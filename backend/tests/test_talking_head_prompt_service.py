from types import SimpleNamespace

import pytest

from app.services.talking_head_prompt_service import (
    _build_story_overview_board_prompt,
    _enforce_video_prompt_contract,
    _fallback_video_prompt,
    _audio_reference_prompt_items,
    _default_scene_reference_path,
    _host_reference_prompt_items,
    _ordered_person_reference_paths,
    _product_reference_prompt_items,
    _product_reference_text,
    _story_overview_board_reference_urls,
    TalkingHeadPromptService,
)
from app.utils.ids import generate_ulid


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
    assert "光希老王" in positive
    assert "图片1是唯一服装与整体造型基准" in positive
    assert "图片2、图片3只用于补充锁定同一角色" in positive
    assert "图片4是完整 Story Overview Board / Production Board 大图" in positive
    assert "不要复刻它的网格页面" in positive
    assert positive.startswith("此视频不生成字幕。最终画面必须纯净无字")
    assert "产品图必须作为本段介绍/展示的真实产品外观参考" in positive
    assert "只读取故事大图中 Segment 2 / 15-30s 区域" in positive
    assert rendered["reference_image_urls"][3] == "https://example.com/board.png"
    assert rendered["params"]["watermark"] is False
    assert "clean visual reference" not in positive
    assert "口播" not in positive
    assert "声音硬约束" not in positive
    assert "negative_prompt" not in rendered


def test_enforce_talking_head_video_prompt_contract_repairs_llm_drift():
    rendered = _enforce_video_prompt_contract(
        {
            "positive_prompt": "生成一个15秒中文单人知识视频。浅米色西装，女性形象。",
            "negative_prompt": "字幕",
        }
    )

    positive = rendered["positive_prompt"]
    assert "主角只能是光希老王" in positive
    assert "图片1是唯一服装与整体造型基准" in positive
    assert "图片4是完整 Story Overview Board / Production Board 大图" in positive
    assert positive.startswith("此视频不生成字幕。最终画面必须纯净无字")
    assert "口播" not in positive
    assert "声音硬约束" not in positive
    assert "negative_prompt" not in rendered

def test_story_overview_board_reference_urls_include_hosts_scene_and_products():
    urls = _story_overview_board_reference_urls(
        host_reference_urls=[
            "https://example.com/person-1.png",
            "https://example.com/person-2.png",
            "https://example.com/person-3.png",
            "https://example.com/person-extra.png",
        ],
        scene_reference_url="https://example.com/scene.png",
        product_refs=[
            {"asset_id": "prod_1", "url": "https://example.com/product-1.png"},
            {"asset_id": "prod_2", "url": "https://example.com/product-2.png"},
            {"asset_id": "prod_3", "url": "https://example.com/product-3.png"},
        ],
    )

    assert urls == [
        "https://example.com/person-1.png",
        "https://example.com/person-2.png",
        "https://example.com/person-3.png",
        "https://example.com/scene.png",
        "https://example.com/product-1.png",
        "https://example.com/product-2.png",
        "https://example.com/product-3.png",
    ]


def test_local_reference_paths_treat_r_images_as_people_and_d1_as_scene(tmp_path):
    for name in ("d1.png", "r3.png", "r1.png", "r2.png", "a_wrong.png"):
        (tmp_path / name).write_bytes(b"fake")

    person_paths = _ordered_person_reference_paths(tmp_path)
    scene_path = _default_scene_reference_path(tmp_path)

    assert [path.name for path in person_paths] == ["r1.png", "r2.png", "r3.png"]
    assert scene_path is not None
    assert scene_path.name == "d1.png"


def test_story_overview_board_prompt_numbers_products_as_5_6_7_without_urls():
    rendered = _build_story_overview_board_prompt(
        spec=SimpleNamespace(
            user_prompt="光希视黄醇精华",
            output_config={"target_duration_sec": 15, "target_audience": "中老年用户"},
        ),
        brief_payload={"title": "光希视黄醇精华"},
        style_payload={},
        narrative_payload={"shots": [{"dialogue": "大家好。今天讲抗皱。"}]},
        host_assets=[
            "https://example.com/person-1.png",
            "https://example.com/person-2.png",
            "https://example.com/person-3.png",
        ],
        audio_assets=[],
        scene_asset_url="https://example.com/scene.png",
        product_refs=[
            {"asset_id": "prod_1", "url": "https://example.com/product-1.png"},
            {"asset_id": "prod_2", "url": "https://example.com/product-2.png"},
            {"asset_id": "prod_3", "url": "https://example.com/product-3.png"},
        ],
    )

    positive = rendered["image_positive_prompt"]

    assert "图片5是用户上传的产品图" in positive
    assert "图片6是用户上传的产品图" in positive
    assert "图片7是用户上传的产品图" in positive
    assert "图片3是用户上传的产品图" not in positive
    assert "图片4是用户上传的产品图" not in positive
    assert "https://example.com" not in positive
    assert "人声之外不需要任何声音" in positive
    assert "BGM：轻柔干净" not in positive


def test_product_reference_prompt_text_uses_image_numbers_without_urls():
    refs = [
        {"asset_id": "prod_1", "url": "https://example.com/product-1.png"},
        {"asset_id": "prod_2", "url": "https://example.com/product-2.png"},
    ]

    text = _product_reference_text(refs, start_index=5)
    items = _product_reference_prompt_items(refs, start_index=5)

    assert "图片5是用户上传的产品图" in text
    assert "图片6是用户上传的产品图" in text
    assert "https://example.com" not in text
    assert items == [
        {
            "image_no": 5,
            "role": "product_reference",
            "description": "用户上传产品图，只用于锁定产品瓶身、包装、材质、颜色和形态，不是人物图、场地图或 Production Board。",
        },
        {
            "image_no": 6,
            "role": "product_reference",
            "description": "用户上传产品图，只用于锁定产品瓶身、包装、材质、颜色和形态，不是人物图、场地图或 Production Board。",
        },
    ]


def test_reference_prompt_items_describe_roles_without_asset_strings():
    host_items = _host_reference_prompt_items(3)
    audio_items = _audio_reference_prompt_items(2)

    assert [item["image_no"] for item in host_items] == [1, 2, 3]
    assert all(item["role"] == "person_reference" for item in host_items)
    assert "asset://" not in str(host_items)
    assert [item["audio_no"] for item in audio_items] == [1, 2]
    assert all(item["role"] == "voice_reference" for item in audio_items)
    assert "背景音乐" in str(audio_items)
    assert "环境声" in str(audio_items)


@pytest.mark.asyncio
async def test_story_board_reference_urls_keep_app_yaml_asset_refs_unchanged():
    service = TalkingHeadPromptService()
    refs = [
        "asset://asset-20260506200638-6g86k",
        "asset://asset-20260506200638-6g86k",
        "asset://asset-20260506200638-6g86k",
    ]

    urls = await service._resolve_story_board_reference_image_urls(
        "project-1",
        fallback_references=refs,
    )

    assert urls == refs


def test_generated_ulid_still_fits_legacy_id_columns():
    assert len(generate_ulid()) == 26
