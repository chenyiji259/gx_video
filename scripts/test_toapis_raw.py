"""ToAPIs 原始 HTTP 测试 - 只打印原始数据"""

import json
import time
import requests

API_KEY  = "sk-Ac1jmsMbZdhgQCLHcuwdQ4CMyO7XFmXpzyV7OsdQorUxjDnZ"
BASE_URL = "https://toapis.com"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

BODY = {
    "model": "grok-video-3",
    "prompt": "A musician playing guitar on a rooftop at sunset, cinematic slow motion",
    "duration": 10,
    "aspect_ratio": "16:9",
    "metadata": {"resolution": "720P"},
}

# ── 发起任务 ──────────────────────────────────────────────────────────
print("=" * 60)
print(f"POST {BASE_URL}/v1/videos/generations")
print("\n[请求体]")
print(json.dumps(BODY, ensure_ascii=False, indent=2))

resp = requests.post(
    f"{BASE_URL}/v1/videos/generations",
    json=BODY,
    headers=HEADERS,
    timeout=30,
)

print(f"\n[HTTP {resp.status_code}]")
print("[原始响应]")
print(json.dumps(resp.json(), ensure_ascii=False, indent=2))

task_id = resp.json().get("id")
print(f"\ntask_id = {task_id}")

if not task_id:
    print("未获取到 task_id，退出")
    exit(1)

# ── 轮询 ─────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("开始轮询，首次等待 5s ...")
time.sleep(5)

attempt = 0
while True:
    attempt += 1
    poll_url = f"{BASE_URL}/v1/videos/generations/{task_id}"
    r = requests.get(poll_url, headers=HEADERS, timeout=15)

    print(f"\n[轮询 #{attempt}] HTTP {r.status_code}")
    data = r.json()
    print(json.dumps(data, ensure_ascii=False, indent=2))

    status = data.get("status")
    if status in ("completed", "failed"):
        print(f"\n终态: {status}")
        break

    print(f"status={status!r}，10s 后继续...")
    time.sleep(10)
