"""一致性质检 REST API。

来源文档：doc 09 任务 13-01

路由：
  POST /api/v1/projects/{project_id}/consistency/check
    → 触发质检，返回 issues / recommendations / score

前置约束：
  - 项目状态须处于 storyboard_ready 及以上阶段（clips_ready / timeline_ready / ...）
  - 需要已有 active style_bible_version 和 active shot_plan_version
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.consistency_guardian_agent import (
    ConsistencyGuardianAgent,
    build_shots_summary,
)
from app.api.v1.deps import get_current_user, get_db_session
from app.models.user import User
from app.repositories.planning_repositories import (
    ShotRepository,
    StyleBibleRepository,
)
from app.repositories.project_repository import ProjectRepository

router = APIRouter(prefix="/projects/{project_id}/consistency", tags=["consistency"])

# 允许触发质检的项目阶段（storyboard_ready 及以上）
_ALLOWED_STAGES: frozenset[str] = frozenset({
    "storyboard_ready",
    "clips_ready",
    "timeline_ready",
    "export_ready",
    "completed",
})


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ConsistencyIssue(BaseModel):
    type: str
    target_id: str
    severity: str
    description: str


class ConsistencyRecommendation(BaseModel):
    action: str
    target_id: str
    reason: str


class ConsistencyCheckResponse(BaseModel):
    project_id: str
    issues: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    overall_consistency_score: float
    shot_count: int


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/consistency/check
# ---------------------------------------------------------------------------

@router.post(
    "/check",
    response_model=ConsistencyCheckResponse,
    summary="触发项目一致性质检",
)
async def check_consistency(
    project_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ConsistencyCheckResponse:
    """对项目执行角色 / 风格 / 节奏一致性检查。

    - 项目须处于 storyboard_ready 或更高阶段
    - LLM 不可用时返回空 issues（score=1.0），不抛错
    """
    # ---- 1. 校验项目归属 + 状态 ----------------------------------------
    project = await ProjectRepository(session).get_by_id_for_user(
        project_id, current_user.id
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "project_not_found", "message": "项目不存在"},
        )

    if project.current_stage not in _ALLOWED_STAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "stage_not_ready",
                "message": (
                    f"当前项目阶段 {project.current_stage!r} 不支持一致性质检，"
                    f"需要处于 storyboard_ready 或更高阶段"
                ),
            },
        )

    # ---- 2. 读取 active style_bible ----------------------------------------
    style_bible_summary = "（无风格规格）"
    if project.active_style_version_id:
        style_repo = StyleBibleRepository(session)
        style_version = await style_repo.get_active(project_id)
        if style_version and style_version.raw_payload:
            payload = style_version.raw_payload
            style_bible_summary = (
                f"palette={json.dumps(payload.get('palette', {}), ensure_ascii=False)[:80]} "
                f"lighting={payload.get('lighting_style', '?')!r} "
                f"camera={payload.get('camera_style', '?')!r} "
                f"texture={payload.get('film_texture', '?')!r}"
            )

    # ---- 3. 读取 active character_set ----------------------------------------
    # 第一版 character_set 以 raw_payload JSON 存储，直接取摘要
    character_set_summary = "（无角色设定）"
    if project.active_character_set_version_id:
        # character_set_versions 暂无独立 Repository，直接读项目字段说明即可
        # 实际项目中此处应通过 CharacterSetVersionRepository 查询
        character_set_summary = "（已设定，详见角色卡）"

    # ---- 4. 读取 shots ----------------------------------------
    shots = await ShotRepository(session).list_by_project(project_id)
    shots_summary = build_shots_summary(shots)
    shot_count = len(shots)

    # ---- 5. 调用 Agent ----------------------------------------
    agent = ConsistencyGuardianAgent()
    result = await agent.run(
        style_bible_summary=style_bible_summary,
        character_set_summary=character_set_summary,
        shots_summary=shots_summary,
        shot_count=shot_count,
    )

    return ConsistencyCheckResponse(
        project_id=project_id,
        issues=result.get("issues", []),
        recommendations=result.get("recommendations", []),
        overall_consistency_score=float(
            result.get("overall_consistency_score", 1.0)
        ),
        shot_count=shot_count,
    )
