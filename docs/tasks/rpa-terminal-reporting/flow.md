# RPA 终端上报 · 实际功能流程

> 反映代码现状，**不**复述设计文档。设计期望见 [plan.md](plan.md)。

## Cycle 2（实施完成）

### 模块结构

- 新增 [src-tauri/src/terminal.rs](../../../src-tauri/src/terminal.rs)：identity / device info / MGR client / TerminalManager 全部集中于此。
- [src-tauri/src/lib.rs](../../../src-tauri/src/lib.rs) 顶部 `mod terminal;` 引入；`AppState` 新增 `portal_session: Arc<AsyncMutex<Option<PortalSession>>>` 与 `terminal_manager: Arc<AsyncMutex<Option<Arc<TerminalManager>>>>`。
- [src-tauri/Cargo.toml](../../../src-tauri/Cargo.toml) 新增依赖：`tokio` (features: macros / rt-multi-thread / sync / time)、`sysinfo = "0.31"`。

### 已落地

#### 1. terminalId / deviceId 持久化
- 文件路径：`app_data_dir() / terminal-identity.json`，与 `portal-session.json` 同目录。
- 字段：`schema_version` (=1) / `terminal_id` / `device_id` / `created_at`。
- 首次启动：`Uuid::new_v4()` 生成，`device_id == terminal_id`，立刻落盘。
- 后续启动：读 → 解析失败或 `schema_version` 不匹配则覆盖重建；IO 失败走内存 fallback。
- logout **不**清这个文件（终端 ID 与用户身份解耦）。

#### 2. 设备信息采集
通过 `sysinfo` crate 采集以下字段并按 MGR 期望的 camelCase 序列化（`type` / `ipAddress` / `macAddress` / `osName` / `osVersion` / `cpuInfo` / `memoryGb` / `diskGb` / `screenResolution`，加上 `name`）：
- `name`：`System::host_name()`。
- `type`：编译期判定 `windows` / `macos` / `linux`。
- `os_name` / `os_version`：`System::name()` / `System::os_version()`。
- `cpu_info`：第一颗 CPU 的 brand + 频率 + 核心数。
- `memory_gb` / `disk_gb`：总内存与所有磁盘总容量，字节 / (1024³)，溢出饱和到 `i32::MAX`。
- `ip_address` / `mac_address`：`sysinfo::Networks` 第一张非 loopback 且 MAC ≠ 全 0 的网卡的 IPv4 + MAC。失败时填空串。
- `screen_resolution`：当前实现统一填 `"unknown"`（未引入屏幕分辨率库，避免新增 winapi 依赖；待 P1 升级）。

#### 3. MGR 上报 client
- 基类：[`MgrClient`](../../../src-tauri/src/terminal.rs)，构造时拿 `portal_api_base()`（`AISALES_PORTAL_API_BASE` 环境变量优先，默认 QA Portal）。
- 所有调用：`Authorization: Bearer <portal_access_token>`，POST `{base}/mgr/rpa-terminal/<endpoint>`。
- 三个接口落地：
  - `record`：device info + tenantId/terminalId/deviceId，统一 snake→camel 后序列化。
  - `heartbeat`：仅 `{ terminalId }`。
  - `status/change`：`{ tenantId, terminalId, status, reason }`。

#### 4. 调用时机
- **登录 / session 恢复成功**：[src/stores/useAuthStore.ts](../../../src/stores/useAuthStore.ts) 的 `applySession` 内 fire-and-forget `invoke('terminal_initialize', { session })`。失败仅 `console.warn`。
- **terminal_initialize 命令**（[src-tauri/src/lib.rs](../../../src-tauri/src/lib.rs)）：
  1. 写入 `AppState.portal_session`。
  2. 已存在 manager 则 abort 旧 heartbeat（账号切换场景）。
  3. 加载 identity → 构造 `MgrClient` → 新 `TerminalManager` 挂到 `AppState`。
  4. `tauri::async_runtime::spawn` 后台跑 `manager.initialize(token, tenant_id)`，**不阻塞 await**：
     - `try_record`：失败仅写 `TerminalRuntimeState.last_record_error`。
     - 上报 `status=online`，`reason="login"`。
     - 启动 heartbeat。
- **退出登录**（`portal_logout` 命令）：先 `clear_session` 同步返回，再 `spawn` 一个 2s `timeout` 的 `manager.shutdown(token, tenant_id, "logout")`，最后清空 `AppState` 内 session 与 manager。
- **应用关闭**（`WindowEvent::Destroyed`）：`block_on` 一个 1.5s `timeout` 的 `manager.shutdown(token, tenant_id, "app_exit")`，然后 kill Python 子进程。

#### 5. heartbeat 单例
- `tokio::spawn` 上一个 `interval(30s)` loop；首拍 `interval.tick()` 立刻返回，第二拍开始真正发包。
- `JoinHandle` 存在 `TerminalManager.heartbeat_task: AsyncMutex<Option<JoinHandle<()>>>`，启动新任务前 `handle.abort()` 旧的。
- 每拍：
  - 若 `last_record_ok_at` 仍是 `None` 且距 `last_record_attempt_at` ≥ 60s，先补一次 `record`。
  - 调 `heartbeat`：成功重置 `consecutive_heartbeat_failures`；失败累加，到达 6 次后日志升级为 `[terminal] heartbeat 连续失败 ≥6`，但**不退避、不停止**。
- 停止：仅 `logout` / `WindowEvent::Destroyed` / 账号切换时 abort。

