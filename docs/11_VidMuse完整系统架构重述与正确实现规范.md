# VidMuse 完整系统架构重述与正确实现规范

> 文档目标：基于对代码的实际分析和用户对系统的完整描述，重新定义多 Agent 系统的完整架构、每一步的 Tool Call 设计、产物资产管理、导演审核机制和回退重生成机制。
>
> 这份文档是对文档 1-6 的**补充和修正**，凡与本文档冲突以本文档为准。
>
> 文档时间：2026-03-31

---

## 1. 系统核心哲学

这个系统本质上不是"一键生成 MV"，而是：

> **一个对话式多 Agent 导演工作台**
> 用户和主模型（导演）通过问答式交互，逐阶段确认产物，每一步都有回退，任何产物都可以重生成，最终生成一条完整可交付的 MV 粗剪。

三条设计原则：

1. **对话驱动，阶段确认**：每个阶段产物生成后，必须经过导演 Agent 审核 + 用户确认，确认后才推进，不自动流转
2. **产物版本化，可随时回退**：所有产物都有版本号，回退不删除历史，只切换 active 指针，失效下游
3. **长任务异步化，进度可见**：所有媒体生成（图片/视频）走 Worker 队列，不阻塞 HTTP，通过 Project SSE 推送进度

---

## 1.5 Agent 编排模式：类 Claude Code 的导演-子 Agent 协作架构

> 这是理解整个系统的核心心智模型。在看具体流程之前，必须先建立这个认知框架。

### 1.5.1 整体模式类比

这个系统的 Agent 编排模式，和 Claude Code 的工作方式完全一致：

```
Claude Code 工作方式：
  主 Agent（Claude）
    → 读取全局代码状态
    → 决定下一步任务
    → 主动向用户发问（"我需要确认 X，请问你想要..."）
    → 或直接派发 Sub-Agent / 调用 Tool
    → 等待结果
    → 审核结果（质量/正确性）
    → 向用户报告，给出建议
    → 等用户确认后再继续

VidMuse Director Agent 工作方式（完全相同）：
  Director（主导演模型，多模态）
    → 读取 ProjectSnapshot（全局项目状态）
    → 决定当前阶段该做什么
    → 主动向用户发问（"我理解你的歌是...风格，请问你偏向 A 还是 B？"）
    → 或直接派发 Sub-Agent（NarrativeScriptAgent / VisualDevelopmentAgent 等）
    → 等待 Worker 异步任务完成
    → 用多模态能力审核生成结果（看图，检查一致性）
    → 向用户报告结果，给出推荐，展示产物
    → 等用户确认（PendingDecision）后推进下一阶段
```

**关键点**：Director 自己不直接调用图片生成 API，不直接写 Prompt 生成内容。它是"调度者 + 审核者 + 沟通者"，把具体的生成任务分配给专门的 Sub-Agent 去执行。

---

### 1.5.2 Director 的三态循环

Director Agent 在整个生命周期中，始终处于以下三种等待状态之一：

```
状态 A：等待子 Agent / Worker 异步任务完成
  ↳ 触发条件：已 dispatch 生成任务（图片/视频），正在等 Worker 返回
  ↳ 期间：Director 不阻塞，可以继续处理用户的其他消息
  ↳ 结束条件：SSE 收到 "task.completed" 事件
  ↳ 下一步：进入 状态B（内部审核）

状态 B：Director 内部审核（多模态质检，秒级）
  ↳ 触发条件：Worker 任务完成，Director 拿到生成结果
  ↳ 期间：Director 多模态读图，调用 ConsistencyGuardianAgent，生成审核报告
  ↳ 自动重试：若发现高严重度问题，自动重生成（最多2次），重入 状态A
  ↳ 结束条件：审核通过，或达到重试上限
  ↳ 下一步：进入 状态C（等用户确认）

状态 C：等待用户确认（PendingDecision，阻塞流程推进）
  ↳ 触发条件：Director 审核完毕，向用户展示结果，创建 PendingDecision
  ↳ 期间：项目阶段不推进，但用户可以和 Director 持续对话（调整、追问）
  ↳ 结束条件：用户点击确认 / 在 Chat 里明确说"可以" / 选择某个选项
  ↳ 下一步：进入下一阶段，回到 状态A
```

这三态循环贯穿整个 MV 生产流程的每一个阶段，不是只在某一个环节出现。

---

### 1.5.3 Director 主动发问的行为逻辑

Director 不是"被动响应型"助手，而是"主动推进型"导演。以下是它主动发问的两大场景：

**场景 1：需求澄清阶段（项目开始时）**

Director 拿到用户上传的材料（图片 + 文字 + 音频结构数据）后，**主动**执行以下判断：

```
1. 用户的文字描述是否足够清晰（风格 / 故事意图 / 目标受众）？
   → 不清晰：主动提炼 2 个专业风格方向供用户选择，而不是让用户自己想

2. 上传的图片中是否有角色（人脸）？
   → 有：主动问"这张图中的人是主角还是配角？用于全程出现还是部分场景？"
   → 没有但歌词有人物：主动问"你希望视频中出现什么样的人物形象？"

3. 这首歌更适合什么叙事结构（纯氛围 / 有剧情故事 / 表演为主）？
   → 自动判断，给出 2 个选项让用户确认
```

这里的核心设计原则：**Director 把用户模糊的非专业描述，翻译成专业选项，让用户做选择题而不是填空题。**

**场景 2：阶段推进时的主动复盘**

每个 Sub-Agent 完成任务后，Director **不是直接把结果扔给用户**，而是先自己解读，再主动给出判断：

```
例：VisualDevelopmentAgent 生成了 3 张角色参考图

❌ 错误做法（被动）："角色图已生成，请查看"

✅ 正确做法（主动导演式）：
   "我已为主角生成了 3 版定妆方案。
    版本 1 强调街头感，暗色系，符合副歌情绪；
    版本 2 更干净清新，适合 verse 段的回忆场景；
    版本 3 混合了版本 1 和 2 的元素，但面部特征和你上传的参考图相似度最高。
    我建议选择版本 3 作为主角定妆，并用版本 1 的色调作为副歌镜头的光效参考。
    你是否同意这个方案，或者有其他想法？"
```

Director 的每次输出应包含三个部分：**结果描述 + 个人判断/推荐 + 明确的下一步问题**。

---

### 1.5.4 Sub-Agent 的工作协议

每个 Sub-Agent（子 Agent）遵循相同的工作协议：

```
┌─────────────────────────────────────────────┐
│  Director 向 Sub-Agent 发送任务规格           │
│  包含：项目上下文 + 明确的任务类型 + 输入资产 ID │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│  Sub-Agent 执行任务                           │
│  1. 读取输入资产（角色描述 / 歌词 / style等）  │
│  2. 编写生成 Prompt（模型自己写）              │
│  3. 调用注册的 Tool（API 调用生成模型）        │
│     → ImageGenerationTool                    │
│     → VideoGenerationTool                   │
│     → LipSyncTool                           │
│  4. 等待 API 返回                             │
│  5. 将生成结果保存为 Asset（落库）             │
│  6. 返回结构化结果给 Director                 │
│     → { asset_id, url, metadata }            │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│  Director 接收结果，进入审核（状态 B）         │
└─────────────────────────────────────────────┘
```

