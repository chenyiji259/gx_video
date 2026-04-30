"""Director 专属工具实现（批次C 新增）。

来源文档：doc12 §6.2.3（Director 专属工具设计）

工具说明：
  1. dispatch_agent_tool       — 派发任务给 Sub-Agent（NarrativeScriptAgent / VisualDevelopmentAgent 等）
  2. read_artifact_for_review  — 读取产物 JSON 内容供 Director 审核（非 @tool，直接异步调用）
  3. create_decision_tool      — 创建 PendingDecision（包装 DecisionService.create_decision）
  4. get_project_state_tool    — 读取当前 ProjectSnapshot
  5. estimate_cost_tool        — 估算高成本 ToolCall 的 credits 消耗

批次C 状态：骨架实现，@tool 装饰器包装已就位，供后续 Director
升级到 create_react_agent 时直接接入，无需修改工具签名。
Director 在 Mode B 中部分直接调用（非 ReAct 循环），主要为
DirectorReportService 服务。

设计约束：
  - 工具函数均为 async
  - 参数类型保持简单（str / int / float），兼容 LangChain tool schema
  - 失败时返回 {"error": "..."} 而不是抛出异常（让 LLM 感知失败并自行处理）
"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.core.logging import get_logger

_logger = get_logger("tools.director.director_tools", layer="tool")

_DIRECTOR_CONFIRM_ACTIONS: dict[str, tuple[str, str]] = {
    "request_style_decision": ("select_style_direction", "project"),
    "request_brief_confirmation": ("confirm_brief", "project"),
    "request_narrative_confirmation": ("confirm_narrative", "project"),
    "request_visual_bible_confirmation": ("confirm_visual_bible", "project"),
    "request_shot_plan_confirmation": ("confirm_shot_plan", "project"),
    "request_storyboard_confirmation": ("confirm_storyboard", "project"),
}


def _default_target_entity_type(decision_type: str) -> str:
    """根据 decision_type 推断 target_entity_type。"""
    if decision_type in {
        "confirm_brief",
        "confirm_narrative",
        "confirm_visual_bible",
        "confirm_shot_plan",
        "confirm_storyboard",
        "select_style_direction",
    }:
        return "project"
    return "project"


# ---------------------------------------------------------------------------
# 1. read_artifact_for_review — 非 @tool，直接调用（可被 DirectorReportService 使用）
# ---------------------------------------------------------------------------

async def read_artifact_for_review(artifact_ref: dict) -> str:
    """读取产物完整 JSON 内容，返回压缩的字符串摘要（最多 6000 字符）。

    DirectorReportService 在 Mode B 触发时调用此函数，将结果注入 Director prompt。
    返回截断后的 JSON 字符串。
    长度设为 6000 字符：足够容纳完整的叙事剧本或 shot plan，
    同时避免不必要的 prompt 超长。

    Args:
        artifact_ref: ArtifactRef dict（含 local_path / minio_uri 等）。

    Returns:
        产物内容的字符串表示（JSON，截取 6000 字符）；
        失败时返回包含 error 字段的 JSON 字符串。
    """
    from app.tools.shared.artifact_tools import read_artifact  # noqa: PLC0415

    artifact_id = artifact_ref.get("artifact_id", "unknown")
    try:
        from app.core.config import get_config  # noqa: PLC0415
        max_chars: int = get_config().workflow.artifact_review_max_chars
    except Exception:  # noqa: BLE001
        max_chars = 10000  # 配置读取失败时的安全默认值
    try:
        content = await read_artifact(artifact_ref)
        text = json.dumps(content, ensure_ascii=False)
        if len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        _logger.debug(
            f"read_artifact_for_review: {artifact_id!r} 读取成功，"
            f"原始长度={len(text)} max_chars={max_chars}",
            event_type="artifact_review_read_ok",
        )
        return text
    except Exception as exc:
        _logger.warning(
            f"read_artifact_for_review 失败: {artifact_id!r} exc={exc!r}",
            event_type="artifact_review_read_failed",
        )
        return json.dumps({"error": str(exc), "artifact_id": artifact_id})


# ---------------------------------------------------------------------------
# 上下文加载辅助（P6-01：供 dispatch_agent 直连 Sub-Agent 前调用）
# ---------------------------------------------------------------------------

async def _load_brief_dispatch_ctx(project_id: str, user_id: str) -> dict:
    """加载 generate_brief 所需的项目上下文（spec + audio_ref），不做 LLM 调用。"""
    from app.repositories.audio_analysis_repository import AudioAnalysisRepository  # noqa: PLC0415
    from app.repositories.planning_repositories import CreativeBriefRepository  # noqa: PLC0415
    from app.repositories.project_repository import ProjectRepository  # noqa: PLC0415
    from app.repositories.project_spec_repository import ProjectSpecRepository  # noqa: PLC0415
    from app.repositories.unit_of_work import UnitOfWork  # noqa: PLC0415
    from app.tools.shared.artifact_tools import build_ref_from_asset_latest  # noqa: PLC0415

    async with UnitOfWork() as uow:
        session = uow.session
        project = await ProjectRepository(session).get_by_id_for_user(project_id, user_id)
        if project is None:
            raise ValueError(f"项目 {project_id!r} 不存在或不属于当前用户")

        spec = await ProjectSpecRepository(session).get_active(project_id)
        user_prompt = spec.user_prompt or "" if spec else ""
        # 16-01 残留修复：与主流程保持一致，使用实际音频时长而非固定 30s
        target_duration_sec: float = 0.0
        aspect_ratio = "16:9"
        if spec:
            dur = float((spec.audio_end_sec or 0) - (spec.audio_start_sec or 0))
            if dur > 0:
                target_duration_sec = dur
            if isinstance(spec.output_config, dict):
                aspect_ratio = spec.output_config.get("aspect_ratio", "16:9")

        audio_ref = None
        if project.active_audio_analysis_version_id:
            aa = await AudioAnalysisRepository(session).get_by_id(
                project.active_audio_analysis_version_id
            )
            if aa:
                audio_ref = await build_ref_from_asset_latest(
                    project_id, artifact_type="audio_analysis",
                    version_no=aa.version_no, prefix="audio_analysis",
                    summary=f"BPM: {aa.bpm}" if aa.bpm else "audio_analysis",
                )

        version_no = await CreativeBriefRepository(session).get_next_version_no(project_id)

    return {
        "user_prompt": user_prompt,
        "target_duration_sec": target_duration_sec,
        "aspect_ratio": aspect_ratio,
        "audio_ref": audio_ref,
        "version_no": version_no,
    }



# ---------------------------------------------------------------------------
# dispatch_agent — 直连 Sub-Agent 的主入口
# ---------------------------------------------------------------------------

async def dispatch_agent(agent_name: str, task_spec: dict[str, Any]) -> dict[str, Any]:
    from app.tools.shared.artifact_tools import build_ref_from_asset_latest, read_artifact  # noqa: PLC0415
    from app.services.visual_bible_service import VisualBibleService  # noqa: PLC0415

    project_id = task_spec.get("project_id", "")
    user_id = task_spec.get("user_id", "")
    task_type = task_spec.get("task_type", "")

    if not project_id or not user_id:
        return {"error": "dispatch_agent 缺少 project_id 或 user_id"}

    # ------------------------------------------------------------------ #
    # generate_brief — P6-01: 直连 CreativePlanningAgent.run_phase1()
    # ------------------------------------------------------------------ #
    if agent_name == "creative_planning_agent" and task_type == "generate_brief":
        from app.agents.creative_planning_agent import CreativePlanningAgent  # noqa: PLC0415
        from app.services.brief_persistence_service import BriefPersistenceService  # noqa: PLC0415

        try:
            ctx = await _load_brief_dispatch_ctx(project_id, user_id)
        except ValueError as exc:
            return {"error": str(exc)}

        style_direction = task_spec.get("style_direction", "通用风格")
        phase1_result = await CreativePlanningAgent().run_phase1({
            "project_id": project_id,
            "audio_ref": ctx["audio_ref"],
            "style_direction": style_direction,
            "user_prompt": ctx["user_prompt"],
            "target_duration_sec": ctx["target_duration_sec"],
            "aspect_ratio": ctx["aspect_ratio"],
            "version_no": ctx["version_no"],
        })

        brief_ref = phase1_result.get("brief_ref") or {}
        style_ref = phase1_result.get("style_ref") or {}
        try:
            brief_data = await read_artifact(brief_ref) if brief_ref.get("artifact_id") else {}
        except Exception:  # noqa: BLE001
            brief_data = {}
        try:
            style_data = await read_artifact(style_ref) if style_ref.get("artifact_id") else {}
        except Exception:  # noqa: BLE001
            style_data = {}

        brief_version, style_version = await BriefPersistenceService().save_from_data(
            project_id=project_id,
            brief_data=brief_data,
            style_data=style_data,
            style_direction=style_direction,
        )
        _logger.info(
            f"dispatch_agent generate_brief 完成: "
            f"brief_v{brief_version.version_no} style_v{style_version.version_no}",
            event_type="dispatch_brief_done",
        )
        return {
            "task_type": task_type,
            "artifact_ref": brief_ref,
            "brief_ref": brief_ref,
            "style_ref": style_ref,
            "brief_version_no": brief_version.version_no,
            "style_version_no": style_version.version_no,
        }

    # ------------------------------------------------------------------ #
    # generate_narrative — 偏差 2: 改为异步分发（Worker 模式）
    # ------------------------------------------------------------------ #
    if agent_name == "narrative_agent" and task_type == "generate_narrative":
        from app.tasks.dispatcher import task_dispatcher  # noqa: PLC0415
        from app.repositories.unit_of_work import UnitOfWork  # noqa: PLC0415

        try:
            async with UnitOfWork() as uow:
                job, is_new = await task_dispatcher.dispatch(
                    uow.session,
                    project_id=project_id,
                    tool_name="generate_narrative",
                    input_payload={"project_id": project_id, "user_id": user_id},
                )
            if is_new:
                await task_dispatcher.push_to_queue(job.id)

            _logger.info(
                f"dispatch_agent generate_narrative 已分发到异步任务: job_id={job.id!r}",
                event_type="dispatch_narrative_async",
            )
            return {
                "task_type": task_type,
                "job_id": job.id,
                "status": "submitted",
                "message": "叙事剧本生成任务已提交。完成后导演将自动汇报，请稍候。",
            }
        except Exception as exc:
            _logger.error(
                f"dispatch_agent generate_narrative 分发失败: {exc!r}",
                event_type="dispatch_narrative_async_error",
            )
            return {"error": f"异步任务分发失败: {exc}"}

    # ------------------------------------------------------------------ #
    # generate_shot_plan — 新流程：直接由 narrative_script 派生，不再走 phase-2 LLM
    # ------------------------------------------------------------------ #
    if agent_name == "creative_planning_agent" and task_type == "generate_shot_plan":
        from app.services.shot_plan_persistence_service import ShotPlanPersistenceService  # noqa: PLC0415

        scene_version, shot_version, shots = await ShotPlanPersistenceService().derive_from_narrative(
            project_id=project_id,
            user_id=user_id,
        )
        _logger.info(
            f"dispatch_agent generate_shot_plan 完成: {len(shots)} shots v{shot_version.version_no}",
            event_type="dispatch_shot_plan_done",
        )
        artifact_ref = await build_ref_from_asset_latest(
            project_id, artifact_type="shot_plan",
            version_no=shot_version.version_no, prefix="shot_plan",
            summary=f"{len(shots)} 个镜头",
        )
        return {
            "task_type": task_type,
            "artifact_ref": artifact_ref,
            "shot_plan_ref": artifact_ref,
            "scene_count": len(scene_version.raw_payload.get("scenes") or []) if scene_version.raw_payload else 0,
            "shot_count": len(shots),
            "scene_version_no": scene_version.version_no,
            "shot_plan_version_no": shot_version.version_no,
        }

    if agent_name == "visual_dev_agent" and task_type == "generate_character_ref":
        asset_id = await VisualBibleService().generate_character_reference(
            project_id=project_id,
            user_id=user_id,
            character_id=task_spec.get("character_id", ""),
            generation_mode=task_spec.get("generation_mode"),
            source_image_url=task_spec.get("source_image_url") or None,
            provider_name=task_spec.get("provider_name") or None,
        )
        return {"task_type": task_type, "asset_id": asset_id}

    if agent_name == "visual_dev_agent" and task_type == "generate_scene_ref":
        asset_id = await VisualBibleService().generate_scene_reference(
            project_id=project_id,
            user_id=user_id,
            scene_id=task_spec.get("scene_id", ""),
            provider_name=task_spec.get("provider_name") or None,
        )
        return {"task_type": task_type, "asset_id": asset_id}

    return {
        "error": (
            f"不支持的 dispatch 组合: agent_name={agent_name!r}, "
            f"task_type={task_type!r}"
        )
    }


async def create_decision(
    *,
    project_id: str,
    decision_type: str,
    context_summary: str,
    session_id: str,
    options: list[dict] | None = None,
    target_entity_type: str = "",
    target_entity_id: str = "",
    default_option_id: str = "",
) -> dict[str, Any]:
    from app.services.decision_service import DecisionService  # noqa: PLC0415

    resolved_target_entity_type = target_entity_type or _default_target_entity_type(decision_type)
    svc = DecisionService()

    if await svc.has_open_decision_of_type(project_id, decision_type):
        open_list = await svc.get_pending_decisions(project_id)
        existing = next(
            (d for d in open_list if d.get("decision_type") == decision_type),
            None,
        )
        if existing:
            return {
                "decision_id": existing["id"],
                "status": "open",
                "session_id": session_id,
                "target_entity_type": resolved_target_entity_type,
                "context_summary": context_summary,
                "reused": True,
            }

    decision = await svc.create_decision(
        project_id=project_id,
        session_id=session_id,
        decision_type=decision_type,
        target_entity_type=resolved_target_entity_type,
        options_payload=options or [],
        target_entity_id=target_entity_id or None,
        default_option_id=default_option_id or None,
    )
    return {
        "decision_id": decision["id"],
        "status": "open",
        "session_id": session_id,
        "target_entity_type": resolved_target_entity_type,
        "context_summary": context_summary,
        "reused": False,
    }


async def create_decision_for_action(
    *,
    project_id: str,
    session_id: str,
    next_action: str,
    context_summary: str,
    options: list[dict] | None = None,
) -> dict[str, Any]:
    mapping = _DIRECTOR_CONFIRM_ACTIONS.get(next_action)
    if mapping is None:
        return {"error": f"不支持的确认动作: {next_action!r}"}
    decision_type, target_entity_type = mapping
    return await create_decision(
        project_id=project_id,
        session_id=session_id,
        decision_type=decision_type,
        target_entity_type=target_entity_type,
        context_summary=context_summary,
        options=options or [],
    )


# ---------------------------------------------------------------------------
# @tool 包装（供后续 create_react_agent 接入）
# ---------------------------------------------------------------------------

try:
    from langchain_core.tools import tool as _lc_tool

    # ── 2. dispatch_agent_tool ──────────────────────────────────────────

    @_lc_tool
    async def dispatch_agent_tool(agent_name: str, task_spec_json: str) -> str:
        """Dispatch a task to a named Sub-Agent and wait for ArtifactRef result.

        Args:
            agent_name:     Sub-agent name. One of:
                            narrative_agent / creative_planning_agent /
                            visual_dev_agent.
            task_spec_json: Task specification as a JSON string.
                            Must include project_id and input ArtifactRefs.

        Returns JSON string: ArtifactRef on success, {"error": "..."} on failure.
        """
        try:
            task_spec = json.loads(task_spec_json)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"task_spec_json 解析失败: {exc}"})

        try:
            result = await dispatch_agent(agent_name, task_spec)
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                f"dispatch_agent_tool 失败: agent={agent_name!r} exc={exc!r}",
                event_type="dispatch_agent_tool_failed",
            )
            return json.dumps({"error": str(exc)})

    # ── 3. create_decision_tool ─────────────────────────────────────────

    @_lc_tool
    async def create_decision_tool(
        project_id: str,
        decision_type: str,
        context_summary: str,
        options_json: str = "[]",
        session_id: str = "",
        target_entity_type: str = "",
        target_entity_id: str = "",
        default_option_id: str = "",
    ) -> str:
        """Create a PendingDecision and return the decision_id.

        Args:
            project_id:       Project ID.
            decision_type:    Decision type string (e.g. confirm_narrative).
            context_summary:  Brief context to show to the user.
            options_json:     Options as a JSON array (empty for confirm-only).
            session_id:       Conversation session ID. Empty means auto-resolve.
            target_entity_type: Entity type for the decision. Empty means infer.
            target_entity_id: Optional target entity ID.
            default_option_id: Optional default option ID.

        Returns JSON string: {"decision_id": "...", "status": "open"}.
        """
        try:
            options = json.loads(options_json) if options_json else []
        except json.JSONDecodeError:
            options = []

        try:
            from app.services.conversation_service import ConversationService  # noqa: PLC0415
            from app.repositories.project_repository import ProjectRepository  # noqa: PLC0415
            from app.repositories.unit_of_work import UnitOfWork  # noqa: PLC0415

            resolved_session_id = session_id
            if not resolved_session_id:
                async with UnitOfWork() as uow:
                    project = await ProjectRepository(uow.session).get_by_id(project_id)
                    if project is None:
                        return json.dumps({"error": f"项目 {project_id!r} 不存在"})
                    user_id = project.user_id
                session = await ConversationService().get_or_create_session(
                    project_id=project_id,
                    user_id=user_id,
                )
                resolved_session_id = session["id"]

            result = await create_decision(
                project_id=project_id,
                session_id=resolved_session_id,
                decision_type=decision_type,
                target_entity_type=target_entity_type,
                target_entity_id=target_entity_id,
                default_option_id=default_option_id,
                context_summary=context_summary,
                options=options,
            )
            return json.dumps(
                result,
                ensure_ascii=False,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                f"create_decision_tool 失败: {exc!r}",
                event_type="create_decision_tool_failed",
            )
            return json.dumps({"error": str(exc)})

    # ── 4. get_project_state_tool ────────────────────────────────────────

    @_lc_tool
    async def get_project_state_tool(project_id: str, user_id: str) -> str:
        """Get the current ProjectSnapshot (stage + active versions + decisions).

        Returns JSON string of the snapshot, or {"error": "..."} on failure.
        """
        try:
            from app.repositories.project_repository import ProjectRepository  # noqa: PLC0415
            from app.repositories.unit_of_work import UnitOfWork  # noqa: PLC0415

            async with UnitOfWork() as uow:
                project = await ProjectRepository(uow.session).get_by_id_for_user(
                    project_id, user_id
                )

            if project is None:
                return json.dumps({"error": f"项目 {project_id!r} 不存在"})

            return json.dumps({
                "project_id": project.id,
                "current_stage": project.current_stage,
                "active_versions": {
                    "project_spec": project.active_project_spec_version_id,
                    "audio_analysis": project.active_audio_analysis_version_id,
                    "creative_brief": project.active_brief_version_id,
                    "style_bible": project.active_style_version_id,
                    "narrative_script": project.active_narrative_script_version_id,
                    "character_set": project.active_character_set_version_id,
                    "shot_plan": project.active_shot_plan_version_id,
                    "storyboard": project.active_storyboard_version_id,
                    "timeline": project.active_timeline_version_id,
                },
            }, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                f"get_project_state_tool 失败: {exc!r}",
                event_type="get_project_state_tool_failed",
            )
            return json.dumps({"error": str(exc)})

    # ── 5. estimate_cost_tool ────────────────────────────────────────────

    @_lc_tool
    async def estimate_cost_tool(project_id: str, action: str, params_json: str = "{}") -> str:
        """Estimate the credits cost of a high-cost action before dispatching.

        Args:
            project_id:  Project ID.
            action:      Action name (generate_clips / generate_lipsync_clip / export_video).
            params_json: Action parameters as JSON string.

        Returns JSON string: {"total_credits": N, "breakdown": [...], "action": "..."}.
        """
        try:
            params = json.loads(params_json) if params_json else {}
        except json.JSONDecodeError:
            params = {}

        try:
            from app.services.cost_estimation_service import CostEstimationService  # noqa: PLC0415
            svc = CostEstimationService()

            if action == "generate_clips":
                shot_count = params.get("shot_count", 0)
                avg_dur = params.get("avg_duration_sec", 5.0)
                total = svc.estimate_clips_batch(shot_count, avg_dur)
                return json.dumps({
                    "action": action,
                    "total_credits": total,
                    "breakdown": [{"item": f"{shot_count} 个视频片段", "credits": total}],
                })

            if action == "generate_lipsync_clip":
                shot_count = params.get("shot_count", 1)
                total = svc.estimate_lipsync(shot_count)
                return json.dumps({
                    "action": action,
                    "total_credits": total,
                    "breakdown": [{"item": f"{shot_count} 个口型片段", "credits": total}],
                })

            return json.dumps({
                "action": action,
                "total_credits": 0,
                "breakdown": [],
                "note": f"暂不支持对 {action!r} 的费用估算",
            })

        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                f"estimate_cost_tool 失败: {exc!r}",
                event_type="estimate_cost_tool_failed",
            )
            return json.dumps({"error": str(exc), "action": action})

    # ── 6. analyze_reference_image_tool ─────────────────────────────────

    @_lc_tool
    async def analyze_reference_image_tool(
        project_id: str,
        user_id: str,
        asset_id: str,
        character_id: str = "",
    ) -> str:
        """Analyze a reference image using Omni to determine its type and usability.

        Call this tool when a user uploads a reference image for a character,
        to check if it's suitable for MV production or needs transformation.
        When character_id is provided, the analysis result is automatically
        written back to the character record (image_analysis + base_face_asset_id).

        Args:
            project_id:   Project ID.
            user_id:      User ID.
            asset_id:     Asset ID of the uploaded reference image.
            character_id: Optional. When given, writes analysis result to the
                          corresponding character entry in CharacterSetVersion.

        Returns JSON string with image analysis result:
            {"image_type": "...", "usable_directly": bool, "recommended_mode": "...", ...}
        """
        try:
            from app.services.visual_bible_service import VisualBibleService  # noqa: PLC0415
            svc = VisualBibleService()
            result = await svc.analyze_reference_image(
                asset_id=asset_id,
                project_id=project_id,
                user_id=user_id,
                character_id=character_id or None,  # Bug4 修复：传递 character_id 使分析结果回写 DB
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                f"analyze_reference_image_tool 失败: {exc!r}",
                event_type="analyze_ref_image_tool_failed",
            )
            return json.dumps({"error": str(exc)})

    # ── 7. setup_costumes_tool ──────────────────────────────────────────

    @_lc_tool
    async def setup_costumes_tool(
        project_id: str,
        user_id: str,
        skip_image_analysis: str = "false",
    ) -> str:
        """Automatically analyze reference images, derive costumes from narrative, and generate costume references for all characters.

        Call this tool after the narrative script is confirmed and visual bible is initialized,
        to set up multiple costumes for each character based on the story sections.

        Args:
            project_id:          Project ID.
            user_id:             User ID.
            skip_image_analysis: "true" to skip reference image analysis, "false" (default) to analyze.

        Returns JSON string with setup results:
            {"characters": [...], "total_characters": N}
        """
        try:
            from app.services.visual_bible_service import VisualBibleService  # noqa: PLC0415
            svc = VisualBibleService()
            result = await svc.auto_analyze_and_setup_costumes(
                project_id=project_id,
                user_id=user_id,
                skip_image_analysis=(skip_image_analysis.lower() == "true"),
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                f"setup_costumes_tool 失败: {exc!r}",
                event_type="setup_costumes_tool_failed",
            )
            return json.dumps({"error": str(exc)})


except ImportError:
    # langchain_core 未安装时，@tool 工具不可用，但不阻断导入
    _logger.warning(
        "langchain_core 未安装，Director @tool 包装不可用",
        event_type="director_tool_import_failed",
    )

    async def dispatch_agent_tool(*args, **kwargs) -> str:  # type: ignore[misc]
        return json.dumps({"error": "langchain_core 未安装"})

    async def create_decision_tool(*args, **kwargs) -> str:  # type: ignore[misc]
        return json.dumps({"error": "langchain_core 未安装"})

    async def get_project_state_tool(*args, **kwargs) -> str:  # type: ignore[misc]
        return json.dumps({"error": "langchain_core 未安装"})

    async def estimate_cost_tool(*args, **kwargs) -> str:  # type: ignore[misc]
        return json.dumps({"error": "langchain_core 未安装"})

    async def analyze_reference_image_tool(*args, **kwargs) -> str:  # type: ignore[misc]
        return json.dumps({"error": "langchain_core 未安装"})  # type: ignore[misc]

    async def setup_costumes_tool(*args, **kwargs) -> str:  # type: ignore[misc]
        return json.dumps({"error": "langchain_core 未安装"})
