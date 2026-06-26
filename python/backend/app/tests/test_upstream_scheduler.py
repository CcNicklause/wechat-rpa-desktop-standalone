import gc
import subprocess
import tempfile
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


def test_fetch_action_stores_lead_with_valid_status():
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
