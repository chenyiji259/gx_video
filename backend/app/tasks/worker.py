"""异步任务 Worker。

来源文档：doc 03 §8.3（Tool 任务表）、doc 04 §5（任务状态机）

职责：
  TaskWorker 作为 asyncio 后台任务运行，从 Redis 队列消费 ToolJob，
  调用注册好的 handler 执行，并将执行结果回写 ToolJob.status。

架构：
  - Handler Registry：dict[tool_name → async callable]，运行时注册
  - 主循环：BRPOP 取 job_id → 查 DB → 进入 running → 执行 handler → 回写状态
  - 超时：asyncio.wait_for()，超时后当作失败处理
  - 自动重试：retry_count < auto_retry_count 时进入 retrying，重新 push 到队列

Handler 签名：
    async def my_handler(job: ToolJob) -> dict:
        ...
        return {"result_key": "result_value"}  # 存入 output_payload

注册方式：
    from app.tasks import task_worker

    @task_worker.register("audio_analysis")
    async def handle_audio_analysis(job: ToolJob) -> dict:
        ...

启动方式（在 main.py lifespan 中）：
    task = asyncio.create_task(task_worker.run())
    # 关闭时 task.cancel()
"""
from __future__ import annotations

import asyncio
import datetime
from typing import Any, Callable, Coroutine

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.logging import get_logger
from app.core.redis_utils import get_redis_client
from app.domain.states import ProjectStage, TaskStatus
from app.models.workflow import ToolJob
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.services.state_transition_service import state_transition_service

_logger = get_logger("tasks.worker", layer="tool")


# ===========================================================================
# CLASS-03 结构注记：以下所有模块级函数均为 Worker Task Handler。
# 每个 handler 根据工具名向下通过 task_worker.register() 在文件末尾一次注册。
# 为避免循环导入，各 handler 内应延迟导入服务模块。
#
# 超时策略：内部 wait_for 超时后直接重抛 TimeoutError（DESIGN-07 修复），
# 外层 _execute_job 负责 timeout / handler_error 归类。
#
# 内层超时与 Service 层并发锁对齐（16-03 补丁）：
#   单张图片生成类：  2 分钟（_IMAGE_GENERATION_TIMEOUT = 120s）
#   全批分镜生成：   30 分钟（_STORYBOARD_GENERATION_TIMEOUT = 1800s，对齐 StoryboardService 并发锁）
#   视频 clip 生成： 49 分钟（_VIDEO_GENERATION_TIMEOUT = 2980s，略低于外层 job_timeout_seconds=3000s）
#   时间线合成：     10 分钟（_TIMELINE_COMPOSE_TIMEOUT = 600s，对齐 TimelineComposerService 并发锁）
#   音频分析：       45 分钟（_AUDIO_ANALYSIS_TIMEOUT = 2700s，Omni 3 次重试 × 900s，对齐并发锁）
# ===========================================================================

_IMAGE_GENERATION_TIMEOUT: float = 120.0    # 2 分钟 — 单张图片 / 参考图生成
_STORYBOARD_GENERATION_TIMEOUT: float = 1800.0  # 30 分钟 — 全批分镜（16-03 补丁，对齐 StoryboardService 并发锁 1800s）
_VIDEO_GENERATION_TIMEOUT: float = 2980.0   # ~50 分钟 — 视频 clip 批量（16-03 补丁，略低于外层 3000s）
_TIMELINE_COMPOSE_TIMEOUT: float = 600.0    # 10 分钟 — ffmpeg 合成（16-03 补丁，对齐 TimelineComposerService 并发锁 600s）
_AUDIO_ANALYSIS_TIMEOUT: float = 2700.0     # 45 分钟 — 音频分析（16-03 补丁，Omni 3 次重试 × 900s = 2700s）


