"""AudioAnalysisVersion ORM 模型。

来源文档：doc 03 §7.4（audio_analysis_versions 表）
Qwen3.5 Omni 全模态分析

设计约束：
  - append-only：不修改已有版本，只新建
  - is_active 标识当前激活版本
  - 扩展字段（key_scale / time_signature / style_caption / lrc_asset_id / analysis_provider）
    由 Qwen3.5 Omni 多模态分析写入
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, ULIDMixin


class AudioAnalysisVersion(ULIDMixin, CreatedAtMixin, Base):
    """音频分析版本表（audio_analysis_versions）。

    一个项目可以有多个分析版本（如重新切段后重分析），
    projects.active_audio_analysis_version_id 指向当前激活版本。
    """

    __tablename__ = "audio_analysis_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_no", name="uq_audio_analysis_versions_no"),
        CheckConstraint("version_no >= 1", name="ck_audio_analysis_versions_no"),
        Index("idx_audio_analysis_versions_project_active", "project_id", "is_active"),
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
    audio_asset_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # ------------------------------------------------------------------ #
    # librosa 信号分析结果
    # ------------------------------------------------------------------ #
    bpm: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    beat_map: Mapped[list] = mapped_column(JSONB, server_default="'[]'", nullable=False)
    section_map: Mapped[list] = mapped_column(JSONB, server_default="'[]'", nullable=False)  # Omni 真实段落结构（verse/chorus/bridge）
    energy_curve: Mapped[list] = mapped_column(JSONB, server_default="'[]'", nullable=False)  # 保留字段，不再由 librosa 写入
    lyrics_alignment: Mapped[list] = mapped_column(JSONB, server_default="'[]'", nullable=False)

    # ------------------------------------------------------------------ #
    # 原始载荷 + LLM 摘要
    # ------------------------------------------------------------------ #
    raw_payload: Mapped[dict] = mapped_column(JSONB, server_default="'{}'", nullable=False)
    # quality_summary 由 Qwen3.5 Omni 在分析阶段直接输出完整摘要
    quality_summary: Mapped[dict] = mapped_column(JSONB, server_default="'{}'", nullable=False)

    # ------------------------------------------------------------------ #
    # Qwen3.5 Omni 扩展字段
    # ------------------------------------------------------------------ #
    chord_progression: Mapped[list] = mapped_column(
        JSONB, server_default="'[]'", nullable=False
    )  # 和弦走向，如 [{"section": "verse", "chords": ["Dm", "Am"]}]
    instrumentation: Mapped[list] = mapped_column(
        JSONB, server_default="'[]'", nullable=False
    )  # 乐器列表，如 ["guitar", "drums", "bass"]
    five_second_analysis: Mapped[list] = mapped_column(
        JSONB, server_default="'[]'", nullable=False
    )  # 五秒粒度分析，如 [{"start": 0, "end": 5, "energy": 0.3, ...}]

    # ------------------------------------------------------------------ #
    # 扩展字段
    # ------------------------------------------------------------------ #
    key_scale: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )  # 调式，如 "D major"
    time_signature: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )  # 拍号，如 "4/4"
    style_caption: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Omni 自然语言风格描述
    genre: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Omni 结构化风格分类，如 "OST抒情" / "Hip-Hop"
    emotional_curve_graph: Mapped[list] = mapped_column(
        JSONB, server_default="'[]'", nullable=False
    )  # 整体情绪曲线关键点数组，如 [{"time":"00:25","intensity":"high"}]
    lrc_asset_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )  # LRC 歌词文件 asset_id
    analysis_provider: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # 各分析子项所用 provider，如 {"beat_map":"librosa","semantic":"qwen3.5_omni"}

    # ------------------------------------------------------------------ #
    # 激活状态
    # ------------------------------------------------------------------ #
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return (
            f"<AudioAnalysisVersion id={self.id!r} "
            f"project={self.project_id!r} v={self.version_no} "
            f"bpm={self.bpm} active={self.is_active}>"
        )
