"""
连接测试脚本：PostgreSQL + Redis
从 .env 文件读取密码，不硬编码敏感信息。
运行方式：python test_connections.py
"""

import os
import sys
import time
from pathlib import Path

# ── 加载 .env 文件（不依赖 python-dotenv，手动解析即可）─────────────────────
def load_env(env_path: Path) -> None:
    if not env_path.exists():
        print(f"[WARN] .env 文件不存在: {env_path}")
        return
    with env_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

load_env(Path(__file__).parent / ".env")

# ── 读取配置（host/port 硬编码在 yaml，这里直接写；密码走环境变量）──────────
PG_HOST     = "8.134.170.191"
PG_PORT     = 5432
PG_USER     = "vidumuse"
PG_DB       = "vidumuse"
PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")

REDIS_HOST     = "8.134.170.191"
REDIS_PORT     = 6379
REDIS_DB       = 0
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")


def sep(title: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print('─' * 50)


# ────────────────────────────────────────────────────────────────────────────
# 1. PostgreSQL — 用 psycopg2（同步，最通用）
# ────────────────────────────────────────────────────────────────────────────
def test_postgres() -> bool:
    sep("PostgreSQL  (psycopg2)")
    print(f"  Host : {PG_HOST}:{PG_PORT}")
    print(f"  User : {PG_USER}  /  DB: {PG_DB}")
    try:
        import psycopg2  # type: ignore
    except ImportError:
        print("  [SKIP] psycopg2 未安装，跳过")
        return False

    try:
        t0 = time.monotonic()
        conn = psycopg2.connect(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD,
            dbname=PG_DB,
            connect_timeout=10,
        )
        elapsed = (time.monotonic() - t0) * 1000

        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            cur.execute("SELECT current_database(), current_user, pg_postmaster_start_time();")
            db, user, start_time = cur.fetchone()

        conn.close()
        print(f"  [OK]  连接成功，耗时 {elapsed:.1f} ms")
        print(f"  版本 : {version.split(',')[0]}")
        print(f"  数据库: {db}  用户: {user}")
        print(f"  服务启动时间: {start_time}")
        return True

    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return False


# ────────────────────────────────────────────────────────────────────────────
# 2. Redis
# ────────────────────────────────────────────────────────────────────────────
def test_redis() -> bool:
    sep("Redis")
    print(f"  Host : {REDIS_HOST}:{REDIS_PORT}  DB={REDIS_DB}")
    try:
        import redis  # type: ignore
    except ImportError:
        print("  [SKIP] redis 未安装，跳过")
        return False

    try:
        t0 = time.monotonic()
        r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD if REDIS_PASSWORD else None,
            socket_connect_timeout=10,
            decode_responses=True,
        )
        pong = r.ping()
        elapsed = (time.monotonic() - t0) * 1000

        info = r.info("server")
        print(f"  [OK]  PING → {pong}，耗时 {elapsed:.1f} ms")
        print(f"  版本 : Redis {info.get('redis_version')}")
        print(f"  模式 : {info.get('redis_mode', 'standalone')}")
        print(f"  已用内存: {info.get('used_memory_human')}")
        r.close()
        return True

    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return False


# ────────────────────────────────────────────────────────────────────────────
# 汇总
# ────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    results = {
        "PostgreSQL": test_postgres(),
        "Redis":      test_redis(),
    }

    sep("汇总")
    all_ok = True
    for name, ok in results.items():
        status = "✓ 通过" if ok else "✗ 失败"
        print(f"  {status}  {name}")
        if not ok:
            all_ok = False

    print()
    sys.exit(0 if all_ok else 1)
