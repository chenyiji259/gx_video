# VidMuse 后端创作链路设计思路

本文说明 VidMuse 后端从“用户需求输入”到“最终视频生成”的整体设计理念。重点不是接口清单，而是解释为什么要把创作过程拆成需求、创意、剧本、分镜图片、视频片段、时间线和导出这些阶段，以及每个阶段如何把结构化数据传给下游作为生成依据。

## 1. 总体理念：把模糊需求逐层固化为可执行视频资产

AI 视频生成不是一次性把一句话丢给视频模型就能稳定完成的任务。用户一开始给出的通常是模糊意图，例如：

- 想做什么主题的视频
- 面向什么平台
- 面向什么人群
- 要什么风格
- 是否需要真人入镜
- 时长大概多少
- 有没有参考图、音频或其他素材

如果直接把这些信息交给视频模型，系统会遇到几个问题：

1. 需求含义不稳定：同一句需求可以被解释成广告、讲解、剧情、产品展示或纯视觉氛围片。
2. 视觉一致性不可控：人物、场景、风格、画幅、镜头运动容易每段漂移。
3. 成本不可控：视频生成是高成本步骤，不能在创意和剧本尚未锁定时反复调用。
4. 下游缺少硬约束：视频模型需要明确的起始画面、结束画面、动作、时长、画幅和参考图，而不是抽象愿望。
5. 重试和局部修改困难：如果最终视频不好，必须知道是需求错、创意错、剧本错、分镜错，还是视频模型执行错。

因此 VidMuse 采用“逐层收敛”的设计：

```text
用户需求
  -> ProjectSpec 输入规格
  -> CreativeBrief + StyleBible 创意与风格方案
  -> NarrativeScript 逐镜头剧本
  -> ShotPlan 可执行镜头计划
  -> Storyboard 九宫格关键帧
  -> Clip 视频片段
  -> Timeline 时间线合成
  -> Export 最终导出视频
```

每一层都承担一个明确目标：把上一层的模糊内容进一步结构化，变成下一层可以直接执行的依据。系统不是为了“步骤多”而拆分，而是为了让每一步都能被确认、版本化、复用、回滚和局部重生成。

## 2. 入口：需求输入不是一句 prompt，而是一份 ProjectSpec

后端的正式需求入口是 `ProjectSpecVersion`。它不是只保存用户一句话，而是把创作需求拆成一组对后续阶段有约束力的字段。

核心输入包括：

- `user_prompt`：用户对视频内容的自然语言需求，例如主题、内容方向、卖点、故事或讲解目标。
- `platform`：发布平台，例如 TikTok、Bilibili、YouTube、YouTube Shorts、Instagram、小红书等。
- `target_audience`：目标受众，例如小白用户、专业用户、年轻女性、企业客户等。
- `style_preference`：用户期望的视觉风格，例如真人实拍、动画科技感、极简、电影感、产品广告风等。
- `human_on_camera`：是否需要真人入镜。这个字段非常关键，会影响角色生成、分镜提示词和负向提示词。
- `target_duration_sec`：目标视频总时长。
- `aspect_ratio`：画面比例，例如 `9:16`、`16:9`、`1:1`。
- `reference_image_asset_ids`：用户上传的参考图资产 ID，用于角色或视觉参考。
- `audio_asset_id`：可选音频素材。当前 AI 视频内容生成流程中，音频不是必填入口；如果存在，可在时间线阶段作为外部配乐叠加。
- `constraints`：附加约束，例如禁用某些元素、必须包含某些画面、品牌安全要求等。

这些字段进入 `output_config` 和版本化的输入规格中。这样做的好处是：

- 用户每次修改需求都会形成新版本，不覆盖旧版本。
- 下游所有产物都可以追溯到当时激活的需求版本。
- 需求变更可以触发下游失效和重生成，而不是让旧视频继续引用过时需求。
- 后续 agent 不需要猜测“真人入镜”“平台”“受众”“画幅”等关键前提。

当前实现中，只要 `user_prompt` 有内容，项目就可以从 `created` 推进到 `input_ready`。这说明系统已经从旧的“音乐 MV 必须先上传音频”模式，转向“文本需求即可启动的 AI 视频内容生成”模式。

## 3. 为什么先生成 CreativeBrief 和 StyleBible

用户需求直接进入剧本阶段会太散。系统先生成 `CreativeBrief` 和 `StyleBible`，目的是把“想做什么”收敛成“这个视频应该怎么创作”。

`CreativeBrief` 解决内容策略问题：

