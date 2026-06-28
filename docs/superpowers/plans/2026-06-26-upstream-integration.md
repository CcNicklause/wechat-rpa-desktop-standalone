# 上游 API 对接与自动循环调度实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个后台常驻的心跳保活与串行消费线索队列，并通过前端 UI 调试面板提供完美的 Mock 与 Real 模式切换及日志观察。

**Architecture:** 
1. 采用混合托管模式：后端 Python 维护心跳与线索拉取的独立线程，维护一个串行 RPA 消费队列防界面抢占。
2. 前后端通信通过 FastAPI 的 REST API 和 SSE 实时推送日志，前端 Zustand 状态机接管界面配置及日志渲染。

**Tech Stack:** Python (FastAPI, Threading, SQLite), React (Zustand, Tailwind CSS, Lucide Icons)

## Global Constraints
* 微信 RPA 运行时具备前台独占性，加好友任务在真机下必须严格串行消费，且每次完成后根据风控策略强制 Cooldown。
* 当系统无 SQLite Key 权限时，退回到根据 UI RPA 判定反馈汇报结果（不查本地库）。

---

### Task 1: 扩充配置与本地 SQLite 持久化

**Files:**
* Modify: `python/backend/app/core/config.py`
* Modify: `python/backend/app/storage/sqlite_store.py`
* Create: `python/backend/app/tests/test_upstream_storage.py`

**Interfaces:**
* Produces: `SQLiteStore.save_upstream_config(config: dict)` 和 `SQLiteStore.get_upstream_config() -> dict`

- [ ] **Step 1: 在 `config.py` 中新增上游对接所需的默认环境变量声明**
```python
# 插入在 Settings 类中
upstream_mode: Literal['mock', 'real'] = 'mock'
upstream_api_url: str = 'http://localhost:8000/api/v1/upstream'
client_id: str = 'client-001'
client_secret: str = 'secret-xyz123'
upstream_heartbeat_interval_seconds: int = 30
upstream_fetch_interval_seconds: int = 60
```

- [ ] **Step 2: 修改 `sqlite_store.py` 的 `init_db` 创建配置存储表**
```python
# sqlite_store.py:20 附近
conn.executescript(
    """
    CREATE TABLE IF NOT EXISTS upstream_config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """
)
```
新增如下配套读写方法：
```python
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
```

- [ ] **Step 3: 编写对应的测试文件验证配置落盘**
新建 `python/backend/app/tests/test_upstream_storage.py`:
```python
import tempfile
import os
from backend.app.storage.sqlite_store import SQLiteStore

def test_save_and_get_config():
    db_fd, db_path = tempfile.mkstemp()
    try:
        store = SQLiteStore(db_path)
        test_cfg = {"upstream_mode": "mock", "client_id": "test_c"}
        store.save_upstream_config(test_cfg)
        loaded = store.get_upstream_config()
        assert loaded["upstream_mode"] == "mock"
        assert loaded["client_id"] == "test_c"
    finally:
        os.close(db_fd)
        os.unlink(db_path)
```

- [ ] **Step 4: 运行测试验证**
Run: `uv run pytest python/backend/app/tests/test_upstream_storage.py -v`
Expected: PASS

- [ ] **Step 5: 提交 Task 1**
```bash
git add python/backend/app/core/config.py python/backend/app/storage/sqlite_store.py python/backend/app/tests/test_upstream_storage.py
git commit -m "feat(upstream): 扩充配置及 SQLite 配置读写存储"
```

---

### Task 2: 实现 UpstreamClient (Mock/Real 双路网络交互)

**Files:**
* Create: `python/backend/app/services/upstream_client.py`
* Create: `python/backend/app/tests/test_upstream_client.py`

**Interfaces:**
* Produces: `UpstreamClientInterface` 及其实现类 `MockUpstreamClient` 与 `RealUpstreamClient`。

