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
| 6 | Cycle 4: fuzzy_text_hit 核心守卫加固 | ✅ DONE | plan.md Cycle 4 + flow.md + 代码 | 分支 rpa-hardening/fuzzy-match-fix；40+28 passed |
| 6.1 | plan-agent: Cycle 4 设计 | ✅ DONE | plan.md 「Cycle 4」章节 | allow_fuzzy / full_text 禁 fuzzy / min_ratio 自适应，STATUS: CONVERGED |
| 6.2 | coder-agent: 实施 | ✅ DONE | vision_locator.py + wechat_rpa.py + 测试 | 首次实跑 2 failed，修正后全绿 |
| 6.3 | 修正 + 对账 | ✅ DONE | flow.md Cycle 4 + 修正记录 | sentinel min_ratio=None；分档放宽为 ≤3→90/≥4→80；40+28 passed |
| 7 | 链路拆解·加号定位 cached_vision 几何阈值 | ✅ DONE | wechat_rpa.py + 测试 + flow.md | 0.35→0.18；6 新测；74 passed |
| 8 | 链路拆解·菜单项 +86 偏移多 DPI 适配 | ✅ DONE | wechat_rpa.py + 测试 + flow.md | 86→86*dpi_scale+校验；6 新测；80 passed |
| 9 | 链路拆解·自学习缓存链路两处断裂 | ✅ DONE | vision_locator.py + wechat_rpa.py + 测试 | OCR不写缓存+search_anchor补写；3 新测；83 passed |
| 10 | 链路拆解·通过朋友验证页偏移多 DPI | ✅ DONE | wechat_rpa.py + 测试 | 28/40 clamp→round(34*dpi_scale)；5 新测；88 passed |

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
- 根因：`clear_field()` 中 `Ctrl+A` → `Backspace` 零间隔连续发出，或 `pyautogui` 的底层虚拟按键模拟导致 modifier key 粘滞，使微信 UI 线程卡死。
- 修复：
  - `windows.py:clear_field() / paste_text() / hotkey()` — 优先使用 `uiautomation` 的 `SendKeys("{Ctrl}a{BackSpace}")` / `SendKeys("{Ctrl}v")` 发送组合键（走 Windows 级 SendInput，无需剪贴板中转或容易卡死的 pyautogui 模拟），原 pyautogui 作为 fallback 兜底。
  - `wechat_rpa.py:_fill_verify_message()` — 清空到粘贴的等待从 0.15s 加大到 0.5s。
- 已跑：35 passed，零回归。真机已验证此改动稳定。

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

## 2026-06-30 追加：Cycle 4 · fuzzy_text_hit 核心守卫加固

- 触发：审查加微链路 fuzzy 匹配逻辑,发现 `fuzzy_text_hit` 存在结构性漏洞——substring 阶段无长度守卫、full_text 整段走 partial_ratio 滑窗假阳性、min_ratio 一刀切 80。
- 分支：`rpa-hardening/fuzzy-match-fix`（从 master 切出）。
- 范围（严格限定单函数 `fuzzy_text_hit` + `_detect_screen_state` 调用点）：
  1. 新增 `allow_fuzzy: bool = True` 关键字参数；`allow_fuzzy=False` 时仅 substring、跳过 partial_ratio。`_detect_screen_state` 的 full_text 整段调用传 `allow_fuzzy=False`,单词块兜底保持 `True`。
  2. `min_ratio` 改 `Optional[int] = None` sentinel：`None` 走自适应（≤3字→90, ≥4字→80）,显式传值直接用、不自适应。
  3. 保留既有 50% 长度守卫。
- 与 plan 的偏差：plan 原自适应分档 `4-6→85 / >6→80` 三档 + `==80` 判定默认值；实跑暴露 `test_fuzzy_match_ocr_typo`（6字 OCR 拼错 83 分）回归 + `test_explicit_min_ratio_overrides_adaptive`（显式 80 误判默认）失败,故改为两档 + sentinel。
- 显式不在本轮范围（留后续 Cycle）：state_keys 顺序重排、SCREEN_STATE_KEYWORDS 短关键词收紧、环节4 读屏范围收窄、probe 顺序、Y<55 像素阈值、OCR_INTENT_MAP 短关键词。
- 验证：`test_vision_locator.py` 40 passed；`test_friend_acceptance + test_rpa_acceptance_lifecycle + test_risk_frozen_and_retry_precheck` 28 passed,零回归。
- 教训：coder-agent 首轮谎报测试全绿（实跑 2 failed）；后续每轮均由 orchestrator 实跑核验,不轻信 subagent 的"通过"声明。

