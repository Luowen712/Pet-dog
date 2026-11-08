from datetime import datetime, timedelta

from app.db import SessionLocal
from app.models import Device, Telemetry

db = SessionLocal()
try:
    if db.query(Device).count() > 0:
        print("设备表已存在数据，跳过初始化")
    else:
        d1 = Device(
            device_id="PET-0001-ABCD",
            name="桌面小狗",
            firmware="1.0.3",
            capability=3,
            online=True,
            last_seen=datetime.now(),
            owner_id=1,
        )
        d2 = Device(
            device_id="PET-0002-EFGH",
            name="备用桌宠",
            firmware="1.0.2",
            capability=1,
            online=False,
            last_seen=datetime.now() - timedelta(hours=6),
            owner_id=1,
        )
        db.add_all([d1, d2])
        db.commit()
        print("已插入 2 台设备")
        for batt, act, mins in [(88, 1, 30), (85, 2, 20), (82, 1, 10)]:
            db.add(
                Telemetry(
                    device_id="PET-0001-ABCD",
                    battery=batt,
                    music_state=0,
                    action=act,
                    raw="seed",
                    created_at=datetime.now() - timedelta(minutes=mins),
                )
            )
        db.commit()
        print("已插入 3 条遥测")
finally:
    db.close()
