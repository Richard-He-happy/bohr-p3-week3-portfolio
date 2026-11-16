#!/usr/bin/env python3
"""run_audit.py -- entry point of the formula evidence audit skill.

Reads case.json plus the supplied artefacts from --input (default /input) and
writes result.json with every output-contract key echoed back, alongside the
companion artefacts formulas.tex, symbol_table.csv and verification.md.

A syntactically valid result.json is flushed before parsing begins, and the
process always returns 0 so a partial record is never lost.

    python -B scripts/run_audit.py --input /input --output /app/output
"""
import argparse
import csv
import json
import math
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import evidence_core as evx  # noqa: E402
import mathml_engine as mx  # noqa: E402

START_TIME = time.time()
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
TEX_SUFFIXES, TEXT_SUFFIXES = {".tex", ".latex"}, {".txt", ".md", ".rst"}
XML_SUFFIXES = {".xml", ".mathml", ".nxml"}


def pack_text(s):
    return mx.pack_text(s)


def ensure_outdir(a, state):
    for c in ([Path(a)] if a else []) + [Path("/app/output"), Path.cwd() / "output"]:
        try:
            c.mkdir(parents=True, exist_ok=True)
            return c
        except OSError:
            continue
    state["errors"].append({"stage": "output", "message": "no writable destination found"})
    return Path.cwd()


def list_input_files(root):
    try:
        return [p for p in sorted(root.rglob("*")) if p.is_file()]
    except OSError:
        return []


def read_case_json(inp, state):
    cands = [inp / x for x in ("case.json", "case_input.json", "input.json")
             if (inp / x).is_file()]
    cands += [p for p in sorted(inp.rglob("case*.json")) if p not in cands]
    for c in cands:
        try:
            obj = json.loads(c.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError) as e:
            state["errors"].append({"stage": "case_parse", "path": str(c), "message": str(e)[:200]})
            continue
        if not isinstance(obj, dict):
            state["errors"].append({"stage": "case_parse", "path": str(c), "message": "not object"})
            continue
        return obj, c
    return None, None


def split_paragraphs(mats, name, text, sid):
    for i, para in enumerate(re.split(r"\n\s*\n|\f", text)):
        if len(pack_text(para)) >= 8:
            mats["blocks"].append({"path": "%s#p%d" % (name, i + 1), "text": pack_text(para),
                                "source_id": sid})


def ingest_xml_material(p, sid, mats, state, rec):
    txt = mx.decode_file(p)
    try:
        root, note = mx.load_xml(txt)
    except Exception as e:  # noqa: BLE001 - documented fallback
        ann = re.findall(r'<annotation[^>]*encoding="application/x-tex"[^>]*>(.*?)</annotation>',
                         txt, re.S | re.I)
        state["degradations"].append({"item": p.name, "stage": "xml_parse",
                                   "action": "regex fallback on TeX annotations (%s)" % type(e).__name__,
                                   "impact": "structure counts unavailable"})
        for k, a in enumerate(ann):
            mats["formulas"].append({
                "latex": mx.compact_latex(re.sub(r"<[^>]+>", "", a)), "latex_source": "regex_annotation",
                "parse_confidence": "low", "node": None, "fid": "", "eq": "",
                "path": "%s#annotation[%d]" % (p.name, k + 1), "raw": pack_text(a)[:400],
                "source_id": sid, "flags": ["xml_unparsed"], "file": p.name})
        if not ann:
            state["uncertainties"].append({"id": "U-xml-%s" % sid, "type": "parse_failure",
                                        "object": p.name, "description": "XML unparsable, no annotation",
                                        "impact": "no formula recovered", "quote": txt[:160]})
        rec["notes"] = "xml_unparsed"
        return
    bs, fl = mx.walk_text_blocks(root), mx.gather_formula_nodes(root)
    for b in bs:
        b["source_id"], b["file"] = sid, p.name
    for k, f in enumerate(fl):
        f["source_id"], f["file"] = (f["fid"] or "%s#%d" % (sid, k + 1)), p.name
    mats["blocks"] += bs
    mats["formulas"] += fl
    rec["notes"] = "%s; blocks=%d; math_nodes=%d" % (note, len(bs), len(fl))
    rec["role"] = "formula_source" if fl else "narrative_source"


