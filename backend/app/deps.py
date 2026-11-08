from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.security import parse_token

# auto_error=False：头缺失时不抛 FastAPI 默认的 403，交给我们自己返 40100
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="Bearer Token")


def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    """从 Authorization: Bearer <token> 里取出用户信息，验不过就 401。"""
    if cred is None or cred.scheme.lower() != "bearer":
        raise HTTPException(401, detail={"code": 40100, "message": "未登录"})

    data = parse_token(cred.credentials)
    if not data:
        raise HTTPException(401, detail={"code": 40101, "message": "登录已过期"})

    return data
