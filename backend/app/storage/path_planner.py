"""本地产物路径规划器（Local Artifact Path Planner）。

工程约束（doc 08 § 8）：
  所有阶段产物必须可追溯，本地存储结构固定为：

    data/
      projects/
        {project_id}/
          01_input/          原始音频、切段音频、参考图
          02_audio_analysis/ beat map、section map、lyrics alignment
          03_brief/          creative brief JSON
          04_style/          style bible、character set JSON
          05_shot_plan/      shot plan JSON、每个 shot semantic spec
          06_storyboard/     storyboard 图片和元数据
          07_prompt_bundles/ 每个 shot 的 prompt bundle JSON
          08_clips/          生成 clip 文件和执行结果
          09_timeline/       timeline JSON、字幕轨、preview
          10_export/         导出结果和元数据
          logs/              项目级 agent/tool 日志
          snapshots/         graph snapshot、memory snapshot

文件命名规范（doc 08 § 8.5）：
    {stage}_{name}_{version}_{timestamp}.json
    例如：shot_plan_v3_20260327_103000.json
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional


# 项目根目录（相对于本文件向上 4 层：storage → app → backend → 项目根）
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# 本地产物根目录
DATA_ROOT = _PROJECT_ROOT / "data" / "projects"


class ArtifactStage:
    """各阶段目录名常量。"""
    INPUT           = "01_input"
    AUDIO_ANALYSIS  = "02_audio_analysis"
    BRIEF           = "03_brief"
    STYLE           = "04_style"
    SHOT_PLAN       = "05_shot_plan"
    STORYBOARD      = "06_storyboard"
    PROMPT_BUNDLES  = "07_prompt_bundles"
    CLIPS           = "08_clips"
    TIMELINE        = "09_timeline"
    EXPORT          = "10_export"
    LOGS            = "logs"
    SNAPSHOTS       = "snapshots"

    ALL_STAGES = [
        INPUT, AUDIO_ANALYSIS, BRIEF, STYLE, SHOT_PLAN,
        STORYBOARD, PROMPT_BUNDLES, CLIPS, TIMELINE, EXPORT,
        LOGS, SNAPSHOTS,
    ]


class ProjectPathPlanner:
    """为单个项目提供所有阶段的路径计算。

    用法：
        planner = ProjectPathPlanner("proj_abc123")
        input_dir = planner.stage_dir(ArtifactStage.INPUT)
        brief_file = planner.artifact_path(ArtifactStage.BRIEF, "brief", version=2)
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.project_dir = DATA_ROOT / project_id

    # ------------------------------------------------------------------ #
    # 目录访问
    # ------------------------------------------------------------------ #

    def stage_dir(self, stage: str, *, create: bool = False) -> Path:
        """获取指定阶段的目录路径。

        Args:
            stage: ArtifactStage 常量之一。
            create: 是否自动创建目录（默认 False）。
        """
        d = self.project_dir / stage
        if create:
            d.mkdir(parents=True, exist_ok=True)
        return d

    def ensure_all_dirs(self) -> None:
        """创建项目下所有阶段目录（项目初始化时调用）。"""
        for stage in ArtifactStage.ALL_STAGES:
            (self.project_dir / stage).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # 文件命名
    # ------------------------------------------------------------------ #

    @staticmethod
    def build_filename(
        name: str,
        ext: str = "json",
        version: Optional[int] = None,
        timestamp: Optional[str] = None,
    ) -> str:
        """构建标准化文件名。

        命名规范：{name}[_v{version}][_{timestamp}].{ext}

        Examples:
            build_filename("brief", version=2)
            → "brief_v2_20260327_103000.json"

            build_filename("audio_clip", ext="mp3")
            → "audio_clip_20260327_103000.mp3"
        """
        ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        parts = [name]
        if version is not None:
            parts.append(f"v{version}")
        parts.append(ts)
        return f"{'_'.join(parts)}.{ext}"

    def artifact_path(
        self,
        stage: str,
        name: str,
        ext: str = "json",
        version: Optional[int] = None,
        timestamp: Optional[str] = None,
        *,
        create_dir: bool = True,
    ) -> Path:
        """计算某个产物的完整本地路径。

        Args:
            stage: ArtifactStage 常量。
            name: 产物名称，如 "brief"、"shot_plan"、"prompt_bundle_shot_008"。
            ext: 文件扩展名（不含点），默认 "json"。
            version: 版本号，为 None 则不写入文件名。
            timestamp: 时间戳字符串，为 None 则使用当前时间。
            create_dir: 是否自动创建父目录，默认 True。

        Returns:
            完整的 Path 对象。
        """
        stage_dir = self.stage_dir(stage, create=create_dir)
        filename = self.build_filename(name, ext=ext, version=version, timestamp=timestamp)
        return stage_dir / filename

    # ------------------------------------------------------------------ #
    # 快捷阶段路径
    # ------------------------------------------------------------------ #

    def input_dir(self) -> Path:
        return self.stage_dir(ArtifactStage.INPUT, create=True)

    def audio_analysis_dir(self) -> Path:
        return self.stage_dir(ArtifactStage.AUDIO_ANALYSIS, create=True)

    def brief_dir(self) -> Path:
        return self.stage_dir(ArtifactStage.BRIEF, create=True)

    def style_dir(self) -> Path:
        return self.stage_dir(ArtifactStage.STYLE, create=True)

    def shot_plan_dir(self) -> Path:
        return self.stage_dir(ArtifactStage.SHOT_PLAN, create=True)

    def storyboard_dir(self) -> Path:
        return self.stage_dir(ArtifactStage.STORYBOARD, create=True)

    def nine_grid_dir(self) -> Path:
        """九宫格大图目录：data/projects/{pid}/06_storyboard/grids/（doc 21 §5.4）。"""
        d = self.storyboard_dir() / "grids"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def storyboard_cells_dir(self) -> Path:
        """切分图目录：data/projects/{pid}/06_storyboard/cells/（doc 21 §5.4）。"""
        d = self.storyboard_dir() / "cells"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def prompt_bundles_dir(self) -> Path:
        return self.stage_dir(ArtifactStage.PROMPT_BUNDLES, create=True)

    def clips_dir(self) -> Path:
        return self.stage_dir(ArtifactStage.CLIPS, create=True)

    def timeline_dir(self) -> Path:
        return self.stage_dir(ArtifactStage.TIMELINE, create=True)

    def export_dir(self) -> Path:
        return self.stage_dir(ArtifactStage.EXPORT, create=True)

    def logs_dir(self) -> Path:
        return self.stage_dir(ArtifactStage.LOGS, create=True)

    def snapshots_dir(self) -> Path:
        return self.stage_dir(ArtifactStage.SNAPSHOTS, create=True)

    def __repr__(self) -> str:
        return f"ProjectPathPlanner(project_id={self.project_id!r}, root={self.project_dir})"
