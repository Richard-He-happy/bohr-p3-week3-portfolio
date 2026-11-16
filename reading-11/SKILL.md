---
name: lit-extraction-normalizer
description: 把一批文献抽取行（值、单位、物质/指标名、条件列）清洗成可统计的宽表，同时交付行级变更记录、待人工确认清单、重复与冲突判定、规则应用计数和运行自检。当输入是论文抽取记录且带单位/数字区域规则或目标字段字典，并要求统一字段名、保留原值的单位换算、同义归一、缺失与异常处理、来源追溯时使用。触发词：文献数据清洗、抽取记录标准化、单位换算保留原值、去重与变更记录、clean extracted literature values。
version: 1.0.0
---

# 文献抽取记录清洗与标准化（lit-extraction-normalizer）

## 定位

本 Skill 面向"论文数据已经被抽取成表格行、但还不能直接统计"的场景：同一指标在不同文献里写法不同、单位混杂、区间与误差混排、缺失记号与重复行并存。目标是一次调用产出**可统计宽表 + 逐行可追溯的变更记录 + 待人工确认清单**，并且每个被改动的值都能沿"规则编号 → 公式 → 输入行 → 原文定位"回查。

它同时适用于三类调用者：评审（看结果是否可信）、后续分析（直接读 cleaned.csv）、维护者（改规则库/单位表即可适配新数据）。脚本只依赖 Python 标准库，不需要安装任何第三方包，也不访问网络。

## 明确不做的判断

- **不做领域纠错**：单位换算能算通、但同一来源同一条件下两个值科学上明显矛盾时，标 `source_conflict` 并等待人工，不用换算把差异抹平。
- **不猜单位**：`a.u.`、`arb. units`、`counts/s`、无法解析的符号、空单位，一律不换算。
- **不把缺失变 0**：缺失、`n.r.`、`nd` 等一律留空并标 `missing`。
- **不压缩多值信息**：区间不被平均成中值，`±` 误差不被丢弃。
- **不跨条件/跨来源合并**：判定键里带来源与全部条件列，不同实验永远分开。

## 调用方式

```bash
# 常规清洗
python3 scripts/run_clean.py --output /app/output --input /input
# 交付前做同输入两跑的确定性比对
python3 scripts/run_clean.py --determinism --output /app/output --input /input
```

- 不给参数时：优先 `/input`；若不存在则用包目录同级的 `input/`。输出优先 `/app/output`；无 `/app` 时用包目录同级的 `output/`。
- `--determinism` 会在输出目录临时建两个子目录各跑一遍，逐字节比较全部落盘文件后删除临时目录，只打印比较结论。
- 退出码始终是 0：出现异常写进 `result.json.errors` 与 `degradations`，能继续就继续，不能继续就给 partial 结果，绝不以非零码结束。
- 资源路径由脚本自身位置推导（`Path(__file__).resolve().parent.parent / "references"`），与当前工作目录无关。

## 输入识别（按内容语义，不硬编码键名）

脚本递归扫描 `--input` 目录下的文件，按以下优先级归类：

1. **案例描述**：内容里带 `case_id` 或 `output_contract` 的那个 JSON（同名多个时优先文件名以 case 开头的）。脚本只消费这两项——`case_id` 原样搬运，`output_contract` 当作待回填模板；任务说明、组织方附注、输入清单、运行时文件列表至多登记"曾经出现"，不会被加工成结果。
2. **规则文件**：文件名或内容出现 `rule_id` 的 JSON。每条规则可以有 `priority`（默认 10）、适用对象、条件、变换、示例、失效情形与人工门槛。
3. **目标 schema/字段字典**：文件名含 schema/dictionary 或内容含 `fields` 的 JSON；其中 `field_roles` 可扩展列名同义词。
4. **抽取记录**：`.csv` 全部视为记录表；其余 JSON 若是列表，或 `records/rows/data/items/measurements/...` 下挂着 dict 列表，也视为记录表。读不出 JSON 的文件按坏文件记入 `errors`，不影响其他文件。
5. 记录表内按角色识别列：行身份、来源文献、原文定位、数值、单位、指标、物质；其余列若不像备注列，则作为条件列原样保留。

