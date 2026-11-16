#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mindmap_cli.py — 材料 → 思维导图 主流程入口：init / show / check / build。

分工：Agent 写工作稿（theme + nodes + edges + 逐字证据），脚本负责索引、核验、渲染与回填。
纯标准库、不联网、不依赖 CWD；四个子命令退出码恒为 0，异常一律落成合法 result.json。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import audit          # noqa: E402
import assets         # noqa: E402
import mmcore         # noqa: E402
import mmio           # noqa: E402
from mmio import (IN, WK, OUT, SKILL_ID, build_index, ensure, find_case,  # noqa: E402
                  load_contract, semantic)

T0 = time.time()

ROLES = {"mindmap.svg": "主产物：可编辑导图", "mindmap.json": "结构真源与证据",
         "mindmap_preview.png": "预览位图", "node_evidence.csv": "节点→locator/quote",
         "coverage_report.md": "覆盖与结构说明", "pending_human.json": "待人工确认",
         "golden_standard.json": "金标准与出处", "audit_report.json": "对照与自检",
         "diff_report.md": "金标准逐项对照", "version_history.md": "版本史与回退方式",
         "run.log": "真实运行日志", "self_check.json": "机器自检断言"}
DELIVERY = ("mindmap.svg", "mindmap.json", "mindmap_preview.png", "node_evidence.csv",
            "coverage_report.md", "pending_human.json", "golden_standard.json",
            "audit_report.json", "diff_report.md", "version_history.md",
            "self_check.json", "run.log")
ASSET_NAMES = ("golden_standard.json", "diff_report.md", "version_history.md",
               "run.log", "self_check.json")


def base_result(cid, status="partial"):
    return {"case_id": cid, "status": status, "sources": [], "uncertainty": [], "pending_human": [],
            "errors": [], "degradations": [], "changes": [], "runtime": {}, "artifacts": [],
            "coverage": {}}


def closing(note=None):
    out = {"skill": SKILL_ID, "seconds": round(time.time() - T0, 1), "python": sys.version.split()[0]}
    if note:
        out["note"] = note
    return out


def source_list(index):
    return [{"id": m["id"], "name": m["name"], "kind": m["kind"], "path": m["path"],
             "bytes": m["bytes"], "sha1": m["sha1"], "units": len(m["units"]),
             "extractor": m["extractor"]} for m in index.get("materials") or []]


def flag_input(case, case_path, result):
    """输入问题必须写进 errors/degradations，而不是静默退化成空契约。"""
    if case_path and not case:
        result["errors"].append("%s 无法解析为 JSON 对象：契约字段退化为空表，主题退化为材料标题"
                                % Path(case_path).name)
    elif not case_path:
        result["degradations"].append("未找到 case.json：按材料标题与空契约继续")


def skeleton_context(note):
    return {"case_id": None, "files": [], "note": note,
            "deliverable": {"summary": note, "files": []}, "evidence_map": [],
            "preserved_facts": [], "change_log": [], "content_map": {}, "mindmap": {"file": None},
            "preview": None, "coverage": {}}


