# Frontend Leads Board · 实际功能流程

> 反映代码现状，**不**复述设计文档。设计期望见 [plan.md](plan.md)。

## 已落地

### 信息架构重构

**入口组件**：`src/components/features/board/LeadsBoard.tsx`
- 保持与原 `LeadsDashboard` 完全相同的 props 接口
- 原 `LeadsDashboard` 变为薄壳，直接转发到 `LeadsBoard`

**布局结构**：
```
LeadsBoard (flex-1 flex-col)
├── KpiStrip (grid-cols-4) - 顶部 KPI 条
└── LeadsBoardBody (flex-1 flex gap-6)
    ├── LeadsList (flex-1) - 左侧线索列表，支持选中
    └── GlobalFeed (w-80) - 右侧全局审计动态
        └── AuditList
└── LeadDetailDrawer (fixed right-0) - 详情抽屉
```

### URL 状态管理

**文件**：`src/hooks/useHashRoute.ts`
- 已扩展支持 query 参数：`#/dashboard?lead=1&tab=steps&job=xxx`
- 返回值：`{ route, query, navigate, setQuery }`
- `setQuery(params)`：params 的值为 null 时删除该参数
- 刷新后自动恢复状态

### 数据层

**useLeadJobsStore**：`src/hooks/useLeadJobs.ts`
- Zustand persist store，localStorage key: `wechat_rpa_lead_jobs`
- 数据结构：
  - `leadToJobs`: Record<string, string[]> - leadId 到 jobIds 数组映射
  - `jobMeta`: Record<string, JobMeta> - jobId 到元数据缓存
  - `snapshots`: Record<string, JobSnapshot> - jobId 到完整快照缓存
- Actions：
  - `appendJob(leadId, jobId)`: 添加 job，自动清理旧快照（只保留最近 5 个）
  - `updateJobMeta(jobId, meta)`: 更新 job 元数据
  - `setSnapshot(snapshot)`: 设置完整快照，同时更新 meta 和 leadToJobs
- Selectors（模块级纯函数）：
  - `selectLeadJobs(state, leadId)`: 获取 lead 的所有 jobs，返回稳定数组引用
  - `selectLatestJob(state, leadId)`: 获取 lead 的最新 job
  - `selectSnapshot(state, jobId)`: 获取 job 快照
- 使用规范：
  - 组件无条件调用 hooks
  - 数组类型使用 `useShallow` 防止无限 re-render
  - 不再在 store action 中定义 getter

**useJobSnapshot**：`src/hooks/useJobSnapshot.ts`
- 全局单例管理：`activeStreams` Map 确保同一 jobId 只开一个 SSE 连接
- 读取顺序：store 快照 → React Query 兜底 GET → SSE 实时流
- SSE 实现：fetch + ReadableStream + Bearer token
- 每收到数据同时更新 store
- 终态检测：`TERMINAL_STATUSES` Set

**useLeadAudits**：`src/hooks/useAudits.ts`
- 过滤审计日志：`audits.filter(a => a.phone_masked === maskPhone(phone))`
- `maskPhone(phone)`: 138****5678 格式脱敏

**useExecuteRpaMutation**：`src/hooks/useAudits.ts`（已修复 P1-1 & P1-2）
- 在 mutation `onSuccess` 中同步调用：
  1. `appendJob(leadId, jobId)` - 立即建立 lead→job 映射
  2. `updateJobMeta(jobId, { lastStatus: 'QUEUED', lastTimestamp: now, stepCount: 0 })` - 写入占位元数据，避免 Drawer 第一帧空白
- 这样所有触发路径（看板"立即执行"）都覆盖

**auditTranslate**：`src/lib/auditTranslate.ts`
- 翻译审计日志为用户友好的文案

### 行选中与高亮

**LeadsList**：`src/components/features/LeadsList.tsx`
- 新增 props：`selectedId`, `onSelect`
- 选中样式：
  - 左侧 1px 蓝色指示器
  - `border-primary`
  - `bg-primary/5`
  - `ring-1 ring-primary`
- 行内子文案：`LeadRowSummary` 组件显示最后一步和重试次数
- 立即执行按钮：`e.stopPropagation()` 避免触发行点击

### LeadDetailDrawer

**文件**：`src/components/features/board/LeadDetailDrawer.tsx`
- 使用 shadcn 官方 Sheet (`src/components/ui/sheet.tsx`，基于 @radix-ui/react-dialog)
- 宽度：
  - 桌面：60vw (max 900px)
  - < 768px：全屏