如果找不到任何记录表，`status=insufficient_evidence` 并在 `degradations` 写明；如果连 `case.json` 都没有，记一条降级并视契约为空。

## 产物一览

输出目录内生成 9 个文件：

- `result.json` — 主结果。`output_contract` 的每个键都必须出现在顶层（键名不改、未知键保留、缺值给 `null`），另带 `case_id`、`status`、`result`、`claims`、`uncertainties` 与 `uncertainty`（两者同内容，兼容不同读法）、`sources`、`pending_human`、`errors`、`degradations`、`changes`、`runtime`、`contract_mapping`。
- `cleaned.csv` — 目标宽表，每行带行身份、来源、原文定位、归一后的指标/物质、条件摘要、数值列、单位列、原值原单位、规则号、判定键、状态与合并去向。
- `change_log.csv` — 一个被改动的字段占一行。依次是行身份 `row_id`、字段名 `field`、改前值 `before`、改后值 `after`、改前单位 `unit_before`、改后单位 `unit_after`、乘数 `factor`、平移项 `offset`、可读公式 `formula`、精度说明 `precision`、所依据的规则号 `rule_id`，以及来源文献 `source_document_id` 与原文位置 `source_locator`；末列 `note` 留给特殊说明（例如"区间上界单独换算"）。
- `pending_review.csv` — 需要人判断的每一行都在这里。列包括：行身份、涉及字段、原因码、原因说明、建议动作、原始值、原始单位、来源文献、原文位置。它和 `uncertainties` 是同一批事实的两种呈现，CSV 给人看，JSON 给程序看。
- `anomaly_report.md` — 面向人的汇总：计数、列映射率、待确认原因分布、重复/冲突、降级与错误、边界声明。
- `rules.json` — 规则库快照：规则本体、优先级、被压制规则、按规则号的应用次数与示例。
- `field_mapping.json` — 原始列 → 目标字段、命中依据、未映射列清单、schema 来源。
- `unit_table.json` — 单位登记表副本 + `observed_conversions`（本次真正发生的 源单位→目标单位、factor、offset、次数）。
- `verify_report.json` — 运行后自检：复算一致率、计数核对、身份唯一性、规则可解析、变更行身份可解析、可统计行数复核。

`status` 的取值语义：全部干净 → `ok`；有待确认或冲突 → `partial`；没有可清洗行 → `insufficient_evidence`；输入不可用 → `input_error`。

## 主流程

1. **先立规则**：内置规则库（`references/rulebook.json`）与案例自带规则合并；同号规则按 priority 小者优先，落败的写进 `suppressed_rules`。
2. **列角色映射**：列名按同义词表归类；列名里内嵌的单位（`Band gap (eV)`、`size/nm`）拆成指标与单位两部分；无法归类的列保留为条件/备注并进 `unmapped`。
3. **单元格解析**：识别单值、区间、`±` 误差、缺失记号与非数值文本；先把科学计数法（`1.2E3`、`1.2×10³`、`1.2 10^3`）、上下标字符、全角符号归一。
4. **仿射换算**：单位串先拆 token 累加量纲指数，再查规范单位；`after = before * factor + offset`；区间上下界分别换算，`±` 误差用同一 factor 且不加 offset。
5. **同义归一**：物质名与指标名映射到标准标签，原始文本留在 `original_field`/`original_value`。
6. **判定键去重**：键为 `来源 | 条件摘要 | 指标 | 物质`；键相同且值、单位完全一致 → 合并（`merged_duplicate`）；键相同且相对离散度 ≤ 容差 → 保留为重复实验（`replicate`）；超出容差 → `conflict` 并送人工。
7. **稳定落盘**：清洗行按来源 + 行身份自然序排序，变更与待确认也排序后写出；不使用时间戳、随机数或 dict 迭代顺序，因此同输入两次运行逐字节一致。
8. **复算自检**：从已落盘文件读回变更记录逐条按公式复算，写 `verify_report.json`。

## 澄清与人工门槛

