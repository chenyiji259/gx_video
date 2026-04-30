"""Unit of Work（工作单元）模式实现。

文档约束（doc 08 §4 / doc 03 §2）：
  Service 层通过 UoW 管理事务边界，不直接操作 engine 或 sessionmaker。
  UoW 不持有业务 Repository 实例，Repository 由 Service 使用 uow.session 按需创建。

设计原则：
  - UoW 只负责事务生命周期（begin / commit / rollback / close）
  - Repository 通过 uow.session 独立创建，保持松耦合
  - 支持嵌套事务场景（savepoint）通过 begin_nested()

典型用法：
    async with UnitOfWork() as uow:
        user_repo = UserRepository(uow.session)
        project_repo = ProjectRepository(uow.session)

        user = User(username="alice", ...)
        await user_repo.add(user)

        project = Project(user_id=user.id, ...)
        await project_repo.add(project)
    # 退出 with 块：commit（无异常）或 rollback（有异常）
"""
from __future__ import annotations

from types import TracebackType
from typing import Optional, Type

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.core.logging import get_logger

_logger = get_logger("repositories.unit_of_work", layer="system")


class UnitOfWork:
    """异步工作单元，管理一次完整的业务事务边界。

    用法（async context manager）：
        async with UnitOfWork() as uow:
            repo = SomeRepository(uow.session, SomeModel)
            ...
        # 正常退出 → commit；异常 → rollback

    手动控制（可选）：
        uow = UnitOfWork()
        await uow.begin()
        try:
            ...
            await uow.commit()
        except Exception:
            await uow.rollback()
        finally:
            await uow.close()
    """

    def __init__(self) -> None:
        self._session: Optional[AsyncSession] = None

    # ------------------------------------------------------------------ #
    # Async context manager 接口
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "UnitOfWork":
        await self.begin()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()
        await self.close()

    # ------------------------------------------------------------------ #
    # 生命周期方法
    # ------------------------------------------------------------------ #

    async def begin(self) -> None:
        """创建 session 并开启事务。"""
        if self._session is not None:
            raise RuntimeError("UnitOfWork 已开启，不能重复调用 begin()")
        self._session = get_session_factory()()

    async def commit(self) -> None:
        """提交当前事务。"""
        if self._session is None:
            raise RuntimeError("UnitOfWork 未开启，请先调用 begin()")
        await self._session.commit()

    async def rollback(self) -> None:
        """回滚当前事务。"""
        if self._session is None:
            return
        await self._session.rollback()

    async def close(self) -> None:
        """关闭 session，归还连接池。"""
        if self._session is not None:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------ #
    # Session 访问
    # ------------------------------------------------------------------ #

    @property
    def session(self) -> AsyncSession:
        """当前事务的 AsyncSession，供 Repository 使用。

        Raises:
            RuntimeError: 未通过 begin() 或 async with 初始化时。
        """
        if self._session is None:
            raise RuntimeError(
                "UnitOfWork 未开启。请使用 'async with UnitOfWork() as uow:' 语法，"
                "或先调用 await uow.begin()。"
            )
        return self._session

    # ------------------------------------------------------------------ #
    # 工具方法
    # ------------------------------------------------------------------ #

    async def flush(self) -> None:
        """刷新 session（不 commit）。在同一事务内需要数据库生成值时使用。"""
        await self.session.flush()
