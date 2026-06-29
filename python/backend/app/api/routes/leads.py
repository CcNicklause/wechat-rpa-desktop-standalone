from fastapi import APIRouter, Depends, Request

from backend.app.api.deps import get_lead_service
from backend.app.core.security import reject_batch_payload, require_auth
from backend.app.schemas.lead import CallSummaryRequest, CallSummaryResponse, LeadCreateRequest, LeadResponse, LeadStatsResponse
from backend.app.services.lead_service import LeadService

router = APIRouter(prefix='/api/v1/leads', tags=['leads'], dependencies=[Depends(require_auth)])


@router.get('', response_model=list[LeadResponse])
def list_leads(
    limit: int = 100,
    service: LeadService = Depends(get_lead_service),
):
    return service.list_leads(limit)


@router.post('', response_model=LeadResponse)
async def create_lead(request: Request, service: LeadService = Depends(get_lead_service)):
    payload_dict = await request.json()
    reject_batch_payload(payload_dict)
    payload = LeadCreateRequest(**payload_dict)
    return service.create_lead(payload)


@router.post('/{lead_id}/call-start', response_model=LeadResponse)
def start_call(lead_id: str, service: LeadService = Depends(get_lead_service)):
    return service.start_call(lead_id)


@router.post('/{lead_id}/call-summary', response_model=CallSummaryResponse)
async def submit_summary(
    lead_id: str,
    request: Request,
    service: LeadService = Depends(get_lead_service),
):
    payload_dict = await request.json()
    reject_batch_payload(payload_dict)
    payload = CallSummaryRequest(**payload_dict)
    return service.submit_summary(lead_id, payload)


@router.get('/stats', response_model=LeadStatsResponse)
def get_lead_stats(
    service: LeadService = Depends(get_lead_service),
):
    """Get statistics for leads grouped by status categories."""
    return service.compute_lead_stats()
