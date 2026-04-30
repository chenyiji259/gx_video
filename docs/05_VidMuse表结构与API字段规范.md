# VidMuse 表结构与 API 字段规范

> 文档目标：基于前面的多 Agent 架构、项目级记忆、状态机与事件流，定义第一版可开发的数据库表结构、字段约束、索引策略、API 协议与流式接口规范。
>
> 本文档重点回答：
> - 表到底怎么建
> - 字段怎么命名、怎么关联
> - 哪些状态落库，哪些只在图运行态存在
> - API 如何分层
> - 哪些接口采用 OpenAI 兼容协议
> - SSE 流如何设计

---

## 1. 文档范围

本文档覆盖：

- PostgreSQL 主表设计
- Redis / MinIO 的使用边界
- 主键、外键、枚举、索引、幂等键
- 控制面 REST API
- 推理面 OpenAI 兼容 API
- 项目事件 SSE 流

本文档不覆盖：

- 前端页面细节
- 具体 provider SDK 适配代码
- Agent prompt 文本
- 详细开发排期

---

## 2. 基础设计结论

### 2.1 存储层

- 主数据库：`PostgreSQL`
- 队列与缓存：`Redis`
- 对象存储：`MinIO`

说明：

- 第一版统一使用 `MinIO`
- 对象访问统一走 `ObjectStorageAdapter`
- 后续可平滑替换为 `S3 / 阿里云 OSS`

### 2.2 API 分层

API 分成两层：

#### A. 控制面 API

用于：

- 鉴权
- 项目 CRUD
- 资产上传
- 项目状态查询
- 版本切换
- 决策提交
- 时间线、镜头、导出等业务操作

协议：

- 标准 JSON REST API

#### B. 推理面 API

用于：

- 对话式 Agent 入口
- Tool call 输出
- 流式文本/工具事件

协议：

- OpenAI 兼容协议优先
- 主要实现 `/v1/chat/completions`
- `stream=true` 时采用 `text/event-stream`

### 2.3 为什么不把所有 API 都做成 OpenAI 兼容

因为：

- 项目、资产、时间线、版本切换不属于 LLM 标准推理协议
- 强行塞进 `/v1/chat/completions` 会让前后端耦合失控
- OpenAI 兼容协议适合“对话和工具调用”，不适合“完整业务控制面”

所以正确设计是：

- `控制面` 走业务 REST
- `推理面` 走 OpenAI 兼容
- `项目状态更新` 走独立 SSE

---

## 3. 主键、时间戳、命名规范

### 3.1 主键类型

建议统一使用：

- `ULID` 字符串主键

原因：

- 可排序
- 比 UUID 更适合时间序分页
- 前后端传输方便

字段类型建议：

- `varchar(26)` 或 `char(26)`

### 3.2 时间字段

所有核心表统一包含：

- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

版本表至少包含：

- `created_at`

### 3.3 命名规范

表名：

- 全部使用 `snake_case`
- 复数形式

字段名：

- `snake_case`

ID 命名：

- 主键统一 `id`
- 外键统一 `{entity}_id`

版本号：

- `version_no integer not null`

活跃版本标识：

- `is_active boolean not null default false`

---

## 4. 枚举策略

第一版建议：

- 状态字段使用 `varchar`
- 配合 `check constraint`

不建议第一版大量使用 Postgres enum type，原因：

- 迁移成本更高
- 状态演进更麻烦

适合用检查约束的字段：

- `project_status`
- `project_stage`
- `task_status`
- `shot_status`
- `decision_status`
- `asset_type`
- `message_type`

---

## 5. 数据库逻辑分区

建议按以下逻辑模块组织表：

- `auth`
- `project`
- `conversation`
- `artifact`
- `workflow`
- `timeline`
- `billing`
- `event`

物理上第一版可以都放一个 schema，逻辑上按模块划分即可。

---

## 6. 鉴权与用户表

### 6.1 `users`

用途：

- 基础账号密码登录

字段：

