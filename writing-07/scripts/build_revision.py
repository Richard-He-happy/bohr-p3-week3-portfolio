#!/usr/bin/env python3
"""writing-07 rebuttal-response-workbench: assemble a verified revision bundle.

Pipeline: locate the baseline and comment summary -> split comments into
sub-requirements -> read the edit plan -> apply edits -> verify every claimed
change -> emit the revised manuscript, point-by-point letter, comment ledger,
locator table, evidence list and result.json. Standard library only, no
network, no CWD assumptions, exit code stays 0 even on failure.
"""

import argparse, json, re, sys, tempfile, time, traceback

from datetime import datetime

from pathlib import Path


TOOL_VERSION = "1.0.0"

START_TS = time.time()

START_WALL = datetime.now().astimezone().isoformat(timespec="seconds")

SCRIPTS_DIR = Path(__file__).resolve().parent

REF_DIR = SCRIPTS_DIR.parent / "references"

PLAIN_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".tex"}

NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")



def _load_ref(name, default):
    try:
        return json.loads((REF_DIR / name).read_text(encoding="utf-8"))
    except Exception:
        return default



VOCAB = _load_ref("comment_taxonomy.json", {})

FORBIDDEN = VOCAB.get("forbidden_claims") or []

TONE_MAP = VOCAB.get("decision_to_tone") or {"accept": "accept", "partial": "clarify",
                               "reject": "polite_rebuttal", "clarify": "clarify", "invalid": "appeal"}

try:
    sys.path.insert(0, str(SCRIPTS_DIR))
    import audit_bundle as sup
except Exception:
    sup = None

DECISIONS = tuple(TONE_MAP)



def cli(argv=None):
    ap = argparse.ArgumentParser(
        prog="build_revision.py",
        description="writing-07 rebuttal workbench: organizer manuscript baseline plus reviewer comment "
                    "summary -> verified revised manuscript, point-by-point response letter, change locator "
                    "table, evidence list and result.json. Standard library only; exit code 0.",
        epilog="pass 1 builds the comment ledger; fill <work>/edit_plan.json; pass 2 applies the edits. "
               "Plan schema: references/handbook.md",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default="/input", help="input directory (case.json plus materials)")
    ap.add_argument("--output", default="/app/output", help="directory receiving the deliverables")
    ap.add_argument("--work", default="/app/work", help="working directory holding edit_plan.json")
    ap.add_argument("--plan", default=None, help="path to an explicit edit plan file")
    ap.add_argument("--stage", default="auto", choices=["auto", "plan", "draft", "finalize"],
                    help="auto: finalize when a plan exists, otherwise only draft the ledger")
    ap.add_argument("--deliverable-name", default="revised_manuscript.md",
                    help="file name of the revised manuscript")
    ap.add_argument("--version", action="version",
                    version="rebuttal-response-workbench %s" % TOOL_VERSION)
    args = ap.parse_args(argv)
    try:
        return execute(args)
    except Exception:
        err = traceback.format_exc(limit=6)
        try:
            out = Path(args.output)
            out.mkdir(parents=True, exist_ok=True)
            prev, _ = read_json(out / "result.json")
            prev = prev if isinstance(prev, dict) else {}
            prev.update({"case_id": prev.get("case_id", "UNKNOWN-CASE"), "status": "partial",
                         "errors": (prev.get("errors") or []) +
                                   [{"where": "cli", "error": err[-600:]}],
                         "runtime": {"version": TOOL_VERSION, "elapsed_s": elapsed()}})
            dump_json(out / "result.json", prev)
        except Exception:
            pass
        sys.stderr.write(err)
        return 0



