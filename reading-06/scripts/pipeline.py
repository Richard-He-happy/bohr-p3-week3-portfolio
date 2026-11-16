#!/usr/bin/env python3
"""paper-evidence-ledger: build one contract-compliant result.json from a paper case.

Two stages: prepare indexes the corpus, writes a partial result.json that already holds
one slot per requested field_id, and creates an editable draft; finalize merges the draft,
applies the acceptance gate, then writes result.json and a reviewable fields.csv.
Standard library only; the process exit code is always 0.
"""
import argparse, csv, json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks as V
try:                       # additive layer: five audit assets (patch increment); never fatal
    import assets as A
except Exception:
    A = None
SUMMARY_KEYS = ("golden_standard", "diff_report", "version_history", "run_log", "self_check")


def _log(_stage, msg="", **kv):
    if A is not None:
        try:
            A.log(_stage, msg, **kv)
        except Exception:
            pass

TEXT_KEYS = ("text", "content", "body", "passage", "paragraph", "abstract", "summary", "caption", "sentence")
ID_KEYS, SECTION_KEYS = ("paragraph_id", "para_id", "pid", "block_id", "id"), ("section", "section_name", "heading", "part", "chapter")
FIELD_ID_KEYS, FIELD_NAME_KEYS = ("field_id", "id", "key", "slug"), ("field_name", "name", "label", "title")
LOCATOR_FIELDS = V.LOCATOR_FIELDS
LOCATOR_ORDER = ("paragraph_id", "page", "table_id", "row_header", "col_header", "section", "figure_id")
DRAFT_KEYS = ("value", "units", "statistic", "condition", "comparator", "status", "quote", "quote_join", "notes", "claim_type", "kind",
      "search_scope", "original_value", "original_unit", "conversion_rule", "parsed_value", "parsed_unit", "conflicts")
CSV_COLUMNS = ("field_id", "field_name", "status", "value", "units", "statistic", "condition", "comparator", "source_id", "section", "paragraph_id",
        "page", "table_id", "row_header", "col_header", "quote", "claim_type", "condition_complete", "rules_failed", "notes")
DRAFT_NOTES = ["Exactly one object per field_id; status is one of reported, not_reported, source_conflict, extraction_failed.",
         "Copy value exactly as printed (signs, ranges, n=3, p<0.05); keep units and statistic in separate keys; quote word for word.",
         "Locate with paragraph_id, or with table_id plus verbatim row_header and col_header. Never guess and never zero-fill."]


def as_grid(n):
    """Normalise rows given as list[list] or list[dict] into (grid, caption, page, id)."""
    if not isinstance(n, dict):
        return None
    cap, tid, page = pick(n, ("caption", "title")), pick(n, ("table_id", "id", "label")), n.get("page")
    for k in ("rows", "data", "body", "cells", "grid"):
        r = n.get(k)
        if not isinstance(r, list) or not r:
            continue
        if all(isinstance(x, dict) for x in r):
            h = [str(x) for x in (n.get("columns") or n.get("headers") or list(r[0]))]
            return [[h] + [[str(x.get(c, "")) for c in h] for x in r], cap, page, tid]
        if all(isinstance(x, (list, tuple)) for x in r):
            gg, h = [[str(c) for c in x] for x in r], [str(x) for x in (n.get("headers") or n.get("columns") or [])]
            return [[h] + gg if h and h != gg[0] else gg, cap, page, tid]
    return None


def blank_slots(fs):
    return [dict(f, status="extraction_failed", value=None, unit_hits=None, statistic=None, condition=None, comparator=None, quote=None,
                 claim_type=None, source={k: None for k in LOCATOR_FIELDS}, notes="slot reserved by prepare") for f in fs]