**关键原则**：Sub-Agent 只负责生成，不负责和用户沟通。所有和用户的交互，统一由 Director 完成。Sub-Agent 不感知用户的存在，它只和 Director 对话。

---

### 1.5.5 为什么这个模式比"单 Agent + 多工具"更合适

这套多 Agent 架构和 Claude Code 的 agent team 模式相比单 Agent 的优势：

| 维度 | 单 Agent + 工具 | Director + Sub-Agent Team |
|---|---|---|
| Prompt 复杂度 | 一个 Agent 要懂所有任务，Prompt 极长 | 每个 Agent 只关注自己的领域，Prompt 精准 |
| 任务质量 | 专业度不足，什么都懂但什么都不精 | 每个 Sub-Agent 是该领域专家 |
| 可扩展性 | 加新能力 = 改所有 Prompt | 加新 Sub-Agent 不影响其他 Agent |
| 审核机制 | 无法自我审核 | Director 作为独立审核层，天然解耦 |
| 可调试性 | 出问题难以定位 | 每个 Agent 独立可观测、可单独调试 |

**和 Claude Code 的本质相同点**：都是"主模型负责理解意图和调度，子模型/子进程负责具体执行，主模型审核结果，主模型和用户沟通"。

---

## 2. 用户视角的完整交互流程

```
用户操作序列                           系统内部动作
─────────────────────────────────────────────────────────
进入首页，填写创作信息                 → 创建 Project
 · 上传音频文件                        → Asset(audio_original) 存储
 · 上传角色/场景参考图（可选）          → Asset(image_reference) 存储
 · 输入一句创意文字描述                → project_spec.user_prompt
 · 选择时长/比例                       → project_spec.output_config
                                       → 状态推进: created → input_ready

进入工作台，导演 Agent 开始工作        ↓
                                       → 音频分析（后台异步）
                                       → 导演拿到：图片 + 文字 + 音频结构数据
─────────────────────────────────────────────────────────
阶段 0: 理解与澄清
用户：看到导演对上传内容的理解摘要，    → Director 多模态读图，解读文字，读音频结构
      以及 2-3 个澄清问题               → 提出缺失字段，给出选项

用户：回答问题，选择风格                → 创建 PendingDecision(select_style_direction)
      例如：赛博夜景 + 快节奏 + 情绪MV → 用户选择后记录 selected_option_id

─────────────────────────────────────────────────────────
阶段 1: 音频分析完成
（已自动进行，导演展示结果）             → AudioAnalysisVersion 存储
导演展示：BPM/段落/歌词时间轴           → quality_summary 给用户看
用户：确认音频分析，或要求重新分析      → 决策记录

─────────────────────────────────────────────────────────
阶段 2: 创意方案与叙事剧本
导演派发 CreativePlanningAgent          → generate_brief_and_style()
用户收到：Brief + Style Bible 摘要      → 创建 PendingDecision(confirm_brief)
用户：确认/要求调整                     → selected 后继续

导演派发 NarrativeScriptAgent（新）    → generate_narrative_script()
用户收到：完整 MV 叙事剧本摘要          → 角色×场景×段落映射
 · 哪些角色在哪些段落出现
 · 每段歌词对应什么故事情节
 · 情绪弧线规划
用户：确认/调整叙事                     → 创建 PendingDecision(confirm_narrative)

─────────────────────────────────────────────────────────
阶段 3: 视觉圣经 —— 角色 & 场景图生成（当前最大缺失）
导演派发 VisualDevelopmentAgent（新）

 子阶段 3a - 角色参考图：
   对每个角色：
     用户有上传原图 → image-to-image 转换    → Asset(character_reference)
     用户没有原图   → text-to-image 生成     → Asset(character_reference)
   导演展示角色参考图给用户（多模态看图）
   用户：逐个确认/要求重生成/要求调整风格     → PendingDecision(confirm_character_refs)

 子阶段 3b - 场景参考图：
   对每个独立场景：
     text-to-image 生成场景参考图            → Asset(scene_reference)
   导演展示场景参考图给用户
   用户：逐个确认/要求重生成                  → PendingDecision(confirm_scene_refs)

 子阶段 3c - 道具/细节（可选）：
   text-to-image 或 image-to-image           → Asset(prop_reference)

所有确认后 → 形成 VisualBible（固定资产集）  → 状态推进: visual_bible_ready

─────────────────────────────────────────────────────────
阶段 4: 镜头序列规划（绑定视觉资产）
导演派发 CreativePlanningAgent（阶段二）    → generate_shot_plan()
每个 Shot 必须明确写出：
 · start_ms / end_ms（来自音频节拍）
 · lyric_text（对应歌词句）
 · character_ref_asset_id（用哪张定妆图）
 · scene_ref_asset_id（用哪张场地图）
 · camera_language（镜头语言）
 · lipsync_required（是否需要口型）
 · shot_role（表演/叙事/氛围/过渡）

导演展示镜头列表摘要给用户
用户：确认/调整顺序/修改单个镜头        → PendingDecision(confirm_shot_plan)

─────────────────────────────────────────────────────────
阶段 5: 分镜图生成（异步，进度可见）
对每个 Shot → Prompt 编译 → 生成分镜帧
 · 主要用 image-to-image（以角色参考图为基础）
 · 叠加 style_bible 风格约束
 · 叠加 camera_language / emotion
导演 Agent 自动审核生成结果（多模态看图）
 · 检查人物一致性
 · 检查风格一致性
左侧展示：分镜网格（可见每帧）
用户：逐帧确认/要求重生成              → PendingDecision(confirm_storyboard)

─────────────────────────────────────────────────────────
阶段 6: 视频片段生成（异步，进度可见）
对每个 Shot → image-to-video（以分镜帧为起始帧）
 · 非口型镜头: 直接 image-to-video
 · 口型镜头: storyboard_frame → lipsync tool → 合成
导演展示每个 clip 的状态
用户：逐个确认/要求重生成              → PendingDecision(confirm_clips)

─────────────────────────────────────────────────────────
阶段 7: 时间线合成
所有 clip 确认后 → 按节拍顺序拼接
 · ffmpeg 合成
 · 字幕叠加
 · 转场插入
 · 音频对齐
导演展示预览视频
用户：确认 / 调整某个镜头 / 调整顺序

─────────────────────────────────────────────────────────
阶段 8: 导出
用户选择分辨率（720p / 1080p）→ 最终导出文件
```

---

## 3. 项目阶段状态机（修正版）

### 3.1 需要新增的阶段

在现有的 11 个阶段基础上，需要增加 2 个：

```python
# 现有阶段（已实现）
created → input_ready → audio_analyzed → brief_ready →
shot_plan_ready → storyboard_ready → clips_ready →
timeline_ready → export_ready → completed

# 需要在 brief_ready 和 shot_plan_ready 之间插入：
brief_ready → narrative_ready → visual_bible_ready → shot_plan_ready
```

### 3.2 新增阶段定义

