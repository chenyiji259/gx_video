# VidMuse 代码审计问题记录

> 文档目标：记录 2026-04-03 全链路代码审计发现的 Bug 和设计问题，供后续批次修复使用。
>
> 审计范围：用户上传 → 音频分析 → Brief/Style → 叙事剧本 → 视觉圣经 → 分镜 → 视频片段 → 时间线合成。产物的本地/MinIO/DB 三副本保存、上下游数据传递、多用户并发隔离。积分扣费逻辑暂不在本次审计范围内。
>
> 审计依据：结合实际代码，以代码行为为准，非文档设计预期。

---

## Bug 列表

---

### BUG-01 音频分析 MinIO 下载调用三重错误（严重）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/services/audio_analysis_service.py`
**行号**：第 121–124 行

**问题描述**：

`run_and_save()` 在裁切音频后，需要从 MinIO 下载裁切后的音频文件到本地临时目录，供 librosa 和 Qwen Omni 分析使用。当前代码：

```python
with tempfile.TemporaryDirectory() as tmpdir:
    audio_path = os.path.join(tmpdir, "trimmed.wav")
    await storage.download_file(trimmed_bucket, trimmed_key, audio_path)
```

存在三个错误同时叠加：

**错误①：对同步方法使用 await**
`MinIOAdapter.download_file()` 是同步方法（返回 `Path`，不是协程）。直接 `await` 会立即抛出 `TypeError: object Path can't be used in 'await' expression`。`MinIOAdapter` 没有提供 `async_download_file` 方法，只有 `async_download_bytes`。

**错误②：参数顺序颠倒**
`MinIOAdapter.download_file` 签名为 `(self, key: str, dest_path: Path, *, bucket: Optional[str] = None)`。
当前调用把 `trimmed_bucket`（bucket 名称）传给了 `key`，把 `trimmed_key`（对象路径）传给了 `dest_path`，完全颠倒。

**错误③：第三位置参数违反 keyword-only 约束**
`bucket` 是 `*` 之后的关键字参数，不接受位置传参。`audio_path` 作为第三个位置参数传入，会抛出 `TypeError: download_file() takes 3 positional arguments but 4 were given`。

**影响**：音频分析 Worker handler（`_handle_analyze_audio`）调用此方法后 100% 崩溃，整条音频分析链路不可用。

**正确写法**：

```python
with tempfile.TemporaryDirectory() as tmpdir:
    audio_path = os.path.join(tmpdir, "trimmed.wav")
    data = await storage.async_download_bytes(trimmed_key, bucket=trimmed_bucket)
    Path(audio_path).write_bytes(data)
```

---

### BUG-05 VisualBibleService 两处 get_presigned_url 调用三重错误（严重）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/services/visual_bible_service.py`
**行号**：第 628 行（`_get_project_asset_url`）、第 662 行（`analyze_reference_image`）

**问题描述**：

两处调用均为：

```python
return await storage.get_presigned_url(asset.bucket_name, asset.object_key)
image_url = await storage.get_presigned_url(asset.bucket_name, asset.object_key)
```

`MinIOAdapter.get_presigned_url` 签名为 `(self, key: str, expiry_seconds: Optional[int] = None, *, bucket: Optional[str] = None)`。

错误①：同步方法被 `await`，TypeError。
错误②：`asset.bucket_name`（bucket 名）传给了 `key`；`asset.object_key`（对象路径字符串）传给了 `expiry_seconds`（期望 int）。
错误③：`bucket` 是 keyword-only，无法接受位置参数。

**影响**：
- `generate_character_reference()` 走 `image_to_image` 模式时，尝试获取参考图 URL → 100% 崩溃，用户上传的参考图无法用于角色生成
- `analyze_reference_image()` 调用 Omni 分析参考图时获取图片 URL → 100% 崩溃，Omni 分析链路完全不可用
- `generate_costume_reference()` 依赖 `_get_project_asset_url` → 同样崩溃

**正确写法**：

```python
image_url = await storage.async_get_presigned_url(asset.object_key, bucket=asset.bucket_name)
```

---

### BUG-06 音频裁切工具 download_file 三重错误（严重，流水线最前端）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/tools/audio_trim_tool.py`
**行号**：第 104 行

**问题描述**：

```python
await storage.download_file(src.bucket_name, src.object_key, src_path)
```

`MinIOAdapter.download_file` 签名为 `(self, key: str, dest_path: Path, *, bucket: Optional[str] = None)`。

