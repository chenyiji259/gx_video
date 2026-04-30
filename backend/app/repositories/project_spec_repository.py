"""ProjectSpec Repository — 项目规格版本数据访问层。"""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_spec_version import ProjectSpecVersion
from app.repositories.base import BaseRepository


class ProjectSpecRepository(BaseRepository[ProjectSpecVersion]):
    """项目规格版本表查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ProjectSpecVersion)

    async def get_active(self, project_id: str) -> ProjectSpecVersion | None:
        """获取项目当前激活的 ProjectSpec 版本。"""
        stmt = select(ProjectSpecVersion).where(
            ProjectSpecVersion.project_id == project_id,
            ProjectSpecVersion.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_next_version_no(self, project_id: str) -> int:
        """计算下一个版本号（当前最大 version_no + 1，从 1 开始）。"""
        from sqlalchemy import func
        stmt = select(func.max(ProjectSpecVersion.version_no)).where(
            ProjectSpecVersion.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        max_no: int | None = result.scalar_one_or_none()
        return (max_no or 0) + 1

    async def deactivate_all(self, project_id: str) -> None:
        """将该项目下所有版本的 is_active 置为 False。

        在激活新版本前调用，确保同一项目只有一个 active 版本。
        使用批量 UPDATE 而非逐行加载，效率更高。
        """
        stmt = (
            update(ProjectSpecVersion)
            .where(
                ProjectSpecVersion.project_id == project_id,
                ProjectSpecVersion.is_active.is_(True),
            )
            .values(is_active=False)
        )
        await self._session.execute(stmt)

    async def get_by_id_for_project(
        self, spec_id: str, project_id: str
    ) -> ProjectSpecVersion | None:
        """按 ID 查询，同时验证项目归属。"""
        stmt = select(ProjectSpecVersion).where(
            ProjectSpecVersion.id == spec_id,
            ProjectSpecVersion.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
