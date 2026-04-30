"""VidMuse 日志系统 — 4 层结构化日志。

工程约束（doc 08）：
  日志分四层：system / agent / tool / project
  统一 JSON 格式，字段至少包含：
    timestamp / level / module / project_id / task_id / event_type / message

层级说明：
  system  — 服务启动、全局异常、SSE 连接
  agent   — Agent 输入摘要、输出结构、决策路径
  tool    — Provider 调用、重试次数、产物路径
  project — 阶段推进、回退、stale 标记、重要决策

用法：
    from app.core.logging import get_logger, get_project_logger

    # 系统级
    logger = get_logger("bootstrap.services", layer="system")
    logger.info("Postgres 连接成功")

    # 项目级（自动绑定 project_id）
    plogger = get_project_logger("proj_abc123", module="state_machine")
    plogger.info("项目状态推进", event_type="stage_transition",
                 extra={"from_stage": "audio_analyzed", "to_stage": "brief_ready"})
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger as _loguru_logger

from app.core.config import get_config


# --------------------------------------------------------------------------- #
# 内部：路径与格式工具
# --------------------------------------------------------------------------- #

def _get_log_root() -> Path:
    """返回日志根目录（相对于项目根）。"""
    cfg = get_config()
    log_dir = cfg.logging.log_dir  # e.g. "logs"
    # 从 backend/app/core/logging.py 推算项目根
    project_root = Path(__file__).parent.parent.parent.parent
    return project_root / log_dir


def _get_run_dir() -> Path:
    """返回本次启动的日志目录（logs/YYYYMMDD_HHMMSS/）。"""
    root = _get_log_root()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = root / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _json_formatter(record: dict) -> str:
    """将 loguru record 格式化为单行 JSON 字符串。

    注意：loguru 对 callable format 的返回值仍会调用 str.format_map()，
    因此必须把 JSON 字符串中的 { } 转义为 {{ }}，
    经过 format_map 后会还原为原始 { }，输出仍是合法 JSON。
    """
    extra = record.get("extra", {})
    payload = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "module": extra.get("module", record["name"]),
        "layer": extra.get("layer", "system"),
        "project_id": extra.get("project_id"),
        "task_id": extra.get("task_id"),
        "event_type": extra.get("event_type"),
        "message": record["message"],
    }
    # 移除 None 值（减少噪音）
    payload = {k: v for k, v in payload.items() if v is not None}
    raw = json.dumps(payload, ensure_ascii=False)
    # 转义花括号：{ → {{，} → }}，使 loguru format_map 不把 JSON key 当模板变量
    return raw.replace("{", "{{").replace("}", "}}") + "\n"


# --------------------------------------------------------------------------- #
# 初始化：只初始化一次
# --------------------------------------------------------------------------- #

_initialized = False


def _init_logging() -> None:
    """初始化 loguru sinks（只执行一次）。"""
    global _initialized
    if _initialized:
        return

    cfg = get_config()
    log_cfg = cfg.logging

    # 移除 loguru 默认 sink
    _loguru_logger.remove()

    # 1. stdout sink（开发可见）
    # 使用 callable formatter 而非字符串 format，避免 {extra[layer]} 在 layer 未绑定时抛出 KeyError
    def _stdout_formatter(record: dict) -> str:
        extra = record.get("extra", {})
        layer = extra.get("layer", "?")       # 防御性：未绑定时显示 ?
        module = extra.get("module", record["name"])
        time_str = record["time"].strftime("%Y-%m-%d %H:%M:%S")
        level_str = record["level"].name.ljust(8)
        # 与 _json_formatter 一致：转义消息中的 { }，防止 loguru format_map 误解
        msg = record["message"].replace("{", "{{").replace("}", "}}")
        return (
            f"{time_str} | {level_str} | {layer} | {module} - "
            f"{msg}\n"
        )

    _loguru_logger.add(
        sys.stdout,
        level=log_cfg.level,
        colorize=False,          # callable formatter 不支持 colorize=True
        format=_stdout_formatter,
        filter=lambda r: True,
    )

    # 2. 每个层级各一个 JSON 文件 sink（放在 logs/YYYYMMDD_HHMMSS/{layer}.log）
    run_dir = _get_run_dir()
    for layer in ("system", "agent", "tool", "project"):
        log_file = run_dir / f"{layer}.log"
        _loguru_logger.add(
            str(log_file),
            level=log_cfg.level,
            rotation=log_cfg.rotation,
            retention=log_cfg.retention,
            encoding="utf-8",
            format=_json_formatter,      # 输出结构化 JSON
            serialize=False,
            filter=lambda r, _layer=layer: r["extra"].get("layer") == _layer,
        )

    _initialized = True


# --------------------------------------------------------------------------- #
# 公共 API
# --------------------------------------------------------------------------- #

class _LayerLogger:
    """绑定了 layer/module 的 logger 包装器。"""

    def __init__(self, bound_logger: Any) -> None:
        self._log = bound_logger

    def _bind(self, event_type: Optional[str], extra: dict) -> Any:
        """将 event_type 和其他 extra 合并后 bind 到 loguru logger。

        event_type 是文档要求的核心字段，必须显式 bind 才能进入 JSON 日志。
        """
        ctx = {**extra}
        if event_type is not None:
            ctx["event_type"] = event_type
        return self._log.bind(**ctx)

    def info(self, message: str, *, event_type: Optional[str] = None, **extra: Any) -> None:
        self._bind(event_type, extra).info(message)

    def debug(self, message: str, *, event_type: Optional[str] = None, **extra: Any) -> None:
        self._bind(event_type, extra).debug(message)

    def warning(self, message: str, *, event_type: Optional[str] = None, **extra: Any) -> None:
        self._bind(event_type, extra).warning(message)

    def error(self, message: str, *, event_type: Optional[str] = None, **extra: Any) -> None:
        self._bind(event_type, extra).error(message)

    def exception(self, message: str, *, event_type: Optional[str] = None, **extra: Any) -> None:
        self._bind(event_type, extra).exception(message)


def get_logger(module: str, layer: str = "system") -> _LayerLogger:
    """获取绑定了 module 和 layer 的日志器。

    Args:
        module: 调用模块标识符，如 "bootstrap.services"、"api.health"。
        layer: 日志层级，可选 system | agent | tool | project。
    """
    _init_logging()
    bound = _loguru_logger.bind(layer=layer, module=module)
    return _LayerLogger(bound)


def get_project_logger(project_id: str, module: str) -> _LayerLogger:
    """获取绑定了 project_id 的项目级日志器（layer 固定为 project）。

    Args:
        project_id: 项目 ID。
        module: 调用模块标识符。
    """
    _init_logging()
    bound = _loguru_logger.bind(layer="project", module=module, project_id=project_id)
    return _LayerLogger(bound)


def get_agent_logger(agent_name: str, project_id: Optional[str] = None) -> _LayerLogger:
    """获取 Agent 专用日志器（layer 固定为 agent）。"""
    _init_logging()
    ctx: dict = {"layer": "agent", "module": f"agents.{agent_name}"}
    if project_id:
        ctx["project_id"] = project_id
    bound = _loguru_logger.bind(**ctx)
    return _LayerLogger(bound)


def get_tool_logger(tool_name: str, project_id: Optional[str] = None) -> _LayerLogger:
    """获取 Tool 专用日志器（layer 固定为 tool）。"""
    _init_logging()
    ctx: dict = {"layer": "tool", "module": f"tools.{tool_name}"}
    if project_id:
        ctx["project_id"] = project_id
    bound = _loguru_logger.bind(**ctx)
    return _LayerLogger(bound)
