# VidMuse 系统架构与完整流程总览

> 文档目标：基于当前代码实现，用通俗文字描述 VidMuse 的整体架构和从用户输入到最终产物的完整流程。
>
> 写作依据：2026-04-03 深度代码复检，所有描述均来自实际代码行为，非设计预期。
>
> v1.1 2026-04-03 对照代码二次修正：图片 Provider 更新为 DashScope、分镜生成改为多参考图串行、视觉圣经资产创作流程细化、镜头计划 character_binding 补充造型绑定、视频生成调试信息完备性说明。

---

## 一、系统定位

VidMuse 是一个 AI 音乐视频生成工具。用户上传一首歌，写几句创意描述，可以选填角色参考图，系统自动生成一段 30–60 秒的 MV 粗剪视频，并支持逐镜头修改。

整个过程由一个 AI 导演（Director）全程主持，用户通过聊天窗口与 Director 互动，在关键节点做确认决策，其余工作由系统后台自动完成。

---

## 二、技术栈一览

- **后端**：Python 3.11 + FastAPI + LangGraph
- **前端**：Next.js + TypeScript + Tailwind CSS
- **数据库**：PostgreSQL（主数据）+ Redis（队列与消息推送）
- **对象存储**：MinIO（S3 兼容）
- **本地产物**：项目目录下按阶段分文件夹存储
- **LLM**：Qwen3.5 Omni Plus（Director 对话 + 音频分析 + 图片分析）+ 通义千问系列（文本规划 Agent，通过 `config/base/llm.yaml` 配置）
- **图片生成（主力）**：qwen-image-2.0-pro（图生图，DashScope，支持 1-3 张参考图）+ z-image-turbo（文生图，DashScope）；Flux/Fal.ai 作为备用 Provider 保留
- **视频生成（实际使用）**：**ToAPIs 中转 Grok 视频模型**（grok_imagine_10_video / grok_video_3）；异步轮询模式，API key 已配置在 external_apis.yaml，	oapis_adapter.py 有完整实现。kling_v2 虽在 YAML 中 enabled=true 且排第一，但 Kling API 凭据为空，运行时会认证失败。MiniMax 的 minimax_adapter.py 文件不存在，调用会抛 ImportError。目前唯一可用的视频 Provider 是 ToAPIs

---

## 三、整体架构层次

VidMuse 的后端由六个层次构成，从上到下依次如下。

### 第一层：对话入口层

用户在前端聊天窗口发送消息，所有对话请求统一进入 `/v1/chat/completions` 接口。这个接口兼容 OpenAI 格式，方便前端集成。接口收到请求后，加载对话历史、持久化用户消息，然后把控制权交给第二层。

### 第二层：图执行层（LangGraph 主图）

主图是系统的调度骨架，负责把每一轮对话路由到正确的处理节点。主图有以下几个关键节点：

- **加载项目快照节点**：每轮对话开始时，从数据库读取项目当前阶段、已确认的决策状态、各类产物引用，作为本轮 Director 的上下文。
- **Director 节点**：调用 Director Agent，产生本轮回复和下一步动作。
- **音频分析节点**：在项目进入工作台时自动触发，不需要用户发消息。
- **确认门控节点**：在用户需要做决策时接管，创建或复用 PendingDecision 记录。
- **媒体生成节点**：分镜、视频、时间线生成任务的分发入口，接到指令后转交异步 Worker。

主图优先使用 PostgreSQL 作为状态持久化后端（通过 langgraph-checkpoint-postgres）；若依赖包未安装或 DB_URL 未配置，自动降级为 MemorySaver（内存模式）。支持跨请求的对话状态连续。

### 第三层：Agent 层

系统中共有五种 Agent，各自分工明确。

**Director Agent（导演）**：唯一与用户对话的 Agent，使用 ReAct（推理+工具调用）循环运行，底层模型为 qwen3.5-omni-plus（多模态）。Director 感知项目当前阶段和所有待决策状态，决定下一步是对话、派发任务、审核产物还是创建确认卡。Director 支持**多模态输入**：会话中自动注入用户上传的参考图 URL（最多 3 张）和音频 URL，使 Director 在生成风格方向、确认分镜等环节能直接看图听音做判断。可调用工具：派发子 Agent 任务、读取产物内容、创建用户决策、查询项目状态、估算费用、分析参考图、自动设置造型。

**CreativePlanningAgent（创意规划）**：负责生成创意方案（brief）和镜头计划（shot plan）两类文本产物，内部也以 ReAct 循环运行，先读取音频分析引用，再生成结构化 JSON，最后写出文件。

