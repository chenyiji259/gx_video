# VidMuse 实现偏差与待补充设计记录

> 文档目标：记录当前代码实现与产品预期流程之间的偏差，以及需要补充的设计空白。
>
> 来源：2026-03-31 流程对齐讨论，基于实际代码分析得出。
>
> 凡本文档记录的条目，均需在后续开发迭代中修正或补充。与 doc11 冲突时，以本文档为准（本文档更新）。

***

## 偏差 1：音频分析无 SSE 进度推送（同步阻塞问题） **[已完成]**

### 当前实现

`AudioAnalysisService.run_and_save()` 是同步执行，直接在 HTTP 请求或 LangGraph 图节点内完成，耗时约 10-30 秒。没有 Worker 队列、没有 SSE 进度事件。用户必须等待 HTTP 响应才能收到"分析完成"的信息。

### 预期体验

用户进入工作台后，系统立即开始分析音频，右侧对话栏展示"正在分析音频，请等待（预计 xx 秒）"，左侧 Pipeline 节点状态变为"进行中"，分析完成后通过 SSE 推送结果，Director 自动汇报分析摘要（BPM、段落、歌词等），无需用户主动发消息触发。

### 需要补充的工作

1. **触发方式**：前端进入工作台（`input_ready` 阶段）时，自动调用 `POST /api/v1/projects/{id}/workflow/analyze-audio`，不依赖用户发送聊天消息。REST 接口已有，只需前端自动触发。
2. **异步化**：将 `AudioAnalysisService.run_and_save()` 移入 Worker 队列（新增 `analyze_audio` handler），与 storyboard/clips 保持一致。
3. **SSE 事件**：Worker 完成后推送：
   - `audio.analysis.progress`（如有中间进度）
   - `audio.analysis.completed`（含 BPM、段落数、歌词行数摘要）
   - `project.stage.changed`（阶段推进到 `audio_analyzed`）
4. **Director Mode B 汇报**：`analyze_audio` 任务完成后，`DirectorReportService` 自动触发，Director 展示音频结构摘要并推荐风格方向。需要将 `analyze_audio` 加入 `_REPORT_TASK_TYPES`。

### 影响范围

- `backend/app/tasks/worker.py` — 新增 handler
- `backend/app/services/audio_analysis_service.py` — 保持不变，handler 直接调用
- `backend/app/services/director_report_service.py` — 新增 `analyze_audio` 到白名单
- `backend/app/workflows/nodes/audio_analysis_node.py` — 改为 dispatch 模式
- 前端工作台 — 进入时自动触发

***

## 偏差 2：叙事剧本生成无 SSE 进度（同步执行，可接受） **[已完成]**

### 当前实现

`NarrativeScriptService.generate_and_save()` 在 LangGraph `narrative_node` 内同步调用 LLM，耗时约 10-20 秒，直接返回聊天回复，没有 Worker 队列和 SSE 进度。

### 预期体验

后台开始生成叙事剧本，右侧对话栏提示"正在生成叙事剧本，请稍等"，生成完成后 Director 主动展示结果（故事弧线、角色列表、场景列表、段落映射），而不是用户再发一条消息才看到。

### 现状评估

LLM 调用 10-20 秒属于可接受范围（不像图片/视频需要几分钟）。当前实现的实际效果是：用户发送"确认 brief，继续"后，等待约 15 秒，聊天回复里直接包含叙事剧本摘要。体验上可接受，但缺少"等待中"的状态反馈。

### 需要补充的工作（优先级 P2）

短期方案（低成本）：在 `narrative_node` 返回前，先通过 Project SSE 推送一条 `narrative.generating` 事件，告知前端"正在生成"，生成完后推 `narrative.completed`。图节点内同步执行，但前端有了过渡状态显示。

中期方案（彻底解决）：与 storyboard/clips 一样移入 Worker 队列，支持真正的异步化。

***

## 偏差 3：同一角色多套造型的数据结构缺失（设计空白）

### 当前实现

`character_set_versions` 表中，每个角色只有一个 `active_reference_asset_id`（一张定妆图）。这张图作为所有分镜帧的统一人物参考，覆盖全 MV。

### 实际产品需求

MV 中同一角色在不同场景/段落可能有不同造型：

- verse 段落：校园日常穿搭
- chorus 段落：华丽舞台礼服
- bridge 段落：复古街头风格

这些造型共用同一张"脸"（用户上传的参考图或 txt2img 生成的基础脸），但服装、妆容、发型可以不同，由叙事剧本中各段落的剧情驱动。

### 三种角色图来源及处理方式

| 情况                     | 来源        | 处理方式                     | 当前支持         |
| ---------------------- | --------- | ------------------------ | ------------ |
| 未上传角色图                 | 无         | txt2img 全部生成             | ✅ 已支持        |
| 上传了可直接用的参考图（如角色插画、艺术图） | 用户上传      | 直接作为 IP reference        | ✅ 已支持        |
| 上传了不可直接用的图（如自拍照）       | 用户上传      | img2img 风格化：保留脸部特征，换装换风格 | ✅ 已支持        |
| 同一角色需要多套造型             | 由叙事剧本段落定义 | 每套造型单独生成一张定妆图            | ❌ **数据结构缺失** |

### 需要补充的设计

#### 方案 A（推荐）：角色-造型分层

在 `character_set_versions` 的角色结构中，增加 `costumes`（造型）子列表：

```json
{
  "character_id": "char_001",
  "character_name": "主角",
  "description": "20岁短发女生",
  "base_face_asset_id": "asset_xxx",
  "costumes": [
    {
      "costume_id": "costume_verse",
      "label": "日常穿搭",
      "applies_to_sections": ["intro", "verse"],
      "reference_asset_id": "asset_yyy",
      "user_confirmed": true
    },
    {
      "costume_id": "costume_chorus",
      "label": "舞台礼服",
      "applies_to_sections": ["chorus", "outro"],
      "reference_asset_id": "asset_zzz",
      "user_confirmed": true
    }
  ],
  "active_reference_asset_id": "asset_yyy"
}
```

`shot_plan` 生成时，每个 Shot 根据 `section_type` 匹配对应造型的 `reference_asset_id`，而不是统一用 `active_reference_asset_id`。

#### 方案 B（简化）：多角色实体

叙事剧本里将"角色 A verse 造型"和"角色 A chorus 造型"定义为两个独立角色实体（如 `char_001_verse`、`char_001_chorus`）。实现简单，但角色列表会膨胀，对用户不友好。

#### 推荐方案

采用方案 A，在以下位置修改：