def execute(a):
    out, work = Path(a.output), Path(a.work)
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    E, D, I, P, U = [], [], [], [], []
    events = []
    log_event(events, "start", version=TOOL_VERSION, input=str(a.input), output=str(a.output),
              work=str(a.work), deliverable_name=a.deliverable_name, stage_requested=a.stage)
    probe = probe_degraded_paths()
    log_event(events, "degraded_probe", all(v.get("ok") for v in probe.values() if isinstance(v, dict)),
              probes=len(probe), failed=len([1 for v in probe.values()
                                             if isinstance(v, dict) and not v.get("ok")]))
    info = scan_input(a.input)
    E += info["errors"]
    case = info["case"] if isinstance(info["case"], dict) else {}
    con = case.get("output_contract") if isinstance(case.get("output_contract"), dict) else {}
    cid, dn = str(case.get("case_id") or "UNKNOWN-CASE"), a.deliverable_name
    base0, cm0 = info.get("baseline"), info.get("comments") or []
    sources = {"started_at": START_WALL, "events": events, "probe": probe,
               "input_dir": str(a.input),
               "baseline": {"name": Path(base0["path"]).name if base0 else "not supplied",
                            "text": str((base0 or {}).get("text") or "")},
               "comments": [{"name": Path(c["path"]).name, "text": c["text"]} for c in cm0]}
    log_event(events, "scan_input", True, files=len(info.get("files") or []), case=bool(case),
              baseline=bool(base0), comments=len(cm0), errors=len(info.get("errors") or []))
    ctx = {"case_id": cid, "deliverable": dn, "preserved_facts": [], "evidence_map": [],
           "change_log": [], "status": "partial", "uncertainty": U}
    pre = {"status": "partial", "stage": "partial"}
    pre.update(sup.backfill_contract(con, ctx) if sup else {"case_id": cid})
    pre.update({"pending_human": [{"item": "pipeline", "reason": "initial partial placeholder"}],
                "errors": E, "degradations": [], "runtime": {"version": TOOL_VERSION, "elapsed_s": elapsed()}})
    dump_json(out / "result.json", pre)
    _pre, _perr = read_json(out / "result.json")
    precheck = {"ok": isinstance(_pre, dict) and _perr is None,
                "status": (_pre or {}).get("status") if isinstance(_pre, dict) else None,
                "file": "result.json"}
    sources["precheck"] = precheck
    log_event(events, "partial_result", precheck["ok"], status=precheck["status"], file="result.json")
    base, cm = info.get("baseline"), info.get("comments") or []
    if not base or not str(base.get("text") or "").strip():
        E.append({"where": "input", "error": "baseline manuscript not located in input"})
        P.append({"item": "manuscript baseline", "reason": "missing; no revision attempted"})
        msg = "# No usable baseline\n\nThe input contained no manuscript baseline, so no revision was produced.\n"
        log_event(events, "abort_no_baseline", False, reason="baseline manuscript not located",
                  errors=len(E))
        if sup:
            return sup.publish(out, cid, dn, con, ctx, "input_error", E, D, I, P, U, [], [],
                          msg, "input_error", "not supplied", "not supplied", "en", [], [],
                          case, [], sources=sources)
        dump_text(out / dn, msg)
        return 0
    bstr, bn = base["text"], Path(base["path"]).name
    cstr = "\n\n".join(c["text"] for c in cm)
    cn = ", ".join(Path(c["path"]).name for c in cm) or "not supplied"
    if not cm:
        D.append({"kind": "comments_missing", "detail": "no comment file found"})
        P.append({"item": "reviewer comments", "reason": "reviewer comment summary absent"})
    lang = guess_lang(cstr or bstr)
    bs = split_blocks(bstr)
    led = sup.make_ledger(split_comments(cstr), bs, lang) if sup else []
    log_event(events, "ledger", True, comments=len(led),
              subs=sum(len(c.get("sub_requirements") or []) for c in led), lang=lang)
    if sup is None:
        I.append({"kind": "helper_missing", "detail": "audit_bundle.py not importable"})
    pp = Path(a.plan) if a.plan else work / "edit_plan.json"
    if not pp.is_file() and (out / "edit_plan.json").is_file():
        pp = out / "edit_plan.json"
    plan = {}
    if pp.is_file():
        plan, perr = read_json(pp)
        if perr or not isinstance(plan, dict):
            E.append({"where": str(pp), "error": "unusable edit plan (%s)" % perr})
            plan = {}
    elif a.stage in ("finalize", "plan"):
        E.append({"where": "edit_plan", "error": "edit plan missing; run the plan stage first"})
    stage = a.stage if a.stage != "auto" else (
        "finalize" if (plan.get("edits") or plan.get("sub_overrides")) else "draft")
    log_event(events, "plan", True, file=(str(pp) if pp.is_file() else ""),
              found=bool(pp.is_file()), edits=len(plan.get("edits") or []),
              overrides=len(plan.get("sub_overrides") or []), stage=stage)
    subs = sup.refresh_ledger(led) if sup else {}
    for o in plan.get("sub_overrides") or []:
        o = o if isinstance(o, dict) else {}
        s = subs.get(str(o.get("sub_id")))
        if not s:
            I.append({"kind": "unknown_sub_id", "detail": str(o.get("sub_id"))})
            continue
        for k in ("decision", "response_note", "evidence_status", "evidence_note", "type"):
            if o.get(k):
                s[k] = o[k]
        s["decision"] = s["decision"] if s["decision"] in DECISIONS else "accept"
        s["tone"] = tone_of(s["decision"])
    changes, rb, rtext = [], bs, bstr
    if stage == "finalize":
        ed = [e for e in (plan.get("edits") or []) if isinstance(e, dict)]
        raw, recs = run_edits(bs, ed, I)
        rtext = "\n\n".join(raw)
        rb = split_blocks(rtext)
        for i, r in enumerate(recs):
            e = ed[i] if i < len(ed) else {}
            sid = str(e.get("sub_id") or "")
            loc = find_locator(r["revised_quote"], rb) if r["applied"] else None
            if r["applied"] and not loc:
                I.append({"kind": "revised_text_missing", "detail": r["id"]})
                D.append({"kind": "claim_unverifiable",
                          "detail": "edit %s: revised wording missing from deliverable" % r["id"]})
            nok = set(NUMBER_RE.findall(r["original_quote"])) <= set(NUMBER_RE.findall(r["revised_quote"]))
            if not nok:
                I.append({"kind": "numeric_value_changed", "detail": r["id"]})
                P.append({"item": "changed number in %s" % r["id"],
                          "reason": "digits differ from the baseline value; needs human confirmation"})
            changes.append({
                "id": str(e.get("id") or r["id"]),
                "comment_id": str(e.get("comment_id") or sid.split(".")[0]), "sub_id": sid,
                "original_quote": r["original_quote"], "revised_quote": r["revised_quote"],
                "reason": str(e.get("reason") or ""), "locator": loc,
                "baseline_anchor": str(e.get("anchor") or ""), "hit": bool(loc),
                "numbers_preserved": nok, "decision": str(e.get("decision") or "accept"),
                "evidence_status": str(e.get("evidence_status") or "")})
            s = subs.get(sid)
            if not s:
                I.append({"kind": "edit_orphaned", "detail": sid})
                continue
            if loc:
                s["change_ids"].append(changes[-1]["id"])
            if e.get("decision") in DECISIONS:
                s["decision"] = e["decision"]
            s["tone"] = str(e.get("tone") or tone_of(s["decision"]))
            for k in ("response_note", "evidence_status", "evidence_note"):
                if e.get(k):
                    s[k] = str(e[k])
            if not loc and s["decision"] == "accept":
                s["decision"], s["tone"] = "partial", tone_of("partial")
    elif stage == "draft":
        D.append({"kind": "draft_only", "detail": "edit plan absent: manuscript shipped unrevised; "
                                                  "substantive edits not applied"})
    for s in subs.values():
        s["response_note"], hs = scrub_claims(s.get("response_note", ""), I)
        if hs:
            P.append({"item": "overclaim flagged in %s" % s["sub_id"],
                      "reason": "unsupported claim removed: " + "; ".join(hs[:3])})
    if sup:
        sup.refresh_ledger(led, True)
    for s in subs.values():
        if s["decision"] in ("accept", "partial") and not s["change_ids"]:
            P.append({"item": s["sub_id"],
                      "reason": "decision recorded but no verified locator; confirm or revise"})
        elif s["needs_human"] and not any(p.get("item") == s["sub_id"] for p in P):
            P.append({"item": s["sub_id"],
                      "reason": s.get("evidence_note") or "requires material outside the baseline"})
    allsub = [s for c in led for s in c["sub_requirements"]]
    applied = len([c for c in changes if c["hit"]])
    log_event(events, "apply", True, stage=stage, edits=len(changes), applied=applied,
              pending=len(P), issues=len(I), degradations=len(D))
    st = "insufficient_evidence" if (not cm or not led) else (
        "partial" if (stage != "finalize" or applied < len(changes) or P) else "ok")
    if sup is None:
        dump_text(out / dn, rtext)
        res = {"case_id": cid, "status": st, "deliverable": dn, "preserved_facts": [],
               "evidence_map": [], "change_log": changes, "errors": E, "degradations": D,
               "pending_human": P, "comment_ledger": led}
        res.update(con if isinstance(con, dict) else {})
        dump_json(out / "result.json", res)
        return 0
    pres = keep_facts(rb, changes)
    ev = [{"claim": c["revised_quote"][:300], "locator": c["locator"] or c["baseline_anchor"],
           "source_locator": c["baseline_anchor"], "source_quote": c["original_quote"][:300],
           "basis": "baseline_edit", "comment_id": c["comment_id"]} for c in changes]
    ev += [{"claim": s["text"][:200], "locator": s["anchor"], "source_locator": s["anchor"],
            "source_quote": "", "basis": "baseline_unchanged", "comment_id": c["comment_id"]}
           for c in led for s in c["sub_requirements"] if not s["change_ids"] and s["anchor"]]
    return sup.publish(out, cid, dn, con, ctx, st, E, D, I, P, U, led, changes, rtext,
                  stage, bn, cn, lang, pres, ev, case, plan, allsub, applied, sources=sources)



