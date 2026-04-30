"""叙事剧本生成服务（NarrativeScriptService）。

来源文档：doc11 §5.4（NarrativeScriptAgent 工作协议）

职责：
  1. 前置校验（项目处于 brief_ready，active brief + style 存在）
  2. 读取 ProjectSpec 中的 user_prompt
  3. 读取 AudioAnalysis.quality_summary
  4. 调用 NarrativeScriptAgent 生成叙事剧本
  5. 落库 NarrativeScriptVersion
  6. 失活旧版本
  7. 更新 projects.active_narrative_script_version_id
  8. 写本地 JSON 快照（03_brief/ 阶段目录）
  9. 推进项目状态 → narrative_ready
"""
from __future__ import annotations

from typing import Any

from app.agents.narrative_script_agent import NarrativeScriptAgent
from app.core.logging import get_project_logger
from app.core.provider_registry import get_provider_registry
from app.tools.shared.artifact_tools import build_ref_from_asset_latest, read_artifact
from app.domain.states import ProjectStage
from app.models.visual_bible import NarrativeScriptVersion
from app.repositories.audio_analysis_repository import AudioAnalysisRepository
from app.repositories.planning_repositories import (
    CreativeBriefRepository,
    StyleBibleRepository,
)
from app.repositories.project_repository import ProjectRepository
from app.repositories.project_spec_repository import ProjectSpecRepository
from app.repositories.unit_of_work import UnitOfWork
from app.repositories.visual_bible_repository import NarrativeScriptVersionRepository
from app.services.state_transition_service import state_transition_service
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.path_planner import ArtifactStage
from app.utils.ids import generate_ulid


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class NarrativeScriptError(Exception):
    """叙事剧本生成业务异常。"""

    def __init__(self, message: str, code: str = "narrative_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_EXPLAINER_KEYWORDS = ("讲解", "解说", "科普", "教程", "口播", "旁白", "explainer", "tutorial", "voiceover")
_AD_KEYWORDS = ("广告", "带货", "推广", "品牌", "宣传", "卖点", "cta", "ad", "promo", "brand", "commercial")
_DRAMA_KEYWORDS = ("剧情", "对白", "角色", "故事", "冲突", "drama", "character", "story")
_VISUAL_KEYWORDS = ("纯视觉", "氛围", "情绪", "mv", "visual", "mood", "atmosphere", "music video")


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in keywords)


def _classify_expression_type(user_prompt: str, brief_payload: dict) -> str:
    merged = " ".join(
        str(part or "")
        for part in [
            user_prompt,
            brief_payload.get("title"),
            brief_payload.get("summary"),
            brief_payload.get("style_direction"),
            brief_payload.get("narrative_mode"),
        ]
    )
    if _contains_any(merged, _EXPLAINER_KEYWORDS):
        return "explainer"
    if _contains_any(merged, _AD_KEYWORDS):
        return "ad"
    if _contains_any(merged, _DRAMA_KEYWORDS):
        return "drama"
    if _contains_any(merged, _VISUAL_KEYWORDS):
        return "visual"
    return "general"


def _build_narrative_audio_strategy(expression_type: str) -> dict[str, str]:
    strategy_map = {
        "explainer": {
            "voice_mode": "continuous_voiceover",
            "voice_timbre": "专业、亲切、可信赖的中文讲解音色",
            "voice_tone": "稳定、清楚、像顾问式解释",
            "bgm_mode": "light_bed",
            "bgm_intensity": "low",
            "continuity_rule": "整条视频保持同一位讲解者的口吻与音色，背景音始终让位于信息表达",
        },
        "ad": {
            "voice_mode": "sparse_voiceover",
            "voice_timbre": "更有识别度和记忆点的广告旁白音色",
            "voice_tone": "干脆、强调卖点、节奏更明确",
            "bgm_mode": "rhythmic_ad",
            "bgm_intensity": "medium",
            "continuity_rule": "台词集中在开头、关键卖点和结尾 CTA，背景音乐承担更多推进作用",
        },
        "drama": {
            "voice_mode": "dialogue_driven",
            "voice_timbre": "以角色真实说话感为主，不做统一广告腔",
            "voice_tone": "跟随剧情和角色状态变化",
            "bgm_mode": "cinematic_support",
            "bgm_intensity": "medium",
            "continuity_rule": "对白以角色驱动，背景音为情绪服务，不抢台词",
        },
        "visual": {
            "voice_mode": "music_led",
            "voice_timbre": "默认无固定旁白音色",
            "voice_tone": "以画面和音乐主导，不额外补口播",
            "bgm_mode": "ambient_only",
            "bgm_intensity": "medium",
            "continuity_rule": "优先保持氛围音和音乐连贯性，无需强行加入语言主线",
        },
        "general": {
            "voice_mode": "sparse_voiceover",
            "voice_timbre": "自然、中性、清晰的中文旁白音色",
            "voice_tone": "表达清楚，不抢画面",
            "bgm_mode": "light_bed",
            "bgm_intensity": "low",
            "continuity_rule": "只有关键镜头承载口播，其余镜头让画面与背景音自然衔接",
        },
    }
    return {"expression_type": expression_type, **strategy_map.get(expression_type, strategy_map["general"])}


