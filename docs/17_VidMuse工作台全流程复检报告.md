# VidMuse 工作台全流程复检报告

> 复检时间：2026-04-05
> 复检范围：前端工作台 + 后端数据链路全流程（数据结构 → API → SSE → 组件渲染）
> 复检结论：先列问题，再分"已修复"和"待修复"两类

---

## 一、整体架构流转（已确认正确）

| 层 | 实现 | 状态 |
|---|---|---|
| 工作台路由 | `/projects/:id` → `Workbench.tsx`，独立全屏，含返回按钮（ArrowLeft → `/projects`） | ✅ |
| 阶段切换渲染 | `audio_analyzed` → AudioAnalysisView；`shot_plan_ready/storyboard_ready` → StoryboardReviewer；`clips_ready+` → TimelineEditor | ✅ |
| SSE 连接 | `EventSource ?token=` → Redis pubsub → `onmessage` 解析 `event_type` → `triggerRefresh` → `fetchProjectData` | ✅ |
| 决策门控 | 后端 `/workflow/*` 全部校验前置 decision，`decision_required` 前端 StoryboardReviewer 已处理 | ✅ |
| 音频分析触发 | `POST /workflow/analyze-audio` → dispatch ToolJob → Worker 异步 | ✅ |
| Storyboard/Clips 触发 | `generateStoryboard/generateClips` → dispatch ToolJob → Worker 异步 | ✅ |
| Chat 流式输出 | `/v1/chat/completions stream=true` → 行缓冲解析 SSE delta → 逐字追加 | ✅ |

---

## 二、本次改动复检（2026-04-05 凌晨改动内容）

### 已修复的问题

#### ✅ 中英文切换问题（大部分已修复）

以下硬编码英文文本已全部改为走 `t()` + `i18n` 配置：

| 位置 | 修复内容 |
|---|---|
| `Workbench.tsx` L314 | Prompt textarea `placeholder` → `t('workbench.promptPlaceholder')` |
| `Workbench.tsx` L358 | 进度条 `COMPLETE` → `t('workbench.completeStatus')` |
| `AudioAnalysisView.tsx` L285 | `Chord Progression` 标签 → `t('audioAnalysis.chordProgression')` |
| `AudioAnalysisView.tsx` L307-315 | Genre mock 数据 → `t('audioAnalysis.genreMock1/2/3')` |
| `AudioAnalysisView.tsx` L329-333 | 乐器 fallback → `t('audioAnalysis.instruments.*')` |
| `AudioAnalysisView.tsx` L345 | `Sonic Map:` → `t('audioAnalysis.sonicMap')` |
| `AudioAnalysisView.tsx` L351 | `Visual Advice:` → `t('audioAnalysis.visualAdvice')` |
| `AudioAnalysisView.tsx` L353 | fallback 文本 → `t('audioAnalysis.visualAdviceText')` |
| `StoryboardReviewer.tsx` L40 | Mock 歌词 → `t('storyboard.mockLyric1/2')` |
| `StoryboardReviewer.tsx` L168 | 无歌词段落 → `t('storyboard.noLyrics')` |

同步在 `i18n/index.ts` 中补充了所有对应 en/zh 翻译 key。

---

## 三、仍未修复的问题（待处理）

### 🔴 严重 1：后端音频分析 API 漏发 5 个字段

**位置**：`backend/app/api/v1/audio_analysis.py` → `GET /api/v1/projects/{id}/audio-analysis/active`

**现状**：接口返回 dict 中缺少以下 5 个字段，模型里有、`_persist()` 也写入了 DB，但 API 序列化时遗漏：

```python
# 缺失字段（backend/app/api/v1/audio_analysis.py 第55-69行）
# chord_progression  → aa.chord_progression
# instrumentation    → aa.instrumentation
# five_second_analysis → aa.five_second_analysis
# key_scale          → aa.key_scale
# genre              → aa.genre
```

**影响**：
- `analysis?.chord_progression` 永远为 undefined → 和弦进行区块永不显示
- `analysis?.key_scale` 永远为 undefined → 调式永远显示 "N/A"
- `analysis?.genre` 永远为 undefined → 流派永远显示 mock 数据
- `analysis?.instrumentation` 永远为 undefined → 配器永远显示 fallback

**修复方案**：在 `audio_analysis.py` 的 `ok(data={...})` 里追加这 5 个字段。

---

### 🔴 严重 2：`quality_summary` 字段名前后端根本不对齐

**现状**：

后端 `_persist()` 中将完整 Omni 输出直接写入 `quality_summary`：
```python
# backend/app/services/audio_analysis_service.py 第234行
quality_summary=omni_result  # omni_result 的顶层 key 是 overall_analysis, style_caption 等
```

