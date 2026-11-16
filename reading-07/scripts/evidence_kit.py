"""evidence_kit.py — corpus plumbing for the claim-evidence auditor.

Pure standard-library helpers: read heterogeneous source files, cut them into
locator-tagged units, split sentences, expose cue/direction tests, find the
claims list, and serialise evidence cards. Verdict policy lives in
audit_claims.py; this module only supplies text primitives and I/O.
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
import zipfile
import zlib
from pathlib import Path

# --- tunables (keep in sync with references/support-levels.md) -----------------
UNIT_CAP = 6000
STRONG_CUT = 0.72          # at or above: full support is possible
WEAK_CUT = 0.40            # below: merely on-topic
ANCHOR_PENALTY = 0.35      # off-target multiplier when numeric anchors miss

# --- field aliases used when walking arbitrary JSON ---------------------------
PROSE_KEYS = ("text", "content", "paragraph", "para", "sentence", "body", "abstract",
              "caption", "quote", "chunk", "passage", "value")
ID_FIELDS = ("paragraph_id", "para_id", "pid", "para", "id", "chunk_id", "unit_id")
SECT_FIELDS = ("section", "section_title", "heading", "sec", "chapter")
PAGE_FIELDS = ("page", "page_number", "p", "page_no", "pdf_page")

CJK_BLOCK = re.compile(r"[\u4e00-\u9fff]+")
LATIN_TOKEN = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")
QUANTITY = re.compile(
    r"\d+(?:[.,]\d+)*(?:\s?(?:%|‰|mg|kg|g|mm|cm|km|nm|μm|µm|ml|l|ms|min|h|s|k|pa|kpa|mpa|gpa|"
    r"hz|khz|ghz|ev|kj|mol|mmol|°c|℃))?", re.I)

CJK_FILLER = set("的了和与及或在是对为把被而并且也等就都还又很更最则其之该此是我方可将能会从对向于以但与或如若虽因由于这那些个中上下")
LATIN_FILLER = {"the", "and", "for", "with", "that", "this", "these", "those", "was", "were",
                "are", "have", "has", "had", "from", "not", "but", "than", "into", "there",
                "which", "while", "also", "such", "can", "may", "been", "being", "its", "they",
                "them", "however", "used"}
NEGATIVE_IDIOMS = ("不同", "不断", "不仅", "不少", "不但", "非但")   # not real negations

SIGNAL_PATTERNS = {
    "up": r"高于|更高|增大|增加|上升|提高|增强|促进|多于|超过|优于|higher|greater|larger|increas|enhanc|improve|promot|superior|more than|exceed",
    "down": r"低于|更低|减小|降低|降至|下降至|缩短|减弱|抑制|少于|劣于|lower|smaller|decreas|reduc|inhibit|less than|inferior|suppress|declin",
    "neg": r"不|未|没有|无法|并非|不能|not\b|no\b|did not|was not|were not|without|none\b|fail",
    "sig": r"显著|极显著|显著性|significant|significantly|p\s*[<=]\s*0?\.\d+|95%\s*ci|置信区间|confidence interval",
    "scope": r"所有|全部|任何|均|仅|只|总是|从不|普遍|every|all\b|only\b|always|never|exclusively|solely|universally",
    "compare": r"高于|低于|优于|劣于|大于|小于|相比|更高|更低|多于|少于|higher than|lower than|greater than|less than|compared (?:with|to)|versus|vs\.?|than\b|比",
    "causal": r"导致|引起|造成|因为|由于|因此|从而|使得|归因|驱动|决定|caus|lead(?:s|ing)? to|due to|result(?:s|ed)? in|because|attribut|driven by|responsible for|induced",
}
SIGNAL_RES = {name: re.compile(pat, re.I) for name, pat in SIGNAL_PATTERNS.items()}

HARD_ANCHOR = re.compile(
    r"[a-z]{1,2}\d{3,4}(?!\d)|\b\d{4}(?!\d)|\d+(?:[.,]\d+)?\s?(?:°c|℃|%|mpa|gpa|mm|nm|μm|kg|g|h)\b",
    re.I)
INNER_SPACE = re.compile(r"[ \t\u3000\xa0]+")
SENTENCE_CUT = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")


# ================================================================ text helpers
def tidy_space(text):
    """Collapse intra-line blanks but keep newlines (paragraph boundaries matter)."""
    merged = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return INNER_SPACE.sub(" ", merged).strip()


def squeeze(text):
    """One-line form used for verbatim quote matching."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def key_terms(text, limit=48):
    """Cheap content-word extractor: CJK bigrams plus Latin words, filler removed."""
    picked, seen = [], set()
    for block in CJK_BLOCK.findall(str(text or "")):
        for pos in range(len(block) - 1):
            pair = block[pos:pos + 2]
            if pair[0] in CJK_FILLER or pair[1] in CJK_FILLER or pair in seen:
                continue
            seen.add(pair)
            picked.append(pair)
    for word in LATIN_TOKEN.findall(str(text or "")):
        low = word.lower()
        if low not in LATIN_FILLER and low not in seen:
            seen.add(low)
            picked.append(low)
    return picked[:limit]


