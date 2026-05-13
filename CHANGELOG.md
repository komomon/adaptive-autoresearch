# Changelog & Bug Log

## Bug 修复记录

### BUG-001: apply 阶段超时 300s 而非 3600s

**发现时间**: 2026-05-13
**严重程度**: 严重
**文件**: `harness/apply_packet.py`, `harness/propose_packet.py`

**现象**: apply 阶段在 300s 超时退出，但 YAML 配置的是 3600s。

**根因**: `default_apply_config()` 使用 `{**opt_base}` 构建配置，而 `optimization.model` 只有 3 个字段（model/api_key_env/base_url），导致 invocation 中的 `timeout_seconds`、`thinking`、`effort` 等执行参数全部丢失。`setdefault("timeout_seconds", 3600)` 本应兜底，但实际代码写的是 `setdefault("timeout_seconds", 300)`。

**修复**: 合并顺序改为 `{**invocation, **opt_base, **explicit}` — 先继承 invocation 全部参数，再用 optimization.model 覆盖连接信息，最后用阶段显式配置覆盖。同时 `setdefault` 统一为 3600。

**代码**:
```python
# 修复前 (BUG)
cfg = dict(opt_base)  # 只有 model/key/url，丢失 timeout/thinking/effort

# 修复后
cfg = {**invocation, **opt_base, **explicit}
```

---

### BUG-002: propose 单次调用塞入所有 failure case 导致超时

**发现时间**: 2026-05-13
**严重程度**: 严重
**文件**: `harness/propose_packet.py`

**现象**: 当 failure case 数量多（20+）时，单次 LLM prompt 过大，120s 超时不够用，导致整个 propose 阶段崩溃。

**修复**: 改为两阶段分批分析：
- Phase A: 每批 2 个 case 分别分析，收集 observations
- Phase B: 汇总所有 batch observations 合成一个 proposal

单批失败只 warning 跳过，全部失败才报错。

---

### BUG-003: round 级无 try/except，一次失败整个流程终止

**发现时间**: 2026-05-13
**严重程度**: 高
**文件**: `harness/run_autoresearch.py`

**现象**: round 循环没有异常捕获，round 1 的任何错误直接导致进程退出。

**修复**: round 级 try/except + 重试（默认 2 次）。重试用尽后 continue 到下一个 round，不中断整个流程。

---

### BUG-004: template.yaml 有两个重复的 optimization: 键

**发现时间**: 2026-05-13
**严重程度**: 中
**文件**: `templates/eval-manifest.template.yaml`

**现象**: YAML 中有两个顶级 `optimization:` 块，后者覆盖前者，导致 `optimization.model` 配置丢失。

**修复**: 合并为一个 `optimization:` 块，包含 `model`、`proposal`、`apply` 三个子节。

---

## 新功能记录

### FEAT-001: SDK 心跳状态追踪 (sdk_status)

**时间**: 2026-05-13
**文件**: `harness/model_backends.py`

**功能**: SDK 调用期间心跳日志从简单计时升级为显示实时 SDK 状态：
- `waiting for first response (model thinking or API queued)` — 等待首次响应
- `turns=N | last_tool=Read(file.py) (30s ago)` — 显示轮次和最近工具调用

**实现**: `_heartbeat_loop` 和 `_stream_query` 共享 `sdk_status` dict，实时更新状态。

---

### FEAT-002: 超时自动延长 (max_timeout_extensions)

**时间**: 2026-05-13
**文件**: `harness/model_backends.py`

**功能**: SDK 调用超时时自动延长，而非直接失败。默认延长 1 次。

**配置**: YAML 中 `max_timeout_extensions: 1`，invocation/canonicalization/optimization 均可配置。

---

### FEAT-003: 优化模型与目标项目模型分离

**时间**: 2026-05-13
**文件**: `harness/apply_packet.py`, `harness/propose_packet.py`, 所有 YAML

**功能**: propose/apply 阶段可使用独立的模型、API key 和 endpoint。

**配置**:
```yaml
optimization:
  model:                    # 共享基础
    model: glm-5.1
    api_key_env: OPTIMIZATION_AUTH_TOKEN
    base_url: https://openai.mybank.cn/api/anthropic
```

**合并优先级**: `invocation → optimization.model → proposal/apply`

---

### FEAT-004: canonicalizer 工具和权限增强

**时间**: 2026-05-13
**文件**: `harness/run_packet.py`, `harness/canonicalize_target_output.py`

**功能**: canonicalizer 默认获得全部文件工具（Read/Glob/Grep/Bash/Edit/MultiEdit/Write）和 acceptEdits 权限，可自主读取目标项目输出的文件。

---

### FEAT-005: propose 分批分析

**时间**: 2026-05-13
**文件**: `harness/propose_packet.py`

**功能**: 见 BUG-002 修复。propose 阶段改为两阶段：分批分析 → 汇总合成。

---

### FEAT-006: advance_candidate 每步 try/except

**时间**: 2026-05-13
**文件**: `harness/advance_candidate.py`

**功能**: prepare/propose/apply/evaluate 4 个 stage 各自 try/except，失败时更新 supervisor 状态并 raise AdvanceStageError。

---

### FEAT-007: YAML 模型参数文档化

**时间**: 2026-05-13
**文件**: 所有 YAML 文件

**功能**: 所有 4 个模型配置区域（invocation/canonicalization/optimization.model/proposal/apply）补全全部可用参数注释，取消注释即可生效。

---

### FEAT-008: regrade 子命令 — 重评指定 candidate

**时间**: 2026-05-13
**文件**: `harness/main.py`, `harness/run_packet.py`

