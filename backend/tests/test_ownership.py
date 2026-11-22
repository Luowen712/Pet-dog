"""BB03 第 1 条：归属查询收口 + 遥测按绑定纪元隔离。"""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Device, Telemetry, User
from app.security import make_token
from app.services.ownership import (
    battery_of,
    get_owned_device,
    latest_telemetry,
    latest_telemetry_map,
)

client = TestClient(app)


def _mk_user(db, username: str) -> User:
    u = User(username=username, password_hash="x" * 64, role="user", status="active")
    db.add(u)
    db.commit()
    return u


def _mk_device(db, device_id: str, owner_id=None, be: int = 0) -> Device:
    # ck_device_owner_status：有主必 bound，无主必非 bound
    d = Device(
        device_id=device_id,
        owner_id=owner_id,
        be=be,
        status="bound" if owner_id else "claimable",
        handover_state="ready",
    )
    db.add(d)
    db.commit()
    return d


def test_battery_is_none_without_telemetry():
    db = SessionLocal()
    try:
        u = _mk_user(db, "own_notel")
        d = _mk_device(db, "DEV-NOTEL", owner_id=u.id)
        assert latest_telemetry(db, d) is None
        assert battery_of(latest_telemetry(db, d)) is None
    finally:
        db.close()


def test_latest_telemetry_ignores_old_binding_epoch():
    """上一代绑定的遥测不许被当成现主人的最新数据。"""
    db = SessionLocal()
    try:
        u = _mk_user(db, "own_be")
        d = _mk_device(db, "DEV-BE", owner_id=u.id, be=1)
        db.add(Telemetry(device_id="DEV-BE", device_pk=d.id, battery=88, be=0))
        db.add(Telemetry(device_id="DEV-BE", device_pk=d.id, battery=15, be=1))
        db.commit()

        t = latest_telemetry(db, d)
        assert t.be == 1, "取到了旧绑定纪元的遥测"
        assert battery_of(t) == 15
    finally:
        db.close()


def test_batch_map_matches_single_query():
    """批量结果必须和逐台查询完全一致。"""
    db = SessionLocal()
    try:
        u = _mk_user(db, "own_batch")
        d1 = _mk_device(db, "DEV-B1", owner_id=u.id, be=0)
        d2 = _mk_device(db, "DEV-B2", be=2)
        db.add(Telemetry(device_id="DEV-B1", device_pk=d1.id, battery=40, be=0))
        db.add(
            Telemetry(device_id="DEV-B2", device_pk=d2.id, battery=70, be=1)
        )  # 旧代，不许取
        db.add(Telemetry(device_id="DEV-B2", device_pk=d2.id, battery=60, be=2))
        db.commit()

        m = latest_telemetry_map(db, [d1, d2])
        assert battery_of(m[d1.id]) == 40
        assert battery_of(m[d2.id]) == 60
    finally:
        db.close()


def test_get_owned_device_rejects_other_owner():
    db = SessionLocal()
    try:
        a = _mk_user(db, "own_a")
        b = _mk_user(db, "own_b")
        d = _mk_device(db, "DEV-OWN", owner_id=a.id)

        assert get_owned_device(db, a.id, d.id) is not None
        assert get_owned_device(db, b.id, d.id) is None
    finally:
        db.close()


def _token_for(db, username: str) -> tuple[User, str]:
    u = _mk_user(db, username)
    return u, make_token(u.id, u.username, u.token_version)


# ---------------- BB03 第 5 条：解绑即撤权 ----------------
#
# 下面四个用例都走真实 HTTP，不用 client.delete()：旧版 httpx 的
# delete() 不接受 json 参数，用 request("DELETE", ...) 才能带请求体。


def _unbind(token: str, pk: int, confirm: int):
    return client.request(
        "DELETE",
        f"/api/devices/{pk}/binding",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirm_device_id": confirm},
    )


def test_unbind_clears_five_columns_and_bumps_epoch():
    """解绑必须一次改五列 + be+1，缺一列就违反 CHECK。"""
    db = SessionLocal()
    pk = None
    try:
        u, token = _token_for(db, "ub_ok")
        d = _mk_device(db, "UB-OK", owner_id=u.id, be=0)
        db.commit()
        pk = d.id

        r = _unbind(token, pk, pk)
        assert r.status_code == 200, "统一信封要求业务错误也走 HTTP 200"
        body = r.json()
        assert body["code"] == 0
        assert body["data"] == {"unbound": True, "handover_required": True}
    finally:
        db.close()

    # 换一个 Session 复查：同一连接在 REPEATABLE READ 下已经钉住快照，
    # 看不到别的会话刚提交的改动，刷新也没用（之前踩过）。
    db2 = SessionLocal()
    try:
        d = db2.query(Device).filter(Device.id == pk).first()
        assert d.owner_id is None, "owner 没清"
        assert d.status == "claimable", "status 没回落，CHECK 迟早报 3819"
        assert d.handover_state == "required", "交接门槛没设"
        assert d.bound_at is None, "绑定时间还留着上一任的"
        assert d.be == 1, "绑定纪元没 +1，新主人会读到上一任的遥测"
    finally:
        db2.close()


def test_unbind_confirm_mismatch_returns_40002():
    """confirm_device_id 与路径 id 不一致时拒绝，且不许改动任何数据。"""
    db = SessionLocal()
    pk = None
    try:
        u, token = _token_for(db, "ub_confirm")
        d = _mk_device(db, "UB-CONF", owner_id=u.id)
        db.commit()
        pk = d.id
        owner_before = u.id

        r = _unbind(token, pk, pk + 1)
        assert r.json()["code"] == 40002
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        d = db2.query(Device).filter(Device.id == pk).first()
        assert d.owner_id == owner_before, "参数校验失败却把设备解绑了"
        assert d.status == "bound"
    finally:
        db2.close()


def test_unbind_rejects_other_owner():
    """不是本人的设备一律 40400，不能因为错误码不同暴露设备存在性。"""
    db = SessionLocal()
    try:
        a, _ = _token_for(db, "ub_owner_a")
        _, token_b = _token_for(db, "ub_owner_b")
        d = _mk_device(db, "UB-OTHER", owner_id=a.id)

        r = _unbind(token_b, d.id, d.id)
        assert r.json()["code"] == 40400
    finally:
        db.close()


def test_unbind_twice_returns_40400_not_40900():
    """重复解绑落到 40400，而不是契约里写的 40900。

    原因：归属校验在前。第一次解绑后 owner_id 已经是 NULL，
    第二次调用时 get_owned_device 就返回 None，走不到「status != bound」
    那句 40900。同理，有 CHECK 保证「有主必 bound」，40900 分支当前不可达，
    是给未来的 retired 状态预留的防御，不是写错了。
    """
    db = SessionLocal()
    try:
        u, token = _token_for(db, "ub_twice")
        d = _mk_device(db, "UB-TWICE", owner_id=u.id)

        first = _unbind(token, d.id, d.id)
        assert first.json()["code"] == 0

        second = _unbind(token, d.id, d.id)
        assert second.json()["code"] == 40400
    finally:
        db.close()
