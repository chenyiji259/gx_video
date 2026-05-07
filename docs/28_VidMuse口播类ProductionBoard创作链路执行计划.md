# VidMuse 口播类 Production Board 创作链路执行计划

## 1. 计划目标

本文档基于 `docs/27_VidMuse口播类ProductionBoard创作链路重构设计.md`，把已经拍板的口播类链路拆成后端实现任务和前端适配任务。

目标不是重建整套生成系统，而是在现有 `需求 -> brief -> script -> image -> video -> timeline -> export` 工程阶段里，把口播类项目从三宫格语义切换到 `Story Overview Board / Production Board` 语义。

当前拍板主线：

```text
用户需求
  -> TalkingHeadBrief
  -> SegmentScript[]
  -> StoryOverviewBoardSpec
  -> 生成 1 张 21:9 故事大图
  -> 每 15s 一个 shot，共用同一张故事大图，但读取不同 segment
  -> 每个 shot 编译 Seedance 视频 prompt
  -> Seedance content = text + 固定人物 reference_image + 故事大图 reference_image + 固定声色 reference_audio
  -> 生成 clips
  -> timeline/export
```

## 2. 当前代码现状

后端现有能力：

- `backend/app/services/output_spec_service.py` 已经是 `ProjectSpec.output_config` 的统一规格入口，但当前默认仍是 `1x3_triptych`。
- `backend/app/services/brief_persistence_service.py`、`backend/app/agents/creative_planning_agent.py`、`backend/app/agents/narrative_script_agent.py` 仍按普通创意/三宫格 shot 语义组织。
- `backend/app/services/storyboard_service.py` 当前是三宫格服务：生成大图、切 3 个 cell、落 `storyboard_frames`。
- `backend/app/services/prompt_compiler_service.py` 已经是 LLM prompt 编译边界，但当前模板主要是 `compile_image_prompt.md` / `compile_video_prompt.md`，且带三宫格语义。
- `backend/app/providers/video/seedance_adapter.py` 已支持 `role=reference_image`，但仅支持 `reference_image_urls`，还不支持 `reference_audio_urls`。
- `backend/app/services/clip_service.py` 当前从 storyboard cells 取每个 shot 的 3 张参考图；口播链路需要改为固定人物图 + 同一故事大图 + 固定声色音频。
- timeline/export 已经能拼接 clip，原则上不需要重写。

前端现有能力：

- 当前活跃前端是 `ui_dev`。
- `ui_dev/src/components/Workspace.tsx` 是工作台主入口，当前创建 spec 时固定 `aspect_ratio=9:16`，时长是自由数字输入。
- 前端当前展示三宫格 cells：起始帧/中间帧/结尾帧，并显示“三宫格原图”。
- 前端已有 shot 列表、clip 列表、失败重试、timeline/export 展示能力，可复用。

## 3. 范围和非目标

本轮实现范围：

- 新增数据库约束迁移：`prompt_bundles.target_type` 正式支持 `talking_head_story_overview_board`。
- 新增口播类项目的输出规格与配置契约。
- 新增 15 秒倍数时长规则。
- 新增固定人物资产和固定声色资产读取。
- 新增 Story Overview Board 生图 prompt 编译。
- 新增 talking head video prompt 编译。
- 改造 Seedance 请求 content，支持 `reference_audio`。
- 改造口播 clip 生成时的参考资产传递。
- 前端创建入口和产物展示适配。

本轮非目标：

- 不重新设计数据库全量模型。
- 不把 TTS 接回主链路。
- 不做字幕能力。
- 不做多角色口播完整产品化。
- 不做单段 Production Board 回退实现，除非 21:9 故事大图实测失败后再启动。
- 不改 timeline/export 主体逻辑，除非口播 clip 拼接暴露出实际问题。

## 4. 后端执行计划

### B1. 输出规格和入口契约

目标：让口播类项目从创建入口开始进入 `talking_head_production_board` 语义。

修改文件：

- `backend/app/services/output_spec_service.py`
- `backend/app/api/v1/project_spec.py`
- `backend/app/schemas/project.py`
- `ui_dev/src/api.ts`
- `ui_dev/src/types.ts`

实现内容：

1. 在 `normalize_output_config()` 中识别口播类配置，例如：

