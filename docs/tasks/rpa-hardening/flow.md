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

---

## 2026-06-29 · 好友态误判 TARGET_NOT_FOUND 修复

### 现象

- 最新真实任务 `job_b19f7d46d83b` / `lead_4b0c189d81aa` 搜索 `pixel_punk` 后，截图已显示好友资料页，底部存在“发消息 / 语音聊天 / 视频聊天”。
- DB 中该 job 仍被写为 `REAL_BIZ_TARGET_NOT_FOUND`，lead 被写为 `WECHAT_TARGET_NOT_FOUND`。

### 根因

- `_detect_screen_state()` 按传入顺序检测 `["RISK_CONTROL", "TARGET_NOT_FOUND", "ALREADY_FRIEND"]`。
- `TARGET_NOT_FOUND` 关键词包含“搜索结果为空”，`fuzzy_text_hit()` 使用 `rapidfuzz.partial_ratio`，好友资料页 OCR 中的“搜索”会让该关键词得到高分误命中。
- 因为 `TARGET_NOT_FOUND` 排在 `ALREADY_FRIEND` 前面，明确的“发消息”好友态来不及被判定。

### 已落地

- `_detect_screen_state()` 在 `TARGET_NOT_FOUND` 与 `ALREADY_FRIEND` 同时参与时，内部优先检查 `ALREADY_FRIEND`，但保留 `RISK_CONTROL` 的最高优先级。
- 新增回归测试：好友资料页 OCR 同时包含“搜索”和“发消息/语音聊天”时，必须返回 `ALREADY_FRIEND`。

### 验证

```powershell
cd python
$env:PYTHONPATH='.'
uv run pytest backend/app/tests/test_vision_locator.py::TestScreenStateDetection -q
uv run pytest backend/app/tests/test_vision_locator.py backend/app/tests/test_friend_acceptance.py backend/app/tests/test_rpa_acceptance_lifecycle.py -q
```

结果：`9 passed`；相关测试集 `42 passed`。


## 2026-06-29 · partial_ratio 短文本假阳性根治

### 现象

- 在任务 `job_b5810110bdcb` / `lead_dev_mock_1782729826329_0` 中，搜索 `18325661362` 成功找到用户「凡」，并有“添加到通讯录”按钮，但 DB 仍然记录为 `REAL_BIZ_TARGET_NOT_FOUND` / `WECHAT_TARGET_NOT_FOUND`。
- 上一轮调整了判定顺序（`ALREADY_FRIEND` 优先），但在此场景下不含 `ALREADY_FRIEND` 信号。

### 根因

- `_detect_screen_state()` 的单词块匹配兜底逻辑中，OCR 识别出当前页面有搜索按钮的单词 `"搜索"`（2字）。
- 用 `rapidfuzz.partial_ratio` 匹配 `"搜索"` 和 `"搜索结果为空"` 关键词时，短文本在长文本开头对齐成功，得到 100 分直接命中。
- `partial_ratio` 对短文本比关键词短很多的情况（如本案中 33% 长度）会发生反向匹配（本来应该问“关键词是否被子串命中”，结果成了“短词是否是关键词子串”）。

### 已落地

- 在 `vision_locator.py` 的 `fuzzy_text_hit` 中加 **50% 长度比例守卫**：若 OCR 词长不及关键词长度的 50%，则直接跳过 `partial_ratio`，不予判定。
- 新增 `TestFuzzyTextHit` 单元测试类共计 8 个用例，涵盖精确子串命中、空格忽略、大短词误匹配回归、正常相似度拼错容错等测试点。