- 视频标题或创意命名
- 一句话创意核心
- 叙事类型：讲解、剧情、展示、氛围、混合
- 表演/讲解占比
- 情绪标签
- 创意摘要
- 目标平台
- 目标受众
- 总时长
- shot 数量
- 九宫格数量
- 是否真人入镜
- 角色列表

`StyleBible` 解决视觉执行问题：

- 色彩体系
- 光影方式
- 镜头风格
- 质感
- 参考风格说明

这一层的关键是 `creative_brief.extension`。它把后续流程需要的硬参数提前固化：

```text
target_duration_sec
shot_duration_sec
shot_count
grid_count
total_shots_generated
allowed_shot_durations_sec
character_list
target_platform
target_audience
visual_style
human_on_camera
aspect_ratio
```

当前版本的产品策略是先做一个稳定闭环：单张九宫格、3 个 shot、每个 shot 对应九宫格的一整行。也就是：

```text
grid_count = 1
shot_count = 3
total_shots_generated = 3
```

这不是能力上只能做 3 个 shot，而是当前实现为了稳定视频生成链路，先把创作单位收敛为“3 段式短视频”。这样后续分镜、视频片段和时间线的关系非常明确：

```text
九宫格第 1 行 -> shot 1 的起始 / 中间 / 结尾
九宫格第 2 行 -> shot 2 的起始 / 中间 / 结尾
九宫格第 3 行 -> shot 3 的起始 / 中间 / 结尾
```

## 4. 真人入镜字段为什么必须从需求阶段就明确

`human_on_camera` 不能等到图片生成时才决定。原因是它会影响整条链路：

如果 `human_on_camera=true`：

- brief 需要生成真人角色或真人讲解主体。
- `character_list` 至少需要包含可持续引用的人物外貌、服装和气质。
- narrative 每个关键 shot 要考虑真人是否出现、如何说话、是否有表演动作。
- 九宫格 prompt 需要要求同一人物外观、发型、服装连续一致。
- video prompt 需要保留人物主体和表演连续性。
- negative prompt 要避免假人感、人物数量错误、脸部漂移。

如果 `human_on_camera=false`：

- brief 不应默认生成真人角色。
- narrative 应优先使用产品、场景、图形、抽象元素或概念可视化。
- 九宫格 prompt 要明确避免真人脸、人体和手部特写。
- video prompt 不应暗示主讲人或人物表演。
- negative prompt 要压制人物出镜、脸部特写、手部特写。

所以这个字段本质上是“主体策略门禁”。它从需求阶段传到 brief，再传到 narrative、nine-grid prompt 和 video prompt，防止下游模型擅自把视频从“无真人产品展示”变成“真人口播”，或者把“真人讲解”变成“纯图形动画”。

## 5. NarrativeScript：把创意变成逐镜头剧本

有了创意和风格后，系统进入 `NarrativeScript` 阶段。这个阶段不再讨论“视频大概是什么”，而是生成每个 shot 应该发生什么。

叙事剧本的核心输出包括：

- `story_arc`：整条视频的叙事弧线。
- `characters`：角色定义，来源于 brief 的角色清单。
- `scenes`：场景定义，从各个 shot 的场景中抽取。
- `audio_strategy`：整条视频的声音策略。
- `shots`：逐 shot 剧本。

每个 shot 必须包含：

- `shot_index`：镜头编号。
- `duration_sec`：该 shot 时长，必须从当前视频 provider 支持的时长档位中选择。
- `scene_description`：场景描述。
- `characters_in_shot`：当前镜头出现的角色 ID。
- `start_frame_description`：起始画面。
- `middle_frame_description`：中间画面。
- `end_frame_description`：结束画面。
- `action_description`：从起始到结束发生了什么动作或变化。
- `dialogue`：配音、旁白或角色台词；没有台词时也必须存在并为空字符串。
- `audio_strategy`：当前 shot 的声音执行策略。
- `emotion`：情绪标签。
- `emotion_intensity`：情绪强度。

这个阶段的核心价值是把抽象创意拆成“可拍摄的镜头”。例如用户说“做一个护肤品科普视频”，brief 只知道它是讲解类、目标受众是护肤小白、风格要干净可信；narrative 则必须进一步决定：

- 第一段如何开场
- 第二段如何展示问题或原理
- 第三段如何收束并给出行动建议
- 哪些镜头需要口播
- 哪些镜头只做产品特写或示意画面
- 每段从起始画面到结束画面如何变化

这也是后续九宫格能够生成连续关键帧的基础。

## 6. 台词和声音策略为什么放在剧本阶段

