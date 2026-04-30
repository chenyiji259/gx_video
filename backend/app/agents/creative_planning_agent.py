"""创意规划 Agent（Creative Planning Agent）。

来源文档：doc 06 §4.3（创意规划 Agent 职责）/ doc 09 任务 9-02/9-03

职责：
  phase-1: 生成 creative_brief + style_bible
    - 输入：音乐摘要、用户风格方向、用户描述、参考素材摘要、目标时长/比例
    - 输出：结构化 dict（含 creative_brief 和 style_bible 子对象）
  phase-2: 生成 scene_plan + shot_list (ShotSemanticSpec)
    - 输入：brief、style、音乐结构摘要、目标时长、最大镜头数、表演比例
    - 输出：结构化 dict（含 scene_plan 和 shot_plan 列表）

设计约束（doc 06 §2.2）：
  - Agent 只负责"读取 + 生成"，不写数据库
  - 生成的产物由对应的 PersistenceService 负责落库和写本地快照
  - 生成失败时返回降级输出，不抛出异常
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from app.core.config import get_config
from app.core.logging import get_agent_logger
from app.core.prompt_renderer import PromptRenderer
from app.core.provider_registry import get_provider_registry
from app.tools.shared.artifact_tools import (
    read_artifact_tool,
    write_artifact,
    write_artifact_tool,
)

_logger = get_agent_logger("creative_planning_agent")


# ---------------------------------------------------------------------------
# 解析工具（与 director_agent 一致）
# ---------------------------------------------------------------------------

def _safe_parse_json(text: str) -> dict | list:
    """安全提取 LLM 输出中的 JSON（处理 markdown 代码块、前后缀等）。"""
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
    # 4. 兜底
    _logger.warning(
        f"CreativePlanningAgent JSON 解析失败。LLM 原文：{text[:200]!r}",
        event_type="creative_planning_json_parse_failed",
    )
    return {}


def _extract_all_write_results(agent_result: dict) -> list[dict]:
    """从 create_react_agent 输出中提取所有 write_artifact_tool 的成功结果。"""
    results: list[dict] = []
    messages = agent_result.get("messages", [])
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        try:
            data = json.loads(msg.content)
            if isinstance(data, dict) and "artifact_id" in data and data["artifact_id"]:
                results.append(data)
        except (json.JSONDecodeError, TypeError):
            pass
    return results


# ---------------------------------------------------------------------------
# Creative Planning Agent
# ---------------------------------------------------------------------------

class CreativePlanningAgent:
    """创意规划 Agent：phase-1 生成 brief/style，phase-2 生成 shot plan。

    无副作用：不写数据库，不修改图状态，只返回结构化输出 dict。
    调用方（BriefPersistenceService / ShotPlanPersistenceService）负责落库。
    """

    def __init__(self) -> None:
        self._renderer = PromptRenderer()

    # ------------------------------------------------------------------
    # Batch B: create_react_agent 新接口
    # ------------------------------------------------------------------

    async def run(self, task_spec: dict) -> dict:
        """Batch B 统一入口：根据 task_type 转发给 phase1 或 phase2。"""
        task_type = task_spec.get("task_type", "")
        if task_type == "generate_brief":
            return await self.run_phase1(task_spec)
        elif task_type == "generate_shot_plan":
            return await self.run_phase2(task_spec)
        else:
            _logger.warning(f"CreativePlanningAgent: 未知任务类型 {task_type!r}")
            return {"error": f"未知任务类型 {task_type!r}"}

    async def run_phase1(self, task_spec: dict) -> dict:
        """Phase-1 Batch B：生成 creative_brief + style_bible，写出 ArtifactRef。

        task_spec: {
            project_id         (str)
            audio_ref          (dict)
            style_direction    (str)
            user_prompt        (str)
            target_duration_sec (float)
            aspect_ratio       (str)
            version_no         (int, default=1)
        }
        Returns: {brief_ref: ArtifactRef, style_ref: ArtifactRef}
        """
        cfg = get_config().llm
        project_id: str = task_spec.get("project_id", "")
        version_no: int = int(task_spec.get("version_no", 1))

        if not cfg.api_key:
            _logger.warning(
                "LLM API key 未配置，CreativePlanningAgent phase-1 使用规则兜底",
                event_type="creative_planning_no_api_key_p1",
            )
            return await self._fallback_phase1_refs(task_spec)

        try:
            system_content = self._renderer.render("creative_planning_system", variables={})
        except Exception as exc:
            _logger.warning(f"Prompt 加载失败: {exc!r}", event_type="creative_planning_prompt_failed_p1")
            return await self._fallback_phase1_refs(task_spec)

        audio_ref = task_spec.get("audio_ref") or {}
        # 新流程：audio_ref 为 None（无音乐分析），变量保留供兼容旧调用路径
        style_dir = task_spec.get("style_direction", "待确定")
        user_prompt = task_spec.get("user_prompt", "")
        # 16-02：移除 30.0 居性默认値；调用方（BriefPersistenceService）已在 16-01 保证传入正确实际时长
        duration = float(task_spec.get("target_duration_sec") or 0.0)
        if duration <= 0:
            _logger.warning(
                "run_phase1 未收到有效 target_duration_sec，请检查调用方",
                event_type="creative_planning_no_duration_p1",
            )
        aspect = task_spec.get("aspect_ratio", "16:9")

        # 新流程：从 spec output_config 读取额外参数
        platform = task_spec.get("platform", "")
        target_audience = task_spec.get("target_audience", "")
        style_pref = task_spec.get("style_preference", "") or style_dir
        human_on_camera = task_spec.get("human_on_camera", None)
        allowed_shot_durations_sec = task_spec.get("allowed_shot_durations_sec") or []
        if not allowed_shot_durations_sec:
            allowed_shot_durations_sec = get_provider_registry().list_supported_durations("video", enabled_only=True) or [4, 5, 6, 8, 10, 12, 15]
        human_on_camera_text = "未指定"
        if human_on_camera is True:
            human_on_camera_text = "是，需要真人入镜"
        elif human_on_camera is False:
            human_on_camera_text = "否，不要真人入镜"

        task_msg = (
            f"项目 ID：{project_id}\n"
            f"用户视频需求：{user_prompt or '（未提供）'}\n"
            f"目标时长：{duration}秒，画幅：{aspect}\n"
            f"发布平台：{platform or '未指定'}\n"
            f"目标受众：{target_audience or '未指定'}\n"
            f"视觉风格偏好：{style_pref or '未指定'}\n"
            f"当前视频模型支持的单 shot 时长档位（秒）：{', '.join(str(item) for item in allowed_shot_durations_sec)}\n"
            f"真人入镜要求：{human_on_camera_text}\n\n"
            # 旧流程（音乐MV模式）：音乐分析引用已停用
            # f"音乐分析引用：{json.dumps(audio_ref, ensure_ascii=False)}\n\n"
            # f"请先使用 read_artifact_tool 读取音乐分析引用，再生成..."
            f"请根据以上视频需求，生成 creative_brief 和 style_bible"
            f"（style_bible.palette 必须是 JSON 对象），"
            f"然后依次调用 write_artifact_tool 写出：\n"
            f"1. artifact_type='creative_brief', project_id='{project_id}', version_no={version_no}\n"
            f"2. artifact_type='style_bible', project_id='{project_id}', version_no={version_no}"
        )

        try:
            extra_body = {"enable_thinking": False} if not getattr(cfg, "enable_thinking", False) else None
            llm = ChatOpenAI(
                model=cfg.model, api_key=cfg.api_key,
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
                f"CreativePlanningAgent phase-1 调用失败: {exc!r}",
                event_type="creative_planning_p1_failed",
            )
            return await self._fallback_phase1_refs(task_spec)

        write_results = _extract_all_write_results(result)
        brief_ref = next((r for r in write_results if r.get("artifact_type") == "creative_brief"), None)
        style_ref = next((r for r in write_results if r.get("artifact_type") == "style_bible"), None)

        if not brief_ref or not style_ref:
            _logger.warning(
                "CreativePlanningAgent phase-1 未完整写出 brief+style",
                event_type="creative_planning_p1_incomplete",
            )
            return await self._fallback_phase1_refs(task_spec)

        _logger.info(
            f"CreativePlanningAgent phase-1 完成: brief={brief_ref.get('artifact_id')!r}",
            event_type="creative_planning_phase1_done",
        )
        return {"brief_ref": brief_ref, "style_ref": style_ref}

    async def run_phase2(self, task_spec: dict) -> dict:
        """Phase-2 Batch B：生成 shot_plan，写出 ArtifactRef。

        task_spec: {
            project_id          (str)
            brief_ref           (dict)
            style_ref           (dict)
            audio_ref           (dict)
            narrative_script_ref (dict)          # 新增：NarrativeScriptVersion 的 ArtifactRef
            target_duration_sec (float)
            max_shots           (int, default=16)
            performance_ratio   (float, default=0.4)
            version_no          (int, default=1)
        }
        Returns: {shot_plan_ref: ArtifactRef}
        """
        cfg = get_config().llm
        project_id: str = task_spec.get("project_id", "")
        version_no: int = int(task_spec.get("version_no", 1))

        if not cfg.api_key:
            _logger.warning(
                "LLM API key 未配置，CreativePlanningAgent phase-2 使用规则兜底",
                event_type="creative_planning_no_api_key_p2",
            )
            return await self._fallback_phase2_ref(project_id, version_no)

        try:
            system_content = self._renderer.render("creative_planning_system", variables={})
        except Exception as exc:
            _logger.warning(f"Prompt 加载失败: {exc!r}", event_type="creative_planning_prompt_failed_p2")
            return await self._fallback_phase2_ref(project_id, version_no)

        brief_ref = task_spec.get("brief_ref") or {}
        style_ref = task_spec.get("style_ref") or {}
        audio_ref = task_spec.get("audio_ref") or {}
        narrative_script_ref = task_spec.get("narrative_script_ref") or {}
        # 16-02：移除 30.0 居性默认値；调用方（ShotPlanPersistenceService）已在 16-01 保证传入正确实际时长
        duration = float(task_spec.get("target_duration_sec") or 0.0)
        if duration <= 0:
            _logger.warning(
                "run_phase2 未收到有效 target_duration_sec，请检查调用方",
                event_type="creative_planning_no_duration_p2",
            )
        max_shots = int(task_spec.get("max_shots", 16))
        perf_ratio = float(task_spec.get("performance_ratio", 0.4))
        allowed_shot_durations_sec = task_spec.get("allowed_shot_durations_sec") or (
            get_provider_registry().list_supported_durations("video", enabled_only=True) or [4, 5, 6, 8, 10, 12, 15]
        )

        task_msg = (
            f"项目 ID：{project_id}\n目标时长：{duration}秒，最大镜头数：{max_shots}，演示镜头比例：{perf_ratio}\n\n"
            f"创意简报引用：{json.dumps(brief_ref, ensure_ascii=False)}\n\n"
            f"风格圣经引用：{json.dumps(style_ref, ensure_ascii=False)}\n\n"
            # 旧流程（音乐MV模式）：音乐结构引用已停用
            # f"音乐结构引用：{json.dumps(audio_ref, ensure_ascii=False)}\n\n"
            f"叙事剧本引用：{json.dumps(narrative_script_ref, ensure_ascii=False)}\n\n"
            f"允许的单 shot 时长档位（秒）：{', '.join(str(item) for item in allowed_shot_durations_sec)}\n\n"
            f"请先使用 read_artifact_tool 读取叙事剧本引用，获取详细的角色定义和场景定义，"
            f"再生成完整 shot plan，包含 scene_plan 和 shot_plan 列表。"
            f"每个 shot 必须包含以下所有字段："
            f"shot_index / scene_id / scene_type / shot_role / subject / location / "
            f"emotion / emotion_intensity / camera_language / pace / visual_energy / "
            f"duration_sec / start_ms / end_ms。"
            f"然后调用 write_artifact_tool：\n"
            f"- duration_sec 必须从允许档位中选择，并尽量让总时长贴近 target_duration_sec\n"
            f"- start_ms/end_ms 基于 target_duration_sec={duration}s 按内容节奏均匀分配，"
            f"所有 shot 总时长之和必须等于 {int(duration * 1000)} ms\n"
            f"- end_ms = start_ms + duration_sec * 1000（严格对齐，不得重叠）\n"
            f"- emotion_intensity 根据 shot 在整体视频叙事中的情绪位置推断，仅可取 low/medium/high/very_high\n"
            f"- subject 应引用叙事剧本中定义的 character_concepts，location 应引用叙事剧本中定义的 scene_concepts\n"
            f"artifact_type='shot_plan', project_id='{project_id}', version_no={version_no}"
        )

        # 16-02：动态计算 max_tokens，避免 40+ shots JSON 截断
        _max_tokens_shot = max(
            int(getattr(cfg, "max_tokens_shot_plan", 8192)),
            max_shots * 250,
        )
        try:
            extra_body = {"enable_thinking": False} if not getattr(cfg, "enable_thinking", False) else None
            llm = ChatOpenAI(
                model=cfg.model, api_key=cfg.api_key,
                base_url=getattr(cfg, "base_url", None) or None,
                temperature=getattr(cfg, "temperature", 0.7),
                max_tokens=_max_tokens_shot,
                timeout=max(getattr(cfg, "timeout", 120), 600),  # Shot plan can take up to 10 minutes
                extra_body=extra_body,
            )
            tools = [t for t in [read_artifact_tool, write_artifact_tool] if t is not None]
            agent = create_react_agent(model=llm, tools=tools)
            result = await agent.ainvoke(
                {"messages": [SystemMessage(content=system_content), HumanMessage(content=task_msg)]},
                config={"recursion_limit": 25},  # 16-02: 15 →25，长歌曲工具调用轮次更多
            )
        except Exception as exc:
            _logger.error(
                f"CreativePlanningAgent phase-2 调用失败: {exc!r}",
                event_type="creative_planning_p2_failed",
            )
            return await self._fallback_phase2_ref(project_id, version_no)

        write_results = _extract_all_write_results(result)
        shot_plan_ref = next(
            (r for r in write_results if r.get("artifact_type") in ("shot_plan", "scene_plan")),
            None,
        )

        if not shot_plan_ref:
            _logger.warning(
                "CreativePlanningAgent phase-2 未调用 write_artifact_tool",
                event_type="creative_planning_p2_no_tool",
            )
            return await self._fallback_phase2_ref(project_id, version_no)

        _logger.info(
            f"CreativePlanningAgent phase-2 完成: {shot_plan_ref.get('artifact_id')!r}",
            event_type="creative_planning_phase2_done",
        )
        return {"shot_plan_ref": shot_plan_ref}

    async def _fallback_phase1_refs(self, task_spec: dict) -> dict:
        """Phase-1 规则兜底：写出最小 brief+style ArtifactRef。"""
        project_id = task_spec.get("project_id", "unknown")
        version_no = int(task_spec.get("version_no", 1))
        style_dir = task_spec.get("style_direction", "待确定")
        user_prompt = task_spec.get("user_prompt", "")
        fb = self._fallback_brief(style_dir, user_prompt)
        brief_ref = await write_artifact(
            content=fb["creative_brief"], project_id=project_id,
            artifact_type="creative_brief", version_no=version_no,
            summary=f"兜底 brief v{version_no}",
        )
        style_ref = await write_artifact(
            content=fb["style_bible"], project_id=project_id,
            artifact_type="style_bible", version_no=version_no,
            summary=f"兜底 style v{version_no}",
        )
        return {"brief_ref": brief_ref, "style_ref": style_ref}

    async def _fallback_phase2_ref(self, project_id: str, version_no: int) -> dict:
        """Phase-2 规则兜底：写出空 shot plan ArtifactRef。"""
        ref = await write_artifact(
            content={"scene_plan": [], "shot_plan": []},
            project_id=project_id, artifact_type="shot_plan", version_no=version_no,
            summary=f"兜底 shot plan v{version_no}",
        )
        return {"shot_plan_ref": ref}

    @staticmethod
    def _fallback_brief(style_direction: str, user_prompt: str) -> dict[str, Any]:
        """LLM 不可用时的降级 brief 结构（doc 21 §1.1 含 extension 子字段）。"""
        # 当前默认值：短视频场景收敛为 1 张九宫格 / 3 个 shot
        fallback_extension = {
            "target_duration_sec": 30,
            "shot_duration_sec": 10,
            "shot_count": 3,
            "grid_count": 1,
            "total_shots_generated": 3,
            "allowed_shot_durations_sec": [4, 5, 6, 8, 10, 12, 15],
            "character_list": [],
            "target_platform": None,
            "target_audience": None,
            "visual_style": None,
            "human_on_camera": False,
            "aspect_ratio": "9:16",
        }
        return {
            "creative_brief": {
                "title": "待生成",
                "summary": user_prompt or "未提供创意描述",
                "narrative_mode": "mixed",
                "performance_ratio": 0.4,
                "mood_tags": [],
                "style_direction": style_direction or "待确定",
                # doc 21 §1.1：extension 嵌在 creative_brief 里，会进入 raw_payload
                "extension": fallback_extension,
            },
            "style_bible": {
                "palette": {"description": "待确定"},
                "lighting_style": "待确定",
                "camera_style": "待确定",
                "film_texture": None,
                "reference_notes": None,
            },
            "raw_llm_output": "[LLM 不可用，使用降级输出]",
        }

