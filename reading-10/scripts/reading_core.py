#!/usr/bin/env python3
"""Toolkit behind the reading-bench forge skill.

Everything that touches bytes lives here: input discovery, text extraction for
plain / DOCX / XLSX / PDF material, the paragraph corpus with M<nn>#p<k> locators,
verbatim quote lookup, draft-item coercion, item auditing, and the small helper
set that keeps result.json on-contract. The four workflow verbs are wired up in
run_build.py; nothing here prints unless this module is executed directly.
"""
import hashlib, json, os, re, shutil, subprocess, sys, time, traceback, zipfile, zlib
from html import unescape
from pathlib import Path

VER, TITLE, T_START = "1.0.0", "reading-bench-forge", time.time()
KINDS = ("extraction", "numeric", "method", "definition", "conflict", "coverage", "table", "other")
TEXT_EXTS = {".md", ".txt", ".text", ".csv", ".tsv", ".json", ".jsonl", ".html", ".htm", ".xml", ".tex",
        ".yaml", ".yml", ".rst", ".log", ".py", ".bib"}
STOPWORDS = set(("a an the of and or to in for on with by from this that these is are was were be been it its as at "
           "not but can may such using used study paper result results than then there their they has have had "
           "which who what when where how also more most both each into during show").split())
ID_KEYS = ("case_id", "caseId", "case", "id", "task_id", "taskId", "sample_id")
CONTRACT_KEYS = ("output_contract", "outputContract", "contract", "required_outputs", "result_contract", "output_schema")
SYNTH_KEYS = ("candidate_output", "candidate_answer", "baseline_output", "model_output", "response_text", "checker_log")
FIELD_HINTS = [("scoring", "scor grade rubric"), ("anchors", "anchor evidence citation locator"),
      ("items", "bench item question test"), ("stats", "count metric stat coverage"),
      ("report", "report summary finding"), ("status", "status state"),
      ("sources", "source input material"), ("uncertainty", "uncertain limitation risk gap"),
      ("outputs", "path file output artifact deliverable"), ("changes", "change log revision")]


def root_dir():
    return Path(__file__).resolve().parent.parent


def _resolve_root(env, cands):
    v = os.environ.get(env)
    if v:
        return Path(v).expanduser()
    for c in cands:
        try:
            if Path(c).is_dir():
                return Path(c)
        except OSError:
            pass
    return Path(cands[0])


IN_DIR = _resolve_root("READBENCH_IN", ["/input", str(root_dir().parent / "input"), "input"])
OUT_DIR = _resolve_root("READBENCH_OUT", ["/app/output", str(root_dir().parent / "output"), "output"])
WORK_DIR = _resolve_root("READBENCH_WORK", ["/app/work", str(root_dir().parent / "work"), "work"])


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def read_text(p):
    b = Path(p).read_bytes()
    for e in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return b.decode(e), e
        except UnicodeDecodeError:
            pass
    return b.decode("utf-8", "ignore"), "utf-8-ignore"


def read_json(p):
    t = read_text(p)[0].replace("\ufeff", "").strip()
    if not t:
        raise ValueError("json file is empty")
    return json.loads(t)


def write_json(p, o):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def squeeze(s):
    return re.sub(r"\s+", " ", (s or "").replace("\ufeff", "")).strip()


def strip_space(s):
    return re.sub(r"\s+", "", s or "")


def first_of(d, *names, default=None):
    for n in names:
        v = d.get(n) if isinstance(d, dict) else None
        if v not in (None, "", [], {}):
            return v
    return default


def sniff_kind(p):
    e, h = p.suffix.lower(), b""
    try:
        h = p.read_bytes()[:8]
    except OSError:
        pass
    if h.startswith(b"%PDF") or e == ".pdf":
        return "pdf"
    if h.startswith(b"PK") or e in (".docx", ".doc", ".xlsx", ".xls"):
        return "xlsx" if e in (".xlsx", ".xls") else "docx"
    if e in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"):
        return "image"
    return "text" if e in TEXT_EXTS else "binary"


