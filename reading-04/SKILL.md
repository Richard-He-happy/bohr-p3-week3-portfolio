---
name: cross-paper-field-matrix
description: 跨论文对照工作流：统一字段字典、逐格取证（值+单位+数据集+口径+逐字引文+锚点）、过可比性闸门后再综合，产出可复核矩阵、证据卡与 result.json。面向 comparison-workorder 类多文档比较案例。
version: 1.0.0
---

# 跨论文共同字段对照

## A. 一句话与适用边界

同一研究问题下拿到多篇论文 + 一份比较要求时，用本技能把它们压到**同一套字段定义**上，逐格取证、判可比、解释分歧，最后交出一张能被第三方复算的对照表。

用：多份材料 + 统一字段的比较任务（workorder 里出现 `documents`/`fields`/`comparison_dimensions` 等键）。
不用：单篇摘要式抽取、写作类或制图类任务。**单独一篇的总结按题意不算跨文档比较。**

## B. 环境合同

| 项 | 要求 |
|---|---|
| 读取 | `/input/case.json`、`/input/task.md` 及同目录材料（PDF/DOCX/TXT/MD/CSV/JSON/…） |
| 临时区 | `/app/work`（索引、工作稿、审计记录） |
| 交付区 | `/app/output`，四件产物，必须含 `result.json` |
| 命令 | `scripts/main.py` 提供 `init` / `show` / `check` / `build`；`scripts/evidence_check.py` 提供 `quote` / `draft` |
| 技术约束 | 仅标准库；离线；不读当前工作目录；路径从包根 `Path(__file__).resolve().parent` 展开 |
| 异常策略 | 任何失败都不许让进程非零退出；先写 partial `result.json`，错误进 `errors` |

`--input/--output/--work` 可覆盖默认路径；`SKILL_INPUT/SKILL_OUTPUT/SKILL_WORK` 环境变量同效。

## C. 作业顺序（固定四步 + 一次手写）

**① 建索引**

`python3 -B scripts/main.py init`

脚本切分材料、生成 `work/index.json`（每段的锚点形如 `p3#para7`），并立即落 partial 结果。终端会打印文档 id、类型、段数、抽取器，以及 workorder 的字段/论文摘要——后续引用只认这里打印的 id。

**② 读原文**

`python3 -B scripts/main.py show --doc D1 --paras 1:30`（省略 `--doc` 则列目录）

必须逐篇读完再动笔。内置解析器兜底时锚点会变成 `s2#para5` 一类，这是预期降级。

**③ 手写工作稿 `work/draft.json`**

这是全流程的质量核心，Agent 自己完成。每格写：值、单位、数据集/口径、逐字引文、锚点；没报告就 `status:"unreported"` + `value:null` + `note`（写检索范围）。

> 脚本负责搬运和查错，不负责替你理解论文。没有工作稿时 `build` 只能交降级空表，**不要把它当答案**。

**④ 校验并定稿**

`python3 -B scripts/main.py check` → 按 `FIX [...]` 修稿 → `python3 -B scripts/main.py build`

`check` 输出可读 JSON 与 `coverage=`/`quote_pass=`/`reported=`/`errors=` 汇总。`build` 即使检查未过也会继续：缺格补 `unreported` 占位（绝不造数）并记入 `degradations`，最后回填契约。

## D. 输入怎么认

1. 先找 `case.json`（无则任意 `*.json`），从中取 `case_id`、`task_instruction`、`output_contract`；键名可能不同，按语义判断。
2. 扫 `/input/**`，去掉 `case*.json`、`task.md`、`*workorder*.json`，剩余全是材料。类型用**魔数 + 扩展名**判定（`%PDF`→pdf；`PK` 且含 `word/`→docx），不要凭文件名臆测内容。
3. 比较要求优先读 `*workorder*.json`；没有就去 case 结构里找 workorder 对象。关注 `research_question`、`documents[]`、`fields[]`、`comparison_dimensions[]`、`forbidden_pooling`。
4. 文档 id 以 workorder 的 `document_id` 为准，用文件名配对；配不上的落到 `D1..Dn`，并在 `sources` 写明映射。

## E. 工作稿结构

工作稿是一棵普通 JSON 对象，键名固定、形状如下（值是示意，不代表正式案例结果）：

