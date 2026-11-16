"""通路口令：init / show / check / build / selftest。谁是谁的实体、哪条是激活，由 Agent 读完
材料写进 plan.json；本脚本只做机器能做的事——切材料、比引文、排图导出、落 result.json。"""
import argparse
import json
import platform
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import material_audit as MA
import figure_paint as PT
import figure_audit as AU
import png_canvas as PNG

SKILL, VERSION = "pathway-mechanism-drawer", "1.0.0"

# 契约字段别名：只用于取值，不改键名、不漏键
CANON = {"editable_source": ("editable_source", "source_file", "svg", "editable_svg",
                             "diagram_source"),
         "export_artifact": ("export_artifact", "export", "exports", "pdf", "rendered_output"),
         "content_map": ("content_map", "element_map", "traceability"),
         "compliance_checks": ("compliance_checks", "compliance", "checks", "qa_checks"),
         "exceptions": ("exceptions", "issues", "warnings")}
LAYERS = ["background", "title", "zones", "entities", "relations", "legend", "notes"]


def contract_names(case):
    oc = case.get("output_contract") if isinstance(case, dict) else None
    if oc is None and isinstance(case, dict):
        oc = MA.deep_find(case, ["outputcontract", "outputfields", "requiredfields"])
    if isinstance(oc, dict):
        return list(oc.keys())
    if isinstance(oc, (list, tuple)):
        return [str(x) for x in oc]
    return [x.strip() for x in re.split(r"[,\n;]+", oc) if x.strip()] if isinstance(oc, str) else []


def emit_result(out, case, status, values):
    """把 output_contract 声明过的字段原样回填（缺值 None），再补固定状态块。"""
    names = contract_names(case)
    res = {}
    for nm in names:
        k = MA.norm_key(nm)
        val = None
        for canon, alts in CANON.items():
            if k in [MA.norm_key(a) for a in alts] and values.get(canon) is not None:
                val = values[canon]
                break
        res[nm] = val if val is not None else values.get(k)
    for k, v in values.items():
        res.setdefault(k, v)
    res["case_id"] = values.get("case_id") or ((case or {}).get("case_id")
                                               if isinstance(case, dict) else None)
    res["status"] = status
    for k in ("sources", "uncertainty", "pending_human", "errors", "degradations", "changes"):
        res.setdefault(k, [])
    res.setdefault("runtime", {})
    res["skill"] = {"name": SKILL, "version": VERSION}
    res["contract_fields"] = {"declared": names,
                              "filled": [n for n in names if res.get(n) is not None],
                              "null_fields": [n for n in names if res.get(n) is None]}
    MA.write_json(Path(out) / "result.json", res)
    return res


def src_rows(mats):
    return [{k: m[k] for k in ("rel", "kind", "blocks", "note", "bytes")} for m in mats]


def cmd_init(a):
    t0, out, work = time.time(), Path(a.output), Path(a.work)
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    case = MA.case_of(a.input)
    mats, corpus = MA.scan(a.input)
    MA.write_json(work / "materials.json", {"generated": MA.stamp(), "materials": mats,
                                           "corpus_blocks": len(corpus)})
    MA.write_json(work / "plan.skeleton.json", {
        "title": "", "subtitle": "",
        "compartments": [{"id": "extracellular", "label": "Extracellular", "order": 0},
                         {"id": "membrane", "label": "Plasma membrane", "order": 1},
                         {"id": "cytoplasm", "label": "Cytoplasm", "order": 2},
                         {"id": "nucleus", "label": "Nucleus", "order": 3}],
        "entities": [], "relations": [], "legend_extra": [], "gaps": [],
        "hint": "entities[].evidence.quote 填材料原文逐字切片（>=6 字符）；relations[] 填 "
                "source/target 的实体 id + type，然后 check、build"})
    emit_result(out, case, "input_error" if case is None else "partial",
                {"case_id": (case or {}).get("case_id"), "sources": src_rows(mats),
                 "uncertainty": ["还没有 plan.json，图未生成"],
                 "pending_human": ["读材料、写 plan.json，然后 build"],
                 "errors": [] if case is not None else ["在 %s 下找不到可解析的 case.json" % a.input],
                 "editable_source": None, "export_artifact": None, "content_map": None,
                 "compliance_checks": None, "exceptions": [],
                 "runtime": {"stage": "init", "seconds": round(time.time() - t0, 2),
                             "python": platform.python_version()}})
    print("materials %d | contract: %s" % (len(mats), ", ".join(contract_names(case)) or "none"))
    for m in mats:
        print("  %-40s %-6s %7dB blocks=%d %s%s" % (
            m["rel"][:40], m["kind"], m["bytes"], m["blocks"],
            m["locators"][0] if m["locators"] else "-",
            ("  NOTE: " + m["note"]) if m["note"] else ""))
    print("next: show --doc <材料> -> 写 %s -> check -> build" % (work / "plan.json"))
    return 0


