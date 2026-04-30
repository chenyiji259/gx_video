"""模型层统一导出。

重要：此文件必须导入所有模型，否则表映射无法注册到 Base.metadata。
"""
from app.models.asset import Asset
from app.models.prompt_bundle import PromptBundleModel
from app.models.clip import ClipVersion
from app.models.export import ExportVersion
from app.models.timeline import TimelineSegment, TimelineVersion
from app.models.storyboard import StoryboardFrame, StoryboardVersion
from app.models.audio_analysis import AudioAnalysisVersion
from app.models.base import Base, BaseModel, CreatedAtMixin, TimestampMixin, ULIDMixin, UpdatedAtMixin
from app.models.billing import CreditLedger
from app.models.conversation import ConversationMessage, ConversationSession, SessionContext
from app.models.events import EventLog, OutboxEvent
from app.models.planning import (
    CreativeBriefVersion,
    ScenePlanVersion,
    Shot,
    ShotPlanVersion,
    StyleBibleVersion,
)
from app.models.project import Project
from app.models.project_spec_version import ProjectSpecVersion
from app.models.user import User, UserPreferences
from app.models.visual_bible import (  # doc11
    CharacterReference,
    CharacterSetVersion,
    NarrativeScriptVersion,
    SceneReference,
)
from app.models.workflow import AgentTask, PendingDecision, ToolJob

__all__ = [
    # base
    "Base",
    "BaseModel",
    "ULIDMixin",
    "TimestampMixin",
    "CreatedAtMixin",
    "UpdatedAtMixin",
    # user
    "User",
    "UserPreferences",
    # project
    "Project",
    # assets
    "Asset",
    "AudioAnalysisVersion",
    "ProjectSpecVersion",
    # conversation
    "ConversationSession",
    "ConversationMessage",
    "SessionContext",
    # planning（8-06）
    "CreativeBriefVersion",
    "StyleBibleVersion",
    "ScenePlanVersion",
    "ShotPlanVersion",
    "Shot",
    # workflow
    "PendingDecision",
    "AgentTask",
    "ToolJob",
    # events
    "EventLog",
    "OutboxEvent",
    # billing
    "CreditLedger",
    # prompt bundles（10-01）
    "PromptBundleModel",
    # storyboard（10-03）
    "StoryboardVersion",
    "StoryboardFrame",
    # clips（11-04）
    "ClipVersion",
    # timeline（11-06）
    "TimelineVersion",
    "TimelineSegment",
    # export（11-08）
    "ExportVersion",
    # visual bible + narrative script（doc11 批次1）
    "CharacterSetVersion",
    "NarrativeScriptVersion",
    # visual bible 独立表（patch_002 规范化）
    "CharacterReference",
    "SceneReference",
]
