"""Storyboard 查询 API。

来源文档：doc 09 任务 10-03（配套 9-05 设计模式）

接口：
  GET /api/v1/projects/{project_id}/storyboard/active
    返回当前激活的 storyboard 版本 + frame 数量摘要。

  GET /api/v1/projects/{project_id}/storyboard-frames
    分页列出当前激活版本的所有帧，每帧带资产预签名 URL。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.user import User
from app.repositories.asset_repository import AssetRepository
from app.repositories.storyboard_repositories import (
    StoryboardFrameRepository,
    StoryboardVersionRepository,
)
from app.repositories.unit_of_work import UnitOfWork
from app.repositories.prompt_bundle_repository import PromptBundleRepository
from app.services.asset_access_service import build_asset_access_url, build_asset_access_url_map

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /storyboard/active
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/storyboard/active")
async def get_active_storyboard(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回当前激活的 storyboard 版本及 frame 数量。"""
    req_id = get_request_id(request)

    async with UnitOfWork() as uow:
        session = uow.session
        version_repo = StoryboardVersionRepository(session)
        frame_repo = StoryboardFrameRepository(session)

        version = await version_repo.get_active(project_id)
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "当前项目没有激活的 storyboard 版本"},
            )

        frame_count = await frame_repo.count_by_version(version.id)

    return ok(
        data={
            "version_id": version.id,
            "version_no": version.version_no,
            "project_id": version.project_id,
            "shot_plan_version_id": version.shot_plan_version_id,
            "frame_count": frame_count,
            "is_active": version.is_active,
            "created_at": version.created_at.isoformat() if version.created_at else None,
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# GET /storyboard-frames
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/storyboard-frames")
async def list_storyboard_frames(
    project_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
) -> dict:
    """列出当前激活 storyboard 版本的所有帧（带资产预签名 URL）。"""
    req_id = get_request_id(request)

    async with UnitOfWork() as uow:
        session = uow.session
        version_repo = StoryboardVersionRepository(session)
        frame_repo = StoryboardFrameRepository(session)
        asset_repo = AssetRepository(session)

        version = await version_repo.get_active(project_id)
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "当前项目没有激活的 storyboard 版本"},
            )

        frames = await frame_repo.list_by_version(
            version.id, limit=limit, offset=offset
        )
        total = await frame_repo.count_by_version(version.id)

        # 批量加载 Asset，统一转为当前可访问 URL（私有 OSS 下为签名 URL）
        asset_ids = [f.asset_id for f in frames]
        assets = await asset_repo.list_by_ids(asset_ids)
        asset_map = await build_asset_access_url_map(assets)

    frame_list = []
    for frame in frames:
        frame_list.append({
            "id": frame.id,
            "shot_id": frame.shot_id,
            "asset_id": frame.asset_id,
            "storage_uri": asset_map.get(frame.asset_id),
            "prompt_bundle_id": frame.prompt_bundle_id,
            "frame_index": frame.frame_index,
            "parent_asset_id": frame.parent_asset_id,
            "cell_position": frame.cell_position,
            "grid_index": frame.grid_index,
            "metadata": frame.metadata_,
            "created_at": frame.created_at.isoformat() if frame.created_at else None,
        })

    return ok(
        data={
            "storyboard_version_id": version.id,
            "version_no": version.version_no,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(frame_list)) < total,
            "frames": frame_list,
        },
        request_id=req_id,
    )


# ---------------------------------------------------------------------------
# GET /storyboard/grids（doc 21 §6 九宫格架构）
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/storyboard/grids")
async def get_storyboard_grids(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回当前激活 storyboard 的所有九宫格大图 + 9×N 切分图 URL（doc 21 §6.3）。

    返回结构：
        {
          "storyboard_version_id": str,
          "version_no": int,
          "grid_count": int,
          "total_shots": int,
          "grids": [
            {
              "grid_index": 1,
              "parent_asset_id": "...",     // 大图 asset_id
              "parent_asset_url": "...",    // 大图 storage_uri
              "bundle_id": "...",
              "cells": [
                {
                  "cell_position": 1,
                  "asset_id": "...",
                  "asset_url": "...",
                  "is_reused_from_prev_grid": false  // 当前版本固定 false，仅兼容历史字段
                }, ...
              ]
            }, ...
          ]
        }

    数据来源：StoryboardVersion.raw_payload['grids']（由 StoryboardService 写入）。
    """
    req_id = get_request_id(request)

    async with UnitOfWork() as uow:
        session = uow.session
        version_repo = StoryboardVersionRepository(session)
        prompt_repo = PromptBundleRepository(session)

        version = await version_repo.get_active(project_id)
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "not_found",
                    "message": "当前项目没有激活的 storyboard 版本",
                },
            )

        raw = version.raw_payload or {}
        grids_meta = raw.get("grids") or []
        grid_count = raw.get("grid_count") or 0
        total_shots = raw.get("total_shots") or 0

        asset_ids: set[str] = set()
        for grid in grids_meta:
            parent_asset_id = grid.get("parent_asset_id")
            if parent_asset_id:
                asset_ids.add(parent_asset_id)
            for cell in grid.get("cells") or []:
                cell_asset_id = cell.get("asset_id")
                if cell_asset_id:
                    asset_ids.add(cell_asset_id)
        assets = await AssetRepository(session).list_by_ids(list(asset_ids)) if asset_ids else []
        asset_url_map = await build_asset_access_url_map(assets)

        enriched_grids: list[dict] = []
        for grid in grids_meta:
            bundle_id = grid.get("bundle_id")
            prompt_bundle = (
                await prompt_repo.get_latest_for_target(
                    "nine_grid_image",
                    f"grid_{int(grid.get('grid_index') or 0):03d}",
                )
                if grid.get("grid_index")
                else None
            )
            cells = []
            for cell in grid.get("cells") or []:
                cells.append({
                    **cell,
                    "asset_url": asset_url_map.get(cell.get("asset_id"), cell.get("asset_url")),
                })
            enriched_grids.append({
                **grid,
                "parent_asset_url": asset_url_map.get(
                    grid.get("parent_asset_id"),
                    grid.get("parent_asset_url"),
                ),
                "cells": cells,
                "prompt_bundle": (
                    {
                        "bundle_id": prompt_bundle.id,
                        "target_type": prompt_bundle.target_type,
                        "target_id": prompt_bundle.target_id,
                        "provider": prompt_bundle.provider,
                        "positive_prompt": prompt_bundle.positive_prompt,
                        "negative_prompt": prompt_bundle.negative_prompt,
                        "params": prompt_bundle.params,
                    }
                    if prompt_bundle is not None
                    else None
                ),
                "bundle_id": bundle_id,
            })

    return ok(
        data={
            "storyboard_version_id": version.id,
            "version_no": version.version_no,
            "grid_count": grid_count,
            "total_shots": total_shots,
            "grids": enriched_grids,
        },
        request_id=req_id,
    )
