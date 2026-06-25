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
    return RpaOrchestrator(store, audit, settings)
