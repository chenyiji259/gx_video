"""Seedance 2.0 视频生成适配器（火山方舟 Ark）。

支持模型：
  - doubao-seedance-2-0-260128（高质量）
  - doubao-seedance-2-0-fast-260128（快/便宜）

API 认证：
  Bearer Token，凭据从 get_config().external_apis.ark 读取（ARK_API_KEY 注入）。

异步任务模式：
  POST {base}/contents/generations/tasks  → 提交任务，返回 task_id
  GET  {base}/contents/generations/tasks/{task_id}  → 轮询直到 succeeded / failed

注意：API 路径基于火山方舟 SDK `client.content_generation.tasks` 推测，
实际生产前需用真实 API key 验证。如有偏差请调整 _SUBMIT_PATH / _QUERY_PATH。

特殊参数支持：
  params['reference_image_urls'] - 三图融合 URL 列表（起始 / 中间 / 结尾）
  reference_image_url / params['last_frame_url'] - 旧首尾帧模式兼容字段

文档：docs/api/seedance2-video-generation-api.md
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import aiohttp

from app.core.config import get_config
from app.core.logging import get_logger
from app.core.provider_registry import get_provider_registry
from app.providers.video.base import VideoGenerationError, VideoGenerationMode, VideoResult

_logger = get_logger("seedance_adapter", layer="tool")

_MODEL_NAMES: dict[str, str] = {
    "seedance_2":      "doubao-seedance-2-0-260128",
    "seedance_2_fast": "doubao-seedance-2-0-fast-260128",
}

# REST 路径（基于火山方舟 SDK 资源命名推测，生产前需验证）
_SUBMIT_PATH = "/contents/generations/tasks"
_QUERY_PATH = "/contents/generations/tasks/{task_id}"


class SeedanceAdapter:
    """Seedance 2.0 视频生成适配器（实现 VideoProviderAdapter 协议）。

    用法：
        adapter = SeedanceAdapter("seedance_2")
        result = await adapter.generate(
            "让图片1中的产品展示状态，平滑过渡到图片2中的中间动作，再发展到图片3中的结尾状态，形成一个连续镜头。",
            mode="multi_image_fusion",
            params={
                "reference_image_urls": [
                    "https://.../cell_1.png",
                    "https://.../cell_2.png",
                    "https://.../cell_3.png",
                ],
                "duration": 8,
                "ratio": "9:16",
                "resolution": "1080p",
            },
        )
    """

    def __init__(self, provider_name: str = "seedance_2") -> None:
        if provider_name not in _MODEL_NAMES:
            raise VideoGenerationError(
                f"SeedanceAdapter 不支持 provider: {provider_name!r}, "
                f"可用值: {list(_MODEL_NAMES.keys())}",
                code="unsupported_provider",
            )
        self._provider_name = provider_name
        self._model_name = _MODEL_NAMES[provider_name]

        cfg = get_config()
        ark_cfg = cfg.external_apis.ark
        self._api_key = ark_cfg.api_key
        self._base_url = ark_cfg.base_url.rstrip("/")
        self._timeout = ark_cfg.timeout
        self._poll_interval = ark_cfg.poll_interval
        self._max_poll_attempts = ark_cfg.max_poll_attempts

        registry = get_provider_registry()
        try:
            self._profile = registry.get("video", provider_name)
            self._default_params: dict[str, Any] = dict(self._profile.default_params)
        except (KeyError, AttributeError):
            self._profile = None
            self._default_params = {
                "duration": 8, "ratio": "9:16", "resolution": "1080p",
            }

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        mode: VideoGenerationMode,
        *,
        negative_prompt: Optional[str] = None,
        reference_image_url: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> VideoResult:
        """调用 Seedance 2.0 视频生成。

        Args:
            prompt:               提示词（中英文，须用 "图片1/视频1/音频1" 引用素材）。
            mode:                 multi_image_fusion / image_to_video / text_to_video。
            reference_image_url:  旧兼容模式下的首帧 URL。
            params:               支持以下额外字段：
                reference_image_urls  三图融合参考图列表
                last_frame_url        旧兼容模式尾帧 URL
                duration / ratio / resolution
                generate_audio / watermark
        """
        if not self._api_key:
            raise VideoGenerationError(
                "ARK api_key 未配置，"
                "请在 config/base/external_apis.yaml 中填写 ark.api_key",
                code="api_key_missing",
            )

        if mode == "image_to_video" and not reference_image_url:
            raise VideoGenerationError(
                "image_to_video 模式必须提供 reference_image_url（首帧）",
                code="missing_reference_image",
            )

        if mode not in ("image_to_video", "text_to_video", "multi_image_fusion"):
            raise VideoGenerationError(
                f"Seedance 2.0 不支持的生成模式: {mode!r}",
                code="unsupported_mode",
            )

        merged: dict[str, Any] = dict(self._default_params)
        if params:
            merged.update(params)

        # 字段映射（兼容 base.py 的通用字段名）
        if "duration_sec" in merged:
            merged["duration"] = int(merged.pop("duration_sec"))
        if "aspect_ratio" in merged:
            merged["ratio"] = merged.pop("aspect_ratio")

        last_frame_url: Optional[str] = merged.pop("last_frame_url", None)
        reference_image_urls: list[str] = list(merged.pop("reference_image_urls", []) or [])
        if mode == "multi_image_fusion" and len(reference_image_urls) < 3:
            raise VideoGenerationError(
                "multi_image_fusion 模式必须提供 3 张参考图（起始 / 中间 / 结尾）",
                code="missing_reference_images",
            )

        payload = self._build_payload(
            prompt=prompt,
            mode=mode,
            first_frame_url=reference_image_url,
            last_frame_url=last_frame_url,
            reference_image_urls=reference_image_urls,
            merged=merged,
        )

        _logger.info(
            f"Seedance 2.0 提交: model={self._model_name!r} mode={mode!r} "
            f"duration={payload['duration']}s ratio={payload['ratio']!r} "
            f"multi_ref_count={len(reference_image_urls)} "
            f"legacy_first_last={bool(reference_image_url or last_frame_url)} "
            f"prompt_len={len(prompt)}",
            event_type="seedance_submit",
        )

        task_id = await self._submit_task(payload)
        return await self._poll_task(task_id)

    # ------------------------------------------------------------------
    # 内部：构建请求体
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        *,
        prompt: str,
        mode: VideoGenerationMode,
        first_frame_url: Optional[str],
        last_frame_url: Optional[str],
        reference_image_urls: list[str],
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        """构建 Seedance 2.0 任务请求体（含 content 数组）。"""
        # content 数组：text + 多模态素材（doc 21 §6 文档 §6）
        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt}
        ]

        if mode == "multi_image_fusion":
            for image_url in reference_image_urls[:3]:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": image_url},
                })
        elif mode == "image_to_video":
            if first_frame_url:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": first_frame_url},
                    "role": "first_frame",
                })
            if last_frame_url:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": last_frame_url},
                    "role": "last_frame",
                })

        return {
            "model": self._model_name,
            "content": content,
            "ratio": merged.get("ratio", "9:16"),
            "duration": int(merged.get("duration", 8)),
            "resolution": merged.get("resolution", "1080p"),
            "generate_audio": bool(merged.get("generate_audio", False)),
            "watermark": bool(merged.get("watermark", False)),
        }

    # ------------------------------------------------------------------
    # 内部：提交任务
    # ------------------------------------------------------------------

    async def _submit_task(self, payload: dict[str, Any]) -> str:
        url = f"{self._base_url}{_SUBMIT_PATH}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=self._timeout)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status not in (200, 201, 202):
                        text = await resp.text()
                        raise VideoGenerationError(
                            f"Seedance 提交失败 HTTP {resp.status}: {text[:300]}",
                            code="api_error",
                        )
                    data: dict[str, Any] = await resp.json()
        except asyncio.TimeoutError as exc:
            raise VideoGenerationError(
                f"Seedance 提交超时（{self._timeout}s）", code="timeout"
            ) from exc
        except aiohttp.ClientError as exc:
            raise VideoGenerationError(
                f"Seedance 网络错误: {exc}", code="network_error"
            ) from exc

        if "error" in data:
            err = data["error"]
            raise VideoGenerationError(
                f"Seedance API 错误: {err.get('message', str(err))}",
                code="api_error",
            )

        task_id = data.get("id")
        if not task_id:
            raise VideoGenerationError(
                "Seedance 未返回任务 ID", code="missing_task_id"
            )
        _logger.info(
            f"Seedance 任务已提交: task_id={task_id!r} model={self._model_name!r}",
            event_type="seedance_task_submitted",
        )
        return str(task_id)

    # ------------------------------------------------------------------
    # 内部：轮询任务
    # ------------------------------------------------------------------

    async def _poll_task(self, task_id: str) -> VideoResult:
        url = f"{self._base_url}{_QUERY_PATH.format(task_id=task_id)}"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        poll_timeout = aiohttp.ClientTimeout(total=30)

        for attempt in range(self._max_poll_attempts):
            await asyncio.sleep(self._poll_interval)

            try:
                async with aiohttp.ClientSession(timeout=poll_timeout) as session:
                    async with session.get(url, headers=headers) as resp:
                        if resp.status != 200:
                            _logger.warning(
                                f"Seedance 轮询非 200（attempt={attempt + 1}）: "
                                f"HTTP {resp.status}",
                                event_type="seedance_poll_http_error",
                            )
                            continue
                        data: dict[str, Any] = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                _logger.warning(
                    f"Seedance 轮询网络错误 (attempt={attempt + 1}/"
                    f"{self._max_poll_attempts}): {exc}",
                    event_type="seedance_poll_network_error",
                )
                continue

            status = data.get("status", "")

            # 文档 §10 状态：succeeded / failed / running
            if status in ("succeeded", "completed"):
                _logger.info(
                    f"Seedance 任务完成: task_id={task_id!r}",
                    event_type="seedance_task_completed",
                )
                return self._parse_result(data)

            if status == "failed":
                err = data.get("error", {})
                msg = err.get("message", status) if isinstance(err, dict) else str(err)
                _logger.warning(
                    f"Seedance 任务失败: task_id={task_id!r} reason={msg!r}",
                    event_type="seedance_task_failed",
                )
                raise VideoGenerationError(
                    f"Seedance 任务失败: {msg}", code="task_failed"
                )

            _logger.info(
                f"Seedance 轮询 attempt={attempt + 1}/{self._max_poll_attempts} "
                f"status={status!r} task_id={task_id!r}",
                event_type="seedance_poll",
            )

        raise VideoGenerationError(
            f"Seedance 任务在 {self._max_poll_attempts * self._poll_interval}s 内未完成",
            code="timeout",
        )

    # ------------------------------------------------------------------
    # 内部：解析结果
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_result(data: dict[str, Any]) -> VideoResult:
        """从 succeeded 任务数据中提取 VideoResult。

        响应格式（doc §10）：
        {
          "status": "succeeded",
          "content": {
            "video_url": "https://...",
            ...
          },
          "usage": {...},
          ...
        }
        """
        content = data.get("content", {})
        video_url = content.get("video_url", "")

        # 兼容备选格式（部分 API 返回 result.video_url）
        if not video_url:
            result = data.get("result", {})
            if isinstance(result, dict):
                video_url = result.get("video_url") or (
                    (result.get("data") or [{}])[0].get("url", "")
                )

        if not video_url:
            raise VideoGenerationError(
                f"Seedance 任务结果中无视频 URL: {str(data)[:200]}",
                code="empty_url",
            )

        return VideoResult(
            video_url=video_url,
            provider_meta=data,
        )
