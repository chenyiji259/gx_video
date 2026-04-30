# VidMuse 九宫格分镜重构方案

| 项目 | 内容 |
|---|---|
| 版本 | v1.0 |
| 创建日期 | 2026-04-30 |
| 状态 | **已批准（待开发）** |
| 决策人 | 用户 |
| 架构师 | Claude（VidMuse 首席架构师） |
| 编号 | 21 |

---

## 0. 文档说明

**本文档是 VidMuse 第二轮重构（AI 视频生成 → 九宫格驱动管线）的总方案**。

第一轮重构（音乐 MV → AI 视频生成）已完成跑通，本轮在此基础上：
- 把"逐 shot 单独生图"的分镜流程，改造成"叙事九宫格批量生图 + 代码切分"的新管线
- 简化前端阶段（删除"视觉圣经"独立菜单）
- 全程采用文档驱动开发：本文档落地后，开发严格按 §9 的 TodoList 顺序推进

**核心设计原则**：
- 最大复用现有骨架（状态机、决策框架、事件系统、存储 Adapter 全保留）
- 中型重构，非推倒重来：32 个文件改动，无新增数据库表

---

## 1. 背景与目标

### 1.1 当前流程（已跑通的 AI 视频生成版）

```
项目设置 → 需求输入 → 创意方案 → 剧本创作 → 视觉圣经 → 镜头计划
        → 分镜（每 shot 1 张图） → 视频制作 → 导出
```

**问题**：
1. 分镜阶段每个 shot 独立生图，**相邻 shot 视觉断裂**，i2v 拼接出戏
2. 视觉圣经阶段重，需要预生成大量角色/场景参考图
3. 镜头计划允许用户手动编辑，但实际 AI 视频生成场景下没必要

### 1.2 目标流程（本轮重构）

```
需求输入
  → 创意确认（含时长/shot 数/角色清单）
  → 剧本创作（每 shot 含画面描述）
  → 镜头计划（自动派生）
  → 九宫格分镜（NEW：批量生图 + 代码切分）
       ├─ 第 1 张九宫格 prompt → 大图 → 切分 9 帧
       ├─ 第 2 张九宫格（cell1 复用第 1 张 cell9）→ 切分
       └─ ... 直到覆盖目标时长
  → 视频生成（相邻 2 帧作首尾帧，i2v 并发出 shot ~10s）
  → 时间轴拼接 → 导出
```

**关键改进**：
- shot 之间画面**无缝衔接**（共享同一帧画面作为转换点）
- 单次 LLM 调用生成连续叙事，剧情连续性更强
- 视觉圣经阶段融入"创意方案"（角色定义写进 brief）
- 镜头计划自动派生（shot 数 = 8 × 九宫格数）

---

## 2. 核心设计决策

| 决策 | 内容 | 选择 |
|---|---|---|
| **A** | 九宫格架构位置 | **A1**：改造 storyboard 阶段（不新增 ProjectStage） |
| **B** | shot 数与九宫格映射 | **B3**：9 帧 = 8 shot 重叠模式 + 跨九宫格 cell9→cell1 物理复用 |
| **C** | 角色一致性策略 | **C1**：依赖 LLM 在 prompt 中描述角色（外貌/服装），保留接口扩展点 |
| **D** | 视觉圣经阶段处理 | **D1**：删除前端菜单 + 后端代码降级 deprecated |
| **E** | 音频死代码处理 | **E2**：暂不动，下一轮专项清理 |

### 2.1 决策 A：A1（改造现有阶段）的理由

- 九宫格是"分镜的批量生成策略"，不是新业务阶段
- 不动 `ProjectStage` enum → 状态机 / stale 规则 / 事件类型零改动
- `StoryboardVersion` / `StoryboardFrame` 表完美对应：1 个 version = 1 张大图，9 个 frame = 9 个切分
- 避免数据库迁移压力（无新表）

### 2.2 决策 B：B3 算法的理由（剧情连续性最优）

- shot N 的尾帧 = shot N+1 的首帧（同一张图）→ i2v 视频接起来视觉零跳变
- 跨九宫格衔接：第 N+1 张的 cell1 **物理复用**第 N 张的 cell9（不让模型重生），100% 保证一致

### 2.3 决策 C：C1（prompt 描述角色）的理由

- 删除视觉圣经后，角色一致性纯靠 LLM 在九宫格 prompt 中明确描述（"穿白衬衫、圆框眼镜的程序员小明"）
- 依赖图像模型自身的语义一致性
- 保留扩展点：`StoryboardFrame.character_binding` 字段保留，未来可降级到 C2（自动生成角色定妆图）

### 2.4 决策 D：D1（删前端菜单 + 后端 deprecated）的理由

- 前端 8 个阶段简化为 7 个：删"视觉圣经"
- 后端 `visual_development_agent` / `consistency_guardian_agent` 标记 deprecated，不删代码
- API `/visual_bible/*` 路由删除
- 角色定义并入"创意方案"（brief 含 `character_list`）

### 2.5 决策 E：E2（音频死代码暂不动）的理由

- `audio_analysis_*` 系列代码已逻辑停用（路由注释、节点注释）
- 残留 enum / Repository / 字段不影响主流程
- 本轮不清理避免改动面扩散，下轮专项处理

---

## 3. 关键算法：B3 九宫格映射

### 3.1 单张九宫格的 shot 映射

