"""镜头语义规格 Schema。

来源文档：doc 06 §9 Shot Semantic Spec
  它是创意层（Agent 规划）与执行层（Prompt 编译、视频生成）之间的桥梁。
  必须稳定、可版本化、可重放、与 provider 无关。

用途：
  - 创意规划 Agent 产出 → 写入 shot_plan_versions.raw_payload
  - Prompt 编译服务读取 → 生成 PromptBundle
  - 局部返工时更新此对象 → 触发 Prompt 重编译 → 触发 clip 重生成
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# 镜头角色类型（doc 06 §9 shot_role）
ShotRole = Literal["performance", "narrative", "atmosphere", "transition"]

# 节奏类型
PaceType = Literal["slow", "medium", "fast", "very_fast"]


class ShotSemanticSpec(BaseModel):
    """单个镜头的结构化语义规格。

    这是系统内部最核心的中间对象之一。
    真正应该被长期保存和复用的不是最终 prompt 字符串，而是这个对象。

    字段对应 doc 06 §9.2 的 JSON 示例。
    """
    shot_id: str

    # 镜头角色：performance=演唱、narrative=叙事、atmosphere=氛围、transition=过渡
    shot_role: ShotRole = "narrative"

    # 视觉主体
    subject: str | None = None

    # 场景位置描述
    location: str | None = None

    # 情绪标签（自由文本）
    emotion: str | None = None

    # 镜头运动描述（"fast push-in", "slow dolly out" 等）
    camera_language: str | None = None

    # 节奏感知
    pace: PaceType = "medium"

    # 色调偏好（"cold blue", "warm golden" 等）
    color_tone: str | None = None

    # 目标时长（秒），由音频节拍分析决定
    duration_sec: float = Field(gt=0.0, le=30.0)

    # 是否需要 lipsync 工具链处理
    lipsync_required: bool = False

    # 是否保留上一轮的角色绑定（局部修改时保留人物）
    preserve_character: bool = False

    # 是否锁定全局风格（使用 style_bible）
    style_lock: bool = True

    # 引用的资产 ID（角色参考图、场景参考图等）
    reference_asset_ids: list[str] = Field(default_factory=list)

    # 对应的歌词片段
    lyric_text: str | None = None

    # 对应的音频段落类型（intro/verse/chorus/bridge/outro）
    section_type: str | None = None

    # 用户最近一次 patch（记录修改意图，方便回溯）
    user_patch: dict | None = None

    model_config = ConfigDict(from_attributes=True)  # 允许从 ORM 对象直接构建
