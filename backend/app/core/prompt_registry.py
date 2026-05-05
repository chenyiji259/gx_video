"""Prompt Registry — 外部化提示词加载与索引。

工程约束（doc 08）：
  不允许在 Python 代码中硬编码 prompt 字符串。
  所有 prompt 模板存放于 prompts/ 目录，使用 YAML frontmatter 标注元信息。

文件格式示例（prompts/system/director.md）：
    ---
    name: director_system
    version: 1
    layer: system
    agent: director
    variables:
      - project_stage
      - available_tools
    ---

    你是 VidMuse 的导演 Agent...
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class PromptTemplate:
    """单个 prompt 模板的完整描述。"""
    name: str
    version: int
    layer: str                     # system | tasks | compiler | providers
    body: str                      # 去掉 frontmatter 后的模板正文
    variables: list[str] = field(default_factory=list)
    agent: Optional[str] = None    # 归属 Agent（可选）
    source_path: Optional[str] = None  # 来源文件路径（便于调试）


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_IGNORED_PROMPT_FILE_RE = re.compile(r"(?:^|[_\-])(backup|bak|draft|tmp)(?:[_\-.]|$)", re.IGNORECASE)


def _parse_prompt_file(path: Path) -> PromptTemplate:
    """解析单个 .md 文件，提取 frontmatter 和正文。"""
    content = path.read_text(encoding="utf-8")

    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError(
            f"Prompt 文件缺少 YAML frontmatter: {path}\n"
            "格式要求：文件开头必须有 ---...--- 包裹的 YAML 元信息块。"
        )

    meta = yaml.safe_load(match.group(1))
    body = content[match.end():].strip()

    name = meta.get("name")
    if not name:
        raise ValueError(f"Prompt 文件 frontmatter 缺少 'name' 字段: {path}")

    version_raw = meta.get("version", 1)
    try:
        version = int(version_raw)
    except (TypeError, ValueError):
        # 支持 "1.0" 、"2.0" 等字符串格式
        version = int(float(str(version_raw)))

    return PromptTemplate(
        name=name,
        version=version,
        layer=meta.get("layer", "unknown"),
        agent=meta.get("agent"),
        variables=meta.get("variables") or [],
        body=body,
        source_path=str(path),
    )


class PromptRegistry:
    """扫描 prompts/ 目录，建立 name → PromptTemplate 索引。

    用法：
        registry = PromptRegistry.load()
        tmpl = registry.get("director_system")
    """

    def __init__(self, templates: dict[str, PromptTemplate]) -> None:
        self._templates = templates

    @classmethod
    def load(cls, prompts_dir: Optional[Path] = None) -> "PromptRegistry":
        """从 prompts/ 目录递归加载所有 .md 文件。

        Args:
            prompts_dir: prompts 根目录路径。默认自动推断（项目根/prompts）。
        """
        if prompts_dir is None:
            # 相对于本文件推断：backend/app/core → 项目根 → prompts/
            prompts_dir = (
                Path(__file__).parent.parent.parent.parent / "prompts"
            )

        if not prompts_dir.exists():
            raise FileNotFoundError(
                f"Prompt 目录不存在: {prompts_dir}\n"
                "请确认项目根目录下有 prompts/ 目录。"
            )

        templates: dict[str, PromptTemplate] = {}
        for md_file in sorted(prompts_dir.rglob("*.md")):
            if _IGNORED_PROMPT_FILE_RE.search(md_file.stem):
                continue
            tmpl = _parse_prompt_file(md_file)
            if tmpl.name in templates:
                raise ValueError(
                    f"重复的 prompt name '{tmpl.name}'：\n"
                    f"  已存在: {templates[tmpl.name].source_path}\n"
                    f"  新发现: {tmpl.source_path}"
                )
            templates[tmpl.name] = tmpl

        return cls(templates)

    def get(self, name: str) -> PromptTemplate:
        """按名称获取模板，不存在时抛出明确异常。"""
        tmpl = self._templates.get(name)
        if tmpl is None:
            available = sorted(self._templates.keys())
            raise KeyError(
                f"Prompt 模板 '{name}' 不存在。\n"
                f"当前已加载的模板：{available}"
            )
        return tmpl

    def list_names(self) -> list[str]:
        """返回所有已加载模板的名称列表。"""
        return sorted(self._templates.keys())

    def list_by_layer(self, layer: str) -> list[PromptTemplate]:
        """按 layer 筛选模板列表。"""
        return [t for t in self._templates.values() if t.layer == layer]

    def __len__(self) -> int:
        return len(self._templates)

    def __repr__(self) -> str:
        return f"PromptRegistry({len(self._templates)} templates loaded)"


# 全局单例，懒加载
_registry: Optional[PromptRegistry] = None


def get_registry() -> PromptRegistry:
    """返回全局 PromptRegistry 单例。首次调用时扫描 prompts/ 目录。"""
    global _registry
    if _registry is None:
        _registry = PromptRegistry.load()
    return _registry
