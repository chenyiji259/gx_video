# VidMuse 口播类 Production Board 创作链路重构设计

## 1. 背景

当前 VidMuse 主链路已经可以从用户需求逐层生成 brief、剧本、分镜资产、视频片段、时间线和导出结果。口播类视频继续沿用“先规划、再生成、再合成”的工程阶段，但不继续沿用三宫格作为口播创作单位。

本次讨论的变化点不是“是否还要先规划再生成”，而是口播类视频的创作方式要从普通分镜彻底转向更适合讲解视频的 Production Board。Production Board 是口播类视频的主链路设计，不是三宫格失败后的降级策略，也不是与三宫格并行混用的兼容分支。

参考图所体现的不是单张分镜，而是一张导演前期制作指南：它同时描述项目约束、角色造型、场景设计、机位、故事板、台词、灯光、情绪、音频和摄影语言。对口播科普视频来说，这种图可以成为每个 15 秒段落的统一创作锚点。

## 2. 目标

建立一套面向口播类视频的模板化创作流程：

```text
用户需求
  -> 口播创意策划 TalkingHeadBrief
  -> 分段脚本 SegmentScript
  -> 生成一张 60s 故事大图 / Story Overview Board
  -> 4 个 15s shot 复用同一张故事大图，分别读取对应 segment 区域
  -> LLM 为每个 shot 编译 Seedance 视频提示词
  -> 每段生成一个 15s clip
  -> 拼接成完整视频
```

以“1 分钟讲解视黄醇的科普口播视频”为例，当前目标产物不是 1 张普通三宫格，也不是 4 张彼此独立的 15 秒 Production Board，而是一张覆盖完整 60 秒内容的故事大图。它内部必须清晰拆成 4 个 15 秒 segment，后续 4 次 Seedance 视频生成都复用这同一张图，但每次只读取当前 shot 对应的 segment 区域。

本设计中需要严格区分三类产物：

- `Global Creative Bible`：结构化全局创意圣经，保存主角、场景、声音、色彩、栏目结构和 4 段内容弧线。它不是图片资产，而是生成故事大图和视频 prompt 的上游依据。
- `Story Overview Board`：当前主链路的故事大图资产。一张图覆盖完整 60 秒，内部固定分成 4 个 15 秒 segment，是后续 Seedance 4 个 shot 共同复用的主要参考图。
- `Segment Production Board`：单段制作板，作为备选或后续回退能力保留。当实测证明故事大图读取不稳定时，可以退回每个 15 秒 segment 单独生成一张板，但这不是当前主线。

## 3. 非目标

- 本文档不直接定义数据库迁移方案。
- 本文档不直接修改当前代码。
- 本文档不替代后续 prompt 模板、服务层和前端交互的详细实现设计。
- 本文档不讨论通用剧情短片、MV、广告大片的完整重构，只聚焦口播讲解类视频。
- 本文档不设计“三宫格和 Production Board 并存”的口播方案。口播链路只采用 Production Board，三宫格只作为历史背景和被替换对象出现。

## 4. 核心判断

原有三宫格逻辑适合表达“一个 shot 从起始到中间再到结尾的运动状态”。口播类视频的关键不是单个动作弧线，而是以下要素在一段时间内协同稳定：

- 固定主角
- 固定场景
- 完整台词
- 信息结构
- 辅助视觉
- 镜头节奏
- 声音语气
- 背景音
- 灯光和视觉风格

因此，口播类视频的核心中间产物应从 `1x3_triptych` 转为 `talking_head_production_board`。

### 4.1 当前已明确的结论

基于脚本测试和当前对话，以下内容已经拍板，后续实现不应再反复摇摆：

- 视频总时长必须是 15 秒倍数，前端限制输入，后端二次校验。
- 1 个 15 秒 segment 对应 1 个 shot / 1 个 Seedance clip。
- 当前 60 秒口播验证主线是：1 张故事大图 + 4 个 15 秒 shot 复用同一张图。
- LLM 负责生成故事大图生图提示词，代码不能固定拼一段通用 prompt 就交给图片模型。
- LLM 负责生成每个 shot 的 Seedance 视频提示词，代码不能只写固定模板替换 shot_index。
- 固定 3 张人物资产从 env/config 读取，用于锁脸、年龄感、气质和基础身形，不锁死服装。
- 固定 3 个音频资产从 env/config 读取，只作为声色参考，不作为逐字对白轨。
- 故事大图当前默认画幅固定为 `21:9`，用于承载完整 60 秒总览制作板信息。
- 当前正式链路不用 TTS，不生成 `segment_voiceover_audio`，不引入 `VoiceProfile` 作为主链路依赖。
- Seedance `content` 必须显式传 `role=reference_image` / `role=reference_audio`，不能回到裸 URL。
- 视频最终呈现方式固定为专家知识口播，不是电影广告片，也不是 Production Board 版式复刻。
- 当前视频 prompt 默认要求纯净无字幕画面，不生成字幕、水印、标题栏或文字贴片。

### 4.2 当前还未完全明确的内容

以下内容仍是实现时需要通过小样例验证或局部设计补齐的问题，不应提前写成已完成能力：

- 一张故事大图复用 4 个 shot 的稳定性需要真实跑完整 60 秒样例验证。
- 如果故事大图读取不稳定，是否回退到每段一张 `Segment Production Board`，仍是备选策略。
- 每个 15 秒 shot 内对白、开场动画、停顿、产品特写、动作和辅助视觉的节奏分配，需要由前置创意和剧本设计决定，不能机械要求 15 秒全部说满。
- 中文台词长度、自然口播语速和 LLM 自动压缩规则还需要量化。
- 固定人物资产、音频资产如何在数据库中建模和展示，还需要后续实现设计。

### 4.3 已废弃或不进入当前主线的内容

以下内容容易误导实现，需要明确排除：

- 不再使用三宫格 / triptych 作为口播类视频主链路。
- 不再把 TTS 作为当前口播视频生成前置步骤。
- 不再把参考音频当作完整对白、口型或节奏轨。
- 不再把“4 张单段 Production Board”作为当前 60 秒口播验证主线。
- 不再让视频模型从故事大图中自由猜当前段落；必须由 prompt 指定读取区域。
- 不再默认生成字幕；当前口播视频要求纯净无字幕画面。

## 5. 新创作单位

### 5.1 Segment

口播视频按 15 秒为硬边界拆分为多个 segment。这里的 15 秒不是建议值，而是前端输入、后端规划、LLM 分段和 Seedance 提交共同遵守的基础单位。

前端创建口播类项目时，视频总时长只能选择或输入 15 秒的整数倍，例如 15、30、45、60、75、90 秒。不允许把 20 秒、40 秒、50 秒这类非 15 秒倍数传入后端。后端仍要做二次校验，拒绝非 15 秒倍数，避免前端绕过后续导致 shot 规划、提示词分段和 timeline 合成错位。

LLM 生成 `SegmentScript` 和视频提示词时，也必须把 15 秒作为一个 shot / clip 的分水岭：

- `target_duration_sec = 15`：生成 1 个 segment / 1 个 shot / 1 个 clip。
- `target_duration_sec = 60`：生成 4 个 segment / 4 个 shot / 4 个 15 秒 clip。
- 每个 segment 内部可以继续拆 `micro_shots` 或 `motion_beats`，但它们只是 15 秒 clip 内部的时间段，不再升级成独立 clip。
- 不允许生成 12 秒、18 秒、22 秒这类不稳定片段，再让 timeline 阶段硬凑总时长。

示例：1 分钟视黄醇科普视频可拆为：

```text
Segment 1 / 0-15s：视黄醇是什么，为什么大家都在说
Segment 2 / 15-30s：视黄醇的核心作用和适用人群
Segment 3 / 30-45s：新手如何使用，频率和注意事项
Segment 4 / 45-60s：避坑总结和行动建议
```

当前主链路中，每个 segment 仍然对应一个 15 秒 clip，但不再默认每段独立生成一张 Production Board。1 分钟视频是 4 个 segment、1 张故事大图、4 个 15 秒 clip，最后进入 timeline 拼接。

### 5.2 Production Board

Production Board / Story Overview Board 是口播链路的视觉规划图。它不是最终视频画面，而是给图片模型、视频模型和后续审核流程共同使用的导演板。

当前已验证方向是“1 张故事大图 + 4 个 15 秒 shot 复用读取”。因此故事大图的粒度是完整 60 秒，但它内部必须强制拆成 4 个清晰 segment。每次视频生成时，LLM 和 Seedance prompt 必须指定当前只读取某一个 segment 区域。这里的关键不是把 60 秒信息随意塞进一张图，而是用固定版式、清晰区域和明确读取指令降低串段风险。

Production Board 应包含：

- 顶部栏：项目标题、段落编号、时长、格式、核心观点、色彩基调、场景约束。
- 主角与造型参考：固定主角的正面、侧面、近景、自然口播姿态、服装和配饰。
- 环境与场景设计：固定讲解场景、桌面产品位置、背景灯光、机位图。
- 故事板：6 到 8 个微镜头，描述时间点、景别、运镜、动作、情绪和对应台词。
- 台词区：本段计划表达的口播台词，要求后续视频 prompt 按剧本节奏保留核心表达；允许开场动画、停顿、产品特写或无对白片段。
- 辅助视觉：产品特写、成分图示、使用步骤卡片、注意事项图标。
- 灯光和风格：统一灯光、皮肤质感、色彩、后期风格。
- 音频和声调：主角声音、语速、BGM、环境音和情绪。
- 摄影规则：焦段、景别、运镜方式、禁止事项。

