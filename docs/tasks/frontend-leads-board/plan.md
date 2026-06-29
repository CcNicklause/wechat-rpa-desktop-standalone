# frontend-leads-board · 计划

> 任务线：`frontend-leads-board`
> 状态：`READY`

## 第一部分 · 需求

### 业务问题

当前看板状态不够友好，无法直观查看每个线索的日志流程。用户需要：
1. 快速了解每个线索的执行状态和最后一步
2. 点击线索后可深入查看该线索的完整执行历史
3. 支持查看同一线索的多次执行记录
4. 刷新页面后保留上下文状态

### 用户场景

1. **驾驶舱浏览**：用户打开看板，看到顶部 KPI 条、左侧线索列表、右侧全局审计流
2. **线索下钻**：点击某个线索行，右侧滑出详情抽屉，展示该线索的完整信息
3. **多任务对比**：用户同时触发两个线索执行，能在列表中看到各线索的实时状态
4. **历史追溯**：用户查看某个线索的历史执行记录，切换不同 Job 查看当时的 Steps

### 验收标准

#### 行选中与 URL 状态
- [ ] 点击线索行时，该行高亮并显示左侧蓝色指示条
- [ ] URL hash 更新为 `#/dashboard?lead=<id>&tab=steps&job=<jobId>`
- [ ] 刷新页面后，自动恢复到之前选中的线索和 Tab
- [ ] 关闭抽屉时，URL query 参数被清除

#### 抽屉交互与 Tab 切换
- [ ] 抽屉从右侧滑出，宽度约占屏幕 60% (max 900px)
- [ ] 抽屉包含 4 个 Tab：Jobs / Steps / Timeline / Raw
- [ ] **Jobs Tab**：列出该线索的所有历史执行记录，按时间倒序
- [ ] **Steps Tab**：展示当前选中 Job 的实时步骤流
- [ ] **Timeline Tab**：仅显示该线索相关的审计事件
- [ ] **Raw Tab**：以折叠 JSON 形式展示 snapshot 原始数据

#### 行内子文案与实时更新
- [ ] 线索行显示"最后一步"摘要文本
- [ ] 线索行显示该线索的"已重试次数"（从 steps 中提取 `SYS_ERROR_RETRY`）
- [ ] 执行中的线索，行内子文案实时更新

#### 执行触发与自动导航
- [ ] 点击行内"立即执行"按钮，不打开抽屉
- [ ] 执行成功后，toast 提示并自动打开抽屉，定位到 Steps Tab
- [ ] Steps Tab 实时展示 SSE 推送的步骤流

#### 窄屏适配
- [ ] 屏幕宽度 < 768px 时，抽屉全屏展示
- [ ] 抽屉支持 ESC 键关闭、点击遮罩关闭、关闭按钮关闭

#### 数据持久化
- [ ] 刷新页面后，lead → jobs 映射关系不丢失（localStorage key: `wechat_rpa_lead_jobs`）
- [ ] 刷新页面后，已完成 Job 的快照可立即展示

#### 兼容性
- [ ] 旧入口 `LeadsDashboard` 继续工作（向后兼容）
- [ ] DevTesting 页面不受影响
- [ ] 其他页面（AccountManagement / RiskControl / UpstreamConfig）不受影响

---

## 第二部分 · 技术设计

### 信息架构

```
LeadsBoard (替换 LeadsDashboard)
├── KpiStrip (顶部 KPI 条)
├── LeadsBoardBody
│   ├── LeadsList (左侧主列表，flex-1)
│   │   ├── LeadRowSummary (行内子文案)
│   │   └── 选中高亮 + 左侧指示器
│   └── GlobalFeedColumn (右侧 w-80)
│       └── AuditList
└── LeadDetailDrawer (右侧滑出，60vw / 全屏)
    ├── LeadHeader
    ├── Tabs
    │   ├── Jobs (LeadJobsPanel)
    │   ├── Steps (LeadStepsPanel → JobStepsView)
    │   ├── Timeline (LeadTimelinePanel → AuditList)
    │   └── Raw (LeadRawPanel)
    └── DrawerFooter
```

### 文件清单与变更方式

