"""DashScope 图片生成适配器。

支持两个模型，共用同一 endpoint：
  POST https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation

  - qwen-image-2.0-pro  图生图（image-to-image）
    场景：用户已上传角色参考图 → 换装 / 细节丰富
    比例：自动跟随输入图比例，默认兜底 3:4

  - z-image             文生图（text-to-image）
    场景：用户未上传参考图 → 生成角色/场地
    角色比例：9:16（576×1024）
    场地比例：21:9（1024×439）

API 认证：
  DASHSCOPE_API_KEY 环境变量（与文本/Omni 模型共用同一 Key）

请求体格式（messages 数组）：
  文生图：
    input.messages[0].content = [{"text": "..."}]
  图生图：
    input.messages[0].content = [{"image": "url"}, {"text": "..."}]
API 调用模式：
  同步调用（不传 X-DashScope-Async），直接返回图片 URL，无需轮询。
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.core.logging import get_logger
from app.core.provider_registry import get_provider_registry
from app.providers.image.base import ImageGenerationError, ImageResult

_logger = get_logger("dashscope_adapter", layer="tool")

# DashScope 账户级并发限制：最多同时 2 个请求
_DASHSCOPE_SEMAPHORE = asyncio.Semaphore(2)

# DashScope 任务状态
_STATUS_SUCCEEDED = "SUCCEEDED"
_STATUS_FAILED    = "FAILED"

# 轮询参数
_POLL_INTERVAL = 3.0   # 秒
_POLL_MAX      = 40    # 最多等 40 × 3 = 120 秒

# 自动检测比例 → DashScope size 字符串的映射表（使用官方推荐分辨率）
_RATIO_TO_SIZE: dict[str, str] = {
    "1:1":   "1024*1024",
    "4:3":   "1440*1080",
    "3:4":   "1080*1440",  # 角色换装默认
    "16:9":  "1920*1080",
    "9:16":  "1080*1920",
    "21:9":  "2048*872",
    "2:3":   "1024*1536",
    "3:2":   "1536*1024",
}


def _detect_size_from_url(image_url: str, default_size: str) -> str:
    """
    通过 HTTP HEAD 请求尝试检测图片尺寸，推算最接近的 DashScope size 字符串。
    失败时返回 default_size。

    注意：此函数是同步的，应在 asyncio.to_thread 中调用，
    或直接用 httpx 异步版本（见下方 _detect_size_from_url_async）。
    """
    return default_size   # 占位，实际通过异步版本实现


async def _detect_size_from_url_async(
    image_url: str,
    default_size: str,
    timeout: float = 5.0,
) -> str:
    """异步检测图片宽高，映射为最接近的 DashScope size。"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # 先用 HEAD 拿 Content-Type，再用 GET 读前 1KB 做 JPEG/PNG 头解析
            resp = await client.get(image_url, headers={"Range": "bytes=0-1023"})
            if resp.status_code not in (200, 206):
                return default_size

            data = resp.content
            width, height = _parse_image_dimensions(data)
            if not width or not height:
                return default_size

            ratio = _find_closest_ratio(width, height)
            size = _RATIO_TO_SIZE.get(ratio, default_size)
            _logger.debug(
                f"检测到输入图比例: {width}×{height} → ratio={ratio} → size={size}",
                event_type="dashscope_ratio_detected",
            )
            return size
    except Exception as exc:  # noqa: BLE001
        _logger.debug(f"图片比例检测失败（使用默认）: {exc!r}")
        return default_size


def _parse_image_dimensions(data: bytes) -> tuple[int, int]:
    """从图片头部字节解析宽高（支持 JPEG / PNG）。"""
    try:
        # PNG: 8 字节魔术 + IHDR chunk，width/height 在 16-24 字节
        if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
            import struct
            w, h = struct.unpack(">II", data[16:24])
            return w, h

        # JPEG: 扫描 SOF 标记（0xFF 0xC0/0xC2）
        if data[:2] == b"\xff\xd8":
            i = 2
            while i < len(data) - 8:
                if data[i] != 0xFF:
                    break
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    import struct
                    h, w = struct.unpack(">HH", data[i + 5: i + 9])
                    return w, h
                length = int.from_bytes(data[i + 2: i + 4], "big")
                i += 2 + length
    except Exception:  # noqa: BLE001
        pass
    return 0, 0