**功能**: 对指定 candidate 重新跑 eval 阶段（不重新 propose/apply），用于复盘和验证。

**用法**:
```bash
# 只重跑低质量 case（无 evidence + 无 artifacts）
python harness/main.py regrade \
  --manifest examples/authz-claudecode.eval-manifest2.yaml \
  --run-dir autoresearch-results/authz-claudecode/runs/<run-id> \
  --candidate-id candidate-0003 \
  --split dev

# 重跑全部 case
python harness/main.py regrade ... --split dev --all-cases

# 重跑所有 split
python harness/main.py regrade ... --split all

# 限制只跑前 N 个 case
python harness/main.py regrade ... --limit 5
```

**实现细节**:
- `regrade` 映射到 `run_packet.py`，自动检测 candidate workspace 作为 cwd
- `--split all` 自动扫描 `run_dir/splits/*.jsonl`，逐 split 调用
- regrade 完成后保护 `scoreboard["current"]` 和 `run_state["current"]` 不被覆盖
- 结果追加到 `candidate-ledger.jsonl`，scoreboard 更新对应 split 分数

---

### FEAT-009: rerun_low_quality_cases — 重跑低质量缓存 case

**时间**: 2026-05-13
**文件**: `harness/run_packet.py`, 所有 YAML

**功能**: 当设为 `true` 时，跳过缓存中 evidence 和 artifacts 全空的 case，强制重新执行。

**配置**:
```yaml
execution:
  rerun_low_quality_cases: false   # true 时重跑无证据的缓存 case
```

**regrade 默认行为**: 不加 `--all-cases` 时自动启用 `--rerun-low-quality`。

---

### FEAT-010: --force-rerun 强制忽略缓存

**时间**: 2026-05-13
**文件**: `harness/run_packet.py`, `harness/main.py`

**功能**: `--force-rerun` 标志跳过所有缓存，强制重新执行每个 case。`regrade --all-cases` 自动启用此标志。

---

### FEAT-011: regrade 自动使用 candidate workspace

**时间**: 2026-05-13
**文件**: `harness/run_packet.py`

**功能**: regrade 时自动检测 `run_dir/candidates/<id>/workspace/`，覆盖 invocation 的 `cwd` 为 candidate workspace，确保使用优化后的目标项目。

**回退行为**: 如果 workspace 不存在（如 baseline），使用 manifest 原始 `cwd`。

---

### BUG-005: --all-cases 实际不重跑所有 case

**发现时间**: 2026-05-13
**严重程度**: 高
**文件**: `harness/main.py`

**现象**: `regrade --all-cases` 不传 `--rerun-low-quality`，但 `reuse_completed_cases=True` 导致所有缓存被复用，实际不重跑任何 case。

**修复**: 新增 `--force-rerun` 标志（FEAT-010），`--all-cases` 改为传 `--force-rerun`。

---

### BUG-006: regrade 覆盖 scoreboard/run-state 的 current 指针

**发现时间**: 2026-05-13
**严重程度**: 高
**文件**: `harness/run_packet.py`

**现象**: regrade 非 current candidate 时，`update_scoreboard()` 和 `update_run_state()` 将 `current` 指针指向被 regrade 的 candidate，丢失原来 current 的分数和状态。

**修复**: regrade 前保存 `prev_scoreboard_current` 和 `prev_run_state_current`，regrade 后恢复。只更新对应 split 的分数，不移动 `current` 指针。

---

### BUG-007: canonicalizer 不提取 evidence（files/functions/locations）

**发现时间**: 2026-05-13
**严重程度**: 高
**文件**: `harness/canonicalize_target_output.py`

**现象**: canonicalizer prompt 没有明确要求提取 evidence 字段，导致 25/29 case 的 evidence 为空（得默认分 0.5）。

**修复**: 更新 DEFAULT_PROMPT，显式要求提取 `evidence.files`、`evidence.functions`、`evidence.locations`，并从目标项目原始输出文件中读取内容。

---

### BUG-008: propose 阈值过高导致几乎所有 case 被标记为失败

**发现时间**: 2026-05-13
**严重程度**: 中
**文件**: `harness/propose_packet.py`

**现象**: `needs_optimization` 使用 `evidence_adequacy < 1.0`，导致 evidence=0.5（dataset 无 location 标注的默认分）也被标记为失败，propose 分析过多 case。

**修复**: 降低阈值：`evidence_adequacy < 0.5`、`chain_completeness < 0.25`。

---

### BUG-009: apply 只检测 proposal 指定的文件变更

**发现时间**: 2026-05-13
**严重程度**: 中
**文件**: `harness/apply_packet.py`

**现象**: `apply_packet.py` 只检查 proposal `target_files` 列出的文件，LLM 修改其他文件时不会被检测到（`modified_files: []`）。

**修复**: 新增 `collect_all_file_digests()` 全 workspace 文件摘要对比，确保检测到所有变更。

---

### BUG-010: canonicalizer 子进程丢失 thinking/effort/max_timeout_extensions 参数

**发现时间**: 2026-05-13
**严重程度**: 中
**文件**: `harness/run_packet.py`, `harness/canonicalize_target_output.py`

**现象**: `run_packet.py` 调用 canonicalizer 子进程时，未转发 YAML 中的 `thinking.type`、`effort`、`max_timeout_extensions` 配置。

**修复**: 两处改动：
1. `canonicalize_target_output.py` 新增 `--max-timeout-extensions`、`--thinking-type`、`--effort` CLI 参数
2. `run_external_canonicalizer()` 从 `canonical_cfg` 读取这些参数并转发
