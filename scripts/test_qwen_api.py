"""
Qwen API 连接测试脚本

测试内容：
  1. qwen3.5-plus    文本模型 — 发送「介绍一下你自己」
  2. qwen3.5-omni-plus Omni模型 — 发送「介绍一下你自己」（纯文本模式）

使用方式（项目根目录执行）：
    python scripts/test_qwen_api.py

前提：.env 文件中已配置 DASHSCOPE_API_KEY
"""
import asyncio
import os
import sys
import time
from pathlib import Path

# ── 加载 .env ────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# ── 将 backend 加入 path ─────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.utils.omni_config import load_omni_config
from app.core.config_loader import load_llm_config

# ── 颜色输出 ─────────────────────────────────────────────
def ok(msg: str)      : print(f"  \033[32m✓ {msg}\033[0m")
def fail(msg: str)    : print(f"  \033[31m✗ {msg}\033[0m")
def info(msg: str)    : print(f"  \033[90m{msg}\033[0m")
def section(title: str): print(f"\n\033[1m[{title}]\033[0m")
def hr()              : print("─" * 52)


# ── 测试 1：qwen3.5-plus 文本模型 ────────────────────────
async def test_text_model() -> bool:
    section("qwen3.5-plus  文本模型")
    cfg = load_llm_config()

    api_key = os.environ.get(cfg.api_key_env, "")
    if not api_key:
        fail(f"API Key 未配置（环境变量 {cfg.api_key_env} 为空），请检查 .env 文件")
        return False

    info(f"endpoint : {cfg.base_url}")
    info(f"model    : {cfg.model}")
    info(f"api_key  : {api_key[:8]}{'*' * 20}  (已脱敏)")

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=cfg.base_url,
            timeout=cfg.timeout,
        )

        print("\n  发送：「你好，请用中文简短介绍一下你自己」\n")
        t0 = time.perf_counter()

        response = await client.chat.completions.create(
            model=cfg.model,
            messages=[{"role": "user", "content": "你好，请用中文简短介绍一下你自己"}],
            temperature=cfg.temperature,
            max_tokens=512,
            extra_body={"enable_thinking": False},   # 关闭思考模式，输出干净文本
        )

        elapsed = time.perf_counter() - t0
        reply = response.choices[0].message.content or ""
        usage = response.usage

        # 打印回复（每行缩进）
        for line in reply.strip().splitlines():
            print(f"  \033[36m{line}\033[0m")

        print()
        ok(
            f"响应成功  耗时={elapsed:.2f}s  "
            f"tokens(in={usage.prompt_tokens} out={usage.completion_tokens})"
        )
        return True

    except Exception as e:
        fail(f"调用失败: {e}")
        return False


# ── 测试 2：qwen3.5-omni-plus Omni 模型（纯文本） ─────────
async def test_omni_model() -> bool:
    section("qwen3.5-omni-plus  Omni 模型（纯文本测试）")
    omni_cfg = load_omni_config()

    api_key_env: str = omni_cfg.get("api_key_env", "DASHSCOPE_API_KEY")
    api_key: str = os.environ.get(api_key_env, "")
    if not api_key:
        fail(f"API Key 未配置（环境变量 {api_key_env} 为空），请检查 .env 文件")
        return False

    model_name: str = omni_cfg.get("model_name", "qwen3.5-omni-plus")
    endpoint: str   = omni_cfg.get("endpoint", "")
    timeout: int    = int(omni_cfg.get("timeout", 120))
    output_modalities: list = omni_cfg.get("output_modalities", ["text"])

    info(f"endpoint : {endpoint}")
    info(f"model    : {model_name}")
    info(f"api_key  : {api_key[:8]}{'*' * 20}  (已脱敏)")
    info(f"output   : {output_modalities}")

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=endpoint,
            timeout=timeout,
        )

        print("\n  发送：「你好，请用中文简短介绍一下你自己的能力」\n")
        t0 = time.perf_counter()

        response = await client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "你好，请用中文简短介绍一下你自己的能力"}],
            temperature=0.3,
            max_tokens=512,
            # Omni 模型需要指定输出模态为 text，否则可能尝试返回音频流
            modalities=output_modalities,
        )

        elapsed = time.perf_counter() - t0
        reply = response.choices[0].message.content or ""
        usage = response.usage

        for line in reply.strip().splitlines():
            print(f"  \033[36m{line}\033[0m")

        print()
        ok(
            f"响应成功  耗时={elapsed:.2f}s  "
            f"tokens(in={usage.prompt_tokens} out={usage.completion_tokens})"
        )
        return True

    except Exception as e:
        fail(f"调用失败: {e}")
        return False


