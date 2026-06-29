# project-closure-audit 功能流程文档

> 本文只记录当前代码事实。目标任务线目录在本次阅读前不存在；`state.md` 与既有 `flow.md` 均未读到，因此以下内容从源码入口和调用链追踪生成。

## 0. 运行入口与整体拓扑

- 前端是 Vite + React 19 + TanStack Query + Zustand：`package.json:5-10` 定义 `dev/build/tauri` 脚本，`package.json:11-30` 记录 React、Tauri API、React Query、Zustand 依赖。
- 浏览器入口：`src/main.tsx:7-13` 将 `<App />` 挂到 `#root`，外层包 `QueryClientProvider`，React StrictMode 开启。
- Tauri 入口：`src-tauri/src/main.rs:3-5` 调用 Rust 库 `wechat_rpa_desktop_lib::run()`；`src-tauri/src/lib.rs:480-599` 构建 Tauri App、注册 commands、启动 Python sidecar、退出时杀进程并尽力上报 terminal offline。
- Python 本地 API 入口：`python/backend/app/main.py:23-27` 创建 FastAPI app，`python/backend/app/main.py:37-42` 挂载 health/leads/rpa/friend_acceptance/audit/upstream 路由。
- 本地数据目录：开发环境下 `python/backend/app/core/paths.py:19-34` 使用 `python/backend/data`；打包环境下使用 exe 同级 `data`。SQLite 与 audit jsonl 路径由 `python/backend/app/core/config.py:51-59` 映射到该数据目录。

## 1. 前端登录、入口、路由与视图组织

### 1.1 登录门禁

- `src/App.tsx:29-43` 从 `useAuthStore` 取登录态，首屏 `initialize()` 恢复会话。
- `src/App.tsx:120-130` 在 `status === "checking"` 时显示校验登录状态。
- `src/App.tsx:132-255` 未认证时显示 Portal 登录页，支持密码与短信两种模式：
  - 手机号格式由 `src/App.tsx:18-24` 的 zod schema 校验。
  - 密码登录分支在 `src/App.tsx:67-75`，密码不足 6 位前端直接报错。
  - 短信登录分支在 `src/App.tsx:75-81`，验证码不足 4 位前端直接报错。
  - 获取验证码在 `src/App.tsx:96-118`，成功后 60 秒倒计时。
- 认证成功后 `src/App.tsx:257-263` 渲染 `AppShell`、`StatusBar` 和 Toast 容器。

### 1.2 Portal/Tauri 登录调用链

- 前端 store：`src/stores/useAuthStore.ts:90-107` 调用 Tauri command `portal_get_session`；`src/stores/useAuthStore.ts:109-122` 调用 `portal_login_password`；`src/stores/useAuthStore.ts:124-137` 调用 `portal_login_sms`；`src/stores/useAuthStore.ts:139-148` 调用 `portal_send_sms_code`；`src/stores/useAuthStore.ts:150-157` 调用 `portal_logout`。
- Rust Portal API base：`src-tauri/src/lib.rs:64-69` 从 `AISALES_PORTAL_API_BASE` 读取，默认 `http://aisales-portal.app.qa.internal.weimob.com/api/v1`。
- 登录请求：`src-tauri/src/lib.rs:252-272` 将 payload POST 到 Portal，规范化 user，保存 session；密码路径 `src-tauri/src/lib.rs:310-322` 调 `auth/login`，短信路径 `src-tauri/src/lib.rs:324-336` 调 `auth/login-by-sms`。
- Session 持久化：`src-tauri/src/lib.rs:82-97` 定位 `app_data_dir/portal-session.json`；`src-tauri/src/lib.rs:162-174` 写入；`src-tauri/src/lib.rs:176-193` 读取；`src-tauri/src/lib.rs:195-205` 清除。
- Session 恢复：`src-tauri/src/lib.rs:354-388` 读取本地 session 后调用 Portal `/auth/me` 校验；401 会删除本地 session 并返回 `None`。
- 错误处理：`src-tauri/src/lib.rs:207-250` 对非 2xx Portal 响应提取 JSON `message`，401 归一为 `UNAUTHORIZED`；前端 `src/stores/useAuthStore.ts:39-54` 将错误转成人类可读文案，并对“该手机号未注册”改写提示。

### 1.3 前端 hash 路由与页面组织

- 路由定义集中在 `src/components/layout/Sidebar.tsx:6-12`：`/dashboard` 系统看板、`/accounts` 账号管理、`/risk` 风控管理、`/upstream` 上游对接、`/test` 开发测试。
- `src/hooks/useHashRoute.ts:47-90` 用 URL hash 管理路由和 query，空 hash 会在 `src/hooks/useHashRoute.ts:63-67` 写入默认路由；`setQuery()` 会保留当前 path 并合并/删除 query。
- `src/components/layout/AppShell.tsx:4-8` lazy-load 五个页面组件。
- `src/components/layout/AppShell.tsx:22-29` 建立 hash 路由、线索/统计/审计查询和 RPA mutation。
- `src/components/layout/AppShell.tsx:65-103` 根据 activePath 渲染页面；未知 route 回退为 `/dashboard`。
- `src/components/layout/Sidebar.tsx:48-75` 用 `<a href="#/path">` 展示菜单，同时拦截 click 调 `onNavigate()`；退出按钮 `src/components/layout/Sidebar.tsx:80-82` 调 `logout`。
- `src/components/layout/StatusBar.tsx:7-24` 每 5 秒 GET `/api/v1/health`，成功显示 RPA 引擎已连接并展示今日额度，失败显示断开；文案固定显示 `Port 8000`，没有读取动态端口。

