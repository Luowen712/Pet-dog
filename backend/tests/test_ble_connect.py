"""低功耗蓝牙（ECB02H2 BLE）透传端口、扫描与无配对码直连绑定测试。"""

import time
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from serial import SerialException, SerialTimeoutException

from app.config import settings
from app.db import SessionLocal
from app.link.ble_link import (
    DEFAULT_NOTIFY_UUID,
    DEFAULT_SERVICE_UUID,
    DEFAULT_WRITE_UUID,
    SIM_BLE_ADDRESS,
    BleBytePort,
    resolve_gatt_chars,
    scan_ble_devices,
)
from app.main import app
from app.models import Device, User
from app.security import make_token


class _FakeChar:
    def __init__(self, uuid_str: str, properties: list[str]):
        self.uuid = uuid_str
        self.properties = properties


class _FakeService:
    def __init__(self, uuid_str: str, chars: list[_FakeChar]):
        self.uuid = uuid_str
        self.characteristics = chars


class _FakeBleakClient:
    def __init__(
        self,
        address: str,
        *,
        disconnected_callback=None,
        timeout: float = 8.0,
        services=None,
        fail_on_write_call: int | None = None,
    ):
        self.address = address
        self._disc_cb = disconnected_callback
        self.services = services or [
            _FakeService(
                DEFAULT_SERVICE_UUID,
                [
                    _FakeChar(DEFAULT_NOTIFY_UUID, ["notify"]),
                    _FakeChar(DEFAULT_WRITE_UUID, ["write-without-response"]),
                ],
            )
        ]
        self.is_connected = False
        self.notify_cb = None
        self.written: list[tuple[str, bytes, bool]] = []
        self._fail_on_write_call = fail_on_write_call

    async def connect(self):
        self.is_connected = True

    async def start_notify(self, uuid_str: str, cb):
        self.notify_cb = cb

    async def stop_notify(self, uuid_str: str):
        self.notify_cb = None

    async def write_gatt_char(self, uuid_str: str, data: bytes, response: bool = False):
        idx = len(self.written) + 1
        if self._fail_on_write_call == idx:
            raise OSError("gatt write error")
        self.written.append((uuid_str, bytes(data), response))

    async def disconnect(self):
        self.is_connected = False

    def push_notify(self, data: bytes):
        assert self.notify_cb is not None
        self.notify_cb(None, bytearray(data))

    def trigger_disconnect(self):
        self.is_connected = False
        if self._disc_cb is not None:
            self._disc_cb(self)


def _mk_user(db, prefix: str = "ble") -> tuple[User, dict]:
    u = User(
        username=f"{prefix}_{uuid.uuid4().hex[:10]}",
        password_hash="x" * 64,
        role="user",
        status="active",
        token_version=0,
    )
    db.add(u)
    db.commit()
    return u, {"Authorization": "Bearer " + make_token(u.id, u.username, 0)}


def test_resolve_gatt_chars_supports_fff0_and_ffe0_fallback():
    fff_services = [
        _FakeService(
            "0000fff0-0000-1000-8000-00805f9b34fb",
            [
                _FakeChar("0000fff1-0000-1000-8000-00805f9b34fb", ["notify"]),
                _FakeChar("0000fff2-0000-1000-8000-00805f9b34fb", ["write-without-response"]),
            ],
        )
    ]
    n_uuid, w_uuid, use_resp = resolve_gatt_chars(fff_services, "fff0", "fff1", "fff2")
    assert n_uuid.endswith("fff1-0000-1000-8000-00805f9b34fb")
    assert w_uuid.endswith("fff2-0000-1000-8000-00805f9b34fb")
    assert use_resp is False

    # 部分 ECB02H2 批次使用单特征 FFE1（同时支持 notify + write）
    ffe_services = [
        _FakeService(
            "0000ffe0-0000-1000-8000-00805f9b34fb",
            [_FakeChar("0000ffe1-0000-1000-8000-00805f9b34fb", ["notify", "write"])],
        )
    ]
    n2, w2, use_resp2 = resolve_gatt_chars(ffe_services, "fff0", "fff1", "fff2")
    assert n2 == w2 and n2.endswith("ffe1-0000-1000-8000-00805f9b34fb")
    assert use_resp2 is True


