"""Configuration loader for YAML config files."""
import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

# 自动加载项目根目录的 .env 文件（vidMuse/.env）
# 路径：config_loader.py 向上 3 层到达 vidMuse/
_ENV_FILE = Path(__file__).parent.parent.parent.parent / ".env"
load_dotenv(_ENV_FILE, override=False)  # override=False 表示已有的环境变量不被覆盖


class DatabaseConfig(BaseModel):
    """Database configuration."""
    host: str
    port: int
    username: str
    password: str
    database: str
    pool_min_size: int = 5
    pool_max_size: int = 60


class RedisConfig(BaseModel):
    """Redis configuration."""
    host: str
    port: int
    password: str = ""
    db: int = 0


class StorageConfig(BaseModel):
    """MinIO / S3 Compatible Storage configuration."""
    endpoint: str                    # "host:port"
    access_key: str
    secret_key: str
    bucket: str
    secure: bool = False
    region: str = "us-east-1"
    presigned_expiry: int = 3600     # 预签名 URL 过期秒数
    max_upload_size: int = 104857600 # 单文件上传上限，默认 100MB


class AppConfig(BaseModel):
    """Application configuration."""
    name: str
    version: str
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    # API 层配置（来自 app.yaml 的 api section）
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["*"]


class SecurityConfig(BaseModel):
    """JWT 安全配置。

    secret 必须通过 ${JWT_SECRET} 环境变量注入，
    绝不允许写死在代码或 yaml 默认值中。
    """
    secret: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7


class LoggingConfig(BaseModel):
    """日志系统配置。"""
    level: str = "INFO"
    format: str = "json"
    rotation: str = "100 MB"
    retention: str = "30 days"
    log_dir: str = "logs"


class WorkflowConfig(BaseModel):
    """工作流引擎配置。"""
    state_machine_strict: bool = True
    auto_retry_count: int = 2
    allow_provider_fallback: bool = True
    max_concurrent_jobs: int = 4
    job_timeout_seconds: int = 300
    decision_expire_seconds: int = 3600
    checkpoint_backend: str = "sqlite"
    checkpoint_sqlite_path: str = "data/checkpoints/langgraph.db"
    # Director Mode B 审核产物内容的最大字符数（对应 workflow.yaml artifact_review_max_chars）
    artifact_review_max_chars: int = 10000
    # 调试开关：自动确认所有人工决策阶段（生产环境必须为 False）
    auto_confirm_decisions: bool = False


class MediaConfig(BaseModel):
    """媒体处理配置。"""
    ffmpeg_path: str = ""


class LLMConfig(BaseModel):
    """LLM 调用配置。

    api_key 必须通过环境变量注入（api_key_env），绝不允许硬编码。
    """
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.3
    max_tokens: int = 2048
    timeout: int = 60
    # qwen3.5 系列默认开展思考模式，必须关闭才能输出干净 JSON
    enable_thinking: bool = False
    # shot plan 专用 max_tokens 基础値（16-02）
    # 实际应用値 = max(max_tokens_shot_plan, max_shots * 250)
    max_tokens_shot_plan: int = 8192

    @property
    def api_key(self) -> str:
        """从环境变量读取 API key（不缓存，支持运行时更新）。"""
        return os.environ.get(self.api_key_env, "")


class ToolPricingConfig(BaseModel):
    """单个工具的计费配置。"""
    unit: str
    price_per_unit: float


class BillingConfig(BaseModel):
    """计费与 Credits 配置。"""
    currency: str = "credits"
    free_quota_per_user: int = 100
    tools: dict[str, ToolPricingConfig] = {}


def load_yaml_config(config_path: str) -> dict[str, Any]:
    """Load YAML configuration file with environment variable substitution."""
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Replace ${ENV_VAR} with environment variable values
    for match in re.finditer(r'\$\{([^}]+)\}', content):
        env_var = match.group(1)
        env_value = os.environ.get(env_var, '')
        content = content.replace(f'${{{env_var}}}', env_value)

    return yaml.safe_load(content)


def get_config_dir() -> Path:
    """Get config directory path."""
    return Path(__file__).parent.parent.parent.parent / "config" / "base"


def load_database_config() -> DatabaseConfig:
    """Load database configuration."""
    config_path = get_config_dir() / "database.yaml"
    data = load_yaml_config(str(config_path))
    db_data = data.get("database", {})
    return DatabaseConfig(
        host=db_data.get("host", "localhost"),
        port=db_data.get("port", 5432),
        username=db_data.get("username", "vidmuse"),
        password=db_data.get("password", ""),
        database=db_data.get("database", "vidmuse"),
        pool_min_size=db_data.get("pool", {}).get("min_size", 2),
        pool_max_size=db_data.get("pool", {}).get("max_size", 20),
    )


