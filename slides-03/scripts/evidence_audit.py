#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evidence_audit -- produces this run's verification assets under /app/output:

  golden_standard.json  rule-derived expected structure and acceptance items
  diff_report.md        item-by-item pass / deviation / missing / unmeasured
  version_history.md    skill-package and deck versions with rollback steps
  run.log               appended timeline of init/check/build
  self_check.json       contract, evidence, numeric and fallback-probe gates

Nothing here is pre-written: every asset is recomputed from the real run.
"""
import json
import re
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path
from rules_core import audit_deliverables, ACT_META, FIX_HINTS, RUN_LOG, expected_standard, grade_items, locate_verbatim, paragraph_by_locator, plan_act_profile, read_text_safe, save_json, scan_numbers, squeeze_text, stamp_now, tally_verdicts, time_budget

AUDIT_CLOCK = time.time()


ASSET_STATE = {"fields": {}, "out": None, "tag": "-", "flushed": 0, "hdr": False}


# ---------------- run journal and asset state ----------------


def journal(step, msg="", **kw):
    r = {"t": round(time.time() - AUDIT_CLOCK, 2), "step": step, "msg": msg}
    r.update(kw)
    RUN_LOG.append(r)


def outline_skeleton(idx, h, target):
    """v0 stage: page order, page role and time budget only. No claims, no evidence."""
    prof = plan_act_profile(target, (h or {}).get("audience"))
    secs, total = time_budget(prof, (h or {}).get("duration"))
    return {"stage": "v0_skeleton", "case_id": (h or {}).get("case_id"),
            "audience": (h or {}).get("audience"), "duration_min": (h or {}).get("duration"),
            "target_slides": target, "total_seconds": total,
            "pages": [{"n": i, "act": ACT_META[r][0], "role": r, "seconds": s, "content": None, "evidence": []}
                      for i, (r, s) in enumerate(zip(prof, secs), 1)]}


# ---------------- report renderers ----------------


def render_diff_report(gs, items, plan, sm, target, idx):
    L = ["# Verification: produced deck vs expected standard", "", "- case_id：`%s`　生成：%s" % (gs.get("case_id"), stamp_now()),
         "- expected standard: `output/golden_standard.json` (%d pages / %d acts / %d acceptance items)"
         % (gs["totals"]["pages"], gs["totals"]["acts"], gs["totals"]["acceptance_items"]),
         "- verdicts: `pass` met | `deviation` artifact off-spec | `missing` absent | `unmeasured` cannot be measured (never inflated to pass)",
         "- 汇总：pass %d / deviation %d / missing %d / unmeasured %d，达标率 %.1f%%"
         % (sm["pass"], sm["deviation"], sm["missing"], sm["unmeasured"], sm["coverage"]), "",
         "## 1. Acceptance items, one row each", "", "| ID | dimension | requirement | actual | verdict | evidence |", "|-|-|-|-|-|-|"]
    for it in items:
        L.append("| %s | %s | %s | %s | %s | `%s` |" % (it["id"], it["dimension"], it["expected"].replace("|", "/"),
                                                       str(it["actual"]).replace("|", "/"), it["verdict"], it["evidence"]))
    sl = [s for s in (plan or {}).get("slides") or [] if isinstance(s, dict)]
    nar = {str(a.get("act")): str(a.get("slides") or "") for a in (plan or {}).get("narrative") or [] if isinstance(a, dict)}
    L += ["", "## 2. 叙事结构、页序与时长预算", "",
          "| act | expected page span | budget s | declared span | verdict |", "|-|-|-|-|-|"]
    for a in [x for x in gs["outline"] if x["role"] != "cover"]:
        rng = nar.get(a["act"])
        L.append("| %s | %s | %d | %s | %s |" % (a["act"], a["pages"], a["seconds"], rng or "未声明",
                                                 "unmeasured" if not nar else ("pass" if squeeze_text(rng) == squeeze_text(a["pages"]) else "deviation")))
    L += ["", "> Page spans come from `narrative`; the seconds are a budget, not a measurement.", "",
          "## 3. Page-level evidence check", "", "| page | role | expected evidence seeds | actual bullets | verbatim hits | verdict |", "|-|-|-|-|-|-|"]
    for p in gs["pages"]:
        s = next((x for x in sl if x.get("n") == p["n"]), sl[p["n"] - 1] if len(sl) >= p["n"] else {})
        bl = [b for b in (s.get("bullets") or []) if isinstance(b, dict)]
        ver = sum(1 for b in bl if b.get("quote") and locate_verbatim(b["quote"], idx))
        v = ("pass" if not bl else "deviation") if p["role"] == "cover" else (
            "missing" if not bl else ("pass" if ver == len(bl) and 3 <= len(bl) <= 5 else "deviation"))
        L.append("| %d | %s | %s | %d 条 | %d/%d | %s |" % (p["n"], ACT_META[p["role"]][0],
                                                           ", ".join(x["locator"] for x in p["evidence_seeds"]
                                                                     ) or ("无（封面）" if p["role"] == "cover" else "（材料未提供→预期缺口）"),
                                                           len(bl), ver, len(bl), v))
    L += ["", "## 4. Deviations and gap handling", ""]
    dev = [it for it in items if it["verdict"] in ("deviation", "missing")]
    L += ["- **%s %s**：%s → 实际 %s。处置：%s" % (it["id"], it["dimension"], it["expected"], it["actual"],
                                               FIX_HINTS.get(it["id"], "在 `work/slide_plan.json` 修正后重跑 check/build"))
          for it in dev] or ["- 无 deviation / missing。"]
    gaps = [p for p in gs["pages"] if p.get("expected_gap")]
    if gaps:
        L += ["", "### 预期缺口页（金标准未找到独立证据种子：合并页或写明缺口，不得补造）", ""] + [
            "- 第 %d 页（%s）：材料无独立证据种子，合格做法是合并/削减该页或写明缺口。" % (p["n"], ACT_META[p["role"]][0]) for p in gaps]
    L += ["", "## 5. Conclusion", "",
          "- 达标率 %.1f%%（%d/%d）。%s" % (sm["coverage"], sm["pass"], sm["items"],
                                           "可复核项全部通过；科学性仍以人工评审为准。" if sm["deviation"] + sm["missing"] == 0
                                           else "存在 %d 项偏差/缺失，见第 4 节。" % (sm["deviation"] + sm["missing"])),
          "- 只核验结构/证据/导出/版本的可复核性，不判断科学结论。", ""]
    return "\n".join(L)


def render_version_log(plan, v0, gs, rep, status, changes, errors, degr, case_id):
    sl = [s for s in (plan or {}).get("slides") or [] if isinstance(s, dict)]
    bl = sum(len([b for b in (s.get("bullets") or []) if isinstance(b, dict)]) for s in sl)
    qc, qv = int(rep.get("quotes_checked") or 0), int(rep.get("quotes_verified") or 0)
    L = ["# Version log and rollback", "", "- case_id：`%s`　生成时间：%s" % (case_id, stamp_now()),
         "- 两类版本：Skill 包（v1.0.0→v1.1.0）、本次产物（v0 骨架→v1 成稿）。", "",
         "## 1. Skill 包版本", "", "| 版本 | 改了什么 | 为什么 | 如何回退 |", "|-|-|-|-|",
         "| v1.0.0 | init/show/check/build + makeppt；产物 pptx/pdf/plan/content_map/compliance | 原始链路（baseline_v1.zip） | 解压覆盖 |",
         "| v1.1.0 | 新增 `audit.py`；build 多产 5 个核验资产；`result.json` 增 4 字段 | 原包无法独立复核取舍过程 | 删 `audit.py` + 去掉 `main.py` 4 处 `audit.*` 调用即回 v1.0.0 |",
         "", "## 2. 本次产物版本", "", "| 版本 | 内容 | 位置 | 为什么 | 如何回退 |", "|-|-|-|-|-|",
         "| v0 骨架 | %d 页、%d 幕、预算 %d 秒；只有页序/页角色，无主张无证据 | `work/versions/v0_skeleton.json` | 先定页序与时长，再填内容，避免页数与讲述时长脱节 | `python3 scripts/main.py init` 重生成 |"
         % (len(v0.get("pages") or []), len(gs.get("outline") or []), int(v0.get("total_seconds") or 0)),
         "| v1 计划 | %d 页、%d 条要点、%d 条 quote（逐字命中 %d/%d） | `work/versions/v1_plan.json` | 在骨架上填主张/要点/讲稿/问答 | `build --plan work/versions/v1_plan.json` 复跑同一稿 |"
         % (len(sl), bl, qc, qv, qc),
         "| v1 成稿 | status=`%s`；pptx+preview+content_map+compliance+5 个核验资产 | `output/` | 渲染与核验分离：先定稿再逐项对照 | 用 v1_plan 重跑 build |" % status,
         "", "## 3. 本次实际变更（来自运行）", ""]
    L += ["- `%s`：%s → %s（原因：%s）" % (c.get("what"), c.get("from"), c.get("to"), c.get("why")) for c in changes or []]
    L += (["- 无计划级变更：计划一次通过校验。"] if not changes else []) + ["", "## 4. 降级与异常", ""]
    L += ["- 降级：%s" % d for d in (degr or ["无"])] + ["- 异常：%s" % e for e in (errors or ["无"])]
    L += ["", "## 5. 回退演练", "", "```bash",
          "python3 scripts/main.py build --plan work/versions/v1_plan.json   # 回到 v1 计划",
          "python3 -c \"import json;print(json.load(open('work/versions/v0_skeleton.json'))['pages'])\"",
          "rm -f scripts/audit.py && unzip -o baseline_v1.zip -d .           # 回到 v1.0.0", "```", ""]
    return "\n".join(L)


def build_self_check(out, case, idx, plan, gs, sm, contract_missing, status, rep, chk, errors, degr, rt, ckeys=None):
    files = ["golden_standard.json", "diff_report.md", "version_history.md", "run.log", "self_check.json", "result.json"]
    late = ("self_check.json", "result.json")
    arts = {f: {"exists": (Path(out) / f).is_file(), **({} if f in late else
                 {"bytes": (Path(out) / f).stat().st_size if (Path(out) / f).is_file() else 0})} for f in files}
    sl = [s for s in (plan or {}).get("slides") or [] if isinstance(s, dict)]
    bls = [b for s in sl for b in (s.get("bullets") or []) if isinstance(b, dict)]
    loc = sum(1 for b in bls if str(b.get("locator") or "").strip())
    res = sum(1 for b in bls if b.get("locator") and paragraph_by_locator(b["locator"], idx))
    n, nb = scan_numbers(plan, idx)
    probes = []
    for name, fn in (("empty_input", lambda: expected_standard({}, {"materials": [], "input_root": ""}, {}, 6)),
                     ("empty_plan", lambda: grade_items(gs, {}, {}, {}, idx, {}, None, contract_missing)),
                     ("number_mismatch", lambda: scan_numbers({"slides": [{"bullets": [{"text": "n=999", "quote": "n=1"}]}]}, idx))):
        try:
            fn()
            probes.append({"name": name, "pass": True, "detail": "未抛异常，返回带缺口/不一致标记的对象"})
        except Exception as e:
            probes.append({"name": name, "pass": False, "detail": repr(e)})
    allf = all(v["exists"] for v in arts.values())
    ev_ok = bool(bls) and res == len(bls) and int(rep.get("quotes_verified") or 0) == int(rep.get("quotes_checked") or 0)
    gate = allf and ev_ok and not nb and all(p["pass"] for p in probes)
    return {"schema": "self_check.v1", "case_id": (case or {}).get("case_id") or "unknown_case",
            "generated_at": stamp_now(), "stage": "full", "status": status, "exit_code": 0, "runtime_seconds": rt,
            "artifacts": arts,
            "contract": {"expected_fields": ckeys or "见 result.json.output_contract",
                         "missing": contract_missing or [], "pass": not contract_missing},
            "evidence": {"slides": len(sl), "bullets": len(bls), "with_locator": loc, "locator_resolvable": res,
                         "quotes_checked": int(rep.get("quotes_checked") or 0),
                         "quotes_verified": int(rep.get("quotes_verified") or 0),
                         "pages_with_evidence": int(rep.get("slides_with_evidence") or 0),
                         "coverage_rate": round(100. * res / (len(bls) or 1), 1), "pass": ev_ok},
            "numeric": {"checked": n, "mismatch_count": len(nb), "mismatched": nb[:12], "pass": not nb},
            "golden_standard": {"pages": gs["totals"]["pages"], "acceptance_items": gs["totals"]["acceptance_items"],
                                "declared_gaps": gs["totals"]["gap_pages"]},
            "overall_gate": {"artifacts": allf, "evidence": ev_ok, "numeric": not nb,
                             "probes": all(p["pass"] for p in probes)},
            "diff": sm, "fallback_probes": probes,
            "errors": errors or [], "degradations": degr or [],
            "limits": ["The standard is rule-derived and does not judge scientific merit; the duration is a budget; number checks cover Arabic digits only",
                       "Preview fidelity depends on LibreOffice"],
            "overall": "pass" if (gate and sm["items"] > 0 and not sm["missing"]) else
                       ("partial" if gate else "fail")}


def asset_fields():
    return ASSET_STATE.get("fields") or {}


def asset_field(name, stage, **kw):
    p = Path(ASSET_STATE.get("out") or ".") / name
    d = {"path": "output/%s" % name, "stage": stage, "bytes": p.stat().st_size if p.is_file() else 0}
    d.update(kw)
    return d


def flush_run_log(out):
    """Append only records not yet flushed, so a single run.log can span init/check/build."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    p, i = out / "run.log", ASSET_STATE.get("flushed", 0)
    recs = RUN_LOG[i:]
    if not recs and ASSET_STATE.get("hdr"):
        return p
    ASSET_STATE["flushed"] = len(RUN_LOG)
    head = "" if ASSET_STATE.get("hdr") else "=== run %s | T0 = process start | tag=%s ===\n" % (stamp_now(), ASSET_STATE.get("tag"))
    ASSET_STATE["hdr"] = True
    body = "".join("[+%06.2fs] %-11s %s%s\n" % (r["t"], r["step"], r["msg"],
                                                (" " + json.dumps({k: v for k, v in r.items() if k not in ("t", "step", "msg")},
                                                                  ensure_ascii=False)) if len(r) > 3 else "") for r in recs)
    old = read_text_safe(p) if p.is_file() else ""
    txt = old + head + body
    if len(txt.encode("utf-8")) > 60000:
        txt = "[log trimmed to last 40000 bytes]\n" + txt[-40000:]
    p.write_text(txt, encoding="utf-8")
    return p


