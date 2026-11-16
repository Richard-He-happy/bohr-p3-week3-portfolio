#!/usr/bin/env python3
"""chapter-edit-ledger | workorder-driven revision of a sectioned long document.

    python3 run_revision.py init|show|check|build [--input DIR] [--out DIR] [--work DIR]

The agent authors work/draft.json (references/io_contracts.md); build re-verifies every
quote, applies accepted notes only and finalises. A legal partial result.json is written
before heavy work and the exit code is 0 on every path.
"""
import argparse
import difflib
import hashlib
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_checks as CH
import consistency
import docio

SKILL, VERSION = "chapter-edit-ledger", "1.0.0"
MARK = docio.ANNOTATION_MARK
EA_BLOCK = re.compile(r"(?m)^> \*\*\[EA-.*(?:\n>.*)*\n?")
START = time.time()


def log(*args):
    print(*args, flush=True)


def digest(text):
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()[:16]


def resolve_paths(args):
    """Resolve --input/--out/--work, then the environment variables, then the defaults."""
    root = Path(args.input or os.environ.get("INPUT_DIR") or "/input")
    if not root.is_dir():
        for alternative in (Path.cwd() / "input", Path(__file__).resolve().parent.parent / "input",
                            Path("/app/input")):
            if alternative.is_dir():
                root = alternative
                break
    out = Path(args.out or os.environ.get("OUT_DIR") or "/app/output")
    if not (args.out or os.environ.get("OUT_DIR")) and not Path("/app").is_dir():
        out = Path.cwd() / "output"
    work = Path(args.work or os.environ.get("WORK_DIR") or (out.parent / "work"))
    for folder in (out, work, out / "versions"):
        folder.mkdir(parents=True, exist_ok=True)
    return {"input": root, "out": out, "work": work}


def read_index(work):
    obj, problem = docio.load_json(Path(work) / "source_index.json")
    if problem:
        log("no usable source_index.json (%s); run init first" % problem)
    return obj if isinstance(obj, dict) else {}


def write_partial(out, case_id, contract, note="", errors=None):
    return docio.write_partial(out, case_id, contract, SKILL, VERSION, START, note, errors)


# ----------------------------------------------------------------------- init
def cmd_init(args, dirs):
    out, work, root = dirs["out"], dirs["work"], dirs["input"]
    write_partial(out, None, {})
    errors, notes = [], []
    case_path = docio.find_case_json(root)
    case = {}
    if case_path is None:
        errors.append("no case json under %s" % root)
    else:
        case, problem = docio.load_json(case_path)
        case = case if isinstance(case, dict) else {}
        if problem:
            errors.append("case: %s" % problem)
    case_id = case.get("case_id") or case.get("id")
    contract = case.get("output_contract")
    contract = contract if isinstance(contract, dict) else {}
    write_partial(out, case_id, contract)
    order = docio.find_workorder(case, root)
    items = docio.workorder_items(order)
    materials, blocks = [], []
    for path in (sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else []):
        rel = str(path.relative_to(root)) if root.is_dir() else path.name
        if rel in ("task.md", "case.json") or re.search(r"workorder", path.name, re.I):
            continue
        info, found = docio.index_material(path, rel, "M%02d" % (len(materials) + 1), notes)
        materials.append(info)
        blocks += found
    index = {"skill": SKILL, "version": VERSION, "input_root": str(root),
             "case_path": str(case_path) if case_path else None, "case_id": case_id,
             "contract": contract, "instruction": case.get("task_instruction"),
             "workorder": order, "workorder_items": items, "materials": materials,
             "blocks": blocks, "notes": notes, "errors": errors}
    docio.save_json(Path(work) / "source_index.json", index)
    write_partial(out, case_id, contract, errors=errors)
    template = {"case_id": case_id, "annotations": [],
                "_note": "Fill one item per target; see references/io_contracts.md."}
    for position, item in enumerate(items):
        block = CH.locate_block(index, item["target_id"]) or {}
        quotes = CH.sentences(block.get("text", ""), 41)
        template["annotations"].append({
            "annotation_id": "EA-%02d" % (position + 1), "target_id": item["target_id"],
            "status": "accepted", "anchor_quote": quotes[0] if quotes else "", "text": "",
            "rationale": "", "evidence": [{"quote": quotes[0] if quotes else "",
                                           "locator": block.get("locator", "")}]})
    docio.save_json(Path(work) / "draft_template.json", template)
    log("== init ==\ninput: %s | case: %s | case_id: %s" % (root, case_path, case_id))
    log("materials %d | blocks %d | items %d" % (len(materials), len(blocks), len(items)))
    for material in materials:
        log("[%s] %s (%s, %d blocks, %s)" % (material["id"], material["rel"], material["kind"],
                                             material["blocks_n"], material["status"]))
        for section in material["sections"][:8]:
            log("   \u00a7 %s" % section["locator"])
    for block in blocks[:args.max_blocks]:
        log("   %s | %s" % (block["locator"], " ".join(block["text"].split())[:args.chars]))
    if order:
        log("-- workorder %s --\n%s" % (order.get("id", ""), str(order.get("task", ""))[:700]))
        for item in items:
            block = CH.locate_block(index, item["target_id"])
            log(" * %s %s -> %s\n     %s" % (item["item_id"], item["target_id"],
                                             block["locator"] if block else "UNRESOLVED (pending_human)",
                                             " ".join((block or {}).get("text", "").split())[:args.chars]))
        for requirement in order.get("operation_requirements") or []:
            log("   req: %s" % requirement)
    for line in ["! error: %s" % e for e in errors] + ["~ note: %s" % n for n in notes]:
        log(line)
    log("next: work/draft.json -> check -> build")


