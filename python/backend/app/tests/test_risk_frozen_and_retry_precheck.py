"""Cycle 2 测试：RISK_FROZEN 调度器状态机 + RPA 重试前核验。

设计章节参见 docs/rpa-hardening-plan.md §1 / §3。
"""
from __future__ import annotations

import gc
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.schemas.lead import LeadStatus
from backend.app.services.rpa_orchestrator import RpaBusinessOutcome, RpaOrchestrator
from backend.app.services.upstream_client import MockUpstreamClient
from backend.app.services.upstream_scheduler import UpstreamScheduler
from backend.app.storage.sqlite_store import SQLiteStore


def _make_scheduler(tmp_dir, *, freeze_seconds: int = 60):
    """轻量 scheduler，不实际启动线程，只暴露 is_frozen / notify_risk_event 等 API。"""
    from backend.app.core.config import get_settings
    settings = get_settings()
    settings.risk_freeze_seconds = freeze_seconds
    db_path = Path(tmp_dir.name) / "test.db"
    store = SQLiteStore(db_path)
    store.save_upstream_config({"upstream_mode": "mock"})
    scheduler = UpstreamScheduler(
        settings=settings,
        store=store,
        orchestrator_factory=lambda: None,
    )
    scheduler.client = MockUpstreamClient()
    return scheduler, store


# ============ 设计 §1 — RISK_FROZEN ============

def test_notify_risk_event_freezes_scheduler():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, _ = _make_scheduler(tmp_dir, freeze_seconds=60)
        assert scheduler.is_frozen() is False
        assert scheduler._compute_status_state() == "IDLE"

        scheduler.notify_risk_event(reason="BIZ_RISK_CONTROL")

        assert scheduler.is_frozen() is True
        assert scheduler._compute_status_state() == "RISK_FROZEN"
        assert 0 < scheduler.get_frozen_remaining_seconds() <= 60
        assert scheduler._last_risk_at is not None
    finally:
        scheduler = None
        gc.collect()
        tmp_dir.cleanup()


def test_repeat_risk_event_does_not_extend_freeze_window():
    """同一冻结期内重复触发不刷新 freeze_until（设计 §1 验收 4）。"""
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, _ = _make_scheduler(tmp_dir, freeze_seconds=60)
        scheduler.notify_risk_event()
        first_until = scheduler._freeze_until

        time.sleep(0.02)  # 模拟一小段时间过去
        scheduler.notify_risk_event()
        second_until = scheduler._freeze_until

        assert first_until == second_until, "重复触发不应推迟 freeze_until"
        # last_risk_at 仍应被刷新
    finally:
        scheduler = None
        gc.collect()
        tmp_dir.cleanup()


def test_freeze_expires_on_its_own():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, _ = _make_scheduler(tmp_dir, freeze_seconds=0)
        # freeze_seconds=0：进入后 monotonic() 立刻 >= freeze_until
        scheduler.notify_risk_event()
        # 等待一个 tick 确保过期
        time.sleep(0.01)
        assert scheduler.is_frozen() is False
        assert scheduler._compute_status_state() == "IDLE"
        assert scheduler.get_frozen_remaining_seconds() == 0.0
    finally:
        scheduler = None
        gc.collect()
        tmp_dir.cleanup()


def test_unfreeze_clears_state():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, _ = _make_scheduler(tmp_dir, freeze_seconds=300)
        scheduler.notify_risk_event()
        assert scheduler.is_frozen() is True

        was_frozen = scheduler.unfreeze(reason="test")
        assert was_frozen is True
        assert scheduler.is_frozen() is False

        # 二次解冻返回 False（已无 freeze 在身）
        assert scheduler.unfreeze() is False
    finally:
        scheduler = None
        gc.collect()
        tmp_dir.cleanup()


def test_heartbeat_reports_risk_frozen_state():
    """冻结期间 heartbeat 必须上报 status=RISK_FROZEN（覆盖 status_state）。"""
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, _ = _make_scheduler(tmp_dir, freeze_seconds=60)

        captured = []
        class _CapturingClient(MockUpstreamClient):
            def send_heartbeat(self, status, wechat_online, net_info):
                captured.append(status)
                return True
        scheduler.client = _CapturingClient()
        scheduler.status_state = "BUSY"  # 假装正在跑任务
        scheduler.notify_risk_event()

        with patch("backend.app.services.upstream_scheduler._get_weixin_pids", return_value=[]):
            scheduler._heartbeat_action()

        assert captured == ["RISK_FROZEN"]
    finally:
        scheduler = None
        gc.collect()
        tmp_dir.cleanup()


