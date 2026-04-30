"""视觉圣经 API（visual_bible）。

⚠️ DEPRECATED（doc 21 决策 D1）：本路由文件已停用。
   新流程下 narrative_ready 直接进入 shot_plan，不再有视觉圣经阶段。
   保留代码作为参考（C2 降级方案的扩展点），但已从 main.py 注销，
   外部无法访问 /visual-bible/* 接口。
   
   如果未来需要恢复"角色定妆图自动生成"（决策 C2），可重新挂载本路由
   并改造 generate_character_ref / generate_scene_ref 接口适配新场景。

来源文档：
  - doc11 §4.4 / doc11 批次2（原职责，已 deprecated）
  - doc 21 §2.4 / §4.7 P6-6.4（停用决策）

接口（已停用）：
  GET  /api/v1/projects/{project_id}/visual-bible/active
  POST /api/v1/projects/{project_id}/visual-bible/init-from-narrative
  POST /api/v1/projects/{project_id}/visual-bible/generate-character-ref
  POST /api/v1/projects/{project_id}/visual-bible/generate-scene-ref
  POST /api/v1/projects/{project_id}/visual-bible/confirm
  POST /api/v1/projects/{project_id}/visual-bible/analyze-reference-image
  POST /api/v1/projects/{project_id}/visual-bible/generate-costume-ref
  POST /api/v1/projects/{project_id}/visual-bible/auto-setup-costumes
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.core.logging import get_logger
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.services.visual_bible_service import VisualBibleError, VisualBibleService
from app.tasks.dispatcher import task_dispatcher

router = APIRouter()


# ---------------------------------------------------------------------------
# Request body 模型
# ---------------------------------------------------------------------------

class GenerateCharacterRefBody(BaseModel):
    character_id: str
    generation_mode: Optional[str] = None
    source_image_url: Optional[str] = None
    source_image_hint: Optional[str] = None
    provider_name: Optional[str] = None


class GenerateSceneRefBody(BaseModel):
    scene_id: str
    provider_name: Optional[str] = None


class AnalyzeReferenceImageBody(BaseModel):
    asset_id: str
    character_id: Optional[str] = None


class GenerateCostumeRefBody(BaseModel):
    character_id: str
    costume_id: str
    generation_mode: str = "image_to_image"
    source_image_url: Optional[str] = None


class AutoSetupCostumesBody(BaseModel):
    skip_image_analysis: bool = False


# ---------------------------------------------------------------------------
# 内部辅助：项目归属校验
# ---------------------------------------------------------------------------

async def _require_project(project_id: str, user_id: str) -> None:
    async with UnitOfWork() as uow:
        project = await ProjectRepository(uow.session).get_by_id_for_user(
            project_id, user_id
        )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "项目不存在"},
        )


def _handle_visual_bible_error(exc: VisualBibleError) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if exc.code in ("project_not_found", "character_not_found", "scene_not_found", "no_visual_bible", "no_narrative")
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message},
    )


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/visual-bible/active
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/visual-bible/active")
async def get_active_visual_bible(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回当前激活的视觉圣经数据（从独立表组装）。"""
    req_id = get_request_id(request)
    logger = get_logger("api.visual_bible", layer="system")
    logger.info(
        f"前端请求视觉圣经数据: project_id={project_id!r}",
        event_type="visual_bible_data_requested",
    )

    await _require_project(project_id, str(current_user.id))

    svc = VisualBibleService()
    data = await svc.get_visual_bible_data(project_id)

    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "暂无视觉圣经，请先初始化"},
        )

    return ok(data=data, request_id=req_id)


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/visual-bible/init-from-narrative
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/visual-bible/init-from-narrative")
async def init_visual_bible_from_narrative(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """从 active NarrativeScript 初始化空 CharacterSetVersion。"""
    req_id = get_request_id(request)
    svc = VisualBibleService()
    try:
        csv = await svc.init_from_narrative(
            project_id=project_id,
            user_id=str(current_user.id),
        )
    except VisualBibleError as exc:
        raise _handle_visual_bible_error(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "init_failed", "message": str(exc)},
        ) from exc

    # WP7 适配：从独立表查询实际数量（JSONB 列已置空）
    from app.repositories.character_reference_repository import CharacterReferenceRepository
    from app.repositories.scene_reference_repository import SceneReferenceRepository
    async with UnitOfWork() as uow:
        char_count = await CharacterReferenceRepository(uow.session).count_total(csv.id)
        scene_count = await SceneReferenceRepository(uow.session).count_total(csv.id)

    return ok(
        data={
            "visual_bible_version_id": csv.id,
            "version_no": csv.version_no,
            "character_count": char_count,
            "scene_count": scene_count,
            "message": "视觉圣经已从叙事剧本初始化，可以开始生成参考图。",
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/visual-bible/generate-character-ref
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/visual-bible/generate-character-ref")
async def generate_character_reference(
    project_id: str,
    body: GenerateCharacterRefBody,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """为指定角色提交参考图生成任务（异步）。

    改为异步 dispatch：直接返回 job_id，任务由 Worker 後台执行。
    Worker 完成后自动触发 Director Mode B 汇报（不再需要 API 层手动触发）。
    """
    req_id = get_request_id(request)
    await _require_project(project_id, str(current_user.id))

    async with UnitOfWork() as uow:
        job, is_new = await task_dispatcher.dispatch(
            uow.session,
            project_id=project_id,
            tool_name="generate_character_ref",
            input_payload={
                "project_id": project_id,
                "user_id": str(current_user.id),
                "character_id": body.character_id,
                "generation_mode": body.generation_mode,
                "source_image_url": body.source_image_url,
                "source_image_hint": body.source_image_hint,
                "provider_name": body.provider_name,
            },
        )
    if is_new:
        await task_dispatcher.push_to_queue(job.id)

    return ok(
        data={
            "job_id": job.id,
            "character_id": body.character_id,
            "is_queued": is_new,
            "message": (
                f"角色参考图生成任务已提交（预计 2 分钟），"
                "请通过 SSE 监听进度。"
            ),
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/visual-bible/generate-scene-ref
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/visual-bible/generate-scene-ref")
async def generate_scene_reference(
    project_id: str,
    body: GenerateSceneRefBody,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """为指定场景提交参考图生成任务（异步）。

    改为异步 dispatch：直接返回 job_id，任务由 Worker 後台执行。
    Worker 完成后自动触发 Director Mode B 汇报。
    """
    req_id = get_request_id(request)
    await _require_project(project_id, str(current_user.id))

    async with UnitOfWork() as uow:
        job, is_new = await task_dispatcher.dispatch(
            uow.session,
            project_id=project_id,
            tool_name="generate_scene_ref",
            input_payload={
                "project_id": project_id,
                "user_id": str(current_user.id),
                "scene_id": body.scene_id,
                "provider_name": body.provider_name,
            },
        )
    if is_new:
        await task_dispatcher.push_to_queue(job.id)

    return ok(
        data={
            "job_id": job.id,
            "scene_id": body.scene_id,
            "is_queued": is_new,
            "message": (
                f"场景参考图生成任务已提交（预计 2 分钟），"
                "请通过 SSE 监听进度。"
            ),
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/visual-bible/confirm
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/visual-bible/confirm")
async def confirm_visual_bible(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """确认视觉圣经，推进项目到 visual_bible_ready。"""
    req_id = get_request_id(request)
    svc = VisualBibleService()
    try:
        csv = await svc.confirm_visual_bible(
            project_id=project_id,
            user_id=str(current_user.id),
        )
    except VisualBibleError as exc:
        raise _handle_visual_bible_error(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "confirm_failed", "message": str(exc)},
        ) from exc

    return ok(
        data={
            "visual_bible_version_id": csv.id,
            "confirmed_at": csv.confirmed_at,
            "message": "视觉圣经已确认，项目已推进到 visual_bible_ready 阶段。",
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/visual-bible/analyze-reference-image
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/visual-bible/analyze-reference-image")
async def analyze_reference_image(
    project_id: str,
    body: AnalyzeReferenceImageBody,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """调用 Omni 分析参考图，返回图片类型判断。"""
    req_id = get_request_id(request)
    await _require_project(project_id, str(current_user.id))
    svc = VisualBibleService()
    try:
        result = await svc.analyze_reference_image(
            asset_id=body.asset_id,
            project_id=project_id,
            user_id=str(current_user.id),
            character_id=body.character_id,
        )
    except VisualBibleError as exc:
        raise _handle_visual_bible_error(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "analysis_failed", "message": str(exc)},
        ) from exc
    return ok(data=result, request_id=req_id)


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/visual-bible/generate-costume-ref
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/visual-bible/generate-costume-ref")
async def generate_costume_reference(
    project_id: str,
    body: GenerateCostumeRefBody,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """为指定角色造型生成参考图（异步 dispatch）。"""
    req_id = get_request_id(request)
    await _require_project(project_id, str(current_user.id))

    async with UnitOfWork() as uow:
        job, is_new = await task_dispatcher.dispatch(
            uow.session,
            project_id=project_id,
            tool_name="generate_costume_ref",
            input_payload={
                "project_id": project_id,
                "user_id": str(current_user.id),
                "character_id": body.character_id,
                "costume_id": body.costume_id,
                "generation_mode": body.generation_mode,
                "source_image_url": body.source_image_url,
            },
        )
    if is_new:
        await task_dispatcher.push_to_queue(job.id)

    return ok(
        data={
            "job_id": job.id,
            "character_id": body.character_id,
            "costume_id": body.costume_id,
            "is_queued": is_new,
            "message": "造型参考图生成任务已提交，请通过 SSE 监听进度。",
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/visual-bible/auto-setup-costumes
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/visual-bible/auto-setup-costumes")
async def auto_setup_costumes(
    project_id: str,
    body: AutoSetupCostumesBody,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """一键自动设置多造型（Omni 驱动完整闭环）。"""
    req_id = get_request_id(request)
    await _require_project(project_id, str(current_user.id))

    async with UnitOfWork() as uow:
        job, is_new = await task_dispatcher.dispatch(
            uow.session,
            project_id=project_id,
            tool_name="auto_setup_costumes",
            input_payload={
                "project_id": project_id,
                "user_id": str(current_user.id),
                "skip_image_analysis": body.skip_image_analysis,
            },
        )
    if is_new:
        await task_dispatcher.push_to_queue(job.id)

    return ok(
        data={
            "job_id": job.id,
            "is_queued": is_new,
            "message": "多造型自动设置任务已提交，请通过 SSE 监听进度。",
        },
        request_id=req_id,
    )