# ---------------------------------------------------------------- init
def cmd_init(args):
    ensure(WK)
    ensure(OUT)
    case, case_path = find_case()
    contract = load_contract(case)
    cid = case.get("case_id") or case.get("id") or semantic(case, r"case_?id|^id$")
    result = base_result(cid, "partial")
    flag_input(case, case_path, result)
    context = skeleton_context("init：索引完成，导图待 build")
    context["case_id"] = cid
    mmcore.finalize(result, contract, context, OUT / "result.json", closing("init 落盘"))
    index = build_index(case, contract, case_path)
    mmcore.dump(WK / "index.json", index)
    draft_path = WK / "mindmap.json"
    if not (mmcore.read_json(draft_path) or {}).get("nodes"):
        mmcore.dump(draft_path, {
            "schema": "mindmap/1.0", "case_id": cid,
            "_instructions": "填 theme.label、nodes[]、edges[]；每节点至少一条 evidence{material,locator,quote}，"
                             "quote 必须逐字复制材料原文；层级用 parent；edges 只写跨分支关系，无证据不画。",
            "theme": {"id": "root", "label": "", "evidence": []},
            "nodes": [], "edges": [],
            "_materials": [{"id": m["id"], "name": m["name"], "kind": m["kind"],
                            "units": len(m["units"])} for m in index["materials"]]})
    result["sources"] = source_list(index)
    for mat in index["materials"]:
        if not mat["text_available"]:
            result["uncertainty"].append("%s（%s）无可抽取文本" % (mat["name"], mat["kind"]))
        elif "raw-stream" in str(mat["extractor"]):
            result["uncertainty"].append("%s 页码为估计值（无文本层，走流解析）" % mat["name"])
    result["changes"] = [{"action": "init", "detail": "索引 %d 份材料，落 v0 骨架" % len(index["materials"])}]
    summary = audit.emit("init", cid=cid, case=case, contract=contract, index=index,
                         slots=mmcore.map_contract(contract, context), errors=result["errors"],
                         degradations=result["degradations"], do_probe=not args.no_probe,
                         out=OUT, work=WK)
    payload = mmcore.finalize(result, contract, context, OUT / "result.json", closing("init 完成"),
                              {"golden_standard": summary.get("golden_standard") or {},
                               "audit_report": summary.get("audit_report") or {},
                               "diff_report": summary.get("diff_report") or {},
                               "version_history": summary.get("version_history") or {},
                               "run_log": summary.get("run_log") or {},
                               "self_check": summary.get("self_check") or {},
                               "verifiable_assets": summary.get("verifiable_assets") or []})
    final = assets.finalize_selfcheck(OUT, WK, cid, "init", payload, None, contract,
                                      mmcore.map_contract(contract, context))
    if isinstance(final, dict) and final.get("path"):
        payload["self_check"] = final
        payload["verifiable_assets"] = assets.asset_index(OUT)
        mmcore.dump(OUT / "result.json", payload)
    print("== init | case_id=%s | 材料 %d 份 | 文本 %d 字" % (index.get("case_id"),
                                                            len(index["materials"]), index.get("total_chars")))
    if index.get("instruction"):
        print("[任务] " + str(index["instruction"])[:500])
    keys = list(index.get("contract") or {})
    print("[契约] %s（共 %d 项，全部原样回填）" % (", ".join(keys) or "无", len(keys)))
    for mat in index["materials"]:
        print("%-4s %-6s %7dB u=%-3d %s%s" % (mat["id"], mat["kind"], mat["bytes"], len(mat["units"]),
                                              mat["name"], "" if mat["units"] else "  (无文本)"))
        if mat["units"]:
            print("     [%s] %s" % (mat["units"][0]["locator"],
                                    re.sub(r"\s+", " ", mat["units"][0]["text"])[:100]))
    print("[下一步] show --material M1 → 写 %s → check → build" % draft_path)
    return 0


# ---------------------------------------------------------------- show
def cmd_show(args):
    index = mmcore.read_json(WK / "index.json")
    if not isinstance(index, dict):
        print("缺 index.json，请先运行 init")
        return 0
    materials = index.get("materials") or []
    picked = [m for m in materials if args.material in (m["id"], m["name"], m.get("path"))] \
        if args.material else materials
    if not picked:
        print("未找到 %s；可选：%s" % (args.material, ", ".join(m["id"] for m in materials)))
        return 0
    budget = args.max_chars
    for mat in picked:
        print("### %s · %s · %s · %d units" % (mat["id"], mat["name"], mat["kind"], len(mat["units"])))
        window = [u for u in mat["units"]
                  if not args.grep or args.grep.lower() in (u["text"] or "").lower()]
        window = window[max(0, args.start - 1):max(0, args.start - 1) + args.limit]
        if not window:
            print("  (无匹配单元)")
        for unit in window:
            if budget <= 0:
                print("  ... 已达 --max-chars 上限，用 --start 继续")
                return 0
            text = (unit["text"] or "")[:min(1200, budget)]
            budget -= len(text)
            print("\n[%s] %s" % (unit["locator"], text))
    return 0


