#!/usr/bin/env python
"""协议对拍工具：生成交给嵌入方的帧清单，并自动比对嵌入方回传的 hex。

为什么需要它：
    仓库里 12 组固定向量（docs/contracts/fixtures/frames/）一直是"只读样例"，
    嵌入方拿到后没有统一的输出格式交回来，比对只能靠人眼看 hex，出错查不出
    是字段错了还是 SUM 错了。这个工具把三件事固定下来：
      1. dump      —— 输出对拍清单（谁生成哪一帧、字段含义、期望 hex）
      2. selfcheck —— 用后端自己的编码器重算一遍，证明清单不是照抄文档
      3. check     —— 读嵌入方回传的 hex，逐字节比对并指出第一个差异位置

    对拍的意义：这件事不需要实物板，双方各自独立实现、各自独立算 SUM，
    对上了才说明"协议接起来了"。SIM 跑通不等于对拍通过，对拍通过也不等于
    真机验收通过（见 docs/contracts/handover-embedded.md 第 5 节）。

用法（都在 backend 目录下执行）：
    .venv\\Scripts\\python.exe tools\\frame_vector_dump.py dump
    .venv\\Scripts\\python.exe tools\\frame_vector_dump.py dump --out 对拍清单.md
    .venv\\Scripts\\python.exe tools\\frame_vector_dump.py selfcheck
    .venv\\Scripts\\python.exe tools\\frame_vector_dump.py check --file 固件回传.txt

嵌入方回传文件格式（每行一条，vector id 后跟冒号或逗号，hex 大小写不限）：
    frames.action.request.stand.seq1: AA 55 04 01 31 00 01 01 C7
    frames.status.core9, AA5504 03 ...
"""

import argparse
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND.parent / "docs" / "contracts" / "fixtures" / "frames"

sys.path.insert(0, str(BACKEND))

from app.link.frame import MAX_DATA, OVERHEAD, build, checksum  # noqa: E402

HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")


# ---------------------------------------------------------------- 载入向量


