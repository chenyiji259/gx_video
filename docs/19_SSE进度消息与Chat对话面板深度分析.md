# SSE 进度消息与 Chat 对话面板深度分析

**文档日期**: 2026-04-06
**分析范围**: 后端 SSE 事件推送机制 + 前端 SSE 接收处理 + Chat 对话消息渲染流程
**解决依据**: 代码驱动，基于 `backend/` 和 `frontend/src/` 实际源码分析

---

## 一、问题描述

### 1.1 用户期望的交互体验

用户点击"开始创作"后，期望在 **AI Director 右侧对话面板**中看到类似这样的实时消息流：

```
[AI Director] 我已经接收到你的创作请求，正在为你分析音频和创意。
[AI Director] 正在分析音频，请稍候...
[AI Director] 音频分析完成，BPM: 120，正在构思叙事剧本...
[AI Director] 正在设计创意方案...
[AI Director] 创意方案已生成，请选择你喜欢的风格方向。
```

### 1.2 当前的交互体验

用户在左侧工作台看到进度条和文字提示（`generatingMessage`），但 **AI Director 对话面板中没有任何实时消息**，直到整个流程完成后才会有一个完整的 Director 汇报消息出现。

```
# 当前实际流程

[User] 开始创作
[AI Director] (无任何消息，直到几秒/几分钟后...)

# 流程完成后，突然出现：
[AI Director] 已完成音频分析。BPM: 120，段落结构: 3段，...
              请选择你喜欢的风格方向...
```

### 1.3 问题本质

| 维度 | 当前实现 | 期望实现 |
|------|---------|---------|
| 进度消息展示位置 | 输入框 placeholder（`generatingMessage`） | Chat 对话区内作为消息渲染 |
| 进度消息推送时机 | 无中间进度推送 | 每个关键步骤推送一条消息 |
| Director 汇报时机 | 任务完成后一次性汇报 | 可选：实时进度作为消息 + 最终汇报 |
| SSE 事件利用率 | `audio.analysis.progress` 仅更新状态变量 | 应同时生成对话消息 |

---

## 二、代码架构分析

### 2.1 后端 SSE 推送链路（源码追踪）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SSE 事件推送完整链路                             │
└─────────────────────────────────────────────────────────────────────────────┘

1. 事件发射点（Event Emitter）
   ┌─────────────────────────────────────────────────────────────────────────┐
   │ worker.py:_handle_analyze_audio()（第 168-228 行）                       │
   │                                                                         │
   │ # 发送进度 10%                                                         │
   │ async with UnitOfWork() as uow:                                        │
   │     await event_log_service.emit(uow.session,                           │
   │         ProjectEvent(                                                   │
   │             event_type="audio.analysis.progress",                       │
   │             payload={"progress": 10, "message": "开始裁切并提取音频信号..."},
   │         ))                                                              │
   │                                                                         │
   │ # 发送进度 90%                                                         │
   │ async with UnitOfWork() as uow:                                        │
   │     await event_log_service.emit(uow.session,                           │
   │         ProjectEvent(                                                   │
   │             event_type="audio.analysis.progress",                       │
   │             payload={"progress": 90, "message": "分析完成，正在落库..."}, │
   │         ))                                                              │
   │                                                                         │
   │ # 发送完成事件                                                          │
   │ async with UnitOfWork() as uow:                                        │
   │     await event_log_service.emit(uow.session,                           │
   │         ProjectEvent(                                                   │
   │             event_type="audio.analysis.completed",                      │
   │             payload={...},                                             │
   │         ))                                                              │
   └─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
2. Outbox 持久化（同一 DB 事务）
   event_log_service.emit() 同时写入：
   - event_logs 表
   - outbox_events 表（status='pending'）

3. OutboxPublisher 后台轮询（每 1 秒）
   outbox_publisher.py → redis.publish("vidmuse:events:project", json)

4. SSE 端点订阅
   project_events.py:project_events_stream()
   → pubsub.subscribe("vidmuse:events:project")
   → 按 _project_id 过滤
   → yield f"data: {json_payload}\n\n"

5. 前端 EventSource 接收
   frontend/src/lib/sse.ts:useProjectEvents()
   → eventSource.onmessage = (event) => { ... }
```

**关键文件路径**：

| 文件 | 作用 | 关键代码行 |
|------|------|----------|
| `backend/app/tasks/worker.py` | 发送 `audio.analysis.progress` 等事件 | 第 168-228 行 |
| `backend/app/services/event_log_service.py` | Outbox 模式写入 event_logs + outbox_events | 第 53-115 行 |
| `backend/app/events/outbox_publisher.py` | 后台轮询 outbox_events 并发布到 Redis | - |
| `backend/app/api/v1/project_events.py` | SSE 端点，订阅 Redis pubsub 并 yield 给前端 | 第 95-155 行 |
| `backend/app/schemas/event.py` | `ProjectEvent` 数据模型定义 | - |

### 2.2 前端 SSE 接收链路（源码追踪）

```typescript
// frontend/src/lib/sse.ts:useProjectEvents()（第 61-99 行）

