"""Repository 基类（通用异步 CRUD）。

文档约束（doc 08 §4 分层规范）：
  Service 层不直接操作 session，通过 Repository 访问数据库。
  Repository 不承载业务判断，只做数据存取。
  Agent 不能直接写数据库（doc 06 §4 边界约束）。

设计模式：
  BaseRepository[T] 是泛型基类，提供最小 CRUD 接口。
  子类按需覆盖或添加特定查询方法。

用法示例：
    class UserRepository(BaseRepository[User]):
        async def get_by_username(self, username: str) -> User | None:
            stmt = select(User).where(User.username == username)
            result = await self._session.execute(stmt)
            return result.scalar_one_or_none()

    # 在 Service 层
    async with UnitOfWork() as uow:
        repo = UserRepository(uow.session)
        user = await repo.get_by_id(user_id)
"""
from __future__ import annotations

from typing import Any, Generic, Sequence, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

# 泛型类型变量，绑定到 Base 子类（所有 ORM 模型）
T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """通用异步 Repository 基类。

    子类必须传入对应的 model_class。
    """

    def __init__(self, session: AsyncSession, model_class: Type[T]) -> None:
        self._session = session
        self._model = model_class

    # ------------------------------------------------------------------ #
    # 基础读操作
    # ------------------------------------------------------------------ #

    async def get_by_id(self, entity_id: str) -> T | None:
        """按主键查询单条记录。"""
        return await self._session.get(self._model, entity_id)

    async def get_all(self, *, limit: int = 100, offset: int = 0) -> Sequence[T]:
        """查询全部记录（带分页，仅用于简单场景）。"""
        stmt = select(self._model).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def exists(self, entity_id: str) -> bool:
        """检查指定 ID 的记录是否存在。"""
        entity = await self.get_by_id(entity_id)
        return entity is not None

    # ------------------------------------------------------------------ #
    # 基础写操作
    # ------------------------------------------------------------------ #

    async def add(self, entity: T) -> T:
        """将实体加入 session（等待 flush/commit 落库）。"""
        self._session.add(entity)
        return entity

    async def add_all(self, entities: list[T]) -> list[T]:
        """批量加入 session。"""
        self._session.add_all(entities)
        return entities

    async def delete(self, entity: T) -> None:
        """删除实体（等待 flush/commit 落库）。"""
        await self._session.delete(entity)

    # ------------------------------------------------------------------ #
    # 工具方法
    # ------------------------------------------------------------------ #

    async def flush(self) -> None:
        """主动 flush，将 session 中的变更写入数据库（但不 commit）。

        用于需要在同一事务内拿到数据库生成值（如 server_default）的场景。
        """
        await self._session.flush()

    async def refresh(self, entity: T) -> T:
        """从数据库刷新实体状态（获取 server_default 等数据库生成字段）。"""
        await self._session.refresh(entity)
        return entity

    @property
    def session(self) -> AsyncSession:
        """暴露底层 session，供子类做复杂查询时直接使用。"""
        return self._session