def cli(argv=None):
    ap = argparse.ArgumentParser(prog="pipeline.py", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description="Turn a paper case into result.json: one record per target field holding value, units, statistic, experimental condition, comparator, verbatim quote, exact locator and one of four states.",
                                 epilog="Writes <out>/result.json and <out>/fields.csv plus <work>/corpus_index.json and <work>/draft.json. Exit status stays 0 even on failure; issues land in errors and degradations.")
    ap.add_argument("--stage", choices=["prepare", "finalize", "run"], default="run", help="prepare indexes the corpus and writes skeleton slots; finalize merges the draft and gates every field; run is the same as finalize")
    ap.add_argument("--input", help="case input directory; falls back to /input, /app/input or ./input")
    ap.add_argument("--output", help="directory for result.json and fields.csv; defaults under /app/output")
    ap.add_argument("--work", help="scratch directory for corpus_index.json and draft.json")
    ap.add_argument("--draft", help="optional explicit draft file, default <work>/draft.json")
    a = ap.parse_args(argv)
    inp, out, work = resolve_input(a.input), resolve_output(a.output, "output"), resolve_output(a.work, "work")
    if A is not None:
        try:
            A.start_log(out, sys.argv, inp, out, a.stage)
        except Exception:
            pass
    _log("boot", "pipeline start", phase=a.stage, input=inp, output=out, work=work)
    errs, degr = [], []
    doc, msg = None, ""
    try:
        if a.stage == "prepare":
            q = stage_prepare(inp, out, work, errs, degr)
            msg = "prepare finished: fields=%d units=%d tables=%d" % (len(q[1]), len(q[2]), len(q[3]))
        else:
            doc = stage_finalize(inp, out, work, errs, degr, a.draft)
            msg = "finalize finished: status=%s coverage=%s" % (doc["status"], doc["result"]["coverage"])
    except Exception as e:
        import traceback
        errs.append({"stage": "fatal", "detail": "%s: %s" % (type(e).__name__, e), "trace": traceback.format_exc()[-800:]})
        try:
            o, _ = read_json(inp / "case.json")
            case = o if isinstance(o, dict) else {}
        except Exception:
            case = {}
        doc = wrap_envelope(case.get("case_id"), "partial", {"fields": [], "coverage": tally([]), "method_notes": "the run ended on a fatal error"},
                            [], [], [], [], errs, degr, [{"action": "fallback partial result written"}], list(case.get("output_contract") or []))
        if A is not None:
            try:
                A.fallback(out, errs[-1]["detail"])
            except Exception:
                pass
        write_json(out / "result.json", doc)
        msg = "recovered from fatal error: a partial result was written"
    if A is not None:
        try:
            A.finish_log((doc or {}).get("status") or ("prepared" if a.stage == "prepare" else "partial"), 0)
            if isinstance(doc, dict):
                A.settle(doc, out)
        except Exception:
            pass
    print(json.dumps({"ok": True, "message": msg, "result": str(out / "result.json")}, ensure_ascii=False))
    return 0


def collect_paragraphs(n, out, sec="", page=None):
    if isinstance(n, dict):
        sec, t, page = pick(n, SECTION_KEYS) or sec, pick(n, TEXT_KEYS), n.get("page", n.get("page_number", page))
        if t and len(t) >= 40 and re.search(r"[A-Za-z\u4e00-\u9fff]{2,}[\s,]", t) and not re.fullmatch(r"[\d\s|.,%\-]+", t):
            out.append({"paragraph_id": pick(n, ID_KEYS), "section": sec, "page": page, "text": t})
            return
        for v in n.values():
            collect_paragraphs(v, out, sec, page)
    elif isinstance(n, list):
        for v in n:
            collect_paragraphs(v, out, sec, page)


def collect_tables(n, out):
    if isinstance(n, dict):
        x = as_grid(n)
        if x:
            out.append(x)
        for v in ([] if x else n.values()):
            collect_tables(v, out)
    elif isinstance(n, list):
        for v in n:
            collect_tables(v, out)


