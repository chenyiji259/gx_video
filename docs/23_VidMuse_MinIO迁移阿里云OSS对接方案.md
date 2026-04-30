# VidMuse MinIO 迁移阿里云 OSS 私有桶实施指导

## 1. 文档目的

这份文档不是泛泛说明，而是给后续真实迁移用的实施指导。

目标是把当前 `VidMuse` 从 `MinIO` 切到 **阿里云 OSS 私有桶**，并保持现有系统使用方式不变：

- 数据库存储资产定位信息
- 前端渲染图片 / 视频 / 音频时，仍然拿后端返回的**签名临时 URL**
- 模型、工具、工作流引用资源时，也统一拿**签名临时 URL**
- 你后续只需要在 `.env` 中填写真实 OSS 账密和相关配置

本文档不包含：

- 历史数据迁移脚本
- 真实 AK/SK 入库
- 真实白名单配置

本文档只回答三件事：

1. 你的当前项目真实是怎么用 MinIO 的
2. 切到 OSS 私有桶到底要改哪些地方
3. 如何把这些改动收口成“以后只改 `.env`”的接入方式

---

## 2. 当前项目的真实存储模式

### 2.1 存储抽象已经存在

当前仓库已经有对象存储抽象：

- 抽象协议：[backend/app/storage/object_storage.py](C:/Users/CYJ25/Desktop/vidMuse/backend/app/storage/object_storage.py)
- 当前实现：[backend/app/storage/minio_adapter.py](C:/Users/CYJ25/Desktop/vidMuse/backend/app/storage/minio_adapter.py)

这说明迁移的正确方式不是到处嵌 `oss2`，而是：

1. 新增 `OSSAdapter`
2. 做统一存储工厂
3. 把所有上层代码继续收口到 `get_storage()`

### 2.2 当前数据库确实会存资产路径

资产模型在：

- [backend/app/models/asset.py](C:/Users/CYJ25/Desktop/vidMuse/backend/app/models/asset.py)

当前资产表核心字段是：

- `bucket_name`
- `object_key`
- `storage_uri`

所以你说“数据库存路径”，这个判断是对的。  
而且不只是存路径，还存了一个基础访问地址 `storage_uri`。

### 2.3 当前前端很多时候不是直接吃裸地址

主链路在：

- [backend/app/services/asset_service.py](C:/Users/CYJ25/Desktop/vidMuse/backend/app/services/asset_service.py)
- [backend/app/api/v1/assets.py](C:/Users/CYJ25/Desktop/vidMuse/backend/app/api/v1/assets.py)

真实行为是：

1. 上传完成时，后端会把 `storage_uri` 写进库
2. 但媒体类资源返回前端时，后端通常会再调用 `async_get_presigned_url()`
3. 所以前端很多时候拿到的是**签名 GET URL**

也就是说，当前系统已经天然接近“私有桶 + 签名 URL”这套模型。

### 2.4 当前系统的上传协议

当前上传协议是两步式：

1. 前端请求 `upload-init`
2. 后端生成对象 key 和签名上传 URL
3. 前端浏览器直传对象存储
4. 前端调用 `complete`
5. 后端校验对象存在、落库 Asset、返回资产信息

这个协议本身很好，不需要因为迁 OSS 而重做。

---

## 3. 本次迁移的目标形态

本次迁移后的正确目标，不是“公开桶永久 URL”，而是：

### 3.1 桶权限

- OSS bucket 维持 **私有读**

### 3.2 数据库存储

短期内表结构不变，继续保留：

- `bucket_name`
- `object_key`
- `storage_uri`

这里的 `storage_uri` 在私有桶模式下，定位为：

- 追溯字段
- 调试字段
- 基础地址字段

而不是匿名公网可直接访问的承诺。

### 3.3 前端访问方式

前端渲染图片 / 视频 / 音频时，统一继续使用：

- 后端返回的 **签名 GET URL**

### 3.4 模型 / 工具访问方式

所有传给模型、下游工具、异步工作流的资源 URL，也统一改成：

- **实时生成的签名 GET URL**

### 3.5 配置方式

最终目标是：

- 代码里不写死 OSS 账密
- 代码里不写死具体 bucket 配置
- 只通过 `.env` 和 `storage.yaml` 注入

---

## 4. 你同事给的 OSS 代码，在这个项目里能解决什么

你同事给的代码本质是：

```python
auth = oss2.Auth(access_key_id, access_key_secret)
bucket = oss2.Bucket(auth, endpoint, bucket_name)
result = bucket.put_object_from_file(object_name, local_file_path)
```

它只能证明一件事：