Production Board 中的可见文字默认全部使用中文，包括标题、分区名、台词、镜头说明、音频说明、摄影说明和约束说明。除非是行业内更稳定的专业词汇或模型更容易识别的镜头术语，例如 `push-in`、`close-up`、`macro`、`BGM`、`Seedance`，否则不要使用英文。英文不能作为版面主要语言，也不能把整张制作板做成英文 production sheet。

## 6. 三类一致性锁

口播类视频必须在创意阶段就生成全局一致性锁，并由后续所有 segment 继承。

一致性锁不是让模型自由猜的隐含信息，而是结构化约束和可复用参考资产。当前主链路中，`Story Overview Board` 从这些锁中读取同一主角、同一场景、同一声音和同一视觉系统，再把 4 个 15 秒 segment 组织到一张故事大图中。后续每个 15 秒视频 prompt 只读取故事大图中的当前 segment 区域。

### 6.1 Host Lock

用于锁定人物一致性：

- 固定主角资产作为后续所有生图和视频的参考图。
- 固定外貌、发型、服装、妆容、年龄感、表情气质。
- 后续 board prompt 和 video prompt 都必须禁止换脸、换服装、换年龄感、换人物数量。

当前口播链路先固定 3 个 Seedance 人物参考资产，作为环境配置读取，而不是硬编码在 prompt 或服务实现里。后续如果替换主持人，只需要替换 env/config 中的资产列表。

```text
TALKING_HEAD_HOST_REFERENCE_IMAGE_ASSETS=
asset://asset-20260506200638-6g86k,
asset://asset-20260506200638-5pf4j,
asset://asset-20260506200636-lmt8b
```

这 3 个资产是同一人物的不同着装和颜色参考，后续用途分两层：

- Production Board 生图阶段：作为故事大图 / 制作板的人物参考图，要求模型保持同一张脸、同一年龄感和同一人物气质。
- Seedance 视频生成阶段：作为 `reference_image` 固定传入，用于保持人物脸部一致性。

提示词策略必须写清：这 3 张图只锁定“同一人物脸部身份、年龄感、气质和基础身形”，不要强制锁死服装。服装、颜色和造型应以当前故事大图 / Production Board 的场景设计为主，由模型根据 segment 场景决定；视频阶段则要强调“脸保持参考资产一致，着装以图片2中的故事大图为准”。

本地参考图已放入 `data/person_pic`，它们是这 3 个 asset 的本地源文件副本，主要用于后续生图链路上传、复用、排查和重新登记资产。

### 6.2 Set Lock

用于锁定场景一致性：

- 固定讲解场景，例如护肤讲解台、浴室镜前、实验室风格桌面或生活方式背景。
- 固定桌面产品位置、背景层次、灯光方向和色彩基调。
- segment 之间只替换辅助视觉和台词，不随意换主场景。

### 6.3 Audio Lock

用于锁定声音一致性：

- 同一主角声音。
- 同一语速和语气。
- 同一 BGM 类型和音量策略。
- 同一环境音和整体听觉氛围。

当前口播链路先固定 3 个 Seedance 音频参考资产，也从 env/config 读取，和人物参考资产一样作为可替换配置：

```text
TALKING_HEAD_REFERENCE_AUDIO_ASSETS=
asset://asset-20260506202002-hhmgk,
asset://asset-20260506202001-fg589,
asset://asset-20260506202001-hl2kx
```

这 3 个音频资产只用于参考音色、声线、年龄感、口音和说话气质，不作为逐字对白音轨。视频提示词必须显式写出当前 segment 的台词、情绪、动作和分时间段说话方式，再说明角色使用对应 `reference_audio` 的声色来表达这些台词。

## 7. TalkingHeadBrief 输出建议

口播创意阶段不应只输出普通 creative brief，而应输出面向口播生产的结构化 brief。

建议字段：

```json
{
  "format": "talking_head_educational_video",
  "topic": "视黄醇科普",
  "target_duration_sec": 60,
  "segment_count": 4,
  "segment_duration_sec": 15,
  "host_character_profile": "固定主角，护肤科普博主，亲和、专业、可信",
  "set_design_profile": "统一护肤讲解台，柔和暖白光，干净背景，桌面有视黄醇产品和成分卡片",
  "voice_profile": "同一中文口播声线，语速中等，专业但不压迫",
  "bgm_profile": "轻柔、干净、低音量，不压过人声",
  "content_arc": [
    "视黄醇是什么",
    "它有什么用",
    "新手怎么用",
    "避坑和总结"
  ]
}
```

## 8. SegmentScript 输出建议

每个 segment 至少包含：

```json
{
  "segment_index": 1,
  "duration_sec": 15,
  "segment_goal": "解释视黄醇是什么，并建立用户继续观看的动机",
  "voiceover_script": "完整口播台词",
  "key_visuals": [
    "视黄醇分子概念图",
    "护肤品瓶身特写",
    "主角面对镜头解释"
  ],
  "micro_shots": [
    {
      "time_range": "0-3s",
      "shot_size": "medium close-up",
      "camera_motion": "static with subtle push-in",
      "action": "主角看向镜头，引出本段主题",
      "dialogue_part": "对应台词片段"
    }
  ]
}
```

### 8.1 从需求到故事大图生图的依据传递

口播链路的关键不是“写一个很长的生图 prompt”，而是前置阶段必须产出足够稳定的结构化依据。故事大图生图 prompt 只能做编译，不应该在生图阶段重新发明主角、场景、台词、内容结构或镜头语言。

正确的数据传递链路是：

```text
ProjectSpec
  -> TalkingHeadBrief
      -> Global Creative Bible
      -> Host Lock / Set Lock / Audio Lock / Visual Lock
  -> SegmentScript
      -> segment goal / voiceover / micro shots / key visuals
  -> StoryOverviewBoardSpec
      -> compile_story_board_image_prompt
      -> image provider
      -> Story Overview Board asset
```

其中 `StoryOverviewBoardSpec` 是当前主线生图提示词的直接输入。它不是用户直接填写的表单，也不是 LLM 临场自由发挥的结果，而是由 `TalkingHeadBrief + SegmentScript[] + reference assets + output_config` 编译出来的中间结构。

### 8.2 ProjectSpec 应向口播链路传递的输入字段

需求入口至少要保留以下字段，作为后续创意阶段的硬约束：

```json
{
  "user_prompt": "1分钟讲清视黄醇，面向护肤新手，单人专家口播",
  "output_config": {
    "content_type": "talking_head",
    "topic": "视黄醇科普",
    "target_duration_sec": 60,
    "segment_duration_sec": 15,
    "aspect_ratio": "21:9",
    "video_resolution": "1080p",
    "image_resolution": "2K",
    "target_platform": "小红书 / 抖音 / 视频号",
    "target_audience": "护肤新手",
    "style_preference": "专业、亲和、干净护肤科普",
    "human_on_camera": true,
    "host_requirement": "单人讲解，不出现第二位主持人",
    "language": "zh-CN"
  },
  "reference_image_asset_ids": [
    "host_reference_asset_id",
    "product_reference_asset_id",
    "set_reference_asset_id"
  ],
  "constraints": {
    "must_include": ["视黄醇是什么", "怎么用", "避坑"],
    "must_avoid": ["医疗承诺", "夸大功效", "多人出镜"]
  }
}
```

这些字段的作用边界：

- `content_type=talking_head`：决定进入 Production Board 主链路。
- `target_duration_sec + segment_duration_sec`：决定 segment 数量，例如 60 秒拆成 4 段。
- `target_audience + topic + must_include`：决定内容弧线和每段信息重点。
- `style_preference + aspect_ratio + image_resolution`：决定制作板画面语言、画幅和生图规格。
- `human_on_camera + host_requirement + reference_image_asset_ids`：决定 Host Lock 的强度和参考资产输入。
- `constraints.must_avoid`：进入 board prompt 和 video prompt 的禁止项。

### 8.3 TalkingHeadBrief 必须产出的全局字段

`TalkingHeadBrief` 负责把用户需求变成全局创作圣经。它要回答“这个口播视频整体是谁在什么地方、用什么口吻、按什么内容结构讲完”，不能只输出普通摘要。

建议结构：

