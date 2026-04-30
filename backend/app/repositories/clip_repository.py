"""Clip Repository。

来源文档：doc 09 任务 11-04
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clip import ClipVersion
from app.models.planning import Shot
from app.repositories.base import BaseRepository


class ClipRepository(BaseRepository[ClipVersion]):
    """clip_versions 表的数据访问层。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ClipVersion)

    async def get_active(self, shot_id: str) -> Optional[ClipVersion]:
        """返回指定 shot 当前激活的 ClipVersion。"""
        result = await self.session.execute(
            select(ClipVersion).where(
                ClipVersion.shot_id == shot_id,
                ClipVersion.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def list_active_by_project(self, project_id: str) -> list[ClipVersion]:
        """返回项目内所有 shot 当前激活的 ClipVersion，按 shot_index 升序排序。"""
        result = await self.session.execute(
            select(ClipVersion)
            .join(Shot, ClipVersion.shot_id == Shot.id)
            .where(
                ClipVersion.project_id == project_id,
                ClipVersion.is_active.is_(True),
            )
            .order_by(Shot.shot_index.asc())
        )
        return list(result.scalars().all())

    async def list_by_shot(self, shot_id: str) -> list[ClipVersion]:
        """返回指定 shot 的所有版本（按版本号升序）。"""
        result = await self.session.execute(
            select(ClipVersion)
            .where(ClipVersion.shot_id == shot_id)
            .order_by(ClipVersion.version_no.asc())
        )
        return list(result.scalars().all())

    async def deactivate_all(self, shot_id: str) -> None:
        """将指定 shot 的所有版本标记为 is_active=False。"""
        await self.session.execute(
            update(ClipVersion)
            .where(ClipVersion.shot_id == shot_id)
            .values(is_active=False)
        )

    async def get_next_version_no(self, shot_id: str) -> int:
        """返回下一个版本号（max + 1，无记录则返回 1）。"""
        result = await self.session.execute(
            select(ClipVersion.version_no)
            .where(ClipVersion.shot_id == shot_id)
            .order_by(ClipVersion.version_no.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return (row or 0) + 1
