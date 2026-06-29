# 桌面运行时加固 · 编排状态

> 任务线：`desktop-runtime-hardening`
> 启动时间：2026-06-29
> 模式：头脑风暴 / 设计

## 节点状态

| # | 节点 | 状态 | 产物 | 备注 |
|---|---|---|---|---|
| 0 | 启动登记 | DONE | state.md | 已建立生产运行时稳定性任务线 |
| 1 | brainstorming: 方案收敛 | DONE | plan.md | 推荐方案 C，P0/P1 分步 |
| 2 | coder-agent: P0 实施 | DONE | 代码 + flow.md | 动态端口、前端动态 API base、不再强杀 8000、sidecar 日志落盘 |
| 3 | plan-agent: 对账 | DONE | plan.md | P0/P1 范围已对齐，P0 标记为已实施 |
| 4 | test-agent: 测试 | DONE | flow.md | 已记录 cargo、前端构建、Python 后端测试、diff check |
| 5 | coder-agent: P1 实施 | DONE | 代码 + flow.md | sidecar supervisor、最多 3 次自动重启、状态 command、状态栏展示 |
| 6 | test-agent: P1 测试 | DONE | cargo test / build | 新增 sidecar 状态与重启决策单测 |

## 范围

- 生产环境不固定占用 `127.0.0.1:8000`，避免用户机器已有开发服务被误杀或冲突。
- 前端本地 API base 不再硬编码 `http://127.0.0.1:8000`。
- Tauri 主进程托管 Python sidecar：启动、健康检查、退出监控、日志落盘、必要时自动重启。
- 明确 dev 与 production 的端口策略：`1420` 只属于 Vite dev；生产不依赖该端口。

## 当前等待

- 执行最终验证并提交 P1。
- 后续 P2：生产打包 sidecar 形态，从 `uv run uvicorn` 收敛到独立 sidecar 可执行文件或稳定 Python runtime。

## 本轮结果

- 生产运行时不再固定使用 `127.0.0.1:8000`，启动时选择空闲本机端口。
- 前端所有本地 API 请求与 SSE 改为通过 Tauri command 获取 API base。
- 启动时不再强杀 8000，避免误杀用户机器上的其他开发服务。
- sidecar stdout/stderr 已落盘，便于排查生产断连。
- P1 已增加 sidecar 退出监控，异常退出后最多自动重启 3 次。
- 前端状态栏已展示 `启动中` / `重启中 x/3` / `启动失败` / `已连接`。
- 验证通过：`cargo test`、`pnpm -s build`、`uv run pytest backend/app/tests -q`、`git diff --check`。
