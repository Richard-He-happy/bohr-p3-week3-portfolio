---
name: manuscript-blueprint-audit
version: 1.1.0
description: Audit the structural blueprint of a full manuscript and hand back an executable edit order. Reads the real file under /input, cuts it into chapter/paragraph/sentence locators, then checks six fixed dimensions (research-question alignment, section skeleton, claim-evidence chain, paragraph hand-offs, repetition, conclusion scope) and emits only findings whose quote is anchored back to the source text, each paired with one of six operations (move/merge/split/narrow/delete/insert). Diagnosis only - the manuscript itself is never rewritten.
license: MIT
tags: [academic-writing, structural-audit, claim-evidence-map, edit-order]
---

# 论文蓝图审计（manuscript-blueprint-audit）

## 0. 一页速览

这个 Skill 只做一件事：把一篇完整稿件的**结构问题**定位到章节 / 段落 / 句子，并给出作者可以照着改的动作单。
它不写新稿、不润色句子、不补科学内容、不生成文献或数据。

- 输入：`/input/case.json` + `task.md` + 稿件（md / txt / docx / pdf / html / tex / csv）。
- 输出：`/app/output/` 下 6 个可编辑产物 + `result.json`（回填 `output_contract` 全部字段）
  + 5 个可核验资产（`golden_standard.json` / `diff_report.md` / `version_history.md` /
  `run.log` / `self_check.json`，见第 17 节）。
- 判定依据：每条发现必须先有**原文逐字引用 + locator + 字符区间**，没有引用就不输出（宁缺勿造）。
- 运行特性：纯标准库、不联网、不依赖 CWD、0 次模型请求、退出码恒 0。

## 1. 触发与不触发

**应当触发**：用户手里有一份完整或接近完整的稿件，要求「看看结构哪里不对 / 逻辑链断在哪 / 章节顺序要不要调 /
有没有重复 / 结论是不是说大了」，或者要求「指出问题在第几章第几段、该怎么改」。

典型说法：结构诊断、逻辑优化、论文架构、章节顺序、论证链、论点论据、重复内容、结论收窄、审稿意见里的结构问题。

**不应触发**：

| 请求 | 为什么不做 |
|---|---|
| 「帮我把这篇改一版」 | 会产出一篇对照不上的新稿，与本题「不另起改写稿」冲突 |
| 「语言润色 / 降重改写」 | 语言层问题不在六维度内，本 Skill 明确不为风格偏好出条目 |
| 「这篇的科学结论对不对」 | 只判断表述与数据范围是否匹配，不评判科学真伪 |
| 「补写方法和参考文献」 | 需要作者提供事实，本 Skill 不代写 |

## 2. 运行契约

```bash
python3 -B scripts/audit.py --input /input --out /app/output          # 主流程
python3 -B scripts/audit.py --input /input --out /app/output --check   # 只复核已有产物
python3 -B scripts/gates.py --work /app/output --input /input          # 独立复核（等价入口）
python3 -B scripts/gates.py                                            # 规则表自检
```

- `audit.py`：输入发现、分段、六维度检测调用、产物渲染、契约回填、自检。
- `gates.py`：被 `audit.py` 导入的检测引擎（文本工具、引用锚点、六个门、动作构建、覆盖表、契约回填、复核器）。
- 两个脚本都只用 Python 标准库；资源路径用 `Path(__file__).resolve().parent` 解析，与 CWD 无关。
- `audit.py` 第一步先落盘**合法 partial** `result.json`，最后无条件 finalize 覆盖；任何异常都被捕获，退出码恒 0。
- finalize 阶段由 `scripts/assets.py` 额外写入 5 个可核验资产（见第 17 节）；这是**加法**，
  不改变上面三条命令的调用方式，也不改变 6 个主产物的文件名与 schema。

## 3. 制品清单

