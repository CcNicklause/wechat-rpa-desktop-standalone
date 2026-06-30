# RPA 加微链路 P0/P1 加固方案

> 范围：见 `docs/tasks/rpa-hardening/state.md`，**仅** P0 ①②③ + P1 ④⑤⑥⑦
> 不在范围：P2 前端 UX、密码 API 实装、SSE 鉴权改造
> 文档对象：coder-agent / 测试 / 复盘
> 编排约束：CLAUDE.md §22-50 轻量模板，一份合一文档

---

## 第一部分 · 需求

### 需求 1 — RISK_FROZEN 调度器状态（P0）

- **业务问题**：真实 RPA 链路触发 `BIZ_RISK_CONTROL` 后，仅靠 `daily_counters` 计数饱和实现冷却；进程重启或人工调高 `rpa_daily_limit` 会立即恢复对该号操作，缺乏显式"冷冻期"语义，业务侧无法在心跳/UI 上看到"被风控冻结"这件事。
- **验收标准**
  1. 当 `_finalize_business_outcome` 收到 `circuit_break=True` 的 outcome（即 `BIZ_RISK_CONTROL`），调度器立即从 IDLE/BUSY/COOLDOWN 切换为 `RISK_FROZEN`，状态持续到 `now + risk_freeze_seconds`，期间 worker 不消费 `_task_queue`，`PollingLeadSource` 不发起 `fetch_leads`。
  2. RISK_FROZEN 期间心跳仍然每 `upstream_heartbeat_interval_seconds` 跳动一次，`status` 字段上报为 `RISK_FROZEN`；冻结到期或人工解冻后下一次心跳上报为 `IDLE`。
  3. 冻结到期后调度器自动转 `IDLE`，**不需**人工干预；同时提供一个开发用 `/dev/scheduler/unfreeze` 接口允许手动提前解冻（仅记录 audit，不直接清理 `daily_counters`）。
  4. 同一冻结周期内即使重复触发风控也不重叠延长，仅刷新 `last_risk_at` 与 audit 事件。

### 需求 2 — lead_status_reports outbox（P0）

- **业务问题**：`UpstreamScheduler._worker_loop` 当前在 RPA job 结束后**同步**调用 `client.report_lead_status(...)`，HTTP 失败或上游 5xx 时仅 try/except 吞掉，永远不会重投，导致上游侧 lead 一直停留在执行中、对账缺口。
- **验收标准**
  1. RPA job 终态后写入新 outbox 表 `lead_status_reports`，状态机为 `PENDING → SENT / FAILED`，与 `friend_check_reports` 同构。
  2. 同一 `(lead_id, job_id)` 只会有一条记录，重复 enqueue 等价 upsert（保留 attempts 和 last_error，状态从 SENT 退回 PENDING 是禁止的）。
  3. 新增 `_lead_status_report_loop` 守护线程，按 `lead_status_report_interval_seconds`（默认 30s）拉取 `PENDING` 批量上报；网络失败 → attempts +1 / last_error 记录；attempts ≥ `lead_status_report_max_attempts`（默认 8）→ `FAILED` 并发 audit 告警。
  4. 提供 `trigger_lead_status_report_now()` 开发接口，便于一键 flush。
  5. 进程冷启动时 `recover_interrupted_jobs` 走完后，仍 `PENDING` 的报告在调度器启动时由守护线程自然续投。

### 需求 3 — RPA 重试前核验（P0）

- **业务问题**：`_run_job` 的系统异常重试（`max_retries=1`，attempts 0→1）不区分"添加动作是否已经发出"；如果首次跑到点击"发送"后才崩，第二次会再次搜索→再次发送，造成**重复加微**和对方收到二次申请，触发风控的真实风险。
- **验收标准**
  1. 重试前在新线程内执行一次"轻量核验"——只搜索目标号、读屏，不点击任何按钮；OCR 命中 `ALREADY_FRIEND` / `SEND_SUCCESS` / `RISK_CONTROL` 时立刻短路重试。
  2. 命中 `ALREADY_FRIEND` → 抛 `RpaBusinessOutcome("BIZ_ALREADY_FRIEND")`，按既有终态收尾，enqueue friend_check_report。
  3. 命中 `SEND_SUCCESS` → 抛新增 `RpaBusinessOutcome("BIZ_ALREADY_REQUESTED")`，lead.status 落入 `WECHAT_ADD_REQUESTED`（与正常发送成功等价），不发起第二次添加。
  4. 命中 `RISK_CONTROL` → 抛 `RpaBusinessOutcome("BIZ_RISK_CONTROL", circuit_break=True)`，触发需求 1 的 RISK_FROZEN。
  5. 核验过程本身抛系统异常（窗口找不到、超时）→ 视为"核验失败但允许重试"，记录 `SYS_RETRY_PRECHECK_FAILED` 步骤但不阻塞重试。

### 需求 4 — HTTP add_wechat per-lead 互斥（P1）

- **业务问题**：`POST /api/v1/rpa/add-wechat` 走 `run_background` 异步起 job，没有任何"同一 lead 仅一个 in-flight job"的校验；前端连点 / 上游重复推送 / 调度器手动触发交叉会产生多个 job 并发跑同一号，污染 daily_counters 和 OCR 串话。
- **验收标准**
  1. `RpaOrchestrator.add_wechat` 入口在 `create_job` 之前以原子 SQL 校验"该 lead 当前不存在状态属于 {REAL_QUEUED, REAL_RUNNING, SIMULATION_QUEUED, SIMULATION_RUNNING} 的 job"。
  2. 检测到正在进行的 job → 抛 `AppError("RPA_LEAD_BUSY", "该线索已有进行中的 RPA 任务，请勿重复触发")`，HTTP 409；同时 audit 记录 `rpa.blocked.lead_busy`。
  3. 调度器 `_worker_loop` 也走同一入口，因此自带去重；不需要再加 worker 侧锁。
  4. 校验路径无 race：通过 SQL `INSERT ... WHERE NOT EXISTS (SELECT 1 FROM rpa_jobs ...)` 或包在显式 `BEGIN IMMEDIATE` 事务里。

### 需求 5 — acceptance_attempts 上限 + 状态转换（P1）

- **业务问题**：`FriendAcceptanceRecheckWorker` 对 `WECHAT_ADD_REQUESTED` 的 lead 反复 OCR 复查，没有次数上限，对方永不通过会无限轮询；并且 OCR 在复查链路里命中 `RISK_CONTROL` 时**没有触发熔断**，只是把结果原样写进 audit。
- **验收标准**
  1. `leads` 表新增 `acceptance_attempts` 列（默认 0），每次 `FriendAcceptanceService.check_lead` 真正调用 OCR（非短路分支）后 +1。
  2. 达到 `friend_acceptance_max_attempts`（默认 12，约对应 5min×12 ≈ 1 小时；可配置 1–500）时，lead.status → 新增终态 `WECHAT_ACCEPTANCE_EXHAUSTED`，停止复查；同时 enqueue 一条 lead_status_report，上报 upstream status `BIZ_ACCEPTANCE_EXHAUSTED`。
  3. OCR 在复查中命中 `RISK_CONTROL` → lead.status → `WECHAT_RISK_CONTROL`，调度器进入 RISK_FROZEN（复用需求 1），并 enqueue `BIZ_RISK_CONTROL` 上报。
  4. OCR 命中 `TARGET_NOT_FOUND`（对方注销账号）→ lead.status → `WECHAT_TARGET_NOT_FOUND`，停止复查并 enqueue `BIZ_TARGET_NOT_FOUND`。
  5. `attempts` 不在 OCR 命中 `ALREADY_FRIEND`（成功）时增加；已经为终态的 lead 进入 `check_lead` 短路时不增加。

