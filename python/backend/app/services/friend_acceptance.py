from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from backend.app.core.audit import AuditLogger
from backend.app.core.errors import AppError, not_found
from backend.app.core.rate_limit import runtime_guard
from backend.app.core.security import mask_phone
from backend.app.schemas.lead import LeadStatus
from backend.app.services import wechat_rpa
from backend.app.storage.sqlite_store import SQLiteStore


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FriendAcceptanceCheckResult:
    phone: str
    accepted: bool
    state: Optional[str] = None
    matched_text: Optional[str] = None
    screenshot_path: Optional[str] = None
    steps: list[str] = field(default_factory=list)
    checked_at: str = field(default_factory=now_iso)

    def to_dict(self, lead_id: str | None = None) -> dict:
        return {
            "lead_id": lead_id,
            "phone_masked": mask_phone(self.phone),
            "accepted": self.accepted,
            "state": self.state,
            "matched_text": self.matched_text,
            "screenshot_path": self.screenshot_path,
            "steps": self.steps,
            "checked_at": self.checked_at,
        }


def check_friend_acceptance_by_phone(
    phone: str,
    *,
    job_id: str | None = None,
    cancel_token: threading.Event | None = None,
) -> FriendAcceptanceCheckResult:
    """复查一个手机号是否已经通过好友申请。

    路径与加友流程一致：打开微信添加朋友入口，搜索号码，再通过 OCR
    判断结果页是否出现“发消息/发送消息/音视频通话”等已是好友标志。
    """

    steps: list[str] = []

    def mark(step: str) -> None:
        steps.append(step)

    wechat_rpa.set_cancel_token(cancel_token)

    def _snap(tag: str) -> str | None:
        if not job_id:
            return None
        return f"backend/data/friend_acceptance_{job_id}_{tag}.png"

    wx_window = None
    target_window = None

    try:
        mark("FRIEND_ACCEPTANCE_CHECK_STARTED: 开始复查好友是否已通过")
        wx_window = wechat_rpa._find_wechat_window()
        if wx_window is None:
            raise AppError(
                "WECHAT_NOT_FOUND",
                "未发现已登录的微信客户端；请确认微信窗口可见，且不是企业微信",
            )
        mark(
            f"WECHAT_WINDOW_FOUND: 已定位微信主窗口 "
            f"Name={wx_window.name!r} ClassName={wx_window.class_name!r}"
        )

        desktop = wechat_rpa.get_desktop_adapter()
        desktop.set_active(wx_window)
        desktop.set_topmost(wx_window, True)
        wechat_rpa._sleep(0.3)

        wechat_rpa._cleanup_stale_windows(mark)
        wechat_rpa._open_add_friends_entry(None, wx_window, mark)

        target_window = wechat_rpa._current_add_friend_target(wx_window=wx_window)
        if target_window is not wx_window:
            desktop.set_active(target_window)
            desktop.set_topmost(target_window, True)
            wechat_rpa._sleep(0.3)
            mark(
                f"ADD_FRIENDS_WINDOW_FOUND: 已定位并置顶添加朋友窗口 "
                f"Name={target_window.name!r} ClassName={target_window.class_name!r}"
            )
        else:
            mark("ADD_FRIENDS_WINDOW_IN_MAIN: 添加朋友界面位于微信主窗口内")

        search_box, input_method = wechat_rpa._focus_search_box(None, target_window, mark)
        wechat_rpa._clear_and_type_target(None, search_box, input_method, phone)
        mark(f"PHONE_TYPED: 已通过 {input_method} 输入客户标识")

        wechat_rpa._press_enter(None, search_box, input_method)
        wechat_rpa._sleep(2.0)

        target_window = wechat_rpa._current_add_friend_target(wx_window=wx_window)
        state = wechat_rpa._detect_screen_state(
            target_window,
            ["RISK_CONTROL", "TARGET_NOT_FOUND", "ALREADY_FRIEND"],
            save_path=_snap("after_search"),
            mark=mark,
        )
        if state:
            mark(f"FRIEND_ACCEPTANCE_STATE: 读屏判定命中 {state}")

        matched_text = _last_ocr_text(steps)
        return FriendAcceptanceCheckResult(
            phone=phone,
            accepted=state == "ALREADY_FRIEND",
            state=state or "PENDING",
            matched_text=matched_text,
            screenshot_path=_snap("after_search"),
            steps=steps,
        )
    finally:
        try:
            desktop = wechat_rpa.get_desktop_adapter()
        except Exception:
            desktop = None
        try:
            if target_window is not None and target_window is not wx_window:
                try:
                    desktop.close_window(target_window)
                    mark("CLEANUP_ADD_FRIENDS_WINDOW_CLOSED: 已关闭遗留的添加朋友窗口")
                except Exception:
                    pass
            if wx_window is not None:
                try:
                    desktop.set_topmost(wx_window, False)
                except Exception:
                    pass
        finally:
            wechat_rpa.set_cancel_token(None)


