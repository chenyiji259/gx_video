"""Shot plan 时长归一化工具。"""
from __future__ import annotations

from typing import Any

from app.services.output_spec_service import (
    TALKING_HEAD_LAYOUT,
    TALKING_HEAD_SEGMENT_DURATION_SEC,
)


class ShotPlanDurationError(ValueError):
    """Shot plan 时长契约异常。"""


def apply_talking_head_duration_plan(
    shot_list_data: list[dict[str, Any]],
    target_duration_sec: float,
) -> tuple[list[dict[str, Any]], float]:
    """口播 Production Board 强制按 15 秒 segment 重建 shot 时间轴。"""
    target_total = int(round(target_duration_sec or 0))
    if target_total < TALKING_HEAD_SEGMENT_DURATION_SEC:
        raise ShotPlanDurationError("口播 shot plan target_duration_sec 必须至少为 15 秒")
    if target_total % TALKING_HEAD_SEGMENT_DURATION_SEC != 0:
        raise ShotPlanDurationError("口播 shot plan target_duration_sec 必须是 15 秒的整数倍")

    segment_count = target_total // TALKING_HEAD_SEGMENT_DURATION_SEC
    source_shots = [dict(item) for item in (shot_list_data or [])]
    normalized_shots: list[dict[str, Any]] = []
    for index in range(segment_count):
        source = source_shots[index] if index < len(source_shots) else {}
        normalized = dict(source)
        start_ms = index * TALKING_HEAD_SEGMENT_DURATION_SEC * 1000
        end_ms = start_ms + TALKING_HEAD_SEGMENT_DURATION_SEC * 1000
        requested_duration = source.get("duration_sec")
        normalized["shot_index"] = index
        normalized["scene_id"] = f"scene_{index + 1:03d}"
        normalized["duration_sec"] = TALKING_HEAD_SEGMENT_DURATION_SEC
        normalized["start_ms"] = start_ms
        normalized["end_ms"] = end_ms
        normalized["segment_index"] = index + 1
        normalized["segment_duration_sec"] = TALKING_HEAD_SEGMENT_DURATION_SEC
        normalized["storyboard_layout"] = TALKING_HEAD_LAYOUT
        style_binding = list(normalized.get("style_binding") or [])
        try:
            requested_duration_value = int(round(float(requested_duration or 0)))
        except (TypeError, ValueError):
            requested_duration_value = 0
        if (
            index >= len(source_shots)
            or requested_duration_value != TALKING_HEAD_SEGMENT_DURATION_SEC
        ):
            style_binding.append(
                {
                    "type": "talking_head_duration_lock",
                    "requested_duration_sec": requested_duration,
                    "normalized_duration_sec": TALKING_HEAD_SEGMENT_DURATION_SEC,
                    "segment_index": index + 1,
                }
            )
        normalized["style_binding"] = style_binding
        normalized_shots.append(normalized)

    return normalized_shots, float(target_total)


def build_talking_head_scene_plan(shot_list_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "scene_id": str(shot.get("scene_id") or f"scene_{index + 1:03d}"),
            "scene_name": f"口播 Segment {index + 1}",
            "shot_indices": [index],
            "storyboard_layout": TALKING_HEAD_LAYOUT,
            "segment_index": index + 1,
        }
        for index, shot in enumerate(shot_list_data)
    ]
