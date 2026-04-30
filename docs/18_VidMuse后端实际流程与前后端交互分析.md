# VidMuse 后端实际流程与前后端交互分析

> **文档目标**：基于 2026-04-05 对后端全部代码的深度审查，精确记录从项目创建到视频导出的完整后端执行流程，包括每一步的 API 调用、状态推进、产物落地、SSE 事件、以及与前端的数据交互方式。供后续前端改造作为唯一参考基准。
>
> **重要声明**：本文档所有内容均来自代码实际行为，非设计文档推测。与 docs/14 的偏差已在各处标注。

---

## 一、系统通信架构总览

### 1.1 两条独立的通信通道

后端与前端之间存在两条并行的实时通信通道，各自独立，用途不同：

| 通道 | 端点 | 协议 | 用途 |
|------|------|------|------|
| **Chat SSE** | `POST /v1/chat/completions` (stream=true) | OpenAI Streaming 格式 | Director 对话回复，逐字推送 |
| **Project SSE** | `GET /api/v1/projects/{id}/events/stream` | 标准 SSE (RFC 8895) | 项目事件推送（阶段变更、任务完成、进度） |

**Chat SSE** 是请求-响应模式：前端发消息 → 后端流式返回 Director 回复。每次请求一条流。

**Project SSE** 是长连接订阅模式：前端建立 EventSource 连接后持续接收事件，直到断开。事件来源是 Redis pub-sub（频道 `vidmuse:events:project`），由 OutboxPublisher 后台轮询 `outbox_events` 表发布。

### 1.2 SSE 事件推送机制（Outbox Pattern）

```
业务操作（Service 层）
  → EventLogService.emit() 写入 event_logs + outbox_events（同一 DB 事务）
  → OutboxPublisher（后台 asyncio task，每 1 秒轮询）
  → Redis PUBLISH 到 vidmuse:events:project 频道
  → project_events.py SSE 端点订阅 → 按 _project_id 过滤 → 推给前端
```

前端通过 `EventSource` 连接 `/api/v1/projects/{id}/events/stream?token=xxx`（因浏览器 EventSource 不支持自定义 Header，token 通过 query param 传递）。

### 1.3 Chat SSE 的 vidmuse 扩展字段

`/v1/chat/completions` 返回体中携带自定义 `vidmuse` 字段：

```json
{
  "vidmuse": {
    "requires_confirmation": true,
    "pending_decision_id": "01H...",
    "decision_options": [{"id": "...", "title": "...", "summary": "..."}]
  }
}
```

- **非流式**：在 response body 顶层
- **流式**：在最后一个 chunk（`finish_reason` 非 null 的 chunk）中

前端通过此字段判断是否需要刷新决策卡。

---

## 二、项目生命周期状态机

### 2.1 完整阶段列表（12 个阶段）

```
created → input_ready → audio_analyzed → brief_ready → narrative_ready
→ visual_bible_ready → shot_plan_ready → storyboard_ready → clips_ready
→ timeline_ready → export_ready → completed
```

另有 `failed` 状态，任何阶段均可进入。

### 2.2 各阶段含义与推进条件

| 阶段 | 含义 | 推进到下一阶段的条件 |
|------|------|---------------------|
| `created` | 项目刚创建，无任何输入 | ProjectSpec 激活且有 audio_asset_id |
| `input_ready` | 音频已上传，等待分析 | AudioAnalysisService 完成 → `audio_analyzed` |
| `audio_analyzed` | 音频分析完成，等待风格选择 | 用户选择 `select_style_direction` + Brief 生成完成 → `brief_ready` |
| `brief_ready` | 创意方案已生成，等待确认 | 用户确认 `confirm_brief` + 叙事生成完成 → `narrative_ready` |
| `narrative_ready` | 叙事剧本已生成，等待确认 | 用户确认 `confirm_narrative` + 视觉圣经初始化 → `visual_bible_ready` |
| `visual_bible_ready` | 视觉圣经已构建，等待确认 | 用户确认 `confirm_visual_bible` + 镜头计划生成完成 → `shot_plan_ready` |
| `shot_plan_ready` | 镜头计划已生成，等待确认 | 用户确认 `confirm_shot_plan` + 分镜生成完成 → `storyboard_ready` |
| `storyboard_ready` | 分镜图已生成，等待确认 | 用户确认 `confirm_storyboard` + 视频生成完成 → `clips_ready` |
| `clips_ready` | 视频片段已生成 | 时间线合成完成 → `timeline_ready` |
| `timeline_ready` | 时间线已合成 | 导出完成 → `export_ready` |
| `export_ready` | 导出完成 | 标记 → `completed` |
| `completed` | 项目完成 | 可回退到任意阶段 |

### 2.3 状态推进触发方

状态推进由 `StateTransitionService.advance_project()` 统一执行，调用方包括：
- `ProjectSpecService.activate_version()` — created → input_ready
- `AudioAnalysisService.run_and_save()` — input_ready → audio_analyzed
- `BriefPersistenceService.generate_and_save()` — audio_analyzed → brief_ready
- `NarrativeScriptService.generate_and_save()` — brief_ready → narrative_ready
- `VisualBibleService.init_from_narrative()` — narrative_ready → visual_bible_ready
- `ShotPlanPersistenceService.generate_and_save()` — visual_bible_ready → shot_plan_ready
- `StoryboardService.generate_and_save()` — shot_plan_ready → storyboard_ready
- `ClipService.generate_and_save()` — storyboard_ready → clips_ready
- `TimelineComposerService.compose_and_save()` — clips_ready → timeline_ready
- `ExportService` — timeline_ready → export_ready → completed

每次状态推进都会通过 EventLogService 发射一个 `project_{to_stage}` 事件到 Outbox。

---

## 三、完整执行流程（逐步详解）

### 步骤 0：项目创建

**前端操作**：用户在项目列表页点击创建
**API 调用**：`POST /api/v1/projects` body: `{name: "xxx"}`
**后端行为**：
- 创建 Project 记录，`current_stage = "created"`
- 无 SSE 事件

**产物**：无
**前端响应**：跳转到工作台页面 `/workbench/{projectId}`

---

### 步骤 1：输入准备（上传音频 + 参考图 + 描述 → 激活 Spec）

**前端操作**：用户在 `created` 阶段的输入面板中上传音频、可选上传参考图（最多 3 张）、填写创意描述，点击「开始创作」

**API 调用链**（前端 `handleStartCreation` 串行执行）：
1. `POST /api/v1/projects/{id}/assets/upload-init` — 获取 MinIO 预签名 URL
2. `PUT {upload_url}` — 直传 MinIO
3. `POST /api/v1/projects/{id}/assets/complete` — 确认上传，创建 Asset 记录
4. （参考图重复 1-3 步）
5. `POST /api/v1/projects/{id}/spec/versions` — 创建 ProjectSpec 版本
6. `POST /api/v1/projects/{id}/spec/activate` — 激活版本