def _build_shot_audio_strategy(
    *,
    expression_type: str,
    shot_index: int,
    total_shots: int,
    dialogue: str,
) -> dict[str, Any]:
    has_dialogue = bool((dialogue or "").strip())
    if expression_type == "explainer":
        return {
            "has_dialogue": has_dialogue,
            "delivery_style": "voiceover" if has_dialogue else "silent_visual",
            "voice_tone": "稳定讲解",
            "bgm_action": "duck" if has_dialogue else "support",
            "bgm_intensity": "low" if has_dialogue else "medium",
            "continuity_group": "main_narration",
        }
    if expression_type == "ad":
        style = "cta" if has_dialogue and shot_index == total_shots - 1 else ("voiceover" if has_dialogue else "silent_visual")
        return {
            "has_dialogue": has_dialogue,
            "delivery_style": style,
            "voice_tone": "强调卖点" if has_dialogue else "无口播展示",
            "bgm_action": "duck" if has_dialogue else "music_only",
            "bgm_intensity": "medium",
            "continuity_group": "brand_voice" if has_dialogue else "brand_music",
        }
    if expression_type == "drama":
        return {
            "has_dialogue": has_dialogue,
            "delivery_style": "character_dialogue" if has_dialogue else "silent_visual",
            "voice_tone": "角色真实说话" if has_dialogue else "无对白表演",
            "bgm_action": "duck" if has_dialogue else "support",
            "bgm_intensity": "medium" if has_dialogue else "low",
            "continuity_group": "character_scene",
        }
    if expression_type == "visual":
        return {
            "has_dialogue": has_dialogue,
            "delivery_style": "voiceover" if has_dialogue else "silent_visual",
            "voice_tone": "极少量点题口播" if has_dialogue else "以音乐和氛围主导",
            "bgm_action": "duck" if has_dialogue else "ambient_only",
            "bgm_intensity": "medium",
            "continuity_group": "music_led",
        }
    return {
        "has_dialogue": has_dialogue,
        "delivery_style": "voiceover" if has_dialogue else "silent_visual",
        "voice_tone": "自然中性",
        "bgm_action": "duck" if has_dialogue else "support",
        "bgm_intensity": "low" if has_dialogue else "medium",
        "continuity_group": "general_voice",
    }


# ---------------------------------------------------------------------------
# NarrativeScriptService
# ---------------------------------------------------------------------------

