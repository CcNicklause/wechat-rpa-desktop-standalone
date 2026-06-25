from backend.app.core.errors import AppError


def assert_lead_has_consent(lead: dict) -> None:
    if not bool(lead.get('customer_consent')) or not bool(lead.get('sales_confirmed_call')) or not (lead.get('consent_evidence') or '').strip():
        raise AppError('CONSENT_REQUIRED', '缺少客户明确同意，禁止触发加微流程')
