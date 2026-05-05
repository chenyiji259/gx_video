# Seedance 2.0 视频生成 API 接入文档

> 来源：火山引擎方舟官方文档《Seedance 2.0 SDK 示例官方教程》与其指向的 Video Generation API。当前整理时间：2026-04-24。

## 1. 接入结论

Seedance 2.0 系列通过火山方舟 Video Generation API 接入，核心调用方式是：

1. 使用 API Key 初始化方舟 SDK 或直接请求方舟 API。
2. 调用“创建视频生成任务”接口，提交模型、提示词、参考素材和输出规格。
3. 记录返回的 task id。
4. 轮询“查询视频生成任务”接口，直到任务状态为成功或失败。
5. 成功后读取返回的视频 URL，并建议尽快转存到自己的 TOS，因为原始产物 URL 有有效期限制。

## 2. 前置条件

- 火山引擎账号已注册并登录。
- 已在 API Key 管理页面创建并保存 API Key。
- 本地或服务端配置环境变量：`ARK_API_KEY`。
- 账户余额大于等于 200 元，或已购买资源包，否则无法开通 Seedance 2.0 系列模型。
- 输入图片、视频、音频 URL 必须是公网可访问链接，官方建议存放在 TOS 对象存储并配置公共读。
- 如需使用真人肖像素材，不能直接上传未经认证的真人人脸参考图/视频，应走平台支持的合规方案：预置虚拟人像、已授权真人素材、或同账号可信模型产物。

## 3. 模型选择

| 模型 | Model ID | 适用场景 |
| --- | --- | --- |
| Doubao Seedance 2.0 | `doubao-seedance-2-0-260128` | 追求最高生成品质 |
| Doubao Seedance 2.0 fast | `doubao-seedance-2-0-fast-260128` | 更关注成本和生成速度，不要求极限品质 |

两个模型的能力相同，主要区别在质量、速度和成本取舍。

## 4. API 基础信息

官方 SDK 示例中使用的方舟 API Base URL：

```text
https://ark.cn-beijing.volces.com/api/v3
```

典型 SDK 方法：

- 创建任务：`CreateContentGenerationTask`
- 查询任务：`GetContentGenerationTask`

如果项目中不使用 SDK，也应按同一异步任务模型封装：创建任务 -> 保存 task id -> 定时查询 -> 成功后读取视频 URL。

## 5. 创建任务核心参数

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `model` | string | 模型 ID，例如 `doubao-seedance-2-0-260128` |
| `content` | array | 输入内容数组，包含文本、图片、视频、音频等多模态素材 |
| `ratio` | string | 输出宽高比，例如 `16:9`、`9:16`、`1:1`、`adaptive` |
| `duration` | integer | 输出视频时长，Seedance 2.0 系列常用范围为 4~15 秒 |
| `resolution` | string | 输出分辨率，支持 `480p`、`720p`、`1080p`；fast 版本支持到 `720p` |
| `generate_audio` | boolean | 是否生成有声视频 |
| `watermark` | boolean | 是否显示水印 |
| `return_last_frame` | boolean | 是否返回视频产物对应的尾帧图 |
| `tools` | array | 工具配置；联网搜索时传 `type=web_search` |
| `service_tier` | string | 离线推理时可配置 `flex` |

## 6. content 输入结构

`content` 是数组。提示词和素材都放在该数组中，模型根据数组顺序和提示词中的“素材类型+序号”建立引用关系。

### 6.1 文本输入

```json
{
  "type": "text",
  "text": "微距镜头对准叶片上翠绿的玻璃蛙。焦点逐渐从它光滑的皮肤，转移到透明腹部。"
}
```

### 6.2 图片输入

```json
{
  "type": "image_url",
  "image_url": {
    "url": "https://example.com/reference.png"
  },
  "role": "reference_image"
}
```

图片可传 0~9 张。Seedance 2.0 当前接口要求图片素材显式声明 `role`。普通参考图使用 `reference_image`；强首帧/尾帧约束使用 `first_frame` / `last_frame`。

### 6.3 视频输入

```json
{
  "type": "video_url",
  "video_url": {
    "url": "https://example.com/reference.mp4"
  },
  "role": "reference_video"
}
```

视频可传 0~3 个，可用于视频参考、视频编辑、视频延长和多段串联。

### 6.4 音频输入

```json
{
  "type": "audio_url",
  "audio_url": {
    "url": "https://example.com/reference.mp3"
  },
  "role": "reference_audio"
}
```

音频可传 0~3 个，但官方明确不支持“文本+音频”和“纯音频”输入组合。

### 6.5 首帧/尾帧图生视频

当需要严格指定首帧或尾帧时，应使用图片输入并配置角色：

```json
{
  "type": "image_url",
  "image_url": {
    "url": "https://example.com/first-frame.png"
  },
  "role": "first_frame"
}
```

尾帧使用：

```json
{
  "type": "image_url",
  "image_url": {
    "url": "https://example.com/last-frame.png"
  },
  "role": "last_frame"
}
```

