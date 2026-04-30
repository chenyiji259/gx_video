"""叙事剧本 API（narrative）。

来源文档：doc11 §5.4 / doc09 批次1

接口：
  GET  /api/v1/projects/{project_id}/narrative/active
    返回当前激活的叙事剧本版本。

  POST /api/v1/projects/{project_id}/workflow/generate-narrative
    触发叙事剧本生成（REST 直接路径，绕过 LangGraph 图）。
    前置校验：confirm_brief 决策已 selected，否则返回 decision_required。

设计约束：
  与其他 workflow 接口一致，REST 路径也必须先校验对应前置决策，不能跳过确认。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.user import User
from app.repositories.decision_repository import DecisionRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.services.narrative_script_service import (
    NarrativeScriptError,
    NarrativeScriptService,
)
from app.repositories.visual_bible_repository import NarrativeScriptVersionRepository

router = APIRouter()


# ---------------------------------------------------------------------------
# 内部辅助：校验 confirm_brief 决策
# ---------------------------------------------------------------------------

async def _require_confirm_brief(project_id: str, req_id: str) -> None:
    """确保 confirm_brief 决策已 selected，否则抛 decision_required 错误。"""
    async with UnitOfWork() as uow:
        decisions = await DecisionRepository(uow.session).list_by_type(
            project_id, "confirm_brief", status="selected"
        )
    if not decisions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "decision_required",
                "message": "需要先通过 decisions API 完成 'confirm_brief' 决策，才能触发叙事剧本生成。",
                "decision_type": "confirm_brief",
            },
        )


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/narrative/active
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/narrative/active")
async def get_active_narrative(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回当前激活的叙事剧本版本。"""
    req_id = get_request_id(request)

    async with UnitOfWork() as uow:
        # 项目归属校验
        project = await ProjectRepository(uow.session).get_by_id_for_user(
            project_id, str(current_user.id)
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "项目不存在"},
            )

        narrative = await NarrativeScriptVersionRepository(uow.session).get_active(
            project_id
        )

    if narrative is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "暂无叙事剧本，请先生成"},
        )

    return ok(
        data={
            "id": narrative.id,
            "version_no": narrative.version_no,
            "story_arc": narrative.story_arc,
            "characters": narrative.characters,
            "scenes": narrative.scenes,
            "section_mapping": narrative.section_mapping,
            "raw_payload": narrative.raw_payload,
            "is_active": narrative.is_active,
            "created_at": narrative.created_at.isoformat() if narrative.created_at else None,
        },
        request_id=req_id,
    )


from app.tasks.dispatcher import task_dispatcher

# ---------------------------------------------------------------------------
# POST /projects/{project_id}/workflow/generate-narrative
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/workflow/generate-narrative")
async def trigger_generate_narrative(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """触发叙事剧本生成（REST 直接路径 — 偏差 2 异步化）。

    前置校验：confirm_brief 决策已 selected。
    """
    req_id = get_request_id(request)

    # 前置决策校验
    await _require_confirm_brief(project_id, req_id)

    try:
        async with UnitOfWork() as uow:
            job, is_new = await task_dispatcher.dispatch(
                uow.session,
                project_id=project_id,
                tool_name="generate_narrative",
                input_payload={"project_id": project_id, "user_id": str(current_user.id)},
            )
        if is_new:
            await task_dispatcher.push_to_queue(job.id)

        return ok(
            data={
                "job_id": job.id,
                "status": job.status,
                "message": "叙事剧本生成任务已提交，完成后将通过 SSE 推送结果并由导演自动汇报。",
            },
            request_id=req_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "narrative_dispatch_failed", "message": str(exc)},
        ) from exc
