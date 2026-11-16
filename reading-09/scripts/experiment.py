#!/usr/bin/env python3
"""experiment.py - experiment execution and interpretation for the repro-audit kit.

Responsibilities
  * pick the candidate implementations out of the case / material tree
  * execute each one in an isolated scratch directory and capture its log
  * parse numeric metrics out of candidate stdout
  * compare observations against reported values under the pre-declared tolerance
  * suggest a cause per differing metric (deterministic heuristics)
  * collect quote-verified parameters and claims from the draft
  * render the reproduction record as Markdown

Standard library only. Imported by cli.py; not a standalone entry point except
`python -B experiment.py --help` for a short module summary.
"""
import argparse
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import audit_lib as A

NUM_RE = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
CANDIDATE_CASE_KEYS = ("candidates", "implementations", "candidate_methods",
                       "methods", "code_variants")
CODE_HINTS = ("cand", "impl", "method", "baseline", "variant", "solution")
DIR_HINTS = ("candidate", "candidates", "impl", "implementation", "code",
             "src", "repo", "method", "methods", "baseline")
SKIP_NAME = re.compile(r"(setup|conftest|test_|__)|_(test|setup)$")
COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv")
VERIFIED_STATE = ("ok", "locator_differs_from_index")


def slug(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def scratch_name(name):
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", name).strip("_")[:40]
    return cleaned or "cand"


# --------------------------------------------------------------- candidate pick
def discover_candidates(input_dir, case):
    """Case-declared candidates win; otherwise score .py files by hints."""
    declared = []
    for field in CANDIDATE_CASE_KEYS:
        listed = case.get(field)
        for pos, item in enumerate(listed if isinstance(listed, list) else []):
            if isinstance(item, dict) and (item.get("command") or item.get("entry")
                                           or item.get("path")):
                declared.append(dict(name=str(item.get("name") or "cand%d" % (pos + 1)),
                                     command=item.get("command"),
                                     path=str(item.get("entry") or item.get("path") or ""),
                                     declared=True, score=9))
    if declared:
        return declared[:4]
    found = []
    for path in sorted(input_dir.rglob("*.py")):
        dirs = [part.lower() for part in path.relative_to(input_dir).parts[:-1]]
        stem = path.stem.lower()
        weight = 1 if any(h in stem for h in CODE_HINTS) else 0
        weight += 2 if any(h in dirs for h in DIR_HINTS) else 0
        if not weight and not SKIP_NAME.match(stem):
            weight = 0.5
        if weight:
            found.append(dict(name=stem, path=str(path), command=None,
                              declared=False, score=weight))
    found.sort(key=lambda c: (-c["score"], c["name"]))
    unique = {}
    for item in found:
        unique.setdefault(item["name"], item)
    return list(unique.values())[:4]


# --------------------------------------------------------------- metric parsing
def _numbers(node, bucket, path=""):
    if isinstance(node, dict):
        for key, val in node.items():
            _numbers(val, bucket, (path + "." + str(key)) if path else str(key))
    elif isinstance(node, list):
        for idx, val in enumerate(node[:40]):
            _numbers(val, bucket, "%s[%d]" % (path, idx))
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        bucket[path] = node


def parse_metrics(text):
    """Mine a flat metric dict from JSON blobs or `name: value` lines."""
    body = (text or "").strip()
    if body.startswith("{"):
        blobs = [body]
    else:
        blobs = [line.strip() for line in body.splitlines()[-40:]
                 if line.strip().startswith("{") and line.strip().endswith("}")][:1]
    for blob in blobs:
        bucket = {}
        try:
            _numbers(json.loads(blob), bucket)
        except Exception:
            bucket = {}
        if bucket:
            return bucket
    mined = {}
    line_re = (r"^\s*[-*]?\s*([A-Za-z_][\w .%/+\-]{0,40}?)\s*[=:,\t|]\s*("
               + NUM_RE + r")\s*%?\s*$")
    for line in body.splitlines():
        m = re.match(line_re, line)
        if m:
            mined.setdefault(re.sub(r"\s+", "_", m.group(1).strip().lower()),
                             float(m.group(2)))
    return mined


# ------------------------------------------------------------------ execution
def execute_candidate(item, work_dir, extra_env, timeout):
    """Copy the candidate into runs/<name>, run it, capture metrics and logs."""
    run_dir = work_dir / "runs" / scratch_name(item["name"])
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    rec = dict(name=item["name"], declared=item.get("declared", False),
               workdir=str(run_dir), metrics={}, exit_code=None)
    # Defaults first, caller-supplied overrides last so an explicit seed wins.
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["MPLBACKEND"] = "Agg"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra_env or {})
    started = time.time()
    try:
        if item.get("command"):
            cmd = (item["command"] if isinstance(item["command"], list)
                   else shlex.split(str(item["command"])))
            rec["source"] = "declared_command"
        else:
            src = Path(item["path"])
            shutil.copytree(src.parent, run_dir, dirs_exist_ok=True, ignore=COPY_IGNORE)
            if not (run_dir / src.name).exists():
                rec["error"] = "file_missing_after_copy"
                return rec
            cmd = [sys.executable, "-B", str(run_dir / src.name)]
            rec["source"] = str(src)
        rec["command"] = cmd
        before = {str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()}
        proc = subprocess.run(cmd, cwd=str(run_dir), capture_output=True, text=True,
                              timeout=timeout, env=env, errors="replace")
        rec.update(exit_code=proc.returncode, stdout_tail=A.clip(proc.stdout, 1400),
                   stderr_tail=A.clip(proc.stderr, 500),
                   metrics=parse_metrics(proc.stdout))
        rec["outputs"] = sorted({str(p.relative_to(run_dir)) for p in run_dir.rglob("*")
                                 if p.is_file()
                                 and str(p.relative_to(run_dir)) not in before})[:12]
    except subprocess.TimeoutExpired:
        rec["error"] = "timeout_%ss" % timeout
    except Exception as exc:
        rec["error"] = "%s:%s" % (type(exc).__name__, exc)
    rec["duration_s"] = round(time.time() - started, 2)
    return rec


