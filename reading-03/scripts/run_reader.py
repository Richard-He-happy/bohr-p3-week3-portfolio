#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_reader.py - answer the supplied paper questions, every claim backed by a verbatim quote.

Normal call:
  python3 -B scripts/run_reader.py --input /input --out /app/output

Optional follow-ups:
  python3 -B scripts/run_reader.py --out /app/output --apply answer_patch.json

Write order is deliberate: a placeholder result.json is stored first, the run then
overwrites it together with answers.json, paragraph_index.json, evidence_map.csv and
verify_report.json, and the last write is the audited payload.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import reader_kit  # noqa: E402
from reader_kit import TRACE  # noqa: E402
PKG_VERSION = "1.0.0"
START_CLOCK = time.time()
FUNCTION_WORDS = set("""a an the of and or in on for to with by from at as is are was were be been this that these
those we our it its their there than then such using used use can may might could should would will not
no also both each more most less between among during after before under over into within via vs which
what how why when where who do have has had if while about""".split())
SECTION_PRIOR = {"NUM": ("result", "finding", "abstract", "table", "perform", "characteri"),
            "MECH": ("method", "experimental", "procedure", "synthesis", "material", "model", "architect"),
            "INT": ("method", "result", "abstract", "discussion"),
            "BND": ("discussion", "conclusion", "limitation", "outlook", "abstract"), "GEN": ()}
BOUNDARY_HINTS = ("未报告", "没有报告", "是否报告", "是否给出", "未给出", "没有给出", "未提供", "局限", "不足", "未涉及",
      "未说明", "没有说明", "未提及", "未开展", "没有测试", "未测试", "哪些信息", "缺少", "未披露")
MECHANISM_HINTS = ("方法", "如何", "机制", "机理", "为什么", "为何", "原理", "作用", "贡献", "创新", "相比", "对比",
      "比较", "优于", "提升", "提高", "改进", "步骤", "流程", "策略", "设计")
QUANTITY_HINTS = re.compile(r"多少|多大|多高|多重|数值|百分之|%|几|效率|浓度|温度|时间|速率|强度|精度|准确率|召回|"
                r"误差|容量|性能|范围|比例|提高|降低|提升|幅度|倍数")
VALID_STATUS = ("answered", "partial", "insufficient_evidence", "input_error")


def question_terms(q, gloss):
    terms = {}

    def add(t, w):
        t = reader_kit.norm_text(t)
        if (len(t) < 2 and not t.isdigit()) or t in FUNCTION_WORDS:
            return
        terms[t] = max(terms.get(t, 0), w)

    for zh, ens in gloss.items():
        if zh and zh in q:
            for e in ens:
                if len(reader_kit.norm_text(e)) < 4 and reader_kit.norm_text(e) not in ("uts", "toc", "cod", "gnn", "cnn", "f1", "ph"):
                    continue  # 2–3 letter aliases such as "Eg" match unrelated words
                add(e, 1.0 + 0.12 * min(len(zh), 6))
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9\-]{1,}", q):
        add(tok, 1.3)
    for num in re.findall(r"\d+(?:\.\d+)?", q):
        if len(num) >= 2:
            add(num, 1.1)  # single digits ("top-1") match almost every paragraph
    return terms


def detect_flags(q):
    f = set()
    if any(c in q for c in BOUNDARY_HINTS):
        f.add("BND")
    if QUANTITY_HINTS.search(q):
        f.add("NUM")
    if any(c in q for c in MECHANISM_HINTS):
        f.add("MECH")
    return f


def classify_question(f):
    if "BND" in f:
        return "BND"
    if "NUM" in f and "MECH" in f:
        return "INT"
    return "NUM" if "NUM" in f else ("MECH" if "MECH" in f else "GEN")


NEGATION_RE = re.compile(r"not (?:evaluat|measur|perform|report|test|investigat|studied|assess|available|includ)|"
                 r"did not|were not|was not|no data|not available|future work|beyond the scope|not addressed", re.I)


