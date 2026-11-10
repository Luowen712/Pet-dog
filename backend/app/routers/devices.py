from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends  # 路由容器 + 依赖注入标记
from pydantic import BaseModel  # 声明请求体的形状
from sqlalchemy.orm import Session  # 类型标注用，运行时不做任何事

from app.db import get_db  # Session 工厂（依赖）
from app.deps import current_user  # 登录校验（依赖）
from app.models import Device, Telemetry  # 两张表的映射类
from app.resp import fail, ok  # 统一响应外壳

router = APIRouter(prefix="/api/devices", tags=["设备"])

# 库里存的是服务器本地时间（+08:00），契约 1.4 要求输出带时区，这里补上标签
CST = timezone(timedelta(hours=8))


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt.isoformat()


class RenameIn(BaseModel):
    name: str


class MusicIn(BaseModel):
    command: int
    value: int = 0


def device_out(d: Device, battery: int) -> dict:
    return {
        "id": d.id,
        "name": d.name or f"桌宠{d.id}",
        "online": bool(d.online),
        "firmware": d.firmware or "",
        "last_heartbeat": d.last_seen.isoformat() if d.last_seen else None,
        "battery": battery,
        "location": "",
    }


def latest_telemetry(db: Session, d: Device) -> Telemetry | None:
    return (
        db.query(Telemetry)
        .filter(Telemetry.device_id == d.device_id)
        .order_by(Telemetry.created_at.desc(), Telemetry.id.desc())
        .first()
    )


# 电量


def latest_battery(db: Session, d: Device) -> int:
    t = latest_telemetry(db, d)
    return t.battery if t and t.battery is not None else 0


# 获取设备列表，供页面显示和选择设备
@router.get("")
def list_devices(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    devices = db.query(Device).all()

    data = []
    for d in devices:
        data.append(device_out(d, latest_battery(db, d)))
    return ok(data)


# 获取单台设备的完整信息
@router.get("/{id}")
def get_device(
    id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)
):
    d = db.get(Device, id)
    if not d:
        return fail(40400, "设备不存在")
    return ok(device_out(d, latest_battery(db, d)))


# 	修改设备名字
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


_music_state: dict[str, dict] = {}

MUSIC_CODES = {0, 1, 2, 3, 4, 5}  # 停止/播放/暂停/下一首/上一首/设音量
TRACK_TOTAL = 9  # 曲目总数，下一首/上一首在这里回绕，别推出 0 或 10
DEFAULT_VOLUME = 15  # DFPlayer 量程 0-30


# 获取当前选中设备的实时状态快照
@router.get("/{id}/status")
def get_device_status(
    id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)
):
    d = db.get(Device, id)
    if not d:
        return fail(40400, "设备不存在")

    t = latest_telemetry(db, d)
    music = _music_state.get(d.device_id, {})

    return ok(
        {
            "device_id": d.id,
            "battery": t.battery if t and t.battery is not None else 0,
            "voltage": 0.0,  # 等 0x03 上报 mV / 1000
            "action": t.action if t and t.action is not None else 49,  # 49 = 0x31 站立
            "face": 0,  # 等 0x03 上报表情编号
            "music_state": music.get(
                "state", t.music_state if t and t.music_state is not None else 0
            ),
            "track": music.get("track", 1),
            "volume": music.get("volume", DEFAULT_VOLUME),
            "weather_code": 0,  # 等 0x09 下发/0x03 回报
            "temp": 0,
            "updated_at": to_iso(t.created_at if t else d.last_seen)
            or to_iso(datetime.now()),
        }
    )


# 控制音乐播放、切歌和音量
@router.post("/{id}/music")
def control_music(
    id: int,
    body: MusicIn,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    d = db.get(Device, id)
    if not d:
        return fail(40400, "设备不存在")
    if body.command not in MUSIC_CODES:
        return fail(40002, "音乐子命令需要在 0–5 之间")
    if body.command == 5 and not (0 <= body.value <= 30):
        return fail(40002, "音量需要在 0–30 之间")

    st = _music_state.setdefault(
        d.device_id, {"state": 0, "track": 1, "volume": DEFAULT_VOLUME}
    )

    if body.command == 0:
        st["state"] = 0
    elif body.command == 1:
        st["state"] = 1
    elif body.command == 2:
        st["state"] = 2
    elif body.command == 3:
        st["track"] = st["track"] % TRACK_TOTAL + 1
        st["state"] = 1
    elif body.command == 4:
        st["track"] = (st["track"] + TRACK_TOTAL - 2) % TRACK_TOTAL + 1
        st["state"] = 1
    else:
        st["volume"] = body.value

    # TODO 串口起来后在这里发 0x0A 帧（DATA = [command, value]），并推 WS music 事件
    return ok(
        {"ok": True, "state": st["state"], "track": st["track"], "volume": st["volume"]}
    )
