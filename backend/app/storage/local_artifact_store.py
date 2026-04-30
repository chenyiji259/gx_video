"""本地产物存储器（Local Artifact Store）。

工程约束（doc 08 § 8）：
  数据库只保存结构化索引和元数据，本地文件保存：
    - 原始 prompt bundle
    - provider 原始请求/响应
    - 原始阶段文件
    - 调试日志

用法：
    from app.storage.local_artifact_store import LocalArtifactStore
    from app.storage.path_planner import ArtifactStage

    store = LocalArtifactStore("proj_abc123")
    path = store.write_json(
        ArtifactStage.BRIEF, "brief",
        {"title": "雨夜 MV", "mood": "melancholy"},
        version=1,
    )
    data = store.read_json(path)
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Optional

from app.storage.path_planner import ArtifactStage, ProjectPathPlanner


class LocalArtifactStore:
    """为单个项目提供本地产物的读写操作。"""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._planner = ProjectPathPlanner(project_id)

    # ------------------------------------------------------------------ #
    # 写操作
    # ------------------------------------------------------------------ #

    def write_json(
        self,
        stage: str,
        name: str,
        data: Any,
        version: Optional[int] = None,
        timestamp: Optional[str] = None,
        *,
        indent: int = 2,
    ) -> Path:
        """将对象序列化为 JSON 写入本地。

        Returns:
            写入的文件 Path。
        """
        path = self._planner.artifact_path(
            stage, name, ext="json",
            version=version, timestamp=timestamp,
        )
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=indent),
            encoding="utf-8",
        )
        return path

    def write_text(
        self,
        stage: str,
        name: str,
        content: str,
        ext: str = "txt",
        version: Optional[int] = None,
        timestamp: Optional[str] = None,
    ) -> Path:
        """将文本写入本地。"""
        path = self._planner.artifact_path(
            stage, name, ext=ext,
            version=version, timestamp=timestamp,
        )
        path.write_text(content, encoding="utf-8")
        return path

    def write_bytes(
        self,
        stage: str,
        name: str,
        data: bytes,
        ext: str = "bin",
        version: Optional[int] = None,
        timestamp: Optional[str] = None,
    ) -> Path:
        """将二进制数据写入本地（用于音频、图片、视频副本）。"""
        path = self._planner.artifact_path(
            stage, name, ext=ext,
            version=version, timestamp=timestamp,
        )
        path.write_bytes(data)
        return path

    def copy_file(
        self,
        stage: str,
        name: str,
        source_path: Path,
        ext: Optional[str] = None,
        version: Optional[int] = None,
        timestamp: Optional[str] = None,
    ) -> Path:
        """将已存在的文件复制到对应阶段目录（用于资产副本追溯）。"""
        file_ext = ext or source_path.suffix.lstrip(".")
        dest = self._planner.artifact_path(
            stage, name, ext=file_ext,
            version=version, timestamp=timestamp,
        )
        shutil.copy2(source_path, dest)
        return dest

    # ------------------------------------------------------------------ #
    # 读操作
    # ------------------------------------------------------------------ #

    def read_json(self, path: Path) -> Any:
        """读取并反序列化 JSON 文件。"""
        return json.loads(path.read_text(encoding="utf-8"))

    def read_text(self, path: Path) -> str:
        """读取文本文件。"""
        return path.read_text(encoding="utf-8")

    def read_bytes(self, path: Path) -> bytes:
        """读取二进制文件。"""
        return path.read_bytes()

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #

    def list_stage_files(
        self,
        stage: str,
        pattern: str = "*",
    ) -> list[Path]:
        """列出某个阶段目录下的所有文件（按名称排序）。

        Args:
            stage: ArtifactStage 常量。
            pattern: glob 模式，默认 "*"（全部文件）。
        """
        stage_dir = self._planner.stage_dir(stage)
        if not stage_dir.exists():
            return []
        return sorted(stage_dir.glob(pattern))

    def stage_exists(self, stage: str) -> bool:
        """检查某个阶段目录是否已存在。"""
        return self._planner.stage_dir(stage).exists()

    def latest_in_stage(
        self,
        stage: str,
        prefix: str = "",
        ext: str = "json",
    ) -> Optional[Path]:
        """获取某个阶段目录下最新（按文件名字典序最大）的文件。

        因为文件名含时间戳，字典序最大即最新。
        """
        files = self.list_stage_files(stage, pattern=f"{prefix}*.{ext}")
        return files[-1] if files else None

    # ------------------------------------------------------------------ #
    # 项目初始化
    # ------------------------------------------------------------------ #

    def init_project_dirs(self) -> None:
        """初始化项目的所有阶段目录（项目创建时调用）。"""
        self._planner.ensure_all_dirs()

    @property
    def planner(self) -> ProjectPathPlanner:
        """返回底层路径规划器（供需要直接操作路径的场景使用）。"""
        return self._planner

    @property
    def project_dir(self) -> Path:
        """返回项目根目录路径。"""
        return self._planner.project_dir

    def __repr__(self) -> str:
        return f"LocalArtifactStore(project_id={self.project_id!r})"