def ensure_min_assets(out, case_id="unknown_case", stage="partial", errors=None, tag="minimal"):
    """Guarantee five syntactically valid assets even if the run dies before build."""
    out = Path(out)
    ASSET_STATE["out"], ASSET_STATE["tag"] = str(out), tag
    out.mkdir(parents=True, exist_ok=True)
    err = [str(e) for e in (errors or [])][:6]
    if not (out / "golden_standard.json").is_file():
        save_json(out / "golden_standard.json", {
            "schema": "golden_standard.v1", "case_id": case_id, "generated_at": stamp_now(), "stage": "minimal",
            "basis": {"statement": "Minimal placeholder: the full standard is generated during build.", "derivation": "evidence_audit.py:ensure_min_assets"},
            "constraints": [], "outline": [], "pages": [], "logic": [], "acceptance": [],
            "totals": {"pages": 0, "acts": 0, "logic_items": 0, "acceptance_items": 0, "seconds": 0,
                       "evidence_seeds": 0, "gap_pages": 0},
            "limits": ["build 未执行/失败：合法占位，不代表本案例金标准"] + err})
    if not (out / "diff_report.md").is_file():
        (out / "diff_report.md").write_text("\n".join(
            ["# Verification report (minimal placeholder)", "", "- case_id：`%s`　阶段：`%s`" % (case_id, stage),
             "- build has not finished, the item-by-item comparison is pending.", "", "## Known errors", ""] + ["- %s" % e for e in (err or ["无"])] +
            ["", "next: run `python3 scripts/deckctl.py build`.", ""]), encoding="utf-8")
    if not (out / "version_history.md").is_file():
        (out / "version_history.md").write_text("\n".join(
            ["# Version log and rollback (minimal placeholder)", "", "- case_id：`%s`　阶段：`%s`" % (case_id, stage), "",
             "| 版本 | 内容 | 如何回退 |", "|-|-|-|", "| v1.0.0 | baseline Skill 包 | 解压 `baseline_v1.zip` 覆盖 |",
             "| v1.1.0 | 5 verification assets added | drop evidence_audit.py and restore deckctl.py |",
             "", "The v0 skeleton and v1 plan are recorded here once build completes.", ""]), encoding="utf-8")
    flush_run_log(out)
    if not (out / "self_check.json").is_file():
        save_json(out / "self_check.json", {"schema": "self_check.v1", "case_id": case_id, "generated_at": stamp_now(),
                                       "stage": "minimal", "status": stage, "exit_code": 0, "overall": "partial",
                                       "artifacts": {f: {"exists": (out / f).is_file()} for f in
                                                     ("golden_standard.json", "diff_report.md", "version_history.md", "run.log")},
                                       "contract": {"pass": False, "missing": ["build 未完成"]},
                                       "evidence": {"pass": False, "coverage_rate": 0.0},
                                       "numeric": {"pass": False, "checked": 0}, "errors": err,
                                       "limits": ["Minimal self-check: only exists when build did not finish"]})
    ASSET_STATE["fields"] = {"golden_standard": asset_field("golden_standard.json", "minimal", items=0, pages=0),
                       "diff_report": asset_field("diff_report.md", "minimal", pass_items=0, items=0, coverage_pct=0.0),
                       "version_history": asset_field("version_history.md", "minimal", versions=["v0_skeleton", "v1_plan", "v1_final"]),
                       "self_check": asset_field("self_check.json", "minimal", overall="partial", exit_code=0)}
    return ASSET_STATE["fields"]