- `character_set_versions.characters` JSONB 结构：增加 `costumes` 数组
- `NarrativeScriptAgent` 输出：在 `section_mapping` 里指定每段用哪套造型
- `VisualBibleService`：新增 `generate_costume_reference()` 方法
- `ShotPlanPersistenceService`：Shot 生成时按段落匹配造型，填充 `character_ref_asset_id`
- `VisualBibleAPI`：新增造型生成接口

### 影响范围

- `backend/app/models/visual_bible.py` — `CharacterSetVersion` 结构调整
- `backend/app/services/visual_bible_service.py` — 新增造型生成方法
- `backend/app/services/narrative_script_service.py` — 叙事剧本包含造型信息
- `backend/app/services/shot_plan_persistence_service.py` — 按段落匹配造型
- `backend/app/api/v1/visual_bible.py` — 新增造型接口
- `scripts/init_schema.sql` — 无需改表，JSONB 结构扩展向前兼容

***

## 偏差 4：音频分析架构升级 —— 引入 Qwen3.5 Omni 替换 librosa 全链路（设计空白）

### 背景

经百炼平台测试确认，Qwen3.5 Omni 是全模态模型，可直接接收音频文件，一次调用输出完整结构化音乐分析 JSON（doc 13 的 prompt 已验证）。这使得当前 librosa + WhisperX + AudioAnalysisAgent 三层链路存在大量冗余，且段落检测精度远低于 Omni。

### 当前实现的问题

- `librosa` 段落切分只能按时长均匀切割 + 能量阈值，无法真正识别 Verse / Chorus / Bridge
- `WhisperX` 歌词对齐是可选依赖，未安装时跳过，中文识别稳定性受环境影响
- `AudioAnalysisAgent` 只是用 LLM 二次解读 `librosa` 数字，多一次 LLM 调用但贡献有限
- 整体链路 5 步串行，耗时长，结构理解质量不高

### 调整后架构：两步并发

```text
步骤 1（librosa，保留）：
  仅跑 beat.beat_track() → 输出精确毫秒级 beat_map
  目的：Omni 输出的是段落级 BPM，不含逐拍时间戳，视频卡节拍切割依赖此数据

步骤 2（Qwen3.5 Omni，新增）：
  直接分析音频文件 → 一次输出完整结构化 JSON
  包含：段落结构 / 歌词（中英文）/ 和弦进行 / 乐器 / 情绪弧线 / 五秒粒度分析

两步并发执行，结果合并落库 → 完成
```

### Omni 替代范围

- `librosa` 全局分析：**保留 beat\_track 部分，其余废弃**
- `WhisperX` 歌词对齐：**完全替代**
- `AudioAnalysisAgent`：**合并废弃**
- 段落检测：**完全替代，精度大幅提升**
- 和弦进行：**新增能力**
- 乐器检测：**新增能力**

### 新增音频分析输出字段（落库到 `audio_analysis_versions`）

当前 `audio_analysis_versions` 表已有 `key_scale`、`style_caption` 等预留字段（doc10 §4.4），Omni 的新输出需要补充映射：

- `chord_progression`：整体和弦走向（JSONB，新字段）
- `instrumentation`：乐器列表（JSONB，新字段）
- `five_second_analysis`：五秒粒度详细分析（JSONB，新字段）

### 模型分工（整体架构调整）

- **Director Agent**：Qwen3.5 Omni\
  唯一对话出口，多模态（音频 / 图片 / 视频均可理解）
- **音频分析**：Qwen3.5 Omni\
  替代 `librosa` 全链路（`beat_map` 保留 `librosa`）
- **图片审核（角色图 / 分镜审核）**：Qwen3.5 Omni\
  多模态看图判断
- **叙事剧本 / Shot Plan / Prompt 编译**：高性价比文本模型（DeepSeek / Qwen-text）\
  纯文本推理，不需要多模态
- **图片 / 视频生成**：Flux / Kling / Wan 等 Provider\
  Tool，不是 Agent

### 影响范围

- `backend/app/tools/audio_analysis_tool.py` — 只保留 `beat_track()`，删除其余分析
- `backend/app/tools/lyrics_alignment_tool.py` — 废弃或保留为备用降级路径
- `backend/app/agents/audio_analysis_agent.py` — 重写为 Omni 调用，直接输出 `quality_summary`
- `backend/app/services/audio_analysis_service.py` — 流程简化为两步并发
- `backend/app/models/audio_analysis.py` — 新增 `chord_progression` / `instrumentation` / `five_second_analysis` 字段
- `scripts/init_schema.sql` — `audio_analysis_versions` 表新增字段
- `config/` Provider 配置 — 注册 Omni 模型路由

***

## 偏差 5：角色图类型自动判断 + 多套造型生成（偏差 3 的 Omni 实现方案）

### 背景

偏差 3 记录了“同一角色多套造型数据结构缺失”和“角色图类型判断逻辑缺失”两个问题。引入 Qwen3.5 Omni 后，两个问题都有了具体实现路径。

### 子问题 A：角色图类型自动判断（Omni 看图）

**当前问题**：`generate_character_reference()` 的 `generation_mode` 参数由调用方手动指定，没有自动判断用户上传图是否适合直接用。

**Omni 解法**：Director（Omni）在 VisualBible 初始化前，对每张用户上传的 `image_reference` 资产看图分析：

```json
{
  "image_type": "realistic_photo",
  "usable_directly": false,
  "reason": "用户自拍照，面部特征清晰但服装/背景不符合MV风格",
  "recommended_mode": "image_to_image",
  "face_quality": "high",
  "requires_costume_generation": true
}
```

`VisualBibleService.generate_character_reference()` 根据此分析结果自动选择 `generation_mode`，无需用户或前端指定。

**新增接口建议**：`POST /api/v1/projects/{id}/visual-bible/analyze-reference-image`

- 输入：`asset_id`（用户上传的 `image_reference`）
- 输出：图片类型判断 + 推荐处理方式
- 在 `init_from_narrative` 前后调用均可，结果写入 `CharacterSetVersion` 对应角色的 `image_analysis` 字段

### 子问题 B：多套造型生成（Omni 驱动）

**Omni 解法**：叙事剧本确认后，Director（Omni）读取 `section_mapping` + `style_bible` + 基础脸图，为每个角色自动推导每个段落需要的造型，输出结构化造型描述列表：

