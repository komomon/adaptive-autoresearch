# Harness

`harness` 负责把“系统优化”转化为可复现的实验。

从通用层面看，它的真实工作流是：

1. 你给 `autoresearch` 两样东西：
   - 目标漏洞审计项目
   - 评测集
2. `autoresearch` 按 case 一条一条地调你的目标项目
3. 收集你的目标项目对每个 case 的审计结果和中间 artifact
4. 与人工评测结果比较
5. 判断当前修改应 `keep` 还是 `discard`
6. 只沉淀方法级 lessons，用于继续优化你的目标项目

也就是说，这里的被优化对象不是 `autoresearch` 自己，而是你那个基于 LLM 的 skill / agent teams 漏洞挖掘项目。

后续建议优先在这里补齐：

- xlsx -> normalized case 转换器
- repo/branch materializer
- audit runner wrapper
- artifact collector
- grader
- run summary writer

当前已经补了第一步的 CLI 骨架：

- `normalize_xlsx_to_jsonl.py`
- `build_llm_review_queue.py`
- `canonicalize_target_output.py`

它负责把评测 xlsx 转成 `NormalizedCase` JSONL，供后续 harness、adapter、grader 统一消费。

如果你的 xlsx 字段不全，它现在支持“稀疏输入”思路：

- 自动生成 `case_id`
- 缺失 `transport` 时允许给默认值
- 缺失 `language` 时允许给默认值
- 缺失部分非主指标字段时写入 `normalization.missing_fields`
- 对需要后续大模型补全判断的行标记 `normalization.needs_llm_review`

这里的大模型补全只能做“结构补全”和“字段归一化”，不能伪造人工标签或漏洞结论。

## 当前推荐入口

当前推荐把 autoresearch 的入口放在 Python harness，而不是直接放在一个大模型长会话里。

推荐入口形态：

1. `normalize_xlsx_to_jsonl.py`
2. `build_llm_review_queue.py`
3. `canonicalize_target_output.py`
4. `run_experiment.py`
5. `run_candidate.py`
6. `run_packet.py`
7. `grade_run.py`

这样每个 case 可以独立执行，避免整批评测集把单次模型上下文打满。

## Candidate 级入口

当前推荐的版本级入口是：

```powershell
python .\adaptive-autoresearch\harness\run_candidate.py `
  --manifest .\adaptive-autoresearch\examples\authz-claudecode.eval-manifest.yaml `
  --run-dir .\autoresearch-results\runs\<run_id> `
  --candidate-id candidate-0001
```

它会做三件事：

1. 以 `candidate_id` 初始化当前版本账本
2. 逐 split 调 `run_packet.py`
3. 按 keep gate 决定 `keep` 或 `discard`

默认按 manifest 的 `execution.candidate_evaluation.strategy` 运行：

- `staged`
  先跑 `dev`，只有 dev 达到提升门禁才继续跑 `holdout / cross_repo / canary`
- `full`
  每个 candidate 默认把 4 个 split 全跑完，再做 keep/discard

## Smoke 入口

如果你只是想先验证“目标项目调用链能不能打通”，推荐先跑：

```powershell
python .\adaptive-autoresearch\harness\run_target_smoke.py `
  --manifest .\adaptive-autoresearch\examples\authscan-benchmarkjava-smoke.eval-manifest.yaml `
  --case-file .\adaptive-autoresearch\examples\smoke\BenchmarkTest00008.case.json `
  --output-dir .\autoresearch-results\smoke\authscan-benchmarkjava-00008
```

这个入口只验证：

1. 目标项目调用是否成功
2. raw output 是否被捕获
3. canonicalization 是否能落成 `TargetAuditResult`

它不会直接做 candidate 级 keep/discard。

如果你要走 `claude-agent-sdk-python` 主路，当前建议直接用 `Python 3.14` 运行，例如：

```powershell
py -3.14 .\adaptive-autoresearch\harness\run_target_smoke.py `
  --manifest .\adaptive-autoresearch\examples\authscan-benchmarkjava-sdk-smoke.eval-manifest.yaml `
  --case-file .\adaptive-autoresearch\examples\smoke\BenchmarkTest00008.case.json `
  --output-dir .\autoresearch-results\smoke\authscan-benchmarkjava-sdk-00008
```

## LLM 复核队列

如果 `normalize_xlsx_to_jsonl.py` 产出的某些 case 含有：

- `normalization.needs_llm_review = true`

那么可以先用：

```powershell
python .\adaptive-autoresearch\harness\build_llm_review_queue.py `
  --input .\datasets\authz_cases.jsonl `
  --output .\datasets\authz_review_queue.jsonl `
  --prompt-output .\datasets\authz_review_prompt.md
```

这个脚本不会直接调用模型，而是把需要复核的行单独抽出来，供后续 adapter 或 runner 调模型处理。

## Raw Output Canonicalization

目标项目可以保留 richer output，比如参数分析、调用链分析、lane 级中间产物。

评测时只需要把 richer output 再映射成 `TargetAuditResult`。

当前 `run_packet.py` 已经改成优先外调这个独立 canonicalizer。

推荐脚本：

```powershell
python .\adaptive-autoresearch\harness\canonicalize_target_output.py `
  --case-file .\datasets\case-0001.json `
  --raw-file .\autoresearch-results\raw\case-0001.txt `
  --output .\autoresearch-results\canonical\case-0001.json `
  --mode claude-agent-sdk-python `
  --cwd D:\your-target-project `
  --allowed-tool Read `
  --permission-mode default
```

设计红线：

- grader 不能依赖目标系统自报
- case workspace 默认只读
- lessons 只能回写方法级经验

## 推荐用法

```powershell
python .\adaptive-autoresearch\harness\normalize_xlsx_to_jsonl.py `
  --input .\datasets\authz_cases.xlsx `
  --output .\datasets\authz_cases.jsonl `
  --sheet cases `
  --map case_id=case_id `
  --map repo.url=repo_url `
  --map repo.branch=repo_branch `
  --map entry.name=entry_name `
  --map entry.transport=transport `
  --map entry.language=language `
  --map expected.has_vulnerability=has_vulnerability `
  --map expected.vulnerability_type=vulnerability_type `
  --map expected.vuln_function_or_line=vuln_function_or_line `
  --optional-map expected.severity=severity `
  --optional-map expected.key_anchor=key_anchor `
  --optional-map expected.key_sink=key_sink `
  --optional-map notes=notes
```
