"""Tool Call Bridge Service — 将少量确定性 next_action 输出为 OpenAI tool call 格式。

来源文档：doc 06 §22（Tool 协议）、doc 07 §7.2（右侧 Chat 选项卡/确认卡）

当前定位：兼容输出层（非流程桥接层）
  P6-01 后，文本主线任务（generate_brief / narrative / shot_plan）已由
  Director 通过 dispatch_agent_tool 直接完成，不再依赖此服务路由。
  此服务只保留 analyze_audio / complete_input / generate_brief 三个 schema，
  主要服务于前端需要展示 tool call 的少量入口场景。
  未在 schema 中注册的 next_action 将返回空列表，对业务无影响。

纯函数式，无数据库依赖，无副作用。
"""
from __future__ import annotations

import json
from typing import Optional

from app.utils.ids import generate_ulid


# ---------------------------------------------------------------------------
# Tool 定义（OpenAI function calling schema）
# ---------------------------------------------------------------------------

_TOOL_SCHEMAS: dict[str, dict] = {
    "analyze_audio": {
        "name": "analyze_audio",
        "description": "分析已上传的音频文件，提取 BPM、节拍、段落结构和歌词时间戳",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "目标项目 ID"
                }
            },
            "required": ["project_id"]
        }
    },
    "complete_input": {
        "name": "complete_input",
        "description": "确认项目输入规格已完整，将项目状态推进到 input_ready",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "目标项目 ID"
                }
            },
            "required": ["project_id"]
        }
    },
    "generate_brief": {
        "name": "generate_brief",
        "description": "基于音频分析结果和用户创意描述，生成创意方案（brief + style）",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "目标项目 ID"
                }
            },
            "required": ["project_id"]
        }
    },
}


# ---------------------------------------------------------------------------
# ToolCallBridgeService
# ---------------------------------------------------------------------------

class ToolCallBridgeService:
    """将 next_action 转换为 OpenAI tool call 格式。

    使用场景：
      chat_completions 收到 IntentResult 后，若 next_action 非空，
      调用 build_tool_calls() 生成 tool_calls 列表，
      附加在 message 中返回给前端。
    """

    def build_tool_calls(
        self,
        next_action: Optional[str],
        project_id: str,
    ) -> list[dict]:
        """将 next_action 转换为 OpenAI tool call 对象列表。

        Args:
            next_action: 内部动作标识（来自 IntentResult.next_action）。
            project_id:  操作目标项目 ID。

        Returns:
            tool call 对象列表（格式符合 OpenAI function calling 规范）。
            空列表表示当前轮无可执行动作。
        """
        if not next_action or next_action not in _TOOL_SCHEMAS:
            return []

        schema = _TOOL_SCHEMAS[next_action]
        tool_call = {
            "id": f"call_{generate_ulid()}",
            "type": "function",
            "function": {
                "name": schema["name"],
                "arguments": json.dumps({"project_id": project_id}),
            },
        }
        return [tool_call]

    def get_tool_schema(self, action_name: str) -> Optional[dict]:
        """返回指定动作的 OpenAI function schema（用于 /v1/chat/completions 的 tools 字段）。"""
        return _TOOL_SCHEMAS.get(action_name)

    def list_available_tools(self) -> list[dict]:
        """返回所有已注册工具的 function schema 列表（供前端初始化 tool 注册使用）。"""
        return [
            {"type": "function", "function": schema}
            for schema in _TOOL_SCHEMAS.values()
        ]
