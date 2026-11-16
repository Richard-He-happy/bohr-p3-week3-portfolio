#!/usr/bin/env python3
"""Paper -> academic talk deck: discovery, outline, build call, audit, envelope.

Mechanics live in ooxml_kit; every failure is recorded in result.json and the process
still exits 0.
"""
import argparse, hashlib, json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ooxml_kit as KIT
try:  # 五件可核验资产（缺失时主流程照常跑，只记降级）
    import assetkit as ASSETS
except Exception:  # noqa: BLE001 - 包被裁剪时也不能中断主流程
    ASSETS = None
DEFAULT_CONTRACT = ["case_id", "status", "editable_source", "export_artifact", "content_map", "compliance_checks", "exceptions"]
NUM_PATTERN = re.compile(r"\d+(?:[.,]\d+)*\s*(?:%|‰)?")
FIG_PATTERN = re.compile(r"(figure|fig\.?|table|tab\.?|图|表)\s*\.?\s*(\d+[a-z]?)", re.I)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")
STOPWORDS = set("a an the of in on for to and or with by as is are was were be this that these those we our it from than which they not but".split())
KNOWN_HEADINGS = {"references", "acknowledgements", "future work", "limitations", "conclusions", "conclusion", "discussion", "results and discussion", "results", "materials and methods", "methods", "method", "related work", "background", "introduction", "abstract", "experiments"}
ROLE_HINTS = { "result": ("we find", "results", "outperform", "achiev", "increase", "improv", "compared", "significant", "lower", "higher"), "limitation": ("limitation", "caveat", "remains", "future work", "small sample", "not general"), "discussion": ("suggest", "indicat", "consistent", "impl", "in contrast", "explain", "interpret"),
    "motivation": ("however", "problem", "challenge", "gap", "remain", "limited", "lack", "need", "difficult", "unclear"),
    "method": ("we use", "dataset", "we train", "pipeline", "we collect", "we measure", "model", "participants", "experiment"),
    "approach": ("we propose", "we present", "this work", "we introduce", "we develop", "here we", "our approach", "we design", "we show"),
    "conclusion": ("in conclusion", "we conclude", "taken together", "in summary", "overall", "these results")}
ROLE_LABELS = {"evidence": "Key evidence", "thanks": "Thank you", "conclusion": "Takeaways", "limitation": "Limits and open questions", "discussion": "What it means", "method": "How the work was done", "approach": "Our approach", "motivation": "Why this matters"}
ROLE_SECTIONS = {"conclusion": ("conclusion",), "limitation": ("limitation", "discussion"), "discussion": ("result", "discussion"), "method": ("experiment", "method"), "approach": ("method", "introduction", "abstract"), "motivation": ("abstract", "background", "introduction")}
def squash(row):
    return re.sub(r"\s+", " ", re.sub(r"-\s*\n\s*", "", row or "")).strip()
def fingerprint(row):
    return re.sub(r"[^0-9a-z%\u4e00-\u9fff]", "", (row or "").lower())
def token_set(row):
    return {t for t in TOKEN_PATTERN.findall((row or "").lower()) if t not in STOPWORDS and len(t) > 1}
def number_set(row):
    return {match.group(0).replace(" ", "") for match in NUM_PATTERN.finditer(row or "")}
def cited_refs(row):
    return {("table " if field.lower().startswith(("tab", "表")) else "figure ") + n for field, n in FIG_PATTERN.findall(row or "")}
def is_quote_in_paper(frag, src_lc, src_fp):
    frag = squash(frag).lower()
    return len(frag) >= 8 and (frag in src_lc or (len(fingerprint(frag)) > 8 and fingerprint(frag) in src_fp))
def clip_text(row, match):
    row = squash(row)
    if len(row) <= match:
        return row
    last = row[:match]
    for sep in (". ", "; ", ", ", " and ", " — "):
        pos = last.rfind(sep)
        if pos > match * .45:
            return last[:pos].rstrip(" ,;:") + "…"
    return last.rsplit(" ", 1)[0] + "…"
def scan_sentences(pages, cap=400):
    """Sentence records (page/section locator) plus figure/table captions from page text."""
    ss, sec, F, T = [], "", [], []
    for node, pt in enumerate(pages or [], 1):
        L = [line.strip() for line in (pt or "").split("\n") if line.strip()]
        for pos, t in enumerate(L):
            args = re.match(r"^(Figure|Fig\.?|FIGURE)\s*(\d+[a-z]?)\s*[.:|]?\s*(.{12,240})$", t)
            buff = re.match(r"^(Table|TABLE)\s*(\d+[a-z]?)\s*[.:|]?\s*(.{8,240})$", t)
            if args or buff:
                cont = L[pos + 1] if pos + 1 < len(L) and len(L[pos + 1]) < 160 and not re.match(r"^(Figure|Table|Fig\.)", L[pos + 1]) else ""
                (F if args else T).append({"id": ("Figure " if args else "Table ") + (args or buff).group(2), "cap": squash((args or buff).group(3) + " " + cont), "p": node})
                continue
            match = re.match(r"^(?:(\d+(?:\.\d+)*)[.)]?\s+)?([A-Z][A-Za-z][A-Za-z \-/]{2,48})$", t)
            if match and len(t) < 60 and not t.endswith(".") and (match.group(1) or t.lower() in KNOWN_HEADINGS):
                sec = t
                continue
            for chunk in re.split(r"(?<=[.!?])\s+(?=[A-Z(\[])", t):
                chunk = squash(chunk)
                if 25 <= len(chunk) <= 400 and (not chunk[:1].isascii() or not chunk[:1].islower()):
                    ss.append({"t": chunk, "p": node, "sec": sec})
                if len(ss) >= cap:
                    return ss, F, T
    return ss, F, T
def role_sequence(n):
    body = ["title"]
    for role, least in (("motivation", 3), ("approach", 4), ("method", 6), ("discussion", 10), ("limitation", 10)):
        if n >= least:
            body.append(role)
    tail = ["conclusion"] + (["thanks"] if n >= 14 else [])
    spare = n - len(body) - len(tail)
    for droppable in ("limitation", "discussion", "method", "approach", "motivation"):
        if spare >= 1:
            break
        if droppable in body:
            body.remove(droppable)
            spare = n - len(body) - len(tail)
    if spare < 1:
        body, tail = (["title"] if n == 1 else ["title", "motivation"]), (["conclusion"] if n > 1 else [])
        spare = max(0, n - len(body) - len(tail))
    out = body + ["evidence"] * spare + tail
    while len(out) < n:
        out.insert(len(out) - len(tail), "evidence")
    return out[:n]
def choose_sentences(ss, role, used, field=3, secs=None):
    kws = ROLE_HINTS.get(role, ())
    pool = [row for row in ss if id(row) not in used and len(row["t"]) < 320] or [row for row in ss if len(row["t"]) < 320]
    if secs:
        pr = [row for row in pool if any(w in row["sec"].lower() for w in secs)]
        pool = pr + [row for row in pool if row not in pr]
    out = []
    for pos in sorted(range(len(pool)), key=lambda pos: (-sum(1 for w in kws if w in pool[pos]["t"].lower()), pos)):
        if len(out) >= field:
            break
        row = pool[pos]
        if any(fingerprint(row["t"])[:50] == fingerprint(overl["t"])[:50] for overl in out):
            continue
        out.append(row)
        used.add(id(row))
    return out
def sentence_evidence(row):
    return {"type": "section" if row["sec"] else "page", "id": row["sec"] or "p.%d" % row["p"], "locator": "p.%d%s" % (row["p"], (" / " + row["sec"]) if row["sec"] else ""), "quote": row["t"]}
