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
    return Config(str(ALEMBIC_INI))


def _wipe() -> None:
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


def _diff() -> list:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn, opts={"compare_type": True, "compare_server_default": True}
        )
        return compare_metadata(ctx, Base.metadata)


def test_empty_db_upgrade_matches_models() -> None:
    _wipe()
    assert "user" not in inspect(engine).get_table_names()

    command.upgrade(_cfg(), "head")

    assert TABLES <= set(inspect(engine).get_table_names())
    assert _diff() == []


def test_existing_db_can_be_stamped() -> None:
    _wipe()
    Base.metadata.create_all(bind=engine)

    command.stamp(_cfg(), "head")
    command.upgrade(_cfg(), "head")

    assert _diff() == []


def test_downgrade_then_upgrade_roundtrip() -> None:
    _wipe()
    command.upgrade(_cfg(), "head")
    command.downgrade(_cfg(), "base")

    assert "user" not in inspect(engine).get_table_names()

    command.upgrade(_cfg(), "head")
    assert _diff() == []