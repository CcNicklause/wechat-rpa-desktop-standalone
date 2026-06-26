import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class SQLiteStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    lead_id TEXT PRIMARY KEY,
                    customer_name TEXT NOT NULL,
                    company TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    sales_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    intent TEXT,
                    summary TEXT,
                    customer_consent INTEGER NOT NULL DEFAULT 0,
                    sales_confirmed_call INTEGER NOT NULL DEFAULT 0,
                    consent_evidence TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rpa_jobs (
                    job_id TEXT PRIMARY KEY,
                    lead_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    rpa_mode TEXT NOT NULL,
                    dry_run INTEGER NOT NULL,
                    human_approval INTEGER NOT NULL,
                    greeting TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    outcome_type TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    actor_id TEXT,
                    lead_id TEXT,
                    phone_masked TEXT,
                    rpa_mode TEXT,
                    dry_run INTEGER,
                    customer_consent INTEGER,
                    human_approval INTEGER,
                    result TEXT,
                    reason_code TEXT,
                    message TEXT,
                    data_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS daily_counters (
                    sales_id TEXT NOT NULL,
                    day TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY (sales_id, day)
                );

                CREATE TABLE IF NOT EXISTS upstream_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            # 轻量迁移：为已存在的旧库补 outcome_type 列（CREATE TABLE IF NOT
            # EXISTS 不会修改已有表结构）。
            cols = {row[1] for row in conn.execute("PRAGMA table_info(rpa_jobs)")}
            if 'outcome_type' not in cols:
                conn.execute('ALTER TABLE rpa_jobs ADD COLUMN outcome_type TEXT')

    def create_lead(self, lead: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO leads (
                    lead_id, customer_name, company, phone, sales_id, status,
                    customer_consent, sales_confirmed_call, consent_evidence,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead['lead_id'], lead['customer_name'], lead['company'], lead['phone'],
                    lead['sales_id'], lead['status'],
                    int(bool(lead.get('customer_consent', 0))),
                    int(bool(lead.get('sales_confirmed_call', 0))),
                    lead.get('consent_evidence'),
                    lead['created_at'], lead['updated_at'],
                ),
            )

    def list_leads(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                'SELECT * FROM leads ORDER BY updated_at DESC LIMIT ?',
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_lead(self, lead_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute('SELECT * FROM leads WHERE lead_id = ?', (lead_id,)).fetchone()
        return dict(row) if row else None

    def update_lead(self, lead_id: str, **fields: Any) -> dict[str, Any]:
        if not fields:
            current = self.get_lead(lead_id)
            if current is None:
                raise KeyError(lead_id)
            return current
        assignments = ', '.join(f'{key} = ?' for key in fields.keys())
        values = list(fields.values()) + [lead_id]
        with self._lock, self._connect() as conn:
            conn.execute(f'UPDATE leads SET {assignments} WHERE lead_id = ?', values)
            row = conn.execute('SELECT * FROM leads WHERE lead_id = ?', (lead_id,)).fetchone()
        if not row:
            raise KeyError(lead_id)
        return dict(row)

    def create_job(self, job: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rpa_jobs (
                    job_id, lead_id, status, rpa_mode, dry_run, human_approval, greeting,
                    steps_json, error_code, error_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job['job_id'], job['lead_id'], job['status'], job['rpa_mode'],
                    int(job['dry_run']), int(job['human_approval']), job['greeting'],
                    json.dumps(job.get('steps', []), ensure_ascii=False), job.get('error_code'),
                    job.get('error_message'), job['created_at'], job['updated_at'],
                ),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute('SELECT * FROM rpa_jobs WHERE job_id = ?', (job_id,)).fetchone()
        if not row:
            return None
        job = dict(row)
        job['dry_run'] = bool(job['dry_run'])
        job['human_approval'] = bool(job['human_approval'])
        job['steps'] = json.loads(job.pop('steps_json') or '[]')
        return job

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any]:
        encoded = dict(fields)
        if 'steps' in encoded:
            encoded['steps_json'] = json.dumps(encoded.pop('steps'), ensure_ascii=False)
        if 'dry_run' in encoded:
            encoded['dry_run'] = int(encoded['dry_run'])
        if 'human_approval' in encoded:
            encoded['human_approval'] = int(encoded['human_approval'])
        assignments = ', '.join(f'{key} = ?' for key in encoded.keys())
        values = list(encoded.values()) + [job_id]
        with self._lock, self._connect() as conn:
            conn.execute(f'UPDATE rpa_jobs SET {assignments} WHERE job_id = ?', values)
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        return job

    def recover_interrupted_jobs(self, timestamp: str) -> list[dict[str, Any]]:
        running_statuses = (
            'REAL_QUEUED',
            'REAL_RUNNING',
            'SIMULATION_QUEUED',
            'SIMULATION_RUNNING',
        )
        placeholders = ','.join('?' for _ in running_statuses)
        error_message = '后端进程重启，已将上次遗留的运行中 RPA 任务标记为中断'
        recovered: list[dict[str, Any]] = []

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f'SELECT * FROM rpa_jobs WHERE status IN ({placeholders}) ORDER BY updated_at ASC',
                running_statuses,
            ).fetchall()
            for row in rows:
                job = dict(row)
                steps = json.loads(job.get('steps_json') or '[]')
                steps.append(f'SYS_RPA_INTERRUPTED: {error_message}')
                conn.execute(
                    """
                    UPDATE rpa_jobs
                    SET status = ?, steps_json = ?, error_code = ?, error_message = ?,
                        outcome_type = ?, updated_at = ?
                    WHERE job_id = ?
                    """,
                    (
                        'FAILED',
                        json.dumps(steps, ensure_ascii=False),
                        'SYS_RPA_INTERRUPTED',
                        error_message,
                        'system',
                        timestamp,
                        job['job_id'],
                    ),
                )
                conn.execute(
                    """
                    UPDATE leads
                    SET status = ?, updated_at = ?
                    WHERE lead_id = ? AND status = ?
                    """,
                    ('RPA_FAILED', timestamp, job['lead_id'], 'RPA_EXECUTING'),
                )
                recovered.append(
                    {
                        'job_id': job['job_id'],
                        'lead_id': job['lead_id'],
                        'previous_status': job['status'],
                    }
                )

        return recovered


    def add_audit_event(self, event: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    event_id, event_type, timestamp, actor_id, lead_id, phone_masked,
                    rpa_mode, dry_run, customer_consent, human_approval, result,
                    reason_code, message, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event['event_id'], event['event_type'], event['timestamp'], event.get('actor_id'),
                    event.get('lead_id'), event.get('phone_masked'), event.get('rpa_mode'),
                    self._nullable_bool(event.get('dry_run')),
                    self._nullable_bool(event.get('customer_consent')),
                    self._nullable_bool(event.get('human_approval')),
                    event.get('result'), event.get('reason_code'), event.get('message'),
                    json.dumps(event, ensure_ascii=False),
                ),
            )

    def list_audit_events(self, lead_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            if lead_id:
                rows = conn.execute(
                    'SELECT * FROM audit_events WHERE lead_id = ? ORDER BY timestamp DESC LIMIT ?',
                    (lead_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM audit_events ORDER BY timestamp DESC LIMIT ?',
                    (limit,),
                ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item.pop('data_json', None)
            for key in ('dry_run', 'customer_consent', 'human_approval'):
                if item.get(key) is not None:
                    item[key] = bool(item[key])
            result.append(item)
        return result

    def get_daily_count(self, sales_id: str, day: str) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                'SELECT count FROM daily_counters WHERE sales_id = ? AND day = ?',
                (sales_id, day),
            ).fetchone()
        return int(row['count']) if row else 0

    def increment_daily_count(self, sales_id: str, day: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_counters (sales_id, day, count) VALUES (?, ?, 1)
                ON CONFLICT(sales_id, day) DO UPDATE SET count = count + 1
                """,
                (sales_id, day),
            )

    def save_upstream_config(self, config: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            for k, v in config.items():
                conn.execute(
                    "INSERT OR REPLACE INTO upstream_config (key, value) VALUES (?, ?)",
                    (k, str(v))
                )

    def get_upstream_config(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM upstream_config").fetchall()
        return {row["key"]: row["value"] for row in rows}

    @staticmethod
    def _nullable_bool(value: Any) -> int | None:
        if value is None:
            return None
        return int(bool(value))
