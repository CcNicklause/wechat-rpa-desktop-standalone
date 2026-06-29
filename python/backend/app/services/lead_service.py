import uuid
from datetime import datetime, timezone

from backend.app.core.audit import AuditLogger
from backend.app.core.errors import AppError, not_found
from backend.app.core.security import mask_phone
from backend.app.schemas.lead import CallSummaryRequest, LeadCreateRequest, LeadStatus, LeadStatsResponse
from backend.app.storage.sqlite_store import SQLiteStore


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LeadService:
    def __init__(self, store: SQLiteStore, audit: AuditLogger):
        self.store = store
        self.audit = audit

    def create_lead(self, payload: LeadCreateRequest) -> dict:
        timestamp = now_iso()
        lead = {
            'lead_id': f'lead_{uuid.uuid4().hex[:12]}',
            'customer_name': payload.customer_name,
            'company': payload.company,
            'phone': payload.phone,
            'sales_id': payload.sales_id,
            'status': LeadStatus.NEW_LEAD.value,
            'created_at': timestamp,
            'updated_at': timestamp,
        }
        self.store.create_lead(lead)
        self.audit.record(
            'lead.created',
            actor_id=payload.sales_id,
            lead_id=lead['lead_id'],
            phone_masked=mask_phone(payload.phone),
            result='success',
        )
        return self._public_lead(lead)

    def start_call(self, lead_id: str) -> dict:
        lead = self._require_lead(lead_id)
        if lead['status'] not in {LeadStatus.NEW_LEAD.value, LeadStatus.CALLING.value}:
            raise AppError('INVALID_STATE', '当前线索状态不允许开始通话')
        updated = self.store.update_lead(lead_id, status=LeadStatus.CALLING.value, updated_at=now_iso())
        self.audit.record(
            'lead.call_started',
            actor_id=updated['sales_id'],
            lead_id=lead_id,
            phone_masked=mask_phone(updated['phone']),
            result='success',
        )
        return self._public_lead(updated)

    def submit_summary(self, lead_id: str, payload: CallSummaryRequest) -> dict:
        lead = self._require_lead(lead_id)
        if lead['status'] not in {LeadStatus.CALLING.value, LeadStatus.INTENT_CONFIRMED.value, LeadStatus.RPA_PENDING_APPROVAL.value}:
            raise AppError('INVALID_STATE', '请先开始通话，再提交通话小结')
        if payload.intent == 'STRONG':
            if not payload.customer_consent or not payload.sales_confirmed_call or not payload.consent_evidence.strip():
                self.audit.record(
                    'rpa.blocked.no_consent',
                    actor_id=lead['sales_id'],
                    lead_id=lead_id,
                    phone_masked=mask_phone(lead['phone']),
                    customer_consent=payload.customer_consent,
                    result='blocked',
                    reason_code='CONSENT_REQUIRED',
                    message='缺少客户明确同意或通话确认',
                )
                raise AppError('CONSENT_REQUIRED', '缺少客户明确同意，禁止触发加微流程')
            status = LeadStatus.RPA_PENDING_APPROVAL.value
            next_action = 'RPA_PRECHECK'
        else:
            status = LeadStatus.INTENT_CONFIRMED.value
            next_action = None
        updated = self.store.update_lead(
            lead_id,
            status=status,
            intent=payload.intent,
            summary=payload.summary,
            customer_consent=int(payload.customer_consent),
            sales_confirmed_call=int(payload.sales_confirmed_call),
            consent_evidence=payload.consent_evidence.strip(),
            updated_at=now_iso(),
        )
        self.audit.record(
            'lead.intent_confirmed',
            actor_id=updated['sales_id'],
            lead_id=lead_id,
            phone_masked=mask_phone(updated['phone']),
            customer_consent=bool(updated['customer_consent']),
            result='success',
            message=f'intent={payload.intent}',
        )
        return {'lead_id': lead_id, 'status': updated['status'], 'next_action': next_action}

    def list_leads(self, limit: int = 100) -> list[dict]:
        leads = self.store.list_leads(limit)
        return [self._public_lead(lead) for lead in leads]

    def compute_lead_stats(self) -> LeadStatsResponse:
        """Compute lead statistics grouped by status categories."""
        status_counts = self.store.count_leads_by_status()

        # Define status groupings (matching frontend LEAD_STATUS_GROUPS)
        success_statuses = {'WECHAT_ACCEPTED', 'WECHAT_ALREADY_FRIEND'}
        running_statuses = {'CALLING', 'INTENT_CONFIRMED', 'RPA_PENDING_APPROVAL', 'RPA_EXECUTING', 'WECHAT_ADD_REQUESTED'}
        failed_statuses = {'RPA_BLOCKED', 'RPA_FAILED', 'WECHAT_TARGET_NOT_FOUND', 'WECHAT_ADD_REJECTED', 'WECHAT_RISK_CONTROL', 'WECHAT_ACCEPTANCE_EXHAUSTED'}
        neutral_statuses = {'NEW_LEAD', 'RPA_SIMULATED'}

        total = sum(status_counts.values())
        success = sum(status_counts.get(s, 0) for s in success_statuses)
        running = sum(status_counts.get(s, 0) for s in running_statuses)
        failed = sum(status_counts.get(s, 0) for s in failed_statuses)
        neutral = sum(status_counts.get(s, 0) for s in neutral_statuses)

        return LeadStatsResponse(
            total=total,
            success=success,
            running=running,
            failed=failed,
            neutral=neutral,
            status_counts=status_counts
        )

    def get_lead(self, lead_id: str) -> dict:
        return self._require_lead(lead_id)

    def update_status(self, lead_id: str, status: LeadStatus) -> None:
        self.store.update_lead(lead_id, status=status.value, updated_at=now_iso())

    def _require_lead(self, lead_id: str) -> dict:
        lead = self.store.get_lead(lead_id)
        if not lead:
            raise not_found('线索不存在')
        return lead

    @staticmethod
    def _public_lead(lead: dict) -> dict:
        return {
            'lead_id': lead['lead_id'],
            'customer_name': lead['customer_name'],
            'company': lead['company'],
            'phone_masked': mask_phone(lead['phone']),
            'sales_id': lead['sales_id'],
            'status': lead['status'],
        }