```json
{
  "character_id": "char_001",
  "costumes": [
    {
      "costume_id": "costume_verse",
      "label": "日常穿搭",
      "applies_to_sections": ["intro", "verse"],
      "generation_prompt": "同一女性角色，保持原图脸部特征，校园风穿搭，浅色卫衣+牛仔裤，日系清新风格",
      "generation_mode": "image_to_image",
      "source_asset_id": "base_face_asset_id"
    },
    {
      "costume_id": "costume_chorus",
      "label": "舞台礼服",
      "applies_to_sections": ["chorus", "outro"],
      "generation_prompt": "同一女性角色，保持原图脸部特征，华丽礼服+红唇，强光逆光，电影感",
      "generation_mode": "image_to_image",
      "source_asset_id": "base_face_asset_id"
    }
  ]
}
```

每套造型送入 `generate_costume_reference()`（偏差 3 中待新增方法），各自生成一张定妆图，落库为独立 Asset。

### Shot 绑定逻辑调整

`ShotPlanPersistenceService` 生成 Shot 时，根据该 Shot 的 `section_type` 自动匹配对应造型：

```text
Shot.section_type == "verse"  → character_ref_asset_id = costume_verse.reference_asset_id
Shot.section_type == "chorus" → character_ref_asset_id = costume_chorus.reference_asset_id
```

不再使用统一的 `active_reference_asset_id`。

### 影响范围（偏差 3 + 偏差 5 合并）

- `backend/app/agents/director_agent.py` — 新增图片分析 Tool Call
- `backend/app/services/visual_bible_service.py` — 新增 `analyze_reference_image()` 和 `generate_costume_reference()`
- `backend/app/api/v1/visual_bible.py` — 新增 `analyze-reference-image` 和 `generate-costume-ref` 接口
- `character_set_versions.characters` JSONB 结构 — 增加 `base_face_asset_id`、`image_analysis`、`costumes` 字段
- `backend/app/services/shot_plan_persistence_service.py` — Shot 生成时按段落匹配造型
- `scripts/init_schema.sql` — 无需改表，JSONB 结构扩展向前兼容

***

## 偏差 6：多 Agent 系统架构根本性偏差 —— 当前为 workflow，需重构为生产级 Director-SubAgent 协作模式
（已完成）
> 本偏差是系统最根本的架构性问题，优先级高于偏差 1-5。所有其他偏差的修正方向必须在本偏差描述的正确架构框架内执行。

### 6.1 当前实现的本质

当前系统的实际运行模式是：

```
用户消息
  → /v1/chat/completions
  → Director LLM 输出 next_action
  → _route_after_director() 代码分支路由
  → 对应 graph 节点（实为 Python 函数）
  → 节点内直接调用 Service 同步执行
  → 硬编码 assistant_message 返回用户
```

这是 **"Director-led workflow"（由 Director 决定走哪条 if/else 分支的状态机流程）**，不是多 Agent 协作架构。

核心问题清单：

1. **专业 Agent 不是运行时主体**：`creative_planning_agent.py` / `narrative_script_agent.py` 等都只是被 node 内部直接调用的函数模块，没有自己的 LLM tool-calling 循环，没有独立生命周期。
2. **产物内容在进程内直接传递**：节点之间通过函数返回值或内存对象传递结构化内容，没有落盘 + 引用传递机制。Director 没有「读产物路径」的行为，只有「接收函数返回值」的行为。
3. **Director 没有真正的 dispatch 能力**：Director 的权力边界只是「输出 next\_action 字符串」，实际的任务派发由代码路由完成，不是 Director 主动调用工具。
4. **审核层不存在**：产物生成完就直接写 `assistant_message` 返给用户，没有「生成 → 落盘 → Director 主动读取审核 → 汇报」的完整闭环。
5. **Worker 完成无法唤醒 Director**：异步任务完成后没有任何机制让 Director 主动汇报，用户必须自己再发消息才能看到结果。

***

### 6.2 正确的生产级多 Agent 架构

目标架构类比 Claude Code 的工作方式：主 Agent 负责理解、调度、审核、沟通；Sub-Agent 负责专业执行；所有产物通过存储引用传递，不在进程内直接传内容。

#### 6.2.1 框架选型结论

**保持 LangGraph，但用法根本性改变。**

| 需求              | 说明                                                |
| --------------- | ------------------------------------------------- |
| Director 多轮对话状态 | LangGraph checkpoint 原生支持（保留）                     |
| 阶段路由            | LangGraph conditional edges（保留）                   |
| Sub-agent 作为工具  | `create_react_agent` + compiled graph as tool（新增） |
| 生产级持久化          | `AsyncPostgresSaver` 替换 `MemorySaver`（后续）         |

LangChain 用于工具装饰器（`@tool`）和 `create_react_agent`，不单独作为框架。

***

#### 6.2.2 ArtifactRef 协议（核心设计）

**原则：Agent 之间只传产物引用，不传产物内容。**

所有产物生成后必须：

1. 写入本地文件（`data/projects/{id}/` 对应阶段目录，供调试）
2. 上传 MinIO（生产存储）
3. 落库 Asset 记录（`assets` 表）
4. 返回 `ArtifactRef` 引用对象

```json
// ArtifactRef 结构（Agent 间传递的唯一凭证）
{
  "artifact_id": "narrative_v1",
  "artifact_type": "narrative_script",
  "local_path": "data/projects/proj_001/03_brief/narrative_v1.json",
  "minio_uri": "s3://vidmuse/proj_001/narrative_v1.json",
  "version_no": 1,
  "summary": "3个角色，4个场景，段落×情节映射完成"   ← 仅摘要，不含全文
}
```

Director 需要读取完整内容时，主动调用 `read_artifact(ref)` 工具。不需要时，只看 `summary` 和 `artifact_id`。

**Graph State 中绝对禁止出现的内容类型：**

```python
# ❌ 错误：在 graph state 中存放原文
brief_content: str          # 创意方案全文
narrative_text: str         # 叙事剧本全文
shot_specs: list[dict]      # 所有镜头语义对象

# ✅ 正确：在 graph state 中只存放引用
brief_ref: dict | None      # {artifact_id, local_path, minio_uri, summary}
narrative_ref: dict | None  # 同上
shot_plan_ref: dict | None  # 同上
```

***

#### 6.2.3 共享工具层（所有 Agent 均可调用）

工具定义位置：`backend/app/tools/shared/`