async def _handle_generate_storyboard(job: ToolJob) -> dict:
    """分镜图生成任务 handler — 内部 30 分钟超时（16-03 补丁：对齐 StoryboardService 并发锁 1800s）。"""
    from app.services.storyboard_service import StoryboardService  # noqa: PLC0415
    project_id: str = job.input_payload.get("project_id", "")
    user_id: str = job.input_payload.get("user_id", "")
    if not project_id or not user_id:
        raise ValueError("generate_storyboard: input_payload 缺少 project_id / user_id")
    svc = StoryboardService()

    from app.services.event_log_service import event_log_service  # noqa: PLC0415
    from app.schemas.event import ProjectEvent  # noqa: PLC0415

    async with UnitOfWork() as uow:
        await event_log_service.emit(
            uow.session,
            ProjectEvent(
                project_id=project_id,
                aggregate_type="project",
                aggregate_id=project_id,
                event_type="storyboard.generating",
                category="workflow",
                payload={"message": "正在生成分镜图，请稍候..."},
            ),
        )

    try:
        version = await asyncio.wait_for(
            svc.generate_and_save(project_id=project_id, user_id=user_id),
            timeout=_STORYBOARD_GENERATION_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # DESIGN-07 修复：直接重抛 TimeoutError，使外层 _execute_job 进入正确的 timeout 分支
        raise
    _logger.info(
        f"generate_storyboard handler 完成: version_id={version.id!r} "
        f"frame_count={version.raw_payload.get('frame_count', 0)}",
        event_type="storyboard_handler_done",
    )
    from app.services.conversation_service import ConversationService  # noqa: PLC0415
    from app.services.decision_service import DecisionService  # noqa: PLC0415

    session = await ConversationService().get_or_create_session(
        project_id=project_id,
        user_id=user_id,
    )
    await DecisionService().create_decision(
        project_id=project_id,
        session_id=session["id"],
        decision_type="confirm_storyboard",
        target_entity_type="project",
        target_entity_id=version.id,
        options_payload=[
            {"id": "confirm", "title": "确认关键帧并开始生成视频"},
            {"id": "regenerate", "title": "重新生成关键帧"},
        ],
        default_option_id="confirm",
    )
    return {
        "storyboard_version_id": version.id,
        "version_no": version.version_no,
        "frame_count": version.raw_payload.get("frame_count", 0),
    }


async def _handle_generate_clips(job: ToolJob) -> dict:
    """视频 clip 生成任务 handler — 内部 ~50 分钟超时（16-03 补丁：略低于外层 job_timeout_seconds=3000s）。"""
    from app.services.clip_service import ClipService  # noqa: PLC0415
    project_id: str = job.input_payload.get("project_id", "")
    user_id: str = job.input_payload.get("user_id", "")
    if not project_id or not user_id:
        raise ValueError("generate_clips: input_payload 缺少 project_id / user_id")
    svc = ClipService()
    try:
        clip_versions = await asyncio.wait_for(
            svc.generate_and_save(project_id=project_id, user_id=user_id),
            timeout=_VIDEO_GENERATION_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # DESIGN-07 修复
        raise
    _logger.info(
        f"generate_clips handler 完成: count={len(clip_versions)}",
        event_type="clips_handler_done",
    )
    from app.repositories.project_repository import ProjectRepository  # noqa: PLC0415
    from app.repositories.unit_of_work import UnitOfWork  # noqa: PLC0415
    from app.storage.local_artifact_store import LocalArtifactStore  # noqa: PLC0415
    from app.storage.path_planner import ArtifactStage  # noqa: PLC0415

    current_stage = ""
    async with UnitOfWork() as uow:
        project = await ProjectRepository(uow.session).get_by_id(project_id)
        current_stage = project.current_stage if project is not None else ""

    total_shots = len(clip_versions)
    failed_shot_count = 0
    try:
        store = LocalArtifactStore(project_id)
        summary_files = store.list_stage_files(ArtifactStage.CLIPS, "clips_summary_*.json")
        if summary_files:
            summary = store.read_json(summary_files[-1])
            total_shots = summary.get("total_shots", total_shots)
            failed_shot_count = summary.get("failed_shot_count", failed_shot_count)
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            f"读取 clips_summary 失败，将使用 handler 返回的成功数: {exc!r}",
            event_type="clips_summary_read_failed",
        )

    return {
        "clip_count": len(clip_versions),
        "succeeded": len(clip_versions),
        "total": total_shots,
        "failed": failed_shot_count,
        "project_stage": current_stage,
    }


async def _handle_generate_timeline(job: ToolJob) -> dict:
    """时间线合成任务 handler — 内部 10 分钟超时（16-03 补丁：对齐 TimelineComposerService 并发锁 600s）。"""
    from app.services.timeline_composer_service import TimelineComposerService  # noqa: PLC0415
    project_id: str = job.input_payload.get("project_id", "")
    user_id: str = job.input_payload.get("user_id", "")
    if not project_id or not user_id:
        raise ValueError("generate_timeline: input_payload 缺少 project_id / user_id")
    svc = TimelineComposerService()
    try:
        tl_version = await asyncio.wait_for(
            svc.compose_and_save(project_id=project_id, user_id=user_id),
            timeout=_TIMELINE_COMPOSE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # DESIGN-07 修复
        raise
    _logger.info(
        f"generate_timeline handler 完成: version_id={tl_version.id!r}",
        event_type="timeline_handler_done",
    )
    return {"timeline_version_id": tl_version.id, "version_no": tl_version.version_no}


async def _handle_analyze_audio(job: ToolJob) -> dict:
    """音频分析任务 handler — 内部 45 分钟超时（16-03 补丁：Omni 3 次重试 × 900s = 2700s，对齐并发锁）。

    执行完整音频分析流水线：
      1. AudioAnalysisService.run_and_save() — 裁切 + librosa beat_track + Omni 并发分析 + 落库

    Omni 在 run_and_save() 中直接输出完整摘要（含 quality_summary），不再需要二次回写。
    Worker 完成后自动触发 DirectorReportService Mode B 汇报（通过 _succeed_job 钉子）。
    """
    from app.services.audio_analysis_service import AudioAnalysisService  # noqa: PLC0415
    from app.services.event_log_service import event_log_service  # noqa: PLC0415
    from app.schemas.event import ProjectEvent  # noqa: PLC0415

    payload = job.input_payload
    project_id: str = payload.get("project_id", "")
    user_id: str = payload.get("user_id", "")

    if not project_id or not user_id:
        raise ValueError("analyze_audio: input_payload 缺少 project_id / user_id")

    # 偏差 1: 发送开始进度 SSE
    async with UnitOfWork() as uow:
        await event_log_service.emit(
            uow.session,
            ProjectEvent(
                project_id=project_id,
                aggregate_type="project",
                aggregate_id=project_id,
                event_type="audio.analysis.progress",
                category="workflow",
                payload={"progress": 10, "message": "开始裁切并提取音频信号..."},
            ),
        )

    svc = AudioAnalysisService()

    try:
        version = await asyncio.wait_for(
            svc.run_and_save(project_id, user_id),
            timeout=_AUDIO_ANALYSIS_TIMEOUT,  # 16-03 补丁：Omni 3 次重试 × 900s = 2700s
        )
    except asyncio.TimeoutError:
        # DESIGN-07 修复
        raise

    # 发送分析完成进度 SSE
    async with UnitOfWork() as uow:
        await event_log_service.emit(
            uow.session,
            ProjectEvent(
                project_id=project_id,
                aggregate_type="project",
                aggregate_id=project_id,
                event_type="audio.analysis.progress",
                category="workflow",
                payload={"progress": 90, "message": "librosa + Omni 并发分析完成，正在落库..."},
            ),
        )

    bpm = float(version.bpm or 0)
    sections = version.section_map or []
    duration = (version.raw_payload or {}).get("signal", {}).get("duration_sec", 0)

    # 偏差 1: 发送完整完成 SSE
    async with UnitOfWork() as uow:
        await event_log_service.emit(
            uow.session,
            ProjectEvent(
                project_id=project_id,
                aggregate_type="project",
                aggregate_id=project_id,
                event_type="audio.analysis.completed",
                category="domain",
                payload={
                    "version_id": version.id,
                    "bpm": bpm,
                    "section_count": len(sections),
                    "duration_sec": duration,
                },
            ),
        )

    _logger.info(
        f"analyze_audio handler 完成: version_id={version.id!r} bpm={bpm}",
        event_type="audio_analysis_handler_done",
    )
    return {
        "audio_analysis_version_id": version.id,
        "version_no": getattr(version, "version_no", 1) or 1,
        "bpm": bpm,
        "section_count": len(sections),
        "duration_sec": duration,
    }


async def _handle_generate_shot_plan(job: ToolJob) -> dict:
    """镜头计划生成任务 handler — 内部 5 分钟超时。"""
    from app.services.shot_plan_persistence_service import ShotPlanPersistenceService  # noqa: PLC0415
    from app.services.event_log_service import event_log_service  # noqa: PLC0415
    from app.schemas.event import ProjectEvent  # noqa: PLC0415

    payload = job.input_payload
    project_id: str = payload.get("project_id", "")
    user_id: str = payload.get("user_id", "")

    if not project_id or not user_id:
        raise ValueError("generate_shot_plan: input_payload 缺少 project_id / user_id")

    # 1. 推送正在生成 SSE
    async with UnitOfWork() as uow:
        await event_log_service.emit(
            uow.session,
            ProjectEvent(
                project_id=project_id,
                aggregate_type="project",
                aggregate_id=project_id,
                event_type="shot_plan.generating",
                category="workflow",
                payload={"message": "正在生成镜头计划，请稍候..."},
            ),
        )

    svc = ShotPlanPersistenceService()
    try:
        scene_version, shot_version, shots = await asyncio.wait_for(
            svc.derive_from_narrative(project_id, user_id),
            timeout=600.0,  # 镜头生成最长 10 分钟 (600 秒)
        )
    except asyncio.TimeoutError:
        # DESIGN-07 修复
        raise

    _logger.info(
        f"generate_shot_plan handler 完成: version_id={shot_version.id!r}",
        event_type="shot_plan_handler_done",
    )

    # 2. 推送生成完成 SSE
    async with UnitOfWork() as uow:
        await event_log_service.emit(
            uow.session,
            ProjectEvent(
                project_id=project_id,
                aggregate_type="project",
                aggregate_id=project_id,
                event_type="shot_plan.completed",
                category="domain",
                payload={
                    "scene_version_id": scene_version.id,
                    "shot_plan_version_id": shot_version.id,
                    "shot_count": len(shots),
                    "scene_count": len(scene_version.raw_payload.get("scenes") or []) if scene_version.raw_payload else 0,
                },
            ),
        )

    return {
        "scene_version_id": scene_version.id,
        "shot_plan_version_id": shot_version.id,
        "shot_plan_version_no": shot_version.version_no,
        "scene_version_no": scene_version.version_no,
        "shot_count": len(shots),
        "scene_count": len(scene_version.raw_payload.get("scenes") or []) if scene_version.raw_payload else 0,
    }


async def _handle_generate_narrative(job: ToolJob) -> dict:
    """叙事剧本生成任务 handler — 内部 2 分钟超时（偏差 2 异步化）。

    偏差 2 修正：
      1. 发送 narrative.generating SSE 事件
      2. 调用 NarrativeScriptService.generate_and_save()
      3. 完成后返回 ArtifactRef 供 DirectorReportService 汇报
    """
    from app.services.narrative_script_service import NarrativeScriptService  # noqa: PLC0415
    from app.services.event_log_service import event_log_service  # noqa: PLC0415
    from app.schemas.event import ProjectEvent  # noqa: PLC0415

    payload = job.input_payload
    project_id: str = payload.get("project_id", "")
    user_id: str = payload.get("user_id", "")

    if not project_id or not user_id:
        raise ValueError("generate_narrative: input_payload 缺少 project_id / user_id")

    # 1. 推送正在生成 SSE
    async with UnitOfWork() as uow:
        await event_log_service.emit(
            uow.session,
            ProjectEvent(
                project_id=project_id,
                aggregate_type="project",
                aggregate_id=project_id,
                event_type="narrative.generating",
                category="workflow",
                payload={"message": "正在构思 MV 叙事剧本，请稍候..."},
            ),
        )

    svc = NarrativeScriptService()
    try:
        version = await asyncio.wait_for(
            svc.generate_and_save(project_id, user_id),
            timeout=120.0,  # 叙事生成最长 2 分钟
        )
    except asyncio.TimeoutError:
        # DESIGN-07 修复
        raise

    _logger.info(
        f"generate_narrative handler 完成: version_id={version.id!r}",
        event_type="narrative_handler_done",
    )

    # 2. 推送生成完成 SSE
    async with UnitOfWork() as uow:
        await event_log_service.emit(
            uow.session,
            ProjectEvent(
                project_id=project_id,
                aggregate_type="project",
                aggregate_id=project_id,
                event_type="narrative.completed",
                category="domain",
                payload={
                    "version_id": version.id,
                    "version_no": version.version_no,
                    "story_arc": version.story_arc[:100],
                },
            ),
        )

    return {
        "narrative_version_id": version.id,
        "version_no": version.version_no,
        "story_arc": version.story_arc,
    }


async def _check_visual_bible_all_completed(project_id: str) -> None:
    """WP5 重写：检查视觉圣经是否所有角色+场景参考图都已完成。

    使用独立表 COUNT 查询（替代 JSONB 遍历），消除并发读取竞争。
    黑盒模式：completed < total 时不推送任何 SSE（无 progress 事件）。

    全部完成时：
      1. 推进项目状态到 visual_bible_ready
      2. 推送 visual_bible.completed SSE（前端收到后拉数据）
      3. 延迟触发 Director 汇总汇报
    """
    from app.repositories.character_reference_repository import CharacterReferenceRepository  # noqa: PLC0415
    from app.repositories.scene_reference_repository import SceneReferenceRepository  # noqa: PLC0415
    from app.repositories.visual_bible_repository import CharacterSetVersionRepository  # noqa: PLC0415
    from app.services.event_log_service import event_log_service  # noqa: PLC0415
    from app.schemas.event import ProjectEvent  # noqa: PLC0415

    try:
        # 获取当前 active version_id
        async with UnitOfWork() as uow:
            csv = await CharacterSetVersionRepository(uow.session).get_active(project_id)
        if csv is None:
            return

        # 用独立表的 COUNT 查询，不再读 JSONB
        async with UnitOfWork() as uow:
            char_repo = CharacterReferenceRepository(uow.session)
            scene_repo = SceneReferenceRepository(uow.session)
            char_done = await char_repo.count_completed(csv.id)
            scene_done = await scene_repo.count_completed(csv.id)
            char_total = await char_repo.count_total(csv.id)
            scene_total = await scene_repo.count_total(csv.id)

        completed = char_done + scene_done
        total = char_total + scene_total

        _logger.info(
            f"视觉圣经完成度检查: {completed}/{total} project={project_id!r}",
            event_type="visual_bible_completion_check",
        )

        if completed < total:
            return  # 还没全部完成，不推送任何进度（黑盒模式）

        # === 全部完成 ===

        # 1. 推进项目状态到 visual_bible_ready
        from app.repositories.project_repository import ProjectRepository  # noqa: PLC0415
        from app.domain.states import ProjectStage  # noqa: PLC0415
        async with UnitOfWork() as uow:
            project = await ProjectRepository(uow.session).get_by_id(project_id)
            if project and project.current_stage != ProjectStage.VISUAL_BIBLE_READY.value:
                await state_transition_service.advance_project(
                    uow.session, project, ProjectStage.VISUAL_BIBLE_READY
                )

        # 2. 推送 visual_bible.completed SSE（前端收到后拉数据）
        async with UnitOfWork() as uow:
            await event_log_service.emit(
                uow.session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="project",
                    aggregate_id=project_id,
                    event_type="visual_bible.completed",
                    category="workflow",
                    payload={
                        "total": total,
                        "characters": char_total,
                        "scenes": scene_total,
                        "message": f"全部 {total} 张参考图已生成完成",
                    },
                ),
            )

        _logger.info(
            f"视觉圣经全部完成: {total} 张参考图 project={project_id!r}",
            event_type="visual_bible_all_completed",
        )

        # 3. 延迟 1 秒后触发一次性 Director 汇报（确保 completed SSE 先到达前端）
        await asyncio.sleep(1.0)
        from app.services.director_report_service import director_report_service  # noqa: PLC0415
        await director_report_service.trigger(
            project_id=project_id,
            task_type="visual_bible_all_completed",
            task_result={"total": total, "characters": char_total, "scenes": scene_total},
        )

    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            f"视觉圣经完成度检查异常（不影响主流程）: {exc!r}",
            event_type="visual_bible_completion_check_error",
        )


