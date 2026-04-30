"""成本估算服务（Cost Estimation Service）。

来源文档：doc 09 任务 11-02

职责：
  基于 config/base/billing.yaml 中的定价规则，
  根据工具类型和执行参数（时长/分辨率）估算 credits 消耗。

计费规则（来自 billing.yaml）：
  - audio_analysis:          per_30_seconds × 2
  - generate_storyboard_frame: per_frame × 2
  - image_to_video:          per_second × 15
  - text_to_video:           per_second × 20
  - regenerate_shot:         per_second × 15
  - export_720p:             per_minute × 20
  - export_1080p:            per_minute × 40
  - export_2K/export_4K:      optional config; fallback multiplier if absent

设计：
  所有计算为纯函数，不访问数据库，不需要异步。
  调用方需要在执行前用 estimate_*() 告知用户预期消耗。
"""
from __future__ import annotations

import math
from typing import Literal

from app.core.config import get_config


ExportResolution = Literal["720p", "1080p", "2K", "4K"]


class CostEstimationService:
    """基于 billing 配置估算 credits 消耗。"""

    def estimate_audio_analysis(self, duration_sec: float) -> int:
        """估算音频分析 credits。

        Args:
            duration_sec: 音频时长（秒）。

        Returns:
            预计 credits（向上取整）。
        """
        cfg = get_config().billing.tools.get("audio_analysis")
        if not cfg:
            return 0
        units = math.ceil(duration_sec / 30.0)
        return max(1, units) * int(cfg.price_per_unit)

    def estimate_storyboard_frame(self, frame_count: int) -> int:
        """估算 storyboard 生成 credits。

        Args:
            frame_count: 帧数。
        """
        cfg = get_config().billing.tools.get("generate_storyboard_frame")
        if not cfg:
            return 0
        return frame_count * int(cfg.price_per_unit)

    def estimate_video_generation(
        self,
        duration_sec: float,
        mode: Literal["image_to_video", "text_to_video", "regenerate_shot"] = "image_to_video",
    ) -> int:
        """估算视频生成 credits。

        Args:
            duration_sec: 视频时长（秒）。
            mode:         生成模式。

        Returns:
            预计 credits（向上取整到整秒）。
        """
        tool_name = mode  # billing.yaml key 与 mode 一致
        cfg = get_config().billing.tools.get(tool_name)
        if not cfg:
            return 0
        units = math.ceil(duration_sec)
        return max(1, units) * int(cfg.price_per_unit)

    def estimate_export(
        self,
        duration_sec: float,
        resolution: ExportResolution = "720p",
    ) -> int:
        """估算导出 credits。

        Args:
            duration_sec: 视频时长（秒）。
            resolution:   导出分辨率。

        Returns:
            预计 credits（向上取整到整分钟，至少 1 分钟）。
        """
        tool_name = f"export_{resolution}"
        cfg = get_config().billing.tools.get(tool_name)
        minutes = max(1, math.ceil(duration_sec / 60.0))
        if cfg:
            return minutes * int(cfg.price_per_unit)

        fallback_price = {
            "720p": 20,
            "1080p": 40,
            "2K": 80,
            "4K": 160,
        }.get(resolution, 40)
        return minutes * fallback_price

    def estimate_clips_batch(
        self,
        shot_count: int,
        avg_duration_sec: float,
        mode: Literal["image_to_video", "text_to_video"] = "image_to_video",
    ) -> int:
        """估算批量 clip 生成 credits。

        Args:
            shot_count:        需要生成的 shot 数量。
            avg_duration_sec:  平均每个 shot 的时长（秒）。
            mode:              生成模式。
        """
        per_shot = self.estimate_video_generation(avg_duration_sec, mode)
        return per_shot * shot_count

    def estimate_lipsync(self, duration_sec: float) -> int:
        """估算 LipSync 生成 credits。

        Args:
            duration_sec: 视频时长（秒）。

        Returns:
            预计 credits（向上取整到整秒）。
        """
        cfg = get_config().billing.tools.get("lipsync")
        if not cfg:
            # billing.yaml 未配置 lipsync 时，参考 image_to_video 价格兜底
            img_cfg = get_config().billing.tools.get("image_to_video")
            if not img_cfg:
                return 0
            price = int(img_cfg.price_per_unit)
        else:
            price = int(cfg.price_per_unit)
        units = max(1, math.ceil(duration_sec))
        return units * price

    def get_free_quota(self) -> int:
        """返回新用户免费 credits 配额。"""
        return get_config().billing.free_quota_per_user
