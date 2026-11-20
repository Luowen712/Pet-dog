"""唯一串口 I/O 线程与有界写队列（BA02 第 2、5 条）。

职责边界：
    - 本模块只管「字节流 ↔ 完整帧」的单线程读写，不碰数据库、不理解账号与动作状态机；
    - 真串口（COMx）、原样回读（loop://）与 BA01 模拟器（SimBytePort）共用同一接口；
    - 独立后台线程跑读写循环；若绑定了 asyncio 事件循环，所有回调一律通过
      loop.call_soon_threadsafe() 投递，绝不在 I/O 线程里直接改 asyncio.Future。

队列与安全纪律（06 §7、§8、N07、N30）：
    - 用户写队列上限 32，满时立刻拒收（QueueFullError），不无限堆积内存；
    - 心跳（0x04）独立占 1 个合并槽且优先级高于用户队列，防止表情刷屏饿死固件看门狗；
    - 用户写项排队超过 1 秒未开始写出，判为未写失败（queue_expired），不再发往串口；
    - 每次 write 前先查 DB 实例锁健康状态（still_held()），失锁立即停发、关口、上报 faulted；
    - 连续帧之间按波特率 + 20ms 保守预留物理帧间隔。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Protocol

import serial
from serial import SerialException

from app.link.frame import Frame, Parser
from app.link.send_gate import SendGate, SendGateTimeout
from app.link.simulator import Clock, SimBytePort, SimulatedDevice

logger = logging.getLogger(__name__)

MAX_WRITE_QUEUE = 32  # 06:201
DEFAULT_WRITE_TIMEOUT = 0.2  # 06:201 write_timeout=200ms
DEFAULT_MAX_QUEUE_WAIT = 1.0  # 06:201 排队超过 1 秒未开始 write 判过期
DEFAULT_MIN_FRAME_GAP = 0.02  # 06:210 连续帧至少 20ms

# 06:110 transport 枚举：0=全写，1=确定未写，2=可能部分写
TRANSPORT_OK = 0
TRANSPORT_WRITE_FAILED = 1
TRANSPORT_PARTIAL_WRITE = 2


class LinkError(Exception):
    """链路层基础异常。"""


class QueueFullError(LinkError):
    """写队列已满（32 条），拒绝新入队。"""


class LinkClosedError(LinkError):
    """链路正在关闭、已关闭或已故障，拒绝新操作。"""


class BytePort(Protocol):
    """与 pyserial.Serial 和 SimBytePort 同形的最小端口协议。"""

    @property
    def is_open(self) -> bool: ...

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


class _SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()


@dataclass(frozen=True)
class WriteOutcome:
    """一次入队写操作的最终传输结果。"""

    transport: int  # TRANSPORT_OK / TRANSPORT_WRITE_FAILED / TRANSPORT_PARTIAL_WRITE
    reason: str | None = None
    written_at: float | None = None


BeforeWriteHook = Callable[[], bool]
WriteCallback = Callable[[WriteOutcome], None]
FrameCallback = Callable[[Frame, float], None]
FaultCallback = Callable[[str], None]


@dataclass
class _WriteItem:
    payload: bytes
    enqueued_at: float
    max_queue_wait: float | None  # None 表示不超时（用于心跳）
    is_heartbeat: bool = False
    require_send_gate: bool = True
    before_write: BeforeWriteHook | None = None
    on_done: WriteCallback | None = None


def open_port(
    port_spec: str,
    *,
    baudrate: int = 9600,
    write_timeout: float = DEFAULT_WRITE_TIMEOUT,
    sim_device: SimulatedDevice | None = None,
) -> BytePort:
    """按端口字符串打开真串口、loop:// 或模拟器，对外返回同一协议对象。"""
    spec = port_spec.strip()
    if spec.lower() == "sim":
        return SimBytePort(sim_device if sim_device is not None else SimulatedDevice())
    if "://" in spec:
        return serial.serial_for_url(
            spec,
            baudrate=baudrate,
            timeout=0,
            write_timeout=write_timeout,
        )
    return serial.Serial(
        port=spec,
        baudrate=baudrate,
        timeout=0,
        write_timeout=write_timeout,
    )


