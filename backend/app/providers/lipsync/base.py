"""LipSync Provider 抽象接口层。

来源文档：doc 09 任务 13-03

设计原则（与 image/base.py、video/base.py 完全一致）：
  - LipSyncProviderAdapter 是 Protocol（结构子类型），新 provider 只需实现 generate()
  - LipSyncResult 是 dataclass，统一各 provider 返回结果格式
  - get_lipsync_provider() 工厂函数根据 provider 名称返回对应适配器实例

使用场景（doc 01 §27）：
  只对 shots.lipsync_required=True 的镜头调用，不是全片默认能力。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from app.core.provider_registry import get_provider_registry


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class LipSyncResult:
    """LipSync 生成结果，统一各 provider 返回格式。"""
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
class LipSyncProviderAdapter(Protocol):
    """LipSync Provider 适配器协议。

    所有具体适配器（HedraAdapter 等）必须实现此接口。
    """

    async def generate(
        self,
        face_image_url: str,
        audio_url: str,
        duration_sec: float,
        *,
        params: Optional[dict[str, Any]] = None,
    ) -> LipSyncResult:
        """调用 LipSync 生成 API。

        Args:
            face_image_url:  正脸参考图 URL（直接可访问的图片链接）。
            audio_url:       音频片段 URL（已裁切到目标时长）。
            duration_sec:    目标视频时长（秒）。
            params:          provider 特定参数（aspect_ratio / resolution 等）。

        Returns:
            LipSyncResult，含可下载的视频 URL。

        Raises:
            LipSyncError: 生成失败（key 无效、超时、API 错误等）。
        """
        ...


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class LipSyncError(Exception):
    """LipSync 生成异常（适配器层抛出，上层捕获处理）。"""

    def __init__(self, message: str, code: str = "lipsync_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def get_lipsync_provider(provider_name: Optional[str] = None) -> LipSyncProviderAdapter:
    """根据 provider 名称返回对应的 LipSync 适配器实例。

    Args:
        provider_name: provider 名称（如 "hedra_character"）。
                       为 None 时自动使用 ProviderRegistry 的默认 lipsync provider。

    Returns:
        LipSyncProviderAdapter 实例。

    Raises:
        LipSyncError: provider 不支持或未找到时。
    """
    if provider_name is None:
        registry = get_provider_registry()
        profile = registry.get_default("lipsync")
        if profile is None:
            raise LipSyncError(
                "未找到已启用的 lipsync provider，请检查 config/providers/lipsync_providers.yaml",
                code="no_provider",
            )
        provider_name = profile.name

    _HEDRA_PROVIDERS = {"hedra_character"}
    if provider_name in _HEDRA_PROVIDERS:
        from app.providers.lipsync.hedra_adapter import HedraAdapter
        return HedraAdapter(provider_name=provider_name)

    raise LipSyncError(
        f"不支持的 lipsync provider: {provider_name!r}",
        code="unsupported_provider",
    )
