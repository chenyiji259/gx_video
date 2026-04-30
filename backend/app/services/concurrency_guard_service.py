"""并发守卫服务。

来源文档：doc 02 §5（多 Agent 协同约束）、doc 04 §2（Agent 不能绕过状态机）

职责：
  用 Redis 分布式锁防止同一项目/镜头被并发修改或重复触发高成本操作。

典型场景：
  - 两个浏览器 tab 同时触发音频分析 → 第二个请求应等待或拒绝
  - LangGraph 多节点并发修改同一项目状态 → 用锁序列化
  - 用户快速连击"重生成镜头"按钮 → 第二次触发被拒绝

锁实现方式：
  Redis SET NX PX（SET if Not eXists，带毫秒级超时），原子操作，
  释放时校验 token 防止误删他人的锁。

用法：
    async with concurrency_guard.project_lock(project_id):
        # 保证此块内同一项目不会有第二个并发操作
        ...

    async with concurrency_guard.shot_lock(shot_id, timeout_sec=60):
        ...
"""
from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.core.logging import get_logger
from app.core.redis_utils import get_redis_client
from app.utils.ids import generate_ulid

# DESIGN-04 修复：原子释放锁的 Lua 脚本（GET + DEL 两步合一）。
# 仅当 key 的值等于持锁 token 时才删除，防止超时后误删他人的锁。
_RELEASE_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

_logger = get_logger("services.concurrency_guard", layer="system")

# 锁键前缀
_LOCK_PREFIX_PROJECT = "vidmuse:lock:project:"
_LOCK_PREFIX_SHOT = "vidmuse:lock:shot:"

# 默认锁超时（秒）
_DEFAULT_LOCK_TIMEOUT_SEC = 30


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class ConcurrencyError(Exception):
    """并发冲突异常：目标资源正在被其他操作占用。

    调用方可捕获此异常并向用户提示"操作正在进行中，请稍候"。
    """

    def __init__(
        self,
        message: str,
        *,
        resource_type: str,
        resource_id: str,
    ) -> None:
        super().__init__(message)
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.code = "concurrency_conflict"


# ---------------------------------------------------------------------------
# 并发守卫服务
# ---------------------------------------------------------------------------

class ConcurrencyGuardService:
    """并发守卫服务（Redis 分布式锁）。

    使用全局共享 Redis 连接池（get_redis_client()），
    不再独自建池。
    """

    def __init__(self) -> None:
        pass  # 无需自持 Redis 客户端

    async def close(self) -> None:
        """安全关闭（实际由 close_redis_client() 在 lifespan 平决）。"""
        pass

    # ------------------------------------------------------------------ #
    # 项目级锁
    # ------------------------------------------------------------------ #

    @asynccontextmanager
    async def project_lock(
        self,
        project_id: str,
        *,
        timeout_sec: int = _DEFAULT_LOCK_TIMEOUT_SEC,
    ) -> AsyncIterator[None]:
        """项目级分布式锁（async context manager）。

        Args:
            project_id:  项目 ID。
            timeout_sec: 锁超时秒数（到期自动释放，防死锁）。

        Yields:
            进入临界区（已加锁）。

        Raises:
            ConcurrencyError: 加锁失败（另一操作正在进行）。
        """
        lock_key = f"{_LOCK_PREFIX_PROJECT}{project_id}"
        async with self._lock(lock_key, timeout_sec, "project", project_id):
            yield

    # ------------------------------------------------------------------ #
    # Shot 级锁
    # ------------------------------------------------------------------ #

    @asynccontextmanager
    async def shot_lock(
        self,
        shot_id: str,
        *,
        timeout_sec: int = _DEFAULT_LOCK_TIMEOUT_SEC,
    ) -> AsyncIterator[None]:
        """Shot 级分布式锁（async context manager）。

        Args:
            shot_id:     镜头 ID。
            timeout_sec: 锁超时秒数。

        Yields:
            进入临界区（已加锁）。

        Raises:
            ConcurrencyError: 加锁失败（该镜头正在生成中）。
        """
        lock_key = f"{_LOCK_PREFIX_SHOT}{shot_id}"
        async with self._lock(lock_key, timeout_sec, "shot", shot_id):
            yield

    # ------------------------------------------------------------------ #
    # 内部锁实现
    # ------------------------------------------------------------------ #

    @asynccontextmanager
    async def _lock(
        self,
        lock_key: str,
        timeout_sec: int,
        resource_type: str,
        resource_id: str,
    ) -> AsyncIterator[None]:
        """通用 Redis SET NX EX 分布式锁实现。

        token 唯一标识此次加锁，确保只有持锁者才能释放锁（防止误删）。
        """
        redis_client = get_redis_client()
        token = generate_ulid()
        timeout_ms = timeout_sec * 1000

        # SET NX PX：仅在 key 不存在时设置（原子操作）
        acquired = await redis_client.set(
            lock_key,
            token,
            px=timeout_ms,
            nx=True,
        )

        if not acquired:
            current = await redis_client.get(lock_key)
            _logger.warning(
                f"加锁失败: key={lock_key!r} current_token={current!r}",
                event_type="concurrency_lock_failed",
            )
            raise ConcurrencyError(
                f"{resource_type} {resource_id!r} 当前有其他操作正在进行，请稍后重试",
                resource_type=resource_type,
                resource_id=resource_id,
            )

        _logger.debug(
            f"加锁成功: key={lock_key!r} token={token!r} ttl={timeout_sec}s",
            event_type="concurrency_lock_acquired",
        )

        try:
            yield
        finally:
            # DESIGN-04 修复：用 Lua 脚本原子执行“校验 token 后删除”，
            # 消除原来 GET + DELETE 两步操作间的竞态窗口。
            released = await redis_client.eval(_RELEASE_LOCK_LUA, 1, lock_key, token)
            if released:
                _logger.debug(
                    f"锁已原子释放: key={lock_key!r}",
                    event_type="concurrency_lock_released",
                )
            else:
                _logger.warning(
                    f"锁已超时或被他人持有，跳过释放: key={lock_key!r}",
                    event_type="concurrency_lock_expired",
                )


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

concurrency_guard = ConcurrencyGuardService()