## 2. 前端本地 API、hooks/store 与持久化边界

### 2.1 本地 API client

- `src/lib/api.ts:2-16` 缓存本地 token；Tauri 环境下通过 `invoke("get_security_token")` 获取，失败或非 Tauri 环境回退为硬编码 `dev-local-token`。
- `src/lib/api.ts:24` 将 `LOCAL_API_BASE` 固定为 `http://127.0.0.1:8000`。
- `src/lib/api.ts:26-52` 所有 fetch 默认带 `Content-Type: application/json` 与 `Authorization: Bearer <token>`；401 时清空 token cache；非 2xx 抛 `API Error <status>: <body>`；成功总是 `response.json()`。
- SSE job 事件因 EventSource 不能带 Authorization，`src/hooks/useJobSnapshot.ts:79-90` 使用 fetch + stream reader 访问 `/api/v1/rpa/jobs/{jobId}/events` 并带 Authorization。
- 上游日志 SSE 是例外：`src/components/features/UpstreamConfig.tsx:27-35` 直接 `new EventSource(`${LOCAL_API_BASE}/api/v1/upstream/logs`)`，没有 Authorization header；后端该路由当前也没有 `require_auth` 依赖。

### 2.2 React Query hooks

- 线索列表：`src/hooks/useLeads.ts:17-25` 查询 `/api/v1/leads`，8 秒轮询；`src/hooks/useLeads.ts:28-39` 将 `lead_id/account/phone_masked/customer_name` 归一到 `id/phone/name`。
- 添加线索：`src/hooks/useLeads.ts:41-53` POST `/api/v1/leads`，成功 invalidate `leads`。
- RPA precheck：`src/hooks/useLeads.ts:55-67` POST `/api/v1/rpa/precheck`，成功 invalidate `leads`。
- 审计流：`src/hooks/useAudits.ts:13-18` 查询 `/api/v1/audit`，8 秒轮询。
- 看板 RPA 触发：`src/hooks/useAudits.ts:21-43` POST `/api/v1/rpa/add-wechat`，body 固定 `{ lead_id, dry_run: true }`，成功 invalidate `leads/audits` 并 `registerJobStarted()`。
- 统计：`src/hooks/useLeadsStats.ts:12-21` 查询 `/api/v1/leads/stats`，8 秒轮询，不重试。
- Job 快照：`src/hooks/useJobSnapshot.ts:41-50` 先 GET `/api/v1/rpa/jobs/{jobId}` 作为兜底；`src/hooks/useJobSnapshot.ts:52-147` 开 SSE；`src/hooks/useJobSnapshot.ts:6-14` 认为 `SIMULATION_COMPLETED/REAL_COMPLETED/FAILED/REAL_BIZ_*` 是终态。

### 2.3 Zustand store

- Auth store 不持久化到 localStorage；会话由 Rust 写 `portal-session.json`，见 `src/stores/useAuthStore.ts:84-158` 与 `src-tauri/src/lib.rs:82-205`。
- `src/stores/useAuthStore.ts:56-82` 在每次 `applySession()` 后 fire-and-forget 调 `terminal_initialize`，用模块变量 `lastInitializedToken` 避免 StrictMode 或重复恢复导致 terminal record/status 重复上报。
- 开发测试 store：`src/stores/useDevTestStore.ts:51-97` 以 `wechat_rpa_dev_test` 持久化 testJobId/testLeadId/jobFinished/lastSnapshot/formDraft，保留刷新后的任务展示和表单草稿。
- 看板 job store：`src/hooks/useLeadJobs.ts:63-167` 以 `wechat_rpa_lead_jobs` 持久化 lead→job 映射、job meta 和 snapshots；`src/hooks/useLeadJobs.ts:50-51` 声称每条 lead 只保留最近 5 个 snapshot，但实际清理逻辑在 `src/hooks/useLeadJobs.ts:94-101` 只在 `appendJob()` 时删除不在当前 lead 最新 5 个 job 的 snapshot，可能误删其他 lead 的 snapshot。
- 上游 store：`src/stores/useUpstreamStore.ts:34-124` 不持久化；配置从后端 `/api/v1/upstream/config` 取，状态从 `/api/v1/upstream/status` 取，开发触发按钮异常只写本地 logs。

## 3. 前端功能模块事实

### 3.1 线索看板