def test_ble_byte_port_chunks_writes_buffers_notify_and_tracks_partial_write():
    holder: dict[str, _FakeBleakClient] = {}

    def make_client(addr, **kw):
        c = _FakeBleakClient(addr, **kw)
        holder["c"] = c
        return c

    port = BleBytePort("AA:BB:CC:DD:EE:01", mtu_chunk=20, client_factory=make_client)
    try:
        assert port.is_open is True
        payload = bytes(range(36))  # 协议最大帧长 36B，按 20B 切成 20 + 16
        assert port.write(payload) == 36
        assert [len(chunk) for _, chunk, _ in holder["c"].written] == [20, 16]
        assert b"".join(chunk for _, chunk, _ in holder["c"].written) == payload

        holder["c"].push_notify(b"\xAA\x55\x00\x84\x7B")
        assert port.read(2) == b"\xAA\x55"
        assert port.read(16) == b"\x00\x84\x7B"
        assert port.read(16) == b""

        holder["c"].trigger_disconnect()
        assert port.is_open is False
        with pytest.raises(SerialException):
            port.read(1)
    finally:
        port.close()

    # 第 1 片失败 → SerialException（确定未写）；第 2 片失败 → SerialTimeoutException（可能部分写）
    p_first = BleBytePort(
        "AA:BB:CC:DD:EE:02",
        mtu_chunk=20,
        client_factory=lambda a, **kw: _FakeBleakClient(a, fail_on_write_call=1, **kw),
    )
    try:
        with pytest.raises(SerialException) as ei:
            p_first.write(b"x" * 30)
        assert not isinstance(ei.value, SerialTimeoutException)
    finally:
        p_first.close()

    p_second = BleBytePort(
        "AA:BB:CC:DD:EE:03",
        mtu_chunk=20,
        client_factory=lambda a, **kw: _FakeBleakClient(a, fail_on_write_call=2, **kw),
    )
    try:
        with pytest.raises(SerialTimeoutException):
            p_second.write(b"x" * 30)
    finally:
        p_second.close()


