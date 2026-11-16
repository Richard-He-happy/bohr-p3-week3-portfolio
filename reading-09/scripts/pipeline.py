#!/usr/bin/env python3
"""pipeline.py - shared plumbing and the build command of the repro-audit kit.

Sub-commands
  init    index /input, pre-declare the tolerance band, emit a partial result.json
  show    print indexed material text together with its locators
  check   validate the agent draft (quotes, sections, tolerance widening)
  build   execute the candidates, compare against reported values, attribute the
          gaps, then write result.json + reproduction.json + reproduction.md
  doctor  re-read an already written result.json and report contract/structure health

Routing
  --input / --output / --work override the SCIM_INPUT / SCIM_OUTPUT / SCIM_WORK
  environment variables, which in turn default to /input, /app/output, /app/work.

The command never dies with a non-zero exit status: every failure path still
writes a legal partial result.json.
"""
import argparse
import hashlib
import json
import os
import platform
import re
import sys
import time
import traceback
from pathlib import Path

import audit_lib as A
import experiment as X

START_TS = time.time()
DEADLINE_TS = time.time() + 780
NUM_RE = X.NUM_RE
REQUIRED_FIELDS = ("case_id", "status", "sources", "uncertainty", "pending_human",
                   "errors", "degradations", "changes", "runtime")
VERDICTS = ("reproduced", "partially_reproduced", "not_reproduced",
            "insufficient_evidence")
PARAM_CLASSES = ("paper", "code_inferred", "chosen")
METRIC_HINTS = ("report", "paper", "expect", "reference", "target", "metric",
                "result", "accura", "score", "f1", "auc", "rmse", "mae", "r2")
PATH_ENV = {"--input": "SCIM_INPUT", "--output": "SCIM_OUTPUT", "--work": "SCIM_WORK"}
BLOCKED_PATH_WORDS = ("toler", "budget", "seed", "limit")

DRAFT_TEMPLATE = {
    "_note": "skeleton for the agent draft; example only, never a formal case result",
    "case_id": None,
    "paper": {"title": None, "doi": None, "repo": None, "commit": None},
    "plan": [{"step": 1, "goal": "", "command": None, "expected": None,
              "status": "pending"}],
    "environment": {"python": None, "platform": None, "packages": {}, "seed": None},
    "params": [{"name": "", "value": None, "class": "paper|code_inferred|chosen",
                "source": "",
                "evidence": {"source_id": "", "locator": "", "quote": ""}}],
    "paper_values": [{"metric": "", "value": None, "unit": None,
                      "evidence": {"source_id": "", "locator": "", "quote": ""}}],
    "tolerance": [{"metric": "", "abs_tol": None, "rel_tol": None, "basis": "",
                   "declared_step": "plan"}],
    "claims": [{"id": "c1", "kind": "paper_result|method|param|environment",
                "text": "", "confidence": "direct|inferred|undetermined",
                "evidence": [{"source_id": "", "locator": "", "quote": ""}]}],
    "attribution": [],
    "pending_human": [],
    "conclusion": {"verdict": "reproduced|partially_reproduced|not_reproduced|"
                             "insufficient_evidence", "reason": ""},
}


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def log(msg=""):
    print(msg, flush=True)


def key_norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


# --------------------------------------------------------------------- context
def absorb_path_flags(argv):
    """Turn --input/--output/--work into env overrides, keep the remaining argv."""
    rest, pos = [], 0
    while pos < len(argv):
        arg = argv[pos]
        if arg in PATH_ENV and pos + 1 < len(argv):
            os.environ[PATH_ENV[arg]] = argv[pos + 1]
            pos += 2
            continue
        matched = next((f for f in PATH_ENV if arg.startswith(f + "=")), None)
        if matched:
            os.environ[PATH_ENV[matched]] = arg.split("=", 1)[1]
        else:
            rest.append(arg)
        pos += 1
    return rest