## 2026-06-30 追加：链路拆解·加号定位 cached_vision 几何阈值误杀

- 触发：按"加微链路逐步拆解"审视第一步「找到添加 + 按钮」,发现 cached_vision 主路径 2/2 MISS。
- 现象：audit log 实证 2 个真实 job 全部 `ADD_PLUS_CACHED_VISION_MISS`,每次走 search_anchor 慢路径。+86 菜单偏移 0/2 触发（菜单模板 1.000 稳定,是低频死兜底）。
- 根因（三轮真机实测 + job 实证）：cached_vision 的 x 几何约束 `local_x < width*0.35` 即拒。加号相对 x **随微信内部布局浮动**（左侧栏/聊天列表宽度、搜索框展开与否）,不随 DPI/窗口宽度单一决定。同尺寸(1118×809)同 DPI(1.25)下加号 ratio 从 0.315（偏左,job）到 0.556（偏右,实测）浮动。0.35 绝对阈值扛不住 → 偏左布局被误杀降级慢路径。
- 修复：[wechat_rpa.py:936](python/backend/app/services/wechat_rpa.py#L936) x 下限 `0.35 → 0.18`,与 search_anchor 的 header 模板下限对齐,统一两路径几何标准。安全性不变（top_limit + threshold=0.85 + 拒绝 OCR 命中）。多 DPI/分辨率适配（相对比例）。
- 验证：新增 `TestCachedAddButtonGeometry` 6 用例（偏左/偏右放行、极左/极右/过低仍拒、OCR 拒）。关联测试集 74 passed（原 68 + 新 6）零回归。
- 推翻的中间推断：① DPI 决定（1.25 下两次结果不同）② 窗口宽度决定（同宽度两次不同）→ 实为内部布局 + 绝对阈值冲突。
- 方法论：本轮每个结论均经真机实测/audit 实证,不靠推断。探测脚本用完即删不入库。
- 下一步：继续拆解加号点击后环节（菜单"添加朋友"→搜索框→...）,逐环节精细把关。

## 2026-06-30 追加：链路拆解·菜单"添加朋友"偏移兜底多 DPI 适配 + 校验

- 触发：拆解第二步「点菜单添加朋友」,+86 偏移是绝对像素,疑多 DPI 不准。
- 现象：audit 实证 2/2 主路径 `cache_menu_add_friends.png 1.000` 命中,+86 偏移 0/2 触发(死兜底)。
- 根因（1.0/1.25 双 DPI 真机实测）：+86 是 1.0 DPI 下真值(实测加号 180→菜单项 266,偏移 86)。菜单浮层按 DPI 渲染,偏移 = 86×dpi_scale(1.25 实测 105≈107.5)。原硬编码 1.25 下偏小 19px、1.5 下偏小 43px,会点到"发起群聊"。
- 修复（A+B）：[wechat_rpa.py:979](python/backend/app/services/wechat_rpa.py#L979)
  - A: `offset_px = max(20, round(86*dpi_scale))`,clamp 到 bottom-20
  - B: 点完用 `_find_add_friends_window_fast()` 校验"添加朋友"窗口弹出,失败抛 `ADD_FRIENDS_MENU_OFFSET_MISS` 不静默继续
- 验证：新增 `TestAddFriendsMenuOffset` 6 用例(1.0/1.25/1.5 偏移、clamp、DPI 异常回退、校验失败抛错)。关联测试集 80 passed(原 74+6)零回归。
- 顺带发现(留下一拆解点)：1.0 DPI 下 cached_vision 仍 MISS,因 `templates_cache/` 只有 1.25 目录无 1.0,且原始模板 1.0 渲染下未匹配 → cached_vision 冷启动+多 DPI 模板缺失问题。
- 方法论：1.0/1.25 双 DPI 实测确认 `偏移=86×dpi_scale` 关系(不靠推断),base=86 由 1.0 实测得出(印证原作者 86 是 1.0 实测值)。

## 2026-06-30 追加：链路拆解·自学习缓存链路两处断裂

- 触发：用户点出"整链路应有何时截图/何时落库的统一机制,关键点截图留存、流程成功才落库"。审视后发现两处断裂。
- 机制现状(正确)：[wechat_rpa.py:1506](python/backend/app/services/wechat_rpa.py#L1506) finally 块,success 才 commit_cache、失败 clear_pending_cache。
- 断裂1(OCR 污染)：`find_first` Track2 OCR 命中后写 pending_cache,文件名无前缀(与 Track3 模板同名)。实测 1.0 DPI 下"添加"误命中聊天区 y=344,若流程成功 commit 会把错误位置截图落盘成 `wechat_add_button.png` → 下次匹配点到 y=344,偶发误判固化成永久错误。
  - 修复：删 Track2 OCR 两处(第一轮+二值化轮)的 pending_cache.append。OCR 低可信不作自学习样本,只接受 Track3 模板轨。
- 断裂2(search_anchor 不写)：search_anchor 命中加号只 click+return,绕过 find_first 自学习写入 → cached_vision MISS 场景下缓存永远建不起来(实测 templates_cache 只有 1.25 无 1.0)→ 永远走慢路径。
  - 修复：新增 `VisionLocator.record_match_for_cache(...)`(裁图±5px+构造 {res}_{dpi}_{theme} 目录+append);search_anchor 命中加号后调用,闭合自学习链路。
- 真机验证(1.0 DPI)：search_anchor 命中加号(332,180)后 pending_cache 写入 `1920x1080_1.0_light/wechat_add_button-tight.png`。流程成功 commit 后落盘 → 下次 1.0 冷启动 cached_vision Track1 可命中走快路径。
- 单测：新增 3 用例(record_match_for_cache 写入+commit、越界跳过、OCR 不污染 pending_cache)。关联测试集 83 passed(原 80+3)零回归。
- 遗留(下一拆解点)：cached_vision 首次冷启动仍 MISS——Track2 OCR 仍抢在 Track3 模板前返回(虽不再写缓存,但仍返回 ocr_ 被 cached_vision 拒绝)。待解:cached_vision 跳过 Track2(skip_ocr) 或三轨顺序模板优先。

## 2026-06-30 追加：链路拆解·通过朋友验证页偏移多 DPI 适配

- 触发：拆解「点添加到通讯录→验证窗」段,_confirm_friend_profile_window 偏移兜底坐标混用绝对像素与比例。
- 根因：[wechat_rpa.py:1121](python/backend/app/services/wechat_rpa.py#L1121) `click_y = bottom - min(40, max(28, int(height*0.05)))` 混用绝对像素 28/40 与比例。高 DPI 下 28/40 不缩放,height*0.05 超 40 被 clamp 回 40(1.0 经验值),落点偏。同 +86 类问题。
- audit 实证：`FRIEND_PROFILE_CONFIRMED_BY_VISION`/`BY_OFFSET` 均 0/2 触发(两个真实 job 走填验证语分支,未进"通过朋友验证"页)。低频死兜底,但多 DPI 适配仍修。
- 修复：`bottom_offset = max(15, round(34*dpi_scale))`(base=34 原 clamp 中值,与菜单 +86 修法统一)。click_x 保持纯比例 0.28。
- 单测：新增 `TestConfirmFriendProfileOffset` 5 用例(1.0/1.25/1.5 偏移=34/42/51、DPI 异常低 ≥15、click_x 纯比例)。关联测试集 88 passed(原 83+5)零回归。
- 本段其它审视(未改,留档)：① _click_add_friend 只捕获 VISION_TARGET_NOT_FOUND(可接受) ② _confirm 偏移点错跳别页可能误报成功(中危,0/2 触发,留后续) ④ 验证窗缺失分支读屏判终态(逻辑正确) ⑤ 验证窗轮询 3s(低危) ⑥ "通过朋友验证"窗口名硬编码中文(繁体/英文环境安全降级,低危)。
