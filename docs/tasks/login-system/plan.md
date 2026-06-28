# 登录系统 · 计划

> 任务线：`login-system`
> 状态：IMPLEMENTED
> Portal 源码核对：`C:\Users\Administrator\Desktop\aisales\aisales-portal`
> 本轮范围：P0 真实登录闭环；终端设备信息、心跳、状态变更后续单独推进。

## 第一部分 · 需求

### 需求 1：桌面端接入 Portal 真实登录

- 业务问题：当前桌面端登录是前端 mock，只校验用户名非空和密码长度，写入 `localStorage.mock_token`，没有接入 Portal 账号体系。
- 验收标准：
  1. 桌面端登录页改为手机号登录，支持密码登录；短信验证码登录作为同一页面的备选方式。
  2. 桌面端不提供注册入口，未注册或登录失败时引导用户去 Web Portal 注册或处理账号问题。
  3. 登录成功后保存 Portal 返回的 `access_token` 与 `user`，主界面显示真实用户信息。
  4. 应用启动时用 `GET /api/v1/auth/me` 校验已有 session；401 或网络鉴权失败时清理 session 并回到登录页。

### 需求 2：区分 Portal 用户 JWT 与本地 sidecar Token

- 业务问题：当前 Tauri 生成的 `LOCAL_SECURITY_TOKEN` 只保护 `127.0.0.1:8000` Python 后端，不能当作用户登录凭证；后续如果混用会造成安全和链路语义混乱。
- 验收标准：
  1. `get_security_token` 继续只用于本地 React -> Python API。
  2. Portal 登录 token 单独由 Tauri/Rust session 管理，不写入 `localStorage.mock_token`。
  3. 前端业务请求本地 Python 时仍带本地 token；本轮不把 Portal token 注入 Python。

### 本轮暂不包含：RPA 终端身份与心跳

- 设备信息、`terminalId`、终端注册、心跳、运行状态变更后续等登录接完再做。
- 原因：当前 Python sidecar 在 Tauri `setup()` 阶段启动，早于用户登录；首版不应把 Portal token 注入 Python 或把终端链路绑进登录成功条件。

## 第二部分 · Portal 源码核对

### 已确认接口

- `POST /api/v1/auth/login`：手机号 + 密码登录，请求 `{ phone, password }`，见 Portal `api/src/auth/auth.controller.ts`。
- `POST /api/v1/auth/login-by-sms`：手机号 + 短信验证码登录，请求 `{ phone, code }`。
- `POST /api/v1/sms/send-code`：请求 `{ phone, type: "login" }`。
- `GET /api/v1/auth/me`：需要 `Authorization: Bearer <access_token>`。
- `POST /api/v1/mgr/rpa-terminal/list`：Web 端已封装，MGR 请求经 Portal `MgrController` 透传；本轮仅记录，不接入。

### 与外部分析文档的校正点

- `JwtStrategy` 当前兼容 `tenant_id` 为数字或数字字符串；桌面端仍应保留 Portal 返回的数字 `tenant_id`，不要自己重写 token/user。
- Portal CORS 当前是单 origin：`origin: runtimeConfig.FRONTEND_URL`。桌面端应优先走 Tauri Rust command 调 Portal API，绕开 WebView CORS。
- Portal Web client 只明确封装了 `rpa-terminal/list`；`register` 和 `heartbeat` 走 `/api/v1/mgr/rpa-terminal/*` 转发是合理路径，但请求/响应字段需要以下游 MGR OpenAPI 或联调结果为准。
- Portal `auth.service.ts` 仍存在开发万能密码 `111111`，`sms.service.ts` 存在万能验证码 `1111`；桌面端不能依赖这些行为。
- `POST /auth/login` 返回的 `user.id` 是数据库数字 ID，且包含 `user_id`；`GET /auth/me` 返回的 `id` 是 `user.user_id`，没有 `user_id` 字段。桌面端 session 恢复时必须归一化用户模型。

## 第三部分 · 技术设计

### 设计 1：Tauri/Rust 承担 Portal HTTP 与 session

- 数据模型：
  - `PortalUser`：`id`, `user_id`, `email`, `phone`, `name`, `role`, `tenant_id`。
  - `PortalSession`：`access_token`, `user`, `saved_at`。
