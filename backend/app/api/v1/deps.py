"""API 公共依赖层。

doc 05 §17.2 定义的统一控制面 API 规范：
  - 成功响应: {"success": true, "data": {...}, "request_id": "..."}
  - 失败响应: {"success": false, "error": {"code": "...", "message": "..."}, "request_id": "..."}

此模块提供：
  1. ApiResponse       - 统一响应 Pydantic 模型
  2. ok()              - 封装成功响应
  3. err()             - 封装失败响应（通常用于异常处理器）
  4. get_request_id()  - 每请求生成唯一追踪 ID（从 X-Request-Id 头读取或自动生成）
  5. get_current_user  - FastAPI Depends，从 Authorization Bearer 解析当前用户

用法：
    @router.post("/projects")
    async def create_project(
        req: Request,
        current_user: User = Depends(get_current_user),
    ):
        ...
        return ok(data={"project_id": "..."}, request_id=get_request_id(req))
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import get_db_session
from app.core.logging import get_logger
from app.core.security import TokenDecodeError, get_user_id_from_token
from app.models.user import User
from app.utils.ids import generate_ulid

_logger = get_logger("api.deps", layer="system")

# ---------------------------------------------------------------------------
# 统一响应结构
# ---------------------------------------------------------------------------

def ok(data: Any = None, request_id: str | None = None) -> dict:
    """构建成功响应 dict（doc 05 §17.2）。

    Args:
        data: 响应主体，任意可序列化对象。
        request_id: 本次请求 ID，用于追踪。

    Returns:
        {"success": True, "data": data, "request_id": request_id}
    """
    return {
        "success": True,
        "data": data if data is not None else {},
        "request_id": request_id or generate_ulid(),
    }


def err(code: str, message: str, request_id: str | None = None) -> dict:
    """构建失败响应 dict（doc 05 §17.2）。

    通常用于异常处理器中手动返回，业务代码更推荐直接 raise HTTPException。
    """
    return {
        "success": False,
        "error": {"code": code, "message": message},
        "request_id": request_id or generate_ulid(),
    }


# ---------------------------------------------------------------------------
# Request ID
# ---------------------------------------------------------------------------

def get_request_id(request: Request) -> str:
    """获取本次请求 ID。

    优先从 X-Client-Request-Id 请求头读取（前端自定义），
    否则自动生成一个新 ULID。
    """
    client_req_id = request.headers.get("x-client-request-id")
    return client_req_id or generate_ulid()


# ---------------------------------------------------------------------------
# Bearer Token 依赖
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


async def _get_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """从 Authorization 头提取 Bearer token 字符串。

    Raises:
        HTTPException 401: 未提供 token。
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Missing Authorization header"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


# ---------------------------------------------------------------------------
# 当前用户依赖（需要在 auth_service 可用后，UserRepository 落地）
# ---------------------------------------------------------------------------
# 注意：get_current_user 依赖 UserRepository，因此在这里做懒导入，
# 避免循环依赖（api -> deps -> repositories -> models -> 都 OK）。

async def get_current_user(
    token: str = Depends(_get_token),
) -> User:
    """FastAPI 依赖：解析 access token 并返回当前用户 ORM 对象。

    Raises:
        HTTPException 401: token 无效或已过期。
        HTTPException 401: 用户不存在。
    """
    # Lazy import to avoid module-level circular dependency risk
    from app.repositories.user_repository import UserRepository
    from app.core.database import get_session_factory

    try:
        user_id = get_user_id_from_token(token, expected_type="access")
    except TokenDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": str(e)},
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    async with get_session_factory()() as session:
        repo = UserRepository(session)
        user = await repo.get_by_id(user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "User not found"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "message": "User account is disabled"},
        )
    return user
