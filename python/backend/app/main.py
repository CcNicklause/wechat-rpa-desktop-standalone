from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.deps import get_store
from backend.app.api.routes import audit, friend_acceptance, health, leads, rpa, upstream
from backend.app.core.audit import AuditLogger, utc_now
from backend.app.core.config import get_settings
from backend.app.services.friend_acceptance import (
    probe_screen_state_for_retry,
    start_friend_acceptance_rechecker,
    stop_friend_acceptance_rechecker,
)
from backend.app.services.rpa_orchestrator import RpaOrchestrator
from backend.app.services.startup_reconciler import reconcile_on_startup
from backend.app.services.upstream_scheduler import UpstreamScheduler
from backend.app.services.wechat_rpa import RpaBusinessOutcome

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
app.include_router(upstream.router)


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
    try:
        summary = reconcile_on_startup(store, audit_logger, settings)
        audit_logger.record(
            'startup_reconciler.completed',
            result='success',
            data=summary,
        )
    except Exception as exc:
        audit_logger.record(
            'startup_reconciler.failed',
            result='failed',
            reason_code=exc.__class__.__name__,
            message=str(exc),
        )

    # 初始化全局上游调度器单例。先 new 出来，再用它的 notify_risk_event 作为回调
    # 注入到 orchestrator，把"业务终态 RISK_CONTROL → 调度器 RISK_FROZEN"这条
    # 跨服务链路在启动时一次性闭环（设计 §1 触发路径）。
    upstream.global_scheduler = UpstreamScheduler(settings, store, lambda: None)

    def _retry_precheck(lead: dict, _greeting: str, update_step) -> None:
        """重试前轻量读屏核验（设计 §3）。直接抛 RpaBusinessOutcome 让 _run_job 收尾。"""
        result = probe_screen_state_for_retry(lead.get('phone', ''), job_id=lead.get('lead_id'))
        update_step(f"RETRY_PRECHECK_RESULT: state={result.state} matched={result.matched_text!r}")
        if result.state == "ALREADY_FRIEND":
            raise RpaBusinessOutcome("BIZ_ALREADY_FRIEND", "重试前核验发现对方已是好友")
        if result.state == "SEND_SUCCESS":
            raise RpaBusinessOutcome("BIZ_ALREADY_REQUESTED", "重试前核验发现申请已发出，避免重复点击")
        if result.state == "RISK_CONTROL":
            raise RpaBusinessOutcome(
                "BIZ_RISK_CONTROL",
                "重试前核验命中风控提示，本次任务进入熔断",
                circuit_break=True,
            )

    def orchestrator_factory():
        return RpaOrchestrator(
            store,
            audit_logger,
            settings,
            risk_event_handler=upstream.global_scheduler.notify_risk_event,
            retry_precheck=_retry_precheck,
        )

    upstream.global_scheduler.orchestrator_factory = orchestrator_factory
    upstream.global_scheduler.start()
    start_friend_acceptance_rechecker(
        settings,
        store,
        audit_logger,
        risk_event_handler=upstream.global_scheduler.notify_risk_event,
    )


@app.on_event('shutdown')
def shutdown() -> None:
    if upstream.global_scheduler:
        upstream.global_scheduler.stop()
    stop_friend_acceptance_rechecker()
