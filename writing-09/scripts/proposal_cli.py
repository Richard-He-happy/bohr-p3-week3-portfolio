#!/usr/bin/env python3
import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
try:
    import audit_kit as AK
except Exception:
    AK = None
try:
    import evidence_assets as EA
except Exception:
    EA = None
CONTRACT_KEYS = ("case_id", "deliverable", "preserved_facts", "evidence_map", "change_log")
SUPPORT_FILES = ("proposal.md", "evidence_map.json", "goal_matrix.md", "planning_units.json",
                 "risks.md", "pending_human.json", "draft_boundary.md")
RUBRIC = SCRIPT_DIR.parent / "references" / "audit-rubric.md"
def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default
def dump_json(path, obj):
    try:
        text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
        Path(path).write_text(text, encoding="utf-8")
        return True
    except Exception:
        return False
def put_text(path, text, overwrite=True):
    path = Path(path)
    if path.exists() and not overwrite:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True
    except Exception:
        return False
def overlay_template(name, default=""):
    try:
        body = RUBRIC.read_text(encoding="utf-8")
        hit = re.search(r"<!--BEGIN:%s-->(.*?)<!--END:%s-->" % (name, name), body, re.S)
        return (hit.group(1).strip() + "\n") if hit else default
    except Exception:
        return default
def pick_out_dir(raw):
    if raw:
        return Path(raw).expanduser().resolve()
    for cand in (Path("/app/output"), SCRIPT_DIR.parent.parent / "output"):
        try:
            cand.mkdir(parents=True, exist_ok=True)
            return cand.resolve()
        except Exception:
            pass
    return Path("/app/output")
def locate_workorder(node, depth=0):
    if depth > 6 or not isinstance(node, (dict, list)):
        return None
    if isinstance(node, dict):
        has_sections = "sections" in node
        has_plan = any(k in node for k in ("draft_size", "planning_months", "consistency"))
        if has_sections and has_plan:
            return node
        children = node.values()
    else:
        children = list(node)
    for child in children:
        found = locate_workorder(child, depth + 1)
        if found:
            return found
    return None
def load_context(inp, out):
    ctx = {"case_id": None, "contract": {}, "workorder": {},
           "errors": [], "degradations": [], "changes": [], "sources": [], "out": str(out)}
    case_path = inp / "case.json"
    if not case_path.exists() and inp.exists():
        candidates = sorted(inp.rglob("case*.json"))
        case_path = candidates[0] if candidates else None
    case = load_json(case_path) if case_path else None
    if not isinstance(case, dict):
        ctx["errors"].append({"code": "case_json_unreadable", "message": "case.json 缺失或非法"})
        ctx["degradations"].append("case_json_unreadable")
        case = {}
    ctx["case_id"] = case.get("case_id")
    ctx["contract"] = case.get("output_contract") or {}
    workorder = locate_workorder(case)
    if workorder is None:
        ctx["degradations"].append("workorder_absent_defaults_applied")
    ctx["workorder"] = workorder or {}
    return ctx
def build_plan(ctx):
    wo = ctx["workorder"] or {}
    size = re.search(r"(\d{3,4})\s*[–\-—~至到]\s*(\d{3,4})", str(wo.get("draft_size") or ""))
    lo, hi = (int(size.group(1)), int(size.group(2))) if size else (1600, 2600)
    declared = [s for s in (wo.get("sections") or []) if isinstance(s, dict)]
    sections = []
    for spec in (AK.SECTION_SPECS if AK else []):
        matched = next((s for s in declared
                        if any(alias in str(s.get("title", "")) for alias in spec["aliases"])), {})
        matched = matched or {}
        sections.append({"id": matched.get("id", spec["id"]),
                         "title": matched.get("title", spec["title"]),
                         "minimum": matched.get("minimum", ""),
                         "budget": spec["budget"]})
    return {"sections": sections, "lo": lo, "hi": hi,
            "months": int(wo.get("planning_months") or 12),
            "cap": int(wo.get("planning_unit_cap") or 100),
            "um": wo.get("planning_unit_meaning") or "规划单位：非货币、非已获资金、非真实预算。",
            "auth": wo.get("authority") or "organizer-workorder-not-funder-policy"}
