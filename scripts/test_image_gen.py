"""
图片生成 API 测试脚本

测试内容：
  1. z-image         文生图 → 角色（9:16）
  2. z-image         文生图 → 场地（21:9）
  3. qwen-image-2.0-pro 文生图（不传参考图）

使用方式（项目根目录执行）：
    python scripts/test_image_gen.py
"""
import asyncio
import sys
import httpx
import json
import time

# ↓↓↓  填入你的 DashScope API Key  ↓↓↓
API_KEY = "sk-ba814692ccfd49979c27cc7be7d9e512"
# ↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑↑

# ── 颜色输出 ─────────────────────────────────────────────
def ok(msg):   print(f"  \033[32m✓ {msg}\033[0m")
def fail(msg): print(f"  \033[31m✗ {msg}\033[0m")
def info(msg): print(f"  \033[90m  {msg}\033[0m")
def section(t): print(f"\n\033[1m[{t}]\033[0m")
def hr():      print("─" * 56)

ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks"
POLL_INTERVAL = 3.0
POLL_MAX = 40


async def call_api(client: httpx.AsyncClient, api_key: str, payload: dict) -> dict:
    """同步生图请求，直接返回结果（此 API 不支持异步调用）。"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # X-DashScope-Async 不传：该 API 仅支持同步调用
    }
    resp = await client.post(ENDPOINT, json=payload, headers=headers, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"请求失败 HTTP {resp.status_code}: {resp.text[:300]}")

    return resp.json()


def extract_url(data: dict) -> str:
    """从响应中提取图片 URL。"""
    results = data.get("output", {}).get("results", [])
    if results:
        return results[0].get("url", "")
    return data.get("output", {}).get("url", "") or data.get("url", "")


async def test_z_image_character(client, api_key) -> bool:
    """z-image 文生图 → 角色（9:16，1080*1920）"""
    section("z-image  文生图  角色  9:16")
    info("prompt: 一位二十五岁的中国女性，长发，穿着古风汉服，站姿优雅，写实风格")
    info("size: 1080*1920（9:16）")

    payload = {
        "model": "z-image-turbo",
        "input": {
            "messages": [{
                "role": "user",
                "content": [{"text": "一位二十五岁的中国女性，长发飘逸，穿着青色古风汉服，竖姿优雅，面部精致，写实摄影风格，全身像，白色背景"}]
            }]
        },
        "parameters": {"size": "1080*1920", "n": 1},
    }

    t0 = time.perf_counter()
    try:
        result = await call_api(client, api_key, payload)
        url = extract_url(result)
        elapsed = time.perf_counter() - t0
        if url:
            ok(f"生成成功  耗时={elapsed:.1f}s")
            print(f"\n  \033[36m图片 URL：\033[0m")
            print(f"  {url}\n")
            return True
        else:
            fail(f"响应中未找到图片 URL: {json.dumps(result, ensure_ascii=False)[:200]}")
            return False
    except Exception as e:
        fail(f"{e}")
        return False


async def test_z_image_scene(client, api_key) -> bool:
    """z-image 文生图 → 场地（21:9，2048*872）"""
    section("z-image  文生图  场地  21:9")
    info("prompt: 赛博朋克城市夜晚街道，霓虹灯倒影，雨后湿润地面，电影感")
    info("size: 2048*872（21:9 超宽）")

    payload = {
        "model": "z-image-turbo",
        "input": {
            "messages": [{
                "role": "user",
                "content": [{"text": "赛博朋克城市夜晚街道，霸虹灯倒影在雨后湿润地面，远处高楼林立，大气电影感，超宽画幅，无人物"}]
            }]
        },
        "parameters": {"size": "2048*872", "n": 1},
    }

    t0 = time.perf_counter()
    try:
        result = await call_api(client, api_key, payload)
        url = extract_url(result)
        elapsed = time.perf_counter() - t0
        if url:
            ok(f"生成成功  耗时={elapsed:.1f}s")
            print(f"\n  \033[36m图片 URL：\033[0m")
            print(f"  {url}\n")
            return True
        else:
            fail(f"响应中未找到图片 URL")
            return False
    except Exception as e:
        fail(f"{e}")
        return False


async def test_qwen_txt2img(client, api_key) -> bool:
    """qwen-image-2.0-pro 纯文生图（不传参考图）→ 3:4"""
    section("qwen-image-2.0-pro  文生图（无参考图）  3:4")
    info("prompt: 一位穿着旗袍的女性，站在民国风格的弄堂里，黄昏光线")
    info("size: 1080*1440（3:4 竖向）")

    payload = {
        "model": "qwen-image-2.0-pro",
        "input": {
            "messages": [{
                "role": "user",
                "content": [
                    {"text": "一位穿着民国旗袍的优雅女性，站在上海弄堂石库门前，黄昏暖光，电影质感，写实风格"}
                ]
            }]
        },
        "parameters": {"size": "1080*1440", "n": 1},
    }

    t0 = time.perf_counter()
    try:
        result = await call_api(client, api_key, payload)
        url = extract_url(result)
        elapsed = time.perf_counter() - t0
        if url:
            ok(f"生成成功  耗时={elapsed:.1f}s")
            print(f"\n  \033[36m图片 URL：\033[0m")
            print(f"  {url}\n")
            return True
        else:
            fail(f"响应中未找到图片 URL")
            return False
    except Exception as e:
        fail(f"{e}")
        return False


async def main():
    print("=" * 56)
    print("  VidMuse — 图片生成 API 测试")
    print("=" * 56)

    api_key = API_KEY
    if not api_key or api_key.startswith("sk-填入"):
        fail("请先在脚本顶部填入真实的 API_KEY")
        sys.exit(1)

    info(f"API Key: {api_key[:8]}{'*'*20}（已脱敏）")
    info(f"Endpoint: {ENDPOINT}")

    # 三个测试串行执行（避免并发触发限流）
    async with httpx.AsyncClient() as client:
        r1 = await test_z_image_character(client, api_key)
        hr()
        r2 = await test_z_image_scene(client, api_key)
        hr()
        r3 = await test_qwen_txt2img(client, api_key)

    print("\n" + "=" * 56)
    print("  测试结果汇总")
    print("=" * 56)
    print(f"  z-image 角色 9:16          : {'✓ 正常' if r1 else '✗ 失败'}")
    print(f"  z-image 场地 21:9          : {'✓ 正常' if r2 else '✗ 失败'}")
    print(f"  qwen-image-2.0-pro 文生图  : {'✓ 正常' if r3 else '✗ 失败'}")
    print()

    if all([r1, r2, r3]):
        print("\033[32m  生图 API 全部正常 🎨\033[0m\n")
        sys.exit(0)
    else:
        print("\033[31m  存在失败，请检查 API Key 和网络连接\033[0m\n")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
