"""工作流辅助表 ORM 模型。

来源文档：doc 03 §8（Agent 任务表 / Tool 任务表）、doc 03 §14（Pending Decision）、
          doc 04 §7（决策状态机）、doc 05 表结构
          scripts/init_schema.sql  §10（WORKFLOW 节）

三张表职责：
  PendingDecision — 等待用户确认/选择的挂起决策（doc 04 §7）
  AgentTask       — Agent 级任务记录，含状态流转（doc 03 §8.2）
  ToolJob         — Tool 执行级任务记录，含幂等键（doc 03 §8.3）

设计约束：
  - PendingDecision 只含 created_at（无 updated_at），用 Base + ULIDMixin + CreatedAtMixin
  - AgentTask / ToolJob 含 created_at + updated_at，继承 BaseModel
  - 状态字段使用 varchar + CheckConstraint
  - ToolJob.idempotency_key 加 UniqueConstraint（4-05 幂等服务依赖）
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BaseModel, CreatedAtMixin, ULIDMixin


# ---------------------------------------------------------------------------
# PendingDecision — 挂起决策（append-style，无 updated_at）
# ---------------------------------------------------------------------------

_DECISION_STATUS = "('open', 'selected', 'expired', 'cancelled')"


class PendingDecision(Base, ULIDMixin, CreatedAtMixin):
    """挂起决策表（pending_decisions）。

    生命周期：open → selected | expired | cancelled
    决策不允许修改，只能切换状态（通过 DecisionService 操作）。
    doc 04 §7 / doc 03 §14
    """

    __tablename__ = "pending_decisions"
    __table_args__ = (
        CheckConstraint(
            f"status IN {_DECISION_STATUS}",
            name="ck_pending_decisions_status",
        ),
        Index(
            "idx_pending_decisions_project_status",
            "project_id",
            "status",
            "created_at",
        ),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 决策类型（e.g. "confirm_clip_regen", "select_style_direction"）
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # 决策影响的实体类型（e.g. "shot", "project", "style"）
    target_entity_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # 决策影响的实体 ID（可为空，如项目级决策）
    target_entity_id: Mapped[str | None] = mapped_column(String(26), nullable=True)

    # 选项列表（结构化 JSON，前端渲染确认卡/选项卡）
    options_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    # 默认选项 ID（可为空，不强制默认值）
    default_option_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 用户实际选择的选项 ID（submit_decision 后写入，open 时为 None）
    selected_option_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 决策状态
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="open"
    )

    # 决策过期时间（None 表示永不过期）
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<PendingDecision id={self.id!r} type={self.decision_type!r} "
            f"status={self.status!r}>"
        )


# ---------------------------------------------------------------------------
# AgentTask — Agent 级任务记录
# ---------------------------------------------------------------------------

_AGENT_TASK_STATUS = (
    "('pending', 'running', 'waiting_human', 'succeeded', 'failed', 'cancelled')"
)


class AgentTask(BaseModel):
    """Agent 任务表（agent_tasks）。

    记录 Director Agent 向专业 Agent 派发的每一个任务的生命周期。
    doc 03 §8.2 / doc 04 §5（任务状态机）
    """

    __tablename__ = "agent_tasks"
    __table_args__ = (
        CheckConstraint(
            f"status IN {_AGENT_TASK_STATUS}",
            name="ck_agent_tasks_status",
        ),
        Index(
            "idx_agent_tasks_project_status",
            "project_id",
            "status",
            "created_at",
        ),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_session_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("conversation_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 任务类型（e.g. "generate_shot_plan", "compile_prompt_bundle"）
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # 发起方 Agent 名称（e.g. "director_agent"）
    requested_by_agent: Mapped[str] = mapped_column(String(64), nullable=False)

    # 执行方 Agent 名称（e.g. "creative_planning_agent"）
    assigned_agent: Mapped[str] = mapped_column(String(64), nullable=False)

    # 任务状态
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )

    # 任务输入引用（版本 ID / snapshot ref 等，不存大 payload）
    input_ref: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # 任务输出引用（成功后填入）
    output_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # 失败信息（含错误码、堆栈摘要等）
    error_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AgentTask id={self.id!r} type={self.task_type!r} "
            f"status={self.status!r}>"
        )


# ---------------------------------------------------------------------------
# ToolJob — Tool 执行级任务记录
# ---------------------------------------------------------------------------

_TOOL_JOB_STATUS = (
    "('pending', 'running', 'waiting_human', 'succeeded', "
    "'failed', 'retrying', 'cancelled')"
)


class ToolJob(BaseModel):
    """Tool 任务表（tool_jobs）。

    记录每次工具调用（图片生成、视频生成、音频分析等）的完整生命周期。
    含幂等键（idempotency_key），防止高成本操作重复执行。
    doc 03 §8.3 / doc 03 §16（幂等与恢复）
    """

    __tablename__ = "tool_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_tool_jobs_idempotency"),
        CheckConstraint(
            f"status IN {_TOOL_JOB_STATUS}",
            name="ck_tool_jobs_status",
        ),
        Index(
            "idx_tool_jobs_project_status",
            "project_id",
            "status",
            "created_at",
        ),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_task_id: Mapped[str | None] = mapped_column(
        String(26),
        ForeignKey("agent_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 工具名称（e.g. "audio_analysis", "image_generation", "video_generation"）
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)

    # Provider 名称（e.g. "flux_schnell", "kling_v2"；音频本地工具可为 None）
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 任务状态
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )

    # 工具输入参数快照（用于幂等对比和问题排查）
    input_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # 工具输出结果（成功后填入）
    output_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # 失败信息（含错误码、堆栈摘要等，与 AgentTask.error_payload 语义一致）
    error_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # 幂等键（hash(tool_name + input_payload + provider + active_versions)）
    # 4-05 幂等服务依赖此字段的 UniqueConstraint
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)

    # 自动重试计数
    retry_count: Mapped[int] = mapped_column(nullable=False, server_default="0")

    def __repr__(self) -> str:
        return (
            f"<ToolJob id={self.id!r} tool={self.tool_name!r} "
            f"status={self.status!r} retries={self.retry_count}>"
        )