#### 6. 测试
新增 4 个单元测试（[src-tauri/src/terminal.rs](../../../src-tauri/src/terminal.rs) `mod tests`）：
- `identity_round_trip` — identity JSON 序列化往返。
- `remap_snake_to_camel_keys` — snake→camel 字段名映射。
- `device_info_collect_does_not_panic` — 采集不 panic 且关键字段非空。
- `bytes_to_gb_clamps_to_i32_max` — 字节溢出饱和到 `i32::MAX`，不 panic。

执行结果（`cargo test --lib`）：

```
running 6 tests
test terminal::tests::bytes_to_gb_clamps_to_i32_max ... ok
test terminal::tests::remap_snake_to_camel_keys ... ok
test tests::normalizes_login_user_payload ... ok
test terminal::tests::identity_round_trip ... ok
test tests::normalizes_me_user_payload_without_user_id ... ok
test terminal::tests::device_info_collect_does_not_panic ... ok

test result: ok. 6 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
```

### 与设计的偏差

| 设计点 | 落地差异 | 备注 |
|---|---|---|
| P0-1 心跳 | 与设计一致 | 30s 写死，单例 abort 模型 |
| P0-2 失败处理 | 与设计一致 | 仅 `eprintln!` 暂代 `tracing`（项目尚未引入 tracing） |
| P0-3 退出 offline | 与设计基本一致；**应用关闭使用 `WindowEvent::Destroyed`** 而非 `RunEvent::ExitRequested`，沿用项目既有钩子，1.5s 超时不变 | 等于"已经在销毁路径上同步等一下"，比再加 RunEvent 拦截轻 |
| P0-4 tenant_id 来源 | 与设计一致 | 从 `PortalSession.tenant_id` 取，无 session 时不发 record / status |
| P0-5 identity 文件 | 与设计一致 | logout 不清；schema 不匹配覆盖重建 |
| P1-A 设备库 | `sysinfo 0.31` 已引入 | 编译通过、依赖未爆 |
| P1-B MAC/IP 失败 | 空串 `""` 而非 `null` | 待 MGR 联调确认是否接受 |
| P1-C reason 文案 | `online`→`"login"`；`offline`→`"logout"` / `"app_exit"` | **未单独区分 `session_restored`**：当前 `terminal_initialize` 在登录与 session 恢复两条路径都用 `"login"`；若 MGR 需区分，下一轮调整 |
| P1-D 间隔 | 写死 30s（常量） | 不配置化 |
| P1-E tenantId=0 | 透传，等联调 | 未做特殊分支 |

### 已知遗留

- **`screen_resolution` 暂填 `"unknown"`**：未引入屏幕分辨率库，避免 winapi 依赖。后续如 MGR 需要真实值，需要补 `display-info` 或 winapi 调用。
- **`tracing` 未接入**：所有日志仍走 `eprintln!`，与项目既有风格一致；后续如统一引入 `tracing`，需要全项目联调。
- **`session_restored` 与 `login` 未区分**：见 P1-C；如需区分，给 `terminal_initialize` 加一个 `source: "login" | "restored"` 参数即可。
- **真实联调已完成（2026-06-28）**：API 契约层 6/9 用例直接 curl QA Portal 全过；UI 端经 dev 模式 hot-reload 后登录链路完整跑通，日志按预期输出。

### Cycle 4 联调发现的 bug 与修复

- **bug**：React 18 `<StrictMode>` 在 dev 模式下双触发 [src/App.tsx:42-44](../../../src/App.tsx#L42-L44) 的 `useEffect(initialize)`，导致 `applySession` 内 fire-and-forget 的 `terminal_initialize` 被调两次，向 MGR 重复打了 record + status=online。日志证据：

  ```
  [terminal] terminal_initialize 命令收到 ...
  [terminal] initialize 开始 ...
  [terminal] record 发起 ...
  [terminal] terminal_initialize 命令收到 ...   ← 第二次双触发
  [terminal] initialize 开始 ...
  [terminal] record 成功 ...
  [terminal] status=online 上报成功 ...
  [terminal] heartbeat 已启动 ...
  [terminal] record 发起 ...                    ← 实际重复一份 record
  [terminal] record 成功 ...
  [terminal] status=online 上报成功 ...
  [terminal] heartbeat 已启动 ...
  ```

- **修复（双层去重，2026-06-28）**：
  1. **前端主防线**（[src/stores/useAuthStore.ts](../../../src/stores/useAuthStore.ts)）：用模块级变量 `lastInitializedToken` 缓存上一次成功调用对应的 `access_token`，相等即跳过 invoke；logout 与 invoke 失败时清空标记。
  2. **后端兜底**（[src-tauri/src/lib.rs](../../../src-tauri/src/lib.rs) `terminal_initialize`）：检测 `AppState.portal_session.access_token` 与 manager 已存在且 token 相同时，直接 `return Ok(())`，不重复 record / status_change / 重启 heartbeat。日志 `terminal_initialize 跳过 (同 token 已初始化)` 可观察。
- **结论**：MGR 侧 record 是幂等的（同 `terminalId` 复用 `id=13` 仅刷新 `lastHeartbeatAt`），重复调用不会产生脏数据；但桌面端不应主动重复打。修复后 StrictMode 仍双跑 effect，但 IPC 调用只发一次。

## 测试覆盖

```powershell
cd src-tauri
cargo test --lib
```

结果：6 个测试全部通过。

STATUS: READY_FOR_REVIEW
