# 开发测试页 · 计划

> 任务线：`dev-testing-panel`
> 状态：IMPLEMENTED（Cycle 1 一键清空）

## 第一部分 · 需求

### 需求 1：开发测试页一键清空本地数据

- 业务问题：本地联调会积累僵尸中间态残留（如 `CALLING` 创建后未提交小结、`RPA_SIMULATED` 模拟完成无终态），污染看板计数；需要一个页面级入口快速清空本地业务数据回到干净态。
  - ⚠️ 2026-06-29 纠正：此前表述为“卡死在执行中的孤儿记录”系误判，实测无 running 孤儿（`recover_interrupted_jobs` 正常，`RPA_EXECUTING`=0）。一键清空清的是僵尸中间态残留。
- 验收标准：
  - 开发测试页提供「一键清空本地数据」入口，醒目标注为危险操作。
  - **二次确认**：第一轮 confirm 说明范围与不可逆性，第二轮 prompt 要求输入口令「清空」才真正执行。
  - 清空范围 = 业务数据全清（线索 / RPA 任务 / 审计事件 / 好友对账 / 加微结果上报 / 每日计数），**保留** `upstream_config` 等配置，清空后仍可直接使用。
  - 同步清空调度器内存队列与去重位，避免清空后仍有幽灵任务继续跑。
  - 清空后前端 invalidate 相关查询并清理 DevTest store 残留 job 快照，UI 不再指向已不存在的 job。

### 非目标（明确不做）

- 不根治「孤儿记录产生根因」——那是启动自检缺口，归属 RPA 加固任务线，本页只提供清理手段。
- 不清空上游配置，不重置 mock 上游侧已收到的对账记录。

## 第二部分 · 技术设计

### 设计 1：后端清空能力

- 数据模型：复用现有 SQLite schema，不动表结构。白名单表硬编码在方法内，避免外部输入拼 SQL。
- 代码触点：
  - `python/backend/app/storage/sqlite_store.py` 新增 `wipe_business_data()`：对 `leads / rpa_jobs / audit_events / friend_check_reports / lead_status_reports / daily_counters` 逐表 `DELETE`，返回各表删除行数字典；`upstream_config` 不在白名单内故保留。
  - `python/backend/app/api/routes/upstream.py` 新增 `POST /api/v1/upstream/dev/wipe-data`：调 `store.wipe_business_data()` + `scheduler.clear_queue()`，记录一条日志，返回 `{status, counts, queue_cleared}`。
- 风险与权衡：
  - 表名白名单硬编码 → 安全但增删业务表时需同步更新白名单（可接受，业务表变动频率低）。
  - 不在事务内联动 `scheduler.clear_queue()` → 内存队列与 DB 分别清理，极端并发下可能 DB 已清而队列里还有刚回插的任务；但 clear_queue 会清空去重位与队列，且本操作为人工危险操作，可接受。

### 设计 2：前端二次确认交互

- 代码触点：`src/components/features/DevTesting.tsx`
  - 顶部新增红色危险卡片 + `destructive` 按钮。
  - `wipeAllData()`：两道闸门——`window.confirm` → `window.prompt('清空')` 口令校验 → 调 `POST /api/v1/upstream/dev/wipe-data`。
  - 成功后 `clearJobInStore()` + invalidate `dev-test-leads` / `dev-test-friend-check-reports` / `dev-test-audit` 查询。
- 风险与权衡：用浏览器原生 confirm/prompt 而非自定义弹窗，与页面其它危险操作（批量下发、真实加微）风格一致；prompt 口令增加误触成本。

## 第三部分 · 测试清单

| # | 用例 | 前置 | 触发 | 期望 |
|---|---|---|---|---|
| 1.1 | 清空保留配置 | 写入一条 lead + upstream_config | 调 `wipe_business_data()` | 返回 counts，`get_upstream_config()` 仍返回原配置，`list_leads()` 为空 |
| 1.2 | 取消第一道确认 | — | 点按钮 → confirm 取消 | 不发请求，toast 提示已取消 |
| 1.3 | 口令不匹配 | 已过第一道 | prompt 输入非「清空」 | 不发请求，toast 提示口令不匹配 |
| 1.4 | 正常清空 | 本地有数据 | 口令「清空」 | 接口返回 counts，UI 查询刷新，DevTest job 快照清除 |
| 1.5 | 后端未起 | 关后端 | 触发清空 | toast 提示无法连接本地后端 |

## 第四部分 · 对账与优化清单

| 优先级 | 项目 | 原因 | 建议处理 |
|---|---|---|---|
| P2 | 一键清空只清理，不展示孤儿记录 | 用户需先去别处确认哪些是孤儿 | 后续 Cycle 可在页内展示卡在 running 状态的记录并提供选择性回收 |
| P2 | 僵尸中间态回收（CALLING 超时 / RPA_SIMULATED 终态） | 这些状态会长期挂起污染统计 | 用户当前选择只修 KPI 口径（`frontend-leads-board` Cycle 9），回收暂不做 |

STATUS: IMPLEMENTED