```json
{
  "format": "single_host_educational_talking_head",
  "project_title": "1分钟讲清视黄醇",
  "topic": "视黄醇科普",
  "target_duration_sec": 60,
  "segment_count": 4,
  "segment_duration_sec": 15,
  "language": "zh-CN",
  "content_arc": [
    {
      "segment_index": 1,
      "time_range": "0-15s",
      "title": "视黄醇是什么",
      "goal": "用一句话解释视黄醇，并建立继续观看动机"
    }
  ],
  "host_lock": {
    "identity": "同一位护肤科普男主持",
    "appearance": "黑框眼镜、灰色衬衫、白色内搭、成熟专业气质",
    "wardrobe": "灰色衬衫、白色内搭、简洁商务休闲",
    "expression_range": "自然、耐心、可信、轻微微笑",
    "reference_asset_ids": ["host_reference_asset_id"],
    "negative_rules": ["不要换脸", "不要换服装", "不要改变年龄感", "不要出现第二位主持人"]
  },
  "set_lock": {
    "location": "护肤科普讲解台",
    "environment": "暖灰背景、柔和实用灯、桌面有视黄醇产品和成分卡",
    "tabletop_layout": "主持人居中，产品和成分卡在右侧，辅助道具在左侧",
    "lighting": "柔和主光、暖色背景灯、自然皮肤质感",
    "reference_asset_ids": ["set_reference_asset_id"]
  },
  "visual_lock": {
    "color_palette": ["warm gray", "soft beige", "clean white", "muted amber", "scientific blue accent"],
    "image_style": "商业护肤科普 production board，排版清晰，电影级但不夸张",
    "text_language": "visible_text_must_be_chinese",
    "brand_safety": "不生成真实品牌 logo，不做医疗功效承诺"
  },
  "audio_lock": {
    "voice_profile": "同一中文男声，成熟、平静、专业、亲和",
    "pace": "中等语速，自然停顿",
    "bgm_profile": "轻柔干净、低音量、不压过人声",
    "ambient": "安静室内，轻微产品处理声"
  },
  "cinematography_lock": {
    "lens_plan": ["35mm medium close-up", "50mm close-up", "85mm macro insert"],
    "camera_style": "以静态中近景为主，少量 subtle push-in，产品特写干净",
    "forbidden": ["不要夸张运镜", "不要频繁换场景", "不要综艺化表演"]
  }
}
```

你生成的全局图里，左侧主持人身份锁、上方环境锁、右侧机位图、底部灯光/音频/镜头说明，本质上都应该来自这一层。全局图可以作为人工审核视图，但真正进入每段生图 prompt 的应是这些结构化字段，而不是让后续模型从全局图里反向猜字段。

### 8.4 SegmentScript 必须产出的段落字段

`SegmentScript` 负责把全局创意拆成每个 15 秒段落。它要回答“这一段讲什么、逐字怎么说、画面如何配合台词变化”，不能只输出笼统的 shot 描述。

建议结构：

```json
{
  "segment_index": 1,
  "total_segments": 4,
  "time_range": "0-15s",
  "duration_sec": 15,
  "segment_title": "视黄醇是什么",
  "segment_goal": "解释视黄醇是什么，并建立继续观看动机",
  "knowledge_points": [
    "视黄醇是维生素A衍生物",
    "它不是今天用明天变年轻",
    "它通过持续作用让皮肤状态慢慢变稳"
  ],
  "voiceover_script": "视黄醇，其实是维A的一种衍生物。你可以把它理解成护肤里的长期训练型选手。它不是今天用明天就变年轻，而是通过持续作用，让皮肤状态慢慢变稳。",
  "spoken_duration_estimate_sec": 14.5,
  "key_visuals": [
    "主持人中近景开场",
    "视黄醇分子概念卡片",
    "产品瓶身和成分卡特写"
  ],
  "micro_shots": [
    {
      "micro_shot_index": 1,
      "time_range": "0-3s",
      "shot_size": "medium close-up",
      "lens": "35mm",
      "camera_motion": "static",
      "action": "主持人看向镜头，平静开场",
      "emotion": "专业、亲和",
      "visual_focus": "主角面部和上半身",
      "dialogue_part": "视黄醇，其实是维A的一种衍生物。"
    },
    {
      "micro_shot_index": 2,
      "time_range": "3-7s",
      "shot_size": "medium close-up",
      "lens": "50mm",
      "camera_motion": "subtle push-in",
      "action": "主持人抬手解释，右侧出现简单分子结构卡片",
      "emotion": "耐心解释",
      "visual_focus": "主持人手势 + 成分卡",
      "dialogue_part": "你可以把它理解成护肤里的长期训练型选手。"
    }
  ],
  "segment_specific_visuals": [
    {
      "type": "ingredient_card",
      "label": "视黄醇 Retinol",
      "placement": "画面右侧卡片，不做网页 UI"
    }
  ],
  "segment_negative_rules": [
    "不要出现医学治疗承诺",
    "不要把分子卡做成复杂论文页面",
    "不要改变主持人和场景"
  ]
}
```

如果后续回退到“每个 15 秒 segment 单独生成一张制作板”，单段图里的顶部栏、左侧主持人参考、环境图、机位图、微镜头、底部灯光和音频说明，应该由这一层的段落字段加上全局锁共同编译出来。

### 8.5 SegmentProductionBoardSpec：单段制作板回退规格

本节不是当前 60 秒口播主线，而是回退方案规格。当前主线优先生成一张 `StoryOverviewBoardSpec` 故事大图，再让 4 个 15 秒 shot 复用读取不同 segment 区域。只有当故事大图复用实测出现严重串段、读错区域或版式复刻时，才回退到每段一张 `SegmentProductionBoardSpec`。

如果进入单段制作板回退方案，生图阶段不应直接读取一堆零散的 brief/script 字段，而应先编译出单段制作板规格：

```json
{
  "board_type": "segment_production_board",
  "target_type": "talking_head_production_board",
  "project_title": "1分钟讲清视黄醇",
  "segment_index": 1,
  "total_segments": 4,
  "duration_sec": 15,
  "format": "single_host_educational_talking_head",
  "topic": "视黄醇是什么",
  "layout_language": "zh-CN",
  "visible_text_policy": "all_visible_labels_and_dialogue_in_chinese",
  "top_bar": {
    "project_title": "1分钟讲清视黄醇",
    "segment_label": "1 / 4",
    "duration": "15 秒",
    "format": "单人科普口播",
    "topic": "视黄醇是什么",
    "host": "同一位护肤科普男主持",
    "location": "护肤科普讲解台",
    "color_palette": "暖灰、柔米色、干净白、琥珀色、科学蓝点缀"
  },
  "host_panel": {
    "source": "TalkingHeadBrief.host_lock",
    "reference_asset_ids": ["host_reference_asset_id"],
    "required_views": ["正面中近景", "三分之二侧身", "近景脸部", "手势讲解", "坐在桌前"],
    "styling_notes": "灰色衬衫、白色内搭、黑框眼镜、成熟专业"
  },
  "set_panel": {
    "source": "TalkingHeadBrief.set_lock",
    "reference_asset_ids": ["set_reference_asset_id", "product_reference_asset_id"],
    "environment": "统一护肤讲解台，桌面产品固定，背景暖光架子",
    "camera_plan": "主机位中近景，少量 push-in，产品 macro insert"
  },
  "storyboard_panel": {
    "source": "SegmentScript.micro_shots",
    "micro_shots": []
  },
  "dialogue_panel": {
    "source": "SegmentScript.voiceover_script",
    "full_voiceover_script": "..."
  },
  "supporting_visuals_panel": {
    "source": "SegmentScript.segment_specific_visuals",
    "items": []
  },
  "lighting_audio_cinematography_panel": {
    "source": "TalkingHeadBrief.visual_lock + audio_lock + cinematography_lock",
    "lighting": "...",
    "audio": "...",
    "cinematography": "..."
  },
  "negative_rules": [
    "不要生成英文为主的 production sheet",
    "不要换主持人",
    "不要改变场景",
    "不要出现第二位人物",
    "不要生成品牌 logo 或医疗承诺"
  ]
}
```

单段回退方案中的 `compile_production_board_prompt.md` 只接收这个规格并渲染 prompt。这样后续调试时可以明确追溯：某张单段 Production Board 的主持人、场景、台词、镜头、音频和禁止项分别来自哪个上游版本，而不是只能从最终 prompt 文本里猜。

### 8.5.1 StoryOverviewBoardSpec：故事大图资产规格

当前阶段如果采用“一张故事大图复用生成 4 个 shot”的策略，就不能只让 LLM 写一句“生成一张 1 分钟故事板”。必须先定义故事大图资产规格，再让 LLM 基于该规格生成生图提示词。

故事大图是一个结构化视觉资产，建议 target_type 为 `talking_head_story_overview_board`。它不是最终视频画面，也不是三宫格，而是一张用于后续 4 个 15 秒 shot 共同读取的导演故事大图。

故事大图必须有固定区域布局：

```text
┌──────────────────────────────────────────────┐
│ A. 顶部项目栏                                  │
│ 项目标题 / 总时长 / 4x15s 结构 / 主题 / 风格       │
├───────────────┬──────────────────────────────┤
│ B. 人物参考区   │ C. 场景与机位区                   │
│ 同一主角脸部    │ 统一场景、桌面、灯光、机位、道具       │
│ 多姿态参考      │                                  │
├───────────────┴──────────────────────────────┤
│ D. 四段故事区                                  │
│ Segment 1: 0-15s                               │
│ Segment 2: 15-30s                              │
│ Segment 3: 30-45s                              │
│ Segment 4: 45-60s                              │
│ 每段独立边界、标题、台词摘要、动作、表情、辅助视觉     │
├──────────────────────────────────────────────┤
│ E. 底部声音 / 灯光 / 摄影 / 禁止事项              │
└──────────────────────────────────────────────┘
```

