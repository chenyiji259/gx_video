"""human_confirmation_gate — 人工确认节点。

来源文档：doc 09 任务 9-04

职责：
  - 按当前 next_action 幂等地创建对应 PendingDecision
  - 把 pending_decision_id 写回 GraphState
  - 返回用于展示给用户的 assistant_message
  - 所有操作通过 DecisionService，不直接写数据库

支持的 next_action → decision_type 映射：
  request_style_decision           → select_style_direction
  request_brief_confirmation       → confirm_brief
  request_shot_plan_confirmation   → confirm_shot_plan
  request_storyboard_confirmation  → confirm_storyboard
"""
from __future__ import annotations

from app.core.config import get_config
from app.core.logging import get_logger
from app.services.decision_service import DecisionService
from app.workflows.graph_state import ProjectGraphState

_logger = get_logger("workflows.nodes.human_confirmation_gate", layer="system")

# next_action → (decision_type, target_entity_type)
_ACTION_TO_DECISION: dict[str, tuple[str, str]] = {
    "request_style_decision":            ("select_style_direction", "project"),
    "request_brief_confirmation":        ("confirm_brief",          "project"),
    "request_narrative_confirmation":    ("confirm_narrative",      "project"),
    "request_visual_bible_confirmation": ("confirm_visual_bible",   "project"),
    "request_shot_plan_confirmation":    ("confirm_shot_plan",      "project"),
    "request_storyboard_confirmation":   ("confirm_storyboard",     "project"),
}

# 各 decision_type 的默认选项（若 Director 没有提供 options）
_DEFAULT_OPTIONS: dict[str, list[dict]] = {
    "select_style_direction": [
        {"id": "style_cinematic", "title": "电影感", "summary": "高对比、暖色调、慢推拉"},
        {"id": "style_indie",     "title": "独立风", "summary": "自然光、颗粒感、跟拍运动"},
        {"id": "style_neon",      "title": "霓虹感", "summary": "强饱和、夜景、冷蓝/紫色调"},
    ],
    "confirm_brief": [
        {"id": "confirm",     "title": "确认创意方案并继续"},
        {"id": "regenerate",  "title": "重新生成创意方案"},
    ],
    "confirm_narrative": [
        {"id": "confirm",     "title": "确认创意剧本包并生成关键帧"},
        {"id": "regenerate",  "title": "重新生成创意剧本包"},
    ],
    "confirm_visual_bible": [
        {"id": "confirm",     "title": "确认视觉方向并继续"},
        {"id": "regenerate",  "title": "重新生成参考图"},
    ],
    "confirm_shot_plan": [
        {"id": "confirm",     "title": "确认镜头计划并生成分镜"},
        {"id": "regenerate",  "title": "重新生成镜头计划"},
    ],
    "confirm_storyboard": [
        {"id": "confirm",     "title": "确认关键帧并开始生成视频"},
        {"id": "regenerate",  "title": "重新生成关键帧"},
    ],
}

# 调试模式：各 decision_type 对应的自动确认选项
# 尝试匹配 default_option_id，若匹配失败则取 _DEFAULT_OPTIONS 第一项
_AUTO_CONFIRM_OPTION: dict[str, str] = {
    "select_style_direction": "style_cinematic",  # 第一个预设风格
    "confirm_brief":          "confirm",
    "confirm_narrative":      "confirm",
    "confirm_visual_bible":   "confirm",
    "confirm_shot_plan":      "confirm",
    "confirm_storyboard":     "confirm",
}

# 各 decision_type 的用户提示文案
_USER_MESSAGES: dict[str, str] = {
    "select_style_direction": (
        "音乐分析已完成！请选择一个视觉风格方向，系统将据此生成创意方案："
    ),
    "confirm_brief": (
        "创意方案已生成，请查看并确认，或选择重新生成："
    ),
    "confirm_narrative": (
        "创意剧本包已生成，请查看并确认，或选择重新生成："
    ),
    "confirm_visual_bible": (
        "视觉圣经已生成，请确认当前角色/场景方向，或选择重新生成："
    ),
    "confirm_shot_plan": (
        "镜头计划已生成，请确认后开始生成分镜图："
    ),
    "confirm_storyboard": (
        "关键帧画面已生成，请确认后开始生成视频片段（高成本操作，请确认预计消耗 credits）："
    ),
}


