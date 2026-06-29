# 任务线索引

大任务型需求按任务线目录维护。每条任务线至少包含：

- `plan.md`：需求、设计、测试清单。
- `flow.md`：代码真实落地后的功能流程与偏差说明。
- `state.md`：当前编排节点、状态、测试结果与下一步。
- `test.md`：测试报告，需要 test-agent 独立产出时创建。

## 使用规则

- 继续已有任务：直接更新对应 `docs/tasks/<task-line>/`。
- 新的大主题：从 `docs/tasks/_template/` 复制三件套并改名。
- 小修小补：不强制建任务线；如果影响已有任务线，需要同步更新对应 `flow.md` 或 `state.md`。
- 每次完成大任务后，在本索引更新状态与摘要。

## 渐进式读取

为节省上下文，处理任务时不要全量读取所有任务线：

1. 先读本文件确认任务线。
2. 再读目标任务线的 `state.md`。
3. 需要需求/设计细节时再读 `plan.md`。
4. 需要核对实际行为、继续实现或对账时再读 `flow.md`。
5. 不读取无关任务线目录。

## 当前任务线

| 任务线 | 状态 | 说明 | 入口 |
|---|---|---|---|
| `project-closure-audit` | IN_PROGRESS | 全项目前端、后端/本地 API、RPA sidecar、状态流、审计日志、任务文档闭环审计；本轮不先改代码 | [state.md](project-closure-audit/state.md) |
| `rpa-hardening` | DONE | RPA 加微链路 P0/P1 加固，103 个后端测试通过 | [state.md](rpa-hardening/state.md) |
| `login-system` | IMPLEMENTED | P0 真实登录与 session 恢复已落地；终端心跳后续推进 | [state.md](login-system/state.md) |
| `rpa-terminal-reporting` | DONE | MGR 终端 record/heartbeat/status 3 接口已接入，9/9 用例联调全过；StrictMode 双触发 bug 已修 | [state.md](rpa-terminal-reporting/state.md) |
| `frontend-leads-board` | DONE | Cycle 1：双栏 + Drawer；Cycle 2：KPI 真实化 + DevTesting 联通；Cycle 3-6：线索展示中文化与详情抽屉用户视角收敛 | [state.md](frontend-leads-board/state.md) |
| `desktop-runtime-hardening` | P1 IMPLEMENTED | 动态本地端口、前端动态 API base、不再强杀 8000；sidecar 退出监控与有限自动重启已落地 | [state.md](desktop-runtime-hardening/state.md) |
| `dev-testing-panel` | CYCLE 1 DONE | 开发测试页页面级能力维护；Cycle 1：一键清空本地数据（二次确认，保留上游配置）已落地 | [state.md](dev-testing-panel/state.md) |

## 可选任务线示例

| 任务线 | 适用场景 |
|---|---|
| `upstream-integration` | 上游客户池、状态同步、错误码兼容、token 生命周期 |
| `operator-dashboard` | 运营后台、outbox 积压告警、手动补偿、冻结状态可视化 |
| `rpa-observability` | 审计事件、结构化日志、截图追踪、失败原因聚合 |
| `desktop-packaging` | Tauri/Python 打包、配置加载、自动更新、Windows 权限 |
| `security-hardening` | API token、SSE 鉴权、敏感信息脱敏、本地接口访问控制 |
| `data-migration` | SQLite schema 版本、迁移记录、旧库兼容、修复脚本 |
| `frontend-workbench` | 销售工作台、任务详情、人工确认 UX、错误提示 |