| 文件 | 面向谁 | 内容 | 必需 |
|---|---|---|---|
| `structural_review.json` | 复核者 / 下游工具 | 主结果：`dimension_coverage`、`findings`、`actions`、`grounding`（含字符区间）、`closure_matrix` | 是 |
| `edit_plan.md` | 作者 | 按 P1→P3 排好的动作单：位置、原文、判断、依据、动作、风险 | 是 |
| `outline_after.md` | 作者 | 建议后结构：章节顺序、功能、篇幅占比、结构处置 | 是 |
| `argument_map.json` | 作者 / 复核者 | 论点—论据映射与四环闭环矩阵 | 辅助 |
| `consistency_report.md` | 复核者 | 篇幅占比、引用与图表解析、重复统计、截断与降级 | 辅助 |
| `pending_human.json` | 作者 | 无法判断项与需要补的材料 | 辅助 |
| `result.json` | 平台 | 契约字段 + 状态、来源、不确定性、错误、降级、变更记录、指标 | 是 |
| `golden_standard.json` | 复核者 | 金标准：按 `output_contract` 与任务要求逐项列 expected 字段/章节/修改项，每项带 locator 与逐字 quote | 是 |
| `diff_report.md` | 复核者 | 实际产物 vs 金标准逐项对照：达标/偏差/缺失/待生成 + 原因 | 是 |
| `version_history.md` | 维护者 / 评审 | 静态版本记录 v0 → v1.0.0 → v1.1.0（改了什么、为什么、如何回退）+ 本次运行段 | 是 |
| `run.log` | 复核者 | 真实运行日志：每阶段耗时、退出码契约、降级、异常 | 是 |
| `self_check.json` | 复核者 / 下游工具 | 机器自检回执：契约键/主产物/引文命中/计数一致/空坏输入兜底/退出码恒 0 | 是 |

不产出 `manuscript.md` / `rewrite.md` / `revised.md` 等整篇改写文件；复核器会把这类文件判为不合规。

## 4. 定位符与分段规则

| 层级 | 形式 | 例子 | 生成方式 |
|---|---|---|---|
| 章节 | `Cnn` | `C03` | 标题行（Markdown `#`、编号标题、规范章节名）计数；无标题稿件整体记为 `C01` |
| 段落 | `Cnn-Pnnn` | `C03-P002` | 章内空行分隔的正文块，词数 < 3 的块丢弃 |
| 句子 | `Cnn-Pnnn-Snn` | `C03-P002-S01` | 句末标点切分，跳过 `et al.` `Fig.` 等缩写点与小数 |

章节角色由标题识别：`abstract / introduction / related / method / result / discussion / conclusion /
references / ack / appendix`，其余记为 `body`。角色识别词表在 `references/ruleset.json` 的 `roles`，中英双语。

## 5. 六维度审计矩阵

固定六个 key，缺一不可；每个维度输出 `findings`、`no_issue_with_evidence`、`degraded_by_error`
或 `not_assessable`（无正文时），后两者都带检查证据，不代表漏项。

| key | 看什么 | 本 Skill 的触发规则 | 默认动作 |
|---|---|---|---|
| `research_question_alignment` | 研究问题是否被提出并贯穿；贡献主张是否与实际工作一致 | RQ1 无研究问题句；RQ2 问题关键词 ≥50% 未进结果/讨论/结论；RQ3 贡献句关键词 ≥60% 未进结果 | insert / narrow |
| `section_structure` | 章节完备性、顺序、参考文献章可用性 | SEC1 全文无标题；SEC2 缺 introduction/method/result/conclusion；SEC3 method 晚于 result 或 result 晚于 discussion/conclusion；SEC5 有参考文献章但无编号条目 | insert / move |
| `argument_chain` | 判断性论断是否有可指认论据；引用与图表能否回溯 | ARG1 段内有主张句但零引用/数值/图表指向；ARG2 正文引用编号在文献表缺号；ARG3 引用图表无对应图题 | insert |
| `paragraph_relations` | 相邻段是否有显式关系；单段是否混装多种功能 | PAR1 同章相邻段（各 ≥55 词）词项 Jaccard <0.05 且段首无过渡词；PAR2 段 ≥120 词且含 ≥2 数值句 + ≥1 主张句 | insert / split |
| `duplication` | 同义重复、跨章节重复、整句重复 | DUP1 段落 8 词 shingle Jaccard ≥0.30（跨章且 ≥0.5 记为高）；DUP2 归一化后 ≥55 字符的同一句出现 ≥2 次 | merge / delete |
| `conclusion_boundary` | 结论是否越出数据与设计允许范围 | BND1 方法与结果只有相关性表述、无干预/对照设计，结论句却用因果动词且无限定；BND2 结论句含绝对化措辞且无限定 | narrow |

