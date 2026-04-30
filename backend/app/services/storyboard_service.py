"""Storyboard 生成服务（doc 21 九宫格架构）。

来源文档：doc 21 §3 + §5 + §6

职责：
  按 brief.extension.grid_count 串行生成多张九宫格大图，每张：
    1. 从 narrative_script 取出 9 个 cell 对应的 shot 描述
    2. 编译九宫格 prompt（PromptCompilerService.compile_nine_grid_prompt）
    3. 调用 ImageGenerationTool.generate_nine_grid 生成 3072×3072 大图
    4. 调用 ImageGenerationTool.split_and_persist_grid 切分 9 张 cell
    5. 落库 StoryboardFrame：1 条大图 + 9 条 cell（doc 21 §5.4）
    6. 推送 4 个事件（doc 21 §6.1）：
       storyboard.grid.generating / generated / split_done / all_grids_completed

跨九宫格衔接（doc 21 §3.2）：
  第 N+1 张的 cell 1 物理复用第 N 张的 cell 9 asset_id，
  保证视觉 100% 一致。
"""
from __future__ import annotations

import time
from typing import Any

from app.core.logging import get_project_logger
from app.domain.states import ProjectStage
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
from app.services.prompt_compiler_service import PromptCompilerService
from app.services.shot_plan_persistence_service import ShotPlanPersistenceService
from app.services.state_transition_service import state_transition_service
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
# StoryboardService（doc 21 九宫格架构）
# ---------------------------------------------------------------------------

