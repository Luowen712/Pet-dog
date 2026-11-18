"""主机锁与 CLI 的测试（BB02 第 3、4 条）。

为什么锁要单独测：
    create-admin 要求真人在 TTY 里敲密码（第 4 条五步判定），
    所以自动测试没法完整跑一遍建管理员。但「并发只成功一次」的关键
    在锁上，锁是可以用代码验证的——拿两个独立连接同时抢。

为什么终端判定也要测：
    这五步是硬要求，少一条就会出现「echo 密码 | python cli.py」这种
    把密码写进管道、还可能被回显的用法。测试要证明它在非 TTY 下真的拒绝。
"""

import threading

import pytest

import cli
from app.db import SessionLocal
from app.hostlock import ADMIN_LOCK_NAME, HostLockError, admin_lock
from app.models import User
from app.security import verify_pwd


def test_lock_name_is_the_contracted_constant():
    """规则 1：锁名是常量、不拼接、长度 ≤ 64。"""
    assert ADMIN_LOCK_NAME == "petdog:admin:v1"
    assert len(ADMIN_LOCK_NAME) <= 64


def test_second_holder_is_rejected_while_held():
    """规则 3：已被占用时 GET_LOCK 返回 0，必须失败关闭（退出码 3）。"""
    with admin_lock(timeout=0):
        with pytest.raises(HostLockError) as ei:
            with admin_lock(timeout=0):
                pass
    assert ei.value.exit_code == 3


def test_lock_can_be_reacquired_after_release():
    """规则 4：释放后能重新取得——证明 RELEASE_LOCK 真的生效、没泄漏。"""
    with admin_lock(timeout=0):
        pass
    with admin_lock(timeout=0):
        pass


def test_concurrent_callers_serialize_not_interleave():
    """两个线程同时抢锁（timeout 足够大）→ 都成功，但严格串行不重叠。"""
    inside = []
    overlap = []
    start = threading.Barrier(2)

    def worker(name):
        start.wait()
        with admin_lock(timeout=5):
            if inside:
                overlap.append((name, list(inside)))
            inside.append(name)
            # 持有期间让另一个线程也进入尝试
            threading.Event().wait(0.2)
            inside.remove(name)

    ts = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b")]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=15)

    assert overlap == [], "两个线程同时处于锁内，说明互斥失效：%r" % (overlap,)


def test_single_writer_check_passes_on_local_mysql():
    """规则 5：本地单写 mysqld 应当能通过；只读/组复制才拒绝。"""
    with admin_lock(timeout=2) as conn:
        assert conn is not None


def test_cli_rejects_non_tty():
    """第 4 条 ①~③：pytest 环境下 stdin 不是 TTY，必须拒绝读密码。"""
    with pytest.raises(cli.CliError):
        cli._assert_interactive_terminal()


def test_cli_password_length_is_validated():
    """密码 10–128 位与注册口径一致。"""
    cli._validate_password("1234567890")

    with pytest.raises(cli.CliError):
        cli._validate_password("123456789")

    with pytest.raises(cli.CliError):
        cli._validate_password("x" * 129)


def test_cli_usage_exit_code():
    assert cli.main([]) == 2
    assert cli.main(["unknown-command"]) == 2
    assert cli.main(["create-admin"]) == 2
    assert cli.main(["list-admin", "extra"]) == 2


# --- 以下用 monkeypatch 顶掉密码读取，专测「拿到密码之后」的那段 ---
# 终端判定本身由 test_cli_rejects_non_tty 覆盖；这里要验证的是
# 「算哈希 → 拿锁 → 查重 → 写库」整条路径真的能走通并落库。

CLI_USER = "cli_probe"
CLI_PW = "cli-pw-9f2c"


def _purge_cli_user() -> None:
    db = SessionLocal()
    try:
        db.query(User).filter(User.username == CLI_USER).delete()
        db.commit()
    finally:
        db.close()


def test_create_admin_writes_user(monkeypatch):
    """create-admin 成功路径：落库的账号必须是 admin + active，且密码可验证。"""
    _purge_cli_user()
    monkeypatch.setattr(cli, "_read_password", lambda prompt="密码: ": CLI_PW)
    try:
        assert cli.main(["create-admin", CLI_USER]) == 0

        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == CLI_USER).first()
            assert u is not None, "命令返回 0 却没有落库"
            assert u.role == "admin"
            assert u.status == "active"
            assert u.token_version == 0
            assert verify_pwd(u.password_hash, CLI_PW), "存进去的不是这个密码"
        finally:
            db.close()
    finally:
        _purge_cli_user()


def test_create_admin_duplicate_is_refused(monkeypatch):
    """重名必须拒绝（退出码 2），且不能建出第二行。"""
    _purge_cli_user()
    monkeypatch.setattr(cli, "_read_password", lambda prompt="密码: ": CLI_PW)
    try:
        assert cli.main(["create-admin", CLI_USER]) == 0
        assert cli.main(["create-admin", CLI_USER]) == 2

        db = SessionLocal()
        try:
            n = db.query(User).filter(User.username == CLI_USER).count()
        finally:
            db.close()
        assert n == 1, "重名时建出了 %d 行" % n
    finally:
        _purge_cli_user()


def test_reset_bumps_token_version_and_changes_password(monkeypatch):
    """reset 两个副作用都不能少：换哈希 + token_version+1（踢旧 token）。"""
    _purge_cli_user()
    db = SessionLocal()
    try:
        u = User(username=CLI_USER, password_hash=cli.hash_pwd("old-pw-1234"), role="admin")
        db.add(u)
        db.commit()
        before_tv = u.token_version
        before_hash = u.password_hash
    finally:
        db.close()

    new_pw = "new-pw-5678"
    monkeypatch.setattr(cli, "_read_password", lambda prompt="密码: ": new_pw)
    try:
        assert cli.main(["reset", CLI_USER]) == 0

        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == CLI_USER).first()
            assert u.token_version == before_tv + 1, "token_version 没 +1，旧 token 仍可用"
            assert u.password_hash != before_hash
            assert verify_pwd(u.password_hash, new_pw)
            assert not verify_pwd(u.password_hash, "old-pw-1234")
        finally:
            db.close()
    finally:
        _purge_cli_user()