### 需求 6 — 401 自动续签（P1）

- **业务问题**：`RealUpstreamClient.login()` 拿到 token 后没有过期/失效处理；上游 token 24h 过期或服务端主动撤销时，所有 API 在 401 上 silent fail，调度器拉不到线索也没有告警。
- **验收标准**
  1. `RealUpstreamClient` 所有需要鉴权的 HTTP 调用（`send_heartbeat`、`fetch_leads`、`report_lead_status`、`report_friend_check`）在收到 401 时自动 `login()` 一次后重试**一次**。
  2. 并发场景：多个线程在同一秒收到 401，只触发一次实际 `login()` 调用（线程锁 + token 版本号）。
  3. 续签失败 → 调用方接到 False（保持既有行为），并由 `log_broadcaster` 打一条 `⚠️ 上游 token 续签失败` 日志。
  4. 续签成功后旧 401 请求自动用新 token 重发，对调用方透明。

### 需求 7 — 启动 reconciler（P1）

- **业务问题**：进程异常退出后，`recover_interrupted_jobs` 只把 RUNNING 状态的 job 写成 FAILED + lead 写成 `RPA_FAILED`，但其他"卡死"状态（被 enqueue 但未消费 / RPA_PENDING_APPROVAL 永久挂起 / friend_check_reports 大量积压）没有兜底；`lead_status_reports` outbox 也需要启动时进入续投。
- **验收标准**
  1. 启动阶段（`main.py: startup`）在 `recover_interrupted_jobs` 后追加 `reconcile_on_startup(store, audit, settings)`：
     - 扫描 `leads.status = RPA_PENDING_APPROVAL` 且 `updated_at` 超过 `startup_reconciler_pending_grace_seconds`（默认 600s）→ 标记为 `RPA_BLOCKED` 并 audit `rpa.reconciler.pending_too_long`。
     - 扫描 `lead_status_reports.status = PENDING` 计数，仅 audit 一条 `startup_reconciler.outbox_backlog`（具体续投仍由守护线程负责）。
     - 扫描 `friend_check_reports.status = PENDING` 同上。
  2. reconciler 不直接改 `WECHAT_*` 终态、不删数据；只动 `RPA_PENDING_APPROVAL` 一种系统脏态。
  3. reconciler 全程包在 try/except，失败 → audit `startup_reconciler.failed`，但不阻塞 FastAPI 启动。
  4. 单元测试可以通过预置脏数据 + 调用 `reconcile_on_startup` 验证状态翻转。

---

## 第二部分 · 技术设计

### 设计 1 — RISK_FROZEN

**调度器状态机扩展**

```
                 freeze_until reached / unfreeze API
        ┌────────────────────────────────────────┐
        │                                        │
   IDLE ─→ BUSY ─→ COOLDOWN ─→ IDLE              │
        │             │                          │
        │             └──(circuit_break=True)────▼
        └──────────────────────────────────► RISK_FROZEN
                                              (freeze_until: ts)
```

**新增字段（`UpstreamScheduler`）**
- `_freeze_until: float | None`（monotonic time）
- `_freeze_lock: threading.RLock`
- 公开 getter `is_frozen() -> bool`、`get_frozen_remaining_seconds() -> float`

**新增 `Settings` 配置**
- `risk_freeze_seconds: int = 7200`（2h，可配置 60–86400）

**触发路径**
- `RpaOrchestrator._finalize_business_outcome` 当 `outcome.circuit_break=True` 时，除既有 daily_counters 顶满外，**额外**通过 `scheduler.notify_risk_event()` 调用进入 RISK_FROZEN；为避免循环 import，建议在 `upstream_scheduler.py` 暴露一个模块级 `notify_risk_event(scheduler_singleton)` helper，由 `routes/upstream.py: global_scheduler` 提供单例引用，`orchestrator` 通过传入的回调函数注入（在 `UpstreamScheduler._worker_loop` 创建 orchestrator 时 monkey-patch 或经 `orchestrator_factory` 增参传入 callable）。

**期间行为**
- `_worker_loop`：从 `_task_queue.get()` 拿到任务后，检查 `is_frozen()` 为真则把任务**重新放回队列尾**并 `_stop_event.wait(min(remaining, 30))` 后继续循环；这样 RPA_PENDING_APPROVAL 的 lead 在冻结期不会丢。
- `PollingLeadSource.run`：在 fetch 前调 `scheduler.is_frozen()` 检查（需要把 scheduler 引用注入），冻结期间跳过 fetch 但保持循环节拍。
- `_heartbeat_loop`：把 `self.status_state` 替换为 `_compute_status_state()`，冻结期间始终返回 `"RISK_FROZEN"`。

**代码触点**
- `python/backend/app/services/upstream_scheduler.py:99`（status_state 字段初始化）
- `python/backend/app/services/upstream_scheduler.py:260-284`（heartbeat action / loop）
- `python/backend/app/services/upstream_scheduler.py:332-399`（worker loop 顶部判断）
- `python/backend/app/services/upstream_lead_source.py`（fetch 前 is_frozen 检查）
- `python/backend/app/services/rpa_orchestrator.py:341-348`（circuit_break 注入回调）
- `python/backend/app/core/config.py:18`（新增 `risk_freeze_seconds`）

**兼容性 / 迁移**
- 仅扩展枚举值，不破坏既有 HTTP 协议；上游若不识别 `RISK_FROZEN` 心跳 status，建议先与上游同步语义，否则上游一侧仍会读 `BUSY`。
- 单进程内冻结状态保存在内存，**进程重启会丢**——可接受，因为 daily_counters 已经持久化提供等价熔断兜底。

**风险与权衡**
- 选择内存态而非 DB 存 `freeze_until`：简化实现；代价是重启即解冻。若后续运营反馈需持久化，单独在 `upstream_config` 加一行即可，不影响本轮接口。
- 选择"重新入队"而不是丢弃：保持 lead 至少一次投递语义；代价是冻结结束瞬间会有一次集中爆发，由现有 COOLDOWN 节流缓冲。

---

### 设计 2 — lead_status_reports outbox

**数据模型**

```
TABLE lead_status_reports
  lead_id           TEXT NOT NULL,
  job_id            TEXT NOT NULL,
  upstream_status   TEXT NOT NULL,        -- REAL_SENT / BIZ_*  / BIZ_FAILED
  remark            TEXT,
  error_details     TEXT,
  status            TEXT NOT NULL,        -- PENDING / SENT / FAILED
  attempts          INTEGER NOT NULL DEFAULT 0,
  last_error        TEXT,
  payload_json      TEXT NOT NULL,        -- 冗余存原始 JSON，便于排查
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  PRIMARY KEY (lead_id, job_id)
```