eventSource.onmessage = (event) => {
  const payload = JSON.parse(event.data);
  const eventType = payload.event_type;

  // 进度事件 → 更新 Zustand store 中的 generatingMessage
  if (eventType === 'audio.analysis.progress') {
    setIsGenerating(true);
    setGeneratingMessage(payload.message || '正在分析音频...');  // ← 仅更新 store
    setGenerationProgress(payload.progress || 0);
  }

  // 完成事件 → 触发 refresh 重新加载消息
  if (REFRESH_EVENTS.has(eventType)) {
    if (GENERATION_FINISH_EVENTS.has(eventType)) {
      setIsGenerating(false);
      setGeneratingMessage(null);
    }
    triggerRefresh();  // ← 重新加载 Chat 消息
  }
};
```

**问题所在**：`audio.analysis.progress` 事件只更新了 `generatingMessage`（显示在输入框 placeholder），**没有生成对话消息**插入到 Chat 消息列表中。

### 2.3 前端 Chat 消息加载流程（源码追踪）

```typescript
// frontend/src/pages/Workbench.tsx:fetchProjectData()（第 103-138 行）

const fetchProjectData = async (isRefresh = false) => {
  // 1. 获取项目信息和 pending decisions
  const [projRes, decRes] = await Promise.all([
    projectService.getProject(projectId),
    projectService.getDecisions(projectId)
  ]);

  // 2. 获取对话 sessions 和消息 ← 导演汇报消息从这里加载
  const sessRes = await chatService.getSessions(projectId);
  if (sessRes.success && sessRes.data?.items?.length) {
    const msgRes = await chatService.getSessionMessages(projectId, sessRes.data.items[0].id);
    if (msgRes.success) {
      const dbMsgs = msgRes.data?.items?.map((m: any) => ({
        role: m.role, content: m.content_text, created_at: m.created_at
      }));
      if (dbMsgs.length > 0) setMessages(dbMsgs);
    }
  }
};
```

**关键发现**：
1. Chat 消息来自 `chatService.getSessionMessages()` → 调用后端 `/api/v1/projects/{id}/sessions/{id}/messages`
2. 这些消息是通过 `DirectorReportService._run_report()` 持久化到数据库的
3. `triggerRefresh()` 被调用时，才会重新从数据库加载消息

### 2.4 DirectorReportService 汇报流程（源码追踪）

```python
# backend/app/services/director_report_service.py:_run_report()（第 102 行起）

async def _run_report(self, project_id: str, task_type: str, task_result: dict):
    # 步骤 1-4: 加载项目、session、history、artifact ref

    # 步骤 5: 调用主图（Mode B 汇报模式）
    system_trigger = {...}  # Mode B 触发器
    async for chunk in invoke_director_graph(...):
        # 流式输出...但这里Director汇报是流式的，最终需要save到DB

    # 步骤 6: 持久化汇报消息（关键！）
    await self._conv_svc.save_assistant_message(
        session_id=session_id,
        content_text=director_report_content,
    )

    # 步骤 7: 发送 director.report SSE 事件
    async with UnitOfWork() as uow:
        await event_log_service.emit(
            uow.session,
            ProjectEvent(
                event_type="director.report",  # ← 触发前端 triggerRefresh
                ...
            )
        )
```

**关键发现**：
- Director 的汇报内容是在 `_run_report()` 中生成并通过 `save_assistant_message()` 持久化到数据库
- 然后发送 `director.report` SSE 事件
- 前端收到 `director.report` 后调用 `triggerRefresh()` 重新加载消息
- 但这**只在任务完成后**才发生，**中间没有实时进度消息**

---

## 三、核心问题根因分析

### 3.1 进度消息 vs 对话消息的混淆

**当前设计**：
```
SSE 事件 audio.analysis.progress
  → 前端: setGeneratingMessage(payload.message)  // 输入框 placeholder
  → 前端: setGenerationProgress(payload.progress)  // 进度条

期望设计：
SSE 事件 audio.analysis.progress
  → 前端: 插入一条新的"assistant"角色消息到 Chat 消息列表
