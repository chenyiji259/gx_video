"""LangGraph 主图（阶段感知版 v9）。

来源文档：doc 02 §11 / doc 09 任务 9-01/9-04/10-04/11-05/11-07 / doc12 P6-02

节点链路：
  START
    → load_project_snapshot（加载 ProjectSnapshot + ArtifactRef + decisions）
    → [_route_after_snapshot 阶段预路由]
        input_ready     → audio_analysis_node   → respond_to_user
        其他阶段     → director_intake
    → [director_intake 内部处理]
        文本主线任务 (generate_brief/narrative/shot_plan):
          由 Director 工具调用直接完成 dispatch / review / decision
          直连 Sub-Agent 生成，不再走图内路由
    → [_route_after_director 阶段感知路由]
        request_style_decision          → human_confirmation_gate  → respond_to_user
        request_brief_confirmation      → human_confirmation_gate  → respond_to_user
        generate_storyboard             → storyboard_node          → respond_to_user
        request_storyboard_confirmation → human_confirmation_gate  → respond_to_user
        generate_clips                  → clip_node                → respond_to_user
        generate_timeline               → timeline_node            → respond_to_user
        其他                         → respond_to_user
    → respond_to_user
  END

Checkpoint：
  优先使用 PostgresSaver（生产态持久化）；依赖缺失时 fallback 到 MemorySaver。
  通过 session_id 作为 thread_id，保证同一会话内多轮对话的图状态连续。
"""
from __future__ import annotations

import atexit
from datetime import datetime, timezone
from typing import Optional

from langgraph.graph import END, START, StateGraph
try:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver as _AsyncPostgresSaver
except ImportError:  # langgraph-checkpoint-postgres 包未安装时 fallback
    _AsyncPostgresSaver = None  # type: ignore[assignment,misc]
from langgraph.checkpoint.memory import MemorySaver

from app.agents.director_agent import DirectorAgent
from app.core.config import get_config
from app.core.logging import get_logger
from app.repositories.asset_repository import AssetRepository
from app.repositories.audio_analysis_repository import AudioAnalysisRepository
from app.repositories.decision_repository import DecisionRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.repositories.visual_bible_repository import CharacterSetVersionRepository
from app.schemas.project import ActiveVersions, CharacterRef, ProjectSnapshot, SceneRef
from app.services.asset_access_service import build_asset_access_url, build_asset_access_url_map
from app.services.intent_resolution_service import IntentResolutionService
from app.tools.director.director_tools import create_decision_for_action
from app.tools.shared.artifact_tools import build_ref_from_asset_latest
from app.workflows.graph_state import ProjectGraphState
# 旧流程导入：已停用
# from app.workflows.nodes.audio_analysis_node import audio_analysis_node

_logger = get_logger("workflows.main_graph", layer="system")

_MODE_B_CONFIRM_ACTIONS: frozenset[str] = frozenset(
    {
        "request_brief_confirmation",
        "request_narrative_confirmation",
        "request_visual_bible_confirmation",
        "request_shot_plan_confirmation",
        "request_storyboard_confirmation",
    }
)

# ---------------------------------------------------------------------------
# Checkpointer 初始化（P6-04：优先 PostgresSaver，fallback MemorySaver）
# ---------------------------------------------------------------------------

async def _build_async_checkpointer():
    """异步初始化 checkpointer。

    优先使用 AsyncPostgresSaver（与 ainvoke 兼容的生产态持久化）。
    若包未安装或 DB_URL 未配置，fallback 到 MemorySaver。
    """
    global _checkpointer_context

    if _AsyncPostgresSaver is None:
        _logger.warning(
            "AsyncPostgresSaver 不可用（请安装 langgraph-checkpoint-postgres），"
            "回落到 MemorySaver",
            event_type="checkpointer_fallback_memory",
        )
        return MemorySaver()

    try:
        cfg = get_config()
        db_url: str = getattr(cfg, "database_url", None) or ""
        if not db_url:
            db_cfg = getattr(cfg, "database", None)
            if db_cfg:
                host = getattr(db_cfg, "host", "localhost")
                port = getattr(db_cfg, "port", 5432)
                user = getattr(db_cfg, "username", "postgres")
                password = getattr(db_cfg, "password", "")
                dbname = getattr(db_cfg, "database", "vidumuse")
                db_url = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

        if not db_url:
            _logger.warning(
                "database_url 未配置，回落到 MemorySaver",
                event_type="checkpointer_fallback_no_url",
            )
            return MemorySaver()

        context_manager = _AsyncPostgresSaver.from_conn_string(db_url)
        saver = await context_manager.__aenter__()
        _checkpointer_context = context_manager
        try:
            await saver.setup()
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                f"AsyncPostgresSaver.setup() 执行失败，继续使用: {exc!r}",
                event_type="checkpointer_setup_failed",
            )
        _logger.info(
            "Checkpointer: AsyncPostgresSaver 初始化成功",
            event_type="checkpointer_postgres_ok",
        )
        return saver
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            f"AsyncPostgresSaver 初始化失败，回落到 MemorySaver: {exc!r}",
            event_type="checkpointer_fallback_error",
        )
        return MemorySaver()


