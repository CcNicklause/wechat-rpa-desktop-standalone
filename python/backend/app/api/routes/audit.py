from fastapi import APIRouter, Depends, Query

from backend.app.api.deps import get_store
from backend.app.core.security import require_auth
from backend.app.schemas.audit import AuditEventResponse
from backend.app.storage.sqlite_store import SQLiteStore

router = APIRouter(prefix='/api/v1/audit', tags=['audit'], dependencies=[Depends(require_auth)])


@router.get('', response_model=list[AuditEventResponse])
def list_audit(
    lead_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    store: SQLiteStore = Depends(get_store),
):
    return store.list_audit_events(lead_id=lead_id, limit=limit)
