# VidMuse OSS 对象存储接入说明

本文档用于给其他项目或 AI 助手快速复用 VidMuse 当前的阿里云 OSS 接入方式。内容以当前代码为准，覆盖配置、连接、上传、读取、签名 URL、数据库字段、前端直传和验证方式。

> 当前项目已经接入 OSS。统一存储入口是 `backend/app/storage/storage_factory.py` 的 `get_storage()`，底层实现是 `backend/app/storage/oss_adapter.py` 的 `OSSAdapter`。

## 1. 当前接入结论

VidMuse 当前采用的是“私有 OSS bucket + 后端签名 URL + 前端直传”的模式。

核心行为：

- 服务端通过 `oss2` SDK 连接阿里云 OSS。
- 业务代码不直接操作 `oss2`，统一通过 `get_storage()` 获取存储适配器。
- 前端上传文件时，先请求后端拿 `PUT` 预签名 URL，再由浏览器直接 `PUT` 到 OSS。
- 上传完成后，前端调用后端 `complete` 接口，后端用 OSS SDK 校验对象存在，再把资产记录写入数据库。
- 数据库保存 `bucket_name`、`object_key`、`storage_uri`。
- 前端或外部模型需要读取资源时，后端根据 `object_key` 动态生成 `GET` 签名 URL。
- 后端内部读取文件时，优先用 SDK 按 `bucket_name + object_key` 下载，不依赖公网 URL。

## 2. 依赖

Python 后端依赖：

```txt
oss2>=2.18.6
python-dotenv>=1.0.1
pyyaml>=6.0.2
```

VidMuse 中依赖声明位置：

```text
backend/requirements.txt
```

另一个项目接入时至少需要安装：

```bash
pip install oss2 python-dotenv pyyaml
```

## 3. 环境变量

VidMuse 当前使用 `STORAGE_*` 变量命名，而不是 `OSS_*`。

```env
STORAGE_ENDPOINT=https://oss-cn-beijing.aliyuncs.com
STORAGE_PUBLIC_BASE_URL=https://muse.oss-cn-beijing.aliyuncs.com
STORAGE_ACCESS_KEY=你的 AccessKey ID
STORAGE_SECRET_KEY=你的 AccessKey Secret
STORAGE_BUCKET=你的 bucket 名称
STORAGE_REGION=cn-beijing
STORAGE_SECURE=true
```

字段含义：

| 变量 | 作用 |
| --- | --- |
| `STORAGE_ENDPOINT` | OSS SDK endpoint，用于 `oss2.Bucket(auth, endpoint, bucket)` |
| `STORAGE_PUBLIC_BASE_URL` | 生成基础对象地址的前缀，通常是 `https://{bucket}.oss-cn-beijing.aliyuncs.com` 或自定义域名 |
| `STORAGE_ACCESS_KEY` | 阿里云 AccessKey ID |
| `STORAGE_SECRET_KEY` | 阿里云 AccessKey Secret |
| `STORAGE_BUCKET` | 默认 bucket |
| `STORAGE_REGION` | OSS region，例如 `cn-beijing` |
| `STORAGE_SECURE` | 是否使用 HTTPS，生产应为 `true` |

当前真实值不要写进可提交文档。VidMuse 已在本地私有附录中记录真实配置，见仓库根目录的 `.env.oss-reference.md`。该文件被 `.gitignore` 的 `.env.*` 规则忽略，不应提交。

## 4. 配置加载

VidMuse 的配置链路是：

```text
.env
  -> config/base/storage.yaml
  -> backend/app/core/config_loader.py::load_storage_config()
  -> backend/app/core/config.py::get_config().storage
  -> backend/app/storage/oss_adapter.py::OSSAdapter
```

`config/base/storage.yaml`：

```yaml
storage:
  endpoint: "${STORAGE_ENDPOINT}"
  public_base_url: "${STORAGE_PUBLIC_BASE_URL}"
  access_key: "${STORAGE_ACCESS_KEY}"
  secret_key: "${STORAGE_SECRET_KEY}"
  bucket: "${STORAGE_BUCKET}"
  secure: "${STORAGE_SECURE}"
  region: "${STORAGE_REGION}"
  max_upload_size: 104857600
  presigned_expiry: 3600
```

配置模型核心字段：

```python
class StorageConfig(BaseModel):
    endpoint: str
    public_base_url: str = ""
    access_key: str
    secret_key: str
    bucket: str
    secure: bool = False
    region: str = "us-east-1"
    presigned_expiry: int = 3600
    max_upload_size: int = 104857600
```

另一个项目可以照搬这个结构：环境变量只承载密钥和值，业务代码统一从配置对象读取，不要散落 `os.getenv()`。

## 5. 统一存储入口