class SerialLink:
    """单线程串口读写器：接收单消费者，发送有界队列 + 心跳优先 + 写前验锁。"""

    def __init__(
        self,
        port: BytePort,
        *,
        baudrate: int = 9600,
        clock: Clock | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        on_frame: FrameCallback | None = None,
        on_fault: FaultCallback | None = None,
        lock_check: Callable[[], bool] | None = None,
        send_gate: SendGate | None = None,
        max_queue: int = MAX_WRITE_QUEUE,
        max_queue_wait: float = DEFAULT_MAX_QUEUE_WAIT,
        min_frame_gap: float = DEFAULT_MIN_FRAME_GAP,
        poll_interval: float = 0.005,
    ) -> None:
        self._port = port
        self._baudrate = max(baudrate, 1)
        self._clock: Clock = clock if clock is not None else _SystemClock()
        self._loop = loop
        self._on_frame = on_frame
        self._on_fault = on_fault
        self._lock_check = lock_check
        self._send_gate = send_gate
        self._max_queue = max_queue
        self._max_queue_wait = max_queue_wait
        self._min_frame_gap = min_frame_gap
        self._poll_interval = poll_interval

        self._parser = Parser()
        self._q_lock = threading.Lock()
        self._user_queue: deque[_WriteItem] = deque()
        self._heartbeat_pending: _WriteItem | None = None
        self._wakeup = threading.Event()
        self._stop_event = threading.Event()

        self._started = False
        self._closing = False
        self._faulted = False
        self._fault_reason: str | None = None
        self._thread: threading.Thread | None = None
        self._next_write_allowed_at: float = 0.0

    @property
    def is_running(self) -> bool:
        return self._started and not self._closing and not self._faulted

    @property
    def faulted(self) -> bool:
        return self._faulted

    @property
    def fault_reason(self) -> str | None:
        return self._fault_reason

    @property
    def parser(self) -> Parser:
        return self._parser

    def set_callbacks(
        self,
        *,
        on_frame: FrameCallback | None = None,
        on_fault: FaultCallback | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        send_gate: SendGate | None = None,
    ) -> None:
        if on_frame is not None:
            self._on_frame = on_frame
        if on_fault is not None:
            self._on_fault = on_fault
        if loop is not None:
            self._loop = loop
        if send_gate is not None:
            self._send_gate = send_gate

    def start(self) -> None:
        with self._q_lock:
            if self._started:
                raise RuntimeError("SerialLink 已启动，不要重复 start")
            if self._closing or self._faulted:
                raise LinkClosedError("SerialLink 已关闭或处于故障态，不能重新启动")
            self._started = True
        self._thread = threading.Thread(
            target=self._run, name="petdog-serial-io", daemon=True
        )
        self._thread.start()

    def enqueue(
        self,
        payload: bytes,
        *,
        before_write: BeforeWriteHook | None = None,
        on_done: WriteCallback | None = None,
        max_queue_wait: float | None = None,
        require_send_gate: bool = True,
    ) -> None:
        """把帧放入有界队列（上限 32）。满队抛 QueueFullError，关闭/故障抛 LinkClosedError。"""
        wait = self._max_queue_wait if max_queue_wait is None else max_queue_wait
        item = _WriteItem(
            payload=bytes(payload),
            enqueued_at=self._clock.monotonic(),
            max_queue_wait=wait,
            is_heartbeat=False,
            require_send_gate=require_send_gate,
            before_write=before_write,
            on_done=on_done,
        )
        with self._q_lock:
            if self._closing or self._faulted:
                raise LinkClosedError(
                    f"链路不可写（closing={self._closing}, faulted={self._faulted}）"
                )
            if len(self._user_queue) >= self._max_queue:
                raise QueueFullError(f"写队列已满（上限 {self._max_queue}）")
            self._user_queue.append(item)
        self._wakeup.set()

    def enqueue_heartbeat(
        self,
        payload: bytes,
        *,
        on_done: WriteCallback | None = None,
    ) -> bool:
        """入队心跳帧：至多保留 1 条（合并去重），出队时优先于用户队列（N30）。

        返回 True 表示新放入，False 表示已有一条待发心跳并被合并。
        """
        with self._q_lock:
            if self._closing or self._faulted:
                raise LinkClosedError("链路已关闭或故障，无法入队心跳")
            if self._heartbeat_pending is not None:
                return False
            self._heartbeat_pending = _WriteItem(
                payload=bytes(payload),
                enqueued_at=self._clock.monotonic(),
                max_queue_wait=None,
                is_heartbeat=True,
                require_send_gate=False,
                on_done=on_done,
            )
        self._wakeup.set()
        return True

    def close(self, timeout: float = 2.0) -> None:
        """优雅关闭（BA02 第 5 条）：先拒新入队 → 停止循环等在途 write 退出 → 关串口。"""
        with self._q_lock:
            self._closing = True
        self._stop_event.set()
        self._wakeup.set()

        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=timeout)

        # 把还没来得及写出的排队项明确标为「未写（link_closing）」
        self._drain_unwritten("link_closing")
        self._close_port_quietly()

    # --- 后台 I/O 线程 ---

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set() and not self._faulted:
                self._poll_read()
                if self._faulted or self._stop_event.is_set():
                    break

                # 先清唤醒标记再取队，避免「判空后、wait 前」漏掉新入队信号
                self._wakeup.clear()
                item = self._pop_next()
                if item is not None:
                    self._process_write(item)
                    # 写完顺手读一次，及时吃掉模拟器或高速设备的立即回包
                    if not self._faulted and not self._stop_event.is_set():
                        self._poll_read()
                    continue

                self._wakeup.wait(timeout=self._poll_interval)
        except Exception as exc:
            logger.exception("串口 I/O 线程未预期异常: %s", exc)
            self._trip_fault(f"io_thread_error:{type(exc).__name__}")
        finally:
            self._close_port_quietly()

    def _pop_next(self) -> _WriteItem | None:
        """心跳优先于普通用户写（06:201、N30）。"""
        with self._q_lock:
            if self._heartbeat_pending is not None:
                item = self._heartbeat_pending
                self._heartbeat_pending = None
                return item
            if self._user_queue:
                return self._user_queue.popleft()
            return None

    def _process_write(self, item: _WriteItem) -> None:
        now = self._clock.monotonic()

        # 1. 排队超时检查（超过 1 秒未开始 write 直接退出，不写出到串口）
        if (
            item.max_queue_wait is not None
            and (now - item.enqueued_at) > item.max_queue_wait
        ):
            self._notify_write(
                item,
                WriteOutcome(transport=TRANSPORT_WRITE_FAILED, reason="queue_expired"),
            )
            return

        # 2. 保守物理帧间隔（06:210：至少 20ms + 字节线上传输耗时）
        if self._min_frame_gap > 0 and now < self._next_write_allowed_at:
            remain = self._next_write_allowed_at - now
            if self._stop_event.wait(timeout=remain):
                self._notify_write(
                    item,
                    WriteOutcome(transport=TRANSPORT_WRITE_FAILED, reason="link_closing"),
                )
                return
            # 等完帧间隔后再次核对排队是否已过期
            now = self._clock.monotonic()
            if (
                item.max_queue_wait is not None
                and (now - item.enqueued_at) > item.max_queue_wait
            ):
                self._notify_write(
                    item,
                    WriteOutcome(transport=TRANSPORT_WRITE_FAILED, reason="queue_expired"),
                )
                return

        # 3. 写前 DB 实例锁健康检查（BA02 判据三 / N07：丢锁即停发退出，绝不透明重连）
        if self._lock_check is not None:
            try:
                held = bool(self._lock_check())
            except Exception:
                held = False
            if not held:
                self._notify_write(
                    item,
                    WriteOutcome(transport=TRANSPORT_WRITE_FAILED, reason="db_lock_lost"),
                )
                self._trip_fault("db_lock_lost")
                return

        # 4 & 5. 用户写受 SendGate 保护（06:189：动作与表情共用同一门禁，系统心跳/快照放行）
        gate = self._send_gate if item.require_send_gate else None
        if gate is not None:
            try:
                with gate.hold():
                    self._execute_write(item)
            except SendGateTimeout:
                self._notify_write(
                    item,
                    WriteOutcome(
                        transport=TRANSPORT_WRITE_FAILED, reason="send_gate_timeout"
                    ),
                )
        else:
            self._execute_write(item)

    def _execute_write(self, item: _WriteItem) -> None:
        # 写前门禁钩子（BA04 撤销竞争障碍点 / SendGate 内授权复核）
        if item.before_write is not None:
            try:
                allowed = bool(item.before_write())
            except Exception as exc:
                logger.exception("before_write 钩子异常: %s", exc)
                allowed = False
            if not allowed:
                self._notify_write(
                    item,
                    WriteOutcome(
                        transport=TRANSPORT_WRITE_FAILED, reason="aborted_before_write"
                    ),
                )
                return

        # 真正写串口
        try:
            written = self._port.write(item.payload)
            self._port.flush()
        except (SerialException, OSError) as exc:
            # write 已进入内核/驱动，可能部分字节已发到线上，保守记 partial_write
            self._notify_write(
                item,
                WriteOutcome(
                    transport=TRANSPORT_PARTIAL_WRITE,
                    reason=f"serial_write_error:{type(exc).__name__}",
                ),
            )
            self._trip_fault(f"serial_write_error:{type(exc).__name__}")
            return

        written_at = self._clock.monotonic()
        if written == 0:
            self._notify_write(
                item,
                WriteOutcome(
                    transport=TRANSPORT_WRITE_FAILED,
                    reason="zero_bytes_written",
                    written_at=written_at,
                ),
            )
            return
        if written is None or written < len(item.payload):
            self._notify_write(
                item,
                WriteOutcome(
                    transport=TRANSPORT_PARTIAL_WRITE,
                    reason="partial_write",
                    written_at=written_at,
                ),
            )
            return

        wire_time = (len(item.payload) * 10.0) / self._baudrate
        self._next_write_allowed_at = written_at + wire_time + self._min_frame_gap
        self._notify_write(
            item,
            WriteOutcome(
                transport=TRANSPORT_OK,
                reason=None,
                written_at=written_at,
            ),
        )

    def _poll_read(self) -> None:
        for _ in range(8):
            try:
                chunk = self._port.read(64)
            except (SerialException, OSError) as exc:
                if not self._closing:
                    self._trip_fault(f"serial_read_error:{type(exc).__name__}")
                return
            if not chunk:
                return
            frames = self._parser.feed(chunk)
            for frame in frames:
                # 06:206 接收线程到帧立刻捕获单调时钟，不用上层 DB 处理完的时刻
                received_at = self._clock.monotonic()
                if self._on_frame is not None:
                    self._dispatch(self._on_frame, frame, received_at)

    def _trip_fault(self, reason: str) -> None:
        notify = False
        with self._q_lock:
            if not self._faulted:
                self._faulted = True
                self._fault_reason = reason
                notify = True
        self._stop_event.set()
        self._drain_unwritten(reason)
        self._close_port_quietly()
        if notify and self._on_fault is not None:
            self._dispatch(self._on_fault, reason)

    def _drain_unwritten(self, reason: str) -> None:
        leftover: list[_WriteItem] = []
        with self._q_lock:
            if self._heartbeat_pending is not None:
                leftover.append(self._heartbeat_pending)
                self._heartbeat_pending = None
            while self._user_queue:
                leftover.append(self._user_queue.popleft())
        for item in leftover:
            self._notify_write(
                item,
                WriteOutcome(transport=TRANSPORT_WRITE_FAILED, reason=reason),
            )

    def _notify_write(self, item: _WriteItem, outcome: WriteOutcome) -> None:
        if item.on_done is not None:
            self._dispatch(item.on_done, outcome)

    def _dispatch(self, fn: Callable, *args) -> None:
        """若绑定了 asyncio 事件循环，统一通过 call_soon_threadsafe 切回主循环线程。"""
        loop = self._loop
        if loop is not None:
            try:
                if loop.is_running():
                    loop.call_soon_threadsafe(fn, *args)
                    return
            except RuntimeError:
                pass
        try:
            fn(*args)
        except Exception:
            logger.exception("链路回调执行异常")

    def _close_port_quietly(self) -> None:
        try:
            if self._port.is_open:
                self._port.close()
        except Exception:
            pass
