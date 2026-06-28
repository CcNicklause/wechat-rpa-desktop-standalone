# 开发规范

本文档用于约束前端、后端、RPA 调度和开发测试页的实现范式。后续 AI 或开发者改代码时，应优先遵循本文档，再参考局部文件现有写法。

## 总体原则

- 保持链路语义清晰：上游拉取、RPA 加微、好友对账、状态上报是四个独立阶段，不要把阶段职责混在一起。
- 保持改动局部：优先沿用现有模块和 helper，不为单个需求引入新的框架或大抽象。
- 保持真实链路优先：开发测试能力只能辅助验证，不应改变生产路径的状态机语义。
- 保持可验证：状态机、上报、存储、RPA 关键路径改动必须补对应测试。

## 前端规范

### 目录分层

- `src/components/ui/`：原子 UI 组件，不能包含业务含义。
  - 适合：`Button`、`Input`、`Textarea`、`Select`、`Label`、`Badge`、`Card`、`Switch`、`Toast`。
  - 可以包含基础交互规范，例如 `Button` 的 `cursor-pointer`。
  - 不要包含状态机文案、接口调用、业务枚举。
- `src/components/common/`：跨业务复用组件。
  - 适合未来抽取：`StatusBadge`、`EmptyState`、`PanelHeader`。
  - 可以知道通用状态 tone，但不应绑定某个页面 API。
- `src/components/features/`：页面和业务组件。
  - 适合：`DevTesting`、`RiskControl`、`UpstreamConfig`、`JobProgress`。
  - 页面内可以组合 `ui` 和 `common`，也可以调用 API。

### UI 与 Tailwind 使用边界

- 用 shadcn 风格原子组件承载重复交互控件。
  - 表单控件使用 `Input`、`Textarea`、`Select`、`Label`。
  - 状态展示优先使用 `Badge`。
  - 按钮统一使用 `Button`。
- 用 Tailwind 管页面布局。
  - Grid、Flex、间距、滚动区域、响应式布局可以直接写 class。
  - 不要为一次性布局抽组件。
- 业务态组件只在第二次或第三次重复出现后再抽。
  - 当前优先候选：`StatusBadge`、`EmptyState`、`PanelHeader`。

### 前端数据与请求

- API 请求统一使用 `requestLocalApi`。
- 服务端状态使用 TanStack Query 拉取和刷新。
- 跨刷新需要保留的测试态使用 Zustand store，不要散落在 `localStorage` 直接读写。
- 开发测试页可以提供 mock、清理、立即触发按钮，但按钮文案必须明确是开发用途。

### 确认与危险操作

- 真实 RPA、清空队列、清理待对账等危险操作必须二次确认。
- 目前允许使用 `window.confirm`；如果后续引入 `AlertDialog`，统一替换，不要混用多套确认体验。

## 后端规范

### 目录分层

- `api/routes/`：只做 HTTP 入参解析、权限校验、调用 service/store、返回响应。
  - 不要在 route 中写复杂状态机。
  - 开发测试接口必须放在 `/dev/...` 路径下。
- `services/`：业务流程和状态机。
  - RPA 编排：`rpa_orchestrator.py`。
  - 上游调度：`upstream_scheduler.py`。
  - 好友对账：`friend_acceptance.py`。
- `storage/`：SQLite 持久化。
  - SQL 和表结构集中在 `sqlite_store.py`。
  - service 不应直接拼复杂 SQL，除非已有局部模式且范围很小。
- `schemas/`：请求/响应模型和枚举。

### 错误处理

- 业务错误使用 `AppError`，包含稳定 `code` 和用户可读 `message`。
- 未找到资源使用统一 `not_found`。
- RPA 业务终态不要当系统异常处理。
  - 搜不到、已是好友、拒绝添加、风控属于业务终态。
  - 超时、进程中断、未找到微信窗口等属于系统/运行异常。

## 状态机规范

### Lead 状态

主链路状态：

```text
NEW_LEAD
-> CALLING
-> INTENT_CONFIRMED / RPA_PENDING_APPROVAL
-> RPA_EXECUTING
-> WECHAT_ADD_REQUESTED
-> WECHAT_ACCEPTED
```

业务终态：

```text
WECHAT_ALREADY_FRIEND
WECHAT_TARGET_NOT_FOUND
WECHAT_ADD_REJECTED
WECHAT_RISK_CONTROL
```

