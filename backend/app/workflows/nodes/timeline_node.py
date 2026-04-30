"""timeline_node — 主图时间线合成节点。

来源文档：doc 09 任务 11-07

职责：
  - 调用 TimelineComposerService.compose_and_save()
  - ffmpeg 不可用时返回明确提示，不降级
  - 业务/意外异常均降级为错误消息，不穿透图执行
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.repositories.unit_of_work import UnitOfWork
from app.tasks.dispatcher import task_dispatcher
from app.workflows.graph_state import ProjectGraphState

_logger = get_logger("workflows.nodes.timeline_node", layer="system")


async def timeline_node(state: ProjectGraphState) -> dict:
    """创建 generate_timeline ToolJob 并入队，立即返回。

    doc11 批次3：异步分发版本。
    Worker 后台消费该任务并调用 TimelineComposerService.compose_and_save()。
    """
    project_id: str = state.get("project_id", "")
    user_id: str = state.get("user_id", "")

    if not project_id or not user_id:
        return {
            "assistant_message": "[系统错误] 缺少 project_id 或 user_id，无法提交时间线合成任务",
            "next_action": None,
        }

    try:
        async with UnitOfWork() as uow:
            job, is_new = await task_dispatcher.dispatch(
                uow.session,
                project_id=project_id,
                tool_name="generate_timeline",
                input_payload={"project_id": project_id, "user_id": user_id},
            )
        if is_new:
            await task_dispatcher.push_to_queue(job.id)

        _logger.info(
            f"timeline_node: 任务已提交 job_id={job.id!r} is_new={is_new}",
            event_type="timeline_node_dispatched",
        )
        return {
            "assistant_message": (
                "时间线合成任务已提交，通常需要 1-5 分钟。\n"
                "完成后工作台将展示完整时间线预览，请稍候。"
            ),
            "next_action": None,
        }
    except Exception as exc:  # noqa: BLE001
        _logger.error(
            f"timeline_node 分发失败: {exc!r}",
            event_type="timeline_node_dispatch_error",
        )
        return {
            "assistant_message": f"[系统错误] 时间线合成任务提交失败：{exc}",
            "next_action": None,
        }
