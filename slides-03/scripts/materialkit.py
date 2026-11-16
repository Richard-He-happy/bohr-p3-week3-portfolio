#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""materialkit -- input discovery, text extraction and contract routing.

Reads whatever sits under the input root (PDF / DOCX / XLSX / PPTX / CSV / plain
text) into locator-addressable paragraphs and projects the run onto an arbitrary
output_contract.  No working-directory assumptions, no network, and one broken
material file never aborts the whole run.
"""
import json
import os
import re
import sys
import time
import zipfile
import zlib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent


sys.path.insert(0, str(ROOT_DIR))


START_CLOCK = time.time()


READABLE_EXT = {".pdf", ".docx", ".txt", ".md", ".csv", ".tsv", ".json", ".xlsx", ".pptx",
       ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".html", ".tex"}


NOISE_NAMES = {"task.md", "guide.md", "readme.md"}


def elapsed_seconds():
    return round(time.time() - START_CLOCK, 1)


def ensure_output_dir(env, dflt):
    for c in (os.environ.get(env), dflt, "."):
        if c:
            try:
                p = Path(c)
                p.mkdir(parents=True, exist_ok=True)
                if os.access(p, os.W_OK):
                    return p
            except Exception:
                pass
    return Path.cwd()


INPUT_DIR = Path(os.environ.get("IN_DIR") or next((c for c in ("/input", str(Path.cwd() / "input"), str(ROOT_DIR.parent / "input"))
                                            if Path(c).is_dir()), "/input"))


WORK_DIR = ensure_output_dir("WORK_DIR", "/app/work")


OUTPUT_DIR = ensure_output_dir("OUT_DIR", "/app/output")


# ---------------- tiny IO helpers ----------------


def read_json(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except Exception:
        return d


def write_json(p, o):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------- input discovery ----------------


def probe_file_kind(p):
    try:
        h = Path(p).read_bytes()[:8]
    except Exception:
        return ""
    if h.startswith(b"%PDF"):
        return "pdf"
    if h.startswith(b"PK\x03\x04"):
        return {".docx": "docx", ".xlsx": "xlsx", ".pptx": "pptx"}.get(p.suffix.lower(), "zip")
    if h.startswith(b"\x89PNG") or h[:2] in (b"\xff\xd8", b"II", b"MM"):
        return "image"
    return ""


def locate_case_file():
    for c in [INPUT_DIR / "case.json"] + sorted(INPUT_DIR.rglob("case*.json")):
        d = read_json(c)
        if isinstance(d, dict) and d:
            return c, d
    for c in sorted(INPUT_DIR.rglob("*.json")):
        d = read_json(c)
        if isinstance(d, dict) and re.search(r"instruction|output_contract|case_id|task", json.dumps(d)[:4000], re.I):
            return c, d
    bad = sorted(INPUT_DIR.rglob("case*.json")) if INPUT_DIR.is_dir() else []
    return (bad[0] if bad else None), {}


def flatten_tree(o, pre=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flatten_tree(v, "%s.%s" % (pre, k) if pre else str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from flatten_tree(v, "%s[%d]" % (pre, i))
    else:
        yield pre, o


def scan_hint(case, pats, num=False):
    for k, v in flatten_tree(case):
        if v in (None, "", [], {}) or not any(re.search(p, k.lower()) for p in pats):
            continue
        if not num:
            return v
        m = re.search(r"\d+(?:\.\d+)?", str(v))
        return float(m.group(0)) if m else None
    return None


def discover_materials():
    return [p for p in sorted(INPUT_DIR.rglob("*")) if INPUT_DIR.is_dir() and p.is_file() and not p.name.startswith(".")
            and p.name.lower() not in NOISE_NAMES and not re.match(r"case.*\.json$", p.name, re.I)
            and (p.suffix.lower() in READABLE_EXT or probe_file_kind(p))] if INPUT_DIR.is_dir() else []


# ---------------- text extraction ----------------


def split_paragraphs(text, mid):
    out = [re.sub(r"\s+", " ", s).strip() for s in re.split(r"\n\s*\n|\n|\f", text or "") if s.strip()]
    if len(out) < 2 and len((text or "").strip()) > 200:  
        out = [s.strip() for s in re.split(r"(?<=[。！？.!?])\s+", text) if len(s.strip()) > 2]
    return [{"loc": "%s#p%d" % (mid, i + 1), "text": s} for i, s in enumerate(out)]


def pdf_text_layer(p):
    tx = ""
    try:
        import subprocess
        r = subprocess.run(["pdftotext", "-layout", str(p), "-"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=120)
        tx = r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
    except Exception:
        tx = ""
    if len(tx.strip()) >= 40:
        return "pdf", tx
    try:  
        ch = []
        for m in re.finditer(rb"stream\r?\n(.*?)endstream", Path(p).read_bytes(), re.S):
            try:
                s = zlib.decompress(m.group(1))
            except Exception:
                continue
            ch += [t[1:-1] for t in re.findall(rb"\((?:[^()\\\\]|\\\\.)*\)", s)]
        return "pdf-crude", b" ".join(ch).decode("latin-1", "replace")
    except Exception:
        return "pdf-crude", ""


def load_material_text(p):
    k = probe_file_kind(p) or {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".pptx": "pptx"}.get(p.suffix.lower(), "text")
    try:
        if k == "pdf":
            return pdf_text_layer(p)
        if k == "image":
            return k, ""
        if k in ("docx", "pptx", "xlsx"):
            with zipfile.ZipFile(p) as z:
                nm = z.namelist()
                if k == "docx":
                    x = z.read("word/document.xml").decode("utf-8", "replace")
                    return k, re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n\n", x))
                if k == "pptx":
                    return k, "\n\n".join(" ".join(t for t in re.findall(r"<a:t>(.*?)</a:t>", z.read(n).decode("utf-8", "replace"), re.S) if t.strip())
                                          for n in sorted(x for x in nm if re.match(r"ppt/slides/slide\d+\.xml$", x)))
                sh = [re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode("utf-8", "replace"), re.S)] if "xl/sharedStrings.xml" in nm else []
                rows = [" | ".join(sh[int(v)] if v.isdigit() and int(v) < len(sh) else v for v in re.findall(r"<v>(.*?)</v>", r))
                        for s in sorted(n for n in nm if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
                        for r in re.findall(r"<row[^>]*>(.*?)</row>", z.read(s).decode("utf-8", "replace"), re.S)]
                return k, "\n".join(rows)
        return k, p.read_text(encoding="utf-8-sig")
    except Exception:
        try:
            return k, p.read_text(encoding="latin-1", errors="replace")
        except Exception:
            return "error", ""


def build_material_index():
    cp, case = locate_case_file()
    task = next((c.read_text(encoding="utf-8-sig", errors="replace") for c in (INPUT_DIR / "task.md", INPUT_DIR / "TASK.md") if c.is_file()), "")
    idx = {"input_root": str(INPUT_DIR), "case_path": str(cp) if cp else None, "case": case,
           "task_excerpt": task[:3000], "materials": [], "errors": [], "template": None}
    if cp and not case:
        idx["errors"].append("%s exists but is not parseable JSON: treated as absent contract" % cp.name)
    for i, p in enumerate(discover_materials(), 1):
        mid = "M%d" % i
        try:
            kind, tx = load_material_text(p)
            ps = split_paragraphs(tx.replace(",", " | ") if p.suffix.lower() in (".csv", ".tsv") else tx, mid)
        except Exception as e:
            idx["errors"].append("%s extract failed: %r" % (mid, e))
            kind, tx, ps = "error", "", []
        if kind == "image":
            idx["errors"].append("%s is an image: not read as text, listed as evidence gap" % mid)
        idx["materials"].append({"id": mid, "path": str(p), "name": p.name, "kind": kind,
                                 "bytes": p.stat().st_size if p.exists() else 0, "chars": len(tx), "paras": ps})
        if kind == "pptx" and not idx["template"]:
            idx["template"] = str(p)
            idx["materials"][-1]["role"] = "template"
    return idx


# ---------------- output_contract routing ----------------


ROUTE_TABLE = [(r"quotes?_checked|quotes?_verified|with_evidence|slide_count|^count$|pages?$", "coverage"),
       (r"slide_plan|plan|outline|storyboard|page", "slide_plan"),
       (r"content_map|evidence|mapping|trace|locator", "content_map"),
       (r"compliance|check|validat|render", "compliance"),
       (r"presentation|pptx|deck|editable|deliverable|file", "pptx"),
       (r"preview|pdf|png|image", "preview"), (r"notes|speaker|script", "notes"),
       (r"case_id", "case_id"), (r"status", "status"), (r"sources?|evidence", "sources"),
       (r"summary|conclusion|main_result|result", "summary"), (r"qa|question", "qa"),
       (r"coverage|metric|count", "coverage")]


def route_for_key(k):
    k = (k or "").lower()
    return next((nm for pat, nm in ROUTE_TABLE if re.search(pat, k)), k)


def fill_missing_leaves(tpl, vals, key="", parent=""):
    """Keep the contract shape; only null/empty leaves get filled, nested keys fall back to the parent mapping."""
    if isinstance(tpl, dict):
        return {k: fill_missing_leaves(v, vals, k, key) for k, v in tpl.items()}
    if isinstance(tpl, list):
        if tpl and all(isinstance(x, dict) for x in tpl):
            return [fill_missing_leaves(x, vals, key, parent) for x in tpl]
        if tpl:
            return tpl
        v = vals.get(route_for_key(key))
        return v if isinstance(v, list) else []
    if tpl in (None, ""):
        pv = vals.get(parent)
        if isinstance(pv, dict) and key in pv and not isinstance(pv[key], (dict, list)):
            return pv[key]
        v = vals.get(route_for_key(key))
        return tpl if v is None else v
    return tpl


CONTRACT_ROUTE = {"editable_source": "pptx", "export_artifact": "preview", "export": "preview",
                "content_map": "content_map", "compliance_checks": "compliance", "compliance": "compliance",
                "exceptions": None, "deliverable": "summary", "result": "summary", "claims": "coverage",
                "uncertainties": "uncertainty", "preserved_facts": None, "evidence_map": "content_map",
                "change_log": None, "slide_plan": "slide_plan", "presentation": "pptx", "preview": "preview"}


def contract_field_names(case):
    c = (case or {}).get("output_contract") if isinstance(case, dict) else None
    if isinstance(c, dict):
        return [k for k in c]
    return [x for x in c if isinstance(x, str)] if isinstance(c, list) else []


# ---------------- plan validation against the source ----------------


def squeeze_text(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def locate_verbatim(q, idx):
    n = squeeze_text(q)
    if not n:
        return None
    for m in idx.get("materials", []):
        if m.get("role") == "template":
            continue
        for p in m["paras"]:
            if n in squeeze_text(p["text"]):
                return p["loc"]
        if n in squeeze_text("".join(p["text"] for p in m["paras"])):
            return m["paras"][0]["loc"] if m["paras"] else m["id"]
    return None


def audit_plan(plan, idx, target=None):
    rep = {"errors": [], "warnings": [], "slides": 0, "bullets": 0, "quotes_checked": 0,
           "quotes_verified": 0, "slides_with_evidence": 0, "target_slides": target, "passed": False, "usable": False,
           "page_match": target is None}
    sl = plan.get("slides") if isinstance(plan, dict) else None
    if not isinstance(sl, list) or not sl:
        rep["errors"].append({"field": "slides", "msg": "no slides[] array: plan missing or malformed"})
        return rep
    rep["slides"] = len(sl)
    for i, s in enumerate(sl, 1):
        if not isinstance(s, dict):
            rep["errors"].append({"slide": i, "msg": "slide entry is not a mapping"})
            continue
        bl = [b for b in (s.get("bullets") or []) if isinstance(b, dict)]
        ts = s.get("layout") == "title" or (i == 1 and not bl)
        if not str(s.get("title") or "").strip():
            rep["errors"].append({"slide": i, "field": "title", "msg": "title is empty"})
        if not ts and not 3 <= len(bl) <= 5:
            rep["errors"].append({"slide": i, "field": "bullets", "msg": "%d bullets, expected 3 to 5" % len(bl)})
        if not ts and not str(s.get("notes") or "").strip():
            rep["warnings"].append({"slide": i, "msg": "speaker notes missing"})
        ev = False
        for j, b in enumerate(bl, 1):
            rep["bullets"] += 1
            if not str(b.get("text") or "").strip():
                rep["errors"].append({"slide": i, "field": "bullets[%d].text" % j, "msg": "bullet text is empty"})
            if b.get("quote"):
                rep["quotes_checked"] += 1
                f = locate_verbatim(b["quote"], idx)
                if f:
                    rep["quotes_verified"] += 1
                    ev = True
                    if b.get("locator") and squeeze_text(b["locator"]) not in squeeze_text(f):
                        rep["warnings"].append({"slide": i, "msg": "locator %s actually resolves to %s" % (b["locator"], f)})
                else:
                    rep["errors"].append({"slide": i, "field": "bullets[%d].quote" % j,
                                          "msg": "quote is not a verbatim source substring: %s" % str(b["quote"])[:50]})
            elif b.get("locator"):
                ev = True
            else:
                rep["warnings"].append({"slide": i, "field": "bullets[%d]" % j, "msg": "neither quote nor locator given"})
        if ev:
            rep["slides_with_evidence"] += 1
    rep["page_match"] = target is None or len(sl) == target
    rep["usable"] = (not rep["errors"] and rep["slides_with_evidence"] >= max(1, int(0.8 * rep["slides"])))
    rep["passed"] = rep["usable"] and rep["page_match"]
    return rep


# ---------------- deterministic plan + deck payload ----------------


def baseline_plan(idx, h):
    """Deterministic deck for unusable authored plans: each bullet is a verbatim source sentence plus locator, page count bounded by available evidence."""
    sents = [{"text": p["text"], "loc": p["loc"]} for m in idx.get("materials", []) if m.get("role") != "template" for p in m["paras"]
             if 25 <= len(p["text"]) <= 320 and not re.match(r"^(references|acknowledg|bibliograph)", p["text"], re.I)]
    if not sents:
        return {"slides": [], "_fallback": "no extractable source text"}
    want = max(4, min(15, int(h.get("slides") or 8)))
    pages = max(1, min(want - 1, len(sents) // 3))              
    pages = max(pages, -(-len(sents) // 5))                     
    sents = sents[:5 * pages]                                  
    q, r = divmod(len(sents), pages)
    out = [{"n": 1, "title": h.get("title") or "Talk outline", "layout": "title", "bullets": [],
            "subtitle": h.get("subtitle") or "Narrative built from the supplied material",
            "notes": "Opening: state the audience, the running time and the evidence strength, then enter the main line."}]
    k = 0
    for i in range(pages):
        ch = sents[k:k + q + (1 if i < r else 0)]
        k += len(ch)
        bl = [{"text": c["text"][:110], "locator": c["loc"], "quote": c["text"][:160]} for c in ch]
        while len(bl) < 3:                                      
            bl.append({"text": "No source evidence at this slot yet; the author must fill it (recorded under pending_human).", "locator": "", "quote": ""})
        out.append({"n": len(out) + 1, "title": "Point group %d (source order)" % len(out), "bullets": bl,
                    "notes": "One message per page; evidence from %s. Always state the conditions next to a number."
                             % "、".join(b["locator"] for b in bl),
                    "evidence_strength": "unrated"})
    return {"deck_title": h.get("title") or "Academic report", "slides": out,
            "_fallback": "deterministic plan from source paragraphs (%d pages; %d requested)" % (len(out), want)}


def resolve_template(h, idx):
    """Resolve a template hint (name, path or basename) to a real file, else fall back to the first pptx material."""
    t = h.get("template")
    for c in ([Path(str(t))] if t else []) + [Path(str(t)) if t else None, INPUT_DIR / str(t) if t else None]:
        try:
            if c and c.is_file():
                return str(c)
        except Exception:
            pass
    if t:
        for m in idx.get("materials", []):
            if Path(m["path"]).name == Path(str(t)).name:
                return m["path"]
    return idx.get("template")


def deck_payload(plan, h):
    sl = []
    for i, s in enumerate(plan.get("slides") or [], 1):
        bl = [{"text": b.get("text", ""), "locator": b.get("locator") or ""}
              for b in (s.get("bullets") or []) if isinstance(b, dict)]
        sl.append({"title": s.get("title") or "Slide %d" % i, "bullets": bl, "subtitle": s.get("subtitle") or "",
                   "layout": s.get("layout") or ("title" if i == 1 else "content"), "notes": s.get("notes") or "",
                   "source": "; ".join(sorted({b["locator"] for b in bl if b["locator"]}))})
    return {"title": plan.get("deck_title") or h.get("title") or "Academic report", "subtitle": plan.get("subtitle") or "",
            "meta": h.get("meta") or "", "slides": sl}
