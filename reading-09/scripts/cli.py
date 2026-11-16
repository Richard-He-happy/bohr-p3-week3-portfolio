#!/usr/bin/env python3
"""cli.py - command line front end of the repro-audit kit.

Sub-commands
  init    index /input, pre-declare the tolerance band, emit a partial result.json
  show    print indexed material text together with its locators
  check   validate the agent draft (quotes, sections, tolerance widening)
  build   execute the candidates, compare against reported values, attribute the
          gaps, then write result.json + reproduction.json + reproduction.md
  doctor  re-read an already written result.json and report contract/structure health

Path flags --input/--output/--work become SCIM_INPUT/SCIM_OUTPUT/SCIM_WORK
overrides before argparse sees the remaining argv; defaults are /input,
/app/output and /app/work. Every failure path still writes a legal partial
result.json and the process always exits 0.
"""
import argparse
import json
import sys
import traceback

import audit_lib as A
import pipeline as P

PARAM_CLASSES = ("paper", "code_inferred", "chosen")
log = P.log

# ------------------------------------------------------------------- init/show
def do_init(args):
    inp, out, work = P.paths()
    case, case_path, case_err = P.load_case(inp)
    case_id = case.get("case_id") or case.get("id")
    early = P.shell_result(case, case_id)
    early["summary"] = "init placeholder"
    P.publish(out, early)

    index = P.build_index(inp)
    plan = P.build_tolerance_plan(case, P.reported_values(case))
    A.write_json(work / "index.json", index)
    A.write_json(work / "tolerance_plan.json", plan)
    A.write_json(work / "draft_skeleton.json", dict(P.DRAFT_TEMPLATE, case_id=case_id))

    materials = [{k: m.get(k) for k in ("id", "rel", "kind", "bytes", "quality", "sha1")}
                 for m in index["materials"]]
    res = P.shell_result(case, case_id)
    res.update(summary="init: %d materials, %d units"
               % (len(index["materials"]),
                  sum(len(m["units"]) for m in index["materials"])),
               sources=materials,
               pending_human=["run build for the reproduction record"],
               degradations=["partial_written_at_init"])
    if case_err:
        res.update(status="input_error", errors=[case_err])
    P.publish(out, res)

    log("== init ==\ninput=%s work=%s output=%s\ncase=%s parse=%s case_id=%s"
        % (inp, work, out, case_path, "ok" if not case_err else case_err, case_id))
    log("\n[materials] %d" % len(index["materials"]))
    units = []
    for mat in index["materials"]:
        log("  %-16s %-6s %8dB units=%-4d %s"
            % (mat["id"], mat["kind"], mat["bytes"], len(mat["units"]), mat["quality"]))
        units += mat["units"]
    log("\n[units]")
    for loc, text in units[:args.preview]:
        log("  %s | %s" % (loc, A.clip(text, 110)))
    log("\n[workorder]")
    for field in ("task_instruction", "instruction", "task", "organizer_workorder",
                  "requirements", "scope"):
        value = case.get(field)
        if value:
            shown = (json.dumps(value, ensure_ascii=False)
                     if isinstance(value, (dict, list)) else str(value))
            log("  %s: %s" % (field, A.clip(shown, 360)))
    log("\n[tolerance] %d entries, before_any_run=%s, source=%s"
        % (len(plan["entries"]), plan["before_any_run"], plan["source"]))
    for name, entry in list(plan["entries"].items())[:8]:
        log("  %-18s abs=%s rel=%s [%s]"
            % (name, entry.get("abs_tol"), entry.get("rel_tol"), entry["basis"]))
    log("\n[next] 1) show --id %s\n       2) write %s\n       3) check\n       4) build"
        % (index["materials"][0]["id"] if index["materials"] else "MAT",
           work / "draft.json"))


def do_show(args):
    inp, out, work = P.paths()
    index, _ = A.read_json(work / "index.json")
    if index is None:
        index = P.build_index(inp)
        A.write_json(work / "index.json", index)
    selected = [m for m in index["materials"] if not args.id or args.id in (m["id"], m["rel"])]
    if not selected:
        log("no match --id=%s; ids: %s"
            % (args.id, ", ".join(m["id"] for m in index["materials"])))
        return
    shown = 0
    for mat in selected:
        log("\n### %s (%s, %dB, %s)" % (mat["id"], mat["kind"], mat["bytes"], mat["quality"]))
        for loc, text in mat["units"]:
            if args.grep and args.grep.lower() not in text.lower():
                continue
            shown += 1
            if shown > args.limit:
                log("... --limit=%d reached" % args.limit)
                return
            log("%s | %s" % (loc, text[:args.chars]))
    log("\nprinted %d units" % shown)