- 服务端把一个本地文件上传到 OSS 很容易

但你这个项目的真实要求远不止这一点。当前系统还需要：

1. 浏览器直传文件
2. 生成签名 `PUT` URL
3. 生成签名 `GET` URL
4. 根据 `object_key` 下载对象
5. 检查对象是否存在
6. 获取对象元数据
7. 按项目前缀删除对象
8. 让前端和模型都拿到可访问 URL

所以这段示例代码可以作为 `OSSAdapter` 的底层参考，但不能直接代表迁移完成。

---

## 5. 本次迁移的总体原则

采用下面这条路线：

1. 保留现有 API 协议
2. 保留 `Asset` 表结构
3. 新增 `OSSAdapter`
4. 新增统一存储工厂
5. 所有上层代码继续通过统一 `get_storage()` 调用
6. 所有实际对外消费媒体资源的地方统一改成签名 URL 思路
7. 所有 AK/SK 都通过 `.env` 注入

这样做的结果是：

- 前端上传流程不用改协议
- 大部分业务逻辑不用重写
- 私有桶模式成立
- 后续切换真实账密时，只需要改环境变量

---

## 6. 必须完成的代码改动清单

这一节是本次迁移的核心，后续可以直接按清单实施。

## 6.1 新增文件

需要新增 2 个文件：

1. `backend/app/storage/oss_adapter.py`
2. `backend/app/storage/storage_factory.py`

### `oss_adapter.py` 的职责

封装 `oss2`，提供和 `MinIOAdapter` 对等的能力。

至少要实现：

- `upload_file`
- `upload_bytes`
- `download_file`
- `download_bytes`
- `get_presigned_url`
- `get_upload_presigned_url`
- `object_exists`
- `get_metadata`
- `delete_object`
- `delete_prefix`
- `get_permanent_url`
- 对应的 async 包装

### 这些方法在私有桶模式下的语义

- `get_upload_presigned_url`
  - 给前端浏览器直传 OSS 的签名 `PUT` URL
- `get_presigned_url`
  - 给前端 / 模型 / 工具用的签名 `GET` URL
- `get_permanent_url`
  - 返回基础对象定位地址，用于 DB 追溯
- `download_bytes`
  - 后端内部通过 SDK 读对象，不依赖公网
- `object_exists`
  - 校验上传是否成功
- `delete_prefix`
  - 删除项目下整组对象

## 6.2 改造统一存储工厂

当前很多代码是直接这样导入的：

```python
from app.storage.minio_adapter import get_storage
```

这次迁移必须统一收口成工厂，例如：

```python
from app.storage.storage_factory import get_storage
```

工厂职责：

- 读取 `config.storage.provider`
- `provider=minio` 时返回 MinIO 实现
- `provider=oss` 时返回 OSS 实现

这是本次迁移最关键的架构改动。

## 6.3 扩展配置模型

必须修改：

1. [backend/app/core/config_loader.py](C:/Users/CYJ25/Desktop/vidMuse/backend/app/core/config_loader.py)
2. [config/base/storage.yaml](C:/Users/CYJ25/Desktop/vidMuse/config/base/storage.yaml)
3. [backend/app/core/settings.py](C:/Users/CYJ25/Desktop/vidMuse/backend/app/core/settings.py)

建议把 `storage` 配置扩成：

```yaml
storage:
  provider: ${STORAGE_PROVIDER}
  endpoint: ${OSS_ENDPOINT}
  public_base_url: ${STORAGE_PUBLIC_BASE_URL}
  access_key: ${OSS_ACCESS_KEY_ID}
  secret_key: ${OSS_ACCESS_KEY_SECRET}
  bucket: ${OSS_BUCKET}
  secure: true
  region: ${OSS_REGION}
  presigned_expiry: ${STORAGE_PRESIGNED_EXPIRY}
  max_upload_size: 104857600
```

注意：

- `endpoint` 给 SDK 用
- `public_base_url` 给基础 URL 生成用
- 虽然是私有桶，但仍建议保留 `public_base_url`，统一表达 URL 结构

## 6.4 保持上传服务协议不变

核心文件：

- [backend/app/services/asset_service.py](C:/Users/CYJ25/Desktop/vidMuse/backend/app/services/asset_service.py)

这里需要保证两件事：

### `upload_init()`

继续返回：

- `asset_id`
- `object_key`
- `bucket_name`
- `upload_url`

只是 `upload_url` 从 MinIO 签名 `PUT` 地址，改成 OSS 签名 `PUT` 地址。

### `complete_upload()`

继续做：

