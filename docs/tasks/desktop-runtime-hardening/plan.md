# 桌面运行时加固 · 计划

> 任务线：`desktop-runtime-hardening`
> 状态：P0 IMPLEMENTED

## 第一部分 · 问题背景

### 现状

- 前端本地 API 地址写死为 `http://127.0.0.1:8000`。
- Tauri 启动 Python sidecar 时写死 `uvicorn --port 8000`。
- Tauri 启动前会执行 `kill_existing_backend_on_port(8000)`，在生产环境可能误杀用户机器上已有的 8000 服务。
- Python sidecar 由 Tauri 启动一次后缺少退出监控；sidecar 中途退出时，前端只看到接口断开。
- `1420` 是 Tauri dev 的 Vite dev server 端口；生产包应加载内置资源，不依赖该端口。

### 风险

- 用户是开发者时，`8000` 很可能已被本地服务占用。
- 固定端口 + 强杀策略会造成冲突、误杀、或启动失败。
- sidecar 进程中途退出会导致 RPA job 停在运行中，下一次启动才被 recover 为 `SYS_RPA_INTERRUPTED`。

## 第二部分 · 头脑风暴候选方案

### 方案 A：保留 8000，仅增加占用检测

- 做法：启动前检测 8000 是否可用；不可用则提示用户关闭占用进程。
- 优点：改动最小。
- 缺点：生产体验差；仍要求用户理解端口；不能解决 sidecar 中途退出。

### 方案 B：动态端口 + 前端从 Tauri 获取 API base

- 做法：Tauri 启动时选择空闲端口，传给 Python sidecar；前端通过 command 获取 `localApiBase`。
- 优点：避开用户机器端口冲突；不误杀其他进程；前端无硬编码。
- 缺点：需要改造所有直接引用 `LOCAL_API_BASE` 的请求与 SSE。

### 方案 C：方案 B + sidecar 监督与自动恢复

- 做法：在动态端口基础上，Tauri 记录 sidecar stdout/stderr，监控 child 退出，自动重启并通过前端状态暴露“启动中/重启中/失败”。
- 优点：同时解决端口冲突和执行中断连；生产可观测性最好。
- 缺点：实现与测试成本更高，需要定义重启次数、失败熔断、日志路径。

## 第三部分 · 推荐方向

推荐方案 C，分两步落地：

1. P0：动态端口 + 前端动态 API base + 不再强杀 8000。（本轮已落地）
2. P1：sidecar 退出监控 + 有限自动重启 + UI 运行态展示。（后续）

本轮额外落地：sidecar stdout/stderr 日志落盘到 app data 目录，便于生产排查。

## 第四部分 · 初步测试清单

| # | 用例 | 前置 | 触发 | 期望 |
|---|---|---|---|---|
| 1.1 | 8000 被占用时仍能启动 | 手动占用 8000 | 启动 Tauri | sidecar 选择其他端口，健康检查通过 |
| 1.2 | 前端使用动态 API base | sidecar 非 8000 | 打开首页/调用 health | 请求命中新端口 |
| 1.3 | 不误杀外部 8000 服务 | 8000 上运行外部进程 | 启动 Tauri | 外部进程仍存活 |
| 1.4 | sidecar 中途退出可观测 | 启动后杀 Python child | 前端轮询状态 | UI 显示重启中或失败，而非静默断开 |
| 1.5 | sidecar 自动重启 | 杀 Python child | Tauri supervisor 检测退出 | 新 child 启动，health 恢复 |

## 第五部分 · P0 对账与后续

| 优先级 | 项目 | 原因 | 建议处理 |
|---|---|---|---|
| P1 | sidecar 自动重启 | 当前已避免固定端口冲突，但 child 中途退出仍需用户重启 app | 增加 supervisor loop、重启次数上限、状态 command |
| P1 | UI 展示启动中/重启中/失败 | 当前状态栏只通过 health 成败显示连接状态 | 增加 sidecar runtime status command |
| P2 | 生产打包 sidecar 形态 | 当前 dev 路径仍调用 `uv run uvicorn` | 打包阶段改为内置 sidecar 可执行文件或稳定 Python runtime |

STATUS: P0 IMPLEMENTED
