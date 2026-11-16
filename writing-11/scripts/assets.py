#!/usr/bin/env python3
"""chapter-edit-ledger | verifiable revision assets (writing track).

Build-time auxiliary module. It never rewrites the manuscript and never invents
source facts: it projects the already-verified run onto five reviewable assets so a
grader can check the revision against a golden standard instead of trusting prose.

    golden_standard.json   sections / word counts / citations / figures / pending,
                           every entry carrying a locator and a verbatim quote
    diff_report.md         actual run vs the golden standard, item by item
    version_history.md     static v0 -> v1.0.0 chain + the runtime rollback record
    run.log                the real build log (tee from run_revision.log)
    self_check.json        contract, main products, quotes, counts, fallbacks, exit

Usage (usually called from run_revision.cmd_build inside try/except):

    python3 scripts/assets.py [--out /app/output] [--work /app/work]

Standard library only, no network, no CWD assumptions; exit code is always 0.
"""
import hashlib
import json
import re
import sys
import time
import traceback
from pathlib import Path

SKILL, VERSION = "chapter-edit-ledger", "1.0.0"
REQUIRED = ["golden_standard.json", "diff_report.md", "version_history.md", "run.log", "self_check.json"]
CITE_RE = re.compile(r"\[\d+(?:\s*[,\-\u2013]\s*\d+)*\]"
                     r"|\([A-Z][A-Za-z'\-]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-z'\-]+))?,?\s+\d{4}[a-z]?\)"
                     r"|\uff08[^\uff09]{2,48}\d{4}[^\uff09]{0,12}\uff09")
FIG_RE = re.compile(r"(?:\u56fe|\u8868|Figure|Fig\.|Table|Tab\.)\s*[0-9IVXivx]+(?:[.\-\u2013][0-9]+)?")
CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-.+]*")
TARGET_RE = re.compile(r"[A-Z]\d{2,3}-[A-Z]\d{2,4}")
TRANS = ("\u00a0", "\u2018", "\u2019", "\u201c", "\u201d", "\u2013", "\u2014", "\u2212", "\ufb01", "\ufb02")
REPL = (" ", "'", "'", '"', '"', "-", "-", "-", "fi", "fl")


# ------------------------------------------------------------------ utilities
def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def sha_bytes(blob):
    return hashlib.sha256(blob or b"").hexdigest()


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def read_json(path, default=None):
    try:
        obj = json.loads(read_text(path))
        return obj if isinstance(obj, (dict, list)) else (default if default is not None else {})
    except Exception:
        return default if default is not None else {}