- `id varchar(26) pk`
- `username varchar(64) not null unique`
- `password_hash varchar(255) not null`
- `status varchar(32) not null`
- `last_login_at timestamptz null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

约束：

- `status in ('active','disabled')`

索引：

- `unique(username)`

### 6.2 `user_preferences`

用途：

- 仅存轻量偏好

字段：

- `id varchar(26) pk`
- `user_id varchar(26) not null`
- `default_language varchar(16) null`
- `default_aspect_ratio varchar(16) null`
- `default_resolution varchar(16) null`
- `favorite_style_tags jsonb not null default '[]'`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

约束：

- `unique(user_id)`

---

## 7. 项目主表

### 7.1 `projects`

这是系统主聚合根。

字段：

- `id varchar(26) pk`
- `user_id varchar(26) not null`
- `name varchar(255) not null`
- `status varchar(32) not null`
- `current_stage varchar(32) not null`
- `active_project_spec_version_id varchar(26) null`
- `active_audio_analysis_version_id varchar(26) null`
- `active_brief_version_id varchar(26) null`
- `active_style_version_id varchar(26) null`
- `active_character_set_version_id varchar(26) null`
- `active_scene_plan_version_id varchar(26) null`
- `active_shot_plan_version_id varchar(26) null`
- `active_storyboard_version_id varchar(26) null`
- `active_timeline_version_id varchar(26) null`
- `latest_export_version_id varchar(26) null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

约束：

- `status in ('active','archived','failed')`
- `current_stage in ('created','input_ready','audio_analyzed','brief_ready','shot_plan_ready','storyboard_ready','clips_ready','timeline_ready','export_ready','completed','failed')`

索引：

- `idx_projects_user_updated (user_id, updated_at desc)`
- `idx_projects_stage (user_id, current_stage)`

### 7.2 设计说明

`projects` 表保存的是：

- 当前项目全局状态
- 当前各类 active version 指针

不要在 `projects` 里塞大 JSON 内容。  
大内容属于版本表。

---

## 8. 对话与会话表