**`narrative_ready`**
- 条件：叙事剧本（NarrativeScript）已生成并被用户确认
- 允许动作：生成角色/场景参考图，修改叙事

**`visual_bible_ready`**
- 条件：所有角色参考图 + 场景参考图已被用户逐一确认，视觉圣经固化
- 允许动作：生成 shot plan，修改某个角色图/场景图（会触发 stale）

### 3.3 修正后的失效规则（StaleScope 补充）

| 修改操作 | 失效范围 | 项目回退到 |
|---|---|---|
| 修改音频区间 | shot_plan + storyboard + clips + timeline 全部失效 | input_ready |
| 修改全局风格 | storyboard + clips + timeline 失效 | visual_bible_ready |
| 修改角色参考图 | 使用该角色的所有 storyboard_frame + clip 失效 | visual_bible_ready |
| 修改场景参考图 | 使用该场景的所有 storyboard_frame + clip 失效 | visual_bible_ready |
| 修改叙事剧本 | shot_plan + storyboard + clips + timeline 失效 | narrative_ready |
| 修改全局 brief | shot_plan + storyboard + clips + timeline 失效 | brief_ready |
| 修改单个 shot 规格 | 该 shot 的 storyboard_frame + clip 失效 | shot_plan_ready |
| 修改单个 storyboard 帧 | 该 shot 的 clip 失效 | storyboard_ready |

---

## 4. 资产类型完整定义（Asset Type 补充）

### 4.1 当前已有的资产类型

```
audio_original     用户上传原始音频
audio_trimmed      按时间区间裁切后的音频
image_reference    用户上传的原始参考图（未处理）
style_reference    风格参考图
storyboard_frame   分镜帧图片（AI 文生图）
clip_video         视频片段
export_video       导出成片
subtitle_file      字幕文件
thumbnail          封面图
```

### 4.2 需要新增的资产类型

```
character_reference   角色定妆图（基于用户 image_reference 做 img2img 生成）
                      · 每个角色一张或多张
                      · 有版本号，用户不满意可重生成
                      · 是后续 storyboard_frame 的 reference_image

scene_reference       场景参考图（text2img 生成，定义每个场景的视觉风格）
                      · 每个独立场景一张或多张
                      · 有版本号，用户不满意可重生成
                      · 是后续 storyboard_frame 的 scene reference

prop_reference        道具/细节参考图（可选）
                      · 特殊服装、标志性道具等

narrative_script      叙事剧本文档（JSON 格式存储，不是图片）
                      · 版本化，可回退
                      · asset_type 为文本型资产
```

### 4.3 资产元数据规范（metadata_ 字段）

每个 Asset 的 `metadata_` JSONB 字段应记录：

```json
// 对于 character_reference 类型
{
  "character_id": "char_001",
  "character_name": "主角",
  "generation_mode": "image_to_image",
  "source_asset_id": "原始 image_reference 的 asset_id",
  "style_prompt": "用于生成的风格提示词",
  "provider": "flux_dev",
  "version_no": 1,
  "user_confirmed": true
}

// 对于 scene_reference 类型
{
  "scene_id": "scene_verse",
  "scene_name": "雨夜街头",
  "generation_mode": "text_to_image",
  "prompt_used": "完整 prompt 字符串",
  "provider": "flux_schnell",
  "version_no": 2,
  "user_confirmed": false
}

// 对于 storyboard_frame 类型（补充 reference 绑定信息）
{
  "shot_id": "shot_007",
  "shot_index": 7,
  "character_ref_asset_id": "asset_char_001_v2",
  "scene_ref_asset_id": "asset_scene_verse_v1",
  "prompt_bundle_id": "bundle_xxx",
  "generation_mode": "image_to_image",
  "provider": "flux_dev"
}
```

### 4.4 VisualBible（视觉圣经）结构

VisualBible 不是一张资产，而是一个版本化的映射表，存在 `character_set_versions` 表中：

```json
{
  "version_no": 1,
  "characters": [
    {
      "character_id": "char_001",
      "character_name": "主角女生",
      "description": "20岁左右女性，短发，红色大衣",
      "reference_asset_ids": ["asset_char_001_v2"],
      "active_reference_asset_id": "asset_char_001_v2"
    }
  ],
  "scenes": [
    {
      "scene_id": "scene_verse",
      "scene_name": "雨夜街头",
      "description": "湿漉漉的城市街道，霓虹灯倒影",
      "reference_asset_ids": ["asset_scene_verse_v1"],
      "active_reference_asset_id": "asset_scene_verse_v1"
    }
  ],
  "confirmed_at": "2026-03-31T10:00:00Z"
}
```

---

## 5. 多 Agent 职责划分（完整版）

### 5.1 导演 Agent（Director Agent）

**当前状态**：✅ 已实现，但有关键缺陷

**问题**：Director Agent 当前是纯文本模型，看不到图片。

**正确实现**：Director 必须是多模态模型，在以下场景需要"看图"：
- 用户上传参考图时（理解角色长相、场景风格）
- 角色参考图生成后（审核一致性）
- 场景参考图生成后（审核符合创意）
- 分镜图生成后（审核镜头是否符合规划）

**Director 的多模态消息构造**：
```python
# 当项目有 image_reference 类型资产时，Director 消息应包含图片
messages = [
    SystemMessage(content=system_prompt),
    HumanMessage(content=[
        {"type": "text", "text": user_message},
        # 附加用户上传的参考图
        {"type": "image_url", "image_url": {"url": character_image_url}},
        {"type": "image_url", "image_url": {"url": scene_image_url}},
    ])
]
```

**需要新增的 DirectorInput 字段（GraphState）**：
```python
reference_images: list[dict]    # [{asset_id, url, asset_type, description}]
character_refs: list[dict]      # 已生成的角色参考图
scene_refs: list[dict]          # 已生成的场景参考图
narrative_script: dict | None   # 当前叙事剧本摘要
visual_bible_confirmed: bool    # 视觉圣经是否已被确认
```

---

### 5.2 音乐分析 Agent（AudioAnalysisAgent）

**当前状态**：✅ 已实现，职责正确

职责不变：解读 librosa/WhisperX 原始数据 → 输出创作可用的结构化摘要。

---

### 5.3 创意规划 Agent（CreativePlanningAgent）

**当前状态**：⚠️ 存在但范围偏窄

**问题**：
- Phase-1 生成 brief/style 是对的
- Phase-2 生成 shot_plan，但没有叙事剧本层，也没有与视觉资产的绑定

**正确实现 - Phase 分拆**：

**Phase-1（当前已有）**：生成 creative_brief + style_bible

**Phase-2（新增）**：接收 NarrativeScript 输入，生成 shot_plan（绑定视觉资产）
```python
# 输入增加
narrative_script: dict          # 叙事剧本（阶段2新产物）
visual_bible: dict              # 角色/场景映射表（阶段3新产物）

# 输出 ShotSemanticSpec 必须包含
character_ref_asset_id: str     # 明确指向某个角色参考图
scene_ref_asset_id: str         # 明确指向某个场景参考图
```

---

### 5.4 叙事剧本 Agent（NarrativeScriptAgent）【新增】

**当前状态**：❌ 完全缺失，需要新建

**职责**：
- 输入：audio_analysis（段落/歌词） + creative_brief + style_bible + user_prompt
- 输出：完整的 MV 叙事剧本

**输出结构**：
```json
{
  "story_arc": "一个女孩在雨夜城市里独自游荡，经历情绪崩溃到重新燃起希望的故事",
  "characters": [
    {"id": "char_001", "name": "主角", "description": "20岁短发女生，疲惫又倔强"},
    {"id": "char_002", "name": "路人甲", "description": "模糊的过客，无需定妆"}
  ],
  "scenes": [
    {"id": "scene_verse", "name": "雨夜街头", "description": "湿漉漉的城市，霓虹倒影"},
    {"id": "scene_chorus", "name": "天台", "description": "高处俯瞰城市，狂风大雨"},
    {"id": "scene_bridge", "name": "便利店内", "description": "温暖荧光灯，短暂避雨"}
  ],
  "section_mapping": [
    {
      "section_type": "verse",
      "lyrics": "...",
      "scene_id": "scene_verse",
      "characters": ["char_001"],
      "emotion": "low-energy melancholy",
      "narrative_beat": "主角独自在雨中行走，回忆过去"
    },
    {
      "section_type": "chorus",
      "lyrics": "...",
      "scene_id": "scene_chorus",
      "characters": ["char_001"],
      "emotion": "high-energy catharsis",
      "narrative_beat": "情绪爆发，站在天台对着城市大喊"
    }
  ]
}
```

---

### 5.5 视觉开发 Agent（VisualDevelopmentAgent）【新增】

**当前状态**：❌ 完全缺失，需要新建

**职责**：这是整个系统最关键的缺失 Agent

阶段 3a — 角色参考图生成：
- 输入：NarrativeScript 的 characters[] + user 上传的 image_reference + style_bible
- 操作：
  - 若用户有上传对应角色图 → 调用 `ImageGenerationTool(mode=image_to_image)`
  - 若用户没有上传 → 调用 `ImageGenerationTool(mode=text_to_image)` 生成
- 输出：`Asset(asset_type=character_reference)`
- 与导演协作：导演看图审核后呈现给用户

阶段 3b — 场景参考图生成：
- 输入：NarrativeScript 的 scenes[] + style_bible
- 操作：调用 `ImageGenerationTool(mode=text_to_image)`（场景不需要用户参考图）
- 输出：`Asset(asset_type=scene_reference)`

**VisualDevelopmentAgent 提示词设计**：
```
系统 Prompt：
  你是视觉开发专家。
  你的任务是将叙事描述和风格规格转化为可以驱动图片生成工具的提示词。
  对角色参考图：强调角色外貌特征、服装细节、风格一致性。
  对场景参考图：强调环境氛围、色调、光影、镜头感。
  输出结构化 JSON，包含 positive_prompt、negative_prompt、generation_mode、reference_image_id。
```

---

### 5.6 Prompt 编译服务（PromptCompilerService）

**当前状态**：✅ 已实现，需要增强

**增强点**：编译 storyboard_frame 的 prompt bundle 时，必须加入：
```python
# 当前缺失的输入
character_ref_asset_id: str   # 角色参考图的 asset_id
scene_ref_asset_id: str       # 场景参考图的 asset_id

# 当前缺失的输出字段
reference_image_url: str      # 给 image-to-image 工具用的起始帧 URL
reference_weight: float       # IP-Adapter 权重或图片参考强度（0.0-1.0）
```

---

### 5.7 其余 Agent/Service

| 名称 | 状态 | 说明 |
|---|---|---|
| ConsistencyGuardianAgent | ✅ 已实现 | 正确，审核完后主导演需读取并展示给用户 |
| LipSyncService | ✅ 已实现 | 正确，口型镜头需要 character_reference 作为人脸输入 |
| TimelineComposerService | ✅ 已实现 | 正确，需要走 Worker 队列 |
| ExportService | ✅ 已实现 | 正确 |

---

## 6. 完整 Tool Call 设计

### 6.1 导演 Agent 的工具白名单（完整版）

所有工具分三类：**即时同步工具**、**后台异步工具**、**决策控制工具**。

```python
# ─────────────────────────────────────────
# 类型 A：即时工具（图执行时同步调用，秒级完成）
# ─────────────────────────────────────────

"analyze_audio"
  入参: project_id
  出参: audio_analysis_id（落库后的版本 ID）
  耗时: 5-30 秒（已异步化）

"generate_narrative_script"
  入参: project_id（读取 brief + audio_analysis + user_prompt）
  出参: narrative_script_id
  耗时: LLM 调用，10-20 秒

"generate_brief"
  入参: project_id, style_direction
  出参: brief_version_id
  耗时: LLM 调用，10-20 秒

"generate_shot_plan"
  入参: project_id（读取 brief + narrative + visual_bible + audio_analysis）
  出参: shot_plan_version_id
  耗时: LLM 调用，15-30 秒

# ─────────────────────────────────────────
# 类型 B：后台异步工具（放入 Worker 队列，分钟级完成）
# ─────────────────────────────────────────

"generate_character_reference"
  入参: project_id, character_id, generation_mode("img2img"|"txt2img"),
        source_image_url(optional), prompt_overrides(optional)
  出参: tool_job_id（异步任务 ID，前端通过 SSE 监听进度）
  耗时: 图片生成 10-60 秒/张

"generate_scene_reference"
  入参: project_id, scene_id, generation_mode="txt2img",
        prompt_overrides(optional)
  出参: tool_job_id
  耗时: 图片生成 10-60 秒/张

"generate_storyboard"
  入参: project_id（批量处理所有 shot）
  出参: tool_job_id（批量任务）
  耗时: 图片生成，N 个 shot × 30秒，可并发

"generate_video_clips"
  入参: project_id, shot_ids(optional 指定部分)
  出参: tool_job_id
  耗时: 视频生成，N 个 shot × 5-15分钟，可并发

"generate_lipsync_clip"
  入参: project_id, shot_id
  出参: tool_job_id
  耗时: 1-5 分钟/镜头

"compose_timeline"
  入参: project_id
  出参: tool_job_id
  耗时: ffmpeg，1-5 分钟

# ─────────────────────────────────────────
# 类型 C：决策控制工具（创建 PendingDecision，暂停等用户）
# ─────────────────────────────────────────

"request_style_decision"
  功能: 展示 2-3 个风格选项，等用户选择
  创建: PendingDecision(type=select_style_direction)

"request_confirmation"
  入参: confirmation_type, items_to_review(资产列表)
  可用 type:
    confirm_narrative      确认叙事剧本
    confirm_character_refs 确认角色参考图（含图片审核）
    confirm_scene_refs     确认场景参考图
    confirm_shot_plan      确认镜头计划
    confirm_storyboard     确认分镜图
    confirm_clips          确认视频片段（高成本，需显示预计费用）

# ─────────────────────────────────────────
# 类型 D：修改/回退工具
# ─────────────────────────────────────────

"regenerate_asset"
  入参: project_id, asset_id, patch(可选覆盖参数)
  功能: 重新生成单个资产（不影响其他资产，除非触发 stale 规则）
  出参: tool_job_id

"rollback_version"
  入参: project_id, item_type, item_id, target_version_no
  功能: 回退到历史版本，触发失效规则
  出参: stale_items[]（被标记 stale 的下游 ID 列表）

"patch_shot"
  入参: project_id, shot_id, patch
  功能: 修改单个 shot 的语义规格，触发该 shot 的 storyboard + clip stale

"patch_character"
  入参: project_id, character_id, patch（修改角色描述或参考图）
  功能: 更新角色定义，重新生成该角色的参考图，触发使用该角色的 storyboard/clip stale
```

