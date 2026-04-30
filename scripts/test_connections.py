"""
连接测试脚本 - 测试 PostgreSQL / MinIO / Redis 连通性

使用方式（在项目根目录执行）：
    python scripts/test_connections.py

依赖：requirements.txt 中已包含所有库
会自动加载根目录 .env 文件
"""
import asyncio
import sys
from pathlib import Path

# 加载根目录 .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# 读取配置
from app.core.config_loader import (
    load_database_config,
    load_redis_config,
    load_storage_config,
)

# ── 颜色输出 ────────────────────────────────────────────
def ok(msg: str) -> None:
    print(f"  \033[32m✓ {msg}\033[0m")

def fail(msg: str) -> None:
    print(f"  \033[31m✗ {msg}\033[0m")

def section(title: str) -> None:
    print(f"\n\033[1m[{title}]\033[0m")


# ── PostgreSQL ───────────────────────────────────────────
async def test_postgres() -> bool:
    section("PostgreSQL")
    cfg = load_database_config()
    print(f"  → {cfg.host}:{cfg.port}  db={cfg.database}  user={cfg.username}")
    try:
        import asyncpg
        conn = await asyncpg.connect(
            host=cfg.host,
            port=cfg.port,
            user=cfg.username,
            password=cfg.password,
            database=cfg.database,
            timeout=5,
        )
        result = await conn.fetchval("SELECT version()")
        await conn.close()
        ok(f"连接成功 — {result[:60]}...")
        return True
    except Exception as e:
        fail(f"连接失败: {e}")
        return False


# ── Redis ────────────────────────────────────────────────
async def test_redis() -> bool:
    section("Redis")
    cfg = load_redis_config()
    print(f"  → {cfg.host}:{cfg.port}  db={cfg.db}")
    try:
        import redis.asyncio as aioredis
        url = (
            f"redis://:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.db}"
            if cfg.password
            else f"redis://{cfg.host}:{cfg.port}/{cfg.db}"
        )
        client = aioredis.from_url(url, socket_connect_timeout=5, decode_responses=True)
        pong = await client.ping()
        info = await client.info("server")
        version = info.get("redis_version", "?")
        await client.aclose()
        ok(f"连接成功 — PING={pong}  Redis v{version}")
        return True
    except Exception as e:
        fail(f"连接失败: {e}")
        return False


# ── MinIO ────────────────────────────────────────────────
async def test_minio() -> bool:
    section("MinIO")
    cfg = load_storage_config()
    print(f"  → {cfg.endpoint}  bucket={cfg.bucket}  secure={cfg.secure}")
    try:
        from minio import Minio
        client = Minio(
            cfg.endpoint,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key,
            secure=cfg.secure,
        )
        # bucket_exists 是同步调用
        exists = await asyncio.to_thread(client.bucket_exists, cfg.bucket)
        if exists:
            ok(f"连接成功 — bucket '{cfg.bucket}' 存在")
        else:
            # 连接通了但桶不存在，提示创建
            ok(f"连接成功 — bucket '{cfg.bucket}' 不存在（需要手动创建）")
        return True
    except Exception as e:
        fail(f"连接失败: {e}")
        return False


# ── 主入口 ───────────────────────────────────────────────
async def main() -> None:
    print("=" * 50)
    print("  VidMuse 连接测试")
    print("=" * 50)

    results = await asyncio.gather(
        test_postgres(),
        test_redis(),
        test_minio(),
        return_exceptions=False,
    )

    pg_ok, redis_ok, minio_ok = results

    print("\n" + "=" * 50)
    print("  测试结果汇总")
    print("=" * 50)
    print(f"  PostgreSQL : {'✓ 正常' if pg_ok    else '✗ 失败'}")
    print(f"  Redis      : {'✓ 正常' if redis_ok  else '✗ 失败'}")
    print(f"  MinIO      : {'✓ 正常' if minio_ok  else '✗ 失败'}")
    print()

    if all(results):
        print("\033[32m  全部连接正常，可以启动服务 🚀\033[0m\n")
        sys.exit(0)
    else:
        print("\033[31m  存在连接失败，请检查配置和网络\033[0m\n")
        sys.exit(1)


if __name__ == "__main__":
    # 将 backend 目录加入 Python 路径，使 app.* 可以被正常 import
    backend_dir = Path(__file__).parent.parent / "backend"
    sys.path.insert(0, str(backend_dir))
    asyncio.run(main())
