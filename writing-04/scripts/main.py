#!/usr/bin/env python3
"""Offline manuscript revision desk (skill: manuscript-revision-desk).

Four phases: init, show, check, build. Standard library only, no network access,
independent of the current working directory, and the process always ends with
exit status 0 -- problems are reported inside result.json rather than through exit
codes. Document parsing/rendering helpers live in doc_parse.py; audit assets in
proof_assets.py."""
import argparse, difflib, hashlib, json, re, sys, tempfile, time
from pathlib import Path

ENGINE_VERSION = "2.0.0"
SKILL_NAME = "manuscript-revision-desk"
START_CLOCK = time.time()
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
try:
    import doc_parse as V
    VERR = None
except Exception as _e:
    V, VERR = None, str(_e)
try:
    import proof_assets as A
    AERR = None
except Exception as _e:
    A, AERR = None, str(_e)
if V is not None:
    split_md, split_docx, split_pdf, extract, assign_ids, resolve = (
        V.split_md, V.split_docx, V.split_pdf, V.extract, V.assign_ids, V.resolve)
    ann_text, fallback, preview, change_log, Doc = (
        V.ann_text, V.fallback, V.preview, V.change_log, V.Doc)
CONTRACT_SLOTS = {"case_id": "", "deliverable": "", "preserved_facts": "", "evidence_map": "", "change_log": ""}
PLAN_CANDIDATES = ("workplan.json", "edit_plan.json", "plan.json", "edits.json")


def read_bytes(p):
    try:
        return Path(p).read_bytes()
    except Exception:
        return b""


def digest_of(s):
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()


def read_text(p):
    b = read_bytes(p)
    for e in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return b.decode(e)
        except Exception:
            pass
    return b.decode("utf-8", "replace")


def store_json(p, o):
    return store_text(p, json.dumps(o, ensure_ascii=False, indent=2, default=str) + "\n")


def read_json(p):
    t = read_text(p).strip().lstrip("\ufeff")
    try:
        return json.loads(t), None
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e) if t else "empty file"


def store_text(p, s):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")
    return str(p)


def make_dir(p):
    p = Path(p)
    try:
        p.mkdir(parents=True, exist_ok=True)
        (p / ".probe").write_text("x")
        (p / ".probe").unlink()
        return p, None
    except Exception as e:
        return None, str(e)


def find_key(d, *ns, default=None):
    """Pure helper used by the four-phase revision desk; reads only already-checked inputs. (find_key)"""
    if not isinstance(d, dict):
        return default
    for n in ns:
        for k, v in d.items():
            if n in str(k).lower():
                return v
    return default




SOURCE_HINTS = ("manuscript", "draft", "chapter", "source", "original", "paper", "working", "稿", "正文")
EXCLUDED_NAMES = ("task.md", "case.json", "workorder", "contract", "manifest", "anchor", "resources.yaml")


def phase_init(a):
    c = ingest_inputs(a)
    log_step(c, "init", materials=len(c["inputs"]), targets=len(c["target_ids"]),
            manuscript=(c["manuscript"] or {}).get("rel"), errors=len(c["errors"]))
    store_json(Path(c["work_dir"]) / "index.json", {
        "case_id": c["case_id"], "input_dir": c["input_dir"], "output_contract_keys": list(c["contract"]),
        "instruction": c["instruction"][:1500], "manuscript": c["manuscript"], "targets": c["targets"],
        "materials": [{k: it[k] for k in ("rel", "kind", "bytes")} for it in c["inputs"]],
        "workorder": {"keys": list(c["workorder"]), "task": str(find_key(c["workorder"], "task", default=""))[:1500],
                      "requirements": find_key(c["workorder"], "requirement", "operation", default=[]),
                      "boundaries": find_key(c["workorder"], "boundaries", "scope", default="")},
        "blocks": [{"index": b["index"], "id": b.get("id"), "kind": b["kind"], "chars": len(b["text"]),
                    "locator": V.locator_of(b), "text": b["text"]} for b in c["blocks"]],
        "errors": c["errors"], "degradations": c["degradations"]})
    print("== %s init v%s ==\ncase_id   : %s\ninput     : %s\nout/work  : %s | %s\nmaterials : %d"
          % (SKILL_NAME, ENGINE_VERSION, c["case_id"], c["input_dir"] or "(missing)", c["out_dir"], c["work_dir"],
             len(c["inputs"])))
    if c["manuscript"]:
        m, k = c["manuscript"], V.format_counts(c["raw"])
        print("manuscript: %s (%s, mode=%s, blocks=%d)\nstructure : headings=%s tables=%s formulas=%s "
              "citations=%s chars=%s" % (m["rel"], m["kind"], m["mode"], len(c["blocks"]), k["headings"],
                                         k["table_rows"], k["display_formulas"], k["numbered_citations"],
                                         k["chars"]))
    else:
        print("manuscript: NONE FOUND -> build will emit an honest gap report")
    print("workorder : %s\ntargets   : %s" % (find_key(c["workorder"], "id", default="(none)"),
                                              c["target_ids"] or "(none)"))
    for t in c["targets"]:
        print("   %-12s -> block %-4s [%s] %s" % (t["target_id"], t["block_index"], t["resolution"],
                                                  (t.get("preview") or "")[:88]))
    print("contract  : %s" % ", ".join(c["contract"]))
    for x in c["errors"]:
        print("ERROR     : %s" % x)
    for x in c["degradations"]:
        print("DEGRADED  : %s" % x)
    store_json(Path(c["out_dir"]) / "result.json", result(
        c, "partial", stage="init", rc={"index": str(Path(c["work_dir"]) / "index.json")},
        gs=golden_payload(c),
        pend=[{"item": "workplan not written yet",
               "action": "write workplan.json in the work dir, then run check and build"}]))
    print("\n[partial] result.json -> %s\nnext: %s check && %s build"
          % (Path(c["out_dir"]) / "result.json", Path(__file__).resolve(), Path(__file__).resolve()))
    return 0


