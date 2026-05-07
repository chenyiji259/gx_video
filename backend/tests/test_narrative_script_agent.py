from app.agents.narrative_script_agent import _build_fallback_dialogues


def test_fallback_dialogues_use_spoken_talking_head_style():
    dialogues = _build_fallback_dialogues("讲解视黄醇怎么建立耐受", 3)

    joined = "\n".join(dialogues)

    assert any(line for line in dialogues)
    assert "今天用一分钟带你快速了解" not in joined
    assert "核心原则" not in joined
    assert "正确做法是" not in joined
    assert "少走弯路" not in joined
    assert "不红不刺" in joined