**NarrativeScriptAgent（叙事剧本）**：负责生成故事骨架，读取创意方案和风格引用，输出包含角色、场景、段落映射的叙事结构。

**VisualDevelopmentAgent（视觉开发）**：负责生成角色参考图和场景参考图，根据风格圣经和角色描述调用图片生成 Provider。

**AudioAnalysisAgent（音频分析）**：调用 Qwen3.5 Omni 对音频文件直接分析，一次输出完整的音乐结构 JSON，包含段落划分、歌词、情绪弧线、和弦进行、乐器检测等。

所有 Sub-Agent（除 Director 外）都遵守同一条铁律：只接收产物引用作为输入（不接收原文），完成后通过写出工具存盘，返回产物引用而非内容本身。

### 第四层：服务层

各业务 Service 负责具体的落库、状态推进和数据组织，不涉及 LLM 调用。典型的有：

- **BriefPersistenceService**：把 Agent 生成的 brief + style JSON 落库为版本记录，推进项目阶段到 brief_ready。
- **NarrativeScriptService**：封装叙事剧本的整个生成流程，对外提供统一入口，内部调用 NarrativeScriptAgent。
- **ShotPlanPersistenceService**：把 shot plan JSON 拆分为场景计划、镜头计划、逐个 Shot 记录，写入数据库。
- **VisualBibleService**：管理视觉圣经的完整生命周期，从叙事剧本初始化空框架，到逐个生成参考图、自动推导多套造型、最终确认。
- **DirectorReportService**：Worker 任务完成后，自动触发 Director 以汇报模式运行，生成三段式汇报消息推送给用户。
- **CostGateService**：在视频生成和导出前自动估算费用，创建费用确认决策，阻断直到用户确认。
- **DecisionService**：管理 PendingDecision 的整个生命周期，幂等创建（同类型决策不重复创建）、选项提交、状态查询。

### 第五层：异步任务层

耗时较长的任务（图片生成约 30 秒、视频生成约 5–15 分钟）走 Worker 异步模式：系统创建一条 ToolJob 记录并推入 Redis 队列，立即返回给用户"任务已提交"；TaskWorker 作为独立后台进程从队列消费任务、执行、回写状态；完成后触发 DirectorReportService 做 Mode B 自动汇报。

用户通过 SSE 长连接实时接收进度事件，不需要轮询。

### 第六层：持久化与存储层

所有版本产物都有两个存储副本：数据库里的版本记录（用于查询、版本回退、状态追踪）和对象存储里的文件（用于 Agent 读取原文内容）。本地文件目录则用于调试和快速读取。三者通过 ArtifactRef 引用结构关联，ArtifactRef 包含产物 ID、类型、本地路径、MinIO 路径、版本号、摘要六个字段。

---

## 四、从用户输入到最终视频的完整流程

### 启动入口

用户进入工作台时需要完成三件事：上传音频文件（MP3/WAV）、填写创意描述（几句话说明想要什么风格的 MV）、可选上传 1–3 张角色参考图。系统据此创建 ProjectSpec 记录，项目状态变为"输入就绪"，工作流正式启动。

---

### 第一步：自动音频分析（无需用户操作）

用户进入工作台后，系统立即自动触发音频分析，不需要用户发消息。整个分析过程在后台异步进行，用户在聊天窗口看到进度提示。

**分析过程**：先对音频进行裁切（按用户设置的起止时间），然后同时跑两条分析：一条用 librosa 做精确节拍检测，得到每一拍的毫秒时间戳（用于后续视频卡拍剪辑）；另一条用 Qwen3.5 Omni 直接听音频，一次性输出完整的音乐结构分析，包括各段落（verse、chorus、bridge）的划分、歌词（中英文）、情绪弧线、和弦进行、乐器组合等。

**产物**：一条 AudioAnalysisVersion 记录，包含 BPM、段落时间轴、节拍地图、完整的音乐语义摘要。

**分析完成后**：Director 自动汇报分析结果，告知用户 BPM 是多少、识别出几个段落、歌词主要讲什么，并给出 2–3 个风格方向供用户选择。

---

### 第二步：用户选择风格方向

Director 根据音频分析结果生成 2–3 个风格选项，每个选项包含风格名称和简短描述（例如"复古胶片·忧郁城市风"、"清新日系·青春校园风"）。这是第一个用户决策点。

用户点选其中一个，选择结果存入数据库（decision_type: select_style_direction），后续所有生成环节都会参考这个风格方向。

---

### 第三步：自动生成创意方案

用户选定风格后，Director 立即派发创意规划任务给 CreativePlanningAgent，同步等待结果（约 10–20 秒）。

**生成内容**：
- **创意方案（Creative Brief）**：包含 MV 的叙事模式（纯氛围型 / 故事型 / 演唱型混合）、情绪标签、表演占比、整体风格方向描述。
- **风格圣经（Style Bible）**：包含色调方案、光影风格、镜头风格、胶片质感描述，是后续所有视觉生成的统一标准。

Agent 通过读取音频分析引用获取音乐结构，结合用户的创意描述和风格方向，生成两份结构化 JSON 后落盘入库。

**产物**：CreativeBriefVersion（创意方案版本）+ StyleBibleVersion（风格圣经版本），项目阶段推进到 brief_ready。

**生成完成后**：Director 展示创意方案摘要，并询问用户是否确认。

---

### 第四步：用户确认创意方案

Director 展示创意方案的核心内容，用户阅读后确认（decision_type: confirm_brief）。

确认后，系统解锁叙事剧本生成。

---

### 第五步：自动生成叙事剧本（异步）

Director 派发叙事剧本生成任务，任务进入后台 Worker 队列异步执行，Director 立即告知用户"正在生成叙事剧本，请稍候"并推送 SSE 进度事件。

**生成内容**：NarrativeScriptAgent 读取创意方案引用、风格圣经引用、音频分析引用，生成一份完整的叙事结构：
- **故事弧线**：整部 MV 的叙事脉络概述。
- **角色列表**：每个角色的 ID、名称、外貌描述、出现在哪些段落。
- **场景列表**：每个场景的 ID、名称、氛围描述、出现在哪些段落。
- **段落映射表**：每个音乐段落（verse1、chorus1、bridge...）与场景、角色、情绪、剧情节点的对应关系。

**产物**：NarrativeScriptVersion，项目阶段推进到 narrative_ready。

**完成后**：Director 自动汇报叙事剧本概要，说明共有几个角色、几个场景、故事弧线走向，并创建确认卡。

---

### 第六步：用户确认叙事剧本

用户阅读叙事剧本摘要后确认（decision_type: confirm_narrative），故事骨架固化。

确认后，系统进入视觉圣经构建阶段。

---

### 第七步：构建视觉圣经（资产创作阶段，多个串行子任务）

视觉圣经是所有角色和场景参考图的集合，是后续分镜生成的视觉基准。这一阶段分为两个子阶段：**资产创作**和**用户逐图确认**。

#### 子阶段 A：初始化空框架

根据叙事剧本中的角色和场景列表，创建一个空的视觉圣经版本（CharacterSetVersion），每个角色和场景的参考图槽位初始为空。

#### 子阶段 B：分析用户上传的参考图（如有）

如果用户在入口上传了角色参考图，Director 调用 Qwen3.5 Omni 看图分析，判断图片类型（真人照片 / 插画 / AI 图）、面部质量和可用性。分析结果写回角色记录，后续生成时自动选择处理方式：
- 质量达标 → img2img（保留面部特征换装丰富）
- 质量不达标 → txt2img（根据描述重新生成）

**大多数情况下用户上传的图片无法直接使用**，需经 img2img 美化后才能作为 MV 参考图。

#### 子阶段 C：生成角色基础定妆图

对每个角色各提交一个 Worker 任务（`generate_character_ref`），根据分析结果选择生成方式：
- **用户未上传图**：z-image-turbo 文生图，9:16 竖向比例（全身像）
- **用户有上传图**：qwen-image-2.0-pro 图生图，保留面部特征生成高质量定妆图

每张图生成后触发 Director Mode B 汇报，用户可查看并决定是否重新生成。

#### 子阶段 D：生成段落造型变体

如果同一角色在不同音乐段落穿不同造型（如 verse 校园日常 / chorus 舞台礼服），系统为每套造型各提交一个 Worker 任务（`generate_costume_ref`），以角色定妆图为底，qwen-image-2.0-pro img2img 换装，生成对应造型图。

Shot 落库时，`character_binding.costume_ref_asset_id` 字段精确记录该镜头所属段落的造型图 Asset ID。

#### 子阶段 E：生成场景参考图

对每个场景各提交一个 Worker 任务（`generate_scene_ref`），z-image-turbo 文生图，21:9 超宽比例（银幕感全景）。

**产物**：CharacterSetVersion，每个角色槽位填入定妆图 Asset ID + 各段落造型图 Asset ID，每个场景槽位填入场景图 Asset ID，项目阶段推进到 visual_bible_ready。

---

### 第八步：用户确认视觉圣经

用户逐一查看角色和场景参考图，满意后确认（decision_type: confirm_visual_bible）。

如果某张图不满意，用户可以要求重新生成（Director 接收指令后再次 dispatch 生成任务），新图生成后替换旧图。确认后视觉基准固化，不再变更。

---

### 第九步：自动生成镜头计划

Director 派发镜头计划生成任务给 CreativePlanningAgent，同步执行（约 15–30 秒）。

**生成内容**：Agent 读取创意方案引用、风格圣经引用、音频分析引用，生成完整的镜头计划：
- **场景计划**：每个场景的时间范围和对应的音乐段落。
- **镜头列表**：每个镜头的具体参数，包括镜头编号、所属场景、镜头类型（演唱 / 氛围 / 叙事）、情绪标签、运镜语言、节奏、起止时间（毫秒）、时长（秒）、是否需要口型同步。

**落库时自动绑定视觉圣经资产**：Shot 落库时，系统从叙事剧本的 `section_mapping` 和视觉圣经的 `CharacterSetVersion` 中自动推导每个镜头对应的参考图，写入 `character_binding` 字段：
```
character_binding = {
  character_ids:           [角色ID列表],
  scene_ref_asset_id:      该镜头对应场景的参考图 Asset ID,
  costume_ref_asset_id:    该镜头所属段落的角色造型图 Asset ID（精确到 verse/chorus 等）,
  character_ref_asset_ids: [角色定妆图 Asset ID 列表],
}
```
这是分镜首帧生成时多参考图输入的数据来源，必须在镜头计划阶段就绑定完整。

**产物**：ShotPlanVersion + 逐个 Shot 数据库记录（每个 Shot 是独立一行，后续分镜和视频 clip 都绑定到对应的 Shot），项目阶段推进到 shot_plan_ready。

**生成完成后**：Director 汇报镜头计划概要（共几个镜头、几个场景、总时长），并创建确认卡。

---

### 第十步：用户确认镜头计划

用户看完镜头列表，检查整体结构是否合理，确认（decision_type: confirm_shot_plan）。

用户也可以对单个镜头提出修改意见（时长调整、镜头类型调整等），Director 收到后调用 ShotPatchService 局部修改。

---

### 第十一步：自动生成分镜图（异步）

Director 派发分镜生成任务，整批分镜在 Worker 中异步**串行**生成（逐帧顺序处理，避免图片生成 API 资源争抢），通常需要 2–8 分钟（取决于镜头数量）。

**生成过程**：对每个 Shot，**串行**逐帧处理（不并发）：

1. **编译提示词**：PromptCompilerService 从 `character_binding` 中按顺序取出 1-3 张参考图 URL：
   - 位置 1：场景参考图（构图环境基底）
   - 位置 2：该段落造型图（服装锁定）
   - 位置 3：角色定妆图（脸型一致性）
   同时，LLM 用 `compile_image_prompt.md` 模板把镜头语义（情绪 + 景别 + 运镜 + 风格）编译为英文图像生成指令。

2. **生成首帧图**：调用 qwen-image-2.0-pro，将 1-3 张参考图 + 提示词一起传入，做多参考图 img2img 合成。若参考图不足，自动降级为单图 img2img；无参考图则 txt2img。

3. **落库存储**：图片上传 MinIO（`projects/{id}/assets/storyboard_frame/{asset_id}/frame_XXX.jpg`），DB 写 `assets` + `storyboard_frames`，本地写 `06_storyboard/frame_XXX.jpg`。提示词 bundle 写 `prompt_bundles` 表 + 本地 `07_prompt_bundles/bundle_shot_XXX.json`。

**产物**：StoryboardVersion + 每个 Shot 绑定一张首帧分镜图（图片 Asset），项目阶段推进到 storyboard_ready。

**完成后**：Director 自动汇报，告知分镜图已全部生成，请用户逐帧确认。

---

### 第十二步：用户确认分镜图

用户在工作台逐帧查看分镜图（decision_type: confirm_storyboard）。这是视频生成前的最后一道内容审核门控，因为视频生成是高成本操作，确认后不可轻易撤回。

如果某帧不满意，用户可以要求重新生成单张（Director 派发单 Shot 重生成任务），或者局部修改镜头参数后重生成。

---

### 第十三步：确认视频费用，开始生成视频片段（异步）

用户确认分镜图后，系统在正式生成视频之前先做一次费用门控。系统自动统计需要生成的 Shot 数量和平均时长，计算总 credits 消耗。

**[代码修正]** 独立的 `confirm_cost_clips` 决策类型**不存在**。实际门控为 `confirm_storyboard` 决策，其提示文案已注明"高成本操作，请确认预计消耗 credits"，用户在确认分镜时即已完成对视频生成费用的知情确认。系统在 `POST /workflow/generate-clips` 中前置校验 `confirm_storyboard` 状态，而非单独创建费用确认卡。

视频生成任务进入 Worker 队列（`generate_clips` ToolJob）异步执行。ClipService 对每个 Shot 串行处理：

1. 读取该 Shot 对应的分镜图 URL（`storyboard_frame.storage_uri`），作为视频首帧。
2. PromptCompilerService 用 `compile_video_prompt.md` 编译视频生成提示词（`target_type="shot_clip"`），提示词 bundle 同样写入 `prompt_bundles` 表和本地 `07_prompt_bundles/bundle_shot_XXX.json`，方便逐帧调试。
3. 调用视频 Provider（Kling AI / ToAPIs 中转）以 image_to_video 模式生成，以首帧图作为起始帧。视频 Provider 采用异步轮询模式（提交任务 → 轮询完成），耗时取决于视频时长（约 3-15 分钟/clip）。
4. 生成完成后下载视频字节，上传 MinIO（`projects/{id}/assets/shot_clip/{asset_id}/clip_{asset_id}.mp4`），DB 写 `assets`(clip_video) + `clip_versions`，本地写 `08_clips/clip_{asset_id}.mp4`。

**实时推送：每个 clip 生成完成后立即推送 SSE 事件 `clip.shot.completed`**，消息内容包含该 clip 的 `storage_uri`、`shot_index`、`start_ms/end_ms` 等字段。前端收到后可立即将该 clip 填入时间轴对应位置，实现时间轴逐渐填充效果，无需等待所有 clip 全部完成。全部完成后追加一个 `project_clips_ready` 阶段事件，前端解锁「合成完整视频」按钮。

**产物**：每个 Shot 对应一个视频 clip Asset，ClipVersion 记录绑定到对应 Shot，项目阶段推进到 clips_ready。

---

### 第十四步：编辑预览 + 用户主动触发时间线合成

**[架构说明]** 此阶段实际分为两种模式，各自独立，不开启后者也可看到前者：

**模式 A：分片预览（前端虚拟调度，无需后端）**

`clips_ready` 后即可使用。前端以音频播放器为主时钟，按每个视频片段的 `start_ms/end_ms` 逐个切换 `<video>` 的 `src`，实现虚拟拼接滚动预览效果。**全程不需要后端**。

**模式 B：合成完整视频（后端 ffmpeg，用户主动触发）**

用户在前端点击「合成完整视频」按钮，调用 `POST /api/v1/projects/{id}/timeline/compose`，任务异步进入 Worker 队列。Worker 调用 TimelineComposerService，使用 ffmpeg 将所有视频片段按时间轴顺序拼接并混入音频轨道，生成完整的时间线视频文件。通常需要 1–2 分钟。完成后通过 SSE `project_timeline_ready` 通知，用户可以切换到「完整视频」tab 预览。

> 备注：Director AI 对话流中仍可自动输出 `generate_timeline` 触发合成（同步路径），与用户主动触发为并行两条路径；两种路径最终都调用同一 TimelineComposerService。

**两种产物永久共存，互不覆盖：**
- 分片产物：每个 Shot 独立 clip Asset，`clip_versions` 表 + MinIO `08_clips/`
- 合成产物：ffmpeg 拼接后完整 mp4，`timeline_versions` 表 + MinIO `timeline_preview/`

**产物**：TimelineVersion（合并后的完整 MV 视频文件），项目阶段推进到 timeline_ready。

---

### 第十五步：确认导出费用，导出最终视频

用户选择导出分辨率（720p 或 1080p）。系统做最后一次费用门控，创建导出确认卡（decision_type: confirm_cost_export_720p 或 confirm_cost_export_1080p），显示时长和预计 credits。

用户确认后，ExportService 进行最终渲染和格式化导出，生成可下载的最终视频文件，项目阶段推进到 export_ready 并最终标记为 completed。

**产物**：导出视频文件（Asset），可供用户下载。

---

## 五、贯穿全程的四大核心机制

### 机制一：产物引用协议（ArtifactRef）

Agent 之间传递的不是产物内容本身，而是一个标准化的引用结构（ArtifactRef），包含产物 ID、类型、本地文件路径、MinIO 路径、版本号、摘要六个字段。需要读取产物原文时，通过引用去文件系统或 MinIO 拉取，而不是在内存中传来传去。这样做的目的是防止大型 JSON 滞留在 LangGraph 的 Graph State 中，避免超长状态导致的问题。

### 机制二：Worker 异步任务

耗时超过 10 秒的任务（音频分析、叙事剧本、分镜、视频、时间线）都走异步 Worker 模式：系统立即返回"已提交"，TaskWorker 后台消费，通过 SSE 实时推送进度事件到前端，完成后自动触发 Director Mode B 汇报。用户不需要等待 HTTP 响应，全程异步无感知。

### 机制三：Director Mode B 汇报

每当 Worker 完成一个关键任务，DirectorReportService 自动触发一次特殊的 Director 调用。这次调用中 Director 读取刚完成的产物引用内容，生成三段式汇报：第一段描述产物结果，第二段给出判断和推荐，第三段提问下一步。汇报消息落库后通过 SSE 推送给前端 Chat 区，用户不需要主动发消息就能看到进度。

### 机制四：PendingDecision 门控

每个需要用户确认的节点都对应一类 PendingDecision 记录。PendingDecision 有三个状态：open（等待用户）、selected（用户已选）、expired（超时作废）。系统在每轮对话加载快照时读取所有 open 状态的决策，Director 据此判断当前是否有待处理的确认卡，避免重复创建。用户通过前端点选确认卡上的选项（而不是发文字消息）完成决策，系统收到 selected 状态后才推进到下一阶段。

---

## 六、状态机与阶段回退规则

项目共 12 个阶段，从 created 到 completed 线性推进，但允许在上游产物被修改时回退到对应阶段重做。回退规则如下：

- 修改音频区间 → 项目回退到 input_ready，音频分析之后所有产物全部失效
- 修改创意方案 → 项目回退到 audio_analyzed，brief 之后所有产物失效
- 修改叙事剧本 → 项目回退到 brief_ready，narrative 之后所有产物失效
- 修改角色/场景参考图 → 项目回退到 visual_bible_ready，绑定该角色的 storyboard + clip 标记为 stale（待刷新）
- 修改单个镜头参数 → 只有该镜头的 clip 失效，其他不受影响

---

## 七、可选流程：口型同步

在视频片段生成完成后，用户可以对需要演唱画面的镜头追加口型同步处理。每个镜头各独立一张费用确认卡（decision_type: confirm_cost_lipsync_{镜头ID}），确认后调用 Hedra AI LipSync 服务处理，处理完成后该 clip 被更新版本替换。口型同步不改变项目主阶段，是对单个 clip 的局部增强。

---

## 八、文档版本

| 版本 | 日期 | 内容 |
| v1.0 | 2026-04-03 | 初始建立，基于 2026-04-03 深度代码复检，覆盖 doc12 偏差1/2/3/4/5/6 全部完成后的最终架构状态 |
| v1.1 | 2026-04-03 | 对照代码二次修正：图片 Provider 更新为 DashScope（qwen-image-2.0-pro + z-image-turbo）；分镜生成改为多参考图（场景→造型→角色）串行合成；视觉圣经资产创作五个子阶段详细说明；镜头计划补充 character_binding 造型绑定字段；视频生成补充首帧来源、提示词落盘、Provider 异步轮询模式 |
| v1.2 | 2026-04-03 | 流程架构纠正：第十三步补充 per-clip SSE `clip.shot.completed` 说明（前端时间轴逐渐填充）；第十四步拆分为模式A（前端虚拟预览）和模式B（用户主动触发 ffmpeg 合成），明确 ffmpeg 仅用于导出而非预览 |
| v1.3 | 2026-04-03 | 全面代码复核修正：①视频 Provider 补充 MiniMax Video；②LangGraph checkpoint 改为「优先 PostgreSQL/降级 MemorySaver」；③分镜生成改为串行（非并发）；④删除不存在的 confirm_cost_clips 决策类型，实际门控为 confirm_storyboard；⑤Director Agent 补充多模态输入（图+音）能力；⑥文本规划 Agent 明确模型名 qwen3.5-plus |











