import queue
import socket
import subprocess
import threading
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
})


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


class UpstreamScheduler:
    def __init__(self, settings: Settings, store: SQLiteStore, orchestrator_factory):
        self.settings = settings
        self.store = store
        self.orchestrator_factory = orchestrator_factory

        self.client: Optional[UpstreamClientInterface] = None
        self.lead_source: Optional[PollingLeadSource] = None
        self.status_state = "IDLE"  # IDLE, BUSY, COOLDOWN

        self._task_queue = queue.Queue()
        self._queued_lead_ids: set[str] = set()
        self._queued_lead_ids_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []

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
        )

        # 2. 启动三个后台守护线程
        t_heart = threading.Thread(target=self._heartbeat_loop, name="upstream-heartbeat", daemon=True)
        t_fetch = threading.Thread(
            target=self.lead_source.run,
            args=(self._stop_event,),
            name="upstream-fetch",
            daemon=True,
        )
        t_worker = threading.Thread(target=self._worker_loop, name="upstream-worker", daemon=True)

        self._threads = [t_heart, t_fetch, t_worker]
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
        success = self.client.send_heartbeat(self.status_state, wechat_online, net)
        if success:
            log_broadcaster.log(
                f"💓 心跳发送成功 | 状态: {self.status_state} | "
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

    def _worker_loop(self):
        while not self._stop_event.is_set():
            item = self._task_queue.get()
            if item is None:  # Stop signal
                break

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

                        # 检查执行结果
                        status = job["status"]
                        if status == "FAILED":
                            err_msg = job.get("error_message") or "RPA 物理超时或取消"
                            log_broadcaster.log(f"❌ RPA 失败: {err_msg}")
                            self.client.report_lead_status(lead_id, "BIZ_FAILED", f"{phone}={customer_name}", err_msg)
                        else:
                            # SIMULATION_COMPLETED / REAL_COMPLETED / REAL_BIZ_* 等均视为已发出
                            log_broadcaster.log(f"✅ RPA 执行完毕: {status}")
                            self.client.report_lead_status(lead_id, "REAL_SENT", f"{phone}={customer_name}", None)
            except Exception as e:
                log_broadcaster.log(f"💥 RPA 任务队列执行抛出严重异常: {e}")
                if self.client:
                    self.client.report_lead_status(lead_id, "BIZ_FAILED", f"{phone}={customer_name}", str(e))

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
