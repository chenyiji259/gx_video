"""共享工具层 — 产物引用协议（ArtifactRef Protocol）。

来源文档：docs/12 偏差 6 §6.2.2 + §6.2.3

核心原则：Agent 之间只传 ArtifactRef（引用），不传产物原文内容。
所有产物生成后必须：
  1. 写入本地文件（data/projects/{id}/ 对应阶段目录）
  2. 上传 MinIO（失败时不阻断业务，可降级本地读取）
  3. 落库 Asset 记录（assets 表，含 metadata_）
  4. 返回 ArtifactRef 引用对象

调用者：
  - Director Agent（read_artifact 主动审核产物）
  - Sub-agent（read_artifact 读取上游产物 / write_artifact 写出产物）
  - dispatch_agent 内的上下文加载辅助（build_ref_from_asset_latest）

统一协议（P6-03 收口，与 docs/12 §6.2.2 对齐）：
  write_artifact    — 本地落盘 + MinIO 上传 + Asset 落库（返回 DB-backed ArtifactRef）
  read_artifact     — 优先本地文件，降级 MinIO
  build_ref_from_asset_latest — 从 Asset 表重建 ArtifactRef（供 dispatch_agent 使用）

注意：文本产物同时由版本表（creative_brief_versions / narrative_script_versions 等）
管理，Asset 记录是额外的引用索引，两者并存，不互相替代。
"""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Optional

from app.core.logging import get_logger
from app.models.asset import Asset
from app.repositories.asset_repository import AssetRepository
from app.repositories.unit_of_work import UnitOfWork
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.path_planner import ArtifactStage
from app.utils.ids import generate_ulid

_logger = get_logger("tools.shared.artifact_tools", layer="tool")

# ---------------------------------------------------------------------------
# artifact_type → ArtifactStage 映射
# ---------------------------------------------------------------------------

_ARTIFACT_TYPE_TO_STAGE: dict[str, str] = {
    "audio_analysis":    ArtifactStage.AUDIO_ANALYSIS,
    "creative_brief":    ArtifactStage.BRIEF,
    "style_bible":       ArtifactStage.STYLE,
    "narrative_script":  ArtifactStage.BRIEF,     # 叙事剧本放 03_brief/
    "shot_plan":         ArtifactStage.SHOT_PLAN,
    "scene_plan":        ArtifactStage.SHOT_PLAN,
    "visual_bible":      ArtifactStage.STYLE,      # 视觉圣经放 04_style/
    "storyboard":        ArtifactStage.STORYBOARD,
    "prompt_bundle":     ArtifactStage.PROMPT_BUNDLES,
    "timeline":          ArtifactStage.TIMELINE,
}


# ---------------------------------------------------------------------------
# ArtifactRef 构造辅助
# ---------------------------------------------------------------------------

def make_artifact_ref(
    artifact_type: str,
    local_path: Path,
    version_no: int,
    *,
    asset_id: str = "",
    summary: str = "",
    minio_uri: str = "",
) -> dict:
    """构造标准 ArtifactRef dict。

    ArtifactRef 结构：
      artifact_id   — 版本标识，如 "creative_brief_v1"
      artifact_type — 产物类型
      local_path    — 本地文件路径（字符串，便于 JSON 序列化）
      minio_uri     — MinIO 永久直链（可为空）
      version_no    — 版本号
      summary       — 简短摘要，不含全文
    """
    return {
        "artifact_id":   f"{artifact_type}_v{version_no}",
        "artifact_type": artifact_type,
        "asset_id":      asset_id,
        "local_path":    str(local_path),
        "minio_uri":     minio_uri,
        "version_no":    version_no,
        "summary":       summary,
    }


def _artifact_metadata(
    *,
    artifact_type: str,
    version_no: int,
    summary: str,
    local_path: Path,
) -> dict:
    return {
        "artifact_id": f"{artifact_type}_v{version_no}",
        "artifact_type": artifact_type,
        "version_no": version_no,
        "summary": summary,
        "local_path": str(local_path),
    }