错误①：同步方法被 `await`，TypeError。
错误②：`src.bucket_name` 传给了 `key`；`src.object_key` 传给了 `dest_path`，两者完全颠倒。
错误③：`src_path` 作为第三位置参数，但 `bucket` 是 keyword-only，抛 TypeError。

**影响**：`trim_audio()` 是 `AudioAnalysisService.run_and_save()` 的第一步。此处崩溃导致整条音频分析流水线在最入口处中断，BUG-01 甚至不会被触达。所有依赖音频分析的后续阶段（brief 生成、shot plan、分镜等）全部无法启动。

**正确写法**：

```python
data = await storage.async_download_bytes(src.object_key, bucket=src.bucket_name)
Path(src_path).write_bytes(data)
```

---

### BUG-07 音频裁切工具 upload_file 三重错误 + 返回値误用（严重）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/tools/audio_trim_tool.py`
**行号**：第 131–133 行

**问题描述**：

```python
storage_uri = await storage.upload_file(
    src.bucket_name, object_key, trimmed_path, "audio/wav"
)
```

`MinIOAdapter.upload_file` 签名为 `(self, key: str, file_path: Path, content_type: str = ..., *, bucket: Optional[str] = None) -> str`。

错误①：同步方法被 `await`，TypeError。
错误②：参数顺序全部错位：`src.bucket_name`→`key`、`object_key`→`file_path`、`trimmed_path`→`content_type`。
错误③：`"audio/wav"` 是第四个位置参数，但 `bucket` 是 keyword-only，抛 TypeError。
错误④（额外）：即使调用顺序修正，`upload_file()` 返回 `"minio://{bucket}/{key}"` 协议 URI，而 `storage_uri` 字段应存储 HTTP 永久直链（需调用 `get_permanent_url()`）。存入 `minio://` 协议的 URI 会导致前端无法直接访问。

**正确写法**：

```python
await asyncio.to_thread(storage.upload_file, object_key, Path(trimmed_path), "audio/wav")
storage_uri = storage.get_permanent_url(object_key)
```

或使用异步字节上传：

```python
await storage.async_upload_bytes(object_key, trimmed_bytes, "audio/wav")
storage_uri = storage.get_permanent_url(object_key)
```

---

### BUG-08 CharacterSetVersion JSON 结构体无本地文件、无 MinIO 备份（中）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/services/visual_bible_service.py`

**问题描述**：

视觉圣经的 JSON 结构（角色→参考图绑定、造型列表、是否确认等）仅存储在 `character_set_versions` 表的 JSONB 列里（`characters`、`scenes`、`raw_payload`），未写本地文件，未上传 MinIO，无 Asset 记录。

- DB JSONB：✅
- 本地 `04_style/visual_bible_v{N}.json`：❌
- MinIO：❌
- DB Asset 表：❌

**影响**：
- 视觉圣经结构无法通过 ArtifactRef 协议传递给 Agent 作本地文件读取（`read_artifact_tool` 找不到本地路径）
- 无 MinIO 备份，若 DB 损坏则整个角色绑定结构不可恢复
- 回退逻辑中若需要回溯历史版本的视觉圣经 JSON，只能查 DB，无法从文件系统恢复

**修复方向**：在 `init_from_narrative()` 和每次参考图更新（`_update_character_ref` / `_update_scene_ref`）后调用 `write_artifact()` 写本地 + MinIO，或至少在 `confirm_visual_bible()` 确认时做一次完整快照。

---

### BUG-09 Shot Plan 最终版本（含 beat-snap）仅存本地，未上传 MinIO（低）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/services/shot_plan_persistence_service.py`
**行号**：第 526–539 行

**问题描述**：

`_persist()` 最后使用 `LocalArtifactStore.write_json()` 写了两份本地文件：
- `05_shot_plan/shot_plan_v{N}_{ts}.json`（含 beat-snap 对齐后的最终时间轴）
- `05_shot_plan/shot_semantic_specs_v{N}_{ts}.json`（完整 ShotSemanticSpec）

但这两份文件均未调用 `write_artifact()`，未上传 MinIO，无 Asset 记录。

Agent 生成阶段的“原稿”（beat-snap 前）确实经 `write_artifact_tool` 上传了 MinIO，但那是未经 beat-snap 的版本，不是最终版。

**影响**：
- MinIO 中的 shot plan 是旧版（未 beat-snap），与实际落库的 Shot 时间戳不完全一致
- ShotSemanticSpec 完全没有 MinIO 副本，调试时只能查 DB
- 若本地磁盘损坏，最终版镜头计划无法从 MinIO 重建

