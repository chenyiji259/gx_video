"""Clip 版本 ORM 模型。

来源文档：doc 09 任务 11-04 / scripts/init_schema.sql §8
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Numeric

from app.models.base import Base, CreatedAtMixin, ULIDMixin


class ClipVersion(Base, ULIDMixin, CreatedAtMixin):
    """视频片段版本（clip_versions）。

    每个 Shot 可有多个 ClipVersion（允许重生成），但同时只有一个 is_active=True。
    Append-only，不更新字段（is_active 和 status 除外）。
    """

    __tablename__ = "clip_versions"
    __table_args__ = (
        UniqueConstraint("shot_id", "version_no", name="uq_clip_versions_shot_no"),
        CheckConstraint(
            "generation_mode IN ('image_to_video','text_to_video','video_to_video','lipsync')",
            name="ck_clip_versions_mode",
        ),
        CheckConstraint(
            "status IN ('pending','ready','failed','stale')",
            name="ck_clip_versions_status",
        ),
        Index("idx_clip_versions_shot_active", "shot_id", "is_active"),
        Index("idx_clip_versions_project_created", "project_id", "created_at"),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    shot_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("shots.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_bundle_id: Mapped[Optional[str]] = mapped_column(
        String(26),
        ForeignKey("prompt_bundles.id", ondelete="SET NULL"),
        nullable=True,
    )
    quality_score: Mapped[Optional[float]] = mapped_column(
        Numeric(6, 3), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    def __repr__(self) -> str:
        return (
            f"<ClipVersion id={self.id!r} shot={self.shot_id!r} "
            f"v{self.version_no} status={self.status!r} active={self.is_active}>"
        )
