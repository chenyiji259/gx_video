# VidMuse 三宫格视频生成链路改造汇总

本文档记录本次围绕 `1.txt` 三个问题完成的实际代码改造、改造后的整体阶段链路，以及从需求输入到最终视频生成的数据传递关系。

## 一、我对需求的理解

本次不是单点把“九宫格”文案改成“三宫格”，而是一次从需求入口到视频生成的链路改造：

1. 创作规划阶段要从一开始就按 `1x3 三宫格` 组织内容。15 秒以下的视频默认是 1 个 shot、1 个 clip、1 张三宫格，三张图分别是起始 / 中间 / 结尾；15 秒以上的视频按单 clip 不超过 15 秒拆成多个连续 shot，每个 shot 对应 1 张三宫格和 1 个视频 clip。
2. 视频比例、清晰度、生图规格不能等到 ffmpeg 合成时再决定。它们必须从需求创建开始就由前端选择并进入 `ProjectSpec.output_config`，后续生图、视频生成、合成和导出都读取同一份规格，避免多个 clip 比例不一致。
3. 视频生成 prompt 的正文必须由 LLM 基于前置产物生成，而不是代码拼接。LLM 要读取 brief、style、narrative、shot plan、三宫格切分图描述、角色/场景/运动策略、输出规格，再按 Seedance 专业写法生成可执行视频导演提示词，然后交给视频生成 provider。

其中第 3 点是核心：代码只负责收集上下文、渲染编译模板、调用 LLM、校验 JSON、传递参数；视频 prompt 的专业正文必须由模型思考后生成。

## 二、对应问题与完成内容

### 问题 1：九宫格改成三宫格

已完成的代码链路：

- `backend/app/services/output_spec_service.py`
  - 新增统一输出规格和三宫格规划能力。
  - `plan_triptych_shots()` 按目标时长规划 `shot_count / grid_count / total_shots_generated / shot_durations_sec`。
  - 单 clip 时长被限制在 15 秒以内。
- `prompts/system/creative_planning.md`
  - 创意规划 system prompt 从“单张九宫格 / 3 shot”改为“1x3 三宫格 / 单 clip 不超过 15 秒”。
- `prompts/system/narrative_script.md`
  - 剧本生成从“1 张九宫格 3 行 3 shot”改为“每个 shot 对应 1 张 1x3 三宫格”。
- `backend/app/services/storyboard_service.py`
  - 每张 grid 只准备 3 个 cell。
  - 每张三宫格绑定 1 个 shot。
  - 切分产物从 9 张变成 3 张。
- `backend/app/tools/image_generation_tool.py`
  - `generate_nine_grid()` 继续保留旧函数名和 asset_type 兼容，但实际语义改为生成三宫格大图。
  - `split_and_persist_grid()` 改为横向切 3 张 cell。
- `backend/app/services/clip_service.py`
  - 视频生成阶段不再按九宫格行映射 `cell1-3 / cell4-6 / cell7-9`。
  - 新逻辑是 `grid_index N -> shot N -> cell1/cell2/cell3` 三图融合。

兼容说明：

- 数据库约束仍允许 `cell_position <= 9`，这是为了兼容已有九宫格历史数据，不代表新链路还会生成 9 个 cell。
- `nine_grid_image`、`compile_nine_grid_prompt()` 等名称暂时保留，是为了减少 schema 和旧调用方破坏；当前语义已经变成三宫格。

### 问题 2：从需求创建开始传递视频规格

已完成的代码链路：

- `ui_dev/src/components/Workspace.tsx`
  - 需求表单增加画幅比例选择：`9:16 / 16:9 / 1:1`。
  - 增加视频清晰度选择：`1080p / 720p / 480p`。
  - 需求提交时传递 `aspect_ratio / video_resolution / image_resolution`。
  - 工作台展示当前规格，避免用户不知道后续按什么规格生成。
