"""用真实迁移脚本验证 DDL 与 models.py 一致。

conftest 里的 drop_all/create_all 只证明 models.py 自洽，
这里换成跑 alembic 脚本，才能证明真正上线的 0001 没写错。
"""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

import app.models  # noqa: F401
from app.db import Base, engine

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

TABLES = {"command_log", "device", "face_asset", "scene", "telemetry", "user"}



def _cfg() -> Config:
    """加载 alembic 配置对象。"""
    return Config(str(ALEMBIC_INI))



def _wipe() -> None:
    """清空测试库全部表，包含 alembic_version。"""
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for tbl in inspect(conn).get_table_names():
            conn.execute(text(f"DROP TABLE IF EXISTS `{tbl}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))



def _diff() -> list:
    """返回模型与库结构的差异列表。"""
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn, opts={"compare_type": True, "compare_server_default": True}
        )
        return compare_metadata(ctx, Base.metadata)



def test_empty_db_upgrade_matches_models() -> None:
    """空库升级到 head 后，表结构与模型完全一致。"""
    _wipe()
    assert "user" not in inspect(engine).get_table_names()

    command.upgrade(_cfg(), "head")

    assert TABLES <= set(inspect(engine).get_table_names())
    assert _diff() == []



def test_existing_db_can_be_stamped() -> None:
    """老库用 stamp 接上迁移链后，结构与模型一致。"""
    _wipe()
    Base.metadata.create_all(bind=engine)

    command.stamp(_cfg(), "head")
    command.upgrade(_cfg(), "head")

    assert _diff() == []



def test_downgrade_then_upgrade_roundtrip() -> None:
    """全量回退再升级应能复原结构，验证迁移可逆。"""
    _wipe()
    command.upgrade(_cfg(), "head")
    command.downgrade(_cfg(), "base")

    assert "user" not in inspect(engine).get_table_names()

    command.upgrade(_cfg(), "head")
    assert _diff() == []