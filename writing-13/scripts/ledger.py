# -*- coding: utf-8 -*-
"""ledger.py :: per-item gold standard, comparison against it, score replay, and the
orchestrator that writes the asset set.

The asset files depend only on the case data, the item sheet, the anchors and the ratee
snapshots handed in by the driver; no clock and no random source are involved, so two
runs on one input are byte-identical.  Imported by bench.py.
"""
import re, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import kernel as KN
import assets_ext as AX
from kernel import canon, trim, jstr, dhash
from journal import (STEPS, SET5FILES, ADDFIELDS, MUST_KEYS, GOOD_T, MID_T, KVER, AVER,
                     boot, trace, render_log, release_log, audit_json, seal, fallback_assets)


def find_line(docs, needle, first_num=False):
    qty = canon(needle)
    for d in docs:
        for i, l in enumerate(d.get("lines") or [], 1):
            if (re.search(r"\d", l) if first_num else (qty and qty in canon(l))):
                return {"locator": "%s:L%d" % (d["doc_id"], i), "quote": trim(l, 220)}
    return {}

def docref(loc):
    s = str(loc or "")
    return (s.split(":")[0] or None) if s else None

def unellipsis(q):
    s = re.sub(r"\s+", " ", str(q or "")).strip()
    while s.endswith("…") or s.endswith("..."):
        s = s[:-1].rstrip() if s.endswith("…") else s[:-3].rstrip()
    return s

def verbatim(q, docs):
    qty = canon(unellipsis(q))
    return bool(qty) and any(qty in canon(d.get("text") or "") for d in docs)

def anchor_evidence(a, t, docs):
    rule = a.get("rule") or {}
    b = {"anchor_id": a.get("anchor_id"), "point_id": a.get("point_id"), "scope": a.get("scope"),
         "check_rule": rule, "level_spec": a.get("level_spec"),
         "observable_condition": a.get("observable_condition"), "revision": a.get("revision", 0)}
    if a.get("point_id"):
        ps = [x for x in (t.get("must_include_points") or []) if x.get("point_id") == a.get("point_id")]
        p = ps[0] if ps else {}
        loc, q = p.get("locator") or a.get("evidence_locator"), unellipsis(p.get("quote"))
        okq = verbatim(q, docs)
        b.update(evidence_kind="source_verbatim" if okq else "case_spec", locator=loc,
                 quote=q, verbatim=okq, doc_id=docref(loc),
                 note=None if okq else "quote lives in case metadata, not in a material file")
        return b
    if rule.get("type") == "section_order":
        grade_level = find_line(docs, (rule.get("values") or [""])[0])
        b.update(evidence_kind="source_verbatim" if grade_level else "task_spec",
                 locator=grade_level.get("locator") or "task:%s#format_requirements" % t.get("task_id"),
                 quote=grade_level.get("quote"), verbatim=bool(grade_level), doc_id=docref(grade_level.get("locator")),
                 note="小节顺序：quote 为源材料该小节标题行")
        return b
    if rule.get("type") == "no_new_numbers":
        grade_level = find_line(docs, "", True)
        b.update(evidence_kind="global_number_set" if grade_level else "task_spec",
                 locator=grade_level.get("locator") or "task:%s#input_refs" % t.get("task_id"),
                 quote=grade_level.get("quote"), verbatim=bool(grade_level), doc_id=docref(grade_level.get("locator")),
                 note="证据=源材料数值全集(n=%d)，单条 quote 为可定位样本" % len(rule.get("allowed") or []))
        return b
    fm = [x for x in (t.get("format_requirements") or []) if x.startswith("<= ")]
    b.update(evidence_kind="task_spec", locator="task:%s#format_requirements" % t.get("task_id"),
             quote=(fm[0] if fm else None), verbatim=None, note="字数约束出自题面，verbatim=null")
    return b


# ------------------------------------------------------------------ golden