系统/开发终态：

```text
RPA_SIMULATED
RPA_FAILED
RPA_BLOCKED
```

### RPA 阶段职责

- RPA 加微阶段只负责执行添加动作。
- 真实 RPA 成功执行添加动作后，统一写为 `WECHAT_ADD_REQUESTED`。
- 不要因为执行过程中出现“通过朋友验证确认页”就直接写 `WECHAT_ACCEPTED`。
- 如果搜索阶段发现本来就是好友，写 `WECHAT_ALREADY_FRIEND`，并进入好友对账上报队列。

### 好友对账阶段职责

- 空闲态对账只扫描 `WECHAT_ADD_REQUESTED`。
- 对账确认已是好友后：
  - `leads.status -> WECHAT_ACCEPTED`
  - 写入 `friend_check_reports`，等待上游批量上报。
- 对账未确认时保持 `WECHAT_ADD_REQUESTED`，等待下次扫描。

## 本地存储规范

本地 SQLite 路径：

```text
python/backend/data/demo.db
```

主要表：

- `leads`：线索主状态和客户信息。
- `rpa_jobs`：RPA job、steps、错误码、业务终态。
- `audit_events`：审计事件。
- `daily_counters`：真实 RPA 每日限流计数。
- `upstream_config`：上游配置。
- `friend_check_reports`：好友对账上报 outbox。

运行截图、OCR 截图和临时图片属于运行产物，不要提交。

## 上报规范

### 加微结果上报

由 `UpstreamScheduler` 在 job 结束后调用：

```text
report_lead_status(lead_id, status, remark, error_details)
```

状态映射：

```text
REAL_COMPLETED / SIMULATION_COMPLETED -> REAL_SENT
REAL_BIZ_ALREADY_FRIEND -> BIZ_ALREADY_FRIEND
REAL_BIZ_TARGET_NOT_FOUND -> BIZ_TARGET_NOT_FOUND
REAL_BIZ_RISK_CONTROL -> BIZ_RISK_CONTROL
REAL_BIZ_ADD_REJECTED -> BIZ_ADD_REJECTED
FAILED -> BIZ_FAILED
```

不要把所有非失败结果都粗暴上报为 `REAL_SENT`。

### 好友对账上报

好友状态通过 `friend_check_reports` outbox 批量上报：

```text
report_friend_check(lead_id, is_friend)
```

状态流转：

```text
PENDING -> SENT
PENDING -> FAILED
```

失败时增加 `attempts`，超过最大次数后进入 `FAILED`。

## 开发测试规范

- 开发测试页可以调用 `/dev/...` 接口。
- `/dev/...` 接口不能成为生产链路依赖。
- “清理待对账”只应把 `WECHAT_ADD_REQUESTED` 标记为 `RPA_BLOCKED`，不要物理删除历史数据。
- 手动模拟已是好友时，必须能带上账号和昵称，方便验证上游消息。
- 立即上报按钮只用于开发阶段缩短等待，不改变后台定时批量上报机制。

## 测试规范

以下改动必须补测试：

- lead 状态机变化。
- RPA job 终态映射。
- 上游上报状态映射。
- outbox 入队、发送、失败重试。
- 开发接口的核心行为。

常用验证命令：

```powershell
pnpm -s build
```

```powershell
cd python
$env:PYTHONPATH='.'
uv run pytest backend/app/tests/test_friend_acceptance.py backend/app/tests/test_rpa_acceptance_lifecycle.py backend/app/tests/test_upstream_scheduler.py backend/app/tests/test_upstream_client.py
```

## Git 与提交规范

- 不提交运行产物：
  - `python/backend/data/*.png`
  - `.claude/`
  - `dist/`
  - 临时日志
- 提交前检查：
  - `git status --short`
  - `git diff --check`
  - 相关测试和前端 build
- 提交信息使用中文，描述业务结果，而不是描述“修改文件”。
  - 推荐：`完善好友对账状态机与开发清理能力`
  - 不推荐：`修改了一些文件`

## AI 协作约束

- 修改前先读现有模块，不要凭空新建平行架构。
- 优先复用 `ui` 原子组件和既有 service/store。
- 涉及真实 RPA、状态机、上游协议时，必须说明本地存储和上报影响。
- 不要把开发测试接口、mock 行为、生产路径混在一起。
- 不要提交用户未要求的运行截图、数据库、缓存或 `.claude/`。
