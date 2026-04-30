"""ConversationService — 对话会话与消息持久化服务。

来源文档：doc 03 §4（记忆分层）、doc 05 §8、doc 07 §7（右侧 Chat 栏职责）

职责（任务 6-03 范围）：
  1. get_or_create_session    — 按项目和可选 session_id 获取或新建会话
  2. save_user_message        — 持久化用户消息
  3. save_assistant_message   — 持久化 assistant 消息（含 token 用量）
  4. load_history_for_llm     — 返回 OpenAI messages 格式的历史消息
  5. list_messages            — 返回完整消息列表（API 展示用）
  6. list_sessions            — 列出项目的会话列表
  7. update_session_context   — 更新会话短期状态（Layer C 记忆）

不在此服务范围：
  - LangGraph checkpoint（Layer D，由 LangGraph 内置 checkpointer 管理，任务 7-04 接入）
  - 项目工作记忆（Layer B，由各 xxxVersionService 管理）
"""
from __future__ import annotations

from typing import Any, Optional

from app.core.logging import get_logger, get_project_logger
from app.models.conversation import ConversationMessage, ConversationSession
from app.repositories.conversation_repository import (
    ConversationMessageRepository,
    ConversationSessionRepository,
    SessionContextRepository,
)
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork

_logger = get_logger("conversation_service", layer="project")


# ---------------------------------------------------------------------------
# 业务异常
# ---------------------------------------------------------------------------

