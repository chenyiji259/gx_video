"""领域状态枚举与合法迁移规则。

来源文档：
  doc 04 §4  项目状态机
  doc 04 §5  任务状态机
  doc 04 §6  镜头状态机
  doc 04 §20.4 失效规则

使用方式：
    from app.domain.states import ProjectStage, TaskStatus, ShotStatus
    from app.domain.states import ALLOWED_PROJECT_TRANSITIONS, StaleScope

设计原则：
  - 全部用 str-enum，序列化/反序列化与数据库 varchar 字段天然兼容
  - 迁移规则表（ALLOWED_*_TRANSITIONS）是 StateTransitionService 的唯一合法性来源
  - 任何新增状态必须同时更新 enum 和 ALLOWED 表，否则迁移检查会自动拒绝
"""
from __future__ import annotations

from enum import Enum


# ---------------------------------------------------------------------------
# 项目阶段枚举（对应 projects.current_stage）
# ---------------------------------------------------------------------------

class ProjectStage(str, Enum):
    """项目工作流阶段（doc 04 §4 + doc 11 §3 扩展）。

    每个阶段代表项目在主链路上所处的位置。
    使用 str 混入保证 stage.value == stage（字符串直接可用）。

    doc11 新增阶段（插入 brief_ready 与 shot_plan_ready 之间）：
      narrative_ready    — 叙事剧本已生成并被用户确认
      visual_bible_ready — 所有角色/场景参考图已逐一确认，视觉圣经固化
    """
    CREATED = "created"
    INPUT_READY = "input_ready"
    AUDIO_ANALYZED = "audio_analyzed"
    BRIEF_READY = "brief_ready"
    NARRATIVE_READY = "narrative_ready"        # doc11 新增
    VISUAL_BIBLE_READY = "visual_bible_ready"  # doc11 新增
    SHOT_PLAN_READY = "shot_plan_ready"
    STORYBOARD_READY = "storyboard_ready"
    CLIPS_READY = "clips_ready"
    TIMELINE_READY = "timeline_ready"
    EXPORT_READY = "export_ready"
    COMPLETED = "completed"
    FAILED = "failed"


