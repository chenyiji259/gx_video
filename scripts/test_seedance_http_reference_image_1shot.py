"""Seedance 2.0 参考图视频生成纯 HTTP 测试脚本。

用途：
  1. 使用方舟 asset:// 人像资产作为图片1。
  2. 从本地读取一张无头 Production Board 大图，上传到 ToApis /v1/uploads/images，换取公网图片 URL，作为图片2。
  3. 上传本地 m4a 声音参考到 OSS，取得公网音频 URL，作为音频1。
  4. 按 Seedance 多图融合模式提交：图片1 reference_image + 图片2 reference_image + 音频1 reference_audio。
  5. 通过火山方舟纯 HTTP 接口提交视频生成任务并轮询结果。

这个脚本不依赖 backend/app 主代码，不写数据库，不上传项目对象存储。
音频1只作为音色参考，不作为逐字对白音轨。

运行前：
  - 在项目根目录 .env 中配置 TOAPIS_API_KEY、ARK_API_KEY、STORAGE_* OSS 配置。
  - 默认使用脚本顶部的人像 asset、无头大图路径、音色参考音频和视频提示词，也可用命令行参数覆盖。

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
from urllib.parse import quote

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
LOCAL_VOICE_REFERENCE_AUDIO_PATH = r"C:\Users\CYJ25\Pictures\王总ai 音\南洲路1026号 6_14s8.mp3"
DEFAULT_OSS_SIGNED_URL_EXPIRES = 6 * 60 * 60
DEFAULT_DIALOGUE_TEXT = (
    "视黄醇，其实是维A的一种衍生物。"
    "你可以把它理解成护肤里的长期训练型选手。"
    "它不是今天用明天就变年轻，而是通过持续作用，让皮肤状态慢慢变稳。"
)

TOAPIS_UPLOAD_URL = "https://toapis.com/v1/uploads/images"
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_SUBMIT_PATH = "/contents/generations/tasks"
ARK_QUERY_PATH = "/contents/generations/tasks/{task_id}"

MODEL_NAMES = {
    "seedance_2": "doubao-seedance-2-0-260128",
    "seedance_2_fast": "doubao-seedance-2-0-fast-260128",
}


def build_default_video_prompt(dialogue_text: str) -> str:
    return f"""
生成一个 15 秒中文护肤科普口播视频。

你会收到两个参考图片和一个参考音频：
图片1是人像资产图，只用于锁定真人主角身份、脸型、发型、眼镜、五官、年龄感、灰色衬衫和白色内搭。必须以图片1为主角身份来源，保持同一个人，不要换脸，不要换发型，不要换眼镜，不要改变年龄感。
图片2是“1分钟讲清视黄醇”的无头 Production Board 大图，不是最终视频画面。图片2包含 4 个 15 秒段落，这次只读取故事板中编号 1 的区域，也就是中下部第一列蓝框区域：`1 / 0-15s / 视黄醇是什么`。不要读取编号 2、3、4 的故事内容来生成本段动作或台词。
图片2只用于读取护肤科普工作室场景、桌面产品、视黄醇瓶身、成分卡片、暖灰色灯光、镜头语言和 Segment 1 的内容计划。图片2里的人脸是无五官占位脸，不要采用图片2的人脸；真人脸、发型、眼镜、年龄感、衣着和五官必须始终以图片1为准。
音频1是角色1的声音参考，只用于参考音色、声线质感、年龄感、口音和说话气质。不要把音频1当作原始对白音轨，不要照搬音频1里的具体内容、节奏或停顿。视频中的台词、情绪和时间段以本提示词为准。

不要生成 production board 页面，不要生成网格排版，不要生成顶部标题栏，不要生成分区说明文字，不要生成故事板卡片，不要生成任何可见字幕或说明文字。

本次只生成 Segment 1 / 0-15 秒：视黄醇是什么。
画面必须是一个真实口播视频：图片1中的男性讲师坐在图片2规划的护肤科普工作室桌前，面对镜头自然讲解。保持图片1的人物身份和衣着质感，保持图片2的暖灰色空间、桌面护肤品、视黄醇瓶身、成分卡片、柔和主光和干净商业质感。

分时间段生成真实口播和动作：
0-3 秒：中近景，角色1看向镜头，平静开场，用音频1的成熟中文男声声线自然说：“视黄醇，其实是维A的一种衍生物。”
3-7 秒：轻微 push-in，角色1抬手做解释手势，语气耐心、专业，用音频1的音色说：“你可以把它理解成护肤里的长期训练型选手。”
7-11 秒：切到桌面产品和 Retinol 成分卡的 close-up / macro，角色1继续用同一音色旁白式说明：“它不是今天用明天就变年轻。”
11-15 秒：回到角色1中近景，角色1看向镜头总结，表情亲和可信，用音频1的音色说：“而是通过持续作用，让皮肤状态慢慢变稳。”

完整台词参考：
「{dialogue_text}」

