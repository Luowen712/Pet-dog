"""造一个管理员账号，跑一次就够：python seed.py"""

from app import models  # noqa: F401  必须留着，否则一张表都不建
from app.db import engine, Base, SessionLocal
from app.models import User
from app.security import hash_pwd

Base.metadata.create_all(bind=engine)

db = SessionLocal()
if not db.query(User).filter(User.username == "admin").first():
    db.add(User(username="admin", password_hash=hash_pwd("admin123"), role="admin"))
    db.commit()
    print("已创建 admin / admin123")
else:
    print("管理员已存在")

db.close()