---

### BUG-10 NarrativeScriptService _persist\(\) 本地快照仅写摘要，非全量内容（低）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/services/narrative_script_service.py`
**行号**：第 268–282 行

**问题描述**：

`_persist()` 写本地文件时只序列化了摘要信息：

```python
store.write_json(
    ArtifactStage.BRIEF,
    "narrative_script",
    {
        "version_id": narrative_version.id,
        "version_no": version_no,
        "story_arc": narrative_version.story_arc,
        "character_count": len(...),
        "scene_count": len(...),
        "section_count": len(...),
    },
    version=version_no,
)
```

完整的 `characters`、`scenes`、`section_mapping` 列表均未写入此本地文件。

`03_brief/` 目录中实际存在两类文件：
1. Agent 的 `write_artifact_tool` 写的全量 JSON（较早时间戳）→ 内容完整
2. `_persist()` 写的摘要 JSON（较晚时间戳）→ 仅计数

`build_ref_from_latest()` 按时间戳字典序取最新文件，会优先取到摘要版。若有 Agent 通过本地路径读取叙事剧本全文，会得到摘要而非完整内容。MinIO 和 DB 中均有完整内容，功能影响可控。

**修复方向**：`_persist()` 写本地文件时应写全量内容（`raw_payload` 直接写入），或不在 `_persist()` 重复写文件（由 Agent 的 `write_artifact_tool` 唯一负责本地 + MinIO 写入）。

---

### BUG-11 PromptBundle 本地快照缺少 reference_image_urls 字段，且无 MinIO 备份（低）

**状态**：✅ 已修复（本地快照 2026-04-03；MinIO 上传暂未实现，属 P3 下阶✅）
**文件**：`backend/app/services/prompt_compiler_service.py`
**行号**：第 472–486 行

**问题描述**：

`PromptCompilerService.compile_for_shot()` 确实写了本地快照（`07_prompt_bundles/bundle_shot_XXX_{ts}.json`），早期审计结论有误，此处更正。

但本地快照内容不完整，未包含参考图 URL 信息：

```python
store.write_json(
    ArtifactStage.PROMPT_BUNDLES,
    f"bundle_shot_{shot.shot_index:03d}",
    {
        "bundle_id": bundle.bundle_id,
        "shot_id": shot_id,
        "shot_index": shot.shot_index,
        "target_type": target_type,
        "provider": provider_name,
        "positive_prompt": bundle.positive_prompt,
        "negative_prompt": bundle.negative_prompt,
        "params": bundle.params,
    },
)
```

实际上 `bundle.reference_image_urls`（场景图→造型图→角色图三层参考 URL）和 `bundle.reference_asset_ids` 是分镜生成质量的关键证据，但本地快照未记录。MinIO 同样无上传。

**影响**：调试分镜质量问题时，无法从本地快照直接看到该镜头使用了哪几张参考图，需要关联查 DB。功能不受影响。

---

### BUG-02 ArtifactRef 落库时 bucket_name 取错私有属性（中）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/tools/shared/artifact_tools.py`
**行号**：第 148–151 行

**问题描述**：

`_persist_artifact_asset()` 在把文本产物落库为 Asset 记录时，需要记录 bucket_name：

```python
from app.storage.minio_adapter import get_storage
storage = get_storage()
bucket_name = getattr(storage, "_bucket_name", "vidmuse")  # ← 属性名错误
```

`MinIOAdapter` 的实际私有属性名是 `_default_bucket`，不是 `_bucket_name`。`getattr` 找不到该属性，永远返回默认值 `"vidmuse"`。

**影响**：当配置的 bucket 名称不是 `"vidmuse"` 时，`assets` 表中文本产物（`creative_brief`、`narrative_script`、`shot_plan` 等类型）的 `bucket_name` 字段记录错误，导致通过 `bucket_name + object_key` 重建下载路径时失败。

**正确写法**：

```python
bucket_name = storage.default_bucket  # 使用公开属性
```

---

### BUG-03 ConcurrencyGuardService 已实现但核心服务均未使用（中）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/services/concurrency_guard_service.py` 已实现；以下服务未使用：
- `backend/app/services/audio_analysis_service.py`
- `backend/app/services/storyboard_service.py`
- `backend/app/services/clip_service.py`
- `backend/app/services/timeline_composer_service.py`

**问题描述**：

