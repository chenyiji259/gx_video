"""叙事剧本 Sub-Agent（NarrativeScriptAgent，Batch B 改造版）。

来源文档：doc12 §6.2.4（Sub-Agent 工作协议）/ doc12 批次B

改造内容：
  - 由 Batch A 的单次 ChatOpenAI.ainvoke() 改为 create_react_agent 结构
  - Agent 拥有独立的 LLM tool-calling 循环
  - 通过 write_artifact_tool 写出产物，返回值为 ArtifactRef

工具集：
  - read_artifact_tool  : 可选，读取上游 ArtifactRef 内容
  - write_artifact_tool : 写出 narrative_script 产物，返回 ArtifactRef

接口：
  run(task_spec: dict) -> dict   # 返回 narrative_script ArtifactRef
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from app.core.config import get_config
from app.core.logging import get_agent_logger
from app.core.prompt_renderer import PromptRenderer
from app.tools.shared.artifact_tools import (
    make_artifact_ref,
    read_artifact_tool,
    write_artifact,
    write_artifact_tool,
)

_logger = get_agent_logger("narrative_script_agent")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _extract_last_write_result(agent_result: dict) -> dict | None:
    """从 create_react_agent 输出中提取最后一次 write_artifact_tool 的结果。"""
    messages = agent_result.get("messages", [])
    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            continue
        tool_name = getattr(msg, "name", None)
        if tool_name not in (None, "write_artifact_tool"):
            continue
        try:
            data = json.loads(msg.content)
            if isinstance(data, dict) and "artifact_id" in data and data["artifact_id"]:
                return data
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _extract_last_ai_json(agent_result: dict) -> dict | None:
    """从 agent 输出中提取最后一条 AIMessage 的 JSON 正文。

    某些模型会直接返回完整 JSON，但不会按预期调用 write_artifact_tool。
    旧逻辑会把这类有效正文直接丢弃并走 fallback。
    这里做一次兜底提取，尽量保留真实 LLM 输出。
    """
    messages = agent_result.get("messages", [])
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
                elif isinstance(item, str):
                    parts.append(item)
            content = "\n".join(p for p in parts if p).strip()
        elif not isinstance(content, str):
            content = str(content or "").strip()
        if not content:
            continue
        parsed = _try_parse_json_strict(content)
        if isinstance(parsed, dict) and parsed.get("shots"):
            return parsed
    return None


def _is_explainer_prompt(user_prompt: str) -> bool:
    text = (user_prompt or "").lower()
    keywords = [
        "讲解", "解说", "介绍", "科普", "教程", "说明", "旁白",
        "explain", "explainer", "tutorial", "voiceover", "education",
    ]
    return any(keyword in text for keyword in keywords)


def _is_ad_prompt(user_prompt: str) -> bool:
    text = (user_prompt or "").lower()
    keywords = [
        "广告", "带货", "种草", "推广", "品牌", "宣传", "转化", "口号", "cta",
        "ad", "ads", "brand", "promo", "promotion", "commercial", "campaign",
    ]
    return any(keyword in text for keyword in keywords)


def _build_fallback_dialogues(user_prompt: str, total_shots: int) -> list[str]:
    topic = (user_prompt or "这个主题").strip()
    if len(topic) > 28:
        topic = topic[:28].rstrip("，。！？,.!?:：；; ")
    generic_lines = [
        f"今天用一分钟带你快速了解{topic}。",
        "先别急着上脸，先弄清楚它真正能帮你解决什么问题。",
        "很多人一开始用错频率，效果没看到，刺激却先来了。",
        "正确做法是低频起步，先建立耐受，再慢慢增加使用次数。",
        "如果你是敏感肌，一定要把保湿和修护放在同样重要的位置。",
        "使用这类成分时，白天防晒要跟上，不然前面的努力容易打折。",
        "和酸类、去角质一起叠太猛，反而更容易翻车。",
        "记住核心原则：循序渐进，观察皮肤反馈，长期坚持才更稳。",
    ]
    if _is_ad_prompt(user_prompt):
        sparse_lines = [""] * total_shots
        ad_lines = [
            f"{topic}，这一支先帮你抓住最值得记住的核心卖点。",
            "想少走弯路，就先从最关键的一步开始。",
            "现在就把正确方法记下来，后面执行会轻松很多。",
        ]
        sparse_positions = [0, max(0, total_shots // 2), max(0, total_shots - 1)]
        for idx, line in zip(sparse_positions, ad_lines):
            if idx < total_shots:
                sparse_lines[idx] = line
        return sparse_lines

    if not _is_explainer_prompt(user_prompt):
        return [""] * total_shots

    explainer_lines = [""] * total_shots
    for i in range(total_shots):
        # 讲解类也不强制每个镜头说话，留出产品特写/转场镜头的无台词空间。
        if i in {1, 4} and total_shots >= 5:
            continue
        explainer_lines[i] = generic_lines[min(i, len(generic_lines) - 1)]
    return explainer_lines


def _fallback_narrative_content(user_prompt: str, total_shots: int = 3) -> dict:
    """规则兜底的最小叙事剧本结构（doc 21 §2.3 新流程：按 shot 划分）。"""
    fallback_dialogues = _build_fallback_dialogues(user_prompt, total_shots)
    fallback_durations = [8] * total_shots
    shots: list[dict] = []
    for i in range(total_shots):
        shots.append({
            "shot_index": i,
            "duration_sec": fallback_durations[i],
            "scene_description": "与视频风格匹配的默认场景",
            "characters_in_shot": [],
            "start_frame_description": f"第 {i + 1} 个 shot 的起始画面（兜底）",
            "middle_frame_description": f"第 {i + 1} 个 shot 的中间画面（兜底）",
            "end_frame_description": f"第 {i + 1} 个 shot 的结束画面（兜底）",
            "action_description": "镜头平稳推进，主体保持静态",
            "dialogue": fallback_dialogues[i] if i < len(fallback_dialogues) else "",
            "emotion": "neutral",
            "emotion_intensity": "medium",
        })
    return {
        "story_arc": (
            f"AI 生成视频默认剧本：{user_prompt[:80] if user_prompt else '通用 AI 视频'}。"
            f"共 {total_shots} 个 shot，每个 shot 对应起始 / 中间 / 结束三段关键画面。"
        ),
        "characters": [],
        "scenes": [],
        "shots": shots,
    }


def _safe_parse_json(text: str) -> dict:
    """从 LLM 输出安全提取 JSON（三层解析）。"""
    text = text.strip()

    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 提取 ```json...``` 块
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

    _logger.warning(
        f"NarrativeScriptAgent JSON 解析失败，使用兜底输出。LLM 原文：{text[:200]!r}",
        event_type="narrative_json_parse_failed",
    )
    return _make_fallback_output()


def _try_parse_json_strict(text: str) -> dict | None:
    """严格解析 JSON；失败时返回 None，不触发 fallback。"""
    text = (text or "").strip()
    if not text:
        return None

    candidates = [text]

    block_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if block_match:
        candidates.append(block_match.group(1).strip())

    obj_match = re.search(r"\{.*\}", text, re.DOTALL)
    if obj_match:
        candidates.append(obj_match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


# _make_fallback_output 已合并到 _fallback_narrative_content，此处保留别名以兼容旧调用
def _make_fallback_output() -> dict:
    return _fallback_narrative_content("")


# 注：_build_brief_summary / _build_style_summary / _build_audio_summary_text
# 是 Batch A 旧版留下的文本摘要函数，Batch B 中 Agent 通过 read_artifact_tool
# 直接读取完整 artifact 内容，这三个函数已不再被调用。


# ---------------------------------------------------------------------------
# NarrativeScriptAgent
# ---------------------------------------------------------------------------

class NarrativeScriptAgent:
    """叙事剧本 Sub-Agent：create_react_agent + 工具调用生成叙事剧本（Batch B）。

    不直接写数据库，产物通过 write_artifact_tool 写出，以 ArtifactRef 形式返回。
    """

    def __init__(self) -> None:
        self._renderer = PromptRenderer()  # 内部已使用 get_registry() 全局单例

    async def run(self, task_spec: dict) -> dict:
        """生成叙事剧本，返回 narrative_script ArtifactRef。

        Args:
            task_spec: {
                project_id         (str)
                user_prompt        (str)
                brief_ref          (dict)
                style_ref          (dict, 可选)
                audio_ref          (dict, 可选)
                version_no         (int, default=1)
            }

        Returns:
            ArtifactRef dict（artifact_id / artifact_type / local_path / summary）。
        """
        cfg = get_config().llm
        project_id: str = task_spec.get("project_id", "")
        user_prompt: str = task_spec.get("user_prompt", "")
        version_no: int = int(task_spec.get("version_no", 1))

        if not cfg.api_key:
            _logger.warning(
                "LLM API key 未配置，NarrativeScriptAgent 使用规则兜底",
                event_type="narrative_agent_no_api_key",
            )
            return await self._fallback(project_id, user_prompt, version_no)

        try:
            system_content = self._renderer.render("narrative_script_system", variables={})
        except Exception as exc:
            _logger.warning(f"Prompt 加载失败: {exc!r}", event_type="narrative_agent_prompt_failed")
            return await self._fallback(project_id, user_prompt, version_no)

        brief_ref = task_spec.get("brief_ref") or {}
        style_ref = task_spec.get("style_ref") or {}
        audio_ref = task_spec.get("audio_ref") or {}
        reference_image_count: int = int(task_spec.get("reference_image_count") or 0)
        target_duration_sec: int = int(task_spec.get("target_duration_sec") or 60)
        allowed_shot_durations_sec = task_spec.get("allowed_shot_durations_sec") or [4, 5, 6, 8, 10, 12, 15]

        # 参考图提示词：告知 Agent 用户上传了几张图，影响角色生成逻辑
        if reference_image_count > 0:
            ref_hint = (
                f"【参考图提示】用户已上传 {reference_image_count} 张角色参考图，"
                f"请在 characters 中安排对应数量的人物角色（至少 {reference_image_count} 个）。"
                f"如果是单人主角场景，安排 1 个主角；"
                f"如果是团体场景（女团等），安排 {reference_image_count} 个平等地位的成员角色。"
                "图片将在视觉圣经阶段按顺序自动对应到角色。"
            )
        else:
            ref_hint = "用户未上传角色参考图，角色将在视觉圣经阶段完全重新生成。"

        task_msg = (
            f"项目 ID：{project_id}\n用户描述：{user_prompt or '（未提供）'}\n"
            f"{ref_hint}\n\n"
            f"创意简报引用：{json.dumps(brief_ref, ensure_ascii=False)}\n"
            f"风格圣经引用：{json.dumps(style_ref, ensure_ascii=False)}\n"
            f"音乐分析引用：{json.dumps(audio_ref, ensure_ascii=False)}\n\n"
            f"目标总时长：{target_duration_sec} 秒\n"
            f"允许的单 shot 时长档位：{', '.join(str(item) for item in allowed_shot_durations_sec)}\n\n"
            f"请先使用 read_artifact_tool 读取创意简报和风格圣经，尤其要读取 "
            f"creative_brief.extension.total_shots_generated、target_duration_sec、allowed_shot_durations_sec、character_list、aspect_ratio。"
            f"然后生成叙事剧本 JSON，根对象必须包含 story_arc / shots / characters / scenes。"
            f"其中 shots 必须是逐镜头数组，数量必须等于 total_shots_generated；"
            f"每个 shot 的 duration_sec 必须从允许档位中选择，且全部 shot 的时长总和要尽量贴近 target_duration_sec；"
            f"characters 必须来自 brief.extension.character_list，不能丢失已有角色；"
            f"scenes 必须从 shot 的场景中抽成结构化数组，不能为空；"
            f"根对象还必须包含 audio_strategy；每个 shot 还必须包含 audio_strategy。"
            f"每个 shot 必须包含 shot_index / duration_sec / scene_description / "
            f"characters_in_shot / start_frame_description / middle_frame_description / end_frame_description / "
            f"action_description / dialogue / audio_strategy / emotion / emotion_intensity。"
            f"请先判断这是讲解类、广告类、剧情类还是纯视觉表达，再决定哪些 shot 的 dialogue 非空。"
            f"dialogue 字段必须存在，但不是每个 shot 都必须有实际台词内容。"
            f"如果是讲解/旁白类视频，台词应作为整段连续文案拆分到若干关键 shot；"
            f"如果是广告或氛围表达，可只在开头/结尾/CTA shot 放少量台词，其余 shot 留空。"
            f"shot_index 从 0 连续递增。"
            f"然后调用 write_artifact_tool（artifact_type='narrative_script', "
            f"project_id='{project_id}', version_no={version_no}, summary='叙事剧本 v{version_no}'）写出。"
        )

        try:
            extra_body = {"enable_thinking": False} if not getattr(cfg, "enable_thinking", False) else None
            llm = ChatOpenAI(
                model=cfg.model,
                api_key=cfg.api_key,
                base_url=getattr(cfg, "base_url", None) or None,
                temperature=getattr(cfg, "temperature", 0.7),
                max_tokens=getattr(cfg, "max_tokens", 4096),
                timeout=getattr(cfg, "timeout", 120),
                extra_body=extra_body,
            )
            tools = [t for t in [read_artifact_tool, write_artifact_tool] if t is not None]
            agent = create_react_agent(model=llm, tools=tools)
            result = await agent.ainvoke(
                {"messages": [SystemMessage(content=system_content), HumanMessage(content=task_msg)]},
                config={"recursion_limit": 15},
            )
        except Exception as exc:
            _logger.error(
                f"NarrativeScriptAgent 调用失败: {exc!r}，使用规则兜底",
                event_type="narrative_agent_invoke_failed",
            )
            return await self._fallback(project_id, user_prompt, version_no)

        ref = _extract_last_write_result(result)
        if ref:
            _logger.info(
                f"NarrativeScriptAgent 完成: artifact_id={ref.get('artifact_id')!r}",
                event_type="narrative_agent_done",
            )
            return ref

        # 某些模型不会严格触发工具调用，而是直接把 JSON 正文输出在最后一条 AIMessage 中。
        # 旧逻辑会直接丢弃这份正文并走 fallback，导致 dialogue 等字段全部退化为空模板。
        inline_json = _extract_last_ai_json(result)
        if inline_json:
            try:
                ref = await write_artifact(
                    content=inline_json,
                    project_id=project_id,
                    artifact_type="narrative_script",
                    version_no=version_no,
                    summary=f"叙事剧本 v{version_no}",
                )
                _logger.info(
                    f"NarrativeScriptAgent 从非 tool-call 正文中恢复产物: artifact_id={ref.get('artifact_id')!r}",
                    event_type="narrative_agent_salvaged_inline_json",
                )
                return ref
            except Exception as exc:
                _logger.warning(
                    f"NarrativeScriptAgent 正文恢复写入失败: {exc!r}",
                    event_type="narrative_agent_salvage_failed",
                )

        _logger.warning("NarrativeScriptAgent 未调用 write_artifact_tool", event_type="narrative_agent_no_tool_call")
        return await self._fallback(project_id, user_prompt, version_no)

    async def _fallback(self, project_id: str, user_prompt: str, version_no: int) -> dict:
        """规则兜底：写出最小叙事剧本 ArtifactRef。"""
        content = _fallback_narrative_content(user_prompt)
        try:
            ref = await write_artifact(
                content=content, project_id=project_id,
                artifact_type="narrative_script", version_no=version_no,
                summary=f"规则兜底叙事剧本 v{version_no}",
            )
            _logger.info(
                f"NarrativeScriptAgent 兜底完成: {ref.get('artifact_id')!r}",
                event_type="narrative_agent_fallback_done",
            )
            return ref
        except Exception as exc:
            _logger.error(f"兜底写入失败: {exc!r}", event_type="narrative_agent_fallback_failed")
            from pathlib import Path
            return make_artifact_ref(
                artifact_type="narrative_script",
                local_path=Path(f"data/projects/{project_id}/03_brief/narrative_fallback.json"),
                version_no=version_no,
                summary="兜底叙事剧本（写入失败）",
            )

