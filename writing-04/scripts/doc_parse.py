#!/usr/bin/env python3
"""Deterministic document helpers for the manuscript revision desk.

Block splitting for markdown/docx/pdf, verbatim quote lookup, format-integrity
counting, contract-key mapping, annotation rendering and the HTML preview.
Read-only with respect to the input tree; standard library only; also runnable on
its own with --version / --help."""
from __future__ import annotations

import argparse
import html as H
import json
import re
import sys
import zipfile, zlib
from pathlib import Path

ENGINE_VERSION = "1.1.0"
SKILL_NAME = "manuscript-revision-desk"
UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
KIND_BY_SUFFIX = {".md": "md", ".markdown": "md", ".txt": "txt", ".json": "json", ".csv": "csv",
      ".docx": "docx", ".pdf": "pdf", ".html": "html"}
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BLOCK_BREAK_RE = re.compile(r"^(#{1,6}\s|\||>|```|\$\$)")
ENTITY_ID_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]*)-P(\d{2,4})\b")

WHITESPACE_RE = re.compile(r"\s+")
ASCII_FOLD = {
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u00a0": " ",
    "\u2026": "...", "\u00ad": "", "\u200b": "",
}


def read_bytes(p):
    try:
        return Path(p).read_bytes()
    except Exception:
        return b""


def locator_of(block):
    """Small step of the local manuscript workflow; safe to run repeatedly. (locator_of)"""
    idx = block.get("index")
    bid = block.get("id")
    if block.get("l0"):
        return "block#%s id=%s lines %s-%s" % (idx, bid, block.get("l0"), block.get("l1"))
    return "block#%s id=%s (no line map)" % (idx, bid)


def canon(s):
    """Small step of the local manuscript workflow; safe to run repeatedly. (canon)"""
    if not isinstance(s, str):
        return ""
    s = "".join(ASCII_FOLD.get(ch, ch) for ch in s)
    return WHITESPACE_RE.sub(" ", s).strip()


def find_quote(text, quote):
    """Pure helper used by the four-phase revision desk; reads only already-checked inputs. (find_quote)"""
    if not isinstance(quote, str) or not quote.strip():
        return None
    if quote in text:
        return "exact"
    nq = canon(quote)
    if nq and nq in canon(text):
        return "whitespace-normalized"
    return None


def kind_of(p):
    k = KIND_BY_SUFFIX.get(Path(p).suffix.lower(), "other")
    h = read_bytes(p)[:5]
    return "pdf" if h.startswith(b"%PDF") else ("zip" if h.startswith(b"PK") and k != "docx" else k)


def find_key(d, *ns, default=None):
    if not isinstance(d, dict):
        return default
    for n in ns:
        for k, v in d.items():
            if n in str(k).lower():
                return v
    return default


def read_text(p):
    b = read_bytes(p)
    for e in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return b.decode(e)
        except Exception:
            pass
    return b.decode("utf-8", "replace")


def remove_annotation_blocks(text):
    """Keeps the run reproducible: identical inputs give identical receipt bytes. (remove_annotation_blocks)"""
    out = re.sub(r"\n\n<!--\s*ANN-START.*?ANN-END[^>]*-->", "", text, flags=re.S)
    return re.sub(r"<!--\s*ANN-START.*?ANN-END[^>]*-->\n?", "", out, flags=re.S)


def find_in_blocks(blocks, quote, min_len=6):
    """Pure helper used by the four-phase revision desk; reads only already-checked inputs. (find_in_blocks)"""
    res = {"ok": False, "mode": None, "block_index": None, "block_id": None,
           "locator": None, "quote_chars": 0}
    if not isinstance(quote, str):
        return res
    q = quote.strip()
    if len(q) < min_len:
        return res
    res["quote_chars"] = len(q)
    for i, b in enumerate(blocks):
        mode = find_quote(b.get("text", ""), q)
        if mode:
            res.update({"ok": True, "mode": mode, "block_index": i,
                        "block_id": b.get("id"), "locator": locator_of(b)})
            return res
    return res