`ConcurrencyGuardService` 基于 Redis SET NX 实现了完整的 `project_lock` 和 `shot_lock` 分布式锁，设计合理。但所有核心生成服务均未调用该锁。

Worker 的 `_execute_job` 中有一个 job 状态判断（pending/retrying 才执行），对同一 job 的重复消费有一定保护，但：

1. 同一项目的**两个独立 job** 同时执行时没有项目级互斥（例如用户双击触发了两次分镜生成）
2. load_job → check_status → mark_running 三步非原子，存在 TOCTOU 竞态窗口
3. Shot 级并发（单个镜头重生成与全量分镜生成同时触发）同样没有保护

**影响**：在用户快速操作或网络抖动导致重复请求的场景下，可能出现同一阶段并发写库、状态机乱序推进、产物版本号冲突。

**修复方向**：在各服务 `generate_and_save()` 入口加 `async with concurrency_guard.project_lock(project_id):`，单镜头重生成入口加 `shot_lock(shot_id)`。

---

### BUG-04 Timeline 音频本地文件查找不精确（低）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/services/timeline_composer_service.py`
**行号**：第 411 行

**问题描述**：

`_get_audio_path()` 查找本地音频副本时：

```python
local_candidates = list(input_dir.glob("audio_original*"))
if local_candidates:
    return local_candidates[0]
```

`AssetSyncService.sync()` 写本地副本的文件名格式为 `audio_original_{asset_id}.{ext}`。若用户多次重新上传音频，`01_input/` 目录下会存在多个 `audio_original_*` 文件，`glob("audio_original*")` 加 `[0]` 取的是 OS 排序后的第一个，不保证是最新上传的那个。

**影响**：用户重新上传音频后重新合成时间线，可能拿到旧音频文件做混音，导致音画不同步。

**正确写法**：按 asset_id 精确匹配：

```python
local_candidates = list(input_dir.glob(f"audio_original_{audio_asset.id}*"))
```

---

## 设计缺陷（非 Bug，但需知悉）

---

### DESIGN-01 ~~07_prompt_bundles 本地快照未写入~~（已修正）

> 此条记录已被 BUG-11 取代。实际 `PromptCompilerService.compile_for_shot()` 确实写了本地快照（`07_prompt_bundles/bundle_shot_XXX_{ts}.json`），但内容不完整（缺少 reference_image_urls）且无 MinIO 上传。详见 BUG-11。

---

### DESIGN-02 文本产物本地文件路径在水平扩展时失效

**描述**：

`ArtifactRef.local_path` 和 `Asset.metadata_.local_path` 存储的是当前服务器的本地绝对路径（`data/projects/{id}/...`）。

- 单服务器部署：✅ 正常
- 多实例水平扩展：❌ Worker A 写的本地文件，Worker B 的 `read_artifact(local_path)` 找不到，会 fallback 到 MinIO。MinIO 能兜住核心功能，但本地路径记录失去意义，`read_artifact` 的本地优先逻辑形同虚设。

**影响**：当前为单机部署架构，不影响现有功能。若未来需要水平扩展，本地文件副本策略需要改为共享存储（NFS/OSS FUSE）或完全依赖 MinIO。

---

### DESIGN-03 Storyboard 本地快照缺少每帧 MinIO URI

**状态**：✅ 已修复（2026-04-03）

**文件**：`backend/app/services/storyboard_service.py`，`_persist()` 方法

**描述**：

`06_storyboard/storyboard_v{N}_{ts}.json` 中只记录了 `asset_id`，没有记录每帧图片的 `storage_uri`（MinIO 永久直链）。调试时需要额外查 DB 才能拿到图片 URL。

**影响**：纯调试体验问题，功能不受影响。

---

### DESIGN-04 `ConcurrencyGuardService` 解锁操作非原子，存在 TOCTOU 竞态（严重）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/services/concurrency_guard_service.py`，第 189–196 行

**问题描述**：

`_lock()` 的解锁流程分两步执行：

```python
current_token = await redis_client.get(lock_key)  # 步骤 1
if current_token == token:
    await redis_client.delete(lock_key)            # 步骤 2：两步之间存在竞态窗口
```

GET 与 DELETE 之间若锁恰好超时且被另一个进程重新持有，此 DELETE 将误删他人的锁，导致两个并发操作同时进入临界区。

**影响**：极低概率触发（需锁超时与新进程抢锁同时发生），一旦触发将绕过并发保护，导致同一项目的生成任务并发执行，产生版本号冲突或状态机乱序。

