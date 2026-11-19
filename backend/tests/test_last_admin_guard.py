"""第 5 条：最后一个 active admin 禁止注销。

为什么需要这道闸门：
    注销接口会把 status 改成 revoking。如果系统里只剩一个管理员，
    他注销之后就没有任何 active admin 了 —— 没人能再进后台。

「再建一个」为什么救不了场：
    能写出 role='admin' 的地方全项目只有两处，都在命令行里：
        cli.py   create-admin       需要机器命令行 + 代码目录 + .env + Python
        seed.py  种子脚本           同上
    网页/API 那条路彻底没有：
        auth.py  register  不传 role，走模型默认 'user'
        setup.py /status   只返回一个布尔，不建账号
    所以恢复的前提是「你能进这台机器」。对只拿到一个网址和账号的人
    （运营、客服、外包），这就是死锁 —— 他没有任何比网页更深的权限。

    注意：这不是「技术上建不出来」，而是刻意不让管理员从网页上长出来。
    任何「最后一个 admin 被删时自动补一个」的机制，都会变成免身份的提权
    入口：密码写死则人人皆知，随机打印则日志泄露，通知原管理员则他已经
    注销了。所以宁可拦在注销这一步，也不留那条自动补号的路。
    同理，register 也绝不能接受 role 参数 —— 那等于把提权做成了公开接口。

为什么检查放在密码校验之后：
    如果先检查再验密码，未登录的攻击者也能通过「返回 40900 还是 40001」
    判断某个账号是不是最后一个管理员。身份没验过之前不该泄露任何结构信息。

为什么必须走 HTTP：
    这段逻辑在路由里，且状态判定依赖同一个事务里的 count(*)。
    直接测 SQL 等于把自己写的查询复制一遍，代码改坏了测试照样绿。
"""

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import User
from app.security import hash_pwd, make_token

PASSWORD = "guard-pw-4d21"
client = TestClient(app)


def _reset_admins():
    """清空测试库的管理员，保证「几个 admin」由本用例自己决定。"""
    db = SessionLocal()
    try:
        db.query(User).filter(User.role == "admin").delete()
        db.commit()
    finally:
        db.close()


def _mk_admin(username: str, status: str = "active") -> User:
    db = SessionLocal()
    try:
        u = User(
            username=username,
            password_hash=hash_pwd(PASSWORD),
            role="admin",
            status=status,
            token_version=0,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        db.expunge(u)
        return u
    finally:
        db.close()


def _delete(u: User) -> dict:
    token = make_token(u.id, u.username, u.token_version)
    r = client.request(
        "DELETE",
        "/api/auth/account",
        json={"password": PASSWORD, "confirm_username": u.username},
        headers={"Authorization": f"Bearer {token}"},
    )
    return {"http": r.status_code, "body": r.json()}


def test_sole_admin_cannot_delete_account():
    """唯一管理员注销必须被拒，且账号状态不变。"""
    _reset_admins()
    u = _mk_admin("guard_solo")

    res = _delete(u)
    assert res["body"]["code"] == 40900
    assert "管理员" in res["body"]["message"]

    db = SessionLocal()
    try:
        still = db.query(User).filter(User.id == u.id).first()
        assert still is not None
        assert still.status == "active", "被拒绝的注销居然改了状态"
    finally:
        db.close()


def test_admin_can_delete_when_another_admin_exists():
    """还有别的 active admin 时，注销应当放行 —— 上面那条不能是靠「一律拒绝」蒙对的。"""
    _reset_admins()
    u = _mk_admin("guard_first")
    _mk_admin("guard_second")

    res = _delete(u)
    assert res["body"]["code"] == 0

    db = SessionLocal()
    try:
        gone = db.query(User).filter(User.id == u.id).first()
        assert gone.status == "revoking"
    finally:
        db.close()


def test_disabled_admin_does_not_count_as_backup():
    """disabled 的管理员不算「还有管理员」—— 只剩一个 active 时仍必须拒绝。

    否则会出现「另一个 admin 只是被禁用，系统还以为有人能管」的假象。
    """
    _reset_admins()
    u = _mk_admin("guard_active_one")
    _mk_admin("guard_disabled_one", status="disabled")

    res = _delete(u)
    assert res["body"]["code"] == 40900
