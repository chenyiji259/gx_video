"""导演汇报服务（DirectorReportService）。

来源文档：doc11 §16.2（Worker 完成 → 系统触发 Director 汇报）

职责：
  Worker 执行成功后，异步触发 Director 以 Mode B（汇报模式）运行，
  生成三段式导演汇报消息并持久化到对话历史中。

调用方：
  tasks/worker.py 的 _succeed_job() — 在 DB 回写完成后，通过
  asyncio.create_task(trigger(...)) 异步触发，不阻塞 Worker 主流程。

Mode B 流程：
  1. 从 DB 加载项目（拿到 user_id）
  2. 读取 active ConversationSession
  3. 加载对话历史
  4. 构造 Mode B ProjectGraphState（包含 system_trigger）
  5. 调用 DirectorAgent.run()
  6. 通过 ConversationService.save_assistant_message() 持久化汇报消息

异常处理：
  所有异常均被捕获 + 记录 warning，不抛出，保证 Worker 主流程不受影响。
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import get_logger
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.event import ProjectEvent
from app.services.conversation_service import ConversationService
from app.services.event_log_service import event_log_service
from app.tools.shared.artifact_tools import build_ref_from_asset as build_ref_from_asset_latest  # DESIGN-11: 使用新名，旧名作为导入时别名保持调用处不变
from app.workflows.main_graph import invoke_director_graph

_logger = get_logger("services.director_report", layer="system")

# DESIGN-06 修复：将原来的 _REPORT_TASK_TYPES 和 _TASK_TO_ARTIFACT 两份配置合并为单一映射。
# 内容： {task_type: None | {"artifact_type": str, "prefix": str}}
# None 表示该任务允许汇报但无文本产物引用（如 generate_clips）。
# 新增任务类型时只需在此处维护一处。
_TASK_CONFIG: dict[str, dict | None] = {
    "analyze_audio":          {"artifact_type": "audio_analysis",  "prefix": "audio_analysis"},
    "generate_brief":         {"artifact_type": "creative_brief",  "prefix": "creative_brief"},
    "generate_narrative":     {"artifact_type": "narrative_script", "prefix": "narrative_script"},
    "generate_storyboard":    {"artifact_type": "storyboard",       "prefix": "storyboard"},
    "generate_timeline":      {"artifact_type": "timeline",         "prefix": "timeline"},
    # generate_character_ref / generate_scene_ref 不再逐张触发汇报，
    # 改由 worker 在检测到全部完成后以 visual_bible_all_completed 一次性触发
    "generate_costume_ref":   None,
    "auto_setup_costumes":    None,
    "generate_shot_plan":     {"artifact_type": "shot_plan",       "prefix": "shot_plan"},
    "init_visual_bible":      None,  # visual_bible JSON 快照只在 confirm 时写入 04_style/，init 阶段无文件
    # 视觉圣经全部完成后的统一汇报（由 worker 检测触发）
    "visual_bible_all_completed": None,
    # 下列任务允许汇报但无文本产物引用
    "generate_clips":         None,
}


# ---------------------------------------------------------------------------
# DirectorReportService
# ---------------------------------------------------------------------------

class DirectorReportService:
    """Worker 完成后触发 Director Mode B 自动汇报。"""

    def __init__(self) -> None:
        self._conv_svc = ConversationService()

    async def trigger(
        self,
        project_id: str,
        task_type: str,
        task_result: dict,
    ) -> None:
        """Worker 任务完成后触发 Director 汇报（Mode B）。

        Args:
            project_id:  所属项目 ID。
            task_type:   完成的任务类型（generate_storyboard / generate_clips / ...）。
            task_result: Worker handler 返回的结果 dict。
        """
        if task_type not in _TASK_CONFIG:
            return  # 非汇报任务类型，静默跳过（DESIGN-06）

        _logger.info(
            f"DirectorReportService 触发: project={project_id!r} task={task_type!r}",
            event_type="director_report_trigger",
        )

        try:
            await self._run_report(project_id, task_type, task_result)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                f"DirectorReportService 汇报失败（不影响业务）: "
                f"project={project_id!r} task={task_type!r} error={exc!r}",
                event_type="director_report_failed",
            )

    # ------------------------------------------------------------------
    # 内部：执行 Mode B 汇报
    # ------------------------------------------------------------------

    async def _run_report(
        self,
        project_id: str,
        task_type: str,
        task_result: dict,
    ) -> None:
        """核心汇报逻辑（可抛异常，由 trigger() 捕获）。"""

        # ---- 步骤 1: 加载项目（拿 user_id + active 版本指针）------------------
        async with UnitOfWork() as uow:
            project = await ProjectRepository(uow.session).get_by_id(project_id)
            if project is None:
                _logger.warning(
                    f"DirectorReportService: 项目 {project_id!r} 不存在，跳过汇报",
                    event_type="director_report_project_not_found",
                )
                return

            user_id: str = project.user_id
            # Bug-7修复：删除未使用的 stage 变量（dead code）

        # ---- 步骤 2: 读取 active ConversationSession -------------------------
        session_dict = await self._conv_svc.get_or_create_session(
            project_id=project_id,
            user_id=user_id,
        )
        session_id: str = session_dict["id"]

        # ---- 步骤 3: 加载对话历史 --------------------------------------------
        history = await self._conv_svc.load_history_for_llm(session_id, limit=10)

        # ---- 步骤 4: 尝试加载对应任务的 ArtifactRef 供审核（DESIGN-06） ----
        artifact_ref_for_review: dict | None = None
        task_cfg = _TASK_CONFIG.get(task_type)  # None 表示无文本产物引用
        if task_cfg is not None:
            artifact_type = task_cfg["artifact_type"]
            prefix = task_cfg["prefix"]
            version_no = task_result.get("version_no", 1) or 1
            artifact_ref_for_review = await build_ref_from_asset_latest(
                project_id,
                artifact_type=artifact_type,
                version_no=version_no,
                prefix=prefix,
                summary=f"{task_type} v{version_no}",
            )

        # ---- 步骤 5: 调用主图（Mode B 汇报模式）-----------------------------
        # 批次 D 改造：由直调 Agent 改为调用主图，确保 checkpoint 状态一致
        system_trigger = {
            "type": "task_completed",
            "task_type": task_type,
            "result": task_result,
        }

        report_message, *_ = await invoke_director_graph(
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
            user_message="",  # Mode B 无用户消息
            history=history,
            system_trigger=system_trigger,
            artifact_ref_for_review=artifact_ref_for_review,
        )

        if not report_message or "系统错误" in report_message:
            _logger.warning(
                f"DirectorReportService: Director 未能生成有效汇报 "
                f"task={task_type!r} msg={report_message!r}",
                event_type="director_report_empty_message",
            )
            return

        # ---- 步骤 6: 持久化汇报消息 ------------------------------------------
        await self._conv_svc.save_assistant_message(
            session_id=session_id,
            content_text=report_message,
            message_type="assistant_text",
        )

        # 批次C：推 SSE 事件，让前端 Chat 区实时收到 Director 汇报消息
        # 通过 EventLogService 写入 outbox_events，OutboxPublisher 将其发布到
        # vidmuse:events:project Redis 频道，前端 SSE 端点转发给客户端
        try:
            async with UnitOfWork() as uow:
                await event_log_service.emit(
                    uow.session,
                    ProjectEvent(
                        project_id=project_id,
                        aggregate_type="project",
                        aggregate_id=project_id,
                        event_type="director.report",
                        category="workflow",
                        payload={
                            "task_type": task_type,
                            "message": report_message,
                            "message_preview": report_message[:200],
                            "session_id": session_id,
                        },
                    ),
                )
            _logger.debug(
                f"DirectorReportService SSE 事件已入队: project={project_id!r}",
                event_type="director_report_sse_queued",
            )
        except Exception as sse_exc:  # noqa: BLE001
            # SSE 入队失败不阻止汇报流程——消息已落库，只是实时推送失败
            _logger.warning(
                f"DirectorReportService SSE 事件入队失败（不影响汇报）: {sse_exc!r}",
                event_type="director_report_sse_failed",
            )

        _logger.info(
            f"DirectorReportService 汇报完成: project={project_id!r} "
            f"task={task_type!r} msg_len={len(report_message)}",
            event_type="director_report_done",
        )


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

director_report_service = DirectorReportService()