**正确写法**：用 Lua 脚本原子化 GET+DELETE：

```lua
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
```

Python 调用：`await redis_client.eval(lua_script, 1, lock_key, token)`

---

### DESIGN-05 `_safe_parse_json` 在 3+ 处独立重复定义（中）

**状态**：✅ 已修复（2026-04-03）
**文件**：
- `backend/app/services/visual_bible_service.py`，第 58–77 行
- `backend/app/services/prompt_compiler_service.py`，第 68–87 行
- `backend/app/agents/visual_development_agent.py`，第 38–64 行

**问题描述**：同一三层 JSON 安全解析逻辑在多处各自独立实现，fallback 返回值微有差异，维护时需同步修改多处。

**修复方向**：提取到 `backend/app/utils/json_utils.py` 作为公共工具函数：

```python
def safe_parse_json(text: str, *, fallback: dict | None = None) -> dict:
    """三层安全解析：直接解析 → Markdown 代码块提取 → 裸大括号提取。"""
    ...
```

---

### DESIGN-06 `DirectorReportService` 两张表需手动保持同步，clips/timeline 无 ArtifactRef（中）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/services/director_report_service.py`，第 45–75 行

**问题描述**：

```python
_REPORT_TASK_TYPES = frozenset({...})
_TASK_TO_ARTIFACT  = {...}
```

两个独立数据结构需手动保持同步，新增任务类型时需修改两处，易遗漏。当前 `generate_clips`、`generate_timeline` 在白名单中但不在映射表里，导致这两类任务完成后 Director Mode B 汇报时 `artifact_ref_for_review = None`，Director 无法审核产物内容，只能输出通用汇报语。

**修复方向**：合并为单一数据结构，`artifact_type=None` 表示无需加载引用：

```python
_TASK_CONFIG: dict[str, dict | None] = {
    "generate_storyboard": {"artifact_type": "storyboard", "prefix": "storyboard"},
    "generate_clips":      None,
    "generate_timeline":   {"artifact_type": "timeline", "prefix": "timeline"},
}
```

---

### DESIGN-07 Worker 双层 `asyncio.wait_for` 超时，错误码分支混淆（中）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/tasks/worker.py`

**问题描述**：

Handler 内部（如 `_handle_generate_storyboard`）已用 `asyncio.wait_for(svc.xxx(), timeout=120.0)` 并在超时时 `raise RuntimeError("...超时...")`；外层 `_execute_job` 也有 `asyncio.wait_for(handler(job), timeout=self._job_timeout)`（660s 兜底）。

内部超时先触发，抛 `RuntimeError`，外层 `except Exception` 捕获后走 `error_code="handler_error"` 分支，而非 `error_code="timeout"` 分支。日志中无法区分“handler 内部超时”与“handler 真实异常”，排障困难。

**修复方向（二选一）**：
- **方案 A（推荐）**：移除 handler 内部的 `asyncio.wait_for`，完全依赖外层 `_execute_job` 超时控制；差异化超时通过 ToolJob 字段或 handler 配置表传入
- **方案 B**：handler 内部超时时改为 `raise asyncio.TimeoutError`，使外层能走到正确的超时分支

---

### DESIGN-08 `auto_analyze_and_setup_costumes` 事务分段，造型记录提前持久化形成半完成状态（中）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/services/visual_bible_service.py`，第 899–1005 行

**问题描述**：

流程分三段独立事务：
1. UoW#1：读取 narrative + csv + style
2. 内存中修改 costumes → UoW#2：提前将 costumes（含空 `reference_asset_id`）持久化到 DB
3. 循环为每套造型调用 `generate_costume_reference`（各含独立 UoW）

若第 3 步某套造型图生成失败，第 2 步的 costume 记录已提交（`costume_id` 存在但 `reference_asset_id = None`），系统无法自动识别哪些需要重试，形成持久化的“半完成”状态。

**修复方向**：
- 仅在所有造型图均生成成功后，统一将 `reference_asset_id` 批量写回 DB
- 或引入 costume 级状态字段（`pending` / `ready` / `failed`），使重试逻辑可识别断点

---

### DESIGN-09 `asyncio.create_task` 创建的任务无引用，异常静默丢失（低）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/tasks/worker.py`，第 787–790、920–927、370–374 行

**问题描述**：

```python
asyncio.create_task(
    self._run_with_semaphore(semaphore, job_id)
)
```

Task 无引用时，内部未捕获的异常会在 GC 时打印 `Task exception was never retrieved` 警告，但主循环不感知，异常静默丢失。

