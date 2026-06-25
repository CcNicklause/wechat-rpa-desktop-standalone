from datetime import date
import platform

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.app.api.deps import get_store
from backend.app.core.config import Settings, get_settings
from backend.app.storage.sqlite_store import SQLiteStore

router = APIRouter(prefix='/api/v1', tags=['health'])


class SettingsUpdateRequest(BaseModel):
    daily_limit: int | None = Field(default=None, ge=1, le=15)
    require_human_approval: bool | None = None
    min_interval: int | None = Field(default=None, ge=0)
    max_interval: int | None = Field(default=None, ge=0)


@router.get('/health')
def health(
    settings: Settings = Depends(get_settings),
    store: SQLiteStore = Depends(get_store),
) -> dict:
    today = date.today().isoformat()
    used = store.get_daily_count('sales_demo_001', today)
    return {
        'status': 'ok',
        'app_env': settings.app_env,
        'rpa_mode': settings.rpa_mode,
        'platform': platform.system(),
        'daily_limit': settings.rpa_daily_limit,
        'daily_used': used,
        'real_rpa_requires_human_approval': settings.rpa_require_human_approval,
        'min_interval': settings.rpa_min_interval_seconds,
        'max_interval': settings.rpa_max_interval_seconds,
    }


@router.post('/health/settings')
def update_settings(
    payload: SettingsUpdateRequest,
    settings: Settings = Depends(get_settings),
) -> dict:
    if payload.daily_limit is not None:
        settings.rpa_daily_limit = payload.daily_limit
    if payload.require_human_approval is not None:
        settings.rpa_require_human_approval = payload.require_human_approval
    if payload.min_interval is not None:
        settings.rpa_min_interval_seconds = payload.min_interval
    if payload.max_interval is not None:
        settings.rpa_max_interval_seconds = payload.max_interval
    return {
        'status': 'ok',
        'daily_limit': settings.rpa_daily_limit,
        'real_rpa_requires_human_approval': settings.rpa_require_human_approval,
    }
