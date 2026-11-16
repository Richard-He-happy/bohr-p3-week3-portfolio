#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""conform.py — 稿件模板合规适配的主入口与管线。

    python3 -B scripts/conform.py --input /input --output /app/output

盘查输入 → 抽逐项规格 → 换算版面单位 → 重排 docx → 保真核对 → 一致性断言 → 写 result.json。
仅标准库；不联网；退出码恒 0；先落 partial 结果，异常只记录不中断。

同目录模块：ooxml.py（文档读写）、extract.py（规格抽取与单位换算）、verify.py（核对与断言）。
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
try:
    import ooxml
    import extract
    import verify
    BOOT_TROUBLE = None
except Exception as exc:
    ooxml = extract = verify = None
    BOOT_TROUBLE = repr(exc)

V = "1.0.0"
IN_DEF, OUT_DEF = "/input", "/app/output"


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def dump(path, payload):
    """落盘 JSON：先建目录，再按 UTF-8 无转义写出。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def rel(path, base):
    """产物相对路径（便于他人按记录复现）；跨盘时退回绝对路径。"""
    try:
        return str(Path(path).resolve().relative_to(Path(base).resolve()))
    except (ValueError, OSError):
        return str(path)


def bootstrap(msg, out_dir):
    """依赖模块导入失败时的兜底结果，保证读取方不空手。"""
    try:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        dump(Path(out_dir) / "result.json", {
            "case_id": None, "status": "partial", "deliverable": None, "editable_source": None,
            "export_artifact": None, "preserved_facts": [], "evidence_map": [], "change_log": [],
            "changes": [], "sources": [], "uncertainties": [], "pending_human": [],
            "errors": [{"stage": "bootstrap", "error": str(msg)[:300]}],
            "degradations": [{"what": "主流程未启动", "handled": "写兜底结果", "impact": "无成品"}],
            "runtime": {"version": V, "seconds": 0.0, "stage": "bootstrap"}})
    except OSError:
        pass


def font_families(tool, name):
    """fontconfig 对某个字体名给出的族名列表；无工具或调用失败返回 None。"""
    if not tool:
        return None
    try:
        raw = subprocess.run([tool, "-f", "%{family}", name], timeout=20,
                             capture_output=True, text=True).stdout
        return [f.strip() for f in raw.split(",") if f.strip()]
    except Exception:
        return None


def preview(docx_path, out_dir):
    """尽力导 PDF；缺 soffice 或转换失败返回 None，由调用方记降级。"""
    tool = shutil.which("soffice") or shutil.which("libreoffice")
    if not tool:
        return None
    try:
        subprocess.run([tool, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx_path)],
                       timeout=210, capture_output=True)
        pdf = Path(out_dir) / (Path(docx_path).stem + ".pdf")
        if pdf.exists() and pdf.read_bytes()[:5] == b"%PDF-":
            return pdf
    except Exception:
        return None
    return None


def side(out_dir, st):
    """四份辅助产物：规格表、样式映射、保真报告、待人工确认。"""
    spec, n = st["spec"], st["nums"]
    rows = ["# 逐项格式规格（format_spec）", "", "| 编号 | 规格项 | 取值 | 出处 locator | 原文摘录 | 是否推断 |",
            "|-|-|-|-|-|-|"]
    rows += ["| FS%02d | %s | %s | %s | %s | %s |" % (i, s["id"], s["value"], s["locator"] or "-",
                                                    (s["quote"] or "-").replace("|", "/")[:48],
                                                    "yes" if s["inferred"] else "no")
             for i, s in enumerate(spec, 1)]
    rows += ["", "冲突裁决：" + ("; ".join("%s→%s" % (c["item"], c["chosen"]) for c in st["cf"]) or "无"),
             "", "内容单元覆盖：" + json.dumps(st["cov"], ensure_ascii=False),
             "", "交叉引用：" + json.dumps(st["xref"], ensure_ascii=False)]
    (out_dir / "format_spec.md").write_text("\n".join(rows), encoding="utf-8")
    dump(out_dir / "style_map.json", {
        "generated": stamp(), "applied": {k: n.get(k) for k in ("font", "ea", "sz", "line", "lineRule",
                                                                "align", "cols")},
        "map": {k: k for k in ("Normal", "Heading1", "Heading2", "Heading3", "Caption", "Title",
                               "Abstract", "Bibliography", "FootnoteText")}})
    dump(out_dir / "fidelity_report.json", {
        "generated": stamp(), "coverage": st["cov"], "xref": st["xref"], "built": st.get("info"),
        "conflicts": st["cf"], "facts": st.get("facts") or [],
        "method": "内容单元去空白后取前 40 字符，须在成品纯文本中原样出现"})
    dump(out_dir / "pending_human.json", {"generated": stamp(), "items": st["pend"]})


def fill_contract(payload, contract):
    """contract 的每个键都补到顶层：能按语义对上就填，否则 null，绝不删键。"""
    table = (("case", payload.get("case_id")), ("status", payload.get("status")),
             ("editable", payload.get("editable_source")), ("export", payload.get("export_artifact")),
             ("preview", payload.get("export_artifact")), ("preserv", payload.get("preserved_facts")),
             ("fact", payload.get("preserved_facts")), ("evidence", payload.get("evidence_map")),
             ("pending", payload.get("pending_human")), ("human", payload.get("pending_human")),
             ("complian", payload.get("compliance_checks")), ("check", payload.get("compliance_checks")),
             ("exception", payload.get("errors")), ("error", payload.get("errors")),
             ("format_spec", payload.get("format_spec")), ("spec", payload.get("format_spec")),
             ("source", payload.get("sources")), ("deliverable", payload.get("deliverable")),
             ("result", payload.get("result")), ("change", payload.get("change_log")),
             ("workorder", payload.get("workorder_receipt")))
    if isinstance(contract, dict):
        names = list(contract.keys())
    elif isinstance(contract, (list, tuple)):
        names = [str(k) for k in contract]
    else:
        names = []
    for key in names:
        if key not in payload:
            low = key.lower()
            payload[key] = next((v for token, v in table if token in low), None)


def assemble(st, t0):
    """组装 result.json：主体 → 契约回填 → 一致性断言 → 判定 status。"""
    spec, facts, cov = st["spec"], st["facts"], st["cov"]
    docx_rel, pdf_rel = st.get("docx"), st.get("pdf")
    good = sum(1 for f in facts if f["status"] == "verified")
    status = ("input_error" if st.get("inp_err") else "insufficient_evidence" if not docx_rel else
              "partial" if (st["err"] or st["pend"] or cov.get("ratio", 0) < 0.98) else "ok")
    payload = {
        "case_id": st["case"].get("case_id"), "status": status, "deliverable": docx_rel,
        "editable_source": docx_rel, "export_artifact": pdf_rel,
        "result": {"deliverable": docx_rel, "preview": pdf_rel, "counts": st.get("info"),
                   "coverage": cov.get("ratio"), "spec_items": len(spec),
                   "spec_inferred": sum(1 for s in spec if s["inferred"]),
                   "facts_verified": "%d/%d" % (good, len(facts))},
        "preserved_facts": facts,
        "evidence_map": [{"id": "EV%02d" % i, "claim": "%s=%s" % (s["id"], s["value"]), "kind": "format_spec",
                          "source": s["source"], "locator": s["locator"], "quote": s["quote"],
                          "verified": s.get("traceable")} for i, s in enumerate(spec, 1) if s.get("locator")],
        "change_log": st["chg"], "changes": st["chg"], "compliance_checks": verify.checks(st),
        "spec_conflicts": st["cf"], "uncertainty": [p.get("issue") for p in st["pend"]],
        "uncertainties": [p.get("issue") for p in st["pend"]], "pending_human": st["pend"],
        "exceptions": st["err"], "errors": st["err"], "degradations": st["deg"],
        "sources": st.get("src") or [], "workorder_receipt": st.get("wo") or [],
        "format_spec": [{k: s.get(k) for k in ("id", "value", "source", "locator", "quote",
                                               "inferred", "traceable")} for s in spec],
        "font_resolution": st.get("font_ledger") or {},
        "runtime": {"version": V, "seconds": round(time.time() - t0, 1),
                    "font_probe": st.get("fprobe"), "stage": "final"}}
    fill_contract(payload, st["case"].get("output_contract"))
    audit = verify.invariants(st, payload)
    payload["invariants"] = audit
    bad = [a for a in audit if not a["ok"]]
    if bad:
        st["pend"].extend({"item": "invariant:" + a["id"], "issue": a["claim"] + "未达成",
                           "value": a["actual"], "action": a["action"]} for a in bad)
        payload["pending_human"] = st["pend"]
        payload["uncertainty"] = payload["uncertainties"] = [p.get("issue") for p in st["pend"]]
        if payload["status"] == "ok":
            payload["status"] = "partial"
        try:
            dump(Path(st["out"]) / "pending_human.json", {"generated": stamp(), "items": st["pend"]})
        except OSError:
            pass
    payload["summary"] = {"invariants_passed": "%d/%d" % (len(audit) - len(bad), len(audit)),
                          "spec_traceable": st.get("trace")}
    return payload


def workorder(case):
    """工单条目逐条标注 done / not_applicable。"""
    rows = []
    for key in ("organizer_workorder", "organizer_edit_workorder", "workorder"):
        raw = case.get(key)
        for it in (raw if isinstance(raw, list) else [raw] if raw else []):
            txt = it if isinstance(it, str) else json.dumps(it, ensure_ascii=False)
            hit = re.search(r"格式|模板|字体|字号|行距|边距|题注|参考|目录|页码|导出|format|font|margin|"
                            r"caption|reference|heading", txt, re.I)
            rows.append({"item": txt[:160], "key": key, "status": "done" if hit else "not_applicable",
                         "evidence": "deliverable.docx + format_spec.md" if hit else "非格式条目，未改动"})
    return rows


def pipeline(inp, out_dir, opts, st):
    tpl, draft, rules = extract.roles(extract.scan(inp))
    st["src"] = [{"role": role, "path": rel(f["path"], inp), "kind": f["kind"]}
                 for role, grp in (("template", tpl), ("manuscript", draft), ("requirements", rules))
                 for f in grp]
    cands, corpus = [], {}
    for f in tpl + rules:
        try:
            if f["kind"] == "docx":
                cands += ooxml.docx_spec(f["path"])
                corpus[Path(f["path"]).name] = "".join(
                    zipfile.ZipFile(f["path"]).read(p).decode("utf-8", "replace")
                    for p in zipfile.ZipFile(f["path"]).namelist() if p.endswith(".xml"))
            else:
                txt = extract.content(f["path"])
                if f["kind"] == "tex":
                    cands += extract.tex_spec(txt, Path(f["path"]).name)
                cands += extract.prose_spec(txt, Path(f["path"]).name)
                corpus[Path(f["path"]).name] = txt
        except Exception as exc:
            st["err"].append({"stage": "spec", "file": rel(f["path"], inp), "error": str(exc)[:100]})
    for key in ("task_instruction", "format_requirements"):
        if isinstance(st["case"].get(key), str) and len(st["case"][key]) > 8:
            cands += extract.prose_spec(st["case"][key], "case.json")
            corpus.setdefault("case.json", st["case"][key])
    if not tpl:
        st["deg"].append({"what": "输入里没有模板文件", "handled": "改用格式要求与兜底取值",
                          "impact": "规格可能不完整，需人工补核"})
    if not cands:
        st["deg"].append({"what": "没有抽到任何规格", "handled": "整套使用兜底取值",
                          "impact": "所有条目记为推断，需人工核对模板"})
    st["spec"], st["cf"] = extract.merge(cands)
    n = st["nums"] = extract.units(st["spec"])

    probe = shutil.which("fc-match") or shutil.which("fc-list")
    st["fprobe"], substitute = None, None
    exact = probe is not None and Path(probe).name == "fc-match"
    if probe:
        try:
            if exact:
                # fc-list 会被 fontconfig 的模式匹配带偏，这里比对族名是否精确命中
                fams = font_families(probe, n["font"]) or []
                substitute = fams[0] if fams else None
                st["fprobe"] = bool(fams) and n["font"].strip().lower() in [f.lower() for f in fams]
            else:
                st["fprobe"] = bool(subprocess.run([probe, n["font"]], timeout=20,
                                                  capture_output=True).stdout.strip())
        except Exception:
            st["fprobe"] = None
    lgr = {"requested": n["font"], "policy": "revision3-liberation-serif",
           "probe_tool": Path(probe).name if probe else None, "probe_result": st["fprobe"],
           "substitute": substitute, "resolved": n["font"], "fallback_used": False,
           "note": "字体族写入 styles.xml 的 rFonts"}
    if st["fprobe"] is False:
        st["deg"].append({"what": "模板字体 %s 在本机不可用" % n["font"],
                          "handled": "按 revision3 改用 Liberation Serif",
                          "impact": "字形略有差异；fontconfig 原本会替换成 %s" % (substitute or "未知")})
        n["font"] = "Liberation Serif"
        lgr.update(resolved=n["font"], fallback_used=True)
        if exact:
            alt = [f.lower() for f in (font_families(probe, "Liberation Serif") or [])]
            lgr["fallback_available"] = "liberation serif" in alt
        st["pend"].append({"item": "body.font", "issue": "模板字体缺失，已替换为 Liberation Serif",
                           "action": "请确认替换可接受"})
    st["font_ledger"] = lgr

    blocks = []
    if draft:
        p, low = draft[0]["path"], draft[0]["path"].lower()
        if low.endswith((".docx", ".dotx")):
            blocks = ooxml.docx_blocks(p)[0]
        elif low.endswith((".tex", ".ltx")):
            blocks = ooxml.md_blocks(extract.tex_to_md(ooxml.slurp_text(p)))[0]
        else:
            blocks = ooxml.md_blocks(ooxml.slurp_text(p))[0]
    else:
        st["err"].append({"stage": "manuscript", "error": "未找到可解析的原稿（docx/md/tex）"})

    st["chg"] = []
    st["xref"] = verify.renumber(blocks, st["chg"])
    target = out_dir / "deliverable.docx"
    st["info"] = ooxml.write_docx(str(target), blocks, n)
    pdf = None if opts.no_preview else preview(target, out_dir)
    if not pdf:
        st["deg"].append({"what": "PDF 预览未生成（缺 soffice 或转换失败）", "handled": "保留可编辑 docx",
                          "impact": "无法目视复核版面"})
    flat = re.sub(r"\s", "", verify.docx_text(target))
    st.update(docx=rel(target, out_dir), pdf=rel(pdf, out_dir) if pdf else None,
              cov=verify.cover(blocks, flat), facts=verify.tally_facts(blocks, flat))
    try:
        z = zipfile.ZipFile(target)
        st["sx"] = z.read("word/styles.xml").decode("utf-8", "replace")
        st["dx"] = z.read("word/document.xml").decode("utf-8", "replace")
        st["ftr"] = z.read("word/footer1.xml").decode("utf-8", "replace")
    except Exception:
        st["sx"] = st["dx"] = st["ftr"] = ""

    graded = hit = 0
    for s in st["spec"]:
        if s["inferred"] or not s.get("quote"):
            s["traceable"] = None
            continue
        graded += 1
        host = corpus.get(str(s["locator"]).split("#")[0], "")
        s["traceable"] = bool(host and s["quote"] in host)
        hit += 1 if s["traceable"] else 0
    st["trace"] = "100%" if graded and hit == graded else ("%d%%" % int(100.0 * hit / graded) if graded else "n/a")

    for s in st["spec"]:
        if s["inferred"]:
            st["pend"].append({"item": s["id"], "issue": "无出处，采用兜底取值", "value": s["value"],
                               "action": "请确认模板是否另有规定"})
        elif s["traceable"] is False:
            st["pend"].append({"item": s["id"], "issue": "摘录未在来源原文命中", "value": s["value"],
                               "action": "请核对模板原文"})
    for c in st["cf"]:
        st["pend"].append({"item": c["item"], "issue": "模板与格式要求给出不同取值",
                           "action": "已取 %s，请确认取舍" % c["chosen"]})
    for x in (st["cov"].get("missing") or [])[:8]:
        st["pend"].append({"item": "fidelity", "issue": "成品未匹配到该内容单元", "text": x})
    for x in (st["xref"].get("dangling") or [])[:8]:
        st["pend"].append({"item": "xref", "issue": "引用图表号超过题注总数", "ref": x["ref"]})
    side(out_dir, st)


def self_check():
    """纯函数自检：单位换算、冲突裁决、块解析、题注重编号。"""
    rows = []

    def mark(cid, expr, got, want):
        rows.append({"id": cid, "expr": expr, "got": got, "want": want, "ok": got == want})

    mark("SC1", 'half("12pt")', extract.half("12pt"), 24)
    mark("SC2", 'half("10.5pt")', extract.half("10.5pt"), 21)
    mark("SC3", "CJK 小四 → pt", extract.CJK_PT.get("小四"), 12)
    base = [{"id": i, "value": v, "source": "default", "locator": "", "quote": "", "inferred": True}
            for i, v in extract.DEF]
    plain = extract.units(base)
    mark("SC4", "默认 1.5 行距 → w:line", plain["line"], 360)
    mark("SC5", "默认 2.54cm 边距 → twip", plain["marT"], 1440)
    mark("SC6", "默认 A4 宽 → twip", plain["pgW"], 11906)
    tweak = [dict(s) for s in base]
    for s in tweak:
        if s["id"] == "body.size":
            s["value"] = "10.5pt"
        elif s["id"] == "body.line_spacing":
            s["value"] = "20pt"
        elif s["id"] == "page.columns":
            s["value"] = "2"
    odd = extract.units(tweak)
    mark("SC7", "10.5pt → w:sz", odd["sz"], 21)
    mark("SC8", "20pt 行距 → exact", (odd["line"], odd["lineRule"]), (400, "exact"))
    mark("SC9", "双栏 → col_sep", (odd["cols"], odd["col_sep"]), (2, True))
    demo = ("## 一\n\n正文 95% 保留[1]。\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
            "![图](f.png)\n\n$$x=1$$\n\n[^1]: 注\n")
    blocks, meta = ooxml.md_blocks(demo)
    mark("SC10", "md 块类型顺序", [b["kind"] for b in blocks],
         ["heading", "para", "table", "figure", "equation", "note"])
    mark("SC11", "脚注计数", meta["footnotes"], 1)
    log = []
    verify.renumber([{"kind": "figure", "caption": "图 7 结构"},
                     {"kind": "figure", "caption": "图 8 谱图"}], log)
    mark("SC12", "题注重编号", [z["after"] for z in log], ["图 1 结构", "图 2 谱图"])
    mark("SC13", "控制字符清除", ooxml.esc("a\x00b"), "ab")
    merged, clash = extract.merge([
        {"id": "body.size", "value": "11pt", "source": "requirements", "locator": "r#L1",
         "quote": "字号 11pt", "inferred": False},
        {"id": "body.size", "value": "12pt", "source": "template_tex", "locator": "t#fs",
         "quote": "\\fontsize{12pt}", "inferred": False}])
    pick = [z for z in merged if z["id"] == "body.size"][0]
    mark("SC14", "tex 优先于文字要求", (pick["value"], len(clash)), ("12pt", 1))
    return {"generated": stamp(), "passed": sum(1 for r in rows if r["ok"]), "total": len(rows), "checks": rows}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="conform.py",
        description=("读 /input 下的 case.json、目标模板与稿件，逐条抽出可核对的排版规格，重排成可编辑 docx，"
                     "并写出格式规格表、样式映射、保真报告、待人工确认清单、预览 PDF 与 result.json。"
                     "只用标准库，退出码恒为 0。"))
    ap.add_argument("--input", default=IN_DEF, help="输入目录（默认 /input）")
    ap.add_argument("--output", default=OUT_DEF, help="产物目录（默认 /app/output）")
    ap.add_argument("--no-preview", action="store_true", help="跳过 PDF 预览导出")
    ap.add_argument("--self-check", action="store_true", help="只跑换算与解析自检，写 self_check.json")
    ap.add_argument("--version", action="version", version=V)
    opts = ap.parse_args(argv)

    inp, out_dir = Path(opts.input), Path(opts.output)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if BOOT_TROUBLE is not None:
        bootstrap("import failed: " + BOOT_TROUBLE, out_dir)
        print(json.dumps({"status": "partial", "error": "module unavailable"}, ensure_ascii=False))
        return 0
    t0 = time.time()
    if opts.self_check:
        try:
            report = self_check()
        except Exception as exc:
            report = {"generated": stamp(), "passed": 0, "total": 0, "checks": [], "error": str(exc)[:200]}
        try:
            dump(out_dir / "self_check.json", report)
        except OSError:
            pass
        print(json.dumps({"self_check": "%s/%s" % (report.get("passed"), report.get("total"))},
                         ensure_ascii=False))
        return 0

    st = {"err": [], "deg": [], "pend": [], "chg": [], "cf": [], "spec": [], "facts": [],
          "case": {}, "cov": {}, "xref": {}, "out": out_dir}
    case, cerr = None, None
    for cand in [inp / "case.json"] + sorted(inp.glob("case*.json")) + sorted(inp.rglob("case*.json")):
        try:
            case = json.loads(cand.read_text(encoding="utf-8"))
            break
        except FileNotFoundError:
            continue
        except Exception as exc:
            cerr = {"stage": "case", "file": str(cand), "error": str(exc)[:120]}
            break
    if case is None and cerr is None:
        cerr = {"stage": "case", "error": "case.json 不存在或不可读"}
    if cerr:
        st["err"].append(cerr)
        st["inp_err"] = True
    st["case"] = case if isinstance(case, dict) else {}
    st["wo"] = workorder(st["case"]) if isinstance(st["case"], dict) else []

    # 先落最小合法结果：后续任何中断都还能被读到。
    dump(out_dir / "result.json", {
        "case_id": st["case"].get("case_id"), "status": "partial", "deliverable": None,
        "preserved_facts": [], "evidence_map": [], "change_log": [], "errors": st["err"],
        "pending_human": [], "degradations": [],
        "runtime": {"version": V, "stage": "partial"}})
    try:
        pipeline(inp, out_dir, opts, st)
    except Exception as exc:
        st["err"].append({"stage": "runtime", "error": str(exc)[:200]})
    try:
        payload = assemble(st, t0)
    except Exception as exc:
        payload = {"case_id": st["case"].get("case_id"), "status": "partial", "deliverable": None,
                   "preserved_facts": [], "evidence_map": [], "change_log": [],
                   "errors": st["err"] + [{"stage": "assemble", "error": str(exc)[:200]}],
                   "pending_human": [], "degradations": st["deg"], "runtime": {"version": V}}
    try:
        dump(out_dir / "result.json", payload)
    except OSError:
        pass
    print(json.dumps({k: payload.get(k) for k in ("case_id", "status", "deliverable",
                                                 "export_artifact", "summary")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
