#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evidence-grounded writing pipeline (writing-03).  Turns a writing task plus source material into three mutually joinable deliverables -- ``claims.json`` -> ``evidence_table.json`` -> ``evidence_driven_draft.md`` -- and backfills ``result.json``. Standard library only, offline, partial result written first, exit code always 0. """
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit import (VERSION, NEG_HINT, POS_HINT, units_of, claim_kind, ref_ent, bag_of, abstract_only, overlap, grade_row, ref_text, scan_inputs, soften, sentences, trim_cites, wo_checks, side_records)

CONTRACT_FIELDS = ["case_id", "deliverable", "preserved_facts", "evidence_map", "change_log"]

PHRASES = { "zh": { "t": "证据支撑稿（{c}）", "lim": "证据边界", "ref": "参考文献", "h": {"高": "多项证据一致", "中": "研究提示", "低": "初步线索", "不足": "材料不足以判断"}, "cf": "但材料亦有相反结果：", "uc": "（待核）", "lm": "低强度或证据不足的论断仅作线索（%s）|材料内部存在未合并的冲突结果（%s）|" "部分来源仅摘要可核，未回原文确认|著录信息未联网核验", "rm": "（无著录；{s}，{l}）", "rs": "材料内文献表", "rt": "按首次引用编号；未给 DOI 不补写", },
    "en": { "t": "Evidence draft ({c})", "lim": "Boundaries", "ref": "References", "h": {"高": "Evidence indicates that", "中": "Studies suggest that", "低": "Preliminary evidence suggests", "不足": "The material cannot determine"}, "cf": "However, contrary findings exist: ", "uc": " (to be verified)",
        "lm": "Weak claims serve as leads only (%s)|Unresolved conflicting findings kept (%s)|"
              "Abstract-only sources not checked against full text|Bibliographic data not verified online",
        "rm": "(no record; source {s})", "rs": "Reference list as given",
        "rt": "First-citation order; no invented DOI",
    },
}