- 页面入口：`src/components/features/LeadsDashboard.tsx:14-17` 仅转发到 `LeadsBoard`。
- 看板结构：`src/components/features/board/LeadsBoard.tsx:70-95` 顶部 KPI，主体线索列表，详情抽屉。
- 数据来源：AppShell 将 `useLeadsQuery(true)`、`useLeadsStatsQuery()`、`useAuditLogsQuery()` 结果传入 `LeadsDashboard`，见 `src/components/layout/AppShell.tsx:25-28` 与 `src/components/layout/AppShell.tsx:80-87`。
- KPI：`src/components/features/board/KpiStrip.tsx:13-18` 优先使用后端 stats，否则用前端 `countLeadsByStatus()`；成功率为 `success/total`，见 `src/components/features/board/KpiStrip.tsx:19-21`。
- 列表：`src/components/features/LeadsList.tsx:17-76` 展示 account/remark/status；空状态提示去开发测试页发起模拟线索；列表项点击打开抽屉。
- 字段展示：`src/lib/leadDisplay.ts:17-24` account 优先 `account → phone → phone_masked → id → lead_id`，remark 优先 `remark → add_reason → customer_name → name`，且 remark 与 account 相同时不展示。
- 抽屉路由状态：`src/components/features/board/LeadsBoard.tsx:31-35` 从 hash query 读取 `lead/tab/job`；`src/components/features/board/LeadsBoard.tsx:41-49` 点击行时把最新 job 写入 query；`src/components/features/board/LeadsBoard.tsx:51-58` 关闭时清空 query。
- 详情抽屉：`src/components/features/board/LeadDetailDrawer.tsx:37-49` 从持久化 job store 找 lead 的 job 列表和最新 job；没有 jobId 时默认选最新；`src/components/features/board/LeadDetailDrawer.tsx:58-83` 有 overview/process/history 三个 tab。
- 看板触发 RPA：`src/components/layout/AppShell.tsx:31-57` 调 `executeRpa.mutate(leadId)`；成功后设置 activeJobId、toast，并把 URL query 写成 `lead/tab=overview/job`。

### 3.2 登录与账号管理

- 登录流程见 §1.1/1.2。
- 账号页：`src/components/features/AccountManagement.tsx:24-40` 展示当前用户信息，并调用 Tauri `get_security_token` 展示本地 API 令牌，失败则显示 `test_token`。
- 账号页密码修改：`src/components/features/AccountManagement.tsx:52-59` 实际不调用任何后端，只 toast 提醒前往 Web Portal，并 reset 表单。
- Token 复制：`src/components/features/AccountManagement.tsx:61-64` 将当前页面持有 token 写剪贴板。

### 3.3 开发测试页

- 批量 mock 上游线索：`src/components/features/DevTesting.tsx:143-198` 校验每行 lead_id/phone/customer_name/greeting，confirm 后 POST `/api/v1/upstream/dev/seed-mock-leads`；成功 toast 显示 seeded 与 accepted_by_scheduler。
- 手动加友测试：`src/components/features/DevTesting.tsx:408-502`：真实模式先 confirm；然后依次：
  1. `src/components/features/DevTesting.tsx:421-430` POST `/api/v1/leads` 创建测试线索。
  2. `src/components/features/DevTesting.tsx:432-435` POST `/api/v1/leads/{lead_id}/call-start`。
  3. `src/components/features/DevTesting.tsx:437-447` POST `/api/v1/leads/{lead_id}/call-summary`，强制 customer_consent/sales_confirmed_call 为 true。
  4. `src/components/features/DevTesting.tsx:449-459` POST `/api/v1/rpa/add-wechat`，body 含 greeting、dry_run、human_approval。
  5. `src/components/features/DevTesting.tsx:461-470` 成功后 registerJobStarted 并写入 `useDevTestStore`。
- 开发测试页任务反馈：`src/components/features/DevTesting.tsx:695-701` 用 `JobProgress` 展示当前 job；`src/components/features/JobProgress.tsx:10-57` 使用 `useJobSnapshot()`，显示状态 badge、jobId 和步骤。
- 开发测试页审计：`src/components/features/DevTesting.tsx:237-247` 按 `lead_id` 查询 `/api/v1/audit?lead_id=...&limit=200`，8 秒轮询；`src/components/features/DevTesting.tsx:926-952` 前端倒序展示。
- 好友通过模拟：`src/components/features/DevTesting.tsx:266-290` 对待通过 lead POST `/api/v1/friend-acceptance/dev/simulate-accepted`；`src/components/features/DevTesting.tsx:356-401` 也支持输入 account/customer_name 创建“已是好友”测试线索，必要时立即触发 `/api/v1/upstream/dev/trigger-friend-check-report`。
- 待对账清理：`src/components/features/DevTesting.tsx:315-354` 把所有 `WECHAT_ADD_REQUESTED` 清到 `RPA_BLOCKED`。

### 3.4 上游配置页

- `src/components/features/UpstreamConfig.tsx:19-25` 挂载后拉配置和状态，并每 5 秒刷新状态。
- `src/components/features/UpstreamConfig.tsx:27-35` 建立上游日志 EventSource，收到 message 后写 store logs。
- `src/components/features/UpstreamConfig.tsx:67-126` 配置项为 upstream_mode、upstream_api_url、client_id、client_secret；radio change 或 input blur 即 `saveConfig()`。
- `src/stores/useUpstreamStore.ts:59-76` 保存配置会 POST `/api/v1/upstream/config`，然后更新本地 config 和 scheduler_alive。
- 状态卡：`src/components/features/UpstreamConfig.tsx:135-158` 展示 scheduler_alive、wechat_online、调度器状态与队列数；前端 `UpstreamStatus.state` 类型仅声明 `IDLE | BUSY | COOLDOWN`，但后端可能返回 `RISK_FROZEN`。
- 开发按钮：`src/components/features/UpstreamConfig.tsx:181-185` 触发 fetch、heartbeat、clear queue。

