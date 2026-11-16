# 交付闸门（qa-gates）

本包对外只承诺两件事：**规格有出处**、**内容没丢**。两层闸门就是这两件事的判定口径 ——
第一层看成品字段（C1–C8），第二层看文件之间是否自相矛盾（I1–I7）。判定不过不是"运行失败"，
而是把事实写进结果并降级，绝不整份判 pass。

## 1. 第一层：字段级检查 C1–C8

| ID | 检查什么 | expected 怎么来 | 判定 |
|-|-|-|-|
| C1 | 正文字号 | 换算后的 `w:sz w:val="<2×pt>"` | 出现在 `word/styles.xml` 即 pass |
| C2 | 页边距 | `w:top="<twip>"` | 出现在 `word/document.xml` 即 pass |
| C3 | 行距 | `w:line="<240×倍数 或 20×pt>"` | 出现在 styles.xml 即 pass |
| C4 | 西文字体族 | `w:ascii="<字体名>"` | 出现在 styles.xml 即 pass |
| C5 | 分栏数 | `w:num="<栏数>"` | 出现在 document.xml 即 pass |
| C6 | 页码域 | 字面量 `PAGE` | 出现在 `word/footer1.xml` 即 pass |
| C7 | 内容单元覆盖率 | `>= 0.98` | 不达标 fail |
| C8 | 规格可回溯比例 | `100%` | 全部命中 pass，否则 partial |

每项输出 `id / check / expected / actual / status / locator`，`status ∈ {pass, fail, partial}`。
fail 与 partial 的原因必须能在 `pending_human` 或 `degradations` 里找到对应说明 —— 只报 fail 不解释等于没查。

## 2. 第二层：一致性断言 I1–I7

这一层查"文件之间对不对得上"，是 C 层查不出的问题。

| ID | 断言 | 不成立意味着什么 | 处置 |
|-|-|-|-|
| I1 | `output_contract` 每个键都在结果顶层 | 键名被改名或漏写 | 列出缺键，进待确认 |
| I2 | `deliverable.docx` 可解包且含 `word/document.xml`、`word/styles.xml` | 成品损坏或不是 Word 包 | 降级 partial |
| I3 | 非推断规格的 `quote` 在来源原样命中 | 出处造假或抽取器拼字符串 | 列出未命中项 |
| I4 | 覆盖率 ≥0.98 且内容单元数 >0 | 内容丢失，或原稿压根没解析出东西 | 指出缺失单元 |
| I5 | `resolved` 字体出现在 `word/styles.xml` | 声称用了某字体但成品里没有 | 核对 `font_resolution` |
| I6 | 正文图表引用不超出题注总数 | 题注编号与正文脱节 | 列出越界引用 |
| I7 | `format_spec` 条数 = `result.spec_items` = 内部规格条数 | 三处计数不同源，读数会被带偏 | 重新核对 |

I4 特意带上"单元数 >0"：空输入时 `0/0` 的覆盖率在数学上会被算成 0 或 1，无论哪种都不能当成通过。
I7 防的是"表里 20 条、摘要说 18 条"这类自相矛盾 —— 复核者第一眼就会去数。

任一断言不成立：追加 `pending_human` 一条（`item: invariant:<ID>`），若 `status` 原本是 `ok` 则改判 `partial`，
并把更新后的待确认清单重写到 `pending_human.json`，避免磁盘上的清单和 `result.json` 不一致。

## 3. 保真口径（两个账本）

**内容单元账本**（`fidelity_report.coverage`）

- 单元 = 段落文本、题注文本、表格每一行的单元格拼接。图片与公式不计入（没有可比文本）。
- 比对：两边都去掉全部空白，源单元取前 40 字符，判定是否为成品纯文本的子串。
- `ratio = 命中 / 单元数`；单元数为 0 时按 0 处理并在 `missing` 留空、在 I4 说明"原稿没解析出内容"。
- 这个方法只能证明"文字没被删改"，证明不了字形、分栏、域代码的视觉正确性；后者只能靠 `deliverable.pdf` 目视。
- 常见误报来源：成品把一段拆成多段（文本仍在，命中），或原稿表格单元含换行（去空白后仍可比）。