def compose_slides(parsed, order):
    ss, used, F, T = parsed["sents"], set(), parsed["figs"], parsed["tabs"]
    roles, plan_slides = role_sequence(order["total"]), []
    title, sub = parsed["meta"].get("title") or parsed["meta"].get("stem", ""), parsed["meta"].get("byline", [])[:2]
    for pos, role in enumerate(roles):
        row = {"n": pos + 1, "role": role, "bullets": [], "evidence": [], "notes": ""}
        if role == "title":
            row["title"], row["claim"], row["bullets"] = title, title[:110] or ROLE_LABELS["evidence"], sub or [parsed["meta"].get("stem", "")]
            row["evidence"] = [sentence_evidence(ss[0])] if ss else [{"type": "page", "id": "p.1", "locator": "p.1", "quote": title}]
        elif role == "evidence":
            field, pool = sum(1 for chunk in plan_slides if chunk["role"] == "evidence"), F + T
            if field < len(pool):
                flaws, cap = pool[field], clip_text(pool[field]["cap"], 95)
                res = choose_sentences([chunk for chunk in ss if abs(chunk["p"] - flaws["p"]) <= 1] or ss, "result", used, 2) or choose_sentences(ss, "result", used, 2)
                row["title"], row["claim"] = "%s: %s" % (flaws["id"], clip_text(flaws["cap"], 60)), cap
                row["bullets"] = [cap] + [clip_text(chunk["t"], 105) for chunk in res[:2]]
                row["evidence"] = [{"type": "figure" if "Figure" in flaws["id"] else "table", "id": flaws["id"], "locator": "%s, p.%d" % (flaws["id"], flaws["p"]), "quote": flaws["cap"]}] + [sentence_evidence(chunk) for chunk in res]
            else:
                sel = choose_sentences(ss, "result", used, 3) or choose_sentences(ss, "result", set(), 3)[(field - len(pool)) % 3:]
                row["title"] = "%s %d" % (ROLE_LABELS["evidence"], field - len(pool) + 1)
                row["claim"] = clip_text(sel[0]["t"], 100) if sel else ROLE_LABELS["evidence"]
                row["bullets"], row["evidence"] = [clip_text(chunk["t"], 110) for chunk in sel], [sentence_evidence(chunk) for chunk in sel]
        elif role == "thanks":
            ack = [chunk for chunk in ss if "acknowledg" in chunk["sec"].lower()]
            row["title"] = row["claim"] = ROLE_LABELS["thanks"]
            row["bullets"], row["evidence"] = ([clip_text(chunk["t"], 100) for chunk in ack[:2]] or sub), [sentence_evidence(chunk) for chunk in ack[:1]]
        else:
            sel = choose_sentences(ss, role, used, 3, ROLE_SECTIONS.get(role)) or choose_sentences(ss, role, used, 3)
            row["title"], row["claim"] = ROLE_LABELS.get(role, role), (clip_text(sel[0]["t"], 105) if sel else ROLE_LABELS.get(role, role))
            row["bullets"], row["evidence"] = [clip_text(chunk["t"], 110) for chunk in sel], [sentence_evidence(chunk) for chunk in sel]
        ls = [err["locator"] for err in row["evidence"][:2]]
        nt = ("If asked, cite %s." % "; ".join(ls)) if ls else ""
        if pos + 1 < len(roles):
            nt += " Next: %s." % ROLE_LABELS.get(roles[pos + 1], roles[pos + 1])
        row["notes"] = nt.strip()[:400] or "Emphasis: one claim per page; detail is in the paper."
        plan_slides.append(row)
    return plan_slides
def run_checks(plan_slides, src_lc, src_fp, order, build_info):
    flaws, qm, nu, fj, overlaps, ps = [], 0, 0, 0, [], cited_refs(src_lc)
    for row in plan_slides:
        body = " ".join(map(str, row["bullets"])) + " " + row.get("claim", "")
        for err in row["evidence"]:
            if not is_quote_in_paper(err.get("quote", ""), src_lc, src_fp):
                qm += 1
                flaws.append("s%d quote-not-in-paper %s" % (row["n"], err.get("locator")))
        for val in number_set(body):
            if val not in src_lc and val.rstrip("%‰") not in src_lc:
                nu += 1
                flaws.append("s%d number-not-in-paper %s" % (row["n"], val))
        for env in cited_refs(row.get("title", "") + body):
            if ps and env not in ps:
                fj += 1
                flaws.append("s%d ref-not-in-paper %s" % (row["n"], env))
        overl = round(len(token_set(row["notes"]) & token_set(body + row.get("title", ""))) / max(1, len(token_set(row["notes"]))), 3) if row.get("notes") else 0.0
        if overl > .6:
            flaws.append("s%d notes-restate-text %.2f" % (row["n"], overl))
        overlaps.append(overl)
    dense = [row["n"] for row in plan_slides if len(row["bullets"]) > 5 or max([len(str(buff)) for buff in row["bullets"]] or [0]) > 190]
    return {"slide_count": {"expected": order["total"], "actual": len(plan_slides), "ok": len(plan_slides) == order["total"]}, "template_inheritance": {"declared": order["template_inheritance"], "engine": build_info.get("engine"), "theme_unchanged": build_info.get("theme_unchanged"),
                                     "master_unchanged": build_info.get("master_unchanged"), "layouts_used": build_info.get("layouts_used"), "ok": build_info.get("theme_unchanged") is not False},
            "overflow": {"dense_slides": dense, "ok": not dense},
            "notes_coverage": {"n": sum(1 for row in plan_slides if row.get("notes")), "total": len(plan_slides), "ok": all(row.get("notes") for row in plan_slides)},
            "notes_overlap": {"max": max(overlaps or [0]), "threshold": .6, "ok": max(overlaps or [0]) <= .6},
            "figure_refs": {"paper_count": len(ps), "mismatch": fj, "ok": fj == 0},
            "number_whitelist": {"misses": nu, "ok": nu == 0},
            "fonts": {"theme": "template" if build_info.get("template") else "builtin", "embedded": False},
            "evidence_coverage": {"n": sum(1 for row in plan_slides if row["evidence"]), "total": len(plan_slides), "quotes_missing": qm},
            "pass": not flaws, "failures": flaws[:30]}
