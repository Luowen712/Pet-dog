from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import Device, Telemetry
from app.resp import fail, ok

router = APIRouter(prefix="/api/devices", tags=["设备"])


class RenameIn(BaseModel):
    name: str


def device_out(d: Device, battery: int) -> dict:
    """把数据库的一行，转成前端要的形状。"""
    return {
        "id": d.id,
        "name": d.name or f"桌宠{d.id}",
        "online": bool(d.online),
        "firmware": d.firmware or "",
        "last_heartbeat": d.last_seen.isoformat() if d.last_seen else None,
        "battery": battery,
        "location": "",
    }


def latest_battery(db: Session, d: Device) -> int:
    """取这台设备最新一条遥测的电量，没有就 0。"""
    latest = (
        db.query(Telemetry)
        .filter(Telemetry.device_id == d.device_id)
        .order_by(Telemetry.created_at.desc())
        .first()
    )
    return latest.battery if latest and latest.battery is not None else 0


@router.get("")
def list_devices(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    devices = db.query(Device).all()

    data = []
    for d in devices:
        data.append(device_out(d, latest_battery(db, d)))
    return ok(data)


@router.get("/{id}")
def get_device(
    id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)
):
    d = db.get(Device, id)
    if not d:
        return fail(40400, "设备不存在")
    return ok(device_out(d, latest_battery(db, d)))


@router.patch("/{id}")
def rename_device(
    id: int,
    body: RenameIn,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    d = db.get(Device, id)
    if not d:
        return fail(40400, "设备不存在")

    name = body.name.strip()
    if not (1 <= len(name) <= 20):
        return fail(40002, "名字需要 1–20 个字符")

    d.name = name
    db.commit()
    db.refresh(d)

    return ok(device_out(d, latest_battery(db, d)))
