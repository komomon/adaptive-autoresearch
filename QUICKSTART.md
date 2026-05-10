# Adaptive Autoresearch Quickstart

## 一句话入口

日常只需要记住这个入口：

```powershell
py -3.14 D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\harness\main.py
```

子命令：

- `smoke`：验证目标 skill/agent 项目能否被调起，并产出可评分结果。
- `init`：初始化一个 run，生成 split、run-state、scoreboard。
- `eval`：评测一个已有 candidate。
- `advance`：推进一轮新 candidate。
- `auto`：执行完整闭环：baseline -> 提案 -> 修改 -> 回归 -> keep/discard。

## 运行前准备

```powershell
py -3.14 -V
$env:ANTHROPIC_AUTH_TOKEN="你的 key"
```

需要安装：

- `PyYAML`
- `openpyxl`
- `claude-agent-sdk`

Windows 如果使用 Claude Agent SDK，还需要按 SDK 要求配置 Git Bash。普通 OpenAI-compatible model call 不会自动加载 skill；真正调用 skill/agent 会话请使用 `claude-agent-sdk-python`。

## 最短 smoke 验证

```powershell
py -3.14 D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\harness\main.py smoke `
  --manifest D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\examples\deepseek-smoke.eval-manifest.yaml `
  --case-file D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\examples\smoke\BenchmarkTest00008.case.json `
  --output-dir D:\ccode\aicode\aicode002-claudecode\autoresearch\autoresearch-results\smoke\manual-smoke
```

smoke 主要验证三件事：

- 目标项目能否被 SDK 调起。
- 目标项目 raw output 能否 canonicalize 成 `TargetAuditResult`。
- grader 所需字段是否齐全。

## 自动优化闭环

```powershell
py -3.14 D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\harness\main.py auto `
  --manifest D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\examples\deepseek-smoke.eval-manifest.yaml `
  --rounds 3
```

中断后恢复同一个 run：

```powershell
py -3.14 D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\harness\main.py auto `
  --manifest D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\examples\deepseek-smoke.eval-manifest.yaml `
  --run-dir D:\ccode\aicode\aicode002-claudecode\autoresearch\autoresearch-results\runs\<run_id> `
  --rounds 3
```

恢复时会跳过已完成 baseline，并根据已完成的非 baseline decision 文件继续下一轮。失败现场不会自动删除，便于排障。

## 从 Excel 生成 JSONL

如果评测集是 `.xlsx`，先转成 `NormalizedCase` JSONL：

```powershell
py -3.14 D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\harness\normalize_xlsx_to_jsonl.py `
  --input D:\path\to\cases.xlsx `
  --sheet cases `
  --output D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\datasets\normalized-cases.jsonl `
  --map repo.url=repo_url `
  --map repo.branch=repo_branch `
  --map entry.name=entry_name `
  --map expected.has_vulnerability=has_vulnerability `
  --optional-map case_id=case_id `
  --optional-map entry.transport=transport `
  --optional-map entry.language=language `
  --optional-map expected.vulnerability_type=vulnerability_type `
  --optional-map expected.vuln_function_or_line=vuln_function_or_line `
  --optional-map expected.severity=severity `
  --optional-map expected.key_anchor=key_anchor `
  --optional-map expected.key_sink=key_sink `
  --optional-map expected.actor_model=actor_model `
  --optional-map notes=notes `
  --default-transport other `
  --default-language unknown
```

必填映射：

- `repo.url`
- `repo.branch`
- `entry.name`
- `expected.has_vulnerability`

缺少可选字段时，脚本会写入默认值或标记到 `normalization.missing_fields`，后续可再用 LLM review/canonicalization 补齐。

生成后在 manifest 中指向 JSONL：

```yaml
dataset:
  source:
    kind: jsonl
    path: D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/datasets/normalized-cases.jsonl
  normalize_to: D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/datasets/normalized-cases.jsonl
```

## repo.url 支持格式

`repo.url` 建议填写 Git 可 clone 的地址。推荐格式：

```text
https://github.com/org/repo.git
https://github.com/org/repo
D:/ccode/aicode/some-local-repo
file:///D:/ccode/aicode/some-local-repo
git@github.com:org/repo.git
```

本地路径不需要 `file://` 前缀，推荐直接写普通路径并使用 `/`：

```text
D:/ccode/aicode/BenchmarkJava-master
```

