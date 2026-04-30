"""Credits 服务（Credit Service）。

来源文档：doc 09 任务 11-03

职责：
  管理用户 credits 账本的四种操作：
    - grant:   充值/发放（初始化、购买、奖励）
    - reserve: 预占（高成本操作执行前扣减可用余额）
    - commit:  提交（任务成功后将 reserved → committed）
    - refund:  退款（任务失败后释放预占金额）

设计约束：
  - 预占与媒体生成事务分离：reserve 先落库，生成成功再 commit，失败则 refund
  - 余额不足时 reserve 抛 InsufficientCreditsError，不直接执行媒体生成
  - job_id 唯一标识每次预占，避免重复扣款
"""
from __future__ import annotations

from typing import Optional

from app.core.logging import get_logger
from app.models.billing import CreditLedger
from app.repositories.credit_repository import CreditRepository
from app.repositories.unit_of_work import UnitOfWork
from app.utils.ids import generate_ulid

_logger = get_logger("services.credit", layer="system")

# 临时策略：当前项目阶段关闭 credits 机制，不阻断任何生成链路。
_CREDITS_BYPASS_ENABLED = True


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class InsufficientCreditsError(Exception):
    """余额不足异常。"""

    def __init__(self, required: int, available: float) -> None:
        super().__init__(
            f"Credits 余额不足：需要 {required}，当前可用 {available:.1f}"
        )
        self.code = "insufficient_credits"
        self.required = required
        self.available = available


class CreditOperationError(Exception):
    """Credits 操作异常（如预占记录不存在）。"""

    def __init__(self, message: str, code: str = "credit_error") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# CreditService
# ---------------------------------------------------------------------------