# 项目阶段合法迁移表（key → 可到达的阶段集合）
# 规则来源：doc 04 §4.2 + doc 04 §20.4（上游变更时允许后退）
ALLOWED_PROJECT_TRANSITIONS: dict[ProjectStage, frozenset[ProjectStage]] = {
    ProjectStage.CREATED: frozenset({
        ProjectStage.INPUT_READY,
        ProjectStage.FAILED,
    }),
    ProjectStage.INPUT_READY: frozenset({
        ProjectStage.BRIEF_READY,      # 新流程：直接跳过音频分析
        ProjectStage.AUDIO_ANALYZED,   # 旧流程：音频 MV 模式
        ProjectStage.CREATED,          # 输入被清空时退回
        ProjectStage.FAILED,
    }),
    # 旧流程（音乐 MV 模式）：已在新流程中停用，保留供兼容
    ProjectStage.AUDIO_ANALYZED: frozenset({
        ProjectStage.BRIEF_READY,
        ProjectStage.INPUT_READY,      # 音频区间被修改时退回
        ProjectStage.FAILED,
    }),
    ProjectStage.BRIEF_READY: frozenset({
        ProjectStage.NARRATIVE_READY,  # doc11：brief 确认后生成叙事剧本
        ProjectStage.SHOT_PLAN_READY,  # 兼容旧链路（跳过 narrative 直接到 shot plan）
        ProjectStage.AUDIO_ANALYZED,   # brief 被重置时退回
        ProjectStage.FAILED,
    }),
    # ---- doc11 新增阶段 ----
    ProjectStage.NARRATIVE_READY: frozenset({
        ProjectStage.VISUAL_BIBLE_READY,  # 叙事确认后生成视觉圣经
        ProjectStage.SHOT_PLAN_READY,     # 跳过视觉圣经直接生成 shot plan（简化流程）
        ProjectStage.BRIEF_READY,         # 叙事剧本被重置时退回
        ProjectStage.FAILED,
    }),
    ProjectStage.VISUAL_BIBLE_READY: frozenset({
        ProjectStage.SHOT_PLAN_READY,     # 视觉圣经确认后生成 shot plan
        ProjectStage.NARRATIVE_READY,     # 角色/场景图被重置时退回
        ProjectStage.FAILED,
    }),
    # ---- 原有阶段（已更新依赖关系）----
    ProjectStage.SHOT_PLAN_READY: frozenset({
        ProjectStage.STORYBOARD_READY,
        ProjectStage.VISUAL_BIBLE_READY,  # shot plan 被重置时退回（有 visual bible 时）
        ProjectStage.BRIEF_READY,         # shot plan 被重置时退回（无 visual bible 时）
        ProjectStage.FAILED,
    }),
    ProjectStage.STORYBOARD_READY: frozenset({
        ProjectStage.CLIPS_READY,
        ProjectStage.SHOT_PLAN_READY,  # storyboard 被重置时退回
        ProjectStage.FAILED,
    }),
    ProjectStage.CLIPS_READY: frozenset({
        ProjectStage.TIMELINE_READY,
        ProjectStage.STORYBOARD_READY, # 全量 clip 被重置时退回
        ProjectStage.FAILED,
    }),
    ProjectStage.TIMELINE_READY: frozenset({
        ProjectStage.EXPORT_READY,
        ProjectStage.CLIPS_READY,      # timeline 被重置时退回
        ProjectStage.STORYBOARD_READY, # 切换旧 storyboard 版本时退回
        ProjectStage.FAILED,
    }),
    ProjectStage.EXPORT_READY: frozenset({
        ProjectStage.COMPLETED,
        ProjectStage.TIMELINE_READY,   # 导出前检查失败时退回
        ProjectStage.CLIPS_READY,      # 切换旧 clip 版本时退回
        ProjectStage.STORYBOARD_READY, # 切换旧 storyboard 版本时退回
        ProjectStage.FAILED,
    }),
    ProjectStage.COMPLETED: frozenset({
        # completed 不是终态，允许继续修改（回退到任意可编辑阶段）
        ProjectStage.TIMELINE_READY,
        ProjectStage.CLIPS_READY,
        ProjectStage.STORYBOARD_READY,
        ProjectStage.SHOT_PLAN_READY,
        ProjectStage.VISUAL_BIBLE_READY,
        ProjectStage.NARRATIVE_READY,
        ProjectStage.BRIEF_READY,
        ProjectStage.EXPORT_READY,
    }),
    ProjectStage.FAILED: frozenset({
        # 失败后允许手动重置到上次稳定版本
        ProjectStage.INPUT_READY,
        ProjectStage.AUDIO_ANALYZED,
        ProjectStage.BRIEF_READY,
        ProjectStage.NARRATIVE_READY,
        ProjectStage.VISUAL_BIBLE_READY,
        ProjectStage.SHOT_PLAN_READY,
        ProjectStage.STORYBOARD_READY,
        ProjectStage.CLIPS_READY,
        ProjectStage.TIMELINE_READY,
    }),
}


# ---------------------------------------------------------------------------
# 任务状态枚举（对应 agent_tasks.status / tool_jobs.status）
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    """Agent 任务 / Tool 任务状态（doc 04 §5）。"""
    PENDING = "pending"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"     # 仅 ToolJob 使用
    CANCELLED = "cancelled"


# AgentTask 合法迁移（无 retrying 状态）
ALLOWED_AGENT_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
    }),
    TaskStatus.RUNNING: frozenset({
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.WAITING_HUMAN,
        TaskStatus.CANCELLED,
    }),
    TaskStatus.WAITING_HUMAN: frozenset({
        TaskStatus.RUNNING,    # 用户响应后继续
        TaskStatus.CANCELLED,
    }),
    TaskStatus.SUCCEEDED: frozenset(),    # 终态
    TaskStatus.FAILED: frozenset(),       # 终态
    TaskStatus.CANCELLED: frozenset(),    # 终态
    TaskStatus.RETRYING: frozenset(),     # AgentTask 不用此状态
}