def numeric_tokens(text):
    out, seen = [], set()
    for hit in QUANTITY.finditer(str(text or "")):
        val = hit.group(0).replace(" ", "").lower()
        if val not in seen:
            seen.add(val)
            out.append(val)
    return out


def hard_anchors(text):
    """Model codes and quantity+unit anchors that distinguish one sample from another."""
    return [a.replace(" ", "").lower() for a in HARD_ANCHOR.findall(str(text or ""))]


def cue_hits(kind, text):
    return [m.group(0) for m in SIGNAL_RES[kind].finditer(str(text or ""))]


def is_negated(text):
    probe = str(text or "")
    for idiom in NEGATIVE_IDIOMS:
        probe = probe.replace(idiom, "  ")
    return bool(cue_hits("neg", probe))


def polarity(text):
    rising, falling = cue_hits("up", text), cue_hits("down", text)
    if rising and falling:
        return "mixed"
    return "up" if rising else ("down" if falling else "none")


# ================================================================ file readers
def slurp_text(path):
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return Path(path).read_text(encoding=enc)
        except Exception:
            continue
    return ""


def docx_text(path):
    try:
        with zipfile.ZipFile(path) as archive:
            blocks = []
            for name in archive.namelist():
                if re.match(r"word/(document|footnotes|endnotes)\d*\.xml$", name):
                    raw = archive.read(name).decode("utf-8", "ignore")
                    raw = re.sub(r"<w:tab[^>]*/>", "\t", re.sub(r"</w:p>", "\n\n", raw))
                    blocks.append(html.unescape(re.sub(r"<[^>]+>", "", raw)))
            return "\n".join(blocks)
    except Exception:
        return ""


def _show_operator_text(blob):
    """Pull literal strings out of PDF content streams (crude fallback only)."""
    collected = []
    escapes = {b"n": b" ", b"r": b" ", b"t": b" ", b"b": b"", b"f": b"", b"(": b"(",
               b")": b")", b"\\": b"\\"}
    for match in re.finditer(rb"\((?:\\.|[^\\()])*\)|\bTJ\b|\bTj\b|\bTd\b|\bTD\b|\bT\*", blob, re.S):
        token = match.group(0)
        if token in (b"Td", b"TD", b"T*"):
            collected.append("\n")
        elif token.startswith(b"("):
            payload = re.sub(rb"\\([nrtbf()\\])", lambda x: escapes.get(x.group(1), x.group(1)),
                             token[1:-1])
            collected.append(payload.decode("latin-1", "ignore"))
    return "".join(collected)


def pdf_text(path):
    """Return (text, note). Try pdftotext, then pypdf/PyPDF2, then raw streams."""
    import shutil
    import subprocess
    if shutil.which("pdftotext"):
        try:
            proc = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                                  capture_output=True, timeout=120)
            if proc.returncode == 0 and len(proc.stdout) > 200:
                return proc.stdout.decode("utf-8", "ignore"), ""
        except Exception:
            pass
    for module in ("pypdf", "PyPDF2"):
        try:
            loaded = __import__(module)
            body = "\n".join((pg.extract_text() or "")
                             for pg in loaded.PdfReader(str(path)).pages)
            if len(body) > 200:
                return body, ""
        except Exception:
            continue
    try:
        data, chunks = Path(path).read_bytes(), []
        for match in re.finditer(rb"stream\r?\n", data):
            stop = data.find(b"endstream", match.end())
            if stop < 0:
                continue
            raw = data[match.end():stop]
            try:
                decoded = zlib.decompress(raw)
            except Exception:
                decoded = raw
            if b"Tj" in decoded or b"TJ" in decoded:
                chunks.append(_show_operator_text(decoded))
        body = "\n".join(chunks)
        garbled = (body.count("\ufffd") > 40 or
                   (len(body) > 400 and not CJK_BLOCK.search(body)
                    and body.count(" ") > len(body) * .25))
        return body, ("low_quality_text_layer: CID encoding, quotes need re-check" if garbled else "")
    except Exception:
        return "", "pdf_read_failed"


