---
name: paper-formula-evidence-audit
description: 论文公式证据审计 Skill。读取 case.json 与随附材料（MathML/XML、TeX、正文文本），把每个行间公式确定性还原为 LaTeX 并统计结构元素，产出可回原文的符号表（paper_defined / context_inferred / common_knowledge 三分类）、带假设与边界条件的推导线索、以及可复算的代入核验，落 result.json 与三个伴随产物。材料缺少公式表示时如实降级为 insufficient_evidence，不反推公式、不用 0 或空串掩盖未知。
version: 1.0.0
license: MIT
---

# 论文公式证据审计（reading-08）

## 0. 这个 Skill 解决什么

科研阅读里围绕公式的四类诉求，这里各有一条可核查的落地路径：

- **认得准**：把 MathML 节点按嵌套顺序翻成 LaTeX，上下标、分式、根式、括号层级都保留；翻不了的元素留占位符并打 flag，绝不凭外观猜字形。
- **讲得清**：公式里出现的每个标识符都要进符号表，并给出定义来源标签、定位符与原文引句。
- **推得顺**：从正文里捞出推导线索句，逐句标注规则词、假设、近似和边界条件，供读者判断某一步为何成立。
- **算得回**：只对材料中字面写出的赋值做代入求值；缺值就报不可算，全无赋值时用明确标注的探针值验证表达式可求值。

不做的事（写进 `uncertainties`、`pending_human`，不伪装成结论）：反推缺失公式、把未知量填 0、对位图做 OCR 猜测、做符号代数证明。

一道题可能遇到"论文快照里没有公式表示"的情况（例如只有指标与条件文字）。此时正确做法是把可核对的部分交付，其余标为缺失对象。

## 1. 调用方式

```bash
python3 -B scripts/run_audit.py --input /input --output /app/output
```

- `--input` 默认 `/input`，里面应有 `case.json` 与材料文件（`task.md` 等原样忽略，不当作答案来源）。
- `--output` 默认 `/app/output`；参数目录、`/app/output`、`./output` 依次尝试，第一个可写的胜出。
- 进程返回值恒为 0：先在输出目录落一份结构合法的 partial `result.json`，解析结束后用最终版覆盖。任何异常都写进 `errors.execution`，不会让 Harness 丢掉记录。
- 只依赖 Python 标准库（≥3.8），不联网；脚本用自身所在目录定位同目录模块，与当前工作目录无关。

## 2. 目录结构

```text
paper-formula-evidence-audit/
├─ SKILL.md                        本文件
├─ scripts/
│  ├─ run_audit.py                 入口：材料发现、结果装配、产物写出、兜底
│  ├─ mathml_engine.py             MathML 解析 + LaTeX 渲染 + 结构与符号清点
│  └─ evidence_core.py             数值求值、正文线索抽取、结果装配与信封
└─ references/
   ├─ mathml-render-rules.md       元素映射表、符号约定、flag 含义
   ├─ output-fields.md             result.json 字段字典、枚举、定位符与状态规则
   └─ walkthrough.md               最小输入/输出示例、降级样例、复跑步骤
```

## 3. 一次运行的处理顺序

