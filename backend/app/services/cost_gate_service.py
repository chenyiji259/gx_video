"""高成本动作费用前置门控服务（CostGateService）。

来源文档：doc11 §16.4（高成本 ToolCall 的费用前置门控）

职责：
  在派发高成本任务（视频 clip 生成）前，检查用户是否已确认费用明细。
  若未确认，创建 confirm_cost_clips PendingDecision 并返回"需要确认"信号。

调用方：
  workflows/nodes/clip_node.py — 在 dispatch 前调用 estimate_and_gate()

幂等性：
  - 如果已有 selected 的 confirm_cost_clips 决策（selected_option_id='confirm'）→ 直接放行
  - 如果已有 open 的 confirm_cost_clips 决策 → 不重复创建，返回已有决策 ID
  - 如果都没有 → 估算费用 + 创建新决策

费用估算策略（简化版）：
  基于 active ShotPlan 中的 planned/stale 状态 shot 数量，
  结合平均时长估算总 credits。
"""
from __future__ import annotations

from typing import Optional

from app.core.logging import get_logger
from app.repositories.decision_repository import DecisionRepository
from app.repositories.planning_repositories import ShotPlanRepository, ShotRepository
from app.repositories.unit_of_work import UnitOfWork
from app.services.cost_estimation_service import CostEstimationService
from app.services.decision_service import DecisionService

_logger = get_logger("services.cost_gate", layer="system")

# 临时策略：当前项目阶段关闭所有高成本动作的费用确认门控。
_COST_GATE_BYPASS_ENABLED = True

# 默认平均 shot 时长（秒）
_DEFAULT_AVG_SHOT_DURATION_SEC = 4.0