def score_paragraph(p, terms, typ):
    txt, sec, s, hits = reader_kit.norm_text(p["text"]), reader_kit.norm_text(p["section"]), 0.0, []
    toks = set(re.findall(r"[a-z0-9][a-z0-9\.\-/]*", txt))
    for t, w in terms.items():
        c = txt.count(t)
        if not c and len(t) >= 5:  # loose prefix matching, so "degradation" still scores the token "degraded"
            c = sum(1 for tok in toks if tok.startswith(t[:6]) or (len(tok) >= 5 and t.startswith(tok[:6])))
        if c:
            s += w * (1 + 0.25 * min(c - 1, 3))
            hits.append(t)
    if not hits:
        return 0.0, []
    s /= 1.0 + len(txt.split()) / 150.0
    if any(k in sec for k in SECTION_PRIOR.get(typ, ())):
        s += 0.9
    if typ in ("NUM", "INT") and reader_kit.VALUE_RE.search(p["text"]):
        s += 0.4
    if typ == "BND" and NEGATION_RE.search(txt):  # boundary questions: explicit non-report sentences first
        s += 0.6
    return round(s, 4), hits


def rank_paragraphs(q, paras, gloss, typ, k=5):
    terms = question_terms(q, gloss)
    n = len(paras)
    if n >= 4 and len(terms) > 1:
        # discard terms that occur in most paragraphs (e.g. "photocatalyst"); if kept, every
        # paragraph scores and a question about an absent property silently looks answered
        df = {t: sum(1 for p in paras if t in reader_kit.norm_text(p["text"])) for t in terms}
        keep = {t: w for t, w in terms.items() if df[t] <= max(1, int(0.6 * n))}
        terms = keep or terms
    scored = []
    for i, p in enumerate(paras):
        s, hits = score_paragraph(p, terms, typ)
        if s > 0:
            scored.append((s, i, p, hits))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[:k], terms


def gather_evidence(sub, paras, gloss, typ, limit):
    ranked, terms = rank_paragraphs(sub, paras, gloss, typ, k=limit + 3)
    evs, best = [], ranked[0][0] if ranked else 0
    for score, idx, p, hits in ranked:
        if len(evs) >= limit or score < max(0.7, 0.5 * best):
            continue
        if len(terms) > 2 and len(hits) < 2 and not any(len(h) >= 6 for h in hits):
            continue  # one specific long term is enough support; do not drop such a paragraph
        if any(e["paragraph_id"] == p["paragraph_id"] for e in evs):
            continue
        cand = sorted(((score_paragraph({"text": s, "section": p["section"]}, terms, typ)[0], a, b)
                       for a, b, s in reader_kit.sentence_spans(p["text"])), reverse=True)[:1]  # at most one sentence taken from each paragraph
        for s2, a, b in cand:
            quote = reader_kit.slice_quote(p["text"], a, b, hits)
            if len(quote.split()) < 5:
                continue
            evs.append({"paragraph_id": p["paragraph_id"], "section": p["section"], "quote": quote,
                        "values": reader_kit.extract_values(quote), "condition": reader_kit.condition_phrase(quote),
                        "negation": bool(NEGATION_RE.search(quote)),
                        "locator": p["locator"], "char_start": p["text"].find(quote)})
            if len(evs) >= limit:
                break
    return evs, terms


make_claim = reader_kit.make_claim


UNIT_HINTS = {"温度": ("C", "°C", "℃", "K"), "时间": ("h", "min", "s", "d"),
        "强度": ("MPa", "GPa", "kPa"), "粒径": ("nm", "um", "µm", "μm", "mm"),
        "尺寸": ("nm", "um", "µm", "μm", "mm"), "浓度": ("mg/L", "mol/L", "mmol/L", "g/L", "ppm"),
        "效率": ("%",), "百分比": ("%",), "波长": ("nm",), "电位": ("V", "mV"), "功率": ("W", "mW", "kW"),
        "比表面积": ("m2/g", "m²/g"), "孔容": ("cm3/g",), "孔径": ("nm",), "带隙": ("eV",)}


def expected_units(sub):
    out = set()
    for zh, us in UNIT_HINTS.items():
        if zh in sub:
            out.update(us)
    return out


