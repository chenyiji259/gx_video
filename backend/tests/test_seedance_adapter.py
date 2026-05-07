from app.providers.video.seedance_adapter import SeedanceAdapter


def test_multi_image_fusion_payload_marks_images_as_reference_images():
    adapter = SeedanceAdapter.__new__(SeedanceAdapter)
    adapter._model_name = "doubao-seedance-2-0-260128"

    payload = adapter._build_payload(
        prompt="首帧为图片1，中间参考图片2，尾帧参考图片3。",
        mode="multi_image_fusion",
        first_frame_url=None,
        last_frame_url=None,
        reference_image_urls=[
            "https://example.com/1.png",
            "https://example.com/2.png",
            "https://example.com/3.png",
        ],
        merged={
            "ratio": "9:16",
            "duration": 5,
            "resolution": "1080p",
            "generate_audio": True,
            "watermark": False,
        },
    )

    image_contents = [
        item for item in payload["content"] if item["type"] == "image_url"
    ]
    assert len(image_contents) == 3
    assert [item["role"] for item in image_contents] == [
        "reference_image",
        "reference_image",
        "reference_image",
    ]


def test_payload_marks_audio_as_reference_audio():
    adapter = SeedanceAdapter.__new__(SeedanceAdapter)
    adapter._model_name = "doubao-seedance-2-0-260128"

    payload = adapter._build_payload(
        prompt="参考音频1的声色，生成口播视频。",
        mode="multi_image_fusion",
        first_frame_url=None,
        last_frame_url=None,
        reference_image_urls=[
            "https://example.com/host-1.png",
            "https://example.com/host-2.png",
            "https://example.com/board.png",
        ],
        reference_audio_urls=["https://example.com/voice.wav"],
        merged={
            "ratio": "9:16",
            "duration": 15,
            "resolution": "1080p",
            "generate_audio": True,
            "watermark": False,
        },
    )

    audio_contents = [
        item for item in payload["content"] if item["type"] == "audio_url"
    ]
    assert len(audio_contents) == 1
    assert audio_contents[0]["role"] == "reference_audio"
    assert audio_contents[0]["audio_url"]["url"] == "https://example.com/voice.wav"
