import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable


class LeadBusyError(Exception):
    """该 lead 已存在状态为 busy_statuses 之一的 RPA job，禁止创建第二个 job。"""

    def __init__(self, lead_id: str, existing_job_id: str, existing_status: str):
        super().__init__(
            f"lead {lead_id} already has an in-flight job {existing_job_id} (status={existing_status})"
        )
        self.lead_id = lead_id
        self.existing_job_id = existing_job_id
        self.existing_status = existing_status


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
                    acceptance_attempts INTEGER NOT NULL DEFAULT 0,
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

                CREATE TABLE IF NOT EXISTS friend_check_reports (
                    lead_id TEXT PRIMARY KEY,
                    is_friend INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS lead_status_reports (
                    lead_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    upstream_status TEXT NOT NULL,
                    remark TEXT,
                    error_details TEXT,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (lead_id, job_id)
                );
                """
            )
            # 轻量迁移：为已存在的旧库补 outcome_type 列（CREATE TABLE IF NOT
            # EXISTS 不会修改已有表结构）。
            job_cols = {row[1] for row in conn.execute("PRAGMA table_info(rpa_jobs)")}
            if 'outcome_type' not in job_cols:
                conn.execute('ALTER TABLE rpa_jobs ADD COLUMN outcome_type TEXT')
            lead_cols = {row[1] for row in conn.execute("PRAGMA table_info(leads)")}
            if 'acceptance_attempts' not in lead_cols:
                conn.execute('ALTER TABLE leads ADD COLUMN acceptance_attempts INTEGER NOT NULL DEFAULT 0')

    def create_lead(self, lead: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO leads (
                    lead_id, customer_name, company, phone, sales_id, status,
                    customer_consent, sales_confirmed_call, consent_evidence,
                    acceptance_attempts, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead['lead_id'], lead['customer_name'], lead['company'], lead['phone'],
                    lead['sales_id'], lead['status'],
                    int(bool(lead.get('customer_consent', 0))),
                    int(bool(lead.get('sales_confirmed_call', 0))),
                    lead.get('consent_evidence'),
                    int(lead.get('acceptance_attempts', 0) or 0),
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

    def count_leads_by_status(self) -> dict[str, int]:
        """Count leads grouped by their status."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                'SELECT status, COUNT(*) AS count FROM leads GROUP BY status'
            ).fetchall()
        return {row['status']: int(row['count']) for row in rows}

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

    def clear_leads_by_status(self, *, from_status: str, to_status: str, timestamp: str) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE leads
                SET status = ?, updated_at = ?
                WHERE status = ?
                """,
                (to_status, timestamp, from_status),
            )
            return int(cursor.rowcount or 0)

    def list_leads_by_status_before(self, *, status: str, updated_before: str, limit: int = 500) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM leads
                WHERE status = ? AND updated_at < ?
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (status, updated_before, safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_reports_by_status(self, table_name: str, status: str) -> int:
        if table_name not in {'lead_status_reports', 'friend_check_reports'}:
            raise ValueError(f'unsupported report table: {table_name}')
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM {table_name} WHERE status = ?",
                (status,),
            ).fetchone()
        return int(row['count'] if row else 0)

    def wipe_business_data(self) -> dict[str, int]:
        """清空全部业务数据，保留 upstream_config 等配置。

        供开发测试页"一键清空数据"使用——属于不可恢复的危险操作，调用方需自行做二次确认。
        表名为硬编码白名单，避免外部输入拼到 SQL 里。
        """
        tables = (
            "leads",
            "rpa_jobs",
            "audit_events",
            "friend_check_reports",
            "lead_status_reports",
            "daily_counters",
        )
        counts: dict[str, int] = {}
        with self._lock, self._connect() as conn:
            for table in tables:
                cursor = conn.execute(f"DELETE FROM {table}")
                counts[table] = int(cursor.rowcount or 0)
        return counts

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

    def create_job_if_lead_idle(self, job: dict[str, Any], busy_statuses: Iterable[str]) -> None:
        """原子地为 lead 创建 job：如果该 lead 已有任何 status 属于 busy_statuses 的 job，
        抛出 LeadBusyError；否则插入新 job。SQLite `BEGIN IMMEDIATE` 持写锁，
        保证同一 lead_id 并发请求中只有一个成功。"""
        busy_list = tuple(busy_statuses)
        if not busy_list:
            self.create_job(job)
            return
        placeholders = ','.join('?' for _ in busy_list)
        with self._lock, self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                row = conn.execute(
                    f"SELECT job_id, status FROM rpa_jobs "
                    f"WHERE lead_id = ? AND status IN ({placeholders}) LIMIT 1",
                    (job['lead_id'], *busy_list),
                ).fetchone()
                if row:
                    conn.rollback()
                    raise LeadBusyError(job['lead_id'], row['job_id'], row['status'])
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
                conn.commit()
            except LeadBusyError:
                raise
            except Exception:
                conn.rollback()
                raise

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

    def list_jobs_by_lead(self, lead_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                'SELECT * FROM rpa_jobs WHERE lead_id = ? ORDER BY updated_at DESC LIMIT ?',
                (lead_id, limit),
            ).fetchall()
        jobs = []
        for row in rows:
            job = dict(row)
            job['dry_run'] = bool(job['dry_run'])
            job['human_approval'] = bool(job['human_approval'])
            job['steps'] = json.loads(job.pop('steps_json') or '[]')
            jobs.append(job)
        return jobs

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

    def enqueue_friend_check_report(self, lead_id: str, is_friend: bool, timestamp: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO friend_check_reports (
                    lead_id, is_friend, status, attempts, last_error, created_at, updated_at
                ) VALUES (?, ?, 'PENDING', 0, NULL, ?, ?)
                ON CONFLICT(lead_id) DO UPDATE SET
                    is_friend = excluded.is_friend,
                    status = CASE
                        WHEN friend_check_reports.status = 'SENT' THEN friend_check_reports.status
                        ELSE 'PENDING'
                    END,
                    last_error = CASE
                        WHEN friend_check_reports.status = 'SENT' THEN friend_check_reports.last_error
                        ELSE NULL
                    END,
                    updated_at = excluded.updated_at
                """,
                (lead_id, int(bool(is_friend)), timestamp, timestamp),
            )
            row = conn.execute(
                "SELECT * FROM friend_check_reports WHERE lead_id = ?",
                (lead_id,),
            ).fetchone()
        return self._decode_friend_check_report(dict(row))

    def list_friend_check_reports(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        with self._lock, self._connect() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT r.*, l.customer_name, l.phone AS account, l.status AS lead_status
                    FROM friend_check_reports r
                    LEFT JOIN leads l ON l.lead_id = r.lead_id
                    WHERE r.status = ?
                    ORDER BY r.updated_at DESC
                    LIMIT ?
                    """,
                    (status, safe_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT r.*, l.customer_name, l.phone AS account, l.status AS lead_status
                    FROM friend_check_reports r
                    LEFT JOIN leads l ON l.lead_id = r.lead_id
                    ORDER BY r.updated_at DESC
                    LIMIT ?
                    """,
                    (safe_limit,),
                ).fetchall()
        return [self._decode_friend_check_report(dict(row)) for row in rows]

    def list_pending_friend_check_reports(self, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 50))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM friend_check_reports
                WHERE status = 'PENDING'
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [self._decode_friend_check_report(dict(row)) for row in rows]

    def mark_friend_check_report_sent(self, lead_id: str, timestamp: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE friend_check_reports
                SET status = 'SENT', last_error = NULL, updated_at = ?
                WHERE lead_id = ?
                """,
                (timestamp, lead_id),
            )
            row = conn.execute(
                "SELECT * FROM friend_check_reports WHERE lead_id = ?",
                (lead_id,),
            ).fetchone()
        if not row:
            raise KeyError(lead_id)
        return self._decode_friend_check_report(dict(row))

    def mark_friend_check_report_failed(
        self,
        lead_id: str,
        error: str,
        timestamp: str,
        *,
        max_attempts: int = 5,
    ) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE friend_check_reports
                SET attempts = attempts + 1,
                    status = CASE WHEN attempts + 1 >= ? THEN 'FAILED' ELSE 'PENDING' END,
                    last_error = ?,
                    updated_at = ?
                WHERE lead_id = ?
                """,
                (max_attempts, error, timestamp, lead_id),
            )
            row = conn.execute(
                "SELECT * FROM friend_check_reports WHERE lead_id = ?",
                (lead_id,),
            ).fetchone()
        if not row:
            raise KeyError(lead_id)
        return self._decode_friend_check_report(dict(row))

    @staticmethod
    def _nullable_bool(value: Any) -> int | None:
        if value is None:
            return None
        return int(bool(value))

    @staticmethod
    def _decode_friend_check_report(report: dict[str, Any]) -> dict[str, Any]:
        report['is_friend'] = bool(report['is_friend'])
        report['attempts'] = int(report.get('attempts') or 0)
        return report

    # ----- lead_status_reports outbox（参考 friend_check_reports 同构） -----

    def enqueue_lead_status_report(
        self,
        *,
        lead_id: str,
        job_id: str,
        upstream_status: str,
        remark: str | None,
        error_details: str | None,
        payload: dict[str, Any],
        timestamp: str,
    ) -> dict[str, Any]:
        """UPSERT 一条上报记录。主键 (lead_id, job_id)，状态从 SENT 不退回 PENDING，
        重复 enqueue 等价于刷新 payload / remark / error_details 但保留 attempts."""
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO lead_status_reports (
                    lead_id, job_id, upstream_status, remark, error_details,
                    status, attempts, last_error, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'PENDING', 0, NULL, ?, ?, ?)
                ON CONFLICT(lead_id, job_id) DO UPDATE SET
                    upstream_status = excluded.upstream_status,
                    remark = excluded.remark,
                    error_details = excluded.error_details,
                    payload_json = excluded.payload_json,
                    status = CASE
                        WHEN lead_status_reports.status = 'SENT' THEN lead_status_reports.status
                        ELSE 'PENDING'
                    END,
                    last_error = CASE
                        WHEN lead_status_reports.status = 'SENT' THEN lead_status_reports.last_error
                        ELSE NULL
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    lead_id, job_id, upstream_status, remark, error_details,
                    payload_json, timestamp, timestamp,
                ),
            )
            row = conn.execute(
                "SELECT * FROM lead_status_reports WHERE lead_id = ? AND job_id = ?",
                (lead_id, job_id),
            ).fetchone()
        return self._decode_lead_status_report(dict(row))

    def list_pending_lead_status_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM lead_status_reports
                WHERE status = 'PENDING'
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [self._decode_lead_status_report(dict(row)) for row in rows]

    def mark_lead_status_report_sent(self, lead_id: str, job_id: str, timestamp: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE lead_status_reports
                SET status = 'SENT', last_error = NULL, updated_at = ?
                WHERE lead_id = ? AND job_id = ?
                """,
                (timestamp, lead_id, job_id),
            )
            row = conn.execute(
                "SELECT * FROM lead_status_reports WHERE lead_id = ? AND job_id = ?",
                (lead_id, job_id),
            ).fetchone()
        if not row:
            raise KeyError((lead_id, job_id))
        return self._decode_lead_status_report(dict(row))

    def mark_lead_status_report_failed(
        self,
        lead_id: str,
        job_id: str,
        error: str,
        timestamp: str,
        *,
        max_attempts: int = 8,
    ) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE lead_status_reports
                SET attempts = attempts + 1,
                    status = CASE WHEN attempts + 1 >= ? THEN 'FAILED' ELSE 'PENDING' END,
                    last_error = ?,
                    updated_at = ?
                WHERE lead_id = ? AND job_id = ?
                """,
                (max_attempts, error, timestamp, lead_id, job_id),
            )
            row = conn.execute(
                "SELECT * FROM lead_status_reports WHERE lead_id = ? AND job_id = ?",
                (lead_id, job_id),
            ).fetchone()
        if not row:
            raise KeyError((lead_id, job_id))
        return self._decode_lead_status_report(dict(row))

    @staticmethod
    def _decode_lead_status_report(report: dict[str, Any]) -> dict[str, Any]:
        report['attempts'] = int(report.get('attempts') or 0)
        payload = report.pop('payload_json', None)
        if payload:
            try:
                report['payload'] = json.loads(payload)
            except json.JSONDecodeError:
                report['payload'] = None
        else:
            report['payload'] = None
        return report