```
单张九宫格 9 帧（3×3 排列）：

  ┌───┬───┬───┐
  │ 1 │ 2 │ 3 │
  ├───┼───┼───┤
  │ 4 │ 5 │ 6 │
  ├───┼───┼───┤
  │ 7 │ 8 │ 9 │
  └───┴───┴───┘

shot 映射（首尾帧重叠模式）：
  shot 1: cell1 → cell2  (10s)
  shot 2: cell2 → cell3  (10s)
  shot 3: cell3 → cell4  (10s)
  shot 4: cell4 → cell5  (10s)
  shot 5: cell5 → cell6  (10s)
  shot 6: cell6 → cell7  (10s)
  shot 7: cell7 → cell8  (10s)
  shot 8: cell8 → cell9  (10s)

合计 9 帧 = 8 shot × 10s = 80s
```

### 3.2 多张九宫格衔接

```
第 1 张九宫格：cell1 ~ cell9
第 2 张九宫格：cell1 = 第 1 张 cell9（物理复用）, cell2 ~ cell9 由模型生成

shot 跨九宫格：
  shot 8  (第1张): cell8 → cell9
  shot 9  (第2张): cell9(=第2张cell1) → 第2张cell2
  shot 10 (第2张): 第2张cell2 → 第2张cell3
  ...
```

### 3.3 九宫格数量与 shot 数算法

```python
def plan_nine_grids(target_duration_sec: int, shot_duration_sec: int = 10) -> dict:
    """规划九宫格数量和 shot 数量。
    
    Args:
        target_duration_sec: 用户期望的视频总时长（秒）
        shot_duration_sec:   单个 shot 时长（默认 10s，未来可由 LLM 动态决定）
    
    Returns:
        {
            "shot_count":           需要的 shot 数（向上取整）
            "grid_count":           需要的九宫格张数
            "total_shots_generated": 实际会生成的 shot 数（可能多于需要）
            "frame_count":          实际"独立"帧数 = 9 + 8(N-1) = 8N+1
            "actual_duration_sec":  实际生成时长
            "trim_to_sec":          末尾裁剪点
        }
    """
    shot_count = math.ceil(target_duration_sec / shot_duration_sec)
    grid_count = math.ceil(shot_count / 8)
    total_shots = grid_count * 8
    frame_count = 9 + 8 * (grid_count - 1)
    actual_duration = total_shots * shot_duration_sec
    
    return {
        "shot_count": shot_count,
        "grid_count": grid_count,
        "total_shots_generated": total_shots,
        "frame_count": frame_count,
        "actual_duration_sec": actual_duration,
        "trim_to_sec": target_duration_sec,
    }
```

### 3.4 算法示例

| 用户输入时长 | 实际 shot | 九宫格数 | 实际帧数 | 实际时长 | 裁剪策略 |
|---|---|---|---|---|---|
| 30s | 3 | 1 | 9 | 80s | 用 cell1-4，仅生成前 3 个 shot |
| 60s（1 分钟） | 6 | 1 | 9 | 80s | 用 cell1-7，仅生成前 6 个 shot |
| 80s | 8 | 1 | 9 | 80s | 全用，刚好 |
| 90s（1.5 分钟） | 9 | 2 | 17 | 160s | 第 1 张全 8 shot + 第 2 张 1 shot |
| 120s（2 分钟） | 12 | 2 | 17 | 160s | 第 1 张全 8 shot + 第 2 张 4 shot |
| 160s | 16 | 2 | 17 | 160s | 全用 |

**剩余 shot 处理**：超出用户目标时长的 shot **不进 timeline**，但仍生成（因为生图是按九宫格批量出，无法局部）。

---

## 4. 改造范围（32 个文件，8 个阶段）

### 4.1 全局视图

```
┌────────────────────────────────────────────────────────────┐
│  改造影响面                                                  │
├────────────────────────────────────────────────────────────┤
│  Prompts (4 改 + 1 新)         │ ⚡ 重写 4 个，新增 1 个      │
│  Services (3 改 + 0 新)        │ ⚡ storyboard 重写         │
│  Agents (2 改 + 1 降级)        │ creative/narrative 改     │
│  Schemas (3 改 + 1 新)         │ brief 加字段，新增 NineGrid │
│  Models (1 改, 0 删)           │ StoryboardFrame 加 3 列    │
│  Workflow (1 改)               │ main_graph 删 vb 路由      │
│  API (3 改 + 删 1)             │ brief/storyboard 接口扩展  │
│  Frontend (4 改)               │ 删 vb 菜单、改 UI          │
│  Storage/Tools (2 改)          │ image_tool 加九宫格方法     │
│  Migration (1 新)              │ StoryboardFrame 加列        │
├────────────────────────────────────────────────────────────┤
│  不动的（最大复用）                                          │
│  - state_transition_service                                │
│  - decision_service                                        │
│  - clip_service / clip_node                                │
│  - timeline / export                                       │
│  - 整个数据库阶段 enum                                       │
│  - 音频死代码（E2 暂不动）                                    │
└────────────────────────────────────────────────────────────┘
```

### 4.2 阶段 1：基础设施（schemas + models + storage + migration）