| 操作 | 文件路径 | 说明 |
|-----|---------|-----|
| **新增** | `src/hooks/useJobSnapshot.ts` | ✅ 已实现：抽离 SSE 逻辑，全局单例管理 |
| **新增** | `src/hooks/useLeadJobs.ts` | ✅ 已实现：zustand persist store |
| **新增** | `src/lib/auditTranslate.ts` | ✅ 已实现：抽离翻译函数 |
| **新增** | `src/components/features/board/LeadsBoard.tsx` | ✅ 已实现：新看板主组件 |
| **新增** | `src/components/features/board/KpiStrip.tsx` | ✅ 已实现：KPI 条 |
| **新增** | `src/components/features/board/LeadDetailDrawer.tsx` | ✅ 已实现：抽屉容器 |
| **新增** | `src/components/features/board/LeadHeader.tsx` | ✅ 已实现：抽屉头部 |
| **新增** | `src/components/features/board/LeadJobsPanel.tsx` | ✅ 已实现：Jobs Tab |
| **新增** | `src/components/features/board/LeadStepsPanel.tsx` | ✅ 已实现：Steps Tab |
| **新增** | `src/components/features/board/LeadTimelinePanel.tsx` | ✅ 已实现：Timeline Tab |
| **新增** | `src/components/features/board/LeadRawPanel.tsx` | ✅ 已实现：Raw Tab |
| **新增** | `src/components/features/board/LeadRowSummary.tsx` | ✅ 已实现：行内子文案 |
| **新增** | `src/components/features/board/JobStepsView.tsx` | ✅ 已实现：Steps 纯展示组件 |
| **新增** | `src/components/features/board/AuditList.tsx` | ✅ 已实现：Audit 纯展示组件 |
| **新增** | `src/components/ui/drawer.tsx` | ✅ 已实现：简化版 Drawer |
| **修改** | `src/components/features/JobProgress.tsx` | ✅ 已修改：变薄壳 |
| **修改** | `src/components/features/AuditTimeline.tsx` | ✅ 已修改：变薄壳 |
| **修改** | `src/components/features/LeadsList.tsx` | ✅ 已修改：支持选中、行内子文案 |
| **修改** | `src/components/features/LeadsDashboard.tsx` | ✅ 已修改：转发到 LeadsBoard |
| **修改** | `src/hooks/useHashRoute.ts` | ✅ 已扩展：支持 query 参数 |
| **修改** | `src/hooks/useAudits.ts` | ✅ 已扩展：导出 maskPhone + useLeadAudits |

### 数据模型与 Store

#### 1. `useLeadJobsStore` (zustand persist)

✅ **已实现**：`src/hooks/useLeadJobs.ts`
- persist key: `wechat_rpa_lead_jobs` ✅
- 数据结构：`leadToJobs`, `jobMeta`, `snapshots` ✅
- Actions：`appendJob`, `updateJobMeta`, `setSnapshot`, `getLeadJobs`, `getLatestJob`, `getSnapshot` ✅
- 限制：每 lead 最近 5 个 snapshot（避免 localStorage 膨胀）✅

#### 2. `useJobSnapshot` Hook

✅ **已实现**：`src/hooks/useJobSnapshot.ts`
- 全局单例管理：`activeStreams` Map，同一 jobId 只开一个 SSE 连接 ✅
- 读取顺序：store 快照 → React Query 兜底 GET → SSE 实时流 ✅
- 终态检测：`TERMINAL_STATUSES` Set ✅
- 每收到数据同时更新 store ✅

#### 3. `useHashRoute` 扩展

✅ **已实现**：`src/hooks/useHashRoute.ts`
- 返回值：`{ route, query, navigate, setQuery }` ✅
- `setQuery(params)`：值为 null 时删除该参数 ✅
- 刷新后自动恢复状态 ✅

#### 4. `useLeadAudits` Hook

✅ **已实现**：`src/hooks/useAudits.ts`
- `maskPhone(phone)`: 138****5678 格式脱敏 ✅
- `useLeadAudits(audits, phone)`: 按 phone_masked 过滤 ✅

### 详细设计要点

#### 1. `LeadsBoard` 主组件

✅ **已实现**：`src/components/features/board/LeadsBoard.tsx`
- 保持与原 `LeadsDashboard` 完全相同的 props 接口 ✅
- 管理 URL query 状态（lead/tab/job）✅
- 监听 `activeJobId` 变化，自动打开对应 lead 的抽屉 ✅
- toast 提示："任务开始执行"（设计期望："执行成功"）

#### 2. `LeadDetailDrawer` 组件

✅ **已实现**：`src/components/features/board/LeadDetailDrawer.tsx`
- 简化版自定义 Drawer（不依赖 Radix）✅
- 宽度：桌面 60vw (max 900px)，<768px 全屏 ✅
- 关闭方式：ESC 键、点击遮罩、关闭按钮 ✅
- 无选中 job 时自动选中最新的 ✅