**后端行为（activate 时）**：
- 检查 `audio_asset_id` 不为空 → 调用 `advance_project(INPUT_READY)`
- 写 `project_spec_v{N}.json` 到本地 `data/projects/{id}/01_input/`
- 发射 SSE 事件 `project_input_ready`

**前端继续**：
7. `POST /api/v1/projects/{id}/workflow/analyze-audio` — 触发音频分析

**产物**：
| 存储位置 | 内容 |
|---------|------|
| DB: `assets` | audio_original Asset 记录 |
| DB: `project_spec_versions` | Spec 版本记录 |
| MinIO: `projects/{id}/assets/audio_original/{asset_id}/` | 音频文件 |
| 本地: `data/projects/{id}/01_input/project_spec_v{N}.json` | Spec 快照 |

---

### 步骤 2：音频分析（异步 Worker）

**触发方式**：两条路径并行
- 路径 A：`POST /workflow/analyze-audio` 直接 dispatch ToolJob
- 路径 B：LangGraph 主图在 `input_ready` 阶段自动路由到 `audio_analysis_node`

两条路径最终都是创建 `analyze_audio` ToolJob 推入 Redis 队列。

**Worker 执行**：
1. 裁切音频（按 Spec 的 start_sec/end_sec）
2. 并发执行：librosa beat_track（精确节拍检测） + Qwen3.5 Omni 语义分析
3. 创建 `AudioAnalysisVersion` 记录
4. 上传分析结果到 MinIO
5. 写本地 `data/projects/{id}/02_audio_analysis/`
6. 调用 `advance_project(AUDIO_ANALYZED)`

**SSE 事件序列**：
```
audio.analysis.progress  → {progress: 10, message: "开始裁切并提取音频信号..."}
audio.analysis.progress  → {progress: 90, message: "librosa + Omni 并发分析完成，正在落库..."}
audio.analysis.completed → {version_id, bpm, section_count, duration_sec}
project_audio_analyzed   → {from_stage: "input_ready", to_stage: "audio_analyzed"}
director.report          → {task_type: "analyze_audio", message_preview: "...", session_id}
```

**Director Mode B 汇报**：Worker 完成后自动触发 `DirectorReportService.trigger()`：
- 加载 ArtifactRef → 调用主图（Mode B）→ Director 生成三段式汇报
- 汇报消息存入 `conversation_messages` 表
- 发射 `director.report` SSE 事件

**产物**：
| 存储位置 | 内容 |
|---------|------|
| DB: `audio_analysis_versions` | BPM、section_map、beat_map、quality_summary |
| MinIO: `projects/{id}/assets/audio_analysis/` | 分析结果 JSON |
| 本地: `data/projects/{id}/02_audio_analysis/` | 分析结果 JSON |

---

### 步骤 3：风格选择（用户决策）

**触发方式**：Director Mode B 汇报完成后或用户发消息时，主图路由到 `human_confirmation_gate`

**decision_type**：`select_style_direction`

**默认选项**（若 Director 未提供自定义选项）：
```json
[
  {"id": "style_cinematic", "title": "电影感", "summary": "高对比、暖色调、慢推拉"},
  {"id": "style_indie",     "title": "独立风", "summary": "自然光、颗粒感、跟拍运动"},
  {"id": "style_neon",      "title": "霓虹感", "summary": "强饱和、夜景、冷蓝/紫色调"}
]
```

**前端获取决策**：
- 通过 `GET /api/v1/projects/{id}/decisions` 轮询
- 或 SSE 事件触发 `triggerRefresh()` 后重新拉取

**前端提交决策**：
1. `POST /api/v1/projects/{id}/decisions/{decision_id}/select` body: `{selected_option_id: "style_cinematic"}`
2. 前端 `handleDecision` 中立即触发 `POST /workflow/generate-brief`
3. 再发一条 Chat 消息 "已确认，请继续。" 触发 Director 流

**重要发现**：前端在提交决策后会同时触发 workflow API 和 chat 消息，存在竞态风险。

---

### 步骤 4：创意方案生成（同步）

**触发**：`POST /api/v1/projects/{id}/workflow/generate-brief`

**前置校验**：`select_style_direction` 决策已 selected

**执行**：`BriefPersistenceService.generate_and_save()` — **同步阻塞**（约 10-20 秒）
1. 调用 CreativePlanningAgent 生成 brief + style JSON
2. 创建 `CreativeBriefVersion` + `StyleBibleVersion` 记录
3. 写本地 `data/projects/{id}/03_brief/` 和 `data/projects/{id}/04_style/`
4. 调用 `advance_project(BRIEF_READY)`

**SSE 事件**：
```
project_brief_ready → {from_stage: "audio_analyzed", to_stage: "brief_ready"}
```

**注意**：Brief 生成是同步的（非 Worker 异步），HTTP 响应直接返回结果。前端等待 response 返回后才知道完成。

**产物**：
| 存储位置 | 内容 |
|---------|------|
| DB: `creative_brief_versions` | title、summary、narrative_mode、mood_tags 等 |
| DB: `style_bible_versions` | color_palette、lighting、camera_style 等 |
| MinIO: `projects/{id}/assets/creative_brief/` | Brief JSON |
| 本地: `data/projects/{id}/03_brief/` + `04_style/` | Brief + Style JSON |

---

### 步骤 5：确认创意方案（用户决策）

**decision_type**：`confirm_brief`

**选项**：
```json
[
  {"id": "confirm",     "title": "确认创意方案并继续"},
  {"id": "regenerate",  "title": "重新生成创意方案"}
]
```

**前端提交后触发**：`POST /workflow/generate-narrative`

---

### 步骤 6：叙事剧本生成（异步 Worker）

**触发**：`POST /api/v1/projects/{id}/workflow/generate-narrative`

**前置校验**：`confirm_brief` 决策已 selected

**执行**：dispatch `generate_narrative` ToolJob → Worker 异步执行

**Worker 内部**：
1. 发射 `narrative.generating` SSE 事件
2. `NarrativeScriptService.generate_and_save()` 调用 NarrativeScriptAgent
3. 创建 `NarrativeScriptVersion` 记录
4. 调用 `advance_project(NARRATIVE_READY)`
5. 发射 `narrative.completed` SSE 事件

**SSE 事件序列**：
```
narrative.generating     → {message: "正在构思 MV 叙事剧本，请稍候..."}
narrative.completed      → {version_id, version_no, story_arc}
project_narrative_ready  → {from_stage: "brief_ready", to_stage: "narrative_ready"}
director.report          → {task_type: "generate_narrative", ...}
```

