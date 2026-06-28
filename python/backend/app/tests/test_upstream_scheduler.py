import gc
import subprocess
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from backend.app.core.config import get_settings
from backend.app.schemas.lead import LeadStatus
from backend.app.services.upstream_client import MockUpstreamClient
from backend.app.storage.sqlite_store import SQLiteStore
from backend.app.services.upstream_scheduler import UpstreamScheduler, _get_weixin_pids


class DummyOrchestrator:
    def add_wechat(self, lead_id, greeting, dry_run, human_approval):
        return {"job_id": "job_1", "status": "SUCCESS"}


def test_scheduler_lifecycle():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        settings = get_settings()
        db_path = Path(tmp_dir.name) / "test.db"
        store = SQLiteStore(db_path)

        # 写入 mock 模式配置
        store.save_upstream_config({"upstream_mode": "mock"})

        scheduler = UpstreamScheduler(
            settings=settings,
            store=store,
            orchestrator_factory=lambda: DummyOrchestrator(),
        )

        assert scheduler.is_alive() is False
        scheduler.start()
        assert scheduler.is_alive() is True

        # 触发一次拉取
        scheduler.trigger_fetch_now()
        scheduler.stop()
        assert scheduler.is_alive() is False
    finally:
        scheduler = None
        store = None
        gc.collect()
        tmp_dir.cleanup()


def test_trigger_fetch_now_persists_lead_with_valid_status():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        settings = get_settings()
        db_path = Path(tmp_dir.name) / "test.db"
        store = SQLiteStore(db_path)
        store.save_upstream_config({"upstream_mode": "mock"})

        scheduler = UpstreamScheduler(
            settings=settings,
            store=store,
            orchestrator_factory=lambda: DummyOrchestrator(),
        )
        scheduler.start()
        # Seed one mock lead so the polling source has something to enqueue
        from backend.app.services.upstream_client import MockUpstreamClient
        assert isinstance(scheduler.client, MockUpstreamClient)
        scheduler.client.seed_leads([{
            "lead_id": "mock_lead_1",
            "phone": "13800000001",
            "customer_name": "莫克测试1",
            "greeting": "测试上游线索，请求通过。",
        }])
        scheduler.trigger_fetch_now()
        scheduler.stop()

        lead = store.get_lead("mock_lead_1")
        assert lead is not None
        assert lead["status"] in {status.value for status in LeadStatus}
    finally:
        scheduler = None
        store = None
        gc.collect()
        tmp_dir.cleanup()


def test_get_weixin_pids_detects_weixin_process_name():
    def fake_run(args, **_kwargs):
        image_name = args[2].replace("IMAGENAME eq ", "")
        stdout = (
            '"Weixin.exe","6900","Console","1","18,472 K"\n'
            if image_name == "Weixin.exe"
            else "INFO: No tasks are running which match the specified criteria.\n"
        )
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    with patch("backend.app.services.upstream_scheduler.subprocess.run", side_effect=fake_run):
        assert _get_weixin_pids() == [6900]


def test_upstream_result_mapping_uses_job_business_status():
    cases = [
        ({"status": "REAL_COMPLETED"}, ("REAL_SENT", None)),
        ({"status": "SIMULATION_COMPLETED"}, ("REAL_SENT", None)),
        ({"status": "FAILED", "error_message": "timeout"}, ("BIZ_FAILED", "timeout")),
        (
            {"status": "REAL_BIZ_ALREADY_FRIEND", "error_message": "already"},
            ("BIZ_ALREADY_FRIEND", "already"),
        ),
        (
            {"status": "REAL_BIZ_TARGET_NOT_FOUND", "error_message": "missing"},
            ("BIZ_TARGET_NOT_FOUND", "missing"),
        ),
        (
            {"status": "REAL_BIZ_RISK_CONTROL", "error_message": "risk"},
            ("BIZ_RISK_CONTROL", "risk"),
        ),
        (
            {"status": "REAL_BIZ_ADD_REJECTED", "error_message": "rejected"},
            ("BIZ_ADD_REJECTED", "rejected"),
        ),
    ]

    for job, expected in cases:
        assert UpstreamScheduler._upstream_result_for_job(job) == expected


def make_scheduler_for_test(tmp_dir):
    settings = get_settings()
    db_path = Path(tmp_dir.name) / "test.db"
    store = SQLiteStore(db_path)
    store.save_upstream_config({"upstream_mode": "mock"})
    scheduler = UpstreamScheduler(
        settings=settings,
        store=store,
        orchestrator_factory=lambda: DummyOrchestrator(),
    )
    return scheduler, store


