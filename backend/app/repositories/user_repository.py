"""User Repository — 用户数据访问层。

只做纯数据查询，不承载业务判断（doc 08 §4 分层规范）。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """用户仓库，继承 BaseRepository 通用 CRUD。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_username(self, username: str) -> User | None:
        """按用户名查询，用于登录校验。大小写敏感（与数据库 varchar 一致）。"""
        stmt = select(User).where(User.username == username)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: str) -> User | None:  # type: ignore[override]
        """按主键查询，覆盖基类以明确类型提示。"""
        return await self._session.get(User, user_id)