### 8.1 `conversation_sessions`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `status varchar(32) not null`
- `last_selected_entity_type varchar(32) null`
- `last_selected_entity_id varchar(26) null`
- `pending_decision_id varchar(26) null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

约束：

- `status in ('active','closed')`

索引：

- `idx_conversation_sessions_project (project_id, updated_at desc)`

### 8.2 `conversation_messages`

字段：

- `id varchar(26) pk`
- `session_id varchar(26) not null`
- `role varchar(32) not null`
- `message_type varchar(32) not null`
- `content_text text null`
- `content_json jsonb null`
- `model varchar(128) null`
- `token_usage jsonb null`
- `created_at timestamptz not null`

约束：

- `role in ('user','assistant','tool','system')`
- `message_type in ('user_text','assistant_text','assistant_options','assistant_confirmation','tool_call','tool_result','system_event_summary')`

索引：

- `idx_conversation_messages_session_created (session_id, created_at)`

### 8.3 `session_contexts`

字段：

- `session_id varchar(26) pk`
- `project_id varchar(26) not null`
- `selected_entity_type varchar(32) null`
- `selected_entity_id varchar(26) null`
- `pending_option_set_id varchar(26) null`
- `pending_confirmation_id varchar(26) null`
- `recent_agent_summary jsonb not null default '{}'`
- `updated_at timestamptz not null`

作用：

- 只保存短期交互上下文

---

## 9. 输入规格与资产表

### 9.1 `project_spec_versions`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `version_no integer not null`
- `input_mode varchar(32) not null`
- `audio_asset_id varchar(26) null`
- `audio_start_sec numeric(10,3) not null`
- `audio_end_sec numeric(10,3) not null`
- `user_prompt text not null`
- `output_config jsonb not null`
- `constraints jsonb not null default '{}'`
- `created_by varchar(32) not null`
- `source_event_id varchar(26) null`
- `is_active boolean not null default false`
- `created_at timestamptz not null`

约束：

- `input_mode in ('audio_text','audio_image_text')`
- `unique(project_id, version_no)`

索引：

- `idx_project_spec_versions_project_active (project_id, is_active)`

### 9.2 `assets`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `asset_type varchar(32) not null`
- `bucket_name varchar(128) not null`
- `object_key varchar(512) not null`
- `storage_uri varchar(1024) not null`
- `mime_type varchar(128) not null`
- `size_bytes bigint null`
- `duration_ms integer null`
- `width integer null`
- `height integer null`
- `sha256 varchar(64) null`
- `metadata jsonb not null default '{}'`
- `created_at timestamptz not null`

约束：

- `asset_type in ('audio_original','audio_trimmed','image_reference','style_reference','storyboard_frame','clip_video','export_video','subtitle_file','thumbnail')`

索引：

- `idx_assets_project_type_created (project_id, asset_type, created_at desc)`
- `idx_assets_sha256 (sha256)`

### 9.3 MinIO Key 规范

建议对象路径统一：

```text
projects/{project_id}/assets/{asset_type}/{asset_id}/{filename}
```

例如：

```text
projects/proj_01/assets/clip_video/asset_01/shot_008_v2.mp4
```

---

## 10. 分析与规划版本表

### 10.1 `audio_analysis_versions`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `version_no integer not null`
- `audio_asset_id varchar(26) not null`
- `bpm numeric(8,3) null`
- `beat_map jsonb not null`
- `section_map jsonb not null`
- `energy_curve jsonb not null`
- `lyrics_alignment jsonb not null`
- `raw_payload jsonb not null`
- `quality_summary jsonb not null default '{}'`
- `is_active boolean not null default false`
- `created_at timestamptz not null`

### 10.2 `creative_brief_versions`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `version_no integer not null`
- `title varchar(255) null`
- `summary text not null`
- `narrative_mode varchar(32) not null`
- `performance_ratio numeric(5,2) not null`
- `mood_tags jsonb not null`
- `style_direction text not null`
- `raw_payload jsonb not null`
- `is_active boolean not null default false`
- `created_at timestamptz not null`

### 10.3 `style_bible_versions`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `version_no integer not null`
- `palette jsonb not null`
- `lighting_style text not null`
- `camera_style text not null`
- `film_texture text null`
- `reference_notes text null`
- `raw_payload jsonb not null`
- `is_active boolean not null default false`
- `created_at timestamptz not null`

### 10.4 `character_set_versions`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `version_no integer not null`
- `raw_payload jsonb not null`
- `is_active boolean not null default false`
- `created_at timestamptz not null`

### 10.5 `scene_plan_versions`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `version_no integer not null`
- `raw_payload jsonb not null`
- `is_active boolean not null default false`
- `created_at timestamptz not null`

### 10.6 `shot_plan_versions`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `version_no integer not null`
- `raw_payload jsonb not null`
- `is_active boolean not null default false`
- `created_at timestamptz not null`

---

## 11. Shot 与 Storyboard 表

### 11.1 `shots`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `shot_plan_version_id varchar(26) not null`
- `scene_id varchar(64) null`
- `shot_index integer not null`
- `start_ms integer not null`
- `end_ms integer not null`
- `duration_ms integer not null`
- `section_type varchar(32) not null`
- `lyric_text text null`
- `emotion varchar(128) null`
- `shot_type varchar(32) not null`
- `camera_language text null`
- `visual_energy varchar(32) null`
- `lipsync_required boolean not null default false`
- `character_binding jsonb not null default '[]'`
- `style_binding jsonb not null default '[]'`
- `status varchar(32) not null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

约束：

- `status in ('planned','storyboard_ready','clip_pending','clip_ready','approved','stale','failed')`

索引：

- `idx_shots_project_index (project_id, shot_index)`
- `idx_shots_plan (shot_plan_version_id, shot_index)`
- `idx_shots_status (project_id, status)`

