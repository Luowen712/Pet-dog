"""进程级互斥锁：保证同一台机器上只有一个后端实例在写串口。

为什么必须用独立的 engine 和 NullPool：
    SQLAlchemy 的连接池会让 Connection.close() 只归还物理连接。MySQL 命名锁
    挂在会话上，会话还在，锁就还在。用池化引擎拿锁，锁可能长在别处、被
    pool_recycle 回收掉，而进程依然活着 —— 第二个进程于是能启动。

为什么持锁连接用 AUTOCOMMIT：
    默认隔离级别下，第一条 SELECT 就在服务端开了一个事务并一直开着。持锁连接
    要活整个进程生命周期，等于把事务也开一整个进程生命周期。

为什么 still_held() 外面加一把 threading.Lock：
    持锁那根 DB 连接不是线程安全的。写线程和 HTTP 线程同时查它，会看到连接
    内部状态被互相踩坏 —— 实测四个线程并发调用，188052 次里 188051 次误报
    锁已丢失，足以让后端自己停掉发送。这把锁只在进程内、只护这一根连接。

接口纪律（对应 06:196、06:200、BA02 完成判据三）：
    只有 GET_LOCK 返回 1 才算取得，0 和 NULL 都失败关闭；
    still_held() 是"DB 锁连接丢失就停止发送并退出"的唯一触发器。
"""

import os
import tempfile
import threading
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

if os.name == "nt":
    import msvcrt
else:
    import fcntl

LOCK_NAME = "petdog:instance"
DEFAULT_HOST_LOCK_PATH = Path(tempfile.gettempdir()) / "petdog-host.lock"


class LockUnavailable(Exception):
    """拿不到锁。消息里带占用者的连接号，便于告诉运维先停哪个后端。

    故意不继承 RuntimeError：acquire() 的编程错误（重复加锁）和"锁被别人
    占着"是两件完全不同的事，测试和上层 except 必须能把它们分开。
    """


class ProcessLock:
    """一把 MySQL 命名锁，独占一根不归还连接池的物理连接。"""



    def __init__(self, name: str = LOCK_NAME, db_url: str | None = None) -> None:
        """记录锁名与数据库地址，物理连接留到 acquire 时再建。"""
        if db_url is None:
            from app.config import settings

            db_url = settings.DB_URL
        self._name = name
        self._db_url = db_url
        self._engine = None
        self._conn = None
        self._holder_id: int | None = None
        self._mu = threading.Lock()



    @property
    def holder_id(self) -> int | None:
        """取得锁时自己的 CONNECTION_ID()，没拿到为 None。"""
        return self._holder_id



    def acquire(self) -> None:
        """建独立 AUTOCOMMIT 连接并取 GET_LOCK；单写校验不过或锁被占用即抛 LockUnavailable。"""
        with self._mu:
            if self._conn is not None:
                raise RuntimeError(f"锁 {self._name} 已在本对象上取得，不要重复 acquire")
            engine = create_engine(
                self._db_url, poolclass=NullPool, isolation_level="AUTOCOMMIT"
            )
            conn = None
            try:
                conn = engine.connect()
                # 06:199 单写者 mysqld 校验：只读副本或组复制不允许持有唯一实例锁
                for var in ("super_read_only", "read_only"):
                    row = conn.execute(
                        text(f"SHOW VARIABLES LIKE '{var}'")
                    ).fetchone()
                    if row and str(row[1]).upper() in ("ON", "1"):
                        raise LockUnavailable(
                            f"数据库处于 {var}=ON，禁止启动唯一后端实例"
                        )
                gr = conn.execute(
                    text("SHOW VARIABLES LIKE 'group_replication_group_name'")
                ).fetchone()
                if gr and str(gr[1]).strip():
                    raise LockUnavailable(
                        "数据库启用了 Group Replication，禁止依赖单实例命名锁启动"
                    )
                got = conn.execute(
                    text("SELECT GET_LOCK(:n, 0)"), {"n": self._name}
                ).scalar()
                if got != 1:
                    who = conn.execute(
                        text("SELECT IS_USED_LOCK(:n)"), {"n": self._name}
                    ).scalar()
                    raise LockUnavailable(
                        f"锁 {self._name} 已被数据库连接 {who} 占用，先停掉那个后端"
                    )
                self._holder_id = conn.execute(text("SELECT CONNECTION_ID()")).scalar()
            except BaseException:
                if conn is not None:
                    _quiet(conn.close)
                _quiet(engine.dispose)
                self._holder_id = None
                raise
            self._engine = engine
            self._conn = conn



    def still_held(self) -> bool:
        """每次发送前调用。连接断了也算丢锁，不抛异常。"""
        with self._mu:
            if self._conn is None or self._holder_id is None:
                return False
            try:
                holder = self._conn.execute(
                    text("SELECT IS_USED_LOCK(:n)"), {"n": self._name}
                ).scalar()
            except Exception:
                return False
            return holder == self._holder_id



    def release(self) -> None:
        """幂等：没取得过、已释放过、连接已死，都静默成功。

        RELEASE_LOCK 也在锁内做完：若在字段清空后就放开互斥，另一个线程的
        acquire() 会抢在真释放之前撞上 GET_LOCK 返回 0，把"自己还没放完"
        误报成"别人占着"。
        """
        with self._mu:
            conn, engine = self._conn, self._engine
            self._conn = None
            self._engine = None
            self._holder_id = None
            if conn is not None:
                _quiet(
                    lambda: conn.execute(
                        text("SELECT RELEASE_LOCK(:n)"), {"n": self._name}
                    )
                )
                _quiet(conn.close)
            if engine is not None:
                _quiet(engine.dispose)