def borrowed_evidence(qt, sub, paras, gloss, typ, cited, limit=2):
    """Borrow evidence for a sub-question that shares its sentence with a sibling.

    Whole-question evidence is accepted only from a paragraph a sibling already
    cited, or from one that carries a value in the unit this sub-question asks for.
    """
    evs, _ = gather_evidence(qt, paras, gloss, typ, limit + 1)
    want = expected_units(sub)
    return [ev for ev in evs
            if ev["paragraph_id"] in cited or any(v["unit"] in want for v in ev["values"])][:limit]


def term_doc_freq(sub, paras, gloss):
    terms = question_terms(sub, gloss)
    return terms, {t: sum(1 for p in paras if t in reader_kit.norm_text(p["text"])) for t in terms}


def value_matches_question(v, sub, terms, flags):
    """A boundary question often sits next to incidental numbers (solvent wt%, pH).

    Keep such a number only when it targets what was actually asked; otherwise it
    would ride along as if it answered the question.
    """
    if "BND" not in flags:
        return True
    return v["unit"] in expected_units(sub) or any(len(w) >= 5 and w in reader_kit.norm_text(v["label"]) for w in terms)


def build_answer(q, paras, gloss, maxev):
    """Assemble one answer record: per-number claims, explicit sub_questions[].

    When nothing can be retrieved (or only a unit-mismatched number), the record
    is marked insufficient_evidence/partial instead of a silent 'answered'.
    """
    qid, qt = q["question_id"], q["question"]
    flags = detect_flags(qt)
    typ, subs = classify_question(flags), reader_kit.split_subquestions(qt)
    first, terms = [], {}
    for si, sub in enumerate(subs, 1):
        evs, t = gather_evidence(sub, paras, gloss, typ, maxev)
        terms.update(t)
        first.append((si, sub, evs))
    cited = {ev["paragraph_id"] for _, _, e in first for ev in e}
    for i, (si, sub, evs) in enumerate(first):
        want = expected_units(sub)
        if want and not any(v["unit"] in want for _, _, e in first for ev in e for v in ev["values"]
                            if _ == si):
            # a condition sub-question ("at what temperature") often shares its sentence
            # with a sibling; adopt that paragraph if it carries a value in the wanted unit
            extra = [ev for _, _, e in first if _ != si for ev in e
                     if any(v["unit"] in want for v in ev["values"])
                     and ev["quote"] not in [x["quote"] for x in evs]]
            if extra:
                first[i] = (si, sub, (evs + extra[:1]) if evs else extra[:2])
                TRACE["changes"].append({"item": f"{qid}-S{si}", "change": "借用兄弟子问所在段落里带该单位数值的证据"})
                continue
        if evs:
            continue
        fb = borrowed_evidence(qt, sub, paras, gloss, typ, cited)
        if fb:
            first[i] = (si, sub, fb)
            TRACE["changes"].append({"item": f"{qid}-S{si}", "change": "子问没有独立命中，改借同句或同段证据"})
    if "BND" in flags:  # boundary question: the cited evidence must actually mention the asked feature
        for i, (si, sub, evs) in enumerate(first):
            if not evs:
                continue
            _, dfq = term_doc_freq(sub, paras, gloss)
            feats = [x for x in dfq if dfq[x] <= 1 and len(x) >= 4]
            if feats and not any(x in reader_kit.norm_text(ev["quote"]) for ev in evs for x in feats):
                first[i] = (si, sub, [])
                TRACE["changes"].append({"item": f"{qid}-S{si}",
                                     "change": "边界题：命中段落没有涉及被问特征，按未报告处理"})
    for i, (si, sub, evs) in enumerate(first):  # unit gate: kept numbers must use the unit the sub-question asks for
        want = expected_units(sub)
        if want and evs and "NUM" in flags and \
                not any(v["unit"] in want for ev in evs for v in ev["values"]):
            found = sorted({v["unit"] for ev in evs for v in ev["values"]})
            TRACE["uncertainties"].append({"type": "unit_mismatch", "question_id": qid,
                                       "detail": f"子问所问单位 {'/'.join(want)}，命中段落只有 {'/'.join(found) or '无单位数值'}",
                                       "paragraphs_searched": len(paras)})
            first[i] = (si, sub, [])
            TRACE["changes"].append({"item": f"{qid}-S{si}", "change": "命中段落数值单位与被问量不一致，按未报告处理"})
    claims, unans, conds, subs_out, all_ev, subev, seen = [], [], [], [], [], {}, {}
    for si, sub, evs in first:
        cids, pids = [], []
        for ei, ev in enumerate(evs):
            c = ev["condition"]
            if c and f"{c}（{ev['paragraph_id']}）" not in conds:
                conds.append(f"{c}（{ev['paragraph_id']}）")
            if ev["quote"] not in [x["quote"] for x in all_ev]:
                all_ev.append(ev)
            pids.append(ev["paragraph_id"])
            n_before = len(claims)
            for v in ev["values"]:
                if not value_matches_question(v, sub, terms, flags):
                    continue
                if "NUM" not in flags and ei > 0:
                    continue  # mechanism/boundary question: take numbers from the top-ranked paragraph only
                key = (v["value"], v["unit"], ev["paragraph_id"])
                if key in seen:
                    cids.append(seen[key])
                    continue
                cid = f"{qid}-S{si}-N{len(claims) + 1}"
                claims.append(make_claim(qid, cid, f"{v['label']} = {v['value']} {v['unit']}".strip(),
                                      "reported", [ev], [c] if c else []))
                seen[key] = cid
                cids.append(cid)
            if len(claims) == n_before:  # no number came out of this quote, so cite the quote itself as the claim
                cid = f"{qid}-S{si}-C{len(claims) + 1}"
                claims.append(make_claim(qid, cid, f"原文（{ev['section']}，{ev['paragraph_id']}）：{ev['quote']}",
                                      "reported", [ev], [c] if c else []))
                cids.append(cid)
        subev[si] = evs
        has_num = any(ev["values"] for ev in evs)
        if evs and "NUM" in flags and not has_num:
            unans.append({"part": sub, "question_id": qid, "reason": "numeric_value_not_reported",
                          "missing": "该子问只有定性表述，没有给出问题所问的数值",
                          "needed": "结果表、带单位的数值句，或摘要中给出的数字"})
        if not evs:
            unans.append({"part": sub, "question_id": qid, "reason": "not_reported_after_full_search",
                          "missing": "该子问在供给材料里没有可用原文依据（已检索全部段落）",
                          "needed": "对应章节/表格/图注原文；若论文确实未报告，需作者说明或补充材料"})
        st = "answered" if evs and not ("NUM" in flags and not has_num) else \
            ("partial" if evs else "insufficient_evidence")
        subs_out.append({"index": si, "question": sub, "status": st, "claim_ids": cids,
                         "evidence_paragraph_ids": list(dict.fromkeys(pids))})
    absence = not all_ev
    if absence:
        zero = [k for k in terms if not any(reader_kit.norm_text(p["text"]).count(k) for p in paras)]
        TRACE["uncertainties"].append({"type": "not_reported" if zero else "low_recall", "question_id": qid,
                                   "detail": f"未命中的检索词 {len(zero)}/{len(terms)}；这不等于论文没有该内容",
                                   "zero_hit_terms": zero[:10], "paragraphs_searched": len(paras)})
        TRACE["pending"].append(f"{qid}: 全篇未找到匹配证据，请人工确认「未报告」结论并复核检索词")
        claims.append(make_claim(qid, f"{qid}-ABS1",
                              f"供给材料未报告该问题所求内容（全篇 {len(paras)} 段、{len(terms)} 个检索词均无可用命中）",
                              "inferred", []))
    other = next((ev for ev in all_ev[1:] if ev["paragraph_id"] != all_ev[0]["paragraph_id"]), None)
    if typ in ("INT", "MECH") and other:
        claims.append(make_claim(qid, f"{qid}-INT1",
                              f"跨段落整合：{all_ev[0]['paragraph_id']} 提供方法或条件侧，"
                              f"{other['paragraph_id']} 给结果侧（两段合并推出，非单段直述）",
                              "inferred", [all_ev[0], other],
                              [c for c in (all_ev[0]["condition"], other["condition"]) if c]))
        TRACE["changes"].append({"item": qid, "change": "新增跨段落 inferred 论断"})
    L = []
    if absence:
        L.append(f"供给材料未报告该问题所需内容：全部 {len(paras)} 段已检索、没有可用原文依据，"
                 "不补外部知识（缺口见 unanswered_parts）。")
    for so in subs_out:
        e = subev.get(so["index"], [])
        L.append(f"【子问{so['index']}】{so['question']}")
        if not e:
            L.append("该子问没有匹配到原文（见 unanswered_parts）。")
            continue
        vals = [x for ev in e for x in ev["values"] if value_matches_question(x, so["question"], terms, flags)]
        want = expected_units(so["question"])
        picked = [x for x in vals if x["unit"] in want] if want else []
        kv = list(dict.fromkeys(f"{x['label']} = {x['value']} {x['unit']}".strip()
                                for x in (picked or vals)))
        if kv:
            L.append("可核对数值：" + "；".join(kv) + "。")
        L.append("原文引证：" + "；".join(f'"{ev["quote"]}"（{ev["paragraph_id"]}）' for ev in e))
        cs = list(dict.fromkeys(ev["condition"] for ev in e if ev["condition"]))
        if cs:
            L.append("适用条件：" + "；".join(cs) + "。")
        if any(ev.get("negation") and any(w in reader_kit.norm_text(ev["quote"]) for w in terms if len(w) >= 5)
               for ev in e):
            L.append("判定：引文明确写出该项未开展/未报告，这是原文交代的边界而非漏答。")
        elif typ == "BND":
            L.append("判定：材料只是相关提及，没有给出问题要求的具体项；不能据此推断为「不存在」。")
    pids = list(dict.fromkeys(ev["paragraph_id"] for ev in all_ev))
    status = "insufficient_evidence" if absence else ("partial" if unans else "answered")
    return {"question_id": qid, "question": qt, "answer": "\n".join(L), "conditions": conds,
            "status": status, "question_type": typ, "flags": sorted(flags),
            "sub_questions": subs_out, "claims": claims, "unanswered_parts": unans,
            "evidence_paragraph_ids": pids}