VidMuse 不让业务层直接创建 OSS client，而是统一使用：

```python
from app.storage.storage_factory import get_storage

storage = get_storage()
```

当前工厂实现：

```python
from app.storage.oss_adapter import OSSAdapter

_adapter: OSSAdapter | None = None

def get_storage() -> OSSAdapter:
    global _adapter
    if _adapter is None:
        _adapter = OSSAdapter()
    return _adapter
```

另一个项目也建议保留这个入口。以后如果切换 S3、MinIO 或其他对象存储，只替换适配器，不改业务调用方。

## 6. OSSAdapter 能力

VidMuse 的 `OSSAdapter` 位于：

```text
backend/app/storage/oss_adapter.py
```

初始化逻辑：

```python
cfg = get_config().storage
auth = oss2.Auth(cfg.access_key, cfg.secret_key)
bucket = oss2.Bucket(auth, endpoint, cfg.bucket)
```

核心方法：

| 方法 | 作用 | 典型使用场景 |
| --- | --- | --- |
| `get_upload_presigned_url(key, expiry_seconds=1800)` | 生成 `PUT` 签名 URL | 前端浏览器直传 |
| `get_presigned_url(key, expiry_seconds=None, method="GET")` | 生成 `GET` 签名 URL | 前端展示、模型读取 |
| `get_permanent_url(key)` | 生成基础对象地址 | 写入数据库，做追溯定位 |
| `upload_file(key, file_path, content_type)` | 服务端上传本地文件 | 生成视频、导出文件、时间线产物 |
| `upload_bytes(key, data, content_type)` | 服务端上传字节 | AI 生成图片、JSON 产物 |
| `download_file(key, dest_path)` | 下载到本地文件 | 本地追溯副本 |
| `download_bytes(key)` | 下载为 bytes | 后端内部处理 |
| `get_metadata(key)` | `HEAD` 对象元信息 | 上传完成校验、获取 size/etag |
| `object_exists(key)` | 判断对象是否存在 | 校验或幂等逻辑 |
| `delete_object(key)` | 删除单个对象 | 清理单资源 |
| `delete_prefix(prefix)` | 批量删除前缀下对象 | 删除项目时清理 `projects/{project_id}/` |

异步业务代码使用 `async_*` 方法，例如：

```python
upload_url = await storage.async_get_upload_presigned_url(object_key, expiry_seconds=1800)
access_url = await storage.async_get_presigned_url(object_key, bucket=bucket_name)
await storage.async_upload_bytes(object_key, image_bytes, content_type="image/png")
data = await storage.async_download_bytes(object_key, bucket=bucket_name)
```

这些异步方法内部用 `asyncio.to_thread()` 包装同步 OSS SDK 调用。

## 7. 对象 Key 规范

用户上传资产：

```text
projects/{project_id}/assets/{asset_type}/{asset_id}/{filename}
```

工作流 JSON 产物：

```text
projects/{project_id}/artifacts/{artifact_type}/v{version_no}/{filename}
```

AI 生成媒体、视频片段、导出文件等也统一放在：

```text
projects/{project_id}/...
```

这样删除项目时可以直接清理：

```python
await storage.async_delete_prefix(f"projects/{project_id}/")
```

## 8. 数据库字段

VidMuse 的资产表模型在：

```text
backend/app/models/asset.py
```

和 OSS 相关的字段：

```python
bucket_name: str
object_key: str
storage_uri: str
mime_type: str
size_bytes: int | None
sha256: str | None
metadata_: dict
```

语义：

- `bucket_name`：真实 OSS bucket。
- `object_key`：OSS 对象路径，是生成签名 URL 和 SDK 下载的核心字段。
- `storage_uri`：基础对象定位地址，用于追溯和调试；私有桶模式下不要把它当作长期匿名可访问地址。

推荐原则：

- 数据库必须保存 `bucket_name + object_key`。
- 前端/API 返回时可以把 `storage_uri` 字段填成签名 URL，以兼容旧前端字段名。
- 后端内部不要从 `storage_uri` 反解析 key，除非是兼容历史数据。

## 9. 前端直传上传 API

VidMuse 的上传 API 位于：

```text
backend/app/api/v1/assets.py
backend/app/services/asset_service.py
frontend/src/services/api.ts
```

### 9.1 第一步：初始化上传

请求：

```http
POST /projects/{project_id}/assets/upload-init
Content-Type: application/json

{
  "filename": "demo.png",
  "content_type": "image/png",
  "asset_type": "image_reference"
}
```

后端处理：

1. 校验项目归属。
2. 推断或校验 `asset_type`。
3. 生成 `asset_id`。
4. 生成 `object_key`。
5. 调用 OSS 生成 `PUT` 签名 URL。

返回：