async def human_confirmation_gate(state: ProjectGraphState) -> dict:
    """幂等地创建 PendingDecision，并把决策 ID 写回图状态。

    输入（从 state 读取）：
      project_id (str)
      session_id (str)
      next_action (str) — 决定创建哪种 decision_type
      decision_options (list[dict]) — Director 当前轮建议选项

    输出（写入 state）：
      pending_decision_id (str | None) — 新创建或已有 open decision 的 ID
      assistant_message (str)          — 展示给用户的提示文案
      requires_confirmation (bool)     — True，告知前端需要用户操作
      next_action (None)               — 清空，防止路由循环
    """
    project_id: str = state.get("project_id", "")
    session_id: str = state.get("session_id", "")
    next_action: str = state.get("next_action") or ""
    decision_options: list[dict] = state.get("decision_options") or []

    if not project_id or not session_id:
        return {
            "assistant_message": "[系统错误] 缺少 project_id 或 session_id，无法创建确认决策",
            "pending_decision_id": None,
            "requires_confirmation": False,
            "next_action": None,
        }

    # 查找 decision_type
    if next_action not in _ACTION_TO_DECISION:
        # 按阶段备用：检查 project_snapshot
        snapshot = state.get("project_snapshot") or {}
        stage = snapshot.get("current_stage", "")
        _stage_fallback = {
            "audio_analyzed":   "request_style_decision",
            "brief_ready":      "request_brief_confirmation",
            "narrative_ready":  "request_narrative_confirmation",
            "visual_bible_ready": "request_visual_bible_confirmation",
            "shot_plan_ready":  "request_shot_plan_confirmation",
            "storyboard_ready": "request_storyboard_confirmation",
        }
        next_action = _stage_fallback.get(stage, "")

    if next_action not in _ACTION_TO_DECISION:
        return {
            "assistant_message": "正在等待您的操作...",
            "pending_decision_id": None,
            "requires_confirmation": True,
            "next_action": None,
        }

    decision_type, target_entity_type = _ACTION_TO_DECISION[next_action]
    svc = DecisionService()

    # 幂等检查：已有 open decision 则直接复用
    has_open = await svc.has_open_decision_of_type(project_id, decision_type)
    if has_open:
        open_list = await svc.get_pending_decisions(project_id)
        existing = next(
            (d for d in open_list if d.get("decision_type") == decision_type), None
        )
        decision_id = existing["id"] if existing else None
        _logger.info(
            f"human_confirmation_gate: 复用已有 decision type={decision_type!r} id={decision_id!r}",
            event_type="gate_reuse_decision",
        )
    else:
        # 补丁：检查是否刚选过（防止因舞台切换延迟导致的回环）
        has_selected = await svc.has_selected_decision_of_type(project_id, decision_type)
        if has_selected:
            _logger.info(
                f"human_confirmation_gate: 决策 {decision_type!r} 已选择且尚未切换阶段，跳过创建",
                event_type="gate_skip_selected",
            )
            return {
                "assistant_message": "收到！正在为您生成产物，请稍候...",
                "pending_decision_id": None,
                "requires_confirmation": False,
                "next_action": None,
            }

        options: list[dict] = decision_options or []
        if not options:
            options = _DEFAULT_OPTIONS.get(decision_type, [])

        decision = await svc.create_decision(
            project_id=project_id,
            session_id=session_id,
            decision_type=decision_type,
            target_entity_type=target_entity_type,
            options_payload=options,
        )
        decision_id = decision["id"]
        _logger.info(
            f"human_confirmation_gate: 创建新 decision type={decision_type!r} id={decision_id!r}",
            event_type="gate_create_decision",
        )

    user_msg = _USER_MESSAGES.get(decision_type, "请做出选择以继续。")

    # ---------------------------------------------------------------------------
    # 调试模式：自动确认（auto_confirm_decisions=true 时生效）
    # ---------------------------------------------------------------------------
    cfg = get_config()
    if cfg.workflow.auto_confirm_decisions:
        auto_option = _AUTO_CONFIRM_OPTION.get(decision_type)
        # 如果默认选项不在当前选项列表中，取第一个合法选项
        options_for_check = _DEFAULT_OPTIONS.get(decision_type, [])
        valid_ids = {opt["id"] for opt in options_for_check if opt.get("id")}
        if auto_option not in valid_ids and valid_ids:
            auto_option = next(iter(valid_ids))
        if auto_option and decision_id:
            try:
                await svc.submit_decision(
                    project_id=project_id,
                    decision_id=decision_id,
                    selected_option_id=auto_option,
                )
                _logger.info(
                    f"[DEBUG] auto_confirm_decisions: 自动确认 "
                    f"type={decision_type!r} option={auto_option!r} id={decision_id!r}",
                    event_type="gate_auto_confirmed",
                )
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    f"[DEBUG] auto_confirm_decisions: 自动确认失败 "
                    f"type={decision_type!r} id={decision_id!r}: {exc!r}",
                    event_type="gate_auto_confirm_failed",
                )
        auto_msg = f"[调试模式] 已自动确认：{user_msg}（选项：{auto_option}）"
        return {
            "pending_decision_id": decision_id,
            "assistant_message": auto_msg,
            "requires_confirmation": False,
            "next_action": None,
        }

    # ---------------------------------------------------------------------------
    # 正常模式：等待用户手动确认
    # ---------------------------------------------------------------------------
    # doc12 偏差6修复：Mode B 时 Director 已在 director_intake 中生成三段式汇报，
    # 保留其 assistant_message 并在末尾追加确认提示，而不是直接覆盖。
    # system_trigger 非空 + assistant_message 有内容 = Mode B 场景（文本产物生成后回路）。
    existing_message: str = (state.get("assistant_message") or "").strip()
    system_trigger = state.get("system_trigger")
    if system_trigger and existing_message:
        final_msg = existing_message + "\n\n---\n\n" + user_msg
    else:
        final_msg = user_msg

    return {
        "pending_decision_id": decision_id,
        "assistant_message": final_msg,
        "requires_confirmation": True,
        "next_action": None,  # 清空，防止下次路由再次进入 gate
    }
