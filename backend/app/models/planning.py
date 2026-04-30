"""规划相关 ORM 模型（5张规划表）。

来源文档：doc 05 §11 / scripts/init_schema.sql §5 (ANALYSIS & PLANNING) §6 (SHOTS)
doc 09 任务 8-06

五张规划表：
  CreativeBriefVersion — 创意简报版本（creative_brief_versions）
  StyleBibleVersion    — 风格圣经版本（style_bible_versions）
  ScenePlanVersion     — 场景规划版本（scene_plan_versions）
  ShotPlanVersion      — 镜头方案版本（shot_plan_versions）
  Shot                 — 具体镜头行（shots）

设计约束：
  - 版本表 append-only（无 updated_at），继承 Base + ULIDMixin + CreatedAtMixin
  - Shot 有状态变更，继承 BaseModel（含 updated_at）
  - is_active 标识当前激活版本
  - 状态字段使用 varchar + CheckConstraint（不使用 Postgres enum）
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

from app.models.base import Base, BaseModel, CreatedAtMixin, ULIDMixin


# ---------------------------------------------------------------------------
# CreativeBriefVersion — 创意简报版本
# ---------------------------------------------------------------------------

class CreativeBriefVersion(ULIDMixin, CreatedAtMixin, Base):
    """创意简报版本表（creative_brief_versions）。

    append-only：每次修改 brief 生成新版本，不修改旧版本。
    projects.active_brief_version_id 指向当前激活版本。
    doc 03 §7.5 / doc 09 任务 9-02
    """

    __tablename__ = "creative_brief_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_no", name="uq_creative_brief_versions_no"),
        CheckConstraint("version_no >= 1", name="ck_creative_brief_versions_no"),
        Index("idx_creative_brief_versions_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)

    # brief 主体内容
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="''")
    narrative_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="'mixed'"
    )
    # performance_ratio: 表演镜头占比，0.0~1.0
    performance_ratio: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="0.5"
    )
    mood_tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    style_direction: Mapped[str] = mapped_column(Text, nullable=False, server_default="''")
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'{}'")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return (
            f"<CreativeBriefVersion id={self.id!r} "
            f"project={self.project_id!r} v={self.version_no} active={self.is_active}>"
        )


# ---------------------------------------------------------------------------
# StyleBibleVersion — 风格圣经版本
# ---------------------------------------------------------------------------

class StyleBibleVersion(ULIDMixin, CreatedAtMixin, Base):
    """风格圣经版本表（style_bible_versions）。

    append-only：每次修改风格方向生成新版本。
    projects.active_style_version_id 指向当前激活版本。
    doc 03 §7.6 / doc 09 任务 9-02
    """

    __tablename__ = "style_bible_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_no", name="uq_style_bible_versions_no"),
        CheckConstraint("version_no >= 1", name="ck_style_bible_versions_no"),
        Index("idx_style_bible_versions_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)

    # 风格圣经核心字段
    palette: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'{}'")
    lighting_style: Mapped[str] = mapped_column(Text, nullable=False, server_default="''")
    camera_style: Mapped[str] = mapped_column(Text, nullable=False, server_default="''")
    film_texture: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'{}'")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return (
            f"<StyleBibleVersion id={self.id!r} "
            f"project={self.project_id!r} v={self.version_no} active={self.is_active}>"
        )


# ---------------------------------------------------------------------------
# ScenePlanVersion — 场景规划版本
# ---------------------------------------------------------------------------

class ScenePlanVersion(ULIDMixin, CreatedAtMixin, Base):
    """场景规划版本表（scene_plan_versions）。

    append-only。存储结构化场景分组（多个 shot 属于同一 scene）。
    projects.active_scene_plan_version_id 指向当前激活版本。
    doc 09 任务 9-03
    """

    __tablename__ = "scene_plan_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_no", name="uq_scene_plan_versions_no"),
        CheckConstraint("version_no >= 1", name="ck_scene_plan_versions_no"),
        Index("idx_scene_plan_versions_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # raw_payload 存储完整的场景结构（scenes 数组，每个场景含 shot_ids / scene_description 等）
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'{}'")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return (
            f"<ScenePlanVersion id={self.id!r} "
            f"project={self.project_id!r} v={self.version_no} active={self.is_active}>"
        )


# ---------------------------------------------------------------------------
# ShotPlanVersion — 镜头方案版本
# ---------------------------------------------------------------------------

class ShotPlanVersion(ULIDMixin, CreatedAtMixin, Base):
    """镜头方案版本表（shot_plan_versions）。

    append-only。Shot 行通过 FK 关联此版本。
    projects.active_shot_plan_version_id 指向当前激活版本。
    doc 09 任务 9-03
    """

    __tablename__ = "shot_plan_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_no", name="uq_shot_plan_versions_no"),
        CheckConstraint("version_no >= 1", name="ck_shot_plan_versions_no"),
        Index("idx_shot_plan_versions_project_active", "project_id", "is_active"),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # raw_payload 存储完整的镜头方案 JSON（供审阅用，实际镜头行在 shots 表）
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'{}'")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return (
            f"<ShotPlanVersion id={self.id!r} "
            f"project={self.project_id!r} v={self.version_no} active={self.is_active}>"
        )


# ---------------------------------------------------------------------------
# Shot — 具体镜头行
# ---------------------------------------------------------------------------

_SHOT_STATUS = (
    "('planned', 'storyboard_ready', 'clip_pending', 'clip_ready', 'approved', 'stale', 'failed')"
)


class Shot(BaseModel):
    """镜头表（shots）。

    每行对应一个 MV 镜头，由 ShotPlanPersistenceService 在 shot_plan 生成后批量写入。
    状态随流程推进：planned → storyboard_ready → clip_pending → clip_ready → approved
    支持 stale 标记局部返工，支持 failed 表示生成失败。

    doc 05 §11.1 / doc 09 任务 9-03 / scripts/init_schema.sql §6
    """

    __tablename__ = "shots"
    __table_args__ = (
        CheckConstraint(
            f"status IN {_SHOT_STATUS}",
            name="ck_shots_status",
        ),
        Index("idx_shots_project_index", "project_id", "shot_index"),
        Index("idx_shots_plan", "shot_plan_version_id", "shot_index"),
        Index("idx_shots_status", "project_id", "status"),
    )

    # ------------------------------------------------------------------ #
    # 关联
    # ------------------------------------------------------------------ #
    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    shot_plan_version_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("shot_plan_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ------------------------------------------------------------------ #
    # 位置标识
    # ------------------------------------------------------------------ #
    # scene_id：归属场景标识（可选，来自 ScenePlan 的 scene_id）
    scene_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # shot_index：全局顺序编号，从 0 开始
    shot_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # ------------------------------------------------------------------ #
    # 时间坐标（毫秒，与 audio beat_map 对齐）
    # ------------------------------------------------------------------ #
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # ------------------------------------------------------------------ #
    # 语义属性
    # ------------------------------------------------------------------ #
    # section_type：所属音乐段落类型（verse / chorus / bridge / intro / outro / ...）
    section_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="'verse'"
    )
    # lyric_text：对应时间区间的歌词文本（可选）
    lyric_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # dialogue：该镜头的视频台词 / 配音稿（AI 讲解、旁白等）
    dialogue: Mapped[str | None] = mapped_column(Text, nullable=True)
    # emotion：镜头情绪标签（如 "energetic" / "melancholy"）
    emotion: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # emotion_intensity：情绪强度（low / medium / high / very_high），来自音频分析的 emotion_arc.segments[].intensity
    emotion_intensity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # shot_type：镜头景别（close / medium / wide / extreme_close / extreme_wide）
    shot_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="'medium'"
    )
    # subject：镜头视觉主体描述（如 "主唱站在雨中"）
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    # location：场景位置描述（如 "废弃工厂，夜晚，霓虹灯"）
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    # camera_language：运镜描述（如 "slow push-in" / "handheld tracking"）
    camera_language: Mapped[str | None] = mapped_column(Text, nullable=True)
    # visual_energy：视觉能量等级（low / medium / high）
    visual_energy: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ------------------------------------------------------------------ #
    # lipsync & 绑定
    # ------------------------------------------------------------------ #
    # lipsync_required：该镜头是否需要口型同步
    lipsync_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # character_binding：镜头绑定的角色/参考图结构（历史数据可为 list，新结构为 dict）
    character_binding: Mapped[dict | list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )
    # style_binding：绑定的局部风格覆盖（如特写镜头使用不同光线方案）
    style_binding: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )

    # ------------------------------------------------------------------ #
    # 状态
    # ------------------------------------------------------------------ #
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="'planned'"
    )

    def __repr__(self) -> str:
        return (
            f"<Shot id={self.id!r} project={self.project_id!r} "
            f"idx={self.shot_index} [{self.start_ms}~{self.end_ms}ms] "
            f"status={self.status!r}>"
        )