def xml_to_plain(x):
    x = re.sub(r"</(w:p|w:tr|a:p|text:p)>", "\n\n", re.sub(r"<(w:br|w:cr)\s*/>", "\n", x))
    return unescape(re.sub(r"<[^>]+>", "", x))


def zip_member_text(p, part, pref):
    with zipfile.ZipFile(p) as z:
        n = z.namelist()
        if part not in n:
            c = [x for x in n if x.startswith(pref) and x.endswith(".xml")]
            if not c:
                raise ValueError("zip member absent: " + part)
            part = c[0]
        return z.read(part).decode("utf-8", "ignore")


def pdf_quality(t):
    if len(t.strip()) < 40:
        return 0.0
    s = t[:4000]
    return round(min(sum(c.isprintable() or c in "\n\t" for c in s) / len(s),
                     sum(c.isalpha() or c.isspace() for c in s) / len(s)), 3)


def pdf_inflate(p):
    """Last-resort PDF reader, standard library only.

    Flate streams are inflated and their literal strings are lifted; good enough
    for text-layer PDFs from common exporters. Quality is a fixed mid value
    because no real verifier is involved.
    """
    d, out = Path(p).read_bytes(), []
    for m in re.finditer(rb"stream\r?\n", d):
        end = d.find(b"endstream", m.end())
        if end < 0:
            continue
        try:
            raw = zlib.decompressobj().decompress(d[m.end():end])
        except Exception:
            continue
        s = " ".join(re.sub(rb"\\([nrtbf()\\])", lambda x: b" " if x.group(1) in b"nrtbf" else x.group(1),
                            t.group()[1:-1]).decode("latin-1")
                     for t in re.finditer(rb"\((?:\\.|[^\\()])*\)", raw))
        if s.strip():
            out.append(s)
    return "\f".join(out)


def pdf_extract(p):
    if shutil.which("pdftotext"):
        try:
            t = subprocess.run([shutil.which("pdftotext"), "-layout", str(p), "-"], capture_output=True,
                               timeout=120).stdout.decode("utf-8", "ignore")
            if pdf_quality(t) >= 0.55:
                return t, "pdftotext", pdf_quality(t)
        except Exception:
            pass
    for name, fn in (("pymupdf", lambda: "\f".join(g.get_text() for g in __import__("fitz").open(str(p)))),
                     ("pdfminer", lambda: __import__("pdfminer.high_level", fromlist=["x"]).extract_text(str(p)))):
        try:
            t = fn()
            if pdf_quality(t) >= 0.55:
                return t, name, pdf_quality(t)
        except Exception:
            pass
    try:
        return pdf_inflate(p), "stdlib-zlib", 0.6
    except Exception:
        return "", "failed", 0.0


def extract_material(p, k):
    if k == "text":
        t, e = read_text(p)
        return t, "plain/" + e, ""
    if k == "docx":
        return xml_to_plain(zip_member_text(p, "word/document.xml", "word/")), "docx-xml", ""
    if k == "xlsx":
        try:
            return xml_to_plain(zip_member_text(p, "xl/sharedStrings.xml", "xl/")), "xlsx-xml", "shared strings only"
        except Exception as e:
            return "", "failed", str(e)
    if k == "pdf":
        t, m, q = pdf_extract(p)
        return t, "pdf/" + m, "" if q >= 0.55 else "pdf_text_quality_low=%.2f" % q
    if k == "image":
        return "", "none", "raster image: the standard library cannot OCR it, needs a visual read"
    return "", "none", "binary payload without a stdlib decoder"


def make_blocks(t):
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    raw = [b.strip() for b in re.split(r"\n\s*\n", t) if b.strip()]
    if len(raw) < 3:
        raw = [b.strip() for b in t.split("\n") if b.strip()]
    out = [re.sub(r"[ \t]+", " ", b).strip() for b in raw]
    return [b for b in out if len(b) >= 25] or ([squeeze(t)] if t.strip() else [])


