# Architecture

## 结论

最终架构固定为 5 层：

1. `core`
2. `harness`
3. `profiles`
4. `adapter-codex`
5. `adapter-claudecode`

其中 `core` 和 `harness` 是公共底座，`profiles` 负责漏洞方法论，`adapters` 负责运行时适配。

## 总体结构

```text
Eval Manifest
    |
    v
Harness
    |
    +--> Dataset Normalizer
    +--> Repo/Branch Materializer
    +--> Audit Runner
    +--> Artifact Collector
    +--> Grader
    +--> Lesson Writer
    |
    v
Core Runtime
    |
    +--> Session / State
    +--> Packet / Checkpoint
    +--> Keep / Discard Controller
    +--> Scoreboard
    +--> Meta Optimization Boundary
    |
    +--> Profile
    |      +--> Generic Vuln Audit
    |      +--> Authz And Identity
    |      +--> Traditional Sink Driven
    |      +--> Business Logic And Funds
    |      +--> Composite Mixed Risk
    |
    +--> Adapter
           +--> Codex
           +--> Claude Code
```

## 5 层说明

### 1. core

`core` 只做稳定、可复用、与漏洞类型无关的事情：

- session / state / results / lessons / checkpoint
- keep / discard / crash / refine / pivot / blocked 语义
- packet 执行边界
- artifact / grading / run-state 的统一 schema
- 外层元优化的边界控制

`core` 不应内置任何“某类漏洞长什么样”的规则。

### 2. harness

`harness` 是整个项目的一等公民，负责把“项目自优化”变成可测、可复现、可回滚的实验。

职责固定为：

1. 读取 xlsx 并规范化为统一 case
2. 拉取指定 repo + branch
3. 建立只读评测 workspace
4. 调用目标 agent system 审计
5. 收集中间 artifacts
6. 对照人工标签评分
7. 输出 case/run 级结果
8. 回写只允许方法级经验的 lessons

### 3. profiles

`profiles` 定义的是领域方法论，而不是规则库。

它们负责：

- 角色拓扑
- 分析原语
- 证据契约
- grader 维度
- 何时切换单 agent / compact team / full team / dual verification

### 4. adapter-codex

Codex 侧的主参考是 `codex-autoresearch2`：

- launch/runtime/state/context/lessons 分层
- foreground / background / resume
- helper authoritative state
- parallel batch contract

选择性吸收 `codex-autoresearch`：

- dashboard
- MCP tool contract
- quality-gap loop
- finalize 体验

### 5. adapter-claudecode

Claude Code 侧的主参考是 `AGR`：

- fresh context per iteration
- metric/guard separation
- variance-aware acceptance
- exhausted approaches
- supervisor pattern

它必须和 Codex 侧共用同一份 artifact 和 grading 契约。

## 多漏洞统一抽象模型

为了避免后续新增漏洞类型时改动 `core`，统一使用下面这组原语：

- `EntryPoint`
- `Actor`
- `TrustAnchor`
- `Selector`
- `SensitiveAction`
- `Guard`
- `StateTransition`
- `Evidence`
- `Verdict`

对于业务与资金类，再额外扩展：

- `BusinessInvariant`
- `MonetaryConstraint`
- `QuotaConstraint`
- `ActorSeparation`

新增漏洞类型时，只扩展 profile 与 grading，不改 core。

## 拓扑分级

### S0 单 agent

适合短路径、单文件、小 case。

### S1 compact team

默认是：

- `scope`
- `path`
- `judge`

适合传统 sink 型短链漏洞。

### S2 full audit team

默认角色：

- `planner`
- `entrypoint-scout`
- `context-mapper`
- `call-chain-explorer`
- `forward-analyzer`
- `backward-analyzer`
- `guard-analyzer`
- `evidence-agent`
- `judge-agent`
- `reporter-agent`

### S3 domain-augmented team

在 S2 基础上按 profile 注入专门 lane：

- 传统漏洞：`sink-interest-agent`
- 访问控制：`auth-context-agent`、`input-auth-relation-agent`、`output-auth-relation-agent`
- 业务资金：`state-machine-agent`、`invariant-agent`、`funds-risk-agent`
- 高歧义 case：双 `verifier`

## 拓扑切换依据

固定按以下维度决定，不允许写死成“某类漏洞只能某种 team”：

- 调用链长度
- 分支数
- transport 类型
- 是否跨服务 / 跨仓库
- 是否涉及状态机 / 金额 / 审批
- 当前模型上下文预算
- 当前 profile 的历史失败模式

## 上下文预算原则

1. 不把整仓一次性塞进上下文。
2. 每个阶段只消费“可直接用于下一步”的证据包。
3. 摘要只能做索引，不能替代关键代码片段。
4. 超预算优先拆 packet，不优先压缩事实。