def test_worker_loop_requeues_task_during_freeze():
    """冻结期间从队列拿到的任务原样回插，不被消费。"""
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        scheduler, _ = _make_scheduler(tmp_dir, freeze_seconds=60)

        consumed = []
        class _RecordingOrchestrator:
            def add_wechat(self, **kw):
                consumed.append(kw)
                return {"job_id": "j", "status": "SUCCESS"}

        scheduler.orchestrator_factory = lambda: _RecordingOrchestrator()
        scheduler.notify_risk_event()

        scheduler._task_queue.put({
            "lead_id": "lead_frz",
            "phone": "138",
            "customer_name": "FrozenCustomer",
            "greeting": "hi",
        })

        # 让 worker_loop 跑 1 个 tick 然后退出：在另一个线程跑，0.1s 后 set stop_event
        worker_thread = threading.Thread(target=scheduler._worker_loop, daemon=True)
        worker_thread.start()
        time.sleep(0.2)  # 给 worker 一次"拿出来发现冻结 → 回插 → 等待"的机会
        scheduler._stop_event.set()
        scheduler._task_queue.put(None)  # 唤醒 _task_queue.get()
        worker_thread.join(timeout=2.0)

        # 关键断言：任务没被消费
        assert consumed == []
        # 队列里仍然有这条任务（可能还有刚才塞的 None）
        items_left = []
        try:
            while True:
                items_left.append(scheduler._task_queue.get_nowait())
        except Exception:
            pass
        lead_items = [x for x in items_left if isinstance(x, dict)]
        assert any(it.get("lead_id") == "lead_frz" for it in lead_items)
    finally:
        scheduler._stop_event.set()
        scheduler = None
        gc.collect()
        tmp_dir.cleanup()


def test_orchestrator_finalize_calls_risk_event_handler():
    """RpaOrchestrator._finalize_business_outcome 在 circuit_break=True 时
    必须调用注入的 risk_event_handler。"""
    called = []
    store = MagicMock()
    audit = MagicMock()
    settings = MagicMock()
    settings.rpa_daily_limit = 3

    orch = RpaOrchestrator(
        store, audit, settings,
        risk_event_handler=lambda code: called.append(code),
    )
    outcome = RpaBusinessOutcome("BIZ_RISK_CONTROL", "频繁", circuit_break=True)
    orch._finalize_business_outcome(
        "job_1",
        {
            "lead_id": "lead_1",
            "phone": "138",
            "sales_id": "upstream",
            "customer_consent": 1,
        },
        ["s1"],
        outcome,
    )

    assert called == ["BIZ_RISK_CONTROL"]


def test_non_circuit_break_outcome_does_not_invoke_risk_handler():
    """BIZ_ALREADY_FRIEND 等非 circuit_break 终态不触发冻结。"""
    called = []
    store = MagicMock()
    audit = MagicMock()
    settings = MagicMock()
    settings.rpa_daily_limit = 3

    orch = RpaOrchestrator(
        store, audit, settings,
        risk_event_handler=lambda code: called.append(code),
    )
    outcome = RpaBusinessOutcome("BIZ_ALREADY_FRIEND", "已是好友")
    orch._finalize_business_outcome(
        "job_1",
        {"lead_id": "lead_1", "phone": "138", "sales_id": "upstream", "customer_consent": 1},
        [],
        outcome,
    )
    assert called == []


# ============ 设计 §3 — 重试前核验 ============

