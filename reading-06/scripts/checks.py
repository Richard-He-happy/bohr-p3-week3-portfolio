"""Pure-stdlib verification toolkit sitting behind the evidence ledger.

It folds text for comparison, finds verbatim quotes, checks digit and unit coverage,
classifies claim layers, builds grids from markdown/CSV (merged headers, continued
tables), reads PDF text on a best-effort basis and applies the per-field acceptance gate.
"""
import re
import zlib
import difflib

ALLOWED_STATES = ("reported", "not_reported", "source_conflict", "extraction_failed")
LOCATOR_FIELDS = ("source_id", "section", "paragraph_id", "page", "table_id", "row_header", "col_header", "figure_id", "locator")

_DASH_FOLD = {"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u2015": "-", "\u00ad": ""}
_GLYPH_FOLD = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " ", "\u2009": " ", "\u202f": " ", "\u00b5": "\u03bc",
          "\u00d7": "x", "\u00b1": "+/-", "\u2264": "<=", "\u2265": ">=", "\u200b": "", "\ufeff": ""}


def _condense(s):
    return re.sub(r"[\s\u00a0]+", "", fold_text(s).lower())


def _pdf_stream(body):
    m = re.search(rb"stream\r?\n", body)
    if not m:
        return b""
    end = body.find(b"endstream", m.end())
    raw = body[m.end():end if end > 0 else len(body)]
    if b"/FlateDecode" in body:
        try:
            return zlib.decompress(raw)
        except Exception:
            return b""
    return raw


def _pdf_text(raw):
    s = raw.decode("latin-1", "replace")
    lines, buf = [], []
    for m in re.finditer(r"\((?:[^()\\]|\\.)*\)|<[0-9A-Fa-f\s]{2,}>|T\*|Td|TD|TJ|Tj|ET", s):
        tok = m.group(0)
        if tok.startswith("("):
            buf.append(_pdf_unescape(tok[1:-1]))
        elif tok.startswith("<"):
            try:
                h = re.sub(r"\s", "", tok[1:-1])
                b = bytes.fromhex(h if len(h) % 2 == 0 else h + "0")
                buf.append(b.decode("utf-16-be", "ignore") if len(b) > 8 and b"\x00" in b else b.decode("latin-1", "ignore"))
            except Exception:
                pass
        elif tok in ("T*", "Td", "TD", "ET") and buf:
            lines.append("".join(buf))
            buf = []
    if buf:
        lines.append("".join(buf))
    return fold_text(" ".join(x.strip() for x in lines if x.strip()))


def _pdf_unescape(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n in "nrtbf":
                out.append({"n": "\n", "r": "\n", "t": "\t", "b": "", "f": ""}[n])
                i += 2
            elif n in "()\\":
                out.append(n)
                i += 2
            elif n.isdigit():
                j = 0
                while j < 3 and i + 1 + j < len(s) and s[i + 1 + j].isdigit():
                    j += 1
                try:
                    out.append(chr(int(s[i + 1:i + 1 + j], 8)))
                except Exception:
                    pass
                i += 1 + j
            else:
                i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _pipe_split(line):
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") else s
    return [p.replace("\\|", "|").strip() for p in re.split(r"(?<!\\)\|", s)]


def blocks_of_text(text):
    return [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]


def claim_layer(text):
    """Return claim layer, matched markers and hedging strength for one sentence."""
    t = " " + fold_text(text).lower() + " "
    hit = lambda ws: [w for w in ws if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", t)]
    hz, lm, cn = hit(HEDGE_TERMS), hit(LIMIT_TERMS), hit(STRONG_TERMS)
    ct = "limitation" if (lm and (len(lm) >= len(cn) or not cn)) else "speculation" if hz else "conclusion" if cn else "undetermined"
    return {"claim_type": ct, "hedges": hz, "limitation_markers": lm, "conclusion_markers": cn,
            "strength": "strong" if (cn and not hz) else ("hedged" if hz else "neutral")}


def content_words(s):
    return [t for t in re.findall(r"[A-Za-z\u0370-\u03ff][A-Za-z0-9\u0370-\u03ff\-]{1,}", s or "") if t.lower() not in SKIP_WORDS]


RELATED_TERMS = {
    "sample": ["samples", "specimens", "cohort", "replicates", "subjects", "n =", "n="],
    "size": ["n =", "total", "number of"],
    "temperature": ["temp", "celsius", "anneal", "heating", "cooling"],
    "composition": ["content", "concentration", "ratio", "fraction", "wt", "at"],
    "processing": ["treatment", "treated", "prepared", "synthesised", "synthesized", "fabricated"],
    "instrument": ["diffractometer", "microscope", "spectrometer", "measured using", "recorded on"],
    "metric": ["measured", "obtained", "yield", "efficiency", "strength", "modulus", "conductivity"],
    "error": ["sd", "sem", "standard deviation", "standard error", "confidence interval"],
    "significance": ["p =", "p <", "p<", "significant", "ns"],
    "baseline": ["control", "compared with", "compared to", "reference", "untreated", "vehicle"],
    "conclusion": ["conclude", "conclusion", "we show", "demonstrate", "suggest"],
    "limitation": ["limitation", "limited", "caveat", "further work", "cannot exclude"],
    "time": ["hour", "day", "week", "incubation", "min"],
}

UNIT_LEXICON = """% ‰ °C K h min s ms us ns d day days week weeks year years nm um mm cm m km mg ug ng pg g kg mol mmol umol nmol M mM uM nM
mL uL L ml ul l mg/L g/L ug/mL ug/ml ng/mL ng/ml mg/kg Pa kPa MPa GPa bar atm Torr psi N kN mN J kJ W kW mW V mV kV A mA uA Hz kHz MHz GHz
rpm g/mol Da kDa bp kb ppm ppb mol% at% wt% vol% IU CFU copies fold a.u. AU OD S/m mS/cm eV keV meV""".split()

UNIT_PATTERN = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted((re.escape(u) for u in UNIT_LEXICON), key=len, reverse=True)) + r")(?![A-Za-z])")
NUMBER_PATTERN = re.compile(r"[+\-]?\d+(?:[.,]\d+)*(?:\s*[x]\s*10\s*(?:\^|\*\*)?\s*[+\-]?\d+)?")

