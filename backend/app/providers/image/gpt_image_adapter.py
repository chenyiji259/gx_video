"""GPT Image 2 图片生成适配器（doc 21 §1.4 / docs/api/HarvAI 文档）。

支持模型：
  - gpt-image-2（ToApis 中转）

接入约束（当前项目主链路）：
  - 九宫格主链路按像素尺寸直传 size，例如 3072x3072 / 1728x3072 / 3072x1728
  - metadata.resolution 走项目侧决策（当前默认 2K）
  - metadata.orientation 按 portrait / landscape / square 传入
  - 仍兼容旧的 aspect_ratio 比例模式，作为兜底

API 认证：
  Bearer Token，凭据从 get_config().external_apis.toapis 读取（与 toapis 视频共用一个 key）。

异步任务模式：
  POST /v1/images/generations  → 提交任务，返回 task_id
  GET  /v1/images/generations/{task_id}  → 轮询直到 completed / failed

文档：docs/api/HarvAI_API_接入文档_Qwen36Plus_ToApis_GPTImage2.md
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import aiohttp

from app.core.config import get_config
from app.core.logging import get_logger
from app.core.provider_registry import get_provider_registry
from app.providers.image.base import ImageGenerationError, ImageResult

_logger = get_logger("gpt_image_adapter", layer="tool")

# API 路径
_SUBMIT_PATH = "/v1/images/generations"
_QUERY_PATH = "/v1/images/generations/{task_id}"

_RATIO_TO_PIXEL_SIZE: dict[str, str] = {
    "1:1": "3072x3072",
    "9:16": "1728x3072",
    "2:3": "1728x3072",
    "3:4": "1728x3072",
    "16:9": "3072x1728",
    "3:2": "3072x1728",
    "4:3": "3072x1728",
}


def _classify_orientation_from_ratio(ratio: str) -> str:
    """从宽高比字符串推导 portrait / landscape / square。"""
    ratio_str = (ratio or "1:1").strip().lower()
    if ratio_str == "1:1":
        return "square"

    try:
        parts = ratio_str.split(":")
        if len(parts) != 2:
            return "square"
        w, h = float(parts[0]), float(parts[1])
        if h == 0:
            return "square"
        v = w / h
        if abs(v - 1.0) < 0.05:
            return "square"
        return "landscape" if v > 1 else "portrait"
    except Exception:  # noqa: BLE001
        return "square"


def _resolve_request_shape(params: dict[str, Any]) -> tuple[str, str, str]:
    """解析 GPT Image 2 请求尺寸。

    返回：
      size          像素尺寸，例如 3072x3072
      resolution    2K / 4K / 1K
      orientation   portrait / landscape / square
    """
    requested_size = str(params.get("size") or "").strip()
    requested_resolution = str(params.get("resolution") or "2K").strip() or "2K"
    requested_orientation = str(params.get("orientation") or "").strip().lower()

    if requested_size:
        if requested_orientation:
            orientation = requested_orientation
        else:
            try:
                w_str, h_str = requested_size.lower().split("x", 1)
                w = int(w_str.strip())
                h = int(h_str.strip())
                if w == h:
                    orientation = "square"
                else:
                    orientation = "landscape" if w > h else "portrait"
            except Exception:  # noqa: BLE001
                orientation = "square"
        return requested_size, requested_resolution, orientation

    ratio_input = str(params.get("aspect_ratio") or "1:1").strip()
    size = _RATIO_TO_PIXEL_SIZE.get(ratio_input, "3072x3072")
    orientation = _classify_orientation_from_ratio(ratio_input)
    return size, requested_resolution, orientation


class GPTImageAdapter:
    """GPT Image 2 图片生成适配器（实现 ImageProviderAdapter 协议）。"""

    def __init__(self, provider_name: str = "gpt_image_2") -> None:
        self._provider_name = provider_name
        self._model_name = "gpt-image-2"

        cfg = get_config()
        toapis_cfg = cfg.external_apis.toapis
        self._api_key = toapis_cfg.api_key
        self._base_url = toapis_cfg.base_url.rstrip("/")
        self._timeout = toapis_cfg.timeout
        self._poll_interval = toapis_cfg.poll_interval
        self._max_poll_attempts = toapis_cfg.max_poll_attempts

        registry = get_provider_registry()
        try:
            self._profile = registry.get("image", provider_name)
            self._default_params: dict[str, Any] = dict(self._profile.default_params)
        except (KeyError, AttributeError):
            self._profile = None
            self._default_params = {"size": "3072x3072", "resolution": "2K", "orientation": "square", "n": 1}

    # ------------------------------------------------------------------
    # 公共接口（ImageProviderAdapter 协议）
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> ImageResult:
        """文生图（gpt-image-2 不支持 negative_prompt，忽略此参数）。"""
        return await self._submit_and_poll(
            prompt=prompt,
            params=params or {},
            reference_images=None,
        )

    async def generate_img2img(
        self,
        prompt: str,
        image_url: str,
        strength: float = 0.75,
        negative_prompt: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> ImageResult:
        """图生图（单张参考图，通过 reference_images 传入）。"""
        return await self._submit_and_poll(
            prompt=prompt,
            params=params or {},
            reference_images=[image_url],
        )

    async def generate_multi_ref_img2img(
        self,
        prompt: str,
        image_urls: list[str],
        strength: float = 0.75,
        negative_prompt: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> ImageResult:
        """多参考图（GPT Image 2 文档建议最多 3 张）。"""
        if len(image_urls) > 3:
            _logger.warning(
                f"GPT Image 2 截断参考图数量 {len(image_urls)} → 3",
                event_type="gpt_image_truncate_refs",
            )
        return await self._submit_and_poll(
            prompt=prompt,
            params=params or {},
            reference_images=list(image_urls[:3]),
        )

    # ------------------------------------------------------------------
    # 内部：提交 + 轮询
    # ------------------------------------------------------------------

    async def _submit_and_poll(
        self,
        *,
        prompt: str,
        params: dict[str, Any],
        reference_images: Optional[list[str]],
    ) -> ImageResult:
        if not self._api_key:
            raise ImageGenerationError(
                "ToAPIs api_key 未配置，"
                "请在 config/base/external_apis.yaml 中填写 toapis.api_key",
                code="api_key_missing",
            )

        # prompt 长度校验（官方上限 4000 字符）
        if len(prompt) > 4000:
            _logger.warning(
                f"prompt 长度截断 {len(prompt)} → 4000",
                event_type="gpt_image_prompt_truncated",
            )
            prompt = prompt[:4000]

        # 合并参数
        merged: dict[str, Any] = dict(self._default_params)
        merged.update(params)

        size, resolution, orientation = _resolve_request_shape(merged)

        payload: dict[str, Any] = {
            "model": self._model_name,
            "prompt": prompt,
            "size": size,
            "n": int(merged.get("n", 1)),
            "response_format": "url",
            "metadata": {
                "orientation": orientation,
                "resolution": resolution,
            },
        }
        if reference_images:
            payload["reference_images"] = reference_images

        _logger.info(
            f"GPT Image 2 提交: size={size!r} resolution={resolution!r} orientation={orientation!r} "
            f"refs={len(reference_images or [])} prompt_len={len(prompt)} "
            f"poll_interval={self._poll_interval}s max_attempts={self._max_poll_attempts}",
            event_type="gpt_image_submit",
        )

        task_id = await self._submit_task(payload)
        return await self._poll_task(task_id, requested_size=size)

    async def _submit_task(self, payload: dict[str, Any]) -> str:
        """POST /v1/images/generations → 返回 task_id。"""
        url = f"{self._base_url}{_SUBMIT_PATH}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=self._timeout)

        submit_started_at = time.monotonic()
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status not in (200, 201, 202):
                        text = await resp.text()
                        raise ImageGenerationError(
                            f"GPT Image 2 提交失败 HTTP {resp.status}: {text[:300]}",
                            code="api_error",
                        )
                    data: dict[str, Any] = await resp.json()
        except asyncio.TimeoutError as exc:
            raise ImageGenerationError(
                f"GPT Image 2 提交超时（{self._timeout}s）", code="timeout"
            ) from exc
        except aiohttp.ClientError as exc:
            raise ImageGenerationError(
                f"GPT Image 2 网络错误: {exc}", code="network_error"
            ) from exc

        if "error" in data:
            err = data["error"]
            raise ImageGenerationError(
                f"GPT Image 2 API 错误: {err.get('message', str(err))}",
                code="api_error",
            )

        task_id = data.get("id")
        if not task_id:
            raise ImageGenerationError(
                "GPT Image 2 未返回任务 ID", code="missing_task_id"
            )
        _logger.info(
            f"GPT Image 2 任务已提交: task_id={task_id!r} "
            f"elapsed={time.monotonic() - submit_started_at:.2f}s",
            event_type="gpt_image_task_submitted",
        )
        return str(task_id)

    async def _poll_task(self, task_id: str, requested_size: str) -> ImageResult:
        """GET /v1/images/generations/{task_id} 轮询直到完成。"""
        url = f"{self._base_url}{_QUERY_PATH.format(task_id=task_id)}"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        poll_timeout = aiohttp.ClientTimeout(total=30)

        poll_started_at = time.monotonic()
        # 文档建议初始等待 2s
        await asyncio.sleep(2)

        for attempt in range(self._max_poll_attempts):
            try:
                async with aiohttp.ClientSession(timeout=poll_timeout) as session:
                    async with session.get(url, headers=headers) as resp:
                        if resp.status != 200:
                            _logger.warning(
                                f"GPT Image 2 轮询非 200（attempt={attempt + 1}）: "
                                f"HTTP {resp.status}",
                                event_type="gpt_image_poll_http_error",
                            )
                            await asyncio.sleep(self._poll_interval)
                            continue
                        data: dict[str, Any] = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                _logger.warning(
                    f"GPT Image 2 轮询网络错误 (attempt={attempt + 1}/"
                    f"{self._max_poll_attempts}): {exc}",
                    event_type="gpt_image_poll_error",
                )
                await asyncio.sleep(self._poll_interval)
                continue

            status = data.get("status", "")
            progress = data.get("progress", 0)

            if status == "completed":
                _logger.info(
                    f"GPT Image 2 任务完成: task_id={task_id!r} "
                    f"elapsed={time.monotonic() - poll_started_at:.2f}s",
                    event_type="gpt_image_task_completed",
                )
                return self._parse_result(data, requested_size=requested_size)

            if status == "failed":
                err = data.get("error", {})
                msg = err.get("message", status) if isinstance(err, dict) else str(err)
                _logger.warning(
                    f"GPT Image 2 任务失败: task_id={task_id!r} reason={msg!r}",
                    event_type="gpt_image_task_failed",
                )
                raise ImageGenerationError(
                    f"GPT Image 2 任务失败: {msg}", code="task_failed"
                )

            # queued / in_progress
            _logger.info(
                f"GPT Image 2 轮询 attempt={attempt + 1}/{self._max_poll_attempts} "
                f"status={status!r} progress={progress}% task_id={task_id!r} "
                f"elapsed={time.monotonic() - poll_started_at:.2f}s",
                event_type="gpt_image_poll",
            )
            await asyncio.sleep(self._poll_interval)

        _logger.warning(
            f"GPT Image 2 任务轮询超时: task_id={task_id!r} "
            f"elapsed={time.monotonic() - poll_started_at:.2f}s",
            event_type="gpt_image_poll_timeout",
        )
        raise ImageGenerationError(
            f"GPT Image 2 任务在 {self._max_poll_attempts * self._poll_interval}s 内未完成",
            code="timeout",
        )

    @staticmethod
    def _parse_result(data: dict[str, Any], *, requested_size: str) -> ImageResult:
        """从 completed 任务数据中提取 ImageResult。

        响应格式：
        {
          "status": "completed",
          "result": {
            "type": "image",
            "data": [{"url": "https://..."}]
          }
        }
        """
        result = data.get("result", {})
        images = result.get("data", [])

        if not images:
            raise ImageGenerationError(
                f"GPT Image 2 任务结果中无图片数据: {str(data)[:200]}",
                code="empty_result",
            )

        image_url = images[0].get("url", "")
        if not image_url:
            raise ImageGenerationError(
                "GPT Image 2 返回图片 URL 为空", code="empty_url"
            )

        try:
            width_str, height_str = requested_size.lower().split("x", 1)
            width, height = int(width_str.strip()), int(height_str.strip())
        except Exception:  # noqa: BLE001
            width, height = 3072, 3072

        return ImageResult(
            image_url=image_url,
            width=width,
            height=height,
            provider_meta=data,
        )