```

**证据**（`frontend/src/stores/projectStore.ts` 第 12-17 行）：
```typescript
isGenerating: boolean;
generatingMessage: string | null;  // ← 只用于 placeholder
setGeneratingMessage: (msg: string | null) => void;
```

`generatingMessage` 从未用于 Chat 消息渲染，它只是输入框的 placeholder。

### 3.2 后端已有 progress 事件但前端未充分利用

**后端已发送**（`worker.py` 第 168-228 行）：
- `audio.analysis.progress` (progress=10, message="开始裁切并提取音频信号...")
- `audio.analysis.progress` (progress=90, message="分析完成，正在落库...")
- `audio.analysis.completed`

**前端只处理了**（`sse.ts` 第 75-78 行）：
```typescript
if (eventType === 'audio.analysis.progress') {
  setGeneratingMessage(payload.message);  // 仅更新 placeholder
  // ← 没有插入 Chat 消息！
}
```

### 3.3 其他 Worker handler 的进度事件覆盖不全

| Worker Handler | 是否发送进度事件 | 发送的事件 |
|---------------|----------------|-----------|
| `_handle_analyze_audio` | ✅ 是 | `audio.analysis.progress` (10%, 90%), `audio.analysis.completed` |
| `_handle_generate_narrative` | ✅ 是 | `narrative.generating`, `narrative.completed` |
| `_handle_generate_storyboard` | ❌ 否 | 无进度事件 |
| `_handle_generate_clips` | ❌ 否 | 无进度事件 |
| `_handle_generate_timeline` | ❌ 否 | 无进度事件 |

---

## 四、解决方案

### 4.1 方案概述

**核心思路**：将 SSE 进度事件**同时**用于：
1. 更新 `generatingMessage`（进度条/placeholder）- 保留现有能力
2. **插入一条 assistant 消息到 Chat 消息列表** - 新增能力

### 4.2 后端调整

#### 4.2.1 新增统一进度消息事件类型（推荐）

在后端定义一个新的事件类型 `workflow.step.progress`，payload 包含：
```python
ProjectEvent(
    event_type="workflow.step.progress",
    payload={
        "step": "audio_analysis",          # 当前步骤标识
        "message": "正在分析音频...",      # 展示用中文消息
        "progress": 10,                    # 进度百分比（可选）
        "append": True,                    # 是否追加到 Chat 消息（关键！）
    }
)
```

**优点**：统一格式，前端只需处理一种事件类型
**缺点**：需要修改后端所有发送进度的地方

#### 4.2.2 直接复用现有事件类型（最小改动）

**不变更后端**。后端已发送：
- `audio.analysis.progress` (progress=10, message="开始裁切...")
- `audio.analysis.progress` (progress=90, message="分析完成...")

前端修改：这些事件触发时**同时插入 Chat 消息**。

**优点**：无需修改后端，最小改动
**缺点**：进度事件和 Chat 消息的对应关系需要前端维护

### 4.3 前端调整

#### 4.3.1 修改 `useProjectEvents` hook

```typescript
// frontend/src/lib/sse.ts

// 新增：Chat 消息列表的追加方法（通过 store 或回调）
// 方案 A：在 hook 内部直接操作 messages state（需要提升 state 到 parent）
// 方案 B：通过 triggerRefresh + 特殊标识让 fetchProjectData 知道要插入进度消息

// 推荐方案 A：给 useProjectEvents 传递一个追加消息的回调
export const useProjectEvents = (
  projectId?: string,
  onProgressMessage?: (message: string) => void  // ← 新增
) => {
  // ...
  if (eventType === 'audio.analysis.progress') {
    setIsGenerating(true);
    setGeneratingMessage(payload.message);
    setGenerationProgress(payload.progress);

    // 追加进度消息到 Chat 对话列表
    if (onProgressMessage && payload.message) {
      onProgressMessage(payload.message);
    }
  }
  // ...
}
```

#### 4.3.2 修改 Workbench.tsx

```typescript
// frontend/src/pages/Workbench.tsx

// 在 useProjectEvents 调用时传入追加消息的回调
useProjectEvents(projectId, (message) => {
  // 追加一条 assistant 消息
  setMessages(prev => [...prev, {
    role: 'assistant',
    content: message,
    created_at: new Date().toISOString(),
    _isProgress: true,  // 标记为进度消息（可选用）
  }]);
});
```

#### 4.3.3 修改 AIDirectorPanel 的消息渲染（可选优化）

进度消息可以带有特殊标记（如 `_isProgress: true`），可以渲染成不同样式（如带进度动画）。

---

## 五、解决依据（代码驱动）

### 5.1 后端事件推送机制是完整的

**证据 1**：`worker.py` 第 168-228 行已实现进度事件推送
```python
async with UnitOfWork() as uow:
    await event_log_service.emit(
        uow.session,
        ProjectEvent(
            event_type="audio.analysis.progress",
            payload={"progress": 10, "message": "开始裁切并提取音频信号..."},
        ),
    )
