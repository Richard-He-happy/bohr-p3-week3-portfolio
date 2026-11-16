#!/usr/bin/env python3
"""Cross-chapter consistency for chapter-edit-ledger: scan, facts and six ledgers.

Imported by run_revision.py and by the audit_checks.py CLI.  Nothing here writes
files, so the same functions serve the live workflow and an offline replay.

    from consistency import scan_crossrefs, carry_over_facts, build_ledgers
"""
import re

from docio import table
from audit_checks import (ABBR, CLAIM_CUE, CITE, DIMENSION, DOWN_WORD, HEAD_NUM, MATH_SPAN,
                          PLACEHOLDER, QTY, REF_LINE, SYM_MEANING, UP_WORD, VARIANT_PAIRS, WORD,
                          XREF, _abbreviation_table, _citation_sets, _xref_inventory, norm,
                          note, paragraphs, sentences)


# ------------------------------------------------------ manuscript-level scan
def scan_crossrefs(index, manuscript_text):
    """Terminology, numbering, citation, unit and value checks over the assembled text."""
    out, prose = [], paragraphs(manuscript_text)
    source_abbr, local_abbr = _abbreviation_table(index, prose)
    for abbr, expansions in sorted(source_abbr.items()):
        if len(expansions) > 1:
            note(out, "terminology", "high", "%s carries %d expansions in the source: %s"
                 % (abbr, len(expansions), "; ".join(sorted(expansions))), ["source materials"],
                 "keep the source wording; the author decides")
    for abbr, seen in sorted(local_abbr.items()):
        if len(seen) > 1:
            same = len({exp for _, exp in seen}) == 1
            note(out, "terminology", "warn" if same else "high", "%s defined %d times (%s)"
                 % (abbr, len(seen), "same expansion" if same else "different expansions"),
                 ["manuscript \u00b6%d" % seq for seq, _ in seen])
    for abbr in sorted(set(source_abbr) | set(local_abbr)):
        uses = [seq for seq, para in enumerate(prose, 1) if re.search(r"\b%s\b" % re.escape(abbr), para)]
        defs = [seq for seq, _ in local_abbr.get(abbr, [])]
        if uses and defs and min(uses) < min(defs):
            note(out, "terminology", "warn", "%s first used in \u00b6%d but defined in \u00b6%d"
                 % (abbr, min(uses), min(defs)))
    for left, right, label in VARIANT_PAIRS:
        first = [seq for seq, para in enumerate(prose, 1) if re.search(left, para)]
        second = [seq for seq, para in enumerate(prose, 1) if re.search(right, para)]
        if first and second:
            note(out, "terminology", "warn", "two spellings coexist: %s" % label,
                 ["manuscript \u00b6%d" % first[0], "manuscript \u00b6%d" % second[0]],
                 "unify the spelling only, never the claim")
    refs, captions = _xref_inventory(prose)
    for label in ("table", "figure", "equation"):
        numbers = sorted({int(n) for n, _ in refs.get(label, []) if n.isdigit()})
        gaps = [n for n in range(1, numbers[-1] + 1) if n not in numbers] if numbers else []
        if gaps:
            note(out, "numbering", "info", "%s numbering skips %s"
                 % (label, ", ".join(map(str, gaps))), ["numbering inventory"])
        for number in sorted({n for n in captions.get(label, []) if captions[label].count(n) > 1}):
            note(out, "numbering", "warn", "two %s captions share number %s" % (label, number),
                 sorted({"manuscript \u00b6%d" % seq for num, seq in refs.get(label, []) if num == number})[:4])
    headings = {hit.group(1) for para in prose for hit in [HEAD_NUM.match(para.strip())] if hit}
    for number, seq in refs.get("section", []):
        if headings and number not in headings:
            note(out, "numbering", "warn", "'Section %s' matches no heading" % number,
                 ["manuscript \u00b6%d" % seq], "fix the cross-reference")
    cited, listed, placeholders = _citation_sets(prose)
    for seq in placeholders:
        note(out, "citation", "high", "unresolved citation placeholder",
             ["manuscript \u00b6%d" % seq], "pending_human; never invent a reference")
    if listed:
        missing, unused = sorted(c for c in cited if c not in listed), sorted(r for r in listed if r not in cited)
        if missing:
            note(out, "citation", "high", "cited but absent from the reference list: %s" % missing[:12],
                 ["reference list"], "restore the entry or drop the citation")
        if unused:
            note(out, "citation", "info", "reference entries never cited: %s" % unused[:12])
    elif cited:
        note(out, "citation", "info", "%d citation numbers carried verbatim; the materials hold no "
             "reference list" % len(cited), action="the author confirms the bibliography")
    grouped = {}
    for seq, para in enumerate(prose, 1):
        # A stated range ("from 28.5 MPa to 41.2 MPa", "between 0.05 % and 0.25 %") is not
        # a conflict, so every endpoint inside such a span is skipped.
        spans = [m.span() for m in re.finditer(r"\bfrom\b.{0,60}?\bto\b", para)]
        spans += [m.span() for m in re.finditer(r"\bbetween\b.{0,60}?\band\b", para)]
        spans += [m.span() for m in re.finditer(r"(?:\u4ece|\u7531|\u5728|\u4ecb\u4e8e).{0,40}?"
                                                r"(?:\u5230|\u81f3|~|\uff5e)", para)]
        spans += [m.span() for m in re.finditer(r"\d[\d.,]*\s*%?\s*(?:\u81f3|\u5230|~|\uff5e|to)\s*\d", para)]
        for hit in QTY.finditer(para):
            if any(a <= hit.start() < b for a, b in spans):
                continue
            context = " ".join(re.findall(r"[A-Za-z][A-Za-z\-]{3,}",
                                          norm(para[max(0, hit.start() - 60):hit.start()]).lower())[-3:])
            grouped.setdefault((context, DIMENSION.get(hit.group(2).lower(), "other")), []).append(
                (hit.group(1).replace(",", "."), hit.group(2), seq))
    for (context, dimension), occurrences in sorted(grouped.items()):
        pairs = {(value, unit) for value, unit, _ in occurrences}
        if len({v for v, _ in pairs}) > 1 and len({u for _, u in pairs}) == 1:
            note(out, "numeric_conflict", "warn", "different values for '%s': %s"
                 % (context or "context", ", ".join("%s %s" % p for p in sorted(pairs))),
                 sorted({"manuscript \u00b6%d" % seq for _, _, seq in occurrences}),
                 "keep both; never correct silently")
        units = {unit for _, unit, _ in occurrences}
        if len(units) > 1 and dimension in ("pressure", "length", "temperature"):
            note(out, "units", "info", "mixed units for '%s': %s"
                 % (context or "context", ", ".join(sorted(units))))
    return out


