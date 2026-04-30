"""歌词时间对齐工具（LyricsAlignmentTool）— DEPRECATED。

⚠️ 已废弃：自 2026-04-02 起，歌词提取由 Qwen3.5 Omni 直接完成，
本工具不再被 AudioAnalysisService 调用。保留文件作为备用降级路径。

来源文档：doc 09 §12 任务 8-02

使用 WhisperX 对音频做 ASR + forced alignment，输出带时间戳的歌词片段。

优雅降级策略（White Box）：
  - WhisperX 未安装时：返回 available=False + reason，不抛 ImportError
  - WhisperX 运行失败时：捕获异常，返回 available=False + 错误详情
  - 两种情况均保证主链路不中断，音频分析结果正常落库

doc10 §3.2 说明：
  ACE-Step 的 LRC 生成主要针对其自生成音乐；
  本工具主要面向用户上传的外部音频，两者互补，不冲突。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

# try-import 优雅降级
_WHISPERX_AVAILABLE: bool = False

try:
    import whisperx  # type: ignore[import]
    _WHISPERX_AVAILABLE = True
except ImportError:
    pass


def _skip_result(reason: str) -> dict[str, Any]:
    """构建跳过/降级结果。"""
    return {
        "available": False,
        "reason": reason,
        "segments": [],
        "language": None,
    }


def _run_whisperx_sync(
    audio_path: str,
    model_size: str,
    language: str | None,
    device: str,
) -> dict[str, Any]:
    """WhisperX 全链路同步执行函数（供 asyncio.to_thread 调用）。

    所有 WhisperX 操作都是同步 CPU/GPU 密集型，提取到此函数后
    由 align_lyrics 通过 asyncio.to_thread 放入线程池，避免阻塞事件循环。
    """
    audio = whisperx.load_audio(audio_path)

    model = whisperx.load_model(model_size, device=device, compute_type="int8")
    transcribe_kwargs: dict[str, Any] = {"batch_size": 16}
    if language:
        transcribe_kwargs["language"] = language
    result = model.transcribe(audio, **transcribe_kwargs)
    detected_lang: str = result.get("language", "unknown")

    align_model, align_meta = whisperx.load_align_model(
        language_code=detected_lang, device=device
    )
    result_aligned = whisperx.align(
        result["segments"],
        align_model,
        align_meta,
        audio,
        device,
        return_char_alignments=False,
    )

    segments: list[dict] = []
    for seg in result_aligned.get("segments", []):
        words = [
            {
                "word": w.get("word", ""),
                "start": round(float(w.get("start", 0.0)), 4),
                "end": round(float(w.get("end", 0.0)), 4),
                "score": round(float(w.get("score", 0.0)), 4),
            }
            for w in seg.get("words", [])
        ]
        segments.append({
            "start": round(float(seg.get("start", 0.0)), 4),
            "end": round(float(seg.get("end", 0.0)), 4),
            "text": seg.get("text", "").strip(),
            "words": words,
        })

    return {
        "available": True,
        "reason": None,
        "segments": segments,
        "language": detected_lang,
    }


async def align_lyrics(
    audio_path: str | Path,
    *,
    model_size: str = "base",
    language: str | None = None,
    device: str = "cpu",
) -> dict[str, Any]:
    """对音频做 ASR + 时间对齐，返回带时间戳的歌词片段。

    内部通过 asyncio.to_thread 将全部同步 WhisperX 操作放入线程池，
    避免阻塞 FastAPI 事件循环。

    Args:
        audio_path:  音频文件本地路径。
        model_size:  WhisperX 模型大小（tiny / base / small / medium / large）。
        language:    语言代码（如 "zh" / "en"），None = 自动检测。
        device:      推理设备（"cpu" / "cuda"）。

    Returns:
        dict 包含：
          available (bool)        — WhisperX 是否成功运行
          reason (str | None)     — 不可用时的原因说明
          segments (list[dict])   — [{start, end, text, words: [...]}]
          language (str | None)   — 检测到的语言代码
    """
    if not _WHISPERX_AVAILABLE:
        return _skip_result(
            "WhisperX 未安装，歌词对齐已跳过。"
            "如需启用，请执行: pip install whisperx"
        )

    try:
        return await asyncio.to_thread(
            _run_whisperx_sync,
            str(audio_path),
            model_size,
            language,
            device,
        )
    except Exception as exc:
        return _skip_result(
            f"WhisperX 执行失败: {type(exc).__name__}: {exc}"
        )
