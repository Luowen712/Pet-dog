from datetime import datetime, timedelta

from app.config import settings


def is_online(last_seen: datetime | None, at: datetime | None = None) -> bool:
    if last_seen is None:
        return False
    at = at or datetime.now()
    delta = at - last_seen
    return timedelta(0) <= delta <= timedelta(seconds=settings.ONLINE_TTL_SEC)