def load_vectors() -> tuple[list[dict], list[dict]]:
    """返回 (单帧向量, 边界用例)。单帧向量按 id 排序，边界用例保留顺序。"""
    if not FIXTURES.is_dir():
        raise SystemExit(f"找不到向量目录：{FIXTURES}")

    singles: list[dict] = []
    bounds: list[dict] = []
    for path in sorted(FIXTURES.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if "cases" in doc:
            for index, case in enumerate(doc["cases"]):
                case = dict(case)
                case["id"] = f"{doc['id']}#{index}"
                case["group"] = doc.get("rule", "")
                bounds.append(case)
        else:
            singles.append(doc)
    return singles, bounds


def parse_hex(text: str) -> bytes:
    """把 'AA 55 04 ...' / 'AA5504' / '0xAA,0x55' 统一成 bytes。"""
    cleaned = text.replace("0x", " ").replace("0X", " ")
    compact = re.sub(r"[^0-9A-Fa-f]", "", cleaned)
    if not compact:
        raise ValueError("没有可解析的十六进制字符")
    if len(compact) % 2:
        raise ValueError(f"十六进制位数是奇数：{compact}")
    if not HEX_RE.match(compact):
        raise ValueError(f"含非十六进制字符：{text}")
    return bytes.fromhex(compact)


def hex_str(raw: bytes) -> str:
    return " ".join(f"{b:02X}" for b in raw)


def sum_of(raw: bytes) -> int:
    """从完整帧里独立重算 SUM，不读 fixture 里写的值。"""
    if len(raw) < OVERHEAD or raw[0] != 0xAA or raw[1] != 0x55:
        raise ValueError("不是 AA 55 开头的完整帧")
    length, cmd = raw[2], raw[3]
    return checksum(cmd, raw[4:4 + length])


# ---------------------------------------------------------------- dump


def cmd_dump(args) -> int:
    singles, bounds = load_vectors()
    lines: list[str] = []
    lines.append("# 帧对拍清单")
    lines.append("")
    lines.append(
        "由 `backend/tools/frame_vector_dump.py dump` 生成，数据源是 "
        "`docs/contracts/fixtures/frames/`。**SUM 必须各自独立按 "
        "`~(LEN + CMD + ΣDATA) & 0xFF` 重算，不要照抄本表。**"
    )
    lines.append("")

    lines.append(f"## 一、单帧向量（{len(singles)} 组）")
    lines.append("")
    lines.append("| 向量 id | 方向 | CMD | 说明 | 字段 | 期望 hex |")
    lines.append("|---|---|---|---|---|---|")
    for vec in singles:
        fields = " ".join(vec.get("data_fields") or []) or "—"
        lines.append(
            "| `{id}` | {direction} | {cmd} | {name} | {fields} | `{hex}` |".format(
                id=vec["id"],
                direction=vec.get("direction", "—"),
                cmd=vec.get("cmd", "—"),
                name=vec.get("name", ""),
                fields=fields,
                hex=vec.get("hex", ""),
            )
        )

    lines.append("")
    lines.append("## 二、边界用例（长度与校验和）")
    lines.append("")
    lines.append("| 用例 id | 说明 | 应接受 | 期望 hex | 备注 |")
    lines.append("|---|---|---|---|---|")
    for case in bounds:
        lines.append(
            "| `{id}` | {name} | {valid} | `{hex}` | {note} |".format(
                id=case["id"],
                name=case.get("name", ""),
                valid="是" if case.get("valid") else "否（必须拒绝）",
                hex=case.get("hex", ""),
                note=case.get("error") or case.get("note") or "",
            )
        )

    text = "\n".join(lines) + "\n"
    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = Path.cwd() / out
        out.write_text(text, encoding="utf-8")
        print(f"已写入 {out}（{len(singles)} 组单帧 + {len(bounds)} 条边界）")
    else:
        print(text)
    return 0


# ---------------------------------------------------------------- selfcheck


def cmd_selfcheck(args) -> int:
    """证明清单是后端现场算出来的，不是从文档抄的。"""
    singles, bounds = load_vectors()
    failures = 0
    host_frames = 0

    print("== 单帧向量 ==")
    for vec in singles:
        raw = parse_hex(vec["hex"])
        label = vec["id"]
        problems: list[str] = []

        if len(raw) < OVERHEAD:
            problems.append("帧长度小于 5")
        else:
            length = raw[2]
            if length > MAX_DATA:
                problems.append(f"LEN={length} 超过 {MAX_DATA}")
            if len(raw) != length + OVERHEAD:
                problems.append(f"LEN={length} 与总长 {len(raw)} 不符")
            if sum_of(raw) != raw[-1]:
                problems.append(
                    f"SUM 不符：重算 0x{sum_of(raw):02X}，帧内 0x{raw[-1]:02X}"
                )

        if vec.get("direction") == "host->device":
            host_frames += 1
            data = bytes(int(item, 16) for item in vec["data"])
            rebuilt = build(int(vec["cmd"], 16), data)
            if rebuilt != raw:
                problems.append(
                    f"后端编码器重建为 {hex_str(rebuilt)}，与向量不一致"
                )

        if problems:
            failures += 1
            print(f"  FAIL {label}: " + "；".join(problems))
        else:
            note = "（含编码器重建）" if vec.get("direction") == "host->device" else ""
            print(f"  PASS {label} {hex_str(raw)}{note}")

    print("== 边界用例 ==")
    for case in bounds:
        raw = parse_hex(case["hex"])
        ok = True
        reason = ""
        if len(raw) < OVERHEAD:
            ok, reason = False, "帧过短"
        else:
            length = raw[2]
            if length > MAX_DATA:
                ok, reason = False, f"LEN={length} 超上限"
            elif len(raw) != length + OVERHEAD:
                ok, reason = False, "LEN 与总长不符"
            elif sum_of(raw) != raw[-1]:
                ok, reason = False, "SUM 不符"
        if ok != bool(case.get("valid")):
            failures += 1
            print(
                f"  FAIL {case['id']}: 结构判定={'接受' if ok else '拒绝'}"
                f"（{reason or '结构合法'}），向量期望"
                f"{'接受' if case.get('valid') else '拒绝'}"
            )
        else:
            print(f"  PASS {case['id']}: {'结构合法' if ok else '按预期被拒'}")

    total = len(singles) + len(bounds)
    print("")
    print(f"合计 {total} 项，失败 {failures} 项；其中主机侧可重建编码的 {host_frames} 组。")
    if failures:
        print("结论：后端自身与向量不一致，先修后端，不要把这份清单发出去。")
        return 1
    print("结论：后端编码器与全部向量逐字节一致，清单可以发给嵌入方对拍。")
    return 0


# ---------------------------------------------------------------- check


def read_reply(path: Path) -> dict[str, str]:
    """读嵌入方回传：每行 `向量id: hex`，允许 # 注释与空行。"""
    result: dict[str, str] = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([^:：,\t]+)[:：,\t]\s*(.+)$", stripped)
        if not match:
            print(f"  跳过第 {lineno} 行（格式不是 `id: hex`）：{stripped[:60]}")
            continue
        result[match.group(1).strip().strip("`")] = match.group(2).strip()
    return result


def cmd_check(args) -> int:
    path = Path(args.file)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        raise SystemExit(f"找不到回传文件：{path}")

    singles, bounds = load_vectors()
    expected: dict[str, bytes] = {}
    expectations: dict[str, bool] = {}

    for vec in singles:
        expected[vec["id"]] = parse_hex(vec["hex"])
    for case in bounds:
        expected[case["id"]] = parse_hex(case["hex"])
        expectations[case["id"]] = bool(case.get("valid"))

    reply = read_reply(path)
    if not reply:
        raise SystemExit("回传文件里没有解析到任何 `id: hex` 行")

    print(f"回传 {len(reply)} 条，向量库 {len(expected)} 条。")
    print("")

    passed = failed = 0
    for vec_id, want in expected.items():
        got_text = reply.get(vec_id)
        if got_text is None:
            print(f"  MISSING {vec_id}：嵌入方没有回交这一条")
            failed += 1
            continue
        try:
            got = parse_hex(got_text)
        except ValueError as exc:
            print(f"  FAIL    {vec_id}：hex 解析失败（{exc}）")
            failed += 1
            continue

        if got == want:
            passed += 1
            print(f"  PASS    {vec_id}")
            continue

        failed += 1
        detail = ""
        diff_at = next(
            (i for i, (a, b) in enumerate(zip(want, got)) if a != b),
            min(len(want), len(got)),
        )
        if len(want) != len(got):
            detail = f"长度不一致：期望 {len(want)}B，收到 {len(got)}B"
        else:
            detail = f"第 {diff_at} 字节起不同（0 起算）"
        print(f"  FAIL    {vec_id}：{detail}")
        print(f"          期望 {hex_str(want)}")
        print(f"          收到 {hex_str(got)}")
        if diff_at < min(len(want), len(got)):
            print(
                f"          双方在偏移 {diff_at} 分歧："
                f"期望 0x{want[diff_at]:02X}，收到 0x{got[diff_at]:02X}"
            )
            if diff_at == len(want) - 1:
                print("          位置是末字节，优先怀疑 SUM 公式或统计范围")
            elif diff_at == 2:
                print("          位置是 LEN 域，优先怀疑 DATA 长度统计")
            elif diff_at == 3:
                print("          位置是 CMD 域，优先怀疑命令码表")

    extra = [key for key in reply if key not in expected]
    for key in extra:
        print(f"  EXTRA   {key}：向量库里没有这个 id，检查拼写")

    total = len(expected)
    print("")
    print(f"对拍结果：{passed}/{total} 通过，{failed} 项未通过。")
    if failed == 0 and not extra:
        print("结论：双方帧逐字节一致，协议层对接完成，可以把结果贴进回执单表 A/B。")
        return 0
    print("结论：尚未对齐。只贴在通过的项不能算完成，未通过项必须各自重算后再对一次。")
    return 1


# ---------------------------------------------------------------- main


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="帧向量对拍工具（不需要实物板）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dump = sub.add_parser("dump", help="输出交给嵌入方的对拍清单")
    p_dump.add_argument("--out", help="写入文件（Markdown），不填则打印到终端")
    p_dump.set_defaults(func=cmd_dump)

    p_self = sub.add_parser("selfcheck", help="用后端编码器重算全部向量并自检")
    p_self.set_defaults(func=cmd_selfcheck)

    p_check = sub.add_parser("check", help="比对嵌入方回传的 hex 清单")
    p_check.add_argument("--file", required=True, help="嵌入方回传的文本文件")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
