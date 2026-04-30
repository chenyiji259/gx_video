---
name: generate_shot_plan
version: 3
layer: tasks
variables:
  - creative_brief
  - style_bible
  - max_shots
  - target_duration_sec
  - performance_ratio
  # 旧流程变量（已停用）：
  # - audio_analysis_summary
---

基于已确认的 creative brief 和视觉风格，生成详细的镜头计划（Shot Plan）。

## Creative Brief
{{ creative_brief }}

## Style Bible
{{ style_bible }}

## 约束参数
- 最大镜头数：{{ max_shots }}
- 目标时长：{{ target_duration_sec }} 秒
- 演示镜头比例：{{ performance_ratio }}

## 输出要求

输出一个 JSON 对象，包含 `scene_plan` 和 `shot_plan` 两个列表。

**字段映射说明（和数据库字段的对应关系）：**
- `shot_role` → 存入 `shot_type` 字段
- `pace` → 存入 `visual_energy`（slow=low, medium=medium, fast=high）
- `scene_type` → 存入 `section_type`
- `duration_sec` → 乘 1000 得 `duration_ms`

```json
{
  "scene_plan": [
    {"scene_id": "scene_01", "section_type": "intro", "description": "场景描述", "shot_count": 3}
  ],
  "shot_plan": [
    {
      "shot_index": 0,
      "scene_id": "scene_01",
      "scene_type": "intro|main|climax|outro",
      "shot_role": "performance|narrative|atmosphere",
      "subject": "主体描述（引用叙事剧本中的角色/元素）",
      "location": "场景描述（引用叙事剧本中的场景）",
      "emotion": "情绪标签",
      "emotion_intensity": "low|medium|high|very_high",
      "camera_language": "镜头语言（如 slow dolly-in, medium shot）",
      "pace": "slow|medium|fast",
      "visual_energy": "low|medium|high",
      "duration_sec": 8,
      "start_ms": 0,
      "end_ms": 8000
    }
  ]
}
```

**重要约束：**
- `shot_index` 从 0 开始，连续整数
- `duration_sec` 必须从当前视频模型支持的时长档位中选择，不允许随意输出任意秒数
- `start_ms` 和 `end_ms` 基于 `target_duration_sec` 按内容节奏均匀分配，所有 shot 的总时长之和必须等于 `target_duration_sec * 1000`
- `end_ms = start_ms + duration_sec * 1000`（严格对齐，不得重叠）
- `emotion_intensity` 根据该 shot 在整体视频叙事中的情绪位置推断
- `subject` 应引用叙事剧本中定义的角色/主体概念
- `location` 应引用叙事剧本中定义的场景概念
