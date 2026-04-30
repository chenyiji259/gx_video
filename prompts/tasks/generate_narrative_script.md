---
name: generate_narrative_script
version: "2.0"
description: NarrativeScriptAgent 任务提示词 — 基于 brief 生成按 shot 划分的剧本
variables:
  - user_prompt
  - brief_summary
  - shot_count_total
  - grid_count
  - character_list_json
---

请根据以下信息生成按 shot 划分的视频剧本。

## 用户原始描述

{{ user_prompt }}

## 创意简报摘要

{{ brief_summary }}

## 必须生成的 shot 数量

{{ shot_count_total }} 个 shot（每个 10s，分布在 {{ grid_count }} 张九宫格中）

跨九宫格衔接规则（doc 21 §3.2）：
- 如果 {{ grid_count }} > 1，shot 8 的尾帧 == shot 9 的首帧（物理同一张图）

## 角色清单（来自 brief.extension）

```json
{{ character_list_json }}
```

shot 中出现的角色必须使用上述清单中的 character_id。

---

## 输出要求

按 system prompt 的 JSON 格式输出 shots，shot 数严格等于 {{ shot_count_total }}。
不要输出任何解释文字或 markdown 标记，纯 JSON 字符串。
