"""音频底层分析工具（AudioAnalysisTool）— 精确节拍提取。

使用 librosa 对音频做信号级分析：
  - BPM 与节拍时间戳（beat_map）
  - 音频元信息（duration_sec / sample_rate）

职责边界：
  - 只做 beat_track，不做语义解释
  - 段落结构、歌词、和弦等语义分析由 Qwen3.5 Omni 负责
  - 不写数据库，只返回结构化 dict
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.logging import get_logger

_logger = get_logger("audio_analysis_tool", layer="tool")

import librosa

# hop_length（librosa 帧跳）
_HOP_LENGTH: int = 512


def analyze(audio_path: str | Path) -> dict[str, Any]:
    """使用 librosa 提取精确毫秒级节拍时间戳。

    段落结构、歌词、和弦等语义分析由 Qwen3.5 Omni 负责。

    Args:
        audio_path: 音频文件本地路径（WAV / MP3 / FLAC 等 librosa 支持格式）。

    Returns:
        结构化分析 dict：
          bpm (float)                    — 检测到的 BPM
          beat_map (list[float])         — 节拍时间戳（秒）
          duration_sec (float)           — 音频总时长（秒）
          sample_rate (int)              — 采样率

    Raises:
        RuntimeError: 音频无法加载或数据为空。
    """
    _logger.info(
        f"音频节拍分析开始: path={audio_path}",
        event_type="beat_analysis_start",
    )
    try:
        y, sr = librosa.load(str(audio_path), sr=None)
    except Exception as exc:
        raise RuntimeError(f"librosa 无法加载音频 {audio_path}: {exc}") from exc

    if len(y) == 0:
        raise RuntimeError(f"音频 {audio_path} 数据为空")

    _logger.debug(
        f"音频加载完成: sr={sr} samples={len(y)} duration={len(y)/sr:.2f}s",
        event_type="audio_loaded",
    )

    duration_sec = float(len(y) / sr)

    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=_HOP_LENGTH)
    beat_map: list[float] = [
        round(float(t), 4)
        for t in librosa.frames_to_time(beat_frames, sr=sr, hop_length=_HOP_LENGTH)
    ]

    _logger.info(
        f"音频节拍分析完成: bpm={round(float(tempo), 2)} beats={len(beat_map)} "
        f"duration={round(duration_sec, 3)}s",
        event_type="beat_analysis_done",
    )

    return {
        "bpm": round(float(tempo), 2),
        "beat_map": beat_map,
        "duration_sec": round(duration_sec, 3),
        "sample_rate": int(sr),
    }