HEDGE_TERMS = ["may", "might", "could", "suggest", "appear", "seem", "likely", "unlikely", "probably", "possibly", "possible", "presumably",
         "potential", "potentially", "indicate", "imply", "speculate", "tentative", "candidate", "trend", "tendency", "is expected",
         "preliminary", "putative", "apparent", "consistent with", "we believe", "would"]
LIMIT_TERMS = ["limitation", "limited", "caveat", "however", "cannot exclude", "could not", "did not", "not determined", "remains unclear",
         "further work", "further studies", "future work", "small sample", "under these conditions", "only", "assumption", "uncertain",
         "does not", "do not", "was not", "were not", "no significant", "not statistically"]
STRONG_TERMS = ["conclude", "concluded", "conclusion", "we show", "shows", "showed", "demonstrate", "demonstrated", "reveal", "revealed", "confirm",
            "confirmed", "establish", "established", "we report", "find", "found", "evidence that", "therefore", "these results", "our results",
            "we attribute", "is attributed"]


def csv_tables(text, source_id="", page=None, id_prefix="C", table_id=None):
    import csv
    import io
    rows = [r for r in csv.reader(io.StringIO(text)) if any((c or "").strip() for c in r)]
    if len(rows) < 2:
        return []
    header_n = 2 if (len(rows) > 2 and not any(re.search(r"\d", c or "") for c in rows[0]) and not any(re.search(r"\d", c or "") for c in rows[1])) else 1
    return [make_table(rows, header_n, table_id or (id_prefix + "1"), "", page, source_id, ["csv"])]


def digits_covered(value, quote):
    """Check that each digit group of the value also occurs in the quote text."""
    vn = [n["key"] for n in number_spans(value)]
    qk = {n["key"] for n in number_spans(quote)}
    absent = [k for k in vn if k not in qk]
    return {"value_numbers": vn, "absent_from_quote": absent, "ok": not absent}


def condition_binding(field):
    """Check that the quote itself carries at least one experimental-condition word.

    Digits can match the quote while the sentence belongs to a neighbouring experiment, so
    this guard reports the value/condition binding and lets the caller record an uncertainty
    instead of silently accepting a plausible-looking mix-up.
    """
    cond, quote = field.get("condition"), field.get("quote")
    texts = [x for x in (quote if isinstance(quote, list) else [quote]) if isinstance(x, str)]
    if not isinstance(cond, dict) or not cond or not texts:
        return {"bound": None, "reason": "insufficient_material"}
    quote_words = set(content_words(" ".join(texts)))
    for slot in ("sample", "setting", "timepoint", "baseline"):
        words = [w for w in content_words(str(cond.get(slot) or "")) if len(w) > 1]
        overlap = sorted(quote_words.intersection(words))
        if overlap:
            return {"bound": True, "slot": slot, "overlap": overlap[:5]}
    return {"bound": False, "reason": "no condition word occurs in the quote"}


