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
from backend.app.services.rpa_orchestrator import RpaBusinessOutcome, RpaOrchestrator
from backend.app.storage.sqlite_store import SQLiteStore


class TestRpaAcceptanceLifecycle(unittest.TestCase):
    def test_real_rpa_success_with_direct_confirm_keeps_lead_pending_for_recheck(self):
        rpa, store, audit = self._make_orchestrator()

        def fake_add_request(_phone, _greeting, update_step, _job_id):
            update_step("ADD_DIRECTLY_CONFIRMED: 已处理“通过朋友验证”确认页")

        with patch.object(rpa, "_run_add_request_with_timeout", side_effect=fake_add_request), patch(
            "backend.app.services.rpa_orchestrator.random.uniform",
            return_value=0,
        ), patch("backend.app.services.rpa_orchestrator.time.sleep"):
            rpa._run_job("job_1")

        lead_updates = [call.kwargs for call in store.update_lead.call_args_list]
        self.assertIn({"status": LeadStatus.WECHAT_ADD_REQUESTED.value, "updated_at": unittest.mock.ANY}, lead_updates)
        event_names = [call.args[0] for call in audit.record.call_args_list]
        self.assertIn("wechat.friend.requested", event_names)
        store.enqueue_friend_check_report.assert_not_called()

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

    def test_real_rpa_queues_without_human_approval(self):
        store = MagicMock()
        audit = MagicMock()
        settings = MagicMock()
        settings.rpa_mode = "real"
        settings.rpa_daily_limit = 3
        settings.rpa_require_human_approval = True
        store.get_daily_count.return_value = 0
        store.get_lead.return_value = {
            "lead_id": "lead_auto",
            "phone": "lockthename",
            "sales_id": "sales_demo_001",
            "customer_consent": 1,
            "sales_confirmed_call": 1,
            "consent_evidence": "upstream",
        }
        rpa = RpaOrchestrator(store, audit, settings)

        with patch("backend.app.services.rpa_orchestrator.run_background"):
            response = rpa.add_wechat(
                lead_id="lead_auto",
                greeting="hello",
                dry_run=False,
                human_approval=False,
            )

        self.assertEqual(response["status"], "REAL_QUEUED")
        created_job = store.create_job_if_lead_idle.call_args.args[0]
        self.assertEqual(created_job["rpa_mode"], "real")
        self.assertFalse(created_job["human_approval"])

    def test_already_friend_business_outcome_queues_friend_report(self):
        rpa, store, _audit = self._make_orchestrator()
        lead = store.get_lead.return_value
        outcome = RpaBusinessOutcome(
            code="BIZ_ALREADY_FRIEND",
            message="对方已是好友，无需重复添加",
        )

        rpa._finalize_business_outcome("job_1", lead, [], outcome)

        store.update_lead.assert_called_with(
            lead["lead_id"],
            status=LeadStatus.WECHAT_ALREADY_FRIEND.value,
            updated_at=unittest.mock.ANY,
        )
        store.enqueue_friend_check_report.assert_called_once_with(
            lead["lead_id"],
            True,
            unittest.mock.ANY,
        )

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


# ----- Cycle 1 新增：per-lead 互斥 -----

class TestPerLeadMutualExclusion(unittest.TestCase):
    """add_wechat 入口必须用 create_job_if_lead_idle 原子去重，
    第二次同 lead 请求要抛 RPA_LEAD_BUSY (HTTP 409)。"""

    def _make_orchestrator(self):
        from backend.app.core.errors import AppError
        store = MagicMock()
        audit = MagicMock()
        settings = MagicMock()
        settings.rpa_mode = "real"
        settings.rpa_daily_limit = 3
        settings.rpa_require_human_approval = False
        store.get_daily_count.return_value = 0
        store.get_lead.return_value = {
            "lead_id": "lead_busy",
            "phone": "13800001111",
            "sales_id": "upstream",
            "customer_consent": 1,
            "sales_confirmed_call": 1,
            "consent_evidence": "upstream",
        }
        return RpaOrchestrator(store, audit, settings), store, audit, AppError

    def test_add_wechat_rejects_when_lead_busy(self):
        from backend.app.storage.sqlite_store import LeadBusyError
        rpa, store, audit, AppError = self._make_orchestrator()
        store.create_job_if_lead_idle.side_effect = LeadBusyError("lead_busy", "job_prev", "REAL_RUNNING")

        with patch("backend.app.services.rpa_orchestrator.run_background"):
            with self.assertRaises(AppError) as ctx:
                rpa.add_wechat(
                    lead_id="lead_busy",
                    greeting="hello",
                    dry_run=False,
                    human_approval=False,
                )

        assert ctx.exception.detail["code"] == "RPA_LEAD_BUSY"
        assert ctx.exception.status_code == 409
        event_names = [call.args[0] for call in audit.record.call_args_list]
        assert "rpa.blocked.lead_busy" in event_names

    def test_add_wechat_calls_create_job_if_lead_idle_with_busy_statuses(self):
        rpa, store, _audit, _AppError = self._make_orchestrator()

        with patch("backend.app.services.rpa_orchestrator.run_background"):
            rpa.add_wechat(
                lead_id="lead_busy",
                greeting="hi",
                dry_run=False,
                human_approval=False,
            )

        called_job, busy_statuses = store.create_job_if_lead_idle.call_args.args
        assert called_job["lead_id"] == "lead_busy"
        assert set(busy_statuses) == {
            "REAL_QUEUED", "REAL_RUNNING", "SIMULATION_QUEUED", "SIMULATION_RUNNING",
        }


if __name__ == "__main__":
    unittest.main()
