"""storyboard_node — 主图 storyboard 生成节点（doc11 批次3：异步分发版）。

来源文档：doc 09 任务 10-04 / doc11 批次3

职责：
  创建 ToolJob 并推入 Redis 队列，立即返回“任务已提交”消息。
  Worker 后台消费任务并调用 StoryboardService.generate_and_save()。
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.repositories.unit_of_work import UnitOfWork
from app.tasks.dispatcher import task_dispatcher
from app.workflows.graph_state import ProjectGraphState

_logger = get_logger("workflows.nodes.storyboard_node", layer="system")


async def storyboard_node(state: ProjectGraphState) -> dict:
    """创建 generate_storyboard ToolJob 并入队，立即返回。

    doc11 批次3：异步分发版本。
    Worker 后台消费该任务并调用 StoryboardService.generate_and_save()。
    """
    project_id: str = state.get("project_id", "")
    user_id: str = state.get("user_id", "")

    if not project_id or not user_id:
        return {
            "assistant_message": "[系统错误] 缺少 project_id 或 user_id，无法提交分镜图生成任务",
            "next_action": None,
        }

    try:
        async with UnitOfWork() as uow:
            job, is_new = await task_dispatcher.dispatch(
                uow.session,
                project_id=project_id,
                tool_name="generate_storyboard",
                input_payload={"project_id": project_id, "user_id": user_id},
            )
        # Bug 3 修复：将 push_to_queue 单独包 try/except。
        # 阿里系图片生成为同步调用（单次 HTTP 返回结果，无轮询），
        # Worker handler 运行时间可控，但 Redis push 失败会导致
        # ToolJob 永远卡在 pending，_recover_stale_jobs 不覆盖这种情况。
        # 失败时明确返回错误，避免用户以为任务已成功提交。
        if is_new:
            try:
                await task_dispatcher.push_to_queue(job.id)
            except Exception as push_exc:  # noqa: BLE001
                _logger.error(
                    f"storyboard_node: Redis 入队失败，任务已落库但未入队: "
                    f"job_id={job.id!r} error={push_exc!r}",
                    event_type="storyboard_node_push_failed",
                )
                return {
                    "assistant_message": (
                        f"[系统错误] 分镜图任务入队失败（Redis 连接异常），请稍后重试。"
                    ),
                    "next_action": None,
                }

        _logger.info(
            f"storyboard_node: 任务已提交 job_id={job.id!r} is_new={is_new}",
            event_type="storyboard_node_dispatched",
        )
        return {
            "assistant_message": (
                "分镜图生成任务已提交，通常需要 2-5 分钟。\n"
                "完成后工作台将实时展示分镜图，请稍候。"
            ),
            "next_action": None,
        }
    except Exception as exc:  # noqa: BLE001
        _logger.error(
            f"storyboard_node 分发失败: {exc!r}",
            event_type="storyboard_node_dispatch_error",
        )
        return {
            "assistant_message": f"[系统错误] 分镜图任务提交失败：{exc}",
            "next_action": None,
        }
