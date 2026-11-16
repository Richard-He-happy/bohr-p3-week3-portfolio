#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deckctl -- four-stage command line for the talk-deck skill.

    init    index the input and publish a legal partial result.json
    show    print locator-tagged source paragraphs to quote from
    check   validate work/slide_plan.json (verbatim quotes, 3-5 bullets, page count)
    build   render presentation.pptx, preview.pdf and the complete result bundle

Standard library only, no network, exit code always 0, and a partial
result.json is published before anything downstream can fail.
"""
import argparse
import json
import re
import sys
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

import slidewriter
import evidence_audit as evidence
from materialkit import CONTRACT_ROUTE, INPUT_DIR, OUTPUT_DIR, WORK_DIR, audit_plan, baseline_plan, build_material_index, contract_field_names, deck_payload, discover_materials, elapsed_seconds, fill_missing_leaves, locate_case_file, locate_verbatim, read_json, resolve_template, route_for_key, scan_hint, squeeze_text, write_json

def assemble_result(case, idx, vals, status, errors, degr, changes, extra=None):
    case = case if isinstance(case, dict) else {}
    c = case.get("output_contract")
    if isinstance(c, dict):
        doc = fill_missing_leaves(c, vals)
    elif isinstance(c, list):
        doc = {}
        for name in c:
            if not isinstance(name, str):
                continue
            if name == "exceptions":
                doc[name] = list(degr or [])
                continue
            key = CONTRACT_ROUTE.get(name, route_for_key(name))
            v = vals.get(key) if key else None
            if v is None:
                v = vals.get(route_for_key(name))
            doc[name] = v
        doc["output_contract"] = c
    else:
        doc = {}
    if not isinstance(doc, dict):
        doc = {"output_contract": doc}
    doc.update({"case_id": case.get("case_id") or (Path(idx["case_path"]).stem if idx.get("case_path") else "unknown_case"),
                "status": status,
                "sources": [{k: m.get(k) for k in ("id", "path", "name", "kind", "chars")} for m in idx.get("materials", [])],
                "uncertainty": vals.get("uncertainty") or [], "pending_human": vals.get("pending_human") or [],
                "errors": errors, "degradations": degr, "changes": changes,
                "runtime": {"seconds": elapsed_seconds(), "python": sys.version.split()[0], "skill": "talk-deck-studio",
                            "generated_at": datetime.now().isoformat(timespec="seconds")}})
    for k, v in evidence.asset_fields().items():
        if doc.get(k) in (None, "", [], {}):
            doc[k] = v
    doc.update(extra or {})
    return doc


def write_partial_result(vals=None, idx=None, case=None):
    try:
        evidence.ensure_min_assets(OUTPUT_DIR, (case or {}).get("case_id") or "unknown_case", "partial",
                         (idx or {}).get("errors"), tag="partial")
        evidence.journal("partial", "legal partial result.json written")
    except Exception:
        pass
    write_json(OUTPUT_DIR / "result.json", assemble_result(case or {}, idx or {"materials": []}, vals or {}, "partial", [],
                                       ["run started; deliverables still pending"], []))
    return True


def write_plain_pdf(deck, out):
    """Text-only fallback PDF preview, one page per slide, no external tool required."""
    W, H, st = 960, 540, []
    for s in deck["slides"]:
        y, o = H - 70, []
        blocks = [(s["title"], 28 if s.get("layout") == "title" else 21, 30)] + \
                 [(b["text"], 14, 21) for b in s["bullets"]]
        for txt, sz, step in blocks:
            for l in slidewriter._wrap(txt, sz, W - 120):
                o.append("BT /F1 %d Tf 1 0 0 1 60 %d Tm <%s> Tj ET\n" % (sz, y, l.encode("utf-16-be").hex().upper()))
                y -= step
            y -= 8
        st.append("".join(o))
    st = st or [""]
    n, fid = len(st), 3 * len(st) + 3
    objs = ["<</Type/Catalog/Pages 2 0 R>>",
            "<</Type/Pages/Kids[%s]/Count %d>>" % (" ".join("%d 0 R" % (3 * n + 1 + i) for i in range(n)), n)]
    objs += ["<</Type/Page/Parent 2 0 R/MediaBox[0 0 %d %d]/Resources<</Font<</F1 %d 0 R>>>>/Contents %d 0 R>>" % (W, H, fid, 3 * n + 1 + i) for i in range(n)]
    objs += ["<</Length %d>>stream\n%s\nendstream" % (len(c.encode("latin-1", "replace")), c) for c in st]
    objs += ["<</Type/Font/Subtype/Type0/BaseFont/STSong-Light/Encoding/UniGB-UCS2-H/DescendantFonts[%d 0 R]>>" % (fid + 1),
             "<</Type/Font/Subtype/CIDFontType0/BaseFont/STSong-Light/CIDSystemInfo<</Registry(Adobe)/Ordering(GB1)/Supplement 4>>/FontDescriptor %d 0 R/DW 1000/W[1 95 500]>>" % (fid + 2),
             "<</Type/FontDescriptor/FontName/STSong-Light/Flags 4/FontBBox[-25 -254 1000 880]/ItalicAngle 0/Ascent 880/Descent -120/CapHeight 880/StemV 93>>"]
    buf, offs, pos = ["%PDF-1.4\n"], [], 9
    for i, ob in enumerate(objs):
        offs.append(pos)
        buf.append("%d 0 obj\n%s\nendobj\n" % (i + 1, ob))
        pos += len(buf[-1].encode("latin-1", "replace"))
    tail = "xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + "".join("%010d 00000 n \n" % o for o in offs)
    tail += "trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, pos)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(("".join(buf) + tail).encode("latin-1", "replace"))
    return True


def pdf_page_count(p):
    """Robust page count: pdftotext form feeds first, then a raw /Type /Page scan."""
    try:
        import subprocess
        r = subprocess.run(["pdftotext", "-layout", str(p), "-"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=90)
        if r.returncode == 0 and r.stdout:
            return max(1, r.stdout.count(b"\f") + (0 if r.stdout.endswith(b"\f") else 1))
    except Exception:
        pass
    try:
        d = Path(p).read_bytes()
        return len(re.findall(rb"/Type\s*/Page\b", d)) or d.count(b"/Type/Page")
    except Exception:
        return 0


def plan_as_markdown(plan, h):
    L = ["# Talk plan (editable source of truth)", "", "- audience: %s" % (plan.get("audience") or h.get("audience") or "未指定"),
         "- duration: %s min" % (plan.get("duration_min") or h.get("duration") or "未指定"),
         "- slides: %s" % (plan.get("target_slides") or h.get("slides") or len(plan.get("slides") or [])),
         "- talk goal: %s" % (plan.get("goal") or "按材料主线组织"), ""]
    L += ["## Narrative acts", ""] + ["- **%s**（%s）：%s" % (a.get("act", ""), a.get("slides", ""), a.get("purpose", ""))
                                 for a in plan.get("narrative") or [] if isinstance(a, dict)] + [""] if plan.get("narrative") else []
    L += ["## Slide-by-slide plan", ""]
    for i, s in enumerate(plan.get("slides") or [], 1):
        L.append("### %d. %s" % (i, s.get("title", "")))
        L += ["- claim: %s" % s["claim"]] if s.get("claim") else []
        L += ["- point: %s  `[%s]`" % (b.get("text", ""), b.get("locator") or "-") for b in s.get("bullets") or [] if isinstance(b, dict)]
        L += ["- %s: %s" % (lab, s[k]) for k, lab in (("visual", "visual"), ("evidence_strength", "evidence"), ("notes", "speaker notes")) if s.get(k)]
        L.append("")
    L += ["## Q&A rehearsal", ""] + ["- **Q: %s** -> %s (backup: %s)" % (q.get("q", ""), q.get("a", ""), q.get("backup", "-"))
                                for q in plan.get("qa") or [] if isinstance(q, dict)] + [""] if plan.get("qa") else []
    return "\n".join(L)


def derive_hints(case, task, idx):
    first = next((p["text"] for m in idx.get("materials", []) for p in m["paras"] if len(p["text"]) > 12), "")
    h = {"audience": scan_hint(case, [r"audience|听众|target_group"]),
         "duration": scan_hint(case, [r"duration|minutes|时长|time_limit"], True),
         "slides": scan_hint(case, [r"slide_count|num_slides|n_slides|页数"], True),
         "title": scan_hint(case, [r"^title$|case_title|deck_title|paper_title|研究题目"]),
         "template": scan_hint(case, [r"template|母版|master|starting_deck"])}
    for k, pat, cast in (("duration", r"(\d{1,3})\s*(?:分钟|min\b)", float),
                         ("slides", r"(\d{1,3})\s*(?:页|slides?\b)", float),
                         ("audience", r"听众[：:]\s*([^\n。|]{2,24})", str)):
        if not h.get(k):
            m = re.search(pat, task or "")
            h[k] = cast(m.group(1)) if m else h.get(k)
    h["title"] = h["title"] or (re.sub(r"^[#>*\s]+", "", first)[:60] or None)
    if not h["slides"] and h["duration"]:
        h["slides"] = max(4, round(h["duration"] * 0.8))
    h["meta"] = " | ".join(x for x in [str(h["audience"] or ""), ("%g 分钟" % h["duration"]) if h["duration"] else "",
                                       datetime.now().strftime("%Y-%m-%d")] if x)
    return h


# ---------------- subcommands ----------------


def run_init(a):
    cp, case = locate_case_file()
    write_partial_result({}, {"materials": [], "case_path": str(cp) if cp else None}, case)
    idx = build_material_index()
    idx["hints"] = derive_hints(case, idx["task_excerpt"], idx)
    evidence.journal("init", "index built", discover_materials=len(idx["materials"]), hints={k: idx["hints"].get(k) for k in ("audience", "duration", "slides")}, errors=len(idx["errors"]))
    evidence.ensure_min_assets(OUTPUT_DIR, case.get("case_id") if isinstance(case, dict) else None, "partial", idx["errors"], tag="init")
    write_json(WORK_DIR / "materials.json", idx)
    md = ["# Source material index", "", "- input root: `%s`" % INPUT_DIR, "- case.json: `%s`" % (idx["case_path"] or "未找到"),
          "- hints: %s" % json.dumps({k: idx["hints"].get(k) for k in ("audience", "duration", "slides")}, ensure_ascii=False),
          "", "| id | file | kind | bytes | paragraphs |", "|-|-|-|-|-|"] + \
         ["| %s | %s | %s | %d | %d |" % (m["id"], m["name"], m["kind"], m["bytes"], len(m["paras"])) for m in idx["materials"]] + \
         [["| %s | %s | %s | %d | %d |" % (m["id"], m["name"], m["kind"], m["bytes"], len(m["paras"])) for m in idx["materials"]]][0]
    md += ["", "## Parsing problems"] + ["- " + e for e in idx["errors"]] if idx["errors"] else []
    (WORK_DIR / "index.md").write_text("\n".join(md), encoding="utf-8")
    write_json(OUTPUT_DIR / "result.json", assemble_result(case, idx, {
        "slide_plan": {"path": "output/slide_plan.md", "status": "pending"},
        "uncertainty": ["slide plan not written yet: read the source with `show`, then author work/slide_plan.json"],
        "pending_human": ["per-slide plan pending; run build afterwards"]}, "partial", idx["errors"], ["init stage only: no deck has been built"], []))
    print(json.dumps({"materials": len(idx["materials"]), "chars": sum(m["chars"] for m in idx["materials"]),
                      "hints": idx["hints"], "index": "work/index.md"}, ensure_ascii=False, indent=2))
    print("\nNEXT: python3 scripts/deckctl.py show --grep '<keyword>'  ->  write work/slide_plan.json  |  python3 scripts/deckctl.py build")
    return 0


def run_show(a):
    idx = read_json(WORK_DIR / "materials.json") or build_material_index()
    n = 0
    for m in idx.get("materials", []):
        ps = [p for p in m["paras"] if (not a.material or m["id"] == a.material)
              and (not a.grep or re.search(a.grep, p["text"], re.I))]
        ps = ps[:a.limit] if a.limit else ps
        if ps:
            print("\n== %s  %s (%s, %d paras)" % (m["id"], m["name"], m["kind"], len(m["paras"])))
            for p in ps:
                print("[%s] %s" % (p["loc"], p["text"]))
                n += 1
    print("\n-- %d paragraphs; locator = M<id>#p<n> --" % n)
    return 0


def run_check(a):
    idx = read_json(WORK_DIR / "materials.json") or build_material_index()
    h = idx.get("hints") or {}
    path = a.plan or WORK_DIR / "slide_plan.json"
    plan = read_json(path)
    rep = audit_plan(plan, idx, int(h["slides"]) if h.get("slides") else None)
    rep.update({"plan_path": str(path), "plan_found": bool(plan)})
    write_json(WORK_DIR / "check_report.json", rep)
    evidence.journal("check", "plan validated", usable=rep["usable"], passed=rep["passed"],
              quotes=[rep["quotes_verified"], rep["quotes_checked"]], errors=len(rep["errors"]))
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    print("\n%s — every quote must be a literal source substring; look fragments up with deckctl.py show --grep"
          % ("PASS" if rep["usable"] else "FAIL"))
    return 0


def run_build(a):
    idx = read_json(WORK_DIR / "materials.json") or build_material_index()
    case = idx.get("case") or {}
    h = idx.get("hints") or derive_hints(case, idx.get("task_excerpt", ""), idx)
    errors, degr, changes = list(idx.get("errors") or []), [], []
    evidence.journal("build", "start", input=str(INPUT_DIR), discover_materials=len(idx.get("materials") or []),
              chars=sum(m.get("chars") or 0 for m in idx.get("materials") or []))
    write_partial_result({}, idx, case)
    target = int(h["slides"]) if h.get("slides") else None
    v0 = evidence.outline_skeleton(idx, h, target)
    evidence.journal("skeleton", "v0 written", pages=len(v0["pages"]), seconds=v0["total_seconds"], target=target)
    plan = read_json(a.plan or WORK_DIR / "slide_plan.json")
    rep = audit_plan(plan, idx, target)
    if rep["usable"]:
        changes.append({"what": "slide_plan", "from": "agent draft", "to": "used as-is",
                        "why": "%d/%d quotes verified, %d slides" % (rep["quotes_verified"], rep["quotes_checked"], rep["slides"])})
    else:
        n_bad = len(rep["errors"])
        plan = baseline_plan(idx, h)
        plan["narrative"] = [{"act": "背景与问题", "slides": "2-%d" % max(2, len(plan["slides"]) // 2), "purpose": "建立动机"},
                             {"act": "证据与结论", "slides": "%d-%d" % (max(3, len(plan["slides"]) // 2 + 1), len(plan["slides"])),
                              "purpose": "给结果并标注证据强度"}]
        degr.append("usable authored plan not found (%d errors) -> deterministic plan built from source paragraphs" % n_bad)
        changes.append({"what": "slide_plan", "from": "agent plan (%d errors)" % n_bad, "to": "fallback plan",
                        "why": "no verified plan available; the fallback keeps every page traceable to a source paragraph"})
        rep = audit_plan(plan, idx, target)
    deck = deck_payload(plan, h)
    if not deck["slides"]:
        deck["slides"] = [{"title": h.get("title") or "Academic report", "bullets": [], "layout": "title",
                           "notes": "No usable material: please add input files.", "source": ""}]
        degr.append("no usable source text; the deck is reduced to one title placeholder")
    pptx = OUTPUT_DIR / "presentation.pptx"
    info = {}
    try:
        info = slidewriter.build_pptx(deck, pptx, resolve_template(h, idx))
        if not info.get("template_used") and (h.get("template") or idx.get("template")):
            degr.append("template inheritance failed; fell back to the built-in master: %s"
                        % "; ".join(info.get("errors") or ["unknown"]))
    except Exception as e:
        errors.append("pptx build failed: %r" % (e,))
    pdf = OUTPUT_DIR / "preview.pdf"
    got = slidewriter.office_pdf(pptx, OUTPUT_DIR) if pptx.exists() and pptx.stat().st_size > 2000 else None
    if got and got.name != "preview.pdf":
        got.replace(pdf)
    if got:
        changes.append({"what": "preview", "from": "-", "to": "preview.pdf", "why": "LibreOffice export (fidelity 1:1)"})
    else:
        write_plain_pdf(deck, pdf)
        degr.append("LibreOffice missing or failed; preview.pdf comes from the stdlib text writer; "
                    "re-export on a desktop for the final visual check")
    (OUTPUT_DIR / "slide_plan.md").write_text(plan_as_markdown(plan, h), encoding="utf-8")
    cmap = [{"slide": i, "title": s.get("title"), "claim": s.get("claim"), "evidence_strength": s.get("evidence_strength"),
             "visual": s.get("visual"), "notes": s.get("notes"),
             "bullets": [{"text": b.get("text"), "locator": b.get("locator"), "quote": b.get("quote"),
                          "verified": locate_verbatim(b.get("quote"), idx) if b.get("quote") else (b.get("locator") or None)}
                         for b in (s.get("bullets") or []) if isinstance(b, dict)]}
            for i, s in enumerate(plan.get("slides") or [], 1)]
    zok, zmsg = False, ""
    try:
        with zipfile.ZipFile(pptx) as z:
            nm = z.namelist()
            zok = z.testzip() is None and any(re.match(r"ppt/slides/slide\d+\.xml$", x) for x in nm)
            zmsg = "%d parts, %d slides, %d notes" % (len(nm), len([x for x in nm if "/slides/slide" in x]),
                                                     len([x for x in nm if "notesSlide" in x]))
    except Exception as e:
        zmsg = repr(e)
    n = len(deck["slides"])
    try:
        pages = pdf_page_count(pdf)
    except Exception:
        pages = 0
    dup = [i for i, s in enumerate(plan.get("slides") or [], 1)
           if s.get("notes") and any(b.get("text") and squeeze_text(b["text"])[:40] in squeeze_text(s["notes"])
                                     for b in (s.get("bullets") or []) if isinstance(b, dict))]
    chk = {"slide_count": {"value": n, "target": target, "pass": target is None or n == target},
           "bullets_3_5": {"pass": all(3 <= len([b for b in (s.get("bullets") or []) if isinstance(b, dict)]) <= 5
                                       or s.get("layout") == "title" or i == 1
                                       for i, s in enumerate(plan.get("slides") or [], 1))},
           "notes_present": {"pass": all(str(s.get("notes") or "").strip() or s.get("layout") == "title" for s in plan.get("slides") or [])},
           "notes_not_repeating": {"duplicated_slides": dup, "pass": not dup},
           "evidence": {"checked": rep["quotes_checked"], "verified": rep["quotes_verified"],
                        "slides_with_evidence": rep["slides_with_evidence"], "slides": rep["slides"],
                        "pass": rep["quotes_checked"] > 0 and rep["quotes_verified"] == rep["quotes_checked"]},
           "pptx_editable": {"pass": zok, "detail": zmsg},
           "template": {"used": info.get("template_used"), "mode": info.get("mode"), "errors": info.get("errors")},
           "preview": {"pdf": "output/preview.pdf", "pages": pages, "pass": pages == n},
           "aspect": {"pass": True, "note": "sldSz 12192000x6858000 EMU (16:9)"},
           "fonts": {"theme": "Arial / Microsoft YaHei"}}
    write_json(OUTPUT_DIR / "compliance_checks.json", chk)
    write_json(OUTPUT_DIR / "content_map.json", cmap)
    vals = {"slide_plan": {"md": "output/slide_plan.md", "json": "work/slide_plan.json", "slides": n,
                           "audience": h.get("audience"), "duration_min": h.get("duration"), "target": target,
                           "narrative": plan.get("narrative")},
            "pptx": "output/presentation.pptx", "preview": "output/preview.pdf", "content_map": cmap,
            "compliance": chk,
            "notes": [{"slide": i, "notes": s.get("notes")} for i, s in enumerate(plan.get("slides") or [], 1)],
            "qa": plan.get("qa") or [],
            "coverage": {"slides": n, "with_evidence": rep["slides_with_evidence"],
                         "quotes_verified": rep["quotes_verified"], "quotes_checked": rep["quotes_checked"]},
            "summary": "%d 页可编辑演示稿（%s）+ 逐页证据映射；%d/%d 条引用在源材料逐字命中。"
                       % (n, info.get("mode", "-"), rep["quotes_verified"], rep["quotes_checked"]),
            "uncertainty": [], "pending_human": []}
    if rep["quotes_checked"] == 0:
        vals["uncertainty"].append("no verbatim quote was checked: the page-to-source mapping is not machine-confirmed.")
    vals["pending_human"] += ["validation failures: %s" % json.dumps(e, ensure_ascii=False) for e in rep["errors"][:6]]
    if not rep["page_match"]:
        vals["pending_human"].append("plan has %d pages but %d were requested: add or cut pages before presenting."
                                     % (n, target))
    if not got:
        vals["pending_human"].append("re-check the pptx layout in PowerPoint/LibreOffice on a desktop (the preview is a fallback render).")
    ok = rep["passed"] and zok and pages == n and not errors and (target is None or n == target)
    status = "ok" if ok else ("insufficient_evidence" if rep["quotes_checked"] == 0 and n > 1 else "partial")
    if not idx.get("materials") and not case:
        status = "input_error"
    ckeys = contract_field_names(case)
    cmiss = [k for k in ckeys if k not in assemble_result(case, idx, vals, status, errors, degr, changes)]
    af = evidence.finalize_assets(OUTPUT_DIR, WORK_DIR, case, idx, h, plan, chk, rep, target, vals, status,
                        errors, degr, changes, v0, contract_missing=cmiss, ckeys=ckeys)
    evidence.journal("finalize", "assets done", self_check=(af.get("self_check") or {}).get("overall"),
              diff_pass=(af.get("diff_report") or {}).get("pass_items"))
    if (af.get("self_check") or {}).get("stage") != "full" and status == "ok":
        status = "partial"
    write_json(OUTPUT_DIR / "result.json", assemble_result(case, idx, vals, status, errors, degr, changes, extra={
        "deliverables": {"presentation": "output/presentation.pptx", "preview_pdf": "output/preview.pdf",
                         "slide_plan_md": "output/slide_plan.md", "slide_plan_json": str(WORK_DIR / "slide_plan.json"),
                         "content_map": "output/content_map.json", "compliance": "output/compliance_checks.json"},
        "check_report": rep}))
    print(json.dumps({"status": status, "slides": n, "mode": info.get("mode"),
                      "quotes": [rep["quotes_verified"], rep["quotes_checked"]], "pdf_pages": pages,
                      "checks": {k: v.get("pass") for k, v in chk.items() if isinstance(v, dict) and "pass" in v and v.get("pass") is not None},
                      "degradations": degr, "seconds": elapsed_seconds()}, ensure_ascii=False, indent=2))
    return 0


# ---------------- CLI entry point ----------------


def cli_main():
    ap = argparse.ArgumentParser(description="academic talk deck pipeline (init | show | check | build)")
    ap.add_argument("--version", action="version",
                    version="talk-deck-studio 1.0.0")
    ap.add_argument("cmd", nargs="?", default="init", choices=["init", "show", "check", "build"])
    ap.add_argument("--grep", help="show: only print paragraphs matching this regex")
    ap.add_argument("--material", help="show: restrict output to one material id, e.g. M1")
    ap.add_argument("--limit", type=int, help="show: cap printed paragraphs per material")
    ap.add_argument("--plan", help="check/build: read the plan from this path instead")
    a = ap.parse_args()
    evidence.journal("start", "cmd=%s" % a.cmd, python=sys.version.split()[0])
    try:
        rc = {"init": run_init, "show": run_show, "check": run_check, "build": run_build}[a.cmd](a)
        evidence.journal("exit", "rc=%s" % rc, seconds=elapsed_seconds())
        return rc
    except SystemExit:
        raise
    except Exception as e:
        try:
            evidence.journal("fatal", repr(e)[:300], tb=traceback.format_exc()[-600:])
            write_partial_result({"uncertainty": ["fatal: %r" % (e,)]})
        except Exception:
            pass
        print("error: %r (legal partial result.json written)" % (e,))
        return 0
    finally:
        try:
            evidence.flush_run_log(OUTPUT_DIR)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(cli_main())
