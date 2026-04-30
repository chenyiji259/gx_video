# 20 - VidMuse 前后端流程改造方案

**创建时间**: 2026-04-07
**背景**: 梳理当前前后端流程问题，明确改造目标与执行方向

---

## 一、问题概述

用户原始提问：我的前端，目前设计由问题，[Image #6] ，你看图片，首先是这样的工作台左边的流程，项目设置，音乐分析，创意，没
问题，应该还有一个界面，剧本创作，而不是融合成故事与视觉，应该是分开来，剧本，然后视觉圣经，结合我们的右边对话ui的确认
和汇总机制，我从剧本开始，剧本生成完了对吧，确认，进入下一步，，接下来就是问题所在了，需要重新设计，结合前后端
，前端确认剧本后，后端进入了视觉圣经阶段对吧，这阶段输出文本视觉内容+角色图和长地图对不对，这里，确认剧本后，后端进行，
结合我们sse推流和前面的阶段那样的流程，后端完成后，前端接收sse，然后请求数据加载页面，视觉圣经在剧本确认后后端完全执行
完成了，入库了，minio，数据库了，整个阶段完成了，然后sse才推流，也就是入库完成了，sse就可以推送一个阶段已完成的信息，前
端接受，然后请求图片数据和视觉方案数据，去渲染对应的视觉圣经的页面，加载图片和方案，然后不是还有汇总哪里对不对，这里也
推送，然后确认信息，是这样一个流程，这是目前视觉圣经的，然后，到了分镜计划plan了对不对呢？这里我们前端这里就展示分镜计
划就可以了，分镜计划llm输出了之后，我们后端就开始落地入库对不对，入口完成了了，发送sse流前端，汇总和确认，前端加载分镜
计划和渲染数据在这个工作台阶段的页面；下一步了，由改变了。用户确认了镜头计划shot
plan后，我的后端是不是进入了生成镜头首帧了对吧，我先说说前端的，确认分镜计划，然后界面就加载到视频制作哪里了，一个视频
编辑器和音频播放的pr类型的工作台，显示正为你生成视频，后端的工作是，以一个shot为一个流程，结合shotplan，视觉圣经，角色
图，场地，是不是要生成对应shotplan的首帧图对吧，然后llm再基于图去生成llm生成视频提示词，然后发起视频生成对吧，开始视频
生成，视频生成完成，入库完了，就推送sse，第一个视频已经完成了，到这里为一个完整的闭环，一个shot的完成，然后基于sse，前
端获取视频，然后加载到视频制作哪里的编辑界面哪里，前端开始展示，视频加载到视频界面，按照shot1
shot2的去填充。这个过程，后端不在每一个sse都对推送确认选项卡了，到了这里，视频的生成不再是每一个都要确认了，而是后端有
触发对应的shot重新生成的接口或者方式，前端哪里去点击去触发单个shot的重新生成，重新执行我们从首帧图的重新生成到视频生成
的闭环。一个shot的完整闭环，后端是并发去执行的，不再依赖与导演去调度了，导演只负责审核最终的，按照用户去限制单个用户限
制并发三个三个shot同时进行这个闭环，完成一个后释放一个，推送一个，前端加载一个，也即是不在是导演去调度了，是我们的代码
驱动，只有导演进行汇总和审核就行了，推送机制也变了，sse流消息也变了，前端右边的ui是每一个shot的导演汇总，不再通过这个对
话ui哪里确认，没有确认机制了[Image #8] 你梳理一下我说的问题，后面的内容是改动比较大和复杂的，前面的不那么复杂，但也是涉
及前端改动和后端的改动，你需要梳理一下，告诉我你的理解

当前前端工作台的阶段划分与后端工作流不一致，存在阶段合并、交互模式不统一等问题。
同时，视频制作阶段的调度模式需要从"导演逐个调度"改为"代码驱动并发"。

---

## 二、前端侧边栏阶段拆分

### 现状

```
项目设置 → 音乐分析 → 创意方案 → 故事与视觉 → 分镜规划 → 视频制作 → 导出
```

### 问题

"故事与视觉"将**剧本创作**和**视觉圣经**合并为一个页面，但后端是两个独立阶段：
- `NARRATIVE_READY`（叙事剧本）
- `VISUAL_BIBLE_READY`（视觉圣经）

### 改为

```
项目设置 → 音乐分析 → 创意方案 → 剧本创作 → 视觉圣经 → 镜头计划 → 视频制作 → 导出
```

**改动范围**：
- 前端：侧边栏导航配置、路由、新增剧本创作页面、拆分视觉圣经页面
- 后端：无（后端已经是分开的两个阶段）

---

## 三、剧本 → 视觉圣经 → 镜头计划：统一交互模式

这三个阶段走**相同的交互模式**：

### 流程

```
用户在右侧对话确认上一阶段
  ↓
后端开始执行（LLM生成 / 图片生成 / 入库 / MinIO）
  ↓
前端停留在当前页面，显示 loading 状态
  ↓
后端全部完成（入库完毕）→ SSE 推送"阶段完成"事件
  ↓
前端收到 SSE → 请求数据 API → 拿到完整数据
  ↓
数据到了才渲染并切换到新阶段页面（不是先进页面再等数据）
  ↓
右侧对话推送汇总 + 确认选项
  ↓
用户确认 → 触发下一阶段
```

### 关键设计原则

1. **SSE 是在后端完全落库之后才推送**，不是流式推中间结果
2. **前端不提前进入目标页面**，数据到了才渲染切换（避免空壳占位体验）
3. 右侧对话 UI 继续使用汇总+确认机制

### 各阶段页面内容

| 阶段 | 页面展示内容 |
|------|------------|
| 剧本创作 | 故事弧线、角色定义、场景定义、段落映射 |
| 视觉圣经 | 角色参考图 + 场景参考图 + 视觉方案文本 |
| 镜头计划 | Shot Plan 列表（每个镜头的时间/角色/场景/镜头语言/情绪等） |

---

## 四、视频制作阶段（核心改造，大改动）

### 4.1 触发时机

用户在"镜头计划"页面**确认 shot plan** 后，前端跳转到**视频制作**页面。
这个页面是一个 PR 风格的视频编辑器（视频轨道 + 音频时间轴），初始显示"正在为你生成视频"。

> 注意：视频制作页面与前面阶段不同——需要先进入编辑器页面，然后逐 shot 填充视频。

### 4.2 单个 Shot 的完整闭环

```
Shot N 开始
  ↓
① 读取 shot_plan（该 shot 的规格）+ visual_bible（角色图/场景图）
  ↓
② LLM 基于上游数据生成图片提示词 → 调用图片生成 API → 生成首帧图
  ↓
③ LLM 基于首帧图 + shot 规格生成视频提示词 → 调用视频生成 API → 生成视频
  ↓
④ 视频生成完成 → 入库（DB + MinIO）
  ↓
⑤ SSE 推送"Shot N 完成"
  ↓
⑥ 前端收到 SSE → 请求该 shot 视频数据 → 加载到编辑器对应位置
```

### 4.3 并发模式（核心架构变化）

**现状**：导演 Agent 逐个调度每个 shot 的生成
**改为**：代码驱动并发执行，导演不再参与调度

#### 并发规则

- 单用户并发上限 **3 个 shot** 同时执行闭环
- 完成一个 → 释放一个槽位 → 推送一个 SSE → 前端加载一个 → 启动下一个排队的 shot
- 导演**不再参与每个 shot 的调度**
- 导演只负责**最终汇总审核**

#### 执行流程

```
shot plan 确认后
  ↓
取前 3 个 shot → 并发执行闭环
  ↓
Shot 1 完成 → SSE 推送 → 前端加载 → 释放槽位 → 启动 Shot 4
Shot 2 完成 → SSE 推送 → 前端加载 → 释放槽位 → 启动 Shot 5
Shot 3 完成 → SSE 推送 → 前端加载 → 释放槽位 → 启动 Shot 6
  ↓
... 直到全部 shot 完成
  ↓
导演汇总审核 → SSE 推送最终汇总
```

### 4.4 SSE 推送机制变化

**之前**：每个阶段推送 → 右侧对话展示确认按钮 → 用户逐个确认
**改为**：

- 每个 shot 完成推一条 SSE（事件类型如 `shot_clip_completed`）
- 右侧对话展示**每个 shot 的导演汇总评价**（只读信息，无确认按钮）
- **没有逐 shot 确认机制**
- 全部完成后，导演做最终汇总

### 4.5 单 Shot 重新生成机制

**不再通过右侧对话确认/拒绝来触发重新生成**，改为：

- 前端视频编辑器中，用户**点击某个 shot 的重新生成按钮**
- 前端调用后端**单 shot 重新生成 API**
- 后端重新执行该 shot 的完整闭环（首帧图重新生成 → 视频提示词重新生成 → 视频重新生成）
- 完成后入库 → SSE 推送 → 前端替换该 shot 的视频

```
POST /api/v1/projects/{project_id}/shots/{shot_id}/regenerate

触发：
  首帧图重新生成 → 视频提示词重新生成 → 视频重新生成 → 入库 → SSE → 前端替换
```

### 4.6 右侧对话 UI 变化

| 内容 | 之前 | 改为 |
|------|------|------|
| Shot 完成消息 | 确认按钮 | 只读：导演对该 shot 的汇总评价 |
| 重新生成触发 | 右侧对话拒绝按钮 | 编辑器内 shot 重新生成按钮 |
| 全部完成 | 逐个确认 | 导演最终汇总（只读） |

---

## 五、改动范围总览

| 区域 | 改动内容 | 复杂度 | 涉及 |
|------|---------|--------|------|
| 前端侧边栏 | "故事与视觉"拆为"剧本创作"+"视觉圣经" | 低 | 前端 |
| 前端剧本页面 | 新增独立的剧本展示页面 | 中 | 前端 |
| 前端视觉圣经页面 | 从合并页拆出，独立渲染角色图+场景图 | 中 | 前端 |
| 前端镜头计划页面 | "分镜规划"改名，展示 shot plan 数据 | 低-中 | 前端 |
| 前端页面切换逻辑 | 数据到了才渲染页面，不提前进入空壳 | 中 | 前端 |
| 前端视频制作页面 | PR 风格编辑器，shot 逐个填充，单 shot 重新生成按钮 | **高** | 前端 |
| 后端并发执行器 | shot 闭环从导演调度改为代码驱动并发（3 并发限制） | **高** | 后端 |
| 后端单 shot 重新生成 API | 新增接口，触发单个 shot 完整闭环 | **高** | 后端 |
| SSE 协议 | 新增 `shot_clip_completed` 事件类型，视频阶段去掉确认推送 | 中 | 前后端 |
| 右侧对话 UI | 视频阶段改为只读汇总（每 shot 导演评价），无确认按钮 | 中 | 前端 |

---

## 六、代码分析结果

### 6.1 前端侧边栏（改动点已确认）

**文件**: `frontend/src/components/workbench/ProcessNodes.tsx` 第 22-30 行

```typescript
// 现状
const STAGES = [
  { id: 'setup', backendStages: ['created'], label: '项目设置', icon: Settings },
  { id: 'audio', backendStages: ['input_ready', 'audio_analyzed'], label: '音乐分析', icon: Music },
  { id: 'brief', backendStages: ['brief_ready'], label: '创意方案', icon: Lightbulb },
  { id: 'visual', backendStages: ['narrative_ready', 'visual_bible_ready'], label: '故事与视觉', icon: Sparkles },  // ← 问题：合并了两个阶段
  { id: 'shot', backendStages: ['shot_plan_ready', 'storyboard_ready'], label: '分镜规划', icon: BookOpen },
  { id: 'production', backendStages: ['clips_ready', 'timeline_ready'], label: '视频制作', icon: Clapperboard },
  { id: 'export', backendStages: ['export_ready', 'completed'], label: '导出', icon: Upload }
];
```

**改为**：
```typescript
const STAGES = [
  { id: 'setup', backendStages: ['created'], label: '项目设置', icon: Settings },
  { id: 'audio', backendStages: ['input_ready', 'audio_analyzed'], label: '音乐分析', icon: Music },
  { id: 'brief', backendStages: ['brief_ready'], label: '创意方案', icon: Lightbulb },
  { id: 'narrative', backendStages: ['narrative_ready'], label: '剧本创作', icon: BookText },          // 拆出
  { id: 'visual', backendStages: ['visual_bible_ready'], label: '视觉圣经', icon: Sparkles },          // 拆出
  { id: 'shot', backendStages: ['shot_plan_ready'], label: '镜头计划', icon: BookOpen },                // 去掉 storyboard_ready
  { id: 'production', backendStages: ['storyboard_ready', 'clips_ready', 'timeline_ready'], label: '视频制作', icon: Clapperboard },
  { id: 'export', backendStages: ['export_ready', 'completed'], label: '导出', icon: Upload }
];
```

### 6.2 前端页面组件（已存在，无需新建）

**关键发现**：NarrativeView 和 VisualBibleView 组件**已经独立存在**，只是被合并到同一个侧边栏项下。

| 组件 | 文件 | 状态 |
|------|------|------|
| NarrativeView | `frontend/src/components/workbench/NarrativeView.tsx` | 已存在，展示故事弧线/角色/场景/段落映射 |
| VisualBibleView | `frontend/src/components/workbench/VisualBibleView.tsx` | 已存在，展示角色图+场景图+进度 |

**Workbench.tsx 第 305-373 行** 的 `renderContent()` 已经根据 stage 分别渲染，无需改动。

### 6.3 前端页面切换逻辑（需要改动）

**文件**: `frontend/src/pages/Workbench.tsx`

**现状问题**：SSE 通知后立即 `setCurrentStage` + `triggerRefresh`，viewStage 自动跟随切换到新阶段页面，**然后才异步 fetchProjectData**。这导致先进页面再等数据。

**需要改为**：
1. SSE 通知后先 `triggerRefresh` 获取数据
2. 数据加载完成后再 `setViewStage` 切换页面
3. 加载期间显示 loading 状态，停留在当前页面

**关键改动文件**：
- `frontend/src/lib/sse.ts` — REFRESH_EVENTS 处理逻辑
- `frontend/src/pages/Workbench.tsx` — viewStage 同步逻辑
- `frontend/src/stores/projectStore.ts` — 状态管理

### 6.4 后端调度（已具备改造基础）

**关键发现**：

1. **异步任务基础设施完备**：
   - Redis 队列（LPUSH/BRPOP）
   - Worker 并发控制（asyncio.Semaphore）
   - 分布式锁（Redis SET NX）
   - 任务恢复机制

2. **Shot 重新生成 API 已存在**：
   - `POST /api/v1/projects/{project_id}/shots/{shot_id}/regenerate`
   - `ShotRegenerationService.regenerate()` 已实现

3. **导演当前的调度方式**（需要改造）：
   - `storyboard_ready` → 导演输出 `next_action: generate_clips` → 触发 clip_node
   - `clips_ready` → 导演输出 `next_action: generate_timeline` → 触发 timeline_node
   - 这是**线性顺序调度**，需要改为代码驱动并发

4. **Worker 并发配置**：
   - 当前 `max_concurrent_jobs: 4`���全局）
   - 需要新增**每用户 clip 并发限制: 3**

### 6.5 SSE 事件协议（需要新增事件类型）

**现有事件类型**：
```
audio.analysis.progress / completed
shot_plan.generating / completed
storyboard.generating / completed
narrative.generating / completed
visual_bible.character_ref.completed / failed
visual_bible.scene_ref.completed / failed
```

**需要新增**：
```
clip.shot.started     — 单个 shot 开始生成（首帧→视频完整闭环）
clip.shot.completed   — 单个 shot 视频生成完成
clip.shot.failed      — 单个 shot 生成失败
clips.all_completed   — 全部 shot 生成完成，触发导演汇总
clips.progress        — 整体进度（current/total）
```

### 6.6 改造执行方案

**按优先级排序**：

#### Phase 1: 前端侧边栏拆分（低风险，快速见效）
1. 修改 `ProcessNodes.tsx` STAGES 配置
2. 确认 Workbench.tsx renderContent() 无需改动
3. 验证阶段切换和锁定逻辑

#### Phase 2: 页面切换逻辑改造（中风险）
1. 修改 SSE 处理：数据到了才切换页面
2. 增加 loading 状态管理
3. 测试各阶段转换

#### Phase 3: 后端 Shot 并发执行器（高风险，核心改造）
1. 新增 `ShotPipelineService` — 编排单 shot 闭环（首帧→视频→入库）
2. 新增并发控制器 — 每用户 3 并发限制
3. 修改 clip_node — 从"导演触发单次"改为"代码批量分发"
4. 新增 SSE 细粒度事件
5. 修改导演 Prompt — 去掉 shot 级调度，只保留最终汇总

#### Phase 4: 前端视频编辑器改造（高风险）
1. 接收 shot 级 SSE，逐个填充视频
2. 单 shot 重新生成按钮 → 调用已有 API
3. 右侧对话改为只读汇总

---

## 七、执行记录

### Phase 1 + Phase 2（已完成 2026-04-07）

**改动文件**：
| 文件 | 改动内容 |
|------|---------|
| `frontend/src/components/workbench/ProcessNodes.tsx` | STAGES 拆分：故事与视觉 → 剧本创作 + 视觉圣经；分镜规划 → 镜头计划；storyboard_ready 归入视频制作 |
| `frontend/src/pages/Workbench.tsx` | shot_plan_ready 独立渲染，storyboard_ready 归入 TimelineEditor |
| `frontend/src/i18n/index.ts` | 中英文新增 narrative 阶段翻译 |
| `frontend/src/lib/sse.ts` | 去掉 SSE 立即 setCurrentStage 和 setIsGenerating(false)，改为 fetchProjectData 自然更新 |

### Phase 3（已完成 2026-04-07）

**改动文件**：
| 文件 | 改动内容 |
|------|---------|
| `backend/app/services/clip_service.py` | 串行 for 循环改为 asyncio.Semaphore(3) 并发；新增 clip.shot.started / clip.shot.failed / clips.all_completed SSE 事件推送；锁超时调整为并发模式 |
| `prompts/system/director.md` | storyboard_ready/clips_ready 段落：导演不再逐 shot 调度，改为3并发自动生成，只做最终汇总 |
| `frontend/src/lib/sse.ts` | 新增 clip.shot.started / clip.shot.failed / clips.all_completed 事件处理；REFRESH_EVENTS 新增3个clip事件 |

### Phase 4（已完成 2026-04-07）

**改动文件**：
| 文件 | 改动内容 |
|------|---------|
| `frontend/src/services/api.ts` | 新增 shotService.regenerate() 方法，调用 POST /shots/{shotId}/regenerate |
| `frontend/src/components/workbench/TimelineEditor.tsx` | clip 卡片 hover 显示"重新生成"按钮；regenerating 状态 overlay（Loader2）；handleRegenerateShot 调用 shotService；regeneratingShots Set 状态管理 |
| `frontend/src/components/workbench/AIDirectorPanel.tsx` | 视频制作阶段（storyboard_ready/clips_ready/timeline_ready）隐藏确认按钮和输入框，显示只读提示 |
