"""视觉圣经与叙事剧本 ORM 模型。

来源文档：doc11 §3.1（新增阶段）/ §4.4（VisualBible 结构）/ §5.4（NarrativeScriptAgent）

两张版本表：
  CharacterSetVersion    — 视觉圣经版本（character_set_versions）
                           存储角色 + 场景参考图映射（doc11 §4.4）
  NarrativeScriptVersion — 叙事剧本版本（narrative_script_versions）
                           存储 story_arc / characters / scenes / section_mapping

设计约束：
  - 两张表均 append-only（无 updated_at），继承 Base + ULIDMixin + CreatedAtMixin
  - is_active 标识当前激活版本
  - raw_payload 存储完整 JSON，供 Agent / API 直接消费
  - characters / scenes / section_mapping 等核心业务字段提取为 JSONB，
    便于 SQL 查询而不必完全反序列化 raw_payload
"""
from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin, ULIDMixin


# ---------------------------------------------------------------------------
# CharacterSetVersion — 视觉圣经版本（已有 SQL 表，补充 ORM）
# ---------------------------------------------------------------------------

class CharacterSetVersion(ULIDMixin, CreatedAtMixin, Base):
    """视觉圣经版本表（character_set_versions）。

    append-only：每次固化视觉圣经生成新版本，不修改旧版本。
    projects.active_character_set_version_id 指向当前激活版本。

    raw_payload 结构（doc11 §4.4 VisualBible + Omni 多造型扩展）：
    {
      "characters": [
        {
          "character_id": "char_001",
          "character_name": "主角女生",
          "description": "...",
          "reference_asset_ids": ["asset_xxx"],
          "active_reference_asset_id": "asset_xxx",
          "appears_in_sections": ["verse", "chorus"],
          "base_face_asset_id": null,
          "image_analysis": null,
          "costumes": [
            {
              "costume_id": "costume_verse",
              "label": "日常穿搭",
              "applies_to_sections": ["intro", "verse"],
              "reference_asset_id": null,
              "generation_prompt": null,
              "user_confirmed": false
            }
          ]
        }
      ],
      "scenes": [
        {
          "scene_id": "scene_verse",
          "scene_name": "雨夜街头",
          "description": "...",
          "reference_asset_ids": ["asset_yyy"],
          "active_reference_asset_id": "asset_yyy"
        }
      ],
      "confirmed_at": "2026-03-31T10:00:00Z"
    }
    """

    __tablename__ = "character_set_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_no", name="uq_character_set_versions_no"),
        CheckConstraint("version_no >= 1", name="ck_character_set_versions_no"),
        Index("idx_character_set_versions_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)

    # 角色列表（JSONB，来自 NarrativeScript 的 characters）
    characters: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )
    # 场景列表（JSONB，来自 NarrativeScript 的 scenes）
    scenes: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )

    # 是否已由用户逐一确认（confirmed_at != None 表示已完全确认）
    confirmed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 完整原始载荷（供审阅和追溯）
    raw_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return (
            f"<CharacterSetVersion id={self.id!r} "
            f"project={self.project_id!r} v={self.version_no} "
            f"chars={len(self.characters or [])} "
            f"active={self.is_active}>"
        )


# ---------------------------------------------------------------------------
# NarrativeScriptVersion — 叙事剧本版本（新表）
# ---------------------------------------------------------------------------

class NarrativeScriptVersion(ULIDMixin, CreatedAtMixin, Base):
    """叙事剧本版本表（narrative_script_versions）。

    append-only：每次重新生成叙事剧本创建新版本。
    projects.active_narrative_script_version_id 指向当前激活版本。

    raw_payload 结构（doc11 §5.4 NarrativeScriptAgent 输出）：
    {
      "story_arc": "...",
      "characters": [{"id": "char_001", "name": "...", "description": "..."}],
      "scenes": [{"id": "scene_verse", "name": "...", "description": "..."}],
      "section_mapping": [
        {
          "section_type": "verse",
          "lyrics": "...",
          "scene_id": "scene_verse",
          "characters": ["char_001"],
          "emotion": "melancholy",
          "narrative_beat": "..."
        }
      ]
    }
    """

    __tablename__ = "narrative_script_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_no", name="uq_narrative_script_versions_no"),
        CheckConstraint("version_no >= 1", name="ck_narrative_script_versions_no"),
        Index(
            "idx_narrative_script_versions_project_active",
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

    # 故事弧线摘要
    story_arc: Mapped[str] = mapped_column(Text, nullable=False, server_default="''")

    # 角色列表（JSONB）
    characters: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )
    # 场景列表（JSONB）
    scenes: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )
    # 段落-场景-角色-情绪映射列表（JSONB，核心输出）
    section_mapping: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )

    # 完整原始载荷
    raw_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return (
            f"<NarrativeScriptVersion id={self.id!r} "
            f"project={self.project_id!r} v={self.version_no} "
            f"sections={len(self.section_mapping or [])} "
            f"active={self.is_active}>"
        )


# ---------------------------------------------------------------------------
# CharacterReference — 角色参考图独立行（character_references）
# ---------------------------------------------------------------------------

class CharacterReference(ULIDMixin, TimestampMixin, Base):
    """角色参考图独立行（character_references 表）。

    替代 CharacterSetVersion.characters JSONB 中的角色条目。
    每个角色一行，并发写入无锁竞争。
    """

    __tablename__ = "character_references"
    __table_args__ = (
        UniqueConstraint("version_id", "character_id", name="uq_character_references_version_char"),
        Index("idx_character_references_version", "version_id"),
        Index("idx_character_references_project", "project_id"),
    )

    version_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("character_set_versions.id", ondelete="CASCADE"), nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False,
    )
    character_id: Mapped[str] = mapped_column(String(64), nullable=False)
    character_name: Mapped[str] = mapped_column(String(255), nullable=False, server_default="''")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="''")
    appears_in_sections: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    active_reference_asset_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    reference_asset_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    base_face_asset_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    image_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    costumes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="'[]'")

    def __repr__(self) -> str:
        return (
            f"<CharacterReference id={self.id!r} "
            f"version={self.version_id!r} "
            f"char={self.character_id!r} "
            f"name={self.character_name!r}>"
        )


# ---------------------------------------------------------------------------
# SceneReference — 场景参考图独立行（scene_references）
# ---------------------------------------------------------------------------

class SceneReference(ULIDMixin, TimestampMixin, Base):
    """场景参考图独立行（scene_references 表）。

    替代 CharacterSetVersion.scenes JSONB 中的场景条目。
    每个场景一行，并发写入无锁竞争。
    """

    __tablename__ = "scene_references"
    __table_args__ = (
        UniqueConstraint("version_id", "scene_id", name="uq_scene_references_version_scene"),
        Index("idx_scene_references_version", "version_id"),
        Index("idx_scene_references_project", "project_id"),
    )

    version_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("character_set_versions.id", ondelete="CASCADE"), nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False,
    )
    scene_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scene_name: Mapped[str] = mapped_column(String(255), nullable=False, server_default="''")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="''")
    appears_in_sections: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    active_reference_asset_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    reference_asset_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="'[]'")

    def __repr__(self) -> str:
        return (
            f"<SceneReference id={self.id!r} "
            f"version={self.version_id!r} "
            f"scene={self.scene_id!r} "
            f"name={self.scene_name!r}>"
        )