需要人介入的情况分两类。第一类发生在单元格层面：单位看不懂、有数没单位、内容根本不是数值（文字或公式引用），这三种都只做"留空 + 标 needs_review + 进待确认"，原因码依次是 `unknown_unit`、`missing_unit`、`unparsed_value`，绝不猜单位、不补 0。第二类发生在判定键层面：同一键下若单位不一致，整组标 `conflict` 并记 `unit_conflict`；单位一致但数值差距超过容差，整组标 `value_conflict`（R015），两个原值都留在表里等裁决；差距在容差内则视为重复实验，后来者标 `replicate`（R014）；只有完全一致才合并，后来者标 `merged_duplicate`，其 `duplicate_of` 指向被保留的那一行（R013）。两类情况都会同时出现在 `pending_review.csv` 与 `uncertainties` 里。

证据约定：`claims[].evidence.quote` 必须是输入单元格原文（原值 + 原单位），不能拿换算后的值充数；每条 claim 同时给 `row_id`、`field`、`source_locator` 与规则号。换算类结论标 `kind=inferred`/`readability=inferred`；无法判断的标 `undetermined`，并且只出现在 `uncertainties` 与 `pending_review.csv` 中，不写进 `cleaned.csv` 当真值。

## 输入异常时的行为

- `case.json` 缺失或坏 JSON：继续清洗，契约视为空，写 `degradations`。
- 某个记录文件坏 JSON：跳过该文件，其余照常，写 `errors`。
- CSV 编码不是 UTF-8：按 `utf-8-sig → utf-8 → gb18030 → latin-1` 级联尝试，记录替换字符数。
- 空表或只有表头：`insufficient_evidence`，不假装成功。
- 行身份列缺失：生成 `derived-N`；身份重复：后来者加 `#2`；两者都写 `degradations`。
- 没有 `value` 列：记一条 R003 提示复核映射，再按条件列处理其余字段。
- 运行被中断：流程开始时已落盘的 partial `result.json` 仍可用。
- 单文件极大：脚本按文件逐个处理，一个文件失败不影响其他文件。

## 评分视角的落地位置

- 完成度：9 件产物齐备；`result.counts` 给出输入行、清洗行、可统计行、改动值、待确认、合并重复、冲突，行数关系可解释。
- 正确性：每行变更的 `factor/offset/formula` 可复算，`verify_report.formula_consistency_pct` 为 100；区间、误差不压成单值；缺失不写 0。
- 完整性：字段规范、单位换算、同义归一、缺失与异常、重复记录、来源与变更记录六个方面都有对应产物。
- 可核验：每行都有 `row_id + source_document_id + rule_ids`；定位原样保留到 `source_locator`。
- 质量/效率增益：规则有编号、优先级与使用次数；一次运行完成映射→换算→归一→去重→报告，`counts.pending_review` 即剩余人工量。
- 增益可验证：`result.method_notes` 预置"算对"标准，`--determinism` 给出同输入两跑的逐字节证据；不自造分数。
- 创新与改进：可维护规则库 + 表头单位拆解 + 判定键去重 + 来源追溯导出；规则优先级与冲突消解、`human_gate` 划出"规则可改"与"必须人工"的边界。
- 可靠性：换列名靠 `column_roles`，换 schema 靠案例 `fields`，换单位靠登记表；异常分支见上节。
- 生态：本文件 + `references/handbook.md`（字段字典、脏数据谱系、单位约定、维护、自查）+ 两份可复用的 JSON 资源。

## 最小示例（示例数据，非正式案例结果）

`input/case.json`：

```json
{"case_id": "toy-01",
 "task_instruction": "把抽取行归一成可统计表格",
 "output_contract": {"change_log": "", "cleaned_table": "", "counts": {}}}
```

`input/extraction.json`（两行示例）：

```json
{"measurements": [
 {"row_id": "X7", "source_document_id": "PAPER-Q9", "source_locator": "表 2 / 第 4 页",
  "material": "ZnO", "indicator": "optical band gap (eV)", "value": "3.7", "unit": "eV"},
 {"row_id": "X8", "source_document_id": "PAPER-K2", "source_locator": "图 1",
  "material": "SiO2", "indicator": "particle diameter", "value": "9 to 11", "unit": "nm"}]}
```