def make_units(t):
    if "\f" in t:
        return [(i + 1, b) for i, pg in enumerate(t.split("\f")) for b in make_blocks(pg)]
    return [(None, b) for b in make_blocks(t)]


def index_input(ip):
    """Walk the input tree once and return the material index.

    Per-file problems become error/degradation entries instead of exceptions, so
    one broken attachment can never abort the whole run.
    """
    try:
        files = [p for p in sorted(Path(ip).rglob("*")) if p.is_file() and not p.name.startswith(".")
                 and not any(s in p.parts for s in ("__pycache__", ".git", "node_modules"))
                 and not (p.parent == Path(ip) and p.name in ("case.json", "task.md", "result.json"))]
    except OSError as e:
        return {"materials": [], "n_paragraphs": 0, "degradations": [], "input_root": str(ip),
                "errors": [{"stage": "scan", "error": str(e)}]}
    mats, deg, errs = [], [], []
    for n, p in enumerate(files, 1):
        mid, k = "M%02d" % n, sniff_kind(p)
        rec = {"mid": mid, "name": p.name, "path": str(p), "kind": k, "status": "ok", "method": "none",
               "note": "", "bytes": -1, "sha1": None, "paragraphs": [], "chars": 0}
        try:
            b = p.read_bytes()
            rec["bytes"], rec["sha1"] = len(b), hashlib.sha1(b).hexdigest()[:16]
        except OSError:
            pass
        try:
            t, m, note = extract_material(p, k)
            rec.update(method=m, note=note)
            if note:
                deg.append({"material": mid, "file": p.name, "issue": note})
            if not t.strip():
                rec["status"] = "no_text"
                errs.append({"stage": "material", "material": mid, "error": "no text could be extracted"})
            for i, (pg, b) in enumerate(make_units(t), 1):
                par = {"pid": "%s#p%d" % (mid, i), "n": i, "text": b}
                if pg:
                    par["page"] = pg
                rec["paragraphs"].append(par)
            rec["chars"] = sum(len(x["text"]) for x in rec["paragraphs"])
        except Exception as e:
            rec.update(status="error", note="extraction failed: %s" % e)
            errs.append({"stage": "material", "material": mid, "error": str(e)})
            deg.append({"material": mid, "file": p.name, "issue": "extraction failed: %s" % e})
        mats.append(rec)
    return {"schema": "reading-bench-forge/index@1", "generated_at": stamp(), "input_root": str(ip),
            "materials": mats, "n_paragraphs": sum(len(m["paragraphs"]) for m in mats),
            "degradations": deg, "errors": errs}


def build_corpus(idx):
    c = {}
    for m in idx.get("materials", []):
        buf, spans = "", []
        for par in m.get("paragraphs", []):
            t = squeeze(par["text"])
            if t:
                buf += (" " if buf else "") + t
                spans.append((len(buf) - len(t), len(buf), par))
        if spans:
            c[m["mid"]] = {"t": buf, "cf": buf.casefold(), "spans": spans}
    return c


def locate_quote(c, mid, q):
    """Look one quote up in the corpus and report where it landed.

    Three passes: byte-exact, case-folded, then whitespace-stripped. The first hit
    decides both the match mode and the paragraph id handed back to the caller.
    """
    q = squeeze(q)
    if not q:
        return {"verified": False, "reason": "blank_quote"}
    if mid not in c:
        return {"verified": False, "reason": "material_unknown"}
    for mode, needle, hay in (("exact", q, c[mid]["t"]), ("casefold", q.casefold(), c[mid]["cf"])):
        pos = hay.find(needle)
        if pos >= 0:
            pid = page = None
            for s, e, par in c[mid]["spans"]:
                if s <= pos < e or pos < s < pos + len(needle):
                    pid, page = par["pid"], par.get("page")
                    break
            return {"verified": True, "match": mode, "pid": pid, "page": page}
    if strip_space(q) in strip_space(c[mid]["t"]):
        return {"verified": True, "match": "ignoring_all_spaces", "pid": None, "page": None}
    return {"verified": False, "reason": "quote_absent"}


