import queue
import socket
import subprocess
import threading
import time
import random
from typing import List, Optional
from datetime import datetime, timezone

from backend.app.core.config import Settings
from backend.app.schemas.lead import LeadStatus
from backend.app.storage.sqlite_store import SQLiteStore
from backend.app.services.upstream_client import (
    UpstreamClientInterface,
    MockUpstreamClient,
    RealUpstreamClient,
)
from backend.app.services.upstream_lead_source import PollingLeadSource


TERMINAL_LEAD_STATUSES = frozenset({
    LeadStatus.WECHAT_ACCEPTED.value,
    LeadStatus.WECHAT_ALREADY_FRIEND.value,
    LeadStatus.WECHAT_TARGET_NOT_FOUND.value,
    LeadStatus.WECHAT_RISK_CONTROL.value,
    LeadStatus.WECHAT_ADD_REJECTED.value,
    LeadStatus.WECHAT_ACCEPTANCE_EXHAUSTED.value,
})

JOB_STATUS_UPSTREAM_STATUS = {
    "REAL_COMPLETED": "REAL_SENT",
    "SIMULATION_COMPLETED": "REAL_SENT",
    "REAL_BIZ_ALREADY_FRIEND": "BIZ_ALREADY_FRIEND",
    "REAL_BIZ_TARGET_NOT_FOUND": "BIZ_TARGET_NOT_FOUND",
    "REAL_BIZ_RISK_CONTROL": "BIZ_RISK_CONTROL",
    "REAL_BIZ_ADD_REJECTED": "BIZ_ADD_REJECTED",
    # 重试前核验命中"申请已发送"：当作一次成功发送上报。
    "REAL_BIZ_ALREADY_REQUESTED": "REAL_SENT",
}


