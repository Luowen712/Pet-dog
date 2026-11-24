"""迁移演练库工具的护栏测试。

这里只测纯函数，不连库：目的是证明"它真的会在正式库面前停下来"，
而不是靠人记得别乱敲。用 importlib 按路径导入脚本，因为 scripts/ 不是包。
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_test_db.py"

_spec = importlib.util.spec_from_file_location("migrate_test_db", SCRIPT)
assert _spec and _spec.loader, f"加载不到 {SCRIPT}"
migrate_test_db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate_test_db)

PROD_URL = "mysql+pymysql://petdog:petdog@127.0.0.1:3306/pet_dog?charset=utf8mb4"
TEST_URL = "mysql+pymysql://petdog:petdog@127.0.0.1:3306/pet_dog_test_bb00?charset=utf8mb4"



def test_db_name_of_takes_name_without_query() -> None:
    """从连接串解析库名，且不包含查询串。"""
    assert migrate_test_db.db_name_of(PROD_URL) == "pet_dog"
    assert migrate_test_db.db_name_of(TEST_URL) == "pet_dog_test_bb00"
    assert migrate_test_db.db_name_of("mysql+pymysql://u:p@h:3306/") == ""



def test_guard_rejects_production_db() -> None:
    """护栏拒绝正式库。"""
    with pytest.raises(SystemExit) as excinfo:
        migrate_test_db.assert_safe_db(PROD_URL)
    assert "正式库" in str(excinfo.value)



@pytest.mark.parametrize(
    "url",
    [
        "mysql+pymysql://u:p@127.0.0.1:3306/mysql",
        "mysql+pymysql://u:p@127.0.0.1:3306/sys",
        "mysql+pymysql://u:p@127.0.0.1:3306/information_schema",
    ],
)
def test_guard_rejects_system_schemas(url: str) -> None:
    """护栏拒绝 MySQL 自带系统库。"""
    with pytest.raises(SystemExit):
        migrate_test_db.assert_safe_db(url)



def test_guard_rejects_name_without_test_marker() -> None:
    """库名既不含 test 也不含 verify 时护栏拒绝。"""
    with pytest.raises(SystemExit) as excinfo:
        migrate_test_db.assert_safe_db(
            "mysql+pymysql://u:p@127.0.0.1:3306/pet_dog_staging"
        )
    assert "test" in str(excinfo.value)



def test_guard_accepts_isolated_db() -> None:
    """隔离库名能通过护栏校验。"""
    assert migrate_test_db.assert_safe_db(TEST_URL) == "pet_dog_test_bb00"
    assert (
        migrate_test_db.assert_safe_db("mysql+pymysql://u:p@h:3306/pet_dog_verify")
        == "pet_dog_verify"
    )



def test_resolve_rewrites_only_db_name() -> None:
    """改写测试库只换库名，主机、端口与查询串保留。"""
    got = migrate_test_db.resolve_test_url(PROD_URL)
    assert got == TEST_URL
    # host / port / 账号 / 查询串都必须原样保留
    assert "@127.0.0.1:3306/" in got
    assert got.endswith("?charset=utf8mb4")



def test_resolve_keeps_test_url_untouched() -> None:
    """已经是测试库的连接串原样返回。"""
    assert migrate_test_db.resolve_test_url(TEST_URL) == TEST_URL



def test_obfuscate_hides_password() -> None:
    """打印用连接串里的密码被替换成 ***。"""
    shown = migrate_test_db.obfuscate(PROD_URL)
    assert "petdog:***@127.0.0.1" in shown
    assert "petdog:petdog@" not in shown