每个区域的职责：

- A 顶部项目栏：只放全局信息，不能放某个 shot 的细节。
- B 人物参考区：展示同一人物的脸部身份、年龄感、气质和基础身形；强调这是同一人，不是多人。
- C 场景与机位区：展示统一讲解场景、道具位置、灯光方向、主机位和辅助机位。
- D 四段故事区：核心区域，必须分成 4 个清晰 segment。每个 segment 都要有 `segment_index`、`time_range`、`title`、`dialogue_summary`、`action_plan`、`expression_plan`、`supporting_visuals`。
- E 底部规则区：放声色参考说明、灯光风格、摄影规则、禁止换脸、禁止多人物、禁止字幕水印、禁止复刻制作板排版。

`StoryOverviewBoardSpec` 建议结构：

```json
{
  "board_type": "story_overview_board",
  "target_type": "talking_head_story_overview_board",
  "project_title": "1分钟讲清一个主题",
  "total_duration_sec": 60,
  "segment_duration_sec": 15,
  "segment_count": 4,
  "aspect_ratio": "21:9",
  "layout_language": "zh-CN",
  "host_reference_assets": [
    "asset://asset-20260506200638-6g86k",
    "asset://asset-20260506200638-5pf4j",
    "asset://asset-20260506200636-lmt8b"
  ],
  "audio_reference_assets": [
    "asset://asset-20260506202002-hhmgk",
    "asset://asset-20260506202001-fg589",
    "asset://asset-20260506202001-hl2kx"
  ],
  "top_bar": {
    "title": "...",
    "format": "单人口播",
    "duration_label": "60 秒 / 4 段 / 每段 15 秒",
    "style": "..."
  },
  "host_panel": {
    "identity_rule": "三张参考图是同一人，只锁脸和气质，不锁服装",
    "wardrobe_rule": "服装由故事场景决定"
  },
  "set_panel": {
    "location": "...",
    "props": [],
    "lighting": "...",
    "camera_plan": "..."
  },
  "segments": [
    {
      "segment_index": 1,
      "time_range": "0-15s",
      "title": "...",
      "dialogue": "...",
      "action_plan": "...",
      "expression_plan": "...",
      "supporting_visuals": []
    }
  ],
  "bottom_rules": {
    "audio_rule": "参考音频只参考声色，不承载对白",
    "negative_rules": []
  }
}
```

故事大图生图 prompt 必须由 LLM 生成，但 LLM 的任务是“编译”，不是自由发挥。输入必须包含 `TalkingHeadBrief`、`SegmentScript[]`、固定人物参考资产、固定音频参考资产、画幅规格、可见文字语言和禁止项。输出必须是面向图片模型的完整生图提示词。

故事大图生成后，它在视频阶段作为 `图片4` 使用：视频 prompt 每次都必须说明当前 shot 只读取故事大图中的一个 segment 区域，不读取其他 segment，也不要把故事大图的排版、标题和文字直接生成进视频画面。

### 8.6 两张示例图对链路的校验结论

从你当前生成的两张图看，方向是对的，但数据契约还需要收紧：

- 全局故事大图验证了 60 秒 / 4 segment 统一承载的可行性：它能把同一主持人、同一场景、同一色彩、同一声色和机位语言固定下来。
- 全局故事大图可以进入当前验证主线，但必须有固定分区和明确读取规则，不能让视频模型自由猜当前段落。
- 单段图仍有价值：如果故事大图复用导致串段、读错段落或复刻版式，可以作为回退方案。
- 当前示例图仍有大量英文版面，后续 prompt 必须把可见文字中文化作为硬约束，英文只保留少量镜头术语。
- 单段图的微镜头数量可以按 4 到 6 个起步，不必机械固定 8 个；关键是每个微镜头必须绑定 `time_range + dialogue_part + visual_focus + camera_motion`。
- 生图前必须先有 `StoryOverviewBoardSpec`，否则模型会把全局图的版式、文字和段落混合成不可追溯的视觉结果。

### 8.7 无 TTS 的声色参考链路

当前口播链路不再把 TTS 作为主链路，也不再先生成逐字口播音频。已完成的脚本测试证明，更自然的策略是：让 Seedance 读取固定 `reference_audio` 的声色，同时由 LLM 在视频 prompt 中明确写出台词、分时间段说话方式、情绪、表情和动作。

拍板结论：

- 不生成 `segment_voiceover_audio`。
- 不登记 `VoiceProfile`、`SegmentVoiceoverAsset`，不调用 CosyVoice 作为当前主链路。
- 不把参考音频当作逐字对白轨，也不把参考音频当作口型硬约束。
- 台词、说话节奏、停顿倾向、情绪和动作全部由 LLM 写进 Seedance 视频提示词。
- 固定 3 个音频 asset 只作为声色参考，由 env/config 读取并传入 Seedance `content[*].role=reference_audio`。

当前推荐链路：

```text
ProjectSpec
  -> TalkingHeadBrief
  -> SegmentScript
  -> StoryOverviewBoardSpec / SegmentProductionBoardSpec
  -> LLM 编译故事大图生图提示词
  -> 图片模型生成故事大图资产
  -> LLM 编译每个 15 秒 shot 的 Seedance 视频提示词
  -> Seedance content = text prompt + 固定人物 reference_image + 故事大图 reference_image + 固定声色 reference_audio
  -> clip
  -> timeline / export
```

TTS 相关实验结论只作为历史验证记录保留在测试脚本层，不进入当前正式改造计划。后续如果某个 provider 明确支持“逐字音频驱动口型”，再作为独立能力重新设计，不在当前口播 Production Board 主链路里预留隐性依赖。

### 8.8 Seedance 参考音频提示词策略实测结论

当前 Seedance 多素材融合测试里，`reference_audio` 更适合先作为“音色 / 声线 / 年龄感 / 口音 / 说话气质”参考，而不是直接作为逐字对白音轨。

已验证的更优提示词写法：

- `reference_audio` 只提供角色声色，不承担台词内容。
- 视频对白、分时间段台词、情绪、停顿倾向和动作都写进 Seedance 文本 prompt。
- prompt 中明确写：“音频1是角色1的声音参考，只用于参考音色、声线质感、年龄感、口音和说话气质。不要把音频1当作原始对白音轨，不要照搬音频1里的具体内容、节奏或停顿。”
- 分时间段写法示例：`0-3 秒：角色1用音频1的成熟中文男声声线自然说：“……”`。
- 多角色场景可扩展为：角色1使用音频1的声色说指定台词，角色2使用音频2的声色说指定台词。

不推荐的写法：

- 不要只写“参考音频是当前 segment 的真实 TTS 口播音频，台词以参考音频为准”。
- 不要让视频模型把 `reference_audio` 理解成原始对白和口型硬约束。
- 不要把台词只藏在音频里，导致模型缺少文本级对白、情绪和动作规划。

原因：

- 把参考音频当逐字对白，会让模型更容易产生僵硬口型、僵硬停顿或对白效果变差。
- 把台词和情绪写进 prompt，让模型按当前镜头规划自行生成说话表现，同时只借用参考音频的声色，整体效果更自然。
- 该策略更适合当前“Production Board + 人像 reference_image + 声色 reference_audio”的口播生成实验。

### 8.9 固定人物 / 音频资产的 Seedance 提交契约

口播视频生成阶段的 Seedance `content` 不再是旧三宫格的“图片1 / 图片2 / 图片3 分别代表起始 / 中间 / 结尾”。新的素材语义是：

- `图片1-图片3`：固定人物参考资产，用于锁定同一人物脸部身份和人物气质。
- `图片4`：当前故事大图 / Production Board，用于读取场景、服装、道具、动作、shot 内容和当前 segment 台词策略。
- `音频1-音频3`：固定音频参考资产，用于锁定声色，不承载逐字对白。

正式请求体应按以下结构构造，所有 `role` 字段必须显式保留：

```json
{
  "content": [
    {
      "type": "text",
      "text": "<LLM 生成的当前 shot 视频提示词>"
    },
    {
      "type": "image_url",
      "image_url": {
        "url": "asset://asset-20260506200638-6g86k"
      },
      "role": "reference_image"
    },
    {
      "type": "image_url",
      "image_url": {
        "url": "asset://asset-20260506200638-5pf4j"
      },
      "role": "reference_image"
    },
    {
      "type": "image_url",
      "image_url": {
        "url": "asset://asset-20260506200636-lmt8b"
      },
      "role": "reference_image"
    },
    {
      "type": "image_url",
      "image_url": {
        "url": "<当前故事大图或 Production Board 的 asset:// 或签名 URL>"
      },
      "role": "reference_image"
    },
    {
      "type": "audio_url",
      "audio_url": {
        "url": "asset://asset-20260506202002-hhmgk"
      },
      "role": "reference_audio"
    },
    {
      "type": "audio_url",
      "audio_url": {
        "url": "asset://asset-20260506202001-fg589"
      },
      "role": "reference_audio"
    },
    {
      "type": "audio_url",
      "audio_url": {
        "url": "asset://asset-20260506202001-hl2kx"
      },
      "role": "reference_audio"
    }
  ]
}
```

