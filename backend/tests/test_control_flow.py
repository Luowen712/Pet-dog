import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.link.send_gate import RevokeEvent, send_gate
from app.main import _require_schema, _resolve_device_pk, app
from app.models import Device, User
from app.security import hash_pwd, make_token



@pytest.fixture
def sim(monkeypatch, tmp_path):
    """准备两个账号、一台模拟设备与已启动的应用，返回客户端和请求头。"""
    with SessionLocal.begin() as db:
        pw = hash_pwd('secret-pass-1234')
        users = [User(username=uuid.uuid4().hex[:16], password_hash=pw, status='active', token_version=0) for _ in range(2)]
        db.add_all(users)
        db.flush()
        owner, other = users
        device = Device(device_id=uuid.uuid4().hex[:16], owner_id=owner.id, be=1, status='bound', handover_state='ready')
        db.add(device)
        db.flush()
        pk = device.id
        other_name = other.username
        headers = [{'Authorization': 'Bearer ' + make_token(u.id, u.username, 0)} for u in users]
    monkeypatch.setattr(settings, 'SERIAL_PORT', 'sim')
    for key, value in dict(device_pk=pk, host_lock_path=tmp_path/'sim.lock', heartbeat_interval_sec=.05, timeout_check_interval_sec=.05).items():
        monkeypatch.setattr(app.state, key, value, raising=False)
    with TestClient(app) as client:
        yield client, pk, headers, other_name



def test_sim_control_roundtrip(sim):
    """模拟链路上完成一次动作下发，回执与状态快照都能对上。"""
    client, pk, (headers, foreign), _ = sim
    for _ in range(200):
        if app.state.device_session.control_state == 'ready':
            break
        time.sleep(.02)
    listed = client.get('/api/devices', headers=headers).json()['data']
    mine = next(item for item in listed if item['id'] == pk)
    state = client.get(f'/api/devices/{pk}/status', headers=headers).json()['data']
    assert state['online'] and state['control_state'] == 'ready'
    assert mine['online'] == state['online'] and mine['control_state'] == state['control_state']
    assert mine['battery'] == state['battery']
    assert state['session_id'] and state['state_revision'] > 0
    assert state['volume'] is None
    ticket = client.post('/api/events/ticket', json={'device_id': pk}, headers=headers).json()['data']['ticket']
    key = str(uuid.uuid4())
    command_headers = {**headers, 'Idempotency-Key': key}
    body = {'device_id': pk, 'action': 49}
    with client.websocket_connect(f'/ws/device?device_id={pk}&ticket={ticket}') as ws:
        sent = client.post('/api/commands/send', json=body, headers=command_headers).json()
        assert sent['code'] == 0 and sent['data']['cmd_id'] == key
        while True:
            event = ws.receive_json()
            if event['event'] == 'command' and event['data']['cmd_id'] == key and event['data']['status'] == 'done':
                break
        receipt = client.get('/api/commands/' + key, headers=headers).json()['data']
        assert receipt['status'] == 'done' and receipt['transport'] == 'ok'
        assert client.get('/api/commands/' + key, headers=foreign).json()['code'] == 40400
        assert client.post('/api/commands/send', json=body, headers=command_headers).json()['data'] == receipt
        assert client.post('/api/commands/send', json={**body, 'action': 50}, headers=command_headers).json()['code'] == 40900
        assert app.state.device_session.last_seq == 1
        assert client.post('/api/faces/current', json={'device_id': pk, 'face': 1}, headers=foreign).json()['code'] == 40400
        assert client.post('/api/faces/current', json={'device_id': pk, 'face': 1}, headers=headers).json()['data'] == {'face': 1, 'dispatched': True}
    with client.websocket_connect(f'/ws/device?device_id={pk}&ticket={ticket}') as ws:
        assert ws.receive()['code'] == 4003



@pytest.mark.parametrize('args', [['--workers', '1'], ['--workers=1'], ['-w1']])
def test_explicit_single_worker(monkeypatch, args):
    """显式声明单 worker 时应允许启动。"""
    import sys
    from app.ratelimit import assert_single_process
    monkeypatch.setattr(sys, 'argv', ['uvicorn', *args])
    assert_single_process()



def test_connection_limit_and_logout_closes_live_sockets(sim):
    """同一账号连接数受限，登出会主动断开已建立的连接。"""
    from contextlib import ExitStack
    client, pk, (headers, _), _ = sim
    def connect():
        """用票据建立一条 WebSocket 连接。"""
        ticket = client.post('/api/events/ticket', json={'device_id': pk}, headers=headers).json()['data']['ticket']
        return client.websocket_connect(f'/ws/device?device_id={pk}&ticket={ticket}')
    with ExitStack() as stack:
        sockets = [stack.enter_context(connect()) for _ in range(3)]
        with connect() as extra:
            assert extra.receive()['code'] == 4009
        assert client.post('/api/auth/logout', headers=headers).json()['code'] == 0
        for ws in sockets:
            for _ in range(5):
                msg = ws.receive()
                if msg['type'] == 'websocket.close':
                    assert msg['code'] == 4401
                    break
            else:
                pytest.fail('old socket remained open after logout')