```python
# --- 产物读写工具 ---

@tool
def read_artifact(artifact_ref: dict) -> dict:
    """
    从本地文件读取产物内容（优先本地，降级 MinIO）。
    输入：{"local_path": "...", "artifact_id": "..."}
    输出：产物完整内容（JSON）
    用途：Director 审核产物 / Sub-agent 读取上游输入
    """

@tool
def write_artifact(
    content: dict,
    project_id: str,
    artifact_type: str,   # narrative_script / shot_plan / visual_bible / ...
    version_no: int,
) -> dict:
    """
    将产物写入本地文件 + 上传 MinIO + 落库 Asset。
    返回：ArtifactRef（含 artifact_id / local_path / minio_uri / summary）
    规则：Sub-agent 完成工作后必须调用此工具，不允许直接返回内容
    """

# --- 生成模型工具（封装所有外部 Provider，统一接口）---

@tool
def generate_image(
    prompt: str,
    mode: str,                      # text_to_image | image_to_image
    reference_image_url: str | None,
    project_id: str,
    target_id: str,                 # character_id / scene_id / shot_id
    provider: str = "flux_dev",
) -> dict:
    """
    调用图片生成 Provider，产物上传 MinIO，落库 Asset。
    返回：{"asset_id": ..., "url": ..., "provider": ..., "cost_credits": ...}
    不在返回值中包含图片 bytes，只返回可访问的 URL
    """

@tool
def generate_video(
    storyboard_frame_url: str,
    duration_sec: float,
    project_id: str,
    shot_id: str,
    provider: str = "kling",
) -> dict:
    """
    提交视频生成异步任务（不等结果）。
    返回：{"job_id": ..., "status": "submitted", "estimated_minutes": ...}
    """

@tool
def get_asset_url(asset_id: str) -> str:
    """
    根据 asset_id 查询 MinIO 预签名 URL（有效期 24h）。
    用于：Sub-agent 需要把已有资产 URL 传给生成工具时调用
    """
```

工具定义位置：`backend/app/tools/director/`

```python
# --- Director 专属工具 ---

@tool
async def dispatch_agent(
    agent_name: str,    # "narrative_agent" | "visual_dev_agent" | "creative_planning_agent"
    task_spec: dict,    # {"inputs": {"brief_ref": ArtifactRef, ...}, "task_type": ...}
) -> dict:
    """
    派发任务给 Sub-Agent，等待返回 ArtifactRef。
    Sub-agent 内部运行 LLM tool-calling 循环，Director 不感知内部细节。
    返回：ArtifactRef（Sub-agent 调用 write_artifact 后的引用）
    """

@tool
async def create_decision(
    decision_type: str,
    options: list[dict],
    context_summary: str,   # 向用户展示的决策背景摘要，不是完整产物内容
) -> str:
    """创建 PendingDecision，返回 decision_id。"""

@tool
async def get_project_state() -> dict:
    """读取当前 ProjectSnapshot（阶段、版本、决策状态）。"""

@tool
async def estimate_cost(
    action: str,
    params: dict,
) -> dict:
    """估算高成本动作的 credits 消耗，返回明细。"""
```

***

#### 6.2.4 Sub-Agent 工作协议

每个 Sub-Agent 遵循相同的工作协议：

```python
# 正确结构（以 NarrativeScriptAgent 为例）
# 位置：backend/app/agents/narrative_script_agent.py

from langgraph.prebuilt import create_react_agent

NARRATIVE_TOOLS = [
    read_artifact,      # 读 brief / audio_analysis（通过 ArtifactRef）
    write_artifact,     # 写 narrative_script，返回 ArtifactRef
]

class NarrativeScriptAgent:
    def __init__(self):
        self._agent = create_react_agent(
            model=ChatOpenAI(model="deepseek-chat"),   # 文本模型，不需要多模态
            tools=NARRATIVE_TOOLS,
            state_modifier=load_system_prompt("narrative_script_system"),
        )

    async def run(self, task_spec: dict) -> dict:
        """
        接收 task_spec（包含输入 ArtifactRef）。
        运行 LLM tool-calling 循环：
          1. LLM 决定调用 read_artifact 读取 brief 内容
          2. LLM 生成叙事剧本
          3. LLM 决定调用 write_artifact 写出产物
          4. 返回 write_artifact 的 ArtifactRef
        Sub-agent 自己不和用户说话，只和 Director 交互。
        """
        result = await self._agent.ainvoke({
            "messages": [HumanMessage(content=self._build_task_message(task_spec))]
        })
        return self._extract_artifact_ref(result)  # 从 tool call 结果中提取 ArtifactRef

    def _build_task_message(self, task_spec: dict) -> str:
        # 传的是引用，不是内容
        return (
            f"任务类型：{task_spec['task_type']}\n"
            f"创意方案引用：{task_spec['inputs']['brief_ref']}\n"
            f"音频分析引用：{task_spec['inputs']['audio_ref']}\n"
            f"项目ID：{task_spec['project_id']}\n"
            f"请读取上述引用中的内容，完成叙事剧本生成，"
            f"并使用 write_artifact 工具写出产物。"
        )
```

**Sub-Agent 设计铁律：**

- 有自己的 LLM tool-calling 循环（`create_react_agent`），不是一个 Python 函数
- 只能用 `read_artifact` 读取上游产物，不接收原文内容作为参数
- 完成后必须调用 `write_artifact` 写出产物，返回值只有 `ArtifactRef`
- 不和用户说话，不感知用户的存在
- Sub-agent 只和 Director 对话（通过 task\_spec 输入 / ArtifactRef 输出）

***

#### 6.2.5 Director 的三态工作循环

```
状态 A：等待 Sub-Agent / Worker 异步任务完成
  触发条件：已 dispatch 生成任务，正在等 Worker / Sub-agent 返回
  期间：Director 不阻塞，可以继续处理用户其他消息
  结束条件：WorkerCompletedEvent 触发 → 进入状态 B

状态 B：Director 主动审核（Mode B 汇报模式）
  触发条件：系统事件（Worker 完成 / Sub-agent 返回）
  期间：Director 调用 read_artifact 读取产物，
        必要时调用 ConsistencyGuardianAgent 质检，
        生成三段式汇报（结果描述 + 判断推荐 + 下一步问题）
  写入：assistant_message 落库 → SSE 推给前端 Chat 区
  结束条件：汇报写入完成 → 进入状态 C

状态 C：等待用户确认（PendingDecision）
  触发条件：Director 审核完毕，创建 PendingDecision，项目阶段不推进
  期间：用户可以持续和 Director 对话，Director 进入 Mode A（对话模式）
  结束条件：用户点击确认 / 在对话中明确说"可以"
  下一步：项目阶段推进，进入下一个 dispatch 循环，回到状态 A
```

**Mode A / Mode B 触发源区分（代码层必须显式化）：**

