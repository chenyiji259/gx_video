"""ToApis GPT Image 2 九宫格生图 + 本地切分测试脚本。

用途：
  1. 直接 HTTP 请求 ToApis GPT Image 2 生一张适合 3x3 切分的图片。
  2. 轮询任务直到 completed。
  3. 下载返回 URL 的图片到本地。
  4. 用 PIL 切成 3x3 九宫格 cell，并额外保存 1024x1024 上采样版本。

运行前：
  - 在项目根目录 .env 中配置 TOAPIS_API_KEY。
  - 如缺 Pillow：pip install pillow

示例：
  python scripts/test_gpt_image2_grid_split.py
  python scripts/test_gpt_image2_grid_split.py --preset square_2k
  python scripts/test_gpt_image2_grid_split.py --preset vertical_2k
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少 Pillow，请先执行：pip install pillow") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "toapis_gpt_image2_grid_test"

TOAPIS_BASE_URL = "https://toapis.com"
SUBMIT_URL = f"{TOAPIS_BASE_URL}/v1/images/generations"
POLL_URL_TEMPLATE = f"{TOAPIS_BASE_URL}/v1/images/generations/{{task_id}}"

DEFAULT_PROMPT = """
A clean 3x3 grid of nine sequential cinematic storyboard frames, one complete
image containing exactly nine separate panels arranged in three rows and three
columns. Each panel shows a continuous story about an independent musician
walking from a small bedroom studio to a neon city rooftop stage at night.
Keep the same main character in all nine panels: young Chinese indie musician,
short black hair, black jacket, white T-shirt, carrying a silver guitar.
Clear panel borders, no text, no captions, cinematic lighting, detailed faces,
consistent character, high contrast, music video storyboard.
""".strip()

PRESETS: dict[str, dict[str, str]] = {
    # 每个尺寸都能被 3 整除，保证九宫格 cell 无余数。
    "square_2k": {
        "size": "3072x3072",
        "resolution": "2K",
        "orientation": "square",
        "note": "每格 1024x1024，最适合九宫格切分",
    },
    "vertical_2k": {
        "size": "1728x3072",
        "resolution": "2K",
        "orientation": "portrait",
        "note": "每格 576x1024，适合竖屏项目",
    },
    "horizontal_2k": {
        "size": "3072x1728",
        "resolution": "2K",
        "orientation": "landscape",
        "note": "每格 1024x576，适合横屏项目",
    },
}


def load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if load_dotenv is not None:
        load_dotenv(env_path)
        return

    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def post_generation_task(
    api_key: str,
    prompt: str,
    size: str,
    resolution: str,
    orientation: str,
) -> str:
    payload = {
        "model": "gpt-image-2",
        "prompt": prompt,
        "n": 1,
        "size": size,
        "response_format": "url",
        "metadata": {
            "orientation": orientation,
            "resolution": resolution,
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print(f"[1/5] POST {SUBMIT_URL}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    resp = requests.post(SUBMIT_URL, json=payload, headers=headers, timeout=60)
    print(f"[submit] HTTP {resp.status_code}")
    print(resp.text[:2000])
    resp.raise_for_status()

    data = resp.json()
    task_id = data.get("id")
    if not task_id:
        raise RuntimeError(f"ToApis 未返回任务 id: {data}")
    return str(task_id)


def poll_generation_task(
    api_key: str,
    task_id: str,
    *,
    poll_interval_sec: int,
    max_attempts: int,
) -> str:
    headers = {"Authorization": f"Bearer {api_key}"}
    poll_url = POLL_URL_TEMPLATE.format(task_id=task_id)

    print(f"[2/5] poll task_id={task_id}")
    time.sleep(2)

    for attempt in range(1, max_attempts + 1):
        resp = requests.get(poll_url, headers=headers, timeout=30)
        print(f"[poll {attempt}/{max_attempts}] HTTP {resp.status_code}")
        print(resp.text[:1200])
        resp.raise_for_status()

        data = resp.json()
        status = data.get("status")
        if status == "completed":
            image_url = extract_image_url(data)
            print(f"[completed] image_url={image_url}")
            return image_url
        if status == "failed":
            raise RuntimeError(f"ToApis 任务失败: {json.dumps(data, ensure_ascii=False)}")

        time.sleep(poll_interval_sec)

    raise TimeoutError(f"轮询超时：{max_attempts} 次仍未完成")


def extract_image_url(data: dict[str, Any]) -> str:
    result = data.get("result") or {}
    images = result.get("data") or []
    if images and isinstance(images[0], dict) and images[0].get("url"):
        return str(images[0]["url"])

    # 兼容可能的备用返回形态。
    if result.get("url"):
        return str(result["url"])
    data_list = data.get("data") or []
    if data_list and isinstance(data_list[0], dict) and data_list[0].get("url"):
        return str(data_list[0]["url"])

    raise RuntimeError(f"completed 响应中没有图片 URL: {json.dumps(data, ensure_ascii=False)}")


def download_image(image_url: str, output_dir: Path) -> Path:
    print(f"[3/5] download image: {image_url}")
    resp = requests.get(image_url, timeout=120)
    resp.raise_for_status()

    suffix = ".png"
    content_type = resp.headers.get("content-type", "").lower()
    if "jpeg" in content_type or "jpg" in content_type:
        suffix = ".jpg"
    elif "webp" in content_type:
        suffix = ".webp"

    original_path = output_dir / f"original{suffix}"
    original_path.write_bytes(resp.content)
    print(f"[saved] {original_path}")
    return original_path


def parse_dimensions(size: str) -> tuple[int, int]:
    parts = size.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"size 格式非法: {size!r}，应为 3072x3072 这种像素尺寸")
    width = int(parts[0].strip())
    height = int(parts[1].strip())
    return width, height


def validate_grid_size(size: str) -> tuple[int, int, int, int]:
    width, height = parse_dimensions(size)
    if width % 3 != 0 or height % 3 != 0:
        raise ValueError(
            f"size={size!r} 不能被 3x3 九宫格整除，"
            f"请使用像 3072x3072 / 1728x3072 / 3072x1728 这样的尺寸"
        )
    return width, height, width // 3, height // 3


def split_grid(original_path: Path, output_dir: Path, upscale_size: int) -> None:
    print("[4/5] split 3x3 cells")
    raw_dir = output_dir / "cells_raw"
    upscaled_dir = output_dir / f"cells_upscaled_{upscale_size}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    upscaled_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(original_path) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")
        width, height = img.size
        cell_w = width // 3
        cell_h = height // 3

        print(f"[image] size={width}x{height}, raw_cell={cell_w}x{cell_h}")

        upscaled_cells: list[Image.Image] = []
        for pos in range(1, 10):
            row = (pos - 1) // 3
            col = (pos - 1) % 3
            box = (
                col * cell_w,
                row * cell_h,
                (col + 1) * cell_w,
                (row + 1) * cell_h,
            )
            cell = img.crop(box)
            raw_path = raw_dir / f"cell_{pos:02d}_{cell_w}x{cell_h}.png"
            cell.save(raw_path)

            upscaled = cell.resize((upscale_size, upscale_size), Image.Resampling.LANCZOS)
            draw = ImageDraw.Draw(upscaled)
            draw.rectangle((0, 0, upscale_size - 1, upscale_size - 1), outline=(255, 255, 255), width=2)
            draw.text((16, 16), f"cell {pos}", fill=(255, 255, 255))
            upscaled_path = upscaled_dir / f"cell_{pos:02d}_{upscale_size}x{upscale_size}.png"
            upscaled.save(upscaled_path)
            upscaled_cells.append(upscaled)

        contact_path = output_dir / f"contact_sheet_upscaled_{upscale_size}.png"
        make_contact_sheet(upscaled_cells, contact_path, upscale_size)

    print(f"[saved] raw cells: {raw_dir}")
    print(f"[saved] upscaled cells: {upscaled_dir}")
    print(f"[saved] contact sheet: {contact_path}")


def make_contact_sheet(cells: list[Image.Image], output_path: Path, cell_size: int) -> None:
    sheet = Image.new("RGB", (cell_size * 3, cell_size * 3), (0, 0, 0))
    for i, cell in enumerate(cells):
        row = i // 3
        col = i % 3
        sheet.paste(cell, (col * cell_size, row * cell_size))
    sheet.save(output_path)


def write_metadata(
    output_dir: Path,
    *,
    task_id: str,
    image_url: str,
    prompt: str,
    size: str,
    resolution: str,
) -> None:
    meta = {
        "task_id": task_id,
        "image_url": image_url,
        "model": "gpt-image-2",
        "size": size,
        "resolution": resolution,
        "prompt": prompt,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GPT Image 2 九宫格生图与切分测试")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="生图 prompt")
    parser.add_argument(
        "--preset",
        default="square_2k",
        choices=sorted(PRESETS.keys()),
        help="九宫格尺寸预设",
    )
    parser.add_argument("--size", default="", help="自定义像素尺寸，例如 3072x3072")
    parser.add_argument("--resolution", default="", help="自定义分辨率标签，例如 2K / 4K")
    parser.add_argument("--orientation", default="", help="自定义方向标签，例如 square / portrait / landscape")
    parser.add_argument("--output-dir", default="", help="输出目录，默认 data/toapis_gpt_image2_grid_test/run_时间戳")
    parser.add_argument("--poll-interval-sec", type=int, default=5, help="轮询间隔秒数")
    parser.add_argument("--max-attempts", type=int, default=60, help="最大轮询次数")
    parser.add_argument("--upscale-size", type=int, default=1024, help="cell 上采样边长")
    return parser.parse_args()


def main() -> int:
    load_env()
    args = parse_args()

    api_key = os.getenv("TOAPIS_API_KEY", "").strip()
    if not api_key:
        print("缺少 TOAPIS_API_KEY，请先在项目根目录 .env 配置。", file=sys.stderr)
        return 2

    preset = PRESETS[args.preset]
    size = args.size or preset["size"]
    resolution = args.resolution or preset["resolution"]
    orientation = args.orientation or preset["orientation"]
    declared_w, declared_h, declared_cell_w, declared_cell_h = validate_grid_size(size)

    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = DEFAULT_OUTPUT_ROOT / f"run_{ts}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[preset] {args.preset} | size={size} | resolution={resolution} | "
        f"orientation={orientation} | expected_cell={declared_cell_w}x{declared_cell_h}"
    )
    print(f"[note] {preset['note']}")

    task_id = post_generation_task(api_key, args.prompt, size, resolution, orientation)
    image_url = poll_generation_task(
        api_key,
        task_id,
        poll_interval_sec=args.poll_interval_sec,
        max_attempts=args.max_attempts,
    )
    original_path = download_image(image_url, output_dir)
    split_grid(original_path, output_dir, args.upscale_size)
    write_metadata(
        output_dir,
        task_id=task_id,
        image_url=image_url,
        prompt=args.prompt,
        size=size,
        resolution=resolution,
    )

    print("[5/5] done")
    print(f"输出目录：{output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
