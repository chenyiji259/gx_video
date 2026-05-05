from pathlib import Path

from app.tools.ffmpeg_timeline_tool import FFmpegTimelineTool


def test_resolve_target_size_defaults_to_vertical():
    assert FFmpegTimelineTool._resolve_target_size("9:16") == (1080, 1920)
    assert FFmpegTimelineTool._resolve_target_size(None) == (1080, 1920)


def test_resolve_target_size_supports_common_ratios():
    assert FFmpegTimelineTool._resolve_target_size("16:9") == (1920, 1080)
    assert FFmpegTimelineTool._resolve_target_size("1:1") == (1080, 1080)


def test_concat_filter_normalizes_mixed_clip_sizes(monkeypatch, tmp_path):
    captured: dict[str, list[str]] = {}

    async def fake_run_ffmpeg(cmd: list[str], step: str) -> None:
        captured["cmd"] = cmd
        captured["step"] = [step]

    monkeypatch.setattr(FFmpegTimelineTool, "_run_ffmpeg", staticmethod(fake_run_ffmpeg))

    tool = FFmpegTimelineTool()
    clip_paths = [
        Path("clip_landscape.mp4"),
        Path("clip_portrait.mp4"),
    ]

    import asyncio

    asyncio.run(
        tool._concat_and_mix(
            "ffmpeg",
            clip_paths,
            None,
            tmp_path / "preview.mp4",
            0.0,
            "9:16",
        )
    )

    filter_complex = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert captured["step"] == ["concat_mix"]
    assert "scale=1080:1920:force_original_aspect_ratio=decrease" in filter_complex
    assert "pad=1080:1920:(ow-iw)/2:(oh-ih)/2" in filter_complex
    assert "setsar=1,fps=24,format=yuv420p" in filter_complex
    assert "concat=n=2:v=1:a=0[vcat]" in filter_complex