```python
# graph_state.py 中的触发源字段
system_trigger: dict | None
# system_trigger is None     → Mode A（用户发消息，Director 对话响应）
# system_trigger is not None → Mode B（系统事件，Director 主动汇报）

# Mode B trigger 结构示例
{
    "type": "task_completed",
    "task_type": "generate_narrative_script",
    "result": {
        "artifact_ref": {"artifact_id": "narrative_v1", "local_path": "..."},
        "sub_agent": "narrative_script_agent"
    }
}
```

***

#### 6.2.6 重构后的 Director Agent 工作方式

```python
# Director 运行流程（正确版）

# Mode A（对话）：用户说话
async def director_mode_a(state):
    # Director 有以下工具可调用：
    # - dispatch_agent(...)     → 派发给 Sub-agent
    # - read_artifact(ref)      → 主动读取某个产物内容（审核用）
    # - create_decision(...)    → 创建 PendingDecision
    # - get_project_state()     → 查当前阶段 + 决策状态
    # - estimate_cost(...)      → 高成本操作前报价
    pass

# Mode B（汇报）：Worker/Sub-agent 完成后系统触发
async def director_mode_b(state):
    # 1. 从 system_trigger 拿到 ArtifactRef
    # 2. 调用 read_artifact(ref) 读取产物内容（如需审核）
    # 3. 调用 consistency_guardian 质检（如需）
    # 4. 生成三段式汇报：结果描述 + 判断推荐 + 下一步问题
    # 5. 创建 PendingDecision（等用户确认）
    # 6. 写入 assistant_message → SSE 推给前端
    pass
```

**Director 的多模态审核时机（不是每次都看图）：**

| 阶段       | 是否需要 Director 看图 | 说明                     |
| -------- | ---------------- | ---------------------- |
| 叙事剧本生成后  | ❌ 纯文本            | 只需读取文本 ArtifactRef     |
| 角色参考图生成后 | ✅ 必须看图           | 审核一致性 + 给推荐            |
| 场景参考图生成后 | ✅ 看图             | 审核氛围符合 style\_bible    |
| 分镜图全部生成后 | ✅ 抽样看图           | 配合 ConsistencyGuardian |
| 日常对话     | ❌                | 纯文本即可                  |

***

#### 6.2.7 重构后的 Graph State 设计

```python
# 重构后 ProjectGraphState（只含引用，不含原文内容）

class ProjectGraphState(TypedDict, total=False):
    # --- 输入字段（每轮由 openai_compat.py 或 system_trigger 填充）---
    user_id: str
    project_id: str
    session_id: str
    user_message: str
    history: list[dict]             # 最近 N 条对话（OpenAI messages 格式）
    system_trigger: dict | None     # None=Mode A，有值=Mode B

    # --- 产物引用字段（由 load_project_snapshot 从 DB 加载，只有引用）---
    project_snapshot: dict | None   # 阶段 + active_versions（不含内容）
    brief_ref: dict | None          # ArtifactRef
    narrative_ref: dict | None      # ArtifactRef
    visual_bible_ref: dict | None   # ArtifactRef
    shot_plan_ref: dict | None      # ArtifactRef

    # --- 决策状态字段（布尔 / 枚举，来自 DB decisions 表）---
    style_direction: str | None
    brief_confirmed: bool
    narrative_confirmed: bool
    visual_bible_confirmed: bool
    shot_plan_confirmed: bool
    storyboard_confirmed: bool
    open_decisions: list[dict]      # 当前 open 状态的 decisions 列表（轻量 dict）

    # --- 多模态附件引用（URL，不是 bytes）---
    reference_image_urls: list[str] # 用户上传的参考图 URL
    audio_url: str | None           # 音频文件 URL

    # --- 输出字段 ---
    assistant_message: str
    requires_confirmation: bool
    next_action: str | None
    pending_decision_id: str | None
    error: str | None

# ❌ 以下字段从 Graph State 中完全移除：
# quality_summary: dict     → 需要时通过 read_artifact 读取，不在 state 里
# director_output: dict     → 中间产物，不需要持久化在 state
```

***

#### 6.2.8 完整运行时链路示意

```
用户："请帮我生成叙事剧本"

1. openai_compat.py → invoke_director_graph(mode=A)

2. Director 在 Mode A 下：
   - 感知阶段：brief_ready + brief_confirmed=True
   - 调用 dispatch_agent("narrative_agent", {
       "inputs": {
           "brief_ref": brief_ref,      # ArtifactRef，不是 brief 原文
           "audio_ref": audio_ref,
       },
       "task_type": "generate_narrative_script"
     })

3. NarrativeScriptAgent（独立 LLM tool-calling 循环）：
   - Tool call: read_artifact(brief_ref) → 读取 brief 原文
   - Tool call: read_artifact(audio_ref) → 读取音频分析结果
   - LLM 生成叙事剧本 JSON
   - Tool call: write_artifact(content, "narrative_script", v1)
     → 写本地文件 data/projects/.../03_brief/narrative_v1.json
     → 上传 MinIO
     → 落库 Asset
     → 返回 ArtifactRef
   - 返回 ArtifactRef 给 Director

4. Director 收到 ArtifactRef（不是叙事剧本全文）：
   {"artifact_id": "narrative_v1", "local_path": "...", "summary": "3个角色，4个场景"}

5. Director 进入 Mode B（审核模式）：
   - 调用 read_artifact(narrative_ref) 读取完整叙事剧本（用于审核）
   - 生成三段式汇报：
     段1：叙事剧本已生成。共 3 个角色，4 个场景，段落映射完整...
     段2：故事弧线符合歌词情感走向，副歌段落的情绪设计合理...
     段3：请查看叙事剧本摘要，是否确认这个叙事方向？
   - 创建 PendingDecision(confirm_narrative)
   - 写入 assistant_message → SSE 推给前端

6. 用户："可以，确认"
   → 提交 decision → narrative_confirmed=True → 推进到下一阶段
```

***

### 6.3 改造范围与保留原则