### 验证

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='python'
python -m unittest backend.app.tests.test_vision_locator.TestFuzzyTextHit -v
```

结果：`8 passed`。完整 `test_vision_locator.py` 的 35 个用例全部通过。


## 2026-06-29 · 验证语填写阶段微信界面卡死修复

### 现象

- 真机测试时，微信进程在进入验证语窗口点击并清空后卡住或未响应，导致后续发送按钮点击引发 COM 异常 `(-2147220991, '事件无法调用任何订户')`。重试时因微信进程死锁导致 `WECHAT_NOT_FOUND`，100% 复现。

### 根因

- 原始 `clear_field()` 使用 `pyautogui` 的低级按键 `Ctrl+A` 紧接着 `Backspace`，然后再过仅 `0.15s` 即发送 `Ctrl+V`，多个键盘事件高频打入，容易造成微信 UIA 反应不及或 `pyautogui` 的 **Modifier Key Stuck（组合键粘滞）**（例如 `Ctrl` 按键在系统底层被误认为一直处于按下状态）。
- 这会导致后续事件序列在微信 UI 线程队列里阻塞甚至卡死崩溃。

### 已落地

- 升级 Windows 操作通道，大幅规避 `pyautogui` 虚拟按键层模拟：
  - 优化 `windows.py` 下的 `clear_field()`, `paste_text()`, `hotkey()`：**优先采用 `uiautomation` 内置的 `SendKeys`**（即走 Windows 原生 `SendInput` API，支持 `{Ctrl}a{BackSpace}` 和 `{Ctrl}v`，带防粘滞处理且无需通过 GUI 剪贴板中转），出错时退回 `pyautogui` 兜底。
  - 加大 `wechat_rpa.py` 中 `_fill_verify_message()` 的时序宽限：清空字段到粘贴的延时由原来的 `0.15s` 大幅延长至 `0.5s`，给微信 UI 渲染留出缓冲。

### 验证

- 运行测试套件：
  ```powershell
  $env:PYTHONIOENCODING='utf-8'
  $env:PYTHONPATH='python'
  python -m unittest backend.app.tests.test_vision_locator -v
  ```
- 结果：`35 passed`，零回归。真机执行加友流程时，清空与粘贴极为流畅，微信不再卡死。


## 2026-06-30 · fuzzy_text_hit 核心守卫加固（Cycle 4）

### 变更总览

按 [plan.md:628-704](plan.md) 实施，核心解决 `fuzzy_text_hit` 的三个风险点：
1. 短关键词子串误命中
2. `full_text` 场景 `partial_ratio` 滑窗假阳性
3. `min_ratio` 一刀切

### 已落地代码变更

#### 1. `vision_locator.py:179-256` - `fuzzy_text_hit` 增强

**新增参数**：`allow_fuzzy: bool = True`（关键字参数，向后兼容）
- `allow_fuzzy=False` 时：完全跳过 `rapidfuzz` 分支，仅做子串匹配
- `allow_fuzzy=True` 时：保持既有行为（先子串，后 partial_ratio）

**min_ratio 自适应**（仅当未显式传值时生效）：
- `len(clean_kw) <= 3` → `min_ratio=90`
- `len(clean_kw) >= 4` → `min_ratio=80`
- 显式传参优先：调用方传了 `min_ratio`（任意值）即直接用该值，不自适应

> 注：首次实现按 plan 写的是 `4-6→85 / >6→80` 三档，且用 `==80` 判定默认值。
> 实跑暴露两处问题后改为 `≤3→90 / ≥4→80` 两档 + sentinel(`None`) 判定，详见下方"Cycle 4 修正"记录。

**与设计的一致性**：
- ✅ `allow_fuzzy` 参数语义完全按设计
- ✅ 显式传参优先：调用方显式传 `min_ratio` 时，不会触发自适应
- ✅ 保留 50% 长度守卫不删除

#### 2. `wechat_rpa.py:200-206` - `_detect_screen_state` 调用点区分

- **full_text 调用（L201）**：`allow_fuzzy=False`，防止长文本滑窗假阳性
- **单词块兜底调用（L205）**：`allow_fuzzy=True`，保持短词容错能力
- **判定顺序**：未变更，仍按传入顺序（仅 `TARGET_NOT_FOUND` 与 `ALREADY_FRIEND` 共存时有内部重排）

#### 3. OCR 意图定位调用点

[vision_locator.py:774](../../../python/backend/app/services/vision_locator.py#L774) / [L828](../../../python/backend/app/services/vision_locator.py#L828)：
- 使用默认 `min_ratio=80`（未显式传参）→ 会走自适应逻辑
- 使用默认 `allow_fuzzy=True` → 保持 OCR 拼错容错

### 新增测试用例

在 `TestFuzzyTextHit` 类中新增：
- `test_allow_fuzzy_false_disables_partial_ratio`：`allow_fuzzy=False` 时 OCR 拼错不命中
- `test_allow_fuzzy_true_keeps_ocr_typo_tolerance`：`allow_fuzzy=True` 时拼错仍命中（回归）
- `test_min_ratio_adaptive_by_keyword_length`：短关键词默认要求更高 min_ratio
- `test_explicit_min_ratio_overrides_adaptive`：显式传值覆盖自适应
- `test_full_text_fuzzy_disabled_direct`：`allow_fuzzy=False` 时长文本仅子串匹配

### 与计划的一致性确认

| 计划项 | 落地状态 |
|--------|----------|
| `allow_fuzzy` 参数（默认 True） | ✅ |
| `full_text` 调用传 `allow_fuzzy=False` | ✅ |
| 单词块调用保持 `allow_fuzzy=True` | ✅ |
| min_ratio 按关键词长度自适应 | ✅ |
| 显式传参优先（包括显式传 80） | ✅ |
| 保留 50% 长度守卫 | ✅ |
| 不碰 state_keys 顺序 / SCREEN_STATE_KEYWORDS | ✅ |

### 验证结果（首次实现）

首次实现后实跑暴露 2 个失败（见下方"Cycle 4 修正"），本节为首次实现状态记录，最终通过结果以修正记录为准。

STATUS: NEEDS_ITERATION（Cycle 4 首次）

---

## 2026-06-30 · fuzzy_text_hit 测试失败修复（Cycle 4 修正）

### 问题概述

上一轮 Cycle 4 提交后实跑测试，发现 2 个失败：
1. `test_explicit_min_ratio_overrides_adaptive`：显式传 `min_ratio=80` 被误判为默认值走自适应
2. `test_fuzzy_match_ocr_typo`：6字关键词自适应到 85，导致真实 OCR 拼错（83分）不命中

### 根因分析

**失败1根因**：用 `effective_ratio == 80` 判断是否为默认值，调用方显式传 `80` 也会命中，被误判为未传值走自适应。

**失败2根因**：原计划的自适应分档 `4-6→85` 过严，`"添加到涌讯录"` vs `"添加到通讯录"` partial_ratio≈83 < 85，导致既有测试回归。

### 已落地修复

#### 1. `vision_locator.py:179-231` - sentinel 值区分显式/默认

**签名变更**：
```python
def fuzzy_text_hit(
    item_text: str, keywords: Sequence[str], min_ratio: Optional[int] = None, *, allow_fuzzy: bool = True
) -> Optional[str]:
```

**自适应逻辑修正**：
- `min_ratio is None` → 走自适应（未显式传参）
- `min_ratio is not None` → 直接用该值（包括显式传 `80`）

**自适应分档放宽**：
- `len(clean_kw) <= 3` → `min_ratio=90`（保持，防短关键词假阳性）
- `len(clean_kw) >= 4` → `min_ratio=80`（取消原 4-6→85，保留 OCR 容错能力）

**向后兼容**：
- 调用方不传 `min_ratio` → `None` → 自适应（行为与原默认 `80` 一致，但对短关键词更严）
- 调用方传 `min_ratio=80` → 直接用 80（不再误触发自适应）

#### 2. `test_vision_locator.py:798-810` - 测试用例预期值修正

实际验证发现：`"搜素"` vs `"搜索"` rapidfuzz.partial_ratio≈67，而非测试注释假设的 85。
- `test_explicit_min_ratio_overrides_adaptive`：显式传值从 `80` 改为 `60`，与实际评分匹配
- `test_min_ratio_adaptive_by_keyword_length`：更新注释，注明实际 partial_ratio≈67

### 验证结果

**完整测试输出**（实跑，2026-06-30）：
```
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH='.'
uv run pytest backend/app/tests/test_vision_locator.py -q
=> 40 passed in 0.52s

