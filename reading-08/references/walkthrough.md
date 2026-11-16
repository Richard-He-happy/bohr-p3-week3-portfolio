# 输入/输出示例与复跑方法

> 本文件出现的所有数据都是**示例**，用于说明接口形态，不是平台正式案例，也不构成预置答案。

## 一、示例输入

```text
/input/
├─ case.json
├─ task.md
└─ artifacts/
   ├─ publisher-excerpt.xml
   └─ paragraph-note.txt
```

`case.json` 内容示例：

```json
{"case_id": "sample-a",
 "output_contract": {"formulas": [], "variables": [], "numeric_checks": []},
 "task_instruction": "recover the displayed equation and its symbol definitions"}
```

`artifacts/publisher-excerpt.xml` 示例（分段函数 + 根式，`mml:` 前缀写法）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<article xmlns:mml="http://www.w3.org/1998/Math/MathML">
 <body><sec>
  <p>Here <italic>m</italic> is the sample mass in g and <italic>T</italic> is the bath temperature in K.</p>
  <disp-formula id="eq-A"><label>(A)</label>
   <mml:math>
    <mml:msqrt><mml:mi>m</mml:mi></mml:msqrt>
    <mml:mo>=</mml:mo>
    <mml:mtable>
     <mml:mtr><mml:mtd><mml:mn>1</mml:mn></mml:mtd><mml:mtd><mml:mi>m</mml:mi></mml:mtd></mml:mtr>
     <mml:mtr><mml:mtd><mml:mn>0</mml:mn></mml:mtd><mml:mtd><mml:mi>T</mml:mi></mml:mtd></mml:mtr>
    </mml:mtable>
   </mml:math>
  </disp-formula>
 </sec></body>
</article>
```

`artifacts/paragraph-note.txt` 示例：

```text
The fitted mass was m = 2.5 g and the bath was held at T = 300 K.
```

## 二、跑一次

```bash
python3 -B scripts/run_audit.py --input /input --output /app/output
```

进程返回码恒为 0。输出目录先出现 partial 版 `result.json`，结束时被终版覆盖；同时生成 `formulas.tex`、`symbol_table.csv`、`verification.md`。

## 三、输出长什么样（示例节选）

```json
{"case_id": "sample-a", "status": "partial",
 "result": {
   "formulas": [{"formula_id": "F1", "source_id": "eq-A", "eq_number": "(A)",
                 "latex": "\\sqrt{m}=\\begin{cases} 1 & m \\\\ 0 & T \\end{cases}",
                 "latex_source": "structural_mapping",
                 "structure": {"fracs": 0, "subsups": 0, "radicals": 1, "matrices": 0, "cases": 1},
                 "symbols": ["m", "T"], "flags": ["mtable_as_cases"], "status": "ok"}],
   "variables": [{"symbol": "m", "definition": "the sample mass in g", "unit": "g",
                  "definition_source": "paper_defined",
                  "locator": "/article[1]/body[1]/sec[1]/p[1]"},
                 {"symbol": "T", "definition_source": "paper_defined", "unit": "K"}],
   "numeric_checks": [{"formula_id": "F1", "substituted": {"m": 2.5, "T": 300.0},
                       "status": "not_computable", "missing_symbols": ["m"]}],
   "selfcheck": {"passed": true, "failed": [],
                  "checks": [{"check": "contract_keys_backfilled", "passed": true, "detail": "missing=[]"}]}},
 "contract_fields_missing": []}
```

注意两点：`mtable_as_cases` 是"可能是分段函数也可能是两列矩阵"的提示标记，公式状态仍是 ok 但表格语义要人工复核；块式结构在 `structure` 里计入 `cases`。`numeric_checks` 因为表格里的 `1`/`0` 与 `\sqrt` 组合无法按标量表达式求值而落到 `not_computable`，这是预期行为，不是失败。

## 四、材料没有公式表示时的示例

只有下面这段文字、没有任何 XML/TeX 的公式对象：

```text
The catalyst was tested at 523 K and 1 bar with a space velocity of 12 h-1.
Conversion reached 87 % after 40 h on stream.
```

应得到：`status="insufficient_evidence"`、`result.formulas` 为空数组、`result.missing_objects` 列出缺失的公式表示、`pending_human` 提示补 MathML/TeX 或人工读原文；而 `result.indicator_checks` 会把 `523 K`、`1 bar`、`12 h-1`、`87 %`、`40 h` 逐条列出并各带 quote 与 locator。**不反推公式，也不把缺失量写成 0。**

## 五、复跑与自查命令

```bash
python3 -B scripts/run_audit.py --help
python3 -B scripts/run_audit.py --input /input --output /tmp/run1
python3 -B scripts/run_audit.py --input /input --output /tmp/run2
diff /tmp/run1/formulas.tex /tmp/run2/formulas.tex
python3 -B scripts/run_audit.py --input /tmp/empty-input --output /tmp/run3
```

第二次运行与第一次的 `formulas.tex` 应逐字节一致（无随机性）；空目录输入仍应返回 0 并给出合法 partial。

检查清单：`contract_fields_missing` 为空；`result.selfcheck.passed` 为 true；没有 `quote_verified=false` 的 claim 留在 `claims` 里（有则必须已进 `pending_human`）；`coverage.by_source.common_knowledge` 的每个符号都能在 `uncertainties` 找到对应 object。

## 六、四个产物各管什么

- `result.json`：权威记录，全部结构化字段都在这；后续任何分析只读这份。
- `formulas.tex`：可直接丢进 LaTeX 编辑器的最小集，每条公式带 `% source_id` 注释，方便回查出处。
- `symbol_table.csv`：符号表的表格副本，字段与 `variables[]` 对齐，适合人工盘点或导入表格软件。
- `verification.md`：本次运行摘要，含覆盖度、耗时、错误与自检结论，方便快速判断这次结果可不可信。

## 七、常见问题

- **公式数量对不上**：先看 `sources[].notes.math_nodes` 与 `coverage.formulas_total`；XML 里 `<math>` 节点数才是分母，正文里提到的编号不算。
- **LaTeX 里出现 `\square`**：说明有节点没被映射，查该公式的 `flags` 找到 `unmapped:<节点名>`，再决定是否补映射；不要把占位符当成已识别结果。
- **符号表里出现常识来源**：说明材料里找不到该符号的任何痕迹，这类符号必须同时出现在 `uncertainties`，人工确认后才能用。
- **同一输入两次结果不同**：正常实现没有随机源，若出现差异说明输入目录里混入了变化文件（例如输出目录被误当成输入），把输入与输出目录分开即可。
