"""视觉圣经服务（VisualBibleService）。

来源文档：doc11 §4.4（VisualBible 结构）/ §5.5（VisualDevelopmentAgent）/ doc11 批次2

职责：
  1. 从 active NarrativeScriptVersion 初始化 CharacterSetVersion（框架，无资产）
  2. 为指定角色生成 character_reference 资产并回写 active CharacterSetVersion
  3. 为指定场景生成 scene_reference 资产并回写 active CharacterSetVersion
  4. 确认视觉圣经 → 设置 confirmed_at → 推进项目到 visual_bible_ready

注意：
  - CharacterSetVersion.characters / scenes 均为 JSONB list，每项结构：
      {
        "character_id": str,   # 或 "scene_id"
        "character_name": str, # 或 "scene_name"
        "description": str,
        "reference_asset_ids": list[str],
        "active_reference_asset_id": str | None,
        "appears_in_sections": list[str]  (可选)
      }
  - 每次生成参考图后更新对应条目的 reference_asset_ids 和 active_reference_asset_id
  - append-only：不修改旧 CharacterSetVersion，每次重新生成整个 VisualBible 时创建新版本
    但单个角色/场景参考图重新生成时直接修改当前 active 版本的 JSON（版本内更新）
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.visual_development_agent import VisualDevelopmentAgent
from app.core.logging import get_project_logger
from app.domain.states import ProjectStage
from app.models.visual_bible import CharacterReference, CharacterSetVersion, SceneReference
from app.repositories.asset_repository import AssetRepository
from app.repositories.planning_repositories import StyleBibleRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.project_spec_repository import ProjectSpecRepository
from app.repositories.unit_of_work import UnitOfWork
from app.repositories.visual_bible_repository import (
    CharacterSetVersionRepository,
    NarrativeScriptVersionRepository,
)
from app.services.state_transition_service import state_transition_service
from app.storage.minio_adapter import get_storage
from app.core.config import get_config
from app.core.provider_registry import get_provider_registry
from app.tools.shared.artifact_tools import build_ref_from_asset_latest, write_artifact
from app.tools.image_generation_tool import ImageGenerationTool
from app.utils.ids import generate_ulid


# ---------------------------------------------------------------------------
# 模块级辅助函数
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class VisualBibleError(Exception):
    """视觉圣经业务异常。"""

    def __init__(self, message: str, code: str = "visual_bible_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# VisualBibleService
# ---------------------------------------------------------------------------

class VisualBibleService:
    """视觉圣经生命周期服务。"""

    def __init__(self) -> None:
        self._agent = VisualDevelopmentAgent()
        self._tool = ImageGenerationTool()

    # ------------------------------------------------------------------
    # 公共接口 1：从 NarrativeScript 初始化空 CharacterSetVersion
    # ------------------------------------------------------------------

    async def init_from_narrative(
        self,
        project_id: str,
        user_id: str,
    ) -> CharacterSetVersion:
        """从 active NarrativeScriptVersion 初始化一个空的 CharacterSetVersion。

        初始化后各角色/场景的 reference_asset_ids 为 []，无实际图片。

        Args:
            project_id: 项目 ID。
            user_id:    用户 ID（归属校验）。

        Returns:
            新建的 CharacterSetVersion。

        Raises:
            VisualBibleError: 前置条件不满足。
        """
        logger = get_project_logger(project_id, module="services.visual_bible")

        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise VisualBibleError("项目不存在", code="project_not_found")

            # 允许 narrative_ready / visual_bible_ready 阶段重新初始化
            allowed = {
                ProjectStage.NARRATIVE_READY.value,
                ProjectStage.VISUAL_BIBLE_READY.value,
            }
            if project.current_stage not in allowed:
                raise VisualBibleError(
                    f"当前阶段 {project.current_stage!r} 不允许初始化视觉圣经，"
                    "需要先完成叙事剧本（narrative_ready）",
                    code="invalid_stage",
                )

            # 读取 active NarrativeScript
            narrative = await NarrativeScriptVersionRepository(session).get_active(
                project_id
            )
            if narrative is None:
                raise VisualBibleError(
                    "未找到 active 叙事剧本，请先生成叙事剧本",
                    code="no_narrative",
                )

            # 读取用户上传的参考图（按顺序将自动关联到前 N 个角色）
            ref_image_ids: list[str] = []
            if project.active_project_spec_version_id:
                spec = await ProjectSpecRepository(session).get_active(project_id)
                if spec:
                    ref_image_ids = [
                        r for r in (getattr(spec, "reference_image_asset_ids", None) or []) if r
                    ]

            # 构建空初始化结构，按顺序自动关联参考图
            characters = []
            for i, c in enumerate(narrative.characters or []):
                # 按顺序取对应的参考图（如果有）
                pre_assigned_ref = ref_image_ids[i] if i < len(ref_image_ids) else None
                characters.append({
                    "character_id": c.get("id", ""),
                    "character_name": c.get("name", ""),
                    "description": c.get("description", ""),
                    "appears_in_sections": c.get("appears_in_sections", []),
                    "reference_asset_ids": [pre_assigned_ref] if pre_assigned_ref else [],
                    "active_reference_asset_id": pre_assigned_ref,
                    "base_face_asset_id": pre_assigned_ref,  # 待后续 Omni 分析后确认
                    "image_analysis": None,
                    "costumes": [],
                })
            # 如果参考图比角色多，剩余的放入待匹配池
            unmatched_refs = ref_image_ids[len(characters):]
            scenes = [
                {
                    "scene_id": s.get("id", ""),
                    "scene_name": s.get("name", ""),
                    "description": s.get("description", ""),
                    "appears_in_sections": s.get("appears_in_sections", []),
                    "reference_asset_ids": [],
                    "active_reference_asset_id": None,
                }
                for s in (narrative.scenes or [])
            ]

            csv_repo = CharacterSetVersionRepository(session)
            await csv_repo.deactivate_all(project_id)
            version_no = await csv_repo.get_next_version_no(project_id)

            raw_payload = {
                "characters": characters,
                "scenes": scenes,
                "narrative_script_version_id": narrative.id,
                # 待匹配的参考图（图片数量 > 角色数量时存在）
                "unmatched_reference_asset_ids": unmatched_refs,
            }

            csv = CharacterSetVersion(
                id=generate_ulid(),
                project_id=project_id,
                version_no=version_no,
                characters=[],  # WP4: 不再向 JSONB 写实际数据，改用独立表
                scenes=[],      # WP4: 同上
                confirmed_at=None,
                raw_payload=raw_payload,  # 保留完整 payload 用于追溯
                is_active=True,
            )
            await csv_repo.add(csv)
            await session.flush()
            await session.refresh(csv)

            # WP4: 逐条创建 CharacterReference 独立行
            for i, c in enumerate(narrative.characters or []):
                pre_assigned_ref = ref_image_ids[i] if i < len(ref_image_ids) else None
                char_ref = CharacterReference(
                    id=generate_ulid(),
                    version_id=csv.id,
                    project_id=project_id,
                    character_id=c.get("id", ""),
                    character_name=c.get("name", ""),
                    description=c.get("description", ""),
                    appears_in_sections=c.get("appears_in_sections", []),
                    reference_asset_ids=[pre_assigned_ref] if pre_assigned_ref else [],
                    active_reference_asset_id=pre_assigned_ref,
                    base_face_asset_id=pre_assigned_ref,
                    image_analysis=None,
                    costumes=[],
                )
                session.add(char_ref)

            # WP4: 逐条创建 SceneReference 独立行
            for s in (narrative.scenes or []):
                scene_ref = SceneReference(
                    id=generate_ulid(),
                    version_id=csv.id,
                    project_id=project_id,
                    scene_id=s.get("id", ""),
                    scene_name=s.get("name", ""),
                    description=s.get("description", ""),
                    appears_in_sections=s.get("appears_in_sections", []),
                    reference_asset_ids=[],
                    active_reference_asset_id=None,
                )
                session.add(scene_ref)

            # 更新项目指针
            project.active_character_set_version_id = csv.id
            session.add(project)
        assigned = sum(1 for c in characters if c.get("base_face_asset_id"))
        logger.info(
            f"视觉圣经初始化完成: version_id={csv.id!r} "
            f"characters={len(characters)} scenes={len(scenes)} "
            f"pre_assigned_refs={assigned} unmatched_refs={len(unmatched_refs)}",
            event_type="visual_bible_initialized",
        )
        return csv

    # ------------------------------------------------------------------
    # 公共接口 2：生成角色参考图
    # ------------------------------------------------------------------

    async def generate_character_reference(
        self,
        project_id: str,
        user_id: str,
        character_id: str,
        *,
        generation_mode: Optional[str] = None,
        source_image_url: Optional[str] = None,
        source_image_hint: Optional[str] = None,
        provider_name: Optional[str] = None,
    ) -> str:
        """为指定角色生成参考图，回写 active CharacterSetVersion。

        Returns:
            新建 Asset 的 asset_id。
        """
        logger = get_project_logger(project_id, module="services.visual_bible")

        # 读取上下文
        csv, style, character_item = await self._load_context_for_character(
            project_id, user_id, character_id
        )
        generation_mode = self._resolve_character_generation_mode(character_item, generation_mode)
        logger.info(
            f"角色参考图生成模式决策: character_id={character_id!r} mode={generation_mode!r}",
            event_type="character_ref_mode_resolved",
        )
        source_asset_id = self._get_character_source_asset_id(character_item)
        if generation_mode == "direct":
            if not source_asset_id:
                raise VisualBibleError("缺少可直接复用的角色参考图", code="missing_source_asset")
            await self._update_character_ref(project_id=project_id, csv_id=csv.id, character_id=character_id, new_asset_id=source_asset_id)
            logger.info(
                f"角色参考图直接复用: character_id={character_id!r} asset_id={source_asset_id!r}",
                event_type="character_ref_reused",
            )
            return source_asset_id
        if generation_mode == "image_to_image" and not source_image_url and source_asset_id:
            source_image_url = await self._get_project_asset_url(project_id, source_asset_id)
        if generation_mode == "image_to_image" and not source_image_url:
            generation_mode = "text_to_image"

        # Batch B: 构建 task_spec 并调用 agent.run()
        existing_refs = character_item.get("reference_asset_ids", [])
        version_no = len(existing_refs) + 1

        style_ref = None
        if style is not None:
            style_ref = await build_ref_from_asset_latest(
                project_id,
                artifact_type="style_bible",
                version_no=style.version_no,
                prefix="style_bible",
                summary=getattr(style, "lighting_style", "") or "style_bible",
            )

        task_spec = {
            "project_id": project_id,
            "subject_type": "character",
            "subject_id": character_id,
            "subject_name": character_item.get("character_name", ""),
            "subject_description": character_item.get("description", character_item.get("character_name", "")),
            "generation_mode": generation_mode,
            "source_image_url": source_image_url or "",
            "style_ref": style_ref,
            "version_no": version_no,
        }
        # 根据生成模式从配置查找合适的 provider
        if not provider_name:
            registry = get_provider_registry()
            matched = registry.get_for_mode("image", generation_mode)
            if matched:
                provider_name = matched.name
        if provider_name:
            task_spec["provider_name"] = provider_name

        run_result = await self._agent.run(task_spec)
        asset_id: str = run_result.get("asset_id", "")
        if not asset_id:
            raise VisualBibleError(
                f"角色 {character_id!r} 参考图生成失败: {run_result.get('error', '未知错误')}",
                code="character_ref_generation_failed",
            )

        logger.info(
            f"角色参考图生成完成: character_id={character_id!r} asset_id={asset_id!r}",
            event_type="character_ref_generated",
        )

        # 回写 CharacterSetVersion
        await self._update_character_ref(
            project_id=project_id,
            csv_id=csv.id,
            character_id=character_id,
            new_asset_id=asset_id,
        )

        return asset_id

    # ------------------------------------------------------------------
    # 公共接口 3：生成场景参考图
    # ------------------------------------------------------------------

    async def generate_scene_reference(
        self,
        project_id: str,
        user_id: str,
        scene_id: str,
        *,
        provider_name: Optional[str] = None,
    ) -> str:
        """为指定场景生成参考图，回写 active CharacterSetVersion。

        Returns:
            新建 Asset 的 asset_id。
        """
        logger = get_project_logger(project_id, module="services.visual_bible")

        csv, style, scene_item = await self._load_context_for_scene(
            project_id, user_id, scene_id
        )

        # Batch B: 构建 task_spec 并调用 agent.run()
        existing_refs = scene_item.get("reference_asset_ids", [])
        version_no = len(existing_refs) + 1

        style_ref = None
        if style is not None:
            style_ref = await build_ref_from_asset_latest(
                project_id,
                artifact_type="style_bible",
                version_no=style.version_no,
                prefix="style_bible",
                summary=getattr(style, "lighting_style", "") or "style_bible",
            )

        task_spec = {
            "project_id": project_id,
            "subject_type": "scene",
            "subject_id": scene_id,
            "subject_name": scene_item.get("scene_name", ""),
            "subject_description": scene_item.get("description", scene_item.get("scene_name", "")),
            "generation_mode": "text_to_image",
            "style_ref": style_ref,
            "version_no": version_no,
        }
        # 场景始终是文生图，从配置查找支持 text_to_image 的 provider
        if not provider_name:
            registry = get_provider_registry()
            matched = registry.get_for_mode("image", "text_to_image")
            if matched:
                provider_name = matched.name
        if provider_name:
            task_spec["provider_name"] = provider_name

        logger.info(
            f"场景参考图生成开始: scene_id={scene_id!r} provider={provider_name!r}",
            event_type="scene_ref_generation_start",
        )

        run_result = await self._agent.run(task_spec)
        asset_id: str = run_result.get("asset_id", "")
        if not asset_id:
            raise VisualBibleError(
                f"场景 {scene_id!r} 参考图生成失败: {run_result.get('error', '未知错误')}",
                code="scene_ref_generation_failed",
            )

        logger.info(
            f"场景参考图生成完成: scene_id={scene_id!r} asset_id={asset_id!r}",
            event_type="scene_ref_generated",
        )

        await self._update_scene_ref(
            project_id=project_id,
            csv_id=csv.id,
            scene_id=scene_id,
            new_asset_id=asset_id,
        )

        return asset_id

    # ------------------------------------------------------------------
    # 公共接口 4：确认视觉圣经 → 推进到 visual_bible_ready
    # ------------------------------------------------------------------

    async def confirm_visual_bible(
        self,
        project_id: str,
        user_id: str,
    ) -> CharacterSetVersion:
        """确认视觉圣经，设置 confirmed_at，推进项目到 visual_bible_ready。

        WP4 适配：快照写入时从独立表读取 characters / scenes 数据。

        Returns:
            更新后的 CharacterSetVersion。

        Raises:
            VisualBibleError: 无 active CharacterSetVersion 或阶段不符。
        """
        from app.repositories.character_reference_repository import CharacterReferenceRepository  # noqa: PLC0415
        from app.repositories.scene_reference_repository import SceneReferenceRepository  # noqa: PLC0415

        logger = get_project_logger(project_id, module="services.visual_bible")

        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise VisualBibleError("项目不存在", code="project_not_found")

            csv_repo = CharacterSetVersionRepository(session)
            csv = await csv_repo.get_active(project_id)
            if csv is None:
                raise VisualBibleError(
                    "未找到 active 视觉圣经，请先初始化",
                    code="no_visual_bible",
                )

            # 从独立表读取角色和场景数据
            chars = await CharacterReferenceRepository(session).list_by_version(csv.id)
            scenes = await SceneReferenceRepository(session).list_by_version(csv.id)

            # 设置确认时间
            now_str = datetime.now(timezone.utc).isoformat()
            csv.confirmed_at = now_str

            # 同步 raw_payload
            raw = dict(csv.raw_payload or {})
            raw["confirmed_at"] = now_str
            csv.raw_payload = raw

            session.add(csv)

            # 推进项目状态（init 已推到 visual_bible_ready 时跳过）
            if project.current_stage != ProjectStage.VISUAL_BIBLE_READY.value:
                logger.info(
                    f"视觉圣经确认中，推进项目状态: version_id={csv.id!r}",
                    event_type="visual_bible_confirming",
                )
                await state_transition_service.advance_project(
                    session, project, ProjectStage.VISUAL_BIBLE_READY
                )

        # 构建快照数据（从独立表 ORM 对象转换）
        chars_snapshot = [
            {
                "character_id": c.character_id,
                "character_name": c.character_name,
                "description": c.description,
                "appears_in_sections": c.appears_in_sections,
                "reference_asset_ids": c.reference_asset_ids,
                "active_reference_asset_id": c.active_reference_asset_id,
                "base_face_asset_id": c.base_face_asset_id,
                "image_analysis": c.image_analysis,
                "costumes": c.costumes,
            }
            for c in chars
        ]
        scenes_snapshot = [
            {
                "scene_id": s.scene_id,
                "scene_name": s.scene_name,
                "description": s.description,
                "appears_in_sections": s.appears_in_sections,
                "reference_asset_ids": s.reference_asset_ids,
                "active_reference_asset_id": s.active_reference_asset_id,
            }
            for s in scenes
        ]

        # BUG-08 修复：CharacterSetVersion JSON 结构之前只存在 DB JSONB 列，
        # 无本地文件、无 MinIO 备份、无 Asset 记录。
        # 在用户确认视觉圣经时（结构最终确定）写入三副本：本地 04_style/ + MinIO + Asset。
        try:
            visual_bible_snapshot = {
                "version_id": csv.id,
                "version_no": csv.version_no,
                "confirmed_at": now_str,
                "characters": chars_snapshot,
                "scenes": scenes_snapshot,
                "narrative_script_version_id": (csv.raw_payload or {}).get(
                    "narrative_script_version_id"
                ),
            }
            await write_artifact(
                visual_bible_snapshot,
                project_id=project_id,
                artifact_type="visual_bible",
                version_no=csv.version_no,
                summary=(
                    f"{len(chars_snapshot)} 角色 / "
                    f"{len(scenes_snapshot)} 场景"
                ),
            )
            logger.info(
                f"视觉圣经 JSON 快照已写入本地+MinIO: version_id={csv.id!r}",
                event_type="visual_bible_snapshot_written",
            )
        except Exception as snap_exc:
            # 快照写入失败不影响确认结果（DB 已提交），记录 warning
            logger.warning(
                f"视觉圣经快照写入失败（不影响确认）: {snap_exc!r}",
                event_type="visual_bible_snapshot_failed",
            )

        logger.info(
            f"视觉圣经已确认: version_id={csv.id!r} confirmed_at={now_str}",
            event_type="visual_bible_confirmed",
        )
        return csv

    # ------------------------------------------------------------------
    # 公共接口 5（WP4 新增）：获取视觉圣经组装数据
    # ------------------------------------------------------------------

    async def get_visual_bible_data(self, project_id: str) -> dict | None:
        """WP4 新增：从独立表组装视觉圣经数据，格式与原 API 完全一致。

        用于 API 层返回前端所需的完整视觉圣经数据。

        Returns:
            组装后的 dict（与旧 JSONB 格式一致），无 active 版本时返回 None。
        """
        from app.repositories.character_reference_repository import CharacterReferenceRepository  # noqa: PLC0415
        from app.repositories.scene_reference_repository import SceneReferenceRepository  # noqa: PLC0415

        async with UnitOfWork() as uow:
            csv = await CharacterSetVersionRepository(uow.session).get_active(project_id)
            if csv is None:
                return None
            chars = await CharacterReferenceRepository(uow.session).list_by_version(csv.id)
            scenes = await SceneReferenceRepository(uow.session).list_by_version(csv.id)

        return {
            "id": csv.id,
            "version_no": csv.version_no,
            "characters": [
                {
                    "character_id": c.character_id,
                    "character_name": c.character_name,
                    "description": c.description,
                    "appears_in_sections": c.appears_in_sections,
                    "active_reference_asset_id": c.active_reference_asset_id,
                    "reference_asset_ids": c.reference_asset_ids,
                    "base_face_asset_id": c.base_face_asset_id,
                    "image_analysis": c.image_analysis,
                    "costumes": c.costumes,
                }
                for c in chars
            ],
            "scenes": [
                {
                    "scene_id": s.scene_id,
                    "scene_name": s.scene_name,
                    "description": s.description,
                    "appears_in_sections": s.appears_in_sections,
                    "active_reference_asset_id": s.active_reference_asset_id,
                    "reference_asset_ids": s.reference_asset_ids,
                }
                for s in scenes
            ],
            "confirmed_at": csv.confirmed_at,
            "is_active": csv.is_active,
            "created_at": csv.created_at.isoformat() if csv.created_at else None,
        }

    # ------------------------------------------------------------------
    # 内部辅助：加载上下文
    # ------------------------------------------------------------------

    async def _load_context_for_subject(
        self,
        project_id: str,
        user_id: str,
        subject_type: str,  # "character" | "scene"
        subject_id: str,
    ) -> tuple[CharacterSetVersion, Any, dict]:
        """CLASS-02 修复 + WP4 适配：通用上下文加载，返回 (active_csv, active_style, subject_item)。

        WP4: 从 CharacterReferenceRepository / SceneReferenceRepository 独立表查询，
        不再从 CharacterSetVersion.characters / .scenes JSONB 中查找。

        Args:
            subject_type: "character" 或 "scene"。
            subject_id:   角色 ID 或场景 ID。
        """
        from app.repositories.character_reference_repository import CharacterReferenceRepository  # noqa: PLC0415
        from app.repositories.scene_reference_repository import SceneReferenceRepository  # noqa: PLC0415

        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise VisualBibleError("项目不存在", code="project_not_found")

            csv = await CharacterSetVersionRepository(session).get_active(project_id)
            if csv is None:
                raise VisualBibleError(
                    "未找到 active 视觉圣经，请先调用 init-from-narrative",
                    code="no_visual_bible",
                )

            style = await StyleBibleRepository(session).get_active(project_id)

            if subject_type == "character":
                char_ref = await CharacterReferenceRepository(session).get_by_character_id(
                    csv.id, subject_id
                )
                if char_ref is None:
                    raise VisualBibleError(
                        f"角色 {subject_id!r} 不在视觉圣经中", code="character_not_found"
                    )
                item = {
                    "character_id": char_ref.character_id,
                    "character_name": char_ref.character_name,
                    "description": char_ref.description,
                    "appears_in_sections": char_ref.appears_in_sections,
                    "reference_asset_ids": char_ref.reference_asset_ids,
                    "active_reference_asset_id": char_ref.active_reference_asset_id,
                    "base_face_asset_id": char_ref.base_face_asset_id,
                    "image_analysis": char_ref.image_analysis,
                    "costumes": char_ref.costumes,
                }
            else:
                scene_ref = await SceneReferenceRepository(session).get_by_scene_id(
                    csv.id, subject_id
                )
                if scene_ref is None:
                    raise VisualBibleError(
                        f"场景 {subject_id!r} 不在视觉圣经中", code="scene_not_found"
                    )
                item = {
                    "scene_id": scene_ref.scene_id,
                    "scene_name": scene_ref.scene_name,
                    "description": scene_ref.description,
                    "appears_in_sections": scene_ref.appears_in_sections,
                    "reference_asset_ids": scene_ref.reference_asset_ids,
                    "active_reference_asset_id": scene_ref.active_reference_asset_id,
                }

        return csv, style, item

    async def _load_context_for_character(
        self,
        project_id: str,
        user_id: str,
        character_id: str,
    ) -> tuple[CharacterSetVersion, Any, dict]:
        """薄包装，保持现有调用接口不变。"""
        return await self._load_context_for_subject(project_id, user_id, "character", character_id)

    async def _load_context_for_scene(
        self,
        project_id: str,
        user_id: str,
        scene_id: str,
    ) -> tuple[CharacterSetVersion, Any, dict]:
        """薄包装，保持现有调用接口不变。"""
        return await self._load_context_for_subject(project_id, user_id, "scene", scene_id)

    # ------------------------------------------------------------------
    # 内部辅助：回写参考图到 CharacterSetVersion
    # ------------------------------------------------------------------

    async def _update_character_ref(
        self,
        project_id: str,
        csv_id: str,
        character_id: str,
        new_asset_id: str,
    ) -> None:
        """WP4 重写：更新 character_references 独立行的 active 指针和历史列表。

        每个角色是独立行，无并发竞争，不需要 FOR UPDATE 或 flag_modified。
        """
        from app.repositories.character_reference_repository import CharacterReferenceRepository  # noqa: PLC0415

        async with UnitOfWork() as uow:
            repo = CharacterReferenceRepository(uow.session)
            char_ref = await repo.get_by_character_id(csv_id, character_id)
            if char_ref is None:
                return
            # 更新 active 指针
            char_ref.active_reference_asset_id = new_asset_id
            # append 到历史列表
            refs = list(char_ref.reference_asset_ids or [])
            if new_asset_id not in refs:
                refs.append(new_asset_id)
            char_ref.reference_asset_ids = refs
            # 保留多造型字段：不覆盖已有的 base_face_asset_id
            uow.session.add(char_ref)

    async def _update_scene_ref(
        self,
        project_id: str,
        csv_id: str,
        scene_id: str,
        new_asset_id: str,
    ) -> None:
        """WP4 重写：更新 scene_references 独立行的 active 指针和历史列表。

        每个场景是独立行，无并发竞争，不需要 FOR UPDATE 或 flag_modified。
        """
        from app.repositories.scene_reference_repository import SceneReferenceRepository  # noqa: PLC0415

        async with UnitOfWork() as uow:
            repo = SceneReferenceRepository(uow.session)
            scene_ref = await repo.get_by_scene_id(csv_id, scene_id)
            if scene_ref is None:
                return
            # 更新 active 指针
            scene_ref.active_reference_asset_id = new_asset_id
            # append 到历史列表
            refs = list(scene_ref.reference_asset_ids or [])
            if new_asset_id not in refs:
                refs.append(new_asset_id)
            scene_ref.reference_asset_ids = refs
            uow.session.add(scene_ref)

    @staticmethod
    def _resolve_character_generation_mode(character_item: dict, requested_mode: Optional[str]) -> str:
        allowed = {"text_to_image", "image_to_image", "direct"}
        if requested_mode in allowed:
            return requested_mode
        image_analysis = character_item.get("image_analysis") or {}
        recommended = image_analysis.get("recommended_mode")
        if recommended in allowed:
            return recommended
        return "image_to_image" if character_item.get("base_face_asset_id") else "text_to_image"

    @staticmethod
    def _get_character_source_asset_id(character_item: dict) -> str | None:
        return character_item.get("base_face_asset_id") or character_item.get("active_reference_asset_id")

    async def _get_project_asset_url(self, project_id: str, asset_id: str) -> str | None:
        async with UnitOfWork() as uow:
            asset = await AssetRepository(uow.session).get_by_id_for_project(asset_id, project_id)
            if asset is None:
                return None
        storage = get_storage()
        # BUG-05 修复：get_presigned_url 是同步方法且参数顺序错误。
        # 改用 async_get_presigned_url(key, bucket=bucket)。
        return await storage.async_get_presigned_url(asset.object_key, bucket=asset.bucket_name)

    # ------------------------------------------------------------------
    # P3-01：多造型基础接口
    # ------------------------------------------------------------------

    async def analyze_reference_image(
        self,
        asset_id: str,
        project_id: str,
        user_id: str,
        character_id: str | None = None,
    ) -> dict[str, Any]:
        """调用 Omni 分析用户上传的参考图，返回图片类型判断结构。

        Returns:
            {
                "image_type": "realistic_photo" | "illustration" | "ai_generated" | "other",
                "usable_directly": bool,
                "reason": str,
                "recommended_mode": "direct" | "image_to_image" | "text_to_image",
                "face_quality": "high" | "medium" | "low" | "none",
                "requires_costume_generation": bool,
            }
        """
        logger = get_project_logger(project_id, module="services.visual_bible")

        # 获取图片 URL
        async with UnitOfWork() as uow:
            asset = await AssetRepository(uow.session).get_by_id_for_project(asset_id, project_id)
            if asset is None:
                raise VisualBibleError(f"资产 {asset_id!r} 不存在", code="asset_not_found")

        storage = get_storage()
        # BUG-05 修复：get_presigned_url 是同步方法且参数顺序错误。
        # 改用 async_get_presigned_url(key, bucket=bucket)。
        image_url = await storage.async_get_presigned_url(asset.object_key, bucket=asset.bucket_name)

        # CLASS-01 修复：委托给 VisualDevelopmentAgent.analyze_image()
        from app.core.prompt_renderer import PromptRenderer
        renderer = PromptRenderer()
        try:
            prompt_text = renderer.render("omni_image_analysis", {})
        except Exception:
            prompt_text = (
                "分析这张图片，判断它是什么类型的图片（真人照片/插画/AI生成/其他），"
                "是否可以直接用作MV角色参考图，面部质量如何，是否需要重新生成造型。"
                "输出 JSON 格式。"
            )

        result = await self._agent.analyze_image(image_url, prompt_text)
        if character_id:
            await self._store_character_image_analysis(project_id, character_id, asset_id, result)
        logger.info(f"参考图分析完成: asset_id={asset_id!r}", event_type="image_analysis_done")
        return result

    async def _store_character_image_analysis(
        self, project_id: str, character_id: str, asset_id: str, analysis: dict[str, Any]
    ) -> None:
        """WP4 适配：直接 UPDATE character_references 行，不再修改 JSONB。"""
        from app.repositories.character_reference_repository import CharacterReferenceRepository  # noqa: PLC0415

        async with UnitOfWork() as uow:
            csv = await CharacterSetVersionRepository(uow.session).get_active(project_id)
            if csv is None:
                return
            repo = CharacterReferenceRepository(uow.session)
            char_ref = await repo.get_by_character_id(csv.id, character_id)
            if char_ref is None:
                return
            char_ref.image_analysis = analysis
            if analysis.get("face_quality") in ("high", "medium"):
                char_ref.base_face_asset_id = asset_id
            if analysis.get("recommended_mode") == "direct" or analysis.get("usable_directly"):
                refs = list(char_ref.reference_asset_ids or [])
                if asset_id not in refs:
                    refs.append(asset_id)
                char_ref.reference_asset_ids = refs
                char_ref.active_reference_asset_id = asset_id
            uow.session.add(char_ref)

    async def generate_costume_reference(
        self,
        project_id: str,
        user_id: str,
        character_id: str,
        costume_id: str,
        *,
        generation_mode: str = "image_to_image",
        source_image_url: str | None = None,
    ) -> str:
        """基于基础脸图生成特定造型的定妆图，返回 asset_id。"""
        logger = get_project_logger(project_id, module="services.visual_bible")

        csv, style, character_item = await self._load_context_for_character(
            project_id, user_id, character_id
        )

        # 找到目标 costume
        costumes = character_item.get("costumes") or []
        target_costume = next(
            (c for c in costumes if c.get("costume_id") == costume_id),
            None,
        )
        if target_costume is None:
            raise VisualBibleError(
                f"角色 {character_id!r} 中未找到造型 {costume_id!r}",
                code="costume_not_found",
            )

        # 确定源图：优先用 base_face_asset_id，其次用 active_reference_asset_id
        if not source_image_url:
            ref_asset_id = self._get_character_source_asset_id(character_item)
            if ref_asset_id:
                source_image_url = await self._get_project_asset_url(project_id, ref_asset_id)

        # 构建 task_spec 调用 VisualDevelopmentAgent
        style_ref = None
        if style is not None:
            style_ref = await build_ref_from_asset_latest(
                project_id,
                artifact_type="style_bible",
                version_no=style.version_no,
                prefix="style_bible",
                summary=getattr(style, "lighting_style", "") or "style_bible",
            )

        # Bug5 修复：动态计算 version_no（已有定妆图则适当递层，不再硬编码 1）
        _costume_version_no = 2 if target_costume.get("reference_asset_id") else 1
        task_spec = {
            "project_id": project_id,
            "subject_type": "character",
            "subject_id": f"{character_id}_{costume_id}",
            "subject_name": f"{character_item.get('character_name', '')} - {target_costume.get('label', '')}",
            "subject_description": target_costume.get("generation_prompt") or character_item.get("description", ""),
            "generation_mode": generation_mode,
            "source_image_url": source_image_url or "",
            "style_ref": style_ref,
            "version_no": _costume_version_no,
        }

        run_result = await self._agent.run(task_spec)
        asset_id = run_result.get("asset_id", "")
        if not asset_id:
            raise VisualBibleError(
                f"造型参考图生成失败: {run_result.get('error', '未知错误')}",
                code="costume_ref_generation_failed",
            )

        logger.info(
            f"造型参考图生成完成: character={character_id!r} costume={costume_id!r} asset={asset_id!r}",
            event_type="costume_ref_generated",
        )

        # 回写 costume 的 reference_asset_id
        await self._update_costume_ref(project_id, csv.id, character_id, costume_id, asset_id)

        return asset_id

    async def _update_costume_ref(
        self,
        project_id: str,
        csv_id: str,
        character_id: str,
        costume_id: str,
        new_asset_id: str,
    ) -> None:
        """WP4 适配：更新 character_references 行的 costumes JSONB 字段中指定 costume 的 reference_asset_id。"""
        from app.repositories.character_reference_repository import CharacterReferenceRepository  # noqa: PLC0415

        async with UnitOfWork() as uow:
            repo = CharacterReferenceRepository(uow.session)
            char_ref = await repo.get_by_character_id(csv_id, character_id)
            if char_ref is None:
                return
            costumes = list(char_ref.costumes or [])
            for costume in costumes:
                if costume.get("costume_id") == costume_id:
                    costume["reference_asset_id"] = new_asset_id
                    costume["generation_status"] = "ready"  # DESIGN-08
                    break
            char_ref.costumes = costumes
            uow.session.add(char_ref)

    async def _update_costume_status(
        self,
        project_id: str,
        csv_id: str,
        character_id: str,
        costume_id: str,
        status: str,  # "pending" | "ready" | "failed"
    ) -> None:
        """WP4 适配：独立写回 character_references 行的 costumes JSONB 字段中 costume 的 generation_status。"""
        from app.repositories.character_reference_repository import CharacterReferenceRepository  # noqa: PLC0415

        async with UnitOfWork() as uow:
            repo = CharacterReferenceRepository(uow.session)
            char_ref = await repo.get_by_character_id(csv_id, character_id)
            if char_ref is None:
                return
            costumes = list(char_ref.costumes or [])
            for costume in costumes:
                if costume.get("costume_id") == costume_id:
                    costume["generation_status"] = status
                    break
            char_ref.costumes = costumes
            uow.session.add(char_ref)

    # ------------------------------------------------------------------
    # P5-01：Omni 驱动自动化多造型设置
    # Bug8 修复：删除未使用的死代码 _get_costume_for_section()。
    # 造型按段落匹配的实际逻辑在 shot_plan_persistence_service._build_visual_bible_map() 中完成。
    # ------------------------------------------------------------------

    async def auto_analyze_and_setup_costumes(
        self,
        project_id: str,
        user_id: str,
        *,
        skip_image_analysis: bool = False,
    ) -> dict[str, Any]:
        """完整的 Omni 驱动多造型设置流程。

        WP4 适配：从独立表读取角色/场景数据，持久化 costumes 到 character_references 行。

        流程：
          1. 读取 active NarrativeScript + CharacterSetVersion + StyleBible
          2. 对每个角色：
             a. 分析参考图（如有）-> 设置 base_face_asset_id + image_analysis
             b. 推导造型列表 -> 写入 costumes
             c. 为每套造型生成定妆图
          3. 返回处理结果摘要
        """
        from app.repositories.character_reference_repository import CharacterReferenceRepository  # noqa: PLC0415
        from app.repositories.scene_reference_repository import SceneReferenceRepository  # noqa: PLC0415

        logger = get_project_logger(project_id, module="services.visual_bible")

        async with UnitOfWork() as uow:
            session = uow.session
            project = await ProjectRepository(session).get_by_id_for_user(project_id, user_id)
            if project is None:
                raise VisualBibleError("项目不存在", code="project_not_found")

            narrative = await NarrativeScriptVersionRepository(session).get_active(project_id)
            csv = await CharacterSetVersionRepository(session).get_active(project_id)
            style = await StyleBibleRepository(session).get_active(project_id)

        if csv is None:
            raise VisualBibleError("未找到 active 视觉圣经", code="no_visual_bible")
        if narrative is None:
            raise VisualBibleError("未找到 active 叙事剧本", code="no_narrative")

        # WP4: 从独立表读取角色数据，转换为 dict 列表供后续处理
        async with UnitOfWork() as uow:
            char_refs = await CharacterReferenceRepository(uow.session).list_by_version(csv.id)
            scene_refs = await SceneReferenceRepository(uow.session).list_by_version(csv.id)

        characters: list[dict[str, Any]] = [
            {
                "character_id": c.character_id,
                "character_name": c.character_name,
                "description": c.description,
                "appears_in_sections": c.appears_in_sections,
                "reference_asset_ids": c.reference_asset_ids,
                "active_reference_asset_id": c.active_reference_asset_id,
                "base_face_asset_id": c.base_face_asset_id,
                "image_analysis": c.image_analysis,
                "costumes": c.costumes,
            }
            for c in char_refs
        ]

        results: list[dict[str, Any]] = []

        logger.info(
            f"多造型自动设置开始: {len(characters)} 个角色",
            event_type="auto_costumes_start",
        )

        for char_item in characters:
            char_id = char_item.get("character_id", "")
            char_result: dict[str, Any] = {
                "character_id": char_id,
                "character_name": char_item.get("character_name", ""),
            }

            # a. 分析参考图
            if not skip_image_analysis:
                ref_asset_id = char_item.get("active_reference_asset_id")
                if ref_asset_id:
                    try:
                        analysis = await self.analyze_reference_image(ref_asset_id, project_id, user_id)
                        char_item["image_analysis"] = analysis
                        if analysis.get("face_quality") in ("high", "medium"):
                            char_item["base_face_asset_id"] = ref_asset_id
                        char_result["image_analysis"] = analysis
                    except Exception as exc:
                        logger.warning(f"角色 {char_id} 图片分析失败: {exc!r}")
                        char_result["image_analysis_error"] = str(exc)

            # b. 推导造型列表
            try:
                costumes = await self._derive_costumes_from_narrative(
                    project_id, narrative, char_item, style
                )
                char_item["costumes"] = costumes
                char_result["costumes_count"] = len(costumes)
            except Exception as exc:
                logger.warning(f"角色 {char_id} 造型推导失败: {exc!r}")
                char_result["costumes_error"] = str(exc)
                costumes = []

            results.append(char_result)

        # WP4: 持久化 costumes 到 character_references 独立表
        async with UnitOfWork() as uow:
            repo = CharacterReferenceRepository(uow.session)
            for char_item in characters:
                char_id = char_item.get("character_id", "")
                char_ref = await repo.get_by_character_id(csv.id, char_id)
                if char_ref is not None:
                    char_ref.costumes = char_item.get("costumes", [])
                    if char_item.get("image_analysis") is not None:
                        char_ref.image_analysis = char_item["image_analysis"]
                    if char_item.get("base_face_asset_id") is not None:
                        char_ref.base_face_asset_id = char_item["base_face_asset_id"]
                    uow.session.add(char_ref)

        # c. 为每套造型生成定妆图（必须在 costumes 已持久化之后）
        semaphore = asyncio.Semaphore(5)

        async def _generate_single_costume(char_id: str, costume_id: str, gen_mode: str) -> bool:
            async with semaphore:
                try:
                    await self.generate_costume_reference(
                        project_id, user_id, char_id, costume_id,
                        generation_mode=gen_mode,
                    )
                    return True
                except Exception as exc:
                    logger.warning(f"造型 {costume_id} 生成失败: {exc!r}")
                    # DESIGN-08 修复：将失败造型标记为 failed，便于后续重试筛选
                    try:
                        await self._update_costume_status(
                            project_id, csv.id, char_id, costume_id, "failed"
                        )
                    except Exception:
                        pass
                    return False

        tasks = []
        task_indices = []  # 记录每个任务属于哪个角色

        for i, char_item in enumerate(characters):
            char_id = char_item.get("character_id", "")
            costumes = char_item.get("costumes") or []
            for costume in costumes:
                costume_id = costume.get("costume_id", "")
                gen_mode = "image_to_image" if char_item.get("base_face_asset_id") else "text_to_image"
                tasks.append(_generate_single_costume(char_id, costume_id, gen_mode))
                task_indices.append(i)

        gen_results = await asyncio.gather(*tasks)

        # 统计每个角色生成的定妆图数量
        generated_counts = {i: 0 for i in range(len(characters))}
        for idx, success in zip(task_indices, gen_results):
            if success:
                generated_counts[idx] += 1

        for i in range(len(characters)):
            results[i]["generated_costume_refs"] = generated_counts[i]

        logger.info(
            f"多造型自动设置完成: {len(results)} 个角色",
            event_type="auto_costumes_done",
        )

        # WP4: 从独立表读取场景数据，并发生成场景参考图
        scene_tasks = []

        async def _generate_single_scene(scene_id: str) -> bool:
            async with semaphore:
                try:
                    await self.generate_scene_reference(
                        project_id, user_id, scene_id
                    )
                    return True
                except Exception as exc:
                    logger.warning(f"场景 {scene_id} 生成失败: {exc!r}")
                    return False

        for scene_ref in scene_refs:
            if scene_ref.scene_id:
                scene_tasks.append(_generate_single_scene(scene_ref.scene_id))

        if scene_tasks:
            await asyncio.gather(*scene_tasks)

        # 在所有造型和场景生成完毕后，推进状态
        async with UnitOfWork() as uow:
            project = await ProjectRepository(uow.session).get_by_id_for_user(project_id, user_id)
            if project and project.current_stage != ProjectStage.VISUAL_BIBLE_READY.value:
                await state_transition_service.advance_project(
                    uow.session, project, ProjectStage.VISUAL_BIBLE_READY
                )

        return {"characters": results, "total_characters": len(results)}

    async def _derive_costumes_from_narrative(
        self,
        project_id: str,
        narrative: Any,
        character_item: dict,
        style: Any,
    ) -> list[dict]:
        """调用 Omni 从叙事剧本+风格圣经推导角色在各段落的造型列表。"""
        char_name = character_item.get("character_name", "")
        char_desc = character_item.get("description", "")
        sections = character_item.get("appears_in_sections", [])

        # 从叙事剧本获取段落信息
        section_details: list[dict[str, str]] = []
        for sec in (narrative.section_mapping or []):
            sec_type = sec.get("section_type", "")
            if sec_type in sections or not sections:
                section_details.append({
                    "section_type": sec_type,
                    "emotion": sec.get("emotion", ""),
                    "narrative_beat": sec.get("narrative_beat", ""),
                })

        style_desc = ""
        if style is not None:
            style_desc = getattr(style, "lighting_style", "") or ""

        # CLASS-01 修复：委托给 VisualDevelopmentAgent.derive_costumes()
        from app.core.prompt_renderer import PromptRenderer
        renderer = PromptRenderer()
        try:
            prompt_text = renderer.render("omni_costume_derivation", {
                "character_name": char_name,
                "character_description": char_desc,
                "sections": json.dumps(section_details, ensure_ascii=False),
                "style_description": style_desc,
            })
        except Exception:
            prompt_text = (
                f"角色「{char_name}」({char_desc}) 出现在以下段落中：{section_details}。"
                f"风格方向：{style_desc}。"
                "请为这个角色推导出适合各段落的造型列表，每套造型包含 costume_id、label、"
                "applies_to_sections、generation_prompt。输出 JSON 数组。"
            )
        # derive_costumes 内部包含冖底处理和 Bug9 标签安全化逻辑
        return await self._agent.derive_costumes(prompt_text)

    # _load_omni_config 已迁移至 app.utils.omni_config.load_omni_config()，不再重复定义。
