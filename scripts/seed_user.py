"""
创建测试账户
============
在数据库中创建 E2E 测试用的用户，仅需执行一次。

运行方式：
    cd C:/Users/Administrator/Desktop/1/vidMuse
    python scripts/seed_user.py

    可选参数（修改下方 CONFIG）：
      USERNAME  用户名（默认 admin）
      PASSWORD  密码（默认 changeme）
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 将 backend 目录加入 Python 路径
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

# 加载 .env（需要 POSTGRES_PASSWORD / JWT_SECRET 等）
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

CONFIG = {
    "USERNAME": "admin",
    "PASSWORD": "123456",
}


async def main() -> None:
    from app.services.auth_service import AuthError, AuthService

    username = CONFIG["USERNAME"]
    password = CONFIG["PASSWORD"]

    print(f"创建用户: username={username!r}")
    try:
        user = await AuthService().create_user(username, password)
        print(f"\033[32m✓ 用户已创建: id={user.id}  username={user.username}\033[0m")
    except AuthError as e:
        if e.code == "username_taken":
            print(f"\033[33m! 用户 '{username}' 已存在，无需重复创建\033[0m")
        else:
            print(f"\033[31m✗ 创建失败: {e.message}\033[0m")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