def test_scan_ble_devices_prioritizes_ecb02_and_rssi():
    import asyncio

    async def fake_discover(**_kw):
        return {
            "other": (
                SimpleNamespace(address="11:22:33:44:55:01", name="RandomSpeaker"),
                SimpleNamespace(rssi=-40, service_uuids=[]),
            ),
            "ecb": (
                SimpleNamespace(address="11:22:33:44:55:02", name="ECB02H2-Pet"),
                SimpleNamespace(rssi=-65, service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"]),
            ),
        }

    found = asyncio.run(scan_ble_devices(discover_fn=fake_discover))
    assert [d.address for d in found] == ["11:22:33:44:55:02", "11:22:33:44:55:01"]


def test_ble_scan_direct_connect_bind_and_account_isolation(monkeypatch, tmp_path):
    with SessionLocal() as db:
        u1, h1 = _mk_user(db, "ble_u1")
        u2, h2 = _mk_user(db, "ble_u2")
        u1_id, u2_id = u1.id, u2.id

    monkeypatch.setattr(settings, "SERIAL_PORT", "sim")
    monkeypatch.setattr(settings, "SERIAL_DEVICE_PK", None)
    for k, v in dict(
        host_lock_path=tmp_path / "ble-sim.lock",
        heartbeat_interval_sec=0.05,
        timeout_check_interval_sec=0.05,
    ).items():
        monkeypatch.setattr(app.state, k, v, raising=False)

    with TestClient(app) as client:
        # 旧配对码接口已移除（被 /api/devices/{id} 路由表拒为 404/405）
        assert client.post("/api/devices/claim", json={"device_id": 1, "code": "123456"}, headers=h1).status_code in (404, 405)

        # 扫描返回 SIM ECB02H2 候选，无需配对码
        scan1 = client.get("/api/devices/ble/scan", headers=h1).json()
        assert scan1["code"] == 0
        assert any(item["address"] == SIM_BLE_ADDRESS and not item["bound_to_me"] for item in scan1["data"])

        # 直接点击连接并绑定到账号 A
        conn1 = client.post(
            "/api/devices/ble/connect",
            json={"address": SIM_BLE_ADDRESS, "name": "我的ECB02桌宠"},
            headers=h1,
        ).json()
        assert conn1["code"] == 0
        dev_pk = conn1["data"]["id"]
        assert conn1["data"]["binding_state"] == "bound"

        # 等待 SIM 链路就绪，可直控
        for _ in range(100):
            st = client.get(f"/api/devices/{dev_pk}/status", headers=h1).json()["data"]
            if st["control_state"] == "ready":
                break
            time.sleep(0.02)
        assert st["online"] is True and st["control_state"] == "ready"

        # 账号 B 扫描不到已被 A 绑定的设备，直接抢连返回 40900
        scan2 = client.get("/api/devices/ble/scan", headers=h2).json()["data"]
        assert all(item["address"] != SIM_BLE_ADDRESS for item in scan2)
        steal = client.post(
            "/api/devices/ble/connect",
            json={"address": SIM_BLE_ADDRESS},
            headers=h2,
        ).json()
        assert steal["code"] == 40900

        # 账号 A 已绑定一台时，禁止再绑定第二台
        second = client.post(
            "/api/devices/ble/connect",
            json={"address": "AA:BB:CC:DD:EE:99", "name": "第二台"},
            headers=h1,
        ).json()
        assert second["code"] == 40900

        # A 解绑后，B 可扫描并直接蓝牙连接接管（且 be 递增）
        ub = client.request(
            "DELETE",
            f"/api/devices/{dev_pk}/binding",
            json={"confirm_device_id": dev_pk},
            headers=h1,
        ).json()
        assert ub["code"] == 0 and ub["data"]["unbound"] is True

        scan2_after = client.get("/api/devices/ble/scan", headers=h2).json()["data"]
        assert any(item["address"] == SIM_BLE_ADDRESS for item in scan2_after)

        conn2 = client.post(
            "/api/devices/ble/connect",
            json={"address": SIM_BLE_ADDRESS},
            headers=h2,
        ).json()
        assert conn2["code"] == 0 and conn2["data"]["id"] == dev_pk

        with SessionLocal() as db:
            row = db.get(Device, dev_pk)
            assert row is not None and row.owner_id == u2_id and row.be == 2
            assert u1_id != u2_id


def test_ble_mode_health_and_failed_connect_does_not_dirty_db(monkeypatch, tmp_path):
    with SessionLocal() as db:
        _, h = _mk_user(db, "ble_fail")

    monkeypatch.setattr(settings, "SERIAL_PORT", "ble")
    monkeypatch.setattr(settings, "SERIAL_DEVICE_PK", None)
    for k, v in dict(
        host_lock_path=tmp_path / "ble-real.lock",
        ble_port_override=lambda _addr: (_ for _ in ()).throw(SerialException("device not found")),
    ).items():
        monkeypatch.setattr(app.state, k, v, raising=False)

    with TestClient(app) as client:
        assert client.get("/api/health").json()["data"]["mode"] == "ble"
        bad_addr = f"FF:EE:{uuid.uuid4().hex[:2].upper()}:00:11:22"
        res = client.post(
            "/api/devices/ble/connect",
            json={"address": bad_addr, "name": "ECB02H2-Fail"},
            headers=h,
        ).json()
        assert res["code"] == 40900

    with SessionLocal() as db:
        assert db.query(Device).filter_by(device_id=bad_addr).first() is None


def test_account_delete_disconnects_active_ble_port(monkeypatch, tmp_path):
    from app.security import hash_pwd

    pw = "ble-delete-pw-1234"
    uname = f"ble_del_{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        u = User(username=uname, password_hash=hash_pwd(pw), role="user", status="active", token_version=0)
        db.add(u)
        db.commit()
        h = {"Authorization": "Bearer " + make_token(u.id, u.username, 0)}

    created_ports: list[BleBytePort] = []

    def make_ble_port(addr: str) -> BleBytePort:
        p = BleBytePort(addr, client_factory=lambda a, **kw: _FakeBleakClient(a, **kw))
        created_ports.append(p)
        return p

    monkeypatch.setattr(settings, "SERIAL_PORT", "ble")
    monkeypatch.setattr(settings, "SERIAL_DEVICE_PK", None)
    for k, v in dict(
        host_lock_path=tmp_path / "ble-del.lock",
        ble_port_override=make_ble_port,
    ).items():
        monkeypatch.setattr(app.state, k, v, raising=False)

    addr = f"AA:BB:{uuid.uuid4().hex[:2].upper()}:11:22:33"
    with TestClient(app) as client:
        c = client.post("/api/devices/ble/connect", json={"address": addr, "name": "ECB02H2-Del"}, headers=h).json()
        assert c["code"] == 0
        assert app.state.device_session is not None and created_ports[0].is_open is True

        res = client.request(
            "DELETE",
            "/api/auth/account",
            json={"password": pw, "confirm_username": uname},
            headers=h,
        ).json()
        assert res["code"] == 0 and res["data"]["status"] == "revoking"
        assert app.state.device_session is None
        assert created_ports[0].is_open is False


def test_offline_ble_reconnect_closes_old_port_before_reopening(monkeypatch, tmp_path):
    with SessionLocal() as db:
        _, h = _mk_user(db, "ble_reconn")

    created_ports: list[BleBytePort] = []
    old_open_when_reopening: list[bool] = []

    def make_ble_port(addr: str) -> BleBytePort:
        if created_ports:
            # 单连接外设 ECB02H2 重连前必须先释放旧句柄
            old_open_when_reopening.append(created_ports[-1].is_open)
        p = BleBytePort(addr, client_factory=lambda a, **kw: _FakeBleakClient(a, **kw))
        created_ports.append(p)
        return p

    monkeypatch.setattr(settings, "SERIAL_PORT", "ble")
    monkeypatch.setattr(settings, "SERIAL_DEVICE_PK", None)
    for k, v in dict(
        host_lock_path=tmp_path / "ble-reconn.lock",
        ble_port_override=make_ble_port,
    ).items():
        monkeypatch.setattr(app.state, k, v, raising=False)

    addr = f"AA:CC:{uuid.uuid4().hex[:2].upper()}:11:22:33"
    with TestClient(app) as client:
        r1 = client.post("/api/devices/ble/connect", json={"address": addr, "name": "ECB-Reconn"}, headers=h).json()
        assert r1["code"] == 0
        first_session = app.state.device_session
        assert first_session is not None and first_session.control_state == "offline"
        assert created_ports[0].is_open is True

        # 离线状态下点“重连蓝牙”不得静默复用旧会话，必须先关旧端口再建新会话
        r2 = client.post("/api/devices/ble/connect", json={"address": addr, "name": "ECB-Reconn"}, headers=h).json()
        assert r2["code"] == 0
        assert len(created_ports) == 2
        assert old_open_when_reopening == [False]
        assert created_ports[0].is_open is False
        assert created_ports[1].is_open is True
        assert app.state.device_session is not first_session


def test_ble_connect_rejects_hijacking_other_users_active_session_and_closes_on_bind_error(monkeypatch, tmp_path):
    from app.services import ble as ble_service

    with SessionLocal() as db:
        _, h1 = _mk_user(db, "ble_own")
        _, h2 = _mk_user(db, "ble_intruder")

    created_ports: list[BleBytePort] = []

    def make_ble_port(addr: str) -> BleBytePort:
        p = BleBytePort(addr, client_factory=lambda a, **kw: _FakeBleakClient(a, **kw))
        created_ports.append(p)
        return p

    monkeypatch.setattr(settings, "SERIAL_PORT", "ble")
    monkeypatch.setattr(settings, "SERIAL_DEVICE_PK", None)
    for k, v in dict(
        host_lock_path=tmp_path / "ble-guard.lock",
        ble_port_override=make_ble_port,
    ).items():
        monkeypatch.setattr(app.state, k, v, raising=False)

    addr1 = f"BB:01:{uuid.uuid4().hex[:2].upper()}:11:22:33"
    addr2 = f"BB:02:{uuid.uuid4().hex[:2].upper()}:44:55:66"
    with TestClient(app, raise_server_exceptions=False) as client:
        r1 = client.post("/api/devices/ble/connect", json={"address": addr1, "name": "Pet-A"}, headers=h1).json()
        assert r1["code"] == 0
        sess_a = app.state.device_session
        assert sess_a is not None and len(created_ports) == 1

        # 账号 B 尝试连接另一台 BLE 设备，不得踢掉账号 A 的活跃会话，且不落库
        r2 = client.post("/api/devices/ble/connect", json={"address": addr2, "name": "Pet-B"}, headers=h2).json()
        assert r2["code"] == 40900
        assert app.state.device_session is sess_a
        assert created_ports[0].is_open is True
        assert len(created_ports) == 1

        # A 解绑后，若 _bind 阶段抛出未预期异常，新打开的 BLE 端口必须被关闭不泄漏
        dev_pk = r1["data"]["id"]
        ub = client.request(
            "DELETE",
            f"/api/devices/{dev_pk}/binding",
            json={"confirm_device_id": dev_pk},
            headers=h1,
        ).json()
        assert ub["code"] == 0 and app.state.device_session is None

        monkeypatch.setattr(
            ble_service,
            "bind_ble_device",
            lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("injected db error")),
        )
        r3 = client.post("/api/devices/ble/connect", json={"address": addr2, "name": "Pet-B"}, headers=h2)
        assert r3.status_code == 500
        assert len(created_ports) == 2
        assert created_ports[1].is_open is False

    with SessionLocal() as db:
        assert db.query(Device).filter_by(device_id=addr2).first() is None