如果后续需要加入动作参考视频，也遵循同一 content 结构：

```json
{
  "type": "video_url",
  "video_url": {
    "url": "asset://<asset ID>"
  },
  "role": "reference_video"
}
```

后端实现要求：

- 固定人物资产和固定音频资产必须从 env/config 读取，不写死在 `SeedanceAdapter`、prompt 模板或脚本里。
- `SeedanceAdapter` 需要支持 `reference_image_urls`、`reference_audio_urls`、后续可选 `reference_video_urls` 的统一 content 序列化。
- 旧三宫格 `multi_image_fusion` 里“必须 3 张图”的校验不能直接套到口播链路；口播链路是多模态参考输入，不是起始 / 中间 / 结尾三图。
- 对 `asset://` 资产和签名公网 URL 都要兼容；当前测试证明签名 URL 可以工作，后续如果 provider 支持 asset 资产，则优先使用已上传的 `asset://`，减少临时公网 URL 失效风险。

## 9. Production Board 生图提示词模板

后续可新增 `compile_production_board_prompt.md`。

当前保留两类图，但当前验证主链路以 `Story Overview Board` 作为生图主产物：

- `Story Overview Board`：一张图描述完整 1 分钟 / 4 个 15 秒 segment，是当前 60 秒口播验证主线的故事大图资产，也是后续 4 个 Seedance shot 共同复用的参考图。
- `Segment Production Board`：一张图只描述一个 15 秒 segment，作为故事大图读取不稳定时的备选回退形态，不是当前主线。

无论哪种模板，Production Board 中的可见文字默认全部使用中文。除非是必要专业词汇或模型更稳定识别的镜头术语，例如 `push-in`、`close-up`、`macro`、`BGM`、`Seedance`，否则不要使用英文。

Production Board 生图提示词还必须接入固定人物参考资产：

- `data/person_pic` 中的 3 张人物图 / 对应远端 asset 是生图阶段的固定人物参考链。
- 生图 prompt 必须说明：参考图里的 3 个造型都是同一人物，不是 3 个角色。
- 生图 prompt 必须锁定脸部身份、年龄感、气质和基础身形。
- 生图 prompt 不应强行复刻参考图服装；服装、颜色和造型可以由当前 segment 场景、栏目风格和故事大图设计决定。
- 若当前 segment 需要特定场景着装，则以 `SegmentProductionBoardSpec.host_panel.styling_notes` 为准，同时保持参考人物的脸不变。

### 9.0 LLM 生图提示词编译契约

故事大图 / Production Board 不是由代码拼接固定 prompt 生成，也不是让图片模型直接读用户原始需求自由发挥。正确方式是新增一个 LLM 编译边界：

```text
StoryOverviewBoardSpec 或 SegmentProductionBoardSpec
  -> compile_story_board_image_prompt.md
  -> LLM 输出 image_positive_prompt / image_negative_prompt / image_params / source_trace
  -> image provider 生成故事大图资产
```

LLM 生图提示词编译器的输入：

- `project_spec`：用户主题、目标平台、总时长、画幅、风格偏好。
- `talking_head_brief`：主持人、场景、声音、灯光、摄影、全局内容弧线。
- `segment_scripts`：4 个 15 秒段落的标题、台词、动作、表情和辅助视觉。
- `host_reference_assets`：固定 3 张人物参考图。
- `audio_reference_assets`：固定 3 个声色参考音频，只写入声音说明，不要求图片模型生成声音。
- `board_layout_spec`：故事大图固定区域布局。
- `negative_rules`：禁止换脸、多人物、水印、英文大段排版、真实品牌 logo、医疗承诺等。

LLM 生图提示词编译器的输出必须是 JSON：

```json
{
  "image_positive_prompt": "面向图片模型的完整中文生图提示词",
  "image_negative_prompt": "负向提示词",
  "image_params": {
    "aspect_ratio": "21:9",
    "resolution": "2K",
    "board_type": "talking_head_story_overview_board",
    "visible_text_language": "zh-CN"
  },
  "layout_reading_map": {
    "A_top_bar": "项目标题、总时长、4段结构、主题风格",
    "B_host_panel": "同一人物参考，不是多人",
    "C_set_panel": "统一场景、灯光、机位和道具",
    "D_segment_grid": "4个15秒段落，每段独立边界",
    "E_bottom_rules": "声色、灯光、摄影和禁止项"
  },
  "source_trace": {
    "brief_version_id": "...",
    "segment_script_version_id": "...",
    "host_reference_assets": [],
    "audio_reference_assets": []
  }
}
```

`image_positive_prompt` 必须明确写出：

- 这是一张“中文口播故事大图 / Production Board”，不是最终视频帧。
- 故事大图分为固定区域：顶部项目栏、人物参考区、场景机位区、四段故事区、底部规则区。
- 四段故事区必须清晰分隔，每段对应一个 15 秒 shot。
- 可见文字默认中文，英文只允许少量专业镜头词。
- 固定人物参考图是同一人，不是多人。
- 人物参考锁脸和气质，不锁服装；服装由故事大图中的场景设定决定。
- 音频参考只用于声色说明，不在图里生成音频内容。

禁止把 `compile_story_board_image_prompt.md` 写成一个固定长模板后由代码填空就结束。LLM 必须根据用户主题和 4 个 segment 的真实内容生成具体的故事大图提示词，例如每段的台词摘要、表情、动作、辅助视觉都要不同。

### 9.1 Segment Production Board：单段 15 秒回退模板

该模板只服务于“故事大图复用失败后的回退方案”。当前主线不优先生成 4 张单段 Production Board；当前主线应优先使用 9.2 的 `Story Overview Board` 模板生成一张 60 秒故事大图。

单段回退模板可以继续使用更常规的横向 `16:9` 制作板画幅；这不影响当前主线故事大图默认 `21:9` 的拍板结论。

核心变量：

```text
{{ project_title }}
{{ segment_index }}
{{ total_segments }}
{{ segment_duration_sec }}
{{ topic }}
{{ segment_goal }}
{{ host_character_profile }}
{{ host_reference_assets }}
{{ set_design_profile }}
{{ color_palette }}
{{ full_voiceover_script }}
{{ micro_shots }}
{{ product_visuals }}
{{ audio_tone }}
{{ cinematography_notes }}
```

模板草案：

```text
创建一张电影级口播制作板，横向 16:9，大尺寸高清，专业导演前期制作指南风格。
这是一个 15 秒中文科普口播视频段落，不是普通剧情短片。

制作板里的所有可见文字默认使用中文：顶部栏、分区标题、镜头说明、台词摘录、音频说明、摄影说明、禁止事项都要中文表达。只有必要的专业镜头词汇或模型识别更稳定的词汇可以保留英文，例如 push-in、close-up、macro、BGM。

顶部栏展示项目标题、段落编号、时长、格式、核心观点、色彩基调。
左侧展示固定主角参考：正面、侧面、近景、自然口播姿态、服装配饰。
中部展示统一讲解场景：护肤讲解台、产品摆放、背景灯光、主机位和辅助机位图。
下方展示 6-8 个按时间顺序编号的微镜头故事板，每格包含景别、镜头运动、动作、情绪、对应口播台词。
底部展示灯光风格、情绪关键词、音频声调、摄影规则。

必须保留本段完整口播台词：
「{{ full_voiceover_script }}」

固定主角必须与参考人物一致，禁止换脸、换发型、换服装、换年龄感。
整体像专业商业广告/科普口播视频的 production board，排版清晰、统一、电影化。
```

### 9.2 Story Overview Board：60 秒故事大图模板

该模板用于生成一张完整 60 秒视频的故事大图。它是当前 60 秒口播验证主线的图片资产，不再只是审核图或旁路实验。

它同时承担三件事：

- 给用户和系统查看完整 60 秒创意方向是否一致。
- 作为图片阶段的正式故事大图资产。
- 作为后续 4 个 15 秒 Seedance shot 的共享参考图。

风险：

- 图内信息密度高，模型可能读错段落或混合多个段落。
- 图内有 4 段台词，视频生成时可能出现台词串段。
- 模型可能复刻全局制作板排版，而不是生成真实口播视频。

应对：

- 故事大图必须有清晰的 4 个 segment 区域边界。
- 每个视频 prompt 必须显式写明只读取哪个 segment。
- 视频 prompt 必须禁止复刻故事大图的网格、标题栏、文字说明和导演板版式。

核心变量：

```text
{{ project_title }}
{{ total_duration_sec }}
{{ segment_count }}
{{ segment_duration_sec }}
{{ global_topic }}
{{ host_character_profile }}
{{ host_reference_assets }}
{{ set_design_profile }}
{{ color_palette }}
{{ global_audio_tone }}
{{ global_cinematography_notes }}
{{ segment_1 }}
{{ segment_2 }}
{{ segment_3 }}
{{ segment_4 }}
```

模板草案：

