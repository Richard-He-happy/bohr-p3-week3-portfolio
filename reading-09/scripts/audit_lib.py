#!/usr/bin/env python3
"""audit_lib.py - deterministic toolbox behind the repro-audit kit.

Contents
  * tolerant JSON / text persistence (BOM, GB18030 and latin-1 fallbacks)
  * material kind sniffing plus text-unit extraction (PDF, DOCX, XLSX, CSV/TSV,
    Markdown, JSON, plain text, images, archives)
  * quoted-evidence lookup over the material index
  * tolerance arithmetic and pre-declaration defaults
  * semantic backfill of an arbitrary output_contract template

Standalone:
  python -B audit_lib.py --help       this help
  python -B audit_lib.py --selftest   built-in assertions, exit code 0 == pass

Standard library only. No network access. Import-safe from any CWD.
"""
import argparse
import csv
import html
import io
import json
import os
import re
import sys
import unicodedata
import zipfile
import zlib
from pathlib import Path

NO_MATCH = object()

TEXT_SUFFIXES = (".txt", ".log", ".py", ".yaml", ".yml", ".toml", ".ini", ".cfg",
                 ".r", ".jl", ".m")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff")


# ------------------------------------------------------------------ persistence
def read_json(path):
    """Parse a JSON file tolerantly. Returns (object, error-or-None)."""
    p = Path(path)
    try:
        raw = p.read_bytes()
    except Exception as exc:
        return None, "read_failed:%s" % exc
    for codec in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return json.loads(raw.decode(codec)), None
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            return None, "parse_failed:%s" % exc
    return None, "decode_failed"


def _atomic_write(target, payload, binary=False):
    p = Path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    if binary:
        tmp.write_bytes(payload)
    else:
        tmp.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(tmp, p)
    return str(p)


def write_json(path, obj):
    """Serialise obj as pretty UTF-8 JSON; write-then-rename keeps it whole."""
    return _atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2))


def write_text(path, text):
    return _atomic_write(path, text)


