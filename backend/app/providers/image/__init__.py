"""图片 Provider 包。

对外暴露：
  - get_image_provider(provider_name) → ImageProviderAdapter
  - ImageResult
  - ImageGenerationError
"""
from app.providers.image.base import (
    ImageGenerationError,
    ImageProviderAdapter,
    ImageResult,
    get_image_provider,
)

__all__ = [
    "get_image_provider",
    "ImageProviderAdapter",
    "ImageResult",
    "ImageGenerationError",
]
