# 核验口径、归因表与试跑样例（verification）

## 1. 九项自检（C1–C9）

脚本把成品 docx 解包，对关键 OOXML 片段做字面包含判断。逐项含义：

- **C1 正文字号**：期望片段 `w:sz w:val="<pt×2>"`，在 `word/styles.xml` 命中即过。
- **C2 页边距**：期望片段 `w:top="<twip>"`，在 `word/document.xml` 命中即过。
- **C3 行距**：期望片段 `w:line="<倍数×240>"`，在 styles.xml 命中即过。
- **C4 字体族**：期望片段 `w:ascii="<字体名>"`，在 styles.xml 命中即过。
- **C5 分栏数**：期望片段 `w:num="<栏数>"`，在 document.xml 命中即过。
- **C6 页码域**：字面量 `PAGE`，在 `word/footer1.xml` 命中即过。
- **C7 文本覆盖率**：阈值 0.98，低于即 fail。
- **C8 规格可回溯**：要求 100% 引文可回查，不足则 partial。
- **C9 成品包结构**（本包新增）：`word/document.xml`、`word/styles.xml`、`word/footer1.xml` 三个 part 必须齐全。

C9 用来堵一类假交付：JSON 写得漂亮，但 docx 是空壳或缺部件。每项记录 `id / check / expected / actual / status / locator`；`status` 只允许 `pass`、`fail`、`partial`，未通过项必须在待确认清单或降级记录里有解释。

## 2. 文本保全怎么算

- 单元口径：段落正文、题注、表格每行的单元格拼接。图片与公式无文本，不参与。
- 比对：两边都去掉所有空白字符；源单元截前 40 字符，判断是否为成品文本的子串。
- 命中率 = 命中单元 / 总单元；总单元为 0 时记 1.0，但保留 `units: 0` 提醒人工复核。
- 命中率不足 0.98：状态降到 `partial`，前 8 个缺失单元写进 `coverage.missing` 与待确认清单。
- 局限：只能证明文字未被删改，不能证明字体/分栏/域代码的视觉一致——后者要靠 PDF 预览目检。

## 3. 数字与引用保全

抽取三类模式：统计量（形如 `p<0.05`）、引用编号（`[1]`、`[2-4]`）、带单位量值（mg、kg、mL、%、°C、MPa、kPa、nm、mm、cm、min、h、mmol、mM、nM 等）。每项记 `before_count`（原稿计数）与 `after_count`（成品计数），成品不再出现即 `missing`。计数是保守证据：换行拆分会拉动计数变化，需人工确认不是改写。

## 4. 图表编号与越界引用

- 题注按块序重排为 `图 1`、`表 1` 这样的统一格式，每次实际改动写进 `change_log`（`action: caption.renumber`，带 before/after/locator/reason）。
- 正文里出现 `图 n` / `表 n` 但 n 超过该类题注总数时，只记录到 `dangling` 与待确认清单，不自动改正文数字，避免误伤事实。

## 5. 出问题时的归因写法

| 现象 | 原因判断 | 落盘方式 |
|-|-|-|
| 规格大多标成推断 | 模板是扫描件，或环境缺 pdftotext | 降级记录写"模板取不到文字，套默认规格" |
| 成品字体和模板不符 | 目标字体本机没装 | 降级记录 + 待确认，写明字形差异 |
| 导出件为空 | 没有 soffice 或转换失败 | 保留 docx，说明无法目视核对 |
| 覆盖率异常低而正文完整 | 表格/公式未计，或换行拆分 | 把缺失单元列在 `missing`，不虚报通过 |
| 题注编号变了正文没变 | 只做了编号归一 | `change_log` 留痕，越界引用进待确认 |
| docx 缺部件 | 写出异常 | C9 fail + `errors` 记 stage |

## 6. 一次最小试跑（示例，不是正式案例答案）

材料：`case.json`（`case_id: smoke-w02-a`，`task_instruction`，`output_contract` 含 deliverable/preserved_facts/evidence_map/change_log/format_spec/compliance_checks/custom_unknown_field）；`task.md`；`format_requirements.md`（字体、字号、行距、四边距、双栏、题注位置、GB/T 7714）；`manuscript.md`（标题、正文、三线表、公式、引用、带单位数值）；`template.tex`（文档类、geometry、字体、行距、文献样式）。

本机环境无 soffice / pdftotext / fc-list，实跑结果：

- 退出码 0，输出 6 个文件（result.json、deliverable.docx、format_spec.md、style_map.json、fidelity_report.json、pending_human.json）。
- `status=partial`，待确认 14 条（多为模板与文字要求冲突、默认值推断）。
- `result`：`spec_items=20`、`spec_inferred=8`、`coverage=1.0`、`facts_verified=4/11`。
- `compliance_checks` C1–C9 全 pass；docx 含 document/styles/footer 三个 part。
- `output_contract` 七个键齐全；`custom_unknown_field` 回填 `null`。
- 空目录：`status=input_error`，errors 含 case 与 manuscript 两条，降级含"没模板""零规格"，退出码 0。
- 坏 JSON：errors 首条带解析错误与文件名，退出码 0。
- 只有 case + 原稿：规格全走默认并标推断，主产物照样生成，退出码 0。

## 7. 复跑命令

```bash
python3 -B scripts/main.py --help
python3 -B scripts/main.py --input <材料目录> --output <产物目录>
python3 -c "import json;json.load(open('<产物目录>/result.json'))"
python3 -c "import zipfile;print(zipfile.ZipFile('<产物目录>/deliverable.docx').namelist())"
```
