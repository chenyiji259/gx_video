"""音频分析 LangGraph 节点（AudioAnalysisNode）。

来源文档：doc 09 §12 任务 8-05 / doc12 偏差1 / 批次C

职责（批次C 异步化改版）：
  - 创建 analyze_audio ToolJob 并推入 Redis 队列，立即返回
  - Worker 后台消费任务，调用 AudioAnalysisService + AudioAnalysisAgent
  - Worker 完成后触发 DirectorReportService Mode B 自动汇报

接入条件（main_graph.py 中的条件路由）：
  当项目处于 input_ready 阶段时自动路由到本节点，不等用户发命令。

注意：
  本节点不再同步等待分析完成，直接返回"任务已提交"消息。
  错误（缺少 project_id 等）仍同步处理。
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.repositories.unit_of_work import UnitOfWork
from app.tasks.dispatcher import task_dispatcher
from app.workflows.graph_state import ProjectGraphState

_logger = get_logger("workflows.nodes.audio_analysis", layer="system")


async def audio_analysis_node(state: ProjectGraphState) -> dict:
    """创建 analyze_audio ToolJob 并入队，立即返回。

    批次C：异步分发版本。
    Worker 后台消费该任务，调用 AudioAnalysisService.run_and_save()
    （内部并发执行 librosa beat_track + Omni 语义分析，一步完成落库），
    完成后由 DirectorReportService 触发 Mode B 自动汇报。

    输入（从 state 读取）：
      project_id (str)
      user_id (str)

    输出（写入 state）：
      assistant_message (str)  — 任务提交确认消息
      next_action (None)
      error (str | None)
    """
    project_id: str = state.get("project_id", "")
    user_id: str = state.get("user_id", "")

    _logger.info(
        f"音频分析节点（dispatch 版）启动: project={project_id}",
        event_type="audio_analysis_node_dispatch_start",
    )

    if not project_id or not user_id:
        return {
            "assistant_message": "[系统错误] 缺少 project_id 或 user_id，无法提交音频分析任务",
            "next_action": None,
            "error": "missing_project_or_user",
        }

    try:
        async with UnitOfWork() as uow:
            job, is_new = await task_dispatcher.dispatch(
                uow.session,
                project_id=project_id,
                tool_name="analyze_audio",
                input_payload={"project_id": project_id, "user_id": user_id},
            )
        if is_new:
            await task_dispatcher.push_to_queue(job.id)

        _logger.info(
            f"audio_analysis_node: 任务已提交 job_id={job.id!r} is_new={is_new}",
            event_type="audio_analysis_node_dispatched",
        )
        return {
            "assistant_message": (
                "音频分析任务已提交，通常需要 10-30 秒。\n"
                "完成后导演将自动汇报 BPM、段落结构和歌词摘要，请稍候。"
            ),
            "next_action": None,
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        _logger.error(
            f"audio_analysis_node dispatch 失败: {exc!r}",
            event_type="audio_analysis_node_dispatch_error",
        )
        return {
            "assistant_message": f"[系统错误] 音频分析任务提交失败：{exc}",
            "next_action": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
