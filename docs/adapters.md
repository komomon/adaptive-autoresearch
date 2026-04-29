# Adapters

## 结论

这个项目只维护一个通用核心，不拆三套工程。运行时差异通过 adapter 吸收。

## Codex Adapter

Codex 侧默认吸收 `codex-autoresearch2` 的运行时设计：

- foreground / background / resume
- launch/runtime/state/context/lessons 分层
- helper authoritative state
- parallel batch protocol

选择性吸收 `codex-autoresearch`：

- dashboard
- MCP tool contract
- quality-gap loop
- finalize 体验

## Claude Code Adapter

Claude Code 侧默认吸收 `AGR` 的循环纪律：

- fresh context per iteration
- metric / guard separation
- variance-aware acceptance
- exhausted approaches
- supervisor pattern

交互入口可以参考 `Claude_Autoresearch_Skill`，但评分契约必须与 Codex 版完全对齐。

## 适配层统一要求

两个 adapter 都必须支持：

- `foreground`
- `background`
- `resume`

两个 adapter 都必须输出同构 artifact：

- `entry_pack`
- `path_pack`
- `context_pack`
- `guard_pack`
- `evidence_pack`
- `verdict`
- `grading`