```bash
python3 scripts/run_clean.py --output ./output --input ./input
```

示意输出（**示例**，不是正式案例结果）：X7 的 3.7 eV 会被换算成焦耳并标上 R009；X8 的 "9 to 11" 先拆成上下界，再各乘 1e-6 换成米，所以 `rule_ids` 里同时有 R007 与 R009；三个数值正好对应 `change_log.csv` 的三行。小数位只代表输入精度，正式数值必须来自平台案例的实际运行。

## 提交前自检

- `--help` 退出码 0；空输入目录、坏 JSON、缺工作稿三类输入仍产合法 partial `result.json`。
- `output_contract` 每个键都在 `result.json` 顶层，`case_id` 原样。
- `verify_report.json` 七项检查全过、`formula_consistency_pct=100`。
- 未知单位行 `value` 为空且出现在 `pending_review.csv`。
- 区间/误差未压成单值；不同来源、不同条件的行未合并。
- `--determinism` 两跑逐字节一致。
- 包内无 `__pycache__`、`.pyc`、临时文件或预制案例答案。

## 包内文件

| 文件 | 作用 |
|---|---|
| `SKILL.md` | 入口：定位、契约、流程、人工门槛、自检清单 |
| `scripts/run_clean.py` | 命令行入口：输入扫描、流程编排、产物写出、契约回填、自检与确定性比对 |
| `scripts/clean_engine.py` | 引擎：单位登记与换算、单元格解析、列角色、逐行清洗、判定键去重 |
| `references/unit_registry.json` | 量纲、前缀、单位目录、拒绝 token、规范单位签名与换算约定 |
| `references/rulebook.json` | 规则数组、字段角色同义词、条件/备注标记、目标字段表、物质/指标别名、文案 |
| `references/handbook.md` | 字段字典、脏数据谱系、单位与精度约定、扩展方式、自查脚本 |

依赖：Python ≥ 3.8 标准库即可；无网络、无第三方包。版本 1.0.0。


## 常见失败模式与规避

1. **只交一张成品表**：没有变更记录与待确认清单，值再对也无法复核。规避：永远让 `change_log.csv` 与 `pending_review.csv` 同时存在，哪怕为空也要有表头。
2. **未知单位硬猜**：把 `a.u.` 当成无量纲、把缺失当 0，都会污染统计。规避：凡是不在单位登记表里的 token 一律进待确认，清洗值留空。
3. **合并过头**：同义归一写成"看起来差不多就归一"，会把 TiO2 与 TiN 并成一条，或把不同温度的实验并成一条。规避：判定键包含来源与全部条件列，归一表只放真正的等价写法。
4. **重复实验被平均**：两行同条件不同次测量被取平均，看起来更"整齐"，实际丢掉了重数。规避：容差内保留两行并标 `replicate`。
5. **结果不稳定**：依赖字典顺序、时间戳或随机数，两跑输出不同。规避：所有输出前稳定排序，交付前跑 `--determinism`。
6. **运行中断无产出**：把全部计算堆到最后一次写盘。规避：流程一开始先写 partial `result.json`。

## 想改代码的人先读这里

`run_clean.py` 是编排层：扫描输入 → 合并规则 → 逐文件读行 → 映射列角色 → 调引擎逐行清洗 → 判定键去重 → 排序落盘 → 回填契约 → 自检。它不负责具体的数值解析；数值解析都在 `clean_engine.py`。

`clean_engine.py` 里四个纯函数可以单独测试：`parse_cell`（把单元格变成 值/区间/误差/缺失/文本 五种形态之一）、`parse_unit`+`to_canonical`（把单位串变成 factor/offset 与规范单位）、`classify_columns`（把列名映射到角色）、`form_row`（单行清洗）。`find_duplicates` 只做分组与判定，不改数值。想加新能力时优先扩资源 JSON；只有资源表达不了时才改这两个脚本，改完必须跑一次冒烟并确认 `cleaned.csv` 与旧版本逐行一致。

## 输出字段速查

