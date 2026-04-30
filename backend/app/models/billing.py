"""计费账本 ORM 模型。

来源文档：doc 01 §13（消费机制）、doc 03 §7.8（导出与计费）、doc 05 表结构
          scripts/init_schema.sql  §11（credit_ledger 节）

职责：
  CreditLedger — 系统全量 credits 流水账本
  每次高成本操作（storyboard / clip / export）必须按 reserve → commit / refund 三段式记录

设计约束：
  - Append-only：无 updated_at，继承 Base + ULIDMixin + CreatedAtMixin
  - delta 可为负（refund 时为负值）
  - job_id 是逻辑引用（tool_jobs.id），不建外键（高吞吐场景）
  - project_id 建可为 NULL（充值、系统赠送等无项目场景）
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Numeric

from app.models.base import Base, CreatedAtMixin, ULIDMixin


_ENTRY_TYPE = "('grant', 'reserve', 'commit', 'refund')"
_LEDGER_STATUS = "('pending', 'applied', 'reverted')"


class CreditLedger(Base, ULIDMixin, CreatedAtMixin):
    """Credits 流水账本（credit_ledger）。

    三段式账本设计：
      1. reserve  — 操作前预占（delta < 0，status = pending）
      2. commit   — 操作成功确认（status → applied）
      3. refund   — 操作失败退款（delta > 0，status → applied）

    grant 用于充值和系统赠送（delta > 0）。

    doc 01 §13.5 / doc 03 §7.8
    """

    __tablename__ = "credit_ledger"
    __table_args__ = (
        CheckConstraint(
            f"entry_type IN {_ENTRY_TYPE}",
            name="ck_credit_ledger_entry_type",
        ),
        CheckConstraint(
            f"status IN {_LEDGER_STATUS}",
            name="ck_credit_ledger_status",
        ),
        Index(
            "idx_credit_ledger_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "idx_credit_ledger_project_created",
            "project_id",
            "created_at",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 项目 ID（充值/赠送等非项目操作可为 NULL）
    project_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 逻辑引用 tool_jobs.id（不建 FK，避免高吞吐场景锁竞争）
    job_id: Mapped[str | None] = mapped_column(String(26), nullable=True)

    # 账单类型
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # 关联工具名称（e.g. "image_generation", "video_generation"）
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 消耗单位数量（e.g. 视频秒数、图片张数）
    units: Mapped[float] = mapped_column(
        Numeric(12, 3), nullable=False, server_default="0"
    )

    # 单位价格（credits/unit）
    unit_price: Mapped[float] = mapped_column(
        Numeric(12, 3), nullable=False, server_default="0"
    )

    # 实际 credits 变化量（负值 = 扣减，正值 = 增加/退款）
    delta: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)

    # 账单状态
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )

    # 扩展元数据（provider 信息、成本明细等）
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )

    def __repr__(self) -> str:
        return (
            f"<CreditLedger id={self.id!r} type={self.entry_type!r} "
            f"delta={self.delta} status={self.status!r}>"
        )