# ================================================================ corpus units
def new_unit(source_id, text, unit_id, section, page, locator):
    loc = dict(locator)
    loc["unit_id"] = str(unit_id)
    if section:
        loc["section"] = str(section)
    if page not in (None, ""):
        try:
            loc["page"] = int(page)
        except Exception:
            loc["page_label"] = str(page)
    return {"source_id": str(source_id), "unit_id": str(unit_id), "text": tidy_space(text),
            "section": str(section) if section else None, "page": loc.get("page"),
            "locator": loc}


def locator_label(unit):
    parts = [unit["source_id"]]
    if unit.get("section"):
        parts.append("sec:" + str(unit["section"])[:40])
    if unit.get("page") is not None:
        parts.append("p.%s" % unit["page"])
    return " | ".join(parts + ["unit:" + str(unit["unit_id"])])


def json_to_units(node, source_id, pointer="", sink=None, page=None, section=None):
    sink = [] if sink is None else sink
    if len(sink) >= UNIT_CAP:
        return sink
    if isinstance(node, dict):
        prose = next((node[k] for k in PROSE_KEYS
                      if isinstance(node.get(k), str) and len(node[k].strip()) >= 25), None)
        pg = next((node[k] for k in PAGE_FIELDS if node.get(k) not in (None, "")), page)
        sec = next((node[k] for k in SECT_FIELDS
                    if isinstance(node.get(k), str) and node[k].strip()), section)
        if prose:
            uid = next((str(node[k]) for k in ID_FIELDS
                        if isinstance(node.get(k), (str, int))), None)
            ptr = pointer + "/" + (uid or str(len(sink)))
            sink.append(new_unit(source_id, prose, uid or ptr.strip("/").replace("/", "."),
                                 sec, pg, {"type": "json", "json_pointer": ptr}))
            return sink
        for key, child in node.items():
            json_to_units(child, source_id, pointer + "/" + str(key), sink, pg, sec)
    elif isinstance(node, list):
        for pos, child in enumerate(node):
            json_to_units(child, source_id, pointer + "/" + str(pos), sink, page, section)
    elif isinstance(node, str) and len(node) >= 400:
        sink.append(new_unit(source_id, node, pointer.strip("/").replace("/", ".") or "text",
                             section, page, {"type": "json", "json_pointer": pointer}))
    return sink


def prose_to_units(text, source_id, kind="text"):
    units = []
    for block in (tidy_space(x) for x in re.split(r"\n\s*\n", text or "")):
        if not block:
            continue
        if len(block) > 1600:
            spans, step = sentence_spans(block), 6
            for start in range(0, len(spans), step):
                piece = block[spans[start][0]: spans[min(start + step, len(spans)) - 1][1]]
                if piece.strip():
                    seq = len(units) + 1
                    units.append(new_unit(source_id, piece, "B%02d" % seq, None, None,
                                          {"type": kind, "block": seq}))
        else:
            seq = len(units) + 1
            units.append(new_unit(source_id, block, "B%02d" % seq, None, None,
                                  {"type": kind, "block": seq}))
        if len(units) >= UNIT_CAP:
            break
    return units