def find_quote(quote, hay):
    """Search a quote inside a passage: mode, score in [0, 1] and a snippet."""
    q = fold_text(quote)
    if not q:
        return {"match": "empty", "score": 0.0, "snippet": ""}
    h = fold_text(hay)
    i = h.find(q)
    if i >= 0:
        return {"match": "exact", "score": 1.0, "offset": i, "snippet": h[max(0, i - 60): i + len(q) + 60]}
    if q.lower() in h.lower():
        i = h.lower().find(q.lower())
        return {"match": "case_normalized", "score": 1.0, "offset": i, "snippet": h[max(0, i - 60): i + len(q) + 60]}
    if _condense(q) in _condense(h):
        return {"match": "whitespace_normalized", "score": 0.99, "offset": _condense(h).find(_condense(q)), "snippet": ""}
    qt, best = set(content_words(q.lower())), {"match": "missing", "score": 0.0, "snippet": ""}
    for sent in re.split(r"(?<=[.!?;])\s+", h):
        if len(sent) < 8:
            continue
        cov = len(qt & set(content_words(sent.lower()))) / float(len(qt) or 1)
        sc = round(0.5 * cov + 0.5 * difflib.SequenceMatcher(None, _condense(q)[:400], _condense(sent)[:400]).ratio(), 3)
        if sc > best["score"]:
            best = {"match": "partial", "score": sc, "snippet": sent[:400]}
    if best["score"] < 0.55:
        best["match"] = "missing"
    return best


def fold_text(s):
    """Comparison view of a string: glyphs folded, runs of space collapsed."""
    s = s or ""
    for k, v in _DASH_FOLD.items():
        s = s.replace(k, v)
    for k, v in _GLYPH_FOLD.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", " ", s).strip()


SKIP_WORDS = set("""a an the of in on for and or to with by from at as is are was were be been this that these those we our it its their
they them than then which where when what how not no nor but if into over under between among per via vs versus using used use also both all
any each other such more most less least can may might will would should could do does did""".split())


