# 支持度四级规范

本规范约束 `scripts/audit_claims.py` 的定级结果，同时是人工复核与分歧仲裁的依据。
允许写入产物 `verdict` 字段的字面值只有四个；`needs_review`、`mostly_supported`、`likely_true`
这类自造档位一律视为非法产物。

## 1. 四档的含义与门槛

先看"能不能给"，再看"给哪一档"：

- `supported`
  - 可给条件：五类要素（对象、方向、数值、条件、范围）在原文**同一处**被明确写出，且没有相反表述。
  - 证据要求：逐字 quote，附段落或页码定位。
  - 不可给：只是主题一样；方向对但数字不一样；原文做的是别的样品。
- `partially_supported`
  - 可给条件：只对上一部分——方向成立但显著性、数值、条件、范围有缺项或对不上；或者别处存在方向相反的来源。
  - 证据要求：支持片段 + 逐项列出未对齐要素。
  - 不可给：只有个别关键词重合，核心表述对不上。
- `contradicted`
  - 可给条件：原文**明确写出**相反结论——方向相反或否定极性相反，并且对象与条件确实对齐。
  - 证据要求：相反片段，`role=counter`。
  - 不可给：原文只是没提；原文条件不同；原文没覆盖该论断但也没反驳。
- `insufficient_evidence`
  - 可给条件：只有同主题材料，或原文没有报告该要素，支持与否定都无法确认。
  - 证据要求：非空 `search_scope` + 最佳候选片段。
  - 不可给：把"原文没写"当成 `contradicted`。

**底线规则**：原文没有报告某件事，不等于实验推翻了它。换材料、换温区、外推到没做过的工况，
只能落 `insufficient_evidence`，并在 `uncertainties` 注明"原文未报告"；只有原文出现相反表述才允许 `contradicted`。

## 2. 定级的六步顺序

1. **候选检索**：子判断的内容词 + 数值/型号锚点（示例形态：`450°C`、`Ni/Al2O3`、`18%`）在全语料匹配，
   按覆盖度排序，保留前 6 个句子窗口。
2. **锚点门控**：子判断含数值或型号时，窗口至少要命中一个锚点；一个都没命中的窗口覆盖度乘 0.35，
   表示"同主题、不同样品/条件"，不能充当支持证据。
3. **反证判定**：检查最佳窗口的方向词（`提高/高于` 与 `降低/低于/缩短`）和否定极性。与论断相反即 `contradicted`。
4. **冲突并置**：其它 source/section 有方向相反、覆盖度可比、锚点一致的片段时，给 `partially_supported`，
   `conflict.both_sides` 并列两条定位，置信度降为 `low`。
5. **要素逐项对齐**：显著性、数值、全称限定、条件四项分别比对；任一项没对上就封顶 `partially_supported`，
   并写入 `limitations` 标签（见第 4 节）。
6. **按覆盖度定级**：≥ 0.72 且零未对齐 → `supported`；0.40–0.72 → `partially_supported`；
   低于 0.40 → `insufficient_evidence`。

## 3. 误判高发区

**高发区一：主题相同就判支持。** 论断与段落共享"焙烧温度 / 转化率 / 催化剂"等词，但段落比较的是另一组温度。
这类段落只能当背景。做法是锚点门控 + 比较对象核对；宁可判证据不足，也别判支持。
误支持（主题相关当支持）的代价高于漏检（真支持没识别出来）。

**高发区二：没证伪就判证伪。** 论断声称"该规律同样适用于 Co 基催化剂"，原文只研究了 Ni 基。
这是超出研究范围的推断，不是被实验否定：判 `insufficient_evidence`，`limitations` 记
`anchor_not_matched` 或 `scope_not_established`。

**高发区三：摘要、结果、讨论三处不一致。** 摘要写"提升 18%"，结果表写"约 16%"，讨论段却提到高温下活性下降。
数值不齐 → `partially_supported`；方向相反 → 冲突双方并列。只引摘要或只引讨论都不可接受。

## 4. limitations 标签表

标签 key 用英文且固定，方便统计和复跑。每个标签出现时都会把 verdict 压到对应上限：

- `significance_not_reported`：论断说了"显著"，但证据句里找不到任何显著性字样 → 上限 partially_supported。
- `quantity_not_reported`：论断带具体数值，证据句一个数字都没有 → 上限 partially_supported。
- `reported_value_differs`：证据句给了同类量但数值对不上（原文 16%，论断 18%）→ 上限 partially_supported。
- `scope_not_established`：论断含全称或唯一限定，证据句没有交代样本域 → 上限 partially_supported。
- `condition_not_matched`：论断条件（例如 450 °C 焙烧）没出现在证据句里 → 上限 partially_supported。
- `anchor_not_matched`：论断里的数值/型号锚点没有全部落在证据句 → 上限 partially_supported。
- `conflicting_sources`：存在方向相反的可比来源 → 保持 partially_supported 并输出冲突并列。

## 5. 四个保真字段

定级之前，必须先把下列四项从论断中抽出来并写进产物；人工复核时逐项对照原文确认：

1. `comparator`——比较对象，例如 `450 °C 焙烧 vs 350 °C 焙烧`。原文比较的是别的东西，就算没对齐。
2. `negation`——论断是否带否定（不、未、没有、并非、not、without）。极性相反且覆盖度高 → `contradicted`；
   极性不同但覆盖度一般 → 不能给 `supported`。
3. `significance`——论断是否声称统计显著。原文只给均值差、没做检验，不构成显著支持。
4. `conditions`——温度、时间、样品、剂量等限定。条件不同意味着两个不同问题，不能互相支持。

## 6. 冲突并置怎么写

冲突块是一个对象，形状如下（**示例数据**，非正式案例结果）：

- 必须有 `conflict: true`、`sub_id`、`qualified_verdict`，判定通常取 `partially_supported`；
- `both_sides` 固定长度 2：A 侧对应主判定证据，B 侧对应相反来源；
- 每侧四个字段：`side`、`source_id`、`location`、`quote`；`location` 里给 unit_id + section + page；
- `note` 写明"两处定位并列，不作折中；条件差异需人工确认"。

示例内容：A 侧 `catalyst-paper`，`location={unit_id:R2, section:Results, page:3}`，
`quote="CO 转化率由 62% 提升到 78%"`；B 侧同文件 `location={unit_id:D1, section:Discussion, page:6}`，
`quote="800 °C 焙烧后活性明显下降"`。

不允许：只留一方；把两个方向平均成"基本支持"；只写"存在争议"却不给定位。

## 7. 判定演算示例

假设原文结果段：`"350 °C 与 450 °C 焙烧的 Ni/Al2O3 催化剂中，450 °C 样品的 CO 转化率由 62% 提升到 78%（+16 个百分点，p = 0.02）。"`

| 待判论断 | 应给档位 | 原因 |
|---|---|---|
| "450 °C 焙烧使 CO 转化率显著提升 16 个百分点" | supported | 对象、方向、数值、显著性四项齐备 |
| "450 °C 焙烧使 CO 转化率提升 30 个百分点" | partially_supported | 方向成立，数值不符（reported_value_differs） |
| "该规律适用于 Co 基催化剂" | insufficient_evidence | 锚点缺失，属外推，不是证伪 |
| "450 °C 焙烧会降低 CO 转化率" | contradicted | 原文明确写提升，方向相反 |

（以上为示例数据，不是正式案例结果。）