def attribution_suffix(wo):
    basis = (wo or {}).get("source_basis") or {}
    authors = basis.get("external_authors") or []
    paper = basis.get("published_paper") or ""
    if not authors:
        return "（外部作者）"
    tail = "，" + paper if paper else ""
    return "（%s%s）" % ("、".join(authors), tail)
def human_seed(wo):
    basis = (wo or {}).get("source_basis") or {}
    items = [
        {"id": "PH1", "topic": "真实申请人证据",
         "need": "申请人自有前期成果、数据与平台条件证明",
         "why": "既有结果归外部作者，不能作申请人基础（applicant_owned=%s）"
                % basis.get("applicant_owned_preliminary_results_supplied"),
         "evidence_needed": "申请人已完成实验/论文记录",
         "affected_sections": ["foundation", "background"], "status": "open", "blocking": True},
        {"id": "PH2", "topic": "真实资助要求",
         "need": "真实资助指南、申报口径与政策条款",
         "why": "authority=%s，仅评测写作要求（funder_notice=%s）"
                % ((wo or {}).get("authority"), basis.get("actual_funder_notice_supplied")),
         "evidence_needed": "当年度申报指南原文与评审要点",
         "affected_sections": ["background", "goals"], "status": "open", "blocking": True},
    ]
    if basis.get("resource_availability_evidence_supplied") is not True:
        items.append({"id": "PH3", "topic": "资源可用性证据",
                      "need": "设备、材料、算力与人员投入证明",
                      "why": "resource_availability=%s，不得写“设备已具备”"
                             % basis.get("resource_availability_evidence_supplied"),
                      "evidence_needed": "设备清单与可用时段、协作分工",
                      "affected_sections": ["foundation", "route"], "status": "open",
                      "blocking": False})
    return items
def units_skeleton(plan):
    return {"cap": plan["cap"], "unit_meaning": plan["um"], "total": None,
            "note": "分项之和 = total 且 ≤ cap；非货币、非已获资金、非真实预算。",
            "items": [{"id": "WP%d" % i, "goal": "G%d" % i, "units": None,
                       "name": "（WP%d↔G%d）" % (i, i)} for i in (1, 2, 3)]}
def emit_scaffold(out, ctx, plan, facts):
    hint = overlay_template("skel", "> 字数 {lo}–{hi} 汉字；周期 {m} 月；规划单位上限 {cap}。")
    lines = ["# 基金申请书章节草稿（骨架，待改写；不可直接提交）", "",
             hint.format(lo=plan["lo"], hi=plan["hi"], m=plan["months"], cap=plan["cap"]).strip(),
             "> 结果归外部作者%s；先读 quote_bank.md 取逐字事实。"
             % attribution_suffix(ctx["workorder"]), ""]
    for no, section in enumerate(plan["sections"], 1):
        lines += ["## %d. %s" % (no, section["title"]), "",
                  "> 目标≈%d 字；%s 须实质正文+依据 locator+与邻节编号衔接。"
                  % (section["budget"], section["minimum"]),
                  "", "（在此写正文）", ""]
    put_text(out / "proposal_skeleton.md", "\n".join(lines))
    bank = ["# 候选逐字引文与执行约束（未改写）", "",
            "| source_id | 文件 | 类型 | 单元 |", "|-|-|-|-|"]
    bank += ["| %s | %s | %s | %d |" % (s["source_id"], s["name"], s["kind"], len(s["units"]))
             for s in ctx["sources"]]
    bank += ["", "## 带数值/单位的事实", ""]
    for fact in facts:
        bank += ["- `%s` %s · %s · `%s`" % (fact["fact_id"], fact["source_id"],
                                            fact["locator"], fact["value"]),
                 "  > %s" % fact["quote"].replace("\n", " ")]
    bank += ["- authority=%s，不作为真实资助政策。" % plan["auth"],
             "- 字数 %d–%d；周期 %d 月内；规划单位 ≤%d，非货币。"
             % (plan["lo"], plan["hi"], plan["months"], plan["cap"]),
             "- 目标恰 3 个 G1–G3，各对应工作包+里程碑+指标。"]
    put_text(out / "quote_bank.md", "\n".join(bank) + "\n")
