import pytest

from app.services.output_spec_service import (
    TALKING_HEAD_LAYOUT,
    TALKING_HEAD_PROFILE,
    TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
    TALKING_HEAD_STORY_BOARD_IMAGE_SIZE,
    normalize_output_config,
    plan_talking_head_segments,
    plan_triptych_shots,
    resolve_triptych_image_spec,
)
from app.tools.image_generation_tool import ImageGenerationTool


def test_crop_triptych_cell_to_vertical_reference_ratio():
    from PIL import Image

    cell = Image.new("RGB", (768, 1296))
    cropped = ImageGenerationTool._crop_to_aspect_ratio(cell, "9:16")
    assert cropped.size == (729, 1296)


def test_triptych_image_cells_match_target_video_ratios():
    portrait = resolve_triptych_image_spec("9:16")
    assert portrait["size"] == "16:9"
    assert portrait["resolution"] == "2K"
    assert portrait["target_cell_aspect_ratio"] == "9:16"
    assert portrait["cell_width"] == 768
    assert portrait["cell_height"] == 1296

    landscape = resolve_triptych_image_spec("16:9")
    assert landscape["size"] == "16:9"
    assert landscape["target_cell_aspect_ratio"] == "16:9"

    square = resolve_triptych_image_spec("1:1")
    assert square["size"] == "16:9"
    assert square["target_cell_aspect_ratio"] == "1:1"


def test_normalize_output_config_sets_generation_contract():
    cfg = normalize_output_config(
        {
            "target_duration_sec": 12,
            "aspect_ratio": "16:9",
            "video_resolution": "720p",
            "image_resolution": "4K",
        }
    )

    assert cfg["target_duration_sec"] == 12.0
    assert cfg["aspect_ratio"] == "16:9"
    assert cfg["video_resolution"] == "720p"
    assert cfg["image_resolution"] == "2K"
    assert cfg["storyboard_layout"] == "1x3_triptych"
    assert cfg["grid_rows"] == 1
    assert cfg["grid_columns"] == 3
    assert cfg["image_size"] == "16:9"


def test_plan_triptych_shots_caps_each_clip_at_15_seconds():
    short_plan = plan_triptych_shots(12)
    assert short_plan["shot_count"] == 1
    assert short_plan["grid_count"] == 1
    assert max(short_plan["shot_durations_sec"]) <= 15

    long_plan = plan_triptych_shots(31)
    assert long_plan["shot_count"] >= 3
    assert long_plan["grid_count"] == long_plan["shot_count"]
    assert max(long_plan["shot_durations_sec"]) <= 15


def test_normalize_talking_head_output_config_sets_story_overview_contract():
    cfg = normalize_output_config(
        {
            "generation_profile": TALKING_HEAD_PROFILE,
            "target_duration_sec": 60,
            "aspect_ratio": "9:16",
            "video_resolution": "1080p",
            "story_board_aspect_ratio": "21:9",
            "segment_duration_sec": 15,
        }
    )

    assert cfg["generation_profile"] == TALKING_HEAD_PROFILE
    assert cfg["content_type"] == "talking_head"
    assert cfg["storyboard_layout"] == TALKING_HEAD_LAYOUT
    assert cfg["target_duration_sec"] == 60
    assert cfg["segment_duration_sec"] == 15
    assert cfg["segment_count"] == 4
    assert cfg["shot_count"] == 4
    assert cfg["grid_count"] == 1
    assert cfg["story_board_aspect_ratio"] == "21:9"
    assert cfg["story_board_image_size"] == TALKING_HEAD_STORY_BOARD_IMAGE_SIZE
    assert cfg["story_board_image_resolution"] == TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION
    assert cfg["aspect_ratio"] == "9:16"
    assert cfg["subtitles_enabled"] is False


def test_talking_head_output_config_rejects_non_15_second_multiple():
    with pytest.raises(ValueError, match="15 秒的整数倍"):
        normalize_output_config(
            {
                "storyboard_layout": TALKING_HEAD_LAYOUT,
                "target_duration_sec": 50,
            }
        )


def test_plan_talking_head_segments_uses_one_board_and_fixed_15s_clips():
    plan = plan_talking_head_segments(45)

    assert plan["shot_count"] == 3
    assert plan["segment_count"] == 3
    assert plan["grid_count"] == 1
    assert plan["shot_durations_sec"] == [15, 15, 15]
    assert plan["allowed_shot_durations_sec"] == [15]
    assert plan["storyboard_layout"] == TALKING_HEAD_LAYOUT
    assert plan["story_board_image_size"] == TALKING_HEAD_STORY_BOARD_IMAGE_SIZE
    assert plan["story_board_image_resolution"] == TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION
