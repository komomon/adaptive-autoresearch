# Target Project Contract

## 结论

`autoresearch` 不关心你的目标项目内部到底是：

- 单 skill
- 单 agent
- 多 skill
- agent team

它真正关心的是两件事：

1. 怎么稳定调用
2. 怎么稳定得到可评分结果

所以目标项目只需要对 `autoresearch` 暴露一个稳定契约，不需要为了接入而重写内部架构。

## 1. 推荐调用方式

当前项目只保留两类模型调用路径：

1. `claude-agent-sdk-python`
2. `openai-compatible-chat`

其中推荐项是：

- 主路径：`claude-agent-sdk-python`
- fallback：`openai-compatible-chat`

说明：

- `claude-agent-sdk-python`
  是真正的 agent session 路径，适合直接运行本地 skill / agent-team 项目。
- `openai-compatible-chat`
  只是一次普通模型调用，不是持久 agent 会话。
  它适合做：
  - fallback
  - canonicalization
  - probe / smoke
  - 预加载 `SKILL.md` 的兜底调用

## 2. 每个 case 的最小输入

目标项目至少应能消费这些字段：

- `case_id`
- `repo.url`
- `repo.branch`
- `entry.name`
- `entry.transport`
- `entry.language`
- `profile`

可选增强字段：

- `expected.vulnerability_type`
- `notes`
- `expected.key_anchor`
- `expected.key_sink`

注意：

- `expected.has_vulnerability` 不应作为目标项目主分析逻辑的输入答案。
- 人工标签属于 grader，不属于目标项目“背答案”。

## 3. 输出契约

目标项目本身可以继续输出 rich output，例如：

- 参数分析
- 调用链分析
- trust chain
- lane artifacts
- markdown 报告
- `analysis.json`
- `report.json`

`autoresearch` 不要求你砍掉这些输出。

它只要求在评测入口额外做一层 canonicalization，把 rich output 映射成统一的：

- `TargetAuditResult`

对应 schema：

- [target-audit-result.schema.json](D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/schemas/target-audit-result.schema.json)

## 4. 为什么要单独做 canonicalization

标准链路应该是：

```text
target project rich output
  -> canonicalize_target_output.py
  -> TargetAuditResult
  -> grade_run.py
  -> scoreboard / decision
```

这样做的原因是：

- 目标项目可以继续保留自己的 rich output
- grader 不需要去理解长篇自然语言散文
- 评测口径更稳定
- 可以计算 `accuracy / precision / recall / f1`
- 可以检查 evidence 是否命中人工标注附近

## 5. 当前项目里的对应实现

### 目标项目调用

- [run_packet.py](D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/harness/run_packet.py)

### rich output 对齐

- [canonicalize_target_output.py](D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/harness/canonicalize_target_output.py)

### 评分

- [grade_run.py](D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/harness/grade_run.py)

## 6. 方法论优先和最小必要修改

这是接入和优化目标项目时的硬约束：

### 允许优化

- role split
- dispatch strategy
- checkpoint policy
- evidence schema
- verifier strength
- context packing
- output normalization
- guard / judge 流程

### 禁止优化

- 堆漏洞关键词规则
- 堆字段名特判
- 堆框架名 shortcut
- 根据评测集硬编码 case 特征
- 修改人工标签语义

### 最小必要修改原则

每个 packet 只允许一个主要方法论变更。

可以是：

- 改一处 prompt contract
- 改一处 lane 拆分
- 改一处 verifier 顺序
- 改一处 artifact schema

不应该是：

- 一轮同时改很多大方向
- 一轮混入多条不相关策略

否则你无法知道指标变化到底来自哪里。
