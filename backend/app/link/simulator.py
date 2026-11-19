"""模拟设备（SIM）：BA01 的设备侧替身。

约束：
- 零线程、零真实等待：时间只从注入的 Clock 读取，测试用 FakeClock 推进。
- 收发都过 app/link/frame.py：出帧 build()，入帧 Parser。
- 它不证明设备 ACK，只提供可注入的请求/受理/完成时间线。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from serial import SerialException

from app.link.frame import Frame, Parser, build

# docs/contracts/fixtures/frames.status.core9.json 的同值：87%、空闲、表情 2、7422mV、20°C
DEFAULT_STATUS = bytes([0x57, 0x00, 0x02, 0xFF, 0xFF, 0x1C, 0xFE, 0xFF, 0x14])
ENABLED_ACTIONS = frozenset(range(0x30, 0x37))  # 06:240 本期只启用 0x30~0x36

ERR_UNSUPPORTED = 0x01
ERR_PARAM = 0x02
ERR_OVERLONG = 0x03
ERR_BUSY = 0x04

CMD_ACTION = 0x01
CMD_DONE = 0x02
CMD_STATUS = 0x03
CMD_HEARTBEAT_REQ = 0x04
CMD_HEARTBEAT_ACK = 0x84
CMD_POLL_STATUS = 0x06
CMD_FACE = 0x07
CMD_ACCEPTED = 0x81
CMD_REJECT = 0x05


@dataclass(frozen=True)
class SimFaults:
    drop_ack: bool = False
    drop_done: bool = False
    delay_done_ms: int = 300
    duplicate_done: bool = False
    bad_checksum: bool = False
    disconnect: bool = False


class Clock(Protocol):
    def monotonic(self) -> float: ...


class _SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()


class FakeClock:
    def __init__(self) -> None:
        self._t = 0.0

    def monotonic(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("时间不能倒退")
        self._t += seconds


@dataclass
class SimStats:
    """counter 说明：corrupted 计的是 Parser 的重同步次数（字节级），
    一个坏帧通常会计多次，只用于判断"是否出现过坏帧"。"""

    frames_in: int = 0
    frames_out: int = 0
    dropped: int = 0
    corrupted: int = 0
    duplicates: int = 0
    rejected_busy: int = 0
    rejected_unsupported: int = 0
    rejected_param: int = 0
    unknown_cmd: int = 0
    malformed: int = 0
    rejected_overlong: int = 0


def _opt(value: int) -> int | None:
    return None if value == 0xFF else value


def decode_status(data: bytes) -> dict:
    """按 06:225 解 9 字节状态；LEN=6 只解前 6 字节，电压及之后一律 None。"""
    if len(data) not in (6, 9):
        raise ValueError(f"状态帧只支持 6 或 9 字节，收到 {len(data)}")

    out = {
        "battery": _opt(data[0]),
        "action": data[1],  # 0 是空闲，不是未知
        "face": _opt(data[2]),
        "music_state": _opt(data[3]),
        "track": _opt(data[4]),
        "voltage_mv": None,
        "weather": None,
        "temperature": None,
    }
    if len(data) == 9:
        mv = (data[5] << 8) | data[6]
        out["voltage_mv"] = None if mv == 0xFFFF else mv
        out["weather"] = _opt(data[7])
        temp = data[8] - 0x100 if data[8] > 0x7F else data[8]
        out["temperature"] = None if temp == -128 else temp
    return out


class SimulatedDevice:
    """设备侧替身。feed() 收字节，poll() 取已到期的出站帧。"""

    def __init__(
        self,
        clock: Clock | None = None,
        faults: SimFaults | None = None,
        status: bytes = DEFAULT_STATUS,
    ) -> None:
        self._clock: Clock = clock if clock is not None else _SystemClock()
        self._faults = faults if faults is not None else SimFaults()
        self._status = bytearray(status)
        self._parser = Parser()
        self._out: list[tuple[float, bytes]] = []
        self._seq_results: dict[int, tuple[bytes, list[tuple[float, bytes]]]] = {}
        self._busy_until: float | None = None
        self._connected = not self._faults.disconnect
        self.stats = SimStats()

    # --- 连接 ---

    @property
    def connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    # --- 收发 ---

    def feed(self, chunk: bytes) -> None:
        """主机→设备字节。断线时丢弃；坏帧由 Parser 吞掉，只计噪声。"""
        if not self._connected:
            return
        before = (self._parser.bad_sum, self._parser.bad_len, self._parser.noise)
        frames = self._parser.feed(chunk)
        after = (self._parser.bad_sum, self._parser.bad_len, self._parser.noise)
        self.stats.corrupted += sum(a - b for a, b in zip(after, before))
        self.stats.frames_in += len(frames)
        now = self._clock.monotonic()
        for frame in frames:
            self._handle(frame, now)

    def poll(self) -> list[bytes]:
        now = self._clock.monotonic()
        ready = sorted((item for item in self._out if item[0] <= now), key=lambda it: it[0])
        self._out = [item for item in self._out if item[0] > now]
        return [payload for _, payload in ready]

    # --- 内部 ---

    def _emit(self, due_at: float, payload: bytes) -> None:
        cmd = payload[3]  # SOF(2) + LEN(1) 之后是 CMD
        if cmd == CMD_ACCEPTED and self._faults.drop_ack:
            self.stats.dropped += 1
            return
        if cmd == CMD_DONE and self._faults.drop_done:
            self.stats.dropped += 1
            return
        if self._faults.bad_checksum:
            payload = payload[:-1] + bytes([payload[-1] ^ 0xFF])
            self.stats.corrupted += 1
        self._out.append((due_at, payload))
        self.stats.frames_out += 1

    def _handle(self, frame: Frame, now: float) -> None:
        if frame.cmd == CMD_HEARTBEAT_REQ:
            self._emit(now, build(CMD_HEARTBEAT_ACK))
        elif frame.cmd == CMD_ACTION:
            self._on_action(frame.data, now)
        elif frame.cmd == CMD_POLL_STATUS:
            self._emit(now, build(CMD_STATUS, bytes(self._status)))
        elif frame.cmd == CMD_FACE:
            if frame.data:
                self._status[2] = frame.data[0]
            else:
                self.stats.malformed += 1
        else:
            self.stats.unknown_cmd += 1

    def _on_action(self, data: bytes, now: float) -> None:
        if len(data) < 4:
            self.stats.malformed += 1  # 取不到 seq，按 06:281 不回 05
            return
        action, seq = data[0], data[3]
        if len(data) > 4:
            self.stats.rejected_overlong += 1
            self._emit(now, build(CMD_REJECT, bytes([ERR_OVERLONG, seq])))
            return

        sig = bytes(data)
        known = self._seq_results.get(seq)
        if known is not None:
            if known[0] != sig:
                # 06:284 只说"拒绝"未定码，暂用 02 参数非法，已登记为契约缺口
                self.stats.rejected_param += 1
                self._emit(now, build(CMD_REJECT, bytes([ERR_PARAM, seq])))
                return
            self.stats.duplicates += 1
            for offset, payload in known[1]:
                self._emit(now + offset, payload)
            return

        if action not in ENABLED_ACTIONS:
            self.stats.rejected_unsupported += 1
            self._emit(now, build(CMD_REJECT, bytes([ERR_UNSUPPORTED, seq])))
            return

        if self._busy_until is not None and now < self._busy_until:
            self.stats.rejected_busy += 1
            self._emit(now, build(CMD_REJECT, bytes([ERR_BUSY, seq])))
            return

        delay = self._faults.delay_done_ms / 1000.0
        self._busy_until = now + delay
        responses: list[tuple[float, bytes]] = [
            (0.0, build(CMD_ACCEPTED, bytes([CMD_ACTION, seq]))),
            (delay, build(CMD_DONE, bytes([action, seq]))),
        ]
        if self._faults.duplicate_done:
            responses.append((delay, build(CMD_DONE, bytes([action, seq]))))
        self._seq_results[seq] = (sig, responses)
        while len(self._seq_results) > 255:
            self._seq_results.pop(next(iter(self._seq_results)))
        for offset, payload in responses:
            self._emit(now + offset, payload)


class SimDisconnected(SerialException):
    """模拟端口的所有 I/O 失败都用它。

    继承 serial.SerialException 是为了让上层只写一个 except：
    真串口抛 PortNotOpenError（也是 SerialException 的子类），
    模拟端口抛 SimDisconnected，两者同宗，链路层不必区分真假端口。
    """


class SimBytePort:
    """把 SimulatedDevice 包成与 pyserial.Serial 同形的端口。

    对真端口实测（pyserial 3.5 + loop://）后确定的语义：
    端口关闭后除 is_open 外，每个操作都抛异常，绝不静默返回空；
    打开且无数据时 read 立即返回 b""（timeout=0 的不阻塞语义）。
    """

    def __init__(self, device: SimulatedDevice) -> None:
        self._device = device
        self._rx = bytearray()
        self._closed = False

    @property
    def is_open(self) -> bool:
        return not self._closed

    @property
    def in_waiting(self) -> int:
        self._check_open()
        self._drain()
        return len(self._rx)

    def write(self, data: bytes) -> int:
        self._check_open()
        self._device.feed(bytes(data))
        return len(data)

    def read(self, size: int = 1) -> bytes:
        self._check_open()  # 真 pyserial 先判 is_open 再处理 size，关闭态 read(0) 也抛
        if size <= 0:
            return b""
        if len(self._rx) < size:
            self._drain()
        chunk = bytes(self._rx[:size])
        del self._rx[:size]
        return chunk

    def flush(self) -> None:
        self._check_open()

    def reset_input_buffer(self) -> None:
        self._check_open()
        self._rx.clear()

    def close(self) -> None:
        self._closed = True

    def _check_open(self) -> None:
        if self._closed:
            raise SimDisconnected("端口已关闭")
        if not self._device.connected:
            raise SimDisconnected("模拟设备已断开")

    def _drain(self) -> None:
        while True:
            frames = self._device.poll()
            if not frames:
                return
            for frame in frames:
                self._rx += frame
