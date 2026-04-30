"""Provider 注册中心（Provider Registry）。

工程约束（doc 06 / doc 08）：
  provider 能力矩阵必须先固定，否则 Prompt Compiler 和 Tool 层后面会耦合炸掉。
  provider 硬参数（分辨率上限、价格系数）放在配置里，不写在提示词里。

Provider 类型：
  image    — 图片生成（参考图、storyboard frame）
  video    — 视频生成（image-to-video、text-to-video）
  audio    — 音频分析（BPM、beat、歌词对齐）
  lipsync  — 口型生成（演唱镜头）

用法：
    from app.core.provider_registry import get_provider_registry

    reg = get_provider_registry()
    provider = reg.get("video", "kling_v2")
    print(provider.capabilities)

    # 获取当前 enabled 的默认 provider
    default_video = reg.get_default("video")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #

@dataclass
class ProviderCapabilities:
    """Provider 能力描述。"""
    raw: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def __getattr__(self, item: str) -> Any:
        try:
            return self.raw[item]
        except KeyError:
            raise AttributeError(f"ProviderCapabilities 没有字段 '{item}'")


@dataclass
class ProviderProfile:
    """单个 Provider 的完整描述。"""
    name: str
    display_name: str
    provider_type: str           # image | video | audio | lipsync
    enabled: bool
    api_type: str                # fal_ai | replicate | kling_ai | local_python ...
    endpoint: str
    pricing_ref: str             # 对应 billing.yaml 中的 tool key
    capabilities: ProviderCapabilities
    default_params: dict[str, Any] = field(default_factory=dict)
    field_mapping: dict[str, str] = field(default_factory=dict)
    generation_modes: list[str] = field(default_factory=list)
    prompt_style: str = "natural"  # natural | keyword_stack | structured
    notes: str = ""
    model_name: str = ""           # DashScope 等需要在 payload 中传递的实际模型名称


# --------------------------------------------------------------------------- #
# 注册中心
# --------------------------------------------------------------------------- #

_PROVIDER_FILES = {
    "image":   "image_providers.yaml",
    "video":   "video_providers.yaml",
    "audio":   "audio_providers.yaml",
    "lipsync": "lipsync_providers.yaml",
}

_LIST_KEYS = {
    "image":   "image_providers",
    "video":   "video_providers",
    "audio":   "audio_providers",
    "lipsync": "lipsync_providers",
}


class ProviderRegistry:
    """Provider 注册中心，加载并索引所有 provider 配置。

    数据结构：
        _profiles: dict[type, dict[name, ProviderProfile]]
    """

    def __init__(self, profiles: dict[str, dict[str, ProviderProfile]]) -> None:
        self._profiles = profiles

    @classmethod
    def load(cls, providers_dir: Optional[Path] = None) -> "ProviderRegistry":
        """从 config/providers/ 目录加载所有 provider YAML 文件。"""
        if providers_dir is None:
            providers_dir = (
                Path(__file__).parent.parent.parent.parent / "config" / "providers"
            )

        if not providers_dir.exists():
            raise FileNotFoundError(
                f"Provider 配置目录不存在: {providers_dir}\n"
                "请确认 config/providers/ 目录存在。"
            )

        profiles: dict[str, dict[str, ProviderProfile]] = {}

        for provider_type, filename in _PROVIDER_FILES.items():
            file_path = providers_dir / filename
            if not file_path.exists():
                profiles[provider_type] = {}
                continue

            data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
            list_key = _LIST_KEYS[provider_type]
            raw_list = data.get(list_key, []) or []

            profiles[provider_type] = {}
            for item in raw_list:
                name = item["name"]
                profile = ProviderProfile(
                    name=name,
                    display_name=item.get("display_name", name),
                    provider_type=provider_type,
                    enabled=item.get("enabled", False),
                    api_type=item.get("api_type", ""),
                    endpoint=item.get("endpoint", ""),
                    pricing_ref=item.get("pricing_ref", ""),
                    capabilities=ProviderCapabilities(item.get("capabilities") or {}),
                    default_params=item.get("default_params") or {},
                    field_mapping=item.get("field_mapping") or {},
                    generation_modes=item.get("generation_modes") or [],
                    prompt_style=item.get("prompt_style", "natural"),
                    notes=item.get("notes", ""),
                    model_name=item.get("model_name", ""),
                )
                profiles[provider_type][name] = profile

        return cls(profiles)

    # ------------------------------------------------------------------ #
    # 查询 API
    # ------------------------------------------------------------------ #

    def get(self, provider_type: str, name: str) -> ProviderProfile:
        """按类型和名称获取 provider，不存在时抛出明确异常。"""
        type_profiles = self._profiles.get(provider_type, {})
        profile = type_profiles.get(name)
        if profile is None:
            available = sorted(type_profiles.keys())
            raise KeyError(
                f"Provider '{name}' (type={provider_type}) 不存在。\n"
                f"当前已加载的 {provider_type} providers：{available}"
            )
        return profile

    def get_default(self, provider_type: str) -> Optional[ProviderProfile]:
        """获取指定类型中第一个 enabled 的 provider。"""
        for profile in self._profiles.get(provider_type, {}).values():
            if profile.enabled:
                return profile
        return None

    def select_for_duration(
        self,
        provider_type: str,
        duration_sec: float,
    ) -> Optional[ProviderProfile]:
        """根据目标时长选择最佳 provider。

        优先级：
          1. 有 supported_durations 列表且时长精确命中的 provider
          2. 无 supported_durations 但时长在 [min_duration_sec, max_duration_sec] 内的 provider
          3. 都不满足时，退回 get_default()

        设计意图：
          - 未来接入更多视频模型时，只需在 YAML 中声明 supported_durations，
            此方法自动路由到能力匹配的最优 provider，无需修改代码。
        """
        exact_matches: list[ProviderProfile] = []
        range_matches: list[ProviderProfile] = []

        for profile in self._profiles.get(provider_type, {}).values():
            if not profile.enabled:
                continue
            supported: list | None = profile.capabilities.get("supported_durations")
            if supported is not None:
                # 精确档位匹配（支持整数/浮点混用）
                if duration_sec in [float(d) for d in supported]:
                    exact_matches.append(profile)
            else:
                # 范围匹配
                min_d = float(profile.capabilities.get("min_duration_sec", 0))
                max_d = float(profile.capabilities.get("max_duration_sec", 9999))
                if min_d <= duration_sec <= max_d:
                    range_matches.append(profile)

        if exact_matches:
            return exact_matches[0]
        if range_matches:
            return range_matches[0]
        return self.get_default(provider_type)

    def list_providers(
        self,
        provider_type: str,
        *,
        enabled_only: bool = False,
    ) -> list[ProviderProfile]:
        """列出指定类型的所有 provider。"""
        profiles = list(self._profiles.get(provider_type, {}).values())
        if enabled_only:
            profiles = [p for p in profiles if p.enabled]
        return profiles

    def list_supported_durations(
        self,
        provider_type: str,
        *,
        enabled_only: bool = True,
        provider_name: str | None = None,
    ) -> list[int]:
        """列出 provider 支持的离散时长档位（秒）。"""
        profiles: list[ProviderProfile]
        if provider_name:
            try:
                profile = self.get(provider_type, provider_name)
            except KeyError:
                return []
            profiles = [profile]
        else:
            profiles = self.list_providers(provider_type, enabled_only=enabled_only)

        durations: set[int] = set()
        for profile in profiles:
            supported = profile.capabilities.get("supported_durations")
            if supported:
                for duration in supported:
                    try:
                        durations.add(int(float(duration)))
                    except (TypeError, ValueError):
                        continue

        return sorted(durations)

    def normalize_duration(
        self,
        provider_type: str,
        duration_sec: float,
        *,
        provider_name: str | None = None,
        enabled_only: bool = True,
    ) -> tuple[int, ProviderProfile | None]:
        """将时长吸附到 provider 支持的最近档位，并返回匹配到的 provider。"""

        def _normalize_for_profile(profile: ProviderProfile, requested: float) -> int | None:
            supported = profile.capabilities.get("supported_durations")
            if supported:
                candidates: list[int] = []
                for item in supported:
                    try:
                        candidates.append(int(float(item)))
                    except (TypeError, ValueError):
                        continue
                if not candidates:
                    return None
                # 距离相同时优先取更短时长，避免无意把总时长拉长
                return min(candidates, key=lambda candidate: (abs(candidate - requested), candidate))

            min_d = profile.capabilities.get("min_duration_sec")
            max_d = profile.capabilities.get("max_duration_sec")
            if min_d is None and max_d is None:
                return None
            low = int(float(min_d or requested))
            high = int(float(max_d or requested))
            clamped = max(low, min(int(round(requested)), high))
            return clamped

        if provider_name:
            try:
                profile = self.get(provider_type, provider_name)
            except KeyError:
                return int(round(duration_sec)), None
            normalized = _normalize_for_profile(profile, duration_sec)
            return normalized if normalized is not None else int(round(duration_sec)), profile

        profiles = self.list_providers(provider_type, enabled_only=enabled_only)
        if not profiles:
            return int(round(duration_sec)), None

        best_profile: ProviderProfile | None = None
        best_duration: int | None = None
        best_score: tuple[float, int] | None = None

        for profile in profiles:
            normalized = _normalize_for_profile(profile, duration_sec)
            if normalized is None:
                continue
            score = (abs(normalized - duration_sec), normalized)
            if best_score is None or score < best_score:
                best_score = score
                best_duration = normalized
                best_profile = profile

        if best_duration is None:
            return int(round(duration_sec)), self.get_default(provider_type)
        return best_duration, best_profile

    def list_all(self) -> dict[str, list[ProviderProfile]]:
        """返回所有类型的所有 provider。"""
        return {t: list(ps.values()) for t, ps in self._profiles.items()}

    def supports_mode(
        self,
        provider_type: str,
        name: str,
        mode: str,
    ) -> bool:
        """检查某个 provider 是否支持指定的生成模式。"""
        try:
            profile = self.get(provider_type, name)
            return mode in profile.generation_modes
        except KeyError:
            return False

    def get_for_mode(
        self,
        provider_type: str,
        mode: str,
    ) -> Optional[ProviderProfile]:
        """按生成模式查找第一个 enabled 且支持该模式的 provider。

        例：get_for_mode("image", "text_to_image") → qwen_txt2img profile
        找不到时返回 None。
        """
        for profile in self._profiles.get(provider_type, {}).values():
            if profile.enabled and mode in profile.generation_modes:
                return profile
        return None

    def __repr__(self) -> str:
        summary = {t: len(ps) for t, ps in self._profiles.items()}
        return f"ProviderRegistry({summary})"


# 全局单例，懒加载
_registry: Optional[ProviderRegistry] = None


def get_provider_registry() -> ProviderRegistry:
    """返回全局 ProviderRegistry 单例。首次调用时加载配置文件。"""
    global _registry
    if _registry is None:
        _registry = ProviderRegistry.load()
    return _registry
