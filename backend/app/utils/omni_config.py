"""Omni Provider 配置加载工具函数。

消除 AudioAnalysisAgent 和 VisualBibleService 中 _load_omni_config() 的重复实现。
统一从 config/providers/omni.yaml 读取配置，并解析 api_key 环境变量引用。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

_logger = get_logger("utils.omni_config", layer="tool")

# 相对于 backend/ 目录的配置路径
_OMNI_CONFIG_PATH: Path = (
    Path(__file__).resolve().parents[3] / "config" / "providers" / "omni.yaml"
)


def load_omni_config() -> dict[str, Any]:
    """加载 Omni provider 配置（config/providers/omni.yaml）。

    自动解析 api_key_env 字段并从环境变量注入 api_key。

    Returns:
        配置 dict，至少包含：
          endpoint (str)     — API 基础 URL
          model_name (str)   — 模型名称
          api_key (str)      — 从环境变量解析的 API Key（可能为空）
          timeout (int)      — 请求超时秒数
        失败时返回空 dict，调用方应自行兜底。
    """
    try:
        import yaml  # type: ignore[import-untyped]

        if _OMNI_CONFIG_PATH.exists():
            with open(_OMNI_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg: dict[str, Any] = yaml.safe_load(f) or {}
            api_key_env = cfg.get("api_key_env", "OMNI_API_KEY")
            cfg["api_key"] = os.environ.get(api_key_env, "")
            return cfg
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            f"Omni 配置加载失败，将使用空配置兜底: {exc!r}",
            event_type="omni_config_load_failed",
        )
    return {}