规则编号与阈值一一对应 `references/ruleset.json`；改阈值或改措辞都只改那个文件，脚本不内嵌文案。

## 6. 发现与动作的数据形状

```json
finding = {
  "finding_id": "F01",
  "dimension": "argument_chain",
  "severity": "high|medium|low",
  "locator": "C04-P002-S01",
  "quote": "扎在原文里的逐字片段",
  "diagnosis": "这条结构问题是什么",
  "evidence_for_judgment": "可复算的计数依据",
  "confidence": "high|medium|low-medium"
}

action = {
  "action_id": "A01",
  "finding_id": "F01",
  "operation": "move|merge|split|narrow|delete|insert",
  "from_locator": "C04-P002-S01",
  "to_locator": "C05",
  "expected_effect": "做完这一步，读者能获得什么",
  "risk": "这一步的副作用",
  "priority": "P1|P2|P3",
  "executable": true
}
```

硬约束：一条 finding 只配一条 action；`operation` 只能取六个枚举值；`from_locator` 与 `expected_effect` 必填；
不允许出现「建议加强论证」「语言可以更简洁」这类不可执行条目——它们既没有落点也没有动作。

## 7. 证据三段式：引用 → 锚点 → 判断

本 Skill 与「给一堆写作原则」的分界线在这里：**判断永远写在引用之后**。

1. **取引用**：从被判定的原文块里截取片段（默认 150 字符，逐级放宽到 450）。
2. **锚定**：在空白归一化的全文里查找该片段，命中则记录 `start` / `end` 字符区间；尾部漂移会逐步缩短探针回收，
   仍不命中就**丢弃整条 finding**，并写入 `errors.stage=anchor`。
3. **写判断**：只有拿到 `quote + locator + span` 之后才组装 `diagnosis` 与 `evidence_for_judgment`。

因此 `structural_review.json` 的 `grounding` 恒为：

```json
{"findings_total": 3, "quote_verbatim_hit": 3, "hit_rate": 1.0,
 "dropped_unverifiable": 0, "anchors": [{"finding_id": "F01", "rule": "SEC2", "start": 402, "end": 512}]}
```

`anchors` 里的整数区间让复核者可以直接切原文核对，不用重新猜位置。

## 8. 闭环矩阵与引用结构

`argument_map.json` 除了逐段 `claim → evidence` 配对（`supported` / `unsupported`），还输出四环闭环矩阵：

| 环节 | 判据 | 状态 |
|---|---|---|
| question → method | 两端词项交集 ≥ max(2, 15% 左端词项数) | `linked` / `thin` |
| method → result | 同上 | `linked` / `thin` |
| result → conclusion | 同上 | `linked` / `thin` |
| question → conclusion | 同上 | `linked` / `thin` |

两端之一没有可解析文本时记 `missing_block`，要求作者补齐章节。`unsupported_chains` 计数即 ARG1 的证据来源。

## 9. 执行顺序与断点

```
写 partial result.json
  → 读 case.json（缺失/坏 JSON 不中断）
  → 扫描 /input，识别稿件（最长可解析文本）
  → 分段成 C/P/S 定位符
  → 六个门依次执行（单门异常只降级该维度）
  → 构建动作
  → 渲染 6 个产物
  → 契约回填 → 写 result.json → 读回自检 → 必要时把 ok 降为 partial → 再写一次 result.json
```

重复运行幂等（覆盖写）。断点在第一步：即使后面全崩，`result.json` 仍然合法且契约字段存在（置 null / []）。

## 10. 输入发现与语义键

1. `/input/case.json`；缺失时递归找 `case*.json`；`case_id` 依次取 `case_id` / `id` / `caseId`，全无则 `case-unknown`。
2. `output_contract` 原样保留键名：键名做去符号小写后精确匹配，失败再退化为包含匹配；仍匹配不到就置
   `null`（列表字段置 `[]`）并写入 `contract_unfilled_keys`，绝不臆造值。