def paths():
    def pick(env_name, fallback):
        return Path(os.environ.get(env_name) or fallback)

    inp = pick("SCIM_INPUT", "/input")
    out = pick("SCIM_OUTPUT", "/app/output")
    work = pick("SCIM_WORK", "/app/work")
    if not inp.exists():
        inp = next((c for c in (Path.cwd() / "input", Path("/bohr-workspace/input"))
                    if c.is_dir()), inp)
    for folder in (out, work):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    return inp, out, work


def load_case(input_dir):
    """Locate and parse the case descriptor; tolerate a broken one."""
    for candidate in [input_dir / "case.json"] + sorted(input_dir.rglob("case*.json")):
        if candidate.is_file():
            obj, err = A.read_json(candidate)
            if isinstance(obj, dict):
                return obj, candidate, None
            return {}, candidate, (err or "bad_case_json")
    return {}, None, "case_json_not_found"


def build_index(input_dir):
    """Assign stable ids and text units to every material file."""
    materials, used = [], set()
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file() or path.name == "case.json":
            continue
        base = re.sub(r"[^0-9A-Za-z_]+", "_", path.stem).strip("_") or "mat"
        mid, seq = base, 1
        while mid in used:
            seq += 1
            mid = "%s%d" % (base, seq)
        used.add(mid)
        size = path.stat().st_size
        if size > 25 << 20:
            materials.append(dict(id=mid, path=str(path),
                                  rel=str(path.relative_to(input_dir)), kind="skipped",
                                  bytes=size, units=[], quality="skipped", sha1=None,
                                  notes=[">25MB"]))
            continue
        rec = A.harvest_material(path, str(path.relative_to(input_dir)), mid)
        rec.update(id=mid, sha1=hashlib.sha1(path.read_bytes()).hexdigest()[:10])
        materials.append(rec)
    return {"root": str(input_dir), "generated_at": now(), "materials": materials}


def reported_values(case):
    """Pull reported metric numbers out of the case JSON; JSON pointer = locator."""
    out = {}

    def walk(node, path):
        if isinstance(node, dict):
            metric = node.get("metric") or node.get("name")
            value = node.get("value", node.get("reported"))
            if isinstance(metric, str) and isinstance(value, (int, float)) \
                    and not isinstance(value, bool):
                out[metric] = {"value": value, "ptr": "/".join(path),
                               "source": "case.json#metric_value"}
            for k, child in node.items():
                walk(child, path + [str(k)])
        elif isinstance(node, list):
            for idx, child in enumerate(node):
                walk(child, path + [str(idx)])
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            joined = "/".join(path).lower()
            if any(word in joined for word in BLOCKED_PATH_WORDS):
                return
            if not any(word in joined for word in METRIC_HINTS):
                return
            leaf = str(path[-1]).lower()
            if len(path) > 1 and (re.fullmatch(NUM_RE, leaf)
                                  or leaf in ("value", "val", "score")):
                name = str(path[-2])
            else:
                name = str(path[-1])
            out.setdefault(name, {"value": node, "ptr": "/".join(path),
                                  "source": "case.json#/" + "/".join(path)})

    walk(case, [])
    return out


def build_tolerance_plan(case, reported):
    """Freeze the tolerance band before anything runs."""
    entries = {name: dict(A.standard_tolerance(name, hit.get("value")),
                          declared_at=now(), declared_step="init")
               for name, hit in reported.items()}
    declared = []

    def walk(node):
        if isinstance(node, dict):
            metric = node.get("metric") or node.get("name")
            abs_tol = next((node[x] for x in ("abs_tol", "abs", "atol")
                            if isinstance(node.get(x), (int, float))), None)
            rel_tol = next((node[x] for x in ("rel_tol", "rel", "rtol")
                            if isinstance(node.get(x), (int, float))), None)
            if isinstance(metric, str) and (abs_tol is not None or rel_tol is not None):
                entry = dict(entries.get(metric) or A.standard_tolerance(metric, None))
                if abs_tol is not None:
                    entry["abs_tol"] = float(abs_tol)
                if rel_tol is not None:
                    entry["rel_tol"] = float(rel_tol)
                entries[metric] = dict(entry, basis="case_declared", declared_at=now(),
                                       declared_step="init", source="case_declared")
                declared.append(metric)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(case)
    return {"declared_at": now(), "declared_step": "init", "before_any_run": True,
            "source": "case_declared+prior_default" if declared else "prior_default",
            "entries": entries}


