import pytest

from app.providers.video import seedance_adapter as seedance_module
from app.providers.video.base import VideoResult
from app.providers.video.base import get_video_provider
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
    assert payload["resolution"] == "480p"


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
    assert payload["resolution"] == "480p"


def test_seedance_payload_always_locks_resolution_to_480p():
    adapter = SeedanceAdapter.__new__(SeedanceAdapter)
    adapter._model_name = "doubao-seedance-2-0-260128"

    payload = adapter._build_payload(
        prompt="生成一段测试视频。",
        mode="text_to_video",
        first_frame_url=None,
        last_frame_url=None,
        reference_image_urls=[],
        merged={
            "ratio": "16:9",
            "duration": 8,
            "resolution": "1080p",
            "generate_audio": False,
            "watermark": False,
        },
    )

    assert payload["resolution"] == "480p"


def test_seedance_appends_video_output_constraints_without_negative_prompt():
    merged = SeedanceAdapter._append_video_output_constraints("生成一段口播视频。")

    assert merged.startswith("此视频不生成字幕。最终画面必须纯净无字")
    assert "生成一段口播视频。" in merged
    assert "字幕、水印" not in merged


def test_seedance_http_request_log_formats_prompt_and_redacts_auth(monkeypatch):
    class FakeLogger:
        def __init__(self):
            self.records = []

        def info(self, message, *, event_type=None, **extra):
            self.records.append({
                "message": message,
                "event_type": event_type,
                "extra": extra,
            })

    fake_logger = FakeLogger()
    monkeypatch.setattr(seedance_module, "_logger", fake_logger)

    adapter = SeedanceAdapter.__new__(SeedanceAdapter)
    payload = {
        "model": "doubao-seedance-2-0-260128",
        "content": [
            {
                "type": "text",
                "text": "第一句。第二句！第三句? 不要生成字幕、水印。",
            },
            {
                "type": "image_url",
                "image_url": {"url": "asset://asset-person-1"},
                "role": "reference_image",
            },
        ],
        "ratio": "9:16",
        "duration": 15,
        "resolution": "480p",
        "generate_audio": True,
        "watermark": False,
    }

    adapter._log_http_request_payload(
        url="https://ark.example.com/contents/generations/tasks",
        headers={
            "Authorization": "Bearer real-secret-token",
            "Content-Type": "application/json",
        },
        payload=payload,
    )

    logs = [
        record
        for record in fake_logger.records
        if record["event_type"] == "seedance_http_request_payload"
    ]
    assert len(logs) == 1
    message = logs[0]["message"]
    assert "POST https://ark.example.com/contents/generations/tasks" in message
    assert "real-secret-token" not in message
    assert "Bearer ***" in message
    assert '"image_url": {' in message
    assert "asset://asset-person-1" in message
    assert "prompt_formatted:" in message
    assert "第一句。\n第二句！\n第三句?\n不要生成字幕、水印。" in message
    assert logs[0]["extra"]["headers"]["Authorization"] == "Bearer ***"
    assert logs[0]["extra"]["payload"] == payload


def test_default_seedance_provider_uses_fast_model_from_config():
    adapter = get_video_provider()

    assert isinstance(adapter, SeedanceAdapter)
    assert adapter._provider_name == "seedance_2_fast"
    assert adapter._model_name == "doubao-seedance-2-0-fast-260128"
    assert adapter._default_params["resolution"] == "480p"


@pytest.mark.asyncio
async def test_generate_logs_seedance_request_payload_and_submits_480p(monkeypatch):
    class FakeLogger:
        def __init__(self):
            self.records = []

        def info(self, message, *, event_type=None, **extra):
            self.records.append({
                "message": message,
                "event_type": event_type,
                "extra": extra,
            })

    fake_logger = FakeLogger()
    monkeypatch.setattr(seedance_module, "_logger", fake_logger)

    adapter = SeedanceAdapter.__new__(SeedanceAdapter)
    adapter._api_key = "test-key"
    adapter._model_name = "doubao-seedance-2-0-260128"
    adapter._default_params = {
        "duration": 8,
        "ratio": "9:16",
        "resolution": "1080p",
        "generate_audio": False,
        "watermark": False,
    }

    submitted_payloads = []

    async def fake_submit(payload):
        submitted_payloads.append(payload)
        return "task-1"

    async def fake_poll(task_id):
        return VideoResult(video_url=f"https://example.com/{task_id}.mp4")

    monkeypatch.setattr(adapter, "_submit_task", fake_submit)
    monkeypatch.setattr(adapter, "_poll_task", fake_poll)

    await adapter.generate(
        "生成一段测试视频。",
        mode="text_to_video",
        negative_prompt="字幕，文字贴片",
        params={"resolution": "1080p"},
    )

    assert submitted_payloads[0]["resolution"] == "480p"
    text_prompt = submitted_payloads[0]["content"][0]["text"]
    assert text_prompt.startswith("此视频不生成字幕。最终画面必须纯净无字")
    assert "生成一段测试视频。" in text_prompt
    assert "字幕，文字贴片" not in text_prompt
    assert "负向约束" not in text_prompt
    request_logs = [
        record
        for record in fake_logger.records
        if record["event_type"] == "seedance_request_payload"
    ]
    assert len(request_logs) == 1
    assert "resolution='480p'" in request_logs[0]["message"]
    assert request_logs[0]["extra"]["resolution"] == "480p"
