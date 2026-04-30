"""Storyboard Repository 实现。

来源文档：doc 09 任务 10-03

提供 storyboard_versions 和 storyboard_frames 两张表的基础查询。
模式与 planning_repositories.py 保持一致。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.storyboard import StoryboardFrame, StoryboardVersion
from app.repositories.base import BaseRepository


# ---------------------------------------------------------------------------
# StoryboardVersionRepository
# ---------------------------------------------------------------------------

class StoryboardVersionRepository(BaseRepository[StoryboardVersion]):
    """storyboard_versions 表查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, StoryboardVersion)

    async def get_active(self, project_id: str) -> Optional[StoryboardVersion]:
        """获取当前激活的 storyboard 版本。"""
        stmt = (
            select(StoryboardVersion)
            .where(
                StoryboardVersion.project_id == project_id,
                StoryboardVersion.is_active.is_(True),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_next_version_no(self, project_id: str) -> int:
        """计算下一个版本号（当前最大 + 1，从 1 开始）。"""
        stmt = select(func.max(StoryboardVersion.version_no)).where(
            StoryboardVersion.project_id == project_id
        )
        result = await self._session.execute(stmt)
        max_no: int | None = result.scalar_one_or_none()
        return (max_no or 0) + 1

    async def deactivate_all(self, project_id: str) -> None:
        """将该项目所有 storyboard 版本 is_active 置为 False。"""
        stmt = (
            update(StoryboardVersion)
            .where(
                StoryboardVersion.project_id == project_id,
                StoryboardVersion.is_active.is_(True),
            )
            .values(is_active=False)
        )
        await self._session.execute(stmt)

    async def get_by_id_for_project(
        self, version_id: str, project_id: str
    ) -> Optional[StoryboardVersion]:
        """按 ID 查询，同时验证项目归属。"""
        stmt = select(StoryboardVersion).where(
            StoryboardVersion.id == version_id,
            StoryboardVersion.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# StoryboardFrameRepository
# ---------------------------------------------------------------------------

class StoryboardFrameRepository(BaseRepository[StoryboardFrame]):
    """storyboard_frames 表查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, StoryboardFrame)

    async def list_by_version(
        self,
        storyboard_version_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[StoryboardFrame]:
        """列出指定 storyboard 版本的所有帧（按 frame_index 排序）。"""
        stmt = (
            select(StoryboardFrame)
            .where(StoryboardFrame.storyboard_version_id == storyboard_version_id)
            .order_by(StoryboardFrame.frame_index)
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_version(self, storyboard_version_id: str) -> int:
        """统计指定 storyboard 版本的帧数量。"""
        stmt = select(func.count()).where(
            StoryboardFrame.storyboard_version_id == storyboard_version_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one() or 0

    async def get_by_shot(
        self, storyboard_version_id: str, shot_id: str
    ) -> Optional[StoryboardFrame]:
        """获取指定 storyboard 版本中某个 shot 对应的切分帧。

        新九宫格架构下，真正绑定 shot 的是 cell 小图：
          - shot_id = 对应镜头
          - cell_position ∈ [1, 9]
          - parent_asset_id 指向九宫格大图

        旧实现误写成 frame_index=0，导致在九宫格数据下永远查不到，
        clip / lipsync / 单 shot 重生成链路都会丢失 storyboard 参考帧。
        这里改为优先返回带 cell_position 的帧；若历史单帧数据存在，再回落到任意同 shot 帧。
        """
        stmt = (
            select(StoryboardFrame)
            .where(
                StoryboardFrame.storyboard_version_id == storyboard_version_id,
                StoryboardFrame.shot_id == shot_id,
            )
            .order_by(
                StoryboardFrame.cell_position.is_(None),
                StoryboardFrame.frame_index,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def bulk_add(self, frames: list[StoryboardFrame]) -> None:
        """批量添加帧记录（一次性 flush 效率更高）。"""
        for frame in frames:
            self._session.add(frame)
        await self._session.flush()