- [ ] **Step 1: 新建 `upstream_client.py` 写入客户端定义与 Mock 机制**
```python
import abc
import time
import httpx
from typing import List, Dict, Any, Optional

class UpstreamClientInterface(abc.ABC):
    @abc.abstractmethod
    def login(self) -> bool: pass
    @abc.abstractmethod
    def send_heartbeat(self, status: str, wechat_online: bool, net_info: dict) -> bool: pass
    @abc.abstractmethod
    def fetch_leads(self) -> List[Dict[str, Any]]: pass
    @abc.abstractmethod
    def report_lead_status(self, lead_id: str, status: str, remark: Optional[str], error_details: Optional[str]) -> bool: pass
    @abc.abstractmethod
    def report_friend_check(self, lead_id: str, is_friend: bool) -> bool: pass

class MockUpstreamClient(UpstreamClientInterface):
    def __init__(self):
        self.token = None
        self._fetched = False

    def login(self) -> bool:
        self.token = "mock-bearer-token-123456"
        return True

    def send_heartbeat(self, status: str, wechat_online: bool, net_info: dict) -> bool:
        print(f"[Mock Upstream] 心跳成功: status={status}, wechat_online={wechat_online}")
        return True

    def fetch_leads(self) -> List[Dict[str, Any]]:
        # 仅下发一次，防止重复无休止添加
        if self._fetched:
            return []
        self._fetched = True
        return [
            {
                "lead_id": "mock_lead_1",
                "phone": "13800000001",
                "customer_name": "莫克测试1",
                "greeting": "测试上游线索，请求通过。"
            }
        ]

    def report_lead_status(self, lead_id: str, status: str, remark: Optional[str], error_details: Optional[str]) -> bool:
        print(f"[Mock Upstream] 结果上报: {lead_id} -> {status}, remark={remark}")
        return True

    def report_friend_check(self, lead_id: str, is_friend: bool) -> bool:
        print(f"[Mock Upstream] 好友对账反馈: {lead_id} -> is_friend={is_friend}")
        return True

class RealUpstreamClient(UpstreamClientInterface):
    def __init__(self, api_url: str, client_id: str, client_secret: str):
        self.api_url = api_url.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.token: Optional[str] = None

    def login(self) -> bool:
        try:
            r = httpx.post(f"{self.api_url}/login", json={
                "client_id": self.client_id,
                "client_secret": self.client_secret
            }, timeout=10.0)
            if r.status_code == 200:
                self.token = r.json().get("access_token")
                return True
        except Exception as e:
            print(f"[Real Upstream] Login error: {e}")
        return False

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def send_heartbeat(self, status: str, wechat_online: bool, net_info: dict) -> bool:
        try:
            payload = {
                "client_id": self.client_id,
                "status": status,
                "wechat_online": wechat_online,
                **net_info
            }
            r = httpx.post(f"{self.api_url}/heartbeat", json=payload, headers=self._headers(), timeout=10.0)
            return r.status_code == 200
        except Exception:
            return False

    def fetch_leads(self) -> List[Dict[str, Any]]:
        try:
            r = httpx.get(f"{self.api_url}/leads/pending", headers=self._headers(), timeout=10.0)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return []

    def report_lead_status(self, lead_id: str, status: str, remark: Optional[str], error_details: Optional[str]) -> bool:
        try:
            payload = {
                "lead_id": lead_id,
                "status": status,
                "remark": remark,
                "error_details": error_details
            }
            r = httpx.post(f"{self.api_url}/leads/report", json=payload, headers=self._headers(), timeout=10.0)
            return r.status_code == 200
        except Exception:
            return False

    def report_friend_check(self, lead_id: str, is_friend: bool) -> bool:
        try:
            payload = {"lead_id": lead_id, "is_friend": is_friend}
            r = httpx.post(f"{self.api_url}/leads/friend-check", json=payload, headers=self._headers(), timeout=10.0)
            return r.status_code == 200
        except Exception:
            return False
```

- [ ] **Step 2: 编写测试确认 Mock 客户端行为正确**
创建 `python/backend/app/tests/test_upstream_client.py`:
```python
from backend.app.services.upstream_client import MockUpstreamClient

def test_mock_client_behavior():
    client = MockUpstreamClient()
    assert client.login() is True
    assert client.send_heartbeat("IDLE", True, {}) is True
    leads = client.fetch_leads()
    assert len(leads) == 1
    assert leads[0]["phone"] == "13800000001"
    # 第二次应该为空
    assert len(client.fetch_leads()) == 0
```