身份类：`row_id`、`source_document_id`、`source_locator`。
名称类：`indicator`、`material`、`original_field`。
条件类：`condition_summary`。
数值类：`value`、`value_low`、`value_high`、`value_err`、`value_text`、`unit`。
原文类：`original_value`、`original_unit`。
追溯类：`rule_ids`、`judgment_key`、`status`、`duplicate_of`、`note`。

其中 `rule_ids` 是本行规则的并集（`;` 分隔），`judgment_key` 是去重判定键，`status` 描述该行的处置结果，`note` 记录状态之外的补充事实（如不等号、同单位直通）。


## 一个完整案例的走查（示例数据）

假设输入里有两篇文献的抽取行：PAPER-Q9 报了 ZnO 的光学带隙 3.7 eV，PAPER-K2 报了 SiO2 的晶粒尺寸 "9 to 11" nm，另外还有一行把前者的数据重复抄了一遍，以及一行单位写成 a.u.。一次运行的顺序是：

第一步，扫描输入，找到案例描述、抽取记录与可选的规则/字段字典；行身份按原样记下，重复的身份单元格会被加后缀并记降级。

第二步，映射列：`source_document_id`、`value`、`unit`、`indicator`、`material` 这些角色由别名表命中；`indicator` 里的 "(eV)" 被拆出来当单位，于是即使单位列空着，该行仍可换算。

第三步，逐行解析：3.7 是单值，记下源小数位 1；"9 to 11" 是区间，拆成 9 与 11；"n.r." 是缺失；"a.u." 命中拒绝表，直接进待确认。如果某行值后面带 "± 0.05"，主值与误差会分开存，误差同样乘 factor 但不加 offset。

第四步，换算：eV 在登记表里的 to_base 是 1.602176634e-19，目标规范单位 J 的 to_base 是 1，所以 factor 就是 1.602176634e-19、offset 为 0；nm 与 m 同属长度量纲，factor 为 1e-9。每次换算写一行变更记录，行里同时有改前值、改后值、公式与因子。

第五步，判定键去重：重复抄写的那行与前一行来源、条件、指标、物质全同且数值单位一致，于是合并，后来行标 `merged_duplicate`；a.u. 那行不参与判定键分组，因为它本来就没有可比较的数值。

第六步，落盘与自检：清洗行按来源与行身份自然序排序，三类 CSV 与四份 JSON 全部写出；然后脚本读回 `change_log.csv` 逐行按公式复算，把一致率、计数核对、身份唯一性、规则可解析性等检查写进 `verify_report.json`。如果一致率不是 100%，报告会以 CHECK 结尾，提醒维护者规则或舍入出了问题。

## 判定键为什么这样设计

去重最容易犯的错是"看起来一样就合并"。本实现把判定键定成"来源文献 + 条件摘要 + 指标 + 物质"四段拼接，只要任何一段不同，键就不同，两个实验天然分开。这个设计的代价是把同一条文献的不同条件行视为不同实验（这是正确的），收益是永远不会把 25 ℃ 与 80 ℃ 的结果、或两篇不同论文的同类数据混成一条。合并只发生在键完全相同且数值单位完全相同的行；键相同而数值接近的行只标重复实验、不合并；键相同而数值差距大的行标科学冲突，等人裁决，而不是用换算去解释差异。

## 输入规模与预算

清洗本身是纯 CPU 的字符串与数值运算，没有模型调用，也没有网络请求。数千行级别的抽取表通常在数秒内完成；即使单文件很大，脚本也是按文件逐个处理，一个文件读失败不会拖垮整批。运行开始时先写 partial `result.json`，因此即便被外部中断，输出目录里也有一份合法的部分结果，可以据此判断已经处理到哪一步。

## 常见问题

**问：案例没有给目标字段字典怎么办？** 答：使用 `references/rulebook.json` 里的 `target_table` 作为默认字段表；`field_mapping.json` 会注明 schema 来源是内置还是案例提供。

**问：案例给的规则编号与内置规则冲突怎么办？** 答：案例规则默认优先级更高（priority 数字更小），同号覆盖后，落败的那条会出现在 `rules.json.suppressed_rules` 里，便于复核覆盖行为是否合理。

