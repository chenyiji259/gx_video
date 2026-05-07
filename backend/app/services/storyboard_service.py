"""Storyboard 生成服务（1x3 三宫格架构）。

来源文档：doc 21 §3 + §5 + §6

职责：
  按 brief.extension.grid_count 串行生成多张三宫格大图，每张：
    1. 从 narrative_script 取出 3 个 cell 对应的 shot 描述
    2. 编译三宫格 prompt（PromptCompilerService.compile_nine_grid_prompt）
    3. 调用 ImageGenerationTool.generate_nine_grid 生成三宫格大图
    4. 调用 ImageGenerationTool.split_and_persist_grid 切分 3 张 cell
    5. 落库 StoryboardFrame：1 条大图 + 3 条 cell
    6. 推送 4 个事件（doc 21 §6.1）：
       storyboard.grid.generating / generated / split_done / all_grids_completed

当前版本说明：
  每张三宫格对应一个 shot 的起始 / 中间 / 结尾三帧。
"""
from __future__ import annotations

import time
from typing import Any

from app.core.config import get_config
from app.core.logging import get_project_logger
from app.domain.states import ProjectStage
from app.models.prompt_bundle import PromptBundleModel
from app.models.storyboard import StoryboardFrame, StoryboardVersion
from app.providers.image.base import ImageGenerationError
from app.repositories.asset_repository import AssetRepository
from app.repositories.planning_repositories import (
    CreativeBriefRepository,
    ShotPlanRepository,
    ShotRepository,
)
from app.repositories.project_repository import ProjectRepository
from app.repositories.storyboard_repositories import (
    StoryboardFrameRepository,
    StoryboardVersionRepository,
)
from app.repositories.unit_of_work import UnitOfWork
from app.repositories.visual_bible_repository import NarrativeScriptVersionRepository
from app.schemas.event import ProjectEvent
from app.schemas.project import CreativeBriefExtension
from app.services.asset_access_service import build_asset_access_url, build_asset_access_url_map
from app.services.concurrency_guard_service import ConcurrencyError, concurrency_guard
from app.services.event_log_service import event_log_service
from app.services.output_spec_service import (
    TALKING_HEAD_LAYOUT,
    TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
)
from app.services.prompt_compiler_service import PromptCompilerService
from app.services.regeneration_context_service import regeneration_context_service
from app.services.shot_plan_persistence_service import ShotPlanPersistenceService
from app.services.state_transition_service import state_transition_service
from app.services.talking_head_prompt_service import TalkingHeadPromptService, segment_time_range
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.path_planner import ArtifactStage
from app.tools.image_generation_tool import ImageGenerationTool


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class StoryboardGenerationError(Exception):
    """Storyboard 生成业务异常。"""

    def __init__(self, message: str, code: str = "storyboard_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# StoryboardService（三宫格架构）
# ---------------------------------------------------------------------------

class StoryboardService:
    """三宫格 storyboard 服务：brief.extension + narrative_script → N 张三宫格 + 切分 + 落库。"""

    def __init__(self) -> None:
        self._compiler = PromptCompilerService()
        self._talking_head_compiler = TalkingHeadPromptService()
        self._image_tool = ImageGenerationTool()
        self._shot_plan_service = ShotPlanPersistenceService()

    async def generate_and_save(
        self,
        project_id: str,
        user_id: str,
    ) -> StoryboardVersion:
        """主入口：执行三宫格 storyboard 生成流程。

        Args:
            project_id: 目标项目 ID
            user_id:    当前用户 ID

        Returns:
            新建并激活的 StoryboardVersion 对象

        Raises:
            StoryboardGenerationError: 前置条件不满足、生成失败等
        """
        try:
            async with concurrency_guard.project_lock(project_id, timeout_sec=1800):
                return await self._generate_locked(project_id, user_id)
        except ConcurrencyError as exc:
            raise StoryboardGenerationError(
                str(exc), code="concurrency_conflict"
            ) from exc

    async def _generate_locked(
        self,
        project_id: str,
        user_id: str,
    ) -> StoryboardVersion:
        """加锁后的实际执行体（doc 21 §3 + §6 增量推送）。"""
        logger = get_project_logger(project_id, module="services.storyboard")

        # ---- 步骤 1: 读取并校验项目上下文 -------------------------------
        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise StoryboardGenerationError("项目不存在", code="project_not_found")

            allowed_stages = {
                ProjectStage.NARRATIVE_READY.value,    # 新流程：narrative 直接进 storyboard
                ProjectStage.SHOT_PLAN_READY.value,    # 兼容旧流程
                ProjectStage.STORYBOARD_READY.value,   # 允许重新生成
                ProjectStage.FAILED.value,             # 允许分镜生成失败后手动重试
            }
            if project.current_stage not in allowed_stages:
                raise StoryboardGenerationError(
                    f"当前阶段 {project.current_stage!r} 不允许生成 storyboard",
                    code="invalid_stage",
                )

            # 读取 active brief.extension（doc 21 §1.1：extension 是 raw_payload 子字段）
            brief = await CreativeBriefRepository(session).get_active(project_id)
            if brief is None:
                raise StoryboardGenerationError("未找到 active brief", code="no_brief")

            brief_payload = brief.raw_payload or {}
            if isinstance(brief_payload.get("creative_brief"), dict):
                brief_payload = brief_payload.get("creative_brief") or {}
            ext_dict = brief_payload.get("extension") or {}
            try:
                ext = CreativeBriefExtension(**ext_dict)
            except Exception as exc:  # noqa: BLE001
                raise StoryboardGenerationError(
                    f"brief.raw_payload.extension 字段无效: {exc}",
                    code="invalid_extension",
                ) from exc
            if ext.storyboard_layout == TALKING_HEAD_LAYOUT:
                return await self._generate_talking_head_story_overview(
                    project_id=project_id,
                    user_id=user_id,
                    project=project,
                    ext=ext,
                    logger=logger,
                )
            if ext.storyboard_layout != "1x3_triptych" or ext.grid_count != max(1, ext.total_shots_generated):
                ext = ext.model_copy(
                    update={
                        "storyboard_layout": "1x3_triptych",
                        "grid_count": max(1, ext.total_shots_generated),
                    }
                )

            # 读取 active narrative_script（doc 21 §2.3：含每个 shot 的 frame description）
            narrative = await NarrativeScriptVersionRepository(session).get_active(
                project_id
            )
            if narrative is None:
                raise StoryboardGenerationError(
                    "未找到 active narrative_script，请先生成剧本",
                    code="no_narrative_script",
                )
            narr_payload = narrative.raw_payload or {}
            narrative_shots: list[dict] = narr_payload.get("shots") or []
            if len(narrative_shots) < ext.total_shots_generated:
                raise StoryboardGenerationError(
                    f"narrative_shots 数量 ({len(narrative_shots)}) 少于期望 "
                    f"({ext.total_shots_generated})",
                    code="insufficient_narrative_shots",
                )
            current_storyboard = await StoryboardVersionRepository(session).get_active(
                project_id
            )
            current_storyboard_payload = (
                current_storyboard.raw_payload if current_storyboard is not None else None
            )
            current_storyboard_version_id = (
                current_storyboard.id if current_storyboard is not None else None
            )

        # ---- 步骤 2: 确保 shot_plan 存在（自动派生）---------------------
        async with UnitOfWork() as uow:
            shot_plan = await ShotPlanRepository(uow.session).get_active(project_id)

        if shot_plan is None:
            logger.info(
                "未找到 active shot_plan，从 narrative_script 自动派生",
                event_type="storyboard_derive_shot_plan",
            )
            _, shot_plan_obj, _ = await self._shot_plan_service.derive_from_narrative(
                project_id, user_id,
            )
            shot_plan_version_id = shot_plan_obj.id
        else:
            shot_plan_version_id = shot_plan.id

        # ---- 步骤 3: 读取所有 shots（按 shot_index 排序）----------------
        async with UnitOfWork() as uow:
            all_shots = await ShotRepository(uow.session).list_by_project(project_id)
        all_shots = sorted(all_shots, key=lambda s: s.shot_index)
        shot_id_by_index: dict[int, str] = {s.shot_index: s.id for s in all_shots}

        grid_count = ext.grid_count
        total_shots = ext.total_shots_generated

        logger.info(
            f"三宫格 storyboard 生成开始: grid_count={grid_count} "
            f"total_shots={total_shots}",
            event_type="storyboard_generation_start",
        )
        previous_prompt = await self._latest_storyboard_prompt(
            project_id=project_id,
            storyboard_version_id=current_storyboard_version_id,
        )
        feedback = await regeneration_context_service.get_latest_feedback(
            project_id,
            decision_type="confirm_storyboard",
            target_entity_id=current_storyboard_version_id,
        )
        regeneration_prompt_section = (
            regeneration_context_service.build_storyboard_prompt_section(
                feedback=feedback,
                current_storyboard_payload=current_storyboard_payload,
                previous_prompt=previous_prompt,
            )
        )

        # ---- 步骤 4: 创建 StoryboardVersion 主记录 ---------------------
        async with UnitOfWork() as uow:
            sv_repo = StoryboardVersionRepository(uow.session)
            await sv_repo.deactivate_all(project_id)
            version_no = await sv_repo.get_next_version_no(project_id)
            storyboard_version = StoryboardVersion(
                project_id=project_id,
                version_no=version_no,
                shot_plan_version_id=shot_plan_version_id,
                raw_payload={
                    "grid_count": grid_count,
                    "total_shots": total_shots,
                    "grids": [],
                    "regeneration_feedback": feedback,
                },
                is_active=True,
            )
            await sv_repo.add(storyboard_version)
            await uow.flush()
            await uow.session.refresh(storyboard_version)
            sb_version_id = storyboard_version.id

        # ---- 步骤 5: 遍历 grid 1..grid_count -----------------------
        all_grids_meta: list[dict] = []

        for grid_index in range(1, grid_count + 1):
            await self._process_single_grid(
                project_id=project_id,
                grid_index=grid_index,
                total_grids=grid_count,
                ext=ext,
                narrative_shots=narrative_shots,
                shot_id_by_index=shot_id_by_index,
                storyboard_version_id=sb_version_id,
                logger=logger,
                grids_meta=all_grids_meta,
                regeneration_prompt_section=regeneration_prompt_section,
            )

            # 增量写回 raw_payload，保证前端在 shot_plan_ready 阶段即可读到
            # 已完成的三宫格，而不是等全部完成后一次性出现。
            async with UnitOfWork() as uow:
                sv = await StoryboardVersionRepository(uow.session).get_by_id(
                    sb_version_id
                )
                if sv is not None:
                    sv.raw_payload = {
                        "grid_count": grid_count,
                        "total_shots": total_shots,
                        "grids": all_grids_meta,
                        "regeneration_feedback": feedback,
                    }
                    uow.session.add(sv)

        # ---- 步骤 6: 推进项目阶段 + emit all_completed ------------------
        async with UnitOfWork() as uow:
            project = await ProjectRepository(uow.session).get_by_id(project_id)
            project.active_storyboard_version_id = sb_version_id
            uow.session.add(project)

            # 更新 raw_payload，写入完整 grids_meta
            sv = await StoryboardVersionRepository(uow.session).get_by_id(sb_version_id)
            sv.raw_payload = {
                "grid_count": grid_count,
                "total_shots": total_shots,
                "grids": all_grids_meta,
                "regeneration_feedback": feedback,
            }
            uow.session.add(sv)

            if project.current_stage != ProjectStage.STORYBOARD_READY.value:
                await state_transition_service.advance_project(
                    uow.session, project, ProjectStage.STORYBOARD_READY,
                )

            # emit storyboard.all_grids_completed（在阶段推进事件之前）
            await event_log_service.emit(
                uow.session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="project",
                    aggregate_id=project_id,
                    event_type="storyboard.all_grids_completed",
                    category="domain",
                    payload={
                        "grid_count": grid_count,
                        "total_frames": 3 * grid_count,
                        "shot_count": total_shots,
                        "storyboard_version_id": sb_version_id,
                    },
                ),
            )

        # ---- 步骤 7: 写本地 JSON 快照 -----------------------------
        try:
            store = LocalArtifactStore(project_id)
            store.write_json(
                ArtifactStage.STORYBOARD,
                "storyboard",
                {
                    "version_id": sb_version_id,
                    "version_no": version_no,
                    "shot_plan_version_id": shot_plan_version_id,
                    "grid_count": grid_count,
                    "total_shots": total_shots,
                    "grids": all_grids_meta,
                },
                version=version_no,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"storyboard 本地快照写入失败（不影响业务）: {exc}",
                event_type="storyboard_local_snapshot_failed",
            )

        logger.info(
            f"三宫格 storyboard 生成完成: version={version_no} grids={grid_count} "
            f"total_shots={total_shots}",
            event_type="storyboard_generation_done",
        )
        return storyboard_version

    async def _generate_talking_head_story_overview(
        self,
        *,
        project_id: str,
        user_id: str,
        project: Any,
        ext: CreativeBriefExtension,
        logger: Any,
    ) -> StoryboardVersion:
        """口播链路：生成 1 张 Story Overview Board，不切三宫格 cell。"""
        async with UnitOfWork() as uow:
            shot_plan = await ShotPlanRepository(uow.session).get_active(project_id)
            current_storyboard = await StoryboardVersionRepository(uow.session).get_active(
                project_id
            )
            current_storyboard_payload = (
                current_storyboard.raw_payload if current_storyboard is not None else None
            )
            current_storyboard_version_id = (
                current_storyboard.id if current_storyboard is not None else None
            )

        if shot_plan is None:
            logger.info(
                "未找到 active shot_plan，从 narrative_script 自动派生口播 segment shots",
                event_type="storyboard_talking_head_derive_shot_plan",
            )
            _, shot_plan_obj, _ = await self._shot_plan_service.derive_from_narrative(
                project_id, user_id,
            )
            shot_plan_version_id = shot_plan_obj.id
        else:
            shot_plan_version_id = shot_plan.id

        async with UnitOfWork() as uow:
            all_shots = await ShotRepository(uow.session).list_by_project(project_id)
        all_shots = sorted(all_shots, key=lambda s: s.shot_index)
        total_shots = max(ext.total_shots_generated, len(all_shots))
        segment_count = total_shots

        logger.info(
            f"口播 Story Overview Board 生成开始: segment_count={segment_count}",
            event_type="storyboard_story_overview_start",
        )
        previous_prompt = await self._latest_storyboard_prompt(
            project_id=project_id,
            storyboard_version_id=current_storyboard_version_id,
        )
        feedback = await regeneration_context_service.get_latest_feedback(
            project_id,
            decision_type="confirm_storyboard",
            target_entity_id=current_storyboard_version_id,
        )
        regeneration_prompt_section = (
            regeneration_context_service.build_storyboard_prompt_section(
                feedback=feedback,
                current_storyboard_payload=current_storyboard_payload,
                previous_prompt=previous_prompt,
            )
        )

        async with UnitOfWork() as uow:
            sv_repo = StoryboardVersionRepository(uow.session)
            await sv_repo.deactivate_all(project_id)
            version_no = await sv_repo.get_next_version_no(project_id)
            storyboard_version = StoryboardVersion(
                project_id=project_id,
                version_no=version_no,
                shot_plan_version_id=shot_plan_version_id,
                raw_payload={
                    "board_type": TALKING_HEAD_LAYOUT,
                    "grid_count": 1,
                    "total_shots": total_shots,
                    "segment_count": segment_count,
                    "story_board_aspect_ratio": "21:9",
                    "story_board_image_resolution": TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
                    "grids": [],
                    "regeneration_feedback": feedback,
                },
                is_active=True,
            )
            await sv_repo.add(storyboard_version)
            await uow.flush()
            await uow.session.refresh(storyboard_version)
            sb_version_id = storyboard_version.id

        cfg = get_config().talking_head
        async with UnitOfWork() as uow:
            bundle = await self._talking_head_compiler.compile_story_overview_board(
                uow.session,
                project_id,
                host_reference_assets=cfg.host_reference_image_assets,
                reference_audio_assets=cfg.reference_audio_assets,
                regeneration_prompt_section=regeneration_prompt_section,
            )
            await event_log_service.emit(
                uow.session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="project",
                    aggregate_id=project_id,
                    event_type="storyboard.story_overview.generating",
                    category="domain",
                    payload={
                        "bundle_id": bundle.bundle_id,
                        "segment_count": segment_count,
                        "story_board_aspect_ratio": "21:9",
                        "story_board_image_resolution": TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
                        "message": "口播故事大图生成中…",
                    },
                ),
            )

        try:
            parent_asset_id = await self._image_tool.generate_for_bundle(
                bundle=bundle,
                project_id=project_id,
                shot_index=None,
            )
        except ImageGenerationError as exc:
            logger.warning(
                f"口播故事大图生成失败: {exc}",
                event_type="storyboard_story_overview_failed",
            )
            raise StoryboardGenerationError(
                f"口播故事大图生成失败: {exc.message}",
                code="story_overview_generation_failed",
            ) from exc

        async with UnitOfWork() as uow:
            asset = await AssetRepository(uow.session).get_by_id(parent_asset_id)
            parent_url = await build_asset_access_url(asset) or ""
            layout_reading_map = dict(bundle.params.get("layout_reading_map") or {})
            if not layout_reading_map:
                layout_reading_map = {
                    f"segment_{idx + 1}": f"只读取故事大图中 Segment {idx + 1} / {segment_time_range(idx)} 区域"
                    for idx in range(segment_count)
                }
            segments = [
                {
                    "segment_index": idx + 1,
                    "shot_index": idx,
                    "time_range": segment_time_range(idx),
                    "reading_instruction": layout_reading_map.get(f"segment_{idx + 1}"),
                }
                for idx in range(segment_count)
            ]
            grid_meta = {
                "grid_index": 1,
                "board_type": TALKING_HEAD_LAYOUT,
                "parent_asset_id": parent_asset_id,
                "parent_asset_url": parent_url,
                "bundle_id": bundle.bundle_id,
                "prompt_preview": bundle.positive_prompt,
                "cell_count": 0,
                "cells": [],
                "layout_reading_map": layout_reading_map,
                "story_board_aspect_ratio": "21:9",
                "story_board_image_resolution": TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
                "segment_count": segment_count,
                "segments": segments,
            }

            frame_repo = StoryboardFrameRepository(uow.session)
            await frame_repo.bulk_add([
                StoryboardFrame(
                    project_id=project_id,
                    storyboard_version_id=sb_version_id,
                    shot_id=None,
                    asset_id=parent_asset_id,
                    prompt_bundle_id=bundle.bundle_id,
                    frame_index=100,
                    metadata_={
                        "is_story_overview_board": True,
                        "board_type": TALKING_HEAD_LAYOUT,
                        "layout_reading_map": layout_reading_map,
                        "segment_count": segment_count,
                        "story_board_image_resolution": TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
                    },
                    parent_asset_id=None,
                    cell_position=None,
                    grid_index=1,
                )
            ])

            shot_repo = ShotRepository(uow.session)
            for shot in all_shots:
                shot_orm = await shot_repo.get_by_id(shot.id)
                if shot_orm is not None:
                    shot_orm.status = "storyboard_ready"
                    uow.session.add(shot_orm)

            project_orm = await ProjectRepository(uow.session).get_by_id(project_id)
            project_orm.active_storyboard_version_id = sb_version_id
            uow.session.add(project_orm)
            sv = await StoryboardVersionRepository(uow.session).get_by_id(sb_version_id)
            sv.raw_payload = {
                "board_type": TALKING_HEAD_LAYOUT,
                "grid_count": 1,
                "total_shots": total_shots,
                "segment_count": segment_count,
                "story_board_aspect_ratio": "21:9",
                "story_board_image_resolution": TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
                "parent_asset_id": parent_asset_id,
                "parent_asset_url": parent_url,
                "layout_reading_map": layout_reading_map,
                "segments": segments,
                "grids": [grid_meta],
                "regeneration_feedback": feedback,
            }
            uow.session.add(sv)

            if project_orm.current_stage != ProjectStage.STORYBOARD_READY.value:
                await state_transition_service.advance_project(
                    uow.session, project_orm, ProjectStage.STORYBOARD_READY,
                )
            await event_log_service.emit(
                uow.session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="project",
                    aggregate_id=project_id,
                    event_type="storyboard.story_overview.ready",
                    category="domain",
                    payload={
                        "board_type": TALKING_HEAD_LAYOUT,
                        "parent_asset_id": parent_asset_id,
                        "asset_url": parent_url,
                        "segment_count": segment_count,
                        "story_board_image_resolution": TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
                        "storyboard_version_id": sb_version_id,
                    },
                ),
            )
            await event_log_service.emit(
                uow.session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="project",
                    aggregate_id=project_id,
                    event_type="storyboard.all_grids_completed",
                    category="domain",
                    payload={
                        "grid_count": 1,
                        "total_frames": 1,
                        "shot_count": total_shots,
                        "storyboard_version_id": sb_version_id,
                        "board_type": TALKING_HEAD_LAYOUT,
                    },
                ),
            )

        try:
            LocalArtifactStore(project_id).write_json(
                ArtifactStage.STORYBOARD,
                "storyboard",
                {
                    "version_id": sb_version_id,
                    "version_no": version_no,
                    "shot_plan_version_id": shot_plan_version_id,
                    "board_type": TALKING_HEAD_LAYOUT,
                    "grid_count": 1,
                    "total_shots": total_shots,
                    "segment_count": segment_count,
                    "story_board_image_resolution": TALKING_HEAD_STORY_BOARD_IMAGE_RESOLUTION,
                    "grids": [grid_meta],
                },
                version=version_no,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"口播 storyboard 本地快照写入失败（不影响业务）: {exc}",
                event_type="storyboard_local_snapshot_failed",
            )

        logger.info(
            f"口播 Story Overview Board 生成完成: version={version_no} asset={parent_asset_id!r}",
            event_type="storyboard_story_overview_done",
        )
        return storyboard_version

    async def _latest_storyboard_prompt(
        self,
        *,
        project_id: str,
        storyboard_version_id: str | None,
    ) -> str:
        if not storyboard_version_id:
            return ""
        async with UnitOfWork() as uow:
            frames = await StoryboardFrameRepository(uow.session).list_by_version(
                storyboard_version_id,
                limit=20,
            )
            prompt_ids = [
                frame.prompt_bundle_id
                for frame in frames
                if getattr(frame, "prompt_bundle_id", None)
            ]
            if prompt_ids:
                bundle = await uow.session.get(PromptBundleModel, prompt_ids[0])
                if bundle is not None and bundle.project_id == project_id:
                    return bundle.positive_prompt or ""
            sv = await StoryboardVersionRepository(uow.session).get_by_id_for_project(
                storyboard_version_id,
                project_id,
            )
            raw = sv.raw_payload if sv is not None else {}
        grids = list((raw or {}).get("grids") or [])
        prompts = [
            str(grid.get("prompt_preview") or "").strip()
            for grid in grids
            if isinstance(grid, dict) and grid.get("prompt_preview")
        ]
        return "\n\n".join(prompts[:3])

    # ------------------------------------------------------------------
    # 单张三宫格处理（doc 21 §6 增量推送）
    # ------------------------------------------------------------------

    async def _process_single_grid(
        self,
        *,
        project_id: str,
        grid_index: int,
        total_grids: int,
        ext: CreativeBriefExtension,
        narrative_shots: list[dict],
        shot_id_by_index: dict[int, str],
        storyboard_version_id: str,
        logger: Any,
        grids_meta: list[dict],
        regeneration_prompt_section: str = "",
    ) -> None:
        """处理单张三宫格：编译 prompt → 生成大图 → 切分 → 落 StoryboardFrame。"""

        # 1. 准备 3 个 cell 对应的 shot 描述：同一个 shot 的起始 / 中间 / 结尾
        shot_descriptions: list[dict] = []
        shot_idx = grid_index - 1
        for cell_position in range(1, 4):
            phase = ["start", "middle", "end"][(cell_position - 1) % 3]
            if shot_idx < len(narrative_shots):
                ns = narrative_shots[shot_idx]
                frame_description = (
                    ns.get("start_frame_description", "")
                    if phase == "start"
                    else ns.get("middle_frame_description", "")
                    if phase == "middle"
                    else ns.get("end_frame_description", "")
                )
                shot_descriptions.append({
                    "cell_position": cell_position,
                    "shot_index": shot_idx,
                    "scene_description": ns.get("scene_description", ""),
                    "frame_description": frame_description,
                    "phase": phase,
                    "characters_in_shot": ns.get("characters_in_shot", []),
                    "emotion": ns.get("emotion", "neutral"),
                })

        # 2. 编译三宫格 prompt + emit storyboard.grid.generating
        logger.info(
            f"grid[{grid_index}] 开始编译三宫格 prompt: cells={len(shot_descriptions)}",
            event_type="storyboard_grid_prompt_compile_start",
        )
        prompt_compile_started_at = time.monotonic()
        async with UnitOfWork() as uow:
            bundle = await self._compiler.compile_nine_grid_prompt(
                session=uow.session,
                project_id=project_id,
                grid_index=grid_index,
                total_grids=total_grids,
                shot_descriptions=shot_descriptions,
                regeneration_prompt_section=regeneration_prompt_section,
            )
            await event_log_service.emit(
                uow.session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="project",
                    aggregate_id=project_id,
                    event_type="storyboard.grid.generating",
                    category="domain",
                    payload={
                        "grid_index": grid_index,
                        "total_grids": total_grids,
                        "bundle_id": bundle.bundle_id,
                        "message": f"第 {grid_index}/{total_grids} 张三宫格生成中…",
                    },
                ),
            )
        logger.info(
            f"grid[{grid_index}] 三宫格 prompt 编译完成: "
            f"bundle_id={bundle.bundle_id!r} provider={bundle.provider!r} "
            f"elapsed={time.monotonic() - prompt_compile_started_at:.2f}s",
            event_type="storyboard_grid_prompt_compile_done",
        )

        # 3. 生成大图（不在 UoW 内，避免长时间持有 DB 连接）
        logger.info(
            f"grid[{grid_index}] 开始请求三宫格生图 provider: "
            f"provider={bundle.provider!r} size={bundle.params.get('size')!r}",
            event_type="storyboard_grid_provider_request_start",
        )
        image_generation_started_at = time.monotonic()
        try:
            parent_asset_id = await self._image_tool.generate_nine_grid(
                bundle=bundle, project_id=project_id, grid_index=grid_index,
            )
        except ImageGenerationError as exc:
            logger.warning(
                f"grid[{grid_index}] 生成失败: {exc}",
                event_type="storyboard_grid_failed",
            )
            raise StoryboardGenerationError(
                f"三宫格 {grid_index} 生成失败: {exc.message}",
                code="grid_generation_failed",
            ) from exc
        logger.info(
            f"grid[{grid_index}] 三宫格大图生成成功: parent_asset_id={parent_asset_id!r} "
            f"elapsed={time.monotonic() - image_generation_started_at:.2f}s",
            event_type="storyboard_grid_provider_request_done",
        )

        # 4. emit storyboard.grid.generated
        async with UnitOfWork() as uow:
            parent_asset = await AssetRepository(uow.session).get_by_id(parent_asset_id)
            parent_url = await build_asset_access_url(parent_asset) or ""
            await event_log_service.emit(
                uow.session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="project",
                    aggregate_id=project_id,
                    event_type="storyboard.grid.generated",
                    category="domain",
                    payload={
                        "grid_index": grid_index,
                        "parent_asset_id": parent_asset_id,
                        "asset_url": parent_url,
                        "total_grids": total_grids,
                    },
                ),
            )

        # 5. 切分 3 张 cell
        split_started_at = time.monotonic()
        logger.info(
            f"grid[{grid_index}] 开始切分三宫格: parent_asset_id={parent_asset_id!r}",
            event_type="storyboard_grid_split_start",
        )
        cell_asset_ids = await self._image_tool.split_and_persist_grid(
            parent_asset_id=parent_asset_id,
            project_id=project_id,
            grid_index=grid_index,
        )
        logger.info(
            f"grid[{grid_index}] 三宫格切分完成: cell_count={len(cell_asset_ids)} "
            f"elapsed={time.monotonic() - split_started_at:.2f}s",
            event_type="storyboard_grid_split_done_local",
        )

        # 6. 收集 cells_meta + emit storyboard.grid.split_done
        cells_meta: list[dict] = []
        async with UnitOfWork() as uow:
            asset_repo = AssetRepository(uow.session)
            cell_assets = await asset_repo.list_by_ids(cell_asset_ids)
            cell_url_map = await build_asset_access_url_map(cell_assets)
            for cell_pos, cell_aid in enumerate(cell_asset_ids, start=1):
                shot_idx = grid_index - 1
                shot_id_for_cell = shot_id_by_index.get(shot_idx)
                narrative_meta = (
                    shot_descriptions[cell_pos - 1]
                    if 0 <= cell_pos - 1 < len(shot_descriptions)
                    else {}
                )
                cells_meta.append({
                    "cell_position": cell_pos,
                    "asset_id": cell_aid,
                    "asset_url": cell_url_map.get(cell_aid, ""),
                    "shot_id": shot_id_for_cell,
                    "shot_index": shot_idx if shot_idx < len(narrative_shots) else None,
                    "frame_description": narrative_meta.get("frame_description", ""),
                    "scene_description": narrative_meta.get("scene_description", ""),
                    "is_reused_from_prev_grid": False,
                })

            await event_log_service.emit(
                uow.session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="project",
                    aggregate_id=project_id,
                    event_type="storyboard.grid.split_done",
                    category="domain",
                    payload={
                        "grid_index": grid_index,
                        "total_grids": total_grids,
                        "frames": cells_meta,
                    },
                ),
            )

        # 7. 落 StoryboardFrame（1 条大图 + 3 条 cell）
        async with UnitOfWork() as uow:
            frame_repo = StoryboardFrameRepository(uow.session)
            shot_repo = ShotRepository(uow.session)
            frames: list[StoryboardFrame] = []
            ready_shot_ids: set[str] = set()

            # 大图 frame（cell_position=NULL, parent_asset_id=NULL, shot_id=NULL）
            frames.append(StoryboardFrame(
                project_id=project_id,
                storyboard_version_id=storyboard_version_id,
                shot_id=None,
                asset_id=parent_asset_id,
                prompt_bundle_id=bundle.bundle_id,
                # 大图用 grid*100 区分（避免与 cell frame_index 冲突）
                frame_index=grid_index * 100,
                metadata_={
                    "is_grid_parent": True,
                    "grid_index": grid_index,
                },
                parent_asset_id=None,
                cell_position=None,
                grid_index=grid_index,
            ))

            # 3 条 cell frame
            for cell_pos, cell_aid in enumerate(cell_asset_ids, start=1):
                shot_idx = grid_index - 1
                shot_id_for_cell = shot_id_by_index.get(shot_idx)
                if shot_id_for_cell:
                    ready_shot_ids.add(shot_id_for_cell)
                frames.append(StoryboardFrame(
                    project_id=project_id,
                    storyboard_version_id=storyboard_version_id,
                    shot_id=shot_id_for_cell,
                    asset_id=cell_aid,
                    prompt_bundle_id=bundle.bundle_id,
                    frame_index=grid_index * 100 + cell_pos,
                    metadata_={
                        "grid_index": grid_index,
                        "cell_position": cell_pos,
                        "shot_index": shot_idx if shot_idx < len(narrative_shots) else None,
                    },
                    parent_asset_id=parent_asset_id,
                    cell_position=cell_pos,
                    grid_index=grid_index,
                ))

            await frame_repo.bulk_add(frames)
            for shot_id in ready_shot_ids:
                shot = await shot_repo.get_by_id(shot_id)
                if shot is not None:
                    shot.status = "storyboard_ready"
                    uow.session.add(shot)

        # 8. 更新 grids_meta
        grids_meta.append({
            "grid_index": grid_index,
            "parent_asset_id": parent_asset_id,
            "parent_asset_url": parent_url,
            "bundle_id": bundle.bundle_id,
            "prompt_preview": bundle.positive_prompt,
            "cells": cells_meta,
        })

        logger.info(
            f"grid[{grid_index}] 处理完成: parent={parent_asset_id} "
            f"cells={len(cell_asset_ids)}",
            event_type="storyboard_grid_done",
        )