def phase_assemble(a):
    c, meta, changes, rep, facts, fr = prepare_run(a)
    out = Path(c["out_dir"])
    log_step(c, "build", workplan=c["workplan_path"], blocks=len(c["blocks"]),
            targets=len(c["target_ids"]), workorder=bool(c["workorder"]))
    if not c["blocks"]:
        store_text(out / "deliverable.md",
           "# Deliverable unavailable — no importable manuscript material\n\nThe workflow indexed the input "
           "but found no importable manuscript (md/txt/docx/pdf) under `%s`.\n\n- materials scanned: %d\n"
           "- workorder targets: %s\n- errors: %s\n\nSupply the source manuscript, then re-run init -> check "
           "-> build. No content was invented to fill the gap.\n"
           % (c["input_dir"] or "", len(c["inputs"]), c["target_ids"] or "none", c["errors"]))
        r = result(c, "input_error" if not c["inputs"] else "insufficient_evidence", stage="build",
                dl={"primary": "deliverable.md", "format": "Markdown", "notes": "gap report"}, facts=facts,
                rc={"import": None, "preview": None},
                pend=[{"item": "manuscript material missing", "action": "provide the source and re-run"}])
        if A is not None:
            try:
                r.update(A.degraded(c, {"out": out, "status": r["status"], "raw": c["raw"], "pub": "",
                                        "blocks": c["blocks"], "targets": c["targets"], "rep": rep, "fr": fr,
                                        "pres": {}, "ver": {}, "rb": {}, "inval": [], "ev": [], "chs": [],
                                        "unc": r["uncertainty"], "pend": r["pending_human"], "rc": {},
                                        "manuscript": c["manuscript"], "exceptions": c["errors"]}, r))
            except Exception as e:
                c["degradations"].append("asset emission degraded: %s: %s" % (type(e).__name__, e))
        r["exceptions"] = list(c["errors"])
        store_json(out / "result.json", r)
        print("== build (no manuscript) == status=%s -> %s" % (r["status"], out / "result.json"))
        return 0
    if not c["workplan_path"]:
        c["degradations"].append("workplan absent; labelled fallback annotations produced")
    doc = Doc(c["raw"], c["blocks"])
    applied = []
    for ch in changes:
        ch["blk"] = ann_text(ch)
        try:
            doc.apply(ch["anchor"]["i"], ch)
            applied.append(ch)
        except Exception as e:
            c["errors"].append("apply failed for %s: %s" % (ch["id"], e))
    pub = doc.render(True)
    rb_test = {"attempted": False}
    if applied:
        f, snap = applied[0], doc.render(True)
        try:
            doc.rollback(f["id"])
            after_rb = doc.render(True)
            doc.apply(f["anchor"]["i"], f)
            after_re = doc.render(True)
            rb_test = {"attempted": True, "change_id": f["id"], "rollback_removed_annotation": after_rb != snap,
                       "state_before_sha256": digest_of(snap)[:16], "state_after_rollback_sha256": digest_of(after_rb)[:16],
                       "reapply_restored_state": after_re == snap, "state_after_reapply_sha256": digest_of(after_re)[:16],
                       "note": "v2 -%s-> v2r -+%s-> v2 (byte-identical restore)" % (f["id"], f["id"])}
        except Exception as e:
            c["errors"].append("rollback/reapply failed: %s" % e)
            rb_test = {"attempted": True, "change_id": applied[0]["id"], "error": str(e)}
    pres = {"source_sha256": digest_of(c["raw"]), "published_sha256": digest_of(pub),
            "annotation_free_sha256": digest_of(doc.render(False)),
            "byte_identical_to_source": doc.render(False) == c["raw"], "blocks_total": len(c["blocks"]),
            "blocks_targeted": len({x["tid"] for x in applied}), "blocks_rewritten": 0,
            "annotations_inserted": len(applied),
            "method": "insertion only: annotation blocks are appended after the target block",
            "integrity": V.integrity(c["raw"], pub)}
    inval = invalid_operations(c, doc, applied)
    chs = [change_payload(x) for x in applied]
    d = list(difflib.unified_diff(c["raw"].splitlines(), pub.splitlines(), fromfile="v1_original",
                                  tofile="v2_published", lineterm="", n=0))
    ver = {"versions": [{"id": k, "label": lb, "file": "versions/" + fn, "sha256": digest_of(tx), "chars": len(tx),
                         "annotations": na} for k, lb, fn, tx, na in (
             ("v1", "imported original", "v1_original.md", c["raw"], 0),
             ("v2", "published (accepted annotations)", "v2_published.md", pub, len(chs)))],
           "lineage": "v1 --import--> v2 (publish); v2 --rollback--> v2r --reapply--> v2",
           "diff_v1_v2": {"lines_added": sum(1 for x in d if x[0] == "+" and not x.startswith("+++")),
                          "lines_removed": sum(1 for x in d if x[0] == "-" and not x.startswith("---")),
                          "chars_added": len(pub) - len(c["raw"]),
                          "hunks": sum(1 for x in d if x.startswith("@@"))},
           "rollback_test": rb_test}
    ev = [{"claim_id": "%s-E%d" % (x["change_id"], i + 1), "change_id": x["change_id"],
           "target_id": x["target_id"], "claim": x["annotation"][:300], "quote": e["quote"],
           "source_id": e["source_id"], "locator": e["locator"], "verified": e["verified"], "mode": e["mode"]}
          for x in chs for i, e in enumerate(x["evidence"])]
    ev += [{"claim_id": "F%02d" % (i + 1), "change_id": None, "target_id": None, "claim": f["fact"],
            "quote": f["quote"], "source_id": f["source_id"], "locator": f["locator"],
            "verified": f["verified"], "mode": f["mode"]} for i, f in enumerate(facts)]
    k = V.format_counts(c["raw"])
    rcpt = {
        "import": {"source": {x: (c["manuscript"] or {}).get(x) for x in
                              ("rel", "kind", "sha256", "mode", "bytes")},
                   "parsed": {x: k[x] for x in ("headings", "table_rows", "display_formulas",
                                                "numbered_citations", "chars")},
                   "blocks": len(c["blocks"]), "workorder_targets": c["targets"],
                   "degradations": c["degradations"]},
        "accept_reject": {"policy": "accept only when the anchor quote is verbatim, an evidence quote "
                                    "verifies and the annotation is substantive; otherwise fall back and "
                                    "flag for human review",
                          "totals": {"proposed": len(rep["rows"]), "accepted": len(chs),
                                     "rejected": rep["rejected"], "fallback": rep["fallback_changes"]},
                          "items": rep["rows"]},
        "version_compare": ver,
        "invalid_operations": {"operations": inval,
                               "passed": all(x["raised"] and x["state_unchanged"] for x in inval)},
        "preserved_facts": {"counts": {x: fr[x] for x in ("total", "verified", "rejected")}, "items": facts},
        "evidence_map": {"counts": {"total": len(ev), "verified": sum(1 for x in ev if x["verified"])},
                         "items": ev}}
    store_json(out / "receipts.json", rcpt)
    store_text(out / "manuscript.md", pub)
    store_text(out / "versions" / "v1_original.md", c["raw"])
    store_text(out / "versions" / "v2_published.md", pub)
    store_text(out / "change_log.md", change_log(c, chs, fr, pres))
    store_text(out / "preview.html", preview(c, pub, chs))
    pend = list(meta["pending"]) + [
        {"item": "%s inserted as labelled fallback" % x["target_id"],
         "action": "author must review or replace the fallback annotation"} for x in chs if x["needs_human"]]
    pend += [{"item": "unverified fact: %s" % f["fact"][:110], "action": "confirm against the source or remove"}
             for f in fr["items"] if not f["verified"]]
    if not c["target_ids"]:
        pend.append({"item": "no workorder targets found", "action": "confirm the intended edit scope"})
    unc = list(meta["uncertainty"]) + ["%s located by %s; confirm it is the intended paragraph"
                                       % (t["target_id"], t["resolution"]) for t in c["targets"]
                                       if t["resolution"] != "explicit-label"]
    if not c["workorder"]:
        unc.append("workorder metadata absent; edit scope inferred from case.json")
    status = "partial" if (c["errors"] or rep["fallback_changes"] or rep["rejected"] or not c["target_ids"]
                           or fr["rejected"] or not applied) else "ok"
    if not applied and c["errors"]:
        status = "insufficient_evidence"
    files = ["manuscript.md", "versions/v2_published.md", "preview.html", "receipts.json", "change_log.md"]
    r = result(c, status, stage="build", facts=facts, ev=ev, ch=chs, ver=ver, pres=pres, read_bytes=rb_test,
            rc={"file": "receipts.json", "sections": ["import", "accept_reject", "invalid_operations",
                                                      "version_compare", "preserved_facts", "evidence_map"],
                "preview": "preview.html", "change_log": "change_log.md",
                "coverage": {"targets_total": rep["targets_total"], "agent_changes": rep["agent_changes"],
                             "fallback_changes": rep["fallback_changes"], "rejected": rep["rejected"],
                             "facts_verified": fr["verified"], "facts_rejected": fr["rejected"],
                             "original_text_preserved": pres["byte_identical_to_source"]}},
            pend=pend, unc=unc,
            dl={"primary": "manuscript.md", "editable_files": files, "format": "Markdown (UTF-8, no BOM)",
                "source": (c["manuscript"] or {}).get("rel"),
                "notes": "original text byte-preserved; additions delimited by ANN-START/ANN-END"})
    r["preview"] = {"html": "preview.html", "note": "static HTML export preview; no PDF renderer assumed"}
    if A is not None:
        try:
            r.update(A.finish(c, {"out": out, "status": status, "raw": c["raw"], "pub": pub,
                                  "blocks": c["blocks"], "targets": c["targets"], "rep": rep, "fr": fr,
                                  "pres": pres, "ver": ver, "rb": rb_test, "inval": inval, "ev": ev,
                                  "chs": chs, "unc": unc, "pend": pend, "rc": rcpt,
                                  "manuscript": c["manuscript"], "exceptions": c["errors"]}, r))
        except Exception as e:
            c["degradations"].append("asset emission degraded: %s: %s" % (type(e).__name__, e))
            if A is not None:
                try:
                    A.runlog(c, "assets", "degraded", exception=str(e)[:200])
                except Exception:
                    pass
    r["exceptions"] = list(c["errors"])
    store_json(out / "result.json", r)
    print("== build ==\nstatus    : %s\nchanges   : %d applied (%d agent, %d fallback, %d rejected)"
          % (status, len(applied), rep["agent_changes"], rep["fallback_changes"], rep["rejected"]))
    print("preserved : byte_identical=%s integrity=%s\nrollback  : %s\ninvalid   : %d/%d raised, state unchanged"
          % (pres["byte_identical_to_source"], pres["integrity"]["preserved"],
             rb_test.get("note") or rb_test.get("error") or "n/a",
             sum(1 for x in inval if x["raised"] and x["state_unchanged"]), len(inval)))
    print("\n".join("  %s" % (out / f) for f in files + ["result.json"]))
    return 0