- `ui_dev/src/api.ts`、`ui_dev/src/types.ts`
  - 补齐前端 API 类型和 `ProjectSpec.output_config` 字段。
- `backend/app/api/v1/project_spec.py`
  - `CreateSpecVersionRequest` 接收 `video_resolution`、`image_resolution`。
  - 创建需求版本时调用 `normalize_output_config()` 归一化输出规格。
- `backend/app/services/project_spec_service.py`
  - 落库前统一规范化 `output_config`。
- `backend/app/services/brief_persistence_service.py`
  - brief 生成前读取规范化后的规格和三宫格规划。
  - brief 落库时强制把规格写回 `creative_brief.extension`，包括：
    - `target_duration_sec`
    - `shot_count`
    - `grid_count`
    - `total_shots_generated`
    - `shot_durations_sec`
    - `max_clip_duration_sec`
    - `storyboard_layout`
    - `aspect_ratio`
    - `video_resolution`
    - `image_resolution`
    - `image_size`

生图规格修正：

- `9:16` 三宫格大图：`1728x1024`，切分后每张 cell 为 `576x1024`。
- `16:9` 三宫格大图：`3072x576`，切分后每张 cell 为 `1024x576`。
- `1:1` 三宫格大图：`3072x1024`，切分后每张 cell 为 `1024x1024`。

这样做的原因是：三宫格大图本身是横向 1 行 3 列，真正给 Seedance 的参考图是切分后的 cell。必须保证每个 cell 的宽高比等于目标视频比例，否则后续视频生成和 ffmpeg 合成会出现比例不一致、裁切或黑边问题。

### 问题 3：视频 prompt 必须由 LLM 基于前置产物生成

已完成的代码链路：

- `backend/app/services/prompt_compiler_service.py`
  - 视频目标使用 `compile_video_prompt` 模板调用 LLM。
  - `_call_llm()` 会传入：
    - `style_bible`
    - `character_set`
    - `shot_spec`
    - `audio_direction`
    - `provider_profile`
    - `reference_assets`
    - `generation_mode`
    - `start_frame_description`
    - `middle_frame_description`
    - `end_frame_description`
    - `output_spec`
  - LLM 返回的 JSON 中 `positive_prompt` 是真正交给视频模型的正文。
  - 代码只在 LLM 失败时走规则兜底，正常路径不是代码拼接视频 prompt。
- `prompts/compiler/compile_video_prompt.md`
  - 明确把角色改为 Seedance 视频视觉执行导演。
  - 引入输出规格硬约束，要求 LLM 不得自行改变 `aspect_ratio` 和 `resolution`。
  - 引入三图融合规则：`图片1` 起始帧、`图片2` 中间帧、`图片3` 结束帧。
  - 引入专业 Seedance 写法：
    - 技术参数前置
    - 明确引用图片1/2/3
    - 按实际 duration_sec 拆成 3 个时间戳段落
    - 使用具体运镜术语，如 push-in、tracking shot、dolly-in、pan、tilt、crane、handheld、rack focus、shallow depth of field、parallax
    - 强调连续镜头内部运动，不写 cut、montage、scene change
    - 描述主体动作、景深变化、光线变化、情绪递进
- `backend/app/services/clip_service.py`
  - 从 storyboard raw_payload 中按当前 shot 读取三张 cell 图 URL。
  - 将三张图作为 `reference_image_urls` 传给 prompt 编译和视频生成。
- `backend/app/tools/video_generation_tool.py`
  - 将 `duration_sec` 限制在 15 秒以内并交给 provider normalize。
  - 多图融合模式下透传 `reference_image_urls`。
- `backend/app/providers/video/seedance_adapter.py`
  - `multi_image_fusion` 模式要求 3 张参考图。
  - payload 中将三张图作为 `role=reference_image` 放入 content。
  - 传递 `ratio / duration / resolution` 给 Seedance。

