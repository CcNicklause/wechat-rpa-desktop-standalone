# frontend-leads-board · 编排状态

> 任务线：`frontend-leads-board`
> 启动时间：2026-06-29
> 模式：legacy（前端看板改造，无后端协议变动）

## 节点状态

| # | 节点 | 状态 | 产物 | 备注 |
|---|-----|------|-----|-----|
| 0 | 启动登记 | DONE | state.md | 本文件 |
| 1 | plan-agent: 计划文档 | DONE | plan.md | 需求 + 设计 + 测试清单 |
| 2 | coder-agent: 实施 | DONE | 代码 + flow.md | 双栏 + Lead 详情 Drawer（已回环修 2 P1 + UI 替换为 shadcn 官方 Sheet/Tabs + 修复 Hooks 规则违例导致白屏） |
| 3 | plan-agent: 对账 | DONE | plan.md 优化清单 | P1 已修复，已收敛 |
| 4 | test-agent: 测试 | DONE | test.md | 已完成静态分析 + 编译验证，详见 test.md |

## 范围

- ✅ 看板信息架构重构：KPI 条 + LeadsList（左主）+ 全局 Feed（右窄）+ Lead 详情 Drawer
- ✅ 单线索可下钻：jobs/steps/timeline/raw 四个 Tab；当前/历史 job 均可查看
- ✅ 数据层：前端维护 lead→jobs 映射；新增 `useLeadJobs`/`useJobSnapshot` hooks
- ✅ URL 状态：`#/dashboard?lead=1&tab=steps&job=xxx` 可分享/刷新不丢上下文
- ✅ **不动后端**：所有改造在 `src/` 内完成
- ✅ P1-1 修复：`useExecuteRpaMutation` onSuccess 中立即 `appendJob`
- ✅ P1-2 修复：在 mutation onSuccess 中同步 store + 原子化更新 URL，移除竞态 useEffect
- ✅ UI 替换：手搓 Drawer/Tabs 替换为 shadcn 官方 Sheet/Tabs（基于 Radix）
- ✅ Hooks 规则修复：无条件调用 hooks，模块级 selectors + `useShallow`

## 修复的 bug 总结

1. **Jobs Tab 白屏**：违反 React Hooks 规则，在三元表达式中调用 hooks → 改为无条件调用，selector 处理空值
2. **无限 re-render**：store getter 每次返回新数组 → 改为模块级 selector + `useShallow`
3. **全局 store 订阅**：`useLeadJobsStore()` 不传 selector → 改为分别 selector actions
4. **import 位置错误**：import 在文件底部 → 移到顶部
5. **Drawer API 不符**：手搓 Drawer → 改用 shadcn Sheet（`onOpenChange` 替代 `onClose`）

## 当前等待

- 测试已完成：静态分析 + 编译验证通过
- 结果：ALL_PASSED，无 BLOCKER 问题
- 详见：test.md
- 下一步：如无手工验证发现的问题，可发布

## 关联文档

- 设计计划文档：[plan.md](plan.md)
- 功能流程文档：[flow.md](flow.md)
- 现有看板代码入口：[src/components/features/LeadsDashboard.tsx](../../../src/components/features/LeadsDashboard.tsx)

---

## Cycle 2 · 节点状态（看板数据流真实化 + DevTesting 联通）

| # | 节点 | 状态 | 产物 | 备注 |
|---|-----|------|-----|-----|
| C2-0 | Cycle 2 启动登记 | DONE | state.md（追加本章节） | 首次涉及后端改动 |
| C2-1 | plan-agent: Cycle 2 设计 | DONE | plan.md 追加 Cycle 2 章节 | 需求 + 技术设计 + 测试清单已完成 |
| C2-2 | coder-agent: Cycle 2 实施 | DONE | 代码 + flow.md（追加） | 后端 stats + 前端口径修正 + DevTesting 联通 |
| C2-3 | plan-agent: Cycle 2 对账 | DONE | plan.md 追加对账清单 | Cycle 2 已完整收敛，无 P0/P1 问题 |
| C2-4 | test-agent: Cycle 2 测试 | ✅ DONE | 执行看板交互回归测试 | test.md 已更新 |

### Cycle 2 范围