```text
创建一张电影级中文口播科普视频全局导演制作板，横向超宽 21:9，超高清，专业前期视觉规划表风格。
这张图描述完整 1 分钟视频，包含 4 个 15 秒段落。它不是最终视频画面，而是当前口播链路的 Story Overview Board：既用于人工审核全局创意方向，也作为后续 4 个 Seedance shot 共同复用的故事大图参考资产。

制作板里的所有可见文字默认使用中文：顶部栏、分区标题、镜头说明、台词摘录、音频说明、摄影说明、禁止事项都要中文表达。只有必要专业词汇可以保留英文，例如 push-in、close-up、macro、BGM、Seedance。

顶部栏展示全局创意方向：
项目标题、视频形式、内容类型、总时长、结构、主角、场景、色彩基调、通用背景。

左侧展示主角身份与造型锁定：
展示同一主角或占位主角的多个口播状态，包括正面中近景、三分之二侧身、近景、手势讲解、坐在桌前、自然亲和姿态。
如果采用模型输入版，应避免生成可识别真人脸，使用无五官占位脸或轮廓脸，并说明真正人脸身份由授权人像素材提供。

中上区域展示环境与场景设计锁定：
统一口播场景、桌面产品、背景灯光、产品摆放、机位图和动作路线。

中部主区域清晰分成 4 个 segment：
Segment 1：0-15 秒，包含本段标题、目标、4 个微镜头、每个微镜头的时间、景别、运镜、动作、台词提示。
Segment 2：15-30 秒，包含本段标题、目标、4 个微镜头、每个微镜头的时间、景别、运镜、动作、台词提示。
Segment 3：30-45 秒，包含本段标题、目标、4 个微镜头、每个微镜头的时间、景别、运镜、动作、台词提示。
Segment 4：45-60 秒，包含本段标题、目标、4 个微镜头、每个微镜头的时间、景别、运镜、动作、台词提示。

四个 segment 区域必须有清晰边界、明显编号和独立台词区。不要让不同 segment 的台词、画面和辅助视觉混在一起。

底部展示全局灯光、情绪、音频和摄影语言：
柔和主光、暖色背景灯、干净产品质感、舒适对比、声音风格、语速、BGM、环境声、镜头选择、运镜风格和后期处理。

全局一致性要求：
四个 segment 里的主角、服装、场景、桌面、灯光、产品摆放、色彩和摄影语言保持统一。每个 segment 只改变台词重点、手势、辅助图示和产品特写角度。

禁止：
不要生成最终视频画面。不要把四个 segment 混在同一个故事板格子里。不要让一个画面覆盖所有 60 秒。不要水印，不要品牌 logo，不要低质量排版。
```

## 10. Seedance 视频提示词模板

Seedance 视频提示词在口播链路中必须按 15 秒 shot 编译：每个 15 秒 segment 生成一条独立 prompt，提交一次 Seedance 任务，最终由 timeline 合成为完整视频。这里的 15 秒是生成和拼接边界，不等于 15 秒内必须从第一秒说到最后一秒；开场动画、环境建立、产品特写、停顿、表情反应和对白分布都应由前置创意和剧本节奏决定。

提示词生成的共同骨架保持稳定：

- 固定人物参考资产不变。
- 固定音频参考资产不变。
- 故事大图 / Production Board 引用方式不变。
- 画幅、时长、清晰度、水印、是否生成音频等 provider 参数不变。
- 变化的只有当前 shot 的段落编号、读取区域、台词、动作、表情、辅助视觉和时间轴。

LLM 编译视频 prompt 时必须明确：它每次看到的可能是同一张故事大图 / Production Board URL，但当前 shot 只读取指定 segment 的内容。例如 60 秒视频复用一张 4 段故事大图时：

- shot1 只读取图中的 Segment 1 / 0-15s 区域。
- shot2 只读取图中的 Segment 2 / 15-30s 区域。
- shot3 只读取图中的 Segment 3 / 30-45s 区域。
- shot4 只读取图中的 Segment 4 / 45-60s 区域。

当前实现采用“故事大图复用多个 clip”的策略，prompt 必须带上明确的 `board_segment_reading_instruction`，告诉模型只读取当前 shot 对应区域。该策略是当前验证主线，不是旧三宫格语义，也不是让模型自由从全图猜内容。

如果后续实测故事大图读取不稳定，再评估是否回退为单段 Production Board。回退时每个 clip 使用当前 segment 的 15 秒 `Segment Production Board`，但这属于备选策略，不是当前主线。

### 10.0 视频呈现方式固定为专家知识口播

当前阶段先固定视频呈现方式为 `expert_explainer_talking_head`。这里固定的是最终视频的表达语言，不是固定故事大图结构，也不是固定输出画幅。

故事大图 / Production Board 的角色不变：

- 它仍然是故事资产和内容资产，负责提供段落编号、台词重点、场景、产品、辅助视觉、动作和讲解逻辑。
- 它不是最终视频画面，也不决定最终视频版式。
- 它不决定输出比例；`ratio`、`duration`、`resolution`、`watermark`、`generate_audio` 等仍由 Seedance provider 参数控制。
- 视频生成只从故事大图中读取当前 shot 的内容，而不是复刻整张大图的版式、网格、标题、文字说明或导演板布局。

最终视频目标形态：

- 单人专家知识口播，而不是电影广告片、剧情短片或导演板复刻。
- 固定机位或轻微推近，中近景为主，人物面对镜头自然讲解。
- 场景稳定：桌前讲解、暖色室内、桌面产品和示意卡辅助。
- 节奏主要来自开场动画、手势、表情、轻微镜头变化、产品特写、皮肤/成分/机制示意图插入和自然停顿。
- 当前默认纯净无字幕画面，不生成字幕、标题栏、文字贴片或水印。
- 人物表演应自然、可信、像专家解释给普通用户听，不要夸张广告腔或影视表演腔。

视频 prompt 的写法必须把“呈现方式”和“内容读取”分开：

```text
图片4是故事大图 / Production Board，只用于读取当前 shot 的内容、场景、产品、辅助视觉和讲解计划。
最终视频呈现为单人专家知识口播：固定机位，中近景为主，角色面对镜头自然讲解，辅以开场动画、产品/皮肤/机制示意图和自然停顿。
输出比例由本次 Seedance 参数决定，不由故事大图版式决定。
不要复刻故事大图的网格、标题栏、文字说明、分栏页面或导演板排版。
不要生成字幕、标题栏、文字贴片或水印。
```

字幕策略当前已拍板：暂时不做字幕。视频 prompt 和 negative prompt 都要明确要求纯净无字幕画面；字幕能力如果未来需要，再作为单独的视频呈现层配置重新设计，不混入口播主链路。

模板必须包含两部分：

1. Reference Board Reading Map
2. Segment Video Timeline

### 10.0.1 LLM 视频提示词编译契约

Seedance 视频提示词也必须由 LLM 编译，不能由代码用固定字符串拼接。代码只负责收集上下文、渲染编译模板、调用 LLM、校验 JSON、传递参数。

```text
StoryOverviewBoard asset / SegmentProductionBoard asset
  + 当前 shot_index
  + SegmentScript 当前段台词和动作
  + 固定人物 reference_image assets
  + 固定声色 reference_audio assets
  -> compile_talking_head_video_prompt.md
  -> LLM 输出 Seedance video prompt bundle
  -> SeedanceAdapter 构造 content 并提交
```

LLM 视频提示词编译器输入：

- `story_board_url`：故事大图 / Production Board URL。
- `shot_index`：当前第几个 15 秒 shot，从 1 开始。
- `segment_time_range`：例如 `15-30s`。
- `segment_script`：当前段标题、完整台词、动作、表情、辅助视觉和禁止项。
- `board_layout_reading_map`：故事大图区域说明。
- `host_reference_assets`：固定人物资产。
- `audio_reference_assets`：固定声色资产。
- `provider_profile`：Seedance 模型、时长、画幅、角色字段要求。

LLM 视频提示词编译器输出必须是 JSON：

```json
{
  "positive_prompt": "面向 Seedance 的完整视频提示词",
  "negative_prompt": "不要生成制作板页面、字幕、水印、标题栏、文字贴片、多人物、换脸、错误服装等",
  "board_segment_reading_instruction": "只读取故事大图中 Segment 2 / 15-30s 区域",
  "dialogue_script": "当前 15 秒段落计划说出的台词；允许根据剧本节奏保留开场动画、停顿或无对白片段",
  "timeline": [
    {
      "time_range": "0-3s",
      "dialogue": "...",
      "action": "...",
      "expression": "...",
      "camera": "..."
    }
  ],
  "params": {
    "duration_sec": 15,
    "ratio": "adaptive",
    "generate_audio": true,
    "watermark": true
  }
}
```

`positive_prompt` 必须明确包含：

- 当前视频是 15 秒真实口播视频，不是 Production Board 页面。
- 当前视频呈现方式是单人专家知识口播，不是电影广告片、剧情短片或导演板复刻。
- 图片1-图片3是同一人物参考图，只锁脸和气质。
- 图片4是故事大图 / Production Board，只读取当前 shot 对应 segment 区域。
- 故事大图只提供内容、场景、产品、辅助视觉和讲解计划，不决定最终视频比例或版式。
- 服装、颜色、道具和场景以图片4中当前 segment 的故事设计为主。
- 音频1-音频3只参考声色，不承载对白，不照搬节奏。
- 当前段台词、开场动画、停顿和无对白片段都要写在 prompt 中，并按时间段拆分。
- 每个时间段都要写明表情、动作、镜头和辅助视觉。
- 当前默认不生成字幕、标题栏、文字贴片或水印。

