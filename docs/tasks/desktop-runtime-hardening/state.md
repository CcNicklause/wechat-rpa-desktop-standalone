# 桌面运行时加固 · 编排状态

> 任务线：`desktop-runtime-hardening`
> 启动时间：2026-06-29
> 模式：头脑风暴 / 设计

## 节点状态

| # | 节点 | 状态 | 产物 | 备注 |
|---|---|---|---|---|
| 0 | 启动登记 | DONE | state.md | 已建立生产运行时稳定性任务线 |
| 1 | brainstorming: 方案收敛 | IN_PROGRESS | plan.md | 端口占用、sidecar 守护、前端动态 API base |
| 2 | coder-agent: 实施 | TODO | 代码 + flow.md | 待方案确认后执行 |
| 3 | plan-agent: 对账 | TODO | plan.md 优化清单 |  |
| 4 | test-agent: 测试 | TODO | test.md 或测试命令 |  |

## 范围

- 生产环境不固定占用 `127.0.0.1:8000`，避免用户机器已有开发服务被误杀或冲突。
- 前端本地 API base 不再硬编码 `http://127.0.0.1:8000`。
- Tauri 主进程托管 Python sidecar：启动、健康检查、退出监控、日志落盘、必要时自动重启。
- 明确 dev 与 production 的端口策略：`1420` 只属于 Vite dev；生产不依赖该端口。

## 当前等待

- 与用户确认设计方向：动态端口 + Tauri command 下发 API base + sidecar 退出监控是否作为首选方案。

