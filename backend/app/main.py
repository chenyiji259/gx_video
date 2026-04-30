"""
VidMuse Backend 入口文件

启动命令：
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""
import asyncio
import sys
from contextlib import asynccontextmanager

# Windows 下默认使用 ProactorEventLoop，psycopg / langgraph-checkpoint-postgres
# 只支持 SelectorEventLoop。必须在任何 asyncio 代码运行前设置。
# Linux/macOS 默认已是 SelectorEventLoop，不受影响。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.openai_compat import router as chat_router
from app.api.v1.assets import router as assets_router
from app.api.v1.assets import global_router as global_assets_router
from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.conversation import router as conversation_router
# from app.api.v1.audio_analysis import router as audio_analysis_router  # 旧流程（音乐MV模式）：已停用
from app.api.v1.decisions import router as decisions_router
from app.api.v1.planning import router as planning_router
from app.api.v1.shots import router as shots_router
from app.api.v1.clips import router as clips_router
from app.api.v1.exports import router as exports_router
from app.api.v1.versions import router as versions_router
from app.api.v1.consistency import router as consistency_router
from app.api.v1.lipsync import router as lipsync_router
from app.api.v1.narrative import router as narrative_router  # doc11 批次1
# from app.api.v1.visual_bible import router as visual_bible_router  # doc 21 决策 D1：已停用
from app.api.v1.timeline import router as timeline_router
from app.api.v1.storyboard import router as storyboard_router
from app.api.v1.workflow import router as workflow_router
from app.api.v1.health import router as health_router
from app.api.v1.project_events import router as project_events_router
from app.api.v1.project_spec import router as project_spec_router
from app.api.v1.projects import router as projects_router
from app.api.v1.dashboard import router as dashboard_router
from app.bootstrap.services import service_manager, initialize_storage_singleton
from app.core.logging import get_logger
from app.core.redis_utils import close_redis_client
from app.core.settings import settings
from app.events.outbox_publisher import OutboxPublisher
from app.tasks import task_worker
from app.utils.ids import generate_ulid

_logger = get_logger("main", layer="system")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期：启动检查依赖 + 启动后台任务，关闭时取消。"""
    _logger.info(f"{settings.app_name} v{settings.app_version} 启动中...")

    # 依赖服务健康检查
    results = await service_manager.check_all()
    _logger.info("依赖服务检查完成: " + str(results))

    # CLASS-05 修复：显式初始化存储单例，避免运行期懒加载的竞态风险
    initialize_storage_singleton()

    # 启动后台任务
    # 1. OutboxPublisher：轮询 outbox_events 并发布到 Redis pub-sub（SSE 的事件源）
    outbox_publisher = OutboxPublisher()
    outbox_task = asyncio.create_task(outbox_publisher.run(), name="outbox_publisher")

    # 2. TaskWorker：消费 Redis 队列执行 Tool 任务
    worker_task = asyncio.create_task(task_worker.run(), name="task_worker")

    _logger.info("后台任务已启动: OutboxPublisher, TaskWorker", event_type="background_tasks_started")

    yield

    # 应用关闭：取消后台任务
    _logger.info("应用关闭，取消后台任务...")
    outbox_task.cancel()
    worker_task.cancel()
    # 等待任务丘静退出（最多 5 秒）
    await asyncio.gather(outbox_task, worker_task, return_exceptions=True)
    await service_manager.close()
    # 关闭全局 Redis 连接池（最后平决，确保各服务已用完）
    await close_redis_client()
    _logger.info("全局 Redis 连接池已关闭")