#### 3. `LeadsList` 重构

✅ **已实现**：`src/components/features/LeadsList.tsx`
- 新增 props：`selectedId`, `onSelect` ✅
- 选中样式：左侧 1px 蓝色指示器 + border-primary + bg-primary/5 + ring-1 ✅
- 行内子文案：`LeadRowSummary` 显示最后一步和重试次数 ✅
- 立即执行按钮：`e.stopPropagation()` 避免触发行点击 ✅

#### 4. `LeadRowSummary` 组件

✅ **已实现**：`src/components/features/board/LeadRowSummary.tsx`
- 从 `jobMeta.lastStep` 显示最后一步 ✅
- 重试次数：从 steps 中过滤 `SYS_ERROR_RETRY` 统计 ✅

#### 5. 兼容性处理

✅ **已实现**：
- `LeadsDashboard`：props 不变，内部 `<LeadsBoard {...props} />` ✅
- `JobProgress`：变薄壳，使用 `useJobSnapshot` + `JobStepsView` ✅
- `AuditTimeline`：变薄壳，使用 `AuditList` ✅

### 风险与权衡

| 风险 | 影响 | 缓解方案 |
|-----|------|---------|
| 前端维护 lead → jobs 映射，数据可能与后端不一致 | 中 | 后续可添加 `/api/v1/leads/{id}/jobs` 接口，本设计预留切换空间 |
| 多组件订阅同一 jobId 可能创建多个 SSE 连接 | 低 | ✅ 已实现：全局单例管理 `activeStreams` Map |
| localStorage 持久化快照可能占用较多空间 | 低 | ✅ 已实现：只保留最近 5 个 job 的完整 snapshot |
| Drawer 简化版缺少 focus trap / aria 属性 | 低 | 当前可接受，后续可升级为 Radix |

### 待澄清（plan-agent 留给后续迭代）

1. 是否需要"固定"某个 lead 到侧边栏？（当前设计不需要）
2. Jobs Tab 中的历史记录是否需要删除/清空功能？（当前设计不需要）
3. Raw Tab 的 JSON 是否支持复制/下载？（当前设计仅折叠展示）

---

## 第三部分 · 测试清单

| # | 用例 | 前置 | 触发 | 期望 |
|---|-----|------|-----|-----|
| 1 | 行选中与高亮 | 看板已加载，有线索数据 | 点击某线索行 | 该行高亮，显示左侧蓝色指示条 |
| 2 | URL 同步更新 | 同上 | 点击某线索行 | URL hash 更新为 `#/dashboard?lead=<id>&tab=steps` |
| 3 | 刷新恢复状态 | 已打开某个线索抽屉，选中 Steps Tab | 刷新页面 | 抽屉自动打开，Tab 仍为 Steps，选中同一条线索 |
| 4 | 关闭抽屉清参数 | 抽屉打开状态 | 点击抽屉关闭按钮 / ESC / 点击遮罩 | 抽屉关闭，URL query 参数被清除 |
| 5 | 执行触发不打开抽屉 | 看板已加载 | 点击某行"立即执行"按钮 | 不打开抽屉，任务被触发 |
| 6 | 执行成功自动开抽屉 | 触发执行 | 执行成功返回 | Toast 提示，自动打开抽屉并定位到 Steps Tab |
| 7 | Steps Tab 实时更新 | 抽屉打开，有执行中 Job | SSE 推送新 step | Steps 列表自动滚动到底部，新 step 实时显示 |
| 8 | 多 Job 订阅不串台 | 同时触发两个 lead 执行 | 打开第一个 lead 抽屉看 Steps | 第一个 lead 的 Steps 正常更新，第二个 lead 的行内子文案也正常更新 |
| 9 | Jobs Tab 历史列表 | 某线索执行过多次 | 打开该线索抽屉，切到 Jobs Tab | 列出所有历史 Job，按时间倒序 |
| 10 | 切换历史 Job | Jobs Tab 列出多个 Job | 点击某个历史 Job | Steps Tab 切换显示该 Job 的快照，URL `job=` 参数更新 |
| 11 | Timeline Tab 过滤 | 某线索有审计记录 | 打开该线索抽屉，切到 Timeline Tab | 只显示该线索相关的审计事件（按 phone_masked 过滤） |
| 12 | Raw Tab 折叠展示 | 选中某个已完成 Job | 切到 Raw Tab | JSON 折叠展示，支持展开/折叠 |
| 13 | 窄屏全屏抽屉 | 调整窗口宽度 < 768px | 点击某个线索 | 抽屉全屏展示 |
| 14 | 持久化刷新可用 | 某线索有历史执行记录 | 刷新页面 | 行内子文案立即显示，抽屉内 Jobs 列表立即渲染，无需等待 SSE |
| 15 | 旧入口兼容 | 现有代码调用 `LeadsDashboard` | 编译运行 | 无错误，新看板正常工作 |
| 16 | 其他页面不受影响 | 完成看板改造 | 导航到 DevTesting / Accounts / Risk / Upstream | 各页面功能正常 |