| # | 文件 | 改动 | 行数预估 |
|---|---|---|---|
| 1.1 | `backend/app/schemas/project.py` | `CreativeBriefVO` 加字段：`target_duration_sec: int`、`shot_duration_sec: int = 10`、`shot_count: int`、`grid_count: int`、`character_list: list[CharacterDef]` | +30 |
| 1.2 | `backend/app/schemas/storyboard.py` | 新增 `NineGridMeta` schema（`grid_index`、`parent_asset_id`、`parent_asset_url`、`cell_assets: list[FrameMeta]`） | +60 |
| 1.3 | `backend/app/models/storyboard.py` | `StoryboardFrame` 加 3 列：`parent_asset_id: str | None`（FK→Asset）、`cell_position: int | None`（1-9）、`grid_index: int | None` | +15 |
| 1.4 | `backend/app/models/asset.py` 或 `domain/states.py` | asset_type 枚举加 `nine_grid_image` | +1 |
| 1.5 | `backend/app/storage/path_planner.py` | `storyboard_dir()` 子目录约定：`grids/`（大图）、`cells/`（切分图） | +20 |
| 1.6 | `backend/migrations/versions/{ts}_add_nine_grid_columns.py` | Alembic migration：`storyboard_frames` 加 3 列（允许 NULL，向后兼容） | +40 |

### 4.3 阶段 2：Prompts 重写

| # | 文件 | 改动 |
|---|---|---|
| 2.1 | `prompts/system/creative_planning.md` | 重写为"AI 视频创意策划师"角色，输出含时长/shot 数/角色清单 |
| 2.2 | `prompts/tasks/generate_brief.md` | 输出新 schema（含 character_list、target_duration_sec、shot_count） |
| 2.3 | `prompts/system/narrative_script.md` | 每 shot 含画面描述、情绪、固定时长（删除歌词类字段） |
| 2.4 | `prompts/tasks/generate_narrative_script.md` | 输入 brief，按 shot_count 分配剧本 |
| 2.5 | **新建** `prompts/tasks/generate_nine_grid.md` | 九宫格生图 prompt 编译模板（输入：剧本 + 角色清单 + grid_index + 衔接帧描述） |
| 2.6 | `prompts/compiler/compile_video_prompt.md` | 接受 `first_frame_url` + `last_frame_url` 两张图，编译 i2v prompt |

### 4.4 阶段 3：核心 Services

| # | 文件 | 改动 |
|---|---|---|
| 3.1 | `backend/app/tools/image_generation_tool.py` | **加 2 个方法**：<br/>- `generate_nine_grid(bundle, project_id, grid_index, ref_image_url=None)` —— 生 1 张大图（3072×3072），asset_type=nine_grid_image<br/>- `split_and_persist_grid(parent_asset_id, project_id, grid_index, skip_cell1=False)` —— PIL 切 9 张，每张落 MinIO + Asset + 本地，返回 `list[asset_id]`。skip_cell1=True 时复用上一张 cell9 |
| 3.2 | `backend/app/services/prompt_compiler_service.py` | **加方法** `compile_nine_grid_prompt(project_id, grid_index, total_grids, prev_grid_cell9_url=None)` —— 编译九宫格生图 prompt；**改造** `compile_for_shot(target_type=shot_clip)` 接受 `first_frame_asset_id` + `last_frame_asset_id` |
| 3.3 | `backend/app/services/storyboard_service.py` | **重写**：<br/>- `_generate_locked()` → 串行 N 张九宫格<br/>- 新方法 `_generate_single_grid(grid_index, prev_grid)`<br/>- 新方法 `_persist_grid_frames(grid_meta)`<br/>- 全程 emit 增量推送事件（见 §6） |
| 3.4 | `backend/app/services/shot_plan_persistence_service.py` | shot 数由 `grid_count * 8` 派生，去掉用户编辑能力 |

### 4.5 阶段 4：Agents

| # | 文件 | 改动 |
|---|---|---|
| 4.1 | `backend/app/agents/creative_planning_agent.py` | 输出新 schema（含 character_list、shot_count） |
| 4.2 | `backend/app/agents/narrative_script_agent.py` | 按固定 shot_count 输出剧本 |
| 4.3 | `backend/app/agents/visual_development_agent.py` | **降级 deprecated**（标注，不删代码） |
| 4.4 | `backend/app/agents/consistency_guardian_agent.py` | **降级 deprecated** |

### 4.6 阶段 5：Workflow / Nodes

| # | 文件 | 改动 |
|---|---|---|
| 5.1 | `backend/app/workflows/main_graph.py` | 删除 `confirm_visual_bible` / `request_visual_bible_confirmation` 路由分支；删除 `_route_after_director` 中 visual_bible 相关条件 |
| 5.2 | `backend/app/workflows/graph_state.py` | 标记 `visual_bible_confirmed`/`visual_bible_ref` deprecated（保留兼容） |
| 5.3 | `backend/app/workflows/nodes/storyboard_node.py` | 调用新版 service（接口签名不变，内部已重写） |

### 4.7 阶段 6：API

| # | 文件 | 改动 |
|---|---|---|
| 6.1 | `backend/app/api/v1/projects.py`（或 brief 路由） | brief 接口加新字段（target_duration_sec、character_list 等） |
| 6.2 | `backend/app/api/v1/storyboard.py` | 新增 `GET /projects/{pid}/storyboard/grids` —— 列出所有九宫格大图 + 各自 9 张切分图 URL |
| 6.3 | **删除** `backend/app/api/v1/visual_bible.py` | D1 删除整个文件 |
| 6.4 | `backend/app/api/v1/__init__.py` | 注销 visual_bible 路由 |

