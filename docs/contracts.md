# Contracts

## 结论

这套项目的核心不是 prompt，而是契约。没有统一 contract，adapter、harness、grader 和 lessons 都会失真。

## 核心接口

### `NormalizedCase`

统一评测输入对象，定义在：

- `templates/normalized-case.schema.json`

### `AuditArtifactBundle`

统一中间产物集合，定义在：

- `schemas/audit-artifact-bundle.schema.json`

### `GradingResult`

统一评分结果，定义在：

- `schemas/grading-result.schema.json`

### `RunState`

统一运行状态，定义在：

- `schemas/run-state.schema.json`

## 约束

所有 adapter 必须遵守：

- case 输入结构一致
- artifact 输出结构一致
- grading 字段一致
- state 更新必须通过 helper authoritative state
- lessons 只允许记录方法级经验
