from types import SimpleNamespace

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
    _video_host_reference_urls,
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
        layout_reading_map={"segment_2": "只读取导演分镜图中第 2 行 / 15-30s 的画面内容参考、景别、运镜方式和动作节奏"},
    )

    positive = rendered["positive_prompt"]
    negative = rendered["negative_prompt"]

    assert "光希老王" in positive
    assert "图片1是唯一服装与整体造型基准" in positive
    assert "图片2、图片3只用于补充锁定同一角色" in positive
    assert "图片4是完整导演分镜图" in positive
    assert "不要复刻它的表格页面" in positive
    assert "无字幕硬约束" in positive
    assert "画面中绝对不要出现任何可读文字" in positive
    assert "产品瓶身和道具只能作为不可读的视觉符号" in positive
    assert "只读取导演分镜图中第 2 行 / 15-30s" in positive
    assert rendered["reference_image_urls"][3] == "https://example.com/board.png"
    assert rendered["params"]["watermark"] is False
    assert "clean visual reference" not in positive
    assert "声音硬约束" in positive
    assert "最终视频只需要中文说话人声" in positive
    assert "背景音乐" in negative
    assert "环境声" in negative
    assert "音效" in negative
    assert "换装" in negative
    assert "改性别" in negative
    assert "照抄导演分镜图乱码文字" in negative


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
    assert "图片4是完整导演分镜图" in positive
    assert "无字幕硬约束" in positive
    assert "台词只能通过人物声音、口型和表演传达" in positive
    assert "声音硬约束" in positive
    assert "不要背景音乐" in positive
    assert "改性别" in negative
    assert "服装漂移" in negative
    assert "从图片2或图片3引入新服装" in negative
    assert "读取其他 Segment" in negative
    assert "CTA文字" in negative
    assert "可读文字" in negative

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


def test_video_host_reference_urls_preserve_config_asset_urls():
    urls = _video_host_reference_urls(
        [
            " asset://asset-person-1 ",
            "asset://asset-person-2",
            "",
            "asset://asset-person-3",
            "asset://asset-person-extra",
        ]
    )

    assert urls == [
        "asset://asset-person-1",
        "asset://asset-person-2",
        "asset://asset-person-3",
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
    assert "导演分镜流程图 / Director Shot List" in positive
    assert "画面内容参考图必须是该行最大的视觉区域" in positive
    assert "遮挡式无五官占位主持人" in positive
    assert "浅色空白面罩" in positive
    assert "无五官遮挡层" in positive
    assert "头身比例" in positive
    assert "眼镜外轮廓" in positive
    assert "不要生成有五官的脸" in positive
    assert "脸部无遮挡" in rendered["image_negative_prompt"]
    assert "上传参考图本人脸" in rendered["image_negative_prompt"]
    assert "只读取导演分镜图中第 1 行" in str(rendered["layout_reading_map"])
    assert "图片3是用户上传的产品图" not in positive
    assert "图片4是用户上传的产品图" not in positive
    assert "https://example.com" not in positive
    assert "人声之外不需要任何声音" in positive
    assert "BGM：轻柔干净" not in positive


def test_story_overview_board_prompt_uses_uploaded_scene_reference_over_text_scene():
    rendered = _build_story_overview_board_prompt(
        spec=SimpleNamespace(
            user_prompt="光希玻色因面霜",
            output_config={"target_duration_sec": 15},
        ),
        brief_payload={
            "title": "光希玻色因面霜",
            "set_design_profile": "现代护肤科普工作室。暖灰色或浅米色背景。",
        },
        style_payload={},
        narrative_payload={
            "shots": [
                {
                    "scene_description": "现代护肤科普工作室。暖灰色或浅米色背景。",
                    "dialogue": "先看浓度。再看耐受。",
                }
            ]
        },
        host_assets=["https://example.com/person-1.png"],
        audio_assets=[],
        scene_asset_url="https://example.com/scene.png",
        product_refs=[],
    )

    positive = rendered["image_positive_prompt"]

    assert "图片4：场地参考图，只用于锁定统一空间环境、桌面布局、背景材质、光线和氛围，不是人物图或产品图。" in positive
    assert "以图片4场地参考图为准" in positive
    assert "不要用文字场景设定覆盖图片4里的真实空间" in positive
    assert "画面内容参考图：沿用图片4场地参考图锁定的统一空间环境" in positive
    assert "场景：以图片4场地参考图为准" in positive
    assert "统一场景：\n现代护肤科普工作室" not in positive
    assert "画面内容参考图：现代护肤科普工作室" not in positive


def test_story_overview_board_prompt_keeps_text_scene_when_no_scene_reference():
    rendered = _build_story_overview_board_prompt(
        spec=SimpleNamespace(
            user_prompt="光希玻色因面霜",
            output_config={"target_duration_sec": 15},
        ),
        brief_payload={
            "title": "光希玻色因面霜",
            "set_design_profile": "现代护肤科普工作室。暖灰色或浅米色背景。",
        },
        style_payload={},
        narrative_payload={"shots": [{"dialogue": "先看浓度。再看耐受。"}]},
        host_assets=["https://example.com/person-1.png"],
        audio_assets=[],
        scene_asset_url=None,
        product_refs=[],
    )

    positive = rendered["image_positive_prompt"]

    assert "统一场景：\n现代护肤科普工作室。暖灰色或浅米色背景。" in positive
    assert "画面内容参考图：现代护肤科普工作室。暖灰色或浅米色背景。" in positive
    assert "场景：护肤科普工作室" in positive
    assert "以图片4场地参考图为准" not in positive


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
            "description": "用户上传产品图，只用于锁定产品瓶身、包装、材质、颜色和形态，不是人物图、场地图或导演分镜图。",
        },
        {
            "image_no": 6,
            "role": "product_reference",
            "description": "用户上传产品图，只用于锁定产品瓶身、包装、材质、颜色和形态，不是人物图、场地图或导演分镜图。",
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


def test_generated_ulid_still_fits_legacy_id_columns():
    assert len(generate_ulid()) == 26
