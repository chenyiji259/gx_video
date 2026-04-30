r"""
独立 OSS 私有桶上传与签名访问测试脚本。

用途：
1. 从本地读取一张图片
2. 上传到指定 OSS bucket
3. 打印基础存储地址
4. 生成签名 GET URL 并打印

不依赖当前项目业务代码，只依赖 oss2。

运行前请先设置 Windows + Codex 必要环境变量：
    $env:SystemRoot='C:\Windows'
    $env:windir='C:\Windows'
    $env:COMSPEC='C:\Windows\System32\cmd.exe'

示例：
    python scripts/test_oss_private_bucket.py

可选环境变量：
    OSS_ACCESS_KEY_ID
    OSS_ACCESS_KEY_SECRET
    OSS_BUCKET
    OSS_ENDPOINT
    OSS_REGION
    OSS_PUBLIC_BASE_URL
    OSS_SIGNED_URL_EXPIRES
    OSS_TEST_FILE
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

try:
    import oss2
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "缺少依赖 oss2，请先安装：pip install oss2"
    ) from exc


DEFAULT_LOCAL_FILE = Path(
    r"C:\Users\CYJ25\Desktop\work\autp_video_agent\docs\架构图-clear.png"
)
DEFAULT_BUCKET = "guangxiprod"
DEFAULT_ENDPOINT = "oss-cn-beijing.aliyuncs.com"
DEFAULT_REGION = "cn-beijing"
DEFAULT_EXPIRES = 3600


def _get_env(name: str, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    return value


def _require_env(name: str) -> str:
    value = _get_env(name)
    if not value:
        raise SystemExit(f"缺少环境变量: {name}")
    return value


def build_object_name(local_file: Path) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = local_file.name.replace(" ", "_")
    return f"manual-tests/oss-private-bucket/{timestamp}_{safe_name}"


def build_base_url(bucket: str, public_base_url: str, object_name: str) -> str:
    if public_base_url:
        return f"{public_base_url.rstrip('/')}/{quote(object_name)}"
    return f"https://{bucket}.{DEFAULT_ENDPOINT}/{quote(object_name)}"


def main() -> int:
    access_key_id = _require_env("OSS_ACCESS_KEY_ID")
    access_key_secret = _require_env("OSS_ACCESS_KEY_SECRET")
    bucket_name = _get_env("OSS_BUCKET", DEFAULT_BUCKET)
    endpoint = _get_env("OSS_ENDPOINT", DEFAULT_ENDPOINT)
    region = _get_env("OSS_REGION", DEFAULT_REGION)
    public_base_url = _get_env(
        "OSS_PUBLIC_BASE_URL",
        f"https://{bucket_name}.{endpoint}",
    )
    expires = int(_get_env("OSS_SIGNED_URL_EXPIRES", str(DEFAULT_EXPIRES)))

    local_file = Path(_get_env("OSS_TEST_FILE", str(DEFAULT_LOCAL_FILE)))
    if not local_file.exists():
        raise SystemExit(f"本地文件不存在: {local_file}")

    object_name = build_object_name(local_file)

    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, f"https://{endpoint}", bucket_name, region=region)

    print("开始上传...")
    print(f"bucket={bucket_name}")
    print(f"endpoint={endpoint}")
    print(f"region={region}")
    print(f"local_file={local_file}")
    print(f"object_name={object_name}")

    result = bucket.put_object_from_file(object_name, str(local_file))
    if result.status not in (200, 201):
        raise SystemExit(f"上传失败，status={result.status}")

    base_url = build_base_url(bucket_name, public_base_url, object_name)
    signed_url = bucket.sign_url("GET", object_name, expires)

    print("")
    print("上传完成")
    print(f"status={result.status}")
    print(f"object_name={object_name}")
    print(f"base_url={base_url}")
    print(f"signed_url={signed_url}")
    print("")
    print("请把 signed_url 复制到浏览器验证是否可打开。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
