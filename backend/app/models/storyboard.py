"""Storyboard ORM 模型。

来源文档：doc 05 §11.2 / scripts/init_schema.sql §6
doc 09 任务 10-03

两张表：
  StoryboardVersion  — storyboard_versions（版本表，append-only）
  StoryboardFrame    — storyboard_frames（帧表，每帧对应一个 shot 的参考图）

设计约束：
  - 两者均 append-only：继承 ULIDMixin + CreatedAtMixin + Base（无 updated_at）
  - StoryboardFrame.prompt_bundle_id → prompt_bundles.id（可选 FK，SET NULL 级联）
  - StoryboardFrame.asset_id → assets.id（必填，RESTRICT 级联）
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, ULIDMixin


# ---------------------------------------------------------------------------
# StoryboardVersion — storyboard_versions
# ---------------------------------------------------------------------------

class StoryboardVersion(ULIDMixin, CreatedAtMixin, Base):
    """Storyboard 版本表（storyboard_versions）。

    每次生成 storyboard 创建一条新版本记录，
    projects.active_storyboard_version_id 指向当前激活版本。
    doc 05 §11.2 / doc 09 任务 10-03
    """

    __tablename__ = "storyboard_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "version_no", name="uq_storyboard_versions_no"
        ),
        CheckConstraint("version_no >= 1", name="ck_storyboard_versions_no"),
        Index(
            "idx_storyboard_versions_project_active",
            "project_id",
            "is_active",
        ),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # 对应的 shot_plan 版本（RESTRICT：有 storyboard 时不允许删 shot_plan）
    shot_plan_version_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("shot_plan_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # 元数据快照（保存生成时各帧的摘要信息，供前端快速展示）
    raw_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return (
            f"<StoryboardVersion id={self.id!r} "
            f"project={self.project_id!r} v={self.version_no} active={self.is_active}>"
        )


# ---------------------------------------------------------------------------
# StoryboardFrame — storyboard_frames
# ---------------------------------------------------------------------------

class StoryboardFrame(ULIDMixin, CreatedAtMixin, Base):
    """Storyboard 帧表（storyboard_frames）。

    每条记录可表示两种角色（doc 21 §5.4）：
      1. 九宫格大图：cell_position = NULL，grid_index = N，shot_id = NULL
      2. 切分小图：cell_position ∈ [1,9]，grid_index = N，shot_id = 关联 shot
                  parent_asset_id 指向同 grid 的大图

    旧数据兼容：cell_position = grid_index = parent_asset_id = NULL 时
    视为单帧 storyboard（非九宫格架构产物，已不再生成新数据）。

    外键级联：
      shot_id          → shots.id（CASCADE，nullable，九宫格大图无 shot）
      asset_id         → assets.id（RESTRICT，帧图片不可随意删除）
      prompt_bundle_id → prompt_bundles.id（SET NULL）
      parent_asset_id  → assets.id（RESTRICT，引用九宫格大图）

    doc 05 §11.2 / doc 09 任务 10-03 / doc 21 §5.4
    """

    __tablename__ = "storyboard_frames"
    __table_args__ = (
        Index(
            "idx_storyboard_frames_storyboard_shot",
            "storyboard_version_id",
            "shot_id",
            "frame_index",
        ),
        # doc 21 §5.4：九宫格切分位置约束
        CheckConstraint(
            "cell_position IS NULL OR (cell_position >= 1 AND cell_position <= 9)",
            name="ck_storyboard_frames_cell_position",
        ),
        # doc 21 §5.4：按 grid_index + cell_position 高频查询
        Index(
            "idx_storyboard_frames_grid",
            "storyboard_version_id",
            "grid_index",
            "cell_position",
        ),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    storyboard_version_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("storyboard_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # doc 21 §5.4：shot_id 改为 nullable —— 九宫格大图自身不绑定 shot
    shot_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("shots.id", ondelete="CASCADE"),
        nullable=True,
    )
    # 生成的 storyboard frame 图片资产
    asset_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # 对应的 prompt bundle（可选，SET NULL 级联）
    prompt_bundle_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("prompt_bundles.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 帧顺序（同一 shot 可有多帧，一般为 0）
    frame_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    # 帧元数据（generation_time_ms / provider_meta 等）
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="'{}'"
    )

    # ------------------------------------------------------------------ #
    # doc 21 §5.4 九宫格架构新增字段
    # ------------------------------------------------------------------ #

    # 引用同 grid 的九宫格大图（仅切分小图填写；大图自身为 NULL）
    parent_asset_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # 在 9 格中的位置（1-9）；大图自身为 NULL
    cell_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 第几张九宫格（从 1 开始）；旧数据为 NULL
    grid_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<StoryboardFrame id={self.id!r} "
            f"storyboard={self.storyboard_version_id!r} "
            f"shot={self.shot_id!r} grid={self.grid_index} "
            f"cell={self.cell_position} frame={self.frame_index}>"
        )