这一链路解决的是“视频 prompt 正文必须让模型基于上游产物思考生成”的问题。代码编译器不再决定视频表达内容，它只构造上下文和硬约束；LLM 才负责把前置创意、剧本、镜头计划、三图状态和 Seedance 专业写法综合成 prompt。

## 三、改造后的完整阶段链路

### 阶段 1：前端需求输入

入口：

- `ui_dev/src/components/Workspace.tsx`

用户输入和选择：

- 用户视频需求正文 `user_prompt`
- 平台 `platform`
- 目标受众 `target_audience`
- 风格偏好 `style_preference`
- 是否真人入镜 `human_on_camera`
- 目标时长 `target_duration_sec`
- 画幅比例 `aspect_ratio`
- 视频清晰度 `video_resolution`
- 生图规格 `image_resolution`

提交到后端：

- `POST /api/v1/projects/{project_id}/spec/versions`

进入后端后：

- `backend/app/api/v1/project_spec.py`
- `backend/app/services/project_spec_service.py`
- `normalize_output_config()`

形成统一规格：

```json
{
  "target_duration_sec": 12,
  "aspect_ratio": "9:16",
  "video_resolution": "1080p",
  "image_resolution": "2K",
  "storyboard_layout": "1x3_triptych",
  "grid_columns": 3,
  "grid_rows": 1,
  "image_size": "1728x1024",
  "image_orientation": "landscape"
}
```

### 阶段 2：创意规划 creative brief

入口：

- `workflowApi.generateCreativePackage(projectId)`
- `BriefPersistenceService.generate_and_persist()`
- `CreativePlanningAgent.run_phase1()`

输入：

- `ProjectSpec.user_prompt`
- `ProjectSpec.output_config`
- 目标平台、受众、风格、真人入镜
- `plan_triptych_shots()` 生成的三宫格规划

输出：

- `CreativeBriefVersion`
- `StyleBibleVersion`

关键传递字段：

```json
{
  "extension": {
    "target_duration_sec": 12,
    "shot_count": 1,
    "grid_count": 1,
    "total_shots_generated": 1,
    "shot_durations_sec": [12],
    "allowed_shot_durations_sec": [4, 5, 6, 8, 10, 12, 15],
    "max_clip_duration_sec": 15,
    "storyboard_layout": "1x3_triptych",
    "aspect_ratio": "9:16",
    "video_resolution": "1080p",
    "image_resolution": "2K",
    "image_size": "1728x1024",
    "character_list": [],
    "target_platform": "douyin",
    "target_audience": "...",
    "visual_style": "...",
    "human_on_camera": false
  }
}
```

下游依赖：

- 剧本阶段读取 `total_shots_generated` 和角色/风格约束。
- storyboard 阶段读取 `grid_count / aspect_ratio / image_size`。
- 视频 prompt 编译阶段读取风格、角色、规格硬约束。

### 阶段 3：叙事剧本 narrative script

入口：

- `NarrativeScriptService`
- `NarrativeScriptAgent`
- `prompts/system/narrative_script.md`

输入：

- creative brief
- style bible
- `target_duration_sec`
- `total_shots_generated`
- `grid_count`
- `allowed_shot_durations_sec`
- `character_list`

输出：

- `NarrativeScriptVersion`
- 每个 shot 必须包含：
  - `shot_index`
  - `duration_sec`
  - `scene_description`
  - `action_description`
  - `start_frame_description`
  - `middle_frame_description`
  - `end_frame_description`
  - `emotion`
  - `emotion_intensity`
  - `dialogue`
  - `audio_strategy`

下游依赖：

- storyboard 使用 `start/middle/end_frame_description` 生成三宫格。
- shot plan 使用 narrative shot 派生运镜、节奏、主体、地点、台词。
- 视频 prompt 编译读取这些字段作为当前 shot 的语义基础。

### 阶段 4：shot plan 派生

入口：

- `ShotPlanPersistenceService`

输入：

- narrative shots
- `ProjectSpec.output_config.target_duration_sec`
- provider 支持的时长档位