def shell_result(case, case_id):
    """Legal partial result with the contract keys already present."""
    res = dict(case_id=case_id, status="partial", summary="", sources=[],
               uncertainty=[], pending_human=[], errors=[], degradations=[],
               changes=[], runtime={})
    contract = case.get("output_contract") if isinstance(case, dict) else None
    if isinstance(contract, dict):
        unmapped = []
        res = {**A.apply_contract(contract, res, unmapped), **res}
        if unmapped:
            res["degradations"].append("contract_field_unmapped:"
                                       + ",".join(sorted(set(unmapped))))
    return res


def publish(out_dir, res):
    """Write result.json with the envelope fields guaranteed."""
    for field in REQUIRED_FIELDS:
        res.setdefault(field, None if field in ("case_id", "status", "runtime") else [])
    res["runtime"] = dict(
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(START_TS)),
        finished_at=now(), elapsed_s=round(time.time() - START_TS, 2),
        python=platform.python_version(), platform=platform.platform(),
        budget_s=780, deadline_hit=time.time() > DEADLINE_TS,
        **(res.get("runtime") or {}))
    A.write_json(out_dir / "result.json", res)


def gather_context():
    inp, out, work = paths()
    case, case_path, case_err = load_case(inp)
    index, _ = A.read_json(work / "index.json")
    if index is None:
        index = build_index(inp)
        A.write_json(work / "index.json", index)
    return (inp, out, work, case, case_path, case_err,
            (case.get("case_id") or case.get("id")), index)