| 模块                              | 处置          | 说明                                                                                                                                                                 |
| ------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 状态机（ProjectStage / transitions） | ✅ 完全保留      | 无问题                                                                                                                                                                |
| PostgreSQL / Repository 层       | ✅ 完全保留      | 无问题                                                                                                                                                                |
| MinIO 适配器 / 本地存储                | ✅ 完全保留      | 无问题                                                                                                                                                                |
| Worker / TaskDispatcher         | ✅ 完全保留      | 无问题                                                                                                                                                                |
| SSE / Outbox                    | ✅ 完全保留      | 无问题                                                                                                                                                                |
| PendingDecision 系统              | ✅ 完全保留      | 无问题                                                                                                                                                                |
| LangGraph 图框架                   | ✅ 保留框架，改造用法 | 节点内逻辑重写                                                                                                                                                            |
| `ProjectGraphState`             | 🔄 重设计      | 只留引用字段，移除原文字段                                                                                                                                                      |
| `director_agent.py`             | 🔄 重写       | 改为 tool-calling 模式，有 dispatch/read/create\_decision 工具                                                                                                             |
| 所有 `*_agent.py`                 | 🔄 重写       | 改为 `create_react_agent` 结构，配备自己的工具集                                                                                                                                |
| 所有 `*_node.py`                  | 🔄 重写       | 节点变为「Director dispatch → 等待 ArtifactRef 返回」                                                                                                                        |
| `tool_call_bridge_service.py`   | 🔄 重写       | 改为真正的 dispatch\_agent 桥接                                                                                                                                           |
| 工具层                             | 🆕 新建       | `tools/shared/`（read\_artifact / write\_artifact / generate\_image / generate\_video）+ `tools/director/`（dispatch\_agent / create\_decision / get\_project\_state） |
| `DirectorReportService`         | 🆕 新建       | Worker 完成后触发 Director Mode B 汇报的服务                                                                                                                                 |

***

### 6.4 开发执行优先级

本偏差的修正应分批次执行，每批次对应 docs/09 中的一个子任务：

**批次 A（基础协议层，约 800-1200 行）**

1. 新建 `backend/app/tools/shared/artifact_tools.py`（read\_artifact / write\_artifact）
2. 新建 `backend/app/tools/shared/generation_tools.py`（generate\_image / generate\_video）
3. `ProjectGraphState` 去除原文字段，改为引用字段
4. 在所有 `*_node.py` 中补充产物落盘 + ArtifactRef 返回逻辑（不改 LLM 调用部分）

**批次 B（Sub-Agent 独立化，约 1200-1500 行）**

1. `NarrativeScriptAgent` → 改为 `create_react_agent` + NARRATIVE\_TOOLS
2. `VisualDevelopmentAgent`（新建）→ `create_react_agent` + VISUAL\_TOOLS
3. `CreativePlanningAgent` → 改为 `create_react_agent` + CREATIVE\_TOOLS

**批次 C（Director dispatch 能力，约 800-1000 行）**

1. 新建 `backend/app/tools/director/dispatch_tool.py`
2. `director_agent.py` 改为 LLM + tool-calling 模式
3. 对应的 `prompts/system/director.md` 重写（加入 dispatch / read\_artifact 工具使用规范）

**批次 D（Director 主动汇报闭环，约 600-800 行）**

1. `DirectorReportService`（Worker 完成 → 触发 Director Mode B）
2. Worker `succeed_job` 钩子接入 DirectorReportService
3. 主图新增 Mode B 触发路径

***

## 后续待补充条目（用户持续补充中）

> 本节持续更新，每次讨论后追加新的偏差或设计空白。

***

## 文档版本记录

| 版本   | 日期         | 内容                                                                                              |
| ---- | ---------- | ----------------------------------------------------------------------------------------------- |
| v1.0 | 2026-03-31 | 初始建立，记录三条偏差（音频分析异步化、叙事剧本状态反馈、角色多造型）                                                             |
| v1.1 | 2026-03-31 | 新增偏差 4（Omni 替换 librosa + 模型分工调整）、偏差 5（Omni 驱动角色图判断 + 多造型生成）                                     |
| v1.2 | 2026-03-31 | 新增偏差 6（多 Agent 运行时协议 —— ArtifactRef 协议、共享工具层、Sub-agent 工作协议、Director 三态循环、Graph State 重设计、改造范围） |
| v1.3 | 2026-04-01 | 在文档底部追加偏差 6 终态收口执行计划，明确运行时中枢回收、主图去 workflow 主导化、统一 ArtifactRef 协议、统一 Mode B 闭环与全链路验收方案          |

***

## 附录 A：偏差 6 终态收口执行计划（2026-04-01）

### A.1 为什么需要这一轮终态收口

前面的偏差 6 改造已经完成了基础协议层、Sub-Agent 独立化、Director 工具层骨架和部分 Mode B 闭环，但从代码现状看，系统仍未达到本文件 6.2 定义的生产级 Director-SubAgent 协作终态。

当前剩余问题不是边角缺陷，而是运行时所有权仍然分裂：

1. 主图仍通过 `next_action -> _route_after_director() -> node/service` 掌握主执行权，Director 不是唯一调度中枢。
2. `dispatch_agent_tool` 对文本主线任务仍有大量 Service 直调，Sub-Agent 不是唯一运行时主体。
3. ArtifactRef 协议仍是半收口状态，文本产物与媒体产物未统一到同一持久化协议。
4. Mode B 汇报闭环分裂为“图内回环”和“Worker 异步汇报”两套路径，不是统一生产协议。
5. Graph State 仍保留过渡字段，尚未回到“只留引用和轻状态”的目标设计。

所以，这一轮不是“继续补功能”，而是要完成偏差 6 的最终收口：把系统真正从 Director-led workflow 迁移到生产级 Director-SubAgent 闭环。

***

### A.2 本轮终态收口的目标定义

本轮完成后，系统必须同时满足以下条件，才能算偏差 6 真正关闭：

1. Director 成为唯一调度中枢
   - 用户消息进入系统后，由 Director 决定是对话、派发、审核还是创建决策。
   - 主图不再通过大段字符串路由决定文本主线业务节点。
2. Sub-Agent 成为真实运行时主体
   - `creative_planning` / `narrative_script` / `visual_development` 等任务必须由对应 Sub-Agent 执行。
   - 文本主线任务不再允许通过 Director 工具层直接调用 PersistenceService 冒充 dispatch。
3. ArtifactRef 协议成为统一的 Agent 间协议
   - 所有关键产物都要统一满足：本地落盘、MinIO 上传、数据库记录、返回 ArtifactRef。
   - Director 和 Sub-Agent 只通过引用读写产物，不通过 state 或函数参数直接传全文。
4. Mode B 成为统一闭环
   - 任务完成后统一进入：读取产物 → Director 审核 → 三段式汇报 → 创建 PendingDecision → assistant\_message 落库 → SSE 推送。
   - 不再存在“文本任务一套回环、Worker 任务另一套回环”的分裂模式。
5. Graph State 回到纯引用态
   - state 中只保留项目轻状态、决策状态、ArtifactRef 和必要输出字段。
   - 移除 `quality_summary`、`director_output` 这类过渡态中间内容。
