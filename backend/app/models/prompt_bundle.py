"""PromptBundle ORM 模型。

来源文档：doc 06 §10 / scripts/init_schema.sql §7
doc 09 任务 10-01

设计约束：
  - append-only：每次编译生成新记录，不修改旧记录（可追溯版本历史）
  - target_id 是多态引用（指向 storyboard_frame.id / shot.id / lipsync_clip.id）
    不建 FK，由应用层维护一致性
  - params 存储 provider 特定参数（aspect_ratio / duration_sec / seed 等）
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from app.models.base import Base, CreatedAtMixin, ULIDMixin


# target_type 约束（同 schemas/prompt.py PromptTargetType）
_TARGET_TYPE_VALUES = (
    "('storyboard_frame', 'shot_clip', 'lipsync_clip', "
    "'nine_grid_image', 'talking_head_story_overview_board')"
)


class PromptBundleModel(ULIDMixin, CreatedAtMixin, Base):
    """Prompt Bundle 表（prompt_bundles）。

    append-only：同一 target 可有多条记录（历史版本），通过 created_at DESC 取最新。
    doc 06 §10.2 / doc 09 任务 10-01
    """

    __tablename__ = "prompt_bundles"
    __table_args__ = (
        CheckConstraint(
            f"target_type IN {_TARGET_TYPE_VALUES}",
            name="ck_prompt_bundles_target_type",
        ),
        # 按 target 查最新 bundle 的索引
        Index("idx_prompt_bundles_target", "target_type", "target_id", "created_at"),
    )

    # ------------------------------------------------------------------ #
    # 关联
    # ------------------------------------------------------------------ #
    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ------------------------------------------------------------------ #
    # 目标标识
    # ------------------------------------------------------------------ #
    # 目标类型：storyboard_frame / shot_clip / lipsync_clip / nine_grid_image / talking_head_story_overview_board
    target_type: Mapped[str] = mapped_column(String(128), nullable=False)
    # 目标 ID（多态，无 FK）
    target_id: Mapped[str] = mapped_column(String(26), nullable=False)

    # ------------------------------------------------------------------ #
    # Provider
    # ------------------------------------------------------------------ #
    # 对应 config/providers/ 中的 name 字段
    provider: Mapped[str] = mapped_column(String(64), nullable=False)

    # ------------------------------------------------------------------ #
    # Prompt 内容
    # ------------------------------------------------------------------ #
    positive_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # provider 特定参数（duration_sec / aspect_ratio / seed 等）
    params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )

    # ------------------------------------------------------------------ #
    # 编译溯源（可选，供调试和审阅）
    # ------------------------------------------------------------------ #
    source_brief_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    source_style_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    source_shot_plan_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    # ------------------------------------------------------------------ #
    # Bug 2 修复：补入参考图溯源字段（与 PromptBundle schema 对齐）
    # 需 DB 迁移：
    #   ALTER TABLE prompt_bundles
    #     ADD COLUMN IF NOT EXISTS reference_image_url TEXT,
    #     ADD COLUMN IF NOT EXISTS reference_asset_ids JSONB DEFAULT '[]';
    # ------------------------------------------------------------------ #
    reference_image_url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    reference_asset_ids: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<PromptBundleModel id={self.id!r} "
            f"target={self.target_type}/{self.target_id!r} "
            f"provider={self.provider!r}>"
        )
