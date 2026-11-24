"""隔离测试库 fixture：保证 pytest 永远只在 pet_dog_test_bb00 上跑。

顺序是硬的，不能调：
  ① 先算目标库 URL 并写进环境变量（此时还没 import 任何 app 模块）
  ② 再 import app.config，让 settings 读到刚写进去的值
  ③ 断言 settings 真的读到了，而不是回落到 .env 里的正式库
  ④ 清表重建

库名判定与 URL 改写复用 scripts/migrate_test_db.py 里的同一份实现，
不在这里另写一套 —— 测试和迁移工具对"什么算测试库"必须只有一个答案。
"""

import importlib.util
import os
from pathlib import Path

TEST_DB = "pet_dog_test_bb00"
BACKEND = Path(__file__).resolve().parents[1]
TOOL_PATH = BACKEND / "scripts" / "migrate_test_db.py"



def _load_tool():
    """按文件路径加载迁移工具模块，供护栏函数单测复用。"""
    spec = importlib.util.spec_from_file_location("migrate_test_db", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"加载不到迁移工具：{TOOL_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load_tool()

# ① 正式库 URL（.env 或环境变量）→ 只换库名 → 写回环境变量
os.environ["DB_URL"] = tool.resolve_test_url(tool.read_raw_db_url(), TEST_DB)
tool.assert_safe_db(os.environ["DB_URL"])
os.environ["SERIAL_PORT"] = "loop://"
os.environ["DEV_BENCH_CONTROL"] = "false"

# ② 现在才 import app.config
from app.config import settings  # noqa: E402

# ③ 保险丝：查 settings 实际读到的值，不是上面那行拼出来的常量
assert settings.DB_URL == os.environ["DB_URL"], (
    f"DB_URL 覆盖失败，settings 实际连的是 {settings.DB_URL}"
)
assert tool.db_name_of(settings.DB_URL) == TEST_DB, (
    f"拒绝在非测试库上跑测试，当前库是 {tool.db_name_of(settings.DB_URL)}"
)
assert tool.db_name_of(settings.DB_URL) not in tool.FORBIDDEN_DB_NAMES

# ④ 库已由 root 建好并授权，这里只负责把测试库所有旧表清空重建（含历史已移除的表）
from sqlalchemy import inspect, text  # noqa: E402

import app.models  # noqa: E402,F401
from app.db import engine  # noqa: E402

with engine.begin() as conn:
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    for tbl in inspect(conn).get_table_names():
        conn.execute(text(f"DROP TABLE IF EXISTS `{tbl}`"))
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
from alembic import command
from alembic.config import Config

command.upgrade(Config(str(BACKEND / 'alembic.ini')), 'head')

# ⑤ 每个用例前后清空限流桶。
# 限流器是进程内全局状态，而 TestClient 的来源 IP 固定为 "testclient"，
# 不清的话上个用例打满的桶会带到下一个用例，表现为「单跑通过、全量失败」。
import pytest  # noqa: E402

from app import ratelimit  # noqa: E402



@pytest.fixture(autouse=True)
def _reset_ratelimit():
    """每个用例前后都清空限流计数，避免互相干扰。"""
    ratelimit.reset()
    yield
    ratelimit.reset()