**修复方向**：

```python
task = asyncio.create_task(self._run_with_semaphore(semaphore, job_id))
self._active_tasks.add(task)
task.add_done_callback(self._active_tasks.discard)
```

在 `TaskWorker` 中维护 `_active_tasks: set[asyncio.Task]`，`done_callback` 负责清理并记录逃逸异常。

---

### DESIGN-10 Asset 表 `bucket_name="local"` 反模式，破坏前端展示链路（严重，架构缺陷）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/tools/shared/artifact_tools.py`，第 144–152 行

#### 产品期望的三副本存储架构（2026-04-03 确认）

- **本地文件**：保存文本产物（剧本 / 创意方案 / 镜头计划等），用于调试查看，以及 Agent 通过文件读取工具进行本地产物传递
- **MinIO**：保存文本产物 + 图片 + 视频，作为统一资产存储（canonical storage）
- **DB（assets 表）**：记录 MinIO 的 `storage_uri` / `object_key` / `bucket_name`，供后端把可访问的产物地址传给前端展示

**前端展示链路**：前端通过 API 从后端拿到 `asset.storage_uri`，浏览器直接加载/下载该 MinIO 永久直链。因此 **DB 中的 `storage_uri` 必须是有效 MinIO URL**，本地绝对路径不能作为前端资产地址。

**当前缺陷**：

`_persist_artifact_asset` 在 MinIO 上传失败时：

```python
bucket_name = "local"
storage_uri = str(local_path)
```

这会在 Asset 表中创建一条“幽灵记录”：结构合法，但 `storage_uri` 指向服务器本地路径。该路径对浏览器不可访问，前端若直接展示将得到空白或错误链接。

**问题根源**：当前实现把两种语义混在了一起：
1. MinIO 上传成功后，在 DB 中登记“可对外展示的资产索引”
2. 即使 MinIO 失败，也在 DB 中登记一条本地降级记录

第一种是正确语义，第二种会污染 Asset 表。

**修复结论**：

Asset 表应当只记录 **MinIO 上传成功** 的资产；若 MinIO 失败，应仅返回本地 `ArtifactRef`，不创建 Asset 记录。

建议改造 `write_artifact` 为：

1. **始终写本地文件**
2. **尝试上传 MinIO**
3. **仅当 MinIO 成功时写 Asset 表**
4. **若 MinIO 失败，则仅返回本地 ArtifactRef，不写 DB Asset**

伪代码：

```python
async def write_artifact(...):
    local_path = store.write_json(...)
    try:
        await storage.async_upload_bytes(...)
        minio_uri = storage.get_permanent_url(object_key)
        return await _persist_artifact_asset(..., minio_uri=minio_uri)
    except Exception:
        logger.warning("MinIO 上传失败，返回本地 ArtifactRef，暂不创建 Asset 记录")
        return make_artifact_ref(...)
```

`_persist_artifact_asset` 也应同步收口：移除 `bucket_name="local"` / `storage_uri=local_path` 的分支，`minio_uri` 改为必填。

**降级后链路表现**：

- Agent 读取产物：✅ 正常（本地文件仍可读）
- Director Mode B 汇报：✅ 正常（无 Asset 时可降级读本地）
- 前端产物展示：❌ 临时不可用，但这是正确行为——好过展示一个无效的本地服务器路径

---

### DESIGN-11 `build_ref_from_latest` 与 `build_ref_from_asset_latest` 命名模糊，同步版本轻微阻塞（低）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/tools/shared/artifact_tools.py`，第 445–524 行

**问题描述**：

两个函数命名差异极小，但语义差异很大：
- `build_ref_from_latest`：从本地目录读最新文件
- `build_ref_from_asset_latest`：优先查 Asset 表，再降级本地

前者还是同步目录扫描，在异步上下文中有轻微阻塞风险。

**修复方向**：重命名以强调数据源差异，并将本地目录扫描包装到 `asyncio.to_thread` 中。

---

### DESIGN-12 `StateTransitionService.mark_stale` 中 `STYLE_CHANGED` 的回退目标语义待确认（知悉）

**状态**：⬜ 待确认（需产品侧确认语义）
**文件**：`backend/app/services/state_transition_service.py`，第 333–335 行

**问题描述**：

`STYLE_CHANGED` 当前回退到 `shot_plan_ready`。如果它表示“仅视觉风格圣经变化”，这个回退是合理的；如果它实际承载的是“创意方案变化”，则按 doc14 的表述应回退得更早。当前更像是**语义定义尚未明确**，而不是代码 bug。

