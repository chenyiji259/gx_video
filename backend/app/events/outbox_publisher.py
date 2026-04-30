"""Outbox 事件发布器。

来源文档：doc 03 §10（Outbox 模式）

职责：
  以 asyncio 后台任务运行，定期轮询 outbox_events 表中的 pending 记录，
  将事件发布到 Redis pub-sub，成功后标记 published，失败标记 failed。

工作流：
  1. 从 outbox_events 批量拉取 status='pending' AND available_at <= now()
  2. 逐条尝试 Redis PUBLISH 到频道 vidmuse:events:{aggregate_type}
  3. 成功 → mark_published()；失败 → mark_failed()（不阻塞，后续可告警/重试）
  4. 每轮结束后等待 poll_interval_sec 再下一轮

设计约束：
  - 发布器不属于业务事务；每次轮询开启独立的 UoW
  - Redis 连接从 config 读取，不硬编码
  - 单发布器实例（不并发发布相同事件）
  - 第一版不实现 DLQ（死信队列），failed 状态依赖后续监控告警

启动方式（在 main.py lifespan 中）：
    publisher = OutboxPublisher()
    task = asyncio.create_task(publisher.run())
    # 关闭时 task.cancel()
"""
from __future__ import annotations

import asyncio
import json

import redis.asyncio as aioredis

from app.core.logging import get_logger
from app.core.redis_utils import build_redis_url
from app.repositories.event_log_repository import OutboxRepository
from app.repositories.unit_of_work import UnitOfWork

_logger = get_logger("events.outbox_publisher", layer="system")

# Redis 频道前缀：vidmuse:events:{aggregate_type}
_CHANNEL_PREFIX = "vidmuse:events:"


class OutboxPublisher:
    """Outbox 事件发布器（独立 asyncio 任务）。

    典型用法：
        publisher = OutboxPublisher()
        asyncio.create_task(publisher.run())
    """

    def __init__(
        self,
        *,
        poll_interval_sec: float = 1.0,
        batch_size: int = 50,
    ) -> None:
        """初始化发布器。

        Args:
            poll_interval_sec: 每轮轮询间隔（秒），默认 1 秒。
            batch_size:         单次批量拉取最大条数，默认 50 条。
        """
        self._poll_interval = poll_interval_sec
        self._batch_size = batch_size
        self._redis: aioredis.Redis | None = None
        self._running = False

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """建立 Redis 连接。在 run() 前由 lifespan 调用，或由 run() 内部调用。"""
        if self._redis is None:
            self._redis = aioredis.from_url(
                build_redis_url(),
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                health_check_interval=30,
                retry_on_timeout=True,
            )
            _logger.info("OutboxPublisher Redis 连接已建立", event_type="outbox_publisher_started")

    async def stop(self) -> None:
        """关闭 Redis 连接。在 lifespan shutdown 时调用。"""
        self._running = False
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
            _logger.info("OutboxPublisher 已关闭", event_type="outbox_publisher_stopped")

    # ------------------------------------------------------------------ #
    # 主循环
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        """主循环：持续轮询并发布，直到任务被取消。

        应通过 asyncio.create_task() 启动，取消时 CancelledError 自动退出。
        """
        await self.start()
        self._running = True
        _logger.info(
            f"OutboxPublisher 开始运行（interval={self._poll_interval}s, "
            f"batch={self._batch_size}）",
            event_type="outbox_publisher_loop_start",
        )
        try:
            while self._running:
                try:
                    await self._process_batch()
                except Exception as exc:  # noqa: BLE001
                    # 单轮处理失败不崩溃主循环，记录后继续
                    _logger.error(
                        f"OutboxPublisher 单轮处理异常: {exc!r}",
                        event_type="outbox_publisher_batch_error",
                    )
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            _logger.info("OutboxPublisher 任务已取消", event_type="outbox_publisher_cancelled")
            raise
        finally:
            await self.stop()

    # ------------------------------------------------------------------ #
    # 单轮处理
    # ------------------------------------------------------------------ #

    async def _process_batch(self) -> None:
        """单轮：拉取一批 pending 事件并尝试发布。"""
        async with UnitOfWork() as uow:
            repo = OutboxRepository(uow.session)
            events = await repo.get_pending_batch(batch_size=self._batch_size)

        if not events:
            return

        _logger.info(
            f"[OUTBOX] 拉取到 {len(events)} 条待发布事件",
            event_type="outbox_publisher_batch_fetched",
        )

        for event in events:
            _logger.info(
                f"[OUTBOX] 准备发布事件: event_id={event.id}, aggregate_type={event.aggregate_type}, "
                f"event_type={event.event_type}",
                event_type="outbox_publish_one_start",
            )
            await self._publish_one(event.id, event.aggregate_type, event.event_type, event.payload)

    async def _publish_one(
        self,
        event_id: str,
        aggregate_type: str,
        event_type: str,
        payload: dict,
    ) -> None:
        """尝试发布单条事件到 Redis pub-sub，并更新状态。

        每条事件独立开启 UoW，保证状态回写的事务隔离。
        """
        channel = f"{_CHANNEL_PREFIX}{aggregate_type}"
        message = json.dumps({"event_id": event_id, "event_type": event_type, **payload})

        _logger.info(f"[OUTBOX] Redis publish: channel={channel}, message={message[:200]}...", event_type="outbox_redis_publish_attempt")

        try:
            assert self._redis is not None, "Redis 未初始化"
            result = await self._redis.publish(channel, message)
            _logger.info(f"[OUTBOX] Redis publish 返回: result={result}", event_type="outbox_redis_publish_result")

            # 发布成功 → mark_published（独立事务）
            _logger.info(f"[OUTBOX] 准备标记 published: event_id={event_id}", event_type="outbox_mark_published_start")
            async with UnitOfWork() as uow:
                repo = OutboxRepository(uow.session)
                await repo.mark_published(event_id)
            _logger.info(f"[OUTBOX] 已标记 published: event_id={event_id}", event_type="outbox_mark_published_done")

            _logger.debug(
                f"Outbox 事件已发布: id={event_id!r} channel={channel!r}",
                event_type="outbox_event_published",
            )

        except Exception as exc:  # noqa: BLE001
            # 发布失败 → mark_failed，不抛出（主循环继续处理下一条）
            _logger.warning(
                f"[OUTBOX] 事件发布失败: id={event_id!r} error={exc!r}",
                event_type="outbox_event_failed",
            )
            try:
                async with UnitOfWork() as uow:
                    repo = OutboxRepository(uow.session)
                    await repo.mark_failed(event_id)
            except Exception as mark_exc:  # noqa: BLE001
                _logger.error(
                    f"mark_failed 写库失败: id={event_id!r} error={mark_exc!r}",
                    event_type="outbox_mark_failed_error",
                )
