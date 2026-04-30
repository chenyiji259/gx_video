"""Health check 与 Readiness 接口。

来源文档：doc 08 §12（开发阶段 依赖检查要求）

接口分两个层次（标准 K8s 语义）：
  GET /health    Liveness Probe：进程是否存活（总是 200）
  GET /ready     Readiness Probe：依赖是否全部就绪（全部正常 200，否则 503）

/ready 检查项目：
  - Postgres：SQLAlchemy 异步引擎 SELECT 1（复用连接池）
  - Redis：PING
  - 对象存储：bucket/object exists
  - 后台任务：OutboxPublisher / TaskWorker asyncio.Task 状态
"""
from __future__ import annotations

import asyncio
import time

import redis.asyncio as aioredis
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_config
from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.core.settings import settings
from app.storage.storage_factory import get_storage

router = APIRouter()
_logger = get_logger("api.health", layer="system")
_START_TIME = time.monotonic()


# ---------------------------------------------------------------------------
# Liveness Probe
# ---------------------------------------------------------------------------

@router.get("/health")
async def health_check() -> dict:
    """Liveness Probe：进程是否存活（总是返回 200）。

    不查询任何外部依赖，仅确认进程本身可用。
    """
    return {
        "status": "up",
        "service": "vidmuse-api",
        "version": settings.app_version,
        "uptime_seconds": round(time.monotonic() - _START_TIME, 1),
    }


# ---------------------------------------------------------------------------
# Readiness Probe
# ---------------------------------------------------------------------------

@router.get("/ready")
async def readiness_check() -> JSONResponse:
    """Readiness Probe：全部依赖就绪时返回 200，有任何失败返回 503。

    检查项目：
      - postgres  ： SELECT 1 通过 SQLAlchemy 连接池
      - redis     ： PING
      - storage   ： 对象可达检查
      - tasks     ： OutboxPublisher / TaskWorker asyncio.Task 状态
    """
    checks: dict[str, str] = {}

    # 并发执行三个依赖检查
    pg_ok, redis_ok, storage_ok = await asyncio.gather(
        _check_postgres(),
        _check_redis(),
        _check_storage(),
        return_exceptions=True,
    )

    checks["postgres"] = "ok" if pg_ok is True else f"fail: {_fmt_err(pg_ok)}"
    checks["redis"]    = "ok" if redis_ok is True else f"fail: {_fmt_err(redis_ok)}"
    checks["storage"]  = "ok" if storage_ok is True else f"fail: {_fmt_err(storage_ok)}"

    # 后台 asyncio 任务状态
    checks["outbox_publisher"] = _check_task("outbox_publisher")
    checks["task_worker"]      = _check_task("task_worker")

    all_healthy = all(v == "ok" for v in checks.values())
    http_status = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    body = {
        "status": "ready" if all_healthy else "degraded",
        "checks": checks,
        "uptime_seconds": round(time.monotonic() - _START_TIME, 1),
    }

    if not all_healthy:
        _logger.warning(
            f"Readiness 检查未全部通过: {checks}",
            event_type="readiness_check_degraded",
        )

    return JSONResponse(status_code=http_status, content=body)


# ---------------------------------------------------------------------------
# 内部检查函数
# ---------------------------------------------------------------------------

async def _check_postgres() -> bool:
    """SELECT 1 通过 SQLAlchemy 异步引擎（复用已有连接池）。"""
    async with get_session_factory()() as session:
        await session.execute(text("SELECT 1"))
    return True


async def _check_redis() -> bool:
    """PING Redis（短连接，检查完即关闭）。"""
    cfg = get_config().redis
    url = (
        f"redis://:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.db}"
        if cfg.password
        else f"redis://{cfg.host}:{cfg.port}/{cfg.db}"
    )
    client = aioredis.from_url(url, socket_connect_timeout=3, decode_responses=True)
    try:
        await client.ping()
    finally:
        await client.aclose()
    return True


async def _check_storage() -> bool:
    """通过已有存储单例检查对象存储可达性。"""
    storage = get_storage()
    cfg = get_config().storage
    await storage.async_object_exists(".health_probe", bucket=cfg.bucket)
    return True


def _check_task(task_name: str) -> str:
    """[诊断用] 检查指定名称的 asyncio.Task 是否存在且未完成。"""
    for task in asyncio.all_tasks():
        if task.get_name() == task_name and not task.done():
            return "ok"
    return "not_running"


def _fmt_err(exc: object) -> str:
    """\u5c06异常或布尔展平为可读字符串。"""
    if isinstance(exc, BaseException):
        return type(exc).__name__ + ": " + str(exc)[:80]
    return str(exc)
