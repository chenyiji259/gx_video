"""Concatenate 1shot/2shot/3shot into one 45-second video with local ffmpeg.

Usage:
  python scripts/concat_three_shots_ffmpeg.py
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


DEFAULT_INPUTS = [
    r"C:\Users\CYJ25\Downloads\1shot.mp4",
    r"C:\Users\CYJ25\Downloads\2shot.mp4",
    r"C:\Users\CYJ25\Downloads\3shot.mp4",
]
DEFAULT_OUTPUT = r"C:\Users\CYJ25\Downloads\123shot_45s.mp4"
DEFAULT_FFMPEG = r"C:\Users\CYJ25\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Concat 1shot/2shot/3shot into one 45s video.")
    parser.add_argument("--inputs", nargs=3, default=DEFAULT_INPUTS, help="Three input mp4 files.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output mp4 path.")
    parser.add_argument("--ffmpeg", default=os.getenv("FFMPEG_PATH", DEFAULT_FFMPEG), help="ffmpeg executable path.")
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


def main() -> int:
    args = parse_args()
    ffmpeg = resolve_ffmpeg(args.ffmpeg)

    input_paths = [Path(p).expanduser().resolve() for p in args.inputs]
    for path in input_paths:
        if not path.exists() or not path.is_file():
            raise SystemExit(f"Input file not found: {path}")

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    work_dir = output_path.parent / f"{output_path.stem}_concat_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    concat_list = work_dir / "concat_list.txt"
    concat_list.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in input_paths),
        encoding="utf-8",
    )

    run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )

    print(f"[done] {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