---

## 类设计问题（CLASS，2026-04-03 第二轮审计）

---

### CLASS-01 `VisualBibleService` 违反单一职责，Service 层嵌入 LLM 调用（严重）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/services/visual_bible_service.py`

**问题描述**：

该类承担了过多职责：
1. 初始化 CharacterSetVersion
2. 生成角色/场景/造型参考图
3. 确认视觉圣经
4. 直接调用 Omni 分析参考图（`analyze_reference_image`）
5. 直接调用 Omni 推导造型（`_derive_costumes_from_narrative`）
6. 协调整个多造型自动化流程（`auto_analyze_and_setup_costumes`）

其中第 4 和第 5 项明显属于 Agent 层能力，不应由 Service 层直接实例化 `ChatOpenAI` 完成。当前实现说明 `VisualDevelopmentAgent` 的职责切分还不完整。

**影响**：
- LLM 调用逻辑分散，难复用
- Service 层单测需要 mock LLM
- 后续 Agent 配置化或模型替换时，Service 层也必须一起改

**修复方向**：把 Omni 图片分析和造型推导下沉到 `VisualDevelopmentAgent`，由 `VisualBibleService` 仅做业务编排和落库。

---

### CLASS-02 `_load_context_for_character` 与 `_load_context_for_scene` 高度重复（中）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/services/visual_bible_service.py`，第 498–568 行

**问题描述**：

两方法流程基本一致：项目归属校验 → 取 active CharacterSetVersion → 取 active StyleBible → 从对应列表中找 item。可提取为统一方法，降低维护成本。

---

### CLASS-03 Worker Handler 以模块顶层函数存在，与 `TaskWorker` 类结构分离（中）

**状态**：✅ 已优化（2026-04-03，结构分组注释方式）
**文件**：`backend/app/tasks/worker.py`

**问题描述**：

约 10 个 `_handle_*` 函数以模块级函数方式定义，再在文件末尾手动注册到 `task_worker`。类本身不包含 handler 结构，读文件时需要在多个区域跳转，新增任务时也必须同时维护“定义位置 + 注册位置”两处。

**修复方向**：提取独立 `WorkerHandlerRegistry`，或将 handler 组织到类内的静态方法中，再统一注册。

---

### CLASS-04 `transition_tool_job` 中 `error_info` 与 `output_payload` 共用同一字段（中）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/services/state_transition_service.py`，第 274–278 行

**问题描述**：

```python
if output_payload is not None:
    job.output_payload = output_payload
if error_info is not None:
    job.output_payload = error_info
```

成功输出和错误信息共用 `output_payload`，语义混乱。`AgentTask` 已经区分了成功输出和错误载荷，`ToolJob` 应与之保持一致。

**修复方向**：给 `ToolJob` 增加独立 `error_payload` 字段。

---

### CLASS-05 `get_storage()` 全局单例非原子初始化（低）

**状态**：✅ 已修复（2026-04-03）
**文件**：`backend/app/storage/minio_adapter.py`，第 320–329 行

**问题描述**：

`get_storage()` 采用懒加载单例，虽在当前 asyncio 单线程主流程中问题不大，但设计上属于 check-then-act 模式，未来多线程测试或初始化路径变化时存在重复实例风险。

**修复方向**：在应用启动阶段显式初始化存储客户端，而非在运行期懒加载。

---

## 修复优先级建议

> P0 = 流水线崩溃，立即修； P1 = 下一个功能迭代带上修； P2 = 有空就修； P3 = 调试体验改善

