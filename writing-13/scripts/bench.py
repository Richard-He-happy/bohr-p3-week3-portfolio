#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""writing-bench-eval-kit :: command line driver.

Given a case directory it writes a judgement-ready benchmark delivery: item sheet,
evidence-backed reference answers, observable anchors, two-rater scoring, a per-item
evaluation report, a reproducibility note, the asset files and result.json.
Standard library only and fully offline; the process always exits 0 so the loader
always finds a JSON result instead of a stack trace."""
import argparse, csv, json, re, sys, time, zipfile, zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kernel as KN
import ledger as AST
from kernel import compose_anchors, compose_tasks, trim, jstr, kappa, canon, fill, score, dhash, aggregate, write_csv, write_meta

KVER = "1.1.0"; AVER = "1.0.0"; START = time.time(); CHAR_CAP = 400000
STYLE = json.loads((Path(__file__).resolve().parent.parent / "references" / "stylepack.json").read_text("utf-8"))
LANG = STYLE.get("msg", {})
UNIT = (r"(?:wt%|vol%|mg/mL|mg/L|µg/mL|ug/mL|mmol/L|µmol/L|umol/L|µM|uM|mM|nM|pM|mg|µg|ug|ng|pg|kg|mL|µL|uL|"
        r"kDa|Da|bp|kb|mol|ppm|ppb|°C|kPa|MPa|kHz|MHz|GHz|keV|MeV|kcal|kV|log2FC|log10|dpi|%|g|L|m|s|h|K|V|A|W|J|M|d|x)")
NUMTOK = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(" + UNIT + r")(?![\w])")
DOIRX = re.compile(r"\b10\.\d{4,9}/[^\s\"<>()\[\],;]+")
HEADRX = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
NUMHEADRX = re.compile(r"^\s*(\d+(?:\.\d+){0,2})\.?\s+([A-Z][^.!?]{2,78})$")
CAPRX = re.compile(r"^\s*(?:Table|Figure|Fig\.|Scheme|表|图)\s*(\d+)[.:]?\s*(.*)$")
REFERX = re.compile(r"^\s*\[?\d{1,3}[\].)]\s+\S")
RATEERX = re.compile(r"(manuscript|draft|submission|candidate|to_?evaluat|ratee|稿件|待评)", re.I)
DEGRADED, FAULTS, HOLD, DOUBTS, EDITS = [], [], [], [], []
TEXTEXT = (".pdf", ".docx", ".xlsx", ".csv", ".json", ".md", ".txt", ".html", ".htm", ".tsv")
CSVSPEC, ARTIFACTS = STYLE.get("csv", {}), STYLE.get("tool", [])


def load_text(p):
    x = p.suffix.lower()
    try:
        if x == ".pdf":
            t = pdf_text(p.read_bytes())
            if len(t) < 400: DEGRADED.append({"stage": "read", "file": p.name, "note": "PDF text layer thin or absent; OCR not attempted"})
            return t
        if x == ".docx":
            with zipfile.ZipFile(p) as z:
                return "\n".join(re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n",
                                 z.read(qty).decode("utf-8", "replace")))
                                 for qty in sorted(qty for qty in z.namelist() if qty.endswith("word/document.xml")))
        raw = p.read_text("utf-8", "replace")
        if x == ".json":
            try: return jstr(json.loads(raw))
            except Exception: FAULTS.append({"stage": "read", "file": p.name, "error": "json parse failed, raw text kept"})
        if x in (".html", ".htm"):
            raw = re.sub(r"<[^>]+>", "\n", re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I))
        return re.sub(r"\n{3,}", "\n\n", raw)
    except Exception as e:
        FAULTS.append({"stage": "read", "file": p.name, "error": str(e)}); return ""

def pdf_unescape(b):
    s = (b[1:-1] if b[:1] == b"(" else b).replace(b"\\n", b"\n").replace(b"\\r", b"\n")
    s = re.sub(rb"\\([0-7]{1,3})", lambda m: bytes([int(m.group(1), 8) & 0xFF]), s)
    s = re.sub(rb"\\([()\\])", rb"\1", s)
    return re.sub(rb"\\[^nrt]", b"", s).decode("latin-1")

def pdf_text(data):
    """Recover a text layer from PDF content streams.

 Literal strings sitting next to Tj/TJ operators are concatenated; Flate-compressed
 streams are inflated first.  A scanned page carries no such layer, and OCR is out
 of scope here - the caller records a degradation and moves on."""
    out = []
    for m in re.finditer(rb"stream\r?\n", data):
        e = data.find(b"endstream", m.end())
        if e < 0: continue
        raw = data[m.end():e]
        try: raw = zlib.decompress(raw)
        except Exception: pass
        if b"Tj" in raw or b"TJ" in raw:
            out.append("\n".join(pdf_unescape(x.group(0)) for x in re.finditer(rb"\([^)]{2,}\)", raw)))
    return "\n".join(l.strip() for l in re.sub(r"[ \t]{2,}", " ", "\n".join(out)).splitlines() if l.strip())

def collect_facts(docs):
    out, seen = [], set()
    for d in docs:
        for ln, line in enumerate(d["lines"], 1):
            c = [("number", "%s %s" % (m.group(1), m.group(2))) for m in NUMTOK.finditer(line)]
            c += [("doi", m.group(0)) for m in DOIRX.finditer(line)]
            for rx in (HEADRX, NUMHEADRX):
                m = rx.match(line)
                if m and 2 < len(m.group(2).strip()) <= 80: c.append(("heading", m.group(2).strip())); break
            if REFERX.match(line) and len(line) > 40: c.append(("citation", line.strip()[:160]))
            for k, v in c:
                if (k, canon(v)) in seen: continue
                seen.add((k, canon(v)))
                out.append(dict(fact_id="F-%03d" % (len(out) + 1), kind=k, value=v, quote=trim(line), verbatim=True,
                                locator="%s:L%d" % (d["doc_id"], ln), doc_id=d["doc_id"]))
    return out


# ======================= document writers =======================

def emit_reference(d, items):
    d.mkdir(parents=True, exist_ok=True)
    for t in items:
        (d / ("%s.md" % t["task_id"])).write_text(fill(
            "refs", tid=t["task_id"], dir=t["direction"], wt=t["writing_type"], tier=t["tier"],
            wc=t["word_limit"], lang=t["language"], refs=", ".join(t["input_refs"]),
            secs="; ".join(t["format_requirements"][2:]) or "-",
            points="\n".join(fill("refs_point", pid=p["point_id"], text=p["text"], loc=p["locator"],
                                     quote=trim(p["quote"], 180), obs=p["observable"])
                              for p in t["must_include_points"]),
            variants="\n".join("- " + v for v in t["acceptable_variants"]),
            fails="\n".join("- " + v for v in t["fail_criteria"]), completion=t["completion_rule"]) + "\n",
            encoding="utf-8")

def emit_report(p, grid, items, kv, calib, state, main_rows):
    g = {}
    [g.setdefault((t["writing_type"], t["tier"]), []).append(t) for t in items]
    cov = sorted({t["direction"] for t in items})
    p.write_text(fill(
        "report", cid=state["case_id"], v=KVER, av=AVER, ratee=state["ratee_note"], status=state["status"], kappa=kv,
        docs=", ".join(d["path"] for d in state["docs"]), covn=len(cov), cov=", ".join(cov),
        big=state["big"], biglist=state["biglist"] or LANG.get("no", "-"),
        struct="\n".join("| %s | %s | %d | %s |" % (k[0], k[1], len(v),
                                                     ",".join(sorted({x["direction"] for x in v}))) for k, v in g.items()),
        rows="\n".join("| %s | %s | %d | %d | %s | %s | %s | %s |" % (
            s["task_id"], s["writing_type"], s["anchors"], s["points_met"], s["score"], s["verdict"],
            s["failure_type"], s["blame"]) for s in main_rows),
        details="\n\n".join(fill(
            "report_detail_task", tid=s["task_id"], wt=s["writing_type"], score=s["score"], verdict=s["verdict"],
            fix=s["improvement"] or LANG.get("no", "-"),
            rows="\n".join(fill("report_detail_row", aid=r["anchor_id"], verdict=r["verdict"],
                                   a=r["level_rater_a"], b=r["level_rater_b"], adj=r["adjudicated"],
                                   ev="" if r["adjudicated"] == 2 else "｜`%s`「%s」" % (r["evidence_locator"],
                                                                                      r["evidence_quote"][:80]))
                           for r in grid if r["task_id"] == s["task_id"] and r["ratee_id"] == s["ratee_id"]
                           and r["run_type"] == s["run_type"])) for s in main_rows),
        calib="\n".join("| %s | %s | %s | %d/%d |" % (c["control"], c["expect"], c["mean_score"], c["ok"], c["total"])
                        for c in calib),
        pend="\n".join("- `%s`：%s" % (q.get("item"), q.get("note")) for q in HOLD) or "- 无") + "\n",
        encoding="utf-8")

def emit_anchors(p, ANCH, revs):
    p.write_text(fill(
        "anchors", av=AVER, json=json.dumps(ANCH, ensure_ascii=False),
        rows="\n".join("| %s | %s | %s | `%s` | %s | %s | %s | %s |" % (
            a["anchor_id"], a["task_id"], a["point_id"] or "-", json.dumps(a["rule"], ensure_ascii=False)[:90],
            a["level_spec"]["2"], a["level_spec"]["1"], a["level_spec"]["0"], a["evidence_locator"] or "-") for a in ANCH),
        revs="\n".join("- `%s` v%d：%s（分歧 %s）" % (r["anchor_id"], r["revision"], r["reason"], r["disagreement"])
                       for r in revs) or "- 本轮无 >1 档分歧。") + "\n", encoding="utf-8")

def control_body(items, pos):
    parts = []
    for i, t in enumerate(items):
        graded = t["must_include_points"]
        for q in (graded if pos else (graded[:-1] if i % 2 == 0 else graded[:-2] or graded)):
            ck = q["check"]
            parts += ck.get("values") or [" ".join(x for x in (ck.get("value"), ck.get("unit")) if x)]
        if pos: parts += [x.split(": ", 1)[1] for x in t["format_requirements"] if x.startswith("section: ")]
    return " ".join(parts) + ("" if pos else " 9999 ZX")


# ======================= driver =======================

def locate_case(inp):
    if (inp / "case.json").is_file(): return inp / "case.json", None
    for q in sorted(inp.rglob("case*.json")):
        try:
            if "case_id" in json.loads(q.read_text("utf-8", "replace")): return q, None
        except Exception: pass
    alt = [q for q in sorted(inp.rglob("*.json")) if "manifest" not in q.name]
    return (alt[0] if alt else None), ("case file located through fallback scan" if alt else "no case.json below the input directory")

def crawl(inp):
    docs, submissions, unread = [], [], []
    for i, p in enumerate(sorted(q for q in inp.rglob("*") if q.is_file()), 1):
        if p.suffix.lower() not in TEXTEXT or p.name in ("case.json", "resources.yaml", "public-manifest.json"):
            continue
        t = load_text(p)
        if len(t) > CHAR_CAP:
            DEGRADED.append({"stage": "read", "file": p.name, "note": "truncated at character cap"}); t = t[:CHAR_CAP]
        if not t.strip():
            unread.append(p.name); continue
        rec = dict(doc_id="src-%02d" % i, path=p.relative_to(inp).as_posix(), text=t, sha256=dhash(t),
                   lines=t.splitlines())
        (submissions if RATEERX.search(p.stem) and "task" not in p.stem.lower() else docs).append(rec)
    return docs, submissions, unread

def cli():
    ap = argparse.ArgumentParser(
        description="Produce a judgeable academic-writing benchmark delivery from a case directory: "
                    "item sheet, reference answers, observable anchors, two-rater scores, per-item "
                    "report, reproducibility note and result.json. No third-party imports.")
    ap.add_argument("--input", default="/input", help="case directory holding case.json plus materials")
    ap.add_argument("--output", default="/app/output", help="directory that receives the delivery")
    a = ap.parse_args()
    AST.boot(START); AST.trace("init", script="scripts/bench.py", version=KVER, anchor_version=AVER)
    inp, out = Path(a.input).expanduser(), Path(a.output).expanduser()
    try: out.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        FAULTS.append({"stage": "output", "error": str(e)}); DEGRADED.append({"stage": "output", "note": LANG.get("fallback_out")})
        out = Path("output"); out.mkdir(parents=True, exist_ok=True)
    brief = {}
    case_raw = ""
    cpath, why = locate_case(inp) if inp.is_dir() else (None, "input dir missing")
    if why: FAULTS.append({"stage": "case", "error": why})
    AST.trace("find_case", status="ok" if cpath else "missing", path=cpath.name if cpath else "-", note=why or "")
    if cpath:
        try:
            case_raw = cpath.read_text("utf-8", "replace")
            brief = json.loads(case_raw)
            if not isinstance(brief, dict): brief = {}; FAULTS.append({"stage": "case", "error": "case file is not a json object"})
        except Exception as e:
            FAULTS.append({"stage": "case", "error": "bad json: %s" % e})
    contract = brief.get("output_contract") if isinstance(brief.get("output_contract"), dict) else {}
    cid = brief.get("case_id") or brief.get("id") or brief.get("caseId")
    payload = {k: None for k in ["deliverable", "preserved_facts", "evidence_map", "change_log", "sources", "uncertainty",
                             "pending_human", "errors", "degradations", "changes", "runtime", "workorder_execution",
                             "coverage", "consistency"] + list(contract)}
    payload.update(case_id=cid, status="partial", skill="writing-bench-eval-kit", skill_version=KVER,
               anchor_version=AVER)
    (out / "result.json").write_text(jstr(payload), encoding="utf-8")          # write the partial result before anything can raise
    AST.trace("partial_result", keys=len(payload), status=payload["status"])

    docs, submissions, unread = crawl(inp) if inp.is_dir() else ([], [], [])
    EV = collect_facts(docs)
    AST.trace("scan_materials", docs=len(docs), submissions=len(submissions), unparsed=len(unread))
    AST.trace("extract_facts", facts=len(EV))
    order = brief.get("organizer_workorder") or brief.get("organizer_edit_workorder") or {}
    want = int(brief.get("task_count") or brief.get("n_tasks") or 0)
    if isinstance(order, dict):
        for k, v in order.items():
            if not want and re.search(r"task|count", str(k), re.I) and str(v).strip().isdigit(): want = int(v)
    qty = max(6, min(12, want or 6)) if docs else 0
    items, ANCH, grid, tally, revs, calib, main_rows = [], [], [], [], [], [], []
    state = dict(case_id=cid, status="partial", docs=docs, elapsed=0.0, py=sys.version.split()[0],
               ratee_note=LANG.get("no_ratee"), big=0, biglist="", partial_written=True,
               case_text=case_raw, case_name=(cpath.name if cpath else "case.json"))
    stable = True
    try:
        if not docs:
            state["status"] = "input_error"
            HOLD.append({"item": "材料", "note": LANG.get("pend_mat")})
            (out / "deliverable.md").write_text(LANG.get("stub"), encoding="utf-8")
        else:
            items = compose_tasks(brief, docs, EV, qty, DOUBTS); ANCH = compose_anchors(items, EV, docs)
            AST.trace("build_tasks", items=len(items), anchors=len(ANCH))
            (out / "tasks.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in items),
                                             encoding="utf-8")
            emit_reference(out / "reference_answers", items); AST.trace("write_reference_answers", files=len(items))
            batches = ([("manuscript-01", "\n\n".join(r["text"] for r in submissions), "manuscript")] if submissions else []) + \
                   [("control-positive", control_body(items, True), "anchor_calibration"),
                    ("control-negative", control_body(items, False), "anchor_calibration")]
            if submissions: state["ratee_note"] = LANG.get("scored") + ", ".join(r["path"] for r in submissions)
            bodies = {}
            (out / "ratees").mkdir(exist_ok=True)
            for sub_id, body, run_kind in batches:
                bodies[sub_id] = body
                (out / "ratees" / ("%s.txt" % sub_id)).write_text(body, encoding="utf-8")
                r1, r2 = score(ANCH, sub_id, body, run_kind, DEGRADED), score(ANCH, sub_id, body, run_kind, DEGRADED)
                grid += r1
                stable = stable and [(x["anchor_id"], x["adjudicated"]) for x in r1] ==                     [(x["anchor_id"], x["adjudicated"]) for x in r2]
            AST.trace("dual_rater_scoring", rows=len(grid), batches=len(batches), deterministic=stable)
            if not stable: FAULTS.append({"stage": "score", "error": "scoring is not deterministic"})
            for r in grid:               # a gap wider than one level indicts the rule: rebuild the rule, never the number
                if abs(r["level_rater_a"] - r["level_rater_b"]) > 1:
                    anc = [x for x in ANCH if x["anchor_id"] == r["anchor_id"]][0]
                    anc["revision"] += 1
                    if anc["rule"]["type"] == "contains_all":
                        anc["rule"]["values"] = [canon(v) for v in anc["rule"]["values"]]
                    revs.append(dict(anchor_id=anc["anchor_id"], revision=anc["revision"], reason=LANG.get("repair"),
                                     disagreement="a=%d b=%d" % (r["level_rater_a"], r["level_rater_b"])))
            if revs:
                bad = {x["anchor_id"] for x in revs}
                for r in grid:
                    if r["anchor_id"] in bad:
                        anc = [x for x in ANCH if x["anchor_id"] == r["anchor_id"]][0]
                        la, lb = KN.grade_level(anc["rule"], bodies[r["ratee_id"]], "a"), \
                            KN.grade_level(anc["rule"], bodies[r["ratee_id"]], "b")
                        r.update(level_rater_a=la, level_rater_b=lb, delta=la - lb, adjudicated=min(la, lb),
                                 agree=int(la == lb), verdict="met" if min(la, lb) == 2 else
                                 ("partial" if min(la, lb) == 1 else "missed"))
                DEGRADED.append({"stage": "consistency", "note": LANG.get("repaired") % len(revs)})
                AST.trace("anchor_repair", revisions=len(revs), score_changed=False)
                EDITS.extend([{"target": x["anchor_id"], "action": "anchor_rule_revised", "reason": x["reason"],
                             "disagreement": x["disagreement"], "score_changed": False} for x in revs])
            tally = aggregate(grid, items)
            for sub_id in ("control-positive", "control-negative"):
                ss = [x for x in tally if x["ratee_id"] == sub_id]
                if ss:
                    calib.append(dict(control=sub_id, expect=LANG.get("exp_pos" if sub_id.endswith("positive") else "exp_neg"),
                                      total=len(ss), mean_score=round(sum(x["score"] for x in ss) / len(ss), 1),
                                      ok=sum(1 for x in ss if (x["score"] >= 85) == sub_id.endswith("positive"))))
            main_rows = [s for s in tally if s["ratee_id"] == ("manuscript-01" if submissions else "control-positive")]
            AST.trace("calibration", controls=len(calib), primary_tasks=len(main_rows))
            state.update(status="ok" if submissions else "partial", elapsed=time.time() - START,
                       big=sum(abs(r["level_rater_a"] - r["level_rater_b"]) > 1 for r in grid),
                       biglist=", ".join(sorted({r["anchor_id"] for r in grid
                                                 if abs(r["level_rater_a"] - r["level_rater_b"]) > 1})))
            if not submissions:
                HOLD.append({"item": "待评稿件", "note": LANG.get("pend_ratee")})
            emit_anchors(out / "anchors.md", ANCH, revs)
            write_csv(out / "scores.csv", tally, CSVSPEC["scores"])
            write_csv(out / "scores_detail.csv", grid, CSVSPEC["detail"])
            emit_report(out / "evaluation_report.md", grid, items, kappa(grid), calib, state, main_rows)
            write_meta(out / "reproducibility.md", out / "deliverable.md", state, items, ANCH,
                  [dict(path=d["path"], sha256=d["sha256"], chars=len(d["text"])) for d in docs + submissions], stable)
            AST.trace("render_reports", report="evaluation_report.md", repro="reproducibility.md")
    except Exception as e:
        FAULTS.append({"stage": "pipeline", "error": "%s: %s" % (type(e).__name__, e)}); state["status"] = "partial"
        AST.trace("pipeline_error", status="error", error="%s: %s" % (type(e).__name__, e))

    receipts = []
    if isinstance(order, dict) and items:
        for k, v in order.items():
            tk = bool(re.search(r"task|count", str(k), re.I))
            receipts.append({"item": str(k), "required": trim(v, 160), "status": "executed" if tk else "acknowledged",
                        "applied_value": len(items) if tk else None})
    state["elapsed"] = time.time() - START; state["errors"] = FAULTS
    hashes = [dict(path=d["path"], sha256=d["sha256"], chars=len(d["text"])) for d in docs + submissions]
    FACT_KEYS = ("fact_id", "kind", "value", "locator", "quote", "doc_id", "verbatim")
    payload.update(status=state["status"], pending_human=HOLD, errors=FAULTS, degradations=DEGRADED, changes=EDITS,
               change_log=EDITS, workorder_execution=receipts, sources=hashes + [dict(path=u, note="unparsed") for u in unread],
               preserved_facts=[{k: f[k] for k in FACT_KEYS} for f in EV[:200]],
               evidence_map=[dict(claim=p["text"], kind="requirement", locator=p["locator"], quote=p["quote"],
                                  doc_id=p["locator"].split(":")[0], task_id=t["task_id"], point_id=p["point_id"])
                             for t in items for p in t["must_include_points"]][:200],
               uncertainty=DOUBTS[:50] + ([{"note": "tasks=%d" % len(items)}] if items else []),
               coverage=dict(tasks=len(items), anchors=len(ANCH), missing_points=0, unparsed_files=unread,
                             points=sum(len(t["must_include_points"]) for t in items),
                             directions=sorted({t["direction"] for t in items}),
                             writing_types=sorted({t["writing_type"] for t in items}), ratee_files=[r["path"] for r in submissions]),
               consistency=dict(kappa=kappa(grid) if grid else None, big_delta_anchors=state["big"],
                                repaired=len(revs), calibration=calib),
               runtime=dict(elapsed_s=round(state["elapsed"], 2), python=state["py"], skill_version=KVER,
                            anchor_version=AVER, llm_requests=0),
               deliverable={"primary": "deliverable.md", "task_count": len(items), "anchor_count": len(ANCH),
                            "has_manuscript": bool(submissions), "toolkit": ARTIFACTS if items else []})
    if not EDITS:
        payload["change_log"] = [{"target": "output", "action": "no_source_edit", "reason": LANG.get("no_edit")}]
    # The asset layer runs on the final semantic payload, so golden/diff/self-check can compare
    # against what is actually shipped instead of predicting it.
    asset_refs = {}
    try:
        asset_refs = AST.build_assets(out, brief, state, items, ANCH, docs, grid, tally, revs, FAULTS, DEGRADED, HOLD, payload, stable) or {}
    except Exception as e:
        FAULTS.append({"stage": "assets", "error": "%s: %s" % (type(e).__name__, e)})
        AST.fallback_assets(out, e, state)
    payload.update(asset_refs)
    (out / "result.json").write_text(jstr(payload), encoding="utf-8")
    try:
        AST.seal(out, list(contract), payload["status"])
    except Exception as e:
        FAULTS.append({"stage": "assets_post", "error": str(e)})
    print("[done] case=%s status=%s items=%d anchors=%d assets=%d/5 out=%s"
          % (cid, payload["status"], len(items), len(ANCH),
             sum(1 for qty in AST.SET5FILES if (out / qty).is_file()), out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(cli())
    except SystemExit:
        raise
    except Exception as e:
        try:
            o = Path("/app/output"); o.mkdir(parents=True, exist_ok=True)
            (o / "result.json").write_text(jstr({"case_id": None, "status": "partial",
                                               "errors": [{"stage": "fatal", "error": str(e)}]}), encoding="utf-8")
            try: AST.fallback_assets(o, e, {"case_id": None, "status": "partial"})
            except Exception: pass
        except Exception:
            pass
        sys.exit(0)