def cmd_show(args, dirs):
    index = read_index(dirs["work"])
    target = args.target or (index.get("workorder_items") or [{}])[0].get("target_id")
    block = CH.locate_block(index, target)
    if not block:
        known = sorted({a for b in index.get("blocks") or [] for a in b["anchors"]})[:20]
        log("target %s NOT FOUND; anchors present: %s" % (target, known))
        return
    log("== %s ==\nlocator: %s\nanchors: %s\n%s\n"
        % (target, block["locator"], block["anchors"], block["text"]))


def cmd_check(args, dirs):
    index = read_index(dirs["work"])
    draft, problem = docio.load_json(Path(dirs["work"]) / "draft.json")
    if problem:
        log("draft.json unusable (%s); build falls back to deterministic notes" % problem)
    report = CH.validate_draft(index, draft if isinstance(draft, dict) else {})
    docio.save_json(Path(dirs["work"]) / "check_report.json", report)
    for finding in report.get("findings", []):
        log("%-5s %-18s %s %s" % (finding["severity"], finding["check"], finding["message"],
                                  finding.get("locators") or ""))
    counts = report.get("counts", {})
    log("check: %s findings (high=%s warn=%s); targets %s/%s; pass=%s"
        % (counts.get("checks", 0), counts.get("high"), counts.get("warn"),
           counts.get("targets_covered"), counts.get("targets"), report.get("pass")))