# ToolJob 合法迁移（含 retrying）
ALLOWED_TOOL_JOB_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,    # 任务提交后立即失败（无 handler / _set_running 前崩溃）
    }),
    TaskStatus.RUNNING: frozenset({
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.RETRYING,  # 失败重试：running → retrying，跳过中间 failed 节点
        TaskStatus.WAITING_HUMAN,
        TaskStatus.CANCELLED,
    }),
    TaskStatus.WAITING_HUMAN: frozenset({
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
    }),
    TaskStatus.FAILED: frozenset({
        TaskStatus.RETRYING,   # 可重试时进入 retrying
    }),
    TaskStatus.RETRYING: frozenset({
        TaskStatus.RUNNING,    # 重试开始时回到 running
        TaskStatus.CANCELLED,
    }),
    TaskStatus.SUCCEEDED: frozenset(),    # 终态
    TaskStatus.CANCELLED: frozenset(),    # 终态
}


# ---------------------------------------------------------------------------
# 镜头状态枚举（对应 shots.status，Shot ORM 在任务 9-01 中建立）
# ---------------------------------------------------------------------------

class ShotStatus(str, Enum):
    """镜头状态（doc 04 §6）。"""
    PLANNED = "planned"
    STORYBOARD_READY = "storyboard_ready"
    CLIP_PENDING = "clip_pending"
    CLIP_READY = "clip_ready"
    APPROVED = "approved"
    STALE = "stale"
    FAILED = "failed"


ALLOWED_SHOT_TRANSITIONS: dict[ShotStatus, frozenset[ShotStatus]] = {
    ShotStatus.PLANNED: frozenset({
        ShotStatus.STORYBOARD_READY,
        ShotStatus.STALE,
    }),
    ShotStatus.STORYBOARD_READY: frozenset({
        ShotStatus.CLIP_PENDING,
        ShotStatus.STALE,
    }),
    ShotStatus.CLIP_PENDING: frozenset({
        ShotStatus.CLIP_READY,
        ShotStatus.FAILED,
    }),
    ShotStatus.CLIP_READY: frozenset({
        ShotStatus.APPROVED,
        ShotStatus.STALE,
        ShotStatus.CLIP_PENDING,  # 用户主动重生成
    }),
    ShotStatus.APPROVED: frozenset({
        ShotStatus.STALE,
        ShotStatus.CLIP_PENDING,  # 重生成已批准的镜头
    }),
    ShotStatus.STALE: frozenset({
        ShotStatus.STORYBOARD_READY,   # stale 后重建 storyboard
        ShotStatus.CLIP_PENDING,       # stale 后直接重建 clip
    }),
    ShotStatus.FAILED: frozenset({
        ShotStatus.CLIP_PENDING,       # 失败后可重试
        ShotStatus.STALE,
    }),
}


# ---------------------------------------------------------------------------
# StaleScope — 上游变更影响范围
# ---------------------------------------------------------------------------

class StaleScope(str, Enum):
    """上游变更的影响范围（doc 04 §20.4 + doc11 §3.3 扩展失效规则）。

    用于 StateTransitionService.mark_stale() 确定需要失效的下游范围。
    """
    # 旧流程（音乐模式）：新流程不再使用音频变更失效
    # 音频区间变更：shot plan 之后全部失效，项目回退到 input_ready
    AUDIO_CHANGED = "audio_changed"

    # 全局风格变更：storyboard / clip / timeline 失效，项目回退到 shot_plan_ready
    STYLE_CHANGED = "style_changed"

    # 单个 shot 修改：只有该 shot 的 clip 和 timeline segment 失效
    SINGLE_SHOT_CHANGED = "single_shot_changed"

    # 全局 brief 变更：shot plan / storyboard / clip / timeline 全部失效
    BRIEF_CHANGED = "brief_changed"

    # doc11 新增：叙事剧本变更 → shot plan + storyboard + clip + timeline 全部失效
    NARRATIVE_CHANGED = "narrative_changed"

    # doc11 新增：视觉圣经变更（角色/场景参考图）→ 使用该角色/场景的 storyboard + clip 失效
    # 粒度更细，由 VisualBibleService 负责针对具体角色/场景传播
    VISUAL_BIBLE_CHANGED = "visual_bible_changed"

    # 批次C 新增：单个角色参考图重新生成 → 绑定该角色的 shot + active clip 失效
    # 项目回退到 visual_bible_ready（doc11 §3.3 失效规则）
    # 由 worker._handle_generate_character_ref 完成后调用，粒度为 character_id
    CHARACTER_REF_CHANGED = "character_ref_changed"