**产物**：
| 存储位置 | 内容 |
|---------|------|
| DB: `narrative_script_versions` | story_arc、characters、scenes、section_mapping |
| MinIO: `projects/{id}/assets/narrative_script/` | 叙事 JSON |

---

### 步骤 7：确认叙事剧本（用户决策）

**decision_type**：`confirm_narrative`

**选项**：
```json
[
  {"id": "confirm",     "title": "确认叙事剧本并继续"},
  {"id": "regenerate",  "title": "重新生成叙事剧本"}
]
```

**前端提交后触发**：`POST /workflow/init-visual-bible`

---

### 步骤 8：视觉圣经构建（多步骤过程）

#### 8a. 初始化视觉圣经框架

**触发**：`POST /api/v1/projects/{id}/workflow/init-visual-bible`

**前置校验**：`confirm_narrative` 决策已 selected

**执行**：`VisualBibleService.init_from_narrative()` — 同步
1. 读取叙事剧本中的角色和场景列表
2. 创建空的 `CharacterSetVersion` 记录
3. 调用 `advance_project(VISUAL_BIBLE_READY)`

**SSE 事件**：
```
project_visual_bible_ready → {from_stage: "narrative_ready", to_stage: "visual_bible_ready"}
```

#### 8b-8e. 参考图生成（通过 Director 工具调用触发）

视觉圣经的参考图生成不通过 workflow API 直接触发，而是由 Director Agent 在对话中通过工具调用 dispatch：

- `generate_character_ref` — 生成角色定妆图
- `generate_scene_ref` — 生成场景参考图
- `generate_costume_ref` — 生成段落造型变体

每个生成任务都是独立的 ToolJob，异步执行。每张图完成后 Director Mode B 汇报。

**这部分前端目前没有专门的 UI 展示角色/场景图生成进度和结果。**

---

### 步骤 9：确认视觉圣经（用户决策）

**decision_type**：`confirm_visual_bible`

**选项**：
```json
[
  {"id": "confirm",     "title": "确认视觉方向并继续"},
  {"id": "regenerate",  "title": "重新生成参考图"}
]
```

**前端提交后触发**：`POST /workflow/generate-shot-plan`

---

### 步骤 10：镜头计划生成（同步）

**触发**：`POST /api/v1/projects/{id}/workflow/generate-shot-plan`

**前置校验**：`confirm_visual_bible` 决策已 selected（代码实际检查的是 confirm_visual_bible 而非 confirm_brief，与 docs/14 描述不同）

**执行**：`ShotPlanPersistenceService.generate_and_save()` — **同步阻塞**（约 15-30 秒）
1. 调用 CreativePlanningAgent 生成场景计划 + 镜头列表
2. 创建 `ScenePlanVersion` + `ShotPlanVersion` + 逐个 `Shot` 记录
3. 自动绑定 `character_binding`（角色/场景/造型图 Asset ID）
4. 调用 `advance_project(SHOT_PLAN_READY)`

**SSE 事件**：
```
project_shot_plan_ready → {from_stage: "visual_bible_ready", to_stage: "shot_plan_ready"}
```

**产物**：
| 存储位置 | 内容 |
|---------|------|
| DB: `scene_plan_versions` | 场景计划 |
| DB: `shot_plan_versions` | 镜头计划版本 |
| DB: `shots` | 每个镜头独立记录（含 character_binding） |
| 本地: `data/projects/{id}/05_shot_plan/` | Shot Plan JSON |

---

### 步骤 11：确认镜头计划（用户决策）

**decision_type**：`confirm_shot_plan`

**选项**：
```json
[
  {"id": "confirm",     "title": "确认镜头计划并生成分镜"},
  {"id": "regenerate",  "title": "重新生成镜头计划"}
]
```

**前端提交后触发**：`POST /workflow/generate-storyboard`

---

### 步骤 12：分镜图生成（异步 Worker）

**触发**：`POST /api/v1/projects/{id}/workflow/generate-storyboard`

**前置校验**：`confirm_shot_plan` 决策已 selected

**执行**：dispatch `generate_storyboard` ToolJob → Worker 异步执行（2-8 分钟）

**Worker 内部**（串行逐帧）：
1. 对每个 Shot，编译图片提示词（含场景图 + 造型图 + 角色定妆图参考）
2. 调用图片生成 Provider（qwen-image-2.0-pro img2img）
3. 上传到 MinIO，写 DB assets + storyboard_frames
4. 写本地 `data/projects/{id}/06_storyboard/frame_XXX.jpg`
5. 全部完成后调用 `advance_project(STORYBOARD_READY)`

**SSE 事件**：
```
project_storyboard_ready → {from_stage: "shot_plan_ready", to_stage: "storyboard_ready"}
director.report          → {task_type: "generate_storyboard", ...}
```

**产物**：
| 存储位置 | 内容 |
|---------|------|
| DB: `storyboard_versions` | 分镜版本记录 |
| DB: `storyboard_frames` | 每帧记录（关联 Shot） |
| DB: `assets` | 每帧图片 Asset |
| DB: `prompt_bundles` | 每帧提示词 bundle |
| MinIO: `projects/{id}/assets/storyboard_frame/` | 分镜图片 |
| 本地: `data/projects/{id}/06_storyboard/` | 分镜图片 |
| 本地: `data/projects/{id}/07_prompt_bundles/` | 提示词 JSON |

---

### 步骤 13：确认分镜图（用户决策）

**decision_type**：`confirm_storyboard`

**选项**：
```json
[
  {"id": "confirm",     "title": "确认分镜图并开始生成视频片段"},
  {"id": "regenerate",  "title": "重新生成分镜图"}
]
```

**前端提交后触发**：`POST /workflow/generate-clips`

**注意**：docs/14 提到的独立 `confirm_cost_clips` 决策类型在代码中不存在。`confirm_storyboard` 的提示文案已包含费用提示。

---

### 步骤 14：视频片段生成（异步 Worker）

**触发**：`POST /api/v1/projects/{id}/workflow/generate-clips`

**前置校验**：`confirm_storyboard` 决策已 selected

**执行**：dispatch `generate_clips` ToolJob → Worker 异步执行（5-15 分钟）

**Worker 内部**（串行逐 Shot）：
1. 读取该 Shot 的分镜图 URL 作为首帧
2. 编译视频提示词
3. 调用视频 Provider（ToAPIs 中转 Grok 视频模型）异步轮询
4. 下载生成的视频，上传 MinIO，写 DB
5. **每个 clip 完成立即发射 SSE 事件**
6. 全部完成后调用 `advance_project(CLIPS_READY)`