- `question`：字符串，被比较的同一研究问题。
- `papers`：数组；每项含 `doc_id`、`citation`、`study_type`。
- `fields`：数组；每项含 `field_id`、`name`、`definition`、`unit`、`value_rule`。
- `matrix`：数组；每项含 `doc_id`、`field_id`、`value`、`unit`、`dataset`、`metric_scope`、`status`、`quote`、`locator`、`note`。
- `comparability`：数组；每项含 `dimension`、`doc_ids`、`comparable`、`basis`，可选 `quote` 与 `doc_id` 指出依据出处。
- `conclusions`：数组；每项含 `doc_id`、`direction`、`strength`、`claim`、`quote`、`locator`。
- `agreement`：对象；含 `overall` 与 `items`，每个 item 有 `topic`、`verdict`、`attribution`、`explanation`、`evidence`（数组，元素为 `{doc_id, locator}`）。
- `limitations`、`uncertainty`：字符串数组，写作者自述的边界与不确定处。

枚举只能用下列值：`matrix[].status` ∈ reported / unreported / not_applicable；`conclusions[].direction` ∈ increase / decrease / no_effect / mixed / unclear；`agreement.items[].verdict` ∈ consistent / partially_consistent / conflicting / insufficient；`agreement.items[].attribution` ∈ sample / method / metric / condition / unresolved。

## F. 取证纪律（每格四件套：值、单位、引文、锚点）

- 引文必须在该文档抽取全文里**逐字出现**；不许转述、拼接、翻译或跨段拼句。找不到就改判 `unreported` 或进 `pending_human`，不要凑。
- 数值格必带 `unit`；跨数据集/口径时再带 `dataset`/`metric_scope`；换算值在 `note` 标 `converted from …`。
- 锚点复制 `show` 打印值；跨段引用取首段锚点。
- 图表只能写"约 X"，误差进 `uncertainty`；没有文字依据的不要写成事实。
- `unreported ≠ 0 ≠ 未做`：note 里写清查过哪些段/表。

## G. 两级对齐法

**第一级——先立字典**：一个 `field_id` 一种含义；同义指标合并并在 `definition` 标注范围；剂量与时长等不同口径不得混放。

**第二级——可比性闸门**：综合前逐维检查（workorder 指定维度优先）：`task` → `metric` → `units` → `material` → `pollutant` → `budget`。全一致才 `comparable:true` 允许合并；任一维不同就 `false` + `basis`（哪维、原文依据），数值保留但**不入池**，改分层叙述；维度未报告按不可比处理。workorder 的 `forbidden_pooling` 是红线，命中即禁止合并；给定量结论时必须写明可比子集。

## H. 一致性与冲突

判定口径如下：`consistent` 表示方向与强度都一致、且条件确实可比；`partially_consistent` 表示方向相同但强度或人群范围有差异；`conflicting` 表示方向或显著性相反，此时归因字段必须落到 sample/method/metric/condition 之一，实在归不了就填 `unresolved` 并把该项列入 `pending_human`（`check` 会把这种情况标错）；`insufficient` 指仅一篇报告或证据量不足。凡冲突都要成对出现两边原话和各自锚点，不许平均、不许只写一边。

## I. 产物、契约与状态

四件产物：`comparison_matrix.csv`（长表，表头见脚本内 `CSV_COLUMNS`）、`comparison_table.md`（宽表 + 判定 + 冲突 + 覆盖）、`evidence_cards.jsonl`（每张卡带 quote/锚点）、`result.json`（契约 + 信封）。

**契约回填**：`output_contract` 的每个键都要出现在 `result.json`，不改名不漏键；优先同名取值，其次按语义提示（`matrix`→矩阵、`comparability`→可比性、`agreement`/`conclusion`→一致性、`coverage`→覆盖计数、`conflicts`→冲突、`fields`→字段表、`papers`→论文表、`summary`→Markdown 汇总）；仍取不到就按声明类型填空值（null/[]/{}），并把键名写进 `pending_human`。`build` 末行 `unfilled contract:` 必须是 `none` 或已有解释。