def load_redis_config() -> RedisConfig:
    """Load Redis configuration."""
    config_path = get_config_dir() / "redis.yaml"
    data = load_yaml_config(str(config_path))
    redis_data = data.get("redis", {})
    return RedisConfig(
        host=redis_data.get("host", "localhost"),
        port=redis_data.get("port", 6379),
        password=redis_data.get("password", ""),
        db=redis_data.get("db", 0),
    )


def load_storage_config() -> StorageConfig:
    """Load storage configuration."""
    config_path = get_config_dir() / "storage.yaml"
    data = load_yaml_config(str(config_path))
    storage_data = data.get("storage", {})
    return StorageConfig(
        endpoint=storage_data.get("endpoint", "localhost:9000"),
        access_key=storage_data.get("access_key", ""),
        secret_key=storage_data.get("secret_key", ""),
        bucket=storage_data.get("bucket", "vidmuse"),
        secure=storage_data.get("secure", False),
        region=storage_data.get("region", "us-east-1"),
        presigned_expiry=storage_data.get("presigned_expiry", 3600),
        max_upload_size=storage_data.get("max_upload_size", 104857600),
    )


def load_app_config() -> AppConfig:
    """Load application configuration."""
    config_path = get_config_dir() / "app.yaml"
    data = load_yaml_config(str(config_path))
    app_data = data.get("app", {})
    api_data = data.get("api", {})
    return AppConfig(
        name=app_data.get("name", "VidMuse"),
        version=app_data.get("version", "0.1.0"),
        debug=app_data.get("debug", False),
        host=app_data.get("host", "0.0.0.0"),
        port=app_data.get("port", 8000),
        api_prefix=api_data.get("prefix", "/api/v1"),
        cors_origins=api_data.get("cors_origins", ["*"]),
    )


def load_logging_config() -> LoggingConfig:
    """加载日志配置。"""
    config_path = get_config_dir() / "logging.yaml"
    data = load_yaml_config(str(config_path))
    log_data = data.get("logging", {})
    return LoggingConfig(
        level=log_data.get("level", "INFO"),
        format=log_data.get("format", "json"),
        rotation=log_data.get("rotation", "100 MB"),
        retention=log_data.get("retention", "30 days"),
        log_dir=log_data.get("log_dir", "logs"),
    )


def load_workflow_config() -> WorkflowConfig:
    """加载工作流引擎配置。"""
    config_path = get_config_dir() / "workflow.yaml"
    data = load_yaml_config(str(config_path))
    wf_data = data.get("workflow", {})
    return WorkflowConfig(
        state_machine_strict=wf_data.get("state_machine_strict", True),
        auto_retry_count=wf_data.get("auto_retry_count", 2),
        allow_provider_fallback=wf_data.get("allow_provider_fallback", True),
        max_concurrent_jobs=wf_data.get("max_concurrent_jobs", 4),
        job_timeout_seconds=wf_data.get("job_timeout_seconds", 300),
        decision_expire_seconds=wf_data.get("decision_expire_seconds", 3600),
        checkpoint_backend=wf_data.get("checkpoint_backend", "sqlite"),
        checkpoint_sqlite_path=wf_data.get("checkpoint_sqlite_path", "data/checkpoints/langgraph.db"),
        artifact_review_max_chars=int(wf_data.get("artifact_review_max_chars", 10000)),
        auto_confirm_decisions=bool(wf_data.get("auto_confirm_decisions", False)),
    )


def load_media_config() -> MediaConfig:
    """加载媒体处理配置。"""
    config_path = get_config_dir() / "app.yaml"
    data = load_yaml_config(str(config_path))
    media_data = data.get("media", {})
    return MediaConfig(
        ffmpeg_path=(media_data.get("ffmpeg_path", "") or "").strip(),
    )


def load_security_config() -> SecurityConfig:
    """Load JWT security configuration from app.yaml.

    Raises ValueError if JWT_SECRET env var is not set (empty after substitution).
    """
    config_path = get_config_dir() / "app.yaml"
    data = load_yaml_config(str(config_path))
    jwt_data = data.get("jwt", {})
    secret = jwt_data.get("secret", "")
    if not secret:
        raise ValueError(
            "JWT_SECRET 环境变量未设置。"
            "请在环境中设置并执行：export JWT_SECRET=<your-secret>"
        )
    return SecurityConfig(
        secret=secret,
        algorithm=jwt_data.get("algorithm", "HS256"),
        access_token_expire_minutes=int(jwt_data.get("access_token_expire_minutes", 30)),
        refresh_token_expire_days=int(jwt_data.get("refresh_token_expire_days", 7)),
    )