**事实账本**（`preserved_facts`）

- 抽取：统计量 `p<0.05` / `p=.01`；引用编号 `[1]`、`[2-4]`、`[1,3]`；带单位数值（`mg/kg`、`mg`、`kg`、`mL`、`%`、`°C`、`MPa`、`kPa`、`nm`、`mm`、`cm`、`min`、`h`、`mmol`、`mM`、`nM`）。
- 每条给 `before_count`（原稿出现次数）与 `after_count`（成品出现次数），`status` 为 `verified` 或 `missing`。
- 比对前取值与成品文本都要去空白：`300 °C` 在成品里可能被排成 `300°C`，带空格直接比会假报丢失。
- 计数是保守指标：换行拆分会把 `after_count` 抬高，需要人看一眼确认不是改写。

## 4. 字体处置

1. `fc-list` 探测模板要求字体 → `font_resolution.probe_result`（`true`/`false`/`null`，`null` 表示无探测工具）。
2. `false` → 改用 Liberation Serif（revision3），`fallback_used: true`，同时写 `degradations`（`what`/`handled`/`impact`）与 `pending_human`。
3. `null` → 不知道字体是否可用，不改名，`probe_result` 如实为 `null`，供人判断。
4. 三种情况都必须让成品 `word/styles.xml` 里的 `w:ascii` 与实际选定的字体族一致；I5 与 C4 会各查一遍。

绝不出现"成品用系统默认字体、结果写着已满足 Liberation Serif"这种组合 —— 那是正确性与可靠性双重扣分。

## 5. 降级决策树

| 观察到 | 归因 | 正确处置 | 记录 |
|-|-|-|-|
| 规格几乎全是 `inferred: true` | 模板没取到文字 / 压根没模板 | 说明缺哪类依据，列待补项 | `degradations` + `pending_human` |
| 模板与规定给出不同取值 | 版本差异或口径冲突 | 取最强出处，留全部候选 | `spec_conflicts` + `pending_human` |
| 字体被替换 | 模板字体未安装 | 说明替换与字形差异 | `font_resolution` + `degradations` |
| `export_artifact: null` | 无 soffice 或转换失败 | 保留可编辑 docx，说明无法目视 | `degradations` |
| 覆盖率低但正文看着完整 | 表格单元/公式未计入，或换行拆分 | 在 `missing` 列具体单元，不虚报 pass | `coverage.missing` |
| 题注改了编号正文没改 | 只做了编号归一 | 记 `change_log`，越界引用进待确认 | `change_log` + `pending_human` |
| `case.json` 坏掉 | 输入问题 | 用目录扫描继续，状态 `input_error` | `errors[stage=case]` |

## 6. 交付前十条

1. `python3 -B scripts/conform.py --help` 退出码 0。
2. `--self-check` 输出 14/14。
3. 空输入、坏 JSON、缺模板三种情况各自跑一次：仍产出合法 `result.json`，退出码 0。
4. `output_contract` 每个键都在顶层；`case_id` 与输入一致。
5. `deliverable.docx` 能被 `zipfile` 打开，含 `document.xml`、`styles.xml`、`footer1.xml`。
6. `deliverable.pdf`（若有）以 `%PDF-` 开头，`pdfinfo` 能读出页数。
7. `format_spec.md` 里非推断项都带 locator 与原始摘录。
8. `compliance_checks` 八项都有实际值；`invariants` 全绿或已在 `pending_human` 说明。
9. `degradations` 每条含 `what / handled / impact`；`errors` 只写真实发生的失败。
10. 包内无 `__pycache__`、`.pyc`、临时产物；示例一律标注"示例，非正式案例结果"。