ANN_SPAN_RE = re.compile(r"<!--\s*ANN-START.*?ANN-END[^>]*-->", re.S)


def annotation_ranges(text):
    return [(m.start(), m.end()) for m in ANN_SPAN_RE.finditer(text)]


def format_counts(t):
    """Offline utility that keeps the audit trail consistent across the phases. (format_counts)"""
    t = t or ""
    return {
        "headings": len(re.findall(r"(?m)^#{1,6}\s", t)),
        "heading_levels": sorted({len(h) for h in re.findall(r"(?m)^(#{1,6})\s", t)}),
        "h2_plus": len(re.findall(r"(?m)^#{2,6}\s", t)),
        "table_rows": len(re.findall(r"(?m)^\s*\|.*\|\s*$", t)),
        "display_formulas": t.count("$$") // 2,
        "inline_math": len(re.findall(r"(?<!\$)\$(?!\$)[^$\n]{1,90}\$(?!\$)", t)),
        "numbered_citations": len(re.findall(r"\[\d{1,3}(?:\s*[,;-]\s*\d{1,3})*\]", t)),
        "figure_refs": len(re.findall(r"(?i)\b(?:fig(?:ure)?s?\.?)\s*\d+", t)),
        "table_refs": len(re.findall(r"(?i)\btables?\s*\d+", t)),
        "words_ascii": len(re.findall(r"[A-Za-z][A-Za-z'\u2019\-]*", t)),
        "cjk_chars": len(re.findall(r"[\u4e00-\u9fff]", t)),
        "chars": len(t),
    }


STRUCTURE_KEYS = ["headings", "h2_plus", "table_rows", "display_formulas",
                "inline_math", "numbered_citations", "figure_refs", "table_refs"]


def change_log(c, chs, fr, pres):
    L = ["# Change log — %s" % c["case_id"], "", "Workorder `%s` · source `%s`"
         % (find_key(c["workorder"], "id", default="(none)"), (c["manuscript"] or {}).get("rel")), "",
         "| metric | value |", "|---|---|", "| accepted changes | %d |" % len(chs),
         "| facts verified / rejected | %d / %d |" % (fr["verified"], fr["rejected"]),
         "| original text byte-identical | %s |" % pres["byte_identical_to_source"],
         "| structural integrity preserved | %s |" % (pres.get("integrity") or {}).get("preserved"), ""]
    for ch in chs:
        L += ["## %s · %s" % (ch["change_id"], ch["target_id"]), "",
              "- operation `%s` at %s (%s); origin %s; needs human confirmation: %s"
              % (ch["operation"], ch["anchor"]["locator"], ch["anchor"]["position"], ch["origin"],
                 ch["needs_human"]),
              "- rationale: %s" % (ch["rationale"] or "(none)"), "",
              "**Before (verbatim source quote):**", "", "> " + ch["original_quote"].replace("\n", " "), "",
              "**After (inserted; source quote untouched):**", "", "> "
              + ch["annotation"].replace("\n", "\n> "), ""]
        L += ["- evidence: \"%s\" — %s (%s, %s)" % (re.sub(r"\s+", " ", e["quote"] or "")[:220], e["locator"],
                                                     e["source_id"],
                                                     "verified" if e["verified"] else "NOT VERIFIED")
              for e in ch["evidence"]]
        L.append("")
    return "\n".join(L + ["## Open items", "", "- fallback annotations awaiting review: %d"
                          % sum(1 for x in chs if x["needs_human"]),
                          "- unverified facts: %d" % fr["rejected"], ""])


