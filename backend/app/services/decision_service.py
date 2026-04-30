"""DecisionService — 挂起决策管理服务。

职责：
  - 创建待决策记录（create_decision）
  - 查询项目待决策列表（get_pending_decisions）
  - 查询单个决策（get_decision）
  - 提交用户选择（submit_decision）
  - 过期/取消决策（expire_decision / cancel_decision）

状态机：open → selected | expired | cancelled

文档约束（doc 09 任务 8-07 / 9-04）：
  - 高成本操作前通过 human_confirmation_gate 节点创建决策
  - 前端通过 GET /decisions 轮询待决策
  - 用户通过 POST /decisions/{id}/select 提交选择后
    由工作流触发 API（任务 9-05）继续推进 Pipeline
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from app.core.logging import get_logger
from app.models.workflow import PendingDecision
from app.repositories.decision_repository import DecisionRepository
from app.repositories.unit_of_work import UnitOfWork

_logger = get_logger("services.decision", layer="system")


# ---------------------------------------------------------------------------
# 业务异常
# ---------------------------------------------------------------------------

class DecisionError(Exception):
    """DecisionService 业务异常。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# 序列化帮助函数
# ---------------------------------------------------------------------------

def _decision_to_dict(d: PendingDecision) -> dict:
    """将 PendingDecision ORM 对象转为 API 响应 dict。

    session 关闭后访问 detached ORM 对象的简单列属性是安全的，
    只要不触发 lazy-load 的关联查询即可。
    """
    return {
        "id": d.id,
        "project_id": d.project_id,
        "session_id": d.session_id,
        "decision_type": d.decision_type,
        "target_entity_type": d.target_entity_type,
        "target_entity_id": d.target_entity_id,
        "options_payload": d.options_payload,
        "default_option_id": d.default_option_id,
        "selected_option_id": d.selected_option_id,
        "status": d.status,
        "expires_at": d.expires_at.isoformat() if d.expires_at else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


# ---------------------------------------------------------------------------
# DecisionService
# ---------------------------------------------------------------------------

class DecisionService:
    """PendingDecision 管理服务。"""

    # ------------------------------------------------------------------ #
    # 创建决策
    # ------------------------------------------------------------------ #

    async def create_decision(
        self,
        project_id: str,
        session_id: str,
        decision_type: str,
        target_entity_type: str,
        options_payload: list,
        *,
        target_entity_id: Optional[str] = None,
        default_option_id: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> dict:
        """创建一个新的挂起决策。

        Args:
            project_id:          关联项目 ID
            session_id:          当前会话 ID（关联 conversation_sessions）
            decision_type:       决策类型，如 "select_style_direction" / "confirm_brief"
            target_entity_type:  影响的实体类型，如 "project" / "style" / "shot"
            options_payload:     选项列表，每项格式 {"id": "...", "label": "...", ...}
            target_entity_id:    影响的实体 ID（可选，项目级决策可为 None）
            default_option_id:   默认选项 ID（可选，前端预选）
            expires_at:          过期时间（可选，None 表示永不过期）

        Returns:
            决策 dict（_decision_to_dict 格式）。
        """
        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            decision = PendingDecision(
                project_id=project_id,
                session_id=session_id,
                decision_type=decision_type,
                target_entity_type=target_entity_type,
                target_entity_id=target_entity_id,
                options_payload=options_payload,
                default_option_id=default_option_id,
                status="open",
                expires_at=expires_at,
            )
            await repo.add(decision)
            await uow.flush()
            await uow.session.refresh(decision)

        _logger.info(
            f"Decision created type={decision_type!r} project={project_id!r} id={decision.id!r}",
            event_type="decision_created",
        )
        return _decision_to_dict(decision)

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #

    async def get_pending_decisions(self, project_id: str) -> List[dict]:
        """查询项目下所有 status='open' 的待确认决策。

        前端工作台通过此接口轮询（或 SSE 推送后按需请求）
        当前等待用户处理的风格选项/brief 确认/shot list 确认等。
        """
        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            decisions = await repo.list_open(project_id)
        return [_decision_to_dict(d) for d in decisions]

    async def get_decision(
        self, project_id: str, decision_id: str
    ) -> Optional[dict]:
        """查询单个决策详情（含用户选择结果，任意状态均可查询）。"""
        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            decision = await repo.get_by_id_for_project(decision_id, project_id)
        return _decision_to_dict(decision) if decision else None

    async def has_open_decision_of_type(
        self, project_id: str, decision_type: str
    ) -> bool:
        """检查是否已有指定类型的 open 决策（幂等创建前的检查）。"""
        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            existing = await repo.list_by_type(project_id, decision_type, status="open")
        return len(existing) > 0

    async def has_selected_decision_of_type(
        self, project_id: str, decision_type: str
    ) -> bool:
        """检查是否已有指定类型的 selected 决策（防止回环重复创建）。"""
        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            existing = await repo.list_by_type(project_id, decision_type, status="selected")
        return len(existing) > 0

    # ------------------------------------------------------------------ #
    # 提交选择
    # ------------------------------------------------------------------ #

    async def submit_decision(
        self,
        project_id: str,
        decision_id: str,
        selected_option_id: str,
    ) -> dict:
        """提交用户选择，将决策状态从 open → selected。

        Args:
            project_id:          关联项目 ID（安全校验，防止跨项目操作）
            decision_id:         决策 ID
            selected_option_id:  用户选择的选项 ID

        Returns:
            更新后的决策 dict。

        Raises:
            DecisionError: 决策不存在、不属于该项目、状态非 open、或选项不在列表中。
        """
        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            decision = await repo.get_by_id_for_project(decision_id, project_id)

            if decision is None:
                raise DecisionError("not_found", f"Decision {decision_id!r} not found")

            if decision.status != "open":
                raise DecisionError(
                    "invalid_status",
                    f"Decision is already {decision.status!r}, cannot submit again",
                )

            # 校验选项合法性（options_payload 有结构化 id 时才做校验）
            # options_payload 格式：[{"id": "...", "label": "...", ...}, ...]
            valid_ids = {
                opt.get("id")
                for opt in (decision.options_payload or [])
                if isinstance(opt, dict) and opt.get("id")
            }
            if valid_ids and selected_option_id not in valid_ids:
                raise DecisionError(
                    "invalid_option",
                    f"Option {selected_option_id!r} is not valid. "
                    f"Valid choices: {sorted(valid_ids)}",
                )

            decision.status = "selected"
            decision.selected_option_id = selected_option_id
            uow.session.add(decision)
            await uow.flush()
            await uow.session.refresh(decision)

        _logger.info(
            f"Decision {decision_id!r} selected={selected_option_id!r} project={project_id!r}",
            event_type="decision_selected",
        )
        return _decision_to_dict(decision)

    # ------------------------------------------------------------------ #
    # 过期 / 取消
    # ------------------------------------------------------------------ #

    async def expire_decision(self, decision_id: str) -> None:
        """将决策状态设置为 expired（系统自动过期调用，如检测到 expires_at 已过）。"""
        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            decision = await repo.get_by_id(decision_id)
            if decision is not None and decision.status == "open":
                decision.status = "expired"
                uow.session.add(decision)

    async def cancel_decision(self, decision_id: str) -> None:
        """将决策状态设置为 cancelled（系统主动撤销，如 Director Agent 生成了新决策）。"""
        async with UnitOfWork() as uow:
            repo = DecisionRepository(uow.session)
            decision = await repo.get_by_id(decision_id)
            if decision is not None and decision.status == "open":
                decision.status = "cancelled"
                uow.session.add(decision)
