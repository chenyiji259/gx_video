from types import SimpleNamespace

from app.services.talking_head_prompt_service import (
    _enforce_video_prompt_contract,
    _fallback_video_prompt,
)


def test_fallback_talking_head_video_prompt_locks_host_identity_and_clothing():
    rendered = _fallback_video_prompt(
        shot=SimpleNamespace(shot_index=1, dialogue=""),
        segment_script={
            "dialogue": "它不像普通抗氧化剂只停留在表面，而是能直接进入细胞线粒体。",
            "segment_goal": "讲清麦角硫因从源头清除自由基。",
        },
        story_board_url="https://example.com/board.png",
        host_assets=[
            "asset://host-clothing-base",
            "asset://host-face-2",
            "asset://host-face-3",
        ],
        audio_assets=["https://example.com/voice-1.wav"],
        layout_reading_map={"segment_2": "只读取故事大图中 Segment 2 / 15-30s 区域"},
    )

    positive = rendered["positive_prompt"]
    negative = rendered["negative_prompt"]

    assert "50岁男性护肤专家" in positive
    assert "图片1是唯一服装与整体造型基准" in positive
    assert "图片2、图片3只用于补充锁定同一角色" in positive
    assert "不要读取、复刻或依赖图片4里的中文文字" in positive
    assert "不依赖图片4 OCR" in positive
    assert "只读取故事大图中 Segment 2 / 15-30s 区域" in positive
    assert rendered["params"]["watermark"] is False
    assert "换装" in negative
    assert "女性专家" in negative
    assert "照抄故事大图乱码文字" in negative


def test_enforce_talking_head_video_prompt_contract_repairs_llm_drift():
    rendered = _enforce_video_prompt_contract(
        {
            "positive_prompt": "生成一个15秒中文单人专家知识口播视频。浅米色西装，女性护肤专家。",
            "negative_prompt": "字幕",
        }
    )

    positive = rendered["positive_prompt"]
    negative = rendered["negative_prompt"]

    assert "主角只能是50岁男性护肤专家" in positive
    assert "图片1是唯一服装与整体造型基准" in positive
    assert "不读取、不复刻图片4里的中文文字" in positive
    assert "女性专家" in negative
    assert "服装漂移" in negative
    assert "从图片2或图片3引入新服装" in negative
    assert "读取其他 Segment" in negative