### 4.8 阶段 7：前端

| # | 文件 | 改动 |
|---|---|---|
| 7.1 | `frontend/src/components/layout/Sidebar.tsx`（或对应文件） | 删除"视觉圣经"菜单项 |
| 7.2 | `frontend/src/features/project/RequirementForm.tsx` | 加平台/受众/风格/时长输入字段 |
| 7.3 | `frontend/src/features/project/CreativeBriefView.tsx` | 展示时长 / 角色清单 / shot 数预估 |
| 7.4 | `frontend/src/features/pipeline/StoryboardView.tsx` | 改造成"九宫格大图 + 9 切分小图"展示，按 grid_index 增量渲染 |
| 7.5 | `frontend/src/lib/sse.ts` | REFRESH_EVENTS 加 4 个新事件，删 visual_bible 相关，新增按 grid_index 增量渲染逻辑 |

### 4.9 阶段 8：Migration（已含在阶段 1）

阶段 1 的 1.6 已涵盖。

---

## 5. 存储链路设计

### 5.1 MinIO 路径

```
projects/{project_id}/assets/
  ├─ nine_grid_image/{asset_id}/grid_{N}.png        # 九宫格大图
  ├─ storyboard_frame/{asset_id}/cell_{N}_{pos}.png # 切分小图（cell_位置）
  ├─ character_reference/...                         # （C2 预留，本轮不用）
  └─ scene_reference/...                             # （C2 预留，本轮不用）
```

### 5.2 本地副本路径

```
data/projects/{project_id}/06_storyboard/
  ├─ grids/grid_{N}.png                              # 九宫格大图副本
  ├─ cells/grid_{N}_cell_{pos}.png                   # 切分图副本
  ├─ grid_{N}_meta_v1_{ts}.json                      # 单张九宫格元数据
  └─ storyboard_v{V}_{ts}.json                       # 整体 storyboard 快照
```

### 5.3 数据库 Asset 记录

每张大图 + 每张切分图 = 1 条 Asset 记录：

| 字段 | 大图 | 切分图 |
|---|---|---|
| `asset_type` | `nine_grid_image` | `storyboard_frame` |
| `metadata_.grid_index` | N（第几张九宫格） | N |
| `metadata_.cell_position` | NULL | 1-9 |
| `metadata_.parent_asset_id` | NULL | 大图的 asset_id |
| `metadata_.is_reused_from_prev_grid` | NULL | true（第 2+ 张的 cell1） |

### 5.4 StoryboardFrame 记录扩展

```python
class StoryboardFrame:
    # 已有字段
    project_id: str
    storyboard_version_id: str
    shot_id: str | None  # 切分图绑定 shot；大图为 None
    asset_id: str
    prompt_bundle_id: str | None
    frame_index: int
    metadata_: dict
    
    # 新增字段（本轮）
    parent_asset_id: str | None  # 大图的 asset_id；大图自身为 NULL
    cell_position: int | None    # 1-9；大图为 NULL
    grid_index: int | None       # 第几张九宫格（从 1 开始）
```

---

## 6. 推送链路设计

### 6.1 新增事件（5 个）

| 事件 | 触发时机 | payload |
|---|---|---|
| `storyboard.grid.generating` | 开始生成第 N 张九宫格 prompt + 大图 | `{grid_index, total_grids, message}` |
| `storyboard.grid.generated` | 第 N 张大图完成（未切分） | `{grid_index, parent_asset_id, asset_url}` |
| `storyboard.grid.split_done` | 第 N 张切分 9 帧完成 | `{grid_index, frames: [{cell_position, asset_id, asset_url}]}` |
| `storyboard.all_grids_completed` | 所有 N 张九宫格 + 切分全完成 | `{grid_count, total_frames, shot_count}` |
| `project_storyboard_ready` | 阶段推进事件（保留沿用） | `{from_stage, to_stage}` |

### 6.2 删除事件

- `project_visual_bible_ready`
- `visual_bible.initializing`
- `visual_bible.completed`

### 6.3 前端增量渲染策略

```typescript
// frontend/src/lib/sse.ts
case 'storyboard.grid.generating':
  setGeneratingMessage(`第 ${payload.grid_index}/${payload.total_grids} 张九宫格生成中…`)
  break

case 'storyboard.grid.generated':
  // 增量：把这张大图加到 store
  appendNineGridImage(payload.grid_index, payload.parent_asset_id, payload.asset_url)
  break

case 'storyboard.grid.split_done':
  // 增量：把 9 张切分图加到 store
  appendNineGridCells(payload.grid_index, payload.frames)
  break

case 'storyboard.all_grids_completed':
  setIsGenerating(false)
  setGeneratingMessage(null)
  // 不需要 triggerRefresh，因为前面已经增量更新完了
  break
```

### 6.4 用户体验流

```
用户点"开始生成分镜"
  ↓
前端显示 loading
  ↓
后端开始生第 1 张
  → emit storyboard.grid.generating
  → 前端显示 "第 1/2 张九宫格生成中…"
  ↓
大图完成
  → emit storyboard.grid.generated
  → 前端立即显示大图（占位 9 个空格）
  ↓
切分完成
  → emit storyboard.grid.split_done
  → 前端逐格填入 9 张切分图
  ↓
开始生第 2 张（cell1 复用第 1 张 cell9）
  → emit storyboard.grid.generating
  → 前端 "第 2/2 张九宫格生成中…"
  ↓
... 重复 ...
  ↓
全部完成
  → emit storyboard.all_grids_completed
  → emit project_storyboard_ready
  → 前端关闭 loading，进入"视频生成"阶段
```