def _build_ref_from_asset(asset: Asset, *, summary: str = "") -> dict:
    metadata = asset.metadata_ or {}
    artifact_type = metadata.get("artifact_type") or asset.asset_type
    version_no = int(metadata.get("version_no") or 1)
    local_path = Path(metadata.get("local_path") or asset.storage_uri or "")
    resolved_summary = summary or metadata.get("summary") or ""
    return make_artifact_ref(
        artifact_type=artifact_type,
        local_path=local_path,
        version_no=version_no,
        asset_id=asset.id,
        summary=resolved_summary,
        minio_uri=asset.storage_uri,
    )


async def _persist_artifact_asset(
    *,
    project_id: str,
    artifact_type: str,
    version_no: int,
    local_path: Path,
    summary: str,
    object_key: str,
    minio_uri: str,  # DESIGN-10: minio_uri 必须为有效 MinIO URL，调用前已经确保上传成功
) -> dict:
    """DESIGN-10 修复：仅在 MinIO 上传成功后才调用此方法。

    Asset 表仅登记已成功上传 MinIO 的资产，确保 storage_uri 是
    有效的 MinIO 永久直链，供前端展示使用。
    """
    from app.storage.minio_adapter import get_storage
    storage = get_storage()
    bucket_name = storage.default_bucket

    file_bytes = local_path.read_bytes()
    asset_id = generate_ulid()
    metadata = _artifact_metadata(
        artifact_type=artifact_type,
        version_no=version_no,
        summary=summary,
        local_path=local_path,
    )

    async with UnitOfWork() as uow:
        repo = AssetRepository(uow.session)
        asset = Asset(
            id=asset_id,
            project_id=project_id,
            asset_type=artifact_type,
            bucket_name=bucket_name,
            object_key=object_key,
            storage_uri=minio_uri,
            mime_type="application/json",
            size_bytes=len(file_bytes),
            sha256=sha256(file_bytes).hexdigest(),
            metadata_=metadata,
        )
        await repo.add(asset)
        await uow.flush()
        await uow.session.refresh(asset)

    return _build_ref_from_asset(asset, summary=summary)


# ---------------------------------------------------------------------------
# read_artifact — 读取产物内容
# ---------------------------------------------------------------------------

async def read_artifact(artifact_ref: dict) -> dict:
    """从本地文件读取产物 JSON 内容。

    优先读取 local_path（本地文件），若不存在则尝试 MinIO 降级。

    Args:
        artifact_ref: ArtifactRef dict，至少含 local_path 或 minio_uri 之一。

    Returns:
        产物完整内容（JSON dict）。

    Raises:
        FileNotFoundError: 本地文件和 MinIO 均不可读时抛出。
    """
    artifact_id = artifact_ref.get("artifact_id", "unknown")
    local_path_str = artifact_ref.get("local_path", "")

    # 优先：本地文件（精确路径）
    if local_path_str:
        local_path = Path(local_path_str)
        if local_path.exists():
            try:
                content = json.loads(local_path.read_text(encoding="utf-8"))
                _logger.debug(
                    f"read_artifact 本地读取: {artifact_id!r} path={local_path_str!r}",
                    event_type="artifact_read_local",
                )
                return content
            except (json.JSONDecodeError, OSError) as exc:
                _logger.warning(
                    f"read_artifact 本地文件读取失败: {artifact_id!r} exc={exc!r}",
                    event_type="artifact_read_local_failed",
                )

        # 精确路径不存在 → 尝试同目录下按 artifact_type 前缀匹配最新文件
        artifact_type = artifact_ref.get("artifact_type", "")
        if artifact_type and local_path.parent.exists():
            candidates = sorted(local_path.parent.glob(f"{artifact_type}*.json"))
            if candidates:
                fallback_path = candidates[-1]
                _logger.info(
                    f"read_artifact 精确路径不存在，降级到同目录最新文件: "
                    f"{fallback_path.name} (原路径: {local_path.name})",
                    event_type="artifact_read_local_fallback",
                )
                try:
                    content = json.loads(
                        fallback_path.read_text(encoding="utf-8")
                    )
                    return content
                except (json.JSONDecodeError, OSError) as exc:
                    _logger.warning(
                        f"read_artifact 降级文件读取失败: {exc!r}",
                        event_type="artifact_read_local_fallback_failed",
                    )

    # 降级：MinIO 下载
    minio_uri = artifact_ref.get("minio_uri", "")
    if minio_uri:
        try:
            from app.storage.minio_adapter import get_storage
            storage = get_storage()
            # minio_uri 格式: http://host/bucket/object_key
            # 提取 object_key：去掉协议 + host + bucket 三段
            parts = minio_uri.split("/", 4)  # ['http:', '', 'host', 'bucket', 'key...']
            if len(parts) >= 5:
                object_key = parts[4]
                import asyncio
                data_bytes = await asyncio.to_thread(storage.download_bytes, object_key)
                content = json.loads(data_bytes.decode("utf-8"))
                _logger.info(
                    f"read_artifact MinIO 降级读取: {artifact_id!r}",
                    event_type="artifact_read_minio",
                )
                return content
        except Exception as exc:
            _logger.warning(
                f"read_artifact MinIO 降级失败: {artifact_id!r} exc={exc!r}",
                event_type="artifact_read_minio_failed",
            )

    raise FileNotFoundError(
        f"产物 {artifact_id!r} 不可读：本地文件不存在且 MinIO 降级失败。"
        f" local_path={local_path_str!r} minio_uri={minio_uri!r}"
    )