def deep_find(o, keys, d=0):
    if d > 4:
        return None
    if isinstance(o, dict):
        for k, v in o.items():
            if str(k).lower().replace("-", "_") in [x.lower() for x in keys]:
                return v
        vals = list(o.values())
    elif isinstance(o, list):
        vals = o[:5]
    else:
        return None
    for v in vals:
        r = deep_find(v, keys, d + 1)
        if r is not None:
            return r
    return None


def read_case_pack(ip):
    ip = Path(ip)
    for p in ([ip / "case.json"] + sorted(ip.glob("case*.json"))) if ip.is_dir() else []:
        if p.is_file():
            try:
                o = read_json(p)
                return (o if isinstance(o, dict) else {"_raw": o}), p
            except Exception:
                return {"_bad_json": str(p)}, p
    return {}, None


def source_records(idx):
    return [{"id": m["mid"], "name": m["name"], "path": m["path"], "kind": m["kind"], "bytes": m["bytes"],
             "sha1": m["sha1"], "paragraphs": len(m["paragraphs"]), "status": m["status"],
             "method": m["method"]} for m in idx.get("materials", [])]


def contract_field_names(c):
    if isinstance(c, dict):
        return [str(k) for k in c]
    out = []
    for x in c if isinstance(c, list) else []:
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            out += [x[k] for k in ("name", "field", "key", "id", "path") if isinstance(x.get(k), str)][:1]
    return out


def blank_shape(s):
    return {k: blank_shape(v) for k, v in s.items()} if isinstance(s, dict) else ([] if isinstance(s, list) else None)


def fulfill_contract(con, ctx):
    """Build the top-level echo for every field the case declares.

    Known fields carry real values; unknown ones fall back to a null-shaped mirror
    of the declaration so no announced key ever disappears from result.json.
    """
    out = {}
    for k in contract_field_names(con):
        lk, v = k.lower(), None
        # exact/near-exact names are resolved before fuzzy word hints, so a field
        # named status is never satisfied by stats by accident
        if lk in ctx:
            v = ctx.get(lk)
        if v is None:
            for name, words in FIELD_HINTS:
                if lk == name or any(re.search(r"(^|[_\-\s])" + re.escape(w), lk) for w in words.split()):
                    v = ctx.get(name)
                    break
        if v is None and isinstance(con, dict):
            v = blank_shape(con[k])
        out[k] = v
    return out


def result_skeleton(cid, con, status, stage):
    return {"case_id": cid, "status": status, "stage": stage, "skill": {"name": TITLE, "version": VER},
            "outputs": {}, "benchmark": None, "anchors": None,
            "scoring": None, "sources": [], "uncertainty": [], "pending_human": [], "errors": [],
            "degradations": [], "changes": [], "technical_synthetic": {"present": False, "not_a_dsh_score": True},
            "runtime": {"skill_version": VER, "python": sys.version.split()[0], "started_at": stamp(),
                        "elapsed_s": 0.0, "input_root": str(IN_DIR), "output_root": str(OUT_DIR)},
            "contract_fields_present": contract_field_names(con), "contract_echo": con or {}}


def persist_result(res, stage):
    res["runtime"].update({"stage": stage, "written_at": stamp(), "elapsed_s": round(time.time() - T_START, 2),
                           "argv": sys.argv[1:]})
    write_json(OUT_DIR / "result.json", res)