def cmd_show(a):
    md = (MA.read_json(Path(a.work) / "materials.json")
          or MA.read_json(Path(a.output) / "materials.json") or {})
    mats = md.get("materials") or []
    sel = [m for m in mats if not a.doc or a.doc.lower() in m["rel"].lower()]
    if not sel:
        print("没有匹配 %r 的材料；可选：%s" % (a.doc, [m["rel"] for m in mats]))
        return 0
    for m in sel:
        blocks, note = MA.blocks_of(Path(m["path"]))
        print("### %s (%s, %d blocks)%s" % (m["rel"], m["kind"], len(blocks),
                                           (" - " + note) if note else ""))
        shown = 0
        for loc, t in blocks:
            if not a.locator or a.locator in loc:
                print("\n[%s]\n%s" % (loc, t[:1600]))
                shown += 1
        if a.locator and not shown:
            print("locator %r 不在这份材料里" % a.locator)
    return 0


def cmd_check(a):
    case = MA.case_of(a.input)
    _m, corpus = MA.scan(a.input)
    plan, src, err = MA.load_plan(a.work, a.output)
    if plan is None:
        MA.write_json(Path(a.work) / "check_report.json", {"ok": False, "error": err})
        print("没有可用的 plan（%s）" % err)
        return 0
    rep = MA.validate(plan, corpus, case)
    rep["plan_file"] = src
    MA.write_json(Path(a.work) / "check_report.json", rep)
    c = rep["counts"]
    print("entities %d (verified %d) | relations %d (verified %d, drawn %d) | rejected %d | "
          "pending %d" % (c["entities"], c["entities_verified"], c["relations"],
                          c["relations_verified"], c["relations_drawn"], c["rejected_quotes"],
                          c["pending_items"]))
    print("workorder gaps: elements=%s relations=%s"
          % (rep["missing_required_elements"] or "none",
             rep["missing_required_relations"] or "none"))
    for i in rep["issues"][:12]:
        print("  ISSUE  %s" % i)
    for r in rep["rejected"][:8]:
        print("  REJECT %s %s: 引文未逐字命中 -> %r" % (r["kind"], r["id"], r["quote"]))
    print("CLEAN" if rep["ok"] else "NOT CLEAN - 改引文，或把缺口明确留在 pending（不会进图）")
    return 0


