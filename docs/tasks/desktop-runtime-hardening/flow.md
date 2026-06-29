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

### 与设计的偏差

- P0 已完成；P1 的 sidecar 自动重启、重启状态 command、UI“启动中/重启中/失败”仍未落地，保留为下一轮。
- 当前仍使用 `uv run uvicorn` 启动 Python，生产打包为独立 sidecar 可执行文件另行处理。

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
- `cargo test`：9 passed。
- `pnpm -s build`：通过。
- `uv run pytest backend/app/tests -q`：109 passed，保留 4 条 FastAPI deprecation warnings。
- `git diff --check`：通过；PowerShell 输出包含 CRLF 提示，不影响 diff check 结果。

STATUS: P0 IMPLEMENTED
