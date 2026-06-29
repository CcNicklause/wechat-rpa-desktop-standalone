# 开发测试页 · 实际功能流程

> 反映代码现状，**不**复述设计文档。设计期望见 [plan.md](plan.md)。
> 页面组件：`src/components/features/DevTesting.tsx`，路由 `/dev-testing`。

## 页面能力总览（代码现状）

开发测试页是本地联调 + 运维入口，自上而下由若干卡片组成：

1. **一键清空本地数据（危险操作）** — 见 Cycle 1。
2. **批量线索模拟（走真实上游链路）**：多行表单 → `POST /api/v1/upstream/dev/seed-mock-leads`（仅 mock 模式可用）→ 进入 mock 上游待发池并立即 `fetch_once` 拉入本地队列。提交前有 `window.confirm` 确认。
3. **手动加友功能测试面板**：表单（phone/greeting/dryRun 模板）→ 创建 lead → `call-start` → `call-summary` → `POST /api/v1/rpa/add-wechat`；真实加微(dryRun=false)有二次 confirm。表单草稿与 job 快照持久在 zustand store(localStorage)，刷新可恢复。
4. **运行测试反馈控制台**：`JobProgress` 监听 job 步骤流；可跳转看板、清空 job 快照。
5. **审计事件**：按 `lead_id` 轮询 `GET /api/v1/audit?lead_id=&limit=200`，8s 刷新，倒序展示。
6. **好友通过模拟 / 对账**：`simulate-accepted`（单条或按账号）、`清理待对账`(`POST /api/v1/friend-acceptance/dev/clear-pending`，把 `WECHAT_ADD_REQUESTED`→`RPA_BLOCKED`)、`立即上报`(`POST /api/v1/upstream/dev/trigger-friend-check-report`)；展示本地 outbox 与 mock 上游已收对账。

## Cycle 1：一键清空本地数据

### 已落地

- 后端
  - `SQLiteStore.wipe_business_data()`（`storage/sqlite_store.py`）：硬编码白名单表 `leads / rpa_jobs / audit_events / friend_check_reports / lead_status_reports / daily_counters` 逐表 `DELETE`，返回 `{表名: 删除行数}`；`upstream_config` 不在白名单 → 配置保留。
  - `POST /api/v1/upstream/dev/wipe-data`（`api/routes/upstream.py`）：调 `wipe_business_data()` + `scheduler.clear_queue()`（清内存任务队列 + 去重位 `_queued_lead_ids`），写一条日志，返回 `{status:"cleared", counts, queue_cleared}`。无 scheduler 时跳过队列清理但 DB 仍清。
- 前端 `DevTesting.tsx`
  - 顶部红色 `destructive` 卡片 + 按钮，`wipingData` 态控制按钮禁用文案。
  - `wipeAllData()` 两道闸门：① `window.confirm` 说明范围/不可逆；② `window.prompt` 必须输入「清空」口令。两道任一不通过 → toast「已取消」，不发请求。
  - 成功后：`clearJobInStore()` 清 DevTest store 残留 job 快照；invalidate `dev-test-leads` / `dev-test-friend-check-reports` / `dev-test-audit`；toast 汇总删除总行数 + 队列是否清空。
  - 网络错误识别（`TypeError` / Failed to fetch / ECONNREFUSED）→ toast「无法连接本地后端」。

### 与设计的偏差

- 无实质偏差。`scheduler.clear_queue()` 与 DB 清空未包在同一事务，属设计已接受的权衡（人工危险操作）。

## 测试覆盖

```powershell
# 后端单测
cd python; $env:PYTHONPATH="."; uv run pytest backend/app/tests/test_upstream_api.py backend/app/tests/test_upstream_scheduler.py -q
# store + 路由 smoke（清表 + 保留配置）
cd python; $env:PYTHONPATH="."; uv run python -c "from backend.app.storage.sqlite_store import SQLiteStore; ..."
# 前端类型检查
npx tsc --noEmit -p .
```

结果：

- `test_upstream_api.py` 4 passed；`test_upstream_scheduler.py` 17 passed。
- smoke：写入 1 条 lead + upstream_config → `wipe_business_data()` 返回 `{'leads':1,...}` → `get_upstream_config()` 仍返回 `{'upstream_mode':'mock'}`，`list_leads()` 为空。
- `tsc --noEmit` 无报错。

STATUS: IMPLEMENTED