def scrub_claims(t, issues):
    t, hits = str(t or ""), []
    for pat in FORBIDDEN:
        hs = [m.group(0) for m in re.finditer(pat, t, re.I)]
        for h in hs: t = re.sub(re.escape(h), "", t, flags=re.I)
        hits += hs
    if hits: issues.append({"kind": "overclaim_removed", "detail": hits[:5]})
    return t, hits



def keep_facts(blocks, changes, limit=80):
    rev = [squeeze(c.get("revised_quote")) for c in changes if c.get("revised_quote")]
    out = []
    for b in blocks:
        if b.get("level") or any(r and r in squeeze(b.get("text")) for r in rev):
            continue
        for s in re.split(r"(?<=[.!?。！？])(?!\d)\s*", str(b.get("text", "")).strip()):
            s = s.strip()
            if s and (re.search(r"\d", s) or re.search(r"\[\d+\]", s)):
                out.append({"locator": b.get("label"), "quote": s[:300], "changed": False,
                            "kind": "numeric" if re.search(r"\d", s) else "citation"})
            if len(out) >= limit:
                return out
    return out



def find_locator(q, bs):
    q = squeeze(q)
    if not q: return None
    for b in bs:
        if q in squeeze(b["text"]): return b["label"]
    return None



def run_edits(bs, edits, issues):
    bs = [{"label": b["label"], "text": b["text"], "level": b["level"]} for b in bs]
    recs = []
    for i, e in enumerate(edits):
        e = e if isinstance(e, dict) else {}
        rec = {"id": str(e.get("id") or "E%02d" % (i + 1)), "applied": False, "why": "",
               "original_quote": str(e.get("original_quote") or "").strip(),
               "revised_quote": str(e.get("revised_quote") or "").strip()}
        op, oq, rq = str(e.get("op") or "replace").lower(), rec["original_quote"], rec["revised_quote"]
        anc = e.get("anchor") or e.get("locator")
        if not rq: rec["why"] = "revised_quote is empty"
        elif op.startswith("replace"):
            if not oq: rec["why"] = "original_quote is empty"
            else:
                idx = block_at(bs, anc, oq)
                if idx is None: rec["why"] = "original_quote does not occur in baseline"
                else:
                    bs[idx]["text"], ok = swap_text(bs[idx]["text"], oq, rq, -1 if op == "replace_all" else 1)
                    rec["applied"], rec["why"] = ok, "" if ok else "replacement could not be applied"
        elif op in ("append_after", "insert_after"):
            idx = block_at(bs, anc, oq) if (anc or oq) else len(bs) - 1
            if idx is None: rec["why"] = "anchor block not located"
            else: bs.insert(idx + 1, {"label": "", "text": rq, "level": 0}); rec["applied"] = True
        elif op in ("append_end", "insert_section"):
            bs.append({"label": "", "text": rq, "level": 0}); rec["applied"] = True
        else: rec["why"] = "unsupported op: %s" % op
        if not rec["applied"]:
            issues.append({"kind": "edit_not_applied", "id": rec["id"], "detail": rec["why"]})
        recs.append(rec)
    return [b["text"] for b in bs], recs



