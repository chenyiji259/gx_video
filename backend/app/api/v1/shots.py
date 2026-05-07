"""Shot 查询与返工 API。

来源文档：doc 09 任务 9-05 / 12-02 / 12-03

接口：
  GET  /api/v1/projects/{project_id}/shots
    返回镜头列表（按 shot_index 排序，支持 limit/offset）。
  GET  /api/v1/projects/{project_id}/shots/{shot_id}
    返回单个镜头详情。
  PATCH /api/v1/projects/{project_id}/shots/{shot_id}
    修改单个镜头语义字段，触发 stale 传播。
  POST /api/v1/projects/{project_id}/shots/{shot_id}/regenerate
    重编译并重生成单个镜头的 clip。
"""
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.user import User
from app.repositories.event_log_repository import EventLogRepository
from app.repositories.planning_repositories import ShotRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.services.shot_patch_service import ShotPatchError, ShotPatchService
from app.services.shot_regeneration_service import (
    ShotRegenerationError,
    ShotRegenerationService,
)
from app.providers.video.base import VideoGenerationError

router = APIRouter()

# 映射到 404 的错误码集合
_NOT_FOUND_CODES: frozenset[str] = frozenset({"project_not_found", "shot_not_found"})


class ShotPatchFields(BaseModel):
    """ PATCH patch 内嵌字段（全部可选）。"""

    emotion: Optional[str] = None
    shot_type: Optional[str] = None
    camera_language: Optional[str] = None
    visual_energy: Optional[str] = None
    lyric_text: Optional[str] = None
    lipsync_required: Optional[bool] = None
    character_binding: Optional[Any] = None
    style_binding: Optional[List[Any]] = None


class ShotPatchRequest(BaseModel):
    """ PATCH /shots/{shot_id} 请求体（doc05 §17.8 规范：嵌套 patch 键）。

    请求体格式：
        {"patch": {"visual_energy": "high", "camera_language": "fast handheld"}}
    """

    patch: ShotPatchFields


def _shot_to_dict(shot: object) -> dict:
    """Shot ORM 对象 → API 响应 dict。"""
    shot_index = getattr(shot, "shot_index", None)
    start_ms = getattr(shot, "start_ms", None)
    end_ms = getattr(shot, "end_ms", None)
    return {
        "id": getattr(shot, "id", None),
        "project_id": getattr(shot, "project_id", None),
        "shot_plan_version_id": getattr(shot, "shot_plan_version_id", None),
        "scene_id": getattr(shot, "scene_id", None),
        "shot_index": shot_index,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_ms": getattr(shot, "duration_ms", None),
        "segment_index": (int(shot_index) + 1) if shot_index is not None else None,
        "segment_time_range": (
            f"{int(start_ms or 0) // 1000}-{int(end_ms or 0) // 1000}s"
            if start_ms is not None and end_ms is not None
            else None
        ),
        "story_board_segment_label": (
            f"Segment {int(shot_index) + 1}"
            if shot_index is not None
            else None
        ),
        "section_type": getattr(shot, "section_type", None),
        "lyric_text": getattr(shot, "lyric_text", None),
        "dialogue": getattr(shot, "dialogue", None),
        "emotion": getattr(shot, "emotion", None),
        "emotion_intensity": getattr(shot, "emotion_intensity", None),
        "shot_type": getattr(shot, "shot_type", None),
        "subject": getattr(shot, "subject", None),
        "location": getattr(shot, "location", None),
        "camera_language": getattr(shot, "camera_language", None),
        "visual_energy": getattr(shot, "visual_energy", None),
        "lipsync_required": getattr(shot, "lipsync_required", False),
        "character_binding": getattr(shot, "character_binding", []),
        "style_binding": getattr(shot, "style_binding", []),
        "status": getattr(shot, "status", None),
        "created_at": (
            getattr(shot, "created_at", None).isoformat()
            if getattr(shot, "created_at", None)
            else None
        ),
        "updated_at": (
            getattr(shot, "updated_at", None).isoformat()
            if getattr(shot, "updated_at", None)
            else None
        ),
    }


def _build_latest_failure_map(events: list[object]) -> dict[str, dict[str, Any]]:
    """从 clip.shot.failed 事件中提取每个 shot 最近一次失败原因。"""
    failure_map: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = getattr(event, "payload", {}) or {}
        shot_id = payload.get("shot_id")
        if not shot_id or shot_id in failure_map:
            continue
        failure = payload.get("failure") or {}
        failure_map[str(shot_id)] = {
            "code": failure.get("code") or "unknown_error",
            "message": failure.get("message") or payload.get("message") or "视频生成失败，但未返回具体错误。",
            "provider": failure.get("provider"),
            "event_id": getattr(event, "id", None),
            "created_at": (
                getattr(event, "created_at", None).isoformat()
                if getattr(event, "created_at", None)
                else None
            ),
        }
    return failure_map


