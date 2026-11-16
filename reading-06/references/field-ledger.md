# 字段账本：记录契约、条件槽位、单位与来源顺序

这个文件是包的复用半边：它说明一条字段记录由什么构成，以及如何把请求字段清单落成可横向比较的
账本。可以直接裁剪成新案例的 `target-fields.json`，也可以作为字段清单交给 Agent。每次运行都要
把解析后的字典回填到 `result.field_dictionary`。

## 1. 记录键

| 键 | 是否必需 | 说明 |
|---|---|---|
| `field_id` | 必需 | 稳定 slug；输入给出的 id 一律不改写 |
| `field_name` | 必需 | 沿用输入名称；没有则给可读名称 |
| `definition` | 必需 | 本次实际采用的操作性定义 |
| `expected_type` | 可选 | `number` / `range` / `text` / `conclusion` / `table_cell` / `boolean` |
| `unit_hint` | 可选 | 期望单位；与原文不一致时报告，不静默换算 |
| `context_hint` | 可选 | 用于消歧的章节、材料或时间点 |

## 2. 结果的封装结构

`result.json` 顶层有两类键：`output_contract` 要求的（逐键保留，缺值写 null/[]）以及本包的
11 个信封键：

| 信封键 | 内容 |
|---|---|
| `case_id` | 输入案例标识；不可读时为 null |
| `status` | `answered` / `partial` / `input_error` / `insufficient_evidence` |
| `result` | 主结果：`fields`、`coverage`、`field_dictionary`、`corpus`、`method_notes` 等 |
| `claims` | 每条已定字段一条 claim（`claim_id`、`evidence`、`readability`） |
| `sources` | 实际读取的来源清单与 PDF 元信息（含 `quality`） |
| `uncertainties` | 重读可解决的疑点 |
| `pending_human` | 需要人工决策的疑点 |
| `errors` | 结构化错误（stage、path、detail） |
| `changes` | 本次运行的阶段与覆盖情况记录 |
| `degradations` | 降级项（不可读文件、不支持的格式等） |
| `runtime` | 生成时间、工具版本、Python 版本 |

`status` 与 `coverage` 必须自洽：`partial` 时说明哪些字段没落定，`input_error` 时 `fields`
为空数组。

## 3. 值与单位

1. 印刷字符串原样复制：正负号、范围连接符、比较符、样本数、p 值、千分位、末尾零都保留。
2. `units` 单独成键，不要把单位重复塞进 `value`。
3. 离散程度和统计证据写 `statistic`，照原文形式（标准差、标准误、置信区间、p 值或 ns）。
4. 换算时新增 `original_value`、`original_unit`、`conversion_rule`，印刷值不动，例如
   `7.81 g/cm3 -> 7810 kg/m3, 系数 1000`。
5. 差值、比值、百分比变化等导出数标 `inferred`：两个印刷操作数都要有引文，算式写在
   `notes`，不得把导出数写成印刷值。
6. 原文没给数值就是 `not_reported`，不是 `0`。

## 4. 条件槽位

| 槽位 | 放什么 | 示例 |
|---|---|---|
| `sample` | 样本量、模型、材料牌号 | `n = 4`、`C57BL/6, 8 周`、`AA6061-T6` |
| `setting` | 装置、规程、环境 | `压缩, 0.5 mm/min`、`氩气`、`pH 7.4, 37 C` |
| `timepoint` | 读数对应的时间点 | `时效 16 h 后`、`第 14 天`、`稳态` |
| `baseline` | 对照物或基线 | `铸态 210 MPa`、`vehicle`、`未处理对照` |

数值脱离条件就不可用：同一篇论文常在不同条件下给出同一指标。任一槽位缺失都要令
`condition_complete: false` 并追加不确定性。脚本还会对 `reported` 字段做条件-引文绑定检查，
判据见 `references/state-and-claim-codebook.md`。

## 5. 脚本识别的单位

`% ‰ °C K h min s ms us ns d day days week weeks year years nm um mm cm m km mg ug ng pg g kg
mol mmol umol nmol M mM uM nM mL uL L ml ul l mg/L g/L ug/mL ug/ml ng/mL ng/ml mg/kg Pa kPa MPa
GPa bar atm Torr psi N kN mN J kJ W kW mW V mV kV A mA uA Hz kHz MHz GHz rpm g/mol Da kDa bp kb
ppm ppb mol% at% wt% vol% IU CFU copies fold a.u. AU OD S/m mS/cm eV keV meV`

新增单位同时改本清单与 `scripts/checks.py` 的 `UNIT_LEXICON`，正则从那一个列表统一构建。

## 6. 材料类/生命科学论文的起步字段

`sample_size`、`material_or_model`、`processing_condition`、`instrument`、
`primary_metric_value`、`metric_uncertainty`、`significance`、`baseline_or_comparator`、
`author_conclusion`、`limitation`、`hedged_claim`。

这只是模板，不是硬性要求；唯一的硬约束是每个请求的 `field_id` 恰好对应一条结果。

## 7. 读值顺序

按下列顺序尝试，取第一个真正印出"值 + 条件"的来源：

1. 表格单元格（表题、行标题、列标题都逐字保留）；
2. 结果段与图注；
3. 方法段（条件、仪器）；
4. 摘要放最后——它常被压缩，偶尔与结果段不一致。

两个来源对同一字段同一条件给出不同读数，就是 `source_conflict`：两边都保留，交给人工裁定。
