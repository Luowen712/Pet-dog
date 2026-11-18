"""SIM 组件测试：BA01 完成判据的可复现证据。

全部用 FakeClock 推进时间，文件内不允许出现真实等待。
"""

import json
import pathlib

import pytest

from app.link import frame as fr
from app.link.frame import Parser, build
from app.link.simulator import (
    DEFAULT_STATUS,
    FakeClock,
    SimBytePort,
    SimDisconnected,
    SimFaults,
    SimulatedDevice,
    decode_status,
)

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "docs" / "contracts" / "fixtures" / "frames"

STAND_SEQ1 = bytes.fromhex("AA 55 04 01 31 00 01 01 C7")
HEARTBEAT_REQ = bytes.fromhex("AA 55 00 04 FB")
HEARTBEAT_ACK = bytes.fromhex("AA 55 00 84 7B")
POLL_STATUS = bytes.fromhex("AA 55 00 06 F9")
ACCEPTED_SEQ1 = bytes.fromhex("AA 55 02 81 01 01 7A")
DONE_STAND_SEQ1 = bytes.fromhex("AA 55 02 02 31 01 C9")
STATUS_CORE9 = bytes.fromhex("AA 55 09 03 57 00 02 FF FF 1C FE FF 14 6F")
FACE_HAPPY = bytes.fromhex("AA 55 01 07 01 F6")


def sim(**faults):
    clock = FakeClock()
    return SimulatedDevice(clock=clock, faults=SimFaults(**faults)), clock


def test_heartbeat_request_gets_ack():
    dev, _ = sim()
    dev.feed(HEARTBEAT_REQ)
    assert dev.poll() == [HEARTBEAT_ACK]


def test_ack_does_not_get_answered():
    dev, _ = sim()
    dev.feed(HEARTBEAT_ACK)
    assert dev.poll() == []
    assert dev.stats.unknown_cmd == 1


def test_action_produces_accepted_then_done():
    dev, clock = sim()
    dev.feed(STAND_SEQ1)
    assert dev.poll() == [ACCEPTED_SEQ1]
    clock.advance(0.299)
    assert dev.poll() == []
    clock.advance(0.001)
    assert dev.poll() == [DONE_STAND_SEQ1]


def test_delay_done_is_configurable():
    dev, clock = sim(delay_done_ms=5000)
    dev.feed(STAND_SEQ1)
    assert dev.poll() == [ACCEPTED_SEQ1]
    clock.advance(4.999)
    assert dev.poll() == []
    clock.advance(0.001)
    assert dev.poll() == [DONE_STAND_SEQ1]


def test_busy_rejects_second_action():
    dev, _ = sim()
    dev.feed(STAND_SEQ1)
    dev.poll()
    dev.feed(bytes.fromhex("AA 55 04 01 33 00 01 02 C4"))  # 前进 seq2
    assert dev.poll() == [bytes.fromhex("AA 55 02 05 04 02 F2")]
    assert dev.stats.rejected_busy == 1


def test_unsupported_action_does_not_take_busy_slot():
    dev, _ = sim()
    dev.feed(bytes.fromhex("AA 55 04 01 29 00 01 05 CB"))  # 0x29 本期禁用
    assert dev.poll() == [bytes.fromhex("AA 55 02 05 01 05 F2")]
    assert dev.stats.rejected_unsupported == 1
    dev.feed(STAND_SEQ1)
    assert dev.poll() == [ACCEPTED_SEQ1]


def test_poll_status_returns_current_nine_bytes():
    dev, _ = sim()
    dev.feed(POLL_STATUS)
    assert dev.poll() == [STATUS_CORE9]


def test_face_updates_status_and_answers_nothing():
    dev, _ = sim()
    dev.feed(FACE_HAPPY)
    assert dev.poll() == []
    dev.feed(POLL_STATUS)
    assert dev.poll() == [bytes.fromhex("AA 55 09 03 57 00 01 FF FF 1C FE FF 14 70")]