```json
{
  "generation_profile": "talking_head_production_board",
  "storyboard_layout": "talking_head_story_overview_board",
  "segment_duration_sec": 15,
  "story_board_aspect_ratio": "21:9",
  "target_duration_sec": 60
}
```

2. 对口播类项目强制校验：

- `target_duration_sec % 15 == 0`
- `target_duration_sec >= 15`
- `segment_duration_sec == 15`
- `story_board_aspect_ratio == 21:9`

3. 保留最终视频 `aspect_ratio` 与故事大图画幅分离：

- `aspect_ratio`：最终视频比例，例如 `9:16`。
- `story_board_aspect_ratio`：故事大图比例，固定 `21:9`。

4. 当前不建议在代码中到处直接读取 env。项目已有配置约束是业务配置走 `config/base/*.yaml`，secret 才走 `.env`。因此固定资产建议放到集中配置，例如：

```yaml
talking_head:
  host_reference_image_assets:
    - "asset://asset-20260506200638-6g86k"
    - "asset://asset-20260506200638-5pf4j"
    - "asset://asset-20260506200636-lmt8b"
  reference_audio_assets:
    - "asset://asset-20260506202002-hhmgk"
    - "asset://asset-20260506202001-fg589"
    - "asset://asset-20260506202001-hl2kx"
  story_board_aspect_ratio: "21:9"
  segment_duration_sec: 15
  subtitles_enabled: false
```

验收标准：

- 创建 60s 口播 spec 后，`output_config.storyboard_layout=talking_head_story_overview_board`。
- 非 15 秒倍数时长被后端拒绝，返回清晰错误。
- 故事大图画幅和最终视频比例不会互相覆盖。

### B2. 口播 Brief 和 SegmentScript 规划

目标：让 LLM 前置规划产出适合故事大图和视频 prompt 的结构，而不是普通 shot/triptych 字段。

修改文件：

- `backend/app/agents/creative_planning_agent.py`
- `backend/app/agents/narrative_script_agent.py`
- `prompts/system/creative_planning.md`
- `prompts/system/narrative_script.md`
- `prompts/tasks/generate_brief.md`
- `prompts/tasks/generate_shot_plan.md`
- `backend/app/services/brief_persistence_service.py`
- `backend/app/services/shot_plan_persistence_service.py`

实现内容：

1. 对 `generation_profile=talking_head_production_board` 分支生成 `TalkingHeadBrief` 所需字段：

- host lock
- set lock
- audio lock
- visual lock
- column/show style
- segment_count
- segment_duration_sec
- no_subtitles=true

2. 生成 `SegmentScript[]`，每段 15 秒，但不要求 15 秒全程说话。

每段至少包含：

```json
{
  "segment_index": 1,
  "time_range": "0-15s",
  "title": "...",
  "segment_goal": "...",
  "voiceover_script": "...",
  "spoken_duration_estimate_sec": 9.5,
  "speech_timing_plan": [
    {
      "time_range": "0-3s",
      "speech_type": "opening_visual",
      "dialogue": "",
      "action": "...",
      "camera": "..."
    }
  ],
  "action_plan": "...",
  "expression_plan": "...",
  "supporting_visuals": [],
  "negative_rules": []
}
```

3. `shot_plan_persistence_service.py` 对口播类项目按 15 秒固定生成 shot：

- 60s = 4 shots
- 45s = 3 shots
- 每个 shot duration = 15s
- start/end 严格连续

验收标准：

- 60s 口播项目生成 4 个 shot，每个 15s。
- shot 内允许 `speech_timing_plan` 有无对白片段。
- narrative/shot raw payload 能追溯每个 segment 的台词、动作、表情、辅助视觉。

### B3. Story Overview Board 生图编译

目标：生成 1 张 21:9 故事大图，而不是每个 shot 生成一组三宫格。

修改文件：

- `prompts/compiler/compile_story_overview_board_prompt.md` 新增
- `backend/app/services/prompt_compiler_service.py`
- `backend/app/schemas/prompt.py`
- `backend/app/models/prompt_bundle.py`
- `backend/app/services/storyboard_service.py`
- `backend/app/tools/image_generation_tool.py`
- `backend/app/schemas/storyboard.py`
- `backend/app/api/v1/storyboard.py`