### 3.5 风控页与健康栏

- 风控页加载配置：`src/components/features/RiskControl.tsx:23-36` GET `/api/v1/health`，读 daily_limit/min_interval/max_interval。
- 保存风控：`src/components/features/RiskControl.tsx:38-55` POST `/api/v1/health/settings`，只更新进程内 settings，没有写 `.env` 或 SQLite。
- 风控审计流：`src/components/features/RiskControl.tsx:57-60` 从 AppShell 传入 audits 里过滤 `event_type` 包含 `blocked` 或 `limit`，或 `result === failed`。
- 状态栏：`src/components/layout/StatusBar.tsx:7-24` 每 5 秒 health polling，仅以请求成功/失败判定引擎连接。

## 4. Tauri / 本地 API / dynamic port 事实

### 4.1 Python sidecar 启动与端口

- Tauri setup：`src-tauri/src/lib.rs:496-551` 在应用启动时定位 Python 源码目录，执行 `uv run uvicorn backend.app.main:app --port 8000 --host 127.0.0.1`。
- Windows 上启动前：`src-tauri/src/lib.rs:274-300` 通过 `netstat -ano -p tcp` 找监听指定端口的 PID 并 `taskkill /F`；实际调用固定为 `kill_existing_backend_on_port(8000)`，见 `src-tauri/src/lib.rs:529-530`。
- sidecar 环境变量：`src-tauri/src/lib.rs:542-543` 设置 `LOCAL_SECURITY_TOKEN=<随机 token>` 与 `PYTHONPATH=<python dir>`。
- 进程持有：`src-tauri/src/lib.rs:545-548` spawn 后放入 `AppState.python_process`。
- 退出清理：`src-tauri/src/lib.rs:552-585` 窗口 Destroyed 时先尽力 terminal offline，然后 kill Python child。
- 当前代码不存在动态端口协商：前端 `src/lib/api.ts:24`、状态栏 `src/components/layout/StatusBar.tsx:33`、Tauri `src-tauri/src/lib.rs:530-540` 均固定 8000。文档要求关注 dynamic port，但代码事实是固定端口，并且启动前会杀占用 8000 的进程。

### 4.2 本地 API 鉴权与边界

- Rust 启动生成随机 token：`src-tauri/src/lib.rs:481-487` 生成 `local_tok_<uuid>`；`src-tauri/src/lib.rs:305-308` 暴露 `get_security_token`。
- Python 启动覆盖 token：`python/backend/app/main.py:17-22` 读取 `LOCAL_SECURITY_TOKEN` 后覆盖 `settings.api_token`。
- Python 鉴权：`python/backend/app/core/security.py:39-43` 要求请求来源是 `127.0.0.1/::1/localhost/testclient`；`python/backend/app/core/security.py:45-53` 要求 Authorization 精确等于 `Bearer {settings.api_token}`。
- 已加鉴权的路由：leads `python/backend/app/api/routes/leads.py:7`，rpa `python/backend/app/api/routes/rpa.py:11`，friend_acceptance `python/backend/app/api/routes/friend_acceptance.py:19-23`，audit `python/backend/app/api/routes/audit.py:7`。
- 未加鉴权的路由：health `python/backend/app/api/routes/health.py:20-57`、upstream 整个 router `python/backend/app/api/routes/upstream.py:14` 下的 config/status/dev/logs 均无 `Depends(require_auth)`。
- 前端普通请求都会带 token（`src/lib/api.ts:31-40`），但 EventSource logs 不带 token（`src/components/features/UpstreamConfig.tsx:27-35`）。

### 4.3 Terminal/MGR 上报

- 登录后前端 `src/stores/useAuthStore.ts:63-82` 调 `terminal_initialize`，且失败不阻断登录。
- Rust 后端也防重复：`src-tauri/src/lib.rs:433-447` 若同 token 且已有 manager，跳过 record/status。
- `src-tauri/src/lib.rs:462-475` 加载或创建 terminal identity，构建 `MgrClient`，spawn `manager.initialize(token, tenant_id)`。
- identity 文件：`src-tauri/src/terminal.rs:57-65` 存在 `app_data_dir/terminal-identity.json`，schema_version 不是 1 或解析失败会重建，见 `src-tauri/src/terminal.rs:78-105`。
- 初始化行为：`src-tauri/src/terminal.rs:356-386` 先 record，再 status=online，再启动 30 秒 heartbeat。
- MGR URL：`src-tauri/src/terminal.rs:232-234` 以 Portal API base 拼 `/mgr/...`；record/heartbeat/status 端点见 `src-tauri/src/terminal.rs:253-301`。
- heartbeat：`src-tauri/src/terminal.rs:417-439` 启动 tokio task；`src-tauri/src/terminal.rs:441-483` 如果 record 未成功且距离上次尝试 ≥60 秒，先补 record，再 heartbeat；连续失败 ≥6 次升级日志。
- logout：`src-tauri/src/lib.rs:390-420` 清 portal session 后异步 2 秒内尽力上报 offline 并 abort heartbeat。
- app exit：`src-tauri/src/lib.rs:552-578` 窗口销毁时 1.5 秒内尽力 offline。

