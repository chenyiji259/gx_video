"""音频裁切工具（AudioTrimTool）。

来源文档：doc 09 §12 任务 8-01

从 MinIO 下载原始音频，按 ProjectSpec 的时间区间裁切，
上传裁切结果到 MinIO，生成 audio_trimmed 类型的 Asset 记录，
并在本地 01_input/ 保留副本供调试追溯。

实现依赖：
  - librosa >= 0.10.1：load（支持 offset / duration 参数，保留原采样率）
  - soundfile >= 0.12.1：write（输出 WAV 格式）

设计决策：
  - 不依赖 ffmpeg，减少外部依赖
  - 临时文件使用 tempfile.TemporaryDirectory 自动清理
  - ULID 主键在 Python 层生成，INSERT 前即可获取 Asset ID
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

import librosa
import soundfile as sf
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_tool_logger
from app.models.asset import Asset
from app.repositories.asset_repository import AssetRepository
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.minio_adapter import get_storage
from app.storage.path_planner import ArtifactStage
from app.utils.ids import generate_ulid


class AudioTrimError(Exception):
    """音频裁切工具异常。"""

    def __init__(self, message: str, code: str = "trim_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def trim_audio(
    *,
    project_id: str,
    audio_asset_id: str,
    start_sec: float,
    end_sec: float,
    session: AsyncSession,
) -> Asset:
    """按时间区间裁切音频，返回 audio_trimmed 类型的 Asset（已 flush）。

    Args:
        project_id:     目标项目 ID。
        audio_asset_id: 原始音频资产 ID（audio_original / audio_trimmed 类型）。
        start_sec:      裁切起始时间（秒，相对于原音频）。
        end_sec:        裁切结束时间（秒）。
        session:        数据库会话（调用方负责 commit）。

    Returns:
        新建的 audio_trimmed Asset ORM 对象（已 flush，未 commit）。

    Raises:
        AudioTrimError: 资产不存在 / 时间区间非法 / 音频处理失败。
    """
    logger = get_tool_logger("audio_trim_tool", project_id=project_id)

    # 验证时间区间
    # end_sec=0 表示「使用全曲」（librosa duration=None 加载到末尾）
    if end_sec == 0.0:
        duration: float | None = None   # 告知 librosa 加载到音频末尾
    elif end_sec <= start_sec:
        raise AudioTrimError(
            f"无效时间区间: start={start_sec}s >= end={end_sec}s",
            code="invalid_range",
        )
    else:
        duration = end_sec - start_sec

    # 获取源 Asset
    asset_repo = AssetRepository(session)
    src = await asset_repo.get_by_id(audio_asset_id)
    if src is None:
        raise AudioTrimError(f"音频资产 {audio_asset_id!r} 不存在", code="not_found")
    if src.asset_type not in ("audio_original", "audio_trimmed"):
        raise AudioTrimError(
            f"资产类型 {src.asset_type!r} 不支持裁切",
            code="wrong_type",
        )

    logger.info(
        f"开始裁切: asset={audio_asset_id} [{start_sec}s→{end_sec}s]",
        event_type="audio_trim_start",
    )

    storage = get_storage()
    store = LocalArtifactStore(project_id)

    with tempfile.TemporaryDirectory() as tmpdir:
        # ---- 下载原始音频 ------------------------------------------------
        ext = Path(src.object_key).suffix or ".wav"
        src_path = os.path.join(tmpdir, f"original{ext}")
        # BUG-06 修复：download_file 是同步方法且参数顺序与业务意图相反。
        # 改用 async_download_bytes(key, bucket=bucket)，写字节到本地临时路径。
        src_bytes = await storage.async_download_bytes(src.object_key, bucket=src.bucket_name)
        Path(src_path).write_bytes(src_bytes)

        # ---- librosa 按区间加载（保留原采样率，在线程池中执行避免阻塞事件循环）----
        def _load_and_trim() -> tuple:
            return librosa.load(src_path, sr=None, offset=start_sec, duration=duration)

        try:
            y, sr = await asyncio.to_thread(_load_and_trim)
        except Exception as exc:
            raise AudioTrimError(f"librosa 加载失败: {exc}", code="load_failed") from exc

        if len(y) == 0:
            raise AudioTrimError("裁切结果为空音频", code="empty_result")

        # 实际时长（用采样数计算，对 duration=None 全曲情况同样准确）
        actual_duration_sec: float = len(y) / float(sr)

        # ---- 写 WAV 到临时目录（soundfile.write 也是同步 I/O，同样放到线程池）----
        trimmed_path = os.path.join(tmpdir, "trimmed.wav")
        await asyncio.to_thread(sf.write, trimmed_path, y, sr)

        trimmed_bytes = Path(trimmed_path).read_bytes()
        size_bytes = len(trimmed_bytes)
        sha256 = hashlib.sha256(trimmed_bytes).hexdigest()

        # ---- 上传 MinIO --------------------------------------------------
        trimmed_id = generate_ulid()
        object_key = (
            f"projects/{project_id}/assets/audio_trimmed/{trimmed_id}/trimmed.wav"
        )
        # BUG-07 修复：upload_file 是同步方法、参数顺序错误、返回的是 minio:// URI 而非 HTTP 直链。
        # 改用 async_upload_bytes(key, data, content_type)，再通过 get_permanent_url 获取 HTTP 直链。
        await storage.async_upload_bytes(object_key, trimmed_bytes, "audio/wav")
        storage_uri = storage.get_permanent_url(object_key)

        # ---- 本地副本（01_input/ 追溯）----------------------------------
        store.write_bytes(ArtifactStage.INPUT, "audio_trimmed", trimmed_bytes, ext="wav")

        # ---- 创建 Asset 记录 --------------------------------------------
        trimmed_asset = Asset(
            id=trimmed_id,
            project_id=project_id,
            asset_type="audio_trimmed",
            bucket_name=src.bucket_name,
            object_key=object_key,
            storage_uri=storage_uri,
            mime_type="audio/wav",
            size_bytes=size_bytes,
            duration_ms=int(actual_duration_sec * 1000),
            sha256=sha256,
            metadata_={
                "source_asset_id": audio_asset_id,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "sample_rate": int(sr),
                "samples": len(y),
            },
        )
        await asset_repo.add(trimmed_asset)
        await session.flush()
        await session.refresh(trimmed_asset)

    logger.info(
        f"裁切完成: id={trimmed_id} size={size_bytes}B duration={actual_duration_sec:.1f}s sr={sr}",
        event_type="audio_trim_done",
    )
    return trimmed_asset