def cmd_build(a):
    t0, out, work = time.time(), Path(a.output), Path(a.work)
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    logs = ["%s  INFO  build start argv=%s" % (MA.stamp(), " ".join(sys.argv[1:]) or "build")]
    case = MA.case_of(a.input)
    no_case = case is None
    mats, corpus = MA.scan(a.input)
    errs, degr, uncer, pend = [], [], [], []
    emit_result(out, case, "partial", {
        "case_id": (case or {}).get("case_id"), "sources": src_rows(mats),
        "uncertainty": ["渲染尚未完成"], "pending_human": [], "errors": [],
        "degradations": ["渲染前先落一版 partial result.json"], "editable_source": None,
        "export_artifact": None, "content_map": None, "compliance_checks": None, "exceptions": [],
        "runtime": {"stage": "build:partial", "seconds": round(time.time() - t0, 2)}})
    logs.append("%s  INFO  渲染前已写 partial result.json" % MA.stamp())

    plan, src, perr = MA.load_plan(work, out)
    status = "ok"
    if plan is None:
        plan, status = MA.fallback_plan(case, mats, corpus, PT.edge_kind), "partial"
        degr.append("plan.json 不可用（%s）：改用输入原字符串的兜底图" % perr)
        pend.append("读材料、用 plan.json 取代兜底后重建")
        logs.append("%s  WARN  无 plan.json（%s）-> 兜底" % (MA.stamp(), perr))
    else:
        logs.append("%s  INFO  plan 来自 %s" % (MA.stamp(), src))
    rep = MA.validate(plan, corpus, case)
    c = rep["counts"]
    logs.append("%s  INFO  validate entities=%d relations=%d rejected=%d pending=%d"
                % (MA.stamp(), c["entities"], c["relations"], c["rejected_quotes"],
                   c["pending_items"]))
    if rep["rejected"]:
        status = "partial"
        uncer += ["引文未逐字命中，该项不进图：%s %s -> %r"
                  % (r["kind"], r["id"], r["quote"]) for r in rep["rejected"][:15]]
        degr.append("%d 条引文无法回查，相关关系不绘制（见 content_map.pending）"
                    % len(rep["rejected"]))
    if rep["missing_required_elements"] or rep["missing_required_relations"]:
        status = "partial"
        pend.append("工单缺口：elements=%s relations=%s"
                    % (rep["missing_required_elements"], rep["missing_required_relations"]))
    if rep["pending"]:
        pend.append("%d 条关系待定：%s" % (len(rep["pending"]),
                                          ", ".join(x["id"] for x in rep["pending"][:8])))
    if c.get("items_without_quote"):
        status = "partial"
        degr.append("%d 个元素没有证据引文" % c["items_without_quote"])
        pend.append("给 plan.json 里每个实体/关系补一条逐字引文")

    draw = {"title": plan.get("title"), "subtitle": plan.get("subtitle"),
            "compartments": plan.get("compartments") or [],
            "entities": [e for e in (plan.get("entities") or []) if isinstance(e, dict)],
            "relations": [dict(r) for r in (plan.get("relations") or []) if isinstance(r, dict)
                          and r.get("evidence_status") != "unverified"],
            "gaps": plan.get("gaps") or [], "pending": plan.get("pending") or []}
    values = {"case_id": (case or {}).get("case_id"), "counts": c, "sources": src_rows(mats),
              "uncertainty": uncer + [MA.squeeze(g) for g in (plan.get("gaps") or [])][:6],
              "pending_human": pend, "errors": errs, "degradations": degr,
              "changes": plan.get("edits") or []}
    meta = {"title": plan.get("title") or "Biological mechanism figure",
            "byline": "泳道自上游到下游：细胞外 → 细胞膜 → 细胞质 → 细胞核",
            "desc": "mechanism figure; 7 layers: background/title/zones/entities/relations/"
                    "legend/notes",
            "footer": "source: %s | figure.svg 可编辑，figure.pdf / .png 是导出件"
                      % (", ".join(m["rel"] for m in mats[:4]) or "input")}
    try:
        st = PT.relay(draw, meta)
    except Exception as exc:
        errs.append("渲染失败：%s: %s" % (type(exc).__name__, exc))
        emit_result(out, case, "input_error", dict(values, errors=errs,
                                                   degradations=degr + ["未写出图稿"]))
        print(errs[0])
        return 0

    svg_path, pdf_path = out / "figure.svg", out / "figure.pdf"
    svg_path.write_text(st["svg"], encoding="utf-8")
    pdf_path.write_bytes(st["pdf"])
    png_info = PNG.render(Path(out) / "figure.png", st["items_list"], st["width"],
                          st["height"])
    if not png_info.get("magic"):
        degr.append("PNG 预览未生成（%s），figure.pdf 作为检视件" % png_info.get("error", "未知"))
    s, pdf, p = st["svg"], st["pdf"], st["plan"]
    logs.append("%s  INFO  rendered svg=%dB pdf=%dB png=%sB entities=%d relations=%d crossings=%d"
                % (MA.stamp(), len(s.encode("utf-8")), len(pdf), png_info.get("bytes", 0),
                   st["entities"], st["relations"], st.get("crossings", -1)))

    cmap = MA.content_map(plan, p, st, c, rep, LAYERS)
    MA.write_json(out / "content_map.json", cmap)
    MA.write_json(out / "plan.normalized.json", p)
    pj = PT.probe_pdf(pdf)
    pj["lost"] = st["pdf_chars_lost"]
    svg_info = MA.read_svg(s)
    for e in cmap["entities"]:
        e["drawn"] = e["svg_id"][1:] in svg_info.get("entities", {})
    ev = {"verified": c["entities_verified"] + c["relations_verified"],
          "rejected": c["rejected_quotes"], "pending": c["pending_items"],
          "coverage_pct": round(100.0 * (c["entities_verified"] + c["relations_verified"])
                                / max(1, c["entities"] + c["relations"]), 1)}
    sc = AU.self_check({"svg": svg_info, "svg_bytes": s.encode("utf-8"), "pdf_bytes": pdf,
                        "pdf_info": pj, "png_info": png_info,
                        "map_entities": len(cmap["entities"]),
                        "map_relations": len(cmap["relations"]), "evidence": ev,
                        "declared": contract_names(case), "contract_missing": [],
                        "hits": st.get("hits", 0), "crossings": st.get("crossings", 0),
                        "stats": st, "heads": {t: PT.EDGE[t][2] for t in st.get("types", [])},
                        "kinds": {"ent-%s" % PT.sid(e["id"]): e["kind"] for e in p["entities"]},
                        "cli_probes": MA.read_json(work / "cli_probes.json") or {}})
    compl = sc["compliance"]
    MA.write_json(out / "compliance_checks.json", compl)
    AU.write_json(out / "self_check.json", sc)
    if not pdf.startswith(b"%PDF-") or no_case:
        status = "input_error"
    values.update({
        "editable_source": {"path": str(svg_path), "file": str(svg_path),
                            "format": "SVG 1.1（分层、文字为 <text>、基因斜体）",
                            "width_px": st["width"], "height_px": st["height"], "layers": LAYERS,
                            "text_count": s.count("<text"), "bytes": len(s.encode("utf-8")),
                            "sha256": _sha(svg_path)},
        "export_artifact": {"png": {"path": png_info.get("path"), "width": png_info.get("width"),
                                    "height": png_info.get("height"), "dpi": 96,
                                    "engine": png_info.get("engine"),
                                    "bytes": png_info.get("bytes")},
                            "pdf": {"path": str(pdf_path), "pages": pj.get("pages"),
                                    "vector": True, "engine": "stdlib base-14 Helvetica",
                                    "bytes": pdf_path.stat().st_size},
                            "file": str(pdf_path)},
        "content_map": {"file": str(out / "content_map.json"),
                        "entries": len(cmap["entities"]) + len(cmap["relations"]),
                        "entities": len(cmap["entities"]), "relations": len(cmap["relations"]),
                        "pending": len(cmap.get("pending") or [])},
        "compliance_checks": {"file": str(out / "compliance_checks.json"),
                              "summary": compl["verdict"], "pass": compl["pass"]},
        "exceptions": [{"kind": "degradation", "detail": d} for d in degr]
                      + [{"kind": "pending_human", "detail": q} for q in pend],
        "runtime": {"stage": "build", "seconds": round(time.time() - t0, 2),
                    "python": platform.python_version(), "plan_source": src or "fallback",
                    "renderer": "figure_paint.py + png_canvas.py", "argv": sys.argv[1:],
                    "layout": {"order_choice": st.get("order_choice"),
                               "line_crossings": st.get("crossings"),
                               "connectors_through_boxes": st.get("hits")}}})
    gdoc = AU.expectation(case, plan, rep, st, ROOT)
    AU.write_json(out / "golden_standard.json", gdoc)
    md, dsum = AU.compare(gdoc, svg_info, p, st)
    (out / "diff_report.md").write_text(md, encoding="utf-8")
    (out / "version_history.md").write_text(
        AU.history(case, status, {"entities": st["entities"], "relations": st["relations"],
                                  "zones": len(st.get("zones", []))}, dsum, degr), encoding="utf-8")
    logs += ["%s  INFO  golden entities=%d relations=%d rules=%d quotes=%d/%d"
             % (MA.stamp(), gdoc["counts"]["entities"], gdoc["counts"]["relations"],
                gdoc["counts"]["rules"], gdoc["counts"]["evidence_verified"],
                gdoc["counts"]["evidence_items"]),
             "%s  INFO  diff verdict=%s coverage=%s%%"
             % (MA.stamp(), dsum["verdict"], dsum["coverage_pct"]),
             "%s  INFO  self_check all_pass=%s failures=%s"
             % (MA.stamp(), sc["verdict"]["all_pass"], sc["verdict"]["failures"] or "none"),
             "%s  INFO  pdf probe pages=%s tj=%d xref_ok=%s"
             % (MA.stamp(), pj.get("pages"), pj.get("tj", 0), pj.get("xref_ok")),
             "%s  DONE  build %.2fs status=%s" % (MA.stamp(), time.time() - t0, status)]
    (out / "run.log").write_text("\n".join(logs) + "\n", encoding="utf-8")

    written = MA.read_json(out / "result.json") or {}
    values.update({
        "golden_standard": {"file": str(out / "golden_standard.json"),
                            "bytes": (out / "golden_standard.json").stat().st_size},
        "diff_report": {"file": str(out / "diff_report.md"),
                        "bytes": (out / "diff_report.md").stat().st_size,
                        "verdict": dsum.get("verdict")},
        "version_history": {"file": str(out / "version_history.md"),
                            "bytes": (out / "version_history.md").stat().st_size},
        "self_check": {"file": str(out / "self_check.json"),
                       "bytes": (out / "self_check.json").stat().st_size,
                       "all_pass": sc["verdict"].get("all_pass")},
        "run_log": {"file": str(out / "run.log"), "bytes": (out / "run.log").stat().st_size},
        "contract_completeness": {"declared": contract_names(case),
                                  "missing": [n for n in contract_names(case) if written.get(n) is None]},
        "raster_preview": {"file": png_info.get("path"), "engine": png_info.get("engine")}})
    final = emit_result(out, case, status, values)
    print("status=%s entities=%d relations=%d zones=%s types=%s"
          % (status, st["entities"], st["relations"],
             ",".join(z["id"] for z in st.get("zones", [])), ",".join(st.get("types", []))))
    print("svg %dB | pdf %dB | png %sB | content_map %d | checks pass=%s"
          % (svg_path.stat().st_size, pdf_path.stat().st_size, png_info.get("bytes") or 0,
             len(cmap["entities"]) + len(cmap["relations"]), compl["pass"]))
    print("contract missing: %s" % (final["contract_fields"]["null_fields"] or "none"))
    return 0


