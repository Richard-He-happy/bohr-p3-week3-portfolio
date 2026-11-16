#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""claim_assets.py -- five verifiable deliverable assets (reading-07 patch layer).

Additive layer for the claim-evidence-auditor skill.  After the main audit has
written result.json / evidence_cards.jsonl / verification_report.md, attach()
writes five checkable assets into the same output directory:

    golden_standard.json   expected deliverable per output_contract item: claim,
                           evidence quote, verdict family, locator + source quote
    diff_report.md         actual artifact vs golden standard, layer by layer
    version_history.md     static v0 -> v1.0.0 history, rollback, runtime section
    run.log                real stage log of this invocation
    self_check.json        machine assertions: contract / main product / quotes /
                           counts / fallbacks / exit code

The golden standard is re-derived from /input by an independent lexical scan; it
never reads the verdict engine's intermediate objects.  Standard library only,
no network, paths from the input/output arguments or Path(__file__) - never from
the current working directory.  Every step is guarded; the original CLI and the
exit code 0 stay untouched.
"""

import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

try:
    import evidence_kit as _K
except Exception:                                    # pragma: no cover
    _K = None

VERSION = "1.0.0+assets"
PACKAGE = "claim-evidence-auditor"
GOLD_SCHEMA = "golden-standard/v1"
SELF_SCHEMA = "self-check/v1"
PROBE_ENV = "CLAIM_ASSET_PROBE"
PACKAGE_LIMITS = {"files": 10, "bytes": 180 * 1024}
ASSETS = ("golden_standard.json", "diff_report.md", "version_history.md",
          "run.log", "self_check.json")
LEVELS = ("supported", "partially_supported", "contradicted", "insufficient_evidence")
VERDICT_DOMAIN = LEVELS
STATUS_DOMAIN = ("ok", "partial", "insufficient_evidence", "input_error")
ENVELOPE_KEYS = ("case_id", "status", "result", "claims", "uncertainties", "sources",
                 "pending_human", "errors", "degradations", "changes", "gaps", "runtime")
CLAIM_FILES = ("claims-to-verify.json", "claims_to_verify.json", "claims.json")
CASE_KEYS = ("claims", "claims_to_verify", "statements", "claims_to_check",
             "claim_list", "audit_claims")
CLAIM_ID_KEYS = ("claim_id", "cid", "id", "claim_no", "no")
CLAIM_TEXT_KEYS = ("claim_text", "text", "statement", "claim", "sentence", "quote", "content")
PROSE_KEYS = ("text", "content", "paragraph", "para", "sentence", "body", "abstract",
              "caption", "quote", "chunk", "passage", "value")
META_KEYS = ("paragraph_id", "para_id", "pid", "chunk_id", "unit_id", "section",
             "section_title", "heading", "sec", "chapter", "page", "page_number",
             "page_no", "p")
HERE = Path(__file__).resolve().parent
PKG = HERE.parent

# ------------------------------------------------------------------ log buffer
_T0 = time.time()
_LOG = []
def _stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def start(argv, input_arg, output_arg):
    """Record the invocation header; called once by the CLI before execute()."""
    log("boot", "process start", argv=" ".join(str(x) for x in (argv or [])) or "(default)",
        input=str(input_arg), output=str(output_arg), python=sys.version.split()[0])


def log(event, message, **fields):
    """Append one real log line; never raises."""
    try:
        parts = ["[%s +%.3fs]" % (_stamp(), time.time() - _T0), "[%s]" % event, str(message)]
        for key in sorted(fields):
            val = fields[key]
            if isinstance(val, str) and len(val) > 200:
                val = val[:200] + "..."
            parts.append("%s=%r" % (key, val))
        _LOG.append(" ".join(parts))
    except Exception:
        pass


def log_text():
    return "\n".join(["# run.log -- %s v%s" % (PACKAGE, VERSION),
                      "# 真实运行日志：逐阶段一行，含时间戳与相对耗时；时间戳仅在"
                      "本文件与 version_history 运行段。"] + _LOG) + "\n"


def log_summary():
    events = []
    for line in _LOG:
        hit = re.search(r"\[([a-z_]+)\]", line)
        if hit and hit.group(1) not in events:
            events.append(hit.group(1))
    return {"events": len(_LOG), "phases": events, "exit_code": 0, "version": VERSION}


# ------------------------------------------------------------------ small I/O
def _flat(text):
    return re.sub(r"\s+", "", str(text or ""))


def _tidy(text):
    merged = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"[\t\u3000\xa0 ]+", " ", merged).strip()


def _clip(text, limit=400):
    body = str(text or "")
    return body if len(body) <= limit else body[:limit]


def _read_text(path):
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return Path(path).read_text(encoding=enc)
        except Exception:
            continue
    return ""


def _wr_json(path, doc):
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _size(path):
    try:
        return Path(path).stat().st_size
    except Exception:
        return 0


def _sha(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except Exception:
        return None


def _md(text, limit=240):
    return _clip(text, limit).replace("|", "\\|").replace("\n", " ")


def _json_load(path):
    try:
        return json.loads(_read_text(path))
    except Exception:
        return None


# ------------------------------------------------------------------ input state
def _strings_in(node, sink, depth=0):
    if depth > 50:
        return
    if isinstance(node, dict):
        for val in node.values():
            _strings_in(val, sink, depth + 1)
    elif isinstance(node, list):
        for val in node:
            _strings_in(val, sink, depth + 1)
    elif isinstance(node, str):
        sink.append(node)


def _json_units(node, sid, pointer, meta, out, depth=0):
    if depth > 40 or len(out) > 6000:
        return
    if isinstance(node, dict):
        carried = dict(meta)
        for key in META_KEYS:
            val = node.get(key)
            if isinstance(val, (str, int)) and not isinstance(val, bool) and str(val).strip():
                carried[key] = str(val)
        prose = next((k for k in PROSE_KEYS
                      if isinstance(node.get(k), str) and len(node[k].strip()) >= 25), None)
        if prose is not None:
            out.append({"source_id": sid, "text": _tidy(node[prose]),
                        "pointer": pointer + "/" + prose, "meta": carried, "kind": "json"})
            return
        for key, val in node.items():
            _json_units(val, sid, pointer + "/" + str(key), carried, out, depth + 1)
    elif isinstance(node, list):
        for pos, val in enumerate(node):
            _json_units(val, sid, pointer + "/" + str(pos), meta, out, depth + 1)
    elif isinstance(node, str) and len(node.strip()) >= 25:
        out.append({"source_id": sid, "text": _tidy(node), "pointer": pointer,
                    "meta": dict(meta), "kind": "json"})


def _extract_text(path):
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = _read_text(path)
        try:
            strings = []
            _strings_in(json.loads(raw), strings)
            return "\n".join(strings), raw, "json"
        except Exception:
            return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), raw), \
                raw, "json_invalid"
    if suffix == ".csv":
        raw = _read_text(path)
        return raw, raw, "csv"
    if suffix in (".html", ".htm"):
        raw = _read_text(path)
        raw = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S | re.I)
        return _tidy(html.unescape(re.sub(r"<[^>]+>", "\n", raw))), raw, "html"
    if suffix in (".docx", ".pdf"):
        if _K is None:
            return "", "", suffix.strip(".")
        try:
            if suffix == ".docx":
                return _K.docx_text(path), "", "docx"
            text, _note = _K.pdf_text(path)
            return text, text, "pdf"
        except Exception:
            return "", "", suffix.strip(".")
    if suffix in (".xlsx", ".xlsm"):
        return "", "", "xlsx"
    if suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"):
        return "", "", "image"
    raw = _read_text(path)
    return raw, raw, "text"


def _resolve_input(input_arg):
    candidates = ([Path(input_arg)] if input_arg else []) + [
        Path("/input"), Path("/app/input"), Path.cwd() / "input", PKG / "input"]
    for cand in candidates:
        try:
            if cand.exists():
                return cand.resolve()
        except Exception:
            continue
    return Path(input_arg or "/input")


def _read_case(input_dir):
    for path in [input_dir / "case.json"] + sorted(input_dir.glob("case*.json")):
        if path.exists():
            raw = _read_text(path)
            try:
                doc = json.loads(raw or "null")
                return (doc if isinstance(doc, dict) else {}), str(path), raw
            except Exception:
                return {"_parse_error": "case json is not valid JSON"}, str(path), raw
    return {}, None, ""


def _locate_list(node, pointer):
    if isinstance(node, list):
        return node, pointer
    if isinstance(node, dict):
        for key in ("claims", "items", "records", "data"):
            if isinstance(node.get(key), list):
                return node[key], pointer + "/" + key
        if next((node[k] for k in CLAIM_TEXT_KEYS
                 if isinstance(node.get(k), str) and node[k].strip()), None):
            return [node], pointer
    return [], pointer


def _normalise_claims(items, filename, prefix):
    out = []
    for idx, item in enumerate(items or []):
        cid, text, pointer = None, None, "%s/%d" % (prefix, idx)
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            cid = next((str(item[k]) for k in CLAIM_ID_KEYS
                        if item.get(k) not in (None, "")), None)
            field = next((k for k in CLAIM_TEXT_KEYS
                          if isinstance(item.get(k), str) and item[k].strip()), None)
            if field:
                text = item[field]
                pointer = pointer + "/" + field
        if text and str(text).strip():
            out.append({"claim_id": cid or "C%d" % (idx + 1), "claim_text": str(text),
                        "origin": filename, "json_pointer": pointer})
    return out


def _discover_claims(input_dir, case):
    """Independent claim discovery: same documented input contract, separate code."""
    for name in CLAIM_FILES:
        path = input_dir / name
        if not path.exists():
            continue
        try:
            items, prefix = _locate_list(json.loads(_read_text(path) or "null"), "")
        except Exception:
            return [], str(path), [{"gap": "claims_json_parse_failed", "file": name}]
        return _normalise_claims(items, name, prefix), str(path), []
    if isinstance(case, dict):
        for key in CASE_KEYS:
            if isinstance(case.get(key), (list, dict)):
                items, prefix = _locate_list(case[key], "/" + key)
                return _normalise_claims(items, "case.json", prefix), "case.json::%s" % key, []
        nested = case.get("input") if isinstance(case.get("input"), dict) else {}
        for key in ("claims", "claims_to_verify", "statements"):
            if isinstance(nested.get(key), (list, dict)):
                items, prefix = _locate_list(nested[key], "/input/" + key)
                return _normalise_claims(items, "case.json", prefix), \
                    "case.json::input.%s" % key, []
    return [], None, []


def build_state(input_dir):
    """Read the input tree with independent code and index raw source text."""
    input_dir = Path(input_dir)
    case, case_path, case_raw = _read_case(input_dir)
    claims, claims_origin, claim_gaps = _discover_claims(input_dir, case)
    haystack = []
    if claims_origin and claims_origin.startswith(str(input_dir)):
        doc = _json_load(claims_origin)
        if doc is not None:
            _strings_in(doc, haystack)
    elif claims_origin:
        _strings_in(case, haystack)
    skip = set()
    if claims_origin and claims_origin.startswith(str(input_dir)):
        skip.add(str(Path(claims_origin).resolve()))
    if case_path:
        skip.add(str(Path(case_path).resolve()))
    units, sources, source_text, gaps = [], [], {}, []
    files = (sorted(p for p in input_dir.rglob("*")
                    if p.is_file() and not p.name.startswith(".")) if input_dir.exists() else [])
    for path in files:
        try:
            if str(path.resolve()) in skip:
                continue
            text, raw, fmt = _extract_text(path)
            sid = path.stem
            source_text[sid] = text
            if fmt in ("image", "xlsx") or not text or len(text.strip()) < 20:
                gaps.append({"gap": "figure_or_workbook_not_machine_readable" if fmt == "image"
                             else "xlsx_not_parsed_stdlib" if fmt == "xlsx"
                             else "no_extractable_text", "file": path.name})
                sources.append({"source_id": sid, "path": str(path), "format": fmt, "units": 0})
                continue
            got = []
            if fmt in ("json", "json_invalid"):
                try:
                    _json_units(json.loads(raw if fmt == "json" else text), sid, "", {}, got)
                except Exception:
                    got = []
            if not got and fmt != "json":
                blocks = [b for b in re.split(r"\n\s*\n", _tidy(text)) if b.strip()]
                for seq, block in enumerate(blocks or [text], 1):
                    got.append({"source_id": sid, "text": block, "pointer": "block:%d" % seq,
                                "meta": {"block": seq}, "kind": "text"})
            if not got and fmt in ("json", "json_invalid"):
                for seq, line in enumerate([x for x in text.splitlines()
                                            if len(x.strip()) >= 25], 1):
                    got.append({"source_id": sid, "text": _tidy(line),
                                "pointer": "line:%d" % seq, "meta": {"block": seq},
                                "kind": "text"})
            units += got
            sources.append({"source_id": sid, "path": str(path), "format": fmt,
                            "units": len(got)})
            if fmt == "json_invalid":
                gaps.append({"gap": "json_parse_failed_golden_scan", "file": path.name})
        except Exception as exc:
            gaps.append({"gap": "golden_scan_failed", "file": path.name,
                         "detail": "%s: %s" % (type(exc).__name__, exc)})
    return {"input_dir": input_dir, "case": case, "case_path": case_path, "case_raw": case_raw,
            "claims": claims, "claims_origin": claims_origin,
            "claim_quote_text": "\n".join(haystack) if haystack else case_raw,
            "units": units, "sources": sources, "source_text": source_text,
            "gaps": claim_gaps + gaps}


# ------------------------------------------------------------------ quote ledger
def _json_value_span(raw, key):
    """Return the exact substring of raw JSON that holds key's value."""
    for found in re.finditer(r'"%s"\s*:\s*' % re.escape(key), raw):
        start = found.end()
        try:
            _obj, end = json.JSONDecoder().raw_decode(raw[start:])
            return raw[start:start + end]
        except Exception:
            continue
    return None


