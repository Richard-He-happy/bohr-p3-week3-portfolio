# 调用示例：从最小输入到可复核产物

> 本文件展示的是**示例**，用来说明接口形态与产物结构；它不是组织方固定案例的运行结果，也不是白板。
> 示例稿件是为了演示而写的短稿，正文不具备任何科学结论价值。

## 1. 先看接口

| 事项 | 取值 |
|---|---|
| 入口脚本 | `scripts/audit.py` |
| 主流程 | `python3 -B scripts/audit.py --input <输入目录> --out <输出目录>` |
| 复核 | `python3 -B scripts/audit.py --input <目录> --out <目录> --check` |
| 等价复核入口 | `python3 -B scripts/gates.py --work <输出目录> --input <输入目录>` |
| 输出目录内的文件 | `structural_review.json`、`edit_plan.md`、`outline_after.md`、`argument_map.json`、`consistency_report.md`、`pending_human.json`、`result.json` |
| 退出码 | 恒为 0（失败也写合法 partial 结果并说明原因） |

主流程落盘顺序：先写一份占位 `result.json`，再写六件产物，最后回填契约字段并覆盖 `result.json`。

## 2. 最小输入（示例：硅负极预锂化）

`case.json` 只需要 case 标识、任务说明与契约。契约字段的键名会被原样带进结果：

```json
{
  "case_id": "demo-silicon-001",
  "task_instruction": "对该稿做结构诊断，六个维度都要有交代，动作要能直接执行；不要改写全文。",
  "output_contract": {"case_id": null, "deliverable": null, "preserved_facts": [],
                      "evidence_map": [], "change_log": []},
  "organizer_workorder": [
    "六个维度都要落到具体定位符",
    "不要提交整篇改写稿"
  ]
}
```

`manuscript.md`（示例短稿；真实使用时换成完整稿件）：

```markdown
## Introduction

Silicon anodes offer roughly ten times the gravimetric capacity of graphite, but their volume
expansion during lithiation cracks the electrode and consumes lithium in a thickening solid
electrolyte interphase [2]. Here we ask whether prelithiation extends cycle life in pouch cells
assembled from slurry-cast electrodes.

## Results

Prelithiated cells retained 82.4% of their initial capacity after 500 cycles (Fig. 2). Capacity
fade was associated with SEI thickening on the anode surface.

## Conclusion

Prelithiation determines cycle life, and every cell batch benefited [2].
```

运行后稿件被切成 `C01`–`C03` 三章、各一章一段；本示例共 98 词。

## 3. 真实运行输出（示例）

### 3.1 `structural_review.json`

```json
{
  "case_id": "demo-silicon-001",
  "manuscript": {"chapters": 3, "paragraphs": 3, "words": 98, "truncated": false},
  "dimension_coverage": {
    "section_structure":            {"status": "findings", "finding_ids": ["F01"]},
    "research_question_alignment":  {"status": "findings", "finding_ids": ["F02"]},
    "argument_chain":               {"status": "findings", "finding_ids": ["F03"]},
    "conclusion_boundary":          {"status": "findings", "finding_ids": ["F04"]},
    "paragraph_relations":          {"status": "no_issue_with_evidence", "finding_ids": []},
    "duplication":                  {"status": "no_issue_with_evidence", "finding_ids": []}
  },
  "findings": [
    {"finding_id": "F01", "dimension": "section_structure", "severity": "high",
     "locator": "C03-P001",
     "quote": "Prelithiation determines cycle life, and every cell batch benefited [2].",
     "confidence": "high"},
    {"finding_id": "F02", "dimension": "research_question_alignment", "severity": "high",
     "locator": "C01-P001-S02",
     "quote": "Here we ask whether prelithiation extends cycle life in pouch cells",
     "confidence": "medium"},
    {"finding_id": "F03", "dimension": "argument_chain", "severity": "medium",
     "locator": "C02-P001-S01",
     "quote": "Prelithiated cells retained 82.4% of their initial capacity after 500 ",
     "confidence": "medium"},
    {"finding_id": "F04", "dimension": "conclusion_boundary", "severity": "high",
     "locator": "C03-P001-S01",
     "quote": "Prelithiation determines cycle life, and every cell batch benefited [2].",
     "confidence": "high"}
  ],
  "grounding": {"findings_total": 4, "quote_verbatim_hit": 4, "hit_rate": 1.0,
                "dropped_unverifiable": 0,
                "anchors": [{"finding_id": "F01", "rule": "SEC2", "start": 650, "end": 722},
                            {"finding_id": "F02", "rule": "RQ2", "start": 230, "end": 335}]},
  "closure_matrix": {"closed_links": 0, "total_links": 4, "fully_closed": false}
}
```

