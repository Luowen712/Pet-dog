"""BA02 唯一会话与读写生命周期验收测试。

覆盖全部 5 条完成判据及关键 N 矩阵：
  - 判据一：重复启动被拒（HostProcessLock + ProcessLock + FastAPI lifespan）
  - 判据二：第 256 条 seq 耗尽显式拒收且零 write（N09）
  - 判据三：DB 锁连接丢失停止发送、进入 faulted 并关口退出（N07）
  - 判据四：串口线程回调通过 call_soon_threadsafe 投递，不直接改 Future
  - 判据五：重启把旧未终结命令标 unknown、不重发旧动作（N12）
  - 补充：SendGate 释锁后通知、32 队上限/心跳优先/1 秒排队过期（N30）、
         迟到旧帧记 orphan（N10）、0x84 不回显循环（N17）、loop:// 烟测。
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.link.device_session import (
    CMD_STATUS_PENDING,
    CMD_STATUS_UNKNOWN,
    DeviceSession,
    SeqExhaustedError,
    SessionEvent,
    SessionFaultedError,
    SessionNotReadyError,
)
from app.link.frame import Frame, build
from app.link.lock import HostProcessLock, LockUnavailable, ProcessLock
from app.link.send_gate import AuthContext, RevokeEvent, SendGate
from app.link.serial_link import (
    MAX_WRITE_QUEUE,
    TRANSPORT_OK,
    TRANSPORT_WRITE_FAILED,
    LinkClosedError,
    QueueFullError,
    SerialLink,
    WriteOutcome,
    open_port,
)
from app.link.simulator import (
    CMD_ACCEPTED,
    CMD_ACTION,
    CMD_DONE,
    CMD_HEARTBEAT_ACK,
    CMD_HEARTBEAT_REQ,
    CMD_POLL_STATUS,
    CMD_REJECT,
    CMD_STATUS,
    DEFAULT_STATUS,
    FakeClock,
    SimBytePort,
    SimulatedDevice,
)
from app.main import app
from app.models import CommandLog, Device, DeviceSessionRecord


def _mk_device(
    db,
    prefix: str = "BA02",
    *,
    handover_state: str = "ready",
    be: int = 0,
) -> Device:
    d = Device(
        device_id=f"{prefix}-{uuid.uuid4().hex[:8]}",
        name="BA02测试宠",
        be=be,
        status="claimable",
        handover_state=handover_state,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _wait_until(pred, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


class _RecordingPort:
    """记录所有写出帧并可手动注入接收帧的轻量内存端口。"""

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self._rx = bytearray()
        self._mu = threading.Lock()
        self._closed = False
        self.write_gate = threading.Event()
        self.write_gate.set()

    @property
    def is_open(self) -> bool:
        return not self._closed

    def inject_rx(self, data: bytes) -> None:
        with self._mu:
            self._rx += data

    def read(self, size: int = 1) -> bytes:
        with self._mu:
            if self._closed:
                raise OSError("port closed")
            chunk = bytes(self._rx[:size])
            del self._rx[:size]
            return chunk

    def write(self, data: bytes) -> int:
        self.write_gate.wait(timeout=2.0)
        with self._mu:
            if self._closed:
                raise OSError("port closed")
            self.written.append(bytes(data))
            return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        with self._mu:
            self._closed = True


# --- 1. 判据一：lifespan 取得主机锁 + DB 实例锁，重复启动被拒 ---


def test_lifespan_acquires_both_locks_and_rejects_duplicate(tmp_path):
    lock_file = tmp_path / "petdog-test.lock"
    db_lock_name = "petdog:test:life:" + uuid.uuid4().hex[:8]

    app.state.host_lock_path = lock_file
    app.state.db_lock_name = db_lock_name
    try:
        with TestClient(app) as client:
            assert app.state.host_lock.still_held() is True
            assert app.state.process_lock.still_held() is True

            # 运行中，第二份主机锁与第二份 DB 实例锁均必须被拒
            with pytest.raises(LockUnavailable):
                HostProcessLock(lock_file).acquire()
            with pytest.raises(LockUnavailable):
                ProcessLock(name=db_lock_name).acquire()

            # /api/health 按配置返回 mode 与 protocol_version，不暴露 COM
            resp = client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data == {"status": "ok", "mode": "sim", "protocol_version": "3.1"}

        # 退出 lifespan 后两把锁均释放，可再次取得
        h = HostProcessLock(lock_file)
        p = ProcessLock(name=db_lock_name)
        h.acquire()
        p.acquire()
        p.release()
        h.release()
    finally:
        for attr in ("host_lock_path", "db_lock_name"):
            if hasattr(app.state, attr):
                delattr(app.state, attr)


def test_lifespan_rolls_back_host_lock_when_db_lock_busy(tmp_path):
    """DB 实例锁被占用时拒绝启动，且必须回滚释放刚拿到的主机锁。"""
    lock_file = tmp_path / "petdog-rollback.lock"
    db_lock_name = "petdog:test:busy:" + uuid.uuid4().hex[:8]

    occupier = ProcessLock(name=db_lock_name)
    occupier.acquire()
    app.state.host_lock_path = lock_file
    app.state.db_lock_name = db_lock_name
    try:
        with pytest.raises(LockUnavailable):
            with TestClient(app):
                pass
        # 主机锁不得泄漏，立即可被其它进程取得
        check = HostProcessLock(lock_file)
        check.acquire()
        check.release()
    finally:
        occupier.release()
        for attr in ("host_lock_path", "db_lock_name"):
            if hasattr(app.state, attr):
                delattr(app.state, attr)


# --- 2. BA02 第 2 条：SendGate 最小实现与撤销协调接口 ---


def test_send_gate_commits_inside_lock_and_notifies_outside_lock():
    gate = SendGate(default_timeout=1.0)
    seen: list[RevokeEvent] = []
    ctx = AuthContext(uid=7, tv=2, device_pk=1, be=3)
    assert ctx.uid == 7

    def on_revoke(ev: RevokeEvent) -> None:
        # 监听器必须在释锁之后被调用：此时再次获取 gate.hold 绝不能死锁
        with gate.hold(timeout=0.5):
            seen.append(ev)

    unregister = gate.register_revoke_listener(on_revoke)
    try:
        def commit() -> str:
            # commit 期间锁必须正被持有（其他线程拿不到）
            assert gate._lock.locked() is True
            return "committed"

        res = gate.revoke_access(
            uid=7, device_pk=1, kind="unbind", commit_fn=commit, new_be=4
        )
        assert res == "committed"
        assert len(seen) == 1
        assert seen[0] == RevokeEvent(
            uid=7, device_pk=1, kind="unbind", new_tv=None, new_be=4
        )
    finally:
        unregister()


def test_send_gate_skips_listeners_when_commit_fails():
    gate = SendGate(default_timeout=1.0)
    called = False

    def on_revoke(_ev: RevokeEvent) -> None:
        nonlocal called
        called = True

    gate.register_revoke_listener(on_revoke)
    with pytest.raises(ValueError, match="boom"):
        gate.revoke_access(
            uid=1,
            device_pk=1,
            kind="password_change",
            commit_fn=lambda: (_ for _ in ()).throw(ValueError("boom")),
        )
    assert called is False


# --- 3. 写队列 32 上限、心跳合并优先不饿死、排队超 1 秒过期（N30） ---


def test_queue_limit_heartbeat_priority_and_expiry():
    clock = FakeClock()
    port = _RecordingPort()
    link = SerialLink(
        port,
        clock=clock,
        max_queue=MAX_WRITE_QUEUE,
        max_queue_wait=1.0,
        min_frame_gap=0.0,
        poll_interval=0.002,
    )

    # 启动前先把 32 格用户队列塞满（模拟表情刷屏）
    for i in range(MAX_WRITE_QUEUE):
        link.enqueue(build(0x07, bytes([i % 7])))
    with pytest.raises(QueueFullError):
        link.enqueue(build(0x07, b"\x00"))

    # 再连续入队两次心跳：必须合并为 1 条
    assert link.enqueue_heartbeat(build(CMD_HEARTBEAT_REQ)) is True
    assert link.enqueue_heartbeat(build(CMD_HEARTBEAT_REQ)) is False

    # 阻塞写口，让 I/O 线程取出第一帧时检查顺序
    link.start()
    try:
        assert _wait_until(lambda: len(port.written) == 33)
        # 第一帧必须是心跳 0x04（心跳优先于 32 条表情）
        assert port.written[0] == build(CMD_HEARTBEAT_REQ)
    finally:
        link.close()

    # 测试排队超过 1 秒过期不写出
    clock2 = FakeClock()
    port2 = _RecordingPort()
    outcomes: list[WriteOutcome] = []
    link2 = SerialLink(
        port2,
        clock=clock2,
        max_queue_wait=1.0,
        min_frame_gap=0.0,
        poll_interval=0.002,
    )
    link2.enqueue(build(0x07, b"\x01"), on_done=outcomes.append)
    clock2.advance(1.01)  # 入队后超过 1 秒才开始处理
    link2.start()
    try:
        assert _wait_until(lambda: len(outcomes) == 1)
        assert outcomes[0].transport == TRANSPORT_WRITE_FAILED
        assert outcomes[0].reason == "queue_expired"
        assert port2.written == []  # 确定未写到串口
    finally:
        link2.close()


# --- 4. 判据四：串口线程通过 loop.call_soon_threadsafe 投递，不直接改 Future ---


def test_callbacks_run_on_event_loop_thread_not_io_thread():
    async def _scenario() -> None:
        loop = asyncio.get_running_loop()
        loop_tid = threading.get_ident()
        callback_tids: list[int] = []
        got = asyncio.Event()
        received: list[Frame] = []

        sim_dev = SimulatedDevice()
        port = SimBytePort(sim_dev)

        def on_frame(frame: Frame, _received_at: float) -> None:
            callback_tids.append(threading.get_ident())
            received.append(frame)
            got.set()

        link = SerialLink(
            port,
            loop=loop,
            on_frame=on_frame,
            min_frame_gap=0.0,
            poll_interval=0.002,
        )
        link.start()
        try:
            link.enqueue_heartbeat(build(CMD_HEARTBEAT_REQ))
            await asyncio.wait_for(got.wait(), timeout=2.0)
        finally:
            link.close()

        assert len(received) == 1
        assert received[0].cmd == CMD_HEARTBEAT_ACK
        assert callback_tids == [loop_tid]

    asyncio.run(_scenario())


# --- 5. 判据五 & BA02 第 3 条：重启不重发旧动作 + 默认 recovery_required + 新快照才 ready ---


def test_restart_marks_unfinished_unknown_and_requires_prepared_plus_snapshot():
    db = SessionLocal()
    try:
        d = _mk_device(db, "RESTART")
        dev_id, dev_be = d.id, d.be
        old_sid = str(uuid.uuid4())
        db.add(
            DeviceSessionRecord(
                device_pk=dev_id, be=dev_be, session_id=old_sid, state="open", last_seq=5
            )
        )
        old_cmd_id = str(uuid.uuid4())
        db.add(
            CommandLog(
                device_id=d.device_id,
                device_pk=dev_id,
                msg_id=old_cmd_id,
                cmd=CMD_ACTION,
                action=0x31,
                status=CMD_STATUS_PENDING,
                seq=5,
                be=dev_be,
                revision=1,
                session_id=old_sid,
            )
        )
        db.commit()
    finally:
        db.close()

    # A. 无准备标记重启：旧命令改 unknown、零重发、即使收到 0x03 仍为 recovery_required
    port1 = _RecordingPort()
    link1 = SerialLink(port1, min_frame_gap=0.0, poll_interval=0.002)
    sess1 = DeviceSession(dev_id, SessionLocal, link1)
    sess1.start()
    try:
        assert sess1.recovered_unknown_commands == 1
        assert port1.written == []  # 重启绝不重发旧动作

        db = SessionLocal()
        try:
            old_rec = (
                db.query(DeviceSessionRecord)
                .filter(DeviceSessionRecord.session_id == old_sid)
                .first()
            )
            assert old_rec.state == "closed"
            assert old_rec.ended_at is not None

            old_cmd = (
                db.query(CommandLog).filter(CommandLog.msg_id == old_cmd_id).first()
            )
            assert old_cmd.status == CMD_STATUS_UNKNOWN
            assert old_cmd.reason == "session_restart"
            assert old_cmd.revision == 2
        finally:
            db.close()

        # 注入有效 0x03 快照，因未准备仍必须停在 recovery_required
        port1.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
        assert _wait_until(lambda: sess1.online is True)
        assert sess1.control_state == "recovery_required"
        with pytest.raises(SessionNotReadyError):
            sess1.send_motion(str(uuid.uuid4()), 0x31)
        prev_sid = sess1.session_id
    finally:
        sess1.close()

    # B. 带匹配的准备标记重启：未收快照前不 ready；收到有效 0x03 后才 ready
    port2 = _RecordingPort()
    link2 = SerialLink(port2, min_frame_gap=0.0, poll_interval=0.002)
    sess2 = DeviceSession(
        dev_id,
        SessionLocal,
        link2,
        prepared_marker=(dev_be, prev_sid),
    )
    sess2.start()
    try:
        assert sess2.control_state == "offline"
        # 仅收到心跳回包（未收新快照）：在线但仍未 ready
        port2.inject_rx(build(CMD_HEARTBEAT_ACK))
        assert _wait_until(lambda: sess2.online is True)
        assert sess2.control_state == "unconfigured"
        with pytest.raises(SessionNotReadyError):
            sess2.send_motion(str(uuid.uuid4()), 0x31)

        # 收到有效 9 字节 0x03 快照后进入 ready，且 mV→V 换算正确
        port2.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
        assert _wait_until(lambda: sess2.control_state == "ready")
        snap = sess2.snapshot()
        assert snap.battery == 87
        assert snap.voltage == pytest.approx(7.422)
        assert snap.face == 2
        assert snap.music_state is None
        assert snap.weather_code is None
        assert snap.temp == 20
    finally:
        sess2.close()


# --- 6. 判据二 & 第 4 条：pending/seq 先于 write；第 256 条拒收且零 write（N09） ---


def test_seq_and_pending_before_write_and_256th_rejected():
    db = SessionLocal()
    try:
        d = _mk_device(db, "SEQ255")
    finally:
        db.close()

    clock = FakeClock()
    sim_dev = SimulatedDevice(clock=clock)
    port = SimBytePort(sim_dev)
    events: list[SessionEvent] = []
    link = SerialLink(port, clock=clock, min_frame_gap=0.0, poll_interval=0.002)
    sess = DeviceSession(
        d.id,
        SessionLocal,
        link,
        clock=clock,
        auto_prepare_sim=True,
        on_event=events.append,
    )
    sess.start()
    try:
        # 先拉一次 0x03 快照让会话进入 ready
        assert sess.poll_status() is True
        assert _wait_until(lambda: sess.control_state == "ready")

        checked_before_write = {}

        def _verify_before_write() -> bool:
            # 此时尚未调用 port.write()：DB last_seq 与 pending 必须已经先登记
            check_db = SessionLocal()
            try:
                rec = (
                    check_db.query(DeviceSessionRecord)
                    .filter(DeviceSessionRecord.session_id == sess.session_id)
                    .first()
                )
                checked_before_write["db_last_seq"] = rec.last_seq
            finally:
                check_db.close()
            checked_before_write["has_pending_1"] = 1 in sess.pending_seqs
            return True

        cmd_id = str(uuid.uuid4())
        seq = sess.send_motion(cmd_id, 0x31, before_write=_verify_before_write)
        assert seq == 1
        assert _wait_until(lambda: any(e.kind == "accepted" for e in events))
        assert checked_before_write == {"db_last_seq": 1, "has_pending_1": True}

        # 推进 SIM 时钟让第 1 条完成并释放运动槽
        clock.advance(0.35)
        assert _wait_until(lambda: any(e.kind == "done" for e in events))
        assert sess.control_state == "ready"

        # 模拟本会话已经发完 255 号，验证第 256 条拒绝且零 write
        sess._last_seq = 255
        frames_before = sim_dev.stats.frames_in
        with pytest.raises(SeqExhaustedError):
            sess.send_motion(str(uuid.uuid4()), 0x31)
        assert sess.control_state == "recovery_required"
        time.sleep(0.03)
        assert sim_dev.stats.frames_in == frames_before  # 零 write
    finally:
        sess.close()


# --- 7. 判据三：DB 锁丢失停止发送、进入 faulted 并关口（N07） ---


def test_db_lock_loss_halts_writes_and_faults_session():
    class _SwitchableLock:
        def __init__(self) -> None:
            self.alive = True

        def still_held(self) -> bool:
            return self.alive

    db = SessionLocal()
    try:
        d = _mk_device(db, "LOCKLOST")
    finally:
        db.close()

    fake_lock = _SwitchableLock()
    port = _RecordingPort()
    events: list[SessionEvent] = []
    outcomes: list[WriteOutcome] = []

    link = SerialLink(
        port,
        lock_check=fake_lock.still_held,
        min_frame_gap=0.0,
        poll_interval=0.002,
    )
    sess = DeviceSession(
        d.id,
        SessionLocal,
        link,
        process_lock=fake_lock,  # type: ignore[arg-type]
        auto_prepare_sim=True,
        on_event=events.append,
    )
    sess.start()
    try:
        port.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
        assert _wait_until(lambda: sess.control_state == "ready")

        # 模拟 DB 锁连接在排队后、写出前断开
        port.write_gate.clear()
        fake_lock.alive = False
        link.enqueue(build(0x07, b"\x01"), on_done=outcomes.append)
        port.write_gate.set()

        assert _wait_until(lambda: sess.control_state == "faulted")
        assert len(port.written) == 0  # 失锁后绝不写出任何字节
        assert outcomes and outcomes[0].reason == "db_lock_lost"
        assert port.is_open is False
        assert any(e.kind == "fault" and e.payload["reason"] == "db_lock_lost" for e in events)

        with pytest.raises(SessionFaultedError):
            sess.send_motion(str(uuid.uuid4()), 0x31)
    finally:
        sess.close()


# --- 8. 迟到旧帧记 orphan（N10）与 0x84 不回显循环（N17） ---


def test_late_frames_recorded_as_orphan_and_heartbeat_ack_no_echo():
    db = SessionLocal()
    try:
        d = _mk_device(db, "ORPHAN")
    finally:
        db.close()

    port = _RecordingPort()
    events: list[SessionEvent] = []
    link = SerialLink(port, min_frame_gap=0.0, poll_interval=0.002)
    sess = DeviceSession(
        d.id,
        SessionLocal,
        link,
        auto_prepare_sim=True,
        on_event=events.append,
    )
    sess.start()
    try:
        # 注入 0x84 心跳确认：只刷新 online，不回发任何帧
        port.inject_rx(build(CMD_HEARTBEAT_ACK))
        port.inject_rx(build(CMD_HEARTBEAT_ACK))
        assert _wait_until(lambda: sess.online is True)
        time.sleep(0.03)
        assert port.written == []

        # 注入旧会话迟到的 81/02/05（seq=99 未在本会话登记）
        port.inject_rx(build(CMD_ACCEPTED, bytes([CMD_ACTION, 99])))
        port.inject_rx(build(CMD_DONE, bytes([0x31, 99])))
        port.inject_rx(build(CMD_REJECT, bytes([0x04, 99])))
        assert _wait_until(lambda: sess.orphan_frames == 3)
        # 首次 0x84 触发 offline→online 推 1 条 link 事件，第 2 条 0x84 不重复推送，随后 3 条迟到帧为 orphan
        assert [e.kind for e in events] == ["link", "orphan", "orphan", "orphan"]
        assert events[0].payload["online"] is True
    finally:
        sess.close()


# --- 9. 优雅关闭先拒新操作并关闭会话记录 + loop:// 烟测 ---


def test_graceful_close_and_loop_url_smoke():
    db = SessionLocal()
    try:
        d = _mk_device(db, "CLOSE")
    finally:
        db.close()

    port = open_port("loop://")
    received: list[Frame] = []
    link = SerialLink(
        port,
        on_frame=lambda f, _t: received.append(f),
        min_frame_gap=0.0,
        poll_interval=0.002,
    )
    link.start()
    try:
        outcomes: list[WriteOutcome] = []
        link.enqueue(build(CMD_POLL_STATUS), on_done=outcomes.append)
        assert _wait_until(lambda: len(received) == 1)
        assert received[0].cmd == CMD_POLL_STATUS
        assert outcomes and outcomes[0].transport == TRANSPORT_OK
    finally:
        link.close()

    # 关闭后新操作立即被拒
    with pytest.raises(LinkClosedError):
        link.enqueue(build(CMD_POLL_STATUS))

    # 验证 DeviceSession.close 更新 DB 会话记录状态为 closed
    p2 = _RecordingPort()
    l2 = SerialLink(p2, min_frame_gap=0.0, poll_interval=0.002)
    s2 = DeviceSession(d.id, SessionLocal, l2, auto_prepare_sim=True)
    s2.start()
    sid = s2.session_id
    s2.close()

    with pytest.raises(LinkClosedError):
        s2.send_motion(str(uuid.uuid4()), 0x31)

    db = SessionLocal()
    try:
        rec = (
            db.query(DeviceSessionRecord)
            .filter(DeviceSessionRecord.session_id == sid)
            .first()
        )
        assert rec is not None
        assert rec.state == "closed"
        assert rec.ended_at is not None
    finally:
        db.close()


# --- 10. 代码审查补测：确定未写自动释放运动槽 + SendGate 撤销清空设备缓存 ---


def test_aborted_write_releases_pending_slot_and_revoke_clears_cache():
    db = SessionLocal()
    try:
        d = _mk_device(db, "GATECACHE")
        dev_id = d.id
    finally:
        db.close()

    gate = SendGate(default_timeout=1.0)
    port = _RecordingPort()
    link = SerialLink(port, min_frame_gap=0.0, poll_interval=0.002)
    sess = DeviceSession(
        dev_id,
        SessionLocal,
        link,
        send_gate=gate,
        auto_prepare_sim=True,
    )
    sess.start()
    try:
        port.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
        assert _wait_until(lambda: sess.control_state == "ready")
        assert sess.snapshot().battery == 87

        # before_write 返回 False → 确定未写（TRANSPORT_WRITE_FAILED）→ 自动释放运动槽
        outcomes: list[WriteOutcome] = []
        sess.send_motion(
            str(uuid.uuid4()),
            0x31,
            before_write=lambda: False,
            on_write=outcomes.append,
        )
        assert _wait_until(lambda: len(outcomes) == 1)
        assert outcomes[0].transport == TRANSPORT_WRITE_FAILED
        assert port.written == []
        assert sess.pending_seqs == {}
        assert sess.control_state == "ready"

        # 触发 SendGate 解绑撤销：必须清旧缓存并切 handover_required（S01）
        gate.revoke_access(
            uid=1,
            device_pk=dev_id,
            kind="unbind",
            commit_fn=lambda: None,
            new_be=1,
        )
        snap = sess.snapshot()
        assert snap.control_state == "handover_required"
        assert snap.be == 1
        assert snap.battery is None
        assert snap.voltage is None
        assert snap.face is None
    finally:
        sess.close()


# --- 11. P1 验收：lifespan 自动装配 DeviceSession、绑 loop/锁/SendGate 并跑后台心跳 ---


def test_lifespan_assembles_device_session_and_runs_heartbeat_ticker(tmp_path):
    db = SessionLocal()
    try:
        d = _mk_device(db, "LIFE_SESS")
        dev_id = d.id
    finally:
        db.close()

    sim_dev = SimulatedDevice()
    port = SimBytePort(sim_dev)

    app.state.host_lock_path = tmp_path / "life-sess.lock"
    app.state.db_lock_name = "petdog:test:lifesess:" + uuid.uuid4().hex[:8]
    app.state.device_pk = dev_id
    app.state.serial_port_override = port
    app.state.heartbeat_interval_sec = 0.03
    app.state.timeout_check_interval_sec = 0.03
    app.state.min_frame_gap_sec = 0.0
    try:
        with TestClient(app):
            sess = app.state.device_session
            assert sess is not None
            assert sess.device_pk == dev_id
            assert sess._link._lock_check is not None
            assert sess._link._send_gate is app.state.send_gate
            assert sess._link._loop is not None

            # 后台 0x04 心跳上线后自动发首帧 0x06 催状态 → SIM 自动达到 ready
            assert _wait_until(lambda: sess.control_state == "ready", timeout=2.0)
            assert sess.online is True
            assert sim_dev.stats.frames_in >= 2
            sid = sess.session_id

        # 退出 lifespan 后会话已关闭、DB 记录标 closed
        assert app.state.device_session is None
        db = SessionLocal()
        try:
            rec = (
                db.query(DeviceSessionRecord)
                .filter(DeviceSessionRecord.session_id == sid)
                .first()
            )
            assert rec is not None
            assert rec.state == "closed"
        finally:
            db.close()
    finally:
        for attr in (
            "host_lock_path",
            "db_lock_name",
            "device_pk",
            "serial_port_override",
            "heartbeat_interval_sec",
            "timeout_check_interval_sec",
            "min_frame_gap_sec",
        ):
            if hasattr(app.state, attr):
                delattr(app.state, attr)


# --- 12. P2 验收：上行超时恢复与 claim 均轮换 session_id 并归零 seq ---


def test_timeout_recovery_and_claim_rotate_session_and_reset_seq():
    db = SessionLocal()
    try:
        d = _mk_device(db, "ROTATE")
        dev_id = d.id
    finally:
        db.close()

    clock = FakeClock()
    gate = SendGate(default_timeout=1.0)
    port = _RecordingPort()
    link = SerialLink(port, clock=clock, min_frame_gap=0.0, poll_interval=0.002)
    sess = DeviceSession(
        dev_id,
        SessionLocal,
        link,
        send_gate=gate,
        clock=clock,
        auto_prepare_sim=True,
    )
    sess.start()
    try:
        # 1. 上线收快照并发出 1 条动作（last_seq=1）
        port.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
        assert _wait_until(lambda: sess.control_state == "ready")
        assert sess.send_motion(str(uuid.uuid4()), 0x31) == 1
        assert sess.last_seq == 1
        sid1 = sess.session_id

        # 2. 超过 9 秒无上行 → 触发超时：offline、旧会话记录关闭、清 pending
        clock.advance(9.5)
        assert sess.check_uplink_timeout() is True
        assert sess.online is False
        assert sess.pending_seqs == {}

        db = SessionLocal()
        try:
            rec1 = (
                db.query(DeviceSessionRecord)
                .filter(DeviceSessionRecord.session_id == sid1)
                .first()
            )
            assert rec1.state == "closed"
        finally:
            db.close()

        # 3. 有效上行恢复 → 必须新建 session_id 且 seq 归零（06:358）
        port.inject_rx(build(CMD_HEARTBEAT_ACK))
        assert _wait_until(lambda: sess.online is True)
        sid2 = sess.session_id
        assert sid2 != sid1
        assert sess.last_seq == 0

        # 4. 触发 claim（新绑定纪元）→ 轮换 session_id、清 pending、seq 归零、be 更新（06:302）
        sess._last_seq = 9
        gate.revoke_access(
            uid=2,
            device_pk=dev_id,
            kind="claim",
            commit_fn=lambda: None,
            new_be=2,
        )
        sid3 = sess.session_id
        assert sid3 != sid2
        assert sess.be == 2
        assert sess.last_seq == 0
        assert sess.pending_seqs == {}

        db = SessionLocal()
        try:
            rec2 = (
                db.query(DeviceSessionRecord)
                .filter(DeviceSessionRecord.session_id == sid2)
                .first()
            )
            rec3 = (
                db.query(DeviceSessionRecord)
                .filter(DeviceSessionRecord.session_id == sid3)
                .first()
            )
            assert rec2.state == "closed"
            assert rec3 is not None and rec3.state == "open" and rec3.be == 2 and rec3.last_seq == 0
        finally:
            db.close()
    finally:
        sess.close()


# --- 12b. 复审项 A1：超时轮换后旧会话遥测不得贴上新 session_id（06:302）---


def test_timeout_rotation_clears_cached_status_for_new_session():
    db = SessionLocal()
    try:
        d = _mk_device(db, "ROT_CACHE")
        dev_id = d.id
    finally:
        db.close()

    clock = FakeClock()
    port = _RecordingPort()
    link = SerialLink(port, clock=clock, min_frame_gap=0.0, poll_interval=0.002)
    sess = DeviceSession(
        dev_id,
        SessionLocal,
        link,
        clock=clock,
        auto_prepare_sim=True,
    )
    sess.start()
    try:
        port.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
        assert _wait_until(lambda: sess.control_state == "ready")
        sid1 = sess.session_id
        snap1 = sess.snapshot()
        assert snap1.battery == 87 and snap1.action == 0
        assert sess.send_motion(str(uuid.uuid4()), 0x31) == 1

        # 超时只结束会话、此时尚未轮换：快照仍属旧 session_id，缓存可以保留
        clock.advance(9.5)
        assert sess.check_uplink_timeout() is True
        assert sess.session_id == sid1
        assert sess.snapshot().battery == 87

        # 有效上行恢复 → 轮换 session_id，旧会话遥测必须一并作废（06:302）
        port.inject_rx(build(CMD_HEARTBEAT_ACK))
        assert _wait_until(lambda: sess.online is True)
        assert _wait_until(lambda: sess.session_id != sid1)
        assert sess.last_seq == 0
        assert sess.control_state == "recovery_required"

        snap2 = sess.snapshot()
        assert snap2.session_id == sess.session_id
        assert snap2.battery is None
        assert snap2.voltage is None
        assert snap2.action is None
        assert snap2.face is None
        assert snap2.music_state is None
        assert snap2.track is None
        assert snap2.weather_code is None
        assert snap2.temp is None
    finally:
        sess.close()


# --- 12c. 复审项 A2：只有设备已上报空闲才解除 recovery_required（06:358）---


def test_recovery_required_clears_only_after_idle_status_on_valid_session():
    db = SessionLocal()
    try:
        d = _mk_device(db, "REC_EXIT")
        dev_id = d.id
    finally:
        db.close()

    clock = FakeClock()
    port = _RecordingPort()
    link = SerialLink(port, clock=clock, min_frame_gap=0.0, poll_interval=0.002)
    sess = DeviceSession(
        dev_id,
        SessionLocal,
        link,
        clock=clock,
        auto_prepare_sim=True,
    )
    sess.start()
    try:
        # 1. 造出 recovery_required：发出动作后上行超时，未终结命令转不确定
        port.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
        assert _wait_until(lambda: sess.control_state == "ready")
        assert sess.send_motion(str(uuid.uuid4()), 0x31) == 1
        clock.advance(9.5)
        assert sess.check_uplink_timeout() is True
        assert sess.control_state == "offline"  # offline 优先级高于 recovery_required
        port.inject_rx(build(CMD_HEARTBEAT_ACK))
        assert _wait_until(lambda: sess.control_state == "recovery_required")

        # 2. action=0xFF（未知）不能证明空闲，不得解除
        unknown = bytearray(DEFAULT_STATUS)
        unknown[1] = 0xFF
        port.inject_rx(build(CMD_STATUS, bytes(unknown)))
        assert _wait_until(lambda: sess.snapshot().action is None)
        assert sess.control_state == "recovery_required"

        # 3. 设备仍报非空闲动作，同样不得解除
        busy = bytearray(DEFAULT_STATUS)
        busy[1] = 0x31
        port.inject_rx(build(CMD_STATUS, bytes(busy)))
        assert _wait_until(lambda: sess.snapshot().action == 0x31)
        assert sess.control_state == "recovery_required"

        # 4. 上报空闲且已过准备门禁、无未终结命令 → 解除并回到 ready
        port.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
        assert _wait_until(lambda: sess.control_state == "ready")
        # 5. 解除后可再次下发动作，序号在新会话内从 1 重新计数（06:290）
        assert sess.send_motion(str(uuid.uuid4()), 0x32) == 1
    finally:
        sess.close()


# --- 13. P3 验收：DeviceSession 透传 asyncio loop，on_event 在事件循环线程跑 ---


def test_device_session_dispatches_events_on_event_loop_thread():
    db = SessionLocal()
    try:
        d = _mk_device(db, "LOOPPASS")
        dev_id = d.id
    finally:
        db.close()

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        loop_tid = threading.get_ident()
        seen_tids: list[int] = []
        done = asyncio.Event()

        def on_event(ev: SessionEvent) -> None:
            if ev.kind == "state":
                seen_tids.append(threading.get_ident())
                done.set()

        port = SimBytePort(SimulatedDevice())
        link = SerialLink(port, min_frame_gap=0.0, poll_interval=0.002)
        sess = DeviceSession(
            dev_id,
            SessionLocal,
            link,
            loop=loop,
            auto_prepare_sim=True,
            on_event=on_event,
        )
        sess.start()
        try:
            assert sess.poll_status() is True
            await asyncio.wait_for(done.wait(), timeout=2.0)
        finally:
            sess.close()

        assert seen_tids == [loop_tid]

    asyncio.run(_run())


# --- 13b. 复审项 A：超时事件（工作线程触发）也必须切回事件循环线程 ---


def test_uplink_timeout_event_dispatched_on_event_loop_thread():
    """check_uplink_timeout 由 asyncio.to_thread 调用，事件仍须落在事件循环线程（06:185）。"""
    db = SessionLocal()
    try:
        d = _mk_device(db, "TIMEOUTLOOP")
        dev_id = d.id
    finally:
        db.close()

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        loop_tid = threading.get_ident()
        clock = FakeClock()
        seen: list[tuple[str, int]] = []
        done = asyncio.Event()

        def on_event(ev: SessionEvent) -> None:
            if ev.kind == "link" and ev.payload.get("reason") == "uplink_timeout":
                seen.append((str(ev.payload.get("reason")), threading.get_ident()))
                done.set()

        port = _RecordingPort()
        link = SerialLink(port, clock=clock, min_frame_gap=0.0, poll_interval=0.002)
        sess = DeviceSession(
            dev_id,
            SessionLocal,
            link,
            clock=clock,
            loop=loop,
            auto_prepare_sim=True,
            on_event=on_event,
        )
        sess.start()
        try:
            port.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
            deadline = time.monotonic() + 2.0
            while not sess.online and time.monotonic() < deadline:
                await asyncio.sleep(0.005)
            assert sess.online is True

            clock.advance(9.5)
            # 与 main.py 一致：在工作线程里跑超时检查，事件必须切回 loop 线程
            assert await asyncio.to_thread(sess.check_uplink_timeout) is True
            await asyncio.wait_for(done.wait(), timeout=2.0)
        finally:
            sess.close()

        assert seen == [("uplink_timeout", loop_tid)]

    asyncio.run(_run())


# --- 14. P4 验收：SendGate 被占用等待期间，SerialLink 仍持续读串口不阻塞 ---


def test_serial_link_keeps_reading_while_waiting_on_send_gate():
    gate = SendGate(default_timeout=1.0)
    port = _RecordingPort()
    received: list[Frame] = []
    link = SerialLink(
        port,
        on_frame=lambda f, _t: received.append(f),
        send_gate=gate,
        min_frame_gap=0.0,
        poll_interval=0.002,
    )
    link.start()
    try:
        with gate.hold():
            # 用户帧入队，因 SendGate 被占着暂时不能写
            link.enqueue(build(0x07, b"\x01"))
            time.sleep(0.03)
            assert port.written == []
            # 此时注入设备回帧：即使 SendGate 仍被占着，串口读也必须照常收到
            port.inject_rx(build(CMD_HEARTBEAT_ACK))
            assert _wait_until(lambda: len(received) == 1, timeout=1.0)
            assert received[0].cmd == CMD_HEARTBEAT_ACK
        # 释放 SendGate 后，刚才那条用户帧顺利写出
        assert _wait_until(lambda: len(port.written) == 1, timeout=1.0)
    finally:
        link.close()


# --- 15. P5 / P6 / 轻微项验收：未知 action=0xFF、畸形帧不抹缓存、优先级、naive 时区 ---


def test_unknown_action_malformed_status_cache_and_control_state_order():
    db = SessionLocal()
    try:
        d = _mk_device(db, "STATUS_EDGE")
        dev_id = d.id
    finally:
        db.close()

    port = _RecordingPort()
    events: list[SessionEvent] = []
    link = SerialLink(port, min_frame_gap=0.0, poll_interval=0.002)
    sess = DeviceSession(
        dev_id,
        SessionLocal,
        link,
        auto_prepare_sim=True,
        on_event=events.append,
    )
    sess.start()
    try:
        # P6：0x03 中 action=0xFF（未知）应解为 None，不能误判 busy
        unknown_action_status = bytearray(DEFAULT_STATUS)
        unknown_action_status[1] = 0xFF
        port.inject_rx(build(CMD_STATUS, bytes(unknown_action_status)))
        assert _wait_until(lambda: sess.control_state == "ready")
        snap = sess.snapshot()
        assert snap.action is None
        assert snap.battery == 87
        # 轻微项：last_heartbeat 与全后端统一为本地 naive datetime
        assert snap.last_heartbeat is not None
        assert snap.last_heartbeat.tzinfo is None

        # 轻微项：收到 7 字节畸形 0x03，该帧事件字段为 None，但不得抹掉已有有效缓存
        port.inject_rx(build(CMD_STATUS, bytes([1, 2, 3, 4, 5, 6, 7])))
        assert _wait_until(lambda: sess.malformed_status_frames == 1)
        assert events[-1].payload["battery"] is None
        assert events[-1].payload["voltage"] is None
        assert sess.snapshot().battery == 87  # 此前有效缓存保留

        # P5：busy 优先级严格高于 unconfigured（06:346）
        sess._snapshot_received = False
        sess._motion_reserving = True
        assert sess.control_state == "busy"
        sess._motion_reserving = False
        assert sess.control_state == "unconfigured"
    finally:
        sess.close()


# --- 16. 复审项 ③：DB 一次性准备标记（state='prepared'）启动消费且不可复用 ---


def test_db_prepared_marker_consumed_once_on_startup():
    db = SessionLocal()
    try:
        d = _mk_device(db, "DBPREP")
        dev_id, dev_be = d.id, d.be
        prep_sid = str(uuid.uuid4())
        db.add(
            DeviceSessionRecord(
                device_pk=dev_id,
                be=dev_be,
                session_id=prep_sid,
                state="prepared",
                last_seq=0,
            )
        )
        db.commit()
    finally:
        db.close()

    # 第一次真实启动（不传 prepared_marker、不开 auto_prepare_sim）：应一次性消费 DB 标记
    p1 = _RecordingPort()
    s1 = DeviceSession(dev_id, SessionLocal, SerialLink(p1, min_frame_gap=0.0, poll_interval=0.002))
    s1.start()
    try:
        db = SessionLocal()
        try:
            rec = (
                db.query(DeviceSessionRecord)
                .filter(DeviceSessionRecord.session_id == prep_sid)
                .first()
            )
            assert rec.state == "consumed"
        finally:
            db.close()

        p1.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
        assert _wait_until(lambda: s1.control_state == "ready")
    finally:
        s1.close()

    # 第二次重启（未重新落库 prepared）：不可复用旧标记，必须回落 recovery_required
    p2 = _RecordingPort()
    s2 = DeviceSession(dev_id, SessionLocal, SerialLink(p2, min_frame_gap=0.0, poll_interval=0.002))
    s2.start()
    try:
        p2.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
        assert _wait_until(lambda: s2.online is True)
        assert s2.control_state == "recovery_required"
    finally:
        s2.close()


# --- 17. 复审项 ④：轮换写库不占事件循环线程 + 后台 ticker 异常不静默死亡 ---


def test_timeout_rotation_db_write_off_event_loop_and_ticker_survives_error():
    from app.main import _session_maintenance_loop

    db = SessionLocal()
    try:
        d = _mk_device(db, "OFFLOOP")
        dev_id = d.id
    finally:
        db.close()

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        loop_tid = threading.get_ident()
        open_tids: list[int] = []
        done = asyncio.Event()

        clock = FakeClock()
        port = _RecordingPort()
        link = SerialLink(port, clock=clock, min_frame_gap=0.0, poll_interval=0.002)
        sess = DeviceSession(
            dev_id,
            SessionLocal,
            link,
            clock=clock,
            loop=loop,
            auto_prepare_sim=True,
        )

        orig_open = sess._open_session_record

        def _spy_open(be: int, sid: str):
            open_tids.append(threading.get_ident())
            res = orig_open(be, sid)
            loop.call_soon_threadsafe(done.set)
            return res

        sess._open_session_record = _spy_open  # type: ignore[method-assign]
        sess.start()
        try:
            port.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
            # _on_frame 经 call_soon_threadsafe 投递到当前事件循环，必须用 await 让出循环
            deadline = time.monotonic() + 2.0
            while not sess.online and time.monotonic() < deadline:
                await asyncio.sleep(0.005)
            assert sess.online is True

            clock.advance(9.5)
            assert sess.check_uplink_timeout() is True

            # 上行恢复触发轮换：DB 插入必须在线程池（非事件循环线程）执行
            port.inject_rx(build(CMD_HEARTBEAT_ACK))
            await asyncio.wait_for(done.wait(), timeout=2.0)
            assert open_tids and open_tids[0] != loop_tid
        finally:
            sess.close()

        # 验证 ticker 遇到瞬时异常后不会退出，后续轮次继续发心跳
        class _FlakySession:
            online = True

            def __init__(self) -> None:
                self.hb_calls = 0
                self.check_calls = 0

            @property
            def control_state(self) -> str:
                return "ready"

            def send_heartbeat(self) -> bool:
                self.hb_calls += 1
                if self.hb_calls == 1:
                    raise RuntimeError("transient error")
                return True

            def check_command_timeout(self) -> None:
                pass

            def check_uplink_timeout(self) -> bool:
                self.check_calls += 1
                if self.check_calls == 1:
                    raise RuntimeError("transient db error")
                return False

        flaky = _FlakySession()
        task = asyncio.create_task(
            _session_maintenance_loop(
                flaky,  # type: ignore[arg-type]
                heartbeat_interval=0.02,
                check_interval=0.02,
            )
        )
        try:
            await asyncio.sleep(0.1)
            assert not task.done()
            assert flaky.hb_calls >= 2
            assert flaky.check_calls >= 2
        finally:
            task.cancel()
            await task
            assert task.done()

    asyncio.run(_run())


# --- 18. 深度复审补测：SendGate 等待期间失锁拦写 + send_motion 写库间隙解绑拦写 ---


def test_lock_drop_during_send_gate_wait_and_unbind_during_seq_persist():
    # A. SendGate 被占用等待期间 DB 锁断开 → 必须立刻判 db_lock_lost 且 0 字节写出
    gate = SendGate(default_timeout=1.0)
    port = _RecordingPort()
    lock_alive = True
    outcomes: list[WriteOutcome] = []

    link = SerialLink(
        port,
        lock_check=lambda: lock_alive,
        send_gate=gate,
        min_frame_gap=0.0,
        poll_interval=0.002,
    )
    link.start()
    try:
        with gate.hold():
            link.enqueue(build(0x07, b"\x02"), on_done=outcomes.append)
            time.sleep(0.03)
            # 在等待 SendGate 的过程中模拟 DB 锁丢失
            lock_alive = False
            assert _wait_until(lambda: link.faulted is True, timeout=1.0)
        assert link.fault_reason == "db_lock_lost"
        assert port.written == []
        assert outcomes and outcomes[0].reason == "db_lock_lost"
    finally:
        link.close()

    # B. send_motion 阶段 2（锁外持久化 seq）期间触发 unbind → 阶段 3 必须拒绝且 0 字节写出
    db = SessionLocal()
    try:
        d = _mk_device(db, "UNBIND_RACE")
        dev_id = d.id
    finally:
        db.close()

    gate2 = SendGate(default_timeout=1.0)
    port2 = _RecordingPort()
    link2 = SerialLink(port2, min_frame_gap=0.0, poll_interval=0.002)
    sess = DeviceSession(
        dev_id,
        SessionLocal,
        link2,
        send_gate=gate2,
        auto_prepare_sim=True,
    )
    sess.start()
    try:
        port2.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
        assert _wait_until(lambda: sess.control_state == "ready")

        orig_persist = sess._persist_last_seq

        def _persist_then_unbind(rec_id, seq):
            orig_persist(rec_id, seq)
            # 在阶段 2 刚落库、阶段 3 尚未拿锁前，模拟设备被解绑
            gate2.revoke_access(
                uid=1,
                device_pk=dev_id,
                kind="unbind",
                commit_fn=lambda: None,
                new_be=1,
            )

        sess._persist_last_seq = _persist_then_unbind  # type: ignore[method-assign]
        with pytest.raises(SessionNotReadyError):
            sess.send_motion(str(uuid.uuid4()), 0x31)
        time.sleep(0.03)
        assert port2.written == []
        assert sess.pending_seqs == {}
        assert sess.control_state == "handover_required"
    finally:
        sess.close()


def test_done_clears_busy_action_immediately_and_stale_face_retries_poll():
    db = SessionLocal()
    try:
        d = _mk_device(db, "FASTSYNC")
        dev_id = d.id
    finally:
        db.close()

    clock = FakeClock()
    port = _RecordingPort()
    link = SerialLink(port, clock=clock, min_frame_gap=0.0, poll_interval=0.002)
    sess = DeviceSession(
        dev_id,
        SessionLocal,
        link,
        clock=clock,
        auto_prepare_sim=True,
    )
    sess.start()
    try:
        # 1. 上线并下发动作 0x31；执行中途 0x03 上报 action=0x31
        port.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))
        assert _wait_until(lambda: sess.control_state == "ready")
        seq = sess.send_motion(str(uuid.uuid4()), 0x31)
        assert _wait_until(lambda: len(port.written) == 1)
        running = bytearray(DEFAULT_STATUS)
        running[1] = 0x31
        port.inject_rx(build(CMD_STATUS, bytes(running)))
        assert _wait_until(lambda: sess.snapshot().action == 0x31)
        assert sess.control_state == "busy"

        # 收到 0x02 DONE 后应立即清 action 并回到 ready，不必苦等下一次 5s 0x03，同时催一次 0x06
        clock.advance(1.5)
        port.inject_rx(build(CMD_DONE, bytes([0x31, seq])))
        assert _wait_until(lambda: sess.control_state == "ready")
        assert sess.snapshot().action == 0
        assert _wait_until(lambda: build(CMD_POLL_STATUS) in port.written)

        # 2. 下发表情 4 后若抢先收到旧表情 0x03，冷却过后应补发一次 0x06 拉齐新表情
        clock.advance(1.5)
        polls_before = port.written.count(build(CMD_POLL_STATUS))
        sess.send_face(4)
        assert _wait_until(lambda: port.written.count(build(CMD_POLL_STATUS)) == polls_before + 1)
        clock.advance(1.5)
        port.inject_rx(build(CMD_STATUS, DEFAULT_STATUS))  # 仍报旧表情 face=2
        assert _wait_until(lambda: port.written.count(build(CMD_POLL_STATUS)) == polls_before + 2)
        updated = bytearray(DEFAULT_STATUS)
        updated[2] = 4
        port.inject_rx(build(CMD_STATUS, bytes(updated)))
        assert _wait_until(lambda: sess.snapshot().face == 4)
    finally:
        sess.close()