def discover_targets(inp, case, errs):
    for n in ("target-fields.json", "target_fields.json"):
        if (inp / n).is_file():
            o, e = read_json(inp / n)
            if e:
                errs.append({"stage": "target_fields", "path": n, "detail": e})
            elif normalize_targets(o):
                return normalize_targets(o), n
    for src in [case] + [read_json(p)[0] for p in iter_files(inp) if p.suffix == ".json" and p.name != "case.json"]:
        if isinstance(src, dict):
            for k in ("target_fields", "target-fields", "fields", "requested_fields", "extraction_fields"):
                if k in src and normalize_targets(src[k]):
                    return normalize_targets(src[k]), k
    return [], ""


def iter_files(i):
    return [p for p in sorted(i.rglob("*")) if p.is_file() and not p.name.startswith(".")]


def normalize_targets(raw):
    """Flatten any accepted target-list shape into field record dicts."""
    if isinstance(raw, dict):
        for k in ("fields", "target_fields", "target-fields", "requested_fields", "items"):
            if isinstance(raw.get(k), (list, dict)):
                raw = raw[k]
                break
    if isinstance(raw, dict):
        raw = [{"field_id": k, "field_name": k, "definition": v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)} for k, v in raw.items()]
    res, seen = [], set()
    for f in (raw if isinstance(raw, list) else []):
        f = {"field_id": to_slug(f), "field_name": f} if isinstance(f, str) else f
        if not isinstance(f, dict):
            continue
        fid = pick(f, FIELD_ID_KEYS)
        if not fid or fid in seen:
            continue
        seen.add(fid)
        res.append({"field_id": fid, "field_name": pick(f, FIELD_NAME_KEYS) or fid, "definition": pick(f, ("definition", "desc", "description", "hint")),
                    "expected_type": pick(f, ("expected_type", "type", "value_type")), "unit_hint": pick(f, ("unit_hint", "units", "unit")),
                    "context_hint": pick(f, ("context_hint", "context", "scope")), })
    return res


def pick(d, ks):
    for k in ks:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def read_json(p):
    try:
        return json.load(open(p, encoding="utf-8", errors="replace")), None
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def resolve_input(a):
    import os
    for x in ([a] if a else []) + [os.environ.get("INPUT_DIR"), "/input", "/app/input", "input"]:
        if x and Path(x).is_dir():
            return Path(x).resolve()
    return Path("/input")


def resolve_output(a, sub):
    if a:
        return Path(a).resolve()
    for c in ("/app/" + sub, str(Path.cwd() / sub), sub):
        try:
            Path(c).mkdir(parents=True, exist_ok=True)
            return Path(c).resolve()
        except Exception:
            pass
    return Path(".")


