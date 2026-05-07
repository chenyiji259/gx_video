"""Prompt Bundle Schema。

来源文档：doc 06 §10 Prompt Bundle 设计
  PromptBundle 是 Prompt 编译服务输出给工具层的标准产物。
  Tool 层完全不需要理解业务语义，只接收这个对象。

核心价值（doc 06 §10.3）：
  - 同一个 shot 可以用不同 provider 重试
  - 保存每次编译结果（可追溯）
  - 对比不同 prompt 版本
  - provider 切换时业务层不需要改动
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.utils.ids import generate_ulid

# target_type 枚举，对应 prompt_bundles 表的约束（doc 05 §12.1）
# doc 21 九宫格架构新增 nine_grid_image，用于九宫格大图生图 prompt。
# doc 27/28 口播链路新增 talking_head_story_overview_board，用于 21:9 故事大图 prompt。
PromptTargetType = Literal[
    "storyboard_frame",
    "shot_clip",
    "lipsync_clip",
    "nine_grid_image",
    "talking_head_story_overview_board",
]


class PromptBundle(BaseModel):
    """Prompt 编译服务的标准输出对象。

    字段对应 doc 06 §10.2 的 JSON 示例。
    """
    bundle_id: str = Field(default_factory=generate_ulid)

    # 目标类型：storyboard_frame / shot_clip / lipsync_clip / nine_grid_image / talking_head_story_overview_board
    target_type: PromptTargetType

    # 目标对象 ID（storyboard_frame.id / shot.id / grid_XXX）
    target_id: str

    # 目标 provider 名称（对应 config/providers/ 中的 name 字段）
    provider: str

    # 正向提示词
    positive_prompt: str

    # 负向提示词（可选，某些模型不支持）
    negative_prompt: str | None = None

    # 引用的资产 ID（角色参考图、风格参考图等）
    reference_asset_ids: list[str] = Field(default_factory=list)

    # doc11 批次3：image-to-image 参考图字段
    # reference_image_url: 主参考图 URL（向后兼容，单图 img2img 时使用）
    reference_image_url: str | None = None
    # reference_image_urls: 多参考图 URL 列表（qwen-image-2.0-pro 支持 1-3 张）
    # 顺序：[场景参考图, 造型参考图, 角色基础图]，按需取 1-3 张
    # 有值时 ImageGenerationTool 优先使用此字段（多参考图模式），
    # 否则回落到 reference_image_url（单图模式）。
    reference_image_urls: list[str] = Field(default_factory=list)
    # 口播链路：Seedance reference_audio 声色参考资产 URL / asset:// 列表。
    reference_audio_urls: list[str] = Field(default_factory=list)
    # reference_weight: img2img 参考强度（0.0-1.0），默认 0.75
    reference_weight: float = 0.75

    # provider 特定参数（duration_sec / aspect_ratio / seed / motion_strength 等）
    params: dict[str, Any] = Field(default_factory=dict)

    # 编译时使用的版本引用（用于追溯）
    source_brief_version_id: str | None = None
    source_style_version_id: str | None = None
    source_shot_plan_version_id: str | None = None

    model_config = ConfigDict(from_attributes=True)