uv run pytest backend/app/tests/test_friend_acceptance.py backend/app/tests/test_rpa_acceptance_lifecycle.py backend/app/tests/test_risk_frozen_and_retry_precheck.py -q
=> 28 passed in 1.58s
```

**覆盖范围**：
- ✅ `test_fuzzy_match_ocr_typo`：6字关键词自适应到 80，83分命中（回归修复）
- ✅ `test_explicit_min_ratio_overrides_adaptive`：显式传 `60` 覆盖自适应（原 80 因实际评分≈67 不足改为 60）
- ✅ `test_min_ratio_adaptive_by_keyword_length`：不传 min_ratio 时 2 字关键词自适应到 90，67 分不命中
- ✅ `test_allow_fuzzy_false_disables_partial_ratio` / `test_full_text_fuzzy_disabled_direct`：full_text 路径仅子串
- ✅ 其余用例零回归；关联 RPA 链路测试集 28 passed 零回归

STATUS: READY_FOR_REVIEW


## 2026-06-30 · 加微第一步 cached_vision 几何阈值误杀加号（链路拆解·加号定位）

> 按"加微链路逐步拆解"思路审视第一步「找到添加 + 按钮」，发现 cached_vision
> 主路径在"加号偏左"布局下被几何阈值误杀，降级到 search_anchor 慢路径。
> 本节为代码现状记录，对账见下方根因。

### 链路还原

`_open_add_friends_entry`([wechat_rpa.py:943](../../../python/backend/app/services/wechat_rpa.py#L943)) 点加号三层兜底：
1. **cached_vision**（主路径，模板/缓存，threshold=0.85，拒绝 OCR 命中）→ 命中即点
2. **search_anchor**（兜底1，OCR 找"搜索"→ 右侧 ROI 模板匹配加号 → header 模板 0.90）
3. 三层失败 → 抛 `ADD_PLUS_NOT_FOUND`

### 现象

audit log（`rpa_jobs.steps_json`）实证 2 个真实 job 全部 `ADD_PLUS_CACHED_VISION_MISS`，每次走 search_anchor 慢路径。`ADD_FRIENDS_PAGE_OPENED_BY_MENU_OFFSET`（+86 偏移）0/2 触发——菜单项模板 `menu_add_friends.png` score=1.000 稳定，+86 盲点是低频死兜底。

### 根因（三轮真机实测 + job 实证锁定）

cached_vision 的 x 几何约束原为 `local_x < width*0.35` 即拒（[wechat_rpa.py:936](../../../python/backend/app/services/wechat_rpa.py#L936)）。
加号在微信主窗口的相对 x **随内部布局浮动**（左侧导航栏/聊天列表宽度、搜索框是否展开），不随 DPI、不随窗口宽度单一决定：

| 场景 | 窗口宽 | DPI | 加号 center | local_x | ratio | 改前 0.35 |
|---|---|---|---|---|---|---|
| job 实证（偏左布局） | 1118 | 1.25 | 606 | 352 | 0.315 | **拒 → MISS** |
| 真机实测（偏右布局） | 1118 | 1.25 | 876 | 622 | 0.556 | 放行 |

同尺寸同 DPI，加号 ratio 从 0.31 到 0.56 浮动。0.35 这个绝对比例阈值扛不住布局变化——加号偏左（ratio<0.35）就被误判成"非加号区"拒掉，cached_vision 返回 None，降级 search_anchor。

### 已落地

[wechat_rpa.py:936](../../../python/backend/app/services/wechat_rpa.py#L936) x 下限 `0.35 → 0.18`，与 search_anchor 的 header 模板下限（`width*0.18`）对齐，统一两条路径几何标准。

- 改后：偏左布局（ratio=0.315）放行，cached_vision 直接缓存命中点加号，不再走慢路径
- 安全性不变：`top_limit`（仅顶部 22%）+ `threshold=0.85` + 拒绝 OCR 命中 三重保护，聊天列表在 y>top_limit 段不误点
- 多 DPI/分辨率适配：阈值是相对比例，等比缩放下行为一致

### 验证

新增 `TestCachedAddButtonGeometry` 6 个用例（[test_vision_locator.py](../../../python/backend/app/tests/test_vision_locator.py)）：
- 偏左布局（job 真实坐标 center=606）放行并点击 — 回归保护
- 偏右布局（实测 center=876）放行
- 极左（ratio<0.18）/ 极右（ratio>0.75）/ 过低（y>顶部22%）仍拒
- OCR 命中仍拒

```
uv run pytest backend/app/tests/test_vision_locator.py backend/app/tests/test_friend_acceptance.py backend/app/tests/test_rpa_acceptance_lifecycle.py backend/app/tests/test_risk_frozen_and_retry_precheck.py -q
=> 74 passed（原 68 + 新 6），零回归
```

### 推翻的中间推断（留档供复盘）

- ❌ "DPI 决定"：1.25 DPI 下两次同尺寸结果不同（ratio 0.315 vs 0.556）
- ❌ "窗口宽度决定"：同宽度两次结果不同
- ✅ "微信内部布局决定加号相对位置" + 0.35 绝对阈值 → 偏左布局误杀

STATUS: READY_FOR_REVIEW（链路拆解·加号定位）


## 2026-06-30 · 菜单"添加朋友"偏移兜底多 DPI 适配 + 点完校验（链路拆解·菜单项）

### 链路还原

`_open_add_friends_entry` 第二步([wechat_rpa.py:971](../../../python/backend/app/services/wechat_rpa.py#L971))：
- 主路径：`vision.click_first(["menu_add_friends","add_friends_menu_item"])` 模板/缓存匹配菜单项
- 兜底：模板失败 → 加号位置正下方 +86px 盲点

### 现象

audit 实证 2/2 真实 job 主路径 `cache_menu_add_friends.png score=1.000` 命中，+86 偏移 0/2 触发（死兜底）。
但 +86 是绝对像素，多 DPI 下不准。

### 根因（1.0 / 1.25 双 DPI 真机实测）

实测"添加朋友"菜单项相对加号的 y 偏移：

| DPI | 加号 center_y | 菜单项 center_y | 真偏移 | 86×dpi_scale |
|---|---|---|---|---|
| 1.0 | 180 | 266 | **86** | 86 |
| 1.25 | 184 | 289 | **105** | 107.5 |

原 +86 是 1.0 DPI 下的真实值（作者当年在 1.0 下量的）。菜单浮层由微信按当前 DPI 渲染，偏移等比缩放：
`偏移 = 86 × dpi_scale`。原硬编码在高 DPI 下偏小（1.25 差 19px、1.5 差 43px），会点到上方"发起群聊"。

### 已落地（A + B）

[wechat_rpa.py:979-1011](../../../python/backend/app/services/wechat_rpa.py#L979)：

**A. 偏移按 DPI 缩放**：
```python
dpi_scale = get_ocr_adapter().get_dpi_scale(WindowHandle(native_id=wx_window.native_id))
offset_px = max(20, round(86 * dpi_scale))
fallback_y = min(match.center_y + offset_px, bottom - 20)
```
- `max(20, ...)` 防异常 DPI 回退时 0 偏移点到加号自身
- `min(..., bottom-20)` 防越出窗口底部

**B. 点完校验**：
```python
_sleep(0.8)
if _find_add_friends_window_fast() is None:
    raise AppError("ADD_FRIENDS_MENU_OFFSET_MISS", ...)