---

## 7. 风险点与对策

| # | 风险 | 严重度 | 对策 |
|---|---|---|---|
| 1 | 多张九宫格衔接帧不一致 | 🔴 高 | 第 N+1 张的 cell1 **物理复用**第 N 张的 cell9，不让模型重生 |
| 2 | 用户 60s 但 B3 算法生 80s | 🟡 中 | 创意阶段告知"实际生成 8 shot=80s，将裁剪到 60s"；或让 LLM 按 7 shot 设计剧情，第 8 shot 留作余量 |
| 3 | 角色一致性纯靠 prompt（C1）失败 | 🟡 中 | StoryboardFrame.character_binding 字段保留，未来可降级到 C2（自动生角色基底图） |
| 4 | 旧 StoryboardFrame 数据兼容 | 🟢 低 | 新加列允许 NULL；旧数据 cell_position=NULL 视为单帧，前端兼容渲染 |
| 5 | 九宫格大图分辨率不够 | 🟡 中 | 大图 3072×3072，切分后单格 1024×1024（标准 i2v 输入尺寸） |
| 6 | LLM 生成的角色描述不够具体 | 🟡 中 | creative_planning prompt 强约束输出 character_list（外貌/服装/年龄/性别） |
| 7 | 跨九宫格剧情连贯性 | 🟡 中 | generate_nine_grid prompt 接收"前 1 张 cell9 的画面描述"作为衔接上下文 |
| 8 | image_to_image 成本翻倍 | 🟢 低 | 第 2+ 张九宫格 cell1 复用减少 1/9 的生成成本 |

---

## 8. 回滚方案

### 8.1 数据库回滚

- 所有新加列允许 NULL → down migration 直接 drop column
- 不修改现有列约束 → 兼容旧数据

### 8.2 代码回滚

- 开发前打 Git tag：`pre-nine-grid-refactor`
- 必要时 `git revert` 或切回 tag

### 8.3 Prompt 回滚

- 旧 prompt 在 Git 历史里
- 改写后保留旧版作为 `*.md.bak` 在 PR 里

### 8.4 前端回滚

- 删除"视觉圣经"菜单前留 backup 分支：`backup/with-visual-bible-menu`

### 8.5 部分回滚（仅推送链路）

- 若增量推送有问题，可临时改回"全部完成才推 project_storyboard_ready"
- 前端 SSE 处理函数加 feature flag

---

## 9. 开发执行计划

### 9.1 阶段顺序与依赖关系

```
阶段 1（基础设施）
    ↓ [schema/model/migration 落地后才能用]
阶段 2（Prompts）         ← 可与阶段 3 并行
    ↓
阶段 3（Services）        ← 依赖阶段 1+2
    ↓
阶段 4（Agents）          ← 依赖阶段 2+3
    ↓
阶段 5（Workflow/Nodes）  ← 依赖阶段 3+4
    ↓
阶段 6（API）             ← 依赖阶段 1+3
    ↓
阶段 7（Frontend）        ← 依赖阶段 6
    ↓
阶段 8（验收测试）         ← 依赖全部
```

### 9.2 文档驱动开发流程

每个文件改动严格遵守：

```
① 架构师贴出"该文件的具体改动方案"（包括 diff 草稿、新方法签名、影响面）
② 用户审核 / 提问 / 批准
③ 架构师执行改动（用 StrReplace / Write 工具）
④ 架构师贴出关键 diff 给用户看
⑤ 用户确认 → 进入下一个文件
⑥ 阶段所有文件完成后，架构师执行阶段验收（功能完整性 + 规范符合性 + 一致性）
⑦ 用户最终确认 → 进入下一阶段
```

### 9.3 关键里程碑

| 里程碑 | 完成标志 |
|---|---|
| M1：数据底座就绪 | 阶段 1 + 阶段 2 完成（schema、model、migration、prompts 全部就位） |
| M2：核心管线打通 | 阶段 3 + 阶段 4 完成（一次九宫格生成能跑通到落库） |
| M3：流转就绪 | 阶段 5 + 阶段 6 完成（API 能调通、workflow 路由正确） |
| M4：端到端跑通 | 阶段 7 + 阶段 8 完成（前端能展示、用户能完整体验） |

---

## 10. 验收标准

### 10.1 功能验收

- [ ] 用户输入"AI 讲解 agent 视频，1 分钟，抖音，竖屏"，系统正确生成创意（含 6 shot、1 张九宫格规划）
- [ ] 剧本生成正确（每 shot 含画面描述、固定 10s）
- [ ] 镜头计划自动派生（无需用户编辑）
- [ ] 第 1 张九宫格生成 → 大图正确显示在前端
- [ ] 第 1 张九宫格切分 → 9 张小图按 cell_position 正确显示
- [ ] 用户输入 1.5 分钟，系统生成 2 张九宫格，且第 2 张的 cell1 与第 1 张的 cell9 视觉一致（同一张图）
- [ ] 视频生成阶段：每 shot 用相邻 2 张切分图作首尾帧
- [ ] 时间轴拼接 + 导出 → 输出视频时长 ≈ 用户输入时长（误差 ≤ 1s）