6. 验收标准升级为“无已知 bug 的联调闭环”
   - 不只看代码结构，要通过单测、集成测试和关键流程联调验证。
   - 达不到联调闭环，不算完成。

***

### A.3 终态收口的执行原则

#### A.3.1 根因导向

这一轮收口只解决真正决定架构成败的问题，不继续在旧的 workflow 主路径上堆补丁。

#### A.3.2 分批交付

单次改动量仍必须控制在 `2000` 行以内。超过上限时，必须拆分为新的独立批次，不能一次性重写整个系统。

#### A.3.3 复用优先

已经落地的 Agent、ArtifactRef、Worker、Decision、SSE、Outbox、Repository、状态机等能力全部优先复用，只重写其用法，不推倒重来。

#### A.3.4 先收中枢，再收协议，最后收验证

执行顺序必须是：

```text
收回 Director 运行时中枢
-> 主图去 workflow 主导化
-> ArtifactRef 协议统一
-> Mode B 闭环统一
-> 联调与回归验收
```

如果先补验证而不先收中枢，最后只会验证一个结构上仍然分裂的系统。

***

### A.4 终态收口任务拆分

本轮终态收口拆为 5 个连续任务，每个任务都对应明确输入、实现、产出和验收标准。

***

#### 任务 P6-01：收回运行时调度权

当前为什么做：

- 当前最大问题不是没有 Agent，而是系统主路径的执行权仍由主图路由和 Service 直调掌握。
- 只要 Director 不是唯一中枢，后面的所有“闭环”都只是表面闭环。

上一步输入：

- 偏差 6 已有的批次 A / B / C / D 成果
- 已存在的 `DirectorAgent`
- 已存在的文本与视觉 Sub-Agent

本步实现：

1. 重写 `dispatch_agent_tool`，禁止对 `generate_brief` / `generate_narrative` / `generate_shot_plan` 直接调用 Service。
2. 建立统一 dispatch 协议：
   - 文本任务：同步返回 `ArtifactRef`
   - 异步媒体任务：返回 `job_receipt`
3. 重写 `director_agent.py` 的执行约束，让核心业务行为依赖工具调用，而不是把动作字符串交给主图二次解释。
4. 收缩 `intent_resolution_service.py` 的职责，只保留安全白名单和响应归一，不再承担主编排。
5. 评估并收缩 `tool_call_bridge_service.py` 的存在边界，让它从“流程桥接层”退化为“兼容输出层”。

产出结果：

- Director 具备真实 dispatch 能力
- 文本主线任务不再由工具层直调 Service 冒充 Sub-Agent
- 系统运行时的主控制权开始回收至 Director

下一个使用者：

- 任务 P6-02

目录与文件：

- `backend/app/tools/director/director_tools.py`
- `backend/app/agents/director_agent.py`
- `backend/app/services/intent_resolution_service.py`
- `backend/app/services/tool_call_bridge_service.py`
- `backend/app/api/openai_compat.py`
- `prompts/system/director.md`

验收标准：

- `dispatch_agent_tool` 中不再存在 brief / narrative / shot\_plan 的 Service 直调主路径
- Director 执行日志可观察到真实 dispatch 行为
- 文本主线任务执行路径变成 `Director -> dispatch_agent -> Sub-Agent -> ArtifactRef`

预计代码量：

- `700 ~ 1100` 行

***

#### 任务 P6-02：主图去 workflow 主导化

当前为什么做：

- 即使 Director 已具备工具能力，只要主图仍依赖 `_ACTION_NODE_MAP` 控制文本主线，Director 仍不是唯一中枢。

上一步输入：

- 任务 P6-01 已完成运行时调度权回收

本步实现：

1. 重构 `main_graph.py`，让主图退化为：
   - 加载项目快照
   - 区分 Mode A / Mode B
   - 接收系统事件
   - 响应用户
2. 将 `generate_brief_node` / `narrative_node` / `generate_shot_plan_node` 从主路径业务执行节点改成兼容层，必要时从主路由退出。
3. 重写 `human_confirmation_gate.py` 的职责边界：
   - Director 负责创建决策
   - gate 只负责兜底复用或展示确认上下文
4. 削弱 `next_action` 对主流程的控制权，只保留极少数兼容或确定性边界用途。
5. 清理“图驱动文本主线、Director 只是出动作字符串”的混合模式。

产出结果：

- LangGraph 继续保留，但退回到状态承载层
- 文本主线流程不再由 workflow 路由主导
- gate 不再和 Director 争夺决策所有权

下一个使用者：

- 任务 P6-03

目录与文件：

- `backend/app/workflows/main_graph.py`
- `backend/app/workflows/nodes/human_confirmation_gate.py`
- `backend/app/workflows/nodes/creative_planning_node.py`
- `backend/app/workflows/nodes/narrative_node.py`
- `backend/app/api/openai_compat.py`

验收标准：

- 主线生成流程不再依赖 `_ACTION_NODE_MAP` 路由到业务执行节点
- `confirm_*` 决策主创建权回到 Director
- 用户消息与系统事件都通过 Director 进入统一中枢

预计代码量：

- `900 ~ 1400` 行

***

#### 任务 P6-03：统一 ArtifactRef 协议与纯引用态

当前为什么做：

- 现在的 ArtifactRef 还是半协议：文本产物和媒体产物持久化标准不一致，Graph State 也仍保留过渡内容。

上一步输入：

- 任务 P6-02 已完成主图去 workflow 主导化

本步实现：

1. 扩展 `write_artifact` 协议，使关键文本产物也统一具备：
   - 本地落盘
   - MinIO 上传
   - 数据库记录
   - 标准 `ArtifactRef`
2. 优先复用现有 `assets` 表与 `Asset` 模型；若 `asset_type` 不能承载文本 JSON 产物，则增加 migration 和类型扩展。
3. 重写 `artifact_tools.py`，让它不再是“文本/媒体分轨”的半协议实现。
4. 清理 `graph_state.py` 中的过渡字段，移除：
   - `quality_summary`
   - `director_output`
5. 保证 Director 与所有 Sub-Agent 只通过 ArtifactRef 读取上游信息，不接受正文摘要注入。

产出结果：

- 所有关键产物统一成为 DB-backed ArtifactRef
- Graph State 回到只留引用和轻状态的终态设计
- 文本任务与媒体任务的产物协议一致

下一个使用者：

- 任务 P6-04

目录与文件：

- `backend/app/tools/shared/artifact_tools.py`
- `backend/app/workflows/graph_state.py`
- `backend/app/models/asset.py`
- `backend/app/services/asset_service.py`
- `backend/migrations/*`