- [ ] **Step 3: 运行测试**
Run: `uv run pytest python/backend/app/tests/test_upstream_client.py -v`
Expected: PASS

- [ ] **Step 4: 提交 Task 2**
```bash
git add python/backend/app/services/upstream_client.py python/backend/app/tests/test_upstream_client.py
git commit -m "feat(upstream): 实现 Mock/Real 客户端及测试用例"
```

---

### Task 3: 编写常驻多线程调度器 (UpstreamScheduler)

这是本模块的最核心后盾。我们需要在 Python 中建立两个守护循环线程，并提供一个安全的串行队列和 SSE 日志源。

**Files:**
* Create: `python/backend/app/services/upstream_scheduler.py`
* Create: `python/backend/app/tests/test_upstream_scheduler.py`

**Interfaces:**
* Consumes: `UpstreamClientInterface`, `SQLiteStore`, `RpaOrchestrator`
* Produces: `UpstreamScheduler` 及全局单例。

- [ ] **Step 1: 新建 `upstream_scheduler.py` 实现线程心跳、串行消费与日志收集**
```python
import queue
import socket
import uuid
import uuid as uuid_mod
import threading
import time
import random
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from backend.app.core.config import Settings
from backend.app.storage.sqlite_store import SQLiteStore
from backend.app.services.upstream_client import UpstreamClientInterface, MockUpstreamClient, RealUpstreamClient
from backend.app.services.wechat_key_extractor import get_weixin_pids

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
        self.status_state = "IDLE"  # IDLE, BUSY, COOLDOWN
        
        self._task_queue = queue.Queue()
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
        
        # 2. 启动三个后台守护线程
        t_heart = threading.Thread(target=self._heartbeat_loop, name="upstream-heartbeat", daemon=True)
        t_fetch = threading.Thread(target=self._fetch_loop, name="upstream-fetch", daemon=True)
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

    def trigger_fetch_now(self):
        log_broadcaster.log("收到前端手动命令：强制立刻执行拉取")
        self._fetch_action()

    def trigger_heartbeat_now(self):
        log_broadcaster.log("收到前端手动命令：强制立刻发送保活心跳")
        self._heartbeat_action()

    def clear_queue(self):
        while not self._task_queue.empty():
            try:
                self._task_queue.get_nowait()
            except queue.Empty:
                break
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
            "mac": "00:11:22:33:44:55"  # Mock MAC
        }

    def _heartbeat_action(self):
        if not self.client:
            return
        # 登录校验
        if getattr(self.client, 'token', None) is None:
            self.client.login()
            
        wechat_online = len(get_weixin_pids()) > 0
        net = self._get_network_info()
        success = self.client.send_heartbeat(self.status_state, wechat_online, net)
        if success:
            log_broadcaster.log(f"💓 心跳发送成功 | 状态: {self.status_state} | 微信: {'在线' if wechat_online else '离线'}")
        else:
            log_broadcaster.log("⚠️ 心跳发送失败，请检查上游网络")

    def _heartbeat_loop(self):
        while not self._stop_event.is_set():
            try:
                self._heartbeat_action()
            except Exception as e:
                log_broadcaster.log(f"心跳循环异常: {e}")
            self._stop_event.wait(float(self.settings.upstream_heartbeat_interval_seconds))

    def _fetch_action(self):
        if not self.client or self.status_state != "IDLE":
            return
        log_broadcaster.log("正在尝试拉取待添加线索...")
        leads = self.client.fetch_leads()
        if not leads:
            log_broadcaster.log("暂无待加微线索")
            return
        
        log_broadcaster.log(f"📥 成功拉取到 {len(leads)} 个线索")
        for item in leads:
            # 1. 写入本地 SQLite leads 表
            lead_id = item["lead_id"]
            phone = item["phone"]
            customer_name = item["customer_name"]
            
            # 兼容去重写入
            existing = self.store.get_lead(lead_id)
            if not existing:
                self.store.create_lead({
                    "lead_id": lead_id,
                    "customer_name": customer_name,
                    "company": "Upstream",
                    "phone": phone,
                    "sales_id": "upstream",
                    "status": "RPA_QUEUED",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
            
            # 2. 推入线程队列
            self._task_queue.put(item)
            log_broadcaster.log(f"线索 {customer_name} ({phone}) 已推入本地等待消费队列")

    def _fetch_loop(self):
        while not self._stop_event.is_set():
            try:
                self._fetch_action()
            except Exception as e:
                log_broadcaster.log(f"拉取循环异常: {e}")
            self._stop_event.wait(float(self.settings.upstream_fetch_interval_seconds))

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
                # 自动计算备注
                remark = f"{phone}={customer_name}"
                
                # 执行 RPA (dry_run由系统Settings控制或假定真机real)
                res = orch.add_wechat(
                    lead_id=lead_id,
                    greeting=greeting,
                    remark=remark,
                    dry_run=self.settings.rpa_mode == "simulation",
                    human_approval=False
                )
                
                # 等待 Job 运行完毕
                job_id = res["job_id"]
                job_finished = False
                while not job_finished and not self._stop_event.is_set():
                    time.sleep(2.0)
                    job = self.store.get_job(job_id)
                    if job and job["status"] not in ("REAL_QUEUED", "REAL_RUNNING", "SIMULATION_QUEUED", "SIMULATION_RUNNING"):
                        job_finished = True
                        
                        # 检查执行结果
                        if job["status"] == "SUCCESS":
                            log_broadcaster.log(f"✅ RPA 执行完毕: 申请已成功发出")
                            self.client.report_lead_status(lead_id, "REAL_SENT", remark, None)
                        elif job["status"] == "FAILED":
                            err_msg = job.get("error_message") or "RPA 物理超时或取消"
                            log_broadcaster.log(f"❌ RPA 失败: {err_msg}")
                            self.client.report_lead_status(lead_id, "BIZ_FAILED", remark, err_msg)
            except Exception as e:
                log_broadcaster.log(f"💥 RPA 任务队列执行抛出严重异常: {e}")
                self.client.report_lead_status(lead_id, "BIZ_FAILED", f"{phone}={customer_name}", str(e))
                
            # 执行完成后冷却
            self.status_state = "COOLDOWN"
            cooldown_time = random.randint(
                self.settings.rpa_min_interval_seconds,
                self.settings.rpa_max_interval_seconds
            )
            log_broadcaster.log(f"💤 任务完成，进入防风控休眠 {cooldown_time} 秒...")
            self._stop_event.wait(float(cooldown_time))
            
            self.status_state = "IDLE"
            self._task_queue.task_done()
```