def dump_json(path, payload):
    """Atomic JSON write so a crash never leaves a truncated result."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)


def save_text(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, "utf-8")


def make_claims(docs, units, case, instr):
    """Cut claims: sentence-level from the draft, otherwise evidence-bearing material sentences."""
    claims = []
    drafts = [doc for doc in docs if doc["kind"] == "draft" and doc["text"].strip()]
    if drafts:
        source = drafts[0]
        for unit in units:
            text = unit["text"].strip()
            if unit["doc"] != source["doc_id"] or len(text) < 8:
                continue
            if re.match(r"^(\||-{3,}|\[\d+\]\s)", text):
                continue
            claims.append({ "claim_id": "C%03d" % (len(claims) + 1), "text": text, "core": trim_cites(text), "type": claim_kind(text), "location": "draft:%s %s" % (source["path"], unit["loc"]), "uid": unit["uid"], "doc": unit["doc"], })
        return claims, "revise", source

    topic = (instr + " " + json.dumps(case.get("source") or {}, ensure_ascii=False))[:6000]
    topic_tokens = bag_of(topic)
    ref_docs = {doc["doc_id"] for doc in docs if doc["kind"] == "references"}
    ranked = sorted( ((overlap(topic, unit["text"], topic_tokens) + (0.04 if re.search(r"\d", unit["text"]) else 0.0), unit) for unit in units if unit["doc"] not in ref_docs and len(unit["text"]) >= 20 and not re.match(r"^(参考文献|references?|doi|https?)", unit["text"], re.I)), key=lambda pair: -pair[0])
    length_hint = re.search(r"(\d{2,4})\s*(?:字|words?|词|characters?)", topic, re.I)
    target = max(3, min(12, int(round((int(length_hint.group(1)) if length_hint else 240) / 30.0))))
    picked, per_doc = [], {}
    for score, unit in ranked:
        if len(picked) >= target:
            break
        if per_doc.get(unit["doc"], 0) >= 2:
            continue
        if any(overlap(unit["text"], kept["text"]) > 0.8 for kept in picked):
            continue
        per_doc[unit["doc"]] = per_doc.get(unit["doc"], 0) + 1
        picked.append(unit)
    for unit in picked:
        claims.append({ "claim_id": "C%03d" % (len(claims) + 1), "text": unit["text"], "core": trim_cites(unit["text"]), "type": claim_kind(unit["text"]), "location": unit["loc"], "uid": unit["uid"], "doc": unit["doc"], })
    return claims, "synthesize", None


def map_evidence(claims, units, docs, refs):
    """Link each claim to verbatim source passages plus explicit conflicts."""
    doc_map = {doc["doc_id"]: doc for doc in docs}
    pool = [unit for unit in units if doc_map[unit["doc"]]["kind"] == "material"]
    ref_to_doc = {}
    for ref in refs:
        candidates = [ (1.0 if (ref["doi"] and ref["doi"] in doc["text"]) else overlap(ref["body"][:150], doc["text"][:400]), doc["doc_id"]) for doc in docs if doc["kind"] != "references"]
        candidates = [pair for pair in candidates if pair[0] >= 0.45]
        if candidates:
            ref_to_doc[ref["num"]] = max(candidates)[1]

    rows = []
    for claim in claims:
        claim_tokens = bag_of(claim["core"])
        anchored = {ref_to_doc[int(mark)] for mark in re.findall(r"[\[［](\d{1,3})[\]］]", claim["text"]) if int(mark) in ref_to_doc}
        scored = sorted(((overlap(claim["core"], unit["text"], claim_tokens), unit) for unit in pool), key=lambda pair: -pair[0])
        preferred = [unit for score, unit in scored if unit["doc"] in anchored]
        base = (1.0, preferred[0]) if preferred else (scored[0] if scored else (0.0, None))
        floor = 0.05 if preferred else 0.16
        if base[1] is None or base[0] < floor:
            rows.append({ "claim_id": claim["claim_id"], "claim": claim["core"], "source_id": None, "locator": None, "quote": None, "source_type": None, "strength": "不足", "strength_basis": {"reason": "无>=%.2f 重叠段落" % floor}, "support_scope": "无直接支撑", "conflicts": [], "verified": False, "rationale": "未匹配到来源，需补证或改写", })
            continue
        chosen = [base[1]]
        for score, unit in scored:
            if unit["uid"] in {item["uid"] for item in chosen}:
                continue
            same_doc = unit["doc"] in {item["doc"] for item in chosen}
            if (unit["doc"] in anchored or score >= max(floor, base[0] * 0.72)) and not same_doc:
                chosen.append(unit)
                if len(chosen) >= 3:
                    break
        conflicts = [{ "source_id": unit["doc"], "locator": unit["loc"], "quote": unit["text"], "similarity": round(score, 2), "why": "主题重叠但结论方向相反", } for score, unit in scored if score >= 0.40 and unit["uid"] not in {item["uid"] for item in chosen}
            and bool(NEG_HINT.search(unit["text"])) != bool(NEG_HINT.search(claim["core"]))
            and (POS_HINT.search(unit["text"]) or NEG_HINT.search(unit["text"]))]
        for unit in chosen:
            doc = doc_map[unit["doc"]]
            level, why, basis = grade_row(unit["text"], doc["text"], len(chosen), bool(conflicts), abstract_only(doc))
            score = overlap(claim["core"], unit["text"], claim_tokens)
            scope = "直接支撑" if score >= 0.3 else "部分支撑（范围不一致）"
            if basis["sample_size"]:
                scope += "；n~%d" % basis["sample_size"]
            if level in ("低", "不足"):
                scope += "；仅限该研究条件"
            rows.append({ "claim_id": claim["claim_id"], "claim": claim["core"], "source_id": unit["doc"], "source_path": doc["path"], "locator": unit["loc"], "quote": unit["text"], "source_type": basis["design"], "strength": level, "strength_basis": basis,
                "rationale": why + ("；冲突下调" if conflicts else ""), "conflicts": conflicts[:3],
                "verified": True, "abstract_only": abstract_only(doc), "support_scope": scope,
            })
    return rows


def compose(docs, claims, rows, mode, draft_doc, case_id, lang, case, refs):
    """Render the draft: hedged claims, resolvable citation numbers, conflicts kept."""
    words = PHRASES[lang]
    doc_map = {doc["doc_id"]: doc for doc in docs}
    cites, change_log = {}, []
    rows_by_claim = {}
    for row in rows:
        rows_by_claim.setdefault(row["claim_id"], []).append(row)
    rank = {"不足": 0, "低": 1, "中": 2, "高": 3}

    def cite(ids):
        numbers = {cites.setdefault(src, len(cites) + 1) for src in ids}
        return "".join("[%d]" % n for n in sorted(numbers))

    def sourced(claim):
        return [row for row in rows_by_claim.get(claim["claim_id"], []) if row.get("quote")]

    def level_of(claim):
        backed = sourced(claim)
        return min((row["strength"] for row in backed), key=lambda lv: rank[lv]) if backed else "不足"

    for claim in claims:
        claim["_t"], downgrades = soften(claim["core"])
        for action, before, after, reason in downgrades:
            change_log.append({ "change_id": "CH%03d" % (len(change_log) + 1), "claim_id": claim["claim_id"], "action": action, "original_quote": before, "revised_quote": after, "reason": reason, "locator": claim["location"], "human_confirm": True, })

    def emit(claim):
        backed, level = sourced(claim), level_of(claim)
        body = re.sub(r"\s*(?:\[\d{1,3}\]|［\d{1,3}］|[。.；;])+\s*$", "", claim["_t"]).rstrip()
        if not backed:
            return re.sub(r"[。.]$", "", body) + words["uc"]
        if level in ("低", "不足") and not re.search(r"(可能|提示|初步|尚|may|suggest|prelim)", body, re.I):
            body = words["h"][level] + ("，" if lang == "zh" else " ") + body
        body += cite(row["source_id"] for row in backed) + ("。" if lang == "zh" else ".")
        conflicts = [item for row in backed for item in (row.get("conflicts") or [])]
        if conflicts and " " not in body[-3:]:
            body += (" " + words["cf"] + re.sub(r"[。.]$", "", conflicts[0]["quote"][:150]) + cite(item["source_id"] for item in conflicts[:2]) + ("。" if lang == "zh" else "."))
        return body

    joiner = "" if lang == "zh" else " "
    lines = ["# " + words["t"].format(c=case_id), ""]
    source_meta = case.get("source")
    if isinstance(source_meta, dict) and any(source_meta.values()):
        lines += ["> " + "；".join("%s=%s" % (key, val) for key, val in source_meta.items() if val), ""]

    if mode == "revise" and draft_doc:
        by_text = {claim["text"]: claim for claim in claims}
        lines += ["<!-- 修订稿：保留原块结构；逐句补证、按强度调语气、过度推断已下调 -->", ""]
        for block in re.split(r"\n\s*\n", draft_doc["text"]):
            stripped = block.strip()
            if not stripped:
                continue
            if re.match(r"^#{1,6}\s", stripped):
                lines.append(stripped)
            else:
                lines.append(joiner.join(emit(by_text[sentence]) if sentence in by_text else sentence for sentence in sentences(stripped)))
            lines.append("")
    else:
        paragraph = []
        for claim in claims:
            paragraph.append(emit(claim))
            if len(paragraph) >= 3:
                lines += [joiner.join(paragraph), ""]
                paragraph = []
        if paragraph:
            lines += [joiner.join(paragraph), ""]

    boundary = words["lm"].split("|")
    weak = [claim["claim_id"] for claim in claims if not [row for row in rows_by_claim.get(claim["claim_id"], []) if row.get("strength") in ("高", "中")]]
    conflicted = sorted({row["claim_id"] for row in rows if row.get("conflicts")})
    lines += ["## " + words["lim"], ""]
    if weak:
        lines.append("- " + boundary[0] % "、".join(weak[:8]))
    if conflicted:
        lines.append("- " + boundary[1] % "、".join(conflicted))
    if any(row.get("abstract_only") for row in rows):
        lines.append("- " + boundary[2])
    lines += ["- " + boundary[3], "", "## " + words["ref"], "", "<!-- %s -->" % words["rt"]]
    for doc_id, number in sorted(cites.items(), key=lambda pair: pair[1]):
        lines += ["[%d] %s" % (number, ref_text(doc_map.get(doc_id, {}), refs, number, words)), ""]
    if refs:
        lines += ["## " + words["rs"], ""] + ["- " + ref["raw"] for ref in refs]
    return "\n".join(lines).rstrip() + "\n", change_log, cites


def execute(args):
    started = time.time()
    errors, grads, pending, sources = [], [], [], []
    case, con, case_id, instr = {}, {}, "UNKNOWN", ""

    def flag(issue, detail, needed, source_id=None):
        pending.append({"id": "P%03d" % (len(pending) + 1), "issue": issue, "detail": detail, "needed": needed, "source_id": source_id})

    def safe(stage, worker, default):
        try:
            return worker()
        except Exception as exc:
            errors.append({"stage": stage, "type": type(exc).__name__, "detail": str(exc)[:200]})
            return default

    ind = next((Path(cand) for cand in ([args.input] if args.input else []) + ["/input", "input"] if cand and Path(cand).is_dir()), None)
    out = Path(args.output or "/app/output")
    try:
        out.mkdir(parents=True, exist_ok=True)
        probe = out / ".probe"
        probe.write_text("x", "utf-8")
        probe.unlink()
    except Exception:
        out = Path.cwd() / "output"
        out.mkdir(parents=True, exist_ok=True)

    def write_partial():
        payload = {"case_id": case_id, "status": "partial", "skill_version": VERSION, "sources": sources}
        for key in con:
            payload[key] = None if key in CONTRACT_FIELDS else con[key]
        for key in CONTRACT_FIELDS:
            payload.setdefault(key, [] if key != "deliverable" else None)
        payload["case_id"] = case_id
        dump_json(out / "result.json", payload)

    write_partial()
    if ind is None:
        errors.append({"stage": "input", "type": "no_input_dir", "detail": "无 input"})
    else:
        for cand in [ind / "case.json"] + sorted(ind.glob("*case*.json")):
            if cand.is_file() and not case:
                case = safe("input", lambda: json.loads( cand.read_text(encoding="utf-8", errors="ignore")), {})
        if not case:
            errors.append({"stage": "input", "type": "no_case_json", "detail": "无 case"})
        if isinstance(case.get("output_contract"), dict):
            con = dict(case["output_contract"])
        case_id = str(case.get("case_id") or case.get("id") or "UNKNOWN")
        instr = " ".join(str(case.get(key) or "") for key in ("task_instruction", "task", "instruction", "prompt", "goal"))
        for task_name in ("task.md", "task.txt"):
            task_file = ind / task_name
            if task_file.is_file():
                instr += " " + task_file.read_text(encoding="utf-8", errors="ignore")[:4000]
                break
    if not con:
        con = {key: None for key in CONTRACT_FIELDS}
        errors.append({"stage": "contract", "type": "missing_output_contract", "detail": "兜底 5 字段"})
    write_partial()

    docs = safe("discover", lambda: scan_inputs(ind, case) if ind else [], [])
    for doc in docs:
        sources.append({"source_id": doc["doc_id"], "path": doc["path"], "bytes": doc["bytes"], "sha256": doc["sha256"], "kind": doc["kind"], "read_method": doc["method"]})
        if doc["note"]:
            grads.append({"stage": "extract", "source_id": doc["doc_id"], "type": "extraction_partial", "detail": doc["note"]})
        if not doc["text"].strip():
            flag("无可抽文本", "%s(%s)" % (doc["path"], doc["method"]), "OCR 或人工转录", doc["doc_id"])
    if not docs:
        flag("无材料", "只有 case.json", "确认 artifacts")
    units = safe("segment", lambda: units_of(docs), [])
    refs = safe("refs", lambda: ref_ent(docs), [])
    if not refs:
        flag("无文献表", "不能核对著录", "补文献表")
    lang = "zh" if len(re.findall(r"[\u4e00-\u9fff]", " ".join(doc["text"][:800] for doc in docs) + instr)) > 20 else "en"
    claims, mode, draft_doc = safe("claims", lambda: make_claims(docs, units, case, instr), ([], "synthesize", None))
    if not claims:
        flag("无论断", "文本过短", "提供正文/摘要")
    rows = safe("evidence", lambda: map_evidence(claims, units, docs, refs), [])
    document, change_log, cites = safe( "render", lambda: compose(docs, claims, rows, mode, draft_doc, case_id, lang, case, refs), ("# %s\n\n（成稿渲染失败，claims/evidence_table 仍可用）\n" % case_id, [], {}))
    save_text(out / "evidence_driven_draft.md", document)
    save_text(out / "deliverable.md", document)

    pool = "\n".join(doc["text"] for doc in docs)
    for row in rows:
        if row.get("quote") and row["quote"] not in pool:
            row["verified"] = False
            grads.append({"stage": "verify", "source_id": row.get("source_id"), "type": "quote_not_verbatim", "detail": "%s 引文未逐字命中" % row["claim_id"]})
            flag("引文未命中", row["claim_id"], "回原文核对", row.get("source_id"))
    unsupported = [claim["claim_id"] for claim in claims if not [row for row in rows if row["claim_id"] == claim["claim_id"] and row.get("source_id")]]
    for claim_id in unsupported:
        flag("论断无支撑", claim_id, "补证或删句")

    facts = []
    for unit in units:
        for hit in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(%|‰|mg|g|kg|mL|L|μL|µm|nm|mm|cm|h|min|s|岁|例|名|倍|℃|" r"个月|年|周|天)", unit["text"]):
            facts.append({"fact_id": "F%03d" % (len(facts) + 1), "value": hit.group(0), "quote": unit["text"][:180], "locator": unit["loc"], "source_id": unit["doc"], "in_draft": hit.group(0) in document})
    facts = facts[:200]
    backed = [row for row in rows if row.get("source_id")]
    lvc = {}
    for row in rows:
        lvc[row["strength"]] = lvc.get(row["strength"], 0) + 1
    metrics = dict( claims_total=len(claims), claims_with_source=len(claims) - len(unsupported), claims_unsupported=len(unsupported), evidence_rows=len(rows), quotes_verified=sum(1 for row in backed if row.get("verified")), quotes_failed=sum(1 for row in backed if not row.get("verified")), strength_counts=lvc,
        claims_with_conflict=len({row["claim_id"] for row in rows if row.get("conflicts")}),
        overclaim_downgrades=len(change_log), distinct_sources_cited=len(cites),
        citation_markers=len(re.findall(r"\[\d+\]", document)), preserved_facts=len(facts),
        pending_human=len(pending),
        support_rate=round((len(claims) - len(unsupported)) / len(claims), 3) if claims else 0.0,
        strength_label_rate=round(sum(1 for row in rows if row.get("strength")) / len(rows), 3) if rows else 0.0,
    )
    hedge_note = "高→“%s”；中→“%s”；低→“%s”；不足→“%s”" % tuple( PHRASES[lang]["h"][level] for level in ("高", "中", "低", "不足"))
    safe("aux", lambda: side_records(out, rows, refs, hedge_note), None)
    dump_json(out / "claims.json", { "case_id": case_id, "language": lang, "count": len(claims), "claims": [{key: val for key, val in claim.items() if not key.startswith("_") and key != "uid"} for claim in claims]})
    dump_json(out / "evidence_table.json", { "case_id": case_id, "count": len(rows), "schema": "claim_id,source_id,locator,quote,strength,support_scope,conflicts,rationale,verified", "rows": rows})
    dump_json(out / "pending_human.json", {"case_id": case_id, "items": pending})

    status = ("input_error" if (not docs or not units) else "insufficient_evidence" if (not claims or not backed) else "partial" if (errors or unsupported or metrics["quotes_failed"]) else "ok")
    if time.time() - started > 780:
        grads.append({"stage": "budget", "type": "time_budget", "detail": "预算，提前 finalize"})
    evidence_map = [{ "claim_id": claim["claim_id"], "claim": claim["core"], "claim_type": claim["type"], "claim_location": claim["location"], "strength": min((row["strength"] for row in rows if row["claim_id"] == claim["claim_id"]), key=lambda lv: ["不足", "低", "中", "高"].index(lv), default="不足"),
        "evidence": [row for row in rows if row["claim_id"] == claim["claim_id"]],
        "unsupported": claim["claim_id"] in unsupported,
    } for claim in claims]
    uncertainty = ["著录与真实性未联网核验（离线），DOI/期刊/年份按材料转录"]
    if metrics["claims_with_conflict"]:
        uncertainty.append("冲突证据 %d 条，已在 conflicts 与成稿表述中保留" % metrics["claims_with_conflict"])
    if unsupported:
        uncertainty.append("未匹配来源：" + "、".join(unsupported[:6]))
    if any(row.get("abstract_only") for row in rows):
        uncertainty.append("含仅摘要可核来源，强度最高记中")

    integrity = { "claims_evidence_join": not ({row["claim_id"] for row in rows} - {claim["claim_id"] for claim in claims}), "quotes_all_verbatim": metrics["quotes_failed"] == 0, "citation_numbers_resolvable": (max((int(x) for x in re.findall(r"\[(\d{1,3})\]", document)), default=0) <= len(cites)) if cites else True, }
    result = { "case_id": case_id, "status": status, "skill": "writing-03-grounded", "skill_version": VERSION, "deliverable": document, "deliverable_path": str(out / "evidence_driven_draft.md"), "preserved_facts": facts, "evidence_map": evidence_map, "change_log": change_log,
        "claims": {"path": str(out / "claims.json"), "count": len(claims)},
        "evidence_table": {"path": str(out / "evidence_table.json"), "count": len(rows)},
        "workorder_receipt": wo_checks(case, document, cites),
        "sources": sources, "metrics": metrics, "uncertainty": uncertainty,
        "pending_human": pending, "errors": errors, "degradations": grads,
        "changes": change_log, "integrity": integrity,
        "runtime": {"script": "pipeline.py", "version": VERSION, "python": sys.version.split()[0], "seconds": round(time.time() - started, 2), "argv": sys.argv[1:], "network": "disabled"},
    }
    merged = {}
    for key, val in con.items():
        merged[key] = result[key] if key in CONTRACT_FIELDS else result.get(key, val)
    for key in CONTRACT_FIELDS:
        merged.setdefault(key, result[key])
    for key, val in result.items():
        merged.setdefault(key, val)
    merged.setdefault("integrity", {})
    merged["integrity"].update(integrity)
    merged["integrity"]["contract_backfilled"] = all(key in merged for key in con)
    dump_json(out / "result.json", merged)
    print("done %s claims=%d rows=%d quote=%d/%d pending=%d" % ( status, len(claims), len(rows), metrics["quotes_verified"], len(backed), len(pending)))


def crash_guard(output_path, exc):
    """Last-resort handler: a legal partial result.json still lands on disk."""
    try:
        out = Path(output_path)
        out.mkdir(parents=True, exist_ok=True)
        target = out / "result.json"
        current = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
        current["case_id"] = current.get("case_id") or "UNKNOWN"
        current["status"] = "partial"
        for key in ("preserved_facts", "evidence_map", "change_log", "sources", "errors", "pending_human", "changes"):
            current.setdefault(key, [])
        current.setdefault("deliverable", None)
        current.setdefault("uncertainty", ["未完成"])
        current["errors"] = current["errors"] + [ {"stage": "fatal", "type": type(exc).__name__, "detail": str(exc)[:400]}]
        dump_json(target, current)
    except Exception:
        pass


def cli(argv=None):
    parser = argparse.ArgumentParser( prog="pipeline.py", description="Evidence-grounded writing: claims -> evidence_table -> draft; stdlib only, " "offline, partial result first, exit code always 0.", epilog="Input defaults to /input (falls back to ./input); output defaults to /app/output.")
    parser.add_argument("--input", help="input directory (default /input)")
    parser.add_argument("--output", help="output directory (default /app/output)")
    parser.add_argument("--version", action="version", version="writing-03 " + VERSION)
    parsed = parser.parse_args(argv)
    try:
        execute(parsed)
    except Exception as exc:
        crash_guard(parsed.output or "/app/output", exc)
        import traceback
        traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(cli())
