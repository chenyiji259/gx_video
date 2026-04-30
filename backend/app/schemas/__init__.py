"""共享 Schema 层统一导出。

这里导出的对象在 API、LangGraph State、Agent、Service 之间共享。
后续模块不应重复定义这些核心数据结构。
"""
from app.schemas.event import EventCategory, ProjectEvent
from app.schemas.project import ActiveVersions, PendingDecisionRef, ProjectSnapshot
from app.schemas.prompt import PromptBundle, PromptTargetType
from app.schemas.shot import PaceType, ShotRole, ShotSemanticSpec

__all__ = [
    # project
    "ActiveVersions",
    "PendingDecisionRef",
    "ProjectSnapshot",
    # shot
    "ShotRole",
    "PaceType",
    "ShotSemanticSpec",
    # prompt
    "PromptTargetType",
    "PromptBundle",
    # event
    "EventCategory",
    "ProjectEvent",
]