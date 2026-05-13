# Adaptive Autoresearch

## 结论

这是一个面向"基于大模型的漏洞审计项目"的自动评测与自动优化平台。

它的职责不是直接替代你的漏洞审计项目，而是：

1. 调你的目标项目跑评测集
2. 把 rich output 对齐成统一评分格式
3. 计算版本级指标
4. 自动提出最小必要的方法论修改
5. 生成新 candidate 并继续回归

## 前置条件

- Python 3.14+
- 已安装依赖：`claude-agent-sdk`、`PyYAML`
- 设置环境变量 `ANTHROPIC_AUTH_TOKEN`（你的 API key）
- **Windows 额外要求**（macOS/Linux 不需要）：需安装 Git for Windows，并设置 `CLAUDE_CODE_GIT_BASH_PATH` 指向 `bash.exe`

## 快速启动

```powershell
$env:ANTHROPIC_AUTH_TOKEN="你的key"
$env:OPTIMIZATION_AUTH_TOKEN="优化阶段的key"   # 可与上面相同

py -3.14 harness/main.py auto `
  --manifest examples/authscan-benchmarkjava-smoke.eval-manifest.yaml `
  --rounds 1
```

## 主要目录

```text
adaptive-autoresearch/
|-- README.md
|-- CHANGELOG.md          # Bug 修复 + 新功能记录
|-- bugs.md               # 已知陷阱
|-- docs/
|-- templates/            # YAML 模板
|-- examples/             # 示例配置
`-- harness/              # 核心代码
```

---

## YAML 配置详解

整个系统通过一个 YAML manifest 驱动，分为 7 个顶级节：

### 1. experiment — 实验与目标项目

```yaml
experiment:
  name: my-experiment
  profile: authz-and-identity       # 漏洞类型 profile
  adapter: claudecode               # 适配器: claudecode | codex
```

#### target_project — 目标项目配置

```yaml
  target_project:
    kind: skill                     # skill | agent-team
    repo_path: ../your-project      # 目标项目路径
    editable_scope:                 # autoresearch 可修改的目录
      - prompts/
      - skills/
    read_only_scope:                # 禁止修改的目录
      - benchmarks/
```

#### invocation — 目标项目模型配置（第一个 LLM）

调目标项目分析 case 时使用的模型。

```yaml
    invocation:
      mode: claude-agent-sdk-python

      # ── 连接 ──
      model: glm-5.1               # 模型名（或用 model_env 指定环境变量名）
      api_key_env: ANTHROPIC_AUTH_TOKEN  # API key 环境变量名
      base_url: https://openai.mybank.cn/api/anthropic
      # temperature: 0.0            # 采样温度

      # ── 执行控制 ──
      max_turns: 12                 # 最大 agent 轮次
      timeout_seconds: 3600         # 总超时（秒）
      max_attempts: 2               # 失败重试次数
      retry_backoff_seconds: 2      # 重试间隔
      max_timeout_extensions: 1     # 超时自动延长次数

      # ── 思考模式 ──
      thinking:
        type: adaptive              # disabled | enabled | adaptive
      effort: high                  # low | medium | high

      # ── 工具与权限 ──
      allowed_tools:
        - Read
        - Glob
        - Grep
        - Bash
      permission_mode: acceptEdits  # default | acceptEdits | bypassPermissions

      # ── 可观测性 ──
      # heartbeat_interval: 60      # 心跳日志间隔（秒）
      # quiet: false                # 抑制 SDK 输出

      # ── 提示词 ──
      prompt_template: |
        分析 case: {case_json}
      system_prompt: |
        你的系统提示词
```

#### canonicalization — 规范化模型（第二个 LLM）

目标项目输出原始文本后，用第二个 LLM 将其规范化为标准 TargetAuditResult JSON。支持文件工具，可读取目标项目写入的结果文件。

```yaml
      canonicalization:
        enabled: true
        runner: script
        script: ./harness/canonicalize_target_output.py
        mode: claude-agent-sdk-python

        # 连接（不设置则继承 invocation）
        model: glm-5.1
        api_key_env: ANTHROPIC_AUTH_TOKEN
        base_url: https://openai.mybank.cn/api/anthropic
        cwd: ../your-project

        # 执行控制
        timeout_seconds: 120         # 规范化超时
        # max_turns: 8
        # max_timeout_extensions: 1

        # 工具（默认: 全部文件工具 + acceptEdits）
        # allowed_tools: [Read, Glob, Grep, Bash, Edit, MultiEdit, Write]
        # permission_mode: acceptEdits