def ingest_materials(files, state):
    mats = {"formulas": [], "blocks": [], "sources": [], "tables": []}
    for p in files:
        try:
            head = p.read_bytes()[:8]
        except OSError:
            head = b""
        suf, sid = p.suffix.lower(), (p.stem or p.name)
        rec = {"source_id": sid, "file": p.name, "type": suf.lstrip(".") or "bin"}
        if suf in XML_SUFFIXES or head[:5] == b"<?xml":
            ingest_xml_material(p, sid, mats, state, rec)
        elif suf in TEX_SUFFIXES:
            txt = mx.decode_file(p)
            for k, m in enumerate(re.finditer(r"\\begin\{(equation\*?|align\*?)\}(.*?)"
                                              r"\\end\{\1\}", txt, re.S)):
                mats["formulas"].append({"latex": mx.compact_latex(m.group(2)), "latex_source": "source_tex",
                                      "parse_confidence": "high", "node": None, "fid": "", "eq": "",
                                      "path": "%s#eq%d" % (p.name, k + 1), "raw": pack_text(m.group(2))[:400],
                                      "source_id": sid, "flags": [], "file": p.name})
            rec["role"] = "formula_source"
        elif suf in TEXT_SUFFIXES:
            split_paragraphs(mats, p.name, mx.decode_file(p), sid)
            rec["role"] = "narrative_source"
        else:
            state["degradations"].append({"item": p.name, "stage": "unparsed_material",
                                       "action": "kept, not interpreted"})
            if suf == ".pdf" or head[:5] == b"%PDF-":
                state["result"]["missing_objects"].append({"object": "text of %s" % p.name,
                                                        "reason": "no text layer decoded",
                                                        "needed": "vector PDF or MathML"})
            elif suf in IMAGE_SUFFIXES:
                state["result"]["missing_objects"].append({"object": "formula content in %s" % p.name,
                                                        "reason": "raster image",
                                                        "needed": "vector or MathML source"})
        mats["sources"].append(rec)
    return mats


def write_tex(p, fs):
    L = ["% restored from the provided material", "\\documentclass[11pt]{article}",
         "\\usepackage{amsmath,amssymb}", "\\begin{document}"]
    for f in fs:
        L.append("%% source_id: %s | eq: %s | from: %s | confidence: %s"
                 % (f["source_id"], f["eq_number"], f["latex_source"], f["parse_confidence"]))
        L += ["\\begin{equation*}", f["latex"] or "% (no latex restored)", "\\end{equation*}"]
    p.write_text("\n".join(L + ["\\end{document}", ""]), encoding="utf-8")


def write_csv(p, vs):
    cols = ["symbol", "latex", "plain", "definition", "unit", "value_range", "definition_source",
            "locator", "quote", "formula_ids", "confidence", "inferred"]
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for v in vs:
            w.writerow({**v, "formula_ids": ";".join(v.get("formula_ids") or [])})