---

## 7. 导演审核机制（Director Review Protocol）

导演 Agent 在每个阶段执行结束后，**不是直接把结果丢给用户**，而是先自己读取结果，做质量检查，再用清晰的语言展示给用户。

### 7.1 音频分析审核

```
Director 读取: AudioAnalysisVersion.quality_summary
Director 展示:
  "已分析完成，这首歌 BPM 124，共 4 段（intro 8s / verse 16s / chorus 16s / outro 8s）
   能量高峰在 24.5s 处（副歌入口）
   识别到 [X] 句歌词，时间轴精度良好。
   是否需要调整分析区间，或者直接开始创意规划？"
```

### 7.2 角色参考图审核（多模态关键）

```
Director 输入: [角色参考图 URL × N] + [用户原始上传图 URL × M]
Director 执行:
  1. 调用多模态 LLM，对比生成图和原始图的一致性
  2. 检查风格是否与 style_bible 一致
  3. 生成审核报告
Director 展示（携带图片给前端）:
  {
    "message": "已为主角生成 3 版定妆图，风格已与电影感胶片风格对齐。
                第 2 版的光影效果最佳，建议采用。
                请查看并选择你满意的版本。",
    "options": [
      {"id": "char_ref_v1", "title": "版本 1", "asset_url": "..."},
      {"id": "char_ref_v2", "title": "版本 2（推荐）", "asset_url": "..."},
      {"id": "char_ref_v3", "title": "版本 3", "asset_url": "..."}
    ],
    "next_action": "request_confirmation",
    "confirmation_type": "confirm_character_refs"
  }
```

### 7.3 分镜审核

```
Director 输入: 所有 storyboard_frame 图片（批量多模态）
Director 检查:
  1. 调用 ConsistencyGuardianAgent.run() 获取 issues 列表
  2. 如果有高严重度问题，先自动重生成相关帧（最多重试 2 次）
  3. 仍有问题的，提交给用户确认

Director 展示:
  "分镜图已全部生成。质检发现 2 个问题：
   · Shot 3 的人物服装与定妆图不一致（已自动重生成）
   · Shot 7 的背景色调偏暖，与赛博夜景风格有偏差（需您确认是否修改）
   请在左侧查看完整分镜图，确认后开始生成视频片段。"
```

---

## 8. 回退与重生成机制（Rollback & Regeneration）

### 8.1 回退的两种模式

**模式 A：版本回退（已实现）**
- 切换 active 版本指针
- 触发下游 stale 标记
- 不删除历史版本
- 前端通过 `versions_router` API 操作

**模式 B：对话式修改（通过 Director）**
- 用户在 Chat 说："这个角色图颜色太暗，重新生成"
- Director 解析 intent = `regenerate_asset`
- 构造 patch（color_tone 调整）
- 调用 `generate_character_reference`（带 patch 参数）
- 新资产生成后，Director 呈现对比
- 下游 stale 传播

### 8.2 单镜头回退流程（对话驱动）

```
用户说: "第 5 个镜头不对，女主角脸太模糊"

Director 解析:
  intent: regenerate_storyboard_frame
  target: shot_id = "shot_005"
  patch: {"prompt_override": "closer face shot, sharp focus on character"}

执行流程:
  1. PromptCompilerService 用 patch 重新编译 PromptBundle
  2. 投入 Worker 队列（ImageGenerationTool）
  3. 生成新 storyboard_frame（新 Asset，新 version）
  4. shot_005.status = "storyboard_ready"（clip 标记 stale）
  5. Director 展示新帧：
     "已重新生成第 5 个镜头的分镜图，人物面部更清晰。
      对应的视频片段已标记为需重新生成，确认后会自动更新。"

stale 传播:
  shot_005.clip_version.is_active → false（stale）
  timeline_segment for shot_005 → stale
  整体项目 timeline 状态 → stale（不是 export_ready 了）
```

### 8.3 角色修改的 stale 传播链

```
用户: "主角的头发改成金色"

Director 解析:
  intent: patch_character
  target: character_id = "char_001"
  patch: {"hair_color": "golden", "hair_style": "short golden"}

执行流程:
  1. 更新 NarrativeScript 中 char_001 的 description
  2. 重新生成 character_reference（投入 Worker）
  3. 新 character_reference 生成后触发 stale：
     → 所有 shot.character_ref_asset_id == char_001_old 的 storyboard_frame → stale
     → 这些 shot 的 clip_version → stale
     → timeline_segment for these shots → stale
  4. Director 通知用户:
     "主角头发已更新为金色。共影响 8 个镜头的分镜图和视频片段需要重新生成。
      是否现在全部重新生成（预计消耗 X credits）？或者逐个确认？"
```

---

## 9. 异步任务架构（Worker Queue）

### 9.1 当前问题

所有媒体生成（storyboard/clips/timeline）在 LangGraph 图里**同步**执行，HTTP 必然超时。

### 9.2 正确架构

```
LangGraph 图节点（只做派发，不等结果）
  ↓
TaskDispatcher → Redis 队列
  ↓
TaskWorker（后台进程）→ 实际执行媒体生成 → 更新 DB
  ↓
OutboxPublisher → Redis pub-sub
  ↓
Project SSE → 前端实时感知进度
```

### 9.3 节点修改规范

每个媒体生成节点的正确写法：

```python
# 错误写法（当前实现，同步阻塞）
async def storyboard_node(state):
    await storyboard_service.generate_and_save(project_id)  # 阻塞 5 分钟
    return {"assistant_message": "分镜生成完成"}

# 正确写法（应该改成）
async def storyboard_node(state):
    # 只派发，立即返回
    job_id = await task_dispatcher.dispatch(
        task_type="generate_storyboard",
        project_id=project_id,
        idempotency_key=f"storyboard:{project_id}:{active_shot_plan_version}"
    )
    # 不等结果，直接告诉用户"在路上了"
    return {
        "assistant_message": "分镜图生成任务已提交，通常需要 2-5 分钟。"
                             "完成后会在左侧实时展示，请稍等。",
        "pending_job_id": job_id
    }

# Worker 执行完成后，通过 SSE 推送：
# {"event": "storyboard.generated", "data": {"shot_id": "...", "frame_url": "..."}}
# {"event": "project.stage.changed", "data": {"new_stage": "storyboard_ready"}}
# 前端收到 storyboard_ready → 展示确认卡
```

### 9.4 长任务的进度 SSE 事件设计

