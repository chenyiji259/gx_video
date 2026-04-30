"""导演 Agent（Director Agent）。

来源文档：doc 06 §4.1（导演 Agent 职责）

职责（最小版 v1）：
  - 加载 prompts/system/director.md 系统提示词
  - 根据项目状态构造 current_project_summary 和 available_tools
  - 将对话历史转为 LangChain 消息列表
  - 调用 ChatOpenAI（或其他 provider）
  - 安全解析 LLM 返回的结构化 JSON
  - 在 LLM 不可用或返回无效内容时降级为兜底回复

调用方：workflows/main_graph.py 的 director_intake 节点。
不直接面向 API 层，不做数据库写入。
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

import os

from app.core.config import get_config
from app.core.logging import get_agent_logger
from app.core.prompt_renderer import PromptRenderer
from app.tools.director.director_tools import (
    analyze_reference_image_tool,
    create_decision_tool,
    dispatch_agent_tool,
    estimate_cost_tool,
    get_project_state_tool,
    setup_costumes_tool,
)
from app.tools.shared.artifact_tools import read_artifact, read_artifact_tool
from app.workflows.graph_state import ProjectGraphState

_logger = get_agent_logger("director_agent")

# 兑底输出（LLM 不可用或解析失败时使用）
_FALLBACK_MODE = "explain"

# ---------------------------------------------------------------------------
# 全局 LLM 并发限流（解决 30-40 并发用户同时打穿 Qwen 接口触发限流问题）
#
# 设计方案：有界等待（Bounded Waiting）
#
# 等待 vs 排队的区别：
#   asyncio.Semaphore 属于「有界等待」策略：
#     - 40 个请求同时到达，前 20 个立即进入 LLM 调用，
#       后 20 个在 asyncio 事件循环中「挂起等待」（展开 HTTP 连接但不占 CPU）
#     - 某个 LLM 调用完成 → Semaphore 释放 → 下一个请求自动进入
#     - 加 60s 超时防止无限等待（超时返回 503）
#
#   排队（asyncio.Queue + Worker）适合异步任务（如 ToolJob），
#   但聊天接口需要同步回复，用 Semaphore 更简洁。
#
# 限制数配置建议：
#   - qwen3.5-plus 百炼免费额度：通常 60 RPM（每分钟 60 请求）
#   - 20 并发 × 平均 3s LLM响应 = 平均每秒 6.7 请求，远未达到 RPM 限制
#   - 如果百炼账号 RPM 更低，可适当减小此数字
# ---------------------------------------------------------------------------
_LLM_SEMAPHORE = asyncio.Semaphore(20)
_LLM_WAIT_TIMEOUT = 60.0  # 等待进入 Semaphore 的最长秒数，超时返回 503


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

def _build_project_summary(snapshot: dict) -> str:
    """将 ProjectSnapshot dict 转为简洁的自然语言摘要（作为 prompt 变量）。"""
    stage = snapshot.get("current_stage", "unknown")
    av: dict = snapshot.get("active_versions", {})
    completed = [k for k, v in av.items() if v]
    lines = [f"当前阶段：{stage}"]
    if completed:
        lines.append(f"已完成模块：{', '.join(completed)}")
    else:
        lines.append("暂无已完成模块（项目刚创建）")

    # doc11 批次2修复：输出角色/场景参考图进度，供 Director 感知视觉圣经状态
    character_refs: list[dict] = snapshot.get("character_refs", [])
    if character_refs:
        char_lines = []
        for c in character_refs:
            name = c.get("character_name") or c.get("character_id", "?")
            if c.get("active_asset_id"):
                status = "✓ 已有定妆图"
            elif c.get("base_face_asset_id") and not c.get("image_analysis_done"):
                status = f"⚠️ 有上传图待分析 (base_face_asset_id={c['base_face_asset_id']})"
            elif c.get("base_face_asset_id"):
                status = "⏳ 已分析上传图，待生成定妆图"
            else:
                status = "○ 待生成参考图"
            char_lines.append(f"  - {name}：{status}")
        lines.append("角色参考图状态：\n" + "\n".join(char_lines))

    scene_refs: list[dict] = snapshot.get("scene_refs", [])
    if scene_refs:
        scene_lines = [
            f"  - {s.get('scene_name') or s.get('scene_id', '?')}："
            + ("✓ 已有参考图" if s.get("active_asset_id") else "○ 待生成参考图")
            for s in scene_refs
        ]
        lines.append("场景参考图状态：\n" + "\n".join(scene_lines))

    return "\n".join(lines)


def _build_quality_summary_text(quality_summary: dict) -> str:
    """将 quality_summary dict 转为简洁文本，作为 Director prompt 变量。

    quality_summary 结构（来自 AudioAnalysisAgent 输出）：
      {
        "music_structure_summary": {"bpm": ..., "sections": [...], "energy_peaks": [...]},
        "editing_guidance": {"per_section": [{"section": ..., "cut_density": ..., ...}]},
        "emotion_arc": {...}
      }
    """
    if not quality_summary:
        return "暂无音乐摘要，请基于项目创意描述生成风格选项。"

    qs = quality_summary.get("music_structure_summary", {})
    eg = quality_summary.get("editing_guidance", {})

    lines: list[str] = []

    bpm = qs.get("bpm", "")
    if bpm:
        lines.append(f"BPM: {bpm}")

    sections = qs.get("sections", [])
    if sections:
        section_labels = [
            s.get("label", s.get("type", ""))
            for s in sections
            if s.get("label") or s.get("type")
        ]
        if section_labels:
            lines.append(f"结构: {' → '.join(section_labels)}")

    energy_peaks = qs.get("energy_peaks", [])
    if energy_peaks:
        lines.append(f"高潮时间点: {energy_peaks}")

    # editing_guidance.per_section 列表，取副歌段落的剪辑建议
    per_section = eg.get("per_section", [])
    if per_section:
        chorus_hints = [s for s in per_section if s.get("section") == "chorus"]
        if chorus_hints:
            density = chorus_hints[0].get("cut_density", "")
            motion = chorus_hints[0].get("motion_tendency", "")
            hint_parts = [p for p in [density, motion] if p]
            if hint_parts:
                lines.append(f"副歌剪辑建议: {', '.join(hint_parts)}")

    return "\n".join(lines) if lines else str(quality_summary)


def _build_open_decisions_text(open_decisions: list[dict]) -> str:
    """将 open_decisions 列表转为简洁文本。"""
    if not open_decisions:
        return "无待处理决策。"
    lines = []
    for d in open_decisions:
        lines.append(f"- [{d.get('decision_type')}] ID: {d.get('id')}")
    return "\n".join(lines)


def _build_trigger_result_summary(task_type: str, result: dict) -> str:
    """将 Worker/API 任务结果转为简洁文本，供 Mode B 系统 prompt 使用。"""
    # doc12 偏差6修复：补充文本产物任务类型（这三类通过图内 Mode B 触发，非 Worker）
    if task_type == "generate_brief":
        brief_v = result.get("brief_version_no", "?")
        style_v = result.get("style_version_no", "?")
        artifact_ref = result.get("artifact_ref") or {}
        summary = artifact_ref.get("summary", "")
        parts = [f"创意方案已生成，版本 v{brief_v}，风格圣经版本 v{style_v}。"]
        if summary:
            parts.append(f"产物摘要：{summary}")
        return "".join(parts)
    if task_type == "generate_narrative":
        version_no = result.get("version_no", "?")
        char_count = result.get("character_count", "?")
        scene_count = result.get("scene_count", "?")
        section_count = result.get("section_count", "?")
        return (
            f"叙事剧本已生成，版本 v{version_no}，"
            f"共 {char_count} 个角色、{scene_count} 个场景、{section_count} 个段落映射。"
        )
    if task_type == "generate_shot_plan":
        shot_count = result.get("shot_count", "?")
        scene_count = result.get("scene_count", "?")
        version_no = result.get("shot_plan_version_no", "?")
        return (
            f"镜头计划已生成，版本 v{version_no}，"
            f"共 {shot_count} 个镜头、{scene_count} 个场景。"
        )
    if task_type == "generate_storyboard":
        frame_count = result.get("frame_count", "?") or "?"
        version_no = result.get("version_no", "?")
        return f"分镜图已全部生成，共 {frame_count} 张，版本 v{version_no}。"
    if task_type == "generate_clips":
        clip_count = result.get("clip_count", "?") or "?"
        return f"视频片段已全部生成，共 {clip_count} 个 clip。"
    if task_type == "generate_timeline":
        version_no = result.get("version_no", "?")
        return f"时间线已合成完成，版本 v{version_no}。"
    if task_type == "init_visual_bible":
        version_no = result.get("version_no", "?")
        char_count = result.get("character_count", "?")
        scene_count = result.get("scene_count", "?")
        return (
            f"视觉圣经已初始化，版本 v{version_no}，"
            f"共包含 {char_count} 个角色、{scene_count} 个场景。"
        )
    # doc11 批次4修复：视觉圣经任务
    if task_type == "generate_character_ref":
        character_id = result.get("character_id", "")
        character_name = result.get("character_name", character_id or "?")
        asset_id = result.get("asset_id", "?")
        version_no = result.get("version_no", 1)
        return (
            f"角色「{character_name}」的参考图已生成，"
            f"资产 ID: {asset_id}，版本 v{version_no}。"
        )
    if task_type == "generate_scene_ref":
        scene_id = result.get("scene_id", "")
        scene_name = result.get("scene_name", scene_id or "?")
        asset_id = result.get("asset_id", "?")
        version_no = result.get("version_no", 1)
        return (
            f"场景「{scene_name}」的参考图已生成，"
            f"资产 ID: {asset_id}，版本 v{version_no}。"
        )
    if task_type == "analyze_audio":
        bpm = result.get("bpm") or result.get("tempo") or "?"
        section_count = result.get("section_count") or len(result.get("sections") or [])
        lyric_lines = result.get("lyric_line_count") or ""
        parts = [f"音频分析已完成。BPM: {bpm}。"]
        if section_count:
            parts.append(f"识别出 {section_count} 个段落。")
        if lyric_lines:
            parts.append(f"歌词 {lyric_lines} 行。")
        return "".join(parts)
    # Bug7 修复：补充造型参考图任务的汇报文案
    if task_type == "generate_costume_ref":
        character_id = result.get("character_id", "")
        costume_id = result.get("costume_id", "")
        asset_id = result.get("asset_id", "?")
        return (
            f"造型「{costume_id}」的定妆图已生成（角色 {character_id}），"
            f"资产 ID: {asset_id}。"
        )
    if task_type == "auto_setup_costumes":
        total = result.get("total_characters", "?")
        return f"多造型自动设置已完成，共处理 {total} 个角色。"
    # 通用兤底
    return f"任务 {task_type!r} 已完成。结果：{result}"


def _build_lc_messages(history: list[dict]) -> list:
    """将 OpenAI messages 格式历史转为 LangChain 消息对象列表。"""
    result = []
    for m in history:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "user":
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
        elif role == "system":
            result.append(SystemMessage(content=content))
    return result


def _build_multimodal_message(
    text: str,
    *,
    image_urls: list[str],
    audio_url: str | None,
) -> HumanMessage:
    """将用户消息包装为多模态 HumanMessage（图 + 音频 + 文字）。

    doc11 批次2：当项目有用户上传参考图或音频时调用此函数。

    图片使用 {"type": "image_url", "image_url": {"url": ...}} 格式。
    音频使用 {"type": "input_audio", "input_audio": {"url": ..., "format": "mp3"}} 格式，
    如果底层模型不支持该格式则降级为 url 类型。
    """
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]

    # 附加参考图（最多 3 张）
    for url in image_urls[:3]:
        if url:
            content.append({"type": "image_url", "image_url": {"url": url}})

    # 附加音频（OpenAI 多模态 input_audio 格式）
    if audio_url:
        # 推断音频格式
        fmt = "mp3"
        audio_lower = audio_url.lower().split("?")[0]
        if audio_lower.endswith(".wav"):
            fmt = "wav"
        elif audio_lower.endswith(".flac"):
            fmt = "flac"
        content.append({
            "type": "input_audio",
            "input_audio": {"url": audio_url, "format": fmt},
        })

    return HumanMessage(content=content)


def _safe_parse_json(text: str) -> dict:
    """从 LLM 输出中安全提取 JSON（处理 markdown 代码块、前后缀文本等情况）。

    解析顺序：
      1. 直接 json.loads
      2. 提取 ```json...``` 块内容
      3. 正则匹配最外层 {...}
      4. 返回兜底 dict
    """
    text = text.strip()

    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 提取 markdown 代码块
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. 正则匹配最外层 JSON 对象
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # 4. 兜底：把整个文本作为 message 返回
    _logger.warning(
        f"Director Agent JSON 解析失败，降级为兜底输出。LLM 原文：{text[:200]!r}",
        event_type="director_json_parse_failed",
    )
    return _make_fallback_output(text)


def _extract_last_ai_text(messages: list[Any]) -> str:
    """提取最后一条 AIMessage 的文本内容。"""
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            return content
        return str(content)
    return ""


def _extract_last_tool_payload(messages: list[Any], tool_name: str) -> dict | None:
    """提取指定 tool 的最后一次 ToolMessage JSON 结果。"""
    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            continue
        if getattr(msg, "name", None) != tool_name:
            continue
        try:
            payload = json.loads(msg.content)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _make_fallback_output(message: str) -> dict:
    """构造兜底 DirectorOutput dict（LLM 不可用或解析失败时使用）。"""
    return {
        "mode": _FALLBACK_MODE,
        "message": message,
        "intent": "unknown",
        "target": None,
        "patch": {},
        "missing_fields": [],
        "options": [],
        "estimated_cost": None,
        "requires_confirmation": False,
        "next_action": None,
    }


# ---------------------------------------------------------------------------
# Director Agent
# ---------------------------------------------------------------------------

class DirectorAgent:
    """导演 Agent：接受图状态，调用 LLM，返回结构化输出 dict。

    无副作用：不写数据库，不修改状态，只返回 DirectorOutput dict。

    LLM 客户端懒加载（首次调用时建立），避免每请求重新实例化。
    """

    def __init__(self) -> None:
        self._renderer = PromptRenderer()
        self._llm: Any = None  # 懒加载，首次调用时建立

    async def run(self, state: ProjectGraphState) -> dict:
        """执行一轮 Director Agent 调用。

        Args:
            state: 当前图状态（至少需要 history、project_snapshot）。

        Returns:
            DirectorOutput dict，格式与 prompts/system/director.md 一致。
            任何异常均被捕获，返回兜底 dict，不抛出。
        """
        # --- 1. 加载 LLM 配置（Director 使用 qwen3.5-plus 文本+图片模型）
        #
        # 为什么不用 qwen3.5-omni-plus？
        #   DashScope compatible 模式下 omni 模型不支持 Function Calling（tools= 参数），
        #   create_react_agent 必须使用 bind_tools()，触发工具调用会返回 403。
        #   qwen3.5-plus 支持图片输入 + 工具调用，覆盖 Director 全部需求。
        #   音频分析已由 AudioAnalysisAgent（omni）完成，Director 只需读文本摘要。
        cfg = get_config().llm
        api_key: str = cfg.api_key

        if not api_key:
            _logger.warning(
                f"Director API key 未设置（环境变量 {cfg.api_key_env} 为空）",
                event_type="director_no_api_key",
            )
            return _make_fallback_output(
                f"[Director Agent 未激活] 请联系管理员设置环境变量 {cfg.api_key_env}。\n"
                "当前系统已收到您的消息，但无法生成 AI 回复。"
            )

        # --- 2. 构造 prompt 变量 ---
        snapshot: dict = state.get("project_snapshot") or {}
        stage = snapshot.get("current_stage", "created")
        project_summary = _build_project_summary(snapshot)

        # 阶段感知扩展变量（9-01 新增）
        quality_summary: dict = {}
        audio_analysis_ref = state.get("audio_analysis_ref")
        if audio_analysis_ref:
            try:
                audio_artifact = await read_artifact(audio_analysis_ref)
                quality_summary = (
                    audio_artifact.get("quality_summary")
                    or audio_artifact.get("music_structure_summary")
                    or audio_artifact
                )
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    f"Director 读取 audio_analysis_ref 失败: {exc!r}",
                    event_type="director_audio_ref_read_failed",
                )
        quality_summary_text = _build_quality_summary_text(quality_summary)
        open_decisions: list = state.get("open_decisions") or []
        open_decisions_text = _build_open_decisions_text(open_decisions)
        style_direction = state.get("style_direction") or "尚未选择"
        brief_confirmed = state.get("brief_confirmed", False)
        narrative_confirmed = state.get("narrative_confirmed", False)
        visual_bible_confirmed = state.get("visual_bible_confirmed", False)
        shot_plan_confirmed = state.get("shot_plan_confirmed", False)

        # doc11 批次4：Mode B 变量
        system_trigger: dict | None = state.get("system_trigger")
        is_mode_b = bool(system_trigger)
        if is_mode_b:
            trigger_task_type = system_trigger.get("task_type", "unknown")  # type: ignore[union-attr]
            trigger_result = system_trigger.get("result") or {}             # type: ignore[union-attr]
            trigger_result_summary = _build_trigger_result_summary(
                trigger_task_type, trigger_result
            )
        else:
            trigger_task_type = ""
            trigger_result_summary = ""

        # 批次C：Mode B 时主动读取 ArtifactRef 产物内容
        # DirectorReportService 会加载对应任务的 ArtifactRef 并传入 state
        artifact_content_for_review = ""
        if is_mode_b:
            artifact_ref = state.get("artifact_ref_for_review")
            if artifact_ref and artifact_ref.get("local_path"):
                try:
                    from app.tools.director.director_tools import read_artifact_for_review  # noqa: PLC0415
                    artifact_content_for_review = await read_artifact_for_review(artifact_ref)
                    _logger.debug(
                        f"Director Mode B 读取 ArtifactRef: "
                        f"{artifact_ref.get('artifact_id')!r} "
                        f"content_len={len(artifact_content_for_review)}",
                        event_type="director_mode_b_artifact_read",
                    )
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        f"Director Mode B read_artifact_for_review 失败: {exc!r}",
                        event_type="director_mode_b_artifact_read_failed",
                    )
                    artifact_content_for_review = ""

        try:
            system_prompt = self._renderer.render(
                "director_system",
                {
                    "project_id": state.get("project_id", ""),
                    "user_id": state.get("user_id", ""),
                    "project_stage": stage,
                    "current_project_summary": project_summary,
                    "quality_summary_text": quality_summary_text,
                    "style_direction": style_direction,
                    "brief_confirmed": str(brief_confirmed),
                    "narrative_confirmed": str(narrative_confirmed),
                    "visual_bible_confirmed": str(visual_bible_confirmed),
                    "shot_plan_confirmed": str(shot_plan_confirmed),
                    "open_decisions_text": open_decisions_text,
                    # Mode B 变量
                    "mode": "report" if is_mode_b else "conversation",
                    "trigger_task_type": trigger_task_type,
                    "trigger_result_summary": trigger_result_summary,
                    # 批次C 新增：Mode B 产物内容（有内容时注入，无内容时为空字符串）
                    "artifact_content_for_review": artifact_content_for_review,
                },
            )
        except Exception as exc:
            _logger.error(
                f"Prompt 渲染失败: {exc}",
                event_type="director_prompt_render_failed",
            )
            return _make_fallback_output(f"[系统错误] Prompt 渲染失败：{exc}")

        # --- 3. 构造消息列表（系统 prompt + 历史 + 多模态注入）---
        history: list[dict] = state.get("history") or []
        lc_history = _build_lc_messages(history)

        # doc11 批次2：图片多模态处理（qwen3.5-plus 支持图片输入）
        # 音频不传入 Director（omni 模型不支持工具调用，音频分析已由 AudioAnalysisAgent 完成）
        reference_image_urls: list[str] = state.get("reference_image_urls") or []

        has_multimodal = bool(reference_image_urls)
        if has_multimodal and lc_history:
            # 只对最后一条用户消息多模态化——避免历史过长
            last_msg = lc_history[-1]
            if isinstance(last_msg, HumanMessage):
                last_text = (
                    last_msg.content
                    if isinstance(last_msg.content, str)
                    else next(
                        (c.get("text", "") for c in last_msg.content if isinstance(c, dict) and c.get("type") == "text"),
                        "",
                    )
                )
                lc_history[-1] = _build_multimodal_message(
                    last_text,
                    image_urls=reference_image_urls,
                    audio_url=None,  # Director 不直接处理音频，已由 AudioAnalysisAgent 完成
                )
                _logger.debug(
                    f"Director 多模态消息构造: "
                    f"images={len(reference_image_urls)} audio=False",
                    event_type="director_multimodal_message",
                )

        lc_messages = [SystemMessage(content=system_prompt)] + lc_history

        # doc11 批次4/批次 D：若为 Mode B 且历史为空或最后一条不是 HumanMessage，
        # 注入一条合成指令让 Agent 开始汇报
        if is_mode_b:
            trigger_text = f"[系统触发] 任务 {trigger_task_type!r} 已完成，请执行汇报协议。"
            lc_messages.append(HumanMessage(content=trigger_text))

        # --- 4. 获取懒加载 LLM（qwen3.5-omni-plus），Semaphore 限制并发 ---
        dispatch_result: dict | None = None
        created_decision: dict | None = None
        raw_text: str = ""
        try:
            # 懒加载：首次调用时建立 ChatOpenAI，后续复用同一实例
            # qwen3.5-plus 需要关闭思考模式，否则输出 <think> 块破坏 JSON 解析
            if self._llm is None:
                extra_body = {"enable_thinking": False} if not cfg.enable_thinking else None
                self._llm = ChatOpenAI(
                    model=cfg.model,
                    api_key=api_key,
                    base_url=cfg.base_url,
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_tokens,
                    timeout=cfg.timeout,
                    extra_body=extra_body,
                )
            llm = self._llm

            # 注册 Director 专属工具
            tools = [
                dispatch_agent_tool,
                read_artifact_tool,
                create_decision_tool,
                get_project_state_tool,
                estimate_cost_tool,
                analyze_reference_image_tool,
                setup_costumes_tool,
            ]
            tools = [t for t in tools if t is not None]

            agent = create_react_agent(model=llm, tools=tools)

            # 用全局 Semaphore 限制并发 LLM 调用数
            # 超时 _LLM_WAIT_TIMEOUT 秒返回兜底，避免用户无限等待
            try:
                async with asyncio.timeout(_LLM_WAIT_TIMEOUT):
                    async with _LLM_SEMAPHORE:
                        result = await agent.ainvoke(
                            {"messages": lc_messages},
                            config={"recursion_limit": 15},
                        )
            except TimeoutError:
                _logger.warning(
                    f"Director LLM 等待超时（>{_LLM_WAIT_TIMEOUT}s）",
                    event_type="director_llm_semaphore_timeout",
                )
                return _make_fallback_output(
                    "当前请求量较高，AI 处理队列有点拥堵，请稍后再试。"
                )

            # 提取 LLM 回复文本和工具调用结果
            messages = result.get("messages", [])
            raw_text = _extract_last_ai_text(messages)
            if not raw_text and messages:
                final_msg = messages[-1]
                raw_text = (
                    final_msg.content
                    if hasattr(final_msg, "content")
                    else str(final_msg)
                )
            dispatch_result = _extract_last_tool_payload(messages, "dispatch_agent_tool")
            created_decision = _extract_last_tool_payload(messages, "create_decision_tool")

        except Exception as exc:
            _logger.error(
                f"Director ReAct Agent 调用失败: {exc!r}",
                event_type="director_react_failed",
            )
            return _make_fallback_output(
                f"[LLM 调用失败] {type(exc).__name__}: {exc}\n"
                "请稍后重试，或联系管理员检查 API 配置。"
            )

        # --- 5. 安全解析 JSON ---
        director_out = _safe_parse_json(raw_text)
        if dispatch_result and not dispatch_result.get("error"):
            director_out["dispatch_result"] = dispatch_result
        if created_decision and not created_decision.get("error"):
            director_out["created_decision"] = created_decision

        _logger.info(
            f"Director Agent 完成: mode={director_out.get('mode')!r} "
            f"intent={director_out.get('intent')!r} "
            f"next_action={director_out.get('next_action')!r}",
            event_type="director_completed",
        )
        return director_out