- [ ] **Step 2: 编写测试验证守护线程及串行消费机制**
创建 `python/backend/app/tests/test_upstream_scheduler.py`:
```python
import time
import tempfile
import os
from backend.app.core.config import get_settings
from backend.app.storage.sqlite_store import SQLiteStore
from backend.app.services.upstream_scheduler import UpstreamScheduler

class DummyOrchestrator:
    def add_wechat(self, lead_id, greeting, remark, dry_run, human_approval):
        return {"job_id": "job_1", "status": "SUCCESS"}

def test_scheduler_lifecycle():
    db_fd, db_path = tempfile.mkstemp()
    try:
        settings = get_settings()
        store = SQLiteStore(db_path)
        
        # 写入 mock 模式配置
        store.save_upstream_config({"upstream_mode": "mock"})
        
        scheduler = UpstreamScheduler(
            settings=settings,
            store=store,
            orchestrator_factory=lambda: DummyOrchestrator()
        )
        
        assert scheduler.is_alive() is False
        scheduler.start()
        assert scheduler.is_alive() is True
        
        # 触发一次拉取
        scheduler.trigger_fetch_now()
        scheduler.stop()
        assert scheduler.is_alive() is False
    finally:
        os.close(db_fd)
        os.unlink(db_path)
```

- [ ] **Step 3: 运行测试**
Run: `uv run pytest python/backend/app/tests/test_upstream_scheduler.py -v`
Expected: PASS

- [ ] **Step 4: 提交 Task 3**
```bash
git add python/backend/app/services/upstream_scheduler.py python/backend/app/tests/test_upstream_scheduler.py
git commit -m "feat(upstream): 编写常驻队列调度器并测试通过"
```

