---
name: manuscript-template-conformance
description: 把一份现成稿件按目标模板或格式要求重排成可交付的学术稿件。先从模板文件与格式规定里逐条取出页边距、字号、行距、栏数、标题层级、题注位置、参考文献样式等可核对的取值并记下出处，再生成可编辑 docx、逐项自查表、内容单元保真账本、待人工确认清单与合法 result.json。当用户说"套用投稿模板""按学校格式规定改稿""核对排版是否合规""把 md/tex 稿排成 docx"时使用。
version: 1.0.0
---

# 稿件模板合规适配（manuscript-template-conformance）

## 0. 何时使用

**该用**：手上有一份稿子（md / tex / docx）和一份"要变成什么样"的依据（docx/dotx 模板、LaTeX 类文件、期刊或院系的格式规定、或 case 里的格式条目），需要交出可编辑成品而不是截图。

**不该用**：纯文字润色、翻译、文献综述、从零写论文。本包只动版面，不动内容。

**它解决的具体麻烦**：模板里的字号、行距、边距、栏数散落在 styles.xml、sectPr、`\geometry`、规定文档正文里，肉眼抄容易漏；抄完又说不清抄自哪一行。本包把每条取值连同"出处定位 + 原文摘录"一起产出，并核对内容单元有没有在重排中丢失。

## 1. 一次调用的完整动作

```
python3 -B scripts/conform.py --input /input --output /app/output
```

顺序固定，任何一步失败都不中断：

1. **先落 partial 结果**：进入后立刻写一份合法但空的 `result.json`（`status: partial`、`runtime.stage: partial`）。此后即使超时被杀，读取方仍能拿到结构化文件。
2. 盘查 `/input`，给文件分角色（模板 / 原稿 / 格式要求）。
3. 抽规格：每条带 `source`（template_docx / template_tex / requirements / default）、`locator`、`quote`。
4. 合并同项多值，冲突留表并进待确认。
5. 换算成 OOXML 单位，探测字体，按 revision3 规则处理字体替用。
6. 解析原稿为块序列，题注重编号，写 `deliverable.docx`，尽力导 `deliverable.pdf`。
7. 保真比对（覆盖率 + 事实计数），跑 C1–C8 字段级检查。
8. **finalize**：组装 `result.json`，回填 `output_contract` 全部键，跑 I1–I7 一致性断言，按实际完成度判定 `status`，覆盖写回。
9. 退出码恒为 0。

参数：`--input`（默认 `/input`）、`--output`（默认 `/app/output`）、`--no-preview`（跳过 PDF）、`--self-check`（只跑内部自检）、`--version`。

## 2. 输入盘查与文件角色判定

入口读 `<input>/case.json`；找不到就依次试 `case*.json`、递归 `case*.json`。JSON 坏掉时记 `errors[{stage:"case"}]` 并继续用目录扫描工作，不放弃整个运行。

角色按"文件名线索 + 文件类型"判定，不按领域标签猜内容：

| 角色 | 判定线索 | 允许类型 |
|-|-|-|
| 模板 | 文件名含 `templ`/`模板`，或后缀 `.cls`/`.sty` | docx, dotx, tex, cls, sty, pdf |
| 格式要求 | 文件名含 `requir`/`format`/`规定`/`要求`/`须知`/`格式` | md, txt, pdf, json |
| 原稿 | 文件名含 `manuscript`/`paper`/`draft`/`原稿`/`稿件`/`正文` | docx, md, tex |

没有命中原稿时，取"类型可解析且名字最短"的那一份，并在 `sources` 里如实标注它被当成了原稿。命不中的文件不进 `sources`，但留在输入目录不动。

## 3. 从模板里读出规格

三类来源各有抽取器，同一套 20 项规格 ID（见 `references/spec-rubric.md`）：

