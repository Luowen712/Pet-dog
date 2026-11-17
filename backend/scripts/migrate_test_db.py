"""BB01 迁移演练库工具：只在隔离测试库上跑迁移，永远不会连到正式库。

为什么需要它
------------
backend/.env 里的 DB_URL 指向正式库 pet_dog（那上面有真实账号和设备）。
直接敲 alembic upgrade，迁移就落在正式库上，而且 ALTER TABLE 会锁表。
本脚本在动任何 DDL 之前，先把"要连哪个库"算出来、打印出来、断言一遍；
算出来的库名不含 test / verify 就直接退出，一个语句都不发。

用法（cmd 和 bash 一样，在 backend 目录下执行）
----------------------------------------------
    .venv\\Scripts\\python.exe scripts\\migrate_test_db.py current
        看测试库当前停在哪个 revision。

    .venv\\Scripts\\python.exe scripts\\migrate_test_db.py reset
        清空测试库（含 alembic_version）再从零升到 head。
        这是"新库完整 upgrade"那条路径，autogenerate 之前也用它铺底。

    .venv\\Scripts\\python.exe scripts\\migrate_test_db.py reset --to 0001
        只升到 0001。写 0002 之前需要这个基准：库停在 0001，
        models.py 里多出来的列/表才会被 autogenerate 看见。

    .venv\\Scripts\\python.exe scripts\\migrate_test_db.py stamp --to 0001
        按 models.py 直接建表，然后 stamp 到指定版本。
        模拟"老库已经有表、不想重跑建表脚本"那条路径（BB01 第 2 步的第二条路径）。

    .venv\\Scripts\\python.exe scripts\\migrate_test_db.py tables
        列出表名和当前 revision，方便截图留证。

护栏（三层，任一层不过就退出）
------------------------------
1. 库名等于 pet_dog / mysql / sys / information_schema 等，拒绝。
2. 库名既不含 test 也不含 verify，拒绝。
3. DB_URL 从环境变量读；没设就读 backend/.env（不依赖当前工作目录）。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

BACKEND = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND / ".env"
ALEMBIC_INI = BACKEND / "alembic.ini"

# 默认演练库：和 tests/conftest.py 用的是同一个，避免第二套库名各自为政
DEFAULT_TEST_DB = "pet_dog_test_bb00"

# 这些库名一律拒绝：正式库 + MySQL 自带的系统库
FORBIDDEN_DB_NAMES = {
    "pet_dog",
    "mysql",
    "sys",
    "information_schema",
    "performance_schema",
}


def log(msg: str) -> None:
    """逐行落地输出。

    alembic 的 INFO 日志走 stderr，print 走 stdout 且有缓冲；
    重定向到文件时两者顺序会乱，显式 flush 才能让日志按发生顺序排好。
    """
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------- 纯函数部分
# 这一节不连库、不 import app，方便被 tests/ 直接引用做单测。


def db_name_of(url: str) -> str:
    """从 SQLAlchemy URL 里取出库名。取不到返回空串。"""
    path = urlparse(url).path.lstrip("/")
    return path.split("?")[0].strip()


def assert_safe_db(url: str) -> str:
    """护栏：不是测试库就抛 SystemExit，返回库名。"""
    name = db_name_of(url)
    if not name:
        raise SystemExit(f"[拒绝] 从 DB_URL 里取不到库名：{url}")
    if name in FORBIDDEN_DB_NAMES:
        raise SystemExit(
            f"[拒绝] {name} 是正式库或系统库，本脚本不允许对它执行任何 DDL。\n"
            f"       DB_URL = {url}"
        )
    if "test" not in name and "verify" not in name:
        raise SystemExit(
            f"[拒绝] 库名 {name} 既不含 test 也不含 verify，不认为是隔离库。\n"
            f"       DB_URL = {url}"
        )
    return name


def resolve_test_url(raw_url: str, test_db: str = DEFAULT_TEST_DB) -> str:
    """把正式库 URL 换成同名同主的测试库 URL；已经是测试库就原样返回。

    只改路径里的库名，host / port / 账号 / 密码 / 查询串全部保留。
    """
    name = db_name_of(raw_url)
    if "test" in name or "verify" in name:
        return raw_url
    parsed = urlparse(raw_url)
    suffix = parsed.path[len(name) + 1 :] if name else ""  # 保留 ?charset=utf8mb4
    new_path = f"/{test_db}{suffix}"
    return urlunparse(parsed._replace(path=new_path))


# ---------------------------------------------------------------- 取配置


def read_raw_db_url() -> str:
    """优先环境变量，其次 backend/.env。不 import app，避免 settings 提前缓存。"""
    env_value = os.environ.get("DB_URL", "").strip()
    if env_value:
        return env_value

    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "DB_URL":
                return value.strip().strip('"').strip("'")

    raise SystemExit(
        f"[拒绝] 找不到 DB_URL：环境变量没有，{ENV_FILE} 里也没有。\n"
        f"       请在 backend/.env 里补一行 DB_URL=..."
    )


def bind_test_db() -> str:
    """算出目标测试库并写回环境变量，之后再 import app 才读得到。"""
    test_db = os.environ.get("TEST_DB_NAME", DEFAULT_TEST_DB).strip() or DEFAULT_TEST_DB
    raw = read_raw_db_url()
    url = resolve_test_url(raw, test_db)
    name = assert_safe_db(url)

    # 关键顺序：先落环境变量，再让 app.config 去读
    os.environ["DB_URL"] = url

    log(f"[目标库] {name}")
    log(f"[连接串] {obfuscate(url)}")
    if db_name_of(raw) != name:
        log(f"[换算] 原 DB_URL 指向 {db_name_of(raw)}，已改写到隔离库 {name}")
    return url


def obfuscate(url: str) -> str:
    """打印用：把密码换成 ***。"""
    parsed = urlparse(url)
    if not parsed.password:
        return url
    netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@", 1)
    return urlunparse(parsed._replace(netloc=netloc))


# ---------------------------------------------------------------- 连库动作


def get_engine():
    """import 必须在 bind_test_db() 之后，否则 engine 会绑到正式库。"""
    sys.path.insert(0, str(BACKEND))
    from app.db import engine  # noqa: E402

    return engine


def get_alembic_config():
    from alembic.config import Config  # noqa: E402

    if not ALEMBIC_INI.exists():
        raise SystemExit(f"[拒绝] 找不到 {ALEMBIC_INI}")
    return Config(str(ALEMBIC_INI))


def drop_everything(engine) -> list[str]:
    """删掉目标库里所有表（含 alembic_version）。

    MySQL 的 DDL 会隐式提交，所以 FOREIGN_KEY_CHECKS 必须挂在同一条原生连接上，
    不能放进 engine.begin() 的事务里，否则关不掉外键检查、删表会被 FK 挡住。
    """
    from sqlalchemy import inspect  # noqa: E402

    names = inspect(engine).get_table_names()
    if not names:
        log("[清空] 目标库本来就没有表")
        return []

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        try:
            cur.execute("SET FOREIGN_KEY_CHECKS=0")
            for name in names:
                cur.execute(f"DROP TABLE IF EXISTS `{name}`")
            cur.execute("SET FOREIGN_KEY_CHECKS=1")
        finally:
            cur.close()
        raw.commit()
    finally:
        raw.close()

    log(f"[清空] 已删除 {len(names)} 张表：{', '.join(sorted(names))}")
    return names


def show_state(engine) -> None:
    from alembic.runtime.migration import MigrationContext  # noqa: E402
    from sqlalchemy import inspect  # noqa: E402

    tables = sorted(inspect(engine).get_table_names())
    with engine.connect() as conn:
        revision = MigrationContext.configure(conn).get_current_revision()

    log(f"[revision] {revision or '(空，未纳入迁移管理)'}")
    log(f"[表] {len(tables)} 张：{', '.join(tables) if tables else '(无)'}")


# ---------------------------------------------------------------- 子命令


def cmd_current(engine, args) -> None:
    show_state(engine)


def cmd_tables(engine, args) -> None:
    show_state(engine)


def cmd_reset(engine, args) -> None:
    from alembic import command  # noqa: E402

    drop_everything(engine)
    cfg = get_alembic_config()
    command.upgrade(cfg, args.to)
    log(f"[完成] 已从零 upgrade 到 {args.to}")
    show_state(engine)


def cmd_upgrade(engine, args) -> None:
    from alembic import command  # noqa: E402

    command.upgrade(get_alembic_config(), args.to)
    log(f"[完成] 已 upgrade 到 {args.to}")
    show_state(engine)


def cmd_downgrade(engine, args) -> None:
    """回退到指定 revision，会执行该版本的 downgrade()。"""
    from alembic import command  # noqa: E402

    from alembic.util.exc import CommandError  # noqa: E402

    try:
        command.downgrade(get_alembic_config(), args.to)
    except CommandError as exc:
        raise SystemExit(f"[失败] {exc}") from exc
    log(f"[完成] 已 downgrade 到 {args.to}")
    show_state(engine)


def cmd_stamp(engine, args) -> None:
    """老库路径：按 models.py 建表，再假装它已经走过指定版本的迁移。"""
    from alembic import command  # noqa: E402
    from app.db import Base  # noqa: E402
    import app.models  # noqa: E402,F401

    drop_everything(engine)
    Base.metadata.create_all(bind=engine)
    log("[建表] 已按 models.py 直接建表（等价于老库现状）")

    command.stamp(get_alembic_config(), args.to)
    log(f"[完成] 已 stamp 到 {args.to}（没有真正执行该版本的 DDL）")
    show_state(engine)


def inspect_versions(cfg, engine) -> tuple[str | None, set[str]]:
    """返回（库里当前 revision，脚本目录里的 head 集合）。"""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    heads = set(ScriptDirectory.from_config(cfg).get_heads())
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return current, heads


def cmd_revision(engine, args) -> None:
    """对着测试库生成迁移脚本草稿。

    必须连库：autogenerate 的工作原理是"把 models 和库里的实际结构做差集"，
    没有库就没有基线。连正式库也能生成，但那时差集混着真实数据的历史噪声，
    所以统一走测试库。
    """
    from alembic import command
    from alembic.util import CommandError  # noqa: E402

    cfg = get_alembic_config()

    # 先自检：脚本 head 和库里的版本对不上时，alembic 只会抛一句
    # "Target database is not up to date."，看不出到底该做什么。这里翻译成人话。
    current, heads = inspect_versions(cfg, engine)
    if current not in heads:
        raise SystemExit(
            f"[拒绝] 库里的版本和脚本的 head 对不上，生成出来也是错的差集。\n"
            f"       库当前 revision：{current or '(空)'}\n"
            f"       脚本 head：{', '.join(sorted(heads)) or '(无)'}\n"
            f"       常见原因：某个迁移脚本已经生成、但还没执行到库里。\n"
            f"       处理办法二选一：\n"
            f"         a) 先把它执行掉：python scripts/migrate_test_db.py upgrade --to {sorted(heads)[-1] if heads else 'head'}\n"
            f"         b) 想重来：python scripts/migrate_test_db.py reset --to {current or '0001'}"
        )

    try:
        script = command.revision(
            cfg,
            message=args.message,
            autogenerate=not args.no_autogenerate,
            rev_id=args.rev_id,
        )
    except CommandError as exc:
        raise SystemExit(f"[失败] {exc}") from exc

    log(f"[生成] {script.path}")
    log("[下一步] 打开这个文件逐行审，不要直接 upgrade。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="隔离测试库的迁移演练工具（拒绝连接正式库）",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    for name, help_text in (
        ("current", "查看测试库当前 revision"),
        ("tables", "列出表与 revision"),
    ):
        sub.add_parser(name, help=help_text)

    p_reset = sub.add_parser("reset", help="清空测试库并从零 upgrade")
    p_reset.add_argument("--to", default="head", help="目标 revision，默认 head")

    p_up = sub.add_parser("upgrade", help="在现有库上 upgrade（不清空）")
    p_up.add_argument("--to", default="head", help="目标 revision，默认 head")

    p_down = sub.add_parser("downgrade", help="在现有库上回退到指定 revision（不清空）")
    p_down.add_argument("--to", required=True, help="目标 revision，如 0004")

    p_stamp = sub.add_parser("stamp", help="按 models 建表后 stamp（模拟老库）")
    p_stamp.add_argument("--to", default="0001", help="stamp 到的 revision，默认 0001")

    p_rev = sub.add_parser("revision", help="对着测试库生成迁移脚本（默认 autogenerate）")
    p_rev.add_argument("-m", "--message", required=True, help="迁移说明，建议用英文，文件名会用到")
    p_rev.add_argument(
        "--rev-id",
        dest="rev_id",
        default=None,
        help="手工指定版本号，如 0002。不指定则生成随机 hash",
    )
    p_rev.add_argument(
        "--no-autogenerate",
        action="store_true",
        help="生成空模板，不比对库结构",
    )

    return parser


HANDLERS = {
    "current": cmd_current,
    "tables": cmd_tables,
    "reset": cmd_reset,
    "upgrade": cmd_upgrade,
    "downgrade": cmd_downgrade,
    "stamp": cmd_stamp,
    "revision": cmd_revision,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bind_test_db()  # 先过护栏，再过任何 app 模块
    engine = get_engine()
    try:
        HANDLERS[args.action](engine, args)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