禁止：
不要把音频1当作逐字对白原音轨，不要复刻音频1的原始说话内容，不要让人物无意义对口型。不要使用图片2的无五官占位脸替代图片1真人脸，不要换脸，不要换发型，不要换眼镜，不要换服装，不要出现第二个人，不要跳到新场景，不要夸张表演，不要医疗承诺，不要说一夜变年轻，不要读取 Segment 2、3、4 的故事板内容，不要把图片2中的文字和排版复刻到视频里。
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
    parser.add_argument("--voice-reference-audio", default=LOCAL_VOICE_REFERENCE_AUDIO_PATH, help="本地声音参考音频路径，上传后作为音色 reference_audio")
    parser.add_argument("--audio-url-expires", type=int, default=DEFAULT_OSS_SIGNED_URL_EXPIRES, help="OSS 签名 GET URL 有效期秒数")
    parser.add_argument("--audio-url", default="", help="公网音频 URL；传入后跳过本地音频上传，直接作为 Seedance reference_audio")
    parser.add_argument("--dialogue-text", default=DEFAULT_DIALOGUE_TEXT, help="写入提示词的真实口播台词")
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
    return build_default_video_prompt(args.dialogue_text.strip())


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
        voice_audio_path = Path(args.voice_reference_audio).expanduser().resolve() if args.voice_reference_audio else None
        if voice_audio_path is None or not voice_audio_path.exists() or not voice_audio_path.is_file():
            raise SystemExit("缺少本地声音参考音频。请传入 --voice-reference-audio。")
    if not args.dialogue_text.strip():
        raise SystemExit("缺少口播台词。请传入 --dialogue-text。")
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


def upload_audio_to_oss(audio_path: Path, expires: int) -> dict[str, Any]:
    """上传本地声音参考到 OSS，返回签名 GET URL。"""
    try:
        import oss2
    except ImportError as exc:
        raise RuntimeError("缺少依赖 oss2，请先安装 backend/requirements.txt 中的 oss2。") from exc

    endpoint = os.getenv("STORAGE_ENDPOINT", "").strip()
    public_base_url = os.getenv("STORAGE_PUBLIC_BASE_URL", "").strip()
    access_key = os.getenv("STORAGE_ACCESS_KEY", "").strip()
    secret_key = os.getenv("STORAGE_SECRET_KEY", "").strip()
    bucket_name = os.getenv("STORAGE_BUCKET", "").strip()
    region = os.getenv("STORAGE_REGION", "").strip() or None
    if not all([endpoint, public_base_url, access_key, secret_key, bucket_name]):
        raise RuntimeError("缺少 STORAGE_ENDPOINT/STORAGE_PUBLIC_BASE_URL/STORAGE_ACCESS_KEY/STORAGE_SECRET_KEY/STORAGE_BUCKET 配置。")

    endpoint_for_sdk = endpoint if endpoint.startswith(("http://", "https://")) else f"https://{endpoint}"
    object_key = f"seedance-reference-audio/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{audio_path.name}"
    content_type = mimetypes.guess_type(str(audio_path))[0] or "audio/mp4"

    print(f"[2/5] 上传本地声音参考到 OSS: {audio_path}")
    auth = oss2.Auth(access_key, secret_key)
    bucket = oss2.Bucket(auth, endpoint_for_sdk, bucket_name, region=region)
    headers = {"Content-Type": content_type}
    result = bucket.put_object_from_file(object_key, str(audio_path), headers=headers)
    if result.status not in (200, 201):
        raise RuntimeError(f"OSS 上传失败，status={result.status}")

    permanent_url = f"{public_base_url.rstrip('/')}/{quote(object_key)}"
    signed_url = bucket.sign_url("GET", object_key, int(expires))
    print(f"[oss audio permanent url] {permanent_url}")
    print(f"[oss audio signed url] {signed_url}")
    return {
        "object_key": object_key,
        "bucket": bucket_name,
        "content_type": content_type,
        "permanent_url": permanent_url,
        "signed_url_expires": int(expires),
        "audio_url": signed_url,
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
    ark_base_url = os.getenv("ARK_BASE_URL", ARK_BASE_URL).strip() or ARK_BASE_URL
    if not toapis_key:
        raise SystemExit("缺少 TOAPIS_API_KEY，请先在项目根目录 .env 配置。")
    if not ark_key:
        raise SystemExit("缺少 ARK_API_KEY，请先在项目根目录 .env 配置。")

    try:
        upload_result = upload_image_to_toapis(board_image_path, toapis_key)
        audio_upload_result: dict[str, Any] = {}
        reference_audio_url = args.audio_url.strip()
        if not reference_audio_url:
            audio_path = Path(args.voice_reference_audio).expanduser().resolve()
            audio_upload_result = upload_audio_to_oss(audio_path, args.audio_url_expires)
            reference_audio_url = audio_upload_result["audio_url"]
            write_json(output_dir / "voice_reference_audio_upload.json", audio_upload_result)

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
            "local_voice_reference_audio_path": str(Path(args.voice_reference_audio).expanduser().resolve()) if args.voice_reference_audio else "",
            "voice_reference_audio_object_key": audio_upload_result.get("object_key", ""),
            "dialogue_text": args.dialogue_text.strip(),
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
