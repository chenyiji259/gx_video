"""ORM 基类（SQLAlchemy 2.x 声明式风格）。

文档约束（doc 05 §3）：
  - 所有核心表主键统一使用 ULID varchar(26)
  - 核心表含 created_at / updated_at timestamptz
  - 状态字段使用 varchar + CheckConstraint，不用 Postgres enum（迁移成本低）
  - updated_at 通过 SQLAlchemy ORM onupdate 触发（非数据库触发器）

使用方式：
  大多数模型继承 BaseModel（自动获得 ULID PK + 时间戳）。
  session_contexts 等特殊表直接继承 Base，手动定义主键。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.utils.ids import generate_ulid


# ---------------------------------------------------------------------------
# 全局 ORM 元数据根（所有模型必须共享同一个 Base）
# Alembic 通过 Base.metadata 自动发现所有表
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """全局 ORM 基类，持有共享 metadata。所有模型必须继承此类。"""
    pass


# ---------------------------------------------------------------------------
# Mixin：独立组合，让特殊表可按需拼装
# ---------------------------------------------------------------------------

class ULIDMixin:
    """提供 ULID 主键的 Mixin（varchar(26)，自动在 Python 层生成）。

    使用 default= 而非 server_default=，确保 SQLAlchemy 在 INSERT 前
    就能拿到 id 值（方便关联对象、日志追踪）。
    """
    id: Mapped[str] = mapped_column(
        String(26),
        primary_key=True,
        default=generate_ulid,
    )


class TimestampMixin:
    """提供 created_at / updated_at 的 Mixin。

    - created_at：由数据库 server_default=now() 填充（落库时生成）。
    - updated_at：created 时也由 server_default 填充；
                  ORM UPDATE 时通过 onupdate=func.now() 由 SQLAlchemy 更新。
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CreatedAtMixin:
    """只含 created_at 的 Mixin，用于 append-only 表（如 conversation_messages）。"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class UpdatedAtMixin:
    """只含 updated_at 的 Mixin，用于无独立创建时间的 1:1 关联表（如 session_contexts）。"""
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# 标准业务模型基类
# ---------------------------------------------------------------------------

class BaseModel(Base, ULIDMixin, TimestampMixin):
    """标准业务模型基类：ULID PK + created_at + updated_at。

    绝大多数业务表继承此类。例外情况：
      - session_contexts：以外键作主键，继承 Base 直接定义
      - conversation_messages：append-only，无 updated_at，使用 Base + ULIDMixin + CreatedAtMixin
    """
    __abstract__ = True
