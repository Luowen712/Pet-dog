from app.db import SessionLocal
from app.models import Device

db = SessionLocal()
try:
    if db.query(Device).count() > 0:
        print("设备表已存在数据，跳过初始化")
    else:
        # owner_id 一律不传（NULL = 未绑定），be / status / handover_state
        # 由模型默认值给出：0 / 'claimable' / 'required'，
        # 正好满足 I1「无主必非 bound」。
        db.add_all(
            [
                Device(
                    device_id="PET-0001-ABCD",
                    name="桌面小狗",
                    firmware="1.0.3",
                    capability=3,
                ),
                Device(
                    device_id="PET-0002-EFGH",
                    name="备用桌宠",
                    firmware="1.0.2",
                    capability=1,
                ),
            ]
        )
        db.commit()
        print("已插入 2 台无主设备（owner_id=NULL，需通过认领流程绑定）")
finally:
    db.close()
