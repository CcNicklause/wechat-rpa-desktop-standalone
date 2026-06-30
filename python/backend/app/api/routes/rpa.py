import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.app.api.deps import get_rpa_orchestrator
from backend.app.core.security import reject_batch_payload, require_auth
from backend.app.schemas.rpa import AddWechatRequest, AddWechatResponse, JobResponse, PrecheckRequest, PrecheckResponse
from backend.app.services.rpa_orchestrator import RpaOrchestrator

router = APIRouter(prefix='/api/v1/rpa', tags=['rpa'], dependencies=[Depends(require_auth)])


@router.post('/precheck', response_model=PrecheckResponse)
async def precheck(request: Request, rpa: RpaOrchestrator = Depends(get_rpa_orchestrator)):
    payload_dict = await request.json()
    reject_batch_payload(payload_dict)
    payload = PrecheckRequest(**payload_dict)
    return rpa.precheck(payload.lead_id)


@router.post('/add-wechat', response_model=AddWechatResponse)
async def add_wechat(request: Request, rpa: RpaOrchestrator = Depends(get_rpa_orchestrator)):
    payload_dict = await request.json()
    reject_batch_payload(payload_dict)
    payload = AddWechatRequest(**payload_dict)
    return rpa.add_wechat(payload.lead_id, payload.greeting, payload.dry_run, payload.human_approval)


@router.get('/jobs', response_model=list[JobResponse])
def list_jobs(
    lead_id: str,
    limit: int = 50,
    rpa: RpaOrchestrator = Depends(get_rpa_orchestrator),
):
    return rpa.list_jobs_by_lead(lead_id, limit)


@router.get('/jobs/{job_id}', response_model=JobResponse)
def get_job(job_id: str, rpa: RpaOrchestrator = Depends(get_rpa_orchestrator)):
    return rpa.get_job(job_id)


@router.get('/jobs/{job_id}/events')
async def job_events(job_id: str, rpa: RpaOrchestrator = Depends(get_rpa_orchestrator)):
    async def stream():
        last = None
        for _ in range(120):
            job = rpa.get_job(job_id)
            payload = json.dumps(job, ensure_ascii=False)
            if payload != last:
                yield f'data: {payload}\n\n'
                last = payload
            if job['status'] in {'SIMULATION_COMPLETED', 'REAL_COMPLETED', 'FAILED'}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type='text/event-stream')