前端 TypeScript 类型和渲染代码访问的是：
```ts
// frontend/src/types/index.ts 第71-77行
quality_summary: {
  music_summary: string;        // ❌ 不存在于 omni_result
  visual_suggestion: string;    // ❌ 不存在于 omni_result
  ...
}
```

```tsx
// frontend/src/components/workbench/AudioAnalysisView.tsx 第347行
analysis?.quality_summary?.music_summary      // → undefined，显示 fallback
// 第353行
analysis?.quality_summary?.visual_suggestion  // → undefined，显示 fallback
```

**根因**：`omni_result` 的实际顶层 key 是 `style_caption`（对应 music_summary）、`overall_analysis.mood` + `editing_guidance`（对应 visual_suggestion），前端类型定义与后端实际结构从未对齐。

**修复方案二选一**：
- 方案 A（推荐）：后端在 API 序列化时做字段映射，返回前端期待的 `music_summary` 和 `visual_suggestion`
- 方案 B：前端修改访问路径 `quality_summary.style_caption` 和 `quality_summary.overall_analysis.mood`

---

### 🔴 严重 3：`section_map` 数据结构前后端不对齐

**现状**：

后端 `_persist()` 优先用 `structure_segments` 写入 `section_map`（Omni 正常时）：
```python
# backend/app/services/audio_analysis_service.py 第216-222行
section_map = structure_segments
# structure_segments 元素结构：
# { "segment_id": ..., "type": "verse", "start_time": 0, "end_time": 25, ... }
```

前端消费时用的是 `section.end - section.start`（没有 end/start 字段，是 end_time/start_time）和 `section.label`（字段名应为 `type`）：
```tsx
// frontend/src/components/workbench/AudioAnalysisView.tsx 第164行
const width = ((section.end - section.start) / duration) * 100;  // → NaN
// 第176行
{section.label}  // → undefined
```

**后果**：Omni 正常工作时，段落色带宽度全为 NaN（不显示），hover tooltip 为空。只有 Omni 退回 fallback（用 `music_structure_summary.sections`）时才正常，因为那个结构有 `start/end/label`。

**修复方案**：后端在写入 `section_map` 前统一转换为 `{start, end, label}` 格式，或前端兼容两种 key。

---

### 🔴 严重 4：音频播放器是伪实现，无实际音频

**现状**：
- `audioRef` 定义了但完全未使用，无 `<audio>` 标签
- 播放逻辑是 `setInterval` 推进 `currentTime`，与音频无关
- `duration` 硬编码 `240`（4 分钟 mock）
- 后端 `/audio-analysis/active` 未返回音频 URL（`AudioAnalysisVersion` 有 `audio_asset_id`，但 API 没有关联 Asset 的 `storage_uri`）

**修复方案**：后端 API 追加 `audio_url` 字段（通过 `audio_asset_id` 查 Asset 的 `storage_uri`）；前端挂 `<audio>` 元素，用 `onLoadedMetadata` 读取真实 `duration`。

---

### 🟡 中等 5：`composeTimeline` 走同步路由（会阻塞 HTTP 连接）

**现状**：
```ts
// frontend/src/services/api.ts
composeTimeline: async (projectId) => {
  // 注释写着"已修复"，但修复方向反了
  return api.post(`/projects/${projectId}/workflow/generate-timeline`);
}
```

`/workflow/generate-timeline` 对应 `workflow.py`，是**同步**调用 `TimelineComposerService`（ffmpeg 合成，1-2 分钟），HTTP 连接会超时。

正确路由是 `/projects/{id}/timeline/compose`（对应 `timeline.py`），异步 dispatch ToolJob，立即返回 job_id。

**修复方案**：`api.ts` 中改回 `timeline/compose`。

---

### 🟡 中等 6：`ExportModal` 被错误绑定到合成而非导出

**现状**：
```tsx
// frontend/src/components/workbench/TimelineEditor.tsx
<ExportModal
  onExport={handleCompose}  // ← 触发的是合成时间线，不是导出！
/>
```

用户打开导出弹窗选好分辨率/帧率点确认，实际触发的是 `composeTimeline`。导出接口 `POST /api/v1/projects/{id}/exports` 完全未被调用。

**修复方案**：实现真正的导出逻辑，或明确拆分"合成"按钮和"导出"按钮。

---

### 🟡 中等 7：`brief_ready`/`narrative_ready`/`visual_bible_ready` 三个阶段无专属视图

**现状**：`Workbench.tsx` 的 `renderMainContent()` 对这三个阶段均 fall through 到默认输入 Grid，显示"上传音频"界面。

- 用户停在这些阶段时，实际产物（创意方案 / 叙事剧本 / 视觉圣经）无任何展示
- 这些阶段内点击"启动 AI 分析"按钮，后端会返回 422 `invalid_stage`，前端无错误提示

