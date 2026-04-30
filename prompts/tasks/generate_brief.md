---
name: generate_brief
version: 6
layer: tasks
variables:
  - user_prompt
  - target_duration_sec
  - aspect_ratio
  - target_platform
  - target_audience
  - visual_style
---

基于以下用户视频需求，按 system prompt 中的九宫格算法生成 creative_brief + style_bible + extension。

## 用户视频需求描述

{{ user_prompt }}

## 项目参数

- 目标时长：{{ target_duration_sec }} 秒
- 画幅比例：{{ aspect_ratio }}
- 发布平台：{{ target_platform }}
- 目标受众：{{ target_audience }}
- 视觉风格：{{ visual_style }}

## 输出要求

1. **严格按 system prompt 的 JSON 结构**输出（含 creative_brief / style_bible / extension 三个根键）
2. **extension 字段必须含完整算法计算结果**：
   - `allowed_shot_durations_sec` 必须写成当前视频模型支持的时长档位数组
   - `shot_count` 由内容复杂度和目标时长共同决定，不再固定按 10 秒切分
   - `grid_count = ceil(shot_count / 8)`
   - `total_shots_generated = shot_count`
3. **character_list 中每个角色的 appearance 必须详细**——后续九宫格 prompt 会引用，外貌不一致会导致跨 cell 角色漂移
4. **不输出任何解释文字、markdown 标记或代码块包裹**——纯 JSON 字符串

## narrative_mode 选择参考

- 视频有情节 / 故事线 / 角色关系 → `narrative`
- 教程 / 演示 / 科普类，有持续讲解 → `performance`
- 概念可视化 / 品牌展示 / 氛围类 → `atmosphere`
- 多种特征共存 → `mixed`
