"""任务分发器。

来源文档：doc 03 §8.3（Tool 任务表）、doc 03 §16（幂等与恢复）

职责：
  TaskDispatcher.dispatch() 负责：
    1. 幂等检查：相同 idempotency_key 已有 pending/running job 时直接返回已有 job
    2. 在调用方事务内建 ToolJob 记录（状态 pending）
    3. 调用方事务 commit 后，将 job_id push 到 Redis 队列（不在事务内 push，避免事务回滚但消息已推）

设计约束：
  - dispatch() 接受外部 AsyncSession（在调用方事务内建 DB 记录）
  - Redis push 在 dispatch() 外部调用（由调用方在 commit 后执行）
  - 幂等键生成规则：hash(tool_name + provider + sorted json(input_payload))
  - 队列 key 从 config 读取（vidmuse:task_queue）

调用示例：
    async with UnitOfWork() as uow:
        job, is_new = await dispatcher.dispatch(
            uow.session,
            project_id=project.id,
            tool_name="audio_analysis",
            provider="librosa_local",
            input_payload={"audio_asset_id": "xxx"},
        )
    # commit 完成后推 Redis
    if is_new:
        await dispatcher.push_to_queue(job.id)
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.redis_utils import get_redis_client
from app.models.workflow import ToolJob
from app.utils.ids import generate_ulid

_logger = get_logger("tasks.dispatcher", layer="tool")

# Redis 队列 key
_QUEUE_KEY = "vidmuse:task_queue"


def _build_idempotency_key(
    tool_name: str,
    provider: str | None,
    input_payload: dict,
) -> str:
    """生成幂等键。

    规则（doc 03 §16.1）：
      hash(tool_name + provider + sorted_json(input_payload))
    """
    canonical = json.dumps(
        {
            "tool": tool_name,
            "provider": provider or "",
            "input": input_payload,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:64]


class TaskDispatcher:
    """任务分发器（无状态，使用全局共享 Redis 池）。"""

    def __init__(self) -> None:
        pass  # 无需自持 Redis 客户端

    async def close(self) -> None:
        """安全关闭（实际由 close_redis_client() 在 lifespan 平决）。"""
        pass

    # ------------------------------------------------------------------ #
    # 核心分发方法
    # ------------------------------------------------------------------ #

    async def dispatch(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        tool_name: str,
        provider: str | None = None,
        input_payload: dict,
        agent_task_id: str | None = None,
    ) -> tuple[ToolJob, bool]:
        """创建 ToolJob 记录（在调用方事务内执行）。

        Args:
            session:       调用方的 AsyncSession。
            project_id:    项目 ID。
            tool_name:     工具名（e.g. "audio_analysis"）。
            provider:      Provider 名（本地工具可为 None）。
            input_payload: 工具输入参数。
            agent_task_id: 关联的 AgentTask ID（可选）。

        Returns:
            (ToolJob, is_new)
            is_new = True  表示新建了 job，调用方 commit 后应调用 push_to_queue()
            is_new = False 表示已有相同幂等键的 job，直接复用

        Note:
            此方法只写 DB，不 push Redis。
            Redis push 必须在 commit 之后执行，避免消息先到 worker 但 DB 事务未提交。
        """
        idem_key = _build_idempotency_key(tool_name, provider, input_payload)

        # 幂等检查：相同 key 的 pending / running / retrying job 直接复用
        # 允许 failed / succeeded 的历史 job 存在时重新创建新任务。
        # 旧约束下直接 INSERT 会撞 uq_tool_jobs_idempotency，导致用户无法在
        # 修正 credits、provider 或上游状态后重新发起同一类高成本任务。
        existing_stmt = select(ToolJob).where(
            ToolJob.idempotency_key == idem_key,
            ToolJob.status.in_(["pending", "running", "retrying"]),
        )
        result = await session.execute(existing_stmt)
        existing_job = result.scalar_one_or_none()

        if existing_job is not None:
            _logger.debug(
                f"ToolJob 幂等复用: key={idem_key[:16]}... id={existing_job.id!r}",
                event_type="tool_job_deduped",
            )
            return existing_job, False

        # 若只有 failed / succeeded 的历史记录，先让旧记录释放唯一键，
        # 再创建新的 ToolJob，保留可追溯性同时允许显式重试。
        historical_stmt = select(ToolJob).where(
            ToolJob.idempotency_key == idem_key,
            ToolJob.status.in_(["failed", "succeeded", "cancelled"]),
        )
        historical_result = await session.execute(historical_stmt)
        historical_jobs = list(historical_result.scalars().all())
        for old_job in historical_jobs:
            old_job.idempotency_key = f"{old_job.idempotency_key}__archived__{old_job.id}"

        # 新建 ToolJob
        job = ToolJob(
            id=generate_ulid(),
            project_id=project_id,
            agent_task_id=agent_task_id,
            tool_name=tool_name,
            provider=provider,
            status="pending",
            input_payload=input_payload,
            idempotency_key=idem_key,
            retry_count=0,
        )
        session.add(job)

        _logger.info(
            f"ToolJob 已创建: id={job.id!r} tool={tool_name!r} provider={provider!r}",
            event_type="tool_job_created",
        )
        return job, True

    async def push_to_queue(self, job_id: str) -> None:
        """将 job_id 推送到 Redis 队列（在 DB commit 之后调用）。

        使用 LPUSH + BRPOP 的 Redis List 队列模式。
        queue key = vidmuse:task_queue

        Args:
            job_id: ToolJob 的 ULID 主键。
        """
        redis_client = get_redis_client()
        await redis_client.lpush(_QUEUE_KEY, job_id)
        _logger.info(
            f"ToolJob 已入队: id={job_id!r} queue={_QUEUE_KEY!r}",
            event_type="tool_job_enqueued",
        )


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

task_dispatcher = TaskDispatcher()