---

### Task 4: REST / SSE 接口集成与服务自拉起

我们现在要把写好的 `UpstreamScheduler` 挂载进 FastAPI，并提供实时 SSE 日志和开发调试触发接口。

**Files:**
* Create: `python/backend/app/api/routes/upstream.py`
* Modify: `python/backend/app/main.py`
* Modify: `python/backend/app/api/deps.py`

**Interfaces:**
* Consumes: `UpstreamScheduler` 全局实例
* Produces: `/api/v1/upstream/*` 路由

- [ ] **Step 1: 新建 `upstream.py` 路由暴露配置、状态及 SSE 连接**
```python
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import Dict, Any

from backend.app.api.deps import get_store, get_settings
from backend.app.storage.sqlite_store import SQLiteStore
from backend.app.core.config import Settings
from backend.app.services.upstream_scheduler import log_broadcaster
import queue

router = APIRouter(prefix="/api/v1/upstream", tags=["upstream"])

# 全局单例持有器，在 main.py startup 阶段实例化并拉起
global_scheduler = None

def get_scheduler():
    global global_scheduler
    return global_scheduler

@router.post("/config")
def save_config(config: Dict[str, Any], store: SQLiteStore = Depends(get_store)):
    store.save_upstream_config(config)
    
    # 动态重启调度器应用新配置
    scheduler = get_scheduler()
    if scheduler:
        if scheduler.is_alive():
            scheduler.stop()
        scheduler.start()
        
    return {"status": "configured", "scheduler_alive": scheduler.is_alive() if scheduler else False}

@router.get("/config")
def get_config(store: SQLiteStore = Depends(get_store)):
    return store.get_upstream_config()

@router.get("/status")
def get_status(scheduler = Depends(get_scheduler)):
    if not scheduler:
        return {"scheduler_alive": False, "wechat_online": False, "state": "IDLE", "queue_remaining": 0}
        
    from backend.app.services.wechat_key_extractor import get_weixin_pids
    return {
        "scheduler_alive": scheduler.is_alive(),
        "wechat_online": len(get_weixin_pids()) > 0,
        "state": scheduler.status_state,
        "queue_remaining": scheduler._task_queue.qsize()
    }

@router.post("/dev/trigger-fetch")
def trigger_fetch(scheduler = Depends(get_scheduler)):
    if not scheduler: raise HTTPException(status_code=400, detail="Scheduler not ready")
    scheduler.trigger_fetch_now()
    return {"status": "triggered"}

@router.post("/dev/trigger-heartbeat")
def trigger_heartbeat(scheduler = Depends(get_scheduler)):
    if not scheduler: raise HTTPException(status_code=400, detail="Scheduler not ready")
    scheduler.trigger_heartbeat_now()
    return {"status": "triggered"}

@router.post("/dev/clear-queue")
def clear_queue(scheduler = Depends(get_scheduler)):
    if not scheduler: raise HTTPException(status_code=400, detail="Scheduler not ready")
    scheduler.clear_queue()
    return {"status": "cleared"}

@router.get("/logs")
def sse_logs(request: Request):
    """通过 SSE 实时向前端输出后台运行日志流水"""
    async def event_generator():
        q = queue.Queue()
        log_broadcaster.add_listener(q)
        try:
            while True:
                # 检查连接断开
                if await request.is_disconnected():
                    break
                try:
                    # 轮询获取新日志
                    log_item = q.get_nowait()
                    yield f"data: {log_item}\n\n"
                except queue.Empty:
                    await asyncio.sleep(0.5)
        finally:
            log_broadcaster.remove_listener(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

- [ ] **Step 2: 修改 `main.py` 在初始化阶段拉起守护线程**
```python
# main.py:10 附近引入
from backend.app.api.routes import upstream
from backend.app.services.upstream_scheduler import UpstreamScheduler
from backend.app.services.rpa_orchestrator import RpaOrchestrator
from backend.app.core.audit import AuditLogger

# main.py:33 附近挂载路由
app.include_router(upstream.router)

