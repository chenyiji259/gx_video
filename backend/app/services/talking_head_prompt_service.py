"""口播导演分镜图 prompt 编译辅助。"""
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
from app.repositories.asset_repository import AssetRepository
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
from app.services.asset_access_service import build_asset_access_url
from app.utils.ids import generate_ulid
from app.utils.json_utils import safe_parse_json

PERSON_REFERENCE_STEMS = ("r1", "r2", "r3")
SCENE_REFERENCE_STEM = "d1"
IMAGE_REFERENCE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
FACE_OCCLUSION_RULE = (
    "人物脸部必须做成遮挡式无五官脸：用浅色空白面罩、柔和纯色脸部轮廓或无五官遮挡层覆盖眼睛、鼻子、嘴巴和真实皮肤细节；"
    "只保留发型轮廓、眼镜外轮廓、头部比例、脖颈肩线、身形、服装、手势、坐姿和整体气质。"
    "不要复刻上传参考图本人的真实五官、真实脸型细节或可识别面部纹理。"
)


def _no_visible_text_contract() -> str:
    return (
        "无字幕硬约束：最终视频画面必须是纯净无字画面；台词只能通过人物声音、口型和表演传达，"
        "不得以任何可见文字形式出现在画面中。"
        "禁止生成字幕、双语字幕、歌词、旁白字幕、下三分之一标题、解释说明、按钮文案、弹幕、CTA文字、"
        "成分卡文字、产品卖点文字、编号、时间码、标签、贴纸文字、UI文字、提示牌、白板字、屏幕字、"
        "海报字、瓶身可读小字、包装可读文字或任何文字贴片。"
        "如果参考图、导演分镜图、产品图或脚本中出现文字，只能理解其语义，不得复刻字形、排版、行列、乱码或文本块。"
        "产品瓶身和道具只能作为不可读的视觉符号，成分卡和屏幕也只能作为抽象图标，不能承载可读文字。"
        "合格标准：任意一帧里都不能出现中文、英文、数字、乱码、假字或类似字幕的文本痕迹；"
        "画面中绝对不要出现任何可读文字；只要出现任何文字痕迹，本次视频视为失败，需要重新生成。"
    )


def _required_no_text_negative_terms() -> list[str]:
    return [
        "字幕",
        "双语字幕",
        "歌词字幕",
        "旁白字幕",
        "水印",
        "标题栏",
        "文字贴片",
        "下三分之一标题",
        "按钮文案",
        "弹幕",
        "CTA文字",
        "成分卡文字",
        "产品卖点文字",
        "可读文字",
        "中文文字",
        "英文文字",
        "数字编号",
        "时间码",
        "乱码文字",
        "假字",
        "UI文字",
        "屏幕字",
        "白板字",
        "海报字",
        "瓶身可读小字",
        "包装可读文字",
        "Production Board 页面",
        "导演分镜图页面",
        "网格排版",
        "故事板卡片",
        "换装",
        "服装漂移",
        "改性别",
        "从图片2或图片3引入新服装",
        "照抄导演分镜图乱码文字",
        "读取其他 Segment",
        "背景音乐",
        "BGM",
        "环境声",
        "场景音",
        "音效",
        "掌声",
        "转场音",
    ]


def _required_no_text_negative_prompt() -> str:
    return "，".join(_required_no_text_negative_terms())


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


def _video_host_reference_urls(host_reference_assets: list[str]) -> list[str]:
    return _clean_reference_list(host_reference_assets)[:3]


def _story_overview_board_reference_urls(
    *,
    host_reference_urls: list[str],
    scene_reference_url: str | None,
    product_refs: list[dict[str, str]],
) -> list[str]:
    urls: list[str] = []
    for url in [*host_reference_urls[:3], scene_reference_url, *[ref["url"] for ref in product_refs]]:
        if url and url not in urls:
            urls.append(url)
    return urls


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_path_from_project_root(path_text: str | Path) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = _project_root() / path
    return path


def _find_named_image(directory: Path, stem: str) -> Path | None:
    for suffix in IMAGE_REFERENCE_SUFFIXES:
        candidate = directory / f"{stem}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _ordered_person_reference_paths(ref_dir: Path) -> list[Path]:
    ordered = [
        path
        for stem in PERSON_REFERENCE_STEMS
        if (path := _find_named_image(ref_dir, stem)) is not None
    ]
    if ordered:
        return ordered[:3]

    image_paths: list[Path] = []
    for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        image_paths.extend(sorted(ref_dir.glob(pattern)))
    return [
        path
        for path in image_paths
        if path.stem.lower() != SCENE_REFERENCE_STEM
    ][:3]


