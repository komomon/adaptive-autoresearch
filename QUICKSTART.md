# Quickstart

## 结论

日常只需要记住一个入口：

```powershell
py -3.14 D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\harness\main.py
```

它现在提供 5 个子命令：

- `smoke`
  先验证“能不能调起目标项目，并拿到可评分结果”
- `init`
  初始化一个 run
- `eval`
  跑一个已有 candidate
- `advance`
  推进一轮新 candidate
- `auto`
  从 baseline 开始自动跑完整优化循环

## 1. 运行前准备

必须满足：

- 使用 `py -3.14`
- 已安装：
  - `claude-agent-sdk-python`
  - `openai`
  - `PyYAML`
- 已设置环境变量 `DASHSCOPE_API_KEY`

推荐先确认：

```powershell
$env:DASHSCOPE_API_KEY="你的 key"
py -3.14 -V
```

## 2. 最短可运行命令

直接跑当前自带 smoke 示例：

```powershell
py -3.14 D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\harness\main.py auto `
  --manifest D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\examples\authscan-benchmarkjava-sdk-smoke.eval-manifest.yaml `
  --rounds 1
```

这条命令会自动完成：

1. 初始化 run
2. 跑 baseline
3. 生成一个 packet
4. 修改 candidate 工作区
5. 回跑评测
6. 做 keep / discard
7. 写入 lesson ledger

## 3. 你平时怎么用

### 场景 A：先验证目标项目调用链能不能跑通

```powershell
py -3.14 D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\harness\main.py smoke `
  --manifest D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\examples\authscan-benchmarkjava-sdk-smoke.eval-manifest.yaml `
  --case-file D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\examples\smoke\BenchmarkTest00008.case.json `
  --output-dir D:\ccode\aicode\aicode002-claudecode\autoresearch\autoresearch-results\smoke\manual-smoke
```

适合先看 3 件事：

- 目标项目能不能被调起
- rich output 能不能被 canonicalize 成 `TargetAuditResult`
- grading 所需字段是不是齐

### 场景 B：只评测一个已有版本

先初始化：

```powershell
py -3.14 D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\harness\main.py init `
  --manifest D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\examples\authscan-benchmarkjava-sdk-smoke.eval-manifest.yaml
```

再评测：

```powershell
py -3.14 D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\harness\main.py eval `
  --manifest D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\examples\authscan-benchmarkjava-sdk-smoke.eval-manifest.yaml `
  --run-dir D:\ccode\aicode\aicode002-claudecode\autoresearch\autoresearch-results\runs\<run_id> `
  --candidate-id baseline
```

### 场景 C：在已有 run 上再推进一轮

```powershell
py -3.14 D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\harness\main.py advance `
  --manifest D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\examples\authscan-benchmarkjava-sdk-smoke.eval-manifest.yaml `
  --run-dir D:\ccode\aicode\aicode002-claudecode\autoresearch\autoresearch-results\runs\<run_id>
```

### 场景 D：让它自己连续跑多轮

```powershell
py -3.14 D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\harness\main.py auto `
  --manifest D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\examples\authscan-benchmarkjava-sdk-smoke.eval-manifest.yaml `
  --rounds 3
```

## 4. manifest 主要改哪些

日常主要改 manifest，不要先改 harness 代码。

模板文件：

- [eval-manifest.template.yaml](D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/templates/eval-manifest.template.yaml)

### 4.1 必改项

#### 目标项目路径

```yaml
experiment:
  target_project:
    repo_path: D:/your/target/project
```

#### 目标项目调用方式

推荐默认值：

```yaml
invocation:
  mode: claude-agent-sdk-python
```

如果 SDK 临时不稳定，保留 fallback：

```yaml
fallback_invocation:
  mode: openai-compatible-chat
```

#### 数据集路径

如果你已经有标准 JSONL：

```yaml
dataset:
  source:
    kind: jsonl
    path: ./datasets/your-cases.jsonl
  normalize_to: ./datasets/your-cases.jsonl
```

如果你起点是 xlsx：

- 先跑 [normalize_xlsx_to_jsonl.py](D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/harness/normalize_xlsx_to_jsonl.py)

#### 选哪个 profile

推荐映射：

- 越权、未授权、身份冒用、跨租户：`authz-and-identity`
- SQLi、RCE、SSRF、文件类：`traditional-sink-driven`
- 红包、余额、支付、退款、订单资金逻辑：`business-logic-and-funds`
- 还没定场景，只想先跑通：`generic-vuln-audit`
- 组合链路验证：`composite-mixed-risk`

示例：

```yaml
experiment:
  profile: authz-and-identity
```

#### 哪些目录允许自动修改

只允许改 prompts / skills / orchestrator：

```yaml
editable_scope:
  - prompts/
  - skills/
  - configs/
  - orchestrator/
  - agents/
```

允许改整个目标项目：

```yaml
editable_scope:
  - ./
```

### 4.2 重要默认值

如果你不额外配置，现在默认会按这些策略跑：

- `experiment.profile`
  - 默认：`generic-vuln-audit`
- `target_project.invocation.mode`
  - 默认：`claude-agent-sdk-python`
- `execution.resume_completed_cases`
  - 默认：`true`
- `execution.candidate_evaluation.strategy`
  - 默认：`staged`
- `execution.case_retry.max_attempts`
  - 默认：`2`
- `execution.case_retry.backoff_seconds`
  - 默认：`2`
- `execution.packet.max_primary_change_count`
  - 默认：`1`
- `optimization_policy.methodology_first`
  - 默认：`true`
- `optimization_policy.minimum_necessary_change`
  - 默认：`true`

`staged` 的意思是：

1. 先跑 `dev`
2. `dev` 通过门禁后，再跑 `holdout / cross_repo / canary`
3. 只有全部门禁过了才 keep

## 5. 不同场景怎么配

### 5.1 你现在做越权审计

推荐：

- `profile: authz-and-identity`
- `invocation.mode: claude-agent-sdk-python`
- `execution.candidate_evaluation.strategy: staged`
- `editable_scope` 先小范围，再逐步放大

### 5.2 做传统漏洞

只要改：

- `profile: traditional-sink-driven`

其他主架构不用改。

### 5.3 做业务资金漏洞

推荐：

- `profile: business-logic-and-funds`

并尽量在 case 里补：

- `notes`
- `expected.business_invariant`
- `expected.actor_model`

## 6. 结果看哪里

一次 run 的核心产物都在：

```text
autoresearch-results/runs/<run_id>/
```

平时最常看这几个：

- `run-state.json`
  当前状态、当前 candidate、下一步动作
- `scoreboard.json`
  baseline / best / current 指标
- `decisions/<candidate>.decision.json`
  某个 candidate 为什么 keep / discard
- `packets/<packet_id>/packet.json`
  这一轮想改什么方法论点
- `packets/<packet_id>/apply-result.json`
  实际改了哪些文件
- `lesson-ledger.md`
  每轮沉淀的方法级经验

## 7. 当前推荐工作流

1. 复制模板 manifest
2. 改 `repo_path`
3. 改 `dataset.source.path`
4. 改 `profile`
5. 改 `editable_scope`
6. 先跑一次 `main.py smoke`
7. 再跑 `main.py auto`

## 8. 当前版本边界

现在已经稳定可用的是：

- 调目标项目
- canonicalize rich output
- grading
- baseline / candidate keep-discard
- candidate workspace
- 自动提 packet
- 自动改目标项目
- 自动 lesson 回灌

现在还不应该误解成：

- 自带高质量真实 benchmark
- 已经保证 packet 提案一定最优
- 可以完全替代人工复审
