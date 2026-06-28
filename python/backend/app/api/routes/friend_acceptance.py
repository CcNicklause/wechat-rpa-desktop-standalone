import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.app.api.deps import get_audit_logger, get_store
from backend.app.core.audit import AuditLogger
from backend.app.core.security import reject_batch_payload, require_auth
from backend.app.schemas.lead import LeadStatus
from backend.app.schemas.friend_acceptance import (
    FriendAcceptanceBatchResponse,
    FriendAcceptanceCheckRequest,
    FriendAcceptanceCheckResponse,
    FriendAcceptancePendingRequest,
)
from backend.app.services.friend_acceptance import FriendAcceptanceCheckResult, FriendAcceptanceService
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


class SimulateAcceptedRequest(BaseModel):
    lead_id: str | None = Field(default=None, min_length=1)
    account: str | None = Field(default=None, min_length=5, max_length=32)
    customer_name: str | None = Field(default=None, min_length=1, max_length=64)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


@router.post('/dev/simulate-accepted', response_model=FriendAcceptanceCheckResponse)
async def simulate_accepted(
    request: Request,
    store: SQLiteStore = Depends(get_store),
    audit: AuditLogger = Depends(get_audit_logger),
):
    payload_dict = await request.json()
    reject_batch_payload(payload_dict)
    payload = SimulateAcceptedRequest(**payload_dict)
    lead_id = payload.lead_id
    if not lead_id:
        if not payload.account:
            from backend.app.core.errors import AppError

            raise AppError('DEV_ACCOUNT_REQUIRED', '请提供 lead_id 或已是好友的账号')
        slug = re.sub(r'[^0-9A-Za-z_]+', '_', payload.account).strip('_')[:40] or 'account'
        lead_id = f'dev_friend_{slug}'

    lead = store.get_lead(lead_id)
    if not lead:
        timestamp = now_iso()
        account = payload.account or lead_id
        store.create_lead({
            'lead_id': lead_id,
            'customer_name': payload.customer_name or account,
            'company': 'Dev Friend Acceptance',
            'phone': account,
            'sales_id': 'dev_friend_acceptance',
            'status': LeadStatus.WECHAT_ADD_REQUESTED.value,
            'customer_consent': 1,
            'sales_confirmed_call': 1,
            'consent_evidence': 'dev simulated already-friend account',
            'created_at': timestamp,
            'updated_at': timestamp,
        })
    elif lead['status'] not in {LeadStatus.WECHAT_ADD_REQUESTED.value, LeadStatus.WECHAT_ACCEPTED.value}:
        store.update_lead(
            lead_id,
            status=LeadStatus.WECHAT_ADD_REQUESTED.value,
            updated_at=now_iso(),
        )

    def checker(phone: str, **_kwargs):
        return FriendAcceptanceCheckResult(
            phone=phone,
            accepted=True,
            state='ALREADY_FRIEND',
            matched_text='开发测试模拟：微信联系人页已出现发消息入口',
            steps=[
                'DEV_SIMULATED_ACCEPTANCE: 开发测试模拟好友已通过',
                'OCR_RAW_TEXT: 发消息',
            ],
        )

    service = FriendAcceptanceService(store, audit, checker=checker)
    return service.check_lead(lead_id)


@router.post('/dev/clear-pending')
async def clear_pending_friend_acceptance(store: SQLiteStore = Depends(get_store)):
    cleared = store.clear_leads_by_status(
        from_status=LeadStatus.WECHAT_ADD_REQUESTED.value,
        to_status=LeadStatus.RPA_BLOCKED.value,
        timestamp=now_iso(),
    )
    return {
        'status': 'cleared',
        'cleared': cleared,
        'from_status': LeadStatus.WECHAT_ADD_REQUESTED.value,
        'to_status': LeadStatus.RPA_BLOCKED.value,
    }
