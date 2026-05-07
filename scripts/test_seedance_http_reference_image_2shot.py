"""Seedance 2.0 参考图视频生成纯 HTTP 测试脚本。

用途：
  1. 使用方舟 asset:// 人像资产作为图片1。
  2. 从本地读取一张无头 Production Board 大图，上传到 ToApis /v1/uploads/images，换取公网图片 URL，作为图片2。
  3. 调用 CosyVoice 生成当前 segment 的 TTS 音频，取得临时公网音频 URL，作为音频1。
  4. 按 Seedance 多图融合模式提交：图片1 reference_image + 图片2 reference_image + 音频1 reference_audio。
  5. 通过火山方舟纯 HTTP 接口提交视频生成任务并轮询结果。

这个脚本不依赖 backend/app 主代码，不写数据库，不上传项目对象存储。
TTS 音频 URL 只用于本次 Seedance 实验，不做持久化存储。

运行前：
  - 在项目根目录 .env 中配置 TOAPIS_API_KEY、ARK_API_KEY、DASHSCOPE_API_KEY。
  - 默认使用脚本顶部的人像 asset、无头 Production Board 大图路径、TTS 台词和视频提示词，也可用命令行参数覆盖。

示例：
  python scripts/test_seedance_http_reference_image.py
  python scripts/test_seedance_http_reference_image.py --board-image "C:\\path\\board.png" --prompt-file prompt.txt
  python scripts/test_seedance_http_reference_image.py --person-asset-url "asset://asset-xxx" --board-image "C:\\path\\board.png" --audio-url "https://example.com/voiceover.mp3" --prompt-file prompt.txt
  python scripts/test_seedance_http_reference_image.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import mimetypes
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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "seedance_http_reference_test"

# 只需要改这里，或通过命令行参数覆盖。
LOCAL_PERSON_IMAGE_PATH = r"C:\Users\CYJ25\Pictures\老王写真图\IMG_7149.JPG"
DEFAULT_PERSON_ASSET_URL = "asset://asset-20260506142121-6ns58"
LOCAL_BOARD_IMAGE_PATH = r"C:\Users\CYJ25\Downloads\无头.png"
DEFAULT_COSYVOICE_MODEL = "cosyvoice-v3.5-plus"
DEFAULT_COSYVOICE_VOICE_ID = "cosyvoice-v3.5-plus-bailian-50762e3d4f0e4c528ff661c37da30326"
DEFAULT_TTS_TEXT = (
    "视黄醇真正被关注的作用，是帮助皮肤更稳定地更新。"
    "它能慢慢改善细纹、粗糙和暗沉。"
    "但记住，它不是一次使用就立刻逆转，而是要和时间配合。"
)
DEFAULT_TTS_INSTRUCTION = "语气专业、亲和、自然，适合中文护肤科普口播。"

TOAPIS_UPLOAD_URL = "https://toapis.com/v1/uploads/images"
DASHSCOPE_TTS_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_SUBMIT_PATH = "/contents/generations/tasks"
ARK_QUERY_PATH = "/contents/generations/tasks/{task_id}"

MODEL_NAMES = {
    "seedance_2": "doubao-seedance-2-0-260128",
    "seedance_2_fast": "doubao-seedance-2-0-fast-260128",
}


def build_default_video_prompt(tts_text: str) -> str:
    return f"""
生成一个 15 秒中文护肤科普口播视频。

你会收到两个参考图片和一个参考音频：
图片1是人像资产图，只用于锁定真人主角身份、脸型、发型、眼镜、五官、年龄感、灰色衬衫和白色内搭。必须以图片1为主角身份来源，保持同一个人，不要换脸，不要换发型，不要换眼镜，不要改变年龄感。
图片2是“1分钟讲清视黄醇”的无头 Production Board 大图，不是最终视频画面。图片2包含 4 个 15 秒段落，这次只读取故事板中编号 2 的区域，也就是中下部第二列蓝框区域：`2 / 15-30s / 它到底有什么用`。不要读取编号 1、3、4 的故事内容来生成本段动作或台词。
图片2只用于读取护肤科普工作室场景、桌面产品、视黄醇瓶身、皮肤屏障示意卡、暖灰色灯光、镜头语言和 Segment 2 的内容计划。图片2里的人脸是无五官占位脸，不要采用图片2的人脸；真人脸、发型、眼镜、年龄感、衣着和五官必须始终以图片1为准。
音频1是当前 Segment 2 的真实 TTS 口播音频，人物口型、停顿、表情和镜头节奏要尽量贴合音频1。

