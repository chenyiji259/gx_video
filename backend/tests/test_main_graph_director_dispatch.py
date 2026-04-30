import pytest

from app.workflows import main_graph


def test_route_after_director_no_longer_routes_text_generation_nodes():
    brief_state = {
        "project_snapshot": {"current_stage": "audio_analyzed"},
        "next_action": "generate_brief",
        "style_direction": "style_cinematic",
    }
    narrative_state = {
        "project_snapshot": {"current_stage": "brief_ready"},
        "brief_confirmed": True,
    }
    shot_plan_state = {
        "project_snapshot": {"current_stage": "visual_bible_ready"},
        "visual_bible_confirmed": True,
    }

    assert main_graph._route_after_director(brief_state) == "respond_to_user"
    assert main_graph._route_after_director(narrative_state) == "respond_to_user"
    assert main_graph._route_after_director(shot_plan_state) == "respond_to_user"


@pytest.mark.asyncio
async def test_director_intake_auto_dispatches_text_actions(monkeypatch):
    class FakeDirectorAgent:
        async def run(self, state):
            return {
                "mode": "report",
                "message": "叙事剧本已生成，请确认叙事方向。",
                "intent": "request_narrative_confirmation",
                "next_action": "request_narrative_confirmation",
                "options": [{"id": "confirm", "title": "确认并继续"}],
                "dispatch_result": {
                    "artifact_ref": {
                        "artifact_id": "narrative_script_v1",
                        "artifact_type": "narrative_script",
                        "local_path": "data/projects/p1/03_brief/narrative_script_v1.json",
                        "version_no": 1,
                        "summary": "3 个角色，4 个场景",
                    },
                    "version_no": 1,
                    "character_count": 3,
                    "scene_count": 4,
                    "section_count": 5,
                },
            }

    async def fake_create_decision_for_action(**kwargs):
        assert kwargs["next_action"] == "request_narrative_confirmation"
        return {"decision_id": "dec_001", "status": "open"}

    monkeypatch.setattr(main_graph, "DirectorAgent", FakeDirectorAgent)
    monkeypatch.setattr(main_graph, "create_decision_for_action", fake_create_decision_for_action)

    state = {
        "project_id": "p1",
        "user_id": "u1",
        "session_id": "s1",
        "history": [],
        "project_snapshot": {"current_stage": "brief_ready"},
        "system_trigger": None,
    }

    result = await main_graph.director_intake(state)

    assert result["assistant_message"] == "叙事剧本已生成，请确认叙事方向。"
    assert result["requires_confirmation"] is True
    assert result["next_action"] is None
    assert result["pending_decision_id"] == "dec_001"
    assert result["artifact_ref_for_review"]["artifact_id"] == "narrative_script_v1"