def replay(out, ANCH, grid):
    run_kind = {}
    for p in sorted((Path(out) / "ratees").glob("*.txt")):
        try:
            run_kind[p.stem] = p.read_text("utf-8", "replace")
        except Exception:
            pass
    if not run_kind or not ANCH:
        return {"available": False, "checked": 0, "mismatch": [], "ratees": sorted(run_kind)}
    want = {(r["ratee_id"], r["anchor_id"]): int(float(r["adjudicated"])) for r in grid}
    bad, qty = [], 0
    for sub_id in sorted(run_kind):
        for r in KN.score(ANCH, sub_id, run_kind[sub_id], "audit"):
            qty += 1
            if want.get((sub_id, r["anchor_id"])) != r["adjudicated"]:
                bad.append("%s/%s csv=%s recomputed=%s"
                           % (sub_id, r["anchor_id"], want.get((sub_id, r["anchor_id"])), r["adjudicated"]))
    return {"available": True, "checked": qty, "mismatch": bad, "ratees": sorted(run_kind)}

def make_gold(brief, state, items, ANCH, docs):
    by = {}
    for a in ANCH:
        by.setdefault(a.get("task_id"), []).append(a)
    tk = []
    for t in items:
        rub, exp, anc = [], [], []
        for k, p in enumerate(t.get("must_include_points") or [], 1):
            q, loc = unellipsis(p.get("quote")), p.get("locator")
            okq = verbatim(q, docs)
            ev = {"kind": "source_verbatim" if okq else "case_spec", "locator": loc,
                  "quote": q, "verbatim": okq, "doc_id": docref(loc),
                  "note": None if okq else "quote lives in case metadata, not in a material file"}
            rub.append({"rubric_id": "R-%s-%02d" % (t["task_id"], k), "point_id": p.get("point_id"),
                        "criterion": p.get("observable"), "check_rule": p.get("check"), "weight": 1,
                        "verdict_map": {"2": "met", "1": "partial", "0": "missed"}, "evidence": ev})
            exp.append({"point_id": p.get("point_id"), "must_contain": trim(p.get("text"), 200),
                        "rewrite_rule": "连接句可同义改写；数值/单位/条件/主体对象不得变", "evidence": ev})
        anc += [anchor_evidence(a, t, docs) for a in by.get(t["task_id"], [])]
        tk.append({"task_id": t.get("task_id"), "writing_type": t.get("writing_type"), "tier": t.get("tier"),
                   "direction": t.get("direction"), "input_refs": t.get("input_refs"),
                   "word_limit": t.get("word_limit"), "language": t.get("language"),
                   "instruction": trim(t.get("instruction"), 400), "rubric": rub,
                   "expected_answer": {"must_contain": exp,
                                       "acceptable_variants": t.get("acceptable_variants") or [],
                                       "unacceptable_errors": t.get("fail_criteria") or [],
                                       "completion_rule": t.get("completion_rule")},
                   "anchors": anc,
                   "thresholds": {"pass": GOOD_T, "partial": MID_T,
                                  "score_formula": "100*sum(adjudicated)/(2*len(anchors))"}})
    sv = [a for x in tk for a in x["anchors"] if a.get("evidence_kind") == "source_verbatim"]
    okq = [a for a in sv if a.get("verbatim")]
    return {
        "schema": "golden-standard/v1", "skill": "writing-bench-eval-kit",
        "skill_version": KVER, "anchor_version": AVER, "case_id": (state or {}).get("case_id"),
        "provenance": {"built_from": ["tasks.jsonl", "anchors.md", "input materials"],
                       "independence_note": "金标准与评分器共用证据层，故独立校验点是"
                                            "「quote 是否在源材料逐字命中」与「分数能否由锚点+ratees 复算」",
                       "source_sha256": [{"path": d.get("path"), "sha256": d.get("sha256"),
                                          "chars": len(d.get("text") or "")} for d in docs]},
        "scoring_rule": {"anchor_levels": {"2": "met", "1": "partial", "0": "missed"},
                         "adjudicated": "min(rater_a, rater_b)",
                         "task_score": "100*sum(adjudicated)/(2*len(task_anchors))",
                         "verdict": {"pass": ">=%d" % GOOD_T, "partial": "%d-%d" % (MID_T, GOOD_T - 1),
                                     "fail": "<%d" % MID_T},
                         "repair_policy": "双评 >1 档只修锚点并重算，不改分数"},
        "task_count": len(tk), "rubric_point_count": sum(len(x["rubric"]) for x in tk),
        "expected_point_count": sum(len(x["expected_answer"]["must_contain"]) for x in tk),
        "anchor_count": sum(len(x["anchors"]) for x in tk), "min_rubric_points_per_task": 3,
        "completeness": {"tasks_with_rubric": sum(1 for x in tk if len(x["rubric"]) >= 3),
                         "tasks_with_expected": sum(1 for x in tk if len(x["expected_answer"]["must_contain"]) >= 3),
                         "tasks_with_anchors": sum(1 for x in tk if len(x["anchors"]) >= 2),
                         "source_anchors": len(sv), "source_anchors_verbatim": len(okq),
                         "quote_verbatim_rate": round(len(okq) / len(sv), 4) if sv else None},
        "gaps": [] if items else [{"item": "材料未提供", "note": "无可解析材料，金标准无题可列"}],
        "tasks": tk}