**SSE 事件序列**：
```
clip.shot.completed     → {storage_uri, shot_index, start_ms, end_ms}  // 每个 clip 一次
clip.shot.completed     → {...}  // 重复 N 次（N = Shot 数量）
project_clips_ready     → {from_stage: "storyboard_ready", to_stage: "clips_ready"}
director.report         → {task_type: "generate_clips", ...}
```

**前端行为预期**：收到 `clip.shot.completed` 后可将该 clip 填入时间轴对应位置，实现"逐渐填充"效果。收到 `project_clips_ready` 后解锁「合成完整视频」按钮。

**产物**：
| 存储位置 | 内容 |
|---------|------|
| DB: `clip_versions` | 每个 clip 版本（关联 Shot） |
| DB: `assets` | clip 视频 Asset |
| MinIO: `projects/{id}/assets/shot_clip/` | 视频文件 |
| 本地: `data/projects/{id}/08_clips/` | 视频文件 |

---

### 步骤 15：时间线合成（用户主动触发）

**触发方式**：两条路径
- 路径 A（推荐）：`POST /api/v1/projects/{id}/timeline/compose` — 异步 dispatch
- 路径 B：`POST /workflow/generate-timeline` — 同步阻塞

**执行**：TimelineComposerService 使用 ffmpeg 拼接所有 clip + 混入音频轨道

**SSE 事件**：
```
project_timeline_ready → {from_stage: "clips_ready", to_stage: "timeline_ready"}
```

**产物**：
| 存储位置 | 内容 |
|---------|------|
| DB: `timeline_versions` | 时间线版本 |
| MinIO: `projects/{id}/assets/timeline_preview/` | 合成视频 |
| 本地: `data/projects/{id}/09_timeline/` | 合成视频 |

---

### 步骤 16：导出最终视频

**触发**：`POST /api/v1/projects/{id}/exports` body: `{resolution: "720p"|"1080p"}`

**产物**：
| 存储位置 | 内容 |
|---------|------|
| DB: `export_versions` | 导出版本 |
| MinIO: `projects/{id}/assets/export/` | 最终视频 |
| 本地: `data/projects/{id}/10_export/` | 最终视频 |

---

## 四、决策系统完整对照表

| 阶段 | decision_type | 触发时机 | 选项 | 确认后触发的 workflow API |
|------|--------------|---------|------|------------------------|
| audio_analyzed | `select_style_direction` | 音频分析完成后 Director 创建 | 2-3 个风格选项 | `POST /workflow/generate-brief` |
| brief_ready | `confirm_brief` | Brief 生成完成后 | confirm / regenerate | `POST /workflow/generate-narrative` |
| narrative_ready | `confirm_narrative` | 叙事生成完成后 | confirm / regenerate | `POST /workflow/init-visual-bible` |
| visual_bible_ready | `confirm_visual_bible` | 视觉圣经框架初始化后 | confirm / regenerate | `POST /workflow/generate-shot-plan` |
| shot_plan_ready | `confirm_shot_plan` | Shot Plan 生成完成后 | confirm / regenerate | `POST /workflow/generate-storyboard` |
| storyboard_ready | `confirm_storyboard` | 分镜图生成完成后 | confirm / regenerate | `POST /workflow/generate-clips` |

**决策生命周期**：`open` → `selected` / `expired` / `cancelled`

**决策创建方**：
- LangGraph `human_confirmation_gate` 节点
- Director Agent 工具调用 `create_decision_for_action`

**前端决策提交**：`POST /api/v1/projects/{id}/decisions/{decision_id}/select`

---

## 五、SSE 事件完整清单

### 5.1 阶段变更事件（由 StateTransitionService 通过 EventLogService 发射）

| event_type | 触发时机 | payload |
|-----------|---------|---------|
| `project_input_ready` | Spec 激活后 | `{from_stage, to_stage}` |
| `project_audio_analyzed` | 音频分析完成 | `{from_stage, to_stage}` |
| `project_brief_ready` | Brief 生成完成 | `{from_stage, to_stage}` |
| `project_narrative_ready` | 叙事生成完成 | `{from_stage, to_stage}` |
| `project_visual_bible_ready` | 视觉圣经初始化完成 | `{from_stage, to_stage}` |
| `project_shot_plan_ready` | Shot Plan 完成 | `{from_stage, to_stage}` |
| `project_storyboard_ready` | 分镜完成 | `{from_stage, to_stage}` |
| `project_clips_ready` | 所有 clip 完成 | `{from_stage, to_stage}` |
| `project_timeline_ready` | 时间线合成完成 | `{from_stage, to_stage}` |
| `project_export_ready` | 导出完成 | `{from_stage, to_stage}` |
| `project_completed` | 项目完成 | `{from_stage, to_stage}` |

### 5.2 业务进度事件（由 Worker handler 通过 EventLogService 发射）

| event_type | 触发时机 | payload |
|-----------|---------|---------|
| `audio.analysis.progress` | 音频分析进行中 | `{progress: 10/90, message}` |
| `audio.analysis.completed` | 音频分析完成 | `{version_id, bpm, section_count, duration_sec}` |
| `narrative.generating` | 叙事生成中 | `{message}` |
| `narrative.completed` | 叙事生成完成 | `{version_id, version_no, story_arc}` |
| `clip.shot.completed` | 单个 clip 完成 | `{storage_uri, shot_index, start_ms, end_ms}` |
| `director.report` | Director Mode B 汇报完成 | `{task_type, message_preview, session_id}` |

### 5.3 连接管理事件

| event_type | 说明 |
|-----------|------|
| `sse_connected` | SSE 连接建立确认 |
| `: heartbeat` | 每 30 秒心跳（SSE 注释行，不触发 onmessage） |

---

## 六、前端工作台现状分析

### 6.1 布局结构

```
┌──────────────────────────────────────────────────────────────────┐
│ 顶部导航栏：项目名 + 进度条 + 当前阶段标签                       │
├──────────┬────────────────────────────────────┬──────────────────┤
│ 左侧栏    │ 中央工作区                          │ 右侧栏           │
│ 阶段导航   │ 决策卡（浮动）+ 动态内容区            │ AI 导演对话      │
│ 12 个阶段  │                                    │ Chat 窗口        │
│ 列表       │                                    │                  │
└──────────┴────────────────────────────────────┴──────────────────┘
```

### 6.2 各阶段中央工作区当前渲染内容