### 10.2 性能验收

- 九宫格生成时延：≤ 30s/张（含 prompt 编译 + 大图生成）
- 切分操作时延：≤ 2s（PIL 切 9 张 + 上传 MinIO）
- 全流程时延：1 分钟视频（1 张九宫格 + 6 shot）≤ 8 分钟

### 10.3 一致性验收

- 跨九宫格的衔接帧（cell9 → 下一张 cell1）**100% 像素一致**（物理复用同一张图）
- 角色一致性：同一角色在不同 cell 中外貌差异（人工评分）≥ 7/10

### 10.4 兼容性验收

- 旧项目（有 storyboard 数据，cell_position=NULL）能正常打开
- 旧 storyboard 渲染不破坏（前端按 cell_position 是否为 NULL 走不同路径）

---

## 11. 进度跟踪

进度通过 Cursor Agent 内置的 TodoWrite 工具实时跟踪。文档落地后，TodoList 即建立。

**TodoList 结构**（与本文档 §4 阶段顺序完全一致）：

```
[阶段 1] 基础设施
  ├─ 1.1 schemas/project.py 加 brief 字段
  ├─ 1.2 schemas/storyboard.py 加 NineGridMeta
  ├─ 1.3 models/storyboard.py 加 3 列
  ├─ 1.4 models/asset.py 加 nine_grid_image 类型
  ├─ 1.5 storage/path_planner.py 加子目录
  └─ 1.6 migrations 新增 alembic 文件

[阶段 2] Prompts 重写
  ├─ 2.1 creative_planning.md
  ├─ 2.2 generate_brief.md
  ├─ 2.3 narrative_script.md
  ├─ 2.4 generate_narrative_script.md
  ├─ 2.5 generate_nine_grid.md（新建）
  └─ 2.6 compile_video_prompt.md

[阶段 3] 核心 Services
  ├─ 3.1 image_generation_tool.py 加九宫格方法
  ├─ 3.2 prompt_compiler_service.py 加九宫格编译
  ├─ 3.3 storyboard_service.py 重写
  └─ 3.4 shot_plan_persistence_service.py 简化

[阶段 4] Agents
  ├─ 4.1 creative_planning_agent.py
  ├─ 4.2 narrative_script_agent.py
  ├─ 4.3 visual_development_agent.py（降级）
  └─ 4.4 consistency_guardian_agent.py（降级）

[阶段 5] Workflow / Nodes
  ├─ 5.1 main_graph.py 删 vb 路由
  ├─ 5.2 graph_state.py 标 deprecated
  └─ 5.3 storyboard_node.py 调新 service

[阶段 6] API
  ├─ 6.1 projects/brief 接口加字段
  ├─ 6.2 storyboard.py 加 grids 接口
  ├─ 6.3 删除 visual_bible.py
  └─ 6.4 注销路由

[阶段 7] 前端
  ├─ 7.1 Sidebar 删 vb 菜单
  ├─ 7.2 RequirementForm 加字段
  ├─ 7.3 CreativeBriefView 改
  ├─ 7.4 StoryboardView 改造
  └─ 7.5 sse.ts 加事件

[阶段 8] 验收
  ├─ 8.1 端到端测试（1 分钟视频）
  ├─ 8.2 跨九宫格测试（1.5 分钟视频）
  └─ 8.3 兼容性测试（旧项目）
```

---

## 附录 A：相关文档

- `docs/02_VidMuse多Agent架构与LangGraph选型.md` —— LangGraph 主图设计
- `docs/04_VidMuse状态机与事件流规范.md` —— 状态机 + 事件 Outbox 模式
- `docs/06_VidMuse多Agent协议与Prompt编译规范.md` —— PromptCompiler 设计
- `docs/07_VidMuse前端工作台与交互流程规范.md` —— SSE + 前端订阅
- `docs/18_VidMuse后端实际流程与前后端交互分析.md` —— 当前流程实证分析
- `docs/20_VidMuse前后端流程改造方案.md` —— 第一轮重构方案

## 附录 B：术语表

| 术语 | 定义 |
|---|---|
| 九宫格（Nine Grid） | 一张 3×3 排列的大图，包含 9 个连续叙事画面 |
| Cell | 九宫格中的单个画面，编号 1-9（左上→右下） |
| 衔接帧（Bridge Frame） | 跨九宫格时复用的画面：第 N 张 cell9 = 第 N+1 张 cell1 |
| Shot | 一段约 10s 的视频片段，由 i2v 模型基于首尾帧生成 |
| 首尾帧（Start/End Frame） | shot 的起始画面和结束画面，对应九宫格中的相邻 cell |

---

## 附录 C：实施进度日志

### 2026-04-30：阶段 1（基础设施）+ 阶段 2（Prompts）已完成

**实施背景的方案修订**：
- 实施前发现 VidMuse **不使用 alembic**，使用 `scripts/sql/patch_NNN_xxx.sql` 文件管理 schema 迁移
- 实施前发现 brief schema 不在 `schemas/project.py` 中，brief 是 `models/planning.py` 中的 ORM 模型
- 因此 §1.1 修订为：在 `schemas/project.py` 末尾追加 `CharacterDef` 和 `CreativeBriefExtension` 两个 Pydantic 类，用于解析 `CreativeBriefVersion.raw_payload` 中的 JSONB 扩展字段（不修改 ORM 表结构，保持向后兼容）
- §1.6 修订为：新建 `scripts/sql/patch_003_nine_grid_columns.sql`，由用户手动执行（不写 alembic）

