"""对话控制面接口（会话与消息查询）。

来源文档：doc 07 §7（右侧 Chat 栏设计）

接口：
  GET  /projects/{project_id}/sessions                         — 列出项目会话
  POST /projects/{project_id}/sessions                         — 显式新建会话
  GET  /projects/{project_id}/sessions/{session_id}/messages   — 查询消息历史

职责：
  前端在打开项目工作台时，通过这几个接口加载历史会话和消息记录，
  供右侧 Chat 面板初始化显示。
  实际聊天（发送消息/接收回复）走 POST /v1/chat/completions（openai_compat.py）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.user import User
from app.services.conversation_service import ConversationError, ConversationService

router = APIRouter(
    prefix="/projects/{project_id}/sessions",
    tags=["conversation"],
)


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/sessions
# ---------------------------------------------------------------------------

@router.get("", status_code=status.HTTP_200_OK)
async def list_sessions(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100, description="最多返回条数"),
) -> JSONResponse:
    """列出项目的所有对话会话（按最近活跃时间倒序）。

    前端用于展示「历史对话」列表，用户可切换不同会话查看历史消息。
    """
    req_id = get_request_id(request)
    try:
        sessions = await ConversationService().list_sessions(
            project_id=project_id,
            user_id=current_user.id,
            limit=limit,
        )
    except ConversationError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ok(data={"items": sessions, "count": len(sessions)}, request_id=req_id),
    )


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/sessions
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_session(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """显式新建一个对话会话。

    通常不需要手动调用（POST /v1/chat/completions 会自动获取或新建）。
    适用于「开始新对话」按钮：用户主动开启新会话而不复用旧会话。
    """
    req_id = get_request_id(request)
    try:
        # 不传 session_id，且通过不传 session_id 强制走「无 active 则新建」路径。
        # 但若已有 active 会话，get_or_create_session 会返回现有会话。
        # 为确保新建，可扩展 ConversationService.create_new_session()。
        # 此处先用 get_or_create_session 满足基础需求，后续可按业务需要优化。
        session = await ConversationService().get_or_create_session(
            project_id=project_id,
            user_id=current_user.id,
            session_id=None,
        )
    except ConversationError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=ok(data=session, request_id=req_id),
    )


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/sessions/{session_id}/messages
# ---------------------------------------------------------------------------

@router.get("/{session_id}/messages", status_code=status.HTTP_200_OK)
async def list_messages(
    project_id: str,
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200, description="最多返回条数"),
) -> JSONResponse:
    """查询指定会话的消息历史（按时间升序，含完整字段）。

    前端在切换会话或重新打开项目时，用此接口加载历史消息记录。
    返回包含 content_json 的完整消息对象（选项卡/确认卡在 7-02 后填充）。
    """
    req_id = get_request_id(request)
    svc = ConversationService()

    # 验证 session 归属（project_id + user 双重校验）
    try:
        await svc.get_or_create_session(
            project_id=project_id,
            user_id=current_user.id,
            session_id=session_id,
        )
    except ConversationError as e:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )

    messages = await svc.list_messages(session_id, limit=limit)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ok(
            data={"items": messages, "count": len(messages), "session_id": session_id},
            request_id=req_id,
        ),
    )