def gate_field(f, unit_hits, tbl, unc, pend):
    """Apply the acceptance gate to one field and return its final record.

    reported must carry a quote found verbatim at the cited locator, with every value digit
    inside it; not_reported must carry search_scope; source_conflict needs two quotes.
    """
    st, s = f.get("status"), f.get("source") or {}
    ck, rules = {"quote_match": None, "locator_verified": False}, []
    if st not in ALLOWED_STATES:
        rules.append("status_vocabulary")
        f["status"] = st = "extraction_failed"
    q = f.get("quote")
    qs = [x for x in ([q] if isinstance(q, str) else (q or [])) if isinstance(x, str) and x.strip()]
    if st == "reported":
        loc = ""
        for u in unit_hits:
            if s.get("paragraph_id") and u["paragraph_id"] == s["paragraph_id"]:
                loc = u["text"]
                s["source_id"] = s.get("source_id") or u["source_id"]
                s["section"] = s.get("section") or u.get("section")
                s["page"] = s.get("page") if s.get("page") is not None else u.get("page")
                break
        for t in tbl:
            if s.get("table_id") == t["table_id"]:
                for r in t["rows"]:
                    if not s.get("row_header") or r["row_header"] == s["row_header"]:
                        loc += " | ".join([t.get("caption") or "", " ".join(t["columns"]), r["row_header"]] + [v for v in r["cells"] if v])
        b = find_quote(qs[0], loc) if (qs and loc) else {"match": "missing", "score": 0}
        if not qs:
            rules.append("missing_quote")
            f["status"] = "extraction_failed"
        elif b["match"] == "missing":
            rules.append("quote_not_in_source")
            f["status"] = "extraction_failed"
            pend.append({"field_id": f["field_id"], "issue": "quote_not_found", "quote": qs[0][:160],
                         "action": "a human should re-read the cited passage"})
        else:
            ck["quote_match"], ck["locator_verified"] = b["match"], b["score"] >= 0.99
            if b["match"] == "partial":
                rules.append("quote_fuzzy")
                unc.append({"field_id": f["field_id"], "type": "quote_not_verbatim", "detail": "approximate match score %.2f" % b["score"], "best_sentence": b.get("snippet", "")[:250]})
        if f["status"] == "reported":
            nc = digits_covered(f.get("value") or "", " ".join(qs))
            ck["numbers"] = nc
            if not nc["ok"]:
                rules.append("value_number_not_in_quote")
                f["status"] = "extraction_failed"
                pend.append({"field_id": f["field_id"], "issue": "value_quote_mismatch", "detail": nc})
            hdr = " ".join(" ".join(t["columns"]) + " " + (t.get("caption") or "") for t in tbl if t["table_id"] == s.get("table_id"))
            uc = unit_present(f.get("units"), " ".join(qs), hdr)
            ck["units"] = uc
            if not uc["ok"]:
                rules.append("unit_not_in_source")
                unc.append({"field_id": f["field_id"], "type": "unit_not_in_quote", "unit": f.get("units"), "detail": "declared unit does not occur in the quote or its header"})
            c = f.get("condition")
            c = c if isinstance(c, dict) else ({"raw": c} if c else {})
            f["condition"], miss = c, [x for x in ("sample", "setting", "timepoint", "baseline") if not c.get(x)]
            f["condition_complete"] = not miss
            if miss:
                unc.append({"field_id": f["field_id"], "type": "condition_incomplete", "missing_slots": miss, "detail": "the value is quotable, yet the condition record is incomplete"})
            bind = condition_binding(f)
            ck["condition_binding"] = bind
            if bind.get("bound") is False:
                rules.append("condition_not_in_quote")
                unc.append({"field_id": f["field_id"], "type": "condition_not_bound_to_quote",
                            "detail": "value digits appear in the quote but no condition word does; re-check for a condition/value mix-up"})
    elif st == "not_reported" and not f.get("search_scope"):
        f["search_scope"] = {"sections_searched": sorted({u.get("section") or "unsectioned" for u in unit_hits}),
                             "tables_searched": [t["table_id"] for t in tbl], "note": "filled automatically: all sections and tables were scanned, no verbatim value found"}
        rules.append("search_scope_autofilled")
    elif st == "source_conflict":
        if len(qs) < 2:
            rules.append("conflict_needs_two_quotes")
            unc.append({"field_id": f["field_id"], "type": "conflict_underdocumented", "detail": "source_conflict requires a quote and a locator for each side"})
        pend.append({"field_id": f["field_id"], "issue": "source_conflict", "detail": "both printed values kept word for word; no averaging applied"})
    ck["rules_failed"] = rules
    f["source"], f["validation"] = {k: s.get(k) for k in LOCATOR_FIELDS}, ck
    return f
def join_continuations(tables):
    """Fuse a table that continues with an identical header onto the previous grid."""
    out = [dict(tables[0])] if tables else []
    for t in tables[1:]:
        prev = out[-1]
        same = [c.lower() for c in t["columns"]] == [c.lower() for c in prev["columns"]]
        cont = bool(re.search(r"continu|\(cont", (t.get("caption") or "") + " " + (prev.get("caption") or ""), re.I))
        if same and (cont or t.get("page") != prev.get("page")) and len(t["columns"]) > 1:
            base = len(prev["rows"])
            prev["rows"] = prev["rows"] + [dict(r, row_index=r["row_index"] + base) for r in t["rows"]]
            prev["n_rows"], prev["parse_flags"] = len(prev["rows"]), sorted(set(prev.get("parse_flags", []) + ["cross_page_merged"]))
            prev.setdefault("merged_from", []).append(t["table_id"])
        else:
            out.append(dict(t))
    return out


def make_table(raw_rows, header_n=1, table_id="T1", caption="", page=None, source_id="", parse_flags=None):
    """Turn a raw grid into column labels and row records carrying cell addresses."""
    header_n = max(1, min(header_n, len(raw_rows) - 1)) if len(raw_rows) > 1 else len(raw_rows)
    heads, width = raw_rows[:header_n], max(len(r) for r in raw_rows) if raw_rows else 0
    cols = []
    for c in range(width):
        parts = []
        for h in heads:
            v = h[c].strip() if c < len(h) else ""
            if v and v not in parts:
                parts.append(v)
        cols.append(" / ".join(parts) if parts else "col%d" % (c + 1))
    rows, carry, repeat = [], "", False
    for i, r in enumerate(raw_rows[header_n:]):
        cells = [c.strip() for c in r] + [""] * (width - len(r))
        if not any(cells):
            continue
        if [c.lower() for c in cells[:len(heads[-1])]] == [c.lower() for c in heads[-1]]:
            repeat = True
            continue
        merged = not cells[0] and bool(carry)
        if cells[0]:
            carry = cells[0]
        rows.append({"row_index": i, "row_header": cells[0] or carry, "cells": cells,
                     "merged_cell": merged or any(c in ('"', "''", "\u2033", "同上", "same") for c in cells[1:]),
                     "by_col": {cols[j]: cells[j] for j in range(width)}})
    return {"table_id": table_id, "caption": caption, "page": page, "source_id": source_id, "columns": cols,
            "n_header_rows": header_n, "rows": rows, "header_repeat_inside": repeat, "parse_flags": parse_flags or [], "n_rows": len(rows)}


