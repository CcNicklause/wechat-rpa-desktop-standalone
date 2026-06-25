import threading
from contextlib import contextmanager
from datetime import date

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.storage.sqlite_store import SQLiteStore


class RpaRuntimeGuard:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    @contextmanager
    def single_task(self):
        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            raise AppError('RPA_BUSY', '当前已有 RPA 任务执行中，请稍后再试', 409)
        try:
            yield
        finally:
            self._lock.release()


runtime_guard = RpaRuntimeGuard()


def enforce_daily_limit(store: SQLiteStore, settings: Settings, sales_id: str) -> None:
    today = date.today().isoformat()
    used = store.get_daily_count(sales_id, today)
    if used >= settings.rpa_daily_limit:
        raise AppError('DAILY_CIRCUIT_BREAKER_OPEN', '今日真实加微次数已达安全上限，请人工处理', 429)


def increment_daily_count(store: SQLiteStore, sales_id: str) -> None:
    store.increment_daily_count(sales_id, date.today().isoformat())