## 7. 提示词引用规则

提示词中必须使用“素材类型+序号”引用素材，例如：

- `图片1中美妆博主面带笑容，向镜头介绍图片2中的面霜。`
- `全程使用视频1的第一视角构图，全程使用音频1作为背景音乐。`
- `视频1中的拱形窗户打开，进入美术馆室内，接视频2，之后镜头进入画内，接视频3。`

序号按 `content` 数组中同类素材的出现顺序从 1 开始计算。

重要限制：

- `asset://<asset ID>` 只能用于向模型传入素材。
- 提示词里不要写 asset id。
- 正确：`图片1中美妆博主`。
- 错误：`asset-2026**** 是美妆博主`。

## 8. 典型能力接入方式

### 8.1 文生视频

只传 `text`，可设置 `ratio`、`duration`、`resolution`、`generate_audio`。

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    {
      "type": "text",
      "text": "固定机位，近景镜头，清新自然风格。室内自然光下，一位博主介绍一款面霜。"
    }
  ],
  "ratio": "16:9",
  "duration": 8,
  "resolution": "720p",
  "generate_audio": true,
  "watermark": true
}
```

### 8.2 多模态参考生视频

可组合文本、图片、视频、音频，用参考图片继承角色形象、视觉风格和构图，用参考视频继承主体、运镜、动作和风格，用参考音频继承音色、音乐旋律或对话内容。

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    {
      "type": "text",
      "text": "全程使用视频1的第一视角构图，全程使用音频1作为背景音乐。首帧为图片1，尾帧定格为图片2。"
    },
    { "type": "image_url", "image_url": { "url": "https://example.com/first.png" }, "role": "reference_image" },
    { "type": "image_url", "image_url": { "url": "https://example.com/last.png" }, "role": "reference_image" },
    { "type": "video_url", "video_url": { "url": "https://example.com/ref.mp4" }, "role": "reference_video" },
    { "type": "audio_url", "audio_url": { "url": "https://example.com/bgm.mp3" }, "role": "reference_audio" }
  ],
  "ratio": "9:16",
  "duration": 8,
  "generate_audio": true
}
```

### 8.3 视频编辑

传入待编辑视频，也可以附加参考图片或音频，并在提示词中描述编辑动作。

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    {
      "type": "text",
      "text": "将视频1礼盒中的香水替换成图片1中的面霜，保持原视频运镜不变。"
    },
    { "type": "video_url", "video_url": { "url": "https://example.com/origin.mp4" }, "role": "reference_video" },
    { "type": "image_url", "image_url": { "url": "https://example.com/product.png" }, "role": "reference_image" }
  ],
  "ratio": "16:9",
  "duration": 8,
  "generate_audio": true
}
```

### 8.4 视频延长 / 多视频串联

传入 1 段视频可向前或向后延长；传入 2~3 段视频时，模型会补全中间过渡部分，生成视频通常包含原视频和新增生成内容。

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    {
      "type": "text",
      "text": "视频1中的拱形窗户打开，进入美术馆室内，接视频2，之后镜头进入画内，接视频3。"
    },
    { "type": "video_url", "video_url": { "url": "https://example.com/video1.mp4" }, "role": "reference_video" },
    { "type": "video_url", "video_url": { "url": "https://example.com/video2.mp4" }, "role": "reference_video" },
    { "type": "video_url", "video_url": { "url": "https://example.com/video3.mp4" }, "role": "reference_video" }
  ],
  "ratio": "16:9",
  "duration": 8,
  "generate_audio": true
}
```

### 8.5 联网搜索

