"""事件表 ORM 模型。

来源文档：doc 03 §8（Outbox 模式）、doc 04 §8（事件系统设计）、doc 05 表结构
          scripts/init_schema.sql  §11（EVENTS 节）

两张表职责：
  EventLog    — 业务事件的追加写入日志（domain / workflow / ui 三类）
  OutboxEvent — Outbox 模式的待发布事件缓冲（保证事务内业务数据 + 事件原子一致）

设计约束：
  - 两张表均 append-only：只含 created_at（无 updated_at）
  - 均使用 Base + ULIDMixin + CreatedAtMixin
  - outbox_events 无 FK 约束（高吞吐，与业务表同事务写入靠 DB 事务保一致性）
  - outbox_events 的 idx_outbox_status_available 是 partial index（只扫 pending 行）
    Alembic 不原生支持 partial index 语法，在迁移文件中用 text() 写
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, ULIDMixin


# ---------------------------------------------------------------------------
# EventLog — 业务事件追加日志
# ---------------------------------------------------------------------------


class EventLog(Base, ULIDMixin, CreatedAtMixin):
    """业务事件日志表（event_logs）。

    记录系统内所有重要的领域事件、工作流事件和 UI 事件。
    append-only：不更新，不删除（级联删除除外）。
    doc 04 §8 / doc 03 §2.4
    """

    __tablename__ = "event_logs"
    __table_args__ = (
        Index(
            "idx_event_logs_project_created",
            "project_id",
            "created_at",
        ),
        Index(
            "idx_event_logs_aggregate",
            "aggregate_type",
            "aggregate_id",
            "created_at",
        ),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 事件所属聚合根类型（e.g. "project", "shot", "timeline", "clip"）
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # 聚合根 ID（对应 projects.id / shots.id 等）
    aggregate_id: Mapped[str] = mapped_column(String(26), nullable=False)

    # 事件类型（命名规范：过去式，如 audio_analysis_completed）
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # 事件携带的业务数据（结构化）
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # 因果链：引起此事件的命令/事件 ID（可为空）
    causation_id: Mapped[str | None] = mapped_column(String(26), nullable=True)

    # 关联追踪 ID（同一业务请求的所有事件共享）
    correlation_id: Mapped[str | None] = mapped_column(String(26), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<EventLog id={self.id!r} type={self.event_type!r} "
            f"aggregate={self.aggregate_type}/{self.aggregate_id!r}>"
        )


# ---------------------------------------------------------------------------
# OutboxEvent — Outbox 模式发布缓冲
# ---------------------------------------------------------------------------

_OUTBOX_STATUS = "('pending', 'published', 'failed')"


class OutboxEvent(Base, ULIDMixin, CreatedAtMixin):
    """Outbox 事件缓冲表（outbox_events）。

    Outbox Pattern 核心：业务写入与事件写入在同一 DB 事务，
    由后台 OutboxPublisher 轮询并发布到 Redis pub-sub。

    此表无外键约束（避免 FK 锁影响发布器高频扫描）。
    doc 03 §10（Outbox 模式）
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            f"status IN {_OUTBOX_STATUS}",
            name="ck_outbox_events_status",
        ),
        # partial index：只扫 pending 行，发布器高频访问此索引
        # 注意：Alembic create_index 不支持 WHERE 子句，迁移文件中用 op.execute 建
    )

    # 聚合根类型（与 event_logs.aggregate_type 对齐）
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # 聚合根 ID
    aggregate_id: Mapped[str] = mapped_column(String(26), nullable=False)

    # 事件类型（与 event_logs.event_type 对齐）
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # 事件 payload（发布时原样投递）
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # 发布状态
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )

    # 可发布时间（支持延迟发布，默认 now()）
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
    )

    # 实际发布时间（成功后填入）
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<OutboxEvent id={self.id!r} type={self.event_type!r} "
            f"status={self.status!r}>"
        )