### 11.2 `storyboard_versions`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `version_no integer not null`
- `shot_plan_version_id varchar(26) not null`
- `raw_payload jsonb not null`
- `is_active boolean not null default false`
- `created_at timestamptz not null`

### 11.3 `storyboard_frames`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `storyboard_version_id varchar(26) not null`
- `shot_id varchar(26) not null`
- `asset_id varchar(26) not null`
- `prompt_bundle_id varchar(26) null`
- `frame_index integer not null default 0`
- `metadata jsonb not null default '{}'`
- `created_at timestamptz not null`

索引：

- `idx_storyboard_frames_storyboard_shot (storyboard_version_id, shot_id, frame_index)`

---

## 12. Prompt 与 Clip 表

### 12.1 `prompt_bundles`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `target_type varchar(32) not null`
- `target_id varchar(26) not null`
- `provider varchar(64) not null`
- `positive_prompt text not null`
- `negative_prompt text null`
- `params jsonb not null default '{}'`
- `created_at timestamptz not null`

约束：

- `target_type in ('storyboard_frame','shot_clip','lipsync_clip')`

索引：

- `idx_prompt_bundles_target (target_type, target_id, created_at desc)`

### 12.2 `clip_versions`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `shot_id varchar(26) not null`
- `version_no integer not null`
- `provider varchar(64) not null`
- `generation_mode varchar(32) not null`
- `asset_id varchar(26) not null`
- `duration_ms integer not null`
- `prompt_bundle_id varchar(26) null`
- `quality_score numeric(6,3) null`
- `status varchar(32) not null`
- `is_active boolean not null default false`
- `created_at timestamptz not null`

约束：

- `generation_mode in ('image_to_video','text_to_video','video_to_video','lipsync')`
- `status in ('pending','ready','failed','stale')`
- `unique(shot_id, version_no)`

索引：

- `idx_clip_versions_shot_active (shot_id, is_active)`
- `idx_clip_versions_project_created (project_id, created_at desc)`

---

## 13. Timeline 与导出表

### 13.1 `timeline_versions`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `version_no integer not null`
- `audio_asset_id varchar(26) not null`
- `subtitle_track jsonb not null default '[]'`
- `render_status varchar(32) not null`
- `raw_payload jsonb not null`
- `is_active boolean not null default false`
- `created_at timestamptz not null`

约束：

- `render_status in ('draft','ready','stale','rendering','failed')`

### 13.2 `timeline_segments`

字段：

- `id varchar(26) pk`
- `timeline_version_id varchar(26) not null`
- `shot_id varchar(26) not null`
- `clip_version_id varchar(26) not null`
- `start_ms integer not null`
- `end_ms integer not null`
- `transition_in varchar(32) null`
- `transition_out varchar(32) null`
- `metadata jsonb not null default '{}'`
- `created_at timestamptz not null`

索引：

- `idx_timeline_segments_timeline_start (timeline_version_id, start_ms)`

### 13.3 `export_versions`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `timeline_version_id varchar(26) not null`
- `asset_id varchar(26) not null`
- `resolution varchar(16) not null`
- `status varchar(32) not null`
- `created_at timestamptz not null`

约束：

- `status in ('pending','processing','completed','failed')`

---

## 14. 决策、任务、事件、账本表

### 14.1 `pending_decisions`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `session_id varchar(26) not null`
- `decision_type varchar(64) not null`
- `target_entity_type varchar(32) not null`
- `target_entity_id varchar(26) null`
- `options_payload jsonb not null`
- `default_option_id varchar(64) null`
- `status varchar(32) not null`
- `expires_at timestamptz null`
- `created_at timestamptz not null`

约束：

- `status in ('open','selected','expired','cancelled')`

索引：

- `idx_pending_decisions_project_status (project_id, status, created_at desc)`