def _sha(path):
    import hashlib
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except Exception:
        return None


def _brief(p):
    rj = MA.read_json(p) or {}
    svg = Path(p).parent / "figure.svg"
    png = Path(p).parent / "figure.png"
    return {"result_json": bool(rj), "status": rj.get("status"),
            "svg": svg.is_file(), "svg_bytes": svg.stat().st_size if svg.is_file() else 0,
            "png_magic": png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" if png.is_file() else False,
            "contract_null": (rj.get("contract_fields") or {}).get("null_fields")}


def cmd_selftest(a):
    """真跑 CLI 探针（subprocess），把真实退出码与产物情况记下来。"""
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    probe, me, res = work / "_probe", str(Path(__file__).resolve()), {}
    t = subprocess.run([sys.executable, "-B", me, "--help"], capture_output=True, text=True,
                       timeout=60)
    res["help"] = {"exit_code": t.returncode, "usage_printed": "usage:" in (t.stdout + t.stderr).lower()}
    for key, payload in (("empty_input", None), ("bad_json", "{not json,,]")):
        d = probe / key
        d.mkdir(parents=True, exist_ok=True)
        if payload:
            (d / "case.json").write_text(payload, encoding="utf-8")
        t = subprocess.run([sys.executable, "-B", me, "build", "--input", str(d),
                            "--output", str(probe / (key + "_o")),
                            "--work", str(probe / (key + "_w"))],
                           capture_output=True, text=True, timeout=300)
        row = _brief(probe / (key + "_o") / "result.json")
        row["exit_code"] = t.returncode
        res[key] = row
    res["pass"] = (res["help"]["exit_code"] == 0 and res["help"]["usage_printed"]
                   and all(res[k]["exit_code"] == 0 and res[k]["result_json"] and res[k]["svg"]
                           for k in ("empty_input", "bad_json")))
    MA.write_json(work / "cli_probes.json", res)
    for k in ("help", "empty_input", "bad_json"):
        print("%-12s %s" % (k, json.dumps(res[k], ensure_ascii=False)))
    print("selftest pass=%s (探针记录在 %s)" % (res["pass"], work / "cli_probes.json"))
    return 0


