---
name: paper-evidence-ledger
description: 将单个文献案例整理为契约化的 result.json：每个请求的 field_id 对应一条记录，含字面值、单位、统计量、实验条件、对照物、逐字引文、段落/表格精确定位，以及 reported / not_reported / source_conflict / extraction_failed 四种状态之一。输入通常包含论文材料（段落 JSON、markdown/CSV 表格、带文本层 PDF、补充材料）与字段清单（如 /input/target-fields.json），适用于结构化结论与数据抽取、实验条件表、结论/限制/推测分层、字段级证据定位等任务。
version: 1.0.0
---

# paper-evidence-ledger

目标是把论文读成一份能复核的账本：字段清单的每一项都有印刷值、支持它的实验语境、第二个人
能按定位查到的原句，以及一个不夸大的状态。输出不是摘要，也不是"尽量像原文"的复述。

适用：期刊/预印本正文与补充材料、段落与表格 JSON、markdown/CSV 网格、仍有文本层的 PDF。
不适用：无文本层扫描页（不做 OCR）、化学结构图像、跨论文元分析；一次只处理一个案例。

## 一、先跑起来

```bash
python3 scripts/pipeline.py --stage=prepare  --input=/input --output=/app/output --work=/app/work
# 读 /app/work/corpus_index.json，把每个字段的读数写进 /app/work/draft.json
python3 scripts/pipeline.py --stage=finalize --input=/input --output=/app/output --work=/app/work
```

| 阶段 | 结果 |
|---|---|
| `prepare` | 占位 `output/result.json`（每个字段一个槽）、`work/corpus_index.json`、`work/draft.json` |
| `finalize` | 最终 `output/result.json` + 供抽查的 `output/fields.csv` |
| `run` | 等价 finalize；无草稿时全部槽位为 `extraction_failed` 并写明原因 |

脚本只用 Python 3.8+ 标准库，不依赖当前目录；`--draft 路径` 可换草稿位置。预算 900 秒 /
64 次请求，约 780 秒时必须开始收尾。之所以先写占位再覆盖，是保证预算耗尽时磁盘上也有一份
结构合法、可以继续人工接手的结果。

## 二、交付契约

`result.json` 要让 `output_contract` 里的每个键原样存在；无值的键保留为 `null` 或 `[]`。
契约键之外另加 11 个封装键：`case_id`、`status`、`result`、`claims`、`sources`、
`uncertainties`、`pending_human`、`errors`、`changes`、`degradations`、`runtime`，含义与
结构见 `references/field-ledger.md`。任何异常只在 JSON 里记录，进程退出码始终为 0。

## 三、输入与中间文件

输入看 `/input`：`case.json`、`task.md`，字段清单优先 `/input/target-fields.json`。字段清单
识别不依赖固定键名，`{fields:[…]}`、裸数组、`{groups:[…]}`、字符串数组都可以；都没有时按语义
在 case 与 task 文档里找，仍找不到就报 `input_error` 并列出检索过的路径。

`work/corpus_index.json` 有两部分：`units` 是可读段落（`paragraph_id`、`section`、`page`、
`text`、`source_id`）；`tables` 是网格（`table_id`、`columns`、`rows`、`caption`、
`parse_flags`）。`work/draft.json` 是骨架：说明块 + 每字段一个空位；填充时保留 `field_id`，
按需给 `status`、`value`、`units`、`statistic`、`condition`、`comparator`、`source`、`quote`
等键。定不下来的字段也留占位，不能从数组消失。

## 四、一条字段记录

`result.fields` 条数 = 请求字段数，不多不少。常用键：值三件套 `value`/`units`/`statistic`；
条件对象 `condition`（槽位 `sample`、`setting`、`timepoint`、`baseline`）与 `condition_complete`、
`comparator`；证据 `source`、`quote`、可选 `quote_join`；分类 `claim_type`、`kind`；说明
`notes`、`search_scope`、`conflicts`；脚本回填的 `validation`。字段字典随结果提交在
`result.field_dictionary`。