---

## 第四部分 · 对账与优化清单

| 优先级 | 项目 | 原因 | 建议处理 |
|-------|------|------|---------|
| **P1** ✅ 已修复 | `handleTriggerJob` 不调用 `appendJob` | 已修复：在 `useExecuteRpaMutation.onSuccess` 中调用 `appendJob` + `updateJobMeta` 写 QUEUED 占位 | - |
| **P1** ✅ 已修复 | 自动打开抽屉的竞态风险 | 已修复：在 `AppShell.tsx` 的 mutation `onSuccess` 中原子化 `setQuery`，`LeadsBoard.tsx` 已移除竞态 useEffect | - |
| **P2** | Drawer 缺少 focus trap / aria 属性 | 简化版 Drawer 没有实现 focus trap、正确的 aria-modal 属性等可访问性功能 | 后续可升级为 @radix-ui/react-dialog |
| **P3** | toast 文案差异 | 设计期望"执行成功"，实际是"任务启动成功" | 可修改，也可接受（因为 activeJobId 出现时任务确实刚开始） |
| **P3** | 全局 Feed 宽度差异 | 设计 w-72 ~ w-80，实际 w-80 | 可接受 |

---

## 测试用例覆盖核查

逐条对照 flow.md + 源码，评估覆盖情况：

| # | 用例 | 状态 | 说明 |
|---|-----|------|-----|
| 1 | 行选中与高亮 | ✅ | `LeadsList.tsx` 已实现选中样式 + 左侧指示器 |
| 2 | URL 同步更新 | ✅ | `useHashRoute.ts` 已支持 query 参数，`handleRowClick` 中调用 `setQuery` |
| 3 | 刷新恢复状态 | ✅ | `useHashRoute` 从 hash 读取状态，`useLeadJobsStore` 从 localStorage 恢复 |
| 4 | 关闭抽屉清参数 | ✅ | `handleCloseDrawer` 中 `setQuery({ lead: null, tab: null, job: null })` |
| 5 | 执行触发不打开抽屉 | ✅ | 点击"立即执行"时 `e.stopPropagation()`，不触发行点击 |
| 6 | 执行成功自动开抽屉 | ✅ | 已修复：在 `AppShell.tsx` 的 mutation `onSuccess` 中原子化更新 URL，无竞态 |
| 7 | Steps Tab 实时更新 | ✅ | `useJobSnapshot` SSE 实时流 + `JobStepsView` 自动滚动 |
| 8 | 多 Job 订阅不串台 | ✅ | `useJobSnapshot` 全局单例管理 `activeStreams` Map |
| 9 | Jobs Tab 历史列表 | ✅ | `LeadJobsPanel` 按时间倒序展示 |
| 10 | 切换历史 Job | ✅ | `handleJobChange` 更新 URL `job=` 参数 |
| 11 | Timeline Tab 过滤 | ✅ | `useLeadAudits` 按 phone_masked 过滤 |
| 12 | Raw Tab 折叠展示 | ✅ | `LeadRawPanel` 支持展开/折叠 |
| 13 | 窄屏全屏抽屉 | ✅ | `drawer.tsx` 检测 `window.innerWidth < 768` |
| 14 | 持久化刷新可用 | ✅ | `useLeadJobsStore` 使用 zustand persist |
| 15 | 旧入口兼容 | ✅ | `LeadsDashboard` 转发到 `LeadsBoard` |
| 16 | 其他页面不受影响 | ✅ | `JobProgress` / `AuditTimeline` 保持兼容，其他页面未改动 |

### 总体评估

✅ **所有问题已收敛**，P1 已修复，核心功能完整实现，可以进入测试环节。

STATUS: CONVERGED

---

## Cycle 2 · 看板数据流真实化 + DevTesting 联通

### 业务背景与范围