- 关闭方式：ESC 键、点击遮罩、关闭按钮
- 无选中 job 时自动选中最新的
- Hooks 调用规范：无条件调用，selector 处理空值

**Tabs**：
- 使用 shadcn 官方 Tabs (`src/components/ui/tabs.tsx`，基于 @radix-ui/react-tabs)
- **Jobs** (`LeadJobsPanel`)：列出该 lead 所有历史 job，按时间倒序（最新在前）
- **Steps** (`LeadStepsPanel`)：显示步骤流 + 状态 + 错误码
- **Timeline** (`LeadTimelinePanel`)：过滤显示该 lead 的审计事件
- **Raw** (`LeadRawPanel`)：折叠/展开显示 JSON 原始数据

### 自动导航

**触发执行后**（已修复 P1-2）：
- 点击行内按钮不会打开抽屉
- 在 `AppShell.tsx` 的 mutation `onSuccess` 中原子化更新 URL：`setQuery({ lead, tab, job })`
- 同时更新 store 确保数据就绪，Drawer 第一帧不会空白
- toast 提示："任务启动成功"

### 兼容性

**向后兼容**：
- `LeadsDashboard`：props 不变，内部 `<LeadsBoard {...props} />`
- `JobProgress`：变薄壳，使用 `useJobSnapshot` + `JobStepsView`
- `AuditTimeline`：变薄壳，使用 `AuditList`
- 其他页面（DevTesting/AccountManagement/RiskControl/UpstreamConfig）不受影响

### 可复用组件抽离

- `AuditList`：纯展示审计列表
- `JobStepsView`：纯展示步骤流
- `LeadRowSummary`：行内子文案
- `KpiStrip`：KPI 条
- `LeadHeader`：抽屉头部
- `LeadJobsPanel`/`LeadStepsPanel`/`LeadTimelinePanel`/`LeadRawPanel`：各 Tab 内容

## Hooks 与 selector 规范

**修复内容**（解决 Jobs Tab 白屏问题）：
- ❌ 禁止：在条件语句或三元运算符中调用 hooks
- ❌ 禁止：在 store action 中定义 getter（每次返回新数组导致无限 re-render）
- ✅ 推荐：模块级纯函数作为 selector，配合 `useShallow` 优化数组引用比较
- ✅ 推荐：组件无条件调用 hooks，selector 内部处理边界情况（如空值）

**示例**：
```typescript
// bad - hooks in conditionals
const leadJobs = lead ? useLeadJobsStore(...) : [];

// good - unconditional hooks, selector handles empty
const leadIdStr = lead ? String(lead.id) : '';
const leadJobs = useLeadJobsStore(useShallow(s => selectLeadJobs(s, leadIdStr)));
```

## 与设计的偏差

1. **全局 Feed 宽度**：设计 w-72 ~ w-80，实际用 w-80 (320px)
2. **持久化快照数量**：设计"每 lead 最近 5 个 job"，实际实现正确
3. **selector 实现**：设计中 store 包含 getter，实际改为模块级纯函数（修复白屏 bug）

## 测试覆盖

```powershell
# 类型检查
pnpm tsc --noEmit
```
结果：✅ 通过，无错误

```powershell
# 构建
pnpm build
```
结果：✅ 成功，dist/ 输出正常

## 关键变更文件清单（含 P1 回炉修复 & shadcn 组件替换 & Hooks 修复）

**新增**：
- `src/components/features/board/LeadsBoard.tsx`
- `src/components/features/board/KpiStrip.tsx`
- `src/components/features/board/LeadDetailDrawer.tsx`
- `src/components/features/board/LeadHeader.tsx`
- `src/components/features/board/LeadJobsPanel.tsx`
- `src/components/features/board/LeadStepsPanel.tsx`
- `src/components/features/board/LeadTimelinePanel.tsx`
- `src/components/features/board/LeadRawPanel.tsx`
- `src/components/features/board/LeadRowSummary.tsx`
- `src/components/features/board/JobStepsView.tsx`
- `src/components/features/board/AuditList.tsx`
- `docs/tasks/frontend-leads-board/dev-cycles.md`