def test_ble_connect_timeout_releases_backend_handles_and_stops_thread():
    import asyncio

    closed_handles: list[str] = []

    class _FakeWinRTHandle:
        def __init__(self, label: str):
            self.label = label

        def close(self):
            closed_handles.append(self.label)

    class _HangingClient(_FakeBleakClient):
        def __init__(self, address: str, **kw):
            super().__init__(address, **kw)
            self.disconnect_calls = 0
            self._backend = SimpleNamespace(
                _session=_FakeWinRTHandle("session"),
                _requester=_FakeWinRTHandle("requester"),
            )

        async def connect(self):
            await asyncio.sleep(5.0)

        async def disconnect(self):
            self.disconnect_calls += 1

    holder: dict[str, _HangingClient] = {}

    def make_client(addr, **kw):
        c = _HangingClient(addr, **kw)
        holder["c"] = c
        return c

    with pytest.raises(SerialTimeoutException, match="BLE 建连超时"):
        BleBytePort(
            "AA:BB:CC:DD:EE:88",
            connect_timeout=0.15,
            client_factory=make_client,
        )

    assert holder["c"].disconnect_calls >= 1
    assert set(closed_handles) == {"session", "requester"}


def test_serial_link_closes_ble_port_thread_after_remote_disconnect():
    from app.link.serial_link import SerialLink

    holder: dict[str, _FakeBleakClient] = {}

    class _CountingClient(_FakeBleakClient):
        def __init__(self, address: str, **kw):
            super().__init__(address, **kw)
            self.disconnect_calls = 0

        async def disconnect(self):
            self.disconnect_calls += 1
            self.is_connected = False

    def make_client(addr, **kw):
        c = _CountingClient(addr, **kw)
        holder["c"] = c
        return c

    port = BleBytePort("AA:BB:CC:DD:EE:77", client_factory=make_client)
    link = SerialLink(port, poll_interval=0.005)
    link.start()
    try:
        # 远端断开使 port.is_open 立即变 False，SerialLink 仍必须调 port.close() 释放线程与底层句柄
        holder["c"].trigger_disconnect()
        for _ in range(100):
            if link.faulted and not port._thread.is_alive():
                break
            time.sleep(0.02)
        assert link.faulted is True
        assert port._thread.is_alive() is False
        assert holder["c"].disconnect_calls >= 1
    finally:
        link.close()


