"""唯一设备会话与生命周期管理（BA02 第 1、3、4、5 条）。

职责：
    - 进程内一台物理/模拟设备只对应一个 DeviceSession 实例，串联：
        DeviceSessionRecord（数据库会话与 seq 持久化）
        ↔ ProcessLock（DB 实例锁写前验活）
        ↔ SendGate（发送与权限撤销互斥协调）
        ↔ SerialLink（单线程串口收发与有界队列）
    - 启动时清查旧会话与未终结命令：旧未终结命令一律改 unknown、绝不重发；
      默认进入 recovery_required，只有携带匹配的准备标记且收到新会话有效 0x03 快照
      后才允许进入 ready。
    - 序号 1..255 在本会话内绝不复用：先持久化 last_seq（锁外写库，不阻塞收帧）、
      先登记 pending 映射、再入队写出；第 256 条直接拒绝（SeqExhaustedError），零 write。
    - 看门狗/上行超时（06 第 12.3 节）结束后，有效上行恢复时新建 session_id 并归零 seq；
      认领切换绑定纪元（06:302）时同样轮换 session_id、清 pending 与缓存、归零 seq。
    - 任一数据库或串口致命异常、或 DB 锁丢失（still_held()=False）立即进入 faulted，
      停止发送并关口，绝不降级成无锁工作。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.link.frame import Frame, build
from app.link.lock import ProcessLock
from app.link.send_gate import RevokeEvent, SendGate
from app.link.serial_link import (
    BeforeWriteHook,
    LinkClosedError,
    QueueFullError,
    SerialLink,
    TRANSPORT_OK,
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
HEARTBEAT_INTERVAL_SEC = 3.0  # 06:219 后端每 3 秒发 04
UPLINK_TIMEOUT_SEC = 9.0  # 06 第 12.1 节：9 秒无有效上行即 offline
POLL_MIN_INTERVAL_SEC = 1.0  # 06 第 12.2 节：同一设备两次 06 至少间隔 1 秒

SUPPORTED_CORE_ACTIONS: tuple[int, ...] = (0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36)
SUPPORTED_ALL_ACTIONS: tuple[int, ...] = (
    0x29, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36,
    0x37, 0x38, 0x39, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x48, 0x49,
)


class SessionError(Exception):
    """设备会话异常基类。"""


class SessionNotReadyError(SessionError):
    """设备未处于可接受控制的状态（如 offline / recovery_required / handover_required / busy）。"""



    def __init__(self, control_state: str, message: str) -> None:
        """记录当前控制态，供上层拼出错误原因。"""
        super().__init__(message)
        self.control_state = control_state


class SeqExhaustedError(SessionError):
    """本会话序号 1..255 已耗尽（06:290 → 40900 / seq_exhausted）。"""

    reason = "seq_exhausted"


class SessionFaultedError(SessionError):
    """会话因 DB/串口/锁丢失进入故障态，禁止新发送。"""



    def __init__(self, reason: str) -> None:
        """记录故障原因，便于日志与诊断。"""
        super().__init__(f"设备会话已故障（{reason}），停止发送")
        self.reason = reason


class _SystemClock:



    def monotonic(self) -> float:
        """读取系统单调时钟。"""
        return time.monotonic()


@dataclass(frozen=True)
class PendingSlot:
    cmd_id: str
    seq: int
    action: int
    be: int
    created_at: float
    deadline: float | None = None
    accepted: bool = False
    uncertain: bool = False


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
        loop: asyncio.AbstractEventLoop | None = None,
        prepared_marker: tuple[int, str | None] | None = None,
        auto_prepare_sim: bool = False,
        bench_mode: bool = False,
        on_event: EventCallback | None = None,
        supported_actions: tuple[int, ...] = SUPPORTED_CORE_ACTIONS,
    ) -> None:
        """初始化会话标识、序号、待确认指令表与状态缓存。"""
        self._device_pk = device_pk
        self._session_factory = session_factory
        self._link = link
        self._process_lock = process_lock
        self._send_gate = send_gate
        self._clock: Clock = clock if clock is not None else _SystemClock()
        self._loop = loop
        self._prepared_marker = prepared_marker
        self._auto_prepare_sim = auto_prepare_sim
        self._bench_mode = bench_mode
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
        self._session_ended_by_timeout = False
        self._online = False
        self._last_uplink: float | None = None
        # 与全后端（models.py / devices.py / presence.py）统一采用本地 naive datetime
        self._last_heartbeat: datetime | None = None
        self._last_poll_sent_at: float | None = None
        self._poll_timer: threading.Timer | None = None
        self._desired_face: tuple[int, float, int] | None = None  # (face, written_at, retries)

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
        self._motion_reserving: bool = False
        self._session_record_ready = threading.Event()
        self._session_record_ready.set()
        self._unregister_revoke: Callable[[], None] | None = None
        self.orphan_frames: int = 0
        self.malformed_status_frames: int = 0
        self.recovered_unknown_commands: int = 0

    # --- 只读属性 ---



    @property
    def device_pk(self) -> int:
        """返回设备主键。"""
        return self._device_pk



    @property
    def session_id(self) -> str:
        """返回当前会话 ID。"""
        with self._mu:
            return self._session_id



    @property
    def be(self) -> int:
        """返回当前绑定纪元。"""
        with self._mu:
            return self._be



    @property
    def last_seq(self) -> int:
        """返回本会话已用到的最大指令序号。"""
        with self._mu:
            return self._last_seq



    @property
    def remaining_seq(self) -> int:
        """返回本会话剩余可用序号数量。"""
        with self._mu:
            return max(0, MAX_SEQ - self._last_seq)



    @property
    def online(self) -> bool:
        """设备是否在线（9 秒内有有效上行）。"""
        with self._mu:
            return self._online



    @property
    def needs_initial_status(self) -> bool:
        with self._mu:
            return (
                self._bench_mode
                and self._last_poll_sent_at is None
                and self._face is None
                and self._battery is None
            )

    @property
    def fault_reason(self) -> str | None:
        with self._mu:
            return self._fault_reason or self._link.fault_reason

    @property
    def pending_seqs(self) -> dict[int, PendingSlot]:
        """返回待确认指令表的副本。"""
        with self._mu:
            return dict(self._pending)



    @property
    def control_state(self) -> str:
        """严格按 06 第 12.1 节（06:346）优先级裁决 control_state：
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
            if (
                self._pending
                or self._motion_reserving
                or (self._action not in (None, 0))
            ):
                return "busy"
            if self._snapshot_received:
                return "ready"
            return "unconfigured"



    def snapshot(self) -> SessionSnapshot:
        """生成对外的只读状态快照。"""
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



    def set_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        """绑定事件循环，并把循环同步给链路层的回调。"""
        self._loop = loop
        if loop is not None:
            self._link.set_callbacks(loop=loop)

    # --- 生命周期 ---



    def start(self) -> None:
        """启动会话（BA02 第 3 条）：
        1. 读出旧会话与未终结命令，旧未终结改 unknown，绝不重发；
        2. 核对准备标记，默认 recovery_required；
        3. 新建 DeviceSessionRecord(state='open', last_seq=0) 并启动串口线程。
        """
        self._ensure_db_lock_or_fault()

        with self._mu:
            if self._started:
                raise RuntimeError("DeviceSession 已启动，不要重复 start")

        now_dt = datetime.now()
        db = self._session_factory()
        try:
            device = db.query(Device).filter(Device.id == self._device_pk).first()
            if device is None:
                raise SessionError(f"设备不存在：device_pk={self._device_pk}")

            be = device.be
            handover_required = device.handover_state != "ready"

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
                cmd.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                cmd.finished_at = None
            recovered_count = len(unfinished)

            # 3. 决定是否通过准备门禁（06:299）：
            #    支持显式 prepared_marker、DB 一次性准备标记（state='prepared'，供 BA04/BB04 CLI 落库）、
            #    或 SIM 自动准备；消费后标记改 'consumed'，下次重启不复用。
            if handover_required:
                prepared = False
                recovery_required = True
            elif self._prepared_marker is not None and self._prepared_marker == (
                be,
                prev_session_id,
            ):
                prepared = True
                recovery_required = False
            elif (
                latest_prev is not None
                and latest_prev.state == "prepared"
                and latest_prev.be == be
                and not open_records
                and recovered_count == 0
            ):
                latest_prev.state = "consumed"
                latest_prev.ended_at = latest_prev.ended_at or now_dt
                prepared = True
                recovery_required = False
            elif self._auto_prepare_sim and recovered_count == 0:
                prepared = True
                recovery_required = False
            else:
                prepared = False
                recovery_required = True

            # 4. 登记本次新会话记录
            new_rec = DeviceSessionRecord(
                device_pk=self._device_pk,
                be=be,
                session_id=self._session_id,
                state="open",
                last_seq=0,
                started_at=now_dt,
            )
            db.add(new_rec)
            db.commit()
            new_rec_id = new_rec.id
        except SessionError:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            self._enter_fault(f"db_startup_error:{type(exc).__name__}")
            raise SessionFaultedError(
                self._fault_reason or "db_startup_error"
            ) from exc
        finally:
            db.close()

        with self._mu:
            self._be = be
            self._handover_required = handover_required
            self._prepared = prepared
            self._recovery_required = recovery_required
            self._session_record_id = new_rec_id
            self.recovered_unknown_commands = recovered_count
            if self._bench_mode and not handover_required:
                # 人工监护联调模式：链路已打开即置在线就绪，方便无上行回包时直接测下行帧
                self._online = True
                self._snapshot_received = True
                self._last_uplink = self._clock.monotonic()
                self._last_heartbeat = datetime.now()

            self._link.set_callbacks(
                on_frame=self._on_frame,
                on_fault=self._on_link_fault,
                loop=self._loop,
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
            self._cancel_poll_timer_locked()
            unreg = self._unregister_revoke
            self._unregister_revoke = None

        if unreg is not None:
            unreg()

        self._link.close(timeout=timeout)
        # 若后台线程池正在插入轮换后的新会话记录，短暂等待其落位后再统一置 closed
        with self._mu:
            ready_ev = self._session_record_ready
        ready_ev.wait(timeout=min(timeout, 1.0))

        with self._mu:
            rec_id = self._session_record_id
            self._session_record_id = None

        if rec_id is not None:
            self._close_session_record(rec_id)

    # --- 下行控制 ---



    def send_motion(
        self,
        cmd_id: str,
        action: int,
        *,
        expected_session_id: str | None = None,
        on_write: WriteCallback | None = None,
        before_write: BeforeWriteHook | None = None,
    ) -> int:
        """分配 seq（1..255 锁外先落库）→ 先登记 pending → 再入队写 0x01 动作帧（BA02 第 4 条）。"""
        self._ensure_db_lock_or_fault()
        # 若刚经历超时恢复且后台线程池正在落库新会话记录，等其就绪再读 rec_id
        with self._mu:
            ready_ev = self._session_record_ready
        ready_ev.wait(timeout=5.0)

        # 阶段 1（微秒级持锁）：校验状态并预约运动槽，绝不在持锁期间写库（P4）
        with self._mu:
            self._assert_writable_locked()
            state = self.control_state
            if state != "ready":
                raise SessionNotReadyError(
                    state, f"设备当前状态为 {state}，不能发起新运动"
                )
            if expected_session_id is not None and expected_session_id != self._session_id:
                raise SessionNotReadyError(state, '设备会话已切换')
            if action not in self._supported_actions:
                raise ValueError(f"动作码 0x{action:02X} 不在当前允许列表内")
            if self._pending or self._motion_reserving:
                raise SessionNotReadyError("busy", "设备已有在途运动指令")

            # 第 256 条显式拒绝，绝不复用序号，零 write（BA02 判据二 / N09）
            if self._last_seq >= MAX_SEQ:
                self._recovery_required = True
                raise SeqExhaustedError(
                    "当前会话序号 1..255 已耗尽，请停止控制并执行人工会话恢复"
                )

            rec_id = self._session_record_id
            if rec_id is None:
                raise SessionNotReadyError(
                    "unconfigured", "当前会话记录尚未就绪，暂不能发起新运动"
                )

            next_seq = self._last_seq + 1
            expected_sid = self._session_id
            self._motion_reserving = True

        # 阶段 2（锁外写库）：先持久化 last_seq，避免 DB 抖动阻塞 _on_frame 收帧
        try:
            self._persist_last_seq(rec_id, next_seq)
        except SessionFaultedError:
            with self._mu:
                self._motion_reserving = False
            self._link.close(timeout=0.5)
            raise

        # 阶段 3（微秒级持锁）：复核阶段 2 期间未发生关闭/故障/解绑/超时切换，再登记 pending 并入队
        with self._mu:
            self._motion_reserving = False
            if self._closing:
                raise LinkClosedError("设备会话正在关闭，拒绝新操作")
            if self._faulted or self._link.faulted:
                raise SessionFaultedError(
                    self._fault_reason or self._link.fault_reason or "faulted"
                )
            if (
                self._session_id != expected_sid
                or self._session_record_id != rec_id
                or self._handover_required
                or not self._online
                or not self._prepared
                or self._recovery_required
            ):
                raise SessionNotReadyError(
                    self.control_state, "会话在持久化序号期间已解绑、离线或切换"
                )
            self._last_seq = next_seq
            self._state_revision += 1
            self._pending[next_seq] = PendingSlot(
                cmd_id=cmd_id,
                seq=next_seq,
                action=action,
                be=self._be,
                created_at=self._clock.monotonic(),
            )

            def _handle_motion_write(outcome: WriteOutcome) -> None:
                # 06:116 确定未写失败可释放运动槽；可能部分写保持 recovery_required
                """写入结果回调：确定未写就释放运动槽，部分写转不确定并置恢复态。"""
                with self._mu:
                    if outcome.transport == TRANSPORT_WRITE_FAILED:
                        cur = self._pending.get(next_seq)
                        if cur is not None and cur.cmd_id == cmd_id:
                            self._pending.pop(next_seq, None)
                            self._state_revision += 1
                    else:
                        cur = self._pending.get(next_seq)
                        if cur and cur.cmd_id == cmd_id and self._session_id == expected_sid:
                            if outcome.transport == TRANSPORT_PARTIAL_WRITE:
                                self._state_revision += 1
                                self._pending[next_seq] = replace(cur, uncertain=True, deadline=None)
                                self._recovery_required = True
                            elif not cur.accepted and not cur.uncertain and outcome.written_at is not None:
                                self._pending[next_seq] = replace(cur, deadline=outcome.written_at + .600)
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
                # 确定未进入写队列时释放本次 pending 槽（已持久化的 seq 不回滚复用）
                self._pending.pop(next_seq, None)
                raise

            return next_seq



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
            def _after_face_write(outcome: WriteOutcome) -> None:
                if outcome.transport == TRANSPORT_OK:
                    with self._mu:
                        written_at = (
                            outcome.written_at
                            if outcome.written_at is not None
                            else self._clock.monotonic()
                        )
                        self._desired_face = (face, written_at, 0)
                        self._request_status_poll_locked()
                if on_write is not None:
                    on_write(outcome)

            self._link.enqueue(
                build(CMD_FACE, bytes([face])),
                before_write=before_write,
                on_done=_after_face_write,
                require_send_gate=True,
            )

    def _cancel_poll_timer_locked(self) -> None:
        """取消待触发的延迟状态轮询定时器（调用方需持锁）。"""
        timer = self._poll_timer
        self._poll_timer = None
        if timer is not None:
            timer.cancel()

    def _request_status_poll_locked(self) -> None:
        """催一次 0x06 拉新状态（0x07 表情写线成功后也走这里），避免网页苦等 5 秒周期；
        若仍在 1 秒冷却窗内则合并调度一次延迟 0x06，遵守 06 第 12.2 节。"""
        if self._closing or self._faulted:
            return
        now = self._clock.monotonic()
        if (
            self._last_poll_sent_at is None
            or (now - self._last_poll_sent_at) >= POLL_MIN_INTERVAL_SEC
        ):
            try:
                self._link.enqueue(
                    build(CMD_POLL_STATUS),
                    require_send_gate=False,
                )
                self._last_poll_sent_at = now
                self._cancel_poll_timer_locked()
            except (LinkClosedError, QueueFullError):
                pass
            return
        if self._poll_timer is None:
            delay = max(
                0.05,
                POLL_MIN_INTERVAL_SEC - (now - self._last_poll_sent_at) + 0.03,
            )
            timer = threading.Timer(delay, self._on_deferred_poll_timer)
            timer.daemon = True
            self._poll_timer = timer
            timer.start()



    def _on_deferred_poll_timer(self) -> None:
        """冷却窗结束后补发一次状态轮询；会话已关闭或故障则丢弃。"""
        with self._mu:
            self._poll_timer = None
            self._request_status_poll_locked()



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



    def check_command_timeout(self) -> None:
        """扫描待确认指令，超过期限的置为不确定并上报 unknown 事件。"""
        with self._mu:
            now = self._clock.monotonic()
            for seq, slot in list(self._pending.items()):
                if slot.deadline is not None and now >= slot.deadline:
                    if self._bench_mode:
                        self._pending.pop(seq, None)
                        if self._action == slot.action:
                            self._action = 0
                    else:
                        self._pending[seq] = replace(slot, uncertain=True, deadline=None)
                        self._recovery_required = True
                    self._state_revision += 1
                    self._emit(SessionEvent('unknown', self._session_id, now, {
                        'cmd_id': slot.cmd_id, 'seq': seq,
                        'reason': 'done_timeout' if slot.accepted else 'ack_timeout'}))



    def fail_closed(self, reason: str) -> None:
        """外部触发的失败关闭：先转故障态再关链路。"""
        self._on_link_fault(reason)
        self._link.close(timeout=.5)



    def check_uplink_timeout(self) -> bool:
        """按 06 第 12.1 / 12.3 节检查 9 秒无有效上行超时。

        触发时：
          - 标记 offline，结束当前 session_id（关闭 DB 会话记录）；
          - 若有未终结命令，置 unknown(uplink_timeout) 并标记 recovery_required；
          - 后续有效上行恢复时新建 session_id 并从 0 重新计 seq。
        """
        event: SessionEvent | None = None
        affected_cmd_ids: list[str] = []
        closed_rec_id: int | None = None
        with self._mu:
            if self._bench_mode:
                return False
            if not self._online or self._last_uplink is None:
                return False
            now = self._clock.monotonic()
            if (now - self._last_uplink) <= UPLINK_TIMEOUT_SEC:
                return False

            self._online = False
            self._session_ended_by_timeout = True
            closed_rec_id = self._session_record_id
            self._session_record_id = None
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

        # 锁外落库，不阻塞串口接收
        if closed_rec_id is not None:
            self._close_session_record(closed_rec_id)
        if affected_cmd_ids:
            self._mark_commands_unknown(affected_cmd_ids, event.session_id, reason="uplink_timeout")
        if event is not None:
            self._emit(event)
        return True

    # --- 接收处理（绑定 asyncio loop 时经 call_soon_threadsafe 在事件循环线程执行） ---



    def _on_frame(self, frame: Frame, received_at: float) -> None:
        # 06 §12.1：仅设备→主机有效帧刷新上行；忽略主机下行命令（防止 loop:// 或 RX-TX 短接误判在线）
        """接收入口：刷新上行时刻，再按命令字分发到各处理器。"""
        if frame.cmd not in (CMD_STATUS, CMD_HEARTBEAT_ACK, CMD_ACCEPTED, CMD_DONE, CMD_REJECT):
            return

        # 06:358 上行超时结束后首次恢复有效上行：先在锁外轮换新建 session_id 并归零 seq
        need_rotate = False
        with self._mu:
            need_rotate = self._session_ended_by_timeout
        if need_rotate:
            self._rotate_session_after_timeout()

        event: SessionEvent | None = None
        with self._mu:
            was_online = self._online
            prev_ctrl = self.control_state
            # 06 第 12.1 节：任一设备→主机有效完整帧均刷新 last_uplink 与 last_heartbeat
            self._last_uplink = received_at
            self._last_heartbeat = datetime.now()
            self._online = True

            if frame.cmd == CMD_HEARTBEAT_ACK:
                # 06:220 / N17：收到 0x84 只刷新上行，绝不回发 0x04；
                # 若此次心跳使在线/控制状态发生变化，推一次 link 事件让前端实时点亮在线状态。
                if not was_online or self.control_state != prev_ctrl:
                    self._state_revision += 1
                    event = SessionEvent(
                        kind="link",
                        session_id=self._session_id,
                        received_at=received_at,
                        payload={
                            "device_id": self._device_pk,
                            "online": self._online,
                            "control_state": self.control_state,
                            "reason": None,
                            "session_id": self._session_id,
                            "state_revision": self._state_revision,
                        },
                    )
                else:
                    return
            elif frame.cmd == CMD_STATUS:
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
        """解析 0x03 状态帧并更新缓存；长度异常只计数并把状态字段置空。"""
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
            # 06:358 末句：只有设备已上报空闲（action==0；0xFF 已解析为 None，未知不能证明空闲）
            # 且准备门禁已通过、无未终结命令、序号未耗尽时才解除本次不确定回到 ready。
            # 序号耗尽（06:290）只能靠重建会话解决，故不在此解除。
            elif (
                parsed["action"] == 0
                and self._prepared
                and not self._pending
                and self._last_seq < MAX_SEQ
            ):
                self._recovery_required = False

            self._state_revision += 1
            if self._desired_face is not None:
                want_face, sent_at, retries = self._desired_face
                if parsed["face"] == want_face:
                    self._desired_face = None
                elif (received_at - sent_at) < 3.0 and retries < 1:
                    self._desired_face = (want_face, sent_at, retries + 1)
                    self._request_status_poll_locked()
                else:
                    self._desired_face = None
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

        # 06 第 12.6 节：非 6/9 字节只刷新上行，把「该帧」状态字段置 null 并记诊断计数，
        # 不抹掉此前已缓存的有效设备状态。
        self.malformed_status_frames += 1
        self._state_revision += 1
        return SessionEvent(
            kind="state",
            session_id=self._session_id,
            received_at=received_at,
            payload={
                "device_id": self._device_pk,
                "online": self._online,
                "control_state": self.control_state,
                "session_id": self._session_id,
                "state_revision": self._state_revision,
                "battery": None,
                "voltage": None,
                "action": None,
                "face": None,
                "music_state": None,
                "track": None,
                "volume": None,
                "weather_code": None,
                "temp": None,
            },
        )



    def _handle_accepted_locked(self, data: bytes, received_at: float) -> SessionEvent:
        """处理 0x81 受理帧：命中待确认序号则标记已受理并延长完成期限。"""
        if len(data) != 2 or data[0] != CMD_ACTION:
            self.orphan_frames += 1
            return SessionEvent(
                "orphan", self._session_id, received_at, {"cmd": CMD_ACCEPTED}
            )
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
        if not slot.accepted and not slot.uncertain:
            self._pending[seq] = replace(slot, accepted=True, deadline=received_at + 30.)
        return SessionEvent(
            "accepted",
            self._session_id,
            received_at,
            {"cmd_id": slot.cmd_id, "seq": seq, "action": slot.action},
        )



    def _handle_done_locked(self, data: bytes, received_at: float) -> SessionEvent:
        """处理 0x02 完成帧：序号与动作都匹配才移除待确认项并上报 done。"""
        if len(data) != 2:
            self.orphan_frames += 1
            return SessionEvent(
                "orphan", self._session_id, received_at, {"cmd": CMD_DONE}
            )
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
        if self._action == action:
            self._action = 0
        if slot.uncertain:
            self._recovery_required = False
        self._state_revision += 1
        self._request_status_poll_locked()
        return SessionEvent(
            "done",
            self._session_id,
            received_at,
            {"cmd_id": slot.cmd_id, "seq": seq, "action": action},
        )



    def _handle_rejected_locked(self, data: bytes, received_at: float) -> SessionEvent:
        """处理 0x05 拒绝帧：移除待确认项并上报错误码。"""
        if len(data) != 2:
            self.orphan_frames += 1
            return SessionEvent(
                "orphan", self._session_id, received_at, {"cmd": CMD_REJECT}
            )
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
        if slot.uncertain:
            self._recovery_required = False
        self._state_revision += 1
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
        """SendGate 撤销后清理本设备缓存、隔离 (device, be, session) 并轮换会话（06 §9 / S01）。"""
        if event.device_pk != self._device_pk:
            return

        if event.kind in ("unbind", "account_delete"):
            old_rec_id: int | None = None
            with self._mu:
                old_rec_id = self._session_record_id
                self._session_record_id = None
                self._pending.clear()
                self._handover_required = True
                self._prepared = False
                self._recovery_required = True
                self._snapshot_received = False
                self._clear_cached_status_locked()
                if event.new_be is not None:
                    self._be = event.new_be
                self._state_revision += 1
            if old_rec_id is not None:
                self._close_session_record(old_rec_id)
            return

        if event.kind == "claim":
            # 新绑定纪元必须开启新 session_id、清 pending 与缓存、重置 seq=0 与 state_revision=0
            new_sid = str(uuid.uuid4())
            with self._mu:
                old_rec_id = self._session_record_id
                self._session_record_id = None
                if event.new_be is not None:
                    self._be = event.new_be
                new_be = self._be
                self._session_id = new_sid
                self._last_seq = 0
                self._state_revision = 0
                self._pending.clear()
                self._handover_required = False
                self._snapshot_received = False
                self._session_ended_by_timeout = False
                if self._auto_prepare_sim:
                    self._prepared = True
                    self._recovery_required = False
                self._clear_cached_status_locked()

            if old_rec_id is not None:
                self._close_session_record(old_rec_id)
            new_rec_id = self._open_session_record(new_be, new_sid)
            orphan_rec_id: int | None = None
            with self._mu:
                if self._session_id == new_sid and not self._closing:
                    self._session_record_id = new_rec_id
                else:
                    orphan_rec_id = new_rec_id
            if orphan_rec_id is not None:
                self._close_session_record(orphan_rec_id)



    def _rotate_session_after_timeout(self) -> None:
        """06:358 有效上行恢复后新建 session_id，序号与 state_revision 归零重新计数。

        内存轮换同步完成；DB 插入会话记录在绑定事件循环时丢给 run_in_executor，
        绝不在 asyncio 主循环线程里做同步写库（避免 DB 抖动顶住心跳与 HTTP）。
        """
        new_sid = str(uuid.uuid4())
        ready_ev = threading.Event()
        with self._mu:
            if not self._session_ended_by_timeout:
                return
            self._session_ended_by_timeout = False
            be = self._be
            self._session_id = new_sid
            self._session_record_id = None
            self._last_seq = 0
            self._state_revision = 0
            self._pending.clear()
            self._snapshot_received = False
            # 06:302 缓存按 (device, be, session) 隔离：旧会话遥测不得贴上新 session_id 继续对外
            self._clear_cached_status_locked()
            # 每次轮换使用独立 Event，避免连续两次轮换互相提前 set
            self._session_record_ready = ready_ev
            loop = self._loop

        def _persist_new_record() -> None:
            """在后台线程落库新会话记录，完成后置位就绪事件。"""
            orphan_rec_id: int | None = None
            try:
                new_rec_id = self._open_session_record(be, new_sid)
                with self._mu:
                    if self._session_id == new_sid and not self._closing:
                        self._session_record_id = new_rec_id
                    else:
                        orphan_rec_id = new_rec_id
                # 落库完成前会话若已关闭或再次轮换，在锁外关掉孤立记录，绝不持 _mu 写库
                if orphan_rec_id is not None:
                    self._close_session_record(orphan_rec_id)
            finally:
                ready_ev.set()

        if loop is not None:
            try:
                if loop.is_running():
                    loop.run_in_executor(None, _persist_new_record)
                    return
            except RuntimeError:
                pass
        _persist_new_record()



    def _clear_cached_status_locked(self) -> None:
        """清空全部状态缓存，未知字段一律回到 None。"""
        self._battery = None
        self._voltage = None
        self._action = None
        self._face = None
        self._desired_face = None
        self._music_state = None
        self._track = None
        self._volume = None
        self._weather_code = None
        self._temp = None



    def _on_link_fault(self, reason: str) -> None:
        """链路故障回调：把会话转故障态并上报 fault 事件。"""
        logger.warning("设备会话进入故障态：device_pk=%s reason=%s", self._device_pk, reason)
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
        """写操作前置断言：已关闭、已故障或未启动时抛对应异常。"""
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
        """把会话切到故障态并记录首次原因。"""
        with self._mu:
            self._cancel_poll_timer_locked()
            self._desired_face = None
            if not self._faulted:
                self._faulted = True
                self._fault_reason = reason
                self._state_revision += 1



    def _open_session_record(self, be: int, session_id: str) -> int | None:
        """新建一条 open 状态会话记录并返回主键；写库失败转故障态。"""
        db = self._session_factory()
        try:
            rec = DeviceSessionRecord(
                device_pk=self._device_pk,
                be=be,
                session_id=session_id,
                state="open",
                last_seq=0,
                started_at=datetime.now(),
            )
            db.add(rec)
            db.commit()
            return rec.id
        except Exception as exc:
            db.rollback()
            self._enter_fault(f"db_session_open_error:{type(exc).__name__}")
            logger.exception("创建新 DeviceSessionRecord 失败")
            return None
        finally:
            db.close()



    def _close_session_record(self, rec_id: int) -> None:
        """把会话记录置为 closed；写库失败只记日志。"""
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



    def _persist_last_seq(self, rec_id: int | None, seq: int) -> None:
        """在 write 前把 last_seq 持久化到 DeviceSessionRecord（锁外执行）；DB 异常立刻 faulted。"""
        db = self._session_factory()
        try:
            rec = (
                db.query(DeviceSessionRecord)
                .filter(DeviceSessionRecord.id == rec_id)
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



    def _mark_commands_unknown(self, cmd_ids: list[str], sid: str, *, reason: str) -> None:
        """把指定指令批量置为 unknown 并写明原因。"""
        db = self._session_factory()
        try:
            rows = (
                db.query(CommandLog)
                .filter(
                    CommandLog.device_pk == self._device_pk,
                    CommandLog.msg_id.in_(cmd_ids),
                    CommandLog.session_id == sid,
                    CommandLog.status.in_((CMD_STATUS_PENDING, CMD_STATUS_ACCEPTED)),
                )
                .all()
            )
            now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
            for row in rows:
                row.status = CMD_STATUS_UNKNOWN
                row.reason = reason
                row.revision = (row.revision or 0) + 1
                row.updated_at = now_dt
                row.finished_at = None
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("超时标记命令为 unknown 时写库失败")
        finally:
            db.close()



    def _emit(self, event: SessionEvent) -> None:
        """06:185 事件统一在绑定的事件循环线程送达。

        check_uplink_timeout 由 main.py 放到 asyncio.to_thread 的工作线程执行，
        因此这里必须和 SerialLink._dispatch 一样经 call_soon_threadsafe 切回主循环；
        未绑定 loop（或 loop 已停）时退回同步调用，供单测与 CLI 使用。
        """
        if self._on_event is None:
            return
        loop = self._loop
        try:
            running_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if loop is None or running_loop is loop:
            # 未绑定 loop，或本就在事件循环线程（收帧链路）：直接同步送达，保持事件顺序
            self._run_event_callback(event)
            return
        try:
            if loop.is_running():
                loop.call_soon_threadsafe(self._run_event_callback, event)
                return
        except RuntimeError:
            pass
        self._run_event_callback(event)



    def _run_event_callback(self, event: SessionEvent) -> None:
        """真正调用事件回调，回调异常只记日志不外抛。"""
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception:
            logger.exception("DeviceSession 事件回调异常: kind=%s", event.kind)