class ConversationError(Exception):
    """对话业务异常。"""

    def __init__(self, message: str, code: str = "conversation_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 内部序列化帮助函数
# ---------------------------------------------------------------------------

def _session_to_dict(s: ConversationSession) -> dict:
    return {
        "id": s.id,
        "project_id": s.project_id,
        "status": s.status,
        "last_selected_entity_type": s.last_selected_entity_type,
        "last_selected_entity_id": s.last_selected_entity_id,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _message_to_dict(m: ConversationMessage) -> dict:
    return {
        "id": m.id,
        "session_id": m.session_id,
        "role": m.role,
        "message_type": m.message_type,
        "content_text": m.content_text,
        "content_json": m.content_json,
        "model": m.model,
        "token_usage": m.token_usage,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


# ---------------------------------------------------------------------------
# ConversationService
# ---------------------------------------------------------------------------

class ConversationService:
    """对话会话与消息持久化服务。"""

    # ------------------------------------------------------------------ #
    # 会话管理
    # ------------------------------------------------------------------ #

    async def get_or_create_session(
        self,
        project_id: str,
        user_id: str,
        *,
        session_id: Optional[str] = None,
    ) -> dict:
        """获取或创建会话。

        流程：
          1. 验证项目归属（project 必须属于该 user）
          2. 若提供 session_id：验证归属后直接返回
          3. 否则：找最新 active 会话，无则新建

        Returns:
            session dict

        Raises:
            ConversationError: 项目不存在 / session 不存在或无归属权。
        """
        async with UnitOfWork() as uow:
            # 1. 验证项目归属
            project_repo = ProjectRepository(uow.session)
            project = await project_repo.get_by_id_for_user(project_id, user_id)
            if project is None:
                raise ConversationError("项目不存在", code="not_found")

            session_repo = ConversationSessionRepository(uow.session)

            # 2. 使用指定 session_id
            if session_id:
                session = await session_repo.get_by_id_for_project(
                    session_id, project_id
                )
                if session is None:
                    raise ConversationError(
                        f"会话 {session_id!r} 不存在或不属于该项目",
                        code="not_found",
                    )
                return _session_to_dict(session)

            # 3. 查找最新 active 会话
            session = await session_repo.get_active_for_project(project_id)

            # 4. 无 active 会话则新建
            if session is None:
                session = ConversationSession(
                    project_id=project_id,
                    status="active",
                )
                await session_repo.add(session)
                await uow.flush()
                await uow.session.refresh(session)

                get_project_logger(project_id, module="services.conversation").info(
                    f"新会话已创建: session_id={session.id!r}",
                    event_type="conversation_session_created",
                )

        return _session_to_dict(session)

    async def list_sessions(
        self,
        project_id: str,
        user_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """列出项目所有会话（按活跃时间倒序）。"""
        async with UnitOfWork() as uow:
            project_repo = ProjectRepository(uow.session)
            project = await project_repo.get_by_id_for_user(project_id, user_id)
            if project is None:
                raise ConversationError("项目不存在", code="not_found")

            session_repo = ConversationSessionRepository(uow.session)
            sessions = await session_repo.list_for_project(project_id, limit=limit)

        return [_session_to_dict(s) for s in sessions]

    # ------------------------------------------------------------------ #
    # 消息持久化
    # ------------------------------------------------------------------ #

    async def save_user_message(
        self,
        session_id: str,
        content_text: str,
    ) -> dict:
        """持久化用户消息（role=user, message_type=user_text）。"""
        return await self._append_message(
            session_id=session_id,
            role="user",
            message_type="user_text",
            content_text=content_text,
        )

    async def save_assistant_message(
        self,
        session_id: str,
        content_text: str,
        *,
        content_json: Optional[dict] = None,
        message_type: str = "assistant_text",
        model: Optional[str] = None,
        token_usage: Optional[dict] = None,
    ) -> dict:
        """持久化 assistant 消息。

        Args:
            session_id:    会话 ID。
            content_text:  文本内容（streaming 完成后传入完整文本）。
            content_json:  结构化内容（选项卡/确认卡/tool call payload，7-02 后使用）。
            message_type:  默认 assistant_text，结构化消息另传。
            model:         生成此消息的模型标识。
            token_usage:   Token 用量（prompt_tokens/completion_tokens/total_tokens）。
        """
        return await self._append_message(
            session_id=session_id,
            role="assistant",
            message_type=message_type,
            content_text=content_text,
            content_json=content_json,
            model=model,
            token_usage=token_usage,
        )

    async def _append_message(
        self,
        session_id: str,
        role: str,
        message_type: str,
        *,
        content_text: Optional[str] = None,
        content_json: Optional[dict] = None,
        model: Optional[str] = None,
        token_usage: Optional[dict] = None,
    ) -> dict:
        """内部：追加消息 + 更新 session.updated_at（同一 UoW 事务）。"""
        async with UnitOfWork() as uow:
            msg_repo = ConversationMessageRepository(uow.session)
            session_repo = ConversationSessionRepository(uow.session)

            msg = ConversationMessage(
                session_id=session_id,
                role=role,
                message_type=message_type,
                content_text=content_text,
                content_json=content_json,
                model=model,
                token_usage=token_usage,
            )
            await msg_repo.add(msg)
            await uow.flush()
            await uow.session.refresh(msg)

            # 更新会话 updated_at，确保 get_active_for_project 返回最近使用的会话
            await session_repo.touch_updated_at(session_id)

        _logger.debug(
            f"消息已持久化: session_id={session_id!r} role={role!r} type={message_type!r}",
            event_type="conversation_message_saved",
        )
        return _message_to_dict(msg)

    # ------------------------------------------------------------------ #
    # 历史加载（供 Director Agent 使用）
    # ------------------------------------------------------------------ #

    async def load_history_for_llm(
        self,
        session_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """加载最近 N 条消息，以 OpenAI messages 格式返回。

        仅返回 user / assistant / system 角色的文本消息，
        跳过 tool_call / tool_result 等结构化类型（Director Agent 7-02 接入时处理）。

        Returns:
            [{"role": "user", "content": "..."}, ...]
        """
        async with UnitOfWork() as uow:
            repo = ConversationMessageRepository(uow.session)
            messages = await repo.get_messages(session_id, limit=limit)

        result = [
            {"role": m.role, "content": m.content_text}
            for m in messages
            if m.role in ("user", "assistant", "system") and m.content_text
        ]
        _logger.debug(
            f"LLM 历史加载: session_id={session_id!r} total={len(messages)} returned={len(result)}",
            event_type="conversation_history_loaded",
        )
        return result

    async def list_messages(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """查询会话消息完整列表（含 content_json，供 API 展示使用）。"""
        async with UnitOfWork() as uow:
            repo = ConversationMessageRepository(uow.session)
            messages = await repo.get_messages(session_id, limit=limit)
        return [_message_to_dict(m) for m in messages]

    # ------------------------------------------------------------------ #
    # 会话上下文（Layer C 记忆）
    # ------------------------------------------------------------------ #

    async def update_session_context(
        self,
        session_id: str,
        project_id: str,
        *,
        selected_entity_type: Optional[str] = None,
        selected_entity_id: Optional[str] = None,
        pending_option_set_id: Optional[str] = None,
        pending_confirmation_id: Optional[str] = None,
        recent_agent_summary: Optional[dict[str, Any]] = None,
    ) -> None:
        """更新会话短期上下文（Layer C 记忆）。

        Director Agent (任务 7-02) 每轮响应后调用，记录：
          - 本轮涉及的 shot/scene/clip ID（供代词解析：「这个镜头」）
          - 当前悬挂的待确认项/待选项 ID
          - Agent 输出摘要（供下轮快速恢复上下文，减少 token 开销）
        """
        async with UnitOfWork() as uow:
            ctx_repo = SessionContextRepository(uow.session)
            await ctx_repo.upsert(
                session_id=session_id,
                project_id=project_id,
                selected_entity_type=selected_entity_type,
                selected_entity_id=selected_entity_id,
                pending_option_set_id=pending_option_set_id,
                pending_confirmation_id=pending_confirmation_id,
                recent_agent_summary=recent_agent_summary,
            )
            await uow.flush()
            get_project_logger(project_id, module="services.conversation").debug(
                f"会话上下文已更新: session_id={session_id!r} "
                f"entity_type={selected_entity_type!r} entity_id={selected_entity_id!r}",
                event_type="conversation_context_updated",
            )