- **docx/dotx 模板** → 读 `word/document.xml` 的 `sectPr`（`pgSz`/`pgMar`/`cols`、TOC 域指令），读 `word/styles.xml` 的 `docDefaults` 与 `Normal`/`heading n`/`caption`/`Bibliography` 样式块。摘录直接用命中的 XML 片段，所以成品侧能 grep 到同形字符串。
- **LaTeX 类文件** → `\documentclass[..]{..}`（栏数、字号）、`\geometry`、`\setmainfont`/`\setCJKmainfont`、`\fontsize`、`\onehalfspacing` 一类行距命令、`\bibliographystyle`、`\captionsetup`、`\tableofcontents`。
- **文字规定**（含 cases 里 `task_instruction`、`format_requirements` 字段） → 逐行正则。注意两条实际经验：`Liberation Serif 字体` 与 `字体 Liberation Serif` 两种语序都认；"上边距 2.5cm，下边距 2.5cm，左边距 3cm，右边距 3cm" 这种一行四条边距要全量扫描，否则只拿到第一条。

抽不到的值不猜：落回兜底表并标 `inferred: true`，同时进 `pending_human` 请人确认模板是否另有规定。

> 扫描版 PDF 模板读不出文字时，`pdftotext` 返回空，结果是整套规格走兜底 —— 这是真实降级，不是失败，见第 10 节。

## 4. 冲突合并与出处强度

出处强度：`template_docx` > `template_tex` > `requirements` > 兜底。

同一规格项出现多个不同取值时：取最强出处的那条，同时把全部候选写进 `spec_conflicts[]`（含 `item`/`chosen`/`rule`/`values[]`），并把该项送进 `pending_human` 让人确认。**不擅自替用户选边**，也不隐瞒被放弃的取值。

同源同值重复出现只算一次冲突也不记。

## 5. 版面重建

成品是**真正可编辑的 docx**：`zipfile` 直接拼最小 OOXML（`[Content_Types].xml`、`_rels/.rels`、`word/document.xml`、`word/styles.xml`、`word/footer1.xml`、`word/_rels/document.xml.rels`），不是把页面临摹成图片。

- 段落一律绑定样式名（`Normal`/`Heading1-3`/`Title`/`Abstract`/`Caption`/`Bibliography`/`FootnoteText`），标题层级同时写 `w:outlineLvl`，目录才能认出来。
- 标题处写书签，正文前插 `TOC \o "1-N" \h \z \u` 域；页脚写 `PAGE` 域。域是"待刷新"状态而非死文本。
- 表格写三线表：表头行加下边框，整表不加竖线。
- 分栏写 `w:cols`，栏间距与分隔线随之带上；页面尺寸与页边距写 `w:pgSz`/`w:pgMar`。
- 题注按出现顺序统一编号（`图 n`/`表 n`），改动逐条记进 `change_log`（before → after）。

## 6. 内容单元保真

"转得全"优先于"排得漂亮"。口径写在 `references/qa-gates.md`：

1. 原稿先拆成块序列（标题/段落/表格行/图注/公式/脚注/文献条目），这是比对基准。
2. 成品 docx 取回纯文本并去掉全部空白，原稿每个内容单元去空白后取前 40 字符，必须作为子串出现。
3. `coverage = 命中数 / 单元数`；低于 0.98 即 `status: partial`，缺失单元前 8 条进 `coverage.missing` 与 `pending_human`。
4. 事实侧另记账：统计量（`p<0.05`）、引用编号（`[1]`、`[2-4]`）、带单位数值（`95%`、`300 °C`、`20 nm`）在改前改后的出现次数，逐条给 `before_count`/`after_count`/`status`。比对前把取值同样去空白，否则 `300 °C` 这种带空格的值会被误判为丢失。

局限要讲清：覆盖率只能证明"文字没被删改"，证明不了字形、分栏、域是否视觉正确 —— 后者靠 `deliverable.pdf` 目视。

## 7. 字体：Liberation Serif 与 revision3

- **优先用 supplied Liberation Serif**：先用 `fc-list` 探测模板要求的字体是否可用，结果写进 `font_resolution`（`requested`/`probe_tool`/`probe_result`/`resolved`/`fallback_used`）。
- 模板字体不可用时，按 revision3 规定改用 Liberation Serif，记 `degradations`（含 `what`/`handled`/`impact`：字形略有差异）并进 `pending_human`。**不得静默用默认字体冒充满足要求**。
- 早期"字体不可用"的输入与结果按历史处理，不再作为失败沿用；源文件与评分口径不变。
- 成品侧可核：`word/styles.xml` 的 `w:rFonts w:ascii="Liberation Serif"`；这一条同时是 I5 断言与 C4 检查的对象。