```

**证据 2**：`event_log_service.emit()` 实现了 Outbox Pattern，同一事务写入 `event_logs` 和 `outbox_events`

**证据 3**：`project_events.py` 的 SSE 端点正确实现了 Redis pubsub 订阅和按 `project_id` 过滤

**结论**：后端 SSE 推送链路**已完整实现**，无需修改。

### 5.2 前端 SSE hook 的处理是不完整的

**证据**：`sse.ts` 第 75-78 行只更新了 `generatingMessage`，没有生成 Chat 消息
```typescript
if (eventType === 'audio.analysis.progress') {
  setIsGenerating(true);
  setGeneratingMessage(payload.message);  // ← 只更新了 placeholder
  // ← 缺少：追加消息到 Chat 消息列表
}
```

**结论**：前端需要修改 `useProjectEvents` hook，将进度消息同时追加到 Chat 消息列表。

### 5.3 Chat 消息的持久化机制是正确的

**证据**：`DirectorReportService._run_report()` 通过 `ConversationService.save_assistant_message()` 正确持久化了 Director 汇报到数据库

**结论**：Chat 消息的存储是完整的，不需要修改数据库模型。

### 5.4 前端消息加载时机是正确的

**证据**：`Workbench.tsx` 的 `fetchProjectData()` 在 `triggerRefresh()` 被调用时重新从数据库加载消息（第 122-131 行）

**结论**：消息加载链路是正确的，不需要修改 `fetchProjectData()`。

---

## 六、推荐实施方案（最小改动）

### 6.1 修改范围

| 文件 | 修改内容 | 工作量 |
|------|---------|-------|
| `frontend/src/lib/sse.ts` | 新增 `onProgressMessage` 回调参数 | 小 |
| `frontend/src/pages/Workbench.tsx` | 传入 `onProgressMessage` 回调，追加消息到 state | 小 |
| `backend/app/tasks/worker.py`（可选） | 为其他 handler 添加进度事件 | 中 |

### 6.2 具体代码修改

#### 前端：`frontend/src/lib/sse.ts`

```typescript
// 修改 useProjectEvents 签名，新增可选回调
export const useProjectEvents = (
  projectId?: string,
  onProgressMessage?: (message: string) => void
) => {
  // ... 现有代码 ...

  eventSource.onmessage = (event) => {
    // ...
    if (eventType === 'audio.analysis.progress') {
      setIsGenerating(true);
      setGeneratingMessage(payload.message || '正在分析音频...');
      setGenerationProgress(payload.progress || 0);

      // 新增：将进度消息追加到 Chat 对话列表
      if (onProgressMessage && payload.message) {
        onProgressMessage(payload.message);
      }
    } else if (eventType === 'narrative.generating') {
      setIsGenerating(true);
      setGeneratingMessage(payload.message || '正在构思叙事剧本...');

      // 新增
      if (onProgressMessage && payload.message) {
        onProgressMessage(payload.message);
      }
    }
    // ...
  };
};
```

#### 前端：`frontend/src/pages/Workbench.tsx`

```typescript
// 在 useProjectEvents 调用时传入回调
useProjectEvents(projectId, (message) => {
  setMessages(prev => [...prev, {
    role: 'assistant',
    content: message,
    created_at: new Date().toISOString(),
    _isProgress: true,
  }]);
});
```

### 6.3 可选增强：为其他 Worker handler 添加进度事件

为 `_handle_generate_storyboard`、`_handle_generate_clips` 等添加类似的进度事件推送，使整个流程都有实时消息。

---

## 七、总结

| 维度 | 结论 |
|------|------|
| **问题根因** | 前端 SSE hook 只将进度消息用于 `generatingMessage`（输入框 placeholder），没有同时生成 Chat 对话消息 |
| **后端是否需要修改** | ❌ 不需要，后端进度事件推送链路已完整实现 |
| **前端需要修改** | ✅ 需要修改 `useProjectEvents` hook 和 `Workbench.tsx` |
| **改动范围** | 2 个前端文件，代码量约 20-30 行 |
| **风险** | 低，纯前端修改，不影响后端逻辑 |

---

## 八、相关文件索引

### 后端
- `backend/app/tasks/worker.py` - Worker handlers，进度事件发送（第 168-228 行）
- `backend/app/services/event_log_service.py` - Outbox 模式实现
- `backend/app/api/v1/project_events.py` - SSE 端点实现
- `backend/app/schemas/event.py` - ProjectEvent 数据模型
- `backend/app/services/director_report_service.py` - Director Mode B 汇报
- `backend/app/workflows/nodes/audio_analysis_node.py` - 音频分析节点

### 前端
- `frontend/src/lib/sse.ts` - SSE hook，事件接收处理
- `frontend/src/stores/projectStore.ts` - Zustand store，generatingMessage 状态
- `frontend/src/pages/Workbench.tsx` - 主页面，消息加载和状态管理
- `frontend/src/components/workbench/AIDirectorPanel.tsx` - AI Director 对话面板
