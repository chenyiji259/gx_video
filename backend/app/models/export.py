"""Export 版本 ORM 模型。

来源文档：doc 09 任务 11-08 / scripts/init_schema.sql §9
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, ULIDMixin


class ExportVersion(Base, ULIDMixin, CreatedAtMixin):
    """导出版本（export_versions）。"""

    __tablename__ = "export_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','processing','completed','failed')",
            name="ck_export_versions_status",
        ),
        Index("idx_export_versions_project_created", "project_id", "created_at"),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    timeline_version_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("timeline_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    asset_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    resolution: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )

    def __repr__(self) -> str:
        return (
            f"<ExportVersion id={self.id!r} resolution={self.resolution!r} "
            f"status={self.status!r}>"
        )
