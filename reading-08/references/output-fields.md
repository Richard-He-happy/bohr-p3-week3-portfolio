# 字段字典：result.json 怎么读

## 一、顶层必备键

| 键 | 类型 | 语义 |
|---|---|---|
| `case_id` | 字符串或 null | 输入里的原值；输入没有就 null |
| `status` | 字符串 | 四选一：`ok` / `partial` / `insufficient_evidence` / `input_error` |
| `result` | 对象 | 主结果，见下节 |
| `claims` | 数组 | 可引用的关键结论，每条都带证据链 |
| `uncertainties` | 数组 | 未报告、冲突、需要人工确认的条目 |
| `uncertainty` | 数组 | 与 `uncertainties` 同值（题面里用的是单数写法） |
| `sources` | 数组 | 每个输入文件一条登记 |
| `pending_human` | 数组 | 需要人工接管的点 |
| `errors` | 数组 | 异常记录，元素含 stage/message |
| `degradations` | 数组 | 降级动作与影响 |
| `changes` | 数组 | 本次运行写出了哪些产物 |
| `runtime` | 对象 | skill 名、版本、Python 版本、耗时、输入输出目录 |
| `output_contract_echo` | 对象 | 契约字段到落点的映射 |
| `contract_fields_missing` | 数组 | 契约缺项，正常必须为空 |

契约回填：输入里 `output_contract`（或 `output_spec`、`contract`）的每个键都要以原键名出现在顶层。`result` 里同名的子结构直接镜像过去；其余键按声明类型补空（数组补 `[]`，对象补 `{}`，其他补 `null`）。

## 二、`result` 内部

| 子键 | 一条记录里的主要字段 | 说明 |
|---|---|---|
| `formulas` | `formula_id`、`source_id`、`eq_number`、`mathml_raw_path`、`latex`、`latex_source`、`parse_confidence`、`structure`、`symbols`、`operators`、`flags`、`status` | `structure` 是五个计数（分式/上下标/根式/矩阵/分段）；`status` 仅 ok 或 needs_review |
| `variables` | `symbol`、`latex`、`plain`、`definition`、`unit`、`value_range`、`definition_source`、`locator`、`quote`、`source_id`、`formula_ids`、`confidence`、`inferred`、`value` | `definition` 允许为 null；`unit` 缺失写空串 |
| `derivations` | `step_id`、`from`、`to`、`rule`、`statement`、`assumptions`、`approximations`、`boundary_conditions`、`depends_on`、`quote`、`locator`、`source_id`、`verified`、`status` | 句子级线索，`verified` 恒为 false，`status` 恒为 textual_only |
| `numeric_checks` | `formula_id`、`substituted`、`computed`、`unit_check`、`order_of_magnitude_check`、`expected_range`、`missing_symbols`、`is_example`、`note`、`status` | 见第三节状态 |
| `indicator_checks` | `value`、`unit`、`quote`、`locator`、`source_id`、`checked` | 材料里字面写出的数值，`checked` 恒为 reported_as_written |
| `coverage` | `formulas_total`、`formulas_ok`、`variables_total`、`by_source`、`derivations_total`、`numeric_computed`、`numeric_example_only`、`claims_total`、`uncertainties_total`、`symbol_coverage`、`claims_quote_verified` | 覆盖度汇总 |
| `missing_objects` | `object`、`reason`、`needed` | 材料中不存在的对象，绝不补造 |
| `method_notes` | 字符串 | 本次方法口径一句话说明 |
| `status_reason` | 对象 | 仅 partial 时出现，写缺项 |
| `selfcheck` | `passed`、`failed`、`checks` | 本版新增：一致性自检结论 |

## 三、枚举与判定

`latex_source` 四值：`mml_annotation`（采用原文 TeX 标注）、`structural_mapping`（结构映射）、`source_tex`（TeX 源文件环境）、`regex_annotation`（解析失败后的正则回退）。
`parse_confidence` 三档：high / medium / low。

符号定义来源 `definition_source`：

