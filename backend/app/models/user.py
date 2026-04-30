"""用户与偏好 ORM 模型。

来源文档：doc 05 §6
  - users：基础账号密码表
  - user_preferences：轻量用户偏好（默认语言、比例、分辨率、常用风格标签）

设计约束：
  - 状态字段使用 varchar + CheckConstraint（不用 Postgres enum，迁移成本低）
  - favorite_style_tags 使用 JSONB，存轻量数组偏好
  - user_preferences 与 user 是 1:1 关系，user_id 唯一约束
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class User(BaseModel):
    """用户账号表（users）。

    doc 05 §6.1 字段规范。
    """
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
    )

    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="active"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    credits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="200")
    plan_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="free")

    # Relationships
    preferences: Mapped["UserPreferences | None"] = relationship(
        "UserPreferences",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id!r} username={self.username!r} status={self.status!r}>"


class UserPreferences(BaseModel):
    """用户偏好表（user_preferences）。

    doc 05 §6.2 字段规范。
    工程约束（doc 03 §2.3）：只存很薄的偏好，不存项目创作事实。
    """
    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_preferences_user_id"),
    )

    user_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 轻量偏好字段（全部可选）
    default_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    default_aspect_ratio: Mapped[str | None] = mapped_column(String(16), nullable=True)
    default_resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # 常用风格标签数组，例如 ["cinematic", "film_grain", "cold_tone"]
    favorite_style_tags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="preferences")

    def __repr__(self) -> str:
        return f"<UserPreferences user_id={self.user_id!r}>"
