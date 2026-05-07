"""统一配置门面（Unified Config Facade）。

工程约束（doc 08）：
  - 所有业务配置从 config/base/*.yaml 读取，不从环境变量读取。
  - 环境变量仅承载 secret（密码、密钥），在 YAML 中以 ${ENV_VAR} 形式引用。
  - 此模块是所有后端代码访问配置的唯一入口。

用法：
    from app.core.config import get_config

    cfg = get_config()
    cfg.database.host       # PostgreSQL 主机
    cfg.billing.tools       # 工具计费规则
    cfg.logging.level       # 日志级别
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.core.config_loader import (
    AppConfig,
    BillingConfig,
    DatabaseConfig,
    ExternalApisConfig,
    LLMConfig,
    LoggingConfig,
    RedisConfig,
    SecurityConfig,
    StorageConfig,
    TalkingHeadConfig,
    WorkflowConfig,
    load_app_config,
    load_billing_config,
    load_database_config,
    load_external_apis_config,
    load_llm_config,
    load_logging_config,
    load_redis_config,
    load_security_config,
    load_storage_config,
    load_talking_head_config,
    load_workflow_config,
)


@dataclass(frozen=True)
class VidMuseConfig:
    """全量应用配置，聚合所有 section。

    frozen=True 确保运行时不会意外修改配置。
    """
    app: AppConfig
    database: DatabaseConfig
    redis: RedisConfig
    storage: StorageConfig
    logging: LoggingConfig
    workflow: WorkflowConfig
    billing: BillingConfig
    security: SecurityConfig
    llm: LLMConfig
    external_apis: ExternalApisConfig
    talking_head: TalkingHeadConfig


@lru_cache(maxsize=1)
def get_config() -> VidMuseConfig:
    """返回全局缓存的配置实例。

    首次调用时从 config/base/*.yaml 加载所有配置节，
    后续调用直接返回同一实例（lru_cache 保证单例）。

    如需在测试中重置配置，调用 get_config.cache_clear()。
    """
    return VidMuseConfig(
        app=load_app_config(),
        database=load_database_config(),
        redis=load_redis_config(),
        storage=load_storage_config(),
        logging=load_logging_config(),
        workflow=load_workflow_config(),
        billing=load_billing_config(),
        security=load_security_config(),
        llm=load_llm_config(),
        external_apis=load_external_apis_config(),
        talking_head=load_talking_head_config(),
    )
