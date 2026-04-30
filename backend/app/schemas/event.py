"""项目事件 Schema。

来源文档：doc 04 §8 事件系统
  事件分三类：
    A. Domain Event  — 业务事实发生（audio_analysis_completed 等）
    B. Workflow Event — 流程状态变化（agent_task_started 等）
    C. UI Event       — 前端需要感知的交互事件（decision_requested 等）

事件命名规范（doc 04 §8.2）：
  统一采用过去式，如：
    audio_analysis_requested / audio_analysis_completed / audio_analysis_failed
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.utils.ids import generate_ulid


# 事件大类
EventCategory = Literal["domain", "workflow", "ui"]


class ProjectEvent(BaseModel):
    """项目事件的标准化封装。

    对应 event_logs 表的数据结构（doc 05 §14.4）。
    也用于 outbox_events 的 payload（doc 10 Outbox 模式）。
    """
    event_id: str = Field(default_factory=generate_ulid)
    project_id: str

    # 事件所属聚合根类型（project / shot / timeline / clip 等）
    aggregate_type: str

    # 聚合根 ID
    aggregate_id: str

    # 事件类型（命名规范：过去式，如 audio_analysis_completed）
    event_type: str

    # 事件分类
    category: EventCategory = "domain"

    # 事件携带的业务数据
    payload: dict[str, Any] = Field(default_factory=dict)

    # 因果链追踪（可选）
    causation_id: str | None = None     # 引起此事件的命令/事件 ID
    correlation_id: str | None = None   # 同一业务请求的追踪 ID

    created_at: datetime | None = None
