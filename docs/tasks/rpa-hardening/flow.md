# RPA 加微链路加固 · 实际功能流程

> 反映代码现状，**不**复述设计文档。设计期望见 [plan.md](plan.md)。
> 对账机制：plan-agent 用本文档 vs plan 设计章节 diff → 出优化清单。

---

## Cycle 1 · 基础设施层（需求 2 / 4 / 6）已落地

### 1. lead_status_reports outbox（需求 2）

**新增表**：[python/backend/app/storage/sqlite_store.py:97-110](../../../python/backend/app/storage/sqlite_store.py#L97-L110)
```
TABLE lead_status_reports (
  lead_id, job_id, upstream_status, remark, error_details,
  status, attempts, last_error, payload_json,
  created_at, updated_at,
  PRIMARY KEY (lead_id, job_id)
)
```
主键按设计取 `(lead_id, job_id)`；重复 enqueue 走 `ON CONFLICT ... DO UPDATE`，状态从 SENT **不退回** PENDING（与 friend_check_reports 一致）。

**Store 新增 4 个方法**（[sqlite_store.py:480-625](../../../python/backend/app/storage/sqlite_store.py)）：
- `enqueue_lead_status_report(...)` — UPSERT
- `list_pending_lead_status_reports(limit)` — 按 `updated_at ASC`，limit clamp 1–200
- `mark_lead_status_report_sent(lead_id, job_id, timestamp)`
- `mark_lead_status_report_failed(lead_id, job_id, error, timestamp, *, max_attempts=8)` — `attempts+1 >= max_attempts THEN FAILED`

**Scheduler 接入**：
- `_worker_loop` 不再调用 `self.client.report_lead_status(...)`，改走 `self._enqueue_lead_status_report(...)` ([upstream_scheduler.py:378-396](../../../python/backend/app/services/upstream_scheduler.py#L378))
- 严重异常分支也走 outbox：`job_id` 取当前 job_id，缺失时落 `orch_error_{lead_id}` 占位
- 新增 `_lead_status_report_loop` 守护线程，间隔 `lead_status_report_interval_seconds`（默认 **30s**）
- 新增 `_report_lead_status_once()`：批量拉 PENDING → `client.report_lead_status(...)` → 成功 mark_sent / 失败 mark_failed，attempts 累计；达上限 `lead_status_report_max_attempts`（默认 **8**）→ FAILED 死信，不再返出
- 暴露 `trigger_lead_status_report_now()` + dev 路由 `POST /api/v1/upstream/dev/trigger-lead-status-report`
- 暴露 `GET /api/v1/upstream/dev/lead-status-reports` 直接读 outbox（限 limit ≤ 200）

**与设计的实际偏差**：
- ✅ 主键、状态机、守护线程间隔、max_attempts 全部按设计
- ⚠️ 设计写"路由 dev 触发是 `/dev/lead-status-report/run`"，实际落地为 `/dev/trigger-lead-status-report`，与 friend-check 路由命名风格保持一致（`/dev/trigger-*`）
- ⚠️ 设计未明示"outbox 入队本身失败时怎么办"，实际做法：try/except 后只 log，不阻塞 worker 流程（[upstream_scheduler.py:329-339](../../../python/backend/app/services/upstream_scheduler.py)）

### 2. HTTP add_wechat per-lead 互斥（需求 4）

**新增异常**：`LeadBusyError(lead_id, existing_job_id, existing_status)`（[sqlite_store.py:8-19](../../../python/backend/app/storage/sqlite_store.py#L8))

**新增 Store 方法**：`create_job_if_lead_idle(job, busy_statuses)` ([sqlite_store.py:181-219](../../../python/backend/app/storage/sqlite_store.py#L181))
- 走 `BEGIN IMMEDIATE` 持写锁
- 查 `lead_id` + `status IN busy_statuses` 命中即 `ROLLBACK` 抛 `LeadBusyError`
- 未命中则原子 INSERT

**Orchestrator 接入**：`add_wechat` 的 `store.create_job(job)` 替换为 `create_job_if_lead_idle(job, _BUSY_JOB_STATUSES)`（[rpa_orchestrator.py:109-132](../../../python/backend/app/services/rpa_orchestrator.py))
- `_BUSY_JOB_STATUSES = ("REAL_QUEUED","REAL_RUNNING","SIMULATION_QUEUED","SIMULATION_RUNNING")`
- 命中 → audit `rpa.blocked.lead_busy` → 抛 `AppError("RPA_LEAD_BUSY", ..., http_status.HTTP_409_CONFLICT)`

**与设计的偏差**：
- ✅ 原子 SQL、busy_statuses 范围、HTTP 409、audit reason_code 全部按设计
- ⚠️ 设计提到"DummyOrchestrator 测试需补 LeadBusyError 分支"——本轮**仅**在 unit test 层加了 `TestPerLeadMutualExclusion`；`test_upstream_scheduler.py` 里的 `DummyOrchestrator` 没有触发该分支（它从不重复 enqueue 同一 lead），保留现状

### 3. 401 自动续签（需求 6）

**RealUpstreamClient 重写**（[upstream_client.py:82-203](../../../python/backend/app/services/upstream_client.py#L82))：
- 新增 `_login_lock: threading.Lock` 和 `_token_version: int`
- 公开 `login()` 持锁后调 `_login_locked()`；后者负责实际 HTTP + 自增版本号
- 新增 `_call_with_relogin(do_request)` 统一包装：
  - 第一次请求，收到 401 → 进锁内"token 版本号没变"判断 → 走 `_login_locked()` 一次
  - 续签成功 → 用新 token 重试 do_request **一次**
  - 续签失败 → 透传第一次的 401 响应（保持调用方 False 返回）
  - 并发：多线程同时撞 401，靠 token 版本号去重，只触发 1 次实际 login
- 4 个鉴权调用（send_heartbeat / fetch_leads / report_lead_status / report_friend_check）全部通过 `_call_with_relogin` 包装

**与设计的偏差**：
- ✅ 锁、版本号、单点续签、4 个调用全覆盖
- ⚠️ 设计提到"非 401 不触发续签"——实际任何 `>=400` 但 `!= 401` 都直接透传（包括 403/422/500/503），与设计一致

---

## Cycle 1 配置项落地（[core/config.py:23-27](../../../python/backend/app/core/config.py#L23))

```python
lead_status_report_interval_seconds: int = Field(default=30, ge=5, le=86400)
lead_status_report_batch_size: int = Field(default=20, ge=1, le=100)
lead_status_report_max_attempts: int = Field(default=8, ge=1, le=50)
```

> 设计稿写 `interval` 范围 30s 起，实际下限放到 5s 以便测试；max_attempts 上限 50 是防误输入。

---

## Cycle 1 测试覆盖

新增/调整测试 → 全部绿色，pytest 总数 65 → 82。

| 文件 | 用例 |
|---|---|
| `test_upstream_storage.py` | `enqueue_lead_status_report` 各转移、 `create_job_if_lead_idle` 互斥/放行 |
| `test_rpa_acceptance_lifecycle.py::TestPerLeadMutualExclusion` | add_wechat 抛 RPA_LEAD_BUSY/409，audit reason_code=RPA_LEAD_BUSY，busy_statuses 正确 |
| `test_upstream_client_relogin.py` (新文件) | heartbeat/report_lead_status/fetch_leads 各自 401→login→retry；并发 401 单点 login；login 失败透传；非 401 不触发 |
| `test_upstream_scheduler.py` | `_report_lead_status_once` 成功/失败转 FAILED；`_worker_loop` 不再直接调 `client.report_lead_status` 而是写 outbox |

**未在本轮覆盖的测试**：FastAPI 路由层 409 端到端（计划文档列在 4.4，本轮认为 unit 层 AppError 已足够，端到端放 Cycle 3 reconciler 时一并跑）。

---

## Cycle 1 阶段遗留追踪

1. **`acceptance_attempts` 字段还没加到 leads 表**——已在 Cycle 3 落地。
2. **`WECHAT_ACCEPTANCE_EXHAUSTED` 终态尚未引入**——已在 Cycle 3 落地。
3. **`_worker_loop` 写 outbox 时若入队失败仅 log**——本轮 plan 的启动 reconciler 只要求处理 `RPA_PENDING_APPROVAL` 过期态与 outbox backlog audit，未要求回填"终态 job 但缺 lead_status_report"。该项保留为后续优化候选，见 plan 对账优化清单。

---

## Cycle 2 · 状态机（需求 1 + 3）已落地

### 1. RISK_FROZEN 调度器状态（需求 1）

**新增 settings**：[python/backend/app/core/config.py:19-25](../../../python/backend/app/core/config.py#L19)
- `rpa_retry_precheck_enabled: bool = True`
- `rpa_retry_precheck_timeout_seconds: int = 30`（保留，本轮未使用）
- `risk_freeze_seconds: int = 7200`（默认 2h，范围 60–86400）

**UpstreamScheduler 扩展**（[upstream_scheduler.py:99-117](../../../python/backend/app/services/upstream_scheduler.py))：
- 新增字段：`_freeze_lock: RLock`, `_freeze_until: float | None`, `_last_risk_at: str | None`
- 注释明确：`status_state` 与 `RISK_FROZEN` 是**维度叠加**——只要 `_freeze_until > monotonic()` 心跳/接口都报 RISK_FROZEN
- 新增公开 API：
  - `is_frozen() -> bool` —— 内含到期自动清零的副作用（[L163-L171](../../../python/backend/app/services/upstream_scheduler.py#L163))
  - `get_frozen_remaining_seconds() -> float`
  - `_compute_status_state() -> str` —— 心跳/路由读取
  - `notify_risk_event(*, reason='BIZ_RISK_CONTROL')` —— 由 orchestrator 注入回调
  - `unfreeze(*, reason='manual') -> bool` —— dev API 提前解冻

**接入点**：
- `_heartbeat_action`：状态值改读 `_compute_status_state()`（[L353-L363](../../../python/backend/app/services/upstream_scheduler.py))
- `_worker_loop`：从队列拿到 item 后若 `is_frozen()` → 原样回插 + `_stop_event.wait(min(30, remaining))`（[L386-L399](../../../python/backend/app/services/upstream_scheduler.py))
- `PollingLeadSource.run`：接受 `is_frozen` 回调，冻结期间跳过 fetch 但保持节拍（[upstream_lead_source.py:39-49](../../../python/backend/app/services/upstream_lead_source.py))
- `lead_source` 实例化时传 `is_frozen=self.is_frozen`

**dev 路由**：`POST /api/v1/upstream/dev/scheduler/unfreeze` ([api/routes/upstream.py:46-54](../../../python/backend/app/api/routes/upstream.py))
**`/status` 接口**：增加 `frozen_remaining_seconds` 字段；`state` 字段改读 `_compute_status_state()`。

**与设计的偏差**：
- ✅ 内存态 + monotonic 时间、2 小时默认、重复触发不延长、自动到期、dev unfreeze 全按设计
- ⚠️ 设计的"orchestrator_factory 增参传入 callable" 实际方案：`RpaOrchestrator.__init__` 新增 `risk_event_handler` 关键字参数（[rpa_orchestrator.py:38-58](../../../python/backend/app/services/rpa_orchestrator.py)），由 `main.py` startup 时先创建 scheduler、再用它的 `notify_risk_event` 注入到 orchestrator_factory（[main.py:60-80](../../../python/backend/app/main.py))。HTTP 路径走 `deps.get_rpa_orchestrator` 也注入同一 scheduler 引用。
- ⚠️ heartbeat 上报字段直接复用 `status` 而非新增字段——与上游协议一致；上游若不识别 `RISK_FROZEN` 会被当 `BUSY` 解释（已在设计 §1 兼容性说明）

### 2. RPA 重试前核验（需求 3）

**新增模块函数**：[friend_acceptance.py:153-228](../../../python/backend/app/services/friend_acceptance.py)
- `probe_screen_state_for_retry(phone, *, job_id=None, cancel_token=None)`
  - 状态序：`["RISK_CONTROL", "TARGET_NOT_FOUND", "ALREADY_FRIEND", "SEND_SUCCESS"]`
  - **不写 DB / 不发 audit**，只完成"看一眼"
  - 失败抛 AppError；命中状态由调用方判断

**RpaOrchestrator 接入**：
- `__init__` 新增 `retry_precheck` kwarg（[rpa_orchestrator.py:38-58](../../../python/backend/app/services/rpa_orchestrator.py)）
- `_run_job` 在 `attempt > 0` 时调一次核验（[L194-L221](../../../python/backend/app/services/rpa_orchestrator.py)）：
  - 命中 `RpaBusinessOutcome` → 外层 `except RpaBusinessOutcome` 收尾走 `_finalize_business_outcome`
  - 系统级 `Exception` → 仅 `update_step('SYS_RETRY_PRECHECK_FAILED: ...')`，重试链路继续
- `_OUTCOME_LEAD_STATUS` 新增 `BIZ_ALREADY_REQUESTED → WECHAT_ADD_REQUESTED`（[L324-L331](../../../python/backend/app/services/rpa_orchestrator.py)）
- `_finalize_business_outcome` 在 `circuit_break=True` 时调用 `self.risk_event_handler(outcome.code)`（[L361-L368](../../../python/backend/app/services/rpa_orchestrator.py)）

**上游映射**：
- `JOB_STATUS_UPSTREAM_STATUS["REAL_BIZ_ALREADY_REQUESTED"] = "REAL_SENT"`（[upstream_scheduler.py:31-39](../../../python/backend/app/services/upstream_scheduler.py))

**main.py 注入** ([main.py:62-91](../../../python/backend/app/main.py))：
- 定义 `_retry_precheck(lead, greeting, update_step)` 包装 `probe_screen_state_for_retry`
- 命中映射：`ALREADY_FRIEND → BIZ_ALREADY_FRIEND`、`SEND_SUCCESS → BIZ_ALREADY_REQUESTED`、`RISK_CONTROL → BIZ_RISK_CONTROL(circuit_break=True)`
- `orchestrator_factory` 同时注入 `risk_event_handler` 和 `retry_precheck`

**与设计的偏差**：
- ✅ attempt>0 才执行、复用 friend_acceptance 路径、SEND_SUCCESS 走 BIZ_ALREADY_REQUESTED、系统错误不阻塞重试 —— 全按设计
- ⚠️ 设计提到的 `rpa_retry_precheck_timeout_seconds=30` 实际**未在代码层强制**：核验内部的 `_sleep(2.0)` 与 `_detect_screen_state` 自带超时已可保护，本轮不引入额外 watchdog。若后续证明核验确实可能挂死再补 worker.join(timeout=...) 包装

---

## Cycle 2 测试覆盖

新增 [test_risk_frozen_and_retry_precheck.py](../../../python/backend/app/tests/test_risk_frozen_and_retry_precheck.py)，**13 个用例全绿**：

| 分组 | 用例 |
|---|---|
| RISK_FROZEN | `notify_risk_event_freezes` / `repeat_does_not_extend` / `expires_on_its_own` / `unfreeze_clears` / `heartbeat_reports_frozen` / `worker_loop_requeues_during_freeze` / `finalize_calls_handler` / `non_circuit_break_no_handler` |
| 重试前核验 | `precheck_skipped_on_first` / `precheck_invoked_only_on_retry` / `precheck_already_friend_short_circuits` / `precheck_send_success_maps_to_already_requested` / `precheck_system_error_does_not_block_retry` |

**pytest 总数**：82 → **95**，无回归。

---

## Cycle 3 · 业务收尾（需求 5 / 7）已落地

### 1. acceptance_attempts 上限 + 状态转换（需求 5）

**数据模型**
- `leads` 新增 `acceptance_attempts INTEGER NOT NULL DEFAULT 0`，`init_db()` 对旧库执行轻量 `ALTER TABLE` 迁移。
- `create_lead()` 支持写入 `acceptance_attempts`，默认 0。
- `LeadStatus.WECHAT_ACCEPTANCE_EXHAUSTED` 已作为复查上限终态加入；`TERMINAL_LEAD_STATUSES` 已包含该状态。

**FriendAcceptanceService.check_lead**
- 已接受好友：转 `WECHAT_ACCEPTED`，写 `friend_check_reports=True`，**不增加** `acceptance_attempts`。
- 仍待通过：`acceptance_attempts + 1`，保持 `WECHAT_ADD_REQUESTED`。
- 达到 `friend_acceptance_max_attempts`（默认 12）：转 `WECHAT_ACCEPTANCE_EXHAUSTED`，写 `lead_status_reports`，`upstream_status=BIZ_ACCEPTANCE_EXHAUSTED`。
- 读屏命中 `RISK_CONTROL`：转 `WECHAT_RISK_CONTROL`，写 `lead_status_reports(BIZ_RISK_CONTROL)`，写 `friend_check_reports=False`，并调用 `risk_event_handler(reason="BIZ_RISK_CONTROL")` 触发调度器冻结。
- 读屏命中 `TARGET_NOT_FOUND`：转 `WECHAT_TARGET_NOT_FOUND`，写 `lead_status_reports(BIZ_TARGET_NOT_FOUND)`。

**Settings**
- 新增 `friend_acceptance_max_attempts: int = 12`（范围 1–100）。
- `start_friend_acceptance_rechecker()` 将该阈值传入 worker，并把 scheduler 的 `notify_risk_event` 注入复查链路。

**与设计的偏差**
- ✅ attempts 字段、默认阈值、EXHAUSTED / RISK / TARGET_NOT_FOUND 转态、RISK_FROZEN 联动均已落地。
- ⚠️ `BIZ_ACCEPTANCE_EXHAUSTED` 通过 `lead_status_reports` 直接上报，不进入 `JOB_STATUS_UPSTREAM_STATUS`，因为它不是 RPA job 终态产生的状态。

### 2. 启动 reconciler（需求 7）

**新增模块**：`python/backend/app/services/startup_reconciler.py`
- `reconcile_on_startup(store, audit, settings) -> dict`
- 将超过 `startup_reconciler_pending_grace_seconds`（默认 600s）的 `RPA_PENDING_APPROVAL` 线索转为 `RPA_BLOCKED`，并记录 `rpa.reconciler.pending_too_long`。
- 统计 `lead_status_reports` 与 `friend_check_reports` 的 PENDING 积压。
- 积压超过 `startup_reconciler_outbox_alert_threshold`（默认 20）时记录 `startup_reconciler.outbox_backlog`。

**main.py 接入顺序**
1. `store.recover_interrupted_jobs(...)`
2. `reconcile_on_startup(...)`，成功记录 `startup_reconciler.completed`，异常记录 `startup_reconciler.failed` 且不阻塞启动
3. 初始化 `UpstreamScheduler`
4. 启动 friend acceptance rechecker，并注入 scheduler 的 `notify_risk_event`

**与设计的偏差**
- ✅ 独立模块、grace 配置、outbox backlog audit、异常不阻塞启动均按设计。
- ⚠️ reconciler 仅统计 outbox 积压，不主动重投；实际重投仍由已有 outbox 守护线程负责，避免 startup 同步阶段做网络 I/O。

### 3. Cycle 3 测试覆盖

新增/调整测试：
- `test_friend_acceptance.py`
  - accepted 分支不增加 attempts
  - pending 分支 attempts +1
  - attempts 达上限转 `WECHAT_ACCEPTANCE_EXHAUSTED` 并上报 `BIZ_ACCEPTANCE_EXHAUSTED`
  - `RISK_CONTROL` 转态、写 outbox、触发 `risk_event_handler`
  - `TARGET_NOT_FOUND` 转态并写 outbox
- `test_startup_reconciler.py`
  - 过期 `RPA_PENDING_APPROVAL` 转 `RPA_BLOCKED`
  - 未过期待审批不变
  - outbox 积压触发 audit

**验证命令**
```
$env:PYTHONPATH='.'; uv run pytest backend/app/tests
```

**结果**：101 passed，4 个 FastAPI `on_event` deprecation warnings（既有框架弃用提醒，本轮不改）。

STATUS: READY_FOR_REVIEW（Cycle 3）