3. `task.md` / `guide.md` / `readme.md` 记为 `instruction`，不作为稿件；其余按扩展名分类，非文本材料记为 `non_text_material`。
4. 多个可解析文本时取最长者为主稿，并写一条 `multiple_materials` 待确认项。
5. `organizer_workorder` / `scope` 一类键逐项回报：结构类记 `done`，导出/PDF 或整篇改写类记 `not_applicable` 并说明原因。

## 11. 降级阶梯

| 情况 | 处置 | `status` |
|---|---|---|
| `case.json` 缺失 / 坏 JSON | 继续跑，契约字段置 null/[]，记 `errors.case_parse` | `input_error` |
| 无任何可解析正文 | 不编造诊断，六维度记 `not_assessable`，`pending_human` 说明 | `input_error` |
| 正文过短（<60 词或 0 段） | 结构诊断不可行，写明词数与段数 | `insufficient_evidence` |
| PDF 无文本层 / 无 `pdftotext` | 记 `errors.pdf`，其余材料照常 | `partial` |
| 稿件末字符不是句末标点（且 >1500 字符） | 判疑似截断；缺章判断降级为待确认，不再断定「缺章节」 | `partial` |
| 缺章节 / 无参考文献 / 图表无图题 | 照常输出 finding——这类正是被考察的结构缺陷 | `ok` |
| 单条规则抛异常 | 只把该维度标 `degraded_by_error`，其余维度照常 | `partial` |
| `gates.py` 或规则表不可用 | 六维度全部降级，`compliance_checks.engine_loaded=false` | `partial` |
| 引用片段无法锚定 | 丢弃该条 finding，计入 `dropped_unverifiable` | `partial` |

## 12. 自审计不变量

写完产物后，脚本会重新从磁盘读回 `structural_review.json` 与 `result.json` 逐项核对，结果写进
`result.json.self_audit`：

| 不变量 | 判据 |
|---|---|
| `quotes_present` | 每条 finding 的 `quote` 非空 |
| `six_dimensions` | `dimension_coverage` 恰好六个 key |
| `coverage_status_enum` | 状态值只能取四个枚举值之一 |
| `anchor_spans_consistent` | `end - start` 等于 `quote` 长度 |
| `finding_action_join` | 每条 action 的 `finding_id` 都能在 findings 中找到 |
| `actions_well_formed` | `operation` 在六值枚举内，`from_locator` 与 `expected_effect` 非空 |
| `no_rewrite_file` | 不存在 `manuscript.md` / `rewrite.md` / `revised.md` |
| `case_id_kept` | `case_id` 非空 |
| `status_declared` | `status` 非空 |
| `contract_keys_present` | `output_contract` 的每个键都出现在 result.json 顶层 |

自检不通过时，`status` 从 `ok` 降为 `partial`，不会静默通过。这套检查同时作为 `--check` 入口对外提供。

## 13. 评分点对应

| 评分点 | 落地方式 |
|---|---|
| 任务完成度 | 三件主产物齐备；每条 action 可执行；workorder 逐项回报 |
| 结果正确性 | `hit_rate` 恒 1.0；diagnosis 只由已锚定的引用触发；规则未命中即声明 `no_issue_with_evidence` 并给计数 |
| 结果完整性 | 六维度固定枚举，缺项必须带「检查了什么、计数多少」的证据 |
| 可核验性 | 每条 finding / action 带 locator 与字符区间；`evidence_for_judgment` 给可复算计数 |
| 质量增益 | `metrics.findings/actions/quote_hit_rate` 与六维度检出数构成同口径对照 |
| 效率增益 | `metrics.estimated_revision_rounds`、`action_ratio_per_finding`（标注为估算，非实测） |
| 创新证据 | 字符区间锚定、`argument_map` 论点—论据映射、四环闭环矩阵 |
| 可靠性 | 第 11 节降级阶梯 + 第 12 节自审计 |
| 生态价值 | 六维度定义与规则表（`references/dimensions.md`）、可替换文案的规则库（`references/ruleset.json`）、最小示例（`references/sample.md`） |

