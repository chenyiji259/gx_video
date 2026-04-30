import asyncio
import httpx
import json

API_KEY = "sk-ba814692ccfd49979c27cc7be7d9e512"

ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

async def main():
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "qwen-image-2.0-pro",
        "input": {
            "messages": [{
                "role": "user",
                "content": [
                    {"text": "一位穿着旅袍的女性，竖向全身像，写实风格"}
                ]
            }]
        },
        "parameters": {"size": "1080*1440", "n": 1},
    }

    print("发送请求...")
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(ENDPOINT, json=payload, headers=headers)

    print(f"HTTP 状态码: {resp.status_code}")
    print("原始响应:")
    print(json.dumps(resp.json(), ensure_ascii=False, indent=2))

asyncio.run(main())