- 代码触点：
  - `src-tauri/src/lib.rs`：新增 `portal_login_password`、`portal_login_sms`、`portal_send_sms_code`、`portal_get_session`、`portal_logout`、`portal_validate_session`。
  - `src/stores/useAuthStore.ts`：移除 mock token 逻辑，改为调用 Tauri command。
  - `src/App.tsx`：登录表单改为手机号、密码/验证码 Tab、启动时恢复 session。
- 风险与权衡：
  - 走 Rust command 可规避 CORS，但需要增加 Rust HTTP 依赖和错误映射。
  - 当前 `src-tauri/Cargo.toml` 没有 HTTP client；本轮需增加 `reqwest` 或等价依赖。
  - Portal API base URL 默认 QA：`http://aisales-portal.app.qa.internal.weimob.com/api/v1`，并保留 `AISALES_PORTAL_API_BASE` 覆盖能力。
  - 初期 session 可写入 app data JSON；后续再升级 OS keyring 或 Tauri store。

### 设计 2：认证错误统一处理

- 数据模型：前端 store 增加 `status: "checking" | "anonymous" | "authenticated"`，避免启动时闪登录页。
- 代码触点：
  - `src/lib/api.ts` 继续只处理本地 Python 401。
  - 新增 Portal API command 错误结构：`{ code, message, status }`。
- 风险与权衡：
  - Portal 无 refresh token，401 只能清 session 后重新登录。
  - 网络错误和凭证错误要分开提示，避免误导用户重新注册。

### 设计 3：本轮边界

- 保持 Python sidecar 启动与本地 API 鉴权现状不变。
- 不新增 `AISALES_PORTAL_TOKEN` env，不让 Python 直接访问 Portal。
- 不生成 `terminalId`，不调用 MGR 终端注册/心跳。
- 后续终端链路优先由 Rust 代理 Portal/MGR 调用，再按需要设计 Python 协同。

## 第四部分 · 测试清单

| # | 用例 | 前置 | 触发 | 期望 |
|---|---|---|---|---|
| 1.1 | 密码登录成功 | mock Portal 返回 token + user | 提交手机号和密码 | store 进入 authenticated，用户信息为 Portal user |
| 1.2 | 密码错误 | Portal 返回 401 `手机号或密码错误` | 提交错误密码 | 停留登录页，显示可读错误，不写 session |
| 1.3 | 短信验证码发送 | Portal 返回 success | 点击获取验证码 | 按钮进入 60s 倒计时 |
| 1.4 | 短信登录未注册 | Portal 返回 401 `该手机号未注册` | 提交验证码登录 | 提示前往 Web Portal 注册 |
| 1.5 | 启动恢复 session 成功 | 本地有 session，`/auth/me` 返回 200 | 启动应用 | 直接进入主界面 |
| 1.6 | 启动恢复 session 失效 | 本地有 session，`/auth/me` 返回 401 | 启动应用 | 清 session，进入登录页 |
| 2.1 | 本地 sidecar token 不受影响 | 已登录 Portal | 调用本地 Python API | 仍使用 `get_security_token` Bearer |

## 第五部分 · 对账与优化清单

| 优先级 | 项目 | 原因 | 建议处理 |
|---|---|---|---|
| P0 | Portal API base URL | Rust command 需要知道登录接口地址 | QA 已确认；生产地址发布前确认 |
| P0 | `/auth/me` 用户模型归一化 | 登录响应与恢复响应字段不完全一致 | 在 Rust 或前端 store 内统一为 `PortalUser` |
| P0 | Portal 生产万能密码/验证码 | 安全债务，桌面端不能依赖 | Portal 侧按环境关闭或移除 |
| P1 | session 安全存储 | JSON 文件比 keyring 弱 | 第一版限制 ACL，后续升级 keyring |
| P1 | MGR 终端 register/heartbeat OpenAPI | 后续设备信息与心跳需要，Portal 只透传 | 登录完成后单独确认并开子阶段 |
| P1 | token 过期后 Python 协同 | 如果后续 Python 直接访问 Portal，需要刷新/通知机制 | 优先让 Rust 代理 Portal 调用，避免首版注入 token |

STATUS: IMPLEMENTED
