# Profiles

## 结论

profile 是这套系统的扩展点。新增漏洞类型时，优先扩 profile，而不是改 core。

## 默认 profiles

### `generic-vuln-audit`

母版 profile，负责：

- 统一入口发现
- 调用链扩展
- 证据包与 verdict 契约
- 基础 judge / verifier 流程

### `authz-and-identity`

覆盖：

- 越权
- IDOR
- BOLA / BFLA
- 未授权
- 身份冒用
- 跨租户
- 审批流授权

重点关注：

- identity binding
- resource binding
- output authorization
- delayed authorization
- stored identity re-validation

### `traditional-sink-driven`

覆盖：

- 注入
- 文件
- SSRF
- 反序列化
- 命令执行

核心模型：

`EntryPoint -> InfluencePath -> Sink -> Guard -> Verdict`

### `business-logic-and-funds`

覆盖：

- 红包
- 余额
- 支付
- 退款
- 优惠券
- 积分
- 审批
- 资格
- 限额 / 次数 / 并发

额外引入原语：

- `BusinessInvariant`
- `StateTransition`
- `MonetaryConstraint`
- `QuotaConstraint`
- `ActorSeparation`

### `composite-mixed-risk`

覆盖组合风险：

- 身份冒用 + 资金操作
- 越权读取 + 业务套利
- SSRF + 内部高权限接口

它主要用于 holdout / canary / cross-repo，而不是初始调优主战场。
