# RPA 终端上报 · 计划

> 任务线：`rpa-terminal-reporting`
> 状态：DRAFT
> MGR Swagger：`http://aisales-mgr.app.qa.internal.weimob.com/swagger-ui/index.html#/`

## 第一部分 · 需求

### 需求 1：登录后记录终端信息

- 业务问题：桌面端已接入 Portal 登录，但 MGR 还不知道这台桌面终端的设备信息，Web 侧无法看到终端记录。
- 验收标准：
  1. 用户登录成功并恢复 session 后，桌面端生成或读取稳定 `terminalId` / `deviceId`。
  2. 通过 Portal 网关调用 `POST /api/v1/mgr/rpa-terminal/record` 记录终端信息。
  3. 记录失败不阻断用户进入工作台，但需要在日志或本地状态中可见。

### 需求 2：定时记录心跳

- 业务问题：MGR 需要根据心跳判断终端在线状态。
- 验收标准：
  1. 终端信息记录成功后启动心跳。
  2. 按固定间隔通过 Portal 网关调用 `POST /api/v1/mgr/rpa-terminal/heartbeat`。
  3. 心跳失败可重试或记录错误，但不影响本地 RPA 基础功能。

### 需求 3：记录状态变更

- 业务问题：终端登录、退出状态需要同步到 MGR。
- 验收标准：
  1. 登录成功后上报 `online`。
  2. 退出登录或应用关闭时尽力上报离线状态。
  3. 本轮只使用 `online` / `offline` 两个状态；RPA 运行/异常等业务态后续另行评估。

## 第二部分 · MGR Swagger 核对

Swagger OpenAPI 地址：`http://aisales-mgr.app.qa.internal.weimob.com/v3/api-docs`

运行时全局设计：桌面端不直连 MGR，统一调用 Portal Node/NestJS 网关：

```text
Desktop -> Portal /api/v1/mgr/* -> MGR /mgr/*
```

当前 QA Portal API base：`http://aisales-portal.app.qa.internal.weimob.com/api/v1`。

### 1. 记录终端信息

```http
POST {PORTAL_API_BASE}/mgr/rpa-terminal/record
```

请求体：`RpaTerminalRecordReqDTO`

| 字段 | 类型 | 说明 |
|---|---|---|
| `tenantId` | int64 | Portal 用户租户 ID |
| `terminalId` | string | 桌面终端唯一 ID |
| `deviceId` | string | 设备 ID，可与机器标识相关 |
| `name` | string | 设备名称 |
| `type` | string | 设备类型，如 `windows` |
| `ipAddress` | string | IP 地址 |
| `macAddress` | string | MAC 地址 |
| `osName` | string | 操作系统名称 |
| `osVersion` | string | 操作系统版本 |
| `cpuInfo` | string | CPU 信息 |
| `memoryGb` | int32 | 内存 GB |
| `diskGb` | int32 | 磁盘 GB |
| `screenResolution` | string | 屏幕分辨率 |

响应：`SoaResponseRpaTerminalDTOVoid`，`responseVo` 为 `RpaTerminalDTO`。

### 2. 记录心跳

```http
POST {PORTAL_API_BASE}/mgr/rpa-terminal/heartbeat
```

请求体：`RpaTerminalHeartbeatReqDTO`

| 字段 | 类型 | 说明 |
|---|---|---|
| `terminalId` | string | 桌面终端唯一 ID |

响应：`SoaResponseVoidVoid`。

### 3. 记录状态变更

```http
POST {PORTAL_API_BASE}/mgr/rpa-terminal/status/change
```

请求体：`RpaTerminalStatusChangeReqDTO`

| 字段 | 类型 | 说明 |
|---|---|---|
| `tenantId` | int64 | Portal 用户租户 ID |
| `terminalId` | string | 桌面终端唯一 ID |
| `status` | string | 终端状态，本轮使用 `online` / `offline` |
| `reason` | string | 状态变化原因 |

响应：`SoaResponseVoidVoid`。

### 鉴权与网关信息