**唯一约束选 `(lead_id, job_id)` 而非 `lead_id`**：同一 lead 在 reconciler / 重试场景下会产生多 job（每 job 一份独立汇报），不能让新 job 覆盖旧 job 的 SENT 记录。

**Store 接口（与 friend_check_reports 同构）**
- `enqueue_lead_status_report(lead_id, job_id, upstream_status, remark, error_details, payload, timestamp)` — UPSERT，状态从 SENT 不退回 PENDING。
- `list_pending_lead_status_reports(limit)`
- `mark_lead_status_report_sent(lead_id, job_id, timestamp)`
- `mark_lead_status_report_failed(lead_id, job_id, error, timestamp, *, max_attempts=8)`

**调度器侧**
- `_worker_loop` 在 `_upstream_result_for_job` 算出 `(upstream_status, error_details)` 后，**不再直接** `client.report_lead_status(...)`，而是改为 `store.enqueue_lead_status_report(...)`。
- 新增 `_lead_status_report_loop()` 守护线程，间隔 `lead_status_report_interval_seconds`（默认 30s），实现与 `_friend_check_report_loop` 同构。
- 新增 `trigger_lead_status_report_now()` 与 dev 路由 `/dev/lead-status-report/run`。

**Settings**
- `lead_status_report_interval_seconds: int = 30`
- `lead_status_report_batch_size: int = 20`
- `lead_status_report_max_attempts: int = 8`

**代码触点**
- `python/backend/app/storage/sqlite_store.py:85-95`（init_db schema 增表）
- `python/backend/app/storage/sqlite_store.py:337-450`（参照 friend_check_reports 方法增加四个新方法）
- `python/backend/app/services/upstream_scheduler.py:332-399`（worker loop 写 outbox 而非直接 HTTP）
- `python/backend/app/services/upstream_scheduler.py:286-319`（新增 `_lead_status_report_loop` / `_report_lead_status_once`）
- `python/backend/app/main.py`（无需变更，启动顺序保留）

**兼容性 / 迁移**
- `CREATE TABLE IF NOT EXISTS` 新表自动建；旧库不需要数据迁移。
- 旧调用站点（试探性手动上报、单元测试）需要同步迁移到 enqueue + flush 模式。

**风险与权衡**
- 同步上报改异步会引入"上游短暂晚收到 ≤ 30s"延迟：可接受，上游策略容忍 1 分钟级延迟。
- 失败上限默认 8 次（≈ 4 分钟～若指数退避；本轮**不引入退避**，先 fixed interval）：减少复杂度，遇到上游长时不可用时人工 dev 触发即可。

---

### 设计 3 — RPA 重试前核验

**调用点**

`RpaOrchestrator._run_job` 现状（`rpa_orchestrator.py:146-235`）：

```
for attempt in 0..max_retries:
    try:
        ... 真实加微 ...
    except RpaBusinessOutcome: finalize, return
    except Exception:
        if attempt < max_retries:
            update_step("SYS_ERROR_RETRY: …")
            time.sleep(2.0)
            continue
        fail_job
```

调整为：

```
for attempt in 0..max_retries:
    if attempt > 0:                # 第二次进入循环前
        _precheck_before_retry(lead, update_step)   # 可能抛 RpaBusinessOutcome 或 update_step 落库
    try:
        ... 真实加微 ...
    ...
```

**`_precheck_before_retry` 实现要点**
- 复用 `friend_acceptance.check_friend_acceptance_by_phone` 的搜索 + 读屏路径（已经实现了"只看不点"的语义）；新增一个 `pre_retry=True` 入参，使其
  - 优先 `["ALREADY_FRIEND", "SEND_SUCCESS", "RISK_CONTROL"]` 顺序读屏；
  - 命中后**不写 lead.status**，把状态码原封不动 raise 出来。
- `_run_job` 接到 RpaBusinessOutcome 走既有 `_finalize_business_outcome` 链路。

**新增业务终态码 `BIZ_ALREADY_REQUESTED`**

| 终态码 | LeadStatus | 上游 status | 说明 |
|---|---|---|---|
| BIZ_ALREADY_REQUESTED | WECHAT_ADD_REQUESTED | REAL_SENT | 重试前发现上一次申请已成功发出 |

**`_OUTCOME_LEAD_STATUS` 与 `JOB_STATUS_UPSTREAM_STATUS` 同步**
- `rpa_orchestrator.py:316-321` 增 `'BIZ_ALREADY_REQUESTED': LeadStatus.WECHAT_ADD_REQUESTED`
- `upstream_scheduler.py:28-35` 增 `"REAL_BIZ_ALREADY_REQUESTED": "REAL_SENT"`

**Settings**
- `rpa_retry_precheck_enabled: bool = True`（开关，紧急情况可关闭）
- `rpa_retry_precheck_timeout_seconds: int = 30`

**核验自身失败不阻塞重试的实现**
- `_precheck_before_retry` 内部 try/except，遇到 `WECHAT_NOT_FOUND` / `VERIFY_WINDOW_MISSING` 等系统级错误 → 仅 `update_step("SYS_RETRY_PRECHECK_FAILED: ...")`，不重抛。
- 但若**核验本身**命中 `RISK_CONTROL` 必须重抛——因为这一信号比"继续重试"更重要。

**代码触点**
- `python/backend/app/services/rpa_orchestrator.py:146-235`（_run_job 重试循环）
- `python/backend/app/services/rpa_orchestrator.py:316-321`（终态码映射）
- `python/backend/app/services/friend_acceptance.py:46-151`（新增 pre_retry 入参或抽出 `_search_only_probe` helper）
- `python/backend/app/services/wechat_rpa.py:121-138`（SCREEN_STATE_KEYWORDS 复用，无需改）

**风险与权衡**
- 重试前再次走 UI 增加单 job 时长上限 30~45s：可接受，因为重试本身就是慢路径。
- "对方刚通过申请，OCR 命中 ALREADY_FRIEND" 这种正确分支会落 `BIZ_ALREADY_FRIEND` 并 enqueue friend_check_report —— 与正常路径一致，无副作用。

---

### 设计 4 — HTTP add_wechat per-lead 互斥

**关键决策**：用 SQL 条件 INSERT 实现原子去重，不引入 SELECT-FOR-UPDATE（SQLite 不支持）也不引入 in-process 锁（不跨进程；reconciler 重新拉起就破防）。

**新增 Store 方法 `create_job_if_lead_idle(job, busy_statuses)` 草案**

```
BEGIN IMMEDIATE;
SELECT COUNT(*) FROM rpa_jobs
  WHERE lead_id = :lead_id AND status IN (REAL_QUEUED, REAL_RUNNING,
        SIMULATION_QUEUED, SIMULATION_RUNNING);
-- 若 count > 0 → ROLLBACK，抛 LeadBusyError
INSERT INTO rpa_jobs (...);
COMMIT;
```

SQLite 在 `BEGIN IMMEDIATE` 下持有写锁，等同于互斥；并发请求只会让其中一个事务等待，另一个再读会读到刚插入的行。