def swap_text(text, oq, rq, count):
    if oq and oq in text: return text.replace(oq, rq, count), True
    m = re.compile(r"\s+".join(re.escape(t) for t in oq.split())).search(text) if oq else None
    if m: return text[:m.start()] + rq + text[m.end():], True
    return text, False



def block_at(bs, anchor, oq):
    if anchor:
        for i, b in enumerate(bs):
            if b["label"] == anchor and (not oq or squeeze(oq) in squeeze(b["text"])): return i
    if oq:
        for i, b in enumerate(bs):
            if oq in b["text"]: return i
        for i, b in enumerate(bs):
            if squeeze(oq) in squeeze(b["text"]): return i
    if anchor:
        for i, b in enumerate(bs):
            if b["label"] == anchor: return i
    return None



def split_comments(text):
    units, cur = [], None
    for ln in str(text or "").splitlines():
        s = ln.strip()
        if not s:
            if cur: cur["body"].append("")
            continue
        head, cand = ln.lstrip().startswith("#"), None
        if head and re.search(r"comment|reviewer|referee|point|item|remark|意见|审稿|问题", s, re.I) and re.search(r"\d", s):
            cand = re.sub(r"^#+\s*", "", s).strip(" *")
            if re.match(r"^(reviewer|审稿人)\s*\d+\s*$", cand, re.I): cur = None; continue
        elif not head and re.match(r"^(?:\*\*)?(?:comment|point|item|q|c|r|意见|问题)\s*[#]?\.?\s*\d{1,2}(?:\.\d{1,2})?\b", s, re.I):
            cand = s.strip(" *")
        elif not head and re.match(r"^(?:\*\*)?\d{1,2}[.)、)）]\s+\S", s) and len(s) > 12:
            cand = s.strip(" *")
        if cand is None and cur is None and head:
            continue
        if cand:
            units.append({"label": cand[:120], "body": []}); cur = units[-1]
            rest = re.sub(r"^.{0,40}?\d{1,2}(?:\.\d+)?\s*[:：.\-–)）]?\s*", "", cand)
            if rest and len(rest) > 12 and rest != cand: cur["body"].append(rest)
            continue
        if cur is None:
            units.append({"label": "Comment %d" % (len(units) + 1), "body": []}); cur = units[-1]
        cur["body"].append(s)
    out = []
    for i, u in enumerate(units, 1):
        body = "\n".join(u["body"]).strip()
        if body or u["label"]:
            out.append({"comment_id": "C%d" % i, "source_label": u["label"], "body": body})
    if not out and str(text).strip():
        out.append({"comment_id": "C1", "source_label": "Comment 1", "body": str(text).strip()})
    return out



