"""BB03 第 1 条：归属查询收口 + 遥测按绑定纪元隔离。"""

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


def test_claimable_lists_ready_unowned_device():
    db = SessionLocal()
    try:
        _, token = _token_for(db, "cl_ready")
        d = _mk_device(db, "CL-READY", be=0)  # 无主 + claimable + ready
        r = client.get(
            "/api/devices/claimable", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200
        ids = {x["id"] for x in r.json()["data"]}
        assert d.id in ids
        # 字段只有 id 和 name，别把 owner 带出来
        assert set(r.json()["data"][0].keys()) <= {"id", "name"}
    finally:
        db.close()


def test_claimable_excludes_handover_required():
    db = SessionLocal()
    try:
        _, token = _token_for(db, "cl_req")
        d = _mk_device(db, "CL-REQ", be=0)
        d.handover_state = "required"
        db.commit()
        r = client.get(
            "/api/devices/claimable", headers={"Authorization": f"Bearer {token}"}
        )
        ids = {x["id"] for x in r.json()["data"]}
        assert d.id not in ids
    finally:
        db.close()


def test_claimable_excludes_bound_device():
    db = SessionLocal()
    try:
        u, token = _token_for(db, "cl_bound")
        d = _mk_device(db, "CL-BOUND", owner_id=u.id)  # status=bound
        r = client.get(
            "/api/devices/claimable", headers={"Authorization": f"Bearer {token}"}
        )
        ids = {x["id"] for x in r.json()["data"]}
        assert d.id not in ids
    finally:
        db.close()
