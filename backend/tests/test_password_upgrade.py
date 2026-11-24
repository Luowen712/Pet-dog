"""密码哈希升级：存量 SHA-256 必须在下次登录时自动换成 Argon2id。

背景：
    改造前 security.py 用的是 sha256("pet$" + 明文)——固定盐、无内存硬度、
    GPU 每秒能穷举几十亿次。换成 Argon2id 后，库里老账号的哈希仍是 64 位
    十六进制，如果不做升级，「旧格式校验」这条分支就永远拆不掉。

为什么只能在登录时升级：
    哈希不可逆，登录是唯一能拿到明文的时刻。错过这次，账号就永远停在旧格式。

为什么验证失败时绝不能写：
    写回的是「这次提交的密码」。验证没过还写，等于把错误密码当成新密码存进去，
    用户从此再也登不上——而且没有任何报错，只会看到「密码错误」。

为什么用真实 HTTP 而不是直接调 verify_pwd：
    升级逻辑落在 login 路由里（验证 → 判断 → 重算 → commit）。
    只测纯函数等于把那段流程复制一遍，代码改回旧写法测试照样绿。
"""

import hashlib

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import User
from app.security import needs_rehash, verify_pwd

USERNAME = "pwd_upgrade_case"
PASSWORD = "legacy-pw-123"
NEW_PREFIX = "$argon2id$"



def _legacy_hash(raw: str) -> str:
    """复刻旧的固定盐 SHA-256，用来伪造「历史遗留」账号。"""
    return hashlib.sha256(("pet$" + raw).encode("utf-8")).hexdigest()



def _cleanup(db) -> None:
    """清掉本用例创建的账号，含已改名的占位账号。"""
    db.query(User).filter(User.username.like("pwd_upgrade_%")).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.username.like("~del~%pwd_upgrade_%")).delete(
        synchronize_session=False
    )
    db.commit()



def _make_user(db, username: str, password: str, status: str = "active") -> int:
    """用旧版哈希造账号，返回主键。"""
    u = User(
        username=username,
        password_hash=_legacy_hash(password),
        role="user",
        token_version=0,
        status=status,
    )
    db.add(u)
    db.commit()
    return u.id



def _read_hash(uid: int) -> str:
    """读取账号当前的密码哈希。"""
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == uid).one().password_hash
    finally:
        db.close()



def test_legacy_hash_upgrades_on_successful_login():
    """旧摘要 + 正确密码 → 登录成功，且库里的哈希当场变成 Argon2id。"""

    db = SessionLocal()
    try:
        _cleanup(db)
        uid = _make_user(db, USERNAME, PASSWORD)
    finally:
        db.close()

    before = _read_hash(uid)
    assert len(before) == 64, "造出来的存量哈希应该是 64 位十六进制"
    assert not before.startswith(NEW_PREFIX)

    client = TestClient(app)
    r = client.post(
        "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["token"], "登录必须成功，否则老用户被锁在门外"

    after = _read_hash(uid)
    assert after.startswith(NEW_PREFIX), "登录成功后旧摘要必须已升级为 Argon2id"
    assert needs_rehash(after) is False, "升级过的哈希不该再被判为需要升级"

    # 关键回归点：升级后必须还能登录。哈希写错了这里会立刻红。
    r2 = client.post(
        "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["token"]

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()



def test_wrong_password_leaves_hash_untouched():
    """密码错 → 拒绝登录，且哈希一个字节都不能变。"""

    db = SessionLocal()
    try:
        _cleanup(db)
        uid = _make_user(db, USERNAME, PASSWORD)
    finally:
        db.close()

    before = _read_hash(uid)

    client = TestClient(app)
    r = client.post(
        "/api/auth/login", json={"username": USERNAME, "password": "not-the-password"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["code"] == 40001
    assert r.json()["data"] is None

    assert _read_hash(uid) == before, "验证失败时绝不能把提交的密码写回库里"

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()



def test_inactive_user_does_not_upgrade():
    """账号不可用时即使密码对，也不升级——升级条件是「验证通过且 active」。"""

    db = SessionLocal()
    try:
        _cleanup(db)
        uid = _make_user(db, USERNAME, PASSWORD, status="revoked")
    finally:
        db.close()

    before = _read_hash(uid)

    client = TestClient(app)
    r = client.post(
        "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
    )
    assert r.json()["code"] == 40001
    assert _read_hash(uid) == before

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()



def test_unknown_format_is_rejected_not_guessed():
    """认不出的哈希格式一律判 False —— 绝不回落到弱校验。"""

    assert verify_pwd("bogus-string", "anything") is False
    assert verify_pwd("", "anything") is False
    assert needs_rehash("bogus-string") is True
    assert needs_rehash("") is True



def test_register_password_length_boundary():
    """注册门槛与改密码统一为 10–128：9 位拒绝，10 位通过且存 Argon2id。"""

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()

    client = TestClient(app)

    r = client.post(
        "/api/auth/register",
        json={"username": "pwd_upgrade_short", "password": "123456789"},
    )
    assert r.json()["code"] == 40002, "9 位必须被拒"

    r = client.post(
        "/api/auth/register",
        json={"username": "pwd_upgrade_ok", "password": "1234567890"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["code"] == 0

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == "pwd_upgrade_ok").one()
        assert u.password_hash.startswith(NEW_PREFIX), "新注册必须直接写 Argon2id"
        _cleanup(db)
    finally:
        db.close()