def _default_scene_reference_path(ref_dir: Path) -> Path | None:
    return _find_named_image(ref_dir, SCENE_REFERENCE_STEM)


async def _upload_local_reference_image(
    *,
    project_id: str,
    path: Path,
    asset_dir: str,
) -> str:
    suffix = path.suffix.lower() or ".png"
    content_type = mimetypes.guess_type(path.name)[0] or "image/png"
    key = f"projects/{project_id}/assets/{asset_dir}/{path.stem}{suffix}"
    storage = get_storage()
    await storage.async_upload_file(key, path, content_type=content_type)
    return storage.get_presigned_url(key, expiry_seconds=6 * 60 * 60)


def _story_board_topic(*, spec: Any, brief_payload: dict[str, Any]) -> str:
    ext = brief_payload.get("extension") or {}
    return (
        ext.get("topic")
        or brief_payload.get("title")
        or brief_payload.get("project_title")
        or getattr(spec, "user_prompt", "")
        or "中文口播科普视频"
    )


def _product_reference_asset_ids(spec: Any | None) -> list[str]:
    output_config = getattr(spec, "output_config", None) or {}
    raw_ids = output_config.get("product_reference_asset_ids") or []
    if not isinstance(raw_ids, list):
        return []
    ids: list[str] = []
    for item in raw_ids:
        text = str(item or "").strip()
        if text and text not in ids:
            ids.append(text)
        if len(ids) >= 3:
            break
    return ids