def merge_answer_patch(payload, path, paras):
    data, err = reader_kit.load_json(path)
    ed = data.get("answers") if isinstance(data, dict) else None
    if not ed:
        TRACE["degradations"].append({"item": "answers_patch.json", "reason": err, "impact": "保留原始回答"})
        return payload
    n = 0
    for a in payload["result"]["answers"]:
        pt = ed.get(a["question_id"])
        if not pt:
            continue
        pt = {"answer": pt} if isinstance(pt, str) else pt
        ev = " ".join(e["quote"] for c in a["claims"] for e in c.get("evidence") or [])
        if pt.get("answer") and all(x in ev for x in re.findall(r"\d+(?:\.\d+)?", str(pt["answer"]))):
            a["answer"], n = str(pt["answer"]).strip(), n + 1
            if isinstance(pt.get("conditions"), list):
                a["conditions"] = [str(x) for x in pt["conditions"]]
        else:
            TRACE["pending"].append(f'{a["question_id"]}: 改写稿中的数字未出现在引文里，已拒收')
    TRACE["changes"].append({"item": "answers_patch", "change": f"合并 {n} 条回答"})
    return payload


def process_case(inp, out, args):
    cpath = reader_kit.locate_case(inp, args.case)
    case, err = (None, None)
    if cpath:
        case, err = reader_kit.load_json(cpath)
    if case is None:
        TRACE["errors"].append({"stage": "load_case", "error": err or "case.json not found", "looked_in": str(inp)})
        TRACE["missing"].append("case.json（/input 下未找到可解析的案例文件）")
        case = {}
    meta = reader_kit.extract_meta(case)
    paras = reader_kit.gather_paragraphs(case)
    questions, qwhere = reader_kit.gather_questions(case)
    gloss = reader_kit.load_term_map()
    answers, all_unans = [], []
    if not questions:
        TRACE["degradations"].append({"item": "questions", "reason": "无问题清单", "impact": "answers 为空，契约字段仍完整"})
    for q in questions:
        try:
            a = build_answer(q, paras, gloss, 3)
        except Exception as e:  # noqa: BLE001
            TRACE["errors"].append({"stage": "answer", "question_id": q["question_id"],
                                "error": f"{type(e).__name__}: {e}"})
            a = {"question_id": q["question_id"], "question": q["question"], "conditions": [], "status": "partial",
                 "claims": [], "answer": "该题处理中断，未能生成回答（详见 errors）。",
                 "unanswered_parts": [{"part": q["question"], "reason": "internal_error", "needed": f"{e}"}],
                 "evidence_paragraph_ids": [], "sub_questions": [], "question_type": "GEN", "flags": []}
        answers.append(a)
        all_unans.extend(a["unanswered_parts"])
    claims = [c for a in answers for c in a["claims"]]
    for c in claims:
        c["source_id"] = meta["paper_id"]
        for e in c.get("evidence", []):
            e["paper_id"] = meta["paper_id"]
    st = [a["status"] for a in answers]
    overall = ("input_error" if not questions else "ok" if st and set(st) == {"answered"} else
               "insufficient_evidence" if st and set(st) == {"insufficient_evidence"} else "partial")
    cov = reader_kit.build_coverage(paras, answers)
    cn = reader_kit.summarize_counts(answers, claims)
    payload = {
        "case_id": meta["case_id"], "paper_id": meta["paper_id"],
        "material_version": meta["material_version"], "status": overall,
        "summary": (f"{cn['questions']} 题（{cn['sub_questions']} 个子问）：answered {cn['answered']}、"
                    f"partial {cn['partial']}、insufficient_evidence {cn['insufficient_evidence']}；"
                    f"claims {cn['claims']}（含数值 claim {cn['numeric_claims']}），"
                    f"引文命中 {cn['evidence_verified']}/{cn['evidence']}；阅读 {cov.get('paragraphs_indexed')} 段"
                    f"（{cov.get('read_status')}）"),
        "result": {"answers": answers, "unanswered_parts": all_unans, "coverage": cov},
        "answers": answers, "unanswered_parts": all_unans, "coverage": cov,
        "claims": claims, "uncertainties": TRACE["uncertainties"], "uncertainty": TRACE["uncertainties"],
        "sources": ([{"type": "input_case", "path": str(cpath), "sha256_16": reader_kit.digest16(cpath),
                      "paragraphs": len(paras), "questions": len(questions)}] if cpath else []),
        "pending_human": TRACE["pending"], "errors": TRACE["errors"], "degradations": TRACE["degradations"],
        "changes": TRACE["changes"], "counts": cn,
        "primary_result": "/app/output/result.json",
        "evidence": list({(e.get("paragraph_id"), e.get("quote")): e for c in claims
                          for e in c.get("evidence") or []}.values()),
        "method_notes": {"pipeline": "load case > map terms > rank paragraphs > quote sentences > assemble claims > audit",
                         "quote_policy": "引文从原文字符区间切片并逐字校验（15–60 词，同段内按句延伸）；全篇零命中记为未报告",
                         "claim_policy": "每个报告数值单独一条 claim（label = value unit）；跨段合并另立 inferred 论断"},
        "runtime": {"script_seconds": round(time.time() - START_CLOCK, 2), "model_requests_by_script": 0,
                    "python": sys.version.split()[0], "version": PKG_VERSION, "truncated": False,
                    "budget": {"wall_limit_s": 900, "questions_processed": len(answers),
                               "paragraphs_scanned": len(paras), "max_evidence_per_subq": 3},
                    "budget_note": "脚本不发起模型请求，单次调用秒级完成且不截断"},
        "contract_keys": list(case["output_contract"]) if isinstance(case.get("output_contract"), dict) else [],
        "question_ids": [q["question_id"] for q in questions],
    }
    payload = reader_kit.fill_contract(payload, case.get("output_contract"))
    if args.apply:
        payload = merge_answer_patch(payload, args.apply, paras)
        payload["claims"] = [c for a in payload["result"]["answers"] for c in a["claims"]]
        payload["counts"] = reader_kit.summarize_counts(payload["result"]["answers"], payload["claims"])
    return payload, paras, meta