Cycle 1 实现了看板的基本交互，但存在以下问题：
1. KPI 统计口径完全基于前端列表（受 `/api/v1/leads?limit=100` 截断），数据失真
2. 状态分组逻辑硬编码在组件中，易出错且难复用
3. DevTesting 触发的 job 不会同步到看板
4. 看板行内"立即执行"按钮直接调 `/api/v1/rpa/add-wechat`，跳过了 call-start/call-summary 流程

**Cycle 2 范围**（三件事合并）：
- 前端 KPI 口径修正 + 状态分组统一抽离
- DevTesting 联通看板
- 后端新增 `/api/v1/leads/stats` + 前端接入（首次动后端）

**不在范围**：
- 看板分页/筛选
- 今日新增成功等基于 audit_events 的 KPI
- LeadHeader 重跑按钮的完整流程改造

---

### 需求与验收标准

#### 件 1：前端 KPI 口径修正

| ID | 验收标准 |
|----|----------|
| K1-1 | 新增 `src/lib/leadStatus.ts` 统一管理状态分组与判定函数，所有组件不再直接写 `status === 'XXX'` |
| K1-2 | 状态分组明确定义：<br>- SUCCESS: `WECHAT_ACCEPTED`<br>- RUNNING: `CALLING, INTENT_CONFIRMED, RPA_PENDING_APPROVAL, RPA_SIMULATED, RPA_EXECUTING, WECHAT_ADD_REQUESTED`<br>- FAILURE: `RPA_FAILED, RPA_BLOCKED, WECHAT_RISK_CONTROL, WECHAT_ADD_REJECTED, WECHAT_TARGET_NOT_FOUND, WECHAT_ACCEPTANCE_EXHAUSTED`<br>- NEUTRAL: `NEW_LEAD, WECHAT_ALREADY_FRIEND` |
| K1-3 | KpiStrip 使用新分组计算，错误不再漏统计、终态不再被误算为执行中 |
| K1-4 | 降级模式（无 stats 接口/失败）：总数副标题改为 "近 N 条样本"，成功率副标题加 "(基于 N 条样本，仅供参考)" |

#### 件 2：DevTesting 联通看板

| ID | 验收标准 |
|----|----------|
| K2-1 | `useLeadJobsStore` 新增导出 `registerJobStarted(leadId, jobId)`，内部调用 `appendJob` + `updateJobMeta(lastStatus='QUEUED', lastTimestamp, stepCount=0)` |
| K2-2 | `useExecuteRpaMutation.onSuccess` 改为调用 `registerJobStarted` 而非直接调 `appendJob` |
| K2-3 | DevTesting 的 onSubmit 拿到 `response.job_id` 后调用 `registerJobStarted` |
| K2-4 | DevTesting toast 新增按钮 "在看板查看 →"，点击后更新 hash 为 `#/dashboard?lead=<leadId>&tab=steps&job=<jobId>` |
| K2-5 | 看板 LeadsList 移除行内"立即执行"按钮，`onTriggerJob` prop 改为可选 |
| K2-6 | LeadHeader 按钮文案改为"重跑"，handler 不变 |
| K2-7 | Lead.id 类型从 number 改为 string；全端 grep 并移除 `parseInt(lead.id)` |

#### 件 3：后端 KPI Stats 接口

| ID | 验收标准 |
|----|----------|
| K3-1 | 后端新增 `GET /api/v1/leads/stats` 接口，需要鉴权 |
| K3-2 | 响应 Schema（python/schemas/lead.py）：<br>- `total: int`（全库总数）<br>- `by_status: dict[str, int]`（所有 15 个 LeadStatus 都有 key，count=0 也列出）<br>- `success: int`（WECHAT_ACCEPTED 数）<br>- `running: int`（RUNNING group 总和）<br>- `failure: int`（FAILURE group 总和）<br>- `ts: str`（ISO-8601 服务端时间） |
| K3-3 | SQLiteStore 新增 `count_leads_by_status()` 返回 `dict[str, int]`，使用 `SELECT status, COUNT(*) FROM leads GROUP BY status` |
| K3-4 | LeadService 新增 `compute_lead_stats()` 计算并返回完整响应结构 |
| K3-5 | 新增 `python/backend/tests/test_lead_stats.py` 覆盖空库、单状态、多状态、所有状态出现一次的场景 |
| K3-6 | 前端新增 `useLeadsStatsQuery` hook（react-query，8s 轮询） |
| K3-7 | KpiStrip 在 stats 可用时切换到 stats 数据：总数用 `total`，成功/执行中/异常用 `success/running/failure`，副标题改为 "全库实时计数" |
| K3-8 | Stats 接口 404/失败时降级到列表样本计算 |