**阶段 1 完成项**（6 个文件）：
- ✅ 1.1 `backend/app/schemas/project.py` 末尾追加 `CharacterDef` + `CreativeBriefExtension`
- ✅ 1.2 新建 `backend/app/schemas/storyboard.py`：`NineGridFrameVO`/`NineGridMeta`/`StoryboardOverview`
- ✅ 1.3 `backend/app/models/storyboard.py` `StoryboardFrame` 加 3 列（parent_asset_id / cell_position / grid_index）+ shot_id 改 nullable + 新 CheckConstraint + 新 Index
- ✅ 1.4 `backend/app/models/asset.py` `_ASSET_TYPE_VALUES` 加 `nine_grid_image`
- ✅ 1.5 `backend/app/storage/path_planner.py` 加 `nine_grid_dir()` + `storyboard_cells_dir()` 方法
- ✅ 1.6 新建 `scripts/sql/patch_003_nine_grid_columns.sql`（含回滚说明，**待用户手动执行**）

**阶段 2 完成项**（6 个 prompt）：
- ✅ 2.1 `prompts/system/creative_planning.md` 重写（v3 → v4）：删除音乐 MV 相关字段，引入九宫格算法 + extension 输出
- ✅ 2.2 `prompts/tasks/generate_brief.md` 重写（v4 → v5）：变量从音频相关改为视频需求相关
- ✅ 2.3 `prompts/system/narrative_script.md` 重写（v1 → v2）：删除歌词 / section_mapping，改为按 shot_count 划分 + 首尾帧描述
- ✅ 2.4 `prompts/tasks/generate_narrative_script.md` 重写（v1 → v2）：变量改为 brief_summary + character_list_json + shot_count_total
- ✅ 2.5 `prompts/tasks/generate_nine_grid.md` 新建：九宫格生图 prompt 编译模板，含跨九宫格衔接规则
- ✅ 2.6 `prompts/compiler/compile_video_prompt.md` 改造（v3 → v4）：加 `first_frame_description` + `last_frame_description` 变量，加首尾帧约束章节

**待用户执行**：
- 🔧 在数据库上手动跑 `scripts/sql/patch_003_nine_grid_columns.sql`（用户将自己执行）

### 2026-04-30：阶段 3（核心 Services）+ 阶段 4（Agents）已完成

**实施过程中的设计修订**：
- 原设计 `extension` 字段在 `brief.raw_payload` 顶层 → 修订为 `creative_brief` 的子字段（避免改动 BriefPersistenceService）
- 同步修订 `creative_planning.md` 输出格式 + `compile_nine_grid_prompt` / `storyboard_service` 解析方式

**阶段 3 完成项**（4 个文件）：
- ✅ 3.1 `backend/app/tools/image_generation_tool.py` 加 `generate_nine_grid()` + `split_and_persist_grid()` + `_ASSET_TYPE_SUBPATH` 加 `nine_grid_image`
- ✅ 3.2 `backend/app/services/prompt_compiler_service.py` 加 `compile_nine_grid_prompt()` + `compile_for_shot` 加 `first_frame_description` / `last_frame_description` 参数
- ✅ 3.3 `backend/app/services/storyboard_service.py` 整体重写为九宫格驱动（含 `_process_single_grid` + 4 个生命周期事件 + 跨九宫格 cell9 物理复用）
- ✅ 3.4 `backend/app/services/shot_plan_persistence_service.py` 加 `derive_from_narrative()` 直接从 narrative 派生 shots

**阶段 4 完成项**（4 个文件）：
- ✅ 4.1 `backend/app/agents/creative_planning_agent.py` `_fallback_brief` 加 extension 子字段
- ✅ 4.2 `backend/app/agents/narrative_script_agent.py` `_fallback_narrative_content` 改为新 shots 格式
- ✅ 4.3 `backend/app/agents/visual_development_agent.py` 加 ⚠️ DEPRECATED 标注
- ✅ 4.4 `backend/app/agents/consistency_guardian_agent.py` 加 ⚠️ DEPRECATED 标注

**已知风险**：
- `StoryboardVersion.raw_payload` 分两次写入（创建空 + 步骤 6 完整更新），中途失败会留半完成
- `derive_from_narrative` 严格依赖 narrative_shots 数量 ≥ `total_shots_generated`
- 九宫格大图生成需配置支持 3072×3072 的 image provider（默认 `flux_schnell` 可能不够）

### 2026-04-30：阶段 5（Workflow）+ 阶段 6（API）已完成

**实施过程发现的简化**：
- §4.6 P5-5.3 `storyboard_node.py` 接口兼容，**不需要改动**（`generate_and_save` 签名不变）
- §4.7 P6-6.1 `project_spec.py` 已支持 `target_duration_sec` / `platform` / `target_audience` / `style_preference` / `aspect_ratio` 等所有新流程字段，**不需要改动**

**阶段 5 完成项**（3 个文件，1 个不改）：
- ✅ 5.1 `backend/app/workflows/main_graph.py` 注释 visual_bible 相关路由（_ACTION_NODE_MAP + _route_after_director）
- ✅ 5.2 `backend/app/workflows/graph_state.py` `visual_bible_confirmed` / `visual_bible_ref` 加 ⚠️ DEPRECATED 注释
- ⊘ 5.3 `backend/app/workflows/nodes/storyboard_node.py` 接口兼容，不改

