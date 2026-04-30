"""规划产物查询 API（brief + style）。

来源文档：doc 09 任务 9-05

接口：
  GET /api/v1/projects/{project_id}/brief/active
    返回当前激活的 creative brief 版本。
  GET /api/v1/projects/{project_id}/style/active
    返回当前激活的 style bible 版本。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.user import User
from app.repositories.planning_repositories import (
    CreativeBriefRepository,
    StyleBibleRepository,
)
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork

router = APIRouter()


@router.get("/projects/{project_id}/brief/active")
async def get_active_brief(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回当前激活的 creative brief 版本。"""
    req_id = get_request_id(request)
    async with UnitOfWork() as uow:
        project = await ProjectRepository(uow.session).get_by_id_for_user(
            project_id, str(current_user.id)
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "项目不存在"},
            )
        brief = await CreativeBriefRepository(uow.session).get_active(project_id)

    if brief is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "暂无 creative brief"},
        )

    return ok(
        data={
            "id": brief.id,
            "version_no": brief.version_no,
            "title": brief.title,
            "summary": brief.summary,
            "narrative_mode": brief.narrative_mode,
            "performance_ratio": float(brief.performance_ratio) if brief.performance_ratio else 0.4,
            "mood_tags": brief.mood_tags,
            "style_direction": brief.style_direction,
            "raw_payload": brief.raw_payload,
            "is_active": brief.is_active,
            "created_at": brief.created_at.isoformat() if brief.created_at else None,
        },
        request_id=req_id,
    )


@router.get("/projects/{project_id}/style/active")
async def get_active_style(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回当前激活的 style bible 版本。"""
    req_id = get_request_id(request)
    async with UnitOfWork() as uow:
        project = await ProjectRepository(uow.session).get_by_id_for_user(
            project_id, str(current_user.id)
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "项目不存在"},
            )
        style = await StyleBibleRepository(uow.session).get_active(project_id)

    if style is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "暂无 style bible"},
        )

    return ok(
        data={
            "id": style.id,
            "version_no": style.version_no,
            "palette": style.palette,
            "lighting_style": style.lighting_style,
            "camera_style": style.camera_style,
            "film_texture": style.film_texture,
            "reference_notes": style.reference_notes,
            "raw_payload": style.raw_payload,
            "is_active": style.is_active,
            "created_at": style.created_at.isoformat() if style.created_at else None,
        },
        request_id=req_id,
    )