```
偏移点击后用现成的 `_find_add_friends_window_fast()`（0s 即时探测）确认"添加朋友"窗口弹出。点偏（如点到"发起群聊"）不再静默继续、下游归因错位，而是抛明确错误。

### 验证

新增 `TestAddFriendsMenuOffset` 6 用例（[test_vision_locator.py](../../../python/backend/app/tests/test_vision_locator.py)）：
- 1.0/1.25/1.5 DPI 偏移分别 = 86/108/129（锁死多 DPI 回归）
- 偏移 clamp 到窗口底部
- DPI 异常回退时偏移 ≥20
- 校验失败抛 `ADD_FRIENDS_MENU_OFFSET_MISS`，不静默继续

```
uv run pytest backend/app/tests/test_vision_locator.py backend/app/tests/test_friend_acceptance.py backend/app/tests/test_rpa_acceptance_lifecycle.py backend/app/tests/test_risk_frozen_and_retry_precheck.py -q
=> 80 passed（原 74 + 新 6），零回归
```

### 顺带发现（留作下一拆解点）

1.0 DPI 实测时 cached_vision 又 MISS（改 0.18 后仍 MISS），原因是 **1.0 DPI 下无缓存目录**（`templates_cache/` 只有 `1920x1080_1.25_*`），且原始 `wechat_add_button.png` 模板在 1.0 渲染下未匹配。这是 cached_vision 冷启动 + 多 DPI 模板缺失问题，留待下一环节深挖。

STATUS: READY_FOR_REVIEW（链路拆解·菜单项）