LLM 不允许输出泛泛描述，例如“根据图中第二段生成视频”。它必须把“第二段里具体讲什么、人物怎么说、表情怎么变、镜头怎么动、辅助视觉怎么出现”写进 `positive_prompt`。

### 10.0 固定人物与声色引用规则

视频 prompt 必须包含以下固定说明：

```text
图片1、图片2、图片3是同一位角色的固定人物参考图，只用于保持人物脸部身份、年龄感、五官气质和基础身形一致。不要把图片1-3理解成三位不同角色。

图片4是当前故事大图 / Production Board，用于读取当前 shot 的场景、服装、动作、表情、道具、构图和台词内容。角色脸部必须保持图片1-3一致，但当前视频中的服装、颜色和造型以图片4中的故事大图为主。

音频1、音频2、音频3是同一角色或同一声色体系的参考音频，只用于参考音色、声线质感、年龄感、口音和说话气质。不要把音频1-3当作原始对白音轨，不要照搬音频里的具体内容、节奏或停顿。
```

若后续出现多角色口播，可扩展为：角色1使用音频1声色、角色2使用音频2声色、角色3使用音频3声色。但当前单人口播默认将 3 个音频作为同一主角声色体系的稳定参考。

### 10.1 Reference Board Reading Map

单段图固定模板：

```text
参考图是一张当前 15 秒 segment 的 production board，不是完整 1 分钟视频总览，也不是最终视频画面。
请只读取其中的人物、场景、镜头计划、灯光、音频和台词信息。
不要生成网格、标题栏、文字说明、平面图、编号标签或制作板排版。

参考图读取规则：
- 左上角或左侧「Character / Host Reference」区域：只用于锁定主角外貌、发型、服装、妆容、表情气质，不要生成该区域的网格排版。
- 中上部「Environment / Set Design」区域：用于锁定口播场景、桌面、背景灯光和产品摆放，不要生成平面图或标注文字。
- 中部「Storyboard」区域：用于理解本段 15 秒视频的镜头顺序、景别、动作和情绪变化。
- 下方「Lighting / Mood / Audio / Cinematography」区域：用于锁定灯光、色彩、音频语气和摄影风格，不要生成这些文字说明。
```

### 10.2 Segment Video Timeline

单段图示例模板：

```text
生成一个 15 秒中文口播科普视频。
参考图是一张当前 15 秒 segment 的 production board，只作为人物、场景、镜头计划、灯光和视觉风格参考。
不要生成 production board 页面，不要生成网格排版，不要生成文字标题，不要生成分栏页面。

画面必须是一个真实口播视频：
固定主角坐或站在统一护肤讲解场景中，面对镜头讲解。
保持与参考图中主角一致的人物身份、发型、服装、妆容、年龄感和表情气质。
保持同一场景、同一灯光、同一桌面产品摆放。

0-3s：
参考图中部 Storyboard 的第 1 格。
生成真实视频画面：中近景，主角位于画面中央偏左，看向镜头，引出本段主题。
背景使用参考图中上部 Environment / Set Design 的统一讲解场景。

3-7s：
参考图中部 Storyboard 的第 2-3 格。
轻微 push-in，主角保持同一外貌和服装，用手势解释核心概念。
产品或成分辅助视觉出现在画面右侧，但不要变成网页 UI 或文字卡片。

7-11s：
参考图中部 Storyboard 的第 4-5 格。
切到同一场景内的产品/成分特写或手部示意，镜头可以是 close-up / macro。
桌面、灯光和产品摆放必须来自参考图中上部 Environment 区域。

11-15s：
参考图中部 Storyboard 的第 6-8 格。
回到主角中近景，主角看向镜头总结本段观点，表情专业亲和。
保持同一场景、同一灯光、同一声音。

口播台词按剧本计划表达，不要求 15 秒全程说话；允许开场动画、停顿、产品特写或无对白片段：
「{{ full_voiceover_script }}」

声音：
同一主角声音，中文自然口播，语速中等，专业亲和。
背景音乐轻柔干净，音量低，不压过人声。

禁止：
不要生成 production board 页面，不要生成文字水印，不要多人物，不要换脸，不要换服装，不要跳到新场景，不要夸张表演。
```

## 11. 口播链路的替换边界

口播类视频的工程阶段仍然保持：

```text
需求 -> brief -> script -> image -> video -> timeline -> export
```

但这些阶段里的领域语义必须整体采用口播 Production Board 语义：

```text
TalkingHeadBrief
SegmentScript
Story Overview Board
talking_head video prompt
```

这里不是两条链路并存，也不是按失败情况在三宫格和 Production Board 之间回退。对当前口播类项目来说，Story Overview Board 是当前验证主线的图片中间产物：

- 不再为口播项目生成 `1x3_triptych`。
- 不再把 `NarrativeScript.shots` 当作口播主结构。
- 不再把 `ShotPlan` 的三段起承转合运动语义套到口播 segment 上。
- 不再让口播视频 prompt 读取三宫格 cell 或三图融合语义。
- 不再在前端给用户暴露“三宫格 / Production Board”二选一，避免功能路径混乱。

后续实现时可以复用底层工程能力，例如任务调度、资产持久化、provider 调用、clip 记录、timeline 合成和导出服务；但复用的是基础设施，不是复用旧三宫格领域模型。凡是进入口播项目的创作字段、PromptBundle target_type、前端展示和反馈入口，都必须以 `talking_head_production_board` 为准。

### 11.1 前端输入和产物展示调整

前端入口需要做两类调整：

- 创建 / 配置口播类项目时，总时长只允许选择 15 秒倍数。推荐用下拉或分段按钮提供 `15s / 30s / 45s / 60s / 75s / 90s`，不要让用户自由输入任意秒数后再由后端猜测分段。
- 前端传给后端的 `target_duration_sec` 必须已经是 15 的整数倍，同时带上 `segment_duration_sec=15` 或等价配置，保证后续 LLM 规划、shot 生成、视频生成和 timeline 都知道 15 秒是 clip 边界。

产物展示上，口播链路与现有视频产物展示大体一致，差异主要在图片产物：

- 图片阶段不再展示三宫格 / triptych，而展示 `Production Board` 或故事大图。
- 视频阶段仍展示每个 shot/clip 的生成状态、视频预览、失败原因和重试入口。
- timeline / export 阶段仍按已有视频合成产物展示，不需要因为口播链路单独设计一套全新视频展示结构。
- 如果未来提供“同一故事大图生成 4 个 shot”的调试视图，前端应能标注当前 clip 对应读取的是第几个 segment 区域，避免用户误以为每个 shot 都有不同参考图。

## 12. 设计风险

### 12.1 Seedance 误把制作板当最终画面

风险：如果直接把完整故事大图 / Production Board 作为参考图，视频模型可能生成带网格、标题、文字说明的画面。

应对：

- 在视频 prompt 中加入 Reference Board Reading Map。
- 明确禁止生成 board 页面、网格、文字、编号和平面图。
- 后续可考虑从 Production Board 中再派生一张 clean hero frame 作为真正的视频视觉参考。

### 12.1.1 一张故事大图复用生成多个 clip 的风险

当前主线是生成一张 1 分钟故事大图，然后让视频模型每次只读取其中一个 segment。

这个方案的风险：

- 一张图承载 1 分钟信息，文字和分区太多，模型读取压力更大。
- 生成第 2、3、4 段时，模型可能误读第 1 段或混合多个段落。
- 同一参考图里有 4 段不同台词和不同辅助视觉，容易造成台词错配。
- 视频模型可能更倾向复刻总览版式，而不是生成真实口播画面。

当前应对策略：

```text
Story Overview Board -> shot1 只读 Segment 1 -> clip1
Story Overview Board -> shot2 只读 Segment 2 -> clip2
Story Overview Board -> shot3 只读 Segment 3 -> clip3
Story Overview Board -> shot4 只读 Segment 4 -> clip4
```

每个 shot 的视频 prompt 必须包含 `board_segment_reading_instruction`，并在正向 prompt 中写清当前只读取哪一个 segment。如果 60 秒样例实测仍出现严重串段，再回退评估 `Segment Production Board -> Segment clip`。

### 12.2 台词可控性

风险：如果把每个 15 秒 shot 理解成“必须 15 秒全程说话”，视频会变得机械，尤其开头 shot 通常需要环境建立、开场动画、人物入镜或产品露出；如果台词过长，模型也可能不能严格逐字朗读全部内容。

应对：

- SegmentScript 阶段控制每段字数，同时允许 `opening_visual`、`silent_beat`、`product_insert`、`reaction_pause` 等非对白节奏。
- 每段保留 `voiceover_script`、`spoken_duration_estimate_sec` 和 `speech_timing_plan`。
- LLM 编译视频 prompt 时必须把计划说出的台词写入 `dialogue_script`，并拆成 0-3s、3-7s、7-11s、11-15s 等时间段；某些时间段可以是开场动画、产品特写、停顿或无对白动作。
- 每个时间段必须同时写出“是否说话、说什么、用什么情绪说、人物有什么表情和动作、镜头如何运动”。
- `reference_audio` 只作为声色参考，不能把参考音频当逐字对白轨或口型硬约束。
- 如果台词过长，回到 SegmentScript 阶段压缩文案，不通过额外逐字音频轨修正。