## 5. Python/RPA sidecar API、执行、状态、审计、SSE/轮询

### 5.1 FastAPI 启停与后台线程

- startup：`python/backend/app/main.py:45-49` 初始化 DB 和 AuditLogger。
- 启动恢复：`python/backend/app/main.py:50-58` 调 `store.recover_interrupted_jobs()`，把重启前运行中的 job 标失败并写 audit。
- 启动对账：`python/backend/app/main.py:60-72` 调 `reconcile_on_startup()`，成功/失败写 audit。
- 上游调度器：`python/backend/app/main.py:74-104` 创建 `UpstreamScheduler`，注入带风险事件处理与 retry_precheck 的 `RpaOrchestrator` factory，并 `start()`。
- 好友复查 worker：`python/backend/app/main.py:105-110` 调 `start_friend_acceptance_rechecker()`；该函数仅在 `friend_acceptance_recheck_enabled` 且 `rpa_mode == real` 时启动，见 `python/backend/app/services/friend_acceptance.py:463-495`。
- shutdown：`python/backend/app/main.py:113-117` 停 scheduler 和 friend rechecker。

### 5.2 线索 API 与状态流转

- `GET /api/v1/leads`：`python/backend/app/api/routes/leads.py:10-15` 调 `LeadService.list_leads()`；store 以 `updated_at DESC LIMIT ?` 返回，见 `python/backend/app/storage/sqlite_store.py:153-159`。
- `POST /api/v1/leads`：`python/backend/app/api/routes/leads.py:18-23` 先 `reject_batch_payload()`，再 `LeadCreateRequest` 校验，最后 `LeadService.create_lead()`。
- 创建线索：`python/backend/app/services/lead_service.py:19-39` 生成 `lead_<uuid12>`，状态 `NEW_LEAD`，写 DB 并记录 `lead.created` audit。
- 开始通话：`python/backend/app/services/lead_service.py:41-53` 仅 `NEW_LEAD/CALLING` 可转 `CALLING`，否则 `INVALID_STATE`。
- 提交通话总结：`python/backend/app/services/lead_service.py:55-97` 仅 `CALLING/INTENT_CONFIRMED/RPA_PENDING_APPROVAL` 可提交；`intent=STRONG` 时必须 customer_consent、sales_confirmed_call 与 consent_evidence 均满足，否则写 `rpa.blocked.no_consent` 并抛 `CONSENT_REQUIRED`；满足后转 `RPA_PENDING_APPROVAL`。
- 统计：`python/backend/app/schemas/lead.py:71-101` 全量补齐 15 个 LeadStatus，再计算 success/running/failure。

### 5.3 RPA precheck/add-wechat/job/SSE

- Precheck 路由：`python/backend/app/api/routes/rpa.py:14-20` POST `/api/v1/rpa/precheck`，拒绝批量 payload。
- Precheck 逻辑：`python/backend/app/services/rpa_orchestrator.py:54-113` 写 `rpa.precheck.started`，检查客户同意、通话确认、同意证据、single target、daily limit、rpa_mode，然后写 passed/failed audit 并返回 allowed。
- Add-wechat 路由：`python/backend/app/api/routes/rpa.py:22-28` POST `/api/v1/rpa/add-wechat`，拒绝批量 payload。
- Add-wechat 入队：`python/backend/app/services/rpa_orchestrator.py:115-172` 先 `_validate_add_request()`；effective_mode 为 dry_run 或 settings.rpa_mode=simulation 时 simulation，否则 real；创建 `SIMULATION_QUEUED` 或 `REAL_QUEUED` job；`create_job_if_lead_idle()` 原子拒绝同一 lead 已有进行中 job；写 queued audit；`run_background()` 异步跑 `_run_job()`。
- Job 查询：`python/backend/app/api/routes/rpa.py:30-32` GET `/api/v1/rpa/jobs/{job_id}` 返回 store 中 job。
- Job SSE：`python/backend/app/api/routes/rpa.py:35-49` GET `/api/v1/rpa/jobs/{job_id}/events` 每秒最多轮询 120 次；payload 变化才 `data: ...`；只在 `SIMULATION_COMPLETED/REAL_COMPLETED/FAILED` 时 break。注意：`REAL_BIZ_*` 业务终态不会触发 break，只会继续轮询到 120 秒结束，尽管前端把它们视为终态。
- 前端 SSE 解析：`src/hooks/useJobSnapshot.ts:97-118` 手工按 `\n\n` 分帧，解析 data JSON；坏帧只 console.warn。

### 5.4 RPA 执行分支

