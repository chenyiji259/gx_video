from app.providers.image.gpt_image_adapter import _resolve_request_shape


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
