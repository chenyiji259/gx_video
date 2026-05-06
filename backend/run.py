"""
VidMuse 后端启动脚本（Windows 兼容版）

在 uvicorn 创建事件循环之前先设置 WindowsSelectorEventLoopPolicy，
确保 psycopg / langgraph-checkpoint-postgres 能正常使用 AsyncPostgresSaver。

用法：
    python run.py              # 生产/调试模式（不带 --reload，避免 spawn 子进程覆盖策略）
    python run.py --reload     # 开发热重载（Windows 下 ProactorEventLoop 警告仍可能出现）
"""
import asyncio
import sys

# ⚑ 必须在 uvicorn import 之前执行
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import argparse
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VidMuse Backend Runner")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8003)
    parser.add_argument("--reload", action="store_true", help="热重载（开发用，Windows 下 SelectorEventLoop 保障较弱）")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers if not args.reload else 1,
        loop="asyncio",          # 显式指定 asyncio 事件循环（不用 uvloop / auto）
        access_log=False,        # 禁用 uvicorn 访问日志（频繁轮询请求不记录）
    )