class HostProcessLock:
    """本机排他进程锁（BA02 第 1 条 / 06 §7）：比 DB 锁更早拦住重复启动与并发 CLI。

    为什么有了 MySQL 命名锁（ProcessLock）还要一把本机文件锁：
        1. 串口/蓝牙 COM 口是挂在「这台机器」上的硬件资源，哪怕两份配置指到了
           不同的数据库，同一台主机上也不能同时起两个后端或边跑后端边跑改状态 CLI；
        2. 文件锁由操作系统内核托管，进程被 kill / 断电崩溃后内核自动收回，
           不会留下需要手工删掉的「死锁文件」。
    """



    def __init__(self, path: Path | str | None = None) -> None:
        """记录锁文件路径，文件描述符留到 acquire 时再打开。"""
        self._path = Path(path) if path is not None else DEFAULT_HOST_LOCK_PATH
        self._fd: int | None = None
        self._mu = threading.Lock()



    @property
    def path(self) -> Path:
        """返回主机锁文件所在路径。"""
        return self._path



    def acquire(self) -> None:
        """打开锁文件并加非阻塞排他锁，已被占用则抛 LockUnavailable。"""
        with self._mu:
            if self._fd is not None:
                raise RuntimeError(f"主机锁 {self._path} 已在本对象上取得，不要重复 acquire")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
            fd = os.open(str(self._path), flags)
            try:
                if os.name == "nt":
                    # 确保文件至少有 1 字节，再在偏移 0 处加非阻塞排他锁
                    if os.fstat(fd).st_size == 0:
                        os.write(fd, b"0")
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                _quiet(lambda: os.close(fd))
                raise LockUnavailable(
                    f"主机锁 {self._path} 已被另一个进程占用，请先停掉正在运行的后端或 CLI"
                ) from exc
            self._fd = fd



    def still_held(self) -> bool:
        """文件描述符仍在即视为持锁；进程崩溃时锁由内核自动回收。"""
        with self._mu:
            return self._fd is not None



    def release(self) -> None:
        """幂等释放：未取得或已释放均静默返回。"""
        with self._mu:
            fd = self._fd
            self._fd = None
            if fd is None:
                return
            if os.name == "nt":
                def _unlock_win() -> None:
                    """Windows 下解除文件锁，先回到文件头再解锁。"""
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

                _quiet(_unlock_win)
            else:
                _quiet(lambda: fcntl.flock(fd, fcntl.LOCK_UN))
            _quiet(lambda: os.close(fd))



    def __enter__(self) -> "HostProcessLock":
        """上下文管理器入口：取锁后返回自身。"""
        self.acquire()
        return self



    def __exit__(self, exc_type, exc, tb) -> None:
        """上下文管理器出口：无条件释放锁。"""
        self.release()



def _quiet(fn) -> None:
    """清理路径上的异常一律吞掉：已经在拆东西了，再抛只会盖住真正的原因。"""
    try:
        fn()
    except Exception:
        pass