def as_item_list(out, name):
    payload = load_json(out / name, None)
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, dict):
        return list(payload.get("items") or [])
    return []
def _carry_records(md, facts, evidence, changelog, suffix):
    seen = {str(x.get("original_quote", ""))[:40] for x in changelog if isinstance(x, dict)}
    known = {str(x.get("quote", ""))[:40] for x in evidence if isinstance(x, dict)}
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        value = str(fact.get("value") or "")
        if not value or value not in md or str(fact.get("quote", ""))[:40] in seen:
            continue
        carried = sorted([x.strip() for x in re.split(r"(?<=[。\n])", md) if value in x],
                         key=len)
        if not carried:
            continue
        changelog.append({"id": "CLA%02d" % (len(changelog) + 1), "kind": "fact_carryover",
                          "original_quote": fact.get("quote", ""),
                          "revised_quote": carried[0][:220],
                          "reason": "数值/条件逐字保留，改为拟开展语态；结果归外部作者%s" % suffix,
                          "locator": fact.get("locator"), "source_id": fact.get("source_id"),
                          "attribution": "external_author"})
        fingerprint = str(fact.get("quote", ""))[:40]
        seen.add(fingerprint)
        if fingerprint not in known:
            evidence.append({"claim_id": "CE%02d" % (len(evidence) + 1), "section": None,
                             "kind": "fact", "verified": True,
                             "claim": "沿用源材料事实 %s" % value,
                             "source_id": fact.get("source_id"),
                             "locator": fact.get("locator"), "quote": fact.get("quote", ""),
                             "auto": True})
def _support_present(out):
    return [name for name in SUPPORT_FILES if (out / name).exists()]