# --------------------------------------------------------------- comparison
def tolerance_for(metric, plan, reported):
    for name, entry in (plan.get("entries") or {}).items():
        if slug(name) == slug(metric):
            return {k: entry.get(k) for k in ("abs_tol", "rel_tol", "basis",
                                              "declared_step")}
    return dict(A.standard_tolerance(metric, reported), declared_step="init")


def build_rows(runs, reported, plan):
    """One row per (metric, run) pair that produced a number."""
    rows, indexed = [], {slug(k): v for k, v in reported.items()}
    metrics_order = list(dict.fromkeys([m for r in runs for m in (r.get("metrics") or {})]))
    for metric in metrics_order:
        hit = indexed.get(slug(metric))
        if not hit:
            hit = next((v for k, v in indexed.items()
                        if slug(metric) and (slug(metric) in k or k in slug(metric))), None)
        target = hit.get("value") if hit else None
        tol = tolerance_for(metric, plan, target)
        for run in runs:
            observed = (run.get("metrics") or {}).get(metric)
            if observed is None:
                continue
            cmp = (A.within_tolerance(observed, target, tol["abs_tol"], tol["rel_tol"])
                   if target is not None else {})
            inside = cmp.get("within_tolerance")
            rows.append(dict(metric=metric, run=run["name"], observed=observed,
                             reported=target, abs_tol=tol["abs_tol"],
                             rel_tol=tol["rel_tol"], tolerance_basis=tol["basis"],
                             reported_source=hit.get("source") if hit else None,
                             abs_dev=cmp.get("abs_dev"), rel_dev=cmp.get("rel_dev"),
                             within_tolerance=inside,
                             verdict={True: "in_tolerance",
                                      False: "out_of_tolerance"}.get(
                                          inside, "no_reported_value")))
    return rows