```json
// 单帧完成
{"event": "storyboard.frame.generated", "data": {"shot_id": "shot_005", "frame_url": "..."}}

// 批量进度
{"event": "storyboard.progress", "data": {"completed": 5, "total": 12}}

// 全部完成
{"event": "project.stage.changed", "data": {"new_stage": "storyboard_ready"}}

// 单个 clip 完成
{"event": "clip.generated", "data": {"shot_id": "shot_005", "clip_url": "..."}}

// clip 批量进度
{"event": "clips.progress", "data": {"completed": 3, "total": 12}}

// 角色参考图完成（触发导演审核）
{"event": "character_reference.generated", "data": {"character_id": "char_001", "asset_id": "...", "url": "..."}}
```

---

## 10. 项目记忆（ProjectSnapshot）增强

### 10.1 需要在 ProjectSnapshot 中增加的字段

```python
class ProjectSnapshot(BaseModel):
    # 现有字段...
    project_id: str
    current_stage: str
    active_versions: ActiveVersions
    
    # 新增字段
    narrative_script_id: str | None = None     # active 叙事剧本 ID
    visual_bible_version_id: str | None = None # active 视觉圣经 ID
    character_refs: list[CharacterRef] = []    # 各角色的 active 参考图
    scene_refs: list[SceneRef] = []            # 各场景的 active 参考图
    narrative_confirmed: bool = False          # 叙事是否已确认
    visual_bible_confirmed: bool = False       # 视觉圣经是否已确认

class CharacterRef(BaseModel):
    character_id: str
    character_name: str
    active_asset_id: str | None = None
    asset_url: str | None = None

class SceneRef(BaseModel):
    scene_id: str
    scene_name: str
    active_asset_id: str | None = None
    asset_url: str | None = None
```

---

## 11. 前端工作台的信息展示逻辑

### 11.1 左侧 Pipeline 节点（修正版）

在原有 9 个节点基础上，需要增加：

```
1. 输入          ← 已有
2. 音频分析      ← 已有
3. 创意方案      ← 已有（brief + style）
4. 叙事剧本      ← 新增（NarrativeScript）
5. 视觉圣经      ← 新增（角色/场景参考图确认）
6. 镜头计划      ← 已有（但需加资产绑定展示）
7. 分镜图        ← 已有
8. 视频片段      ← 已有
9. 时间线        ← 已有
10. 导出         ← 已有
```

### 11.2 中间工作区 - 视觉圣经阶段视图（新增）

需要展示：
- 角色卡片列表（每个角色展示其 active 参考图）
- 场景卡片列表（每个场景展示其 active 参考图）
- 版本历史（每个角色/场景的历史参考图版本）

操作：
- 点击某个角色/场景 → 展示版本对比
- "重新生成"按钮 → 触发重生成流程
- "确认全部"按钮 → 触发 confirm_character_refs + confirm_scene_refs

---

## 12. 当前代码与正确实现的对照表

| 模块 | 当前状态 | 需要的修改 | 优先级 |
|---|---|---|---|
| Director Agent 多模态 | ❌ 纯文字 | 添加 image_url 到消息构造 | P0 |
| NarrativeScriptAgent | ❌ 不存在 | 新建 agent + prompt + DB 表 | P0 |
| VisualDevelopmentAgent | ❌ 不存在 | 新建 agent（最复杂） | P0 |
| ProjectStage 新增 2 个 | ❌ 不存在 | narrative_ready + visual_bible_ready | P0 |
| Asset 新类型 | ❌ 缺 3 种 | character_reference + scene_reference + prop_reference | P0 |
| character_set_versions | ⚠️ 有表无数据 | 完善 VisualBible 结构和 ORM | P0 |
| ShotSemanticSpec 绑定 | ⚠️ 有字段但不用 | reference_asset_ids 正确填充 | P1 |
| PromptCompiler 增强 | ⚠️ 有但不完整 | 加入 character_ref + scene_ref URL | P1 |
| StoryboardService img2img | ❌ 只有 txt2img | 支持 image_to_image 模式 | P1 |
| 长任务异步化 | ❌ 同步阻塞 | 所有生成节点改为 dispatch → Worker | P1 |
| SSE 进度推送 | ⚠️ 有基础 | 补充生成进度事件类型 | P1 |
| LipSync 用 character_ref | ⚠️ 用 storyboard 帧 | 改为用 character_reference 作为人脸输入 | P2 |
| 音频剪段传给 lipsync | ⚠️ 用整段音频 | 按 shot 时间窗口准确切段 | P2 |
| 导演自动审核（多模态） | ❌ 不存在 | Director 在每阶段读图，调 Consistency Guardian | P2 |
| Director 双模式区分 | ❌ 只有被动响应 | 拆分 Mode A（对话）和 Mode B（派发+审核） | P1 |
| Worker 完成→Director 汇报 | ❌ 完全缺失 | Worker succeed 后自动写入 assistant message | P0 |
| 资产不变性 Enforce | ⚠️ 方向对但未强制 | AssetService 层拒绝 update，只允许新建版本 | P1 |
| 高成本前置费用展示 | ❌ CostEstimationService 有但 Director 未用 | clip/lipsync/export 类动作必须先展示 breakdown | P1 |
| Director 三段式汇报协议 | ❌ 各节点返回硬编码文案 | 所有汇报统一为：结果描述+判断/推荐+下一步问题 | P1 |

---

## 13. 正确的开发执行顺序

基于当前代码基础，下一批开发的正确顺序：

**批次 1（P0 核心缺失，约 1500-2000 行）**
1. 新增 asset_type：character_reference / scene_reference / prop_reference
2. 新增 ProjectStage：narrative_ready / visual_bible_ready
3. 完善 character_set_versions 表结构（VisualBible）
4. NarrativeScriptAgent + 对应 prompt 模板
5. 对应 DB 模型和 API（narrative_script_versions 表）

**批次 2（P0 核心，约 1500 行）**
1. VisualDevelopmentAgent（角色/场景图生成，最核心）
2. ImageGenerationTool 新增 image_to_image 模式（基于 Fal.ai IP-Adapter）
3. VisualBibleService（角色/场景版本管理）
4. Director Agent 多模态消息构造（在 director_agent.py 加 image_url）

**批次 3（P1 重要，约 1000 行）**
1. 长任务异步化（storyboard_node / clip_node / timeline_node 改为 dispatch）
2. ShotPlanPersistenceService 绑定 visual_bible 资产
3. PromptCompilerService 支持 character_ref + scene_ref image URL
4. StoryboardService 支持 image_to_image 模式

**批次 4（P0/P1 主动导演行为层，约 800-1200 行）**
1. Worker 完成 → 自动触发 Director 汇报（`DirectorReportService` + `succeed_job` 钩子）
2. Director 双模式区分（`mode_a_conversation` / `mode_b_report` 在 prompt + 路由层显式化）
3. 高成本动作费用前置（`CostGateService`，clip/lipsync/export 强制走 estimate → confirm → dispatch）
4. AssetService 不变性 enforce（禁止 update_asset，只允许 create_new_version）
5. Director prompt 三段式汇报协议（结果描述 + 判断推荐 + 下一步问题）

---

## 14. 关键设计决策记录

