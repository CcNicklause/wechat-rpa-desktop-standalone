import json
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import Settings
from backend.app.storage.sqlite_store import SQLiteStore


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditLogger:
    def __init__(self, store: SQLiteStore, settings: Settings):
        self.store = store
        self.settings = settings
        self.settings.audit_file.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event_type: str, **fields: Any) -> dict[str, Any]:
        event = {
            'event_id': f'audit_{uuid.uuid4().hex}',
            'event_type': event_type,
            'timestamp': utc_now(),
            **fields,
        }
        self.store.add_audit_event(event)
        with self.settings.audit_file.open('a', encoding='utf-8') as file:
            file.write(json.dumps(event, ensure_ascii=False) + '\n')
        return event
