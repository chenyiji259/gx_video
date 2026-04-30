"""ULID 生成器工具。

文档约束（doc 05 §3.1）：
  所有核心表主键统一使用 ULID（varchar(26)）：
  - 可排序（按时间戳单调递增）
  - 比 UUID 更适合时间序分页
  - 前后端传输方便（26 位无连字符大写字符串）

示例：
    from app.utils.ids import generate_ulid
    id_ = generate_ulid()  # "01ARYZ6S41TSV4RRFFQ69G5FAV"
"""
from ulid import ULID


def generate_ulid() -> str:
    """生成一个新的 ULID 字符串（26 个字符，大写字母 + 数字）。

    Returns:
        形如 "01ARYZ6S41TSV4RRFFQ69G5FAV" 的 26 位 ULID 字符串。
    """
    return str(ULID())