1. 校验对象已上传
2. 写入 `Asset`
3. 生成 `storage_uri`
4. 返回资产信息

注意这里的 `storage_uri` 在私有桶模式下不是匿名可访问链接，但仍然保留。

## 6.5 保持前端接口字段不变

核心文件：

- [backend/app/api/v1/assets.py](C:/Users/CYJ25/Desktop/vidMuse/backend/app/api/v1/assets.py)
- [frontend/src/services/api.ts](C:/Users/CYJ25/Desktop/vidMuse/frontend/src/services/api.ts)

接口形态建议保持不变：

- `POST /upload-init`
- `POST /complete`
- `GET /assets`

这样前端不用重写上传协议。

## 6.6 继续保留媒体资源签名返回

当前 [backend/app/services/asset_service.py](C:/Users/CYJ25/Desktop/vidMuse/backend/app/services/asset_service.py) 的 `_asset_to_dict_presigned()` 已经有这个逻辑：

- `image/*`
- `video/*`
- `audio/*`

优先转成签名 GET URL 再返回前端。

本次迁移要做的是：

- 保留这个思路
- 把底层签名实现从 MinIO 切到 OSS

换句话说，这里不是推翻，而是沿用。

---

## 7. 必须统一改造的文件类别

这一节不只是“可能受影响”，而是后续迁移时必须逐个过一遍。

## 7.1 直接依赖 `minio_adapter.get_storage` 的文件

当前明确搜到的文件包括：

1. `backend/app/services/asset_service.py`
2. `backend/app/services/audio_analysis_service.py`
3. `backend/app/services/asset_sync_service.py`
4. `backend/app/services/export_service.py`
5. `backend/app/services/project_service.py`
6. `backend/app/services/timeline_composer_service.py`
7. `backend/app/services/visual_bible_service.py`
8. `backend/app/tools/audio_trim_tool.py`
9. `backend/app/tools/image_generation_tool.py`
10. `backend/app/tools/lipsync_tool.py`
11. `backend/app/tools/video_generation_tool.py`
12. `backend/app/tools/shared/artifact_tools.py`
13. `backend/app/api/v1/health.py`
14. `backend/app/bootstrap/services.py`

这些文件必须统一改成从 `storage_factory` 导入 `get_storage()`。

## 7.2 直接消费 `storage_uri` 的高风险文件

当前明确搜到的高风险位置包括：

1. `backend/app/workflows/main_graph.py`
2. `backend/app/services/shot_regeneration_service.py`
3. `backend/app/services/prompt_compiler_service.py`
4. `backend/app/services/clip_service.py`
5. `backend/app/services/storyboard_service.py`
6. `backend/app/services/lipsync_service.py`
7. `backend/app/services/audio_analysis_service.py`
8. `backend/app/api/v1/audio_analysis.py`
9. `backend/app/api/v1/clips.py`
10. `backend/app/api/v1/exports.py`
11. `backend/app/api/v1/storyboard.py`
12. `backend/app/api/v1/timeline.py`
13. `backend/app/tools/image_generation_tool.py`
14. `backend/app/tools/shared/artifact_tools.py`

这些地方后续都要判断：

- 是给前端返回资源
- 还是给模型传资源
- 还是后端内部自己消费

处理原则必须统一：

- 给前端：返回签名 URL
- 给模型：传签名 URL
- 后端内部：尽量直接用 `bucket_name + object_key + SDK`

## 7.3 直接写死 MinIO 语义的注释 / 日志 / 文档串

重点要同步修正：

1. [backend/app/models/asset.py](C:/Users/CYJ25/Desktop/vidMuse/backend/app/models/asset.py)
2. [backend/app/services/asset_service.py](C:/Users/CYJ25/Desktop/vidMuse/backend/app/services/asset_service.py)
3. [backend/app/api/v1/assets.py](C:/Users/CYJ25/Desktop/vidMuse/backend/app/api/v1/assets.py)
4. `backend/app/agents/audio_analysis_agent.py`
5. `backend/app/schemas/storyboard.py`

如果不改，后面会持续误导排查。

---

## 8. 私有桶模式下，哪些链路要特别留意

## 8.1 前端渲染链路

前端如果继续通过：

- `<img src=...>`
- `<video src=...>`
- `<audio src=...>`

来渲染资源，就必须保证后端返回的是：

- 有效期内可访问的签名 GET URL

## 8.2 模型引用链路

这是本次迁移里最容易漏的点。

如果某些地方仍然把数据库里的裸 `storage_uri` 直接传给模型，在私有桶模式下就会失败。

因此必须检查：

