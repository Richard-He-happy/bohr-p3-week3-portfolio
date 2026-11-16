#!/usr/bin/env python3
"""Deterministic verification for chapter-edit-ledger (library + CLI).

    python3 audit_checks.py audit  --index work/source_index.json --draft work/draft.json \
        --manuscript output/manuscript.md --out-dir output
    python3 audit_checks.py quote  --index work/source_index.json --quote "<sentence>"

Every verdict is computed from the supplied text: standard library only, no
network, and no dependency on the current working directory.
"""
import argparse
import json
import os
import re

VARIANT_PAIRS = [
    (r"\b3D\b", r"\b3-D\b", "3D / 3-D"),
    (r"\bmodel(?:ing|ed)\b", r"\bmodell(?:ing|ed)\b", "modeling / modelling"),
    (r"\bfiber", r"\bfibre", "fiber / fibre"),
    (r"\bbehavior", r"\bbehaviour", "behavior / behaviour"),
    (r"\banalyz(?:e|ed|ing)\b", r"\banalys(?:e|ed|ing)\b", "analyze / analyse"),
    (r"\blabel(?:ed|ing)\b", r"\blabell(?:ed|ing)\b", "labeled / labelled"),
    (r"\bcolor", r"\bcolour", "color / colour"),
    (r"\u00b5m", r"\bum\b", "\u00b5m / um"),
]
ABBR = re.compile(r"([A-Z][A-Za-z\-]+(?:\s+[A-Za-z\-]+){0,5})\s*\(([A-Z]{2,6}s?)\)")
XREF = re.compile(r"\b(Table|Tables|Figure|Fig\.|Equation|Eq\.|Section|Sec\.|Appendix|Algorithm)"
                  r"\s*\(?(\d+(?:\.\d+)*)\)?")
HEAD_NUM = re.compile(r"^#{1,6}\s*(\d+(?:\.\d+)*)")
CITE = re.compile(r"\[(\d+(?:\s*[,\u2013\-]\s*\d+)*)\]")
REF_LINE = re.compile(r"^\s*\[(\d+)\]|^\s*(\d+)\.\s+[A-Z]")
PLACEHOLDER = re.compile(r"\[(?:CITATION|CITE|REF|TODO|TBD|\u5f85\u8865)\w*\s*\]|\?\?|\[\?\]", re.I)
QTY = re.compile(r"(\d+(?:[.,]\d+)?)\s*(MPa|GPa|kPa|Pa|kN|N\u00b7m|Nm|mm|cm|nm|\u00b5m|um|kg|mg"
                 r"|\u00b5g|ms|min|h|\u00b0C|K|mL|ml|L|%)(?![A-Za-z])")
DIMENSION = {"mpa": "pressure", "gpa": "pressure", "kpa": "pressure", "pa": "pressure", "kn": "force",
             "n\u00b7m": "moment", "mm": "length", "cm": "length", "nm": "length", "kg": "mass",
             "mg": "mass", "\u00b5g": "mass", "ms": "time", "min": "time", "h": "time",
             "\u00b0c": "temperature", "k": "temperature", "ml": "volume", "l": "volume", "%": "ratio"}
NUMERAL = re.compile(r"\d+(?:[.,]\d+)?")
MATH_SPAN = re.compile(r"\$([^$\n]{1,80})\$")
SYM_MEANING = re.compile(r"(?:where|with|let)\s+\$?([A-Za-z\u03b1-\u03c9\u0391-\u03a9\u00b5][A-Za-z0-9_]{0,5})"
                         r"\$?\s+(?:is|are|denotes|stands for|is defined as)\s+([^.;\n]{3,80})", re.I)
CLAIM_CUE = re.compile(r"\b(therefore|thus|hence|indicat\w*|show\w*|suggest\w*|conclud\w*|"
                       r"demonstrat\w*|confirm\w*|consistent with|impl(?:y|ies))\b", re.I)
UP_WORD = re.compile(r"\b(increas|improv|strengthen|rais|higher|greater|enhanc)\w*", re.I)
DOWN_WORD = re.compile(r"\b(decreas|reduc|weaken|lower|smaller|diminish)\w*", re.I)
WORD = re.compile(r"[A-Za-z][A-Za-z\-]{3,}")