**阶段 6 完成项**（4 个文件，1 个不改）：
- ⊘ 6.1 `backend/app/api/v1/project_spec.py` 已支持新字段，不改
- ✅ 6.2 `backend/app/api/v1/storyboard.py` 新增 `GET /storyboard/grids` 接口
- ✅ 6.3 `backend/app/api/v1/visual_bible.py` 文件顶部加 ⚠️ DEPRECATED docstring（**保留文件不删**，避免级联编译错误）
- ✅ 6.4 `backend/app/main.py` 注释 visual_bible_router 的 import 行 + include_router 行（外部不可访问）

**重要提醒**：visual_bible.py 文件本身保留，原因是 visual_bible_service 仍被 agents 等部分引用，删除会引入级联错误。如要彻底删除需单独立项清理。

**进度**：28/35 文件完成（80%）

**下一步**：阶段 7（前端，5 个文件），需要用户批准后执行。后端九宫格全链路已完整可独立测试。

### 2026-04-30：阶段 7（Frontend）已完成 + 阶段 8（验收测试）取消

**实施过程发现的额外文件**（原 5 个 → 实际 7 个）：
- 多了 `frontend/src/services/api.ts`（加 `getStoryboardGrids` 方法）
- 多了 `frontend/src/pages/Workbench.tsx`（`handleDecision` 的 `confirm_narrative` case 改为跳过视觉圣经直接生 shot_plan）

**阶段 7 完成项**（7 个文件）：
- ✅ 7.1 `frontend/src/components/workbench/ProcessNodes.tsx` 删除"视觉圣经"菜单项；"剧本创作"节点 backendStages 加 `visual_bible_ready` 兼容旧项目
- ✅ 7.2 `frontend/src/components/workbench/SetupView.tsx` 流程提示文案改为"创意方案 → 剧本 → 九宫格分镜 → 视频片段 → 拼接导出"
- ✅ 7.3 `frontend/src/components/workbench/BriefView.tsx` 新增"视频规划"概览卡片（含 target_duration_sec / shot_count / grid_count / aspect_ratio / character_list / target_platform / target_audience / visual_style）
- ✅ 7.4 `frontend/src/components/workbench/StoryboardReviewer.tsx` 加九宫格视图（每张大图 + 3×3 切分 cell 网格 + 复用标签）；`refreshFlag` 触发增量更新；表格"歌词/内容"列改为"画面描述"+"场景"
- ✅ 7.5 `frontend/src/lib/sse.ts` 加 4 个九宫格事件（grid.generating / generated / split_done / all_grids_completed）+ onmessage handler
- ✅ 7.6 `frontend/src/services/api.ts` 加 `projectService.getStoryboardGrids()`
- ✅ 7.7 `frontend/src/pages/Workbench.tsx` `handleDecision` 中 `confirm_narrative` case 改为直接调 `generateShotPlan`（跳过 `initVisualBible`）

**阶段 8 取消**：用户决定自行结合前端实测，不再走架构师层面的端到端验收。

**最终进度**：32/32 工程文件 + 1 篇设计文档 = 100% 完成。

---

## 重构最终交付物总览（32 个工程文件）

### 后端
- schemas: 2 个（project.py 加扩展 + 新建 storyboard.py）
- models: 2 个（storyboard.py + asset.py）
- storage: 1 个（path_planner.py）
- SQL patch: 1 个新建（patch_003_nine_grid_columns.sql）
- tools: 1 个（image_generation_tool.py）
- services: 3 个（prompt_compiler / storyboard 重写 / shot_plan_persistence）
- agents: 4 个（creative_planning / narrative_script / 2 个 deprecated）
- workflows: 2 个（main_graph / graph_state）
- api: 3 个（storyboard 加接口 / visual_bible deprecated / main.py 注销路由）
- prompts: 6 个（5 改 + 1 新建）

### 前端
- components: 4 个（ProcessNodes / SetupView / BriefView / StoryboardReviewer）
- lib: 1 个（sse.ts）
- services: 1 个（api.ts）
- pages: 1 个（Workbench.tsx）

### 文档
- docs/21_VidMuse九宫格分镜重构方案.md（含 4 次进度日志更新）

---

## 用户必须执行的运维步骤

1. **跑 SQL**：`psql -f scripts/sql/patch_003_nine_grid_columns.sql`
2. **重启后端**：让新 prompt / service / model 加载
3. **配置 3072×3072 image provider**：`config/providers/image_providers.yaml`
4. **前端**：dev 模式自动热更新，生产需 `npm run build`

---

## 端到端测试建议

| 用例 | 输入 | 预期 |
|---|---|---|
| **1 分钟视频** | 主题 + 时长 60s + tiktok | 1 张九宫格 + 6 i2v 片段 |
| **1.5 分钟视频** | 时长 90s | 2 张九宫格（cell 1 复用 cell 9） + 9 i2v 片段 |
| **兼容性** | 打开旧 visual_bible_ready 项目 | 正常打开，侧边栏映射到"剧本创作" |

---

**文档结束**

*本文档落地后，开发严格按 §9.3 流程推进。每个文件改动前，架构师贴方案，用户审核批准后再动手。*
