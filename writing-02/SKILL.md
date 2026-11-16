---
name: paper-format-conformance-kit
description: 论文投稿排版对齐工具：自动读取目标模板、文字格式要求与原始稿件，逐项产出可回查的版式规格，重排成可编辑 docx，同时给出规格清单、样式映射、文本保全报告与合同字段。适合"照模板改稿""按格式要求重排""导出件合规核验"等学术写作任务。
version: 1.0.0
---

# 论文排版对齐工具（paper-format-conformance-kit）

## 0. 它解决什么

把"一篇真实稿件 + 一份真实模板"变成可交付的排版成品。核心不是把字改大改粗，而是：

- 从模板/要求里**读**出每一条可核对的版式参数（纸张、边距、栏数、字体、字号、行距、标题层级、题注位置、文献体例、目录深度）；
- 把参数**落**到生成的 docx 样式与节属性里；
- 把"原文有没有被改动"**证**出来：逐内容单元比对、数字/引用计数、改动记录；
- 把拿不准的**标**出来：来源缺失、模板与要求互相矛盾、字体不可用、预览失败，全部进待人工确认或降级记录。

不做：改写正文语义、增删文献、翻译、补造材料里没有的数据。稿子里的文字只搬不改，数值与引用编号原样保留。

## 1. 三个固定目录

| 目录 | 作用 | 备注 |
|-|-|-|
| `/input` | 平台投喂的材料根 | `case.json`、`task.md`、模板、稿件、格式要求通常都在这里 |
| `/app/work` | 草稿区 | 中间稿、试排、临时转换都丢这里，**不是**交付物 |
| `/app/output` | 交付根 | 只放最终产物和 `result.json` |

代码里不写死当前目录：所有资源定位都用 `Path(__file__).resolve().parent` 推导。默认输入 / 输出路径是容器约定，但可用命令行参数覆盖。只用 Python 标准库，全程离线。

**退出码永远是 0。** 失败与降级只体现在 `result.json` 的 `errors` / `degradations` 里，不用非零退出码表达。

## 2. 如何调用

```bash
python3 -B /app/skills/weekly-skill/scripts/main.py --input /input --output /app/output
```

入口只接受四种参数：`--input DIR` 指定材料目录（缺省 `/input`）、`--output DIR` 指定产物目录（缺省 `/app/output`）、`--no-preview` 关闭预览导出、`--version` 与 `--help` 打印信息后退出。

执行顺序固定：先写一份 `status=partial` 的最小 `result.json` → 跑主流程 → 无论成败都覆盖为最终版。中途被杀也有合法结果可读。

## 3. 材料怎么认

`case.json` 先读：优先 `<input>/case.json`，再按 `case*.json` 通配和递归查找。JSON 坏了不要停，记 `errors[{stage:"case"}]` 后靠目录扫描继续。

其余材料按"文件名语义 + 扩展名"分三堆：

1. **模板**：名字含 `templ`/`模板`，或后缀 `.cls`/`.sty`；类型 docx/tex/pdf。文档解释优先级最高。
2. **文字要求**：名字含 `requir`/`format`/`规定`/`要求`/`须知`/`格式`；类型 text/pdf/json。
3. **原稿**：名字含 `manuscript`/`paper`/`draft`/`原稿`/`稿件`/`正文`；没命中就选文件名最短的可解析文档兜底。

`case` 里的 `task_instruction`、`format_requirements`、`organizer_workorder` 也当规格/回执来源读。材料没有的对象不猜，缺什么就写什么到降级记录。

## 4. 规格体系

固定 20 项，覆盖页面、字体、正文、标题、题注、文献、目录七个域。完整槽位、默认值、换算与边界见 `references/spec_rules.md`。

抽取路径三选多：

- **docx 模板**：解析 `word/styles.xml`（Normal、Heading 1–3、Caption、Bibliography）与 `word/document.xml` 的 `sectPr`、TOC 域；
- **tex 模板**：解析文档类选项、`geometry`、中英文字体命令、字号、行距、`bibliographystyle`、`captionsetup`；
- **文字要求**：按关键词逐行正则，抓字号/行距/边距/栏数/题注位置/文献体例。

合并规则：模板 docx 强于模板 tex，强于文字要求，强于默认值。同槽位多个取值 → 取最强的，记录全部候选并进 `pending_human`；无任何来源 → 默认值 + `inferred=true` + 进 `pending_human`。字体缺失时按 revision3 换成 Liberation Serif，并在两处记录，不静默顶替。

## 5. 交付什么

`/app/output` 至少应有这些文件：`deliverable.docx`（可编辑主产物，带样式绑定、书签、TOC 域、页码域、分栏与三线表）、`deliverable.pdf`（有 LibreOffice 时导出的真实预览，没有则字段为 `null`，不算失败）、`format_spec.md`（逐项规格清单，含 ID/取值/出处/引文/是否推断）、`style_map.json`（生效样式数值与源→目标样式名映射）、`fidelity_report.json`（覆盖率、交叉引用、构建计数、比对口径）、`pending_human.json`（待人工确认项）、`result.json`（结构化结果与契约回填）。

`result.json` 必须覆盖五类信息，缺一即视为不完整：

1. 标识：`case_id`（原样）、`status`、`runtime`；
2. 主交付：`deliverable`、`editable_source`、`export_artifact`；
3. 结果摘要：`result`（含 coverage、spec_items、spec_inferred、facts_verified、counts）、`format_spec`；
4. 证据链：`preserved_facts`、`evidence_map`、`change_log`/`changes`、`compliance_checks`；
5. 边界：`sources`、`uncertainty`/`uncertainties`、`pending_human`、`errors`/`exceptions`、`degradations`、`workorder_receipt`。

