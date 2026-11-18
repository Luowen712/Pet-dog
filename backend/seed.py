"""造一个管理员账号，跑一次就够：python seed.py"""

from app.db import SessionLocal
from app.models import User
from app.security import hash_pwd

# 必须满足 10~128 位，与 /api/auth/register 同一口径。
# 否则这个脚本会造出一个「按新规则根本注册不出来」的弱密码账号，
# 而且它直接写库、不走接口，不会有任何报错。
SEED_PASSWORD = "petdog-admin-2026"


db = SessionLocal()
if not db.query(User).filter(User.username == "admin").first():
    db.add(
        User(username="admin", password_hash=hash_pwd(SEED_PASSWORD), role="admin")
    )
    db.commit()
    print(f"已创建 admin / {SEED_PASSWORD}")
else:
    print("管理员已存在")

db.close()