def test_enqueue_remote_lead_persists_valid_lead_and_queues_once():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, store = make_scheduler_for_test(tmp_dir)
        item = {
            "lead_id": "remote_lead_1",
            "phone": "13800000011",
            "customer_name": "赵六",
            "greeting": "你好，请通过。",
        }

        first_result = scheduler.enqueue_remote_lead(item)
        second_result = scheduler.enqueue_remote_lead(item)

        lead = store.get_lead("remote_lead_1")
        assert first_result is True
        assert second_result is False
        assert lead is not None
        assert lead["status"] == LeadStatus.RPA_PENDING_APPROVAL.value
        assert scheduler._task_queue.qsize() == 1
    finally:
        scheduler = None
        store = None
        gc.collect()
        tmp_dir.cleanup()


def test_enqueue_remote_lead_rejects_missing_required_field():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, store = make_scheduler_for_test(tmp_dir)
        item = {
            "lead_id": "remote_lead_missing_phone",
            "customer_name": "缺少手机号",
            "greeting": "你好，请通过。",
        }

        result = scheduler.enqueue_remote_lead(item)

        assert result is False
        assert store.get_lead("remote_lead_missing_phone") is None
        assert scheduler._task_queue.qsize() == 0
    finally:
        scheduler = None
        store = None
        gc.collect()
        tmp_dir.cleanup()


def test_trigger_fetch_now_delegates_to_configured_lead_source():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, store = make_scheduler_for_test(tmp_dir)

        class FakeLeadSource:
            def __init__(self):
                self.fetch_count = 0

            def fetch_once(self):
                self.fetch_count += 1
                return 0

        fake_source = FakeLeadSource()
        scheduler.lead_source = fake_source

        scheduler.trigger_fetch_now()

        assert fake_source.fetch_count == 1
    finally:
        scheduler = None
        store = None
        gc.collect()
        tmp_dir.cleanup()


def test_clear_queue_resets_duplicate_tracking():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, _store = make_scheduler_for_test(tmp_dir)
        item = {
            "lead_id": "remote_lead_clear",
            "phone": "13800000099",
            "customer_name": "清队伍",
            "greeting": "你好，请通过。",
        }

        assert scheduler.enqueue_remote_lead(item) is True
        scheduler.clear_queue()
        re_enqueue_result = scheduler.enqueue_remote_lead(item)

        assert re_enqueue_result is True
        assert scheduler._task_queue.qsize() == 1
    finally:
        scheduler = None
        gc.collect()
        tmp_dir.cleanup()


def test_enqueue_remote_lead_is_thread_safe_against_duplicate_inserts():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, _store = make_scheduler_for_test(tmp_dir)
        item = {
            "lead_id": "remote_lead_concurrent",
            "phone": "13800000077",
            "customer_name": "并发测试",
            "greeting": "你好，请通过。",
        }
        start_gate = threading.Event()
        results: list[bool] = []
        results_lock = threading.Lock()

        def worker():
            start_gate.wait()
            outcome = scheduler.enqueue_remote_lead(item)
            with results_lock:
                results.append(outcome)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        start_gate.set()
        for t in threads:
            t.join()

        assert sum(1 for outcome in results if outcome) == 1
        assert scheduler._task_queue.qsize() == 1
    finally:
        scheduler = None
        gc.collect()
        tmp_dir.cleanup()


def test_enqueue_remote_lead_skips_terminal_status():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, store = make_scheduler_for_test(tmp_dir)
        timestamp = "2026-06-26T00:00:00+00:00"
        store.create_lead({
            "lead_id": "remote_lead_terminal",
            "customer_name": "已加",
            "company": "Upstream",
            "phone": "13800000020",
            "sales_id": "upstream",
            "status": LeadStatus.WECHAT_ALREADY_FRIEND.value,
            "created_at": timestamp,
            "updated_at": timestamp,
        })

        result = scheduler.enqueue_remote_lead({
            "lead_id": "remote_lead_terminal",
            "phone": "13800000020",
            "customer_name": "已加",
            "greeting": "你好，请通过。",
        })

        reloaded = store.get_lead("remote_lead_terminal")
        assert result is False
        assert scheduler._task_queue.qsize() == 0
        assert reloaded is not None
        assert reloaded["status"] == LeadStatus.WECHAT_ALREADY_FRIEND.value
        assert "remote_lead_terminal" not in scheduler._queued_lead_ids
    finally:
        scheduler = None
        store = None
        gc.collect()
        tmp_dir.cleanup()