class StoryboardService:
    """九宫格 storyboard 服务：brief.extension + narrative_script → N 张九宫格 + 切分 + 落库。"""

    def __init__(self) -> None:
        self._compiler = PromptCompilerService()
        self._image_tool = ImageGenerationTool()
        self._shot_plan_service = ShotPlanPersistenceService()

    async def generate_and_save(
        self,
        project_id: str,
        user_id: str,
    ) -> StoryboardVersion:
        """主入口：执行九宫格 storyboard 生成流程。

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
            f"九宫格 storyboard 生成开始: grid_count={grid_count} "
            f"total_shots={total_shots}",
            event_type="storyboard_generation_start",
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
                },
                is_active=True,
            )
            await sv_repo.add(storyboard_version)
            await uow.flush()
            await uow.session.refresh(storyboard_version)
            sb_version_id = storyboard_version.id

        # ---- 步骤 5: 遍历 grid 1..grid_count -----------------------
        prev_cell9_asset_id: str | None = None
        prev_cell9_description: str | None = None
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
                prev_cell9_asset_id=prev_cell9_asset_id,
                prev_cell9_description=prev_cell9_description,
                logger=logger,
                grids_meta=all_grids_meta,
            )

            # 增量写回 raw_payload，保证前端在 shot_plan_ready 阶段即可读到
            # 已完成的九宫格，而不是等全部完成后一次性出现。
            async with UnitOfWork() as uow:
                sv = await StoryboardVersionRepository(uow.session).get_by_id(
                    sb_version_id
                )
                if sv is not None:
                    sv.raw_payload = {
                        "grid_count": grid_count,
                        "total_shots": total_shots,
                        "grids": all_grids_meta,
                    }
                    uow.session.add(sv)

            # 更新跨 grid 衔接信息（doc 21 §3.2）
            last_grid = all_grids_meta[-1]
            prev_cell9_asset_id = last_grid["cells"][-1]["asset_id"]
            cell9_shot_index = (grid_index - 1) * 3 + 2
            if cell9_shot_index < len(narrative_shots):
                next_shot = narrative_shots[cell9_shot_index]
                prev_cell9_description = next_shot.get(
                    "start_frame_description", ""
                )
            else:
                last_shot = narrative_shots[-1]
                prev_cell9_description = last_shot.get(
                    "end_frame_description", ""
                )

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
                        "total_frames": 9 * grid_count,
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
            f"九宫格 storyboard 生成完成: version={version_no} grids={grid_count} "
            f"total_shots={total_shots}",
            event_type="storyboard_generation_done",
        )
        return storyboard_version

    # ------------------------------------------------------------------
    # 单张九宫格处理（doc 21 §6 增量推送）
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
        prev_cell9_asset_id: str | None,
        prev_cell9_description: str | None,
        logger: Any,
        grids_meta: list[dict],
    ) -> None:
        """处理单张九宫格：编译 prompt → 生成大图 → 切分 → 落 StoryboardFrame。"""

        # 1. 准备 9 个 cell 对应的 shot 描述
        # 当前版本：每一行对应 1 个 shot（起始 / 中间 / 结尾）
        shot_descriptions: list[dict] = []
        for cell_position in range(1, 10):
            row_offset = (cell_position - 1) // 3
            shot_idx = (grid_index - 1) * 3 + row_offset
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
            else:
                # 边界 cell（超出 total_shots）：沿用最后画面
                last_ns = narrative_shots[-1] if narrative_shots else {}
                shot_descriptions.append({
                    "cell_position": cell_position,
                    "shot_index": None,
                    "scene_description": "（边界，沿用最后画面）",
                    "frame_description": last_ns.get("end_frame_description", ""),
                    "phase": phase,
                    "characters_in_shot": [],
                    "emotion": "neutral",
                })

        # 2. 编译九宫格 prompt + emit storyboard.grid.generating
        logger.info(
            f"grid[{grid_index}] 开始编译九宫格 prompt: cells={len(shot_descriptions)} "
            f"prev_cell9={'有' if prev_cell9_description else '无'}",
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
                prev_cell9_description=prev_cell9_description,
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
                        "message": f"第 {grid_index}/{total_grids} 张九宫格生成中…",
                    },
                ),
            )
        logger.info(
            f"grid[{grid_index}] 九宫格 prompt 编译完成: "
            f"bundle_id={bundle.bundle_id!r} provider={bundle.provider!r} "
            f"elapsed={time.monotonic() - prompt_compile_started_at:.2f}s",
            event_type="storyboard_grid_prompt_compile_done",
        )

        # 3. 生成大图（不在 UoW 内，避免长时间持有 DB 连接）
        logger.info(
            f"grid[{grid_index}] 开始请求九宫格生图 provider: "
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
                f"九宫格 {grid_index} 生成失败: {exc.message}",
                code="grid_generation_failed",
            ) from exc
        logger.info(
            f"grid[{grid_index}] 九宫格大图生成成功: parent_asset_id={parent_asset_id!r} "
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

        # 5. 切分 9 张 cell（带跨九宫格衔接 prev_cell9_asset_id）
        split_started_at = time.monotonic()
        logger.info(
            f"grid[{grid_index}] 开始切分九宫格: parent_asset_id={parent_asset_id!r}",
            event_type="storyboard_grid_split_start",
        )
        cell_asset_ids = await self._image_tool.split_and_persist_grid(
            parent_asset_id=parent_asset_id,
            project_id=project_id,
            grid_index=grid_index,
            prev_cell9_asset_id=prev_cell9_asset_id,
        )
        logger.info(
            f"grid[{grid_index}] 九宫格切分完成: cell_count={len(cell_asset_ids)} "
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
                shot_idx = (grid_index - 1) * 3 + ((cell_pos - 1) // 3)
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
                    "is_reused_from_prev_grid": (
                        cell_pos == 1 and prev_cell9_asset_id == cell_aid
                    ),
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

        # 7. 落 StoryboardFrame（1 条大图 + 9 条 cell）
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

            # 9 条 cell frame
            for cell_pos, cell_aid in enumerate(cell_asset_ids, start=1):
                shot_idx = (grid_index - 1) * 3 + ((cell_pos - 1) // 3)
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
            f"cells={len(cell_asset_ids)} reused_cell1={bool(prev_cell9_asset_id)}",
            event_type="storyboard_grid_done",
        )