联网搜索只适用于纯文本输入。配置 `tools.type=web_search` 后，模型会根据提示词自主判断是否搜索互联网内容。是否实际搜索可从查询任务返回的 `usage.tool_usage.web_search` 判断，为 0 表示没有搜索。

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    {
      "type": "text",
      "text": "微距镜头对准叶片上翠绿的玻璃蛙，重点表现玻璃蛙的真实外观特征。"
    }
  ],
  "tools": [
    { "type": "web_search" }
  ],
  "ratio": "adaptive",
  "duration": 11,
  "generate_audio": true
}
```

## 9. 虚拟人像与真人素材

Seedance 2.0 系列不支持直接上传含有真人人脸的参考图或视频。官方提供以下合规路径：

### 9.1 使用预置虚拟人像

适合需要真人风格人脸但不指定真实人物的场景。每个素材有独立 asset id，在对应模态 URL 字段传入：

```json
{
  "type": "image_url",
  "image_url": {
    "url": "asset://<asset ID>"
  },
  "role": "reference_image"
}
```

### 9.2 使用已授权真人素材

通过真人认证和本人授权后，将真人图片、视频、音频上传至方舟。素材入库成功后，同样使用：

```text
asset://<asset ID>
```

### 9.3 信任模型产物作为输入素材

同账号下部分模型生成的含人脸原始产物，可作为 Seedance 2.0 系列的输入素材二次创作，不会触发输入审核拦截。官方文档列出的信任范围包括 Seedance 2.0 / Seedance 2.0 fast 生成的视频、对应尾帧图片，以及 Seedream 5.0 lite 文生图得到的含人脸图片等，并有生效时间和有效期要求。

## 10. 查询任务与状态处理

创建任务成功后，接口返回任务 ID。服务端应持久化该 ID，并轮询查询任务接口。

| 状态 | 处理方式 |
| --- | --- |
| `running` 或处理中 | 等待后继续查询，官方示例中 10~30 秒轮询一次 |
| `succeeded` | 读取 `content.video_url`，记录产物 URL、usage 和时间戳 |
| `failed` | 读取 `error.code` 和 `error.message`，记录失败原因并返回业务错误 |

成功返回中重点字段：

- `id`：任务 ID。
- `model`：实际使用的模型。
- `status`：任务状态。
- `content.video_url`：生成视频 URL。
- `usage.completion_tokens`：用量信息。
- `usage.tool_usage.web_search`：联网搜索使用次数。
- `created_at` / `updated_at`：任务时间。
- `error.code` / `error.message`：失败时的错误信息。

## 11. Python SDK 接入示例

> 字段名以官方 SDK 实际版本为准；下面示例表达核心调用结构。

```python
import os
import time
from volcenginesdkarkruntime import Ark

client = Ark(
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key=os.environ["ARK_API_KEY"],
)

create_resp = client.content_generation.tasks.create(
    model="doubao-seedance-2-0-260128",
    content=[
        {
            "type": "text",
            "text": "固定机位，近景镜头，清新自然风格。图片1中美妆博主介绍图片2中的面霜。",
        },
        {
            "type": "image_url",
            "image_url": {"url": "asset://<virtual-human-asset-id>"},
            "role": "reference_image",
        },
        {
            "type": "image_url",
            "image_url": {"url": "https://example.com/product.png"},
            "role": "reference_image",
        },
    ],
    ratio="16:9",
    duration=8,
    resolution="720p",
    generate_audio=True,
    watermark=True,
)

task_id = create_resp.id

while True:
    task = client.content_generation.tasks.retrieve(task_id)
    if task.status == "succeeded":
        print("video_url:", task.content.video_url)
        break
    if task.status == "failed":
        print("error:", task.error.code, task.error.message)
        break
    print("status:", task.status)
    time.sleep(10)
```

## 12. 服务端封装建议

建议在本项目中不要把前端请求直接透传给方舟，而是封装为服务端任务：

1. `POST /api/video-generation/tasks`
   - 接收业务提示词、素材列表、输出规格。
   - 校验素材 URL 可访问性、数量、模态组合和真人素材规则。
   - 调用方舟创建任务。
   - 保存本地任务记录：`task_id`、模型、参数摘要、状态、创建时间。

2. `GET /api/video-generation/tasks/{id}`
   - 查询本地任务状态。
   - 必要时触发或读取后端轮询结果。
   - 返回状态、视频 URL、错误信息和 usage。

3. 后台轮询任务
   - 10~30 秒间隔查询方舟任务状态。
   - 成功后把 `content.video_url` 转存到自己的 TOS 或项目素材库。
   - 失败后保存 `error.code`、`error.message` 和原始响应摘要。

4. 素材治理
   - 业务侧保存原始素材、方舟 asset id、生成产物 URL、本地转存 URL 的映射。
   - 对 24 小时有效期的原始视频 URL 不要长期依赖。

## 13. 接入校验清单

- [ ] `ARK_API_KEY` 不写入代码仓库，只通过环境变量或密钥管理注入。
- [ ] 服务端校验 `content` 中图片不超过 9 张、视频不超过 3 个、音频不超过 3 个。
- [ ] 图片、视频、音频素材项显式声明 `role`，普通参考素材分别使用 `reference_image`、`reference_video`、`reference_audio`。
- [ ] 禁止“纯音频”和“文本+音频”这类官方不支持组合。
- [ ] 首尾帧强一致需求使用 `role=first_frame` / `role=last_frame`，不要只靠提示词描述。
- [ ] 提示词引用素材使用“图片1 / 视频1 / 音频1”格式，不使用 asset id。
- [ ] 生成任务异步化，前端只轮询本项目任务状态，不长时间阻塞请求。
- [ ] 任务失败时保存并展示 `error.code` 和 `error.message`。
- [ ] 成功后尽快转存视频产物，避免官方原始 URL 过期。
- [ ] 真人肖像素材仅走预置虚拟人像、已授权真人素材或官方信任产物路径。
- [ ] 使用联网搜索时只允许纯文本输入，并记录 `usage.tool_usage.web_search`。

## 14. 官方来源

- 当前浏览器页面：`https://www.volcengine.com/docs/82379/2291680?lang=zh`
- 文档标题：`Seedance 2.0 SDK 示例官方教程`
- 关联能力：`Video Generation API`