# main.py:40 @app.on_event('startup') 中加入自启动
@app.on_event('startup')
def startup() -> None:
    store = get_store()
    store.init_db()
    audit_logger = AuditLogger(store, settings)
    
    # 初始化全局调度器单例
    orchestrator_factory = lambda: RpaOrchestrator(store, audit_logger, settings)
    upstream.global_scheduler = UpstreamScheduler(settings, store, orchestrator_factory)
    upstream.global_scheduler.start()
    
    # 其它原有逻辑
    ...

# main.py:57 @app.on_event('shutdown') 中加入注销
@app.on_event('shutdown')
def shutdown() -> None:
    if upstream.global_scheduler:
        upstream.global_scheduler.stop()
    stop_friend_acceptance_rechecker()
```

- [ ] **Step 3: 运行完整 pytest 测试套件确认系统级兼容无冲突**
Run: `uv run pytest python/backend/app/tests/ -v`
Expected: ALL 42+ PASS (无错误)

- [ ] **Step 4: 提交 Task 4**
```bash
git add python/backend/app/api/routes/upstream.py python/backend/app/main.py
git commit -m "feat(upstream): 挂载本地 API 并绑定服务生命周期"
```

---

### Task 5: 前端 Zustand 状态管理与连接组件 (useUpstreamStore)

现在进入前端 React 开发。我们先建立上游的专属全局 Store，并与 SSE 和 REST 进行对接。

**Files:**
* Create: `src/stores/useUpstreamStore.ts`

**Interfaces:**
* Produces: React Hook `useUpstreamStore` 状态机。

- [ ] **Step 1: 创建 `useUpstreamStore.ts` 管理连接配置、指示灯状态与滚动日志数组**
```typescript
import { create } from 'zustand';

export interface UpstreamConfig {
  upstream_mode: 'mock' | 'real';
  upstream_api_url: string;
  client_id: string;
  client_secret: string;
}

export interface UpstreamStatus {
  scheduler_alive: boolean;
  wechat_online: boolean;
  state: 'IDLE' | 'BUSY' | 'COOLDOWN';
  queue_remaining: number;
}

interface UpstreamStoreState {
  config: UpstreamConfig;
  status: UpstreamStatus;
  logs: string[];
  isConnecting: boolean;
  
  // actions
  fetchConfig(): Promise<void>;
  saveConfig(cfg: Partial<UpstreamConfig>): Promise<void>;
  fetchStatus(): Promise<void>;
  triggerFetch(): Promise<void>;
  triggerHeartbeat(): Promise<void>;
  clearQueue(): Promise<void>;
  addLog(log: string): void;
  clearLogs(): void;
}

const BACKEND_URL = 'http://127.0.0.1:8000/api/v1/upstream';

export const useUpstreamStore = create<UpstreamStoreState>((set, get) => ({
  config: {
    upstream_mode: 'mock',
    upstream_api_url: '',
    client_id: '',
    client_secret: '',
  },
  status: {
    scheduler_alive: false,
    wechat_online: false,
    state: 'IDLE',
    queue_remaining: 0,
  },
  logs: [],
  isConnecting: false,

  fetchConfig: async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/config`);
      if (res.ok) {
        const data = await res.json();
        set({ config: { ...get().config, ...data } });
      }
    } catch (e) {
      console.error(e);
    }
  },

  saveConfig: async (cfg) => {
    set({ isConnecting: true });
    try {
      const body = { ...get().config, ...cfg };
      const res = await fetch(`${BACKEND_URL}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const data = await res.json();
        set({ 
          config: body,
          status: { ...get().status, scheduler_alive: data.scheduler_alive }
        });
      }
    } catch (e) {
      console.error(e);
    } finally {
      set({ isConnecting: false });
    }
  },

  fetchStatus: async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/status`);
      if (res.ok) {
        const data = await res.json();
        set({ status: data });
      }
    } catch (e) {}
  },

  triggerFetch: async () => {
    await fetch(`${BACKEND_URL}/dev/trigger-fetch`, { method: 'POST' });
  },

  triggerHeartbeat: async () => {
    await fetch(`${BACKEND_URL}/dev/trigger-heartbeat`, { method: 'POST' });
  },

  clearQueue: async () => {
    await fetch(`${BACKEND_URL}/dev/clear-queue`, { method: 'POST' });
  },

  addLog: (log) => set((state) => ({ logs: [...state.logs.slice(-199), log] })), // 最多保留 200 行日志
  
  clearLogs: () => set({ logs: [] }),
}));
```