视频不是只有画面。对讲解、广告、剧情类内容来说，声音是内容结构的一部分。

系统在 narrative 阶段判断表达类型：

- `explainer`：讲解、科普、教程、口播类。
- `ad`：广告、品牌、带货、CTA 类。
- `drama`：剧情、对白、角色演绎类。
- `visual`：纯视觉、氛围、音乐驱动类。
- `general`：无法明确分类的通用视频。

不同类型决定不同台词策略：

- 讲解类通常需要连续旁白，但不强制每个 shot 都说话。
- 广告类可以只在开头、卖点和结尾 CTA 放台词。
- 剧情类只在角色实际说话的镜头放对白。
- 纯视觉类允许全部 `dialogue=""`。

声音策略会继续进入 shot plan、prompt compiler、video prompt 和 timeline。这样视频生成阶段知道当前 shot 是要“保留旁白”，还是“不要强行加口播”，背景音是要压低、支撑，还是作为氛围主导。

## 7. ShotPlan：把剧本变成可执行镜头计划

`NarrativeScript` 仍然偏创作语言，`ShotPlan` 则把它转换成更接近执行层的镜头规格。

当前新流程里，shot plan 可以从 narrative 自动派生，不一定再次调用 LLM。它会把每个 narrative shot 转换成数据库中的 `Shot`：

- `shot_index`
- `scene_id`
- `section_type`
- `shot_type`
- `subject`
- `location`
- `dialogue`
- `audio_strategy`
- `emotion`
- `emotion_intensity`
- `camera_language`
- `pace`
- `visual_energy`
- `duration_ms`
- `start_ms`
- `end_ms`
- `lipsync_required`
- `status`

这里最重要的是三类执行约束：

1. 时长约束  
   系统会把 `duration_sec` 对齐到当前视频 provider 支持的时长档位，并重建 `start_ms/end_ms`。这可以避免后续视频模型收到不支持的时长。

2. 运动约束  
   系统会根据表达类型、动作描述、台词、情绪强度推导 `camera_language`、`pace`、`visual_energy`。视频模型需要知道镜头是 slow push-in、tracking follow、static close-up，还是更强烈的动态运动。

3. 声音约束  
   每个 shot 的 `audio_strategy` 会进入 style binding 或 raw payload，后续 prompt 编译时用于决定旁白、语气、BGM 和是否压低背景音。

ShotPlan 是后续 Storyboard 和 Clip 的共同依据。Storyboard 根据它知道有哪些 shot，Clip 根据它知道每个视频片段的时长、运动、台词和画面目标。

## 8. Storyboard：为什么使用九宫格关键帧

视频模型直接从文本生成视频，稳定性通常不够。VidMuse 当前采用“九宫格关键帧”策略：先生成一张 3x3 大图，再把它切成 9 张关键帧图片。

当前映射关系是：

```text
cell 1 / cell 2 / cell 3 -> shot 1 的 start / middle / end
cell 4 / cell 5 / cell 6 -> shot 2 的 start / middle / end
cell 7 / cell 8 / cell 9 -> shot 3 的 start / middle / end
```

这样做有几个原因：

1. 提升视觉一致性  
   9 张图在同一张大图里生成，更容易保持角色、光线、风格和色彩一致。

2. 降低多次生图漂移  
   如果 9 张图分 9 次独立生成，同一角色和同一场景很容易漂移。九宫格把它们放进一次生成任务中，降低跨图不一致。

3. 给视频模型明确起止状态  
   每个 shot 后续会拿同一行的 3 张图作为参考：起始帧、中间帧、结束帧。视频模型不再只靠文字想象，而是知道这个 shot 应该从哪开始、经过什么中间状态、到哪里结束。

4. 便于前端审阅  
   用户可以先看分镜图。如果图的方向不对，可以在视频生成前重做 storyboard，避免浪费更高成本的视频调用。

Storyboard 阶段会产出：

- `StoryboardVersion`
- 九宫格大图 asset
- 9 个 cell frame asset
- 每个 cell 对应的 `shot_index`
- 每个 cell 的 `frame_description`
- 前端可访问的 `asset_url`

这些图片资产会存入对象存储和 `assets` 表，并通过 `StoryboardFrame` 绑定到 storyboard version 和 shot。

## 9. PromptBundle：为什么图片和视频生成前还要编译 prompt

上游产物是结构化数据，但不同 provider 对 prompt、参数、参考图和时长的要求不同。`PromptCompilerService` 的职责是把结构化决策翻译成 provider 可执行的 `PromptBundle`。

对九宫格图片，它会聚合：