**Orchestrator 调用**

`RpaOrchestrator.add_wechat`（`rpa_orchestrator.py:91-126`）的 `self.store.create_job(job)` 替换为：

```
try:
    self.store.create_job_if_lead_idle(job, BUSY_STATUSES)
except LeadBusyError:
    audit.record('rpa.blocked.lead_busy', ...)
    raise AppError('RPA_LEAD_BUSY', '该线索已有进行中的 RPA 任务，请勿重复触发')
```

`LeadBusyError` 定义在 `storage/sqlite_store.py`（新增），是普通 `Exception` 子类。

**HTTP 路由**：FastAPI 默认会把未捕获的 `AppError` 转为 4xx；需要确认 `AppError` 包装时返回 409 而非 400 —— 检查 `python/backend/app/core/errors.py` 现有 `AppError` 是否带 status_code；若没有，在 routes/rpa.py 增加一个具名 except 段把 `RPA_LEAD_BUSY` 转 409。

**代码触点**
- `python/backend/app/storage/sqlite_store.py:162-205`（create_job / update_job 附近）
- `python/backend/app/services/rpa_orchestrator.py:91-126`（add_wechat）
- `python/backend/app/core/errors.py`（确认 AppError 是否能携带 409；如果不能，路由层兼容）
- `python/backend/app/api/routes/rpa.py:23-28`

**兼容性 / 迁移**
- 旧前端如果连点会收到 409 错误而不是默默并发跑：UI 已经有 toast，行为是友好降级。
- DummyOrchestrator 测试需补 LeadBusyError 分支。

**风险与权衡**
- BEGIN IMMEDIATE 在高并发下会让请求排队 50–200ms：本系统单 worker 量级低，可接受。
- 若未来跨进程部署，SQLite 的全局写锁仍然有效；切换 Postgres 时需要换成行级唯一约束。

---

### 设计 5 — acceptance_attempts 上限 + 状态转换

**数据模型**
- `leads` 新增 `acceptance_attempts INTEGER NOT NULL DEFAULT 0`，通过 `ALTER TABLE` 软迁移（参照 `sqlite_store.py:96-100` outcome_type 的写法）。
- `LeadStatus` 新增 `WECHAT_ACCEPTANCE_EXHAUSTED = 'WECHAT_ACCEPTANCE_EXHAUSTED'`，加入 `TERMINAL_LEAD_STATUSES`。

**`FriendAcceptanceService.check_lead` 改造（friend_acceptance.py:164-224）**

```
if lead.status in {WECHAT_ACCEPTED, ...终态}: 短路（与现状相同）
if lead.status != WECHAT_ADD_REQUESTED: raise FRIEND_ACCEPTANCE_NOT_PENDING（现状）

result = checker(...)
attempts = (lead['acceptance_attempts'] or 0) + 1
store.update_lead(lead_id, acceptance_attempts=attempts, updated_at=timestamp)

if result.accepted:                  # ALREADY_FRIEND
    -> WECHAT_ACCEPTED, enqueue friend_check_report(True), audit
elif result.state == 'RISK_CONTROL':
    -> WECHAT_RISK_CONTROL
    enqueue lead_status_report('BIZ_RISK_CONTROL')
    enqueue friend_check_report(False)
    scheduler.notify_risk_event()    # 触发 RISK_FROZEN
elif result.state == 'TARGET_NOT_FOUND':
    -> WECHAT_TARGET_NOT_FOUND
    enqueue lead_status_report('BIZ_TARGET_NOT_FOUND')
elif attempts >= settings.friend_acceptance_max_attempts:
    -> WECHAT_ACCEPTANCE_EXHAUSTED
    enqueue lead_status_report('BIZ_ACCEPTANCE_EXHAUSTED')
# 其他情况保持 WECHAT_ADD_REQUESTED 等下次轮询
```

**Settings**
- `friend_acceptance_max_attempts: int = 12`（默认对应约 1 小时；范围 1–500）

**新增上游状态码 `BIZ_ACCEPTANCE_EXHAUSTED`**
- `JOB_STATUS_UPSTREAM_STATUS` 不需要改（这条不是 job 路径产生的）；
- `lead_status_reports` 直接以 `BIZ_ACCEPTANCE_EXHAUSTED` enqueue。需要与上游对齐文档约定，本轮假设上游已经接受任何 `BIZ_*` 前缀。

**代码触点**
- `python/backend/app/schemas/lead.py:9-24`（新枚举）
- `python/backend/app/storage/sqlite_store.py:24-38, 96-100`（leads schema + ALTER）
- `python/backend/app/services/friend_acceptance.py:164-224`（check_lead 核心改造）
- `python/backend/app/services/upstream_scheduler.py:20-26`（TERMINAL_LEAD_STATUSES 加新终态）
- `python/backend/app/core/config.py:21-22`（新增 max_attempts）

**风险与权衡**
- attempts 写在 `leads` 表上：单表查询、迁移最简单；缺点是字段语义不够强（leads 表本应只描述客户）。备选放在 `friend_check_reports` 上但与 outbox 语义混淆——综合选择 leads。
- 阈值默认 12 是经验值，运营可改；不在范围内做指数退避。
- RISK_CONTROL 直接判 `WECHAT_RISK_CONTROL` 而不"先升 attempts 再升级"：因为复查中 OCR 命中 RISK 已经是高置信度信号，等同业务终态语义。

---

### 设计 6 — 401 自动续签

**选择**：不引入 httpx event hook 拦截器（项目目前用同步 `httpx.post/get`，不是 Client 实例），而是在 `RealUpstreamClient` 内部加一个轻量装饰器 `_call_with_relogin`，把所有 4 个鉴权调用统一包一层。

**实现草案**

```
class RealUpstreamClient:
    def __init__(...):
        self._login_lock = threading.Lock()
        self._token_version = 0          # 用来判定"我看到的 token 是否已被别的线程换过"

    def _call_with_relogin(self, do_request: Callable[[], httpx.Response]) -> httpx.Response | None:
        token_version_at_entry = self._token_version
        try:
            resp = do_request()
        except Exception: return None
        if resp.status_code != 401:
            return resp
        with self._login_lock:
            if self._token_version == token_version_at_entry:
                ok = self._login_locked()
                if not ok: return resp
                self._token_version += 1
        try:
            return do_request()    # 用新 token 重试一次
        except Exception:
            return None
```

`do_request` 由各调用方提供 lambda；`_headers()` 内部读 `self.token` 即可获得续签后的新 token（前提是 do_request 每次调用时都重新构造 headers，不能缓存）。

**`login` → `_login_locked` 拆分**
- 公开 `login()` 仍存在（启动时心跳前需要），内部去拿锁后调 `_login_locked()`。

**代码触点**
- `python/backend/app/services/upstream_client.py:82-168`（整个 Real 类）

**风险与权衡**
- 选择 token 版本号去重而不是单纯锁内重判：避免"持锁线程刚刚续签完，外面无数线程同时重试"——一次续签全员通过。
- 不引入异步 httpx Client：保持现有同步调用最小改动；代价是连接池没有复用——本轮可接受。
- 不处理 4xx 其他错误：仅 401 触发续签，403/422 等仍透传。

