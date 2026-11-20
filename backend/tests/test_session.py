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
        assert [e.kind for e in events] == ["orphan", "orphan", "orphan"]
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