- `paper_defined`：命中"where X is …"这类定义句；必须给 locator 与 quote，可信度 high。
- `context_inferred`：该符号在正文出现过、但没有定义句；`definition` 为 null，必须同时出现在 `uncertainties`。
- `common_knowledge`：材料里根本没出现该符号；`definition` 为 null、`inferred=true`，可附 `common_knowledge_hint`，同样必须进 `uncertainties`。

数值核验 `numeric_checks[].status`：

- `computed`：公式变量全部有材料中字面赋值，`substituted` 有值，`order_of_magnitude_check` 给 `log10|value|`。
- `example_only`：无任何赋值，用 1.0 探针验证表达式可求值，`is_example=true` 且 `note` 必须写明示例性质。
- `not_computable`：缺值或表达式不可标量求值，缺的符号列在 `missing_symbols`。

`claims[].kind` 只有 reported 与 inferred；`readability` 只有 directly_read / inferred / undetermined；`quote_verified` 为 true / false / null，false 表示引句没有逐字命中、已被降级。

`uncertainties[].type` 四值：`definition_inferred`、`definition_absent`、`parse_failure`、`synthetic_example`。

## 四、claims 的编号

公式还原记 `C-F<序号>`；符号定义记 `S-<符号>`；推导步骤记 `C-D<序号>`；数值核验记 `C-N-F<序号>`。

## 五、locator 写法

XML 节点写绝对 XPath（元素本地名加位置谓词，如 `/article[1]/body[1]/sec[1]/disp-formula[1]/math[1]`）；正文段落写 `<文件名>#p<序号>`；TeX 环境写 `<文件名>#eq<序号>`；XML 解析失败的回退改写成 `<文件名>#annotation<n>`；JSON 内嵌公式用 `<文件名>#m<n>`。

## 六、状态如何判定

- 目录为空且没有可解析 case → `input_error`。
- 有材料但恢复不出任何公式 → `insufficient_evidence`，同时给 `missing_objects` 和人工接管建议。
- 所有公式 ok、符号覆盖 1.0、有推导、至少一次真实代入 → `ok`。
- 其余 → `partial`，并在 `status_reason` 记录差在哪一项。

`ok` 门槛是有意设高的：任一公式带 flag、任一符号只能算常识、或完全没有可算的代入，都会停在 `partial`。

## 七、字段的写入位置

所有字段只在 `evidence_core.assemble_result()` 一处拼装，入口脚本负责把状态变量喂进去，别处不复制字段名。这样改字段时只需要动两个地方：本文件与 `assemble_result()`。

`result.json` 是唯一机器可读的权威记录；`symbol_table.csv` 是符号表的扁平副本（便于 Excel 打开）；`formulas.tex` 是可编译的 LaTeX 最小集，每条公式前用注释标出来源与置信度；`verification.md` 是给人看的本次运行摘要（含自检结论），三者都不含正式答案。

## 八、常见排错路径

- `contract_fields_missing` 非空：说明输入契约的某个键既不在 `result` 里也没有按类型补空，检查 `output_contract` 是否被当成了非对象。
- `selfcheck.passed` 为 false：看 `selfcheck.failed` 列表，按 check 名定位是符号覆盖、枚举、LaTeX 结构还是示例备注哪一项；失败项同时会出现在 `pending_human`。
- `status` 一直是 `partial`：按 `status_reason` 区分是符号覆盖不足还是缺少真实赋值；材料有限时这是正确结论，不要为了到 `ok` 而编造数据。
- `quote_verified` 为 false：说明该 claim 的引句在材料语料里找不到逐字匹配，通常是因为引句被改写或跨段拼接；应改为原文片段或进入 `pending_human`。

## 九、兼容性约定

字段名与枚举值是评测方读取结果的接口，属于稳定契约：只增不改、不删不换名。本版相对基础实现只新增了 `result.selfcheck` 一个对象，其余字段保持原义；旧的消费方忽略未知键即可。新增字段时必须同时更新本文件与 `assemble_result()`，否则自检的 `contract_keys_backfilled` 检查会提醒。
