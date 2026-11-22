"""The disabled music extension must not acknowledge hardware operations or invent state."""
from uuid import uuid4
from fastapi.testclient import TestClient
from app.db import SessionLocal
from app.main import app
from app.models import Device, User
from app.security import make_token


def test_disabled_music_cannot_change_device_status():
    client = TestClient(app)
    with SessionLocal.begin() as db:
        user = User(username=uuid4().hex, password_hash='unused', role='user', status='active')
        db.add(user)
        db.flush()
        device = Device(device_id=uuid4().hex, owner_id=user.id, be=1, status='bound', handover_state='ready')
        db.add(device)
        db.flush()
        pk = device.id
        headers = {'Authorization': 'Bearer ' + make_token(user.id, user.username, user.token_version)}
    assert client.post(f'/api/devices/{pk}/music', json={'command': 5, 'value': 25}, headers=headers).status_code == 404
    data = client.get(f'/api/devices/{pk}/status', headers=headers).json()['data']
    assert data['music_state'] is None and data['volume'] is None and data['track'] is None
    assert data['action'] is None and data['voltage'] is None and data['face'] is None