## 8. 产物与 result.json

产物（`/app/output/`）：

| 文件 | 内容 |
|-|-|
| `deliverable.docx` | 主产物：可编辑成品，样式绑定 + 书签 + 目录域 + 页码域 + 分栏 + 三线表 |
| `deliverable.pdf` | 预览（soffice 不可用或转换失败时为 `null`，docx 照留） |
| `format_spec.md` | 20 项规格表：编号 / 规格项 / 取值 / 出处 locator / 原文摘录 / 是否推断，末尾附冲突与覆盖摘要 |
| `style_map.json` | 落到成品的数值样式（font/ea/sz/line/lineRule/align/cols）与样式名映射 |
| `fidelity_report.json` | 覆盖率、交叉引用、构建计数、冲突、事实账本、比对方法 |
| `pending_human.json` | 待人工确认项（`item`/`issue`/`action`） |
| `result.json` | 结构化结果 + 契约字段回填 |

`result.json` 顶层键：`case_id`、`status`、`deliverable`、`editable_source`、`export_artifact`、`result`（计数/覆盖率/规格条数/事实核验比例）、`format_spec`、`evidence_map`、`preserved_facts`、`change_log`（=`changes`）、`compliance_checks`、`spec_conflicts`、`invariants`、`font_resolution`、`sources`、`uncertainty`（=`uncertainties`）、`pending_human`、`errors`（=`exceptions`）、`degradations`、`workorder_receipt`、`summary`、`runtime`。

`output_contract` 的每个键都必须在顶层出现：能按语义对上就填对应内容，对不上给 `null`，**不改名、不删键、不漏键**。`case_id` 原样回填。

## 9. 一致性断言与 --self-check

交付前两道闸门（细节见 `references/qa-gates.md`）：

- **C1–C8 字段级检查**：字号、页边距、行距、字体族、栏数、页码域在成品 XML 里是否真的出现，覆盖率是否达标，规格是否可回溯。
- **I1–I7 一致性断言**：契约键齐全、成品可解包、每条规格的摘录能在来源里原样命中、内容单元保真、字体已写入样式、交叉引用不越界、`format_spec` 与 `result.spec_items` 同源同数。

任一 I 断言不成立：该项进 `pending_human`，`status` 由 `ok` 降为 `partial`。断言结果随结果一起交付，复核者不必重跑脚本也能看出哪一条没守住。

`python3 -B scripts/conform.py --self-check --output <dir>` 只跑纯函数自检（pt↔half-point、cm↔twip、中文字号表、行距 exact/auto、md 块识别、题注重编号、控制字符清除、出处优先级），写 `self_check.json`，14 条断言应全绿。这一项不碰输入，用于改动脚本后快速回归。

## 10. 降级分支表

| 情景 | 处理方式 | 记在哪 |
|-|-|-|
| `case.json` 缺失 / 坏 JSON | 目录扫描继续，按语义发现文件 | `errors[stage=case]`，`status: input_error` |
| 输入里没有模板 | 用格式要求 + 兜底表 | `degradations` + 相关项 `inferred: true` |
| 一条规格都没抽到 | 全套兜底 | `degradations` + 20 项全标推断 |
| 模板 / 要求冲突 | 取最强出处，留全部候选 | `spec_conflicts` + `pending_human` |
| 模板字体不可用 | 换 Liberation Serif（revision3） | `font_resolution.fallback_used` + `degradations` + `pending_human` |
| PDF 取不到文字（无 pdftotext / 扫描件） | 跳过该来源，其余照常 | `errors` 或空 quote |
| soffice 缺失 / 转换失败 | 保留 docx，`export_artifact: null` | `degradations` |
| 原稿缺失或不可解析 | 空正文 docx + 状态降级 | `errors[stage=manuscript]` |
| 单个模板文件抽取异常 | 只丢该文件结果 | `errors[stage=spec]`（带 files） |
| 主流程任何异常 | 记录后继续，仍 finalize | `errors[stage=runtime]` |
| finalize 自身异常 | 写降级版 result.json | `errors[stage=assemble]` |