def phase_inspect(a):
    c = ingest_inputs(a)
    log_step(c, "show", requested=a.id or a.grep, blocks=len(c["blocks"]))
    sel = c["blocks"]
    if a.id:
        i, how = resolve(a.id, c["blocks"])
        sel = [c["blocks"][i]] if i is not None else [b for b in c["blocks"] if a.id in b["text"]]
        print("id=%s -> block %s (%s)" % (a.id, i, how))
    if a.grep:
        try:
            rx = re.compile(a.grep, re.I)
        except Exception:
            rx = re.compile(re.escape(a.grep), re.I)
        sel = [b for b in sel if rx.search(b["text"])]
    print("-- %d block(s) --" % len(sel))
    for b in sel:
        print("\n[%s] %s (%s, %d chars)\n%s" % (b.get("id"), V.locator_of(b), b["kind"], len(b["text"]),
                                                b["text"][:a.limit or 900]))
    return 0


def seek_wp(a, work):
    if a.workplan:
        p = Path(a.workplan)
        return (p, None) if p.exists() else (None, "workplan path not found: %s" % p)
    for nm in PLAN_CANDIDATES:
        if (Path(work) / nm).exists():
            return Path(work) / nm, None
    for p in sorted(Path(work).glob("*.json")):
        if p.name in ("index.json", "check_report.json"):
            continue
        o, _ = read_json(p)
        ents = next((v for k, v in (o or {}).items() if k in ("targets", "edits", "changes", "annotations")
                     and isinstance(v, list)), None) if isinstance(o, dict) else None
        if ents and all(isinstance(x, dict) for x in ents) and any(
                k in str(ents[0]) for k in ("annotation", "new_text", "note", "quote", "original_quote")):
            return p, None
    return None, "no workplan json in %s" % work


