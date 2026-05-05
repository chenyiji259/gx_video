"""FFmpeg 时间线合成工具（FFmpeg Timeline Tool）。

来源文档：doc 09 任务 11-06

职责：
  - 按 segments 顺序拼接视频 clips
  - 叠加原始音频轨
  - 输出 preview 视频文件（本地）

设计约束：
  - ffmpeg 不可用时明确抛出 FFmpegNotAvailableError，而不是 silent failure
  - 所有路径操作使用 pathlib.Path
  - 不依赖 moviepy（避免额外重量级依赖），直接调用 subprocess
  - 输入 clips 列表必须按时间顺序排列
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from app.core.config_loader import load_media_config
from app.core.logging import get_logger

_logger = get_logger("ffmpeg_timeline", layer="tool")


class FFmpegNotAvailableError(Exception):
    """ffmpeg 不可用时抛出。"""
    pass


class TimelineCompositionError(Exception):
    """时间线合成失败异常。"""

    def __init__(self, message: str, code: str = "timeline_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _check_ffmpeg() -> str:
    """检查 ffmpeg 是否可用，返回 ffmpeg 可执行路径。

    Raises:
        FFmpegNotAvailableError: ffmpeg 未安装或不在 PATH 中。
    """
    configured_path = load_media_config().ffmpeg_path
    if configured_path:
        configured = Path(configured_path).expanduser()
        if configured.exists() and configured.is_file():
            return str(configured)
        raise FFmpegNotAvailableError(
            f"配置中的 ffmpeg_path 不可用：{configured}\n"
            "请检查 config/base/app.yaml 或 .env 中的 FFMPEG_PATH。"
        )

    path = shutil.which("ffmpeg")
    if path is None:
        raise FFmpegNotAvailableError(
            "ffmpeg 未安装或不在系统 PATH 中。\n"
            "也可在 config/base/app.yaml / .env 中配置 FFMPEG_PATH。\n"
            "时间线合成功能依赖 ffmpeg，请先安装：\n"
            "  Linux: apt install ffmpeg\n"
            "  macOS: brew install ffmpeg\n"
            "  Windows: 下载 ffmpeg.exe 并加入 PATH"
        )
    return path
class FFmpegTimelineTool:
    """使用 ffmpeg 合成时间线预览视频。"""

    async def compose_preview(
        self,
        clip_paths: list[Path],
        audio_path: Path | None,
        output_path: Path,
        *,
        audio_start_sec: float = 0.0,
        target_aspect_ratio: str | None = None,
    ) -> Path:
        """拼接 clips，必要时叠加外部音频，输出 preview 视频。

        Args:
            clip_paths:       按顺序排列的 clip 本地文件路径列表。
            audio_path:       原始音频文件路径（可为空；为空时保留 clip 自带音轨）。
            output_path:      输出文件路径（.mp4）。
            audio_start_sec:  音频起始偏移（秒）。
            target_aspect_ratio: 项目目标画幅，用于多 clip 拼接前统一视频参数。

        Returns:
            output_path（写入成功后）。

        Raises:
            FFmpegNotAvailableError: ffmpeg 未安装。
            TimelineCompositionError: 合成过程中出错。
        """
        ffmpeg_bin = _check_ffmpeg()

        _logger.info(
            f"时间线合成开始: clips={len(clip_paths)} "
            f"audio={(audio_path.name if audio_path else 'none')} "
            f"output={output_path.name} audio_start={audio_start_sec}s",
            event_type="timeline_compose_start",
        )

        if not clip_paths:
            raise TimelineCompositionError(
                "clip_paths 不能为空", code="no_clips"
            )

        # 确保输出目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if len(clip_paths) == 1:
            # 单 clip：有外部音频则 mux，否则直接复制。
            if audio_path:
                result = await self._mix_single_clip_audio(
                    ffmpeg_bin, clip_paths[0], audio_path, output_path, audio_start_sec
                )
            else:
                result = await self._normalize_single_clip(
                    ffmpeg_bin, clip_paths[0], output_path
                )
            _logger.info("时间线合成完成（单clip模式）", event_type="timeline_compose_done")
            return result
        else:
            # 多 clip：先拼接；若有外部音频再叠加，否则保留原视频音轨。
            result = await self._concat_and_mix(
                ffmpeg_bin, clip_paths, audio_path, output_path, audio_start_sec, target_aspect_ratio
            )
            _logger.info(
                f"时间线合成完成（多clip模式）: clips={len(clip_paths)}",
                event_type="timeline_compose_done",
            )
            return result

    # ------------------------------------------------------------------
    # 单 clip 处理
    # ------------------------------------------------------------------

    async def _normalize_single_clip(
        self,
        ffmpeg_bin: str,
        clip_path: Path,
        output_path: Path,
    ) -> Path:
        """单 clip 无外部音频时做最小可用的响度归一。"""
        cmd = [
            ffmpeg_bin, "-y",
            "-i", str(clip_path),
            "-map", "0:v:0",
            "-map", "0:a:0",
            "-c:v", "copy",
            "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        await self._run_ffmpeg(cmd, "single_clip_normalize")
        return output_path

    async def _mix_single_clip_audio(
        self,
        ffmpeg_bin: str,
        clip_path: Path,
        audio_path: Path,
        output_path: Path,
        audio_start_sec: float,
    ) -> Path:
        """单 clip 时保留原音，并用原音对外部背景音做 ducking。"""
        cmd = [
            ffmpeg_bin, "-y",
            "-i", str(clip_path),
            "-i", str(audio_path),
            "-filter_complex",
            (
                f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo[voice];"
                f"[1:a]atrim=start={audio_start_sec},asetpts=PTS-STARTPTS,"
                f"aformat=sample_rates=48000:channel_layouts=stereo[bgm];"
                f"[bgm][voice]sidechaincompress=threshold=0.04:ratio=8:attack=15:release=300[bgmduck];"
                f"[voice][bgmduck]amix=inputs=2:weights=1 0.28:normalize=0,"
                f"loudnorm=I=-16:LRA=11:TP=-1.5[aout]"
            ),
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path),
        ]
        await self._run_ffmpeg(cmd, "single_clip_mix")
        return output_path

    # ------------------------------------------------------------------
    # 多 clip 拼接
    # ------------------------------------------------------------------

    async def _concat_and_mix(
        self,
        ffmpeg_bin: str,
        clip_paths: list[Path],
        audio_path: Path | None,
        output_path: Path,
        audio_start_sec: float,
        target_aspect_ratio: str | None,
    ) -> Path:
        """多 clip 时对画面做顺序拼接，对音频做轻量 crossfade + loudnorm，可选 bgm ducking。"""
        crossfade_sec = 0.12
        overlap_total = max(0.0, crossfade_sec * max(len(clip_paths) - 1, 0))
        target_width, target_height = self._resolve_target_size(target_aspect_ratio)
        input_args: list[str] = []
        for clip_path in clip_paths:
            input_args.extend(["-i", str(clip_path)])
        if audio_path:
            input_args.extend(["-i", str(audio_path)])

        video_prep = "".join(
            (
                f"[{idx}:v]setpts=PTS-STARTPTS,"
                f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,"
                f"setsar=1,fps=24,format=yuv420p[v{idx}];"
            )
            for idx in range(len(clip_paths))
        )
        video_concat_inputs = "".join(f"[v{idx}]" for idx in range(len(clip_paths)))
        video_chain = f"{video_concat_inputs}concat=n={len(clip_paths)}:v=1:a=0[vcat];"

        audio_prep = "".join(
            f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{idx}];"
            for idx in range(len(clip_paths))
        )
        current_audio = "a0"
        audio_chain_parts: list[str] = []
        for idx in range(1, len(clip_paths)):
            next_label = f"ax{idx}"
            audio_chain_parts.append(
                f"[{current_audio}][a{idx}]acrossfade=d={crossfade_sec}:c1=tri:c2=tri[{next_label}];"
            )
            current_audio = next_label
        audio_chain_parts.append(
            f"[{current_audio}]apad=pad_dur={overlap_total:.3f},"
            f"loudnorm=I=-16:LRA=11:TP=-1.5[avoice];"
        )
        audio_chain = "".join(audio_chain_parts)

        if audio_path:
            bgm_input_idx = len(clip_paths)
            audio_chain += (
                f"[{bgm_input_idx}:a]atrim=start={audio_start_sec},asetpts=PTS-STARTPTS,"
                f"aformat=sample_rates=48000:channel_layouts=stereo[bgm];"
                f"[bgm][avoice]sidechaincompress=threshold=0.04:ratio=8:attack=15:release=300[bgmduck];"
                f"[avoice][bgmduck]amix=inputs=2:weights=1 0.28:normalize=0,"
                f"loudnorm=I=-16:LRA=11:TP=-1.5[aout]"
            )
        else:
            audio_chain += "[avoice]anull[aout]"

        filter_complex = f"{video_prep}{audio_prep}{video_chain}{audio_chain}"
        cmd = [
            ffmpeg_bin, "-y",
            *input_args,
            "-filter_complex", filter_complex,
            "-map", "[vcat]",
            "-map", "[aout]",
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        await self._run_ffmpeg(cmd, "concat_mix")
        _logger.debug(
            f"时间线音频处理完成: clips={len(clip_paths)} overlap={overlap_total:.3f}s "
            f"target={target_width}x{target_height}",
            event_type="timeline_audio_postprocess_done",
        )
        return output_path

    @staticmethod
    def _resolve_target_size(aspect_ratio: str | None) -> tuple[int, int]:
        """返回 timeline preview 的统一画幅尺寸，保证 concat 输入参数一致。"""
        ratio = (aspect_ratio or "").strip()
        if ratio == "16:9":
            return 1920, 1080
        if ratio == "1:1":
            return 1080, 1080
        # 短视频默认竖版；未知比例也使用竖版，避免不同尺寸 clip 直接 concat 失败。
        return 1080, 1920

    # ------------------------------------------------------------------
    # 转码到目标分辨率（供 ExportService 使用）
    # ------------------------------------------------------------------

    async def transcode_to_resolution(
        self,
        input_path: Path,
        output_path: Path,
        scale: str,
    ) -> Path:
        """使用 ffmpeg 把输入视频转码到目标分辨率。

        Args:
            input_path:  输入视频路径（一般为 timeline preview .mp4）。
            output_path: 输出文件路径（.mp4）。
            scale:       ffmpeg scale 参数，例如 "1280:720" / "1920:1080"。

        Returns:
            output_path（写入成功后）。

        Raises:
            FFmpegNotAvailableError: ffmpeg 未安装。
            TimelineCompositionError: 转码失败。
        """
        ffmpeg_bin = _check_ffmpeg()
        _logger.info(
            f"视频转码开始: input={input_path.name} scale={scale!r} "
            f"output={output_path.name}",
            event_type="timeline_transcode_start",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            ffmpeg_bin, "-y",
            "-i", str(input_path),
            "-vf", f"scale={scale}",
            "-c:v", "libx264", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]
        await self._run_ffmpeg(cmd, f"transcode_{scale}")
        _logger.info(
            f"视频转码完成: output={output_path.name} scale={scale!r}",
            event_type="timeline_transcode_done",
        )
        return output_path

    # ------------------------------------------------------------------
    # 执行 ffmpeg 命令
    # ------------------------------------------------------------------

    @staticmethod
    async def _run_ffmpeg(cmd: list[str], step: str) -> None:
        """异步执行 ffmpeg 命令，失败时抛出 TimelineCompositionError。"""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace")[-500:] if stderr else ""
            raise TimelineCompositionError(
                f"ffmpeg [{step}] 失败（returncode={proc.returncode}）:\n{err_msg}",
                code="ffmpeg_error",
            )