def scan_corpus(inp, case, errs, degr):
    """Collect paragraphs and grids from case.json, material JSON, MD/TXT/CSV and PDF."""
    unit_hits, tbl, src, sid, ps, ts = [], [], [], 0, [], []
    if isinstance(case, dict):
        collect_paragraphs(case, ps)
        collect_tables(case, ts)
    if ps or ts:
        sid = 1
        src.append({"source_id": "S1", "kind": "case_json", "path": "case.json", "units": len(ps)})
        unit_hits += [dict(x, source_id="S1") for x in ps]
        tbl += ts
    for p in iter_files(inp):
        s, nm = p.suffix.lower(), p.name
        if nm in ("case.json", "target-fields.json", "target_fields.json", "public-manifest.json", "task.md"):
            continue
        sid_, kind = "S%d" % (sid + 1), s[1:] or "file"
        if s == ".json":
            o, e = read_json(p)
            if e:
                errs.append({"stage": "read_json", "path": nm, "detail": e})
                continue
            ps, ts = [], []
            collect_paragraphs(o, ps)
            collect_tables(o, ts)
            if not ps and not ts:
                continue
            unit_hits += [dict(x, source_id=sid_) for x in ps]
            tbl += ts
        elif s in (".csv", ".md", ".markdown", ".txt", ".rst"):
            t = p.read_text(encoding="utf-8", errors="replace")
            if s == ".csv":
                tbl += V.csv_tables(t, sid_, None, "C", p.stem)
            else:
                tbl += V.md_tables(t, sid_)
                unit_hits += [{"source_id": sid_, "section": "", "page": None, "text": b, "generated_id": True, "file": nm,
                           "paragraph_id": "%s-p%03d" % (to_slug(p.stem), i)} for i, b in enumerate(V.blocks_of_text(t), 1)]
        elif s == ".pdf":
            try:
                pgs, meta = V.read_pdf(p)
            except Exception as e:
                errs.append({"stage": "pdf", "path": nm, "detail": str(e)})
                degr.append({"stage": "pdf", "path": nm, "detail": "the PDF could not be read"})
                continue
            if meta.get("quality") in ("no_text_layer", "encrypted", "low"):
                degr.append({"stage": "pdf", "path": nm, "meta": meta, "detail": "text layer quality is %s; fields depending on it stay extraction_failed" % meta.get("quality"),
                             "action": "pending_human"})
            unit_hits += [{"source_id": sid_, "section": "", "page": pg["page"], "text": pg["text"], "generated_id": True, "file": nm,
                       "paragraph_id": "pdf-p%03d" % (pg["page"] or 0)} for pg in pgs if pg["text"]]
            src.append({"source_id": sid_, "kind": "pdf", "path": nm, "units": len(pgs), "meta": meta})
            sid += 1
            continue
        else:
            degr.append({"stage": "unsupported_material", "path": nm, "action": "pending_human"})
            continue
        src.append({"source_id": sid_, "kind": "json_material" if s == ".json" else kind, "path": nm, "units": len(ps) if s == ".json" else 0})
        sid += 1
    for i, u in enumerate(unit_hits, 1):
        u["section"] = (u.get("section") or "").strip()
        if not u.get("paragraph_id"):
            u.update(paragraph_id="P%04d" % i, generated_id=True)
    built = [x if isinstance(x, dict) else V.make_table(x[0], 1, x[3] or "T%d" % i, x[1] or "", x[2], "ST", ["auto"])
             for i, x in enumerate(tbl, 1) if (isinstance(x, dict) or x[0])]
    return unit_hits, V.join_continuations(built), src


