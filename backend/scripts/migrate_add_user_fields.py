"""
数据库迁移：给 users 表补充 credits 和 plan_type 字段。

运行方式：
    python backend/scripts/migrate_add_user_fields.py
"""
import asyncio
import sys
import os

# 把项目根目录加到 sys.path，以便读取 .env
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))
except ImportError:
    pass

import asyncpg


async def migrate() -> None:
    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not password:
        print("ERROR: POSTGRES_PASSWORD env var not set.")
        sys.exit(1)

    conn = await asyncpg.connect(
        host="8.134.170.191",
        port=5432,
        user="vidumuse",
        password=password,
        database="vidumuse",
    )
    try:
        print("Connected. Running migrations...")

        await conn.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS credits INTEGER NOT NULL DEFAULT 200;
        """)
        print("  ✓ credits column added (or already exists)")

        await conn.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS plan_type VARCHAR(32) NOT NULL DEFAULT 'free';
        """)
        print("  ✓ plan_type column added (or already exists)")

        # 验证
        rows = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'users' ORDER BY ordinal_position"
        )
        print("\nCurrent users columns:")
        for r in rows:
            print(f"  - {r['column_name']} ({r['data_type']})")

        print("\nMigration complete.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