不要生成 production board 页面，不要生成网格排版，不要生成顶部标题栏，不要生成分区说明文字，不要生成故事板卡片，不要生成任何可见字幕或说明文字。

本次只生成 Segment 2 / 15-30 秒：它到底有什么用。
画面必须是一个真实口播视频：图片1中的男性讲师坐在图片2规划的护肤科普工作室桌前，面对镜头自然讲解视黄醇的核心作用。保持图片1的人物身份和衣着质感，保持图片2的暖灰色空间、桌面护肤品、视黄醇瓶身、皮肤屏障示意卡、柔和主光和干净商业质感。

镜头节奏：
15-18 秒：中近景，主角坐在桌前，面向镜头承接上一段，开始解释“它到底有什么用”。
18-23 秒：插入皮肤屏障或皮肤纹理示意卡，镜头可以轻微平移或 close-up，表现细纹、粗糙和暗沉等状态被逐渐改善的概念；画面要像真实科普演示，不要变成网页 UI。
23-27 秒：回到主角中近景或轻微 push-in，主角用手势指向示意卡，说明视黄醇通过持续作用帮助皮肤正常更新。
27-30 秒：主角 close-up，总结“不是一次使用就立刻逆转，而是长期稳定改善”，表情理性、耐心、可信。

口播台词必须以音频1为准：
「{tts_text}」

