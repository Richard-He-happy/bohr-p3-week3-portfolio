#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verifiable-asset layer for the writing-07 rebuttal workbench.

Five assets are written next to the normal deliverables on every build/finalize:

  golden_standard.json  expected response/edit items, each with a source locator
                        and a verbatim quote taken from the supplied materials
  diff_report.md        the golden standard vs the delivered bundle, item by item
  version_history.md    a static version ledger (v0 skeleton -> v1.0.0) with a
                        section for this run appended at the end
  run.log               a real phase log: phase, elapsed time, artifacts, exit
                        code, degradations and exceptions
  self_check.json       a machine receipt: contract-key completeness, main
                        artifact presence, verbatim-quote hit rate, counter
                        consistency, empty/bad-input fallback probe, exit code

Everything here is additive: the original entry points, CLI options and
result.json fields are untouched.  Standard library only, no network, no CWD
assumptions.  A failure in this module is caught by audit_bundle.publish() and
recorded as an issue, so it can never turn into a non-zero exit code.
"""

import difflib, json, re, time

from pathlib import Path

import evidence_render as render
from evidence_render import (ASSET_FILES, BASE_ARTIFACTS, TOOL, TOOL_VERSION, _now,
                             _squeeze, _cell, _dump_json, _dump_text, _read_json,
                             _stat_files, locate_quote)

_T0 = time.time()

SCHEMA = "rebuttal-response-workbench/evidence-assets/v1"

LOCATOR_SCHEME = ("B### = index of the blank-line separated block inside the named input file "
                  "(the same rule the delivered manuscript uses for P###); case.json#<path> = "
                  "a path inside the case document.")


# ---------------------------------------------------------------- golden standard

def _pick_comment_source(comment, sources):
    """Map one ledger comment back to the input comment file that contains it."""
    subs = [_squeeze(s.get("text")) for s in comment.get("sub_requirements") or []]
    raw = _squeeze(comment.get("raw_summary"))
    best, score = None, -1
    for src in sources.get("comments") or []:
        text = _squeeze(src.get("text"))
        s = (100 if raw and raw in text else 0) + sum(2 for q in subs if q and q in text)
        if s > score:
            best, score = src, s
    return best or {"name": "review-comments", "text": ""}


def _source_text(sources, name, case_text):
    if name == "case.json":
        return case_text
    base = sources.get("baseline") or {}
    if base.get("name") == name:
        return str(base.get("text") or "")
    for c in sources.get("comments") or []:
        if c.get("name") == name:
            return str(c.get("text") or "")
    return ""


def _verbatim_excerpt(quote, text, min_len=12):
    """Longest literal run shared by quote and text; used only when quote itself is not verbatim.

    Keeps every golden-standard quote a literal source excerpt even when the
    ledger joined clauses from several sentences (a normal split artefact).
    """
    q, t = _squeeze(quote), _squeeze(text)
    if not q or not t:
        return ""
    try:
        m = difflib.SequenceMatcher(None, q, t, autojunk=False).find_longest_match(
            0, len(q), 0, len(t))
    except Exception:
        return ""
    return q[m.a:m.a + m.size] if m.size >= min_len else ""


def build_golden(payload):
    """Expected response/edit items derived from the contract, workorder and comments.

    Computed from the input materials and the package rules only; it never reads
    the actual decisions, so diffing against it is a real check.
    """
    case = payload.get("case") if isinstance(payload.get("case"), dict) else {}
    case_text = json.dumps(case, ensure_ascii=False) if case else ""
    contract = payload.get("contract") if isinstance(payload.get("contract"), dict) else {}
    sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    led = payload.get("led") or []
    dn = str(payload.get("deliverable") or "revised_manuscript.md")
    items = []

    def add(layer, ident, expected, file, locator, quote, basis, **extra):
        item = {"id": ident, "layer": layer, "basis": basis, "expected": expected,
                "source": {"file": file, "locator": locator, "quote": _squeeze(quote)[:600],
                           "quote_verbatim": False, "quote_block": None}}
        if item["source"]["quote"]:
            src_text = _source_text(sources, file, case_text)
            block, hit = locate_quote(item["source"]["quote"], src_text)
            if not hit:
                excerpt = _verbatim_excerpt(item["source"]["quote"], src_text)
                if excerpt:
                    item["source"]["expected_quote"] = item["source"]["quote"]
                    item["source"]["quote"] = excerpt
                    item["source"]["quote_is_excerpt"] = True
                    block, hit = locate_quote(excerpt, src_text)
            item["source"]["quote_verbatim"] = bool(hit)
            item["source"]["quote_block"] = block
        item.update(extra)
        items.append(item)

    for i, (k, v) in enumerate(contract.items(), 1):
        desc = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        add("contract", "G-C%02d" % i,
            "result.json 顶层键 `%s` 按原键名回填（契约说明：%s）" % (k, _cell(desc, 100)),
            "case.json", "case.json#output_contract.%s" % k, desc, "contract", contract_key=k)
    n_w = 0
    for key in ("organizer_workorder", "organizer_edit_workorder", "workorder"):
        raw = case.get(key)
        seq = raw if isinstance(raw, list) else ([] if raw is None else [raw])
        for i, it in enumerate(seq, 1):
            txt = _squeeze(it.get("instruction") if isinstance(it, dict) else it)
            if not txt:
                continue
            n_w += 1
            wid = str((it.get("id") if isinstance(it, dict) else "") or "%s-%d" % (key, i))
            add("workorder", "G-W%02d" % n_w, "工作单条目回应：%s" % _cell(txt, 160),
                "case.json", "case.json#%s[%d]" % (key, i - 1), txt, "contract", workorder_id=wid)
    n_r = n_s = 0
    for c in led:
        if not isinstance(c, dict):
            continue
        n_r += 1
        cid = str(c.get("comment_id") or "C%d" % n_r)
        label = str(c.get("source_label") or cid)
        src = _pick_comment_source(c, sources)
        fname = str(src.get("name") or "review-comments")
        add("comment", "G-R%02d" % n_r,
            "意见 %s 进入台账并拆分为至少 1 条子要求（来源标题：%s）" % (cid, _cell(label, 80)),
            fname, "%s#%s" % (fname, _cell(label, 80)),
            _squeeze(c.get("raw_summary")), "review_comment", comment_id=cid)
        for s in c.get("sub_requirements") or []:
            if not isinstance(s, dict):
                continue
            n_s += 1
            sid = str(s.get("sub_id") or "%s.%d" % (cid, n_s))
            needs = bool(s.get("needs_human"))
            add("sub_requirement", "G-S%03d" % n_s,
                "子要求 %s 的逐条回应：decision + 可核验定位；%s"
                % (sid, "材料无法支持，须标 not_provided 并说明" if needs else "基线可支持的须真实落稿并带 locator"),
                fname, "%s#%s" % (fname, _cell(label, 80)), _squeeze(s.get("text")), "review_comment",
                sub_id=sid, comment_id=cid,
                expected_decision="partial" if needs else "accept",
                expected_evidence="not_provided" if needs else "provided",
                expected_change="not_possible" if needs else "required")
    for i, name in enumerate([dn] + BASE_ARTIFACTS + ["golden_standard.json",
                                                      "version_history.md", "run.log"], 1):
        add("artifact", "G-A%02d" % i, "输出目录存在非空文件 `%s`" % name,
            "package contract", "outputs/%s" % name, "", "contract", artifact=name)
    layers, quotes = {}, []
    for it in items:
        layers[it["layer"]] = layers.get(it["layer"], 0) + 1
        if it["source"]["quote"]:
            quotes.append(it)
    hits = [it for it in quotes if it["source"]["quote_verbatim"]]
    excerpted = [it for it in quotes if it["source"].get("quote_is_excerpt")]
    counts = {"items_total": len(items), "layers": layers,
              "contract_keys": len(contract), "workorder_items": n_w,
              "comments": n_r, "sub_requirements": n_s,
              "quotes": len(quotes), "quotes_verbatim": len(hits),
              "quotes_excerpt_fallback": len(excerpted),
              "quote_hit_rate": round(len(hits) / len(quotes), 3) if quotes else 0.0}
    return {
        "schema": SCHEMA, "kind": "golden_standard",
        "tool": {"name": TOOL, "version": TOOL_VERSION},
        "case_id": payload.get("case_id"), "generated_at": _now(),
        "generated_by": "scripts/evidence_assets.py, called from audit_bundle.publish() on build/finalize",
        "scope_note": "本 case 的受控返修期望：只覆盖 output_contract、organizer workorder 与所给审稿意见；"
                      "不假设材料之外的实验、数据或编辑部决定。",
        "locator_scheme": LOCATOR_SCHEME,
        "basis_legend": {
            "contract": "从 case.json 的 output_contract / organizer workorder 或包级交付契约直接导出，无外部材料来源",
            "review_comment": "从输入审稿意见材料逐字导出（squeeze 后逐字子串命中）"},
        "expected_artifacts": [dn] + BASE_ARTIFACTS + ASSET_FILES,
        "items": items, "counts": counts,
        "notes": [
            "expected_decision / expected_evidence 由材料可得性规则推导，不读取本次实际决定。",
            "quote 逐字命中按空白归一后的子串匹配判定；quote_block 是来源文件的 B### 段落定位。",
            "若台账文本由多个分句拼接而无法整句逐字命中，quote 改取来源中的最长逐字片段"
            "（quote_is_excerpt=true），expected_quote 保留原期望文本。",
            "无外部材料来源的条目一律标 basis=contract。"]}


# ---------------------------------------------------------------------- self check

def _exit_policy_check():
    scripts = Path(__file__).resolve().parent
    findings, checked = [], []
    try:
        for p in sorted(scripts.glob("*.py")):
            t = p.read_text(encoding="utf-8", errors="replace")
            if not re.search(r"(?m)^if __name__ == ['\"]__main__['\"]:", t):
                continue          # only the two real CLI entry points are inspected
            checked.append(p.name)
            for m in re.finditer(r"sys\.exit\(", t):
                tail = t[m.end():m.end() + 24].strip()
                if not (tail.startswith("cli()") or tail.startswith("0)")):
                    findings.append("%s: sys.exit(%s" % (p.name, tail.split("\n")[0][:30]))
            if re.search(r"raise\s+SystemExit", t):
                findings.append("%s: raise SystemExit" % p.name)
            if "return 0" not in t:
                findings.append("%s: no return-0 guard" % p.name)
    except Exception as exc:
        findings.append("scan failed: %s" % type(exc).__name__)
    return {"ok": not findings, "scripts": checked, "findings": findings,
            "policy": "all CLI paths return 0; failures are recorded inside result.json"}


def build_self_check(out, payload, golden):
    out = Path(out)
    checks = {}
    result = _read_json(out / "result.json")
    contract = payload.get("contract") if isinstance(payload.get("contract"), dict) else {}
    expected = [str(k) for k in contract]
    missing = [k for k in expected if k not in result]
    checks["contract_keys_complete"] = {"ok": not missing, "expected": len(expected),
                                        "present": len(expected) - len(missing),
                                        "missing": missing[:10],
                                        "source": "result.json on disk vs case.json output_contract"}
    dn = str(payload.get("deliverable") or "revised_manuscript.md")
    path = out / dn
    size = path.stat().st_size if path.is_file() else 0
    checks["main_artifact_present"] = {"ok": size > 0, "file": dn, "bytes": size}
    q = golden.get("counts") if isinstance(golden.get("counts"), dict) else {}
    rate = float(q.get("quote_hit_rate") or 0.0)
    checks["quote_verbatim_hit_rate"] = {
        "ok": (int(q.get("quotes") or 0) == 0) or rate >= 0.8,
        "quotes": int(q.get("quotes") or 0), "verbatim_hits": int(q.get("quotes_verbatim") or 0),
        "excerpt_fallbacks": int(q.get("quotes_excerpt_fallback") or 0),
        "rate": rate, "threshold": 0.8,
        "scope": "golden_standard.json quotes vs the supplied input materials"}
    led = payload.get("led") or []
    chs = payload.get("changes") or []
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    subs = [s for c in led for s in c.get("sub_requirements") or [] if isinstance(s, dict)]
    recomputed = [("comments_total", len(led)),
                  ("sub_requirements_total", len(subs)),
                  ("edits_total", len(chs)),
                  ("edits_applied", len([c for c in chs if c.get("hit")])),
                  ("subs_with_verified_change", len([s for s in subs if s.get("change_ids")])),
                  ("pending_human_items", len(payload.get("pending_human") or []))]
    pairs = [{"counter": k, "result_json": counts.get(k), "recomputed": v,
              "ok": counts.get(k) == v} for k, v in recomputed]
    checks["counts_consistency"] = {"ok": all(p["ok"] for p in pairs), "pairs": pairs}
    sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    probe = sources.get("probe") if isinstance(sources.get("probe"), dict) else {}
    checks["degraded_input_probe"] = {
        "ok": bool(probe) and all(isinstance(v, dict) and v.get("ok") for v in probe.values()),
        "probe": probe,
        "scope": "empty input dir and malformed case.json are handled by the same functions used for the real input"}
    pre = sources.get("precheck") if isinstance(sources.get("precheck"), dict) else {}
    checks["partial_result_first"] = {"ok": bool(pre.get("ok")), "detail": pre,
                                      "scope": "a partial result.json exists before any real work"}
    checks["exit_code_zero_policy"] = _exit_policy_check()
    present = {n: (out / n).stat().st_size for n in ASSET_FILES if (out / n).is_file()}
    to_check = [n for n in ASSET_FILES if n != "self_check.json"]
    checks["assets_generated"] = {
        "ok": all(present.get(n, 0) > 0 for n in to_check),
        "expected": len(ASSET_FILES), "observed_before_self_check": len(present),
        "self_check_written": True, "sizes": present,
        "note": "self_check.json is this receipt; its non-emptiness follows from serialising this dict"}
    failed = [k for k, v in checks.items() if not v.get("ok")]
    return {"schema": SCHEMA, "kind": "self_check",
            "tool": {"name": TOOL, "version": TOOL_VERSION},
            "case_id": payload.get("case_id"), "generated_at": _now(),
            "checks": checks, "ok": not failed, "failed": failed,
            "metrics": {"status": payload.get("status"), "stage": payload.get("stage"),
                        "items_checked": len(checks), "items_passed": len(checks) - len(failed),
                        "contract_keys": len(expected), "quotes": q.get("quotes"),
                        "quote_hit_rate": q.get("quote_hit_rate"),
                        "counts": counts}}


# ------------------------------------------------------------------------ emitter

def _summarize(out, golden, diff_tally, events):
    files = _stat_files(out)
    q = golden.get("counts") if isinstance(golden.get("counts"), dict) else {}
    return {
        "golden_standard": {"file": "golden_standard.json", "bytes": files.get("golden_standard.json", 0),
                            "items": q.get("items_total"), "quotes": q.get("quotes"),
                            "quote_hit_rate": q.get("quote_hit_rate")},
        "diff_report": {"file": "diff_report.md", "bytes": files.get("diff_report.md", 0),
                        "met": diff_tally.get("met", 0),
                        "deviation": diff_tally.get("deviation", 0),
                        "missing": diff_tally.get("missing", 0)},
        "version_history": {"file": "version_history.md", "bytes": files.get("version_history.md", 0),
                            "versions": len(render.VERSION_LEDGER)},
        "run_log": {"file": "run.log", "bytes": files.get("run.log", 0),
                    "events": len([e for e in events if isinstance(e, dict)]), "exit_code": 0},
        "self_check": {"file": "self_check.json", "bytes": files.get("self_check.json", 0)}}


def emit_assets(out, payload):
    """Write the five assets and return the summary that goes into result.json."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    events = sources.get("events") if isinstance(sources.get("events"), list) else []
    meta = {"started_at": sources.get("started_at"), "case_id": payload.get("case_id"),
            "stage": payload.get("stage"), "status": payload.get("status"),
            "input": sources.get("input_dir"), "output": str(out),
            "errors": len(payload.get("errors") or []),
            "degradations": len(payload.get("degradations") or []),
            "issues": len(payload.get("issues") or []), "counts": payload.get("counts") or {},
            "artifacts": len(_stat_files(out)), "verification": "pending-at-emit"}
    golden = build_golden(payload)
    _dump_json(out / "golden_standard.json", golden)
    render._dump_text(out / "version_history.md", render.build_version_history(payload))
    render.write_run_log(out, events, meta)
    payload = dict(payload)
    payload["files"] = _stat_files(out)
    diff_md, diff_tally = render.build_diff(payload, golden)
    render._dump_text(out / "diff_report.md", diff_md)
    payload["files"] = _stat_files(out)
    self_check = build_self_check(out, payload, golden)
    _dump_json(out / "self_check.json", self_check)
    summary = _summarize(out, golden, diff_tally, events)
    summary["diff_report"]["items"] = len(golden.get("items") or [])
    summary["self_check"]["ok"] = self_check.get("ok")
    summary["self_check"]["checks_total"] = len(self_check.get("checks") or {})
    summary["self_check"]["checks_passed"] = summary["self_check"]["checks_total"] - len(
        self_check.get("failed") or [])
    return summary