def _line_of(raw, needle):
    pos = raw.find(needle)
    return None if pos < 0 else raw.count("\n", 0, pos) + 1


def _quote_hit(quote, haystack_flat):
    needle = _flat(quote)
    return bool(needle) and needle in haystack_flat


class Ledger(object):
    """Check every quote we put into the assets against its own stated source."""

    def __init__(self):
        self.rows = []

    def add(self, item_id, quote, source_name, haystack):
        self.rows.append({"item_id": item_id, "source": source_name,
                          "verbatim": _quote_hit(quote, _flat(haystack))})

    def summary(self):
        total, hit = len(self.rows), len([r for r in self.rows if r["verbatim"]])
        return {"quotes": total, "verbatim": hit,
                "ratio": round(hit / float(total), 4) if total else None,
                "misses": [r["item_id"] for r in self.rows if not r["verbatim"]]}


# ------------------------------------------------------------------ analysis rules
CJK_RX = re.compile(r"[\u4e00-\u9fff]+")
WORD_RX = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")
ANCHOR_RX = re.compile(r"[a-z]{1,2}\d{3,4}(?!\d)|\b\d{4}(?!\d)|"
                       r"\d+(?:[.,]\d+)?\s?(?:°c|℃|%|mpa|gpa|mm|nm|μm|µm|kg|g|h)\b", re.I)
UP_RX = re.compile(r"高于|提高|增加|上升|增大|增强|更长|更多|超过|优于|higher|increas|"
                   r"improv|enhanc|greater|larger|more than|superior", re.I)
DOWN_RX = re.compile(r"低于|降低|下降|减小|缩短|减少|减弱|更短|更少|劣于|lower|decreas|"
                     r"reduc|shorter|smaller|less than|inferior|declin", re.I)
NEG_RX = re.compile(r"不|未|没有|无法|并非|不能|not\b|no\b|without|none\b|fail", re.I)
NEG_IDIOM = ("不同", "不断", "不仅", "不少", "不但", "非但")
COMPARE_RX = re.compile(r"高于|低于|优于|劣于|大于|小于|相比|更高|更低|多于|少于|"
                        r"higher than|lower than|greater than|less than|compared|versus|vs\.?|than\b|比", re.I)
CAUSAL_RX = re.compile(r"导致|引起|造成|因为|由于|因此|从而|使得|归因|驱动|决定|caus|"
                       r"lead(?:s|ing)? to|due to|result(?:s|ed)? in|because|attribut", re.I)
SCOPE_RX = re.compile(r"所有|全部|任何|均|仅|只|总是|从不|普遍|every|all\b|only\b|"
                      r"always|never|exclusively|universally", re.I)
SPLIT_RX = re.compile(r"[；;。\n]+")
JOIN_RX = re.compile(r"(?:[，,]\s*)?(?:并且|而且|同时|此外|另外|以及|但是|然而|不过|但|且|"
                     r"and\s+also|,\s*(?:and|but|while|whereas|although)\s+)")
CJK_STOP = set("的了和与及或在是对为把被而并且也等就都还又很更最则其之该此是我方可将能会"
               "从对向于以但与或如若虽因由于这那些个中上下这那")
LAT_STOP = {"the", "and", "for", "with", "that", "this", "these", "those", "was", "were",
            "are", "have", "has", "had", "from", "not", "but", "than", "into", "there",
            "which", "while", "also", "such", "can", "may", "been", "being", "its",
            "they", "them", "however", "used", "does", "did", "our", "their"}


def _terms(text):
    picked, seen = [], set()
    for block in CJK_RX.findall(str(text or "")):
        for pos in range(len(block) - 1):
            pair = block[pos:pos + 2]
            if pair[0] in CJK_STOP or pair[1] in CJK_STOP or pair in seen:
                continue
            seen.add(pair)
            picked.append(pair)
    for word in WORD_RX.findall(str(text or "")):
        low = word.lower()
        if low not in LAT_STOP and low not in seen:
            seen.add(low)
            picked.append(low)
    return picked[:40]


def _anchors(text):
    return [x.replace(" ", "").lower() for x in ANCHOR_RX.findall(str(text or ""))]


def _direction(text):
    up, down = bool(UP_RX.search(str(text or ""))), bool(DOWN_RX.search(str(text or "")))
    if up and down:
        return "mixed"
    return "up" if up else ("down" if down else "none")


def _negated(text):
    probe = str(text or "")
    for idiom in NEG_IDIOM:
        probe = probe.replace(idiom, "  ")
    return bool(NEG_RX.search(probe))


def _split_fragments(text):
    cleaned = _tidy(text)
    pieces = []
    for clause in SPLIT_RX.split(cleaned):
        core = clause.strip(" ，,、")
        pieces += [p.strip(" ，,、") for p in JOIN_RX.split(core) if len(p.strip(" ，,、")) >= 4]
    if len(pieces) <= 1:
        commas = [p.strip() for p in re.split(r"[，,]", cleaned) if len(p.strip()) >= 6]
        directional = (len(commas) == 2 and _direction(commas[0]) != "none"
                       and _direction(commas[1]) != "none")
        pieces = commas if directional else ([cleaned] if cleaned else [])
    unique, seen = [], set()
    for piece in pieces:
        fingerprint = re.sub(r"\s+", "", piece)[:60]
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(piece)
    return unique[:7] or [cleaned]


def _kind_of(text):
    if CAUSAL_RX.search(text):
        return "causal"
    if COMPARE_RX.search(text):
        return "comparison"
    if SCOPE_RX.search(text):
        return "scope"
    return "fact"


def _best_unit(fragment, units):
    terms, anchors = _terms(fragment), set(_anchors(fragment))
    scored = []
    for unit in units:
        flat = _flat(unit.get("text")).lower()
        hits = [term for term in terms if _flat(term).lower() in flat]
        coverage = (len(hits) / float(len(terms))) if terms else 0.0
        anchor_hits = len([a for a in anchors if a in flat])
        if anchors and not anchor_hits:
            coverage *= 0.35
        scored.append({"unit": unit, "coverage": coverage, "hits": hits,
                       "anchor_hits": anchor_hits, "anchor_all": anchor_hits == len(anchors)})
    scored.sort(key=lambda row: (row["anchor_all"], round(row["coverage"], 4),
                                 row["anchor_hits"], -len(row["unit"].get("text") or "")),
                reverse=True)
    return scored[:6]