### 14.2 `agent_tasks`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `conversation_session_id varchar(26) null`
- `task_type varchar(64) not null`
- `requested_by_agent varchar(64) not null`
- `assigned_agent varchar(64) not null`
- `status varchar(32) not null`
- `input_ref jsonb not null`
- `output_ref jsonb null`
- `error_payload jsonb null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

约束：

- `status in ('pending','running','waiting_human','succeeded','failed','cancelled')`

索引：

- `idx_agent_tasks_project_status (project_id, status, created_at desc)`

### 14.3 `tool_jobs`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `agent_task_id varchar(26) null`
- `tool_name varchar(64) not null`
- `provider varchar(64) null`
- `status varchar(32) not null`
- `input_payload jsonb not null`
- `output_payload jsonb null`
- `idempotency_key varchar(128) not null`
- `retry_count integer not null default 0`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

约束：

- `status in ('pending','running','waiting_human','succeeded','failed','retrying','cancelled')`

索引：

- `unique(idempotency_key)`
- `idx_tool_jobs_project_status (project_id, status, created_at desc)`

### 14.4 `event_logs`

字段：

- `id varchar(26) pk`
- `project_id varchar(26) not null`
- `aggregate_type varchar(32) not null`
- `aggregate_id varchar(26) not null`
- `event_type varchar(64) not null`
- `payload jsonb not null`
- `causation_id varchar(26) null`
- `correlation_id varchar(26) null`
- `created_at timestamptz not null`

索引：

- `idx_event_logs_project_created (project_id, created_at desc)`
- `idx_event_logs_aggregate (aggregate_type, aggregate_id, created_at desc)`

### 14.5 `outbox_events`

字段：

- `id varchar(26) pk`
- `aggregate_type varchar(32) not null`
- `aggregate_id varchar(26) not null`
- `event_type varchar(64) not null`
- `payload jsonb not null`
- `status varchar(32) not null`
- `available_at timestamptz not null`
- `published_at timestamptz null`
- `created_at timestamptz not null`

约束：

- `status in ('pending','published','failed')`

索引：

- `idx_outbox_status_available (status, available_at)`

### 14.6 `credit_ledger`

字段：

- `id varchar(26) pk`
- `user_id varchar(26) not null`
- `project_id varchar(26) null`
- `job_id varchar(26) null`
- `entry_type varchar(32) not null`
- `tool_name varchar(64) null`
- `units numeric(12,3) not null default 0`
- `unit_price numeric(12,3) not null default 0`
- `delta numeric(12,3) not null`
- `status varchar(32) not null`
- `metadata jsonb not null default '{}'`
- `created_at timestamptz not null`

约束：

- `entry_type in ('grant','reserve','commit','refund')`
- `status in ('pending','applied','reverted')`

索引：

- `idx_credit_ledger_user_created (user_id, created_at desc)`
- `idx_credit_ledger_project_created (project_id, created_at desc)`

---

## 15. 关系与外键原则

第一版建议：

- 所有核心 `{entity}_id` 都建外键
- 对 `event_logs`、`outbox_events` 这类高吞吐表，可按性能评估是否弱化部分外键

必须强外键的关系：

- `projects.user_id -> users.id`
- `conversation_sessions.project_id -> projects.id`
- `conversation_messages.session_id -> conversation_sessions.id`
- `project_spec_versions.project_id -> projects.id`
- `assets.project_id -> projects.id`
- `shots.project_id -> projects.id`
- `shots.shot_plan_version_id -> shot_plan_versions.id`
- `storyboard_frames.storyboard_version_id -> storyboard_versions.id`
- `clip_versions.shot_id -> shots.id`
- `timeline_segments.timeline_version_id -> timeline_versions.id`

---

## 16. Active Version 维护规则

### 16.1 规则

- 新版本创建后，不自动切 active，除非流程明确推进
- 一个项目同类版本只能有一个 `is_active = true`
- `projects` 表上的 active 指针为主读取入口

### 16.2 一致性

写入流程应保证：

1. 旧 active 版本 `is_active = false`
2. 新版本 `is_active = true`
3. `projects.active_xxx_version_id` 指向新版本
4. 写入 `event_logs`
5. 同事务写入 `outbox_events`

---

## 17. 控制面 API 规范

### 17.1 基础约定

前缀建议：

- `/api/v1`

鉴权：

- `Authorization: Bearer <jwt>`

幂等：

- 支持 `X-Idempotency-Key`

追踪：

- 支持 `X-Client-Request-Id`
- 服务端返回 `X-Request-Id`

### 17.2 返回结构

成功：

```json
{
  "success": true,
  "data": {},
  "request_id": "req_01"
}
```

失败：

```json
{
  "success": false,
  "error": {
    "code": "state_invalid",
    "message": "Current project stage does not allow this action."
  },
  "request_id": "req_01"
}
```

### 17.3 鉴权接口

#### `POST /api/v1/auth/login`

请求：

```json
{
  "username": "demo",
  "password": "******"
}
```

响应：

```json
{
  "success": true,
  "data": {
    "access_token": "jwt",
    "refresh_token": "jwt",
    "user": {
      "id": "usr_01",
      "username": "demo"
    }
  }
}
```

#### `POST /api/v1/auth/refresh`

#### `POST /api/v1/auth/logout`

### 17.4 项目接口

#### `POST /api/v1/projects`

#### `GET /api/v1/projects`

支持：

- 分页
- `stage`
- `updated_after`

#### `GET /api/v1/projects/{project_id}`

返回：

- 项目基础信息
- active version 指针
- 当前 stage
- pipeline summary

#### `PATCH /api/v1/projects/{project_id}`

可修改：

- `name`
- 归档状态

### 17.5 资产接口

#### `POST /api/v1/projects/{project_id}/assets/upload-init`

返回：

- MinIO 预签名上传参数

#### `POST /api/v1/projects/{project_id}/assets/complete`

#### `GET /api/v1/projects/{project_id}/assets`

### 17.6 项目规格接口

#### `POST /api/v1/projects/{project_id}/spec/versions`

创建新 `project_spec` 版本。

#### `POST /api/v1/projects/{project_id}/spec/activate`

请求：

```json
{
  "version_id": "ps_v3"
}
```

### 17.7 工作流接口

#### `POST /api/v1/projects/{project_id}/workflow/analyze-audio`

#### `POST /api/v1/projects/{project_id}/workflow/generate-brief`

#### `POST /api/v1/projects/{project_id}/workflow/generate-shot-plan`

#### `POST /api/v1/projects/{project_id}/workflow/generate-storyboard`

#### `POST /api/v1/projects/{project_id}/workflow/generate-clips`

#### `POST /api/v1/projects/{project_id}/workflow/compose-timeline`

#### `POST /api/v1/projects/{project_id}/workflow/export`

所有工作流接口返回：

- `agent_task_id`
- `tool_job_ids`
- 是否需要确认
- 估算成本

### 17.8 镜头接口

#### `GET /api/v1/projects/{project_id}/shots`

#### `GET /api/v1/projects/{project_id}/shots/{shot_id}`

#### `PATCH /api/v1/projects/{project_id}/shots/{shot_id}`

请求体是结构化 patch：

```json
{
  "patch": {
    "visual_energy": "high",
    "camera_language": "fast handheld push-in"
  }
}
```

#### `POST /api/v1/projects/{project_id}/shots/{shot_id}/regenerate`

#### `POST /api/v1/projects/{project_id}/shots/{shot_id}/lipsync`

### 17.9 决策接口

#### `GET /api/v1/projects/{project_id}/decisions`

#### `POST /api/v1/projects/{project_id}/decisions/{decision_id}/select`

请求：

```json
{
  "selected_option_id": "style_b"
}
```

### 17.10 版本接口

#### `GET /api/v1/projects/{project_id}/versions`

#### `POST /api/v1/projects/{project_id}/versions/activate`

用于：

- brief 回退
- style 回退
- storyboard 回退
- timeline 回退

### 17.11 事件流接口

#### `GET /api/v1/projects/{project_id}/events/stream`

用途：

- 向前端实时推送项目级状态变化

协议：

- `Content-Type: text/event-stream`

事件类型建议：

- `project.stage.changed`
- `task.updated`
- `decision.requested`
- `timeline.updated`
- `shot.updated`
- `error`

示例：

```text
event: project.stage.changed
data: {"project_id":"proj_01","current_stage":"storyboard_ready"}