输出：

- `ShotPlanVersion`
- `Shot`

每个 shot 传递给后续视频 prompt 的内容：

- `duration_sec`
- `start_ms`
- `end_ms`
- `subject`
- `location`
- `dialogue`
- `audio_strategy`
- `emotion`
- `emotion_intensity`
- `camera_language`
- `pace`
- `visual_energy`
- `motion_strategy`
- `start_frame_description`
- `middle_frame_description`
- `end_frame_description`

下游依赖：

- prompt compiler 的 `shot_spec` 来自这里。
- video generation 的 `duration_sec` 来自这里，并会被限制在 15 秒以内。

### 阶段 5：三宫格 storyboard 生图与切分

入口：

- `StoryboardService.generate()`
- `PromptCompilerService.compile_nine_grid_prompt()`
- `ImageGenerationTool.generate_nine_grid()`
- `ImageGenerationTool.split_and_persist_grid()`

输入：

- creative brief extension
- style bible
- narrative script 中当前 shot 的三段画面描述
- `aspect_ratio`
- `image_size`
- `image_resolution`

输出：

- 一张三宫格大图 asset：`asset_type=nine_grid_image`
- 三张切分 cell asset：`asset_type=storyboard_frame`

三张 cell 的语义：

- `cell 1`：当前 shot 起始帧
- `cell 2`：当前 shot 中间帧
- `cell 3`：当前 shot 结束帧

下游依赖：

- clip 生成阶段按 `grid_index -> shot_index` 读取这三张 cell。
- 三张 cell URL 会作为 Seedance `multi_image_fusion` 的参考图。

### 阶段 6：LLM 编译 Seedance 视频 prompt

入口：

- `ClipService`
- `PromptCompilerService.compile_prompt_bundle()`
- `PromptCompilerService._call_llm()`
- `prompts/compiler/compile_video_prompt.md`

输入给 LLM 的上下文：

- `style_bible`：全局视觉风格、色彩、光线、镜头质感
- `character_set`：角色身份、外观、服装、气质
- `shot_spec`：当前 shot 的主体、地点、时长、情绪、运镜、动作、台词
- `audio_direction`：背景音、配音和声音策略
- `provider_profile`：Seedance 能力和参数约束
- `reference_assets`：参考素材状态
- `generation_mode`：通常为 `multi_image_fusion`
- `start_frame_description`：图片1语义
- `middle_frame_description`：图片2语义
- `end_frame_description`：图片3语义
- `output_spec`：画幅、清晰度、三宫格布局、单 clip 最大 15 秒

LLM 必须输出：

```json
{
  "positive_prompt": "由模型基于上游产物生成的专业 Seedance 视频导演提示词",
  "negative_prompt": "...",
  "params": {
    "duration_sec": 12,
    "aspect_ratio": "9:16",
    "resolution": "1080p",
    "motion_strength": 0.55,
    "seed": null
  },
  "reference_asset_ids": []
}
```

这里的 `positive_prompt` 是真正的视频提示词正文。它不是后端写死的字符串，而是 LLM 结合前面所有阶段产物生成的结果。

代码额外做的硬约束：

- 最终 `params.aspect_ratio` 覆盖为 `ProjectSpec.output_config.aspect_ratio`。
- 最终 `params.resolution` 覆盖为 `ProjectSpec.output_config.video_resolution`。
- 如果有三张参考图，写入 `reference_image_urls` 并设置视频参考模式。

### 阶段 7：Seedance 三图融合视频生成

入口：

- `VideoGenerationTool.generate_for_bundle()`
- `SeedanceAdapter.generate()`

输入：

- LLM 生成的 `positive_prompt`
- `negative_prompt`
- `reference_image_urls` 三张 cell 图
- `duration_sec`
- `aspect_ratio -> ratio`
- `resolution`

Seedance payload 关键结构：

