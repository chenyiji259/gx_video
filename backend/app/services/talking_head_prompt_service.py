"""口播 Production Board prompt 编译辅助。"""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.logging import get_project_logger
from app.core.prompt_renderer import PromptRenderer
from app.core.provider_registry import get_provider_registry
from app.models.prompt_bundle import PromptBundleModel
from app.repositories.planning_repositories import CreativeBriefRepository, StyleBibleRepository
from app.repositories.project_spec_repository import ProjectSpecRepository
from app.repositories.prompt_bundle_repository import PromptBundleRepository
from app.repositories.visual_bible_repository import NarrativeScriptVersionRepository
from app.schemas.prompt import PromptBundle
from app.services.output_spec_service import (
    TALKING_HEAD_LAYOUT,
    TALKING_HEAD_SEGMENT_DURATION_SEC,
    TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
    TALKING_HEAD_STORY_BOARD_IMAGE_SIZE,
    TALKING_HEAD_STORY_BOARD_ASPECT_RATIO,
)
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.path_planner import ArtifactStage
from app.storage.storage_factory import get_storage
from app.utils.ids import generate_ulid
from app.utils.json_utils import safe_parse_json


def segment_time_range(index_zero_based: int) -> str:
    start = index_zero_based * TALKING_HEAD_SEGMENT_DURATION_SEC
    end = start + TALKING_HEAD_SEGMENT_DURATION_SEC
    return f"{start}-{end}s"


def _brief_payload(brief: Any) -> dict[str, Any]:
    raw = getattr(brief, "raw_payload", None) or {}
    if isinstance(raw.get("creative_brief"), dict):
        return raw.get("creative_brief") or {}
    return raw


def _json_text(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, indent=2)


def _clean_reference_list(references: list[str]) -> list[str]:
    return [str(item).strip() for item in references if str(item or "").strip()]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _story_board_topic(*, spec: Any, brief_payload: dict[str, Any]) -> str:
    ext = brief_payload.get("extension") or {}
    return (
        ext.get("topic")
        or brief_payload.get("title")
        or brief_payload.get("project_title")
        or getattr(spec, "user_prompt", "")
        or "中文口播科普视频"
    )


def _segment_title(segment: dict[str, Any], index: int, topic: str) -> str:
    return (
        segment.get("segment_title")
        or segment.get("title")
        or segment.get("subject")
        or f"{topic} 第 {index + 1} 段"
    )


def _segment_goal(segment: dict[str, Any], topic: str) -> str:
    return (
        segment.get("segment_goal")
        or segment.get("goal")
        or segment.get("action_description")
        or segment.get("scene_description")
        or f"围绕{topic}完成本段口播讲解"
    )


def _segment_dialogue(segment: dict[str, Any]) -> str:
    return (
        segment.get("dialogue")
        or segment.get("voiceover_script")
        or segment.get("lyric_text")
        or "按本段主题自然口播"
    )


def _split_dialogue(dialogue: str) -> list[str]:
    text = str(dialogue or "").strip()
    if not text:
        return ["按本段主题自然口播"] * 4
    parts = [item.strip(" ，。；;") for item in text.replace("！", "。").replace("？", "。").split("。") if item.strip()]
    if not parts:
        parts = [text]
    while len(parts) < 4:
        parts.append(parts[-1])
    return parts[:4]


