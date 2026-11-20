"""唯一设备会话与生命周期管理（BA02 第 1、3、4、5 条）。

职责：
    - 进程内一台物理/模拟设备只对应一个 DeviceSession 实例，串联：
        DeviceSessionRecord（数据库会话与 seq 持久化）
        ↔ ProcessLock（DB 实例锁写前验活）
        ↔ SerialLink（单线程串口收发与有界队列）
    - 启动时清查旧会话与未终结命令：旧未终结命令一律改 unknown、绝不重发；
      默认进入 recovery_required，只有携带匹配的准备标记且收到新会话有效 0x03 快照
      后才允许进入 ready。
    - 序号 1..255 在本会话内绝不复用：先持久化 last_seq、先登记 pending 映射、
      再入队写出；第 256 条直接拒绝（SeqExhaustedError），零 write。
    - 任一数据库或串口致命异常、或 DB 锁丢失（still_held()=False）立即进入 faulted，
      停止发送并关口，绝不降级成无锁工作。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.link.frame import Frame, build
from app.link.lock import ProcessLock
from app.link.send_gate import RevokeEvent, SendGate
from app.link.serial_link import (
    BeforeWriteHook,
    LinkClosedError,
    SerialLink,
    TRANSPORT_PARTIAL_WRITE,
    TRANSPORT_WRITE_FAILED,
    WriteCallback,
    WriteOutcome,
)
from app.link.simulator import (
    CMD_ACCEPTED,
    CMD_ACTION,
    CMD_DONE,
    CMD_FACE,
    CMD_HEARTBEAT_ACK,
    CMD_HEARTBEAT_REQ,
    CMD_POLL_STATUS,
    CMD_REJECT,
    CMD_STATUS,
    Clock,
    decode_status,
)
from app.models import CommandLog, Device, DeviceSessionRecord

logger = logging.getLogger(__name__)

# 06 §4 命令存储状态码
CMD_STATUS_PENDING = 10
CMD_STATUS_ACCEPTED = 20
CMD_STATUS_DONE = 30
CMD_STATUS_REJECTED = 40
CMD_STATUS_UNKNOWN = 50
CMD_STATUS_SUPERSEDED = 60

MAX_SEQ = 255  # 06:290 同会话 1..255 不复用
UPLINK_TIMEOUT_SEC = 9.0  # 06 第 12.1 节：9 秒无有效上行即 offline
POLL_MIN_INTERVAL_SEC = 1.0  # 06 第 12.2 节：同一设备两次 06 至少间隔 1 秒

SUPPORTED_CORE_ACTIONS: tuple[int, ...] = (0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36)


class SessionError(Exception):
    """设备会话异常基类。"""


class SessionNotReadyError(SessionError):
    """设备未处于可接受控制的状态（如 offline / recovery_required / handover_required / busy）。"""

    def __init__(self, control_state: str, message: str) -> None:
        super().__init__(message)
        self.control_state = control_state


class SeqExhaustedError(SessionError):
    """本会话序号 1..255 已耗尽（06:290 → 40900 / seq_exhausted）。"""

    reason = "seq_exhausted"


class SessionFaultedError(SessionError):
    """会话因 DB/串口/锁丢失进入故障态，禁止新发送。"""

    def __init__(self, reason: str) -> None:
        super().__init__(f"设备会话已故障（{reason}），停止发送")
        self.reason = reason


class _SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()


@dataclass(frozen=True)
class PendingSlot:
    cmd_id: str
    seq: int
    action: int
    be: int
    created_at: float


@dataclass(frozen=True)
class SessionEvent:
    """上报给上层（命令服务 / WS Hub / 测试）的只读事件。"""

    kind: str  # accepted / done / rejected / orphan / state / link / fault
    session_id: str
    received_at: float
    payload: dict


@dataclass(frozen=True)
class SessionSnapshot:
    """对外只读状态快照（可直接投影为 DeviceStatus / control_state）。"""

    device_pk: int
    be: int
    session_id: str
    online: bool
    control_state: str
    state_revision: int
    battery: int | None
    voltage: float | None
    action: int | None
    face: int | None
    music_state: int | None
    track: int | None
    volume: int | None
    weather_code: int | None
    temp: int | None
    last_heartbeat: datetime | None
    remaining_seq: int
    supported_actions: tuple[int, ...]


EventCallback = Callable[[SessionEvent], None]
SessionFactory = Callable[[], Session]


class DeviceSession:
    """单设备的唯一运行时会话。"""

    def __init__(
        self,
        device_pk: int,
        session_factory: SessionFactory,
        link: SerialLink,
        *,
        process_lock: ProcessLock | None = None,
        send_gate: SendGate | None = None,
        clock: Clock | None = None,
        prepared_marker: tuple[int, str | None] | None = None,
        auto_prepare_sim: bool = False,
        on_event: EventCallback | None = None,
        supported_actions: tuple[int, ...] = SUPPORTED_CORE_ACTIONS,
    ) -> None:
        self._device_pk = device_pk
        self._session_factory = session_factory
        self._link = link
        self._process_lock = process_lock
        self._send_gate = send_gate
        self._clock: Clock = clock if clock is not None else _SystemClock()
        self._prepared_marker = prepared_marker
        self._auto_prepare_sim = auto_prepare_sim
        self._on_event = on_event
        self._supported_actions = tuple(supported_actions)

        self._mu = threading.RLock()
        self._session_id: str = str(uuid.uuid4())
        self._session_record_id: int | None = None
        self._be: int = 0
        self._last_seq: int = 0

        self._started = False
        self._closing = False
        self._faulted = False
        self._fault_reason: str | None = None

        self._handover_required = True
        self._prepared = False
        self._recovery_required = True
        self._snapshot_received = False
        self._online = False
        self._last_uplink: float | None = None
        self._last_heartbeat: datetime | None = None
        self._last_poll_sent_at: float | None = None

        # 0x03 缓存字段：未知一律 None，绝不回填 0（06:44）
        self._state_revision: int = 0
        self._battery: int | None = None
        self._voltage: float | None = None
        self._action: int | None = None
        self._face: int | None = None
        self._music_state: int | None = None
        self._track: int | None = None
        self._volume: int | None = None
        self._weather_code: int | None = None
        self._temp: int | None = None

        self._pending: dict[int, PendingSlot] = {}
        self._unregister_revoke: Callable[[], None] | None = None
        self.orphan_frames: int = 0
        self.malformed_status_frames: int = 0
        self.recovered_unknown_commands: int = 0

    # --- 只读属性 ---

    @property
    def device_pk(self) -> int:
        return self._device_pk

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def be(self) -> int:
        return self._be

    @property
    def last_seq(self) -> int:
        with self._mu:
            return self._last_seq

    @property
    def remaining_seq(self) -> int:
        with self._mu:
            return max(0, MAX_SEQ - self._last_seq)

    @property
    def online(self) -> bool:
        with self._mu:
            return self._online

    @property
    def pending_seqs(self) -> dict[int, PendingSlot]:
        with self._mu:
            return dict(self._pending)

    @property
    def control_state(self) -> str:
        """严格按 06 第 12.1 节优先级裁决 control_state：
        faulted > handover_required > offline > recovery_required > busy > ready > unconfigured
        """
        with self._mu:
            if self._faulted or self._link.faulted:
                return "faulted"
            if self._handover_required:
                return "handover_required"
            if not self._online:
                return "offline"
            if not self._prepared or self._recovery_required:
                return "recovery_required"
            if not self._snapshot_received:
                return "unconfigured"
            if self._pending or (self._action not in (None, 0)):
                return "busy"
            return "ready"

    def snapshot(self) -> SessionSnapshot:
        with self._mu:
            return SessionSnapshot(
                device_pk=self._device_pk,
                be=self._be,
                session_id=self._session_id,
                online=self._online,
                control_state=self.control_state,
                state_revision=self._state_revision,
                battery=self._battery,
                voltage=self._voltage,
                action=self._action,
                face=self._face,
                music_state=self._music_state,
                track=self._track,
                volume=self._volume,
                weather_code=self._weather_code,
                temp=self._temp,
                last_heartbeat=self._last_heartbeat,
                remaining_seq=max(0, MAX_SEQ - self._last_seq),
                supported_actions=self._supported_actions,
            )

    # --- 生命周期 ---

    def start(self) -> None:
        """启动会话（BA02 第 3 条）：
        1. 读出旧会话与未终结命令，旧未终结改 unknown，绝不重发；
        2. 核对准备标记，默认 recovery_required；
        3. 新建 DeviceSessionRecord(state='open', last_seq=0) 并启动串口线程。
        """
        # 先验锁（不在持有 self._mu 时关闭链路，避免与 _on_frame 互相等待）
        self._ensure_db_lock_or_fault()

        with self._mu:
            if self._started:
                raise RuntimeError("DeviceSession 已启动，不要重复 start")

            now_dt = datetime.now()
            db = self._session_factory()
            try:
                device = (
                    db.query(Device).filter(Device.id == self._device_pk).first()
                )
                if device is None:
                    raise SessionError(f"设备不存在：device_pk={self._device_pk}")

                self._be = device.be
                self._handover_required = device.handover_state != "ready"

                # 1. 查找最近一次旧会话（供准备标记核对）并关闭所有遗留 open 会话
                latest_prev = (
                    db.query(DeviceSessionRecord)
                    .filter(DeviceSessionRecord.device_pk == self._device_pk)
                    .order_by(DeviceSessionRecord.id.desc())
                    .first()
                )
                prev_session_id = latest_prev.session_id if latest_prev else None

                open_records = (
                    db.query(DeviceSessionRecord)
                    .filter(
                        DeviceSessionRecord.device_pk == self._device_pk,
                        DeviceSessionRecord.state == "open",
                    )
                    .all()
                )
                for rec in open_records:
                    rec.state = "closed"
                    rec.ended_at = now_dt

                # 2. 所有旧的未终结命令（pending/accepted）一律改 unknown，绝不重放
                unfinished = (
                    db.query(CommandLog)
                    .filter(
                        CommandLog.device_pk == self._device_pk,
                        CommandLog.status.in_(
                            (CMD_STATUS_PENDING, CMD_STATUS_ACCEPTED)
                        ),
                    )
                    .all()
                )
                for cmd in unfinished:
                    cmd.status = CMD_STATUS_UNKNOWN
                    cmd.reason = "session_restart"
                    cmd.revision = (cmd.revision or 0) + 1
                    cmd.finished_at = now_dt
                self.recovered_unknown_commands = len(unfinished)

                # 3. 决定是否通过准备门禁（06:299）
                if self._handover_required:
                    self._prepared = False
                    self._recovery_required = True
                elif self._prepared_marker is not None and self._prepared_marker == (
                    self._be,
                    prev_session_id,
                ):
                    self._prepared = True
                    self._recovery_required = False
                elif self._auto_prepare_sim and self.recovered_unknown_commands == 0:
                    self._prepared = True
                    self._recovery_required = False
                else:
                    self._prepared = False
                    self._recovery_required = True

                # 4. 登记本次新会话记录
                new_rec = DeviceSessionRecord(
                    device_pk=self._device_pk,
                    be=self._be,
                    session_id=self._session_id,
                    state="open",
                    last_seq=0,
                    started_at=now_dt,
                )
                db.add(new_rec)
                db.commit()
                self._session_record_id = new_rec.id
            except SessionError:
                db.rollback()
                raise
            except Exception as exc:
                db.rollback()
                self._enter_fault(f"db_startup_error:{type(exc).__name__}")
                raise SessionFaultedError(self._fault_reason or "db_startup_error") from exc
            finally:
                db.close()

            self._link.set_callbacks(
                on_frame=self._on_frame,
                on_fault=self._on_link_fault,
                send_gate=self._send_gate,
            )
            if self._send_gate is not None:
                self._unregister_revoke = self._send_gate.register_revoke_listener(
                    self._on_revoke
                )
            self._link.start()
            self._started = True

    def close(self, timeout: float = 2.0) -> None:
        """关闭顺序（BA02 第 5 条）：先拒新操作 → 停写等在途退出并关串口 → 关闭会话记录。"""
        with self._mu:
            self._closing = True
            rec_id = self._session_record_id
            unreg = self._unregister_revoke
            self._unregister_revoke = None

        if unreg is not None:
            unreg()

        self._link.close(timeout=timeout)

        if rec_id is not None:
            db = self._session_factory()
            try:
                rec = (
                    db.query(DeviceSessionRecord)
                    .filter(DeviceSessionRecord.id == rec_id)
                    .first()
                )
                if rec is not None and rec.state == "open":
                    rec.state = "closed"
                    rec.ended_at = datetime.now()
                    db.commit()
            except Exception:
                db.rollback()
                logger.exception("关闭 DeviceSessionRecord 时写库失败")
            finally:
                db.close()

    # --- 下行控制 ---

    def send_motion(
        self,
        cmd_id: str,
        action: int,
        *,
        on_write: WriteCallback | None = None,
        before_write: BeforeWriteHook | None = None,
    ) -> int:
        """分配 seq（1..255 先落库）→ 先登记 pending → 再入队写 0x01 动作帧（BA02 第 4 条）。"""
        # 锁外检查 DB 实例锁，失锁关口绝不持 self._mu
        self._ensure_db_lock_or_fault()

        close_on_fault = False
        try:
            with self._mu:
                self._assert_writable_locked()
                state = self.control_state
                if state != "ready":
                    raise SessionNotReadyError(
                        state, f"设备当前状态为 {state}，不能发起新运动"
                    )
                if action not in self._supported_actions:
                    raise ValueError(f"动作码 0x{action:02X} 不在当前允许列表内")
                if self._pending:
                    raise SessionNotReadyError("busy", "设备已有在途运动指令")

                # 第 256 条显式拒绝，绝不复用序号，零 write（BA02 判据二 / N09）
                if self._last_seq >= MAX_SEQ:
                    self._recovery_required = True
                    raise SeqExhaustedError(
                        "当前会话序号 1..255 已耗尽，请停止控制并执行人工会话恢复"
                    )

                next_seq = self._last_seq + 1
                try:
                    self._persist_last_seq_locked(next_seq)
                except SessionFaultedError:
                    close_on_fault = True
                    raise
                self._last_seq = next_seq

                # pending 登记必须早于 write，防止极速回包早于登记（BA02 第 4 条 / 06:206）
                self._pending[next_seq] = PendingSlot(
                    cmd_id=cmd_id,
                    seq=next_seq,
                    action=action,
                    be=self._be,
                    created_at=self._clock.monotonic(),
                )

                def _handle_motion_write(outcome: WriteOutcome) -> None:
                    # 06:116 确定未写失败可释放运动槽；可能部分写保持 recovery_required
                    with self._mu:
                        if outcome.transport == TRANSPORT_WRITE_FAILED:
                            self._pending.pop(next_seq, None)
                        elif outcome.transport == TRANSPORT_PARTIAL_WRITE:
                            self._recovery_required = True
                    if on_write is not None:
                        on_write(outcome)

                payload = build(CMD_ACTION, bytes([action, 0x00, 0x01, next_seq]))
                try:
                    self._link.enqueue(
                        payload,
                        before_write=before_write,
                        on_done=_handle_motion_write,
                        require_send_gate=True,
                    )
                except Exception:
                    # 确定未进入写队列时释放本次 pending 槽（但已持久化的 seq 不回滚复用）
                    self._pending.pop(next_seq, None)
                    raise

                return next_seq
        except SessionFaultedError:
            if close_on_fault:
                self._link.close(timeout=0.5)
            raise

    def send_face(
        self,
        face: int,
        *,
        on_write: WriteCallback | None = None,
        before_write: BeforeWriteHook | None = None,
    ) -> None:
        """下发 0x07 预设表情（0..6），无 seq、不占运动槽，但受同一 SendGate 与锁门禁保护。"""
        if not (0 <= face <= 6):
            raise ValueError(f"表情编号超出 0..6 范围: {face}")
        self._ensure_db_lock_or_fault()
        with self._mu:
            self._assert_writable_locked()
            state = self.control_state
            if state not in ("ready", "busy"):
                raise SessionNotReadyError(
                    state, f"设备当前状态为 {state}，不能设置表情"
                )
            self._link.enqueue(
                build(CMD_FACE, bytes([face])),
                before_write=before_write,
                on_done=on_write,
                require_send_gate=True,
            )

    def send_heartbeat(self, *, on_write: WriteCallback | None = None) -> bool:
        """入队 0x04 心跳请求（合并且优先于用户写）。"""
        with self._mu:
            if self._closing or self._faulted:
                raise LinkClosedError("会话已关闭或故障")
            return self._link.enqueue_heartbeat(
                build(CMD_HEARTBEAT_REQ), on_done=on_write
            )

    def poll_status(self, *, on_write: WriteCallback | None = None) -> bool:
        """入队 0x06 催状态（系统帧，不占 SendGate），遵守 06 第 12.2 节至少间隔 1 秒规则。"""
        with self._mu:
            if self._closing or self._faulted:
                raise LinkClosedError("会话已关闭或故障")
            now = self._clock.monotonic()
            if (
                self._last_poll_sent_at is not None
                and (now - self._last_poll_sent_at) < POLL_MIN_INTERVAL_SEC
            ):
                return False
            self._link.enqueue(
                build(CMD_POLL_STATUS),
                on_done=on_write,
                require_send_gate=False,
            )
            self._last_poll_sent_at = now
            return True

    def check_uplink_timeout(self) -> bool:
        """按 06 第 12.1 / 12.3 节检查 9 秒无有效上行超时。返回本次是否触发离线转换。"""
        event: SessionEvent | None = None
        affected_cmd_ids: list[str] = []
        with self._mu:
            if not self._online or self._last_uplink is None:
                return False
            now = self._clock.monotonic()
            if (now - self._last_uplink) <= UPLINK_TIMEOUT_SEC:
                return False

            self._online = False
            if self._pending:
                affected_cmd_ids = [slot.cmd_id for slot in self._pending.values()]
                self._pending.clear()
                self._recovery_required = True
            self._state_revision += 1
            event = SessionEvent(
                kind="link",
                session_id=self._session_id,
                received_at=now,
                payload={
                    "device_id": self._device_pk,
                    "online": False,
                    "control_state": self.control_state,
                    "reason": "uplink_timeout",
                    "session_id": self._session_id,
                    "state_revision": self._state_revision,
                    "affected_cmd_ids": affected_cmd_ids,
                },
            )

        if affected_cmd_ids:
            self._mark_commands_unknown(affected_cmd_ids, reason="uplink_timeout")
        if event is not None:
            self._emit(event)
        return True

    # --- 接收处理（由 SerialLink 经主线程/回调调用） ---

    def _on_frame(self, frame: Frame, received_at: float) -> None:
        event: SessionEvent | None = None
        with self._mu:
            # 06 第 12.1 节：任一设备→主机有效完整帧均刷新 last_uplink 与 last_heartbeat
            self._last_uplink = received_at
            self._last_heartbeat = datetime.now(timezone.utc)
            self._online = True

            if frame.cmd == CMD_HEARTBEAT_ACK:
                # 06:220 / N17：收到 0x84 只刷新上行，绝不回发 0x04
                return

            if frame.cmd == CMD_STATUS:
                event = self._handle_status_locked(frame.data, received_at)
            elif frame.cmd == CMD_ACCEPTED:
                event = self._handle_accepted_locked(frame.data, received_at)
            elif frame.cmd == CMD_DONE:
                event = self._handle_done_locked(frame.data, received_at)
            elif frame.cmd == CMD_REJECT:
                event = self._handle_rejected_locked(frame.data, received_at)
            else:
                return

        if event is not None:
            self._emit(event)

    def _handle_status_locked(self, data: bytes, received_at: float) -> SessionEvent:
        if len(data) in (6, 9):
            first_snapshot = not self._snapshot_received
            parsed = decode_status(data)
            self._battery = parsed["battery"]
            self._voltage = (
                parsed["voltage_mv"] / 1000.0
                if parsed["voltage_mv"] is not None
                else None
            )
            self._action = parsed["action"]
            self._face = parsed["face"]
            self._music_state = parsed["music_state"]
            self._track = parsed["track"]
            self._volume = None  # 0x03 帧不含音量（06:225）
            self._weather_code = parsed["weather"]
            self._temp = parsed["temperature"]
            self._snapshot_received = True
            # 06 第 12.3 节：首次快照若设备仍报非空闲动作，保持 recovery_required 直到人工确认
            if first_snapshot and parsed["action"] not in (None, 0):
                self._recovery_required = True
        else:
            # 06 第 12.6 节：非 6/9 字节只刷新上行，状态字段置 None 并记诊断计数
            self.malformed_status_frames += 1
            self._clear_cached_status_locked()

        self._state_revision += 1
        snap = self.snapshot()
        return SessionEvent(
            kind="state",
            session_id=self._session_id,
            received_at=received_at,
            payload={
                "device_id": snap.device_pk,
                "online": snap.online,
                "control_state": snap.control_state,
                "session_id": snap.session_id,
                "state_revision": snap.state_revision,
                "battery": snap.battery,
                "voltage": snap.voltage,
                "action": snap.action,
                "face": snap.face,
                "music_state": snap.music_state,
                "track": snap.track,
                "volume": snap.volume,
                "weather_code": snap.weather_code,
                "temp": snap.temp,
            },
        )

    def _handle_accepted_locked(self, data: bytes, received_at: float) -> SessionEvent:
        if len(data) < 2:
            self.orphan_frames += 1
            return SessionEvent("orphan", self._session_id, received_at, {"cmd": CMD_ACCEPTED})
        seq = data[1]
        slot = self._pending.get(seq)
        if slot is None:
            self.orphan_frames += 1
            return SessionEvent(
                "orphan",
                self._session_id,
                received_at,
                {"cmd": CMD_ACCEPTED, "seq": seq},
            )
        return SessionEvent(
            "accepted",
            self._session_id,
            received_at,
            {"cmd_id": slot.cmd_id, "seq": seq, "action": slot.action},
        )

    def _handle_done_locked(self, data: bytes, received_at: float) -> SessionEvent:
        if len(data) < 2:
            self.orphan_frames += 1
            return SessionEvent("orphan", self._session_id, received_at, {"cmd": CMD_DONE})
        action, seq = data[0], data[1]
        slot = self._pending.get(seq)
        if slot is None or slot.action != action:
            self.orphan_frames += 1
            return SessionEvent(
                "orphan",
                self._session_id,
                received_at,
                {"cmd": CMD_DONE, "seq": seq, "action": action},
            )
        self._pending.pop(seq, None)
        return SessionEvent(
            "done",
            self._session_id,
            received_at,
            {"cmd_id": slot.cmd_id, "seq": seq, "action": action},
        )

    def _handle_rejected_locked(self, data: bytes, received_at: float) -> SessionEvent:
        if len(data) < 2:
            self.orphan_frames += 1
            return SessionEvent("orphan", self._session_id, received_at, {"cmd": CMD_REJECT})
        error_code, seq = data[0], data[1]
        slot = self._pending.pop(seq, None)
        if slot is None:
            self.orphan_frames += 1
            return SessionEvent(
                "orphan",
                self._session_id,
                received_at,
                {"cmd": CMD_REJECT, "seq": seq, "error_code": error_code},
            )
        return SessionEvent(
            "rejected",
            self._session_id,
            received_at,
            {
                "cmd_id": slot.cmd_id,
                "seq": seq,
                "action": slot.action,
                "error_code": error_code,
            },
        )

    def _on_revoke(self, event: RevokeEvent) -> None:
        """SendGate 撤销后清理本设备缓存并同步交接/纪元状态（06 §9 / S01）。"""
        if event.device_pk is not None and event.device_pk != self._device_pk:
            return
        with self._mu:
            if event.kind in ("unbind", "account_delete"):
                self._handover_required = True
                self._prepared = False
                self._recovery_required = True
                self._snapshot_received = False
                self._clear_cached_status_locked()
                if event.new_be is not None:
                    self._be = event.new_be
                self._state_revision += 1
            elif event.kind == "claim":
                if event.new_be is not None:
                    self._be = event.new_be
                self._snapshot_received = False
                self._clear_cached_status_locked()
                self._state_revision += 1

    def _clear_cached_status_locked(self) -> None:
        self._battery = None
        self._voltage = None
        self._action = None
        self._face = None
        self._music_state = None
        self._track = None
        self._volume = None
        self._weather_code = None
        self._temp = None

    def _on_link_fault(self, reason: str) -> None:
        self._enter_fault(reason)
        self._emit(
            SessionEvent(
                kind="fault",
                session_id=self._session_id,
                received_at=self._clock.monotonic(),
                payload={"device_id": self._device_pk, "reason": reason},
            )
        )

    # --- 内部工具 ---

    def _assert_writable_locked(self) -> None:
        if self._closing:
            raise LinkClosedError("设备会话正在关闭，拒绝新操作")
        if self._faulted or self._link.faulted:
            raise SessionFaultedError(
                self._fault_reason or self._link.fault_reason or "faulted"
            )
        if not self._started:
            raise SessionNotReadyError("unconfigured", "设备会话尚未启动")

    def _ensure_db_lock_or_fault(self) -> None:
        """锁外验 DB 实例锁：失锁时先标 faulted 再关串口，绝不在持有 self._mu 时 join 线程。"""
        if self._process_lock is not None and not self._process_lock.still_held():
            self._enter_fault("db_lock_lost")
            self._link.close(timeout=0.5)
            raise SessionFaultedError("db_lock_lost")

    def _enter_fault(self, reason: str) -> None:
        with self._mu:
            if not self._faulted:
                self._faulted = True
                self._fault_reason = reason
                self._state_revision += 1

    def _persist_last_seq_locked(self, seq: int) -> None:
        """在 write 前把 last_seq 持久化到 DeviceSessionRecord；DB 异常立刻 faulted。"""
        db = self._session_factory()
        try:
            rec = (
                db.query(DeviceSessionRecord)
                .filter(DeviceSessionRecord.id == self._session_record_id)
                .first()
            )
            if rec is None:
                raise RuntimeError("DeviceSessionRecord 丢失")
            rec.last_seq = seq
            db.commit()
        except Exception as exc:
            db.rollback()
            self._enter_fault(f"db_seq_persist_error:{type(exc).__name__}")
            raise SessionFaultedError(
                self._fault_reason or "db_seq_persist_error"
            ) from exc
        finally:
            db.close()

    def _mark_commands_unknown(self, cmd_ids: list[str], *, reason: str) -> None:
        db = self._session_factory()
        try:
            rows = (
                db.query(CommandLog)
                .filter(
                    CommandLog.device_pk == self._device_pk,
                    CommandLog.msg_id.in_(cmd_ids),
                    CommandLog.status.in_((CMD_STATUS_PENDING, CMD_STATUS_ACCEPTED)),
                )
                .all()
            )
            now_dt = datetime.now()
            for row in rows:
                row.status = CMD_STATUS_UNKNOWN
                row.reason = reason
                row.revision = (row.revision or 0) + 1
                row.finished_at = now_dt
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("超时标记命令为 unknown 时写库失败")
        finally:
            db.close()

    def _emit(self, event: SessionEvent) -> None:
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:
                logger.exception("DeviceSession 事件回调异常: kind=%s", event.kind)
