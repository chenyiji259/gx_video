---
name: review_consistency
version: 1
layer: tasks
variables:
  - style_bible
  - character_set
  - shots_summary
---

对以下项目产物进行一致性检查。

## 风格规格
{{ style_bible }}

## 角色设定
{{ character_set }}

## 待检查镜头摘要
{{ shots_summary }}

## 检查维度

1. **角色一致性**：服装、发型、面部特征在不同镜头间是否漂移
2. **风格一致性**：色调、质感、镜头语言是否与 style bible 吻合
3. **节奏一致性**：镜头时长分配是否与音乐段落节奏匹配

## 输出格式

```json
{
  "issues": [
    {
      "type": "character_drift|style_drift|pacing_mismatch",
      "target_id": "shot_005",
      "severity": "high|medium|low",
      "description": "问题描述"
    }
  ],
  "recommendations": [
    {
      "action": "regenerate_shot|adjust_style|reorder_shots",
      "target_id": "shot_005",
      "reason": "修复理由"
    }
  ],
  "overall_consistency_score": 0.85
}
```