def put_json(node, overl):
    Path(node).parent.mkdir(parents=True, exist_ok=True)
    Path(node).write_text(json.dumps(overl, ensure_ascii=False, indent=1), encoding="utf-8")
def read_case_json(inp):
    inp = Path(inp)
    files = sorted([node for node in inp.rglob("*") if node.is_file()]) if inp.exists() else []
    for node in [inp / "case.json"] + [frag for frag in files if re.match(r"case.*\.json$", frag.name, re.I)]:
        if node.is_file():
            try:
                blob = json.loads(node.read_text(encoding="utf-8-sig", errors="ignore"))
                if isinstance(blob, dict):
                    return blob, node, files
            except Exception:
                pass
    return {}, None, files
def read_workorder(case, files):
    wo = {}
    for field, val in case.items():
        if isinstance(val, dict) and ("slide" in str(field).lower() or any(("slide" in str(chunk).lower() or "count" in str(chunk).lower()) for chunk in val)):
            wo.update({str(args).lower().replace(" ", "_"): buff for args, buff in val.items()})
    for node in files:
        if re.search(r"workorder.*\.json$|slide[-_]?spec.*\.json$", node.name, re.I):
            try:
                blob = json.loads(node.read_text(encoding="utf-8-sig", errors="ignore"))
                if isinstance(blob, dict):
                    wo.update({str(args).lower().replace(" ", "_"): buff for args, buff in blob.items()})
            except Exception:
                pass
    last = lambda *names: next((wo[field] for field in names if wo.get(field) not in (None, "")), None)
    n = re.sub(r"[^0-9]", "", str(last("total_slide_count", "slide_count", "total_slides", "n_slides", "max_slides") or ""))
    return {"mode": str(last("mode", "requested_mode") or "generate"), "total": int(n) if n else 12, "source_preservation": last("source_preservation"), "template_inheritance": last("template_inheritance"), "audience": last("audience"), "duration": last("duration_minutes", "duration"), "raw": wo}
def structure_audit(map_out, slides, deck_report):
    rows = map_out.get("slides") or []
    required = ("n", "title", "role", "claim", "bullets", "evidence", "assets", "notes")
    gaps = []
    for row in rows:
        absent = [key for key in required if key not in row]
        if absent:
            gaps.append({"n": row.get("n"), "missing": absent})
        elif not (row.get("claim") and row.get("evidence") and row.get("notes")):
            gaps.append({"n": row.get("n"), "missing": ["claim/evidence/notes empty"]})
    numbers = [row.get("n") for row in rows]
    ordered = numbers == list(range(1, len(rows) + 1))
    deck_slides, deck_notes = deck_report.get("slides"), deck_report.get("notes")
    report = {"content_map_rows": len(rows), "modelled_slides": len(slides), "row_numbers_ok": ordered, "rows_complete": not gaps, "gaps": gaps[:10], "pptx_slides": deck_slides, "pptx_notes": deck_notes, "notes_match_slides": deck_notes == deck_slides}
    report["ok"] = bool(len(rows) == len(slides) and ordered and not gaps
                        and deck_slides == len(slides) and deck_notes == deck_slides)
    return report
