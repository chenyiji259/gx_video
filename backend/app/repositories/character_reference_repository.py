"""角色参考图 Repository。

提供 character_references 表的数据访问接口。
每个角色一行，消除并发写入时的 JSONB 锁竞争。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.visual_bible import CharacterReference
from app.repositories.base import BaseRepository


class CharacterReferenceRepository(BaseRepository[CharacterReference]):
    """角色参考图 Repository。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CharacterReference)

    async def list_by_version(self, version_id: str) -> list[CharacterReference]:
        """列出指定版本下的所有角色参考图行。"""
        stmt = select(CharacterReference).where(
            CharacterReference.version_id == version_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_character_id(
        self, version_id: str, character_id: str,
    ) -> Optional[CharacterReference]:
        """按 version_id + character_id 唯一定位一条角色记录。"""
        stmt = select(CharacterReference).where(
            CharacterReference.version_id == version_id,
            CharacterReference.character_id == character_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_completed(self, version_id: str) -> int:
        """统计已完成（active_reference_asset_id 非空）的角色数量。"""
        stmt = select(func.count()).select_from(CharacterReference).where(
            CharacterReference.version_id == version_id,
            CharacterReference.active_reference_asset_id.isnot(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_total(self, version_id: str) -> int:
        """统计指定版本下的角色总数。"""
        stmt = select(func.count()).select_from(CharacterReference).where(
            CharacterReference.version_id == version_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