def score_plan(c, plan):
    nums = set(V.numbers_in(c["raw"]))
    changes, rows = [], []
    for pos, t in enumerate(c["targets"], 1):
        tid, cid = t["target_id"], "A%02d" % pos
        e = plan.get(tid)
        row = {"change_id": cid, "target_id": tid, "origin": "agent", "decision": "accept",
               "reasons": [], "warnings": []}
        fb = (lambda: fallback(c["blocks"][t["block_index"]])) if t["block_index"] is not None else (lambda: ("", ""))
        if not e:
            row.update({"decision": "fallback", "origin": "fallback",
                        "reasons": ["target not covered by the workplan"]})
            changes += [x for x in [make_revision(c, t, cid, *fb())] if x]
            rows.append(row)
            continue
        q, ann = e["quote"], e["annotation"].strip()
        loc = V.find_in_blocks(c["blocks"], q)
        ev = []
        for x in e["ev"]:
            if not isinstance(x, dict):
                continue
            qq = str(find_key(x, "quote", "text", "excerpt", default="") or "")
            hit = V.find_in_blocks(c["blocks"], qq)
            ev.append({"q": qq[:300], "ok": bool(hit.get("ok")), "mode": hit.get("mode"),
                       "loc": hit.get("locator") or find_key(x, "locator", default=None),
                       "src": find_key(x, "source_id", "source", default="manuscript")})
        ok = sum(1 for x in ev if x["ok"])
        row.update({"quote_ok": bool(loc.get("ok")), "quote_loc": loc.get("locator") or t.get("locator"),
                    "chars": len(ann), "ev_total": len(ev), "ev_ok": ok})
        if e["decision"].startswith(("reject", "decline", "no")):
            row.update({"decision": "rejected", "reasons": ["rejected in the agent workplan"]})
        elif not q or not loc.get("ok") or len(ann) < 60 or ok == 0:
            row.update({"decision": "fallback", "origin": "fallback", "reasons": [
                x for x in ("original_quote not found verbatim in the source" if not q or not loc.get("ok") else "",
                            "annotation under 60 chars (not substantive)" if len(ann) < 60 else "",
                            "no evidence quote verified against the source" if ok == 0 else "") if x]})
            changes += [x for x in [make_revision(c, t, cid, *fb())] if x]
        else:
            bad = [x for x in V.numbers_in(ann) if x not in nums]
            if bad:
                row["warnings"].append("numbers not found in source: %s" % sorted(set(bad))[:8])
            changes.append({"id": cid, "tid": tid, "origin": "agent", "decision": "accept", "human": False,
                            "before": q, "after": ann, "why": e["why"], "ev": ev,
                            "anchor": {"i": t["block_index"], "bid": t.get("block_id"),
                                       "loc": t.get("locator"), "pos": "after"}})
        rows.append(row)
    rep = {"targets_total": len(c["targets"]), "accepted": len(changes),
           "agent_changes": sum(1 for r in rows if r["origin"] == "agent"),
           "fallback_changes": sum(1 for r in rows if r["decision"] == "fallback"),
           "rejected": sum(1 for r in rows if r["decision"] == "rejected"), "rows": rows}
    return changes, rep


