"""PromptBundle Repository。

来源文档：doc 09 任务 10-01

提供针对 prompt_bundles 表的基础查询。
同一个 target（target_type + target_id）可能有多条 bundle 记录（历史编译版本），
查询时通常取最新一条（created_at DESC）。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt_bundle import PromptBundleModel
from app.repositories.base import BaseRepository


class PromptBundleRepository(BaseRepository[PromptBundleModel]):
    """prompt_bundles 表查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PromptBundleModel)

    async def get_latest_for_target(
        self,
        target_type: str,
        target_id: str,
    ) -> Optional[PromptBundleModel]:
        """获取指定 target 的最新一条 bundle（created_at DESC）。"""
        stmt = (
            select(PromptBundleModel)
            .where(
                PromptBundleModel.target_type == target_type,
                PromptBundleModel.target_id == target_id,
            )
            .order_by(desc(PromptBundleModel.created_at))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_target(
        self,
        target_type: str,
        target_id: str,
        *,
        limit: int = 10,
    ) -> list[PromptBundleModel]:
        """列出指定 target 的所有 bundle 历史（最新优先）。"""
        stmt = (
            select(PromptBundleModel)
            .where(
                PromptBundleModel.target_type == target_type,
                PromptBundleModel.target_id == target_id,
            )
            .order_by(desc(PromptBundleModel.created_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_project(
        self,
        project_id: str,
        *,
        target_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[PromptBundleModel]:
        """列出项目下的所有 bundle，可按 target_type 过滤（最新优先）。"""
        stmt = (
            select(PromptBundleModel)
            .where(PromptBundleModel.project_id == project_id)
        )
        if target_type:
            stmt = stmt.where(PromptBundleModel.target_type == target_type)
        stmt = stmt.order_by(desc(PromptBundleModel.created_at)).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