event: task.updated
data: {"task_id":"task_01","status":"running"}
```

这个 SSE 流和 OpenAI 兼容聊天流是两条不同的流。

---

## 18. 推理面 OpenAI 兼容 API 规范

### 18.1 设计原则

OpenAI 兼容接口只承载：

- 对话输入
- 多模态消息输入
- 工具定义
- 工具调用输出
- SSE 文本流

不承载：

- 项目 CRUD
- 资产上传
- 版本切换
- 决策查询列表

### 18.2 为什么用 OpenAI 兼容协议

好处：

- 前端/SDK 接入简单
- 便于后续对接通用客户端
- 工具调用格式清晰
- 流式返回范式成熟

### 18.3 主入口：`POST /v1/chat/completions`

我建议第一版优先实现这个兼容端点。

原因：

- 生态兼容最好
- 前端和调试工具最成熟
- 对“用户与 Director Agent 对话”最适合

参考：

- OpenAI Chat Completions API：<https://platform.openai.com/docs/api-reference/chat/create-chat-completion>

### 18.4 请求体兼容策略

兼容字段建议支持：

- `model`
- `messages`
- `tools`
- `tool_choice`
- `stream`
- `temperature`
- `response_format`
- `metadata`

第一版可扩展自定义字段：

- `project_id`
- `conversation_id`
- `selected_entity`

建议放入：

- 顶层 `metadata`
- 或服务端从鉴权上下文解析

推荐请求：

```json
{
  "model": "director-agent",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "从这首歌 75 秒开始做 30 秒 MV，风格更冷一点。"
        }
      ]
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "request_decision",
        "description": "Request user confirmation or selection",
        "parameters": {
          "type": "object",
          "properties": {
            "decision_type": {"type": "string"}
          },
          "required": ["decision_type"]
        }
      }
    }
  ],
  "tool_choice": "auto",
  "stream": true,
  "metadata": {
    "project_id": "proj_01",
    "conversation_id": "sess_01"
  }
}
```

### 18.5 响应兼容策略

非流式时：

- 返回 `chat.completion`

流式时：

- 返回 `chat.completion.chunk`
- 最后一条 `data: [DONE]`

参考：

- OpenAI 文档中 `stream=true` 采用 SSE：<https://platform.openai.com/docs/api-reference/chat/create-chat-completion>

### 18.6 SSE 兼容流规范

响应头：

```http
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

