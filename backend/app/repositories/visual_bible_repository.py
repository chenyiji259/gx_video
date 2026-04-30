"""视觉圣经与叙事剧本版本 Repository。

来源文档：doc11 §4.4（VisualBible 结构）/ §5.4（NarrativeScriptAgent）

两个 Repository：
  CharacterSetVersionRepository  — 视觉圣经版本（character_set_versions）
  NarrativeScriptVersionRepository — 叙事剧本版本（narrative_script_versions）

均遵循其他版本表 Repository 的统一接口模式：
  get_active          / get_next_version_no /
  deactivate_all      / get_by_id_for_project
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.visual_bible import CharacterSetVersion, NarrativeScriptVersion
from app.repositories.base import BaseRepository


# ---------------------------------------------------------------------------
# CharacterSetVersionRepository
# ---------------------------------------------------------------------------

class CharacterSetVersionRepository(BaseRepository[CharacterSetVersion]):
    """视觉圣经版本 Repository。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CharacterSetVersion)

    async def get_active(self, project_id: str) -> Optional[CharacterSetVersion]:
        """返回当前激活的视觉圣经版本，不存在时返回 None。"""
        stmt = (
            select(CharacterSetVersion)
            .where(
                CharacterSetVersion.project_id == project_id,
                CharacterSetVersion.is_active.is_(True),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_next_version_no(self, project_id: str) -> int:
        """返回下一个版本号（当前最大值 + 1，无版本时为 1）。"""
        from sqlalchemy import func
        stmt = select(func.max(CharacterSetVersion.version_no)).where(
            CharacterSetVersion.project_id == project_id
        )
        result = await self.session.execute(stmt)
        max_no = result.scalar_one_or_none()
        return (max_no or 0) + 1

    async def deactivate_all(self, project_id: str) -> None:
        """将该项目所有版本的 is_active 置为 False。"""
        stmt = (
            update(CharacterSetVersion)
            .where(CharacterSetVersion.project_id == project_id)
            .values(is_active=False)
        )
        await self.session.execute(stmt)

    async def get_by_id_for_project(
        self, version_id: str, project_id: str
    ) -> Optional[CharacterSetVersion]:
        """按 ID + project_id 查询（防止跨项目访问）。"""
        stmt = select(CharacterSetVersion).where(
            CharacterSetVersion.id == version_id,
            CharacterSetVersion.project_id == project_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# NarrativeScriptVersionRepository
# ---------------------------------------------------------------------------

class NarrativeScriptVersionRepository(BaseRepository[NarrativeScriptVersion]):
    """叙事剧本版本 Repository。"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, NarrativeScriptVersion)

    async def get_active(self, project_id: str) -> Optional[NarrativeScriptVersion]:
        """返回当前激活的叙事剧本版本，不存在时返回 None。"""
        stmt = (
            select(NarrativeScriptVersion)
            .where(
                NarrativeScriptVersion.project_id == project_id,
                NarrativeScriptVersion.is_active.is_(True),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_next_version_no(self, project_id: str) -> int:
        """返回下一个版本号（当前最大值 + 1，无版本时为 1）。"""
        from sqlalchemy import func
        stmt = select(func.max(NarrativeScriptVersion.version_no)).where(
            NarrativeScriptVersion.project_id == project_id
        )
        result = await self.session.execute(stmt)
        max_no = result.scalar_one_or_none()
        return (max_no or 0) + 1

    async def deactivate_all(self, project_id: str) -> None:
        """将该项目所有版本的 is_active 置为 False。"""
        stmt = (
            update(NarrativeScriptVersion)
            .where(NarrativeScriptVersion.project_id == project_id)
            .values(is_active=False)
        )
        await self.session.execute(stmt)

    async def get_by_id_for_project(
        self, version_id: str, project_id: str
    ) -> Optional[NarrativeScriptVersion]:
        """按 ID + project_id 查询（防止跨项目访问）。"""
        stmt = select(NarrativeScriptVersion).where(
            NarrativeScriptVersion.id == version_id,
            NarrativeScriptVersion.project_id == project_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_project(
        self, project_id: str
    ) -> list[NarrativeScriptVersion]:
        """列出该项目所有叙事剧本版本（按版本号升序）。"""
        stmt = (
            select(NarrativeScriptVersion)
            .where(NarrativeScriptVersion.project_id == project_id)
            .order_by(NarrativeScriptVersion.version_no)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