# ------------------------------------------------------------------------ check
def do_check(args):
    inp, out, work, case, case_path, case_err, case_id, index = P.gather_context()
    units = A.flatten_index(index)
    plan, _ = A.read_json(work / "tolerance_plan.json")
    plan = plan or {"entries": {}}
    draft, _ = A.read_json(work / "draft.json")
    d = draft if isinstance(draft, dict) else {}

    errors, warns, accepted, rejected, widened = [], [], 0, 0, 0
    if not d:
        errors.append("draft_missing:%s" % (work / "draft.json"))
        if (work / "draft.md").exists():
            warns.append("draft_markdown_only: not structurally checkable")
    for section in ("paper", "plan", "params", "claims", "conclusion"):
        if not d.get(section):
            if section in ("params", "claims", "conclusion"):
                errors.append("draft_section_empty:" + section)
            else:
                warns.append("draft_section_empty:" + section)

    for claim in d.get("claims") or []:
        tag = str(claim.get("id") or "?")
        if not str(claim.get("text") or "").strip():
            errors.append("claim_text_empty:" + tag)
        if claim.get("confidence") not in ("direct", "inferred", "undetermined"):
            errors.append("claim_confidence_invalid:" + tag)
        if not claim.get("evidence"):
            errors.append("claim_without_evidence:" + tag)
        for ev in claim.get("evidence") or []:
            ok, hits, why = A.validate_evidence(units, ev)
            if ok:
                accepted += 1
                if why == "locator_differs_from_index":
                    warns.append("locator_mismatch:%s->%s" % (tag, hits[0]["locator"]))
            else:
                rejected += 1
                errors.append("evidence_rejected:%s:%s:%s"
                              % (tag, why, A.clip(str(ev.get("quote")), 60)))

    for param in d.get("params") or []:
        if param.get("class") not in PARAM_CLASSES:
            errors.append("param_class_invalid:%s" % param.get("name"))
        if param.get("value") in (None, ""):
            warns.append("param_value_empty:%s" % param.get("name"))
        if param.get("class") == "paper" and not (param.get("evidence") or {}).get("quote"):
            errors.append("paper_param_without_quote:%s" % param.get("name"))

    planned = {P.key_norm(k): v for k, v in (plan.get("entries") or {}).items()}
    for band in d.get("tolerance") or []:
        base = planned.get(P.key_norm(band.get("metric")))
        if not base:
            warns.append("tolerance_not_predeclared:%s" % band.get("metric"))
            continue
        for field_name in ("abs_tol", "rel_tol"):
            draft_value, plan_value = band.get(field_name), base.get(field_name)
            if isinstance(draft_value, (int, float)) and isinstance(plan_value, (int, float)) \
                    and draft_value > plan_value * (1 + 1e-9):
                widened += 1
                errors.append("tolerance_widened_after_run:%s:%s>%s"
                              % (band.get("metric"), draft_value, plan_value))

    if (d.get("conclusion") or {}).get("verdict") not in P.VERDICTS + (None,):
        errors.append("conclusion_verdict_invalid")
    if not (d.get("paper_values") or d.get("tolerance")):
        warns.append("no_reported_paper_values: build falls back to case.json")

    counts = dict(claims=len(d.get("claims") or []), evidence_ok=accepted,
                  evidence_rejected=rejected, params=len(d.get("params") or []),
                  tolerance_entries=len(d.get("tolerance") or []),
                  tolerance_widened=widened)
    A.write_json(work / "check_report.json",
                 {"draft": str(work / "draft.json"), "errors": errors,
                  "warnings": warns, "counts": counts, "pass": not errors})
    log("== check %s ==" % ("PASS" if not errors else "FAIL"))
    log("claims=%(claims)d ok=%(evidence_ok)d rejected=%(evidence_rejected)d "
        "params=%(params)d tol=%(tolerance_entries)d widened=%(tolerance_widened)d"
        % counts)
    for item in errors[:25]:
        log("  ERROR " + item)
    for item in warns[:25]:
        log("  WARN  " + item)
    log("report: %s" % (work / "check_report.json"))