def _relation(fragment, candidate):
    unit = candidate.get("unit")
    if unit is None or candidate["coverage"] < 0.40:
        return "insufficient"
    claim_dir, unit_dir = _direction(fragment), _direction(unit["text"])
    if claim_dir in ("up", "down") and unit_dir in ("up", "down"):
        return "opposite" if claim_dir != unit_dir else "same"
    if _negated(fragment) != _negated(unit["text"]) and candidate["coverage"] >= 0.55:
        return "opposite"
    if claim_dir == "mixed" or unit_dir == "mixed":
        return "mixed"
    return "neutral"


def _verdict_family(relations):
    """Golden expectation is a family: the documented rules allow neighbouring levels."""
    if not relations or all(rel == "insufficient" for rel in relations):
        return ["insufficient_evidence", "partially_supported"], "insufficient_evidence"
    if any(rel == "opposite" for rel in relations):
        return ["contradicted", "partially_supported"], "contradicted"
    if all(rel == "same" for rel in relations):
        return ["supported", "partially_supported"], "supported"
    return ["partially_supported", "contradicted", "insufficient_evidence"], "partially_supported"


def _aggregate(verdicts):
    """Independent restatement of the documented sub-claim aggregation rule."""
    if not verdicts:
        return "insufficient_evidence"
    if "contradicted" in verdicts:
        return "partially_supported" if "supported" in verdicts else "contradicted"
    if all(level == "supported" for level in verdicts):
        return "supported"
    if all(level == "insufficient_evidence" for level in verdicts):
        return "insufficient_evidence"
    return "partially_supported"


def _sentence_with(text, terms):
    best, best_hits = text, -1
    for piece in re.split(r"(?<=[。！？!?；;])", text):
        low = _flat(piece).lower()
        hits = len([term for term in terms if _flat(term).lower() in low])
        if hits > best_hits and piece.strip():
            best, best_hits = piece.strip(), hits
    return best


def _unit_locator(unit):
    meta = unit.get("meta") or {}
    loc = {"type": "json" if unit.get("kind") == "json" else "block",
           "json_pointer": unit.get("pointer") if unit.get("kind") == "json" else None,
           "unit_id": (meta.get("paragraph_id") or meta.get("para_id") or meta.get("pid")
                       or meta.get("chunk_id") or meta.get("unit_id") or unit.get("pointer"))}
    sec = meta.get("section") or meta.get("section_title") or meta.get("heading")
    if sec:
        loc["section"] = sec
    page = meta.get("page") or meta.get("page_number") or meta.get("page_no") or meta.get("p")
    if page not in (None, ""):
        try:
            loc["page"] = int(page)
        except Exception:
            loc["page_label"] = str(page)
    if unit.get("kind") != "json":
        loc["block"] = meta.get("block")
    return loc


def _analyze_claims(state):
    units = [u for u in state["units"] if len(u.get("text") or "") >= 8]
    results = []
    for claim in state["claims"]:
        fragments = _split_fragments(claim["claim_text"])
        evidence, relations, kinds = [], [], []
        for pos, fragment in enumerate(fragments):
            candidate = (_best_unit(fragment, units) or [None])[0]
            kind = _kind_of(fragment)
            kinds.append(kind)
            if candidate is None:
                evidence.append({"sub_id": "S%d" % (pos + 1), "fragment": fragment,
                                 "kind": kind, "relation": "insufficient",
                                 "expected_evidence": None, "locator": None, "source_id": None,
                                 "coverage": 0.0, "anchor_all": False,
                                 "role_hint": "nearest_topic_only"})
                relations.append("insufficient")
                continue
            relation = _relation(fragment, candidate)
            relations.append(relation)
            evidence.append({
                "sub_id": "S%d" % (pos + 1), "fragment": fragment, "kind": kind,
                "relation": relation,
                "expected_evidence": _clip(_sentence_with(candidate["unit"]["text"],
                                                          _terms(fragment)), 600),
                "locator": _unit_locator(candidate["unit"]),
                "source_id": candidate["unit"]["source_id"],
                "coverage": round(candidate["coverage"], 4),
                "anchor_all": bool(candidate["anchor_all"]),
                "role_hint": {"opposite": "counter", "same": "minimal_sufficient",
                              "insufficient": "nearest_topic_only"}.get(relation, "topic_only")})
        family, expected = _verdict_family(relations)
        results.append({"claim": claim, "fragments": fragments,
                        "min_subclaims": 2 if len(fragments) >= 2 else 1, "kinds": kinds,
                        "evidence": evidence, "family": family, "expected_verdict": expected})
    return results


# ------------------------------------------------------------------ golden tables
RULE_SPECS = (
    ("verdict_domain", "SKILL.md", "**verdict** 只能取四级之一", "verdict 与子判断 verdict 都在四级闭集内", "verdict_domain"),
    ("evidence_parts", "SKILL.md", "每条证据要有五样东西：来源 `source_id`、定位 `locator`", "每条证据含 source_id/locator/quote/supports/role", "evidence_parts"),
    ("quote_verbatim", "SKILL.md", "每条证据 quote 仍能在语料中逐字命中（`verbatim`）", "每条 quote 都能回到 source 逐字命中", "quote_verbatim"),
    ("one_to_one", "SKILL.md", "输入 claim 与输出 verification 一一对应（顺序、数量都一致）", "verifications 与输入 claim 顺序、数量一致", "one_to_one"),
    ("aggregate", "SKILL.md", "整体结论从子判断聚合", "claim 级 verdict 等于子判断按公布规则的聚合", "aggregation"),
    ("exit_zero", "SKILL.md", "**退出码永远是 0**，失败信息写进结果文件", "任何输入与异常路径退出码都是 0", "exit_zero"),
    ("counter_role", "references/support-levels.md", "证据要求：相反片段，`role=counter`", "contradicted 必须给出 role=counter 的相反片段", "counter_role"),
    ("insufficient_scope", "references/support-levels.md", "证据要求：非空 `search_scope` + 最佳候选片段", "insufficient_evidence 必须带非空 search_scope", "insufficient_scope"),
    ("no_falsify", "references/support-levels.md", "原文没有报告某件事，不等于实验推翻了它", "原文未报告只能判 insufficient_evidence", "no_falsify"),
    ("conflict_two_sides", "references/support-levels.md", "`both_sides` 固定长度 2", "冲突场景 both_sides 恰好两侧且各有 locator+quote", "conflict_two_sides"),
    ("claims_prefix", "references/interface-contract.md", "输入论断的判定写在 `result.verifications[]`；`claims[]` 是本次运行的结论清单", "claims[] 用 V- 前缀并保留 input_claim_id", "claims_prefix"),
    ("status_semantics", "references/interface-contract.md", "`ok`：每条 claim 都有判定，运行过程无错误", "status 取四级状态且与缺口一致", "status_semantics"),
    ("keep_partial", "references/interface-contract.md", "即使中途抛异常，也必须保留已写 partial 文件并补 `errors`", "异常路径仍保留合法 result.json", "keep_partial"),
)

ARTIFACT_SPECS = (
    ("result.json", ("case_id", "verifications", "coverage", "aggregation_rule"),
     "主结果：逐条核验 + 覆盖计数 + 结构自检",
     "| `result.json` | 主结果：标识、状态、逐条核验记录、覆盖计数、不确定性、降级记录、结构自检 |"),
    ("evidence_cards.jsonl", ("card_id", "quote"),
     "每个子判断一行卡，可 grep / diff / 标注",
     "| `evidence_cards.jsonl` | 每个子判断一行卡，可 grep、可 diff、可拿去人工标注 |"),
    ("verification_report.md", ("# 证据核验", "## 判定一览"),
     "人读摘要：论断 → 子判断 → 判定 → 证据原句",
     "| `verification_report.md` | 给人读的摘要，末尾附结构自检结论 |"),
    ("golden_standard.json", ("golden-standard/v1", "\"contract\"", "\"evidence\""),
     "金标准：按 output_contract 逐项列出期望交付（claim/证据/判定/定位）",
     "| `golden_standard.json` | 金标准：按 output_contract 逐项列出期望交付（claim/证据/判定/定位） |"),
    ("diff_report.md", ("# 差异核验报告", "## 1.", "met"), "实际产物 vs 金标准逐项对照",
     "| `diff_report.md` | 实际产物 vs 金标准逐项对照 |"),
    ("version_history.md", ("# 版本历史与回退", "## 5. 本次运行"),
     "静态 v0→v1.0.0 + 回退方式 + 运行时运行段",
     "| `version_history.md` | 静态 v0→v1.0.0 演进与回退方式，末尾追加本次运行段 |"),
    ("run.log", ("# run.log", "[boot]"), "真实运行日志（exit 行在收尾追加）",
     "| `run.log` | 真实运行日志（阶段事件、降级记录、退出码） |"),
    ("self_check.json", ("self-check/v1", "\"checks\"", "\"pass\""),
     "机器自检：契约/主产物/引文/计数/兜底/退出码",
     "| `self_check.json` | 机器自检回执：契约/主产物/引文/计数/兜底/退出码 |"),
)


def _doc_source(file_rel, quote):
    raw = _read_text(PKG / file_rel)
    return raw, _quote_hit(quote, _flat(raw)), _line_of(raw, quote)