- MGR OpenAPI 未声明 operation/root `securitySchemes`，但桌面端不直接依赖该安全模型。
- 桌面端通过 Portal 网关调用时必须携带 Portal JWT：`Authorization: Bearer <access_token>`。
- Portal `MgrController` 使用 `CombinedAuthGuard`，统一承接 JWT/APIKey 鉴权与转发。
- Portal 当前对 `orgId` 有自动注入逻辑；这 3 个接口字段是 `tenantId`，第一版仍由桌面端从 Portal session 传入 `tenantId`。

## 第三部分 · 技术设计

### 设计 1：新建 Rust 侧 Portal-MGR terminal client

- 数据模型：
  - `TerminalIdentity`：`terminal_id`, `device_id`, `created_at`。
  - `TerminalDeviceInfo`：设备名、系统、CPU、内存、磁盘、分辨率、IP/MAC。
  - `TerminalRuntimeState`：最近一次 record/heartbeat/status 上报结果。
- 代码触点：
  - `src-tauri/src/lib.rs` 或拆分 `src-tauri/src/terminal.rs`。
  - 新增 command 或内部函数：`record_terminal`、`send_terminal_heartbeat`、`record_terminal_status_change`，请求统一发往 `{PORTAL_API_BASE}/mgr/rpa-terminal/*`。
  - `src/stores/useAuthStore.ts`：登录成功/恢复 session 后触发终端上报初始化。
- 风险与权衡：
  - 当前 `tenant_id` 曾出现 QA 用户为 `0`，本轮暂定接受，实施后按真实联调结果修正。
  - 设备信息采集可能引入额外 Rust 依赖，第一版可先采集稳定且低风险字段。
  - 通过 Portal 网关可以复用登录态和审计边界，避免桌面端耦合 MGR 内网域名。

### 设计 2：terminalId/deviceId 生成与持久化

- 数据模型：
  - `terminalId`：建议本地持久 UUID，路径使用 Tauri app data。
  - `deviceId`：第一版可等于 `terminalId`，后续再升级为硬件 hash。
- 代码触点：
  - 复用登录系统的 app data 目录写入 `terminal-identity.json`。
- 风险与权衡：
  - 硬件 hash 更稳定但实现复杂且涉及隐私；本地 UUID 简单可靠，重装/清数据会变。

### 设计 3：调用时机

- 登录成功或 `portal_get_session` 恢复成功：
  1. 确保 terminal identity。
  2. 采集设备信息。
  3. 调 `record`。
  4. 调 `status/change` 上报 `online`。
  5. 启动 heartbeat。
- 退出登录：
  1. 尽力调 `status/change` 上报 `offline`。
  2. 停止 heartbeat。
- 应用关闭：
  1. 尽力调 `status/change` 上报 `offline`。

## 第四部分 · 测试清单

| # | 用例 | 前置 | 触发 | 期望 |
|---|---|---|---|---|
| 1.1 | 终端信息记录成功 | 已登录 Portal，Portal 网关可访问 | 登录成功后初始化 | 经 Portal 转发到 MGR `/record`，返回成功，保存上报状态 |
| 1.2 | tenantId 为 0 | QA 用户 `tenant_id=0` | 调 `/record` | 暂定接受；联调记录 MGR 实际行为 |
| 2.1 | 心跳成功 | 已 record 成功 | heartbeat timer 触发 | 调 `/heartbeat`，携带 terminalId |
| 2.2 | 心跳失败 | MGR 网络异常 | heartbeat timer 触发 | 不影响工作台，记录错误 |
| 3.1 | 登录上线状态 | 已登录 | 登录成功 | 调 `/status/change`，状态为 `online` |
| 3.2 | 退出离线状态 | 已登录 | 点击退出登录 | 尽力调 `/status/change`，状态为 `offline` |

## 第五部分 · 实施前补充设计（P0）

> 进 Cycle 2 前钉死的 5 条决策；coder-agent 按这些落地，不再二次拍板。

### P0-1 心跳生命周期