- 图像生成参考图
- 视频生成参考图
- lipsync 的人脸图 / 音频片段
- storyboard / nine-grid 资源
- 工作流中的图像、音频 URL 透传

这些地方如果是“交给外部模型去拉 URL”，就必须改成先生成签名 URL 再传。

## 8.3 后端内部下载链路

如果是后端自己下载对象做处理，优先不要走 URL，而是走：

- `bucket_name`
- `object_key`
- SDK 下载

这在私有桶模式下最稳。

---

## 9. OSS 侧必须满足的条件

即使是私有桶，OSS 侧也必须满足以下条件：

## 9.1 后端可访问 OSS

你的后端运行环境必须能访问：

- `oss-cn-beijing.aliyuncs.com`

或者你后续配置的真实 endpoint。

## 9.2 后端有权限生成签名 URL

你使用的 AK/SK 必须具备：

- 上传
- 下载
- `head object`
- 生成签名 URL
- 删除对象

## 9.3 浏览器直传需要 CORS

至少要允许：

- `PUT`
- `GET`
- `HEAD`
- `Content-Type`

否则前端直传会失败。

## 9.4 模型消费方能访问签名 URL

即使 bucket 私有，签名 URL 也必须对真实消费方可达。

也就是说你后续的白名单策略，不能把真正消费签名 URL 的环境挡住。

---

## 10. 最终 `.env` 需要填写的内容

如果代码按本文档完成改造，后续你只需要在 `.env` 或部署环境中填写：

```env
STORAGE_PROVIDER=oss
OSS_ACCESS_KEY_ID=你的真实AK
OSS_ACCESS_KEY_SECRET=你的真实SK
OSS_BUCKET=guangxiprod
OSS_ENDPOINT=oss-cn-beijing.aliyuncs.com
OSS_REGION=cn-beijing
STORAGE_PUBLIC_BASE_URL=https://guangxiprod.oss-cn-beijing.aliyuncs.com
STORAGE_PRESIGNED_EXPIRY=3600
```

你后续真正需要改的只有：

1. 真实 `AK/SK`
2. 真实 bucket
3. endpoint / region
4. 白名单 / CORS / 私有权限策略

业务代码不应该再因为换账号而改。

---

## 11. 推荐实施顺序

## 11.1 第一步：完成底层接入

先做这些：

1. 新增 `OSSAdapter`
2. 新增 `storage_factory`
3. 改造 `config_loader.py`
4. 改造 `settings.py`
5. 改造 `storage.yaml`

目标：

- `provider=oss` 时，系统底层已经能切到 OSS

## 11.2 第二步：统一替换 `get_storage()` 导入

把所有直接导入 `minio_adapter.get_storage` 的地方，替换成统一工厂。

目标：

- 业务层不再直接知道底层是 MinIO 还是 OSS

## 11.3 第三步：统一清理资源 URL 消费方式

把所有“直接把 `storage_uri` 当外部可访问地址用”的地方逐个检查。

目标：

- 前端拿签名 URL
- 模型拿签名 URL
- 后端内部尽量走 SDK

## 11.4 第四步：联调上传与渲染

至少验证：

1. 前端能拿到 OSS 签名 `PUT` URL
2. 浏览器直传成功
3. `complete` 成功落库
4. 资产列表返回签名 `GET` URL
5. 图片能显示
6. 视频能播放
7. 音频能预览

## 11.5 第五步：联调模型和异步链路

至少验证：

1. 参考图 URL 可被模型访问
2. 音频片段 URL 可被模型访问
3. nine-grid / storyboard 素材 URL 可被模型访问
4. 项目删除可清理对象前缀

---

## 12. 验收清单

迁移完成后，至少要通过下面 10 项验收：

1. `upload-init` 返回 OSS 签名 `PUT` URL
2. 图片浏览器直传成功
3. 音频浏览器直传成功
4. `complete` 能校验 OSS 对象并落库
5. 资产接口返回签名 `GET` URL
6. 前端图片展示正常
7. 前端视频播放正常
8. 前端音频播放正常
9. 传给模型的资源 URL 在有效期内可访问
10. 项目删除时 OSS 对象前缀能清理

---

## 13. 最终结论

这次迁移的正确做法不是“把上传函数换成 OSS”，而是：

1. 保留现有存储抽象
2. 新增 `OSSAdapter`
3. 新增统一存储工厂
4. 保留当前上传协议
5. 保留 `Asset` 表结构
6. 统一把外部资源消费方式收口到签名 URL
7. 统一把真实配置收口到 `.env`

这样做完以后，你后续就不需要再碰业务代码，只需要在环境变量里替换真实 OSS 配置即可。

