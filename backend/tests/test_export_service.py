from app.services.export_service import _resolve_export_scale


def test_resolve_export_scale_matches_vertical_project_ratio():
    assert _resolve_export_scale("720p", "9:16") == "720:1280"
    assert _resolve_export_scale("1080p", "9:16") == "1080:1920"


def test_resolve_export_scale_matches_landscape_project_ratio():
    assert _resolve_export_scale("720p", "16:9") == "1280:720"
    assert _resolve_export_scale("1080p", "16:9") == "1920:1080"


def test_resolve_export_scale_supports_square_and_defaults():
    assert _resolve_export_scale("1080p", "1:1") == "1080:1080"
    assert _resolve_export_scale("unknown", None) == "1280:720"
