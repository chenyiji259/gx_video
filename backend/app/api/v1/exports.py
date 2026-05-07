"""Exports API。

来源文档：doc 09 任务 11-08

接口：
  POST /api/v1/projects/{project_id}/exports
    触发导出（默认 720p）。

  GET /api/v1/projects/{project_id}/exports/latest
    返回最新一次导出记录。
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.user import User
from app.repositories.asset_repository import AssetRepository
from app.repositories.export_repository import ExportRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.services.asset_access_service import build_asset_access_url
from app.services.export_service import ExportError, ExportService
from app.tools.ffmpeg_timeline_tool import FFmpegNotAvailableError

router = APIRouter()


@router.post("/projects/{project_id}/exports")
async def trigger_export(
    project_id: str,
    request: Request,
    resolution: Literal["720p", "1080p", "2K", "4K"] = Body(default="1080p", embed=True),
    current_user: User = Depends(get_current_user),
) -> dict:
    """触发视频导出。

    Args:
        resolution: 导出分辨率，720p、1080p、2K 或 4K，默认 1080p。
    """
    req_id = get_request_id(request)

    svc = ExportService()
    try:
        export_version = await svc.export_and_save(
            project_id=project_id,
            user_id=str(current_user.id),
            resolution=resolution,
        )
    except FFmpegNotAvailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ffmpeg_not_available",
                "message": "服务器未安装 ffmpeg，无法导出视频。",
            },
        ) from exc
    except ExportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "export_failed", "message": str(exc)},
        ) from exc

    async with UnitOfWork() as uow:
        asset = await AssetRepository(uow.session).get_by_id(export_version.asset_id)
        asset_url = await build_asset_access_url(asset)

    return ok(
        data={
            "export_version_id": export_version.id,
            "timeline_version_id": export_version.timeline_version_id,
            "asset_id": export_version.asset_id,
            "resolution": export_version.resolution,
            "status": export_version.status,
            "storage_uri": asset_url,
            "created_at": export_version.created_at.isoformat() if export_version.created_at else None,
            "message": f"导出完成（{resolution}），项目已推进到 export_ready 阶段。",
        },
        request_id=req_id,
    )


@router.get("/projects/{project_id}/exports/latest")
async def get_latest_export(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回最新一次导出记录。"""
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

        export_repo = ExportRepository(uow.session)
        export_version = await export_repo.get_latest(project_id)

        if export_version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "当前项目还没有导出记录"},
            )

        asset = await AssetRepository(uow.session).get_by_id(export_version.asset_id)
        asset_url = await build_asset_access_url(asset)

    return ok(
        data={
            "export_version_id": export_version.id,
            "timeline_version_id": export_version.timeline_version_id,
            "asset_id": export_version.asset_id,
            "storage_uri": asset_url,
            "resolution": export_version.resolution,
            "status": export_version.status,
            "created_at": export_version.created_at.isoformat() if export_version.created_at else None,
        },
        request_id=req_id,
    )
