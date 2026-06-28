from functools import lru_cache

from fastapi import Depends

from backend.app.core.audit import AuditLogger
from backend.app.core.config import Settings, get_settings
from backend.app.services.lead_service import LeadService
from backend.app.services.rpa_orchestrator import RpaOrchestrator
from backend.app.storage.sqlite_store import SQLiteStore


@lru_cache
def get_store() -> SQLiteStore:
    settings = get_settings()
    return SQLiteStore(settings.db_file)


def get_audit_logger(
    store: SQLiteStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> AuditLogger:
    return AuditLogger(store, settings)


def get_lead_service(
    store: SQLiteStore = Depends(get_store),
    audit: AuditLogger = Depends(get_audit_logger),
) -> LeadService:
    return LeadService(store, audit)


def get_rpa_orchestrator(
    store: SQLiteStore = Depends(get_store),
    audit: AuditLogger = Depends(get_audit_logger),
    settings: Settings = Depends(get_settings),
) -> RpaOrchestrator:
    # 通过 routes.upstream.global_scheduler 拿到 scheduler 单例的 notify_risk_event，
    # 把"HTTP 直接发起的 add-wechat 路径"也接入 RISK_FROZEN 联动。
    # 本模块在 import 时不能直接 import upstream（避免循环依赖），延迟到调用时取。
    from backend.app.api.routes import upstream as upstream_routes

    risk_handler = None
    if upstream_routes.global_scheduler is not None:
        risk_handler = upstream_routes.global_scheduler.notify_risk_event

    return RpaOrchestrator(store, audit, settings, risk_event_handler=risk_handler)