def probe_screen_state_for_retry(
    phone: str,
    *,
    job_id: str | None = None,
    cancel_token: threading.Event | None = None,
) -> FriendAcceptanceCheckResult:
    """重试前的轻量读屏核验（Cycle 2 需求 3）。

    与 check_friend_acceptance_by_phone 的差别：
    - 多识别一个 SEND_SUCCESS 状态（设计 §3）
    - 调用方拿到 result.state 后自行决定要不要抛 RpaBusinessOutcome
    - 不写任何 DB / 不发 audit；仅完成"看一眼"
    """
    # 复用既有路径：检测序加上 SEND_SUCCESS
    state_keys = ["RISK_CONTROL", "TARGET_NOT_FOUND", "ALREADY_FRIEND", "SEND_SUCCESS"]

    steps: list[str] = []

    def mark(step: str) -> None:
        steps.append(step)

    wechat_rpa.set_cancel_token(cancel_token)
    wx_window = None
    target_window = None
    try:
        mark("RETRY_PRECHECK_STARTED: 重试前轻量核验当前对方状态")
        wx_window = wechat_rpa._find_wechat_window()
        if wx_window is None:
            raise AppError(
                "WECHAT_NOT_FOUND",
                "未发现已登录的微信客户端；请确认微信窗口可见，且不是企业微信",
            )

        desktop = wechat_rpa.get_desktop_adapter()
        desktop.set_active(wx_window)
        desktop.set_topmost(wx_window, True)
        wechat_rpa._sleep(0.3)

        wechat_rpa._cleanup_stale_windows(mark)
        wechat_rpa._open_add_friends_entry(None, wx_window, mark)

        target_window = wechat_rpa._current_add_friend_target(wx_window=wx_window)
        if target_window is not wx_window:
            desktop.set_active(target_window)
            desktop.set_topmost(target_window, True)
            wechat_rpa._sleep(0.3)

        search_box, input_method = wechat_rpa._focus_search_box(None, target_window, mark)
        wechat_rpa._clear_and_type_target(None, search_box, input_method, phone)
        wechat_rpa._press_enter(None, search_box, input_method)
        wechat_rpa._sleep(2.0)

        target_window = wechat_rpa._current_add_friend_target(wx_window=wx_window)
        state = wechat_rpa._detect_screen_state(
            target_window,
            state_keys,
            mark=mark,
        )
        if state:
            mark(f"RETRY_PRECHECK_STATE: 命中 {state}")

        matched_text = _last_ocr_text(steps)
        return FriendAcceptanceCheckResult(
            phone=phone,
            accepted=state == "ALREADY_FRIEND",
            state=state or "UNKNOWN",
            matched_text=matched_text,
            steps=steps,
        )
    finally:
        try:
            desktop = wechat_rpa.get_desktop_adapter()
        except Exception:
            desktop = None
        try:
            if target_window is not None and target_window is not wx_window:
                try:
                    desktop.close_window(target_window)
                except Exception:
                    pass
            if wx_window is not None:
                try:
                    desktop.set_topmost(wx_window, False)
                except Exception:
                    pass
        finally:
            wechat_rpa.set_cancel_token(None)


