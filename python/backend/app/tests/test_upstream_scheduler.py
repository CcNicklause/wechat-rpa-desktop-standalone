import gc
import subprocess
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from backend.app.core.config import get_settings
from backend.app.schemas.lead import LeadStatus
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
