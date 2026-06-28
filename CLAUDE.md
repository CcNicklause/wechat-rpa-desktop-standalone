# 项目工作流约定

本项目使用多 Agent 编排开发流程。**优先使用 `/orchestrate` 命令**，不要绕过流程直接写代码或改代码。

## 启动命令

| 场景 | 命令 |
|---|---|
| 新项目（从需求开始） | `/orchestrate new "需求一句话描述"` |
| 老项目改造 | `/orchestrate legacy "项目路径 + 改动需求"` |
| 从断点继续 | `/orchestrate continue` |
| 查看 agent 是否加载 | `/agents` |

## Agent 分工（不要混用）

- **plan-agent**: 需求、技术设计、评估、测试清单。**只写文档，不写代码。**
- **coder-agent**: 代码实现、读代码产出功能流程文档。**功能流程文档必须反映代码实际行为，禁止复述设计文档。**
- **test-agent**: 执行测试、产出结构化测试报告。**只报告 bug，不修 bug。**

## 文档约定

所有产出物放 `docs/` 下。**默认走轻量模板**，重模板仅在显式声明时启用。

### 默认（轻量）— 大部分迭代用这套

```
docs/
├── orchestrator-state.md             # 当前流程进度，每个节点完成后更新
├── {topic}-plan.md                   # 需求 + 技术设计 + 测试清单 合一
├── {topic}-flow.md                   # 功能流程文档（反映代码现状，对照 plan 的设计部分）
└── {topic}-test.md                   # 测试报告（test-agent 产出）
```

`{topic}` 用一个连字符短语命名本次迭代（例如 `rpa-hardening`、`friend-acceptance-v2`），不带版本号。一次迭代结束 3 份文档归档到 `docs/archive/` 保留历史，下次迭代用同样的 3 份再开一轮。

### 重模板（拆分）— 仅在以下场景启用，需在 `/orchestrate` 命令里加 `--full-docs`

- 跨多个 service / 模块的协议变更
- 状态机重新设计（不是补一两个状态）
- 拆 dev cycle 多于 3 个，或预计 5 工人日以上
- 团队 review 需要分文档签字

重模板恢复成：`requirements.md` / `technical-design.md` / `dev-cycles.md` / `dev-cycle-{N}.md` / `feature-flow-v{N}.md` / `optimization-checklist-v{N}.md` / `test-checklist-v{N}.md` / `test-report-v{N}.md`。版本号 `v{N}` 仅在重模板里启用。

### 老项目场景

老项目沿用 `-{service}-{module}` 后缀规则（轻、重模板都适用）。

## 关键工作流原则

### 文档对账机制
- plan-agent 写的设计（轻模板里是 `{topic}-plan.md` 的设计章节；重模板里是 `technical-design.md`）= 期望
- coder-agent 写的 `{topic}-flow.md` / `feature-flow-v{N}.md` = 事实
- 两者 diff 出优化清单 → 循环到收敛

**coder-agent 绝不能把设计文档复述一遍当功能流程文档**，否则永远收敛不了。

### STATUS 信号
每个 subagent 响应末尾必须有状态行，orchestrator 靠它判断下一步：
- `STATUS: CONVERGED` / `NEEDS_ITERATION`（plan-agent）
- `STATUS: READY_FOR_REVIEW`（coder-agent）
- `STATUS: ALL_PASSED` / `HAS_FAILURES` / `BLOCKED`（test-agent）

如果某次响应漏了 STATUS，直接要求补上，不要自行推断。

### 循环上限
所有自动循环硬上限 **5 轮**。到上限不再自动迭代，必须由人决策。

## 人工介入时机

orchestrator 默认只在以下 3 种情况打断我：
1. 需求/设计/修改文档定稿前的最后确认
2. 评估或测试循环达到 5 轮上限
3. subagent 报告 BLOCKED 或异常

其他场景全自动推进。**不要因为单个文件改动、库选型、文档格式细节来问我。**

## 不在工作流里的请求

如果我直接说"帮我改一下 src/xxx.py"这种**绕过工作流**的请求：
- 小修小补（typo、注释、显式我说的单行修改）→ 直接做
- 涉及功能逻辑变更 → 提醒我："这个改动建议走 `/orchestrate legacy`，要不要我启动？"
- 紧急 hotfix → 直接做，但改完提醒我同步更新 feature-flow 文档

## 项目特定信息
-参考 docs/项目文档索引.md