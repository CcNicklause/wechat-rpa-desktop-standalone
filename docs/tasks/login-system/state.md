# 登录系统 · 编排状态

> 任务线：`login-system`
> 启动时间：2026-06-28
> 模式：实施

## 节点状态

| # | 节点 | 状态 | 产物 | 备注 |
|---|---|---|---|---|
| 0 | 启动登记 | DONE | state.md | 已建立登录系统任务线 |
| 1 | plan-agent: Portal 源码核对 | DONE | plan.md | 已核对 Portal auth/sms/jwt/mgr/web client |
| 2 | coder-agent: 实施 | DONE | 代码 + flow.md | P0 真实登录闭环已落地 |
| 3 | plan-agent: 对账 | DONE | plan.md 优化清单 | 终端心跳仍在后续阶段 |
| 4 | test-agent: 测试 | DONE | 测试命令 | `cargo test`、`pnpm -s build`、`git diff --check` 通过 |

## 范围

- 将当前桌面端 mock 登录替换为 Portal 真实登录设计。
- 保留本地 sidecar token，用于保护 React -> Python 本地接口。
- 本轮只做 Portal 用户登录、session 持久化与启动恢复。
- 设备信息、`terminalId`、终端注册、心跳、运行状态变更后续等登录接完再做。

## 已核对

- 当前桌面端 `useAuthStore` 使用 `localStorage.mock_token`，未调用真实后端。
- 当前 Tauri `get_security_token` 只生成本地随机 token，并通过 `LOCAL_SECURITY_TOKEN` 注入 Python sidecar。
- Portal `POST /api/v1/auth/login`、`POST /api/v1/auth/login-by-sms`、`POST /api/v1/sms/send-code`、`GET /api/v1/auth/me` 可作为真实登录接口。
- Portal CORS 当前为单 origin，桌面端推荐通过 Rust command 调 Portal API。
- Portal `/api/v1/mgr/*` 为通用转发；终端 register/heartbeat 本轮暂不接入。
- Portal 登录响应与 `/auth/me` 响应的 user 字段不完全一致，需要在实现时做归一化。

## 后续拆分

- 生产 Portal API base URL 后续发布前确认；当前默认使用 QA：`http://aisales-portal.app.qa.internal.weimob.com/api/v1`。
- MGR 终端记录、心跳、状态变更后续单独推进。

## 本轮结果

- 已移除前端 mock 登录路径。
- 已通过 Tauri/Rust command 调 Portal 登录接口。
- 已默认连接 QA Portal API：`http://aisales-portal.app.qa.internal.weimob.com/api/v1`。
- 已支持密码登录、短信登录、短信发送、启动恢复 session、退出登录。
- 已保持本地 Python sidecar token 链路不变。
- 已启动 Vite 开发服务器：`http://127.0.0.1:1420`。
