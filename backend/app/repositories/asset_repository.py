"""Asset Repository — 资产数据访问层。"""
from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.project import Project
from app.repositories.base import BaseRepository


class AssetRepository(BaseRepository[Asset]):
    """资产表查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Asset)

    async def list_by_project(
        self,
        project_id: str,
        *,
        asset_type: str | None = None,
        limit: int = 50,
    ) -> Sequence[Asset]:
        """按项目查询资产列表，按 created_at 倒序。"""
        stmt = (
            select(Asset)
            .where(Asset.project_id == project_id)
            .order_by(Asset.created_at.desc())
            .limit(limit)
        )
        if asset_type:
            stmt = stmt.where(Asset.asset_type == asset_type)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def list_all_by_user(
        self,
        user_id: str,
        *,
        asset_type: str | None = None,
        limit: int = 100,
    ) -> list[Asset]:
        """跨项目查询用户所有资产。"""
        stmt = (
            select(Asset)
            .join(Project, Asset.project_id == Project.id)
            .where(Project.user_id == user_id)
            .order_by(Asset.created_at.desc())
            .limit(limit)
        )
        if asset_type:
            stmt = stmt.where(Asset.asset_type == asset_type)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id_for_project(
        self, asset_id: str, project_id: str
    ) -> Asset | None:
        """按 ID 查询资产，同时验证项目归属（防越权）。"""
        stmt = select(Asset).where(
            Asset.id == asset_id,
            Asset.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_ids(self, asset_ids: list[str]) -> list[Asset]:
        """按 ID 列表批量查询（顺序不保证，调用方自行建 id→asset map）。"""
        if not asset_ids:
            return []
        stmt = select(Asset).where(Asset.id.in_(asset_ids))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_sha256(self, sha256: str, project_id: str) -> Asset | None:
        """按 sha256 查重（同项目内），用于幂等上传。"""
        stmt = select(Asset).where(
            Asset.sha256 == sha256,
            Asset.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
