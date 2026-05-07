"""重新生成反馈上下文服务。"""
from __future__ import annotations

import json
from typing import Any

from app.models.events import EventLog
from app.repositories.event_log_repository import EventLogRepository
from app.repositories.unit_of_work import UnitOfWork


REGENERATION_FEEDBACK_EVENT = "decision.feedback.submitted"


def _compact_json(value: Any, *, max_chars: int = 5000) -> str:
    try:
        text = json.dumps(value or {}, ensure_ascii=False, indent=2)
    except TypeError:
        text = str(value or "")
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n...（已截断）"
    return text


class RegenerationContextService:
    """读取用户返工反馈，并整理为 LLM 可消费的上下文。"""

    async def get_latest_feedback(
        self,
        project_id: str,
        *,
        decision_type: str,
        target_entity_id: str | None = None,
    ) -> dict[str, Any] | None:
        async with UnitOfWork() as uow:
            events = await EventLogRepository(
                uow.session
            ).list_project_events_by_type(
                project_id,
                REGENERATION_FEEDBACK_EVENT,
                limit=50,
            )
        for event in events:
            payload = getattr(event, "payload", {}) or {}
            if payload.get("decision_type") != decision_type:
                continue
            if target_entity_id and payload.get("target_entity_id") not in {
                target_entity_id,
                None,
                "",
            }:
                continue
            return self._event_to_feedback(event)
        return None

    def _event_to_feedback(self, event: EventLog) -> dict[str, Any]:
        payload = getattr(event, "payload", {}) or {}
        return {
            "event_id": getattr(event, "id", None),
            "created_at": (
                getattr(event, "created_at", None).isoformat()
                if getattr(event, "created_at", None)
                else None
            ),
            "decision_id": payload.get("decision_id"),
            "decision_type": payload.get("decision_type"),
            "target_entity_id": payload.get("target_entity_id"),
            "feedback_text": str(payload.get("feedback_text") or "").strip(),
            "selected_option_id": payload.get("selected_option_id"),
        }

    def build_narrative_prompt_section(
        self,
        *,
        feedback: dict[str, Any] | None,
        current_narrative_payload: dict[str, Any] | None,
    ) -> str:
        if not feedback or not feedback.get("feedback_text"):
            return ""
        return (
            "\n\n【本轮重新生成要求】\n"
            "用户在确认创意剧本包前选择了重新生成。你必须基于当前剧本包和用户反馈进行修订，"
            "不要无视上一版产物，也不要只重复原始需求。\n"
            f"用户反馈：{feedback['feedback_text']}\n"
            "当前剧本包 JSON 摘要：\n"
            f"{_compact_json(current_narrative_payload, max_chars=8000)}\n"
            "请保留仍然有效的角色、主题、时长和结构约束，只改进用户明确不满意的方向。"
        )

    def build_storyboard_prompt_section(
        self,
        *,
        feedback: dict[str, Any] | None,
        current_storyboard_payload: dict[str, Any] | None,
        previous_prompt: str | None,
    ) -> str:
        if not feedback or not feedback.get("feedback_text"):
            return ""
        return (
            "\n\n【本轮重新生成要求】\n"
            "用户在确认故事大图/关键帧前选择了重新生成。你必须理解上一版图片生成结果、上一轮提示词和用户反馈，"
            "把反馈落实到新的图片提示词中。\n"
            f"用户反馈：{feedback['feedback_text']}\n"
            "上一版故事大图/关键帧元数据：\n"
            f"{_compact_json(current_storyboard_payload, max_chars=7000)}\n"
            "上一轮图片提示词：\n"
            f"{(previous_prompt or '（未找到上一轮提示词）')[:5000]}\n"
            "请保持项目主题、镜头数量、画幅、角色连续性和产品参考图约束不变，只重写画面表达、构图、风格或细节。"
        )


regeneration_context_service = RegenerationContextService()
