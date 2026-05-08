from app.agents.narrative_script_agent import (
    _build_fallback_dialogues,
    _build_reference_image_instruction,
    _reference_image_parts,
)


def test_fallback_dialogues_use_spoken_talking_head_style():
    dialogues = _build_fallback_dialogues("讲解视黄醇怎么建立耐受", 3)

    joined = "\n".join(dialogues)

    assert any(line for line in dialogues)
    assert "今天用一分钟带你快速了解" not in joined
    assert "核心原则" not in joined
    assert "正确做法是" not in joined
    assert "少走弯路" not in joined
    assert "不红不刺" in joined


def test_narrative_reference_instruction_numbers_products_before_scene():
    instruction = _build_reference_image_instruction(
        product_reference_urls=[
            "https://example.com/product-1.png",
            "https://example.com/product-2.png",
            "https://example.com/product-3.png",
        ],
        scene_reference_url="https://example.com/scene.png",
        product_reference_role="产品参考图",
        scene_reference_role="当前场地图",
        scene_reference_observation="开放式厨房台面，暖光，浅色石材背景。",
        product_reference_observation="白色泵头瓶，银色标签。",
    )

    assert "图1-图3 为产品参考图" in instruction
    assert "图4 为当前场地图" in instruction
    assert "开放式厨房台面" in instruction
    assert "白色泵头瓶" in instruction


def test_narrative_reference_image_parts_keep_scene_last():
    parts = _reference_image_parts(
        product_reference_urls=[
            "https://example.com/product-1.png",
            "https://example.com/product-2.png",
        ],
        scene_reference_url="https://example.com/scene.png",
    )

    assert [part["image_url"]["url"] for part in parts] == [
        "https://example.com/product-1.png",
        "https://example.com/product-2.png",
        "https://example.com/scene.png",
    ]
