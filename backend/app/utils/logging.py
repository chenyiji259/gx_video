"""[已废弃] 请改用 app.core.logging 。

此模块为任务 0 的占位实现，已被 task 1-03 替代。
请改为：
    from app.core.logging import get_logger, get_project_logger
"""
from app.core.logging import get_logger, get_project_logger, get_agent_logger, get_tool_logger

__all__ = ["get_logger", "get_project_logger", "get_agent_logger", "get_tool_logger"]
