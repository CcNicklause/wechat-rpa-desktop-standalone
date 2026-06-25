from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    event_id: str
    event_type: str
    timestamp: str
    actor_id: str | None = None
    lead_id: str | None = None
    phone_masked: str | None = None
    rpa_mode: str | None = None
    dry_run: bool | None = None
    customer_consent: bool | None = None
    human_approval: bool | None = None
    result: str | None = None
    reason_code: str | None = None
    message: str | None = None
