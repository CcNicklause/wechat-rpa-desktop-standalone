import asyncio
import queue

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Dict, Any

from backend.app.api.deps import get_store, get_settings
from backend.app.storage.sqlite_store import SQLiteStore
from backend.app.core.config import Settings
from backend.app.services.upstream_client import MockUpstreamClient
from backend.app.services.upstream_scheduler import log_broadcaster

router = APIRouter(prefix="/api/v1/upstream", tags=["upstream"])

# 全局单例持有器，在 main.py startup 阶段实例化并拉起
global_scheduler = None


def get_scheduler():
    global global_scheduler
    return global_scheduler


@router.post("/config")
def save_config(config: Dict[str, Any], store: SQLiteStore = Depends(get_store)):
    store.save_upstream_config(config)

    # 动态重启调度器应用新配置
    scheduler = get_scheduler()
    if scheduler:
        if scheduler.is_alive():
            scheduler.stop()
        scheduler.start()

    return {"status": "configured", "scheduler_alive": scheduler.is_alive() if scheduler else False}


@router.get("/config")
def get_config(store: SQLiteStore = Depends(get_store)):
    return store.get_upstream_config()


@router.get("/status")
def get_status(scheduler=Depends(get_scheduler)):
    if not scheduler:
        return {"scheduler_alive": False, "wechat_online": False, "state": "IDLE", "queue_remaining": 0}

    from backend.app.services.upstream_scheduler import _get_weixin_pids
    return {
        "scheduler_alive": scheduler.is_alive(),
        "wechat_online": len(_get_weixin_pids()) > 0,
        "state": scheduler.status_state,
        "queue_remaining": scheduler._task_queue.qsize(),
    }


@router.post("/dev/trigger-fetch")
def trigger_fetch(scheduler=Depends(get_scheduler)):
    if not scheduler:
        raise HTTPException(status_code=400, detail="Scheduler not ready")
    scheduler.trigger_fetch_now()
    return {"status": "triggered"}


@router.post("/dev/trigger-heartbeat")
def trigger_heartbeat(scheduler=Depends(get_scheduler)):
    if not scheduler:
        raise HTTPException(status_code=400, detail="Scheduler not ready")
    scheduler.trigger_heartbeat_now()
    return {"status": "triggered"}


@router.post("/dev/trigger-friend-check-report")
def trigger_friend_check_report(scheduler=Depends(get_scheduler)):
    if not scheduler:
        raise HTTPException(status_code=400, detail="Scheduler not ready")
    return scheduler.trigger_friend_check_report_now()


@router.post("/dev/clear-queue")
def clear_queue(scheduler=Depends(get_scheduler)):
    if not scheduler:
        raise HTTPException(status_code=400, detail="Scheduler not ready")
    scheduler.clear_queue()
    return {"status": "cleared"}


@router.get("/dev/friend-check-reports")
def get_friend_check_reports(
    limit: int = 100,
    scheduler=Depends(get_scheduler),
    store: SQLiteStore = Depends(get_store),
):
    upstream_reports = []
    if scheduler and isinstance(scheduler.client, MockUpstreamClient):
        for report in scheduler.client.friend_check_reports():
            enriched = dict(report)
            lead = store.get_lead(enriched["lead_id"])
            if lead:
                enriched["customer_name"] = lead.get("customer_name")
                enriched["account"] = lead.get("phone")
                enriched["lead_status"] = lead.get("status")
            upstream_reports.append(enriched)
    return {
        "outbox": store.list_friend_check_reports(limit),
        "mock_upstream_reports": upstream_reports,
    }


class SeedLead(BaseModel):
    lead_id: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    customer_name: str = Field(min_length=1)
    greeting: str = Field(min_length=1)


class SeedMockLeadsRequest(BaseModel):
    leads: list[SeedLead] = Field(min_length=1)


@router.post("/dev/seed-mock-leads")
def seed_mock_leads(payload: SeedMockLeadsRequest, scheduler=Depends(get_scheduler)):
    if not scheduler or scheduler.client is None:
        raise HTTPException(status_code=400, detail="Scheduler not ready")
    if not isinstance(scheduler.client, MockUpstreamClient):
        raise HTTPException(
            status_code=400,
            detail="Seed only available in mock mode",
        )
    if scheduler.lead_source is None:
        raise HTTPException(status_code=400, detail="Scheduler not ready")

    leads = [lead.model_dump() for lead in payload.leads]
    seeded = scheduler.client.seed_leads(leads)
    log_broadcaster.log(
        f"收到前端开发测试页种子下发：{seeded} 条线索已入 mock 上游待发池"
    )
    accepted = scheduler.lead_source.fetch_once()

    return {
        "seeded": seeded,
        "accepted_by_scheduler": accepted,
        "scheduler_alive": scheduler.is_alive(),
    }


@router.get("/logs")
def sse_logs(request: Request):
    """通过 SSE 实时向前端输出后台运行日志流水"""

    async def event_generator():
        q = queue.Queue()
        log_broadcaster.add_listener(q)
        try:
            while True:
                # 检查连接断开
                if await request.is_disconnected():
                    break
                try:
                    # 轮询获取新日志
                    log_item = q.get_nowait()
                    yield f"data: {log_item}\n\n"
                except queue.Empty:
                    await asyncio.sleep(0.5)
        finally:
            log_broadcaster.remove_listener(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
