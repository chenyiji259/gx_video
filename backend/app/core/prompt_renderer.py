"""Prompt Renderer — 变量渲染与校验。

将 PromptTemplate.body 中的 {{ variable }} 占位符替换为实际值。

用法：
    from app.core.prompt_registry import get_registry
    from app.core.prompt_renderer import PromptRenderer

    renderer = PromptRenderer(get_registry())
    text = renderer.render("director_system", {
        "project_stage": "shot_plan_ready",
        "available_tools": "...",
        "current_project_summary": "...",
    })
"""
from __future__ import annotations

import re
from typing import Any

from app.core.prompt_registry import PromptRegistry, PromptTemplate, get_registry


_VAR_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class MissingPromptVariableError(ValueError):
    """渲染时缺少必要变量。"""
    pass


class PromptRenderer:
    """基于 PromptRegistry 渲染 prompt 模板。"""

    def __init__(self, registry: PromptRegistry | None = None) -> None:
        self._registry = registry or get_registry()

    def render(
        self,
        name: str,
        variables: dict[str, Any],
        *,
        allow_extra: bool = True,
        strict: bool = True,
    ) -> str:
        """渲染指定名称的 prompt 模板。

        Args:
            name: prompt 模板名（frontmatter 中的 name 字段）。
            variables: 变量字典，key 为变量名，value 为替换内容。
            allow_extra: 是否允许传入模板未声明的变量（默认 True）。
            strict: True 时，模板声明的变量必须全部传入，否则抛出异常。

        Returns:
            渲染后的完整 prompt 字符串。

        Raises:
            KeyError: 模板名不存在。
            MissingPromptVariableError: strict=True 时，缺少必要变量。
        """
        tmpl = self._registry.get(name)
        return self._render_template(tmpl, variables, strict=strict)

    def render_template(
        self,
        tmpl: PromptTemplate,
        variables: dict[str, Any],
        *,
        strict: bool = True,
    ) -> str:
        """直接渲染一个 PromptTemplate 对象（无需按名称查找）。"""
        return self._render_template(tmpl, variables, strict=strict)

    def _render_template(
        self,
        tmpl: PromptTemplate,
        variables: dict[str, Any],
        *,
        strict: bool,
    ) -> str:
        # 检查必要变量是否齐全
        if strict and tmpl.variables:
            missing = [v for v in tmpl.variables if v not in variables]
            if missing:
                raise MissingPromptVariableError(
                    f"渲染 prompt '{tmpl.name}' 时缺少必要变量：{missing}\n"
                    f"已传入变量：{list(variables.keys())}\n"
                    f"模板要求变量：{tmpl.variables}\n"
                    f"模板来源：{tmpl.source_path}"
                )

        # 替换 {{ variable }} 占位符
        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            if var_name in variables:
                return str(variables[var_name])
            # 未传入的变量：保留原占位符（soft fallback）
            return match.group(0)

        return _VAR_PATTERN.sub(_replace, tmpl.body)

    def list_variables(self, name: str) -> list[str]:
        """返回指定模板的变量列表。"""
        return self._registry.get(name).variables.copy()