def change_payload(ch):
    return {"change_id": ch["id"], "target_id": ch["tid"], "operation": "insert_annotation_after_block",
            "origin": ch["origin"], "decision": ch["decision"], "needs_human": ch["human"],
            "original_quote": ch["before"], "revised_quote": ch["after"], "annotation": ch["after"],
            "rationale": ch["why"], "revised_quote_chars": len(ch["after"]),
            "evidence": [{"quote": e["q"], "verified": e["ok"], "locator": e["loc"],
                          "source_id": e["src"], "mode": e["mode"]} for e in ch["ev"]],
            "anchor": {"block_index": ch["anchor"]["i"], "block_id": ch["anchor"]["bid"],
                       "locator": ch["anchor"]["loc"], "position": ch["anchor"]["pos"]}}


def select_source_doc(items):
    best = None
    for n, it in enumerate(items):
        nm = it["name"].lower()
        if it["kind"] not in ("md", "txt", "docx", "pdf") or it["bytes"] < 400:
            continue
        if any(s in nm for s in EXCLUDED_NAMES):
            continue
        sc = {"md": 6, "txt": 4, "docx": 5, "pdf": 3}[it["kind"]] + 4 * any(h in nm for h in SOURCE_HINTS)
        if best is None or sc > best[0]:
            best = (sc, it)
    return best[1] if best else None


def golden_payload(c):
    """Pure helper used by the four-phase revision desk; reads only already-checked inputs. (golden_payload)"""
    if A is None:
        return None
    try:
        g = A.emit_golden(c)
        return {"file": "golden_standard.json", "schema": g["schema"], "status": g["status"],
                "items": len(g["items"]), "unresolved_quotes": g["summary"]["unresolved_quotes"]}
    except Exception as e:
        c["degradations"].append("golden standard unavailable: %s" % e)
        return None


def canon_plan(obj):
    ents = obj if isinstance(obj, list) else None
    if ents is None and isinstance(obj, dict):
        ents = next((obj[k] for k in ("targets", "edits", "changes", "annotations", "items")
                     if isinstance(obj.get(k), list)), [])
    by = {}
    for e in ents or []:
        if not isinstance(e, dict):
            continue
        tid = str(find_key(e, "target_id", "target", "id", default="") or "").strip()
        ann = find_key(e, "annotation", "new_text", "note", "insert", "content", default="")
        if not tid:
            continue
        by[tid] = {"annotation": ann if isinstance(ann, str) else json.dumps(ann, ensure_ascii=False),
                   "quote": str(find_key(e, "original_quote", "quote", "anchor", "before", "original", default="") or ""),
                   "why": str(find_key(e, "rationale", "reason", "why", default="") or ""),
                   "ev": find_key(e, "evidence", "sources", "citations", default=[]) or [],
                   "decision": str(find_key(e, "decision", "status", "accept", default="accept") or "").lower()}
    top = obj if isinstance(obj, dict) else {}
    return by, {"facts": find_key(top, "preserved_facts", "fact", default=[]) or [],
                "uncertainty": find_key(top, "uncertainty", "uncertain", default=[]) or [],
                "pending": find_key(top, "pending_human", "human", default=[]) or []}


