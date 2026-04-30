# VidMuse API 参考文档

> 版本：v1.0 | 最后更新：2026-04-03
>
> **Base URL（开发环境）**：`http://localhost:8000`
>
> 所有 `/api/v1/` 接口均需在请求头携带 `Authorization: Bearer <access_token>`，
> 除 `/health`、`/ready`、`/api/v1/auth/login`、`/api/v1/auth/refresh` 外。

---

## 目录

1. [通用规范](#1-通用规范)
2. [系统健康检查](#2-系统健康检查)
3. [鉴权](#3-鉴权)
4. [对话（OpenAI 兼容接口）](#4-对话openai-兼容接口)
5. [项目管理](#5-项目管理)
6. [项目输入规格（ProjectSpec）](#6-项目输入规格projectspec)
7. [资产管理](#7-资产管理)
8. [工作流触发](#8-工作流触发)
9. [音频分析](#9-音频分析)
10. [规划产物 — Brief / Style](#10-规划产物--brief--style)
11. [叙事剧本（Narrative）](#11-叙事剧本narrative)
12. [视觉圣经（Visual Bible）](#12-视觉圣经visual-bible)
13. [镜头管理（Shots）](#13-镜头管理shots)
14. [分镜图（Storyboard）](#14-分镜图storyboard)
15. [视频片段（Clips）](#15-视频片段clips)
16. [口型生成（LipSync）](#16-口型生成lipsync)
17. [时间线（Timeline）](#17-时间线timeline)
18. [导出（Exports）](#18-导出exports)
19. [决策管理（Decisions）](#19-决策管理decisions)
20. [对话会话（Conversation Sessions）](#20-对话会话conversation-sessions)
21. [项目事件流（SSE）](#21-项目事件流sse)
22. [版本管理（Versions）](#22-版本管理versions)
23. [一致性质检（Consistency）](#23-一致性质检consistency)

---

## 1. 通用规范

### 统一响应结构

**成功响应**
```json
{
  "success": true,
  "data": { ... },
  "request_id": "01HXXXXXXXXXXXXXXXXXXXXX"
}
```

**失败响应**
```json
{
  "success": false,
  "error": {
    "code": "not_found",
    "message": "项目不存在"
  },
  "request_id": "01HXXXXXXXXXXXXXXXXXXXXX"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 请求是否成功 |
| data | object | 成功时的返回数据 |
| error.code | string | 错误码（机器可读） |
| error.message | string | 错误描述（人类可读，中文） |
| request_id | string | 请求追踪 ID（ULID，可由客户端通过 `X-Client-Request-Id` 请求头自定义） |

### 常见 HTTP 状态码

| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 401 | 未认证（token 缺失或无效） |
| 402 | 费用确认缺失（高成本操作） |
| 403 | 无权限（账户禁用） |
| 404 | 资源不存在 |
| 422 | 参数校验失败或业务规则不满足 |
| 500 | 服务器内部错误 |
| 503 | 外部依赖不可用 |

---

## 2. 系统健康检查

### GET /health

**存活探针（Liveness Probe）**，不检查外部依赖，始终返回 200。

**请求示例**
```bash
curl http://localhost:8000/health
```

**响应示例**
```json
{
  "status": "up",
  "service": "vidmuse-api",
  "version": "1.0.0",
  "uptime_seconds": 123.4
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | 固定为 `"up"` |
| service | string | 服务名称 |
| version | string | 应用版本号 |
| uptime_seconds | float | 进程已运行时长（秒） |

---

### GET /ready

**就绪探针（Readiness Probe）**，检查所有外部依赖是否正常。全部通过返回 200，任一失败返回 503。

**请求示例**
```bash
curl http://localhost:8000/ready
```

**响应示例（全部正常）**
```json
{
  "status": "ready",
  "checks": {
    "postgres": "ok",
    "redis": "ok",
    "minio": "ok",
    "outbox_publisher": "ok",
    "task_worker": "ok"
  },
  "uptime_seconds": 123.4
}
```

**响应示例（部分故障）**
```json
{
  "status": "degraded",
  "checks": {
    "postgres": "ok",
    "redis": "fail: ConnectionRefusedError: ...",
    "minio": "ok",
    "outbox_publisher": "not_running",
    "task_worker": "ok"
  },
  "uptime_seconds": 123.4
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | `"ready"` 全部正常；`"degraded"` 有故障 |
| checks.postgres | string | Postgres 连接检查结果 |
| checks.redis | string | Redis PING 检查结果 |
| checks.minio | string | MinIO bucket 检查结果 |
| checks.outbox_publisher | string | outbox 后台任务状态（`"ok"` 或 `"not_running"`） |
| checks.task_worker | string | worker 后台任务状态 |

---

## 3. 鉴权

### POST /api/v1/auth/login

用户名密码登录，返回 access token 和 refresh token。

**请求体**
```json
{
  "username": "admin",
  "password": "your_password"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | ✓ | 用户名，1–64 字符 |
| password | string | ✓ | 密码，1–128 字符 |

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 1800
  },
  "request_id": "01HX..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| access_token | string | JWT 访问令牌，有效期 30 分钟 |
| refresh_token | string | JWT 刷新令牌，有效期 7 天 |
| token_type | string | 固定 `"bearer"` |
| expires_in | int | access_token 有效秒数 |

**错误码**

| code | 说明 |
|------|------|
| invalid_credentials | 用户名或密码错误 |
| account_disabled | 账户已禁用 |

---

### POST /api/v1/auth/refresh

用 refresh token 换取新 access token。

**请求体**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 1800
  },
  "request_id": "01HX..."
}
```

---

### POST /api/v1/auth/logout

登出（服务端无状态，客户端应清除本地存储的 token）。

**响应示例（200）**
```json
{
  "success": true,
  "data": { "message": "Logged out successfully" },
  "request_id": "01HX..."
}
```

---

## 4. 对话（OpenAI 兼容接口）

### POST /v1/chat/completions

与项目 Director Agent 对话，兼容 OpenAI Chat Completions API 格式，支持流式和非流式两种模式。

> **路由前缀**：挂载在 `/v1`，完整路径为 `/v1/chat/completions`，与 OpenAI SDK 标准路径兼容。

**请求体**
```json
{
  "model": "vidmuse-director",
  "messages": [
    { "role": "user", "content": "我想做一个赛博朋克风格的 MV" }
  ],
  "stream": false,
  "project_id": "01HPROJECT_ID",
  "session_id": "01HSESSION_ID"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| model | string | 否 | 模型标识，默认 `"vidmuse-director"` |
| messages | array | ✓ | 消息历史，至少含一条 user 消息 |
| messages[].role | string | ✓ | `user` / `assistant` / `system` |
| messages[].content | string | ✓ | 消息文本内容 |
| stream | bool | 否 | 是否流式返回，默认 false |
| project_id | string | ✓ | 关联项目 ID |
| session_id | string | 否 | 指定会话 ID；不填则自动获取或新建当前活跃会话 |

**非流式响应（stream=false）**
```json
{
  "id": "chatcmpl-01HX...",
  "object": "chat.completion",
  "created": 1712345678,
  "model": "vidmuse-director",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "好的！我已分析你的音乐，请选择一个视觉风格方向...",
        "tool_calls": [
          {
            "id": "call_01HX...",
            "type": "function",
            "function": {
              "name": "request_style_decision",
              "arguments": "{\"project_id\": \"01HPROJECT_ID\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "usage": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 }
}
```

**流式响应（stream=true）**

返回 `Content-Type: text/event-stream`，符合 OpenAI SSE 格式：
```
data: {"id":"chatcmpl-01HX...","object":"chat.completion.chunk","created":1712345678,"model":"vidmuse-director","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-01HX...","object":"chat.completion.chunk","created":1712345678,"model":"vidmuse-director","choices":[{"index":0,"delta":{"content":"好的！"},"finish_reason":null}]}

data: {"id":"chatcmpl-01HX...","object":"chat.completion.chunk","created":1712345678,"model":"vidmuse-director","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | completion ID |
| choices[0].message.content | string | assistant 回复文本 |
| choices[0].message.tool_calls | array | 需要前端执行的工具调用（可为 null） |
| choices[0].finish_reason | string | `"stop"` 正常结束；`"tool_calls"` 有待执行工具调用 |
| vidmuse | object | VidMuse 扩展字段（见下） |
| vidmuse.requires_confirmation | bool | 是否需要用户做出决策 |
| vidmuse.pending_decision_id | string/null | 待确认的决策 ID，直接用于 `POST /decisions/{id}/select` |
| vidmuse.decision_options | array | 决策选项列表，每项含 id / title / summary，**无需额外调用 `GET /decisions`** |

**`vidmuse` 字段示例**
```json
{
  "vidmuse": {
    "requires_confirmation": true,
    "pending_decision_id": "01HDECISION_ID",
    "decision_options": [
      { "id": "style_cinematic", "title": "电影感", "summary": "高对比、暖色调、慢推拉" },
      { "id": "style_indie",     "title": "独立风", "summary": "自然光、颗粒感、跟拍运动" },
      { "id": "style_neon",      "title": "霓虹感", "summary": "强饱和、夜景、冷蓝/紫色调" }
    ]
  }
}
```

> **流式响应**：`vidmuse` 字段附加在最后一个 stop chunk 上，前端在收到 `finish_reason` 时读取即可。
> **无决策时**：`requires_confirmation=false`，`pending_decision_id=null`，`decision_options=[]`。

---

## 5. 项目管理

### POST /api/v1/projects

创建新项目，初始阶段为 `created`。

**请求体**
```json
{
  "name": "我的第一个 MV"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | ✓ | 项目名称，1–255 字符 |

**响应示例（201）**
```json
{
  "success": true,
  "data": {
    "id": "01HPROJECT_ID",
    "name": "我的第一个 MV",
    "current_stage": "created",
    "archived": false,
    "active_project_spec_version_id": null,
    "active_audio_analysis_version_id": null,
    "active_brief_version_id": null,
    "active_style_version_id": null,
    "active_shot_plan_version_id": null,
    "active_storyboard_version_id": null,
    "active_timeline_version_id": null,
    "latest_export_version_id": null,
    "created_at": "2026-04-03T12:00:00Z",
    "updated_at": "2026-04-03T12:00:00Z"
  },
  "request_id": "01HX..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 项目 ID（ULID） |
| current_stage | string | 当前 pipeline 阶段（见下方阶段说明） |
| archived | bool | 是否已归档 |
| active_*_version_id | string/null | 各产物的当前激活版本 ID 指针 |

**Pipeline 阶段枚举**

| 阶段 | 说明 |
|------|------|
| created | 初始，未设置输入 |
| input_ready | 音频/Prompt 输入完整，等待分析 |
| audio_analyzed | 音频分析完成 |
| brief_ready | 创意方案和风格已生成 |
| narrative_ready | 叙事剧本已生成 |
| visual_bible_ready | 视觉圣经已确认 |
| shot_plan_ready | 镜头计划已生成 |
| storyboard_ready | 分镜图已生成 |
| clips_ready | 视频片段已生成 |
| timeline_ready | 时间线已合成 |
| export_ready | 视频导出完成 |

---

### GET /api/v1/projects

查询当前用户的项目列表（游标分页，按 updated_at 倒序）。

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| limit | int | 20 | 每页条数（1–100） |
| after | string | — | 游标分页：上一页最后一条项目的 ID |
| include_archived | bool | false | 是否包含已归档项目 |

**请求示例**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/projects?limit=10&include_archived=false"
```

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "01HPROJECT_ID",
        "name": "我的第一个 MV",
        "current_stage": "audio_analyzed",
        "archived": false,
        "created_at": "2026-04-03T12:00:00Z",
        "updated_at": "2026-04-03T14:00:00Z"
      }
    ],
    "has_more": false,
    "next_cursor": null
  },
  "request_id": "01HX..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| items | array | 项目列表 |
| has_more | bool | 是否还有更多数据 |
| next_cursor | string/null | 下一页游标（传入 `after` 参数使用） |

---

### GET /api/v1/projects/{project_id}

查询单个项目详情。

**响应示例（200）** —— 同 POST /api/v1/projects 返回的数据结构。

---

### PATCH /api/v1/projects/{project_id}

更新项目名称或归档状态。两个字段至少传一个。

**请求体**
```json
{
  "name": "新名称",
  "archived": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 至少一个 | 新项目名称，1–255 字符 |
| archived | bool | 至少一个 | true=归档，false=恢复 |

---

## 6. 项目输入规格（ProjectSpec）

### POST /api/v1/projects/{project_id}/spec/versions

创建新的 ProjectSpec 版本（不自动激活）。

**请求体**
```json
{
  "input_mode": "audio_text",
  "audio_asset_id": "01HASSET_ID",
  "audio_start_sec": 0.0,
  "audio_end_sec": 45.0,
  "user_prompt": "赛博朋克风格，主角在霓虹灯下奔跑，节奏感强",
  "output_config": {
    "aspect_ratio": "16:9",
    "resolution": "1080p",
    "target_duration_sec": 45
  },
  "reference_image_asset_ids": ["01HIMAGE_ASSET_ID"]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| input_mode | string | 否 | `audio_text`（默认）或 `audio_image_text` |
| audio_asset_id | string | 否 | 已上传的音频资产 ID |
| audio_start_sec | float | 否 | 音频起始时间（秒），默认 0.0 |
| audio_end_sec | float | 否 | 音频结束时间（秒），须大于 start |
| user_prompt | string | 否 | 用户创意描述，最长 2000 字符 |
| output_config | object | 否 | 输出配置（aspect_ratio / resolution / target_duration_sec） |
| reference_image_asset_ids | array | 否 | 参考图 asset_id 列表（最多 5 张），有值时 input_mode 自动切换为 audio_image_text |
| constraints | object | 否 | 附加约束（可选） |

**响应示例（201）**
```json
{
  "success": true,
  "data": {
    "id": "01HSPEC_ID",
    "project_id": "01HPROJECT_ID",
    "version_no": 1,
    "input_mode": "audio_text",
    "audio_asset_id": "01HASSET_ID",
    "audio_start_sec": 0.0,
    "audio_end_sec": 45.0,
    "user_prompt": "赛博朋克风格...",
    "is_active": false,
    "created_at": "2026-04-03T12:00:00Z"
  },
  "request_id": "01HX..."
}
```

---

### POST /api/v1/projects/{project_id}/spec/activate

激活指定 ProjectSpec 版本。

满足以下三个条件时自动推进项目到 `input_ready`：
- `audio_asset_id` 不为空
- `audio_end_sec > audio_start_sec`
- `user_prompt` 不为空

**请求体**
```json
{
  "version_id": "01HSPEC_ID"
}
```

**响应示例（200）** —— 返回激活后的 spec 对象，`is_active: true`。

---

### GET /api/v1/projects/{project_id}/spec/active

获取当前激活的 ProjectSpec 版本详情。

---

## 7. 资产管理

资产上传采用**两步式直传**：
1. POST `upload-init` 获取预签名 URL
2. 客户端直接 PUT 文件到预签名 URL（绕过后端）
3. POST `complete` 通知后端确认落库

### POST /api/v1/projects/{project_id}/assets/upload-init

步骤一：申请上传槽位，获取 MinIO PUT 预签名 URL（有效期 30 分钟）。

**请求体**
```json
{
  "filename": "my_song.mp3",
  "content_type": "audio/mpeg",
  "asset_type": "audio_original"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| filename | string | ✓ | 原始文件名（含扩展名） |
| content_type | string | ✓ | MIME 类型，如 `audio/mpeg`、`image/jpeg` |
| asset_type | string | 否 | 资产类型（见下）；留空由后端根据 content_type 自动推断 |

**asset_type 枚举**

| 值 | 说明 |
|----|------|
| audio_original | 原始音频文件 |
| image_reference | 角色参考图 |
| style_reference | 风格参考图 |
| storyboard_frame | 分镜图帧 |
| clip_video | 视频片段 |
| timeline_preview | 时间线预览视频 |
| export_video | 导出视频 |

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "asset_id": "01HASSET_ID",
    "object_key": "projects/01HPROJECT/assets/01HASSET_ID/my_song.mp3",
    "bucket_name": "vidmuse",
    "upload_url": "https://minio.example.com/vidmuse/projects/...?X-Amz-Signature=...",
    "expires_in": 1800
  },
  "request_id": "01HX..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| asset_id | string | 预分配的资产 ID，complete 时需要回传 |
| object_key | string | MinIO 对象路径，complete 时需要回传 |
| bucket_name | string | MinIO bucket 名称，complete 时需要回传 |
| upload_url | string | PUT 预签名 URL，客户端直接 PUT 文件到此地址 |
| expires_in | int | upload_url 有效期（秒） |

---

### POST /api/v1/projects/{project_id}/assets/complete

步骤三：通知后端上传完成，落库 Asset 记录。

**请求体**
```json
{
  "asset_id": "01HASSET_ID",
  "object_key": "projects/01HPROJECT/assets/01HASSET_ID/my_song.mp3",
  "bucket_name": "vidmuse",
  "filename": "my_song.mp3",
  "content_type": "audio/mpeg",
  "asset_type": "audio_original",
  "duration_ms": 45000,
  "sha256": "abc123..."
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| asset_id | string | ✓ | upload-init 返回的 asset_id |
| object_key | string | ✓ | upload-init 返回的 object_key |
| bucket_name | string | ✓ | upload-init 返回的 bucket_name |
| filename | string | ✓ | 原始文件名 |
| content_type | string | ✓ | MIME 类型 |
| asset_type | string | ✓ | 资产类型 |
| sha256 | string | 否 | 文件 SHA-256（用于去重） |
| duration_ms | int | 否 | 音视频时长（毫秒） |
| width | int | 否 | 图片/视频宽度（像素） |
| height | int | 否 | 图片/视频高度（像素） |

**响应示例（201）**
```json
{
  "success": true,
  "data": {
    "id": "01HASSET_ID",
    "project_id": "01HPROJECT_ID",
    "asset_type": "audio_original",
    "filename": "my_song.mp3",
    "content_type": "audio/mpeg",
    "storage_uri": "https://minio.example.com/vidmuse/projects/.../my_song.mp3",
    "duration_ms": 45000,
    "sha256": "abc123...",
    "created_at": "2026-04-03T12:00:00Z"
  },
  "request_id": "01HX..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| storage_uri | string | 资产永久可访问 URL（MinIO 公开读直链） |

---

### GET /api/v1/projects/{project_id}/assets

列出项目下的资产（按创建时间倒序）。

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| asset_type | string | — | 按资产类型过滤 |
| limit | int | 50 | 最多返回条数（1–200） |

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "items": [ { ...asset对象... } ],
    "count": 3
  },
  "request_id": "01HX..."
}
```

---

## 8. 工作流触发

所有工作流触发接口均需要先完成对应的决策确认（`decisions` API），否则返回 `decision_required` 错误。

### POST /api/v1/projects/{project_id}/workflow/analyze-audio

触发音频分析（异步，返回 job_id）。

> 前置：项目处于 `input_ready` 阶段。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "job_id": "01HJOB_ID",
    "status": "pending",
    "message": "音频分析任务已提交，完成后将通过 SSE 推送结果并由导演自动汇报。"
  },
  "request_id": "01HX..."
}
```

---

### POST /api/v1/projects/{project_id}/workflow/generate-brief

触发 brief + style 生成（同步）。

> 前置：`select_style_direction` 决策已 selected。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "brief_version_id": "01HBRIEF_ID",
    "style_version_id": "01HSTYLE_ID",
    "brief_version_no": 1,
    "title": "霓虹都市追逐曲",
    "summary": "以赛博朋克城市夜景为主线...",
    "message": "创意方案已生成，项目已推进到 brief_ready 阶段。"
  },
  "request_id": "01HX..."
}
```

---

### POST /api/v1/projects/{project_id}/workflow/generate-narrative

触发叙事剧本生成（异步）。

> 前置：`confirm_brief` 决策已 selected（且未选 regenerate）。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "job_id": "01HJOB_ID",
    "status": "pending",
    "message": "叙事剧本生成任务已提交，完成后将通过 SSE 推送结果并由导演自动汇报。"
  },
  "request_id": "01HX..."
}
```

---

### POST /api/v1/projects/{project_id}/workflow/generate-shot-plan

触发镜头计划生成（同步）。

> 前置：`confirm_brief` 决策已 selected（且选 confirm）。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "scene_version_id": "01HSCENE_ID",
    "shot_plan_version_id": "01HSHOT_PLAN_ID",
    "shot_count": 12,
    "message": "镜头计划已生成（12 个镜头），项目已推进到 shot_plan_ready 阶段。"
  },
  "request_id": "01HX..."
}
```

---

### POST /api/v1/projects/{project_id}/workflow/generate-storyboard

触发分镜图生成（异步，返回 job_id）。

> 前置：`confirm_shot_plan` 决策已 selected。耗时 2–5 分钟。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "job_id": "01HJOB_ID",
    "status": "submitted",
    "message": "分镜图生成任务已提交，通常需要 2-5 分钟，完成后 Director 将自动汇报。"
  },
  "request_id": "01HX..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | `submitted`（新提交）或 `already_running`（任务已在队列中） |

---

### POST /api/v1/projects/{project_id}/workflow/generate-clips

触发视频片段生成（异步）。高成本操作，耗时 5–15 分钟。

> 前置：`confirm_storyboard` 决策已 selected。

**响应示例（200）** —— 同 generate-storyboard 格式。

---

### POST /api/v1/projects/{project_id}/workflow/generate-timeline

触发时间线合成（同步）。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "timeline_version_id": "01HTL_ID",
    "version_no": 1,
    "segment_count": 12,
    "total_duration_ms": 45000,
    "message": "时间线已合成，项目已推进到 timeline_ready 阶段。"
  },
  "request_id": "01HX..."
}
```

---

## 9. 音频分析

### GET /api/v1/projects/{project_id}/audio-analysis/active

返回当前激活的音频分析版本。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "id": "01HAA_ID",
    "version_no": 1,
    "bpm": 128.5,
    "beat_map": [0.0, 0.469, 0.938, ...],
    "section_map": [
      { "start": 0.0, "end": 16.0, "label": "intro" },
      { "start": 16.0, "end": 32.0, "label": "verse" }
    ],
    "energy_curve": [0.3, 0.5, 0.7, ...],
    "lyrics_alignment": [
      { "word": "城市", "start": 2.1, "end": 2.5 }
    ],
    "quality_summary": "BPM 128，强节拍驱动，共 3 段（intro/verse/chorus），整体高能量...",
    "is_active": true,
    "created_at": "2026-04-03T12:30:00Z"
  },
  "request_id": "01HX..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| bpm | float | 节拍速度（每分钟节拍数） |
| beat_map | array[float] | 每个节拍的时间戳（秒） |
| section_map | array | 音乐段落列表，每项含 start（秒）、end（秒）、label（intro/verse/chorus等） |
| energy_curve | array[float] | 能量曲线采样值列表 |
| lyrics_alignment | array | 歌词对齐结果，每项含 word、start、end（秒） |
| quality_summary | string | LLM 生成的自然语言音乐摘要，供 Director Agent 使用 |

---

## 10. 规划产物 — Brief / Style

### GET /api/v1/projects/{project_id}/brief/active

返回当前激活的 Creative Brief 版本。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "id": "01HBRIEF_ID",
    "version_no": 1,
    "title": "霓虹都市追逐曲",
    "summary": "以赛博朋克城市夜景为主线，主角在霓虹灯下奔跑...",
    "narrative_mode": "performance",
    "performance_ratio": 0.6,
    "mood_tags": ["dark", "energetic", "neon"],
    "style_direction": "style_neon",
    "raw_payload": { ... },
    "is_active": true,
    "created_at": "2026-04-03T13:00:00Z"
  },
  "request_id": "01HX..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| title | string | 创意方案标题 |
| summary | string | 方案摘要描述 |
| narrative_mode | string | 叙事模式：`performance`（表演）/ `narrative`（叙事）/ `mixed` |
| performance_ratio | float | 表演镜头占比（0.0–1.0） |
| mood_tags | array[string] | 情绪标签列表 |
| style_direction | string | 用户选择的风格方向 ID |
| raw_payload | object | LLM 生成的完整原始 JSON |

---

### GET /api/v1/projects/{project_id}/style/active

返回当前激活的 Style Bible 版本。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "id": "01HSTYLE_ID",
    "version_no": 1,
    "palette": { "primary": "#FF00FF", "secondary": "#00FFFF", "background": "#0A0A1A" },
    "lighting_style": "neon backlight, high contrast",
    "camera_style": "handheld, dutch angle, fast cut",
    "film_texture": "grain, vignette, chromatic aberration",
    "reference_notes": "参考《银翼杀手 2049》的色调...",
    "raw_payload": { ... },
    "is_active": true,
    "created_at": "2026-04-03T13:00:00Z"
  },
  "request_id": "01HX..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| palette | object | 颜色调色板（primary/secondary/background 等色值） |
| lighting_style | string | 灯光风格描述 |
| camera_style | string | 镜头运动风格描述 |
| film_texture | string | 胶片质感描述 |
| reference_notes | string | 风格参考说明 |

---

## 11. 叙事剧本（Narrative）

### GET /api/v1/projects/{project_id}/narrative/active

返回当前激活的叙事剧本版本。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "id": "01HNARRATIVE_ID",
    "version_no": 1,
    "story_arc": "主角在霓虹都市中奔跑，逃离追杀...",
    "characters": [
      { "character_id": "char_01", "name": "Nova", "role": "protagonist", "description": "..." }
    ],
    "scenes": [
      { "scene_id": "scene_01", "title": "序幕", "location": "city_street", "mood": "tense" }
    ],
    "section_mapping": { "intro": "scene_01", "verse": "scene_02" },
    "is_active": true,
    "created_at": "2026-04-03T13:30:00Z"
  },
  "request_id": "01HX..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| story_arc | string | 故事弧线总览 |
| characters | array | 角色列表，每项含 character_id、name、role、description |
| scenes | array | 场景列表，每项含 scene_id、title、location、mood |
| section_mapping | object | 音乐段落 → 场景 ID 映射 |

---

## 12. 视觉圣经（Visual Bible）

### GET /api/v1/projects/{project_id}/visual-bible/active

返回当前激活的 CharacterSetVersion（视觉圣经）。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "id": "01HCSV_ID",
    "version_no": 1,
    "characters": [
      {
        "character_id": "char_01",
        "character_name": "Nova",
        "active_reference_asset_id": "01HASSET_ID",
        "image_analysis": { "type": "full_body", "style": "cyberpunk" }
      }
    ],
    "scenes": [
      {
        "scene_id": "scene_01",
        "scene_name": "城市街道",
        "active_reference_asset_id": "01HSCENE_ASSET_ID"
      }
    ],
    "confirmed_at": "2026-04-03T14:00:00Z",
    "is_active": true,
    "created_at": "2026-04-03T13:45:00Z"
  },
  "request_id": "01HX..."
}
```

---

### POST /api/v1/projects/{project_id}/visual-bible/init-from-narrative

从激活的叙事剧本初始化空视觉圣经，提取角色和场景骨架。

**无请求体**

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "visual_bible_version_id": "01HCSV_ID",
    "version_no": 1,
    "character_count": 2,
    "scene_count": 3,
    "message": "视觉圣经已从叙事剧本初始化，可以开始生成参考图。"
  }
}
```

---

### POST /api/v1/projects/{project_id}/visual-bible/generate-character-ref

为指定角色提交参考图生成任务（异步）。

**请求体**
```json
{
  "character_id": "char_01",
  "generation_mode": "text_to_image",
  "source_image_hint": "赛博朋克女性，霓虹灯下，长发",
  "provider_name": "fal_ai"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| character_id | string | ✓ | 目标角色 ID |
| generation_mode | string | 否 | `text_to_image` 或 `image_to_image` |
| source_image_url | string | 否 | 参考图 URL（image_to_image 模式使用） |
| source_image_hint | string | 否 | 文字提示 |
| provider_name | string | 否 | 指定图片提供商（如 `fal_ai`） |

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "job_id": "01HJOB_ID",
    "character_id": "char_01",
    "is_queued": true,
    "message": "角色参考图生成任务已提交（预计 2 分钟），请通过 SSE 监听进度。"
  }
}
```

---

### POST /api/v1/projects/{project_id}/visual-bible/generate-scene-ref

为指定场景提交参考图生成任务（异步）。

**请求体**
```json
{
  "scene_id": "scene_01",
  "provider_name": "fal_ai"
}
```

---

### POST /api/v1/projects/{project_id}/visual-bible/confirm

确认视觉圣经，推进项目到 `visual_bible_ready`。

**无请求体**

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "visual_bible_version_id": "01HCSV_ID",
    "confirmed_at": "2026-04-03T14:00:00Z",
    "message": "视觉圣经已确认，项目已推进到 visual_bible_ready 阶段。"
  }
}
```

---

### POST /api/v1/projects/{project_id}/visual-bible/analyze-reference-image

调用多模态 AI 分析已上传的参考图，返回图片类型判断结果（全身/半身/头像等）。

**请求体**
```json
{
  "asset_id": "01HASSET_ID",
  "character_id": "char_01"
}
```

---

### POST /api/v1/projects/{project_id}/visual-bible/generate-costume-ref

为指定角色造型生成参考图（异步）。

**请求体**
```json
{
  "character_id": "char_01",
  "costume_id": "costume_01",
  "generation_mode": "image_to_image",
  "source_image_url": "https://..."
}
```

---

### POST /api/v1/projects/{project_id}/visual-bible/auto-setup-costumes

一键自动设置多造型（Omni 驱动完整闭环，异步）。

**请求体**
```json
{
  "skip_image_analysis": false
}
```

---

## 13. 镜头管理（Shots）

### GET /api/v1/projects/{project_id}/shots

返回项目镜头列表（按 shot_index 升序）。

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| limit | int | 50 | 每页条数（1–200） |
| offset | int | 0 | 偏移量 |
| status | string | — | 按状态过滤（pending/storyboard_ready/clip_ready/stale/failed） |

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "01HSHOT_ID",
        "project_id": "01HPROJECT_ID",
        "shot_plan_version_id": "01HSHOT_PLAN_ID",
        "scene_id": "scene_01",
        "shot_index": 0,
        "start_ms": 0,
        "end_ms": 3750,
        "duration_ms": 3750,
        "section_type": "intro",
        "lyric_text": "城市的霓虹",
        "emotion": "melancholy",
        "shot_type": "wide",
        "camera_language": "slow push-in",
        "visual_energy": "low",
        "lipsync_required": false,
        "character_binding": ["char_01"],
        "style_binding": [],
        "status": "clip_ready",
        "created_at": "2026-04-03T13:00:00Z",
        "updated_at": "2026-04-03T15:00:00Z"
      }
    ],
    "total": 12,
    "limit": 50,
    "offset": 0,
    "has_more": false
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| shot_index | int | 镜头序号（从 0 开始） |
| start_ms | int | 对应音频起始时间（毫秒） |
| end_ms | int | 对应音频结束时间（毫秒） |
| section_type | string | 所属音乐段落（intro/verse/chorus等） |
| lyric_text | string | 该镜头对应的歌词片段 |
| emotion | string | 情绪标签 |
| shot_type | string | 景别（wide/medium/close_up 等） |
| camera_language | string | 镜头运动描述 |
| visual_energy | string | 视觉能量（low/medium/high） |
| lipsync_required | bool | 是否需要口型驱动 |
| character_binding | array | 绑定的角色 ID 列表 |
| style_binding | array | 绑定的风格约束列表 |
| status | string | 镜头状态（pending/storyboard_ready/clip_ready/stale/failed） |

---

### GET /api/v1/projects/{project_id}/shots/{shot_id}

返回单个镜头详情，字段与列表项相同。

---

### PATCH /api/v1/projects/{project_id}/shots/{shot_id}

修改单个镜头的语义字段，触发下游 clip 的 stale 标记。

**可修改字段**：`emotion`、`shot_type`、`camera_language`、`visual_energy`、`lyric_text`、`lipsync_required`、`character_binding`、`style_binding`。

**请求体**
```json
{
  "patch": {
    "emotion": "euphoric",
    "camera_language": "fast handheld tracking"
  }
}
```

**响应示例（200）** —— 返回修改后的 shot 对象，附加 `message` 字段说明下游影响。

---

### POST /api/v1/projects/{project_id}/shots/{shot_id}/regenerate

重新生成单个镜头的 clip（高成本操作）。

支持的镜头状态：`stale`、`clip_ready`、`failed`、`storyboard_ready`。

**请求头（可选）**

| 请求头 | 说明 |
|--------|------|
| X-Idempotency-Key | 幂等键，防止重复触发生成 |

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "clip_version_id": "01HCLIP_ID",
    "shot_id": "01HSHOT_ID",
    "version_no": 2,
    "provider": "kling_v2",
    "generation_mode": "text_to_video",
    "asset_id": "01HASSET_ID",
    "duration_ms": 3750,
    "status": "ready",
    "is_active": true,
    "created_at": "2026-04-03T16:00:00Z",
    "message": "clip 重生成完成。如有 active timeline，对应 segment 已更新，timeline 标记为 stale。"
  }
}
```

---

## 14. 分镜图（Storyboard）

### GET /api/v1/projects/{project_id}/storyboard/active

返回当前激活的 storyboard 版本摘要。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "version_id": "01HSTORYBOARD_ID",
    "version_no": 1,
    "project_id": "01HPROJECT_ID",
    "shot_plan_version_id": "01HSHOT_PLAN_ID",
    "frame_count": 12,
    "is_active": true,
    "created_at": "2026-04-03T15:00:00Z"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| frame_count | int | 分镜帧总数（每个镜头对应一帧） |
| shot_plan_version_id | string | 生成此版本所用的 shot_plan 版本 ID |

---

### GET /api/v1/projects/{project_id}/storyboard-frames

分页列出当前激活 storyboard 版本的所有帧（含图片 URL）。

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| limit | int | 50 | 每页条数（1–200） |
| offset | int | 0 | 偏移量 |

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "storyboard_version_id": "01HSTORYBOARD_ID",
    "version_no": 1,
    "total": 12,
    "limit": 50,
    "offset": 0,
    "has_more": false,
    "frames": [
      {
        "id": "01HFRAME_ID",
        "shot_id": "01HSHOT_ID",
        "asset_id": "01HASSET_ID",
        "storage_uri": "https://minio.example.com/vidmuse/projects/.../frame_0.jpg",
        "prompt_bundle_id": "01HPROMPT_BUNDLE_ID",
        "frame_index": 0,
        "metadata": { "provider": "fal_ai", "seed": 12345 },
        "created_at": "2026-04-03T15:10:00Z"
      }
    ]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| storage_uri | string | 分镜帧图片的永久可访问 URL，前端直接用于 `<img>` 加载 |
| frame_index | int | 帧序号（与 shot_index 对应） |
| metadata | object | 生成元信息（provider / seed / prompt 摘要等） |

---

## 15. 视频片段（Clips）

### GET /api/v1/projects/{project_id}/clips

返回项目内所有激活 ClipVersion（每个 shot 的最新版本）。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "clips": [
      {
        "id": "01HCLIP_ID",
        "shot_id": "01HSHOT_ID",
        "version_no": 1,
        "provider": "kling_v2",
        "generation_mode": "text_to_video",
        "asset_id": "01HASSET_ID",
        "storage_uri": "https://minio.example.com/.../clip_0.mp4",
        "duration_ms": 3750,
        "status": "ready",
        "is_active": true,
        "created_at": "2026-04-03T15:30:00Z"
      }
    ],
    "count": 12
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| provider | string | 生成使用的视频提供商（kling_v2 / minimax_video 等） |
| generation_mode | string | 生成模式（text_to_video / image_to_video / lipsync） |
| storage_uri | string | 视频片段永久 URL |

---

### GET /api/v1/projects/{project_id}/clips/{clip_id}

返回单个 ClipVersion 详情，含 `prompt_bundle_id`。

---

## 16. 口型生成（LipSync）

### POST /api/v1/projects/{project_id}/shots/{shot_id}/lipsync

为指定 shot 生成口型驱动视频 clip（高成本操作）。

> 前置：`shot.lipsync_required=true`；shot 状态须为 `storyboard_ready` / `clip_ready` / `stale` / `failed`；项目须有激活的 storyboard frame 作为正脸参考图。
>
> 若未通过费用确认将返回 402 `cost_confirmation_required`。

**响应示例（201）**
```json
{
  "clip_version_id": "01HCLIP_ID",
  "shot_id": "01HSHOT_ID",
  "generation_mode": "lipsync",
  "duration_ms": 3750,
  "asset_id": "01HASSET_ID",
  "status": "ready"
}
```

> 注意：此接口直接返回对象（非 `success/data` 包装格式）。

---

### GET /api/v1/projects/{project_id}/shots/lipsync-candidates

列出项目中 `lipsync_required=true` 的所有 shots。

**响应示例（200）**
```json
{
  "project_id": "01HPROJECT_ID",
  "candidates": [
    {
      "shot_id": "01HSHOT_ID",
      "shot_index": 3,
      "status": "storyboard_ready",
      "duration_ms": 3750,
      "emotion": "passionate",
      "lipsync_required": true
    }
  ],
  "total": 2
}
```

---

## 17. 时间线（Timeline）

### POST /api/v1/projects/{project_id}/timeline/compose

**用户手动触发**时间线合成（异步 dispatch，不经过 AI 对话流）。这是前端「合成完整视频」按钮对应的接口。

> 前置：项目处于 `clips_ready` 或 `timeline_ready`（重新合成）阶段。
> 合成完成后通过 SSE `project_timeline_ready` 事件通知，再调 `GET /timeline/active` 获取 `preview_uri`。

**无请求体**

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "job_id": "01HJOB_ID",
    "is_new": true,
    "message": "时间线合成任务已提交，请通过 SSE 监听 timeline_ready 事件。"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| job_id | string | Worker 任务 ID |
| is_new | bool | true=新提交；false=已有相同任务在运行 |

> **与 `POST /workflow/generate-timeline` 的区别**：
> - `/timeline/compose`：用户主动触发，**异步** dispatch，前端点按钮用这个
> - `/workflow/generate-timeline`：Director AI 在对话流中触发，**同步**执行

---

### GET /api/v1/projects/{project_id}/timeline/active

返回当前激活的 timeline 版本及 preview URL。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "version_id": "01HTL_ID",
    "version_no": 1,
    "project_id": "01HPROJECT_ID",
    "render_status": "ready",
    "total_duration_ms": 45000,
    "segment_count": 12,
    "preview_uri": "https://minio.example.com/.../preview.mp4",
    "is_active": true,
    "created_at": "2026-04-03T17:00:00Z"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| render_status | string | `ready`（可用）/ `stale`（有上游 clip 更新，需重新合成） |
| total_duration_ms | int | 整个时间线总时长（毫秒） |
| segment_count | int | segment 数量 |
| preview_uri | string/null | 预览视频 URL（如有） |

---

### GET /api/v1/projects/{project_id}/timeline/segments

返回当前激活 timeline 的所有 segments（按 start_ms 升序）。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "timeline_version_id": "01HTL_ID",
    "version_no": 1,
    "segments": [
      {
        "id": "01HSEG_ID",
        "shot_id": "01HSHOT_ID",
        "clip_version_id": "01HCLIP_ID",
        "start_ms": 0,
        "end_ms": 3750,
        "duration_ms": 3750,
        "transition_in": "cut",
        "transition_out": "cut"
      }
    ]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| start_ms | int | 在时间线中的起始时间（毫秒） |
| end_ms | int | 在时间线中的结束时间（毫秒） |
| transition_in | string | 入场转场效果（cut / fade / dissolve） |
| transition_out | string | 出场转场效果 |

---

## 18. 导出（Exports）

### POST /api/v1/projects/{project_id}/exports

触发视频导出。导出为高成本操作，首次触发可能返回 402 要求费用确认。

**请求体**
```json
{
  "resolution": "720p"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| resolution | string | `"720p"`（默认）或 `"1080p"` |

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "export_version_id": "01HEXPORT_ID",
    "resolution": "720p",
    "status": "ready",
    "storage_uri": "https://minio.example.com/.../export_720p.mp4",
    "created_at": "2026-04-03T17:30:00Z",
    "message": "导出完成（720p），项目已推进到 export_ready 阶段。"
  }
}
```

**费用确认错误（402）**
```json
{
  "detail": {
    "code": "cost_confirmation_required",
    "message": "导出 720p 视频为高成本操作，请先确认费用明细。",
    "decision_id": "01HDECISION_ID"
  }
}
```

---

### GET /api/v1/projects/{project_id}/exports/latest

返回最新一次导出记录。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "export_version_id": "01HEXPORT_ID",
    "timeline_version_id": "01HTL_ID",
    "asset_id": "01HASSET_ID",
    "storage_uri": "https://minio.example.com/.../export_720p.mp4",
    "resolution": "720p",
    "status": "ready",
    "created_at": "2026-04-03T17:30:00Z"
  }
}
```

---

## 19. 决策管理（Decisions）

决策用于实现「人工确认门控（Human-in-the-loop）」，在风格选择、brief/narrative/visual_bible/shot_plan/storyboard 确认等关键节点暂停 Pipeline 等待用户操作。

### GET /api/v1/projects/{project_id}/decisions

查询项目下所有 `open` 状态的待确认决策。

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "01HDECISION_ID",
        "project_id": "01HPROJECT_ID",
        "session_id": "01HSESSION_ID",
        "decision_type": "select_style_direction",
        "target_entity_type": "project",
        "target_entity_id": null,
        "options_payload": [
          { "id": "style_cinematic", "title": "电影感", "summary": "高对比、暖色调、慢推拉" },
          { "id": "style_indie",     "title": "独立风", "summary": "自然光、颗粒感、跟拍运动" },
          { "id": "style_neon",      "title": "霓虹感", "summary": "强饱和、夜景、冷蓝/紫色调" }
        ],
        "default_option_id": null,
        "selected_option_id": null,
        "status": "open",
        "expires_at": null,
        "created_at": "2026-04-03T13:05:00Z"
      }
    ],
    "total": 1
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| decision_type | string | 决策类型（见下表） |
| options_payload | array | 可选项列表，每项含 id、title、summary（可选） |
| selected_option_id | string/null | 用户选择的选项 ID（open 时为 null） |
| status | string | `open`（等待）/ `selected`（已选）/ `expired`（已过期）/ `cancelled`（已取消） |

**decision_type 枚举**

| 值 | 触发时机 | 说明 |
|----|---------|------|
| select_style_direction | audio_analyzed 阶段 | 用户选择视觉风格方向 |
| confirm_brief | brief_ready 阶段 | 用户确认或重新生成创意方案 |
| confirm_narrative | narrative_ready 阶段 | 用户确认或重新生成叙事剧本 |
| confirm_visual_bible | visual_bible_ready 阶段 | 用户确认视觉圣经 |
| confirm_shot_plan | shot_plan_ready 阶段 | 用户确认或重新生成镜头计划 |
| confirm_storyboard | storyboard_ready 阶段 | 用户确认分镜图（高成本操作前）|

---

### GET /api/v1/projects/{project_id}/decisions/{decision_id}

查询单个决策详情（任意状态均可查询，含用户选择结果）。

---

### POST /api/v1/projects/{project_id}/decisions/{decision_id}/select

提交用户选择，将决策状态从 `open` 更新为 `selected`。

**请求体**
```json
{
  "selected_option_id": "style_neon"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| selected_option_id | string | ✓ | 选择的选项 ID，须在 options_payload 中 |

**响应示例（200）** —— 返回更新后的决策对象，`status: "selected"`。

**错误码**

| code | 说明 |
|------|------|
| not_found | 决策不存在或不属于该项目 |
| invalid_status | 决策不处于 open 状态 |
| invalid_option | 选项 ID 不在 options_payload 中 |

> **提交后续步骤**：提交决策后，应调用对应的工作流触发 API（如 `POST /workflow/generate-brief`）继续推进 Pipeline。

---

## 20. 对话会话（Conversation Sessions）

### GET /api/v1/projects/{project_id}/sessions

列出项目的所有对话会话（按最近活跃时间倒序）。

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| limit | int | 20 | 最多返回条数（1–100） |

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "01HSESSION_ID",
        "project_id": "01HPROJECT_ID",
        "status": "active",
        "created_at": "2026-04-03T12:00:00Z",
        "updated_at": "2026-04-03T16:00:00Z"
      }
    ],
    "count": 1
  }
}
```

---

### POST /api/v1/projects/{project_id}/sessions

显式新建一个对话会话。通常不需要手动调用（`POST /v1/chat/completions` 会自动创建）。

**响应示例（201）** —— 返回新建的会话对象。

---

### GET /api/v1/projects/{project_id}/sessions/{session_id}/messages

查询指定会话的消息历史（按时间升序）。

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| limit | int | 50 | 最多返回条数（1–200） |

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "01HMSG_ID",
        "session_id": "01HSESSION_ID",
        "role": "user",
        "content": "我想做赛博朋克风格",
        "created_at": "2026-04-03T12:00:00Z"
      },
      {
        "id": "01HMSG_ID2",
        "session_id": "01HSESSION_ID",
        "role": "assistant",
        "content": "好的！请先选择一个视觉风格方向...",
        "created_at": "2026-04-03T12:00:05Z"
      }
    ],
    "count": 2,
    "session_id": "01HSESSION_ID"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| role | string | `user` / `assistant` |
| content | string | 消息文本内容 |

---

## 21. 项目事件流（SSE）

### GET /api/v1/projects/{project_id}/events/stream

订阅项目实时事件流（Server-Sent Events）。前端通过 `EventSource` 接收 Pipeline 阶段变化通知。

**请求示例（JavaScript）**
```javascript
const es = new EventSource(
  `http://localhost:8000/api/v1/projects/${projectId}/events/stream`,
  { headers: { Authorization: `Bearer ${token}` } }
);

es.onmessage = (e) => {
  const event = JSON.parse(e.data);
  console.log(event.event_type, event);
};
```

**SSE 事件格式（RFC 8895）**
```
data: {"event_type": "sse_connected", "project_id": "01HPROJECT_ID"}

data: {"event_type": "project_stage_advanced", "_project_id": "01HPROJECT_ID", "from_stage": "input_ready", "to_stage": "audio_analyzed", "timestamp": "2026-04-03T13:00:00Z"}

: heartbeat
```

| 字段 | 类型 | 说明 |
|------|------|------|
| event_type | string | 事件类型（见下表） |
| _project_id | string | 项目 ID（用于前端过滤） |

**常见 event_type**

| event_type | 说明 |
|------------|------|
| sse_connected | SSE 连接建立 |
| project_stage_advanced | 项目阶段推进（通用，见下方具体事件） |
| project_audio_analyzed | 音频分析完成，项目进入 audio_analyzed |
| project_brief_ready | brief + style 生成完成 |
| project_narrative_ready | 叙事剧本完成 |
| project_shot_plan_ready | 镜头计划完成 |
| project_storyboard_ready | 分镜图全部生成完成 |
| **clip.shot.completed** | **单个 clip 生成完成**，含该 clip 的 storage_uri，前端可立即将其填入时间轴 |
| project_clips_ready | **所有** clip 生成完成，前端解锁「合成完整视频」按钮 |
| project_timeline_ready | 时间线合成完成，preview_uri 可用 |
| audio.analysis.progress | 音频分析进度（progress 0-100） |
| narrative.generating | 叙事剧本生成中 |
| narrative.completed | 叙事剧本生成完成 |
| tool_job_failed | 后台任务失败 |
| director_report | Director Mode B 自动汇报触发 |

**`clip.shot.completed` 事件 payload 详细说明**
```json
{
  "event_type": "clip.shot.completed",
  "_project_id": "01HPROJECT_ID",
  "shot_id": "01HSHOT_ID",
  "shot_index": 3,
  "start_ms": 12000,
  "end_ms": 15750,
  "duration_ms": 3750,
  "storage_uri": "https://minio.example.com/.../clip_03.mp4",
  "clip_version_id": "01HCLIP_ID"
}
```

> 前端收到此事件后，可直接用 `storage_uri` 将 clip 填入时间轴对应位置，无需调用其他 API。
> `shot_index` 决定在时间轴上的位置，`start_ms/end_ms` 决定音频时钟的切换点。

> **心跳**：每 30 秒发送一次 `: heartbeat` 注释行（不触发 `onmessage`），防止连接超时。

---

## 22. 版本管理（Versions）

### GET /api/v1/projects/{project_id}/versions/{entity_type}

查询指定产物的历史版本列表（按版本号倒序）。

**entity_type 取值**：`brief` / `style` / `storyboard` / `timeline`

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| limit | int | 20 | 每页条数（1–100） |
| offset | int | 0 | 偏移量 |

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "entity_type": "brief",
    "project_id": "01HPROJECT_ID",
    "versions": [
      {
        "id": "01HBRIEF_V2",
        "project_id": "01HPROJECT_ID",
        "version_no": 2,
        "is_active": true,
        "title": "霓虹都市追逐曲（修订版）",
        "summary": "加强了高潮段的视觉冲击力...",
        "created_at": "2026-04-03T16:00:00Z"
      },
      {
        "id": "01HBRIEF_V1",
        "version_no": 1,
        "is_active": false,
        "title": "霓虹都市追逐曲",
        "summary": "以赛博朋克城市夜景为主线...",
        "created_at": "2026-04-03T13:00:00Z"
      }
    ],
    "total": 2,
    "limit": 20,
    "offset": 0,
    "has_more": false
  }
}
```

---

### POST /api/v1/projects/{project_id}/versions/{entity_type}/{version_id}/activate

激活指定历史版本，触发对应的 stale 传播和项目阶段回退。

**版本回退影响**

| entity_type | 激活后项目阶段 | 失效的下游产物 |
|-------------|--------------|--------------|
| brief | audio_analyzed | shot_plan / storyboard / clips / timeline |
| style | shot_plan_ready | storyboard / clips / timeline |
| storyboard | storyboard_ready | clips / timeline |
| timeline | 不变 | 无（仅切换指针） |

**响应示例（200）**
```json
{
  "success": true,
  "data": {
    "entity_type": "brief",
    "version_id": "01HBRIEF_V1",
    "activated": true,
    "message": "版本已激活，项目已回退到 audio_analyzed 阶段，下游产物已标记为 stale。"
  }
}
```

---

## 23. 一致性质检（Consistency）

### POST /api/v1/projects/{project_id}/consistency/check

对项目执行角色/风格/节奏一致性检查（LLM 驱动）。

> 前置：项目须处于 `storyboard_ready` 或更高阶段（clips_ready / timeline_ready / export_ready）。

**无请求体**

**响应示例（200）**
```json
{
  "project_id": "01HPROJECT_ID",
  "issues": [
    {
      "type": "character_inconsistency",
      "target_id": "01HSHOT_05",
      "severity": "warning",
      "description": "第 5 个镜头的角色服装描述与风格规范不一致"
    }
  ],
  "recommendations": [
    {
      "action": "patch_shot",
      "target_id": "01HSHOT_05",
      "reason": "建议修改 style_binding 以匹配霓虹风格"
    }
  ],
  "overall_consistency_score": 0.85,
  "shot_count": 12
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| issues | array | 发现的一致性问题列表 |
| issues[].type | string | 问题类型（character_inconsistency / style_mismatch / pacing_issue 等） |
| issues[].target_id | string | 问题所在的 shot_id 或其他实体 ID |
| issues[].severity | string | 严重程度：`error`（严重）/ `warning`（警告）/ `info`（提示） |
| issues[].description | string | 问题描述 |
| recommendations | array | 修复建议列表 |
| overall_consistency_score | float | 整体一致性评分（0.0–1.0，越高越好） |
| shot_count | int | 检查的镜头总数 |

> **注意**：此接口直接返回对象（非 `success/data` 包装格式）。LLM 不可用时返回空 issues 和 score=1.0，不报错。

---

## 附录：Pipeline 完整调用流程示例

```
1. POST /api/v1/auth/login                          → 获取 token
2. POST /api/v1/projects                             → 创建项目
3. POST /api/v1/projects/{id}/assets/upload-init    → 获取上传 URL
   PUT  <upload_url>                                 → 直传文件到 MinIO
   POST /api/v1/projects/{id}/assets/complete       → 确认上传
4. POST /api/v1/projects/{id}/spec/versions         → 创建输入规格
   POST /api/v1/projects/{id}/spec/activate         → 激活（自动推进到 input_ready）
5. POST /v1/chat/completions                        → 发消息触发分析（或手动调用 analyze-audio）
6. GET  /api/v1/projects/{id}/decisions             → 轮询等待风格选项决策
   POST /api/v1/projects/{id}/decisions/{id}/select → 选择风格
   POST /api/v1/projects/{id}/workflow/generate-brief → 触发 brief 生成
7. GET  /api/v1/projects/{id}/decisions             → 等待 brief 确认决策
   POST /api/v1/projects/{id}/decisions/{id}/select → 确认 brief
   POST /api/v1/projects/{id}/workflow/generate-shot-plan → 触发 shot plan
8. GET  /api/v1/projects/{id}/decisions             → 等待 shot plan 确认
   POST /api/v1/projects/{id}/decisions/{id}/select → 确认
   POST /api/v1/projects/{id}/workflow/generate-storyboard → 触发分镜（异步）
9. GET  /api/v1/projects/{id}/events/stream         → SSE 监听完成通知
10. GET  /api/v1/projects/{id}/decisions            → 等待 storyboard 确认
    POST /api/v1/projects/{id}/decisions/{id}/select → 确认
    POST /api/v1/projects/{id}/workflow/generate-clips → 触发 clip 生成（异步）
10b. 【每个 clip 生成时】SSE: clip.shot.completed
     → 前端实时将该 clip 填入时间轴对应位置（无需额外 API）
11. 【所有 clip 完成】SSE: project_clips_ready
     → 前端解锁「合成完整视频」按鈕
     POST /api/v1/projects/{id}/timeline/compose  → 异步合成（用户点按按鈕）
     SSE: project_timeline_ready  → GET /timeline/active 拿 preview_uri
12. POST /api/v1/projects/{id}/exports              → 导出视频
    GET  /api/v1/projects/{id}/exports/latest       → 获取下载链接
```