Windows 反斜杠路径也可以，但在 JSON 中需要转义：

```json
{
  "repo": {
    "url": "D:\\ccode\\aicode\\BenchmarkJava-master",
    "branch": "master"
  }
}
```

当前版本注意：`repo.url` / `repo.branch` 会进入传给目标审计项目的 `case_json`，但 harness 还没有统一执行 clone/checkout。如果目标审计项目自己会根据 `repo.url` 拉代码，就可以直接使用；否则后续需要补 `repo materializer`，由 autoresearch 统一生成 `audited_repo_path`。

## 常用 manifest 配置

目标项目路径：

```yaml
experiment:
  target_project:
    repo_path: D:/ccode/aicode/gitcode/back/authscan-2
```

目标项目调用方式：

```yaml
experiment:
  target_project:
    invocation:
      mode: claude-agent-sdk-python
      cwd: D:/ccode/aicode/gitcode/back/authscan-2
      model: qwen3.6-plus
      api_key_env: ANTHROPIC_AUTH_TOKEN
      base_url: https://dashscope.aliyuncs.com/apps/anthropic
      thinking:
        type: adaptive
      effort: high
      max_turns: 12
      timeout_seconds: 3600
      heartbeat_interval: 60
      max_timeout_extensions: 1
```

执行控制：

```yaml
execution:
  modes:
    - foreground
    - background
    - resume
  resume_completed_cases: true
  case_concurrency: 1
  candidate_evaluation:
    strategy: staged
  case_retry:
    max_attempts: 2
    backoff_seconds: 2
  round_retry:
    max_attempts: 2
```

`case_retry` 是单 case 调目标项目失败后的重试配置。`round_retry` 是整轮 candidate 推进失败后的重试配置。

## profile 选择

- 越权、未授权、身份冒用、跨租户：`authz-and-identity`
- SQLi、RCE、SSRF、文件类、反序列化：`traditional-sink-driven`
- 红包、余额、支付、退款、订单、优惠券、积分：`business-logic-and-funds`
- 混合链路或不确定场景：`generic-vuln-audit`
- 组合风险/跨域链路：`composite-mixed-risk`

越权审计推荐：

```yaml
experiment:
  profile: authz-and-identity
```

## editable_scope

只允许优化方法论、prompt、skill、agent 编排时：

```yaml
editable_scope:
  - prompts/
  - skills/
  - configs/
  - orchestrator/
  - agents/
```

允许修改整个目标项目时：

```yaml
editable_scope:
  - ./
```

## staged 策略

`staged` 的执行顺序：

```text
dev
-> dev 过门禁后才跑 holdout / cross_repo / canary
-> 全部门禁通过才 keep
```

门禁关注：

- dev 有提升。
- holdout 不下降。
- cross_repo 不下降。
- evidence adequacy 不下降。
- 高置信误报率不上升。

`case_filter` 会先裁剪 case，再按 `dataset.split` 分桶；正式评测建议去掉 `case_filter`。

## 结果在哪里看

一次 run 的核心产物在：

```text
autoresearch-results/runs/<run_id>/
```

常看文件：

- `run-state.json`：当前 candidate、supervisor 状态、最近失败阶段。
- `scoreboard.json`：baseline/best/current 指标。
- `decisions/<candidate>.decision.json`：candidate keep/discard 原因。
- `packets/<packet_id>/packet.json`：本轮优化提案。
- `packets/<packet_id>/apply-result.json`：实际修改了哪些文件。
- `target-results/<candidate>/status/*.status.json`：每个 case 的执行/重试状态。
- `lesson-ledger.md`：每轮沉淀的方法级经验。

## 当前边界

已经具备：

- 调用目标 skill/agent 项目。
- target raw output 到 `TargetAuditResult` 的 canonicalization。
- case 级并发、重试、心跳、状态文件。
- baseline / candidate 评测和 keep/discard。
- 断点恢复和 round 重试。
- candidate workspace 版本隔离。

仍需注意：

- 当前 harness 尚未统一拉取 `case.repo.url + case.repo.branch`，被审计代码拉取逻辑暂时需要目标审计项目自己完成。
- 评测集质量仍需要人工维护，尤其是人工 expected 字段和关键证据位置。
- 自动优化只应学习方法论、组织方式、证据结构和上下文策略，不能把评测集标签学成规则库。
