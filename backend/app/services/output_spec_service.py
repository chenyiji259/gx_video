"""输出规格与 Storyboard 规划工具。"""
from __future__ import annotations

from math import ceil
from typing import Any

from app.core.provider_registry import get_provider_registry

SUPPORTED_VIDEO_RATIOS = {"9:16", "16:9", "1:1", "adaptive"}
SUPPORTED_VIDEO_RESOLUTIONS = {"480p", "720p", "1080p"}
SUPPORTED_IMAGE_RESOLUTIONS = {"1K", "2K", "4K"}
TALKING_HEAD_PROFILE = "talking_head_production_board"
TALKING_HEAD_LAYOUT = "talking_head_story_overview_board"
TALKING_HEAD_SEGMENT_DURATION_SEC = 15
TALKING_HEAD_STORY_BOARD_ASPECT_RATIO = "21:9"
TALKING_HEAD_STORY_BOARD_IMAGE_SIZE = "21:9"
TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION = "4K"
TALKING_HEAD_STYLE_PREFERENCE = "专家知识口播，专业、亲和、干净护肤科普，纯净无字幕画面"

IMAGE_SIZE_BY_RATIO: dict[str, dict[str, str]] = {
    # GPT Image 2 不支持 27:16 三宫格总画幅。三宫格统一请求 16:9 + 2K，
    # 切分后再按 target_cell_aspect_ratio 做中心裁剪，供视频阶段使用。
    "9:16": {
        "size": "16:9",
        "resolution": "2K",
        "orientation": "landscape",
        "target_cell_aspect_ratio": "9:16",
    },
    "16:9": {
        "size": "16:9",
        "resolution": "2K",
        "orientation": "landscape",
        "target_cell_aspect_ratio": "16:9",
    },
    "1:1": {
        "size": "16:9",
        "resolution": "2K",
        "orientation": "landscape",
        "target_cell_aspect_ratio": "1:1",
    },
}


def allowed_video_durations() -> list[int]:
    values = get_provider_registry().list_supported_durations("video", enabled_only=True)
    return sorted({int(v) for v in (values or [4, 5, 6, 8, 10, 12, 15])})


def is_talking_head_config(output_config: dict[str, Any] | None) -> bool:
    """判断输出配置是否进入口播 Production Board 主链路。"""
    cfg = output_config or {}
    return (
        cfg.get("generation_profile") == TALKING_HEAD_PROFILE
        or cfg.get("storyboard_layout") == TALKING_HEAD_LAYOUT
        or cfg.get("content_type") == "talking_head"
    )


def normalize_output_config(output_config: dict[str, Any] | None) -> dict[str, Any]:
    """规范化从需求入口传入的输出规格，作为后续生成和合成的唯一契约。"""
    cfg = dict(output_config or {})

    ratio = str(cfg.get("aspect_ratio") or "9:16").strip()
    if ratio not in SUPPORTED_VIDEO_RATIOS:
        ratio = "9:16"
    if ratio == "adaptive":
        ratio = "9:16"

    video_resolution = str(cfg.get("video_resolution") or cfg.get("resolution") or "1080p").strip()
    if video_resolution not in SUPPORTED_VIDEO_RESOLUTIONS:
        video_resolution = "1080p"

    image_resolution = str(cfg.get("image_resolution") or "2K").strip().upper()
    if image_resolution not in SUPPORTED_IMAGE_RESOLUTIONS:
        image_resolution = "2K"

    try:
        target_duration_sec = float(cfg.get("target_duration_sec") or 15)
    except (TypeError, ValueError):
        target_duration_sec = 15.0
    target_duration_sec = max(4.0, min(target_duration_sec, 600.0))

    if is_talking_head_config(cfg):
        return normalize_talking_head_output_config(
            cfg,
            target_duration_sec=target_duration_sec,
            aspect_ratio=ratio,
            video_resolution=video_resolution,
            image_resolution=image_resolution,
        )

    image_grid = resolve_triptych_image_spec(ratio)
    if image_resolution != image_grid["resolution"]:
        # 当前三宫格使用像素尺寸直传，保持 2K 以避免切分后 cell 低于视频生成质量要求。
        image_resolution = image_grid["resolution"]

    cfg.update(
        {
            "target_duration_sec": target_duration_sec,
            "aspect_ratio": ratio,
            "video_resolution": video_resolution,
            "image_resolution": image_resolution,
            "storyboard_layout": "1x3_triptych",
            "grid_columns": 3,
            "grid_rows": 1,
            "image_size": image_grid["size"],
            "image_orientation": image_grid["orientation"],
        }
    )
    return cfg


