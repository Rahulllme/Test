import threading
from datetime import datetime, timezone


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ManualClock:
    def __init__(self, now: datetime):
        self._lock = threading.Lock()
        self._now = now.astimezone(timezone.utc)

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, now: datetime) -> None:
        with self._lock:
            self._now = now.astimezone(timezone.utc)