# 全局图单例（懒加载，首次调用 get_main_graph() 时初始化）
_graph: Optional[object] = None
_checkpointer: Optional[object] = None
_checkpointer_context: Optional[object] = None


def _close_checkpointer() -> None:
    """atexit 回调：尝试关闭 AsyncPostgresSaver 上下文。"""
    context_manager = _checkpointer_context
    if context_manager is None:
        return
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        loop.run_until_complete(context_manager.__aexit__(None, None, None))
        loop.close()
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            f"关闭 AsyncPostgresSaver 失败: {exc!r}",
            event_type="checkpointer_close_failed",
        )


atexit.register(_close_checkpointer)

_DIRECTOR_TEXT_ACTIONS: frozenset[str] = frozenset({
    "generate_brief",
    "generate_narrative",
    "generate_shot_plan",
})


# ---------------------------------------------------------------------------
# 节点 1：load_project_snapshot
# ---------------------------------------------------------------------------

async def load_project_snapshot(state: ProjectGraphState) -> dict:
    """从 DB 加载 ProjectSnapshot 并扩展阶段感知字段。

    除了基础 ProjectSnapshot，还加载：
      - open PendingDecisions（待处理决策）
      - selected PendingDecisions（已选关键决策）
      - 推断 style_direction / brief_confirmed / shot_plan_confirmed

    失败时写入 error 字段，不抛出异常。
    """
    project_id: str = state.get("project_id", "")
    user_id: str = state.get("user_id", "")

    if not project_id or not user_id:
        return {"error": "缺少 project_id 或 user_id，无法加载项目快照"}

    try:
        async with UnitOfWork() as uow:
            session = uow.session
            repo = ProjectRepository(session)
            project = await repo.get_by_id_for_user(project_id, user_id)

            if project is None:
                return {"error": f"项目 {project_id!r} 不存在或不属于当前用户"}

            # 提前初始化 asset_repo（后续多处复用，避免重复实例化）
            asset_repo = AssetRepository(session)

            _character_refs: list[CharacterRef] = []
            _scene_refs: list[SceneRef] = []
            _active_csv = None  # Bug-2修复：提前初始化，防止 NameError
            
            # Bug修复：即使当前没有激活的视觉圣经版本，后续判断是否 confirm_visual_bible 也会用到 _active_csv
            # 为防止后续代码 UnboundLocalError，此处先声明 _csv_repo
            _csv_repo = CharacterSetVersionRepository(session)
            
            if project.active_character_set_version_id:
                _active_csv = await _csv_repo.get_active(project_id)
                if _active_csv is not None:
                    # WP7 适配：从独立表查询角色/场景参考图（JSONB 列已置空）
                    from app.repositories.character_reference_repository import CharacterReferenceRepository
                    from app.repositories.scene_reference_repository import SceneReferenceRepository
                    _char_ref_rows = await CharacterReferenceRepository(session).list_by_version(_active_csv.id)
                    _scene_ref_rows = await SceneReferenceRepository(session).list_by_version(_active_csv.id)

                    _active_asset_ids = [
                        c.active_reference_asset_id
                        for c in _char_ref_rows
                        if c.active_reference_asset_id
                    ] + [
                        s.active_reference_asset_id
                        for s in _scene_ref_rows
                        if s.active_reference_asset_id
                    ]
                    _url_map: dict[str, str] = {}
                    if _active_asset_ids:
                        _ref_assets = await asset_repo.list_by_ids(_active_asset_ids)
                        _url_map = await build_asset_access_url_map(_ref_assets)
                    _character_refs = [
                        CharacterRef(
                            character_id=c.character_id,
                            character_name=c.character_name,
                            active_asset_id=c.active_reference_asset_id,
                            asset_url=_url_map.get(c.active_reference_asset_id or "") or None,
                            base_face_asset_id=c.base_face_asset_id,
                            image_analysis_done=bool(c.image_analysis),
                        )
                        for c in _char_ref_rows
                    ]
                    _scene_refs = [
                        SceneRef(
                            scene_id=s.scene_id,
                            scene_name=s.scene_name,
                            active_asset_id=s.active_reference_asset_id,
                            asset_url=_url_map.get(s.active_reference_asset_id or "") or None,
                        )
                        for s in _scene_ref_rows
                    ]

            snapshot = ProjectSnapshot(
                project_id=project_id,
                current_stage=project.current_stage,
                active_versions=ActiveVersions(
                    project_spec=project.active_project_spec_version_id,
                    audio_analysis=project.active_audio_analysis_version_id,
                    creative_brief=project.active_brief_version_id,
                    style_bible=project.active_style_version_id,
                    character_set=project.active_character_set_version_id,
                    narrative_script=project.active_narrative_script_version_id,  # doc11
                    scene_plan=project.active_scene_plan_version_id,
                    shot_plan=project.active_shot_plan_version_id,
                    storyboard=project.active_storyboard_version_id,
                    timeline=project.active_timeline_version_id,
                    latest_export=project.latest_export_version_id,
                ),
                snapshot_taken_at=datetime.now(timezone.utc),
                character_refs=_character_refs,
                scene_refs=_scene_refs,
            )

            # 加载决策数据
            decision_repo = DecisionRepository(session)
            open_decisions_objs = await decision_repo.list_open(project_id)
            open_decisions = [
                _decision_obj_to_dict(d) for d in open_decisions_objs
            ]

            # 已选 style_direction
            style_decisions = await decision_repo.list_by_type(
                project_id, "select_style_direction", status="selected"
            )
            style_direction = (
                style_decisions[0].selected_option_id if style_decisions else None
            )

            # brief_confirmed
            brief_decisions = await decision_repo.list_by_type(
                project_id, "confirm_brief", status="selected"
            )
            brief_confirmed: bool = any(
                d.selected_option_id == "confirm" for d in brief_decisions
            )

            # shot_plan_confirmed
            shot_decisions = await decision_repo.list_by_type(
                project_id, "confirm_shot_plan", status="selected"
            )
            shot_plan_confirmed: bool = any(
                d.selected_option_id == "confirm" for d in shot_decisions
            )

            # storyboard_confirmed
            storyboard_decisions = await decision_repo.list_by_type(
                project_id, "confirm_storyboard", status="selected"
            )
            storyboard_confirmed: bool = any(
                d.selected_option_id == "confirm" for d in storyboard_decisions
            )

            # narrative_confirmed
            narrative_decisions = await decision_repo.list_by_type(
                project_id, "confirm_narrative", status="selected"
            )
            narrative_confirmed: bool = any(
                d.selected_option_id == "confirm" for d in narrative_decisions
            )

            # visual_bible_confirmed
            vb_decisions = await decision_repo.list_by_type(
                project_id, "confirm_visual_bible", status="selected"
            )
            visual_bible_confirmed: bool = any(
                d.selected_option_id == "confirm" for d in vb_decisions
            )
            if not visual_bible_confirmed and _active_csv is not None:
                visual_bible_confirmed = bool(getattr(_active_csv, "confirmed_at", None))

            # doc11 批次2：加载用户上传的 image_reference URL（最多 3 张）
            image_ref_assets = await asset_repo.list_by_project(
                project_id, asset_type="image_reference", limit=3
            )
            reference_image_urls: list[str] = []
            for asset in image_ref_assets:
                url = await build_asset_access_url(asset)
                if url:
                    reference_image_urls.append(url)

            # doc11 批次2：加载激活的 audio_original URL
            audio_url: str | None = None
            if project.active_audio_analysis_version_id:
                # 通过 project_spec 中的 audio_asset_id 查找原始音频
                audio_assets = await asset_repo.list_by_project(
                    project_id, asset_type="audio_original", limit=1
                )
                if audio_assets:
                    audio_url = await build_asset_access_url(audio_assets[0])

            selected_decisions = [
                _decision_obj_to_dict(d)
                for d in (
                    style_decisions + brief_decisions + shot_decisions
                    + storyboard_decisions + narrative_decisions + vb_decisions
                )
            ]

            # 批次 A/C 补救：从最新版本构建 ArtifactRef 引用
            # Sub-agent 运行需要这些引用作为输入，不再传原文
            audio_analysis_ref = None
            if project.active_audio_analysis_version_id:
                aa_repo = AudioAnalysisRepository(session)
                aa_v = await aa_repo.get_by_id(project.active_audio_analysis_version_id)
                if aa_v:
                    audio_analysis_ref = await build_ref_from_asset_latest(
                        project_id, "audio_analysis", aa_v.version_no,
                        prefix="audio_analysis", summary=f"BPM: {aa_v.bpm}"
                    )

            brief_ref = None
            if project.active_brief_version_id:
                from app.repositories.planning_repositories import CreativeBriefRepository
                b_repo = CreativeBriefRepository(session)
                b_v = await b_repo.get_by_id(project.active_brief_version_id)
                if b_v:
                    brief_ref = await build_ref_from_asset_latest(
                        project_id, "creative_brief", b_v.version_no,
                        prefix="creative_brief", summary=b_v.summary or ""
                    )

            narrative_ref = None
            if project.active_narrative_script_version_id:
                from app.repositories.visual_bible_repository import NarrativeScriptVersionRepository  # Bug-3修复：正确的类名
                n_repo = NarrativeScriptVersionRepository(session)
                n_v = await n_repo.get_by_id(project.active_narrative_script_version_id)
                if n_v:
                    narrative_ref = await build_ref_from_asset_latest(
                        project_id, "narrative_script", n_v.version_no,
                        prefix="narrative_script", summary="叙事剧本"
                    )

            shot_plan_ref = None
            if project.active_shot_plan_version_id:
                from app.repositories.planning_repositories import ShotPlanRepository
                s_repo = ShotPlanRepository(session)
                s_v = await s_repo.get_by_id(project.active_shot_plan_version_id)
                if s_v:
                    shot_plan_ref = await build_ref_from_asset_latest(
                        project_id, "shot_plan", s_v.version_no,
                        prefix="shot_plan", summary="镜头计划"
                    )

            visual_bible_ref = None
            if project.active_character_set_version_id:
                v_repo = CharacterSetVersionRepository(session)
                v_v = await v_repo.get_by_id(project.active_character_set_version_id)
                if v_v:
                    visual_bible_ref = await build_ref_from_asset_latest(
                        project_id, "visual_bible", v_v.version_no,
                        prefix="character_set", summary="视觉圣经"
                    )

        return {
            "project_snapshot": snapshot.model_dump(mode="json"),
            "open_decisions": open_decisions,
            "selected_decisions": selected_decisions,
            "style_direction": style_direction,
            "brief_confirmed": brief_confirmed,
            "shot_plan_confirmed": shot_plan_confirmed,
            "storyboard_confirmed": storyboard_confirmed,
            "narrative_confirmed": narrative_confirmed,
            "visual_bible_confirmed": visual_bible_confirmed,
            "reference_image_urls": reference_image_urls,
            "audio_url": audio_url,
            # 补救字段写入 state
            "audio_analysis_ref": audio_analysis_ref,
            "brief_ref": brief_ref,
            "narrative_ref": narrative_ref,
            "shot_plan_ref": shot_plan_ref,
            "visual_bible_ref": visual_bible_ref,
            "pending_decision_id": None,
            "decision_options": [],
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        _logger.error(
            f"load_project_snapshot 失败: {exc!r}",
            event_type="load_snapshot_failed",
        )
        return {"error": f"加载项目快照失败：{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# 节点 2：director_intake
# ---------------------------------------------------------------------------

async def director_intake(state: ProjectGraphState) -> dict:
    """调用 Director Agent 和 Intent Resolution Service，写回回复和动作字段。"""

    # 若上一节点失败，直接返回错误信息
    if state.get("error"):
        return {
            "assistant_message": f"[系统错误] {state['error']}",
            "decision_options": [],
            "requires_confirmation": False,
            "next_action": None,
        }

    agent = DirectorAgent()
    intent_svc = IntentResolutionService()

    if state.get("system_trigger"):
        return await _execute_director_mode_b(
            state=state,
            agent=agent,
            intent_svc=intent_svc,
        )

    director_out = await agent.run(state)
    intent_result = intent_svc.resolve(director_out)
    return await _finalize_director_response(
        state=state,
        director_out=director_out,
        intent_result=intent_result,
    )


# ---------------------------------------------------------------------------
# 节点 3：respond_to_user
# ---------------------------------------------------------------------------

def respond_to_user(state: ProjectGraphState) -> dict:
    """确保 assistant_message 已设置（兜底保护）。

    目前是直通节点，未来可在此处：
      - 格式化 assistant_message（加选项卡、确认卡的 JSON 载荷）
      - 根据 requires_confirmation 生成确认提示文案
    """
    if not state.get("assistant_message"):
        return {"assistant_message": "[系统未能生成回复，请稍后重试]"}
    return {}


# ---------------------------------------------------------------------------
# 快照载入辅助函数
# ---------------------------------------------------------------------------

def _decision_obj_to_dict(d: object) -> dict:
    """PendingDecision ORM 对象 → 轻量 dict（仅包含快照需要的字段）。"""
    return {
        "id": getattr(d, "id", None),
        "decision_type": getattr(d, "decision_type", None),
        "status": getattr(d, "status", None),
        "selected_option_id": getattr(d, "selected_option_id", None),
        "options_payload": getattr(d, "options_payload", []),
    }


def _pick_review_artifact(dispatch_result: dict) -> Optional[dict]:
    artifact_ref = dispatch_result.get("artifact_ref")
    if artifact_ref:
        return artifact_ref
    action_name = dispatch_result.get("task_type")
    if action_name == "generate_brief":
        return dispatch_result.get("brief_ref")
    if action_name == "generate_shot_plan":
        return dispatch_result.get("shot_plan_ref")
    return None


def _build_dispatch_state_updates(dispatch_result: dict) -> dict:
    action_name = dispatch_result.get("task_type")
    review_ref = _pick_review_artifact(dispatch_result)
    updates: dict = {}
    if review_ref:
        updates["artifact_ref_for_review"] = review_ref
    if action_name == "generate_brief":
        updates["brief_ref"] = dispatch_result.get("brief_ref") or review_ref
    elif action_name == "generate_narrative":
        updates["narrative_ref"] = review_ref
    elif action_name == "generate_shot_plan":
        updates["shot_plan_ref"] = dispatch_result.get("shot_plan_ref") or review_ref
    return updates


async def _finalize_director_response(
    *,
    state: ProjectGraphState,
    director_out: dict,
    intent_result,
) -> dict:
    dispatch_result: dict = director_out.get("dispatch_result") or {}
    if dispatch_result.get("error"):
        return {
            "decision_options": [],
            "assistant_message": f"[系统错误] {dispatch_result['error']}",
            "requires_confirmation": False,
            "next_action": None,
            "error": dispatch_result["error"],
        }

    if (
        intent_result.next_action in _DIRECTOR_TEXT_ACTIONS
        and not dispatch_result
    ):
        action_name = intent_result.next_action
        return {
            "assistant_message": (
                f"[系统错误] Director 未按协议调用 dispatch_agent_tool 就返回了 "
                f"{action_name!r}。文本主线已拒绝继续执行。"
            ),
            "requires_confirmation": False,
            "next_action": None,
            "decision_options": [],
            "error": f"director_missing_dispatch:{action_name}",
        }

    pending_decision_id = None
    requires_confirmation = intent_result.requires_confirmation
    next_action = intent_result.next_action
    created_decision = director_out.get("created_decision") or {}
    if created_decision.get("decision_id"):
        pending_decision_id = created_decision.get("decision_id")
        requires_confirmation = True
        next_action = None
    elif next_action and next_action.startswith("request_"):
        decision_result = await create_decision_for_action(
            project_id=state.get("project_id", ""),
            session_id=state.get("session_id", ""),
            next_action=next_action,
            context_summary=intent_result.user_message,
            options=director_out.get("options") or [],
        )
        if not decision_result.get("error"):
            pending_decision_id = decision_result.get("decision_id")
            requires_confirmation = True
            next_action = None

    result = {
        "assistant_message": intent_result.user_message,
        "requires_confirmation": requires_confirmation,
        "next_action": next_action,
        "pending_decision_id": pending_decision_id,
        "decision_options": director_out.get("options") or [],
        "error": None,
    }
    if dispatch_result:
        result.update(_build_dispatch_state_updates(dispatch_result))
    return result


async def _execute_director_mode_b(
    *,
    state: ProjectGraphState,
    agent: DirectorAgent,
    intent_svc: IntentResolutionService,
) -> dict:
    system_trigger: dict = state.get("system_trigger") or {}
    if system_trigger.get("task_type") == "generate_clips":
        trigger_result = system_trigger.get("result") or {}
        clip_count = int(trigger_result.get("clip_count") or 0)
        project_stage = trigger_result.get("project_stage") or ""
        if clip_count <= 0 or project_stage == "failed":
            return {
                "assistant_message": "视频生成阶段失败：没有生成出可用视频片段。请查看失败镜头原因后重试视频生成。",
                "requires_confirmation": False,
                "next_action": None,
                "pending_decision_id": None,
                "decision_options": [],
                "error": None,
            }

    report_output = await agent.run(state)
    report_result = intent_svc.resolve(report_output)
    if report_result.next_action not in _MODE_B_CONFIRM_ACTIONS:
        report_result.next_action = None
        report_result.requires_confirmation = False
    return await _finalize_director_response(
        state=state,
        director_out=report_output,
        intent_result=report_result,
    )


# ---------------------------------------------------------------------------
# 条件路由
# ---------------------------------------------------------------------------

# 快照载入后预路由：处理确定性阶段（input_ready 跳过 Director）
def _route_after_snapshot(state: ProjectGraphState) -> str:
    """load_project_snapshot 完成后的预路由。

    路由优先级（高→低）：
      1. 错误状态  → director_intake（展示错误）
      2. Mode B 触发（system_trigger 非空）→ director_intake（跳过阶段预路由）
      3. input_ready 阶段  → audio_analysis_node
      4. 其他            → director_intake
    """
    if state.get("error"):
        return "director_intake"  # 快照失败时进 Director 展示错误
    # Mode B 系统触发：必须进入 director_intake 执行汇报协议，
    # 不能被阶段预路由拦截（防止误路由到 audio_analysis_node）
    if state.get("system_trigger"):
        return "director_intake"
    snapshot: dict = state.get("project_snapshot") or {}
    stage: str = snapshot.get("current_stage", "")
    if stage == "input_ready":
        # 旧流程：input_ready 曾走音频分析节点，新流程直接对话
        # return "audio_analysis_node"
        return "director_intake"
    return "director_intake"


# Director 输出后的阶段感知路由
_ACTION_NODE_MAP: dict[str, str] = {
    # 旧流程（音乐MV模式）：已停用
    # "analyze_audio":                     "audio_analysis_node",
    # "request_style_decision":            "human_confirmation_gate",
    "request_brief_confirmation":        "human_confirmation_gate",
    # doc11 narrative 阶段（保留）
    "request_narrative_confirmation":    "human_confirmation_gate",
    # doc 21 决策 D1：visual_bible 阶段已 deprecated，路由停用
    # "request_visual_bible_confirmation": "human_confirmation_gate",
    # 原有
    "request_shot_plan_confirmation":    "human_confirmation_gate",
    "generate_storyboard":               "storyboard_node",
    "request_storyboard_confirmation":   "human_confirmation_gate",
    "generate_clips":                    "clip_node",
    "generate_timeline":                 "timeline_node",
}


def _route_after_director(state: ProjectGraphState) -> str:
    """阶段感知路由（director_intake 之后）。

    路由优先级：
      1. input_ready 强制路由到 audio_analysis_node
      2. next_action 已注册时直接路由
      3. 阶段备用：若 Director 未输出正确 next_action 但处于需要 gate 的阶段，则强制进 gate
    """
    snapshot: dict = state.get("project_snapshot") or {}
    stage: str = snapshot.get("current_stage", "")
    next_action: str | None = state.get("next_action")
    style_direction: str | None = state.get("style_direction")
    brief_confirmed: bool = bool(state.get("brief_confirmed", False))
    shot_plan_confirmed: bool = bool(state.get("shot_plan_confirmed", False))
    storyboard_confirmed: bool = bool(state.get("storyboard_confirmed", False))
    narrative_confirmed: bool = bool(state.get("narrative_confirmed", False))
    visual_bible_confirmed: bool = bool(state.get("visual_bible_confirmed", False))

    # 1. input_ready 确定性强制路由
    # 旧流程（音乐MV模式）：input_ready 曾强制路由到 audio_analysis_node
    # if stage == "input_ready":
    #     return "audio_analysis_node"
    # 新流程：input_ready 直接进 director_intake（brief 生成已在前置 REST 调用中触发）

    # 2. next_action 已注册
    if next_action and next_action in _ACTION_NODE_MAP:
        return _ACTION_NODE_MAP[next_action]

    # 3. 阶段备用：若 Director 未输出正确 next_action，按阶段强制路由
    if stage == "audio_analyzed" and not style_direction:
        return "human_confirmation_gate"
    if stage == "brief_ready" and not brief_confirmed:
        return "human_confirmation_gate"
    # narrative_ready → 等待用户确认叙事剧本
    if stage == "narrative_ready" and not narrative_confirmed:
        return "human_confirmation_gate"
    # doc 21 决策 D1：visual_bible 阶段已停用，narrative 确认后直接进 shot_plan
    # 旧流程（doc11 批次2）：
    # if stage == "narrative_ready" and narrative_confirmed and not visual_bible_confirmed:
    #     return "human_confirmation_gate"
    # if stage == "visual_bible_ready" and not visual_bible_confirmed:
    #     return "human_confirmation_gate"
    if stage == "shot_plan_ready":
        return "storyboard_node"
    # 新流程：shot_plan 是 narrative → 九宫格之间的内部派生数据，不再创建
    # confirm_shot_plan 人工门。媒体任务仍通过显式 action 或幂等 worker dispatch 推进。

    return "respond_to_user"


# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------

def _build_graph() -> object:
    """构建并编译 LangGraph 主图。仅在首次调用时执行。

    P6-02 清理：移除文本主线节点（generate_brief_node / narrative_node /
    generate_shot_plan_node）。文本生成任务由 Director 自身的工具调用结果
    在 director_intake 内收口，不再走图内业务路由。
    """
    # 媒体任务节点（Worker dispatch 层）保留
    from app.workflows.nodes.human_confirmation_gate import human_confirmation_gate  # noqa: PLC0415
    from app.workflows.nodes.clip_node import clip_node  # noqa: PLC0415
    from app.workflows.nodes.storyboard_node import storyboard_node  # noqa: PLC0415
    from app.workflows.nodes.timeline_node import timeline_node  # noqa: PLC0415

    graph_builder = StateGraph(ProjectGraphState)

    # 注册所有节点（文本主线生成节点已移除，由 director_intake 内直连 Sub-Agent）
    graph_builder.add_node("load_project_snapshot", load_project_snapshot)
    graph_builder.add_node("director_intake", director_intake)
    # 旧流程节点（音乐MV模式）：已停用，import 已注释，不再注册
    # graph_builder.add_node("audio_analysis_node", audio_analysis_node)
    graph_builder.add_node("human_confirmation_gate", human_confirmation_gate)
    graph_builder.add_node("storyboard_node", storyboard_node)
    graph_builder.add_node("clip_node", clip_node)
    graph_builder.add_node("timeline_node", timeline_node)
    graph_builder.add_node("respond_to_user", respond_to_user)

    # 首节点到快照加载
    graph_builder.add_edge(START, "load_project_snapshot")

    # 快照加载后：预路由（input_ready 绕过 Director）
    graph_builder.add_conditional_edges(
        "load_project_snapshot",
        _route_after_snapshot,
        {
            # 旧流程路由：已停用
            # "audio_analysis_node": "audio_analysis_node",
            "director_intake": "director_intake",
        },
    )

    # Director 后：阶段感知路由（文本主线任务已在 director_intake 内处理，不再路由到节点）
    graph_builder.add_conditional_edges(
        "director_intake",
        _route_after_director,
        {
            # 旧流程路由：已停用
            # "audio_analysis_node":     "audio_analysis_node",
            "human_confirmation_gate": "human_confirmation_gate",
            "storyboard_node":         "storyboard_node",
            "clip_node":               "clip_node",
            "timeline_node":           "timeline_node",
            "respond_to_user":         "respond_to_user",
        },
    )

    # 媒体任务节点 + 其他节点最终到 respond_to_user
    # 旧流程边：已停用
    # graph_builder.add_edge("audio_analysis_node",    "respond_to_user")
    graph_builder.add_edge("human_confirmation_gate", "respond_to_user")
    graph_builder.add_edge("storyboard_node",        "respond_to_user")
    graph_builder.add_edge("clip_node",              "respond_to_user")
    graph_builder.add_edge("timeline_node",          "respond_to_user")
    graph_builder.add_edge("respond_to_user",         END)

    # 编译时注入已初始化的 checkpointer
    compiled = graph_builder.compile(checkpointer=_checkpointer)

    _logger.info(
        "LangGraph 主图已编译（阶段感知路由: input_ready→audio_analysis, "
        "audio_analyzed→gate/brief, brief_ready+confirmed→narrative, "
        "narrative_ready+confirmed→visual_bible/shot_plan, "
        "shot_plan_ready+confirmed→storyboard, storyboard_ready+confirmed→clip）",
        event_type="main_graph_compiled",
    )
    return compiled


async def get_main_graph():
    """返回全局编译好的主图单例（异步懒加载，首次调用时初始化 checkpointer）。"""
    global _graph, _checkpointer
    if _graph is None:
        _checkpointer = await _build_async_checkpointer()
        _graph = _build_graph()
    return _graph


# ---------------------------------------------------------------------------
# 图调用入口（供 openai_compat.py 使用）
# ---------------------------------------------------------------------------

async def invoke_director_graph(
    *,
    user_id: str,
    project_id: str,
    session_id: str,
    user_message: str,
    history: list[dict],
    system_trigger: Optional[dict] = None,
    artifact_ref_for_review: Optional[dict] = None,
) -> tuple[str, bool, Optional[str], Optional[str], list[dict]]:
    """调用主图，返回 (assistant_message, requires_confirmation, next_action,
    pending_decision_id, decision_options)。

    Args:
        user_id:       当前用户 ID。
        project_id:    目标项目 ID。
        session_id:    对话会话 ID（同时作为 LangGraph thread_id）。
        user_message:  本轮用户输入（已持久化）。
        history:       完整对话历史（含本轮 user 消息，OpenAI messages 格式）。
        system_trigger: 系统触发信号（Mode B 汇报模式）。
        artifact_ref_for_review: 供审核的产物引用。

    Returns:
        (assistant_message, requires_confirmation, next_action,
         pending_decision_id, decision_options)
        任何异常均被捕获，返回错误提示文本，不抛出。
    """
    graph = await get_main_graph()

    initial_state: ProjectGraphState = {
        "user_id": user_id,
        "project_id": project_id,
        "session_id": session_id,
        "user_message": user_message,
        "history": history,
        # 快照扩展字段，由 load_project_snapshot 覆写
        "open_decisions": [],
        "selected_decisions": [],
        "style_direction": None,
        "brief_confirmed": False,
        "shot_plan_confirmed": False,
        "storyboard_confirmed": False,
        "narrative_confirmed": False,
        "visual_bible_confirmed": False,
        "reference_image_urls": [],
        "audio_url": None,
        "system_trigger": system_trigger,
        "artifact_ref_for_review": artifact_ref_for_review,
        "pending_decision_id": None,
        "decision_options": [],
        # 中间字段
        "project_snapshot": None,
        "assistant_message": "",
        "requires_confirmation": False,
        "next_action": None,
        "error": None,
    }

    # thread_id = session_id，保证同会话多轮连续
    config = {"configurable": {"thread_id": session_id}}

    try:
        result: ProjectGraphState = await graph.ainvoke(initial_state, config=config)
    except Exception as exc:  # noqa: BLE001
        _logger.error(
            f"主图调用失败: {exc!r}",
            event_type="main_graph_invoke_failed",
        )
        return (
            f"[系统错误] 主图执行失败：{type(exc).__name__}: {exc}",
            False,
            None,
            None,
            [],
        )

    return (
        result.get("assistant_message") or "[系统未能生成回复]",
        bool(result.get("requires_confirmation", False)),
        result.get("next_action"),
        result.get("pending_decision_id"),
        result.get("decision_options") or [],
    )
