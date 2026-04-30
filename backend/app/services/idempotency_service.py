"""幂等服务。

来源文档：doc 03 §16（幂等与恢复）

与 TaskDispatcher 的分工：
  TaskDispatcher.dispatch()  — 检查 pending / running / retrying（同一操作在途中）
  IdempotencyService         — 检查 succeeded（同一操作已完成，直接返回缓存结果）
  两者合起来覆盖全部状态，形成完整幂等保护。

核心方法：
  ensure_unique()  — 全量检查，返回已有 job 或新建 job
  invalidate()     — 上游变更时取消已成功的旧 job（使其失效，强制下游重做）

调用约定：
  - ensure_unique() 接受外部 AsyncSession，在调用方事务内执行 DB 查询和新建
  - Redis push（由 TaskDispatcher 内部调用）在 commit 之后执行
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.workflow import ToolJob
from app.tasks.dispatcher import TaskDispatcher, task_dispatcher

_logger = get_logger("services.idempotency", layer="system")


class IdempotencyService:
    """幂等服务（无状态，依赖注入 TaskDispatcher）。"""

    def __init__(self, dispatcher: TaskDispatcher | None = None) -> None:
        self._dispatcher = dispatcher or task_dispatcher

    # ------------------------------------------------------------------ #
    # 核心：全量幂等检查
    # ------------------------------------------------------------------ #

    async def ensure_unique(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        tool_name: str,
        provider: str | None = None,
        input_payload: dict,
        agent_task_id: str | None = None,
    ) -> tuple[ToolJob, bool]:
        """全量幂等检查：返回已有 job 或新建 job。

        检查顺序：
          1. 查已 succeeded 且 output_payload 非空 → 直接返回（短路，不重跑）
          2. 委托 TaskDispatcher.dispatch()（内部检查 pending/running/retrying）
             → 已有 in-progress job → 返回（is_new=False）
             → 均无 → 新建 job（is_new=True）

        Args:
            session:       调用方的 AsyncSession。
            project_id:    项目 ID。
            tool_name:     工具名称。
            provider:      Provider 名称（本地工具可为 None）。
            input_payload: 工具输入参数。
            agent_task_id: 关联的 AgentTask ID（可选）。

        Returns:
            (ToolJob, is_new)
            is_new=True  → 新 job，调用方 commit 后执行 push_to_queue()
            is_new=False → 已有 job（短路或复用）
        """
        from app.tasks.dispatcher import _build_idempotency_key  # noqa: PLC0415

        idem_key = _build_idempotency_key(tool_name, provider, input_payload)

        # ---- 步骤 1：检查已成功的 job ----
        succeeded_stmt = select(ToolJob).where(
            ToolJob.idempotency_key == idem_key,
            ToolJob.status == "succeeded",
            ToolJob.output_payload.isnot(None),
        ).order_by(ToolJob.created_at.desc()).limit(1)

        result = await session.execute(succeeded_stmt)
        succeeded_job = result.scalar_one_or_none()

        if succeeded_job is not None:
            _logger.debug(
                f"IdempotencyService 短路: tool={tool_name!r} "
                f"id={succeeded_job.id!r} (succeeded)",
                event_type="idempotency_short_circuit",
            )
            return succeeded_job, False

        # ---- 步骤 2：委托 TaskDispatcher（处理 pending/running/retrying）----
        return await self._dispatcher.dispatch(
            session,
            project_id=project_id,
            tool_name=tool_name,
            provider=provider,
            input_payload=input_payload,
            agent_task_id=agent_task_id,
        )

    # ------------------------------------------------------------------ #
    # 失效：上游变更时取消已成功的旧 job
    # ------------------------------------------------------------------ #

    async def invalidate(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        tool_name: str,
        provider: str | None = None,
    ) -> int:
        """将指定项目+工具的已成功 job 标记为 cancelled（强制下次重跑）。

        典型场景：
          - 用户修改音频区间 → 使 audio_analysis 的旧 succeeded job 失效
          - 用户修改全局风格 → 使 image_generation 的旧 succeeded job 失效

        Args:
            session:    调用方的 AsyncSession。
            project_id: 项目 ID。
            tool_name:  工具名称。
            provider:   Provider 名称（None 时匹配所有 provider）。

        Returns:
            被取消的 job 数量。
        """
        conditions = [
            ToolJob.project_id == project_id,
            ToolJob.tool_name == tool_name,
            ToolJob.status == "succeeded",
        ]
        if provider is not None:
            conditions.append(ToolJob.provider == provider)

        stmt = (
            update(ToolJob)
            .where(*conditions)
            .values(status="cancelled")
        )
        result = await session.execute(stmt)
        affected = result.rowcount

        _logger.info(
            f"IdempotencyService invalidate: tool={tool_name!r} "
            f"project={project_id!r} cancelled={affected}",
            event_type="idempotency_invalidated",
        )
        return affected


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

idempotency_service = IdempotencyService()