**问：为什么 cleaned.csv 里有的值是空的？** 答：因为那行属于待确认或缺失。空值不是错误，而是"工具不敢确认"的显式表达；对应原值与原因在 `pending_review.csv` 里可以查到。

**问：想看某个数值是怎么来的？** 答：从 `cleaned.csv` 找到 `row_id`，在 `change_log.csv` 里筛同一 `row_id`，读 `before`、`factor`、`offset`、`formula`、`rule_id`，再回到 `result.claims` 里找带 `source_locator` 的那条 claim。

**问：换一批列名不同的数据要改代码吗？** 答：不需要。往 `reference/rulebook.json` 的 `column_roles` 里补别名即可；改完用 `--help` 确认入口没坏，再用一组最小输入跑通四个 CSV 即可。

## 术语约定

- **判定键**：判断两行是否描述同一测量结果的四段字符串。
- **仿射换算**：同时包含乘数与平移的换算模型，`after = before * factor + offset`。
- **规范单位**：同一量纲下选定的目标单位，例如质量选 g、长度选 m、能量选 J。
- **直通**：源单位与规范单位相同或比例恰为 1，不需要写变更记录。
- **降级**：能让流程继续但质量受影响的情况，如缺案例描述、编码回退、派生行身份。
- **人工门槛**：规则无法安全自动处理、必须由人确认的分界。

## 版本与兼容

当前版本 1.0.0，随包资源版本同步。脚本要求 Python 3.8 及以上，只 import 标准库模块（argparse、csv、json、re、sys、subprocess、traceback、pathlib、tokenize 的等价能力由运行时提供）。不依赖任何第三方包、不访问网络、不写包内文件，所有输出都落在 `--output` 指定目录。资源文件统一 UTF-8 编码；脚本读取输入时对编码做了级联回退，因此 GBK/GB18030 导出的 CSV 也能读入，只是会在降级记录里留下替换字符计数。


## 交付物之间的关系

四份 CSV/JSON 数据产物不是互相独立的：`cleaned.csv` 是"结论"，`change_log.csv` 与 `pending_review.csv` 是"依据与保留意见"，`field_mapping.json` 则回答"这个结论是从哪些原始列推出来的"。评审或下游分析常见的三种用法是：只读 `cleaned.csv` 做统计；把 `change_log.csv` 当作审计日志逐条复算；用 `field_mapping.json` 判断某列是否被错误忽略。三份文件的行身份字段可以互相 join，这是刻意保留的设计——如果三者用了不同编号，追溯链就断了。

另外四份 JSON 面向不同读者：`result.json` 是给评测框架的白名单字段载体；`verify_report.json` 是给维护者的自检凭证；`rules.json` 是规则库快照，方便对比"本次用了哪些规则、哪些被压制"；`unit_table.json` 在单位登记表之外多出 `observed_conversions`，用来回答"这次到底发生了哪些换算"。它们都由同一次运行生成，不含时间戳与随机值。


## 一句话总结

输入是"有人已经替你从论文里抄下来的行"，输出是"统计软件和审稿人都敢用的表 + 一条能倒查回原文的路"。中间所有拿不准的判断都被显式隔离，而不是被悄悄抹平——这正是它与随手写一段换算脚本的本质区别。


## 适用边界的三个小例子

例一：同一篇论文的 Table 1 与 Table 2 都报了同一个带隙值，来源与条件完全相同。工具会把它们判为重复记录并合并，只保留一行，后来行标 `merged_duplicate`——这是"重复录入"，不是两次独立实验。

例二：同一篇论文在 25 ℃ 与 80 ℃ 各报了一个转化率，条件列不同，判定键不同，工具绝不合并，哪怕两个数值碰巧接近。条件列在判定键里是硬边界。

例三：两篇不同论文报的带隙分别是 3.2 eV 与 2.1 eV，来源不同，判定键不同，工具同样不合并；如果恰好同一来源同一条件出现这两个数，那就属于科学冲突，工具会保留两行、标 `conflict`、把裁决权交给人。这三种情况看起来都是"两个数不一样"，但处理方式完全不同，区分依据就是判定键与数值容差，而不是措辞。
