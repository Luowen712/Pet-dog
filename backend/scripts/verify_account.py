"""注销账号接口的验收脚本。

用途：一条命令跑完全部场景，自动注册临时账号、自动造设备归属、自动还原。
跑法（在 backend 目录下）：
    .venv\\Scripts\\python.exe scripts\\verify_account.py

前提：后端已在 8000 端口运行。
注意：只会用临时账号（t开头、s开头），不碰 admin / zhoujiaxin / mzx。
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8000"
ok_count = 0
fail_count = 0


def call(method, path, body=None, token=None):
    """发一个请求，返回 (HTTP 状态码, 解析后的响应体)。"""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def check(name, condition, detail=""):
    """打印一条 PASS / FAIL。"""
    global ok_count, fail_count
    if condition:
        ok_count += 1
        print("  [PASS] %s" % name)
    else:
        fail_count += 1
        print("  [FAIL] %s   %s" % (name, detail))


def make_user(tag):
    """注册并登录一个临时账号，返回 (用户名, 密码, token)。"""
    un = "%s%d" % (tag, int(time.time() * 1000) % 1000000)
    pw = "pw" + un + "xyz"
    call("POST", "/api/auth/register", {"username": un, "password": pw})
    _, b = call("POST", "/api/auth/login", {"username": un, "password": pw})
    return un, pw, b["data"]["token"]


def device_snapshot():
    """当前每台设备的归属，形如 [(1, 1), (2, 1)]。"""
    from app.db import SessionLocal
    from app.models import Device

    s = SessionLocal()
    try:
        return [(d.id, d.owner_id) for d in s.query(Device).all()]
    finally:
        s.close()


def user_state(uid):
    """某个账号的 (status, token_version)。"""
    from app.db import SessionLocal
    from app.models import User

    s = SessionLocal()
    try:
        u = s.query(User).filter(User.id == uid).first()
        return (u.status, u.token_version) if u else (None, None)
    finally:
        s.close()


def give_device(un, uid):
    """把第一台设备划给指定用户，返回设备 id。"""
    from app.db import SessionLocal
    from app.models import Device

    s = SessionLocal()
    try:
        d = s.query(Device).order_by(Device.id).first()
        d.owner_id = uid
        s.commit()
        return d.id
    finally:
        s.close()


def restore_devices(before):
    """把设备归属还原成测试前的样子。"""
    from app.db import SessionLocal
    from app.models import Device

    s = SessionLocal()
    try:
        for did, oid in before:
            d = s.query(Device).filter(Device.id == did).first()
            if d:
                d.owner_id = oid
        s.commit()
    finally:
        s.close()


def main():
    print("=" * 60)
    print("注销账号接口验收")
    print("=" * 60)

    before = device_snapshot()
    print("\n测试前设备归属: %s" % before)

    un, pw, tok = make_user("t")
    from app.db import SessionLocal
    from app.models import User

    s = SessionLocal()
    try:
        uid = s.query(User).filter(User.username == un).first().id
    finally:
        s.close()
    did = give_device(un, uid)
    print("临时账号: %s (uid=%d)，设备 %d 已划给它\n" % (un, uid, did))

    print("--- 失败分支（都不应该动数据）---")
    cases = [
        ("密码填错", {"password": "wrongpwd000", "confirm_username": un}, 40001),
        ("用户名填错", {"password": pw, "confirm_username": "wrongname"}, 40002),
        ("用户名传空", {"password": pw, "confirm_username": ""}, 40002),
        ("用户名带多余词", {"password": pw, "confirm_username": un + " 多余"}, 40002),
        ("用户名只差一个字符", {"password": pw, "confirm_username": un[:-1]}, 40002),
    ]
    for name, body, expect in cases:
        _, b = call("DELETE", "/api/auth/account", body, tok)
        check(
            "%-14s 应返回 %d" % (name, expect),
            b.get("code") == expect,
            "实际 code=%s message=%s" % (b.get("code"), b.get("message")),
        )

    st, tv = user_state(uid)
    check("五轮失败后账号未被改动", st == "active" and tv == 0, "实际 status=%s tv=%s" % (st, tv))

    print("\n--- 用户名前后带空格（应容忍并注销）---")
    un2, pw2, tok2 = make_user("s")
    _, b = call(
        "DELETE", "/api/auth/account",
        {"password": pw2, "confirm_username": "  " + un2 + "  "}, tok2,
    )
    check(
        "带空格也能通过",
        (b.get("data") or {}).get("status") == "revoking",
        "实际 code=%s data=%s" % (b.get("code"), b.get("data")),
    )

    print("\n--- 正常注销 ---")
    _, b = call("DELETE", "/api/auth/account", {"password": pw, "confirm_username": un}, tok)
    check(
        "返回 {status: revoking}",
        (b.get("data") or {}).get("status") == "revoking",
        "实际 code=%s data=%s" % (b.get("code"), b.get("data")),
    )
    check("响应字段名是 status 而不是 deleted", "status" in (b.get("data") or {}),
          "实际 data=%s" % b.get("data"))

    print("\n--- 注销后的连带效果 ---")
    after = device_snapshot()
    dev = dict(after).get(did)
    check("设备已解绑（owner_id 变 None）", dev is None, "实际 owner_id=%s" % dev)

    st, tv = user_state(uid)
    check("status 变成 revoking", st == "revoking", "实际 status=%s" % st)
    check("token_version 加了 1", tv == 1, "实际 tv=%s" % tv)

    st_code, b = call("POST", "/api/auth/login", {"username": un, "password": pw})
    check("原密码登不进去", b.get("code") == 40001, "实际 code=%s" % b.get("code"))

    st_code, b = call("GET", "/api/auth/me", token=tok)
    check("注销前的旧票失效", st_code == 401, "实际 HTTP %s code=%s" % (st_code, b.get("code")))

    print("\n--- 还原设备归属 ---")
    restore_devices(before)
    print("  已恢复: %s" % device_snapshot())

    print("\n" + "=" * 60)
    print("结果: PASS %d / FAIL %d" % (ok_count, fail_count))
    print("=" * 60)
    if fail_count:
        print("\n测试账号留在库里了：%s / %s（status 都是 revoking）" % (un, un2))
        print("清理: DELETE FROM user WHERE username REGEXP '^[ts][0-9]+$';")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