- ✅ **件 1**：前端 KPI 口径修正（抽离 `src/lib/leadStatus.ts`）
- ✅ **件 2**：DevTesting 联通看板（移除"立即执行"按钮 + `registerJobStarted` + toast 跳转看板）
- ✅ **件 3**：后端 KPI Stats 接口（`GET /api/v1/leads/stats` + 前端接入）
- ✅ **新增**：后端单测 `python/backend/app/tests/test_lead_stats.py`（覆盖空库/单状态/多状态/全状态）
- ✅ **不动**：`useDevTestStore`、重跑按钮完整流程、今日新增等 audit_events 基 KPI

### Cycle 2 当前等待

- ✅ plan.md Cycle 2 章节已追加完成
- ✅ coder-agent 已完成 Cycle 2 实施
- ✅ 后端单测 + 回归已完成（108/108 全通过）
- ✅ plan-agent 对账已完成，Cycle 2 已完整收敛，无 P0/P1 问题
- ✅ test-agent 已完成 Cycle 2 测试，结果：ALL PASSED
- 下一步：可发布

STATUS: CONVERGED

---

## Cycle 9 · 节点状态（KPI「执行中」口径收窄）

| # | 节点 | 状态 | 产物 | 备注 |
|---|-----|------|-----|-----|
| C9-0 | 根因核实 | DONE | demo.db 查询 | 推翻"running 孤儿"误判：实测 `RPA_EXECUTING`=0、running job=0；"19 个执行中"= running 桶把 CALLING(11)+RPA_SIMULATED(8) 僵尸中间态算入 |
| C9-1 | 口径确认 | DONE | 对话 | 「执行中」= 引擎链路活跃：`RPA_PENDING_APPROVAL` + `RPA_EXECUTING` |
| C9-2 | 实施 | DONE | lead.py / leadStatus.ts / KpiStrip.tsx / test_lead_stats.py | 后端口径收窄 + 前端镜像同步 + 副标题文案 + 测试断言同步 |
| C9-3 | 验证 | DONE | pytest + tsc | 109 passed；tsc 无报错 |

### Cycle 9 范围

- ✅ 后端 `LeadStatsResponse.make` 的 running 桶从 6 态（CALLING/INTENT_CONFIRMED/RPA_PENDING_APPROVAL/RPA_SIMULATED/RPA_EXECUTING/WECHAT_ADD_REQUESTED）收窄为 2 态（`RPA_PENDING_APPROVAL` + `RPA_EXECUTING`）。
- ✅ 前端 `LEAD_STATUS_GROUPS.RUNNING`（`src/lib/leadStatus.ts`）镜像同步，保持与后端 stats 对齐。
- ✅ `KpiStrip`「执行中」副标题由"客户端引擎正在操作的队列数"改为"排队待执行 + 引擎执行中"，与口径一致。
- ✅ `test_lead_stats.py::test_all_statuses_once` running 断言 6→2 并更新注释。
- ✅ 被移出 running 的状态（CALLING/INTENT_CONFIRMED/RPA_SIMULATED/WECHAT_ADD_REQUESTED）仍计入「线索总数」与成功率分母，但不再误报为执行中。

### Cycle 9 验证

```powershell
cd python; $env:PYTHONPATH='.'; uv run pytest backend/app/tests -q
```
结果：✅ 109 passed, 4 warnings

```powershell
npx tsc --noEmit -p .
```
结果：✅ 无报错

STATUS: CONVERGED

---

## Cycle 8 · 节点状态（小窗口抽屉布局修复）

| # | 节点 | 状态 | 产物 | 备注 |
|---|-----|------|-----|-----|
| C8-0 | 问题定位 | DONE | 截图 + 代码检查 | 小窗口下抽屉宽度、过程页固定高度、日志裁切、状态行挤压 |
| C8-1 | TDD 测试 | DONE | `scripts/tests/boardCopy.test.mjs` | 锁定响应式宽度、去固定高度、可换行布局 |
| C8-2 | 前端实施 | DONE | Drawer / Process / Steps / Header / Overview | 修复窄窗口错位与裁切 |
| C8-3 | 验证 | DONE | 测试命令结果 | 布局测试与 `pnpm build` 通过 |

### Cycle 8 范围