1. **找 case**：按 `case.json` → `case_input.json` → `input.json` → 递归 `case*.json` 的顺序取第一个能解析的 JSON 对象；`case_id`（或 `id`）原样带出。
2. **认出契约**：`output_contract` / `output_spec` / `contract` 任取其一，键名一个不改地回填到结果顶层；`output_contract_echo` 记录每个键落在哪里，`contract_fields_missing` 正常必须为空。
3. **清点材料**：递归扫描输入目录，用扩展名加文件头判断类型。XML 走解析器；TeX 抽 `equation`/`align` 环境；纯文本按空行切段落；PDF、位图等不可解释的材料登记为降级项与缺失对象，不臆造内容。
4. **渲染公式**：XML 每个 MathML 节点占一个公式槽位。优先级：`annotation[encoding*=tex]` 原文 > 结构化映射 > `.tex` 环境原文。结构映射不认识的元素输出 `\square` 并记 flag。
5. **建符号表**：`mi` 原子与 `msub/msup/msubsup` 的基进入候选集；`e^{…}`、`10^{…}` 的底数视为常数、继续扫指数。定义从正文"where X is …"句或赋值句里捞，命中即给定义、单位、locator 与引句。
6. **判来源**：有定义句 → `paper_defined`；只在正文出现 → `context_inferred`（`definition=null`）；两种都没有 → `common_knowledge`（`inferred=true`，可附常识提示）。后两类必同时进 `uncertainties`。
7. **抽推导**：按句式线索（substitut / rearrang / assum / approximat / limit / integrat / differentiat / yields 等）切句，填 `rule`、`assumptions`、`approximations`、`boundary_conditions`，并标 `verified=false`（只到"原文这么说"的程度）。
8. **代入核验**：变量在材料中有字面赋值才代入，缺值的进 `missing_symbols` 并标 `not_computable`；完全没有赋值时用 1.0 探针跑一次，标 `example_only` + `is_example=true` + 明确备注。
9. **引句回查**：每条 claim 的引句前 120 字去材料语料里逐字比对；对不上就把 `quote_verified` 置 false、`readability` 降为 `undetermined`，并进 `pending_human`。
10. **一致性自检**（本 Skill 新增）：核对契约回填完整性、公式编号唯一性、符号表覆盖率、定义来源枚举、常识项是否已登记为不确定、LaTeX 结构标志、示例核验是否有备注；结果写入 `result.selfcheck`，失败项同时进 `pending_human`。
11. **写产物**：`result.json`、`formulas.tex`（每式一封 equation 环境，附 `% source_id` 注释）、`symbol_table.csv`、`verification.md`（本次运行摘要）。

## 4. 结果字段

顶层（缺键即失败）：

| 键 | 含义 |
|---|---|
| `case_id` | 输入原值，缺失为 `null` |
| `status` | `ok` / `partial` / `insufficient_evidence` / `input_error` |
| `result` | 主结果对象，见下 |
| `claims` | 关键结论断言，带来源、定位、引句、可信度 |
| `uncertainties` | 未报告、冲突、需人工确认的项 |
| `uncertainty` | 与 `uncertainties` 同值（题面用此别名） |
| `sources` | 每个输入文件的登记项 |
| `pending_human` | 需要人工接管的点 |
| `errors` / `degradations` / `changes` | 异常、降级动作、本次写了什么 |
| `runtime` | skill 名、版本、Python 版本、耗时、输入输出目录 |
| `output_contract_echo` / `contract_fields_missing` | 契约回填位置与缺项 |

`result` 子对象：`formulas`、`variables`、`derivations`、`numeric_checks`、`indicator_checks`、`coverage`、`missing_objects`、`method_notes`、`status_reason`（仅 partial）、`selfcheck`（新增）。逐字段定义、枚举取值与定位符格式见 `references/output-fields.md`。

状态判定：没有 case 也没有任何文件 → `input_error`；有材料但一个公式都没恢复 → `insufficient_evidence`（同时给出 `missing_objects` 与人工接管建议）；全部公式 `status=ok`、`symbol_coverage=1.0`、存在推导且至少一次真实代入 → `ok`；其余一律 `partial` 并在 `status_reason` 写明差在哪。这个 `ok` 是有意严格的。

## 5. 证据与定位规范

- `locator` 必须能按文本规则复现：XML 节点用绝对 XPath（local-name + 位置谓词），文本段落用 `<文件名>#p<序号>`，TeX 公式用 `<文件名>#eq<序号>`，XML 解析失败回退用 `<文件名>#annotation<n>`。
- `quote` 要么是材料里的逐字片段，要么为空并进 `pending_human`；不修改、不拼接原文。
- 级别的稳定标识：`formula_id` 形如 `F1…`（文档顺序），`source_id` 优先取容器 `id`，没有就用 `<文件名>#<序号>`；公式正文编号进 `eq_number`，与 `source_id` 不一致时两者都保留、不强行对齐。
- 每个 claim 都要能沿着 `claim → source_id → locator → quote` 回到材料。

## 6. 状态、冲突与降级