---

### 技术设计

#### 件 1：前端 KPI 口径修正

**新增文件**：
| 文件 | 说明 |
|------|------|
| `src/lib/leadStatus.ts` | 状态分组常量 + 判定函数 |

**src/lib/leadStatus.ts 内容（精确抄）**：
```typescript
import type { Lead } from '@/hooks/useLeads';

/** 后端 LeadStatus 枚举值（全量 15 个） */
export const LEAD_STATUS = {
  NEW_LEAD: 'NEW_LEAD',
  CALLING: 'CALLING',
  INTENT_CONFIRMED: 'INTENT_CONFIRMED',
  RPA_PENDING_APPROVAL: 'RPA_PENDING_APPROVAL',
  RPA_SIMULATED: 'RPA_SIMULATED',
  RPA_EXECUTING: 'RPA_EXECUTING',
  WECHAT_ADD_REQUESTED: 'WECHAT_ADD_REQUESTED',
  WECHAT_ACCEPTED: 'WECHAT_ACCEPTED',
  RPA_BLOCKED: 'RPA_BLOCKED',
  RPA_FAILED: 'RPA_FAILED',
  WECHAT_TARGET_NOT_FOUND: 'WECHAT_TARGET_NOT_FOUND',
  WECHAT_ALREADY_FRIEND: 'WECHAT_ALREADY_FRIEND',
  WECHAT_ADD_REJECTED: 'WECHAT_ADD_REJECTED',
  WECHAT_RISK_CONTROL: 'WECHAT_RISK_CONTROL',
  WECHAT_ACCEPTANCE_EXHAUSTED: 'WECHAT_ACCEPTANCE_EXHAUSTED',
} as const;

export type LeadStatus = (typeof LEAD_STATUS)[keyof typeof LEAD_STATUS];

/** 状态分组（与后端 stats 返回对齐） */
export const LEAD_STATUS_GROUPS = {
  SUCCESS: new Set([LEAD_STATUS.WECHAT_ACCEPTED]),
  RUNNING: new Set([
    LEAD_STATUS.CALLING,
    LEAD_STATUS.INTENT_CONFIRMED,
    LEAD_STATUS.RPA_PENDING_APPROVAL,
    LEAD_STATUS.RPA_SIMULATED,
    LEAD_STATUS.RPA_EXECUTING,
    LEAD_STATUS.WECHAT_ADD_REQUESTED,
  ]),
  FAILURE: new Set([
    LEAD_STATUS.RPA_FAILED,
    LEAD_STATUS.RPA_BLOCKED,
    LEAD_STATUS.WECHAT_RISK_CONTROL,
    LEAD_STATUS.WECHAT_ADD_REJECTED,
    LEAD_STATUS.WECHAT_TARGET_NOT_FOUND,
    LEAD_STATUS.WECHAT_ACCEPTANCE_EXHAUSTED,
  ]),
  NEUTRAL: new Set([LEAD_STATUS.NEW_LEAD, LEAD_STATUS.WECHAT_ALREADY_FRIEND]),
} as const;

/** 判定函数（纯函数，无副作用） */
export function isSuccess(status: string): boolean {
  return LEAD_STATUS_GROUPS.SUCCESS.has(status as LeadStatus);
}

export function isRunning(status: string): boolean {
  return LEAD_STATUS_GROUPS.RUNNING.has(status as LeadStatus);
}

export function isFailure(status: string): boolean {
  return LEAD_STATUS_GROUPS.FAILURE.has(status as LeadStatus);
}

export function isNeutral(status: string): boolean {
  return LEAD_STATUS_GROUPS.NEUTRAL.has(status as LeadStatus);
}

/** 统计一组 leads */
export function countLeadsByStatus(leads: Pick<Lead, 'status'>[]): {
  success: number;
  running: number;
  failure: number;
  total: number;
} {
  let success = 0;
  let running = 0;
  let failure = 0;
  for (const lead of leads) {
    const status = lead.status;
    if (isSuccess(status)) success++;
    else if (isRunning(status)) running++;
    else if (isFailure(status)) failure++;
    // NEUTRAL 不计入统计值，仅计入总数
  }
  return { success, running, failure, total: leads.length };
}
```