def test_enqueue_remote_lead_terminal_skip_does_not_block_other_leads():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, store = make_scheduler_for_test(tmp_dir)
        timestamp = "2026-06-26T00:00:00+00:00"
        store.create_lead({
            "lead_id": "remote_lead_terminal_blocker",
            "customer_name": "已加",
            "company": "Upstream",
            "phone": "13800000021",
            "sales_id": "upstream",
            "status": LeadStatus.WECHAT_ALREADY_FRIEND.value,
            "created_at": timestamp,
            "updated_at": timestamp,
        })

        terminal_result = scheduler.enqueue_remote_lead({
            "lead_id": "remote_lead_terminal_blocker",
            "phone": "13800000021",
            "customer_name": "已加",
            "greeting": "你好，请通过。",
        })
        fresh_result = scheduler.enqueue_remote_lead({
            "lead_id": "remote_lead_fresh",
            "phone": "13800000022",
            "customer_name": "新线索",
            "greeting": "你好，请通过。",
        })

        assert terminal_result is False
        assert fresh_result is True
        assert scheduler._task_queue.qsize() == 1
        queued_item = scheduler._task_queue.get_nowait()
        assert queued_item["lead_id"] == "remote_lead_fresh"
    finally:
        scheduler = None
        store = None
        gc.collect()
        tmp_dir.cleanup()


def test_worker_can_be_interrupted_while_polling_job():
    import time as _time

    class NeverFinishingOrchestrator:
        def add_wechat(self, lead_id, greeting, dry_run, human_approval):
            return {"job_id": f"job_{lead_id}", "status": "REAL_QUEUED"}

    class AlwaysRunningStore(SQLiteStore):
        def get_job(self, job_id):
            return {"job_id": job_id, "status": "REAL_RUNNING"}

    tmp_dir = tempfile.TemporaryDirectory()
    try:
        settings = get_settings()
        db_path = Path(tmp_dir.name) / "test.db"
        store = AlwaysRunningStore(db_path)
        store.save_upstream_config({"upstream_mode": "mock"})
        scheduler = UpstreamScheduler(
            settings=settings,
            store=store,
            orchestrator_factory=lambda: NeverFinishingOrchestrator(),
        )
        scheduler.start()

        scheduler.enqueue_remote_lead({
            "lead_id": "remote_lead_stop",
            "phone": "13800000030",
            "customer_name": "停止测试",
            "greeting": "你好，请通过。",
        })

        _time.sleep(0.5)

        t0 = _time.monotonic()
        scheduler.stop()
        elapsed = _time.monotonic() - t0

        assert elapsed < 3.0, f"stop() took {elapsed:.2f}s, expected < 3.0s"
        assert scheduler.is_alive() is False
    finally:
        scheduler = None
        store = None
        gc.collect()
        tmp_dir.cleanup()


def test_enqueue_remote_lead_writes_consent_fields():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, store = make_scheduler_for_test(tmp_dir)

        result = scheduler.enqueue_remote_lead({
            "lead_id": "remote_lead_consent",
            "phone": "13800000050",
            "customer_name": "授权客户",
            "greeting": "你好，请通过。",
        })

        lead = store.get_lead("remote_lead_consent")
        assert result is True
        assert lead is not None
        assert lead["customer_consent"] == 1
        assert lead["sales_confirmed_call"] == 1
        assert lead["consent_evidence"] == "upstream"
    finally:
        scheduler = None
        store = None
        gc.collect()
        tmp_dir.cleanup()


def test_friend_check_reports_are_sent_to_mock_upstream():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, store = make_scheduler_for_test(tmp_dir)
        scheduler.client = MockUpstreamClient()
        store.enqueue_friend_check_report(
            "friend_report_lead",
            True,
            "2026-06-26T00:00:00+00:00",
        )

        result = scheduler._report_friend_checks_once()

        reports = store.list_friend_check_reports()
        assert result["reported"] == 1
        assert result["failed"] == 0
        assert reports[0]["status"] == "SENT"
        assert scheduler.client.friend_check_reports() == [
            {"lead_id": "friend_report_lead", "is_friend": True}
        ]
    finally:
        scheduler = None
        store = None
        gc.collect()
        tmp_dir.cleanup()


# ----- Cycle 1 新增：lead_status_reports outbox 路径 -----