实现内容：

1. 新增 prompt 模板 `compile_story_overview_board_prompt.md`。

输入包括：

- `ProjectSpec.output_config`
- `TalkingHeadBrief`
- `SegmentScript[]`
- 固定人物 reference image assets
- 固定声色 reference audio assets
- no subtitles
- 21:9 story board aspect ratio

输出建议为结构化 JSON：

```json
{
  "image_positive_prompt": "...",
  "image_negative_prompt": "...",
  "image_params": {
    "aspect_ratio": "21:9",
    "resolution": "2K",
    "board_type": "talking_head_story_overview_board"
  },
  "layout_reading_map": {
    "segment_1": "0-15s 区域说明"
  },
  "source_trace": {}
}
```

2. `PromptCompilerService` 新增 `compile_story_overview_board()`。

3. `PromptTargetType` 需要加入 `talking_head_story_overview_board`。

4. 数据库必须同步迁移 `prompt_bundles.target_type` 的 CHECK 约束，不再复用 `nine_grid_image` 临时承载口播故事大图。迁移脚本固定为：

```text
scripts/sql/patch_007_prompt_bundle_talking_head_target.sql
```

本地数据库已执行并验证通过；服务器数据库后续发布前同步执行同一脚本。

4. `StoryboardService` 增加口播分支：

- 当前三宫格分支保持给非口播项目使用。
- 口播分支只生成 1 张 parent story board asset。
- 不调用 `split_and_persist_grid()`。
- `StoryboardVersion.raw_payload` 写入 `board_type=talking_head_story_overview_board`、`parent_asset_id`、`parent_asset_url`、`layout_reading_map`、`segments`。

5. `api/v1/storyboard.py` 返回故事大图元数据。为了前端最小改动，可继续返回 `grids`，但 grid 内标记：

```json
{
  "grid_index": 1,
  "board_type": "talking_head_story_overview_board",
  "parent_asset_id": "...",
  "parent_asset_url": "...",
  "cell_count": 0,
  "cells": [],
  "layout_reading_map": {}
}
```

验收标准：

- 口播项目 storyboard 阶段只生成 1 张 21:9 故事大图。
- 不生成三宫格 cell。
- API 能返回故事大图 URL 和 segment reading map。

### B4. Talking Head 视频 prompt 编译

目标：每个 shot 使用同一张故事大图，但 prompt 明确读取不同 segment。

修改文件：

- `prompts/compiler/compile_talking_head_video_prompt.md` 新增
- `backend/app/services/prompt_compiler_service.py`
- `backend/app/services/clip_service.py`
- `backend/app/schemas/prompt.py`

实现内容：

1. 新增 `compile_talking_head_video_prompt.md`。

输入包括：

- `story_board_url`
- `shot_index`
- `segment_time_range`
- `segment_script`
- `layout_reading_map`
- fixed host reference image assets
- fixed reference audio assets
- provider profile
- no subtitles

2. LLM 输出 JSON：

```json
{
  "positive_prompt": "...",
  "negative_prompt": "不要字幕、水印、制作板页面、标题栏、文字贴片、多人物、换脸...",
  "board_segment_reading_instruction": "只读取故事大图中 Segment 2 / 15-30s 区域",
  "dialogue_script": "...",
  "timeline": [],
  "params": {
    "duration_sec": 15,
    "ratio": "adaptive",
    "generate_audio": true,
    "watermark": true
  }
}
```

3. prompt 必须写清：

- 图片1-图片3：固定人物参考，只锁脸、年龄感、气质、基础身形。
- 图片4：故事大图，只读取当前 segment。
- 音频1-音频3：只参考声色，不承载台词内容，不照搬节奏。
- 当前 15 秒不是必须全程说话，按 `speech_timing_plan` 安排开场动画、停顿、对白、产品特写。
- 当前不生成字幕。

验收标准：

- 4 个 shot 的 prompt 都引用同一故事大图 URL。
- 每个 prompt 的 `board_segment_reading_instruction` 不同。
- prompt 中不出现“字幕”“关键词字幕”等正向要求。

### B5. Seedance content 和视频工具改造

目标：支持 `reference_audio`，并让口播类请求 content 顺序稳定。

修改文件：

