# Harness

## 结论

harness 在这套方案里不是辅助脚本，而是核心模块。没有 harness，就没有稳定、可复现、可回滚的自优化。

## 输入

统一从 xlsx 规范化到 `NormalizedCase`，至少包含：

- `case_id`
- `repo.url`
- `repo.branch`
- `entry.name`
- `entry.transport`
- `entry.language`
- `expected.has_vulnerability`
- `expected.vulnerability_type`
- `expected.vuln_function_or_line`
- `notes`

建议额外保留：

- `expected.severity`
- `expected.key_anchor`
- `expected.key_sink`
- `expected.business_invariant`
- `expected.actor_model`

## 执行流

1. 拉取指定 repo 与 branch
2. 建立只读评测 workspace
3. 生成 `entry_pack`
4. 调用目标 agent system 审计
5. 收集 artifacts
6. 按 profile rubric 评分
7. 输出 case 级与 run 级结果
8. 仅写入方法级 lessons

## 输出 artifacts

每个 case 固定输出：

- `entry_pack.json`
- `path_pack.json`
- `context_pack.json`
- `guard_pack.json`
- `evidence_pack.json`
- `verdict.json`
- `grading.json`

## harness 必须保证的事情

- 输入规范化可复现
- 拉仓和分支选择可审计
- grader 不依赖目标系统自报结果
- artifacts 结构跨 adapter 一致
- keep/discard 决策可回放