# --------------------------------------------------------------- attribution
def infer_causes(rows):
    """Deterministic cause hints; the agent still has to justify them."""
    causes, grouped = [], {}
    for row in rows:
        grouped.setdefault(row["metric"], []).append(row)
    for metric, group in grouped.items():
        reported = next((r["reported"] for r in group if r["reported"] is not None), None)
        misses = [r for r in group if r["within_tolerance"] is False]
        if reported is None:
            causes.append(dict(metric=metric, cause="paper_value_unavailable",
                               confidence="determined",
                               detail="no reported value in the materials; agreement undecidable"))
        elif not misses:
            causes.append(dict(metric=metric, cause="none", confidence="determined",
                               detail="every observation stayed inside the pre-declared tolerance"))
        else:
            values = [r["observed"] for r in group]
            band = max([r["rel_tol"] or 0 for r in group] + [0.02])
            spread = (max(values) - min(values)) if len(values) > 1 else 0.0
            if len(values) > 1 and spread <= abs(reported) * band:
                causes.append(dict(
                    metric=metric, cause="shared_upstream_factor", confidence="inferred",
                    detail="candidates agree (spread %.6g) yet both miss %.6g -> shared "
                           "upstream: data version/split, restored params, environment"
                           % (spread, reported)))
            elif len(values) > 1:
                causes.append(dict(metric=metric, cause="implementation",
                                   confidence="inferred",
                                   detail="candidates disagree (spread %.6g beyond tolerance)"
                                          % spread))
            else:
                causes.append(dict(
                    metric=metric, cause="unverified_single_implementation",
                    confidence="inferred",
                    detail="only one candidate produced numbers; implementation vs upstream "
                           "cannot be separated"))
    return causes


# --------------------------------------------------------------- draft audit
def collect_findings(draft, units):
    """Verify quotes for params and claims; return (params, claims, evidence)."""
    params, claims, evidence = [], [], []
    for item in draft.get("params") or []:
        ev = item.get("evidence") or {}
        ok, hits, why = A.validate_evidence(units, ev)
        params.append(dict(name=item.get("name"), value=item.get("value"),
                           klass=item.get("class"), source=item.get("source"),
                           locator=hits[0]["locator"] if hits else ev.get("locator"),
                           quote=ev.get("quote"), verified=ok, check=why))
    for claim in draft.get("claims") or []:
        verified = []
        for ev in claim.get("evidence") or []:
            ok, hits, why = A.validate_evidence(units, ev)
            verified.append(dict(source_id=hits[0]["source_id"] if hits else ev.get("source_id"),
                                 locator=hits[0]["locator"] if hits else ev.get("locator"),
                                 quote=ev.get("quote"), verified=ok, check=why))
        claims.append(dict(id=claim.get("id"), kind=claim.get("kind"),
                           text=claim.get("text"), confidence=claim.get("confidence"),
                           evidence=verified))
        evidence += [dict(e, claim=claim.get("id")) for e in verified if e["verified"]]
    return params, claims, evidence


def snapshot_env(draft_env, seed_env):
    """Environment snapshot from the draft, filled with host facts."""
    packages = {}
    for name in ("numpy", "pandas", "scipy", "sklearn", "matplotlib"):
        try:
            packages[name] = getattr(__import__(name), "__version__", "?")
        except Exception:
            pass
    return dict(python=draft_env.get("python") or platform.python_version(),
                platform=draft_env.get("platform") or platform.platform(),
                packages=draft_env.get("packages") or packages,
                seed=draft_env.get("seed") or seed_env.get("SEED"),
                snapshot_source="draft+host" if draft_env else "host")


# --------------------------------------------------------------- rendering
def _table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for row in rows:
        out.append("| " + " | ".join("" if cell is None else str(cell).replace("|", "/")
                                     for cell in row) + " |")
    out.append("")
    return out