def carry_over_facts(index, manuscript_text, limit=90):
    """Facts worth tracking: sentences carrying a value, a citation or a defined term."""
    out, seen, haystack = [], set(), norm(manuscript_text)
    for block in index.get("blocks") or []:
        for sentence in sentences(block["text"], 12):
            kinds = [kind for kind, pattern in (("measurement", QTY), ("citation", CITE),
                                                ("term", ABBR)) if pattern.search(sentence)]
            if not kinds or sentence[:70] in seen:
                continue
            seen.add(sentence[:70])
            out.append({"fact_id": "F%03d" % (len(out) + 1), "kind": kinds[0], "quote": sentence,
                        "source_locator": block["locator"], "preserved": sentence[:70] in haystack,
                        "note": "verbatim carry-over; annotations must not alter it"})
            if len(out) >= limit:
                return out
    return out


def build_ledgers(index, manuscript_text, findings=None):
    """Terms, symbols, definitions, numbering, citations and conclusion claims.

    The skill's own addition: a table with locators, not a verdict.  Conflicts keep
    both sides so a reviewer can re-read them; nothing is resolved automatically.
    """
    blocks, prose = index.get("blocks") or [], paragraphs(manuscript_text)
    led = {"case_id": index.get("case_id"),
           "basis": "computed from work/source_index.json materials and the assembled manuscript",
           "terms": [], "symbols": [], "definitions": [], "numbering": {}, "citations": {},
           "claims": [], "conflicts": [], "counts": {},
           "limits": ["A row records what the text says, not whether the claim is true.",
                      "Whether an annotation is entailed by its quote is not machine-judged.",
                      "An absent row means the pattern was not found, not that nothing exists."]}
    source_abbr, local_abbr = _abbreviation_table(index, prose)
    for abbr in sorted(set(source_abbr) | set(local_abbr)):
        uses = [b for b in blocks if re.search(r"\b%s\b" % re.escape(abbr), b["text"])]
        expansions = sorted(source_abbr.get(abbr, set()))
        led["terms"].append({"term": abbr, "expansions": expansions,
                             "definitions_in_manuscript": [seq for seq, _ in local_abbr.get(abbr, [])],
                             "use_count": len(uses),
                             "first_locator": uses[0]["locator"] if uses else None,
                             "conflict": "multiple expansions" if len(expansions) > 1 else None})
        if len(expansions) > 1:
            led["conflicts"].append({"category": "terms", "key": abbr, "sides": expansions,
                                     "locators": [b["locator"] for b in uses][:4],
                                     "resolution": "reported, not corrected"})
    symbols = {}
    for block in blocks:
        for span in MATH_SPAN.findall(block["text"]) + [block["text"]]:
            for hit in SYM_MEANING.finditer(span):
                symbols.setdefault(hit.group(1), set()).add(norm(hit.group(2)))
    for symbol, meanings in sorted(symbols.items()):
        led["symbols"].append({"symbol": symbol, "meanings": sorted(meanings),
                               "single_meaning": len(meanings) == 1,
                               "sources": [b["locator"] for b in blocks if symbol in b["text"]][:3]})
        if len(meanings) > 1:
            led["conflicts"].append({"category": "symbols", "key": symbol,
                                     "sides": sorted(meanings), "locators": [],
                                     "resolution": "reported; the author fixes the notation"})
    defined = {}
    for seq, para in enumerate(prose, 1):
        for hit in ABBR.finditer(para):
            defined.setdefault(hit.group(2), []).append({"definition": norm(hit.group(1)),
                                                         "manuscript_block": seq})
    for label in sorted(defined):
        entries = defined[label]
        distinct = len({e["definition"] for e in entries})
        led["definitions"].append({"label": label, "count": len(entries), "distinct_wording": distinct,
                                   "entries": entries[:4],
                                   "status": "single definition" if len(entries) == 1 else
                                             ("repeated identically" if distinct == 1
                                              else "redefined with different wording")})
    refs, captions = _xref_inventory(prose)
    for label in ("table", "figure", "equation", "section", "appendix", "algorithm"):
        numbers = sorted({n for n, _ in refs.get(label, [])})
        dupes = sorted({n for n in captions.get(label, []) if captions[label].count(n) > 1})
        gaps = ([n for n in range(1, int(numbers[-1]) + 1) if str(n) not in numbers]
                if numbers and numbers[-1].isdigit() else [])
        led["numbering"][label] = {"referenced": numbers,
                                   "caption_numbers": sorted(set(captions.get(label, []))),
                                   "caption_duplicates": dupes, "gaps": gaps}
        if dupes:
            led["conflicts"].append({"category": "numbering", "key": label, "sides": dupes,
                                     "locators": [], "resolution": "two captions claim one number"})
    cited, listed, placeholders = _citation_sets(prose)
    led["citations"] = {"cited": sorted(cited), "listed": sorted(listed),
                        "missing_from_list": sorted(c for c in cited if c not in listed),
                        "never_cited": sorted(r for r in listed if r not in cited),
                        "placeholder_blocks": placeholders, "has_reference_list": bool(listed)}
    if led["citations"]["missing_from_list"]:
        led["conflicts"].append({"category": "citations", "key": "cited but unlisted",
                                 "sides": led["citations"]["missing_from_list"],
                                 "locators": ["reference list"],
                                 "resolution": "flagged for the author; no entry invented"})
    claims, words = [], {}
    for block in blocks:
        if len(claims) >= 60:
            break
        for sentence in sentences(block["text"], 40):
            if not CLAIM_CUE.search(sentence) or len(claims) >= 60:
                continue
            polarity = "up" if UP_WORD.search(sentence) else ("down" if DOWN_WORD.search(sentence) else "flat")
            claims.append({"claim_id": "K%03d" % (len(claims) + 1), "locator": block["locator"],
                           "quote": sentence[:400], "has_quantity": bool(QTY.search(sentence)),
                           "polarity": polarity})
            if len(WORD.findall(sentence.lower())) >= 5:
                words[claims[-1]["claim_id"]] = set(WORD.findall(sentence.lower()))
    by_id = {c["claim_id"]: c for c in claims}
    keys = list(words)
    for pos, left in enumerate(keys):
        for right in keys[pos + 1:]:
            shared = words[left] & words[right]
            if len(shared) >= 3 and by_id[left]["polarity"] != by_id[right]["polarity"] and \
                    "flat" not in (by_id[left]["polarity"], by_id[right]["polarity"]):
                led["conflicts"].append({"category": "claims", "key": ", ".join(sorted(shared)[:4]),
                                         "sides": [by_id[left]["quote"][:160], by_id[right]["quote"][:160]],
                                         "locators": [by_id[left]["locator"], by_id[right]["locator"]],
                                         "resolution": "opposite direction on shared vocabulary; "
                                                       "the author confirms intent"})
    led["claims"] = claims
    led["counts"] = {"terms": len(led["terms"]), "symbols": len(led["symbols"]),
                     "definitions": len(led["definitions"]), "claims": len(claims),
                     "conflicts": len(led["conflicts"]),
                     "checks_high": sum(1 for f in (findings or []) if f.get("severity") == "high")}
    return led


