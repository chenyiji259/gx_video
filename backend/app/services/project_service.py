"""Project Service — 项目业务逻辑。

本组只实现最小 CRUD：
  - create_project()
  - get_project()
  - list_projects()
  - update_project()（重命名/归档）

工程约束：
  - 所有操作必须携带 user_id（R4 用户隔离）
  - 不直接操作 session，通过 UoW 管理事务（doc 08 §4）
  - 状态机推进（input_ready 等）留给后续 Group 4+
"""
from __future__ import annotations

import asyncio
import shutil

from app.core.logging import get_project_logger
from app.models.project import Project
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.utils.ids import generate_ulid


class ProjectError(Exception):
    """项目业务异常。"""
    def __init__(self, message: str, code: str = "project_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# 阶段进度映射 (用于前端进度条显示)
STAGE_PROGRESS = {
    "created": 0,
    "input_ready": 10,
    "audio_analyzed": 20,
    "brief_ready": 30,
    "narrative_ready": 40,
    "visual_bible_ready": 50,
    "shot_plan_ready": 60,
    "storyboard_ready": 70,
    "clips_ready": 80,
    "timeline_ready": 90,
    "export_ready": 95,
    "completed": 100,
    "failed": -1
}


def _project_to_dict(p: Project) -> dict:
    """将 Project ORM 对象转为 API 响应 dict。"""
    return {
        "id": p.id,
        "name": p.name,
        "status": p.status,
        "archived": p.status == "archived",
        "current_stage": p.current_stage,
        "progress_percentage": STAGE_PROGRESS.get(p.current_stage, 0),
        "cover_url": getattr(p, "cover_url", None),
        # active version 指针（前端需要用于展示 Pipeline 阶段摘要）
        "active_versions": {
            "project_spec": p.active_project_spec_version_id,
            "audio_analysis": p.active_audio_analysis_version_id,
            "creative_brief": p.active_brief_version_id,
            "style_bible": p.active_style_version_id,
            "character_set": p.active_character_set_version_id,
            "narrative_script": p.active_narrative_script_version_id,
            "scene_plan": p.active_scene_plan_version_id,
            "shot_plan": p.active_shot_plan_version_id,
            "storyboard": p.active_storyboard_version_id,
            "timeline": p.active_timeline_version_id,
            "latest_export": p.latest_export_version_id,
        },
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


class ProjectService:
    """项目服务。所有操作必须提供 user_id，保证用户隔离。"""

    # ------------------------------------------------------------------ #
    # 创建项目
    # ------------------------------------------------------------------ #

    async def create_project(self, user_id: str, name: str) -> dict:
        """创建新项目，初始 stage 为 'created'。

        Args:
            user_id: 当前登录用户 ID。
            name: 项目名称，长度 1-255 字符。

        Returns:
            project dict（见 _project_to_dict）。

        Raises:
            ProjectError: 名称格式非法。
        """
        name = name.strip()
        if not name:
            raise ProjectError("项目名称不能为空", code="validation_error")
        if len(name) > 255:
            raise ProjectError("项目名称过长（最多 255 字符）", code="validation_error")

        async with UnitOfWork() as uow:
            repo = ProjectRepository(uow.session)
            project = Project(
                id=generate_ulid(),
                user_id=user_id,
                name=name,
                status="active",
                current_stage="created",
            )
            await repo.add(project)
            await uow.flush()
            await uow.session.refresh(project)

        logger = get_project_logger(project.id, module="services.project")
        logger.info(
            f"Project created: name={name!r}",
            event_type="project_created",
        )
        return _project_to_dict(project)

    # ------------------------------------------------------------------ #
    # 获取项目详情
    # ------------------------------------------------------------------ #

    async def get_project(self, project_id: str, user_id: str) -> dict:
        """查询单个项目，验证归属。

        Raises:
            ProjectError: 项目不存在或不属于该用户（统一 not_found，防止 ID 枚举）。
        """
        async with UnitOfWork() as uow:
            repo = ProjectRepository(uow.session)
            project = await repo.get_by_id_for_user(project_id, user_id)

        if project is None:
            raise ProjectError("项目不存在", code="not_found")

        return _project_to_dict(project)

    # ------------------------------------------------------------------ #
    # 项目列表
    # ------------------------------------------------------------------ #

    async def list_projects(
        self,
        user_id: str,
        *,
        limit: int = 20,
        after_id: str | None = None,
        include_archived: bool = False,
    ) -> dict:
        """查询用户的项目列表（doc 05 §17.4 分页规范）。

        Returns:
            {"items": [...], "has_more": bool}
        """
        limit = max(1, min(limit, 100))

        async with UnitOfWork() as uow:
            repo = ProjectRepository(uow.session)
            # 多取一条用于判断 has_more
            projects = await repo.list_by_user(
                user_id,
                limit=limit + 1,
                after_id=after_id,
                include_archived=include_archived,
            )

        has_more = len(projects) > limit
        items = projects[:limit]

        return {
            "items": [_project_to_dict(p) for p in items],
            "has_more": has_more,
        }

    # ------------------------------------------------------------------ #
    # 更新项目（重命名/归档）
    # ------------------------------------------------------------------ #

    async def update_project(
        self,
        project_id: str,
        user_id: str,
        *,
        name: str | None = None,
        archived: bool | None = None,
    ) -> dict:
        """更新项目名称或归档状态。

        doc 05 §17.4 PATCH /projects/{id}：只允许改 name 和 archived。
        状态机推进由工作流接口负责，不在这里处理。

        Raises:
            ProjectError: 项目不存在、名称非法。
        """
        if name is not None:
            name = name.strip()
            if not name:
                raise ProjectError("项目名称不能为空", code="validation_error")
            if len(name) > 255:
                raise ProjectError("项目名称过长（最多 255 字符）", code="validation_error")

        async with UnitOfWork() as uow:
            repo = ProjectRepository(uow.session)
            project = await repo.get_by_id_for_user(project_id, user_id)

            if project is None:
                raise ProjectError("项目不存在", code="not_found")

            if name is not None:
                project.name = name

            if archived is True and project.status == "active":
                project.status = "archived"
            elif archived is False and project.status == "archived":
                project.status = "active"

            await uow.flush()
            await uow.session.refresh(project)

        return _project_to_dict(project)

    # ------------------------------------------------------------------ #
    # 删除项目
    # ------------------------------------------------------------------ #

    async def delete_project(self, project_id: str, user_id: str) -> bool:
        """从系统中永久删除项目及所有关联产物。

        清理顺序：
          1. MinIO：删除 projects/{project_id}/ 前缀下的所有对象
          2. 本地磁盘：递归删除 data/projects/{project_id}/ 目录
          3. 数据库：删除 projects 行（ON DELETE CASCADE 自动清理所有关联表）

        第 1、2 步失败只记日志，不阻断第 3 步（确保数据库始终保持干净）。
        """
        logger = get_project_logger(project_id, module="services.project")

        # --- 前置校验：项目归属 ---
        async with UnitOfWork() as uow:
            repo = ProjectRepository(uow.session)
            project = await repo.get_by_id_for_user(project_id, user_id)
            if project is None:
                raise ProjectError("项目不存在", code="not_found")

        # --- Step 1: 清理 MinIO（删除整个项目前缀）---
        try:
            from app.storage.minio_adapter import get_storage  # noqa: PLC0415
            storage = get_storage()
            prefix = f"projects/{project_id}/"
            deleted_count = await storage.async_delete_prefix(prefix)
            logger.info(
                f"MinIO 清理完成: 已删除 {deleted_count} 个对象（前缀 {prefix!r}）",
                event_type="project_minio_cleaned",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"MinIO 清理失败（不阻断删除流程）: {exc!r}",
                event_type="project_minio_clean_failed",
            )

        # --- Step 2: 清理本地磁盘 ---
        try:
            from app.storage.local_artifact_store import LocalArtifactStore  # noqa: PLC0415
            project_dir = LocalArtifactStore(project_id).project_dir
            if project_dir.exists():
                await asyncio.to_thread(shutil.rmtree, str(project_dir), True)
                logger.info(
                    f"本地目录已删除: {project_dir}",
                    event_type="project_local_cleaned",
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"本地目录清理失败（不阻断删除流程）: {exc!r}",
                event_type="project_local_clean_failed",
            )

        # --- Step 3: 数据库物理删除（CASCADE 自动清理所有关联表）---
        async with UnitOfWork() as uow:
            repo = ProjectRepository(uow.session)
            project = await repo.get_by_id_for_user(project_id, user_id)
            if project is not None:
                await repo.delete(project)

        logger.info(
            "Project deleted permanently with full cleanup",
            event_type="project_deleted",
        )
        return True

    # ------------------------------------------------------------------ #
    # Dashboard 概览
    # ------------------------------------------------------------------ #

    async def get_dashboard_summary(self, user_id: str) -> dict:
        """获取用户 Dashboard 概览数据。"""
        async with UnitOfWork() as uow:
            repo = ProjectRepository(uow.session)
            # 获取最近 5 个活跃项目
            recent_projects = await repo.list_by_user(
                user_id,
                limit=5,
                include_archived=False,
            )
            
            # 统计数据（简单版，后续可增加视频总时长等）
            total_active = len(recent_projects)  # 这里的 limit 会影响，但在 repository 里是全量 list 才有真实值
            # 真实统计应在 repo 里加 count 方法，此处先简化
            
        return {
            "recent_projects": [_project_to_dict(p) for p in recent_projects],
            "stats": {
                "total_projects": len(recent_projects), # 占位
                "total_clips": 0, # 占位
                "credits_balance": 200, # 占位
            }
        }
