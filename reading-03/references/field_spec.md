# result.json 字段说明与状态判定

本文件回答三个问题：产物里有哪些键、每个键装什么、什么情况下该给哪个状态。
`scripts/reader_kit.py` 按这里生成字段；平台若改名，只需保证层级与含义不变。

## 1. 顶层信封

| 键 | 类型 | 说明 |
|-|-|-|
| `case_id` `paper_id` `material_version` | string / null | 从输入原样带出；输入没有就写 `null`，绝不编造 |
| `status` | enum | 整体状态，取值见第 5 节 |
| `result` | object | 业务主体：`answers[]`、`unanswered_parts[]`、`coverage` |
| `answers` | array | `result.answers` 的镜像，便于按题序直接读取 |
| `claims` | array | 所有题目的 `claims` 展平后的合集 |
| `uncertainties` | array | 未报告、召回偏低、数值单位不符、证据冲突等不确定项 |
| `pending_human` | array[string] | 需要人工确认的具体动作，写成可执行的一句话 |
| `errors` | array[object] | 运行异常：`stage`、`question_id`、`error` |
| `degradations` | array[object] | 降级记录及其影响：缺词表、patch 不合格、兼容件写失败等 |
| `changes` | array[object] | 本次运行的结构化改动：跨段推断、子问借证、边界清空等 |
| `sources` | array[object] | 输入来源与 `sha256_16`，供回溯 |
| `counts` | object | 计数：题数、状态分布、claim 数、引文命中率、数值痕迹率 |
| `method_notes` | object | 流程与引文策略自述（不代替结果本身） |
| `runtime` | object | 脚本耗时、Python 版本、预算说明、是否截断 |
| `contract_keys` / `question_ids` | array | 输入 `output_contract` 的键名、输入问题 id（供自检核对） |

**契约回填规则**：输入 `output_contract` 里出现的每个键都要在顶层出现。已知键填真实内容，
未知键原样保留，缺值写 `null` 或 `[]`，键名不改。平台把业务字段预声明为空列表时，
真实结果优先，不能被空声明覆盖。

## 2. `result.answers[]`

| 键 | 要求 |
|-|-|
| `question_id` | 与输入一致；输入只给字符串题干时按顺序生成 `Q1..Qn`，并写入顶层 `question_ids` |
| `question` | 原题干，方便逐条核对 |
| `answer` | 中文回答；多子问用 `【子问1】…【子问2】…` 分块，数值、单位、条件只来自引文 |
| `conditions` | 成立条件列表（原文条件片段 + 段落号），无则为 `[]` |
| `status` | `answered` / `partial` / `insufficient_evidence` / `input_error` |
| `claims` | 本题论断数组 |
| `unanswered_parts` | 未答部分；`answered` 时必须为 `[]` |
| `evidence_paragraph_ids` | 本题引用到的段落号，`coverage` 的计数依据 |
| `sub_questions` | 子问数组：`index`（从 1 连续）、`question`、`status`、`claim_ids`、`evidence_paragraph_ids` |
| `question_type` / `flags` | 判型结果（`NUM`/`MECH`/`BND`/`INT`/`GEN`）与命中标记，供复核 |

题干有几个问题就要有几条 `answers`，读不出、答不了的题也要留位并写清原因。

## 3. `claims[]` 与 `evidence[]`

论断字段：`claim_id`、`question_id`、`text`、`kind`、`readability`、`conditions`、`source_id`、`evidence[]`。

- `claim_id` 稳定唯一。约定：`Q1-S2-N3` 表示第 1 题第 2 子问的第 3 个数值论断；
  `Q1-S1-C4` 为原文引证论断；`Q1-INT1` 为跨段推断；`Q1-ABS1` 为「材料未报告」论断。
- `text`：数值论断统一写成 `label = value unit`，一个数值一条 claim，便于逐条核验。
- `kind`：只有 `reported`（原文报告）和 `inferred`（由多段合并或由缺席推出）两个值。
- `readability`：`reported` 对应 `directly_read`；`inferred` 对应 `inferred` 或 `undetermined`。
- 未报告类论断允许 `evidence` 为空，但必须在 `uncertainties` 附检索统计（检索词、零命中数、检索段数）。

证据字段：`paper_id`、`paragraph_id`、`section`、`locator`、`quote`、`char_start`、`quote_verified`、`quote_words`。

- `paragraph_id` 必须来自输入段落清单，不许自造；`section` 缺失写 `unknown`。
- `locator` 用 `/paragraphs/12`、`/tables/1`、`/raw_text/7` 这类可回查的路径。
- `quote` 必须是原文逐字子串：不翻译、不改写、不拼接两段、不加省略号；一般 15–60 词。
- 校验口径：`paragraph.text[char_start : char_start+len(quote)] == quote`，同时 `quote in paragraph.text`。
  脚本按字符区间切片，天然满足；外部补写的引文必须经 `--apply` 或自检才被接收。