def _build_story_overview_board_prompt(
    *,
    spec: Any,
    brief_payload: dict[str, Any],
    style_payload: dict[str, Any],
    narrative_payload: dict[str, Any],
    host_assets: list[str],
    audio_assets: list[str],
) -> dict[str, Any]:
    output_config = getattr(spec, "output_config", None) or {}
    segments = list(narrative_payload.get("shots") or [])
    target_duration = int(output_config.get("target_duration_sec") or len(segments) * TALKING_HEAD_SEGMENT_DURATION_SEC or 60)
    expected_segments = max(1, target_duration // TALKING_HEAD_SEGMENT_DURATION_SEC)
    if len(segments) < expected_segments:
        segments.extend({} for _ in range(expected_segments - len(segments)))
    segments = segments[:expected_segments]
    topic = _story_board_topic(spec=spec, brief_payload=brief_payload)
    style_text = (
        output_config.get("style_preference")
        or brief_payload.get("style_direction")
        or "专家知识口播，专业、亲和、干净护肤科普，纯净无字幕画面"
    )
    audience = output_config.get("target_audience") or "目标用户"
    platform = output_config.get("platform") or "短视频平台"
    host_lock = (
        "参考上传人物的整体气质、身形、服装和姿态。主角是一位成熟、理性、专业的男性知识型科普讲师，"
        "保留短黑发轮廓、黑框眼镜轮廓、灰色衬衫、白色内搭、冷静可信的讲解气质。"
        "所有出现主角的位置都必须是无五官占位脸，不能出现可识别真人脸。"
    )
    scene_lock = (
        brief_payload.get("set_design_profile")
        or (style_payload.get("visual_style", {}) if isinstance(style_payload.get("visual_style"), dict) else {}).get("environment")
        or "现代护肤科普工作室。暖灰色或浅米色背景，柔和暖白光，桌面有护肤品包装、成分卡片、简洁分子结构图和皮肤屏障示意卡。"
    )
    segment_blocks: list[str] = []
    reading_map: dict[str, str] = {}
    for idx, segment in enumerate(segments):
        time_range = segment_time_range(idx)
        title = _segment_title(segment, idx, topic)
        goal = _segment_goal(segment, topic)
        dialogue_parts = _split_dialogue(_segment_dialogue(segment))
        scene = segment.get("scene_description") or scene_lock
        action = segment.get("action_description") or "占位主角面对镜头自然讲解，配合克制手势和产品/图示插入镜头。"
        reading_map[f"segment_{idx + 1}"] = f"只读取故事大图中 Segment {idx + 1} / {time_range} 区域"
        segment_blocks.append(
            "\n".join([
                f"段落{idx + 1} / {time_range}",
                f"标题：{title}",
                f"本段目标：{goal}",
                f"统一场景提示：{scene}",
                f"动作提示：{action}",
                f"画面1：中近景，占位主角看向镜头方向，冷静开场，脸部无五官。镜头：35mm。景别：中近景。运镜：固定。台词提示：「{dialogue_parts[0]}」",
                f"画面2：轻微 push-in，占位主角抬手解释，旁边出现简洁成分/概念卡片。镜头：50mm。景别：中近景。运镜：轻微 push-in。台词提示：「{dialogue_parts[1]}」",
                f"画面3：产品瓶、成分卡片或皮肤示意图特写，占位主角手部轻轻指向卡片。镜头：85mm macro。景别：产品 close-up。运镜：缓慢 push-in。台词提示：「{dialogue_parts[2]}」",
                f"画面4：回到占位主角中近景，面对镜头方向总结，用头部姿态表现专业亲和，不画五官。镜头：50mm。景别：close-up。运镜：固定后轻微 push-in。台词提示：「{dialogue_parts[3]}」",
            ])
        )
    positive = f"""
请基于上传人物参考图，创建一张“{target_duration}秒中文口播科普视频全局 Production Board / 全局导演制作板”。

重要规则：
这张图用于后续视频模型测试。图中的人物只允许作为“无五官占位主持人”出现，不要绘制可识别真人脸。人物可以保留身体轮廓、发型轮廓、灰色衬衫、白色内搭、黑框眼镜轮廓、手势、坐姿和服装风格，但脸部必须是柔和空白脸或浅色无五官脸部轮廓。不要生成真实眼睛、鼻子、嘴巴、皮肤细节或可识别面部纹理。真正的人脸身份后续会由视频生成请求中的授权人像素材提供。

图内所有可见文字默认使用中文。除了必要专业镜头词汇如 push-in、close-up、macro、BGM、Seedance，其余标题、分区名、台词、说明、约束都必须用中文。

项目主题：
《{topic}》

视频类型：
单人固定主角中文科普口播视频，面向{audience}，发布平台：{platform}。风格：{style_text}。

固定主角占位规则：
{host_lock}

统一场景：
{scene_lock}

画面规格：
横向超宽 21:9，4K，电影级商业科普全局导演制作板，网格化布局，信息清晰，专业前期视觉规划表风格。

顶部栏：全局创意方向
展示以下中文信息：项目标题：{topic}；视频形式：单人中文科普口播；内容类型：知识科普/护肤成分科普；总时长：{target_duration}秒；结构：{expected_segments}个段落，每段15秒；主角：同一位男性讲师占位；场景：护肤科普工作室；色彩基调：暖灰、柔米、洁白、浅琥珀、科学蓝点缀。

左侧板块：主角身份与造型锁定
展示同一位无五官占位男性主角的多种口播状态：正面中近景、三分之二侧脸、近景脸部轮廓、手势讲解、坐在桌前讲解、轻微微笑姿态。板块内写明：同一主角占位、同一发型轮廓、同一眼镜轮廓、同一灰色衬衫、成熟专业气质、脸部无五官，不可识别真人脸。

中上板块：环境与场景设计锁定
展示统一讲解场景：无五官占位主角坐在护肤科普桌前，桌面有产品、成分卡片、小型台灯、简洁背景架。右侧加入俯视机位图，标出统一机位：主机位中近景、轻微 push-in、产品 macro、手部示意、成分卡片插入、回到主角 close-up。

中部主板块：故事板 / {expected_segments}个段落 / {target_duration}秒
把中部区域清晰分成{expected_segments}个段落区域，每个段落都有明显编号和边界。每个段落只包含自己的15秒内容，不要让不同段落的台词和镜头混在一起。所有故事板里的人物都必须是无五官占位主持人，不要出现真实人脸。

{chr(10).join(segment_blocks)}

底部左侧：灯光 / 氛围 / 风格注释
柔和主光、暖色背景灯、干净护肤质感、舒适对比。关键词：专业、冷静、可信、干净、温暖、成熟男性讲师。

底部中间：音频 / 声调锁定
声音：成熟中文男性声线，冷静、清晰、专业、亲和。语速：中等，有自然停顿，不夸张推销。BGM：轻柔干净，低音量，生活方式与科技感之间。

底部右侧：摄影语言注释
镜头选择：35mm 用于主角中近景，50mm 用于讲解 close-up，85mm macro 用于产品和成分卡片。运镜风格：大部分固定，重点处轻微 push-in，干净产品插入镜头。视觉理念：同一占位主角、同一工作室、清晰教育表达、高级护肤品牌质感。

全局一致性要求：
所有段落里的身体、服装、发型轮廓、眼镜轮廓、场景、桌面、灯光、产品摆放、色彩和摄影语言必须保持统一。每个段落只改变台词重点、手势、辅助图示和产品特写角度。所有人物脸部必须无五官，不可识别真人脸。

禁止：
不要生成真实可识别真人脸，不要画眼睛鼻子嘴巴，不要画真实面部纹理，不要让脸像上传参考图本人。不要生成最终视频画面，不要让一个画面覆盖所有段落，不要把不同段落混在同一个故事板格子里。不要生成多个不同男人，不要生成女性主持人，不要生成医生白大褂，不要生成夸张网红直播间，不要生成杂乱背景，不要水印，不要品牌logo，不要低质量排版。
""".strip()
    return {
        "image_positive_prompt": positive,
        "image_negative_prompt": "真实清晰的人脸五官, 眼睛, 鼻子, 嘴巴, 真实面部纹理, 可识别真人脸, 女性主持人, 多个不同主持人, 医生白大褂, 直播间, 综艺棚, 英文大段文字, 字幕条, 水印, 品牌Logo, 医疗功效承诺文字, 杂乱背景, 低质量排版, 低分辨率, 最终成片画面",
        "image_params": {
            "aspect_ratio": TALKING_HEAD_STORY_BOARD_ASPECT_RATIO,
            "size": TALKING_HEAD_STORY_BOARD_IMAGE_SIZE,
            "resolution": TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
            "orientation": "landscape",
            "board_type": TALKING_HEAD_LAYOUT,
            "segment_count": expected_segments,
            "target_duration_sec": target_duration,
        },
        "layout_reading_map": reading_map,
        "source_trace": {
            "host_reference_image_assets": host_assets,
            "reference_audio_assets": audio_assets,
        },
    }


def _fallback_story_board_prompt(
    *,
    spec: Any,
    brief_payload: dict[str, Any],
    narrative_payload: dict[str, Any],
    host_assets: list[str],
    audio_assets: list[str],
) -> dict[str, Any]:
    ext = brief_payload.get("extension") or {}
    segments = narrative_payload.get("shots") or []
    topic = ext.get("topic") or brief_payload.get("title") or getattr(spec, "user_prompt", "")
    segment_lines = []
    for idx, segment in enumerate(segments):
        segment_lines.append(
            f"Segment {idx + 1} / {segment_time_range(idx)}："
            f"{segment.get('segment_goal') or segment.get('action_description') or segment.get('scene_description') or topic}，"
            f"台词：{segment.get('dialogue') or segment.get('voiceover_script') or '按本段主题自然口播'}"
        )
    positive = (
        "生成一张 21:9 中文 Story Overview Board / 口播 Production Board，覆盖完整视频，"
        "内部清晰分成 4 个或对应数量的 15 秒 Segment 区域。"
        "画面包含全局创意圣经、同一主持人身份锁、统一讲解场景、机位图、每段台词、微镜头、"
        "灯光、音频声色和摄影规则。可见文字使用中文。"
        f"主题：{topic}。"
        f"Segments：{'；'.join(segment_lines)}。"
        "固定人物参考资产只锁定脸部身份、年龄感、气质和基础身形，不锁死服装；"
        "服装与道具以故事大图当前段落设计为主。"
        "制作板中的主持人面部需要遮住或弱化真实五官，只保留发型、眼镜轮廓、头部比例、"
        "身体姿态、服装、场景、动作和道具信息，避免生成可识别真人脸。"
    )
    return {
        "image_positive_prompt": positive,
        "image_negative_prompt": "英文大段文字，字幕条，水印，真实品牌 logo，医疗功效承诺，多位主持人，混乱网格，低清晰度",
        "image_params": {
            "aspect_ratio": TALKING_HEAD_STORY_BOARD_ASPECT_RATIO,
            "size": TALKING_HEAD_STORY_BOARD_IMAGE_SIZE,
            "resolution": TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
            "orientation": "landscape",
            "board_type": TALKING_HEAD_LAYOUT,
        },
        "layout_reading_map": {
            f"segment_{idx + 1}": f"只读取故事大图中 Segment {idx + 1} / {segment_time_range(idx)} 区域"
            for idx, _ in enumerate(segments)
        },
        "source_trace": {
            "host_reference_image_assets": host_assets,
            "reference_audio_assets": audio_assets,
        },
    }


def _fallback_video_prompt(
    *,
    shot: Any,
    segment_script: dict[str, Any],
    story_board_url: str,
    host_assets: list[str],
    audio_assets: list[str],
    layout_reading_map: dict[str, Any],
) -> dict[str, Any]:
    index = int(getattr(shot, "shot_index", 0) or 0)
    segment_key = f"segment_{index + 1}"
    instruction = str(
        layout_reading_map.get(segment_key)
        or f"只读取故事大图中 Segment {index + 1} / {segment_time_range(index)} 区域"
    )
    dialogue = (
        segment_script.get("dialogue")
        or segment_script.get("voiceover_script")
        or getattr(shot, "dialogue", "")
        or ""
    )
    goal = segment_script.get("segment_goal") or segment_script.get("action_description") or "围绕本段主题进行护肤科普讲解"
    positive = f"""
生成一个 15 秒中文单人护肤科普口播视频。

你会收到四张参考图片和三段参考音频：
图片1、图片2、图片3是同一位 50岁男性护肤专家 的固定角色资产，不是三位不同角色。图片1是唯一服装与整体造型基准，人物上衣、内搭、颜色、领口、袖口、配饰和穿搭风格必须全程严格保持图片1一致。图片2、图片3只用于补充锁定同一角色的脸部身份、年龄感、五官气质和基础身形，不允许从图片2、图片3引入新服装、新性别、新职业气质或新的造型风格。
图片4是 Production Board / 故事大图，不是最终视频画面。图片4必须作为参考图使用，但只读取当前区域：{instruction}。图片4只用于参考当前 Segment 的位置、构图、护肤科普工作室场景、桌面产品、道具、辅助视觉和镜头氛围；不要读取、复刻或依赖图片4里的中文文字、台词、标题、编号说明、小字段落或乱码文字。
音频1、音频2、音频3只用于参考音色、声线质感、年龄感、口音和说话气质，不承载对白内容，不照搬原音频内容、节奏或停顿。

本次只生成 Segment {index + 1} / {segment_time_range(index)}。当前段语义来自结构化脚本和镜头计划，不依赖图片4 OCR。
本段目标：{goal}。
完整台词参考：「{dialogue or '本段可包含开场动画、产品特写、自然停顿或少量无对白片段'}」

分时间段生成真实口播和动作：
0-3 秒：中近景，50岁男性护肤专家保持图片1服装和整体造型，面对镜头平静建立本段主题，口型和台词自然同步。
3-7 秒：轻微 push-in，主角抬手做克制讲解手势，语气专业亲和，桌面护肤品和辅助概念视觉保持在画面边缘。
7-11 秒：切到产品、成分卡片或皮肤/分子示意的 close-up / macro，画面只呈现干净道具和视觉符号，不出现可读小字或字幕。
11-15 秒：回到主角中近景，主角看向镜头总结，表情可信、动作稳定，延续同一服装、同一人物、同一工作室灯光。

不要生成 Production Board 页面，不要生成网格排版，不要生成顶部标题栏，不要生成分区说明文字，不要生成故事板卡片，不要生成任何可见字幕或文字贴片。不要换脸，不要换发型，不要换眼镜，不要换服装，不要改变为女性专家，不要出现第二个人，不要跳到新场景，不要读取其他 Segment 的故事内容。
""".strip()
    return {
        "positive_prompt": positive,
        "negative_prompt": "字幕，水印，标题栏，文字贴片，Production Board 页面，网格排版，多人物，换脸，换年龄感，换装，服装漂移，改性别，女性专家，白大褂，西装，耳饰，照抄故事大图乱码文字，读取其他 Segment，跳到新场景，夸张表演",
        "board_segment_reading_instruction": instruction,
        "dialogue_script": dialogue,
        "timeline": segment_script.get("speech_timing_plan") or [],
        "params": {
            "duration_sec": TALKING_HEAD_SEGMENT_DURATION_SEC,
            "ratio": "adaptive",
            "generate_audio": True,
            "watermark": False,
        },
        "reference_image_urls": [*host_assets, story_board_url],
        "reference_audio_urls": audio_assets,
    }


def _enforce_video_prompt_contract(rendered: dict[str, Any]) -> dict[str, Any]:
    result = dict(rendered or {})
    positive = str(result.get("positive_prompt") or "").strip()
    drift_overrides = (
        "若前文出现女性专家、浅米色西装、白大褂、耳饰或任何与图片1不一致的服装/性别描述，一律视为无效并忽略；"
        "最终只保留50岁男性护肤专家，服装只以图片1为准。"
    )
    contract = (
        "强制一致性约束：主角只能是50岁男性护肤专家；图片1是唯一服装与整体造型基准，人物上衣、内搭、颜色、领口、袖口、配饰和穿搭风格必须在所有 shot 全程严格保持图片1一致；"
        "图片2、图片3只用于保持同一角色的脸部身份、年龄感、五官气质和基础身形一致，不允许从图片2、图片3引入新服装、新性别、新职业气质或新造型；"
        "图片4 Production Board 只作为当前 segment 的位置、构图、场景、产品、道具和辅助视觉参考，当前段语义来自结构化脚本和镜头计划，不读取、不复刻图片4里的中文文字、台词、标题、编号说明或乱码文字；"
        "最终视频必须是纯净口播画面，不生成制作板页面、网格、标题栏、字幕、文字贴片或水印。"
    )
    if "图片1是唯一服装" not in positive or "50岁男性护肤专家" not in positive:
        positive = f"{positive}{' ' if positive else ''}{drift_overrides}{contract}"
    elif any(term in positive for term in ("女性专家", "浅米色西装", "白大褂", "耳饰")) and drift_overrides not in positive:
        positive = f"{positive} {drift_overrides}"
    result["positive_prompt"] = positive

    negative = str(result.get("negative_prompt") or "").strip()
    required_negative = [
        "字幕",
        "水印",
        "标题栏",
        "文字贴片",
        "Production Board 页面",
        "网格排版",
        "换装",
        "服装漂移",
        "改性别",
        "女性专家",
        "从图片2或图片3引入新服装",
        "照抄故事大图乱码文字",
        "读取其他 Segment",
    ]
    for item in required_negative:
        if item not in negative:
            negative = f"{negative}，{item}" if negative else item
    result["negative_prompt"] = negative
    return result


class TalkingHeadPromptService:
    """口播故事大图和视频 prompt 编译边界。"""

    def __init__(self) -> None:
        self._renderer = PromptRenderer()

    async def compile_story_overview_board(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        host_reference_assets: list[str],
        reference_audio_assets: list[str],
    ) -> PromptBundle:
        logger = get_project_logger(project_id, module="services.talking_head_prompt")
        spec = await ProjectSpecRepository(session).get_active(project_id)
        brief = await CreativeBriefRepository(session).get_active(project_id)
        style = await StyleBibleRepository(session).get_active(project_id)
        narrative = await NarrativeScriptVersionRepository(session).get_active(project_id)
        if spec is None or brief is None or narrative is None:
            raise ValueError("缺少 active spec/brief/narrative，无法编译口播故事大图 prompt")

        brief_data = _brief_payload(brief)
        narrative_data = narrative.raw_payload or {}
        style_data = getattr(style, "raw_payload", None) or {}
        host_reference_urls = await self._resolve_story_board_reference_image_urls(
            project_id,
            fallback_references=host_reference_assets,
        )
        reference_audio_urls = _clean_reference_list(reference_audio_assets)
        rendered = _build_story_overview_board_prompt(
            spec=spec,
            brief_payload=brief_data,
            style_payload=style_data,
            narrative_payload=narrative_data,
            host_assets=host_reference_urls,
            audio_assets=reference_audio_assets,
        )

        registry = get_provider_registry()
        provider_profile = registry.get_default("image")
        provider_name = provider_profile.name if provider_profile else "gpt_image_2"
        image_params = dict(rendered.get("image_params") or {})
        image_params.update(
            {
                "aspect_ratio": TALKING_HEAD_STORY_BOARD_ASPECT_RATIO,
                "size": TALKING_HEAD_STORY_BOARD_IMAGE_SIZE,
                "resolution": TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
                "orientation": "landscape",
                "board_type": TALKING_HEAD_LAYOUT,
                "storyboard_layout": TALKING_HEAD_LAYOUT,
                "layout_reading_map": rendered.get("layout_reading_map") or {},
            }
        )
        bundle = PromptBundle(
            bundle_id=generate_ulid(),
            target_type="talking_head_story_overview_board",
            target_id="story_overview_board",
            provider=provider_name,
            positive_prompt=str(rendered.get("image_positive_prompt") or ""),
            negative_prompt=rendered.get("image_negative_prompt"),
            reference_asset_ids=list(host_reference_assets),
            reference_image_urls=list(host_reference_urls[:3]),
            reference_weight=0.75,
            params=image_params,
            source_brief_version_id=brief.id,
            source_style_version_id=style.id if style else None,
        )
        await self._persist_bundle(session, project_id, bundle)
        LocalArtifactStore(project_id).write_json(
            ArtifactStage.PROMPT_BUNDLES,
            "bundle_story_overview_board",
            {
                "bundle_id": bundle.bundle_id,
                "target_type": bundle.target_type,
                "provider": bundle.provider,
                "positive_prompt": bundle.positive_prompt,
                "negative_prompt": bundle.negative_prompt,
                "params": bundle.params,
                "reference_image_urls": bundle.reference_image_urls,
                "reference_asset_ids": bundle.reference_asset_ids,
                "resolved_reference_audio_urls": reference_audio_urls,
            },
        )
        return bundle

    async def _resolve_story_board_reference_image_urls(
        self,
        project_id: str,
        *,
        fallback_references: list[str],
    ) -> list[str]:
        cfg = get_config().talking_head
        ref_dir = Path(cfg.story_board_reference_image_dir)
        if not ref_dir.is_absolute():
            ref_dir = _project_root() / ref_dir
        image_paths: list[Path] = []
        if ref_dir.exists():
            for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                image_paths.extend(sorted(ref_dir.glob(pattern)))
        if not image_paths:
            return _clean_reference_list(fallback_references)

        storage = get_storage()
        urls: list[str] = []
        for path in image_paths[:3]:
            suffix = path.suffix.lower() or ".png"
            content_type = mimetypes.guess_type(path.name)[0] or "image/png"
            key = f"projects/{project_id}/assets/talking_head_reference/{path.stem}{suffix}"
            await storage.async_upload_file(key, path, content_type=content_type)
            urls.append(storage.get_presigned_url(key, expiry_seconds=6 * 60 * 60))
        return urls

    async def compile_talking_head_video(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        shot: Any,
        story_board_url: str,
        layout_reading_map: dict[str, Any],
        host_reference_assets: list[str],
        reference_audio_assets: list[str],
    ) -> PromptBundle:
        logger = get_project_logger(project_id, module="services.talking_head_prompt")
        spec = await ProjectSpecRepository(session).get_active(project_id)
        brief = await CreativeBriefRepository(session).get_active(project_id)
        narrative = await NarrativeScriptVersionRepository(session).get_active(project_id)
        if spec is None or brief is None:
            raise ValueError("缺少 active spec/brief，无法编译口播视频 prompt")
        narrative_payload = narrative.raw_payload if narrative is not None else {}
        segment_scripts = narrative_payload.get("shots") or []
        shot_index = int(getattr(shot, "shot_index", 0) or 0)
        host_reference_urls = _clean_reference_list(host_reference_assets)
        reference_audio_urls = _clean_reference_list(reference_audio_assets)
        segment_script = next(
            (item for item in segment_scripts if int(item.get("shot_index", -1)) == shot_index),
            segment_scripts[shot_index] if shot_index < len(segment_scripts) else {},
        )
        rendered = await self._call_llm(
            template_name="compile_talking_head_video_prompt",
            variables={
                "project_spec_json": _json_text({"user_prompt": spec.user_prompt, "output_config": spec.output_config}),
                "talking_head_brief_json": _json_text(_brief_payload(brief)),
                "segment_script_json": _json_text(segment_script),
                "story_board_url": story_board_url,
                "shot_index": shot_index + 1,
                "segment_time_range": segment_time_range(shot_index),
                "layout_reading_map_json": _json_text(layout_reading_map),
                "host_reference_assets_json": _json_text(host_reference_assets),
                "reference_audio_assets_json": _json_text(reference_audio_assets),
            },
            logger=logger,
        )
        if not rendered.get("positive_prompt"):
            rendered = _fallback_video_prompt(
                shot=shot,
                segment_script=segment_script,
                story_board_url=story_board_url,
                host_assets=host_reference_assets,
                audio_assets=reference_audio_assets,
                layout_reading_map=layout_reading_map,
            )
        rendered = _enforce_video_prompt_contract(rendered)
        registry = get_provider_registry()
        duration_sec = round((getattr(shot, "duration_ms", 0) or 15000) / 1000, 1)
        provider_profile = registry.select_for_duration("video", duration_sec)
        provider_name = provider_profile.name if provider_profile else "seedance_2"
        params = dict(rendered.get("params") or {})
        params.update(
            {
                "duration_sec": TALKING_HEAD_SEGMENT_DURATION_SEC,
                "ratio": (spec.output_config or {}).get("aspect_ratio", "9:16"),
                "resolution": (spec.output_config or {}).get("video_resolution", "1080p"),
                "generate_audio": True,
                "reference_image_urls": [*host_reference_urls, story_board_url],
                "reference_audio_urls": list(reference_audio_urls),
                "board_segment_reading_instruction": rendered.get("board_segment_reading_instruction"),
                "storyboard_layout": TALKING_HEAD_LAYOUT,
            }
        )
        bundle = PromptBundle(
            bundle_id=generate_ulid(),
            target_type="shot_clip",
            target_id=shot.id,
            provider=provider_name,
            positive_prompt=str(rendered.get("positive_prompt") or ""),
            negative_prompt=rendered.get("negative_prompt"),
            reference_asset_ids=list(host_reference_assets) + list(reference_audio_assets),
            reference_image_url=host_reference_urls[0] if host_reference_urls else None,
            reference_image_urls=[*host_reference_urls, story_board_url],
            reference_audio_urls=list(reference_audio_urls),
            params=params,
            source_brief_version_id=brief.id,
        )
        await self._persist_bundle(session, project_id, bundle)
        LocalArtifactStore(project_id).write_json(
            ArtifactStage.PROMPT_BUNDLES,
            f"bundle_talking_head_shot_{shot_index + 1:03d}",
            {
                "bundle_id": bundle.bundle_id,
                "shot_id": shot.id,
                "shot_index": shot_index,
                "target_type": bundle.target_type,
                "provider": bundle.provider,
                "positive_prompt": bundle.positive_prompt,
                "negative_prompt": bundle.negative_prompt,
                "params": bundle.params,
                "reference_image_urls": bundle.reference_image_urls,
                "reference_audio_urls": bundle.reference_audio_urls,
                "reference_asset_ids": bundle.reference_asset_ids,
            },
        )
        return bundle

    async def _call_llm(
        self,
        *,
        template_name: str,
        variables: dict[str, Any],
        logger: Any,
    ) -> dict[str, Any]:
        cfg = get_config().llm
        if not cfg.api_key:
            return {}
        try:
            prompt_text = self._renderer.render(template_name, variables=variables)
            llm = ChatOpenAI(
                model=cfg.model,
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                timeout=cfg.timeout,
            )
            response = await llm.ainvoke(prompt_text)
            raw_text = response.content if hasattr(response, "content") else str(response)
            parsed = safe_parse_json(str(raw_text))
            return parsed if isinstance(parsed, dict) else {}
        except Exception as exc:
            logger.warning(
                f"口播 prompt LLM 编译失败，使用规则兜底: {exc!r}",
                event_type="talking_head_prompt_llm_failed",
            )
            return {}

    @staticmethod
    async def _persist_bundle(
        session: AsyncSession,
        project_id: str,
        bundle: PromptBundle,
    ) -> None:
        orm = PromptBundleModel(
            id=bundle.bundle_id,
            project_id=project_id,
            target_type=bundle.target_type,
            target_id=bundle.target_id,
            provider=bundle.provider,
            positive_prompt=bundle.positive_prompt,
            negative_prompt=bundle.negative_prompt,
            params=bundle.params,
            source_brief_version_id=bundle.source_brief_version_id,
            source_style_version_id=bundle.source_style_version_id,
            source_shot_plan_version_id=bundle.source_shot_plan_version_id,
            reference_image_url=bundle.reference_image_url,
            reference_asset_ids=bundle.reference_asset_ids,
        )
        await PromptBundleRepository(session).add(orm)
        await session.flush()