class FriendAcceptanceService:
    def __init__(
        self,
        store: SQLiteStore,
        audit: AuditLogger,
        checker: Callable[..., FriendAcceptanceCheckResult] = check_friend_acceptance_by_phone,
        *,
        max_attempts: int = 12,
        risk_event_handler: Callable[..., None] | None = None,
    ) -> None:
        self.store = store
        self.audit = audit
        self.checker = checker
        self.max_attempts = max(1, int(max_attempts))
        self.risk_event_handler = risk_event_handler

    def check_lead(self, lead_id: str) -> dict:
        lead = self.store.get_lead(lead_id)
        if not lead:
            raise not_found("线索不存在")

        if lead["status"] == LeadStatus.WECHAT_ACCEPTED.value:
            self.store.enqueue_friend_check_report(lead_id, True, now_iso())
            return {
                "lead_id": lead_id,
                "phone_masked": mask_phone(lead["phone"]),
                "accepted": True,
                "state": "ALREADY_ACCEPTED",
                "matched_text": None,
                "screenshot_path": None,
                "steps": [],
                "checked_at": now_iso(),
            }
        if lead["status"] != LeadStatus.WECHAT_ADD_REQUESTED.value:
            raise AppError(
                "FRIEND_ACCEPTANCE_NOT_PENDING",
                "只有已发送好友申请且待通过的线索可以复查",
            )

        result = self.checker(
            lead["phone"],
            job_id=f"lead_{lead_id}",
        )
        result_payload = result.to_dict(lead_id)
        timestamp = now_iso()

        if result.accepted:
            self.store.update_lead(
                lead_id,
                status=LeadStatus.WECHAT_ACCEPTED.value,
                updated_at=timestamp,
            )
            self.store.enqueue_friend_check_report(lead_id, True, timestamp)
            self.audit.record(
                "wechat.friend.accepted",
                actor_id=lead["sales_id"],
                lead_id=lead_id,
                phone_masked=mask_phone(lead["phone"]),
                rpa_mode="real",
                result="accepted",
                reason_code=result.state,
                message=result.matched_text,
                data=result_payload,
            )
        else:
            attempts = int(lead.get("acceptance_attempts") or 0) + 1
            next_status = LeadStatus.WECHAT_ADD_REQUESTED
            upstream_status: str | None = None
            if result.state == "RISK_CONTROL":
                next_status = LeadStatus.WECHAT_RISK_CONTROL
                upstream_status = "BIZ_RISK_CONTROL"
            elif result.state == "TARGET_NOT_FOUND":
                next_status = LeadStatus.WECHAT_TARGET_NOT_FOUND
                upstream_status = "BIZ_TARGET_NOT_FOUND"
            elif attempts >= self.max_attempts:
                next_status = LeadStatus.WECHAT_ACCEPTANCE_EXHAUSTED
                upstream_status = "BIZ_ACCEPTANCE_EXHAUSTED"

            self.store.update_lead(
                lead_id,
                status=next_status.value,
                acceptance_attempts=attempts,
                updated_at=timestamp,
            )
            result_payload["acceptance_attempts"] = attempts

            if upstream_status:
                self.store.enqueue_lead_status_report(
                    lead_id=lead_id,
                    job_id=f"friend_acceptance_{lead_id}",
                    upstream_status=upstream_status,
                    remark=result.matched_text,
                    error_details=None,
                    payload={
                        "lead_id": lead_id,
                        "source": "friend_acceptance",
                        "state": result.state,
                        "acceptance_attempts": attempts,
                    },
                    timestamp=timestamp,
                )
            if result.state == "RISK_CONTROL":
                self.store.enqueue_friend_check_report(lead_id, False, timestamp)
                if self.risk_event_handler:
                    self.risk_event_handler(reason="BIZ_RISK_CONTROL")

            self.audit.record(
                "wechat.friend.acceptance_checked",
                actor_id=lead["sales_id"],
                lead_id=lead_id,
                phone_masked=mask_phone(lead["phone"]),
                rpa_mode="real",
                result="terminal" if upstream_status else "pending",
                reason_code=result.state,
                message=result.matched_text,
                data=result_payload,
            )
        return result_payload

    def check_pending(self, limit: int = 10) -> dict:
        leads = self._list_pending_leads(limit)
        results = []
        for lead in leads:
            try:
                results.append(self.check_lead(lead["lead_id"]))
            except AppError as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                results.append(
                    {
                        "lead_id": lead["lead_id"],
                        "phone_masked": mask_phone(lead["phone"]),
                        "accepted": False,
                        "state": detail.get("code", "ERROR"),
                        "matched_text": detail.get("message", str(exc)),
                        "screenshot_path": None,
                        "steps": [],
                        "checked_at": now_iso(),
                    }
                )
        return {
            "checked": len(results),
            "accepted": sum(1 for item in results if item["accepted"]),
            "results": results,
        }

    def _list_pending_leads(self, limit: int) -> list[dict]:
        safe_limit = max(1, min(int(limit), 50))
        with self.store._lock, self.store._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM leads
                WHERE status = ?
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (LeadStatus.WECHAT_ADD_REQUESTED.value, safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]