四条发现的判定依据（`evidence_for_judgment`）分别是：

- `F01`：角色集合为 conclusion / introduction / result，缺 method；全篇 3 段。
- `F02`：研究问题抽出 9 个关键词，其中 5 个未在结果／讨论／结论出现。
- `F03`：正文引用图表编号 {2}，全文检索到的图题／表题为空集。
- `F04`：结论句含因果动词；方法／结果只命中相关关系词（associated），未命中干预／随机化／对照组。

### 3.2 `edit_plan.md`

```markdown
## P1 · 第一批：不修则论证不成立

### A01 · 章节骨架 · 严重度高

- 位置: `C03-P001`
- 原文: > Prelithiation determines cycle life, and every cell batch benefited [2].
- 判断: 稿件缺少该承担「方法与材料」职责的一节……
- 依据: 已识别的角色集合是 conclusion, introduction, result，其中没有 method；全篇段落数为 3。
- 动作: `insert` — 在最后一段之后新起一节「方法与材料」……
- 风险: 新增章节会牵动后续编号与交叉引用，落点需作者确认。
```

四条动作对应关系：`A01→F01 insert`、`A02→F02 narrow`、`A03→F03 insert`（P2）、`A04→F04 narrow`。

### 3.3 `result.json` 的关键字段

```json
{"case_id": "demo-silicon-001", "status": "partial",
 "deliverable": {"primary": ".../edit_plan.md", "editable": true, "format": "markdown+json"},
 "preserved_facts": [{"fact_id": "PF01", "kind": "citation", "locator": "C01-P001-S01",
                      "quote": "Silicon anodes offer roughly ten times the gravimetric capacity of graphite, ..."}],
 "evidence_map": [{"claim_id": "F04", "locator": "C03-P001-S01",
                   "quote": "Prelithiation determines cycle life, and every cell batch benefited [2]."}],
 "change_log": [{"change_id": "CH01", "action_id": "A01", "finding_id": "F01",
                 "revised_quote": null, "status": "proposed_not_applied"}],
 "metrics": {"dimensions_covered": 4, "dimensions_no_issue_with_evidence": 2,
             "findings": 4, "actions": 4, "quote_hit_rate": 1.0,
             "estimated_revision_rounds": 1},
 "self_audit": {"pass": true}}
```

状态之所以是 `partial`，是因为示例稿只有三章、且有 1 条待人工确认项；这不代表流程失败。

## 4. 从这个示例可以确认的五件事

1. 一条发现配一条动作，`action.finding_id` 与 `finding.finding_id` 双向可查，没有悬空动作。
2. 每条 `quote` 都能在稿件里逐字找到，并在 `grounding.anchors` 里对应一个 `start`/`end` 字符区间。
3. 状态写作 `no_issue_with_evidence` 表示「已经查过、没有命中」，`checked` 里给出检查规模；它不等于漏项。
4. `change_log.revised_quote` 始终为 `null`：本 Skill 只给结构动作，不产出改写后的正文。
5. 判断不了的部分进 `pending_human.json`，不写进事实陈述。

## 5. 换成自己的案例

把完整稿件放进输入目录（`md` / `txt` / `docx` / 文本层 PDF 均可），目录里可有多个材料文件；脚本取最长可解析文本作为主稿，并在 `pending_human` 里写明这一判断。若无 `case.json`，流程照常跑完，`case_id` 记为 `case-unknown`，契约字段置空。
