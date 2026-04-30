"""项目 CRUD API（doc 05 §17.4）。

接口：
  POST   /projects             - 创建项目
  GET    /projects             - 项目列表（分页）
  GET    /projects/{id}        - 项目详情
  PATCH  /projects/{id}        - 重命名/归档

工程约束：
  - 所有接口必须携带 Bearer token（get_current_user 依赖）
  - 项目按 user_id 隔离，不允许跨用户访问（R4）
  - 响应格式统一为 ok/err（doc 05 §17.2）
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.core.logging import get_logger
from app.models.user import User
from app.services.project_service import ProjectError, ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])
_logger = get_logger("api.projects", layer="system")


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="项目名称")


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="新项目名称")
    archived: Optional[bool] = Field(None, description="true=归档, false=恢复")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(
    body: CreateProjectRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """创建新项目，初始阶段为 'created'。"""
    req_id = get_request_id(request)
    try:
        project = await ProjectService().create_project(
            user_id=current_user.id,
            name=body.name,
        )
    except ProjectError as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=ok(data=project, request_id=req_id),
    )


@router.get("")
async def list_projects(
    request: Request,
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100, description="每页条数"),
    after: Optional[str] = Query(default=None, description="游标分页：上一页最后一条项目 ID"),
    include_archived: bool = Query(default=False, description="是否包含已归档项目"),
) -> dict:
    """查询当前用户的项目列表（游标分页，按 updated_at desc）。"""
    req_id = get_request_id(request)
    result = await ProjectService().list_projects(
        user_id=current_user.id,
        limit=limit,
        after_id=after,
        include_archived=include_archived,
    )
    return ok(data=result, request_id=req_id)


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """查询单个项目详情（含 active version 指针和 pipeline 阶段）。"""
    req_id = get_request_id(request)
    try:
        project = await ProjectService().get_project(
            project_id=project_id,
            user_id=current_user.id,
        )
    except ProjectError as e:
        http_status = status.HTTP_404_NOT_FOUND if e.code == "not_found" else status.HTTP_422_UNPROCESSABLE_ENTITY
        return JSONResponse(
            status_code=http_status,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ok(data=project, request_id=req_id),
    )


@router.patch("/{project_id}")
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """更新项目名称或归档状态（doc 05 §17.4 PATCH 只允许 name/archived）。"""
    req_id = get_request_id(request)

    # 如果两个字段都没传，提前返回
    if body.name is None and body.archived is None:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "error": {"code": "validation_error", "message": "至少需要提供 name 或 archived 中的一个字段"},
                "request_id": req_id,
            },
        )

    try:
        project = await ProjectService().update_project(
            project_id=project_id,
            user_id=current_user.id,
            name=body.name,
            archived=body.archived,
        )
    except ProjectError as e:
        http_status = status.HTTP_404_NOT_FOUND if e.code == "not_found" else status.HTTP_422_UNPROCESSABLE_ENTITY
        return JSONResponse(
            status_code=http_status,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ok(data=project, request_id=req_id),
    )


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """永久删除项目（doc 11 补充）。"""
    req_id = get_request_id(request)
    try:
        await ProjectService().delete_project(
            project_id=project_id,
            user_id=current_user.id,
        )
    except ProjectError as e:
        http_status = status.HTTP_404_NOT_FOUND if e.code == "not_found" else status.HTTP_422_UNPROCESSABLE_ENTITY
        return JSONResponse(
            status_code=http_status,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )
    return ok(data={"id": project_id}, request_id=req_id)
