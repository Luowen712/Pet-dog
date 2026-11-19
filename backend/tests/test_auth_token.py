"""JWT 鉴权口径 —— 旧票、错版本、非 active 账号都必须挡在门外。

为什么单独测这一块：
    make_token 现在会写入 tv（token_version）声明，但历史签发的 token 里
    没有这个字段。如果校验写成 data.get("tv", 0)，那些旧票会被当成 tv=0；
    而绝大多数账号的 token_version 恰好就是 0 —— 等于让所有历史 token 复活。
    必须显式判 None 再拒绝，这条边界只能靠测试钉住。

为什么走 HTTP 而不是直接调 current_user：
    只有真正打一次接口，才能同时验证「deps 抛的 HTTPException」和
    「errors.py 把它转成 {code,message} 信封」这两段接得上。
    直接调函数测不到状态码和响应体。
"""

import jwt
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import User
from app.security import hash_pwd, make_token

USERNAME = "token_case"
PASSWORD = "pw-token-7f3a"

client = TestClient(app)


def _seed(**kwargs) -> User:
    """建一个用于本文件的账号，多余字段由调用方覆盖。"""
    db = SessionLocal()
    try:
        db.query(User).filter(User.username == USERNAME).delete()
        u = User(username=USERNAME, password_hash=hash_pwd(PASSWORD), **kwargs)
        db.add(u)
        db.commit()
        db.refresh(u)
        db.expunge(u)
        return u
    finally:
        db.close()


def _legacy_token(uid: int, username: str) -> str:
    """签一个不含 tv 的旧式 token —— 模拟改造前签发的票。"""
    return jwt.encode(
        {"uid": uid, "sub": username},
        settings.JWT_SECRET,
        algorithm="HS256",
    )


def test_missing_header_40100():
    """没带 Authorization 头 → 40100 未登录，而不是 FastAPI 默认的 403。"""
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == 40100


def test_legacy_token_without_tv_rejected():
    """旧票（缺 tv 声明）必须拒绝。

    这是本文件最重要的一条：如果实现写成 data.get("tv", 0)，
    这个用例会失败，而接口在真实环境里会悄悄放行所有历史 token。
    """
    u = _seed()
    token = _legacy_token(u.id, u.username)

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["code"] == 40101


def test_token_version_mismatch_rejected():
    """tv 对不上（改过密码 / 注销过）→ 旧票失效。"""
    u = _seed(token_version=5)
    # 签一个 tv 仍然为 4 的票，模拟「改密码后手里还攥着旧票」
    token = make_token(u.id, u.username, 4)

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["code"] == 40101


def test_inactive_status_rejected():
    """status 非 active（disabled）→ 拒绝，即便 tv 完全正确。"""
    u = _seed(status="disabled")
    token = make_token(u.id, u.username, u.token_version)

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["code"] == 40101


def test_valid_token_accepted():
    """正常票要能通过 —— 上面四条拒绝不能是靠「一律拒绝」蒙对的。"""
    u = _seed()
    token = make_token(u.id, u.username, u.token_version)

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["username"] == USERNAME


def test_logout_invalidates_old_token():
    """注销让 token_version +1，手里的票立刻失效。

    校验的是「+1 真的发生并写库」这个副作用，光看注销返回 200 不够。
    """
    u = _seed()
    token = make_token(u.id, u.username, u.token_version)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.post("/api/auth/logout", headers=headers).json()["code"] == 0

    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 401
    assert r.json()["code"] == 40101