def test_unopened_commands_are_silent():
    dev, _ = sim()
    dev.feed(build(0x08, b""))
    dev.feed(build(0x0B, b"\x01"))
    assert dev.poll() == []
    assert dev.stats.unknown_cmd == 2


def test_speed_and_repeat_are_ignored():
    dev, _ = sim()
    dev.feed(build(0x01, bytes([0x32, 0x05, 0x09, 0x01])))
    assert dev.poll() == [ACCEPTED_SEQ1]


def test_duplicate_seq_replays_result():
    dev, clock = sim()
    dev.feed(STAND_SEQ1)
    assert dev.poll() == [ACCEPTED_SEQ1]
    clock.advance(0.3)
    assert dev.poll() == [DONE_STAND_SEQ1]
    dev.feed(STAND_SEQ1)
    assert dev.poll() == [ACCEPTED_SEQ1]
    clock.advance(0.3)
    assert dev.poll() == [DONE_STAND_SEQ1]
    assert dev.stats.duplicates == 1


def test_same_seq_different_payload_is_rejected():
    dev, _ = sim()
    dev.feed(STAND_SEQ1)
    dev.poll()
    dev.feed(bytes.fromhex("AA 55 04 01 32 00 01 01 C6"))  # 同 seq1，异 payload
    assert dev.poll() == [bytes.fromhex("AA 55 02 05 02 01 F5")]
    assert dev.stats.rejected_param == 1


def test_drop_ack_still_produces_done():
    dev, clock = sim(drop_ack=True)
    dev.feed(STAND_SEQ1)
    assert dev.poll() == []
    clock.advance(0.3)
    assert dev.poll() == [DONE_STAND_SEQ1]
    assert dev.stats.dropped == 1


def test_drop_done_only_sends_ack():
    dev, clock = sim(drop_done=True)
    dev.feed(STAND_SEQ1)
    assert dev.poll() == [ACCEPTED_SEQ1]
    clock.advance(1.0)
    assert dev.poll() == []


def test_duplicate_done_sends_two_frames():
    dev, clock = sim(duplicate_done=True)
    dev.feed(STAND_SEQ1)
    dev.poll()
    clock.advance(0.3)
    assert dev.poll() == [DONE_STAND_SEQ1, DONE_STAND_SEQ1]


def test_bad_checksum_is_observable_by_parser():
    dev, _ = sim(bad_checksum=True)
    dev.feed(HEARTBEAT_REQ)
    corrupted = dev.poll()
    assert len(corrupted) == 1
    assert corrupted[0] == HEARTBEAT_ACK[:-1] + bytes([HEARTBEAT_ACK[-1] ^ 0xFF])
    parser = Parser()
    assert parser.feed(corrupted[0]) == []
    assert parser.bad_sum == 1


def test_disconnect_blocks_write():
    dev, _ = sim(disconnect=True)
    assert dev.connected is False
    port = SimBytePort(dev)
    with pytest.raises(SimDisconnected):
        port.write(HEARTBEAT_REQ)
    with pytest.raises(SimDisconnected):
        port.read(5)
    with pytest.raises(SimDisconnected):
        _ = port.in_waiting

    assert port.is_open is True


def test_port_assembles_frame_byte_by_byte():
    dev, _ = sim()
    port = SimBytePort(dev)
    for i, byte in enumerate(HEARTBEAT_REQ):
        port.write(bytes([byte]))
        if i < len(HEARTBEAT_REQ) - 1:
            assert port.read(fr.MAX_FRAME) == b""
    assert port.read(2) == HEARTBEAT_ACK[:2]
    assert port.read(3) == HEARTBEAT_ACK[2:]


def test_two_frames_in_one_chunk():
    dev, _ = sim()
    dev.feed(HEARTBEAT_REQ + POLL_STATUS)
    assert dev.poll() == [HEARTBEAT_ACK, STATUS_CORE9]


