"""Poll a Seedance/Ark content generation task by task id.

Usage:
  python scripts/poll_seedance_task.py
  python scripts/poll_seedance_task.py --task-id cgt-20260506172956-kk6mc
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_QUERY_PATH = "/contents/generations/tasks/{task_id}"
DEFAULT_TASK_ID = "cgt-20260506172956-kk6mc"


def load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if load_dotenv is not None:
        load_dotenv(env_path)
        return

    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll Seedance task status by task id.")
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID, help="Seedance task id.")
    parser.add_argument("--interval-sec", type=int, default=30, help="Polling interval in seconds.")
    parser.add_argument("--max-attempts", type=int, default=80, help="Maximum polling attempts.")
    parser.add_argument("--output", default="", help="Optional path to save final JSON response.")
    return parser.parse_args()


def extract_video_url(data: dict[str, Any]) -> str:
    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    video_url = str(content.get("video_url") or "")
    if video_url:
        return video_url

    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    video_url = str(result.get("video_url") or "")
    if video_url:
        return video_url

    items = result.get("data") if isinstance(result.get("data"), list) else []
    if items and isinstance(items[0], dict):
        return str(items[0].get("url") or "")
    return ""


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    load_env()
    args = parse_args()

    api_key = os.getenv("ARK_API_KEY", "").strip()
    base_url = os.getenv("ARK_BASE_URL", ARK_BASE_URL).strip() or ARK_BASE_URL
    if not api_key:
        raise SystemExit("Missing ARK_API_KEY in .env or environment.")

    task_id = args.task_id.strip()
    if not task_id:
        raise SystemExit("Missing --task-id.")

    url = f"{base_url.rstrip('/')}{ARK_QUERY_PATH.format(task_id=task_id)}"
    headers = {"Authorization": f"Bearer {api_key}"}

    print(f"[poll] task_id={task_id}")
    print(f"[poll] url={url}")
    for attempt in range(1, args.max_attempts + 1):
        now = datetime.now().isoformat(timespec="seconds")
        resp = requests.get(url, headers=headers, timeout=60)
        print(f"[{now}] attempt {attempt}/{args.max_attempts} HTTP {resp.status_code}")
        print(resp.text[:2000])

        if resp.status_code != 200:
            time.sleep(args.interval_sec)
            continue

        data = resp.json()
        status = str(data.get("status") or "")
        if status in ("succeeded", "completed"):
            video_url = extract_video_url(data)
            print("[done] task succeeded")
            if video_url:
                print(f"video_url={video_url}")
            if args.output:
                write_json(Path(args.output).expanduser().resolve(), data)
            return 0

        if status == "failed":
            print("[done] task failed")
            error = data.get("error")
            if error:
                print(f"error={json.dumps(error, ensure_ascii=False)}")
            if args.output:
                write_json(Path(args.output).expanduser().resolve(), data)
            return 1

        time.sleep(args.interval_sec)

    print(f"[timeout] task not finished after {args.max_attempts} attempts")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