def test_heartbeat_ack_emits_link_event_when_device_comes_online(tmp_path):
    from app.link.device_session import DeviceSession
    from app.link.frame import build
    from app.link.serial_link import SerialLink
    from app.link.simulator import CMD_HEARTBEAT_ACK

    with SessionLocal() as db:
        u, _ = _mk_user(db, "hb")
        dev = Device(
            device_id=f"HB-{uuid.uuid4().hex[:8]}",
            name="HB-Test",
            owner_id=u.id,
            status="bound",
            handover_state="ready",
            be=1,
        )
        db.add(dev)
        db.commit()
        dev_pk = dev.id

    holder: dict[str, _FakeBleakClient] = {}

    def make_client(addr, **kw):
        c = _FakeBleakClient(addr, **kw)
        holder["c"] = c
        return c

    events = []
    port = BleBytePort("AA:BB:CC:DD:EE:66", client_factory=make_client)
    link = SerialLink(port, poll_interval=0.005)
    session = DeviceSession(
        dev_pk,
        SessionLocal,
        link,
        auto_prepare_sim=True,
        on_event=events.append,
    )
    session.start()
    try:
        assert session.online is False
        holder["c"].push_notify(build(CMD_HEARTBEAT_ACK))
        for _ in range(100):
            if any(ev.kind == "link" and ev.payload.get("online") is True for ev in events):
                break
            time.sleep(0.02)
        link_events = [ev for ev in events if ev.kind == "link"]
        assert len(link_events) == 1
        assert link_events[0].payload["online"] is True

        # 已在线时再次收到 0x84 不重复推送冗余 link 事件
        holder["c"].push_notify(build(CMD_HEARTBEAT_ACK))
        time.sleep(0.05)
        assert len([ev for ev in events if ev.kind == "link"]) == 1
    finally:
        session.close()