| 阶段 | 当前渲染 | 问题 |
|------|---------|------|
| `created` | 输入面板（音频上传 + 参考图 + 描述 + 开始创作按钮） | OK |
| `input_ready` | 加载动画（"AI 导演正在分析音乐"） | OK，但无法显示具体进度 |
| `audio_analyzed` | `AudioAnalysisView` 组件（BPM、段落、波形、歌词） | OK |
| `brief_ready` | 通用占位（"AI 导演已生成最新产物，请确认"） | **问题**：无 Brief 内容展示 |
| `narrative_ready` | 通用占位 | **问题**：无叙事剧本内容展示 |
| `visual_bible_ready` | 通用占位 | **问题**：无角色/场景参考图展示 |
| `shot_plan_ready` | `StoryboardReviewer`（镜头列表） | 部分 OK |
| `storyboard_ready` | `StoryboardReviewer`（镜头列表 + 分镜图） | 部分 OK |
| `clips_ready` | `TimelineEditor`（视频片段 + 时间轴） | 部分 OK |
| `timeline_ready` | `TimelineEditor` | 部分 OK |
| `export_ready` | `TimelineEditor` | 缺少导出按钮和下载 |

### 6.3 核心交互问题

**问题 1：决策提交后的竞态**
`handleDecision` 中同时执行三件事：
1. 提交决策（`POST /decisions/{id}/select`）
2. 触发下一步 workflow API（如 `generateBrief`）
3. 发送 Chat 消息"已确认，请继续。"
这三个操作串行执行但没有等待前一步完全落地（尤其 workflow API 可能是同步阻塞的），可能导致后端收到 Chat 消息时 workflow 还没完成。

**问题 2：brief/narrative/visual_bible 阶段无内容展示**
这三个阶段只有一个通用占位卡，用户看不到实际产物内容（Brief 摘要、叙事剧本、角色/场景图），只能通过 Chat 窗口里 Director 的汇报来了解。

**问题 3：决策卡与产物内容分离**
决策卡浮动在最上方，但用户在确认前需要看到对应的产物内容。目前产物内容和决策卡是分离的，体验不连贯。

**问题 4：左侧阶段列表缺乏可操作性**
左侧 12 个阶段只是展示状态，不支持点击跳转到对应内容。并且有些阶段名对用户不友好。

**问题 5：视觉圣经阶段完全没有 UI**
视觉圣经是重要的创作阶段（角色定妆图、场景图、造型变体），但前端没有任何展示和交互界面。

**问题 6：SSE 事件未充分利用**
后端发射了丰富的进度事件（如 `clip.shot.completed`），但前端只是简单地 `triggerRefresh()` 刷新整个项目，没有局部更新 UI（如逐个 clip 填入时间轴）。

---

## 七、前端工作台详细 UI 设计

### 7.1 整体布局定义

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 顶部栏：← 返回 │ 项目名 │ 进度条 │ 当前步骤标签 │ 设置               │
├────────┬─────────────────────────────────────┬───────────────────────────┤
│ 左侧栏  │ 中央产物区                           │ 右侧 AI 导演面板          │
│        │                                     │                         │
│ 步骤导航 │ 纯展示当前阶段产物                    │ 对话消息流                │
│ 7 个步骤 │ （只读 / 可交互取决于阶段）            │ ＋ 决策卡（内嵌在消息流中） │
│        │                                     │ ＋ 消息输入框              │
│        │                                     │                         │
└────────┴─────────────────────────────────────┴───────────────────────────┘
```

**核心设计原则**：
- **中央区只展示产物**：音频分析、Brief 内容、叙事剧本、角色图、分镜图、视频等，不放任何决策按钮
- **右侧面板承载所有交互**：Director 对话、决策卡（风格选择 / 确认 / 重新生成）、进度提示，全部作为对话流的一部分
- **决策卡是特殊消息**：嵌入在 Director 消息之后，用户在对话上下文中做决定，比浮动卡更直观

### 7.2 左侧步骤导航（精简为 7 步）

将 12 个后端技术阶段合并为 7 个用户友好的步骤：

| 步骤 | 导航名称 | 对应后端阶段 | 步骤内子状态 |
|------|---------|------------|------------|
| 1 | 项目设置 | `created` | 上传音频 → 填描述 → 选参考图 → 开始 |
| 2 | 音乐分析 | `input_ready` → `audio_analyzed` | 分析中... → 分析完成 → 选风格 |
| 3 | 创意方案 | `brief_ready` | 生成中... → 查看方案 → 确认 |
| 4 | 故事与视觉 | `narrative_ready` → `visual_bible_ready` | 叙事生成中 → 确认叙事 → 视觉圣经 → 确认视觉 |
| 5 | 分镜规划 | `shot_plan_ready` → `storyboard_ready` | 镜头计划 → 确认 → 分镜生成中 → 确认分镜 |
| 6 | 视频制作 | `clips_ready` → `timeline_ready` | 视频生成中 → 逐 clip 预览 → 合成时间线 |
| 7 | 导出 | `export_ready` → `completed` | 选分辨率 → 导出 → 下载 |

导航交互：
- 当前步骤高亮，已完成步骤打勾，未到达步骤置灰
- **点击已完成步骤可以回看该阶段产物**（只读模式，中央区切换到历史内容）
- 当前步骤有子状态动画（如"生成中"显示旋转图标）

### 7.3 各步骤详细 UI 设计

---

#### 步骤 1：项目设置（`created`）

**中央产物区**：

```
┌─────────────────────────────────────────────────────────────┐
│ ┌───────────────────────────┐  ┌──────────────────────────┐ │
│ │                           │  │ 角色参考图（可选，0/3）    │ │
│ │   音频上传区              │  │ ┌────┐ ┌────┐ ┌────┐    │ │
│ │   拖拽或点击上传           │  │ │ +  │ │ +  │ │ +  │    │ │
│ │   MP3 / WAV              │  │ └────┘ └────┘ └────┘    │ │
│ │                           │  │ JPG/PNG, 最多 3 张       │ │
│ └───────────────────────────┘  └──────────────────────────┘ │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 创意描述                                                 │ │
│ │ 描述你想要的画面风格、叙事节奏...                          │ │
│ │                                                         │ │
│ │                                    [开始创作] ←主按钮     │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**右侧面板**：创作向导（静态步骤提示 01-04），不显示对话，不显示消息输入框。

**Chat 输入状态**：**禁用**。此阶段无 Director 对话，用户完成输入后点按钮即可。

---

#### 步骤 2：音乐分析（`input_ready` → `audio_analyzed`）

**中央产物区——分析中（`input_ready`）**：

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│              🎵 波形可视化（实时动画）                        │
│              ════════════════════════                        │
│                                                             │
│              AI 导演正在分析你的音乐                          │
│              ▓▓▓▓▓▓▓▓▓░░░░░░░░░░  45%                     │
│              正在提取节拍和情绪信息...                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

