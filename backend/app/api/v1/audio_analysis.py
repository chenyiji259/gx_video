"""音频分析查询 API。

来源文档：doc 09 任务 9-05

接口：
  GET /api/v1/projects/{project_id}/audio-analysis/active
    返回当前激活的音频分析版本摘要（含 quality_summary）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.user import User
from app.repositories.asset_repository import AssetRepository
from app.repositories.audio_analysis_repository import AudioAnalysisRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.services.asset_access_service import build_asset_access_url

router = APIRouter()


@router.get("/projects/{project_id}/audio-analysis/active")
async def get_active_audio_analysis(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """返回项目当前激活的音频分析版本。

    前端工作台「音频分析」阶段页面通过此接口加载数据。
    """
    req_id = get_request_id(request)
    async with UnitOfWork() as uow:
        project = await ProjectRepository(uow.session).get_by_id_for_user(
            project_id, str(current_user.id)
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "not_found", "message": "项目不存在"},
            )

        aa = None
        audio_url: str | None = None
        if project.active_audio_analysis_version_id:
            aa = await AudioAnalysisRepository(uow.session).get_by_id(
                project.active_audio_analysis_version_id
            )
            # 同步拉取音频 asset URL，供前端播放器使用
            if aa and aa.audio_asset_id:
                audio_asset = await AssetRepository(uow.session).get_by_id(
                    aa.audio_asset_id
                )
                if audio_asset:
                    audio_url = await build_asset_access_url(audio_asset)

    if aa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "暂无音频分析结果"},
        )

    # 将 Omni 原始 omni_result 映射为前端期待的 quality_summary 结构
    qs: dict = aa.quality_summary or {}
    overall: dict = qs.get("overall_analysis", {}) or {}
    editing: dict = qs.get("editing_guidance", {}) or {}
    per_section: list = editing.get("per_section", []) or []
    normalized_quality_summary = {
        "music_summary": (
            qs.get("style_caption")
            or overall.get("mood", "")
            or ""
        ),
        "visual_suggestion": (
            (per_section[0].get("motion", "") if per_section else "")
            or overall.get("emotional_arc", "")
            or ""
        ),
        "music_structure_summary": qs.get("music_structure_summary"),
        "emotion_arc": qs.get("emotion_arc"),
        "editing_guidance": editing,
    }

    return ok(
        data={
            "id": aa.id,
            "version_no": aa.version_no,
            "bpm": float(aa.bpm) if aa.bpm else None,
            "duration_sec": aa.raw_payload.get("signal", {}).get("duration_sec") if aa.raw_payload else None,
            "beat_map": aa.beat_map,
            "section_map": aa.section_map,
            "energy_curve": aa.energy_curve,
            # Omni 输出 lyrics.lines 为 {start, end, text}，前端期待 {time, text}，统一在 API 层归一化
            "lyrics_alignment": [
                {
                    "time": line.get("start") if line.get("start") is not None else line.get("time", 0),
                    "text": line.get("text", ""),
                }
                for line in (aa.lyrics_alignment or [])
            ],
            "quality_summary": normalized_quality_summary,
            # 扩展字段（之前漏发，现补全）
            "chord_progression": aa.chord_progression,
            "instrumentation": aa.instrumentation,
            "five_second_analysis": aa.five_second_analysis,
            "key_scale": aa.key_scale,
            "genre": aa.genre,
            # 音频 URL（供前端播放器使用）
            "audio_url": audio_url,
            "is_active": aa.is_active,
            "created_at": aa.created_at.isoformat() if aa.created_at else None,
        },
        request_id=req_id,
    )