def test_no_ack_late_done_corrects_original_without_resending(sim, monkeypatch):
    """丢 ACK 后迟到的完成帧能纠正原回执，且不会重发指令。"""
    from app.link.simulator import SimFaults
    client, pk, (headers, _), _ = sim
    session = app.state.device_session
    monkeypatch.setattr(session._link._port._device, '_faults', SimFaults(drop_ack=True, delay_done_ms=1800))
    for _ in range(100):
        if session.control_state == 'ready':
            break
        time.sleep(.02)
    key = str(uuid.uuid4())
    body = {'device_id': pk, 'action': 49}
    h = {**headers, 'Idempotency-Key': key}
    assert client.post('/api/commands/send', headers=h, json=body).json()['code'] == 0
    statuses = []
    for _ in range(200):
        status = client.get('/api/commands/' + key, headers=headers).json()['data']['status']
        if status == 'unknown' and status not in statuses:
            assert session.control_state == 'recovery_required'
            assert client.post('/api/commands/send', headers={**headers, 'Idempotency-Key': str(uuid.uuid4())}, json=body).json()['code'] == 40900
        statuses.append(status)
        if status == 'done':
            break
        time.sleep(.02)
    assert 'unknown' in statuses and statuses[-1] == 'done'
    assert session.last_seq == 1 and session.control_state == 'ready'



def test_dual_account_delete_preserves_other_session_and_inflight_command(sim, monkeypatch):
    """一个账号注销不影响另一账号的会话与在途指令。"""
    from app.link.simulator import SimFaults
    client, pk, (owner_h, other_h), other_name = sim
    session = app.state.device_session
    monkeypatch.setattr(session._link._port._device, '_faults', SimFaults(delay_done_ms=450))
    for _ in range(100):
        if session.control_state == 'ready':
            break
        time.sleep(.02)
    key = str(uuid.uuid4())
    sent = client.post('/api/commands/send', json={'device_id': pk, 'action': 49},
                       headers={**owner_h, 'Idempotency-Key': key}).json()
    assert sent['code'] == 0
    # A (无设备) 走真实 HTTP 注销，此时 B 的动作仍在途
    deleted = client.request('DELETE', '/api/auth/account', headers=other_h,
                             json={'password': 'secret-pass-1234', 'confirm_username': other_name}).json()
    assert deleted['code'] == 0 and deleted['data']['status'] == 'revoking'
    assert session.control_state != 'handover_required'
    for _ in range(100):
        receipt = client.get('/api/commands/' + key, headers=owner_h).json()['data']
        if receipt['status'] == 'done':
            break
        time.sleep(.02)
    assert receipt['status'] == 'done'
    assert session.control_state == 'ready'



def test_password_change_closes_live_ws_with_4401(sim):
    """改密码后现有连接应以 4401 关闭。"""
    client, pk, (headers, _), _ = sim
    ticket = client.post('/api/events/ticket', json={'device_id': pk}, headers=headers).json()['data']['ticket']
    with client.websocket_connect(f'/ws/device?device_id={pk}&ticket={ticket}') as ws:
        res = client.put('/api/auth/password', headers=headers,
                         json={'old_password': 'secret-pass-1234', 'new_password': 'new-secret-pass-5678'}).json()
        assert res['code'] == 0
        for _ in range(5):
            msg = ws.receive()
            if msg['type'] == 'websocket.close':
                assert msg['code'] == 4401
                break
        else:
            pytest.fail('live socket stayed open after password change')



def test_schema_mismatch_and_ambiguous_serial_device_guard(monkeypatch):
    """迁移版本不匹配、多设备未指定主键都必须拒绝启动。"""
    from types import SimpleNamespace
    from alembic.migration import MigrationContext
    monkeypatch.setattr(MigrationContext, 'get_current_heads', lambda self: ('0001',))
    with pytest.raises(RuntimeError, match='数据库版本不匹配'):
        _require_schema()

    with SessionLocal.begin() as db:
        db.add_all([Device(device_id=f'AMB-{uuid.uuid4().hex[:8]}') for _ in range(2)])
    fake_app = SimpleNamespace(state=SimpleNamespace())
    monkeypatch.setattr(settings, 'SERIAL_DEVICE_PK', None)
    assert _resolve_device_pk(fake_app) is None
    assert fake_app.state.device_session_error == 'ambiguous_serial_device'