- ✅ 详情抽屉保持接近旧尺寸的 `60vw / max 900px`，同时不再受默认 `sm:max-w-sm` 限制。
- ✅ `过程` Tab 移除固定 `h-[calc(100vh-280px)]`。
- ✅ 关键日志不再 `overflow-hidden` 裁切时间线圆点和状态 Badge。
- ✅ 步骤头部、底部状态、步骤 tag、错误码允许换行，避免窄宽互相挤压。
- ✅ 概览信息块小窗口下一列展示，抽屉头部允许换行。
- ✅ 线索选中态移除整圈 `ring`，避免右侧边框在遮罩下显得过粗。
- ✅ 抽屉头部右侧使用 `pr-16` 并与左侧 padding 分离，避免关闭按钮与“重跑”交错。

### Cycle 8 验证

```powershell
node --test scripts/tests/boardCopy.test.mjs
```
结果：✅ 6/6 测试通过

```powershell
pnpm -s build
```
结果：✅ 构建通过

STATUS: CONVERGED

---

## Cycle 7 · 节点状态（概览展示验证语）

| # | 节点 | 状态 | 产物 | 备注 |
|---|-----|------|-----|-----|
| C7-0 | 需求确认 | DONE | 对话确认 | 概览中轻量展示验证语 |
| C7-1 | TDD 测试 | DONE | `scripts/tests/boardCopy.test.mjs` | 断言验证语取值与空值文案 |
| C7-2 | 前端实施 | DONE | `LeadOverviewPanel`、`leadOverviewCopy.ts` | 概览新增“验证语”信息块 |
| C7-3 | 验证 | DONE | 测试命令结果 | 文案测试与 `pnpm build` 通过 |

### Cycle 7 范围

- ✅ 详情抽屉 `概览` 增加“验证语”信息块。
- ✅ 验证语取值优先级：`greeting` → `verification_message` → `verify_message` → `add_reason`。
- ✅ 验证语为空时显示 `未设置`。
- ✅ 不新增 Tab，不改后端协议。

### Cycle 7 验证

```powershell
node --test scripts/tests/boardCopy.test.mjs
```
结果：✅ 4/4 测试通过

```powershell
pnpm -s build
```
结果：✅ 构建通过

STATUS: CONVERGED

---

## Cycle 6 · 节点状态（详情抽屉用户视角收敛）

| # | 节点 | 状态 | 产物 | 备注 |
|---|-----|------|-----|-----|
| C6-0 | 口径确认 | DONE | state.md | 用户认可从技术 Tab 收敛为用户任务视角 |
| C6-1 | TDD 测试 | DONE | `scripts/tests/boardCopy.test.mjs` | 断言三 Tab 与旧 URL 映射 |
| C6-2 | 前端实施 | DONE | `LeadOverviewPanel`、`LeadProcessPanel`、`LeadDetailDrawer` | 默认进入概览，过程合并日志与步骤，历史保留 job 列表 |
| C6-3 | 验证 | DONE | 测试命令结果 | 6/6 前端文案测试通过，`pnpm build` 通过 |

### Cycle 6 范围

- ✅ 详情抽屉从 `执行记录/执行步骤/审计日志/原始数据` 收敛为 `概览/过程/历史`。
- ✅ `概览` 提供状态、最近执行和下一步建议。
- ✅ `过程` 合并关键日志与执行步骤。
- ✅ `历史` 保留历史执行记录。
- ✅ 旧 URL 的 `jobs/steps/timeline/raw` 映射到新 Tab。

### Cycle 6 验证

```powershell
node --test scripts/tests/leadDisplay.test.mjs scripts/tests/boardCopy.test.mjs
```
结果：✅ 6/6 测试通过

```powershell
pnpm build
```
结果：✅ 构建通过

STATUS: CONVERGED

---

## Cycle 5 · 节点状态（详情 Tab 中文化 + 数据映射说明）