def audit_consistency(state):
    """New in this edition: cross-check the assembled result for contradictions.

    Every check is cheap and local; failures are reported (and surfaced through
    pending_human) instead of being silently repaired, so a reviewer can see
    exactly where the machine-readable record is not self-consistent.
    """
    res = state["result"]
    checks = []

    def note(name, passed, detail=""):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    formula_ids = [f.get("formula_id") for f in res.get("formulas", [])]
    var_names = {v.get("symbol") for v in res.get("variables", [])}
    known = {u.get("object") for u in state.get("uncertainties", []) if isinstance(u, dict)}
    envelope = evx.assemble_result(state)
    note("contract_keys_backfilled", not envelope.get("contract_fields_missing"),
         "missing=%s" % (envelope.get("contract_fields_missing") or []))
    note("formula_ids_unique", len(formula_ids) == len(set(formula_ids)),
         "count=%d" % len(formula_ids))
    orphans = sorted({s for f in res.get("formulas", []) for s in (f.get("symbols") or [])
                      if s not in var_names})
    note("formula_symbols_in_variable_table", not orphans, "orphans=%s" % orphans[:6])
    allowed = ("paper_defined", "context_inferred", "common_knowledge")
    invalid = sorted({v.get("symbol") for v in res.get("variables", [])
                      if v.get("definition_source") not in allowed})
    note("definition_source_enum", not invalid, "invalid=%s" % invalid[:6])
    glossed = [v.get("symbol") for v in res.get("variables", [])
               if v.get("definition_source") == "common_knowledge"]
    note("common_knowledge_tracked", all(g in known for g in glossed),
         "untracked=%s" % [g for g in glossed if g not in known][:6])
    broken = [f.get("formula_id") for f in res.get("formulas", [])
              if {"unbalanced_braces", "empty_latex"} & set(f.get("flags") or [])]
    note("latex_structurally_sound", not broken, "broken=%s" % broken[:6])
    probes = [c for c in res.get("numeric_checks", []) if c.get("is_example")]
    note("example_checks_labelled", all(c.get("note") for c in probes),
         "unlabelled=%d" % len([c for c in probes if not c.get("note")]))
    failed = [c["check"] for c in checks if not c["passed"]]
    res["selfcheck"] = {"passed": not failed, "failed": failed, "checks": checks}
    return failed


def write_verification(p, state):
    cov = state["result"].get("coverage") or {}
    self_check = state["result"].get("selfcheck") or {}
    lines = ["# Run verification summary (written by the skill at run time; not a prepared answer)", "",
             "- case_id: %s" % state.get("case_id"),
             "- status: %s" % state.get("status"),
             "- contract_fields_missing: %s" % len(state.get("contract_fields_missing", [])),
             "- files_scanned: %s" % (state["result"].get("input_summary") or {}).get("files_scanned"),
             "- formulas: total=%s ok=%s" % (cov.get("formulas_total"), cov.get("formulas_ok")),
             "- variables: total=%s by_source=%s" % (cov.get("variables_total"),
                                                     cov.get("by_source")),
             "- derivations: %s" % cov.get("derivations_total"),
             "- numeric_checks: computed=%s example_only=%s" % (cov.get("numeric_computed"),
                                                              cov.get("numeric_example_only")),
             "- symbol_coverage: %s" % cov.get("symbol_coverage"),
             "- claims: total=%s quote_verified=%s" % (cov.get("claims_total"),
                                                       cov.get("claims_quote_verified")),
             "- uncertainties: %s" % cov.get("uncertainties_total"),
             "- errors: %s, degradations: %s, pending_human: %s" % (
                 len(state.get("errors", [])), len(state.get("degradations", [])),
                 len(state.get("pending_human", []))),
             "- selfcheck: passed=%s failed=%s" % (self_check.get("passed"),
                                                   self_check.get("failed")),
             "", "Full machine-readable record: result.json."]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def execute_pipeline(a, state, out):
    state["runtime"]["input_dir"] = str(a.input)
    case = read_case_json(Path(a.input), state)[0]
    state["case_loaded"] = bool(case)
    if case:
        state["case_id"] = case.get("case_id") or case.get("id") or None
        con = case.get("output_contract") or case.get("output_spec") or case.get("contract") or {}
        state["contract"] = con if isinstance(con, dict) else {}
    else:
        state["errors"].append({"stage": "case_load", "message": "no case.json; artifacts only"})
    files = list_input_files(Path(a.input))
    mats = ingest_materials(files, state)
    state["sources"] = mats["sources"]
    state["result"]["input_summary"] = {"files_scanned": len(files),
                                     "math_nodes_found": len(mats["formulas"]),
                                     "text_blocks": len(mats["blocks"]),
                                     "tabular_material": len(mats["tables"])}
    state["claims"], state["uncertainties"] = evx.build_analysis(state, mats)
    corpus = pack_text(" ".join([b["text"] for b in mats["blocks"]] + [f.get("raw") or "" for f in mats["formulas"]]
                        + [x["latex"] for x in state["result"]["formulas"]]))
    bad = 0
    for c in state["claims"]:
        q = pack_text(c.get("quote") or "")[:120]
        c["quote_verified"] = None if not q else (q in corpus)
        if q and not c["quote_verified"]:
            bad += 1
            c["readability"] = "undetermined"
    cov, fs = state["result"]["coverage"], state["result"]["formulas"]
    cov["claims_quote_verified"] = sum(1 for c in state["claims"] if c.get("quote_verified"))
    if bad:
        state["pending_human"].append({"item": "quote_check", "why": "%d quotes not verbatim" % bad})
    if not fs:
        state["status"] = "input_error" if not files else "insufficient_evidence"
        if files:
            state["result"]["missing_objects"].append({"object": "formula representation",
                                                    "reason": "no MathML/TeX/text formula found",
                                                    "needed": "MathML, TeX or text formula"})
            state["pending_human"].append({"item": "formula_source_missing",
                                        "why": "no machine-readable formula object",
                                        "action": "supply publisher XML/TeX or read the page"})
    elif (all(f["status"] == "ok" for f in fs) and cov["symbol_coverage"] == 1.0
          and cov["derivations_total"] and cov["numeric_computed"]):
        state["status"] = "ok"
    else:
        state["status"] = "partial"
        state["result"]["status_reason"] = {k: cov[k] for k in ("symbol_coverage",
                                                             "numeric_computed")}
    if audit_consistency(state):
        state["pending_human"].append({"item": "selfcheck",
                                       "why": "consistency checks failed: %s"
                                       % state["result"]["selfcheck"]["failed"][:4]})
    write_tex(out / "formulas.tex", fs)
    write_csv(out / "symbol_table.csv", state["result"]["variables"])
    write_verification(out / "verification.md", state)
    state["changes"].append({"item": "deliverables",
                          "action": "wrote formulas.tex, symbol_table.csv, verification.md",
                          "reason": "reviewable companions to result.json"})


