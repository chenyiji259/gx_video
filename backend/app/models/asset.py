"""资产表 ORM 模型。

来源文档：doc 05 §9（assets 表）

设计约束：
  - 资产一经落库不允许修改（不可变），故只有 created_at，无 updated_at
  - storage_uri 存储对象定位 URL（例如 OSS 基础地址）
  - sha256 的 partial index（WHERE sha256 IS NOT NULL）通过 migration 手动建
  - asset_type 使用 varchar + CheckConstraint，不用 Postgres ENUM

对象存储路径规范（doc 05 §9.3）：
    projects/{project_id}/assets/{asset_type}/{asset_id}/{filename}

资产类型（doc 05 §9.2）：
    audio_original   - 用户上传的原始音频
    audio_trimmed    - 按时间区间裁切后的音频
    image_reference  - 角色/场景参考图
    style_reference  - 风格参考图
    storyboard_frame - 分镜帧图片（AI生成）
    clip_video       - 视频片段（AI生成）
    export_video     - 导出成片
    subtitle_file    - 字幕文件
    thumbnail        - 封面/缩略图
"""
from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, ULIDMixin

# 允许的资产类型（doc 05 §9.2 + doc11 §4.2 扩展类型 + doc12 偏差6 文本产物协议）
_ASSET_TYPE_VALUES = (
    "('audio_original', 'audio_trimmed', "
    "'image_reference', 'style_reference', "
    "'storyboard_frame', 'clip_video', "
    "'export_video', 'subtitle_file', 'thumbnail', "
    "'character_reference', 'scene_reference', 'prop_reference', "
    "'audio_analysis', 'creative_brief', 'style_bible', "
    "'narrative_script', 'scene_plan', 'shot_plan', "
    "'visual_bible', 'storyboard', 'prompt_bundle', 'timeline', "
    "'nine_grid_image')"
    # character_reference: 角色定妆图（img2img 或 txt2img，doc11 §4.2）
    # scene_reference:     场景参考图（txt2img，doc11 §4.2）
    # prop_reference:      道具/细节参考图（可选，doc11 §4.2）
    # creative_brief / narrative_script / shot_plan 等：doc12 偏差6 统一 ArtifactRef 协议文本产物
    # nine_grid_image:     三宫格大图（兼容旧枚举名）
)


class Asset(ULIDMixin, CreatedAtMixin, Base):
    """资产表（assets）。

    append-only：资产落库后不可修改，无 updated_at。
    storage_uri 为对象存储定位地址，
    对外访问时由服务层按需转换为签名 URL。
    """

    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint(
            f"asset_type IN {_ASSET_TYPE_VALUES}",
            name="ck_assets_type",
        ),
        # 高频查询索引（doc 05 §17.1）
        Index("idx_assets_project_type_created", "project_id", "asset_type", "created_at"),
        # sha256 全量索引（partial WHERE 版本通过 migration op.execute 单独建）
        Index("idx_assets_sha256", "sha256"),
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
    # 资产分类与存储位置
    # ------------------------------------------------------------------ #
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    bucket_name: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)

    # 对象定位 URL（例如 OSS 基础地址 + object_key）
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)

    # ------------------------------------------------------------------ #
    # 媒体元信息
    # ------------------------------------------------------------------ #
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 扩展元数据（文件名、来源等）
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        server_default="'{}'",
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<Asset id={self.id!r} type={self.asset_type!r} "
            f"key={self.object_key!r}>"
        )