禁止：
不要使用图片2的无五官占位脸替代图片1真人脸，不要换脸，不要换发型，不要换眼镜，不要换服装，不要出现第二个人，不要跳到新场景，不要夸张表演，不要医疗承诺，不要说一夜变年轻，不要读取 Segment 1、3、4 的故事板内容，不要把图片2中的文字和排版复刻到视频里。
""".strip()


def load_env() -> None:
    """加载项目根目录 .env，避免依赖主项目配置代码。"""
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
    parser = argparse.ArgumentParser(description="Seedance 2.0 参考图视频生成纯 HTTP 测试")
    parser.add_argument("--person-image", default=LOCAL_PERSON_IMAGE_PATH, help="本地人像图路径，仅用于记录和人工核对；Seedance 默认使用 --person-asset-url")
    parser.add_argument("--person-asset-url", default=DEFAULT_PERSON_ASSET_URL, help="方舟人像资产 URL，作为图片1 reference_image")
    parser.add_argument("--board-image", "--image", dest="board_image", default=LOCAL_BOARD_IMAGE_PATH, help="本地无头 Production Board 大图路径，上传后作为图片2 reference_image")
    parser.add_argument("--audio-url", default="", help="公网音频 URL；传入后跳过 CosyVoice，直接作为 Seedance reference_audio")
    parser.add_argument("--tts-text", default=DEFAULT_TTS_TEXT, help="要合成为 TTS 的口播台词")
    parser.add_argument("--tts-model", default=DEFAULT_COSYVOICE_MODEL, help="CosyVoice 模型")
    parser.add_argument("--voice-id", default=DEFAULT_COSYVOICE_VOICE_ID, help="CosyVoice 音色 ID")
    parser.add_argument("--tts-format", default="mp3", choices=["mp3", "wav", "pcm", "opus"], help="TTS 输出格式")
    parser.add_argument("--tts-sample-rate", type=int, default=24000, help="TTS 采样率")
    parser.add_argument("--tts-rate", type=float, default=1.0, help="TTS 语速，常用 0.5-2.0")
    parser.add_argument("--tts-pitch", type=float, default=1.0, help="TTS 音高，常用 0.5-2.0")
    parser.add_argument("--tts-volume", type=int, default=50, help="TTS 音量，0-100")
    parser.add_argument("--tts-instruction", default=DEFAULT_TTS_INSTRUCTION, help="TTS 风格指令")
    parser.add_argument("--prompt", default="", help="视频提示词；为空时使用脚本内 VIDEO_PROMPT")
    parser.add_argument("--prompt-file", default="", help="从文本文件读取视频提示词")
    parser.add_argument(
        "--provider",
        default="seedance_2",
        choices=sorted(MODEL_NAMES.keys()),
        help="Seedance provider 预设",
    )
    parser.add_argument("--model", default="", help="直接指定方舟模型 ID，优先级高于 --provider")
    parser.add_argument("--ratio", default="16:9", help="输出画幅，例如 16:9 / 9:16 / adaptive")
    parser.add_argument("--duration", type=int, default=15, help="输出视频时长，Seedance 常用 4-15 秒")
    parser.add_argument("--resolution", default="1080p", help="输出分辨率，例如 720p / 1080p")
    parser.add_argument("--generate-audio", action=argparse.BooleanOptionalAction, default=True, help="让 Seedance 同时生成音频")
    parser.add_argument("--watermark", action="store_true", help="生成视频带水印")
    parser.add_argument("--poll-interval-sec", type=int, default=15, help="轮询间隔秒数")
    parser.add_argument("--max-attempts", type=int, default=50, help="最大轮询次数")
    parser.add_argument("--output-dir", default="", help="输出目录，默认 data/seedance_http_reference_test/run_时间戳")
    parser.add_argument("--download-video", action="store_true", help="成功后下载视频到输出目录")
    parser.add_argument("--dry-run", action="store_true", help="只打印 payload，不提交任务")
    return parser.parse_args()


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        path = Path(args.prompt_file).expanduser().resolve()
        return path.read_text(encoding="utf-8").strip()
    if args.prompt:
        return args.prompt.strip()
    return build_default_video_prompt(args.tts_text.strip())


def ensure_inputs(args: argparse.Namespace, prompt: str) -> Path:
    board_image_path = Path(args.board_image).expanduser().resolve() if args.board_image else None
    if board_image_path is None or not board_image_path.exists() or not board_image_path.is_file():
        raise SystemExit(
            "缺少本地无头 Production Board 大图。请填写脚本顶部 LOCAL_BOARD_IMAGE_PATH，"
            "或使用 --board-image \"C:\\path\\image.png\"。"
        )
    if args.person_image:
        person_image_path = Path(args.person_image).expanduser().resolve()
        if not person_image_path.exists() or not person_image_path.is_file():
            print(f"[warn] 本地人像图不存在，仅影响人工核对，不影响 asset:// 请求: {person_image_path}")
    if not args.person_asset_url.startswith(("asset://", "http://", "https://")):
        raise SystemExit("--person-asset-url 必须是 asset:// 或 HTTP(S) URL。")
    if not prompt or prompt == "在这里填写 Seedance 视频提示词。":
        raise SystemExit(
            "缺少视频提示词。请填写脚本顶部 VIDEO_PROMPT，"
            "或使用 --prompt / --prompt-file。"
        )
    if args.duration < 1 or args.duration > 15:
        raise SystemExit("Seedance 单次视频时长建议在 1-15 秒之间，请调整 --duration。")
    if args.audio_url and not args.audio_url.startswith(("http://", "https://")):
        raise SystemExit("--audio-url 必须是公网可访问的 HTTP(S) URL。")
    if not args.audio_url:
        if not args.tts_text.strip():
            raise SystemExit("缺少 TTS 台词。请传入 --tts-text。")
        if not args.voice_id.strip():
            raise SystemExit("缺少 CosyVoice 音色 ID。请传入 --voice-id。")
        if not args.tts_model.strip():
            raise SystemExit("缺少 CosyVoice 模型。请传入 --tts-model。")
    return board_image_path


def make_output_dir(args: argparse.Namespace) -> Path:
    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = DEFAULT_OUTPUT_ROOT / f"run_{ts}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def upload_image_to_toapis(image_path: Path, api_key: str) -> dict[str, Any]:
    """上传本地图片到 ToApis，返回包含公网 URL 的响应数据。"""
    mime_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    headers = {"Authorization": f"Bearer {api_key}"}

    print(f"[1/5] 上传本地无头 Production Board 大图到 ToApis: {image_path}")
    with image_path.open("rb") as file_obj:
        files = {"file": (image_path.name, file_obj, mime_type)}
        resp = requests.post(TOAPIS_UPLOAD_URL, headers=headers, files=files, timeout=120)

    print(f"[toapis upload] HTTP {resp.status_code}")
    print(resp.text[:2000])
    resp.raise_for_status()

    data = resp.json()
    public_url = extract_toapis_upload_url(data)
    print(f"[toapis public url] {public_url}")
    return {"raw_response": data, "public_url": public_url}


def extract_toapis_upload_url(data: dict[str, Any]) -> str:
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    url = ""
    if isinstance(payload, dict):
        url = str(payload.get("url") or payload.get("public_url") or "")
    if not url:
        raise RuntimeError(f"ToApis 上传响应中没有公网 URL: {json.dumps(data, ensure_ascii=False)}")
    if not url.startswith(("http://", "https://")):
        raise RuntimeError(f"ToApis 返回的 URL 不是 HTTP(S): {url!r}")
    return url


def synthesize_cosyvoice_tts(args: argparse.Namespace, api_key: str) -> dict[str, Any]:
    """生成 TTS 音频并返回 provider 临时公网 URL，不做本地下载或持久化。"""
    input_payload: dict[str, Any] = {
        "text": args.tts_text.strip(),
        "voice": args.voice_id.strip(),
        "format": args.tts_format,
        "sample_rate": int(args.tts_sample_rate),
        "rate": float(args.tts_rate),
        "pitch": float(args.tts_pitch),
        "volume": int(args.tts_volume),
        "language_hints": ["zh"],
    }
    if args.tts_instruction.strip():
        input_payload["instruction"] = args.tts_instruction.strip()

    payload = {
        "model": args.tts_model.strip(),
        "input": input_payload,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print("[2/5] 调用 CosyVoice 生成 TTS 临时音频 URL")
    print(
        json.dumps(
            {
                "model": payload["model"],
                "voice": input_payload["voice"],
                "characters": len(input_payload["text"]),
                "format": input_payload["format"],
                "sample_rate": input_payload["sample_rate"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    resp = requests.post(DASHSCOPE_TTS_URL, headers=headers, json=payload, timeout=180)
    print(f"[cosyvoice tts] HTTP {resp.status_code}")
    print(resp.text[:2000])
    resp.raise_for_status()

    data = resp.json()
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    audio = output.get("audio") if isinstance(output.get("audio"), dict) else {}
    audio_url = str(audio.get("url") or "")
    if not audio_url.startswith(("http://", "https://")):
        raise RuntimeError(f"CosyVoice 响应中没有可用 audio.url: {json.dumps(data, ensure_ascii=False)}")
    print(f"[cosyvoice audio url] {audio_url}")
    return {
        "raw_response": data,
        "audio_url": audio_url,
        "audio_id": str(audio.get("id") or ""),
        "expires_at": audio.get("expires_at"),
        "characters": (data.get("usage") or {}).get("characters"),
    }


def build_seedance_payload(
    *,
    args: argparse.Namespace,
    prompt: str,
    board_image_url: str,
) -> dict[str, Any]:
    model = args.model.strip() or MODEL_NAMES[args.provider]
    content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {"url": args.person_asset_url.strip()},
            "role": "reference_image",
        },
        {
            "type": "image_url",
            "image_url": {"url": board_image_url},
            "role": "reference_image",
        },
    ]
    if args.audio_url:
        content.append(
            {
                "type": "audio_url",
                "audio_url": {"url": args.audio_url.strip()},
                "role": "reference_audio",
            }
        )

    return {
        "model": model,
        "content": content,
        "ratio": args.ratio,
        "duration": int(args.duration),
        "resolution": args.resolution,
        "generate_audio": bool(args.generate_audio),
        "watermark": bool(args.watermark),
    }


def submit_seedance_task(payload: dict[str, Any], api_key: str, base_url: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{ARK_SUBMIT_PATH}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    print(f"[3/5] 提交 Seedance 任务: POST {url}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    print(f"[seedance submit] HTTP {resp.status_code}")
    print(resp.text[:3000])
    resp.raise_for_status()

    data = resp.json()
    task_id = data.get("id")
    if not task_id:
        raise RuntimeError(f"Seedance 未返回任务 ID: {json.dumps(data, ensure_ascii=False)}")
    return {"task_id": str(task_id), "raw_response": data}


def poll_seedance_task(
    *,
    task_id: str,
    api_key: str,
    base_url: str,
    poll_interval_sec: int,
    max_attempts: int,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{ARK_QUERY_PATH.format(task_id=task_id)}"
    headers = {"Authorization": f"Bearer {api_key}"}
    print(f"[4/5] 开始轮询 Seedance: task_id={task_id}")

    for attempt in range(1, max_attempts + 1):
        time.sleep(poll_interval_sec)
        resp = requests.get(url, headers=headers, timeout=60)
        print(f"[poll {attempt}/{max_attempts}] HTTP {resp.status_code}")
        print(resp.text[:2000])

        if resp.status_code != 200:
            continue

        data = resp.json()
        status = str(data.get("status") or "")
        if status in ("succeeded", "completed"):
            video_url = extract_seedance_video_url(data)
            print(f"[succeeded] video_url={video_url}")
            return {"status": status, "video_url": video_url, "raw_response": data}
        if status == "failed":
            raise RuntimeError(f"Seedance 任务失败: {json.dumps(data, ensure_ascii=False)}")

    raise TimeoutError(f"Seedance 轮询超时：{max_attempts} 次仍未完成")


def extract_seedance_video_url(data: dict[str, Any]) -> str:
    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    video_url = str(content.get("video_url") or "")
    if not video_url:
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        video_url = str(result.get("video_url") or "")
        if not video_url:
            items = result.get("data") if isinstance(result.get("data"), list) else []
            if items and isinstance(items[0], dict):
                video_url = str(items[0].get("url") or "")
    if not video_url:
        raise RuntimeError(f"Seedance 成功响应中没有 video_url: {json.dumps(data, ensure_ascii=False)}")
    return video_url


def download_video(video_url: str, output_dir: Path) -> Path:
    print(f"[download] {video_url}")
    resp = requests.get(video_url, timeout=300)
    resp.raise_for_status()

    suffix = ".mp4"
    content_type = resp.headers.get("content-type", "").lower()
    if "quicktime" in content_type or video_url.lower().split("?")[0].endswith(".mov"):
        suffix = ".mov"
    elif "webm" in content_type or video_url.lower().split("?")[0].endswith(".webm"):
        suffix = ".webm"

    output_path = output_dir / f"seedance_result{suffix}"
    output_path.write_bytes(resp.content)
    print(f"[saved video] {output_path}")
    return output_path


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    load_env()
    args = parse_args()
    prompt = read_prompt(args)
    board_image_path = ensure_inputs(args, prompt)
    output_dir = make_output_dir(args)

    toapis_key = os.getenv("TOAPIS_API_KEY", "").strip()
    ark_key = os.getenv("ARK_API_KEY", "").strip()
    dashscope_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    ark_base_url = os.getenv("ARK_BASE_URL", ARK_BASE_URL).strip() or ARK_BASE_URL
    if not toapis_key:
        raise SystemExit("缺少 TOAPIS_API_KEY，请先在项目根目录 .env 配置。")
    if not ark_key:
        raise SystemExit("缺少 ARK_API_KEY，请先在项目根目录 .env 配置。")
    if not args.audio_url and not dashscope_key:
        raise SystemExit("缺少 DASHSCOPE_API_KEY，请先在项目根目录 .env 配置，或传入 --audio-url 跳过 TTS。")

    try:
        upload_result = upload_image_to_toapis(board_image_path, toapis_key)
        tts_result: dict[str, Any] = {}
        reference_audio_url = args.audio_url.strip()
        if not reference_audio_url:
            tts_result = synthesize_cosyvoice_tts(args, dashscope_key)
            reference_audio_url = tts_result["audio_url"]
            write_json(output_dir / "cosyvoice_tts_response.json", tts_result["raw_response"])

        args.audio_url = reference_audio_url
        payload = build_seedance_payload(
            args=args,
            prompt=prompt,
            board_image_url=upload_result["public_url"],
        )
        write_json(output_dir / "seedance_payload.json", payload)
        write_json(output_dir / "toapis_upload_response.json", upload_result["raw_response"])

        if args.dry_run:
            print("[dry-run] 已生成 payload，不提交 Seedance 任务。")
            print(f"输出目录：{output_dir}")
            return 0

        submit_result = submit_seedance_task(payload, ark_key, ark_base_url)
        write_json(output_dir / "seedance_submit_response.json", submit_result["raw_response"])

        poll_result = poll_seedance_task(
            task_id=submit_result["task_id"],
            api_key=ark_key,
            base_url=ark_base_url,
            poll_interval_sec=args.poll_interval_sec,
            max_attempts=args.max_attempts,
        )
        write_json(output_dir / "seedance_final_response.json", poll_result["raw_response"])

        metadata = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "local_person_image_path": str(Path(args.person_image).expanduser().resolve()) if args.person_image else "",
            "person_asset_url": args.person_asset_url.strip(),
            "local_board_image_path": str(board_image_path),
            "toapis_public_board_image_url": upload_result["public_url"],
            "reference_audio_url": reference_audio_url,
            "cosyvoice_audio_id": tts_result.get("audio_id", ""),
            "cosyvoice_expires_at": tts_result.get("expires_at"),
            "cosyvoice_characters": tts_result.get("characters"),
            "cosyvoice_model": args.tts_model.strip(),
            "cosyvoice_voice_id": args.voice_id.strip(),
            "tts_text": args.tts_text.strip(),
            "seedance_task_id": submit_result["task_id"],
            "seedance_video_url": poll_result["video_url"],
            "model": payload["model"],
            "ratio": payload["ratio"],
            "duration": payload["duration"],
            "resolution": payload["resolution"],
            "generate_audio": payload["generate_audio"],
            "watermark": payload["watermark"],
            "prompt": prompt,
        }

        if args.download_video:
            video_path = download_video(poll_result["video_url"], output_dir)
            metadata["downloaded_video_path"] = str(video_path)

        write_json(output_dir / "metadata.json", metadata)
        print("[5/5] done")
        print(f"输出目录：{output_dir}")
        print(f"视频 URL：{poll_result['video_url']}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
