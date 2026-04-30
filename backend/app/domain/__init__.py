"""领域模块统一导出。"""
from app.domain.states import (
    ALLOWED_AGENT_TASK_TRANSITIONS,
    ALLOWED_PROJECT_TRANSITIONS,
    ALLOWED_SHOT_TRANSITIONS,
    ALLOWED_TOOL_JOB_TRANSITIONS,
    ProjectStage,
    ShotStatus,
    StaleScope,
    TaskStatus,
)

__all__ = [
    "ProjectStage",
    "TaskStatus",
    "ShotStatus",
    "StaleScope",
    "ALLOWED_PROJECT_TRANSITIONS",
    "ALLOWED_AGENT_TASK_TRANSITIONS",
    "ALLOWED_TOOL_JOB_TRANSITIONS",
    "ALLOWED_SHOT_TRANSITIONS",
]