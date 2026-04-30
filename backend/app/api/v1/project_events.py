"""Project SSE（Server-Sent Events）接口。

来源文档：doc 07 §10（SSE 驱动设计）

接口：
  GET /api/v1/projects/{project_id}/events/stream

架构（完整调用链）：
  advance_project()
    → EventLogService.emit()   写 outbox_events
    → OutboxPublisher PUBLISH  vidmuse:events:project
    → 此端点订阅 Redis 频道   → 推给前端工作台

设计约束：
  - 验证 Bearer token 和项目所属权（用户不能订阅他人项目的事件流）
  - 每 30 秒发一次 SSE 心跳注释行，防止代理和浏览器超时断连
  - 使用 pubsub.get_message(timeout=1.0) 非阻塞轮询，每轮检查客户端是否已断开
  - 按 payload._project_id 过滤，只转发属于本项目的事件
  - 客户端断开后 finally 块清理 Redis 订阅，防止内存/连接泄漏

SSE 格式（RFC 8895）：
  data: {"event_type": "project_audio_analyzed", ...}\n\n
  : heartbeat\n\n       ← 注释行，不触发 onmessage
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator, Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.api.v1.deps import get_current_user  # kept for other potential uses
from app.core.logging import get_logger
from app.core.redis_utils import build_redis_url
from app.core.security import TokenDecodeError, get_user_id_from_token
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork

# SSE 专用：可选认证依赖（不抛异常，返回 None 让路由做 query param fallback）
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
_sse_bearer = HTTPBearer(auto_error=False)


async def _get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_sse_bearer),
) -> Optional[User]:
    """SSE 专用可选认证：有 Bearer header 就验证，否则返回 None（不抛 401）。"""
    if credentials is None or not credentials.credentials:
        return None
    try:
        from app.repositories.user_repository import UserRepository  # noqa: PLC0415
        from app.core.database import get_session_factory  # noqa: PLC0415
        user_id = get_user_id_from_token(credentials.credentials, expected_type="access")
        async with get_session_factory()() as session:
            repo = UserRepository(session)
            return await repo.get_by_id(user_id)
    except (TokenDecodeError, Exception):  # noqa: BLE001
        return None

router = APIRouter(prefix="/projects", tags=["events"])
_logger = get_logger("api.project_events", layer="system")

# OutboxPublisher 发布的 project 事件频道（与 outbox_publisher.py 保持一致）
_PROJECT_EVENT_CHANNEL = "vidmuse:events:project"

# SSE 心跳间隔（秒）
_HEARTBEAT_INTERVAL = 30


async def _verify_project_ownership(
    project_id: str,
    user_id: str,
) -> None:
    """验证项目所属权，用户不能订阅他人项目的事件流。

    Raises:
        HTTPException 404: 项目不存在或不属于当前用户。
    """
    async with UnitOfWork() as uow:
        repo = ProjectRepository(uow.session)
        project = await repo.get_by_id_for_user(project_id, user_id)

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"项目 {project_id!r} 不存在"},
        )


@router.get("/{project_id}/events/stream")
async def project_events_stream(
    project_id: str,
    request: Request,
    token: Optional[str] = Query(None, description="Bearer token via query param (EventSource fallback)"),
    current_user: Optional[User] = Depends(_get_optional_user),
) -> StreamingResponse:
    """订阅项目事件流（SSE）。

    支持两种 token 传递方式：
    1. Authorization: Bearer <token>  (标准，Axios/fetch 使用)
    2. ?token=<token>                 (EventSource fallback，因浏览器 EventSource 不支持自定义头)

    前端通过 EventSource 连接，只能通过 query param 传 token：
        const es = new EventSource(`/api/v1/projects/{id}/events/stream?token=${token}`);
        es.onmessage = (e) => { const event = JSON.parse(e.data); ... };

    Returns:
        StreamingResponse（text/event-stream）

    Raises:
        HTTPException 401: token 无效。
        HTTPException 404: 项目不存在或不属于当前用户。
    """
    # 如果 get_current_user 依赖（Authorization header）未能认证用户，
    # 则尝试从 query param ?token= 手动验证
    user = current_user
    if user is None and token:
        try:
            from app.repositories.user_repository import UserRepository  # noqa: PLC0415
            from app.core.database import get_session_factory  # noqa: PLC0415
            user_id = get_user_id_from_token(token, expected_type="access")
            async with get_session_factory()() as session:
                repo = UserRepository(session)
                user = await repo.get_by_id(user_id)
        except (TokenDecodeError, Exception):
            user = None

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Missing or invalid token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    await _verify_project_ownership(project_id, user.id)

    _logger.info(
        f"SSE 连接建立: project_id={project_id!r} user_id={user.id!r}",
        event_type="sse_connected",
    )

    return StreamingResponse(
        _event_generator(request, project_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # 关闭 Nginx 缓冲，确保实时推送
        },
    )


async def _event_generator(
    request: Request,
    project_id: str,
) -> AsyncIterator[str]:
    """SSE 事件生成器。

    订阅 Redis pub-sub 频道，过滤本项目事件，以 SSE 格式 yield 给客户端。
    """
    redis_client = aioredis.from_url(
        build_redis_url(),
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_keepalive=True,
        health_check_interval=30,
        retry_on_timeout=True,
    )
    pubsub = redis_client.pubsub()

    try:
        await pubsub.subscribe(_PROJECT_EVENT_CHANNEL)

        # 发送连接建立事件（让前端确认 SSE 已就绪）
        connected_payload = json.dumps({
            "event_type": "sse_connected",
            "project_id": project_id,
        })
        yield f"data: {connected_payload}\n\n"

        last_heartbeat = time.monotonic()

        while True:
            # 检测客户端断开
            if await request.is_disconnected():
                _logger.info(
                    f"SSE 客户端断开: project_id={project_id!r}",
                    event_type="sse_disconnected",
                )
                break

            # 非阻塞拉取消息，等待最多 1 秒
            try:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    f"SSE get_message 异常: {exc!r}",
                    event_type="sse_get_message_error",
                )
                await asyncio.sleep(0.5)
                continue

            if message is not None and message.get("type") == "message":
                raw_data = message.get("data", "")
                _logger.info(
                    f"[SSE] 收到 Redis 消息: raw_data={raw_data[:200] if raw_data else None}...",
                    event_type="sse_message_received",
                )
                try:
                    payload = json.loads(raw_data)
                    # 按 project_id 过滤（OutboxPublisher 写入了 _project_id 字段）
                    _project_id_in_payload = payload.get("_project_id")
                    _logger.info(
                        f"[SSE] 消息过滤检查: payload._project_id={_project_id_in_payload}, target_project_id={project_id}, match={_project_id_in_payload == project_id}",
                        event_type="sse_message_filter_check",
                    )
                    if payload.get("_project_id") == project_id:
                        _logger.info(f"[SSE] 匹配成功，发送给前端: event_type={payload.get('event_type')}", event_type="sse_message_yield")
                        yield f"data: {json.dumps(payload)}\n\n"
                except (json.JSONDecodeError, AttributeError):
                    _logger.warning(f"[SSE] 非 JSON 消息: raw_data={raw_data}", event_type="sse_non_json_message")
                    pass  # 忽略非 JSON 消息

            # 每 30 秒发一次心跳（SSE 注释行，不触发 onmessage）
            now = time.monotonic()
            if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
                yield ": heartbeat\n\n"
                last_heartbeat = now

    except asyncio.CancelledError:
        _logger.info(
            f"SSE 生成器被取消: project_id={project_id!r}",
            event_type="sse_cancelled",
        )
        raise
    finally:
        # 取消订阅并关闭连接，防止资源泄漏
        try:
            await pubsub.unsubscribe(_PROJECT_EVENT_CHANNEL)
            await pubsub.aclose()
        except Exception:  # noqa: BLE001
            pass
        try:
            await redis_client.aclose()
        except Exception:  # noqa: BLE001
            pass
        _logger.info(
            f"SSE 连接关闭: project_id={project_id!r}",
            event_type="sse_closed",
        )
