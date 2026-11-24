import json
from pathlib import Path

import pytest

from app.link.frame import Frame, Parser, build

FIXTURES = (
    Path(__file__).resolve().parents[2] / "docs" / "contracts" / "fixtures" / "frames"
)



def hx(text: str) -> bytes:
    """把 "AA 55 04 01" 这种带空格的十六进制串变成字节。"""
    return bytes.fromhex(text.replace(" ", ""))



def test_build_stand_matches_official_vector():
    """06:282 官方向量：请求站立 seq=1。"""
    assert build(0x01, b"\x31\x00\x01\x01") == hx("AA 55 04 01 31 00 01 01 C7")



def test_build_face_frames():
    """七个表情帧，face=0..6，SUM 依次 F7..F1。"""
    sums = []
    for face in range(7):
        raw = build(0x07, bytes([face]))
        assert raw[2] == 1 and raw[3] == 0x07 and raw[4] == face
        sums.append(raw[5])
    assert sums == [0xF7, 0xF6, 0xF5, 0xF4, 0xF3, 0xF2, 0xF1]
    assert build(0x07, b"\x01") == hx("AA 55 01 07 01 F6")



def test_seven_actions_sum_is_arithmetic():
    """七动作 SUM 等差 C8→C2，差一错一眼就看出来。"""
    sums = [build(0x01, bytes([code, 0, 1, 1]))[-1] for code in range(0x30, 0x37)]
    assert sums == list(range(0xC8, 0xC1, -1))



def test_build_rejects_oversize():
    """LEN=32 必须抛异常，不是发出后让固件拒绝。"""
    with pytest.raises(ValueError):
        build(0x03, bytes(32))



def test_parse_all_fixtures():
    """docs/contracts/fixtures/frames 下 11 个方向样例必须逐字解得回来。"""
    count = 0
    for path in sorted(FIXTURES.glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        if "hex" not in fixture:
            continue  # frames-bounds.json 是 cases，另有用例
        frames = Parser().feed(hx(fixture["hex"]))
        assert len(frames) == 1, path.name
        assert frames[0].cmd == int(fixture.get("cmd", "0x00"), 16), path.name
        expected = bytes(int(token, 16) for token in fixture.get("data", []))
        assert frames[0].data == expected, path.name
        count += 1
    assert count == 11



def test_parse_bounds_fixture():
    """边界用例：合法的一帧，非法的零帧。"""
    fixture = json.loads(
        (FIXTURES / "frames-bounds.json").read_text(encoding="utf-8")
    )
    for case in fixture["cases"]:
        frames = Parser().feed(hx(case["hex"]))
        if case["valid"]:
            assert len(frames) == 1, case["name"]
        else:
            assert frames == [], case["name"]



def test_parse_byte_by_byte():
    """逐字节喂：前 8 次都不许产出，第 9 次出 1 帧。"""
    parser = Parser()
    raw = hx("AA 55 04 01 31 00 01 01 C7")
    for index, byte in enumerate(raw[:-1]):
        assert parser.feed(bytes([byte])) == [], f"第 {index} 个字节就产出了"
    frames = parser.feed(raw[-1:])
    assert len(frames) == 1
    assert frames[0].data == b"\x31\x00\x01\x01"



def test_parse_two_frames_in_one_chunk():
    """粘包：一次喂两帧，必须产出两帧。"""
    raw = hx("AA 55 00 04 FB") + hx("AA 55 00 04 FB")
    frames = Parser().feed(raw)
    assert [f.cmd for f in frames] == [0x04, 0x04]



def test_parse_bad_sum_then_good():
    """坏 SUM 只丢 1 字节，后面那个好帧不能被连累丢掉。"""
    parser = Parser()
    raw = hx("AA 55 04 01 31 00 01 01 C8") + hx("AA 55 04 01 31 00 01 01 C7")
    frames = parser.feed(raw)
    assert len(frames) == 1
    assert frames[0].cmd == 0x01
    assert parser.bad_sum == 1



def test_parse_garbage_is_silent():
    """100 个垃圾字节：不抛异常、不产出、缓冲区不膨胀（守恒律）。"""
    parser = Parser()
    assert parser.feed(b"\x00" * 100) == []
    assert parser.noise + len(parser._buf) == 100   # 守恒：丢掉的 + 留着的 = 进来的
    assert len(parser._buf) < 3