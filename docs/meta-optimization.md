# Meta Optimization

## 结论

v1 只允许“配置级元优化”，不开放任意代码生成型 mechanism research。

## 可优化项

- role split
- topology activation
- search order
- packet selection policy
- verifier intensity
- context packing
- failure taxonomy
- taboo search memory
- lesson merge policy

## 禁止优化项

- expected labels
- holdout membership
- grading rubric meaning
- vulnerability taxonomy semantics
- hard invariants

## 为什么要收这么紧

如果 outer loop 可以改标签、改 rubric、改 holdout，它就会自然滑向“刷榜器”而不是“方法优化器”。对你的目标来说，这会直接把系统推向过拟合。