# ------------------------------------------------------------------ text utils
def fade(s):
    """Fade punctuation width and case so quotes compare reliably."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKC", s)
    for ch in ("\u200b", "\ufeff", "\u00a0", "\u3000"):
        s = s.replace(ch, " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def clip(s, limit=200):
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return s if len(s) <= limit else s[:limit] + "\u2026"


def rows_of(text, prefix, hard_limit=4000):
    out, n = [], 0
    for chunk in re.split(r"\n\s*\n", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        pieces = ([x.strip() for x in chunk.splitlines() if x.strip()]
                  if len(chunk) > 1200 else [chunk])
        for piece in pieces:
            n += 1
            out.append(("%s:p%d" % (prefix, n), piece))
    return out[:hard_limit]


# ------------------------------------------------------------------ kind detection
def detect_kind(path):
    """Classify a material by magic bytes first, suffix second."""
    p = Path(path)
    suffix = p.suffix.lower()
    try:
        head = p.open("rb").read(1024)
    except Exception:
        return "unreadable"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8") or head[:4] == b"GIF8":
        return "image"
    if head[:2] == b"PK":
        try:
            with zipfile.ZipFile(p) as z:
                names = set(z.namelist())
        except Exception:
            return "zip"
        if "word/document.xml" in names:
            return "docx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        if any(n.startswith("ppt/") for n in names):
            return "pptx"
        return "zip"
    table = {".pdf": "pdf", ".json": "json", ".csv": "csv", ".tsv": "tsv",
             ".md": "md", ".markdown": "md", ".xlsx": "xlsx", ".xls": "xlsx",
             ".docx": "docx", ".ipynb": "ipynb"}
    if suffix in table:
        return table[suffix]
    if suffix in TEXT_SUFFIXES:
        return "text"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    try:
        head.decode("utf-8")
        return "text"
    except Exception:
        return "binary"


# ------------------------------------------------------------------ extractors
def _unescape_pdf_literal(blob):
    try:
        s = blob.decode("latin-1")
    except Exception:
        return ""
    s = s.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
    s = re.sub(r"\\([nrtbf])",
               lambda m: {"n": "\n", "r": "\r", "t": "\t", "b": "", "f": ""}[m.group(1)], s)
    return re.sub(r"\\[0-7]{1,3}", " ", s)


def extract_pdf(path):
    """Try pdftotext, else inflate content streams and pull Tj/TJ text."""
    p = Path(path)
    import shutil as _shutil
    exe = _shutil.which("pdftotext")
    if exe:
        try:
            import subprocess
            got = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(p), "-"],
                                 capture_output=True, timeout=120)
            if got.returncode == 0 and got.stdout.strip():
                body = got.stdout.decode("utf-8", "ignore")
                return body, "pdftotext", body.count("\f") + 1
        except Exception:
            pass
    try:
        data = p.read_bytes()
    except Exception:
        return "", "unreadable", 0
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    pieces = []
    for anchor in re.finditer(rb"stream\r?\n", data):
        begin = anchor.end()
        stop = data.find(b"endstream", begin)
        if stop < 0:
            continue
        blob = data[begin:stop].rstrip(b"\r\n")
        try:
            blob = zlib.decompress(blob)
        except Exception:
            try:
                blob = zlib.decompress(blob, -15)
            except Exception:
                continue
        if b"Tj" not in blob and b"TJ" not in blob:
            continue
        buf = []
        for tok in re.finditer(rb"\((?:\\.|[^\\()])*\)\s*Tj|\[(?:[^\[\]]|\\.)*\]\s*TJ|T\*|TD|Td|ET",
                               blob):
            chunk = tok.group(0)
            if chunk.endswith(b"Tj"):
                buf.append(_unescape_pdf_literal(chunk[chunk.find(b"(") + 1:chunk.rfind(b")")]))
            elif chunk.endswith(b"TJ"):
                parts = re.findall(rb"\((?:\\.|[^\\()])*\)", chunk)
                buf.append("".join(_unescape_pdf_literal(x[1:-1]) for x in parts))
            else:
                buf.append("\n")
        seg = "".join(buf)
        if seg.strip():
            pieces.append(seg)
    body = "\n\n".join(pieces)
    return body, ("raw_stream" if body.strip() else "failed"), pages


def markdown_rows(text, prefix):
    """Split Markdown into (locator, text) units keyed by current heading."""
    units, heading, seq, buf = [], "root", 0, []

    def flush():
        nonlocal buf, seq
        body = "\n".join(buf).strip()
        if body:
            seq += 1
            units.append(("%s:\u00a7%s/p%d" % (prefix, heading, seq), body))
        buf = []

    for line in text.splitlines():
        if re.match(r"^\s{0,3}#{1,6}\s", line):
            flush()
            heading = (re.sub(r"^\s{0,3}#{1,6}\s*", "", line).strip() or "untitled")
            heading = heading.replace("/", "-")[:40]
            seq, buf = 0, [line]
        elif not line.strip():
            flush()
        else:
            buf.append(line)
    flush()
    return units


def json_rows(obj, prefix, cap=4000):
    units = []

    def walk(node, ptr):
        if len(units) >= cap:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, ptr + "/" + str(k).replace("~", "~0").replace("/", "~1"))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, ptr + "/" + str(i))
        elif node is not None:
            units.append(("%s#%s" % (prefix, ptr or "#"),
                          "%s: %s" % (ptr.rsplit("/", 1)[-1], node)))

    walk(obj, "")
    return units


def table_rows(path, prefix, delim=","):
    """CSV/TSV -> header unit plus one unit per non-blank row."""
    units = []
    try:
        raw = Path(path).read_bytes().decode("utf-8-sig", "replace")
        parsed = list(csv.reader(io.StringIO(raw), delimiter=delim))
    except Exception:
        return units, None
    if not parsed:
        return units, None
    header = parsed[0]
    units.append(("%s:header" % prefix, " | ".join(header)))
    for idx, row in enumerate(parsed[1:], start=1):
        if any(cell.strip() for cell in row):
            units.append(("%s:r%d" % (prefix, idx), " | ".join(row)))
    return units, header


def docx_rows(path, prefix):
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
    except Exception:
        return []
    xml = re.sub(r"</w:p>", "\n\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", " ", xml)
    return rows_of(html.unescape(re.sub(r"<[^>]+>", "", xml)), prefix)


def xlsx_rows(path, prefix, cap=3000):
    units = []
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            shared = []
            if "xl/sharedStrings.xml" in names:
                sheet = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
                shared = [html.unescape(re.sub(r"<[^>]+>", "", m))
                          for m in re.findall(r"<si>([\s\S]*?)</si>", sheet)]
            sheets = sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
            if not sheets:
                return units
            sheet = z.read(sheets[0]).decode("utf-8", "ignore")
    except Exception:
        return units
    for ridx, row in enumerate(re.finditer(r"<row\b[^>]*>([\s\S]*?)</row>", sheet), start=1):
        cells = []
        for cell in re.finditer(r"<c\b([^>]*)>([\s\S]*?)</c>", row.group(1)):
            attrs, inner = cell.group(1), cell.group(2)
            raw = re.search(r"<v>([\s\S]*?)</v>", inner)
            val = raw.group(1) if raw else ""
            if 't="s"' in attrs and str(val).isdigit():
                pos = int(val)
                val = shared[pos] if 0 <= pos < len(shared) else val
            else:
                inline = re.search(r"<is>[\s\S]*?<t[^>]*>([\s\S]*?)</t>", inner)
                if inline:
                    val = html.unescape(re.sub(r"<[^>]+>", "", inline.group(1)))
            cells.append(html.unescape(re.sub(r"<[^>]+>", "", str(val))))
        if any(c.strip() for c in cells):
            units.append(("%s:r%d" % (prefix, ridx), " | ".join(cells)))
        if len(units) >= cap:
            break
    return units


def harvest_material(path, rel, prefix):
    """Return the index record for one material file."""
    p = Path(path)
    kind = detect_kind(p)
    rec = {"path": str(p), "rel": rel, "prefix": prefix, "kind": kind,
           "bytes": 0, "units": [], "quality": "ok", "notes": []}
    try:
        rec["bytes"] = p.stat().st_size
    except Exception:
        pass
    try:
        if kind == "pdf":
            body, mode, pages = extract_pdf(p)
            rec["pages"] = pages
            rec["notes"].append("pdf_text:%s" % mode)
            if mode in ("raw_stream", "failed") and len(body.strip()) < 200:
                rec["quality"] = "low_text"
                rec["notes"].append("PDF text layer unusable; render or OCR before quoting pages")
            if mode == "pdftotext":
                for pno, page in enumerate(body.split("\f"), start=1):
                    if not page.strip():
                        continue
                    for loc, chunk in rows_of(page, "%s:p%d" % (prefix, pno)):
                        rec["units"].append((loc.replace(":p%d:" % pno, ":pg%d/" % pno), chunk))
            else:
                rec["units"] = rows_of(body, prefix)
        elif kind == "docx":
            rec["units"] = docx_rows(p, prefix)
        elif kind == "xlsx":
            rec["units"] = xlsx_rows(p, prefix)
            rec["notes"].append("xlsx: first worksheet only; formulas read as cached values")
        elif kind in ("csv", "tsv"):
            units, header = table_rows(p, prefix, "\t" if kind == "tsv" else ",")
            rec["units"], rec["columns"] = units, header or []
        elif kind in ("json", "ipynb"):
            obj, err = read_json(p)
            if obj is None:
                rec["quality"] = "unparsed"
                rec["notes"].append(err or "json parse failed")
            else:
                rec["units"] = json_rows(obj, prefix)
        elif kind == "md":
            rec["units"] = markdown_rows(p.read_text(encoding="utf-8-sig", errors="replace"),
                                         prefix)
        elif kind == "text":
            rec["units"] = rows_of(p.read_text(encoding="utf-8-sig", errors="replace"),
                                   prefix)
        elif kind == "image":
            rec["quality"] = "no_ocr"
            rec["notes"].append("image material: pixels are not read; quote external OCR text")
        else:
            rec["quality"] = "unsupported"
            rec["notes"].append("unrecognised kind %s" % kind)
    except Exception as exc:
        rec["quality"] = "unparsed"
        rec["notes"].append("%s:%s" % (type(exc).__name__, exc))
    if len(rec["units"]) > 4000:
        rec["units"] = rec["units"][:4000]
        rec["notes"].append("unit list truncated at 4000")
    return rec


# ------------------------------------------------------------------ evidence
def flatten_index(index):
    flat = []
    for mat in index.get("materials", []):
        for loc, text in mat.get("units", []):
            flat.append({"source_id": mat["id"], "locator": loc, "text": text,
                         "match_text": fade(text), "kind": mat["kind"]})
    return flat


def hits_for(flat, quote, source_id=None):
    """Normalised substring search; returns every matching unit."""
    needle = fade(quote)
    if len(needle) < 4:
        return []
    found = []
    for unit in flat:
        if source_id and unit["source_id"] != source_id:
            continue
        if needle and needle in unit["match_text"]:
            found.append({"source_id": unit["source_id"], "locator": unit["locator"],
                          "method": "normalized_exact"})
    return found


def validate_evidence(flat, ev):
    """Check one evidence object. Returns (accepted, hits, reason)."""
    if not isinstance(ev, dict):
        return False, [], "evidence_not_object"
    quote = ev.get("quote") or ""
    if not str(quote).strip():
        return False, [], "missing_quote"
    found = hits_for(flat, str(quote), ev.get("source_id") or None)
    if not found:
        return False, [], "quote_not_found"
    if ev.get("source_id") and not any(h["source_id"] == ev["source_id"] for h in found):
        return False, found, "source_mismatch"
    if ev.get("locator"):
        want = fade(str(ev["locator"]))
        exact = [h for h in found if fade(h["locator"]) == want]
        return (True, exact, "ok") if exact else (True, found, "locator_differs_from_index")
    return True, found[:3], "ok"


# ------------------------------------------------------------------ tolerance
def standard_tolerance(metric, reported):
    """Pre-run default: 2% relative plus 0.5% of the reported magnitude."""
    abs_tol = 0.0
    if isinstance(reported, (int, float)) and reported != 0:
        abs_tol = round(abs(reported) * 0.005, 12)
    return {"abs_tol": abs_tol, "rel_tol": 0.02,
            "basis": "pre-run default: 2% relative band, plus 0.5% of the reported "
                     "magnitude to absorb rounding"}


def within_tolerance(observed, reported, abs_tol, rel_tol):
    if not isinstance(observed, (int, float)) or not isinstance(reported, (int, float)):
        return {"within_tolerance": None, "abs_dev": None, "rel_dev": None,
                "note": "non_numeric"}
    delta = abs(float(observed) - float(reported))
    ratio = (delta / abs(float(reported))) if reported else None
    inside = (abs_tol is not None and delta <= float(abs_tol) + 1e-15) or \
             (ratio is not None and rel_tol is not None
              and ratio <= float(rel_tol) + 1e-15)
    return {"within_tolerance": bool(inside), "abs_dev": round(delta, 12),
            "rel_dev": None if ratio is None else round(ratio, 8)}


# ------------------------------------------------------------------ contract
SLOT_RULES = [
    (("repro", "\u590d\u73b0"), "reproduction"),
    (("compar", "diff", "\u5bf9\u6bd4", "\u5dee\u5f02"), "comparison"),
    (("attribut", "\u5f52\u56e0", "cause"), "attribution"),
    (("toler", "\u5bb9\u5dee"), "tolerance"),
    (("run", "exec", "\u8fd0\u884c", "command"), "runs"),
    (("param", "\u53c2\u6570", "hyper", "\u8d85\u53c2"), "params"),
    (("environ", "\u73af\u5883"), "environment"),
    (("evid", "\u8bc1\u636e", "quote", "citation", "locator"), "evidence"),
    (("conclusion", "verdict", "\u7ed3\u8bba", "\u5224\u5b9a"), "conclusion"),
    (("uncert", "\u4e0d\u786e\u5b9a"), "uncertainty"),
    (("pending", "human", "\u4eba\u5de5", "\u63a5\u7ba1"), "pending_human"),
    (("gap", "missing", "\u7f3a\u53e3", "\u7f3a\u5931"), "gaps"),
    (("plan", "step", "checklist", "\u6d41\u7a0b", "\u6e05\u5355"), "plan"),
    (("claim", "\u7ed3\u8bba\u70b9"), "claims"),
    (("summary", "\u6458\u8981", "answer", "\u7b54\u6848", "abstract"), "summary"),
    (("source", "\u6765\u6e90", "material", "\u6750\u6599"), "sources"),
    (("status", "\u72b6\u6001"), "status"),
    (("result", "\u7ed3\u679c"), "reproduction"),
]


def slot_for(key, slots):
    """Resolve a contract key to a payload slot, or NO_MATCH."""
    lowered = (key or "").lower()
    for needles, name in SLOT_RULES:
        if any(n in lowered for n in needles) and name in slots:
            return slots[name]
    return NO_MATCH


def apply_contract(template, slots, unmapped, key=""):
    """Fill an output_contract template without renaming its keys."""
    if isinstance(template, dict):
        if template:
            return {k: apply_contract(v, slots, unmapped, k) for k, v in template.items()}
        val = slot_for(key, slots)
        return {} if val is NO_MATCH else val
    val = slot_for(key, slots)
    if isinstance(template, list):
        if val is NO_MATCH:
            if key:
                unmapped.append(key)
            return []
        return val if isinstance(val, list) else [val]
    if val is NO_MATCH:
        if key:
            unmapped.append(key)
        return None
    return val


# ------------------------------------------------------------------ selftest
def selftest():
    bad = []
    if fade("A  b\n c") != "a b c":
        bad.append("fade")
    unit = [{"source_id": "m1", "locator": "m1:p2",
             "text": "Top-1 accuracy 76.5% on ImageNet",
             "match_text": fade("Top-1 accuracy 76.5% on ImageNet"), "kind": "text"}]
    ok, hits, why = validate_evidence(unit, {"quote": "accuracy 76.5%", "source_id": "m1"})
    if not (ok and hits and why == "ok"):
        bad.append("quote_hit")
    ok2, _, why2 = validate_evidence(unit, {"quote": "accuracy 99.9%"})
    if ok2 or why2 != "quote_not_found":
        bad.append("quote_miss")
    ok3, _, why3 = validate_evidence(unit, {"quote": "accuracy 76.5%", "source_id": "m9"})
    if ok3 or why3 != "quote_not_found":
        bad.append("quote_wrong_source")
    near = within_tolerance(76.8, 76.5, 0.3825, 0.02)
    if not near["within_tolerance"]:
        bad.append("tolerance_pass")
    far = within_tolerance(80.0, 76.5, 0.3825, 0.02)
    if far["within_tolerance"] is not False:
        bad.append("tolerance_fail")
    if within_tolerance("n/a", 1.0, 0.1, 0.1)["within_tolerance"] is not None:
        bad.append("tolerance_non_numeric")
    slots = {"status": "ok", "summary": "s", "runs": [1], "evidence": [{"x": 1}],
             "reproduction": {"v": 1}}
    unmapped = []
    filled = apply_contract({"status": None, "reproduction_record": None,
                             "run_log": [], "evidence": [], "zzz_unknown": None},
                            slots, unmapped)
    if filled["status"] != "ok" or filled["reproduction_record"] != {"v": 1}:
        bad.append("contract")
    if filled["run_log"] != [1] or "zzz_unknown" not in unmapped:
        bad.append("contract_unknown")
    if not (isinstance(filled["evidence"], list) and filled["evidence"]):
        bad.append("contract_evidence")
    print("selftest: %s" % ("PASS" if not bad else "FAIL " + ", ".join(bad)))
    return 0 if not bad else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Audit helpers: material extraction, quote lookup, tolerance, contract")
    ap.add_argument("--selftest", action="store_true", help="run built-in assertions")
    args = ap.parse_args(argv)
    if args.selftest:
        sys.exit(selftest())
    ap.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()
