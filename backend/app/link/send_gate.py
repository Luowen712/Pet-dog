"""发送与撤销协调门禁（BA02 第 2 条向 BB03 交付的最小实现；完整竞争测试见 BA04）。

为什么需要 SendGate（06 §7）：
    串口 write 与数据库 commit 无法放进同一个事务。
    如果没有这把统一的门禁锁，就可能出现：用户刚点完「改密码/解绑/注销」并已提交，
    另一条线程上旧权限发出的运动指令却正好穿过校验写进了串口。
    SendGate 把「所有用户发起的设备写（动作 + 表情）」与「所有会改变授权版本的
    数据库提交（改密/登出/解绑/注销/认领）」放进同一把互斥锁里串行协调。

锁顺序硬约定（06:191，防止死锁）：
    SendGate → admin 命名锁（需要时）→ user → device → claim
    只读查询不拿 SendGate；密码哈希计算先算完再拿锁。

为什么撤销通知（清缓存/关 WS/作废票据）必须放在释锁之后（BA04 第 2 条）：
    网络 I/O 可能慢或阻塞；数据库一旦 commit，权威事实就已经生效，
    释锁后再通知监听器清理连接，避免慢客户端拖住整把 SendGate。
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_GATE_TIMEOUT = 5.0  # 06:202 操作整体 5 秒上限


class SendGateTimeout(TimeoutError):
    """在超时时间内未能取得 SendGate 锁。"""


@dataclass(frozen=True)
class AuthContext:
    """跨层传递的不可变授权上下文（06 §6）。

    只装纯整数，不装 SQLAlchemy ORM 对象或 Session——
    Session 不能跨线程传递，串口/发送层绝不能直接持有请求线程的 DB Session。
    """

    uid: int
    tv: int
    device_pk: int
    be: int


@dataclass(frozen=True)
class RevokeEvent:
    """授权变更提交成功后广播给进程内监听器的只读事件。"""

    uid: int | None
    device_pk: int | None
    kind: str  # logout / password_change / unbind / account_delete / claim / handover
    new_tv: int | None = None
    new_be: int | None = None


RevokeListener = Callable[[RevokeEvent], None]


class SendGate:
    """进程内同步门禁锁：只在线程中使用（06:201）。"""



    def __init__(self, default_timeout: float = DEFAULT_GATE_TIMEOUT) -> None:
        """初始化门禁锁、撤销监听器表与默认等待超时。"""
        self._lock = threading.Lock()
        self._listeners_mu = threading.Lock()
        self._listeners: list[RevokeListener] = []
        self._default_timeout = default_timeout
        self._hold_seq = 0



    @property
    def default_timeout(self) -> float:
        """返回门禁默认等待超时（秒）。"""
        return self._default_timeout

    @property
    def hold_seq(self) -> int:
        """持锁次数计数：调用方据此判断临界区是否被推进过。"""
        return self._hold_seq

    @contextmanager
    def hold(self, timeout: float | None = None) -> Iterator[None]:
        """持锁执行需要与撤销互斥的临界区（例如设备写前置检查或归属提交）。"""
        wait = self._default_timeout if timeout is None else timeout
        acquired = self._lock.acquire(timeout=wait)
        if not acquired:
            raise SendGateTimeout(f"等待 SendGate 超时（{wait:.2f}s）")
        try:
            self._hold_seq += 1
            yield
        finally:
            self._lock.release()



    def register_revoke_listener(self, listener: RevokeListener) -> Callable[[], None]:
        """注册撤销监听器（如 DeviceSession / WS Hub / TicketStore），返回取消函数。"""
        with self._listeners_mu:
            self._listeners.append(listener)

        def _unregister() -> None:
            """把已注册的监听器移出列表，重复调用不报错。"""
            with self._listeners_mu:
                try:
                    self._listeners.remove(listener)
                except ValueError:
                    pass

        return _unregister



    def notify_revoke(self, event: RevokeEvent) -> None:
        """在 SendGate 释锁后广播撤销事件，监听器异常只记日志不反向影响已提交事务。"""
        with self._listeners_mu:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                # DB 已经提交成功，监听器异常只记日志，绝不伪造「提交失败」
                logger.exception("SendGate 撤销监听器执行异常: kind=%s", event.kind)



    def revoke_access(
        self,
        uid: int | None,
        device_pk: int | None,
        kind: str,
        commit_fn: Callable[[], T],
        *,
        new_tv: int | None = None,
        new_be: int | None = None,
        timeout: float | None = None,
    ) -> T:
        """在 SendGate 内执行权威失效提交，释锁后再通知监听器清理缓存/票据/连接。

        参数：
            uid / device_pk: 受影响的账号主键与设备主键（按场景可空）。
            kind: 撤销类型（logout / password_change / unbind / account_delete / claim）。
            commit_fn: 真正执行 DB 更新并 commit 的无参回调；抛出异常时不触发监听器。
        """
        with self.hold(timeout=timeout):
            result = commit_fn()

        self.notify_revoke(
            RevokeEvent(
                uid=uid,
                device_pk=device_pk,
                kind=kind,
                new_tv=new_tv,
                new_be=new_be,
            )
        )
        return result


# 进程唯一门禁实例：BA 与 BB 共用这一把，禁止各自另建第二把。
send_gate = SendGate()



def revoke_access(
    uid: int | None,
    device_pk: int | None,
    kind: str,
    commit_fn: Callable[[], T],
    *,
    new_tv: int | None = None,
    new_be: int | None = None,
    timeout: float | None = None,
) -> T:
    """模块级快捷入口，等价于 send_gate.revoke_access(...)。"""
    return send_gate.revoke_access(
        uid=uid,
        device_pk=device_pk,
        kind=kind,
        commit_fn=commit_fn,
        new_tv=new_tv,
        new_be=new_be,
        timeout=timeout,
    )
