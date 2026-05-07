import pytest

from app.providers.image.gpt_image_adapter import GPTImageAdapter, _resolve_request_shape


def test_gpt_image_shape_supports_talking_head_21_9_4k_board():
    size, resolution, orientation = _resolve_request_shape(
        {
            "aspect_ratio": "21:9",
            "size": "21:9",
            "resolution": "4K",
        }
    )

    assert size == "21:9"
    assert resolution == "4K"
    assert orientation == "landscape"


@pytest.mark.asyncio
async def test_gpt_image_multi_ref_uses_provider_reference_limit(monkeypatch):
    adapter = GPTImageAdapter()
    captured = {}

    async def fake_submit_and_poll(*, prompt, params, reference_images):
        captured["reference_images"] = reference_images
        return None

    monkeypatch.setattr(adapter, "_submit_and_poll", fake_submit_and_poll)

    await adapter.generate_multi_ref_img2img(
        prompt="test prompt",
        image_urls=[f"https://example.com/ref-{idx}.png" for idx in range(8)],
    )

    assert captured["reference_images"] == [
        "https://example.com/ref-0.png",
        "https://example.com/ref-1.png",
        "https://example.com/ref-2.png",
        "https://example.com/ref-3.png",
        "https://example.com/ref-4.png",
        "https://example.com/ref-5.png",
        "https://example.com/ref-6.png",
    ]
