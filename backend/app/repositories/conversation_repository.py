"""对话数据访问层。

来源文档：doc 05 §8（conversation_sessions / conversation_messages / session_contexts）

三张表各对应一个 Repository：
  ConversationSessionRepository  — 会话管理
  ConversationMessageRepository  — 消息追加与查询（append-only）
  SessionContextRepository       — 短期上下文读写（PK = session_id，不继承 BaseRepository）
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import (
    ConversationMessage,
    ConversationSession,
    SessionContext,
)
from app.repositories.base import BaseRepository


# ---------------------------------------------------------------------------
# ConversationSessionRepository
# ---------------------------------------------------------------------------

class ConversationSessionRepository(BaseRepository[ConversationSession]):
    """会话表查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ConversationSession)

    async def get_active_for_project(
        self, project_id: str
    ) -> ConversationSession | None:
        """获取项目最新的 active 会话（updated_at 倒序取第一条）。

        用于 get_or_create_session 中「无 session_id 时复用最近会话」的场景。
        """
        stmt = (
            select(ConversationSession)
            .where(
                ConversationSession.project_id == project_id,
                ConversationSession.status == "active",
            )
            .order_by(ConversationSession.updated_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_project(
        self, session_id: str, project_id: str
    ) -> ConversationSession | None:
        """按 ID 查会话，同时校验项目归属（防越权）。"""
        stmt = select(ConversationSession).where(
            ConversationSession.id == session_id,
            ConversationSession.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_project(
        self, project_id: str, limit: int = 20
    ) -> Sequence[ConversationSession]:
        """列出项目所有会话（updated_at 倒序）。"""
        stmt = (
            select(ConversationSession)
            .where(ConversationSession.project_id == project_id)
            .order_by(ConversationSession.updated_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def touch_updated_at(self, session_id: str) -> None:
        """将会话 updated_at 更新为当前时间（消息写入后调用）。"""
        await self._session.execute(
            sa_update(ConversationSession)
            .where(ConversationSession.id == session_id)
            .values(updated_at=datetime.now(timezone.utc))
        )


# ---------------------------------------------------------------------------
# ConversationMessageRepository
# ---------------------------------------------------------------------------

class ConversationMessageRepository(BaseRepository[ConversationMessage]):
    """消息表查询（append-only，历史消息不可修改）。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ConversationMessage)

    async def get_messages(
        self, session_id: str, limit: int = 50
    ) -> Sequence[ConversationMessage]:
        """获取会话消息，按 created_at 升序（最旧在前，符合 LLM 上下文顺序）。"""
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()


# ---------------------------------------------------------------------------
# SessionContextRepository（PK = session_id，不继承 BaseRepository）
# ---------------------------------------------------------------------------

class SessionContextRepository:
    """会话短期上下文表（session_contexts）。

    此表以 session_id 为主键（无独立 ULID id），不继承 BaseRepository。
    采用"先查后更新/新增"模式保证幂等。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, session_id: str) -> SessionContext | None:
        stmt = select(SessionContext).where(
            SessionContext.session_id == session_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        session_id: str,
        project_id: str,
        *,
        selected_entity_type: Optional[str] = None,
        selected_entity_id: Optional[str] = None,
        pending_option_set_id: Optional[str] = None,
        pending_confirmation_id: Optional[str] = None,
        recent_agent_summary: Optional[dict[str, Any]] = None,
    ) -> SessionContext:
        """INSERT（首次）或 UPDATE（后续）session context。

        None 值表示「不修改该字段」，传入空字符串或空 dict 才会清空。
        """
        ctx = await self.get(session_id)
        if ctx is None:
            ctx = SessionContext(
                session_id=session_id,
                project_id=project_id,
            )
            self._session.add(ctx)

        # 仅更新显式传入的非 None 字段
        if selected_entity_type is not None:
            ctx.selected_entity_type = selected_entity_type
        if selected_entity_id is not None:
            ctx.selected_entity_id = selected_entity_id
        if pending_option_set_id is not None:
            ctx.pending_option_set_id = pending_option_set_id
        if pending_confirmation_id is not None:
            ctx.pending_confirmation_id = pending_confirmation_id
        if recent_agent_summary is not None:
            ctx.recent_agent_summary = recent_agent_summary

        return ctx
