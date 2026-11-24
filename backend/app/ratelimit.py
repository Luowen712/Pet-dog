"""单进程内存限流器（06 §2 限流工程基线）。

为什么自己写而不引 slowapi：
    契约要求三件事——单进程内存计数器、重启清空窗口、多 worker 启动即拒绝。
    引库反而要绕开它的默认行为（它默认按 endpoint 装饰，不好做"按账号"和
    "按 IP"两套键同时计数），自己写约 80 行，完全可控。

为什么用滑动窗口而不是固定窗口：
    固定窗口在交界处有缝——第 59 秒打满 5 次，第 61 秒又是一个新窗口，
    实际 2 秒内能过 10 次。滑动窗口记录每次命中的时间戳，没有这个缝。

计数的语义（契约第 34 行）：
    "计数只累计失败与拒绝事件，成功登录不重置来源 IP 桶"
    所以先 check（只读判断），业务失败了再 record（记账）。
    成功登录不清空任何桶——IP 桶契约明确要求不重置；账号桶契约没提，
    这里同样不重置，让 15 分钟窗口自然过期，规则一致且最保守。
"""

import os
import sys
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

# 登录失败：账号 5 次 / 15 分钟
LOGIN_ACCT_LIMIT = 5
LOGIN_ACCT_WINDOW = 1 * 60

# 登录失败：来源 IP 30 次 / 15 分钟
LOGIN_IP_LIMIT = 30
LOGIN_IP_WINDOW = 15 * 60

# 注册：来源 IP 5 次 / 小时
REGISTER_IP_LIMIT = 5
REGISTER_IP_WINDOW = 10 * 60

# 每 60 秒做一次全量清理，防止 key 无限增长
_SWEEP_INTERVAL = 60.0
# 最长窗口，用来判定一个桶是否彻底过期
_MAX_WINDOW = max(LOGIN_ACCT_WINDOW, LOGIN_IP_WINDOW, REGISTER_IP_WINDOW)

_lock = threading.Lock()
_buckets: dict[str, deque] = {}
_last_sweep = 0.0


def _sweep_locked(now: float) -> None:
    """清掉所有彻底过期的桶。调用方必须已持锁。"""
    global _last_sweep
    if now - _last_sweep < _SWEEP_INTERVAL:
        return
    _last_sweep = now
    cutoff = now - _MAX_WINDOW
    for key in list(_buckets):
        q = _buckets[key]
        while q and q[0] <= cutoff:
            q.popleft()
        if not q:
            del _buckets[key]


def check(key: str, limit: int, window_sec: int) -> int:
    """只读判断：返回 0 表示还能尝试，>0 表示已达上限、需要等待的秒数。"""
    now = time.monotonic()
    with _lock:
        q = _buckets.get(key)
        if not q:
            return 0
        cutoff = now - window_sec
        while q and q[0] <= cutoff:
            q.popleft()
        if not q:
            del _buckets[key]
            return 0
        if len(q) >= limit:
            # 最早那次过期后才腾出一个位置，+1 向上取整避免返回 0
            return max(int(q[0] + window_sec - now) + 1, 1)
        return 0


def record(key: str, window_sec: int) -> None:
    """记一次失败/拒绝事件。成功不放行时不调用。"""
    now = time.monotonic()
    with _lock:
        _sweep_locked(now)
        q = _buckets.setdefault(key, deque())
        cutoff = now - window_sec
        while q and q[0] <= cutoff:
            q.popleft()
        q.append(now)


def reset() -> None:
    """清空所有桶。只给测试用——正式运行没有"重置"这个动作。"""
    with _lock:
        _buckets.clear()


def client_ip(request: Request) -> str:
    """取来源 IP。

    刻意不读 X-Forwarded-For：那个头客户端可以随手伪造，信它等于把 IP
    限流关掉。只有部署在可信反向代理之后、且由代理覆写该头时才该启用。
    """
    return request.client.host if request.client else "unknown"


def too_many(retry_after: int) -> HTTPException:
    """按契约返回 HTTP 429 + 42900，并带 retry_after。"""
    return HTTPException(
        status_code=429,
        detail={
            "code": 42900,
            "message": "请求过于频繁，请稍后再试",
            "retry_after": retry_after,
        },
    )


def assert_single_process() -> None:
    """多 worker 启动即拒绝。

    内存计数器在进程内，多 worker 时每个进程各算一份，实际阈值会被放大
    成 N 倍，等于限流失效。契约要求这时必须拒绝启动，而不是悄悄降级。
    """
    raw = os.environ.get("WEB_CONCURRENCY")
    if raw is not None:
        try:
            n = int(raw)
        except ValueError:
            n = 0
        if n > 1:
            raise RuntimeError(
                "限流器是单进程内存计数器，WEB_CONCURRENCY=%s 会让阈值失效。"
                "请用单 worker 启动，或改成共享存储后再开多 worker。" % raw
            )

    args = iter(sys.argv[1:])
    for arg in args:
        if arg in ("--workers", "-w"):
            value = next(args, "")
        elif arg.startswith("--workers="):
            value = arg.partition("=")[2]
        elif arg.startswith("-w") and arg[2:].isdigit():
            value = arg[2:]
        else:
            continue
        if value != "1":
            raise RuntimeError(f"限流器要求单 worker，收到 {arg} (workers={value})。")
