"""场景参考图 Repository。

提供 scene_references 表的数据访问接口。
每个场景一行，消除并发写入时的 JSONB 锁竞争。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.visual_bible import SceneReference
from app.repositories.base import BaseRepository


class SceneReferenceRepository(BaseRepository[SceneReference]):
    """场景参考图 Repository。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SceneReference)

    async def list_by_version(self, version_id: str) -> list[SceneReference]:
        """列出指定版本下的所有场景参考图行。"""
        stmt = select(SceneReference).where(
            SceneReference.version_id == version_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_scene_id(
        self, version_id: str, scene_id: str,
    ) -> Optional[SceneReference]:
        """按 version_id + scene_id 唯一定位一条场景记录。"""
        stmt = select(SceneReference).where(
            SceneReference.version_id == version_id,
            SceneReference.scene_id == scene_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_completed(self, version_id: str) -> int:
        """统计已完成（active_reference_asset_id 非空）的场景数量。"""
        stmt = select(func.count()).select_from(SceneReference).where(
            SceneReference.version_id == version_id,
            SceneReference.active_reference_asset_id.isnot(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_total(self, version_id: str) -> int:
        """统计指定版本下的场景总数。"""
        stmt = select(func.count()).select_from(SceneReference).where(
            SceneReference.version_id == version_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
