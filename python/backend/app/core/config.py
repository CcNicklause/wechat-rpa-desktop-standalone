from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_env: str = 'local'
    api_token: str = 'dev-local-token'
    rpa_mode: Literal['simulation', 'real'] = 'real'
    rpa_daily_limit: int = Field(default=3, ge=1, le=15)
    rpa_min_interval_seconds: int = Field(default=3, ge=0)
    rpa_max_interval_seconds: int = Field(default=9, ge=0)
    rpa_task_timeout_seconds: int = Field(default=90, ge=15, le=600)
    rpa_require_human_approval: bool = False
    # 重试前先做一次"只看不点"的读屏核验，防止首次执行其实已经把申请发出去，
    # 第二次重复点击触发风控。
    rpa_retry_precheck_enabled: bool = True
    rpa_retry_precheck_timeout_seconds: int = Field(default=30, ge=5, le=180)
    # 触发 BIZ_RISK_CONTROL 后调度器进入 RISK_FROZEN 的持续时间。
    # 期间 worker 不消费队列、PollingLeadSource 跳过 fetch；心跳照常并上报 status=RISK_FROZEN。
    risk_freeze_seconds: int = Field(default=7200, ge=60, le=86400)
    friend_acceptance_recheck_enabled: bool = True
    friend_acceptance_recheck_interval_seconds: int = Field(default=300, ge=30, le=86400)
    friend_acceptance_recheck_batch_size: int = Field(default=3, ge=1, le=10)
    friend_acceptance_max_attempts: int = Field(default=12, ge=1, le=100)
    friend_check_report_interval_seconds: int = Field(default=60, ge=10, le=86400)
    friend_check_report_batch_size: int = Field(default=10, ge=1, le=50)
    lead_status_report_interval_seconds: int = Field(default=30, ge=5, le=86400)
    lead_status_report_batch_size: int = Field(default=20, ge=1, le=100)
    lead_status_report_max_attempts: int = Field(default=8, ge=1, le=50)
    startup_reconciler_enabled: bool = True
    startup_reconciler_pending_grace_seconds: int = Field(default=600, ge=60, le=86400)
    startup_reconciler_outbox_alert_threshold: int = Field(default=20, ge=1, le=10000)
    db_path: str = 'backend/data/demo.db'
    audit_log_path: str = 'backend/data/audit.jsonl'
    cors_allow_origins: str = 'http://127.0.0.1:5500,http://localhost:5500,null'

    upstream_mode: Literal['mock', 'real'] = 'mock'
    lead_source_mode: Literal['polling', 'sse', 'hybrid'] = 'polling'
    upstream_api_url: str = 'http://localhost:8000/api/v1/upstream'
    client_id: str = 'client-001'
    client_secret: str = 'secret-xyz123'
    upstream_heartbeat_interval_seconds: int = 30
    upstream_fetch_interval_seconds: int = 60

    @property
    def db_file(self) -> Path:
        from backend.app.core.paths import get_data_dir
        return get_data_dir() / Path(self.db_path).name

    @property
    def audit_file(self) -> Path:
        from backend.app.core.paths import get_data_dir
        return get_data_dir() / Path(self.audit_log_path).name

    @property
    def cors_origins(self) -> list[str]:
        return [
            "tauri://localhost",
            "http://localhost:1420",
            "http://localhost:5173", # Vite dev port
            "http://127.0.0.1:1420",
            "http://127.0.0.1:5500",
            "http://localhost:5500"
        ]


@lru_cache
def get_settings() -> Settings:
    import sys
    
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        env_file = exe_dir / '.env'
        if env_file.exists():
            return Settings(_env_file=str(env_file))
            
    return Settings()
