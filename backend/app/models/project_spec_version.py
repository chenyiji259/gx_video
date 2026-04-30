"""ProjectSpec 版本表 ORM 模型。

来源文档：doc 05 §9.1（project_spec_versions 表）

设计约束：
  - append-only：每次输入变更都插入新版本，不覆盖旧版本
  - 版本激活通过 is_active 标志 + projects.active_project_spec_version_id 双重维护
  - 同一项目只能有一个 is_active=true（由 ProjectSpecService 保证，非 DB 约束）
  - audio_asset_id → assets.id FK（可 SET NULL，允许资产被删除）

input_mode 取值（doc 05 §9.1）：
    audio_text        - 音频 + 文字描述（主入口）
    audio_image_text  - 音频 + 参考图 + 文字描述
"""
from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, ULIDMixin


class ProjectSpecVersion(ULIDMixin, CreatedAtMixin, Base):
    """项目输入规格版本表（project_spec_versions）。

    每次用户修改上传内容或配置，都创建一个新版本。
    系统通过 is_active 标志追踪当前激活版本，旧版本保留用于回滚。
    """

    __tablename__ = "project_spec_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_no", name="uq_project_spec_versions_no"),
        CheckConstraint(
            "input_mode IN ('audio_text', 'audio_image_text')",
            name="ck_project_spec_versions_mode",
        ),
        # 按项目快速查活跃版本
        Index("idx_project_spec_versions_project_active", "project_id", "is_active"),
    )

    # ------------------------------------------------------------------ #
    # 关联
    # ------------------------------------------------------------------ #
    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)

    # ------------------------------------------------------------------ #
    # 输入规格
    # ------------------------------------------------------------------ #
    input_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="audio_text"
    )

    # 音频资产关联（audio_text / audio_image_text 模式下必填）
    audio_asset_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("assets.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 音频时间区间（秒，3位小数）
    audio_start_sec: Mapped[float] = mapped_column(
        Numeric(10, 3), nullable=False, server_default="0"
    )
    audio_end_sec: Mapped[float] = mapped_column(
        Numeric(10, 3), nullable=False, server_default="0"
    )

    # 用户创意描述
    user_prompt: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )

    # 输出配置（画幅、分辨率、目标时长等）
    output_config: Mapped[dict] = mapped_column(
        JSONB, server_default="'{}'", nullable=False
    )

    # 用户上传的角色参考图 asset_id 列表（顺序即上传顺序，不附带角色绑定）
    # input_mode='audio_image_text' 时应有内容，最多 5 张
    reference_image_asset_ids: Mapped[list] = mapped_column(
        JSONB, server_default="'[]'", nullable=False
    )

    # 附加约束（保留给后续扩展）
    constraints: Mapped[dict] = mapped_column(
        JSONB, server_default="'{}'", nullable=False
    )

    # ------------------------------------------------------------------ #
    # 版本管理
    # ------------------------------------------------------------------ #
    # 谁触发了这次版本创建（'user' / 'system'）
    created_by: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="user"
    )

    # 触发本次版本变更的事件 ID（可追溯来源）
    source_event_id: Mapped[str | None] = mapped_column(String(26), nullable=True)

    # 当前是否为激活版本（同一项目只有一个 True）
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectSpecVersion id={self.id!r} "
            f"project={self.project_id!r} v={self.version_no} "
            f"active={self.is_active}>"
        )
