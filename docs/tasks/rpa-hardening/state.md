# Orchestrator State — RPA 加微链路加固

> 触发命令：`/orchestrate legacy "wechat-rpa-desktop-standalone：按上一轮代码审计结论修复加微链路 P0/P1 缺口 ..."`
> 场景：老项目改造（legacy），轻量模板（CLAUDE.md §22-50）
> 启动时间：2026-06-28
> 模式：手工编排（B 路径，`/orchestrate` 命令未在当前会话注册）

## 节点状态

| # | 节点 | 状态 | 产物 | 备注 |
|---|---|---|---|---|
| 0 | 启动登记 | ✅ DONE | docs/tasks/rpa-hardening/state.md | 本文件 |
| 1 | plan-agent: 合一计划文档 | ✅ DONE | docs/tasks/rpa-hardening/plan.md | 需求 + 设计 + 测试清单 三章节，STATUS: CONVERGED |
| 2 | **人工定稿**（CLAUDE.md §62 第 1 条） | ✅ DONE | — | 2026-06-28 用户签字"可以" |
| 3 | coder-agent: 切 dev cycle 实施 | ✅ DONE | 代码 + docs/tasks/rpa-hardening/flow.md | 3 个 cycle：基础设施 / 状态机 / 业务收尾 |
| 3.1 | Cycle 1：基础设施 | ✅ DONE | 需求 4 + 6 + 2 实现 + 测试 + flow.md 追加 | per-lead 互斥 / 401 续签 / outbox。82 个测试全绿，STATUS: READY_FOR_REVIEW |
| 3.2 | Cycle 2：状态机 | ✅ DONE | 需求 1 + 3 | RISK_FROZEN / 重试前核验。95 个测试全绿，STATUS: READY_FOR_REVIEW |
| 3.3 | Cycle 3：业务收尾 | ✅ DONE | 需求 5 + 7 | acceptance_attempts / 启动 reconciler。101 个测试全绿，STATUS: READY_FOR_REVIEW |
| 4 | plan-agent 对账：plan 设计章节 vs flow.md | ✅ DONE | docs/tasks/rpa-hardening/plan.md 第四部分·对账与优化清单 | 结论：功能完成；2 项 P1-test 已补，剩余 3 项非阻塞优化 |
| 5 | test-agent: 执行测试 | ✅ DONE | uv run pytest backend/app/tests | 103 passed, 4 FastAPI on_event deprecation warnings |

## 范围（一次性确认）

**P0**：① RISK_FROZEN 状态机 ② lead_status_reports outbox ③ RPA 重试前核验
**P1**：④ HTTP add_wechat per-lead 互斥 ⑤ acceptance_attempts 上限 + RISK/NOT_FOUND 转态 ⑥ 401 自动续签 ⑦ 启动 reconciler
**显式不在范围**：P2（前端运营级 UX）、P3（清死状态 / 真实 password change / SSE auth）

## 当前等待

Cycle 1 / 2 / 3 与 plan-agent 对账均已完成，P1-test 优化也已补齐。当前剩余为非阻塞优化清单：recover/reconciler 协同测试、终态 job report 回填 hardening、FastAPI lifespan 迁移。

## 2026-06-29 追加：好友资料页误判未搜到

- 最新数据：`job_b19f7d46d83b` / `lead_4b0c189d81aa` 搜索 `pixel_punk` 后，截图已是好友资料页，DB 却写为 `REAL_BIZ_TARGET_NOT_FOUND` / `WECHAT_TARGET_NOT_FOUND`。
- 根因：`TARGET_NOT_FOUND` 关键词“搜索结果为空”被 `rapidfuzz.partial_ratio` 通过好友页里的“搜索”误命中；由于判定顺序早于 `ALREADY_FRIEND`，覆盖了“发消息”好友态。
- 修复：`_detect_screen_state()` 内部在 `TARGET_NOT_FOUND` 与 `ALREADY_FRIEND` 同时参与时优先检查 `ALREADY_FRIEND`，仍保留 `RISK_CONTROL` 最高优先级。
- 已补测试：好友资料页 OCR 包含“搜索 + 发消息/语音聊天”时返回 `ALREADY_FRIEND`。
- 已跑：`uv run pytest backend/app/tests/test_vision_locator.py::TestScreenStateDetection -q`，`9 passed`；相关测试集 `42 passed`。

## 2026-06-29 追加：partial_ratio 短文本假阳性根治

