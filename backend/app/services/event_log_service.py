"""事件日志服务。

来源文档：doc 03 §10（Outbox 模式）、doc 04 §8（事件系统）

核心设计（Outbox Pattern）：
  业务写入 + event_log 写入 + outbox 写入 必须在同一 DB 事务，
  因此 EventLogService.emit() 不自行开启 UoW，而是接受调用方传入的 AsyncSession，
  在调用方事务内完成两次 INSERT。

与 AuthService 的区别：
  AuthService 是顶层入口，自持 UoW 是因为它的所有操作构成完整事务边界。
  EventLogService 是横切关注点（cross-cutting concern），
  必须嵌入到其他 Service 的事务中才能实现原子性。

调用示例（在 ProjectService 内）：
    async with UnitOfWork() as uow:
        # ... 业务写入 ...
        await event_log_service.emit(
            uow.session,
            ProjectEvent(
                project_id=project.id,
                aggregate_type="project",
                aggregate_id=project.id,
                event_type="project_input_ready",
                category="domain",
                payload={"stage": "input_ready"},
            )
        )
    # commit 时业务数据 + event_log + outbox 三者原子落库
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.events import EventLog, OutboxEvent
from app.repositories.event_log_repository import EventLogRepository, OutboxRepository
from app.schemas.event import ProjectEvent
from app.utils.ids import generate_ulid

_logger = get_logger("services.event_log", layer="system")


class EventLogService:
    """事件日志服务（无状态，每次调用传入 session）。

    不持有 UoW，设计为在调用方事务内工作。
    可直接实例化或作为单例使用（无状态，线程安全）。
    """

    async def emit(
        self,
        session: AsyncSession,
        event: ProjectEvent,
    ) -> tuple[EventLog, OutboxEvent]:
        """在给定 session 的事务内原子写入 event_log + outbox_event。

        Args:
            session:  调用方已开启的 AsyncSession（由 UoW 持有）。
            event:    业务事件描述对象（ProjectEvent Schema）。

        Returns:
            (EventLog ORM 实例, OutboxEvent ORM 实例)
            两者均已加入 session，等待外层事务 commit 落库。

        Raises:
            ValueError: event 缺少必要字段时。
        """
        _logger.info(
            f"[EVENT_LOG_EMIT] 进入: project_id={event.project_id}, event_type={event.event_type}, "
            f"aggregate_type={event.aggregate_type}, aggregate_id={event.aggregate_id}",
            event_type="event_log_emit_enter",
        )

        if not event.project_id:
            raise ValueError("emit() 要求 event.project_id 不为空")
        if not event.event_type:
            raise ValueError("emit() 要求 event.event_type 不为空")

        # ---- 写 event_logs ----
        _logger.info("[EVENT_LOG_EMIT] 步骤1: 写入 EventLog", event_type="event_log_write_start")
        event_log = EventLog(
            id=event.event_id or generate_ulid(),
            project_id=event.project_id,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            event_type=event.event_type,
            payload=event.payload,
            causation_id=event.causation_id,
            correlation_id=event.correlation_id,
        )
        event_log_repo = EventLogRepository(session)
        await event_log_repo.add_event(event_log)
        _logger.info(
            f"[EVENT_LOG_EMIT] EventLog 写入完成: id={event_log.id}",
            event_type="event_log_write_done",
        )

        # ---- 写 outbox_events（同一事务）----
        _logger.info("[EVENT_LOG_EMIT] 步骤2: 写入 OutboxEvent", event_type="outbox_event_write_start")
        outbox_event = OutboxEvent(
            id=generate_ulid(),
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            event_type=event.event_type,
            payload={
                **event.payload,
                # 附带追踪字段，方便消费方关联
                "_event_id": event_log.id,
                "_project_id": event.project_id,
                "_category": event.category,
            },
            status="pending",
            available_at=datetime.now(timezone.utc),
        )
        outbox_repo = OutboxRepository(session)
        await outbox_repo.add_event(outbox_event)
        _logger.info(
            f"[EVENT_LOG_EMIT] OutboxEvent 写入完成: id={outbox_event.id}, status={outbox_event.status}",
            event_type="outbox_event_write_done",
        )

        _logger.debug(
            f"Event queued: type={event.event_type!r} "
            f"aggregate={event.aggregate_type}/{event.aggregate_id!r}",
            event_type="event_queued",
        )

        _logger.info("[EVENT_LOG_EMIT] 完成，准备返回", event_type="event_log_emit_exit")
        return event_log, outbox_event


# ---------------------------------------------------------------------------
# 模块级单例（无状态，可安全共享）
# ---------------------------------------------------------------------------

event_log_service = EventLogService()