def collect_corpus(input_dir, skip=()):
    """Walk the input tree; a single unreadable file only degrades itself."""
    units, sources, degradations, gaps = [], [], [], []
    root = Path(input_dir)
    omitted = {str(Path(s).resolve()) for s in skip}
    files = (sorted(p for p in root.rglob("*") if p.is_file() and not p.name.startswith("."))
             if root.exists() else [])
    for path in files:
        if str(path.resolve()) in omitted:
            continue
        suffix, sid = path.suffix.lower(), path.stem
        try:
            if suffix == ".json":
                try:
                    got = json_to_units(json.loads(slurp_text(path) or "null"), sid)
                except Exception:
                    degradations.append({"stage": "corpus", "file": path.name,
                                         "issue": "json_parse_failed"})
                    continue
                if got:
                    units += got
                    sources.append({"source_id": sid, "path": str(path), "format": "json",
                                    "units": len(got)})
                else:
                    gaps.append({"gap": "json_without_text_fields", "file": path.name})
                continue
            if suffix == ".csv":
                rows = list(csv.reader(io.StringIO(slurp_text(path))))[:UNIT_CAP]
                got = [new_unit(sid, " | ".join(c.strip() for c in row if c.strip()),
                                "R%03d" % (idx + 1), None, None, {"type": "csv", "row": idx + 1})
                       for idx, row in enumerate(rows) if len(" | ".join(row)) >= 25]
                if got:
                    units += got
                    sources.append({"source_id": sid, "path": str(path), "format": "csv",
                                    "units": len(got)})
                continue
            if suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"):
                sources.append({"source_id": sid, "path": str(path), "format": "image", "units": 0,
                                "note": "figure pixels not machine-readable here"})
                gaps.append({"gap": "figure_pixels_not_read", "file": path.name})
                continue
            if suffix in (".xlsx", ".xlsm"):
                degradations.append({"stage": "corpus", "file": path.name,
                                     "issue": "xlsx_not_parsed_stdlib"})
                gaps.append({"gap": "xlsx_not_parsed", "file": path.name})
                continue
            note, fmt = "", {".docx": "docx", ".pdf": "pdf", ".html": "html",
                             ".htm": "html"}.get(suffix, "text")
            if fmt == "docx":
                text = docx_text(path)
            elif fmt == "pdf":
                text, note = pdf_text(path)
            elif fmt == "html":
                stripped = re.sub(r"<script.*?</script>|<style.*?</style>", " ",
                                  slurp_text(path), flags=re.S | re.I)
                text = html.unescape(re.sub(r"<[^>]+>", "\n", stripped))
            elif suffix in (".txt", ".md", ".markdown", ".rst", ".tex", ".srt", ".log", ""):
                text = slurp_text(path)
            else:
                gaps.append({"gap": "unsupported_file_type", "file": path.name})
                continue
            if note == "pdf_read_failed" or len(text.strip()) < 20:
                issue = "pdf_no_text_layer" if fmt == "pdf" else "no_extractable_text"
                degradations.append({"stage": "corpus", "file": path.name, "issue": issue,
                                     "detail": "no readable text; needs OCR or manual page reading"})
                gaps.append({"gap": issue, "file": path.name})
                continue
            if note:
                degradations.append({"stage": "corpus", "file": path.name, "issue": note})
            got = prose_to_units(text, sid, fmt)
            units += got
            sources.append({"source_id": sid, "path": str(path), "format": fmt, "units": len(got)})
        except Exception as exc:
            degradations.append({"stage": "corpus", "file": path.name, "issue": "unhandled",
                                 "detail": "%s: %s" % (type(exc).__name__, exc)})
    return units[:UNIT_CAP], sources, degradations, gaps


# ================================================================ sentence spans
def sentence_spans(text):
    body, spans = text or "", []
    for match in SENTENCE_CUT.finditer(body):
        start, stop = match.start(), match.end()
        while start < stop and body[start] in " \t，,":
            start += 1
        if stop - start >= 2:
            spans.append((start, stop))
    return spans or [(0, len(body))]


def span_windows(unit, widths=(1, 2)):
    spans = unit["sentences"]
    for width in widths:
        if width > len(spans):
            continue
        for pos in range(0, len(spans) - width + 1):
            yield {"unit": unit,
                   "text": unit["text"][spans[pos][0]: spans[pos + width - 1][1]]}


def locate_quote(quote, units, min_chars=8):
    needle = squeeze(quote)
    if len(needle) < min_chars:
        return None
    for unit in units:
        if needle in squeeze(unit["text"]):
            return unit
    return None


# ================================================================ claim discovery
def discover_claims(input_dir, case=None):
    """Return (claims, origin, gaps). Every claim is a QUESTION, never a fact to copy."""
    root = Path(input_dir)
    found, origin, gaps = None, None, []
    for name in ("claims-to-verify.json", "claims_to_verify.json", "claims.json"):
        candidate = root / name
        if candidate.exists():
            try:
                found, origin = json.loads(slurp_text(candidate) or "null"), str(candidate)
                break
            except Exception:
                gaps.append({"gap": "claims_json_parse_failed", "file": name})
    if not found and isinstance(case, dict):
        for key in ("claims", "claims_to_verify", "statements", "claims_to_check",
                    "claim_list", "audit_claims"):
            if isinstance(case.get(key), (list, dict)):
                found, origin = case[key], "case.json::%s" % key
                break
    if not found and isinstance(case, dict):
        nested = case.get("input") if isinstance(case.get("input"), dict) else {}
        for key in ("claims", "claims_to_verify", "statements"):
            if isinstance(nested.get(key), (list, dict)):
                found, origin = nested[key], "case.json::input.%s" % key
                break
    if isinstance(found, dict):
        for key in ("claims", "items", "records", "data"):
            if isinstance(found.get(key), list):
                found = found[key]
                break
        else:
            found = [found] if found else []
    claims = []
    for idx, item in enumerate(found or []):
        cid, text, extra = None, None, {}
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            cid = next((str(item[k]) for k in ("claim_id", "cid", "id", "claim_no", "no")
                        if item.get(k) not in (None, "")), None)
            text = next((item[k] for k in ("claim_text", "text", "statement", "claim",
                                           "sentence", "quote", "content")
                         if isinstance(item.get(k), str) and item[k].strip()), None)
            extra = {k: v for k, v in item.items()
                     if k not in ("claim_text", "text", "statement", "claim", "sentence")}
        if text and str(text).strip():
            claims.append({"claim_id": cid or "C%d" % (idx + 1), "claim_text": tidy_space(text),
                           "meta": extra, "input_index": idx})
    return claims, origin, gaps