```

---

### 2. dataset — 数据集

```yaml
dataset:
  source:
    kind: jsonl                     # jsonl | xlsx
    path: ./datasets/cases.jsonl
    # sheet: cases                  # xlsx 时需要
  normalize_to: ./datasets/normalized.jsonl
  column_mapping:
    case_id: case_id
    expected.has_vulnerability: has_vulnerability
    # ... 更多字段映射
  case_filter:
    # range: [1, 10]               # 选用第 1-10 条（1-based，含）
    # indices: [1, 3, 5]           # 选用指定编号
    # case_ids: ["row-00001"]      # 选用指定 case_id
  split:
    dev: 0.50                       # 开发集 50%
    holdout: 0.25                   # 验证集 25%
    cross_repo: 0.15                # 跨仓集 15%
    canary: 0.10                    # 金丝雀集 10%
```

---

### 3. execution — 执行控制

```yaml
execution:
  modes:
    - foreground
    - background
    - resume
  resume_completed_cases: true      # 断点续跑跳过已完成 case
  rerun_low_quality_cases: false    # true 时重跑无 evidence/artifacts 的缓存 case
  case_concurrency: 3               # 并发 case 数
  case_retry:
    max_attempts: 2                 # case 级重试
    backoff_seconds: 2
  packet:
    max_primary_change_count: 1     # 每轮最多几个方法论变更
    max_dev_cases_per_round: 12     # 每轮最多分析多少 dev case
  topology:
    default: S1                     # 默认拓扑
    escalation_order:               # 升级顺序
      - S1
      - S2
      - S3
```

---

### 4. grading — 评分

grading 不调用 LLM，是纯统计计算。

```yaml
grading:
  primary_metric: verdict_match
  match_rules:
    require_verdict_match: true               # 结论必须匹配
    require_type_match_when_available: true   # 漏洞类型匹配（有标注时）
    require_evidence_for_high_confidence: true # 高置信度必须有证据
  aggregate_metrics:
    - accuracy
    - precision
    - recall
    - f1
  secondary_metrics:
    - evidence_adequacy          # 证据充分性
    - chain_completeness         # 调用链完整性
    - confidence_calibration     # 置信度校准
    - false_positive_control     # 误报控制
    - false_negative_control     # 漏报控制
  keep_gate:
    require_dev_improvement: true               # dev 集必须提升
    require_holdout_non_regression: true        # holdout 不能退步
    require_cross_repo_non_regression: true     # 跨仓不能退步
    require_evidence_non_regression: true       # 证据不能退步
    require_high_confidence_fp_non_regression: true  # 高置信误报不能退步
```

---

### 5. optimization — 优化模型配置（第三个 LLM）

propose 和 apply 阶段使用的模型，可与目标项目模型完全独立。

**合并优先级**: `invocation → optimization.model → proposal/apply 阶段配置`

```yaml
optimization:
  model:                             # propose & apply 共享基础
    model: glm-5.1
    api_key_env: OPTIMIZATION_AUTH_TOKEN
    base_url: https://openai.mybank.cn/api/anthropic
    # timeout_seconds: 3600
    # max_timeout_extensions: 1
    # thinking: {type: adaptive}
    # effort: high

  # propose 阶段: 分析失败 case → 生成方法论改进 proposal
  # 继承: invocation → optimization.model → 此块
  # proposal:
  #   permission_mode: default      # 只读分析
  #   max_turns: 8
  #   timeout_seconds: 3600

  # apply 阶段: 按 proposal 修改目标项目文件
  # 继承: invocation → optimization.model → 此块
  # apply:
  #   permission_mode: acceptEdits  # 需要写权限
  #   allowed_tools: [Read, Glob, Grep, Edit, MultiEdit, Write]
  #   max_turns: 18
  #   timeout_seconds: 3600
