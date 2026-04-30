"""一致性质检 Agent（Consistency Guardian Agent）。

⚠️  DEPRECATED（doc 21 决策 D1）：本 Agent 与"视觉圣经"阶段绑定，
    新流程（九宫格架构）下角色一致性由九宫格 prompt 自身保证（决策 C1），
    不再需要独立的一致性质检阶段。保留代码不删除，作为未来质量回检的扩展点。

来源文档：
  - doc 06 §4.4 / doc 09 任务 13-01（原职责，已 deprecated）
  - doc 21 §2.4（决策 D1 deprecated 说明）

职责（已停用）：
  检查项目 storyboard + shots 在角色、视觉风格、镜头节奏三个维度的一致性，
  输出结构化问题列表（issues）和修复建议（recommendations）。

设计约束（doc 06 §2.4）：
  - 只负责"发现问题 + 给建议"，不修改数据库，不调用生成工具
  - 生成失败时返回空 issues 列表（score=1.0），不阻断主链路
  - 模式完全对齐 audio_analysis_agent.py：外部 prompt → ChatOpenAI → safe_parse_json → rule fallback

输出格式（对应 prompts/system/consistency_guardian.md）：
  {
    "issues": [
      {"type": "character_drift|style_drift|pacing_mismatch",
       "target_id": "shot_005",
       "severity": "high|medium|low",
       "description": "..."}
    ],
    "recommendations": [
      {"action": "regenerate_shot|adjust_style|reorder_shots",
       "target_id": "shot_005",
       "reason": "..."}
    ],
    "overall_consistency_score": 0.85
  }
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_config
from app.core.logging import get_agent_logger
from app.core.prompt_renderer import PromptRenderer

_logger = get_agent_logger("consistency_guardian_agent")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _safe_parse_json(content: str) -> dict[str, Any]:
    """三层 JSON 解析：直接解析 → Markdown 代码块提取 → 正则提取。"""
    text = content.strip()

    # 层 1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 层 2: Markdown ```json 代码块
    md_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if md_match:
        try:
            return json.loads(md_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 层 3: 找 {…} 最外层
    brace_match = re.search(r"(\{[\s\S]*\})", text)
    if brace_match:
        try:
            return json.loads(brace_match.group(1))
        except json.JSONDecodeError:
            pass

    # 兜底
    return {"_raw_response": content, "_parse_failed": True}


def _empty_result() -> dict[str, Any]:
    """LLM 不可用时的安全兜底结果（无问题）。"""
    return {
        "issues": [],
        "recommendations": [],
        "overall_consistency_score": 1.0,
        "_generated_by": "rule_fallback",
    }


# ---------------------------------------------------------------------------
# ConsistencyGuardianAgent
# ---------------------------------------------------------------------------

class ConsistencyGuardianAgent:
    """一致性质检 Agent。

    无副作用：不写数据库，不修改图状态，只返回结构化质检报告。
    调用方（ConsistencyAPI）负责将结果返回给用户或触发后续修复流程。
    """

    def __init__(self) -> None:
        self._cfg = get_config().llm
        self._renderer = PromptRenderer()

    async def run(
        self,
        *,
        style_bible_summary: str,
        character_set_summary: str,
        shots_summary: str,
        shot_count: int,
    ) -> dict[str, Any]:
        """执行一致性质检。

        Args:
            style_bible_summary:     style_bible 的关键字段文本摘要。
            character_set_summary:   character_set 的关键字段文本摘要。
            shots_summary:           全部 shot 的简要描述（shot_id / emotion /
                                     camera_language / lipsync_required 等）。
            shot_count:              当前 shot 总数。

        Returns:
            {issues, recommendations, overall_consistency_score}
            任何异常均被捕获，返回空 issues 兜底结果，不向上抛出。
        """
        # ---- 渲染系统提示词 -----------------------------------------------
        try:
            system_text = self._renderer.render(
                "consistency_guardian_system",
                {
                    "style_bible_summary": style_bible_summary or "（无风格规格）",
                    "character_set_summary": character_set_summary or "（无角色设定）",
                    "shot_count": str(shot_count),
                },
            )
        except Exception as exc:
            _logger.warning(
                f"Prompt 渲染失败（system），使用内置提示词: {exc}",
                event_type="cg_prompt_render_failed",
            )
            system_text = self._fallback_system_prompt(
                style_bible_summary, character_set_summary
            )

        # ---- 渲染任务提示词 -----------------------------------------------
        try:
            task_text = self._renderer.render(
                "review_consistency",
                {
                    "style_bible": style_bible_summary or "（无）",
                    "character_set": character_set_summary or "（无）",
                    "shots_summary": shots_summary or "（无镜头数据）",
                },
            )
        except Exception as exc:
            _logger.warning(
                f"Prompt 渲染失败（task），使用内置提示词: {exc}",
                event_type="cg_task_render_failed",
            )
            task_text = (
                f"风格规格：{style_bible_summary}\n"
                f"角色设定：{character_set_summary}\n"
                f"镜头摘要：{shots_summary}\n\n"
                "请输出结构化 JSON 质检报告，包含 issues / recommendations / "
                "overall_consistency_score 三个字段。"
            )

        # ---- 调用 LLM -------------------------------------------------------
        try:
            api_key = self._cfg.api_key
            if not api_key:
                raise ValueError("LLM API key 未配置")

            extra_body = {"enable_thinking": False} if not getattr(self._cfg, "enable_thinking", False) else None
            model_kwargs: dict[str, Any] = {
                "model": self._cfg.model,
                "api_key": api_key,
                "temperature": self._cfg.temperature,
                "max_tokens": self._cfg.max_tokens,
                "timeout": self._cfg.timeout,
                "extra_body": extra_body,
            }
            if self._cfg.base_url:
                model_kwargs["base_url"] = self._cfg.base_url

            llm = ChatOpenAI(**model_kwargs)
            messages = [
                SystemMessage(content=system_text),
                HumanMessage(content=task_text),
            ]
            response = await llm.ainvoke(messages)
            raw_text: str = (
                response.content if hasattr(response, "content") else str(response)
            )
            result = _safe_parse_json(raw_text)

            # 标准化：确保必要字段存在
            if not isinstance(result.get("issues"), list):
                result["issues"] = []
            if not isinstance(result.get("recommendations"), list):
                result["recommendations"] = []
            if not isinstance(result.get("overall_consistency_score"), (int, float)):
                result["overall_consistency_score"] = 1.0

            _logger.info(
                f"一致性质检完成: issues={len(result['issues'])} "
                f"score={result['overall_consistency_score']}",
                event_type="consistency_check_done",
            )
            return result

        except Exception as exc:
            _logger.warning(
                f"LLM 调用失败，使用兜底（空 issues）: {exc}",
                event_type="cg_llm_fallback",
            )
            return _empty_result()

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fallback_system_prompt(
        style_bible_summary: str, character_set_summary: str
    ) -> str:
        return (
            "你是一个视频一致性质检专家。请检查以下项目产物中的角色一致性、"
            "风格一致性和节奏一致性问题，并输出结构化 JSON 报告，"
            "包含 issues / recommendations / overall_consistency_score 三个字段。\n"
            f"风格规格摘要：{style_bible_summary}\n"
            f"角色设定摘要：{character_set_summary}"
        )


# ---------------------------------------------------------------------------
# 辅助：从 ORM 对象构建 shots_summary 文本
# ---------------------------------------------------------------------------

def build_shots_summary(shots: list[Any]) -> str:
    """将 Shot ORM 列表转成 LLM 可读的摘要文本。

    Args:
        shots: Shot ORM 对象列表（需有 id / shot_index / emotion /
               camera_language / visual_energy / lipsync_required / status 字段）。

    Returns:
        格式化的多行摘要字符串。
    """
    if not shots:
        return "（无镜头数据）"

    lines = []
    for s in shots:
        lipsync = "需口型" if getattr(s, "lipsync_required", False) else "普通"
        lines.append(
            f"  Shot {getattr(s, 'shot_index', '?'):>2}: "
            f"emotion={getattr(s, 'emotion', '?')!r:<24} "
            f"camera={getattr(s, 'camera_language', '?')!r:<30} "
            f"energy={getattr(s, 'visual_energy', '?')!r} "
            f"{lipsync} status={getattr(s, 'status', '?')!r}"
        )
    return "\n".join(lines)
