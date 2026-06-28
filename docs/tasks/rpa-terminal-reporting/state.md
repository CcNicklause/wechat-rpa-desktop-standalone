# RPA 终端上报 · 编排状态

> 任务线：`rpa-terminal-reporting`
> 启动时间：2026-06-28
> 模式：设计核对

## 节点状态

| # | 节点 | 状态 | 产物 | 备注 |
|---|---|---|---|---|
| 0 | 启动登记 | DONE | state.md | 已建立终端上报任务线 |
| 1 | plan-agent: MGR Swagger 核对 | DONE | plan.md | 已核对 3 个 RPA 终端记录接口 |
| 1.5 | plan-agent: 实施前补充设计 | DONE | plan.md 第五/七部分 | 心跳生命周期/重试/退出 offline/tenant_id 来源/identity 文件 5 条 P0 已钉死，P1 留 Cycle 2 决策 |
| 2 | coder-agent: 实施 | DONE | 代码 + flow.md | terminal.rs + lib.rs + useAuthStore.ts 落地；cargo test 6/6 通过 |
| 3 | plan-agent: 对账 | DONE | plan.md 优化清单 | 对账完成，无 P0 回炉项；P1 项 5 条均接受现状；P2 项 2 条 |
| 4 | test-agent: 测试 | DONE | test.md | 9/9 用例全过：API 契约层 + UI 端实跑均通过；额外修复 StrictMode 双触发去重 bug |
| 5 | 收尾 | TODO | commit / PR | 任务线达到 DONE 条件，可走 finishing-a-development-branch |

## 范围

- 接入 MGR RPA 终端记录 tab 所需 3 个接口：
  - `POST /mgr/rpa-terminal/record`
  - `POST /mgr/rpa-terminal/heartbeat`
  - `POST /mgr/rpa-terminal/status/change`
- 记录终端信息、心跳、状态变更。
- 不包含 RPA 任务拉取、加微任务上报、数字员工绑定。

## 已核对

- MGR QA Swagger 可访问：`http://aisales-mgr.app.qa.internal.weimob.com/v3/api-docs`。
- 三个目标接口均在 tag `RPA终端记录` 下。
- 运行时全局设计：桌面端走 Portal `/api/v1/mgr/*` 网关，不直连 MGR。
- Portal 网关调用需要携带 Portal JWT。
- MGR OpenAPI 未声明鉴权 scheme，但仅作为接口契约来源。
- `heartbeat` 只需要 `terminalId`。
- `record` 和 `status/change` 需要 `tenantId` + `terminalId`。
- 状态枚举本轮使用 `online` / `offline`。

## 当前等待

- ✅ **Cycle 4 全部完成（2026-06-28）：9/9 用例全过**
  - API 契约层（curl 直连 QA Portal）：TC-1.1 / TC-1.2 / TC-3.1 / TC-3.2 / P1-1 / P1-2 全过，MGR 落库 `id=13`。
  - UI 端实跑（`pnpm tauri dev` 日志验证）：
    - TC-2.1 30s 真实心跳周期：连续两拍 `[terminal] heartbeat 成功`。
    - TC-2.2 断网容错 + 自愈：累计失败计数仅打 warn 不退避；UI 不崩，本地 Mock Upstream 心跳不受影响；恢复网络后下一拍即 `heartbeat 成功`。
    - TC-3.2 退出登录 offline：`shutdown 开始 reason=logout` → `status=offline 上报成功` → `heartbeat 已 abort`。
    - P1-3 应用关闭 offline：`shutdown 开始 reason=app_exit` → `status=offline 上报成功` → `heartbeat 已 abort`，整体退出 ≤1.5s。
- ✅ **额外修复**：React 18 `<StrictMode>` 双触发 effect 导致 `terminal_initialize` 重复调用 → 前端 `lastInitializedToken` 去重 + 后端 `terminal_initialize 跳过 (同 token 已初始化)` 兜底；现场日志已确认仅触发一次。
- ⏳ **Cycle 5 收尾**：commit 整理 + 是否走 PR 由用户决定。
- 任务线已达 DONE 条件，无遗留 P0/P1 项。
