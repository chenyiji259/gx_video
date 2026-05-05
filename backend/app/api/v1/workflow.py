"""工作流触发 API（REST 控制面路径，绕过图直接调用 Service）。

来源文档：doc 09 任务 9-05 / 计划决策 5（双路设计）

接口：
  POST /api/v1/projects/{project_id}/workflow/analyze-audio
    触发音频分析（state 需为 input_ready 或 audio_analyzed）。
  POST /api/v1/projects/{project_id}/workflow/generate-brief
    触发 brief+style 生成。
    前置校验：select_style_direction 决策已 selected，否则返回 decision_required。
  POST /api/v1/projects/{project_id}/workflow/generate-shot-plan
    触发 shot plan 生成。
    前置校验：confirm_brief 决策已 selected，否则返回 decision_required。

设计约束（计划决策 5）：
  REST 路径绕过图，但必须先校验对应前置决策已 selected，不能跳过确认。
  两条路径最终都落到同一 Service 层，保证状态推进行为一致。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.user import User
from app.repositories.decision_repository import DecisionRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.repositories.visual_bible_repository import NarrativeScriptVersionRepository
from app.repositories.storyboard_repositories import StoryboardVersionRepository
# from app.services.audio_analysis_service import AudioAnalysisError, AudioAnalysisService  # 旧流程：已停用
from app.services.brief_persistence_service import (
    BriefGenerationError,
    BriefPersistenceService,
)
from app.services.shot_plan_persistence_service import (
    ShotPlanGenerationError,
    ShotPlanPersistenceService,
)
from app.services.clip_service import ClipGenerationError, ClipService
from app.services.timeline_composer_service import TimelineComposerService, TimelineError
from app.tools.ffmpeg_timeline_tool import FFmpegNotAvailableError as FFmpegError
from app.services.storyboard_service import (
    StoryboardGenerationError,
    StoryboardService,
)
from app.services.narrative_script_service import (
    NarrativeScriptError,
    NarrativeScriptService,
)
from app.services.visual_bible_service import (
    VisualBibleError,
    VisualBibleService,
)
from app.repositories.character_reference_repository import CharacterReferenceRepository
from app.repositories.scene_reference_repository import SceneReferenceRepository
from app.tasks.dispatcher import task_dispatcher
from app.services.director_report_service import director_report_service
from app.services.conversation_service import ConversationService
from app.services.decision_service import DecisionService
from app.services.event_log_service import event_log_service
from app.schemas.event import ProjectEvent

from app.core.logging import get_logger

router = APIRouter()
_logger = get_logger("api.v1.workflow", layer="api")


# ---------------------------------------------------------------------------
# 内部辅助：查找已 selected 的指定类型决策
# ---------------------------------------------------------------------------

async def _get_selected_decision(
    project_id: str, decision_type: str, target_entity_id: str | None = None
) -> dict[str, Any] | None:
    """查找并返回指定类型的最近 selected 决策，不存在则返回 None。"""
    async with UnitOfWork() as uow:
        repo = DecisionRepository(uow.session)
        decisions = await repo.list_by_type(
            project_id, decision_type, status="selected"
        )
        if not decisions:
            return None
        if target_entity_id is not None:
            exact = [
                d for d in decisions
                if getattr(d, "target_entity_id", None) == target_entity_id
            ]
            if exact:
                decisions = exact
            else:
                current_open = await repo.list_by_type(
                    project_id, decision_type, status="open"
                )
                has_bound_open = any(
                    getattr(d, "target_entity_id", None) == target_entity_id
                    for d in current_open
                )
                if has_bound_open:
                    return None
                decisions = [
                    d for d in decisions
                    if getattr(d, "target_entity_id", None) is None
                ]
                if not decisions:
                    return None
        d = decisions[0]
        return {
            "id": d.id,
            "decision_type": d.decision_type,
            "target_entity_id": d.target_entity_id,
            "selected_option_id": d.selected_option_id,
            "status": d.status,
        }


async def _require_selected_decision(
    project_id: str,
    decision_type: str,
    req_id: str,
    target_entity_id: str | None = None,
) -> str:
    """确保指定 decision_type 已 selected，否则抛 decision_required HTTPException。

    Returns:
        selected_option_id
    """
    decision = await _get_selected_decision(project_id, decision_type, target_entity_id)
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "decision_required",
                "message": (
                    f"需要先通过 decisions API 完成 '{decision_type}' 决策，"
                    "才能触发此工作流步骤。"
                ),
                "decision_type": decision_type,
            },
        )
    return decision["selected_option_id"] or ""


async def _cancel_open_decisions(
    project_id: str,
    decision_types: set[str],
) -> None:
    """取消会造成新 UI 双轨语义的旧 open 决策。"""
    async with UnitOfWork() as uow:
        repo = DecisionRepository(uow.session)
        for decision_type in decision_types:
            decisions = await repo.list_by_type(
                project_id, decision_type, status="open"
            )
            for decision in decisions:
                decision.status = "cancelled"
                uow.session.add(decision)


async def _create_project_decision(
    *,
    project_id: str,
    user_id: str,
    decision_type: str,
    target_entity_id: str,
    options_payload: list[dict[str, str]],
    default_option_id: str = "confirm",
) -> dict:
    """创建绑定当前产物版本的项目级确认决策。"""
    session = await ConversationService().get_or_create_session(
        project_id=project_id,
        user_id=user_id,
    )
    return await DecisionService().create_decision(
        project_id=project_id,
        session_id=session["id"],
        decision_type=decision_type,
        target_entity_type="project",
        target_entity_id=target_entity_id,
        options_payload=options_payload,
        default_option_id=default_option_id,
    )


# ---------------------------------------------------------------------------
# POST /workflow/analyze-audio
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/workflow/analyze-audio")
async def trigger_analyze_audio(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """[旧流程停用] 触发音频分析。新流程（AI视频内容生成）不再需要音频分析步骤。"""
    # 旧流程（音乐MV模式）：已停用，新流程跳过此步骤直接生成 brief
    req_id = get_request_id(request)
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=200,
        content={"success": True, "data": {"message": "新流程无需音频分析，请直接调用 generate-brief"}, "request_id": req_id},
    )
    # === 以下为旧流程代码（已停用）===
    # try:
    #     async with UnitOfWork() as uow:
    #         job, is_new = await task_dispatcher.dispatch(
    #             uow.session,
    #             project_id=project_id,
    #             tool_name="analyze_audio",
    #             input_payload={"project_id": project_id, "user_id": str(current_user.id)},
    #         )
    #     if is_new:
    #         await task_dispatcher.push_to_queue(job.id)
    #
    #     return ok(
    #         data={
    #             "job_id": job.id,
    #             "status": job.status,
    #             "message": "音频分析任务已提交，完成后将通过 SSE 推送结果并由导演自动汇报。",
    #         },
    #         request_id=req_id,
    #     )
    # except Exception as exc:
    #     raise HTTPException(
    #         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    #         detail={"code": "analysis_dispatch_failed", "message": str(exc)},
    #     ) from exc


@router.post("/projects/{project_id}/workflow/generate-brief")
async def trigger_generate_brief(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """触发 brief + style 生成（REST 直接路径）。

    前置校验：select_style_direction 决策已 selected。
    若未选择风格，返回 decision_required 错误。
    """
    req_id = get_request_id(request)

    # 前置决策校验（决策 5：REST 路径也必须校验）
    # style_direction = await _require_selected_decision(project_id, "select_style_direction", req_id)
    # 旧流程：新流程不再需要前置风格选择决策
    style_direction = ""  # 新流程：style 由 LLM 从 user_prompt 推断，无需前置选择

    # 推送进度事件
    async with UnitOfWork() as uow:
        await event_log_service.emit(
            uow.session,
            ProjectEvent(
                project_id=project_id,
                aggregate_type="project",
                aggregate_id=project_id,
                event_type="brief.generating",
                category="workflow",
                payload={"message": "正在生成创意方案，请稍候..."},
            ),
        )

    svc = BriefPersistenceService()
    try:
        brief_version, style_version = await svc.generate_and_save(
            project_id=project_id,
            user_id=str(current_user.id),
            style_direction=style_direction,
        )
    except BriefGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "brief_failed", "message": str(exc)},
        ) from exc

    # 同步等待 Director 汇报完成，确保前端 refresh 时能拿到汇报消息
    try:
        await director_report_service.trigger(
            project_id=project_id,
            task_type="generate_brief",
            task_result={
                "brief_version_no": brief_version.version_no,
                "style_version_no": style_version.version_no,
            }
        )
    except Exception:
        pass  # Director 汇报失败不影响 API 响应

    return ok(
        data={
            "brief_version_id": brief_version.id,
            "style_version_id": style_version.id,
            "brief_version_no": brief_version.version_no,
            "title": brief_version.title,
            "summary": brief_version.summary,
            "message": "创意方案已生成，项目已推进到 brief_ready 阶段。",
        },
        request_id=req_id,
    )


@router.post("/projects/{project_id}/workflow/generate-creative-package")
async def trigger_generate_creative_package(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """生成新 UI 使用的创意剧本包。

    后端仍保留 brief/style/narrative 三个内部产物，但对前端只暴露一个
    confirm_narrative 决策：确认创意剧本包后直接进入关键帧生成。
    """
    req_id = get_request_id(request)
    user_id = str(current_user.id)

    await _cancel_open_decisions(
        project_id,
        {"confirm_brief", "confirm_narrative", "confirm_storyboard"},
    )

    async with UnitOfWork() as uow:
        await event_log_service.emit(
            uow.session,
            ProjectEvent(
                project_id=project_id,
                aggregate_type="project",
                aggregate_id=project_id,
                event_type="creative_package.generating",
                category="workflow",
                payload={"message": "正在生成创意方案和三镜头脚本，请稍候..."},
            ),
        )

    brief_svc = BriefPersistenceService()
    try:
        brief_version, style_version = await brief_svc.generate_and_save(
            project_id=project_id,
            user_id=user_id,
            style_direction="",
        )
    except BriefGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "creative_package_brief_failed", "message": str(exc)},
        ) from exc

    narrative_svc = NarrativeScriptService()
    try:
        narrative = await narrative_svc.generate_and_save(
            project_id=project_id,
            user_id=user_id,
        )
    except NarrativeScriptError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "creative_package_narrative_failed", "message": str(exc)},
        ) from exc

    await _cancel_open_decisions(
        project_id,
        {"confirm_brief", "confirm_narrative"},
    )
    decision = await _create_project_decision(
        project_id=project_id,
        user_id=user_id,
        decision_type="confirm_narrative",
        target_entity_id=narrative.id,
        options_payload=[
            {"id": "confirm", "title": "确认创意剧本包并生成关键帧"},
            {"id": "regenerate", "title": "重新生成创意剧本包"},
        ],
    )

    try:
        await director_report_service.trigger(
            project_id=project_id,
            task_type="generate_narrative",
            task_result={
                "version_no": narrative.version_no,
                "character_count": len(narrative.raw_payload.get("characters") or []) if narrative.raw_payload else 0,
                "scene_count": len(narrative.raw_payload.get("scenes") or []) if narrative.raw_payload else 0,
                "section_count": len(narrative.raw_payload.get("sections") or []) if narrative.raw_payload else 0,
            }
        )
    except Exception:
        pass

    return ok(
        data={
            "brief_version_id": brief_version.id,
            "style_version_id": style_version.id,
            "narrative_version_id": narrative.id,
            "brief_version_no": brief_version.version_no,
            "narrative_version_no": narrative.version_no,
            "decision_id": decision["id"],
            "message": "创意剧本包已生成，请确认后开始生成关键帧。",
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# POST /workflow/generate-narrative
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/workflow/generate-narrative")
async def trigger_generate_narrative(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """触发叙事剧本生成。

    前置校验：confirm_brief 决策已 selected。
    """
    req_id = get_request_id(request)

    # 前置决策校验
    await _require_selected_decision(project_id, "confirm_brief", req_id)

    svc = NarrativeScriptService()
    try:
        narrative = await svc.generate_and_save(
            project_id=project_id,
            user_id=str(current_user.id),
        )
    except NarrativeScriptError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "narrative_failed", "message": str(exc)},
        ) from exc

    try:
        await director_report_service.trigger(
            project_id=project_id,
            task_type="generate_narrative",
            task_result={
                "version_no": narrative.version_no,
                "character_count": len(narrative.raw_payload.get("characters") or []) if narrative.raw_payload else 0,
                "scene_count": len(narrative.raw_payload.get("scenes") or []) if narrative.raw_payload else 0,
                "section_count": len(narrative.raw_payload.get("sections") or []) if narrative.raw_payload else 0,
            }
        )
    except Exception:
        pass

    return ok(
        data={
            "narrative_version_id": narrative.id,
            "version_no": narrative.version_no,
            "message": "叙事剧本已生成，项目已推进到 narrative_ready 阶段。",
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# POST /workflow/init-visual-bible
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/workflow/init-visual-bible")
async def trigger_init_visual_bible(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """初始化视觉圣经（分步架构，先 init 框架，细节由 Agent/Tool 填充）。

    前置校验：confirm_narrative 决策已 selected。
    """
    req_id = get_request_id(request)

    # 前置决策校验
    await _require_selected_decision(project_id, "confirm_narrative", req_id)

    # 推送进度事件
    async with UnitOfWork() as uow:
        await event_log_service.emit(
            uow.session,
            ProjectEvent(
                project_id=project_id,
                aggregate_type="project",
                aggregate_id=project_id,
                event_type="visual_bible.initializing",
                category="workflow",
                payload={"message": "正在初始化视觉圣经，请稍候..."},
            ),
        )

    svc = VisualBibleService()
    try:
        csv = await svc.init_from_narrative(
            project_id=project_id,
            user_id=str(current_user.id),
        )
    except VisualBibleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "visual_bible_init_failed", "message": str(exc)},
        ) from exc

    # 移除同步触发 Director Report 的代码，因为此时只是初始化了框架，还没有实际生成图片
    # Director Report 应该在图片生成完成后触发（即 auto-setup-costumes 等任务完成后）

    # 自动 dispatch 所有缺少参考图的角色/场景的图片生成任务
    # 从独立表查询角色/场景参考图行，替代原来从 csv.characters / csv.scenes JSONB 读取
    user_id_str = str(current_user.id)
    async with UnitOfWork() as uow:
        char_refs = await CharacterReferenceRepository(uow.session).list_by_version(csv.id)
        scene_refs = await SceneReferenceRepository(uow.session).list_by_version(csv.id)

    for char_ref in char_refs:
        if not char_ref.character_id or char_ref.active_reference_asset_id:
            continue
        try:
            async with UnitOfWork() as uow:
                job, is_new = await task_dispatcher.dispatch(
                    uow.session,
                    project_id=project_id,
                    tool_name="generate_character_ref",
                    input_payload={
                        "project_id": project_id,
                        "user_id": user_id_str,
                        "character_id": char_ref.character_id,
                    },
                )
            if is_new:
                await task_dispatcher.push_to_queue(job.id)
        except Exception as exc:
            _logger.error(
                f"角色参考图 dispatch/push 失败: character_id={char_ref.character_id!r} error={exc!r}",
                event_type="visual_bible_dispatch_error",
            )

    for scene_ref in scene_refs:
        if not scene_ref.scene_id:
            continue
        try:
            async with UnitOfWork() as uow:
                job, is_new = await task_dispatcher.dispatch(
                    uow.session,
                    project_id=project_id,
                    tool_name="generate_scene_ref",
                    input_payload={
                        "project_id": project_id,
                        "user_id": user_id_str,
                        "scene_id": scene_ref.scene_id,
                    },
                )
            if is_new:
                await task_dispatcher.push_to_queue(job.id)
        except Exception as exc:
            _logger.error(
                f"场景参考图 dispatch/push 失败: scene_id={scene_ref.scene_id!r} error={exc!r}",
                event_type="visual_bible_dispatch_error",
            )

    return ok(
        data={
            "character_set_version_id": csv.id,
            "version_no": csv.version_no,
            "character_count": len(char_refs),
            "scene_count": len(scene_refs),
            "message": "视觉圣经框架已初始化，您可以开始为角色和场景生成参考图。",
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# POST /workflow/generate-shot-plan
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/workflow/generate-shot-plan")
async def trigger_generate_shot_plan(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """触发 shot plan 生成（REST 直接路径）。

    前置校验：confirm_narrative 决策已 selected（且选择 'confirm'）。
    若未确认剧本，返回 decision_required 错误。
    """
    req_id = get_request_id(request)

    # 前置决策校验
    selected_option = await _require_selected_decision(
        project_id, "confirm_narrative", req_id
    )
    # 若用户选择 regenerate，则不允许继续生成 shot plan
    if selected_option == "regenerate":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "decision_required",
                "message": "用户选择了重新生成叙事剧本，请先重新生成剧本后再触发 shot plan。",
            },
        )

    try:
        async with UnitOfWork() as uow:
            job, is_new = await task_dispatcher.dispatch(
                uow.session,
                project_id=project_id,
                tool_name="generate_shot_plan",
                input_payload={"project_id": project_id, "user_id": str(current_user.id)},
            )
        if is_new:
            await task_dispatcher.push_to_queue(job.id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "shot_plan_dispatch_failed", "message": str(exc)},
        ) from exc

    return ok(
        data={
            "job_id": job.id,
            "status": "submitted" if is_new else "already_running",
            "message": "镜头计划生成任务已提交，通常需要 2-10 分钟，完成后 Director 将自动汇报。",
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# POST /workflow/generate-storyboard
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/workflow/generate-storyboard")
async def trigger_generate_storyboard(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """触发九宫格 storyboard 生成（REST Worker dispatch 版本）。

    新流程中 narrative 确认后可直接生成九宫格；shot_plan 由后端从 narrative
    自动派生，仅作为视频生成内部输入，不再要求用户额外确认。
    返回 job_id，前端通过 SSE 或轮询获取完成结果。
    """
    req_id = get_request_id(request)

    # 新流程：confirm_narrative 后直接进入九宫格分镜。
    # shot_plan 只是后端从 narrative 派生的内部数据，不再要求用户额外确认。
    async with UnitOfWork() as uow:
        project = await ProjectRepository(uow.session).get_by_id_for_user(
            project_id, str(current_user.id)
        )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "project_not_found", "message": "项目不存在"},
        )
    if project.current_stage in {"narrative_ready", "shot_plan_ready"}:
        async with UnitOfWork() as uow:
            narrative = await NarrativeScriptVersionRepository(uow.session).get_active(
                project_id
            )
        await _require_selected_decision(
            project_id,
            "confirm_narrative",
            req_id,
            getattr(narrative, "id", None),
        )

    try:
        async with UnitOfWork() as uow:
            job, is_new = await task_dispatcher.dispatch(
                uow.session,
                project_id=project_id,
                tool_name="generate_storyboard",
                input_payload={"project_id": project_id, "user_id": str(current_user.id)},
            )
        if is_new:
            await task_dispatcher.push_to_queue(job.id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "storyboard_dispatch_failed", "message": str(exc)},
        ) from exc

    return ok(
        data={
            "job_id": job.id,
            "status": "submitted" if is_new else "already_running",
            "message": "分镜图生成任务已提交，通常需要 2-5 分钟，完成后 Director 将自动汇报。",
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# POST /workflow/generate-clips
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/workflow/generate-clips")
async def trigger_generate_clips(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """触发视频 clip 生成（REST Worker dispatch 版本）。

    新 UI 下 storyboard_ready 表示关键帧已生成完成，但仍必须先选择
    confirm_storyboard，避免高成本视频生成被直接触发。
    """
    req_id = get_request_id(request)
    _logger.info(
        f"收到生成视频请求: project_id={project_id!r} user_id={str(current_user.id)!r}",
        event_type="generate_clips_request_received",
    )
    _logger.info(
        f"当前生成视频请求运行在 credits bypass 模式: project_id={project_id!r}",
        event_type="generate_clips_credits_bypass_mode",
    )

    async with UnitOfWork() as uow:
        project = await ProjectRepository(uow.session).get_by_id_for_user(
            project_id, str(current_user.id)
        )
        if project is None:
            _logger.warning(
                f"生成视频请求失败: project_id={project_id!r} 不存在",
                event_type="generate_clips_project_not_found",
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "项目不存在"},
            )
        if project.current_stage not in {"storyboard_ready", "clips_ready", "failed"}:
            _logger.warning(
                f"生成视频请求被拒绝: project_id={project_id!r} "
                f"current_stage={project.current_stage!r}",
                event_type="generate_clips_invalid_stage",
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "invalid_stage",
                    "message": (
                        f"当前阶段 {project.current_stage!r} 还不能开始生成视频，"
                        "请先完成九宫格生成与切分，进入 storyboard_ready；若本次是视频生成阶段失败，也可在 failed 状态下重试。"
                    ),
                },
            )
        storyboard = await StoryboardVersionRepository(uow.session).get_active(
            project_id
        )

    if project.current_stage in {"storyboard_ready", "clips_ready", "failed"}:
        selected_option = await _require_selected_decision(
            project_id,
            "confirm_storyboard",
            req_id,
            getattr(storyboard, "id", None),
        )
        if selected_option == "regenerate":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "decision_required",
                    "message": "用户选择了重新生成关键帧，请先重新生成关键帧后再触发视频生成。",
                },
            )

    try:
        async with UnitOfWork() as uow:
            job, is_new = await task_dispatcher.dispatch(
                uow.session,
                project_id=project_id,
                tool_name="generate_clips",
                input_payload={"project_id": project_id, "user_id": str(current_user.id)},
            )
        if is_new:
            await task_dispatcher.push_to_queue(job.id)
            _logger.info(
                f"生成视频任务已提交: project_id={project_id!r} job_id={job.id!r}",
                event_type="generate_clips_job_submitted",
            )
        else:
            _logger.info(
                f"生成视频任务复用已有 job: project_id={project_id!r} job_id={job.id!r}",
                event_type="generate_clips_job_reused",
            )
    except Exception as exc:
        _logger.exception(
            f"生成视频任务分发失败: project_id={project_id!r} error={exc!r}",
            event_type="generate_clips_dispatch_failed",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "clip_dispatch_failed", "message": str(exc)},
        ) from exc

    return ok(
        data={
            "job_id": job.id,
            "status": "submitted" if is_new else "already_running",
            "message": "视频片段生成任务已提交，此过程耗时较长（5-15 分钟），完成后 Director 将自动汇报。",
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# POST /workflow/generate-timeline
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/workflow/generate-timeline")
async def trigger_generate_timeline(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """触发时间线合成（REST 直接路径）。

    前置校验：项目应处于 clips_ready 或 timeline_ready 阶段。
    """
    req_id = get_request_id(request)

    svc = TimelineComposerService()
    try:
        tl_version = await svc.compose_and_save(
            project_id=project_id,
            user_id=str(current_user.id),
        )
    except FFmpegError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ffmpeg_not_available", "message": str(exc)},
        ) from exc
    except TimelineError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "timeline_failed", "message": str(exc)},
        ) from exc

    payload = tl_version.raw_payload or {}
    
    try:
        await director_report_service.trigger(
            project_id=project_id,
            task_type="generate_timeline",
            task_result={
                "version_no": tl_version.version_no,
                "segment_count": payload.get("segment_count", 0),
                "total_duration_ms": payload.get("total_duration_ms", 0),
            }
        )
    except Exception:
        pass

    return ok(
        data={
            "timeline_version_id": tl_version.id,
            "version_no": tl_version.version_no,
            "segment_count": payload.get("segment_count", 0),
            "total_duration_ms": payload.get("total_duration_ms", 0),
            "message": "时间线已合成，项目已推进到 timeline_ready 阶段。",
        },
        request_id=req_id,
    )
