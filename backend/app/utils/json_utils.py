"""JSON 解析工具（DESIGN-05 修复）。

将原先散落在 visual_bible_service / prompt_compiler_service /
visual_development_agent 中各自独立的三层 JSON 安全解析逻辑统一收口。

用法：
    from app.utils.json_utils import safe_parse_json

    result = safe_parse_json(llm_output)          # 失败返回 {}
    result = safe_parse_json(llm_output, fallback=[])  # 失败返回 []
"""
from __future__ import annotations

import json
import re
from typing import Any


def safe_parse_json(text: str, *, fallback: Any = None) -> Any:
    """三层安全解析 LLM 输出中的 JSON 内容。

    解析顺序：
      1. 直接 json.loads()
      2. 提取 Markdown 代码块（```json ... ``` 或 ``` ... ```）内的 JSON
      3. 提取文本中第一个 {...} 或 [...] 裸块

    Args:
        text:     LLM 原始输出字符串。
        fallback: 三层均失败时的返回值，默认 {}（空字典）。

    Returns:
        解析成功的 Python 对象；全部失败时返回 fallback。
    """
    if fallback is None:
        fallback = {}

    cleaned = text.strip()

    # 层 1：直接解析
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass

    # 层 2：Markdown 代码块提取
    md_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", cleaned, re.IGNORECASE)
    if md_match:
        try:
            return json.loads(md_match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # 层 3：裸大括号 / 方括号块提取
    brace_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", cleaned)
    if brace_match:
        try:
            return json.loads(brace_match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    return fallback