# ----------------------------------------------------------------------- doctor
def do_doctor(args):
    """Post-hoc structural audit of the artefacts already on disk."""
    inp, out, work = P.paths()
    result, _ = A.read_json(out / "result.json")
    record, _ = A.read_json(out / "reproduction.json")
    result = result if isinstance(result, dict) else {}
    record = record if isinstance(record, dict) else {}

    def note(tag, good, detail=""):
        checks.append((tag, good, detail))

    checks = []
    note("result_json_parsed", bool(result), str(out / "result.json"))
    absent = [k for k in P.REQUIRED_FIELDS if k not in result]
    note("envelope_fields", not absent, ",".join(absent))
    case, _case_path, _case_err = P.load_case(inp)
    contract = case.get("output_contract") if isinstance(case.get("output_contract"),
                                                        dict) else {}
    missing_contract = sorted(k for k in contract if k not in result)
    note("contract_keys_present", not missing_contract, ",".join(missing_contract))
    plan = result.get("tolerance_plan") or record.get("tolerance_plan") or {}
    note("tolerance_predeclared",
         plan.get("before_any_run") is True and plan.get("declared_step") == "init",
         "%s/%s" % (plan.get("declared_step"), plan.get("before_any_run")))
    conclusion = (record.get("conclusion") or result.get("conclusion") or {})
    verdict = conclusion.get("verdict") if isinstance(conclusion, dict) else None
    note("verdict_known", verdict in P.VERDICTS, str(verdict))
    runs = record.get("runs") or result.get("runs") or []
    good_runs = [r for r in runs if isinstance(r, dict) and r.get("exit_code") == 0]
    note("runs_recorded", bool(good_runs), "%d ok / %d total" % (len(good_runs), len(runs)))
    rows = record.get("comparison") or result.get("comparison") or []
    outside = [r for r in rows if isinstance(r, dict)
               and r.get("verdict") == "out_of_tolerance"]
    inside = [r for r in rows if isinstance(r, dict)
              and r.get("verdict") == "in_tolerance"]
    coherent = not ((verdict == "reproduced" and outside)
                    or (verdict == "not_reproduced" and inside)
                    or (verdict == "partially_reproduced" and not inside))
    note("verdict_matches_rows", coherent,
         "rows in=%d out=%d" % (len(inside), len(outside)))

    log("== doctor ==")
    for tag, good, detail in checks:
        log("  %-24s %s%s" % (tag, "PASS" if good else "FAIL",
                              (" (" + detail + ")") if detail else ""))
    log("doctor summary: %d/%d checks passed"
        % (sum(1 for _t, good, _d in checks if good), len(checks)))


# ------------------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(
        description="Repro-audit kit: init | show | check | build | doctor "
                    "(stdlib only, always exit 0).",
        epilog="flow: init -> agent fills work/draft.json -> check -> build -> doctor; "
               "paths can be overridden with --input/--output/--work")
    subs = parser.add_subparsers(dest="cmd")
    p_init = subs.add_parser("init", help="index the input, freeze tolerance, write "
                                          "a partial result")
    p_init.add_argument("--preview", type=int, default=10)
    p_show = subs.add_parser("show", help="print material text with locators")
    p_show.add_argument("--id")
    p_show.add_argument("--grep")
    p_show.add_argument("--limit", type=int, default=80)
    p_show.add_argument("--chars", type=int, default=600)
    subs.add_parser("check", help="validate the draft: quotes, fields, tolerance widening")
    subs.add_parser("build", help="execute candidates, compare, attribute, finalise result.json")
    subs.add_parser("doctor", help="audit an already written result.json / reproduction.json")
    args = parser.parse_args(P.absorb_path_flags(sys.argv[1:]))
    handlers = {"init": do_init, "show": do_show, "check": do_check, "build": P.do_build,
                "doctor": do_doctor}
    handlers.get(args.cmd, lambda _a: parser.print_help())(args)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        pass
    except Exception:
        try:
            inp, out, _work = P.paths()
            case, _cp, _err = P.load_case(inp)
            res = P.shell_result(case, case.get("case_id") or case.get("id"))
            res.update(status="partial", summary="unhandled exception",
                       errors=[A.clip(traceback.format_exc(), 1200)],
                       degradations=["unhandled_exception"])
            P.publish(out, res)
            sys.stderr.write("fatal: partial result.json written\n")
        except Exception:
            pass
    sys.exit(0)
