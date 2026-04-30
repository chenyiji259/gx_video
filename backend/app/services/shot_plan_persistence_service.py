"""ShotPlanPersistenceService — shot plan 生成与落库。

来源文档：doc 09 任务 9-03

职责：
  1. 读取 active CreativeBriefVersion + StyleBibleVersion
  2. 读取 active AudioAnalysisVersion（quality_summary → 摘要文本）
  3. 读取 active ProjectSpecVersion（目标时长/比例/performance_ratio）
  4. 调用 CreativePlanningAgent.generate_shot_plan()
  5. 落库 scene_plan_versions + shot_plan_versions + shots（批量写入 shots 表）
  6. 更新项目 active 指针（scene_plan / shot_plan）
  7. 写本地 JSON 快照（05_shot_plan/），包含完整 ShotSemanticSpec
  8. 推进项目状态 → shot_plan_ready

字段映射规则（doc 09 §3 风险说明 + creative_planning.md）：
  - shot_role      → shot_type   (performance/narrative/atmosphere)
  - pace           → visual_energy: slow→low, medium→medium, fast→high
  - scene_type     → section_type
  - duration_sec   → duration_ms (× 1000)
  - start_ms / end_ms 直接使用（若缺失则按 shot 顺序等分时长估算）
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.creative_planning_agent import CreativePlanningAgent
from app.core.logging import get_project_logger
from app.core.provider_registry import get_provider_registry
from app.tools.shared.artifact_tools import build_ref_from_asset_latest, read_artifact, write_artifact
from app.domain.states import ProjectStage
from app.models.planning import ScenePlanVersion, Shot, ShotPlanVersion
# from app.repositories.audio_analysis_repository import AudioAnalysisRepository  # 旧流程：已停用
from app.repositories.planning_repositories import (
    CreativeBriefRepository,
    ScenePlanRepository,
    ShotPlanRepository,
    ShotRepository,
    StyleBibleRepository,
)
from app.repositories.project_repository import ProjectRepository
from app.repositories.project_spec_repository import ProjectSpecRepository
from app.repositories.unit_of_work import UnitOfWork
from app.repositories.visual_bible_repository import (
    CharacterSetVersionRepository,
    NarrativeScriptVersionRepository,
)
# from app.services.brief_persistence_service import _quality_summary_to_text  # 旧流程：已停用
from app.services.state_transition_service import state_transition_service
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.path_planner import ArtifactStage


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class ShotPlanGenerationError(Exception):
    """Shot Plan 生成或落库异常。"""

    def __init__(self, message: str, code: str = "shot_plan_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Beat-snap 工具
# ---------------------------------------------------------------------------

def _snap_to_beat(ms: int, beat_map_sec: list[float], tolerance_ms: int = 400) -> int:
    """将毫秒时间戳 snap 到最近节拍点。

    Args:
        ms:             原始时间戳（毫秒）。
        beat_map_sec:   librosa 输出的节拍时间戳列表（单位：秒）。
        tolerance_ms:   偏差阈值，超出此范围不 snap（默认 400ms）。

    Returns:
        snap 后的毫秒时间戳；若 beat_map 为空或最近拍点超出容差则返回原值。
    """
    if not beat_map_sec:
        return ms
    # 转为毫秒列表
    beat_ms_list = [round(b * 1000) for b in beat_map_sec]
    nearest = min(beat_ms_list, key=lambda b: abs(b - ms))
    if abs(nearest - ms) <= tolerance_ms:
        return nearest
    return ms


# ---------------------------------------------------------------------------
# 字段映射辅助
# ---------------------------------------------------------------------------

_PACE_TO_ENERGY: dict[str, str] = {
    "slow": "low",
    "medium": "medium",
    "fast": "high",
}

_EXPLAINER_KEYWORDS = (
    "讲解", "解说", "介绍", "科普", "教程", "说明", "评测", "口播",
    "explainer", "tutorial", "education", "guide", "how to", "voiceover",
)
_AD_KEYWORDS = (
    "广告", "带货", "种草", "推广", "宣传", "品牌", "转化", "卖点", "口号",
    "ad", "ads", "promo", "promotion", "brand", "commercial", "campaign",
)
_DRAMA_KEYWORDS = (
    "剧情", "对白", "人物关系", "冲突", "故事", "表演", "角色",
    "drama", "cinematic story", "character", "scene",
)
_VISUAL_KEYWORDS = (
    "纯视觉", "氛围", "卡点", "情绪", "无对白", "抽象", "mv",
    "visual", "mood", "atmosphere", "abstract", "music video",
)

_VALID_SECTION_TYPES = frozenset([
    "intro", "verse", "chorus", "bridge", "outro", "pre_chorus", "interlude", "drop"
])


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lower_text = (text or "").lower()
    return any(keyword in lower_text for keyword in keywords)


def _classify_expression_type(user_prompt: str, brief_payload: dict | None = None) -> str:
    """根据需求文本粗分视频表达类型。"""
    brief_payload = brief_payload or {}
    text_parts = [
        user_prompt or "",
        str(brief_payload.get("title") or ""),
        str(brief_payload.get("summary") or ""),
        str(brief_payload.get("style_direction") or ""),
        str(brief_payload.get("narrative_mode") or ""),
    ]
    merged_text = " ".join(part for part in text_parts if part)

    if _contains_any(merged_text, _EXPLAINER_KEYWORDS):
        return "explainer"
    if _contains_any(merged_text, _AD_KEYWORDS):
        return "ad"
    if _contains_any(merged_text, _DRAMA_KEYWORDS):
        return "drama"
    if _contains_any(merged_text, _VISUAL_KEYWORDS):
        return "visual"
    return "general"


def _derive_motion_strategy(
    *,
    expression_type: str,
    shot_index: int,
    total_shots: int,
    action_description: str,
    dialogue: str,
    emotion: str,
    emotion_intensity: str,
) -> dict[str, str]:
    """从表达类型、情绪强度和动作描述派生运镜、节奏、视觉能量。"""
    action_text = (action_description or "").lower()
    emotion_text = (emotion or "").lower()
    has_dialogue = bool((dialogue or "").strip())
    intensity = (emotion_intensity or "medium").lower()

    pace = {
        "low": "slow",
        "medium": "medium",
        "high": "fast",
        "very_high": "very_fast",
    }.get(intensity, "medium")
    visual_energy = {
        "low": "low",
        "medium": "medium",
        "high": "high",
        "very_high": "high",
    }.get(intensity, "medium")

    if "静态" in action_text or "停留" in action_text or "观察" in action_text:
        base_camera = "locked medium shot with subtle breathing room"
    elif "特写" in action_text or "细节" in action_text or "产品" in action_text:
        base_camera = "macro close-up with controlled micro push-in"
    elif "转身" in action_text or "走" in action_text or "移动" in action_text:
        base_camera = "tracking follow with gentle lateral movement"
    elif "推进" in action_text or "靠近" in action_text:
        base_camera = "slow push-in with stable framing"
    else:
        base_camera = "steady medium shot with subtle push-in"

    if expression_type == "explainer":
        if has_dialogue:
            if shot_index == 0:
                base_camera = "steady medium introduction shot with soft push-in"
            elif shot_index == total_shots - 1:
                base_camera = "confident closing medium shot with gentle push-in"
            else:
                base_camera = "stable presenter shot with restrained push-in"
        else:
            base_camera = "insert close-up with measured tilt and detail emphasis"
            pace = "slow" if pace == "medium" else pace
            visual_energy = "low" if visual_energy == "medium" else visual_energy
    elif expression_type == "ad":
        if shot_index == 0:
            base_camera = "hero reveal push-in with polished product emphasis"
        elif shot_index == total_shots - 1:
            base_camera = "clean closing hero shot with crisp forward move"
        elif has_dialogue:
            base_camera = "confident showcase shot with rhythmic push-in"
        else:
            base_camera = "dynamic product insert with quick angle shift"
        if pace == "slow":
            pace = "medium"
        if visual_energy == "low":
            visual_energy = "medium"
    elif expression_type == "drama":
        if "紧张" in emotion_text or intensity in {"high", "very_high"}:
            base_camera = "handheld close tracking with urgent push-in"
        elif has_dialogue:
            base_camera = "performance-driven over-shoulder framing with gentle drift"
        else:
            base_camera = "observational medium-wide shot with restrained movement"
    elif expression_type == "visual":
        if intensity in {"high", "very_high"}:
            base_camera = "sweeping kinetic move with rhythmic motion arc"
        elif intensity == "low":
            base_camera = "floating wide shot with slow atmospheric drift"
        else:
            base_camera = "gliding cinematic move with smooth visual flow"
        if not has_dialogue and pace == "medium":
            pace = "slow"
            visual_energy = "low" if intensity == "low" else visual_energy
    else:
        if has_dialogue:
            base_camera = "steady narrative shot with moderate push-in"

    return {
        "camera_language": base_camera,
        "pace": pace,
        "visual_energy": visual_energy,
    }


def _derive_shot_audio_strategy(
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
        return {
            "has_dialogue": has_dialogue,
            "delivery_style": "cta" if has_dialogue and shot_index == total_shots - 1 else ("voiceover" if has_dialogue else "silent_visual"),
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


def _allowed_video_durations() -> list[int]:
    registry = get_provider_registry()
    return registry.list_supported_durations("video", enabled_only=True) or [4, 5, 6, 8, 10, 12, 15]


def _nearest_duration(duration_sec: float, allowed_durations: list[int]) -> int:
    if not allowed_durations:
        return max(1, int(round(duration_sec)))
    return min(allowed_durations, key=lambda candidate: (abs(candidate - duration_sec), candidate))


def _rebalance_durations_to_target(
    durations: list[int],
    target_duration_sec: int,
    allowed_durations: list[int],
) -> list[int]:
    """在支持档位内尽量逼近目标总时长。"""
    if not durations or not allowed_durations:
        return durations

    durations = list(durations)
    max_iterations = max(1, len(durations) * 8)

    for _ in range(max_iterations):
        diff = target_duration_sec - sum(durations)
        if diff == 0:
            break

        best_index = -1
        best_next = None
        best_score = None

        for index, current in enumerate(durations):
            current_pos = allowed_durations.index(current)
            candidate_positions: list[int] = []
            if diff > 0 and current_pos < len(allowed_durations) - 1:
                candidate_positions.append(current_pos + 1)
            if diff < 0 and current_pos > 0:
                candidate_positions.append(current_pos - 1)

            for candidate_pos in candidate_positions:
                candidate_value = allowed_durations[candidate_pos]
                delta = candidate_value - current
                score = (abs(diff - delta), abs(delta), candidate_value)
                if best_score is None or score < best_score:
                    best_score = score
                    best_index = index
                    best_next = candidate_value

        if best_index < 0 or best_next is None:
            break
        durations[best_index] = best_next

    return durations


def _apply_duration_plan(
    shot_list_data: list[dict[str, Any]],
    target_duration_sec: float,
    *,
    preserve_existing_timeline: bool = False,
) -> tuple[list[dict[str, Any]], float]:
    """按支持档位规范化 shot 时长，并重建时间轴。"""
    if not shot_list_data:
        return shot_list_data, target_duration_sec

    allowed_durations = _allowed_video_durations()
    target_total = int(round(target_duration_sec or 0))

    normalized_durations: list[int] = []
    requested_durations: list[float] = []
    for shot in shot_list_data:
        raw_duration = shot.get("duration_sec")
        if raw_duration in (None, "", 0):
            start_ms = int(shot.get("start_ms") or 0)
            end_ms = int(shot.get("end_ms") or 0)
            raw_duration = max(1, round((end_ms - start_ms) / 1000)) if end_ms > start_ms else 0
        try:
            requested_duration = float(raw_duration or 0)
        except (TypeError, ValueError):
            requested_duration = 0
        if requested_duration <= 0:
            requested_duration = max(allowed_durations[0], round(target_total / max(len(shot_list_data), 1)))
        requested_durations.append(requested_duration)
        normalized_durations.append(_nearest_duration(requested_duration, allowed_durations))

    if target_total <= 0:
        target_total = sum(normalized_durations)

    normalized_durations = _rebalance_durations_to_target(
        normalized_durations,
        target_total,
        allowed_durations,
    )

    cursor_ms = 0
    normalized_shots: list[dict[str, Any]] = []
    for index, shot in enumerate(shot_list_data):
        normalized = dict(shot)
        duration_sec = normalized_durations[index]
        normalized["duration_sec"] = duration_sec
        style_binding = list(normalized.get("style_binding") or [])
        if round(float(requested_durations[index]), 3) != float(duration_sec):
            style_binding.append({
                "type": "duration_normalization",
                "requested_duration_sec": round(float(requested_durations[index]), 3),
                "normalized_duration_sec": duration_sec,
                "allowed_durations_sec": allowed_durations,
            })
        normalized["style_binding"] = style_binding
        if preserve_existing_timeline and normalized.get("start_ms") is not None and normalized.get("end_ms") is not None:
            normalized_shots.append(normalized)
            continue
        normalized["start_ms"] = cursor_ms
        normalized["end_ms"] = cursor_ms + duration_sec * 1000
        cursor_ms = normalized["end_ms"]
        normalized_shots.append(normalized)

    return normalized_shots, round(sum(normalized_durations), 2)


def _build_visual_bible_map(
    narrative: Any,
    char_set_version: Any,
    *,
    character_refs: list | None = None,
    scene_refs: list | None = None,
) -> dict:
    """从 NarrativeScriptVersion + CharacterSetVersion 构建参考图绑定映射表。

    doc11 批次3：供 _map_shot_fields 使用。
    WP7 适配：优先从独立表 ORM 对象列表读取，JSONB 列已置空。

    Returns:
        {
          "scene_ref_map":     {scene_id: active_ref_asset_id},
          "character_ref_map": {character_id: active_ref_asset_id},
          "section_chars_map": {section_type: [char_id, ...]},
          "costume_ref_map":   {character_id: {section_type: {"costume_id": ..., "reference_asset_id": ...}}},
        }
        任一输入为 None 时返回空映射表。
    """
    result: dict = {
        "scene_ref_map": {},
        "character_ref_map": {},
        "section_chars_map": {},
        "costume_ref_map": {},
    }

    # --- 场景参考图 ---
    if scene_refs is not None:
        # WP7：从独立表 SceneReference ORM 对象读取
        for s in scene_refs:
            sid = getattr(s, "scene_id", None) or (s.get("scene_id") if isinstance(s, dict) else None)
            ref = getattr(s, "active_reference_asset_id", None) or (s.get("active_reference_asset_id") if isinstance(s, dict) else None)
            if sid and ref:
                result["scene_ref_map"][sid] = ref
    elif char_set_version is not None:
        # 向后兼容：从 JSONB 列读取（旧路径）
        for s in (char_set_version.scenes or []):
            sid = s.get("scene_id")
            ref = s.get("active_reference_asset_id")
            if sid and ref:
                result["scene_ref_map"][sid] = ref

    # --- 角色参考图 + 造型映射 ---
    if character_refs is not None:
        # WP7：从独立表 CharacterReference ORM 对象读取
        for c in character_refs:
            cid = getattr(c, "character_id", None) or (c.get("character_id") if isinstance(c, dict) else None)
            ref = getattr(c, "active_reference_asset_id", None) or (c.get("active_reference_asset_id") if isinstance(c, dict) else None)
            if cid and ref:
                result["character_ref_map"][cid] = ref
            # 造型映射（costumes 在独立表中仍为 JSONB list[dict]）
            costumes = getattr(c, "costumes", None) or (c.get("costumes") if isinstance(c, dict) else None) or []
            if cid and costumes:
                result["costume_ref_map"][cid] = {}
                for costume in costumes:
                    applies = costume.get("applies_to_sections") or [] if isinstance(costume, dict) else getattr(costume, "applies_to_sections", [])
                    ref_id = costume.get("reference_asset_id") if isinstance(costume, dict) else getattr(costume, "reference_asset_id", None)
                    costume_id = costume.get("costume_id") if isinstance(costume, dict) else getattr(costume, "costume_id", "")
                    for section in applies:
                        if ref_id:
                            result["costume_ref_map"][cid][section] = {
                                "costume_id": costume_id,
                                "reference_asset_id": ref_id,
                            }
    elif char_set_version is not None:
        # 向后兼容：从 JSONB 列读取（旧路径）
        for c in (char_set_version.characters or []):
            cid = c.get("character_id")
            ref = c.get("active_reference_asset_id")
            if cid and ref:
                result["character_ref_map"][cid] = ref
            costumes = c.get("costumes") or []
            if cid and costumes:
                result["costume_ref_map"][cid] = {}
                for costume in costumes:
                    for section in (costume.get("applies_to_sections") or []):
                        if costume.get("reference_asset_id"):
                            result["costume_ref_map"][cid][section] = {
                                "costume_id": costume["costume_id"],
                                "reference_asset_id": costume["reference_asset_id"],
                            }

    if narrative is not None:
        for sec in (narrative.section_mapping or []):
            sec_type = sec.get("section_type")
            chars = sec.get("characters") or []
            if sec_type:
                # 同一段落可能有多条，取合并后的字符算集
                existing = result["section_chars_map"].get(sec_type, [])
                merged = list(dict.fromkeys(existing + [c for c in chars if c]))
                result["section_chars_map"][sec_type] = merged
    return result


def _map_shot_fields(raw: dict[str, Any], idx: int, ref_binding_map: dict | None = None) -> dict[str, Any]:
    """将 LLM 输出的 ShotSemanticSpec 字段映射到 ORM 字段。"""
    shot_index: int = int(raw.get("shot_index") or idx)

    # 时间坐标
    start_ms: int = int(raw.get("start_ms") or 0)
    end_ms: int = int(raw.get("end_ms") or 0)
    duration_sec = raw.get("duration_sec") or 0

    # 若 start_ms/end_ms 缺失但有 duration_sec，用 duration_sec 估算
    if end_ms <= start_ms and duration_sec:
        end_ms = start_ms + int(float(duration_sec) * 1000)
    duration_ms = max(int(end_ms - start_ms), int(float(duration_sec) * 1000))

    # section_type
    section_type = raw.get("scene_type") or raw.get("section_type") or "verse"
    if section_type not in _VALID_SECTION_TYPES:
        section_type = "verse"

    # shot_type（来自 shot_role）
    shot_type = raw.get("shot_role") or raw.get("shot_type") or "medium"

    # visual_energy（来自 pace）
    pace = raw.get("pace") or ""
    visual_energy = (
        raw.get("visual_energy")
        or _PACE_TO_ENERGY.get(pace.lower(), "medium")
    )

    # doc11 批次3修复：构建富结构 character_binding（支持多角色参考图绑定）
    character_binding: dict = {}
    if ref_binding_map:
        scene_id_val = raw.get("scene_id")
        scene_ref = ref_binding_map["scene_ref_map"].get(scene_id_val) if scene_id_val else None

        # 收集该段落所有角色及其参考图（不再只取第一个，保留完整列表以支持多角色场景）
        char_ids = ref_binding_map["section_chars_map"].get(section_type, [])
        all_char_refs: list[str] = [
            ref_binding_map["character_ref_map"][cid]
            for cid in char_ids
            if ref_binding_map["character_ref_map"].get(cid)
        ]

        character_binding = {
            "character_ids": char_ids,
            "character_ref_asset_ids": all_char_refs,                          # 多角色支持（新字段）
            "character_ref_asset_id": all_char_refs[0] if all_char_refs else None,  # 向后兼容旧字段
            "scene_ref_asset_id": scene_ref,
        }

        # 造型匹配（多造型支持）
        costume_match = None
        costume_ref_map = ref_binding_map.get("costume_ref_map", {})
        for cid in char_ids:
            match = costume_ref_map.get(cid, {}).get(section_type)
            if match:
                costume_match = match
                break

        character_binding["costume_id"] = costume_match["costume_id"] if costume_match else None
        character_binding["costume_ref_asset_id"] = costume_match["reference_asset_id"] if costume_match else None
        # 当有造型参考图时，优先使用造型图替代统一的 active_reference_asset_id
        if costume_match and costume_match.get("reference_asset_id"):
            character_binding["character_ref_asset_id"] = costume_match["reference_asset_id"]

    style_binding = list(raw.get("style_binding") or [])
    audio_strategy = raw.get("audio_strategy")
    if isinstance(audio_strategy, dict):
        style_binding.append({"type": "audio_strategy", "value": audio_strategy})

    return {
        "shot_index": shot_index,
        "scene_id": raw.get("scene_id"),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_ms": duration_ms,
        "section_type": section_type,
        "lyric_text": raw.get("lyric_text"),
        "dialogue": raw.get("dialogue") or None,
        "emotion": raw.get("emotion"),
        "emotion_intensity": raw.get("emotion_intensity") or None,
        "subject": raw.get("subject") or None,
        "location": raw.get("location") or None,
        "shot_type": shot_type,
        "camera_language": raw.get("camera_language"),
        "visual_energy": visual_energy,
        "lipsync_required": bool(raw.get("lipsync_required", False)),
        "character_binding": character_binding,
        "style_binding": style_binding,
        "status": "planned",
    }


# ---------------------------------------------------------------------------
# ShotPlanPersistenceService
# ---------------------------------------------------------------------------

class ShotPlanPersistenceService:
    """Shot Plan 生成与落库服务。"""

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def generate_and_save(
        self,
        project_id: str,
        user_id: str,
    ) -> tuple[ScenePlanVersion, ShotPlanVersion, list[Shot]]:
        """执行完整 shot plan 生成流程并落库。

        Args:
            project_id:  目标项目 ID。
            user_id:     当前用户 ID（项目归属校验）。

        Returns:
            (ScenePlanVersion, ShotPlanVersion, List[Shot]) — 新建并激活的版本和 Shot 行。

        Raises:
            ShotPlanGenerationError: 前置条件不满足、状态非法、生成失败。
        """
        logger = get_project_logger(project_id, module="services.shot_plan_persistence")

        # ---- 步骤 1: 读取项目上下文 ----------------------------------------
        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise ShotPlanGenerationError("项目不存在", code="project_not_found")

            allowed_stages = {
                ProjectStage.BRIEF_READY.value,
                ProjectStage.NARRATIVE_READY.value,       # doc11: narrative 确认后可跳过 visual_bible
                ProjectStage.VISUAL_BIBLE_READY.value,    # doc11: 正常流程，visual_bible 确认后生成
                ProjectStage.SHOT_PLAN_READY.value,       # 允许重新生成
            }
            if project.current_stage not in allowed_stages:
                raise ShotPlanGenerationError(
                    f"当前阶段 {project.current_stage!r} 不允许生成 shot plan",
                    code="invalid_stage",
                )

            # 读取 active brief
            brief = await CreativeBriefRepository(session).get_active(project_id)
            if brief is None:
                raise ShotPlanGenerationError("未找到 active brief", code="no_brief")

            # 读取 active style
            style = await StyleBibleRepository(session).get_active(project_id)
            if style is None:
                raise ShotPlanGenerationError("未找到 active style", code="no_style")

            # 读取 ProjectSpec
            spec = await ProjectSpecRepository(session).get_active(project_id)
            target_duration_sec: float = 0.0
            performance_ratio: float = float(brief.performance_ratio or 0.4)
            if spec:
                # 新流程：优先从 output_config.target_duration_sec 读取
                _oc_dur = float((spec.output_config or {}).get("target_duration_sec", 0) or 0)
                if _oc_dur > 0:
                    target_duration_sec = _oc_dur
                else:
                    # 旧流程兼容：从音频时间区间计算（新流程此值为 0）
                    target_duration_sec = float((spec.audio_end_sec or 0) - (spec.audio_start_sec or 0))

            # 新流程：shot plan 不再依赖音频分析，时长从 creative brief 或 ProjectSpec.output_config 获取
            audio_analysis_summary = ""  # 旧流程（音乐MV模式）：已停用
            # 当 audio_end_sec=0（用户未手动设置，trim 工具按全曲处理）时，
            # 从 AudioAnalysisVersion.raw_payload['signal']['duration_sec'] 取实际时长。
            # 旧流程（音乐MV模式）：已停用
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

            if target_duration_sec <= 0:
                raise ShotPlanGenerationError(
                    "未找到 active ProjectSpec 或无法获取有效目标时长，请在项目设置中指定 target_duration_sec。",
                    code="no_spec_or_no_duration",
                )

            brief_ref = await build_ref_from_asset_latest(
                project_id,
                artifact_type="creative_brief",
                version_no=brief.version_no,
                prefix="creative_brief",
                summary=brief.summary or "",
            )
            style_ref = await build_ref_from_asset_latest(
                project_id,
                artifact_type="style_bible",
                version_no=style.version_no,
                prefix="style_bible",
                summary=getattr(style, "lighting_style", "") or "style_bible",
            )

            # 旧流程（音乐MV模式）：已停用
            # if project.active_audio_analysis_version_id:
            #     aa = await AudioAnalysisRepository(session).get_by_id(
            #         project.active_audio_analysis_version_id
            #     )
            #     if aa:
            #         audio_ref = await build_ref_from_asset_latest(
            #             project_id,
            #             artifact_type="audio_analysis",
            #             version_no=aa.version_no,
            #             prefix="audio_analysis",
            #             summary=_quality_summary_to_text(aa.quality_summary or {}),
            #         )
            #         beat_map_sec = aa.beat_map or []
            audio_ref = None
            beat_map_sec: list[float] = []

            # doc11 批次3：读取 active NarrativeScript + CharacterSetVersion（可选）
            narrative = await NarrativeScriptVersionRepository(session).get_active(project_id)
            char_set_version = await CharacterSetVersionRepository(session).get_active(project_id)

            # 构建 narrative_ref 传递给 phase-2
            narrative_ref = None
            if narrative:
                narrative_ref = await build_ref_from_asset_latest(
                    project_id,
                    artifact_type="narrative_script",
                    version_no=narrative.version_no,
                    prefix="narrative_script",
                    summary=narrative.story_arc or "",
                )

            next_shot_plan_version_no = await ShotPlanRepository(session).get_next_version_no(project_id)

        # ---- 步骤 2: 计算 max_shots
        # 改为按可变 shot 时长估算上限，不再假设固定 10s/shot。
        # 使用 6s 作为较积极的平均值，只作为上限提示，不是最终落地时长。
        max_shots = max(4, min(80, int(target_duration_sec / 6) + 2))

        # ---- 步骤 3: 调用 CreativePlanningAgent.run_phase2() ----------------
        logger.info("开始生成 shot plan", event_type="shot_plan_generation_start")
        agent = CreativePlanningAgent()
        phase2_result = await agent.run_phase2({
            "project_id": project_id,
            "brief_ref": brief_ref,
            "style_ref": style_ref,
            "audio_ref": audio_ref,
            "narrative_script_ref": narrative_ref,
            "target_duration_sec": target_duration_sec,
            "allowed_shot_durations_sec": _allowed_video_durations(),
            "max_shots": max_shots,
            "performance_ratio": performance_ratio,
            "version_no": next_shot_plan_version_no,
        })

        # 从 ArtifactRef 读回 shot plan 内容
        shot_plan_ref = phase2_result.get("shot_plan_ref") or {}
        try:
            shot_artifact = await read_artifact(shot_plan_ref) if shot_plan_ref.get("artifact_id") else {}
        except Exception as exc:
            logger.warning(
                f"读取 shot_plan ArtifactRef 失败: {exc!r}，使用兜底结构",
                event_type="shot_plan_artifact_read_failed",
            )
            shot_artifact = {}

        scene_plan_data: list = shot_artifact.get("scene_plan") or []
        shot_list_data: list = shot_artifact.get("shot_plan") or []

        # ---- 步骤 4: 落库 + 激活 + 快照 + 状态推进 -------------------------
        async with UnitOfWork() as uow2:
            scene_version, shot_version, shots = await self._persist(
                session=uow2.session,
                project_id=project_id,
                scene_plan_data=scene_plan_data,
                shot_list_data=shot_list_data,
                target_duration_sec=target_duration_sec,
                shot_plan_audio_strategy=(narrative.raw_payload or {}).get("audio_strategy") if narrative is not None else None,
                narrative=narrative,
                char_set_version=char_set_version,
                beat_map_sec=beat_map_sec,
            )

        # BUG-09 修复：_persist() 写入本地的是 beat-snap 对齐后的最终版本，
        # 但当时只用了 LocalArtifactStore.write_json()，无 MinIO 上传和 Asset 记录。
        # Agent 的 write_artifact_tool 写入的是 beat-snap 前原稿，不是最终版本。
        # 在事务提交后，读取就写的本地文件，重上传一份到 MinIO + 建 Asset。
        try:
            _store = LocalArtifactStore(project_id)
            _latest = _store.latest_in_stage(ArtifactStage.SHOT_PLAN, prefix="shot_plan")
            if _latest and _latest.exists():
                _content = _store.read_json(_latest)
                await write_artifact(
                    _content,
                    project_id=project_id,
                    artifact_type="shot_plan",
                    version_no=shot_version.version_no,
                    summary=f"{len(shots)} shots",
                )
                logger.info(
                    f"shot plan 最终版本已上传 MinIO: version_no={shot_version.version_no}",
                    event_type="shot_plan_minio_uploaded",
                )
        except Exception as _exc:
            logger.warning(
                f"shot plan MinIO 上传失败（不影响主流程）: {_exc!r}",
                event_type="shot_plan_minio_upload_failed",
            )

        logger.info(
            f"shot plan 生成完成: scene_version={scene_version.id!r} "
            f"shot_version={shot_version.id!r} shots={len(shots)}",
            event_type="shot_plan_generation_done",
        )
        return scene_version, shot_version, shots

    # ------------------------------------------------------------------
    # 落库核心（单 UoW 事务）
    # ------------------------------------------------------------------

    async def _persist(
        self,
        *,
        session: AsyncSession,
        project_id: str,
        scene_plan_data: list[dict],
        shot_list_data: list[dict],
        target_duration_sec: float,
        shot_plan_audio_strategy: dict[str, Any] | None = None,
        narrative: Any = None,
        char_set_version: Any = None,
        beat_map_sec: list[float] | None = None,
    ) -> tuple[ScenePlanVersion, ShotPlanVersion, list[Shot]]:
        """落库 + 激活 + 写快照 + 推进状态（单事务）。"""
        logger = get_project_logger(project_id, module="services.shot_plan_persistence")
        scene_repo = ScenePlanRepository(session)
        shot_plan_repo = ShotPlanRepository(session)
        shot_repo = ShotRepository(session)
        proj_repo = ProjectRepository(session)

        project = await proj_repo.get_by_id(project_id)

        # ---- 若 shot_list_data 为空，生成一个最小占位 shot -------------------
        if not shot_list_data:
            shot_list_data = [
                {
                    "shot_index": 0,
                    "scene_type": "verse",
                    "shot_role": "atmosphere",
                    "emotion": "neutral",
                    "camera_language": "static",
                    "pace": "medium",
                    "duration_sec": target_duration_sec,
                    "start_ms": 0,
                    "end_ms": int(target_duration_sec * 1000),
                    "lipsync_required": False,
                }
            ]

        shot_list_data, target_duration_sec = _apply_duration_plan(
            shot_list_data,
            target_duration_sec,
        )

        # ---- ScenePlan 版本 -----------------------------------------------
        await scene_repo.deactivate_all(project_id)
        scene_version_no = await scene_repo.get_next_version_no(project_id)
        scene_version = ScenePlanVersion(
            project_id=project_id,
            version_no=scene_version_no,
            raw_payload={"scenes": scene_plan_data},
            is_active=True,
        )
        await scene_repo.add(scene_version)
        await session.flush()
        await session.refresh(scene_version)

        # ---- ShotPlan 版本 -----------------------------------------------
        await shot_plan_repo.deactivate_all(project_id)
        shot_plan_version_no = await shot_plan_repo.get_next_version_no(project_id)
        shot_version = ShotPlanVersion(
            project_id=project_id,
            version_no=shot_plan_version_no,
            raw_payload={
                "shots": shot_list_data,
                "audio_strategy": shot_plan_audio_strategy or {},
            },
            is_active=True,
        )
        await shot_plan_repo.add(shot_version)
        await session.flush()
        await session.refresh(shot_version)

        # ---- 批量写入 shots 行 --------------------------------------------
        shots: list[Shot] = []
        spec_snapshots: list[dict] = []  # ShotSemanticSpec，写入本地快照

        # 构建参考图绑定映射表（doc11 批次3）
        # WP7 适配：从独立表查询角色/场景参考图数据（JSONB 列已置空）
        from app.repositories.character_reference_repository import CharacterReferenceRepository
        from app.repositories.scene_reference_repository import SceneReferenceRepository
        _char_ref_rows: list = []
        _scene_ref_rows: list = []
        if char_set_version is not None:
            _char_ref_rows = await CharacterReferenceRepository(session).list_by_version(char_set_version.id)
            _scene_ref_rows = await SceneReferenceRepository(session).list_by_version(char_set_version.id)

        ref_binding_map = _build_visual_bible_map(
            narrative, char_set_version,
            character_refs=_char_ref_rows,
            scene_refs=_scene_ref_rows,
        )

        _beat_map = beat_map_sec or []

        for idx, raw_shot in enumerate(shot_list_data):
            mapped = _map_shot_fields(raw_shot, idx, ref_binding_map)

            if mapped["duration_ms"] <= 0:
                logger.warning(
                    f"Shot[{idx}] 时长异常: duration_ms={mapped['duration_ms']}",
                    event_type="shot_duration_invalid",
                )

            # Beat-snap：将 start_ms / end_ms snap 到最近节拍点（容差 400ms）
            if _beat_map:
                snapped_start = _snap_to_beat(mapped["start_ms"], _beat_map)
                snapped_end = _snap_to_beat(mapped["end_ms"], _beat_map)
                # 保证 snap 后 end > start
                if snapped_end > snapped_start:
                    logger.debug(
                        f"Shot[{idx}] beat-snap: start {mapped['start_ms']}→{snapped_start}ms "
                        f"end {mapped['end_ms']}→{snapped_end}ms",
                        event_type="shot_beat_snap",
                    )
                    mapped["start_ms"] = snapped_start
                    mapped["end_ms"] = snapped_end
                    mapped["duration_ms"] = snapped_end - snapped_start

            shot = Shot(
                project_id=project_id,
                shot_plan_version_id=shot_version.id,
                **mapped,
            )
            await shot_repo.add(shot)
            shots.append(shot)
            # 保留完整 ShotSemanticSpec（原始 + 映射后字段）
            spec_snapshots.append({**raw_shot, **mapped})

        logger.info(
            f"Shot 字段映射与落库完成: {len(shots)} 条 shot",
            event_type="shot_persist_mapped",
        )

        if shots:
            await session.flush()
            for s in shots:
                await session.refresh(s)

        # ---- 更新项目 active 指针 ----------------------------------------
        project.active_scene_plan_version_id = scene_version.id
        project.active_shot_plan_version_id = shot_version.id
        session.add(project)

        # ---- 状态推进 → shot_plan_ready ------------------------------------
        if project.current_stage != ProjectStage.SHOT_PLAN_READY.value:
            await state_transition_service.advance_project(
                session, project, ProjectStage.SHOT_PLAN_READY
            )

        # ---- 写本地快照（含 ShotSemanticSpec）--------------------------------
        store = LocalArtifactStore(project_id)
        store.write_json(
            ArtifactStage.SHOT_PLAN,
            "shot_plan",
            {"shot_plan": shot_list_data, "scene_plan": scene_plan_data},
            version=shot_plan_version_no,
        )
        # ShotSemanticSpec 单独存一份（供后续 Prompt 编译服务直接读取）
        store.write_json(
            ArtifactStage.SHOT_PLAN,
            "shot_semantic_specs",
            {"specs": spec_snapshots},
            version=shot_plan_version_no,
        )

        return scene_version, shot_version, shots

    # ------------------------------------------------------------------
    # doc 21 §3.4 新流程：从 narrative_script 自动派生 shot plan
    # 不再调用 LLM，shot 数由 brief.extension.total_shots_generated 决定
    # ------------------------------------------------------------------

    async def derive_from_narrative(
        self,
        project_id: str,
        user_id: str,
    ) -> tuple[ScenePlanVersion, ShotPlanVersion, list[Shot]]:
        """新流程（doc 21 §3.4）：从 narrative_script 直接派生 shot plan，不调 LLM。

        每个 narrative shot 直接转成 ORM Shot：
          - duration_ms 按 narrative 产出的 duration_sec 逐段累加
          - start_ms / end_ms 按实际 duration_sec 顺序排列
          - subject = action_description
          - location = scene_description
          - emotion / emotion_intensity 复用 narrative
          - section_type = "verse"（默认，AI 视频无音乐 section 概念）
          - shot_type = "medium"（默认，新流程不区分景别）
          - character_binding = {"character_ids": shot.characters_in_shot}

        Args:
            project_id: 目标项目 ID
            user_id:    当前用户 ID

        Returns:
            (ScenePlanVersion, ShotPlanVersion, list[Shot])

        Raises:
            ShotPlanGenerationError: 项目不存在 / 无 narrative / narrative 无 shots
        """
        logger = get_project_logger(project_id, module="services.shot_plan_persistence")

        # ---- 步骤 1: 读取项目 + narrative + brief/spec ----------------------------------------
        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise ShotPlanGenerationError("项目不存在", code="project_not_found")

            narrative = await NarrativeScriptVersionRepository(session).get_active(project_id)
            if narrative is None:
                raise ShotPlanGenerationError(
                    "未找到 active narrative_script，请先生成剧本",
                    code="no_narrative_script",
                )

            narr_payload = narrative.raw_payload or {}
            narrative_shots: list[dict] = narr_payload.get("shots") or []
            if not narrative_shots:
                raise ShotPlanGenerationError(
                    "narrative_script.raw_payload 不含 shots 字段（doc 21 §2.3 新流程）",
                    code="empty_narrative_shots",
                )

            brief = await CreativeBriefRepository(session).get_active(project_id)
            spec = await ProjectSpecRepository(session).get_active(project_id)

        # ---- 步骤 2: 构造 shot_list_data ----------------------------------------
        brief_payload = {}
        if brief is not None:
            brief_payload = brief.raw_payload or {}
            if isinstance(brief_payload.get("creative_brief"), dict):
                brief_payload = brief_payload.get("creative_brief") or {}
        user_prompt = getattr(spec, "user_prompt", "") or ""
        expression_type = _classify_expression_type(user_prompt, brief_payload)

        shot_list_data: list[dict] = []
        for idx, ns in enumerate(narrative_shots):
            shot_audio_strategy = ns.get("audio_strategy") or _derive_shot_audio_strategy(
                expression_type=expression_type,
                shot_index=int(ns.get("shot_index", idx)),
                total_shots=len(narrative_shots),
                dialogue=str(ns.get("dialogue") or ""),
            )
            motion = _derive_motion_strategy(
                expression_type=expression_type,
                shot_index=int(ns.get("shot_index", idx)),
                total_shots=len(narrative_shots),
                action_description=str(ns.get("action_description") or ""),
                dialogue=str(ns.get("dialogue") or ""),
                emotion=str(ns.get("emotion") or ""),
                emotion_intensity=str(ns.get("emotion_intensity") or "medium"),
            )
            shot_list_data.append({
                "shot_index": int(ns.get("shot_index", idx)),
                "scene_id": f"scene_{(idx // 3) + 1:03d}",
                "scene_type": "verse",
                "shot_role": "narrative",
                "subject": ns.get("action_description") or ns.get("end_frame_description") or "",
                "location": ns.get("scene_description") or "",
                "dialogue": ns.get("dialogue") or "",
                "audio_strategy": shot_audio_strategy,
                "emotion": ns.get("emotion") or "neutral",
                "emotion_intensity": ns.get("emotion_intensity") or "medium",
                "camera_language": motion["camera_language"],
                "pace": motion["pace"],
                "visual_energy": motion["visual_energy"],
                "duration_sec": int(ns.get("duration_sec", 8)),
                "lipsync_required": False,
            })

        shot_list_data, target_duration_sec = _apply_duration_plan(
            shot_list_data,
            float((spec.output_config or {}).get("target_duration_sec", 0) or 0) if spec is not None else 0.0,
        )

        # ---- 步骤 3: 构造 scene_plan_data（当前版本：每张九宫格 3 个 shot）-------------
        scene_plan_data: list[dict] = []
        grid_count = max(1, (len(shot_list_data) + 2) // 3)
        for g in range(grid_count):
            scene_plan_data.append({
                "scene_id": f"scene_{g + 1:03d}",
                "scene_name": f"九宫格 #{g + 1}",
                "shot_indices": list(
                    range(g * 3, min((g + 1) * 3, len(shot_list_data)))
                ),
            })

        # ---- 步骤 4: 落库（复用 _persist，但不传 narrative/char_set_version）-----
        async with UnitOfWork() as uow2:
            scene_version, shot_version, shots = await self._persist(
                session=uow2.session,
                project_id=project_id,
                scene_plan_data=scene_plan_data,
                shot_list_data=shot_list_data,
                target_duration_sec=target_duration_sec,
                shot_plan_audio_strategy=narr_payload.get("audio_strategy") or {},
                narrative=None,        # 新流程不依赖旧 narrative.section_mapping
                char_set_version=None, # 新流程不用 visual_bible（doc 21 决策 D1）
                beat_map_sec=[],
            )

        logger.info(
            f"shot plan 派生完成: shots={len(shots)} grid_count={grid_count} "
            f"target_duration={target_duration_sec:.1f}s expression_type={expression_type!r}",
            event_type="shot_plan_derived_from_narrative",
        )
        return scene_version, shot_version, shots

    async def save_from_data(
        self,
        project_id: str,
        scene_plan_data: list,
        shot_list_data: list,
        target_duration_sec: float,
    ) -> tuple["ScenePlanVersion", "ShotPlanVersion", "list[Shot]"]:
        """Sub-Agent 完成生成后调用：持久化 shot plan 数据，不做 LLM 生成。

        dispatch_agent() 在 CreativePlanningAgent.run_phase2() 返回后调用此方法。
        内部会重新加载 narrative + char_set_version 以支持参考图绑定。
        """
        logger = get_project_logger(project_id, module="services.shot_plan_persistence")
        logger.info(
            f"save_from_data 开始: scenes={len(scene_plan_data)} shots={len(shot_list_data)} "
            f"target_duration={target_duration_sec:.1f}s",
            event_type="shot_plan_save_from_data_start",
        )
        from app.repositories.visual_bible_repository import (  # noqa: PLC0415
            NarrativeScriptVersionRepository, CharacterSetVersionRepository,
        )
        async with UnitOfWork() as uow:
            session = uow.session
            narrative = await NarrativeScriptVersionRepository(session).get_active(project_id)
            char_set_version = await CharacterSetVersionRepository(session).get_active(project_id)
            # 加载 beat_map 以支持 beat-snap
            beat_map_sec: list[float] = []
            from app.repositories.project_repository import ProjectRepository  # noqa: PLC0415
            project = await ProjectRepository(session).get_by_id(project_id)
            # 旧流程（音乐MV模式）：已停用
            # if project and project.active_audio_analysis_version_id:
            #     aa = await AudioAnalysisRepository(session).get_by_id(
            #         project.active_audio_analysis_version_id
            #     )
            #     if aa:
            #         beat_map_sec = aa.beat_map or []
            return await self._persist(
                session=session,
                project_id=project_id,
                scene_plan_data=scene_plan_data,
                shot_list_data=shot_list_data,
                target_duration_sec=target_duration_sec,
                shot_plan_audio_strategy=(narrative.raw_payload or {}).get("audio_strategy") if narrative is not None else None,
                narrative=narrative,
                char_set_version=char_set_version,
                beat_map_sec=beat_map_sec,
            )
