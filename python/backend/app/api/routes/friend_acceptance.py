from fastapi import APIRouter, Depends, Request

from backend.app.api.deps import get_audit_logger, get_store
from backend.app.core.audit import AuditLogger
from backend.app.core.security import reject_batch_payload, require_auth
from backend.app.schemas.friend_acceptance import (
    FriendAcceptanceBatchResponse,
    FriendAcceptanceCheckRequest,
    FriendAcceptanceCheckResponse,
    FriendAcceptancePendingRequest,
)
from backend.app.services.friend_acceptance import FriendAcceptanceService
from backend.app.storage.sqlite_store import SQLiteStore

router = APIRouter(
    prefix='/api/v1/friend-acceptance',
    tags=['friend-acceptance'],
    dependencies=[Depends(require_auth)],
)


def get_friend_acceptance_service(
    store: SQLiteStore = Depends(get_store),
    audit: AuditLogger = Depends(get_audit_logger),
) -> FriendAcceptanceService:
    return FriendAcceptanceService(store, audit)


@router.post('/check', response_model=FriendAcceptanceCheckResponse)
async def check_acceptance(
    request: Request,
    service: FriendAcceptanceService = Depends(get_friend_acceptance_service),
):
    payload_dict = await request.json()
    reject_batch_payload(payload_dict)
    payload = FriendAcceptanceCheckRequest(**payload_dict)
    return service.check_lead(payload.lead_id)


@router.post('/check-pending', response_model=FriendAcceptanceBatchResponse)
async def check_pending_acceptance(
    request: Request,
    service: FriendAcceptanceService = Depends(get_friend_acceptance_service),
):
    payload_dict = await request.json()
    reject_batch_payload(payload_dict)
    payload = FriendAcceptancePendingRequest(**payload_dict)
    return service.check_pending(payload.limit)
