"""设备归属与遥测查询（BB03 第 1 条）。

为什么单独成层：
    路由（devices.py）和后面的 CLI（BB04 的 recover-device / complete-handover）
    都要判「这台设备是不是这个人的」。两处各写一份，早晚会跑偏。

为什么最新遥测必须带 be（绑定纪元）：
    设备换主人时 be +1，旧主人的遥测行还留在表里。
    只按 device_id 查，会把上一个主人的电量和动作当成现主人的「最新」，
    台账 S01「两账号交叉所有资源，历史与缓存不泄漏」卡的就是这条。
    device_id 本来就是设备自己报的字符串（外部输入），不该当主键用。
"""

from sqlalchemy import func, tuple_
from sqlalchemy.orm import Session

from app.models import Device, Telemetry


def get_owned_device(db: Session, uid: int, device_pk: int) -> Device | None:
    """只返回「这个人拥有的」设备。不是他的、不存在的，一律 None。

    调用方拿到 None 必须返回 40400，不能区分「没这台」和「不是你的」——
    一旦区分，就成了设备存在性探测接口。
    """
    return (
        db.query(Device).filter(Device.id == device_pk, Device.owner_id == uid).first()
    )


def latest_telemetry(db: Session, d: Device) -> Telemetry | None:
    """这台设备在当前绑定纪元下的最新一条遥测。

    排序用 id 而不是 created_at：id 是自增主键，插入顺序就是时间顺序，
    而 created_at 是应用层 datetime.now() 写的，系统时钟回拨会乱序。
    单台查询和下面的批量必须用同一套「谁算最新」的判据，否则两边结果对不上。
    """
    return (
        db.query(Telemetry)
        .filter(Telemetry.device_pk == d.id, Telemetry.be == d.be)
        .order_by(Telemetry.id.desc())
        .first()
    )


def latest_telemetry_map(db: Session, devices: list[Device]) -> dict[int, Telemetry]:
    """一次查出多台设备各自的最新遥测，key 是 device_pk。

    坑在这：每台设备的 be 不一定相同，所以不能写 Telemetry.be == 某个值，
    要用行构造器 (device_pk, be) IN ((1,0),(2,1))。
    也不能用 or_ 拼一堆条件，设备一多 SQL 就爆。
    """
    if not devices:
        return {}

    pairs = [(d.id, d.be) for d in devices]

    # 第一步：每台设备在当前 be 下的最大 id（最大 id = 最新那条）
    sub = (
        db.query(func.max(Telemetry.id).label("tid"))
        .filter(tuple_(Telemetry.device_pk, Telemetry.be).in_(pairs))
        .group_by(Telemetry.device_pk)
        .subquery()
    )
    # 第二步：拿这些 id 回表取整行
    rows = db.query(Telemetry).join(sub, Telemetry.id == sub.c.tid).all()
    return {t.device_pk: t for t in rows}


def battery_of(t: Telemetry | None) -> int | None:
    """没上报过就是 None，不是 0。

    契约 openapi.yaml:971 写的是 battery nullable:true。
    回填 0 会让前端显示「电量 0%」，用户以为没电跑去插线。
    """
    return t.battery if t is not None else None


def list_claimable_devices(db: Session) -> list[Device]:
    """可认领 = 状态可认领 + 无主 + 交接已完成，三个条件缺一不可。

    这个函数只读，不需要 SendGate（06:191：只读无须 SendGate）。
    """
    return (
        db.query(Device)
        .filter(
            Device.status == "claimable",
            Device.owner_id.is_(None),
            Device.handover_state == "ready",
        )
        .order_by(Device.id)
        .all()
    )