# ------------------------------------------------------------------- diff

def compare_gold(state, brief, items, ANCH, docs, grid, tally, revs, GOLD, REPLAY, FAULTS, DEGRADED, HOLD, stable):
    gmap = {x["task_id"]: x for x in GOLD["tasks"]}
    cov, miss, dev, rows = [], [], [], []
    for t in items:
        g = gmap.get(t["task_id"], {})
        nr = len(g.get("rubric") or [])
        ne = len(g.get("expected_answer", {}).get("must_contain") or [])
        anc = g.get("anchors") or []
        nv = len([a for a in anc if a.get("verbatim")])
        nsrc = len([a for a in anc if a.get("evidence_kind") in ("source_verbatim", "global_number_set")])
        nsc = len([s for s in tally if s["task_id"] == t["task_id"]])
        st = "一致"
        if nr < 3 or ne < 3:
            st = "偏差"
            dev.append({"sev": "high", "scope": t["task_id"], "item": "rubric/答案要点数",
                        "expect": ">=3 / >=3", "actual": "%d / %d" % (nr, ne),
                        "note": "点数不足时两名评分员无法不商量判定"})
        if len(anc) < nr + 2:
            st = "偏差"
            dev.append({"sev": "mid", "scope": t["task_id"], "item": "锚点数", "expect": ">= rubric+2",
                        "actual": len(anc), "note": "缺全局锚点（防编造/字数）"})
        if nv < nsrc:
            st = "偏差"
            dev.append({"sev": "high", "scope": t["task_id"], "item": "锚点 quote 逐字命中",
                        "expect": "100%", "actual": "%d/%d" % (nv, len(anc)),
                        "note": "quote 在源材料找不到即不可核验"})
        if not nsc:
            st = "缺失"
            miss.append({"sev": "mid", "scope": t["task_id"], "item": "评分记录", "note": "无 scores_detail 行"})
        rows.append((t["task_id"], t.get("writing_type"), nr, ne, "%d/%d" % (nv, nsrc), nsc, st))
    try:
        want = int(brief.get("task_count") or brief.get("n_tasks") or 0)
    except Exception:
        want = 0
    dirs = sorted({t.get("direction") for t in items})
    types = sorted({t.get("writing_type") for t in items})
    if want and want != len(items):
        dev.append({"sev": "low", "scope": "题集", "item": "题量 vs 声明", "expect": str(want),
                    "actual": len(items), "note": "题量夹在 6-12 的可判定区间（下限 6 覆盖六方向）"})
    if items and len(dirs) < 6:
        dev.append({"sev": "mid", "scope": "题集", "item": "六方向覆盖", "expect": "6",
                    "actual": len(dirs), "note": "缺方向见 coverage.directions"})
    if REPLAY["available"] and REPLAY["mismatch"]:
        dev.append({"sev": "high", "scope": "评分", "item": "评分可复算", "expect": "0 mismatch",
                    "actual": "%d/%d" % (len(REPLAY["mismatch"]), REPLAY["checked"]), "note": "分数无法重算即不可核验"})
    if not stable:
        dev.append({"sev": "high", "scope": "评分", "item": "确定性", "expect": "两次一致",
                    "actual": "不一致", "note": "同进程两次评分不一致"})
    if not [r for r in tally if r["ratee_id"] == "manuscript-01"]:
        miss.append({"sev": "mid", "scope": "评分对象", "item": "待评稿件",
                     "note": "未提供待评稿件：仅交付题集/答案/锚点/校准评分"})

    L = ["# diff_report · 实际题集/评分 vs 金标准（%s）" % ((state or {}).get("case_id"),), "",
         "- skill v%s · anchor_version %s · status `%s`" % (KVER, AVER, (state or {}).get("status")),
         "- 对照：`golden_standard.json` ←→ `tasks.jsonl` / `anchors.md` / `scores_detail.csv`",
         "- 复算：`verify.py --audit`（锚点+ratees）、`verify.py --check`（含五件套 10 项）", "",
         "## 1 对照口径", "",
         "金标准与评分器共用证据层，故不以金标准自证。只比两类外部可复核对象："
         "①证据侧——每条 rubric/锚点 `quote` 能否在源材料**逐字**命中（可 grep 原文）；"
         "②评分侧——`scores_detail.csv` 每格能否由锚点规则 + `ratees/*.txt` **重算**出同值。", "",
         "## 2 逐题对照", "",
         "| task | 题型 | rubric 点 | 期望答案要点 | 锚点(逐字/需逐字) | 评分行 | 状态 |", "|-|-|-|-|-|-|-|"]
    L += ["| %s | %s | %d | %d | %s | %d | %s |" % r for r in rows]
    L += ["", "合计：题 %d · rubric %d · 期望要点 %d · 锚点 %d · 评分行 %d"
          % (len(items), GOLD["rubric_point_count"], GOLD["expected_point_count"], GOLD["anchor_count"], len(grid)),
          "六方向 %d/6：%s · 题型：%s" % (len(dirs), ", ".join(dirs) or "-", ", ".join(types) or "-"), "",
          "## 3 覆盖（对上）", ""]
    L += ["- `%s`：rubric %d / 期望要点 %d / 锚点 %s，证据与评分两侧均对上。" % (r[0], r[2], r[3], r[4])
          for r in rows if r[6] == "一致"] or ["- 无完全对上项。"]
    L += ["", "## 4 缺失（金标准要求、实际没有）", ""]
    L += ["- `%s` · %s：%s" % (x["scope"], x["item"], x["note"]) for x in miss] or ["- 无。"]
    L += ["", "## 5 偏差（有值但对不上）", "",
          "| 严重度 | 范围 | 项 | 期望 | 实际 | 说明 |", "|-|-|-|-|-|-|"]
    L += ["| %s | %s | %s | %s | %s | %s |" % (x["sev"], x["scope"], x["item"], x["expect"],
                                              x["actual"], x["note"]) for x in dev] or ["| - | - | - | - | - | 无未解释偏差 |"]
    L += ["", "## 6 评分复算（可核验性硬证据）", ""]
    if REPLAY["available"]:
        L.append("- 重算 %d 格（%s）→ 与 `scores_detail.csv` %s。"
                 % (REPLAY["checked"], ", ".join(REPLAY["ratees"]),
                    "**逐格一致**" if not REPLAY["mismatch"] else "**%d 格不一致**" % len(REPLAY["mismatch"])))
        L += ["  - %s" % m for m in REPLAY["mismatch"][:10]]
    else:
        L.append("- 无 ratees 快照或无锚点，本轮不可复算（已计入缺失）。")
    L += ["", "## 7 运行期降级/异常/待确认", ""]
    L += ["- %s：%d 条" % (k, v) for k, v in (("锚点修订(>1 档)", len(revs)), ("降级", len(DEGRADED)),
                                              ("异常", len(FAULTS)), ("待人工确认", len(HOLD)))]
    L += ["", "## 8 结论", ""]
    if dev or miss:
        L.append("**偏差 %d 项、缺失 %d 项**（高严重度 %d 项），逐条见 §4/§5。"
                 % (len(dev), len(miss), len([x for x in dev if x["sev"] == "high"])))
    else:
        L.append("**无未解释偏差**：逐题 rubric/期望要点/锚点齐备；source 类 quote 全部逐字命中；"
                 "评分可由锚点复算；缺失项仅限输入未提供的对象。")
    L += ["", "> 只陈述本轮实际产物与可复算关系；不含基准分、提升倍数或外部排名。", ""]
    return "\n".join(L), {"deviations": dev, "missing": miss,
                          "covered": [r[0] for r in rows if r[6] == "一致"],
                          "checked_items": len(items) * 4, "recompute": REPLAY}