- `content[0]`：文本 prompt
- `content[1..3]`：三张参考图，`role=reference_image`
- `ratio`：来自需求入口规格
- `duration`：来自 shot plan，并限制在 15 秒以内
- `resolution`：来自需求入口规格

输出：

- `clip_video` asset
- `ClipVersion`
- 实际 `duration_ms`

### 阶段 8：时间线合成与导出

入口：

- `TimelineComposerService`
- `FFmpegTimelineTool`
- `ExportService`

输入：

- 多个 clip asset
- `ProjectSpec.output_config.aspect_ratio`
- 导出分辨率

处理方式：

- timeline 阶段按项目目标画幅归一 clip。
- export 阶段再按导出分辨率转码。

本次改造的重点是让比例在前置生成阶段就一致，而不是依赖 ffmpeg 最后强行补救。

## 四、最终数据流总览

```text
ui_dev 需求表单
  -> ProjectSpec.output_config
      target_duration_sec
      aspect_ratio
      video_resolution
      image_resolution
      image_size
      storyboard_layout=1x3_triptych

ProjectSpec
  -> CreativePlanningAgent
      -> CreativeBrief.extension
          shot_count / grid_count / total_shots_generated
          shot_durations_sec / max_clip_duration_sec
          aspect_ratio / video_resolution / image_size
          character_list / visual_style / human_on_camera

CreativeBrief + StyleBible
  -> NarrativeScriptAgent
      -> NarrativeScript.shots
          duration_sec
          start_frame_description
          middle_frame_description
          end_frame_description
          emotion / dialogue / audio_strategy

NarrativeScript
  -> ShotPlanPersistenceService
      -> ShotPlan + Shot
          camera_language
          pace
          visual_energy
          motion_strategy
          start_ms / end_ms / duration_sec

NarrativeScript + CreativeBrief + StyleBible
  -> compile_nine_grid_prompt
      -> GPT Image 2 三宫格大图
          -> split cell1/cell2/cell3

Shot + StyleBible + CharacterSet + 三张 cell + output_spec
  -> compile_video_prompt
      -> LLM 生成 Seedance 专业 positive_prompt

positive_prompt + cell1/cell2/cell3 + ratio + duration + resolution
  -> Seedance multi_image_fusion
      -> clip_video

clip_video list + aspect_ratio
  -> timeline compose
      -> export
```

## 五、验证结果

已完成验证：

- `git diff --check`
- `python -m compileall` 覆盖本次改动的后端 Python 文件
- `python -m pytest backend\tests\test_output_spec_service.py backend\tests\test_seedance_adapter.py backend\tests\test_ffmpeg_timeline_tool.py`
  - 结果：`7 passed`
  - pytest 退出时出现 Windows 临时目录清理 `PermissionError`，测试本身已通过
- `cd ui_dev && npm run lint`
  - 结果：TypeScript `tsc --noEmit` 通过

新增测试：

- `backend/tests/test_output_spec_service.py`
  - 校验三宫格大图切分后的 cell 比例。
  - 校验 `normalize_output_config()` 输出统一生成契约。
  - 校验 `plan_triptych_shots()` 不会规划超过 15 秒的单 clip。

## 六、残留风险与后续注意

1. 旧命名仍存在：`nine_grid_image`、`compile_nine_grid_prompt()` 等为兼容旧 schema 暂未重命名。当前语义已是三宫格，但后续如果要彻底清理技术债，可以单独做一次命名迁移。
2. 历史数据兼容：旧九宫格历史数据可能仍有 `cell_position 1-9`。本次没有做历史数据迁移，也不应在没有用户确认的情况下做不可逆迁移。
3. LLM 视频 prompt 的质量依赖真实模型调用。代码已经把上下文、硬约束和 Seedance 专业写法交给 LLM，但真实效果仍需要用实际项目跑一次端到端视频生成来评估。
4. Seedance API 的真实参数接受范围要以线上 provider 为准。本次验证覆盖了 adapter payload 和本地链路，不包含真实外部 API 调用。
