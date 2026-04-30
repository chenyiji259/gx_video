"""视觉开发 Agent（VisualDevelopmentAgent）。

⚠️  DEPRECATED（doc 21 决策 D1）：本 Agent 用于"视觉圣经"阶段（角色/场景参考图生成），
    已被九宫格架构（doc 21）取代。新流程依赖 LLM 在九宫格 prompt 中描述角色保持一致性
    （决策 C1），不再预生成定妆图/场景图。

    保留代码不删除，作为未来"角色定妆图自动生成"扩展点的基础（决策 C2 降级路径）。
    不要在新流程中调用本 Agent。

来源文档：
  - doc11 §5.5（原职责，已 deprecated）
  - doc 21 §2.4（决策 D1 deprecated 说明）

职责（已停用）：
  - 输入：角色或场景的文字描述 + 风格圣经摘要 + 生成模式
  - 输出：结构化图片生成规格 dict（positive_prompt / negative_prompt / generation_mode / strength / aspect_ratio）

调用方：VisualBibleService.generate_character_reference() / generate_scene_reference()
无副作用：不写数据库，只返回结构化 dict。
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from app.core.config import get_config
from app.core.logging import get_agent_logger
from app.core.prompt_renderer import PromptRenderer
from app.tools.shared.artifact_tools import read_artifact_tool
from app.tools.shared.generation_tools import generate_reference_image_tool

_logger = get_agent_logger("visual_development_agent")

SubjectType = Literal["character", "scene", "prop"]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _safe_parse_json(text: str) -> dict:
    """从 LLM 输出安全提取 JSON，解析失败时返回 Agent 兜底规格。"""
    from app.utils.json_utils import safe_parse_json  # DESIGN-05
    result = safe_parse_json(text)
    if not result or result == {}:
        _logger.warning(
            f"VisualDevelopmentAgent JSON 解析失败，使用兜底输出。LLM 原文：{text[:200]!r}",
            event_type="visual_agent_json_parse_failed",
        )
        return _make_fallback_spec(generation_mode="text_to_image", subject_type="character")
    return result


def _make_fallback_spec(
    generation_mode: str,
    subject_type: SubjectType,
) -> dict:
    """LLM 不可用或解析失败时的规则底底规格。"""
    if subject_type == "scene":
        return {
            "positive_prompt": (
                "电影感场景，氛围感强，胶片质感，"
                "专业摄影表现，高质量"
            ),
            "negative_prompt": (
                "人物，水印，文字，模糊，低质量"
            ),
            "generation_mode": generation_mode,
            "aspect_ratio": "16:9",
        }
    # character / prop 默认
    return {
        "positive_prompt": (
            "人物半身像，面部特写，电影感光线，"
            "胶片质感，专业摄影表现，高质量"
        ),
        "negative_prompt": (
            "多余人物，水印，文字，模糊，低质量，面部变形"
        ),
        "generation_mode": generation_mode,
        "aspect_ratio": "1:1",
    }


def _build_style_text(style: Any) -> str:
    """将 StyleBibleVersion ORM 对象提取为摘要文本。"""
    if style is None:
        return "暂无风格圣经，使用电影感通用风格。"
    parts: list[str] = []
    if getattr(style, "lighting_style", None):
        parts.append(f"光影：{style.lighting_style}")
    if getattr(style, "camera_style", None):
        parts.append(f"镜头：{style.camera_style}")
    if getattr(style, "film_texture", None):
        parts.append(f"质感：{style.film_texture}")
    palette = getattr(style, "palette", None) or {}
    if palette:
        parts.append(f"色调：{json.dumps(palette, ensure_ascii=False)}")
    return "；".join(parts) if parts else "风格圣经内容为空。"


# ---------------------------------------------------------------------------
# VisualDevelopmentAgent
# ---------------------------------------------------------------------------

class VisualDevelopmentAgent:
    """视觉开发 Sub-Agent：create_react_agent + generate_reference_image_tool（Batch B）。

    Batch B 新增 run() 方法：Agent 自行生成提示词并调用 generate_reference_image_tool 生成图片。
    原 generate_spec() 方法保留供降级路径使用。
    """

    def __init__(self) -> None:
        self._renderer = PromptRenderer()  # 内部已使用 get_registry() 全局单例

    # ------------------------------------------------------------------
    # Batch B: create_react_agent 新接口
    # ------------------------------------------------------------------

    async def run(self, task_spec: dict) -> dict:
        """Batch B 新接口：生成参考图并返回 asset_id。

        Agent 内部自行生成提示词规格，然后调用 generate_reference_image_tool 生成图片。

        task_spec: {
            project_id       (str)
            subject_type     (str)  — character / scene / prop
            subject_id       (str)
            subject_name     (str)
            subject_description (str)
            generation_mode  (str)  — text_to_image / image_to_image
            source_image_url (str, 可选)
            style_ref        (dict, 可选)
            version_no       (int, default=1)
        }
        Returns: {asset_id: str, provider: str|None, ...}。
        """
        cfg = get_config().llm
        project_id: str = task_spec.get("project_id", "")
        subject_type: str = task_spec.get("subject_type", "character")
        subject_id: str = task_spec.get("subject_id", "")
        subject_name: str = task_spec.get("subject_name", "")
        description: str = task_spec.get("subject_description", "")
        gen_mode: str = task_spec.get("generation_mode", "text_to_image")
        source_url: str = task_spec.get("source_image_url", "") or ""
        style_ref = task_spec.get("style_ref") or {}
        version_no: int = int(task_spec.get("version_no", 1))
        asset_type = f"{subject_type}_reference"

        if not cfg.api_key:
            _logger.warning(
                "LLM API key 未配置，VisualDevelopmentAgent 使用规则兜底",
                event_type="visual_agent_no_api_key_run",
            )
            return await self._fallback_run(task_spec)

        try:
            system_content = self._renderer.render("visual_development_system", variables={})
        except Exception as exc:
            _logger.warning(f"Prompt 加载失败: {exc!r}", event_type="visual_agent_prompt_failed")
            return await self._fallback_run(task_spec)

        provider_name: str = task_spec.get("provider_name", "") or ""
        task_msg = (
            f"项目 ID：{project_id}\n主体类型：{subject_type}\n"
            f"主体 ID：{subject_id}\n主体名称：{subject_name}\n"
            f"描述：{description}\n风格圣经引用：{json.dumps(style_ref, ensure_ascii=False)}\n"
            f"生成模式：{gen_mode}\n"
            + (f"源图 URL：{source_url}\n" if source_url else "")
            + (f"provider_name='{provider_name}'\n" if provider_name else "")
            + f"\n请根据上述信息生成提示词规格，"
            f"然后调用 generate_reference_image_tool：\n"
            f"  project_id='{project_id}'\n"
            f"  asset_type='{asset_type}'\n"
            f"  generation_mode='{gen_mode}'\n"
            f"  source_image_url='{source_url}'\n"
            f"  subject_id='{subject_id}'\n"
            f"  subject_name='{subject_name}'\n"
            f"  version_no={version_no}"
            + (f"\n  provider_name='{provider_name}'" if provider_name else "")
        )

        try:
            extra_body = {"enable_thinking": False} if not getattr(cfg, "enable_thinking", False) else None
            llm = ChatOpenAI(
                model=cfg.model, api_key=cfg.api_key,
                base_url=getattr(cfg, "base_url", None) or None,
                temperature=getattr(cfg, "temperature", 0.7),
                max_tokens=getattr(cfg, "max_tokens", 2048),
                timeout=getattr(cfg, "timeout", 180),
                extra_body=extra_body,
            )
            tools = [t for t in [read_artifact_tool, generate_reference_image_tool] if t is not None]
            agent = create_react_agent(model=llm, tools=tools)
            result = await agent.ainvoke(
                {"messages": [SystemMessage(content=system_content), HumanMessage(content=task_msg)]},
                config={"recursion_limit": 10},
            )
        except Exception as exc:
            _logger.error(
                f"VisualDevelopmentAgent run() 调用失败: {exc!r}",
                event_type="visual_agent_run_failed",
            )
            return await self._fallback_run(task_spec)

        # 提取 generate_reference_image_tool 结果
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if not isinstance(msg, ToolMessage):
                continue
            import json as _json
            try:
                data = _json.loads(msg.content)
                if isinstance(data, dict) and data.get("asset_id"):
                    _logger.info(
                        f"VisualDevelopmentAgent run() 完成: asset_id={data['asset_id']!r}",
                        event_type="visual_agent_run_done",
                    )
                    return data
            except (ValueError, TypeError):
                pass

        _logger.warning("VisualDevelopmentAgent run() 未调用工具", event_type="visual_agent_run_no_tool")
        return await self._fallback_run(task_spec)

    async def _fallback_run(self, task_spec: dict) -> dict:
        """run() 的规则底底：直接生成默认提示词并调用图片生成工具。"""
        from app.tools.shared.generation_tools import generate_reference_image
        import json as _json

        project_id: str = task_spec.get("project_id", "")
        subject_type: str = task_spec.get("subject_type", "character")
        subject_id: str = task_spec.get("subject_id", "")
        subject_name: str = task_spec.get("subject_name", "")
        description: str = task_spec.get("subject_description", "")
        gen_mode: str = task_spec.get("generation_mode", "text_to_image")
        source_url: str = task_spec.get("source_image_url", "") or ""
        version_no: int = int(task_spec.get("version_no", 1))
        provider_name: str = task_spec.get("provider_name", "") or ""
        asset_type = f"{subject_type}_reference"
        fallback = _make_fallback_spec(gen_mode, subject_type)  # type: ignore[arg-type]
        return await generate_reference_image(
            project_id=project_id,
            asset_type=asset_type,
            positive_prompt=fallback.get("positive_prompt", description or "电影感，高质量"),
            negative_prompt=fallback.get("negative_prompt"),
            generation_mode=gen_mode,
            source_image_url=source_url or None,
            subject_id=subject_id or None,
            subject_name=subject_name or None,
            version_no=version_no,
            provider_name=provider_name or None,
        )

    # ------------------------------------------------------------------
    # CLASS-01 修复：Omni 多模态能力接口（从 VisualBibleService 迁入）
    # ------------------------------------------------------------------

    async def analyze_image(
        self,
        image_url: str,
        prompt_text: str,
    ) -> dict:
        """调用 Omni 分析参考图，返回图片类型判断结构。

        CLASS-01 修复：将原先在 VisualBibleService 中的内嵌 LLM 调用迁入 Agent 层。

        Returns:
            {
                "image_type": "realistic_photo" | "illustration" | "ai_generated" | "other",
                "usable_directly": bool,
                "reason": str,
                "recommended_mode": "direct" | "image_to_image" | "text_to_image",
                "face_quality": "high" | "medium" | "low" | "none",
                "requires_costume_generation": bool,
            }
        """
        from app.utils.omni_config import load_omni_config
        from app.utils.json_utils import safe_parse_json

        _fallback: dict = {
            "image_type": "unknown",
            "usable_directly": True,
            "reason": "Omni 分析失败，默认直接使用",
            "recommended_mode": "direct",
            "face_quality": "unknown",
            "requires_costume_generation": False,
        }
        try:
            omni_cfg = load_omni_config()
            cfg = get_config()
            # qwen3.5-omni-plus 强制要求 stream=True + modalities
            # streaming=True 让 LangChain 内部用流式，ainvoke() 仍返回完整 AIMessage
            extra_body_omni = {"enable_thinking": False}
            llm = ChatOpenAI(
                model=omni_cfg.get("model_name", "qwen2.5-omni-7b"),
                api_key=omni_cfg.get("api_key") or cfg.llm.api_key,
                base_url=omni_cfg.get("endpoint") or cfg.llm.base_url,
                temperature=0.3,
                timeout=omni_cfg.get("timeout", 60),
                streaming=True,
                extra_body=extra_body_omni,
                model_kwargs={
                    "modalities": ["text"],
                    "stream_options": {"include_usage": False},
                },
            )
            content = [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": prompt_text},
            ]
            # 加载外部模板作为系统提示词（omni_image_analysis.md）
            try:
                _sys_content = self._renderer.render("omni_image_analysis", {}, strict=False)
            except Exception:
                _sys_content = "你是一个专业的视觉分析专家，负责判断图片类型和可用性，输出纯 JSON。"
            messages = [
                SystemMessage(content=_sys_content),
                HumanMessage(content=content),
            ]
            response = await llm.ainvoke(messages)
            result = safe_parse_json(response.content, fallback=_fallback)
            _logger.info("参考图 Omni 分析完成", event_type="visual_agent_image_analysis_done")
            return result
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                f"Omni 图片分析失败: {exc!r}",
                event_type="visual_agent_image_analysis_failed",
            )
            return {**_fallback, "reason": f"分析失败，默认直接使用: {exc}"}

    async def derive_costumes(
        self,
        prompt_text: str,
    ) -> list[dict]:
        """调用 Omni 从 prompt 推导造型列表。

        CLASS-01 修复：将原先在 VisualBibleService._derive_costumes_from_narrative
        中的内嵌 LLM 调用迁入 Agent 层。

        Args:
            prompt_text: 已由 VisualBibleService 构建好的完整 prompt
                         （含角色描述、段落信息、风格方向）。

        Returns:
            造型列表，每项含 costume_id / label / applies_to_sections /
            generation_prompt / reference_asset_id / user_confirmed /
            generation_status（DESIGN-08 新增）。
            LLM 失败时返回 []。
        """
        from app.utils.omni_config import load_omni_config
        from app.utils.json_utils import safe_parse_json

        try:
            omni_cfg = load_omni_config()
            cfg = get_config()
            # qwen3.5-omni-plus 强制要求 stream=True + modalities
            extra_body_omni = {"enable_thinking": False}
            llm = ChatOpenAI(
                model=omni_cfg.get("model_name", "qwen2.5-omni-7b"),
                api_key=omni_cfg.get("api_key") or cfg.llm.api_key,
                base_url=omni_cfg.get("endpoint") or cfg.llm.base_url,
                temperature=0.5,
                timeout=60,
                streaming=True,
                extra_body=extra_body_omni,
                model_kwargs={
                    "modalities": ["text"],
                    "stream_options": {"include_usage": False},
                },
            )
            # 加载外部模板作为系统提示词（omni_costume_derivation.md）
            try:
                _sys_content = self._renderer.render("omni_costume_derivation", {}, strict=False)
            except Exception:
                _sys_content = "你是一个专业的 MV 造型设计师，负责为角色设计不同段落的造型，输出纯 JSON。"
            messages = [
                SystemMessage(content=_sys_content),
                HumanMessage(content=prompt_text),
            ]
            response = await llm.ainvoke(messages)
            raw = safe_parse_json(response.content, fallback=[])

            if isinstance(raw, list):
                costumes = raw
            elif isinstance(raw, dict) and "costumes" in raw:
                costumes = raw["costumes"]
            else:
                costumes = []

            # Bug9 修复逻辑：label 安全化，确保 costume_id 不含中文或空格
            for costume in costumes:
                raw_label = costume.get("label") or "default"
                safe_label = re.sub(r"[^\w]", "_", raw_label).strip("_") or "default"
                costume.setdefault("costume_id", f"costume_{safe_label}")
                costume.setdefault("reference_asset_id", None)
                costume.setdefault("user_confirmed", False)
                costume.setdefault("generation_status", "pending")  # DESIGN-08

            _logger.info(
                f"Omni 造型推导完成: {len(costumes)} 套造型",
                event_type="visual_agent_costume_derivation_done",
            )
            return costumes
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                f"Omni 造型推导失败: {exc!r}",
                event_type="visual_agent_costume_derivation_failed",
            )
            return []

    # ------------------------------------------------------------------
    # Batch A 旧接口（保留）
    # ------------------------------------------------------------------

    async def generate_spec(
        self,
        *,
        subject_type: SubjectType,
        subject_description: str,
        style: Any,
        generation_mode: str = "text_to_image",
        source_image_hint: Optional[str] = None,
    ) -> dict:
        """生成图片生成规格。

        Args:
            subject_type:        "character" / "scene" / "prop"。
            subject_description: 角色或场景的文字描述（来自 NarrativeScript）。
            style:               StyleBibleVersion ORM 对象（可为 None）。
            generation_mode:     "text_to_image" 或 "image_to_image"。
            source_image_hint:   用户原始图的简短视觉描述（img2img 时辅助保留特征）。

        Returns:
            包含 positive_prompt / negative_prompt / generation_mode /
            [strength] / aspect_ratio 的 dict。
        """
        cfg = get_config()
        llm_cfg = cfg.llm

        style_description = _build_style_text(style)

        # 构造任务 prompt（直接组合，无独立 task prompt 文件）
        task_content = (
            f"主体类型：{subject_type}\n"
            f"描述：{subject_description}\n"
            f"生成模式：{generation_mode}\n"
            f"风格圣经：{style_description}\n"
        )
        if source_image_hint and generation_mode == "image_to_image":
            task_content += f"原始参考图视觉特征（需保留）：{source_image_hint}\n"

        api_key = getattr(llm_cfg, "api_key", None)
        if not api_key:
            _logger.warning(
                "LLM API key 未配置，VisualDevelopmentAgent 使用规则兜底",
                event_type="visual_agent_no_api_key",
            )
            return _make_fallback_spec(generation_mode, subject_type)

        try:
            system_content = self._renderer.render("visual_development_system", variables={})
        except Exception as exc:
            _logger.warning(
                f"visual_development_system prompt 加载失败: {exc}，使用兜底",
                event_type="visual_agent_prompt_load_failed",
            )
            return _make_fallback_spec(generation_mode, subject_type)

        try:
            extra_body = {"enable_thinking": False} if not getattr(llm_cfg, "enable_thinking", False) else None
            llm = ChatOpenAI(
                model=llm_cfg.model,
                api_key=api_key,
                base_url=getattr(llm_cfg, "base_url", None) or None,
                temperature=getattr(llm_cfg, "temperature", 0.7),
                timeout=getattr(llm_cfg, "timeout", 120),
                extra_body=extra_body,
            )

            messages = [
                SystemMessage(content=system_content),
                HumanMessage(content=task_content),
            ]

            response = await llm.ainvoke(messages)
            raw_text = response.content if hasattr(response, "content") else str(response)

            result = _safe_parse_json(raw_text)

            # 补全必要字段（防止 LLM 漏输）
            result.setdefault("generation_mode", generation_mode)
            result.setdefault(
                "aspect_ratio", "1:1" if subject_type != "scene" else "16:9"
            )

            _logger.info(
                f"VisualDevelopmentAgent 生成完成: type={subject_type!r} "
                f"mode={generation_mode!r} prompt_len={len(result.get('positive_prompt', ''))}",
                event_type="visual_agent_done",
            )
            return result

        except Exception as exc:  # noqa: BLE001
            _logger.error(
                f"VisualDevelopmentAgent LLM 调用失败: {exc!r}，使用规则兜底",
                event_type="visual_agent_llm_failed",
            )
            return _make_fallback_spec(generation_mode, subject_type)
