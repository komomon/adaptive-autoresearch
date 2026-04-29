# Adaptive Autoresearch

## 结论

这是一个面向“基于大模型的漏洞审计项目”的自动评测与自动优化平台。

它的职责不是直接替代你的漏洞审计项目，而是：

1. 调你的目标项目跑评测集
2. 把 rich output 对齐成统一评分格式
3. 计算版本级指标
4. 自动提出最小必要的方法论修改
5. 生成新 candidate 并继续回归

快速上手直接看：

- [QUICKSTART.md](D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/QUICKSTART.md)

## 当前推荐入口

统一入口：

- [harness/main.py](D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/harness/main.py)

推荐命令：

```powershell
py -3.14 D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\harness\main.py auto `
  --manifest D:\ccode\aicode\aicode002-claudecode\autoresearch\adaptive-autoresearch\examples\authscan-benchmarkjava-sdk-smoke.eval-manifest.yaml `
  --rounds 1
```

## 这套项目解决什么问题

适用目标：

- 单 skill 漏洞审计项目
- 单 agent 漏洞审计项目
- 多 skill 项目
- agent team 项目

适用漏洞范围：

- 传统漏洞
- 越权、未授权、身份冒用、跨租户
- 业务逻辑漏洞
- 资金与红包等业务安全漏洞

## 当前主路径

模型调用路径现在只保留：

- `claude-agent-sdk-python`
- `openai-compatible-chat`

说明：

- `claude-agent-sdk-python`
  是主路径，适合直接运行本地 skill / agent-team 项目
- `openai-compatible-chat`
  只是普通模型调用，不是 agent session
  主要用于 fallback、canonicalization 和 probe

## 主要目录

```text
adaptive-autoresearch/
|-- README.md
|-- QUICKSTART.md
|-- bugs.md
|-- docs/
|-- profiles/
|-- schemas/
|-- templates/
`-- harness/
```

## 关键文档

- 架构：
  [architecture.md](D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/docs/architecture.md)
- 目标项目接入契约：
  [target-project-contract.md](D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/docs/target-project-contract.md)
- 评分规则：
  [grading.md](D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/docs/grading.md)
- 反过拟合约束：
  [anti-overfit.md](D:/ccode/aicode/aicode002-claudecode/autoresearch/adaptive-autoresearch/docs/anti-overfit.md)

## 当前状态

已经稳定可用：

- 调目标项目
- rich output canonicalization
- grading
- baseline / candidate keep-discard
- candidate workspace
- 自动提 packet
- 自动改目标项目
- lesson ledger 回灌

当前仍需真实数据集继续优化的部分：

- 真实 benchmark 覆盖度
- packet 提案质量
- 失败 case 聚类与 lesson 回灌强度