class TestRetryPrecheck(unittest.TestCase):
    def _make_orchestrator(self, retry_precheck):
        store = MagicMock()
        audit = MagicMock()
        settings = MagicMock()
        settings.rpa_daily_limit = 3
        settings.rpa_task_timeout_seconds = 90
        settings.rpa_min_interval_seconds = 0
        settings.rpa_max_interval_seconds = 0
        settings.rpa_mode = "real"
        settings.rpa_retry_precheck_enabled = True

        store.get_job.return_value = {
            "job_id": "job_1",
            "lead_id": "lead_1",
            "status": "REAL_QUEUED",
            "rpa_mode": "real",
            "dry_run": False,
            "human_approval": True,
            "greeting": "hi",
            "steps": [],
        }
        store.get_lead.return_value = {
            "lead_id": "lead_1",
            "phone": "13811112222",
            "sales_id": "upstream",
            "customer_consent": 1,
        }
        rpa = RpaOrchestrator(
            store, audit, settings,
            retry_precheck=retry_precheck,
        )
        return rpa, store, audit

    def test_precheck_skipped_on_first_attempt(self):
        """attempt=0 不调用核验。"""
        precheck_calls = []
        def precheck(lead, greeting, update_step):
            precheck_calls.append(lead["lead_id"])

        rpa, store, _ = self._make_orchestrator(precheck)

        with patch.object(rpa, "_run_add_request_with_timeout"), \
             patch("backend.app.services.rpa_orchestrator.random.uniform", return_value=0), \
             patch("backend.app.services.rpa_orchestrator.time.sleep"):
            rpa._run_job("job_1")

        self.assertEqual(precheck_calls, [], "首次执行不应调用核验")

    def test_precheck_invoked_only_on_retry(self):
        """attempt=1 之前调一次。"""
        precheck_calls = []
        def precheck(lead, greeting, update_step):
            precheck_calls.append(lead["lead_id"])
            update_step("RETRY_PRECHECK_RESULT: state=UNKNOWN")

        attempt_count = {"n": 0}
        def fake_add(_phone, _g, update_step, _job_id):
            attempt_count["n"] += 1
            if attempt_count["n"] == 1:
                raise RuntimeError("first attempt boom")
            update_step("ADD_DIRECTLY_CONFIRMED: 已处理通过朋友验证")

        rpa, store, audit = self._make_orchestrator(precheck)
        with patch.object(rpa, "_run_add_request_with_timeout", side_effect=fake_add), \
             patch("backend.app.services.rpa_orchestrator.random.uniform", return_value=0), \
             patch("backend.app.services.rpa_orchestrator.time.sleep"):
            rpa._run_job("job_1")

        # 核验被调一次
        self.assertEqual(len(precheck_calls), 1)
        # 第二次最终成功，lead 转 WECHAT_ADD_REQUESTED
        lead_updates = [call.kwargs for call in store.update_lead.call_args_list]
        self.assertIn(
            {"status": LeadStatus.WECHAT_ADD_REQUESTED.value, "updated_at": unittest.mock.ANY},
            lead_updates,
        )

    def test_precheck_already_friend_short_circuits(self):
        """核验抛 BIZ_ALREADY_FRIEND 直接走业务终态收尾，**不再执行第二次** add。"""
        add_calls = []
        def fake_add(_phone, _g, update_step, _job_id):
            add_calls.append(True)
            raise RuntimeError("first attempt boom")

        def precheck(lead, greeting, update_step):
            raise RpaBusinessOutcome("BIZ_ALREADY_FRIEND", "重试前发现已是好友")

        rpa, store, audit = self._make_orchestrator(precheck)
        with patch.object(rpa, "_run_add_request_with_timeout", side_effect=fake_add), \
             patch("backend.app.services.rpa_orchestrator.random.uniform", return_value=0), \
             patch("backend.app.services.rpa_orchestrator.time.sleep"):
            rpa._run_job("job_1")

        # add 只被调了第一次（attempt 0），重试时被 precheck 拦截
        self.assertEqual(len(add_calls), 1)
        lead_updates = [call.kwargs for call in store.update_lead.call_args_list]
        self.assertIn(
            {"status": LeadStatus.WECHAT_ALREADY_FRIEND.value, "updated_at": unittest.mock.ANY},
            lead_updates,
        )

    def test_precheck_send_success_maps_to_already_requested(self):
        """核验抛 BIZ_ALREADY_REQUESTED → lead 落 WECHAT_ADD_REQUESTED，
        job.status 落 REAL_BIZ_ALREADY_REQUESTED。"""
        def fake_add(_phone, _g, update_step, _job_id):
            raise RuntimeError("first attempt boom")

        def precheck(lead, greeting, update_step):
            raise RpaBusinessOutcome("BIZ_ALREADY_REQUESTED", "申请已发出")

        rpa, store, audit = self._make_orchestrator(precheck)
        with patch.object(rpa, "_run_add_request_with_timeout", side_effect=fake_add), \
             patch("backend.app.services.rpa_orchestrator.random.uniform", return_value=0), \
             patch("backend.app.services.rpa_orchestrator.time.sleep"):
            rpa._run_job("job_1")

        job_updates = [call.kwargs for call in store.update_job.call_args_list]
        # 找包含 status=REAL_BIZ_ALREADY_REQUESTED 的那条
        assert any(u.get("status") == "REAL_BIZ_ALREADY_REQUESTED" for u in job_updates), \
            f"应当写入 REAL_BIZ_ALREADY_REQUESTED，实际 job_updates={job_updates}"

        lead_updates = [call.kwargs for call in store.update_lead.call_args_list]
        assert any(u.get("status") == LeadStatus.WECHAT_ADD_REQUESTED.value for u in lead_updates)

    def test_precheck_system_error_does_not_block_retry(self):
        """核验自身系统错误：仅写 SYS_RETRY_PRECHECK_FAILED step，重试继续。"""
        def precheck(lead, greeting, update_step):
            raise RuntimeError("WECHAT_NOT_FOUND")

        attempt_count = {"n": 0}
        def fake_add(_phone, _g, update_step, _job_id):
            attempt_count["n"] += 1
            if attempt_count["n"] == 1:
                raise RuntimeError("first attempt boom")
            update_step("ADD_DIRECTLY_CONFIRMED: 已处理通过朋友验证")

        rpa, store, audit = self._make_orchestrator(precheck)
        captured_steps = []

        def update_steps_capture(job_id, **kwargs):
            if "steps" in kwargs:
                captured_steps.append(kwargs["steps"][-1] if kwargs["steps"] else "")
            return store.get_job.return_value

        store.update_job.side_effect = update_steps_capture
        with patch.object(rpa, "_run_add_request_with_timeout", side_effect=fake_add), \
             patch("backend.app.services.rpa_orchestrator.random.uniform", return_value=0), \
             patch("backend.app.services.rpa_orchestrator.time.sleep"):
            rpa._run_job("job_1")

        assert any("SYS_RETRY_PRECHECK_FAILED" in s for s in captured_steps), \
            f"应写入 SYS_RETRY_PRECHECK_FAILED step；实际 captured={captured_steps}"
        # 第二次 add 仍然被调用
        self.assertEqual(attempt_count["n"], 2, "核验失败不应阻塞重试")


if __name__ == "__main__":
    unittest.main()