def load_llm_config() -> LLMConfig:
    """加载 LLM 调用配置。"""
    config_path = get_config_dir() / "llm.yaml"
    data = load_yaml_config(str(config_path))
    llm_data = data.get("llm", {})
    base_url = llm_data.get("base_url")
    return LLMConfig(
        provider=llm_data.get("provider", "openai"),
        model=llm_data.get("model", "gpt-4o-mini"),
        base_url=base_url if base_url else None,
        api_key_env=llm_data.get("api_key_env", "OPENAI_API_KEY"),
        temperature=float(llm_data.get("temperature", 0.3)),
        max_tokens=int(llm_data.get("max_tokens", 2048)),
        timeout=int(llm_data.get("timeout", 60)),
        enable_thinking=bool(llm_data.get("enable_thinking", False)),
        max_tokens_shot_plan=int(llm_data.get("max_tokens_shot_plan", 8192)),
    )


class HedraConfig(BaseModel):
    """Hedra AI LipSync 服务配置（未正式接入，预留以备后续扩展）。"""
    api_key: str = ""
    base_url: str = "https://mercury.dev.dream-ai.com/api"
    timeout: int = 180
    poll_interval: int = 5
    max_poll_attempts: int = 36


class ToAPIsConfig(BaseModel):
    """ToAPIs 中转服务配置（Grok 视频生成 + GPT Image 2 图片生成共用此凭据）。

    api_key 通过 .env 中的 TOAPIS_API_KEY 注入。
    """
    api_key: str = ""
    base_url: str = "https://toapis.com"
    timeout: int = 660
    poll_interval: int = 10
    max_poll_attempts: int = 66


class ArkConfig(BaseModel):
    """火山方舟（Ark）API 配置 — Seedance 2.0 视频生成。

    api_key 通过 .env 中的 ARK_API_KEY 注入。
    文档：docs/api/seedance2-video-generation-api.md
    """
    api_key: str = ""
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    timeout: int = 660
    poll_interval: int = 15
    max_poll_attempts: int = 50


class ExternalApisConfig(BaseModel):
    """外部 API 凭据聚合配置（config/base/external_apis.yaml）。

    当前已接入：
      - ToAPIs（Grok 视频生成 + GPT Image 2 图片生成）
      - Ark（火山方舟 Seedance 2.0 视频生成）
    预留未用：Hedra（口型同步，待接入）
    """
    hedra: HedraConfig = HedraConfig()
    toapis: ToAPIsConfig = ToAPIsConfig()
    ark: ArkConfig = ArkConfig()


def load_external_apis_config() -> ExternalApisConfig:
    """加载外部 API 凭据配置。"""
    config_path = get_config_dir() / "external_apis.yaml"
    if not config_path.exists():
        return ExternalApisConfig()
    data = load_yaml_config(str(config_path))
    ext_data = data.get("external_apis", {})
    hedra_data = ext_data.get("hedra", {})
    toapis_data = ext_data.get("toapis", {})
    ark_data = ext_data.get("ark", {})
    return ExternalApisConfig(
        hedra=HedraConfig(
            api_key=hedra_data.get("api_key", ""),
            base_url=hedra_data.get("base_url", "https://mercury.dev.dream-ai.com/api"),
            timeout=int(hedra_data.get("timeout", 180)),
            poll_interval=int(hedra_data.get("poll_interval", 5)),
            max_poll_attempts=int(hedra_data.get("max_poll_attempts", 36)),
        ),
        toapis=ToAPIsConfig(
            api_key=toapis_data.get("api_key", ""),
            base_url=toapis_data.get("base_url", "https://toapis.com"),
            timeout=int(toapis_data.get("timeout", 660)),
            poll_interval=int(toapis_data.get("poll_interval", 10)),
            max_poll_attempts=int(toapis_data.get("max_poll_attempts", 66)),
        ),
        ark=ArkConfig(
            api_key=ark_data.get("api_key", ""),
            base_url=ark_data.get("base_url", "https://ark.cn-beijing.volces.com/api/v3"),
            timeout=int(ark_data.get("timeout", 660)),
            poll_interval=int(ark_data.get("poll_interval", 15)),
            max_poll_attempts=int(ark_data.get("max_poll_attempts", 50)),
        ),
    )


def load_billing_config() -> BillingConfig:
    """加载计费与 Credits 配置。"""
    config_path = get_config_dir() / "billing.yaml"
    data = load_yaml_config(str(config_path))
    billing_data = data.get("billing", {})
    tools_raw = billing_data.get("tools", {})
    tools = {
        name: ToolPricingConfig(
            unit=cfg.get("unit", "count"),
            price_per_unit=float(cfg.get("price_per_unit", 1.0)),
        )
        for name, cfg in tools_raw.items()
    }
    return BillingConfig(
        currency=billing_data.get("currency", "credits"),
        free_quota_per_user=billing_data.get("free_quota_per_user", 100),
        tools=tools,
    )