**修复方案**：增加 BriefView、NarrativeView、VisualBibleView 组件，或至少在这些阶段隐藏无效的上传 / 分析按钮。

---

### 🟢 低级 8：`AudioAnalysisView.tsx` 仍有一处硬编码英文

**位置**：`frontend/src/components/workbench/AudioAnalysisView.tsx` 第 150 行

```tsx
<p>No alignment data available</p>  // ❌ 未走 i18n
```

歌词为空时显示此文字，中文模式下仍显示英文。`i18n/index.ts` 中也尚未添加对应 key。

---

### 🟢 低级 9：`StoryboardReviewer` loading 文字用了字符串替换 hack

**位置**：`frontend/src/components/workbench/StoryboardReviewer.tsx` 第 104 行

```tsx
{t('timeline.loading').replace('Timeline', 'Storyboard')}
```

中文模式：`t('timeline.loading')` = "正在加载时间线..."，`replace('Timeline', ...)` 不匹配，结果保持原文，勉强可接受。英文模式下工作正常但逻辑脆弱。建议改为独立的 i18n key `storyboard.loading`。

---

## 四、前后端字段对照总表

### 音频分析（`GET /audio-analysis/active` 响应）

| 字段 | 后端 API 现状 | 前端 TypeScript 类型 | 状态 |
|---|---|---|---|
| `id` | ✅ 返回 | ✅ | 正常 |
| `bpm` | ✅ 返回 | ✅ | 正常 |
| `beat_map` | ✅ 返回 | ✅ | 正常 |
| `section_map` | ✅ 返回 | `{start, end, label}[]` | ⚠️ 结构不对齐（问题 3） |
| `energy_curve` | ✅ 返回 | ✅ | 正常 |
| `lyrics_alignment` | ✅ 返回 | `{time, text}[]` | ✅ |
| `quality_summary` | ✅ 返回（含完整 omni_result） | `{music_summary, visual_suggestion}` | ❌ 字段名不对齐（问题 2） |
| `chord_progression` | ❌ 未返回 | `{section, chords[]}[]` | ❌ 漏字段（问题 1） |
| `instrumentation` | ❌ 未返回 | `string[]` | ❌ 漏字段（问题 1） |
| `five_second_analysis` | ❌ 未返回 | `{start,end,energy,mood,instruments[]}[]` | ❌ 漏字段（问题 1） |
| `key_scale` | ❌ 未返回 | `string?` | ❌ 漏字段（问题 1） |
| `genre` | ❌ 未返回 | `string?` | ❌ 漏字段（问题 1） |
| `audio_url` | ❌ 未返回 | 无（需新增） | ❌ 播放器需要（问题 4） |

### Omni `quality_summary` 实际结构 vs 前端期待

| 前端期待 key | 后端实际 key | 对齐状态 |
|---|---|---|
| `quality_summary.music_summary` | `quality_summary.style_caption` | ❌ |
| `quality_summary.visual_suggestion` | `quality_summary.editing_guidance.per_section[0]...` | ❌ |
| `quality_summary.music_structure_summary` | `quality_summary.music_structure_summary` | ✅ |
| `quality_summary.emotion_arc` | `quality_summary.emotion_arc` | ✅ |
| `quality_summary.editing_guidance` | `quality_summary.editing_guidance` | ✅ |

---

## 五、修复优先级建议

| 优先级 | 问题 | 工作量 | 影响 |
|---|---|---|---|
| P0 | 后端 API 补齐 5 个漏字段 + 返回 audio_url | 小（10 行） | 音频分析数据完全正确展示 |
| P0 | `quality_summary` 字段名映射（后端或前端） | 小（5-10 行） | Sonic Map / Visual Advice 显示真实内容 |
| P0 | `section_map` 结构统一（后端写入前转换） | 小（10 行） | 段落色带正确显示 |
| P1 | `composeTimeline` 改回异步路由 `timeline/compose` | 极小（1 行） | 合成不阻塞 HTTP |
| P1 | ExportModal 绑定修正 | 中（需实现导出 API 调用） | 导出功能实际可用 |
| P2 | 音频播放器接入真实音频 | 中 | 播放功能实际可用 |
| P2 | brief/narrative/visual_bible 阶段补充占位视图 | 中 | 用户体验连贯 |
| P3 | AudioAnalysisView L150 补 i18n key | 极小（2 行） | 中文完整 |
| P3 | StoryboardReviewer loading 文字改为独立 key | 极小（2 行） | 代码健壮 |

---

## 六、文档版本

| 版本 | 日期 | 内容 |
|---|---|---|
| v1.0 | 2026-04-05 | 初始建立，基于全代码复检，含改动前后对比分析 |
