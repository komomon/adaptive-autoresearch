# Runtime And Versioning

## 结论

当前这套项目的推荐入口不是“让大模型直接吃完整个 autoresearch 项目并自己循环”，而是：

- **Python harness 作为控制面入口**
- **大模型作为每个 case / 每个 packet 的执行单元**

也就是说，入口应当是脚本和状态机，模型是被调度的工作节点，不是整个系统唯一入口。

这样设计的原因很直接：

1. 评测集很多时，不能把全部 case 放进同一个上下文。
2. 每个 case 必须可复现、可回放、可单独追责。
3. 版本对比、keep/discard、holdout 门禁必须由外部控制面统一执行。

## 推荐入口

### 入口层

推荐用 Python 脚本作为统一入口，例如：

- `normalize_xlsx_to_jsonl.py`
- 后续应补：
  - `run_experiment.py`
  - `run_packet.py`
  - `grade_run.py`
  - `resume_run.py`

### 模型层

模型不直接管理全局实验状态，而是通过 adapter 被调用：

- Codex 走 `adapter-codex`
- Claude Code 走 `adapter-claudecode`

模型每次只接收：

- 当前 case 的最小必要证据包
- 当前版本的目标项目
- 当前 packet 的变更意图
- 当前 profile 的约束

## 为什么不是“大模型总入口”

如果把整个 autoresearch 当成一个超长会话，让大模型自己管：

- 很容易被评测集塞满上下文
- 不利于断点恢复
- 不利于严格比较两个版本
- 不利于保证每个 case 都真的跑过

所以正确结构是：

```text
Python Harness
  -> Packet Scheduler
  -> Case Runner
  -> Adapter
  -> Model
  -> Artifact Collector
  -> Grader
  -> Keep/Discard Controller
```

## case 是怎么跑的

推荐的执行单位不是“整批评测集一起喂给模型”，而是：

- 一个 `candidate version`
- 在一个数据集 split 上
- 按 case 逐条运行

但是版本是否保留，不是由单 case 决定，而是由该 `candidate version` 在一整个 split 上的聚合指标决定。

每条 case 都应该是独立执行、独立收集 artifact、独立评分。

这样即使是 agent + subagent 模式，也只是在单 case 内部展开，不会把所有 case 共享到一个上下文里。

## 当前版本区分粒度

版本不应只靠“聊天记忆”区分，而应至少有这几层标识：

- `run_id`
- `packet_id`
- `candidate_id`
- `profile`
- `adapter`
- `target_project_revision`
- `version_backend`

推荐语义：

- `run_id`：一次完整 autoresearch 实验
- `packet_id`：一次有限变更尝试
- `candidate_id`：packet 下的具体候选版本

## 修改策略：不是按单 case 立即定版

你问的核心点是：

> 如果某个 case 没审出来，是立刻改项目并继续测当前 case，还是修改后全部 case 再跑？

推荐答案是：

- **不能按单 case 通过就直接定版**
- **必须按 candidate version 在一个 split 上重新跑一组 case**

默认策略应该是：

1. 发现当前版本在某些 case 上失败
2. 归因出这轮 packet 想改的方法点
3. 生成一个 candidate version
4. 在 `dev` 子集上重新跑一轮
5. 计算该 candidate 在 `dev` 上的 `accuracy / precision / recall / f1`
6. 如果 dev 有提升，再跑 `holdout / cross_repo / canary`
7. 对每个 split 也计算 `accuracy / precision / recall / f1`
8. 全部门禁通过才 `keep`
9. 否则 `discard`

不能做成：

- 某个 case 过了就立即保留改动

因为那样会非常快地过拟合。

## 那单 case 的失败还有什么价值

单 case 很重要，但它的作用是：

- 提供失败归因
- 触发新 packet
- 提供 lesson 候选
- 验证某个特定 failure mode 是否被修复

而不是直接决定最终版本。

## 推荐的运行顺序

### 开发阶段

1. baseline 跑 `dev`
2. 找失败模式
3. 生成 packet
4. candidate 跑 `dev`
5. 计算 `accuracy / precision / recall / f1`

### 门禁阶段

只有 dev 提升后再跑：

1. `holdout`
2. `cross_repo`
3. `canary`
4. 计算各 split 指标与 evidence 指标

### 保留阶段

只有全部满足以下条件才 keep：

- dev 提升
- holdout 不下降
- cross-repo 不下降
- evidence adequacy 不下降
- 高置信度误报率不上升

## 版本控制推荐

### 第一层：实验账本

不管目标项目是不是 git 仓库，autoresearch 自己都必须有外部账本：

- run state
- packet ledger
- candidate ledger
- grading result
- lesson ledger
- scoreboard

这是必须的，不能只靠 git。

### 第二层：目标项目版本

如果目标项目是 git 仓库，推荐：

- 每个 candidate version 对应一个独立 worktree / branch / patch

如果目标项目不是 git 仓库，也至少要保留：

- 原始快照引用
- 变更 patch
- candidate 输出目录

## 是否必须依赖 git

不是必须，但**强烈建议**目标项目用 git 管版本。

原因是：

- 更容易回滚
- 更容易对比 candidate 差异
- 更容易结合 worktree 做隔离评测

如果没有 git，也能跑，但控制成本和风险都会更高。

## 推荐版本后端

推荐支持两个后端：

### `git`

适合目标项目本身就是本地 git 仓库的情况。

建议：

- baseline 基于当前 HEAD
- 每个 candidate 使用独立 branch / worktree / patch
- keep 后再更新最佳版本引用

### `local-dir`

适合目标项目暂时不是 git 仓库，或者只是想先做低门槛实验。

建议：

- 为每个 candidate 建立独立目录快照
- 记录源目录、快照目录、patch 目录
- 明确当前 best 目录引用

## 推荐的最终结论

对你这个场景，最合适的运行方式是：

- 以 **Python harness** 为系统入口
- 以 **adapter 调大模型** 为执行层
- 以 **candidate version + split replay** 为版本比较单位
- 以 **run/packet/candidate ledger + 可选 git worktree** 为版本控制手段

这比“单个大模型长会话驱动全局 autoresearch”稳定得多，也更不容易因为上下文打满而失真。
