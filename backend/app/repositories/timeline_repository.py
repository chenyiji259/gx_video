"""Timeline Repository。

来源文档：doc 09 任务 11-06
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.timeline import TimelineSegment, TimelineVersion
from app.repositories.base import BaseRepository


class TimelineVersionRepository(BaseRepository[TimelineVersion]):
    """timeline_versions 表的数据访问层。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TimelineVersion)

    async def get_active(self, project_id: str) -> Optional[TimelineVersion]:
        """返回当前激活的 TimelineVersion。"""
        result = await self.session.execute(
            select(TimelineVersion).where(
                TimelineVersion.project_id == project_id,
                TimelineVersion.is_active.is_(True),
            ).limit(1)
        )
        return result.scalar_one_or_none()

    async def deactivate_all(self, project_id: str) -> None:
        """将项目所有版本标记为 is_active=False。"""
        await self.session.execute(
            update(TimelineVersion)
            .where(TimelineVersion.project_id == project_id)
            .values(is_active=False)
        )

    async def get_next_version_no(self, project_id: str) -> int:
        """返回下一个版本号（max + 1，无记录则返回 1）。"""
        from sqlalchemy import func
        result = await self.session.execute(
            select(func.max(TimelineVersion.version_no)).where(
                TimelineVersion.project_id == project_id
            )
        )
        row = result.scalar_one_or_none()
        return (row or 0) + 1


class TimelineSegmentRepository(BaseRepository[TimelineSegment]):
    """timeline_segments 表的数据访问层。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TimelineSegment)

    async def list_by_version(
        self, timeline_version_id: str
    ) -> list[TimelineSegment]:
        """返回指定版本的所有 segments（按 start_ms 排序）。"""
        result = await self.session.execute(
            select(TimelineSegment)
            .where(TimelineSegment.timeline_version_id == timeline_version_id)
            .order_by(TimelineSegment.start_ms.asc())
        )
        return list(result.scalars().all())

    async def get_by_shot(
        self,
        timeline_version_id: str,
        shot_id: str,
    ) -> Optional[TimelineSegment]:
        """返回指定 timeline 版本中某个 shot 对应的 segment（用于单镜头返工时更新 clip_version_id）。"""
        result = await self.session.execute(
            select(TimelineSegment)
            .where(
                TimelineSegment.timeline_version_id == timeline_version_id,
                TimelineSegment.shot_id == shot_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def bulk_add(self, segments: list[TimelineSegment]) -> None:
        """批量添加 segments。"""
        for seg in segments:
            self.session.add(seg)
        await self.session.flush()