- `backend/app/providers/video/seedance_adapter.py`
- `backend/app/tools/video_generation_tool.py`
- `backend/app/services/clip_service.py`
- `backend/tests/test_seedance_adapter.py`

实现内容：

1. `VideoGenerationTool.generate_for_bundle()` 支持：

```python
reference_audio_urls: list[str] | None = None
reference_video_urls: list[str] | None = None
```

2. `SeedanceAdapter.generate()` / `_build_payload()` 支持：

- `reference_image_urls`
- `reference_audio_urls`
- `reference_video_urls` 后续预留

3. 口播类 content 顺序：

```json
[
  {"type": "text", "text": "<prompt>"},
  {"type": "image_url", "role": "reference_image", "image_url": {"url": "asset://host1"}},
  {"type": "image_url", "role": "reference_image", "image_url": {"url": "asset://host2"}},
  {"type": "image_url", "role": "reference_image", "image_url": {"url": "asset://host3"}},
  {"type": "image_url", "role": "reference_image", "image_url": {"url": "<story_board_url>"}},
  {"type": "audio_url", "role": "reference_audio", "audio_url": {"url": "asset://audio1"}},
  {"type": "audio_url", "role": "reference_audio", "audio_url": {"url": "asset://audio2"}},
  {"type": "audio_url", "role": "reference_audio", "audio_url": {"url": "asset://audio3"}}
]
```

4. 不要把参考音频作为 dialogue/audio track 使用。

验收标准：

- 单元测试覆盖 `reference_audio` content。
- Seedance payload 不再只支持 3 张图片。
- 旧三图融合测试仍通过或按新分支保留兼容。

### B6. ClipService 口播分支

目标：clip 生成时不再从三宫格 cell 取每 shot 的 3 张图，而是使用固定人物图 + 同一故事大图 + 固定声色音频。

修改文件：

- `backend/app/services/clip_service.py`
- `backend/app/services/asset_access_service.py` 如需解析 `asset://`
- `backend/app/repositories/storyboard_repositories.py`
- `backend/app/api/v1/shots.py` 可选，补充 segment metadata

实现内容：

1. 根据 `ProjectSpec.output_config.storyboard_layout` 分支：

- `1x3_triptych`：走现有逻辑。
- `talking_head_story_overview_board`：走口播逻辑。

2. 口播逻辑读取：

- fixed host reference image assets
- active Story Overview Board asset URL
- fixed reference audio assets
- current shot segment metadata

3. 生成每个 shot：

- `mode="multi_image_fusion"` 或按 Seedance 2.0 r2v 多模态任务实际要求选择同一入口。
- `reference_image_urls = host_assets + [story_board_url]`
- `reference_audio_urls = audio_assets`
- `duration_sec = 15`
- `generate_audio = true`
- `watermark` 按当前配置

验收标准：

- 60s 项目生成 4 个 clip。
- 每个 clip 都使用同一故事大图。
- 失败时 `last_failure` 能显示 Seedance 返回原因。

### B7. 事件、API 和兼容展示

目标：前端能知道当前是故事大图链路，并能展示“同图复用不同 segment”。

修改文件：

- `backend/app/api/v1/storyboard.py`
- `backend/app/api/v1/shots.py`
- `backend/app/schemas/storyboard.py`
- `backend/app/schemas/shot.py`
- `backend/app/services/event_log_service.py` 如需新增事件类型

实现内容：

1. Storyboard API 返回：

- `board_type`
- `parent_asset_url`
- `story_board_aspect_ratio`
- `segment_count`
- `layout_reading_map`

2. Shots API 可补充：

- `segment_index`
- `segment_time_range`
- `story_board_segment_label`

3. 事件可以继续复用现有 `storyboard.grid.generated`，但建议新增或补 payload：

- `storyboard.story_overview.generated`
- `storyboard.story_overview.ready`

验收标准：

- 前端无需猜测当前是三宫格还是故事大图。
- 旧项目仍能展示三宫格。

## 5. 前端执行计划

### F1. 创建入口：口播类配置

目标：用户在入口就创建口播类项目，不再让后端猜。

修改文件：

- `ui_dev/src/components/Workspace.tsx`
- `ui_dev/src/api.ts`
- `ui_dev/src/types.ts`

实现内容：

1. 表单增加或默认隐藏传递：