`status` 的枚举只有 `input_error`、`insufficient_evidence`、`partial`、`ok`，判定优先级从高到低：case 读不了 → 没有可编辑主产物 → 有错误/待确认项/覆盖率低于 0.98 → 全部干净。不要把没做到的状态写成 `ok`。

**契约回填**：`output_contract` 里每个键都必须在结果顶层出现。若该键天然不存在，就按名字语义从最接近的字段借值（例如带 `preview` 的键借导出件、带 `evidence` 的键借证据映射、带 `pending` 的键借待确认清单）；借不到就写 `null`，键不能少。未知自定义键保留原键名，同样回填或置空。

## 6. 证据与保真口径

- 每条生效规格都必须带定位符与逐字引文：`文件#行号`、`tpl.docx#sectPr/pgMar@top`、`tpl.docx#styles.xml[Normal]/sz`、`paper.tex#命令片段` 之一。
- 引文只有在来源文本中逐字命中，`traceable` 才为 `true`；否则 `false` 并进待确认。默认值 `traceable=null` 且 `inferred=true`。
- 文本保全按内容单元算：段落、题注、表格行。比对时双边去空白，源单元取前 40 字符查是否出现在成品文本里；命中率低于 0.98 就降级为 `partial` 并列出缺失单元。
- 事实保全抽三类：统计量（`p<0.05` 类）、引用编号（`[1]`、`[2-4]`）、带单位量值。每项给改前/改后计数，成品中消失即 `missing`。
- 图表编号按出现顺序归一并记录每次改动；正文里指向不存在的图/表编号只报告，不自动改。
- 计数只是保守证据，不能替代视觉核对；视觉一致性靠真实 PDF 预览。

## 7. 工作稿与计划（可选）

长任务建议在 `/app/work/plan.json` 维护进度，脚本不强制，但字段与枚举最好按下面来，便于中断续跑：

```json
{"case_id": "...", "steps": [
  {"id": "inventory", "status": "done", "evidence": "文件清单"},
  {"id": "spec_extract", "status": "doing", "evidence": "format_spec.md"},
  {"id": "build", "status": "todo", "evidence": "deliverable.docx"},
  {"id": "audit", "status": "todo", "evidence": "result.json"}
], "open_questions": []}
```

- `steps[].id` 建议值：`inventory` / `spec_extract` / `build` / `audit`；
- `steps[].status` 只能取 `todo` / `doing` / `done` / `skipped`；
- 计划只是过程记录：不进 `/app/output`，也别放进 `/input` 免得被当成材料扫描。

## 8. 降级对照表

现场情况与处理方式一一对应：case 缺失或坏 JSON 时靠目录扫描继续、状态置 `input_error` 并写 `errors[stage=case]`；没有模板就走"文字要求 + 默认规格"并记降级；零规格命中则全默认、全标推断；字体不可用换 Liberation Serif 并双处留痕；PDF 取不到文本就跳过该来源、留空引文；没有 soffice 或转换失败则保留 docx、预览置 `null` 并记降级；原稿缺失输出空正文 docx 并写 `errors[stage=manuscript]`；单文件抽取异常只丢该文件结果、写 `errors[stage=spec]`；主流程任何异常先记 `runtime` 再继续收尾。

## 9. 交付前自审 9 问

1. `--help`、`--version` 退出码为 0。
2. 最小 case 实跑后，`deliverable.docx` 可被 `zipfile` 打开且含 `word/document.xml`、`word/styles.xml`、`word/footer1.xml`。
3. `result.json` 可解析，`case_id` 与输入一致，`output_contract` 无缺键。
4. 每条规格要么可回查（`traceable=true`），要么在 `pending_human` 有说明。
5. `compliance_checks` 覆盖 C1–C9（C9 是本包新增的成品包结构自检），失败项有归因。
6. `result.coverage` 有值；低于 0.98 时状态不写 `ok`。
7. 同一输入重跑，`change_log` 与 `preserved_facts` 条目一致。
8. 空输入、坏 JSON、缺模板三种情况均 exit 0 且结果文件合法。
9. 输出目录没有临时文件、`__pycache__`、`.pyc`。

## 10. 示例（示例数据，非正式案例结果）

`/input`：`case.json`（`case_id=demo-001`，含 `task_instruction`、`output_contract`）、`format_requirements.md`、`manuscript.md`、`template.tex`。

```bash
python3 -B scripts/main.py --input /input --output /app/output
```

跑完可见：

```
result.json  deliverable.docx  format_spec.md  style_map.json
fidelity_report.json  pending_human.json  [deliverable.pdf]
```

结果片段（数值随输入变化）：

```json
{"case_id": "demo-001", "status": "partial", "deliverable": "deliverable.docx",
 "export_artifact": null,
 "result": {"spec_items": 20, "spec_inferred": 8, "coverage": 1.0, "facts_verified": "4/11"},
 "compliance_checks": [{"id": "C1", "check": "正文字号", "expected": "w:sz w:val=\"21\"", "status": "pass"}]}
```

## 11. 包结构与维护

```text
SKILL.md
scripts/main.py          命令行入口 + 兜底写结果
scripts/format_mapper.py 材料识别、编排、自检、落盘
scripts/docx_kit.py      Markdown/docx 解析 + 最小 OOXML 生成
scripts/spec_rules.py    20 项规格抽取、合并、单位换算
scripts/reporting.py     result.json 与四份核验文件装配
references/spec_rules.md 槽位字典/优先级/定位符/换算/边界
references/verification.md 检查口径/失败归因/最小试跑记录
```

版本 1.0.0；Python 3.10+；字体默认 Liberation Serif（revision3）。扩展规格项时同步默认值表、扫描器、换算函数与本包 `references/spec_rules.md`；改检查项时同步 `references/verification.md` 与第 9 节。