- brief 的风格和 extension
- style bible
- 9 个 cell 的 frame description
- character_list
- human_on_camera 门禁
- aspect_ratio
- 九宫格尺寸、分辨率和 cell 尺寸

输出：

- `positive_prompt`
- `negative_prompt`
- `params`
- `provider`
- `target_type = nine_grid_image`

对视频 clip，它会聚合：

- 当前 shot 的主体、场景、情绪、运镜、时长和台词
- style bible
- character set 或角色描述
- 起始/中间/结束三张参考图
- audio_direction
- provider 能力
- generation mode

输出：

- `positive_prompt`
- `negative_prompt`
- `params.duration_sec`
- `params.aspect_ratio`
- `params.motion_strength`
- `reference_image_urls`
- `reference_asset_ids`
- `provider`
- `target_type = shot_clip`

这个编译层让创作决策和 provider 适配解耦。上游只负责“这个镜头应该是什么”，编译层负责“这个 provider 要怎么描述才更可能生成出来”。

## 10. Clip：从三张关键帧生成一个视频片段

Clip 阶段是高成本执行阶段。它发生在 `storyboard_ready` 之后。

当前主模式是按 shot 逐个生成视频片段：

1. 读取 active shot plan。
2. 找出状态为 `storyboard_ready` 或 `failed` 的 shot。
3. 从 storyboard 九宫格中取该 shot 对应的一整行 3 张图。
4. 决定生成模式：
   - 有 3 张参考图：`multi_image_fusion`
   - 有 1 张参考图：`image_to_video`
   - 无参考图：`text_to_video`
5. 编译 video PromptBundle。
6. 调用 video provider 生成视频。
7. 下载视频结果并上传对象存储。
8. 写入 `Asset` 和 `ClipVersion`。
9. 把 shot 状态改为 `clip_ready`。
10. 通过事件流通知前端该 shot 完成。

这里三张图的作用非常明确：

```text
图片 1 -> 起始状态
图片 2 -> 中间状态
图片 3 -> 结束状态
```

video prompt 会要求模型把这三张图理解为同一个连续镜头的发展过程，而不是三次剪辑或 montage。这样能让视频片段更符合“一个 shot 内连续运动”的语义。

Clip 生成是并发执行的，但有项目锁和并发上限，防止同一个项目重复触发或一次性打爆 provider。

## 11. Timeline：把视频片段合成为预览视频

当所有 clip 都生成成功后，项目进入 `clips_ready`，随后可以合成时间线。

Timeline 阶段做的事情是：

1. 读取所有 active `ClipVersion`。
2. 按对应 `shot_index` 排序。
3. 准备本地 clip 文件；如果本地没有，就从对象存储下载。
4. 如果 ProjectSpec 有音频资产，则把音频作为外部配乐叠加。
5. 如果没有音频资产，则直接拼接 clip，并保留 clip 自带音轨。
6. 调用 FFmpeg 合成 preview。
7. 上传 preview 到对象存储。
8. 写入 `TimelineVersion` 和 `TimelineSegment`。
9. 推进项目到 `timeline_ready`。

Timeline 的核心产物是：

- `preview_asset_id`
- `total_duration_ms`
- `segments`
- `audio_mode = external | embedded`
- 每段的 `shot_id`
- 每段的 `clip_version_id`
- 每段的 `start_ms/end_ms`
- 每段的 `audio_strategy`

这一步把“多个分散视频片段”变成“完整可播放的视频预览”。

## 12. Export：最终导出视频

Export 阶段发生在 `timeline_ready` 之后。它读取当前 active timeline 的 preview asset，按指定分辨率转码导出。

当前支持的分辨率包括：

- `720p`
- `1080p`
- `2K`
- `4K`

导出后会：

- 上传最终视频到对象存储。
- 写入 `Asset(asset_type="export_video")`。
- 写入 `ExportVersion(status="completed")`。
- 更新 `projects.latest_export_version_id`。
- 推进项目到 `export_ready`。

这就是用户最终拿到的视频资产。

## 13. 数据如何在阶段之间传递

VidMuse 后端不是靠大段文本在 agent 之间传来传去，而是用三类机制传递上下文。

第一类是 active version 指针。

`projects` 表只保存每个阶段当前激活的版本 ID，例如：

- `active_project_spec_version_id`
- `active_brief_version_id`
- `active_style_version_id`
- `active_narrative_script_version_id`
- `active_shot_plan_version_id`
- `active_storyboard_version_id`
- `active_timeline_version_id`
- `latest_export_version_id`

