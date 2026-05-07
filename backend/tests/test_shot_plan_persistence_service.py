import pytest

from app.services.output_spec_service import TALKING_HEAD_LAYOUT
from app.services.shot_plan_duration_service import (
    ShotPlanDurationError,
    apply_talking_head_duration_plan,
)


def test_apply_talking_head_duration_plan_rebuilds_fixed_15s_segments():
    shots, total = apply_talking_head_duration_plan(
        [
            {"shot_index": 9, "duration_sec": 8, "start_ms": 1200, "end_ms": 9200},
            {"shot_index": 10, "duration_sec": "bad"},
            {"shot_index": 11, "duration_sec": 20},
            {"shot_index": 12, "duration_sec": 15},
            {"shot_index": 13, "duration_sec": 15},
        ],
        60,
    )

    assert total == 60.0
    assert len(shots) == 4
    assert [shot["shot_index"] for shot in shots] == [0, 1, 2, 3]
    assert [shot["duration_sec"] for shot in shots] == [15, 15, 15, 15]
    assert [shot["start_ms"] for shot in shots] == [0, 15000, 30000, 45000]
    assert [shot["end_ms"] for shot in shots] == [15000, 30000, 45000, 60000]
    assert all(shot["storyboard_layout"] == TALKING_HEAD_LAYOUT for shot in shots)
    assert all(shot["segment_index"] == index + 1 for index, shot in enumerate(shots))
    assert shots[0]["style_binding"][0]["type"] == "talking_head_duration_lock"
    assert shots[1]["style_binding"][0]["requested_duration_sec"] == "bad"


def test_apply_talking_head_duration_plan_rejects_non_15s_multiple():
    with pytest.raises(ShotPlanDurationError, match="15 秒的整数倍"):
        apply_talking_head_duration_plan([{"duration_sec": 15}], 50)
