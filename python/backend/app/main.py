from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.deps import get_store
from backend.app.api.routes import audit, friend_acceptance, health, leads, rpa
from backend.app.core.audit import AuditLogger, utc_now
from backend.app.core.config import get_settings
from backend.app.services.friend_acceptance import (
    start_friend_acceptance_rechecker,
    stop_friend_acceptance_rechecker,
)

settings = get_settings()
import os
token = os.environ.get("LOCAL_SECURITY_TOKEN")
if token:
    settings.api_token = token

app = FastAPI(
    title='AI Sales Agent RPA Local Demo',
    description='本地企业级 RPA 加微验证 Demo：默认模拟执行，真实 RPA 需显式启用与人工确认。',
    version='0.1.0',
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=['GET', 'POST', 'OPTIONS'],
    allow_headers=['Authorization', 'Content-Type'],
)

app.include_router(health.router)
app.include_router(leads.router)
app.include_router(rpa.router)
app.include_router(friend_acceptance.router)
app.include_router(audit.router)


@app.on_event('startup')
def startup() -> None:
    store = get_store()
    store.init_db()
    audit_logger = AuditLogger(store, settings)
    for job in store.recover_interrupted_jobs(utc_now()):
        audit_logger.record(
            'rpa.job.interrupted',
            lead_id=job['lead_id'],
            result='failed',
            reason_code='SYS_RPA_INTERRUPTED',
            message='后端进程重启，已将上次遗留的运行中 RPA 任务标记为中断',
            data=job,
        )
    start_friend_acceptance_rechecker(settings, store, audit_logger)


@app.on_event('shutdown')
def shutdown() -> None:
    stop_friend_acceptance_rechecker()