def _get_weixin_pids() -> list:
    """检测 WeChat.exe / Weixin.exe 主进程 PID 列表"""
    pids = []
    for image_name in ("WeChat.exe", "Weixin.exe"):
        try:
            result = subprocess.run(
                ['tasklist', '/FI', f'IMAGENAME eq {image_name}', '/FO', 'CSV', '/NH'],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.strip().split('\n'):
                if image_name in line:
                    parts = line.split(',')
                    if len(parts) >= 2:
                        try:
                            pids.append(int(parts[1].strip('"')))
                        except ValueError:
                            pass
        except Exception:
            continue
    return pids


class LogBroadcaster:
    """线程安全的全局日志广播器，供 SSE 监听"""

    def __init__(self):
        self._listeners = []
        self._lock = threading.Lock()

    def add_listener(self, q: queue.Queue):
        with self._lock:
            self._listeners.append(q)

    def remove_listener(self, q: queue.Queue):
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def log(self, text: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {text}"
        with self._lock:
            for q in self._listeners:
                q.put(formatted)


log_broadcaster = LogBroadcaster()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UpstreamScheduler:
    def __init__(self, settings: Settings, store: SQLiteStore, orchestrator_factory):
        self.settings = settings
        self.store = store
        self.orchestrator_factory = orchestrator_factory

        self.client: Optional[UpstreamClientInterface] = None
        self.lead_source: Optional[PollingLeadSource] = None
        # 调度器对外暴露的状态：IDLE / BUSY / COOLDOWN / RISK_FROZEN。
        # RISK_FROZEN 与其他三态是"维度叠加"——只要 _freeze_until > monotonic()，
        # 心跳上报和 status 接口都报告 RISK_FROZEN，覆盖 status_state 的原值。
        self.status_state = "IDLE"

        self._task_queue = queue.Queue()
        self._queued_lead_ids: set[str] = set()
        self._queued_lead_ids_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []

        # RISK_FROZEN 内存态。进程重启即失效，由 daily_counters 持久化兜底（设计 §1 风险表）。
        self._freeze_lock = threading.RLock()
        self._freeze_until: float | None = None
        # 最近一次进入冻结的时间戳，用于审计。
        self._last_risk_at: str | None = None

    def start(self):
        if self._threads:
            return

        self._stop_event.clear()

        # 1. 读取 SQLite 配置初始化客户端
        cfg = self.store.get_upstream_config()
        mode = cfg.get("upstream_mode", self.settings.upstream_mode)
        api_url = cfg.get("upstream_api_url", self.settings.upstream_api_url)
        client_id = cfg.get("client_id", self.settings.client_id)
        client_secret = cfg.get("client_secret", self.settings.client_secret)

        if mode == "real":
            self.client = RealUpstreamClient(api_url, client_id, client_secret)
        else:
            self.client = MockUpstreamClient()

        log_broadcaster.log(f"上游调度器已启动。当前模式: {mode.upper()}")

        self.lead_source = PollingLeadSource(
            client=self.client,
            enqueue_lead=self.enqueue_remote_lead,
            interval_seconds=float(self.settings.upstream_fetch_interval_seconds),
            log=log_broadcaster.log,
            is_frozen=self.is_frozen,
        )

        # 2. 启动后台守护线程
        t_heart = threading.Thread(target=self._heartbeat_loop, name="upstream-heartbeat", daemon=True)
        t_fetch = threading.Thread(
            target=self.lead_source.run,
            args=(self._stop_event,),
            name="upstream-fetch",
            daemon=True,
        )
        t_worker = threading.Thread(target=self._worker_loop, name="upstream-worker", daemon=True)
        t_friend_report = threading.Thread(
            target=self._friend_check_report_loop,
            name="upstream-friend-check-report",
            daemon=True,
        )
        t_lead_status_report = threading.Thread(
            target=self._lead_status_report_loop,
            name="upstream-lead-status-report",
            daemon=True,
        )

        self._threads = [t_heart, t_fetch, t_worker, t_friend_report, t_lead_status_report]
        for t in self._threads:
            t.start()

    def stop(self):
        self._stop_event.set()
        self._task_queue.put(None)  # 解锁阻塞的工作线程
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads = []
        log_broadcaster.log("上游调度器已停止")

    def is_alive(self) -> bool:
        return len(self._threads) > 0

    # ---------- RISK_FROZEN 状态机 ----------

    def is_frozen(self) -> bool:
        with self._freeze_lock:
            if self._freeze_until is None:
                return False
            if time.monotonic() >= self._freeze_until:
                # 到期自动解冻，下一次读取 status_state 就会回到 IDLE/BUSY/COOLDOWN
                self._freeze_until = None
                return False
            return True

    def get_frozen_remaining_seconds(self) -> float:
        """返回剩余冻结秒数；非冻结状态返回 0。"""
        with self._freeze_lock:
            if self._freeze_until is None:
                return 0.0
            remaining = self._freeze_until - time.monotonic()
            return max(0.0, remaining)

    def _compute_status_state(self) -> str:
        """对外暴露的状态值。RISK_FROZEN 覆盖 IDLE/BUSY/COOLDOWN。"""
        if self.is_frozen():
            return "RISK_FROZEN"
        return self.status_state

    def notify_risk_event(self, *, reason: str = "BIZ_RISK_CONTROL") -> None:
        """由 RpaOrchestrator._finalize_business_outcome 注入：风控终态触发冻结。
        同一冻结周期内重复调用**不延长** freeze_until（设计 §1 验收 4），仅刷新 last_risk_at。"""
        freeze_seconds = float(getattr(self.settings, "risk_freeze_seconds", 7200))
        with self._freeze_lock:
            already_frozen = self._freeze_until is not None and time.monotonic() < self._freeze_until
            now_mono = time.monotonic()
            if not already_frozen:
                self._freeze_until = now_mono + freeze_seconds
            self._last_risk_at = now_iso()
        log_broadcaster.log(
            f"🛡️ 风控终态触发调度器冻结：reason={reason} "
            f"freeze_seconds={freeze_seconds:.0f} "
            f"{'（已在冻结中，不延长）' if already_frozen else '（开始计时）'}"
        )

    def unfreeze(self, *, reason: str = "manual") -> bool:
        """提前解冻（dev API）。返回是否真的解冻了。"""
        with self._freeze_lock:
            was_frozen = self._freeze_until is not None and time.monotonic() < self._freeze_until
            self._freeze_until = None
        if was_frozen:
            log_broadcaster.log(f"🔓 调度器手动解冻：reason={reason}")
        return was_frozen

    def enqueue_remote_lead(self, item: dict) -> bool:
        required_fields = ("lead_id", "phone", "customer_name", "greeting")
        missing = [field for field in required_fields if not item.get(field)]
        if missing:
            log_broadcaster.log(f"⚠️ 远程线索缺少必要字段，已跳过: {', '.join(missing)}")
            return False

        lead_id = item["lead_id"]
        phone = item["phone"]
        customer_name = item["customer_name"]

        # 拉取线程与前端手动触发可能并发进入；先抢占去重位再做持久化/入队，
        # 避免多个线程同时通过 `in` 检查后重复 `create_lead` 触发 UNIQUE 冲突。
        with self._queued_lead_ids_lock:
            if lead_id in self._queued_lead_ids:
                log_broadcaster.log(f"线索 {lead_id} 已在本地等待队列中，跳过重复入队")
                return False
            self._queued_lead_ids.add(lead_id)

        try:
            existing = self.store.get_lead(lead_id)
            if existing and existing.get("status") in TERMINAL_LEAD_STATUSES:
                log_broadcaster.log(
                    f"线索 {lead_id} 已是终态 {existing['status']}，跳过入队"
                )
                with self._queued_lead_ids_lock:
                    self._queued_lead_ids.discard(lead_id)
                return False

            if not existing:
                timestamp = datetime.now(timezone.utc).isoformat()
                self.store.create_lead({
                    "lead_id": lead_id,
                    "customer_name": customer_name,
                    "company": "Upstream",
                    "phone": phone,
                    "sales_id": "upstream",
                    "status": LeadStatus.RPA_PENDING_APPROVAL.value,
                    "customer_consent": 1,
                    "sales_confirmed_call": 1,
                    "consent_evidence": "upstream",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                })
                log_broadcaster.log(f"线索 {customer_name} ({phone}) 已写入本地数据库")
            else:
                log_broadcaster.log(f"线索 {lead_id} 已存在本地数据库，跳过重复写入")

            self._task_queue.put(item)
            log_broadcaster.log(f"线索 {customer_name} ({phone}) 已推入本地等待消费队列")
            return True
        except Exception:
            # 任一持久化/入队步骤失败，回滚去重位，允许后续重试。
            with self._queued_lead_ids_lock:
                self._queued_lead_ids.discard(lead_id)
            raise

    def trigger_fetch_now(self):
        log_broadcaster.log("收到前端手动命令：强制立刻执行拉取")
        if self.lead_source:
            self.lead_source.fetch_once()

    def trigger_heartbeat_now(self):
        log_broadcaster.log("收到前端手动命令：强制立刻发送保活心跳")
        self._heartbeat_action()

    def trigger_friend_check_report_now(self) -> dict:
        log_broadcaster.log("收到前端手动命令：立刻上报好友对账结果")
        return self._report_friend_checks_once()

    def trigger_lead_status_report_now(self) -> dict:
        log_broadcaster.log("收到前端手动命令：立刻上报加微结果 outbox")
        return self._report_lead_status_once()

    def clear_queue(self):
        while not self._task_queue.empty():
            try:
                self._task_queue.get_nowait()
            except queue.Empty:
                break
        with self._queued_lead_ids_lock:
            self._queued_lead_ids.clear()
        log_broadcaster.log("本地等待队列已清空")

    def _get_network_info(self) -> dict:
        hostname = socket.gethostname()
        ip = "127.0.0.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass
        return {
            "hostname": hostname,
            "ip": ip,
            "mac": "00:11:22:33:44:55",  # Mock MAC
        }

    def _heartbeat_action(self):
        if not self.client:
            return
        # 登录校验
        if getattr(self.client, 'token', None) is None:
            self.client.login()

        wechat_online = len(_get_weixin_pids()) > 0
        net = self._get_network_info()
        reported_state = self._compute_status_state()
        success = self.client.send_heartbeat(reported_state, wechat_online, net)
        if success:
            log_broadcaster.log(
                f"💓 心跳发送成功 | 状态: {reported_state} | "
                f"微信: {'在线' if wechat_online else '离线'}"
            )
        else:
            log_broadcaster.log("⚠️ 心跳发送失败，请检查上游网络")

    def _heartbeat_loop(self):
        while not self._stop_event.is_set():
            try:
                self._heartbeat_action()
            except Exception as e:
                log_broadcaster.log(f"心跳循环异常: {e}")
            self._stop_event.wait(float(self.settings.upstream_heartbeat_interval_seconds))

    def _friend_check_report_loop(self):
        interval = float(getattr(self.settings, "friend_check_report_interval_seconds", 60))
        while not self._stop_event.wait(interval):
            try:
                self._report_friend_checks_once()
            except Exception as e:
                log_broadcaster.log(f"好友对账上报异常: {e}")

    def _enqueue_lead_status_report(
        self,
        *,
        lead_id: str,
        job_id: str,
        upstream_status: str,
        remark: str | None,
        error_details: str | None,
    ) -> None:
        """统一封装：把 RPA job 终态写入 lead_status_reports outbox。
        守护线程 _lead_status_report_loop 会异步 flush，失败自动重试。"""
        payload = {
            "lead_id": lead_id,
            "status": upstream_status,
            "remark": remark,
            "error_details": error_details,
        }
        try:
            self.store.enqueue_lead_status_report(
                lead_id=lead_id,
                job_id=job_id,
                upstream_status=upstream_status,
                remark=remark,
                error_details=error_details,
                payload=payload,
                timestamp=now_iso(),
            )
        except Exception as exc:
            # outbox 入队都失败说明 SQLite 本身出问题：仅 log，不阻塞 worker 流程
            log_broadcaster.log(f"⚠️ lead_status_reports 入队失败: {lead_id}/{job_id} -> {exc}")

    def _lead_status_report_loop(self):
        interval = float(getattr(self.settings, "lead_status_report_interval_seconds", 30))
        while not self._stop_event.wait(interval):
            try:
                self._report_lead_status_once()
            except Exception as e:
                log_broadcaster.log(f"加微结果上报异常: {e}")

    def _report_lead_status_once(self) -> dict:
        """异步消费 lead_status_reports outbox：拉取 PENDING 批量上报，成功 → SENT，
        失败 attempts+1；超过 max_attempts → FAILED 留作人工排查。"""
        if not self.client:
            return {"reported": 0, "failed": 0, "results": []}

        batch_size = int(getattr(self.settings, "lead_status_report_batch_size", 20))
        max_attempts = int(getattr(self.settings, "lead_status_report_max_attempts", 8))
        reports = self.store.list_pending_lead_status_reports(batch_size)
        results = []
        reported = 0
        failed = 0
        for report in reports:
            lead_id = report["lead_id"]
            job_id = report["job_id"]
            upstream_status = report["upstream_status"]
            remark = report.get("remark")
            error_details = report.get("error_details")
            try:
                ok = self.client.report_lead_status(lead_id, upstream_status, remark, error_details)
                if not ok:
                    raise RuntimeError("upstream rejected lead-status report")
                updated = self.store.mark_lead_status_report_sent(lead_id, job_id, now_iso())
                reported += 1
                results.append(updated)
                log_broadcaster.log(f"✅ 加微结果已上报: {lead_id}/{job_id} -> {upstream_status}")
            except Exception as exc:
                failed += 1
                updated = self.store.mark_lead_status_report_failed(
                    lead_id, job_id, str(exc), now_iso(), max_attempts=max_attempts,
                )
                results.append(updated)
                if updated.get("status") == "FAILED":
                    log_broadcaster.log(
                        f"❌ 加微结果已超出重试上限 {max_attempts} 次，标记为 FAILED: {lead_id}/{job_id}"
                    )
                else:
                    log_broadcaster.log(
                        f"⚠️ 加微结果上报失败 (attempts={updated.get('attempts')}): {lead_id}/{job_id} -> {exc}"
                    )
        return {"reported": reported, "failed": failed, "results": results}

    def _report_friend_checks_once(self) -> dict:
        if not self.client:
            return {"reported": 0, "failed": 0, "results": []}

        batch_size = int(getattr(self.settings, "friend_check_report_batch_size", 10))
        reports = self.store.list_pending_friend_check_reports(batch_size)
        results = []
        reported = 0
        failed = 0
        for report in reports:
            lead_id = report["lead_id"]
            is_friend = bool(report["is_friend"])
            try:
                ok = self.client.report_friend_check(lead_id, is_friend)
                if not ok:
                    raise RuntimeError("upstream rejected friend-check report")
                updated = self.store.mark_friend_check_report_sent(lead_id, now_iso())
                reported += 1
                results.append(updated)
                log_broadcaster.log(f"✅ 好友对账已上报: {lead_id} -> is_friend={is_friend}")
            except Exception as exc:
                failed += 1
                updated = self.store.mark_friend_check_report_failed(lead_id, str(exc), now_iso())
                results.append(updated)
                log_broadcaster.log(f"❌ 好友对账上报失败: {lead_id} -> {exc}")
        return {"reported": reported, "failed": failed, "results": results}

    @staticmethod
    def _upstream_result_for_job(job: dict) -> tuple[str, Optional[str]]:
        status = job.get("status")
        if status == "FAILED":
            return "BIZ_FAILED", job.get("error_message") or "RPA 物理超时或取消"
        if status in JOB_STATUS_UPSTREAM_STATUS:
            return JOB_STATUS_UPSTREAM_STATUS[status], job.get("error_message")
        if isinstance(status, str) and status.startswith("REAL_BIZ_"):
            return job.get("error_code") or status.removeprefix("REAL_"), job.get("error_message")
        return "REAL_SENT", None

    def _worker_loop(self):
        while not self._stop_event.is_set():
            item = self._task_queue.get()
            if item is None:  # Stop signal
                break

            # RISK_FROZEN 期间不消费队列：任务原样回插队尾，等冻结到期再轮到它。
            # 这里用 _stop_event.wait 而不是 time.sleep，保证 stop() 能立刻唤醒退出。
            if self.is_frozen():
                self._task_queue.put(item)
                remaining = self.get_frozen_remaining_seconds()
                wait_for = min(30.0, max(1.0, remaining))
                log_broadcaster.log(
                    f"⏸ 调度器 RISK_FROZEN 中（剩余 {remaining:.0f}s），"
                    f"任务 {item.get('lead_id')} 回插队尾，等待 {wait_for:.0f}s"
                )
                if self._stop_event.wait(wait_for):
                    break
                continue

            self.status_state = "BUSY"
            lead_id = item["lead_id"]
            phone = item["phone"]
            customer_name = item["customer_name"]
            greeting = item["greeting"]

            log_broadcaster.log(f"🚀 [队列开始] 正在执行加友 RPA: {customer_name} ({phone})")

            try:
                # 获取最新的 Orchestrator 实例
                orch = self.orchestrator_factory()

                # 执行 RPA
                res = orch.add_wechat(
                    lead_id=lead_id,
                    greeting=greeting,
                    dry_run=self.settings.rpa_mode == "simulation",
                    human_approval=False,
                )

                # 等待 Job 运行完毕
                job_id = res["job_id"]
                job_finished = False
                while not job_finished and not self._stop_event.is_set():
                    if self._stop_event.wait(2.0):
                        break
                    job = self.store.get_job(job_id)
                    running_states = (
                        "REAL_QUEUED", "REAL_RUNNING",
                        "SIMULATION_QUEUED", "SIMULATION_RUNNING",
                    )
                    if job and job["status"] not in running_states:
                        job_finished = True
                        upstream_status, error_details = self._upstream_result_for_job(job)
                        log_broadcaster.log(
                            f"RPA 执行完毕: {job['status']} -> 上游状态 {upstream_status}"
                        )
                        # 不再同步 client.report_lead_status：写入 outbox 由
                        # _lead_status_report_loop 异步重试，避免短暂网络抖动丢上报。
                        self._enqueue_lead_status_report(
                            lead_id=lead_id,
                            job_id=job_id,
                            upstream_status=upstream_status,
                            remark=f"{phone}={customer_name}",
                            error_details=error_details,
                        )
                        break
            except Exception as e:
                log_broadcaster.log(f"💥 RPA 任务队列执行抛出严重异常: {e}")
                # orchestrator 没起 job_id 时，用 lead_id 作 job_id 占位，保证 (lead_id, job_id) 唯一
                placeholder_job_id = locals().get('job_id') or f'orch_error_{lead_id}'
                self._enqueue_lead_status_report(
                    lead_id=lead_id,
                    job_id=placeholder_job_id,
                    upstream_status="BIZ_FAILED",
                    remark=f"{phone}={customer_name}",
                    error_details=str(e),
                )

            # 执行完成后冷却
            self.status_state = "COOLDOWN"
            cooldown_time = random.randint(
                self.settings.rpa_min_interval_seconds,
                self.settings.rpa_max_interval_seconds,
            )
            log_broadcaster.log(f"💤 任务完成，进入防风控休眠 {cooldown_time} 秒...")
            self._stop_event.wait(float(cooldown_time))

            self.status_state = "IDLE"
            with self._queued_lead_ids_lock:
                self._queued_lead_ids.discard(lead_id)
            self._task_queue.task_done()