进度百分比来自 SSE `audio.analysis.progress` 事件。

**中央产物区——分析完成（`audio_analyzed`）**：

```
┌─────────────────────────────────────────────────────────────┐
│ ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐│
│ │ BPM: 128    │  │ 段落数：6     │  │ 时长：3:24          ││
│ │ 调性：Am    │  │ 体裁：Pop    │  │ 情绪：忧郁→振奋      ││
│ └─────────────┘  └──────────────┘  └──────────────────────┘│
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐│
│ │ 波形 + 段落标注时间轴（可交互播放）                        ││
│ │ [Intro][Verse1][Chorus1][Verse2][Chorus2][Outro]         ││
│ │ ▶ 0:00 ─────────●──────────────────────────── 3:24      ││
│ └─────────────────────────────────────────────────────────┘│
│                                                             │
│ ┌──────────────────────┐  ┌──────────────────────────────┐│
│ │ 歌词对齐              │  │ AI 音乐摘要                   ││
│ │ 0:12 月光洒在街角...  │  │ 这首歌以轻柔的钢琴开场...     ││
│ │ 0:18 寻找你的影子...  │  │ 副歌部分能量骤升，适合...     ││
│ └──────────────────────┘  └──────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

**右侧面板——分析中**：
- 显示 Director 消息："正在分析您的音乐，请稍候..."
- **消息输入框禁用**，显示"分析进行中..."

**右侧面板——分析完成**：
- Director 汇报消息（Mode B 自动生成）："音乐分析完成！BPM 128，共 6 个段落，歌词讲述的是..."
- **紧接着显示风格选择决策卡**（内嵌在消息流中）：

```
┌─────────────────────────────────────────┐
│ 🎨 请选择视觉风格方向                     │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ ● 电影感                             │ │
│ │   高对比、暖色调、慢推拉              │ │
│ └─────────────────────────────────────┘ │
│ ┌─────────────────────────────────────┐ │
│ │ ○ 独立风                             │ │
│ │   自然光、颗粒感、跟拍运动            │ │
│ └─────────────────────────────────────┘ │
│ ┌─────────────────────────────────────┐ │
│ │ ○ 霓虹感                             │ │
│ │   强饱和、夜景、冷蓝/紫色调           │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

- **消息输入框启用**，用户可以向 Director 提问（如"电影感具体是什么样的？"）

---

#### 步骤 3：创意方案（`brief_ready`）

用户选完风格后，前端调 `/workflow/generate-brief`（同步 10-20 秒）。

**中央产物区——生成中**：

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│              ✨ 正在构思创意方案...                           │
│              （根据音乐分析和风格方向生成中）                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**中央产物区——生成完成（`brief_ready`）**：

```
┌─────────────────────────────────────────────────────────────┐
│ 创意方案 v1                                                  │
│ ─────────────────────────────────────────────────────────── │
│                                                             │
│ ┌──────────────────────────┐  ┌────────────────────────────┐│
│ │ 叙事模式                  │  │ 风格圣经                    ││
│ │ ● 演唱型混合（60%演唱画面）│  │ 色调：暖黄 + 深蓝对比       ││
│ │ ● 氛围叙事穿插            │  │ 光影：黄金时段侧光          ││
│ │                           │  │ 镜头：35mm 浅景深           ││
│ │ 情绪标签                  │  │ 质感：轻微胶片颗粒           ││
│ │ #怀旧 #温暖 #成长         │  │                             ││
│ └──────────────────────────┘  └────────────────────────────┘│
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 方案摘要                                                 │ │
│ │ 以城市黄昏为主视觉基调，通过演唱者在街头漫步的画面串联     │ │
│ │ 整首歌的情绪弧线。Verse 部分以近景和特写为主，营造...      │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**右侧面板**：
- Director 汇报消息："创意方案已生成！采用演唱型混合叙事，以城市黄昏为..."
- **确认决策卡**（内嵌在消息流中）：

```
┌─────────────────────────────────────────┐
│ 📋 请确认创意方案                         │
│                                         │
│ [✅ 确认方案并继续]   [🔄 重新生成]       │
│                                         │
│ 或在下方输入修改意见                      │
└─────────────────────────────────────────┘
```

- **消息输入框启用**，用户可以输入修改意见（如"我想更偏向复古感"）

**数据来源**：需要新增 API 或复用现有接口获取 Brief 内容。当前后端 `creative_brief_versions` 表有完整数据。

---

#### 步骤 4：故事与视觉（`narrative_ready` → `visual_bible_ready`）

这一步分两个子阶段，中央区内容切换。

**子阶段 A：叙事剧本（`narrative_ready`）**

**中央产物区——生成中**：

```
┌─────────────────────────────────────────────────────────────┐
│              📖 正在构思 MV 叙事剧本...                      │
│              进度条（来自 SSE narrative.generating）          │
└─────────────────────────────────────────────────────────────┘
```

**中央产物区——生成完成**：

```
┌─────────────────────────────────────────────────────────────┐
│ 叙事剧本 v1                                                 │
│ ─────────────────────────────────────────────────────────── │
│                                                             │
│ 故事弧线                                                    │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 黄昏时分，主角走在回忆中的城市街头，从迷茫到释然...        │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌──────────────────────┐  ┌──────────────────────────────┐ │
│ │ 角色列表              │  │ 场景列表                      │ │
│ │ 🧑 主角 - 年轻歌手   │  │ 🌆 城市街头（黄昏）           │ │
│ │   出现：全程          │  │   段落：Verse1, Verse2        │ │
│ │ 👤 回忆中的朋友       │  │ 🎭 排练室                    │ │
│ │   出现：Verse2, Bridge│  │   段落：Chorus1, Chorus2     │ │
│ └──────────────────────┘  └──────────────────────────────┘ │
│                                                             │
│ 段落映射表                                                  │
│ ┌──────────┬────────┬────────┬──────────────────┐          │
│ │ 段落      │ 场景    │ 角色   │ 情绪/剧情         │          │
│ │ Verse1   │ 街头    │ 主角   │ 迷茫、回忆         │          │
│ │ Chorus1  │ 排练室  │ 主角   │ 振奋、爆发         │          │
│ │ ...      │ ...    │ ...    │ ...               │          │
│ └──────────┴────────┴────────┴──────────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

**右侧面板**：Director 汇报 + 确认决策卡（确认叙事剧本 / 重新生成）+ 消息输入框启用。

**子阶段 B：视觉圣经（`visual_bible_ready`）**

用户确认叙事后，前端调 `/workflow/init-visual-bible`，框架初始化后 Director 开始 dispatch 角色/场景图生成任务。

**中央产物区**：

