"""Project Repository — 项目数据访问层。

工程约束（R4）：
  所有查询都必须按 user_id 隔离，不允许跨用户查询。
  create/get/list/update 都必须绑定 user_id。
"""
from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    """项目仓库，所有查询强制按 user_id 隔离。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Project)

    async def get_by_id_for_user(self, project_id: str, user_id: str) -> Project | None:
        """按项目 ID 查询，同时校验所属用户（防止越权访问）。"""
        stmt = select(Project).where(
            and_(Project.id == project_id, Project.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = 20,
        after_id: str | None = None,
        include_archived: bool = False,
    ) -> list[Project]:
        """查询用户的项目列表。

        Args:
            user_id: 必须传，防止全量查询。
            limit: 每页条数，默认 20，最大 100。
            after_id: 游标分页：从该 ID 对应的 updated_at 之前开始查（exclusive）。
            include_archived: 是否包含已归档项目，默认 False。

        Returns:
            按 updated_at desc 排序的项目列表。
        """
        limit = min(limit, 100)  # 硬性上限，防止超大分页

        conditions = [Project.user_id == user_id]

        if not include_archived:
            conditions.append(Project.status != "archived")

        stmt = select(Project).where(and_(*conditions))

        # 游标分页：如果提供了 after_id，找到该项目的 updated_at，查更早的
        if after_id:
            anchor = await self.get_by_id_for_user(after_id, user_id)
            if anchor is not None:
                stmt = stmt.where(Project.updated_at < anchor.updated_at)

        stmt = stmt.order_by(Project.updated_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def name_exists_for_user(self, user_id: str, name: str) -> bool:
        """检查用户是否已有同名活跃项目（防止重复项目名）。"""
        stmt = select(Project.id).where(
            and_(
                Project.user_id == user_id,
                Project.name == name,
                Project.status == "active",
            )
        ).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None