```json
{
  "success": true,
  "data": {
    "asset_id": "01...",
    "upload_url": "https://...签名PUT地址...",
    "object_key": "projects/{project_id}/assets/image_reference/{asset_id}/demo.png",
    "bucket_name": "bucket-name",
    "expires_in": 1800
  }
}
```

关键代码：

```python
storage = get_storage()
upload_url = await storage.async_get_upload_presigned_url(
    object_key,
    expiry_seconds=1800,
)
bucket_name = storage.default_bucket
```

### 9.2 第二步：浏览器直接 PUT 到 OSS

前端代码：

```ts
await fetch(uploadUrl, {
  method: 'PUT',
  body: file,
  headers: {
    'Content-Type': file.type,
  },
});
```

注意：

- `Content-Type` 需要和后端申请签名时预期一致。
- OSS bucket 必须配置 CORS，允许前端域名发起 `PUT`。

### 9.3 第三步：确认上传完成

请求：

```http
POST /projects/{project_id}/assets/complete
Content-Type: application/json

{
  "asset_id": "upload-init 返回值",
  "object_key": "upload-init 返回值",
  "bucket_name": "upload-init 返回值",
  "filename": "demo.png",
  "content_type": "image/png",
  "asset_type": "image_reference"
}
```

后端处理：

1. 校验项目归属。
2. 调用 `get_metadata(object_key)`，确认对象已上传并读取大小。
3. 调用 `get_permanent_url(object_key)` 生成基础定位地址。
4. 写入 `assets` 表。
5. 需要时下载一份本地追溯副本。
6. 返回资产信息，`storage_uri` 优先填签名 GET URL。

关键代码：

```python
meta = await storage.async_get_metadata(object_key, bucket=bucket_name)
storage_uri = storage.get_permanent_url(object_key, bucket=bucket_name)
```

## 10. 读取和签名 URL

私有 OSS bucket 下，前端和外部模型不能依赖裸 `storage_uri`。VidMuse 统一通过：

```text
backend/app/services/asset_access_service.py
```

核心函数：

```python
async def build_asset_access_url(asset: Asset | None) -> str | None:
    if asset is None:
        return None
    if not asset.object_key:
        return asset.storage_uri or None

    try:
        storage = get_storage()
        return await storage.async_get_presigned_url(
            asset.object_key,
            bucket=asset.bucket_name,
        )
    except Exception:
        return asset.storage_uri or None
```

使用原则：

- 给前端展示图片、视频、音频：返回签名 `GET` URL。
- 给外部模型读取参考图、音频、视频：返回签名 `GET` URL。
- 后端自己处理文件：用 `download_bytes()` 或 `download_file()`，不要绕公网 URL。

## 11. 服务端上传产物

AI 生成图片、视频、时间线预览、导出文件、JSON 产物等，不走前端直传，而是后端生成后直接上传 OSS。

上传 bytes：

```python
storage = get_storage()
await storage.async_upload_bytes(object_key, image_bytes, content_type="image/png")
storage_uri = storage.get_permanent_url(object_key)
```

上传本地文件：

```python
storage = get_storage()
await storage.async_upload_file(object_key, output_path, content_type="video/mp4")
storage_uri = storage.get_permanent_url(object_key)
```

落库时仍保存：

```python
Asset(
    bucket_name=storage.default_bucket,
    object_key=object_key,
    storage_uri=storage_uri,
    mime_type=content_type,
    size_bytes=size_bytes,
)
```

## 12. 项目删除时清理 OSS

VidMuse 删除项目时会清理整个项目前缀：

```python
storage = get_storage()
prefix = f"projects/{project_id}/"
deleted_count = await storage.async_delete_prefix(prefix)
```

`delete_prefix()` 内部使用 `oss2.ObjectIterator` 遍历对象，并按 1000 条一批调用 `batch_delete_objects()`。

注意：删除是不可逆动作，另一个项目接入时应先确认权限和前缀边界，避免误删其他业务对象。

## 13. OSS Bucket 权限和 CORS

私有 bucket 至少需要满足：

- 后端 AK/SK 具备 `PutObject`、`GetObject`、`HeadObject`、`DeleteObject`、`ListObjects` 权限。
- 浏览器直传需要 OSS CORS 允许前端域名。
- 外部模型如果需要拉取签名 URL，必须能访问 OSS 公网或对应自定义域名。

推荐 CORS：

```text
AllowedOrigin: 你的前端域名，开发环境可临时加 http://localhost:3000 / http://localhost:5173
AllowedMethod: GET, PUT, HEAD
AllowedHeader: Content-Type, Authorization, x-oss-*
ExposeHeader: ETag, x-oss-request-id
MaxAgeSeconds: 3600
```