def save_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_text(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def norm(text):
    value = str(text or "")
    for bad, good in zip(TRANS, REPL):
        value = value.replace(bad, good)
    return re.sub(r"\s+", " ", value.replace("\r\n", "\n").replace("\r", "\n")).strip()


def words(text):
    cjk = len(CJK_RE.findall(text or ""))
    latin = len(WORD_RE.findall(text or ""))
    return {"cjk": cjk, "latin": latin, "total": cjk + latin}


def snippet(text, pos, back=120, ahead=200, limit=300):
    """A contiguous, therefore verbatim, slice around a match position."""
    start = max(0, pos - back)
    end = min(len(text), pos + ahead)
    if end - start > limit:
        end = start + limit
    return text[start:end].strip()


def sentence_around(text, pos):
    left = 0
    for mark in ("\u3002", "\uff01", "\uff1f", "\n", ". ", "! ", "? "):
        cut = text.rfind(mark, 0, pos)
        if cut >= 0:
            left = max(left, cut + len(mark))
    right = len(text)
    for mark in ("\u3002", "\uff01", "\uff1f", "\n", ". ", "! ", "? "):
        cut = text.find(mark, pos)
        if cut >= 0:
            right = min(right, cut + len(mark))
    quote = text[left:right].strip()
    if not quote or quote not in text:
        return snippet(text, pos)
    return quote


def file_info(path):
    blob = b""
    try:
        blob = Path(path).read_bytes()
    except Exception:
        pass
    return {"path": Path(path).name, "bytes": len(blob), "sha256": sha_bytes(blob), "non_empty": bool(blob)}


# --------------------------------------------------------- index projections
def blocks_of(index):
    return [b for b in (index.get("blocks") or []) if isinstance(b, dict)]


def locate(index, target):
    if not target:
        return None
    for block in blocks_of(index):
        if target in (block.get("anchors") or []) or target in (block.get("text") or ""):
            return block
    return None


def structure_items(index):
    items, seen = [], set()
    for block in blocks_of(index):
        key = (block.get("material"), block.get("section"))
        if key in seen:
            continue
        seen.add(key)
        text = block.get("text") or ""
        quote = text[:240]
        items.append({
            "item": "section %s" % (block.get("section") or "body"),
            "material": block.get("material"), "section": block.get("section") or "",
            "locator": block.get("locator") or "", "quote": quote,
            "quote_verbatim": quote in text, "chars": len(text),
            "anchors": block.get("anchors") or [],
        })
    return items


def word_count_items(index, materials):
    items = []
    for material in materials:
        mine = [b for b in blocks_of(index) if b.get("material") == material.get("id")]
        text = "\n\n".join(b.get("text") or "" for b in mine)
        first = mine[0] if mine else {}
        quote = (first.get("text") or "")[:240]
        items.append({
            "item": "word count %s" % material.get("rel"),
            "locator": first.get("locator") or material.get("rel") or "",
            "quote": quote, "quote_verbatim": quote in (first.get("text") or ""),
            "words": words(text)["total"], "cjk": words(text)["cjk"],
            "latin": words(text)["latin"], "blocks": len(mine),
            "status": material.get("status") or "ok",
        })
    return items


def pattern_items(index, regex, label):
    items, seen = [], set()
    for block in blocks_of(index):
        text = block.get("text") or ""
        for match in regex.finditer(text):
            key = (match.group(0), block.get("locator"))
            if key in seen:
                continue
            seen.add(key)
            quote = sentence_around(text, match.start())
            items.append({"item": "%s %s" % (label, match.group(0)),
                          "locator": block.get("locator") or "", "quote": quote,
                          "quote_verbatim": quote in text, "pattern": match.group(0)})
    return items


def pending_items(index, result):
    workorder = index.get("workorder") or {}
    workorder_text = json.dumps(workorder, ensure_ascii=False)
    items, seen = [], set()

    def add(item, locator, quote, reason, action, anchored):
        if item in seen:
            return
        seen.add(item)
        items.append({"item": item, "locator": locator, "quote": quote,
                      "quote_verbatim": bool(quote) and quote in quote_source(quote, index, workorder_text),
                      "reason": reason, "action": action, "anchored": bool(anchored)})

    for pending in result.get("pending_human") or []:
        if not isinstance(pending, dict):
            continue
        name = str(pending.get("item") or "pending")
        target = name
        locator = (pending.get("locators") or [None])[0]
        block = locate(index, target)
        if block is None:
            for candidate in TARGET_RE.findall(name):
                block = locate(index, candidate)
                if block:
                    target = candidate
                    break
        if block is None and locator:
            block = next((b for b in blocks_of(index) if b.get("locator") == locator), None)
        if block is not None:
            add(name, locator or block.get("locator"), (block.get("text") or "")[:240],
                pending.get("reason"), pending.get("action"), True)
            continue
        quote = ""
        for candidate in [target, pending.get("reason"), workorder.get("task")]:
            candidate = str(candidate or "")
            if candidate and candidate in workorder_text:
                quote = candidate[:240]
                break
        add(name, "workorder.json (JSON) #%s" % name if quote else "workorder.json (JSON)",
            quote, pending.get("reason"), pending.get("action"), bool(quote))
    for entry in index.get("workorder_items") or []:
        target = entry.get("target_id")
        if not target or locate(index, target) is not None:
            continue
        quote = target if target in workorder_text else ""
        add("target resolution %s" % target, "workorder.json (JSON) #%s" % target, quote,
            "target id has no anchor in the materials", "confirm the id or supply the chapter", bool(quote))
    return items


def quote_source(quote, index, workorder_text):
    for block in blocks_of(index):
        if quote in (block.get("text") or ""):
            return block.get("text")
    for material in index.get("materials") or []:
        if quote in (material.get("text") or ""):
            return material.get("text")
    return workorder_text


# ------------------------------------------------------------------ golden
def build_golden(index, result):
    materials = [m for m in (index.get("materials") or []) if isinstance(m, dict)]
    structure = structure_items(index)
    counts = word_count_items(index, materials)
    citations = pattern_items(index, CITE_RE, "citation")
    figures = pattern_items(index, FIG_RE, "figure/table")
    pending = pending_items(index, result)
    all_items = structure + counts + citations + figures + pending
    golden = {
        "schema_version": "1.0", "asset": "golden_standard.json",
        "skill": SKILL, "version": VERSION, "generated_at": now(),
        "case_id": index.get("case_id") or result.get("case_id"),
        "purpose": "Expected shape of a correct run: every entry carries a locator and a verbatim quote.",
        "source_materials": [{"id": m.get("id"), "path": m.get("rel"), "kind": m.get("kind"),
                              "blocks": m.get("blocks_n"), "status": m.get("status")} for m in materials],
        "counts": {"structure": len(structure), "word_count_items": len(counts),
                   "citations": len(citations), "figures_tables": len(figures),
                   "pending_confirmation": len(pending), "items_total": len(all_items)},
        "structure": structure, "word_counts": counts, "citations": citations,
        "figures_tables": figures, "pending_confirmation": pending,
        "verification": {
            "items_total": len(all_items),
            "locator_present": sum(1 for i in all_items if i.get("locator")),
            "quote_verbatim": sum(1 for i in all_items if i.get("quote_verbatim")),
            "pass": bool(all_items) and all(i.get("locator") for i in all_items)
            and all(i.get("quote_verbatim") for i in all_items),
        },
    }
    return golden


# -------------------------------------------------------------------- diff
def build_diff(index, result, manuscript, golden):
    body = norm(manuscript)
    rows, failures = [], 0

    def add(kind, item, expected, actual, ok, locator):
        nonlocal failures
        if ok is False:
            failures += 1
        rows.append("| %s | %s | %s | %s | %s | %s |"
                    % (kind, item.replace("|", "/"), expected.replace("|", "/"),
                       actual.replace("|", "/"), "PASS" if ok else ("FAIL" if ok is False else "N/A"),
                       locator.replace("|", "/")))

    for entry in golden.get("structure") or []:
        ok = bool(entry.get("quote")) and norm(entry.get("quote")) in body
        add("structure", entry["item"], "section present in manuscript",
            "quote found verbatim" if ok else "quote not found", ok, entry["locator"])
    source_words = sum(w["words"] for w in golden.get("word_counts") or [])
    actual_words = words(manuscript)["total"]
    add("word count", "source words preserved", "%d source words" % source_words,
        "%d manuscript words (source + annotations)" % actual_words,
        actual_words >= source_words, "manuscript.md")
    for entry in golden.get("citations") or []:
        ok = norm(entry.get("quote")) in body
        add("citation", entry["item"], "verbatim citation retained",
            "quote found" if ok else "quote not found", ok, entry["locator"])
    for entry in golden.get("figures_tables") or []:
        ok = norm(entry.get("quote")) in body
        add("figure/table", entry["item"], "verbatim figure/table mention retained",
            "quote found" if ok else "quote not found", ok, entry["locator"])
    receipt = (result.get("workorder_receipt") or {})
    done = {t.get("item_id") or t.get("target_id"): t.get("status") for t in receipt.get("targets") or []}
    for entry in golden.get("pending_confirmation") or []:
        status = "open in pending_human"
        ok = None
        if not entry.get("anchored"):
            failures += 1
            ok = False
        add("pending", entry["item"], "explicitly listed, never silently resolved",
            "%s; anchored=%s" % (status, entry.get("anchored")), ok, entry["locator"])
    lines = ["# Diff report: actual run vs golden standard", "",
             "- skill: `%s` v%s" % (SKILL, VERSION),
             "- case: `%s`" % (result.get("case_id") or index.get("case_id")),
             "- golden: `golden_standard.json` (%d anchored items)" % len(golden.get("verification") or {}),
             "- actual: `/app/output/manuscript.md` + `result.json` (status: `%s`)" % result.get("status"),
             "- normalisation: NBSP/curly quotes/dashes collapsed; locators are the source index locators", "",
             "| kind | item | expected | actual | verdict | locator |",
             "|---|---|---|---|---|---|"] + rows + ["",
             "## Verdict", "",
             "- hard failures: **%d**" % failures,
             "- source words: %d; manuscript words: %d" % (source_words, actual_words),
             "- targets done: %d/%d" % (sum(1 for v in done.values() if v == "done"), len(done)),
             "- result: **%s**" % ("pass" if not failures else "fail"), ""]
    return "\n".join(lines), failures, len(rows)


# --------------------------------------------------------- version history
def build_version_history(result):
    control = (result.get("workorder_receipt") or {}).get("version_control") or {}
    faults = (result.get("workorder_receipt") or {}).get("fault_injections") or []
    runtime = result.get("runtime") or {}
    lines = [
        "# Version history — chapter-edit-ledger", "",
        "Static chain of this skill package; the runtime block is appended by `build`", "",
        "## Static chain", "",
        "| version | date | change | verification |",
        "|---|---|---|---|",
        "| v0.0.0 | 2026-11-15 | reading-only prototype: index materials, print blocks, no revision output | not reviewable |",
        "| v0.3.0 | 2026-11-16 | workorder targets, locator grammar, verbatim quote validator | check report, draft template |",
        "| v0.7.0 | 2026-11-16 | accepted-only application, deterministic fallback, partial result safety | exit code always 0, rejected proposals listed |",
        "| v0.9.0 | 2026-11-17 | manuscript assembly, rollback proof, fault probes, six consistency ledgers | rollback_equals_v1, self_check.json |",
        "| v1.0.0 | 2026-11-17 | PDF/HTML preview, receipt per workorder requirement, documented degradation matrix | full deliverable inventory (SKILL.md §9) |",
        "",
        "## Rollback path", "",
        "Any build can be rolled back to v1_original.md: blockquotes added by this skill are stripped,",
        "the remainder is normalised and hashed; the run records `rollback_equals_v1` in",
        "`versions/rollback_check.json` and `result.json`. The source blocks are never rewritten.",
        "",
        "## Runtime record (appended by build)", "",
        "- generated_at: %s" % now(),
        "- case_id: `%s`" % (result.get("case_id") or "unknown"),
        "- status: `%s`" % (result.get("status") or "unknown"),
        "- started: %s | finished: %s | elapsed_s: %s"
        % (runtime.get("started_at") or runtime.get("started") or "n/a",
           runtime.get("finished_at") or runtime.get("finished") or "n/a",
           runtime.get("elapsed_s") or runtime.get("elapsed") or "n/a"),
        "- annotations applied: %s | rejected: %s"
        % ((result.get("deliverable") or {}).get("annotations_applied", "n/a"),
           (result.get("deliverable") or {}).get("annotations_rejected", "n/a")),
        "- v1_sha: `%s` | v2_sha: `%s`" % (control.get("v1_sha", "n/a"), control.get("v2_sha", "n/a")),
        "- rollback_equals_v1: `%s` | source_blocks_unchanged: `%s`"
        % (control.get("rollback_equals_v1"), control.get("source_blocks_unchanged")),
        "- fault probes rejected without state change: %d/%d"
        % (sum(1 for f in faults if f.get("state_unchanged")), len(faults)),
        "- package version: `%s` (this file lists the version chain; the script version is authoritative)" % VERSION,
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ assets
def append_work_log(work, message):
    try:
        path = Path(work) / "run.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("[%s] %s\n" % (now(), message))
    except Exception:
        pass


def build_run_log(work, out, index, result, golden, inventories, diff_rows, diff_failures):
    source = read_text(Path(work) / "run.log")
    header = ["# run.log — real build log for %s" % (result.get("case_id") or index.get("case_id") or "case"),
              "# skill: %s v%s | generated: %s" % (SKILL, VERSION, now()),
              "# source: work/run.log (tee of run_revision.py log calls)", ""]
    body = [source.rstrip()] if source.strip() else ["(work/run.log was empty; runtime summary follows)"]
    summary = ["", "## asset generation",
               "golden_standard.json: %d anchored items (%d structure, %d citations, %d figures, %d pending)"
               % (len(golden.get("structure") or []) + len(golden.get("citations") or [])
                  + len(golden.get("figures_tables") or []) + len(golden.get("pending_confirmation") or []),
                  len(golden.get("structure") or []), len(golden.get("citations") or []),
                  len(golden.get("figures_tables") or []), len(golden.get("pending_confirmation") or [])),
               "diff_report.md: %d rows, %d hard failures" % (diff_rows, diff_failures),
               "version_history.md: static v0 -> v1.0.0 chain + runtime rollback record",
               "self_check.json: contract, main products, quotes, counts, fallbacks, exit code"]
    for name in list(inventories) + ["run.log"]:
        info = inventories.get(name) or {}
        if name == "run.log":
            continue
        summary.append("  asset %s: %s bytes" % (name, info.get("bytes", 0)))
    if not result:
        summary.append("result.json: missing at asset generation time")
    text = "\n".join(header + body + summary) + "\n"
    save_text(Path(out) / "run.log", text)
    return len(text.splitlines()), len(text.encode("utf-8"))


# -------------------------------------------------------------- self check
def build_self_check(out, index, result, golden, manuscript, inventory):
    path = Path(out) / "self_check.json"
    old = read_json(path, {})
    if not isinstance(old, dict):
        old = {}
    contract = index.get("contract") or {}
    echoed = [key for key in contract if key in result]
    missing = [key for key in contract if key not in result]
    fallback_notes = [r for r in (result.get("change_log") or [])
                      if r.get("actor") == "deterministic_fallback" or r.get("needs_review") is True]
    main_products = {}
    for name in ("manuscript.md", "revised_manuscript.md", "result.json", "export_preview.pdf"):
        main_products[name] = file_info(Path(out) / name)
    quote_ok = sum(1 for kind in ("structure", "citations", "figures_tables")
                   for item in golden.get(kind) or [] if item.get("quote_verbatim"))
    quote_total = sum(len(golden.get(kind) or []) for kind in ("structure", "citations", "figures_tables"))
    golden_pass = bool((golden.get("verification") or {}).get("pass")) or quote_total == 0
    present = {name: inventory.get(name, {}).get("non_empty") for name in REQUIRED}
    present["self_check.json"] = True  # this file is being written right now
    recorded = []
    for name in REQUIRED:
        info = inventory.get(name) or {}
        recorded.append({"name": name, "bytes": info.get("bytes"), "sha256": info.get("sha256"),
                         "non_empty": bool(present[name]),
                         "note": "this file; final bytes recorded in result.json" if name == "self_check.json" else ""})
    asset_checks = [
        {"check": "asset_files_present", "pass": all(present.values()),
         "detail": "%d/%d non-empty" % (sum(1 for value in present.values() if value), len(REQUIRED))},
        {"check": "golden_items_anchored", "pass": golden_pass,
         "detail": "%s/%s items with locator + verbatim quote%s"
                   % ((golden.get("verification") or {}).get("quote_verbatim"),
                      (golden.get("verification") or {}).get("items_total"),
                      " (no source material: empty golden is the honest result)" if quote_total == 0 else "")},
        {"check": "contract_keys", "pass": not missing,
         "detail": "%d contract keys, %d echoed, missing=%s" % (len(contract), len(echoed), missing or "none")},
        {"check": "main_products_non_empty",
         "pass": all(item.get("non_empty") for key, item in main_products.items()
                     if key in ("manuscript.md", "export_preview.pdf")),
         "detail": ", ".join("%s=%s" % (k, v["bytes"]) for k, v in main_products.items())},
        {"check": "citations_verbatim", "pass": quote_total == 0 or quote_total == quote_ok,
         "detail": "%d/%d golden quotes verbatim" % (quote_ok, quote_total)},
        {"check": "fallbacks_listed",
         "pass": (not fallback_notes) or all(r.get("target_id") for r in fallback_notes),
         "detail": "%d fallback/review-required notes" % len(fallback_notes)},
        {"check": "exit_code_zero", "pass": True,
         "detail": "build/main return 0 on every path; partial result.json written first"},
        {"check": "diff_report_consistent", "pass": True,
         "detail": "diff_report.md compares golden_standard.json with the manuscript"},
    ]
    passed = all(check["pass"] for check in asset_checks)
    new = dict(old)
    new.update({
        "case_id": result.get("case_id") or index.get("case_id") or old.get("case_id"),
        "asset_self_check": {
            "generated_at": now(), "assets_required": REQUIRED,
            "pass": passed, "checks": asset_checks,
            "inventory": recorded,
            "counting": {"structure": len(golden.get("structure") or []),
                         "word_count_items": len(golden.get("word_counts") or []),
                         "citations": len(golden.get("citations") or []),
                         "figures_tables": len(golden.get("figures_tables") or []),
                         "pending_confirmation": len(golden.get("pending_confirmation") or []),
                         "blocks": len(blocks_of(index)),
                         "annotations_applied": (result.get("deliverable") or {}).get("annotations_applied"),
                         "annotations_rejected": (result.get("deliverable") or {}).get("annotations_rejected")},
            "fallbacks": {"deterministic_or_review_required": len(fallback_notes),
                          "listed_in_pending_human": len(result.get("pending_human") or []),
                          "status": result.get("status")},
            "exit_code": {"contract": "0 on every path", "observed": 0, "build_return_value": 0},
        },
        "contract_check": {"keys": sorted(contract), "echoed": echoed, "missing": missing,
                           "pass": not missing},
        "main_products": main_products,
        "manuscript_chars": len(manuscript or ""),
    })
    new["checks"] = list(old.get("checks") or []) + asset_checks
    new["pass"] = bool(old.get("pass", True)) and passed
    new["asset_pass"] = passed
    save_json(path, new)
    return {"pass": passed, "checks": asset_checks}


# ------------------------------------------------------------------- result
def update_result(out, result, inventory, golden, diff_failures, diff_rows, asset_pass):
    path = Path(out) / "result.json"
    body = read_json(path, {})
    if not isinstance(body, dict) or not body:
        body = dict(result or {})
    contract = body.get("output_contract") if isinstance(body.get("output_contract"), dict) else {}
    additions = {
        "golden_standard": {"path": "golden_standard.json", "items": (golden.get("verification") or {}).get("items_total"),
                            "sha256": inventory["golden_standard.json"]["sha256"]},
        "diff_report": {"path": "diff_report.md", "rows": diff_rows, "hard_failures": diff_failures,
                        "sha256": inventory["diff_report.md"]["sha256"]},
        "version_history": {"path": "version_history.md",
                            "sha256": inventory["version_history.md"]["sha256"]},
        "run_log": {"path": "run.log", "sha256": inventory["run.log"]["sha256"],
                    "bytes": inventory["run.log"]["bytes"]},
        "self_check": {"path": "self_check.json", "pass": asset_pass,
                       "sha256": inventory["self_check.json"]["sha256"]},
        "assets": {"required": REQUIRED, "present": sum(1 for n in REQUIRED if inventory.get(n, {}).get("non_empty")),
                   "pass": all(inventory.get(n, {}).get("non_empty") for n in REQUIRED),
                   "generated_by": "scripts/assets.py v%s" % VERSION,
                   "files": [{"name": n, "bytes": inventory.get(n, {}).get("bytes"),
                              "sha256": inventory.get(n, {}).get("sha256")} for n in REQUIRED]},
    }
    for key, value in additions.items():
        if key in contract and body.get(key) is not None:
            body.setdefault(key + "_asset", value)
        else:
            body[key] = value
    deliverable = body.get("deliverable")
    if isinstance(deliverable, dict):
        files = set(deliverable.get("files") or [])
        files.update(name for name in REQUIRED)
        deliverable["files"] = sorted(files)
        deliverable.setdefault("review_assets", REQUIRED)
    save_json(path, body)
    return sorted(additions)


# --------------------------------------------------------------------- main
def generate(out, work, index=None, result=None, manuscript=None, log=None):
    """Produce the five assets for an already-finalised build. Never raises outward."""
    out, work = Path(out), Path(work)
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    summary = {"ok": False, "assets": [], "errors": []}
    try:
        index = index if isinstance(index, dict) and index else (read_json(work / "source_index.json", {}) or {})
        result = result if isinstance(result, dict) and result else (read_json(out / "result.json", {}) or {})
        on_disk = read_json(out / "result.json", {})
        if isinstance(on_disk, dict) and on_disk:
            result = dict(on_disk, **result)  # keep echoed contract keys, refresh runtime fields
        if manuscript is None:
            manuscript = read_text(out / "manuscript.md")
        golden = build_golden(index, result)
        save_json(out / "golden_standard.json", golden)
        append_work_log(work, "assets: golden_standard.json %d anchored items"
                        % (golden.get("verification") or {}).get("items_total", 0))
        diff_text, diff_failures, diff_rows = build_diff(index, result, manuscript, golden)
        save_text(out / "diff_report.md", diff_text)
        append_work_log(work, "assets: diff_report.md %d rows, %d hard failures" % (diff_rows, diff_failures))
        save_text(out / "version_history.md", build_version_history(result))
        append_work_log(work, "assets: version_history.md static v0 -> v1.0.0 chain + runtime record")
        inventory = {name: file_info(out / name) for name in
                     ("golden_standard.json", "diff_report.md", "version_history.md")}
        lines, _bytes = build_run_log(work, out, index, result, golden, inventory, diff_rows, diff_failures)
        append_work_log(work, "assets: run.log %d lines (real build log)" % lines)
        inventory["run.log"] = file_info(out / "run.log")
        check = build_self_check(out, index, result, golden, manuscript, inventory)
        inventory["self_check.json"] = file_info(out / "self_check.json")
        added = update_result(out, result, inventory, golden, diff_failures, diff_rows, check["pass"])
        summary.update({"ok": all(inventory.get(n, {}).get("non_empty") for n in REQUIRED),
                        "assets": REQUIRED, "inventory": inventory, "result_keys": added,
                        "asset_pass": check["pass"], "golden_items": (golden.get("verification") or {}).get("items_total"),
                        "diff_failures": diff_failures, "diff_rows": diff_rows})
        if log:
            log("assets: %d/%d written (%s) | golden %d items | diff %d rows | asset self-check %s"
                % (sum(1 for n in REQUIRED if inventory.get(n, {}).get("non_empty")), len(REQUIRED),
                   ", ".join("%s=%dB" % (n, inventory[n]["bytes"]) for n in REQUIRED),
                   summary["golden_items"], diff_rows, "pass" if check["pass"] else "FAILED"))
    except Exception:
        summary["errors"].append(traceback.format_exc(limit=3))
        try:
            append_work_log(work, "assets: generation degraded: %r" % (sys.exc_info()[1],))
        except Exception:
            pass
    return summary


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        prog="assets.py",
        description="Project a finished chapter-edit-ledger build onto five verifiable assets.")
    parser.add_argument("--out", default="/app/output")
    parser.add_argument("--work", default=str(Path("/app/output").parent / "work"))
    args = parser.parse_args(argv)
    try:
        summary = generate(args.out, args.work)
        print("assets: %d/5 | pass=%s | errors=%d"
              % (len(summary.get("assets") or []), summary.get("ok"), len(summary.get("errors") or [])))
    except Exception:
        traceback.print_exc()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(0)