```
┌─────────────────────────────────────────────────────────────┐
│ 视觉圣经                                                    │
│ ─────────────────────────────────────────────────────────── │
│                                                             │
│ 角色参考图                                                  │
│ ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│ │ [定妆图]  │  │ [定妆图]  │  │ 生成中... │                  │
│ │          │  │          │  │  ⟳       │                  │
│ │ 主角     │  │ 朋友     │  │ 路人甲    │                  │
│ │ ✅ 已生成 │  │ ✅ 已生成 │  │ ⏳ 排队中  │                  │
│ └──────────┘  └──────────┘  └──────────┘                  │
│                                                             │
│ 场景参考图                                                  │
│ ┌────────────────┐  ┌────────────────┐                    │
│ │ [宽幅场景图]     │  │ [宽幅场景图]     │                    │
│ │ 城市街头（黄昏） │  │ 排练室          │                    │
│ │ ✅ 已生成        │  │ ✅ 已生成        │                    │
│ └────────────────┘  └────────────────┘                    │
│                                                             │
│ 点击图片可放大查看                                           │
└─────────────────────────────────────────────────────────────┘
```

每张图有状态：⏳排队中 → ⟳生成中 → ✅已生成。图生成完成后 Director Mode B 会在右侧对话中汇报。

**右侧面板**：
- Director 逐张汇报："主角的定妆图已生成，基于您上传的参考图做了风格化处理..."
- 用户可以在对话中说"朋友的图不太满意，换一张"，Director 会 dispatch 重新生成
- 全部生成完毕后，Director 推送**整体确认决策卡**：

```
┌─────────────────────────────────────────┐
│ 🎨 请确认视觉圣经                         │
│ 所有角色和场景参考图已生成完毕              │
│                                         │
│ [✅ 全部满意，继续]   [🔄 整体重新生成]    │
│                                         │
│ 如需修改个别图片，请在下方输入告诉导演      │
└─────────────────────────────────────────┘
```

- **消息输入框启用**，用户可以指定重新生成某张图

---

#### 步骤 5：分镜规划（`shot_plan_ready` → `storyboard_ready`）

**子阶段 A：镜头计划（`shot_plan_ready`）**

**中央产物区**：

```
┌─────────────────────────────────────────────────────────────┐
│ 镜头计划（共 12 个镜头）                                     │
│ ─────────────────────────────────────────────────────────── │
│                                                             │
│ ┌────┬──────┬───────┬────────┬──────┬───────┬─────┐       │
│ │ #  │ 场景  │ 类型   │ 景别    │ 情绪  │ 时长   │ 口型 │       │
│ ├────┼──────┼───────┼────────┼──────┼───────┼─────┤       │
│ │ 01 │ 街头  │ 演唱   │ 中近景  │ 忧郁  │ 4.2s  │ ✓   │       │
│ │ 02 │ 街头  │ 氛围   │ 全景   │ 迷茫  │ 3.0s  │ ✗   │       │
│ │ 03 │ 排练室│ 演唱   │ 特写   │ 振奋  │ 3.5s  │ ✓   │       │
│ │ ...│      │       │        │      │       │     │       │
│ └────┴──────┴───────┴────────┴──────┴───────┴─────┘       │
│                                                             │
│ 时间轴总览（条形图，每个 Shot 一段色块）                      │
│ [01][02][03][04][05][06][07][08][09][10][11][12]            │
│ 0:00 ──────────────────────────────────────── 3:24          │
└─────────────────────────────────────────────────────────────┘
```

**右侧面板**：Director 汇报 + 确认决策卡（确认镜头计划 / 重新生成）。用户可在对话中说"第 3 个镜头时长太短了"，Director 调用 ShotPatchService 修改。

**子阶段 B：分镜图（`storyboard_ready`）**

分镜生成是异步的（2-8 分钟），生成中显示进度。

**中央产物区——生成完成**：

```
┌─────────────────────────────────────────────────────────────┐
│ 分镜图（12 帧）                                              │
│ ─────────────────────────────────────────────────────────── │
│                                                             │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│ │ [分镜图1] │ │ [分镜图2] │ │ [分镜图3] │ │ [分镜图4] │       │
│ │ #01 4.2s │ │ #02 3.0s │ │ #03 3.5s │ │ #04 3.8s │       │
│ │ 演唱·中近 │ │ 氛围·全景 │ │ 演唱·特写 │ │ 叙事·中景 │       │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│ │ [分镜图5] │ │ [分镜图6] │ │ [分镜图7] │ │ [分镜图8] │       │
│ │ ...      │ │ ...      │ │ ...      │ │ ...      │       │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│                                                             │
│ 点击单帧可放大查看详情                                       │
└─────────────────────────────────────────────────────────────┘
```

**右侧面板**：Director 汇报 + 确认决策卡（确认分镜并开始生成视频 / 重新生成）。用户可在对话中指定"第 5 帧重新生成"。

---

#### 步骤 6：视频制作（`clips_ready` → `timeline_ready`）

**中央产物区——生成中**：

```
┌─────────────────────────────────────────────────────────────┐
│ 视频片段生成中（3/12 完成）                                   │
│ ─────────────────────────────────────────────────────────── │
│                                                             │
│ 时间轴（逐渐填充效果）                                       │
│ ┌──────────────────────────────────────────────────────┐   │
│ │ [▶ clip1] [▶ clip2] [▶ clip3] [⏳...] [⏳...] [⏳...]│   │
│ │ ═══════  ═══════  ═══════  ░░░░░░  ░░░░░░  ░░░░░░  │   │
│ └──────────────────────────────────────────────────────┘   │
│ 0:00 ──────────────────────────────────────────── 3:24     │
│                                                             │
│ 已完成的 clip 可点击预览                                     │
└─────────────────────────────────────────────────────────────┘
```

每收到一个 SSE `clip.shot.completed` 事件，对应位置从灰色变为可播放的视频缩略图。

**中央产物区——全部完成（`clips_ready`）**：

```
┌─────────────────────────────────────────────────────────────┐
│ 视频时间轴                                                   │
│ ─────────────────────────────────────────────────────────── │
│                                                             │
│ ┌──────────────────────────────────────────────────────┐   │
│ │ 🔊 音频轨道（波形）                                     │   │
│ │ ═══════════════════════════════════════════════════   │   │
│ │ 🎬 视频轨道（clip 缩略图序列）                          │   │
│ │ [clip1][clip2][clip3][clip4]...[clip12]               │   │
│ └──────────────────────────────────────────────────────┘   │
│ ▶ 0:00 ─────────●──────────────────────────── 3:24        │
│                                                             │
│ ┌─────────────────────────────────────┐                    │
│ │ 当前 clip 预览播放器（大画面）        │                    │
│ │                                     │                    │
│ │                                     │                    │
│ └─────────────────────────────────────┘                    │
│                                                             │
│                    [🎬 合成完整视频]  ← 用户主动触发          │
└─────────────────────────────────────────────────────────────┘
```