---

### 设计 7 — 启动 reconciler

**新增模块 `python/backend/app/services/startup_reconciler.py`** 或直接在 `main.py: startup` 内联（推荐独立文件便于测试）。

**伪流程**

```
def reconcile_on_startup(store, audit, settings) -> dict:
    summary = {pending_lead_blocked: 0, lead_status_outbox_backlog: 0,
               friend_check_outbox_backlog: 0}
    now = utc_now()
    grace_seconds = settings.startup_reconciler_pending_grace_seconds   # default 600

    # 1. RPA_PENDING_APPROVAL 过老 → RPA_BLOCKED
    cutoff = now - grace_seconds 的 ISO 字符串
    rows = SELECT * FROM leads WHERE status='RPA_PENDING_APPROVAL' AND updated_at < cutoff
    for r in rows:
        store.update_lead(r.lead_id, status='RPA_BLOCKED', updated_at=now)
        audit.record('rpa.reconciler.pending_too_long', lead_id=r.lead_id, ...)
        summary['pending_lead_blocked'] += 1

    # 2. 计数 outbox 积压
    summary['lead_status_outbox_backlog'] = count_pending(lead_status_reports)
    summary['friend_check_outbox_backlog'] = count_pending(friend_check_reports)
    if any backlog > threshold:
        audit.record('startup_reconciler.outbox_backlog', data=summary)

    return summary
```

**main.py 集成位置**

```
@app.on_event('startup')
def startup():
    store.init_db()
    audit_logger = AuditLogger(...)

    # ① 先跑 recover_interrupted_jobs（现有）
    for job in store.recover_interrupted_jobs(utc_now()): ...

    # ② 再跑 reconciler（新增）
    try:
        summary = reconcile_on_startup(store, audit_logger, settings)
        audit_logger.record('startup_reconciler.completed', data=summary)
    except Exception as e:
        audit_logger.record('startup_reconciler.failed', message=str(e))

    # ③ 启动 rechecker + scheduler（现有）
```

**Settings**
- `startup_reconciler_enabled: bool = True`
- `startup_reconciler_pending_grace_seconds: int = 600`
- `startup_reconciler_outbox_alert_threshold: int = 20`

**代码触点**
- `python/backend/app/main.py:43-62`（startup 钩子）
- `python/backend/app/services/startup_reconciler.py`（新建）
- `python/backend/app/core/config.py`（新增 3 个 settings）

**风险与权衡**
- reconciler 只清理 `RPA_PENDING_APPROVAL`、不动 `WECHAT_*` 终态：避免误杀合法业务态。
- 600s grace 阈值是保守值，正常调度器一拿到 lead 立刻起 job（< 5s），>10min 还没起说明上次崩溃。
- backlog 仅 audit 不主动续投：守护线程已经覆盖；重复触发会增加 contention，且 reconciler 同步执行会延长 startup 时间。

---

## 第三部分 · 测试清单

### 测试组 1 — RISK_FROZEN

**fixture**：复用 `test_upstream_scheduler.py` 的 `DummyOrchestrator`、`MockUpstreamClient`、`SQLiteStore(tmp)`，新增 helper 注入 `risk_freeze_seconds=2`。

| # | 用例 | 前置 | 触发 | 期望 |
|---|---|---|---|---|
| 1.1 | 风控事件进入冻结 | scheduler.start(); IDLE | `scheduler.notify_risk_event()` | `is_frozen()==True`；status_state=='RISK_FROZEN'；下次 heartbeat payload.status=='RISK_FROZEN' |
| 1.2 | 冻结期间不消费队列 | freeze 已生效 | enqueue 一条 mock lead | `_task_queue` 仍持有该任务；DummyOrchestrator.add_wechat 不被调用 |
| 1.3 | 冻结到期自动解冻 | freeze_seconds=1 已触发 | sleep 1.2s | `is_frozen()==False`，status='IDLE'，队列任务被消费 |
| 1.4 | 重复风控不延长 | 已冻结剩余 1s | 再次 notify_risk_event | freeze_until 不被刷新到 +2s，仍按原 deadline 解冻（或按"刷新"实现明确二选一并锁死语义） |
| 1.5 | dev unfreeze API | 已冻结 | 调 `/dev/scheduler/unfreeze` | `is_frozen()==False`，audit 'scheduler.unfrozen_manual' |

**新增 fixture**：mock orchestrator 注入 `notify_risk_event` 回调。

### 测试组 2 — lead_status_reports outbox

**fixture**：参照 `test_upstream_storage.py`（如未覆盖 friend_check_reports 则新建）。

| # | 用例 | 前置 | 触发 | 期望 |
|---|---|---|---|---|
| 2.1 | enqueue 新报告 | 空表 | `store.enqueue_lead_status_report` | status='PENDING', attempts=0 |
| 2.2 | 重复 enqueue 不覆盖 SENT | 一条 SENT | 再 enqueue 同 (lead, job) | 仍 SENT，attempts/last_error 不变 |
| 2.3 | flush 成功 | 1 PENDING | `_report_lead_status_once` + mock client True | status='SENT'，attempts 不增 |
| 2.4 | flush 失败累计 | 1 PENDING | client 抛异常 | attempts=1, last_error 设置，status='PENDING' |
| 2.5 | 失败上限 → FAILED | attempts=7, max=8 | 失败一次 | attempts=8, status='FAILED' |
| 2.6 | worker_loop 走 outbox 不直接 HTTP | mock client.report_lead_status 监听 | 跑完一个 job | report_lead_status 被守护线程调用，而不是 worker_loop 内 |

**复用**：`MockUpstreamClient.report_lead_status` 已有 print 行为，新增可注入失败模式。

### 测试组 3 — RPA 重试前核验

**fixture**：在 `test_rpa_acceptance_lifecycle.py` 增加新 case；mock `_run_add_request_with_timeout` 与 `_precheck_before_retry` 分别。

| # | 用例 | 前置 | 触发 | 期望 |
|---|---|---|---|---|
| 3.1 | 首次系统错误 + 重试前核验命中 ALREADY_FRIEND | attempt 0 抛 AppError | 进入 attempt 1 | _precheck 抛 BIZ_ALREADY_FRIEND；走 _finalize_business_outcome；lead=WECHAT_ALREADY_FRIEND；enqueue friend_check_report |
| 3.2 | 核验命中 SEND_SUCCESS | 同上 | _precheck 抛 BIZ_ALREADY_REQUESTED | lead=WECHAT_ADD_REQUESTED；upstream status 映射为 REAL_SENT |
| 3.3 | 核验命中 RISK_CONTROL | 同上 | _precheck 抛 BIZ_RISK_CONTROL(circuit_break) | RISK_FROZEN 触发；daily_counter 饱和 |
| 3.4 | 核验自身报错不阻塞重试 | 核验 raise AppError('WECHAT_NOT_FOUND') | 进入 attempt 1 | 实际加微逻辑被调用一次；step 含 'SYS_RETRY_PRECHECK_FAILED' |
| 3.5 | 核验在 attempt=0 不执行 | 正常成功路径 | _run_job 跑通 | _precheck_before_retry 被 mock 但未调用 |

