"""ProjectSpec Service — 项目输入规格版本化管理。

来源文档：doc 05 §9.1（project_spec_versions）、doc 04 §4（项目状态机）

职责：
  - 创建新 ProjectSpec 版本（不自动激活）
  - 激活指定版本（失活旧版本，更新 projects.active_project_spec_version_id）
  - 激活后自动检查是否满足 input_ready 三个条件，满足则调用状态机推进

input_ready 推进条件（doc 04 §4.2 input_ready）：
  1. audio_asset_id 不为空（已上传音频）
  2. audio_end_sec > audio_start_sec（有效时间区间，且 end > 0）
  3. user_prompt 不为空（有创意描述）

所有写操作使用同一个 UoW 事务，确保版本激活 + 项目 active 指针更新 + 状态推进原子落库。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_project_logger
from app.domain.states import ProjectStage
from app.models.project import Project
from app.models.project_spec_version import ProjectSpecVersion
from app.repositories.asset_repository import AssetRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.project_spec_repository import ProjectSpecRepository
from app.repositories.unit_of_work import UnitOfWork
from app.services.state_transition_service import StateTransitionService
from app.services.output_spec_service import normalize_output_config
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.path_planner import ArtifactStage

_state_svc = StateTransitionService()


class ProjectSpecError(Exception):
    """项目规格版本业务异常。"""
    def __init__(self, message: str, code: str = "spec_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _spec_to_dict(spec: ProjectSpecVersion) -> dict:
    """将 ProjectSpecVersion ORM 对象转为 API 响应 dict。"""
    return {
        "id": spec.id,
        "project_id": spec.project_id,
        "version_no": spec.version_no,
        "input_mode": spec.input_mode,
        "audio_asset_id": spec.audio_asset_id,
        "audio_start_sec": float(spec.audio_start_sec) if spec.audio_start_sec is not None else 0.0,
        "audio_end_sec": float(spec.audio_end_sec) if spec.audio_end_sec is not None else 0.0,
        "user_prompt": spec.user_prompt,
        "reference_image_asset_ids": spec.reference_image_asset_ids or [],
        "output_config": spec.output_config,
        "constraints": spec.constraints,
        "created_by": spec.created_by,
        "source_event_id": spec.source_event_id,
        "is_active": spec.is_active,
        "created_at": spec.created_at.isoformat() if spec.created_at else None,
    }


def normalize_product_reference_asset_ids(value: object) -> list[str]:
    """规范化产品参考图 asset_id 列表，最多 3 张。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProjectSpecError(
            "product_reference_asset_ids 必须是 asset_id 字符串列表",
            code="validation_error",
        )
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        if text not in result:
            result.append(text)
        if len(result) > 3:
            raise ProjectSpecError(
                "产品图最多只能上传 3 张",
                code="too_many_product_images",
            )
    return result