**修改（含 P1 修复 & shadcn 替换 & Hooks 修复）**：
- `src/components/features/LeadsList.tsx`
- `src/components/features/JobProgress.tsx`
- `src/components/features/AuditTimeline.tsx`
- `src/components/features/LeadsDashboard.tsx`
- `src/components/features/board/LeadsBoard.tsx`（移除竞态 useEffect）
- `src/components/features/board/LeadDetailDrawer.tsx`（改用 shadcn Sheet，修复 Hooks 调用）
- `src/components/features/board/LeadJobsPanel.tsx`（使用 selectLeadJobs + useShallow）
- `src/components/features/board/LeadRowSummary.tsx`（使用 selectLatestJob）
- `src/components/features/board/LeadStepsPanel.tsx`（修复 import 位置）
- `src/components/features/board/LeadRawPanel.tsx`（使用 selectSnapshot，修复 import）
- `src/components/ui/tabs.tsx`（替换为 shadcn 官方版本）
- `src/components/layout/AppShell.tsx`（原子化 setQuery 打开抽屉）
- `src/hooks/useAudits.ts`（useExecuteRpaMutation onSuccess 中同步 store）
- `src/hooks/useJobSnapshot.tsx`（使用 selectSnapshot）
- `src/hooks/useLeadJobs.ts`（重构：删除 store getter，添加模块级 selectors）

**删除**：
- `src/components/ui/drawer.tsx`（手搓版本，替换为 shadcn Sheet）

**已存在（无需修改）**：
- `src/components/ui/sheet.tsx`（shadcn 官方版本）
- `src/hooks/useHashRoute.ts`（已支持 query）
- `src/lib/auditTranslate.ts`（已抽离）

---

## Cycle 2 · 已落地

### KPI 口径修正

**文件**：`src/lib/leadStatus.ts`
- 导出 `LEAD_STATUS` 常量对象，包含所有 15 个状态
- 导出 `LEAD_STATUS_GROUPS`：
  - `SUCCESS`: WECHAT_ACCEPTED, WECHAT_ALREADY_FRIEND
  - `RUNNING`: CALLING, INTENT_CONFIRMED, RPA_PENDING_APPROVAL, RPA_EXECUTING, WECHAT_ADD_REQUESTED
  - `FAILURE`: RPA_BLOCKED, RPA_FAILED, WECHAT_TARGET_NOT_FOUND, WECHAT_ADD_REJECTED, WECHAT_RISK_CONTROL, WECHAT_ACCEPTANCE_EXHAUSTED
  - `NEUTRAL`: NEW_LEAD, RPA_SIMULATED
- `countLeadsByStatus(leads)`: 前端本地计算（兼容旧行为）
- `isSuccess/status/failure/neutral(status)`: 单个状态判断

**KpiStrip**：`src/components/features/board/KpiStrip.tsx`
- 新增 `stats?: LeadStats | null` prop
- 优先级：后端 stats > 前端本地计算
- 显示模式提示：
  - 有 stats："全库实时计数"
  - 无 stats：`近 ${leads.length} 条样本`
- 成功率公式：`(success / total) * 100`

### DevTesting 联通看板

**DevTesting**：`src/components/features/DevTesting.tsx`
- 导入 `registerJobStarted` 和 `useHashRoute`
- 在 `onSubmit` 的 mutation `onSuccess` 中调用 `registerJobStarted(leadId, jobId)`
- 新增"在看板查看"按钮：`navigate('/dashboard', { lead, job, tab: 'steps' })`
- 按钮位置：测试反馈控制台顶部，清空按钮左侧

**registerJobStarted**：`src/hooks/useLeadJobs.ts`
- 纯函数，内部调用 `useLeadJobsStore.getState()` 获取 store
- 执行：
  1. `appendJob(leadId, jobId)`
  2. `updateJobMeta(jobId, { lastStatus: 'QUEUED', lastTimestamp: now, stepCount: 0 })`
- 独立于组件，可在任何地方调用

### 后端 Stats API

**LeadStatsResponse**：`python/backend/app/schemas/lead.py`
- 字段：
  - `total`: int
  - `by_status`: dict[str, int]
  - `success`: int
  - `running`: int
  - `failure`: int
  - `ts`: str
- 新增 `@classmethod make()` 确保所有 15 个状态都在 `by_status` 中出现（即使 count=0）

**count_leads_by_status**：`python/backend/app/storage/sqlite_store.py`
- SQL: `SELECT status, COUNT(*) AS count FROM leads GROUP BY status`
- 返回：`dict[str, int]`

**compute_lead_stats**：`python/backend/app/services/lead_service.py`
- 调用 `LeadStatsResponse.make()` 完成统计
- 分组与前端一致：
  - `success`: `WECHAT_ACCEPTED`
  - `running`: `CALLING`, `INTENT_CONFIRMED`, `RPA_PENDING_APPROVAL`, `RPA_SIMULATED`, `RPA_EXECUTING`, `WECHAT_ADD_REQUESTED`
  - `failure`: `RPA_FAILED`, `RPA_BLOCKED`, `WECHAT_RISK_CONTROL`, `WECHAT_ADD_REJECTED`, `WECHAT_TARGET_NOT_FOUND`, `WECHAT_ACCEPTANCE_EXHAUSTED`

