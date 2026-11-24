import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request  # 路由容器 + 依赖注入标记
from pydantic import BaseModel  # 声明请求体的形状
from serial import SerialException
from sqlalchemy.orm import Session  # 类型标注用，运行时不做任何事

from app import ratelimit
from app.config import settings  # 配置（DEV_HEARTBEAT开关）
from app.db import SessionLocal, get_db  # Session 工厂（依赖）
from app.deps import current_user  # 登录校验（依赖）
from app.link.ble_link import BleUnavailableError
from app.link.send_gate import RevokeEvent, send_gate
from app.link.serial_link import open_port
from app.models import Device  # 设备表映射类
from app.resp import fail, ok  # 统一响应外壳
from app.services import ble as ble_service
from app.services import presence
from app.services.ble import BleBindError
from app.services.ownership import (
    battery_of,
    get_owned_device,
    latest_telemetry,
    latest_telemetry_map,
)

SUPPORTED_ACTIONS = [0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36]

router = APIRouter(prefix="/api/devices", tags=["设备"])

# 库里存的是服务器本地时间（+08:00），契约 1.4 要求输出带时区，这里补上标签
CST = timezone(timedelta(hours=8))



def to_iso(dt: datetime | None) -> str | None:
    """把库里的本地时间补上 +08:00 时区后转成 ISO 字符串，None 原样返回。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt.isoformat()


class RenameIn(BaseModel):
    name: str



def _live_session(request: Request | None, device_pk: int):
    """取该设备当前的在线会话；设备不匹配或进程未启动会话时返回 None。"""
    if request is None:
        return None
    sess = getattr(request.app.state, "device_session", None)
    if sess is not None and sess.device_pk == device_pk:
        return sess
    return None



def device_out(
    d: Device,
    battery: int | None,
    online: bool | None = None,
    *,
    session=None,
) -> dict:
    """把设备行拼成前端展示结构，有实时会话时优先用会话快照。"""
    snap = session.snapshot() if session is not None else None
    if snap is not None and snap.be != d.be:
        snap = None
    if snap is not None:
        is_on = snap.online
        ctrl = snap.control_state
        bat = snap.battery
        last_hb = snap.last_heartbeat
    else:
        is_on = presence.is_online(d.last_seen) if online is None else online
        if d.handover_state != "ready":
            ctrl = "handover_required"
        else:
            ctrl = "unconfigured" if is_on else "offline"
        bat = battery
        last_hb = d.last_seen

    return {
        "id": d.id,
        "name": d.name or f"桌宠{d.id}",
        "online": is_on,
        "firmware": d.firmware or "",
        "last_heartbeat": to_iso(last_hb),
        "battery": bat,
        "location": "",
        "binding_state": d.status or "claimable",
        "control_state": ctrl,
        "supported_actions": list(snap.supported_actions) if snap is not None else [],
    }



# 获取设备列表，供页面显示和选择设备
@router.get("")
def list_devices(
    request: Request,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户名下的设备，附带最新遥测与在线状态。"""
    devices = db.query(Device).filter(Device.owner_id == user.get("uid")).all()
    tmap = latest_telemetry_map(db, devices)
    at = datetime.now()
    data = [
        device_out(
            d,
            battery_of(tmap.get(d.id)),
            presence.is_online(d.last_seen, at),
            session=_live_session(request, d.id),
        )
        for d in devices
    ]
    return ok(data)



@router.get("/ble/scan")
async def scan_ble(request: Request, user: dict = Depends(current_user)):
    """按用户限流后扫描附近蓝牙设备，并过滤掉已归属他人的设备。"""
    uid = user.get("uid")
    bucket = f"ble_scan:{uid}"
    wait = ratelimit.check(bucket, 20, 60)
    if wait:
        raise ratelimit.too_many(wait)
    ratelimit.record(bucket, 60)

    discover_fn = getattr(request.app.state, "ble_discover_override", None)
    try:
        candidates = await ble_service.discover_ble_candidates(discover_fn=discover_fn)
    except BleUnavailableError as exc:
        return fail(40900, str(exc))

    def _filter():
        """在线程里查库过滤候选设备，避免阻塞事件循环。"""
        with SessionLocal() as db:
            return ble_service.filter_ble_candidates(db, uid, candidates)

    items = await asyncio.to_thread(_filter)
    return ok(items)


class BleConnectIn(BaseModel):
    address: str
    name: str | None = None