class CostGateService:
    """高成本动作费用前置门控。"""

    def __init__(self) -> None:
        self._estimator = CostEstimationService()
        self._decision_svc = DecisionService()

    async def estimate_and_gate(
        self,
        project_id: str,
        session_id: str,
    ) -> tuple[bool, Optional[str]]:
        """检查 clip 生成费用门控。

        Returns:
            (confirmed, decision_id)
            confirmed=True  → 费用已确认，可以 dispatch generate_clips
            confirmed=False → 需要等待用户确认，decision_id 为 PendingDecision ID

        Raises:
            无异常。内部异常均被捕获并降级为"已确认"（不阻塞生成流程）。
        """
        if _COST_GATE_BYPASS_ENABLED:
            _logger.info(
                f"Cost gate bypass: clips 放行 project={project_id!r}",
                event_type="cost_gate_bypass_clips",
            )
            return True, None
        try:
            return await self._check_gate(project_id, session_id)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                f"CostGateService 异常，降级为已确认: {exc!r}",
                event_type="cost_gate_error_fallback",
            )
            # 出错时降级：允许生成（不因费用服务故障阻塞主流程）
            return True, None

    async def _check_gate(
        self,
        project_id: str,
        session_id: str,
    ) -> tuple[bool, Optional[str]]:
        """内部门控检查逻辑（可抛异常）。"""

        # ---- 1. 检查是否已有已选中的确认决策 ----------------------------------
        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            selected = await repo.list_by_type(
                project_id, "confirm_cost_clips", status="selected"
            )

        if selected:
            confirmed_option = selected[0].selected_option_id
            if confirmed_option == "confirm":
                _logger.debug(
                    f"CostGate: project={project_id!r} 费用已确认，放行",
                    event_type="cost_gate_confirmed",
                )
                return True, None
            # 用户选择了取消
            _logger.info(
                f"CostGate: project={project_id!r} 用户取消了费用确认",
                event_type="cost_gate_cancelled",
            )
            return False, None

        # ---- 2. 检查是否已有 open 的确认决策（幂等检查）-----------------------
        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            open_decisions = await repo.list_by_type(
                project_id, "confirm_cost_clips", status="open"
            )

        if open_decisions:
            _logger.debug(
                f"CostGate: project={project_id!r} 已有 open 决策，等待用户确认",
                event_type="cost_gate_open_decision_exists",
            )
            return False, open_decisions[0].id

        # ---- 3. 没有决策 → 估算费用 + 创建新决策 ------------------------------
        shot_count, avg_duration = await self._load_shot_info(project_id)
        total_credits = self._estimator.estimate_clips_batch(
            shot_count=shot_count,
            avg_duration_sec=avg_duration,
            mode="image_to_video",
        )

        cost_label = (
            f"确认生成 {shot_count} 个视频片段"
            f"（预计 {total_credits} credits，约 {shot_count * 5}-{shot_count * 15} 分钟）"
            if total_credits > 0
            else f"确认生成 {shot_count} 个视频片段"
        )

        decision = await self._decision_svc.create_decision(
            project_id=project_id,
            session_id=session_id,
            decision_type="confirm_cost_clips",
            target_entity_type="project",
            options_payload=[
                {"id": "confirm", "label": cost_label},
                {"id": "cancel", "label": "取消生成"},
            ],
        )

        _logger.info(
            f"CostGate: project={project_id!r} 创建费用确认决策 "
            f"id={decision['id']!r} shots={shot_count} credits={total_credits}",
            event_type="cost_gate_decision_created",
        )
        return False, decision["id"]

    # ------------------------------------------------------------------
    # 口型生成门控
    # ------------------------------------------------------------------

    async def estimate_and_gate_lipsync(
        self,
        project_id: str,
        session_id: str,
        *,
        shot_id: str,
        duration_ms: int = 0,
    ) -> tuple[bool, "Optional[str]"]:
        """检查单个 lipsync shot 的费用门控。

        Returns:
            (confirmed, decision_id)
        """
        if _COST_GATE_BYPASS_ENABLED:
            _logger.info(
                f"Cost gate bypass: lipsync 放行 project={project_id!r} shot={shot_id!r}",
                event_type="cost_gate_bypass_lipsync",
            )
            return True, None
        try:
            return await self._check_gate_lipsync(project_id, session_id, shot_id, duration_ms)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                f"CostGateService lipsync 异常，降级为已确认: {exc!r}",
                event_type="cost_gate_lipsync_error_fallback",
            )
            return True, None

    async def _check_gate_lipsync(
        self,
        project_id: str,
        session_id: str,
        shot_id: str,
        duration_ms: int,
    ) -> tuple[bool, "Optional[str]"]:
        """Lipsync 门控内部实现。"""
        decision_type = f"confirm_cost_lipsync_{shot_id[:8]}"

        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            selected = await repo.list_by_type(project_id, decision_type, status="selected")

        if selected:
            return selected[0].selected_option_id == "confirm", None

        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            open_decisions = await repo.list_by_type(project_id, decision_type, status="open")

        if open_decisions:
            return False, open_decisions[0].id

        duration_sec = duration_ms / 1000.0 if duration_ms else 5.0
        credits = self._estimator.estimate_lipsync(duration_sec)
        label = (
            f"确认为该镜头生成口型视频（预计 {credits} credits，约 1-5 分钟）"
            if credits > 0
            else "确认为该镜头生成口型视频"
        )
        decision = await self._decision_svc.create_decision(
            project_id=project_id,
            session_id=session_id,
            decision_type=decision_type,
            target_entity_type="shot",
            options_payload=[
                {"id": "confirm", "label": label},
                {"id": "cancel", "label": "取消生成"},
            ],
        )
        _logger.info(
            f"CostGate lipsync: project={project_id!r} shot={shot_id!r} "
            f"decision={decision['id']!r} credits={credits}",
            event_type="cost_gate_lipsync_decision_created",
        )
        return False, decision["id"]

    # ------------------------------------------------------------------
    # 导出门控
    # ------------------------------------------------------------------

    async def estimate_and_gate_export(
        self,
        project_id: str,
        session_id: str,
        *,
        resolution: str = "720p",
        duration_sec: float = 0.0,
    ) -> tuple[bool, "Optional[str]"]:
        """检查导出费用门控。

        Returns:
            (confirmed, decision_id)
        """
        if _COST_GATE_BYPASS_ENABLED:
            _logger.info(
                f"Cost gate bypass: export 放行 project={project_id!r} resolution={resolution!r}",
                event_type="cost_gate_bypass_export",
            )
            return True, None
        try:
            return await self._check_gate_export(project_id, session_id, resolution, duration_sec)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                f"CostGateService export 异常，降级为已确认: {exc!r}",
                event_type="cost_gate_export_error_fallback",
            )
            return True, None

    async def _check_gate_export(
        self,
        project_id: str,
        session_id: str,
        resolution: str,
        duration_sec: float,
    ) -> tuple[bool, "Optional[str]"]:
        """Export 门控内部实现。"""
        decision_type = f"confirm_cost_export_{resolution}"

        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            selected = await repo.list_by_type(project_id, decision_type, status="selected")

        if selected:
            return selected[0].selected_option_id == "confirm", None

        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            open_decisions = await repo.list_by_type(project_id, decision_type, status="open")

        if open_decisions:
            return False, open_decisions[0].id

        # 导出时长未知时用 shot plan 总时长估算
        if duration_sec <= 0:
            duration_sec = await self._estimate_project_duration(project_id)

        credits = self._estimator.estimate_export(
            duration_sec=max(duration_sec, 30.0),  # 至少按 30 秒计算
            resolution=resolution,  # type: ignore[arg-type]
        )
        label = (
            f"确认导出 {resolution} 视频（预计 {credits} credits，时长 ≈{int(duration_sec)}s）"
            if credits > 0
            else f"确认导出 {resolution} 视频"
        )
        decision = await self._decision_svc.create_decision(
            project_id=project_id,
            session_id=session_id,
            decision_type=decision_type,
            target_entity_type="project",
            options_payload=[
                {"id": "confirm", "label": label},
                {"id": "cancel", "label": "取消导出"},
            ],
        )
        _logger.info(
            f"CostGate export: project={project_id!r} resolution={resolution!r} "
            f"decision={decision['id']!r} credits={credits}",
            event_type="cost_gate_export_decision_created",
        )
        return False, decision["id"]

    async def _estimate_project_duration(self, project_id: str) -> float:
        """从 active shot plan 估算项目总时长（秒）。"""
        async with UnitOfWork() as uow:
            shot_plan = await ShotPlanRepository(uow.session).get_active(project_id)
            if shot_plan is None:
                return 30.0
            shots = await ShotRepository(uow.session).list_by_project(project_id)
        total_ms = sum(s.duration_ms or 0 for s in shots if s.shot_plan_version_id == shot_plan.id)
        return max(total_ms / 1000.0, 30.0)

    async def _load_shot_info(
        self, project_id: str
    ) -> tuple[int, float]:
        """读取需要生成的 shot 数量和平均时长。"""
        async with UnitOfWork() as uow:
            shot_plan = await ShotPlanRepository(uow.session).get_active(project_id)
            if shot_plan is None:
                return 0, _DEFAULT_AVG_SHOT_DURATION_SEC

            shot_repo = ShotRepository(uow.session)
            all_shots = await shot_repo.list_by_project(project_id)

        # 只计算需要生成的 shot（planned/stale 状态）
        pending_shots = [
            s for s in all_shots
            if s.status in ("planned", "stale", "storyboard_ready")
            and s.shot_plan_version_id == shot_plan.id
        ]
        count = len(pending_shots)
        if count == 0:
            return 0, _DEFAULT_AVG_SHOT_DURATION_SEC

        # 计算平均时长
        total_ms = sum(s.duration_ms or 0 for s in pending_shots)
        avg_sec = (total_ms / count / 1000.0) if total_ms > 0 else _DEFAULT_AVG_SHOT_DURATION_SEC
        return count, avg_sec