# ---------------------------------------------------------------------------
# write_artifact — 写出产物并返回 ArtifactRef
# ---------------------------------------------------------------------------

async def write_artifact(
    content: dict,
    project_id: str,
    artifact_type: str,
    version_no: int,
    *,
    summary: str = "",
    upload_to_minio: bool = True,
) -> dict:
    """将产物写入本地文件（可选上传 MinIO），返回 ArtifactRef。

    用于 Sub-agent 完成生成后持久化产物。
    文本产物会额外登记 Asset 记录，返回 DB-backed ArtifactRef。

    Args:
        content:         产物 JSON 内容。
        project_id:      项目 ID。
        artifact_type:   产物类型（用于路径映射和 artifact_id 生成）。
        version_no:      版本号。
        summary:         产物摘要（不含全文，写入 ArtifactRef）。
        upload_to_minio: 是否上传 MinIO（默认 True，失败不阻塞业务）。

    Returns:
        ArtifactRef dict。
    """
    store = LocalArtifactStore(project_id)
    stage = _ARTIFACT_TYPE_TO_STAGE.get(artifact_type, ArtifactStage.BRIEF)

    # 写本地文件，文件名：{artifact_type}_v{version_no}_{timestamp}.json
    local_path = store.write_json(
        stage, artifact_type, content, version=version_no
    )

    _logger.info(
        f"write_artifact 本地写入: {artifact_type!r} v{version_no} "
        f"project={project_id!r} path={local_path!r}",
        event_type="artifact_written_local",
    )

    # DESIGN-10 修复：仅在 MinIO 上传成功时才写入 Asset 表。
    # 上传失败时返回本地 ArtifactRef，不写任何 Asset 记录（避免前端收到无法访问的本地路径）。
    if not upload_to_minio:
        local_ref = make_artifact_ref(
            artifact_type, local_path, version_no, summary=summary
        )
        _logger.debug(
            f"write_artifact 完成（仅本地）: artifact_id={local_ref['artifact_id']!r}",
            event_type="artifact_write_done",
        )
        return local_ref

    try:
        from app.storage.minio_adapter import get_storage
        storage = get_storage()
        object_key = (
            f"projects/{project_id}/artifacts/"
            f"{artifact_type}/v{version_no}/{local_path.name}"
        )
        file_bytes = local_path.read_bytes()
        await storage.async_upload_bytes(
            object_key, file_bytes, content_type="application/json"
        )
        minio_uri = storage.get_permanent_url(object_key)
        _logger.info(
            f"write_artifact MinIO 上传成功: {artifact_type!r} key={object_key!r}",
            event_type="artifact_uploaded_minio",
        )
        # MinIO 成功→写 Asset 表，返回 DB-backed ArtifactRef
        ref = await _persist_artifact_asset(
            project_id=project_id,
            artifact_type=artifact_type,
            version_no=version_no,
            local_path=local_path,
            summary=summary,
            object_key=object_key,
            minio_uri=minio_uri,
        )
        _logger.debug(
            f"write_artifact 完成: artifact_id={ref['artifact_id']!r}",
            event_type="artifact_write_done",
        )
        return ref
    except Exception as exc:
        # MinIO 失败→不写 Asset 记录，仅返回本地引用
        _logger.warning(
            f"write_artifact MinIO 上传失败，返回本地 ArtifactRef（Asset 表未写入）: {exc!r}",
            event_type="artifact_minio_upload_failed",
        )
        local_ref = make_artifact_ref(
            artifact_type, local_path, version_no, summary=summary
        )
        _logger.debug(
            f"write_artifact 完成（本地降级）: artifact_id={local_ref['artifact_id']!r}",
            event_type="artifact_write_done",
        )
        return local_ref


