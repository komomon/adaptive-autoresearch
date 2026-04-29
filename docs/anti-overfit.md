# Anti-Overfit

## 结论

这套 autoresearch 的第一原则不是“把分数刷高”，而是“在不破坏泛化和证据质量的前提下，让方法更稳”。任何靠规则捷径换来的提升，都必须被系统性拦截。

## 系统级硬约束

以下内容禁止被外层优化修改：

- 不能把关键词、字段名、注解名、SDK 名称学成漏洞规则
- 不能把某仓库编码风格学成 profile 规则
- 不能把人工标签泄漏进提示词
- 不能为了刷分放宽 evidence 要求
- 不能修改 grader 语义、holdout 划分、标签解释
- 不能用“常见有洞模式”代替代码证据

## 允许自动学习的内容

只允许进入 lessons 或 outer-loop 搜索空间的方法级经验包括：

- 搜索顺序
- 角色切换时机
- checkpoint 粒度
- 证据包压缩方式
- verifier 强度
- lesson 合并方式
- taboo / exhausted approach 管理

## 评测集切分建议

至少保留四层：

- `dev`
- `holdout`
- `cross_repo`
- `canary`

`canary` 应重点覆盖：

- 后置鉴权
- 参数覆盖
- 审批流授权
- 父类/接口/抽象类中的授权逻辑
- 冗余纵深防御
- 文件/下载/RPC/SSRF 等非 SQL 授权面
- 业务资金状态机与资格约束

## keep gate

只有同时满足以下条件才允许 `keep`：

- dev 提升
- holdout 不下降
- cross-repo 不下降
- evidence adequacy 不下降
- 高置信度误报率不上升

否则一律 `discard`。

## 评分重点

主指标：

- `verdict_match`

次指标：

- `evidence_adequacy`
- `chain_completeness`
- `confidence_calibration`
- `false_positive_control`
- `false_negative_control`
- `business_invariant_coverage`（仅业务/资金类）

## 需要直接判负的模式

以下任一出现，都应直接进入失败归因或回滚：

- 高置信度结论缺少明确代码依据
- 只凭关键词或框架名下结论
- 关键调用链被截断却未声明
- dev 提升但 holdout 下降
- cross-repo 明显退化
- lessons 中出现“字段名等于语义”的硬编码捷径

## lessons 写入规则

lessons 只能写方法，不写答案。

可以写：

- 哪种 packet 组织更利于下一阶段消费
- 哪种 verifier 顺序更能压误报
- 哪类 case 应更早进入双向分析
- 哪类失败模式应加入 taboo 列表

不可以写：

- 某注解等于安全
- 某 SDK 等于授权锚点
- 某字段名就代表 owner / tenant / user
- 某类框架一定使用某种授权模式
