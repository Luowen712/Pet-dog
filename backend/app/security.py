import hashlib
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings


def hash_pwd(raw: str) -> str:
    """把明文密码变成一串固定长度的哈希，不可逆。"""
    return hashlib.sha256(("pet$" + raw).encode("utf-8")).hexdigest()


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
