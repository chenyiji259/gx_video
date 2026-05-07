from types import SimpleNamespace

from app.services.prompt_compiler_service import _derive_audio_direction_text


def test_audio_direction_is_voice_only_without_bgm_or_ambient_plan():
    text = _derive_audio_direction_text(
        brief=SimpleNamespace(raw_payload={"title": "护肤科普"}),
        shot=SimpleNamespace(dialogue="大家好，今天讲抗皱。"),
        spec=SimpleNamespace(user_prompt="口播科普", output_config={}),
    )

    assert "声音硬约束" in text
    assert "只允许中文说话人声" in text
    assert "不要背景音乐" in text
    assert "背景音策略" not in text
    assert "背景音应" not in text
    assert "背景音可" not in text
    assert "氛围音" not in text