async def _resolve_product_reference_urls(
    session: AsyncSession,
    project_id: str,
    spec: Any | None,
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    repo = AssetRepository(session)
    for asset_id in _product_reference_asset_ids(spec):
        asset = await repo.get_by_id_for_project(asset_id, project_id)
        url = await build_asset_access_url(asset)
        if url:
            refs.append({"asset_id": asset_id, "url": url})
    return refs


def _product_reference_text(product_refs: list[dict[str, str]], *, start_index: int) -> str:
    if not product_refs:
        return "（未上传产品图，产品仅按剧本和创意描述进行抽象展示）"
    lines = []
    for offset, _ref in enumerate(product_refs):
        image_no = start_index + offset
        lines.append(
            f"图片{image_no}是用户上传的产品图。"
            "它是本次要讲解/展示的真实产品外观参考，只能作为产品瓶身、包装、材质、颜色和形态参考，"
            "不要当作人物、场景或导演分镜图。"
        )
    return "\n".join(lines)


def _product_reference_prompt_items(product_refs: list[dict[str, str]], *, start_index: int) -> list[dict[str, Any]]:
    return [
        {
            "image_no": start_index + offset,
            "role": "product_reference",
            "description": "用户上传产品图，只用于锁定产品瓶身、包装、材质、颜色和形态，不是人物图、场地图或导演分镜图。",
        }
        for offset, _ref in enumerate(product_refs)
    ]


def _host_reference_prompt_items(count: int) -> list[dict[str, Any]]:
    descriptions = [
        "唯一服装与整体造型基准，锁定上衣、内搭、颜色、领口、袖口、配饰和穿搭风格。",
        "同一角色身份补充参考，只锁定脸部身份、年龄感、五官气质和基础身形，不引入新服装。",
        "同一角色身份补充参考，只锁定脸部身份、年龄感、五官气质和基础身形，不引入新性别、新职业气质或新造型。",
    ]
    return [
        {
            "image_no": idx + 1,
            "role": "person_reference",
            "description": descriptions[idx] if idx < len(descriptions) else "同一角色人物参考，不代表新增人物。",
        }
        for idx in range(min(count, 3))
    ]


def _audio_reference_prompt_items(count: int) -> list[dict[str, Any]]:
    return [
        {
            "audio_no": idx + 1,
            "role": "voice_reference",
            "description": "只参考说话人声的音色、声线质感、年龄感、口音和说话气质，不承载对白内容，不代表背景音乐、环境声、场景音或音效。",
        }
        for idx in range(count)
    ]


def _story_overview_board_reference_text(product_count: int) -> str:
    product_lines = "\n".join(
        f"- 图片{5 + idx}：产品参考图，用于锁定用户上传产品的瓶身、包装、材质、颜色和形态。"
        for idx in range(product_count)
    )
    if not product_lines:
        product_lines = "- 未上传产品图：产品仅按剧本和创意描述抽象展示。"
    return "\n".join(
        [
            "参考图职责说明：",
            "- 图片1、图片2、图片3：人物参考图，只用于锁定同一位主持人的年龄感、气质、基础身形、发型轮廓、眼镜外轮廓、头身比例、服装基准和姿态，不代表三位不同人物，也不用于复刻可识别真人脸。",
            "- 图片4：场地参考图，只用于锁定统一空间环境、桌面布局、背景材质、光线和氛围，不是人物图或产品图。",
            product_lines,
        ]
    )


def _story_overview_scene_lock_text(*, has_scene_reference: bool, fallback_scene: str) -> str:
    if has_scene_reference:
        return (
            "以图片4场地参考图为准。图片4只用于锁定统一空间环境、桌面布局、背景材质、"
            "光线方向和整体氛围，不是人物图或产品图；不要用文字场景设定覆盖图片4里的真实空间。"
        )
    return fallback_scene


def _story_overview_segment_scene_text(
    *,
    has_scene_reference: bool,
    fallback_scene: str,
    segment: dict[str, Any],
) -> str:
    if has_scene_reference:
        return (
            "沿用图片4场地参考图锁定的统一空间环境、桌面布局、背景材质、光线和氛围，"
            "只根据本段动作、产品露出和辅助图示做局部调度，不额外改换场景。"
        )
    return segment.get("scene_description") or fallback_scene


def _story_overview_scene_summary_text(*, has_scene_reference: bool) -> str:
    if has_scene_reference:
        return "场景：以图片4场地参考图为准；色彩基调：沿用图片4的背景材质、光线和氛围，产品与辅助图示只做局部补充。"
    return "场景：护肤科普工作室；色彩基调：暖灰、柔米、洁白、浅琥珀、科学蓝点缀。"


def _segment_reading_instruction(index: int) -> str:
    time_range = segment_time_range(index)
    return (
        f"只读取导演分镜图中第 {index + 1} 行 / {time_range} 的画面内容参考、景别、运镜方式和动作节奏，"
        "不要复刻表格标题、编号、分栏、注释或任何可读文字。"
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
    scene_asset_url: str | None = None,
    product_refs: list[dict[str, str]] | None = None,
    product_start_index: int = 5,
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
        or "知识口播，专业、亲和、干净护肤科普，纯净无字幕画面"
    )
    audience = output_config.get("target_audience") or "目标用户"
    platform = output_config.get("platform") or "短视频平台"
    host_lock = (
        "参考上传人物的整体气质、身形、服装和姿态。主角是一位成熟、理性、专业的男性知识型科普讲师，"
        "保留短黑发轮廓、黑框眼镜轮廓、灰色衬衫、白色内搭、冷静可信的讲解气质。"
        f"{FACE_OCCLUSION_RULE}"
    )
    fallback_scene_lock = (
        brief_payload.get("set_design_profile")
        or (style_payload.get("visual_style", {}) if isinstance(style_payload.get("visual_style"), dict) else {}).get("environment")
        or "现代护肤科普工作室。暖灰色或浅米色背景，柔和暖白光，桌面有护肤品包装、成分卡片、简洁分子结构图和皮肤屏障示意卡。"
    )
    has_scene_reference = bool(scene_asset_url)
    scene_lock = _story_overview_scene_lock_text(
        has_scene_reference=has_scene_reference,
        fallback_scene=fallback_scene_lock,
    )
    scene_summary = _story_overview_scene_summary_text(has_scene_reference=has_scene_reference)
    product_refs = product_refs or []
    product_text = _product_reference_text(product_refs, start_index=product_start_index)
    reference_text = _story_overview_board_reference_text(len(product_refs))
    segment_blocks: list[str] = []
    reading_map: dict[str, str] = {}
    for idx, segment in enumerate(segments):
        time_range = segment_time_range(idx)
        title = _segment_title(segment, idx, topic)
        goal = _segment_goal(segment, topic)
        dialogue_parts = _split_dialogue(_segment_dialogue(segment))
        scene = _story_overview_segment_scene_text(
            has_scene_reference=has_scene_reference,
            fallback_scene=fallback_scene_lock,
            segment=segment,
        )
        action = segment.get("action_description") or "占位主角面对镜头自然讲解，配合克制手势和产品/图示插入镜头。"
        camera = segment.get("camera_language") or "固定中近景，重点处轻微 push-in"
        reading_map[f"segment_{idx + 1}"] = _segment_reading_instruction(idx)
        segment_blocks.append(
            "\n".join([
                f"镜头{idx + 1} / {time_range}",
                f"标题：{title}",
                f"本段目标：{goal}",
                f"画面内容参考图：{scene}",
                f"运镜方式：{camera}",
                f"画面调度 / 动作：{action}",
                f"声音 / 台词摘要：{dialogue_parts[0]}；{dialogue_parts[1]}；{dialogue_parts[2]}；{dialogue_parts[3]}",
                "备注：同一位遮挡式无五官占位主持人，保持服装、发型轮廓、眼镜外轮廓、头身比例、身形、场景、桌面、灯光和产品一致；不要生成任何可读文字。",
            ])
        )
    positive = f"""
请基于上传人物参考图，创建一张“{target_duration}秒中文口播科普视频导演分镜流程图 / Director Shot List”。

重要规则：
这张图用于后续视频模型测试。图中的人物只允许作为“遮挡式无五官占位主持人”出现，不要绘制可识别真人脸。人物必须保留上传参考图带来的身体轮廓、头身比例、发型轮廓、灰色衬衫、白色内搭、黑框眼镜外轮廓、手势、坐姿和服装风格；脸部必须被浅色空白面罩、柔和纯色脸部轮廓或无五官遮挡层覆盖，效果类似人脸被完整遮挡但人物轮廓仍然清楚。不要生成真实眼睛、鼻子、嘴巴、皮肤细节或可识别面部纹理。真正的人脸身份后续会由视频生成请求中的授权人像素材提供。

图内所有可见文字默认使用中文。除了必要专业镜头词汇如 push-in、close-up、macro、Seedance，其余标题、分区名、台词、说明、约束都必须用中文。

项目主题：
《{topic}》

视频类型：
单人固定主角中文科普口播视频，面向{audience}，发布平台：{platform}。风格：{style_text}。

固定主角占位规则：
{host_lock}

统一场景：
{scene_lock}

{reference_text}

用户上传产品图职责：
{product_text}
生图时必须把这些图片理解为本次视频要介绍的产品，结合创意方向、SegmentScript 和台词安排产品展示、产品 close-up、桌面摆放和不可读瓶身轮廓。产品图可以不出现于每个格子，但出现时必须保持产品外观一致，不要变成随机护肤瓶或普通道具。

画面规格：
横向超宽 21:9，4K，导演分镜流程表风格，信息清晰但尽量克制，按时间顺序排布每个 15 秒段落。

顶部摘要栏只保留以下信息：项目标题：{topic}；视频形式：单人中文科普口播；内容类型：护肤成分科普；总时长：{target_duration}秒；结构：{expected_segments}个段落，每段15秒；主角：同一位遮挡式无五官男性讲师占位；{scene_summary}

主表格按行展示 {expected_segments} 个 15 秒段落，每行都要有清楚的边界，但不要做成海报式策划板。
每行建议包含以下列：镜头号、时间、景别、画面内容参考图、运镜方式、画面调度 / 动作、声音 / 台词摘要、备注。
画面内容参考图必须是该行最大的视觉区域，文字只做最少必要说明，不要堆叠额外说明卡、底部大段注释或侧边复杂分区。

{chr(10).join(segment_blocks)}

底部摘要只保留三类短信息：灯光 / 氛围 / 风格注释；人声 / 说话音锁定；摄影语言注释。
灯光 / 氛围 / 风格注释：柔和主光、暖色背景灯、干净护肤质感、舒适对比。关键词：专业、冷静、可信、干净、温暖、成熟男性讲师。
人声 / 说话音锁定：只保留成熟中文男性说话人声，冷静、清晰、专业、亲和。语速中等，有自然停顿，不夸张推销。不要背景音乐、不要环境声、不要场景音、不要音效，人声之外不需要任何声音。
摄影语言注释：35mm 用于主角中近景，50mm 用于讲解 close-up，85mm macro 用于产品和成分卡片。运镜风格以固定和轻微 push-in 为主，保持干净、利落、适合视频提取。

全局一致性要求：
所有段落里的身体、服装、发型轮廓、眼镜外轮廓、头身比例、身形、场景、桌面、灯光、产品摆放、色彩和摄影语言必须保持统一。每个段落只改变台词重点、手势、辅助图示和产品特写角度。所有人物脸部必须是遮挡式无五官脸，不可识别真人脸。不要生成页面式信息图，不要生成夸张大标题海报，不要生成密集小字矩阵。

禁止：
不要生成真实可识别真人脸，不要画眼睛鼻子嘴巴，不要画真实面部纹理，不要让脸像上传参考图本人。不要生成有五官的脸、清晰真人脸、半透明真实脸、真实皮肤细节或可识别人脸。不要生成最终视频画面，不要把不同段落混在同一个格子里。不要生成多个不同男人，不要生成女性主持人，不要生成医生白大褂，不要生成夸张网红直播间，不要生成杂乱背景，不要水印，不要品牌logo，不要低质量排版，不要生成可读字幕或长段文字。
""".strip()
    return {
        "image_positive_prompt": positive,
        "image_negative_prompt": "真实清晰的人脸五官, 有五官的脸, 清晰真人脸, 真实眼睛, 真实鼻子, 真实嘴巴, 真实皮肤细节, 真实面部纹理, 可识别真人脸, 上传参考图本人脸, 脸部无遮挡, 女性主持人, 多个不同主持人, 医生白大褂, 直播间, 综艺棚, 英文大段文字, 字幕条, 水印, 品牌Logo, 医疗功效承诺文字, 杂乱背景, 低质量排版, 低分辨率, 最终成片画面, 可读字幕, 长段文字",
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
            "product_reference_asset_ids": [ref["asset_id"] for ref in product_refs],
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
        "生成一张 21:9 中文导演分镜流程图，覆盖完整视频，"
        "内部按时间顺序清晰分成对应数量的 15 秒镜头行。"
        "画面以当前镜头内容参考图为主，配合时间、景别、运镜方式、动作节奏和声音 / 台词摘要。可见文字使用中文。"
        f"主题：{topic}。"
        f"Segments：{'；'.join(segment_lines)}。"
        "固定人物参考资产只锁定脸部身份、年龄感、气质和基础身形，不锁死服装；"
        "服装与道具以导演分镜图当前镜头行设计为主。"
        "导演分镜图中的主持人面部需要遮住或弱化真实五官，只保留发型、眼镜轮廓、头部比例、"
        "身体姿态、服装、场景、动作和道具信息，避免生成可识别真人脸。"
    )
    return {
        "image_positive_prompt": positive,
        "image_negative_prompt": "英文大段文字，字幕条，水印，真实品牌 logo，医疗功效承诺，多位主持人，混乱网格，低清晰度，Production Board 页面，海报式策划板",
        "image_params": {
            "aspect_ratio": TALKING_HEAD_STORY_BOARD_ASPECT_RATIO,
            "size": TALKING_HEAD_STORY_BOARD_IMAGE_SIZE,
            "resolution": TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
            "orientation": "landscape",
            "board_type": TALKING_HEAD_LAYOUT,
        },
        "layout_reading_map": {
            f"segment_{idx + 1}": _segment_reading_instruction(idx)
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
    product_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    index = int(getattr(shot, "shot_index", 0) or 0)
    segment_key = f"segment_{index + 1}"
    instruction = str(
        layout_reading_map.get(segment_key)
        or _segment_reading_instruction(index)
    )
    dialogue = (
        segment_script.get("dialogue")
        or segment_script.get("voiceover_script")
        or getattr(shot, "dialogue", "")
        or ""
    )
    goal = segment_script.get("segment_goal") or segment_script.get("action_description") or "围绕本段主题进行护肤科普讲解"
    product_refs = product_refs or []
    shot_reference_url = story_board_url
    product_text = _product_reference_text(product_refs, start_index=5)
    no_visible_text_rule = _no_visible_text_contract()
    positive = f"""
生成一个 15 秒中文单人护肤科普口播视频。

你会收到有序参考图片和参考音频：
图片1、图片2、图片3是同一位光希老王的固定角色资产，不是三位不同角色。图片1是唯一服装与整体造型基准，人物上衣、内搭、颜色、领口、袖口、配饰和穿搭风格必须全程严格保持图片1一致。图片2、图片3只用于补充锁定同一角色的脸部身份、年龄感、五官气质和基础身形，不允许从图片2、图片3引入新服装、新性别、新职业气质或新的造型风格。
图片4是完整导演分镜图，只用于读取当前 Segment 的位置、构图、场景、桌面产品、道具、动作节奏和光线氛围；不要复刻它的表格页面、标题栏、编号、台词、说明栏、镜头参数、字幕或任何可读文字。
{product_text}
产品图必须作为本段介绍/展示的真实产品外观参考，结合创意和剧本说明产品如何出现在桌面、手边或产品 close-up 中；不要只依赖导演分镜图里的泛化道具。
音频1、音频2、音频3只用于参考说话人声的音色、声线质感、年龄感、口音和说话气质，不承载对白内容，不照搬原音频内容、节奏或停顿；它们不是背景音乐、环境声、场景音或音效参考。

本次只生成 Segment {index + 1} / {segment_time_range(index)}。当前段语义来自结构化脚本和镜头计划，不依赖图片4 OCR。
图片4读取范围：{instruction}。这条信息只用于从大图中定位当前段落，不允许把原始导演分镜图的文字、编号、分栏或排版带回最终视频。
本段目标：{goal}。
对白只用于驱动人物口型和人声，不是画面元素，不得以字幕、提词器、标题条、说明卡、气泡文字或任何可读文字形式出现在画面中。对白参考：「{dialogue or '本段可包含开场动画、产品特写、自然停顿或少量无对白片段'}」
{no_visible_text_rule}
声音硬约束：最终视频只需要中文说话人声，不要背景音乐、不要环境声、不要场景音、不要音效、不要掌声、不要转场音，人声之外不需要别的声音。

分时间段生成真实口播和动作：
0-3 秒：中近景，光希老王保持图片1服装和整体造型，面对镜头平静建立本段主题，口型和台词自然同步。
3-7 秒：轻微 push-in，主角抬手做克制讲解手势，语气专业亲和，桌面护肤品和辅助概念视觉保持在画面边缘。
7-11 秒：切到产品、成分卡片或皮肤/分子示意的 close-up / macro，画面只呈现干净道具和视觉符号，不出现可读小字或字幕。
11-15 秒：回到主角中近景，主角看向镜头总结，表情可信、动作稳定，延续同一服装、同一人物、同一工作室灯光。

不要生成导演分镜图页面，不要生成网格排版，不要生成顶部标题栏，不要生成分区说明文字，不要生成故事板卡片，不要生成任何可见字幕或文字贴片。不要换脸，不要换发型，不要换眼镜，不要换服装，不要改变性别，不要出现第二个人，不要跳到新场景，不要读取其他 Segment 的故事内容。
""".strip()
    return {
        "positive_prompt": positive,
        "negative_prompt": _required_no_text_negative_prompt(),
        "board_segment_reading_instruction": instruction,
        "dialogue_script": dialogue,
        "timeline": segment_script.get("speech_timing_plan") or [],
        "params": {
            "duration_sec": TALKING_HEAD_SEGMENT_DURATION_SEC,
            "ratio": "adaptive",
            "generate_audio": True,
            "watermark": False,
        },
        "reference_image_urls": [*host_assets, shot_reference_url, *[ref["url"] for ref in product_refs]],
        "reference_audio_urls": audio_assets,
    }


def _enforce_video_prompt_contract(rendered: dict[str, Any]) -> dict[str, Any]:
    result = dict(rendered or {})
    positive = str(result.get("positive_prompt") or "").strip()
    drift_overrides = (
        "若前文出现浅米色西装、白大褂、耳饰或任何与图片1不一致的服装/性别描述，一律视为无效并忽略；"
        "最终只保留光希老王，服装只以图片1为准。"
    )
    no_visible_text_contract = _no_visible_text_contract()
    voice_only_contract = (
        "声音硬约束：最终视频只需要中文说话人声；音频参考只用于说话音色和声线，不要背景音乐、不要环境声、不要场景音、不要音效、不要掌声、不要转场音，人声之外不需要任何声音。"
    )
    contract = (
        "强制一致性约束：主角只能是光希老王；图片1是唯一服装与整体造型基准，人物上衣、内搭、颜色、领口、袖口、配饰和穿搭风格必须在所有 shot 全程严格保持图片1一致；"
        "图片2、图片3只用于保持同一角色的脸部身份、年龄感、五官气质和基础身形一致，不允许从图片2、图片3引入新服装、新性别、新职业气质或新造型；"
        "图片4是完整导演分镜图，只用于读取当前 segment 的真实视频场景、构图、产品、道具和辅助视觉参考；不要复刻它的表格页面、标题栏、编号、台词、说明栏、镜头参数、字幕或任何可读文字；当前段语义来自结构化脚本和镜头计划；"
        "最终视频必须是纯净口播画面，不生成制作板页面、网格、标题栏、字幕、文字贴片或水印。"
    )
    if "图片1是唯一服装" not in positive or "光希老王" not in positive:
        positive = f"{positive}{' ' if positive else ''}{drift_overrides}{contract}"
    elif any(term in positive for term in ("浅米色西装", "白大褂", "耳饰")) and drift_overrides not in positive:
        positive = f"{positive} {drift_overrides}"
    if "无字幕硬约束" not in positive:
        positive = f"{positive}{' ' if positive else ''}{no_visible_text_contract}"
    if "声音硬约束" not in positive:
        positive = f"{positive}{' ' if positive else ''}{voice_only_contract}"
    result["positive_prompt"] = positive

    negative = str(result.get("negative_prompt") or "").strip()
    required_negative = _required_no_text_negative_terms()
    for item in required_negative:
        if item not in negative:
            negative = f"{negative}，{item}" if negative else item
    result["negative_prompt"] = negative
    return result


def _append_product_contract(rendered: dict[str, Any], product_refs: list[dict[str, str]]) -> dict[str, Any]:
    if not product_refs:
        return rendered
    result = dict(rendered or {})
    positive = str(result.get("positive_prompt") or "").strip()
    product_contract = (
        "产品参考图硬约束："
        f"{_product_reference_text(product_refs, start_index=5)}"
        "以上产品图是本次要讲解/展示的真实产品外观参考，必须结合当前 SegmentScript 的创意和台词安排产品露出、桌面摆放或 close-up；"
        "不要把产品图当作人物、场景、导演分镜图或普通随机道具，不要只依赖资产大图里的泛化产品。"
    )
    if "产品参考图硬约束" not in positive:
        positive = f"{positive}{' ' if positive else ''}{product_contract}"
    result["positive_prompt"] = positive
    return result


class TalkingHeadPromptService:
    """口播导演分镜图和视频 prompt 编译边界。"""

    def __init__(self) -> None:
        self._renderer = PromptRenderer()

    async def compile_story_overview_board(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        host_reference_assets: list[str],
        reference_audio_assets: list[str],
        regeneration_prompt_section: str = "",
    ) -> PromptBundle:
        logger = get_project_logger(project_id, module="services.talking_head_prompt")
        spec = await ProjectSpecRepository(session).get_active(project_id)
        brief = await CreativeBriefRepository(session).get_active(project_id)
        style = await StyleBibleRepository(session).get_active(project_id)
        narrative = await NarrativeScriptVersionRepository(session).get_active(project_id)
        if spec is None or brief is None or narrative is None:
            raise ValueError("缺少 active spec/brief/narrative，无法编译口播导演分镜图 prompt")

        brief_data = _brief_payload(brief)
        narrative_data = narrative.raw_payload or {}
        style_data = getattr(style, "raw_payload", None) or {}
        host_reference_urls = await self._resolve_story_board_reference_image_urls(
            project_id,
            fallback_references=host_reference_assets,
        )
        scene_reference_url = await self._resolve_scene_reference_image_url(session, project_id, spec)
        product_refs = await _resolve_product_reference_urls(session, project_id, spec)
        reference_audio_urls = _clean_reference_list(reference_audio_assets)
        rendered = _build_story_overview_board_prompt(
            spec=spec,
            brief_payload=brief_data,
            style_payload=style_data,
            narrative_payload=narrative_data,
            host_assets=host_reference_urls,
            audio_assets=reference_audio_assets,
            scene_asset_url=scene_reference_url,
            product_refs=product_refs,
            product_start_index=5,
        )
        if regeneration_prompt_section:
            rendered["image_positive_prompt"] = (
                f"{rendered.get('image_positive_prompt') or ''}\n\n"
                f"{regeneration_prompt_section}"
            ).strip()

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
                "regeneration_feedback": regeneration_prompt_section or None,
            }
        )
        board_reference_urls = _story_overview_board_reference_urls(
            host_reference_urls=host_reference_urls,
            scene_reference_url=scene_reference_url,
            product_refs=product_refs,
        )

        bundle = PromptBundle(
            bundle_id=generate_ulid(),
            target_type="talking_head_story_overview_board",
            target_id="story_overview_board",
            provider=provider_name,
            positive_prompt=str(rendered.get("image_positive_prompt") or ""),
            negative_prompt=rendered.get("image_negative_prompt"),
            reference_asset_ids=list(host_reference_assets) + [ref["asset_id"] for ref in product_refs],
            reference_image_urls=board_reference_urls,
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
                "scene_reference_url": scene_reference_url,
                "product_reference_urls": [ref["url"] for ref in product_refs],
            },
        )
        return bundle

    async def _resolve_scene_reference_image_url(
        self,
        session: AsyncSession,
        project_id: str,
        spec: Any | None,
    ) -> str | None:
        output_config = getattr(spec, "output_config", None) or {}
        scene_asset_id = str(
            output_config.get("scene_reference_asset_id")
            or output_config.get("scene_reference_image_asset_id")
            or ""
        ).strip()
        if scene_asset_id:
            asset = await AssetRepository(session).get_by_id_for_project(scene_asset_id, project_id)
            if asset:
                url = await build_asset_access_url(asset)
                if url:
                    return url

        cfg = get_config().talking_head
        scene_path = str(
            output_config.get("scene_reference_image_path")
            or output_config.get("story_board_scene_image_path")
            or getattr(cfg, "story_board_scene_image_path", "")
            or ""
        ).strip()
        if scene_path:
            path = _resolve_path_from_project_root(scene_path)
        else:
            ref_dir = _resolve_path_from_project_root(cfg.story_board_reference_image_dir)
            path = _default_scene_reference_path(ref_dir)
        if path is None:
            return None
        if not path.exists():
            return None
        return await _upload_local_reference_image(
            project_id=project_id,
            path=path,
            asset_dir="talking_head_scene_reference",
        )

    async def _resolve_story_board_reference_image_urls(
        self,
        project_id: str,
        *,
        fallback_references: list[str],
    ) -> list[str]:
        cfg = get_config().talking_head
        ref_dir = _resolve_path_from_project_root(cfg.story_board_reference_image_dir)
        image_paths = _ordered_person_reference_paths(ref_dir) if ref_dir.exists() else []
        if not image_paths:
            return _clean_reference_list(fallback_references)

        urls: list[str] = []
        for path in image_paths:
            urls.append(await _upload_local_reference_image(
                project_id=project_id,
                path=path,
                asset_dir="talking_head_reference",
            ))
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
        host_reference_urls = _video_host_reference_urls(host_reference_assets)
        shot_reference_url = story_board_url
        reference_audio_urls = _clean_reference_list(reference_audio_assets)
        product_refs = await _resolve_product_reference_urls(session, project_id, spec)
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
                "host_reference_assets_json": _json_text(
                    _host_reference_prompt_items(len(host_reference_urls))
                ),
                "reference_audio_assets_json": _json_text(
                    _audio_reference_prompt_items(len(reference_audio_assets))
                ),
                "product_reference_assets_json": _json_text(
                    _product_reference_prompt_items(product_refs, start_index=5)
                ),
            },
            logger=logger,
        )
        if not rendered.get("positive_prompt"):
            rendered = _fallback_video_prompt(
                shot=shot,
                segment_script=segment_script,
                story_board_url=story_board_url,
                host_assets=host_reference_urls,
                audio_assets=reference_audio_assets,
                layout_reading_map=layout_reading_map,
                product_refs=product_refs,
            )
        rendered = _enforce_video_prompt_contract(rendered)
        rendered = _append_product_contract(rendered, product_refs)
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
                "reference_image_urls": [*host_reference_urls, shot_reference_url, *[ref["url"] for ref in product_refs]],
                "reference_audio_urls": list(reference_audio_urls),
                "board_segment_reading_instruction": rendered.get("board_segment_reading_instruction"),
                "storyboard_layout": TALKING_HEAD_LAYOUT,
                "source_story_board_url": story_board_url,
            }
        )
        bundle = PromptBundle(
            bundle_id=generate_ulid(),
            target_type="shot_clip",
            target_id=shot.id,
            provider=provider_name,
            positive_prompt=str(rendered.get("positive_prompt") or ""),
            negative_prompt=rendered.get("negative_prompt"),
            reference_asset_ids=list(reference_audio_assets) + [ref["asset_id"] for ref in product_refs],
            reference_image_url=host_reference_urls[0] if host_reference_urls else None,
            reference_image_urls=[*host_reference_urls, shot_reference_url, *[ref["url"] for ref in product_refs]],
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