- 模拟执行：`python/backend/app/services/rpa_orchestrator.py:218-235` 将 job 改 `SIMULATION_RUNNING`，执行 `execute_simulation()`；`python/backend/app/services/simulation_rpa.py:4-20` 依次 sleep 0.15 秒并推送 6 个固定步骤；完成后 job `SIMULATION_COMPLETED`，lead `RPA_SIMULATED`，audit `rpa.simulation.completed`。
- 真实执行：`python/backend/app/services/rpa_orchestrator.py:237-289` 将 job 改 `REAL_RUNNING`，lead 改 `RPA_EXECUTING`；第一次 attempt 写 `rpa.real.approved`、安全随机延时、写 `rpa.real.started`；调用 `_run_add_request_with_timeout()`；成功后 increment daily counter，job `REAL_COMPLETED/outcome_type=success`，lead `WECHAT_ADD_REQUESTED`，audit `rpa.real.completed`，再写 `wechat.friend.requested`。
- 超时隔离：`python/backend/app/services/rpa_orchestrator.py:307-359` 在 daemon thread 中执行真实加微；join 超过 `rpa_task_timeout_seconds` 设置 cancel_token 并抛 `SYS_RPA_TIMEOUT`。
- 自动重试：`python/backend/app/services/rpa_orchestrator.py:191-305` max_retries=1；系统异常第一次写 `SYS_ERROR_RETRY` 步骤并 2 秒后重试；第二次失败走 `_fail_job()`。
- 重试前读屏：`python/backend/app/services/rpa_orchestrator.py:194-217` attempt>0 且注入 retry_precheck 时执行；命中业务终态由 `RpaBusinessOutcome` 收尾，读屏自身系统错误只写 step 后继续重试。
- 业务终态：`python/backend/app/services/rpa_orchestrator.py:385-442` 将 `BIZ_TARGET_NOT_FOUND/BIZ_ALREADY_FRIEND/BIZ_ADD_REJECTED/BIZ_RISK_CONTROL/BIZ_ALREADY_REQUESTED` 映射到 LeadStatus；job status 写成 `REAL_<code>`，`outcome_type=business`；已是好友会 enqueue friend check report；风控会把 daily counter 顶到上限并调用 risk handler；audit 写 `rpa.real.business_outcome`。
- 系统失败：`python/backend/app/services/rpa_orchestrator.py:444-464` job 改 `FAILED/outcome_type=system`，lead 改 `RPA_FAILED`，audit 写 `rpa.real.failed`。
- RPA 核心 UI 流程：`python/backend/app/services/wechat_rpa.py:1259-1477` 入口校验目标非空、锁屏预检、定位微信窗口、置顶、清理遗留窗口、打开添加朋友、搜索、OCR 判定业务状态、点击添加、等待验证窗、填写验证语、点击发送、发送后 OCR 确认，成功 commit vision cache，失败 clear pending cache。
- 真实 RPA 业务状态关键词与映射：`python/backend/app/services/wechat_rpa.py:84-145` 定义 TARGET_NOT_FOUND、ALREADY_FRIEND、ADD_REJECTED、RISK_CONTROL、SEND_SUCCESS 关键词；`python/backend/app/services/wechat_rpa.py:205-210` 命中后抛 `RpaBusinessOutcome`。

### 5.5 好友通过复查与对账

- API check：`python/backend/app/api/routes/friend_acceptance.py:43-52` POST `/api/v1/friend-acceptance/check`，拒绝批量后调用 `FriendAcceptanceService.check_lead()`。
- API check-pending：`python/backend/app/api/routes/friend_acceptance.py:54-63` 批量复查待通过线索。
- 开发模拟：`python/backend/app/api/routes/friend_acceptance.py:65-120` 可按 lead_id 或 account 创建/更新 lead 到 `WECHAT_ADD_REQUESTED`，注入 checker 返回 `ALREADY_FRIEND`，再走正常 `check_lead()`。
- check_lead：`python/backend/app/services/friend_acceptance.py:257-358`：
  - 已经 `WECHAT_ACCEPTED`：enqueue friend check report 并直接返回 `ALREADY_ACCEPTED`。
  - 非 `WECHAT_ADD_REQUESTED`：抛 `FRIEND_ACCEPTANCE_NOT_PENDING`。
  - checker 返回 accepted：lead 改 `WECHAT_ACCEPTED`，enqueue friend check report，audit `wechat.friend.accepted`。
  - checker 未 accepted：attempts+1；RISK_CONTROL/TARGET_NOT_FOUND/max_attempts 分别转 `WECHAT_RISK_CONTROL/WECHAT_TARGET_NOT_FOUND/WECHAT_ACCEPTANCE_EXHAUSTED` 并 enqueue lead_status_report；RISK_CONTROL 还 enqueue friend_check_report false 并通知风险事件；audit `wechat.friend.acceptance_checked`。
- 后台复查：`python/backend/app/services/friend_acceptance.py:421-455` worker 每轮用 `runtime_guard.single_task()` 避免和 RPA 同时操作微信；`python/backend/app/services/friend_acceptance.py:445-455` 循环异常写 audit。

### 5.6 上游调度、轮询、状态、outbox

