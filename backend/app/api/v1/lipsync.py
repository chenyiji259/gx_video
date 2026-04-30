"""LipSync REST API。

来源文档：doc 09 任务 13-04

路由：
  POST /api/v1/projects/{project_id}/shots/{shot_id}/lipsync
    → 为指定 shot 触发 LipSync 生成，返回新建的 ClipVersion 信息

  GET  /api/v1/projects/{project_id}/shots/lipsync-candidates
    → 列出当前项目中 lipsync_required=True 的 shots

前置约束：
  - shot.lipsync_required 必须为 True
  - shot 须处于 storyboard_ready / clip_ready / stale / failed 状态
  - 项目须有 active storyboard frame（作为正脸参考图）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_db_session
from app.models.user import User
from app.repositories.planning_repositories import ShotRepository
from app.repositories.project_repository import ProjectRepository
from app.services.lipsync_service import LipSyncService, LipSyncServiceError
from app.providers.lipsync.base import LipSyncError

router = APIRouter(prefix="/projects/{project_id}", tags=["lipsync"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ClipVersionResponse(BaseModel):
    clip_version_id: str
    shot_id: str
    generation_mode: str
    duration_ms: int
    asset_id: str
    status: str


class LipSyncCandidateResponse(BaseModel):
    shot_id: str
    shot_index: int
    status: str
    duration_ms: int
    emotion: str | None
    lipsync_required: bool


class LipSyncCandidatesResponse(BaseModel):
    project_id: str
    candidates: list[LipSyncCandidateResponse]
    total: int


# ---------------------------------------------------------------------------
# POST /shots/{shot_id}/lipsync
# ---------------------------------------------------------------------------

@router.post(
    "/shots/{shot_id}/lipsync",
    response_model=ClipVersionResponse,
    summary="触发单镜头 LipSync 生成",
    status_code=status.HTTP_201_CREATED,
)
async def generate_lipsync(
    project_id: str,
    shot_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ClipVersionResponse:
    """为指定 shot 生成口型驱动视频 clip。

    前置：
    - shot.lipsync_required=True
    - shot 状态：storyboard_ready / clip_ready / stale / failed
    - 项目有 active storyboard frame（用作正脸参考图）
    """
    shot = await ShotRepository(session).get_by_id(shot_id)
    if shot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "shot_not_found", "message": f"Shot {shot_id!r} 不存在"},
        )

    svc = LipSyncService()
    try:
        clip = await svc.generate_for_shot(
            project_id=project_id,
            shot_id=shot_id,
            user_id=current_user.id,
        )
    except LipSyncServiceError as exc:
        code_to_status = {
            "project_not_found": status.HTTP_404_NOT_FOUND,
            "shot_not_found": status.HTTP_404_NOT_FOUND,
            "lipsync_not_required": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_shot_status": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "no_face_image": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "no_audio_asset": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "insufficient_credits": status.HTTP_402_PAYMENT_REQUIRED,
        }
        http_status = code_to_status.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        raise HTTPException(
            status_code=http_status,
            detail={"code": exc.code, "message": exc.message},
        )
    except LipSyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": exc.code, "message": exc.message},
        )

    return ClipVersionResponse(
        clip_version_id=clip.id,
        shot_id=clip.shot_id,
        generation_mode=clip.generation_mode,
        duration_ms=clip.duration_ms,
        asset_id=clip.asset_id,
        status=clip.status,
    )


# ---------------------------------------------------------------------------
# GET /shots/lipsync-candidates
# ---------------------------------------------------------------------------

@router.get(
    "/shots/lipsync-candidates",
    response_model=LipSyncCandidatesResponse,
    summary="列出可触发 LipSync 的 shots",
)
async def list_lipsync_candidates(
    project_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> LipSyncCandidatesResponse:
    """返回项目中 lipsync_required=True 的所有 shots。"""
    project = await ProjectRepository(session).get_by_id_for_user(
        project_id, current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "project_not_found", "message": "项目不存在"},
        )

    all_shots = await ShotRepository(session).list_by_project(project_id)
    candidates = [s for s in all_shots if s.lipsync_required]

    return LipSyncCandidatesResponse(
        project_id=project_id,
        candidates=[
            LipSyncCandidateResponse(
                shot_id=s.id,
                shot_index=s.shot_index,
                status=s.status,
                duration_ms=s.duration_ms or 0,
                emotion=s.emotion,
                lipsync_required=s.lipsync_required,
            )
            for s in candidates
        ],
        total=len(candidates),
    )