### D1. 为什么 visual_bible 阶段是独立阶段

角色参考图是所有 storyboard 和 clip 的视觉锚点。如果不固化，生成的所有内容角色一致性无法保证。

这一步必须让用户逐一确认，因为：
- 用户的审美标准只有用户自己知道
- 一旦后面的镜头都生成了再改角色图，成本极高

### D2. 为什么叙事剧本是独立阶段（不合并进 brief）

Brief 定义"情绪基调和风格方向"，叙事剧本定义"谁在哪里做什么"。

两者职责不同：brief 是美学规格，叙事是内容规格。分开后：
- 用户可以保持相同 brief 但改变故事内容
- 叙事改变只影响下游，不会触发 brief 重生成

### D3. 为什么不直接把用户原图送给 storyboard 生成

用户上传的原图可能：
- 分辨率不统一
- 角度不统一（正脸/侧脸混合）
- 与风格不匹配（现实照片 vs 动漫风格）

必须先做 image-to-image 统一化，生成"定妆照"，才能保证全片人物一致性。

### D4. Director 的多模态审核时机

不是每次 HTTP 请求都做多模态（成本高），而是：
- 角色参考图生成后：必须看图审核
- 分镜图生成后：必须看图审核（抽样）
- 用户质疑某个图时：Director 实时看图

平时的对话：纯文字即可。

---

## 15. 本文档与历史文档的关系

| 文档 | 本文档态度 |
|---|---|
| doc01 §11.1 生成链路 | ✅ 继承，但 "角色/场景参考图" 阶段在本文档中具体化 |
| doc01 §8.1 单 Agent | ❌ 废弃，已被 doc02 的多 Agent 架构取代 |
| doc02 §14.1 多模态 Director | ✅ 继承，本文档提供具体实现方案 |
| doc02 §15.2 链路图 | ⚠️ 修正，原图缺少 narrative + visual_bible 两个阶段 |
| doc06 Agent 职责表 | ✅ 继承，本文档在此基础上新增 2 个 Agent |
| doc04 状态机 | ⚠️ 扩展，新增 2 个中间阶段和更细粒度的 stale 规则 |
| doc09 执行计划 | ⚠️ 需要在本文档基础上补充 batch 1-3 的执行计划 |

---

## 16. 主动导演行为规范（5 大补充）

> 本章是对 §1.5（Agent 编排模式）的实现层补充，聚焦「当前代码缺失的核心行为」，
> 凡与本章冲突，以本章为准。

---

### 16.1 Director 的两种工作模式（Mode A / Mode B）

Director 不是只有一种工作状态，而是两种截然不同的模式交替运行。**当前代码只实现了 Mode A，Mode B 完全缺失。**

**Mode A：理解 + 澄清（对话模式）**
```
触发源：用户发送消息
特征：
  · 用户说话 → Director 读懂意图 → Director 反问 / 给出选项
  · Director 是"对话伙伴"
  · 代价低，可以多轮来回
  · 不触发任何生成任务
典型场景：
  · 项目创建后的需求澄清
  · 用户对某个产物表达不满
  · 用户问"这首歌应该怎么拍"
```

**Mode B：派发 + 审核（汇报模式）**
```
触发源：系统事件（Worker 完成、阶段状态变更）
特征：
  · 系统事件 → Director 被唤醒 → 审核产物 → 主动汇报给用户
  · Director 是"项目经理"
  · 有明确的输出结构：结果描述 + 判断/推荐 + 下一步问题
  · 不需要用户先说话
典型场景：
  · Worker 完成角色参考图生成 → Director 看图审核 → 主动汇报
  · 音频分析完成 → Director 展示分析结果 + 建议风格方向
  · 分镜图全部生成 → Director 质检 + 汇报问题 + 请用户确认
```

**两种模式的区分必须在代码层显式化：**
```python
# 当前缺失的核心逻辑：触发源路由
触发源判断:
  user_message 不为空 AND 无 system_trigger → Mode A（对话）
  system_trigger 存在（task_completed / stage_changed） → Mode B（汇报）

# Mode B 的特殊 prompt 变量
{
  "trigger_type": "task_completed",
  "task_type": "generate_storyboard",
  "task_result": { "frame_count": 12, "issues": [...] },
  "mode": "report"   # 指示 Director 使用汇报格式
}
```

---

### 16.2 Worker 完成 → 系统触发 Director 汇报（最大缺失闭环）

**当前代码链路（有断点）：**
```
Worker.succeed_job()
  → state_transition_service.transition_tool_job(SUCCEEDED)
  → OutboxPublisher.publish(SSE 事件)
  → 前端展示进度
  → ⚠️ 断点：没有任何机制触发 Director 说话
  → 等用户自己发消息
```

**正确链路（补充后）：**
```
Worker.succeed_job()
  → state_transition_service.transition_tool_job(SUCCEEDED)
  → OutboxPublisher.publish(SSE 事件)           ← 维持原有，前端进度展示
  → DirectorReportService.trigger(             ← 新增
      project_id=job.project_id,
      trigger_type="task_completed",
      task_type=job.tool_name,
      task_result=output_payload
    )
  → DirectorAgent.run(mode=B, trigger=...)     ← 以 Mode B 调用 Director
  → 生成 assistant_message（含审核报告）
  → ConversationService.save_assistant_message() ← 写入对话历史
  → OutboxPublisher.publish("director.report") ← 推给前端 Chat 区
```

**实现要点：**
```python
# app/services/director_report_service.py（新建）
class DirectorReportService:
    async def trigger(self, project_id: str, trigger_type: str,
                      task_type: str, task_result: dict) -> None:
        """Worker 完成后触发 Director 自动汇报。"""
        # 1. 加载 ProjectSnapshot（复用 main_graph 里的逻辑）
        snapshot = await self._load_snapshot(project_id)

        # 2. 加载或获取该项目的 active session
        session = await conversation_svc.get_or_create_session(project_id, ...)

        # 3. 构造 Mode B 触发状态
        state = ProjectGraphState(
            project_id=project_id,
            user_message="",          # Mode B 不需要用户消息
            system_trigger={
                "type": trigger_type,
                "task_type": task_type,
                "result": task_result,
            },
            history=await conversation_svc.load_history_for_llm(session["id"]),
            ...snapshot_fields
        )

        # 4. 调用 Director（走 Mode B prompt）
        director_out = await director_agent.run(state)

        # 5. 持久化并推 SSE
        await conversation_svc.save_assistant_message(
            session["id"],
            director_out["message"],
            message_type="director_report",
        )
        await outbox_publisher.publish(
            project_id=project_id,
            event_type="director.report",
            payload={"message": director_out["message"], ...},
        )
```

**受影响的所有任务类型：**
```
task_type                 → Director 报告内容
audio_analysis            → BPM / 段落 / 歌词展示 + 建议风格方向
generate_character_ref    → 角色参考图展示 + 一致性审核 + 推荐版本
generate_scene_ref        → 场景参考图展示 + 氛围评价
generate_storyboard       → 分镜图展示 + 质检问题 + 请确认
generate_clips            → clip 展示 + 口型/动作评价 + 请确认
compose_timeline          → 预览就绪 + 节拍对齐简评 + 请确认导出
```

