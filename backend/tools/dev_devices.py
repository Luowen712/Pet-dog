"""开发期设备管理工具：批量造设备、查看、解绑还原。

为什么需要它：
    后端目前没有任何「设备入册」的路径 —— 全项目没有一行代码会创建 Device 行，
    而 POST /api/devices/heartbeat 要求设备已存在（不存在返回 40400）。
    所以联调、验收、演示时只能手工往库里插数据。
    手工敲 python -c "..."，一是长，二是容易漏 handover_state 或 be，
    三是解绑还原那串命令特别容易写错，因此收口成这个脚本。

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe tools\\dev_devices.py list
    .venv\\Scripts\\python.exe tools\\dev_devices.py add              # 造 1 台
    .venv\\Scripts\\python.exe tools\\dev_devices.py add 3            # 造 3 台
    .venv\\Scripts\\python.exe tools\\dev_devices.py add 2 --name 测试桌宠
    .venv\\Scripts\\python.exe tools\\dev_devices.py add 1 --handover required
    .venv\\Scripts\\python.exe tools\\dev_devices.py release 1        # 按主键解绑
    .venv\\Scripts\\python.exe tools\\dev_devices.py release DEV-TEST-02

配对码要从「可认领」状态才能发，所以 add 默认 handover=ready。
真实流程里解绑后是 required，要等管理员走完交接才能再发码（06:296）。

这是开发期工具，不是生产 CLI：
    - 不拿 admin_lock（那会把正在跑的服务锁住）
    - 不做交互式密码输入
    - 上线前应连同 tools/sim_heartbeat.py 一起删掉

删设备是禁止的：Telemetry / CommandLog / DeviceClaim 等 5 张表都以
ondelete=RESTRICT 引用 device.id，删一台设备必须先清掉它的历史。
所以本工具只提供 release（解绑还原），不提供 delete。
"""

import argparse
import os
import sys

# 脚本在 tools/ 子目录里，sys.path[0] 是 tools 而不是 backend，
# 直接 import app 会 ModuleNotFoundError。把上一级塞进去。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func

from app.db import SessionLocal
from app.models import Device, DeviceClaim, Telemetry

DEFAULT_PREFIX = "DEV-TEST-"
DEFAULT_NAME = "测试桌宠"


def _next_seq(db, prefix: str) -> int:
    """找到 prefix 下已用的最大编号，返回下一个可用号。

    不能用 count()+1：删过设备或者跳号时，会和已有编号撞车（device_id 上有唯一约束）。
    """
    rows = db.query(Device.device_id).filter(Device.device_id.like(prefix + "%")).all()
    biggest = 0
    for (did,) in rows:
        tail = did[len(prefix):]
        if tail.isdigit():
            biggest = max(biggest, int(tail))
    return biggest + 1


def cmd_add(args) -> int:
    db = SessionLocal()
    try:
        start = _next_seq(db, args.prefix)
        made = []
        for i in range(args.count):
            did = "%s%02d" % (args.prefix, start + i)
            # 无主设备必须是 claimable 且不能是 bound —— ck_device_owner_status 卡这条
            d = Device(
                device_id=did,
                name=args.name,
                be=0,
                status="claimable",
                handover_state=args.handover,
            )
            db.add(d)
            made.append(did)
        db.commit()

        print("已创建 %d 台设备：" % len(made))
        for d in made:
            row = db.query(Device).filter(Device.device_id == d).first()
            print("  pk=%-3d %-16s name=%s handover=%s"
                  % (row.id, row.device_id, row.name, row.handover_state))
        if args.handover != "ready":
            print("\n注意：handover=%s 的设备发不出配对码，需先走完交接流程。" % args.handover)
        return 0
    finally:
        db.close()


