# 网格、定位、图与 PDF 质量

记录证据位置和修复表格的操作规则。最后一节是改动脚本或文档后必须执行的回归流程。

## 1. 定位格式

| 证据类型 | 需要的键 | 示例 |
|---|---|---|
| 正文段落 | `paragraph_id`，可加 `section`、`page` | `"R-012"`，第 5 页，`Results` |
| 表格单元格 | `table_id` + `row_header` + `col_header`（+ `page`） | `T3` / `T6-aged` / `Strength (MPa)` |
| 图 | `figure_id`（+ `page`、`panel`） | `Fig. 4c`，第 8 页 |
| 补充材料 | 补充材料的 `source_id` + `paragraph_id` | `S2` / `S2-p006` |

规则：

1. `paragraph_id` 必须在 `work/corpus_index.json` 中存在。自动生成的 id 形如
   `<文件名>-pNNN` 或 `pdf-pNNN`，使用时要说明是生成的。
2. 不允许只写表号。行标题和列标题要照印刷原样给出，表头里带单位也要一起写。
3. 一个字段一个主定位。若数值在表里、条件在方法里，定位数值并在 `notes.secondary` 记第二处。
4. 引文必须能在所引定位处找到；找不到时闸门会把该字段降级。

## 2. 表格重建

- 表头识别：markdown 分隔线上方的行；CSV/JSON 网格取开头不含数字的一行或多行。多层表头
  按列用 ` / ` 连接。
- 合并单元格：首列为空时继承上一行的行标题，标 `merged_cell: true`；继承来的标签照抄，
  不要凭空补。
- 跨页续表：出现重复表头或 `(continued)` 表题时，行仍属同一 `table_id`，网格标
  `parse_flags: ["cross_page_merged"]`；若数值来自第二页，在 `notes` 说明。
- 特殊写法：范围（`12–15`）、不等式（`< 0.05`）、`n.r.`、`–`、空格子都照抄。`n.r.` 表示
  未报告——该字段为 `not_reported`，并把该单元格写入 `search_scope`，绝不能写 `0`。
- 一个格子里两个数（`318 / 305`、`318 (305)`）表示两个条件或两个样品；表注无法区分时用
  `source_conflict` 或不确定性，不挑一个。
- 单位可能在列标题、表注、方法三处。`units` 优先取表头，其余位置写 `notes`，不要为了对齐
  而换算。

## 3. 图作为证据

记录 `figure_id`、`page`、`panel`、坐标轴类型（线性/对数）、刻度值、轴单位、图例项、系列
数、误差线类型（SD/SEM/CI/无）；显微图还要比例尺。区分"从印刷标签直接读出"与"按刻度位置
估计"：估计值写成 `~810` 加误差，并标 `readability: inferred`，不得伪装成印刷值。

## 4. PDF 文本质量

`scripts/checks.py` 只用 `zlib` 从 PDF 内容流还原文本，不调用外部工具，也不做 OCR。
`sources[].meta.quality` 给出四档：

| 质量 | 处理 |
|---|---|
| `usable` | 正常抽取，用 `pdf-pNNN` 定位第 N 页 |
| `low` | 可抽取，但引文核验不了时给数值字段加 `quote_not_verbatim` 不确定性 |
| `no_text_layer` | 该文件不抽：相关字段 `extraction_failed`，按页写 `pending_human`，原因进 `degradations` |
| `encrypted` | 同上；解密不在能力范围内 |

扫描页不靠眼睛猜数，图片表格也不补值。

## 5. 收尾审计清单

- 每个请求的 `field_id` 恰好一条结果，四种状态计数之和等于请求数；
- 每条 `reported` 的引文在定位处逐字出现，且 `value` 的每个数字都在引文内；
- 每条 `not_reported` 有 `search_scope`；每条 `source_conflict` 有双引文与双定位；
- 结论类字段有 `claim_type`，模糊词仍在；
- 没有字段把某个条件的数值配上另一个条件的单位或条件——最快的探针是
  `condition_not_in_quote` 标记与 `validation.condition_binding`；
- 上面任何一条不满足时，`uncertainties` / `pending_human` 必须有对应记录。

## 6. 改动后的回归流程

按顺序执行并记录结果：

1. `python3 scripts/pipeline.py --help`：退出码 0，帮助文本与文档中的参数一致。
2. 空输入目录：`--stage prepare` 产出 `input_error` 的 partial `result.json`，退出码 0。
3. 故意写坏的 `case.json`：错误被记录，其余材料仍解析，partial 结果照写，退出码 0。
4. `SKILL.md` 里的合成示例：填好草稿后 finalize，coverage 计数自洽，`fields.csv` 每字段一行。
5. 抽查若干 `reported` 记录：引文、数字、条件绑定三项人工复核至少三条。

本包新增的条件绑定检查相当于把第 5 步的一部分自动执行：它让"数值与条件张冠李戴"可见，但
无法证明语义正确，人工抽查仍是必需的。