- [ ] **Step 2: 提交 Task 5**
```bash
git add src/stores/useUpstreamStore.ts
git commit -m "feat(upstream): 创建前端 Zustand 状态管理 Store"
```

---

### Task 6: 创建前端 UI 控制面板并绑定侧边栏路由

我们现在要在前端画出仪表盘界面，绑定 SSE 日志流，并在左侧导航栏新增路由。

**Files:**
* Create: `src/components/features/UpstreamConfig.tsx`
* Modify: `src/components/layout/AppShell.tsx`
* Modify: `src/components/layout/Sidebar.tsx`

- [ ] **Step 1: 新建 `UpstreamConfig.tsx` 实现卡片布局及滚动日志监控**
```typescript
import { useEffect, useRef } from 'react';
import { useUpstreamStore } from '@/stores/useUpstreamStore';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Label } from '@/components/ui/label';

export function UpstreamConfig() {
  const { 
    config, status, logs, isConnecting,
    fetchConfig, saveConfig, fetchStatus,
    triggerFetch, triggerHeartbeat, clearQueue,
    addLog, clearLogs
  } = useUpstreamStore();

  const logEndRef = useRef<HTMLDivElement>(null);

  // 1. 定期刷新健康状态
  useEffect(() => {
    fetchConfig();
    fetchStatus();
    const timer = setInterval(fetchStatus, 5000);
    return () => clearInterval(timer);
  }, []);

  // 2. 初始化监听 SSE 日志流
  useEffect(() => {
    const eventSource = new EventSource('http://127.0.0.1:8000/api/v1/upstream/logs');
    eventSource.onmessage = (event) => {
      addLog(event.data);
    };
    return () => {
      eventSource.close();
    };
  }, []);

  // 3. 自动滚动日志到底部
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const stateColors = {
    IDLE: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
    BUSY: 'bg-amber-500/10 text-amber-500 border-amber-500/20',
    COOLDOWN: 'bg-indigo-500/10 text-indigo-500 border-indigo-500/20',
  };

  return (
    <div className="flex-1 p-6 overflow-y-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold tracking-tight">上游接口与调度管理</h1>
        <p className="text-xs text-muted-foreground">配置与测试外部业务系统对接</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Card A: 配置 */}
        <Card className="p-6 border border-border bg-card space-y-4 lg:col-span-2">
          <h2 className="text-sm font-bold">上游参数配置</h2>
          
          <div className="space-y-4">
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-muted-foreground">运行模式</Label>
              <RadioGroup 
                value={config.upstream_mode} 
                onValueChange={(val: 'mock' | 'real') => saveConfig({ upstream_mode: val })}
                className="flex items-center gap-6"
              >
                <div className="flex items-center space-x-2">
                  <RadioGroupItem value="mock" id="mode-mock" />
                  <Label htmlFor="mode-mock" className="text-xs">Mock 本地模拟模式</Label>
                </div>
                <div className="flex items-center space-x-2">
                  <RadioGroupItem value="real" id="mode-real" />
                  <Label htmlFor="mode-real" className="text-xs">Real 真实网络模式</Label>
                </div>
              </RadioGroup>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs font-semibold text-muted-foreground">上游 API URL</Label>
              <input 
                type="text" 
                defaultValue={config.upstream_api_url}
                onBlur={(e) => saveConfig({ upstream_api_url: e.target.value })}
                className="w-full px-3 py-2 bg-transparent border border-input text-foreground rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-ring transition-colors"
                placeholder="http://localhost:8000/api/v1/upstream"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label className="text-xs font-semibold text-muted-foreground">Client ID</Label>
                <input 
                  type="text" 
                  defaultValue={config.client_id}
                  onBlur={(e) => saveConfig({ client_id: e.target.value })}
                  className="w-full px-3 py-2 bg-transparent border border-input text-foreground rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-ring transition-colors"
                  placeholder="client-001"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs font-semibold text-muted-foreground">Client Secret</Label>
                <input 
                  type="password" 
                  defaultValue={config.client_secret}
                  onBlur={(e) => saveConfig({ client_secret: e.target.value })}
                  className="w-full px-3 py-2 bg-transparent border border-input text-foreground rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-ring transition-colors"
                  placeholder="••••••••••••"
                />
              </div>
            </div>
          </div>
        </Card>

        {/* Card B: 状态 */}
        <Card className="p-6 border border-border bg-card space-y-4">
          <h2 className="text-sm font-bold">系统健康度监控</h2>
          <div className="space-y-3.5 pt-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">后台守护服务</span>
              <Badge variant={status.scheduler_alive ? "success" : "destructive"} className="text-[10px]">
                {status.scheduler_alive ? "运行中" : "已停止"}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">PC 微信状态</span>
              <Badge variant={status.wechat_online ? "success" : "destructive"} className="text-[10px]">
                {status.wechat_online ? "微信已启动" : "未检测到进程"}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">调度器工作状态</span>
              <Badge variant="outline" className={`text-[10px] ${stateColors[status.state]}`}>
                {status.state === "IDLE" ? "IDLE 空闲" : status.state === "BUSY" ? "BUSY 繁忙" : "COOLDOWN 风控等待"}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">队列任务数</span>
              <Badge variant="secondary" className="text-[10px]">{status.queue_remaining} 个等待中</Badge>
            </div>
          </div>
        </Card>
      </div>

      {/* Card C: 滚动日志 */}
      <Card className="p-6 border border-border bg-card space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold">调试日志控制台</h2>
          <Button variant="ghost" size="sm" onClick={clearLogs} className="text-xs h-7 text-muted-foreground">清空日志</Button>
        </div>

        <div className="h-64 bg-slate-950 text-slate-100 rounded-lg p-4 font-mono text-xs overflow-y-auto space-y-1.5 border border-slate-800">
          {logs.map((log, index) => (
            <div key={index} className="leading-relaxed whitespace-pre-wrap">{log}</div>
          ))}
          {logs.length === 0 && <div className="text-slate-500">等待调度事件日志流入...</div>}
          <div ref={logEndRef} />
        </div>

        <div className="flex items-center gap-3">
          <Button onClick={triggerFetch} size="sm">立即触发拉取线索</Button>
          <Button onClick={triggerHeartbeat} variant="outline" size="sm">测试发送心跳</Button>
          <Button onClick={clearQueue} variant="destructive" size="sm">清空本地等待队列</Button>
        </div>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: 修改 `Sidebar.tsx` 加入上游对接导航项**
在 `Sidebar.tsx:7` 附近：
```typescript
import { LayoutDashboard, UserCheck, ShieldAlert, FlaskConical, Radio } from 'lucide-react'; // 引入 Radio 图标