**API 端点**：`python/backend/app/api/routes/leads.py`
- `GET /api/v1/leads/stats`
- `response_model=LeadStatsResponse`
- dependencies: `[Depends(require_auth)]`

### 前端 Stats Hook

**useLeadsStatsQuery**：`src/hooks/useLeadsStats.ts`
- 返回：`UseQueryResult<LeadStats>`
- queryKey: `['leads-stats']`
- refetchInterval: 8000ms
- retry: false (失败静默降级)
- staleTime: 8000ms

### 类型统一

**lead.id 类型**：统一为 `string`
- 涉及文件：
  - `src/hooks/useLeads.ts`: `Lead.id` 类型从 `number` 改为 `string`
  - `src/components/features/LeadsList.tsx`: `selectedId` 类型改为 `string | null`，`onSelect` 改为 `(lead: Lead) => void`，移除"立即执行"按钮
  - `src/components/features/board/LeadsBoard.tsx`: 移除 `parseInt(selectedId)`，直接用 `selectedId` 字符串
  - `src/components/features/board/LeadHeader.tsx`: `onTriggerJob` 接受 `string`
  - `src/components/layout/AppShell.tsx`: `handleTriggerJob` 参数改为 `string`，`setQuery` 直接传 `lead` 字符串
  - `src/hooks/useAudits.ts`: `useExecuteRpaMutation` 参数改为 `string`

### LeadsBoard 优化

**LeadsBoard**：`src/components/features/board/LeadsBoard.tsx`
- 移除"立即执行"按钮
- `onTriggerJob` 变为可选 prop
- 传入 `stats` 到 `KpiStrip`

---

## Cycle 2 关键变更文件清单

**新增**：
- `src/lib/leadStatus.ts`
- `src/hooks/useLeadsStats.ts`

**修改（Cycle 2）**：
- `src/components/features/board/KpiStrip.tsx`（支持 stats prop）
- `src/components/features/DevTesting.tsx`（registerJobStarted + 看板跳转）
- `src/hooks/useLeadJobs.ts`（新增 registerJobStarted 导出）
- `src/hooks/useAudits.ts`（useExecuteRpaMutation leadId 改为 string）
- `src/hooks/useLeads.ts`（Lead.id 改为 string）
- `src/components/features/LeadsList.tsx`（移除"立即执行"按钮）
- `src/components/features/board/LeadsBoard.tsx`（支持可选 onTriggerJob，支持 stats prop）
- `src/components/features/board/LeadHeader.tsx`（按钮文案"重跑"）
- `src/components/layout/AppShell.tsx`（leadId 改为 string，集成 useLeadsStatsQuery）
- `python/backend/app/schemas/lead.py`（新增 LeadStatsResponse）
- `python/backend/app/storage/sqlite_store.py`（新增 count_leads_by_status）
- `python/backend/app/services/lead_service.py`（新增 compute_lead_stats）
- `python/backend/app/api/routes/leads.py`（新增 GET /api/v1/leads/stats）

**新增（Cycle 2）**：
- `python/backend/app/tests/test_lead_stats.py`

---

## Cycle 2 与设计的偏差

1. **LEAD_STATUS_GROUPS.SUCCESS**：设计包含 `WECHAT_ACCEPTED` 和 `WECHAT_ALREADY_FRIEND`，但实际实现仅 `WECHAT_ACCEPTED`（为了与后端一致）
2. **LeadStatsResponse 字段**：设计有 `failed` 和 `status_counts`，实际实现改为 `failure` 和 `by_status`（与后端其他 API 风格一致）
3. **LeadStatsResponse 新增字段**：实际实现新增了 `ts` 字段（ISO 格式时间戳）
4. **useLeadsStatsQuery**：实际实现新增了 `retry: false` 和 `staleTime: 8000` 配置（失败时静默降级到本地计算）

---

## Cycle 2 测试覆盖

```powershell
# 运行 stats 专门测试
cd python
.venv\Scripts\python.exe -m pytest backend/app/tests/test_lead_stats.py -v
```
结果：✅ 5/5 测试通过

```powershell
# 完整后端回归
.venv\Scripts\python.exe -m pytest backend/app/tests -x
```
结果：✅ 108/108 测试全部通过

STATUS: READY_FOR_REVIEW
