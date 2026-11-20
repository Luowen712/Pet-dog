"""进程锁的验收测试：BA02 完成判据一"重复启动被拒"的最小证据。

每个测试用独立锁名，绝不碰真实的 petdog:instance —— 否则一个测试没释放，
后面 60 多个测试会集体假红，而且报错信息完全指不到凶手。
"""

import threading
import time
import uuid

import pytest
from sqlalchemy import create_engine, text

from app.config import settings
from app.link.lock import HostProcessLock, LOCK_NAME, LockUnavailable, ProcessLock


@pytest.fixture
def lock_name() -> str:
    return "petdog:test:" + uuid.uuid4().hex[:12]


@pytest.fixture
def db_url() -> str:
    return settings.DB_URL


def test_lock_name_is_the_contract_constant():
    """锁名是契约常量，不能带版本后缀。

    v3.1 和 v3.2 的后端同样不能共享一个串口，给锁名加版本号会让新旧版本
    互相看不见对方，正好漏掉该拦的情况。
    """
    assert LOCK_NAME == "petdog:instance"


def test_first_instance_acquires(lock_name, db_url):
    lock = ProcessLock(lock_name, db_url)
    try:
        lock.acquire()
        assert lock.still_held() is True
        assert lock.holder_id is not None
    finally:
        lock.release()


def test_second_instance_is_rejected(lock_name, db_url):
    """重复启动必须直接失败，且报错里要有占用者，便于运维定位。"""
    holder = ProcessLock(lock_name, db_url)
    holder.acquire()
    try:
        intruder = ProcessLock(lock_name, db_url)
        with pytest.raises(LockUnavailable) as exc:
            intruder.acquire()
        assert str(holder.holder_id) in str(exc.value)
    finally:
        holder.release()


def test_failed_acquire_leaves_no_residue(lock_name, db_url):
    """抢锁失败的那一方要自己收拾干净，不能把连接漏在 MySQL 里。"""
    holder = ProcessLock(lock_name, db_url)
    holder.acquire()
    try:
        with pytest.raises(LockUnavailable):
            ProcessLock(lock_name, db_url).acquire()
    finally:
        holder.release()
    successor = ProcessLock(lock_name, db_url)
    try:
        successor.acquire()
        assert successor.still_held() is True
    finally:
        successor.release()


def test_release_lets_another_instance_in(lock_name, db_url):
    """release 必须真的释放物理连接上的锁，而不是只把对象字段清空。"""
    first = ProcessLock(lock_name, db_url)
    first.acquire()
    first.release()
    second = ProcessLock(lock_name, db_url)
    try:
        second.acquire()
        assert second.still_held() is True
    finally:
        second.release()


def test_release_is_idempotent(lock_name, db_url):
    """关闭路径上有多个出口，release 会被调多次，不能抛。"""
    lock = ProcessLock(lock_name, db_url)
    lock.release()
    lock.acquire()
    lock.release()
    lock.release()


def test_still_held_is_false_before_acquire(lock_name, db_url):
    """没拿到锁时不能谎报 held，否则健康检查形同虚设。"""
    assert ProcessLock(lock_name, db_url).still_held() is False


def test_double_acquire_is_a_programming_error(lock_name, db_url):
    """同一对象重复 acquire 会累计 MySQL 的锁计数，必须当场炸掉。"""
    lock = ProcessLock(lock_name, db_url)
    try:
        lock.acquire()
        with pytest.raises(RuntimeError):
            lock.acquire()
    finally:
        lock.release()


def test_lock_unavailable_is_not_a_runtime_error():
    """两种失败必须能分开：锁被占 vs 自己写错。

    如果 LockUnavailable 继承 RuntimeError，上层 except RuntimeError 会把
    "别的后端在跑"当成代码 bug 吞掉，运维就再也看不到占用者了。
    """
    assert not issubclass(LockUnavailable, RuntimeError)
    assert issubclass(LockUnavailable, Exception)


def test_still_held_survives_concurrent_callers(lock_name, db_url):
    """写线程和 HTTP 线程会同时问"锁还在吗"。

    持锁连接不是线程安全的：四个线程共用它查询时，实测 188052 次里 188051
    次误报 False。按 BA02 判据三，误报一次就要停发送并退出。
    """
    lock = ProcessLock(lock_name, db_url)
    lock.acquire()
    answers: list[bool] = []
    stop = threading.Event()

    def ask() -> None:
        while not stop.is_set():
            answers.append(lock.still_held())

    threads = [threading.Thread(target=ask) for _ in range(4)]
    try:
        for thread in threads:
            thread.start()
        time.sleep(0.5)
        stop.set()
        for thread in threads:
            thread.join()
    finally:
        lock.release()
    assert len(answers) > 100
    assert all(answers), f"{answers.count(False)}/{len(answers)} 次误报锁已丢失"


def test_still_held_is_false_after_connection_dies(lock_name, db_url):
    """BA02 判据三：DB 锁连接丢失必须能被发现。

    用 KILL 杀掉持锁连接，模拟 MySQL 侧断链。这一步只在有 PROCESS 权限的
    账号上可行；拿不到权限就跳过，不要改成断言"能杀"。
    """
    lock = ProcessLock(lock_name, db_url)
    lock.acquire()
    holder_id = lock.holder_id
    killer = create_engine(db_url)
    try:
        try:
            with killer.connect() as conn:
                conn.execute(text("KILL :i").bindparams(i=holder_id))
        except Exception:
            pytest.skip("当前账号没有 KILL 权限，无法模拟断链")
    finally:
        killer.dispose()
    try:
        assert lock.still_held() is False
        lock.release()  # 连接已死，release 必须静默成功
    finally:
        successor = ProcessLock(lock_name, db_url)
        successor.acquire()
        successor.release()


def test_host_lock_rejects_second_holder_and_releases(tmp_path):
    """主机排他文件锁：第二个持有者立即被拒，释放后可重新取得。"""
    lock_file = tmp_path / "host.lock"
    first = HostProcessLock(lock_file)
    second = HostProcessLock(lock_file)

    first.acquire()
    try:
        assert first.still_held() is True
        with pytest.raises(LockUnavailable):
            second.acquire()
        assert second.still_held() is False
    finally:
        first.release()

    assert first.still_held() is False
    second.acquire()
    try:
        assert second.still_held() is True
    finally:
        second.release()


def test_host_lock_double_acquire_and_idempotent_release(tmp_path):
    lock = HostProcessLock(tmp_path / "host2.lock")
    lock.release()  # 未取得前 release 不报错
    lock.acquire()
    try:
        with pytest.raises(RuntimeError):
            lock.acquire()
    finally:
        lock.release()
        lock.release()