- 心跳定时器跑在 **Rust 侧**，使用 `tokio::spawn` + `tokio::time::interval`,独立于前端窗口与 UI 状态。
- 进程内最多保留 **1 个 heartbeat 任务**：用 `Mutex<Option<JoinHandle<()>>>` 或 `CancellationToken` 管理；启动新任务前先 abort 旧任务。
- 触发启动：`record_terminal` 成功后立即启动。
- 触发停止:
  - 用户主动调 `portal_logout` → abort heartbeat。
  - `RunEvent::ExitRequested` → abort heartbeat。
- 窗口最小化/隐藏不影响 heartbeat;前端 reload 不重启 heartbeat（由 Rust 单例守护）。
- 间隔：**默认 30s**，写成常量 `HEARTBEAT_INTERVAL_SECS: u64 = 30`，后续如要配置化再单独需求。

#### 心跳间隔决策备忘（2026-06-28 用户确认）

| 选项 | 一天/终端 | 适用场景 |
|---|---|---|
| **30s（现状）** | 2880 次 | 看板需要近实时在线、唤醒/网络抖动容差由 P0-2"连续 ≥6 次失败升 error"兜底 |
| 60s（备选 ⭐） | 1440 次 | 主流 SaaS 桌面客户端工业值，QPS 减半，UI 体感无差别 |
| 120s（备选） | 720 次 | 看板可接受分钟级精度 |

**决策理由**：MGR 侧目前未对心跳频率给出强约束，30s 已通过联调且 Cycle 4 实测无 QPS 压力；保持现状。**触发再调整的信号**：MGR 看板/运维同学反馈 QPS 过高，或上量到 100+ 终端时再回头评估改 60s。改的成本仅一行常量 + 重跑 TC-2.1。

### P0-2 失败重试与节流

| 调用 | 失败处理 |
|---|---|
| `record` | 登录链路里只调 1 次,失败不阻塞登录;错误写日志 + 缓存到 `TerminalRuntimeState.last_record_error`;**下一次心跳前自动补一次 record**(最多重试 1 次/分钟,避免风暴)。 |
| `heartbeat` | 单次失败仅记录错误,不退避(下一拍照常发);**连续 ≥6 次失败**(≈3 分钟)后把日志级别从 `warn` 升 `error`,但不停止定时器。 |
| `status/change` | 仅记录错误,不重试;`offline` 上报由退出/关闭流程做"尽力一次"。 |

- 所有失败不通过 SSE 推送到前端(本任务线范围外);只走 `tracing` 日志 + `TerminalRuntimeState` 内存状态。
- 不引入持久化重试队列。

### P0-3 退出/关闭时的 offline 上报

- **退出登录路径**(`portal_logout` command 内):
  1. 先调 `status/change` 上报 `offline`,**整体超时 2s**(`tokio::time::timeout`),超时即放弃;不阻塞 logout 主流程。
  2. abort heartbeat。
  3. 清 session 文件 + 内存状态(沿用现有 logout 行为)。
- **应用关闭路径**(Tauri `RunEvent::ExitRequested`):
  1. 拦截一次 exit,触发 `status/change` 上报 `offline`,**整体超时 1.5s**,完成或超时后 `api.prevent_exit()` 之外 resume exit。
  2. 同步 abort heartbeat。
  3. 不做持久化离线标记;若超时未送达,接受 MGR 侧靠 heartbeat 超时自然判离线。

### P0-4 tenant_id 来源