def test_ble_bench_mode_unlocks_all_actions_and_faces(monkeypatch, tmp_path):
    with SessionLocal() as db:
        _, h = _mk_user(db, "ble_bench")

    holder: dict[str, _FakeBleakClient] = {}

    def make_ble_port(addr: str) -> BleBytePort:
        def make_client(a, **kw):
            c = _FakeBleakClient(a, **kw)
            holder["c"] = c
            return c

        return BleBytePort(addr, client_factory=make_client)

    monkeypatch.setattr(settings, "SERIAL_PORT", "ble")
    monkeypatch.setattr(settings, "SERIAL_DEVICE_PK", None)
    monkeypatch.setattr(settings, "DEV_BENCH_CONTROL", True)
    for k, v in dict(
        host_lock_path=tmp_path / "ble-bench.lock",
        db_lock_name=f"petdog:test:bench:{uuid.uuid4().hex[:8]}",
        ble_port_override=make_ble_port,
        heartbeat_interval_sec=60.0,
        timeout_check_interval_sec=0.05,
    ).items():
        monkeypatch.setattr(app.state, k, v, raising=False)

    addr = f"BC:01:{uuid.uuid4().hex[:2].upper()}:11:22:33"
    with TestClient(app) as client:
        conn = client.post(
            "/api/devices/ble/connect",
            json={"address": addr, "name": "BenchDog"},
            headers=h,
        ).json()
        assert conn["code"] == 0
        dev_pk = conn["data"]["id"]
        assert conn["data"]["online"] is True
        assert conn["data"]["control_state"] == "ready"
        assert len(conn["data"]["supported_actions"]) == 19
        assert 0x43 in conn["data"]["supported_actions"]

        # GET /api/faces 返回与固件 DebugUI.c 对齐的 0..6 表情表
        faces_resp = client.get("/api/faces", headers=h).json()
        assert faces_resp["code"] == 0
        assert [(f["id"], f["name"]) for f in faces_resp["data"]] == [
            (0, "睡觉"),
            (1, "委屈"),
            (2, "开心"),
            (3, "狂热"),
            (4, "超开心"),
            (5, "眼睛"),
            (6, "震惊"),
        ]

        # 无需下位机先回 0x03/0x84，直接能下发动作（如 0x43 打招呼）和表情
        r_face = client.post(
            "/api/faces/current",
            json={"device_id": dev_pk, "face": 1},
            headers=h,
        ).json()
        assert r_face["code"] == 0 and r_face["data"]["dispatched"] is True

        r_cmd1 = client.post(
            "/api/commands/send",
            json={"device_id": dev_pk, "action": 0x43},
            headers={**h, "Idempotency-Key": str(uuid.uuid4())},
        ).json()
        assert r_cmd1["code"] == 0 and r_cmd1["data"]["status"] == "pending"

        # 即使下位机未回 0x81，600ms 超时后释放槽回到 ready，可继续连测下一条动作
        for _ in range(50):
            st = client.get(f"/api/devices/{dev_pk}/status", headers=h).json()["data"]
            if st["control_state"] == "ready":
                break
            time.sleep(0.04)
        assert st["control_state"] == "ready"

        r_cmd2 = client.post(
            "/api/commands/send",
            json={"device_id": dev_pk, "action": 0x31},
            headers={**h, "Idempotency-Key": str(uuid.uuid4())},
        ).json()
        assert r_cmd2["code"] == 0 and r_cmd2["data"]["seq"] == 2
        assert len(holder["c"].written) >= 3