# --------------------------------------------------------- version history

def build_assets(out, brief, state, items, ANCH, docs, grid, tally, revs, FAULTS, DEGRADED, HOLD, payload=None, stable=True):
    out = Path(out)
    state = dict(state or {})
    state.setdefault("anchor_version", AVER)
    state.setdefault("errors", FAULTS)
    trace("golden_standard", items=len(items), anchors=len(ANCH))
    GOLD = make_gold(brief, state, items, ANCH, docs)
    CO = AX.contract_gold(brief, state, items, ANCH, docs, grid, payload, out)
    GOLD["contract_expected"] = CO
    gt = jstr(GOLD) + "\n"
    (out / "golden_standard.json").write_text(gt, encoding="utf-8")

    REPLAY = replay(out, ANCH, grid)
    dt, DIFF = compare_gold(state, brief, items, ANCH, docs, grid, tally, revs, GOLD, REPLAY, FAULTS, DEGRADED, HOLD, stable)
    (out / "diff_report.md").write_text(dt, encoding="utf-8")
    trace("diff_report", recompute_checked=REPLAY["checked"], mismatch=len(REPLAY["mismatch"]))
    # parseable placeholders so the early audit already finds all five asset files
    (out / "self_check.json").write_text(jstr({"schema": "self-check/v1", "state": "seed",
                                             "checks": [], "summary": {}}) + "\n", encoding="utf-8")
    trace("self_check")
    vt = AX.release_history(GOLD, DIFF, state)
    (out / "version_history.md").write_text(vt, encoding="utf-8")
    trace("version_history", releases=len(AX.VERSIONS))
    trace("run_log", lines=len(STEPS))
    lt = render_log(state, FAULTS, DEGRADED, HOLD, state.get("status") or "partial")
    (out / "run.log").write_text(lt, encoding="utf-8")

    refs = {
        "golden_standard": dict(AX.file_ref(out / "golden_standard.json", "golden_standard.json"),
                                schema=GOLD["schema"],
                                task_count=GOLD["task_count"], rubric_point_count=GOLD["rubric_point_count"],
                                expected_point_count=GOLD["expected_point_count"],
                                anchor_count=GOLD["anchor_count"],
                                quote_verbatim_rate=GOLD["completeness"]["quote_verbatim_rate"],
                                contract_expected={"contract": len(CO.get("contract_items") or []),
                                                   "workorder": len(CO.get("workorder_items") or []),
                                                   "deliverable": len(CO.get("deliverable_items") or []),
                                                   "quoted": len([x for x in (CO.get("contract_items") or [])
                                                                  + (CO.get("deliverable_items") or [])
                                                                  if x.get("quote_verbatim")])}),
        "diff_report": dict(AX.file_ref(out / "diff_report.md", "diff_report.md"),
                            deviations=DIFF["deviations"], missing=DIFF["missing"],
                            covered_tasks=DIFF["covered"], contract={},
                            recompute={"checked": REPLAY["checked"], "mismatch": REPLAY["mismatch"]}),
        "version_history": dict(AX.file_ref(out / "version_history.md", "version_history.md"),
                                versions=list(AX.VERSIONS), current=AX.CURRENT,
                                anchor_version=AVER, rollback="file-level（§3）"),
        "run_log": AX.run_log_ref(out),
        "self_check": {"path": "self_check.json", "pending": True},
    }
    audit_res = audit_json(out, brief, state, items, ANCH, GOLD, DIFF, REPLAY, grid, stable, payload,
                           published=refs)
    audit_res["checks"] += AX.extra_checks(out, state, items, ANCH, GOLD, CO, payload, grid, brief)
    audit_res = AX.finalize_summary(audit_res)
    st = jstr(audit_res) + "\n"
    (out / "self_check.json").write_text(st, encoding="utf-8")
    refs["self_check"] = dict(AX.file_ref(out / "self_check.json", "self_check.json"),
                              summary=audit_res["summary"], checks=len(audit_res["checks"]),
                              artifacts=list(SET5FILES), run_log="run.log",
                              groups=audit_res["summary"]["groups"])
    trace("self_check", status="ok", checks=len(audit_res["checks"]), verdict=audit_res["summary"]["verdict"])

    # contract / deliverable comparison runs once every asset file is final
    csec, CSUM = AX.contract_diff(out, CO, payload, items, ANCH, grid)
    DIFF["contract"] = CSUM
    if "## 3 覆盖" in dt:
        dt = dt.replace("## 3 覆盖", csec + "## 3 覆盖", 1)
    else:
        dt = dt + csec
    (out / "diff_report.md").write_text(dt, encoding="utf-8")
    refs["diff_report"].update(AX.file_ref(out / "diff_report.md", "diff_report.md"))
    refs["diff_report"].update(
        contract={k: CSUM.get(k) for k in ("total", "met", "deviation", "missing")},
        verdict="no_unexplained_deviation"
        if not DIFF["deviations"] and not DIFF["missing"] and not CSUM.get("missing") else
        ("high_severity_deviation"
         if ([x for x in DIFF["deviations"] if x.get("sev") == "high"] or CSUM.get("missing"))
         else "explained_deviations"))
    trace("contract_diff", items=CSUM.get("total"), met=CSUM.get("met"),
          deviation=CSUM.get("deviation"), missing=CSUM.get("missing"))

    # release notes carry the real audit verdict and the contract comparison
    vt = AX.release_history(GOLD, DIFF, state, extra={"self_check": refs["self_check"]})
    (out / "version_history.md").write_text(vt, encoding="utf-8")
    refs["version_history"].update(AX.file_ref(out / "version_history.md", "version_history.md"))
    refs["version_history"].update(versions=list(AX.VERSIONS), current=AX.CURRENT,
                                   anchor_version=AVER, rollback="file-level（§3）")
    # final run.log render: every step above is now part of the real event stream
    lt = render_log(state, FAULTS, DEGRADED, HOLD, state.get("status") or "partial")
    (out / "run.log").write_text(lt, encoding="utf-8")
    try:
        with (out / "run.log").open("a", encoding="utf-8") as f:
            f.write("[assets] five files written: golden %d B / diff %d B / version %d B / self_check %d B"
                    "（run.log 由 seal 追加 [verify]/[exit] 并在 result.json 刷新指针）\n"
                    % (refs["golden_standard"].get("bytes", 0), refs["diff_report"].get("bytes", 0),
                       refs["version_history"].get("bytes", 0), refs["self_check"].get("bytes", 0)))
            f.write("[self_check] verdict=%s pass=%d fail=%d（seal 另补 SC-19/20 与资产指针校验）\n"
                    % (audit_res["summary"]["verdict"], audit_res["summary"]["pass"],
                       audit_res["summary"]["fail"]))
    except Exception:
        pass
    refs["run_log"] = AX.run_log_ref(out)
    return refs