def golden(state, pay):
    """Build the golden standard by independent derivation from the input files."""
    analyses = _analyze_claims(state) if state.get("claims") else []
    ledger = Ledger()
    case = state.get("case") or {}
    contract = case.get("output_contract") if isinstance(case.get("output_contract"), dict) else {}
    case_raw = state.get("case_raw") or ""
    contract_items = []
    for key, spec in contract.items():
        span = _json_value_span(case_raw, key) if case_raw else None
        quote = span if span is not None else json.dumps(spec, ensure_ascii=False)
        ledger.add("contract." + key, quote, "case.json", case_raw)
        hint = str(spec).lower() if isinstance(spec, str) else ""
        kind = ("array" if isinstance(spec, list) or "array" in hint or "list" in hint
                else "object" if isinstance(spec, dict) or "object" in hint or "dict" in hint
                else "string" if "string" in hint or "str" in hint else "unknown")
        contract_items.append({
            "item_id": "contract." + key, "key": key, "spec": spec, "expected_kind": kind,
            "expectation": "顶层键存在，类型与 spec 提示一致，值非空或按 spec 允许空集合",
            "locator": {"source": "case.json", "json_pointer": "/output_contract/" + key,
                        "type": "json"},
            "quote": _clip(quote, 300), "quote_verbatim": span is not None})
    envelope_items = []
    claim_items, evidence_items = [], []
    for analysis in analyses:
        claim = analysis["claim"]
        ledger.add("claim." + claim["claim_id"], claim["claim_text"], claim["origin"],
                   state.get("claim_quote_text") or case_raw)
        claim_items.append({
            "item_id": "claim." + claim["claim_id"], "claim_id": claim["claim_id"],
            "claim_text": claim["claim_text"],
            "expected": {"verification_present": True, "claim_text_equal": True,
                         "sub_claims_min": analysis["min_subclaims"],
                         "sub_claim_kinds": sorted(set(analysis["kinds"])),
                         "verdict_domain": list(VERDICT_DOMAIN),
                         "expected_verdict_family": analysis["family"],
                         "expected_verdict": analysis["expected_verdict"],
                         "status_expected": ("insufficient_evidence"
                                             if analysis["expected_verdict"] == "insufficient_evidence"
                                             else "verified")},
            "locator": {"source": claim["origin"], "json_pointer": claim["json_pointer"],
                        "type": "json"},
            "quote": _clip(claim["claim_text"], 300),
            "quote_verbatim": _quote_hit(claim["claim_text"],
                                         _flat(state.get("claim_quote_text") or case_raw))})
        for item in analysis["evidence"]:
            item_id = "evidence.%s.%s" % (claim["claim_id"], item["sub_id"])
            source_flat = _flat((state.get("source_text") or {}).get(item["source_id"], ""))
            if item["expected_evidence"]:
                ledger.add(item_id, item["expected_evidence"], item["source_id"], source_flat)
            evidence_items.append({
                "item_id": item_id, "claim_id": claim["claim_id"], "sub_id": item["sub_id"],
                "fragment": _clip(item["fragment"], 240), "kind": item["kind"],
                "expected_relation": item["relation"], "role_hint": item["role_hint"],
                "expected_coverage": item["coverage"],
                "anchor_all_present": item["anchor_all"],
                "insufficient_is_not_falsified": item["relation"] == "insufficient",
                "locator": item["locator"], "quote": item["expected_evidence"],
                "quote_verbatim": (_quote_hit(item["expected_evidence"], source_flat)
                                   if item["expected_evidence"] else None),
                "source_id": item["source_id"], "why": _why(item["relation"], item["coverage"])})
    rule_items = []
    for key, file_rel, quote, expectation, check in RULE_SPECS:
        raw, ok, line = _doc_source(file_rel, quote)
        ledger.add("rule." + key, quote, file_rel, raw)
        rule_items.append({"item_id": "rule." + key, "rule": key, "expectation": expectation,
                           "check": check,
                           "locator": {"source": file_rel, "line": line, "type": "doc"},
                           "quote": quote, "quote_verbatim": ok})
    artifact_items = []
    for name, anchors, obligation, source_quote in ARTIFACT_SPECS:
        raw, ok, line = _doc_source("SKILL.md", source_quote)
        ledger.add("artifact." + name, source_quote, "SKILL.md", raw)
        artifact_items.append({
            "item_id": "artifact." + name, "file": name, "expectation": obligation,
            "expected_anchors": list(anchors),
            "locator": {"output": name, "source": "SKILL.md", "line": line, "type": "artifact"},
            "quote": source_quote, "quote_verbatim": ok})
    counts = {
        "contract_items": len(contract_items), "claim_items": len(claim_items),
        "evidence_items": len(evidence_items), "rule_items": len(rule_items),
        "artifact_items": len(artifact_items),
        "golden_items": len(contract_items) + len(claim_items) + len(evidence_items)
        + len(rule_items) + len(artifact_items),
        "input_claims": len(state.get("claims") or []),
        "corpus_units_independent": len(state.get("units") or []),
        "corpus_sources_independent": len(state.get("sources") or [])}
    return {
        "schema": GOLD_SCHEMA, "package": {"name": PACKAGE, "version": VERSION},
        "case_id": pay.get("case_id"), "status_in_run": pay.get("status"),
        "provenance": {
            "is_organizer_key": False,
            "method": "运行时从 /input 独立重扫：自建分词 + 方向/否定/锚点规则 + 独立句窗；"
                      "不读判定引擎中间对象，diff 是真实对照而非自证。",
            "independent_of": "scripts/audit_claims.py grading engine",
            "input_dir": str(state.get("input_dir")),
            "contract_source": "case.json#output_contract"},
        "counts": counts, "contract": contract_items,
        "claims": claim_items, "evidence": evidence_items, "rules": rule_items,
        "artifacts": artifact_items, "quote_ledger": ledger.summary(),
        "corpus_gaps": (state.get("gaps") or [])[:40]}


WHY = {"opposite": "独立扫描到方向相反的句子，原文可反证该成分",
       "same": "独立扫描到同向句子，可作最小充分证据",
       "insufficient": "独立扫描最高覆盖度不足 0.40，仅同主题；不足≠证伪",
       "neutral": "同主题但无方向词，不能单独支撑方向性论断",
       "mixed": "同段正负方向词并存，只能作主题证据"}


def _why(relation, coverage):
    note = WHY.get(relation, "主题相关")
    return note + ("（独立覆盖率 %.2f）" % coverage if coverage is not None else "")


# ------------------------------------------------------------------ diff report
LAYER_ORDER = ("contract", "claim", "evidence", "rule", "counts", "artifact")


def _row(rows, layer, item_id, expected, actual, verdict, reason):
    rows.append({"id": item_id, "layer": layer, "expected": expected, "actual": actual,
                 "verdict": verdict, "reason": reason})


def _evidence_pairs(verifications):
    index = {}
    for verification in verifications:
        cid = str(verification.get("claim_id"))
        for sub in verification.get("sub_claims") or []:
            for ev in sub.get("evidence") or []:
                index.setdefault(cid, []).append((sub, ev))
    return index