# ---------------------------------------------------------------------------
# get_asset_url — 查询媒体资产永久 URL
# ---------------------------------------------------------------------------

async def get_asset_url(asset_id: str) -> str:
    """根据 asset_id 查询媒体资产的永久 URL（MinIO 直链）。

    用途：Sub-agent 需要把已存在的角色图/场景图 URL 传给生成工具时调用。

    Args:
        asset_id: Asset 表记录的 ID。

    Returns:
        storage_uri 永久直链字符串；查询失败或不存在时返回空字符串。
    """
    try:
        from app.repositories.asset_repository import AssetRepository
        from app.repositories.unit_of_work import UnitOfWork

        async with UnitOfWork() as uow:
            asset = await AssetRepository(uow.session).get_by_id(asset_id)

        if asset is None:
            return ""
        return asset.storage_uri or ""

    except Exception as exc:
        _logger.warning(
            f"get_asset_url 查询失败: asset_id={asset_id!r} exc={exc!r}",
            event_type="get_asset_url_failed",
        )
        return ""


# ---------------------------------------------------------------------------
# 辅助：从已有 LocalArtifactStore 写出的最新文件构建 ArtifactRef
# 供 Batch A 节点调用（服务已写文件，节点只需读路径）
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Batch B: @tool wrappers — 供 create_react_agent 使用的工具包装
# ---------------------------------------------------------------------------
try:
    from langchain_core.tools import tool as _lc_tool

    @_lc_tool
    async def read_artifact_tool(artifact_ref_json: str) -> str:
        """Read artifact content from local file or MinIO by ArtifactRef.

        Pass the ArtifactRef as a JSON string.
        Returns the full artifact content as a JSON string.
        On failure, returns {"error": "...", "content": {}}.
        """
        try:
            ref = json.loads(artifact_ref_json)
            content = await read_artifact(ref)
            return json.dumps(content, ensure_ascii=False)
        except Exception as exc:
            _logger.warning(
                f"read_artifact_tool 失败: {exc!r}",
                event_type="read_artifact_tool_failed",
            )
            return json.dumps({"error": str(exc), "content": {}})

    @_lc_tool
    async def write_artifact_tool(
        content_json: str,
        project_id: str,
        artifact_type: str,
        version_no: int,
        summary: str = "",
    ) -> str:
        """Persist artifact content to local file and MinIO, return ArtifactRef JSON.

        Args:
            content_json: artifact content as a JSON string.
            project_id: the project ID.
            artifact_type: creative_brief / style_bible / narrative_script / shot_plan.
            version_no: version number for this artifact.
            summary: brief summary (not full content).

        Returns ArtifactRef as a JSON string with artifact_id, local_path, etc.
        """
        try:
            content = json.loads(content_json)
            ref = await write_artifact(
                content=content,
                project_id=project_id,
                artifact_type=artifact_type,
                version_no=version_no,
                summary=summary,
            )
            return json.dumps(ref, ensure_ascii=False)
        except Exception as exc:
            _logger.warning(
                f"write_artifact_tool 失败: {exc!r}",
                event_type="write_artifact_tool_failed",
            )
            return json.dumps({"error": str(exc), "artifact_id": ""})

    @_lc_tool
    async def get_asset_url_tool(asset_id: str) -> str:
        """Get the permanent MinIO URL for a media asset by its asset_id.

        Returns URL string, or empty string if not found.
        """
        return await get_asset_url(asset_id)