## 14. 常见误用

1. **拿它当润色工具**：它不会改句子；要润色请用别的工具。
2. **要求「多给点建议」**：没有 locator 与引用的建议会被丢弃，这是设计而不是偷懒。
3. **把 `no_issue_with_evidence` 当成漏项**：那是「检查过、没命中」，括号里有检查对象计数。
4. **在短稿上期待完整诊断**：<60 词的输入会返回 `insufficient_evidence`。
5. **把截断稿的「缺章节」当结论**：疑似截断时缺章判断会降级为待确认。

## 15. 最小示例入口

`references/sample.md` 给出一组最小输入、调用命令与（标注为示例的）示意输出，用来说明接口与产物结构。
本仓库的冒烟测试记录见 `SMOKE.md`（打包时由组织方删除），其中命令与输出为真实运行结果，不是正式案例答案。

## 16. 文件清单、阈值与维护

```
SKILL.md                        本文件：契约、六维度、schema、降级、自检
scripts/audit.py     (~30 KB)   编排层：输入发现、分段、渲染、契约回填、自检调用、资产钩子
scripts/gates.py     (~25 KB)   检测层：文本工具、引用锚点、六个门、动作、覆盖、复核器
scripts/assets.py    (~63 KB)   可核验资产层：金标准、逐项对照、版本记录、运行日志、机器自检
references/ruleset.json         正则可调项、阈值、文案模板、渲染模板（改文案只动这里）
references/dimensions.md        六维度定义、规则索引、finding/action 字段表、映射表模板
references/sample.md            最小输入 / 调用 / 示意输出（示例，非正式结果）
```

阈值集中在 `references/ruleset.json` 的 `thresholds`：`dup_shingle=8`、`dup_paragraph=0.30`、
`handoff_jaccard=0.05`、`handoff_min_words=55`、`mixed_layer_min_words=120`、
`claim_paragraph_min_words=30`、`verbatim_sentence_min_chars=55`、`bound_sentence_cap=6`、`fact_cap=25`。

新增规则的步骤：在 `patterns` 加正则 → 在 `diagnosis`/`basis`/`effect`/`hazard` 四张表加同名条目 →
在 `scripts/gates.py` 对应门里调用 `self.rec(...)`。四张表缺任何一条会回落到维度默认文案（不会崩，但会变笼统）。

## 17. 可核验资产（v1.1.0 新增）

finalize 阶段由 scripts/assets.py 额外写入 /app/output/ 的 5 个文件，让第三方不依赖本 Skill 的自述
即可复核本次运行；任何输入形态（正常 / 空 / 坏 JSON / 截断）都会产出，不会缺件。

| 文件 | 内容 | 复核方式 |
|---|---|---|
| golden_standard.json | 金标准：按 output_contract 与任务要求逐项列期望字段/章节/修改项，每项带 locator 与逐字 quote（无来源标 asis: contract） | python3 -m json.tool；看 completeness.quote_hit_rate |
| diff_report.md | 实际产物 vs 金标准逐项对照（met / partial / missing / pending + 原因） | 直接读；与 self_check.json 交叉核对 |
| ersion_history.md | 静态版本记录 v0 → v1.0.0 → v1.1.0（改了什么 / 为什么 / 如何回退）+ 本次运行段 | 读第 2 节「本次运行段」 |
| 
un.log | 真实运行日志：阶段耗时、退出码契约、降级、异常 | grep -E WARN\|ERROR 或直接读 |
| self_check.json | 机器自检回执：契约键 / 主产物 / 引文命中 / 计数一致 / 空坏输入兜底 / 退出码恒 0 | 看顶层 pass 与 checks |

约定：
esult.json 顶层新增 5 个同名字段指向上述文件，output_contract 原字段一个不少；资产生成
是**加法**（原入口、--check、6 个主产物文件名与 schema、退出码恒 0 均不变）；空/坏输入下是诚实
降级件（self_check.fallback 记录子进程实测结果），不伪造诊断；回退见 ersion_history.md v1.1.0 条目。