def main():
    ap = argparse.ArgumentParser(
        prog="pathway-mechanism-drawer",
        description="init 索引材料 -> Agent 写 plan.json -> check 验引文 -> build 出 1600x1000 "
                    "分层 SVG + 单页 PDF + 真实 PNG；任何情况退出码 0 并留下合法 result.json。")
    ap.add_argument("--version", action="version", version="%s %s" % (SKILL, VERSION))
    ap.add_argument("--input", default="/input", help="输入目录（默认 /input）")
    ap.add_argument("--output", default="/app/output", help="产物目录（默认 /app/output）")
    ap.add_argument("--work", default="/app/work", help="工作目录（默认 /app/work）")
    sub = ap.add_subparsers(dest="cmd")
    for nm, hlp in (("init", "索引材料并先写一版 partial result.json"),
                    ("show", "带 locator 打印材料原文"),
                    ("check", "校验 plan.json 的引文、id 与工单覆盖"),
                    ("build", "出 SVG/PDF/PNG + content_map + 5 个可核验资产 + result.json"),
                    ("selftest", "真跑 --help / 空输入 / 坏 JSON 三个探针")):
        sp = sub.add_parser(nm, help=hlp)
        sp.add_argument("--input", default="/input")
        sp.add_argument("--output", default="/app/output")
        sp.add_argument("--work", default="/app/work")
        if nm == "show":
            sp.add_argument("--doc", default="", help="材料名子串")
            sp.add_argument("--locator", default="", help="如 para3 / stream2")
    a = ap.parse_args()
    if not a.cmd:
        ap.print_help()
        return 0
    for p in (a.output, a.work):
        try:
            Path(p).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    try:
        return {"init": cmd_init, "show": cmd_show, "check": cmd_check,
                "build": cmd_build, "selftest": cmd_selftest}[a.cmd](a)
    except SystemExit:
        return 0
    except Exception as exc:
        tb = traceback.format_exc()
        try:
            case = MA.read_json(MA.find_case(a.input)) if a.input else None
            emit_result(a.output, case, "input_error", {
                "case_id": (case or {}).get("case_id"),
                "errors": ["%s: %s" % (type(exc).__name__, exc)],
                "degradations": ["未捕获异常，已写 partial result.json"],
                "uncertainty": ["本次运行在产物齐备前中断"],
                "editable_source": None, "export_artifact": None, "content_map": None,
                "compliance_checks": None, "exceptions": [{"kind": "error", "detail": str(exc)}],
                "runtime": {"stage": a.cmd, "traceback_tail": tb.strip().splitlines()[-3:]}})
        except Exception:
            pass
        print("已从 %s 恢复：%s" % (type(exc).__name__, exc))
        return 0


if __name__ == "__main__":
    sys.exit(main())