export const ROUTE_DEFINITIONS = [
  { path: '/dashboard', label: '系统看板', icon: LayoutDashboard },
  { path: '/accounts', label: '账号管理', icon: UserCheck },
  { path: '/risk', label: '风控管理', icon: ShieldAlert },
  { path: '/upstream', label: '上游对接', icon: Radio }, // 新增
  { path: '/test', label: '开发测试', icon: FlaskConical },
] as const;
```

- [ ] **Step 3: 修改 `AppShell.tsx` 动态加载并挂载新路由**
在 `AppShell.tsx:9` 附近：
```typescript
const UpstreamConfig = lazy(() => import('../features/UpstreamConfig').then(m => ({ default: m.UpstreamConfig })));
```
在 `AppShell.tsx:85` 附近的路由渲染判断中：
```typescript
case '/upstream':
  return <UpstreamConfig />;
```

- [ ] **Step 4: 运行 Vite 本地打包编译验证 React 代码零错误**
Run: `npm run build`
Expected: 成功编译无 TypeScript 与 Eslint 错误。

- [ ] **Step 5: 提交 Task 6 并完成开发任务**
```bash
git add src/components/features/UpstreamConfig.tsx src/components/layout/Sidebar.tsx src/components/layout/AppShell.tsx
git commit -m "feat(upstream): 编写前端 UI 仪表盘并完成侧边栏集成"
```
