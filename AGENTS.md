# 每次处理问题前，请按渐进式披露读取 docs，禁止一上来全文扫描所有 docs
# 读取顺序：1) docs/项目文档索引.md 2) docs/tasks/README.md 3) 用户指定或最相关任务线的 state.md
# 只有需要设计细节时再读 plan.md；只有需要核对实际行为或继续实现时再读 flow.md
# 大任务型需求按任务线维护：docs/tasks/<task-line>/plan.md、flow.md、state.md
# 如果用户指定已有任务线，继续更新对应目录；如果是新的大主题，先新建任务线目录
# 你可以根据实际情况更新 docs/ 下的文档，特别是过程和状态，但不要读取或改动无关任务线
# 每一次commit 需要加step
# 每个功能需要带测试代码,你需要确保能测试通过

# 任务线 + superpowers 轻量策略
# 默认以 docs/tasks/<task-line>/ 作为项目级记忆和执行骨架；superpowers 只作为局部方法论辅助，不默认完整展开重流程
# 优先使用任务线 state.md / flow.md 承接连续小迭代；只有新大主题或跨模块重构时才考虑完整 spec/plan 流程
# brainstorming：用于产品方向、信息架构、取舍讨论；小迭代只借用其思路，不强制写完整 spec、提交 spec、再写 plan
# test-driven-development：用于 bugfix、状态映射、展示文案、URL 映射等可测试规则；先补最小失败测试，再实现
# verification-before-completion：完成前必须跑对应测试与构建/回归命令，用实际输出确认通过
# writing-plans / finishing-a-development-branch：仅在大任务、跨模块计划、PR/合并/分支收尾时使用；普通小修不默认触发
# 如果 superpowers 的完整流程与当前任务线轻量策略冲突，优先遵循本项目 AGENTS.md 的任务线策略

# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

