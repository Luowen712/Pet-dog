"""BB00 第 3 步：采样已实现接口的真实返回体。

只读运行：不写库、不改数据。token 做打码处理后可入库。
用法（在 backend/ 目录下）：
    .venv\\Scripts\\python.exe scripts\\sample_bb00.py
"""

import json
import sys
from pathlib import Path

# 让脚本能 import 到 app 包（scripts/ 不在 sys.path 里）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.security import make_token  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "docs" / "evidence" / "BB00" / "samples"
OUT.mkdir(parents=True, exist_ok=True)

client = TestClient(app)

# 只用于采样：给已存在的 admin(id=1) 现签一个 token，不写库
ADMIN = {"Authorization": f"Bearer {make_token(1, 'admin', 0)}"}


def mask(obj):
    """把 token 打码，其余字段原样保留。"""
    if isinstance(obj, dict):
        return {
            k: ("<JWT 已打码>" if k == "token" else mask(v)) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [mask(i) for i in obj]
    return obj


CASES = [
    ("health-200", "GET", "/api/health", None, None),
    ("setup-status-200", "GET", "/api/setup/status", None, None),
    ("faces-list-200", "GET", "/api/faces", None, ADMIN),
    ("devices-list-200", "GET", "/api/devices", None, ADMIN),
    ("devices-detail-200", "GET", "/api/devices/1", None, ADMIN),
    ("devices-status-200", "GET", "/api/devices/1/status", None, ADMIN),
    ("devices-list-401", "GET", "/api/devices", None, None),
    (
        "login-40001",
        "POST",
        "/api/auth/login",
        {"username": "admin", "password": "__wrong__"},
        None,
    ),
    (
        "register-40002",
        "POST",
        "/api/auth/register",
        {"username": "a", "password": "123"},
        None,
    ),
]

for name, method, url, body, headers in CASES:
    resp = client.request(method, url, json=body, headers=headers or {})
    ctype = resp.headers.get("content-type", "")
    payload = {
        "request": {"method": method, "path": url, "body": body},
        "status_code": resp.status_code,
        "body": (
            mask(resp.json()) if ctype.startswith("application/json") else resp.text
        ),
    }
    (OUT / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"{name:22s} HTTP {resp.status_code}  "
        f"{json.dumps(payload['body'], ensure_ascii=False)[:120]}"
    )

print(f"\n已写入 {len(CASES)} 个文件 -> {OUT}")
