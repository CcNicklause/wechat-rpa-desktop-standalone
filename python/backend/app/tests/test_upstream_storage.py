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


# ----- Cycle 1 新增：lead_status_reports outbox / create_job_if_lead_idle -----

import pytest

from backend.app.storage.sqlite_store import LeadBusyError


def _make_store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "outbox.db")


def _make_job(job_id: str, lead_id: str, status: str = "REAL_QUEUED") -> dict:
    return {
        "job_id": job_id,
        "lead_id": lead_id,
        "status": status,
        "rpa_mode": "real",
        "dry_run": False,
        "human_approval": False,
        "greeting": "你好",
        "steps": [],
        "created_at": "2026-06-28T00:00:00+00:00",
        "updated_at": "2026-06-28T00:00:00+00:00",
    }


def test_enqueue_lead_status_report_creates_pending_row(tmp_path):
    store = _make_store(tmp_path)
    row = store.enqueue_lead_status_report(
        lead_id="lead_a",
        job_id="job_1",
        upstream_status="REAL_SENT",
        remark="138==Customer",
        error_details=None,
        payload={"lead_id": "lead_a", "status": "REAL_SENT"},
        timestamp="2026-06-28T00:00:00+00:00",
    )
    assert row["status"] == "PENDING"
    assert row["attempts"] == 0
    assert row["payload"]["status"] == "REAL_SENT"

    pending = store.list_pending_lead_status_reports(10)
    assert len(pending) == 1 and pending[0]["job_id"] == "job_1"


def test_lead_status_report_mark_sent_then_re_enqueue_keeps_sent(tmp_path):
    store = _make_store(tmp_path)
    store.enqueue_lead_status_report(
        lead_id="lead_a", job_id="job_1", upstream_status="REAL_SENT",
        remark=None, error_details=None, payload={},
        timestamp="2026-06-28T00:00:00+00:00",
    )
    store.mark_lead_status_report_sent("lead_a", "job_1", "2026-06-28T00:01:00+00:00")

    # 重复入队不应将 SENT 退回 PENDING
    row = store.enqueue_lead_status_report(
        lead_id="lead_a", job_id="job_1", upstream_status="REAL_SENT",
        remark=None, error_details=None, payload={"replay": True},
        timestamp="2026-06-28T00:02:00+00:00",
    )
    assert row["status"] == "SENT"
    pending = store.list_pending_lead_status_reports(10)
    assert pending == []


def test_lead_status_report_failure_increments_attempts(tmp_path):
    store = _make_store(tmp_path)
    store.enqueue_lead_status_report(
        lead_id="lead_a", job_id="job_1", upstream_status="REAL_SENT",
        remark=None, error_details=None, payload={},
        timestamp="2026-06-28T00:00:00+00:00",
    )
    row = store.mark_lead_status_report_failed(
        "lead_a", "job_1", "boom", "2026-06-28T00:01:00+00:00", max_attempts=8,
    )
    assert row["attempts"] == 1
    assert row["status"] == "PENDING"
    assert row["last_error"] == "boom"


def test_lead_status_report_reaches_failed_after_max_attempts(tmp_path):
    store = _make_store(tmp_path)
    store.enqueue_lead_status_report(
        lead_id="lead_a", job_id="job_1", upstream_status="REAL_SENT",
        remark=None, error_details=None, payload={},
        timestamp="2026-06-28T00:00:00+00:00",
    )
    final = None
    for _ in range(3):
        final = store.mark_lead_status_report_failed(
            "lead_a", "job_1", "boom", "2026-06-28T00:01:00+00:00", max_attempts=3,
        )
    assert final["status"] == "FAILED"
    assert final["attempts"] == 3
    assert store.list_pending_lead_status_reports(10) == []


def test_create_job_if_lead_idle_rejects_when_busy_job_exists(tmp_path):
    store = _make_store(tmp_path)
    busy = ("REAL_QUEUED", "REAL_RUNNING", "SIMULATION_QUEUED", "SIMULATION_RUNNING")
    store.create_job_if_lead_idle(_make_job("job_a", "lead_x"), busy)

    with pytest.raises(LeadBusyError) as ei:
        store.create_job_if_lead_idle(_make_job("job_b", "lead_x"), busy)
    assert ei.value.existing_job_id == "job_a"

    # 把第一个 job 标记终态后，新 job 可以创建
    store.update_job("job_a", status="REAL_COMPLETED")
    store.create_job_if_lead_idle(_make_job("job_c", "lead_x"), busy)
    assert store.get_job("job_c") is not None


def test_create_job_if_lead_idle_allows_different_leads(tmp_path):
    store = _make_store(tmp_path)
    busy = ("REAL_QUEUED", "REAL_RUNNING")
    store.create_job_if_lead_idle(_make_job("job_a", "lead_1"), busy)
    store.create_job_if_lead_idle(_make_job("job_b", "lead_2"), busy)
    assert store.get_job("job_a") is not None
    assert store.get_job("job_b") is not None