class FriendAcceptanceRecheckWorker:
    def __init__(
        self,
        store: SQLiteStore,
        audit: AuditLogger,
        *,
        batch_size: int = 3,
        interval_seconds: int = 300,
        max_attempts: int = 12,
        risk_event_handler: Callable[..., None] | None = None,
        checker: Callable[..., FriendAcceptanceCheckResult] = check_friend_acceptance_by_phone,
    ) -> None:
        self.store = store
        self.audit = audit
        self.batch_size = max(1, min(int(batch_size), 10))
        self.interval_seconds = max(30, int(interval_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.risk_event_handler = risk_event_handler
        self.checker = checker

    def run_once(self) -> dict:
        try:
            with runtime_guard.single_task():
                with _com_context():
                    service = FriendAcceptanceService(
                        self.store,
                        self.audit,
                        checker=self.checker,
                        max_attempts=self.max_attempts,
                        risk_event_handler=self.risk_event_handler,
                    )
                    return service.check_pending(self.batch_size)
        except AppError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            if detail.get("code") == "RPA_BUSY":
                return {
                    "checked": 0,
                    "accepted": 0,
                    "skipped": True,
                    "reason": "RPA_BUSY",
                    "results": [],
                }
            raise

    def run_forever(self, stop_event: threading.Event) -> None:
        while not stop_event.wait(self.interval_seconds):
            try:
                self.run_once()
            except Exception as exc:
                self.audit.record(
                    "wechat.friend.acceptance_recheck_failed",
                    result="failed",
                    reason_code=exc.__class__.__name__,
                    message=str(exc),
                )


_recheck_lock = threading.Lock()
_recheck_thread: threading.Thread | None = None
_recheck_stop_event: threading.Event | None = None


def start_friend_acceptance_rechecker(
    settings,
    store: SQLiteStore,
    audit: AuditLogger,
    *,
    risk_event_handler: Callable[..., None] | None = None,
) -> bool:
    if not getattr(settings, "friend_acceptance_recheck_enabled", True):
        return False
    if getattr(settings, "rpa_mode", "simulation") != "real":
        return False

    global _recheck_thread, _recheck_stop_event
    with _recheck_lock:
        if _recheck_thread is not None and _recheck_thread.is_alive():
            return True
        _recheck_stop_event = threading.Event()
        worker = FriendAcceptanceRecheckWorker(
            store=store,
            audit=audit,
            batch_size=getattr(settings, "friend_acceptance_recheck_batch_size", 3),
            interval_seconds=getattr(settings, "friend_acceptance_recheck_interval_seconds", 300),
            max_attempts=getattr(settings, "friend_acceptance_max_attempts", 12),
            risk_event_handler=risk_event_handler,
        )
        _recheck_thread = threading.Thread(
            target=worker.run_forever,
            args=(_recheck_stop_event,),
            name="friend-acceptance-rechecker",
            daemon=True,
        )
        _recheck_thread.start()
        return True


def stop_friend_acceptance_rechecker() -> None:
    global _recheck_thread, _recheck_stop_event
    with _recheck_lock:
        if _recheck_stop_event is not None:
            _recheck_stop_event.set()
        _recheck_thread = None
        _recheck_stop_event = None


@contextmanager
def _com_context():
    com_inited = False
    try:
        try:
            import comtypes

            comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
            com_inited = True
        except Exception:
            pass
        yield
    finally:
        if com_inited:
            try:
                import comtypes

                comtypes.CoUninitialize()
            except Exception:
                pass


def _last_ocr_text(steps: list[str]) -> str | None:
    for step in reversed(steps):
        if step.startswith("OCR_RAW_TEXT: "):
            return step.removeprefix("OCR_RAW_TEXT: ").strip()
    return None