## 11. 最小调用示例（示例，非正式案例结果）

输入目录放三样东西：`case.json`（里面有 `case_id:"demo"`、`output_contract` 与 `task_instruction`）；一份 `format_requirements.md`，把字体、字号、行距、边距、栏数、题注位置、参考文献样式各写一条；一份 `manuscript.md`，含一级标题、配图、两行表格、公式、脚注各一处，另有 `[1]`/`[2]` 两处引用与 `95%`、`300 °C` 两个数值。

```
python3 -B scripts/conform.py --input /input --output /app/output
```

示意输出：`deliverable.docx`、`deliverable.pdf`、`format_spec.md`、`style_map.json`、`fidelity_report.json`、`pending_human.json`、`result.json`。

`result.json` 片段（**接口示意，数值随输入变化，非正式案例结果**）：

```json
{
  "case_id": "demo",
  "status": "partial",
  "deliverable": "deliverable.docx",
  "export_artifact": "deliverable.pdf",
  "result": {"coverage": 1.0, "spec_items": 20, "spec_inferred": 8, "facts_verified": "6/6"},
  "compliance_checks": [{"id": "C1", "check": "正文字号", "expected": "w:sz w:val=\"24\"", "status": "pass"}],
  "invariants": [{"id": "I2", "claim": "成品可解包", "actual": 6, "ok": true}],
  "font_resolution": {"requested": "Liberation Serif", "probe_tool": "fc-list", "resolved": "Liberation Serif", "fallback_used": false},
  "pending_human": [{"item": "heading.1.size", "issue": "无出处，采用兜底取值", "action": "请确认模板是否另有规定"}],
  "runtime": {"version": "1.0.0", "seconds": 4.2, "stage": "final"}
}
```

`status: partial` 的原因写在同一份文件里（本次是若干规格只能取兜底值），不是含糊的"差不多完成"。

## 12. 已知限制与维护

**支持范围**：docx/dotx 模板、tex/cls/sty 类文件、md/txt/pdf 格式规定；原稿支持 md、tex、docx。不支持：扫描件模板（无文字层）、`w:theme` 继承链、参考文献字段级标点差异、图片二进制迁移（图注保留，图片本身不嵌入，`media` 计数为 0 时以 `sources` 与 `degradations` 说明）。

**依赖**：Python 3.10+ 标准库；可选外部命令 `fc-list`（字体探测）、`pdftotext`（PDF 取文）、`soffice`/`libreoffice`（PDF 预览）；缺哪个就走对应降级，不阻断。

**文件**：`scripts/conform.py`（入口与管线）、`scripts/extract.py`（盘查与规格抽取）、`scripts/ooxml.py`（解析与 OOXML 写出）、`scripts/verify.py`（核对与断言）、`references/spec-rubric.md`、`references/qa-gates.md`。

**改代码时**：新增规格项要同时改三处 —— `extract.DEF` 的兜底值、对应 `spec_*` 抽取规则、`extract.units()` 的单位换算；新增检查项要同步 `verify.checks()`/`verify.invariants()` 与 `references/qa-gates.md`。改完必跑第 9 节的 `--self-check` 与第 11 节的最小试跑。

**交付前自检**：`--help` 退出码 0；空输入与坏 JSON 仍产出合法 `result.json` 且退出码 0；`output_contract` 每个键都在；规格表里非推断项都有 locator + quote；`compliance_checks` C1–C8 都有实际值；`invariants` 全绿或已在 `pending_human` 说明；`deliverable.docx` 能被 `zipfile` 打开并含 `word/document.xml`、`word/styles.xml`；`deliverable.pdf` 以 `%PDF-` 开头（有则核对页数）；包内无 `__pycache__`/`.pyc`/临时文件；示例均标注"示例，非正式案例结果"。
