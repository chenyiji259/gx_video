"""创建初始测试用户。

使用方式（在 backend/ 目录下）：
    # 需要先设置环境变量
    $env:JWT_SECRET="your-dev-secret"
    $env:POSTGRES_PASSWORD="your-db-password"

    python scripts/seed_user.py --username admin --password changeme

    # 或使用默认值（仅开发环境）
    python scripts/seed_user.py
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

# 确保 backend/ 目录在 sys.path 中
_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))


async def main(username: str, password: str) -> None:
    from app.services.auth_service import AuthError, AuthService

    print(f"Creating user: username={username!r}")
    try:
        user = await AuthService().create_user(username, password)
        print(f"✓ User created successfully: id={user.id!r} username={user.username!r}")
    except AuthError as e:
        if e.code == "username_taken":
            print(f"⚠ User '{username}' already exists, skipping.")
        else:
            print(f"✗ Error: {e.message}")
            sys.exit(1)
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed a user into the database")
    parser.add_argument("--username", default="admin", help="Username (default: admin)")
    parser.add_argument("--password", default="vidmuse2026", help="Password (default: vidmuse2026)")
    args = parser.parse_args()

    # 检查必要的环境变量
    if not os.environ.get("JWT_SECRET"):
        print("Error: JWT_SECRET environment variable is not set.")
        print("Example: $env:JWT_SECRET='your-dev-secret'")
        sys.exit(1)
    if not os.environ.get("POSTGRES_PASSWORD"):
        print("Warning: POSTGRES_PASSWORD is not set, using empty password.")

    asyncio.run(main(args.username, args.password))