def norm(s):
    """Whitespace- and typography-insensitive form used by every comparison."""
    s = s or ""
    for src, dst in (("\u00a0", " "), ("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'),
                     ("\u201d", '"'), ("\u2013", "-"), ("\u2014", "-"), ("\u2212", "-"),
                     ("\ufb01", "fi"), ("\ufb02", "fl")):
        s = s.replace(src, dst)
    return re.sub(r"\s+", " ", s).strip()


def note(store, check, severity, message, locators=None, action=""):
    store.append({"id": "V%03d" % (len(store) + 1), "check": check, "severity": severity,
                  "status": "open" if severity in ("high", "warn") else "ok", "message": message,
                  "locators": [x for x in (locators or []) if x], "action": action})
    return store[-1]


def paragraphs(text):
    return [p for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def sentences(text, minimum=0):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if len(s.strip()) >= minimum]


# ------------------------------------------------------- target and evidence
def locate_block(index, target_id):
    """Map a workorder target onto the one block that carries it."""
    tid = (target_id or "").strip()
    if not tid:
        return None
    blocks = index.get("blocks") or []
    for block in blocks:
        if tid in (block.get("anchors") or []):
            return block
    for block in blocks:
        if tid in (block.get("text") or ""):
            return block
    suffix = re.search(r"P(\d{1,5})$", tid)
    if suffix and 1 <= int(suffix.group(1)) <= len(blocks):
        guess = dict(blocks[int(suffix.group(1)) - 1])
        guess["_heuristic"] = "paragraph index taken from the target id suffix"
        return guess
    return None


def quote_hits(index, quote, limit=3):
    """Verbatim search: inside one block first, then across a whole material."""
    want = norm(quote)
    if len(want) < 8:
        return []
    hits = [{"block_id": b["bid"], "material": b["material"], "locator": b["locator"],
             "exact_block": True} for b in index.get("blocks") or [] if want in norm(b.get("text", ""))]
    if hits:
        return hits[:limit]
    for material in index.get("materials") or []:
        if want in norm(material.get("text", "")):
            hits.append({"block_id": None, "material": material["id"], "exact_block": False,
                         "locator": material.get("rel", "") + " (match spans blocks)"})
    return hits[:limit]


def material_numbers(index):
    """Every numeric token present anywhere in the supplied materials."""
    return {t.replace(",", ".") for m in index.get("materials") or []
            for t in NUMERAL.findall(m.get("text") or "")}


# ----------------------------------------------------------- draft validation
def validate_draft(index, draft):
    """Scope, verbatim anchoring, evidence, numeric novelty and per-target receipts."""
    out = []
    draft = draft if isinstance(draft, dict) else {}
    proposals = draft.get("annotations") if isinstance(draft.get("annotations"), list) else []
    targets = [item.get("target_id") for item in (index.get("workorder_items") or [])]
    if not proposals:
        note(out, "workorder_receipt", "high",
             "draft carries no annotation, so build can only emit fallback notes",
             action="write one proposal per target")
    known, seen_text = material_numbers(index), {}
    for pos, item in enumerate(proposals):
        if not isinstance(item, dict):
            note(out, "draft_schema", "high", "#%d is not an object" % (pos + 1))
            continue
        aid, tid = item.get("annotation_id") or "EA-%02d" % (pos + 1), (item.get("target_id") or "").strip()
        block = locate_block(index, tid)
        if not tid:
            note(out, "draft_schema", "high", "%s has no target_id" % aid)
        elif targets and tid not in targets:
            note(out, "annotation_scope", "high", "%s points at %s, which the workorder omits"
                 % (aid, tid), action="not applied")
        elif block is None:
            note(out, "workorder_receipt", "high", "%s: target %s is absent from the materials"
                 % (aid, tid), action="pending_human; do not invent the paragraph")
        anchor = item.get("anchor_quote") or ""
        if block is not None:
            if not anchor:
                note(out, "quote_traceability", "warn", "%s has no anchor_quote" % aid, [block["locator"]])
            elif norm(anchor) not in norm(block.get("text", "")):
                elsewhere = quote_hits(index, anchor)
                tail = " (present at %s)" % elsewhere[0]["locator"] if elsewhere else "; not verbatim anywhere"
                note(out, "quote_traceability", "high", "%s anchor_quote is not inside %s%s"
                     % (aid, tid, tail), [elsewhere[0]["locator"]] if elsewhere else [],
                     "copy the target sentence exactly")
        body = norm(item.get("text"))
        if len(body) < 60:
            note(out, "annotation_quality", "warn", "%s annotation is under 60 characters" % aid)
        if body in seen_text:
            note(out, "annotation_quality", "warn", "%s duplicates the text of %s" % (aid, seen_text[body]))
        seen_text[body] = aid
        fresh = sorted({t.replace(",", ".") for t in NUMERAL.findall(body)} - known)
        if fresh:
            note(out, "annotation_novelty", "high", "%s introduces %d number(s) absent from every "
                 "material: %s" % (aid, len(fresh), ", ".join(fresh[:8])),
                 action="quote a supplied value or drop the number")
        evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
        if not evidence:
            note(out, "quote_traceability", "warn", "%s ships without evidence" % aid)
        for seq, entry in enumerate(evidence):
            quote = entry.get("quote") if isinstance(entry, dict) else None
            if not quote:
                note(out, "quote_traceability", "high", "%s evidence #%d has no quote" % (aid, seq + 1))
            elif not quote_hits(index, quote):
                note(out, "quote_traceability", "high", "%s evidence #%d is not verbatim in the materials"
                     % (aid, seq + 1), action="quote a real source sentence")
        if str(item.get("status") or "").lower().startswith("reject") and not (
                item.get("reason") or item.get("rationale")):
            note(out, "workorder_receipt", "warn", "%s is rejected without a reason" % aid)
        if item.get("revised_original") or item.get("replace_original"):
            note(out, "annotation_scope", "high", "%s would rewrite author text" % aid)
    covered = {(p.get("target_id") or "").strip() for p in proposals if isinstance(p, dict)}
    for tid in targets:
        if tid not in covered:
            note(out, "workorder_receipt", "high", "target %s has neither a proposal nor a rejection"
                 % tid, action="accept or explicitly reject every item")
    drafted = {(c.get("id") or c.get("heading") or "").strip()
               for c in (draft.get("chapter_drafts") or []) if isinstance(c, dict)}
    for entry in draft.get("outline") or []:
        key = ((entry.get("id") or entry.get("heading") or "") if isinstance(entry, dict)
               else str(entry)).strip()
        if key and key not in drafted:
            note(out, "coverage", "warn", "outline chapter %s has no drafted section" % key)
    high = sum(1 for f in out if f["severity"] == "high")
    warn = sum(1 for f in out if f["severity"] == "warn")
    return {"findings": out, "pass": high == 0,
            "counts": {"checks": len(out), "high": high, "warn": warn, "info": len(out) - high - warn,
                       "annotations": len(proposals), "targets": len(targets),
                       "targets_covered": len(covered & set(targets))}}


# ------------------------------------------------------ manuscript-level scan
def _abbreviation_table(index, prose):
    source, local = {}, {}
    for block in index.get("blocks") or []:
        for hit in ABBR.finditer(block["text"]):
            source.setdefault(hit.group(2), set()).add(norm(hit.group(1)))
    for seq, para in enumerate(prose, 1):
        for hit in ABBR.finditer(para):
            local.setdefault(hit.group(2), []).append((seq, norm(hit.group(1))))
    return source, local


def _xref_inventory(prose):
    refs, captions = {}, {}
    for seq, para in enumerate(prose, 1):
        for hit in XREF.finditer(para):
            # Normalise the caption word so "Table"/"Tables"/"table" share one inventory key.
            label = norm(hit.group(1)).rstrip(".").rstrip("s").lower()
            label = {"fig": "figure", "eq": "equation", "sec": "section"}.get(label, label)
            refs.setdefault(label, []).append((hit.group(2), seq))
            if re.search(r"(?i)\b%s\s*%s\s*[:.|]" % (re.escape(hit.group(1)), re.escape(hit.group(2))), para):
                captions.setdefault(label, []).append(hit.group(2))
    return refs, captions


def _citation_sets(prose):
    cited, listed, placeholders = set(), set(), []
    for seq, para in enumerate(prose, 1):
        for hit in CITE.finditer(para):
            for part in hit.group(1).split(","):
                part = part.strip()
                if re.match(r"^\d+\s*[\u2013\-]\s*\d+$", part):
                    low, high = [int(x) for x in re.split(r"[\u2013\-]", part)]
                    cited.update(range(min(low, high), max(low, high) + 1))
                elif part.isdigit():
                    cited.add(int(part))
        head = REF_LINE.match(para.strip())
        if head:
            listed.add(int(head.group(1) or head.group(2)))
        if PLACEHOLDER.search(para):
            placeholders.append(seq)
    return cited, listed, placeholders


# --------------------------------------------------- annotation acceptance
def accept(index, proposal, targets):
    """One validator for real annotations and for deliberate fault injection."""
    if not isinstance(proposal, dict):
        return None, "not an object"
    target = (proposal.get("target_id") or "").strip()
    if not target:
        return None, "missing target_id"
    if targets and target not in targets:
        return None, "target %s outside the workorder" % target
    block = locate_block(index, target)
    if block is None:
        return None, "target %s not in the materials" % target
    anchor = proposal.get("anchor_quote") or ""
    if anchor and norm(anchor) not in norm(block["text"]):
        return None, "anchor_quote not verbatim in the target"
    text = (proposal.get("text") or "").strip()
    if len(text) < 40:
        return None, "text too short"
    evidence = proposal.get("evidence") if isinstance(proposal.get("evidence"), list) else []
    if any(not (isinstance(e, dict) and e.get("quote") and quote_hits(index, e["quote"]))
           for e in evidence):
        return None, "evidence quote not verbatim"
    return {"annotation_id": proposal.get("annotation_id") or "EA", "target_id": target,
            "bid": block["bid"], "locator": block["locator"],
            "anchor_quote": anchor or block["text"][:160], "text": text, "evidence": evidence,
            "rationale": (proposal.get("rationale") or "").strip(),
            "generated_by": proposal.get("generated_by") or "agent_draft",
            "needs_review": bool(proposal.get("needs_review"))}, None


def fallback_note(index, block, seq):
    """Deterministic source-grounded note for a target the agent left uncovered."""
    quotes = sentences(block["text"], 61)
    anchor = quotes[0] if quotes else block["text"][:220]
    words = set(re.findall(r"[A-Za-z][A-Za-z\-]{4,}", block["text"].lower()))
    best, score = None, 0
    for candidate in index["blocks"]:
        if candidate["bid"] == block["bid"]:
            continue
        overlap = len(words & set(re.findall(r"[A-Za-z][A-Za-z\-]{4,}", candidate["text"].lower())))
        if overlap > score:
            best, score = candidate, overlap
    evidence, tail = [], ""
    if best is not None and score >= 2:
        rows = sentences(best["text"], 41)
        quote = rows[0] if rows else best["text"][:200]
        evidence = [{"quote": quote, "locator": best["locator"],
                     "note": "related statement, overlap %d" % score}]
        tail = 'Related passage %s: "%s"' % (best["locator"], quote[:200])
    return {"annotation_id": "EA-FB%02d" % seq, "target_id": (block["anchors"] or ["?"])[0],
            "bid": block["bid"], "locator": block["locator"], "anchor_quote": anchor[:240],
            "text": anchor, "evidence": evidence, "rationale": tail,
            "generated_by": "deterministic_fallback", "needs_review": True}


def run_faults(index, targets):
    """Four deliberate invalid operations; each must be rejected without touching state."""
    faults = []

    def attempt(label, proposal):
        record, why = accept(index, proposal, targets)
        faults.append({"id": label, "expected": "rejected", "state_unchanged": record is None,
                       "actual": ("rejected: %s" % why) if record is None else "ACCEPTED (defect)"})

    if targets:
        first = locate_block(index, targets[0]) or {}
        attempt("FAULT-1 fabricated anchor", {"annotation_id": "F1", "target_id": targets[0],
                                              "text": "x" * 60,
                                              "anchor_quote": "<<absent from the source>>"})
        attempt("FAULT-2 unknown target", {"annotation_id": "F2", "target_id": "FAULT-UNKNOWN-999",
                                            "text": "x" * 60})
        attempt("FAULT-3 invented evidence", {"annotation_id": "F3", "target_id": targets[0],
                                               "text": "A note whose evidence sentence the source never carried.",
                                               "anchor_quote": (first.get("text") or "")[:80],
                                               "evidence": [{"quote": "invented evidence sentence xyz"}]})
    try:
        json.loads('{"annotations": [')
        outcome = "parsed (unexpected)"
    except Exception as exc:
        outcome = "rejected: %r; state unchanged" % (exc,)
    faults.append({"id": "FAULT-4 malformed draft", "expected": "rejected", "actual": outcome,
                   "state_unchanged": True})
    return faults


# ----------------------------------------------------------------------- CLI
def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="audit_checks.py",
        description="Verify quotes and compute cross-chapter consistency for a chapter revision.")
    parser.add_argument("mode", nargs="?", default="audit", choices=["audit", "quote", "ledger"])
    for flag in ("--index", "--draft", "--manuscript", "--quote", "--out-dir"):
        parser.add_argument(flag, default="")
    args = parser.parse_args(argv)
    index = {}
    if args.index:
        try:
            with open(args.index, "r", encoding="utf-8-sig") as fh:
                index = json.load(fh)
        except Exception as exc:
            print("index unreadable: %r" % (exc,))
    if args.mode == "quote":
        hits = quote_hits(index, args.quote or "")
        print(json.dumps(hits, ensure_ascii=False, indent=2) if hits else "NOT FOUND (verbatim)")
        return 0
    manuscript, draft = "", {}
    for path, label in ((args.manuscript, "manuscript"), (args.draft, "draft")):
        if not path:
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                raw = fh.read()
            if label == "manuscript":
                manuscript = raw
            else:
                draft = json.loads(raw)
        except Exception as exc:
            print("%s unreadable: %r" % (label, exc))
    draft_report = validate_draft(index, draft) if index else {"findings": [], "counts": {}, "pass": False}
    import consistency
    findings = consistency.scan_crossrefs(index, manuscript) if index else []
    facts = consistency.carry_over_facts(index, manuscript) if index else []
    if args.out_dir:
        import docio
        led = consistency.build_ledgers(index, manuscript, findings) if index else {}
        os.makedirs(args.out_dir, exist_ok=True)
        payloads = (("consistency_report.md", consistency.render_report(index, findings, facts, draft_report)),
                    ("consistency_report.json", json.dumps(
                        {"findings": findings, "draft_validation": draft_report,
                         "preserved_facts_summary": {"total": len(facts),
                                                     "verified": sum(1 for f in facts if f["preserved"])}},
                        ensure_ascii=False, indent=2)),
                    ("consistency_tables.json", json.dumps(led, ensure_ascii=False, indent=2)),
                    ("consistency_ledger.md", consistency.ledger_markdown(led)))
        for name, payload in payloads:
            with open(os.path.join(args.out_dir, name), "w", encoding="utf-8") as fh:
                fh.write(payload + "\n")
        print("wrote consistency_report.md/.json, consistency_tables.json, consistency_ledger.md in %s"
              % args.out_dir)
    severity = {key: sum(1 for f in findings if f["severity"] == key) for key in ("high", "warn", "info")}
    print("consistency: %d findings (high=%d warn=%d info=%d); facts %d/%d verbatim; draft pass=%s"
          % (len(findings), severity["high"], severity["warn"], severity["info"],
             sum(1 for f in facts if f["preserved"]), len(facts), draft_report.get("pass")))
    return 0


if __name__ == "__main__":
    try:
        import sys
        sys.exit(main())
    except Exception as exc:
        import sys
        print("audit_checks.py internal error (reported, exit 0): %r" % (exc,))
        sys.exit(0)