验收标准：

- brief / narrative / shot\_plan / audio / storyboard 至少具备统一 ArtifactRef 协议
- `quality_summary` 与 `director_output` 已从 Graph State 移除
- 文本 Sub-Agent 输入只接受 ref，不接受完整原文摘要

预计代码量：

- `1100 ~ 1700` 行

***

#### 任务 P6-04：统一 Mode B 闭环与生产级持久化

当前为什么做：

- 当前系统仍存在“图内文本回审链”和“Worker 异步汇报链”两套协议，无法称为统一生产闭环。

上一步输入：

- 任务 P6-03 已完成统一产物协议与纯引用态

本步实现：

1. 重写 `DirectorReportService`，让以下任务统一进入同一 Mode B 协议：
   - `analyze_audio`
   - `generate_brief`
   - `generate_narrative`
   - `generate_shot_plan`
   - `generate_storyboard`
   - `generate_clips`
   - `generate_timeline`
   - `generate_character_ref`
   - `generate_scene_ref`
2. 统一任务完成事件结构，不再区分“图内回环专用 trigger”和“Worker 专用 trigger”。
3. 固化 Mode B 流程：
   - 读 Artifact
   - Director 审核
   - 生成三段式汇报
   - 创建 PendingDecision
   - assistant\_message 落库
   - SSE 推送
4. 将主图 checkpointer 从内存态迁移到可恢复的持久化实现，优先接入 `AsyncPostgresSaver`。
5. 保证系统重启后，Director 的对话状态、待决策状态和汇报链路均可恢复。

产出结果：

- 所有阶段完成后的反馈都走统一 Mode B 闭环
- 对话持久化从开发态升级到生产态
- 汇报、决策、SSE 三方状态一致

下一个使用者：

- 任务 P6-05

目录与文件：

- `backend/app/services/director_report_service.py`
- `backend/app/tasks/worker.py`
- `backend/app/workflows/main_graph.py`
- `backend/app/agents/director_agent.py`
- 持久化 checkpointer 相关配置与接入代码

验收标准：

- 每个阶段完成后只产生一条主 Director 汇报消息
- 每次确认只创建一个 open decision
- SSE、对话历史、决策状态三者一致
- checkpointer 不再是 `MemorySaver`

预计代码量：

- `900 ~ 1400` 行

***

#### 任务 P6-05：全链路回归与无已知 bug 验收

当前为什么做：

- 偏差 6 的关闭条件不是“代码结构接近”，而是“达到生产级闭环且无已知 bug”。

上一步输入：

- 任务 P6-01 \~ P6-04 已完成

本步实现：

1. 建立分层验证体系：
   - Director dispatch 单测
   - ArtifactRef 协议单测
   - Mode B 汇报 / create\_decision 集成测试
   - 主流程联调测试
2. 重点覆盖 6 条关键链路：
   - audio → style decision
   - brief → confirm\_brief
   - narrative → confirm\_narrative
   - visual → confirm\_visual\_bible
   - shot\_plan → confirm\_shot\_plan
   - storyboard → clips → timeline
3. 对每条链路验证：
   - 状态推进正确
   - ArtifactRef 可读
   - Director 汇报不丢失
   - decision 不重复创建
   - SSE 推送正常
4. 对失败链路直接修复，不把已知缺陷留到最终汇报。

产出结果：

- 偏差 6 的关闭有自动化和联调证据支撑
- “无已知 bug”有可追溯依据，而不是主观判断

下一个使用者：

- docs/09 对应执行记录更新
- 偏差 6 正式关闭

目录与文件：

- `backend/tests/**`
- 必要的测试夹具、联调脚本、mock 与回归用例

验收标准：

- `compileall` / 目标测试集 / 关键联调脚本全部通过
- 至少一条文本主线和一条媒体主线完成端到端验证
- 不存在重复 decision、汇报丢失、状态错乱、ArtifactRef 失效等已知问题

预计代码量：

- `600 ~ 1000` 行

***

### A.5 执行顺序与批次依赖

本轮终态收口的严格顺序如下：

```text
P6-01 收回运行时调度权
-> P6-02 主图去 workflow 主导化
-> P6-03 统一 ArtifactRef 协议与纯引用态
-> P6-04 统一 Mode B 闭环与生产级持久化
-> P6-05 全链路回归与无已知 bug 验收
```

依赖关系说明：

1. 不先做 P6-01，就无法让 Director 真正成为唯一调度中枢。
2. 不先做 P6-02，就会继续保留“Director 调度”和“主图路由”双中枢并存。
3. 不先做 P6-03，Mode B 审核就无法建立统一产物协议。
4. 不先做 P6-04，就不能验证统一闭环是否真实成立。
5. P6-05 只能在前四步完成后做，否则验证对象仍是过渡态系统。

***

### A.6 风险与注意事项

1. 前端依赖风险\
   当前前端可能依赖 `tool_calls`、`pending_decision_id`、`assistant_message` 的现有耦合方式。\
   在 P6-02 和 P6-04 中必须同步评估兼容性，避免出现后端闭环成立但前端渲染错位。
2. 数据模型风险\
   若 `assets` 表现有 `asset_type` 无法合理承载文本 JSON 产物，P6-03 将涉及 migration。\
   这一点必须在实现前先确认，而不是写到一半再补。
3. 兼容过渡风险\
   旧的 `next_action`、图节点直调和 worker 汇报路径将逐步退出主路径。\
   过渡期间必须明确“主路径”和“兼容路径”，避免双路径同时生效导致重复执行。
4. 验证成本风险\
   “没 bug”不是语言承诺，而是验证结果。\
   若 P6-05 没有形成自动化和联调证据，就不能宣布偏差 6 关闭。

***

### A.7 终态关闭判定

只有当以下条件全部满足时，偏差 6 才能标记为真正完成：

1. Director 已成为唯一调度中枢。
2. 文本主线与视觉主线均由真实 Sub-Agent 执行。
3. 所有关键产物通过统一 ArtifactRef 协议传递。
4. Mode B 汇报、决策、SSE、对话落库形成唯一闭环。
5. Graph State 已清理为纯引用态。
6. 持久化 checkpointer 已替换开发态 `MemorySaver`。
7. 自动化测试、关键集成测试和联调验证全部通过。
8. 不存在已知的重复 decision、汇报丢失、状态错乱、引用失效等问题。

在以上条件满足之前，偏差 6 只能视为“阶段性完成”，不能视为“生产级闭环已完成”。
