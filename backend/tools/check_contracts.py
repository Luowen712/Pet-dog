#!/usr/bin/env python
"""J00 契约一致性检查。

只做静态比对，不启动后端、不连数据库、不读写被测系统之外的文件。
规则来源是 docs/plan/06_跨组接口与状态规则.md；本脚本不新增规则，只报差异。

用法：
    python backend/tools/check_contracts.py            # 有 ERROR 才退出 1
    python backend/tools/check_contracts.py --strict    # WARN 也算失败
    python backend/tools/check_contracts.py --verbose   # 打印每一条，不只摘要

依赖：PyYAML（运行依赖，不引入新包）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "docs" / "contracts"
OPENAPI = CONTRACTS / "openapi.yaml"
FIXTURES = CONTRACTS / "fixtures"
PLAN_06 = ROOT / "docs" / "plan" / "06_跨组接口与状态规则.md"
FRONTEND_TYPES = ROOT / "frontend" / "src" / "types" / "index.ts"

IMPL_STATUS = {"implemented", "partial", "not-implemented"}
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

findings: list[tuple[str, str, str]] = []


def report(severity: str, check: str, message: str) -> None:
    findings.append((severity, check, message))


def load_openapi() -> dict:
    if not OPENAPI.exists():
        report("ERROR", "openapi.exists", str(OPENAPI) + " 不存在")
        return {}
    with OPENAPI.open("r", encoding="utf-8") as fh:
        try:
            return yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            report("ERROR", "openapi.parse", "YAML 解析失败: " + str(exc))
            return {}


def resolve(doc: dict, ref: str):
    """解析本地引用，返回 (节点, 错误信息)。"""
    if not ref.startswith("#/"):
        return None, "只支持本地引用: " + ref
    node = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None, "引用不可解析: " + ref
        node = node[part]
    return node, None


def check_refs(doc: dict) -> None:
    total = 0

    def walk(node):
        nonlocal total
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                total += 1
                _, err = resolve(doc, ref)
                if err:
                    report("ERROR", "openapi.ref", err)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    if total == 0:
        report("ERROR", "openapi.ref", "文档里没有任何引用，明显不是这份 openapi.yaml")


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(instance, schema, doc: dict, path: str) -> None:
    """按本文档实际用到的那部分 JSON Schema 校验（3.0 语义）。"""
    if schema is True or schema == {}:
        return
    if not isinstance(schema, dict):
        return
    if "$ref" in schema:
        target, err = resolve(doc, schema["$ref"])
        if err:
            report("ERROR", "schema.ref", err + " at " + path)
            return
        validate(instance, target, doc, path)
        return
    if instance is None:
        if schema.get("nullable") is True:
            return
        if "enum" in schema and None in schema["enum"]:
            return
        report("ERROR", "schema.type", path + " 不允许为 null")
        return
    for sub in schema.get("allOf", []) or []:
        validate(instance, sub, doc, path)

    expected = schema.get("type")
    if expected == "object":
        if not isinstance(instance, dict):
            report("ERROR", "schema.type", path + " 应为 object")
            return
        for field in schema.get("required", []) or []:
            if field not in instance:
                report("ERROR", "schema.required", path + " 缺少必填字段 " + field)
        for key, sub in (schema.get("properties") or {}).items():
            if key in instance:
                validate(instance[key], sub, doc, path + "." + key)
    elif expected == "array":
        if not isinstance(instance, list):
            report("ERROR", "schema.type", path + " 应为 array")
            return
        items = schema.get("items")
        if items is not None:
            for index, item in enumerate(instance):
                validate(item, items, doc, path + "[" + str(index) + "]")
    elif expected == "string":
        if not isinstance(instance, str):
            report("ERROR", "schema.type", path + " 应为 string")
            return
        if "minLength" in schema and len(instance) < schema["minLength"]:
            report("ERROR", "schema.minLength", path + " 长度小于 " + str(schema["minLength"]))
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            report("ERROR", "schema.maxLength", path + " 长度大于 " + str(schema["maxLength"]))
        fmt = schema.get("format")
        if fmt == "date-time" and not DATETIME_RE.match(instance):
            report("ERROR", "schema.format", path + " 不是 date-time: " + instance)
        if fmt == "uuid" and not UUID_RE.match(instance):
            report("ERROR", "schema.format", path + " 不是 uuid: " + instance)
    elif expected == "integer":
        if not is_int(instance):
            report("ERROR", "schema.type", path + " 应为 integer")
            return
    elif expected == "number":
        if not is_number(instance):
            report("ERROR", "schema.type", path + " 应为 number")
            return
    elif expected == "boolean":
        if not isinstance(instance, bool):
            report("ERROR", "schema.type", path + " 应为 boolean")
            return

    if "enum" in schema and instance not in schema["enum"]:
        report("ERROR", "schema.enum", path + " 不在枚举 " + json.dumps(schema["enum"], ensure_ascii=False))
    if is_number(instance):
        if "minimum" in schema and instance < schema["minimum"]:
            report("ERROR", "schema.minimum", path + " 小于 " + str(schema["minimum"]))
        if "maximum" in schema and instance > schema["maximum"]:
            report("ERROR", "schema.maximum", path + " 大于 " + str(schema["maximum"]))
        ex_min = schema.get("exclusiveMinimum")
        if is_number(ex_min) and instance <= ex_min:
            report("ERROR", "schema.exclusiveMinimum", path + " 必须大于 " + str(ex_min))


def path_pattern(template: str) -> re.Pattern:
    parts = re.split(r"(\{[^}]+\})", template)
    out = []
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            out.append("[^/]+")
        else:
            out.append(re.escape(part))
    return re.compile("^" + "".join(out) + "$")


def openapi_operations(doc: dict) -> dict:
    """返回 {(METHOD, 模板路径): operation}。"""
    ops = {}
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            op = item.get(method)
            if isinstance(op, dict):
                ops[(method.upper(), path)] = op
    return ops


def match_path(ops: dict, method: str, concrete: str):
    for (op_method, template), op in ops.items():
        if op_method != method:
            continue
        if path_pattern(template).match(concrete):
            return template, op
    return None, None


def check_operations(doc: dict, ops: dict) -> None:
    ids = set()
    for (method, path), op in ops.items():
        label = method + " " + path
        status = op.get("x-impl-status")
        if status not in IMPL_STATUS:
            report("ERROR", "openapi.impl_status", label + " 缺少合法 x-impl-status")
        if status == "partial" and not op.get("x-impl-gap"):
            report("ERROR", "openapi.impl_gap", label + " 标了 partial 却没写 x-impl-gap")
        oid = op.get("operationId")
        if not oid:
            report("ERROR", "openapi.operationId", label + " 缺少 operationId")
        elif oid in ids:
            report("ERROR", "openapi.operationId", label + " operationId 重复: " + oid)
        else:
            ids.add(oid)
        if not op.get("responses"):
            report("ERROR", "openapi.responses", label + " 没有 responses")
    if doc.get("openapi") != "3.0.3":
        report("ERROR", "openapi.version", "openapi 字段应为 3.0.3，实际 " + str(doc.get("openapi")))


def check_06_endpoints(doc: dict, ops: dict) -> None:
    if not PLAN_06.exists():
        report("ERROR", "plan06.exists", str(PLAN_06) + " 不存在")
        return
    text = PLAN_06.read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        match = re.match(r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s+(/\S*)\s*\|", line)
        if match:
            rows.append((match.group(1), match.group(2)))
    if not rows:
        report("ERROR", "plan06.parse", "06 的端点表没有解析出任何行")
        return
    ws_paths = []
    for method, path in rows:
        if path.startswith("/ws"):
            ws_paths.append(path)
            continue
        if (method, path) not in ops and not any(
            op_method == method and path_pattern(template).match(path)
            for (op_method, template) in ops
        ):
            report("ERROR", "openapi.coverage", "06 定义了 " + method + " " + path + "，openapi 里没有")
    for (method, path) in ops:
        if (method, path) not in rows and not any(
            method == m and path_pattern(path).match(p) for (m, p) in rows
        ):
            report("ERROR", "openapi.coverage", "openapi 多出 " + method + " " + path + "，06 端点表里没有")
    ws_block = doc.get("x-ws-endpoints") or []
    if not isinstance(ws_block, list) or not ws_block:
        report("ERROR", "openapi.ws", "x-ws-endpoints 必须是非空数组")
        return
    declared_ws = ws_block[0].get("path")
    if len(ws_paths) != 1 or ws_paths[0] != declared_ws:
        report("ERROR", "openapi.ws", "06 的 WS 路径 " + str(ws_paths) + " 与 x-ws-endpoints[0].path " + str(declared_ws) + " 不一致")
    query_names = {item.get("name") for item in ws_block[0].get("query") or []}
    if query_names != {"device_id", "ticket"}:
        report("ERROR", "openapi.ws", "握手查询参数应为 device_id 与 ticket，实际 " + str(sorted(query_names)))


def iter_json(directory: Path):
    if not directory.exists():
        report("ERROR", "fixtures.exists", str(directory) + " 不存在")
        return
    for path in sorted(directory.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                yield path, json.load(fh)
        except json.JSONDecodeError as exc:
            report("ERROR", "fixtures.parse", path.name + " JSON 解析失败: " + str(exc))


def check_http_fixtures(doc: dict, ops: dict) -> None:
    responses = (doc.get("components") or {}).get("responses") or {}
    count = 0
    for path, fixture in iter_json(FIXTURES / "http"):
        count += 1
        name = path.name
        for field in ("id", "method", "path", "http_status", "rule", "response", "body"):
            if field not in fixture:
                report("ERROR", "fixture.shape", name + " 缺少字段 " + field)
        method = fixture.get("method")
        concrete = fixture.get("path")
        if not method or not concrete:
            continue
        shared = fixture.get("scope") == "shared"
        template, op = match_path(ops, method, concrete)
        if op is None and not shared:
            report("ERROR", "fixture.path", name + " 指向的 " + str(method) + " " + str(concrete) + " 不在 openapi 里")
            continue
        response_name = fixture.get("response")
        if response_name not in responses:
            report("ERROR", "fixture.response", name + " 的 response " + str(response_name) + " 不在 components.responses")
            continue
        status_code = fixture.get("http_status")
        if not shared and status_code is not None and str(status_code) not in (op.get("responses") or {}):
            report("ERROR", "fixture.status", name + " 的 HTTP " + str(status_code) + " 未登记在 " + method + " " + template)
        if shared and status_code is not None:
            registered = any(str(status_code) in (candidate.get("responses") or {}) for candidate in ops.values())
            if not registered:
                report("ERROR", "fixture.status", name + " 的 HTTP " + str(status_code) + " 在任何 operation 里都没登记；横切样例也不例外")
        schema = responses[response_name]["content"]["application/json"]["schema"]
        validate(fixture.get("body"), schema, doc, name)
        body = fixture.get("body") or {}
        if body.get("code") == 0 and body.get("data") is None:
            report("ERROR", "fixture.envelope", name + " 成功响应 data 不应为 null")
        if body.get("code") not in (None, 0) and body.get("data") is not None:
            report("ERROR", "fixture.envelope", name + " 业务错误 data 必须为 null")
        if "timestamp" in body and not is_int(body["timestamp"]):
            report("ERROR", "fixture.envelope", name + " timestamp 必须是毫秒整数")
    if count == 0:
        report("ERROR", "fixtures.http", "没有任何 HTTP 样例")


def check_ws_fixtures(doc: dict) -> None:
    schemas = (doc.get("components") or {}).get("schemas") or {}
    event_schema = schemas.get("WsEvent")
    if event_schema is None:
        report("ERROR", "ws.schema", "components.schemas 里没有 WsEvent")
        return
    declared = set((event_schema.get("properties") or {}).get("event", {}).get("enum", []))
    seen = set()
    close_codes_fixture = None
    for path, fixture in iter_json(FIXTURES / "ws"):
        if path.name == "close-codes.json":
            close_codes_fixture = (path.name, fixture)
            continue
        body = fixture.get("body")
        if body is None:
            report("ERROR", "fixture.shape", path.name + " 缺少 body")
            continue
        validate(body, event_schema, doc, path.name)
        seen.add(body.get("event"))
    missing = declared - seen
    if missing:
        report("WARN", "fixtures.ws", "这些事件没有样例: " + ", ".join(sorted(missing)))
    extra = seen - declared
    if extra:
        report("ERROR", "fixtures.ws", "样例出现未登记事件: " + ", ".join(sorted(extra)))

    if close_codes_fixture is None:
        report("ERROR", "fixtures.ws", "缺少 close-codes.json")
        return
    name, fixture = close_codes_fixture
    codes_schema = schemas.get("CloseCode") or {}
    declared_codes = {int(key) for key in (codes_schema.get("properties") or {})}
    fixture_codes = {int(item["code"]) for item in fixture.get("codes", [])}
    if declared_codes != fixture_codes:
        report("ERROR", "fixtures.close_codes", "CloseCode schema " + str(sorted(declared_codes)) + " 与样例 " + str(sorted(fixture_codes)) + " 不一致")
    for item in fixture.get("codes", []):
        if "reconnect" not in item or "frontend" not in item or "trigger" not in item:
            report("ERROR", "fixtures.close_codes", "关闭码 " + str(item.get("code")) + " 缺少 trigger/frontend/reconnect")
    if "4001" in {str(key) for key in (fixture.get("forbidden") or {})}:
        pass
    elif 4001 in fixture_codes:
        report("ERROR", "fixtures.close_codes", "4001 不得再作为关闭码出现（06:157）")


def frame_bytes(hex_text: str) -> list[int]:
    return [int(token, 16) for token in hex_text.split()]


def check_sum(values: list[int]) -> tuple[bool, str]:
    if len(values) < 5:
        return False, "长度不足 5 字节"
    if values[0] != 0xAA or values[1] != 0x55:
        return False, "缺少 AA 55 帧头"
    length = values[2]
    cmd = values[3]
    data = values[4:-1]
    if len(data) != length:
        return False, "LEN 字节 " + str(length) + " 与实际 DATA 长度 " + str(len(data)) + " 不符"
    if len(values) != length + 5:
        return False, "总长 " + str(len(values)) + " 不等于 LEN+5"
    if length > 31:
        return False, "LEN 超界 " + str(length) + " > 31"
    expected = (~(length + cmd + sum(data))) & 0xFF
    if expected != values[-1]:
        return False, "SUM 应为 0x" + format(expected, "02X") + " 实际 0x" + format(values[-1], "02X")
    return True, "0x" + format(expected, "02X")


def check_frames() -> None:
    count = 0
    for path, fixture in iter_json(FIXTURES / "frames"):
        if "cases" in fixture:
            for case in fixture["cases"]:
                count += 1
                ok, detail = check_sum(frame_bytes(case["hex"]))
                if ok != bool(case.get("valid")):
                    report("ERROR", "frames.bounds", case.get("name", "?") + " 判定 valid=" + str(case.get("valid")) + "，实际 " + ("合法" if ok else "非法: " + detail))
                if "total_bytes" in case:
                    actual = len(frame_bytes(case["hex"]))
                    if actual != case["total_bytes"]:
                        report("ERROR", "frames.bounds", case.get("name", "?") + " total_bytes 写 " + str(case["total_bytes"]) + " 实际 " + str(actual))
            continue
        count += 1
        name = fixture.get("id", path.name)
        values = frame_bytes(fixture["hex"])
        ok, detail = check_sum(values)
        if not ok:
            report("ERROR", "frames.sum", name + " 不合法: " + detail)
            continue
        hex_sum = "0x" + format(values[-1], "02X")
        if fixture.get("sum") != hex_sum:
            report("ERROR", "frames.sum", name + " sum 字段 " + str(fixture.get("sum")) + " 与帧尾 " + hex_sum + " 不一致")
        if int(fixture.get("cmd", "0x00"), 16) != values[3]:
            report("ERROR", "frames.sum", name + " cmd 字段与帧内 CMD 不一致")
        declared = [int(token, 16) for token in fixture.get("data", [])]
        if declared and declared != values[4:-1]:
            report("ERROR", "frames.sum", name + " data 数组与帧内 DATA 不一致")
    if count == 0:
        report("ERROR", "fixtures.frames", "没有任何串口帧样例")


def frontend_interfaces(source: str) -> dict:
    result = {}
    for match in re.finditer(r"export interface (\w+)\s*\{(.*?)\n\}", source, re.S):
        body = match.group(2)
        fields = set()
        for line in body.splitlines():
            field = re.match(r"\s*(\w+)\??\s*:", line)
            if field:
                fields.add(field.group(1))
        result[match.group(1)] = fields
    return result


def check_frontend_types(doc: dict) -> None:
    schemas = (doc.get("components") or {}).get("schemas") or {}
    if not FRONTEND_TYPES.exists():
        report("ERROR", "frontend.exists", str(FRONTEND_TYPES) + " 不存在")
        return
    source = FRONTEND_TYPES.read_text(encoding="utf-8")
    interfaces = frontend_interfaces(source)
    for name in ("User", "Device", "DeviceStatus", "CommandReceipt", "FaceItem"):
        schema = schemas.get(name)
        if schema is None:
            continue
        if name not in interfaces:
            report("WARN", "frontend.type", "frontend/src/types/index.ts 没有 interface " + name)
            continue
        declared = set((schema.get("properties") or {}))
        missing = sorted(declared - interfaces[name])
        if missing:
            report("WARN", "frontend.type", "interface " + name + " 缺字段: " + ", ".join(missing))
    ws_union = source.split("export type WsEvent =", 1)
    declared_events = set((schemas.get("WsEvent", {}).get("properties") or {}).get("event", {}).get("enum", []))
    if len(ws_union) == 2:
        found = set(re.findall(r"event:\s*'(\w+)'", ws_union[1].split("export type", 1)[0]))
        missing = sorted(declared_events - found)
        if missing:
            report("WARN", "frontend.type", "WsEvent 联合类型缺事件: " + ", ".join(missing))


def main() -> int:
    parser = argparse.ArgumentParser(description="J00 契约一致性检查")
    parser.add_argument("--strict", action="store_true", help="WARN 也视为失败")
    parser.add_argument("--verbose", action="store_true", help="逐条打印")
    args = parser.parse_args()

    doc = load_openapi()
    if not doc:
        pass
    else:
        check_refs(doc)
        ops = openapi_operations(doc)
        if not ops:
            report("ERROR", "openapi.paths", "没有解析出任何 operation")
        check_operations(doc, ops)
        check_06_endpoints(doc, ops)
        check_http_fixtures(doc, ops)
        check_ws_fixtures(doc)
        check_frontend_types(doc)
    check_frames()

    errors = [item for item in findings if item[0] == "ERROR"]
    warns = [item for item in findings if item[0] == "WARN"]
    limit = len(findings) if args.verbose else 20
    for severity, check, message in findings[:limit]:
        print("[" + severity + "] " + check + ": " + message)
    if len(findings) > limit:
        print("... 另有 " + str(len(findings) - limit) + " 条，加 --verbose 查看")
    print("")
    print("ERROR " + str(len(errors)) + " 条 / WARN " + str(len(warns)) + " 条")
    if errors:
        print("结论：契约不一致，先改 06 或改产物，不要改检查脚本去迁就。")
        return 1
    if warns and args.strict:
        print("结论：--strict 下 WARN 视为失败（前端类型尚未同步）。")
        return 1
    print("结论：契约一致。WARN 是待同步项，不是脚本误报。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
