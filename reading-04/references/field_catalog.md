# 统一字段字典与可比性判据

本文件规定 `draft.json` 的字段口径：所有论文共用同一组 `field_id`；每格记录"值 + 单位 + 数据集 + 指标口径 + 逐字引文 + locator"。

## 1. 八个通用字段（workorder 未给字段时使用）

| field_id | 收什么 | 取值规则 | 常见单位 |
|---|---|---|---|
| task | 研究问题/目标 | 用原文句概括任务，不得改写结论 | — |
| dataset | 数据或语料来源、版本 | 编号/队列/语料名 + 版本；不同版本算不同值 | — |
| sample | 样本量及构成 | 取**最终分析**的 n，不取筛选前；人群/物种/细胞系另记 | participants / samples |
| material | 研究对象/基质 | 药品、染料、污染物、组织、菌株等，保留原文命名 | — |
| method | 方法及关键设置 | 方法名 + 剂量/时长/温度/仪器型号 | 随设置 |
| metric | 评价指标及口径 | 指标名 + 方向 + 计算口径（如 AUC vs accuracy） | 随指标 |
| unit | 数值单位 | 与 `value` 严格配套；换算值注明 "converted" | mg/L、µM、% |
| budget | 成本/资源约束 | 计算预算、样本成本、时间窗；workorder 要求时才填 | USD、GPU-h |

## 2. 填写硬规则

1. 一个 `field_id` 只承载一种口径；剂量与暴露时长不得混在同一字段。
2. 数值与单位分离：`value` 只放数字或原文短语，单位进 `unit`；范围写 "10–20"，脚本不代算均值。
3. 默认不做单位换算；确需换算时在 `note` 写 `converted from <原值>`。
4. 缺失写缺失：`status:"unreported"`、`value:null`、`note` 注明检索范围；**不得填 0**，不得把图上估读冒充正文值。
5. 不适用写 `status:"not_applicable"`（如综述没有原始样本量）；同义指标统一 `field_id`，在 `definition` 标同义范围。

## 3. 可比性六维（定量综合前逐维过闸）

判定顺序：`task` → `metric` → `units` → `material` → `pollutant` → `budget`。

| 判定 | 写法 | 后果 |
|---|---|---|
| 同条件可比 | `comparable: true` | 可数值合并/做差 |
| 任一维不同 | `comparable: false` + `basis`（哪维、原文依据、影响方向） | 数值保留但不入池，改分层叙述 |
| 维度未报告 | 视同不可比，`basis` 写"未报告，无法确认同条件" | 不入池 |

高频"看似可比、实则不可比"：同数据集不同版本；同指标不同口径（全样本 AUC vs 测试集 AUC）；单位不同且缺换算条件；剂量/时程不同；人群或物种不同。workorder 的 `forbidden_pooling` 是硬红线。

## 4. 冲突归因类别

| attribution | 触发条件 | 解释写法要点 |
|---|---|---|
| sample | 人群、物种或 n 不同 | 写明两组 n 与群体，说明效应量不可直接对照 |
| method | 剂量、时长、仪器不同 | 并列两组设置参数 |
| metric | 指标或计算口径不同 | 指出同名不同口径 |
| condition | 环境、基质、共变量不同 | 引用两篇的条件原句 |
| unresolved | 材料不足以归因 | 同时进 `pending_human`，不硬下结论 |

## 5. 引文与定位

引文从 `main.py show` 的输出逐字复制，1–2 句；locator 用 `p3#para7` 形式（内置 PDF 解析器兜底时为 `s2#para5`）。p 值、效应量、样本量等数字必须与引文原样一致。

## 6. 对齐审计记录（本包增量）

每个字段完成抽取后，在 `work/align_audit.md` 记一行：`field_id | 定义来源 | 涉及文档 | 判定为不可比的维度 | 依据`。用途：新论文加入时只补行列，不必重做字段定义；他人可按该记录复算对齐过程。

## 7. 字段拆分与合并的决策记录（增量）

跨领域复用时，通用 8 维往往不够细，需要拆字段；拆分本身要留痕，否则下一轮换人会填出两套口径。建议把每次变更写成三行：

- 变更：`material` 拆为 `material` 与 `substrate`（原值保留在 `material`，基底填 `substrate`）。
- 影响：D2、D3 需要补 `substrate`；`comparability` 的 `material` 维改按"催化剂+基底"联合判定。
- 回滚与兼容：旧工作稿若只填 `material`，`check` 会多出 `substrate` 空列（状态 `unreported`），不影响已有结论。

合并同理：两个论文里分别叫 `efficiency` 与 `removal_rate` 的指标，只有在 `definition` 明确写成同一个量的前提下才可并为一个 `field_id`；否则保持两列，在 `comparability` 里标 `metric` 不可比。记录这一条判断，比记录最终数字更重要。

最后提醒：字段字典的权威版本在包内只有这一份；SKILL.md 只描述规则，不重复枚举。二者冲突时以本文件的 `field_id` 与单位约定为准，并在 `changes` 里补一条修订记录。这样第三个人接手时不会在两种说法之间摇摆。
