"""clip_node — 主图 clip 生成节点。

来源文档：doc 09 任务 11-05

职责：
  - 从 GraphState 读取 project_id / user_id
  - 调用 ClipService.generate_and_save()
  - 成功时回填 assistant_message
  - 失败时降级为错误提示，不让异常穿透图执行

触发条件：
  项目处于 storyboard_ready，可开始生成 clip，
  由 _route_after_director 路由至此。
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.repositories.unit_of_work import UnitOfWork
from app.services.cost_gate_service import CostGateService
from app.tasks.dispatcher import task_dispatcher
from app.workflows.graph_state import ProjectGraphState

_logger = get_logger("workflows.nodes.clip_node", layer="system")


async def clip_node(state: ProjectGraphState) -> dict:
    """创建 generate_clips ToolJob 并入队，立即返回。

    doc11 批次3：异步分发版本。
    doc11 批次4：集成 CostGate，高成本动作必须先确认费用。
    Worker 后台消费该任务并调用 ClipService.generate_and_save()。
    """
    project_id: str = state.get("project_id", "")
    user_id: str = state.get("user_id", "")
    session_id: str = state.get("session_id", "")

    if not project_id or not user_id:
        return {
            "assistant_message": "[系统错误] 缺少 project_id 或 user_id，无法提交视频片段生成任务",
            "next_action": None,
        }

    # doc11 批次4：费用前置门控 — 已停用（开发/调试模式）
    # 生产环境可恢复：取消下方注释，注释掉 confirmed = True
    # cost_gate = CostGateService()
    # confirmed, decision_id = await cost_gate.estimate_and_gate(
    #     project_id=project_id,
    #     session_id=session_id or project_id,
    # )
    # if not confirmed:
    #     decision_hint = f"(决策 ID: {decision_id})" if decision_id else ""
    #     _logger.info(
    #         f"clip_node: 费用未确认，等待用户确认 {decision_hint}",
    #         event_type="clip_node_cost_gate_pending",
    #     )
    #     return {
    #         "assistant_message": (
    #             "视频片段生成为高成本操作，已为你创建费用确认卡。\n"
    #             "请查看费用明细并确认后，我将立即开始生成。"
    #         ),
    #         "next_action": None,
    #     }
    confirmed = True  # 开发模式：跳过费用确认，直接生成

    try:
        async with UnitOfWork() as uow:
            job, is_new = await task_dispatcher.dispatch(
                uow.session,
                project_id=project_id,
                tool_name="generate_clips",
                input_payload={"project_id": project_id, "user_id": user_id},
            )
        if is_new:
            await task_dispatcher.push_to_queue(job.id)

        _logger.info(
            f"clip_node: 任务已提交 job_id={job.id!r} is_new={is_new}",
            event_type="clip_node_dispatched",
        )
        return {
            "assistant_message": (
                "视频片段生成任务已提交，此过程耗时较长（每个 clip 约 5-15 分钟）。\n"
                "完成后工作台将实时展示各镜头视频预览，请稍候。"
            ),
            "next_action": None,
        }
    except Exception as exc:  # noqa: BLE001
        _logger.error(
            f"clip_node 分发失败: {exc!r}",
            event_type="clip_node_dispatch_error",
        )
        return {
            "assistant_message": f"[系统错误] 视频片段任务提交失败：{exc}",
            "next_action": None,
        }