- **同名符号多处定义**：保留首次命中，差异不静默合并；在 `uncertainties` 记 `definition_inferred` / `definition_absent`，人工按 locator 复核。
- **正文与表格数值冲突**：不做裁决，`indicator_checks` 逐条保留原文数值、单位与 locator。
- **XML 命名空间变体**：解析器按本地名识别元素，三种写法都吃；`mml:` 前缀缺少 xmlns 声明时，本版会先补声明再重试（新增修复路径）。
- **命名实体**：`&alpha;` 之类先转数字实体再解析。
- **XML 破损**：退化为正则抽取 TeX annotation，`parse_confidence=low` + `flags:[xml_unparsed]` + 降级记录。
- **公式截断/子节点缺失**：保留已恢复部分，缺参数节点打 `*_arity` flag。
- **输出目录不可写**：退到 `./output` 并记 `errors`；实在写不出去才向 stdout 报一行提示。
- 其余逐项处理见 `references/output-fields.md` 的降级表。

## 7. 对应评分维度

| 维度 | 本实现的做法 | 可查证据 |
|---|---|---|
| 完成度/正确性 | 公式槽位数 = 实际 MathML 节点数；映射是确定性的（分式→`\frac`、上下标→`_{}^{}`、根式→`\sqrt`、算子/标识符查表） | `formulas[].latex` + `structure` + `flags` |
| 完整性/可核验 | 每个符号进变量表；每符号有 locator 与引句；每次核验有代入值与中间表达式 | `coverage.symbol_coverage`、`symbol_table.csv` |
| 质量增益/创新 | 结构化解析优先、定义来源三分类、量级检查（`log10|v|`）、一致性自检 | `variables[].definition_source`、`numeric_checks[].order_of_magnitude_check`、`result.selfcheck` |
| 可靠体验 | 变体、截断、无 XML、空快照各有分支；异常全捕获、退出码 0 | `degradations`、`errors`、两次运行 LaTeX 逐字一致 |
| 生态贡献 | 本文档 + 三份 references + 纯标准库脚本可直接复用 | `references/` |

## 8. 交付前自检

- [ ] `python3 -B scripts/run_audit.py --help` 退出码 0，三个脚本可独立被 import。
- [ ] 含 `mfrac` + `msubsup` 的最小 MathML 能跑通，`latex` 里出现 `\frac` 与上下标，符号表覆盖全部 `mi`。
- [ ] 默认命名空间 / `mml:` 前缀 / 无命名空间三种小样本都能解析；`mml:` 无声明也能恢复。
- [ ] 每条公式的 `source_id` 能在 XML 里找到对应容器或节点。
- [ ] 每个变量 `definition_source` 属于三值之一，`common_knowledge` 项都在 `uncertainties`。
- [ ] 无赋值材料时核验为 `example_only` 且带备注；没有 0 值冒充计算结果。
- [ ] 空目录、坏 JSON、只有 artifacts 三种输入都产出合法 partial 且退出码 0。
- [ ] `contract_fields_missing` 为空；`result.selfcheck.passed == true`。
- [ ] 包内无 `__pycache__`、`.pyc`、答案或预制正式结果。

## 9. 最小示例（示例，不是正式案例结果）

输入骨架与 `case.json`、`source-formulas.xml` 的完整示例在 `references/walkthrough.md`。要点：

- `case.json` 给出 `case_id` 与 `output_contract`（示例用 `{"formulas": [], "variables": []}`）。
- 材料含一段 `mfrac` + `msubsup` 的 MathML，以及一行 "where k is …" 定义句。
- 运行后 `result.json` 的 `result.formulas[0].latex` 形如 `\frac{\alpha+\beta}{\sqrt{\gamma}}`，`variables[]` 里每个符号都有 `definition_source` 与 locator。
- 示例输出均标注"示例"，脚本不内置任何正式案例答案。

## 10. 维护说明

- 新增算子：改 `mathml_engine.OPERATOR_TEX`；新增结构：在 `render_latex` 加分支并同步 `count_structures` 的计数键。
- 新增定义句式：在 `evidence_core` 的 `WHERE_DEFINITION_RE` / `AND_DEFINITION_RE` 追加正则，保留 locator + quote。
- 改字段先改 `references/output-fields.md`，字段只允许在一个地方拼装（`assemble_result`），别处不复制字段名。
- 回归方法：用第 8 节小样本重跑两次，比较 `formulas[].latex` 与 `result.selfcheck` 是否稳定。