app = FastAPI(
    title=settings.app_name,
    description="AI Music Video Generation Platform",
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# 全局异常处理器（doc 05 §17.2 统一响应格式）
# ---------------------------------------------------------------------------

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """HTTPException 统一为 {success: false, error: {code, message}} 格式。"""
    req_id = request.headers.get("x-client-request-id") or generate_ulid()
    # detail 可能是 dict（已有 code/message）或简单字符串
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        error = exc.detail
    else:
        error = {"code": "http_error", "message": str(exc.detail)}
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": error, "request_id": req_id},
        headers={"x-request-id": req_id},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic 校验失败统一为 422 响应。"""
    req_id = request.headers.get("x-client-request-id") or generate_ulid()
    errors = exc.errors()
    message = "; ".join(
        f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}" for e in errors
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error": {"code": "validation_error", "message": message},
            "request_id": req_id,
        },
        headers={"x-request-id": req_id},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕获异常统一返回 500，生个日志。"""
    req_id = request.headers.get("x-client-request-id") or generate_ulid()
    _logger.exception(
        f"Unhandled exception on {request.method} {request.url.path}: {exc}",
        event_type="unhandled_exception",
        request_id=req_id,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {"code": "internal_error", "message": "Internal server error"},
            "request_id": req_id,
        },
        headers={"x-request-id": req_id},
    )


# Routes（控制面接口，统一走 /api/v1）
app.include_router(health_router, prefix=settings.api_prefix, tags=["health"])
app.include_router(auth_router, prefix=settings.api_prefix, tags=["auth"])
app.include_router(users_router, prefix=settings.api_prefix, tags=["users"])
app.include_router(projects_router, prefix=settings.api_prefix, tags=["projects"])
app.include_router(assets_router, prefix=settings.api_prefix, tags=["assets"])
app.include_router(global_assets_router, prefix=settings.api_prefix, tags=["assets"])
app.include_router(project_spec_router, prefix=settings.api_prefix, tags=["project-spec"])
app.include_router(project_events_router, prefix=settings.api_prefix, tags=["events"])
app.include_router(conversation_router, prefix=settings.api_prefix, tags=["conversation"])
app.include_router(decisions_router, prefix=settings.api_prefix, tags=["decisions"])  # 8-07
# app.include_router(audio_analysis_router, prefix=settings.api_prefix, tags=["audio-analysis"])  # 9-05  # 旧流程（音乐MV模式）：已停用
app.include_router(planning_router, prefix=settings.api_prefix, tags=["planning"])  # 9-05
app.include_router(shots_router, prefix=settings.api_prefix, tags=["shots"])  # 9-05
app.include_router(workflow_router, prefix=settings.api_prefix, tags=["workflow"])  # 9-05
app.include_router(storyboard_router, prefix=settings.api_prefix, tags=["storyboard"])  # 10-03
app.include_router(clips_router, prefix=settings.api_prefix, tags=["clips"])  # 11-04
app.include_router(timeline_router, prefix=settings.api_prefix, tags=["timeline"])  # 11-06
app.include_router(exports_router, prefix=settings.api_prefix, tags=["exports"])  # 11-08
app.include_router(versions_router, prefix=settings.api_prefix, tags=["versions"])  # 12-04
app.include_router(consistency_router, prefix=settings.api_prefix, tags=["consistency"])  # 13-01
app.include_router(lipsync_router, prefix=settings.api_prefix, tags=["lipsync"])  # 13-04
app.include_router(narrative_router, prefix=settings.api_prefix, tags=["narrative"])  # doc11 批次1
# app.include_router(visual_bible_router, prefix=settings.api_prefix, tags=["visual-bible"])  # doc 21 决策 D1：已停用
app.include_router(dashboard_router, prefix=settings.api_prefix, tags=["dashboard"])

# OpenAI 兼容接口（挂载在 /v1，路径为 /v1/chat/completions）
# 不走 api_prefix=/api/v1，保证与 OpenAI SDK 标准路径兼容
app.include_router(chat_router, prefix="/v1")


@app.get("/")
async def root() -> dict:
    return {"message": settings.app_name, "version": settings.app_version}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        access_log=False,        # 禁用 uvicorn 访问日志
    )