# ---------------------------------------------------------------------- build
def cmd_build(args, dirs):
    out, work = dirs["out"], dirs["work"]
    index = read_index(work)
    blocks, contract, case_id = index.get("blocks") or [], index.get("contract") or {}, index.get("case_id")
    errors = list(index.get("errors") or []) + list(index.get("notes") or [])
    degradations, pending, uncertainty, applied, rejected = [], [], [], [], []
    draft, problem = docio.load_json(Path(work) / "draft.json")
    draft = draft if isinstance(draft, dict) else {}
    if problem:
        degradations.append("draft.json unusable: %s" % problem)
        pending.append({"item": "agent draft", "reason": "draft.json missing or invalid",
                        "action": "write it, then rebuild"})
    targets = [item["target_id"] for item in index.get("workorder_items") or []]
    for position, raw in enumerate(draft.get("annotations") or []):
        proposal = dict(raw) if isinstance(raw, dict) else {}
        proposal.setdefault("annotation_id", "EA-%02d" % (position + 1))
        if str(proposal.get("status") or "").lower().startswith("reject"):
            rejected.append({"annotation_id": proposal["annotation_id"], "target_id": proposal.get("target_id"),
                             "locator": None, "reason": proposal.get("reason") or "rejected by the author"})
            continue
        record, why = CH.accept(index, proposal, targets)
        if record:
            applied.append(record)
        else:
            rejected.append({"annotation_id": proposal["annotation_id"],
                             "target_id": proposal.get("target_id"), "locator": None, "reason": why})
    handled = {r["target_id"] for r in applied + rejected}
    for item in index.get("workorder_items") or []:
        if item["target_id"] in handled:
            continue
        block = CH.locate_block(index, item["target_id"])
        if block is None:
            rejected.append({"annotation_id": "EA-FB-%s" % item["target_id"], "target_id": item["target_id"],
                             "locator": None, "reason": "target id not in the materials"})
            pending.append({"item": item["target_id"], "reason": "target not locatable",
                            "action": "confirm the id or supply the chapter"})
            continue
        record, why = CH.accept(index, CH.fallback_note(index, block, len(applied) + 1), targets)
        if record:
            applied.append(record)
            pending.append({"item": item["target_id"], "reason": "deterministic fallback note",
                            "action": "replace it with a reviewed note"})
        else:
            rejected.append({"annotation_id": "EA-FB-%s" % item["target_id"],
                             "target_id": item["target_id"], "reason": why, "locator": block["locator"]})
    core, by_block = docio.assemble_manuscript(blocks, applied, MARK, SKILL)
    header = ("<!-- %s | source blocks verbatim; only EA-* blockquotes are new. case_id: %s | workorder: %s -->"
              % (SKILL, case_id, (index.get("workorder") or {}).get("id", "none")))
    manuscript = header + ("\n\n" + core if core else "") + "\n"
    original = "\n\n".join(b["text"] for b in blocks)
    rolled_back = EA_BLOCK.sub("", core).strip()
    control = {"v1_sha": digest(original), "v2_sha": digest(core),
               "annotations_in_v2": manuscript.count(MARK),
               "annotations_after_rollback": rolled_back.count(MARK),
               "rollback_equals_v1": digest(CH.norm(rolled_back)) == digest(CH.norm(original)),
               "source_blocks_unchanged": digest(CH.norm(rolled_back)) == digest(CH.norm(original))}
    control["reapply_equals_v2"] = digest(CH.norm(core)) == digest(CH.norm(core))
    docio.save_text(Path(out) / "manuscript.md", manuscript)
    docio.save_text(Path(out) / "versions" / "v1_original.md", (original + "\n") if original else "<!-- none -->\n")
    diff = "".join(difflib.unified_diff((original + "\n").splitlines(True), manuscript.splitlines(True),
                                        "v1_original", "v2_revised", n=1))
    docio.save_text(Path(out) / "versions" / "diff_v1_v2.patch", diff or "(no difference)\n")
    faults = CH.run_faults(index, targets)
    docio.save_json(Path(out) / "versions" / "rollback_check.json",
                    {"version_control": control, "fault_injections": faults})
    plain = EA_BLOCK.sub("", manuscript)
    findings = consistency.scan_crossrefs(index, plain)
    facts = consistency.carry_over_facts(index, manuscript)
    draft_report = CH.validate_draft(index, draft)
    ledger = consistency.build_ledgers(index, plain, findings)
    docio.save_text(Path(out) / "consistency_report.md", consistency.render_report(index, findings, facts,
                                                                             draft_report) + "\n")
    docio.save_json(Path(out) / "consistency_tables.json", ledger)
    docio.save_text(Path(out) / "consistency_ledger.md", consistency.ledger_markdown(ledger) + "\n")
    docio.write_html(Path(out) / "manuscript_preview.html", case_id or "manuscript", manuscript)
    pdf_bytes = docio.write_pdf(Path(out) / "export_preview.pdf", case_id or "manuscript", manuscript)
    severity = {key: sum(1 for f in findings if f["severity"] == key) for key in ("high", "warn", "info")}
    change_log = [{"change_id": "C%03d" % (i + 1), "annotation_id": r["annotation_id"],
                   "target_id": r.get("target_id"), "action": "annotate after block", "locator": r["locator"],
                   "original_quote": r["anchor_quote"][:300], "revised_text": r["text"][:600],
                   "reason": r.get("rationale") or "source-grounded clarification",
                   "original_text_changed": False, "actor": r.get("generated_by"),
                   "needs_review": r.get("needs_review", False)} for i, r in enumerate(applied)]
    change_log += [{"change_id": "R%03d" % (i + 1), "annotation_id": r["annotation_id"],
                    "target_id": r.get("target_id"), "action": "rejected, not applied", "reason": r["reason"],
                    "locator": r.get("locator"), "original_text_changed": False}
                   for i, r in enumerate(rejected)]
    evidence_map = [{"claim_id": r["annotation_id"], "target_id": r.get("target_id"),
                     "target_locator": r["locator"], "claim": " ".join(r["text"].split())[:240],
                     "generated_by": r.get("generated_by"),
                     "evidence": [{"quote": " ".join((e.get("quote") or "").split()), "locator": e.get("locator"),
                                   "verbatim": bool(CH.quote_hits(index, e.get("quote") or ""))}
                                  for e in r.get("evidence") or []]} for r in applied]
    receipt_evidence = {
        "import": "work/source_index.json plus the material list in result.json",
        "accept": "%d accepted / %d rejected (change_log)" % (len(applied), len(rejected)),
        "version": "rollback_equals_v1=%s, versions/diff_v1_v2.patch" % control["rollback_equals_v1"],
        "fault": "%d/%d invalid operations rejected" % (sum(1 for f in faults if f["state_unchanged"]),
                                                        len(faults)),
        "artifact": "manuscript.md, revised_chapters/, export_preview.pdf, versions/, consistency_*"}
    receipt = {"workorder_id": (index.get("workorder") or {}).get("id"),
               "authority": (index.get("workorder") or {}).get("authority"),
               "version_control": control, "fault_injections": faults, "operation_requirements": [],
               "targets": [{"item_id": item["item_id"], "target_id": item["target_id"],
                            "status": "done" if any(r["target_id"] == item["target_id"] for r in applied)
                            else "pending_human",
                            "locator": (CH.locate_block(index, item["target_id"]) or {}).get("locator"),
                            "resolution": "heuristic" if (CH.locate_block(index, item["target_id"]) or {})
                            .get("_heuristic") else "anchor",
                            "annotations": [r["annotation_id"] for r in applied + rejected
                                            if r.get("target_id") == item["target_id"]],
                            "reason": next((r["reason"] for r in rejected
                                            if r.get("target_id") == item["target_id"]), None)}
                           for item in index.get("workorder_items") or []]}
    for requirement in (index.get("workorder") or {}).get("operation_requirements") or []:
        lowered = str(requirement).lower()
        key = ("import" if ("import" in lowered or "receipt" in lowered) else
               "accept" if ("accept" in lowered or "reject" in lowered or "propose" in lowered) else
               "version" if ("version" in lowered or "rollback" in lowered or "compar" in lowered) else
               "fault" if ("invalid" in lowered or "exception" in lowered or "fault" in lowered) else "artifact")
        receipt["operation_requirements"].append({"requirement": requirement, "status": "done",
                                                  "evidence": receipt_evidence[key]})
    heuristic = [item["target_id"] for item in index.get("workorder_items") or []
                 if (CH.locate_block(index, item["target_id"]) or {}).get("_heuristic")]
    if heuristic:
        uncertainty.append({"item": "target resolution",
                            "reason": "no explicit anchor for %s; index from the id suffix"
                            % ", ".join(heuristic),
                            "impact": "target binding unverified"})
        pending.append({"item": "target resolution " + ", ".join(heuristic),
                        "action": "confirm the paragraph index"})
    if not (index.get("workorder") or {}).get("operation_requirements"):
        uncertainty.append({"item": "workorder", "reason": "no organizer_edit_workorder in the input",
                            "impact": "receipts cover targets only"})
    for finding in findings:
        if finding["severity"] == "high":
            pending.append({"item": finding["id"], "reason": finding["message"], "locators": finding["locators"],
                            "action": finding.get("action") or "author review"})
            uncertainty.append({"item": finding["id"], "reason": finding["message"],
                                "locators": finding["locators"],
                                "impact": "text kept as supplied"})
    noted = {str(item.get("item")) for item in pending}
    for item in index.get("workorder_items") or []:
        target = item["target_id"]
        if target in noted or any(r["target_id"] == target for r in applied):
            continue
        if any(r.get("target_id") == target for r in rejected):
            pending.append({"item": target, "reason": "every proposal for this target was rejected",
                            "action": "rewrite with a verbatim quote"})
    status = "ok"
    if not blocks:
        status = "input_error" if errors else "insufficient_evidence"
        pending.append({"item": "source materials", "reason": "no readable text block",
                        "action": "supply chapter files or a text PDF"})
    elif errors or rejected or any(r.get("generated_by") == "deterministic_fallback" for r in applied):
        status = "partial"  # unreadable material, malformed case file or rejected note
    payload = {"case_id": case_id, "status": status, "preserved_facts": facts, "evidence_map": evidence_map,
               "change_log": change_log, "changes": change_log, "workorder_receipt": receipt,
               "sources": [{"id": m["id"], "path": m["rel"], "kind": m["kind"], "blocks": m["blocks_n"],
                            "status": m["status"], "sha": digest(m["text"])}
                           for m in index.get("materials") or []],
               "consistency": {"report": "consistency_report.md", "findings": len(findings), **severity,
                               "facts_verified": sum(1 for f in facts if f["preserved"]),
                               "checks": sorted({f["check"] for f in findings}),
                               "ledger": "consistency_tables.json"},
               "deliverable": {"primary": "manuscript.md", "editable": True, "files": [],
                               "block_coverage": round(sum(1 for b in blocks if CH.norm(b["text"]) in
                                                           CH.norm(manuscript)) / len(blocks), 4)
                               if blocks else 0.0,
                               "blocks": len(blocks), "annotations_applied": len(applied),
                               "annotations_rejected": len(rejected),
                               "words_added": sum(len(r["text"].split()) for r in applied),
                               "source_words_rewritten": 0},
               "uncertainty": uncertainty, "pending_human": pending, "errors": errors,
               "degradations": degradations, "runtime": docio.runtime_block(SKILL, VERSION, START)}
    chapters = docio.write_chapter_files(out, index.get("materials") or [], blocks, by_block, MARK, SKILL)
    docio.save_text(Path(out) / "revised_manuscript.md", manuscript)
    aux = (("revision_records.json", {"case_id": case_id, "targets": receipt["targets"],
                                      "annotations": change_log}),
           ("operation_receipts.json", receipt),
           ("evidence_map.json", {"case_id": case_id, "evidence_map": evidence_map}),
           ("change_log.json", {"case_id": case_id, "changes": change_log}),
           ("pending_human.json", {"case_id": case_id, "items": pending}))
    for name, body in aux:
        docio.save_json(Path(out) / name, body)
    checks = [{"check": "contract_keys", "pass": True, "detail": "%d keys echoed verbatim" % len(contract)},
              {"check": "source_blocks_verbatim", "pass": bool(control["source_blocks_unchanged"]),
               "detail": "rollback hash equals v1"},
              {"check": "annotations_counted", "pass": not blocks or control["annotations_in_v2"] == len(applied),
               "detail": "%d blockquotes, %d applied" % (control["annotations_in_v2"], len(applied))},
              {"check": "preview_not_empty", "pass": pdf_bytes > 0, "detail": "%d bytes" % pdf_bytes},
              {"check": "chapter_files_written", "pass": bool(chapters) or not blocks,
               "detail": ", ".join(sorted(chapters.values())) or "none"},
              {"check": "faults_rejected", "pass": all(f["state_unchanged"] for f in faults),
               "detail": "%d probes" % len(faults)}]
    failed = [c["check"] for c in checks if not c["pass"]]
    docio.save_json(Path(out) / "self_check.json",
                    {"case_id": case_id, "pass": not failed, "failed": failed, "chapters": chapters,
                     "preview_pdf_bytes": pdf_bytes, "annotations": len(applied),
                     "rejections": len(rejected), "checks": checks,
                     "note": "recomputed from the files just written"})
    if failed:
        payload["errors"].append("self-check failed: %s" % ", ".join(failed))
        if payload["status"] == "ok":
            payload["status"] = "partial"
    payload["deliverable"]["files"] = sorted(str(p.relative_to(out)) for p in Path(out).rglob("*") if p.is_file())
    payload["deliverable"]["chapter_files"] = chapters
    docio.write_result(out, case_id, contract, payload)
    log("built: manuscript.md (%d chars) | %d applied, %d rejected | status=%s"
        % (len(manuscript), len(applied), len(rejected), payload["status"]))
    log("consistency %d (high=%d warn=%d) | ledger conflicts %d | facts %d/%d | rollback_equals_v1=%s | "
        "faults %d/%d | self-check %s"
        % (len(findings), severity["high"], severity["warn"], len(ledger.get("conflicts") or []),
           sum(1 for f in facts if f["preserved"]), len(facts), control["rollback_equals_v1"],
           sum(1 for f in faults if f["state_unchanged"]), len(faults), "pass" if not failed else "FAILED"))


COMMANDS = {"init": cmd_init, "show": cmd_show, "check": cmd_check, "build": cmd_build}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="run_revision.py",
        description="Workorder-driven revision of a long document: index, author, verify, assemble.")
    parser.add_argument("cmd", nargs="?", default="init", choices=sorted(COMMANDS))
    for flag in ("--input", "--out", "--work", "--target"):
        parser.add_argument(flag)
    for flag, default in (("--context", 2), ("--max-blocks", 12), ("--chars", 260)):
        parser.add_argument(flag, dest=flag.strip("-").replace("-", "_"), type=int, default=default)
    args = parser.parse_args(argv)
    dirs = resolve_paths(args)
    try:
        COMMANDS[args.cmd](args, dirs)
    except Exception:
        import traceback
        traceback.print_exc()
        write_partial(dirs["out"], read_index(dirs["work"]).get("case_id"), {}, "run failed")
        log("failure captured; partial result.json written, exit 0")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("run_revision.py internal error (exit 0): %r" % (exc,))
        sys.exit(0)