数据格式：

```text
data: {"id":"chatcmpl_01","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant","content":"好的"},"finish_reason":null}]}

data: {"id":"chatcmpl_01","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"，我先分析音频结构。"},"finish_reason":null}]}

data: {"id":"chatcmpl_01","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

### 18.7 Tool Call 兼容策略

如果 Director Agent 决定发起内部动作，可通过 OpenAI 兼容 `tool_calls` 返回：

```json
{
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "tool_calls": [
          {
            "id": "call_01",
            "type": "function",
            "function": {
              "name": "request_decision",
              "arguments": "{\"decision_type\":\"confirm_global_style_change\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ]
}
```

### 18.8 兼容边界

需要强调：

- OpenAI 兼容 API 只是对话入口协议
- 真正的多 Agent、状态机、工具执行在服务端内部完成
- 前端不直接驱动底层专业 Agent

---

## 19. 是否实现 `/v1/responses`

建议：

- 架构上预留
- 第一版主打 `/v1/chat/completions`
- 第二阶段再加 `/v1/responses`

原因：

- `chat/completions` 兼容度更高
- `responses` 更先进，但第一版不是必须

参考：

- OpenAI Responses API：<https://platform.openai.com/docs/api-reference/responses/retrieve>

---

## 20. API 幂等、分页与错误码

### 20.1 幂等

以下接口应支持 `X-Idempotency-Key`：

- 资产上传完成
- 生成工作流触发
- 单镜头重生成
- 导出

### 20.2 分页

列表接口统一支持：

- `limit`
- `after`
- `before`

排序默认：

- `created_at desc`

### 20.3 错误码建议

- `unauthorized`
- `forbidden`
- `not_found`
- `validation_error`
- `state_invalid`
- `decision_required`
- `credits_insufficient`
- `provider_timeout`
- `provider_failed`
- `conflict`
- `idempotency_conflict`

---

## 21. 状态机与表结构的映射

### 21.1 项目状态

落库位置：

- `projects.current_stage`
- `projects.status`

### 21.2 镜头状态

落库位置：

- `shots.status`

### 21.3 任务状态

落库位置：

- `agent_tasks.status`
- `tool_jobs.status`

### 21.4 决策状态

落库位置：

- `pending_decisions.status`

### 21.5 失效状态

落库位置：

- `shots.status = 'stale'`
- `clip_versions.status = 'stale'`
- `timeline_versions.render_status = 'stale'`

---

## 22. OpenAI 兼容协议与项目事件 SSE 的协同

前端建议同时维护两条流：

### 22.1 Chat SSE

来自：

- `/v1/chat/completions`

负责：

- Assistant 文本
- tool call
- tool result 文本反馈

### 22.2 Project SSE

来自：

- `/api/v1/projects/{project_id}/events/stream`

负责：

- Pipeline 阶段变化
- 某个 shot 状态变化
- storyboard/clip/timeline 更新
- 决策卡弹出

### 22.3 为什么要双流

因为：

- OpenAI 兼容聊天流不适合承载完整业务状态
- Pipeline UI 需要细粒度项目事件
- 将两者混在一条 SSE 里会让协议失控

---

## 23. 第一版实施建议

### 23.1 先实现的表

建议第一批先建：

- `users`
- `user_preferences`
- `projects`
- `conversation_sessions`
- `conversation_messages`
- `session_contexts`
- `project_spec_versions`
- `assets`
- `audio_analysis_versions`
- `creative_brief_versions`
- `style_bible_versions`
- `shot_plan_versions`
- `shots`
- `storyboard_versions`
- `storyboard_frames`
- `prompt_bundles`
- `clip_versions`
- `timeline_versions`
- `timeline_segments`
- `pending_decisions`
- `agent_tasks`
- `tool_jobs`
- `event_logs`
- `outbox_events`
- `credit_ledger`

### 23.2 第二批再建

- `character_set_versions`
- `scene_plan_versions`
- `export_versions`

如果时间紧，这几张可以第二批补齐。

---

## 24. 最终拍板建议

现在可以先拍板这几个关键结论：

- 对象存储第一版统一用 `MinIO`
- 业务 API 走 `/api/v1`
- 对话入口走 OpenAI 兼容 `/v1/chat/completions`
- 聊天流和项目事件流分离
- 项目主表只保留 active version 指针，不塞大 JSON
- 所有核心 artifact 都用版本表
- 任务、事件、决策、账本单独建表
- 使用 `ULID` 作为主键
- 状态字段使用字符串 + check 约束

---

## 25. 下一份文档建议

基于当前文档，下一份最合适继续写的是：

- `06_VidMuse多Agent协议与Prompt规范.md`

这份会继续下钻到：

- Director Agent 输入输出
- 专业 Agent 工单协议
- 反问规则
- 选项卡协议
- 确认协议
- Prompt Compiler 分层模板
- 哪些 Agent 必须多模态，哪些不必

---

## 26. 参考资料

- OpenAI Chat Completions API: <https://platform.openai.com/docs/api-reference/chat/create-chat-completion>
- OpenAI Responses API: <https://platform.openai.com/docs/api-reference/responses/retrieve>
- OpenAI API Reference 总览: <https://platform.openai.com/docs/api-reference/>

