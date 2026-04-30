"""PendingDecision Repository — 挂起决策数据访问层。

文档约束：
  - PendingDecision 是 append-style（状态只往前走，不修改历史）
  - 只需要查询 open 状态的决策（前端展示和 Agent 检查）
  - list_by_type 用于幂等检查（避免重复创建同类型决策）
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import PendingDecision
from app.repositories.base import BaseRepository


class DecisionRepository(BaseRepository[PendingDecision]):
    """挂起决策表查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PendingDecision)

    async def list_open(self, project_id: str) -> List[PendingDecision]:
        """查询项目下所有 status='open' 的待决策（按创建时间升序）。

        前端轮询此接口判断是否有待确认的风格选项/brief/shot plan。
        """
        stmt = (
            select(PendingDecision)
            .where(
                PendingDecision.project_id == project_id,
                PendingDecision.status == "open",
            )
            .order_by(PendingDecision.created_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id_for_project(
        self, decision_id: str, project_id: str
    ) -> Optional[PendingDecision]:
        """按 ID 查询，同时验证项目归属（防止跨项目操作）。"""
        stmt = select(PendingDecision).where(
            PendingDecision.id == decision_id,
            PendingDecision.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_type(
        self,
        project_id: str,
        decision_type: str,
        status: str = "open",
    ) -> List[PendingDecision]:
        """查询指定类型 + 状态的决策（用于幂等检查，避免重复创建同类决策）。

        例：检查是否已有 open 状态的 "select_style_direction" 决策，
        若有则不再重复创建。
        """
        stmt = (
            select(PendingDecision)
            .where(
                PendingDecision.project_id == project_id,
                PendingDecision.decision_type == decision_type,
                PendingDecision.status == status,
            )
            .order_by(PendingDecision.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
