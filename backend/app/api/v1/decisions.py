"""决策 API — PendingDecision 查询与提交。

接口：
  GET   /projects/{project_id}/decisions                         — 查询 open 状态待决策
  GET   /projects/{project_id}/decisions/{decision_id}           — 查询单个决策（含结果）
  POST  /projects/{project_id}/decisions/{decision_id}/select    — 提交用户选择

文档约束（doc 09 任务 8-07）：
  - 所有接口需要 Bearer token（get_current_user）
  - project_id 路径参数做项目归属安全校验
  - 决策 ID 隔离：DecisionService 内部验证 project_id 归属
  - 提交后，前端应通过工作流触发 API（任务 9-05）继续推进 Pipeline
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.core.logging import get_logger
from app.models.user import User
from app.services.decision_service import DecisionError, DecisionService

router = APIRouter(prefix="/projects/{project_id}/decisions", tags=["decisions"])
_logger = get_logger("api.decisions", layer="system")


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class SubmitDecisionRequest(BaseModel):
    selected_option_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="用户选择的选项 ID（对应 options_payload 中某项的 id 字段）",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
async def list_pending_decisions(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """查询项目下所有 open 状态的待决策。

    前端工作台通过此接口轮询（或 SSE 推送后按需拉取）
    当前等待用户处理的风格选项、brief 确认、shot list 确认等决策。

    返回格式：
        {
          "success": true,
          "data": {
            "items": [{ "id": "...", "decision_type": "select_style_direction", ... }],
            "total": 1
          }
        }
    """
    req_id = get_request_id(request)
    decisions = await DecisionService().get_pending_decisions(project_id)
    return ok(
        data={"items": decisions, "total": len(decisions)},
        request_id=req_id,
    )


@router.get("/{decision_id}")
async def get_decision(
    project_id: str,
    decision_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """查询单个决策详情，包含用户选择结果（任意状态均可查询）。

    用于工作流触发 API 在唤醒图后查询用户选择了什么。
    """
    req_id = get_request_id(request)
    decision = await DecisionService().get_decision(project_id, decision_id)
    if decision is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "success": False,
                "error": {"code": "not_found", "message": "Decision not found"},
                "request_id": req_id,
            },
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ok(data=decision, request_id=req_id),
    )


@router.post("/{decision_id}/select")
async def select_decision(
    project_id: str,
    decision_id: str,
    body: SubmitDecisionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """提交用户选择，将决策状态更新为 selected。

    提交后：
    1. 决策 status 变为 'selected'，selected_option_id 记录用户选择
    2. 前端应调用工作流触发 API（doc 09 任务 9-05）继续推进 Pipeline
       (例如 POST /workflow/generate-brief)

    错误码：
      not_found        — 决策不存在或不属于该项目
      invalid_status   — 决策状态不为 open（已提交或已过期）
      invalid_option   — 选项 ID 不在 options_payload 中
    """
    req_id = get_request_id(request)
    try:
        decision = await DecisionService().submit_decision(
            project_id=project_id,
            decision_id=decision_id,
            selected_option_id=body.selected_option_id,
        )
    except DecisionError as e:
        http_status = (
            status.HTTP_404_NOT_FOUND
            if e.code == "not_found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return JSONResponse(
            status_code=http_status,
            content={
                "success": False,
                "error": {"code": e.code, "message": e.message},
                "request_id": req_id,
            },
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ok(data=decision, request_id=req_id),
    )