**修改文件**：
| 文件 | 变更 |
|------|------|
| `src/components/features/board/KpiStrip.tsx` | 移除硬编码分组，改用 `countLeadsByStatus`；新增副标题文案区分样本模式/全库模式；后续将接受 stats 作为可选 prop |

---

#### 件 2：DevTesting 联通看板

**修改文件**：
| 文件 | 变更 |
|------|------|
| `src/hooks/useLeadJobs.ts` | 新增导出 `registerJobStarted(leadId: string, jobId: string)` |
| `src/hooks/useAudits.ts` | `useExecuteRpaMutation.onSuccess` 调用 `registerJobStarted` |
| `src/components/features/DevTesting.tsx` | onSubmit 拿到 jobId 后调用 `registerJobStarted`；toast 新增"在看板查看"按钮 |
| `src/components/features/LeadsList.tsx` | 移除"立即执行"按钮；`onTriggerJob` prop 改为可选 |
| `src/components/features/board/LeadHeader.tsx` | 按钮文案改为"重跑" |
| `src/components/features/board/LeadsBoard.tsx` | `onTriggerJob` 改为可选，不传也可以渲染 |
| `src/hooks/useLeads.ts` | Lead.id 从 number 改为 string |
| `src/components/layout/AppShell.tsx` | 移除 parseInt(leadId)，直接用 string |
| `src/components/features/board/LeadsBoard.tsx` | 移除 parseInt(leadId)，直接用 string |
| `src/components/features/LeadsList.tsx` | selectedId 类型改为 string |
| 其他文件 | grep `parseInt.*\.id` 检查并移除 |

**src/hooks/useLeadJobs.ts 新增代码（精确抄）**：
```typescript
export function registerJobStarted(leadId: string, jobId: string): void {
  const state = useLeadJobsStore.getState();
  state.appendJob(leadId, jobId);
  state.updateJobMeta(jobId, {
    lastStatus: 'QUEUED',
    lastTimestamp: Date.now(),
    stepCount: 0,
  });
}
```

---

#### 件 3：后端 KPI Stats 接口

**后端新增/修改文件**：
| 文件 | 变更 |
|------|------|
| `python/backend/app/schemas/lead.py` | 新增 `LeadStatsResponse` Pydantic 模型 |
| `python/backend/app/storage/sqlite_store.py` | 新增 `count_leads_by_status()` 方法 |
| `python/backend/app/services/lead_service.py` | 新增 `compute_lead_stats()` 方法 |
| `python/backend/app/api/routes/leads.py` | 新增 `GET /api/v1/leads/stats` 路由 |
| `python/backend/tests/test_lead_stats.py` | 新增单测（可选但推荐） |

**python/backend/app/schemas/lead.py 新增（精确抄）**：
```python
from datetime import datetime, timezone

class LeadStatsResponse(BaseModel):
    total: int
    by_status: dict[str, int]
    success: int
    running: int
    failure: int
    ts: str

    @classmethod
    def make(cls, by_status: dict[str, int]) -> "LeadStatsResponse":
        # 确保所有 15 个 LeadStatus 都存在，缺失补 0
        full_by_status: dict[str, int] = {status: by_status.get(status, 0) for status in LeadStatus}
        total = sum(full_by_status.values())
        success = full_by_status[LeadStatus.WECHAT_ACCEPTED]
        running = sum(full_by_status[s] for s in [
            LeadStatus.CALLING,
            LeadStatus.INTENT_CONFIRMED,
            LeadStatus.RPA_PENDING_APPROVAL,
            LeadStatus.RPA_SIMULATED,
            LeadStatus.RPA_EXECUTING,
            LeadStatus.WECHAT_ADD_REQUESTED,
        ])
        failure = sum(full_by_status[s] for s in [
            LeadStatus.RPA_FAILED,
            LeadStatus.RPA_BLOCKED,
            LeadStatus.WECHAT_RISK_CONTROL,
            LeadStatus.WECHAT_ADD_REJECTED,
            LeadStatus.WECHAT_TARGET_NOT_FOUND,
            LeadStatus.WECHAT_ACCEPTANCE_EXHAUSTED,
        ])
        ts = datetime.now(timezone.utc).isoformat()
        return cls(
            total=total,
            by_status=full_by_status,
            success=success,
            running=running,
            failure=failure,
            ts=ts,
        )
```

**python/backend/app/storage/sqlite_store.py 新增（精确抄）**：
```python
    def count_leads_by_status(self) -> dict[str, int]:
        """返回 {status: count}，仅统计库中存在的 status，缺失由 schema.make() 补 0"""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM leads GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}
```