### 测试组 4 — per-lead 互斥

| # | 用例 | 前置 | 触发 | 期望 |
|---|---|---|---|---|
| 4.1 | 第二次 add_wechat 同 lead 报错 | 已有 REAL_QUEUED job | orch.add_wechat 同 lead_id | raise AppError('RPA_LEAD_BUSY') |
| 4.2 | job 终态后允许再次创建 | job=REAL_COMPLETED | orch.add_wechat | 正常创建新 job |
| 4.3 | 跨线程并发 | 起 5 线程同 lead 同时 add_wechat | join | 仅 1 个成功，4 个抛 LEAD_BUSY |
| 4.4 | HTTP 路由返回 409 | 同 4.1 | POST /api/v1/rpa/add-wechat 第二次 | status=409，body.code='RPA_LEAD_BUSY' |

**新增 fixture**：`test_upstream_api.py` 增加 409 断言；线程并发 helper 直接用 `concurrent.futures`。

### 测试组 5 — acceptance_attempts 上限与状态转换

**fixture**：扩展 `test_friend_acceptance.py`，注入可控 `checker`。

| # | 用例 | 前置 | 触发 | 期望 |
|---|---|---|---|---|
| 5.1 | accepted=True attempts 不增 | lead WECHAT_ADD_REQUESTED, attempts=3 | checker 返回 ALREADY_FRIEND | lead=WECHAT_ACCEPTED, attempts 仍=3, enqueue friend_check_report |
| 5.2 | accepted=False attempts +1 | attempts=3 | checker 返回 state=PENDING | attempts=4, lead 保持 WECHAT_ADD_REQUESTED |
| 5.3 | 达到 max → EXHAUSTED | attempts=11, max=12 | checker 返回 PENDING | attempts=12, lead=WECHAT_ACCEPTANCE_EXHAUSTED, enqueue lead_status_report 'BIZ_ACCEPTANCE_EXHAUSTED' |
| 5.4 | RISK_CONTROL 触发熔断 | attempts=3 | checker 返回 state=RISK_CONTROL | lead=WECHAT_RISK_CONTROL, scheduler.notify_risk_event 调用，lead_status_report 入队 |
| 5.5 | TARGET_NOT_FOUND 终态 | attempts=3 | checker 返回 state=TARGET_NOT_FOUND | lead=WECHAT_TARGET_NOT_FOUND, lead_status_report 入队 |
| 5.6 | 短路分支不增 attempts | lead 已 WECHAT_ACCEPTED | check_lead | attempts 不变 |

### 测试组 6 — 401 自动续签

**fixture**：用 `respx` 或 `httpx.MockTransport` 替换 `httpx.post/get`；现有 `test_upstream_client.py` 暂未覆盖 RealUpstreamClient，需新增。

| # | 用例 | 前置 | 触发 | 期望 |
|---|---|---|---|---|
| 6.1 | 401 → 续签后重试成功 | mock /login 返回 200 + token2；/heartbeat 第一次 401，第二次 200 | client.send_heartbeat | 返回 True；login 调一次；heartbeat 调两次 |
| 6.2 | 续签失败透传 False | /login 一直 500 | client.send_heartbeat 收 401 | 返回 False；不死循环；日志含"续签失败" |
| 6.3 | 并发 401 仅触发一次 login | 5 个线程同时收 401 | 各自 send_heartbeat | 全部成功；login mock 只被调用一次 |
| 6.4 | 非 401 不触发续签 | /heartbeat 返回 500 | send_heartbeat | 返回 False；login 未调用 |

### 测试组 7 — 启动 reconciler

| # | 用例 | 前置 | 触发 | 期望 |
|---|---|---|---|---|
| 7.1 | 旧 RPA_PENDING_APPROVAL 转 RPA_BLOCKED | lead.updated_at=1h ago | reconcile_on_startup | lead=RPA_BLOCKED, audit 'rpa.reconciler.pending_too_long' |
| 7.2 | 新 RPA_PENDING_APPROVAL 不动 | lead.updated_at=now | reconcile | lead 保持 RPA_PENDING_APPROVAL |
| 7.3 | outbox 积压告警 | 25 条 PENDING lead_status_reports | reconcile | audit 'startup_reconciler.outbox_backlog' 含 lead_status_outbox_backlog=25 |
| 7.4 | reconciler 异常不阻塞启动 | 注入 store.list 抛错 | startup 钩子 | FastAPI 起来，audit 'startup_reconciler.failed' |
| 7.5 | 与 recover_interrupted_jobs 协同 | 既有 RUNNING job 又有过期 PENDING | startup | 先 RUNNING→FAILED, 再 PENDING→BLOCKED，互不影响 |

### 显式不测的边界

下列场景在本轮**不写测试**，由 P2/P3 单独立项：

- 实际 OCR 误识别率（依赖真实截图，CI 不可重现）。
- 跨进程 scheduler / 多 worker 并发（项目只一个进程一个 worker）。
- `daily_counters` 与 `RISK_FROZEN` 的双重熔断在 freeze 到期且 counters 同时清空的临界点行为（手工运营回退）。
- `RealUpstreamClient` 真实 HTTP 端到端（仅 mock transport，依赖上游模拟器属于 P2）。
- 上游推 `WECHAT_ACCEPTANCE_EXHAUSTED` 后销售端 UI 展示（前端范畴 P2）。
- `BIZ_ALREADY_REQUESTED` 与人工"立即上报"按钮的交互（dev 路径）。
- 401 期间正在收 200 的请求被错配重试（极低概率，单线程模型下不会发生）。

---

## 核心决策摘要

本轮加固以"业务可观测、链路可恢复、风控可隔离"为主线：① RISK_FROZEN 用内存态 + heartbeat 字段把风控从隐式（daily_counters 饱和）升级为显式状态，冻结时长默认 2 小时可配，到期自动恢复；② 新增 `lead_status_reports` outbox 与既有 `friend_check_reports` 同构，主键 `(lead_id, job_id)`，max_attempts=8 由 30s 守护线程续投；③ 重试前核验复用 `friend_acceptance` 路径，命中 `SEND_SUCCESS` 走新增 `BIZ_ALREADY_REQUESTED` 终态；④ per-lead 互斥用 `BEGIN IMMEDIATE` + 条件 INSERT 实现原子去重，HTTP 返回 409；⑤ `acceptance_attempts` 字段放 `leads` 表，达到 12 次默认阈值 → `WECHAT_ACCEPTANCE_EXHAUSTED`，复查中 RISK_CONTROL 直接转 `WECHAT_RISK_CONTROL` 并联动需求 1；⑥ 401 续签用单点 `_login_lock` + token 版本号去重；⑦ 启动 reconciler 仅处理 `RPA_PENDING_APPROVAL` 过期态，outbox 只 audit 不重投。

---

## 第四部分 · 对账与优化清单（plan vs flow）

> 对账时间：2026-06-28
> 对账对象：`docs/tasks/rpa-hardening/plan.md` 设计章节 / 测试清单 vs `docs/tasks/rpa-hardening/flow.md` 实际落地说明