class NarrativeScriptService:
    """叙事剧本生成服务：brief + style + audio → NarrativeScriptVersion。"""

    def __init__(self) -> None:
        self._agent = NarrativeScriptAgent()

    async def generate_and_save(
        self,
        project_id: str,
        user_id: str,
    ) -> NarrativeScriptVersion:
        """执行完整叙事剧本生成流程。

        Args:
            project_id: 目标项目 ID。
            user_id:    当前用户 ID（项目归属校验）。

        Returns:
            新建并激活的 NarrativeScriptVersion 对象。

        Raises:
            NarrativeScriptError: 前置条件不满足或生成失败。
        """
        logger = get_project_logger(project_id, module="services.narrative_script")

        # ---- 步骤 1: 读取并校验项目上下文 ----------------------------------------
        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise NarrativeScriptError("项目不存在", code="project_not_found")

            # 允许在 brief_ready 或 narrative_ready 阶段生成（narrative_ready 允许重新生成）
            allowed_stages = {
                ProjectStage.BRIEF_READY.value,
                ProjectStage.NARRATIVE_READY.value,
            }
            if project.current_stage not in allowed_stages:
                raise NarrativeScriptError(
                    f"当前阶段 {project.current_stage!r} 不允许生成叙事剧本，"
                    "需要先完成 brief 并等待 confirm_brief 决策",
                    code="invalid_stage",
                )

            # 读取 active brief
            brief = await CreativeBriefRepository(session).get_active(project_id)
            if brief is None:
                raise NarrativeScriptError(
                    "未找到 active creative brief，请先完成创意方案",
                    code="no_brief",
                )

            brief_ref = await build_ref_from_asset_latest(
                project_id,
                artifact_type="creative_brief",
                version_no=brief.version_no,
                prefix="creative_brief",
                summary=brief.summary or "",
            )

            # 读取 active style
            style = await StyleBibleRepository(session).get_active(project_id)
            # style 缺失时容忍（使用 None 兜底，Agent 会自行推断）
            style_ref = None
            if style is not None:
                style_ref = await build_ref_from_asset_latest(
                    project_id,
                    artifact_type="style_bible",
                    version_no=style.version_no,
                    prefix="style_bible",
                    summary=getattr(style, "lighting_style", "") or "style_bible",
                )

            # 读取音频分析摘要
            audio_ref = None
            if project.active_audio_analysis_version_id:
                aa = await AudioAnalysisRepository(session).get_by_id(
                    project.active_audio_analysis_version_id
                )
                if aa:
                    from app.services.brief_persistence_service import _quality_summary_to_text  # noqa: PLC0415
                    audio_ref = await build_ref_from_asset_latest(
                        project_id,
                        artifact_type="audio_analysis",
                        version_no=aa.version_no,
                        prefix="audio_analysis",
                        summary=_quality_summary_to_text(aa.quality_summary or {}),
                    )

            # 读取 user_prompt + 参考图信息（来自 active ProjectSpec）
            user_prompt = ""
            reference_image_count = 0
            if project.active_project_spec_version_id:
                spec = await ProjectSpecRepository(session).get_active(project_id)
                if spec:
                    user_prompt = getattr(spec, "user_prompt", "") or ""
                    ref_ids = getattr(spec, "reference_image_asset_ids", None) or []
                    reference_image_count = len([r for r in ref_ids if r])

            brief_payload = brief.raw_payload or {}
            if isinstance(brief_payload.get("creative_brief"), dict):
                brief_payload = brief_payload.get("creative_brief") or {}
            extension = brief_payload.get("extension") or {}
            target_duration_sec = int(extension.get("target_duration_sec") or 60)
            allowed_shot_durations_sec = extension.get("allowed_shot_durations_sec") or (
                get_provider_registry().list_supported_durations("video", enabled_only=True) or [4, 5, 6, 8, 10, 12, 15]
            )

        # ---- 步骤 2: 构建 task_spec 并调用 Agent.run() --------------------------------
        logger.info("叙事剧本生成开始", event_type="narrative_generation_start")

        # P1 修复：version_no 只查询一次，同时传给 Agent 和 _persist()，
        # 保证 ArtifactRef 中的 version_no 与落库版本号严格一致。
        next_version_no = await self._get_next_version_no(project_id)
        task_spec = {
            "project_id": project_id,
            "user_prompt": user_prompt,
            "brief_ref": brief_ref,
            "style_ref": style_ref,
            "audio_ref": audio_ref,
            "reference_image_count": reference_image_count,
            "target_duration_sec": target_duration_sec,
            "allowed_shot_durations_sec": allowed_shot_durations_sec,
            "version_no": next_version_no,
        }
        artifact_ref = await self._agent.run(task_spec)

        # 从 ArtifactRef 读回叙事剧本内容
        try:
            narrative_data = await read_artifact(artifact_ref)
        except Exception as exc:
            logger.warning(
                f"从 ArtifactRef 读取叙事剧本内容失败: {exc!r}，使用兜底内容",
                event_type="narrative_artifact_read_failed",
            )
            narrative_data = {
                "story_arc": "纯氛围型 MV", "characters": [],
                "scenes": [{"id": "scene_default", "name": "主场景",
                            "description": "与音乐风格匹配", "appears_in_sections": []}],
                "section_mapping": [],
            }

        # 用 brief.extension 和 shots 对 narrative 结构做补全，避免 LLM 漏掉
        # characters / scenes 导致下游 visual bible、前端和 shot_plan 失真。
        narrative_data = self._normalize_narrative_data(
            narrative_data=narrative_data,
            brief_raw_payload=brief.raw_payload if brief else {},
            user_prompt=user_prompt,
        )

        # ---- 步骤 3: 落库 + 激活 + 状态推进 ----------------------------------------
        narrative_version = await self._persist(
            project_id=project_id,
            narrative_data=narrative_data,
            logger=logger,
            version_no=next_version_no,
        )

        logger.info(
            f"叙事剧本生成完成: version={narrative_version.version_no} "
            f"chars={len(narrative_version.characters or [])} "
            f"scenes={len(narrative_version.scenes or [])}",
            event_type="narrative_generation_done",
        )
        return narrative_version

    def _normalize_narrative_data(
        self,
        *,
        narrative_data: dict,
        brief_raw_payload: dict,
        user_prompt: str = "",
    ) -> dict:
        """补齐 narrative 的 characters / scenes / shots 结构。

        规则：
          1. brief.extension.character_list 非空时，characters 不能为空
          2. scenes 为空时，从 shots[*].scene_description 自动抽取
          3. shots[*].characters_in_shot 为空时，尽量回填 brief 里的首角色
        """
        result = dict(narrative_data or {})
        shots = list(result.get("shots") or [])

        brief_payload = brief_raw_payload or {}
        if isinstance(brief_payload.get("creative_brief"), dict):
            brief_payload = brief_payload.get("creative_brief") or {}
        extension = brief_payload.get("extension") or {}
        brief_characters = list(extension.get("character_list") or [])
        expression_type = _classify_expression_type(user_prompt, brief_payload)

        normalized_characters = list(result.get("characters") or [])
        if not normalized_characters and brief_characters:
            appears = [s.get("shot_index") for s in shots if isinstance(s, dict)]
            normalized_characters = [
                {
                    "id": char.get("character_id") or "",
                    "name": char.get("name") or "",
                    "description": " / ".join(
                        [
                            str(char.get("appearance") or "").strip(),
                            str(char.get("personality") or "").strip(),
                        ]
                    ).strip(" /"),
                    "appears_in_shots": appears,
                }
                for char in brief_characters
                if char.get("character_id")
            ]

        fallback_character_id = (
            normalized_characters[0].get("id")
            if normalized_characters and isinstance(normalized_characters[0], dict)
            else None
        )
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            chars = shot.get("characters_in_shot")
            if not chars and fallback_character_id:
                shot["characters_in_shot"] = [fallback_character_id]
            if "dialogue" not in shot or shot.get("dialogue") is None:
                shot["dialogue"] = ""
        total_shots = len(shots)
        for idx, shot in enumerate(shots):
            if not isinstance(shot, dict):
                continue
            shot["audio_strategy"] = shot.get("audio_strategy") or _build_shot_audio_strategy(
                expression_type=expression_type,
                shot_index=int(shot.get("shot_index", idx)),
                total_shots=total_shots,
                dialogue=str(shot.get("dialogue") or ""),
            )

        normalized_scenes = list(result.get("scenes") or [])
        if not normalized_scenes:
            scene_map: dict[str, dict] = {}
            for shot in shots:
                if not isinstance(shot, dict):
                    continue
                scene_desc = str(shot.get("scene_description") or "").strip()
                if not scene_desc:
                    continue
                key = scene_desc
                scene = scene_map.get(key)
                if scene is None:
                    scene_id = f"scene_{len(scene_map) + 1:03d}"
                    scene = {
                        "id": scene_id,
                        "name": f"场景 {len(scene_map) + 1}",
                        "description": scene_desc,
                        "appears_in_shots": [],
                    }
                    scene_map[key] = scene
                if shot.get("shot_index") is not None:
                    scene["appears_in_shots"].append(shot["shot_index"])
            normalized_scenes = list(scene_map.values())

        result["shots"] = shots
        result["characters"] = normalized_characters
        result["scenes"] = normalized_scenes
        result["audio_strategy"] = result.get("audio_strategy") or _build_narrative_audio_strategy(expression_type)
        return result

    async def _get_next_version_no(self, project_id: str) -> int:
        async with UnitOfWork() as uow:
            return await NarrativeScriptVersionRepository(uow.session).get_next_version_no(project_id)

    # ------------------------------------------------------------------
    # 落库核心
    # ------------------------------------------------------------------

    async def _persist(
        self,
        project_id: str,
        narrative_data: dict,
        logger: Any,
        version_no: int | None = None,
    ) -> NarrativeScriptVersion:
        """落库 NarrativeScriptVersion + 更新项目指针 + 推进状态。

        Args:
            version_no: 外部传入的版本号。若为 None 则内部查询（兼容旧调用）。
                        P1 修复：generate_and_save() 和 save_from_data() 均传入，
                        保证与 Agent 写出的 ArtifactRef version_no 一致。
        """
        async with UnitOfWork() as uow:
            session = uow.session

            repo = NarrativeScriptVersionRepository(session)
            proj_repo = ProjectRepository(session)
            project = await proj_repo.get_by_id(project_id)

            # 失活旧版本
            await repo.deactivate_all(project_id)
            # P1 修复：优先使用外部传入的 version_no，避免两次独立查询在并发时不一致
            if version_no is None:
                version_no = await repo.get_next_version_no(project_id)

            # 创建新版本
            narrative_version = NarrativeScriptVersion(
                id=generate_ulid(),
                project_id=project_id,
                version_no=version_no,
                story_arc=narrative_data.get("story_arc", ""),
                characters=narrative_data.get("characters", []),
                scenes=narrative_data.get("scenes", []),
                section_mapping=narrative_data.get("section_mapping", []),
                raw_payload=narrative_data,
                is_active=True,
            )
            await repo.add(narrative_version)
            await session.flush()
            await session.refresh(narrative_version)

            # 更新项目 active 指针
            project.active_narrative_script_version_id = narrative_version.id
            session.add(project)

            # 推进状态 → narrative_ready（若当前不在该阶段才推进）
            if project.current_stage != ProjectStage.NARRATIVE_READY.value:
                await state_transition_service.advance_project(
                    session, project, ProjectStage.NARRATIVE_READY
                )

        # BUG-10 修复：之前只写摘要（仅有计数），导致 build_ref_from_latest() 取到的最新文件
        # 就是摘要而非 Agent 先写的全量 JSON。
        # 修复：直接写入 narrative_data 全量内容，确保最新文件含完整的
        # characters、scenes、section_mapping 数据。
        store = LocalArtifactStore(project_id)
        store.write_json(
            ArtifactStage.BRIEF,
            "narrative_script",
            narrative_data,
            version=version_no,
        )

        logger.info(
            f"叙事剧本落库完成: version_id={narrative_version.id!r} "
            f"version_no={version_no}",
            event_type="narrative_persisted",
        )
        return narrative_version

    async def save_from_data(
        self,
        project_id: str,
        narrative_data: dict,
        version_no: int | None = None,
    ) -> "NarrativeScriptVersion":
        """Sub-Agent 完成生成后调用：持久化叙事剧本数据，不做 LLM 生成。

        dispatch_agent() 在 NarrativeScriptAgent.run() 返回后调用此方法。

        Args:
            version_no: 外部传入的版本号。P1 修复：若调用方已知 version_no，
                        传入此参数可避免重复查询，保证 ArtifactRef 与落库版本一致。
        """
        # Bug-5修复：save_from_data 增加阶段合法性前置校验，防止状态机跳跃
        async with UnitOfWork() as _check_uow:
            _proj = await ProjectRepository(_check_uow.session).get_by_id(project_id)
            if _proj is None:
                raise NarrativeScriptError("项目不存在", code="project_not_found")
            _allowed = {
                ProjectStage.BRIEF_READY.value,
                ProjectStage.NARRATIVE_READY.value,
            }
            if _proj.current_stage not in _allowed:
                raise NarrativeScriptError(
                    f"当前阶段 {_proj.current_stage!r} 不允许保存叙事剧本，"
                    "需要先完成 brief 并等待 confirm_brief 决策",
                    code="invalid_stage",
                )
        logger = get_project_logger(project_id, module="services.narrative_script")
        return await self._persist(
            project_id=project_id,
            narrative_data=narrative_data,
            logger=logger,
            version_no=version_no,
        )
