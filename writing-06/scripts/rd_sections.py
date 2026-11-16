# -*- coding: utf-8 -*-
"""Fallback synthesis, rule audit and the init / check / build CLI (stdlib).

Exit status is always 0; a failed run still leaves a legal result.json.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rd_material as M  # noqa: E402

VERSION = "1.0.0"
SCAN = M.scan_quantities
STOP = "不 未 非 无 无法 不能 not no cannot".split()
CAUSAL = "导致 造成 因为 由于 机制 证明 证实 调控 cause because mechanism prove demonstrat".split()
HYPE = "证明 证实 确证 首次 prove proven confirm definitiv establish".split()
BOUNDARY = "局限 不能排除 相关不等于因果 不能证明 不推断因果 limitation association".split()
TESTED = r"p\s*[<>=]\s*0?\.\d+|ANOVA|t-?test|Mann|Kruskal"

# Fallback prose for the no-draft case.
PHRASES = {
    "zh": {"head": "{m} 随 {h} 的变化",
           "series": "{h} 共 {n} 个水平（{x0}–{x1} {xu}），{m} 由 {y0}{mu} 变为 {y1}{mu}{xr}。",
           "shape": "形态：{shape}。",
           "spread": "{dname} 在 {x} {xu} 最大（{d}）；误差棒含义未给，不解读离散度；n = {ns}。",
           "scope_mono": "读数只支持方向与幅度（关联），无干预组不推断因果。",
           "scope_flat": "读数非单调，只陈述实测值，不概括趋势。",
           "lit": "材料未附文献，不做一致性判断；需作者补引用。",
           "mech": "只有终点读数，不设机制假设；谈因果需干预组与对照。",
           "lim_method": "方法层：只有汇总读数，组间差异不是处理效应。",
           "lim_stat": "统计层：无多重比较校正，不报显著性。",
           "ask": ["请作者确认图/表编号", "请作者补文献对照与机制"],
           "h1": "数据支持到什么程度", "h2": "与已有证据的关系", "h3": "机制与因果边界",
           "title": "结果与讨论", "quote": "材料记载：“{q}”（{loc}）。", "qhead": "{f} 的读数",
           "no_table": "无结构化表：Results 为引文，需改写。",
           "row": "行序",
           "empty_head": "可读读数缺口",
           "empty_results": "材料中无读数块，本节只记录该缺口；补入数据表/图注/统计输出后再写观察句。",
           "shape_word": {"down": "单调下降", "up": "单调上升", "nonmono": "非单调波动", "flat": "基本持平"}},
    "en": {"head": "{m} across {h}",
           "series": "Across {n} {h} levels ({x0} to {x1} {xu}), {m} went from {y0}{mu} to {y1}{mu}{xr}.",
           "shape": "Shape: {shape}.",
           "spread": "{dname} peaked at {x} {xu} ({d}); error-bar meaning not given, so dispersion is not read; "
                     "n = {ns}.",
           "scope_mono": "Readouts support direction and magnitude only (an association); no intervention arm, so "
                         "causation is not inferred.",
           "scope_flat": "Readouts are non-monotonic: only measured values are stated, no trend claimed.",
           "lit": "No comparable literature supplied, so no consistency claim is made; the author must add "
                  "citations.",
           "mech": "Endpoint readouts only: no mechanism proposed, it would exceed the data. Causation needs an "
                   "intervention arm and a control.",
           "lim_method": "Method level: aggregate readouts only, so the difference is no treatment effect.",
           "lim_stat": "Statistics level: no multiplicity correction, so significance is not reported.",
           "ask": ["Author to confirm figure/table numbering", "Author to add literature and mechanism"],
           "h1": "What the data support", "h2": "Relation to existing evidence",
           "h3": "Mechanism and causal boundary", "title": "Results and Discussion",
           "quote": "The material states: \u201c{q}\u201d ({loc}).", "qhead": "Readout for {f}",
           "no_table": "No structured table: Results are quote-bound, rewrite needed.",
           "row": "row order",
           "empty_head": "No readable readout",
           "empty_results": "No readable readout block was found; this section records the gap only. Add a "
                            "table, caption or statistics output before writing observations.",
           "shape_word": {"down": "monotonic decrease", "up": "monotonic increase",
                          "nonmono": "non-monotonic variation", "flat": "essentially flat"}},
}


def synthesize(index):
    corpus = " ".join(b["text"] for b in index.get("blocks") or [] if b["file"] != index.get("case_rel"))
    tag = "zh" if M.cjk_share(corpus) > 0.15 else "en"
    P, rn = PHRASES[tag], M.render_number
    res, dis, ev = [], [], []
    pending, uncertain, shape = list(P["ask"]), [], "flat"

    for table in [t for t in index.get("tables") or [] if t.get("rows") and t.get("header")][:3]:
        series = M.make_series(table)
        if not series:
            continue
        pts, ys = series["pts"], [p["y"] for p in series["pts"]]
        vlabel, clabel = M.pretty_label(series["value"]["head"]), P["row"]
        if series["cond"]:
            clabel = M.pretty_label(series["cond"]["head"])
        cunit = series["cond"]["unit"] if series["cond"] else ""
        shape, refs = M.shape_of(ys), M.caption_refs(index, table)
        paras = [P["series"].format(h=clabel, n=len(pts), x0=rn(pts[0]["x"]), x1=rn(pts[-1]["x"]),
                                    xu=cunit, m=vlabel, y0=rn(ys[0]), y1=rn(ys[-1]),
                                    mu=series["value"]["unit"],
                                    xr=(" (%s)" % "; ".join(refs)) if refs else ""),
                 P["shape"].format(shape=P["shape_word"][shape])]
        if series["spread"] and all(p["d"] is not None for p in pts):
            peak = max(pts, key=lambda p: p["d"] or 0)
            sizes = sorted({rn(p["n"]) for p in pts if p["n"] is not None})
            paras.append(P["spread"].format(dname=M.pretty_label(series["spread"]["head"]),
                                            x=rn(peak["x"]), xu=cunit, d=rn(peak["d"]),
                                            ns="/".join(sizes) or "-"))
        res.append({"heading": P["head"].format(m=vlabel, h=clabel), "xref": refs, "paragraphs": paras})
        for point in pts:
            block = M.resolve_block(index, point["loc"]) if point["loc"] else None
            if block:
                ev.append({"id": "e%d" % (len(ev) + 1), "quote": block["text"][:300],
                           "locator": point["loc"]})

    if not res:
        for block in [b for b in index.get("blocks") or []
                      if b["file"] != index.get("case_rel") and SCAN(b["text"])
                      and not b["text"].startswith(M.VISUAL_TAG)][:6]:
            res.append({"heading": P["qhead"].format(f=block["file"].split("/")[-1]), "xref": [],
                        "paragraphs": [P["quote"].format(q=block["text"][:300], loc=block["loc"])]})
            ev.append({"id": "e%d" % (len(ev) + 1), "quote": block["text"][:300],
                       "locator": block["loc"]})
        if res:
            pending.append(P["no_table"])
    if not res:
        res.append({"heading": P["empty_head"], "xref": [], "paragraphs": [P["empty_results"]]})
        pending.append(P["empty_head"])

    for key, head in (("scope_mono" if shape in ("up", "down") else "scope_flat", "h1"),
                      ("lit", "h2"), ("mech", "h3")):
        dis.append({"heading": P[head], "xref": [], "paragraphs": [P[key]]})

    gaps = M.material_gaps(index)
    return {"title": P["title"], "language": tag, "results": res, "discussion": dis,
            "limitations": [g["limit"] for g in gaps] + [P["lim_method"], P["lim_stat"]],
            "evidence": ev, "derived": [],
            "preserved_facts": [{"fact": "readout @%s" % e["locator"], "quote": e["quote"],
                                 "locator": e["locator"]} for e in ev][:20],
            "changes": [], "pending_human": pending, "uncertainty": uncertain}, gaps


def audit(index, draft, path):
    out = []

    def add(level, code, msg, loc=None, sug=None):
        out.append({"level": level, "code": code, "message": msg, "locator": loc, "suggest": sug})
        return out[-1]

    if not isinstance(draft, dict):
        add("error", "draft_missing", "no draft at %s" % path)
        return {"draft": str(path), "issues": out, "counters": {"errors": 1, "warnings": 0}}

    def paras(sections):
        for i, sec in enumerate(sections):
            for j, text in enumerate([x for x in (sec.get("paragraphs") or [])
                                      if isinstance(x, str) and x.strip()]):
                yield i, j, text

    blocks = index.get("blocks") or []
    res = [s for s in (draft.get("results") or []) if isinstance(s, dict)]
    dis = [s for s in (draft.get("discussion") or []) if isinstance(s, dict)]
    if not res or not dis:
        add("error", "schema", "results and discussion need a section each")

    verbatim, approx, broken = set(), set(), 0
    entries = [e for e in (draft.get("evidence") or []) if isinstance(e, dict)]
    for i, entry in enumerate(entries):
        quote, loc = entry.get("quote"), entry.get("locator")
        if not quote or not loc:
            broken += 1
            add("error", "evidence_bad", "evidence[%d]: quote+loc" % i, loc)
            continue
        status, at = M.verify_citation(index, quote, loc)
        if status in ("exact", "span", "misplaced"):
            verbatim |= {x["value"] for x in SCAN(quote)}
        elif entry.get("approx"):
            approx |= {x["value"] for x in SCAN(quote)}
        else:
            broken += 1
            first = SCAN(quote)
            add("error", "evidence_bad", "evidence[%d] not verbatim" % i, loc,
                M.holders(index, first[0]["value"] if first else None, 2, True))

    derived = set()
    for item in draft.get("derived") or []:
        value = M.to_number(str(item.get("value"))) if isinstance(item, dict) else None
        if value is not None:
            derived.add(value)

    def sourced(value):
        return value in verbatim or value in approx or value in derived

    rtext, dtext, seen = [], [], []
    for i, j, text in paras(res):
        rtext.append(text)
        low = text.lower()
        for token in SCAN(text):
            seen.append(token)
            if not sourced(token["value"]):
                add("error", "number_unverified", "results[%d].p[%d] %r unsourced"
                    % (i, j, token["raw"]), None, M.holders(index, token["value"]))["token"] = token["raw"]
        for word in CAUSAL:
            at = low.find(word)
            if at >= 0 and not any(n in low[max(0, at - 12):at] for n in STOP):
                add("error", "results_causal", "results[%d].p[%d] %r: move to Discussion" % (i, j, word))
        if re.search(r"显著|significan", low) and not re.search(TESTED, low):
            add("error", "sig_without_stat", "results[%d].p[%d] significant, no test" % (i, j))

    rvalues = {t["value"] for t in SCAN(" ".join(rtext))}
    for i, j, text in paras(dis):
        dtext.append(text)
        low = text.lower()
        for word in HYPE:
            at = low.find(word)
            if at >= 0 and not any(n in low[max(0, at - 12):at] for n in STOP):
                add("error", "overclaim", "discussion[%d].p[%d] %r: hedge" % (i, j, word))
        for token in SCAN(text):
            if token["value"] not in rvalues and not sourced(token["value"]):
                add("warn", "discussion_new_number", "discussion[%d].p[%d] %r no source"
                    % (i, j, token["raw"]))

    joined = " ".join(dtext).lower()
    if dtext and not any(word.lower() in joined for word in BOUNDARY):
        add("warn", "discussion_no_boundary", "no causal boundary")

    limits = [str(x).strip() for x in (draft.get("limitations") or []) if str(x).strip()]
    lack = M.missing_layers(limits)
    if not limits:
        add("error", "no_limitations", "limitations is empty")
    elif len(limits) < 2 or lack:
        add("warn", "limitations_weak", "%d limit(s), layers missing %s" % (len(limits), ",".join(lack) or "-"))

    for i, fact in enumerate([x for x in (draft.get("preserved_facts") or []) if isinstance(x, dict)]):
        if not fact.get("quote") or not fact.get("locator"):
            add("warn", "fact_no_source", "preserved_facts[%d]: quote+loc" % i)
        elif M.verify_citation(index, fact["quote"], fact["locator"])[0] in ("notfound", "empty"):
            add("error", "fact_bad", "preserved_facts[%d] not verbatim" % i, fact["locator"])
    if not blocks:
        add("warn", "no_blocks", "no readable block in index")

    def words(ps):
        return sum(len(re.findall(r"[\u4e00-\u9fff]", p)) if M.cjk_share(p) > 0.3 else len(p.split())
                   for p in ps)

    levels = [x["level"] for x in out]
    return {"draft": str(path), "issues": out[:120],
            "counters": {"errors": levels.count("error"), "warnings": levels.count("warn"),
                         "evidence_total": len(entries), "evidence_ok": len(entries) - broken,
                         "evidence_failed": broken, "numbers_total": len(seen),
                         "numbers_verified": sum(1 for t in seen if sourced(t["value"])),
                         "numbers_unverified": sum(1 for t in seen if not sourced(t["value"])),
                         "results_sections": len(res),
                         "discussion_sections": len(dis), "results_words": words(rtext),
                         "discussion_words": words(dtext), "limitations": len(limits)}}


def cmd_init(args):
    root, work, out = Path(args.input), Path(args.work), Path(args.out)
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    case, case_error = M.read_case(root)
    keys = M.contract_keys(case)
    case_id = M.pick(case, ["case_id", "caseid"]) if isinstance(case, dict) else None
    payload = dict({"case_id": case_id, "status": "partial", "sources": [], "uncertainty": [],
                    "pending_human": [], "errors": [], "changes": [],
                    "degradations": ["init placeholder: run build"],
                    "runtime": {"stage": "init", "wrote_at": M.stamp()}},
                   **{k: None for k in keys if k.lower() != "case_id"})
    M.write_json(out / "result.json", payload)
    if not root.is_dir():
        payload.update({"status": "input_error", "errors": ["input_error %s" % root]})
        M.write_json(out / "result.json", payload)
        print("INPUT ERROR: %s is not a directory" % root)
        return
    index = M.build_index(root, keys)
    index.update({"case_id": case_id, "case_error": case_error,
                  "instruction": M.pick(case, ["task_instruction", "instruction", "task"]),
                  "contract_raw": M.pick(case, ["output_contract", "contract"])})
    M.write_json(work / "index.json", index)
    M.print_source_map(index, case_id, case_error)
    payload.update({"sources": index["materials"], "errors": list(index["errors"])})
    if not index["blocks"]:
        payload.update({"status": "insufficient_evidence",
                        "pending_human": ["no readable text block under %s" % root]})
    M.write_json(out / "result.json", payload)


def cmd_check(args):
    index = M.index_for(args)
    draft_path = Path(args.draft) if args.draft else Path(args.work) / "draft.json"
    report = audit(index, M.read_json(draft_path)[0], draft_path)
    M.write_json(Path(args.work) / "check_report.json", report)
    c = report["counters"]
    print("CHECK %s errors=%d warnings=%d | evidence ok/failed %d/%d | numbers %d/%d"
          % (draft_path, c.get("errors", 0), c.get("warnings", 0), c.get("evidence_ok", 0),
             c.get("evidence_failed", 0), c.get("numbers_verified", 0), c.get("numbers_total", 0)))
    for issue in report["issues"][:8]:
        print("  %-4s %-15s %s%s" % (issue["level"][:4], issue["code"], issue["message"][:110],
                                     " @" + issue["locator"] if issue["locator"] else ""))
    print("NEXT:", "fix errors" if c.get("errors") else "build")


def cmd_build(args):
    out, work = Path(args.out), Path(args.work)
    for path in (out, work):
        path.mkdir(parents=True, exist_ok=True)
    index = M.index_for(args)
    contract = index.get("contract") or list(M.BASE_FIELDS)
    case_id = index.get("case_id")
    draft_path = Path(args.draft) if args.draft else work / "draft.json"
    draft, draft_error = M.read_json(draft_path)
    spare, steps = synthesize(index)[0], []
    if isinstance(draft, dict):
        mode = "agent-draft"
        for key in ("results", "discussion", "limitations", "evidence"):
            if not [x for x in (draft.get(key) or []) if str(x).strip()]:
                draft[key] = spare[key]
                steps.append(key + " from fallback")
    else:
        draft, mode = dict(spare), "fallback"
        steps.append("no draft: %s" % draft_error)

    report = audit(index, draft, draft_path)
    c = report["counters"]
    manuscript, lang = M.render_markdown(draft, M.SECTION_LABELS)
    (out / "manuscript.md").write_text(manuscript, encoding="utf-8")
    plain = re.sub(r"## [12]\. ", "## ", manuscript)
    (out / "results_discussion.md").write_text(plain, encoding="utf-8")
    sections = [{"section": "1.%d" % i, "paragraph": j, "text": text,
                 "readouts": [{"token": q["raw"], "value": q["value"], "unit": q["unit"],
                               "sources": M.holders(index, q["value"])} for q in SCAN(text)]}
                for i, sec in enumerate([s for s in draft.get("results") or [] if isinstance(s, dict)], 1)
                for j, text in enumerate([x for x in (sec.get("paragraphs") or [])
                                          if isinstance(x, str) and x.strip()], 1)]
    evidence = []
    for i, entry in enumerate([x for x in (draft.get("evidence") or []) if isinstance(x, dict)]):
        state, at = M.verify_citation(index, entry.get("quote"), entry.get("locator"))
        evidence.append({"id": entry.get("id") or "e%d" % (i + 1), "quote": entry.get("quote"),
                         "locator": at, "verified": state})
    facts = [{"fact": f.get("fact"), "quote": f.get("quote"), "locator": f.get("locator"),
              "verified": M.verify_citation(index, f.get("quote"), f.get("locator"))[0]}
             for f in (draft.get("preserved_facts") or []) if isinstance(f, dict)]
    changes = [x for x in (draft.get("changes") or []) if isinstance(x, dict)] + [
        {"action": "assembled manuscript.md", "mode": mode}]
    pending = [x for x in (draft.get("pending_human") or []) if isinstance(x, str)]
    pending += [x["message"] for x in report["issues"] if x["level"] == "error"][:4]
    limits = [str(x).strip() for x in (draft.get("limitations") or []) if str(x).strip()]

    M.write_json(out / "results_map.json", {
        "case_id": case_id, "sections": sections,
        "coverage": {"numbers": c.get("numbers_total", 0), "verified": c.get("numbers_verified", 0)},
        "unverified": [{"token": x.get("token") or x["message"], "suggest": x.get("suggest")}
                       for x in report["issues"] if x["code"] == "number_unverified"]})
    M.write_json(out / "evidence_map.json", {"case_id": case_id, "entries": evidence})
    M.write_json(out / "preserved_facts.json", {"case_id": case_id, "facts": facts})
    M.write_json(out / "change_log.json", {"case_id": case_id, "changes": changes,
                                           "pending_human": pending, "degradations": steps})
    art = {"deliverable": {"path": "manuscript.md", "format": "markdown", "language": lang,
                           "mode": mode, "bytes": len(manuscript.encode("utf-8")),
                           "text": manuscript[:12000]},
           "results_map": {"path": "results_map.json", "sections": len(sections),
                           "verified": c.get("numbers_verified", 0)},
           "evidence_map": {"path": "evidence_map.json", "entries": len(evidence)},
           "preserved_facts": facts,
           "limitations": {"items": limits, "layers_missing": M.missing_layers(limits),
                           "material_gaps": M.material_gaps(index)},
           "change_log": {"changes": changes, "pending_human": pending},
           "uncertainty": [x for x in (draft.get("uncertainty") or []) if isinstance(x, str)]}
    errs = list(index.get("errors") or [])
    if index.get("case_error"):
        errs.insert(0, "case.json: %s" % index["case_error"])
    status = "input_error" if not Path(args.input).is_dir() else (
        "insufficient_evidence" if not index.get("blocks") else (
            "partial" if mode == "fallback" or c.get("errors") else "ok"))
    payload, filled = {"case_id": case_id, "status": status}, 0
    for key in contract:
        payload[key] = M.route_contract(key, art)
        filled += 0 if payload[key] in (None, "", [], {}) else 1
    metrics = dict(c, materials=len(index.get("materials") or []), mode=mode,
                   tables=len(index.get("tables") or []),
                   traceability_rate=round(c.get("numbers_verified", 0) / c["numbers_total"], 3)
                   if c.get("numbers_total") else 0.0)
    payload.update({"output_contract": index.get("contract_raw") or {k: "" for k in contract},
                    "contract_fields": {"total": len(contract), "filled": filled, "keys": contract},
                    "sources": index.get("materials") or [], "uncertainty": art["uncertainty"],
                    "pending_human": pending, "errors": errs,
                    "degradations": steps, "changes": changes, "metrics": metrics,
                    "runtime": {"version": VERSION, "stage": "build", "wrote_at": M.stamp()}})
    verdict = M.self_audit(payload, art, c, manuscript, contract)
    metrics["self_audit"] = {k: verdict[k] for k in ("passed", "failed", "passed_names", "failed_names")}
    if verdict["failed"]:
        payload["degradations"] = steps + ["self_audit_failed:" + n for n in verdict["failed_names"]]
    M.write_json(out / "result.json", payload)
    print("BUILD %s status=%s mode=%s contract=%d/%d self-audit=%d/%d %dB results=%d/%d numbers=%d/%d"
          % (out, status, mode, filled, len(contract), verdict["passed"],
             verdict["passed"] + verdict["failed"], len(manuscript.encode("utf-8")),
             c.get("results_sections", 0), c.get("discussion_sections", 0),
             c.get("numbers_verified", 0), c.get("numbers_total", 0)))


def safe_fail(args, exc):
    """Last resort: leave a legal result.json that still carries every contract key."""
    try:
        case, _ = M.read_case(Path(getattr(args, "input", "/input")))
        keys = M.contract_keys(case) if isinstance(case, dict) else list(M.BASE_FIELDS)
        case_id = M.pick(case, ["case_id", "caseid"]) if isinstance(case, dict) else None
        payload = dict({"case_id": case_id, "status": "partial", "sources": [],
                        "uncertainty": [str(exc)], "changes": [], "metrics": {},
                        "pending_human": ["run aborted; see errors"],
                        "errors": ["%s: %s" % (type(exc).__name__, exc)],
                        "degradations": ["safe_fail"],
                        "runtime": {"version": VERSION, "stage": "safe_fail", "wrote_at": M.stamp()}},
                       **{k: None for k in keys if str(k).lower() != "case_id"})
        M.write_json(Path(getattr(args, "out", "/app/output")) / "result.json", payload)
    except Exception:
        pass
    print("ERROR %s: %s" % (type(exc).__name__, exc))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="rd_sections.py",
        description="Readout-to-sections: init | check | build; exit status is always 0")
    commands = parser.add_subparsers(dest="cmd", help="index / audit / finalise")
    blurbs = {"init": "index material, write partial result.json",
              "check": "audit work/draft.json", "build": "write manuscript and result.json"}
    for name, blurb in blurbs.items():
        sub = commands.add_parser(name, help=blurb, description=blurb)
        for flag, default in (("input", "/input"), ("work", "/app/work"), ("out", "/app/output")):
            sub.add_argument("--" + flag, default=os.environ.get("SKILL_" + flag.upper(), default))
        if name != "init":
            sub.add_argument("--draft", default=None, help="default <work>/draft.json")
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    try:
        {"init": cmd_init, "check": cmd_check, "build": cmd_build}[args.cmd](args)
    except SystemExit:
        raise
    except Exception as exc:
        safe_fail(args, exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