def split_docx(path):
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return []
    out = []
    for seg in re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", xml, re.S):
        st = re.search(r'w:pStyle w:val="([^"]+)"', seg)
        txt = H.unescape("".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", seg, re.S))).strip()
        if not txt:
            continue
        hd = bool(st and re.search(r"(?i)heading|title", st.group(1)))
        lv = re.search(r"(\d)", st.group(1)) if hd else None
        out.append({"kind": "heading" if hd else "para", "l0": 0, "l1": 0,
                    "text": "#" * (int(lv.group(1)) if lv else 2) + " " + txt if hd else txt})
    return out


def preview(c, pub, chs):
    def inl(s):
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", H.escape(s))
        return re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", s)
    o = []
    for ln in pub.splitlines():
        m = HEADING_RE.match(ln.strip())
        if not ln.strip() or ln.startswith("<!--"):
            continue
        if m:
            o.append("<h%d>%s</h%d>" % (len(m.group(1)), H.escape(m.group(2)), len(m.group(1))))
        elif ln.startswith(">"):
            t = ln.lstrip("> ").strip()
            o.append('<blockquote class="%s">%s</blockquote>'
                     % ("ann" if re.match(r"^\**\s*(Editorial|FALLBACK|自动)", t) else "q", inl(t)))
        elif ln.strip().startswith("|"):
            cs = [x.strip() for x in ln.strip().strip("|").split("|")]
            if not all(re.match(r"^:?-{2,}:?$", x) for x in cs if x):
                o.append("<table><tr>%s</tr></table>" % "".join("<td>%s</td>" % inl(x) for x in cs))
        else:
            o.append("<p>%s</p>" % inl(ln.strip()))
    css = ("body{font:16px/1.6 Georgia,serif;max-width:860px;margin:30px auto;padding:0 20px}"
           ".b{background:#fff8e1;border-left:4px solid #f0b429;padding:10px 14px;font:14px Helvetica}"
           "blockquote.ann{background:#eef4ff;border-left:4px solid #3b6fd4;padding:8px 14px}"
           "blockquote.q{border-left:3px solid #ccc;padding:2px 14px;color:#444}td{border:1px solid #ccc;padding:3px 7px}")
    return ("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><title>Manuscript preview — %s"
            "</title><style>%s</style></head><body><div class='b'><strong>Preview — %s v%s</strong>. "
            "Original text preserved verbatim; highlighted blocks are editorial additions delimited in the "
            "source by <code>&lt;!-- ANN-START ... --&gt;</code>. Case %s. Export-inspection aid, not a "
            "journal submission file.</div><ul>%s</ul>%s</body></html>\n"
            % (H.escape(c["case_id"]), css, SKILL_NAME, ENGINE_VERSION, H.escape(c["case_id"]),
               "".join("<li>%s — %s</li>" % (x["change_id"], H.escape(x["target_id"])) for x in chs),
               "\n".join(o)))


def classify_contract_key(key):
    """Keeps the run reproducible: identical inputs give identical receipt bytes. (classify_contract_key)"""
    k = (key or "").lower()
    if "case" in k and "id" in k:
        return "case_id"
    if any(x in k for x in ("receipt", "\u56de\u6267")):
        return "receipts"
    if any(x in k for x in ("deliver", "manuscript", "artifact", "output", "\u4ea7\u7269", "\u7a3f")):
        return "deliverable"
    if any(x in k for x in ("preserv", "fact", "\u4e8b\u5b9e")):
        return "preserved_facts"
    if any(x in k for x in ("evidence", "source_map", "mapping", "citation_map", "\u8bc1\u636e")):
        return "evidence_map"
    if any(x in k for x in ("change", "revision", "revise", "log", "\u4fee\u6539", "\u8bb0\u5f55")):
        return "change_log"
    if any(x in k for x in ("uncert", "risk", "\u4e0d\u786e\u5b9a")):
        return "uncertainty"
    if any(x in k for x in ("version", "diff", "\u7248\u672c")):
        return "version_compare"
    return "unmapped"


def split_pdf(path):
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", read_bytes(path), re.S):
        try:
            data = zlib.decompress(m.group(1))
        except Exception:
            continue
        ch = re.findall(rb"\((?:\\.|[^()\\])*\)", data)
        if len(ch) < 5:
            continue
        txt = " ".join(re.sub(rb"\\([()\\])", rb"\1", re.sub(rb"\\[nrt]", b" ", c[1:-1])).decode("latin-1")
                       for c in ch)
        txt = re.sub(r"\s+", " ", txt).strip()
        if len(txt) > 60:
            out.append({"kind": "para", "text": txt, "l0": 0, "l1": 0})
    return out


def assign_ids(blocks, prefix):
    hits = [ENTITY_ID_RE.search(b["text"][:80]) for b in blocks]
    explicit = sum(1 for m in hits if m) >= 2
    n = 0
    for b, m in zip(blocks, hits):
        if explicit and m:
            b["id"] = m.group(1) + "-P" + m.group(2)
        elif b["kind"] in ("para", "quote", "table", "formula", "code"):
            n += 1
            b["id"] = "%s-P%03d" % (prefix, n)
        else:
            b["id"] = None
    return blocks, explicit


def integrity(source_text, built_text):
    """Deterministic helper of the offline revision pipeline; no network, stdlib only. (integrity)"""
    body = remove_annotation_blocks(built_text)
    a = format_counts(source_text)
    b = format_counts(body)
    changed = {k: {"source": a[k], "export": b[k]} for k in STRUCTURE_KEYS if a[k] != b[k]}
    return {
        "compared_on": "export without annotation blocks",
        "counters": {k: b[k] for k in STRUCTURE_KEYS},
        "preserved": not changed,
        "mismatches": changed,
        "original_text_intact": canon(source_text) == canon(body),
        "char_delta": b["chars"] - a["chars"],
    }


def fallback(block):
    q = re.sub(r"\s+", " ", (split_sentences(block["text"])[0] if split_sentences(block["text"]) else block["text"])[:220])
    if len(re.findall(r"[\u4e00-\u9fff]", block["text"])) > 4:
        body = ("自动兜底标注（工作流生成，未经 Agent 逐条校订，需人工确认）：本段陈述「%s」。现有材料未在同一"
                "处给出该陈述成立的边界条件与不确定度；在作者确认适用条件前，该陈述应仅按本稿报告的材料体系、"
                "工艺参数与测量条件理解，不得外推。" % q)
    else:
        body = ("FALLBACK EDITORIAL NOTE (workflow-generated, not reviewed item by item by the agent; needs "
                "author confirmation). The paragraph states: \"%s\" The supplied material does not state, at "
                "this location, the boundary conditions under which the statement holds or the uncertainty "
                "attached to it. Until the authors confirm them, the statement should be read as limited to "
                "the material system, process parameters and measurement conditions reported here, and "
                "should not be extrapolated beyond them." % q)
    return body, q


def split_md(raw):
    L, B, i, n = raw.splitlines(), [], 0, len(raw.splitlines())
    while i < n:
        s = L[i].strip()
        if not s:
            i += 1
            continue
        j = i
        if s.startswith("```") or s.startswith("$$"):
            close = s[:3] if s.startswith("```") else "$$"
            kd = "code" if close == "```" else "formula"
            j = i + 1
            while j < n and close not in L[j]:
                j += 1
        elif HEADING_RE.match(s):
            kd = "heading"
        else:
            kd = "table" if s[0] == "|" else "quote" if s[0] == ">" else "para"
            while s[0] in "|>" and j + 1 < n and L[j + 1].strip().startswith(s[0]):
                j += 1
            while j + 1 < n and L[j + 1].strip() and not BLOCK_BREAK_RE.match(L[j + 1].strip()):
                j += 1
        j = min(j, n - 1)
        B.append({"kind": kd, "text": "\n".join(L[i:j + 1]), "l0": i + 1, "l1": j + 1})
        i = j + 1
    return B


def extract(path, kind):
    if kind == "html":
        raw = re.sub(r"(?is)<(script|style).*?</\1>", "", read_text(path))
        raw = re.sub(r"(?i)<h(\d)[^>]*>(.*?)</h\1>", lambda m: "\n" + "#" * int(m.group(1)) + " " + m.group(2), raw)
        raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n\n", raw)
        return raw, split_md(H.unescape(re.sub(r"<[^>]+>", "", raw))), "native"
    if kind in ("md", "txt"):
        return read_text(path), split_md(read_text(path)), "native"
    if kind in ("docx", "pdf"):
        bl = split_docx(path) if kind == "docx" else split_pdf(path)
        return "\n\n".join(b["text"] for b in bl), bl, "reconstructed" + ("-degraded" if kind == "pdf" else "")
    raise ValueError("UNSUPPORTED_FORMAT: cannot import kind '%s' as a manuscript" % kind)


def split_sentences(text, limit=2):
    if not isinstance(text, str):
        return []
    parts = re.split(r"(?<=[.!?\u3002\uff01\uff1f])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()][:limit]


def numbers_in(text):
    """Pure helper used by the four-phase revision desk; reads only already-checked inputs. (numbers_in)"""
    if not isinstance(text, str):
        return []
    return re.findall(r"\d+(?:[.,]\d+)*", text)


def resolve(tid, blocks):
    tid = str(tid).strip()
    for i, b in enumerate(blocks):
        if b.get("id") == tid or tid in b["text"][:70]:
            return i, "explicit-label"
    m = re.search(r"P0*(\d+)$", tid)
    paras = [i for i, b in enumerate(blocks) if b["kind"] in ("para", "quote")]
    if m and 0 < int(m.group(1)) <= len(paras):
        return paras[int(m.group(1)) - 1], "ordinal"
    return None, "unresolved"


def ann_text(ch):
    rows = ["<!-- ANN-START %s target=%s -->" % (ch["id"], ch["tid"]),
            "> **Editorial annotation %s · target %s · added by the revision workflow, not part of the "
            "original text**" % (ch["id"], ch["tid"]), ">"]
    rows += ["> " + p.strip() if p.strip() else ">" for p in ch["after"].split("\n")]
    ev = [e for e in ch["ev"] if e["q"]][:3]
    if ev:
        rows += [">", "> *Basis:* " + " ; ".join('"%s" (%s)' % (re.sub(r"\s+", " ", e["q"])[:220],
                                                              e["loc"] or "source") for e in ev)]
    if ch["human"]:
        rows.append("> *Status:* provisional — needs author confirmation")
    return "\n".join(rows + ["<!-- ANN-END %s -->" % ch["id"]])




class Doc:
    def __init__(self, raw, blocks):
        self.raw, self.blocks = raw, blocks
        self.line_mode = all(b.get("l0") for b in blocks)

    def render(self, ann=True):
        if not self.line_mode:
            p = []
            for b in self.blocks:
                p.append(b["text"])
                p += [c["blk"] for c in b["ann"]] if ann else []
            return "\n\n".join(p) + "\n"
        L, out, cur = self.raw.splitlines(), [], 0
        for b in self.blocks:
            s, e = max(0, b["l0"] - 1), max(0, b["l1"])
            out += L[cur:s] + L[s:e]
            for c in b["ann"] if ann else []:
                out += [""] + c["blk"].splitlines()
            cur = e
        out += L[cur:]
        res = "\n".join(out)
        return res + "\n" if self.raw.endswith("\n") else res

    def apply(self, idx, ch):
        if idx is None or not (0 <= idx < len(self.blocks)):
            raise KeyError("TARGET_NOT_IN_WORKORDER: block %r is not a workorder target" % idx)
        if any(x["id"] == ch["id"] for x in self.blocks[idx]["ann"]):
            raise ValueError("DUPLICATE_CHANGE_ID: %s already applied" % ch["id"])
        self.blocks[idx]["ann"].append(ch)

    def rollback(self, cid):
        for b in self.blocks:
            for i, x in enumerate(b["ann"]):
                if x["id"] == cid:
                    return b["ann"].pop(i)
        raise LookupError("NOT_APPLIED: %s has no applied change" % cid)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="doc_parse.py",
        description="Read-only deterministic helpers: verbatim quote lookup, format integrity, "
                    "contract-key mapping; offline and standard library only.")
    ap.add_argument("--version", action="store_true", help="print version")
    a = ap.parse_args(argv)
    if a.version:
        print("doc_parse.py", ENGINE_VERSION)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