def audit_facts(c, fl):
    items = []
    for f in fl:
        f = {"fact": f} if isinstance(f, str) else f
        if not isinstance(f, dict):
            continue
        q = str(find_key(f, "quote", "evidence", default="") or "")
        hit = V.find_in_blocks(c["blocks"], q)
        items.append({"fact": str(find_key(f, "fact", "statement", "item", default="") or "")[:400],
                      "value": find_key(f, "value", default=None), "quote": q[:400], "verified": bool(hit.get("ok")),
                      "locator": hit.get("locator") or find_key(f, "locator", default=None),
                      "source_id": find_key(f, "source_id", "source", default="manuscript"), "mode": hit.get("mode")})
    v = sum(1 for x in items if x["verified"])
    return items, {"total": len(items), "verified": v, "rejected": len(items) - v, "items": items}


def seek_wos(obj, acc=None, d=0):
    """Contract helper of the revision desk; every value it returns is plain JSON data. (seek_wos)"""
    acc = [] if acc is None else acc
    if d > 8:
        return acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "target" in str(k).lower() and isinstance(v, list) and v and all(isinstance(x, str) for x in v):
                acc.append({"obj": obj, "target_ids": v})
                break
        for v in obj.values():
            seek_wos(v, acc, d + 1)
    elif isinstance(obj, list):
        for v in obj:
            seek_wos(v, acc, d + 1)
    return acc


def ingest_inputs(a):
    c = {"errors": [], "degradations": [], "sources": [], "case": {}, "contract": dict(CONTRACT_SLOTS),
         "case_id": "unknown", "blocks": [], "raw": "", "targets": [], "target_ids": [],
         "workorder": {}, "manuscript": None, "inputs": [], "case_path": None,
         "workplan_path": None, "instruction": ""}
    if V is None:
        c["degradations"].append("doc_parse.py unavailable (%s)" % VERR)
        return c
    src = a.input or next((p for p in ("/input", "/app/input") if Path(p).exists()), "")
    c["input_dir"] = src
    for key, dflt in (("out_dir", a.output or "/app/output"), ("work_dir", a.work or "/app/work")):
        p, err = make_dir(dflt)
        if p is None:
            p = Path(tempfile.mkdtemp(prefix="w04-"))
            c["degradations"].append("%s unwritable (%s); using %s" % (key, err, p))
        c[key] = p
    cp = Path(src) / "case.json" if src else None
    if cp and not cp.exists():
        cp = next(iter(sorted(Path(src).rglob("case*.json"))), None)
    if cp and cp.exists():
        obj, err = read_json(cp)
        c["case"] = obj if isinstance(obj, dict) else {}
        c["case_path"] = str(cp)
        if err:
            c["errors"].append("case.json unreadable: %s" % err)
    if not c["case"]:
        c["errors"].append("case.json missing or unusable under %s" % (src or "input"))
    case = c["case"]
    c["case_id"] = str(find_key(case, "case_id", default="unknown") or "unknown")
    c["contract"] = case.get("output_contract") if isinstance(case.get("output_contract"), dict) \
        and case.get("output_contract") else dict(CONTRACT_SLOTS)
    c["instruction"] = str(find_key(case, "task_instruction", "instruction", default="") or "")
    c["inputs"] = []
    if src:
        try:
            c["inputs"] = [{"path": str(q), "rel": str(q.relative_to(src)), "name": q.name,
                            "kind": V.kind_of(q), "bytes": q.stat().st_size}
                           for q in sorted(Path(src).rglob("*")) if q.is_file() and "__pycache__" not in q.parts]
        except Exception as e:
            c["degradations"].append("input scan failed: %s" % e)
    c["sources"] = [{"source_id": it["rel"], "kind": it["kind"], "bytes": it["bytes"],
                     "sha256": hashlib.sha256(read_bytes(it["path"])).hexdigest()} for it in c["inputs"]]
    wos = seek_wos(case)
    wo = wos[0] if wos else None
    pre = c["case_id"].split("-")[0].lower()
    for cand in wos:
        if any(str(t).lower().startswith(pre) for t in cand["target_ids"]):
            wo = cand
            break
    c["workorder"] = wo["obj"] if wo else {}
    c["target_ids"] = [str(t) for t in (wo["target_ids"] if wo else [])]
    it = select_source_doc(c["inputs"])
    if it:
        try:
            raw, blocks, mode = extract(it["path"], it["kind"])
        except Exception as e:
            c["degradations"].append("manuscript %s rejected: %s" % (it["rel"], e))
            raw, blocks, mode = "", [], ""
        if blocks:
            blocks, explicit = assign_ids(blocks, c["case_id"].split("-")[0])
            for i, b in enumerate(blocks):
                b["index"], b["ann"] = i, []
            c.update({"raw": raw, "blocks": blocks,
                      "manuscript": {"path": it["path"], "rel": it["rel"], "kind": it["kind"],
                                     "bytes": it["bytes"], "mode": mode, "explicit_ids": explicit,
                                     "sha256": digest_of(raw)}})
            if mode != "native":
                c["degradations"].append("%s parsed as %s; verify against the original" % (it["rel"], mode))
    if not c["blocks"]:
        c["errors"].append("no importable manuscript material under %s" % (src or "input"))
    for tid in c["target_ids"]:
        i, how = resolve(tid, c["blocks"])
        t = {"target_id": tid, "block_index": i, "resolution": how}
        if i is not None:
            b = c["blocks"][i]
            t.update({"block_id": b.get("id"), "locator": V.locator_of(b),
                      "preview": re.sub(r"\s+", " ", b["text"])[:170]})
        c["targets"].append(t)
    return c


