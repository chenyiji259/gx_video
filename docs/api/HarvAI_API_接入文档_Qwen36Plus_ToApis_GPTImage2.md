# HarvAI AI 模型 API 接入文档

> 本文档汇总当前项目计划接入的 AI 模型 API，包括 Qwen 3.6 Plus 文本/多模态模型、ToApis GPT Image 2 异步生图 API、ToApis 图片上传中转能力，以及 Seedance 2.0 视频生成 API 的衔接约束。
> 本文档用于避免后续实现继续引用旧的 Qwen 3.5 Plus 或 ToApis Gemini 生图模型名。

---

## 目录

1. [Qwen 3.6 Plus 接入文档](#一-qwen-36-plus-接入文档)
   - [1.1 基础信息](#11-基础信息)
   - [1.2 认证方式](#12-认证方式)
   - [1.3 Chat 接口调用](#13-chat-接口调用)
   - [1.4 工具调用](#14-工具调用)
   - [1.5 多模态图片理解](#15-多模态图片理解)

2. [ToApis GPT Image 2 异步生图 API](#二-toapis-gpt-image-2-异步生图-api)
   - [2.1 基础信息](#21-基础信息)
   - [2.2 认证方式](#22-认证方式)
   - [2.3 提交生图任务](#23-提交生图任务)
   - [2.4 轮询查询任务状态](#24-轮询查询任务状态)
   - [2.5 图片上传中转公网 URL](#25-图片上传中转公网-url)
   - [2.6 参数与状态说明](#26-参数与状态说明)

3. [本项目接入约束](#三-本项目接入约束)

---

## 一、 Qwen 3.6 Plus 接入文档

### 1.1 基础信息

| 项目 | 内容 |
|------|------|
| 模型名称 | `qwen3.6-plus` |
| API 地址 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| API 版本 | OpenAI 兼容模式 v1 |
| 协议 | OpenAI 兼容 REST API |
| 用途 | 文本生成、导演模型、多模态图片理解 |
| 多模态 | 支持文本 + 图片 URL |
| thinking 模式 | 默认关闭，可通过参数开启 |

### 1.2 认证方式

使用 Bearer Token 认证。

```http
Authorization: Bearer <api-key>
Content-Type: application/json
```

### 1.3 Chat 接口调用

**接口地址**：`POST https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`

**请求体格式**：

```json
{
  "model": "qwen3.6-plus",
  "messages": [
    {
      "role": "user",
      "content": "你好，请用一句话介绍你自己"
    }
  ],
  "max_tokens": 4096,
  "temperature": 0.7,
  "enable_thinking": false
}
```

**关键参数说明**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | 是 | 模型名称，本项目默认 `qwen3.6-plus` |
| `messages` | array | 是 | OpenAI 兼容消息数组 |
| `max_tokens` | integer | 否 | 最大输出 token 数 |
| `temperature` | number | 否 | 采样温度 |
| `enable_thinking` | boolean | 否 | 是否启用 thinking 模式 |

导演模型不单独引入新供应商，复用 Qwen 3.6 Plus 调用通道，通过 `purpose`、Prompt Template 和业务上下文区分用途。

### 1.4 工具调用

Qwen 3.6 Plus 可按 OpenAI 兼容格式传入 Tools。阶段 7 只要求文本/导演模型调用能力可追踪；完整 Tool Registry 在后续阶段单独实现。

请求形态示例：

```json
{
  "model": "qwen3.6-plus",
  "messages": [
    {
      "role": "user",
      "content": "北京今天天气怎么样？"
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "获取指定城市的天气信息",
        "parameters": {
          "type": "object",
          "properties": {
            "city": {
              "type": "string",
              "description": "城市名称"
            }
          },
          "required": ["city"]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

### 1.5 多模态图片理解

Qwen 3.6 Plus 多模态请求中，图片必须以公网可访问 URL 传入。

```json
{
  "model": "qwen3.6-plus",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "请描述这张图片中人物的外貌特征"
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "https://example.com/image.png"
          }
        }
      ]
    }
  ],
  "max_tokens": 4096
}
```

本地文件路径、`localhost`、`127.0.0.1`、内网地址不得直接传给外部模型。需要先通过本项目资产服务或 ToApis 上传接口换取公网 URL。

---

## 二、 ToApis GPT Image 2 异步生图 API

### 2.1 基础信息

| 项目 | 内容 |
|------|------|
| 服务提供商 | ToApis |
| 模型名称 | `gpt-image-2` |
| 提交接口 | `POST https://toapis.com/v1/images/generations` |
| 查询接口 | `GET https://toapis.com/v1/images/generations/{task_id}` |
| 上传接口 | `POST https://toapis.com/v1/uploads/images` |
| 返回方式 | 异步，提交后返回任务 ID，再轮询获取结果 |
| 参考图 | `reference_images`，仅支持公网 URL |
| 向后兼容字段 | `image_urls`，ToApis 会归一化为 `reference_images` |

官方文档：

- `https://docs.toapis.com/docs/cn/api-reference/images/gpt-image-2/generation`
- `https://docs.toapis.com/docs/cn/api-reference/uploads/images`
- `https://docs.toapis.com/docs/cn/api-reference/tasks/image-status`

### 2.2 认证方式

使用 Bearer Token 认证。

```http
Authorization: Bearer <api-key>
Content-Type: application/json
```

### 2.3 提交生图任务

**接口地址**：`POST https://toapis.com/v1/images/generations`

**请求体字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | 是 | 固定使用 `gpt-image-2` |
| `prompt` | string | 是 | 生图提示词，最长 4000 字符 |
| `size` | string | 否 | 输出比例，取值依赖 `resolution` |
| `resolution` | string | 否 | `1K`、`2K`、`4K` |
| `n` | integer | 否 | 生成数量，默认 1 |
| `response_format` | string | 否 | 推荐 `url` |
| `reference_images` | array[string] | 否 | 参考图公网 URL 列表 |
| `image_urls` | array[string] | 否 | 向后兼容字段，会归一化为 `reference_images` |

**文生图请求示例**：

```json
{
  "model": "gpt-image-2",
  "prompt": "生成一张未来城市夜景海报，霓虹灯，电影感构图",
  "n": 1,
  "size": "1:1",
  "resolution": "1K",
  "response_format": "url"
}
```

**图生图请求示例**：

```json
{
  "model": "gpt-image-2",
  "prompt": "保持人物身份一致，生成电影感半身肖像",
  "n": 1,
  "size": "3:2",
  "resolution": "2K",
  "response_format": "url",
  "reference_images": [
    "https://files.toapis.com/uploads/123/reference.jpg"
  ]
}
```

**提交成功响应**：

```json
{
  "id": "task_img_abc123def456",
  "object": "generation.task",
  "model": "gpt-image-2",
  "status": "queued",
  "progress": 0,
  "created_at": 1703884800,
  "metadata": {}
}
```

### 2.4 轮询查询任务状态

**接口地址**：`GET https://toapis.com/v1/images/generations/{task_id}`

**查询成功响应（处理中）**：

```json
{
  "id": "task_img_abc123def456",
  "object": "generation.task",
  "model": "gpt-image-2",
  "status": "in_progress",
  "progress": 50,
  "created_at": 1703884800
}
```

**查询成功响应（已完成）**：

```json
{
  "id": "task_img_abc123def456",
  "object": "generation.task",
  "model": "gpt-image-2",
  "status": "completed",
  "progress": 100,
  "created_at": 1703884800,
  "completed_at": 1703884820,
  "expires_at": 1703971220,
  "result": {
    "type": "image",
    "data": [
      {
        "url": "https://result.example.com/image_abc123.png"
      }
    ]
  }
}
```

**查询成功响应（失败）**：

```json
{
  "id": "task_img_abc123def456",
  "object": "generation.task",
  "model": "gpt-image-2",
  "status": "failed",
  "error": {
    "code": "content_policy_violation",
    "message": "Prompt contains prohibited content"
  }
}
```

轮询建议：

- 初始等待约 2 秒。
- 后续每 3 到 5 秒查询一次。
- 最大等待时间按业务配置控制。
- `completed` 后读取 `result.data[].url`。
- 生成图片 URL 有有效期，应尽快下载或转存到本项目可控存储。

### 2.5 图片上传中转公网 URL

GPT Image 2 不再支持在 `reference_images` 或 `image_urls` 中直接传入 base64 图片数据。参考图必须是公开可访问的 `http://` 或 `https://` URL。

本地图片或本机 HTTP 图片需要先上传到 ToApis：

**接口地址**：`POST https://toapis.com/v1/uploads/images`

**请求示例**：

```bash
curl --request POST \
  --url https://toapis.com/v1/uploads/images \
  --header 'Authorization: Bearer <token>' \
  --form 'file=@/path/to/reference.jpg'
```

**成功响应**：

```json
{
  "success": true,
  "message": "",
  "data": {
    "id": "upload_abc12345",
    "url": "https://files.toapis.com/uploads/123/1737568800_abc12345.jpg",
    "mime_type": "image/jpeg",
    "size": 89234
  }
}
```

推荐桥接流程：

```text
本地图片 / localhost 图片 URL
-> 服务端读取图片二进制
-> POST /v1/uploads/images
-> 获取 data.url
-> 写入 GPT Image 2 reference_images
-> POST /v1/images/generations
-> GET /v1/images/generations/{task_id}
```

来自 `C:\Users\CYJ25\Desktop\xhs-project\xhs-project` 的实现参考：

- `server/services/toapis-upload-service.ts`：检测 `localhost`、`127.0.0.1`、`0.0.0.0` 图片 URL，下载后以 multipart/form-data 上传到 ToApis，并缓存 `sourceUrl -> publicUrl`。
- `server/services/image-generation-service.ts`：把本地或相对路径参考图转为可访问 URL，再经 ToApis 上传桥接为公网 URL，最后放入 `reference_images`。
- `scripts/toapis_gptimage_reference_test.py`：最小端到端验证脚本，覆盖本地文件上传、GPT Image 2 提交任务、轮询任务和提取结果 URL。

### 2.6 参数与状态说明

`resolution` 与 `size` 的关系：

| resolution | 支持 size |
| --- | --- |
| `1K` | `1:1`、`3:2`、`2:3` |
| `2K` | `1:1`、`3:2`、`2:3`、`4:3`、`3:4`、`5:4`、`4:5`、`16:9`、`9:16`、`2:1`、`1:2`、`21:9`、`9:21` |
| `4K` | `16:9`、`9:16`、`2:1`、`1:2`、`21:9`、`9:21` |

状态说明：

| 状态值 | 含义 | 是否终态 | 建议处理 |
|--------|------|----------|----------|
| `queued` | 排队等待处理 | 否 | 等待后继续查询 |
| `in_progress` | 正在处理 | 否 | 等待后继续查询 |
| `completed` | 成功完成 | 是 | 读取 `result.data[].url` |
| `failed` | 处理失败 | 是 | 检查 `error.code` 和 `error.message` |

常见错误：

| 错误码 | 说明 |
|--------|------|
| `invalid_request` | 请求参数无效 |
| `unauthorized` | 认证失败 |
| `insufficient_quota` | 余额不足 |
| `task_not_found` | 任务不存在 |
| `content_policy_violation` | 内容违规 |
| `rate_limit_exceeded` | 请求频率超限 |
| `internal_error` | 服务内部错误 |

---

## 三、本项目接入约束

### 3.1 配置参考

```text
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen3.6-plus
QWEN_DIRECTOR_MODEL=qwen3.6-plus
QWEN_API_KEY=<secret>

TOAPIS_BASE_URL=https://toapis.com/v1/images/generations
TOAPIS_UPLOAD_URL=https://toapis.com/v1/uploads/images
TOAPIS_API_KEY=<secret>
TOAPIS_IMAGE_MODEL=gpt-image-2
TOAPIS_POLL_INTERVAL_MS=5000
TOAPIS_MAX_POLL_ATTEMPTS=60
```

### 3.2 生图参数不写死

GPT Image 2 的 `size`、`resolution`、`n`、`response_format`、`reference_images` 不应在后端固定为单一业务常量。

后端职责：

- 从前端或上游业务请求接收参数。
- 按官方允许值做白名单校验。
- 对 `prompt` 做 4000 字符长度校验。
- 把最终参数写入任务记录、tool call 或 model/tool invocation 追踪。
- 对参考图 URL 做公网可访问性、数量和协议校验。

前端或业务编排职责：

- 提供用户可选的尺寸、分辨率、数量和参考图选择。
- 根据业务阶段决定默认推荐值，但默认值不应散落在后端 provider 代码里。

### 3.3 公网 URL 统一边界

所有外部模型都不得直接接收本地路径。

统一处理规则：

- 已是公网 `http://` 或 `https://` URL：可直接使用。
- `localhost`、`127.0.0.1`、`0.0.0.0` 或本地相对路径：必须先通过服务端读取并上传到 ToApis 或项目对象存储，得到公网 URL。
- 上传返回的公网 URL 可以用于 GPT Image 2 的 `reference_images`。
- 同一公网 URL 边界后续也应服务 Seedance 2.0 的 `image_url.url`、`video_url.url` 和 `audio_url.url`。
- 上传桥接应做缓存，避免同一源图片在同一任务内重复上传。

### 3.4 错误处理建议

1. 网络错误：指数退避重试。
2. 限流错误 429：等待后重试。
3. 服务端错误 500/502/503：可按配置重试。
4. 认证错误 401/403：不重试，提示检查 API Key。
5. 参数错误 400/422：不重试，返回可读的参数修正建议。
6. 内容安全错误：不重试，保留供应商错误码和消息。

---

*文档版本: v2.0*
*最后更新: 2026-04-27*
*来源: ToApis 官方文档、Seedance 2.0 接入文档、`xhs-project` ToApis 上传中转实现*
