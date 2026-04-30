"""Auth Service — 鉴权业务逻辑。

职责：
  - login(): 校验用户名/密码，签发 access + refresh token，更新 last_login_at
  - refresh_token(): 用 refresh token 换取新 access token
  - create_user(): 创建新用户（供 seed 脚本使用，无对外注册接口）

工程约束：
  - Service 通过 UnitOfWork 管理事务，不直接操作 session（doc 08 §4）
  - 不存明文密码（doc 08 R2）
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.logging import get_logger
from app.core.security import (
    TokenDecodeError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.repositories.unit_of_work import UnitOfWork
from app.repositories.user_repository import UserRepository
from app.utils.ids import generate_ulid

_logger = get_logger("services.auth", layer="system")


class AuthError(Exception):
    """鉴权业务异常（用于区分系统异常与业务逻辑失败）。"""
    def __init__(self, message: str, code: str = "auth_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AuthService:
    """鉴权服务。每次请求实例化，通过 UoW 管理事务。"""

    # ------------------------------------------------------------------ #
    # 登录
    # ------------------------------------------------------------------ #

    async def login(self, username: str, password: str) -> dict:
        """校验用户名和密码，返回 token pair。

        Returns:
            {
                "access_token": "...",
                "refresh_token": "...",
                "token_type": "bearer",
                "user": {"id": "...", "username": "..."}
            }

        Raises:
            AuthError: 用户不存在或密码错误（统一返回相同错误，防止用户名枚举）。
        """
        async with UnitOfWork() as uow:
            repo = UserRepository(uow.session)
            user = await repo.get_by_username(username)

            if user is None or not verify_password(password, user.password_hash):
                _logger.warning(
                    f"Login failed for username={username!r}",
                    event_type="login_failed",
                )
                raise AuthError("用户名或密码错误", code="invalid_credentials")

            if user.status != "active":
                raise AuthError("账号已禁用", code="account_disabled")

            # 更新最后登录时间
            user.last_login_at = datetime.now(timezone.utc)

        # 事务已提交，现在签发 token（不在事务内，避免 token 签发异常回滚登录记录）
        access_token = create_access_token(user.id)
        refresh_token = create_refresh_token(user.id)

        _logger.info(
            f"Login successful for user_id={user.id!r}",
            event_type="login_success",
        )
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {"id": user.id, "username": user.username, "credits": getattr(user, 'credits', 200), "plan_type": getattr(user, 'plan_type', 'free')},
        }

    # ------------------------------------------------------------------ #
    # 刷新 access token
    # ------------------------------------------------------------------ #

    async def refresh_token(self, refresh_token_str: str) -> dict:
        """用有效的 refresh token 换取新的 access token。

        Returns:
            {"access_token": "...", "token_type": "bearer"}

        Raises:
            AuthError: refresh token 无效、已过期或用户不存在。
        """
        try:
            payload = decode_token(refresh_token_str, expected_type="refresh")
        except TokenDecodeError as e:
            raise AuthError(str(e), code="invalid_token") from e

        user_id = payload["sub"]

        # 确认用户还存在且处于活跃状态
        async with UnitOfWork() as uow:
            repo = UserRepository(uow.session)
            user = await repo.get_by_id(user_id)

        if user is None or user.status != "active":
            raise AuthError("用户不存在或已禁用", code="invalid_token")

        new_access_token = create_access_token(user_id)
        return {"access_token": new_access_token, "token_type": "bearer"}

    # ------------------------------------------------------------------ #
    # 创建用户（仅供 seed 脚本或管理员使用）
    # ------------------------------------------------------------------ #

    async def create_user(self, username: str, password: str) -> User:
        """创建新用户，密码自动哈希。

        Args:
            username: 用户名，必须唯一。
            password: 明文密码。

        Returns:
            已持久化的 User ORM 对象。

        Raises:
            AuthError: 用户名已存在。
        """
        async with UnitOfWork() as uow:
            repo = UserRepository(uow.session)
            existing = await repo.get_by_username(username)
            if existing is not None:
                raise AuthError(f"用户名 '{username}' 已存在", code="username_taken")

            user = User(
                id=generate_ulid(),
                username=username,
                password_hash=hash_password(password),
                status="active",
            )
            await repo.add(user)
            await uow.flush()
            await uow.session.refresh(user)

        _logger.info(
            f"User created: id={user.id!r} username={user.username!r}",
            event_type="user_created",
        )
        return user
