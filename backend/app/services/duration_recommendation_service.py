"""时长建议服务。

基于用户需求、平台、受众、风格和真人门禁，返回推荐总时长。
"""
from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from app.core.config import get_config
from app.core.prompt_renderer import PromptRenderer
from app.core.provider_registry import get_provider_registry
from app.utils.json_utils import safe_parse_json


class DurationRecommendationError(Exception):
    """时长建议异常。"""

    def __init__(self, message: str, code: str = "duration_recommendation_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DurationRecommendationService:
    """生成推荐总时长。"""

    def __init__(self) -> None:
        self._renderer = PromptRenderer()

    async def recommend(
        self,
        *,
        user_prompt: str,
        platform: str,
        target_audience: str,
        style_preference: str,
        human_on_camera: bool | None,
    ) -> dict[str, Any]:
        """返回推荐时长及说明。"""
        allowed_shot_durations = self._get_allowed_shot_durations()
        prompt = self._renderer.render(
            "recommend_duration",
            variables={
                "user_prompt": user_prompt or "（未提供）",
                "platform": platform or "未指定",
                "target_audience": target_audience or "未指定",
                "style_preference": style_preference or "未指定",
                "human_on_camera": self._human_text(human_on_camera),
                "allowed_shot_durations_sec": ", ".join(str(item) for item in allowed_shot_durations),
            },
        )

        cfg = get_config()
        if not cfg.llm.api_key:
            return self._fallback(
                user_prompt=user_prompt,
                platform=platform,
                target_audience=target_audience,
                style_preference=style_preference,
                human_on_camera=human_on_camera,
                allowed_shot_durations=allowed_shot_durations,
            )

        try:
            llm = ChatOpenAI(
                model=cfg.llm.model,
                api_key=cfg.llm.api_key,
                base_url=cfg.llm.base_url,
                temperature=0.3,
                max_tokens=800,
                timeout=cfg.llm.timeout,
            )
            response = await llm.ainvoke(prompt)
            raw_text = response.content if hasattr(response, "content") else str(response)
            parsed = safe_parse_json(str(raw_text), fallback={})
        except Exception:
            parsed = {}

        recommended_duration_sec = self._coerce_duration(
            parsed.get("recommended_duration_sec"),
            platform=platform,
            user_prompt=user_prompt,
            human_on_camera=human_on_camera,
        )
        min_sec = max(5, int(parsed.get("min_duration_sec") or max(5, recommended_duration_sec - 15)))
        max_sec = min(600, int(parsed.get("max_duration_sec") or min(600, recommended_duration_sec + 30)))
        if min_sec > recommended_duration_sec:
            min_sec = recommended_duration_sec
        if max_sec < recommended_duration_sec:
            max_sec = recommended_duration_sec

        return {
            "recommended_duration_sec": recommended_duration_sec,
            "min_duration_sec": min_sec,
            "max_duration_sec": max_sec,
            "reason": str(parsed.get("reason") or "已根据内容表达密度、平台和节奏给出建议时长。"),
            "allowed_shot_durations_sec": allowed_shot_durations,
        }

    def _get_allowed_shot_durations(self) -> list[int]:
        registry = get_provider_registry()
        durations = registry.list_supported_durations("video", enabled_only=True)
        return durations or [4, 5, 6, 8, 10, 12, 15]

    @staticmethod
    def _human_text(human_on_camera: bool | None) -> str:
        if human_on_camera is True:
            return "需要真人入镜"
        if human_on_camera is False:
            return "不要真人入镜"
        return "未指定"

    def _coerce_duration(
        self,
        raw_value: Any,
        *,
        platform: str,
        user_prompt: str,
        human_on_camera: bool | None,
    ) -> int:
        try:
            if raw_value is not None:
                value = int(float(raw_value))
                if 5 <= value <= 600:
                    return value
        except (TypeError, ValueError):
            pass

        fallback = self._fallback(
            user_prompt=user_prompt,
            platform=platform,
            target_audience="",
            style_preference="",
            human_on_camera=human_on_camera,
            allowed_shot_durations=self._get_allowed_shot_durations(),
        )
        return int(fallback["recommended_duration_sec"])

    def _fallback(
        self,
        *,
        user_prompt: str,
        platform: str,
        target_audience: str,
        style_preference: str,
        human_on_camera: bool | None,
        allowed_shot_durations: list[int],
    ) -> dict[str, Any]:
        text = " ".join(
            part for part in [
                user_prompt or "",
                target_audience or "",
                style_preference or "",
                platform or "",
            ] if part
        ).lower()
        recommended = 45
        if any(keyword in text for keyword in ("教程", "讲解", "解说", "科普", "explainer", "tutorial", "guide")):
            recommended = 60
        elif any(keyword in text for keyword in ("广告", "带货", "宣传", "promo", "ad", "commercial", "品牌")):
            recommended = 30
        elif any(keyword in text for keyword in ("剧情", "故事", "drama", "story", "角色")):
            recommended = 75
        elif any(keyword in text for keyword in ("氛围", "mv", "visual", "mood", "music video")):
            recommended = 45

        if human_on_camera is True:
            recommended += 15
        if (platform or "").lower() in {"tiktok", "youtube_shorts", "xiaohongshu"}:
            recommended = min(recommended, 60)

        return {
            "recommended_duration_sec": max(5, min(600, recommended)),
            "min_duration_sec": max(5, min(600, recommended - 15)),
            "max_duration_sec": max(5, min(600, recommended + 30)),
            "reason": "已按内容类型、平台与表达复杂度给出兜底建议时长。",
            "allowed_shot_durations_sec": allowed_shot_durations,
        }