# 低功耗蓝牙直接连接并绑定当前账号（取消 6 位配对码流程，见 06 第 12.7 节）
@router.post("/ble/connect")
async def connect_ble(
    body: BleConnectIn,
    request: Request,
    user: dict = Depends(current_user),
):
    """蓝牙直连并绑定当前账号，取代 6 位配对码流程。"""
    uid = user.get("uid")
    try:
        addr = ble_service.normalize_ble_address(body.address)
        clean_name = ble_service.normalize_device_name(body.name, addr)
    except BleBindError as e:
        return fail(e.code, e.message)

    has_lifespan = getattr(request.app.state, "process_lock", None) is not None
    session_lock = getattr(request.app.state, "session_lock", None)
    sim_mode = ble_service.is_sim_mode()

    async def _run_connect():
        """执行完整连接流程：预检、开串口、绑定落库，按需启动设备会话。"""
        cur_session = getattr(request.app.state, "device_session", None)

        def _precheck():
            """连接前只读预检：账号可用、设备可绑、主机蓝牙链路未被他人占用。"""
            with SessionLocal() as db:
                existing_row = ble_service.precheck_ble_bind(db, uid, addr)
                if cur_session is not None and (
                    existing_row is None or cur_session.device_pk != existing_row.id
                ):
                    active_dev = db.get(Device, cur_session.device_pk)
                    if (
                        active_dev is not None
                        and active_dev.owner_id is not None
                        and active_dev.owner_id != uid
                        and cur_session.control_state not in ("faulted", "handover_required")
                    ):
                        raise BleBindError(40900, "当前主机蓝牙链路正被其他账号设备占用")
                return existing_row

        try:
            existing = await asyncio.to_thread(_precheck)
        except BleBindError as e:
            if e.code == 40101:
                raise HTTPException(401, detail={"code": 40101, "message": e.message})
            return fail(e.code, e.message)

        reuse_session = (
            existing is not None
            and existing.owner_id == uid
            and cur_session is not None
            and cur_session.device_pk == existing.id
            and cur_session.be == existing.be
            and cur_session.online
            and cur_session.control_state not in ("faulted", "offline", "handover_required")
        )
        opened_port = None
        if has_lifespan and not reuse_session:
            port_override = getattr(request.app.state, "ble_port_override", None)
            # 重连同一台设备时先释放旧会话句柄，避免单连接 BLE 模块 ECB02H2 拒连
            if (
                cur_session is not None
                and existing is not None
                and cur_session.device_pk == existing.id
            ):
                from app.main import stop_device_session

                was_open = bool(
                    getattr(getattr(getattr(cur_session, "_link", None), "_port", None), "is_open", False)
                )
                await stop_device_session(request.app)
                if was_open and not sim_mode and port_override is None:
                    # 给 ECB02H2 与 Windows BLE 协议栈短暂回落时间，避免旧连接尚未撤完就撞连
                    await asyncio.sleep(0.5)

            spec = "sim" if sim_mode else f"ble://{addr}"
            try:
                opened_port = (
                    port_override(addr)
                    if callable(port_override)
                    else await asyncio.to_thread(open_port, spec, baudrate=settings.SERIAL_BAUD)
                )
            except (SerialException, OSError) as exc:
                return fail(40900, f"蓝牙连接失败：{exc}")

        def _bind():
            """在线程里完成绑定，并顺带取回最新电量。"""
            with SessionLocal() as db:
                d, _ = ble_service.bind_ble_device(db, uid, addr, clean_name)
                bat = battery_of(latest_telemetry(db, d))
                return d, bat

        try:
            d, bat = await asyncio.to_thread(_bind)
        except BaseException as exc:
            if opened_port is not None:
                try:
                    await asyncio.to_thread(opened_port.close)
                except Exception:
                    pass
            if isinstance(exc, BleBindError):
                if exc.code == 40101:
                    raise HTTPException(401, detail={"code": 40101, "message": exc.message})
                return fail(exc.code, exc.message)
            raise

        if has_lifespan and opened_port is not None:
            from app.main import start_device_session

            await start_device_session(request.app, d.id, port=opened_port, is_sim=sim_mode)

        return ok(device_out(d, bat, session=_live_session(request, d.id)))

    if session_lock is not None:
        async with session_lock:
            return await _run_connect()
    return await _run_connect()



