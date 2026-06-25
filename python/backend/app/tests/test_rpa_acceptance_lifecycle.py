import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.schemas.lead import LeadStatus
from backend.app.services.friend_acceptance import (
    FriendAcceptanceCheckResult,
    FriendAcceptanceRecheckWorker,
)
from backend.app.services.rpa_orchestrator import RpaOrchestrator
from backend.app.storage.sqlite_store import SQLiteStore


class TestRpaAcceptanceLifecycle(unittest.TestCase):
    def test_real_rpa_success_with_direct_confirm_marks_lead_accepted(self):
        rpa, store, audit = self._make_orchestrator()

        def fake_add_request(_phone, _greeting, update_step, _job_id):
            update_step("ADD_DIRECTLY_CONFIRMED: 已处理“通过朋友验证”确认页")

        with patch.object(rpa, "_run_add_request_with_timeout", side_effect=fake_add_request), patch(
            "backend.app.services.rpa_orchestrator.random.uniform",
            return_value=0,
        ), patch("backend.app.services.rpa_orchestrator.time.sleep"):
            rpa._run_job("job_1")

        lead_updates = [call.kwargs for call in store.update_lead.call_args_list]
        self.assertIn({"status": LeadStatus.WECHAT_ACCEPTED.value, "updated_at": unittest.mock.ANY}, lead_updates)
        event_names = [call.args[0] for call in audit.record.call_args_list]
        self.assertIn("wechat.friend.accepted", event_names)

    def test_real_rpa_success_with_sent_request_keeps_lead_pending_and_records_request(self):
        rpa, store, audit = self._make_orchestrator()

        def fake_add_request(_phone, _greeting, update_step, _job_id):
            update_step("SEND_CONFIRMED: 已读屏确认好友申请发送成功")

        with patch.object(rpa, "_run_add_request_with_timeout", side_effect=fake_add_request), patch(
            "backend.app.services.rpa_orchestrator.random.uniform",
            return_value=0,
        ), patch("backend.app.services.rpa_orchestrator.time.sleep"):
            rpa._run_job("job_1")

        lead_updates = [call.kwargs for call in store.update_lead.call_args_list]
        self.assertIn({"status": LeadStatus.WECHAT_ADD_REQUESTED.value, "updated_at": unittest.mock.ANY}, lead_updates)
        event_names = [call.args[0] for call in audit.record.call_args_list]
        self.assertIn("wechat.friend.requested", event_names)

    def test_recheck_worker_turns_pending_request_into_accepted_lead(self):
        temp_dir = tempfile.TemporaryDirectory()
        store = SQLiteStore(Path(temp_dir.name) / "demo.db")
        store_ref = {"store": store}

        def cleanup():
            store_ref["store"] = None
            gc.collect()
            temp_dir.cleanup()

        self.addCleanup(cleanup)
        audit = MagicMock()
        store.create_lead(
            {
                "lead_id": "lead_pending",
                "customer_name": "测试客户",
                "company": "测试公司",
                "phone": "lockthename",
                "sales_id": "sales_demo_001",
                "status": LeadStatus.WECHAT_ADD_REQUESTED.value,
                "created_at": "2026-06-24T00:00:00+00:00",
                "updated_at": "2026-06-24T00:00:00+00:00",
            }
        )

        def checker(phone: str, **_kwargs):
            return FriendAcceptanceCheckResult(
                phone=phone,
                accepted=True,
                state="ALREADY_FRIEND",
                matched_text="发消息",
                steps=["OCR_RAW_TEXT: 发消息"],
            )

        worker = FriendAcceptanceRecheckWorker(
            store=store,
            audit=audit,
            batch_size=1,
            checker=checker,
        )

        result = worker.run_once()

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(store.get_lead("lead_pending")["status"], LeadStatus.WECHAT_ACCEPTED.value)
        self.assertEqual(audit.record.call_args.args[0], "wechat.friend.accepted")

    def test_store_recovers_interrupted_running_jobs_on_startup(self):
        temp_dir = tempfile.TemporaryDirectory()
        store = SQLiteStore(Path(temp_dir.name) / "demo.db")
        store_ref = {"store": store}

        def cleanup():
            store_ref["store"] = None
            gc.collect()
            temp_dir.cleanup()

        self.addCleanup(cleanup)
        store.create_lead(
            {
                "lead_id": "lead_running",
                "customer_name": "测试客户",
                "company": "测试公司",
                "phone": "lockthename",
                "sales_id": "sales_demo_001",
                "status": LeadStatus.RPA_EXECUTING.value,
                "created_at": "2026-06-24T00:00:00+00:00",
                "updated_at": "2026-06-24T00:00:00+00:00",
            }
        )
        store.create_job(
            {
                "job_id": "job_running",
                "lead_id": "lead_running",
                "status": "REAL_RUNNING",
                "rpa_mode": "real",
                "dry_run": False,
                "human_approval": True,
                "greeting": "你好",
                "steps": ["WECHAT_WINDOW_FOUND"],
                "created_at": "2026-06-24T00:00:00+00:00",
                "updated_at": "2026-06-24T00:00:00+00:00",
            }
        )

        recovered = store.recover_interrupted_jobs("2026-06-24T10:55:00+00:00")

        self.assertEqual([item["job_id"] for item in recovered], ["job_running"])
        job = store.get_job("job_running")
        self.assertEqual(job["status"], "FAILED")
        self.assertEqual(job["error_code"], "SYS_RPA_INTERRUPTED")
        self.assertEqual(job["outcome_type"], "system")
        self.assertEqual(store.get_lead("lead_running")["status"], LeadStatus.RPA_FAILED.value)

    def _make_orchestrator(self):
        store = MagicMock()
        audit = MagicMock()
        settings = MagicMock()
        settings.rpa_daily_limit = 3
        settings.rpa_task_timeout_seconds = 90
        settings.rpa_min_interval_seconds = 0
        settings.rpa_max_interval_seconds = 0
        settings.rpa_mode = "real"

        job = {
            "job_id": "job_1",
            "lead_id": "lead_1",
            "status": "REAL_QUEUED",
            "rpa_mode": "real",
            "dry_run": False,
            "human_approval": True,
            "greeting": "你好",
            "steps": [],
        }
        lead = {
            "lead_id": "lead_1",
            "phone": "lockthename",
            "sales_id": "sales_demo_001",
            "customer_consent": 1,
        }
        store.get_job.return_value = job
        store.get_lead.return_value = lead
        return RpaOrchestrator(store, audit, settings), store, audit


if __name__ == "__main__":
    unittest.main()
