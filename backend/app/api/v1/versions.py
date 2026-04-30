"""版本管理 API。

来源文档：doc 09 任务 12-04

接口：
  GET  /api/v1/projects/{project_id}/versions/{entity_type}
    查询指定实体的版本列表（brief / style / storyboard / timeline）。

  POST /api/v1/projects/{project_id}/versions/{entity_type}/{version_id}/activate
    激活指定版本，触发 stale 传播和项目阶段回退。

entity_type 取值：brief / style / storyboard / timeline
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.planning import CreativeBriefVersion, StyleBibleVersion
from app.models.storyboard import StoryboardVersion
from app.models.timeline import TimelineVersion
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.services.version_switch_service import (
    SUPPORTED_ENTITY_TYPES,
    VersionSwitchError,
    VersionSwitchService,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# 内部：版本列表查询
# ---------------------------------------------------------------------------

async def _list_versions(
    session: Any,
    project_id: str,
    entity_type: str,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """按 entity_type 查询版本列表（按 version_no 倒序）。

    Returns:
        (versions_list, total_count)
    """
    _MODEL_MAP = {
        "brief": CreativeBriefVersion,
        "style": StyleBibleVersion,
        "storyboard": StoryboardVersion,
        "timeline": TimelineVersion,
    }
    model = _MODEL_MAP[entity_type]
    # 分页查询
    result = await session.execute(
        select(model)
        .where(model.project_id == project_id)
        .order_by(model.version_no.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = list(result.scalars().all())
    # 总数查询
    count_result = await session.execute(
        select(func.count()).select_from(model).where(model.project_id == project_id)
    )
    total: int = count_result.scalar_one() or 0

    versions: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {
            "id": row.id,
            "project_id": row.project_id,
            "version_no": row.version_no,
            "is_active": row.is_active,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        # timeline 有额外字段
        if entity_type == "timeline":
            entry["render_status"] = getattr(row, "render_status", None)
            payload = getattr(row, "raw_payload", {}) or {}
            entry["total_duration_ms"] = payload.get("total_duration_ms")
            entry["segment_count"] = payload.get("segment_count")
        # brief 有标题摘要
        if entity_type == "brief":
            entry["title"] = getattr(row, "title", None)
            entry["summary"] = (getattr(row, "summary", "") or "")[:120]
        # storyboard 的 shot_plan_version_id
        if entity_type == "storyboard":
            entry["shot_plan_version_id"] = getattr(row, "shot_plan_version_id", None)
        versions.append(entry)
    return versions, total


# ---------------------------------------------------------------------------
# GET /versions/{entity_type}
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/versions/{entity_type}")
async def list_versions(
    project_id: str,
    entity_type: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
) -> dict:
    """查询项目指定产物的历史版本列表（按版本号倒序）。

    entity_type: brief / style / storyboard / timeline
    支持 limit（默认 20，最大 100）和 offset 分页参数。
    """
    req_id = get_request_id(request)

    if entity_type not in SUPPORTED_ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unsupported_entity_type",
                "message": f"不支持的 entity_type: {entity_type!r}，"
                           f"支持: {sorted(SUPPORTED_ENTITY_TYPES)}",
            },
        )

    async with UnitOfWork() as uow:
        # 项目归属校验
        if await ProjectRepository(uow.session).get_by_id_for_user(
            project_id, str(current_user.id)
        ) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "项目不存在"},
            )

        versions, total = await _list_versions(
            uow.session, project_id, entity_type, limit=limit, offset=offset
        )

    return ok(
        data={
            "entity_type": entity_type,
            "project_id": project_id,
            "versions": versions,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(versions)) < total,
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# POST /versions/{entity_type}/{version_id}/activate
# ---------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/versions/{entity_type}/{version_id}/activate"
)
async def activate_version(
    project_id: str,
    entity_type: str,
    version_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """激活指定版本，触发对应的 stale 传播与项目阶段回退。

    entity_type: brief / style / storyboard / timeline

    - brief 激活 → 项目退到 audio_analyzed，shot_plan / storyboard / clips / timeline 失效
    - style 激活 → 项目退到 shot_plan_ready，storyboard / clips / timeline 失效
    - storyboard 激活 → 项目退到 storyboard_ready，clips / timeline 失效
    - timeline 激活 → 只切换 active 指针，不影响上游
    """
    req_id = get_request_id(request)

    svc = VersionSwitchService()
    try:
        result = await svc.activate(
            project_id=project_id,
            user_id=str(current_user.id),
            entity_type=entity_type,
            version_id=version_id,
        )
    except VersionSwitchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "version_switch_failed", "message": str(exc)},
        ) from exc

    return ok(data=result, request_id=req_id)
