import asyncio
import queue

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import Dict, Any

from backend.app.api.deps import get_store, get_settings
from backend.app.storage.sqlite_store import SQLiteStore
from backend.app.core.config import Settings
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


@router.post("/dev/clear-queue")
def clear_queue(scheduler=Depends(get_scheduler)):
    if not scheduler:
        raise HTTPException(status_code=400, detail="Scheduler not ready")
    scheduler.clear_queue()
    return {"status": "cleared"}


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