---

### 16.3 资产不变性原则（Immutability Guarantee）

> **资产一旦生成，永远不修改，只新建版本。**

这不是工程习惯，是产品正确性保证。如果允许覆盖资产，以下功能全部失效：回滚、版本对比、stale 追溯、调试历史。

**不变性规则：**
```
允许：
  · AssetService.create(asset_type, url, metadata)    → 创建新 Asset
  · VersionSwitchService.set_active(asset_id)         → 切换 active 指针
  · asset.metadata_ 写入一次后只读                    → 不允许 patch

禁止（必须在 AssetService 层拒绝）：
  · asset.url 字段修改
  · asset.file_path 字段修改
  · asset.asset_type 修改
  · 任何形式的 UPDATE assets SET url=... 操作
```

**stale 传播与 active 指针的正确流程：**
```
用户不满意角色图 → Director 解析 intent=regenerate_asset
  → VisualDevelopmentAgent 生成新 character_reference（version_no +1）
  → 新 Asset 落库（ID 全新，不覆盖旧 Asset）
  → VersionSwitchService.set_active(new_asset_id)  → 更新 active 指针
  → StaleService.propagate(changed_asset_id)        → 下游 stale
  → 旧 Asset 依然存在，用户随时可以说"换回上一个" → 切回旧指针
```

**代码层 enforce（待实现）：**
```python
# app/services/asset_service.py 中补充
async def update_asset(self, asset_id: str, **kwargs) -> None:
    """禁止调用。资产不允许修改，请使用 create_new_version()。"""
    raise ImmutabilityViolationError(
        f"Asset {asset_id!r} 不允许修改，请创建新版本。"
    )
```

---

### 16.4 高成本 ToolCall 的费用前置门控

每个高成本 ToolCall 派发前，Director **必须**先向用户展示费用明细，等用户确认后才真正 dispatch。

**高成本动作清单：**
```
需要费用前置的动作：
  generate_clips          → 视频生成，每镜 15-30 credits
  generate_lipsync_clip   → 口型生成，每镜 15 credits
  compose_timeline        → 合成，少量
  export_video            → 导出，720p/1080p 不同

不需要费用前置的动作（成本低或 LLM 调用）：
  analyze_audio           → 少量
  generate_narrative      → LLM，免费层
  generate_brief          → LLM，免费层
  generate_shot_plan      → LLM，免费层
  generate_storyboard     → 中等，但已有 confirm_storyboard 门控
```

**前置费用展示格式（Director 汇报内容）：**
```
「即将为 12 个镜头生成视频，预计消耗：
  · 普通镜头 × 10（image-to-video）：10 × 15 = 150 credits
  · 口型镜头 × 2（lipsync）：2 × 15 = 30 credits
  合计：180 credits（约 15 分钟）
  你当前余额：450 credits，生成后剩余：270 credits
  是否继续？」
```

**实现方案 —— CostGateService（新建）：**
```python
# app/services/cost_gate_service.py（新建）
class CostGateService:
    """高成本 ToolCall 的费用前置门控。"""

    GATED_TOOLS = {
        "generate_clips",
        "generate_lipsync_clip",
        "export_video",
    }

    async def estimate_and_request_confirmation(
        self,
        project_id: str,
        tool_name: str,
        tool_params: dict,
    ) -> PendingDecision:
        """估算成本 + 创建 confirm_cost PendingDecision，等用户确认。

        Director 在 dispatch 前调用此方法。
        PendingDecision resolved 后才真正 dispatch。
        """
        breakdown = self._build_breakdown(tool_name, tool_params)
        decision = await decision_service.create(
            project_id=project_id,
            decision_type="confirm_cost",
            options_payload=breakdown,
        )
        return decision

    def _build_breakdown(self, tool_name: str, params: dict) -> dict:
        """根据 tool_name 和参数构造费用明细。"""
        est = CostEstimationService()
        if tool_name == "generate_clips":
            shot_count = params.get("shot_count", 0)
            avg_dur = params.get("avg_duration_sec", 5.0)
            total = est.estimate_clips_batch(shot_count, avg_dur)
            return {"total": total, "breakdown": [{...}]}
        ...
```

---

### 16.5 Director 输出的节奏感规范（三段式汇报协议）

Director 的每次输出 —— **无论是回应用户还是汇报 Worker 结果** —— 都应遵循统一的三段式结构。

**三段式：结果描述 + 判断/推荐 + 下一步问题**

```
段 1：结果描述（发生了什么）
  · 客观陈述已完成的工作和产物
  · 不夸张，不带情绪，准确
  例："音频分析完成。BPM 128，4段结构（intro 8s / verse 16s / chorus 16s / outro 8s），
       副歌能量最强，主唱进入点在 4.2s。"

段 2：判断 / 推荐（Director 的主观意见）
  · Director 基于专业判断给出建议
  · 不是列出所有可能，而是有倾向地推荐
  · 如果质检发现问题，清晰指出
  例："基于你描述的'雨夜情绪'和副歌的高能量，我建议走'电影感冷蓝'风格方向。
       这个方向与 BPM 128 的节奏切合度高。"

段 3：下一步问题（让用户做决策）
  · 必须是明确的决策邀请，不是开放性聊天
  · 给出 2-3 个选项，或直接问"是否确认"
  · 如果需要费用，在这里说
  例："你希望走：
       A）电影感冷蓝（我的推荐）
       B）暖色调胶片感
       C）先看两个风格的参考图再决定？"
```

**当前问题（代码里的反例）：**
```python
# app/workflows/nodes/storyboard_node.py — 当前硬编码文案
return {
    "assistant_message": (
        f"分镜图已生成完成！共 {frame_count} 张分镜图（版本 v{storyboard_version.version_no}）。\n"
        "你可以在工作台的分镜图区域查看每个镜头的视觉参考。\n"
        "确认满意后，下一步将进入视频 clip 生成阶段。"
    )
}
# 问题：纯状态播报，没有判断，没有主动推荐，没有费用提示
```

**正确实现方式：** 节点本身只返回结构化数据，由 Director（Mode B）负责生成汇报文案
```python
# 节点只返回结构化结果
return {
    "storyboard_result": {
        "frame_count": frame_count,
        "version_no": storyboard_version.version_no,
        "issues": consistency_issues,   # ConsistencyGuardianAgent 输出
        "auto_fixed_count": 1,
    },
    "trigger_director_report": True,  # 标记：需要 Director 生成汇报
}
# Director 接收 storyboard_result → Mode B prompt → 生成三段式汇报
```

**Director Mode B 的 prompt 变量补充：**
```python
# director_agent.py 的 Mode B prompt 需要以下变量
{
    "mode": "report",
    "trigger_type": "task_completed",
    "task_type": "generate_storyboard",
    "task_result": {
        "frame_count": 12,
        "issues": [{"shot_id": "shot_003", "issue": "服装不一致", "severity": "high"}],
        "auto_fixed_count": 1,
    },
    "project_stage": "storyboard_ready",
    "next_step_cost_estimate": 180,   # clip 生成预计费用（来自 CostEstimationService）
}
```
