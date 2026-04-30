"""图片 Provider 抽象接口层。

来源文档：doc 09 任务 10-02

设计原则：
  - ImageProviderAdapter 是 Protocol（结构子类型），新 provider 只需实现 generate()，
    无需继承，保持松耦合
  - ImageResult 是 dataclass，统一各 provider 返回结果格式
  - get_image_provider() 工厂函数根据 provider 名称返回对应适配器实例
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from app.core.provider_registry import get_provider_registry


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class ImageResult:
    """图片生成结果，统一各 provider 返回格式。"""
    # 生成图片的 URL（可下载）
    image_url: str
    # 图片尺寸（部分 provider 不提供，为 None）
    width: Optional[int] = None
    height: Optional[int] = None
    # 本次生成使用的随机种子（可选，用于复现）
    seed: Optional[int] = None
    # provider 返回的原始元数据（供调试）
    provider_meta: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 适配器 Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class ImageProviderAdapter(Protocol):
    """图片 Provider 适配器协议。

    所有具体适配器（FalAIAdapter 等）必须实现此接口。
    generate()         — text-to-image
    generate_img2img() — image-to-image（可选，不支持时抛 ImageGenerationError）
    """

    async def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> ImageResult:
        """调用图片生成 API（text-to-image）。

        Args:
            prompt:          正向提示词。
            negative_prompt: 负向提示词（部分 provider 不支持，忽略即可）。
            params:          provider 特定参数（aspect_ratio / num_inference_steps 等）。

        Returns:
            ImageResult，含可下载的图片 URL。

        Raises:
            ImageGenerationError: 生成失败（key 无效、超时、API 错误等）。
        """
        ...

    async def generate_img2img(
        self,
        prompt: str,
        image_url: str,
        strength: float = 0.75,
        negative_prompt: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> ImageResult:
        """调用图片生成 API（image-to-image，单张参考图）。

        Args:
            prompt:          正向提示词。
            image_url:       参考图 URL（作为起始帧）。
            strength:        参考图影响强度（0.0-1.0，越高越像原图）。
            negative_prompt: 负向提示词。
            params:          provider 特定参数。

        Returns:
            ImageResult，含可下载的图片 URL。

        Raises:
            ImageGenerationError: 不支持 image-to-image 或生成失败。
        """
        ...

    async def generate_multi_ref_img2img(
        self,
        prompt: str,
        image_urls: list[str],
        strength: float = 0.75,
        negative_prompt: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> ImageResult:
        """多参考图 image-to-image（qwen-image-2.0-pro 支持 1-3 张参考图）。

        图片顺序影响权重，建议：[场景图, 造型图, 角色基础图]。
        Provider 不支持时应抛 ImageGenerationError。

        Args:
            prompt:     正向提示词（图像编辑/合成指令）。
            image_urls: 1-3 张参考图 URL，有序传入。
            strength:   参考强度。
            negative_prompt: 负向提示词。
            params:     provider 特定参数。
        """
        ...


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class ImageGenerationError(Exception):
    """图片生成异常（适配器层抛出，上层捕获处理）。"""

    def __init__(self, message: str, code: str = "image_generation_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def get_image_provider(provider_name: Optional[str] = None) -> ImageProviderAdapter:
    """根据 provider 名称返回对应的图片生成适配器实例。

    Args:
        provider_name: provider 名称（如 "flux_schnell"）。
                       为 None 时自动使用 ProviderRegistry 的默认 image provider。

    Returns:
        ImageProviderAdapter 实例。

    Raises:
        ImageGenerationError: provider 不支持或未找到时。
    """
    if provider_name is None:
        registry = get_provider_registry()
        profile = registry.get_default("image")
        if profile is None:
            raise ImageGenerationError(
                "未找到已启用的 image provider，请检查 config/providers/image_providers.yaml",
                code="no_provider",
            )
        provider_name = profile.name

    # FAL.ai 托管的 FLUX 系列
    _FAL_PROVIDERS = {"flux_schnell", "flux_dev", "stable_diffusion_xl"}
    if provider_name in _FAL_PROVIDERS:
        from app.providers.image.fal_adapter import FalAIAdapter
        return FalAIAdapter(provider_name=provider_name)

    # DashScope / Qwen 图片生成
    #   qwen_img2img  → qwen-image-2.0-pro 图生图（角色换装/丰富）
    #   qwen_txt2img  → z-image 文生图（角色/场地生成）
    _DASHSCOPE_PROVIDERS = {"qwen_img2img", "qwen_txt2img"}
    if provider_name in _DASHSCOPE_PROVIDERS:
        from app.providers.image.dashscope_adapter import DashscopeImageAdapter
        return DashscopeImageAdapter(provider_name=provider_name)

    # GPT Image 2（ToApis 中转，doc 21 §1.4 1K 三比例硬约束）
    _GPT_IMAGE_PROVIDERS = {"gpt_image_2"}
    if provider_name in _GPT_IMAGE_PROVIDERS:
        from app.providers.image.gpt_image_adapter import GPTImageAdapter
        return GPTImageAdapter(provider_name=provider_name)

    raise ImageGenerationError(
        f"不支持的 image provider: {provider_name!r}",
        code="unsupported_provider",
    )
