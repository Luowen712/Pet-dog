"""限流：登录失败按账号 + IP 双桶，注册按 IP 单桶（06§2 基线）。

为什么必须走 HTTP：
    限流的判定在路由里（check → 业务 → 失败才 record）。只测 ratelimit 模块
    等于把路由里那几行抄一遍，以后有人删掉 record 调用、或把它挪到验证之前，
    单测照样绿，而线上限流已经失效。

为什么每个用例前后都要 reset：
    桶是进程内全局状态，TestClient 的来源 IP 固定为 "testclient"，
    不清的话上一个用例打满的桶会顺延到下一个，出现「单跑通过、全量失败」。
    conftest.py 里已有 autouse fixture 负责这件事。
"""

import sys

import pytest
from fastapi.testclient import TestClient

from app import ratelimit
from app.db import SessionLocal
from app.main import app
from app.models import User
from app.security import hash_pwd

PASSWORD = "rl-test-pw-01"
USER_A = "rl_case_a"
USER_B = "rl_case_b"


def _cleanup(db) -> None:
    db.query(User).filter(User.username.like("rl_%")).delete(synchronize_session=False)
    db.commit()


def _make_user(db, username: str) -> None:
    db.add(
        User(
            username=username,
            password_hash=hash_pwd(PASSWORD),
            role="user",
            token_version=0,
            status="active",
        )
    )
    db.commit()


def test_login_locks_account_after_five_failures():
    """连续 5 次密码错 → 第 6 次即使密码正确也被 429 挡住。"""

    db = SessionLocal()
    try:
        _cleanup(db)
        _make_user(db, USER_A)
    finally:
        db.close()

    client = TestClient(app)

    for _ in range(ratelimit.LOGIN_ACCT_LIMIT):
        r = client.post(
            "/api/auth/login", json={"username": USER_A, "password": "wrong-password"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["code"] == 40001

    # 锁定期内不看密码对错，正确密码也进不来
    r = client.post(
        "/api/auth/login", json={"username": USER_A, "password": PASSWORD}
    )
    assert r.status_code == 429, r.text
    body = r.json()
    assert body["code"] == 42900
    assert body["data"] is None
    assert isinstance(body["retry_after"], int)
    assert 0 < body["retry_after"] <= ratelimit.LOGIN_ACCT_WINDOW

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()


def test_account_bucket_does_not_leak_to_other_user():
    """A 的账号桶打满，不能连累 B —— 否则一个人被爆破，全家都登不上。"""

    db = SessionLocal()
    try:
        _cleanup(db)
        _make_user(db, USER_A)
        _make_user(db, USER_B)
    finally:
        db.close()

    client = TestClient(app)
    for _ in range(ratelimit.LOGIN_ACCT_LIMIT):
        client.post(
            "/api/auth/login", json={"username": USER_A, "password": "wrong-password"}
        )

    r = client.post(
        "/api/auth/login", json={"username": USER_B, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["token"]

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()


def test_successful_login_does_not_consume_quota():
    """成功登录不计入失败桶：连登 8 次（超过阈值 5）也不该被限。"""

    db = SessionLocal()
    try:
        _cleanup(db)
        _make_user(db, USER_A)
    finally:
        db.close()

    client = TestClient(app)
    for _ in range(8):
        r = client.post(
            "/api/auth/login", json={"username": USER_A, "password": PASSWORD}
        )
        assert r.status_code == 200, r.text
        assert r.json()["code"] == 0

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()


def test_register_limits_by_ip():
    """注册第 6 次被拒 —— 成功的注册也占额度，否则换个用户名就能无限建号。"""

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()

    client = TestClient(app)
    for i in range(ratelimit.REGISTER_IP_LIMIT):
        r = client.post(
            "/api/auth/register",
            json={"username": f"rl_reg_{i}", "password": "1234567890"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["code"] == 0, r.text

    r = client.post(
        "/api/auth/register",
        json={"username": "rl_reg_over", "password": "1234567890"},
    )
    assert r.status_code == 429, r.text
    assert r.json()["code"] == 42900
    assert r.json()["retry_after"] > 0

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()


def test_invalid_register_does_not_consume_quota():
    """格式不合法的注册不该消耗额度，否则前端调格式就把用户锁在门外。"""

    client = TestClient(app)
    for _ in range(ratelimit.REGISTER_IP_LIMIT + 2):
        r = client.post(
            "/api/auth/register", json={"username": "rl_x", "password": "short"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["code"] == 40002

    # 额度还没被吃掉，正常注册应该能过
    r = client.post(
        "/api/auth/register",
        json={"username": "rl_reg_after_bad", "password": "1234567890"},
    )
    assert r.json()["code"] == 0, r.text

    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()


def test_multi_worker_is_rejected(monkeypatch):
    """WEB_CONCURRENCY > 1 → 拒绝启动（契约：多 worker 必须拒绝，不能降级）。"""

    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(RuntimeError):
        ratelimit.assert_single_process()

    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    ratelimit.assert_single_process()


def test_workers_flag_is_rejected(monkeypatch):
    """uvicorn --workers N / -w N 同样拒绝。"""

    monkeypatch.setattr(sys, "argv", ["uvicorn", "app.main:app", "--workers", "4"])
    with pytest.raises(RuntimeError):
        ratelimit.assert_single_process()

    monkeypatch.setattr(sys, "argv", ["uvicorn", "app.main:app", "-w", "2"])
    with pytest.raises(RuntimeError):
        ratelimit.assert_single_process()

    monkeypatch.setattr(sys, "argv", ["uvicorn", "app.main:app", "--reload"])
    ratelimit.assert_single_process()
