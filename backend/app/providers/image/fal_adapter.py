"""FAL.ai 图片生成适配器。

来源文档：doc 09 任务 10-02

支持 FAL.ai 托管的 FLUX 系列模型：
  - flux_schnell（默认，~3-8s，同步响应）
  - flux_dev（约 20-60s，需轮询）

API 认证：
  api_key 从 get_config().external_apis.fal_ai.api_key 读取，
  绝不使用 os.getenv()，全从配置系统。

FAL.ai API 文档：https://fal.ai/docs
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from app.core.config import get_config
from app.core.logging import get_logger
from app.core.provider_registry import get_provider_registry
from app.providers.image.base import ImageGenerationError, ImageResult

_logger = get_logger("fal_adapter", layer="tool")


# ---------------------------------------------------------------------------
# endpoint 映射：provider_name → fal.run path
# ---------------------------------------------------------------------------

_PROVIDER_ENDPOINT_MAP: dict[str, str] = {
    "flux_schnell": "/fal-ai/flux/schnell",
    "flux_dev": "/fal-ai/flux/dev",
    "stable_diffusion_xl": "/fal-ai/sdxl",
}

# image-to-image 端点（doc11 批次2）
_IMG2IMG_ENDPOINT_MAP: dict[str, str] = {
    "flux_dev": "/fal-ai/flux/dev/image-to-image",
    "flux_schnell": "/fal-ai/flux/schnell/image-to-image",
    "stable_diffusion_xl": "/fal-ai/sdxl/image-to-image",
}

# flux_schnell 同步模型（提交即有结果）；flux_dev 等需读误
_ASYNC_PROVIDERS = {"flux_dev", "stable_diffusion_xl"}

# 轮询参数
_POLL_INTERVAL_SECONDS = 3.0
_POLL_MAX_ATTEMPTS = 30  # 最多等 ~90s


# ---------------------------------------------------------------------------
# FAL.ai 适配器
# ---------------------------------------------------------------------------

class FalAIAdapter:
    """FAL.ai 图片生成适配器，实现 ImageProviderAdapter 协议。

    用法：
        adapter = FalAIAdapter("flux_schnell")
        result = await adapter.generate("cinematic sunset, film grain")
    """

    def __init__(self, provider_name: str = "flux_schnell") -> None:
        self._provider_name = provider_name
        cfg = get_config()
        self._api_key = cfg.external_apis.fal_ai.api_key
        self._base_url = cfg.external_apis.fal_ai.base_url.rstrip("/")
        self._timeout = cfg.external_apis.fal_ai.timeout

        # 从 ProviderRegistry 读取默认参数
        registry = get_provider_registry()
        try:
            self._profile = registry.get("image", provider_name)
            self._default_params: dict[str, Any] = dict(self._profile.default_params)
            # endpoint 优先从 registry 读取，兜底用映射
            _registry_ep = self._profile.endpoint or ""
        except KeyError:
            self._profile = None
            self._default_params = {}
            _registry_ep = ""

        ep_path = _PROVIDER_ENDPOINT_MAP.get(provider_name, f"/fal-ai/{provider_name}")
        # registry 里的 endpoint 是完整 URL，提取 path 部分
        if _registry_ep.startswith("http"):
            # 取 https://fal.run/fal-ai/... 中的 path
            from urllib.parse import urlparse
            self._endpoint_path = urlparse(_registry_ep).path
        else:
            self._endpoint_path = ep_path

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> ImageResult:
        """调用 FAL.ai API 生成图片。

        Args:
            prompt:          正向提示词。
            negative_prompt: 负向提示词（flux_schnell 不支持，自动忽略）。
            params:          provider 特定参数（aspect_ratio / num_inference_steps 等）。

        Returns:
            ImageResult，含可下载图片 URL。

        Raises:
            ImageGenerationError: API key 为空、请求失败或超时。
        """
        if not self._api_key:
            raise ImageGenerationError(
                "FAL.ai API key 未配置，请在 config/base/external_apis.yaml 中填写 fal_ai.api_key",
                code="api_key_missing",
            )

        # 合并参数（provider 默认参数 + 调用方传入参数）
        merged_params = dict(self._default_params)
        if params:
            merged_params.update(params)

        # 构建请求体
        payload: dict[str, Any] = {"prompt": prompt}

        # 处理 aspect_ratio
        aspect_ratio = merged_params.pop("aspect_ratio", "16:9")
        payload["image_size"] = self._resolve_image_size(aspect_ratio)

        # flux_schnell 不支持 negative_prompt
        if negative_prompt and self._profile:
            supports_neg = self._profile.capabilities.get(
                "supports_negative_prompt", False
            )
            if supports_neg:
                payload["negative_prompt"] = negative_prompt

        # 其余参数透传
        for k, v in merged_params.items():
            if v is not None and k not in ("duration_sec",):
                payload[k] = v

        _logger.info(
            f"FAL.ai 图片生成请求: provider={self._provider_name!r} "
            f"aspect={aspect_ratio!r} prompt_len={len(prompt)}",
            event_type="fal_generate_start",
        )

        if self._provider_name in _ASYNC_PROVIDERS:
            return await self._generate_async(payload)
        return await self._generate_sync(payload)

    # ------------------------------------------------------------------
    # 同步模式（flux_schnell）
    # ------------------------------------------------------------------

    async def _generate_sync(self, payload: dict[str, Any]) -> ImageResult:
        """flux_schnell 同步提交，直接返回结果。"""
        url = f"{self._base_url}{self._endpoint_path}"
        headers = {
            "Authorization": f"Key {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise ImageGenerationError(
                    f"FAL.ai 请求超时（{self._timeout}s）",
                    code="timeout",
                ) from exc
            except httpx.RequestError as exc:
                raise ImageGenerationError(
                    f"FAL.ai 网络请求失败: {exc}",
                    code="network_error",
                ) from exc

            if resp.status_code != 200:
                raise ImageGenerationError(
                    f"FAL.ai API 返回错误 {resp.status_code}: {resp.text[:300]}",
                    code="api_error",
                )

            data = resp.json()

        _logger.info(
            f"FAL.ai 同步请求完成: provider={self._provider_name!r}",
            event_type="fal_generate_done",
        )
        return self._parse_result(data)

    # ------------------------------------------------------------------
    # 异步模式（flux_dev 等，需轮询）
    # ------------------------------------------------------------------

    async def _generate_async(self, payload: dict[str, Any]) -> ImageResult:
        """flux_dev 异步提交 + 轮询。"""
        submit_url = f"{self._base_url}{self._endpoint_path}"
        headers = {
            "Authorization": f"Key {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            # 提交任务
            try:
                resp = await client.post(submit_url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise ImageGenerationError(
                    f"FAL.ai 提交请求超时（{self._timeout}s）", code="timeout"
                ) from exc

            if resp.status_code not in (200, 202):
                raise ImageGenerationError(
                    f"FAL.ai 提交失败 {resp.status_code}: {resp.text[:300]}",
                    code="api_error",
                )

            data = resp.json()
            # 同步立即返回（部分模型不需要轮询）
            if "images" in data or "image" in data:
                _logger.info(
                    f"FAL.ai 异步请求立即返回: provider={self._provider_name!r}",
                    event_type="fal_generate_done",
                )
                return self._parse_result(data)

            request_id = data.get("request_id") or data.get("id")
            if not request_id:
                raise ImageGenerationError(
                    "FAL.ai 未返回 request_id，无法轮询结果",
                    code="missing_request_id",
                )
            return await self._poll_for_result(request_id, client, headers)

    # ------------------------------------------------------------------
    # 内部工具：异步轮询（两种模式共用）
    # ------------------------------------------------------------------

    async def _poll_for_result(
        self,
        request_id: str,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        *,
        prefix: str = "FAL.ai",
    ) -> ImageResult:
        """轮询 FAL.ai 异步任务直到完成。

        由 _generate_async 和 generate_img2img 共同调用，避免重复实现轮询逻辑。
        """
        status_url = f"{self._base_url}/requests/{request_id}/status"
        result_url = f"{self._base_url}/requests/{request_id}"
        for _ in range(_POLL_MAX_ATTEMPTS):
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            sr = await client.get(status_url, headers=headers)
            if sr.status_code != 200:
                continue
            sr_data = sr.json()
            state = sr_data.get("status", "")
            if state == "COMPLETED":
                _logger.info(
                    f"{prefix} 任务完成: request_id={request_id!r}",
                    event_type="fal_poll_completed",
                )
                rr = await client.get(result_url, headers=headers)
                return self._parse_result(rr.json())
            if state in ("FAILED", "CANCELLED"):
                raise ImageGenerationError(
                    f"{prefix} 任务失败: {sr_data.get('error', state)}",
                    code="task_failed",
                )
            _logger.debug(
                f"{prefix} 轮询中: request_id={request_id!r} status={state!r}",
                event_type="fal_poll_waiting",
            )
        raise ImageGenerationError(
            f"{prefix} 任务在 {_POLL_MAX_ATTEMPTS * _POLL_INTERVAL_SECONDS}s 内未完成",
            code="timeout",
        )

    # ------------------------------------------------------------------
    # image-to-image 公共接口（doc11 批次2）
    # ------------------------------------------------------------------

    async def generate_img2img(
        self,
        prompt: str,
        image_url: str,
        strength: float = 0.75,
        negative_prompt: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> ImageResult:
        """FAL.ai image-to-image 生成。

        使用 flux/dev/image-to-image 端点，以 image_url 作为起始帧。

        Args:
            prompt:          正向提示词。
            image_url:       参考图 URL。
            strength:        参考图影响强度（0.0-1.0）。
            negative_prompt: 负向提示词（可选）。
            params:          额外参数覆写。
        """
        if not self._api_key:
            raise ImageGenerationError(
                "FAL.ai API key 未配置，请在 config/base/external_apis.yaml 中填写 fal_ai.api_key",
                code="api_key_missing",
            )

        # 找到 img2img 端点路径
        ep_path = _IMG2IMG_ENDPOINT_MAP.get(
            self._provider_name,
            f"/fal-ai/{self._provider_name}/image-to-image",
        )

        # 合并参数
        merged_params: dict[str, Any] = dict(self._default_params)
        if params:
            merged_params.update(params)

        # aspect_ratio 只在 txt2img 时需要，img2img 端点用 strength + image_url
        merged_params.pop("aspect_ratio", None)

        payload: dict[str, Any] = {
            "prompt": prompt,
            "image_url": image_url,
            "strength": max(0.0, min(1.0, strength)),
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        # 透传其他参数
        for k, v in merged_params.items():
            if v is not None and k not in ("duration_sec",):
                payload[k] = v

        _logger.info(
            f"FAL.ai img2img 请求: provider={self._provider_name!r} "
            f"strength={strength} prompt_len={len(prompt)}",
            event_type="fal_img2img_start",
        )

        url = f"{self._base_url}{ep_path}"
        headers = {
            "Authorization": f"Key {self._api_key}",
            "Content-Type": "application/json",
        }

        # img2img 直接使用异步模式（需要转换时间较长）
        if self._provider_name in _ASYNC_PROVIDERS:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                try:
                    resp = await client.post(url, json=payload, headers=headers)
                except httpx.TimeoutException as exc:
                    raise ImageGenerationError(
                        f"FAL.ai img2img 请求超时（{self._timeout}s）", code="timeout"
                    ) from exc

                if resp.status_code not in (200, 202):
                    raise ImageGenerationError(
                        f"FAL.ai img2img 提交失败 {resp.status_code}: {resp.text[:300]}",
                        code="api_error",
                    )
                data = resp.json()
                if "images" in data or "image" in data:
                    return self._parse_result(data)

                request_id = data.get("request_id") or data.get("id")
                if not request_id:
                    raise ImageGenerationError(
                        "FAL.ai img2img 未返回 request_id", code="missing_request_id"
                    )
                return await self._poll_for_result(
                    request_id, client, headers, prefix="FAL.ai img2img"
                )
        else:
            # flux_schnell 等同步端点
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                try:
                    resp = await client.post(url, json=payload, headers=headers)
                except httpx.TimeoutException as exc:
                    raise ImageGenerationError(
                        f"FAL.ai img2img 请求超时（{self._timeout}s）", code="timeout"
                    ) from exc
                if resp.status_code != 200:
                    raise ImageGenerationError(
                        f"FAL.ai img2img API 错误 {resp.status_code}: {resp.text[:300]}",
                        code="api_error",
                    )
                _logger.info(
                    f"FAL.ai img2img 完成: provider={self._provider_name!r}",
                    event_type="fal_img2img_done",
                )
                return self._parse_result(resp.json())

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_result(data: dict[str, Any]) -> ImageResult:
        """从 FAL.ai 响应中提取 ImageResult。"""
        # FLUX 模型响应格式：{"images": [{"url": "...", "width": ..., "height": ...}]}
        images = data.get("images", [])
        if images and isinstance(images, list):
            img = images[0]
            return ImageResult(
                image_url=img.get("url", ""),
                width=img.get("width"),
                height=img.get("height"),
                seed=data.get("seed"),
                provider_meta=data,
            )
        # 兜底：直接取 image 字段
        img_url = data.get("image", {}).get("url", "") if isinstance(data.get("image"), dict) else ""
        if not img_url:
            img_url = data.get("url", "")
        if not img_url:
            raise ImageGenerationError(
                f"无法从 FAL.ai 响应中提取图片 URL: {str(data)[:200]}",
                code="parse_error",
            )
        return ImageResult(image_url=img_url, provider_meta=data)

    @staticmethod
    def _resolve_image_size(aspect_ratio: str) -> dict[str, int] | str:
        """将 aspect_ratio 字符串转为 FAL.ai 接受的 image_size 格式。

        FAL.ai 支持：
          - "square" | "landscape_4_3" | "landscape_16_9" | "portrait_4_3" | "portrait_16_9"
          - 或 {"width": int, "height": int}
        """
        _RATIO_MAP: dict[str, str] = {
            "1:1":  "square",
            "16:9": "landscape_16_9",
            "9:16": "portrait_16_9",
            "4:3":  "landscape_4_3",
            "3:4":  "portrait_4_3",
        }
        return _RATIO_MAP.get(aspect_ratio, "landscape_16_9")
