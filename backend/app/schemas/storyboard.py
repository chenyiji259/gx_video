"""Storyboard schema（三宫格架构）。

来源文档：doc 21 §5.4 + §6（存储链路 + 推送链路设计）

职责：
  定义三宫格架构的 Pydantic 数据传输对象，供 Service / API / Agent 使用。

设计要点：
  - 一张三宫格大图（asset_type=nine_grid_image）→ 1 个 NineGridMeta
  - 3 张切分小图（asset_type=storyboard_frame）→ 3 个 NineGridFrameVO
  - 当前版本按 1 行 × 3 列组织，每一张三宫格对应一个 shot 的 起始 / 中间 / 结尾
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NineGridFrameVO(BaseModel):
    """三宫格中单个 cell 的元数据（对应一张切分图 + 1 个 shot 的关键帧）。

    当前版本中：
      - cell 1/2/3 → 当前 shot 的起始 / 中间 / 结尾
    """
    cell_position: int                      # 1-3
    asset_id: str                           # 切分图 asset_id
    asset_url: str                          # 切分图 storage_uri（永久直链）
    shot_id: str | None = None              # 关联的 shot（同一行 3 个 cell 共享同一个 shot_id）
    is_reused_from_prev_grid: bool = False  # 当前版本固定为 false，保留字段仅兼容旧数据

    model_config = ConfigDict(frozen=True)


class NineGridMeta(BaseModel):
    """单张三宫格大图的完整元数据（含 3 个 cell 的索引）。"""
    grid_index: int                         # 第几张三宫格（从 1 开始）
    parent_asset_id: str                    # 大图 asset_id（asset_type=nine_grid_image）
    parent_asset_url: str                   # 大图 storage_uri（永久直链）
    bundle_id: str | None = None            # 编译该三宫格的 PromptBundle ID
    cell_count: int = 3
    cells: list[NineGridFrameVO] = Field(default_factory=list)
    # 元数据
    width: int | None = None                # 大图宽度（按项目方向映射到 2K）
    height: int | None = None               # 大图高度（按项目方向映射到 2K）
    generation_time_sec: float | None = None  # 生图耗时

    model_config = ConfigDict(frozen=True)


class StoryboardOverview(BaseModel):
    """整个 storyboard 版本的元数据（一个 storyboard_version 包含 N 张三宫格）。

    供前端 GET /api/v1/projects/{pid}/storyboard/grids 使用。
    """
    storyboard_version_id: str
    version_no: int
    grid_count: int                         # 该版本含几张三宫格
    total_frames: int                       # 当前版本总切分图数 = 3 × grid_count
    total_shots: int                        # 当前版本总 shot 数 = grid_count
    grids: list[NineGridMeta] = Field(default_factory=list)
