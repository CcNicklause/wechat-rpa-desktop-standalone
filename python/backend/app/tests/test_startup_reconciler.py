from pathlib import Path
from unittest.mock import MagicMock

from backend.app.core.config import Settings
from backend.app.main import startup
from backend.app.schemas.lead import LeadStatus
from backend.app.services.startup_reconciler import reconcile_on_startup
from backend.app.storage.sqlite_store import SQLiteStore


def _create_lead(store: SQLiteStore, lead_id: str, status: LeadStatus, updated_at: str) -> None:
    store.create_lead(
        {
            "lead_id": lead_id,
            "customer_name": "测试客户",
            "company": "测试公司",
            "phone": "18325661362",
            "sales_id": "sales_demo_001",
            "status": status.value,
            "created_at": updated_at,
            "updated_at": updated_at,
        }
    )


def test_reconcile_on_startup_blocks_stale_pending_leads(tmp_path: Path):
    store = SQLiteStore(tmp_path / "demo.db")
    audit = MagicMock()
    settings = Settings(
        startup_reconciler_pending_grace_seconds=600,
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    _create_lead(
        store,
        "lead_old",
        LeadStatus.RPA_PENDING_APPROVAL,
        "2026-06-28T00:00:00+00:00",
    )

    summary = reconcile_on_startup(store, audit, settings)

    assert summary["pending_lead_blocked"] == 1
    assert store.get_lead("lead_old")["status"] == LeadStatus.RPA_BLOCKED.value
    audit.record.assert_called_once()
    assert audit.record.call_args.args[0] == "rpa.reconciler.pending_too_long"


def test_reconcile_on_startup_keeps_recent_pending_leads(tmp_path: Path):
    store = SQLiteStore(tmp_path / "demo.db")
    audit = MagicMock()
    settings = Settings(
        startup_reconciler_pending_grace_seconds=86400,
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    from backend.app.core.audit import utc_now

    _create_lead(store, "lead_recent", LeadStatus.RPA_PENDING_APPROVAL, utc_now())

    summary = reconcile_on_startup(store, audit, settings)

    assert summary["pending_lead_blocked"] == 0
    assert store.get_lead("lead_recent")["status"] == LeadStatus.RPA_PENDING_APPROVAL.value
    audit.record.assert_not_called()


def test_reconcile_on_startup_audits_outbox_backlog(tmp_path: Path):
    store = SQLiteStore(tmp_path / "demo.db")
    audit = MagicMock()
    settings = Settings(
        startup_reconciler_outbox_alert_threshold=1,
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    for index in range(2):
        store.enqueue_lead_status_report(
            lead_id=f"lead_{index}",
            job_id=f"job_{index}",
            upstream_status="REAL_SENT",
            remark=None,
            error_details=None,
            payload={"lead_id": f"lead_{index}"},
            timestamp="2026-06-28T00:00:00+00:00",
        )

    summary = reconcile_on_startup(store, audit, settings)

    assert summary["lead_status_outbox_backlog"] == 2
    audit.record.assert_called_once()
    assert audit.record.call_args.args[0] == "startup_reconciler.outbox_backlog"


def test_startup_records_reconciler_failure_without_blocking(monkeypatch):
    from backend.app import main as main_module

    store = MagicMock()
    store.recover_interrupted_jobs.return_value = []
    audit = MagicMock()
    started = {"scheduler": False}

    class FakeScheduler:
        def __init__(self, *_args, **_kwargs):
            self.orchestrator_factory = None

        def notify_risk_event(self, **_kwargs):
            return None

        def start(self):
            started["scheduler"] = True

    def fail_reconcile(*_args, **_kwargs):
        raise RuntimeError("reconcile failed")

    monkeypatch.setattr(main_module, "get_store", lambda: store)
    monkeypatch.setattr(main_module, "AuditLogger", lambda *_args, **_kwargs: audit)
    monkeypatch.setattr(main_module, "reconcile_on_startup", fail_reconcile)
    monkeypatch.setattr(main_module, "UpstreamScheduler", FakeScheduler)
    monkeypatch.setattr(main_module, "start_friend_acceptance_rechecker", lambda *_args, **_kwargs: True)

    startup()

    assert started["scheduler"] is True
    event_names = [call.args[0] for call in audit.record.call_args_list]
    assert "startup_reconciler.failed" in event_names