# 获取单台设备的完整信息
@router.get("/{id}")
def get_device(
    id: int,
    request: Request,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    """查询自己名下单台设备的详细信息。"""
    d = get_owned_device(db, user.get("uid"), id)
    if not d:
        return fail(40400, "设备不存在")
    return ok(
        device_out(
            d,
            battery_of(latest_telemetry(db, d)),
            session=_live_session(request, d.id),
        )
    )



# 	修改设备名字
@router.patch("/{id}")
def rename_device(
    id: int,
    body: RenameIn,
    request: Request,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    """修改设备名字，长度须在 1–64 个字符之间。"""
    d = get_owned_device(db, user.get("uid"), id)
    if not d:
        return fail(40400, "设备不存在")

    name = body.name.strip()
    if not (1 <= len(name) <= 64):
        return fail(40002, "名字需要 1–64 个字符")

    d.name = name
    db.commit()
    db.refresh(d)

    return ok(
        device_out(
            d,
            battery_of(latest_telemetry(db, d)),
            session=_live_session(request, d.id),
        )
    )



# 获取当前选中设备的实时状态快照
@router.get('/{id}/status')
def get_device_status(id: int, request: Request, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    """返回设备实时状态快照，没有在线会话时回落到最新遥测。"""
    d = get_owned_device(db, user['uid'], id)
    if not d:
        return fail(40400, '设备不存在')
    session = _live_session(request, id)
    snap = session.snapshot() if session else None
    fields = ('battery', 'voltage', 'action', 'face', 'music_state', 'track', 'volume', 'weather_code', 'temp')
    if snap and snap.be == d.be:
        return ok(dict(device_id=id, online=snap.online, control_state=snap.control_state,
                       session_id=snap.session_id, state_revision=snap.state_revision,
                       updated_at=to_iso(snap.last_heartbeat), **{k: getattr(snap, k) for k in fields}))
    latest = latest_telemetry(db, d)
    values = dict.fromkeys(fields)
    if latest:
        values.update(battery=latest.battery, action=latest.action, music_state=latest.music_state)
    return ok(dict(device_id=id, online=presence.is_online(d.last_seen),
                   control_state=device_out(d, None)['control_state'], session_id=None, state_revision=0,
                   updated_at=to_iso(latest.created_at if latest else d.last_seen), **values))




class BindingDeleteIn(BaseModel):
    # 契约 BindingDeleteRequest：只需一个确认字段，防止前端点错设备
    confirm_device_id: int



# 解绑设备（06:78、06:296）
@router.delete("/{id}/binding")
async def unbind_device(
    id: int,
    body: BindingDeleteIn,
    request: Request,
    user: dict = Depends(current_user),
):
    # 先判参数、再判归属、最后判状态。顺序反过来的话，错误码的差异
    # 就成了「这个 id 到底存不存在」的探测器。
    """解绑设备：递增绑定纪元、清空归属，并停掉该设备的会话。"""
    if body.confirm_device_id != id:
        return fail(40002, "确认设备 id 不匹配")
    uid = user.get("uid")

    def _unbind_tx():
        """在门禁与事务内校验归属和状态后解绑，返回新的绑定纪元。"""
        with send_gate.hold(), SessionLocal() as db:
            d = get_owned_device(db, uid, id, for_update=True)
            if not d:
                return None, fail(40400, "设备不存在")
            # 只有 bound 的设备能解绑。已经是 claimable / retired 的没有绑定可解
            if d.status != "bound":
                return None, fail(40900, "设备当前状态不允许解绑")
            old_be = d.be
            d.owner_id = None
            d.status = "claimable"
            d.handover_state = "required"
            d.bound_at = None
            new_be = old_be + 1
            d.be = new_be
            db.commit()
            return new_be, None

    new_be, err = await asyncio.to_thread(_unbind_tx)
    if err is not None:
        return err

    send_gate.notify_revoke(
        RevokeEvent(uid=uid, device_pk=id, kind="unbind", new_be=new_be)
    )
    from app.main import stop_ble_session_if_matching

    await stop_ble_session_if_matching(request.app, {id})
    return ok({"unbound": True, "handover_required": True})


if settings.DEV_HEARTBEAT:

    class HeartbeatIn(BaseModel):
        device_id: str



    @router.post("/heartbeat")
    def heartbeat(body: HeartbeatIn, db: Session = Depends(get_db)):
        """开发用心跳接口：刷新设备的最后在线时间。"""
        d = db.query(Device).filter(Device.device_id == body.device_id).first()
        if not d:
            return fail(40400, "设备不存在")
        d.last_seen = datetime.now()
        db.commit()
        return ok(
            {"device_id": d.id, "online": True, "last_heartbeat": to_iso(d.last_seen)}
        )