| 编号 | 优先级 | 描述 | 预计改动量 |
|---|---|---|---|
| BUG-06 | **P0** | 音频裁切 download_file 三重错误，整个音频链路最入口就崩溃 | 极小（3行） |
| BUG-07 | **P0** | 音频裁切 upload_file 三重错误+返回値误用 | 极小（3行） |
| BUG-01 | **P0** | 音频分析服务中 download_file 三重错误 | 极小（2行） |
| BUG-05 | **P0** | 视觉圣经服务 get_presigned_url 三重错误，参考图/Omni分析全部崩溃 | 极小（2行） |
| DESIGN-04 | **P1** | ConcurrencyGuard 解锁非原子，存在 TOCTOU 竞态 | 极小（Lua 脚本） |
| DESIGN-10 | **P1** | Asset 表 `bucket_name=\"local\"` 反模式，前端展示链路断裂 | 小（约30行重构） |
| CLASS-01 | **P1** | VisualBibleService 嵌入 LLM 调用，违反 Service/Agent 分层 | 大（职责重构） |
| CLASS-04 | **P1** | ToolJob 错误与输出共用同一字段，语义混淆 | 极小（加字段） |
| BUG-02 | P1 | ArtifactRef 落库时 bucket_name 取错属性名 | 极小（1行） |
| BUG-03 | P1 | ConcurrencyGuard 已实现但所有核心服务均未使用 | 小（各服务入口加锁 约20行） |
| BUG-08 | P1 | CharacterSetVersion JSON 结构无本地文件、无 MinIO、无 Asset 记录 | 小（约40行） |
| DESIGN-06 | P2 | DirectorReportService 两表手动同步，clips/timeline 无 ArtifactRef | 小（重构数据结构） |
| DESIGN-07 | P2 | 双层超时导致错误码不准确，排障困难 | 小（统一超时层） |
| DESIGN-08 | P2 | auto_setup_costumes 事务分段，形成半完成状态 | 中（调整事务边界） |
| DESIGN-05 | P2 | `_safe_parse_json` 多处重复定义 | 极小（提取工具函数） |
| CLASS-02 | P2 | `_load_context` 两方法高度重复 | 极小（提取公共方法） |
| BUG-04 | P2 | Timeline 音频本地文件查找不精确 | 极小（1行） |
| BUG-09 | P2 | Shot Plan 最终版本仅存本地，未上传 MinIO | 小（约20行） |
| BUG-10 | P2 | NarrativeScriptService 本地快照仅写摘要，非全量内容 | 极小（5行） |
| BUG-11 | P2 | PromptBundle 本地快照缺 reference_image_urls，且无 MinIO 上传 | 小（少量新增） |
| CLASS-03 | P3 | Worker handler 散落在类外，注册需手动维护 | 小（重组结构） |
| DESIGN-09 | P3 | `asyncio.Task` 无引用，异常静默丢失 | 极小（加 done callback） |
| CLASS-05 | P3 | `get_storage()` 懒加载单例设计偏脆弱 | 极小 |
| DESIGN-02 | 知悉 | 本地文件路径在水平扩展时失效 | — |
| DESIGN-03 | P3 | Storyboard 本地快照缺每帧 MinIO URI | 极小 |
| DESIGN-11 | P3 | `build_ref_from_latest` 命名模糊，同步版本轻微阻塞 | 极小 |
| DESIGN-12 | 待确认 | `STYLE_CHANGED` 回退目标语义需产品侧确认 | — |

---

## 文档版本

| 版本 | 日期 | 内容 |
|---|---|---|
| v1.0 | 2026-04-03 | 初始建立，基于首轮快速审计（BUG-01》BUG-04） |
| v1.1 | 2026-04-03 | 深度审计补展：新增 BUG-05~BUG-11，修正 DESIGN-01，更新优先级表 |
| v1.2 | 2026-04-03 | 修复第一批 P0：BUG-01、BUG-05、BUG-06、BUG-07 全部已修复 |
| v1.3 | 2026-04-03 | 修复第二批 P1：BUG-02、BUG-03（四个服务加项目级并发锁）、BUG-08（视觉圣经快照） |
| v1.4 | 2026-04-03 | 修复第三批 P2：BUG-04（音频路径精确匹配）、BUG-09（shot plan MinIO）、BUG-10（叙事副本全量）、BUG-11（prompt bundle 字段补全） |
| v1.5 | 2026-04-03 | 第二轮审计：新增 DESIGN-04~DESIGN-12 与 CLASS-01~CLASS-05；深度展开 DESIGN-10 存储架构缺陷与修复策略 |
| v1.6 | 2026-04-03 | 修复第一批 7 项：CLASS-02/CLASS-04（ToolJob 字段+context 重构）、DESIGN-04（Lua 原子锁）、DESIGN-05（json_utils）、DESIGN-06（_TASK_CONFIG 合并）、DESIGN-07（超时重抛）、DESIGN-10（Asset 存储链路收敛） |
| v1.7 | 2026-04-03 | 修复第二批 7 项：CLASS-01（LLM 迁入 Agent 层）、CLASS-03（结构分组）、CLASS-05（存储单例初始化）、DESIGN-03（分镖 storage_uri）、DESIGN-08（造型状态字段）、DESIGN-09（Task 引用）、DESIGN-11（build_ref 重命名+别名） |
