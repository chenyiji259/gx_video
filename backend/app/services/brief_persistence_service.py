"""BriefPersistenceService — brief + style 生成与落库。

来源文档：doc 09 任务 9-02

职责：
  1. 读取 active AudioAnalysisVersion（获取摘要和 quality_summary）
  2. 读取 active ProjectSpecVersion（获取 user_prompt / target_duration / aspect_ratio）
  3. 读取 style_direction（从 select_style_direction 决策的 selected_option_id）
  4. 调用 CreativePlanningAgent.generate_brief_and_style()
  5. 落库 creative_brief_versions + style_bible_versions（版本化，append-only）
  6. 更新 projects.active_brief_version_id + active_style_version_id
  7. 写本地 JSON 快照（03_brief/ + 04_style/）
  8. 推进项目状态 → brief_ready
"""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.creative_planning_agent import CreativePlanningAgent
from app.core.logging import get_project_logger
from app.core.config import get_config
from app.core.provider_registry import get_provider_registry
from app.tools.shared.artifact_tools import build_ref_from_asset_latest, read_artifact
from app.domain.states import ProjectStage
from app.models.planning import CreativeBriefVersion, StyleBibleVersion
# from app.repositories.audio_analysis_repository import AudioAnalysisRepository  # 旧流程：已停用
from app.repositories.decision_repository import DecisionRepository
from app.repositories.planning_repositories import (
    CreativeBriefRepository,
    StyleBibleRepository,
)
from app.repositories.project_repository import ProjectRepository
from app.repositories.project_spec_repository import ProjectSpecRepository
from app.repositories.unit_of_work import UnitOfWork
from app.repositories.asset_repository import AssetRepository
from app.services.asset_access_service import build_asset_access_url
from app.services.state_transition_service import state_transition_service
from app.services.regeneration_context_service import regeneration_context_service
from app.services.output_spec_service import (
    is_talking_head_config,
    normalize_output_config,
    plan_talking_head_segments,
    plan_triptych_shots,
)
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.path_planner import ArtifactStage
from app.storage.storage_factory import get_storage


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class BriefGenerationError(Exception):
    """Brief 生成或落库异常。"""

    def __init__(self, message: str, code: str = "brief_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


TALKING_HEAD_HOST_CHARACTER = {
    "character_id": "host_001",
    "name": "光希老王",
    "appearance": "光希老王",
    "personality": "专业、亲和、可信",
}


# ---------------------------------------------------------------------------
# 辅助：quality_summary → 文本摘要
# ---------------------------------------------------------------------------

def _quality_summary_to_text(quality_summary: dict[str, Any]) -> str:
    """将 quality_summary dict 转为给 LLM 的文本摘要。"""
    if not quality_summary:
        return "暂无详细音乐分析结果。"
    parts: list[str] = []

    # 1. 整体风格与情绪（Omni overall_analysis）
    oa = quality_summary.get("overall_analysis") or {}
    if oa.get("genre"):
        parts.append(f"风格分类: {oa['genre']}")
    if oa.get("mood"):
        parts.append(f"整体情绪: {oa['mood']}")
    if oa.get("key_theme"):
        parts.append(f"歌词主题: {oa['key_theme']}")
    if oa.get("structural_pattern"):
        parts.append(f"结构模式: {oa['structural_pattern']}")
    if oa.get("emotional_arc"):
        parts.append(f"情绪弧线: {oa['emotional_arc']}")

    # 2. BPM 和面调（music_structure_summary）
    mss = quality_summary.get("music_structure_summary") or {}
    if mss.get("bpm"):
        parts.append(f"BPM: {mss['bpm']}")
    if mss.get("key_scale"):
        parts.append(f"调式: {mss['key_scale']}")
    if mss.get("time_signature"):
        parts.append(f"拍号: {mss['time_signature']}")
    sections = mss.get("sections") or []
    if sections:
        labels = [s.get("label") or s.get("type", "") for s in sections]
        parts.append(f"段落结构: {' → '.join(l for l in labels if l)}")
        # 带上每段时间范围
        time_ranges = [
            f"{s.get('label') or s.get('type', '?')}({s.get('start', '?')}-{s.get('end', '?')}s)"
            for s in sections if s.get("start") is not None
        ]
        if time_ranges:
            parts.append(f"段落时间轴: {', '.join(time_ranges)}")

    # 3. 剪辑建议（新格式 per_section）
    eg = quality_summary.get("editing_guidance") or {}
    per_section = eg.get("per_section") or []
    if per_section:
        hints = [
            f"{p.get('section', '?')}: {p.get('shot_duration_range', '?')}s / 切分密度:{p.get('cut_density', '?')}"
            for p in per_section if p.get("section")
        ]
        if hints:
            parts.append(f"剪辑建议: {'; '.join(hints)}")

    # 4. 歌词示例（前 3 句，让 LLM 知道这首歌在唱什么）
    lyrics = quality_summary.get("lyrics") or {}
    lyric_lines = lyrics.get("lines") or []
    if lyric_lines:
        sample = [line.get("text", "") for line in lyric_lines[:3] if line.get("text")]
        if sample:
            parts.append(f"歌词示例: {'  /  '.join(sample)}")
        parts.append(f"歌词语言: {lyrics.get('language', '未知')}")

    return "\n".join(parts) if parts else json.dumps(quality_summary, ensure_ascii=False)


# ---------------------------------------------------------------------------
# BriefPersistenceService
# ---------------------------------------------------------------------------

class BriefPersistenceService:
    """Brief + Style 生成与落库服务。"""

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def generate_and_save(
        self,
        project_id: str,
        user_id: str,
        style_direction: str = "",  # 新流程：不再需要前置风格选择，LLM 从 user_prompt 推断
    ) -> tuple[CreativeBriefVersion, StyleBibleVersion]:
        """执行完整 brief/style 生成流程并落库。

        Args:
            project_id:       目标项目 ID。
            user_id:          当前用户 ID（项目归属校验）。
            style_direction:  用户选定的风格方向（来自 PendingDecision.selected_option_id）。

        Returns:
            (CreativeBriefVersion, StyleBibleVersion) — 新建并激活的版本对象。

        Raises:
            BriefGenerationError: 项目/规格缺失、状态非法、生成失败。
        """
        logger = get_project_logger(project_id, module="services.brief_persistence")

        # ---- 步骤 1: 读取项目上下文 ----------------------------------------
        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise BriefGenerationError("项目不存在", code="project_not_found")

            allowed_stages = {
                ProjectStage.INPUT_READY.value,   # 新流程：从 input_ready 直接生成 brief
                ProjectStage.BRIEF_READY.value,   # 允许重新生成
                ProjectStage.NARRATIVE_READY.value,  # 新 UI：创意剧本包整体重新生成
                # ProjectStage.AUDIO_ANALYZED.value,  # 旧流程（音乐MV模式）：已停用
            }
            if project.current_stage not in allowed_stages:
                raise BriefGenerationError(
                    f"当前阶段 {project.current_stage!r} 不允许生成 brief",
                    code="invalid_stage",
                )

            # 读取 ProjectSpec
            spec = await ProjectSpecRepository(session).get_active(project_id)
            if spec is None:
                raise BriefGenerationError("未找到 active ProjectSpec", code="no_spec")

            user_prompt: str = spec.user_prompt or ""
            # 新流程：从 ProjectSpec.output_config 读取用户指定的目标时长
            # 旧流程（音乐MV模式）时长来源已停用：
            # target_duration_sec: float = float(
            #     (spec.audio_end_sec or 0) - (spec.audio_start_sec or 0)
            # )
            # 当 audio_end_sec=0（用户未手动设置，trim 工具按全曲处理）时，
            # 从 AudioAnalysisVersion.raw_payload['signal']['duration_sec'] 取实际时长。
            # if target_duration_sec <= 0 and project.active_audio_analysis_version_id:
            #     _aa_for_dur = await AudioAnalysisRepository(session).get_by_id(
            #         project.active_audio_analysis_version_id
            #     )
            #     if _aa_for_dur:
            #         _dur = (
            #             (_aa_for_dur.raw_payload or {})
            #             .get("signal", {})
            #             .get("duration_sec", 0)
            #         )
            #         target_duration_sec = float(_dur or 0)
            # if target_duration_sec <= 0:
            #     raise BriefGenerationError(
            #         f"无法获取有效音频时长（audio_end_sec={spec.audio_end_sec!r} 且 "
            #         "AudioAnalysis 未记录 duration_sec），请重新上传并分析音频。",
            #         code="invalid_audio_range",
            #     )
            output_config: dict[str, Any] = normalize_output_config(spec.output_config)
            reference_image_asset_ids = list(spec.reference_image_asset_ids or [])
            target_duration_sec = float(output_config.get("target_duration_sec", 15.0))
            aspect_ratio = output_config.get("aspect_ratio", "9:16")
            storyboard_plan = (
                plan_talking_head_segments(target_duration_sec)
                if is_talking_head_config(output_config)
                else plan_triptych_shots(target_duration_sec)
            )

            # 新流程：不再读取音频分析摘要，audio_ref 置为 None
            # audio_analysis_summary = "暂无音乐摘要。"
            # if project.active_audio_analysis_version_id: ... (旧流程音频分析读取已停用)
            # if project.active_audio_analysis_version_id:
            #     aa = await AudioAnalysisRepository(session).get_by_id(
            #         project.active_audio_analysis_version_id
            #     )
            #     if aa:
            #         audio_analysis_summary = _quality_summary_to_text(
            #             aa.quality_summary or {}
            #         )
            # if project.active_audio_analysis_version_id and aa:
            #     audio_ref = await build_ref_from_asset_latest(
            #         project_id,
            #         artifact_type="audio_analysis",
            #         version_no=aa.version_no,
            #         prefix="audio_analysis",
            #         summary=audio_analysis_summary,
            #     )
            audio_ref = None

            brief_version_no = await CreativeBriefRepository(session).get_next_version_no(project_id)
            style_version_no = await StyleBibleRepository(session).get_next_version_no(project_id)
            active_narrative_id = project.active_narrative_script_version_id

        scene_reference_url = await self._resolve_scene_reference_image_url(project_id)
        product_reference_urls = await self._resolve_product_reference_image_urls(
            project_id,
            reference_image_asset_ids,
        )
        regeneration_feedback = await regeneration_context_service.get_latest_feedback(
            project_id,
            decision_type="confirm_narrative",
            target_entity_id=active_narrative_id,
        )
        if regeneration_feedback:
            logger.info(
                "创意剧本包重新生成反馈已载入",
                event_type="creative_package_regeneration_feedback_loaded",
            )

        # ---- 步骤 2: 调用 CreativePlanningAgent.run_phase1() -------------------
        logger.info("开始生成 brief+style", event_type="brief_generation_start")
        agent = CreativePlanningAgent()
        phase1_result = await agent.run_phase1({
            "project_id": project_id,
            "audio_ref": audio_ref,
            "style_direction": style_direction,
            "user_prompt": user_prompt,
            "target_duration_sec": target_duration_sec,
            "aspect_ratio": aspect_ratio,
            "platform": output_config.get("platform", ""),
            "target_audience": output_config.get("target_audience", ""),
            "style_preference": output_config.get("style_preference", ""),
            "human_on_camera": output_config.get("human_on_camera"),
            "allowed_shot_durations_sec": get_provider_registry().list_supported_durations("video", enabled_only=True) or [4, 5, 6, 8, 10, 12, 15],
            "triptych_plan": storyboard_plan,
            "storyboard_plan": storyboard_plan,
            "generation_profile": output_config.get("generation_profile"),
            "storyboard_layout": output_config.get("storyboard_layout"),
            "segment_duration_sec": output_config.get("segment_duration_sec"),
            "story_board_aspect_ratio": output_config.get("story_board_aspect_ratio"),
            "subtitles_enabled": output_config.get("subtitles_enabled"),
            "video_resolution": output_config.get("video_resolution", "1080p"),
            "image_resolution": output_config.get("image_resolution", "2K"),
            "image_size": output_config.get("image_size"),
            "scene_reference_url": scene_reference_url,
            "scene_reference_role": "固定场地/场景参考图，用于创意规划阶段锁定空间、布景、光线、桌面关系和场地氛围",
            "product_reference_urls": product_reference_urls,
            "product_reference_role": "产品参考图，用于创意规划阶段识别产品外观、包装、质地、颜色、卖点呈现和使用场景",
            "regeneration_feedback": regeneration_feedback,
            "version_no": min(brief_version_no, style_version_no),
        })

        # 从 ArtifactRef 读回内容
        brief_ref = phase1_result.get("brief_ref") or {}
        style_ref = phase1_result.get("style_ref") or {}

        try:
            creative_brief_data: dict[str, Any] = await read_artifact(brief_ref) if brief_ref.get("artifact_id") else {}
        except Exception as exc:
            logger.warning(f"读取 brief ArtifactRef 失败: {exc!r}，使用兜底结构", event_type="brief_artifact_read_failed")
            creative_brief_data = {}
        try:
            style_bible_data: dict[str, Any] = await read_artifact(style_ref) if style_ref.get("artifact_id") else {}
        except Exception as exc:
            logger.warning(f"读取 style ArtifactRef 失败: {exc!r}，使用兜底结构", event_type="style_artifact_read_failed")
            style_bible_data = {}
        self._enforce_reference_profiles(
            creative_brief_data,
            style_bible_data,
            scene_reference_url=scene_reference_url,
            product_reference_urls=product_reference_urls,
        )

        # ---- 步骤 3: 落库 + 激活 + 快照 + 状态推进 -------------------------
        logger.info(
            f"[BRIEF-DEBUG] 开始落库: brief_version_no={brief_version_no}, style_version_no={style_version_no}, "
            f"creative_brief_data keys={list(creative_brief_data.keys()) if creative_brief_data else None}, "
            f"style_bible_data keys={list(style_bible_data.keys()) if style_bible_data else None}",
            event_type="brief_persist_start",
        )
        try:
            async with UnitOfWork() as uow2:
                logger.info("[BRIEF-DEBUG] UnitOfWork 已开启，准备调用 _persist", event_type="brief_uow_opened")
                brief_version, style_version = await self._persist(
                    session=uow2.session,
                    project_id=project_id,
                    creative_brief_data=creative_brief_data,
                    style_bible_data=style_bible_data,
                    style_direction=style_direction,
                )
                logger.info("[BRIEF-DEBUG] _persist 执行完成，准备提交事务", event_type="brief_persist_done")
            logger.info(
                f"[BRIEF-DEBUG] 事务已提交: brief={brief_version.id!r} style={style_version.id!r}",
                event_type="brief_transaction_committed",
            )
        except Exception as persist_exc:
            logger.error(
                f"[BRIEF-ERROR] _persist 异常: {persist_exc!r}",
                event_type="brief_persist_error",
            )
            raise

        logger.info(
            f"brief/style 生成完成: brief={brief_version.id!r} style={style_version.id!r}",
            event_type="brief_generation_done",
        )
        return brief_version, style_version

    async def _resolve_scene_reference_image_url(self, project_id: str) -> str | None:
        cfg = get_config().talking_head
        scene_path = str(getattr(cfg, "story_board_scene_image_path", "") or "").strip()
        if not scene_path:
            return None
        path = Path(scene_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[3] / path
        if not path.exists():
            return None
        suffix = path.suffix.lower() or ".png"
        content_type = mimetypes.guess_type(path.name)[0] or "image/png"
        key = f"projects/{project_id}/assets/creative_scene_reference/{path.stem}{suffix}"
        storage = get_storage()
        await storage.async_upload_file(key, path, content_type=content_type)
        return storage.get_presigned_url(key, expiry_seconds=6 * 60 * 60)

    async def _resolve_product_reference_image_urls(
        self,
        project_id: str,
        asset_ids: list[str],
    ) -> list[str]:
        if not asset_ids:
            return []
        async with UnitOfWork() as uow:
            asset_repo = AssetRepository(uow.session)
            assets = await asset_repo.list_by_ids(asset_ids[:3])
            asset_map = {asset.id: asset for asset in assets if asset.project_id == project_id}
            ordered_assets = [asset_map[asset_id] for asset_id in asset_ids[:3] if asset_id in asset_map]
            urls: list[str] = []
            for asset in ordered_assets:
                url = await build_asset_access_url(asset)
                if url:
                    urls.append(url)
                else:
                    get_project_logger(project_id, module="services.brief").warning(
                        f"产品参考图访问 URL 生成失败: asset_id={asset.id!r}",
                        event_type="product_reference_url_missing",
                    )
            return urls

    def _enforce_reference_profiles(
        self,
        creative_brief_data: dict[str, Any],
        style_bible_data: dict[str, Any],
        *,
        scene_reference_url: str | None,
        product_reference_urls: list[str],
    ) -> None:
        """LLM 可能忽略图片附件；后端用真实输入修正可继承的参考图契约。"""
        brief = creative_brief_data.get("creative_brief")
        if isinstance(brief, dict):
            extension = brief.setdefault("extension", {})
        else:
            extension = creative_brief_data.setdefault("extension", {})
        if not isinstance(extension, dict):
            return

        if scene_reference_url:
            scene_profile = {
                "role": "固定场地/场景参考图",
                "url": scene_reference_url,
                "observation": (
                    "已收到固定场地参考图 data/person_pic/d1.png。后续创意、剧本、分镜和视频 prompt "
                    "必须基于该图片的空间结构、布景、桌面关系、背景材质、光线和场地氛围展开。"
                ),
                "usage_rules": "不得声称未收到固定场地图；不得规划与该场地冲突的新空间。",
            }
            extension["scene_reference_profile"] = scene_profile
            extension["set_design_profile"] = scene_profile

        if product_reference_urls:
            extension.setdefault(
                "product_reference_profile",
                {
                    "role": "产品参考图",
                    "urls": product_reference_urls,
                    "observation": (
                        "已收到产品参考图。后续创意、剧本、分镜和视频 prompt 应继承产品外观、"
                        "包装、颜色、材质和卖点呈现。"
                    ),
                    "usage_rules": "不得忽略产品真实外观；不得把产品图当作人物图。",
                },
            )

        notes_parts = []
        if style_bible_data.get("reference_notes"):
            notes_parts.append(str(style_bible_data["reference_notes"]))
        if scene_reference_url:
            notes_parts.append(
                "固定场地图已提供：data/person_pic/d1.png，后续必须以该图的真实场地为基准，"
                "不得再写“未收到固定场地参考图”。"
            )
        if product_reference_urls:
            notes_parts.append(
                f"产品参考图已提供 {len(product_reference_urls)} 张，后续必须继承产品真实外观、包装、材质和颜色。"
            )
        if notes_parts:
            style_bible_data["reference_notes"] = " ".join(notes_parts)

    async def save_from_data(
        self,
        project_id: str,
        brief_data: dict,
        style_data: dict,
        style_direction: str,
    ) -> tuple["CreativeBriefVersion", "StyleBibleVersion"]:
        """Sub-Agent 完成生成后调用：持久化 brief+style 数据，不做 LLM 生成。

        dispatch_agent() 在 CreativePlanningAgent.run_phase1() 返回后调用此方法。
        """
        # Bug-5修复：save_from_data 增加阶段合法性前置校验，防止状态机跳跃
        async with UnitOfWork() as _check_uow:
            _proj = await ProjectRepository(_check_uow.session).get_by_id(project_id)
            if _proj is None:
                raise BriefGenerationError("项目不存在", code="project_not_found")
            _allowed = {
                ProjectStage.INPUT_READY.value,   # 新流程
                ProjectStage.BRIEF_READY.value,
                # ProjectStage.AUDIO_ANALYZED.value,  # 旧流程：已停用
            }
            if _proj.current_stage not in _allowed:
                raise BriefGenerationError(
                    f"当前阶段 {_proj.current_stage!r} 不允许保存 brief",
                    code="invalid_stage",
                )
        async with UnitOfWork() as uow:
            return await self._persist(
                session=uow.session,
                project_id=project_id,
                creative_brief_data=brief_data,
                style_bible_data=style_data,
                style_direction=style_direction,
        )

    async def _persist(
        self,
        *,
        session: AsyncSession,
        project_id: str,
        creative_brief_data: dict[str, Any],
        style_bible_data: dict[str, Any],
        style_direction: str,
    ) -> tuple[CreativeBriefVersion, StyleBibleVersion]:
        """落库 + 激活 + 写快照 + 状态推进（单事务）。"""
        from app.core.logging import get_project_logger
        _logger = get_project_logger(project_id, module="services.brief_persistence._persist")

        # 新流程真实输出：
        #   {"creative_brief": {...}, "style_bible": {...}}
        # 旧流程/旧兼容输出：
        #   creative_brief_data = {...}
        #   style_bible_data   = {...}
        # 在保存层统一解包，避免 DB 列字段为空、raw_payload 结构错位，
        # 否则后续 narrative / shot_plan / storyboard 都会读不到 extension 与 style 字段。
        creative_brief_content = (
            creative_brief_data.get("creative_brief")
            if isinstance(creative_brief_data, dict) and isinstance(creative_brief_data.get("creative_brief"), dict)
            else creative_brief_data
        ) or {}
        style_bible_content = (
            style_bible_data.get("style_bible")
            if isinstance(style_bible_data, dict) and isinstance(style_bible_data.get("style_bible"), dict)
            else style_bible_data
        ) or {}
        extension = creative_brief_content.get("extension")
        if isinstance(extension, dict):
            normalized_output = normalize_output_config(extension)
            storyboard_plan = (
                plan_talking_head_segments(float(normalized_output.get("target_duration_sec") or 15))
                if is_talking_head_config(normalized_output)
                else plan_triptych_shots(float(normalized_output.get("target_duration_sec") or 15))
            )
            creative_brief_content["extension"] = {
                **extension,
                **storyboard_plan,
                "target_duration_sec": int(storyboard_plan["target_duration_sec"]),
                "aspect_ratio": normalized_output["aspect_ratio"],
                "video_resolution": normalized_output["video_resolution"],
                "image_resolution": normalized_output["image_resolution"],
                "image_size": normalized_output.get("image_size") or normalized_output.get("story_board_image_size"),
                "storyboard_layout": normalized_output["storyboard_layout"],
                "generation_profile": normalized_output.get("generation_profile"),
                "segment_duration_sec": normalized_output.get("segment_duration_sec"),
                "story_board_aspect_ratio": normalized_output.get("story_board_aspect_ratio"),
                "subtitles_enabled": normalized_output.get("subtitles_enabled", False),
            }
            if is_talking_head_config(normalized_output):
                creative_brief_content["extension"]["character_list"] = [
                    dict(TALKING_HEAD_HOST_CHARACTER)
                ]

        _logger.info(
            f"[_PERSIST] 开始落库: project_id={project_id}, current_stage检查前",
            event_type="persist_enter",
        )

        brief_repo = CreativeBriefRepository(session)
        style_repo = StyleBibleRepository(session)
        proj_repo = ProjectRepository(session)

        project = await proj_repo.get_by_id(project_id)
        _logger.info(
            f"[_PERSIST] 项目加载完成: project_id={project_id}, current_stage={project.current_stage}",
            event_type="persist_project_loaded",
        )

        # ---- Brief 版本 --------------------------------------------------
        _logger.info("[_PERSIST] 步骤1: 写入 Brief 版本", event_type="persist_brief_start")
        await brief_repo.deactivate_all(project_id)
        brief_version_no = await brief_repo.get_next_version_no(project_id)

        brief_version = CreativeBriefVersion(
            project_id=project_id,
            version_no=brief_version_no,
            title=creative_brief_content.get("title") or "",
            summary=creative_brief_content.get("summary") or "",
            narrative_mode=creative_brief_content.get("narrative_mode") or "mixed",
            performance_ratio=float(
                creative_brief_content.get("performance_ratio") or 0.4
            ),
            mood_tags=creative_brief_content.get("mood_tags") or [],
            style_direction=creative_brief_content.get("style_direction") or style_direction,
            raw_payload=creative_brief_content,
            is_active=True,
        )
        await brief_repo.add(brief_version)
        await session.flush()
        await session.refresh(brief_version)
        _logger.info(
            f"[_PERSIST] Brief 版本写入完成: brief_version.id={brief_version.id}, version_no={brief_version_no}",
            event_type="persist_brief_done",
        )

        # ---- Style 版本 --------------------------------------------------
        _logger.info("[_PERSIST] 步骤2: 写入 Style 版本", event_type="persist_style_start")
        await style_repo.deactivate_all(project_id)
        style_version_no = await style_repo.get_next_version_no(project_id)

        # palette 规范化：确保是 dict
        palette = style_bible_content.get("palette")
        if isinstance(palette, str):
            palette = {"description": palette}
        elif not isinstance(palette, dict):
            palette = {}

        # 将 dict/list 类型字段序列化为字符串，兼容 LLM 返回复杂结构的情况
        def _serialize_field(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, str):
                return value
            return json.dumps(value, ensure_ascii=False)

        style_version = StyleBibleVersion(
            project_id=project_id,
            version_no=style_version_no,
            palette=palette,
            lighting_style=_serialize_field(style_bible_content.get("lighting_style")),
            camera_style=_serialize_field(
                style_bible_content.get("camera_style") or style_bible_content.get("camera_language")
            ),
            film_texture=_serialize_field(style_bible_content.get("film_texture")),
            reference_notes=_serialize_field(style_bible_content.get("reference_notes")),
            raw_payload=style_bible_content,
            is_active=True,
        )
        await style_repo.add(style_version)
        await session.flush()
        await session.refresh(style_version)
        _logger.info(
            f"[_PERSIST] Style 版本写入完成: style_version.id={style_version.id}, version_no={style_version_no}",
            event_type="persist_style_done",
        )

        # ---- 更新项目 active 指针 ----------------------------------------
        _logger.info("[_PERSIST] 步骤3: 更新项目 active 指针", event_type="persist_update_pointer_start")
        project.active_brief_version_id = brief_version.id
        project.active_style_version_id = style_version.id
        session.add(project)
        _logger.info(
            f"[_PERSIST] active_brief_version_id={project.active_brief_version_id}, active_style_version_id={project.active_style_version_id}",
            event_type="persist_update_pointer_done",
        )

        # ---- 状态推进 → brief_ready ----------------------------------------
        _logger.info(
            f"[_PERSIST] 步骤4: 状态推进检查: current_stage={project.current_stage}, target=BRIEF_READY",
            event_type="persist_state_transition_check",
        )
        if project.current_stage != ProjectStage.BRIEF_READY.value:
            _logger.info("[_PERSIST] 准备调用 state_transition_service.advance_project", event_type="persist_advance_project_start")
            await state_transition_service.advance_project(
                session, project, ProjectStage.BRIEF_READY
            )
            _logger.info("[_PERSIST] state_transition_service.advance_project 返回", event_type="persist_advance_project_done")
        else:
            _logger.info("[_PERSIST] 当前已是 BRIEF_READY 阶段，跳过状态推进", event_type="persist_state_already_brief_ready")

        # Bug-8修复：移除此处的本地文件写入。
        # 当通过 dispatch_agent 路径调用时，CreativePlanningAgent.run_phase1()已经通过
        # write_artifact_tool 写入本地文件 + Asset。此处再次写入会导致同一目录下
        # 两个重复文件。此写入僅适用于直接调用 generate_and_save()（非 dispatch 路径）的情况。
        # 根据调用方是否已写入 Asset 进行判断：若 brief_version_no==1 则务必补写。
        from app.repositories.asset_repository import AssetRepository  # noqa: PLC0415
        async with UnitOfWork() as _asset_uow:
            _existing = await AssetRepository(_asset_uow.session).list_by_project(
                project_id, asset_type="creative_brief", limit=1
            )
        if not _existing:
            # 无 Asset 记录时（非 dispatch 路径）才写本地快照
            store = LocalArtifactStore(project_id)
            store.write_json(
                ArtifactStage.BRIEF,
                "creative_brief",
                creative_brief_content,
                version=brief_version_no,
            )
            store.write_json(
                ArtifactStage.STYLE,
                "style_bible",
                style_bible_content,
                version=style_version_no,
            )

        return brief_version, style_version
