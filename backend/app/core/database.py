"""数据库连接与会话管理（SQLAlchemy 2.x 异步）。

文档约束（doc 02 / doc 08）：
  - 使用 SQLAlchemy 2.x 异步引擎（asyncpg 驱动）
  - 连接参数来自 settings（最终读 config/base/database.yaml）
  - 提供两种会话入口：
      1. get_db_session() —— FastAPI Depends() 用，请求级自动 commit/rollback
      2. transaction() —— Service / UoW 层显式事务上下文
  - engine 是全局单例，在应用生命周期内保持连接池

启动命令（提醒）：
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.logging import get_logger
from app.core.settings import settings

_logger = get_logger("core.database", layer="system")


# ---------------------------------------------------------------------------
# 异步引擎（懒加载单例）
# ---------------------------------------------------------------------------
# 不在模块级直接创建 engine，避免 import 时触发配置读取和连接创建。
# 测试环境无数据库时，只要不调用 get_engine()/get_session_factory() 就不会报错。

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine() -> AsyncEngine:
    """根据 settings 构建异步 engine。"""
    url = settings.get_database_url()   # postgresql+asyncpg://...
    return create_async_engine(
        url,
        # 连接池：min_size 个常驻连接，超出后可临时扩展到 max_size
        pool_size=settings.postgres_pool_min,
        max_overflow=settings.postgres_pool_max - settings.postgres_pool_min,
        # pool_pre_ping：每次借用连接前先发 SELECT 1，防止僵尸连接
        pool_pre_ping=True,
        # debug 模式下把 SQL 语句打印到日志，便于排查
        echo=settings.debug,
    )


def get_engine() -> AsyncEngine:
    """返回全局 AsyncEngine 单例（首次调用时创建）。"""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


# ---------------------------------------------------------------------------
# Session 工厂（懒加载）
# ---------------------------------------------------------------------------

def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """返回全局 AsyncSessionFactory 单例（首次调用时创建）。"""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            # expire_on_commit=False：commit 后实例不失效，避免访问属性时触发懒加载
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


# 向后兼容别名：允许现有代码继续使用 AsyncSessionFactory()
class _LazySessionFactory:
    """代理类，将 AsyncSessionFactory() 调用透明转发给懒加载工厂。"""
    def __call__(self) -> AsyncSession:
        return get_session_factory()()
    def __repr__(self) -> str:
        return "AsyncSessionFactory(lazy)"


AsyncSessionFactory = _LazySessionFactory()


# ---------------------------------------------------------------------------
# FastAPI Depends() 会话依赖（请求级）
# ---------------------------------------------------------------------------

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 路由层的 session 依赖。

    用法：
        @router.post("/projects")
        async def create_project(
            session: AsyncSession = Depends(get_db_session),
        ):
            ...

    生命周期：
        - 请求处理正常结束 → 自动 commit
        - 抛出异常 → 自动 rollback
        - 无论如何 → 关闭 session（归还连接池）
    """
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Service / UoW 层显式事务上下文
# ---------------------------------------------------------------------------

@asynccontextmanager
async def transaction() -> AsyncGenerator[AsyncSession, None]:
    """Service 层主动控制事务的上下文管理器。

    与 get_db_session 的区别：
      - get_db_session 适合 HTTP 请求层（FastAPI Depends）
      - transaction() 适合需要跨多个 Repository 操作的 Service 层事务

    用法：
        async with transaction() as session:
            user = User(...)
            session.add(user)
            project = Project(user_id=user.id, ...)
            session.add(project)
        # 退出 with 块时自动 commit（无异常）或 rollback（有异常）

    注意：
        内部使用 session.begin() 开启显式事务，不依赖 SQLAlchemy autobegin。
    """
    async with get_session_factory()() as session:
        async with session.begin():
            try:
                yield session
            except Exception:
                # session.begin() 的 __aexit__ 会处理 rollback，
                # 这里 raise 即可让外层感知异常
                raise