def run(argv=None):
    ap = argparse.ArgumentParser(description="Turn one research paper into a page-level, evidence-anchored academic deck (editable pptx + preview PDF + evidence map + result envelope). Never exits non-zero: problems are written into result.json.")
    ap.add_argument("--input", default="/input", help="folder holding case.json, task.md, the paper and optional artifacts")
    ap.add_argument("--output", default="/app/output", help="folder for the deliverables (presentation.pptx/.pdf, plan.json, result.json)")
    ap.add_argument("--work", default="/app/work", help="scratch folder for intermediate/verification files")
    args = ap.parse_args(argv)
    t_start, out, work = time.time(), Path(args.output), Path(args.work)
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    run_meta = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "version": ASSETS.VERSION if ASSETS else "1.0.0",
                "run_id": time.strftime("%Y%m%dT%H%M%S"), "argv": [str(part) for part in (argv if argv is not None else sys.argv[1:])],
                "input": str(args.input), "output": str(args.output), "work": str(args.work)}
    run_meta["command"] = "python %s %s" % (Path(__file__).name, " ".join(run_meta["argv"]))
    log = ASSETS.RunLog(out / "run.log", argv=run_meta["argv"]) if ASSETS else None
    if log:
        log.mark("boot", "pipeline start version=%s input=%s output=%s work=%s" % (run_meta["version"], args.input, args.output, args.work))
    case, case_path, files = read_case_json(args.input)
    if log:
        log.mark("case", "case loaded case_id=%s files=%d case_json=%s"
                 % (case.get("case_id") or case.get("id") or "-", len(files), "yes" if case_path else "no"))
    contract = case.get("output_contract")
    contract = [str(field) for field in contract] if isinstance(contract, list) and contract else list(DEFAULT_CONTRACT)
    contract = contract if "case_id" in contract else ["case_id"] + contract
    case_ref = case.get("case_id") or case.get("id")
    env = {field: None for field in contract}
    env.update({"case_id": case_ref, "status": "partial"})
    env.update({"degradations": [], "errors": [], "exceptions": [], "uncertainty": [], "pending_human": [], "sources": {}, "changes": {}, "runtime": {"started": time.strftime("%Y-%m-%dT%H:%M:%S")}})
    put_json(out / "result.json", env)
    ctx = {"out": out, "work": work, "case": case, "case_path": case_path, "files": files,
           "contract": contract, "run_meta": run_meta, "plan": None, "parsed": None, "order": None,
           "map_out": None, "val": None, "deck_path": None, "preview": None, "audit": None,
           "build_info": None, "source": None, "template": None, "probes": {},
           "log": log, "t0": t_start}
    probes = ASSETS.fallback_probes(work, read_case_json) if ASSETS else {"empty_input": {}, "bad_json": {}}
    ctx["probes"] = probes
    if log:
        log.mark("probe", "fallback probes empty_input=%s bad_json=%s"
                 % ((probes.get("empty_input") or {}).get("ok"), (probes.get("bad_json") or {}).get("ok")))
    problems, degraded, human_todo = [], [], []
    E = lambda field, blob: problems.append({"kind": field, "detail": blob})
    def finish():
        """收尾链全部在 assetkit.finalize 里（资产 → result.json → run.log 收尾）；永不抛异常。"""
        if ASSETS is None:
            try:
                env["runtime"] = dict(env.get("runtime") or {}, seconds=round(time.time() - t_start, 1))
                put_json(out / "result.json", env)
            except Exception:  # noqa: BLE001
                pass
            return 0
        return ASSETS.finalize(env, ctx)
    try:
        order = read_workorder(case, files)
        ctx["order"] = order
        candidates = [node for node in files if node.suffix.lower() in (".pdf", ".docx", ".md", ".txt") and node.stat().st_size > 1500 and not re.search(r"^task\.md$|readme", node.name, re.I)]
        decks_found = [node for node in files if node.suffix.lower() == ".pptx"]
        source = candidates[0] if candidates else None
        template = next((node for node in decks_found if re.search(r"template|master|layout|style|brand", node.name, re.I)), None) or (decks_found[0] if decks_found else None)
        ctx["source"], ctx["template"] = source, template
        if log:
            log.mark("scan", "input scanned files=%d paper=%s decks=%d total_slides=%s mode=%s"
                     % (len(files), Path(str(source)).name if source else "none", len(decks_found), order.get("total"), order.get("mode")))
        if not case_path:
            E("input", "no case.json; contract defaulted")
        if template is None:
            degraded.append({"what": "template", "detail": "no template; builtin master/layout/theme"})
        if not source:
            env.update({"status": "input_error", "exceptions": problems + [{"kind": "input", "detail": "no paper file under %s" % args.input}],
                        "sources": {"file": None, "engine": None, "chars": 0},
                        "runtime": dict(env["runtime"], seconds=round(time.time() - t_start, 1))})
            if log:
                log.fail("input", "no paper file under %s; input_error envelope" % args.input)
            return finish()
        parsed = KIT.read_paper(source)
        parsed["sents"], parsed["figs"], parsed["tabs"] = scan_sentences(parsed["pages"])
        ctx["parsed"] = parsed
        if log:
            log.mark("extract", "engine=%s chars=%d pages=%d figures=%d tables=%d"
                     % (parsed["engine"], len(parsed["text"]), len(parsed["pages"]), len(parsed["figs"]), len(parsed["tabs"])))
        if len(parsed["text"]) < 200:
            E("extraction", "text layer empty (engine=%s); nothing invented" % parsed["engine"])
            env.update({"status": "partial", "exceptions": problems, "sources": {"file": str(source), "engine": parsed["engine"], "chars": len(parsed["text"])},
                        "runtime": dict(env["runtime"], seconds=round(time.time() - t_start, 1))})
            if log:
                log.fail("extract", "text layer empty engine=%s; partial, no deck invented" % parsed["engine"])
            return finish()
        if parsed["engine"] == "stdlib-inflate":
            degraded.append({"what": "text extraction", "detail": "python-only PDF parsing; captions may be incomplete"})
        if not parsed["figs"] and not parsed["tabs"]:
            human_todo.append({"action": "confirm figure list", "detail": "no captions matched; locators only"})
        plan_slides = compose_slides(parsed, order)
        ctx["plan"] = plan_slides
        put_json(out / "deck_model.json", {"case_id": case_ref, "workorder": order, "paper": str(source), "template": str(template), "slides": plan_slides})
        put_json(out / "plan.json", {"case_id": case_ref, "mode": order["mode"], "total_slide_count": order["total"], "source_preservation": order["source_preservation"], "template_inheritance": order["template_inheritance"],
                               "slides": [{"n": row["n"], "role": row["role"], "title": row["title"], "claim": row["claim"], "locators": [err["locator"] for err in row["evidence"]]} for row in plan_slides]})
        env["sources"] = {"file": str(source), "engine": parsed["engine"], "chars": len(parsed["text"]), "pages": len(parsed["pages"]), "figures": len(parsed["figs"]), "tables": len(parsed["tabs"]), "template": str(template) if template else None}
        if log:
            log.mark("plan", "slides=%d evidence_items=%d claims=%d"
                     % (len(plan_slides), sum(len(row["evidence"]) for row in plan_slides),
                        sum(1 for row in plan_slides if row["claim"])))
        deck_path = out / "presentation.pptx"
        build_info = KIT.assemble_deck(plan_slides, deck_path, template=str(template) if template else None)
        ctx["build_info"], ctx["deck_path"] = build_info, deck_path
        if log:
            log.mark("pptx", "written bytes=%d engine=%s slides=%d template=%s"
                     % (deck_path.stat().st_size, build_info.get("engine"), len(plan_slides), "yes" if template else "builtin"))
        preview = KIT.render_preview_pdf(deck_path, out, work=work)
        ctx["preview"] = preview
        if preview["degraded"]:
            degraded.append({"what": "pdf", "detail": "no office renderer; preview PDF built from the deck's own text layer (layout fidelity degraded)"})
        if log:
            log.mark("pdf", "written engine=%s degraded=%s path=%s"
                     % (preview.get("engine"), preview.get("degraded"), preview.get("pdf")))
        val = {"pptx": KIT.inspect_deck(deck_path, order["total"]), "pdf": KIT.inspect_pdf(out / "presentation.pdf"), "png": {"count": 0}}
        val["pass"] = bool(val["pptx"]["ok"] and val["pdf"]["ok"])
        ctx["val"] = val
        put_json(work / "verification.json", val)
        if log:
            log.mark("verify", "pptx_ok=%s slides=%s notes=%s pdf_ok=%s pdf_pages=%s"
                     % (val["pptx"]["ok"], val["pptx"]["slides"], val["pptx"]["notes"], val["pdf"]["ok"], val["pdf"]["pages"]))
        src_lc, src_fp = parsed["text"].lower(), fingerprint(parsed["text"])
        audit = run_checks(plan_slides, src_lc, src_fp, order, build_info)
        audit["files"] = {"pptx_ok": val["pptx"]["ok"], "pdf_ok": val["pdf"]["ok"], "png": val["png"]["count"], "pptx_slides": val["pptx"]["slides"], "pdf_pages": val["pdf"]["pages"], "pptx_notes": val["pptx"]["notes"]}
        if not val["pptx"]["ok"]:
            E("pptx", "; ".join(val["pptx"]["issues"])[:300])
        if not val["pdf"]["ok"]:
            E("render", "PDF preview invalid/absent")
        matches = lambda err: is_quote_in_paper(err["quote"], src_lc, src_fp)
        mapping = lambda row: {"n": row["n"], "title": row["title"], "role": row["role"], "claim": row["claim"], "bullets": row["bullets"], "evidence": [dict(err, matched=matches(err)) for err in row["evidence"]], "notes": row.get("notes"), "assets": [{"path": None, "note": "caption+locator only"}]}
        map_out = {"unit": "slide", "slides": [mapping(row) for row in plan_slides], "coverage": {"slides": len(plan_slides), "with_evidence": sum(1 for row in plan_slides if row["evidence"]), "evidence_items": sum(len(row["evidence"]) for row in plan_slides), "quotes_matched": sum(1 for row in plan_slides for err in row["evidence"] if matches(err))}}
        ctx["map_out"] = map_out
        sweep_report = structure_audit(map_out, plan_slides, val["pptx"])
        audit["content_map_completeness"] = {"rows": sweep_report["content_map_rows"], "complete": sweep_report["rows_complete"], "gaps": sweep_report["gaps"], "ok": sweep_report["rows_complete"]}
        audit["structure_consistency"] = {"row_numbers_ok": sweep_report["row_numbers_ok"], "pptx_slides": sweep_report["pptx_slides"], "pptx_notes": sweep_report["pptx_notes"], "notes_match_slides": sweep_report["notes_match_slides"], "ok": sweep_report["ok"]}
        if not sweep_report["ok"]:
            audit["pass"] = False
            audit["failures"] = (audit.get("failures") or []) + ["structure audit: slide/notes/content_map rows disagree"]
        put_json(work / "structure_check.json", sweep_report)
        ctx["audit"] = audit
        if log:
            log.mark("audit", "checks_pass=%s failures=%d content_map_rows=%d structure_ok=%s"
                     % (audit.get("pass"), len(audit.get("failures") or []), len(map_out["slides"]),
                        (audit.get("structure_consistency") or {}).get("ok")))
        env.update({"status": "ok" if (audit["pass"] and val["pass"] and not problems) else "partial", "editable_source": {"path": str(deck_path), "format": "pptx", "slides": val["pptx"]["slides"], "bytes": deck_path.stat().st_size, "sha256": hashlib.sha256(deck_path.read_bytes()).hexdigest(), "engine": build_info.get("engine"), "notes_slides": val["pptx"]["notes"],
                                      "template": {"path": build_info.get("template"), "master": build_info.get("master"), "layouts_used": build_info.get("layouts_used"), "inherited": build_info.get("theme_unchanged") is not False}},
                  "export_artifact": {"pdf": {"path": preview.get("pdf"), "pages": val["pdf"]["pages"], "engine": preview.get("engine"), "valid": val["pdf"]["ok"]}, "png": {"dir": None, "count": 0}},
                  "content_map": map_out, "compliance_checks": audit, "exceptions": problems, "degradations": degraded, "pending_human": human_todo,
                  "changes": {"artifact": "presentation.pptx", "engine": build_info.get("engine"), "slides": len(plan_slides), "action": "modify" if template else "add"},
                  "runtime": dict(env["runtime"], seconds=round(time.time() - t_start, 1), model_requests=0)})
        print(json.dumps({"status": env["status"], "slides": len(plan_slides), "pptx": str(deck_path), "pdf": preview.get("pdf"),
                          "checks_pass": audit["pass"], "seconds": round(time.time() - t_start, 1)}))
        return finish()
    except Exception as err:
        env["errors"] = (env.get("errors") or []) + [{"kind": "runtime", "detail": "%s: %s" % (type(err).__name__, str(err)[:300])}]
        if log:
            log.fail("runtime", "%s: %s" % (type(err).__name__, str(err)[:200]))
        env["runtime"] = dict(env.get("runtime") or {}, seconds=round(time.time() - t_start, 1))
        return finish()
if __name__ == "__main__":
    try:
        sys.exit(run())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