except ImportError:
    _logger.warning("langchain_core 未安装，@tool 包装不可用", event_type="lc_tool_import_failed")
    read_artifact_tool = None  # type: ignore[assignment]
    write_artifact_tool = None  # type: ignore[assignment]
    get_asset_url_tool = None  # type: ignore[assignment]


def build_ref_from_local_file(
    project_id: str,
    artifact_type: str,
    version_no: int,
    *,
    summary: str = "",
    prefix: str = "",
) -> Optional[dict]:
    """从本地阶段目录中读取最新文件路径，构造 ArtifactRef。

    DESIGN-11 改名：原名 build_ref_from_latest，可用外部别名保持向后兼容。

    用于 Batch A 节点：PersistenceService 已写好本地文件，
    节点通过此函数找到对应路径并返回 ArtifactRef。

    Args:
        project_id:    项目 ID。
        artifact_type: 产物类型，用于映射阶段目录。
        version_no:    版本号（用于 artifact_id）。
        summary:       摘要文本。
        prefix:        文件名前缀过滤（空字符串 = 全部文件）。

    Returns:
        ArtifactRef dict，若目录为空则返回 None。
    """
    store = LocalArtifactStore(project_id)
    stage = _ARTIFACT_TYPE_TO_STAGE.get(artifact_type, ArtifactStage.BRIEF)
    latest = store.latest_in_stage(stage, prefix=prefix)

    if latest is None:
        _logger.warning(
            f"build_ref_from_latest: 阶段 {stage!r} 无文件 "
            f"artifact_type={artifact_type!r} project={project_id!r}",
            event_type="artifact_ref_build_no_file",
        )
        return None

    return make_artifact_ref(
        artifact_type=artifact_type,
        local_path=latest,
        version_no=version_no,
        summary=summary,
    )


async def build_ref_from_asset(
    project_id: str,
    artifact_type: str,
    version_no: int,
    *,
    summary: str = "",
    prefix: str = "",
) -> Optional[dict]:
    """优先查 Asset 表，再降级本地文件，构造 ArtifactRef。

    DESIGN-11 改名：原名 build_ref_from_asset_latest，可用外部别名保持向后兼容。
    """
    try:
        async with UnitOfWork() as uow:
            assets = await AssetRepository(uow.session).list_by_project(
                project_id,
                asset_type=artifact_type,
                limit=50,
            )
        for asset in assets:
            metadata = asset.metadata_ or {}
            local_name = Path(metadata.get("local_path", "")).name
            if prefix and prefix != metadata.get("artifact_type", "") and not local_name.startswith(prefix):
                continue
            if int(metadata.get("version_no") or 0) == int(version_no):
                return _build_ref_from_asset(asset, summary=summary)
        if assets:
            return _build_ref_from_asset(assets[0], summary=summary)
    except Exception as exc:
        _logger.warning(
            f"build_ref_from_asset_latest 失败: {exc!r}",
            event_type="artifact_ref_build_db_failed",
        )

    return build_ref_from_local_file(
        project_id,
        artifact_type,
        version_no,
        summary=summary,
        prefix=prefix,
    )


# ---------------------------------------------------------------------------
# DESIGN-11: 向后兼容别名（旧名仍可用，逐步迁移）
# ---------------------------------------------------------------------------
build_ref_from_latest = build_ref_from_local_file
build_ref_from_asset_latest = build_ref_from_asset