## 五、字面值

照抄页面：`±`、`12–15` 这类范围、`<`/`>`、`n = 4`、`p < 0.05`、千分位、末尾零（`7.80` 不能
变 `7.8`）。单位进 `units`，误差与显著性进 `statistic`。换算要另存 `original_value`、
`original_unit`、`conversion_rule`，印刷值不动。相减或相除才得到的数字标 `inferred`：两个
操作数都要有引文，算式写 `notes`。原文没给数值 = `not_reported`，绝不当 0。

## 六、表格、图、PDF

合并单元格继承上一行行标题并标 `merged_cell`；重复表头的续表并入同一 `table_id` 并标
`cross_page_merged`。`n.r.`、`–`、空格子表示未报告，不是 0；一格两个数表示两个条件或样品，
说不清就用 `source_conflict` 或不确定性。单位可能在列标题、表注、方法三处：`units` 取表头，
其余位置记 `notes`，不为了对齐而换算。图中按刻度估的值写 `~810` 加误差并标
`readability: inferred`。PDF 质量四档记在 `sources[].meta.quality`：`low` 时数值字段可能加
`quote_not_verbatim` 不确定性，`no_text_layer` / `encrypted` 时相关字段全部
`extraction_failed` 并写 `pending_human`；本包不做 OCR。细则见
`references/grid-evidence-and-pdf.md`。

## 七、定位与引文

| 证据 | 需要的定位 |
|---|---|
| 正文 | `paragraph_id`（须存在于 corpus_index），可加 `section`、`page` |
| 表格 | `table_id` + 逐字 `row_header`、`col_header`；只写表号不算定位 |
| 图 | `figure_id`，必要时 `page`、`panel` |
| 补充材料 | 补充件 `source_id` + `paragraph_id` |

引文取所引单元内连续的一段原文，覆盖数字、单位和区分条件的关键词。值与条件分处相邻两句时给
两段引文并标 `quote_join: "adjacent_sentences"`，不能拼成一句假引文。自动生成 id（形如
`<文件名>-pNNN`、`pdf-pNNN`）要在 `notes` 说明。引文能在定位处找到只是必要条件，还要确认句子
的主体与条件就是本字段的。

## 八、状态只有四种

| 状态 | 何时用 | 附带 |
|---|---|---|
| `reported` | 定位处印出了该值 | `value`、逐字 `quote`、`source` |
| `not_reported` | 全章节 + 全表格查过确实没有 | `search_scope`（章节、表格、关键词） |
| `source_conflict` | 同字段同条件出现两个读数 | 两段引文、两个定位、两个值 |
| `extraction_failed` | 材料不可读或引文无法核实 | `notes` 写明原因 |

顺序是：能定位核验先 `reported`；材料自身矛盾就 `source_conflict`；完整扫描后才允许
`not_reported`；材料本身读不了才是 `extraction_failed`。冲突不取平均，缺失不写 0。

## 九、结论类字段分层

`author_conclusion`、`limitation`、`hedged_claim` 或 `expected_type: text` 必须给 `claim_type`：
`conclusion`（论文明确给出/证明）、`limitation`（范围限制、未做的检验、样本偏小、后续工作）、
`speculation`（may / might / suggest / appear / likely 等可能性表述）。`value` 保留模糊词，
`may point to` 不能改成 `shows`。每条 claim 标 `readability`：`directly_read`、`inferred`、
`undetermined`（有引文但语义关系未建立，同时进 `uncertainties`）。

## 十、条件绑定检查（本包增量）

每个 `reported` 字段会把 `condition` 的词与 `quote` 的词比对：至少一个条件词应出现在引文里。
数字命中而条件词全不命中时，`validation.condition_binding.bound` 为 false，追加
`condition_not_bound_to_quote` 不确定性并记规则 `condition_not_in_quote`；此时不要直接采信，
回到上下文确认是否错拿了相邻样品或时间点的数值。命中时记录槽位与重合词，便于审计"值和条件
同源"。

