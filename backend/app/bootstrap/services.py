"""Service health checks and dependency management.

负责在应用启动/关闭时检查 Postgres / Redis / OSS 连通性。
"""
import asyncio
from typing import Optional

import asyncpg
import redis.asyncio as aioredis

from app.core.logging import get_logger
from app.core.settings import settings
from app.storage.storage_factory import get_storage

_logger = get_logger("bootstrap.services", layer="system")


class ServiceManager:
    """管理外部服务连接与健康检查。"""

    def __init__(self) -> None:
        self.pg_pool: Optional[asyncpg.Pool] = None
        self.redis_client: Optional[aioredis.Redis] = None
        self.storage_client: Optional[object] = None

    async def check_postgres(self) -> bool:
        """检查 PostgreSQL 连通性。"""
        try:
            self.pg_pool = await asyncpg.create_pool(
                host=settings.postgres_host,
                port=settings.postgres_port,
                user=settings.postgres_user,
                password=settings.postgres_password,
                database=settings.postgres_db,
                min_size=settings.postgres_pool_min,
                max_size=settings.postgres_pool_max,
            )
            async with self.pg_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            _logger.error(f"Postgres 连接检查失败: {e}", event_type="dependency_check_failed")
            return False

    async def check_redis(self) -> bool:
        """检查 Redis 连通性。"""
        try:
            self.redis_client = aioredis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                password=settings.redis_password or None,
                db=settings.redis_db,
                decode_responses=True,
            )
            await self.redis_client.ping()
            return True
        except Exception as e:
            _logger.error(f"Redis 连接检查失败: {e}", event_type="dependency_check_failed")
            return False

    async def check_storage(self) -> bool:
        """检查对象存储连通性。"""
        try:
            self.storage_client = get_storage()
            await self.storage_client.async_object_exists(
                ".health_probe",
                bucket=settings.storage_bucket,
            )
            return True
        except Exception as e:
            _logger.error(f"对象存储连接检查失败: {e}", event_type="dependency_check_failed")
            return False

    async def check_all(self) -> dict[str, bool]:
        """并发检查所有依赖服务，返回各服务状态。"""
        pg_ok, redis_ok, storage_ok = await asyncio.gather(
            self.check_postgres(),
            self.check_redis(),
            self.check_storage(),
        )
        results = {"postgres": pg_ok, "redis": redis_ok, "storage": storage_ok}
        all_ok = all(results.values())
        status = "全部正常" if all_ok else "部分服务不可用"
        _logger.info(
            "依赖检查完成 - " + status + ": " + str(results),
            event_type="dependency_check_completed",
        )
        return results

    async def close(self) -> None:
        """应用关闭时释放连接。"""
        if self.pg_pool:
            await self.pg_pool.close()
        if self.redis_client:
            await self.redis_client.aclose()


service_manager = ServiceManager()


def initialize_storage_singleton() -> None:
    """应用启动时显式初始化 OSS 存储单例。

    将原来的懒加载单例改为在启动阶段一次性初始化，
    避免运行期并发路径下重复创建客户端的风险。
    """
    get_storage()
    _logger.info("存储客户端已初始化", event_type="storage_singleton_init")
