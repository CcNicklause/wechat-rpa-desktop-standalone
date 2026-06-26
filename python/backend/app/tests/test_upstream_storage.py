import gc
import tempfile
from pathlib import Path
from backend.app.storage.sqlite_store import SQLiteStore


def test_save_and_get_config():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        db_path = Path(tmp_dir.name) / "test.db"
        store = SQLiteStore(db_path)
        test_cfg = {"upstream_mode": "mock", "client_id": "test_c"}
        store.save_upstream_config(test_cfg)
        loaded = store.get_upstream_config()
        assert loaded["upstream_mode"] == "mock"
        assert loaded["client_id"] == "test_c"
    finally:
        # 释放 SQLite 文件锁后再清理临时目录
        store = None
        gc.collect()
        tmp_dir.cleanup()


def test_default_lead_source_mode_is_polling():
    from backend.app.core.config import Settings

    settings = Settings()

    assert settings.lead_source_mode == "polling"


import gc
import tempfile
from pathlib import Path

from backend.app.storage.sqlite_store import SQLiteStore


def test_create_lead_persists_consent_fields_when_provided():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        db_path = Path(tmp_dir.name) / "test.db"
        store = SQLiteStore(db_path)
        store.create_lead({
            "lead_id": "lead_with_consent",
            "customer_name": "授权客户",
            "company": "Upstream",
            "phone": "13800009999",
            "sales_id": "upstream",
            "status": "RPA_PENDING_APPROVAL",
            "customer_consent": 1,
            "sales_confirmed_call": 1,
            "consent_evidence": "upstream",
            "created_at": "2026-06-26T00:00:00+00:00",
            "updated_at": "2026-06-26T00:00:00+00:00",
        })

        lead = store.get_lead("lead_with_consent")

        assert lead is not None
        assert lead["customer_consent"] == 1
        assert lead["sales_confirmed_call"] == 1
        assert lead["consent_evidence"] == "upstream"
    finally:
        store = None
        gc.collect()
        tmp_dir.cleanup()


def test_create_lead_defaults_consent_fields_when_omitted():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        db_path = Path(tmp_dir.name) / "test.db"
        store = SQLiteStore(db_path)
        store.create_lead({
            "lead_id": "lead_no_consent",
            "customer_name": "默认客户",
            "company": "Local",
            "phone": "13800008888",
            "sales_id": "sales_demo_001",
            "status": "NEW_LEAD",
            "created_at": "2026-06-26T00:00:00+00:00",
            "updated_at": "2026-06-26T00:00:00+00:00",
        })

        lead = store.get_lead("lead_no_consent")

        assert lead is not None
        assert lead["customer_consent"] == 0
        assert lead["sales_confirmed_call"] == 0
        assert lead["consent_evidence"] is None
    finally:
        store = None
        gc.collect()
        tmp_dir.cleanup()