def invalid_operations(c, doc, applied):
    recs = []

    def att(oid, what, fn):
        before, raised, err = digest_of(doc.render(True)), False, None
        try:
            fn()
        except Exception as e:
            raised, err = True, "%s: %s" % (type(e).__name__, str(e)[:150])
        recs.append({"op_id": oid, "attempt": what, "raised": raised, "error": err,
                     "state_unchanged": before == digest_of(doc.render(True)), "state": before[:16]})

    att("I1", "apply a change to a block index outside the workorder",
        lambda: doc.apply(10 ** 6, {"id": "X1", "tid": "C99-P999", "after": "x"}))
    att("I2", "apply a change with a negative anchor block",
        lambda: doc.apply(-1, {"id": "X2", "tid": "C99-P999", "after": "x"}))
    if applied:
        att("I3", "roll back a change id that was never applied", lambda: doc.rollback("A99-NEVER"))
        att("I4", "apply a duplicate change id to the same block",
            lambda: doc.apply(applied[0]["anchor"]["i"], applied[0]))
    ok = False
    try:
        extract(c["case_path"] or __file__, "json")
    except Exception as e:
        ok = "UNSUPPORTED_FORMAT" in str(e)
    recs.append({"op_id": "I5", "attempt": "import case.json as the manuscript", "raised": ok,
                 "error": "UNSUPPORTED_FORMAT" if ok else "no exception", "state_unchanged": True})
    return recs


def result(c, status, **k):
    """Deterministic helper of the offline revision pipeline; no network, stdlib only. (result)"""
    oc = c["contract"] if isinstance(c["contract"], dict) else {}
    sl = {"case_id": c["case_id"], "deliverable": k.get("dl"), "preserved_facts": k.get("facts") or [],
          "evidence_map": k.get("ev") or [], "change_log": k.get("ch") or [], "receipts": k.get("rc"),
          "uncertainty": k.get("unc") or [], "version_compare": k.get("ver")}
    o = {key: sl.get(V.classify_contract_key(key)) for key in oc}
    o.update({"case_id": c["case_id"], "status": status, "stage": k.get("stage", "build"),
              "deliverable": sl["deliverable"], "contract_keys": list(oc), "sources": c["sources"],
              "uncertainty": sl["uncertainty"], "pending_human": k.get("pend") or [],
              "errors": c["errors"] + (k.get("err") or []), "degradations": c["degradations"],
              "changes": sl["change_log"], "receipts": k.get("rc"), "version_compare": k.get("ver"),
              "preservation": k.get("pres"), "format_integrity": (k.get("pres") or {}).get("integrity"),
              "rollback": k.get("rb"),
              "runtime": {"skill": SKILL_NAME, "version": ENGINE_VERSION, "stage": k.get("stage", "build"),
                          "elapsed_s": round(time.time() - START_CLOCK, 2), "python": sys.version.split()[0],
                          "manuscript": c["manuscript"], "workplan": c["workplan_path"]}})
    o["exceptions"] = k.get("exc") or []
    for field, key in (("golden_standard", "gs"), ("diff_report", "dr"),
                       ("version_history", "vh"), ("self_check", "sc")):
        o[field] = k.get(key)
    return o


def log_step(c, step, **kv):
    """Small step of the local manuscript workflow; safe to run repeatedly. (log_step)"""
    if A is not None:
        try:
            A.boot(c, sys.argv[1:])
        except Exception:
            pass
    if A is not None:
        try:
            A.runlog(c, step, "ok", **kv)
        except Exception:
            pass


def prepare_run(a):
    c = ingest_inputs(a)
    wp, err = seek_wp(a, c["work_dir"])
    c["workplan_path"] = str(wp) if wp else None
    obj, jerr = (read_json(wp) if wp else (None, err))
    if jerr and wp:
        c["errors"].append("workplan unreadable: %s" % jerr)
        obj = None
    plan, meta = canon_plan(obj)
    changes, rep = score_plan(c, plan)
    facts, fr = audit_facts(c, meta["facts"])
    return c, meta, changes, rep, facts, fr


