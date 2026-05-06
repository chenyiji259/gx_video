import pytest

from app.workflows import main_graph


@pytest.mark.asyncio
async def test_director_intake_system_trigger_uses_unified_mode_b(monkeypatch):
    class FakeDirectorAgent:
        async def run(self, state):
            assert state["system_trigger"]["task_type"] == "generate_brief"
            return {
                "mode": "report",
                "message": "创意方案已生成，请确认 brief。",
                "intent": "request_brief_confirmation",
                "next_action": "request_brief_confirmation",
                "options": [{"id": "confirm", "title": "确认并继续"}],
            }

    async def fake_create_decision_for_action(**kwargs):
        assert kwargs["next_action"] == "request_brief_confirmation"
        assert kwargs["project_id"] == "p1"
        return {"decision_id": "dec_brief_001", "status": "open"}

    monkeypatch.setattr(main_graph, "DirectorAgent", FakeDirectorAgent)
    monkeypatch.setattr(main_graph, "create_decision_for_action", fake_create_decision_for_action)

    state = {
        "project_id": "p1",
        "user_id": "u1",
        "session_id": "s1",
        "history": [],
        "project_snapshot": {"current_stage": "brief_ready"},
        "system_trigger": {
            "type": "task_completed",
            "task_type": "generate_brief",
            "result": {"brief_version_no": 1},
        },
        "artifact_ref_for_review": {
            "artifact_id": "creative_brief_v1",
            "artifact_type": "creative_brief",
            "version_no": 1,
            "local_path": "data/projects/p1/03_brief/creative_brief_v1.json",
        },
    }

    result = await main_graph.director_intake(state)

    assert result["assistant_message"] == "创意方案已生成，请确认 brief。"
    assert result["requires_confirmation"] is True
    assert result["next_action"] is None
    assert result["pending_decision_id"] == "dec_brief_001"
    assert result["decision_options"] == [{"id": "confirm", "title": "确认并继续"}]


@pytest.mark.asyncio
async def test_director_intake_mode_b_does_not_execute_generation_actions(monkeypatch):
    class FakeDirectorAgent:
        async def run(self, state):
            assert state["system_trigger"]["task_type"] == "generate_storyboard"
            return {
                "mode": "report",
                "message": "关键帧已生成，请确认后再开始视频生成。",
                "intent": "storyboard_completed",
                "next_action": "generate_clips",
                "requires_confirmation": False,
            }

    monkeypatch.setattr(main_graph, "DirectorAgent", FakeDirectorAgent)

    state = {
        "project_id": "p1",
        "user_id": "u1",
        "session_id": "s1",
        "history": [],
        "project_snapshot": {"current_stage": "storyboard_ready"},
        "system_trigger": {
            "type": "task_completed",
            "task_type": "generate_storyboard",
            "result": {"version_no": 1},
        },
    }

    result = await main_graph.director_intake(state)

    assert result["assistant_message"] == "关键帧已生成，请确认后再开始视频生成。"
    assert result["requires_confirmation"] is False
    assert result["next_action"] is None
    assert result["pending_decision_id"] is None
