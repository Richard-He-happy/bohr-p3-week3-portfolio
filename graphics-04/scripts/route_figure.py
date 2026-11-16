#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""route_figure.py -- graphics-04 command line entry point (standard library only).

Job of this module: find the case bundle, read every material file, turn the
workorder (or, failing that, the prose) into a figure-ready model, then hand the
model to svg_export.py which draws the SVG and produces the PDF/PNG exports.
"""
import argparse, hashlib, json, re, subprocess, sys, time, zipfile, zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import svg_export as G

VERSION, START_TIME, MATERIALS = G.VERSION, time.time(), []


def as_seq(v):
  return [] if v is None else (v if isinstance(v, list) else [v])


def assemble_model(order, exc):
  kind_token = str(pick(order, "figure_kind", "figure_type", "diagram_type", "kind") or "").lower()
  kind = next((k for k, pats in (("combo", ("combo", "combined", "multi", "组合")),
  ("route", ("route", "路线", "roadmap")),
  ("process", ("process", "flow", "流程", "procedure")),
  ("apparatus", ("apparatus", "device", "装置", "setup")))
  if any(p in kind_token for p in pats)), "")
  type_token = str(pick(order, "workorder_type") or pick(order, "figure_type") or "").lower()
  if "apparatus" in type_token and any(k in type_token for k in ("route", "process", "flow")):
    kind = "combo"
  parts = []
  for i, r in enumerate(as_seq(pick(order, "required_parts", "parts", "components", "equipment")), 1):
    r = {"name": r} if isinstance(r, str) else r
    label = str(pick(r, "name", "label", "title") or "").strip()
    if not label:
      continue
    p = {"id": "part-%02d" % i, "name": label, "qty": pick(r, "qty", "count", "quantity"),
  "ports": [str(pick(x, "name", "id", "port") or x) if isinstance(x, dict) else str(x)
  for x in as_seq(pick(r, "ports", "interfaces"))][:4],
  "group": pick(r, "group")}
    if p["qty"] is None:
      log_issue(exc, "qty_missing", "部件「%s」没有报告数量" % label, "minor", "图上写「数量未报告」，不推测数字")
    parts.append(bind_source(p, label, exc, "部件"))
  label2id = {}
  for p in parts:
    label2id[p["name"]], label2id[p["id"]] = p["id"], p["id"]

  def match_part(token):
    key = str(token or "").strip()
    return label2id.get(key) or next((pid for name, pid in label2id.items() if key and (key in name or name in key)), None)
  conns = []
  for i, r in enumerate(as_seq(pick(order, "required_connections", "connections", "links")), 1):
    if isinstance(r, str):
      mm = re.match(r"\s*(.+?)\s*(?:->|→|-->|to|到|至)\s*([^\(（\[]+)(?:[\(（\[](.*?)[\)）\]])?\s*$", r)
      if not mm:
        log_issue(exc, "conn_unparsed", "连接「%s」无法解析出两个端点" % r, "major", "不绘制，等待人工补齐端点")
        continue
      r = {"from": mm.group(1), "to": mm.group(2), "medium": mm.group(3)}
    frm, to = pick(r, "from", "from_id", "source"), pick(r, "to", "to_id", "target")
    med = pick(r, "medium", "phase", "type")
    c = {"id": "conn-%02d" % i, "from": frm, "to": to, "from_id": match_part(frm), "to_id": match_part(to), "medium": classify_medium(med),
  "direction": str(pick(r, "direction", "flow", "dir") or "forward").lower(),
  "label": pick(r, "label", "medium_name", "name"), "interface": pick(r, "interface", "port")}
    if not med:
      log_issue(exc, "medium_missing", "连接「%s→%s」未说明介质" % (frm, to), "minor", "按物料流呈现并在图例说明")
    c["drawable"] = bool(frm and to and c["from_id"] and c["to_id"])
    if not (frm and to):
      log_issue(exc, "conn_one_end", "连接「%s→%s」只给出一端" % (frm, to), "major", "不画半截箭头")
    elif not c["drawable"]:
      log_issue(exc, "conn_dangling", "连接「%s→%s」的端点不在部件清单里" % (frm, to), "major", "不绘制，避免凭空补管路")
    conns.append(bind_source(c, c["label"] or frm or to, exc, "连接"))
  steps = []
  for i, r in enumerate(as_seq(pick(order, "steps", "procedure", "process_steps")), 1):
    r = {"title": r} if isinstance(r, str) else r
    t = str(pick(r, "title", "name", "action", "desc") or "").strip()
    if not t:
      continue
    so = pick(r, "no", "index", "step_no", "num")
    if so is not None and str(so) != str(i):
      log_issue(exc, "step_order_mismatch", "步骤自带编号 %s 与出现顺序 %d 不一致" % (so, i), "major", "图上按正文顺序重新编号，原编号留档")
    steps.append(bind_source({"no": i, "source_order": so, "title": t,
  "after": as_seq(pick(r, "after", "depends_on")),
  "parallel": bool(pick(r, "parallel", "branch")),
  "loop_to": pick(r, "loop_to", "return_to"),
  "detail": pick(r, "detail", "note", "condition")}, t, exc, "步骤"))
  stages = []
  for i, r in enumerate(as_seq(pick(order, "stages", "phases", "route_stages")), 1):
    r = {"title": r} if isinstance(r, str) else r
    if not isinstance(r, dict):
      continue
    stages.append(bind_source({
  "id": str(pick(r, "id", "stage", "no", "code") or ("ST%d" % i)),
  "title": str(pick(r, "title", "name", "stage") or ("阶段%d" % i)),
  "goal": pick(r, "goal", "objective", "aim", "target"),
  "methods": as_seq(pick(r, "methods", "method", "tasks")),
  "inputs": as_seq(pick(r, "inputs", "input")), "outputs": as_seq(pick(r, "outputs", "output")),
  "deps": as_seq(pick(r, "dependencies", "depends_on", "after")),
  "milestone": pick(r, "milestone", "deliverable")}, str(pick(r, "title", "name", "stage") or i),
  exc, "阶段"))
  if not kind:
    kind = ("combo" if parts and conns and (steps or stages) else "apparatus" if parts and conns else
  "route" if stages else "process" if steps else "apparatus")
    log_issue(exc, "figure_kind_inferred", "workorder 没有指定 figure_kind", "minor", "依据材料内容判定为 %s" % kind)
  return {"kind": kind, "title": pick(order, "title", "caption", "figure_title"), "parts": parts, "conns": conns,
  "steps": steps, "stages": stages, "metrics": []}


def bind_source(item, name, exc, what):
  item["source"], item["source_verified"] = evidence_for(name)
  if not item["source_verified"]:
    log_issue(exc, "source_not_located", "%s「%s」在材料中找不到逐字来源" % (what, name), "major", "元素保留但标记为未核验")
  return item


def blank_result():
  r = dict(case_id=None, status="partial", editable_source=None, export_artifact=None, compliance_checks={},
  exceptions=[], sources=[], uncertainty=[], pending_human=[], errors=[], degradations=[], changes=[],
  runtime={}, output_contract=None,
  content_map=dict(parts=[], connections=[], steps=[], stages=[], legend=[], metrics=[], panels=[],
  coverage={}))
  return r


def classify_medium(v):
  s = str(v or "").lower()
  if any(k in s for k in ("energy", "heat", "power", "能量", "热", "电")):
    return "energy"
  if any(k in s for k in ("info", "signal", "信息", "信号")) or "data" in s:
    return "information"
  return "material"


def cli(argv=None):
  ap = argparse.ArgumentParser(
  prog="route_figure.py",
  description="Turn an apparatus / process / route workorder into an editable "
  "layered SVG plus real PDF and PNG exports; every drawn element carries a "
  "locator and a verbatim quote from the source material.")
  ap.add_argument("--input", default="/input", help="folder with case.json and the source material files")
  ap.add_argument("--output", default="/app/output", help="folder for figure.svg / figure.pdf / figure.png / result.json")
  ap.add_argument("--work", default="/app/work", help="scratch folder for renderer logs and engine profiles")
  a = ap.parse_args(argv)
  rp = Path(a.output) / "result.json"
  for d in (Path(a.output), Path(a.work)):
    try:
      d.mkdir(parents=True, exist_ok=True)
    except Exception:
      pass
  report = blank_result()
  persist(dict(report), rp, sys.argv[1:])      # write a valid partial result before any real work starts
  try:
    report = run_pipeline(a, report)
  except Exception as e:
    import traceback
    report["errors"].append({"code": "pipeline_error", "message": str(e), "trace": traceback.format_exc()[-900:]})
    report["status"] = "partial"
  persist(report, rp, sys.argv[1:])
  return 0


def collect_workorders(case):
  hits = []

  def walk(o):
    if isinstance(o, dict):
      if any(k in o for k in ("figure_kind", "figure_type", "required_parts", "required_connections",
  "workorder_type", "stages", "panels", "steps")):
        hits.append(o)
      for v in o.values():
        walk(v)
    elif isinstance(o, list):
      for v in o:
        walk(v)
  walk(case)
  return hits


def evidence_for(name):
  label = str(name or "").strip()
  for d in (MATERIALS if label else []):
    i = d["text"].find(label)
    if i < 0:
      continue
    ls, le = d["text"].rfind("\n", 0, i) + 1, d["text"].find("\n", i)
    q = re.sub(r"^[#>\-*\s|]+", "", d["text"][ls:le if le > 0 else len(d["text"])].strip()).strip()[:240] or label
    pre = d["text"][:i]
    pg, line = pre.count("\f"), pre.split("\f")[-1].count("\n") + 1
    return {"locator": "%s:L%d" % (d["id"], line) if pg == 0 else "%s:p%d:L%d" % (d["id"], pg + 1, line),
  "quote": q, "file": d["path"]}, True
  return {"locator": None, "quote": None, "file": None}, False


def flatten_xml(x):
  x = re.sub(r"<[^>]+>", "\n", x)
  for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
    x = x.replace(a, b)
  return re.sub(r"\n{2,}", "\n", x)


def harvest_from_text(m, exc):
  allt = "\n".join(d["text"] for d in MATERIALS)
  if not m["parts"]:
    cand = [c.strip() for c in (x.group(1) or x.group(2) for x in re.finditer(
  r"^\s*[-*]\s*([^\s：:]{2,20})[：:]|^\|\s*([^|]{2,20})\s*\|", allt, re.M))
  if c.strip() and c.strip().lower() not in ("名称", "部件", "序号", "name", "---")][:12]
    for i, label in enumerate(cand, 1):
      p = bind_source({"id": "part-%02d" % i, "name": label, "qty": None, "ports": [], "group": None},
  label, exc, "部件")
      if p["source_verified"]:
        m["parts"].append(p)
    if m["parts"]:
      log_issue(exc, "parts_from_text", "部件清单由正文抽取", "major", "连接关系需人工确认")
  if not m["steps"]:
    for x in list(re.finditer(r"^\s*(\d+)[.、)]\s+(.{2,120})$", allt, re.M))[:14]:
      source_ref, ok = evidence_for(x.group(0).strip())
      m["steps"].append({"no": len(m["steps"]) + 1, "source_order": int(x.group(1)), "title": x.group(2).strip(),
  "after": [], "parallel": False, "loop_to": None, "detail": None, "source": source_ref,
  "source_verified": ok})
    if m["steps"]:
      log_issue(exc, "steps_from_text", "步骤由正文编号列表抽取", "major", "并行与回流关系未报告")


def locate_case(inp):
  inp, files = Path(inp), []
  files = sorted(x for x in inp.rglob("*") if x.is_file()) if inp.is_dir() else []
  for c in [inp / "case.json"] + sorted(inp.glob("case*.json")) + sorted(inp.rglob("case*.json")):
    if c.is_file():
      try:
        d = json.loads(c.read_text(encoding="utf-8", errors="replace"))
      except Exception:
        continue
      if isinstance(d, dict):
        return d, c, files
  return None, None, files


def log_issue(exc, code, msg, sev="major", act=""):
  exc.append({"code": code, "message": msg, "severity": sev, "action": act})


def pdf_text_streams(b):
  out = []
  for m in re.finditer(rb"stream\r?\n(.*?)endstream", b, re.S):
    try:
      d = zlib.decompress(m.group(1))
    except Exception:
      d = m.group(1)
    out += [s[1:-1].decode("latin-1", "replace") for s in re.findall(rb"\((?:[^()\\]|\\.)*\)", d)]
  return "\n".join(t for t in out if len(t.strip()) > 1)


def persist(report, path, argv):
  try:
    write_json(path, stamp_runtime(report, argv))
  except Exception as e:
    sys.stderr.write("result write failed: %s\n" % e)


def pick(d, *ks):
  if not isinstance(d, dict):
    return None
  for k in ks:
    v = d.get(k)
    if isinstance(v, str) and v.strip():
      return v.strip()
    if isinstance(v, (int, float)) or (isinstance(v, (list, dict)) and v):
      return v
  return None


def read_material(p):
  e = p.suffix.lower()
  try:
    if e == ".pdf":
      t = shell_capture(["pdftotext", "-layout", str(p), "-"])
      return (t, "pdftotext") if len(t.split()) > 5 else (pdf_text_streams(p.read_bytes()), "pdf-raw")
    if e in (".docx", ".pptx"):
      z = zipfile.ZipFile(p)
      ks = sorted(k for k in z.namelist() if re.match(r"(word/document|ppt/slides/slide)\d*\.xml", k))
      return "\n".join(flatten_xml(z.read(k).decode("utf-8", "replace")) for k in ks), "ooxml"
    if e == ".xlsx":
      return workbook_text(p), "xlsx"
    if e in (".md", ".txt", ".csv", ".tsv", ".json", ".svg", ".yaml", ".yml", ".xml"):
      return p.read_text(encoding="utf-8", errors="replace"), "text"
  except Exception:
    return "", "failed"
  return "", "unsupported"


def run_pipeline(a, report):
  out, work, exc = Path(a.output), Path(a.work), report["exceptions"]
  case, cp, files = locate_case(a.input)
  ct = case.get("output_contract", {}) if isinstance(case, dict) else {}
  report["case_id"] = (case.get("case_id") or case.get("id")) if isinstance(case, dict) else None
  report["output_contract"] = ct if isinstance(ct, dict) else {}
  [report.setdefault(k, None) for k in report["output_contract"]]
  if case is None:
    log_issue(exc, "case_unreadable", "case.json 不能解析为 JSON 对象", "major", "跳过它，改从散落材料重建")
  for f in files:
    if f.name.startswith(".") or f.suffix.lower() in (".pyc", ".py"):
      continue
    t, kind = read_material(f)
    if t.strip():
      MATERIALS.append({"id": "S%d" % (len(MATERIALS) + 1), "path": str(f), "kind": kind, "text": t})
    else:
      log_issue(exc, "material_unreadable", "材料 %s 没有提取到可用文本" % f.name, "minor", "不作为证据，需人工复核")
  if cp and not any(d["path"] == str(cp) for d in MATERIALS):
    MATERIALS.append({"id": "S%d" % (len(MATERIALS) + 1), "path": str(cp), "kind": "json",
  "text": json.dumps(case, ensure_ascii=False, indent=2) if case else ""})
  report["sources"] = [{"id": d["id"], "path": d["path"], "kind": d["kind"], "chars": len(d["text"])} for d in MATERIALS]
  wos = collect_workorders(case) if case else []
  if not wos:
    log_issue(exc, "workorder_missing", "输入中没有 figure workorder 结构", "major", "按正文语义抽取，连接关系待人工确认")
  m = assemble_model(wos[0] if wos else {}, exc)
  harvest_from_text(m, exc)
  if not m["title"]:
    m["title"] = next((mm.group(1).strip() for d in MATERIALS
  for mm in [re.search(r"^\s*#\s+(.{3,80})$", d["text"], re.M)] if mm), None)
  specs = G.choose_panels(m["kind"], m)
  if not specs:
    log_issue(exc, "no_drawable_entities", "没有任何可绘制实体", "blocking", "输出缺口说明画布，等待人工提供清单")
    report["status"], specs = "insufficient_evidence", ["apparatus"]
  foot = "材料：%s ｜ 每个图元在 content_map 中都带 locator 与逐字 quote ｜ 版本 %s" % (
  "、".join("%s(%s)" % (d["id"], Path(d["path"]).name) for d in MATERIALS[:4]) or "无输入材料", VERSION)
  svg, cv, W, H = G.compose_svg(m, specs, m["title"] or "实验装置与技术路线图", foot)
  same = svg == G.compose_svg(m, specs, m["title"] or "x", foot)[0]
  (out / "figure.svg").write_text(svg, encoding="utf-8")
  exp = G.export_bundle(cv, W, H, out / "figure.svg", out, work, exc, 640.0, START_TIME)
  for p in m["parts"]:
    p.pop("_x", None); p.pop("_y", None)
  write_json(out / "figure_model.json", {"skill_version": VERSION, "kind": m["kind"], "title": m["title"],
  "parts": m["parts"], "connections": m["conns"], "steps": m["steps"], "stages": m["stages"]})
  cm = report["content_map"]
  cm.update(parts=m["parts"], connections=m["conns"], steps=m["steps"], stages=m["stages"])
  used = list(dict.fromkeys(c["medium"] for c in m["conns"] if c["drawable"]))
  cm["legend"] = [{"key": k, "label": G.FLOW_MEDIA[k][0], "color": G.FLOW_MEDIA[k][1], "dash": G.FLOW_MEDIA[k][2],
  "in_svg": "legend-line-" + k}
  for k in (used or ["material"])]
  cm["panels"] = [{"panel": i + 1, "kind": sp, "svg_layer": "layer-" + ("parts" if sp == "apparatus" else sp)}
  for i, sp in enumerate(specs)]
  P, C, S, T = m["parts"], m["conns"], m["steps"], m["stages"]
  ids, items = G.element_ids(svg), P + C + S + T
  pids = {p["id"] for p in P}
  dang = [c["id"] for c in C if c["drawable"] and (c["from_id"] not in pids or c["to_id"] not in pids)]
  undrawn = [c["id"] for c in C if not c["drawable"]]
  cm_ids = ([p["id"] for p in P] + [c["id"] for c in C if c["drawable"]] if "apparatus" in specs else []) + \
           (["step-%d" % x["no"] for x in S] if "process" in specs else []) + \
           (["stage-%d" % (i + 1) for i in range(len(T))] if "route" in specs else [])
  missing = [i for i in cm_ids if i not in ids]
  seq = [s["no"] for s in S]
  contig = seq == list(range(1, len(seq) + 1))
  ver = len([x for x in items if x["source_verified"]])
  pixel_report = G.probe_png(exp["png"]["path"]) if exp.get("png") else {"ok": False, "note": "no png"}
  sws = [p.get("sw") or 2 for p in cv.p]
  model_ids = set(p["id"] for p in P) | set(c["id"] for c in C) | set("step-%d" % x["no"] for x in S) | \
    set("stage-%d" % (i + 1) for i in range(len(T)))
  expect_magic = {"figure.svg": b"<?xml", "figure.pdf": b"%PDF-", "figure.png": b"\x89PNG\r\n\x1a\n"}
  audit = {}
  for fname, magic in expect_magic.items():
    blob = (out / fname).read_bytes() if (out / fname).is_file() else b""
    audit[fname] = {"bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()[:16] if blob else None,
                    "magic_ok": blob.startswith(magic)}
  audit_ok = all(v["magic_ok"] for v in audit.values()) and bool(model_ids & ids)
  fails = [k for k, ok in (("dangling", not dang), ("step_numbering", contig), ("id_coverage", not missing),
  ("quote_verification", ver == len(items)), ("pixel_probe", pixel_report.get("ok", False)),
  ("artifact_audit", audit_ok))
  if not ok]
  report["compliance_checks"] = {
  "artifact_audit": {"files": audit, "model_ids_in_svg": len(model_ids & ids), "model_ids_total": len(model_ids),
  "ok": audit_ok},
  "canvas": {"width": W, "height": H, "ok": W >= 800 and H >= 300},
  "fonts": {"family": G.FONT_STACK, "generic_fallback": True, "cjk_in_svg": any(ord(c) > 0x2E80 for c in svg),
  "embedded_in_pdf": (exp.get("pdf") or {}).get("engine") == "soffice-svg2pdf"},
  "line_widths": {"min": min(sws), "ok": min(sws) >= 0.5},
  "dangling_connections": {"count": len(dang), "detail": dang, "not_drawn": undrawn, "ok": not dang},
  "flow_direction": {"drawn": len(C) - len(undrawn), "unresolved": len(undrawn), "ok": not undrawn},
  "step_numbering": {"sequence": seq, "contiguous_1_to_n": contig, "ok": contig,
  "source_order": [s["source_order"] for s in S]},
  "overflow": {"max_x": round(cv.maxx, 1), "max_y": round(cv.maxy, 1), "canvas": [W, H],
  "ok": cv.maxx <= W and cv.maxy <= H},
  "quote_verification": {"items": len(items), "verified": ver, "ok": ver == len(items),
  "rate": round(ver / max(1, len(items)), 3)},
  "id_coverage": {"content_map_ids": len(cm_ids), "element_ids": len(ids), "missing": missing, "ok": not missing},
  "pixel_probe": pixel_report,
  "determinism": {"svg_sha256": hashlib.sha256(svg.encode()).hexdigest()[:16], "rerender_identical": same},
  "render_engine": {"pdf": (exp.get("pdf") or {}).get("engine"), "png": (exp.get("png") or {}).get("engine")},
  "pass": not fails, "failures": fails}
  report["editable_source"] = {"path": "figure.svg", "format": "svg", "editable": True, "layers": G.LAYER_ORDER,
  "viewBox": [W, H], "text_count": len([p for p in cv.p if p["t"] == "t"]),
  "bytes": len(svg.encode()), "sha256": hashlib.sha256(svg.encode()).hexdigest()}
  report["export_artifact"] = {"png": exp.get("png"), "pdf": exp.get("pdf")}
  cm["coverage"] = {"parts": len(P), "connections": len(C), "steps": len(S), "stages": len(T), "panels": specs,
  "verified_rate": round(ver / max(1, len(items)), 3)}
  if report["status"] != "insufficient_evidence":
    report["status"] = "ok" if (not fails and (exp.get("pdf") or exp.get("png")) and items) else "partial"
  if not (exp.get("pdf") and exp.get("png")):
    report["degradations"].append("导出不完整，缺少：" + str([k for k in ("pdf", "png") if not exp.get(k)]))
  if any(p["qty"] is None for p in P):
    report["pending_human"].append("请人工确认部件数量：" + "、".join(p["name"] for p in P if p["qty"] is None))
  report["pending_human"] += ["请人工确认缺端点或介质的连接：%s→%s" % (c["from"], c["to"]) for c in C if not c["drawable"]]
  if any(not x["source_verified"] for x in items):
    report["pending_human"].append("请人工确认无来源定位的元素：" + "、".join(
  str(x.get("name") or x.get("title")) for x in items if not x["source_verified"]))
  if not items:
    report["uncertainty"].append("材料中没有可绘制的装置、步骤或阶段，因此只输出缺口说明画布")
  report["uncertainty"] += ["%s：%s" % (e["code"], e["message"]) for e in exc if e["severity"] in ("major", "blocking")]
  report["changes"] = [{"target": "figure.svg", "original": None, "revised": "rebuilt from source materials",
  "locator": "n/a", "reason": "重建型工单，没有可解析的既有图源"}]
  return report


def shell_capture(command, timeout=120):
  """Run a helper executable and return its stdout; any failure yields empty text."""
  try:
    done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return done.stdout if done.returncode == 0 else ""
  except Exception:
    return ""


def stamp_runtime(report, argv):
  [report.setdefault(k, None) for k in (report.get("output_contract") or {})]
  report["runtime"] = {"skill_version": VERSION, "seconds": round(time.time() - START_TIME, 2), "argv": argv,
  "python": sys.version.split()[0]}
  return report


def workbook_text(p):
  try:
    z = zipfile.ZipFile(p)
  except Exception:
    return ""
  ks, rows = z.namelist(), []
  ss = [flatten_xml(m) for m in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(
  "utf-8", "replace"), re.S)] if "xl/sharedStrings.xml" in ks else []
  for label in sorted(k for k in ks if re.match(r"xl/worksheets/sheet\d+\.xml", k)):
    for rm in re.findall(r"<row[^>]*>(.*?)</row>", z.read(label).decode("utf-8", "replace"), re.S):
      cells = []
      for at, body in re.findall(r"<c([^>]*)>(.*?)</c>", rm, re.S):
        t, v = re.search(r"<t[^>]*>(.*?)</t>", body, re.S), re.search(r"<v>(.*?)</v>", body, re.S)
        val = flatten_xml(t.group(1)).strip() if t else (v.group(1).strip() if v else "")
        cells.append(ss[int(val)] if 't="s"' in at and val.isdigit() and int(val) < len(ss) else val)
      if any(cells):
        rows.append(" | ".join(cells))
  return "\n".join(rows)


def write_json(p, o):
  Path(p).write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
  try:
    sys.exit(cli())
  except SystemExit:
    raise
  except Exception as e:  # never fail the harness
    sys.stderr.write("fatal: %s\n" % e)
    sys.exit(0)