def split_blocks(text):
    blocks, buf = [], []
    for ln in str(text or "").splitlines():
        if ln.strip() == "":
            if buf: blocks.append("\n".join(buf)); buf = []
        else: buf.append(ln)
    if buf: blocks.append("\n".join(buf))
    out = []
    for i, b in enumerate(blocks, 1):
        m = re.match(r"^(#{1,6})\s", b)
        out.append({"label": "P%03d" % i, "text": b, "level": len(m.group(1)) if m else 0})
    return out



def scan_input(inp):
    """Locate materials by semantics: filename hints plus word frequency, never fixed keys."""
    inp = Path(inp)
    info = {"case": {}, "files": [], "baseline": None, "comments": [], "errors": []}
    cands = [inp / "case.json"] if (inp / "case.json").is_file() else \
        [p for p in walk_files(inp) if p.suffix.lower() == ".json" and "case" in p.name.lower()][:3]
    for c in cands:
        d, e = read_json(c)
        if e:
            info["errors"].append({"where": str(c), "error": "unreadable case JSON (%s)" % e}); continue
        if isinstance(d, dict): info["case"] = d; break
    sc = []
    for p in walk_files(inp):
        if p.suffix.lower() not in PLAIN_SUFFIXES:
            if p.name != "case.json": info["files"].append(str(p))
            continue
        t = slurp(p); info["files"].append(str(p))
        cn = 3.0 if re.search(r"comment|reviewer|referee|response|意见|审稿", p.name, re.I) else 0.0
        if re.search(r"manuscript|baseline|draft|paper|正文|稿件|论文", p.name, re.I): cn -= 2.0
        head = t[:4000]
        cn += 2.0 * len(re.findall(r"reviewer|referee|comment|审稿人|意见", head, re.I)) / max(1, len(head) / 500.0)
        bn = (3.0 if re.search(r"manuscript|baseline|draft|paper|article|正文|稿件|论文", p.name, re.I) else 0.0) \
            - (3.0 if re.search(r"comment|reviewer|意见|审稿", p.name, re.I) else 0.0) + min(3.0, len(t) / 4000.0)
        sc.append({"path": p, "text": t, "c": cn, "b": bn})
    cm = [x for x in sc if x["c"] > 1.0]
    rest = [x for x in sc if x["c"] <= 1.0] or ([max(sc, key=lambda x: len(x["text"]))] if sc else [])
    if rest: info["baseline"] = max(rest, key=lambda x: x["b"])
    info["comments"] = sorted(cm, key=lambda x: -x["c"])[:4]
    return info



