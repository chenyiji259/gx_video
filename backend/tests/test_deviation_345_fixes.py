import pytest

from app.api.v1.shots import ShotPatchRequest
from app.services.state_transition_service import StateTransitionService
from app.services.visual_bible_service import VisualBibleService
from app.tasks.worker import task_worker


def test_shot_patch_request_accepts_dict_character_binding():
    req = ShotPatchRequest.model_validate(
        {"patch": {"character_binding": {"character_ids": ["char_001"]}}}
    )
    assert req.patch.character_binding == {"character_ids": ["char_001"]}


def test_visual_bible_resolve_character_generation_mode_uses_analysis():
    character = {
        "image_analysis": {"recommended_mode": "direct"},
        "base_face_asset_id": "asset_face",
    }
    assert VisualBibleService._resolve_character_generation_mode(character, None) == "direct"
    assert (
        VisualBibleService._resolve_character_generation_mode(character, "text_to_image")
        == "text_to_image"
    )


def test_worker_registers_costume_handlers():
    assert task_worker.get_handler("generate_costume_ref") is not None
    assert task_worker.get_handler("auto_setup_costumes") is not None


@pytest.mark.asyncio
async def test_mark_shots_by_character_stale_supports_object_binding():
    class FakeSession:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def execute(self, stmt, params):  # noqa: ANN001
            self.calls.append(str(stmt))

    session = FakeSession()
    await StateTransitionService()._mark_shots_by_character_stale(session, "proj_1", "char_001")

    sql = "\n".join(session.calls)
    assert "jsonb_typeof(character_binding) = 'object'" in sql
    assert "jsonb_array_elements_text" in sql