生产环境不要长期使用 `AllowedOrigin=*`，除非你明确接受跨站直传风险。

## 14. 最小可复用代码骨架

```python
from pathlib import Path
import asyncio
import io
from urllib.parse import quote

import oss2


class OSSAdapter:
    def __init__(self, cfg):
        self.default_bucket = cfg.bucket
        self.presigned_expiry = cfg.presigned_expiry
        endpoint = cfg.endpoint.rstrip("/")
        if not endpoint.startswith(("http://", "https://")):
            endpoint = f"https://{endpoint}" if cfg.secure else f"http://{endpoint}"
        self.endpoint = endpoint
        self.public_base_url = (cfg.public_base_url or f"https://{cfg.bucket}.{endpoint.split('://', 1)[-1]}").rstrip("/")
        self.auth = oss2.Auth(cfg.access_key, cfg.secret_key)
        self.client = oss2.Bucket(self.auth, self.endpoint, cfg.bucket)

    def get_permanent_url(self, key: str) -> str:
        return f"{self.public_base_url}/{quote(key, safe='/')}"

    def get_upload_presigned_url(self, key: str, expiry_seconds: int = 1800) -> str:
        return self.client.sign_url("PUT", key, expiry_seconds)

    def get_presigned_url(self, key: str, expiry_seconds: int | None = None, method: str = "GET") -> str:
        return self.client.sign_url(method.upper(), key, expiry_seconds or self.presigned_expiry)

    def upload_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self.client.put_object(key, io.BytesIO(data), headers={"Content-Type": content_type})
        return self.get_permanent_url(key)

    def download_bytes(self, key: str) -> bytes:
        resp = self.client.get_object(key)
        try:
            return resp.read()
        finally:
            resp.close()

    def get_metadata(self, key: str):
        return self.client.head_object(key)

    async def async_get_presigned_url(self, *args, **kwargs) -> str:
        return await asyncio.to_thread(self.get_presigned_url, *args, **kwargs)
```

正式项目建议使用 VidMuse 当前的完整 `OSSAdapter`，不要只复制这个最小版。

## 15. 验证方式

VidMuse 有独立测试脚本：

```text
scripts/test_oss_private_bucket.py
```

脚本做四件事：

1. 读取环境变量里的 AK/SK、bucket、endpoint、region。
2. 上传一个本地文件到 OSS。
3. 打印基础对象地址。
4. 生成签名 GET URL。

Windows + Codex 环境运行 Python 前先补齐：

```powershell
$env:SystemRoot='C:\Windows'
$env:windir='C:\Windows'
$env:COMSPEC='C:\Windows\System32\cmd.exe'
```

脚本当前使用的是 `OSS_*` 变量名，和主项目 `STORAGE_*` 不完全一致。运行脚本时可以临时映射：

```powershell
$env:OSS_ACCESS_KEY_ID=$env:STORAGE_ACCESS_KEY
$env:OSS_ACCESS_KEY_SECRET=$env:STORAGE_SECRET_KEY
$env:OSS_BUCKET=$env:STORAGE_BUCKET
$env:OSS_ENDPOINT='oss-cn-beijing.aliyuncs.com'
$env:OSS_REGION=$env:STORAGE_REGION
$env:OSS_PUBLIC_BASE_URL=$env:STORAGE_PUBLIC_BASE_URL
python scripts/test_oss_private_bucket.py
```

## 16. 另一个项目接入清单

1. 安装 `oss2`。
2. 增加 `STORAGE_*` 环境变量。
3. 增加 `storage.yaml` 或等价配置模型。
4. 增加 `OSSAdapter`。
5. 增加统一 `get_storage()`。
6. 数据库保存 `bucket_name`、`object_key`、`storage_uri`。
7. 上传采用 `upload-init -> PUT OSS -> complete` 三步。
8. 前端和模型读取资源时统一走后端签名 GET URL。
9. 后端内部处理资源时走 SDK 下载。
10. OSS 配置 CORS 和最小权限。
11. 用独立脚本验证上传、HEAD、签名 GET、下载。
12. 项目删除或资源删除时只清理明确前缀。

## 17. 关键注意事项

- `storage_uri` 在私有桶下是定位地址，不是长期可匿名访问承诺。
- 传给前端和模型的 URL 应该是短期签名 URL。
- 不要在前端保存 AK/SK。
- 不要让浏览器通过后端中转大文件，使用签名 URL 直传。
- 不要只保存完整 URL，必须保存 `object_key`，否则后续签名、下载、删除都不稳定。
- 不要把真实 AK/SK 写进会提交的文档或代码。
- OSS CORS 配置错误时，后端签名成功但浏览器 `PUT` 仍会失败。
- 外部模型读取签名 URL 时，有效期要覆盖模型拉取资源的时间窗口。
