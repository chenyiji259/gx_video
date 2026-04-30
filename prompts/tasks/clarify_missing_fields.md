---
name: clarify_missing_fields
version: 1
layer: tasks
variables:
  - missing_fields
  - project_stage
---

当前项目阶段：{{ project_stage }}

以下必填信息尚未提供：

{{ missing_fields }}

请按照重要性从高到低逐一询问用户，每次只问一个问题，语气自然友好。
优先问会阻塞主流程的字段：音频区间 > 输出时长 > 风格方向 > 是否锁定角色 > 是否需要演唱镜头。
