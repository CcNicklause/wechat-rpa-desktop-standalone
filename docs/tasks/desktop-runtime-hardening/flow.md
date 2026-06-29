# 桌面运行时加固 · 实际功能流程

> 反映代码现状，**不**复述设计文档。设计期望见 [plan.md](plan.md)。

## Cycle 1 · P0 动态端口与本地 API base

### 已落地

- `src-tauri/src/lib.rs`
  - 新增 `reserve_local_api_port()`：优先在 `18100..=18199` 中选择空闲本机端口，全部占用时回退到系统分配端口。
  - 新增 `local_api_base(port)` 和 Tauri command `get_local_api_base`，供前端获取真实本地 API 地址。
  - Python sidecar 启动参数改为 `uvicorn --port <selected_port> --host 127.0.0.1`。
  - 移除启动前强杀 `8000` 的行为，不再误杀用户机器上的其他开发服务。
  - sidecar stdout/stderr 分别落盘到 app data 目录的 `sidecar-stdout.log` / `sidecar-stderr.log`。
- `src/lib/api.ts`
  - 移除写死导出的 `LOCAL_API_BASE`。
  - 新增 `getLocalApiBase()`：Tauri 环境调用 `get_local_api_base`，浏览器/Vite 预览回退 `http://127.0.0.1:8000`。
  - `requestLocalApi()` 改为使用动态 API base。
- `src/hooks/useJobSnapshot.ts`
  - fetch-based SSE job events 改用 `getLocalApiBase()`。
- `src/components/features/UpstreamConfig.tsx`
  - upstream 日志 SSE 改用 `getLocalApiBase()`。
- `src/components/layout/StatusBar.tsx`
  - 状态栏连接文案展示实际 API base，不再写死 `Port 8000`。
- `src/components/features/DevTesting.tsx`
  - 断连提示改为通用本地 Python 后端未响应，不再指向固定 8000。

## Cycle 2 · P1 sidecar 监督与状态展示

### 已落地

- `src-tauri/src/lib.rs`
  - 新增 `SidecarRuntimeStatus` / `SidecarStatusPayload`，记录 `starting`、`running`、`restarting`、`failed`、`stopped`、重启次数、最近退出原因、API base、日志目录。
  - 新增 `get_sidecar_status` Tauri command，前端可读取 sidecar runtime 状态。
  - 抽出 `spawn_python_sidecar()`，初次启动和自动重启共用同一套 `uvicorn` 参数、环境变量和日志落盘逻辑。
  - 新增 supervisor loop：每 2 秒检查 Python child；异常退出后最多自动重启 3 次；超过上限进入 `failed`。
  - App 关闭时设置 shutdown 标记并进入 `stopped`，避免用户主动退出时 supervisor 再拉起 sidecar。
- `src/lib/api.ts`
  - 新增 `SidecarStatus` 类型和 `getSidecarStatus()`。
- `src/components/layout/StatusBar.tsx`
  - 状态栏读取 sidecar runtime 状态。
  - health 成功显示 `已连接 (<api_base>)`；sidecar 启动/重启时显示 `启动中` / `重启中 x/3`；超过重启上限显示 `启动失败`。

### 与设计的偏差

- P1 已完成；当前仍使用 `uv run uvicorn` 启动 Python，生产打包为独立 sidecar 可执行文件另行处理。
- supervisor 当前只负责进程级重启；RPA job 中断后的业务恢复仍依赖后端现有启动恢复逻辑。

## 测试覆盖

```powershell
cd src-tauri
cargo test

cd ..
pnpm -s build

cd python
uv run pytest backend/app/tests -q

git diff --check
```

结果：
- `cargo test`：11 passed。
- `pnpm -s build`：通过。
- `uv run pytest backend/app/tests -q`：109 passed，保留 4 条 FastAPI deprecation warnings。
- `git diff --check`：通过；PowerShell 输出包含 CRLF 提示，不影响 diff check 结果。

STATUS: P1 IMPLEMENTED