### 12.2.1 声色参考资产与授权风险

风险：固定参考音频资产用于声色参考，如果缺少授权和资产边界，会带来声音身份滥用风险；如果把参考音频误当对白轨，也会造成生成策略混乱。

应对：

- 固定参考音频必须作为受控资产登记，资产类型建议为 `audio_voice_reference` 或 `reference_audio`。
- 资产元数据必须记录 owner_user_id、source、consent_status、provider_asset_id、status。
- 当前默认 3 个音频 asset 从 `TALKING_HEAD_REFERENCE_AUDIO_ASSETS` 读取，不在 prompt 或代码里硬编码。
- 视频提示词必须写清：参考音频只用于音色、声线、年龄感、口音和说话气质，不承载台词内容。
- 删除、停用或替换参考音频资产时，后续新视频任务必须读取新的配置，不继续使用旧 asset。

### 12.3 人物一致性

风险：Production Board 内有多角度角色图，视频模型可能混淆为多个人。

应对：

- prompt 明确“这是同一主角的多角度参考，不是多人”。
- 固定使用用户提供的人物角色资产。
- 每段 board 和 video prompt 都继承 Host Lock。

### 12.4 场景一致性

风险：每段 board 生图可能重绘出不同讲解场景。

应对：

- 创意阶段生成 Set Lock。
- 每段 board prompt 复用同一 set_design_profile。
- 后续可固定场景参考图作为额外 reference asset。

### 12.5 画幅选择

故事大图当前默认画幅固定为 `21:9`。它作为“总览制作板”使用，需要承载 60 秒 / 4 segment 的全局信息，超宽画幅更利于横向排布：

- 顶部共享创意栏
- 左侧角色参考
- 中部场景与机位图
- 下方故事板、音频和摄影说明

这里固定的是故事大图资产画幅，不是最终视频画幅。最终视频的 `ratio` 仍由 Seedance provider 参数和项目输出配置控制，不能因为故事大图是 `21:9` 就把最终视频也强制成 `21:9`。

选择画幅时要看三件事：

1. 是否要塞下大量文字、多个角色参考、多栏布局。
2. 是否要把这张图作为导演板长期阅读，而不是只作为模型参考。
3. 是否要让它同时服务人工审核、Story Overview Board 全局阅读和视频模型按 segment 定向读取。

因此当前拍板：

- `StoryOverviewBoardSpec.aspect_ratio` 默认使用 `21:9`。
- 生图 prompt 明确生成 21:9 中文故事大图 / 总览制作板。
- 视频 prompt 明确：故事大图只提供内容读取，不决定最终视频比例。
- 如果后续 Seedance 读取 21:9 故事大图不稳定，再讨论是否派生 clean hero frame 或回退单段 Production Board，而不是先把主线画幅改回待定。

## 13. 后续待深入讨论的问题

1. Story Overview Board 是否能稳定支撑 4 个 shot 复用读取，还是需要回退为每段一张 Segment Production Board。
2. 每个 15 秒 segment 的微镜头数量应固定为 6、8，还是根据台词节奏动态生成。
3. LLM 编译视频 prompt 时，中文台词长度、开场动画、无对白停顿和 15 秒口播自然度的校验规则如何量化。
4. 固定主角资产的数据结构如何设计：单图、组图、角色包还是 CharacterSetVersion 扩展。
5. 前端是否需要展示 Production Board 并允许用户对具体区域做反馈。
6. `talking_head_production_board` 作为新的 PromptBundle target_type 时，服务层、资产类型和前端展示如何完整贯通。
7. 项目入口如何识别口播类项目，并直接进入 Production Board 链路，避免用户在创作中途手动选择或混用三宫格。
8. 不同口播类型是否共用模板：护肤科普、产品讲解、知识教育、财经解读、法律科普等。
9. 是否需要从故事大图派生 clean hero frame，作为比 Production Board 更干净的视频参考图。

## 14. 建议实施顺序

1. 先把口播类视频总时长约束为 15 秒倍数：前端限制可选值，后端二次校验，LLM 规划按 `target_duration_sec / 15` 生成 segment / shot / clip 数量。
2. 新增固定人物参考资产配置：从 env/config 读取 `TALKING_HEAD_HOST_REFERENCE_IMAGE_ASSETS`，当前默认值为 `asset://asset-20260506200638-6g86k`、`asset://asset-20260506200638-5pf4j`、`asset://asset-20260506200636-lmt8b`。
3. 新增固定音频参考资产配置：从 env/config 读取 `TALKING_HEAD_REFERENCE_AUDIO_ASSETS`，当前默认值为 `asset://asset-20260506202002-hhmgk`、`asset://asset-20260506202001-fg589`、`asset://asset-20260506202001-hl2kx`。
4. 新增 Production Board / 故事大图生图提示词模板：生图阶段读取 `data/person_pic` 或配置资产作为人物参考链，锁脸不锁服装，服装和造型以当前故事场景为主。
5. 新增 talking head video prompt 编译模板：同一故事大图可以按 shot_index 读取不同 segment 区域；每条 prompt 明确当前只读取第几个 15 秒段落。
6. 改造 `SeedanceAdapter` 的 content 构造：支持 `reference_image_urls`、`reference_audio_urls`、后续可选 `reference_video_urls`，并为每个素材显式写入 `role=reference_image/reference_audio/reference_video`。
7. 调整口播 ClipService / VideoGenerationTool 参数传递：每个 15 秒 shot 使用同一组固定人物资产、同一组固定音频资产、当前故事大图 URL，只改变 LLM 生成的当前 shot prompt。
8. 固化参考音频提示词策略：音频只作为声色参考，台词、情绪、动作和分时间段说话内容全部写在 prompt 中。
9. 前端产物展示调整：图片阶段展示 Production Board / 故事大图，不再展示三宫格；视频、timeline、export 阶段沿用现有产物展示结构。
10. 小范围跑一个 60 秒 / 4 shot 样例，验证 15 秒倍数约束、同图多 shot 读取、固定人物资产、固定音频声色、clip 生成和 timeline 合成。
11. 根据样例质量决定是否需要把故事大图拆回单段 Production Board、是否需要 clean hero frame、以及是否需要更强的口播台词长度与节奏校验。

## 15. 当前结论

口播类视频的重构方向成立：不是推翻现有工程管线，而是在创意阶段开始，把普通分镜创作替换为 Story Overview Board / Production Board 驱动的口播段落创作。对当前口播类项目来说，Story Overview Board 是当前验证主线的图片中间产物；三宫格不再进入口播主线，单段 Production Board 只作为故事大图读取失败后的回退规格。

真正需要模板化的是三层：

- 生图模板：把项目主题、四段台词、人物、场景、镜头和声色说明设计成一张故事大图 / Production Board。
- 固定资产模板：人物参考资产、故事大图和参考音频资产按统一 content 结构传给 Seedance，资产 ID 从 env/config 读取。
- 视频模板：读取 Production Board / 故事大图中当前 15 秒 segment 的内容，把台词、开场动画、停顿、动作、表情和情绪写进 prompt，同时只把参考音频作为声色参考，而不是把音频当逐字对白轨。

后续讨论应围绕故事大图 / Production Board 的字段结构、参考图区域映射、台词长度与节奏控制、固定人物资产、固定声色参考资产、Seedance 实测行为，以及口播项目入口如何直接绑定 `talking_head_production_board` 继续收敛。

### 15.1 文档校准结论

根据脚本测试和当前讨论，本设计文档必须以以下结论为准：

- 已明确：当前验证主线是 `1 张 60s 故事大图 + 4 个 15s shot + 4 个 Seedance clip + timeline 拼接`，不是 4 张独立 Production Board。
- 已明确：总时长必须是 15 秒倍数，前端限制输入，后端二次校验，LLM 以 15 秒为 shot/segment 分界。
- 已明确：故事大图默认使用 `21:9`，最终视频比例仍由 provider 参数和输出配置控制。
- 已明确：当前主线不走 TTS。参考音频只作为 `reference_audio` 声色资产，台词、开场动画、停顿、情绪、动作和分时间段表达全部写进视频 prompt。
- 已明确：15 秒 shot 是生成边界，不是必须 15 秒全程说话；是否有开场动画、无对白停顿或产品特写，由创意和剧本节奏决定。
- 已明确：当前视频暂时不做字幕，prompt 默认要求纯净无字幕画面。
- 已明确：固定人物资产和固定音频资产都从 env/config 读取，Seedance `content` 必须显式写 `role=reference_image` / `role=reference_audio`。
- 已明确：LLM 同时负责故事大图生图 prompt 和每个 shot 的 Seedance 视频 prompt；代码只组装上下文、约束、资产和结构化输入，不硬编码最终创意文案。
- 未完全明确：同图复用 4 个 shot 的稳定性、中文台词长度阈值、15 秒内对白与非对白节奏比例、是否需要 clean hero frame。
- 已废弃：把 TTS 作为主链路前置步骤、把参考音频当对白轨、把三宫格作为口播主线、让视频模型自由猜故事大图当前段落。