- 调度器启动：`python/backend/app/services/upstream_scheduler.py:119-170` 读取 SQLite upstream_config，mode=real 用 `RealUpstreamClient`，否则 `MockUpstreamClient`；创建 PollingLeadSource 并启动 heartbeat/fetch/worker/friend_report/lead_status_report 五个 daemon 线程。
- 上游状态 API：`python/backend/app/api/routes/upstream.py:55-67` 返回 scheduler_alive、wechat_online、state、queue_remaining、frozen_remaining_seconds。
- 风控冻结：`python/backend/app/services/upstream_scheduler.py:184-231` `_freeze_until` 是内存态，冻结时 `_compute_status_state()` 返回 `RISK_FROZEN`；重复 risk event 不延长冻结；dev API `/dev/scheduler/unfreeze` 可提前解冻，见 `python/backend/app/api/routes/upstream.py:44-52`。
- 轮询源：`python/backend/app/services/upstream_lead_source.py:37-48` 非冻结时按 interval 调 `fetch_once()`；冻结时跳过拉取。`fetch_once()` 见 `python/backend/app/services/upstream_lead_source.py:23-35`，从 client 拉取待添加线索并逐条 enqueue。
- 入队：`python/backend/app/services/upstream_scheduler.py:233-289` 要求 lead_id/phone/customer_name/greeting；用 `_queued_lead_ids` 去重；终态 lead 跳过；新 lead 写入 DB，状态 `RPA_PENDING_APPROVAL`，默认 consent/confirmed 为 1；随后 put 到本地队列。
- worker：`python/backend/app/services/upstream_scheduler.py:487-578` 冻结时将任务回插队尾并等待；正常时调用 orchestrator.add_wechat，轮询 job 到非 running 状态后映射上游状态并 enqueue lead_status_report；异常时 enqueue `BIZ_FAILED` 占位上报；结束后进入 COOLDOWN 并清 queued lead id。
- job→上游状态映射：`python/backend/app/services/upstream_scheduler.py:29-39` 与 `python/backend/app/services/upstream_scheduler.py:476-485`，FAILED→BIZ_FAILED，REAL_COMPLETED/SIMULATION_COMPLETED/REAL_BIZ_ALREADY_REQUESTED→REAL_SENT，业务终态映射到对应 BIZ_*。
- lead_status_reports outbox：SQLite schema `python/backend/app/storage/sqlite_store.py:107-120`；入队/发送/失败重试见 `python/backend/app/storage/sqlite_store.py:570-689`；调度器 flush 见 `python/backend/app/services/upstream_scheduler.py:407-447`。
- friend_check_reports outbox：SQLite schema `python/backend/app/storage/sqlite_store.py:97-105`；入队/发送/失败重试见 `python/backend/app/storage/sqlite_store.py:441-555`；调度器 flush 见 `python/backend/app/services/upstream_scheduler.py:449-474`。
- Mock upstream：`python/backend/app/services/upstream_client.py:25-79` 本地内存保存 pending leads 与 friend check reports；fetch 后清空 pending；上报总是 true。
- Real upstream：`python/backend/app/services/upstream_client.py:81-215` 对 `/login`、`/heartbeat`、`/leads/pending`、`/leads/report`、`/leads/friend-check` 发 HTTP；`_call_with_relogin()` 在 401 时用锁续签 token 并重试一次。
- 上游日志 SSE：`python/backend/app/services/upstream_scheduler.py:63-87` LogBroadcaster 用 queue 给 listener 广播；`python/backend/app/api/routes/upstream.py:175-196` 每 0.5 秒从 queue 取日志并 yield SSE。

## 6. 状态枚举、字段映射、持久化/config 边界

### 6.1 后端状态枚举

- `python/backend/app/schemas/lead.py:9-26` 定义 15 个 LeadStatus：`NEW_LEAD/CALLING/INTENT_CONFIRMED/RPA_PENDING_APPROVAL/RPA_SIMULATED/RPA_EXECUTING/WECHAT_ADD_REQUESTED/WECHAT_ACCEPTED/RPA_BLOCKED/RPA_FAILED/WECHAT_TARGET_NOT_FOUND/WECHAT_ALREADY_FRIEND/WECHAT_ADD_REJECTED/WECHAT_RISK_CONTROL/WECHAT_ACCEPTANCE_EXHAUSTED`。
- `python/backend/app/schemas/rpa.py:33-44` JobResponse 包含 job_id、lead_id、status、rpa_mode、dry_run、steps、error_code、error_message、outcome_type。
- 前端状态枚举与分组：`src/lib/leadStatus.ts:3-19` 复制 15 个 LeadStatus；`src/lib/leadStatus.ts:23-43` 将 success/running/failure/neutral 分组；分组与后端 stats 基本对齐。
- 前端状态文案：`src/lib/statusDisplay.ts:0-62` 映射 audit/job/lead/upstream 状态到中文；REAL_BIZ_* 有特殊处理。

### 6.2 数据库与审计持久化