**信封字段**：`case_id`、`status`、`sources`、`uncertainty`、`pending_human`、`errors`、`degradations`、`changes`、`runtime`。状态四档：`ok`（契约齐、零错误、无降级、覆盖>0）/ `partial`（有降级或缺格但表可读）/ `insufficient_evidence`（无可用文本）/ `input_error`（目录缺失或无材料）。

## J. 降级手册

| 触发 | 动作 |
|---|---|
| PDF 扫描件无文字层 | 记 `degradations`，转 `pending_human`，不瞎猜 |
| 没有 `pdftotext` | 内置 zlib 解析兜底，锚点变 `s1#para3`，注明页号不权威 |
| 不认识的容器 | 不解析，记降级 |
| workorder 无字段 | 用 8 个通用维度，`pending_human` 提示补字段 |
| 材料与 workorder 对不上 | 保留 `D1..Dn` 编号并写映射 |
| 同一论文两版本 | 当两个文档，`dataset` 维判不可比 |
| 某文档解析失败 | 只降级该文档，其余继续 |
| 工作稿缺失/坏 JSON | 全 `unreported` 空表 + `partial` + 缺口清单 |
| 冲突无法归因 | `unresolved` + `pending_human`，不硬判 |
| 空输入/坏 case | 合法 partial `result.json` + `errors`，退出码 0 |

## K. 交付自检

1. `output_contract` 键齐全，`unfilled contract:` 为 `none`。
2. CSV 行数 = 文档数 × 字段数；`reported` 行都有引文和锚点。
3. 任抽 3 格用 `scripts/evidence_check.py quote --index work/index.json --doc <id> --quote "<引文>"` 回查，返回 `found: true`。
4. 每篇都能覆盖对象/数据/方法/条件/指标/结论/局限中可得项；未报告项都有 note。
5. 可比性维度齐全；不可比数值未入池；冲突都有归因。
6. 同输入复跑两遍，CSV 与 JSONL 逐字节一致。

**本包增量 · 三验抽样**：额外做一张 `work/sample_audit.md` 记录表，各抽一个数值格、未报告格、冲突格，逐格核对「值→引文→锚点→单位/数据集/口径」四环，并写明失败处置。模板见 `references/review_playbook.md` 第 5 节。

## K2. 五件可核验资产（build 自动生成，v1.0.0+p1）

`build` 在写完四件主产物后，由 `scripts/assets.py` 在交付区**追加**五件资产，原主产物与
`output_contract` 键不变（`result.json` 只加键：`assets`/`golden_standard`/`diff_report`/
`self_check`/`version_history`/`run_log`）：

| 资产 | 内容与复核方式 |
|---|---|
| `golden_standard.json` | 每文档 × 每字段的期望值/单位/数据集/口径/锚点/逐字引文（取自 `work/draft.json`，并用 `work/index.json` 文本逐字回查），附 `quote_summary` 与 `coverage` |
| `diff_report.md` | 实际 `comparison_matrix.csv` vs 金标准逐格 diff（value/unit/dataset/metric_scope/locator/quote/status 七维）、可比性闸门、冲突归因、缺口/降级；零差异时也列全表 |
| `version_history.md` | 静态版本线 v0 → v1.0.0 → 本次 p1 与回退点；每次 `build` 在运行时记录追加一行 |
| `run.log` | 真实运行日志（append-only）：build 摘要、资产字节数、引文回查、self_check 结果 |
| `self_check.json` | 退出码、契约键、主产物存在性、逐字引文通过率、文档×字段计数、fallback 兜底、产物哈希、环境声明 |

生成时不改变任何入口/参数/默认路径/退出码，也不触碰四件主产物；`assets.py` 内所有失败都被
捕获并写入 `run.log`，`build` 仍以 `python3 -B scripts/main.py build` 正常结束（exit 0）。

## L. 演练（示例，非正式结果）

```bash
python3 -B scripts/main.py init  --input ./demo/in  --output ./demo/out --work ./demo/scratch
python3 -B scripts/main.py show  --doc D1 --paras 5:12
# Agent 写 ./demo/scratch/draft.json（3 篇 × 4 字段）
python3 -B scripts/main.py check --input ./demo/in  --output ./demo/out --work ./demo/scratch
python3 -B scripts/main.py build --input ./demo/in  --output ./demo/out --work ./demo/scratch
```