**右侧面板**：
- Director 汇报："全部 12 个视频片段已生成完毕！您可以在时间轴上预览..."
- **无决策卡**。此阶段是用户自由预览、选择合成的阶段
- 消息输入框启用，用户可以提问

**时间线合成后（`timeline_ready`）**：中央区切换为完整视频播放器 + 导出选项

---

#### 步骤 7：导出（`export_ready` → `completed`）

**中央产物区**：

```
┌─────────────────────────────────────────────────────────────┐
│ ┌─────────────────────────────────────┐                    │
│ │ 完整 MV 预览播放器                    │                    │
│ │                                     │                    │
│ │          ▶ 播放                      │                    │
│ │                                     │                    │
│ └─────────────────────────────────────┘                    │
│                                                             │
│ 导出选项                                                    │
│ ┌──────────────┐  ┌──────────────┐                        │
│ │ 720p 标清     │  │ 1080p 高清    │                        │
│ │ 约 XX credits │  │ 约 XX credits │                        │
│ │ [导出]        │  │ [导出]        │                        │
│ └──────────────┘  └──────────────┘                        │
│                                                             │
│ 导出完成后：                                                 │
│ [⬇ 下载 MV]  [📤 分享]                                      │
└─────────────────────────────────────────────────────────────┘
```

**右侧面板**：Director 恭喜消息 + 消息输入框启用。

---

### 7.4 消息发送规则（哪个阶段可以 / 不可以发消息）

| 阶段状态 | 消息输入框 | 原因 |
|---------|-----------|------|
| `created` | **禁用** | 项目还没开始，无 Director 上下文，右侧显示创作向导 |
| `input_ready`（分析中） | **禁用** | 后台异步分析中，发消息会触发重复分析任务 |
| `audio_analyzed` | **启用** | 用户可以向 Director 提问分析结果、讨论风格 |
| Brief 生成中（同步等待） | **禁用** | HTTP 请求阻塞中（10-20 秒），显示"生成中..." |
| `brief_ready` | **启用** | 用户可以讨论方案、提修改意见 |
| Narrative 生成中（异步） | **禁用** | 后台 Worker 执行中，显示"叙事剧本生成中..." |
| `narrative_ready` | **启用** | 用户可以讨论剧本 |
| Visual bible 图生成中 | **启用** | 用户可以指定重新生成某张图（Director 工具调用） |
| `visual_bible_ready` | **启用** | 用户可以讨论、指定修改 |
| Shot plan 生成中（同步） | **禁用** | HTTP 请求阻塞中 |
| `shot_plan_ready` | **启用** | 用户可以提修改意见 |
| Storyboard 生成中（异步） | **禁用** | 后台 Worker 执行中（2-8 分钟） |
| `storyboard_ready` | **启用** | 用户可以指定重新生成某帧 |
| Clips 生成中（异步） | **禁用** | 后台 Worker 执行中（5-15 分钟） |
| `clips_ready` | **启用** | 用户自由预览、提问 |
| Timeline 合成中 | **禁用** | ffmpeg 合成中 |
| `timeline_ready` | **启用** | 用户可以提问 |
| `export_ready` / `completed` | **启用** | 自由对话 |

**核心规则**：
- 只要有**正在执行的后台任务**（Worker 异步 或 同步阻塞），消息输入框禁用
- 任务完成后（SSE 阶段变更事件到达），自动启用消息输入框
- **禁用期间右侧面板不是空白**，而是显示进度信息和 Director 的进度提示

### 7.5 用户实际操作路径总结

从用户视角看，整个流程中**用户需要主动操作的节点**只有以下几个：

```
上传音频 + 描述 + 点「开始创作」
         ↓ 等待
选风格方向（在右侧 Chat 中点选）
         ↓ 等待
确认创意方案（在右侧 Chat 中点确认）
         ↓ 等待
确认叙事剧本（在右侧 Chat 中点确认）
         ↓ 等待，期间可以对个别角色图提修改意见
确认视觉圣经（在右侧 Chat 中点确认）
         ↓ 等待
确认镜头计划（在右侧 Chat 中点确认）
         ↓ 等待 2-8 分钟
确认分镜图（在右侧 Chat 中点确认）
         ↓ 等待 5-15 分钟
预览视频 → 点「合成完整视频」
         ↓ 等待 1-2 分钟
预览完整 MV → 选分辨率 → 点「导出」→ 下载
```

6 次确认 + 2 次主动触发（合成 + 导出）= 8 个用户操作点。
其余时间用户可以在右侧 Chat 中和 Director 讨论，或者等待后台任务完成。

### 7.6 "生成中" 过渡状态的 UI 处理

后端没有显式的"generating"阶段，前端需要自己追踪。方案：

1. 前端调 workflow API 后，本地设置 `isGenerating = true`
2. 中央区切换为对应的"生成中"视图（进度动画 / 进度条）
3. SSE 收到阶段变更事件后，`isGenerating = false`，切换到产物展示视图
4. SSE 收到业务进度事件（如 `audio.analysis.progress`、`clip.shot.completed`）时，更新进度 UI

这样用户在等待期间始终有视觉反馈。

---

## 八、与 docs/14 的关键偏差

| 项目 | docs/14 描述 | 代码实际行为 |
|------|------------|------------|
| Brief 生成方式 | 未明确说明 | **同步阻塞**（非异步 Worker） |
| Shot Plan 生成方式 | 未明确说明 | **同步阻塞**（非异步 Worker） |
| Shot Plan 前置校验 | 检查 `confirm_brief` | 代码实际检查 **`confirm_visual_bible`** |
| `confirm_cost_clips` | 提到独立的费用确认决策 | **不存在**，费用提示在 `confirm_storyboard` 文案中 |
| 视觉圣经参考图触发 | 描述为自动串行子任务 | 实际由 **Director 工具调用触发**，非自动 |
| 前端 Chat 消息来源 | 未详细说明 | Chat 消息存在 DB 中，前端每次刷新从 DB 拉取历史 |
| Director Mode B 推送 | SSE 推送消息 | 消息存入 DB 后发 `director.report` SSE，前端收到后刷新拉取 DB 消息 |

---

## 九、文档版本

| 版本 | 日期 | 内容 |
|------|------|------|
| v1.0 | 2026-04-05 | 基于全部后端代码深度审查，覆盖从项目创建到视频导出的完整流程、SSE 事件清单、前端现状分析与改造建议 |