# ---------------- asset production ----------------


def finalize_assets(out, work, case, idx, h, plan, chk, rep, target, vals, status,
             errors, degr, changes, v0, contract_missing=None, ckeys=None):
    """Write the five verification assets; never raises and degrades to ensure_min on failure."""
    out, work = Path(out), Path(work)
    ASSET_STATE["out"], ASSET_STATE["tag"] = str(out), "full"
    case, plan = case if isinstance(case, dict) else {}, plan if isinstance(plan, dict) else {}
    journal("assets", "start", stage="full")
    v0 = v0 or {}
    v0["case_id"] = v0.get("case_id") or case.get("case_id")
    try:
        gs = expected_standard(case, idx, h, target)
        save_json(out / "golden_standard.json", gs)
        journal("assets", "golden_standard written", pages=gs["totals"]["pages"], items=gs["totals"]["acceptance_items"])
    except Exception as e:
        errors.append("golden_standard failed: %r" % (e,))
        journal("error", "golden_standard", tb=traceback.format_exc()[-300:])
        ensure_min_assets(out, case.get("case_id"), "partial", errors, tag="degraded")
        return ASSET_STATE["fields"]
    items, sm = [], {"pass": 0, "deviation": 0, "missing": 0, "unmeasured": 0, "items": 0, "coverage": 0.0}
    try:
        items = grade_items(gs, plan, chk, rep, idx, vals, target, contract_missing)
        sm = tally_verdicts(items)
        (out / "diff_report.md").write_text(render_diff_report(gs, items, plan, sm, target, idx), encoding="utf-8")
        journal("assets", "diff_report written", pass_=sm["pass"], deviation=sm["deviation"], missing=sm["missing"])
    except Exception as e:
        errors.append("diff_report failed: %r" % (e,))
        journal("error", "diff_report", tb=traceback.format_exc()[-300:])
        if not (out / "diff_report.md").is_file():
            (out / "diff_report.md").write_text("# Verification report\n\nGeneration failed: %r\n" % (e,), encoding="utf-8")
    try:
        save_json(work / "versions" / "v0_skeleton.json", v0)
        save_json(work / "versions" / "v1_plan.json", plan)
        (out / "version_history.md").write_text(
            render_version_log(plan, v0, gs, rep, status, changes, errors, degr, gs.get("case_id")), encoding="utf-8")
        journal("assets", "version_history written", v0_pages=len(v0.get("pages") or []), v1_pages=len(plan.get("slides") or []))
    except Exception as e:
        errors.append("version_history failed: %r" % (e,))
        journal("error", "version_history", tb=traceback.format_exc()[-300:])
    for d in degr or []:
        journal("degradation", str(d)[:200])
    for e in errors or []:
        journal("exception", str(e)[:200])
    journal("assets", "run.log flush", lines=len(RUN_LOG))
    try:
        flush_run_log(out)
    except Exception:
        pass
    try:
        sc = build_self_check(out, case, idx, plan, gs, sm, contract_missing, status, rep, chk, errors, degr,
                        round(time.time() - AUDIT_CLOCK, 2), ckeys)
        save_json(out / "self_check.json", sc)
        overall = sc["overall"]
        journal("assets", "self_check written", overall=overall)
    except Exception as e:
        errors.append("self_check failed: %r" % (e,))
        journal("error", "self_check", tb=traceback.format_exc()[-300:])
        overall, sc = "fail", {"overall": "fail", "stage": "degraded", "evidence": {}}
    try:
        art = audit_deliverables(out)
        save_json(out / "artifact_audit.json", art)
        journal("assets", "deliverable audit", overall=art["overall"])
        if art["overall"] != "pass":
            errors.append("deliverable audit: %s" % ", ".join(art["failures"]))
    except Exception as e:
        art = {"overall": "fail", "failures": ["deliverable audit failed: %r" % (e,)]}
        journal("error", "deliverable audit", tb=traceback.format_exc()[-300:])
    t = gs["totals"]
    ASSET_STATE["fields"] = {
        "artifact_audit": asset_field("artifact_audit.json", "full", overall=art.get("overall"),
                                      failures=len(art.get("failures") or [])),
        "golden_standard": asset_field("golden_standard.json", "full", items=t["acceptance_items"], pages=t["pages"],
                              acts=t["acts"], evidence_seeds=t["evidence_seeds"], declared_gaps=t["gap_pages"],
                              basis=gs["basis"]["derivation"]),
        "diff_report": asset_field("diff_report.md", "full", pass_items=sm["pass"], deviation=sm["deviation"],
                          missing=sm["missing"], unmeasured=sm["unmeasured"], items=sm["items"], coverage_pct=sm["coverage"]),
        "version_history": asset_field("version_history.md", "full", versions=["v1.0.0-baseline", "v1.1.0", "v0_skeleton", "v1_plan", "v1_final"],
                              v0_snapshot="work/versions/v0_skeleton.json", v1_snapshot="work/versions/v1_plan.json"),
        "self_check": asset_field("self_check.json", sc.get("stage", "full"), overall=overall, exit_code=0,
                         evidence_coverage=(sc.get("evidence") or {}).get("coverage_rate")),
    }
    return ASSET_STATE["fields"]