- 触发：`job_b5810110bdcb` / `lead_dev_mock_1782729826329_0` 搜索 `18325661362` 后，截图显示已搜到用户「凡」且有“添加到通讯录”按钮，DB 却写 `REAL_BIZ_TARGET_NOT_FOUND`。
- 根因：上一轮修复只调整了判定顺序（`ALREADY_FRIEND` 优先），但本 case 无 `ALREADY_FRIEND` 信号。`_detect_screen_state` 的单词块兜底匹配将 OCR 词块 “搜索”（搜索按钮文字，2字）单独送入 `fuzzy_text_hit`，`rapidfuzz.partial_ratio("搜索结果为空", "搜索")` 将短串滑过长串得分 100，误命中 `TARGET_NOT_FOUND`。
- 修复：在 `fuzzy_text_hit`（`vision_locator.py`）的 `partial_ratio` 分支加 **50% 长度比例守卫**——`len(ocr_text) < len(keyword) * 0.5` 时跳过，防止短文本反向匹配到长关键词。
- 已补测试：`TestFuzzyTextHit` 8 个用例，覆盖短文本假阳性回归 + OCR 拼错容错 + 子串命中 + 空格不敏感。
- 已跑：`python -m unittest backend.app.tests.test_vision_locator -v`，`35 passed`，零回归。

## 2026-06-29 追加：验证语填写阶段微信卡死

- 触发：`job_3f5419a7fa99`、`job_43294647d300` 都在 `GREETING_FILLED` 后的 `_click_send_verify` 处抛 COM 异常 `(-2147220991, '事件无法调用任何订户')`，重试时微信进程已无响应（`WECHAT_NOT_FOUND`）。100% 复现。
- 现象：微信界面卡住不动，窗口还在但无法操作，需手动关闭。
- 根因：`clear_field()` 中 `Ctrl+A` → `Backspace` 零间隔连续发出，然后仅 0.15s 后又 `Ctrl+V` 粘贴。3 个快捷键在 ~0.2s 内打到 `mmui::VerifyFriendWindow`，微信 UI 线程来不及处理清空渲染就收到粘贴指令，卡死。
- 修复：
  - `windows.py:clear_field()` — `Ctrl+A` 与 `Backspace` 之间加 `time.sleep(0.15)` 间隔
  - `wechat_rpa.py:_fill_verify_message()` — 清空到粘贴的等待从 0.15s 加大到 0.5s
- 已跑：35 passed，零回归。需真机验证微信不再卡死。

## 2026-06-29 已纠正：「19 个执行中」实为僵尸中间态，非 running 孤儿

> 此前一度推断为"卡在 `RPA_EXECUTING`/`REAL_RUNNING` 的崩溃孤儿"并登记了"Cycle 4 回收 running 孤儿"——**经查 demo.db 后作废**。

- 经查 `python/backend/data/demo.db`：`RPA_EXECUTING` lead = **0**，running job = **0**；`recover_interrupted_jobs` 工作正常（120 个 FAILED job 均已回收，[sqlite_store.py:333-386](python/backend/app/storage/sqlite_store.py#L333-L386)）。
- "19 个执行中"= KPI「执行中」卡 = `LeadStatsResponse.running` 桶（[lead.py:78-85](python/backend/app/schemas/lead.py#L78-L85)）= `CALLING`(11) + `RPA_SIMULATED`(8) = 19。
  - `CALLING` 11 条：age 6~13 天，开发测试创建 lead + call-start 后未提交 call-summary，永久卡通话中。
  - `RPA_SIMULATED` 8 条：age 6~13 天，模拟加微完成，但 mock/simulation 不真实发送，永远进不了 `WECHAT_ADD_REQUESTED`，挂在 running 桶。
- 上游模式 = **mock** → `WECHAT_ADD_REQUESTED` = 0 → 好友对账队列天然为空（复查只扫该状态），**非 bug**。
- **结论**：无 running 孤儿需回收；"Cycle 4 回收 running 孤儿"方向作废。

### 重新识别的候选问题（待定方向后再立 Cycle）

| # | 问题 | 性质 |
|---|---|---|
| ① | KPI「执行中」把 `CALLING`/`RPA_SIMULATED` 计入，与副标题"客户端引擎正在操作的队列数"语义不符 | 统计分类 / 展示 — **已在 `frontend-leads-board` Cycle 9 修复**（running 桶收窄为 `RPA_PENDING_APPROVAL`+`RPA_EXECUTING`） |
| ② | `CALLING` 僵尸（创建后未提交小结）无任何回收机制 | 状态流转缺口 — 未做（用户选择只修 KPI 分类） |
| ③ | `RPA_SIMULATED` 无终态，模拟完成后永久挂 running 桶 | 状态流转缺口 — 未做（用户选择只修 KPI 分类） |
