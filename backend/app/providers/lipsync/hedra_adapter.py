"""Hedra AI（Character-2）LipSync 适配器。

来源文档：doc 09 任务 13-03

Hedra Character-2 API 流程：
  1. POST /v1/characters（multipart/form-data）
     - avatar_image_input: 正脸参考图 URL 或 base64
     - audio_source: 音频文件 URL
     - aspect_ratio: "1:1" | "9:16" | "16:9"
  2. GET /v1/characters/{id} 轮询
     - status: "processing" → "completed" | "error"
  3. completed 时返回 video_url

认证：
  Authorization: Bearer {api_key}
  api_key 全从 get_config().external_apis.hedra 读取，绝不 hardcode。

文档参考：https://www.hedra.com/developers
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from app.core.config import get_config
from app.core.logging import get_logger
from app.providers.lipsync.base import LipSyncError, LipSyncResult

_logger = get_logger("hedra_adapter", layer="tool")


class HedraAdapter:
    """Hedra Character-2 LipSync 适配器，实现 LipSyncProviderAdapter 协议。

    用法：
        adapter = HedraAdapter("hedra_character")
        result = await adapter.generate(
            face_image_url="https://...",
            audio_url="https://...",
            duration_sec=4.8,
            params={"aspect_ratio": "9:16"},
        )
    """

    def __init__(self, provider_name: str = "hedra_character") -> None:
        self._provider_name = provider_name
        cfg = get_config().external_apis.hedra
        self._api_key = cfg.api_key
        self._base_url = cfg.base_url.rstrip("/")
        self._timeout = cfg.timeout
        self._poll_interval = cfg.poll_interval
        self._max_poll_attempts = cfg.max_poll_attempts

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def generate(
        self,
        face_image_url: str,
        audio_url: str,
        duration_sec: float,
        *,
        params: Optional[dict[str, Any]] = None,
    ) -> LipSyncResult:
        """调用 Hedra API 生成 LipSync 视频。

        Args:
            face_image_url: 正脸参考图 URL（公网可访问）。
            audio_url:      音频片段 URL（公网可访问）。
            duration_sec:   目标时长（秒，仅作日志用，Hedra 按音频时长自动判断）。
            params:         覆盖默认参数（aspect_ratio / resolution 等）。

        Raises:
            LipSyncError: API key 缺失、生成失败、超时等。
        """
        if not self._api_key:
            raise LipSyncError(
                "Hedra API key 未配置，"
                "请在 config/base/external_apis.yaml 中填写 hedra.api_key",
                code="api_key_missing",
            )
        if not face_image_url:
            raise LipSyncError(
                "face_image_url 不能为空（hedra_character 需要正脸参考图）",
                code="missing_face_image",
            )
        if not audio_url:
            raise LipSyncError(
                "audio_url 不能为空",
                code="missing_audio",
            )

        merged: dict[str, Any] = {"aspect_ratio": "9:16", "resolution": "540p"}
        if params:
            merged.update(params)

        _logger.info(
            f"Hedra LipSync 请求: provider={self._provider_name!r} "
            f"duration={duration_sec:.1f}s aspect_ratio={merged['aspect_ratio']!r}",
            event_type="hedra_generate_start",
        )

        character_id = await self._submit_task(
            face_image_url=face_image_url,
            audio_url=audio_url,
            aspect_ratio=merged["aspect_ratio"],
            resolution=merged.get("resolution", "540p"),
        )
        result = await self._poll_task(character_id)

        _logger.info(
            f"Hedra LipSync 完成: character_id={character_id!r}",
            event_type="hedra_generate_done",
        )
        return result

    # ------------------------------------------------------------------
    # 内部：提交任务
    # ------------------------------------------------------------------

    async def _submit_task(
        self,
        face_image_url: str,
        audio_url: str,
        aspect_ratio: str,
        resolution: str,
    ) -> str:
        """提交 character 生成任务，返回 character_id。"""
        url = f"{self._base_url}/v1/characters"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "avatarImage": face_image_url,
            "audioSource": audio_url,
            "aspectRatio": aspect_ratio,
            "resolution": resolution,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise LipSyncError(
                    f"Hedra 提交请求超时（{self._timeout}s）", code="timeout"
                ) from exc
            except httpx.RequestError as exc:
                raise LipSyncError(
                    f"Hedra 网络请求失败: {exc}", code="network_error"
                ) from exc

            if resp.status_code not in (200, 201, 202):
                raise LipSyncError(
                    f"Hedra 提交失败 HTTP {resp.status_code}: {resp.text[:300]}",
                    code="api_error",
                )

            data = resp.json()

        # 响应格式：{"jobId": "...", "status": "queued", ...}
        # 也可能是 {"id": "...", "status": "processing"}
        character_id = (
            data.get("jobId")
            or data.get("id")
            or data.get("character_id")
        )
        if not character_id:
            raise LipSyncError(
                f"Hedra 未返回 character_id / jobId，响应: {str(data)[:200]}",
                code="missing_job_id",
            )
        _logger.info(
            f"Hedra 任务已提交: character_id={character_id!r}",
            event_type="hedra_task_submitted",
        )
        return str(character_id)

    # ------------------------------------------------------------------
    # 内部：轮询任务
    # ------------------------------------------------------------------

    async def _poll_task(self, character_id: str) -> LipSyncResult:
        """轮询 character 状态直到完成，返回 LipSyncResult。"""
        url = f"{self._base_url}/v1/characters/{character_id}"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        for attempt in range(self._max_poll_attempts):
            await asyncio.sleep(self._poll_interval)

            async with httpx.AsyncClient(timeout=30) as client:
                try:
                    resp = await client.get(url, headers=headers)
                except httpx.RequestError as exc:
                    _logger.warning(
                        f"Hedra 轮询网络错误（attempt={attempt + 1}/"
                        f"{self._max_poll_attempts}）: {exc}",
                        event_type="hedra_poll_network_error",
                    )
                    continue

                if resp.status_code != 200:
                    _logger.warning(
                        f"Hedra 轮询 HTTP {resp.status_code}，继续等待",
                        event_type="hedra_poll_http_error",
                    )
                    continue

                data = resp.json()

            status = (
                data.get("status")
                or data.get("jobStatus")
                or ""
            ).lower()

            if status in ("completed", "succeeded", "success"):
                return self._parse_result(data, character_id)

            if status in ("error", "failed", "cancelled"):
                reason = (
                    data.get("errorMessage")
                    or data.get("error")
                    or status
                )
                raise LipSyncError(
                    f"Hedra 任务失败: {reason}", code="task_failed"
                )

            # queued / processing → 继续等待
            _logger.info(
                f"Hedra 轮询 attempt={attempt + 1}/{self._max_poll_attempts} "
                f"status={status!r} character_id={character_id!r}",
                event_type="hedra_poll",
            )

        raise LipSyncError(
            f"Hedra 任务在 "
            f"{self._max_poll_attempts * self._poll_interval}s 内未完成",
            code="timeout",
        )

    # ------------------------------------------------------------------
    # 内部：解析结果
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_result(data: dict[str, Any], character_id: str) -> LipSyncResult:
        """从 Hedra 任务数据中提取 LipSyncResult。

        Hedra 响应格式（示例）：
          {
            "id": "...",
            "status": "completed",
            "videoUrl": "https://...",
            "durationMs": 4800
          }
        """
        video_url = (
            data.get("videoUrl")
            or data.get("video_url")
            or data.get("resultUrl")
            or data.get("result_url")
            or ""
        )
        if not video_url:
            raise LipSyncError(
                f"Hedra 任务结果中无视频 URL: {str(data)[:200]}",
                code="empty_result",
            )

        duration_sec: Optional[float] = None
        duration_ms = data.get("durationMs") or data.get("duration_ms")
        if duration_ms is not None:
            try:
                duration_sec = float(duration_ms) / 1000.0
            except (ValueError, TypeError):
                pass

        return LipSyncResult(
            video_url=video_url,
            duration_sec=duration_sec,
            provider_meta={"character_id": character_id, **data},
        )
