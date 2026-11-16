# 最小调用示例（自拟材料 · 示例输出，非正式案例结果）

> 下面所有段落、问题与输出都是为了说明接口而自拟的短样例，**不是**任何隐藏案例的答案，
> 也不能当作效果证明。组织方的正式论文与九道问题不在包内。

## 1. 输入样例

目录 `/input/` 下放一个 `case.json`（键名可以不同，脚本按语义识别）：

```json
{
  "case_id": "sample-photo-01",
  "paper_id": "SAMPLE-PAPER-A",
  "material_version": "v3",
  "output_contract": {"case_id": null, "status": null, "result": null, "claims": [], "uncertainties": []},
  "questions": [
    {"question_id": "Q1", "question": "该催化剂在可见光下降解甲基橙的去除率是多少，光源条件如何？"},
    {"question_id": "Q2", "question": "论文是否报告了该材料的比表面积？"}
  ],
  "materials": {
    "paragraphs": [
      {"paragraph_id": "P1", "section": "abstract",
       "text": "The photocatalyst degraded 92% of methylene blue within 60 min under visible light from a 300 W xenon lamp."},
      {"paragraph_id": "P2", "section": "results",
       "text": "After four reuse cycles the removal efficiency remained above 88%, indicating stable activity."},
      {"paragraph_id": "P3", "section": "methods",
       "text": "The sample was annealed at 450 C for 2 h; phase composition was confirmed by X-ray diffraction."}
    ]
  }
}
```

## 2. 调用

```powershell
python -B <包根>/scripts/run_reader.py --input /input --out /app/output
```

终端摘要（示例）：

```text
[source-bound-paper-qa 1.0.0] case=sample-photo-01 status=partial q=2 subq=2 claims=3 quote_hit=1.0 num_trace=1.0 audit=True fails=[]
```

## 3. 输出节选

```json
{
  "case_id": "sample-photo-01", "paper_id": "SAMPLE-PAPER-A", "material_version": "v3",
  "status": "partial",
  "result": {"answers": [
    {"question_id": "Q1", "status": "answered",
     "answer": "【子问1】该催化剂在可见光下降解甲基橙的去除率是多少，光源条件如何\n可核对数值：... = 92 %。\n原文引证：\"The photocatalyst degraded 92% of methylene blue within 60 min under visible light from a 300 W xenon lamp.\"（P1）\n适用条件：under visible light from a 300 W xenon lamp。",
     "claims": [{"claim_id": "Q1-S1-N1", "kind": "reported", "text": "... = 92 %",
                 "evidence": [{"paragraph_id": "P1", "quote": "The photocatalyst degraded 92% of methylene blue within 60 min under visible light from a 300 W xenon lamp.",
                               "char_start": 0, "quote_verified": true}]}],
     "evidence_paragraph_ids": ["P1"], "sub_questions": [{"index": 1, "status": "answered"}]},
    {"question_id": "Q2", "status": "insufficient_evidence",
     "answer": "材料未报告该问题所需内容：全部 3 段已检索、没有可用原文依据，不补外部知识。",
     "claims": [{"claim_id": "Q2-ABS1", "kind": "inferred", "evidence": []}],
     "unanswered_parts": [{"part": "论文是否报告了该材料的比表面积？", "reason": "not_reported_after_full_search",
                           "missing": "该子问在供给材料里没有可用原文依据", "needed": "含 BET 数值的结果段或表格"}],
     "evidence_paragraph_ids": []}],
    "coverage": {"paragraphs_indexed": 3, "sections_read": [{"section": "abstract"}, {"section": "results"}, {"section": "methods"}],
                 "not_supplied": ["table 未提供，答案只依据已给的正文段落"]}},
  "counts": {"questions": 2, "answered": 1, "insufficient_evidence": 1, "quote_hit_rate": 1.0,
             "numeric_claims_checked": 1, "numeric_claims_traced": 1, "numeric_trace_rate": 1.0},
  "uncertainties": [{"type": "not_reported", "question_id": "Q2", "zero_hit_terms": ["surface area", "BET"]}],
  "pending_human": ["Q2: 全篇未找到匹配证据，请人工确认「未报告」结论并复核检索词"]
}
```

## 4. 怎么读这份产物

1. `question_id` → `answers[]` 中的一条 → `claims[].claim_id`；
2. `claim_id` → `evidence[].paragraph_id` + `char_start`；
3. 用 `paragraph_index.json` 里该段原文按偏移切出 `quote`，逐字比对；
4. `evidence_map.csv` 是同一关系的表格视图，一行一条证据，可直接筛 `quote_verified=false` 复核。

## 5. 其它分支长什么样

- 问题问「是否报告疲劳寿命」，材料只写 “fatigue life was not evaluated”：该题仍可 `answered`，
  论断 `Q?-ABS1` 的 `kind=inferred`、`readability=undetermined`，`uncertainties` 记 `not_reported`。
- 问「降解率是多少」而材料只给「显著提升」没有数字：`status=partial`，
  `unanswered_parts[].reason=numeric_value_not_reported`。
- `/input` 下没有可读案例：`status=input_error`、`errors[]` 记 `stage=load_case`、`answers=[]`，退出码仍是 0。
- 段落没有编号：脚本生成 `P1..Pn`，`locator` 指回来源数组，可在 `paragraph_index.json` 核对映射。

## 6. 换论文、换领域时的建议

1. 只换 `/input`，脚本不用改；新领域词先补 `references/term_map.md`（一行一个 `- 中文 => 英文…`）。
2. 若希望中文答句更自然，写 `answer_patch.json` 后用 `--apply` 合并；脚本会拒收含引文外数字的改写稿。
3. 自检结果看 `verify_report.json`：`ok=true`、`quote_hit_rate=1.0`、`numeric_trace.checked == traced` 才算通过。
