import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import settings

# 旧版哈希的固定盐。只在验证存量密码时使用，新密码一律走 Argon2id。
_LEGACY_SALT = "pet$"
# Argon2id 的 PHC 串前缀，用来区分新旧格式。
_PHC_PREFIX = "$argon2id$"

# 模块级创建：argon2 后端不可用时这里就抛异常，进程起不来。
# 这是刻意的——宁可启动失败，也不能悄悄回落到弱哈希。
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)



def hash_pwd(raw: str) -> str:
    """生成 Argon2id 哈希。盐和参数都编码在返回值里，不需要额外存储。"""
    return _hasher.hash(raw)



def _is_legacy_hash(stored: str) -> bool:
    """旧格式：64 个十六进制字符的 SHA-256 摘要。"""
    if len(stored) != 64:
        return False
    try:
        bytes.fromhex(stored)
    except ValueError:
        return False
    return True



def _verify_legacy(stored: str, raw: str) -> bool:
    """用旧的固定盐 + SHA-256 复算，与存量摘要比对。"""
    calc = hashlib.sha256((_LEGACY_SALT + raw).encode("utf-8")).hexdigest()
    return hmac.compare_digest(stored, calc)



def verify_pwd(stored: str, raw: str) -> bool:
    """校验密码。新格式走 Argon2id，旧格式走 SHA-256；认不出的格式一律 False。"""
    if not stored or not raw:
        return False
    if stored.startswith(_PHC_PREFIX):
        try:
            _hasher.verify(stored, raw)
        except (VerificationError, InvalidHashError):
            return False
        return True
    if _is_legacy_hash(stored):
        return _verify_legacy(stored, raw)
    return False



def needs_rehash(stored: str) -> bool:
    """这个哈希是否需要升级。登录验证通过后调用，True 则重算并写回。"""
    if not stored or not stored.startswith(_PHC_PREFIX):
        return True
    try:
        return _hasher.check_needs_rehash(stored)
    except InvalidHashError:
        return True



def make_token(user_id: int, username: str, tv: int) -> str:
    """签发 JWT，里面装着用户 id、用户名和过期时间。"""
    payload = {
        "uid": user_id,
        "sub": username,
        "tv": tv,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")



def parse_token(token: str):
    """校验并解出 JWT 内容；签名不对或已过期，返回 None。"""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return None