| # | 节点 | 状态 | 产物 | 备注 |
|---|-----|------|-----|-----|
| C5-0 | 需求登记 | DONE | state.md | 详情抽屉 Tab 仍有英文 |
| C5-1 | TDD 测试 | DONE | `scripts/tests/boardCopy.test.mjs` | 先断言中文 Tab 标签 |
| C5-2 | 前端实施 | DONE | `src/lib/leadDetailTabs.ts` + `LeadDetailDrawer.tsx` | UI 标签中文化，URL key 不变 |
| C5-3 | 映射说明 | DONE | flow.md | 记录四个 Tab 的数据来源和后端接口映射 |
| C5-4 | 验证 | DONE | 测试命令结果 | 6/6 前端文案测试通过，`pnpm build` 通过 |

### Cycle 5 范围

- ✅ `Jobs/Steps/Timeline/Raw` 改为 `执行记录/执行步骤/审计日志/原始数据`。
- ✅ URL 的 `tab=jobs|steps|timeline|raw` 保持不变，避免破坏刷新恢复和旧链接。
- ✅ 在 `flow.md` 记录四个 Tab 对应的数据映射。

### Cycle 5 验证

```powershell
node --test scripts/tests/leadDisplay.test.mjs scripts/tests/boardCopy.test.mjs
```
结果：✅ 6/6 测试通过

```powershell
pnpm build
```
结果：✅ 构建通过

STATUS: CONVERGED

---

## Cycle 4 · 节点状态（中文状态 + 最近线索列表提示）

| # | 节点 | 状态 | 产物 | 备注 |
|---|-----|------|-----|-----|
| C4-0 | 口径确认 | DONE | state.md | 暂不做全量滚动或分页加载 |
| C4-1 | TDD 测试 | DONE | `scripts/tests/boardCopy.test.mjs` | 状态中文与列表计数文案先测后实现 |
| C4-2 | 前端实施 | DONE | `statusDisplay.ts`、`leadListCopy.ts`、看板组件修改 | 状态右侧展示，中文 Badge |
| C4-3 | 验证 | DONE | 测试命令结果 | 5/5 前端文案测试通过，`pnpm build` 通过 |

### Cycle 4 范围

- ✅ 状态枚举映射为中文，不再在看板线索行露出 `RPA_BLOCKED` 等原始枚举。
- ✅ 线索状态保持在每行右侧，不另起一行。
- ✅ 列表计数从 `100 leads` 改为 `显示 N / 共 M`。
- ✅ 增加提示：按最近更新时间排序，点击线索查看执行步骤与日志。
- ✅ 暂不做全量滚动、分页或加载更多。

### Cycle 4 验证

```powershell
node --test scripts/tests/leadDisplay.test.mjs scripts/tests/boardCopy.test.mjs
```
结果：✅ 5/5 测试通过

```powershell
pnpm build
```
结果：✅ 构建通过

STATUS: CONVERGED

---

## Cycle 3 · 节点状态（线索显示口径 + 全局审计栏收敛）

| # | 节点 | 状态 | 产物 | 备注 |
|---|-----|------|-----|-----|
| C3-0 | 需求登记 | DONE | plan.md/state.md | 使用当前 `frontend-leads-board` 任务线承接 |
| C3-1 | TDD 测试 | DONE | `scripts/tests/leadDisplay.test.mjs` | 先验证 RED，再实现展示工具 |
| C3-2 | 前端实施 | DONE | `src/lib/leadDisplay.ts` + 看板组件修改 | 账号主显示，备注存在才显示 |
| C3-3 | 固定全局审计栏收敛 | DONE | `LeadsBoard.tsx` | 移除右侧常驻全局审计栏，保留 Drawer Timeline |
| C3-4 | 验证 | DONE | 测试命令结果 | 3/3 展示测试通过，`pnpm build` 通过 |

### Cycle 3 范围

- ✅ 线索列表显示回到后端线索对象语义：`phone`/微信号为主，备注存在才显示。
- ✅ 兼容后端 `lead_id/customer_name/phone_masked` 与旧前端 `id/name/phone` 字段。
- ✅ 详情抽屉头部与列表复用同一显示规则。
- ✅ 移除看板主区域固定右侧全局审计动态栏；单线索审计仍在 Timeline Tab 中查看。

### Cycle 3 验证

```powershell
node --test scripts/tests/leadDisplay.test.mjs
```
结果：✅ 3/3 测试通过

```powershell
pnpm build
```
结果：✅ 构建通过

STATUS: CONVERGED