```

---

### 6. meta_optimization — 元优化边界

```yaml
meta_optimization:
  enabled: true
  optimize_axes:                     # 允许优化的维度
    - role_split
    - dispatch_strategy
    - evidence_schema
    # ...
  never_optimize:                    # 禁止优化的维度
    - expected_labels
    - holdout_membership
    - grading_rubric_meaning
    # ...
```

---

### 7. outputs — 输出配置

```yaml
outputs:
  run_root: ./autoresearch-results
  ledgers:
    - run-state.json
    - scoreboard.json
    - candidate-ledger.jsonl
    - lesson-ledger.md
```

---

## 系统流程

```text
YAML manifest
    │
    ▼
main.py auto --manifest ... --rounds N
    │
    ▼
┌─ Round 循环（每轮） ─────────────────────────┐
│                                                │
│  1. advance_candidate.py                       │
│     ├─ prepare: 准备 candidate workspace       │
│     ├─ propose:  分析失败 case → 生成 packet   │
│     ├─ apply:    将 packet 应用到 workspace    │
│     └─ evaluate: 跑评测 → 评分 → keep/discard  │
│                                                │
│  2. evaluate 内部:                              │
│     ├─ run_packet.py (逐 case)                 │
│     │   ├─ 调用目标项目 LLM (invocation 模型)   │
│     │   ├─ 规范化输出 (canonicalization 模型)   │
│     │   └─ 评分 (grade_run.py, 纯统计)         │
│     └─ run_candidate.py (keep_gate 判定)       │
│                                                │
└────────────────────────────────────────────────┘
```

### 5 个 LLM 调用点

| 阶段 | 模型来源 | 用途 |
|------|---------|------|
| 目标项目分析 | `invocation` 配置 | 分析代码、产出审计结果 |
| 规范化 | `canonicalization` 配置（缺省继承 invocation） | 将原始输出转为标准 JSON |
| propose 分批分析 | `optimization.model` 配置 | 分析每批失败 case 的根因 |
| propose 合成 | `optimization.model` 配置 | 汇总 observations 生成 proposal |
| apply 执行 | `optimization.model` 配置 | 按 proposal 编辑目标项目文件 |

每个 LLM 调用点都可以独立配置不同的模型、API key 和 endpoint。

---

## 优化阶段 LLM 提示词详解

优化阶段分 propose 和 apply 两步，共使用 3 个 prompt，全部通过 `claude_agent_sdk_query()` 直接传入（无 system_prompt）。

### 1. propose Phase A — 分批分析 (`render_batch_analysis_prompt`)

每批 2 个 failure case，让 LLM 分析失败原因。

**输入**: 该批次的 failure case 详情（case_id、verdict 是否匹配、期望值/实际值、证据充分性、chain 完整性、entry 信息、notes 等）

**提示词核心**:

```
You are analyzing a small batch of N failing case(s) from a vulnerability-audit project.
This is batch X of Y. Focus only on these cases.

For each case, identify:
- What went wrong (verdict mismatch, missing evidence, etc.)
- The suspected root cause pattern
- Whether this looks like a systematic methodology gap
```

**输出 JSON**:

```json
{
  "observations": ["observation 1", "observation 2"],
  "common_patterns": ["pattern shared across cases in this batch"],
  "suspected_root_cause": "one-sentence root cause hypothesis"
}
```

### 2. propose Phase B — 合成 proposal (`render_synthesis_prompt`)

汇总所有 batch 的 observations，生成一个方法论改进 packet。

**输入**: 所有 batch 的 observations + 可编辑文件列表 + optimization_policy + 失败 case IDs

**提示词核心**:

```
You are proposing exactly one methodology-first optimization packet for a target vulnerability-audit project.

Hard constraints:
1. Propose exactly one primary methodology change.
2. Minimum necessary change only. No broad rewrites.
3. Do not solve the benchmark by memorizing case patterns.
4. Do not add vulnerability keyword rules or field-name shortcuts.
5. Prefer changes to skill instructions, methodology docs, dispatch strategy,
   evidence schema, or verifier behavior.