# ---------------------------------------------------------------- check
def cmd_check(args):
    draft = mmcore.read_json(Path(args.work) if args.work else WK / "mindmap.json")
    index = mmcore.read_json(WK / "index.json", {}) or {}
    if not isinstance(index, dict):
        index = {}
    report = audit.inspect(draft, index)
    mmcore.dump(WK / "check.json", {k: v for k, v in report.items() if k != "model"})
    stats = report["stats"]
    audit.note(WK, OUT, "check", "校验 nodes=%d errors=%d warnings=%d depth=%d"
               % (stats["nodes"], report["errors"], report["warnings"], stats["depth"]),
               "INFO" if report["ok"] else "WARN")
    if not report["model"]["nodes"]:
        report["model"] = mmcore.build_model(audit.scaffold(index), index)
        audit.note(WK, OUT, "check", "工作稿为空：已演示兜底稿可成图，正式产物请自行填写")
    print("== 校验：%s（errors=%d warnings=%d）"
          % ("通过" if report["ok"] else "未通过", report["errors"], report["warnings"]))
    for issue in report["issues"][:30]:
        print("  [%s] %s" % (issue["severity"], issue["message"]))
    print("节点 %d，带证据 %d（%.0f%%），引文命中 %d，未命中 %d，深度 %d"
          % (stats["nodes"], stats["verified_nodes"], 100 * stats["verified_ratio"],
             stats["verified_quotes"], stats["rejected_quotes"], stats["depth"]))
    print("结论：%s" % ("可 build" if report["ok"] else "先修 error 再 build（否则 status=partial）"))
    return 0


