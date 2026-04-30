"""资产上传 API（doc 05 §17.5）。

接口：
  POST /projects/{project_id}/assets/upload-init  - 获取对象存储 PUT 预签名 URL
  POST /projects/{project_id}/assets/complete     - 确认上传完成，落库 Asset
  GET  /projects/{project_id}/assets              - 列出项目资产

上传流程说明（两步式）：
  1. 客户端 POST upload-init 拿到 upload_url + asset_id + object_key
  2. 客户端直接 PUT 文件到 upload_url（绕过后端，直传对象存储）
  3. 客户端 POST complete 告知后端上传完成
  4. 后端核验对象存在 → 落库 → 本地追溯副本 → 返回 asset（含永久 storage_uri）
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.user import User
from app.services.asset_service import AssetError, AssetService

router = APIRouter(
    prefix="/projects/{project_id}/assets",
    tags=["assets"],
)


global_router = APIRouter(
    prefix="/assets",
    tags=["assets"],
)


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class UploadInitRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=256, description="原始文件名（含扩展名）")
    content_type: str = Field(..., min_length=1, max_length=128, description="文件 MIME 类型")
    asset_type: Optional[str] = Field(
        None,
        description="资产类型，留空时由后端根据 content_type 自动推断",
    )


class CompleteUploadRequest(BaseModel):
    asset_id: str = Field(..., description="upload-init 返回的 asset_id")
    object_key: str = Field(..., description="upload-init 返回的 object_key")
    bucket_name: str = Field(..., description="upload-init 返回的 bucket_name")
    filename: str = Field(..., min_length=1, max_length=256, description="原始文件名")
    content_type: str = Field(..., min_length=1, max_length=128, description="文件 MIME 类型")
    asset_type: str = Field(..., description="资产类型")
    # 可选媒体元信息（客户端可选填）
    sha256: Optional[str] = Field(None, max_length=64, description="文件 SHA-256（用于去重）")
    duration_ms: Optional[int] = Field(None, ge=0, description="音视频时长（毫秒）")
    width: Optional[int] = Field(None, ge=0, description="图片/视频宽度（像素）")
    height: Optional[int] = Field(None, ge=0, description="图片/视频高度（像素）")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/upload-init", status_code=status.HTTP_200_OK)
async def upload_init(
    project_id: str,
    body: UploadInitRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """步骤一：申请上传槽位，返回对象存储 PUT 预签名 URL。

    客户端拿到 upload_url 后，直接 PUT 文件到该 URL（无需通过后端中转）。
    upload_url 有效期 30 分钟。
    """
    req_id = get_request_id(request)
    try:
        result = await AssetService().upload_init(
            project_id=project_id,
            user_id=current_user.id,
            filename=body.filename,
            content_type=body.content_type,
            asset_type=body.asset_type,
        )
    except AssetError as e:
        http_status = (
            status.HTTP_404_NOT_FOUND
            if e.code == "not_found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return JSONResponse(
            status_code=http_status,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ok(data=result, request_id=req_id),
    )


@router.post("/complete", status_code=status.HTTP_201_CREATED)
async def complete_upload(
    project_id: str,
    body: CompleteUploadRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """步骤二：确认上传完成，落库 Asset 记录，返回含访问 URL 的资产信息。

    后端会：
      1. 核验对象存储中对象真实存在
      2. 落库 Asset 记录（storage_uri 为永久直链）
      3. 同步本地追溯副本（01_input/）
    """
    req_id = get_request_id(request)
    try:
        asset = await AssetService().complete_upload(
            project_id=project_id,
            user_id=current_user.id,
            asset_id=body.asset_id,
            object_key=body.object_key,
            bucket_name=body.bucket_name,
            filename=body.filename,
            content_type=body.content_type,
            asset_type=body.asset_type,
            sha256=body.sha256,
            duration_ms=body.duration_ms,
            width=body.width,
            height=body.height,
        )
    except AssetError as e:
        http_status = (
            status.HTTP_404_NOT_FOUND
            if e.code == "not_found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return JSONResponse(
            status_code=http_status,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=ok(data=asset, request_id=req_id),
    )


@router.get("", status_code=status.HTTP_200_OK)
async def list_assets(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    asset_type: Optional[str] = Query(default=None, description="按资产类型过滤"),
    limit: int = Query(default=50, ge=1, le=200, description="最多返回条数"),
) -> dict:
    """列出项目下的资产（按创建时间倒序）。"""
    req_id = get_request_id(request)
    try:
        assets = await AssetService().list_assets(
            project_id=project_id,
            user_id=current_user.id,
            asset_type=asset_type,
            limit=limit,
        )
    except AssetError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )
    return ok(data={"items": assets, "count": len(assets)}, request_id=req_id)


@global_router.get("", status_code=status.HTTP_200_OK)
async def list_global_assets(
    request: Request,
    current_user: User = Depends(get_current_user),
    asset_type: Optional[str] = Query(default=None, description="按资产类型过滤"),
    limit: int = Query(default=100, ge=1, le=500, description="最多返回条数"),
) -> dict:
    """全局拉取当前用户所有项目的所有资产。"""
    req_id = get_request_id(request)
    assets = await AssetService().list_all_assets_for_user(
        user_id=current_user.id,
        asset_type=asset_type,
        limit=limit,
    )
    return ok(data={"items": assets, "count": len(assets)}, request_id=req_id)