def stage_finalize(inp, out, work, errs, degr, draft=None):
    t0 = time.time()
    case, fs, unit_hits, tbl, src, fpath = stage_prepare(inp, out, work, errs, degr)
    dp = Path(draft) if draft else (work / "draft.json")
    d, derr = read_json(dp) if dp.is_file() else (None, "draft.json absent")
    by = {}
    if derr:
        errs.append({"stage": "draft", "path": str(dp), "detail": derr, "action": "fill the draft and run finalize again"})
    else:
        by = {x["field_id"]: x for x in ((d.get("fields") if isinstance(d, dict) else d) or []) if isinstance(x, dict) and x.get("field_id")}
    _log("draft", "draft read" if not derr else "draft missing", path=dp.name, filled=len(by), requested=len(fs))
    unc, pend, cl, ofs = [], [], [], []
    for f in fs:
        got = by.get(f["field_id"])
        if not got:
            b = blank_slots([f])[0]
            b["notes"] = "draft has no entry for this field"
            ofs.append(b)
            unc.append({"field_id": f["field_id"], "type": "not_extracted", "detail": "draft has no entry for this field"})
            continue
        m = dict(f)
        m.update({k: got[k] for k in DRAFT_KEYS if k in got})
        s = dict(got.get("source") or {})
        s.update({k: got[k] for k in LOCATOR_FIELDS if k not in s and k in got})
        m["source"], m["status"] = {k: s.get(k) for k in LOCATOR_FIELDS}, got.get("status") or "extraction_failed"
        m = V.gate_field(m, unit_hits, tbl, unc, pend)
        if m["status"] == "reported":
            if not m.get("claim_type"):
                cls = V.claim_layer(" ".join([str(m.get("quote") or ""), str(m.get("value") or "")]))
                m["claim_markers"] = cls
                if re.search(r"conclu|claim|finding|interpret|limit|specul|outcome", f["field_id"] + f.get("field_name", ""), re.I) or f.get("expected_type") in ("text", "conclusion", "claim"):
                    m["claim_type"] = cls["claim_type"]
            cl.append({"claim_id": "C%02d" % (len(cl) + 1), "field_id": m["field_id"], "kind": m.get("kind") or "reported", "claim_type": m.get("claim_type"),
                       "text": m.get("value"), "units": m.get("units"), "condition": m.get("condition"), "comparator": m.get("comparator"),
                       "evidence": {"quote": m.get("quote"), "quote_join": m.get("quote_join")}, "source_id": m["source"].get("source_id"), "location": {k: m["source"].get(k) for k in LOCATOR_ORDER},
                       "readability": "directly_read" if m["validation"].get("quote_match") in ("exact", "case_normalized", "whitespace_normalized") else "inferred"})
        ofs.append(m)
    c = tally(ofs)
    assert c["reported"] + c["not_reported"] + c["source_conflict"] + c["extraction_failed"] == c["fields_requested"]
    ok = c["reported"] + c["not_reported"] + c["source_conflict"]
    _log("gate", "fields gated", coverage=c, claims=len(cl), uncertainties=len(unc), pending_human=len(pend))
    doc = wrap_envelope(case.get("case_id"), "input_error" if not fs else "insufficient_evidence" if not unit_hits and not tbl else "answered" if ok == c["fields_requested"] else "partial",
               {"fields": ofs, "coverage": c, "field_dictionary": fs, "corpus": {"n_units": len(unit_hits), "n_tables": len(tbl)},
                "search_scope_global": {"sections": sorted({u.get("section") or "unsectioned" for u in unit_hits}), "tables": [t["table_id"] for t in tbl], "sources": [x["source_id"] for x in src]},
                "method_notes": "source priority is table cell, then results text and captions, then abstract; values stay literal; conversions only recorded through original_value plus conversion_rule; conflicting readings are never averaged"},
               cl, unc, src, pend, errs, degr, [{"action": "prepare", "detail": "slots were written before any value was filled"},
                                                {"action": "finalize", "detail": "gated %d fields, coverage %s" % (len(ofs), c)}],
               list(case.get("output_contract") or []))
    if A is not None:
        try:
            A.attach(out, {"case": case, "fs": fs, "units": unit_hits, "tables": tbl, "sources": src,
                           "field_source": fpath, "inp": inp, "work": work, "errs": errs, "degr": degr,
                           "elapsed_s": round(time.time() - t0, 3)},
                     doc, inp, sys.argv)
        except Exception as e:
            errs.append({"stage": "assets", "detail": "%s: %s" % (type(e).__name__, e)})
            _log("error", "assets attach failed", detail=str(e)[:160])
            try:
                A.fallback(out, "attach failed: %s" % e)
            except Exception:
                pass
    for k in SUMMARY_KEYS:
        doc.setdefault(k, None)
    write_json(out / "result.json", doc)
    _log("result", "result.json written", status=doc.get("status"), fields=len(ofs))
    rows = []
    for x in ofs:
        r, s_, cd, q = dict.fromkeys(CSV_COLUMNS, ""), x.get("source") or {}, x.get("condition"), x.get("quote")
        r.update({"field_id": x.get("field_id"), "field_name": x.get("field_name"), "status": x.get("status"), "units": x.get("units"), "statistic": x.get("statistic"),
                  "comparator": x.get("comparator"), "source_id": s_.get("source_id"), "section": s_.get("section"), "paragraph_id": s_.get("paragraph_id"),
                  "page": s_.get("page"), "table_id": s_.get("table_id"), "row_header": s_.get("row_header"), "claim_type": x.get("claim_type"),
                  "condition_complete": x.get("condition_complete"), "notes": x.get("notes") or "",
                  "value": x.get("value") if not isinstance(x.get("value"), (list, dict)) else json.dumps(x.get("value"), ensure_ascii=False),
                  "quote": q if isinstance(q, str) else json.dumps(q, ensure_ascii=False),
                  "condition": "; ".join("%s=%s" % (k, v) for k, v in cd.items() if v) if isinstance(cd, dict) else (cd or ""),
                  "col_header": " ; ".join(s_.get("col_header")) if isinstance(s_.get("col_header"), list) else (s_.get("col_header") or ""),
                  "rules_failed": ",".join((x.get("validation") or {}).get("rules_failed") or [])})
        rows.append({k: ("" if r.get(k) is None else r.get(k)) for k in CSV_COLUMNS})
    with open(out / "fields.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    try:
        _log("csv", "fields.csv written", rows=len(rows), bytes=(out / "fields.csv").stat().st_size)
    except OSError:
        pass
    return doc


def stage_prepare(inp, out, work, errs, degr):
    case, cp = {}, None
    for n in ("case.json", "task.json"):
        if (inp / n).is_file():
            cp = inp / n
            break
    cp = cp or next((p for p in iter_files(inp) if p.suffix == ".json" and "case" in p.name.lower()), None)
    if cp:
        o, e = read_json(cp)
        if e:
            errs.append({"stage": "case_json", "path": cp.name, "detail": e, "action": "degraded"})
            degr.append({"stage": "case_json", "detail": "case.json could not be parsed"})
        elif isinstance(o, dict):
            case = o
    else:
        errs.append({"stage": "case_json", "detail": "case.json was not found in the input directory"})
    fs, fpath = discover_targets(inp, case, errs)
    unit_hits, tbl, src = scan_corpus(inp, case, errs, degr)
    _log("scan", "corpus scanned", fields=len(fs), field_source=fpath or "-", units=len(unit_hits),
         tables=len(tbl), sources=len(src), errors=len(errs), degradations=len(degr))
    write_json(work / "corpus_index.json", {"units": unit_hits, "tables": tbl})
    sk = blank_slots(fs)
    if not (work / "draft.json").exists():
        write_json(work / "draft.json", {"_instructions": DRAFT_NOTES, "fields": sk})
    write_json(out / "result.json", wrap_envelope(case.get("case_id"), "partial" if fs else "input_error",
                                   {"fields": sk, "coverage": tally(sk), "field_dictionary": fs, "field_source": fpath,
                                    "corpus": {"n_units": len(unit_hits), "n_tables": len(tbl), "sections": sorted({u.get("section") or "unsectioned" for u in unit_hits})},
                                    "method_notes": "prepare done: one slot per field created; draft still empty"}, [], [], src, [], errs, degr,
                                   [{"action": "prepare", "detail": "field slots prepared"}], list(case.get("output_contract") or [])))
    _log("prepare", "slots prepared", case_id=case.get("case_id"), fields=len(sk),
         status="partial" if fs else "input_error")
    return case, fs, unit_hits, tbl, src, fpath


def tally(fs):
    c = {"fields_requested": len(fs), "reported": 0, "not_reported": 0, "source_conflict": 0, "extraction_failed": 0}
    for f in fs:
        if f.get("status") in c:
            c[f["status"]] += 1
    return c


def to_slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_") or "f"


def wrap_envelope(cid, st, res, cl, unc, src, pend, errs, degr, chg, ck):
    d = {"case_id": cid, "status": st, "result": res, "claims": cl, "uncertainties": unc, "uncertainty": unc, "sources": src, "pending_human": pend,
         "errors": errs, "degradations": degr, "changes": chg,
         "runtime": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tool": "paper-field-extract 1.0.0", "python": sys.version.split()[0]}}
    for k in ck:
        d.setdefault(k, None)
    return d


def write_json(p, o):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    try:
        cli()
    except SystemExit:
        raise
    except Exception as e:
        print("soft failure handled: %s" % e)
    sys.exit(0)
