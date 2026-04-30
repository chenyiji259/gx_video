"""Export Repository。

来源文档：doc 09 任务 11-08
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.export import ExportVersion
from app.repositories.base import BaseRepository


class ExportRepository(BaseRepository[ExportVersion]):
    """export_versions 表的数据访问层。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ExportVersion)

    async def get_latest(self, project_id: str) -> Optional[ExportVersion]:
        """返回项目最新一次导出记录（按 created_at 倒序）。"""
        result = await self.session.execute(
            select(ExportVersion)
            .where(ExportVersion.project_id == project_id)
            .order_by(ExportVersion.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self, project_id: str, limit: int = 20
    ) -> list[ExportVersion]:
        """返回项目所有导出记录（按时间倒序）。"""
        result = await self.session.execute(
            select(ExportVersion)
            .where(ExportVersion.project_id == project_id)
            .order_by(ExportVersion.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
