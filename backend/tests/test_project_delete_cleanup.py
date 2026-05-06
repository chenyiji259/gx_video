import pytest

from app.services.project_service import _delete_project_dependent_rows


class RecordingSession:
    def __init__(self) -> None:
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)


@pytest.mark.asyncio
async def test_delete_project_dependent_rows_clears_restrict_tables_first():
    session = RecordingSession()

    await _delete_project_dependent_rows(session, "project_01")

    deleted_tables = [statement.table.name for statement in session.statements]

    assert deleted_tables == [
        "timeline_segments",
        "export_versions",
        "storyboard_frames",
        "clip_versions",
        "timeline_versions",
        "storyboard_versions",
        "audio_analysis_versions",
        "assets",
    ]
