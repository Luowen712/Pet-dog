"""注销账号必须把设备解绑干净 —— 0008 的 CHECK 会拦住"只清 owner_id"的写法。

背景：
    0008 加的 ck_device_owner_status 要求「无主必非 bound」。
    auth.py 原来只把 owner_id 置空、status 留着 'bound'，
    这一句在真实 MySQL 上会立刻违反 CHECK 报 3819，整个注销事务回滚，
    用户点注销只会看到 500，账号永远删不掉。

为什么必须走 HTTP 而不是直接测 SQL：
    这段逻辑在路由里。直接测 SQL 等于把自己写的那句 UPDATE 复制一遍，
    以后代码改回旧写法、测试照样绿 —— 那就不叫回归测试了。
    只有真正打一次接口，才能保证"解绑语句 + 后续 commit"整体是对的。

一个容易踩的细节：
    DELETE 带 JSON body。httpx 的 client.delete() 不接受 json= 参数，
    必须用 client.request("DELETE", ...)，否则 body 发不出去、后端取不到密码。
"""

from datetime import datetime

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Device, User
from app.security import hash_pwd

DEVICE_ID = "PET-UNBIND-01"
USERNAME = "unbind_case"
PASSWORD = "pw-123456"



def _cleanup(db) -> None:
    """清掉本用例建的设备与账号，保证可重复执行。"""
    db.query(Device).filter(Device.device_id == DEVICE_ID).delete()
    db.query(User).filter(User.username == USERNAME).delete()
    db.query(User).filter(User.username.like("~del~%unbind_case%")).delete()
    db.commit()



def test_delete_account_unbinds_device_and_passes_check():
    """注销成功，且设备回到「无主 + claimable + required + bound_at 为空」。"""

    db = SessionLocal()
    try:
        _cleanup(db)

        user = User(
            username=USERNAME,
            password_hash=hash_pwd(PASSWORD),
            role="user",
            token_version=0,
            status="active",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        device = Device(
            device_id=DEVICE_ID,
            owner_id=user.id,
            be=1,
            status="bound",
            handover_state="ready",
            bound_at=datetime.now(),
        )
        db.add(device)
        db.commit()
        db.refresh(device)

        uid, did = user.id, device.id
    finally:
        db.close()

    client = TestClient(app)

    r = client.post(
        "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    token = r.json()["data"]["token"]

    r = client.request(
        "DELETE",
        "/api/auth/account",
        json={"password": PASSWORD, "confirm_username": USERNAME},
        headers={"Authorization": f"Bearer {token}"},
    )

    # 失败时把响应体打出来，否则只会看到一句 500，不知道是哪条约束
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "revoking"

    db = SessionLocal()
    try:
        d = db.query(Device).filter(Device.id == did).first()
        assert d is not None, "设备行不该因为注销被删除，只该解除归属"
        assert d.owner_id is None, "注销后设备必须无主"
        assert d.status == "claimable", "注销后设备必须回到可被认领状态"
        assert d.handover_state == "required"
        assert d.bound_at is None
        # 与 DELETE /devices/{id}/binding 同一口径（06:296 / S01）：注销解绑同步 be+1
        assert d.be == 2

        u = db.query(User).filter(User.id == uid).first()
        assert u.status == "revoking"
        assert u.deleted_at is not None
        assert u.username.startswith("~del~"), "用户名必须被改写成 ~del~ 前缀"

        _cleanup(db)
    finally:
        db.close()