def render_report(record):
    """Reproduction record as Markdown: materials -> env -> params -> tolerance
    -> runs -> comparison -> attribution -> gaps -> evidence -> conclusion."""
    lines = ["# Reproduction and method-verification record\n",
             "- case_id: `%s` | generated: %s" % (record.get("case_id"),
                                                  record.get("generated_at")),
             "- conclusion: **%s** - %s" % (record["conclusion"]["verdict"],
                                            record["conclusion"]["reason"]),
             "- scope: %s\n" % record.get("scope")]
    lines += ["## 1. Materials and locators\n"]
    lines += _table(["id", "file", "kind", "bytes", "units", "quality", "sha1"],
                    [[m["id"], m["rel"], m["kind"], m["bytes"], m["units"],
                      m["quality"], m["sha1"] or "-"] for m in record["materials"]])
    notes = [n for m in record["materials"] for n in (m.get("notes") or [])]
    if notes:
        lines.append("Parse notes: " + "; ".join(notes) + "\n")
    lines += ["## 2. Environment snapshot\n```json\n"
              + json.dumps(record["environment"], ensure_ascii=False, indent=2) + "\n```\n"]
    lines += ["## 3. Parameter restoration\n"]
    if record["params"]:
        lines += _table(["param", "value", "class", "source", "locator", "quote check"],
                        [[p.get("name"), p.get("value"), p.get("klass"), p.get("source"),
                          p.get("locator"), "ok" if p.get("verified") else p.get("check")]
                         for p in record["params"]])
    else:
        lines.append("_No parameter table in the draft; see section 8._\n")
    lines += ["## 4. Pre-declared tolerance\n"]
    lines.append("step `%s`, time `%s`, before any run = `%s`, source `%s`.\n"
                 % (record["tolerance_plan"].get("declared_step"),
                    record["tolerance_plan"].get("declared_at"),
                    record["tolerance_plan"].get("before_any_run"),
                    record["tolerance_plan"].get("source")))
    lines += _table(["metric", "abs_tol", "rel_tol", "basis"],
                    [[name, entry.get("abs_tol"), entry.get("rel_tol"), entry.get("basis")]
                     for name, entry in (record["tolerance_plan"].get("entries") or {}).items()])
    lines += ["## 5. Runs\n"]
    for run in record["runs"]:
        lines.append("### %s\n" % run["name"])
        lines.append("- command: `%s`" % (" ".join(map(str, run.get("command") or [])) or "-"))
        lines.append("- workdir: `%s` | exit: %s | %ss"
                     % (run.get("workdir"), run.get("exit_code"), run.get("duration_s")))
        if run.get("error"):
            lines.append("- error: `%s`" % run["error"])
        lines.append("- metrics: `%s`\n"
                     % json.dumps(run.get("metrics") or {}, ensure_ascii=False))
        if run.get("stdout_tail"):
            lines.append("```text\n" + run["stdout_tail"][:700] + "\n```\n")
    if not record["runs"]:
        lines.append("_No candidate implementation started; see section 8._\n")
    lines += ["## 6. Result comparison (pre-declared tolerance)\n"]
    if record["comparison"]:
        lines += _table(["run", "metric", "observed", "reported", "rel_dev", "rel_tol",
                         "verdict", "reported source"],
                        [[x["run"], x["metric"], x["observed"], x["reported"],
                          x["rel_dev"], x["rel_tol"], x["verdict"], x["reported_source"]]
                         for x in record["comparison"]])
    else:
        lines.append("_No comparable numeric pairs._\n")
    lines += ["## 7. Difference attribution\n"]
    lines += _table(["metric", "cause", "confidence", "detail"],
                    [[x.get("metric"), x.get("cause"), x.get("confidence"),
                      x.get("detail")] for x in record["attribution"]])
    lines += ["## 8. Gaps, degradations, handover\n"]
    lines += ["- gap: %s" % g for g in (record["gaps"] or ["(none)"])]
    lines.append("")
    lines += ["- degraded: %s" % g for g in (record["degradations"] or ["(none)"])]
    lines += ["\n## 9. Evidence\n"]
    evidence_rows = [[c.get("id"), e.get("source_id"), e.get("locator"),
                      A.clip(str(e.get("quote")), 90),
                      "ok" if e.get("verified") else e.get("check")]
                     for c in record["claims"] for e in c["evidence"]][:120]
    if evidence_rows:
        lines += _table(["claim", "source", "locator", "quote", "check"], evidence_rows)
    else:
        lines.append("_No quoted evidence._\n")
    lines += ["## 10. Conclusion\n"]
    lines += ["- graded verdict: **%s**" % record["conclusion"]["verdict"],
              "- basis: %s" % record["conclusion"]["reason"],
              "- rule: %s" % record["conclusion"]["basis"],
              "- counts: `%s`\n" % json.dumps(record["counts"], ensure_ascii=False)]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        description="Experiment layer: candidate discovery, execution, comparison, "
                    "attribution, Markdown rendering (imported by cli.py)")
    ap.add_argument("--selftest", action="store_true",
                    help="run the small parser assertion set")
    args = ap.parse_args()
    if args.selftest:
        ok = (parse_metrics('{"a": {"b": 1.5}}') == {"a.b": 1.5}
              and parse_metrics("score: 0.91\n") == {"score": 0.91})
        print("experiment selftest: %s" % ("PASS" if ok else "FAIL"))
        sys.exit(0 if ok else 1)
    ap.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()
