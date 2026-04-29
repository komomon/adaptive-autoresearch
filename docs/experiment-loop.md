# Experiment Loop

## 结论

对漏洞审计场景，推荐的 autoresearch 主循环是：

1. 建立 baseline
2. baseline 跑一轮 split
3. 汇总失败 case 和聚合指标
4. 归因失败模式
5. 生成一个 candidate version
6. candidate 跑整批 split
7. 计算 accuracy / precision / recall / f1
8. 再结合 evidence / 泛化门禁决定 keep 或 discard

不是“按单 case 通过就立刻定版”。

## 为什么这样更适合漏洞审计

漏洞审计不同于简单单目标优化，因为你同时关心：

- 召回率
- 精确率
- 误报控制
- 证据充分性
- 跨仓泛化

如果只按单 case 推进，会很快把系统推向题库式过拟合。

## 每轮循环的推荐结构

```text
baseline
  -> run dev
  -> collect failures
  -> propose packet
  -> candidate version
  -> run_candidate.py
  -> compute metrics
  -> if improved: run holdout / cross_repo / canary
  -> compute metrics
  -> keep or discard
```

落地到当前 harness 时，推荐入口顺序是：

1. `run_experiment.py` 初始化 run 和 split
2. 准备一个目标项目 candidate version
3. `run_candidate.py` 作为 candidate 级控制面入口
4. `run_candidate.py` 内部逐 split 调 `run_packet.py`
5. `run_packet.py` 完成目标项目调用、canonicalization、grading

## 指标

每个 candidate 至少要有：

- `accuracy`
- `precision`
- `recall`
- `f1`

这些指标应该按 split 记录：

- `dev`
- `holdout`
- `cross_repo`
- `canary`

还要额外记录：

- `evidence_adequacy`
- `chain_completeness`
- `high_confidence_false_positive_rate`

## 失败 case 的作用

失败 case 不直接决定版本留存，它们主要用于：

- failure clustering
- packet 归因
- lesson 候选
- 后续回归检查

## 推荐版本策略

每轮只允许一个主要方法论变更进入 packet。

例如：

- 调整 role split
- 提高 verifier 强度
- 改 checkpoint 结构
- 改 evidence 包布局

不要在一轮里混入多个大改动，否则很难知道指标变化是由什么引起的。
