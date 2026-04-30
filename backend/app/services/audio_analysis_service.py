"""AudioAnalysis Service — 音频分析版本管理（librosa beat_track + Qwen3.5 Omni 并发模式）。

来源文档：doc 09 §12 任务 8-03

职责：
  1. 读取 active ProjectSpec → 获取 audio_asset_id / start_sec / end_sec
  2. 调用 audio_trim_tool 裁切音频（落库 + MinIO）
  3. 并发执行 librosa beat_track（精确节拍）+ Qwen3.5 Omni（语义分析）
  4. 保存 AudioAnalysisVersion → 激活 → 更新 projects.active_audio_analysis_version_id
  5. 写本地 JSON 快照到 02_audio_analysis/
  6. 调用 StateTransitionService 推进项目到 audio_analyzed
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_project_logger
from app.storage.minio_adapter import get_storage
from app.domain.states import ProjectStage
from app.models.audio_analysis import AudioAnalysisVersion
from app.repositories.audio_analysis_repository import AudioAnalysisRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.project_spec_repository import ProjectSpecRepository
from app.repositories.unit_of_work import UnitOfWork
from app.services.state_transition_service import state_transition_service
from app.agents.audio_analysis_agent import AudioAnalysisAgent
from app.tools.audio_analysis_tool import analyze as _beat_analyze
from app.tools.audio_trim_tool import trim_audio
from app.tools.shared.artifact_tools import write_artifact
from app.services.concurrency_guard_service import ConcurrencyError, concurrency_guard


class AudioAnalysisError(Exception):
    """音频分析服务异常。"""

    def __init__(self, message: str, code: str = "analysis_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AudioAnalysisService:
    """音频分析版本服务。"""

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #

    async def run_and_save(
        self,
        project_id: str,
        user_id: str,
        *,
        providers: Optional[dict[str, str]] = None,
    ) -> AudioAnalysisVersion:
        """执行完整音频分析流程并落库。

        Args:
            project_id:  目标项目 ID。
            user_id:     当前用户 ID（项目归属校验）。
            providers:   分析路径配置（预留，当前无效，扩展阶段 1 使用）。

        Returns:
            新建并激活的 AudioAnalysisVersion 对象。

        Raises:
            AudioAnalysisError: 项目/规格缺失、状态非法、分析失败。
        """
        logger = get_project_logger(project_id, module="services.audio_analysis")

        # BUG-03 修复：防止同一项目并发触发两次音频分析。
        # 16-03：150s →2700s（覆盖 Omni 3 次重试 × 900s = 2700s）
        try:
            async with concurrency_guard.project_lock(project_id, timeout_sec=2700):
                return await self._run_locked(project_id, user_id, providers=providers)
        except ConcurrencyError as exc:
            raise AudioAnalysisError(str(exc), code="concurrency_conflict") from exc

    async def _run_locked(
        self,
        project_id: str,
        user_id: str,
        *,
        providers: Optional[dict[str, str]] = None,
    ) -> "AudioAnalysisVersion":
        """加锁后的实际执行体（由 run_and_save 调用）。"""
        logger = get_project_logger(project_id, module="services.audio_analysis")

        # ---- 步骤 1: 读取项目 + ProjectSpec --------------------------------
        async with UnitOfWork() as uow:
            project = await ProjectRepository(uow.session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise AudioAnalysisError("项目不存在", code="project_not_found")

            allowed = {"input_ready", "audio_analyzed"}
            if project.current_stage not in allowed:
                raise AudioAnalysisError(
                    f"项目阶段 {project.current_stage!r} 不允许音频分析",
                    code="invalid_stage",
                )

            spec = await ProjectSpecRepository(uow.session).get_active(project_id)
            if spec is None or spec.audio_asset_id is None:
                raise AudioAnalysisError(
                    "未找到 active ProjectSpec 或缺少 audio_asset_id",
                    code="no_spec",
                )

            audio_asset_id: str = spec.audio_asset_id
            start_sec: float = float(spec.audio_start_sec or 0.0)
            end_sec: float = float(spec.audio_end_sec or 0.0)
            user_prompt: str = spec.user_prompt or ""

            # ---- 步骤 2: 音频裁切 ----------------------------------------
            logger.info("开始音频裁切", event_type="trim_start")
            trimmed_asset = await trim_audio(
                project_id=project_id,
                audio_asset_id=audio_asset_id,
                start_sec=start_sec,
                end_sec=end_sec,
                session=uow.session,
            )
            # trimmed_asset 已 flush，trimmed_asset.id 可用
            trimmed_asset_id: str = trimmed_asset.id
            trimmed_bucket: str = trimmed_asset.bucket_name
            trimmed_key: str = trimmed_asset.object_key
            # 16-03：UoW 内提前提取 storage_uri（commit 后 ORM 对象 detached，直接访问可能触发 DetachedInstanceError）
            trimmed_storage_uri: str = trimmed_asset.storage_uri or ""
            # commit trim 事务
        # UoW 退出时自动 commit

        # ---- 步骤 3: librosa beat_track + Omni 并发分析（无 DB session）---
        storage = get_storage()

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "trimmed.wav")
            # BUG-01 修复：download_file 是同步方法且参数顺序错误（bucket 传给了 key位置）。
            # 改用 async_download_bytes(key, bucket=bucket)。
            _audio_bytes = await storage.async_download_bytes(trimmed_key, bucket=trimmed_bucket)
            with open(audio_path, "wb") as _f:
                _f.write(_audio_bytes)

            logger.info("开始并发分析: librosa beat_track + Omni", event_type="concurrent_analysis_start")
            agent = AudioAnalysisAgent()
            beat_result, omni_result = await asyncio.gather(
                asyncio.to_thread(_beat_analyze, audio_path),
                # 16-03：Omni 改为 URL 传输；MinIO 不可公网时自动降级 base64
                # tempfile 下载块保留，librosa 仍需要本地文件 audio_path
                agent.run_with_omni(
                    trimmed_storage_uri,  # 16-03: UoW 内提前提取的 storage_uri
                    audio_file_path=audio_path,
                ),
            )

        logger.info(
            f"并发分析完成: bpm={beat_result.get('bpm')} omni_keys={list(omni_result.keys())}",
            event_type="concurrent_analysis_done",
        )

        # ---- 步骤 4+5+6: 落库 + 激活 + 快照 + 状态推进 ------------------
        async with UnitOfWork() as uow2:
            version = await self._persist(
                session=uow2.session,
                project_id=project_id,
                trimmed_asset_id=trimmed_asset_id,
                beat_result=beat_result,
                omni_result=omni_result,
                user_prompt=user_prompt,
            )

        logger.info(
            f"音频分析完成: version={version.id!r} bpm={beat_result.get('bpm')} "
            f"sections={len(omni_result.get('music_structure_summary', {}).get('sections', []))}",
            event_type="audio_analysis_done",
        )
        return version

    # ------------------------------------------------------------------ #
    # 落库核心（单 UoW 事务）
    # ------------------------------------------------------------------ #

    async def _persist(
        self,
        *,
        session: AsyncSession,
        project_id: str,
        trimmed_asset_id: str,
        beat_result: dict[str, Any],
        omni_result: dict[str, Any],
        user_prompt: str,
    ) -> AudioAnalysisVersion:
        """落库 + 激活 + 写本地快照 + 推进状态（单事务内完成）。"""
        aa_repo = AudioAnalysisRepository(session)
        proj_repo = ProjectRepository(session)

        project = await proj_repo.get_by_id(project_id)
        version_no = await aa_repo.get_next_version_no(project_id)

        # 失活旧版本
        await aa_repo.deactivate_all(project_id)

        raw_payload: dict[str, Any] = {
            "signal": beat_result,
            "omni": omni_result,
            "user_prompt": user_prompt,
        }

        overall_analysis = omni_result.get("overall_analysis", {}) or {}
        structure_segments = omni_result.get("structure_segments", []) or []
        if structure_segments:
            # 统一转换为前端期待的 {start, end, label} 格式
            # structure_segments 的原始 key 是 {start_time, end_time, type, ...}
            section_map = [
                {
                    "start": seg.get("start_time") if seg.get("start_time") is not None else seg.get("start", 0),
                    "end": seg.get("end_time") if seg.get("end_time") is not None else seg.get("end", 0),
                    "label": seg.get("type") or seg.get("label") or seg.get("segment_id") or "",
                }
                for seg in structure_segments
            ]
        else:
            section_map = (
                omni_result.get("music_structure_summary", {}).get("sections", []) or []
            )

        version = AudioAnalysisVersion(
            project_id=project_id,
            version_no=version_no,
            audio_asset_id=trimmed_asset_id,
            bpm=beat_result.get("bpm"),
            beat_map=beat_result.get("beat_map", []),
            section_map=section_map,
            energy_curve=[],
            lyrics_alignment=omni_result.get("lyrics", {}).get("lines", []),
            raw_payload=raw_payload,
            quality_summary=omni_result,
            chord_progression=omni_result.get("chord_progression", []),
            instrumentation=omni_result.get("instrumentation", []),
            five_second_analysis=omni_result.get("five_second_analysis", []),
            key_scale=omni_result.get("music_structure_summary", {}).get("key_scale"),
            time_signature=omni_result.get("music_structure_summary", {}).get("time_signature"),
            style_caption=omni_result.get("style_caption") or None,
            genre=overall_analysis.get("genre") or None,
            emotional_curve_graph=overall_analysis.get("emotional_curve_graph", []) or [],
            analysis_provider={"beat_map": "librosa", "semantic": "qwen3.5_omni"},
            is_active=True,
        )
        await aa_repo.add(version)
        await session.flush()
        await session.refresh(version)

        # 更新项目 active 指针
        project.active_audio_analysis_version_id = version.id
        session.add(project)

        # 推进项目状态 → audio_analyzed
        # 仅当当前状态不是 audio_analyzed 时才推进（重新分析场景防止非法转换）
        if project.current_stage != ProjectStage.AUDIO_ANALYZED.value:
            await state_transition_service.advance_project(session, project, ProjectStage.AUDIO_ANALYZED)

        await write_artifact(
            raw_payload,
            project_id=project_id,
            artifact_type="audio_analysis",
            version_no=version_no,
            summary=f"BPM: {beat_result.get('bpm') or 0}",
        )

        return version

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #

    async def get_active_version(
        self, project_id: str
    ) -> Optional[AudioAnalysisVersion]:
        """获取当前激活的音频分析版本。"""
        async with UnitOfWork() as uow:
            return await AudioAnalysisRepository(uow.session).get_active(project_id)