- `char_start = -1` 表示未命中，这类证据不计入 `quote_hit_rate`。

## 4. `unanswered_parts[]` 与 `coverage`

未答条目：`{"part": 未答子问原文, "question_id", "reason", "missing": 缺什么, "needed": 需要什么才能补}`。
`reason` 取值：`no_matching_paragraph`、`not_reported_after_full_search`、
`numeric_value_not_reported`、`internal_error`。`partial` / `insufficient_evidence` 题必须有条目。

`coverage` 记录读到哪里、没读到哪里：

| 键 | 含义 |
|-|-|
| `paragraphs_supplied` / `paragraphs_indexed` | 输入段落数 / 实际建索引数 |
| `paragraphs_cited` / `cited_paragraph_ids` | 被引段落数 / 段落号列表 |
| `sections_read` / `sections_cited` | 各章节段落数 / 被引章节 |
| `sections_unread` / `unread_reason` | 未读章节 / 原因（`only_abstract_supplied` 等） |
| `read_status` | `full_text_sections_indexed` / `only_abstract_supplied` / `section_labels_not_supplied` |
| `chars_supplied` | 索引字符数 |
| `not_supplied` | 材料未提供的对象（表格、图注、参考文献著录等） |
| `method` / `note` | 阅读方式与边界说明 |

材料只给了已抽取文本，没有 PDF 页图或像素，因此 `coverage` 里不给页码和图元读数，
也不做 OCR 与联网检索。

## 5. 状态判定表

| 场景 | 逐题 `status` | 整体 `status` |
|-|-|-|
| 所有子问都有原文依据，数值题拿到带单位数值 | `answered` | `ok` |
| 部分子问有依据、缺子问或缺数值 | `partial` | `partial` |
| 全篇检索无可用依据，「未报告」结论有检索统计支撑 | `insufficient_evidence` | `insufficient_evidence`（全部题目如此时） |
| 案例包读不出（缺文件、坏 JSON、无问题清单） | `input_error` | `input_error` |

约束：逐题与子问的 `status` 只能取上述四值，不许出现 `ok`、`unknown`、`N/A`；
`claims[].kind` 只能取 `reported` / `inferred`。有依据地说明「材料未报告」也算完成该题，
但必须给出检索范围与零命中情况；不能只写一句「不存在」。

## 6. `uncertainties[]` / `pending_human[]`

`uncertainties` 每条是一个对象，至少带 `type` 与 `question_id`，可按情况补
`detail`、`zero_hit_terms`、`paragraphs_searched`；`type` 允许
`not_reported` / `low_recall` / `conflict` / `unit_mismatch` / `missing_meta`。
同一数量在原文出现两个不同值时，两条都保留为 `reported`，另记 `conflict` 与两处段落号，
不挑一个当唯一事实。`pending_human` 写具体动作，例如「Q3 未见直接证据，请人工确认未报告结论并复核检索词」。

## 7. 与评分维度的映射

| 评分点 | 在产物里的落点 |
|-|-|
| 生态贡献 | 本文件 + `term_map.md` + `worked_example.md` + `SKILL.md` |
| 可靠体验 | `errors` / `degradations` / `input_error` 分支，退出码恒 0 |
| 创新 | `INT1` 跨段推断、子问级状态、条件绑定、`ABS1` 未报告判定 |
| 质量/效率增益 | `counts`、`method_notes`、`verify_report.json`，可与同输入白板逐条对照 |
| 结果可核验性 | 段落号、locator、字符偏移、逐字校验标志与 CSV 证据表 |
| 结果完整性 | 子问分块 `【子问N】`，缺项进 `unanswered_parts` |
| 结果正确性 | `claims[].text` 的数值单位、`evidence[].quote` 原文与 `conditions` |
| 任务完成度 | `answers` 题数 = 输入题数，逐题 `status` 齐全，子问进 `sub_questions` |

## 8. 自研审计项：数值痕迹率

`counts.numeric_claims_checked` / `numeric_claims_traced` / `numeric_trace_rate`
与 `verify_report.json.numeric_trace` 检查一件事：每个 `label = value unit` 型论断的数值，
必须能在该论断自己的 `evidence[].quote` 中逐字找到（千分位 `1,250` 与逗号小数 `2,4`
在比较前归一化）。命中率低于 1.0 时把对应 `claim_id` 列入
`numeric_trace.unmatched_claim_ids`，交人工复核；该检查与 `verification.checks` 中的
`numeric_values_trace_to_quotes` 同步。
