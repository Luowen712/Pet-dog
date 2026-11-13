from datetime import datetime, timedelta

from app.services.presence import is_online


def test_never_seen_is_offline():
    """从没上报过心跳的设备，last_seen 是 None，必须算离线。"""
    assert is_online(None) is False


def test_just_heartbeat_is_online():
    """刚上报完心跳，立刻查，应该在线。"""
    now = datetime.now()
    assert is_online(now, at=now) is True


def test_31s_ago_is_offline():
    """超过 30 秒 TTL，算离线。"""
    now = datetime.now()
    assert is_online(now - timedelta(seconds=31), at=now) is False


def test_exactly_30s_ago_is_still_online():
    """边界：正好 30 秒，源码用的是 <=，所以还在线。"""
    now = datetime.now()
    assert is_online(now - timedelta(seconds=30), at=now) is True


def test_future_timestamp_counts_as_online():
    """设备时钟比服务器快时会怎样？负数差值 -> 永远在线。

    这条不是在说这个行为是对的，而是先把现状钉住：
    哪天有人修了这个缺陷，这条测试会变红，提醒改成 is False。
    """
    now = datetime.now()
    assert is_online(now + timedelta(seconds=60), at=now) is True