## 十一、异常分支

| 情况 | 处理 |
|---|---|
| 无字段清单且无同义结构 | `status: input_error`，`errors` 列已找路径，`fields: []` |
| `case.json` 非法 JSON | 记录降级，`case_id` 置 null，其他材料继续处理 |
| 输入目录为空 | 写 `input_error` partial `result.json`，退出码 0 |
| 单条引文核验失败 | 仅该字段 `extraction_failed` |
| 表格/页面读不了 | 依赖它的字段失败，其余不受影响 |
| 草稿缺字段 | 该槽保持 `extraction_failed` 并记不确定性 |
| 内部异常 | trace 进 `errors`，落盘兜底 partial，退出码 0 |

`uncertainties` 放重读能解决的事（引文模糊、缺单位/误差、条件不全）；`pending_human` 放需人
决定的事（引文找不到、值与引文不符、真冲突、区域不可读）。

## 十二、禁止事项

禁止猜值补全、把相邻条件的数值挪给本字段、因字段难而删字段、润色引文或拼接假引文、把推测写成
结论、对冲突取平均、引入第三方库/OCR/联网、依赖当前目录或写死路径、把正式评测答案预置进包。

## 十三、交付前检查

1. `fields` 条数 = 请求字段数，`result.coverage` 四种状态计数之和等于同一数字。
2. 抽 3 条 `reported`，值与单位能在引文里逐字找到。
3. 每条 `not_reported` 有 `search_scope`；每条 `source_conflict` 有双引文双定位。
4. 结论类字段有 `claim_type` 且模糊词仍在。
5. `condition_not_in_quote` 要么重读修正，要么转成不确定性。
6. `output_contract` 全部键仍在；`fields.csv` 每字段一行。
7. `errors`、`degradations`、`pending_human` 与实际情况一致。

## 十四、合成示例（虚构数据，仅演示接口）

设 `/input/case.json` 给出 `case_id: SYN-READ-DEMO`、含 5 个键的 `output_contract`，材料只有
段落 `R-004`（T6 态合金抗压 318 MPa，SD 11 MPa，n = 4，铸态 210 MPa）和表格 `T7`，字段清单
只请求 `yield_strength`。两阶段跑完后：`status` 为 `answered`；`result.fields` 恰一条，`value`
是 `"318"`、`units` 为 `"MPa"`、`source.paragraph_id` 为 `"R-004"`、`quote` 为原句；`coverage`
计为 requested=1、reported=1、其余三项为 0；`claims` 等四个列表存在。示例值均为虚构。

## 十五、文件清单与维护

| 路径 | 作用 |
|---|---|
| `SKILL.md` | 入口：流程、契约、规则、检查项 |
| `scripts/pipeline.py` | 两段式驱动：语料索引、占位槽、封装、CSV、恒退出 0 |
| `scripts/checks.py` | 校验闸门：引文检索、数字/单位覆盖、结论分层、网格、PDF 文本、条件绑定 |
| `references/field-ledger.md` | 记录契约、条件槽位、单位表、来源顺序、封装字段 |
| `references/state-and-claim-codebook.md` | 状态判定、引文规则、结论分层、冲突与人工接管 |
| `references/grid-evidence-and-pdf.md` | 定位格式、表格修复、图与 PDF 质量、回归流程 |

依赖 Python 3.8+ 标准库（`json`、`csv`、`re`、`zlib`、`difflib`、`argparse`、`pathlib`），
不联网；版本 1.0.0。扩展点：单位改 `checks.py` 的 `UNIT_LEXICON`，模糊/限制/强结论词改同文件
三个词表，字段模板改 `references/field-ledger.md`。改完脚本至少重跑 `--help`、空输入、坏
JSON 三种情况（退出码 0 且 partial 合法），再跑合成示例确认 coverage 自洽。
