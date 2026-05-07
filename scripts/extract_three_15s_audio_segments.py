"""Extract audio from a video and split it into three 15-second mp3 segments.

Usage:
  python scripts/extract_three_15s_audio_segments.py
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


DEFAULT_VIDEO = r"C:\Users\CYJ25\Pictures\老王写真图\1748324b6be7235724bf4b383be99f2d.mp4"
DEFAULT_OUTPUT_ROOT = r"C:\Users\CYJ25\Pictures\王总ai 音"
DEFAULT_FFMPEG = r"C:\Users\CYJ25\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract 3 x 15s mp3 audio segments from a video.")
    parser.add_argument("--video", default=DEFAULT_VIDEO, help="Input video path.")
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT, help="Output root directory.")
    parser.add_argument("--ffmpeg", default=os.getenv("FFMPEG_PATH", DEFAULT_FFMPEG), help="ffmpeg executable path.")
    parser.add_argument("--segment-duration", type=float, default=15.0, help="Segment duration in seconds.")
    parser.add_argument("--segments", type=int, default=3, help="Number of segments to export.")
    return parser.parse_args()


def resolve_ffmpeg(path: str) -> str:
    candidate = Path(path)
    if candidate.exists():
        return str(candidate)
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise SystemExit(f"ffmpeg not found: {path}")


def run(cmd: list[str]) -> None:
    print(" ".join(f'"{part}"' if " " in part else part for part in cmd))
    subprocess.run(cmd, check=True)


def make_output_dir(video_path: Path, output_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / f"{video_path.stem}_audio_segments_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def main() -> int:
    args = parse_args()
    ffmpeg = resolve_ffmpeg(args.ffmpeg)
    video_path = Path(args.video).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()

    if not video_path.exists() or not video_path.is_file():
        raise SystemExit(f"Input video not found: {video_path}")
    output_root.mkdir(parents=True, exist_ok=True)

    output_dir = make_output_dir(video_path, output_root)
    full_audio = output_dir / "full_audio.mp3"

    run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "192k",
            "-ar",
            "44100",
            str(full_audio),
        ]
    )

    for index in range(args.segments):
        start = index * args.segment_duration
        segment_path = output_dir / f"{index + 1}.mp3"
        run(
            [
                ffmpeg,
                "-y",
                "-ss",
                f"{start:.3f}",
                "-i",
                str(full_audio),
                "-t",
                f"{args.segment_duration:.3f}",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "192k",
                "-ar",
                "44100",
                str(segment_path),
            ]
        )

    print(f"[done] output_dir={output_dir}")
    print(f"[done] full_audio={full_audio}")
    for index in range(args.segments):
        print(f"[done] segment_{index + 1}={output_dir / f'{index + 1}.mp3'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
