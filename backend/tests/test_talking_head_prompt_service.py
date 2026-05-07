from types import SimpleNamespace

from app.services.talking_head_prompt_service import (
    _build_clean_reference_prompt,
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
        clean_reference_url="https://example.com/clean-shot-2.png",
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

    assert "光希老王" in positive
    assert "图片1是唯一服装与整体造型基准" in positive
    assert "图片2、图片3只用于补充锁定同一角色" in positive
    assert "图片4是当前 shot 的 clean visual reference" in positive
    assert "不是 Production Board" in positive
    assert "无字幕硬约束" in positive
    assert "画面中绝对不要出现任何可读文字" in positive
    assert "产品瓶身和道具只能作为不可读的视觉符号" in positive
    assert "只读取故事大图中 Segment 2 / 15-30s 区域" in positive
    assert rendered["reference_image_urls"][3] == "https://example.com/clean-shot-2.png"
    assert "https://example.com/board.png" not in rendered["reference_image_urls"]
    assert rendered["params"]["watermark"] is False
    assert "换装" in negative
    assert "改性别" in negative
    assert "照抄故事大图乱码文字" in negative


def test_enforce_talking_head_video_prompt_contract_repairs_llm_drift():
    rendered = _enforce_video_prompt_contract(
        {
            "positive_prompt": "生成一个15秒中文单人知识口播视频。浅米色西装，女性形象。",
            "negative_prompt": "字幕",
        }
    )

    positive = rendered["positive_prompt"]
    negative = rendered["negative_prompt"]

    assert "主角只能是光希老王" in positive
    assert "图片1是唯一服装与整体造型基准" in positive
    assert "图片4是当前 shot 的 clean visual reference" in positive
    assert "无字幕硬约束" in positive
    assert "台词只能通过人物声音、口型和表演传达" in positive
    assert "改性别" in negative
    assert "服装漂移" in negative
    assert "从图片2或图片3引入新服装" in negative
    assert "读取其他 Segment" in negative
    assert "CTA文字" in negative
    assert "可读文字" in negative


def test_clean_reference_prompt_removes_production_board_text_elements():
    rendered = _build_clean_reference_prompt(
        shot=SimpleNamespace(shot_index=0),
        segment_script={"segment_goal": "从静态开场切到配合手势进行科普讲解。"},
        story_board_url="https://example.com/board.png",
        layout_reading_map={"segment_1": "仅读取 Segment 1 / 0-15s 的构图和动作"},
        topic="视黄醇科普",
        product_refs=[{"asset_id": "prod_1", "url": "https://example.com/product.png"}],
    )

    positive = rendered["image_positive_prompt"]
    negative = rendered["image_negative_prompt"]

    assert "不要裁剪原图" in positive
    assert "无字幕" in positive
    assert "无标题" in positive
    assert "无编号" in positive
    assert "无任何可读中文/英文/数字" in positive
    assert "用户上传产品图" in positive
    assert "https://example.com/product.png" in positive
    assert "产品瓶身、包装、颜色、材质、形态" in positive
    assert "不相干产品" in positive
    assert "Production Board" in negative
    assert "可读产品文字" in negative
    assert "与用户上传产品图不一致的产品" in negative
    assert rendered["params"]["size"] == "1920x1080"