### 总体结论

Cycle 1 / 2 / 3 对应的 7 个需求均已落地：
- Cycle 1：需求 2 / 4 / 6，`lead_status_reports outbox`、per-lead 互斥、401 自动续签。
- Cycle 2：需求 1 / 3，`RISK_FROZEN` 状态机、RPA 重试前核验。
- Cycle 3：需求 5 / 7，`acceptance_attempts` 上限与转态、启动 reconciler。

完整后端测试已通过：
```
$env:PYTHONPATH='.'; uv run pytest backend/app/tests
```

结果：103 passed，4 个 FastAPI `on_event` deprecation warnings。

### 已接受的实现偏差

| 项 | 计划预期 | 实际落地 | 结论 |
|---|---|---|---|
| lead_status_report dev 触发路由 | `/dev/lead-status-report/run` | `/dev/trigger-lead-status-report` | 接受。与既有 friend-check `trigger-*` 命名保持一致。 |
| retry precheck timeout | 配置 `rpa_retry_precheck_timeout_seconds=30` | 配置存在，但未额外包 watchdog | 接受。当前读屏链路已有内部等待/检测超时；如后续发现挂死再补。 |
| `BIZ_ACCEPTANCE_EXHAUSTED` 上游映射 | 直接写 lead_status outbox，不进 job 映射 | 已按此落地 | 接受。该状态不是 RPA job 终态产生，不进入 `JOB_STATUS_UPSTREAM_STATUS`。 |
| startup reconciler outbox 处理 | backlog audit，不主动重投 | 已按此落地 | 接受。重投仍由守护线程负责，避免启动阶段做网络 I/O。 |

### 优化清单

| 优先级 | 项目 | 原因 | 建议处理 |
|---|---|---|---|
| DONE | 补 FastAPI `add_wechat` 路由层 409 端到端测试 | 测试组 4.4 原计划覆盖；当前已有 orchestrator/unit 层覆盖，但缺路由层断言 | 已新增 `test_rpa_api.py::test_add_wechat_route_returns_409_when_lead_is_busy`。 |
| DONE | 补 startup 异常不阻塞测试 | 测试组 7.4 原计划覆盖；当前 `main.py` 已 catch 并 audit，但未单测 startup 钩子异常分支 | 已新增 `test_startup_reconciler.py::test_startup_records_reconciler_failure_without_blocking`。 |
| P2-test | 补 recover_interrupted_jobs 与 reconciler 协同测试 | 测试组 7.5 原计划覆盖；当前代码顺序正确但未单测组合场景 | 构造 RUNNING job + 过期 `RPA_PENDING_APPROVAL`，执行 startup 逻辑或抽 helper 后断言互不影响。 |
| P2-hardening | 终态 job 缺失 lead_status_report 的回填 reconciler | Cycle 1 flow 曾记录“outbox 入队失败仅 log”的恢复问题；最终 plan 设计 7 未纳入该回填 | 后续可扩展 `startup_reconciler`：扫描终态 `rpa_jobs` 且缺 report 的记录，按 `JOB_STATUS_UPSTREAM_STATUS` 回填 outbox。 |
| P3-maint | FastAPI `on_event` deprecation warnings | 完整测试有 4 个弃用警告，不影响当前功能 | 后续迁移到 lifespan，避免 FastAPI 升级时产生维护成本。 |

### 收口状态

功能实现：完成。

测试基线：103 passed。

剩余事项：以上优化清单均非本轮 P0/P1 功能阻塞项，可进入下一轮小步 hardening。

STATUS: REVIEWED_WITH_OPTIMIZATION_LIST


# Cycle 4 · fuzzy_text_hit 核心守卫加固

## 问题背景

当前 `fuzzy_text_hit` 存在三处风险：

1. **短关键词子串误命中**：`"发消息"` / `"已发送"` / `"OK"` / `"添加"` 等短关键词，容易作为子串误命中长文本（如 `"添加朋友"` → 误中 `"添加"`）
2. **full_text 场景 partial_ratio 滑窗假阳性**：`_detect_screen_state` 把整页 OCR 拼接成 `full_text`（几百字）后调用 `fuzzy_text_hit`，此时 `len(clean_text) >> len(clean_kw)`，现有 50% 长度守卫不生效，`partial_ratio` 退化为滑窗找最优局部对齐，极易假阳性
3. **min_ratio 一刀切**：短关键词（≤3字）用 80 分阈值太低，容易误中；长关键词用 80 分合理

## 设计决策

### 1. substring 阶段短关键词边界约束

**方案**：
- 对 `clean_kw` 长度 ≤ 3 的短关键词，在 `full_text`（将由新参数标识）场景下仅做精确子串匹配，不做 partial_ratio
- 在单词块（`item.text`）场景下，保持既有行为

**关键阈值**：`len(clean_kw) ≤ 3` 视为短关键词

### 2. full_text 场景禁用 partial_ratio

**新增参数**：
```python
def fuzzy_text_hit(
    item_text: str,
    keywords: Sequence[str],
    min_ratio: int = 80,
    *,
    allow_fuzzy: bool = True,  # 新增：是否允许 partial_ratio
) -> Optional[str]:
```

**调用方修改**：
- `_detect_screen_state` 中，`full_text` 调用 `fuzzy_text_hit(full_text, keywords, min_ratio=min_ratio, allow_fuzzy=False)`
- `_detect_screen_state` 中，单词块兜底调用保持 `allow_fuzzy=True`
- `VisionLocator._find_first_ocr_track` 中，`fuzzy_text_hit(item.text, keywords)` 保持 `allow_fuzzy=True`（默认）

**向后兼容**：默认 `allow_fuzzy=True`，与当前行为一致，不破坏既有调用

### 3. min_ratio 按关键词长度自适应

**分档规则**：
- `len(clean_kw) ≤ 3`：`min_ratio = 90`
- `4 ≤ len(clean_kw) ≤ 6`：`min_ratio = 85`
- `len(clean_kw) > 6`：`min_ratio = 80`

**显式传参优先级**：如果调用方显式传了 `min_ratio`，则使用该值，不覆盖自适应；但 `allow_fuzzy=False` 时仍禁用 partial_ratio

**调用方检查**：
- `wechat_rpa.py` L201/L205：显式传 `min_ratio=min_ratio`（来自 `_detect_screen_state` 参数）
- `vision_locator.py` L760/L814：使用默认 `min_ratio=80`

## 代码变更清单

| 文件 | 变更 |
|------|------|
| `vision_locator.py` | `fuzzy_text_hit` 新增 `allow_fuzzy` 参数；min_ratio 自适应逻辑 |
| `wechat_rpa.py` | `_detect_screen_state` 中 `full_text` 调用传 `allow_fuzzy=False` |

## 不在本轮范围

- 各业务环节 `state_keys` 顺序重排（RISK_CONTROL 双关键词门槛、SEND_SUCCESS 顺序）
- `SCREEN_STATE_KEYWORDS` 短关键词收紧
- 环节 4 读屏范围收窄、probe 顺序、Y < 55px 阈值
- OCR 意图定位的短关键词误定位（OCR_INTENT_MAP）