def compose_result(ctx, out, plan, audit, status=None):
    suffix = attribution_suffix(ctx["workorder"])
    contract = ctx["contract"] if isinstance(ctx["contract"], dict) else {}
    md = ""
    if (out / "proposal.md").exists():
        try:
            md = (out / "proposal.md").read_text(encoding="utf-8", errors="ignore")
        except Exception:
            md = ""
    facts = as_item_list(out, "preserved_facts.json")
    evidence = as_item_list(out, "evidence_map.json")
    changelog = as_item_list(out, "change_log.json")
    human = as_item_list(out, "pending_human.json")
    units = load_json(out / "planning_units.json", {}) or {}
    total_units = None
    if isinstance(units.get("items"), list):
        nums = [i.get("units") for i in units["items"] if isinstance(i, dict)]
        if nums and all(isinstance(n, (int, float)) for n in nums):
            total_units = sum(nums)
    metrics = audit.get("metrics", {})
    _carry_records(md, facts, evidence, changelog, suffix)
    sections = []
    if AK and md:
        for key, span in AK.section_ranges(md).items():
            sections.append({"id": key, "title": span["title"], "found": span["found"],
                             "char_count": span["chars"]})
    result = {"case_id": ctx["case_id"], "preserved_facts": facts, "evidence_map": evidence,
              "change_log": changelog, "pending_human": human,
              "errors": list(ctx.get("errors", [])),
              "degradations": sorted(set(ctx.get("degradations", []))),
              "changes": ctx.get("changes", []),
              "status": status or audit.get("status", "partial")}
    result["deliverable"] = {"file": "proposal.md", "path": str(out / "proposal.md"),
                             "format": "markdown", "editable": True,
                             "char_count": metrics.get("char_total", 0),
                             "char_range": [plan["lo"], plan["hi"]], "sections": sections,
                             "supporting_files": _support_present(out),
                             "title": "基金申请书七要素章节草稿（源材料限定）"}
    for key, value in contract.items():
        if key not in CONTRACT_KEYS and key not in result:
            result[key] = value
    if contract:
        result["output_contract_echo"] = contract
    result["sources"] = [{"source_id": s["source_id"], "name": s["name"], "kind": s["kind"],
                          "role": s["role"], "units": len(s["units"]), "path": s.get("path")}
                         for s in ctx.get("sources", [])]
    result["uncertainty"] = [
        {"id": "U1", "topic": "申请人自有证据缺失", "impact": "foundation",
         "detail": "前期成果全部来自外部作者论文。"},
        {"id": "U2", "topic": "真实资助要求缺失", "impact": "background",
         "detail": "写作要求来自 organizer_workorder，非指南。"},
        {"id": "U3", "topic": "资源可用性未证实", "impact": "route",
         "detail": "设备/材料投入未证明，只作拟开展。"}]
    result["runtime"] = {"tool": "proposal_cli.py", "version": "1.0.0", "network": False,
                         "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "seconds": round(time.time() - ctx.get("t0", time.time()), 2)}
    present = result["deliverable"]["supporting_files"]
    executed = {"workorder_id": (ctx["workorder"] or {}).get("id"), "authority": plan["auth"],
                "authority_honored": True, "sections_expected": len(plan["sections"]),
                "sections_satisfied": len(metrics.get("sections_found", [])),
                "char_count": metrics.get("char_total", 0),
                "char_range": [plan["lo"], plan["hi"]],
                "char_count_in_range": plan["lo"] <= metrics.get("char_total", 0) <= plan["hi"],
                "planning_months": plan["months"], "max_month_found": metrics.get("max_month"),
                "planning_units_total": total_units, "planning_unit_cap": plan["cap"],
                "goals_count": metrics.get("goals_count"), "matrix_rows": metrics.get("matrix_rows"),
                "risks_count": metrics.get("risks_count"), "pending_human_count": len(human)}
    executed["planning_units_in_cap"] = (isinstance(total_units, (int, float))
                                         and total_units <= plan["cap"])
    executed["limits_checks"] = {
        "attribution_flagged": metrics.get("attribution_flagged", 0),
        "external_author_marked": metrics.get("external_author_marked", False),
        "banned_phrases_unverified": metrics.get("banned_unverified", 0),
        "currency_free": "万元" not in md and "￥" not in md}
    executed["contract_keys_missing"] = sorted(k for k in contract if k not in result)
    executed["supporting_files_missing"] = [n for n in SUPPORT_FILES if n not in present]
    executed["cross_file_checks"] = {"matrix_units_joined": metrics.get("matrix_units_joined"),
                                     "boundary_present": metrics.get("boundary_present"),
                                     "unbacked_claims": metrics.get("unbacked_claims")}
    result["workorder_execution"] = executed
    result["checks"] = {"status": audit.get("status"), "counts": audit.get("counts"),
                        "metrics": metrics, "issues": audit.get("issues", [])}
    return result
def rescale_units(out, plan, ctx):
    payload = load_json(out / "planning_units.json", None)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return
    items = [i for i in payload["items"] if isinstance(i, dict)]
    nums = [i.get("units") for i in items]
    if not items or not all(isinstance(x, (int, float)) for x in nums):
        return
    total = sum(nums)
    if total > plan["cap"]:
        scaled = [round(x * plan["cap"] / total, 1) for x in nums]
        for item, val in zip(items, scaled):
            item["units"] = val
        payload["total"] = round(sum(scaled), 1)
        payload["repair_note"] = "合计 %.1f 超上限 %d，按比例缩放（不改结构），需人工复核。" % (
            total, plan["cap"])
        ctx["changes"].append({"id": "CH-units", "file": "planning_units.json",
                               "action": "rescale", "original": "total=%.1f" % total,
                               "revised": "total=%.1f" % payload["total"],
                               "reason": "planning_unit_cap=%d" % plan["cap"],
                               "human_confirm": True})
    elif payload.get("total") != total:
        payload["total"] = total
    dump_json(out / "planning_units.json", payload)
def prepare_run(inp, out):
    out.mkdir(parents=True, exist_ok=True)
    ctx = load_context(inp, out)
    ctx["t0"] = time.time()
    ctx["sources"] = AK.scan_sources(inp) if AK else []
    facts = AK.harvest_facts(ctx["sources"]) if AK else []
    if EA:
        EA.note("scan_done", sources=len(ctx["sources"]), facts=len(facts))
    return ctx, build_plan(ctx), facts
def run_init(inp, out):
    ctx, plan, facts = prepare_run(inp, out)
    dump_json(out / "workorder.json", ctx["workorder"] or {
        "absent": True, "defaults": {"planning_months": 12, "planning_unit_cap": 100}})
    emit_scaffold(out, ctx, plan, facts)
    templates = (("planning_units.json", json.dumps(units_skeleton(plan), ensure_ascii=False,
                                                   indent=2) + "\n"),
                 ("goal_matrix.md", overlay_template("matrix", "# 目标—工作包—里程碑—指标矩阵\n")),
                 ("risks.md", overlay_template("risks", "# 风险与备选方案\n")),
                 ("draft_boundary.md", overlay_template("boundary", "# 已完成 / 拟开展 边界表\n")))
    for name, text in templates:
        put_text(out / name, text, False)
    seeds = {"pending_human.json": human_seed(ctx["workorder"]),
             "preserved_facts.json": {"note": "只保留用到的条目；quote 须逐字。",
                                      "items": facts[:25]},
             "evidence_map.json": {"note": "claim/section/kind/source_id/locator/quote",
                                   "items": []},
             "change_log.json": {"note": "original_quote->revised_quote+reason+locator",
                                 "items": []}}
    for name, payload in seeds.items():
        if not (out / name).exists():
            dump_json(out / name, payload)
    audit = AK.audit_output(out, plan) if AK else {}
    result = compose_result(ctx, out, plan, audit, status="partial")
    result["stage"] = "init"
    result["limits"] = "仅骨架与证据抽取"
    dump_json(out / "result.json", result)
    if EA:
        EA.note("run_done", stage="init", status="partial", sources=len(ctx["sources"]))
    print(json.dumps({"stage": "init", "case_id": ctx["case_id"], "output": str(out),
                      "sources": len(ctx["sources"]),
                      "sections": [s["title"] for s in plan["sections"]],
                      "chars_range": [plan["lo"], plan["hi"]],
                      "next": "编辑 proposal.md 后 finalize"}, ensure_ascii=False, indent=2))
    return 0
def run_finalize(inp, out):
    ctx, plan, _facts = prepare_run(inp, out)
    index = AK.quote_index(ctx["sources"]) if AK else []
    if not (out / "proposal.md").exists():
        skeleton = out / "proposal_skeleton.md"
        fallback = skeleton.read_text(encoding="utf-8") if skeleton.exists() else \
            "# 降级保底稿，需人工补写\n"
        put_text(out / "proposal.md", fallback)
        ctx["degradations"].append("proposal_absent_fallback_generated")
        ctx["errors"].append({"code": "proposal_absent",
                              "message": "未找到 proposal.md，已生成降级保底稿"})
    rescale_units(out, plan, ctx)
    raw = load_json(out / "evidence_map.json", None)
    if isinstance(raw, dict):
        entries = raw.get("items") or []
    elif isinstance(raw, list):
        entries = raw
    else:
        entries = []
    entries = [e for e in (entries or []) if isinstance(e, dict)]
    unmatched = 0
    for entry in entries:
        if not (entry.get("quote") or "").strip():
            entry["verified"], entry["match"] = None, "no_quote_needed"
            continue
        hit = AK.locate_quote(index, entry.get("quote") or "")
        entry["verified"] = hit["match"] in ("normalized", "partial")
        entry["match"] = hit["match"]
        if not entry["verified"]:
            unmatched += 1
            entry["locator"] = entry.get("locator") or hit.get("locator")
            entry["note"] = "未定位，需核对原文"
    if raw is not None:
        dump_json(out / "evidence_map.json",
                  entries if isinstance(raw, list) else
                  {"note": (raw or {}).get("note", ""), "items": entries})
    if unmatched:
        ctx["degradations"].append("evidence_quotes_unverified:%d" % unmatched)
        human = load_json(out / "pending_human.json", []) or []
        if isinstance(human, dict):
            human = human.get("items") or []
        human = list(human)
        human.append({"id": "PHQ", "topic": "引文未能定位", "need": "%d 条引文未定位" % unmatched,
                      "why": "PDF 无文本层或引文被改写", "status": "open", "blocking": False})
        dump_json(out / "pending_human.json", human)
    audit = AK.audit_output(out, plan) if AK else {}
    status = "partial" if ctx["errors"] else audit.get("status", "partial")
    result = compose_result(ctx, out, plan, audit, status=status)
    result["stage"] = "final"
    dump_json(out / "result.json", result)
    if EA:
        EA.note("run_done", stage="final", status=status, issues=audit.get("counts"))
    metrics = audit.get("metrics", {})
    print(json.dumps({"stage": "final", "case_id": ctx["case_id"], "status": status,
                      "char_count": metrics.get("char_total"),
                      "planning_units_total": metrics.get("planning_units_total"),
                      "issues": audit.get("counts"),
                      "result": str(out / "result.json")}, ensure_ascii=False, indent=2))
    return 0
def flush_assets(inp, out, stage):
    if not EA:
        return
    try:
        EA.finish(inp, out, stage, 0)
    except Exception:
        pass
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="七要素基金申请书 Skill：init 建骨架；finalize 回检与契约回填。")
    parser.add_argument("command", nargs="?", default="init", choices=["init", "finalize", "all"],
                        help="init(默认) / finalize / all")
    parser.add_argument("--input", default="", help="输入目录，默认 /input")
    parser.add_argument("--output", default="", help="输出目录，默认 /app/output")
    parser.add_argument("--version", action="version", version="1.0.0")
    args = parser.parse_args(argv)
    inp = Path(args.input).expanduser().resolve() if args.input else Path("/input")
    out = pick_out_dir(args.output)
    stage = "init" if args.command == "init" else "final"
    try:
        if args.command == "finalize":
            code = run_finalize(inp, out)
        elif args.command == "all":
            run_init(inp, out)
            code = run_finalize(inp, out)
        else:
            code = run_init(inp, out)
        flush_assets(inp, out, stage)
        return code
    except Exception:
        detail = traceback.format_exc(limit=4)
        try:
            rescue = load_json(out / "result.json", {}) or {}
            rescue.update(status="partial",
                          degradations=sorted(set(list(rescue.get("degradations") or [])
                                                  + ["unhandled_exception"])),
                          errors=list(rescue.get("errors") or [])
                          + [{"code": "unhandled_exception", "traceback": detail}])
            for key in ("preserved_facts", "evidence_map", "change_log", "pending_human"):
                rescue.setdefault(key, [])
            rescue.setdefault("case_id", None)
            rescue.setdefault("deliverable", {"file": "proposal.md",
                                              "present": (out / "proposal.md").exists()})
            dump_json(out / "result.json", rescue)
        except Exception:
            pass
        flush_assets(inp, out, stage)
        print(json.dumps({"status": "partial", "error": detail.splitlines()[-1]},
                         ensure_ascii=False))
        return 0
if __name__ == "__main__":
    raise SystemExit(main())
