"""音乐状态的绑定纪元隔离。

`_music_state` 是进程内存字典，不落库。原先用 `device_id`（设备自报的字符串）
当 key，跨绑定纪元不变，于是设备换主人后新主人查状态会读到上一任的曲目与音量。
这和 latest_telemetry 缺 be 条件那处是同一类泄漏（台账 S01）。

改成 (device_pk, be) 之后，下面两条用例各守一半：
    1. be 变了 → 读不到旧状态
    2. device_id 变了 → 状态还在（说明 key 不是字符串编号）
"""

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Device, User
from app.routers import devices as devices_router
from app.routers.devices import DEFAULT_VOLUME
from app.security import make_token

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_music_state():
    """清掉上个用例留在模块字典里的状态，否则用例之间互相污染。"""
    devices_router._music_state.clear()
    yield
    devices_router._music_state.clear()


def _mk_user(db, username: str) -> User:
    u = User(
        username=username,
        password_hash="x" * 64,
        role="user",
        status="active",
        token_version=0,
    )
    db.add(u)
    db.commit()
    return u


def _mk_device(db, device_id: str, owner_id: int, be: int = 0) -> Device:
    d = Device(
        device_id=device_id,
        owner_id=owner_id,
        be=be,
        status="bound",
        handover_state="ready",
    )
    db.add(d)
    db.commit()
    return d


def _headers(u: User) -> dict:
    return {"Authorization": "Bearer " + make_token(u.id, u.username, u.token_version)}


def test_music_state_not_visible_after_binding_epoch_changes():
    """设备换主人（be+1）后，新纪元看不到上一任的音量。"""
    db = SessionLocal()
    try:
        u = _mk_user(db, "mus_epoch")
        d = _mk_device(db, "MUS-EPOCH", owner_id=u.id, be=0)
        h = _headers(u)

        r = client.post(
            f"/api/devices/{d.id}/music", json={"command": 5, "value": 25}, headers=h
        )
        assert r.status_code == 200
        assert r.json()["data"]["volume"] == 25

        d.be = 1
        db.commit()

        r = client.get(f"/api/devices/{d.id}/status", headers=h)
        assert r.json()["data"]["volume"] == DEFAULT_VOLUME, "新绑定纪元读到了上一任的音量"
    finally:
        db.close()


def test_music_state_keyed_by_pk_not_device_id():
    """设备编号变了也不能丢状态——说明 key 是主键而不是字符串编号。"""
    db = SessionLocal()
    try:
        u = _mk_user(db, "mus_rename")
        d = _mk_device(db, "MUS-OLD", owner_id=u.id, be=0)
        h = _headers(u)

        client.post(
            f"/api/devices/{d.id}/music", json={"command": 5, "value": 20}, headers=h
        )

        d.device_id = "MUS-NEW"
        db.commit()

        r = client.get(f"/api/devices/{d.id}/status", headers=h)
        assert r.json()["data"]["volume"] == 20, "改设备编号后状态丢了，说明 key 用了 device_id"
    finally:
        db.close()
