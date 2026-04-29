# Grading

## 结论

对错判定应该定义在 grader 层，而不是定义在目标项目输出的自然语言里。

也就是说：

- 目标项目负责分析并输出结构化结果
- grader 负责判断这个 case 是跑对了还是跑错了

## 主判定

每个 case 的首要判定是：

- `verdict.has_vulnerability` 是否与人工标签一致

## 次判定

在主判定之外，还要看：

- `verdict.vulnerability_type` 是否一致或兼容
- 高置信度结论是否有足够 evidence
- evidence 是否命中人工提供的函数或代码行附近
- 是否存在“unknown / insufficient evidence”但仍高置信度下结论

## 聚合指标

每个 candidate version 至少计算：

- `accuracy`
- `precision`
- `recall`
- `f1`

此外还记录：

- `evidence_adequacy`
- `chain_completeness`
- `high_confidence_false_positive_rate`

## 高置信度要求

当结果满足以下条件时，grader 应判为高风险错误：

- `confidence` 很高
- 但 `evidence.locations` 为空
- 或 evidence 无法命中人工标签附近

## vulnerability_type 匹配建议

推荐采用：

- 完全匹配
- 或 profile 内兼容匹配

例如访问控制子类：

- `idor`
- `bola`
- `bfla`
- `broken-access-control`
- `unauthorized`
- `identity-impersonation`

可以在同一大类下设兼容表，但不能无限放宽到“只要说有洞都算对”。
