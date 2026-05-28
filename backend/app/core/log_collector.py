import collections
import csv
import io
import logging
from datetime import datetime


class _InMemoryHandler(logging.Handler):
    def __init__(self, store: collections.deque):
        super().__init__()
        self._store = store

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        self._store.append({
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": msg,
        })


class LogCollector:
    def __init__(self, maxlen: int = 2000) -> None:
        self._logs: collections.deque = collections.deque(maxlen=maxlen)
        handler = _InMemoryHandler(self._logs)
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        if root.level == logging.WARNING or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
        root.addHandler(handler)

    def get(self, level: str | None = None, limit: int = 500) -> list[dict]:
        entries = list(self._logs)
        if level and level.upper() not in ("ALL", ""):
            entries = [e for e in entries if e["level"] == level.upper()]
        return list(reversed(entries))[:limit]

    def clear_old(self, keep_last: int = 200) -> int:
        removed = max(0, len(self._logs) - keep_last)
        while len(self._logs) > keep_last:
            self._logs.popleft()
        return removed

    def to_csv(self, level: str | None = None) -> str:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["timestamp", "level", "logger", "message"])
        writer.writeheader()
        writer.writerows(self.get(level=level, limit=10000))
        return buf.getvalue()


log_collector = LogCollector()
