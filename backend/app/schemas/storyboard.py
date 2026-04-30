"""Storyboard schema（doc 21 九宫格架构）。

来源文档：doc 21 §5.4 + §6（存储链路 + 推送链路设计）

职责：
  定义九宫格架构的 Pydantic 数据传输对象，供 Service / API / Agent 使用。

设计要点：
  - 一张九宫格大图（asset_type=nine_grid_image）→ 1 个 NineGridMeta
  - 9 张切分小图（asset_type=storyboard_frame）→ 9 个 NineGridFrameVO
  - 跨九宫格衔接：第 N+1 张的 cell1 物理复用第 N 张的 cell9
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NineGridFrameVO(BaseModel):
    """九宫格中单个 cell 的元数据（对应一张切分图 + 1 个 shot 的关键帧）。

    cell_position 与 shot 的关系（doc 21 §3.1）：
      shot N 的首帧 = cell N 的图片
      shot N 的尾帧 = cell N+1 的图片
      （cell 1-9，shot 1-8，首尾帧重叠）
    """
    cell_position: int                      # 1-9
    asset_id: str                           # 切分图 asset_id
    asset_url: str                          # 切分图 storage_uri（永久直链）
    shot_id: str | None = None              # 关联的 shot（cell N 是 shot[N-1] 的尾帧 + shot[N] 的首帧）
    is_reused_from_prev_grid: bool = False  # 是否复用自上一张九宫格的 cell9（doc 21 §3.2）

    model_config = ConfigDict(frozen=True)


class NineGridMeta(BaseModel):
    """单张九宫格大图的完整元数据（含 9 个 cell 的索引）。"""
    grid_index: int                         # 第几张九宫格（从 1 开始）
    parent_asset_id: str                    # 大图 asset_id（asset_type=nine_grid_image）
    parent_asset_url: str                   # 大图 storage_uri（永久直链）
    bundle_id: str | None = None            # 编译该九宫格的 PromptBundle ID
    cell_count: int = 9
    cells: list[NineGridFrameVO] = Field(default_factory=list)
    # 元数据
    width: int | None = None                # 大图宽度（按项目方向映射到 2K）
    height: int | None = None               # 大图高度（按项目方向映射到 2K）
    generation_time_sec: float | None = None  # 生图耗时

    model_config = ConfigDict(frozen=True)


class StoryboardOverview(BaseModel):
    """整个 storyboard 版本的元数据（一个 storyboard_version 包含 N 张九宫格）。

    供前端 GET /api/v1/projects/{pid}/storyboard/grids 使用。
    """
    storyboard_version_id: str
    version_no: int
    grid_count: int                         # 该版本含几张九宫格
    total_frames: int                       # 总切分图数 = 9 + 8(N-1) = 8N+1
    total_shots: int                        # 总 shot 数 = 8N
    grids: list[NineGridMeta] = Field(default_factory=list)
