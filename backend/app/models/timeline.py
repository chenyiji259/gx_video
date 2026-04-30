"""Timeline ORM 模型。

来源文档：doc 09 任务 11-06 / scripts/init_schema.sql §9
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, ForeignKey, Index, Integer,
    String, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, ULIDMixin


class TimelineVersion(Base, ULIDMixin, CreatedAtMixin):
    """时间线版本（timeline_versions）。"""

    __tablename__ = "timeline_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_no", name="uq_timeline_versions_no"),
        CheckConstraint(
            "render_status IN ('draft','ready','stale','rendering','failed')",
            name="ck_timeline_versions_render_status",
        ),
        Index("idx_timeline_versions_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_asset_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=True,
    )
    subtitle_track: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    render_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="draft"
    )
    raw_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    def __repr__(self) -> str:
        return (
            f"<TimelineVersion id={self.id!r} v{self.version_no} "
            f"status={self.render_status!r} active={self.is_active}>"
        )


class TimelineSegment(Base, ULIDMixin, CreatedAtMixin):
    """时间线片段（timeline_segments）。"""

    __tablename__ = "timeline_segments"
    __table_args__ = (
        Index(
            "idx_timeline_segments_timeline_start",
            "timeline_version_id", "start_ms",
        ),
    )

    timeline_version_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("timeline_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    shot_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("shots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    clip_version_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("clip_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    transition_in: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    transition_out: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )

    def __repr__(self) -> str:
        return (
            f"<TimelineSegment id={self.id!r} "
            f"shot={self.shot_id!r} [{self.start_ms}-{self.end_ms}ms]>"
        )
