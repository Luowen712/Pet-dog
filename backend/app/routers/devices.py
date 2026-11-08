from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import Device, Telemetry

router = APIRouter(prefix="/api/devices", tags=["设备"])


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


@router.get("")
def list_devices(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    devices = db.query(Device).all()

    data = []
    for d in devices:
        latest = (
            db.query(Telemetry)
            .filter(Telemetry.device_id == d.device_id)
            .order_by(Telemetry.created_at.desc())
            .first()
        )
        battery = latest.battery if latest and latest.battery is not None else 0
        data.append(device_out(d, battery))

    return {"code": 0, "message": "ok", "data": data, "timestamp": 0}
