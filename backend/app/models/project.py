"""项目主表 ORM 模型。

来源文档：doc 05 §7
  projects 是系统的主聚合根。
  它只保存当前 active version 指针，不存大 JSON 内容。
  真正的内容在各 xxx_versions 版本表里（本阶段暂未实现，后续任务补充）。

设计约束：
  - active_xxx_version_id 字段当前阶段不加 FK（版本表尚未建），迁移时统一加
  - current_stage 和 status 使用 varchar + CheckConstraint
  - 索引遵循 doc 05 §17 的高频查询建议
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


# 允许的项目状态（doc 05 §7.1 status 约束）
_STATUS_VALUES = "('active', 'archived', 'failed')"

# 允许的项目阶段（doc 04 §4 + doc11 §3 扩展阶段）
_STAGE_VALUES = (
    "('created', 'input_ready', 'audio_analyzed', 'brief_ready', "
    "'narrative_ready', 'visual_bible_ready', "
    "'shot_plan_ready', 'storyboard_ready', 'clips_ready', "
    "'timeline_ready', 'export_ready', 'completed', 'failed')"
)


class Project(BaseModel):
    """项目主表（projects）。

    doc 05 §7.1 字段规范。
    """
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(f"status IN {_STATUS_VALUES}", name="ck_projects_status"),
        CheckConstraint(f"current_stage IN {_STAGE_VALUES}", name="ck_projects_current_stage"),
        # 高频查询索引（doc 05 §17.1）
        Index("idx_projects_user_updated", "user_id", "updated_at"),
        Index("idx_projects_stage", "user_id", "current_stage"),
    )

    user_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # 项目运营状态（active / archived / failed）
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="active"
    )

    # 当前所处的工作流阶段（对应状态机，doc 04 §4）
    current_stage: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="created"
    )

    # ---------------------------------------------------------------------------
    # Active version 指针（doc 05 §7.1 / doc 03 §5.1）
    # 每类产物只保存当前激活版本的 ID，版本表自行管理历史
    # 注意：本阶段不加 FK 约束，版本表在后续任务中建立
    # ---------------------------------------------------------------------------
    active_project_spec_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    active_audio_analysis_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    active_brief_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    active_style_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    active_character_set_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    active_narrative_script_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    active_scene_plan_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    active_shot_plan_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    active_storyboard_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    active_timeline_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    latest_export_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    # Relationships
    conversation_sessions: Mapped[list["ConversationSession"]] = relationship(  # noqa: F821
        "ConversationSession",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Project id={self.id!r} name={self.name!r} "
            f"stage={self.current_stage!r} status={self.status!r}>"
        )
