"""低功耗蓝牙（ECB02H2）扫描与直连绑定服务：取代 6 位配对码流程。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.link.ble_link import (
    SIM_BLE_ADDRESS,
    SIM_BLE_NAME,
    BleCandidate,
    scan_ble_devices,
)
from app.link.send_gate import RevokeEvent, send_gate
from app.models import Device, User


class BleBindError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_ble_address(raw: str) -> str:
    addr = raw.strip()
    if not (1 <= len(addr) <= 32) or any(ch.isspace() for ch in addr):
        raise BleBindError(40002, "蓝牙设备地址格式不合法")
    return addr


def normalize_device_name(raw: str | None, fallback: str) -> str:
    if raw is None or not raw.strip():
        return fallback[:64]
    name = raw.strip()
    if not (1 <= len(name) <= 64):
        raise BleBindError(40002, "名字需要 1–64 个字符")
    return name


def is_sim_mode() -> bool:
    return settings.SERIAL_PORT.strip().lower() == "sim"


async def discover_ble_candidates(
    *,
    discover_fn: Callable[..., Any] | None = None,
) -> list[BleCandidate]:
    """仅执行异步 BLE 扫描（不占数据库连接）。"""
    if is_sim_mode() and discover_fn is None:
        return [
            BleCandidate(
                address=SIM_BLE_ADDRESS,
                name=SIM_BLE_NAME,
                rssi=-45,
                transport="sim",
            )
        ]
    return await scan_ble_devices(
        timeout=settings.BLE_SCAN_TIMEOUT_SEC,
        service_uuid=settings.BLE_SERVICE_UUID,
        discover_fn=discover_fn,
    )


def filter_ble_candidates(
    db: Session,
    uid: int,
    candidates: list[BleCandidate],
) -> list[dict]:
    """按库内归属过滤已停用与已归属他人的设备，不泄露他人绑定关系。"""
    addrs = [c.address for c in candidates]
    existing_map: dict[str, Device] = {}
    if addrs:
        rows = db.query(Device).filter(Device.device_id.in_(addrs)).all()
        existing_map = {d.device_id: d for d in rows}

    visible: list[dict] = []
    for c in candidates:
        row = existing_map.get(c.address)
        if row is not None:
            if row.status == "retired":
                continue
            if row.owner_id is not None and row.owner_id != uid:
                continue
        visible.append(
            {
                "address": c.address,
                "name": row.name if (row is not None and row.owner_id == uid and row.name) else c.name,
                "rssi": c.rssi,
                "transport": c.transport,
                "bound_to_me": row is not None and row.owner_id == uid,
            }
        )
    return visible


async def scan_ble_for_user(
    db: Session,
    uid: int,
    *,
    discover_fn: Callable[..., Any] | None = None,
) -> list[dict]:
    """扫描附近 BLE 外设并过滤掉已归属他人的设备，不泄露他人绑定关系。"""
    candidates = await discover_ble_candidates(discover_fn=discover_fn)
    return filter_ble_candidates(db, uid, candidates)


def precheck_ble_bind(db: Session, uid: int, address: str) -> Device | None:
    """在发起慢速 BLE 建连前只读预检，避免无法绑定时白连蓝牙。"""
    u = db.query(User).filter(User.id == uid).first()
    if u is None or u.status != "active":
        raise BleBindError(40101, "登录已过期")
    existing = db.query(Device).filter(Device.device_id == address).first()
    owned = db.query(Device).filter(Device.owner_id == uid).first()
    if owned is not None and (existing is None or owned.id != existing.id):
        raise BleBindError(40900, "当前账号已绑定设备，请先解绑")
    if existing is not None:
        if existing.status == "retired":
            raise BleBindError(40900, "设备已停用")
        if existing.owner_id is not None and existing.owner_id != uid:
            raise BleBindError(40900, "设备已被其他账号绑定")
    return existing


def bind_ble_device(
    db: Session,
    uid: int,
    address: str,
    name: str | None = None,
) -> tuple[Device, bool]:
    """在 SendGate 内直接绑定（或登记并绑定）指定 BLE 设备到当前账号，无需配对码。"""
    addr = normalize_ble_address(address)
    clean_name = normalize_device_name(name, addr)
    newly_bound = False
    bound_be: int | None = None

    with send_gate.hold():
        u = db.query(User).filter(User.id == uid).with_for_update().first()
        if u is None or u.status != "active":
            raise BleBindError(40101, "登录已过期")

        d = (
            db.query(Device)
            .filter(Device.device_id == addr)
            .with_for_update()
            .first()
        )
        owned = db.query(Device).filter(Device.owner_id == uid).first()
        if owned is not None and (d is None or owned.id != d.id):
            raise BleBindError(40900, "当前账号已绑定设备，请先解绑")

        now = datetime.now()
        if d is None:
            d = Device(
                device_id=addr,
                name=clean_name,
                owner_id=uid,
                status="bound",
                handover_state="ready",
                be=1,
                bound_at=now,
            )
            db.add(d)
            newly_bound = True
        else:
            if d.status == "retired":
                raise BleBindError(40900, "设备已停用")
            if d.owner_id is not None and d.owner_id != uid:
                raise BleBindError(40900, "设备已被其他账号绑定")
            if d.owner_id != uid:
                d.owner_id = uid
                d.status = "bound"
                d.handover_state = "ready"
                d.bound_at = now
                if not d.name:
                    d.name = clean_name
                newly_bound = True
            else:
                d.handover_state = "ready"

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise BleBindError(40900, "当前账号已绑定设备或该蓝牙设备已被占用")

        db.refresh(d)
        bound_be = d.be

    if newly_bound:
        send_gate.notify_revoke(
            RevokeEvent(uid=uid, device_pk=d.id, kind="claim", new_be=bound_be)
        )
    return d, newly_bound
