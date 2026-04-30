"""Prompt 编译服务（Prompt Compiler Service）。

来源文档：doc 06 §10 / doc 09 任务 10-01

职责：
  将结构化镜头语义（ShotSemanticSpec）+ brief/style + provider 能力矩阵，
  通过 LLM + prompt 模板编译为 provider 可执行的 PromptBundle。

  输入：
    - shot_id / project_id（从 DB 读取完整上下文）
    - target_type（storyboard_frame | shot_clip | lipsync_clip）

  输出：
    - PromptBundle schema 对象（schemas/prompt.py）
    - 同步落库到 prompt_bundles 表
    - 写本地快照（07_prompt_bundles/）

规则：
  - LLM 失败时规则兜底（不抛异常），保证 storyboard 流程不被 LLM 故障阻断
  - 配置从 config/base/llm.yaml 读取，绝不硬编码
  - provider profile 从 ProviderRegistry 读取
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.logging import get_project_logger
from app.core.prompt_renderer import PromptRenderer
from app.core.provider_registry import get_provider_registry
from app.models.prompt_bundle import PromptBundleModel
from app.repositories.asset_repository import AssetRepository
from app.repositories.planning_repositories import (
    CreativeBriefRepository,
    ShotRepository,
    StyleBibleRepository,
)
from app.repositories.project_spec_repository import ProjectSpecRepository
from app.repositories.visual_bible_repository import CharacterSetVersionRepository
from app.repositories.prompt_bundle_repository import PromptBundleRepository
from app.schemas.prompt import PromptBundle
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.path_planner import ArtifactStage
from app.utils.ids import generate_ulid


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class PromptCompilerError(Exception):
    """Prompt 编译异常（仅前置条件不满足时抛出；LLM 故障用兜底处理）。"""

    def __init__(self, message: str, code: str = "compiler_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

from app.utils.json_utils import safe_parse_json as _safe_parse_json  # DESIGN-05


def _shot_to_spec_text(shot: Any) -> str:
    """将 Shot ORM 字段序列化为自然语言文本，作为 prompt 变量。"""
    parts = [f"镜头编号: {shot.shot_index}"]
    if shot.section_type:
        parts.append(f"段落类型: {shot.section_type}")
    subject = getattr(shot, "subject", None)
    if subject:
        parts.append(f"主体: {subject}")
    location = getattr(shot, "location", None)
    if location:
        parts.append(f"场景位置: {location}")
    if shot.emotion:
        intensity = getattr(shot, "emotion_intensity", None)
        if intensity:
            parts.append(f"情绪: {shot.emotion}（强度: {intensity}）")
        else:
            parts.append(f"情绪: {shot.emotion}")
    if shot.shot_type:
        parts.append(f"景别: {shot.shot_type}")
    if shot.camera_language:
        parts.append(f"运镜: {shot.camera_language}")
    if shot.visual_energy:
        parts.append(f"视觉能量: {shot.visual_energy}")
    if shot.lyric_text:
        parts.append(f"歌词: {shot.lyric_text}")
    dialogue = getattr(shot, "dialogue", None)
    if dialogue:
        parts.append(f"视频配音: {dialogue}")
    duration_ms = getattr(shot, "duration_ms", 0) or 0
    duration_sec = round(duration_ms / 1000, 2)
    parts.append(f"目标时长: {duration_sec}s")
    lipsync = getattr(shot, "lipsync_required", False)
    if lipsync:
        parts.append("需要口型同步: 是")
    return "\n".join(parts)


def _style_bible_to_text(brief: Any, style: Any) -> str:
    """将 brief + style 压缩为给 LLM 的风格摘要文本。"""
    parts: list[str] = []
    if brief:
        if brief.style_direction:
            parts.append(f"风格方向: {brief.style_direction}")
        if brief.mood_tags:
            tags = brief.mood_tags if isinstance(brief.mood_tags, list) else []
            if tags:
                parts.append(f"情绪标签: {', '.join(str(t) for t in tags)}")
        if brief.summary:
            parts.append(f"创意概要: {brief.summary}")
        human_on_camera = _extract_human_on_camera(brief)
        if human_on_camera is True:
            parts.append("主体策略: 需要真人入镜，关键画面应以真人主体为核心，并保持人物外观连续一致。")
        elif human_on_camera is False:
            parts.append("主体策略: 不需要真人入镜，避免真人面部、人体和手部特写，优先产品、场景、图形化元素或抽象镜头。")
    if style:
        if style.lighting_style:
            parts.append(f"光线风格: {style.lighting_style}")
        if style.camera_style:
            parts.append(f"镜头风格: {style.camera_style}")
        if style.film_texture:
            parts.append(f"胶片质感: {style.film_texture}")
        palette = style.palette
        if isinstance(palette, dict) and palette:
            desc_val = palette.get("description") or str(palette)
            if desc_val:
                parts.append(f"调色板: {desc_val}")
    return "\n".join(parts) if parts else "无风格信息，请使用通用电影美学风格。"


def _extract_human_on_camera(brief: Any) -> bool | None:
    """从 brief.raw_payload.extension 提取真人入镜开关。"""
    if brief is None:
        return None
    raw_payload = getattr(brief, "raw_payload", None) or {}
    if isinstance(raw_payload.get("creative_brief"), dict):
        raw_payload = raw_payload.get("creative_brief") or {}
    ext = raw_payload.get("extension") or {}
    if "human_on_camera" not in ext:
        return None
    value = ext.get("human_on_camera")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in keywords)


def _classify_expression_type_for_audio(
    user_prompt: str,
    brief_payload: dict | None = None,
    dialogue: str | None = None,
) -> str:
    brief_payload = brief_payload or {}
    merged_text = " ".join(
        str(part or "")
        for part in [
            user_prompt,
            brief_payload.get("title"),
            brief_payload.get("summary"),
            brief_payload.get("style_direction"),
            dialogue,
        ]
    )
    if _contains_any(merged_text, ("讲解", "解说", "科普", "教程", "口播", "旁白", "explainer", "tutorial", "voiceover")):
        return "explainer"
    if _contains_any(merged_text, ("广告", "带货", "推广", "品牌", "宣传", "cta", "ad", "brand", "promo", "commercial")):
        return "ad"
    if _contains_any(merged_text, ("剧情", "对白", "角色", "故事", "scene", "drama", "character")):
        return "drama"
    if _contains_any(merged_text, ("氛围", "纯视觉", "情绪", "mv", "visual", "mood", "atmosphere")):
        return "visual"
    return "general"


def _derive_audio_direction_text(
    *,
    brief: Any,
    shot: Any,
    spec: Any | None,
) -> str:
    """派生视频生成阶段的声音/旁白/BGM策略说明。"""
    brief_payload = getattr(brief, "raw_payload", None) or {}
    if isinstance(brief_payload.get("creative_brief"), dict):
        brief_payload = brief_payload.get("creative_brief") or {}
    ext = brief_payload.get("extension") or {}
    output_config = getattr(spec, "output_config", None) or {}
    user_prompt = getattr(spec, "user_prompt", "") or ""
    dialogue = getattr(shot, "dialogue", None) or ""
    shot_audio_strategy = None
    style_binding = getattr(shot, "style_binding", None) or []
    if isinstance(style_binding, list):
        for item in style_binding:
            if isinstance(item, dict) and item.get("type") == "audio_strategy" and isinstance(item.get("value"), dict):
                shot_audio_strategy = item.get("value")
                break
            if isinstance(item, dict) and isinstance(item.get("audio_strategy"), dict):
                shot_audio_strategy = item.get("audio_strategy")
                break

    expression_type = (
        str(shot_audio_strategy.get("expression_type"))
        if isinstance(shot_audio_strategy, dict) and shot_audio_strategy.get("expression_type")
        else _classify_expression_type_for_audio(user_prompt, brief_payload, dialogue)
    )
    emotion = getattr(shot, "emotion", None) or "neutral"
    intensity = getattr(shot, "emotion_intensity", None) or "medium"
    platform = output_config.get("platform") or ext.get("target_platform") or ""
    audience = output_config.get("target_audience") or ext.get("target_audience") or ""

    if expression_type == "explainer":
        voice = "专业、亲切、可信赖的中文讲解女声，语速中等偏稳，咬字清楚"
        tone = "像经验丰富的护肤顾问在面对镜头解释重点，避免夸张推销感"
        bgm = "背景音应轻、干净、低存在感，可有细微科技感或生活方式感 pad，不要压过人声"
    elif expression_type == "ad":
        voice = "更有记忆点和节奏感的中文广告旁白，可更干脆、更聚焦卖点"
        tone = "句子更短、更有强调感，重点信息和 CTA 要更明确"
        bgm = "背景音可更鲜明、更有节奏，但仍需给品牌信息和口播让位"
    elif expression_type == "drama":
        voice = "若该 shot 有台词，优先真实人物说话感；若无台词，不要强行补旁白"
        tone = "情绪跟随角色状态变化，避免广告腔或解说腔"
        bgm = "背景音服务剧情情绪，可更电影化，但不要破坏对白可懂度"
    elif expression_type == "visual":
        voice = "默认无旁白；若当前 shot 没有 dialogue，不要暗示额外口播"
        tone = "以画面和节奏主导表达"
        bgm = "背景音或氛围音应承担主要情绪推进作用"
    else:
        voice = "中文中性旁白或自然口播，根据当前镜头内容保持稳定"
        tone = "信息表达清晰，不要抢画面"
        bgm = "背景音保持克制，优先保证主体表达清楚"

    delivery_style = "derived"
    bgm_action = "derived"
    bgm_intensity = "derived"
    continuity_group = "derived"
    if isinstance(shot_audio_strategy, dict):
        delivery_style = str(shot_audio_strategy.get("delivery_style") or delivery_style)
        bgm_action = str(shot_audio_strategy.get("bgm_action") or bgm_action)
        bgm_intensity = str(shot_audio_strategy.get("bgm_intensity") or bgm_intensity)
        continuity_group = str(shot_audio_strategy.get("continuity_group") or continuity_group)
        if shot_audio_strategy.get("voice_tone"):
            tone = str(shot_audio_strategy.get("voice_tone"))

    shot_rule = (
        f"当前 shot {'有明确台词，应保留并按该台词朗读' if dialogue.strip() else '没有明确台词，不要强行补口播'}。"
    )
    audience_rule = f"平台/受众参考: platform={platform or 'unknown'}, audience={audience or 'unknown'}。"
    mood_rule = f"语气需贴合当前镜头情绪: emotion={emotion}, intensity={intensity}。"
    return "\n".join(
        [
            f"表达类型: {expression_type}",
            f"建议音色: {voice}",
            f"建议语气: {tone}",
            f"背景音策略: {bgm}",
            f"当前 shot 声音执行: delivery_style={delivery_style}, bgm_action={bgm_action}, bgm_intensity={bgm_intensity}, continuity_group={continuity_group}",
            mood_rule,
            shot_rule,
            audience_rule,
        ]
    )


def _provider_to_text(profile: Any) -> str:
    """将 ProviderProfile 转为给 LLM 的能力说明文本。"""
    if profile is None:
        return "通用图片生成 provider，支持 natural prompt 风格，分辨率最高 2048x2048。"
    parts = [f"Provider: {profile.display_name}"]
    caps = profile.capabilities
    neg = caps.get("supports_negative_prompt", False)
    parts.append(f"支持负向 prompt: {'是' if neg else '否'}")
    durations = caps.get("supported_durations", [])
    if durations:
        parts.append(f"支持时长档位: {', '.join(str(int(float(duration))) for duration in durations)} 秒")
    ratios = caps.get("supported_aspect_ratios", [])
    if ratios:
        parts.append(f"支持宽高比: {', '.join(ratios)}")
    parts.append(f"Prompt 风格: {profile.prompt_style}")
    return "\n".join(parts)


def _build_character_set_text(
    char_set_version: Any,
    char_ids: list[str],
    section_type: str | None = None,
    *,
    character_refs: list | None = None,
) -> str:
    """从 CharacterSetVersion 或独立表数据提取指定角色的描述文字，用于 prompt 编译的 character_set 变量。

    WP7 适配：优先从 character_refs（独立表 ORM 对象列表）读取，JSONB 列已置空。
    提取内容：角色名 / 外貌描述 / 当前段落对应造型描述。
    """
    if not char_ids:
        return "（暂无角色绑定）"

    # 构建统一的 chars_data 列表
    if character_refs is not None:
        # WP7：从独立表 CharacterReference ORM 对象读取
        chars_data: list[dict] = [
            {
                "character_id": getattr(c, "character_id", ""),
                "character_name": getattr(c, "character_name", ""),
                "description": getattr(c, "description", ""),
                "appearance_description": getattr(c, "description", ""),
                "costumes": getattr(c, "costumes", []) or [],
            }
            for c in character_refs
        ]
    elif char_set_version is not None:
        chars_data = char_set_version.characters or []
    else:
        return "（暂无角色绑定）"

    char_lines: list[str] = []
    for c in chars_data:
        cid = c.get("character_id", "") if isinstance(c, dict) else getattr(c, "character_id", "")
        if cid not in char_ids:
            continue
        name = (c.get("character_name") or cid) if isinstance(c, dict) else (getattr(c, "character_name", "") or cid)
        # 外貌描述：支持多种字段名
        desc = (
            c.get("appearance_description")
            or c.get("description")
            or c.get("appearance_notes")
            or c.get("appearance")
            or ""
        ) if isinstance(c, dict) else getattr(c, "description", "")
        parts = [f"角色: {name}"]
        if desc:
            parts.append(f"外貌: {desc}")
        # 造型匹配：找当前段落对应的造型描述
        costumes: list = (c.get("costumes") or []) if isinstance(c, dict) else (getattr(c, "costumes", []) or [])
        for costume in costumes:
            applies = costume.get("applies_to_sections") or [] if isinstance(costume, dict) else getattr(costume, "applies_to_sections", [])
            if section_type and section_type in applies:
                costume_desc = (
                    costume.get("description")
                    or costume.get("costume_name")
                    or costume.get("costume_id")
                    or ""
                ) if isinstance(costume, dict) else getattr(costume, "description", "")
                if costume_desc:
                    parts.append(f"造型（{section_type}）: {costume_desc}")
                break
        char_lines.append(" / ".join(parts))

    return "\n".join(char_lines) if char_lines else "（暂无角色绑定）"


def _make_fallback_bundle(
    shot: Any,
    brief: Any,
    provider_name: str,
    *,
    ref_image_url: str | None = None,
    ref_asset_ids: list[str] | None = None,
    human_on_camera: bool | None = None,
) -> dict[str, Any]:
    """规则兑底：LLM 不可用时生成最小可用 bundle。

    doc11 修复：显式接收并保留 ref_image_url / ref_asset_ids，
    确保工具底路径不丢失参考图，维持检题一致性。
    """
    style_hint = ""
    if brief and brief.style_direction:
        style_hint = brief.style_direction + "，"
    emotion = (shot.emotion or "") if shot else ""
    shot_type = (shot.shot_type or "中景") if shot else "中景"
    camera = (shot.camera_language or "固定镜头") if shot else "固定镜头"
    duration_ms = getattr(shot, "duration_ms", 3000) or 3000
    duration_sec = round(duration_ms / 1000, 2)

    subject_hint = ""
    negative_extra = ""
    if human_on_camera is True:
        subject_hint = "真人主体入镜，人物表情自然，身份连续稳定，"
        negative_extra = "假人感，人物数量错误，"
    elif human_on_camera is False:
        subject_hint = "无人物、无人脸、无手部特写，以场景、产品或图形元素为主体，"
        negative_extra = "人物出镜，脸部特写，手部特写，"

    positive = (
        f"{style_hint}{emotion}，{shot_type}，{camera}，"
        f"{subject_hint}电影感光线，高质量，胶片质感"
    ).strip("，")

    result: dict[str, Any] = {
        "positive_prompt": positive,
        "negative_prompt": f"画质模糊，低质量，水印，解剖变形，面部扬曲，{negative_extra}".strip("，"),
        "params": {
            "aspect_ratio": "16:9",
            "duration_sec": duration_sec,
        },
        "reference_asset_ids": list(ref_asset_ids or []),
    }
    if ref_image_url:
        result["reference_image_url"] = ref_image_url
    return result


def _classify_aspect_ratio_orientation(aspect_ratio: str) -> str:
    """将业务宽高比归类为 square / portrait / landscape。"""
    ratio_str = (aspect_ratio or "1:1").strip().lower()
    if ratio_str == "1:1":
        return "square"

    try:
        parts = ratio_str.split(":")
        if len(parts) != 2:
            return "square"
        w = float(parts[0].strip())
        h = float(parts[1].strip())
        if h == 0:
            return "square"
        value = w / h
    except Exception:  # noqa: BLE001
        return "square"

    if abs(value - 1.0) < 0.05:
        return "square"
    return "landscape" if value > 1 else "portrait"


def _resolve_nine_grid_output_spec(aspect_ratio: str) -> dict[str, Any]:
    """九宫格固定生成 1:1 大图。

    约束：
      - 所有尺寸都必须能被 3 整除，保证九宫格切分无余数像素
      - 当前产品流程要求九宫格本身是 1:1 大图：3072x3072
      - 最终视频画幅仍由 clip/video 阶段按 ProjectSpec.aspect_ratio 控制
    """
    orientation = "square"
    width, height = 3072, 3072

    return {
        "orientation": orientation,
        "resolution": "2K",
        "width": width,
        "height": height,
        "size": f"{width}x{height}",
        "cell_width": width // 3,
        "cell_height": height // 3,
    }


# ---------------------------------------------------------------------------
# PromptCompilerService
# ---------------------------------------------------------------------------

class PromptCompilerService:
    """Prompt 编译服务：Shot + brief/style → PromptBundle。"""

    def __init__(self) -> None:
        self._renderer = PromptRenderer()

    async def compile_for_shot(
        self,
        session: AsyncSession,
        shot_id: str,
        project_id: str,
        *,
        target_type: str = "storyboard_frame",
        generation_mode: str = "image_to_video",
        first_frame_description: str | None = None,
        last_frame_description: str | None = None,
    ) -> PromptBundle:
        """为指定 shot 编译 PromptBundle 并落库。

        Args:
            session:     已开启的 AsyncSession（由调用方 UoW 提供）。
            shot_id:     要编译 prompt 的 shot ID。
            project_id:  所属项目 ID。
            target_type: 生成目标类型，默认 storyboard_frame。

        Returns:
            PromptBundle schema 对象（已落库 + 已写本地快照）。

        Raises:
            PromptCompilerError: shot 不存在时抛出；LLM 失败时使用兜底，不抛异常。
        """
        logger = get_project_logger(project_id, module="services.prompt_compiler")

        # ---- 步骤 1: 读取 Shot + brief + style + spec ----------------------------------------
        shot_repo = ShotRepository(session)
        brief_repo = CreativeBriefRepository(session)
        style_repo = StyleBibleRepository(session)
        spec_repo = ProjectSpecRepository(session)
        asset_repo = AssetRepository(session)

        shot = await shot_repo.get_by_id(shot_id)
        if shot is None:
            raise PromptCompilerError(
                f"Shot {shot_id!r} 不存在", code="shot_not_found"
            )

        brief = await brief_repo.get_active(project_id)
        style = await style_repo.get_active(project_id)
        spec = await spec_repo.get_active(project_id)

        # doc11 批次3修复：读取参考图（场景为主帧，角色图为全面附加一致性参考）
        ref_image_url: str | None = None
        ref_asset_ids: list[str] = []
        ref_assets_text = "（无参考素材）"

        binding: dict = {}
        if isinstance(getattr(shot, "character_binding", None), dict):
            binding = shot.character_binding

        # 支持新字段（多角色列表）和旧字段（单个 ID）向后兼容
        char_ref_ids: list[str] = binding.get("character_ref_asset_ids") or (
            [binding["character_ref_asset_id"]]
            if binding.get("character_ref_asset_id")
            else []
        )
        scene_ref_id: str | None = binding.get("scene_ref_asset_id")
        costume_ref_id: str | None = binding.get("costume_ref_asset_id")

        # ------------------------------------------------------------------
        # 多参考图 URL 收集（顺序：场景图 → 造型图 → 角色基础图）
        # qwen-image-2.0-pro 支持 1-3 张，齐全最好
        # ------------------------------------------------------------------
        ref_image_urls: list[str] = []  # 有序多参考图 URL 列表
        ref_url_asset_ids: list[str] = []  # 对应 asset_id（用于调试）

        async def _load_url(asset_id_val: str | None) -> str | None:
            if not asset_id_val:
                return None
            a = await asset_repo.get_by_id_for_project(asset_id_val, project_id)
            return a.storage_uri if a and a.storage_uri else None

        # 1. 场景参考图（定义场景环境与构图基底）
        scene_url = await _load_url(scene_ref_id)
        if scene_url:
            ref_image_urls.append(scene_url)
            ref_url_asset_ids.append(scene_ref_id)  # type: ignore[arg-type]
            ref_asset_ids.append(scene_ref_id)  # type: ignore[arg-type]

        # 2. 造型参考图（该段落对应造型，比角色基础图更准确）
        if costume_ref_id and costume_ref_id != scene_ref_id:
            costume_url = await _load_url(costume_ref_id)
            if costume_url:
                ref_image_urls.append(costume_url)
                ref_url_asset_ids.append(costume_ref_id)
                if costume_ref_id not in ref_asset_ids:
                    ref_asset_ids.append(costume_ref_id)

        # 3. 角色基础图（定妆图，强化脸型一致性）
        for cid in char_ref_ids[:1]:  # 取第一张，不超过 3 张总限
            if cid not in ref_url_asset_ids and len(ref_image_urls) < 3:
                char_url = await _load_url(cid)
                if char_url:
                    ref_image_urls.append(char_url)
                    ref_url_asset_ids.append(cid)
                    if cid not in ref_asset_ids:
                        ref_asset_ids.append(cid)

        # 其余角色参考图仅记录 asset_id，不加入 URL 列表（已超出 3 张限制）
        for cid in char_ref_ids:
            if cid not in ref_asset_ids:
                ref_asset_ids.append(cid)

        # 向后兼容：保留单图字段（取第一张作为主参考）
        ref_image_url = ref_image_urls[0] if ref_image_urls else None

        # 构建调试文本
        ref_url_count = len(ref_image_urls)
        if ref_url_count > 0:
            parts = []
            if scene_url:
                parts.append("场景图")
            if costume_ref_id and len(ref_image_urls) > 1:
                parts.append("造型图")
            if ref_url_count == 3:
                parts.append("角色基础图")
            ref_assets_text = f"多参考图 {ref_url_count} 张 ({', '.join(parts)})"
        else:
            ref_assets_text = "（无参考素材）"

        # ---- 步骤 2: 读取 provider profile ----------------------------------------
        # shot_clip 类型必须使用视频 provider，否则会拿到错误的 provider 名称导致视频生成失败
        registry = get_provider_registry()
        is_video_target = target_type in ("shot_clip", "lipsync_clip")
        if is_video_target:
            # 按 shot 时长选择最佳视频 provider（supported_durations 精确匹配 > 范围匹配 > 默认）
            _duration_sec = round((getattr(shot, "duration_ms", 0) or 0) / 1000, 1)
            provider_profile = registry.select_for_duration("video", _duration_sec)
            provider_name = provider_profile.name if provider_profile else "kling_v2"
        else:
            provider_profile = registry.get_default("image")
            provider_name = provider_profile.name if provider_profile else "flux_schnell"

        # ---- 步骤 2.5: 构建角色描述文字（供 prompt 编译 LLM 使用） -----------------
        # 从 CharacterSetVersion 提取匹配角色的名字/外貌/造型描述
        char_set_text = "（暂无角色绑定）"
        char_ids_for_lookup: list[str] = binding.get("character_ids") or []
        if char_ids_for_lookup:
            try:
                csv_repo = CharacterSetVersionRepository(session)
                active_csv = await csv_repo.get_active(project_id)
                if active_csv is not None:
                    section_type_val = getattr(shot, "section_type", None)
                    # WP7 适配：从独立表查询角色参考图数据（JSONB 列已置空）
                    from app.repositories.character_reference_repository import CharacterReferenceRepository
                    _char_ref_rows_for_text = await CharacterReferenceRepository(session).list_by_version(active_csv.id)
                    char_set_text = _build_character_set_text(
                        active_csv, char_ids_for_lookup, section_type_val,
                        character_refs=_char_ref_rows_for_text,
                    )
            except Exception as _csv_exc:  # noqa: BLE001
                logger.warning(
                    f"PromptCompiler 读取 CharacterSetVersion 失败，使用空角色绑定: {_csv_exc!r}",
                    event_type="prompt_compiler_csv_read_failed",
                )

        # ---- 步骤 3: 渲染 prompt 模板 + LLM 调用 ----------------------------------------
        rendered_result = await self._call_llm(
            shot=shot,
            brief=brief,
            style=style,
            spec=spec,
            provider_profile=provider_profile,
            project_id=project_id,
            logger=logger,
            is_video=is_video_target,
            generation_mode=generation_mode,
            ref_assets_text=ref_assets_text,
            ref_image_url=ref_image_url,    # 将参考图 URL 传入，准认工具底也显式保留
            ref_asset_ids=ref_asset_ids,    # 将全部参考图 ID 传入，准认工具底也显式保留
            character_set_text=char_set_text,  # 角色描述文字（外貌/造型）
            first_frame_description=first_frame_description,  # doc 21 §3.2 i2v 首帧
            last_frame_description=last_frame_description,    # doc 21 §3.2 i2v 尾帧
        )

        # ---- 步骤 4: 构建 PromptBundle schema ----------------------------------------
        # doc11 批次3：合并 LLM 输出的 reference_asset_ids 与视觉圣经绑定的 ref_asset_ids
        llm_ref_ids: list = rendered_result.get("reference_asset_ids") or []
        merged_ref_ids = list(dict.fromkeys(ref_asset_ids + llm_ref_ids))

        bundle = PromptBundle(
            bundle_id=generate_ulid(),
            target_type=target_type,  # type: ignore[arg-type]
            target_id=shot_id,
            provider=provider_name,
            positive_prompt=rendered_result.get("positive_prompt", ""),
            negative_prompt=rendered_result.get("negative_prompt"),
            reference_asset_ids=merged_ref_ids,
            reference_image_url=ref_image_url,          # 向后兼容，单图主参考
            reference_image_urls=ref_image_urls,        # 多参考图列表（场景→造型→角色）
            reference_weight=0.75,
            params=rendered_result.get("params", {}),
            source_brief_version_id=brief.id if brief else None,
            source_style_version_id=style.id if style else None,
        )

        # ---- 步骤 5: 落库 ----------------------------------------
        orm = PromptBundleModel(
            id=bundle.bundle_id,
            project_id=project_id,
            target_type=target_type,
            target_id=shot_id,
            provider=provider_name,
            positive_prompt=bundle.positive_prompt,
            negative_prompt=bundle.negative_prompt,
            params=bundle.params,
            source_brief_version_id=bundle.source_brief_version_id,
            source_style_version_id=bundle.source_style_version_id,
            # Bug 2 修复：保存参考图溯源信息，供事后调试
            reference_image_url=getattr(bundle, "reference_image_url", None),
            reference_asset_ids=getattr(bundle, "reference_asset_ids", None) or [],
        )
        bundle_repo = PromptBundleRepository(session)
        await bundle_repo.add(orm)
        await session.flush()

        # ---- 步骤 6: 写本地快照 ----------------------------------------
        # BUG-11 修复：原快照缺少 reference_image_urls 和 reference_asset_ids，
        # 调试分镜质量问题时无法得知该镜头用了哪年张参考图。补充完整字段。
        store = LocalArtifactStore(project_id)
        store.write_json(
            ArtifactStage.PROMPT_BUNDLES,
            f"bundle_shot_{shot.shot_index:03d}",
            {
                "bundle_id": bundle.bundle_id,
                "shot_id": shot_id,
                "shot_index": shot.shot_index,
                "target_type": target_type,
                "provider": provider_name,
                "positive_prompt": bundle.positive_prompt,
                "negative_prompt": bundle.negative_prompt,
                "params": bundle.params,
                "reference_image_urls": getattr(bundle, "reference_image_urls", []) or [],
                "reference_asset_ids": getattr(bundle, "reference_asset_ids", []) or [],
            },
        )

        logger.info(
            f"PromptBundle 编译完成: shot={shot.shot_index} provider={provider_name!r}",
            event_type="prompt_bundle_compiled",
        )
        return bundle

    # ------------------------------------------------------------------
    # 内部：LLM 调用
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        *,
        shot: Any,
        brief: Any,
        style: Any,
        spec: Any | None,
        provider_profile: Any,
        project_id: str,
        logger: Any,
        is_video: bool = False,
        generation_mode: str = "image_to_video",
        ref_assets_text: str = "（无参考素材）",
        ref_image_url: str | None = None,
        ref_asset_ids: list[str] | None = None,
        character_set_text: str = "（暂无角色绑定）",
        first_frame_description: str | None = None,
        last_frame_description: str | None = None,
    ) -> dict[str, Any]:
        """渲染 compile_*_prompt.md 并调用 LLM，失败时兑底。

        is_video=True 时使用 compile_video_prompt（shot_clip / lipsync_clip），
        否则使用 compile_image_prompt（storyboard_frame）。
        ref_image_url / ref_asset_ids 传递给兑底逻辑，确保其不丢失参考图。
        character_set_text 来自 CharacterSetVersion，包含角色名/外貌/造型描述。
        """
        cfg = get_config()
        provider_name = provider_profile.name if provider_profile else (
            "kling_v2" if is_video else "flux_schnell"
        )
        human_on_camera = _extract_human_on_camera(brief)

        # 根据目标类型选择模板
        template_name = "compile_video_prompt" if is_video else "compile_image_prompt"
        base_vars = {
            "style_bible": _style_bible_to_text(brief, style),
            "character_set": character_set_text,  # 角色外貌/造型描述（来自 CharacterSetVersion）
            "shot_spec": _shot_to_spec_text(shot),
            "provider_profile": _provider_to_text(provider_profile),
            "reference_assets": ref_assets_text,
        }
        if is_video:
            base_vars["generation_mode"] = generation_mode
            base_vars["audio_direction"] = _derive_audio_direction_text(
                brief=brief,
                shot=shot,
                spec=spec,
            )
            # doc 21 §3.2：i2v 模式接受首尾帧描述（来自九宫格切分图所对应的 narrative shot）
            base_vars["first_frame_description"] = first_frame_description or "（无首帧描述）"
            base_vars["last_frame_description"] = last_frame_description or "（无尾帧描述）"

        try:
            # 渲染 prompt 模板
            prompt_text = self._renderer.render(
                template_name,
                variables=base_vars,
            )

            # 构建 LLM 客户端
            llm = ChatOpenAI(
                model=cfg.llm.model,
                api_key=cfg.llm.api_key or "sk-placeholder",  # type: ignore[arg-type]
                base_url=cfg.llm.base_url,
                temperature=cfg.llm.temperature,
                max_tokens=cfg.llm.max_tokens,
                timeout=cfg.llm.timeout,
            )

            response = await llm.ainvoke(prompt_text)
            raw_text = response.content if hasattr(response, "content") else str(response)
            parsed = _safe_parse_json(str(raw_text))

            if parsed and parsed.get("positive_prompt"):
                return parsed

        except Exception as exc:
            logger.warning(
                f"PromptCompiler LLM 调用失败（使用规则兜底）: {exc}",
                event_type="prompt_compiler_llm_failed",
            )

        # 规则兑底（显式保留参考图，确保图片生成能走 img2img 不失去一致性）
        logger.info(
            "PromptCompiler 使用规则兑底生成 bundle",
            event_type="prompt_compiler_fallback",
        )
        return _make_fallback_bundle(
            shot=shot,
            brief=brief,
            provider_name=provider_name,
            ref_image_url=ref_image_url,
            ref_asset_ids=ref_asset_ids,
            human_on_camera=human_on_camera,
        )

    # ------------------------------------------------------------------
    # doc 21 §3.2 九宫格 prompt 编译
    # ------------------------------------------------------------------

    async def compile_nine_grid_prompt(
        self,
        session: AsyncSession,
        project_id: str,
        grid_index: int,
        total_grids: int,
        *,
        shot_descriptions: list[dict],
        prev_cell9_description: str | None = None,
    ) -> PromptBundle:
        """编译九宫格生图 prompt（doc 21 §3 + §6）。

        Args:
            session:                已开启的 AsyncSession
            project_id:             所属项目 ID
            grid_index:             第几张九宫格（从 1 开始）
            total_grids:            总九宫格张数
            shot_descriptions:      9 个 cell 对应的 shot 描述列表（含 start_frame/end_frame/scene_description 等）
            prev_cell9_description: 跨九宫格衔接（doc 21 §3.2）：
                grid_index >= 2 时传入上一张 cell9 的画面描述

        Returns:
            PromptBundle（target_type='nine_grid_image', target_id=f"grid_{grid_index:03d}"）
        """
        logger = get_project_logger(project_id, module="services.prompt_compiler")

        # 1. 读 brief（含 raw_payload 中的 CreativeBriefExtension）
        brief_repo = CreativeBriefRepository(session)
        brief = await brief_repo.get_active(project_id)
        if brief is None:
            raise PromptCompilerError(
                "未找到 active brief，无法编译九宫格 prompt",
                code="no_brief",
            )

        # 2. 解析 extension（doc 21 §1.1：extension 是 raw_payload 的子字段）
        from app.schemas.project import CreativeBriefExtension  # noqa: PLC0415

        brief_payload = brief.raw_payload or {}
        if isinstance(brief_payload.get("creative_brief"), dict):
            brief_payload = brief_payload.get("creative_brief") or {}
        ext_dict = brief_payload.get("extension") or {}
        try:
            ext = CreativeBriefExtension(**ext_dict)
        except Exception as exc:  # noqa: BLE001
            raise PromptCompilerError(
                f"brief.raw_payload.extension 字段无效: {exc}",
                code="invalid_extension",
            ) from exc

        # 3. 读 style（用于 style_direction 兜底）
        style_repo = StyleBibleRepository(session)
        style = await style_repo.get_active(project_id)
        style_direction = brief.style_direction or (
            f"{(style.lighting_style or '')}, {(style.camera_style or '')}".strip(", ")
            if style
            else "电影感画面，高质量"
        )

        # 4. 渲染 prompt 模板
        char_list_json = json.dumps(
            [c.model_dump() for c in ext.character_list],
            ensure_ascii=False,
            indent=2,
        )
        shot_desc_json = json.dumps(
            shot_descriptions, ensure_ascii=False, indent=2
        )
        base_vars = {
            "grid_index": grid_index,
            "total_grids": total_grids,
            "shot_descriptions_json": shot_desc_json,
            "character_list_json": char_list_json,
            "style_direction": style_direction,
            "aspect_ratio": ext.aspect_ratio,
            "prev_cell9_description": prev_cell9_description or "",
            "human_on_camera": "true" if ext.human_on_camera else "false",
            "human_on_camera_text": (
                "需要真人入镜，关键画面应以真人主体为核心，保持人物外观和服装连续一致。"
                if ext.human_on_camera
                else "不需要真人入镜，九宫格中不要出现真人脸、真人身体或真人手部特写，优先场景、产品、图形和抽象主体。"
            ),
        }
        grid_spec = _resolve_nine_grid_output_spec(ext.aspect_ratio)
        base_vars.update(
            {
                "grid_width": grid_spec["width"],
                "grid_height": grid_spec["height"],
                "grid_resolution": grid_spec["resolution"],
                "grid_orientation": grid_spec["orientation"],
                "cell_width": grid_spec["cell_width"],
                "cell_height": grid_spec["cell_height"],
            }
        )

        # 5. 调 LLM
        cfg = get_config()
        rendered_result: dict = {}
        try:
            prompt_text = self._renderer.render(
                "generate_nine_grid",
                variables=base_vars,
            )
            llm = ChatOpenAI(
                model=cfg.llm.model,
                api_key=cfg.llm.api_key or "sk-placeholder",  # type: ignore[arg-type]
                base_url=cfg.llm.base_url,
                temperature=cfg.llm.temperature,
                max_tokens=cfg.llm.max_tokens,
                timeout=cfg.llm.timeout,
            )
            response = await llm.ainvoke(prompt_text)
            raw_text = response.content if hasattr(response, "content") else str(response)
            parsed = _safe_parse_json(str(raw_text))
            if parsed and parsed.get("positive_prompt"):
                rendered_result = parsed
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"九宫格 prompt LLM 调用失败（使用兜底）: {exc}",
                event_type="nine_grid_compiler_llm_failed",
            )

        # 6. 兜底
        if not rendered_result.get("positive_prompt"):
            rendered_result = _make_fallback_nine_grid_prompt(
                ext, grid_index, total_grids, prev_cell9_description
            )

        # 7. 选择 image provider
        registry = get_provider_registry()
        provider_profile = registry.get_default("image")
        provider_name = provider_profile.name if provider_profile else "flux_schnell"

        # 8. 构建 PromptBundle
        bundle = PromptBundle(
            bundle_id=generate_ulid(),
            target_type="nine_grid_image",  # type: ignore[arg-type]
            target_id=f"grid_{grid_index:03d}",
            provider=provider_name,
            positive_prompt=rendered_result.get("positive_prompt", ""),
            negative_prompt=rendered_result.get("negative_prompt"),
            reference_asset_ids=[],
            reference_image_url=None,
            reference_image_urls=[],
            reference_weight=0.75,
            params={
                "aspect_ratio": ext.aspect_ratio,
                "size": grid_spec["size"],
                "resolution": grid_spec["resolution"],
                "orientation": grid_spec["orientation"],
                "width": grid_spec["width"],
                "height": grid_spec["height"],
            },
            source_brief_version_id=brief.id,
            source_style_version_id=style.id if style else None,
        )

        # 9. 落库 PromptBundle
        orm = PromptBundleModel(
            id=bundle.bundle_id,
            project_id=project_id,
            target_type="nine_grid_image",
            target_id=f"grid_{grid_index:03d}",
            provider=provider_name,
            positive_prompt=bundle.positive_prompt,
            negative_prompt=bundle.negative_prompt,
            params=bundle.params,
            source_brief_version_id=bundle.source_brief_version_id,
            source_style_version_id=bundle.source_style_version_id,
            reference_image_url=None,
            reference_asset_ids=[],
        )
        bundle_repo = PromptBundleRepository(session)
        await bundle_repo.add(orm)
        await session.flush()

        # 10. 写本地快照
        store = LocalArtifactStore(project_id)
        store.write_json(
            ArtifactStage.PROMPT_BUNDLES,
            f"bundle_grid_{grid_index:03d}",
            {
                "bundle_id": bundle.bundle_id,
                "target_type": "nine_grid_image",
                "grid_index": grid_index,
                "total_grids": total_grids,
                "provider": provider_name,
                "positive_prompt": bundle.positive_prompt,
                "negative_prompt": bundle.negative_prompt,
                "params": bundle.params,
            },
        )

        logger.info(
            f"九宫格 prompt 编译完成: grid_index={grid_index} provider={provider_name!r}",
            event_type="nine_grid_prompt_compiled",
        )
        return bundle


def _make_fallback_nine_grid_prompt(
    ext: Any,
    grid_index: int,
    total_grids: int,
    prev_cell9_description: str | None,
) -> dict:
    """LLM 不可用时的简单兜底（doc 21 §3 九宫格架构）。"""
    char_descs = "; ".join(
        f"{c.name}: {c.appearance}" for c in ext.character_list
    ) or "no fixed character"

    bridge_note = ""
    if prev_cell9_description:
        bridge_note = f" Cell 1 must visually match the previous grid's cell 9: {prev_cell9_description}."

    grid_spec = _resolve_nine_grid_output_spec(ext.aspect_ratio)

    positive = (
        f"A 3x3 grid of nine sequential cinematic frames for an AI explainer video, "
        f"frame {grid_index} of {total_grids}.{bridge_note} "
        f"Each cell shows a continuous narrative moment from top-left to bottom-right. "
        f"Characters: {char_descs}. "
        + (
            "真人主体必须进入关键画面并保持同一人物的脸部、发型、服装连续一致。 "
            if ext.human_on_camera
            else "不要出现真人脸、真人身体或真人手部特写，主体应保持为产品、场景、图形化元素或抽象视觉。 "
        )
        + "Maintain identical character appearance, costume and lighting across all cells. "
        f"Use full-bleed edge-to-edge composition with no white border, no white outer frame, "
        f"no card-style padding, and no thick divider bars. "
        f"Aspect ratio per cell: {ext.aspect_ratio}. "
        f"High quality, detailed, consistent style, clean cell boundaries."
    )
    return {
        "positive_prompt": positive,
        "negative_prompt": (
            "blurry, watermark, text overlay, distorted faces, "
            "mismatched character appearance, inconsistent lighting, "
            "merged cells, blurred boundaries, white border, white frame, "
            "white divider, wide padding"
            + (", mannequin face, missing presenter" if ext.human_on_camera else ", human face, human body, human hand")
        ),
        "params": {
            "aspect_ratio": ext.aspect_ratio,
            "size": grid_spec["size"],
            "resolution": grid_spec["resolution"],
            "orientation": grid_spec["orientation"],
            "width": grid_spec["width"],
            "height": grid_spec["height"],
            "seed": None,
        },
    }
