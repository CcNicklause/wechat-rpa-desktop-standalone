# 登录系统 · 实际功能流程

> 反映代码现状，**不**复述设计文档。设计期望见 [plan.md](plan.md)。

## Cycle 1

### 已落地

- `src-tauri/src/lib.rs`
  - 新增 Portal 登录 command：`portal_login_password`、`portal_login_sms`、`portal_send_sms_code`、`portal_get_session`、`portal_logout`。
  - Portal API base URL 通过 `AISALES_PORTAL_API_BASE` 配置，默认 QA：`http://aisales-portal.app.qa.internal.weimob.com/api/v1`。
  - 使用 `reqwest` 由 Rust 侧调用 Portal，绕开 WebView CORS。
  - Portal HTTP client 设置 15 秒超时，避免网络异常时登录长时间卡住。
  - session 写入 Tauri app data 目录下的 `portal-session.json`。
  - `/auth/login` 与 `/auth/me` 的 user 响应会归一化为统一 `PortalUser`。
  - 401 恢复 session 时清本地 session 并返回未登录。
- `src/stores/useAuthStore.ts`
  - 移除 `localStorage.mock_token` 逻辑。
  - 新增 `checking / anonymous / authenticated` 状态。
  - 登录、短信验证码、启动恢复、退出都调用 Tauri command。
- `src/App.tsx`
  - 登录页改为手机号登录。
  - 支持密码登录和短信验证码登录两个模式。
  - App 启动时先执行 `portal_get_session`，避免已登录用户闪登录页。
- `src/components/layout/Sidebar.tsx`、`src/components/features/AccountManagement.tsx`
  - 用户展示改为 Portal 用户信息：姓名/手机号/角色/租户 ID。
  - 账号管理页不再模拟“修改密码成功”，改为提示前往 Web Portal 处理密码。
- `src-tauri/Cargo.toml` / `Cargo.lock`
  - 新增 `reqwest` 依赖。
- 保持本地 API 鉴权不变：
  - `get_security_token` 继续返回本地 sidecar token。
  - Python sidecar 仍只接收 `LOCAL_SECURITY_TOKEN`，本轮不注入 Portal JWT。

### 与设计的偏差

- Portal API base URL 已默认指向 QA Web 同源 API；本地/生产仍可通过 `AISALES_PORTAL_API_BASE` 覆盖。
- 账号管理页仍展示本地 API 安全接入令牌，这是 sidecar token，不是 Portal JWT；当前按“区分 token”设计保留。
- 未生成或上报 RPA `terminalId`，符合本轮边界。

## 测试覆盖

```powershell
cd src-tauri
cargo test
```

结果：通过。2 个 Rust 单元测试覆盖 Portal user 归一化。

```powershell
pnpm -s build
```

结果：通过。TypeScript 与 Vite production build 成功。

```powershell
git diff --check
```

结果：通过。仅有 Windows 换行提示，无 whitespace error。

## 本地预览

```text
http://127.0.0.1:1420
```

说明：浏览器/Vite 预览可看 UI；真实 Tauri command 登录需在 Tauri 壳中运行。

STATUS: IMPLEMENTED

## Cycle 2

### 已落地

- `src-tauri/src/lib.rs`
  - Portal 登录、短信验证码、`/auth/me` session 恢复请求统一携带桌面端来源头：
    - `x-aisales-client: desktop`
    - `x-aisales-session-scope: desktop`
  - 新增 `portal_requests_are_tagged_as_desktop_client` 单元测试，固定桌面端请求标记，便于 Portal 后端按 Web/Desktop 做会话隔离。

### 对账说明

- 桌面端仍只保存 Portal 返回的 `access_token`，不会主动刷新或替换 Web 端 JWT。
- 如果 Web 登录和桌面登录仍互相踢下线，根因在 Portal 后端当前按用户维度只保留单个有效 token/session；需要 Portal 后端识别上述桌面端请求头，并按 `user + session_scope` 或真正无状态 JWT 策略允许 Web/Desktop 并行。

## Cycle 2 测试覆盖

```powershell
cd src-tauri
cargo test portal_requests_are_tagged_as_desktop_client
```

结果：通过。1 个 Rust 单元测试覆盖桌面端 Portal 请求来源头。
