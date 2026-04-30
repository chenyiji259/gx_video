"""鉴权 API（doc 05 §17.3）。

接口：
  POST /auth/login   - 用户名/密码登录，返回 access + refresh token
  POST /auth/refresh - refresh token 换新 access token
  POST /auth/logout  - 客户端登出（服务端无状态，仅告知清理本地存储）

工程约束：
  - 无注册接口（第一版不对外开放注册）
  - 无 token 黑名单（MVP 阶段，token 靠短 expire 自然过期）
  - 统一响应格式 ok/err（doc 05 §17.2）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.core.logging import get_logger
from app.models.user import User
from app.services.auth_service import AuthError, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
_logger = get_logger("api.auth", layer="system")


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/register")
async def register(body: RegisterRequest, request: Request) -> JSONResponse:
    """注册新账号并自动下发 Token。"""
    req_id = get_request_id(request)
    try:
        await AuthService().create_user(body.username, body.password)
        result = await AuthService().login(body.username, body.password)
    except AuthError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "success": False,
                "error": {"code": e.code, "message": e.message},
                "request_id": req_id,
            },
        )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=ok(data=result, request_id=req_id),
    )


@router.post("/login")
async def login(body: LoginRequest, request: Request) -> JSONResponse:
    """用户名密码登录。

    返回 access_token（短期）和 refresh_token（长期）。
    """
    req_id = get_request_id(request)
    try:
        result = await AuthService().login(body.username, body.password)
    except AuthError as e:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "success": False,
                "error": {"code": e.code, "message": e.message},
                "request_id": req_id,
            },
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ok(data=result, request_id=req_id),
    )


@router.post("/refresh")
async def refresh(body: RefreshRequest, request: Request) -> JSONResponse:
    """用 refresh token 换取新的 access token。"""
    req_id = get_request_id(request)
    try:
        result = await AuthService().refresh_token(body.refresh_token)
    except AuthError as e:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "success": False,
                "error": {"code": e.code, "message": e.message},
                "request_id": req_id,
            },
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ok(data=result, request_id=req_id),
    )


@router.post("/logout")
async def logout(
    request: Request,
    _current_user: User = Depends(get_current_user),
) -> dict:
    """登出（服务端无状态，仅返回成功，客户端应清除本地 token）。"""
    return ok(
        data={"message": "Logged out successfully"},
        request_id=get_request_id(request),
    )