```ts
generation_profile: 'talking_head_production_board'
storyboard_layout: 'talking_head_story_overview_board'
segment_duration_sec: 15
story_board_aspect_ratio: '21:9'
subtitles_enabled: false
```

2. 时长输入从自由数字改为选项：

- `15s`
- `30s`
- `45s`
- `60s`
- `75s`
- `90s`

默认建议 `60s`。

3. 最终视频比例仍保留 `9:16` 默认，避免和故事大图 `21:9` 混淆。

验收标准：

- 前端不能提交非 15 秒倍数。
- 创建 spec payload 明确带口播 profile。
- UI 上不把 21:9 误显示为最终视频比例。

### F2. 工作台文案和阶段命名

目标：把三宫格/关键帧语义替换为故事大图/Production Board。

修改文件：

- `ui_dev/src/components/Workspace.tsx`

实现内容：

1. `storyboard_layout=talking_head_story_overview_board` 时：

- Step 3 标题从“关键帧/三宫格”改为“故事大图 / Production Board”。
- 按钮文案从“生成关键帧”改为“生成故事大图”。
- 错误文案从“关键帧生成失败”改为“故事大图生成失败”。

2. 保留旧三宫格项目文案兼容。

验收标准：

- 口播项目 UI 不出现“三宫格原图”“起始帧/中间帧/结尾帧”等误导文案。
- 旧项目仍按原展示。

### F3. 故事大图展示

目标：图片阶段展示 1 张故事大图，而不是 3 个 cell。

修改文件：

- `ui_dev/src/components/Workspace.tsx`
- `ui_dev/src/types.ts`

实现内容：

1. `StoryboardGrid` 类型补充：

```ts
board_type?: string;
layout_reading_map?: Record<string, unknown>;
story_board_aspect_ratio?: string;
```

2. 如果 `board_type=talking_head_story_overview_board`：

- 主区域展示 `parent_asset_url`。
- 显示 Segment 1/2/3/4 选择器。
- 选择某个 shot 时，高亮“当前 clip 读取 Segment N / x-y 秒”。
- 不展示起始帧/中间帧/结尾帧三列。

验收标准：

- 用户能看到一张 21:9 故事大图。
- 用户能理解 4 个 clip 都来自同一张图的不同 segment。

### F4. Clip 列表和视频预览

目标：视频展示沿用现有 clip/timeline/export，但补齐 segment 映射。

修改文件：

- `ui_dev/src/components/Workspace.tsx`
- `ui_dev/src/types.ts`

实现内容：

1. clip 列表文案：

- `Shot 1 · Segment 1 · 0-15s`
- `Shot 2 · Segment 2 · 15-30s`

2. 缩略图优先使用故事大图父图或后端返回的 clip thumbnail；不要再使用三宫格 cell 当缩略图。

3. 视频信息增加：

- 故事大图：21:9
- 最终视频比例：9:16 / adaptive
- 无字幕
- 声色参考：固定资产

验收标准：

- clip 列表不再显示“三图关键帧已就绪”。
- 失败重试仍可用。
- timeline/export 展示不需要额外操作。

### F5. 前端 API 类型对齐

修改文件：

- `ui_dev/src/api.ts`
- `ui_dev/src/types.ts`

实现内容：

1. `createSpecVersion` payload 支持：

```ts
generation_profile?: string;
storyboard_layout?: string;
segment_duration_sec?: number;
story_board_aspect_ratio?: string;
subtitles_enabled?: boolean;
```

2. `ProjectSpec.output_config` 类型同步补充上述字段。

3. `StoryboardGrid` 类型兼容故事大图字段。

验收标准：

- TypeScript build 通过。
- 口播字段不需要 `as any` 到处绕过。

## 6. 推荐实施顺序

### 第一批：后端契约先闭合

1. B1 输出规格和 15 秒校验。
2. B5 Seedance `reference_audio` content 支持和测试。
3. B4 talking head video prompt 模板骨架。

原因：先把 provider 请求和规格入口闭合，避免后面故事大图做好后卡在请求结构上。

### 第二批：故事大图链路

4. B2 口播 brief / SegmentScript。
5. B3 Story Overview Board 生图编译和 StoryboardService 分支。
6. B7 Storyboard API 返回故事大图结构。

