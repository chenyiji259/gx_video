"""Clips 查询 API。

来源文档：doc 09 任务 11-04/11-05

接口：
  GET /api/v1/projects/{project_id}/clips
    返回项目内所有激活 clip（每个 shot 的 active ClipVersion）。

  GET /api/v1/projects/{project_id}/clips/{clip_id}
    返回单个 ClipVersion 详情。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.user import User
from app.repositories.asset_repository import AssetRepository
from app.repositories.clip_repository import ClipRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork

router = APIRouter()


@router.get("/projects/{project_id}/clips")
async def list_active_clips(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回项目内所有激活 ClipVersion（每个 shot 的最新版本）。"""
    req_id = get_request_id(request)

    async with UnitOfWork() as uow:
        # 项目归属校验
        project = await ProjectRepository(uow.session).get_by_id_for_user(
            project_id, str(current_user.id)
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "项目不存在"},
            )

        clip_repo = ClipRepository(uow.session)
        asset_repo = AssetRepository(uow.session)
        clips = await clip_repo.list_active_by_project(project_id)

        clip_list = []
        for clip in clips:
            asset = await asset_repo.get_by_id(clip.asset_id)
            clip_list.append({
                "id": clip.id,
                "shot_id": clip.shot_id,
                "version_no": clip.version_no,
                "provider": clip.provider,
                "generation_mode": clip.generation_mode,
                "asset_id": clip.asset_id,
                "storage_uri": asset.storage_uri if asset else None,
                "duration_ms": clip.duration_ms,
                "status": clip.status,
                "is_active": clip.is_active,
                "created_at": clip.created_at.isoformat() if clip.created_at else None,
            })

    return ok(
        data={"clips": clip_list, "count": len(clip_list)},
        request_id=req_id,
    )


@router.get("/projects/{project_id}/clips/{clip_id}")
async def get_clip(
    project_id: str,
    clip_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回单个 ClipVersion 详情。"""
    req_id = get_request_id(request)

    async with UnitOfWork() as uow:
        # 项目归属校验
        project = await ProjectRepository(uow.session).get_by_id_for_user(
            project_id, str(current_user.id)
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "项目不存在"},
            )

        clip_repo = ClipRepository(uow.session)
        clip = await clip_repo.get_by_id(clip_id)

        if clip is None or clip.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "Clip 不存在"},
            )

        asset = await AssetRepository(uow.session).get_by_id(clip.asset_id)

    return ok(
        data={
            "id": clip.id,
            "shot_id": clip.shot_id,
            "version_no": clip.version_no,
            "provider": clip.provider,
            "generation_mode": clip.generation_mode,
            "asset_id": clip.asset_id,
            "storage_uri": asset.storage_uri if asset else None,
            "duration_ms": clip.duration_ms,
            "status": clip.status,
            "is_active": clip.is_active,
            "prompt_bundle_id": clip.prompt_bundle_id,
            "created_at": clip.created_at.isoformat() if clip.created_at else None,
        },
        request_id=req_id,
    )