- 字段:`PortalUser.tenant_id`(`i64`,见 [src-tauri/src/lib.rs:23](src-tauri/src/lib.rs#L23) 与 [src-tauri/src/lib.rs:135](src-tauri/src/lib.rs#L135))。
- 取值时机:**从内存中的 `PortalSession` 读**,不再回查 session 文件。
- 缺失/未登录:`record` 与 `status/change` 直接返回 `NOT_AUTHENTICATED` 错误,不发请求;heartbeat 不依赖 tenant_id 故可继续。
- `tenant_id == 0`:按既定决策本轮直接透传,coder-agent 不做特殊分支;联调结果回写 [flow.md](flow.md)。

### P0-5 terminal-identity.json 路径与 schema

- 路径:`app.path().app_data_dir() / terminal-identity.json`,与 [src-tauri/src/lib.rs:73-87](src-tauri/src/lib.rs#L73-L87) 中 `portal-session.json` 同目录。
- Schema(JSON):

  ```json
  {
    "schema_version": 1,
    "terminal_id": "uuid-v4",
    "device_id": "uuid-v4",
    "created_at": 1719555600
  }
  ```

- 读写规则:
  - 首次启动:文件不存在 → 生成 `Uuid::new_v4()` 作为 `terminal_id`,`device_id = terminal_id`,`created_at = now_seconds()`,写盘。
  - 后续启动:读文件;**`schema_version` 不识别时**记录 warn 并按当前规则覆盖重建(本轮简单处理,不做迁移)。
  - 解析失败/IO 失败:走内存 fallback(本进程内生成临时 ID),不阻断登录;flow.md 暴露此偏差。
- 与登录 session 解耦:logout **不**删除 `terminal-identity.json`(终端 ID 与用户身份分离)。

## 第六部分 · 对账与优化清单

| 优先级 | 项目 | 原因 | 建议处理 |
|---|---|---|---|
| P0 | 状态枚举 | 用户已确认本轮只需要在线/离线 | 使用 `online` / `offline` |
| P0 | tenantId=0 行为 | 当前 QA 登录用户 tenant_id 为 0 | 暂定接受，实施联调时记录 MGR 实际行为 |
| P0 | 网关转发可用性 | 全局设计要求走 Portal 网关 | 用 Portal JWT 请求 `/api/v1/mgr/rpa-terminal/record` 验证转发 |
| P1 | 设备信息采集范围 | 全量硬件信息可能依赖较多 | 第一版采集 hostname/os/内存/磁盘/分辨率，MAC/IP 尽力 |
| P1 | 心跳间隔 | Swagger 未说明频率 | 初始建议 30s，后续按 MGR 要求调整 |
| P1 | reason=session_restored 区分 | 当前登录与 session 恢复都用 "login" | 本轮接受统一用 "login"，后续如 MGR 需要区分再加 source 参数 |
| P1 | screen_resolution 填 "unknown" | 避免引入 winapi 依赖 | 本轮接受 "unknown"，后续如 MGR 需要真实值再引入 display-info 或 winapi |
| P1 | WindowEvent::Destroyed 替代 RunEvent::ExitRequested | 沿用项目既有钩子，更轻量 | 接受当前实现，已满足 1.5s 超时尽力上报 offline |
| P2 | 心跳首拍时机 | 当前第一次心跳在 record 后 30s 发出，而非立刻 | 不影响功能，后续如需要立即首拍再调整 |
| P2 | logout 不清 identity 文件 | 终端标识与用户身份分离 | 接受，此行为符合设计理念，补入 plan 共识 |

## 第七部分 · 实施时由 coder-agent 决策并回写 flow.md(P1)

> 这些项不影响契约,允许 Cycle 2 现场决定;flow.md 必须如实记录最终选择。

| # | 项目 | 备选/默认 |
|---|---|---|
| P1-A | 设备信息采集库 | 默认引入 `sysinfo` crate(跨平台、维护活跃);若编译/体积有问题再退到手写 Windows API |
| P1-B | MAC/IP 采集失败 | 失败时字段填空串 `""`(非 null),MGR 若拒绝再改 |
| P1-C | `status/change.reason` 填法 | `online` → `"login"` 或 `"session_restored"`(区分两条调用路径);`offline` → `"logout"` 或 `"app_exit"` |
| P1-D | 心跳间隔配置化 | 本轮写死 30s,不引入配置文件 |
| P1-E | 测试 1.2 tenantId=0 判定 | MGR HTTP 200 即视为通过;flow.md 记录响应体与是否落库(若可观测) |
| P1-F | logout 不清 identity 文件 | 终端标识与用户身份分离;已确认接受 |
| P1-G | 心跳首拍不立即发包 | 首拍仅重置 interval，第一次真实发包在 30s 后;已确认接受 |

STATUS: CONVERGED