这样主项目表保持轻量，各阶段完整内容放在自己的版本表中。下游永远读取 active 版本，历史版本仍可保留。

第二类是 ArtifactRef。

Agent 生成的大 JSON 产物会先写成本地/对象存储 artifact，再用引用传递：

```text
artifact_id
artifact_type
local_path
storage_uri
version_no
summary
```

这样做的原因是：

- 避免把大段 JSON 塞进 LangGraph state。
- Agent 需要审核时可以主动读取真实产物。
- 产物可以落盘、追溯、复查、上传和复用。

第三类是数据库实体。

真正被前端、worker 和后续服务消费的内容会进入数据库：

- `CreativeBriefVersion`
- `StyleBibleVersion`
- `NarrativeScriptVersion`
- `ScenePlanVersion`
- `ShotPlanVersion`
- `Shot`
- `StoryboardVersion`
- `StoryboardFrame`
- `PromptBundle`
- `Asset`
- `ClipVersion`
- `TimelineVersion`
- `TimelineSegment`
- `ExportVersion`

这种设计让后端每个阶段都有可查询的事实来源，而不是只靠临时内存。

## 14. 状态机为什么重要

项目阶段不是 UI 展示用标签，而是后端保护链路正确性的状态机。

主要阶段包括：

```text
created
input_ready
brief_ready
narrative_ready
shot_plan_ready
storyboard_ready
clips_ready
timeline_ready
export_ready
completed
failed
```

状态机解决三类问题：

1. 防止越级执行  
   例如没有 brief 就不能生成 narrative，没有 storyboard 就不能生成 clip。

2. 支持重生成和回退  
   用户修改上游需求时，下游 storyboard、clip、timeline 应该失效或重新生成。

3. 区分可恢复失败  
   视频生成失败后，shot 会标记 `failed`，项目可以进入 `failed`，但允许用户重新触发 clip 生成。

状态机本质上是创作管线的“交通规则”：每一步必须在正确阶段执行，产物才不会引用错误的上游版本。

## 15. 为什么要有人类确认和异步任务

从 brief 到 narrative 的生成成本相对可控，但 storyboard、clip 和 timeline 属于更重的任务：

- storyboard 调用图片 provider。
- clip 调用视频 provider。
- timeline 调用 FFmpeg 并处理大文件。

因此系统把高成本任务通过 `ToolJob` 和 worker 异步执行，并通过事件流给前端推送进度。

这样做有几个好处：

- 用户不需要一直阻塞等待 HTTP 请求。
- 后端可以控制并发、重试和失败恢复。
- 前端可以逐步显示九宫格生成、切分、clip 完成等状态。
- 高成本步骤可以放在用户确认之后再执行。

这也是为什么 Director Agent 不直接生成视频，而是根据项目阶段和用户意图决定下一步动作，再由专门 service/worker 执行。

## 16. 当前链路的设计边界

当前实现的主线是 AI 视频内容生成，不再强制走音乐 MV 流程。旧的音频分析、视觉圣经、角色定妆图等能力在代码中仍有兼容或扩展痕迹，但当前主链路是：

```text
文本/参考图/可选音频需求
  -> brief/style
  -> narrative shots
  -> shot plan
  -> nine-grid storyboard
  -> clip videos
  -> timeline preview
  -> export video
```

当前版本默认单张九宫格和 3 个 shot，是为了先保证端到端闭环稳定。未来如果要扩展到更长视频，可以沿着已有字段自然扩展：

- `grid_count > 1`
- `total_shots_generated > 3`
- 多张九宫格之间的 cell 连续性
- 更多 shot 的分批 clip 生成
- 更复杂的 timeline 结构

因为 `CreativeBriefExtension`、`NarrativeScript.shots`、`ShotPlan`、`StoryboardVersion.grids` 和 `TimelineSegment` 都已经按可扩展结构设计，未来扩展时不需要推翻整体链路。

## 17. 一句话总结

VidMuse 后端的创作理念是：不要把 AI 视频生成当成一次 prompt 调用，而是把它拆成一条可追溯、可确认、可重试、可局部替换的创作生产线。

用户输入负责定义目标；brief 负责确定创意与风格；narrative 负责把创意拆成镜头；shot plan 负责把镜头变成可执行规格；storyboard 负责提供稳定视觉关键帧；clip 负责生成动态视频；timeline 负责组合；export 负责交付。

这条链路的核心价值在于：每个阶段都把上游的不确定性转化为下游可执行的结构化依据，最终让视频生成从“碰运气”变成“有状态、有版本、有约束、有回溯”的工程化流程。