预期（示例）：`status=partial docs=3 fields=4 cells=12 reported=9 coverage=0.75 quote_pass=1.0`；CSV 12 行；`comparability` 2 条（units 不可比、dataset 不可比）；`agreement` 1 条冲突，归因 `sample`。

## M. 复用与维护

- 换语料：清空 `work/` 与 `output/`，重跑 `init`，沿用同一字段字典重填工作稿。
- 加论文：`init` 拿新 id → 补 `papers`/`matrix` 行 → `check` → `build`，不必重做旧表。
- 改字段：同步 `references/field_catalog.md` 与本文 G 节，防止两套口径。
- 版本 1.0.0；脚本职责只有抽取、校验、渲染，判断与措辞始终由 Agent 负责。

## N. 附录：三类难案的具体处置演练

### N.1 扫描版 PDF（只有图像、抽不出文字）

先看 `init` 的终端：该文档的 engine 会是 `builtin-zlib`，notes 里出现 "no text layer" 之类的提示，`show` 出来只有空段。这时不要启动"猜测模式"，按下面顺序处理：把该文档写进 `degradations`，说明"扫描件无文字层，需 OCR"；在 `sources` 里保留它的 id 与文件信息；所有本该来自它的格一律写 `reported` 之外的占位（通常是 `unreported`，note 写明"需 OCR，未获得文字"）；把它列进 `pending_human`，并给人工接管一条明确指令（例如"对该 PDF 跑 OCR 后重跑 init，再补 matrix 中该文档的列"）。其余文档不受影响，矩阵照样完整，只是缺一列内容——这比整案失败或编造数值都好。

### N.2 同一篇论文的 preprint 与正式版

两者在 `init` 里会得到两个不同 doc_id，workorder 也可能把它们列为两个文档。正确做法是：分别建列、分别填格；在 `comparability` 里新增一条 `dataset` 维判定，说明"同一研究的两个版本，页码/样本量/NCT 号可能变化，禁止合并计数"；若两版结论不同，把它当作冲突处理并归因到 `method` 或 `dataset`。**不要**只留正式版而悄悄删掉 preprint，也不要因为标题相同就当成同一文档去重——去重会破坏可追溯性。

### N.3 冲突双方都有理，但找不出原因

先回到材料做一次"条件清单核对"：把两篇的剂量、时长、温度、样本来源、指标定义、统计口径逐项并排抄成两列（这活由 Agent 手工做，不交给脚本的自动兜底）。若仍无明显差异，就把该条 verdict 从 `conflicting` 保留下来，attribution 填 `unresolved`，同时在 `pending_human` 写清"需要作者提供更多条件信息"或"需读者复核某表某段"。禁止为了消除报错而强行改判 `partially_consistent`，也不许折中改写原话。评估者更看重"saying I cannot attribute this yet"的诚实，而不是一个编出来的原因。

### N.4 数据图表只能读近似值

图上的柱子高度只能给出"约 62%"这类带约数的写法，并把误差范围写进 `uncertainty`；原文正文若同时给出精确值，以正文为准并在 `note` 写"图值仅供参考"。若全文既无正文值也无图注值，该格只能是 `unreported`。

## O. 交付前的口头边界

向用户/评估者说明结果时，坚持三句话：① 这张表的每一格都来自被标注的原文位置，不是模型记忆；② 哪些格子是空的、为什么空，都写在 `pending_human` 与 `degradations` 里；③ 凡是拿去做数值综合的结论，只在该子集内成立，不推广到全表。若某一步没做完，就在 `result.json.status` 上如实写 `partial`，不必假装 `ok`。这套边界比任何"看起来完整"的表格都更接近科研阅读的真实要求。

## P. 换一个领域的复用提示

把字段字典的 8 个维度当成骨架，而不是教条：材料学可把 `material` 细分出 `substrate`/`dopant`，医学可把 `sample` 拆成 `cohort`/`arm`，机器学习可把 `metric` 拆成 `metric`/`split`。拆分后的新 id 必须同步写进 `fields[].definition` 与 `references/field_catalog.md`，否则同一字段在不同轮次会被填成不同口径。训练/测试划分、随机种子、评价脚本版本这类容易漏的比较条件，建议单独设一个 `protocol` 字段并在每篇都尝试抽取，抽不到就写 `unreported`——"未报告"本身就是有价值的信息。
