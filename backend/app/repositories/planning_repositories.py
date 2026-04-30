"""规划相关 Repository 实现。

覆盖五张规划表的基础查询：
  CreativeBriefRepository  — creative_brief_versions
  StyleBibleRepository     — style_bible_versions
  ScenePlanRepository      — scene_plan_versions
  ShotPlanRepository       — shot_plan_versions
  ShotRepository           — shots

查询模式遵循 ProjectSpecRepository 规范：
  - get_active(project_id)       获取当前激活版本
  - get_next_version_no(project_id)  计算下一版本号
  - deactivate_all(project_id)   失活全部旧版本（激活新版本前调用）
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.planning import (
    CreativeBriefVersion,
    ScenePlanVersion,
    Shot,
    ShotPlanVersion,
    StyleBibleVersion,
)
from app.repositories.base import BaseRepository


# ---------------------------------------------------------------------------
# CreativeBriefRepository
# ---------------------------------------------------------------------------

class CreativeBriefRepository(BaseRepository[CreativeBriefVersion]):
    """创意简报版本表查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CreativeBriefVersion)

    async def get_active(self, project_id: str) -> Optional[CreativeBriefVersion]:
        """获取当前激活的创意简报版本。"""
        stmt = (
            select(CreativeBriefVersion)
            .where(
                CreativeBriefVersion.project_id == project_id,
                CreativeBriefVersion.is_active.is_(True),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_next_version_no(self, project_id: str) -> int:
        """计算下一个版本号（当前最大 version_no + 1，从 1 开始）。"""
        stmt = select(func.max(CreativeBriefVersion.version_no)).where(
            CreativeBriefVersion.project_id == project_id
        )
        result = await self._session.execute(stmt)
        max_no: int | None = result.scalar_one_or_none()
        return (max_no or 0) + 1

    async def deactivate_all(self, project_id: str) -> None:
        """将该项目所有版本 is_active 置为 False（激活新版本前调用）。"""
        stmt = (
            update(CreativeBriefVersion)
            .where(
                CreativeBriefVersion.project_id == project_id,
                CreativeBriefVersion.is_active.is_(True),
            )
            .values(is_active=False)
        )
        await self._session.execute(stmt)

    async def get_by_id_for_project(
        self, version_id: str, project_id: str
    ) -> Optional[CreativeBriefVersion]:
        """按 ID 查询，同时验证项目归属。"""
        stmt = select(CreativeBriefVersion).where(
            CreativeBriefVersion.id == version_id,
            CreativeBriefVersion.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# StyleBibleRepository
# ---------------------------------------------------------------------------

class StyleBibleRepository(BaseRepository[StyleBibleVersion]):
    """风格圣经版本表查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, StyleBibleVersion)

    async def get_active(self, project_id: str) -> Optional[StyleBibleVersion]:
        """获取当前激活的风格圣经版本。"""
        stmt = (
            select(StyleBibleVersion)
            .where(
                StyleBibleVersion.project_id == project_id,
                StyleBibleVersion.is_active.is_(True),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_next_version_no(self, project_id: str) -> int:
        stmt = select(func.max(StyleBibleVersion.version_no)).where(
            StyleBibleVersion.project_id == project_id
        )
        result = await self._session.execute(stmt)
        max_no: int | None = result.scalar_one_or_none()
        return (max_no or 0) + 1

    async def deactivate_all(self, project_id: str) -> None:
        stmt = (
            update(StyleBibleVersion)
            .where(
                StyleBibleVersion.project_id == project_id,
                StyleBibleVersion.is_active.is_(True),
            )
            .values(is_active=False)
        )
        await self._session.execute(stmt)

    async def get_by_id_for_project(
        self, version_id: str, project_id: str
    ) -> Optional[StyleBibleVersion]:
        stmt = select(StyleBibleVersion).where(
            StyleBibleVersion.id == version_id,
            StyleBibleVersion.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# ScenePlanRepository
# ---------------------------------------------------------------------------

class ScenePlanRepository(BaseRepository[ScenePlanVersion]):
    """场景规划版本表查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ScenePlanVersion)

    async def get_active(self, project_id: str) -> Optional[ScenePlanVersion]:
        """获取当前激活的场景规划版本。"""
        stmt = (
            select(ScenePlanVersion)
            .where(
                ScenePlanVersion.project_id == project_id,
                ScenePlanVersion.is_active.is_(True),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_next_version_no(self, project_id: str) -> int:
        stmt = select(func.max(ScenePlanVersion.version_no)).where(
            ScenePlanVersion.project_id == project_id
        )
        result = await self._session.execute(stmt)
        max_no: int | None = result.scalar_one_or_none()
        return (max_no or 0) + 1

    async def deactivate_all(self, project_id: str) -> None:
        stmt = (
            update(ScenePlanVersion)
            .where(
                ScenePlanVersion.project_id == project_id,
                ScenePlanVersion.is_active.is_(True),
            )
            .values(is_active=False)
        )
        await self._session.execute(stmt)

    async def get_by_id_for_project(
        self, version_id: str, project_id: str
    ) -> Optional[ScenePlanVersion]:
        stmt = select(ScenePlanVersion).where(
            ScenePlanVersion.id == version_id,
            ScenePlanVersion.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# ShotPlanRepository
# ---------------------------------------------------------------------------

class ShotPlanRepository(BaseRepository[ShotPlanVersion]):
    """镜头方案版本表查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ShotPlanVersion)

    async def get_active(self, project_id: str) -> Optional[ShotPlanVersion]:
        """获取当前激活的镜头方案版本。"""
        stmt = (
            select(ShotPlanVersion)
            .where(
                ShotPlanVersion.project_id == project_id,
                ShotPlanVersion.is_active.is_(True),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_next_version_no(self, project_id: str) -> int:
        stmt = select(func.max(ShotPlanVersion.version_no)).where(
            ShotPlanVersion.project_id == project_id
        )
        result = await self._session.execute(stmt)
        max_no: int | None = result.scalar_one_or_none()
        return (max_no or 0) + 1

    async def deactivate_all(self, project_id: str) -> None:
        stmt = (
            update(ShotPlanVersion)
            .where(
                ShotPlanVersion.project_id == project_id,
                ShotPlanVersion.is_active.is_(True),
            )
            .values(is_active=False)
        )
        await self._session.execute(stmt)

    async def get_by_id_for_project(
        self, version_id: str, project_id: str
    ) -> Optional[ShotPlanVersion]:
        stmt = select(ShotPlanVersion).where(
            ShotPlanVersion.id == version_id,
            ShotPlanVersion.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# ShotRepository
# ---------------------------------------------------------------------------

class ShotRepository(BaseRepository[Shot]):
    """镜头表查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Shot)

    async def list_by_plan(self, shot_plan_version_id: str) -> List[Shot]:
        """查询某个镜头方案版本下的所有镜头（按 shot_index 升序）。"""
        stmt = (
            select(Shot)
            .where(Shot.shot_plan_version_id == shot_plan_version_id)
            .order_by(Shot.shot_index)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_project(
        self,
        project_id: str,
        *,
        status_filter: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Shot]:
        """查询某项目下的镜头列表（支持状态过滤，按 shot_index 排序）。"""
        stmt = select(Shot).where(Shot.project_id == project_id)
        if status_filter is not None:
            stmt = stmt.where(Shot.status == status_filter)
        stmt = stmt.order_by(Shot.shot_index).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id_for_project(
        self, shot_id: str, project_id: str
    ) -> Optional[Shot]:
        """按 ID 查询镜头，同时验证项目归属。"""
        stmt = select(Shot).where(
            Shot.id == shot_id,
            Shot.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_by_project(self, project_id: str) -> int:
        """统计项目下的镜头总数。"""
        stmt = (
            select(func.count())
            .select_from(Shot)
            .where(Shot.project_id == project_id)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())