# ---------------------------------------------------------------- build
def cmd_build(args):
    ensure(WK)
    ensure(OUT)
    early = base_result(None, "partial")
    mmcore.finalize(early, {}, {"case_id": None, "files": [],
                                "deliverable": {"summary": "build 进行中，尚未成稿"}},
                    OUT / "result.json", closing("build 启动占位"))
    index = mmcore.read_json(WK / "index.json")
    if not isinstance(index, dict) or "materials" not in index:
        case, case_path = find_case()
        index = build_index(case, load_contract(case), case_path)
        mmcore.dump(WK / "index.json", index)
    contract = index.get("contract") or {}
    cid = index.get("case_id")
    draft_path = Path(args.work) if args.work else WK / "mindmap.json"
    draft = mmcore.read_json(draft_path)
    degraded = []

    case_chk, case_chk_path = find_case()
    shape = base_result(cid, "partial")
    flag_input(case_chk, case_chk_path, shape)
    input_errors = list(shape["errors"])
    degraded.extend([d for d in shape["degradations"] if d not in degraded])
    if not isinstance(draft, dict) or not draft.get("nodes"):
        draft, mode = audit.scaffold(index), "fallback"
        degraded.append("工作稿缺失/为空：改用确定性要点抽取兜底成稿")
    else:
        mode = "agent"
    report = audit.inspect(draft, index)
    model = report["model"]
    if not model["nodes"]:
        model = mmcore.build_model(audit.scaffold(index), index)
        mode = "fallback"
        degraded.append("工作稿节点全部无效：改用兜底抽取")
    if model["dropped"]:
        degraded.append("按规则丢弃 %d 条关系（端点/类型非法或无证据）" % len(model["dropped"]))
    if model["unverified"]:
        degraded.append("%d 个节点引文未命中材料：%s"
                        % (len(model["unverified"]), ", ".join(model["unverified"][:8])))
    if model["cycles"]:
        degraded.append("父子链异常：%s（已在布局中挂回 root）" % ", ".join(model["cycles"][:6]))

    geo = mmcore.compose(model)
    collisions = mmcore.collisions(geo["boxes"])
    verified = sum(1 for n in model["nodes"] for e in n["evidence"] if e["verified"])
    stamp = "%s | 节点 %d | 关系 %d | 核验证据 %d 条 | 材料 %d 份 | %s" % (
        SKILL_ID, len(model["nodes"]), len(model["edges"]), verified,
        len(index.get("materials") or []), "Agent 工作稿" if mode == "agent" else "脚本兜底")
    svg_text = mmio.to_svg(model, geo, stamp)
    (OUT / "mindmap.svg").write_bytes(svg_text.encode("utf-8"))
    preview = mmio.preview(OUT / "mindmap.svg", OUT / "mindmap_preview.png", model, geo)
    if preview["mode"] == "geometry-blocks":
        degraded.append("无 SVG 渲染器：预览为同源几何位图（色块+连线，无字形），"
                        "可编辑与阅读请用 mindmap.svg")
    elif preview["mode"] == "none":
        degraded.append("预览未生成：%s（SVG 仍可用）" % preview.get("note"))

    depth = max([n["level"] for n in model["nodes"]] or [0])
    structure = {"schema": "mindmap/1.0", "case_id": cid, "generator": SKILL_ID,
                 "source_mode": mode, "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "theme": model["theme"], "nodes": model["nodes"], "edges": model["edges"],
                 "dropped_edges": model["dropped"],
                 "layout": {"canvas": [geo["w"], geo["h"]],
                            "boxes": {k: [round(v, 1) for v in box] for k, box in geo["boxes"].items()},
                            "columns": len({n["level"] for n in model["nodes"]} | {0}),
                            "collisions": collisions},
                 "stats": {"nodes": len(model["nodes"]), "edges": len(model["edges"]),
                           "verified_evidence": verified, "depth": depth}}
    mmcore.dump(OUT / "mindmap.json", structure)

    ratio = sum(1 for n in model["nodes"] if n["verified"]) / max(1, len(model["nodes"]))
    problems = [f for f in ("mindmap.svg", "mindmap.json")
                if not (OUT / f).is_file() or not (OUT / f).stat().st_size]
    if "<text" not in svg_text:
        problems.append("SVG 无 text 元素")
    if collisions:
        problems.append("布局存在 %d 处重叠" % len(collisions))
    if problems:
        degraded.append("自检：%s" % "; ".join(problems))

    has_text = any(m["units"] for m in index.get("materials") or [])
    status = ("insufficient_evidence" if not has_text else
              "partial" if (mode == "fallback" or len(model["nodes"]) < 6 or ratio < 0.6
                            or problems) else "ok")
    evidence_rows = [{"node": n["id"], "material": e["material"], "locator": e["locator"],
                      "quote": e["quote"][:140], "type": n["status"], "evidence_id": e["id"],
                      "verified": e["verified"]}
                     for n in model["nodes"] for e in n["evidence"]][:400]
    context = {
        "case_id": cid, "files": [],
        "deliverable": {"summary": "%d 节点 / %d 跨分支关系 / %d 条逐字证据；主题「%s」"
                                   % (len(model["nodes"]), len(model["edges"]), verified,
                                      model["theme"]["label"]),
                        "primary": "mindmap.svg", "structure": "mindmap.json",
                        "preview": "mindmap_preview.png" if preview.get("mode") not in (None, "none") else None,
                        "evidence": "node_evidence.csv", "editable": True},
        "preview": "mindmap_preview.png" if preview.get("mode") not in (None, "none") else None,
        "evidence_map": evidence_rows, "preserved_facts": evidence_rows, "content_map": evidence_rows,
        "mindmap": {"file": "mindmap.json", "theme": model["theme"]["label"],
                    "nodes": len(model["nodes"]), "edges": len(model["edges"]), "depth": depth,
                    "branches": [n["label"] for n in model["nodes"] if n["parent"] == "root"]},
        "note": "build 完成：%d 节点 / %d 关系 / 核验证据 %d 条" % (len(model["nodes"]),
                                                              len(model["edges"]), verified),
        "change_log": [{"action": "build", "detail": "工作稿=%s；%d 节点/%d 关系；预览=%s"
                        % (mode, len(model["nodes"]), len(model["edges"]), preview.get("mode"))}],
        "uncertainty": (["层级与分支由 Agent 依据材料归纳（概括，非原文结构）"] if mode == "agent"
                        else ["结构来自兜底抽取，未表达论证层级"]),
        "coverage": {"materials": len(index.get("materials") or []), "nodes": len(model["nodes"]),
                     "edges": len(model["edges"]), "depth": depth, "verified_ratio": round(ratio, 3),
                     "verified_quotes": verified, "source_mode": mode}}
    context["uncertainty"] += ["%s（%s）无可抽取文本" % (m["name"], m["kind"])
                               for m in index.get("materials") or [] if not m["units"]]

    result = base_result(cid, status)
    result["sources"] = source_list(index)
    result["errors"] = input_errors
    result["coverage"] = context["coverage"]
    result["degradations"] = list(degraded)
    result["uncertainty"] = list(context["uncertainty"])
    result["changes"] = list(context["change_log"])
    result["pending_human"] = []
    if model["unverified"]:
        result["pending_human"].append("补证据或删除节点：%s" % ", ".join(model["unverified"][:8]))
    if model["dropped"]:
        result["pending_human"].append("未绘制关系待确认：%s" % "; ".join(
            "%s→%s(%s,%s)" % (d["from"], d["to"], d["type"], d["reason"]) for d in model["dropped"][:6]))
    if mode == "fallback":
        result["pending_human"].append("复核兜底导图：确认主题、合并同级、补逐字证据")

    summary = audit.emit("build", cid=cid, contract=contract, index=index, model=model,
                         svg_text=svg_text, slots=mmcore.map_contract(contract, context),
                         errors=result["errors"], degradations=degraded,
                         do_probe=not args.no_probe, mode=mode, png_info=preview,
                         out=OUT, work=WK)
    if (summary.get("self_check") or {}).get("pass") is False:
        degraded.append("自检未通过：%s（详见 audit_report.json）"
                        % (", ".join(summary["self_check"].get("failed") or []) or "unknown"))
        result["degradations"] = degraded
        if status == "ok":
            status = "partial"
            result["status"] = status
    if summary.get("error"):
        degraded.append("审计层降级：%s" % summary["error"])
        result["degradations"] = degraded

    files = [f for f in DELIVERY if (OUT / f).is_file() and (OUT / f).stat().st_size]
    context["files"] = files
    result["artifacts"] = [{"path": f, "bytes": (OUT / f).stat().st_size, "role": ROLES.get(f, f)}
                           for f in files]

    extra = {"editable_source": "mindmap.svg", "export_artifact": "mindmap_preview.png",
             "structure_file": "mindmap.json", "node_count": len(model["nodes"]),
             "edge_count": len(model["edges"]), "evidence_coverage": round(ratio, 3),
             "preview_mode": preview.get("mode"),
             "golden_standard": summary.get("golden_standard") or {},
             "audit_report": summary.get("audit_report") or {},
             "diff_report": summary.get("diff_report") or {},
             "version_history": summary.get("version_history") or {},
             "run_log": summary.get("run_log") or {},
             "self_check": summary.get("self_check") or {},
             "node_evidence": summary.get("node_evidence") or {},
             "coverage_report": summary.get("coverage_report") or {},
             "probes": summary.get("probes") or [],
             "verifiable_assets": summary.get("verifiable_assets") or []}
    payload = mmcore.finalize(result, contract, context, OUT / "result.json",
                              closing("build 完成：status=%s" % status), extra)
    final = assets.finalize_selfcheck(OUT, WK, cid, "build", payload, model, contract,
                                      mmcore.map_contract(contract, context))
    if isinstance(final, dict) and final.get("path"):
        if final.get("pass") is False:
            if payload.get("status") == "ok":
                payload["status"] = "partial"
            payload["degradations"] = list(payload.get("degradations") or []) + [
                "最终自检未通过：%s（详见 self_check.json）"
                % (", ".join(final.get("failed") or []) or "unknown")]
        payload["self_check"] = final
        payload["artifacts"] = [{"path": f, "bytes": (OUT / f).stat().st_size,
                                 "role": ROLES.get(f, f)}
                                for f in files if (OUT / f).is_file()]
        payload["verifiable_assets"] = assets.asset_index(OUT)
        mmcore.dump(OUT / "result.json", payload)
    print("== build | status=%s mode=%s nodes=%d edges=%d evidence=%d depth=%d preview=%s"
          % (status, mode, len(model["nodes"]), len(model["edges"]), verified, depth,
             preview.get("mode")))
    print("== 自检 | pass=%s checks=%s failed=%s"
          % ((summary.get("self_check") or {}).get("pass"),
             (summary.get("self_check") or {}).get("checks"),
             (summary.get("self_check") or {}).get("failed")))
    print("== 最终自检 | pass=%s checks=%s failed=%s"
          % ((final or {}).get("pass"), (final or {}).get("checks"),
             (final or {}).get("failed")))
    print("__END__")
    for name in files:
        print("  %-22s %8d B" % (name, (OUT / name).stat().st_size))
    for item in degraded:
        print("  [降级] " + item[:170])
    return 0


