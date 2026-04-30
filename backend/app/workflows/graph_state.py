"""LangGraph 主图状态定义。

来源文档：doc 02 §11.4（Graph State 建议）/ doc 09 任务 9-01（阶段感知扩展）

ProjectGraphState 是主图的全局状态 TypedDict。
每次 POST /v1/chat/completions 调用时，由 openai_compat.py 初始化，
经过节点链路 load_project_snapshot → [stage_route] → director_intake → respond_to_user 后返回。

字段分类：
  输入字段       — 每轮调用由 openai_compat.py 填充
  快照扩展字段   — 由 load_project_snapshot 节点填充（9-01 新增）
  中间字段       — 由图节点逐步填充
  输出字段       — 最终被 openai_compat.py 读取
"""
from __future__ import annotations

from typing import Optional, TypedDict


class ProjectGraphState(TypedDict, total=False):
    """LangGraph 主图的全局状态。

    total=False 允许部分字段可缺省（节点只需返回它修改的字段）。
    各字段的生命周期见下方注释。
    """

    # ------------------------------------------------------------------ #
    # 输入字段（每轮调用由 openai_compat.py 填充）
    # ------------------------------------------------------------------ #

    user_id: str
    """当前登录用户 ID，用于 load_project_snapshot 验证项目归属。"""

    project_id: str
    """目标项目 ID。"""

    session_id: str
    """对话会话 ID，同时作为 LangGraph 的 thread_id（保证同会话多轮连续）。"""

    user_message: str
    """本轮用户输入文本（已通过 ConversationService 持久化）。"""

    history: list[dict]
    """完整对话历史（OpenAI messages 格式，包含本轮 user 消息）。
    格式：[{"role": "user"|"assistant"|"system", "content": "..."}]
    """

    # ------------------------------------------------------------------ #
    # 快照扩展字段（由 load_project_snapshot 节点填充，9-01 新增）
    # ------------------------------------------------------------------ #

    open_decisions: list[dict]
    """当前项目所有 status='open' 的待决策列表（_decision_to_dict 格式）。
    Director Agent 用于判断是否已有待处理的选项卡/确认卡，避免重复创建。
    无开放决策时为 []。
    """

    selected_decisions: list[dict]
    """关键类型的已选决策列表（status='selected'，含 selected_option_id）。
    用于推断 style_direction / brief_confirmed / shot_plan_confirmed。
    """

    # 旧流程字段：新流程已停用
    # style_direction: Optional[str]
    # """用户已选择的风格方向（来自 select_style_direction 决策的 selected_option_id）。
    # None 表示用户尚未选定风格，audio_analyzed 阶段应展示风格选项。
    # """

    brief_confirmed: bool
    """brief 是否已被用户确认（来自 confirm_brief 决策）。
    doc09 任务 9-04 明确要求的路由条件。
    """

    shot_plan_confirmed: bool
    """shot plan 是否已被用户确认（来自 confirm_shot_plan 决策）。
    doc09 任务 9-04 明确要求的路由条件。
    """

    storyboard_confirmed: bool
    """storyboard 是否已被用户确认可开始生成视频片段（来自 confirm_storyboard 决策）。
    clip 生成是高成本操作，必须先经过此确认门控。
    """

    narrative_confirmed: bool
    """叙事剧本是否已被用户确认（来自 confirm_narrative 决策）。
    doc11 批次1 新增：brief_ready + narrative_confirmed → generate_narrative 路由条件。
    """

    visual_bible_confirmed: bool
    """⚠️ DEPRECATED（doc 21 决策 D1）：视觉圣经阶段已停用，本字段保留以兼容旧 state 数据。
    新流程下 narrative_ready 后直接进 shot_plan，本字段值不影响路由。
    
    旧流程（已停用）：视觉圣经是否已被用户逐一确认（来自 confirm_visual_bible 决策）。
    doc11 批次1：narrative_ready + visual_bible_confirmed → shot_plan 路由条件。
    """

    reference_image_urls: list[str]
    """用户上传的 image_reference 资产 URL 列表（最多 3 张）。
    doc11 批次2 新增：由 load_project_snapshot 填充，供 DirectorAgent 多模态消息使用。
    """

    # 旧流程字段：新流程已停用
    # audio_url: Optional[str]
    # """当前激活的 audio_original 资产 URL（1 个）。
    # doc11 批次2 新增：由 load_project_snapshot 填充，供 DirectorAgent 多模态消息使用。
    # """

    system_trigger: Optional[dict]
    """系统触发信号（doc11 批次4 Mode B）。

    为 None 时 Director 进入 Mode A（对话）。
    不为 None 时 Director 进入 Mode B（汇报）。

    结构示例：
    {
      "type": "task_completed",
      "task_type": "generate_storyboard",
      "result": {"frame_count": 12, ...},
    }
    """

    artifact_ref_for_review: Optional[dict]
    """批次C 新增：Mode B 时供 Director 审核的 ArtifactRef。

    由 DirectorReportService 根据 task_type 从本地文件系统加载并传入。
    Director 在 Mode B 中通过 read_artifact(ref) 读取真实产物内容注入 prompt。
    为 None 时 Director 仅使用静态任务摘要（批次C 之前的行为）。

    结构见 tools/shared/artifact_tools.py — make_artifact_ref()
    """

    pending_decision_id: Optional[str]
    """本轮 human_confirmation_gate 刚创建的 PendingDecision ID。
    用于将决策 ID 透传给 respond_to_user，以便前端定向渲染选项卡。
    """

    # ------------------------------------------------------------------ #
    # 产物引用字段（ArtifactRef，docs/12 偏差 6 §6.2.2）
    # 每个字段是 ArtifactRef dict 或 None，结构：
    #   {"artifact_id": str, "artifact_type": str, "local_path": str,
    #    "minio_uri": str, "version_no": int, "summary": str}
    # 传递引用而非原文内容，Director 需要审核时主动调用 read_artifact(ref)。
    # ------------------------------------------------------------------ #

    # 旧流程字段：新流程已停用
    # audio_analysis_ref: Optional[dict]
    # """音频分析产物引用。
    # 由 audio_analysis_node 在分析完成后填入，
    # Sub-agent 通过 read_artifact(audio_analysis_ref) 读取完整分析数据。
    # """

    brief_ref: Optional[dict]
    """创意方案产物引用（creative_brief）。
    由 generate_brief_node 在 brief 生成并落盘后填入。
    """

    narrative_ref: Optional[dict]
    """叙事剧本产物引用（narrative_script）。
    由 narrative_node 在叙事剧本生成并落盘后填入。
    """

    shot_plan_ref: Optional[dict]
    """镜头计划产物引用（shot_plan）。
    由 generate_shot_plan_node 在 shot plan 生成并落盘后填入。
    """

    visual_bible_ref: Optional[dict]
    """⚠️ DEPRECATED（doc 21 决策 D1）：视觉圣经阶段已停用，本字段保留以兼容旧 state 数据。
    新流程下不再生成此引用，新建项目此字段为 None。
    
    旧流程（已停用）：视觉圣经产物引用（character_set_version + scene refs）。
    由 VisualDevelopmentAgent（Batch B 新建）在视觉圣经固化后填入。
    """

    # ------------------------------------------------------------------ #
    # 中间字段（由图节点逐步填充）
    # ------------------------------------------------------------------ #

    project_snapshot: Optional[dict]
    """项目记忆快照（ProjectSnapshot.model_dump()）。
    由 load_project_snapshot 节点填充，failure 时为 None。
    包含 current_stage、active_versions 等项目事实。
    """

    decision_options: list[dict]
    """Director 当前轮建议给 gate/前端的轻量选项。
    仅保留 options 数组，不保留完整 director_output，避免中间产物滞留在 state。
    """

    # ------------------------------------------------------------------ #
    # 输出字段（由 director_intake 写入，openai_compat.py 读取）
    # ------------------------------------------------------------------ #

    assistant_message: str
    """最终返回给用户的 assistant 回复文本。"""

    requires_confirmation: bool
    """是否需要用户对高成本操作进行确认。"""

    next_action: Optional[str]
    """下一步要执行的内部动作标识（由 IntentResolutionService 解析）。
    例如：analyze_audio / generate_brief / request_style_decision 等。
    None 表示当前轮次不需要触发工具调用。
    """

    # ------------------------------------------------------------------ #
    # 错误字段
    # ------------------------------------------------------------------ #

    error: Optional[str]
    """节点执行过程中发生的错误信息（不抛出异常，降级为错误回复）。
    非 None 时，director_intake 节点会直接返回错误信息给用户。
    """
