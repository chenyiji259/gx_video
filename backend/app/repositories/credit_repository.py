"""Credit Ledger Repository。

来源文档：doc 09 任务 11-03
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import CreditLedger
from app.repositories.base import BaseRepository


class CreditRepository(BaseRepository[CreditLedger]):
    """credit_ledger 表的数据访问层。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CreditLedger)

    async def get_balance(self, user_id: str) -> float:
        """计算用户当前余额（所有 status=applied 记录的 delta 之和）。"""
        result = await self.session.execute(
            select(func.coalesce(func.sum(CreditLedger.delta), 0.0)).where(
                CreditLedger.user_id == user_id,
                CreditLedger.status == "applied",
            )
        )
        return float(result.scalar() or 0.0)

    async def get_reserved(self, user_id: str) -> float:
        """计算用户当前预占金额（entry_type=reserve 且 status=pending）。"""
        result = await self.session.execute(
            select(func.coalesce(func.sum(-CreditLedger.delta), 0.0)).where(
                CreditLedger.user_id == user_id,
                CreditLedger.entry_type == "reserve",
                CreditLedger.status == "pending",
            )
        )
        return float(result.scalar() or 0.0)

    async def list_by_project(
        self,
        project_id: str,
        limit: int = 50,
    ) -> list[CreditLedger]:
        """查询项目相关的账本记录（按时间倒序）。"""
        result = await self.session.execute(
            select(CreditLedger)
            .where(CreditLedger.project_id == project_id)
            .order_by(CreditLedger.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_reservation(
        self, user_id: str, job_id: str
    ) -> Optional[CreditLedger]:
        """查询某 job 的预占记录（entry_type=reserve, status=pending）。"""
        result = await self.session.execute(
            select(CreditLedger).where(
                CreditLedger.user_id == user_id,
                CreditLedger.job_id == job_id,
                CreditLedger.entry_type == "reserve",
                CreditLedger.status == "pending",
            )
        )
        return result.scalar_one_or_none()

    async def get_reservation_any_status(
        self, user_id: str, job_id: str
    ) -> Optional[CreditLedger]:
        """查询某 job 的预占记录（任意 status），用于 commit/refund 幂等性检查。"""
        result = await self.session.execute(
            select(CreditLedger).where(
                CreditLedger.user_id == user_id,
                CreditLedger.job_id == job_id,
                CreditLedger.entry_type == "reserve",
            )
        )
        return result.scalar_one_or_none()
