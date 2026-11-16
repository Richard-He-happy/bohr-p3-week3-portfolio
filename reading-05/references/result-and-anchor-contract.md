# 数据契约：结果、锚点、批注与资产

本技能用到的 JSON 全部是 UTF-8，字段名一旦发布只增不改。字符偏移的坐标系是清洗后的段落文本
（段落之间以空行拼接成全文），清洗规则见 `passage-anchoring-rules.md`。因此你可以拿任意
`quote` 到 `reader/anchors.json` 的段落文本里按 `char_start`/`char_end` 切片，逐字对上。

## 1. `result.json` 的信封

第一组是结果定位：`case_id`（输入原值，缺失写 `UNKNOWN-CASE`）、`status`（取值 `ok`、`answered`、
`partial`、`insufficient_evidence`、`input_error`）、`result`（主结果对象）、`claims`（结论列表）、
`uncertainties`（不确定项列表）。

第二组是运行证据：`sources`（材料清单，含来源 id、路径、类型、字节数、sha256）、
`pending_human`（需要人做的动作）、`errors`（异常流水）、`degradations`（可用但降级的点）、
`changes`（状态变化）、`runtime`（版本、起止与耗时、Python 版本、日志计数）。

回填规则：输入 `output_contract` 声明的键必须全部出现在最终 JSON 里。认识的键填真值；不认识的
键保留键名，值按声明类型给 `null`/`[]`/`{}`。`case_id` 不改名、不截断。另外会附一个
`uncertainty` 兼容键，与 `uncertainties` 同值。

## 2. `result` 里装什么

- `task_summary`：任务说明摘要、任务数量、已作答数量。
- `document`：材料来源、路径、格式、页数、是否有文本层、用的是哪种抽取器、是否加密、
  报告页数与实际分段是否一致。
- `closed_loop`：七步各自的 `{step, status, output, artifact}`；没执行的记 `skipped` 并写 `reason`。
- `selections`：每条任务的定位结果（见第 3 节）。
- `annotations`：批注与问答的合并记录（见第 4 节）。
- `anchor_precision_counts`：四档精度计数，总和必须等于选区块数。
- `context_design`：问答上下文的构造规则、是否强制、排除了什么。
- `export`：导出文件列表与条目数。
- `efficiency`：脚本步骤数、用户动作数、重开次数、复制粘贴次数（设计值，不是实测对照）。
- `method_notes`：抽取器、锚点规则、上下文规则、持久化策略。
- `artifacts`：本次产出文件的相对路径。

## 3. 锚点文件 `reader/anchors.json`

顶层：`schema`（`margin-reader/anchors@1`）、`source_id`、`doc_text_sha256`（全文哈希，
用来确认版本）、`normalization`（清洗规则说明）、`page_map`（物理页→印刷页→段落的展开映射）、
`paragraphs`、`selections`、`precision_counts`。

`paragraphs` 的每一项：`paragraph_id`，`kind`（`p` 段落 / `h` 标题），`section`（所属章节标题），
`page`（PDF 物理页），`printed`（页脚印刷页，可能为 null），`char_start`，`char_end`，`text`。

`selections` 的每一项：`task_id`，`quote`，`paragraph_id`，`pdf_page`，`printed_page`，
`section`，`char_start`，`char_end`，`anchor_precision`，`locate_method`。

精度四档的含义与触发方式：

| 档位 | 什么情况下给 | 方法名 |
|---|---|---|
| 字符级 | 选区逐字命中，起止字符精确 | `verbatim_search` |
| 段落级 | 只能确定到段落或句子（模糊匹配相似度不低于 0.55，或按关键词排序命中） | `fuzzy_paragraph_match`、`keyword_rank_in_section`、`keyword_rank_global` |
| 页级 | 只确定到章节首段/页 | `section_first_paragraph` |
| 未解析 | 所有办法都失败 | 无；同时写进 `uncertainties` |

注意：段落级/页级的 `quote` 仍然是段落内逐字片段，只是不是用户点的那一段，所以 `notes` 里
必须写明为什么降档；未解析绝不能向下兼容成段落级。

## 4. 批注文件 `reader/annotations.json`

数组，每条同时承载批注与问答：

- 身份与锚点：`annotation_id`（形如 `an-p7-02`，由段落号加顺序确定，不含随机数）、`task_id`、
  `paragraph_id`、`quote`、`pdf_page`、`printed_page`、`section`、`char_start`、`char_end`、
  `anchor_precision`。
- 内容：`question`、`answer`、`answer_quotes`（答案里逐字引用的句子）。
- 上下文：`context_scope`，内含 `selection`、`paragraph_id`、`section`、`used_scope`、
  `excluded_scope`、`chars_used`。
- 元数据：`status`（`answered`/`partial`/`undetermined`）、`tags`、`created_at`。

写入约定：一条写完立刻落盘（先临时文件再原子替换）。下次运行先读旧文件，按段落号与问题文本
合并，批注数量只增不减。

## 5. 问答日志 `reader/qa_log.json`

`schema`（`margin-reader/qa@1`）+ `source_id` + `context_policy` + `qa` 数组。每条问答记
任务号、问题、答案、引用句、所属段落、锚点对象（物理页/印刷页/字符区间/章节）、精度档位、
上下文范围与状态。它是问答的流水账，与 `annotations.json` 同源。

## 6. 会话状态 `reader/reading_state.json`

`schema`（`margin-reader/state@1`）+ `source_id` + `doc_text_sha256` + `last_paragraph_id` +
`annotation_ids` + `sessions` + `resumed_from_previous` + `updated_at`。每次运行 `sessions`
加一；续读时 `resumed_from_previous` 为真。

## 7. 客户端 `reader/index.html`

一份不依赖任何外部资源的 HTML：样式与脚本内联，字体用系统字体。正文按段落 id 铺开，被选中的
段落加 `data-selection` 标记，批注范围用 `<mark>` 高亮并挂 `data-aid`。侧栏把批注渲染成卡片，
点击能跳回段落；另有关键词过滤、上次位置记忆（localStorage）和阅读记录下载。页面里嵌了
anchors/annotations/qa/record 四份 JSON，HTML 本身就是数据容器，可以离线复核。

## 8. 目录里的五件资产

| 文件 | 结构 |
|---|---|
| `golden_standard.json` | `golden@1`；`items[]` 每项有 id、类别、要求、期望值、定位器、逐字引文、检查方式、状态；`output_contract` 键逐键登记，问答/批注/锚点/选区逐项带 locator |
| `diff_report.md` | 总览计数、逐项对照（含复核位置）、未达标清单 |
| `version_history.md` | 静态谱系 v0 → v1.0.0、文件字节与 sha256、回退步骤，末尾运行时追加本次运行段 |
| `run.log` | `runlog@1`；步骤时间线、材料哈希、降级、异常、待人工、校验摘要 |
| `self_check.json` | `selfcheck@1`；`checks[]`、`probes[]`、`counts`、`overall` |

`result.json` 顶层会再挂这五个同名摘要对象（路径、哈希、字节数，`run.log` 另记步骤数与错误/降级条数），
并额外记录 `runtime.augment`（资产版本、自检结论、差异判定）。它们与业务字段并存，不改名。