class CreditService:
    """Credits 账本操作服务。"""

    async def grant(
        self,
        user_id: str,
        amount: int,
        *,
        project_id: Optional[str] = None,
        note: Optional[str] = None,
    ) -> CreditLedger:
        """充值 / 发放 credits。

        Args:
            user_id:    用户 ID。
            amount:     发放金额（正整数）。
            project_id: 关联项目 ID（可选）。
            note:       备注（如"初始免费额度"）。

        Returns:
            新建的 CreditLedger 记录。
        """
        if amount <= 0:
            raise CreditOperationError(
                f"grant 金额必须为正整数，收到: {amount}", code="invalid_amount"
            )

        async with UnitOfWork() as uow:
            ledger = CreditLedger(
                id=generate_ulid(),
                user_id=user_id,
                project_id=project_id,
                entry_type="grant",
                delta=float(amount),
                units=float(amount),
                unit_price=1.0,
                status="applied",
                metadata_={"note": note or "credits grant"},
            )
            repo = CreditRepository(uow.session)
            await repo.add(ledger)
            await uow.flush()

        _logger.info(
            f"Credits grant: user={user_id!r} amount={amount}",
            event_type="credits_grant",
        )
        return ledger

    async def reserve(
        self,
        user_id: str,
        amount: int,
        *,
        job_id: str,
        project_id: Optional[str] = None,
        tool_name: str = "video_generation",
    ) -> CreditLedger:
        """预占 credits（执行高成本操作前调用）。

        Args:
            user_id:    用户 ID。
            amount:     预占金额（正整数）。
            job_id:     关联 ToolJob ID（唯一标识，防重复预占）。
            project_id: 关联项目 ID（可选）。
            tool_name:  工具名称（用于账本追溯）。

        Returns:
            新建的 reserved 状态 CreditLedger 记录。

        Raises:
            InsufficientCreditsError: 可用余额不足。
        """
        if _CREDITS_BYPASS_ENABLED:
            _logger.info(
                f"Credits bypass: reserve 放行 user={user_id!r} amount={amount} job={job_id!r}",
                event_type="credits_bypass_reserve",
            )
            return CreditLedger(
                id=generate_ulid(),
                user_id=user_id,
                project_id=project_id,
                job_id=job_id,
                entry_type="reserve",
                tool_name=tool_name,
                delta=0.0,
                units=float(amount),
                unit_price=0.0,
                status="applied",
                metadata_={"note": "credits bypass reserve"},
            )

        async with UnitOfWork() as uow:
            repo = CreditRepository(uow.session)

            # 幂等检查：同 job_id 已有预占则直接返回
            existing = await repo.get_reservation(user_id, job_id)
            if existing is not None:
                return existing

            # 余额检查
            balance = await repo.get_balance(user_id)
            reserved = await repo.get_reserved(user_id)
            available = balance - reserved

            if available < amount:
                raise InsufficientCreditsError(
                    required=amount, available=available
                )

            ledger = CreditLedger(
                id=generate_ulid(),
                user_id=user_id,
                project_id=project_id,
                job_id=job_id,
                entry_type="reserve",
                tool_name=tool_name,
                delta=-float(amount),    # 预占：负数
                units=float(amount),
                unit_price=1.0,
                status="pending",
                metadata_={"note": f"reserve for job {job_id}"},
            )
            await repo.add(ledger)
            await uow.flush()

        _logger.info(
            f"Credits reserve: user={user_id!r} amount={amount} job={job_id!r}",
            event_type="credits_reserve",
        )
        return ledger

    async def commit(
        self,
        user_id: str,
        job_id: str,
    ) -> CreditLedger:
        """提交预占（任务成功后调用，将 reserved → committed）。

        Args:
            user_id: 用户 ID。
            job_id:  ToolJob ID。

        Returns:
            更新后的 CreditLedger 记录。

        Raises:
            CreditOperationError: 预占记录不存在。
        """
        if _CREDITS_BYPASS_ENABLED:
            _logger.info(
                f"Credits bypass: commit 放行 user={user_id!r} job={job_id!r}",
                event_type="credits_bypass_commit",
            )
            return CreditLedger(
                id=generate_ulid(),
                user_id=user_id,
                job_id=job_id,
                entry_type="reserve",
                delta=0.0,
                units=0.0,
                unit_price=0.0,
                status="applied",
                metadata_={"note": "credits bypass commit"},
            )

        async with UnitOfWork() as uow:
            repo = CreditRepository(uow.session)
            # 幂等性检查：不区分 status，防止重试时报错
            ledger = await repo.get_reservation_any_status(user_id, job_id)
            if ledger is None:
                raise CreditOperationError(
                    f"未找到 job_id={job_id!r} 的预占记录，无法 commit",
                    code="reservation_not_found",
                )
            # 已经 commit 过，幂等返回
            if ledger.status == "applied":
                return ledger
            ledger.status = "applied"
            uow.session.add(ledger)
            await uow.flush()

        _logger.info(
            f"Credits commit: user={user_id!r} job={job_id!r} "
            f"amount={abs(ledger.delta):.0f}",
            event_type="credits_commit",
        )
        return ledger

    async def refund(
        self,
        user_id: str,
        job_id: str,
    ) -> CreditLedger:
        """退款（任务失败后调用，释放预占金额）。

        将 reserved 记录标记为 refunded，相当于撤销预占。

        Args:
            user_id: 用户 ID。
            job_id:  ToolJob ID。

        Returns:
            更新后的 CreditLedger 记录。

        Raises:
            CreditOperationError: 预占记录不存在。
        """
        if _CREDITS_BYPASS_ENABLED:
            _logger.info(
                f"Credits bypass: refund 放行 user={user_id!r} job={job_id!r}",
                event_type="credits_bypass_refund",
            )
            return CreditLedger(
                id=generate_ulid(),
                user_id=user_id,
                job_id=job_id,
                entry_type="reserve",
                delta=0.0,
                units=0.0,
                unit_price=0.0,
                status="reverted",
                metadata_={"note": "credits bypass refund"},
            )

        async with UnitOfWork() as uow:
            repo = CreditRepository(uow.session)
            # 幂等性检查：不区分 status，防止重试时报错
            ledger = await repo.get_reservation_any_status(user_id, job_id)
            if ledger is None:
                raise CreditOperationError(
                    f"未找到 job_id={job_id!r} 的预占记录，无法 refund",
                    code="reservation_not_found",
                )
            # 已经 refund 过，幂等返回
            if ledger.status == "reverted":
                return ledger
            ledger.status = "reverted"
            uow.session.add(ledger)
            await uow.flush()

        _logger.info(
            f"Credits refund: user={user_id!r} job={job_id!r} "
            f"amount={abs(ledger.delta):.0f}",
            event_type="credits_refund",
        )
        return ledger

    async def get_balance(self, user_id: str) -> dict:
        """查询用户余额摘要。

        Returns:
            {
                "committed": float,  # 真实可用余额
                "reserved": float,   # 当前预占金额
                "available": float,  # 可用金额 = committed - reserved
            }
        """
        async with UnitOfWork() as uow:
            repo = CreditRepository(uow.session)
            committed = await repo.get_balance(user_id)
            reserved = await repo.get_reserved(user_id)

        return {
            "committed": committed,
            "reserved": reserved,
            "available": committed - reserved,
        }