def normalize_talking_head_output_config(
    cfg: dict[str, Any],
    *,
    target_duration_sec: float,
    aspect_ratio: str,
    video_resolution: str,
    image_resolution: str,
) -> dict[str, Any]:
    """规范化口播类项目规格，强制 15 秒 segment 和 21:9 故事大图。"""
    target_total = int(round(target_duration_sec))
    if target_total < TALKING_HEAD_SEGMENT_DURATION_SEC:
        raise ValueError("口播类视频 target_duration_sec 必须至少为 15 秒")
    if target_total % TALKING_HEAD_SEGMENT_DURATION_SEC != 0:
        raise ValueError("口播类视频 target_duration_sec 必须是 15 秒的整数倍")

    segment_duration = int(cfg.get("segment_duration_sec") or TALKING_HEAD_SEGMENT_DURATION_SEC)
    if segment_duration != TALKING_HEAD_SEGMENT_DURATION_SEC:
        raise ValueError("口播类视频 segment_duration_sec 必须等于 15")

    story_board_aspect_ratio = str(
        cfg.get("story_board_aspect_ratio") or TALKING_HEAD_STORY_BOARD_ASPECT_RATIO
    ).strip()
    if story_board_aspect_ratio != TALKING_HEAD_STORY_BOARD_ASPECT_RATIO:
        raise ValueError("口播类故事大图 story_board_aspect_ratio 必须是 21:9")

    cfg.update(
        {
            "generation_profile": TALKING_HEAD_PROFILE,
            "content_type": "talking_head",
            "target_duration_sec": target_total,
            "segment_duration_sec": TALKING_HEAD_SEGMENT_DURATION_SEC,
            "segment_count": target_total // TALKING_HEAD_SEGMENT_DURATION_SEC,
            "shot_count": target_total // TALKING_HEAD_SEGMENT_DURATION_SEC,
            "grid_count": 1,
            "total_shots_generated": target_total // TALKING_HEAD_SEGMENT_DURATION_SEC,
            "storyboard_layout": TALKING_HEAD_LAYOUT,
            "story_board_aspect_ratio": story_board_aspect_ratio,
            "story_board_image_size": TALKING_HEAD_STORY_BOARD_IMAGE_SIZE,
            "story_board_image_resolution": TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
            "aspect_ratio": aspect_ratio,
            "video_resolution": video_resolution,
            "image_resolution": image_resolution if image_resolution in SUPPORTED_IMAGE_RESOLUTIONS else "2K",
            "style_preference": TALKING_HEAD_STYLE_PREFERENCE,
            "subtitles_enabled": False,
            "human_on_camera": True if cfg.get("human_on_camera") is None else bool(cfg.get("human_on_camera")),
        }
    )
    return cfg


def resolve_triptych_image_spec(aspect_ratio: str) -> dict[str, Any]:
    spec = IMAGE_SIZE_BY_RATIO.get(aspect_ratio, IMAGE_SIZE_BY_RATIO["9:16"])
    return {
        **spec,
        "width": 2304,
        "height": 1296,
        "cell_width": 768,
        "cell_height": 1296,
    }


def plan_triptych_shots(target_duration_sec: float) -> dict[str, Any]:
    """按 Seedance 单 clip 最长 15s 规划三宫格 shot 数与时长档位。"""
    durations = allowed_video_durations()
    max_duration = min(15, max(durations or [15]))
    target_total = max(4, int(round(target_duration_sec or max_duration)))
    shot_count = max(1, ceil(target_total / max_duration))

    base = target_total / shot_count
    planned: list[int] = []
    for _ in range(shot_count):
        planned.append(min(durations, key=lambda item: (abs(item - base), item)))

    # 尽量逼近目标总时长，同时保持每段 <=15s 且落在 provider 档位内。
    for _ in range(max(1, shot_count * 8)):
        diff = target_total - sum(planned)
        if diff == 0:
            break
        best_index = -1
        best_value = None
        best_score = None
        for index, current in enumerate(planned):
            current_pos = durations.index(current)
            next_positions: list[int] = []
            if diff > 0 and current_pos < len(durations) - 1:
                next_positions.append(current_pos + 1)
            if diff < 0 and current_pos > 0:
                next_positions.append(current_pos - 1)
            for pos in next_positions:
                candidate = durations[pos]
                if candidate > max_duration:
                    continue
                delta = candidate - current
                score = (abs(diff - delta), abs(delta), candidate)
                if best_score is None or score < best_score:
                    best_score = score
                    best_index = index
                    best_value = candidate
        if best_index < 0 or best_value is None:
            break
        planned[best_index] = best_value

    return {
        "target_duration_sec": target_total,
        "shot_duration_sec": planned[0] if len(set(planned)) == 1 else None,
        "shot_durations_sec": planned,
        "shot_count": len(planned),
        "grid_count": len(planned),
        "total_shots_generated": len(planned),
        "allowed_shot_durations_sec": durations,
        "max_clip_duration_sec": max_duration,
        "storyboard_layout": "1x3_triptych",
    }


def plan_talking_head_segments(target_duration_sec: float) -> dict[str, Any]:
    """按 15 秒硬边界规划口播 segment / shot / clip。"""
    target_total = int(round(target_duration_sec or 0))
    if target_total < TALKING_HEAD_SEGMENT_DURATION_SEC:
        raise ValueError("口播类视频 target_duration_sec 必须至少为 15 秒")
    if target_total % TALKING_HEAD_SEGMENT_DURATION_SEC != 0:
        raise ValueError("口播类视频 target_duration_sec 必须是 15 秒的整数倍")
    count = target_total // TALKING_HEAD_SEGMENT_DURATION_SEC
    return {
        "target_duration_sec": target_total,
        "shot_duration_sec": TALKING_HEAD_SEGMENT_DURATION_SEC,
        "shot_durations_sec": [TALKING_HEAD_SEGMENT_DURATION_SEC] * count,
        "shot_count": count,
        "grid_count": 1,
        "segment_count": count,
        "segment_duration_sec": TALKING_HEAD_SEGMENT_DURATION_SEC,
        "total_shots_generated": count,
        "allowed_shot_durations_sec": [TALKING_HEAD_SEGMENT_DURATION_SEC],
        "max_clip_duration_sec": TALKING_HEAD_SEGMENT_DURATION_SEC,
        "storyboard_layout": TALKING_HEAD_LAYOUT,
        "generation_profile": TALKING_HEAD_PROFILE,
        "story_board_aspect_ratio": TALKING_HEAD_STORY_BOARD_ASPECT_RATIO,
        "story_board_image_size": TALKING_HEAD_STORY_BOARD_IMAGE_SIZE,
        "story_board_image_resolution": TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
        "subtitles_enabled": False,
    }