class ProjectSpecService:
    """项目输入规格版本服务。"""

    # ------------------------------------------------------------------ #
    # 创建新版本
    # ------------------------------------------------------------------ #

    async def create_version(
        self,
        project_id: str,
        user_id: str,
        *,
        input_mode: str = "audio_text",
        audio_asset_id: Optional[str] = None,
        audio_start_sec: float = 0.0,
        audio_end_sec: float = 0.0,
        user_prompt: str = "",
        reference_image_asset_ids: Optional[list] = None,
        output_config: Optional[dict] = None,
        constraints: Optional[dict] = None,
        created_by: str = "user",
    ) -> dict:
        """创建新 ProjectSpec 版本（不自动激活，需要显式调用 activate_version）。

        Args:
            project_id:      目标项目 ID。
            user_id:         当前用户 ID（用于归属校验）。
            input_mode:      输入模式（audio_text / audio_image_text）。
            audio_asset_id:  音频资产 ID（可后续通过 activate 时补充）。
            audio_start_sec: 音频起始时间（秒）。
            audio_end_sec:   音频结束时间（秒）。
            user_prompt:     用户创意描述。
            output_config:   输出配置（画幅比例、分辨率、目标时长等）。
            constraints:     附加约束。
            created_by:      创建者标识（'user' / 'system'）。

        Returns:
            spec dict（is_active=False）。

        Raises:
            ProjectSpecError: 项目不存在 / input_mode 非法。

        注：若 audio_end_sec=0 且传了 audio_asset_id，会自动查询 Asset.duration_ms 回填（16-01）。
        """
        # 校验 input_mode
        if input_mode not in ("audio_text", "audio_image_text", "text_only"):
            raise ProjectSpecError(
                f"不支持的 input_mode: {input_mode!r}，只允许 audio_text / audio_image_text / text_only",
                code="validation_error",
            )

        async with UnitOfWork() as uow:
            # 验证项目归属
            project = await self._get_project(uow.session, project_id, user_id)

            spec_repo = ProjectSpecRepository(uow.session)
            version_no = await spec_repo.get_next_version_no(project_id)

            # input_mode 自动推断：有参考图且未指定模式时自动切换
            _ref_ids = [r for r in (reference_image_asset_ids or []) if r]
            if _ref_ids and input_mode == "audio_text":
                input_mode = "audio_image_text"

            # 16-01：audio_end_sec 自动检测——用户不传或传 0 时，从已上传音频 Asset 读取实际时长
            if audio_end_sec == 0.0 and audio_asset_id:
                _asset = await AssetRepository(uow.session).get_by_id(audio_asset_id)
                if _asset and _asset.duration_ms:
                    audio_end_sec = _asset.duration_ms / 1000.0

            spec = ProjectSpecVersion(
                project_id=project_id,
                version_no=version_no,
                input_mode=input_mode,
                audio_asset_id=audio_asset_id,
                audio_start_sec=audio_start_sec,
                audio_end_sec=audio_end_sec,
                user_prompt=user_prompt,
                reference_image_asset_ids=_ref_ids,
                output_config=normalize_output_config(output_config),
                constraints=constraints or {},
                created_by=created_by,
                is_active=False,
            )
            await spec_repo.add(spec)
            await uow.flush()
            await uow.session.refresh(spec)

        logger = get_project_logger(project_id, module="services.project_spec")
        logger.info(
            f"ProjectSpec version created: id={spec.id!r} v={version_no} mode={input_mode!r}",
            event_type="project_spec_version_created",
        )
        return _spec_to_dict(spec)

    # ------------------------------------------------------------------ #
    # 激活版本（5-04 入口）
    # ------------------------------------------------------------------ #

    async def activate_version(
        self,
        project_id: str,
        user_id: str,
        version_id: str,
    ) -> dict:
        """激活指定 ProjectSpec 版本，并在满足条件时推进项目到 input_ready。

        原子操作（单事务）：
          1. 将该项目所有旧版本 is_active 置 False
          2. 将目标版本 is_active 置 True
          3. 更新 projects.active_project_spec_version_id
          4. 若满足 input_ready 三个条件，调用状态机推进

        Args:
            project_id:  目标项目 ID。
            user_id:     当前用户 ID。
            version_id:  要激活的版本 ID。

        Returns:
            激活后的 spec dict（is_active=True）。

        Raises:
            ProjectSpecError: 版本不存在 / 项目不存在。
        """
        async with UnitOfWork() as uow:
            # 1. 验证项目归属
            project = await self._get_project(uow.session, project_id, user_id)

            spec_repo = ProjectSpecRepository(uow.session)

            # 2. 查找目标版本
            spec = await spec_repo.get_by_id_for_project(version_id, project_id)
            if spec is None:
                raise ProjectSpecError("ProjectSpec 版本不存在", code="not_found")

            # 3. 失活旧版本（批量 UPDATE）
            await spec_repo.deactivate_all(project_id)

            # 4. 激活新版本
            spec.is_active = True
            uow.session.add(spec)

            # 5. 更新 projects.active_project_spec_version_id
            project.active_project_spec_version_id = spec.id
            uow.session.add(project)

            # 6. 检查并推进 input_ready（5-04 逻辑）
            if self._can_advance_to_input_ready(project, spec):
                await _state_svc.advance_project(
                    uow.session,
                    project,
                    ProjectStage.INPUT_READY,
                    emit_event=True,
                )

            await uow.flush()
            await uow.session.refresh(spec)

        # 本地保存规格快照（追溯用）
        try:
            store = LocalArtifactStore(project_id)
            store.write_json(
                ArtifactStage.INPUT,
                f"project_spec_v{spec.version_no}",
                _spec_to_dict(spec),
                version=spec.version_no,
            )
        except Exception as exc:
            get_project_logger(project_id, module="services.project_spec").warning(
                f"规格快照写入失败（不影响业务）: {exc}",
                event_type="spec_snapshot_failed",
            )

        logger = get_project_logger(project_id, module="services.project_spec")
        logger.info(
            f"ProjectSpec activated: id={spec.id!r} v={spec.version_no}",
            event_type="project_spec_activated",
        )
        return _spec_to_dict(spec)

    # ------------------------------------------------------------------ #
    # 获取当前激活版本
    # ------------------------------------------------------------------ #

    async def get_active_version(self, project_id: str, user_id: str) -> dict:
        """获取项目当前激活的 ProjectSpec 版本详情。

        Raises:
            ProjectSpecError: 项目不存在 / 尚无激活版本。
        """
        async with UnitOfWork() as uow:
            await self._get_project(uow.session, project_id, user_id)
            spec_repo = ProjectSpecRepository(uow.session)
            spec = await spec_repo.get_active(project_id)

        if spec is None:
            raise ProjectSpecError(
                "该项目尚无激活的 ProjectSpec 版本", code="not_found"
            )
        return _spec_to_dict(spec)

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _get_project(
        session: AsyncSession, project_id: str, user_id: str
    ) -> Project:
        """验证项目归属，返回 Project 对象。"""
        repo = ProjectRepository(session)
        project = await repo.get_by_id_for_user(project_id, user_id)
        if project is None:
            raise ProjectSpecError("项目不存在", code="not_found")
        return project

    @staticmethod
    def _can_advance_to_input_ready(project: Project, spec: ProjectSpecVersion) -> bool:
        """判断是否满足 input_ready 推进条件（doc 04 §4.2）。

        条件（已简化）：
          1. audio_asset_id 不为空（已上传音频，必须项）

        设计变更说明：
          - user_prompt 已改为可选：用户可不填创意描述，Director 仍可工作
          - audio_end_sec=0 表示「使用全曲」，由 trim_audio 工具处理，不作为门控
          - 两项均从推进条件移除，避免门控过严导致项目永远停在 created 阶段

        只有项目当前处于 created 时才推进（created → input_ready）。
        已经是 input_ready 或更高阶段时不重复推进（幂等保护）。
        """
        if project.current_stage != ProjectStage.CREATED.value:
            return False
        # 新流程（AI视频内容生成）：只需要 user_prompt 不为空即可推进
        can_push_to_input_ready = bool(spec.user_prompt)
        # 旧流程（音乐MV模式）条件已停用（注释保留）：
        # can_push_to_input_ready = (
        #     bool(spec.audio_asset_id) and
        #     float(spec.audio_end_sec or 0) > float(spec.audio_start_sec or 0) and
        #     bool(spec.user_prompt)
        # )
        return can_push_to_input_ready
