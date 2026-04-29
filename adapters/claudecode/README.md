# Claude Code Adapter

推荐以 `AGR` 为主循环纪律参考。

建议直接吸收：

- fresh context per iteration
- metric / guard separation
- variance-aware acceptance
- exhausted approaches
- supervisor pattern

可以参考但不必照搬：

- `Claude_Autoresearch_Skill` 的交互入口设计

该 adapter 必须保证与 Codex 版输出同构 artifact，并遵守相同的 keep/discard 与 anti-overfit 约束。
