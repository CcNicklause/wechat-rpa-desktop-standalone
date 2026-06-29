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
| C2-3 | plan-agent: Cycle 2 对账 | TODO | plan.md 追加对账清单 | 对齐事实与期望 |
| C2-4 | test-agent: Cycle 2 测试 | DONE | 后端单测 + 回归 | 新增 5 个单测，108 个回归全通过 |

### Cycle 2 范围

- ✅ **件 1**：前端 KPI 口径修正（抽离 `src/lib/leadStatus.ts`）
- ✅ **件 2**：DevTesting 联通看板（移除"立即执行"按钮 + `registerJobStarted` + toast 跳转）
- ✅ **件 3**：后端 KPI Stats 接口（`GET /api/v1/leads/stats` + 前端接入）
- ✅ **新增**：后端单测 `python/backend/app/tests/test_lead_stats.py`（覆盖空库/单状态/多状态/全状态）
- ✅ **不动**：`useDevTestStore`、重跑按钮完整流程、今日新增等 audit_events 基 KPI

### Cycle 2 当前等待

- plan.md Cycle 2 章节已追加完成
- coder-agent 已完成 Cycle 2 实施
- 后端单测 + 回归已完成（108/108 全通过）
- 下一步：plan-agent 对账

STATUS: CYCLE2_DONE