def md_tables(text, source_id="", page=None, id_prefix="T"):
    tables, lines, i, k = [], text.splitlines(), 0, 0
    while i < len(lines):
        if lines[i].strip().startswith("|") and i + 1 < len(lines) and re.fullmatch(r"[\s:\-|]+", lines[i + 1].strip()) and "-" in lines[i + 1]:
            grid, j, seps = [], i, 0
            while j < len(lines) and lines[j].strip().startswith("|"):
                if re.fullmatch(r"[\s:\-|]+", lines[j].strip()):
                    seps += 1
                    j += 1
                    continue
                grid.append(_pipe_split(lines[j]))
                j += 1
            cap = ""
            for back in range(i - 1, max(-1, i - 4), -1):
                if lines[back].strip() and not lines[back].strip().startswith("|"):
                    cap = lines[back].strip() if re.match(r"^(table|tab\.|\u8868)", lines[back].strip(), re.I) else ""
                    break
            k += 1
            if grid:
                tables.append(make_table(grid, max(1, seps), "%s%d" % (id_prefix, k), cap, page, source_id, ["markdown"]))
            i = j
        else:
            i += 1
    return tables


def number_spans(s):
    """Every numeric literal as printed, paired with a digit-only comparison key."""
    out = []
    for m in NUMBER_PATTERN.finditer(fold_text(s)):
        key = re.sub(r"[^0-9.]", "", m.group(0)).strip(".")
        if key:
            out.append({"raw": m.group(0).strip(), "key": key})
    return out


def read_pdf(path):
    """Recover page text from a PDF without external libraries -> (pages, meta)."""
    data = open(path, "rb").read()
    meta = {"bytes": len(data), "has_font": b"/Font" in data, "encrypted": b"/Encrypt" in data, "pages": 0}
    objs = {}
    for m in re.finditer(rb"(\d+)\s+\d+\s+obj\b(.*?)endobj", data, re.S):
        objs.setdefault(int(m.group(1)), m.group(2))
    page_objs = sorted(n for n, b in objs.items() if re.search(rb"/Type\s*/Page[^s]", b))
    pages = []
    for pno, num in enumerate(page_objs, 1):
        body = objs[num]
        m = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)", body)
        raw = b""
        if m:
            for ref in re.findall(rb"(\d+)\s+\d+\s+R", m.group(1)):
                raw += _pdf_stream(objs.get(int(ref), b""))
        pages.append({"page": pno, "text": _pdf_text(raw or _pdf_stream(body))})
    if not pages:
        for i, m in enumerate(re.finditer(rb"stream\r?\n", data), 1):
            t = _pdf_text(_pdf_stream(data[max(0, m.start() - 400):]))
            if len(t) > 40:
                pages.append({"page": None, "text": t, "stream_index": i})
    meta["pages"], chars = len(pages), sum(len(p["text"]) for p in pages)
    meta["chars"] = chars
    if meta["encrypted"]:
        meta["quality"] = "encrypted"
    elif chars < 200 or not meta["has_font"]:
        meta["quality"] = "no_text_layer"
    elif chars / max(1, len(pages)) < 400:
        meta["quality"] = "low"
    else:
        meta["quality"] = "usable"
    return pages, meta


def unit_hits(s):
    return sorted({m.group(1) for m in UNIT_PATTERN.finditer(fold_text(s))})


def unit_present(unit_field, quote, extra=""):
    """Check that a declared unit shows up in the quote or the nearby header rows."""
    if not unit_field:
        return {"ok": True, "where": "no_unit_declared"}
    u = unit_hits(unit_field) or [str(unit_field).strip().lower()]
    hay = fold_text(quote + " " + extra).lower()
    return {"ok": any(x.lower() in hay for x in u), "checked": u, "where": "quote_or_header"}