def _find_closest_ratio(width: int, height: int) -> str:
    """将图片实际宽高映射为最接近的标准比例字符串。"""
    if width == 0 or height == 0:
        return "3:4"
    actual = width / height
    candidates = {
        "1:1":  1.0,
        "4:3":  4 / 3,
        "3:4":  3 / 4,
        "16:9": 16 / 9,
        "9:16": 9 / 16,
        "21:9": 21 / 9,
    }
    return min(candidates, key=lambda k: abs(candidates[k] - actual))


# ---------------------------------------------------------------------------
# DashScope 适配器
# ---------------------------------------------------------------------------

class DashscopeImageAdapter:
    """DashScope 图片生成适配器，实现 ImageProviderAdapter 协议。

    同时支持：
      - generate()         文生图（z-image）
      - generate_img2img() 图生图（qwen-image-2.0-pro）
    """

    def __init__(self, provider_name: str) -> None:
        self._provider_name = provider_name

        # 从 ProviderRegistry 读取配置
        registry = get_provider_registry()
        try:
            profile = registry.get("image", provider_name)
            self._profile     = profile
            self._endpoint    = profile.endpoint or ""
            self._task_url    = getattr(profile, "task_query_url", None) or \
                                "https://dashscope.aliyuncs.com/api/v1/tasks"
            self._model_name  = profile.model_name or provider_name
            self._default_params: dict[str, Any] = dict(profile.default_params or {})
            self._timeout     = 120.0
        except KeyError as exc:
            raise ImageGenerationError(
                f"未在 image_providers.yaml 找到 provider: {provider_name!r}",
                code="no_provider",
            ) from exc

        # API Key
        self._api_key = os.environ.get("DASHSCOPE_API_KEY", "")

    # ------------------------------------------------------------------
    # 公共接口：文生图
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> ImageResult:
        """文生图（z-image）。

        比例通过 params["size"] 覆盖，默认使用 image_providers.yaml 中的 default_params.size。
        - 角色：传 params={"size": "576*1024"}  → 9:16
        - 场地：传 params={"size": "1024*439"}  → 21:9
        """
        self._check_api_key()

        merged = dict(self._default_params)
        if params:
            merged.update(params)

        size = merged.get("size", "576*1024")
        n    = int(merged.get("n", 1))

        # messages 格式：文生图只需要 text
        payload = {
            "model": self._model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": prompt}],
                    }
                ]
            },
            "parameters": {"size": size, "n": n},
        }

        _logger.info(
            f"DashScope 文生图请求: model={self._model_name!r} size={size!r} "
            f"prompt_len={len(prompt)}",
            event_type="dashscope_txt2img_start",
        )

        return await self._submit_and_poll(payload)

    # ------------------------------------------------------------------
    # 公共接口：图生图
    # ------------------------------------------------------------------

    async def generate_img2img(
        self,
        prompt: str,
        image_url: str,
        strength: float = 0.75,
        negative_prompt: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> ImageResult:
        """图生图（qwen-image-2.0-pro）。

        比例策略：
          1. 优先使用 params["size"] 指定
          2. 其次自动检测输入图比例（auto_detect_ratio=true）
          3. 兜底使用 default_params.size（768*1024，3:4）
        """
        self._check_api_key()

        merged = dict(self._default_params)
        if params:
            merged.update(params)

        default_size = merged.get("size", "768*1024")

        # 自动检测输入图比例
        auto_detect = (
            self._profile and
            self._profile.capabilities.get("auto_detect_ratio", False)
        )
        if "size" not in (params or {}) and auto_detect and image_url:
            size = await _detect_size_from_url_async(image_url, default_size)
        else:
            size = default_size

        n = int(merged.get("n", 1))

        # messages 格式：图生图先放 image URL，再放编辑指令文本
        payload = {
            "model": self._model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"image": image_url},
                            {"text": prompt},
                        ],
                    }
                ]
            },
            "parameters": {
                "size": size,
                "n": n,
            },
        }

        _logger.info(
            f"DashScope 图生图请求: model={self._model_name!r} size={size!r} "
            f"strength={strength} prompt_len={len(prompt)}",
            event_type="dashscope_img2img_start",
        )

        return await self._submit_and_poll(payload)

    # ------------------------------------------------------------------
    # 公共接口：多参考图生图（qwen-image-2.0-pro 1-3 张）
    # ------------------------------------------------------------------

    async def generate_multi_ref_img2img(
        self,
        prompt: str,
        image_urls: list[str],
        strength: float = 0.75,
        negative_prompt: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> "ImageResult":
        """多参考图生图（qwen-image-2.0-pro 支持 1-3 张参考图）。

        content 数组格式：
          [{"image": url1}, {"image": url2}, {"image": url3}, {"text": prompt}]

        图片顺序建议：[场景图, 造型图, 角色基础图]。
        """
        if not image_urls:
            raise ImageGenerationError(
                "generate_multi_ref_img2img 至少需要 1 张参考图",
                code="no_reference_images",
            )

        self._check_api_key()

        merged = dict(self._default_params)
        if params:
            merged.update(params)

        default_size = merged.get("size", "1080*1440")

        # 自动检测比例（以第一张图为基准）
        auto_detect = (
            self._profile and
            self._profile.capabilities.get("auto_detect_ratio", False)
        )
        if "size" not in (params or {}) and auto_detect and image_urls[0]:
            size = await _detect_size_from_url_async(image_urls[0], default_size)
        else:
            size = default_size

        n = int(merged.get("n", 1))

        # 构建 content 数组：先放 1-3 张参考图，最后放提示词
        content: list[dict] = [
            {"image": url} for url in image_urls[:3]  # 最多 3 张
        ]
        content.append({"text": prompt})

        payload = {
            "model": self._model_name,
            "input": {
                "messages": [
                    {"role": "user", "content": content}
                ]
            },
            "parameters": {"size": size, "n": n},
        }

        _logger.info(
            f"DashScope 多参考图生图: model={self._model_name!r} "
            f"ref_count={len(image_urls[:3])} size={size!r} prompt_len={len(prompt)}",
            event_type="dashscope_multi_ref_start",
        )

        return await self._submit_and_poll(payload)

    # ------------------------------------------------------------------
    # 内部：提交任务 + 轮询
    # ------------------------------------------------------------------

    async def _submit_and_poll(self, payload: dict[str, Any]) -> ImageResult:
        """同步生图请求，含 Semaphore 并发控制和 429 指数退避重试。"""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        _MAX_RETRIES = 3
        _BACKOFF_BASE = 2.0  # 2s, 4s, 8s

        async with _DASHSCOPE_SEMAPHORE:
            for attempt in range(_MAX_RETRIES + 1):
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    try:
                        resp = await client.post(self._endpoint, json=payload, headers=headers)
                    except httpx.TimeoutException as exc:
                        raise ImageGenerationError(
                            f"DashScope 请求超时（{self._timeout}s）", code="timeout"
                        ) from exc
                    except httpx.RequestError as exc:
                        raise ImageGenerationError(
                            f"DashScope 网络错误: {exc}", code="network_error"
                        ) from exc

                    if resp.status_code == 429:
                        if attempt < _MAX_RETRIES:
                            wait = _BACKOFF_BASE * (2 ** attempt)
                            _logger.warning(
                                f"DashScope 429 限流，{wait:.0f}s 后第 {attempt+1} 次重试",
                                event_type="dashscope_rate_limited",
                            )
                            await asyncio.sleep(wait)
                            continue
                        else:
                            raise ImageGenerationError(
                                f"DashScope 429 限流，{_MAX_RETRIES} 次重试后仍失败: {resp.text[:300]}",
                                code="rate_limit",
                            )

                    if resp.status_code != 200:
                        raise ImageGenerationError(
                            f"DashScope 请求失败 HTTP {resp.status_code}: {resp.text[:300]}",
                            code="api_error",
                        )

                    _logger.info(
                        f"DashScope 请求完成: model={self._model_name!r}",
                        event_type="dashscope_generate_done",
                    )
                    return self._parse_result(resp.json())

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _check_api_key(self) -> None:
        if not self._api_key:
            raise ImageGenerationError(
                "DASHSCOPE_API_KEY 未配置，请在 .env 中设置",
                code="api_key_missing",
            )

    @staticmethod
    def _parse_result(data: dict[str, Any]) -> ImageResult:
        """从 DashScope 响应中提取 ImageResult。

        实际响应结构：
          {
            "output": {
              "choices": [{
                "message": {
                  "content": [
                    {"image": "https://..."},  # 图片 URL
                    {"text": "..."}             # 可选，z-image 会附加描述
                  ]
                }
              }]
            },
            "usage": {"width": 1080, "height": 1920, ...}
          }
        """
        choices = data.get("output", {}).get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", [])
            for item in content:
                if "image" in item and item["image"]:
                    usage = data.get("usage", {})
                    return ImageResult(
                        image_url=item["image"],
                        width=usage.get("width"),
                        height=usage.get("height"),
                        provider_meta=data,
                    )

        raise ImageGenerationError(
            f"无法从 DashScope 响应中提取图片 URL: {str(data)[:300]}",
            code="parse_error",
        )