**python/backend/app/services/lead_service.py 新增（精确抄）**：
```python
    def compute_lead_stats(self) -> LeadStatsResponse:
        by_status = self.store.count_leads_by_status()
        return LeadStatsResponse.make(by_status)
```

**python/backend/app/api/routes/leads.py 新增（精确抄）**：
```python
@router.get("/stats", response_model=LeadStatsResponse)
def get_lead_stats(
    service: LeadService = Depends(get_lead_service),
) -> LeadStatsResponse:
    return service.compute_lead_stats()
```

**前端新增/修改文件**：
| 文件 | 变更 |
|------|------|
| `src/hooks/useLeadsStats.ts` | 新增 `useLeadsStatsQuery` hook |
| `src/components/features/board/KpiStrip.tsx` | 接受可选 `stats` prop；优先用 stats，降级用 leads 列表；副标题文案切换 |

**src/hooks/useLeadsStats.ts（精确抄）**：
```typescript
import { useQuery } from '@tanstack/react-query';
import { requestLocalApi } from '@/lib/api';

export interface LeadStats {
  total: number;
  by_status: Record<string, number>;
  success: number;
  running: number;
  failure: number;
  ts: string;
}

export function useLeadsStatsQuery(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['leads-stats'],
    queryFn: async () => requestLocalApi<LeadStats>('/api/v1/leads/stats'),
    refetchInterval: 8000,
    enabled: options?.enabled ?? true,
    // 失败静默降级，不抛错
    retry: false,
    staleTime: 8000,
  });
}
```

**KpiStrip 升级（精确变更要点）**：
- Props 新增 `stats?: LeadStats`
- 优先用 `stats.total/success/running/failure`
- 无 stats 或 stats 失败时降级用 `countLeadsByStatus(leads)`
- 副标题文案：
  - stats 模式：总数副标题 "全库实时计数"
  - 样本模式：总数副标题 `近 ${leads.length} 条样本`；成功率副标题 `(基于 N=${leads.length} 条样本，仅供参考)`
- `src/components/layout/AppShell.tsx` 中 `LeadsBoard` 传入 stats

---

### 测试清单（Cycle 2）

| ID | 分类 | 用例 | 前置 | 触发 | 期望 |
|----|------|------|------|------|------|
| C2-A1 | KPI 口径 | 状态分组判定 | - | 调用 `isRunning('WECHAT_ALREADY_FRIEND')` / `isFailure('WECHAT_ADD_REJECTED')` | `false` / `true` |
| C2-A2 | KPI 口径 | 全库 stats 正常 | stats 接口 200 | KpiStrip 渲染 | 总数用 `stats.total`，副标题 "全库实时计数" |
| C2-A3 | KPI 口径 | stats 接口失败 | stats 404/500 | KpiStrip 渲染 | 降级用列表样本，副标题 "近 N 条样本" |
| C2-B1 | DevTesting 联通 | DevTesting 触发 job | 打开 DevTesting | 执行一次 dryRun | toast 出现"在看板查看"按钮；点击后 hash 正确跳转；看板能看到该 job |
| C2-B2 | DevTesting 联通 | 看板 LeadsList 无"立即执行" | 打开看板 | 查看线索行 | 行内无按钮，只有 LeadRowSummary |
| C2-B3 | DevTesting 联通 | LeadHeader 文案 | 打开抽屉 | 查看按钮 | 文案为"重跑" |
| C2-B4 | DevTesting 联通 | lead.id 类型 | 全端 grep | 搜索 `parseInt.*\.id` | 无残留 |
| C2-C1 | 后端 stats | 空库统计 | 空库 | 调 `GET /api/v1/leads/stats` | `total=0, success=0, running=0, failure=0, by_status` 包含所有 15 个 key |
| C2-C2 | 后端 stats | 各状态覆盖 | 有多个状态 | 调接口 | 各状态正确归类统计 |
| C2-C3 | 后端 stats | 鉴权 | 无 token | 调接口 | 401 |

---

### 划清范围重申

✅ **在范围内**：
- KPI 口径修正
- 状态分组抽离
- DevTesting 看板联通
- 后端 stats 接口 + 前端接入
- Lead.id 类型 string 化

❌ **不在范围内**（另起任务线）：
- 看板分页/筛选
- audit_events 基 KPI（今日新增/今日成功）
- LeadHeader 重跑按钮的完整流程改造（仍直调 add-wechat）
- `useDevTestStore` 改造（不动）