def bootstrap(stage, case):
    """Create the output/work roots and persist a legal partial result.json at once."""
    for d in (OUT_DIR, WORK_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    con = deep_find(case, CONTRACT_KEYS) if isinstance(case, dict) else None
    con = con if isinstance(con, (dict, list)) else {}
    cid = deep_find(case, ID_KEYS) if isinstance(case, dict) else None
    res = result_skeleton(str(cid) if cid else None, con, "partial", stage)
    res["pending_human"] = ["run the build verb to finalise benchmark/anchors/scoring/report"]
    persist_result(res, stage)
    return res, con


def load_or_index(res):
    p = WORK_DIR / "index.json"
    if p.is_file():
        try:
            return read_json(p)
        except Exception as e:
            res["errors"].append({"stage": "index", "error": str(e)})
    idx = index_input(IN_DIR)
    write_json(p, idx)
    return idx


# ---- draft items, term extraction, auditing ------------------------------------
def extract_terms(t, k=8):
    out = []
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", t or ""):
        L = min(4, len(run))
        for i in range(len(run) - L + 1):
            out.append(run[i:i + L])
            if len(out) >= k:
                return out[:k]
    for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", t or ""):
        if w.lower() not in STOPWORDS:
            out.append(w.lower())
            if len(out) >= k:
                break
    return out[:k]


def term_coverage(ts, text):
    cf = (text or "").casefold()
    return round(sum(t.casefold() in cf for t in ts) / len(ts), 3) if ts else 0.0


def parse_locator(loc):
    m = re.match(r"^\s*([A-Za-z0-9_\-]+)\s*#\s*p(\d+)\s*$", str(loc or ""))
    return (m.group(1), int(m.group(2))) if m else (None, None)


def coerce_item(raw, i):
    """Normalise one hand-written item; returns (item, errors) and never raises."""
    if not isinstance(raw, dict):
        return None, ["item %d is not an object" % i]
    it = {"id": str(first_of(raw, "id", "qid", default="Q%02d" % i)).strip(),
          "type": str(first_of(raw, "type", "task_type", default="other")).lower(),
          "difficulty": str(first_of(raw, "difficulty", "level", default="medium")).lower(),
          "question": str(first_of(raw, "question", "prompt", default="")).strip(),
          "rubric": [], "reference_answer": [], "evidence": []}
    it["type"] = it["type"] if it["type"] in KINDS else "other"
    ra = first_of(raw, "reference_answer", "answer", default=[])
    it["reference_answer"] = [str(x).strip() for x in ([ra] if isinstance(ra, str) else ra) if str(x).strip()]
    rub = first_of(raw, "rubric", "rubric_points", default=[])
    for j, rp in enumerate([rub] if isinstance(rub, dict) else rub, 1):
        rp = {"text": rp} if isinstance(rp, str) else rp
        if not isinstance(rp, dict):
            continue
        try:
            w = float(first_of(rp, "weight", default=1.0 / max(1, len(rub))))
        except (TypeError, ValueError):
            w = 0.0
        it["rubric"].append({"id": str(first_of(rp, "id", default="R%d" % j)),
                             "text": str(first_of(rp, "text", "point", default="")).strip(),
                             "weight": round(w, 4),
                             "key_terms": [str(x) for x in (rp.get("key_terms") or []) if str(x).strip()]})
    for e in first_of(raw, "evidence", "anchors", default=[]):
        if isinstance(e, dict):
            loc = str(first_of(e, "locator", "loc", default="")).strip()
            it["evidence"].append({"material": str(first_of(e, "material", "mid", default="")).strip()
                                   or (parse_locator(loc)[0] or ""), "locator": loc,
                                   "quote": str(first_of(e, "quote", "text", default="")).strip()})
    errs = ["%s: %s" % (it["id"], m) for bad, m in
            ((len(it["question"]) < 10, "question missing or shorter than 10 characters"), (not it["rubric"], "no rubric point defined"),
             (not it["reference_answer"], "no reference_answer given"),
             (not it["evidence"], "no evidence block (locator + verbatim quote)")) if bad]
    return it, errs


def audit_items(draft, c):
    """Audit required fields, quote fidelity and locator agreement in one pass."""
    if not isinstance(draft, dict):
        return {"ok": False, "items": [], "rejected": [], "n_raw": 0, "warnings": [],
                "issues": [{"level": "error", "msg": "draft is not a JSON object"}]}
    raws = first_of(draft, "items", "questions", default=[])
    raws = (raws.get("items") or []) if isinstance(raws, dict) else (raws if isinstance(raws, list) else [])
    iss, warns, items, rej, seen = [], [], [], [], set()
    for i, raw in enumerate(raws, 1):
        it, errs = coerce_item(raw, i)
        if not it:
            iss += [{"level": "error", "msg": e} for e in errs]
            continue
        iss += [{"level": "error", "item": it["id"], "msg": e} for e in errs]
        if it["id"] in seen:
            it["id"] += "b"
            iss.append({"level": "error", "item": it["id"], "msg": "duplicate item id was renamed"})
        seen.add(it["id"])
        tot = sum(p["weight"] for p in it["rubric"])
        if it["rubric"] and abs(tot - 1.0) > 0.02:
            warns.append({"item": it["id"], "msg": "rubric weights sum to %.2f (expected 1.0)" % tot})
        good = 0
        for ev in it["evidence"]:
            if len(squeeze(ev["quote"])) < 12:
                iss.append({"level": "error", "item": it["id"], "msg": "quote shorter than 12 characters"})
            v = ev["_v"] = locate_quote(c, ev["material"], ev["quote"])
            if not v.get("verified"):
                iss.append({"level": "error", "item": it["id"],
                            "msg": "quote not found in %s (%s) - re-copy the paragraph verbatim from `show`"
                                   % (ev["material"], v.get("reason"))})
                continue
            good += 1
            pid = v.get("pid")
            if pid and ev["locator"] and pid != ev["locator"]:
                iss.append({"level": "error", "item": it["id"], "msg": "locator_mismatch: declared %s, actual %s"
                            % (ev["locator"], pid)})
            elif not ev["locator"] and pid:
                ev["locator"] = pid
                warns.append({"item": it["id"], "msg": "locator inferred from the matched quote (%s)" % pid})
        (items if good else rej).append(it)
        if not any(p["key_terms"] for p in it["rubric"]):
            warns.append({"item": it["id"], "msg": "no key_terms given (derived from the reference answer)"})
    return {"ok": not any(x["level"] == "error" for x in iss), "items": items, "issues": iss,
            "warnings": warns, "rejected": rej, "n_raw": len(raws)}



def retarget(inp=None, out=None, work=None):
    """Re-point the three filesystem roots at run time.

    The CLI exposes them as --input/--output/--work so a smoke run never has to
    touch /input or /app; embedding callers may call this directly. None keeps the
    current value, so partial overrides are allowed.
    """
    global IN_DIR, OUT_DIR, WORK_DIR
    moved = []
    if inp:
        IN_DIR = Path(inp).expanduser().resolve()
        moved.append("input -> " + str(IN_DIR))
    if out:
        OUT_DIR = Path(out).expanduser().resolve()
        moved.append("output -> " + str(OUT_DIR))
    if work:
        WORK_DIR = Path(work).expanduser().resolve()
        moved.append("work -> " + str(WORK_DIR))
    return {"roots": moved, "input": str(IN_DIR), "output": str(OUT_DIR), "work": str(WORK_DIR)}


if __name__ == "__main__":
    try:
        print("reading-bench-forge %s | helper library (verbs live in run_build.py)" % VER)
        print("try: python3 -B scripts/run_build.py --help   (init | show | check | build)")
        print("roots: input=%s output=%s work=%s" % (IN_DIR, OUT_DIR, WORK_DIR))
    except Exception:
        print(traceback.format_exc(limit=3))
    sys.exit(0)