def walk_files(root):
    out = []
    try:
        for p in sorted(Path(root).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts: out.append(p)
    except Exception: pass
    return out[:400]



def guess_lang(t):
    zh, en = len(re.findall(r"[\u4e00-\u9fff]", t)), len(re.findall(r"[A-Za-z]", t))
    return "zh" if zh >= 20 and zh * 3 >= en else "en"



def dump_json(p, o): dump_text(p, json.dumps(o, ensure_ascii=False, indent=2))



def dump_text(p, s):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(str(s), encoding="utf-8")



def read_json(p):
    try: return json.loads(slurp(p)), None
    except Exception as e: return None, "%s: %s" % (type(e).__name__, e)



def squeeze(s): return re.sub(r"\s+", " ", str(s or "")).strip()



def slurp(p):
    try: return Path(p).read_text(encoding="utf-8", errors="replace")
    except Exception: return ""



def tone_of(d): return TONE_MAP.get(d, "accept")



def elapsed(): return round(time.time() - START_TS, 3)


def now_iso():
    """Local wall-clock timestamp with offset; naive ISO on exotic hosts."""
    try: return datetime.now().astimezone().isoformat(timespec="milliseconds")
    except Exception: return ""


def log_event(events, phase, ok=True, **detail):
    """Append one real phase record; consumed by evidence_assets.write_run_log()."""
    try:
        events.append({"ts": now_iso(), "elapsed": elapsed(), "phase": str(phase),
                       "ok": bool(ok), "detail": detail})
    except Exception:
        pass


def probe_degraded_paths():
    """Runtime probe of empty input and malformed case.json using the real helpers."""
    probe = {}
    try:
        with tempfile.TemporaryDirectory(prefix="rbw-probe-") as td:
            t = Path(td)
            try:
                i = scan_input(t)
                probe["empty_input"] = {
                    "ok": not i.get("baseline") and not i.get("comments") and not i.get("errors"),
                    "baseline_found": bool(i.get("baseline"))}
            except Exception as exc:
                probe["empty_input"] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
            try:
                (t / "case.json").write_text('{"case_id": "BROKEN", "output_contract": {',
                                             encoding="utf-8")
                obj, err = read_json(t / "case.json")
                i = scan_input(t)
                probe["bad_case_json"] = {
                    "ok": obj is None and bool(err) and len(i.get("errors") or []) >= 1,
                    "error_recorded": bool(err)}
            except Exception as exc:
                probe["bad_case_json"] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    except Exception as exc:
        probe["probe_environment"] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    return probe

if __name__ == "__main__":
    sys.exit(cli())
