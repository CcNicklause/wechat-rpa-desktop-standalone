from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.core.audit import AuditLogger, utc_now
from backend.app.schemas.lead import LeadStatus
from backend.app.storage.sqlite_store import SQLiteStore


def reconcile_on_startup(store: SQLiteStore, audit: AuditLogger, settings) -> dict:
    summary = {
        "pending_lead_blocked": 0,
        "lead_status_outbox_backlog": 0,
        "friend_check_outbox_backlog": 0,
    }
    if not getattr(settings, "startup_reconciler_enabled", True):
        return summary

    grace_seconds = int(getattr(settings, "startup_reconciler_pending_grace_seconds", 600))
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=grace_seconds)).isoformat()
    timestamp = utc_now()

    pending_rows = store.list_leads_by_status_before(
        status=LeadStatus.RPA_PENDING_APPROVAL.value,
        updated_before=cutoff,
    )
    for lead in pending_rows:
        store.update_lead(
            lead["lead_id"],
            status=LeadStatus.RPA_BLOCKED.value,
            updated_at=timestamp,
        )
        audit.record(
            "rpa.reconciler.pending_too_long",
            actor_id=lead.get("sales_id"),
            lead_id=lead["lead_id"],
            result="blocked",
            reason_code="RPA_PENDING_APPROVAL_TIMEOUT",
            message="启动自检发现线索长时间停留在待审批状态，已标记为阻塞",
            data={
                "lead_id": lead["lead_id"],
                "previous_status": lead["status"],
                "previous_updated_at": lead["updated_at"],
                "cutoff": cutoff,
            },
        )
        summary["pending_lead_blocked"] += 1

    summary["lead_status_outbox_backlog"] = store.count_reports_by_status(
        "lead_status_reports",
        "PENDING",
    )
    summary["friend_check_outbox_backlog"] = store.count_reports_by_status(
        "friend_check_reports",
        "PENDING",
    )

    threshold = int(getattr(settings, "startup_reconciler_outbox_alert_threshold", 20))
    if (
        summary["lead_status_outbox_backlog"] > threshold
        or summary["friend_check_outbox_backlog"] > threshold
    ):
        audit.record(
            "startup_reconciler.outbox_backlog",
            result="warning",
            reason_code="OUTBOX_BACKLOG",
            message="启动自检发现 outbox 积压",
            data=summary,
        )

    return summary