def cmd_list(args) -> int:
    db = SessionLocal()
    try:
        rows = db.query(Device).order_by(Device.id).all()
        if not rows:
            print("(库里没有任何设备)")
            return 0

        print("%-4s %-16s %-6s %-3s %-10s %-9s %-19s %-19s"
              % ("pk", "device_id", "owner", "be", "status", "handover", "bound_at", "last_seen"))
        for d in rows:
            print("%-4d %-16s %-6s %-3d %-10s %-9s %-19s %-19s"
                  % (d.id, d.device_id, str(d.owner_id), d.be, d.status,
                     d.handover_state, str(d.bound_at or "-"), str(d.last_seen or "-")))

        # 遥测条数顺手打出来：换主人后旧代遥测还在表里，这是 be 过滤存在的理由
        counts = dict(
            db.query(Telemetry.device_pk, func.count(Telemetry.id))
            .group_by(Telemetry.device_pk)
            .all()
        )
        if counts:
            print("\n遥测条数：" + "  ".join("pk%s=%d" % (k, v) for k, v in sorted(counts.items())))

        claims = db.query(DeviceClaim).all()
        if claims:
            print("配对码行：")
            for c in claims:
                state = "已用" if c.consumed_at else ("锁定" if c.locked_until else "未用")
                print("  device_pk=%-3d attempts=%d %s expires=%s"
                      % (c.device_pk, c.attempts, state, c.expires_at))
        return 0
    finally:
        db.close()


def _resolve(db, ref: str):
    """先按主键找，找不到再按 device_id 找。人手敲的时候两种都可能。"""
    if ref.isdigit():
        d = db.query(Device).filter(Device.id == int(ref)).first()
        if d:
            return d
    return db.query(Device).filter(Device.device_id == ref).first()


def cmd_release(args) -> int:
    """解绑还原：把设备退回「可认领」状态，方便反复测试认领流程。

    这一步等价于真实的 DELETE /api/devices/{id}/binding（尚未实现）：
        owner 置空、status 回 claimable、be+1（隔断上一代遥测）、清 bound_at。
    be+1 是关键 —— 不 +1 的话下一个人会看到上一个人的电量（台账 S01）。
    """
    db = SessionLocal()
    try:
        d = _resolve(db, args.device)
        if d is None:
            print("[错误] 设备不存在：%s" % args.device, file=sys.stderr)
            return 2

        old_be = d.be
        d.owner_id = None
        d.status = "claimable"
        d.be = d.be + 1
        d.bound_at = None
        # 配对码行整行删掉：重新发码时会重建，留着会让 attempts 顺延
        db.query(DeviceClaim).filter(DeviceClaim.device_pk == d.id).delete()
        db.commit()

        print("已解绑 pk=%d %s    be: %d → %d   handover=%s"
              % (d.id, d.device_id, old_be, d.be, d.handover_state))
        if d.handover_state != "ready":
            print("handover=%s，发码会被拒；需要时用 -c 手工改回 ready" % d.handover_state)
        return 0
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(
        prog="dev_devices.py",
        description="开发期设备管理：造设备 / 查看 / 解绑还原",
    )
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="批量创建设备")
    a.add_argument("count", nargs="?", type=int, default=1, help="数量，默认 1")
    a.add_argument("--name", default=DEFAULT_NAME, help="设备名，默认「%s」" % DEFAULT_NAME)
    a.add_argument("--prefix", default=DEFAULT_PREFIX, help="编号前缀，默认 %s" % DEFAULT_PREFIX)
    a.add_argument("--handover", default="ready", choices=["ready", "required"],
                   help="交接状态，默认 ready（可直接发配对码）")
    a.set_defaults(func=cmd_add)

    b = sub.add_parser("list", help="列出所有设备")
    b.set_defaults(func=cmd_list)

    c = sub.add_parser("release", help="解绑还原（owner 置空、be+1、清配对码）")
    c.add_argument("device", help="设备主键或设备编号")
    c.set_defaults(func=cmd_release)

    args = p.parse_args()
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    if args.cmd == "add" and args.count < 1:
        print("[错误] count 至少为 1", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