- SQLite 初始化：`python/backend/app/storage/sqlite_store.py:31-121` 建表：leads、rpa_jobs、audit_events、daily_counters、upstream_config、friend_check_reports、lead_status_reports。
- 轻量迁移：`python/backend/app/storage/sqlite_store.py:123-130` 只补 rpa_jobs.outcome_type 与 leads.acceptance_attempts。
- rpa_jobs create：`python/backend/app/storage/sqlite_store.py:225-240` 插入时未写 `outcome_type`；终态 update 时才写，见 `python/backend/app/services/rpa_orchestrator.py:268-275`、`python/backend/app/services/rpa_orchestrator.py:400-408`、`python/backend/app/services/rpa_orchestrator.py:445-453`。
- 审计双写：`python/backend/app/core/audit.py:19-29` 每条 audit 同时写 SQLite `audit_events` 与 `settings.audit_file` JSONL。
- 审计查询：`python/backend/app/storage/sqlite_store.py:388-408` 默认按 timestamp DESC；会移除 data_json，并把 dry_run/customer_consent/human_approval 转 bool。

### 6.3 Config 边界

- Python settings：`python/backend/app/core/config.py:8-49` 从 `.env` 读 BaseSettings，默认 `rpa_mode='real'`、`upstream_mode='mock'`、`api_token='dev-local-token'`。
- 打包环境 `.env`：`python/backend/app/core/config.py:72-82` 若 `sys.frozen` 且 exe 同级 `.env` 存在则用它。
- 运行时 health settings：`python/backend/app/api/routes/health.py:40-57` 只改内存 settings，不写 SQLite 或 `.env`，重启丢失。
- upstream config：`python/backend/app/api/routes/upstream.py:25-37` 保存任意 dict 到 SQLite upstream_config，并 stop/start scheduler 应用新配置；`python/backend/app/storage/sqlite_store.py:428-439` 以 key/value 文本保存，不做类型 schema 迁移。
- 前端 UpstreamStatus 类型漏掉 `RISK_FROZEN`：`src/stores/useUpstreamStore.ts:10-16` 声明 state 为 `IDLE | BUSY | COOLDOWN`，而后端 `python/backend/app/services/upstream_scheduler.py:202-206` 可返回 `RISK_FROZEN`。

## 7. 明显未闭环 / 需 plan-agent 对账的问题

1. **dynamic port 未落地**：代码固定 8000。前端 `src/lib/api.ts:24`、Tauri sidecar `src-tauri/src/lib.rs:530-540`、状态栏 `src/components/layout/StatusBar.tsx:33` 都写死 8000；且 Windows 启动会 `taskkill` 占用 8000 的进程（`src-tauri/src/lib.rs:274-300`）。如果计划要求动态端口，需要补设计/实现对账。
2. **upstream/health 路由未鉴权**：本地鉴权只覆盖 leads/rpa/friend_acceptance/audit；`python/backend/app/api/routes/upstream.py:14` 和 `python/backend/app/api/routes/health.py:20-57` 没有 `Depends(require_auth)`。尤其 `/api/v1/upstream/logs` 本来被前端 EventSource 无 token 访问。
3. **RPA job SSE 对业务终态不主动结束**：前端把 `REAL_BIZ_*` 当终态（`src/hooks/useJobSnapshot.ts:6-14`），但后端 SSE 只对 `SIMULATION_COMPLETED/REAL_COMPLETED/FAILED` break（`python/backend/app/api/routes/rpa.py:45-46`），业务终态会保持连接直到 120 秒循环结束。
4. **上游状态类型前后端不一致**：后端可能返回 `RISK_FROZEN`（`python/backend/app/services/upstream_scheduler.py:202-206`），前端 store 类型只允许 `IDLE/BUSY/COOLDOWN`（`src/stores/useUpstreamStore.ts:10-16`），UI label switch 也无 RISK_FROZEN 专门文案（`src/components/features/UpstreamConfig.tsx:43-50`）。
5. **lead job snapshot 清理可能跨 lead 误删**：`src/hooks/useLeadJobs.ts:94-101` 只基于当前 lead 的 `jobIdsToKeep` 删除 `state.snapshots` 中所有不在列表里的 id，可能删除其他 lead 的 snapshots。
6. **health/settings 非持久化**：风控页面保存只改 Python 进程内 settings（`python/backend/app/api/routes/health.py:40-57`），重启后回到 `.env/default`。
7. **RPA direct board trigger 固定 dry_run=true 且缺少 call consent 流**：看板触发 `src/hooks/useAudits.ts:24-31` 只传 `{lead_id,dry_run:true}`，但后端 `_validate_add_request()` 仍要求 consent（`python/backend/app/services/rpa_orchestrator.py:466-482`）。若看板中存在上游自动创建且已带 consent 的 lead 可跑；普通新建 lead 未走 call-summary 会被阻断。需确认这是预期还是 UX 缺口。
8. **AccountManagement 密码修改仅前端提示**：`src/components/features/AccountManagement.tsx:52-59` 没有 Portal 修改密码 API 调用。
9. **本次任务线目录缺少 state.md**：按要求读取 `docs/tasks/project-closure-audit/state.md`，但目录不存在；本次只创建并写入了 flow.md，未补 state.md，以避免超出“只产出 flow.md”的任务范围。

STATUS: READY_FOR_REVIEW
