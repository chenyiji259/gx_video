"""可灵 AI（Kling AI）视频生成适配器。

来源文档：doc 09 任务 11-01

支持模式：
  - image_to_video：图片转视频（起始帧约束）
  - text_to_video：文本直接生成视频

API 认证：
  Kling 使用 access_key + secret_key 签发 JWT Token，
  所有凭据从 get_config().external_apis.kling_ai 读取，绝不使用 os.getenv()。

Kling API 文档：https://docs.klingai.com
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

# JWT 有效期 1800s（参数中设置），超过 1500s 刷新 token（为 5 分钟配置留缓冲）
_TOKEN_REFRESH_SECS: int = 1500

import httpx

from app.core.config import get_config
from app.core.logging import get_logger
from app.core.provider_registry import get_provider_registry
from app.providers.video.base import VideoGenerationError, VideoGenerationMode, VideoResult

_logger = get_logger("kling_adapter", layer="tool")

# Kling API 端点路径
_ENDPOINTS: dict[str, str] = {
    "image_to_video": "/v1/videos/image2video",
    "text_to_video": "/v1/videos/text2video",
}


class KlingAdapter:
    """Kling AI 视频生成适配器，实现 VideoProviderAdapter 协议。

    用法：
        adapter = KlingAdapter("kling_v2")
        result = await adapter.generate(
            "cinematic slow push-in, rain night street",
            mode="image_to_video",
            reference_image_url="https://...",
            params={"duration": 5},
        )
    """

    def __init__(self, provider_name: str = "kling_v2") -> None:
        self._provider_name = provider_name
        cfg = get_config()
        kling_cfg = cfg.external_apis.kling_ai
        self._access_key = kling_cfg.access_key
        self._secret_key = kling_cfg.secret_key
        self._base_url = kling_cfg.base_url.rstrip("/")
        self._timeout = kling_cfg.timeout
        self._poll_interval = kling_cfg.poll_interval
        self._max_poll_attempts = kling_cfg.max_poll_attempts

        # 从 ProviderRegistry 读取默认参数
        registry = get_provider_registry()
        try:
            self._profile = registry.get("video", provider_name)
            self._default_params: dict[str, Any] = dict(self._profile.default_params)
        except (KeyError, AttributeError):
            self._profile = None
            self._default_params = {"duration": 5, "cfg_scale": 0.5}

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        mode: VideoGenerationMode,
        *,
        negative_prompt: Optional[str] = None,
        reference_image_url: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> VideoResult:
        """调用 Kling AI API 生成视频。

        Args:
            prompt:               正向提示词（英文）。
            mode:                 生成模式（image_to_video / text_to_video）。
            negative_prompt:      负向提示词（Kling 支持，但影响较小）。
            reference_image_url:  image_to_video 模式必须提供起始帧 URL。
            params:               覆盖默认参数（duration_sec / cfg_scale 等）。

        Raises:
            VideoGenerationError: API key 缺失、生成失败、超时等。
        """
        if not self._access_key or not self._secret_key:
            raise VideoGenerationError(
                "Kling AI access_key / secret_key 未配置，"
                "请在 config/base/external_apis.yaml 中填写 kling_ai.access_key 和 kling_ai.secret_key",
                code="api_key_missing",
            )

        if mode == "image_to_video" and not reference_image_url:
            raise VideoGenerationError(
                "image_to_video 模式必须提供 reference_image_url",
                code="missing_reference_image",
            )

        if mode not in _ENDPOINTS:
            raise VideoGenerationError(
                f"Kling 不支持的生成模式: {mode!r}",
                code="unsupported_mode",
            )

        # 合并参数
        merged: dict[str, Any] = dict(self._default_params)
        if params:
            merged.update(params)

        # 字段映射（duration_sec → duration，motion_strength → cfg_scale）
        if "duration_sec" in merged:
            merged["duration"] = int(merged.pop("duration_sec"))
        if "motion_strength" in merged:
            merged["cfg_scale"] = float(merged.pop("motion_strength"))

        # 构建请求体
        payload: dict[str, Any] = {
            "prompt": prompt,
            "duration": merged.get("duration", 5),
            "cfg_scale": merged.get("cfg_scale", 0.5),
        }
        if mode == "image_to_video":
            payload["image_url"] = reference_image_url
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        # 宽高比
        aspect_ratio = merged.get("aspect_ratio", "16:9")
        payload["aspect_ratio"] = aspect_ratio

        _logger.info(
            f"Kling 视频生成请求: mode={mode!r} duration={payload['duration']}s "
            f"prompt_len={len(prompt)} provider={self._provider_name!r}",
            event_type="kling_generate_start",
        )

        token = self._build_jwt_token()
        task_id = await self._submit_task(payload, mode, token)
        result = await self._poll_task(task_id, mode, token)

        _logger.info(
            f"Kling 视频生成完成: task_id={task_id!r}",
            event_type="kling_generate_done",
        )
        return result

    # ------------------------------------------------------------------
    # 内部：提交任务
    # ------------------------------------------------------------------

    async def _submit_task(
        self, payload: dict[str, Any], mode: VideoGenerationMode, token: str
    ) -> str:
        """提交视频生成任务，返回 task_id。"""
        url = f"{self._base_url}{_ENDPOINTS[mode]}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                raise VideoGenerationError(
                    f"Kling 提交请求超时（{self._timeout}s）", code="timeout"
                ) from exc
            except httpx.RequestError as exc:
                raise VideoGenerationError(
                    f"Kling 网络请求失败: {exc}", code="network_error"
                ) from exc

            if resp.status_code not in (200, 201, 202):
                raise VideoGenerationError(
                    f"Kling 提交失败 HTTP {resp.status_code}: {resp.text[:300]}",
                    code="api_error",
                )

            data = resp.json()

        # 响应格式：{"code": 0, "data": {"task_id": "...", "task_status": "submitted"}}
        if data.get("code", 0) != 0:
            raise VideoGenerationError(
                f"Kling API 错误: code={data.get('code')} msg={data.get('message', '')}",
                code="api_error",
            )

        task_id = data.get("data", {}).get("task_id") or data.get("task_id")
        if not task_id:
            raise VideoGenerationError(
                "Kling 未返回 task_id", code="missing_task_id"
            )
        _logger.info(
            f"Kling 任务已提交: task_id={task_id!r} mode={mode!r}",
            event_type="kling_task_submitted",
        )
        return str(task_id)

    # ------------------------------------------------------------------
    # 内部：轮询任务
    # ------------------------------------------------------------------

    async def _poll_task(
        self, task_id: str, mode: VideoGenerationMode, token: str
    ) -> VideoResult:
        """轮询任务状态直到完成，返回 VideoResult。轮询期间到期自动刷新 JWT token。"""
        if mode == "image_to_video":
            query_url = (
                f"{self._base_url}/v1/videos/image2video/{task_id}"
            )
        else:
            query_url = (
                f"{self._base_url}/v1/videos/text2video/{task_id}"
            )

        # 记录 token 创建时刻，超过 _TOKEN_REFRESH_SECS 后重新生成
        token_created_at: float = time.time()
        headers = {"Authorization": f"Bearer {token}"}

        for attempt in range(self._max_poll_attempts):
            await asyncio.sleep(self._poll_interval)

            # 到期刷新 JWT token（token 有效期 1800s，超过 1500s 即提前刷新）
            if time.time() - token_created_at >= _TOKEN_REFRESH_SECS:
                token = self._build_jwt_token()
                token_created_at = time.time()
                headers = {"Authorization": f"Bearer {token}"}
                _logger.info(
                    f"Kling JWT token 已刷新: attempt={attempt + 1} task_id={task_id!r}",
                    event_type="kling_token_refreshed",
                )

            async with httpx.AsyncClient(timeout=30) as client:
                try:
                    resp = await client.get(query_url, headers=headers)
                except httpx.RequestError as exc:
                    _logger.warning(
                        f"Kling 轮询网络错误（attempt={attempt + 1}/{self._max_poll_attempts}）"
                        f"，将在下次尝试继续: {exc}",
                        event_type="kling_poll_network_error",
                    )
                    continue

                if resp.status_code != 200:
                    continue

                data = resp.json()

            if data.get("code", 0) != 0:
                raise VideoGenerationError(
                    f"Kling 查询任务失败: {data.get('message', '')}",
                    code="poll_api_error",
                )

            task_data = data.get("data", {})
            status = task_data.get("task_status", "")

            if status == "succeed":
                _logger.info(
                    f"Kling 任务已完成，开始解析结果: task_id={task_id!r}",
                    event_type="kling_task_completed",
                )
                return self._parse_result(task_data)

            if status in ("failed", "cancelled"):
                reason = task_data.get("task_status_msg", status)
                _logger.warning(
                    f"Kling 任务失败: task_id={task_id!r} status={status!r} reason={reason!r}",
                    event_type="kling_task_failed",
                )
                raise VideoGenerationError(
                    f"Kling 任务失败: {reason}", code="task_failed"
                )

            # submitted / processing → 继续等待
            _logger.info(
                f"Kling 轮询 attempt={attempt + 1}/{self._max_poll_attempts} "
                f"status={status!r} task_id={task_id!r}",
                event_type="kling_poll",
            )

        raise VideoGenerationError(
            f"Kling 任务在 "
            f"{self._max_poll_attempts * self._poll_interval}s 内未完成",
            code="timeout",
        )

    # ------------------------------------------------------------------
    # 内部：解析结果
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_result(task_data: dict[str, Any]) -> VideoResult:
        """从 Kling 任务数据中提取 VideoResult。"""
        # 响应格式示例：
        # {"task_id": "...", "task_status": "succeed",
        #  "task_result": {"videos": [{"url": "...", "duration": "5"}]}}
        task_result = task_data.get("task_result", {})
        videos = task_result.get("videos", [])

        if not videos:
            raise VideoGenerationError(
                f"Kling 任务结果中无视频: {str(task_data)[:200]}",
                code="empty_result",
            )

        video = videos[0]
        video_url = video.get("url", "")
        if not video_url:
            raise VideoGenerationError(
                "Kling 返回视频 URL 为空", code="empty_url"
            )

        duration_raw = video.get("duration")
        duration_sec: Optional[float] = None
        if duration_raw is not None:
            try:
                duration_sec = float(duration_raw)
            except (ValueError, TypeError):
                pass

        return VideoResult(
            video_url=video_url,
            duration_sec=duration_sec,
            provider_meta=task_data,
        )

    # ------------------------------------------------------------------
    # 内部：JWT 签名
    # ------------------------------------------------------------------

    def _build_jwt_token(self) -> str:
        """使用 access_key + secret_key 生成 Kling API JWT Token。

        Kling 使用标准 HS256 JWT，payload 格式：
          {"iss": access_key, "exp": now+1800, "nbf": now-5}

        使用 python-jose（项目已有依赖），无需引入 PyJWT。
        """
        from jose import jwt

        now = int(time.time())
        claims = {
            "iss": self._access_key,
            "exp": now + 1800,
            "nbf": now - 5,
        }
        token: str = jwt.encode(claims, self._secret_key, algorithm="HS256")
        return token
