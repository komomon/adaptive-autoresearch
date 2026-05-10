# Harness

`harness` 是 Adaptive Autoresearch 的控制面。它负责把评测集、目标审计项目、候选版本、评分和 keep/discard 决策串成可恢复的闭环。

## 当前真实流程

```text
normalized cases
-> run_experiment.py 初始化 run 和 split
-> run_candidate.py 选择 staged/full 策略
-> run_packet.py 按 case 调用目标审计项目
-> canonicalize_target_output.py 把 raw output 对齐成 TargetAuditResult
-> grade_run.py 评分
-> run_candidate.py keep/discard
-> advance_candidate.py 生成并应用下一轮 packet
-> run_autoresearch.py 执行多轮自动优化
```

## 统一入口

推荐从 `main.py` 进入：

```powershell
py -3.14 .\adaptive-autoresearch\harness\main.py --help
```

子命令：

- `smoke`：验证目标项目调用链。
- `init`：初始化 run。
- `eval`：评测已有 candidate。
- `advance`：推进一个新 candidate。
- `auto`：执行完整多轮闭环。

## 关键脚本

- `_shared.py`：低风险公共工具。不会删除 candidate、packet、grading 或 target-result artifacts。
- `normalize_xlsx_to_jsonl.py`：把 Excel 评测集转换为 `NormalizedCase` JSONL。
- `build_llm_review_queue.py`：把需要人工/LLM 复核的稀疏 case 抽成队列。
- `run_experiment.py`：创建 run 目录、split、run-state、scoreboard。
- `run_packet.py`：按 split 执行 case，支持并发、重试、状态文件和 canonicalization。
- `grade_run.py`：按 `TargetAuditResult` 和人工 expected 字段评分。
- `run_candidate.py`：执行 candidate 级评测并做 keep/discard。
- `advance_candidate.py`：prepare/propose/apply/evaluate 四阶段推进 candidate。
- `run_autoresearch.py`：多轮自动优化循环，支持 resume 和 round retry。
- `version_backend.py`：准备 candidate workspace，隔离目标审计项目版本。
- `model_backends.py`：Claude Agent SDK 与 OpenAI-compatible backend 工具。

## 重要边界

当前 harness 管理的是“目标审计项目”的候选版本，不是每条 case 的被审计仓库。

`case.repo.url` 和 `case.repo.branch` 当前会传入目标项目的 `case_json`。如果目标项目会根据这些字段自己拉取代码，则可以直接使用。否则后续需要补 `repo materializer`，由 harness 统一 clone/checkout 被审计仓库并传入 `audited_repo_path`。

## 评分规则

`grade_run.py` 已读取 manifest 中的：

- `grading.match_rules.require_type_match_when_available`
- `grading.match_rules.require_evidence_for_high_confidence`

因此当配置要求类型匹配或高置信证据时，错误类型或无证据高置信结果不会被算作真正命中。

## 故障排查

常看位置：

- `run-state.json`
- `scoreboard.json`
- `candidate-ledger.jsonl`
- `decisions/*.decision.json`
- `target-results/<candidate>/status/*.status.json`
- `packets/<packet_id>/apply-result.json`

失败现场默认保留。不要默认清理 incomplete candidate 或 packet，这些 artifacts 对定位模型调用、canonicalization、grader 和 keep gate 问题很重要。