def test_ble_write_timeout_tolerates_wireless_jitter_without_faulting(monkeypatch):
    import asyncio
    from app.link import ble_link
    from app.link.ble_link import DEFAULT_BLE_WRITE_TIMEOUT
    from app.link.frame import build
    from app.link.serial_link import (
        DEFAULT_WRITE_TIMEOUT,
        SerialLink,
        TRANSPORT_OK,
        open_port,
    )
    from app.link.simulator import CMD_HEARTBEAT_REQ

    class _SlowWriteClient(_FakeBleakClient):
        async def write_gatt_char(self, uuid_str: str, data: bytes, response: bool = False):
            # 模拟 Windows BLE 空口写抖动（350ms > 有线串口 200ms，但 < BLE 默认 3s）
            await asyncio.sleep(0.35)
            await super().write_gatt_char(uuid_str, data, response=response)

    port = BleBytePort("AA:BB:CC:DD:EE:55", client_factory=lambda a, **kw: _SlowWriteClient(a, **kw))
    assert port._write_timeout == DEFAULT_BLE_WRITE_TIMEOUT >= 2.0
    outcomes = []
    link = SerialLink(port, poll_interval=0.005)
    link.start()
    try:
        link.enqueue_heartbeat(build(CMD_HEARTBEAT_REQ), on_done=outcomes.append)
        for _ in range(100):
            if outcomes:
                break
            time.sleep(0.02)
        assert len(outcomes) == 1
        assert outcomes[0].transport == TRANSPORT_OK
        assert link.faulted is False
    finally:
        link.close()

    # open_port("ble://...") 默认用 BLE 写超时（3s），有线/loop:// 维持 200ms
    captured: dict[str, float] = {}

    class _CaptureBlePort:
        def __init__(self, _addr: str, **kw):
            captured["ble_wt"] = kw["write_timeout"]

    monkeypatch.setattr(ble_link, "BleBytePort", _CaptureBlePort)
    open_port("ble://AA:BB:CC:DD:EE:56")
    assert captured["ble_wt"] == DEFAULT_BLE_WRITE_TIMEOUT

    loop_port = open_port("loop://")
    try:
        assert loop_port.write_timeout == DEFAULT_WRITE_TIMEOUT
    finally:
        loop_port.close()


