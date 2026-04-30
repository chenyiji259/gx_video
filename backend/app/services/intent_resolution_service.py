"""Intent Resolution Service — 将 Director Agent 输出翻译为系统内部 IntentResult。

来源文档：doc 03 §12（对话到任务的桥接）

职责：
  接收 DirectorAgent.run() 返回的结构化 dict（director_output），
  翻译为系统可执行的 IntentResult，决定：
    1. 向用户展示什么文本（user_message）
    2. 是否需要用户确认（requires_confirmation）
    3. 下一步触发哪个内部动作（next_action）

最小版 v1 支持的 intent 集合：
  clarify        — 缺少必填字段，Director 需要反问
  ask_input      — 提示用户上传或填写输入
  complete_input — 输入规格已齐全，可进入主流程
  analyze_audio  — 触发音频分析流程
  get_status     — 查询项目当前状态
  recommend      — 给出选项供用户选择
  explain        — 解释性回复（默认，不触发动作）
  unknown        — 无法识别，降级为 explain
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# IntentResult 数据类
# ---------------------------------------------------------------------------

@dataclass
class IntentResult:
    """Intent Resolution 的输出结果。"""

    # 向用户展示的自然语言回复
    user_message: str

    # 意图标识
    intent: str = "explain"

    # 操作目标（可选，如 {"type": "shot", "id": "..."}）
    target: Optional[dict] = None

    # 本轮修改 patch（可选，用于局部修改场景）
    patch: Optional[dict] = None

    # 缺失字段列表（clarify 模式下填充）
    missing_fields: list[str] = field(default_factory=list)

    # 选项列表（recommend 模式下填充）
    options: list[dict] = field(default_factory=list)

    # 是否需要用户对高成本操作确认
    requires_confirmation: bool = False

    # 下一步内部动作标识（None = 不触发动作）
    next_action: Optional[str] = None


# ---------------------------------------------------------------------------
# 已知 next_action 白名单（只有白名单内的值才会被系统执行）
# ---------------------------------------------------------------------------

# v2 阶段可执行的动作集合（包含任务 9-01 扩充）
_EXECUTABLE_ACTIONS: frozenset[str] = frozenset([
    # Group 8 已激活
    # "analyze_audio",                    # 旧流程（音乐MV模式）：已停用
    "complete_input",                   # 输入规格已齐全
    # Group 9 新增（9-01）
    # "request_style_decision",           # 旧流程（音乐MV模式）：已停用（风格由 LLM 从 brief 自动推断）
    "generate_brief",                   # 风格已选，生成 brief+style
    "request_brief_confirmation",       # brief_ready：确认 brief
    "generate_narrative",               # brief 已确认，生成叙事剧本
    "request_narrative_confirmation",   # narrative_ready：确认叙事剧本
    "request_visual_bible_confirmation",# visual_bible_ready：确认视觉圣经
    "generate_shot_plan",               # brief 已确认，生成镜头计划
    "request_shot_plan_confirmation",   # shot_plan_ready：确认镜头计划
    "generate_storyboard",              # shot_plan 已确认，生成分镜
    "request_storyboard_confirmation",  # storyboard_ready：确认分镜
    "generate_clips",                   # 分镜已确认，生成 clips
    "generate_timeline",                # clips 完成，生成时间线
])


# ---------------------------------------------------------------------------
# IntentResolutionService
# ---------------------------------------------------------------------------

class IntentResolutionService:
    """将 DirectorOutput dict 翻译为 IntentResult。

    纯函数式，无副作用，无数据库依赖。
    """

    def resolve(self, director_output: dict) -> IntentResult:
        """解析 Director Agent 输出，返回 IntentResult。

        Args:
            director_output: DirectorAgent.run() 的返回值（结构化 JSON dict）。

        Returns:
            IntentResult，包含展示文本、动作标识等字段。
        """
        mode: str = director_output.get("mode", "explain") or "explain"
        message: str = director_output.get("message", "") or ""
        intent: str = director_output.get("intent", "unknown") or "unknown"
        raw_next_action: Optional[str] = director_output.get("next_action")
        requires_confirmation: bool = bool(director_output.get("requires_confirmation", False))
        missing_fields: list[str] = director_output.get("missing_fields") or []
        options: list[dict] = director_output.get("options") or []
        target: Optional[dict] = director_output.get("target")
        patch: Optional[dict] = director_output.get("patch") or {}

        # --- 校验 next_action（只允许白名单内的值执行）---
        next_action: Optional[str] = None
        if raw_next_action and raw_next_action in _EXECUTABLE_ACTIONS:
            next_action = raw_next_action

        # --- 按 mode 映射 intent ---
        resolved_intent = self._resolve_intent(mode, intent, next_action)

        # --- 确保 user_message 不为空 ---
        if not message.strip():
            message = self._default_message(resolved_intent)

        return IntentResult(
            user_message=message,
            intent=resolved_intent,
            target=target,
            patch=patch if patch else None,
            missing_fields=missing_fields,
            options=options,
            requires_confirmation=requires_confirmation,
            next_action=next_action,
        )

    @staticmethod
    def _resolve_intent(mode: str, raw_intent: str, next_action: Optional[str]) -> str:
        """将 Director mode + intent 映射为标准化 intent 字符串。"""
        # mode = clarify：缺字段，需要反问
        if mode == "clarify":
            return "clarify"

        # mode = recommend：展示选项
        if mode == "recommend":
            return "recommend"

        if mode == "report":
            return "explain"

        # mode = execute：有实际动作要触发
        if mode == "execute":
            if next_action:
                return next_action  # 直接用动作名作为 intent
            return "explain"

        # mode = explain / 兜底
        # 如果原始 intent 是已知的有效值，使用它
        known_intents = {
            "clarify", "ask_input", "complete_input",
            "analyze_audio", "get_status", "recommend", "explain",
            # 9-01 新增
            "request_style_decision", "generate_brief",
            "request_brief_confirmation", "generate_shot_plan",
            "request_shot_plan_confirmation",
            "generate_narrative", "request_narrative_confirmation",
            "request_visual_bible_confirmation",
            "generate_storyboard", "request_storyboard_confirmation",
            "generate_clips", "generate_timeline",
        }
        if raw_intent in known_intents:
            return raw_intent

        return "explain"

    @staticmethod
    def _default_message(intent: str) -> str:
        """当 Director 返回空 message 时，根据 intent 提供默认文案。"""
        defaults = {
            "clarify":        "请提供更多信息，以便系统继续执行。",
            "ask_input":      "请上传音频文件并填写创意描述，再开始生成。",
            "complete_input": "输入规格已齐全，可以开始进入 AI 生产流程了。",
            "analyze_audio":  "好的，系统将开始分析您上传的音频。",
            "get_status":     "已获取项目当前状态。",
            "recommend":      "为您提供以下选项，请选择一个继续。",
        }
        return defaults.get(intent, "已收到您的消息。")