def ledger_markdown(led):
    """Render the ledger for a human reader; JSON stays the machine copy."""
    out = ["# Consistency ledger", "",
           "Six ledgers over the supplied materials and the assembled manuscript. Every row keeps "
           "a locator; each conflict lists both sides and is never resolved here.", "", "## 1. Terms", ""]
    out += table(["term", "source expansion", "uses", "first locator", "conflict"],
                 [[r["term"], "; ".join(r["expansions"]) or "-", r["use_count"],
                   r.get("first_locator") or "-", r.get("conflict") or "-"] for r in led.get("terms") or []],
                 ["no abbreviation pattern found"] + ["-"] * 4)
    out += ["", "## 2. Symbols", ""]
    out += table(["symbol", "meaning in the text", "single meaning"],
                 [[r["symbol"], "; ".join(r["meanings"]), r["single_meaning"]]
                  for r in led.get("symbols") or []], ["no 'where X is ...' pattern"] + ["-"] * 2)
    out += ["", "## 3. Definitions", ""]
    out += table(["label", "occurrences", "distinct wording", "status"],
                 [[r["label"], r["count"], r["distinct_wording"], r["status"]]
                  for r in led.get("definitions") or []], ["nothing defined"] + ["-"] * 3)
    out += ["", "## 4. Numbering", ""]
    out += table(["label", "referenced", "captions", "duplicates", "gaps"],
                 [[label, ", ".join(r["referenced"]) or "-", ", ".join(r["caption_numbers"]) or "-",
                   ", ".join(r["caption_duplicates"]) or "-",
                   ", ".join(str(g) for g in r["gaps"]) or "-"]
                  for label, r in sorted((led.get("numbering") or {}).items())], ["none"] + ["-"] * 4)
    cit = led.get("citations") or {}
    out += ["", "## 5. Citations", "",
            "- cited: %s" % (", ".join(map(str, cit.get("cited") or [])) or "none"),
            "- listed: %s" % (", ".join(map(str, cit.get("listed") or [])) or "no reference list supplied"),
            "- cited but unlisted: %s" % (", ".join(map(str, cit.get("missing_from_list") or [])) or "none"),
            "- listed but never cited: %s" % (", ".join(map(str, cit.get("never_cited") or [])) or "none"),
            "", "## 6. Conclusion-bearing claims", ""]
    out += table(["id", "polarity", "quantity", "locator", "quote"],
                 [[r["claim_id"], r["polarity"], "yes" if r["has_quantity"] else "no", r["locator"],
                   r["quote"][:110]] for r in (led.get("claims") or [])[:25]],
                 ["no conclusion cue found"] + ["-"] * 4)
    out += ["", "## 7. Conflicts", ""]
    out += (["- **%s / %s**: %s - %s" % (r["category"], r["key"],
                                         " | ".join(str(s)[:150] for s in r["sides"]),
                                         r.get("resolution") or "") for r in led.get("conflicts") or []]
            or ["- none detected by the implemented patterns"])
    out += ["", "## 8. Limits", ""] + ["- %s" % item for item in led.get("limits") or []] + [""]
    return "\n".join(out)