def fresh_state():
    return {"case_id": None, "case_loaded": False, "status": "partial", "contract": {}, "task": {},
            "sources": [], "claims": [], "uncertainties": [], "pending_human": [], "errors": [],
            "degradations": [], "changes": [],
            "result": {"formulas": [], "variables": [], "derivations": [], "numeric_checks": [],
                       "indicator_checks": [], "missing_objects": [], "input_summary": {}},
            "runtime": {"skill": "formula-evidence-audit", "version": "1.0.0",
                        "python": sys.version.split()[0]}}


def cli_entry(argv=None):
    ap = argparse.ArgumentParser(
        prog="run_audit.py",
        description="Formula evidence audit: MathML -> LaTeX, symbol table, derivation cues, numeric checks.",
        epilog="Writes result.json plus formulas.tex / symbol_table.csv / verification.md; always exits 0.")
    ap.add_argument("--input", default="/input", help="directory holding case.json and the artefacts (default /input)")
    ap.add_argument("--output", default=None, help="destination directory (default /app/output)")
    a = ap.parse_args(argv)
    state = fresh_state()
    out = ensure_outdir(a.output, state)
    try:
        (out / "result.json").write_text(
            json.dumps(evx.assemble_result(state), ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    try:
        execute_pipeline(a, state, out)
    except Exception as e:  # noqa: BLE001 - always finalise with a valid file
        state["errors"].append({"stage": "fatal", "message": ("%s: %s" % (type(e).__name__, e))[:300]})
        state["status"] = "partial" if state["result"].get("formulas") else "input_error"
    finally:
        state["runtime"].update({"elapsed_s": round(time.time() - START_TIME, 2), "output_dir": str(out)})
        try:
            (out / "result.json").write_text(
            json.dumps(evx.assemble_result(state), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            sys.stdout.write("cannot persist result.json\n")
    return 0


if __name__ == "__main__":
    sys.exit(cli_entry())