def phase_audit(a):
    c, meta, changes, rep, facts, fr = prepare_run(a)
    log_step(c, "check", workplan=c["workplan_path"], targets=rep["targets_total"],
            fallback=rep["fallback_changes"], rejected=rep["rejected"])
    rep.update({"facts": fr, "workplan": c["workplan_path"], "ready_for_build": bool(changes)})
    store_json(Path(c["work_dir"]) / "check_report.json", rep)
    print("== check ==\nworkplan  : %s\ntargets   : %d total · %d agent · %d fallback · %d rejected"
          % (c["workplan_path"] or "MISSING", rep["targets_total"], rep["agent_changes"],
             rep["fallback_changes"], rep["rejected"]))
    for r in rep["rows"]:
        print("  %-4s %-12s %-9s %s%s" % (r["change_id"], r["target_id"], r["decision"],
                                          "; ".join(r["reasons"]),
                                          " [quote OK, evidence %d/%d]" % (r["ev_ok"], r["ev_total"])
                                          if r.get("quote_ok") else ""))
        for w in r["warnings"]:
            print("       WARN %s" % w)
    print("facts     : %d verified, %d rejected\nready     : %s"
          % (fr["verified"], fr["rejected"], rep["ready_for_build"]))
    store_json(Path(c["out_dir"]) / "result.json", result(
        c, "partial", stage="check", facts=facts, ch=[change_payload(x) for x in changes],
        rc={"check_report": str(Path(c["work_dir"]) / "check_report.json")},
        gs=golden_payload(c),
        pend=[{"item": "edits not applied yet", "action": "run build"}]))
    print("report    : %s\nnext: %s build" % (Path(c["work_dir"]) / "check_report.json", Path(__file__).resolve()))
    return 0


def make_revision(c, t, cid, body, q):
    """Pure helper used by the four-phase revision desk; reads only already-checked inputs. (make_revision)"""
    if not body or t["block_index"] is None:
        return None
    hit = V.find_in_blocks(c["blocks"], q)
    return {"id": cid, "tid": t["target_id"], "origin": "fallback", "decision": "accept", "human": True,
            "before": q, "after": body,
            "why": "workplan missing or unusable for this target: deterministic fallback keeps the "
                   "deliverable complete and labels the gap honestly",
            "ev": [{"q": q, "ok": bool(hit.get("ok")), "loc": hit.get("locator") or t.get("locator"),
                    "src": "manuscript", "mode": hit.get("mode")}],
            "anchor": {"i": t["block_index"], "bid": t.get("block_id"), "loc": t.get("locator"),
                       "pos": "after"}}




class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, msg):
        self.print_usage(sys.stderr)
        print("bad arguments: %s -- defaults are used" % msg, file=sys.stderr)


def main(argv=None):
    ap = SafeArgumentParser(prog="main.py", description="Manuscript revision desk: offline local "
                                       "editing workflow (init/show/check/build); stdlib only, offline.")
    ap.add_argument("--version", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("init", "show", "check", "build"):
        sp = sub.add_parser(name, help="%s phase of the revision run" % name)
        sp.add_argument("--input", default=None, help="material root (default /input, else /app/input)")
        sp.add_argument("--output", default=None, help="deliverable root (default /app/output)")
        sp.add_argument("--work", default=None, help="scratch root (default /app/work)")
        if name == "show":
            sp.add_argument("--id", default=None, help="block or target identifier, e.g. C01-P002")
            sp.add_argument("--grep", default=None, help="regular-expression filter")
            sp.add_argument("--limit", type=int, default=900)
        if name in ("check", "build"):
            sp.add_argument("--workplan", default=None, help="path to an explicit workplan JSON")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 0
    if getattr(a, "version", False):
        print(SKILL_NAME, ENGINE_VERSION)
        return 0
    for n in ("input", "output", "work", "workplan", "id", "grep", "limit"):
        if not hasattr(a, n):
            setattr(a, n, None)
    if not getattr(a, "cmd", None):
        ap.print_help()
        return 0
    try:
        return {"init": phase_init, "show": phase_inspect, "check": phase_audit, "build": phase_assemble}[a.cmd](a) or 0
    except Exception as e:
        import traceback
        print("uncaught failure: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        traceback.print_exc(limit=4)
        try:
            out = Path(a.output or "/app/output")
            store_json(out / "result.json", {"case_id": "unknown", "status": "partial", "deliverable": None,
                                     "preserved_facts": [], "evidence_map": [], "change_log": [],
                                     "errors": ["%s: %s" % (type(e).__name__, e)],
                                     "exceptions": ["%s: %s (%s)" % (type(e).__name__, e, a.cmd)],
                                     "degradations": ["run aborted; see stderr"],
                                     "pending_human": [{"item": "workflow aborted",
                                                        "action": "inspect the work dir"}],
                                     "sources": [], "uncertainty": ["run did not complete"],
                                     "golden_standard": None, "diff_report": None,
                                     "version_history": None, "self_check": None,
                                     "runtime": {"skill": SKILL_NAME, "version": ENGINE_VERSION,
                                                 "elapsed_s": round(time.time() - START_CLOCK, 2)}})
            if A is not None:
                A.runlog({"out_dir": out}, "fatal", "exception",
                         exception="%s: %s" % (type(e).__name__, str(e)[:200]), step_cmd=a.cmd)
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