def render_report(index, findings, facts, draft_report=None):
    """Human-readable consistency report built only from computed data."""
    out = ["# Cross-chapter consistency report", "",
           "Produced by `chapter-edit-ledger` from the supplied files; every count and locator "
           "below was computed, not asserted.", "", "## 1. Materials read", ""]
    out += table(["id", "file", "kind", "blocks", "extraction"],
                 [[m["id"], m["rel"], m["kind"], m.get("blocks_n", 0), m.get("extraction", "")]
                  for m in index.get("materials") or []], ["none"] + ["-"] * 4)
    out += ["", "## 2. Findings", ""]
    out += table(["id", "check", "severity", "message", "locators"],
                 [[f["id"], f["check"], f["severity"], f["message"],
                   "<br>".join(f["locators"]) or "-"] for f in findings],
                 ["-", "-", "ok", "no inconsistency found by the implemented checks", "-"])
    severity = {key: sum(1 for f in findings if f["severity"] == key) for key in ("high", "warn", "info")}
    out += ["", "**Totals:** %d checks - %d high, %d warn, %d info."
            % (len(findings), severity["high"], severity["warn"], severity["info"]), "",
            "## 3. Preserved facts", "",
            "%d facts tracked; %d verified verbatim in the manuscript."
            % (len(facts), sum(1 for f in facts if f["preserved"]))]
    out += ["- **%s not preserved** `%s` (%s)" % (f["fact_id"], f["quote"][:100], f["source_locator"])
            for f in [x for x in facts if not x["preserved"]][:12]]
    if draft_report and draft_report.get("counts"):
        counts = draft_report["counts"]
        out += ["", "## 4. Draft validation", "",
                "- checks: %s / high: %s / warn: %s / annotations: %s / targets covered: %s of %s"
                % (counts.get("checks"), counts.get("high"), counts.get("warn"),
                   counts.get("annotations"), counts.get("targets_covered"), counts.get("targets"))]
        out += ["- **%s/%s** %s (%s)" % (f["check"], f["severity"], f["message"],
                                         "; ".join(f["locators"]) or "-")
                for f in draft_report.get("findings", []) if f["severity"] in ("high", "warn")]
    out += ["", "## 5. What these checks cannot do", "",
            "- They do not judge whether an annotation is entailed by its quote; verbatim presence, "
            "scope and lexical overlap are all they test.",
            "- They do not judge whether the source itself is right. Contradictions are reported "
            "unchanged, because the workorder forbids silent correction.",
            "- They cannot assess bibliography completeness when the materials carry no reference "
            "list; the gap is reported instead of being filled.", ""]
    return "\n".join(out)


ID_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]{0,9}-[A-Z]{0,2}\d{1,5})\b")
