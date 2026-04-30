"""视频 Provider 抽象接口层。

来源文档：doc 09 任务 11-01

设计原则（与 image/base.py 一致）：
  - VideoProviderAdapter 是 Protocol（结构子类型），新 provider 只需实现 generate()
  - VideoResult 是 dataclass，统一各 provider 返回结果格式
  - get_video_provider() 工厂函数根据 provider 名称返回对应适配器实例
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Protocol, runtime_checkable

from app.core.provider_registry import get_provider_registry


# ---------------------------------------------------------------------------
# 类型定义
# ---------------------------------------------------------------------------

VideoGenerationMode = Literal["image_to_video", "text_to_video", "video_to_video", "multi_image_fusion"]


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class VideoResult:
    """视频生成结果，统一各 provider 返回格式。"""
    # 生成视频的可下载 URL
    video_url: str
    # 视频时长（秒），部分 provider 不提供
    duration_sec: Optional[float] = None
    # 视频尺寸（部分 provider 不提供）
    width: Optional[int] = None
    height: Optional[int] = None
    # provider 返回的原始元数据（供调试）
    provider_meta: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 适配器 Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class VideoProviderAdapter(Protocol):
    """视频 Provider 适配器协议。

    所有具体适配器（KlingAdapter 等）必须实现此接口。
    """

    async def generate(
        self,
        prompt: str,
        mode: VideoGenerationMode,
        *,
        negative_prompt: Optional[str] = None,
        reference_image_url: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> VideoResult:
        """调用视频生成 API。

        Args:
            prompt:               正向提示词（英文）。
            mode:                 生成模式（image_to_video / text_to_video / video_to_video / multi_image_fusion）。
            negative_prompt:      负向提示词（部分 provider 不支持，忽略即可）。
            reference_image_url:  参考起始帧图片 URL（image_to_video 模式必须提供）。
            params:               provider 特定参数（duration / cfg_scale 等）。

        Returns:
            VideoResult，含可下载视频 URL。

        Raises:
            VideoGenerationError: 生成失败（key 无效、超时、API 错误等）。
        """
        ...


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class VideoGenerationError(Exception):
    """视频生成异常（适配器层抛出，上层捕获处理）。"""

    def __init__(self, message: str, code: str = "video_generation_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def get_video_provider(provider_name: Optional[str] = None) -> VideoProviderAdapter:
    """根据 provider 名称返回对应的视频生成适配器实例。

    Args:
        provider_name: provider 名称（如 "kling_v2"）。
                       为 None 时自动使用 ProviderRegistry 的默认 video provider。

    Returns:
        VideoProviderAdapter 实例。

    Raises:
        VideoGenerationError: provider 不支持或未找到时。
    """
    if provider_name is None:
        registry = get_provider_registry()
        profile = registry.get_default("video")
        if profile is None:
            raise VideoGenerationError(
                "未找到已启用的 video provider，请检查 config/providers/video_providers.yaml",
                code="no_provider",
            )
        provider_name = profile.name

    _KLING_PROVIDERS = {"kling_v2", "kling_v1"}
    _MINIMAX_PROVIDERS = {"minimax_video"}
    _TOAPIS_PROVIDERS = {"grok_imagine_10_video", "grok_video_3"}
    _SEEDANCE_PROVIDERS = {"seedance_2", "seedance_2_fast"}

    if provider_name in _KLING_PROVIDERS:
        from app.providers.video.kling_adapter import KlingAdapter
        return KlingAdapter(provider_name=provider_name)

    if provider_name in _MINIMAX_PROVIDERS:
        from app.providers.video.minimax_adapter import MinimaxAdapter
        return MinimaxAdapter()

    if provider_name in _TOAPIS_PROVIDERS:
        from app.providers.video.toapis_adapter import ToAPIsAdapter
        return ToAPIsAdapter(provider_name=provider_name)

    # Seedance 2.0（火山方舟 Ark，支持 first_frame + last_frame role 标记）
    if provider_name in _SEEDANCE_PROVIDERS:
        from app.providers.video.seedance_adapter import SeedanceAdapter
        return SeedanceAdapter(provider_name=provider_name)

    raise VideoGenerationError(
        f"不支持的 video provider: {provider_name!r}",
        code="unsupported_provider",
    )
