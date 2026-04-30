"""Timeline 查询与触发 API。

来源文档：doc 09 任务 11-06

接口：
  GET /api/v1/projects/{project_id}/timeline/active
    返回当前激活的 timeline 版本摘要（含 preview URL）。

  GET /api/v1/projects/{project_id}/timeline/segments
    返回当前激活 timeline 的所有 segments。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.domain.states import ProjectStage
from app.models.user import User
from app.repositories.asset_repository import AssetRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.timeline_repository import (
    TimelineSegmentRepository,
    TimelineVersionRepository,
)
from app.repositories.unit_of_work import UnitOfWork
from app.tasks.dispatcher import task_dispatcher

router = APIRouter()


@router.get("/projects/{project_id}/timeline/active")
async def get_active_timeline(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回当前激活的 timeline 版本及 preview URL。"""
    req_id = get_request_id(request)

    async with UnitOfWork() as uow:
        # 项目归属校验
        if await ProjectRepository(uow.session).get_by_id_for_user(
            project_id, str(current_user.id)
        ) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "项目不存在"},
            )

        tv_repo = TimelineVersionRepository(uow.session)
        version = await tv_repo.get_active(project_id)

        if version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "当前项目没有激活的 timeline"},
            )

        # 读取 preview asset URL
        preview_uri = None
        payload = version.raw_payload or {}
        preview_asset_id = payload.get("preview_asset_id")
        if preview_asset_id:
            asset = await AssetRepository(uow.session).get_by_id(preview_asset_id)
            if asset:
                preview_uri = asset.storage_uri

    return ok(
        data={
            "version_id": version.id,
            "version_no": version.version_no,
            "project_id": version.project_id,
            "render_status": version.render_status,
            "total_duration_ms": payload.get("total_duration_ms"),
            "segment_count": payload.get("segment_count"),
            "preview_uri": preview_uri,
            "is_active": version.is_active,
            "created_at": version.created_at.isoformat() if version.created_at else None,
        },
        request_id=req_id,
    )


@router.post("/projects/{project_id}/timeline/compose")
async def compose_timeline(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """用户手动触发时间线合成（直接派发 ToolJob，不经过 AI 对话流）。

    前置条件：项目阶段为 clips_ready 或 timeline_ready（重新合成）。
    触发后通过 SSE timeline_ready 事件获取 preview_uri。
    """
    req_id = get_request_id(request)
    user_id = str(current_user.id)

    _ALLOWED_STAGES = {
        ProjectStage.CLIPS_READY.value,
        ProjectStage.TIMELINE_READY.value,
    }

    async with UnitOfWork() as uow:
        project = await ProjectRepository(uow.session).get_by_id_for_user(
            project_id, user_id
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "项目不存在"},
            )
        if project.current_stage not in _ALLOWED_STAGES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "invalid_stage",
                    "message": (
                        f"当前阶段 {project.current_stage!r} 不允许合成时间线，"
                        "需先完成所有 clip 生成（clips_ready）"
                    ),
                },
            )
        job, is_new = await task_dispatcher.dispatch(
            uow.session,
            project_id=project_id,
            tool_name="generate_timeline",
            input_payload={"project_id": project_id, "user_id": user_id},
        )

    if is_new:
        await task_dispatcher.push_to_queue(job.id)

    return ok(
        data={
            "job_id": job.id,
            "is_new": is_new,
            "message": "时间线合成任务已提交，请通过 SSE 监听 timeline_ready 事件。",
        },
        request_id=req_id,
    )


@router.get("/projects/{project_id}/timeline/segments")
async def list_timeline_segments(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回当前激活 timeline 的所有 segments（按 start_ms 排序）。"""
    req_id = get_request_id(request)

    async with UnitOfWork() as uow:
        # 项目归属校验
        if await ProjectRepository(uow.session).get_by_id_for_user(
            project_id, str(current_user.id)
        ) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "项目不存在"},
            )

        tv_repo = TimelineVersionRepository(uow.session)
        seg_repo = TimelineSegmentRepository(uow.session)

        version = await tv_repo.get_active(project_id)
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "当前项目没有激活的 timeline"},
            )

        segments = await seg_repo.list_by_version(version.id)

    return ok(
        data={
            "timeline_version_id": version.id,
            "version_no": version.version_no,
            "segments": [
                {
                    "id": seg.id,
                    "shot_id": seg.shot_id,
                    "clip_version_id": seg.clip_version_id,
                    "start_ms": seg.start_ms,
                    "end_ms": seg.end_ms,
                    "duration_ms": seg.end_ms - seg.start_ms,
                    "transition_in": seg.transition_in,
                    "transition_out": seg.transition_out,
                }
                for seg in segments
            ],
        },
        request_id=req_id,
    )
