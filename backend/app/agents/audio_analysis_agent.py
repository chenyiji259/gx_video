"""音乐分析 Agent（AudioAnalysisAgent）— Qwen3.5 Omni 多模态版。

职责：
  - 接收音频文件路径，调用 Qwen3.5 Omni 直接分析音频
  - 输出完整的音乐结构摘要 JSON（含段落、和弦、乐器、歌词、情感等）
  - librosa 只负责精确的 beat_map，其余全部由 Omni 完成

不负责：
  - 精确 BPM / beat_map 提取（由 audio_analysis_tool.py 的 librosa 负责）
  - 直接写数据库
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from app.core.config import get_config
from app.core.logging import get_agent_logger
from app.core.prompt_renderer import PromptRenderer
from app.utils.omni_config import load_omni_config

_logger = get_agent_logger("audio_analysis_agent")


# ---------------------------------------------------------------------------
# 字段校验
# ---------------------------------------------------------------------------

# 必填顶层字段
_REQUIRED_TOP_FIELDS: list[str] = [
    "overall_analysis",
    "music_structure_summary",
    "structure_segments",
    "chord_progression",
    "instrumentation",
    "five_second_analysis",
    "lyrics",
    "emotion_arc",
    "editing_guidance",
    "style_caption",
]


def _validate_omni_result(data: dict) -> tuple[bool, list[str]]:
    """校验 Omni 输出的字段完整性。

    Returns:
        (is_valid, missing_fields_list)
    """
    missing: list[str] = []

    # 如果 JSON 解析本身失败
    if not isinstance(data, dict) or data.get("_parse_failed"):
        return False, ["(JSON 解析失败，未能提取有效 JSON对象)"]

    # 顶层必填字段
    for field in _REQUIRED_TOP_FIELDS:
        if field not in data:
            missing.append(field)

    # 嵌套字段校验（仅当父字段存在时）
    oa = data.get("overall_analysis")
    if isinstance(oa, dict):
        for sub in ("genre", "mood", "emotional_curve_graph"):
            if sub not in oa:
                missing.append(f"overall_analysis.{sub}")
    elif "overall_analysis" not in missing:
        missing.append("overall_analysis (必须是对象)")

    lyrics = data.get("lyrics")
    if isinstance(lyrics, dict):
        if "lines" not in lyrics or not isinstance(lyrics["lines"], list):
            missing.append("lyrics.lines (必须是数组)")
    elif "lyrics" not in missing:
        missing.append("lyrics (必须是对象)")

    mss = data.get("music_structure_summary")
    if isinstance(mss, dict):
        if "sections" not in mss or not isinstance(mss["sections"], list):
            missing.append("music_structure_summary.sections (必须是数组)")
    elif "music_structure_summary" not in missing:
        missing.append("music_structure_summary (必须是对象)")

    eg = data.get("editing_guidance")
    if isinstance(eg, dict):
        if "per_section" not in eg or not isinstance(eg["per_section"], list):
            missing.append("editing_guidance.per_section (必须是数组)")
    elif "editing_guidance" not in missing:
        missing.append("editing_guidance (必须是对象)")

    if not isinstance(data.get("structure_segments", []), list):
        missing.append("structure_segments (必须是数组)")

    return len(missing) == 0, missing


def _merge_with_fallback(partial: dict, fallback: dict) -> dict:
    """将部分有效结果与完整充展结构合并，避免丢失已有数据。"""
    result = dict(fallback)
    for k, v in partial.items():
        if v is not None and v != "" and v != [] and v != {}:
            result[k] = v
    return result


def _is_url_accessible(url: str) -> bool:
    """判断 URL 是否可被公网访问（Omni 云端能接收）。

    以下情况判定为不可公网访问，需要降级 base64 模式：
    - URL 为空
    - 以 file:// 开头
    - localhost / 127.x / 10.x / 192.168.x（dev 环境 MinIO）
    """
    if not url:
        return False
    if url.startswith("file://"):
        return False
    for prefix in (
        "http://localhost", "https://localhost",
        "http://127.", "https://127.",
        "http://10.",  "https://10.",
        "http://192.168.", "https://192.168.",
    ):
        if url.lower().startswith(prefix):
            return False
    return url.startswith(("http://", "https://"))


class AudioAnalysisAgent:
    """Qwen3.5 Omni 音频分析 Agent。"""

    def __init__(self) -> None:
        self._cfg = get_config().llm
        self._renderer = PromptRenderer()

    async def run(
        self,
        audio_url: str,
        *,
        audio_file_path: str | None = None,
    ) -> dict[str, Any]:
        """分析音频，返回完整结构化音乐分析 JSON。

        run_with_omni 的公开别名。
        Args:
            audio_url:       MinIO 永久直链 URL。
            audio_file_path: 本地文件路径（URL 不可公网访问时降级用）。
        """
        return await self.run_with_omni(audio_url, audio_file_path=audio_file_path)

    # 最大重试次数（首次 + 2 次修正 = 最多 3 次调用）
    _MAX_RETRIES: int = 2

    async def run_with_omni(
        self,
        audio_url: str,
        *,
        audio_file_path: str | None = None,
    ) -> dict[str, Any]:
        """调用 Qwen3.5 Omni 分析音频，含校验与自动重试。

        16-03：优先用 URL 模式（无需下载）；若 URL 不可公网访问（dev 环境 localhost），
        则降级为 base64 模式（需要 audio_file_path）。

        Args:
            audio_url:       MinIO 永久直链 URL（storage_uri）。
            audio_file_path: 本地文件路径，仅在 URL 降级时使用。

        Returns:
            Omni 返回的结构化分析 JSON。
        """
        # 1. 读取配置
        omni_cfg = load_omni_config()

        # 2. 构建系统提示词
        try:
            system_prompt = self._renderer.render("audio_analysis_system", {})
        except Exception as exc:
            _logger.warning(
                f"Prompt 渲染失败，使用内置提示词: {exc}",
                event_type="prompt_render_failed",
            )
            system_prompt = self._fallback_system_prompt()

        # 3. 16-03：内网/localhost 降级判断，选择 URL 模式或 base64 模式
        _use_url = _is_url_accessible(audio_url)
        if _use_url:
            # URL 模式：官方格式为 input_audio.data = URL
            # 注意：不能用 audio_url 类型（DashScope 不识别），也不能用 input_audio.url
            # 官方文档示例: {"type": "input_audio", "input_audio": {"data": url, "format": "wav"}}
            audio_format = Path(audio_url.split("?")[0]).suffix.lstrip(".") or "wav"
            audio_block: dict = {
                "type": "input_audio",
                "input_audio": {"data": audio_url, "format": audio_format},
            }
        else:
            # base64 降级模式（dev 环境 MinIO 不可公网访问）
            if not audio_file_path:
                _logger.warning(
                    f"Omni 降级：URL {audio_url!r} 不可公网访问且未提供 audio_file_path，返回内建兜底",
                    event_type="omni_fallback_no_file",
                )
                return self._rule_based_fallback()
            audio_b64 = self._encode_audio(audio_file_path)
            audio_format = Path(audio_file_path).suffix.lstrip(".") or "wav"
            # 官方文档：base64 需要加 data:;base64, 前缀
            audio_block = {
                "type": "input_audio",
                "input_audio": {"data": f"data:;base64,{audio_b64}", "format": audio_format},
            }

        # 4. 校验 API Key
        api_key: str = omni_cfg.get("api_key") or self._cfg.api_key
        if not api_key:
            _logger.error(
                "Omni API Key 未配置",
                event_type="omni_no_api_key",
            )
            return self._rule_based_fallback()

        model_name: str = omni_cfg.get("model_name", "qwen-omni-turbo")
        endpoint: str = omni_cfg.get("endpoint") or self._cfg.base_url or ""
        timeout: int = int(omni_cfg.get("timeout", 120))
        max_tokens_omni: int = int(omni_cfg.get("max_tokens", 4096))  # 16-03
        output_modalities: list = omni_cfg.get("output_modalities", ["text"])

        _logger.info(
            f"Omni 音频分析启动: model={model_name!r} "
            f"mode={'url' if _use_url else 'base64'!r} "
            f"audio_format={audio_format!r} max_tokens={max_tokens_omni}",
            event_type="omni_analysis_start",
        )
        # 首次请求文本指令
        _first_instruction = (
            "请对这段音频进行完整的音乐分析，严格按照系统提示词要求输出 JSON。\n"
            "必须包含以下所有顶层字段：\n"
            "overall_analysis, music_structure_summary, structure_segments, "
            "chord_progression, instrumentation, five_second_analysis, "
            "lyrics, emotion_arc, editing_guidance, style_caption\n"
            "【重要】：\n"
            "- 只输出纯 JSON，不要 Markdown 代码块，不要任何解释文字\n"
            "- 第一个字符必须是 {，最后一个字符必须是 }\n"
            "- lyrics.lines 必须是包含 start/end/text 的数组，时间单位为秒\n"
            "- editing_guidance.per_section 必须是数组"
        )

        try:
            # httpx 直调 DashScope 兼容接口，完全绕过 OpenAI SDK 的 content block 序列化。
            # 根因：openai-python SDK 会把 {"type": "input_audio", "input_audio": {"url": ...}}
            # 转换为 {"type": "image_url", "image_url": {"urls": ...}}（urls 而非 url），
            # 导致 DashScope 报 400。httpx 原样发送 JSON，不做任何字段改写。
            import httpx  # noqa: PLC0415

            _base_url = (endpoint or "").rstrip("/")
            _api_url = f"{_base_url}/chat/completions"
            _headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            last_result: dict = {}
            missing_fields: list[str] = []

            async with httpx.AsyncClient(timeout=float(timeout)) as _http:
              for attempt in range(self._MAX_RETRIES + 1):
                if attempt == 0:
                    user_text = _first_instruction
                else:
                    user_text = (
                        f"【第 {attempt + 1} 次，请修正】你的上次输出校验未通过，"
                        f"缺少或格式错误的字段：{missing_fields}\n"
                        "请重新对上述音频进行完整分析，输出满足所有要求的纯 JSON。\n"
                        "- 只输出 {…}，不要任何说明、代码块或前缀文字\n"
                        "- 必须包含全部顶层字段，lyrics.lines 必须是数组"
                    )

                messages = [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            audio_block,
                            {"type": "text", "text": user_text},
                        ],
                    },
                ]

                _body = {
                    "model": model_name,
                    "messages": messages,
                    "modalities": output_modalities,
                    "max_tokens": max_tokens_omni,
                    "temperature": 0.3,
                    # 官方文档明确要求：stream 必须设置为 True，否则会报错
                    "stream": True,
                    "stream_options": {"include_usage": False},
                }
                # 使用流式请求，逐行解析 SSE
                raw_text_parts: list[str] = []
                async with _http.stream("POST", _api_url, headers=_headers, json=_body) as _resp:
                    if not _resp.is_success:
                        _body_bytes = await _resp.aread()
                        _logger.error(
                            f"DashScope API 返回错误: status={_resp.status_code} "
                            f"body={_body_bytes.decode(errors='replace')[:600]}",
                            event_type="omni_api_error_body",
                        )
                        _resp.raise_for_status()
                    async for line in _resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta_content = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content") or ""
                            )
                            if delta_content:
                                raw_text_parts.append(delta_content)
                        except (json.JSONDecodeError, IndexError):
                            pass
                raw_text: str = "".join(raw_text_parts)
                result = _safe_parse_json(raw_text)
                is_valid, missing_fields = _validate_omni_result(result)

                if is_valid:
                    _logger.info(
                        f"Omni 音频分析通过校验 attempt={attempt + 1}",
                        event_type="omni_analysis_done",
                    )
                    return result

                last_result = result
                _logger.warning(
                    f"Omni 输出校验失败 attempt={attempt + 1}/{self._MAX_RETRIES + 1} "
                    f"missing={missing_fields}",
                    event_type="omni_validation_failed",
                )

            # 所有重试均失败：合并已有数据与底底结构
            _logger.error(
                f"Omni 分析在 {self._MAX_RETRIES + 1} 次尝试后仍未通过校验，"
                f"使用 partial+fallback 合并结果。missing={missing_fields}",
                event_type="omni_analysis_all_retries_failed",
            )
            return _merge_with_fallback(last_result, self._rule_based_fallback())

        except Exception as exc:
            _logger.error(
                f"Omni 调用异常: {exc!r}",
                event_type="omni_analysis_failed",
            )
            return self._rule_based_fallback()

    # _load_omni_config 已迁移至 app.utils.omni_config.load_omni_config()，不再重复定义。

    @staticmethod
    def _encode_audio(audio_path: str) -> str:
        """将音频文件编码为 base64 字符串。"""
        with open(audio_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    @staticmethod
    def _fallback_system_prompt() -> str:
        return (
            "你是一个专业的音乐分析专家。请对输入的音频进行全面分析，"
            "输出严格的 JSON 格式，包含以下字段：\n"
            "- overall_analysis: {genre, mood, key_theme, structural_pattern, emotional_arc, emotional_curve_graph: [{time, intensity}]}\n"
            "- music_structure_summary: {bpm, key_scale, time_signature, sections: [{label, start, end, description}]}\n"
            "- structure_segments: [{segment_id, type, start_time, end_time, lyrics, music_analysis, five_second_analysis}]\n"
            "- chord_progression: [{section, chords: [str]}]\n"
            "- instrumentation: [str]\n"
            "- five_second_analysis: [{start, end, energy, mood, instruments: [str], lyrics_fragment}]\n"
            "- lyrics: {language, lines: [{start, end, text}]}\n"
            "- emotion_arc: {overall, segments: [{start, end, emotion, intensity}]}\n"
            "- editing_guidance: {per_section: [{section, shot_duration_range, motion, cut_density}]}\n"
            "- style_caption: str（一句话描述音乐整体风格与氛围，如：电子流行，副歌爆发，情绪激昂）\n"
        )

    @staticmethod
    def _rule_based_fallback() -> dict[str, Any]:
        """Omni 不可用时的兜底空结构。"""
        return {
            "overall_analysis": {
                "genre": "",
                "mood": "",
                "key_theme": "",
                "structural_pattern": "",
                "emotional_arc": "unknown",
                "emotional_curve_graph": [],
            },
            "music_structure_summary": {"bpm": 0, "key_scale": "", "time_signature": "", "sections": []},
            "structure_segments": [],
            "chord_progression": [],
            "instrumentation": [],
            "five_second_analysis": [],
            "lyrics": {"language": "", "lines": []},
            "emotion_arc": {"overall": "unknown", "segments": []},
            "editing_guidance": {"per_section": []},
            "style_caption": "",
            "_generated_by": "rule_fallback",
        }


# ---------------------------------------------------------------------------
# 工具函数（保留原有）
# ---------------------------------------------------------------------------

def _safe_parse_json(content: str) -> dict[str, Any]:
    """三层 JSON 解析：直接解析 → Markdown 代码块提取 → 正则提取。"""
    text = content.strip()

    # 层 1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 层 2: Markdown ```json 代码块
    md_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if md_match:
        try:
            return json.loads(md_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 层 3: 找 {…} 最外层
    brace_match = re.search(r"(\{[\s\S]*\})", text)
    if brace_match:
        try:
            return json.loads(brace_match.group(1))
        except json.JSONDecodeError:
            pass

    # 兜底：包装成文本
    return {"_raw_response": content, "_parse_failed": True}
