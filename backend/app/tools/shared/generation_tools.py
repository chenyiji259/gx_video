"""共享工具层 — 生成模型统一包装。

来源文档：docs/12 偏差 6 §6.2.3

目标：
  对现有 `ImageGenerationTool` / `VideoGenerationTool` 做薄包装，
  提供所有 Sub-agent 后续可直接调用的统一接口。

Batch A 只做包装层，不改变底层工具实现。
"""
from __future__ import annotations

from typing import Optional

from app.schemas.prompt import PromptBundle
from app.tools.image_generation_tool import ImageGenerationTool
from app.tools.video_generation_tool import VideoGenerationTool


async def generate_image(
    bundle: PromptBundle,
    project_id: str,
    *,
    shot_index: Optional[int] = None,
) -> dict:
    """统一图片生成接口：PromptBundle → 图片 Asset。

    Returns:
        {
          "asset_id": "...",
          "provider": "...",
          "target_type": "storyboard_frame",
        }
    """
    tool = ImageGenerationTool()
    asset_id = await tool.generate_for_bundle(
        bundle=bundle,
        project_id=project_id,
        shot_index=shot_index,
    )
    return {
        "asset_id": asset_id,
        "provider": bundle.provider,
        "target_type": "storyboard_frame",
    }


# 根据 asset_type 自动设置尺寸（若 params 未显式指定）
_SIZE_MAP = {
    "character_reference": "1080*1440",  # 3:4 竖版角色
    "scene_reference": "1920*1080",       # 16:9 横版场景
}


async def generate_reference_image(
    *,
    project_id: str,
    asset_type: str,
    positive_prompt: str,
    negative_prompt: Optional[str] = None,
    generation_mode: str = "text_to_image",
    source_image_url: Optional[str] = None,
    strength: float = 0.75,
    provider_name: Optional[str] = None,
    params: Optional[dict] = None,
    subject_id: Optional[str] = None,
    subject_name: Optional[str] = None,
    version_no: int = 1,
) -> dict:
    """统一参考图生成接口：角色/场景/道具参考图。"""
    # 自动注入 size 参数（若 params 未显式指定）
    merged_params = dict(params) if params else {}
    if "size" not in merged_params and asset_type in _SIZE_MAP:
        merged_params["size"] = _SIZE_MAP[asset_type]

    tool = ImageGenerationTool()
    asset_id = await tool.generate_reference_image(
        project_id=project_id,
        asset_type=asset_type,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        generation_mode=generation_mode,
        source_image_url=source_image_url,
        strength=strength,
        provider_name=provider_name,
        params=merged_params,
        subject_id=subject_id,
        subject_name=subject_name,
        version_no=version_no,
    )
    return {
        "asset_id": asset_id,
        "provider": provider_name,
        "target_type": asset_type,
        "subject_id": subject_id,
        "subject_name": subject_name,
    }


# ---------------------------------------------------------------------------
# Batch B: generate_reference_image_tool — @tool 包装，供 VisualDevelopmentAgent 调用
# ---------------------------------------------------------------------------
try:
    import json as _json
    from app.core.logging import get_logger as _get_logger
    _gen_logger = _get_logger("tools.shared.generation_tools", layer="tool")
    from langchain_core.tools import tool as _lc_tool2

    @_lc_tool2
    async def generate_reference_image_tool(
        project_id: str,
        asset_type: str,
        positive_prompt: str,
        generation_mode: str = "text_to_image",
        source_image_url: str = "",
        negative_prompt: str = "",
        subject_id: str = "",
        subject_name: str = "",
        provider_name: str = "",
        version_no: int = 1,
        strength: float = 0.75,
    ) -> str:
        """Generate a character_reference, scene_reference, or prop_reference image.

        Args:
            project_id: project ID.
            asset_type: character_reference / scene_reference / prop_reference.
            positive_prompt: positive prompt in English.
            generation_mode: text_to_image or image_to_image.
            source_image_url: required when generation_mode is image_to_image.
            negative_prompt: negative prompt in English.
            subject_id: character or scene ID (for metadata).
            subject_name: human-readable name (for metadata).
            provider_name: image provider (empty = auto-select).
            version_no: version number for this reference.
            strength: reference image influence strength for image_to_image (0.5-0.95).
                      Higher values preserve more of the source face/style.
                      Recommended: 0.85-0.92 for real face preservation, 0.65-0.75 for style transfer.

        Returns JSON string: {asset_id, provider, target_type, subject_id, subject_name}.
        On failure returns {"error": "...", "asset_id": ""}.
        """
        try:
            result = await generate_reference_image(
                project_id=project_id,
                asset_type=asset_type,
                positive_prompt=positive_prompt,
                negative_prompt=negative_prompt or None,
                generation_mode=generation_mode,
                source_image_url=source_image_url or None,
                strength=max(0.5, min(0.95, float(strength))),  # 安全限制范围
                provider_name=provider_name or None,
                subject_id=subject_id or None,
                subject_name=subject_name or None,
                version_no=version_no,
            )
            return _json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            _gen_logger.warning(
                f"generate_reference_image_tool 失败: {exc!r}",
                event_type="gen_ref_tool_failed",
            )
            return _json.dumps({"error": str(exc), "asset_id": ""})

except ImportError:
    generate_reference_image_tool = None  # type: ignore[assignment]


async def generate_video(
    bundle: PromptBundle,
    project_id: str,
    *,
    shot_index: Optional[int] = None,
    mode: str = "image_to_video",
    reference_image_url: Optional[str] = None,
) -> dict:
    """统一视频生成接口：PromptBundle → clip Asset。"""
    tool = VideoGenerationTool()
    asset_id, duration_ms = await tool.generate_for_bundle(
        bundle=bundle,
        project_id=project_id,
        shot_index=shot_index,
        mode=mode,
        reference_image_url=reference_image_url,
    )
    return {
        "asset_id": asset_id,
        "provider": bundle.provider,
        "target_type": "clip_video",
        "duration_ms": duration_ms,
    }
