r"""Minimal Aliyun DashScope CosyVoice TTS HTTP smoke test.

Usage:
    $env:SystemRoot='C:\Windows'
    $env:windir='C:\Windows'
    $env:COMSPEC='C:\Windows\System32\cmd.exe'
    $env:DASHSCOPE_API_KEY='your_api_key'
    $env:COSYVOICE_VOICE_ID='your_voice_id'
    python scripts/test_aliyun_cosyvoice_tts.py

Optional:
    python scripts/test_aliyun_cosyvoice_tts.py --text "要合成的台词" --model cosyvoice-v3.5-flash --rate 1.05
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
DEFAULT_TEXT = (
    "视黄醇不是让皮肤一夜变好的魔法成分。"
    "它更像一个长期训练计划，持续帮助皮肤更新，让粗糙、暗沉和细纹慢慢变得更稳定。"
)


def _post_json(url: str, *, api_key: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body)
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"CosyVoice HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"CosyVoice request failed: {exc}") from exc


def _download_file(url: str, output_path: Path, timeout: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            output_path.write_bytes(response.read())
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Audio download failed: {exc}") from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test Aliyun CosyVoice TTS with a cloned voice_id.")
    parser.add_argument("--api-key", default=os.getenv("DASHSCOPE_API_KEY", ""), help="DashScope API key.")
    parser.add_argument("--voice-id", default=os.getenv("COSYVOICE_VOICE_ID", ""), help="CosyVoice cloned voice id.")
    parser.add_argument("--text", default=os.getenv("COSYVOICE_TTS_TEXT", DEFAULT_TEXT), help="Text to synthesize.")
    parser.add_argument("--model", default=os.getenv("COSYVOICE_MODEL", "cosyvoice-v3.5-flash"))
    parser.add_argument("--format", default=os.getenv("COSYVOICE_FORMAT", "mp3"), choices=["mp3", "wav", "pcm", "opus"])
    parser.add_argument("--sample-rate", type=int, default=int(os.getenv("COSYVOICE_SAMPLE_RATE", "24000")))
    parser.add_argument("--rate", type=float, default=float(os.getenv("COSYVOICE_RATE", "1.0")), help="Speech speed, 0.5-2.0.")
    parser.add_argument("--pitch", type=float, default=float(os.getenv("COSYVOICE_PITCH", "1.0")), help="Pitch, 0.5-2.0.")
    parser.add_argument("--volume", type=int, default=int(os.getenv("COSYVOICE_VOLUME", "50")), help="Volume, 0-100.")
    parser.add_argument("--instruction", default=os.getenv("COSYVOICE_INSTRUCTION", ""), help="Optional style/emotion instruction.")
    parser.add_argument("--output-dir", default=os.getenv("COSYVOICE_OUTPUT_DIR", "outputs/tts"))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("COSYVOICE_TIMEOUT", "120")))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.api_key:
        print("Missing DASHSCOPE_API_KEY. Set env var or pass --api-key.", file=sys.stderr)
        return 2
    if not args.voice_id:
        print("Missing COSYVOICE_VOICE_ID. Set env var or pass --voice-id.", file=sys.stderr)
        return 2
    if not args.text.strip():
        print("Text is empty.", file=sys.stderr)
        return 2

    input_payload: dict[str, Any] = {
        "text": args.text,
        "voice": args.voice_id,
        "format": args.format,
        "sample_rate": args.sample_rate,
        "rate": args.rate,
        "pitch": args.pitch,
        "volume": args.volume,
        "language_hints": ["zh"],
    }
    if args.instruction:
        input_payload["instruction"] = args.instruction

    payload = {
        "model": args.model,
        "input": input_payload,
    }

    print("Submitting CosyVoice TTS request...")
    result = _post_json(ENDPOINT, api_key=args.api_key, payload=payload, timeout=args.timeout)

    output = result.get("output") or {}
    audio = output.get("audio") or {}
    audio_url = audio.get("url")
    if not audio_url:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("No output.audio.url in response.", file=sys.stderr)
        return 1

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    audio_id = audio.get("id") or "cosyvoice"
    output_path = Path(args.output_dir) / f"{timestamp}_{audio_id}.{args.format}"
    _download_file(audio_url, output_path, timeout=args.timeout)

    print("CosyVoice TTS succeeded.")
    print(f"request_id: {result.get('request_id')}")
    print(f"audio_id: {audio.get('id')}")
    print(f"expires_at: {audio.get('expires_at')}")
    print(f"characters: {(result.get('usage') or {}).get('characters')}")
    print(f"downloaded: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