def test_report_lead_status_once_drains_pending_to_sent():
    """outbox 守护线程的核心：list_pending → client.report_lead_status → mark_sent。"""
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, store = make_scheduler_for_test(tmp_dir)
        scheduler.client = MockUpstreamClient()
        store.enqueue_lead_status_report(
            lead_id="lead_outbox_a",
            job_id="job_outbox_a",
            upstream_status="REAL_SENT",
            remark="13800==Customer",
            error_details=None,
            payload={"lead_id": "lead_outbox_a", "status": "REAL_SENT"},
            timestamp="2026-06-28T00:00:00+00:00",
        )

        result = scheduler._report_lead_status_once()

        assert result["reported"] == 1 and result["failed"] == 0
        assert store.list_pending_lead_status_reports(10) == []
    finally:
        scheduler = None
        store = None
        gc.collect()
        tmp_dir.cleanup()


def test_report_lead_status_once_marks_failed_after_max_attempts():
    """模拟上游持续失败：触达 max_attempts 后 status → FAILED 不再返出。"""
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, store = make_scheduler_for_test(tmp_dir)
        # 真实 settings 不可写，复制一份对象式的轻量代理
        scheduler.settings = type(
            "S", (),
            dict(
                lead_status_report_batch_size=10,
                lead_status_report_max_attempts=3,
                friend_check_report_batch_size=10,
            ),
        )()

        class _AlwaysFailClient(MockUpstreamClient):
            def report_lead_status(self, *a, **kw):
                return False

        scheduler.client = _AlwaysFailClient()
        store.enqueue_lead_status_report(
            lead_id="lead_fail",
            job_id="job_fail",
            upstream_status="REAL_SENT",
            remark=None,
            error_details=None,
            payload={},
            timestamp="2026-06-28T00:00:00+00:00",
        )

        for _ in range(3):
            scheduler._report_lead_status_once()

        # 状态机检查：FAILED 行不再返出 pending；再次 flush 也不重投，是 outbox 死信语义
        assert store.list_pending_lead_status_reports(10) == []
        assert scheduler._report_lead_status_once() == {
            "reported": 0, "failed": 0, "results": [],
        }
    finally:
        scheduler = None
        store = None
        gc.collect()
        tmp_dir.cleanup()


def test_worker_loop_writes_to_outbox_instead_of_direct_report():
    """关键改动：_worker_loop 不再直接 client.report_lead_status，
    而是 store.enqueue_lead_status_report；守护线程异步 flush。"""
    from backend.app.services.upstream_scheduler import UpstreamScheduler
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, store = make_scheduler_for_test(tmp_dir)

        captured_reports = []
        class _RecordingClient(MockUpstreamClient):
            def report_lead_status(self, *args, **kwargs):
                captured_reports.append(("direct", args, kwargs))
                return super().report_lead_status(*args, **kwargs)

        scheduler.client = _RecordingClient()

        class _ImmediateOrchestrator:
            def add_wechat(self, lead_id, greeting, dry_run, human_approval):
                store.create_job({
                    "job_id": "job_w1",
                    "lead_id": lead_id,
                    "status": "REAL_COMPLETED",
                    "rpa_mode": "real",
                    "dry_run": False,
                    "human_approval": False,
                    "greeting": greeting,
                    "steps": [],
                    "error_code": None,
                    "error_message": None,
                    "created_at": "2026-06-28T00:00:00+00:00",
                    "updated_at": "2026-06-28T00:00:00+00:00",
                })
                return {"job_id": "job_w1", "status": "REAL_COMPLETED"}

        scheduler.orchestrator_factory = lambda: _ImmediateOrchestrator()

        # 直接喂一条任务给 _task_queue，跑一次 worker 后 stop
        scheduler._task_queue.put({
            "lead_id": "lead_w1",
            "phone": "138",
            "customer_name": "WorkerCustomer",
            "greeting": "hi",
        })
        scheduler._task_queue.put(None)  # 立即结束
        scheduler._stop_event.clear()

        # 同步跑一次 worker_loop（不起线程，避免 cooldown sleep）
        with patch("backend.app.services.upstream_scheduler.random.randint", return_value=0):
            scheduler._worker_loop()

        # 关键断言 ①：_worker_loop 内**不再**直接调 client.report_lead_status
        assert captured_reports == []
        # 关键断言 ②：outbox 入队成功，等守护线程异步 flush
        pending = store.list_pending_lead_status_reports(10)
        assert len(pending) == 1
        assert pending[0]["job_id"] == "job_w1"
        assert pending[0]["upstream_status"] == "REAL_SENT"
        assert pending[0]["remark"] == "138=WorkerCustomer"

        # ③ 异步 flush 后才真正调用 client.report_lead_status
        scheduler._report_lead_status_once()
        assert len(captured_reports) == 1
        assert captured_reports[0][1][0] == "lead_w1"
        assert store.list_pending_lead_status_reports(10) == []
    finally:
        scheduler = None
        store = None
        gc.collect()
        tmp_dir.cleanup()