def do_build(args):
    inp, out, work, case, case_path, case_err, case_id, index = gather_context()
    pre = shell_result(case, case_id)
    pre["summary"] = "build in progress"
    publish(out, pre)

    units = A.flatten_index(index)
    errors = [case_err] if case_err else []
    degraded, pending, uncertain = [], [], []
    plan, _ = A.read_json(work / "tolerance_plan.json")
    reported = reported_values(case)
    plan = plan or build_tolerance_plan(case, reported)
    raw_draft, _ = A.read_json(work / "draft.json")
    d = raw_draft if isinstance(raw_draft, dict) else {}

    for item in d.get("paper_values") or []:
        if item.get("metric") and isinstance(item.get("value"), (int, float)):
            ev = item.get("evidence") or {}
            reported[str(item["metric"])] = dict(
                value=item["value"], ptr=ev.get("locator"),
                source="draft.paper_values:" + str(ev.get("locator") or ""))

    env_case = case.get("environment") if isinstance(case.get("environment"), dict) else {}
    seed = next((case.get(k, env_case.get(k)) for k in ("seed", "random_seed", "SEED")
                 if isinstance(case.get(k, env_case.get(k)), (int, str))), None)
    seed_env = {"PYTHONHASHSEED": str(seed), "SEED": str(seed)} if seed is not None else {}

    runs = []
    for item in X.discover_candidates(inp, case):
        left = DEADLINE_TS - time.time()
        if left < 60:
            degraded.append("run_skipped_deadline:" + item["name"])
            pending.append("candidate %s skipped: time budget" % item["name"])
            continue
        rec = X.execute_candidate(item, work, seed_env, min(150, max(20, int(left - 30))))
        runs.append(rec)
        if rec.get("exit_code") != 0:
            degraded.append("run_failed:" + rec["name"])
            pending.append("candidate %s failed (exit=%s)"
                           % (rec["name"], rec.get("exit_code")))
        elif not rec.get("metrics"):
            uncertain.append("candidate %s produced no parseable metric" % rec["name"])
    if not runs:
        degraded.append("no_run_or_no_candidate")
        pending.append("no candidate finished; run manually and fill runs")

    rows = X.build_rows(runs, reported, plan)
    if not rows:
        degraded.append("no_comparison_rows")

    params, claims, evidence = X.collect_findings(d, units)
    for param in params:
        if not param["verified"] and param["klass"] == "paper":
            uncertain.append("param %s claimed paper-stated but its quote is not in the "
                             "materials" % param.get("name"))

    draft_env = d.get("environment") or {}
    env = X.snapshot_env(draft_env, seed_env)
    if not draft_env:
        degraded.append("environment_from_host_only")
        uncertain.append("environment snapshot from host, not matched against paper claims")

    attributions = X.infer_causes(rows) + [x for x in (d.get("attribution") or [])
                                           if isinstance(x, dict)]
    soft_params = [p.get("name") for p in params if p["klass"] in ("chosen", "code_inferred")]
    if soft_params:
        attributions.append(dict(
            metric="*", cause="parameter_restoration", confidence="inferred",
            detail="%d params not paper-stated: %s"
                   % (len(soft_params), ", ".join(map(str, soft_params[:5])))))
    evidence += [dict(claim="comparison:" + row["metric"], locator=row["reported_source"],
                      quote=None, verified=True, check="source_pointer")
                 for row in rows if row["reported_source"]]

    if not runs:
        verdict, reason = "insufficient_evidence", "no candidate ran successfully"
    else:
        judged = [r for r in rows if r["within_tolerance"] is not None]
        inside = [r for r in judged if r["within_tolerance"]]
        if not judged:
            verdict, reason = ("insufficient_evidence",
                               "runs produced no comparable reported value")
        elif len(inside) == len(judged):
            verdict, reason = ("reproduced",
                               "all %d observations inside pre-declared tolerance"
                               % len(judged))
        elif inside:
            verdict, reason = ("partially_reproduced",
                               "%d/%d in tolerance; rest attributed"
                               % (len(inside), len(judged)))
        else:
            verdict, reason = ("not_reproduced",
                               "all %d observations outside tolerance" % len(judged))

    draft_conclusion = d.get("conclusion") or {}
    if draft_conclusion.get("verdict") in VERDICTS:
        if draft_conclusion["verdict"] != verdict:
            degraded.append("verdict_conflict:agent=%s:computed=%s"
                            % (draft_conclusion["verdict"], verdict))
            uncertain.append("agent verdict %s vs computed %s; computed kept"
                             % (draft_conclusion["verdict"], verdict))
        if draft_conclusion.get("reason"):
            reason = "%s (agent: %s)" % (reason, A.clip(str(draft_conclusion["reason"]), 260))
    else:
        pending.append("draft has no verdict; computed verdict needs agent review")

    for mat in index["materials"]:
        if mat.get("quality") != "ok":
            degraded.append("material_quality:%s:%s" % (mat["id"], mat["quality"]))
        if mat.get("kind") in ("image", "skipped", "zip", "pptx"):
            pending.append("material %s (%s) not content-parsed" % (mat["id"], mat["kind"]))
    if not d:
        degraded.append("no_draft:deterministic_minimal_delivery")
        pending.append("draft missing: plan/params/claims are script-minimal; fill "
                       "draft.json and rerun")

    tolerance_rows = [dict(v, metric=k) for k, v in (plan.get("entries") or {}).items()]
    counts = dict(
        materials=len(index["materials"]), runs=len(runs),
        runs_ok=sum(1 for r in runs if r.get("exit_code") == 0),
        comparison_rows=len(rows),
        in_tolerance=sum(1 for r in rows if r["within_tolerance"] is True),
        out_of_tolerance=sum(1 for r in rows if r["within_tolerance"] is False),
        no_reported_value=sum(1 for r in rows if r["within_tolerance"] is None),
        claims_verified=sum(1 for c in claims for e in c["evidence"] if e["verified"]),
        claims_rejected=sum(1 for c in claims for e in c["evidence"] if not e["verified"]),
        params=len(params), tolerance_entries=len(tolerance_rows))

    status = "ok"
    if case_err:
        status = "input_error"
    elif not runs or verdict == "insufficient_evidence":
        status = "insufficient_evidence"
    if pending or degraded:
        status = "partial" if status == "ok" else status
    summary = ("verdict %s; %d runs, %d rows (in %d / out %d / n.a. %d)"
               % (verdict, len(runs), len(rows), counts["in_tolerance"],
                  counts["out_of_tolerance"], counts["no_reported_value"]))

    record = dict(
        case_id=case_id, status=status, summary=summary, generated_at=now(),
        scope=A.clip(str(case.get("task_instruction")
                         or case.get("organizer_supplied_scope")
                         or "locate method -> env -> params -> run -> compare -> attribute"),
                     600),
        paper=d.get("paper") or {},
        materials=[dict(id=m["id"], rel=m["rel"], kind=m["kind"], bytes=m["bytes"],
                        sha1=m.get("sha1"), units=len(m["units"]),
                        quality=m["quality"], notes=m.get("notes") or [])
                   for m in index["materials"]],
        environment=env, tolerance_plan=plan, params=params,
        plan=d.get("plan") or [
            dict(step=i + 1, goal=g, status="done")
            for i, g in enumerate(("locate materials", "pre-declare tolerance",
                                   "run candidates", "compare and attribute", "conclude"))],
        runs=runs, comparison=rows, attribution=attributions,
        tolerance=tolerance_rows, claims=claims, evidence=evidence,
        sources=[dict(id=m["id"], path=m["path"], kind=m["kind"], bytes=m["bytes"],
                      sha1=m.get("sha1"),
                      locator_style="p<i>|#h/p<i>|r<i>|#/ptr")
                 for m in index["materials"]],
        uncertainty=uncertain, pending_human=sorted(set(pending)),
        gaps=sorted(set(pending)), errors=errors,
        degradations=sorted(set(degraded)), counts=counts,
        artifacts=dict(reproduction_md=str(out / "reproduction.md"),
                       reproduction_json=str(out / "reproduction.json"),
                       runs_dir=str(work / "runs"), index=str(work / "index.json"),
                       tolerance_plan=str(work / "tolerance_plan.json")),
        changes=[dict(at=now(), change="build wrote reproduction record and filled contract"),
                 dict(at=plan.get("declared_at"),
                      change="init pre-declared %d tolerance entries"
                             % len(tolerance_rows))],
        conclusion=dict(verdict=verdict, reason=reason,
                        basis="all in tolerance=reproduced; some=partially_reproduced; "
                              "none=not_reproduced; no run/value=insufficient_evidence"))

    A.write_json(out / "reproduction.json", record)
    A.write_text(out / "reproduction.md", X.render_report(record))
    contract = case.get("output_contract") if isinstance(case.get("output_contract"),
                                                        dict) else {}
    unmapped = []
    feed = dict(record)
    feed["reproduction"] = {k: record[k] for k in
                            ("case_id", "generated_at", "scope", "paper", "materials",
                             "environment", "tolerance_plan", "params", "plan", "runs",
                             "comparison", "attribution", "claims", "conclusion",
                             "counts", "gaps", "degradations")}
    res = A.apply_contract(contract, feed, unmapped) if contract else {}
    res.update(record)
    if unmapped:
        res["degradations"] = sorted(set(res["degradations"])
                                     | {"contract_field_unmapped:"
                                        + ",".join(sorted(set(unmapped)))})
    publish(out, res)

    log("== build ==\nruns %d (ok %d)" % (len(runs), counts["runs_ok"]))
    for rec in runs:
        log("  %-16s exit=%s %.2fs metrics=%d"
            % (rec["name"], rec.get("exit_code"), rec.get("duration_s") or 0,
               len(rec.get("metrics") or {})))
    log("rows %d in=%d out=%d n.a.=%d"
        % (len(rows), counts["in_tolerance"], counts["out_of_tolerance"],
           counts["no_reported_value"]))
    for row in rows[:20]:
        log("  %-14s %-16s obs=%s rep=%s dev=%s -> %s"
            % (row["run"], row["metric"], row["observed"], row["reported"],
               row["rel_dev"], row["verdict"]))
    log("verdict %s | status %s\nresult.json -> %s"
        % (verdict, status, out / "result.json"))


