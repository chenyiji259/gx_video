"""项目级共享 Schema。

来源文档：
  - doc 03 §5.2  ProjectSnapshot（项目记忆快照结构）
  - doc 04 §8    ProjectEvent（事件系统）
  - doc 05 §7    Projects 表字段

这些对象在 API、LangGraph Graph State、Agent 之间流转，
必须作为系统唯一可信的结构化定义。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# 项目 active version 指针集合（对应 projects 表的多个 active_xxx_version_id）
# ---------------------------------------------------------------------------

class ActiveVersions(BaseModel):
    """当前项目各阶段的 active version 指针。

    None 表示该阶段尚未产出可用版本。
    """
    project_spec: str | None = None
    audio_analysis: str | None = None
    creative_brief: str | None = None
    style_bible: str | None = None
    character_set: str | None = None
    narrative_script: str | None = None  # doc11 新增
    scene_plan: str | None = None
    shot_plan: str | None = None
    storyboard: str | None = None
    timeline: str | None = None
    latest_export: str | None = None


# ---------------------------------------------------------------------------
# 待决策引用（ProjectSnapshot 中的轻量引用，不含完整决策内容）
# ---------------------------------------------------------------------------

class PendingDecisionRef(BaseModel):
    decision_id: str
    decision_type: str
    target_entity_type: str
    target_entity_id: str | None = None


# ---------------------------------------------------------------------------
# 视觉圣经参考图引用（doc11 §10.1，批次2修复）
# ---------------------------------------------------------------------------

class CharacterRef(BaseModel):
    """角色参考图当前激活状态（写入 ProjectSnapshot，供 Director 感知视觉圣经进度）。"""
    character_id: str
    character_name: str
    active_asset_id: str | None = None    # 已生成的定妆图；None 表示尚未生成
    asset_url: str | None = None          # active 参考图的可访问 URL
    base_face_asset_id: str | None = None # 用户上传的原始参考图（待 Omni 分析）
    image_analysis_done: bool = False     # Omni 是否已分析过该图


class SceneRef(BaseModel):
    """场景参考图当前激活状态（写入 ProjectSnapshot，供 Director 感知视觉圣经进度）。"""
    scene_id: str
    scene_name: str
    active_asset_id: str | None = None
    asset_url: str | None = None


# ---------------------------------------------------------------------------
# ProjectSnapshot（doc 03 §5.2）
# ---------------------------------------------------------------------------

class ProjectSnapshot(BaseModel):
    """项目记忆快照。

    LangGraph 图执行前从项目级 memory 切出的标准化快照，
    确保任务执行的输入可追溯、可重放。

    对应 doc 03 §5.2 的结构。
    """
    project_id: str
    current_stage: str
    active_versions: ActiveVersions = Field(default_factory=ActiveVersions)

    # 当前会话选中的实体（用于理解"这个镜头""上一个人物"等指代）
    selected_entity_type: str | None = None
    selected_entity_id: str | None = None

    # 当前未处理的决策（高成本确认、风格选择等）
    pending_decisions: list[PendingDecisionRef] = Field(default_factory=list)

    # 快照元信息
    snapshot_taken_at: datetime | None = None

    # doc11 §10.1 批次2修复：视觉圣经角色/场景参考图激活状态
    character_refs: list[CharacterRef] = Field(default_factory=list)
    scene_refs: list[SceneRef] = Field(default_factory=list)

    model_config = ConfigDict(frozen=True)  # snapshot 不可变，防止误修改


# ---------------------------------------------------------------------------
# 创意方案扩展字段（doc 21 §1.1 九宫格架构）
# 这些字段塞在 CreativeBriefVersion.raw_payload 中，
# 本 schema 用于解析/构造 raw_payload，业务层通过它访问扩展字段。
# ---------------------------------------------------------------------------

class CharacterDef(BaseModel):
    """角色定义（doc 21 决策 C1：纯靠 prompt 描述保持视觉一致性）。"""
    character_id: str
    name: str
    appearance: str
    personality: str | None = None


class CreativeBriefExtension(BaseModel):
    """CreativeBriefVersion.raw_payload 中的九宫格扩展字段（doc 21 §1.1）。

    用法：
        ext = CreativeBriefExtension(**brief.raw_payload)
        ext.target_duration_sec
        ext.character_list

    字段含义见 doc 21 §3.3 算法说明。
    """
    target_duration_sec: int
    shot_duration_sec: int | None = None
    shot_count: int
    grid_count: int
    total_shots_generated: int
    allowed_shot_durations_sec: list[int] = Field(default_factory=list)
    character_list: list[CharacterDef] = Field(default_factory=list)
    target_platform: str | None = None
    target_audience: str | None = None
    visual_style: str | None = None
    human_on_camera: bool = False
    aspect_ratio: str = "9:16"
