"""JWT 安全模块。

工程约束（doc 08 / R2）：
  - JWT secret 通过 settings.security.secret 读取（来自 ${JWT_SECRET} 环境变量）
  - 绝不允许在代码中硬编码 secret
  - access token 短期有效（默认 30 分钟）
  - refresh token 长期有效（默认 7 天）
  - token payload 只放最小信息：user_id + token type + 过期时间

用法：
    from app.core.security import hash_password, verify_password
    from app.core.security import create_access_token, create_refresh_token, decode_token

    hashed = hash_password("my_password")
    ok = verify_password("my_password", hashed)

    token = create_access_token(user_id="usr_01")
    payload = decode_token(token)  # {"sub": "usr_01", "type": "access", "exp": ...}
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.logging import get_logger
from app.core.settings import settings

_logger = get_logger("core.security", layer="system")

# ---------------------------------------------------------------------------
# 密码哈希上下文（bcrypt，自动加 salt）
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """返回 bcrypt 哈希值，可直接存入数据库。"""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与存储的哈希值是否匹配。"""
    return _pwd_context.verify(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# JWT Token 签发
# ---------------------------------------------------------------------------

TokenType = Literal["access", "refresh"]


def _get_secret() -> str:
    """从 settings 获取 JWT secret，每次动态读取（不做模块级缓存）。"""
    return settings.security.secret


def create_access_token(user_id: str) -> str:
    """签发 access token。

    Payload:
        sub: user_id
        type: "access"
        exp: now + access_token_expire_minutes
        iat: now
    """
    sec = settings.security
    expire = datetime.now(timezone.utc) + timedelta(minutes=sec.access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _get_secret(), algorithm=sec.algorithm)


def create_refresh_token(user_id: str) -> str:
    """签发 refresh token。

    Payload:
        sub: user_id
        type: "refresh"
        exp: now + refresh_token_expire_days
        iat: now
    """
    sec = settings.security
    expire = datetime.now(timezone.utc) + timedelta(days=sec.refresh_token_expire_days)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _get_secret(), algorithm=sec.algorithm)


# ---------------------------------------------------------------------------
# Token 解析
# ---------------------------------------------------------------------------

class TokenDecodeError(Exception):
    """Token 解析失败（过期、签名错误、格式错误等）。"""
    pass


def decode_token(token: str, expected_type: TokenType | None = None) -> dict:
    """解析并验证 JWT token。

    Args:
        token: JWT 字符串。
        expected_type: 若指定，则校验 payload 中 type 字段。
            传 "access" 时拒绝 refresh token，反之亦然。

    Returns:
        解码后的 payload dict，包含 sub / type / exp / iat。

    Raises:
        TokenDecodeError: token 无效、过期、签名错误、类型不匹配。
    """
    sec = settings.security
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[sec.algorithm])
    except JWTError as e:
        raise TokenDecodeError(f"Token 解析失败: {e}") from e

    if expected_type is not None and payload.get("type") != expected_type:
        raise TokenDecodeError(
            f"Token 类型不匹配：期望 '{expected_type}'，实际 '{payload.get('type')}'"
        )

    if "sub" not in payload:
        raise TokenDecodeError("Token payload 缺少 'sub' 字段")

    return payload


def get_user_id_from_token(token: str, expected_type: TokenType = "access") -> str:
    """从 token 中提取 user_id，内部调用 decode_token。

    Raises:
        TokenDecodeError: token 无效时。
    """
    payload = decode_token(token, expected_type=expected_type)
    return payload["sub"]
