"""Application settings.

工程约束（doc 08）：
  所有业务配置从 config/base/*.yaml 读取，不从环境变量读取。
  环境变量仅用于承载 secret（密码、密钥），在 YAML 中以 ${ENV_VAR} 形式引用。

  此模块是 FastAPI / uvicorn 层访问配置的入口，内部委托给 get_config() 单例，
  避免重复调用各 load_xxx_config() 产生两条并行配置路径。
"""
from functools import lru_cache

from app.core.config import get_config


class Settings:
    """统一配置入口，委托给 VidMuseConfig 单例，对外提供类型明确的属性。"""

    def __init__(self) -> None:
        cfg = get_config()

        # --- App ---
        self.app_name: str = cfg.app.name
        self.app_version: str = cfg.app.version
        self.debug: bool = cfg.app.debug
        self.host: str = cfg.app.host
        self.port: int = cfg.app.port
        self.api_prefix: str = cfg.app.api_prefix
        self.cors_origins: list[str] = cfg.app.cors_origins

        # --- PostgreSQL ---
        self.postgres_host: str = cfg.database.host
        self.postgres_port: int = cfg.database.port
        self.postgres_user: str = cfg.database.username
        self.postgres_password: str = cfg.database.password
        self.postgres_db: str = cfg.database.database
        self.postgres_pool_min: int = cfg.database.pool_min_size
        self.postgres_pool_max: int = cfg.database.pool_max_size

        # --- Redis ---
        self.redis_host: str = cfg.redis.host
        self.redis_port: int = cfg.redis.port
        self.redis_password: str = cfg.redis.password
        self.redis_db: int = cfg.redis.db

        # --- Object Storage / OSS ---
        self.storage_endpoint: str = cfg.storage.endpoint
        self.storage_public_base_url: str = cfg.storage.public_base_url
        self.storage_access_key: str = cfg.storage.access_key
        self.storage_secret_key: str = cfg.storage.secret_key
        self.storage_bucket: str = cfg.storage.bucket
        self.storage_secure: bool = cfg.storage.secure
        self.storage_region: str = cfg.storage.region
        self.storage_presigned_expiry: int = cfg.storage.presigned_expiry
        self.storage_max_upload_size: int = cfg.storage.max_upload_size

    def get_database_url(self) -> str:
        """异步兼容的 PostgreSQL 连接 URL（asyncpg 驱动）。"""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def get_sync_database_url(self) -> str:
        """同步 PostgreSQL 连接 URL（psycopg2 驱动，供 Alembic 使用）。"""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # --- JWT Security ---
    # 直接暴露 SecurityConfig 对象，避免展开太多字段
    # 调用方：settings.security.secret / settings.security.algorithm 等
    @property
    def security(self):
        return get_config().security

    def get_redis_url(self) -> str:
        """Redis 连接 URL。"""
        if self.redis_password:
            return (
                f"redis://:{self.redis_password}"
                f"@{self.redis_host}:{self.redis_port}/{self.redis_db}"
            )
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回全局缓存的 Settings 实例。"""
    return Settings()


settings = get_settings()