def audit_payload(payload, paras, out):
    txt = {p["paragraph_id"]: p["text"] for p in paras}
    ans = (payload.get("result") or {}).get("answers") or []
    cl, keys = payload.get("claims") or [], payload.get("contract_keys") or []
    evs = [e for a in ans for c in a.get("claims") or [] for e in c.get("evidence") or []]
    bad = [e.get("paragraph_id") for e in evs if e.get("quote") not in txt.get(e.get("paragraph_id"), "")]
    off = [e.get("paragraph_id") for e in evs
           if e.get("quote") in txt.get(e.get("paragraph_id"), "")
           and txt[e["paragraph_id"]].find(e["quote"]) != e.get("char_start")]
    rc = reader_kit.summarize_counts(ans, cl)
    ck = {"result_json_parses": bool(payload),
          "contract_keys_echoed": all(k in payload for k in keys),
          "questions_covered": sorted(a.get("question_id") for a in ans) == sorted(payload.get("question_ids") or []),
          "enums_valid": all(a.get("status") in VALID_STATUS for a in ans) and
          all(c.get("kind") in ("reported", "inferred") for c in cl),
          "quotes_verbatim": not bad,
          "char_offsets_match": not off,
          "paragraph_ids_exist": all(e.get("paragraph_id") in txt for e in evs),
          "gaps_for_non_answered": all(a.get("unanswered_parts") for a in ans
                                       if a.get("status") in ("partial", "insufficient_evidence")),
          "sub_questions_numbered": all(a.get("sub_questions") and
                                        [s.get("index") for s in a["sub_questions"]] ==
                                        list(range(1, len(a["sub_questions"]) + 1)) for a in ans),
          "numeric_claims_for_numeric_q": all(
              any(" = " in str(c.get("text", "")) for c in a.get("claims") or []) or
              a.get("status") != "answered" for a in ans
              if "NUM" in (a.get("flags") or []) and "BND" not in (a.get("flags") or [])),
          "coverage_present": bool((payload.get("result") or {}).get("coverage")),
          "runtime_budget_present": bool((payload.get("runtime") or {}).get("budget")),
          "numeric_values_trace_to_quotes": not [c.get("claim_id") for c in cl
                                                 if reader_kit.digit_traceable(c) is False]}
    num_claims = [c for c in cl if reader_kit.digit_traceable(c) is not None]
    num_bad = [c.get("claim_id") for c in num_claims if reader_kit.digit_traceable(c) is not True]
    rep = {"ok": all(ck.values()), "checks": [{"check": k, "ok": v} for k, v in ck.items()],
           "fails": [k for k, v in ck.items() if not v], "unmatched_quotes": bad[:5],
           "offset_mismatch": off[:5], "stats": rc, "quote_hit_rate": rc["quote_hit_rate"],
           "numeric_trace": {"checked": len(num_claims), "traced": len(num_claims) - len(num_bad),
                             "unmatched_claim_ids": num_bad[:5]},
           "quote_words": {"min": rc.get("quote_words_min"), "max": rc.get("quote_words_max"),
                           "below_15": rc.get("quotes_below_15_words"),
                           "note": "短句属自然句长，不强制截断；不影响逐字命中"}}
    reader_kit.save_json(out / "verify_report.json", rep)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(prog="run_reader.py", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description="source-bound paper QA: answer supplied questions with verbatim paragraph evidence.",
                                 epilog="Always exits 0; a placeholder result.json is written before parsing and re-audited at the end.")
    ap.add_argument("--input", default=None, help="folder holding the case file (default /input, fallback <cwd>/input)")
    ap.add_argument("--out", default=None, help="folder for the result bundle (default /app/output, fallback <cwd>/output)")
    ap.add_argument("--case", default=None, help="explicit case json path, overrides auto-discovery")
    ap.add_argument("--apply", default=None, help="merge an agent-written answer patch json (numbers must exist in the quotes)")
    ap.add_argument("--quiet", action="store_true", help="do not print the one-line run summary")
    ap.add_argument("--version", action="version", version=f"source-bound-paper-qa {PKG_VERSION}")
    args = ap.parse_args(argv)

    def choose_out_dir(path):
        for p in ([Path(path)] if path else []) + [Path("/app/output"), Path.cwd() / "output"]:  # noqa: E501
            try:
                p.mkdir(parents=True, exist_ok=True)
                (p / ".w").write_text("x", encoding="utf-8")
                (p / ".w").unlink()
                return p
            except Exception:  # noqa: BLE001
                continue
        return Path.cwd()

    out = choose_out_dir(args.out)
    inp = Path(args.input) if args.input else Path("/input")
    if not inp.is_dir():
        inp = Path.cwd() / "input"

    reader_kit.save_json(out / "result.json", reader_kit.placeholder_payload())  # placeholder first: a crash still leaves a readable result.json
    payload, paras, meta = reader_kit.placeholder_payload(), [], {}
    try:
        payload, paras, meta = process_case(inp, out, args)
    except Exception as e:  # noqa: BLE001
        TRACE["errors"].append({"stage": "run", "error": f"{type(e).__name__}: {e}"})
        payload = reader_kit.placeholder_payload()
        payload["status"], payload["errors"] = "input_error", TRACE["errors"]
    try:
        reader_kit.save_json(out / "result.json", payload)
        answers = (payload.get("result") or {}).get("answers") or []
        reader_kit.save_json(out / "paragraph_index.json", {
            "case_id": meta.get("case_id"), "paper_id": meta.get("paper_id"), "not_supplied": TRACE["missing"],
            "paragraphs": [{"paragraph_id": p["paragraph_id"], "section": p["section"],
                            "kind": p.get("kind"), "text": p["text"]} for p in paras]})
        reader_kit.save_json(out / "answers.json", {
            "case_id": meta.get("case_id"), "paper_id": meta.get("paper_id"),
            "material_version": meta.get("material_version"),
            "claims": payload.get("claims") or [], **payload["result"]})
        reader_kit.write_evidence_csv(out, meta, answers)
        if Path("/app").is_dir():
            try:
                reader_kit.save_json(Path("/app/answers.json"), {"case_id": meta.get("case_id"), "answers": answers,
                                                      "claims": payload.get("claims") or []})
            except Exception as e:  # noqa: BLE001
                TRACE["degradations"].append({"item": "/app/answers.json", "reason": str(e), "impact": "未写出"})
    except Exception as e:  # noqa: BLE001
        TRACE["errors"].append({"stage": "emit", "error": f"{type(e).__name__}: {e}"})
        try:
            reader_kit.save_json(out / "result.json", payload)
        except Exception:  # noqa: BLE001
            pass
    rep = {"ok": None, "fails": []}
    try:
        rep = audit_payload(payload, paras, out)
    except Exception as e:  # noqa: BLE001
        TRACE["errors"].append({"stage": "selfcheck", "error": f"{type(e).__name__}: {e}"})
    try:  # final flush: the audited payload is the last unconditional write
        payload["verification"] = rep
        payload["errors"], payload["degradations"] = TRACE["errors"], TRACE["degradations"]
        payload["pending_human"] = TRACE["pending"]
        reader_kit.save_json(out / "result.json", payload)
    except Exception as e:  # noqa: BLE001
        TRACE["errors"].append({"stage": "finalize", "error": f"{type(e).__name__}: {e}"})
    assets_note = "assets: 0/5"
    try:  # five verifiable assets: additive only, failures degrade, exit code still 0
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location("reader03_assets", Path(__file__).resolve().parent / "assets.py")
        _mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
        _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
        _done = _mod.finalize(inp, out, stage="build")
        assets_note = "assets: %d/5" % len(_done.get("assets") or [])
    except Exception as e:  # noqa: BLE001
        TRACE["degradations"].append({"item": "assets", "reason": f"{type(e).__name__}: {e}", "impact": "五件资产未生成"})
        try:
            reader_kit.save_json(out / "result.json", payload)
        except Exception:  # noqa: BLE001
            pass
    if not args.quiet:
        c = payload.get("counts", {})
        print(f"[source-bound-paper-qa {PKG_VERSION}] case={payload.get('case_id')} status={payload.get('status')} "
              f"q={c.get('questions')} subq={c.get('sub_questions')} claims={c.get('claims')} "
              f"quote_hit={c.get('quote_hit_rate')} num_trace={c.get('numeric_trace_rate')} "
              f"audit={rep.get('ok')} fails={rep.get('fails')} | {assets_note}")
    return 0


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        pass
    sys.exit(0)