## 测试清单

### 新增单测（TestFuzzyTextHit 补充）

| 用例名 | 意图 |
|--------|------|
| `test_allow_fuzzy_false_disables_partial_ratio` | `allow_fuzzy=False` 时即使拼错也不命中（仅子串） |
| `test_allow_fuzzy_true_keeps_ocr_typo_tolerance` | `allow_fuzzy=True` 时仍保持 OCR 拼错容错（回归） |
| `test_min_ratio_adaptive_by_keyword_length` | 短关键词要求更高 min_ratio |
| `test_explicit_min_ratio_overrides_adaptive` | 显式传 min_ratio 覆盖自适应 |
| `test_full_text_with_short_keyword_no_false_positive` | full_text 含短关键词子串但非精确匹配时不命中 |

### 回归验证

- 既有 `TestFuzzyTextHit` 8 个用例全过
- 既有 `TestScreenStateDetection` 用例全过

## STATUS

STATUS: CONVERGED

---

## 加微链路 fuzzy 匹配逻辑 · 完整审计清单

> 2026-06-30 对加微链路 `fuzzy_text_hit` 及各读屏环节做的完整审查。Cycle 4 已落地第 1 类;
> 第 2–7 类为后续 Cycle 的依据,按收益/风险排序。

### 一、fuzzy_text_hit 核心逻辑漏洞(影响所有环节)

| # | 漏洞 | 位置 | 状态 |
|---|---|---|---|
| 1 | **substring 阶段无长度守卫且优先级最高**:短关键词(发消息/已发送/OK/添加)作为子串极易误命中。守卫只加在 partial_ratio 上 | vision_locator.py `fuzzy_text_hit` L187-191 | ✅ Cycle 4 已修(allow_fuzzy 关 full_text 的 fuzzy;substring 本身方向正确) |
| 2 | **full_text 整段走 partial_ratio 滑窗**:`len(text) >> len(kw)`,50% 长度守卫永不触发,退化为滑窗找等长最优局部对齐,假阳性高 | wechat_rpa.py `_detect_screen_state` L201 | ✅ Cycle 4 已修(full_text 调用传 allow_fuzzy=False) |
| 3 | **full_text 无分隔拼接丢失词块边界**:`"".join(w.text)`,相邻词块可能拼出跨边界伪子串 | wechat_rpa.py L190 | ❌ 未修(留后续) |
| 4 | **min_ratio=80 对 partial_ratio 偏低**:短关键词几乎"沾边即命中" | — | ✅ Cycle 4 已修(自适应 ≤3→90/≥4→80) |

### 二、各业务环节漏洞

| 环节 | 位置 | 漏洞 | 状态 |
|---|---|---|---|
| 1 · 搜索结果判定 | wechat_rpa.py L1376 `["RISK_CONTROL","TARGET_NOT_FOUND","ALREADY_FRIEND"]` | ALREADY_FRIEND 关键词过短过通用("发消息"3字/"Message");RISK_CONTROL 优先级最高且代价最大(误熔断当天全部任务),关键词"请稍后再试"/"操作频繁"在网络慢提示下可能误命中。优先级调整只覆盖 ALREADY_FRIEND vs TARGET_NOT_FOUND,RISK_CONTROL 最高优先级未受约束 | ❌ 未修 |
| 2 · 无添加按钮二次判定 | wechat_rpa.py L1389 含 `ADD_REJECTED` | ADD_REJECTED 关键词"需要先添加"/"对方拒绝"在 full_text 滑窗下可能误命中,把"搜不到"误判成"被拒";误命中即截断,走不进 L1400 兜底 | ❌ 未修 |
| 3 · 验证窗缺失二次判定 ⚠️高危 | wechat_rpa.py L1410,命中 SEND_SUCCESS 直接 return success | SEND_SUCCESS 关键词"已发送"(3字)/"等待验证"(4字)在 full_text 极易出现(历史聊天残留);误命中 → 跳过验证语填写却记为成功,客户收不到验证语系统却认为已发送 | ❌ 未修 |
| 4 · 发送后结果确认 ⚠️脏数据源 | wechat_rpa.py L1445,读屏范围 `wx_window`(整个主窗口) | full_text 最脏:主窗口含聊天列表/菜单/最近消息;在这些文本里找"已发送"/"操作频繁"假阳性最高,却作为成功/熔断判定依据 | ❌ 未修 |
| 5 · 重试前 probe | friend_acceptance.py L167 `[..., "SEND_SUCCESS"]` | SEND_SUCCESS 排在 TARGET_NOT_FOUND 之后,flow.md 只修了 ALREADY_FRIEND vs TARGET_NOT_FOUND 顺序;若屏幕残留"搜索结果为空"或 OCR 误读,TARGET_NOT_FOUND 先命中 → 把"已发送申请"误判成"搜不到"。probe 只 sleep 2.0,页面慢时读到上一帧残留 | ❌ 未修 |

### 三、OCR 意图定位环节(坐标定位,非状态判定)

| 漏洞 | 位置 | 状态 |
|---|---|---|
| 短关键词误定位:OCR_INTENT_MAP 中"添加"/"搜索"/"确定"/"发送"/"OK"均 2 字;"OK" substring 命中 book/lookup/token;"发送" in "发送失败" 把错误提示当发送按钮 → 点击错误位置 | vision_locator.py L225-242,调用 L760/L814 | ❌ 未修 |
| 多 intent 共享"添加":wechat_add_button/menu_add_friends/add_to_contacts 都含"添加",命中顺序取决于 template_names 顺序,可能点到错的"添加"控件 | vision_locator.py OCR_INTENT_MAP | ❌ 未修 |
| Y<55 标题栏排除是像素硬编码:高 DPI/缩放下标题栏高度变化,排除失效 → 把验证窗标题当输入框定位,粘贴到错误位置(上一轮"微信卡死"类问题潜在复发点) | vision_locator.py L764/L818 | ❌ 未修 |

### 四、建议(按性价比排序,供后续 Cycle 选用)

1. ~~substring 也加方向正确的长度约束~~ → Cycle 4 已用 allow_fuzzy 间接处理 full_text 路径
2. ~~full_text 整段禁用 partial_ratio~~ → ✅ Cycle 4 已做
3. **短关键词收紧**:ALREADY_FRIEND 去掉裸"发消息"/"Message",改用更长组合或控件上下文;SEND_SUCCESS 去掉裸"已发送",用"好友申请已发送"等更长短语 ← **收益次高**
4. **重排状态优先级**:RISK_CONTROL 不应无条件最高——要求命中 ≥2 个 RISK 关键词或关键词长度 ≥4 才允许熔断;补 SEND_SUCCESS vs TARGET_NOT_FOUND 顺序
5. **环节 4 读屏范围收窄**:发送后判定限定在 Toast/验证窗区域,而非整个主窗口;或要求 SEND_SUCCESS 关键词出现在屏幕中央 ROI
6. **Y<55 改为相对窗口标题栏高度的比例阈值**
7. ~~min_ratio 按关键词长度自适应~~ → ✅ Cycle 4 已做