@router.get("/projects/{project_id}/shots")
async def list_shots(
    project_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回项目镜头列表（按 shot_index 升序）。"""
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
        shot_repo = ShotRepository(uow.session)
        shots = await shot_repo.list_by_project(
            project_id,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
        )
        total = await shot_repo.count_by_project(project_id)
        failure_events = await EventLogRepository(
            uow.session
        ).list_project_events_by_type(
            project_id,
            "clip.shot.failed",
            limit=200,
        )
        latest_failure_by_shot = _build_latest_failure_map(list(failure_events))

    return ok(
        data={
            "items": [
                {
                    **_shot_to_dict(s),
                    "last_failure": latest_failure_by_shot.get(getattr(s, "id", "")),
                }
                for s in shots
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(shots)) < total,
        },
        request_id=req_id,
    )


@router.get("/projects/{project_id}/shots/{shot_id}")
async def get_shot(
    project_id: str,
    shot_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回单个镜头详情。"""
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
        shot = await ShotRepository(uow.session).get_by_id_for_project(
            shot_id, project_id
        )

    if shot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "镜头不存在"},
        )

    return ok(data=_shot_to_dict(shot), request_id=req_id)


@router.patch("/projects/{project_id}/shots/{shot_id}")
async def patch_shot(
    project_id: str,
    shot_id: str,
    request: Request,
    body: ShotPatchRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """修改单个镜头语义字段（白名单字段），触发 stale 传播。

    可修改字段： emotion / shot_type / camera_language / visual_energy /
              lyric_text / lipsync_required / character_binding / style_binding。
    修改后该 shot 及其 active clip 会被标记 stale，项目退回到 clips_ready。
    """
    req_id = get_request_id(request)
    # 过滤将 None 字段移除，只发送用户明确提供的字段
    patch_data = {k: v for k, v in body.patch.model_dump().items() if v is not None}

    svc = ShotPatchService()
    try:
        shot = await svc.patch(
            project_id=project_id,
            shot_id=shot_id,
            user_id=str(current_user.id),
            patch_data=patch_data,
        )
    except ShotPatchError as exc:
        http_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code in _NOT_FOUND_CODES
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(
            status_code=http_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "patch_failed", "message": str(exc)},
        ) from exc

    return ok(
        data={
            **_shot_to_dict(shot),
            "message": "镜头语义已修改，下游 clip 已标记 stale。可通过重生成接口刷新。",
        },
        request_id=req_id,
    )


@router.post("/projects/{project_id}/shots/{shot_id}/regenerate")
async def regenerate_shot(
    project_id: str,
    shot_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
) -> dict:
    """重编译并重生成单个镜头的 clip（高成本操作，会消耗 credits）。

    允许的 shot 状态： stale / clip_ready / failed / storyboard_ready。
    生成完成后：
      - 新的 ClipVersion 激活，shot 返回 clip_ready。
      - 如果 active timeline 存在，对应 segment 的 clip_version_id 被更新，
        timeline render_status 标记为 stale（需要重新合成才能导出）。
    """
    req_id = get_request_id(request)

    svc = ShotRegenerationService()
    try:
        clip = await svc.regenerate(
            project_id=project_id,
            shot_id=shot_id,
            user_id=str(current_user.id),
            idempotency_key=idempotency_key,
        )
    except ShotRegenerationError as exc:
        http_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code in _NOT_FOUND_CODES
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(
            status_code=http_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except VideoGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "video_generation_failed", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "regen_failed", "message": str(exc)},
        ) from exc

    return ok(
        data={
            "clip_version_id": clip.id,
            "shot_id": clip.shot_id,
            "version_no": clip.version_no,
            "provider": clip.provider,
            "generation_mode": clip.generation_mode,
            "asset_id": clip.asset_id,
            "duration_ms": clip.duration_ms,
            "status": clip.status,
            "is_active": clip.is_active,
            "created_at": clip.created_at.isoformat() if clip.created_at else None,
            "message": "clip 重生成完成。如有 active timeline，对应 segment 已更新，timeline 标记为 stale。",
        },
        request_id=req_id,
    )