原因：这批让图片阶段从三宫格切到故事大图。

### 第三批：clip 生成闭环

7. B6 ClipService 口播分支。
8. 跑 60s / 4 shot 小样例。
9. 根据失败原因补充 prompt guardrails。

原因：这是验证“同图复用 4 个 shot”的关键。

### 第四批：前端适配

10. F1 创建入口。
11. F2/F3 工作台故事大图展示。
12. F4/F5 clip 映射和类型对齐。

原因：前端依赖后端字段稳定，后端 API 字段确定后再做 UI，返工最少。

## 7. 验收标准

后端验收：

- 口播项目 60s 创建后，后端生成 4 个 15s shot。
- Storyboard 阶段只生成 1 张 21:9 故事大图。
- Clip 阶段发起 4 个 Seedance 任务，每个任务使用同一故事大图，不同 prompt segment instruction。
- Seedance content 包含 `reference_image` 和 `reference_audio` role。
- 不调用 TTS。
- prompt 明确无字幕。
- timeline/export 能拼成完整 60s 成品。

前端验收：

- 创建口播项目只能选择 15 秒倍数时长。
- 工作台图片阶段显示故事大图，不显示三宫格三列。
- shot/clip 列表能显示 Segment 1/2/3/4 对应关系。
- 视频信息区区分“故事大图 21:9”和“最终视频比例”。
- 失败重试、clip 预览、timeline/export 操作保持可用。

## 8. 风险和决策点

### R1. PromptBundle target_type 数据库迁移

已拍板：本轮正式新增 `talking_head_story_overview_board`，不再用 `nine_grid_image` 兼容承载。

需要同步改三处：

- 数据库 CHECK 约束：本地已执行 `scripts/sql/patch_007_prompt_bundle_talking_head_target.sql`，服务器数据库后续同步执行。
- 应用层 schema：`backend/app/schemas/prompt.py` 的 `PromptTargetType`。
- ORM 约束声明：`backend/app/models/prompt_bundle.py` 的 `_TARGET_TYPE_VALUES`。

执行状态和后续顺序：

1. 本地数据库：patch_007 已执行，并已确认 `ck_prompt_bundles_target_type` 包含 `talking_head_story_overview_board`。
2. 本地代码：继续实现和测试口播链路。
3. 服务器数据库：发布前执行同一 SQL 脚本。
4. 服务器代码：数据库迁移完成后，再部署包含新 `target_type` 的后端代码。

如果服务器先部署代码但没有执行 SQL，故事大图 prompt 落库会被 `ck_prompt_bundles_target_type` 拒绝。

### R2. Storyboard 数据结构是否继续复用 grids

正式做法：新增更中性的 `storyboard_boards` API 或扩展 schema。

低改动做法：继续用 `grids` 返回故事大图，`cells=[]`，增加 `board_type`。

建议：第一版用低改动做法，前端按 `board_type` 分支。

### R3. 21:9 故事大图能否被 Seedance 稳定读取

这是核心质量风险。当前计划先按 21:9 主线实现；如果实测串段、复刻版式或读错区域，再评估：

- 派生 clean hero frame。
- 回退单段 Production Board。
- 强化 `layout_reading_map` 和 prompt 禁止项。

### R4. asset:// 是否全链路可被 Seedance 直接读取

脚本测试已经验证 asset 方式更稳定，但后端实现时仍要确认：

- 固定人物 asset URL 是否直接传 `asset://...`。
- 故事大图是 OSS signed URL 还是 provider asset。
- 参考音频 asset 是否需要 provider asset ID。

第一版建议：固定人物/音频用 `asset://`，故事大图用后端可访问 URL；若 Seedance 要求 provider asset，再补资产上传/登记步骤。

## 9. 最小可交付版本

最小可交付版本只要求跑通一个 60s 口播项目：

1. 前端创建 60s 口播项目。
2. 后端生成 4 个 15s segment/shot。
3. 生成 1 张 21:9 故事大图。
4. 4 个 shot 复用故事大图生成 clip。
5. 合成 60s 视频。
6. 前端能展示故事大图、4 个 clips、最终导出。

不要求：

- 多角色。
- 字幕。
- TTS。
- 单段 Production Board 回退。
- clean hero frame。
- 数据库资产治理完整后台。
