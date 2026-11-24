"""管理员命名锁（06 §7「命名锁的可执行定义」，六条规则缺一条即视为未实现）。

为什么需要它：
    create-admin 是「先查有没有 admin，没有就建」的两步操作。两个进程同时跑，
    两边都查到「没有」，就会建出两个管理员。命名锁把这两步压成一个互斥区间。

六条规则对应到代码里的位置：
    1. 锁名常量、不拼接、≤64 字符        → ADMIN_LOCK_NAME + 模块级断言
    2. 固定专用连接、不从连接池临时取      → NullPool + 全生命周期同一条 Connection
    3. GET_LOCK 只有返回 1 才算取得        → got != 1（含 0 与 NULL）一律 fail-closed
    4. GET_LOCK/RELEASE_LOCK 严格配对      → 上下文管理器 finally 释放；
                                             RELEASE 非 1 直接 invalidate 连接
    5. P0 只支持单写 mysqld               → _assert_single_writer()
    6. 不替代 SendGate / 设备进程锁        → 本模块只做跨进程管理员计数互斥

失败一律 fail-closed：拿不到锁就不做任何写操作，绝不当作「可能已取得」继续。
"""

from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.config import settings

ADMIN_LOCK_NAME = "petdog:admin:v1"
ADMIN_LOCK_TIMEOUT = 5

# 规则 1：锁名必须是常量，且长度受 MySQL 限制（64 字符）。
assert len(ADMIN_LOCK_NAME) <= 64, "命名锁超过 MySQL 的 64 字符上限"


class HostLockError(RuntimeError):
    """拿不到锁或环境不支持。CLI 应据此退出，且不做任何写操作。"""



    def __init__(self, message: str, exit_code: int = 3):
        """记录退出码，供 CLI 拿到锁失败时直接退出使用。"""
        super().__init__(message)
        self.exit_code = exit_code



def _assert_single_writer(conn) -> None:
    """规则 5：只读副本或组复制多写时拒绝，不静默降级。

    只读实例上 GET_LOCK 能成功，但后续写会失败；组复制多写下锁只在本节点
    有效，跨节点等于没有锁。两种都必须启动即拒绝。
    """
    row = (
        conn.execute(
            text("SELECT @@global.super_read_only AS sro, @@global.read_only AS ro")
        )
        .mappings()
        .first()
    )
    if row["sro"]:
        raise HostLockError(
            "当前 mysqld 是只读实例（super_read_only=1），P0 只支持单写主库",
            exit_code=4,
        )
    if row["ro"]:
        raise HostLockError(
            "当前 mysqld 是只读实例（read_only=1），P0 只支持单写主库", exit_code=4
        )

    # 没装组复制插件时，@@global.group_replication_group_name 根本不存在，
    # 直接查会报 1193 Unknown system variable。用 SHOW VARIABLES：变量不存在
    # 时返回空结果集，不会抛异常。查不到 = 没有组复制 = 单写，放行。
    grp = conn.execute(
        text("SHOW VARIABLES LIKE 'group_replication_group_name'")
    ).first()
    if grp and grp[1]:
        raise HostLockError(
            "检测到组复制 group_replication_group_name=%s；多写会让命名锁只在"
            "本节点生效，等于没有锁" % grp[1],
            exit_code=4,
        )



@contextmanager
def admin_lock(timeout: int = ADMIN_LOCK_TIMEOUT):
    """在专用连接上取得 petdog:admin:v1，退出时严格释放。

    用法：
        with admin_lock() as conn:
            ... 只在这里做管理员计数与状态迁移 ...

    拿不到锁抛 HostLockError(exit_code=3)，调用方应直接退出，不写任何数据。
    """

    # 规则 2：NullPool 表示这条连接不来自池、也不归还池，由本函数独占。
    engine = create_engine(settings.DB_URL, poolclass=NullPool)
    conn = engine.connect()
    acquired = False
    body_error = None

    try:
        _assert_single_writer(conn)

        # 规则 3：1 = 取得；0 = 超时；NULL = 错误。后两者一律失败关闭。
        got = conn.execute(
            text("SELECT GET_LOCK(:name, :timeout)"),
            {"name": ADMIN_LOCK_NAME, "timeout": timeout},
        ).scalar()

        if got != 1:
            # 显式回滚，不留下半开的事务。
            conn.rollback()
            if got == 0:
                raise HostLockError(
                    "获取命名锁超时（%ds）：另一个 CLI 正在执行管理员操作。"
                    "请等它结束再试。" % timeout
                )
            raise HostLockError(
                "GET_LOCK 返回 %r（应为 1）：连接断开、参数非法或锁名不可用。"
                "按失败关闭处理，不做任何写操作。" % (got,)
            )

        acquired = True
        yield conn

    except BaseException as exc:
        body_error = exc
        raise

    finally:
        release_ok = True
        if acquired:
            try:
                # 规则 4：GET_LOCK 会累计计数，必须严格配对释放。
                released = conn.execute(
                    text("SELECT RELEASE_LOCK(:name)"), {"name": ADMIN_LOCK_NAME}
                ).scalar()
            except Exception:
                released = None
            if released != 1:
                # 0 = 不是持有者；NULL = 连接已断。两种都说明连接状态不可信。
                release_ok = False
                try:
                    conn.invalidate()
                except Exception:
                    pass

        try:
            conn.close()
        except Exception:
            pass
        engine.dispose()

        if not release_ok and body_error is None:
            raise HostLockError(
                "RELEASE_LOCK 未返回 1（0=不是持有者，NULL=连接已断），"
                "已销毁该连接；不要复用它继续操作。"
            )
