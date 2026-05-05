"""EventLog / OutboxEvent Repository。

来源文档：doc 03 §10（Outbox 模式）、doc 04 §8（事件系统）

设计原则（doc 08 §4）：
  - Repository 只做数据存取，不含业务判断
  - EventLogService 负责调用这两个 Repository，并保证在同一事务内执行

OutboxRepository 额外提供：
  - get_pending_batch()：供 OutboxPublisher 批量拉取待发布事件
  - mark_published() / mark_failed()：发布后状态回写
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.events import EventLog, OutboxEvent
from app.repositories.base import BaseRepository


class EventLogRepository(BaseRepository[EventLog]):
    """事件日志 Repository。

    只支持写入（append-only），不提供 update/delete。
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EventLog)

    async def add_event(self, event: EventLog) -> EventLog:
        """写入一条事件日志（等待外层事务 commit）。"""
        self._session.add(event)
        return event

    async def list_project_events_by_type(
        self,
        project_id: str,
        event_type: str,
        *,
        limit: int = 200,
    ) -> Sequence[EventLog]:
        """按项目和事件类型读取最近事件，供前端状态恢复使用。"""
        stmt = (
            select(EventLog)
            .where(
                EventLog.project_id == project_id,
                EventLog.event_type == event_type,
            )
            .order_by(EventLog.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()


class OutboxRepository(BaseRepository[OutboxEvent]):
    """Outbox 事件 Repository。

    写入侧（在业务事务内调用）：
      add_event() — 与业务数据在同一事务写入

    读/更新侧（由 OutboxPublisher 后台任务调用）：
      get_pending_batch() — 批量拉取待发布事件
      mark_published()    — 标记为 published
      mark_failed()       — 标记为 failed
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, OutboxEvent)

    # ------------------------------------------------------------------ #
    # 写入侧（在业务事务内调用）
    # ------------------------------------------------------------------ #

    async def add_event(self, event: OutboxEvent) -> OutboxEvent:
        """写入 Outbox 事件（等待外层事务 commit）。"""
        self._session.add(event)
        return event

    # ------------------------------------------------------------------ #
    # 读取 / 更新侧（由 OutboxPublisher 调用，独立事务）
    # ------------------------------------------------------------------ #

    async def get_pending_batch(
        self,
        *,
        batch_size: int = 50,
    ) -> Sequence[OutboxEvent]:
        """批量拉取状态为 pending 且 available_at <= now() 的事件。

        Args:
            batch_size: 单次拉取上限，默认 50 条。

        Returns:
            按 available_at 升序排列的待发布事件列表。
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == "pending",
                OutboxEvent.available_at <= now,
            )
            .order_by(OutboxEvent.available_at)
            .limit(batch_size)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def mark_published(self, event_id: str) -> None:
        """将指定 Outbox 事件标记为 published，记录发布时间。"""
        stmt = (
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(
                status="published",
                published_at=datetime.now(timezone.utc),
            )
        )
        await self._session.execute(stmt)

    async def mark_failed(self, event_id: str) -> None:
        """将指定 Outbox 事件标记为 failed（供重试或告警使用）。"""
        stmt = (
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(status="failed")
        )
        await self._session.execute(stmt)