# ---------------------------------------------------------------- 入口
def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        prog="mindmap_cli.py",
        description="材料 → 可核验思维导图：init 建索引 → Agent 写工作稿 → check → build。",
        epilog="示例：python3 scripts/mindmap_cli.py init && python3 scripts/mindmap_cli.py build")
    sub = parser.add_subparsers(dest="cmd")
    p_init = sub.add_parser("init", help="扫描 /input、建索引、先落 partial result.json（无子命令时默认执行）")
    p_init.add_argument("--no-probe", dest="no_probe", action="store_true",
                        help="跳过空输入/坏 JSON/极小材料三个子进程探针（更快，自检会标注未探测）")
    p_show = sub.add_parser("show", help="按 locator 打印材料原文，供摘录逐字引文")
    p_show.add_argument("--material", default=None, help="材料 id（M1）或文件名")
    p_show.add_argument("--start", type=int, default=1, help="起始单元序号（1 起）")
    p_show.add_argument("--limit", type=int, default=12, help="本次最多打印几个单元")
    p_show.add_argument("--grep", default=None, help="只打印含该关键词的单元")
    p_show.add_argument("--max-chars", dest="max_chars", type=int, default=6000, help="本次字符预算")
    p_check = sub.add_parser("check", help="校验证据命中、层级、规模与粒度")
    p_check.add_argument("--work", default=None, help="工作稿路径（默认 /app/work/mindmap.json）")
    p_build = sub.add_parser("build", help="渲染 SVG/预览并写齐附件与 result.json")
    p_build.add_argument("--work", default=None, help="工作稿路径（默认 /app/work/mindmap.json）")
    p_build.add_argument("--no-probe", dest="no_probe", action="store_true",
                         help="跳过空输入/坏 JSON/极小材料三个子进程探针")
    args = parser.parse_args(argv)
    handler = {"init": cmd_init, "show": cmd_show, "check": cmd_check, "build": cmd_build}
    return handler[args.cmd or "init"](args)


def crash_report(exc):
    """极端情况下也要留下一份能读的 result.json，并保持退出码 0。"""
    try:
        ensure(OUT)
        case, _ = find_case()
        case = case if isinstance(case, dict) else {}
        contract = load_contract(case)
        cid = case.get("case_id") or case.get("id")
        result = base_result(cid, "input_error")
        result["errors"] = [str(exc)[:300]]
        result["degradations"] = ["主流程异常：已写最小合法 result.json，退出码仍为 0"]
        context = skeleton_context("运行时异常，已最小落盘")
        context["case_id"] = cid
        mmcore.finalize(result, contract, context, OUT / "result.json", closing("crash"))
        assets.ensure(OUT, cid, "crash")
    except Exception:
        pass


if __name__ == "__main__":
    code = 0
    try:
        code = main(sys.argv[1:])
    except SystemExit:
        code = 0
    except Exception as exc:
        print("mindmap_cli.py 内部异常（已捕获，退出码 0）：%s" % exc)
        crash_report(exc)
        code = 0
    sys.exit(code if isinstance(code, int) else 0)