# ================================================================ verdict assembly
def combine_verdicts(subclaims):
    levels = [s["verdict"] for s in subclaims]
    if not levels:
        return "insufficient_evidence"
    if any(s.get("alternative") for s in subclaims):
        return "partially_supported"
    if "contradicted" in levels:
        return "contradicted" if "supported" not in levels else "partially_supported"
    if all(level == "supported" for level in levels):
        return "supported"
    return ("insufficient_evidence" if all(level == "insufficient_evidence" for level in levels)
            else "partially_supported")


def conflict_block(subclaims):
    for sub in subclaims:
        opposite = sub.get("alternative")
        if not opposite:
            continue
        main_ev = sub["evidence"][0] if sub["evidence"] else {}
        winner = opposite.get("win") or {}
        winner_unit = winner.get("unit") or {}
        return {"conflict": True, "sub_id": sub["sub_id"],
                "qualified_verdict": sub["verdict"],
                "both_sides": [
                    {"side": "A", "source_id": main_ev.get("source_id"),
                     "location": main_ev.get("locator"), "quote": main_ev.get("quote")},
                    {"side": "B",
                     "source_id": winner_unit.get("source_id") or opposite.get("source_id"),
                     "location": dict(winner_unit["locator"]) if winner_unit
                     else opposite.get("locator"),
                     "quote": winner.get("text") or opposite.get("quote")}],
                "note": "两侧定位并列，未折中；条件差异需人工确认"}
    return {"conflict": False, "both_sides": []}


def card_jsonl(verifications):
    kept = ("source_id", "unit_id", "locator", "label", "quote", "supports", "role")
    rows = []
    for entry in verifications:
        for sub in entry["sub_claims"]:
            rows.append(json.dumps(dict({
                "card_id": "EV-%s-%s" % (entry["claim_id"], sub["sub_id"]),
                "claim_id": entry["claim_id"], "claim_text": entry["claim_text"],
                "sub_text": sub["text"], "type": sub["type"],
                "required_evidence_type": sub["required_evidence_type"],
                "verdict": sub["verdict"], "verdict_confidence": sub["verdict_confidence"],
                "comparator": sub["comparator"], "negation": sub["negation"],
                "significance": sub["significance"], "conditions": sub["conditions"],
                "evidence": [{k: e.get(k) for k in kept} for e in sub["evidence"]],
                "rationale": sub["rationale"], "limitations": sub["limitations"],
                "counter_evidence_searched": sub["counter_evidence_searched"],
                "search_scope": sub["search_scope"],
                "conflict": bool(sub.get("alternative"))}, sub_id=sub["sub_id"]),
                ensure_ascii=False))
    return rows


def render_report(target_dir, res):
    """Human-readable digest: claim -> sub-claim -> verdict -> verbatim quote."""
    lines = ["# 证据核验 %s (%s)" % (res["case_id"], res["status"]), "", "## 判定一览"]
    for entry in res["result"].get("verifications", []):
        lines.append("- %s %s → %s" % (entry["claim_id"], entry["claim_text"][:80],
                                       entry["verdict"]))
        lines += ["    - %s [%s] %s" % (s["sub_id"], s["type"], s["verdict"])
                  for s in entry["sub_claims"]]
        lines += ["      > %s" % e.get("quote") for s in entry["sub_claims"]
                  for e in s["evidence"]]
    audit = res.get("self_check") or {}
    if audit:
        lines += ["", "## 结构自检", "结果：%s（claims=%s, quotes=%s）"
                  % ("通过" if audit.get("passed") else "发现问题",
                     audit.get("claims_checked"), audit.get("quotes_checked"))]
        lines += ["- [%s] %s — %s" % ("ok" if c["ok"] else "FAIL", c["check"], c["detail"])
                  for c in audit.get("checks", [])]
    (target_dir / "verification_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