async def _handle_generate_character_ref(job: ToolJob) -> dict:
    """角色参考图生成任务 handler — 内部 2 分钟超时。

    WP5 黑盒模式：不再推送逐张 SSE，全部完成后由 _check_visual_bible_all_completed 统一推送。
    同时修复 Bug 2：通过查询独立表获取真实角色名。
    """
    from app.repositories.unit_of_work import UnitOfWork  # noqa: PLC0415
    from app.repositories.character_reference_repository import CharacterReferenceRepository  # noqa: PLC0415
    from app.repositories.visual_bible_repository import CharacterSetVersionRepository  # noqa: PLC0415
    from app.services.visual_bible_service import VisualBibleService  # noqa: PLC0415

    payload = job.input_payload
    project_id: str = payload.get("project_id", "")
    user_id: str = payload.get("user_id", "")
    character_id: str = payload.get("character_id", "")

    if not project_id or not user_id or not character_id:
        raise ValueError("generate_character_ref: input_payload 缺少 project_id / user_id / character_id")

    # Bug 2 修复：从独立表查出角色真实名称
    character_name: str = character_id
    try:
        async with UnitOfWork() as uow:
            csv = await CharacterSetVersionRepository(uow.session).get_active(project_id)
            if csv:
                char_ref = await CharacterReferenceRepository(uow.session).get_by_character_id(
                    csv.id, character_id
                )
                if char_ref:
                    character_name = char_ref.character_name or character_id
    except Exception:  # noqa: BLE001
        pass  # 查询失败时降级为 ID，不阻塞生成

    svc = VisualBibleService()
    try:
        asset_id = await asyncio.wait_for(
            svc.generate_character_reference(
                project_id=project_id,
                user_id=user_id,
                character_id=character_id,
                generation_mode=payload.get("generation_mode"),
                source_image_url=payload.get("source_image_url"),
                source_image_hint=payload.get("source_image_hint"),
                provider_name=payload.get("provider_name"),
            ),
            timeout=_IMAGE_GENERATION_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # DESIGN-07 修复
        raise

    _logger.info(
        f"generate_character_ref handler 完成: "
        f"character={character_id!r} asset={asset_id!r}",
        event_type="character_ref_handler_done",
    )

    # 批次C：角色参考图更新后，异步触发下游 stale 传播
    # 不阻塞 handler 返回，失败不影响任务状态
    # DESIGN-09 补全：使用 _bg_create_task 追踪模块级任务引用
    _bg_create_task(
        _propagate_character_ref_stale(project_id, character_id),
        name=f"char_stale_{job.id}",
    )

    # WP5 黑盒模式：不再推送逐张 visual_bible.character_ref.completed SSE

    # 检查是否所有参考图都完成了（直接 await，确保在 _update_character_ref 提交后读到最新数据）
    await _check_visual_bible_all_completed(project_id)

    return {
        "asset_id": asset_id,
        "character_id": character_id,
        "character_name": character_name,
        "version_no": 1,
    }


async def _handle_generate_scene_ref(job: ToolJob) -> dict:
    """场景参考图生成任务 handler — 内部 2 分钟超时。

    WP5 黑盒模式：不再推送逐张 SSE，全部完成后由 _check_visual_bible_all_completed 统一推送。
    同时修复 Bug 2：通过查询独立表获取真实场景名。
    """
    from app.repositories.unit_of_work import UnitOfWork  # noqa: PLC0415
    from app.repositories.scene_reference_repository import SceneReferenceRepository  # noqa: PLC0415
    from app.repositories.visual_bible_repository import CharacterSetVersionRepository  # noqa: PLC0415
    from app.services.visual_bible_service import VisualBibleService  # noqa: PLC0415

    payload = job.input_payload
    project_id: str = payload.get("project_id", "")
    user_id: str = payload.get("user_id", "")
    scene_id: str = payload.get("scene_id", "")

    if not project_id or not user_id or not scene_id:
        raise ValueError("generate_scene_ref: input_payload 缺少 project_id / user_id / scene_id")

    # Bug 2 修复：从独立表查出场景真实名称
    scene_name: str = scene_id
    try:
        async with UnitOfWork() as uow:
            csv = await CharacterSetVersionRepository(uow.session).get_active(project_id)
            if csv:
                scene_ref = await SceneReferenceRepository(uow.session).get_by_scene_id(
                    csv.id, scene_id
                )
                if scene_ref:
                    scene_name = scene_ref.scene_name or scene_id
    except Exception:  # noqa: BLE001
        pass

    svc = VisualBibleService()
    try:
        asset_id = await asyncio.wait_for(
            svc.generate_scene_reference(
                project_id=project_id,
                user_id=user_id,
                scene_id=scene_id,
                provider_name=payload.get("provider_name"),
            ),
            timeout=_IMAGE_GENERATION_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # DESIGN-07 修复
        raise

    _logger.info(
        f"generate_scene_ref handler 完成: "
        f"scene={scene_id!r} asset={asset_id!r}",
        event_type="scene_ref_handler_done",
    )

    # WP5 黑盒模式：不再推送逐张 visual_bible.scene_ref.completed SSE

    # 检查是否所有参考图都完成了（直接 await，确保在 _update_scene_ref 提交后读到最新数据）
    await _check_visual_bible_all_completed(project_id)

    return {
        "asset_id": asset_id,
        "scene_id": scene_id,
        "scene_name": scene_name,
        "version_no": 1,
    }


async def _handle_generate_costume_ref(job: ToolJob) -> dict:
    """角色造型参考图生成任务 handler。"""
    from app.services.visual_bible_service import VisualBibleService  # noqa: PLC0415

    payload = job.input_payload
    project_id: str = payload.get("project_id", "")
    user_id: str = payload.get("user_id", "")
    character_id: str = payload.get("character_id", "")
    costume_id: str = payload.get("costume_id", "")
    if not project_id or not user_id or not character_id or not costume_id:
        raise ValueError("generate_costume_ref: input_payload 缺少 project_id / user_id / character_id / costume_id")

    svc = VisualBibleService()
    try:
        asset_id = await asyncio.wait_for(
            svc.generate_costume_reference(
                project_id=project_id,
                user_id=user_id,
                character_id=character_id,
                costume_id=costume_id,
                generation_mode=payload.get("generation_mode", "image_to_image"),
                source_image_url=payload.get("source_image_url"),
            ),
            timeout=_IMAGE_GENERATION_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # DESIGN-07 修复
        raise

    # DESIGN-09 补全：使用 _bg_create_task 追踪模块级任务引用
    _bg_create_task(
        _propagate_character_ref_stale(project_id, character_id),
        name=f"costume_stale_{job.id}",
    )
    return {
        "asset_id": asset_id,
        "character_id": character_id,
        "costume_id": costume_id,
        "version_no": 1,
    }


async def _handle_auto_setup_costumes(job: ToolJob) -> dict:
    """多造型自动设置任务 handler。"""
    from app.services.visual_bible_service import VisualBibleService  # noqa: PLC0415

    payload = job.input_payload
    project_id: str = payload.get("project_id", "")
    user_id: str = payload.get("user_id", "")
    if not project_id or not user_id:
        raise ValueError("auto_setup_costumes: input_payload 缺少 project_id / user_id")

    svc = VisualBibleService()
    try:
        result = await asyncio.wait_for(
            svc.auto_analyze_and_setup_costumes(
                project_id=project_id,
                user_id=user_id,
                skip_image_analysis=bool(payload.get("skip_image_analysis", False)),
            ),
            timeout=max(_IMAGE_GENERATION_TIMEOUT, 600.0),
        )
    except asyncio.TimeoutError:
        # DESIGN-07 修复
        raise

    return result


async def _propagate_character_ref_stale(project_id: str, character_id: str) -> None:
    """角色参考图更新后的下游 stale 传播（批次C 新增）。

    异步执行：标记绑定该角色的所有 shot + active clip 为 stale，
    如果项目已进入 shot_plan_ready 以上阶段则回退到 visual_bible_ready。
    失败不影响 Worker 任务状态。
    """
    try:
        from app.repositories.project_repository import ProjectRepository  # noqa: PLC0415
        from app.repositories.unit_of_work import UnitOfWork  # noqa: PLC0415
        from app.services.state_transition_service import state_transition_service  # noqa: PLC0415

        async with UnitOfWork() as uow:
            project = await ProjectRepository(uow.session).get_by_id(project_id)
            if project is None:
                _logger.warning(
                    f"_propagate_character_ref_stale: 项目 {project_id!r} 不存在，跳过",
                    event_type="char_stale_project_not_found",
                )
                return
            await state_transition_service.mark_character_ref_changed_stale(
                uow.session, project, character_id
            )
        _logger.info(
            f"character stale 传播完成: project={project_id!r} character={character_id!r}",
            event_type="character_stale_propagated",
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            f"character stale 传播失败（不影响主流程）: "
            f"project={project_id!r} character={character_id!r} error={exc!r}",
            event_type="character_stale_propagation_failed",
        )


# ---------------------------------------------------------------------------
# DESIGN-09 补全：模块级后台 Task 集合，用于追踪 _propagate_character_ref_stale 等
# 无法放入 TaskWorker._active_tasks 的模块级 fire-and-forget 任务。
# ---------------------------------------------------------------------------
_bg_tasks: set["asyncio.Task"] = set()


def _bg_create_task(coro, *, name: str | None = None) -> "asyncio.Task":
    """创建后台 Task 并追踪引用，防止逃逸异常静默丢失。"""
    task = asyncio.create_task(coro, name=name)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    task.add_done_callback(_on_bg_task_done)
    return task


def _on_bg_task_done(task: "asyncio.Task") -> None:
    """后台 Task done 回调，捕获并记录逃逸异常。"""
    try:
        exc = task.exception()
        if exc is not None:
            _logger.error(
                f"bg Task 逃逸异常: task={task.get_name()!r} exc={exc!r}",
                event_type="bg_task_escaped_exception",
            )
    except (asyncio.CancelledError, asyncio.InvalidStateError):
        pass


# Redis 队列 key（与 dispatcher 保持一致）
_QUEUE_KEY = "vidmuse:task_queue"

# BRPOP 阻塞超时（秒），避免连接永久挂起
_BRPOP_TIMEOUT = 2

# Handler 类型别名
HandlerFn = Callable[[ToolJob], Coroutine[Any, Any, dict]]


class TaskWorker:
    """异步任务 Worker（独立 asyncio 任务）。

    使用全局共享 Redis 池（get_redis_client()），
    BRPOP 配置 _BRPOP_TIMEOUT=2s，超时后将连接归还池，不占用连接。

    典型用法：
        asyncio.create_task(task_worker.run())
    """

    def __init__(self) -> None:
        cfg = get_config().workflow
        self._auto_retry_count: int = cfg.auto_retry_count
        self._job_timeout: int = cfg.job_timeout_seconds
        self._max_concurrent: int = cfg.max_concurrent_jobs
        self._handlers: dict[str, HandlerFn] = {}
        self._running = False
        # DESIGN-09 修复：持存平叓异步 Task 引用，防止逗逸异常静默丢失
        self._active_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ #
    # Handler 注册
    # ------------------------------------------------------------------ #

    def register(self, tool_name: str) -> Callable[[HandlerFn], HandlerFn]:
        """装饰器：注册指定工具名的 handler。

        用法：
            @task_worker.register("audio_analysis")
            async def handle_audio_analysis(job: ToolJob) -> dict:
                ...
        """
        def decorator(fn: HandlerFn) -> HandlerFn:
            if tool_name in self._handlers:
                _logger.warning(
                    f"Worker handler 重复注册: tool={tool_name!r}，旧 handler 将被覆盖",
                    event_type="handler_overridden",
                )
            self._handlers[tool_name] = fn
            _logger.debug(
                f"Worker handler 已注册: tool={tool_name!r}",
                event_type="handler_registered",
            )
            return fn
        return decorator

    def get_handler(self, tool_name: str) -> HandlerFn | None:
        """按工具名获取 handler，未注册返回 None。"""
        return self._handlers.get(tool_name)

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """预热全局 Redis 客户端（充起共享池），并恢复崩溃遗留的僵尸任务。"""
        get_redis_client()  # 确保池已初始化
        _logger.info("TaskWorker 已就绪（共享 Redis 池）", event_type="worker_started")
        await self._recover_stale_jobs()

    async def stop(self) -> None:
        """停止 Worker 循环（Redis 池由 close_redis_client() 在 lifespan 关闭）。"""
        self._running = False
        _logger.info("TaskWorker 已关闭", event_type="worker_stopped")

    async def _recover_stale_jobs(self) -> None:
        """启动时扫描并恢复僵尸任务。

        两类异常场景：

        1. running 僵尸（原有逻辑）：
           Worker 进程在执行 handler 期间崩溃，ToolJob.status 永久卡在 running。
           恢复策略：updated_at 超过 job_timeout_seconds → retrying/failed。

        2. pending 孤儿（Bug 3 修复）：
           ToolJob 已落库（pending）但 push_to_queue 失败，Worker 永远不会收到。
           恢复策略：created_at 超过 job_timeout_seconds 的 pending job
           → 直接重新推入 Redis 队列（不修改状态，不消耗重试次数）。
           阿里系图片生成为同步调用，单帧 3-8s，超时阈值合理，不会误判正常任务。
        """
        from sqlalchemy import select  # noqa: PLC0415

        cutoff = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(
            seconds=self._job_timeout
        )

        # 查询所有超时的 running job
        async with UnitOfWork() as uow:
            result = await uow.session.execute(
                select(ToolJob).where(
                    ToolJob.status == "running",
                    ToolJob.updated_at < cutoff,
                )
            )
            stale_jobs = result.scalars().all()

        if not stale_jobs:
            _logger.info(
                "启动恢复扫描：无僵尸任务",
                event_type="worker_recovery_clean",
            )
            return

        _logger.warning(
            f"启动恢复：发现 {len(stale_jobs)} 个僵尸 running 任务，开始恢复",
            event_type="worker_recovery_start",
        )

        requeue_ids: list[str] = []
        for job in stale_jobs:
            async with UnitOfWork() as uow:
                db_job = await uow.session.get(ToolJob, job.id)
                if db_job is None:
                    continue
                current_retry = db_job.retry_count or 0
                if current_retry < self._auto_retry_count:
                    await state_transition_service.transition_tool_job(
                        uow.session,
                        db_job,
                        TaskStatus.RETRYING,
                        error_info={
                            "code": "crash_recovery",
                            "message": "Worker 崩溃恢复，任务重新入队",
                            "stale_since": job.updated_at.isoformat(),
                        },
                        increment_retry=True,
                    )
                    requeue_ids.append(job.id)
                    _logger.info(
                        f"恢复 ToolJob {job.id!r}: retrying "
                        f"({current_retry + 1}/{self._auto_retry_count}) "
                        f"tool={job.tool_name!r}",
                        event_type="worker_job_recovered",
                    )
                else:
                    await state_transition_service.transition_tool_job(
                        uow.session,
                        db_job,
                        TaskStatus.FAILED,
                        error_info={
                            "code": "crash_recovery_exhausted",
                            "message": "Worker 崩溃恢复，重试次数已耗尽，标记为 failed",
                        },
                    )
                    _logger.warning(
                        f"恢复 ToolJob {job.id!r}: failed（重试 {current_retry} 次已耗尽）"
                        f" tool={job.tool_name!r}",
                        event_type="worker_job_recovery_exhausted",
                    )

        # DB commit 完成后统一重新入队（与 _handle_failure 中的策略一致）
        for job_id in requeue_ids:
            await get_redis_client().lpush(_QUEUE_KEY, job_id)

        _logger.warning(
            f"启动恢复完成：{len(requeue_ids)}/{len(stale_jobs)} 个任务重新入队",
            event_type="worker_recovery_done",
        )

        # ---- Bug 3 修复：恢复 pending 孤儿任务（Redis push 失败遗留）------------------
        # pending + created_at 超过 job_timeout_seconds → 视为入队失败的孤儿
        # 直接重推 Redis，不修改状态、不消耗重试次数
        async with UnitOfWork() as uow:
            orphan_result = await uow.session.execute(
                select(ToolJob).where(
                    ToolJob.status == "pending",
                    ToolJob.created_at < cutoff,
                )
            )
            orphan_jobs = orphan_result.scalars().all()

        if not orphan_jobs:
            return

        _logger.warning(
            f"启动恢复：发现 {len(orphan_jobs)} 个 pending 孤儿任务，重新入队",
            event_type="worker_recovery_pending_orphans",
        )
        requeued_orphans = 0
        for job in orphan_jobs:
            try:
                await get_redis_client().lpush(_QUEUE_KEY, job.id)
                requeued_orphans += 1
                _logger.info(
                    f"孤儿任务重新入队: job_id={job.id!r} tool={job.tool_name!r}",
                    event_type="worker_orphan_requeued",
                )
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    f"孤儿任务重新入队失败: job_id={job.id!r} error={exc!r}",
                    event_type="worker_orphan_requeue_failed",
                )
        _logger.warning(
            f"pending 孤儿恢复完成：{requeued_orphans}/{len(orphan_jobs)} 个重新入队",
            event_type="worker_orphan_recovery_done",
        )

    # ------------------------------------------------------------------ #
    # 主循环
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        """主循环：持续消费队列，直到任务被取消。

        使用信号量控制并发度（max_concurrent_jobs）。
        """
        await self.start()
        self._running = True
        semaphore = asyncio.Semaphore(self._max_concurrent)

        _logger.info(
            f"TaskWorker 开始运行（max_concurrent={self._max_concurrent}, "
            f"timeout={self._job_timeout}s, retry={self._auto_retry_count}）",
            event_type="worker_loop_start",
        )

        try:
            while self._running:
                try:
                    job_id = await self._brpop_job_id()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    _logger.error(
                        f"BRPOP 失败: {exc!r}",
                        event_type="worker_brpop_error",
                    )
                    await asyncio.sleep(1)
                    continue

                if job_id is None:
                    continue  # BRPOP timeout，继续轮询

                # 并发执行 job（信号量控制上限）
                # DESIGN-09 修复：持存引用并添加 done_callback，防止逗逸异常静默丢失
                _t = asyncio.create_task(self._run_with_semaphore(semaphore, job_id))
                self._active_tasks.add(_t)
                _t.add_done_callback(self._active_tasks.discard)
                _t.add_done_callback(self._on_task_done)

        except asyncio.CancelledError:
            _logger.info("TaskWorker 任务已取消", event_type="worker_cancelled")
            raise
        finally:
            await self.stop()

    async def _brpop_job_id(self) -> str | None:
        """从 Redis 队列阻塞取一个 job_id，超时返回 None。

        redis-py 5.x BRPOP 返回 (key, value) tuple，失败返回 None。
        使用 asyncio.to_thread 包装阻塞调用，在协程中使用。
        """
        result = await get_redis_client().brpop(_QUEUE_KEY, timeout=_BRPOP_TIMEOUT)
        if result is None:
            return None
        _, job_id = result  # result = (queue_key, job_id)
        return job_id

    async def _run_with_semaphore(
        self,
        semaphore: asyncio.Semaphore,
        job_id: str,
    ) -> None:
        """在信号量保护下执行单个 job。"""
        async with semaphore:
            await self._execute_job(job_id)

    async def _execute_job(self, job_id: str) -> None:
        """执行单个 ToolJob 的完整生命周期。"""
        # 1. 查 DB 获取 job
        job = await self._load_job(job_id)
        if job is None:
            _logger.warning(
                f"ToolJob 不存在: id={job_id!r}，忽略",
                event_type="worker_job_not_found",
            )
            return

        if job.status not in ("pending", "retrying"):
            _logger.warning(
                f"ToolJob {job_id!r} 状态为 {job.status!r}，跳过执行",
                event_type="worker_job_skipped",
            )
            return

        # 2. 查 handler
        handler = self.get_handler(job.tool_name)
        if handler is None:
            await self._fail_job(
                job,
                error={"code": "no_handler", "message": f"未注册 tool={job.tool_name!r} 的 handler"},
            )
            return

        # 3. 标记 running（异常保护：防止 StateTransitionError 从此处逃逸）
        try:
            await self._set_running(job)
        except Exception as set_run_exc:  # noqa: BLE001
            _logger.error(
                f"ToolJob {job_id!r} _set_running 失败，直接标记 failed: {set_run_exc!r}",
                event_type="worker_set_running_failed",
            )
            await self._fail_job(
                job, error={"code": "set_running_failed", "message": repr(set_run_exc)}
            )
            return

        # 4. 执行 handler（含超时控制）
        try:
            output = await asyncio.wait_for(
                handler(job),
                timeout=float(self._job_timeout),
            )
            await self._succeed_job(job, output=output or {})

        except asyncio.TimeoutError as exc:
            # DESIGN-07 修正：内层 handler wait_for 超时后 re-raise，外层在此捕获。
            # exc.__context__ 可追溯实际超时阈值（handler 内设定）；error_payload 记录两层阈值。
            inner_msg = str(exc) if str(exc) else f"handler 内部超时（上限 {self._job_timeout}s 兜底）"
            _logger.warning(
                f"ToolJob {job_id!r} 超时: {inner_msg}",
                event_type="worker_job_timeout",
            )
            await self._handle_failure(
                job,
                error={"code": "timeout", "message": inner_msg},
            )

        except Exception as exc:  # noqa: BLE001
            _logger.error(
                f"ToolJob {job_id!r} 执行异常: {exc!r}",
                event_type="worker_job_error",
            )
            await self._handle_failure(
                job,
                error={"code": "handler_error", "message": repr(exc)},
            )

    # ------------------------------------------------------------------ #
    # 状态回写辅助方法
    # ------------------------------------------------------------------ #

    async def _load_job(self, job_id: str) -> ToolJob | None:
        """从 DB 加载 ToolJob。"""
        async with UnitOfWork() as uow:
            result = await uow.session.execute(
                select(ToolJob).where(ToolJob.id == job_id)
            )
            job = result.scalar_one_or_none()
        return job

    async def _set_running(self, job: ToolJob) -> None:
        """将 ToolJob 标记为 running。"""
        async with UnitOfWork() as uow:
            db_job = await uow.session.get(ToolJob, job.id)
            if db_job is None:
                return
            await state_transition_service.transition_tool_job(
                uow.session, db_job, TaskStatus.RUNNING
            )

    async def _succeed_job(self, job: ToolJob, *, output: dict) -> None:
        """将 ToolJob 标记为 succeeded，写入 output_payload。"""
        async with UnitOfWork() as uow:
            db_job = await uow.session.get(ToolJob, job.id)
            if db_job is None:
                return
            await state_transition_service.transition_tool_job(
                uow.session,
                db_job,
                TaskStatus.SUCCEEDED,
                output_payload=output,
            )
        _logger.info(
            f"ToolJob {job.id!r} 执行成功",
            event_type="worker_job_succeeded",
        )

        # WP5: 角色/场景参考图不逐张触发 Director 汇报，只在 all_completed 时汇总一次
        _SKIP_DIRECTOR_REPORT_TOOLS = frozenset(["generate_character_ref", "generate_scene_ref"])
        if job.tool_name not in _SKIP_DIRECTOR_REPORT_TOOLS:
            from app.services.director_report_service import director_report_service  # noqa: PLC0415
            try:
                await director_report_service.trigger(
                    project_id=job.project_id,
                    task_type=job.tool_name,
                    task_result=output,
                )
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    f"Director 汇报失败（不影响任务成功）: job={job.id!r} exc={exc!r}",
                    event_type="director_report_in_succeed_failed",
                )

    async def _handle_failure(self, job: ToolJob, *, error: dict) -> None:
        """处理执行失败：可重试则进入 retrying + 重新入队，否则标记 failed。"""
        should_requeue = False

        async with UnitOfWork() as uow:
            db_job = await uow.session.get(ToolJob, job.id)
            if db_job is None:
                return

            current_retry = db_job.retry_count or 0
            if current_retry < self._auto_retry_count:
                # 进入 retrying，递增计数（重新入队在事务 commit 后执行，防止竞态）
                await state_transition_service.transition_tool_job(
                    uow.session,
                    db_job,
                    TaskStatus.RETRYING,
                    error_info=error,
                    increment_retry=True,
                )
                should_requeue = True
                _logger.info(
                    f"ToolJob {job.id!r} 重试 ({current_retry + 1}/{self._auto_retry_count})",
                    event_type="worker_job_retrying",
                )
            else:
                await self._fail_job(db_job, error=error, session=uow.session)

        # UoW commit 完成后才推队列：先落库再入队，Worker 收到消息时 DB 状态已可见
        if should_requeue:
            await self._requeue_job(job.id)

    async def _fail_job(
        self,
        job: ToolJob,
        *,
        error: dict,
        session: AsyncSession | None = None,
    ) -> None:
        """将 ToolJob 标记为 failed（无重试机会）。"""
        if session is not None:
            # 在已有 session 中执行
            await state_transition_service.transition_tool_job(
                session, job, TaskStatus.FAILED, error_info=error
            )
        else:
            async with UnitOfWork() as uow:
                db_job = await uow.session.get(ToolJob, job.id)
                if db_job is None:
                    return
                await state_transition_service.transition_tool_job(
                    uow.session, db_job, TaskStatus.FAILED, error_info=error
                )
                await self._mark_project_failed_for_storyboard_job(
                    db_job,
                    error=error,
                    session=uow.session,
                )
                job = db_job
        if session is not None:
            await self._mark_project_failed_for_storyboard_job(
                job,
                error=error,
                session=session,
            )
        _logger.warning(
            f"ToolJob {job.id!r} 标记为 failed: {error!r}",
            event_type="worker_job_failed",
        )

        # 发送失败 SSE 事件，通知前端停止 spinner
        await self._emit_failure_sse(job, error)

    async def _mark_project_failed_for_storyboard_job(
        self,
        job: ToolJob,
        *,
        error: dict,
        session: AsyncSession,
    ) -> None:
        """分镜/故事大图任务最终失败时，同步落项目失败态，供前端进入恢复入口。"""
        if job.tool_name != "generate_storyboard":
            return

        payload_data = job.input_payload or {}
        project_id = payload_data.get("project_id", "")
        if not project_id:
            return

        project = await ProjectRepository(session).get_by_id(project_id)
        if project is None or project.current_stage == ProjectStage.FAILED.value:
            return

        try:
            await state_transition_service.advance_project(
                session,
                project,
                ProjectStage.FAILED,
                emit_event=True,
                correlation_id=job.id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                f"generate_storyboard 失败后项目阶段标记 failed 失败: "
                f"project_id={project_id!r}, job_id={job.id!r}, error={error!r}, exc={exc!r}",
                event_type="worker_project_failed_transition_error",
            )

    async def _emit_failure_sse(self, job: ToolJob, error: dict) -> None:
        """若 job 属于图片生成类型，发送失败 SSE 事件通知前端。"""
        try:
            tool = job.tool_name
            payload_data = job.input_payload or {}
            project_id = payload_data.get("project_id", "")
            if not project_id or tool not in (
                "generate_character_ref",
                "generate_scene_ref",
                "generate_storyboard",
            ):
                return

            if tool == "generate_storyboard":
                event_type = "storyboard.failed"
                event_payload = {
                    "job_id": job.id,
                    "error": str(error.get("message", ""))[:500],
                    "code": str(error.get("code", "storyboard_failed")),
                    "retry_count": job.retry_count,
                }
            elif tool == "generate_character_ref":
                event_type = "visual_bible.character_ref.failed"
                event_payload: dict[str, Any] = {
                    "character_id": payload_data.get("character_id", ""),
                    "character_name": payload_data.get("character_name", ""),
                    "error": str(error.get("message", ""))[:200],
                }
            else:
                event_type = "visual_bible.scene_ref.failed"
                event_payload = {
                    "scene_id": payload_data.get("scene_id", ""),
                    "scene_name": payload_data.get("scene_name", ""),
                    "error": str(error.get("message", ""))[:200],
                }

            from app.services.event_log_service import event_log_service  # noqa: PLC0415
            from app.schemas.event import ProjectEvent  # noqa: PLC0415

            async with UnitOfWork() as uow:
                await event_log_service.emit(
                    uow.session,
                    ProjectEvent(
                        project_id=project_id,
                        aggregate_type="project",
                        aggregate_id=project_id,
                        event_type=event_type,
                        category="workflow",
                        payload=event_payload,
                    ),
                )
        except Exception as sse_exc:  # noqa: BLE001
            _logger.warning(
                f"发送失败 SSE 事件异常: {sse_exc!r}",
                event_type="fail_sse_error",
            )

    async def _requeue_job(self, job_id: str) -> None:
        """将 job_id 重新推入 Redis 队列（在 DB commit 之后调用）。"""
        await get_redis_client().lpush(_QUEUE_KEY, job_id)
        _logger.debug(
            f"ToolJob {job_id!r} 重新入队",
            event_type="worker_job_requeued",
        )

    def _on_task_done(self, task: asyncio.Task) -> None:
        """DESIGN-09 修复： Task done 回调，捕获并记录逗逸异常，防止静默丢失。"""
        try:
            exc = task.exception()
            if exc is not None:
                _logger.error(
                    f"Task 逗逸异常（未被应用层捕获）: task={task.get_name()!r} exc={exc!r}",
                    event_type="worker_task_escaped_exception",
                )
        except (asyncio.CancelledError, asyncio.InvalidStateError):
            pass


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

task_worker = TaskWorker()

# doc11 批次3：图生成 / 视频生成 / 时间线合成
task_worker.register("generate_storyboard")(_handle_generate_storyboard)
task_worker.register("generate_clips")(_handle_generate_clips)
task_worker.register("generate_timeline")(_handle_generate_timeline)
task_worker.register("generate_shot_plan")(_handle_generate_shot_plan)
# doc11 批次2 + 修复：视觉圣经参考图生成（已异步化）
task_worker.register("generate_character_ref")(_handle_generate_character_ref)
task_worker.register("generate_scene_ref")(_handle_generate_scene_ref)
task_worker.register("generate_costume_ref")(_handle_generate_costume_ref)
task_worker.register("auto_setup_costumes")(_handle_auto_setup_costumes)
# 批次C：音频分析异步化
task_worker.register("analyze_audio")(_handle_analyze_audio)
# 偏差 2：叙事剧本生成异步化
task_worker.register("generate_narrative")(_handle_generate_narrative)