# ── 测试 3：Omni 音频分析（base64 模式） ──────────────────
async def test_omni_audio(audio_path: str, model_override: str = "") -> bool:
    omni_cfg = load_omni_config()
    api_key: str = os.environ.get(omni_cfg.get("api_key_env", "DASHSCOPE_API_KEY"), "")
    if not api_key:
        fail("API Key 未配置")
        return False

    model_name: str = model_override or omni_cfg.get("model_name", "qwen3-omni-flash")
    section(f"Omni 音频分析（base64） — {model_name}")
    info(f"音频文件: {audio_path}")
    endpoint: str   = (omni_cfg.get("endpoint") or "").rstrip("/")
    timeout: int    = int(omni_cfg.get("timeout", 120))

    info(f"endpoint : {endpoint}")
    info(f"model    : {model_name}")
    info(f"api_key  : {api_key[:8]}{'*' * 20}  (已脱敏)")

    # 1. 读取音频文件 → base64
    import base64
    audio_file = Path(audio_path)
    if not audio_file.exists():
        fail(f"文件不存在: {audio_path}")
        return False

    audio_bytes = audio_file.read_bytes()
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    audio_format = audio_file.suffix.lstrip(".").lower() or "mp3"
    # 官方文档要求加 data:;base64, 前缀
    audio_data_uri = f"data:;base64,{audio_b64}"
    info(f"音频大小: {len(audio_bytes)/1024:.1f} KB  格式: {audio_format}")

    # 2. 用 httpx 直调（和生产代码一致）
    import json as _json
    import httpx

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model_name,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": audio_data_uri,
                        "format": audio_format,
                    },
                },
                {"type": "text", "text": "这段音频是什么风格的音乐？请简短介绍 BPM、情绪、主要乐器。"},
            ],
        }],
        "modalities": ["text"],
        "max_tokens": 512,
        "temperature": 0.3,
        "stream": True,
        "stream_options": {"include_usage": False},
    }

    print("\n  正在调用，请稍候...\n")
    t0 = time.perf_counter()

    try:
        parts: list[str] = []
        async with httpx.AsyncClient(timeout=float(timeout)) as client:
            async with client.stream("POST", f"{endpoint}/chat/completions",
                                     headers=headers, json=body) as resp:
                if not resp.is_success:
                    body_bytes = await resp.aread()
                    fail(f"HTTP {resp.status_code}: {body_bytes.decode(errors='replace')[:400]}")
                    return False
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(data_str)
                        content = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content") or ""
                        )
                        if content:
                            parts.append(content)
                    except _json.JSONDecodeError:
                        pass

        elapsed = time.perf_counter() - t0
        reply = "".join(parts)
        print()
        for line in reply.strip().splitlines():
            print(f"  \033[36m{line}\033[0m")
        print()
        ok(f"音频分析成功  耗时={elapsed:.2f}s  输出字数≈{len(reply)}")
        return True

    except Exception as e:
        fail(f"调用失败: {e}")
        return False


# ── 主入口 ───────────────────────────────────────────────
async def main() -> None:
    print("=" * 52)
    print("  VidMuse — Qwen API 连接测试")
    print("=" * 52)

    audio_path = r"C:\Users\Administrator\Downloads\Hiko - We R Who We R (Remix) (1).mp3"

    text_ok   = await test_text_model()
    hr()
    omni_ok   = await test_omni_model()
    hr()
    audio_ok  = await test_omni_audio(audio_path)                              # 用 omni.yaml 配置的模型
    hr()
    audio_ok2 = await test_omni_audio(audio_path, model_override="qwen3.5-omni-flash")  # 强制测 3.5-flash
    hr()
    audio_ok3 = await test_omni_audio(audio_path, model_override="qwen3.5-omni-plus")   # 强制测 plus

    print("\n" + "=" * 52)
    print("  测试结果汇总")
    print("=" * 52)
    print(f"  文本模型                       : {'✓ 正常' if text_ok   else '✗ 失败'}")
    print(f"  Omni 纯文本                   : {'✓ 正常' if omni_ok   else '✗ 失败'}")
    print(f"  Omni 音频 (qwen3-omni-flash)      : {'✓ 正常' if audio_ok  else '✗ 失败'}")
    print(f"  Omni 音频 (qwen3.5-omni-flash)    : {'✓ 正常' if audio_ok2 else '✗ 失败'}")
    print(f"  Omni 音频 (qwen3.5-omni-plus)     : {'✓ 正常' if audio_ok3 else '✗ 失败 (可能需白名单)'}") 
    print()

    if text_ok and omni_ok and audio_ok:
        print("\033[32m  核心模型均通过 🎉\033[0m\n")
        sys.exit(0)
    else:
        print("\033[31m  存在失败项，请检查 DASHSCOPE_API_KEY 及模型权限\033[0m\n")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
