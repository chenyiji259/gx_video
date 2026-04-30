"""OpenAI 兼容聊天接口（/v1/chat/completions）。

来源文档：doc 07 §10（Chat SSE 设计）

接口：
  POST /v1/chat/completions   — 支持非流式（stream=false）和流式（stream=true）

路由前缀：
  此路由挂载在 /v1 下，完整路径为 /v1/chat/completions，
  与 OpenAI SDK 标准路径完全兼容。

请求扩展字段（VidMuse 自定义）：
  project_id  — 必填，关联项目 ID
  session_id  — 选填，指定已有会话；不填则自动获取或新建 active 会话

回复生成（任务 7-04 接入后）：
  通过 invoke_director_graph() 调用 LangGraph 主图，
  由 Director Agent 生成结构化回复和可选 tool_calls。
  LLM API key 未配置时自动返回兜底文本，不崩溃服务。

SSE 格式（符合 OpenAI streaming 规范）：
  data: {chat.completion.chunk JSON}\\n\\n
  ...
  data: [DONE]\\n\\n
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.api.v1.deps import get_current_user
from app.core.logging import get_project_logger
from app.models.user import User
from app.services.conversation_service import ConversationError, ConversationService
from app.services.tool_call_bridge_service import ToolCallBridgeService
from app.utils.ids import generate_ulid
from app.workflows.main_graph import invoke_director_graph

router = APIRouter(tags=["chat"])

_MODEL_ID = "vidmuse-director"


# ---------------------------------------------------------------------------
# Request / Response Schemas（Pydantic）
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    """OpenAI 兼容消息对象（当前仅支持文本 content）。"""

    role: str = Field(..., description="消息角色：user / assistant / system")
    content: str = Field(..., description="消息文本内容")


class ChatCompletionsRequest(BaseModel):
    """POST /v1/chat/completions 请求体。

    标准 OpenAI 字段 + VidMuse 扩展字段。
    """

    # --- 标准 OpenAI 字段 ---
    model: str = Field(default=_MODEL_ID, description="模型标识")
    messages: list[ChatMessage] = Field(
        ..., min_length=1, description="消息历史（至少包含当前用户消息）"
    )
    stream: bool = Field(default=False, description="是否流式返回")
    temperature: Optional[float] = Field(
        default=None, ge=0.0, le=2.0, description="温度参数（预留，7-02 接入 LLM 后生效）"
    )
    max_tokens: Optional[int] = Field(
        default=None, ge=1, description="最大 token 数（预留）"
    )

    # --- VidMuse 扩展字段 ---
    project_id: str = Field(
        ..., description="所属项目 ID（必填，用于会话归属和 Agent 加载项目上下文）"
    )
    session_id: Optional[str] = Field(
        default=None, description="指定会话 ID（不填则自动获取或新建 active 会话）"
    )


# ---------------------------------------------------------------------------
# 内部：构造 OpenAI 响应结构
# ---------------------------------------------------------------------------

def _make_completion_id() -> str:
    return f"chatcmpl-{generate_ulid()}"


def _make_non_stream_response(
    completion_id: str,
    content: str,
    model: str,
    created_at: int,
    *,
    tool_calls: Optional[list[dict]] = None,
    vidmuse: Optional[dict] = None,
) -> dict:
    """构造非流式 chat.completion 响应体（符合 OpenAI v1 规范，支持 tool_calls）。

    vidmuse 扩展字段（VidMuse 自定义）：
      前端通过此字段直接获取决策信息，无需再调 GET /decisions。
      格式：
        {
          "requires_confirmation": true,
          "pending_decision_id": "01H...",
          "decision_options": [{"id": "...", "title": "...", ...}]
        }
    """
    finish_reason = "tool_calls" if tool_calls else "stop"
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    response: dict = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created_at,
        "model": model,
        "choices": [
            {"index": 0, "message": message, "finish_reason": finish_reason}
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
    if vidmuse is not None:
        response["vidmuse"] = vidmuse
    return response


async def _stream_reply_generator(
    reply: str,
    completion_id: str,
    created_at: int,
    model: str,
    *,
    tool_calls: Optional[list[dict]] = None,
    vidmuse: Optional[dict] = None,
) -> AsyncIterator[str]:
    """将完整 reply 以 OpenAI streaming chunk 格式逐段 yield，支持 tool_calls 和 vidmuse 扩展。"""
    base = {"id": completion_id, "object": "chat.completion.chunk",
            "created": created_at, "model": model}

    # --- 第一个 chunk：声明 role ---
    first = {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
    yield f"data: {json.dumps(first, ensure_ascii=False)}\n\n"
    await asyncio.sleep(0)

    # --- 内容 chunks（每次最多 8 个字符）---
    chunk_size = 8
    for i in range(0, len(reply), chunk_size):
        piece = reply[i: i + chunk_size]
        chunk = {**base, "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0)

    # --- tool_calls chunk（若有）---
    if tool_calls:
        for idx, tc in enumerate(tool_calls):
            tc_chunk = {**base, "choices": [{"index": 0, "delta": {
                "tool_calls": [{"index": idx, **tc}]
            }, "finish_reason": None}]}
            yield f"data: {json.dumps(tc_chunk, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)

    # --- 结束 chunk（含 vidmuse 扩展字段，前端直接读取，无需再调 GET /decisions）---
    finish_reason = "tool_calls" if tool_calls else "stop"
    stop_chunk: dict = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]}
    if vidmuse is not None:
        stop_chunk["vidmuse"] = vidmuse
    yield f"data: {json.dumps(stop_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# 路由：POST /chat/completions（挂载后完整路径 /v1/chat/completions）
# ---------------------------------------------------------------------------

@router.post("/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionsRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse | StreamingResponse:
    """OpenAI 兼容聊天接口（Director Agent 已接入）。

    流程：
      1. 获取或创建会话
      2. 持久化用户消息
      3. 加载历史消息
      4. 调用 LangGraph 主图（Director Agent + Intent Resolution）
      5. 构造 tool_calls（若 next_action 非空）
      6. 持久化 assistant 消息
      7. 返回非流式或流式响应

    LLM API key 未配置时自动返回兜底文本，不抛出异常。
    """
    svc = ConversationService()
    logger = get_project_logger(body.project_id, module="api.chat")

    # --- 1. 获取或创建会话 ---
    try:
        session = await svc.get_or_create_session(
            project_id=body.project_id,
            user_id=current_user.id,
            session_id=body.session_id,
        )
    except ConversationError as e:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if e.code == "not_found"
                else status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail={"code": e.code, "message": e.message},
        ) from e

    session_id: str = session["id"]

    # --- 2. 提取当前用户消息（取 messages 列表中最后一条 user 消息）---
    user_content = ""
    for m in reversed(body.messages):
        if m.role == "user":
            user_content = m.content
            break

    if not user_content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": "messages 中未找到 user 消息"},
        )

    # --- 3. 持久化用户消息 ---
    await svc.save_user_message(session_id, user_content)

    # --- 4. 加载历史消息（含刚写入的 user 消息）---
    history = await svc.load_history_for_llm(session_id, limit=20)

    # --- 5. 调用 LangGraph 主图（Director Agent + Intent Resolution）---
    reply, requires_confirmation, next_action, pending_decision_id, decision_options = (
        await invoke_director_graph(
            user_id=current_user.id,
            project_id=body.project_id,
            session_id=session_id,
            user_message=user_content,
            history=history,
        )
    )

    # --- 6. 构造 tool_calls（若 next_action 命中白名单）---
    tool_calls = ToolCallBridgeService().build_tool_calls(next_action, body.project_id)

    # --- 6b. 构造 vidmuse 扩展字段（前端直接渲染决策卡，无需额外调用 GET /decisions）---
    vidmuse_ext: dict = {
        "requires_confirmation": requires_confirmation,
        "pending_decision_id": pending_decision_id,
        "decision_options": decision_options,
    }

    completion_id = _make_completion_id()
    created_at = int(time.time())
    model = body.model or _MODEL_ID

    logger.info(
        f"Chat completions: session={session_id!r} stream={body.stream} "
        f"user_len={len(user_content)} reply_len={len(reply)} "
        f"next_action={next_action!r} tool_calls={len(tool_calls)} "
        f"decision_id={pending_decision_id!r}",
        event_type="chat_completions_processed",
    )

    # --- 7. 持久化 assistant 消息（先存后响应，保证追溯一致）---
    await svc.save_assistant_message(
        session_id,
        reply,
        model=model,
        token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )

    # --- 8a. 非流式响应 ---
    if not body.stream:
        return JSONResponse(
            content=_make_non_stream_response(
                completion_id, reply, model, created_at,
                tool_calls=tool_calls or None,
                vidmuse=vidmuse_ext,
            )
        )

    # --- 8b. 流式响应（SSE）---
    return StreamingResponse(
        _stream_reply_generator(
            reply, completion_id, created_at, model,
            tool_calls=tool_calls or None,
            vidmuse=vidmuse_ext,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