6. Output exactly one JSON object.
```

**输出 JSON**:

```json
{
  "packet_id": "...",
  "source_candidate_id": "...",
  "primary_axis": "...",
  "summary": "...",
  "failure_hypothesis": "...",
  "why_this_should_generalize": "...",
  "target_files": [{"path": "...", "reason": "..."}],
  "edit_instructions": [{"file": "...", "instruction": "..."}],
  "validation_expectation": {
    "should_improve": ["..."],
    "must_not_regress": ["..."]
  }
}
```

### 3. apply — 执行编辑 (`render_prompt`)

把 proposal packet 喂给 LLM，让它实际编辑目标项目文件。

**输入**: 完整的 packet JSON（包含 target_files 和 edit_instructions）

**提示词核心**:

```
You are applying exactly one methodology-first optimization packet to the target audit project.

Hard constraints:
1. Follow the packet exactly.
2. Make only the minimum necessary edits.
3. Edit only the files listed in target_files unless a tiny adjacent change is strictly required.
4. Do not add benchmark-specific keyword rules, field-name shortcuts, or dataset memorization.
5. Preserve the target project's existing style unless the packet explicitly says otherwise.
6. After finishing, output a short JSON object summarizing the work.
```

**输出 JSON**:

```json
{
  "packet_id": "...",
  "status": "applied",
  "summary": "...",
  "modified_files": ["..."]
}
```

---

## 命令参考

| 命令 | 用途 |
|------|------|
| `main.py smoke` | 跑一个 smoke case 验证目标项目链路 |
| `main.py init` | 初始化 run 目录、切分 dataset |
| `main.py eval` | 评测一个已有 candidate |
| `main.py advance` | 推进一步：propose → apply → eval |
| `main.py auto` | 自动循环 N 轮 advance |
| `main.py regrade` | 重评指定 candidate（不重新 propose/apply） |

### regrade 命令详解

`regrade` 用于对已有 candidate 重新跑 eval 阶段，不触发 propose/apply。适合复盘、验证分数、补跑未跑的 split。

```bash
# 重跑低质量 case（默认行为）
python harness/main.py regrade \
  --manifest examples/authz-claudecode.eval-manifest2.yaml \
  --run-dir autoresearch-results/authz-claudecode/runs/<run-id> \
  --candidate-id candidate-0003 \
  --split dev

# 重跑全部 case（忽略缓存）
python harness/main.py regrade ... --split dev --all-cases

# 重跑所有 split
python harness/main.py regrade ... --split all

# 只跑前 N 个 case
python harness/main.py regrade ... --limit 5
```

**参数说明**:

| 参数 | 必填 | 说明 |
|------|------|------|
| `--manifest` | 是 | YAML manifest 路径 |
| `--run-dir` | 是 | run 目录路径 |
| `--candidate-id` | 是 | 要重评的 candidate ID |
| `--split` | 否 | `dev`(默认) / `holdout` / `cross_repo` / `canary` / `all` |
| `--all-cases` | 否 | 强制重跑所有 case，忽略缓存 |
| `--limit` | 否 | 限制最多跑 N 个 case |

**行为说明**:
- 自动使用 candidate 的优化 workspace 作为 cwd
- 不加 `--all-cases`：只重跑 evidence 和 artifacts 全空的缓存 case
- 加 `--all-cases`：强制重跑所有 case（`--force-rerun`）
- `--split all`：依次跑所有 split（dev → holdout → cross_repo → canary）
- regrade 完成后，scoreboard 和 run-state 的 `current` 指针不被移动
- 结果追加到 `candidate-ledger.jsonl`

---

## 关键文档

- [CHANGELOG.md](CHANGELOG.md) — Bug 修复 + 新功能记录
- [bugs.md](bugs.md) — 已知陷阱
- [docs/architecture.md](docs/architecture.md) — 架构
- [docs/experiment-loop.md](docs/experiment-loop.md) — 实验循环
- [docs/grading.md](docs/grading.md) — 评分规则
- [docs/anti-overfit.md](docs/anti-overfit.md) — 反过拟合约束
- [docs/target-project-contract.md](docs/target-project-contract.md) — 目标项目接入契约
