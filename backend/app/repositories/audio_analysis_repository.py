"""AudioAnalysis Repository — 音频分析版本数据访问层。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audio_analysis import AudioAnalysisVersion
from app.repositories.base import BaseRepository


class AudioAnalysisRepository(BaseRepository[AudioAnalysisVersion]):
    """音频分析版本表查询。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AudioAnalysisVersion)

    async def get_active(self, project_id: str) -> Optional[AudioAnalysisVersion]:
        """获取当前激活的音频分析版本。"""
        stmt = (
            select(AudioAnalysisVersion)
            .where(
                AudioAnalysisVersion.project_id == project_id,
                AudioAnalysisVersion.is_active.is_(True),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_next_version_no(self, project_id: str) -> int:
        """计算下一个版本号（当前最大 version_no + 1，从 1 开始）。"""
        stmt = select(
            func.coalesce(func.max(AudioAnalysisVersion.version_no), 0) + 1
        ).where(AudioAnalysisVersion.project_id == project_id)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def deactivate_all(self, project_id: str) -> None:
        """将该项目下所有版本 is_active 置为 False（激活新版本前调用）。"""
        stmt = (
            update(AudioAnalysisVersion)
            .where(
                AudioAnalysisVersion.project_id == project_id,
                AudioAnalysisVersion.is_active.is_(True),
            )
            .values(is_active=False)
        )
        await self._session.execute(stmt)

    async def get_by_id_for_project(
        self, version_id: str, project_id: str
    ) -> Optional[AudioAnalysisVersion]:
        """按 ID 查询，同时验证项目归属。"""
        stmt = select(AudioAnalysisVersion).where(
            AudioAnalysisVersion.id == version_id,
            AudioAnalysisVersion.project_id == project_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
