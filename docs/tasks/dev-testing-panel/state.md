# 开发测试页 · 编排状态

> 任务线：`dev-testing-panel`
> 启动时间：2026-06-29
> 模式：轻量（按需迭代，按页面能力增量推进）

## 范围

- 维护「开发测试页」(前端 `src/components/features/DevTesting.tsx` + 后端 `/api/v1/.../dev/*` 系列接口) 的能力清单与演进。
- 该页面是本地联调与运维入口，覆盖：批量线索模拟下发、手动加友测试、运行反馈控制台、审计事件、好友通过模拟/对账，以及危险运维操作（一键清空本地数据）。
- 范围限定在「页面级能力」，不涉及 RPA 物理链路、上游对接协议等已有任务线(`rpa-hardening` / `upstream-integration`)的核心逻辑；只做编排入口与对应 dev 接口。

## 节点状态

| # | 节点 | 状态 | 产物 | 备注 |
|---|---|---|---|---|
| 0 | 启动登记 | DONE | state.md | 本文件 |
| 1 | plan-agent: 计划文档 | DONE | plan.md | 含一键清空需求/设计/测试清单 |
| 2 | coder-agent: 实施（一键清空） | DONE | 代码 + flow.md | store + 路由 + 前端按钮 |
| 3 | plan-agent: 对账 | N/A | — | 小迭代，跳过对账循环 |
| 4 | test-agent: 测试 | DONE | 见 flow.md 测试覆盖 | 后端单测 + smoke + tsc |

## 当前等待

- 无。一键清空已落地并通过验证。
- 后续若需在开发测试页新增能力（如直接展示卡死在"执行中"的孤儿记录并提供回收入口），在本任务线追加 Cycle。

## 已知遗留（不在本任务线根治）

- ⚠️ **2026-06-29 纠正**：此前把一键清空定位为“清理卡死在执行中的孤儿记录”是误判。经查 demo.db：`RPA_EXECUTING` lead=0、running job=0，**无崩溃孤儿**；`recover_interrupted_jobs` 工作正常。看板“19 个执行中”实为 `CALLING`(11)+`RPA_SIMULATED`(8) 僵尸中间态被 running 桶计入（已由 `frontend-leads-board` Cycle 9 修 KPI 口径解决）。
- 一键清空的实际作用：清掉这些**僵尸中间态残留**（及全部业务数据）回到干净态，并非清理崩溃孤儿。详见 `rpa-hardening/state.md` 2026-06-29 纠正记录。