def test_ble_write_hard_timeout_raises_and_cached_device_error_falls_back(monkeypatch):
    import asyncio
    from app.link import ble_link

    class _HungWriteClient(_FakeBleakClient):
        async def write_gatt_char(self, uuid_str: str, data: bytes, response: bool = False):
            await asyncio.sleep(5.0)

    port = BleBytePort(
        "AA:BB:CC:DD:EE:57",
        write_timeout=0.1,
        client_factory=lambda a, **kw: _HungWriteClient(a, **kw),
    )
    try:
        with pytest.raises(SerialTimeoutException, match="BLE 写入超时"):
            port.write(b"\xAA\x55\x00\x04\xFB")
    finally:
        port.close()

    # 缓存对象快速报错（如 OSError / BleakError）时应清缓存并回落按地址重连
    addr = "AA:BB:CC:DD:EE:58"
    cached_obj = SimpleNamespace(address=addr)
    ble_link._cache_ble_device(addr, cached_obj)
    targets: list[object] = []

    class _FallbackClient(_FakeBleakClient):
        def __init__(self, target, **kw):
            targets.append(target)
            super().__init__(addr, **kw)
            self._fail = target is cached_obj

        async def connect(self):
            if self._fail:
                raise OSError("stale WinRT handle")
            await super().connect()

    monkeypatch.setattr(ble_link, "_import_bleak", lambda: (_FallbackClient, None))
    p2 = BleBytePort(addr)
    try:
        assert p2.is_open is True
        assert targets == [cached_obj, addr]
        assert ble_link._get_cached_ble_device(addr) is None
    finally:
        p2.close()


def test_ble_link_drop_during_motion_auto_reconnects_session(monkeypatch, tmp_path):
    with SessionLocal() as db:
        _, h = _mk_user(db, "ble_autoreconn")

    clients: list[_FakeBleakClient] = []

    def make_ble_port(addr: str) -> BleBytePort:
        def make_client(a, **kw):
            c = _FakeBleakClient(a, **kw)
            clients.append(c)
            return c

        return BleBytePort(addr, client_factory=make_client)

    monkeypatch.setattr(settings, "SERIAL_PORT", "ble")
    monkeypatch.setattr(settings, "SERIAL_DEVICE_PK", None)
    monkeypatch.setattr(settings, "DEV_BENCH_CONTROL", True)
    for k, v in dict(
        host_lock_path=tmp_path / "ble-autoreconn.lock",
        db_lock_name=f"petdog:test:autoreconn:{uuid.uuid4().hex[:8]}",
        ble_port_override=make_ble_port,
        ble_reconnect_delays=(0.05, 0.05),
        heartbeat_interval_sec=60.0,
        timeout_check_interval_sec=0.02,
    ).items():
        monkeypatch.setattr(app.state, k, v, raising=False)

    addr = f"BD:02:{uuid.uuid4().hex[:2].upper()}:11:22:33"
    with TestClient(app) as client:
        conn = client.post(
            "/api/devices/ble/connect",
            json={"address": addr, "name": "BrownoutDog"},
            headers=h,
        ).json()
        assert conn["code"] == 0
        dev_pk = conn["data"]["id"]
        first_sid = app.state.device_session.session_id
        assert len(clients) == 1

        # 模拟舵机动作过程中供电跌落导致 BLE 模块瞬断复位
        clients[0].trigger_disconnect()

        # 后台应自动重连并开启新会话，恢复 ready
        for _ in range(100):
            st = client.get(f"/api/devices/{dev_pk}/status", headers=h).json()["data"]
            if len(clients) >= 2 and st["control_state"] == "ready" and st["session_id"] != first_sid:
                break
            time.sleep(0.03)
        assert len(clients) >= 2
        assert st["online"] is True
        assert st["control_state"] == "ready"
        assert st["session_id"] != first_sid