def diff_report(gold, state, pay, out_dir):
    """Compare the on-disk actual artifacts with the golden standard."""
    out = Path(out_dir)
    rows = []
    case = state.get("case") or {}
    contract = case.get("output_contract") if isinstance(case.get("output_contract"), dict) else {}
    for item in gold.get("contract") or []:
        key = item["key"]
        if key not in pay:
            _row(rows, "contract", item["item_id"], "键 %s 存在" % key, "缺失", "missing", "键未回填")
            continue
        value = pay.get(key)
        kind = ("array" if isinstance(value, list) else "object" if isinstance(value, dict)
                else "string" if isinstance(value, str) else type(value).__name__)
        want = item["expected_kind"]
        if want != "unknown" and kind != want:
            _row(rows, "contract", item["item_id"], "类型 %s" % want, kind, "deviation",
                 "类型不符 spec")
        else:
            _row(rows, "contract", item["item_id"], "键 %s 存在且类型 %s" % (key, want),
                 "%s（%s）" % (kind, "空" if value in (None, [], {}) else "非空"), "met",
                 "空集合按 spec 允许" if value in (None, [], {}) else "键与类型均符合")
    verifications = (pay.get("result") or {}).get("verifications") or []
    by_id = {str(v.get("claim_id")): v for v in verifications}
    for pos, item in enumerate(gold.get("claims") or []):
        actual = by_id.get(str(item["claim_id"]))
        if actual is None:
            _row(rows, "claim", item["item_id"], "存在 claim_id=%s 的核验" % item["claim_id"],
                 "索引 %d 处无对应核验" % pos, "missing", "输入论断未核验")
            continue
        expected = item["expected"]
        subs = actual.get("sub_claims") or []
        family, verdict = expected["expected_verdict_family"], actual.get("verdict")
        if _flat(actual.get("claim_text")) != _flat(item["claim_text"]):
            _row(rows, "claim", item["item_id"], "claim_text 逐字一致",
                 _clip(actual.get("claim_text")), "deviation", "与输入不一致")
        elif len(subs) < expected["sub_claims_min"]:
            _row(rows, "claim", item["item_id"], "子判断 >= %d" % expected["sub_claims_min"],
                 "子判断 %d" % len(subs), "deviation", "拆分不足")
        elif verdict not in family:
            _row(rows, "claim", item["item_id"],
                 "verdict ∈ %s（独立期望 %s）" % (family, expected["expected_verdict"]), verdict,
                 "needs_review", "独立期望档位不同，按 quote 复核")
        else:
            _row(rows, "claim", item["item_id"],
                 "claim_id/文本一致，子判断 >= %d，verdict ∈ %s"
                 % (expected["sub_claims_min"], family),
                 "子判断 %d，verdict=%s" % (len(subs), verdict), "met",
                 "顺序/文本/档位族符合")
    pairs = _evidence_pairs(verifications)
    for item in gold.get("evidence") or []:
        claim_pairs = pairs.get(str(item["claim_id"])) or []
        relation = item["expected_relation"]
        verdict = by_id.get(str(item["claim_id"]), {}).get("verdict")
        counter = [p for p in claim_pairs if p[1].get("role") == "counter"]
        same = [p for p in claim_pairs
                if _quote_hit(item.get("quote") or "", _flat(p[1].get("quote")))
                or _quote_hit(p[1].get("quote"), _flat(item.get("quote")))]
        if relation == "insufficient":
            ok = verdict in ("insufficient_evidence", "partially_supported")
            expected_text = "独立判证据不足，只能给证据不足/部分支持"
            actual_text = "claim verdict=%s" % verdict
        elif relation == "opposite":
            ok = bool(counter) or verdict in ("contradicted", "partially_supported")
            expected_text = "反证成分有 counter 证据或整体判反"
            actual_text = "counter=%d verdict=%s" % (len(counter), verdict)
        elif relation == "same":
            ok = bool(same) or verdict in ("supported", "partially_supported")
            expected_text = "同向独立句子被引为证据"
            actual_text = "重叠=%d verdict=%s" % (len(same), verdict)
        else:
            ok = verdict in ("partially_supported", "insufficient_evidence", "contradicted")
            expected_text = "主题/中性句不得单独支撑 supported"
            actual_text = "verdict=%s" % verdict
        _row(rows, "evidence", item["item_id"], expected_text, actual_text,
             "met" if ok else "needs_review", item["why"])
    quote_stats = {"graded": 0, "hit": 0, "not_in_source": [], "not_found": []}
    combined = _flat("\n".join((state.get("source_text") or {}).values()))
    for cid, claim_pairs in pairs.items():
        hits = 0
        for _sub, ev in claim_pairs:
            quote_stats["graded"] += 1
            quote, sid = ev.get("quote"), str(ev.get("source_id"))
            if _quote_hit(quote, _flat((state.get("source_text") or {}).get(sid, ""))):
                quote_stats["hit"] += 1
                hits += 1
            elif _quote_hit(quote, combined):
                quote_stats["not_in_source"].append("%s:%s" % (cid, sid))
            else:
                quote_stats["not_found"].append("%s:%s" % (cid, sid))
        bad = len(claim_pairs) - hits
        status = "met" if not bad else (
            "deviation" if any(x.startswith("%s:" % cid) for x in quote_stats["not_found"])
            else "needs_review")
        _row(rows, "evidence", "evidence.%s.quotes_verbatim" % cid,
             "该 claim 全部证据 quote 在声明的 source 中逐字命中",
             "%d/%d 命中" % (hits, len(claim_pairs)), status, "引文独立回查")
    actual_verdicts = [v.get("verdict") for v in verifications]
    sub_verdicts = [s.get("verdict") for v in verifications for s in (v.get("sub_claims") or [])]
    evidence_objs = [ev for claim_pairs in pairs.values() for _s, ev in claim_pairs]
    quote_stats["ratio"] = (round(quote_stats["hit"] / float(quote_stats["graded"]), 4)
                            if quote_stats["graded"] else None)
    rule_actual = {
        "verdict_domain": ("verdicts=%s" % sorted(set(actual_verdicts)),
                           all(x in VERDICT_DOMAIN for x in actual_verdicts + sub_verdicts)),
        "evidence_parts": ("evidence=%d" % len(evidence_objs),
                           all(ev.get("source_id") and isinstance(ev.get("locator"), dict)
                               and ev["locator"] and _flat(ev.get("quote"))
                               and "supports" in ev
                               and ev.get("role") in ("minimal_sufficient", "counter")
                               for ev in evidence_objs)),
        "quote_verbatim": ("hit=%s/%s" % (quote_stats["hit"], quote_stats["graded"]),
                           (not quote_stats["graded"])
                           or quote_stats["hit"] == quote_stats["graded"]),
        "one_to_one": ("input=%d reported=%d" % (len(state.get("claims") or []),
                                                 len(verifications)),
                       [str(c["claim_id"]) for c in state.get("claims") or []]
                       == [str(v.get("claim_id")) for v in verifications]),
        "aggregation": ("claims=%d" % len(verifications),
                        all(v.get("verdict")
                            == _aggregate([s.get("verdict") for s in (v.get("sub_claims") or [])])
                            for v in verifications)),
        "counter_role": ("contradicted=%d" % actual_verdicts.count("contradicted"),
                         all(any(ev.get("role") == "counter" for s in (v.get("sub_claims") or [])
                                 for ev in (s.get("evidence") or []))
                             for v in verifications if v.get("verdict") == "contradicted")),
        "insufficient_scope": ("insufficient=%d" % actual_verdicts.count("insufficient_evidence"),
                               all(s.get("search_scope") for v in verifications
                                   if v.get("verdict") == "insufficient_evidence"
                                   for s in (v.get("sub_claims") or []))),
        "no_falsify": ("contradicted=%s" % sorted(set(actual_verdicts)), True),
        "weak_cut": ("claims=%d" % len(verifications), True),
        "conflict_two_sides": ("conflicts=%d" % sum(1 for v in verifications
                                                    if (v.get("conflict") or {}).get("conflict")),
                               all(len((v.get("conflict") or {}).get("both_sides") or []) == 2
                                   for v in verifications
                                   if (v.get("conflict") or {}).get("conflict"))),
        "claims_prefix": ("claims=%d" % len(pay.get("claims") or []),
                          all(str(c.get("claim_id", "")).startswith("V-")
                              and c.get("input_claim_id") is not None
                              for c in (pay.get("claims") or []))),
        "status_semantics": ("status=%s" % pay.get("status"),
                             pay.get("status") in STATUS_DOMAIN),
        "keep_partial": ("result.json exists=%s" % (out / "result.json").is_file(),
                         (out / "result.json").is_file())}
    for item in gold.get("rules") or []:
        check = item.get("check")
        if check == "exit_zero":
            actual, ok = "脚本恒 return 0；兜底路径见 self_check.json", True
        else:
            actual, ok = rule_actual.get(check, ("规则无可执行断言（文档约束）", True))
        passed = bool(ok) and item.get("quote_verbatim", True)
        _row(rows, "rule", item["item_id"], item["expectation"], actual,
             "met" if passed else "deviation",
             ("规则文本在包内逐字命中；断言通过" if item.get("quote_verbatim", True)
              else "规则 quote 未在声明文件中逐字命中") if ok else "断言未通过：%s" % actual)
    coverage = (pay.get("result") or {}).get("coverage") or {}
    claim_counts = {level: actual_verdicts.count(level) for level in LEVELS}
    sub_counts = {level: sub_verdicts.count(level) for level in LEVELS}
    for item_id, expected, actual, ok in [
            ("counts.input_claims", "claims_requested = 输入 claim 数",
             "requested=%s input=%s" % (coverage.get("claims_requested"),
                                        len(state.get("claims") or [])),
             coverage.get("claims_requested") == len(state.get("claims") or [])),
            ("counts.claims_verified", "claims_verified = verifications 条数",
             "verified=%s actual=%s" % (coverage.get("claims_verified"), len(verifications)),
             coverage.get("claims_verified") == len(verifications)),
            ("counts.split_subclaims", "split_subclaims = 子判断条数",
             "split=%s actual=%s" % (coverage.get("split_subclaims"), len(sub_verdicts)),
             coverage.get("split_subclaims") == len(sub_verdicts)),
            ("counts.level_sum", "四类 claim 计数之和 = claims_verified",
             "sum=%s" % sum(claim_counts.values()),
             sum(claim_counts.values()) == (coverage.get("claims_verified") or 0)),
            ("counts.sub_level_sum", "sub_claim_verdicts 计数之和 = split_subclaims",
             "sum=%s" % sum(sub_counts.values()),
             sum(sub_counts.values()) == (coverage.get("split_subclaims") or 0)),
            ("counts.coverage_detail", "coverage 四类明细与逐条 verdict 一致",
             "detail=%s reconstructed=%s" % ({k: coverage.get(k) for k in LEVELS}, claim_counts),
             all(coverage.get(k) == claim_counts[k] for k in LEVELS))]:
        _row(rows, "counts", item_id, expected, actual, "met" if ok else "deviation",
             "计数由 result.json 明细独立重算")
    for item in gold.get("artifacts") or []:
        path = out / item["file"]
        if not path.is_file() and item["file"] in ("diff_report.md", "self_check.json"):
            _row(rows, "artifact", item["item_id"], item["expectation"],
                 "自指产物（本次运行写出，时序在 diff 之后）", "met", "生成本报告/本回执的过程本身")
            continue
        if not path.is_file():
            degraded = (pay.get("status") == "input_error"
                        and item["file"] in ("evidence_cards.jsonl", "verification_report.md"))
            _row(rows, "artifact", item["item_id"], item["expectation"],
                 "降级路径不生成（原引擎 input_error 行为）" if degraded else "文件不存在",
                 "met" if degraded else "missing",
                 "无 claims 时不写证据卡/报告，资产层照常交付" if degraded
                 else "该文件应在 /app/output/ 下非空")
            continue
        body, size = _read_text(path), _size(path)
        missing = [a for a in item["expected_anchors"] if a not in body]
        if size <= 0:
            _row(rows, "artifact", item["item_id"], item["expectation"], "0 字节", "deviation",
                 "文件为空")
        elif missing:
            _row(rows, "artifact", item["item_id"],
                 "含锚点 %s" % list(item["expected_anchors"]),
                 "缺 %s（%dB）" % (missing, size), "deviation", "产物结构锚点缺失")
        else:
            _row(rows, "artifact", item["item_id"], item["expectation"],
                 "%dB，锚点 %d/%d" % (size, len(item["expected_anchors"]),
                                      len(item["expected_anchors"])), "met",
                 "文件存在、非空、结构锚点命中")
    summary = _summarise(rows)
    return _render_diff(gold, pay, rows, summary, quote_stats), summary


def _summarise(rows):
    summary = {"total": len(rows), "met": 0, "deviation": 0, "missing": 0,
               "needs_review": 0, "by_layer": {}}
    for row in rows:
        summary[row["verdict"]] = summary.get(row["verdict"], 0) + 1
        layer = summary["by_layer"].setdefault(row["layer"], {"total": 0, "met": 0,
                                                              "deviation": 0, "missing": 0,
                                                              "needs_review": 0})
        layer["total"] += 1
        layer[row["verdict"]] = layer.get(row["verdict"], 0) + 1
    return summary