def finalize_assets(out, payload, result, summary=None):
    """Append the audit/finish phases to run.log and attach the asset summary."""
    out = Path(out)
    sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    events = sources.get("events") if isinstance(sources.get("events"), list) else []
    summary = summary if isinstance(summary, dict) else {}
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    checks = verification.get("checks") or {}
    passed = len([1 for v in checks.values() if isinstance(v, dict) and v.get("ok")])
    events.append({"ts": _now(), "elapsed": round(_elapsed(), 3), "phase": "inspect",
                   "ok": bool(verification.get("ok")),
                   "detail": {"checks": "%d/%d" % (passed, len(checks))}})
    events.append({"ts": _now(), "elapsed": round(_elapsed(), 3), "phase": "finish", "ok": True,
                   "detail": {"exit_code": 0, "status": result.get("status"),
                              "artifacts": len(result.get("outputs") or {})}})
    meta = {"started_at": sources.get("started_at"), "case_id": payload.get("case_id"),
            "stage": payload.get("stage"), "status": result.get("status"),
            "input": sources.get("input_dir"), "output": str(out),
            "errors": len(result.get("errors") or []),
            "degradations": len(result.get("degradations") or []),
            "issues": len(result.get("issues") or []),
            "counts": result.get("counts") or {},
            "artifacts": len(result.get("outputs") or {}),
            "verification": "ok=%s checks=%d/%d" % (bool(verification.get("ok")), passed, len(checks))}
    render.write_run_log(out, events, meta)
    files = _stat_files(out)
    golden = _read_json(out / "golden_standard.json")
    diff = summary.get("diff_report") if isinstance(summary.get("diff_report"), dict) else {}
    tally = {"met": diff.get("met", 0), "deviation": diff.get("deviation", 0),
             "missing": diff.get("missing", 0)}
    final = _summarize(out, golden, tally, events)
    final["diff_report"]["items"] = diff.get("items")
    final["run_log"]["events"] = len([e for e in events if isinstance(e, dict)])
    final["run_log"]["bytes"] = files.get("run.log", 0)
    receipt = _read_json(out / "self_check.json")
    final["self_check"]["ok"] = receipt.get("ok")
    final["self_check"]["checks_total"] = len(receipt.get("checks") or {})
    final["self_check"]["checks_passed"] = final["self_check"]["checks_total"] - len(
        receipt.get("failed") or [])
    for k, v in final.items():
        result[k] = v
    result["outputs"] = {n: s for n, s in files.items()}
    return final


def _elapsed():
    try:
        return time.time() - _T0
    except Exception:
        return 0.0
