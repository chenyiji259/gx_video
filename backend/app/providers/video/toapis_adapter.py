"""ToAPIs Grok 系列视频生成适配器。

支持模型：
  - grok-imagine-1.0-video：时长 6-30s，支持多图（最多 7 张），图字段 image_urls
  - grok-video-3：时长 10s / 15s，图字段 images，分辨率通过 metadata.resolution 传递

API 认证：
  Bearer Token，凭据从 get_config().external_apis.toapis 读取。

文档：https://docs.toapis.com
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import aiohttp

from app.core.config import get_config
from app.core.logging import get_logger
from app.core.provider_registry import get_provider_registry
from app.providers.video.base import VideoGenerationError, VideoGenerationMode, VideoResult

_logger = get_logger("toapis_adapter", layer="tool")

# 两个模型的 API model 名称映射
_MODEL_NAMES: dict[str, str] = {
    "grok_imagine_10_video": "grok-imagine-1.0-video",
    "grok_video_3": "grok-video-3",
}

# 提交 / 查询接口路径
_SUBMIT_PATH = "/v1/videos/generations"
_QUERY_PATH = "/v1/videos/generations/{task_id}"


class ToAPIsAdapter:
    """ToAPIs Grok 视频生成适配器，实现 VideoProviderAdapter 协议。

    用法：
        adapter = ToAPIsAdapter("grok_video_3")
        result = await adapter.generate(
            "cinematic slow push-in, rain night street",
            mode="image_to_video",
            reference_image_url="https://...",
            params={"duration": 10},
        )
    """

    def __init__(self, provider_name: str = "grok_video_3") -> None:
        if provider_name not in _MODEL_NAMES:
            raise VideoGenerationError(
                f"ToAPIsAdapter 不支持 provider: {provider_name!r}，"
                f"可用值：{list(_MODEL_NAMES.keys())}",
                code="unsupported_provider",
            )
        self._provider_name = provider_name
        self._model_name = _MODEL_NAMES[provider_name]

        cfg = get_config()
        toapis_cfg = cfg.external_apis.toapis
        self._api_key = toapis_cfg.api_key
        self._base_url = toapis_cfg.base_url.rstrip("/")
        self._timeout = toapis_cfg.timeout
        self._poll_interval = toapis_cfg.poll_interval
        self._max_poll_attempts = toapis_cfg.max_poll_attempts

        # 从 ProviderRegistry 读取默认参数
        registry = get_provider_registry()
        try:
            self._profile = registry.get("video", provider_name)
            self._default_params: dict[str, Any] = dict(self._profile.default_params)
        except (KeyError, AttributeError):
            self._profile = None
            self._default_params = {"duration": 10, "aspect_ratio": "16:9"}

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
        """调用 ToAPIs Grok 视频生成 API。

        Args:
            prompt:               正向提示词（支持中英文）。
            mode:                 生成模式（image_to_video / text_to_video）。
            negative_prompt:      负向提示词（ToAPIs 当前不支持，忽略）。
            reference_image_url:  image_to_video 模式必须提供首帧图片 URL（公网可访问）。
            params:               覆盖默认参数（duration / aspect_ratio / quality / resolution 等）。

        Raises:
            VideoGenerationError: API key 缺失、生成失败、超时等。
        """
        if not self._api_key:
            raise VideoGenerationError(
                "ToAPIs api_key 未配置，"
                "请在 config/base/external_apis.yaml 中填写 toapis.api_key",
                code="api_key_missing",
            )

        if mode == "image_to_video" and not reference_image_url:
            raise VideoGenerationError(
                "image_to_video 模式必须提供 reference_image_url",
                code="missing_reference_image",
            )

        if mode not in ("image_to_video", "text_to_video"):
            raise VideoGenerationError(
                f"ToAPIs 不支持的生成模式: {mode!r}",
                code="unsupported_mode",
            )

        # 合并参数
        merged: dict[str, Any] = dict(self._default_params)
        if params:
            merged.update(params)

        # duration_sec → duration 字段映射
        if "duration_sec" in merged:
            merged["duration"] = int(merged.pop("duration_sec"))

        payload = self._build_payload(prompt, mode, reference_image_url, merged)

        _logger.info(
            f"ToAPIs 视频生成请求: model={self._model_name!r} "
            f"mode={mode!r} duration={payload.get('duration')}s "
            f"prompt_len={len(prompt)}",
            event_type="toapis_generate_start",
        )

        task_id = await self._submit_task(payload)
        result = await self._poll_task(task_id)

        _logger.info(
            f"ToAPIs 视频生成完成: task_id={task_id!r}",
            event_type="toapis_generate_done",
        )
        return result

    # ------------------------------------------------------------------
    # 内部：构建请求体
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        prompt: str,
        mode: VideoGenerationMode,
        reference_image_url: Optional[str],
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        """根据 provider 差异构建正确的请求体。"""
        payload: dict[str, Any] = {
            "model": self._model_name,
            "prompt": prompt,
            "duration": int(merged.get("duration", 10)),
            "aspect_ratio": merged.get("aspect_ratio", "16:9"),
        }

        if self._provider_name == "grok_imagine_10_video":
            # grok-imagine-1.0-video：quality 字段，图片字段为 image_urls
            payload["quality"] = merged.get("quality", "720p")
            if mode == "image_to_video" and reference_image_url:
                payload["image_urls"] = [reference_image_url]

        elif self._provider_name == "grok_video_3":
            # grok-video-3：resolution 走 metadata，图片字段为 images
            resolution = merged.get("resolution", "1080P")
            payload["metadata"] = {"resolution": resolution}
            if mode == "image_to_video" and reference_image_url:
                payload["images"] = [reference_image_url]

        return payload

    # ------------------------------------------------------------------
    # 内部：提交任务
    # ------------------------------------------------------------------

    async def _submit_task(self, payload: dict[str, Any]) -> str:
        """提交视频生成任务，返回 task_id。"""
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
                            f"ToAPIs 提交失败 HTTP {resp.status}: {text[:300]}",
                            code="api_error",
                        )
                    data: dict[str, Any] = await resp.json()
        except asyncio.TimeoutError as exc:
            raise VideoGenerationError(
                f"ToAPIs 提交请求超时（{self._timeout}s）", code="timeout"
            ) from exc
        except aiohttp.ClientError as exc:
            raise VideoGenerationError(
                f"ToAPIs 网络请求失败: {exc}", code="network_error"
            ) from exc

        # 检查是否有错误
        if "error" in data:
            err = data["error"]
            raise VideoGenerationError(
                f"ToAPIs API 错误: {err.get('message', str(err))}",
                code="api_error",
            )

        task_id = data.get("id")
        if not task_id:
            raise VideoGenerationError(
                "ToAPIs 未返回任务 ID", code="missing_task_id"
            )
        _logger.info(
            f"ToAPIs 任务已提交: task_id={task_id!r} model={self._model_name!r}",
            event_type="toapis_task_submitted",
        )
        return str(task_id)

    # ------------------------------------------------------------------
    # 内部：轮询任务
    # ------------------------------------------------------------------

    async def _poll_task(self, task_id: str) -> VideoResult:
        """轮询任务状态直到完成，返回 VideoResult。"""
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
                                f"ToAPIs 轮询非 200（attempt={attempt + 1}）: "
                                f"HTTP {resp.status}",
                                event_type="toapis_poll_http_error",
                            )
                            continue
                        data: dict[str, Any] = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                _logger.warning(
                    f"ToAPIs 轮询网络错误（attempt={attempt + 1}/"
                    f"{self._max_poll_attempts}），将在下次尝试继续: {exc}",
                    event_type="toapis_poll_network_error",
                )
                continue

            status = data.get("status", "")
            progress = data.get("progress", 0)

            if status == "completed":
                _logger.info(
                    f"ToAPIs 任务已完成: task_id={task_id!r}",
                    event_type="toapis_task_completed",
                )
                return self._parse_result(data)

            if status == "failed":
                err = data.get("error", {})
                reason = err.get("message", status) if isinstance(err, dict) else str(err)
                _logger.warning(
                    f"ToAPIs 任务失败: task_id={task_id!r} reason={reason!r}",
                    event_type="toapis_task_failed",
                )
                raise VideoGenerationError(
                    f"ToAPIs 任务失败: {reason}", code="task_failed"
                )

            # queued / in_progress → 继续等待
            _logger.info(
                f"ToAPIs 轮询 attempt={attempt + 1}/{self._max_poll_attempts} "
                f"status={status!r} progress={progress}% task_id={task_id!r}",
                event_type="toapis_poll",
            )

        raise VideoGenerationError(
            f"ToAPIs 任务在 {self._max_poll_attempts * self._poll_interval}s 内未完成",
            code="timeout",
        )

    # ------------------------------------------------------------------
    # 内部：解析结果
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_result(data: dict[str, Any]) -> VideoResult:
        """从完成的任务数据中提取 VideoResult。

        响应格式：
        {
          "status": "completed",
          "result": {
            "type": "video",
            "data": [{"url": "https://...", "format": "mp4"}]
          }
        }
        """
        result = data.get("result", {})
        video_list = result.get("data", [])

        if not video_list:
            raise VideoGenerationError(
                f"ToAPIs 任务结果中无视频数据: {str(data)[:200]}",
                code="empty_result",
            )

        video_url = video_list[0].get("url", "")
        if not video_url:
            raise VideoGenerationError(
                "ToAPIs 返回视频 URL 为空", code="empty_url"
            )

        return VideoResult(
            video_url=video_url,
            provider_meta=data,
        )