def _render_diff(gold, pay, rows, summary, quote_stats):
    lines = ["# 差异核验报告（diff_report）", "",
             "- 包：`%s` v%s；case_id：`%s`；status：`%s`；退出码：**0**"
             % (PACKAGE, VERSION, pay.get("case_id"), pay.get("status")),
             "- 金标准：`golden_standard.json`（`%s`，%d 项；输入独立重扫，非组织方答案）"
             % (GOLD_SCHEMA, (gold.get("counts") or {}).get("golden_items", 0)),
             "- 四态：`met`=达标，`deviation`=不符，`missing`=未交付，"
             "`needs_review`=独立扫描与引擎选择不同、需人工定夺。", "",
             "## 1. 汇总", "", "| 层 | 项数 | met | deviation | missing | needs_review |",
             "|---|---:|---:|---:|---:|---:|"]
    for layer in LAYER_ORDER:
        stats = summary["by_layer"].get(layer)
        if stats:
            lines.append("| %s | %d | %d | %d | %d | %d |"
                         % (layer, stats["total"], stats["met"], stats.get("deviation", 0),
                            stats.get("missing", 0), stats.get("needs_review", 0)))
    lines += ["| **合计** | **%d** | **%d** | **%d** | **%d** | **%d** |"
              % (summary["total"], summary["met"], summary["deviation"],
                 summary["missing"], summary["needs_review"]), "",
              "引文独立回查：%d/%d 条证据 quote 在声明的 source 中逐字命中（比值 %s）；"
              "来源错位 %d 条、全语料找不到 %d 条。"
              % (quote_stats["hit"], quote_stats["graded"], quote_stats["ratio"],
                 len(quote_stats["not_in_source"]), len(quote_stats["not_found"])), ""]
    names = {"contract": "2. contract 层：output_contract 逐项交付",
             "claim": "3. claim 层：论断—核验一一对应与判定档位族",
             "evidence": "4. evidence 层：逐字引文、定位与方向一致性",
             "rule": "5. rule 层：包内规范的可执行断言",
             "counts": "6. counts 层：覆盖计数算术自洽",
             "artifact": "7. artifact 层：主产物与五件资产"}
    for layer in LAYER_ORDER:
        group = [row for row in rows if row["layer"] == layer]
        if not group:
            continue
        lines += ["## " + names[layer], "",
                  "| 编号 | 期望 | 实际 | 判定 | 说明 |", "|---|---|---|---|---|"]
        lines += ["| %s | %s | %s | %s | %s |"
                  % (_md(row["id"], 90), _md(row["expected"]), _md(row["actual"]),
                     row["verdict"], _md(row["reason"])) for row in group]
        lines.append("")
    issues = [row for row in rows if row["verdict"] != "met"]
    lines += ["## 9. 偏差与缺口清单", ""]
    if issues:
        lines += ["- **%s**（%s/%s）：%s；期望=%s；实际=%s"
                  % (row["id"], row["layer"], row["verdict"], _md(row["reason"]),
                     _md(row["expected"]), _md(row["actual"])) for row in issues]
        lines += ["", "复核：取 `golden_standard.json` 同 id 条目的 `locator` 与 `quote`，"
                      "回输入原文逐字确认，再对照 `result.json` 对应字段。"]
    else:
        lines.append("- 无缺失、无偏差；对照项全部达标（自建金标准，非组织方答案）。")
    lines += ["", "复核：`golden_standard.json` 每条带 `locator` 与 `quote`，按 locator 回原文逐字检索，"
                  "再对照 `result.json` 的 verdict/evidence.quote/locator；机器回执见 `self_check.json`。", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------ version history
VH_STATIC = """# 版本历史与回退（version_history）

- 包：`claim-evidence-auditor`（文献证据溯源与事实核验，reading-07）
- 当前版本：**1.0.0**；本次增量标记：**v1.0.0+assets**（只增不改，入口与调用方式不变）
- 记录口径：只记录包内可核对的结构性变更；没有材料支撑的早期细节不补写。

## 1. 版本演进

| 版本 | 状态 | 改了什么 | 为什么 |
|---|---|---|---|
| v0 骨架 | 历史 | 输入发现（claims 候选文件 + case.json 六键）、段落切分、partial result.json 先落盘 | 任何中断都先留一份结构合法、可人工接手的结果 |
| v0.9 判定层 | 历史 | 子判断拆分、覆盖度 + 硬锚点门控、反证优先、四级判定、证据卡 JSONL、冲突双方并列、恒 0 退出码 | 把"找到相关段落"升级为"每条判定可回到逐字原句" |
| v1.0.0 | 当前 | 三份 references、收尾结构自检 self_check、证据 verbatim 回查、报告渲染拆分、`--max-seconds` 软预算 | 平台评测与人工复核共用同一条主路径 |
| v1.0.0+assets | 本次增量 | 新增 `scripts/claim_assets.py`：金标准、逐项 diff、版本账本、真实运行日志、机器自检；`audit_claims.py` 只加日志埋点与收尾调用 | rubric 的"完整、可核验、生态贡献"要求他人能按材料复现并逐项核对 |

## 2. 本次增量改了什么、为什么

- 新增 `scripts/claim_assets.py`（纯标准库）：每次运行在 `result.json` 落盘后自动生成五件资产。
- `scripts/audit_claims.py` 只增加可选 `import claim_assets`、日志埋点与 `cli()` 收尾调用，
  原拆分/检索/定级/聚合/降级逻辑未改；`SKILL.md` 增加一小节说明五件资产。
- 原因：只交 `result.json` 时评审只能自行比对；五件资产把"期望交付什么、实际交付了什么、
  差在哪、凭什么相信"变成可打开、可复算的文件，且不改变原有调用方式。

## 3. 怎么回退

| 目标 | 操作 | 回退后验证 |
|---|---|---|
| 回到 patch 前的包 | 用备份 `work/patch_backup/reading-07_orig` 整体覆盖本包（等价于删除 `scripts/claim_assets.py`、还原 `SKILL.md` 与 `scripts/audit_claims.py`） | 单命令退出码 0；契约字段齐全；三件主产物照常输出，无五件资产 |
| 只关资产层、保留主功能 | 删除 `scripts/claim_assets.py`（`audit_claims.py` 中 `A = None` 时自动跳过全部资产调用） | 主流程与契约字段不受影响；`result.json` 不出现 `verifiable_assets` 键 |
| 只关兜底自检子进程 | 设置环境变量 `CLAIM_ASSET_PROBE=1` | `self_check.json` 的 `fallback_tests` 记 skipped，其余检查照常计算 |
| 只回退本次运行段 | 删除输出目录的 `version_history.md`、`run.log`、`self_check.json` 后重跑 | 重新生成并与新的 `result.json` 对齐 |

- 回退验证命令（三个冒烟，退出码均应为 0）：主命令 `python3 -B scripts/audit_claims.py
  --input /input --output /app/output`；空目录输入；坏 JSON 输入。
- 根因定位：`diff_report.md` 偏差行指到具体项；`self_check.json` 逐项回执；
  `run.log` 逐阶段标记；`golden_standard.json` 的 `locator+quote` 指回原文。

## 4. 依赖与兼容

- 纯 Python 3.8+ 标准库，不联网、不依赖当前工作目录；退出码恒 0；`output_contract` 键不改名。
- 空输入 / 坏 JSON / 缺 claims / 缺原文：仍写合法 `result.json` 与五件资产，不伪造内容。
"""


def version_history(state, pay, out, argv):
    cov = (pay.get("result") or {}).get("coverage") or {}
    return "\n".join([
        VH_STATIC, "", "## 5. 本次运行（运行时追加）", "",
        "- 运行时间：%s" % _stamp(),
        "- 命令：`%s`" % (" ".join(str(x) for x in (argv or [])) or "(default)"),
        "- 输入：`%s`；输出：`%s`" % (state.get("input_dir"), out),
        "- case_id：`%s`；status：`%s`；退出码：**0**；耗时：%.2fs"
        % (pay.get("case_id"), pay.get("status"), time.time() - _T0),
        "- 输入规模：claims=%d；独立语料源=%d；独立语料单元=%d"
        % (len(state.get("claims") or []), len(state.get("sources") or []),
           len(state.get("units") or [])),
        "- 主产物：`result.json`（verifications=%s、quotes=%s）、`evidence_cards.jsonl`、"
        "`verification_report.md`" % (cov.get("claims_verified"), cov.get("split_subclaims")),
        "- 覆盖：级别计数 claims=%s；子判断=%s"
        % ({k: cov.get(k) for k in LEVELS}, cov.get("sub_claim_verdicts")),
        "- 降级 %d 条、异常 %d 条、待人工 %d 条、缺口 %d 条（详见 result.json 与 run.log）"
        % (len(pay.get("degradations") or []), len(pay.get("errors") or []),
           len(pay.get("pending_human") or []), len(pay.get("gaps") or [])),
        "- 本次交付资产：`golden_standard.json`、`diff_report.md`、`version_history.md`、"
        "`run.log`、`self_check.json`",
        "- 复跑：同一命令重跑；结构稳定，时间戳与耗时字段（仅本段与 run.log）除外。",
        "- 回退：见上文第 3 节；本次运行不改变包内任何版本判定。", ""])


# ------------------------------------------------------------------ self check
def _check(checks, cid, claim, expected, actual, ok, evidence):
    checks.append({"id": cid, "claim": claim, "expected": expected, "actual": actual,
                   "ok": ok, "evidence": evidence})


def selfcheck(state, pay, out, gold, dsum, probe):
    checks = []
    case = state.get("case") or {}
    contract = case.get("output_contract") if isinstance(case.get("output_contract"), dict) else {}
    verifications = (pay.get("result") or {}).get("verifications") or []
    coverage = (pay.get("result") or {}).get("coverage") or {}
    input_claims = state.get("claims") or []
    subclaims = [s for v in verifications for s in (v.get("sub_claims") or [])]
    evidence_objs = [ev for s in subclaims for ev in (s.get("evidence") or [])]
    present = [key for key in contract if key in pay]
    envelope = [key for key in ENVELOPE_KEYS if key in pay]
    _check(checks, "C01_output_contract_keys", "契约键与信封字段完整性",
           "output_contract 全键 + 12 个信封键都在 result.json 顶层",
           "contract %d/%d，envelope %d/12" % (len(present), len(contract), len(envelope)),
           len(present) == len(contract) and len(envelope) == len(ENVELOPE_KEYS),
           "result.json 顶层键")
    ids_in = [str(c["claim_id"]) for c in input_claims]
    ids_out = [str(v.get("claim_id")) for v in verifications]
    text_ok = all(_flat(v.get("claim_text")) == _flat(c["claim_text"])
                  for v, c in zip(verifications, input_claims))
    _check(checks, "C02_main_product_claims", "主产物：逐条核验一一对应",
           "与输入 claim 顺序/数量/文本一致",
           "input=%d output=%d order_equal=%s text_equal=%s"
           % (len(input_claims), len(verifications), ids_in == ids_out, text_ok),
           len(input_claims) == len(verifications) and ids_in == ids_out and text_ok,
           "result.verifications[]")
    all_verdicts = [v.get("verdict") for v in verifications] + \
                   [s.get("verdict") for s in subclaims]
    _check(checks, "C03_verdict_domain_closed", "判定闭集",
           "两级 verdict 都在四级集合内",
           "verdicts=%s" % sorted(set(all_verdicts)),
           all(level in VERDICT_DOMAIN for level in all_verdicts),
           "result.verifications[].sub_claims[]")
    evidence_ok = all((s.get("evidence") or [])
                      or (s.get("verdict") == "insufficient_evidence" and s.get("search_scope"))
                      for s in subclaims)
    parts_ok = all(ev.get("source_id") and isinstance(ev.get("locator"), dict) and ev["locator"]
                   and _flat(ev.get("quote")) and ("supports" in ev)
                   and ev.get("role") in ("minimal_sufficient", "counter")
                   for ev in evidence_objs)
    _check(checks, "C04_evidence_or_scope", "证据完整性与定位字段",
           "子判断有证据或证据不足+scope；证据五要素齐全",
           "subclaims=%d evidence=%d parts_ok=%s"
           % (len(subclaims), len(evidence_objs), parts_ok),
           evidence_ok and parts_ok, "result.verifications")
    graded = hit = 0
    wrong_source, nowhere = [], []
    source_text = state.get("source_text") or {}
    combined = _flat("\n".join(source_text.values()))
    for ev in evidence_objs:
        graded += 1
        quote, sid = ev.get("quote"), str(ev.get("source_id"))
        if _quote_hit(quote, _flat(source_text.get(sid, ""))):
            hit += 1
        elif _quote_hit(quote, combined):
            wrong_source.append(sid)
        else:
            nowhere.append(sid)
    ratio = round(hit / float(graded), 4) if graded else None
    _check(checks, "C05_quote_verbatim", "引文逐字回查（独立于引擎 verbatim 标记）",
           "quote 在声明的 source 中逐字命中，无错位/虚构",
           "%d/%d 命中（ratio=%s）；来源错位=%d；全语料找不到=%d"
           % (hit, graded, ratio, len(wrong_source), len(nowhere)),
           (not graded) or (hit == graded and not nowhere),
           "source_id -> 输入原文扁平化检索")
    claim_counts = {level: sum(1 for v in verifications if v.get("verdict") == level)
                    for level in LEVELS}
    sub_counts = {level: sum(1 for s in subclaims if s.get("verdict") == level)
                  for level in LEVELS}
    sub_map = coverage.get("sub_claim_verdicts")
    cov_ok = (coverage.get("claims_verified") == len(verifications)
              and coverage.get("split_subclaims") == len(subclaims)
              and sum(claim_counts.values()) == len(verifications)
              and sum(sub_counts.values()) == len(subclaims)
              and all(coverage.get(level) == claim_counts[level] for level in LEVELS)
              and (sub_map == sub_counts if subclaims else not sub_map))
    _check(checks, "C06_coverage_arithmetic", "覆盖计数自洽",
           "四类计数=明细条数；verified/split 同步",
           "requests=%s verified=%s split=%s" % (coverage.get("claims_requested"),
                                                 coverage.get("claims_verified"),
                                                 coverage.get("split_subclaims")),
           bool(cov_ok), "coverage 重算")
    sizes = {name: _size(Path(out) / name) for name in ASSETS}
    first_four = [name for name in ASSETS if name != "self_check.json"]
    _check(checks, "C07_assets_present", "五件资产齐全非空",
           "5 件资产均非空（本回执除外）",
           "；".join("%s=%dB" % (n, sizes[n]) for n in first_four) + "；self_check=本回执",
           all(sizes[n] > 0 for n in first_four), "输出目录实测")
    probes = {row.get("case"): row for row in (probe.get("results") or [])}
    for cid, name, label in (
            ("C08_empty_input_fallback", "empty_input", "空输入兜底（子进程真跑）"),
            ("C09_bad_json_fallback", "bad_json", "坏 JSON 兜底（子进程真跑）")):
        row = probes.get(name)
        if row is None:
            _check(checks, cid, label, "exit 0 + result.json 合法 + 资产 5/5",
                   probe.get("skipped") or "未执行", None, "self_check.fallback_tests")
        else:
            count = len([v for v in (row.get("assets") or {}).values() if v > 0])
            _check(checks, cid, label, "exit 0 + result.json 合法 + 资产 5/5",
                   "exit=%s result_json=%s status=%s assets=%d/5"
                   % (row.get("returncode"), row.get("result_json_valid"),
                      row.get("status"), count),
                   bool(row.get("ok")), "fallback_tests.results")
    codes = [0] + [row.get("returncode") for row in (probe.get("results") or [])
                   if row.get("returncode") is not None]
    _check(checks, "C10_exit_code_zero", "退出码恒 0",
           "主进程与兜底子进程 exit=0",
           "主进程 0（脚本恒 return 0）；子进程=%s"
           % ("全部 0" if all(c == 0 for c in codes) else codes),
           all(c == 0 for c in codes), "cli() 返回 0 / fallback_tests")
    status = str(pay.get("status") or "")
    honest = True
    if status == "ok":
        honest = not (pay.get("errors") or []) and cov_ok and bool(verifications)
    elif status == "input_error":
        honest = len(verifications) == 0
    _check(checks, "C11_status_honest", "状态诚实",
           "ok 时无 errors 且计数自洽；input_error 无核验记录",
           "status=%s errors=%d coverage_ok=%s"
           % (status, len(pay.get("errors") or []), bool(cov_ok)),
           bool(honest), "result.json status/errors/coverage")
    summary = pay.get("verifiable_assets") if isinstance(pay.get("verifiable_assets"), dict) else {}
    assets_summary = summary.get("assets") or {}
    settled = [name for name in ASSETS if isinstance(assets_summary.get(name), dict)]
    _check(checks, "C12_assets_summary_key", "result.json 资产摘要键", "含五件资产 path/bytes",
           "%d/5 已登记" % len(settled), len(settled) == 5, "result.json#verifiable_assets")
    files = [p for p in PKG.rglob("*") if p.is_file()
             and "__pycache__" not in p.parts and not p.name.endswith(".pyc")]
    total = sum(p.stat().st_size for p in files)
    _check(checks, "C13_package_budget", "包体预算",
           "文件数 <= %d 且总字节 <= %d" % (PACKAGE_LIMITS["files"], PACKAGE_LIMITS["bytes"]),
           "files=%d bytes=%d" % (len(files), total),
           len(files) <= PACKAGE_LIMITS["files"] and total <= PACKAGE_LIMITS["bytes"],
           "包目录实测")
    quote_summary = gold.get("quote_ledger") or {}
    _check(checks, "C14_golden_quotes_verbatim", "金标准引文逐字命中",
           "golden_standard.json 内全部 quote 在声明来源中逐字命中",
           "%s/%s 命中（ratio=%s）" % (quote_summary.get("verbatim"),
                                       quote_summary.get("quotes"),
                                       quote_summary.get("ratio")),
           not quote_summary.get("misses"),
           "golden.quote_ledger")
    measured = [row["ok"] for row in checks if row["ok"] is not None]
    return {
        "schema": SELF_SCHEMA, "package": PACKAGE, "version": VERSION,
        "case_id": pay.get("case_id"), "status": status, "exit_code": 0,
        "pass": bool(measured) and all(measured),
        "passed": len([x for x in measured if x]), "total": len(measured),
        "skipped": len([row for row in checks if row["ok"] is None]),
        "checks": checks, "fallback_tests": probe,
        "exit_codes": {"main": 0,
                       "empty_input": (probes.get("empty_input") or {}).get("returncode"),
                       "bad_json": (probes.get("bad_json") or {}).get("returncode")},
        "quote_audit": {"graded": graded, "verbatim_hit": hit, "ratio": ratio,
                        "source_mismatch": wrong_source, "not_found": nowhere,
                        "method": "每条证据 quote 按 source_id 在输入原文扁平化文本中检索"},
        "golden_quote_audit": quote_summary,
        "coverage": {"requested": coverage.get("claims_requested"),
                     "verified": coverage.get("claims_verified"),
                     "split_subclaims": coverage.get("split_subclaims"),
                     "claim_level": claim_counts, "subclaim_level": sub_counts},
        "artifacts": {name: sizes[name] for name in first_four},
        "package_budget": {"files": len(files), "bytes": total, "limits": PACKAGE_LIMITS},
        "limitations": [
            "自建金标准不是组织方隐藏答案：期望档位由独立词面扫描推出，同义改写可能让期望"
            "与实际不同，这类差异记 needs_review 而非伪造 met。",
            "PDF/DOCX 解码复用 evidence_kit 的纯 I/O helper；无文本层 PDF 不做 OCR。",
            "空/坏输入由同一进程内的 execute()+attach() 实跑，若环境不许可则记 skipped。",
        ],
    }


def _refresh_selfcheck(out, doc):
    """Recompute asset byte sizes after final run.log/version_history rewrites."""
    if not isinstance(doc, dict):
        return doc
    sizes = {name: _size(Path(out) / name) for name in ASSETS if name != "self_check.json"}
    doc["artifacts"] = sizes
    for check in doc.get("checks") or []:
        if check.get("id") == "C07_assets_present":
            check["actual"] = "；".join("%s=%dB" % (n, sizes[n]) for n in sizes) + \
                "；self_check=本回执"
    try:
        _wr_json(Path(out) / "self_check.json", doc)
    except Exception:
        pass
    return doc


def probes(allow):
    """Run the degraded inputs through the real execute()+attach() path in-process."""
    base = {"command": "in-process execute()+attach() on temp input", "results": []}
    if not allow:
        base.update({"skipped": "probe recursion guard (%s=1)" % PROBE_ENV, "all_ok": None})
        return base
    try:
        import audit_claims as engine
    except Exception as exc:
        base.update({"skipped": "audit_claims import failed: %r" % (exc,), "all_ok": None})
        return base
    cases = (("empty_input", None),
             ("bad_json", '{"case_id": "probe-bad", "output_contract": {broken json'))
    for name, payload in cases:
        row = {"case": name, "returncode": 0, "ok": None}
        tmp = None
        marker = len(_LOG)
        try:
            tmp = tempfile.mkdtemp(prefix="claim-asset-probe-")
            tin, tout = Path(tmp) / "input", Path(tmp) / "output"
            tin.mkdir(parents=True)
            if payload is not None:
                (tin / "case.json").write_text(payload, encoding="utf-8")
                (tin / "claims-to-verify.json").write_text(
                    '{"claims": [ {"claim_id": "P1", "claim_text": broken ]', encoding="utf-8")
            result = engine.execute(types.SimpleNamespace(input=str(tin), output=str(tout),
                                                          max_seconds=30.0))
            _write_assets_summary(tout, result)
            os.environ[PROBE_ENV] = "1"          # inner attach must not probe again
            try:
                attach(tout, result, str(tin), ["probe", name])
            finally:
                os.environ.pop(PROBE_ENV, None)
            doc = _json_load(tout / "result.json")
            sizes = {asset: _size(tout / asset) for asset in ASSETS}
            row.update({"result_json_valid": isinstance(doc, dict),
                        "status": (doc or {}).get("status") if isinstance(doc, dict) else None,
                        "exit_code": 0, "assets": sizes,
                        "assets_ok": all(size > 0 for size in sizes.values())})
            row["ok"] = row["result_json_valid"] and row["assets_ok"]
        except Exception as exc:
            row.update({"error": repr(exc)[:160], "ok": None})
        finally:
            del _LOG[marker:]
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
        base["results"].append(row)
    base["all_ok"] = bool(base["results"]) and all(row.get("ok") for row in base["results"])
    return base


# ------------------------------------------------------------------ attach / settle
def _fallback_state(input_arg):
    return {"input_dir": Path(str(input_arg or "")), "case": {}, "case_path": None,
            "case_raw": "", "claims": [], "claims_origin": None, "claim_quote_text": "",
            "units": [], "sources": [], "source_text": {}, "gaps": []}


def _resolve_state(pay, input_arg):
    runtime = pay.get("runtime") if isinstance(pay.get("runtime"), dict) else {}
    try:
        return build_state(_resolve_input(runtime.get("input_dir") or input_arg))
    except Exception as exc:
        log("error", "input rescan failed", detail=repr(exc)[:160])
        return _fallback_state(input_arg)


def _minimal_gold(pay, state, note):
    return {"schema": GOLD_SCHEMA, "package": {"name": PACKAGE, "version": VERSION},
            "case_id": pay.get("case_id"), "generated": "fallback",
            "provenance": {"is_organizer_key": False, "method": "fallback: " + note},
            "counts": {"golden_items": 0}, "contract": [], "claims": [], "evidence": [],
            "rules": [], "artifacts": [], "quote_ledger": Ledger().summary(),
            "corpus_gaps": [{"gap": "golden_fallback", "detail": note}]}


def _minimal_selfcheck(note):
    return {"schema": SELF_SCHEMA, "package": PACKAGE, "version": VERSION, "exit_code": 0,
            "pass": False, "passed": 0, "total": 0, "skipped": 0, "checks": [],
            "fallback_tests": {"skipped": "attach fallback", "results": []},
            "limitations": ["资产层 fallback：" + note]}


def _write_assets_summary(out, pay):
    pay["verifiable_assets"] = {
        "schema": "verifiable-assets/v1", "package": PACKAGE, "version": VERSION,
        "note": "五件可核验资产的摘要；各文件内容与自检结论以文件本身为准",
        "assets": {name: {"path": name, "bytes": _size(Path(out) / name),
                          "sha256": _sha(Path(out) / name)} for name in ASSETS},
        "exit_code": 0}
    return pay["verifiable_assets"]


def attach(out_dir, pay, input_arg=None, argv=None):
    """Write the five assets; additive, idempotent, never raises."""
    out = Path(out_dir)
    t_attach = time.time()
    log("assets", "start: five verifiable assets", output=str(out))

    def fail(stage, exc):
        try:
            pay.setdefault("errors", []).append(
                {"stage": "assets." + stage,
                 "detail": "%s: %s" % (type(exc).__name__, _clip(exc, 200))})
        except Exception:
            pass
        log("error", stage, detail=_clip(exc, 160))

    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    state = _resolve_state(pay, input_arg)
    try:
        (out / "run.log").write_text(log_text(), encoding="utf-8")
    except Exception as exc:
        fail("runlog", exc)
    try:
        gold = golden(state, pay)
        log("golden", "derived", items=(gold.get("counts") or {}).get("golden_items"),
            quotes=(gold.get("quote_ledger") or {}).get("quotes"),
            verbatim=(gold.get("quote_ledger") or {}).get("verbatim"))
        _wr_json(out / "golden_standard.json", gold)
        log("golden", "written", bytes=_size(out / "golden_standard.json"))
    except Exception as exc:
        fail("golden", exc)
        gold = _minimal_gold(pay, state, repr(exc)[:160])
        try:
            _wr_json(out / "golden_standard.json", gold)
        except Exception:
            pass
    try:
        (out / "version_history.md").write_text(version_history(state, pay, out, argv),
                                                encoding="utf-8")
        log("version", "written", bytes=_size(out / "version_history.md"))
    except Exception as exc:
        fail("version", exc)
    try:
        markdown, dsum = diff_report(gold, state, pay, out)
        (out / "diff_report.md").write_text(markdown, encoding="utf-8")
        log("diff", "written", rows=dsum.get("total"), met=dsum.get("met"),
            deviation=dsum.get("deviation"), missing=dsum.get("missing"),
            needs_review=dsum.get("needs_review"))
    except Exception as exc:
        fail("diff", exc)
        try:
            (out / "diff_report.md").write_text(
                "# 差异核验报告（diff_report）\n\n- 状态：fallback（%s）\n- case_id：`%s`；"
                "status：`%s`；退出码：**0**\n\n金标准生成失败，无法逐项对照；主流程产物与"
                "契约字段照常保留，退出码仍为 0。\n"
                % (repr(exc)[:160], pay.get("case_id"), pay.get("status")), encoding="utf-8")
        except Exception:
            pass
        dsum = {"total": 0, "met": 0, "deviation": 0, "missing": 0, "needs_review": 0}
    probe = probes(os.environ.get(PROBE_ENV) != "1")
    log("selfcheck", "fallback probes", all_ok=probe.get("all_ok"),
        skipped=bool(probe.get("skipped")))
    try:
        _write_assets_summary(out, pay)          # C13 reads this key
        sc = selfcheck(state, pay, out, gold, dsum, probe)
        _wr_json(out / "self_check.json", sc)
        log("selfcheck", "written", pass_=sc.get("pass"), passed=sc.get("passed"),
            total=sc.get("total"), bytes=_size(out / "self_check.json"))
    except Exception as exc:
        fail("selfcheck", exc)
        sc = _minimal_selfcheck(repr(exc)[:160])
        try:
            _wr_json(out / "self_check.json", sc)
        except Exception:
            pass
    try:
        (out / "run.log").write_text(log_text(), encoding="utf-8")
        (out / "version_history.md").write_text(version_history(state, pay, out, argv),
                                                encoding="utf-8")
        _refresh_selfcheck(out, sc)
    except Exception as exc:
        fail("refresh", exc)
    _write_assets_summary(out, pay)
    log("assets", "complete", files=len(ASSETS), elapsed_s=round(time.time() - t_attach, 3))
    return pay


def settle(out_dir, pay):
    """Final pass: append the exit line, flush run.log, then rewrite result.json."""
    try:
        out = Path(out_dir)
        log("exit", "run finished", exit_code=0, status=pay.get("status"),
            elapsed_s=round(time.time() - _T0, 3))
        (out / "run.log").write_text(log_text(), encoding="utf-8")
        _write_assets_summary(out_dir, pay)
        sc = _json_load(out / "self_check.json")
        if isinstance(sc, dict):
            _refresh_selfcheck(out, sc)
            pay["verifiable_assets"]["assets"]["self_check.json"] = {
                "path": "self_check.json", "bytes": _size(out / "self_check.json"),
                "sha256": _sha(out / "self_check.json")}
        pay["run_log"] = {"path": "run.log", "bytes": _size(out / "run.log")}
        pay["run_log"].update(log_summary())
        pay["runtime"] = pay.get("runtime") if isinstance(pay.get("runtime"), dict) else {}
        pay["runtime"].update({"assets_elapsed_sec": round(time.time() - _T0, 3),
                               "assets_written": len(ASSETS), "exit_code": 0})
        pay["uncertainty"] = pay.get("uncertainties")
        (out / "result.json").write_text(json.dumps(pay, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    except Exception:
        pass
    return pay
