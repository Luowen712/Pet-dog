import os

TEST_DB = "pet_dog_test_bb00"

# ① 先改环境变量，再 import 任何 app 模块
os.environ["DB_URL"] = (
    f"mysql+pymysql://petdog:petdog@127.0.0.1:3306/{TEST_DB}?charset=utf8mb4"
)
os.environ["SERIAL_PORT"] = "loop://"

# ② 保险丝：检 settings 实际读到的值，不是上面那个常量
from app.config import settings  # noqa: E402

assert "test" in TEST_DB, "测试库名必须含 test"
assert (
    settings.DB_URL == os.environ["DB_URL"]
), f"DB_URL 覆盖失败，实际连的是 {settings.DB_URL}"
assert "pet_dog_test" in settings.DB_URL, "拒绝在非测试库上跑测试"

# ③ 库已由 root 建好并授权，这里只负责把表清空重建
import app.models  # noqa: E402,F401
from app.db import Base, engine  # noqa: E402

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
