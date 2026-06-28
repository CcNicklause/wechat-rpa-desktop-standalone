# Orchestrator State — RPA 加微链路加固

> 触发命令：`/orchestrate legacy "wechat-rpa-desktop-standalone：按上一轮代码审计结论修复加微链路 P0/P1 缺口 ..."`
> 场景：老项目改造（legacy），轻量模板（CLAUDE.md §22-50）
> 启动时间：2026-06-28
> 模式：手工编排（B 路径，`/orchestrate` 命令未在当前会话注册）

## 节点状态

| # | 节点 | 状态 | 产物 | 备注 |
|---|---|---|---|---|
| 0 | 启动登记 | ✅ DONE | docs/tasks/rpa-hardening/state.md | 本文件 |
| 1 | plan-agent: 合一计划文档 | ✅ DONE | docs/tasks/rpa-hardening/plan.md | 需求 + 设计 + 测试清单 三章节，STATUS: CONVERGED |
| 2 | **人工定稿**（CLAUDE.md §62 第 1 条） | ✅ DONE | — | 2026-06-28 用户签字"可以" |
| 3 | coder-agent: 切 dev cycle 实施 | ✅ DONE | 代码 + docs/tasks/rpa-hardening/flow.md | 3 个 cycle：基础设施 / 状态机 / 业务收尾 |
| 3.1 | Cycle 1：基础设施 | ✅ DONE | 需求 4 + 6 + 2 实现 + 测试 + flow.md 追加 | per-lead 互斥 / 401 续签 / outbox。82 个测试全绿，STATUS: READY_FOR_REVIEW |
| 3.2 | Cycle 2：状态机 | ✅ DONE | 需求 1 + 3 | RISK_FROZEN / 重试前核验。95 个测试全绿，STATUS: READY_FOR_REVIEW |
| 3.3 | Cycle 3：业务收尾 | ✅ DONE | 需求 5 + 7 | acceptance_attempts / 启动 reconciler。101 个测试全绿，STATUS: READY_FOR_REVIEW |
| 4 | plan-agent 对账：plan 设计章节 vs flow.md | ✅ DONE | docs/tasks/rpa-hardening/plan.md 第四部分·对账与优化清单 | 结论：功能完成；2 项 P1-test 已补，剩余 3 项非阻塞优化 |
| 5 | test-agent: 执行测试 | ✅ DONE | uv run pytest backend/app/tests | 103 passed, 4 FastAPI on_event deprecation warnings |

## 范围（一次性确认）

**P0**：① RISK_FROZEN 状态机 ② lead_status_reports outbox ③ RPA 重试前核验
**P1**：④ HTTP add_wechat per-lead 互斥 ⑤ acceptance_attempts 上限 + RISK/NOT_FOUND 转态 ⑥ 401 自动续签 ⑦ 启动 reconciler
**显式不在范围**：P2（前端运营级 UX）、P3（清死状态 / 真实 password change / SSE auth）

## 当前等待

Cycle 1 / 2 / 3 与 plan-agent 对账均已完成，P1-test 优化也已补齐。当前剩余为非阻塞优化清单：recover/reconciler 协同测试、终态 job report 回填 hardening、FastAPI lifespan 迁移。