def test_bad_sum_then_good_frame():
    dev, _ = sim()
    broken = HEARTBEAT_REQ[:-1] + b"\x00"
    dev.feed(broken + POLL_STATUS)
    assert dev.poll() == [STATUS_CORE9]
    assert dev.stats.corrupted >= 1  # 字节级重同步计数，坏帧只污染自己
    assert dev.stats.frames_in == 1


def test_garbage_is_silent():
    dev, _ = sim()
    dev.feed(bytes(range(100)))
    assert dev.poll() == []
    assert dev.stats.frames_in == 0


def test_truncated_action_gets_no_reply():
    dev, _ = sim()
    dev.feed(build(0x01, bytes([0x31, 0x00])))
    assert dev.poll() == []
    assert dev.stats.malformed == 1


def test_fixture_vectors_roundtrip():
    parsed = 0
    for path in sorted(FIXTURES.glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        if "hex" not in spec:
            continue
        parser = Parser()
        frames = parser.feed(bytes.fromhex(spec["hex"]))
        assert len(frames) == 1, path.name
        assert frames[0].cmd == int(spec["cmd"], 16), path.name
        assert list(frames[0].data) == [int(x, 16) for x in spec["data"]], path.name
        assert parser.feed(b"") == [] and not parser._buf, path.name
        parsed += 1
    assert parsed == 11


def test_decode_status_core9():
    got = decode_status(DEFAULT_STATUS)
    assert got == {
        "battery": 0x57,
        "action": 0,
        "face": 2,
        "music_state": None,
        "track": None,
        "voltage_mv": 0x1CFE,
        "weather": None,
        "temperature": 0x14,
    }


def test_decode_status_all_unknown():
    got = decode_status(bytes([0xFF, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x80]))
    assert got["battery"] is None
    assert got["action"] == 0
    assert got["face"] is None
    assert got["music_state"] is None
    assert got["track"] is None
    assert got["voltage_mv"] is None
    assert got["weather"] is None
    assert got["temperature"] is None


def test_decode_status_six_bytes_has_no_voltage():
    got = decode_status(DEFAULT_STATUS[:6])
    assert got["voltage_mv"] is None
    assert got["weather"] is None
    assert got["temperature"] is None
    assert got["battery"] == 0x57


def test_decode_status_negative_temperature():
    data = bytearray(DEFAULT_STATUS)
    data[8] = 0xFE  # -2
    assert decode_status(bytes(data))["temperature"] == -2


def test_decode_status_rejects_other_lengths():
    for bad in (b"", DEFAULT_STATUS[:8], DEFAULT_STATUS + b"\x00"):
        with pytest.raises(ValueError):
            decode_status(bad)


def test_module_never_sleeps():
    src = pathlib.Path(fr.__file__).with_name("simulator.py").read_text(encoding="utf-8")
    assert "sleep" not in src

def test_closed_port_raises_like_pyserial():
    dev, _ = sim()
    port = SimBytePort(dev)
    port.close()
    assert port.is_open is False
    with pytest.raises(SimDisconnected):
        port.read(1)
    with pytest.raises(SimDisconnected):
        port.write(HEARTBEAT_REQ)
    with pytest.raises(SimDisconnected):
        port.flush()
    with pytest.raises(SimDisconnected):
        port.reset_input_buffer()
    with pytest.raises(SimDisconnected):
        _ = port.in_waiting
    port.close()  # 重复 close 不报错，与真端口一致


def test_overlong_action_is_rejected_with_03():
    dev, _ = sim()
    dev.feed(build(0X01, bytes([0x31, 0x00, 0x01, 0x07, 0x09])))
    assert dev.poll() == [bytes.fromhex("AA 55 02 05 03 07 EE")]
    assert dev.stats.rejected_overlong == 1
    assert dev.stats.rejected_busy == 0
