"""Redis 连接 URL 构建工具 + 全局共享连接池。

来源文档：doc 02 §13.1（后端技术栈：Redis）、doc 08 §6.2（config/base/redis.yaml）

设计原则：
  全应用共享一个 Redis ConnectionPool（单例），避免各服务各自建池导致
  连接数膨胀（原来 5 个服务 × 默认 50 连接 = 最多 250 连接）。
  30-40 并发用户下，共享池 max_connections=50 绰绰有余。

使用方式：
    from app.core.redis_utils import get_redis_client

    redis = get_redis_client()
    await redis.set("key", "value")
"""
from __future__ import annotations

import redis.asyncio as aioredis

from app.core.config import get_config

# 全局单例（由 get_redis_client() 懒初始化）
_redis_client: aioredis.Redis | None = None

# 共享连接池大小（覆盖 redis.yaml pool.max_connections）
_POOL_MAX_CONNECTIONS = 50


def build_redis_url() -> str:
    """根据配置构建 Redis 连接 URL。

    格式：
      - 有密码：``redis://:{password}@{host}:{port}/{db}``
      - 无密码：``redis://{host}:{port}/{db}``

    密码不以明文出现在日志中（URL 本身不应直接打印）。

    Returns:
        str: Redis 连接 URL 字符串。
    """
    cfg = get_config().redis
    if cfg.password:
        return f"redis://:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.db}"
    return f"redis://{cfg.host}:{cfg.port}/{cfg.db}"


def get_redis_client() -> aioredis.Redis:
    """返回全局共享的 Redis 客户端（连接池复用）。

    首次调用时初始化连接池，后续复用同一实例。
    所有服务（ConcurrencyGuard / Dispatcher / Worker / OutboxPublisher）
    共享此连接池，避免各自建池导致连接数膨胀。

    线程安全说明：
      FastAPI/uvicorn 在单进程 asyncio 环境下运行，无并发初始化问题。

    Returns:
        aioredis.Redis: 共享 Redis 客户端实例。
    """
    global _redis_client
    if _redis_client is None:
        pool = aioredis.ConnectionPool.from_url(
            build_redis_url(),
            encoding="utf-8",
            decode_responses=True,
            max_connections=_POOL_MAX_CONNECTIONS,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30,
            retry_on_timeout=True,
        )
        _redis_client = aioredis.Redis(connection_pool=pool)
    return _redis_client


async def close_redis_client() -> None:
    """关闭全局 Redis 连接池（在 lifespan shutdown 时调用）。"""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
