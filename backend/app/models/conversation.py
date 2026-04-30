"""对话相关 ORM 模型。

来源文档：doc 05 §8
  - conversation_sessions：会话主表（项目内的对话容器）
  - conversation_messages：消息历史（append-only，无 updated_at）
  - session_contexts：会话短期交互上下文（以 session_id 为 PK，无独立 id）

关键设计点：
  1. conversation_messages 是 append-only，只有 created_at，无 updated_at
     → 继承 Base + ULIDMixin + CreatedAtMixin 而不是 BaseModel
  2. session_contexts 以 session_id 为 PK（1:1 关联 conversation_sessions）
     → 直接继承 Base + UpdatedAtMixin，手动定义 session_id 主键
  3. 消息 message_type 约束覆盖对话协议所有类型（doc 05 §8.2）
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, CreatedAtMixin, ULIDMixin, UpdatedAtMixin


# ---------------------------------------------------------------------------
# conversation_sessions
# ---------------------------------------------------------------------------

class ConversationSession(BaseModel):
    """会话主表（conversation_sessions）。

    doc 05 §8.1 字段规范。
    一个项目可有多个会话（每次重新打开项目可创建新会话或复用）。
    """
    __tablename__ = "conversation_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'closed')",
            name="ck_conversation_sessions_status",
        ),
        Index("idx_conversation_sessions_project", "project_id", "updated_at"),
    )

    project_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="active"
    )

    # 当前会话最后选中的实体（用于代词指代解析：「这个镜头」「上一个人物」）
    last_selected_entity_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    last_selected_entity_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    # 当前悬挂的待决策 ID（FK 到 pending_decisions，后续任务建立）
    pending_decision_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    # Relationships
    project: Mapped["Project"] = relationship(  # noqa: F821
        "Project", back_populates="conversation_sessions"
    )
    messages: Mapped[list["ConversationMessage"]] = relationship(
        "ConversationMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        # order_by 使用 lambda 引用后定义的类属性，避免字符串表达式被当成 SQL 文本解析
        order_by=lambda: ConversationMessage.created_at,
    )
    context: Mapped["SessionContext | None"] = relationship(
        "SessionContext",
        back_populates="session",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ConversationSession id={self.id!r} project_id={self.project_id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# conversation_messages（append-only：只有 created_at，无 updated_at）
# ---------------------------------------------------------------------------

class ConversationMessage(Base, ULIDMixin, CreatedAtMixin):
    """消息历史表（conversation_messages）。

    doc 05 §8.2 字段规范。
    设计为 append-only，历史消息不可修改，故只有 created_at。
    """
    __tablename__ = "conversation_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'tool', 'system')",
            name="ck_conversation_messages_role",
        ),
        CheckConstraint(
            "message_type IN ("
            "'user_text', 'assistant_text', 'assistant_options', "
            "'assistant_confirmation', 'tool_call', 'tool_result', "
            "'system_event_summary')",
            name="ck_conversation_messages_message_type",
        ),
        Index("idx_conversation_messages_session_created", "session_id", "created_at"),
    )

    session_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 消息发送方
    role: Mapped[str] = mapped_column(String(32), nullable=False)

    # 消息类型（区分文本/选项/确认/工具调用等）
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # 文本内容（普通文本消息）
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 结构化内容（选项卡、确认卡、tool call 等的 JSON 载荷）
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # 模型标识（用于追踪哪个模型生成了此消息）
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Token 用量（用于成本监控）
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    session: Mapped["ConversationSession"] = relationship(
        "ConversationSession", back_populates="messages"
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationMessage id={self.id!r} "
            f"role={self.role!r} type={self.message_type!r}>"
        )


# ---------------------------------------------------------------------------
# session_contexts（以 session_id 为主键，无独立 id，无 created_at）
# ---------------------------------------------------------------------------

class SessionContext(Base, UpdatedAtMixin):
    """会话短期上下文表（session_contexts）。

    doc 05 §8.3 字段规范。
    与 conversation_sessions 是 1:1 关系，session_id 即为主键。
    只保存短期交互状态（最近提到哪个 shot、当前待确认项等）。
    """
    __tablename__ = "session_contexts"

    # 主键是 session_id（外键），不是独立 ULID
    session_id: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    project_id: Mapped[str] = mapped_column(String(26), nullable=False)

    # 当前选中的实体（支持指代解析）
    selected_entity_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    selected_entity_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    # 待确认的 option set ID（展示给用户的选项卡）
    pending_option_set_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    # 待确认的操作 ID（高成本确认卡）
    pending_confirmation_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    # Agent 最近一轮输出的结构化摘要（供下一轮 Director Agent 快速恢复上下文）
    recent_agent_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Relationships
    session: Mapped["ConversationSession"] = relationship(
        "ConversationSession", back_populates="context"
    )

    def __repr__(self) -> str:
        return f"<SessionContext session_id={self.session_id!r}>"
