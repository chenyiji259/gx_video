"""Clip 生成服务（Clip Service）。

来源文档：doc 09 任务 11-04

职责：
  将 storyboard_ready 阶段的 shots 转化为视频 clip，形成第一批视频产物。

流程：
  1. 前置校验：项目处于 storyboard_ready 或 clips_ready（允许重生成）
  2. 读取 active ShotPlanVersion，获取所有 storyboard_ready 状态的 shots
  3. 3 并发处理（代码驱动，非导演调度）：
     a. 读取对应 storyboard frame 的 asset（作为 image_to_video 的起始帧）
     b. 调用 PromptCompilerService.compile_for_shot() → PromptBundle（video）
     c. 调用 VideoGenerationTool.generate_for_bundle() → asset_id
     d. 写 clip_versions，标记 is_active=True
     e. 更新 shot.status = 'clip_ready'
     f. 推送 SSE 事件（clip.shot.completed）
  4. 更新 projects.active_clip_* 指针（通过 shot 逐个激活）
  5. 写本地 JSON 快照（08_clips/）
  6. 推进项目状态 → clips_ready

并发策略：
  单用户 3 并发限制，完成一个释放一个，由 asyncio.Semaphore 控制。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from app.core.logging import get_project_logger
from app.domain.states import ProjectStage
from app.models.clip import ClipVersion
from app.providers.video.base import VideoGenerationError
from app.repositories.asset_repository import AssetRepository
from app.repositories.clip_repository import ClipRepository
from app.repositories.planning_repositories import (
    ShotPlanRepository,
    ShotRepository,
)
from app.repositories.project_repository import ProjectRepository
from app.repositories.storyboard_repositories import (
    StoryboardFrameRepository,
    StoryboardVersionRepository,
)
from app.repositories.unit_of_work import UnitOfWork
from app.services.concurrency_guard_service import ConcurrencyError, concurrency_guard
from app.services.prompt_compiler_service import PromptCompilerError, PromptCompilerService
from app.schemas.event import ProjectEvent
from app.services.event_log_service import event_log_service
from app.services.state_transition_service import state_transition_service
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.path_planner import ArtifactStage
from app.tools.video_generation_tool import VideoGenerationTool
from app.utils.ids import generate_ulid


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class ClipGenerationError(Exception):
    """Clip 生成业务异常。"""

    def __init__(self, message: str, code: str = "clip_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# ClipService
# ---------------------------------------------------------------------------

class ClipService:
    """Clip 生成服务：storyboard_ready shots → clip_versions。"""

    def __init__(self) -> None:
        self._compiler = PromptCompilerService()
        self._video_tool = VideoGenerationTool()

    async def generate_and_save(
        self,
        project_id: str,
        user_id: str,
    ) -> list[ClipVersion]:
        """执行完整 clip 批量生成流程。

        Args:
            project_id: 目标项目 ID。
            user_id:    当前用户 ID（项目归属校验）。

        Returns:
            所有成功生成并激活的 ClipVersion 列表。

        Raises:
            ClipGenerationError: 前置条件不满足、shot plan 缺失、状态非法。
        """
        logger = get_project_logger(project_id, module="services.clip")

        # 16-02：锁超时改为动态计算。3 并发模式下，耗时约为 ceil(shots/3) × 每shot时间。
        _estimated_shots = await self._estimate_shot_count(project_id)
        _lock_timeout = max(660, (_estimated_shots // 3 + 1) * 600)  # 每批最多 10 分钟
        logger.info(
            f"Clip 并发锁超时设定: estimated_shots={_estimated_shots} lock_timeout={_lock_timeout}s",
            event_type="clip_lock_timeout_set",
        )
        try:
            async with concurrency_guard.project_lock(project_id, timeout_sec=_lock_timeout):
                return await self._generate_locked(project_id, user_id)
        except ConcurrencyError as exc:
            raise ClipGenerationError(str(exc), code="concurrency_conflict") from exc

    async def _generate_locked(
        self,
        project_id: str,
        user_id: str,
    ) -> "list[ClipVersion]":
        """加锁后的实际执行体。"""
        logger = get_project_logger(project_id, module="services.clip")

        # ---- 步骤 1: 读取并校验项目上下文 ----------------------------------------
        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise ClipGenerationError("项目不存在", code="project_not_found")

            allowed_stages = {
                ProjectStage.STORYBOARD_READY.value,
                ProjectStage.CLIPS_READY.value,
                ProjectStage.FAILED.value,
            }
            if project.current_stage not in allowed_stages:
                raise ClipGenerationError(
                    f"当前阶段 {project.current_stage!r} 不允许生成 clip",
                    code="invalid_stage",
                )

            # 读取需要处理的 shots。
            # 批量视频生成失败后，shot 会被标记为 failed；再次点击“开始生成视频”
            # 应允许这些 failed shots 重新进入批量生成，而不是把流程锁死。
            shot_repo = ShotRepository(session)
            shot_plan = await ShotPlanRepository(session).get_active(project_id)
            if shot_plan is None:
                raise ClipGenerationError(
                    "未找到 active shot plan", code="no_shot_plan"
                )
            shot_plan_version_id = shot_plan.id

            all_shots = await shot_repo.list_by_project(project_id)
            shots_to_process = [
                s for s in all_shots
                if s.status in ("storyboard_ready", "failed")
                and s.shot_plan_version_id == shot_plan_version_id
            ]

            # 读取九宫格边界帧映射：
            #   shot i = cell(i+1) -> cell(i+2)
            # 每张九宫格 9 个 cell 产生 8 个视频 shot；跨九宫格时下一张 cell1
            # 物理复用上一张 cell9，因此边界帧天然连续。
            sb_version = await StoryboardVersionRepository(session).get_active(project_id)
            asset_repo = AssetRepository(session)
            frame_map: dict[str, str] = {}
            next_frame_map: dict[str, str | None] = {}
            next_shot_desc_map: dict[str, str | None] = {}
            sorted_shots = sorted(shots_to_process, key=lambda s: s.shot_index)
            if sb_version and sb_version.raw_payload:
                cell_asset_ids: set[str] = set()
                boundary_by_shot_index: dict[int, tuple[str | None, str | None]] = {}
                for grid in (sb_version.raw_payload.get("grids") or []):
                    grid_index = int(grid.get("grid_index") or 1)
                    base_shot_index = (grid_index - 1) * 8
                    cells = {
                        int(cell.get("cell_position") or 0): cell.get("asset_id")
                        for cell in (grid.get("cells") or [])
                    }
                    for offset in range(8):
                        first_asset_id = cells.get(offset + 1)
                        last_asset_id = cells.get(offset + 2)
                        shot_index = base_shot_index + offset
                        boundary_by_shot_index[shot_index] = (first_asset_id, last_asset_id)
                        if first_asset_id:
                            cell_asset_ids.add(first_asset_id)
                        if last_asset_id:
                            cell_asset_ids.add(last_asset_id)

                assets = await asset_repo.list_by_ids(list(cell_asset_ids))
                asset_url_map = {a.id: a.storage_uri for a in assets if a.storage_uri}

                for shot in sorted_shots:
                    first_asset_id, last_asset_id = boundary_by_shot_index.get(
                        shot.shot_index, (None, None)
                    )
                    frame_map[shot.id] = asset_url_map.get(first_asset_id or "", "")
                    next_frame_map[shot.id] = asset_url_map.get(last_asset_id or "") or None
                    next_shot_desc_map[shot.id] = shot.subject or shot.location or shot.lyric_text

        logger.info(
            f"Clip 上下文加载完成: shots={len(shots_to_process)} "
            f"有起始帧的shots={len(frame_map)}",
            event_type="clip_context_loaded",
        )

        if not shots_to_process:
            raise ClipGenerationError(
                "没有可生成的 shot（既无 storyboard_ready，也无 failed），可能 clip 已是最新版本",
                code="no_shots_to_process",
            )

        logger.info(
            f"Clip 生成开始: {len(shots_to_process)} 个 shot（已移除 credits 预占）",
            event_type="clip_generation_start",
        )

        # ---- 步骤 2: 3 并发处理 shots ----------------------------------------
        clip_versions: list[ClipVersion] = []
        clip_metadata: list[dict[str, Any]] = []
        _MAX_CONCURRENT_CLIPS = 3  # 单用户并发上限

        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_CLIPS)

        async def _process_with_sem(shot: Any) -> tuple[ClipVersion | None, float]:
            async with semaphore:
                t0 = time.monotonic()
                # 推送 clip.shot.started SSE
                try:
                    async with UnitOfWork() as ev_uow:
                        await event_log_service.emit(
                            ev_uow.session,
                            ProjectEvent(
                                project_id=project_id,
                                aggregate_type="project",
                                aggregate_id=project_id,
                                event_type="clip.shot.started",
                                category="workflow",
                                payload={
                                    "shot_id": shot.id,
                                    "shot_index": shot.shot_index,
                                },
                            ),
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        f"SSE clip.shot.started 发送失败: {exc}",
                        event_type="sse_emit_failed",
                    )
                clip = await self._process_single_shot(
                    shot=shot,
                    project_id=project_id,
                    reference_image_url=frame_map.get(shot.id),
                    last_frame_url=next_frame_map.get(shot.id),
                    last_frame_description=next_shot_desc_map.get(shot.id),
                    logger=logger,
                )
                elapsed = round(time.monotonic() - t0, 2)

                # 失败时推送 clip.shot.failed SSE
                if clip is None:
                    try:
                        async with UnitOfWork() as ev_uow:
                            await event_log_service.emit(
                                ev_uow.session,
                                ProjectEvent(
                                    project_id=project_id,
                                    aggregate_type="project",
                                    aggregate_id=project_id,
                                    event_type="clip.shot.failed",
                                    category="domain",
                                    payload={
                                        "shot_id": shot.id,
                                        "shot_index": shot.shot_index,
                                    },
                                ),
                            )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            f"SSE clip.shot.failed 发送失败: {exc}",
                            event_type="sse_emit_failed",
                        )

                return clip, elapsed

        # 并发分发所有 shots，Semaphore 限制同时进行的数量为 3
        results = await asyncio.gather(
            *[_process_with_sem(shot) for shot in shots_to_process],
            return_exceptions=True,
        )

        # 收集结果
        for shot, result in zip(shots_to_process, results):
            if isinstance(result, Exception):
                logger.warning(
                    f"shot[{shot.shot_index}] 并发执行异常: {result}",
                    event_type="clip_shot_concurrent_error",
                )
                continue
            clip, elapsed = result
            if clip is not None:
                clip_versions.append(clip)
                clip_metadata.append({
                    "shot_id": shot.id,
                    "shot_index": shot.shot_index,
                    "clip_version_id": clip.id,
                    "asset_id": clip.asset_id,
                    "duration_ms": clip.duration_ms,
                    "generation_time_sec": elapsed,
                })

        total_shots = len(shots_to_process)
        failed_shot_count = total_shots - len(clip_versions)

        # ---- 步骤 3: 推进项目状态 ----------------------------------------
        await self._advance_project(
            project_id,
            clip_metadata,
            total_shots=total_shots,
            failed_shot_count=failed_shot_count,
            logger=logger,
        )

        # 推送 clips.all_completed SSE，通知前端全部 shot 生成完成
        try:
            async with UnitOfWork() as ev_uow:
                await event_log_service.emit(
                    ev_uow.session,
                    ProjectEvent(
                        project_id=project_id,
                        aggregate_type="project",
                        aggregate_id=project_id,
                        event_type="clips.all_completed",
                        category="domain",
                        payload={
                            "total": total_shots,
                            "succeeded": len(clip_versions),
                            "failed": failed_shot_count,
                        },
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"SSE clips.all_completed 发送失败: {exc}",
                event_type="sse_emit_failed",
            )

        logger.info(
            f"Clip 生成完成: {len(clip_versions)}/{len(shots_to_process)} 成功",
            event_type="clip_generation_done",
        )
        return clip_versions

    # ------------------------------------------------------------------
    # 单 shot 处理
    # ------------------------------------------------------------------

    async def _process_single_shot(
        self,
        *,
        shot: Any,
        project_id: str,
        reference_image_url: str | None,
        last_frame_url: str | None,
        last_frame_description: str | None,
        logger: Any,
    ) -> ClipVersion | None:
        """处理单个 shot：编译 video prompt → 生成 clip → 写 clip_versions。"""
        shot_id = shot.id
        shot_index = shot.shot_index

        try:
            # 决定生成模式
            mode = "image_to_video" if reference_image_url else "text_to_video"
            logger.debug(
                f"shot[{shot_index}] 生成模式: mode={mode!r} "
                f"has_reference={'是' if reference_image_url else '否'}",
                event_type="clip_mode_resolved",
            )

            async with UnitOfWork() as uow:
                bundle = await self._compiler.compile_for_shot(
                    session=uow.session,
                    shot_id=shot_id,
                    project_id=project_id,
                    target_type="shot_clip",
                    generation_mode=mode,  # 传入实际模式，供 compile_video_prompt 模板使用
                    first_frame_description=shot.subject or shot.location or shot.lyric_text,
                    last_frame_description=last_frame_description,
                )
                logger.debug(
                    f"shot[{shot_index}] video prompt 编译完成: bundle_id={bundle.bundle_id!r} "
                    f"provider={bundle.provider!r}",
                    event_type="clip_prompt_compiled",
                )

            # 视频生成（不在 UoW 内，避免长时间持有 DB 连接）
            asset_id, actual_duration_ms = await self._video_tool.generate_for_bundle(
                bundle=bundle,
                project_id=project_id,
                mode=mode,
                shot_index=shot_index,
                reference_image_url=reference_image_url,
                last_frame_url=last_frame_url,
            )
            # 使用 provider 实际返回的视频时长； provider 未返回时回落到计划值
            duration_ms = actual_duration_ms if actual_duration_ms else (shot.duration_ms or 5000)

            # 落库 clip_versions
            async with UnitOfWork() as uow2:
                clip_repo = ClipRepository(uow2.session)
                await clip_repo.deactivate_all(shot_id)
                version_no = await clip_repo.get_next_version_no(shot_id)

                clip = ClipVersion(
                    id=generate_ulid(),
                    project_id=project_id,
                    shot_id=shot_id,
                    version_no=version_no,
                    provider=bundle.provider,
                    generation_mode=mode,
                    asset_id=asset_id,
                    duration_ms=duration_ms,
                    prompt_bundle_id=bundle.bundle_id,
                    status="ready",
                    is_active=True,
                )
                await clip_repo.add(clip)

                # 更新 shot 状态
                shot_orm = await ShotRepository(uow2.session).get_by_id(shot_id)
                if shot_orm is not None:
                    shot_orm.status = "clip_ready"
                    uow2.session.add(shot_orm)

                await uow2.flush()
                await uow2.session.refresh(clip)

            logger.info(
                f"shot[{shot_index}] clip 生成完成: asset_id={asset_id!r}",
                event_type="clip_shot_done",
            )

            # 推送 per-clip SSE，让前端实时感知每个 clip 就绪
            try:
                async with UnitOfWork() as ev_uow:
                    ev_asset = await AssetRepository(ev_uow.session).get_by_id(asset_id)
                    await event_log_service.emit(
                        ev_uow.session,
                    ProjectEvent(
                            project_id=project_id,
                            aggregate_type="project",
                            aggregate_id=project_id,
                            event_type="clip.shot.completed",
                            category="domain",
                            payload={
                                "shot_id": shot_id,
                                "shot_index": shot_index,
                                "start_ms": shot.start_ms,
                                "end_ms": shot.end_ms,
                                "duration_ms": duration_ms,
                                "storage_uri": ev_asset.storage_uri if ev_asset else None,
                                "clip_version_id": clip.id,
                            },
                        ),
                    )
            except Exception:  # noqa: BLE001
                pass  # SSE 失败不阻断主流程

            return clip

        except (PromptCompilerError, VideoGenerationError) as exc:
            logger.warning(
                f"shot[{shot_index}] clip 生成失败（跳过）: {exc}",
                event_type="clip_shot_failed",
            )
            try:
                async with UnitOfWork() as uow_fail:
                    s = await ShotRepository(uow_fail.session).get_by_id(shot_id)
                    if s is not None:
                        s.status = "failed"
                        uow_fail.session.add(s)
            except Exception:
                pass
            return None

        except Exception as exc:
            logger.warning(
                f"shot[{shot_index}] clip 意外错误（跳过）: {exc}",
                event_type="clip_shot_unexpected",
            )
            return None

    # ------------------------------------------------------------------
    # 辅助：无锁估算 shots 数量（16-02）
    # ------------------------------------------------------------------

    async def _estimate_shot_count(self, project_id: str) -> int:
        """锁外快速估算可重新生成的 shots 数量。

        仅用于动态计算并发锁超时，不要求 100% 准确。
        _generate_locked() 内部会再次读取于一致性。
        """
        try:
            async with UnitOfWork() as uow:
                shot_plan = await ShotPlanRepository(uow.session).get_active(project_id)
                if shot_plan is None:
                    return 0
                all_shots = await ShotRepository(uow.session).list_by_project(project_id)
                return len([
                    s for s in all_shots
                    if s.status in ("storyboard_ready", "failed")
                    and s.shot_plan_version_id == shot_plan.id
                ])
        except Exception:
            return 0  # 估算失败时回落默认小子

    # ------------------------------------------------------------------
    # 推进项目状态
    # ------------------------------------------------------------------

    async def _advance_project(
        self,
        project_id: str,
        clip_metadata: list[dict[str, Any]],
        *,
        total_shots: int,
        failed_shot_count: int,
        logger: Any,
    ) -> None:
        """落本地快照并推进项目状态。

        规则：
          - 全部成功 → clips_ready
          - 任意失败 → failed（允许后续整阶段重试）
        """
        succeeded_count = len(clip_metadata)
        stage_failed = failed_shot_count > 0

        async with UnitOfWork() as uow:
            session = uow.session
            project = await ProjectRepository(session).get_by_id(project_id)
            if project:
                target_stage = ProjectStage.FAILED if stage_failed else ProjectStage.CLIPS_READY
                if project.current_stage != target_stage.value:
                    await state_transition_service.advance_project(
                        session, project, target_stage
                    )
                if stage_failed:
                    await event_log_service.emit(
                        session,
                        ProjectEvent(
                            project_id=project_id,
                            aggregate_type="project",
                            aggregate_id=project_id,
                            event_type="clips.stage.failed",
                            category="domain",
                            payload={
                                "total": total_shots,
                                "succeeded": succeeded_count,
                                "failed": failed_shot_count,
                                "retry_action": "generate_clips",
                                "message": (
                                    "视频生成阶段失败：部分镜头生成失败。"
                                    "请处理上游账户/配额问题后重试整个视频生成阶段。"
                                ),
                            },
                        ),
                    )

        # 写本地快照
        store = LocalArtifactStore(project_id)
        store.write_json(
            ArtifactStage.CLIPS,
            "clips_summary",
            {
                "clip_count": succeeded_count,
                "total_shots": total_shots,
                "failed_shot_count": failed_shot_count,
                "stage_failed": stage_failed,
                "clips": clip_metadata,
            },
        )

        logger.info(
            f"Clip 批次快照写入完成: success={succeeded_count} total={total_shots} failed={failed_shot_count}",
            event_type="clip_snapshot_written",
        )
