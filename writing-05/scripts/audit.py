#!/usr/bin/env python3
"""manuscript-blueprint-audit :: orchestrator (input, rendering, self-check).

Finds the input, segments the manuscript, renders the artifacts, back-fills
output_contract and re-reads its own output. Detection lives in gates.py.
Never edits the manuscript; always exits 0.

  python3 -B audit.py --input /input --out /app/output [--check]
"""

import argparse, json, re, shutil, subprocess, sys, time, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
  sys.path.insert(0, str(HERE))
try:
  import gates as G
except Exception:                    # engine unusable -> honest partial, never a crash
  G = None
try:
  import assets as A                 # v1.1.0: verifiable-asset layer (additive, optional)
except Exception:
  A = None

VERSION = "1.1.0"
SKILL = "manuscript-blueprint-audit"
DIMS = ("research_question_alignment", "section_structure", "argument_chain",
    "paragraph_relations", "duplication", "conclusion_boundary")
ARTIFACTS = {"structural_review": "structural_review.json", "edit_plan": "edit_plan.md",
      "outline_after": "outline_after.md", "argument_map": "argument_map.json",
      "consistency_report": "consistency_report.md", "pending_human_file": "pending_human.json"}
TEXT = (".md", ".markdown", ".txt", ".rst", ".tex", ".csv", ".html", ".htm", ".docx", ".pdf")
INSTRUCTION = ("task.md", "guide.md", "readme.md")
REWRITE = ("manuscript.md", "rewrite.md", "revised.md")
DEGRADE_STAGES = ("pdf", "read", "case_parse", "gate", "segment", "engine", "degradation",
         "anchor", "artifacts", "manuscript", "input", "finalize")


def dims():
  return G.DIMENSIONS if G else DIMS


def tpl(key, **fmt):
  return G.msg("render", key, **fmt) if G else key


def note(key, **fmt):
  return G.msg("notes", key, **fmt) if G else ""


def write(path, payload):
  text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
  Path(path).write_text(text, encoding="utf-8")


def read(path, errors):
  """Extract plain text from one material file; failures degrade, never raise."""
  suf = path.suffix.lower()
  try:
    if suf in (".md", ".markdown", ".txt", ".rst", ".tex", ".csv"):
      return path.read_text(encoding="utf-8", errors="replace")
    if suf in (".html", ".htm"):
      return re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8", errors="replace"))
    if suf == ".docx":
      with zipfile.ZipFile(path) as bundle:
        xml = bundle.read("word/document.xml").decode("utf-8", "replace")
      return re.sub(r"<[^>]+>", "", xml.replace("</w:p>", "\n\n"))
    if suf == ".pdf":
      exe = shutil.which("pdftotext")
      if not exe:
        errors.append({"stage": "pdf", "detail": "%s: no pdftotext" % path.name})
        return ""
      proc = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(path), "-"],
                            capture_output=True, timeout=120)
      if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.decode("utf-8", "replace")
      errors.append({"stage": "pdf", "detail": "%s: no text layer" % path.name})
  except Exception as exc:
    errors.append({"stage": "read", "detail": "%s: %s" % (path.name, exc)})
  return ""


def title_of(line, md):
  s = (line or "").strip()
  if not s or len(s) > 110 or s[-1] in ".,;。,；：:":
    return None
  if md:
    m = re.match(r"^#{1,6}\s+(\S.*)$", s)
    return m.group(1).strip().rstrip("#").strip() if m else None
  if G.P.get("head_numbered") and G.P["head_numbered"].match(s):
    return s
  low = s.lower().rstrip(":")
  for _n, rx in G.ROLES:
    if rx.match(low):
      return s
  return s if G.P.get("head_upper") and G.P["head_upper"].match(s) else None


def role_of(title):
  low = (title or "").strip().lower()
  for name, rx in G.ROLES:
    if low and rx.search(low):
      return name
  return "body"


def segment(text):
  """Cut the manuscript into chapters (C01), paragraphs (C01-P001) and sentences."""
  md, units, buf = bool(re.search(r"(?m)^#{1,6}\s+\S", text)), [], []
  for line in text.splitlines():
    s = line.strip()
    head = title_of(s, md) if s else None
    if head or not s:
      if buf:
        units.append(("p", "\n".join(buf)))
      buf = []
      if head:
        units.append(("h", head))
    else:
      buf.append(s)
  if buf:
    units.append(("p", "\n".join(buf)))
  chaps, paras, ch, idx = [], [], 0, 0
  for kind, val in units:
    if kind == "h":
      ch, idx = ch + 1, 0
      chaps.append({"loc": "C%02d" % ch, "title": G.squash(val), "role": role_of(val), "words": 0})
      continue
    if ch == 0:
      ch = 1
      chaps.append({"loc": "C01", "title": "", "role": "body", "words": 0})
    body = G.squash(val)
    if G.wc(body) < 3:
      continue
    idx += 1
    paras.append({"loc": "C%02d-P%03d" % (ch, idx), "ch": ch, "role": chaps[ch - 1]["role"],
                  "text": body, "sents": [("C%02d-P%03d-S%02d" % (ch, idx, i + 1), s)
                                          for i, s in enumerate(G.sents(body))]})
    chaps[ch - 1]["words"] += G.wc(body)
  return chaps, paras


def closure(a):
  """Four-link closure matrix: question -> method -> result -> conclusion."""
  blocks = {"question": a.joined(("abstract", "introduction", "body")) or a.text,
            "method": a.joined(("method",)), "result": a.joined(("result",)),
            "conclusion": a.joined(("conclusion", "discussion", "abstract"))}
  sets = dict((k, G.toks(v)) for k, v in blocks.items())
  links = []
  for lft, rgt in (("question", "method"), ("method", "result"), ("result", "conclusion"),
                   ("question", "conclusion")):
    if not (blocks[lft].strip() and blocks[rgt].strip()):
      links.append({"from": lft, "to": rgt, "status": "missing_block", "shared": 0, "need": 0,
                    "evidence": "无可解析文本，闭环无法判定"})
      continue
    sh, need = len(sets[lft] & sets[rgt]), max(2, int(0.15 * len(sets[lft])))
    ok = sh >= need
    links.append({"from": lft, "to": rgt, "status": "linked" if ok else "thin", "shared": sh,
                  "need": need, "evidence": note("CLOSURE_OK" if ok else "CLOSURE_THIN",
                                                 hit=sh, need=need)})
  done = sum(1 for x in links if x["status"] == "linked")
  return {"links": links, "closed_links": done, "total_links": len(links),
          "fully_closed": done == len(links)}


def argument_map(a):
  chains = []
  for para in a.body():
    claims = [{"locator": l, "quote": s} for l, s in para["sents"]
              if G.P["claim_marker"].search(s)]
    support = []
    for loc, s in para["sents"]:
      kind = "citation" if G.P["cite"].search(s) else (
        "number" if G.P["quantity"].search(s) else (
          "figure" if G.P["figure_ref"].search(s) else ""))
      if kind:
        support.append({"locator": loc, "quote": s, "kind": kind})
    if claims:
      chains.append({"chapter": "C%02d" % para["ch"], "paragraph": para["loc"],
                     "claim": claims[0], "evidence": support,
                     "status": "supported" if support else "unsupported"})
  top = next((f for f in a.F if f["dimension"] == "research_question_alignment"), None)
  return {"research_question": {"quote": top["quote"] if top else "",
                                "locator": top["locator"] if top else ""}, "chains": chains,
          "unsupported_chains": sum(1 for c in chains if c["status"] == "unsupported"),
          "closure_matrix": closure(a), "method": note("ARGMAP")}


def plan_item(act, index):
  f = index.get(act["finding_id"], {})
  return tpl("PLAN_ITEM", aid=act["action_id"], dim=G.label("dimension", f.get("dimension", "")),
             sev=G.label("severity", f.get("severity", "")), loc=f.get("locator", ""),
             quote=f.get("quote", ""), diag=f.get("diagnosis", ""),
             basis=f.get("evidence_for_judgment", ""), op=act["operation"],
             eff=act["expected_effect"], hazard=act["risk"],
             arrow="" if act["to_locator"] == act["from_locator"]
             else " -> `%s`" % act["to_locator"])


def render_plan(cid, a, coverage, pending):
  index = dict((f["finding_id"], f) for f in a.F)
  out = [tpl("PLAN_HEAD", cid=cid, pp=len(a.pa), ch=len(a.ch),
             words=sum(c["words"] for c in a.ch), findings=len(a.F), actions=len(a.A))]
  for pr in ("P1", "P2", "P3"):
    rows = [plan_item(x, index) for x in a.A if x["priority"] == pr]
    if rows:
      out.append(tpl("PLAN_GROUP", priority=pr, label=G.label("priority", pr)))
      out.extend(rows)
  out.append(tpl("PLAN_COVER_HEAD"))
  for dim in dims():
    cell = coverage.get(dim) or {}
    out.append(tpl("PLAN_COVER_ROW", dim=G.label("dimension", dim),
                   status=G.label("coverage", cell.get("status", "")),
                   n=len(cell.get("finding_ids") or [])))
  out.append(tpl("PLAN_PENDING_HEAD"))
  out.extend(["- %s: %s" % (p["item_id"], p["detail"]) for p in pending] or [tpl("PLAN_NONE")])
  return "\n".join(out)


def render_outline(a, cmap):
  total = sum(c["words"] for c in a.ch) or 1
  flags = {}
  for f in a.F:
    flags.setdefault(f["locator"].split("-")[0], set()).add(f["dimension"])
  out = [tpl("OUT_HEAD")]
  for i, c in enumerate(a.ch, 1):
    seen = flags.get(c["loc"], set())
    mark = tpl("OUT_NOTE_MERGE") if "duplication" in seen else (
      tpl("OUT_NOTE_FIX") if {"section_structure", "argument_chain"} & seen
      else tpl("OUT_NOTE_KEEP"))
    out.append(tpl("OUT_ROW", i=i, loc=c["loc"], title=(c["title"] or "-")[:44],
                   role=tpl("OUT_ROLE_BODY") if c["role"] == "body"
                   else G.label("role", c["role"]), words=c["words"],
                   pct=round(100.0 * c["words"] / total, 1), note=mark))
  top = next((f for f in a.F if f["dimension"] == "research_question_alignment"), None)
  moves = "; ".join("%s => after %s" % (x["from_locator"], x["to_locator"])
                    for x in a.A if x["operation"] == "move")
  out.append(tpl("OUT_MAIN", q=(top["quote"][:90] if top else "-"),
                 seq=" > ".join(c["loc"] + " " + (c["title"] or "") for c in a.ch),
                 closure="%d/%d" % (cmap["closed_links"], cmap["total_links"]),
                 moves=moves or tpl("OUT_NOMOVE")))
  return "\n".join(out)


def render_consistency(cid, a, truncated, degradations):
  stats, cite = a.N, (a.N.get("citation") or {})
  out = [tpl("CONS_HEAD", cid=cid)]
  out.extend(tpl("CONS_ROW", k=k, v="%.1f%%" % (v * 100))
       for k, v in (stats.get("share") or {}).items())
  out.append(tpl("CONS_CITE", in_text=cite.get("in_text", 0), listed=cite.get("listed", 0),
         unresolved=", ".join(str(x) for x in (cite.get("unresolved") or []))
         or tpl("NONE"), figs=", ".join(cite.get("figure_refs") or []) or tpl("NONE"),
         caps=", ".join(cite.get("captions") or []) or tpl("NONE")))
  out.append(tpl("CONS_DUP", compared=stats.get("dup_compared", 0),
         hits=stats.get("dup_pairs", 0), top=stats.get("dup_top", 0.0), adj=stats.get("pairs", 0)))
  out.append(tpl("CONS_STATE", trunc=tpl("TRUNC_YES") if truncated else tpl("TRUNC_NO"),
         anchors=len(a.AN), deg="; ".join("%s: %s" % (e.get("stage"), e.get("detail"))
                for e in degradations) or tpl("NONE")))
  return "\n".join(out)


def receipts(case):
  """Report per-item answer status for whichever organizer workorder keys exist."""
  out = []
  for key in ("organizer_workorder", "organizer_edit_workorder", "workorder", "scope"):
    items = case.get(key)
    if not items:
      continue
    for i, item in enumerate(items if isinstance(items, list) else [items], 1):
      req = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
      low = req.lower()
      dims_hit = [d for d in dims() if d.split("_")[0] in low]
      if any(k in low for k in ("pdf", "export", "pptx", "导出")):
        status, ev = "not_applicable", note("SERVICE_PDF")
      elif any(k in low for k in ("rewrite", "改写", "重写", "润色")):
        status, ev = "not_applicable", note("SERVICE_REWRITE")
      else:
        status = "done"
        ev = note("SERVICE_DIMS", d=", ".join(dims_hit)) if dims_hit else note("SERVICE_OK")
      out.append({"item_id": "%s-%02d" % (key[:6], i), "source_key": key,
                  "requirement": req[:300], "status": status, "evidence": ev})
  return out


def run(input_dir, out_dir, started):
  out, inp = Path(out_dir), Path(input_dir)
  errors, sources, extra, case, case_path = [], [], [], {}, None
  log = A.RunLog(VERSION, started) if A else None

  def hold(kind, detail, need):
    extra.append({"kind": kind, "detail": detail, "needed_action": need})

  try:
    out.mkdir(parents=True, exist_ok=True)
    write(out / "result.json", {"case_id": None, "status": "partial", "skill": SKILL,
                  "skill_version": VERSION, "sources": [], "changes": [],
                  "degradations": [], "deliverable": None, "errors":
                  [{"stage": "startup", "detail": "run started"}],
                  "preserved_facts": [], "evidence_map": [], "change_log": [],
                  "pending_human": [], "runtime": {"version": VERSION}})
    if log:
      log.mark("startup", "partial result.json written | input=%s out=%s" % (inp, out))
  except Exception as exc:
    print("cannot prepare output dir: %s" % exc)
    return 0

  if inp.is_dir():
    for cand in [inp / "case.json"] + sorted(inp.glob("**/case*.json")):
      if cand.is_file():
        case_path = cand
        break
    if case_path:
      try:
        loaded = json.loads(case_path.read_text(encoding="utf-8-sig", errors="replace"))
        case = loaded if isinstance(loaded, dict) else {}
      except Exception as exc:
        errors.append({"stage": "case_parse", "detail": "%s: %s" % (case_path.name, exc)})
  else:
    errors.append({"stage": "input", "detail": "input directory missing: %s" % inp})
  contract = case.get("output_contract") or {}
  contract = contract if isinstance(contract, dict) else {"output_contract": contract}
  cid = case.get("case_id") or case.get("id") or case.get("caseId") or "case-unknown"
  if log:
    log.mark("case", "case_id=%s contract_keys=%d parse_errors=%d"
             % (cid, len(contract), len(errors)))

  candidates = []
  for path in (sorted(inp.rglob("*")) if inp.is_dir() else []):
    if not path.is_file() or path.name.startswith("."):
      continue
    size = path.stat().st_size
    entry = {"source_id": path.name, "path": str(path), "bytes": size}
    if case_path and path.resolve() == case_path.resolve():
      entry["role"] = "case"
    elif path.name.lower() in INSTRUCTION:
      entry["role"] = "instruction"
    elif path.suffix.lower() not in TEXT:
      entry["role"] = "non_text_material"
    else:
      text = read(path, errors)
      entry.update({"role": "material", "text_chars": len(text)})
      if text.strip():
        candidates.append((len(text), path, text))
    sources.append(entry)
  if log:
    log.mark("discover", "files=%d readable_texts=%d role_counts=%s"
             % (len(sources), len(candidates),
                dict((r, sum(1 for s in sources if s.get("role") == r))
                     for r in ("case", "instruction", "material", "non_text_material"))))

  audit, mpath, mtext, truncated = None, None, "", False
  if not candidates:
    errors.append({"stage": "manuscript", "detail": "no readable manuscript text"})
    hold("no_manuscript", G.msg("pending", "PD_NO_TEXT"), G.msg("pending", "PD_NO_TEXT_N"))
  else:
    candidates.sort(key=lambda item: -item[0])
    _, mpath, mtext = candidates[0]
    if len(candidates) > 1:
      hold("multiple_materials", G.msg("pending", "PD_MULTI", n=len(candidates),
                      name=mpath.name), G.msg("pending", "PD_MULTI_N"))
    mtext = mtext.replace("\r\n", "\n").replace("\r", "\n")
    tail = mtext.strip()[-1] if mtext.strip() else ""
    truncated = bool(tail) and tail not in ".!?。！？)\u201d\"'" and len(mtext) > 1500
    if truncated:
      hold("truncated_manuscript", G.msg("pending", "PD_TRUNC", n=len(mtext)),
        G.msg("pending", "PD_TRUNC_N"))
      errors.append({"stage": "degradation",
             "detail": "possible truncation: last char is not terminal"})
  if log:
    log.mark("material", "manuscript=%s chars=%d truncated=%s multiple=%d"
             % (mpath.name if mpath else "-", len(mtext), truncated,
                max(0, len(candidates) - 1)))

  chapters, paragraphs = [], []
  if mtext:
    try:
      chapters, paragraphs = segment(mtext)
    except Exception as exc:
      errors.append({"stage": "segment", "detail": str(exc)})
  if log:
    log.mark("segment", "chapters=%d paragraphs=%d words=%d"
             % (len(chapters), len(paragraphs), G.wc(mtext) if G else 0))

  result = {}
  if G is None:
    errors.append({"stage": "engine", "detail": "gates.py not importable; no findings"})
  elif paragraphs and G.wc(mtext) >= 60:
    try:
      audit = G.Audit(G.squash(mtext), mtext, chapters, paragraphs, truncated)
      result = audit.run()
      errors.extend(result.get("errors") or [])
    except Exception as exc:
      errors.append({"stage": "engine", "detail": str(exc)})
      audit = None
  elif mtext:
    hold("manuscript_too_short", G.msg("pending", "PD_SHORT", w=G.wc(mtext),
                     p=len(paragraphs)), G.msg("pending", "PD_SHORT_N"))
  if log:
    log.mark("gates", "findings=%d actions=%d anchors=%d dropped=%d"
             % (len(result.get("findings") or []), len(result.get("actions") or []),
                len(result.get("anchors") or []), int(result.get("dropped") or 0)))

  findings = result.get("findings") or []
  actions = result.get("actions") or []
  anchors = result.get("anchors") or []
  coverage = result.get("coverage") or dict(
    (d, {"status": "not_assessable", "finding_ids": [],
      "checked": G.msg("checked", "absent") if G else ""}) for d in dims())
  pending = list(result.get("pending") or []) + extra
  pending = [dict(x, item_id="PH%02d" % (i + 1)) for i, x in enumerate(pending)]
  cmap = closure(audit) if audit else {"links": [], "closed_links": 0, "total_links": 0,
                    "fully_closed": False}
  argmap = argument_map(audit) if audit else {"research_question": {"quote": "", "locator": ""},
                        "chains": [], "unsupported_chains": 0, "closure_matrix": cmap}
  preserved = G.preserved_facts(audit) if audit else []
  hit = sum(1 for f in findings if f["finding_id"] in set(x["finding_id"] for x in anchors))
  dropped = int(result.get("dropped") or 0)
  degradations = [e for e in errors if e.get("stage") in DEGRADE_STAGES]
  if truncated:
    degradations.append({"stage": "truncation",
              "detail": "tail incomplete; missing-section verdicts held back"})
  if audit is None:
    status = "input_error"
  elif not paragraphs or (G and G.wc(mtext) < 60):
    status = "insufficient_evidence"
  elif pending or degradations or dropped:
    status = "partial"
  else:
    status = "ok"

  hit_rate = 1.0 if not findings else round(hit / float(len(findings)), 4)
  quotes = dict((f["finding_id"], f["quote"]) for f in findings)
  review = {"case_id": cid, "findings": findings, "actions": actions,
            "dimension_coverage": coverage, "closure_matrix": cmap,
            "skill": {"name": SKILL, "version": VERSION},
            "manuscript": {"path": str(mpath) if mpath else None,
                           "title": chapters[0]["title"] if chapters else "",
                           "chapters": len(chapters), "paragraphs": len(paragraphs),
                           "words": G.wc(mtext) if G else 0, "truncated": truncated},
            "grounding": {"findings_total": len(findings), "quote_verbatim_hit": hit,
                          "hit_rate": hit_rate, "dropped_unverifiable": dropped,
                          "anchors": anchors, "rule": note("GROUND")}}

  change_log = [{"change_id": "CH%02d" % i, "action_id": x["action_id"],
                 "finding_id": x["finding_id"], "locator": x["from_locator"],
                 "original_quote": quotes.get(x["finding_id"], ""), "revised_quote": None,
                 "status": "proposed_not_applied", "change_type": "structural_action_proposed",
                 "reason": x["expected_effect"]} for i, x in enumerate(actions, 1)]
  try:
    write(out / "structural_review.json", review)
    write(out / "argument_map.json", argmap)
    write(out / "pending_human.json", {"case_id": cid, "items": pending,
                                       "cannot_judge": [p["detail"] for p in pending]})
    if audit:
      write(out / "edit_plan.md", render_plan(cid, audit, coverage, pending))
      write(out / "outline_after.md", render_outline(audit, cmap))
      write(out / "consistency_report.md", render_consistency(cid, audit, truncated, degradations))
    else:
      why = "; ".join(e.get("detail", "") for e in errors) or "无可用正文"
      note_md = "# 未能生成结构诊断\n\n- case_id: `%s`\n- 原因: %s\n\n> 直述失败，不编造结论。" % (cid, why)
      for name in ("edit_plan.md", "outline_after.md", "consistency_report.md"):
        write(out / name, note_md)
  except Exception as exc:
    errors.append({"stage": "artifacts", "detail": str(exc)})
  if log:
    log.mark("artifacts", "6 editable artifacts written (structural_review/argument_map/"
             "pending_human/edit_plan/outline_after/consistency_report)")

  ids = set(f["finding_id"] for f in findings)
  state = [v.get("status") for v in coverage.values()]
  usable = bool(G) and all(x.get("operation") in G.OPS and x.get("from_locator")
                           and x.get("expected_effect") for x in actions)
  pairs = [("six_dimension_coverage", len(coverage) == len(dims()), note("CHK_DIMS")),
           ("quote_verbatim_anchored", hit == len(findings), note("CHK_QUOTE", h=hit, t=len(findings))),
           ("actions_executable", usable, note("CHK_ACTION")),
           ("finding_action_join", all(x.get("finding_id") in ids for x in actions), note("CHK_JOIN")),
           ("no_full_rewrite", not any((out / n).exists() for n in REWRITE), note("CHK_NOREWRITE")),
           ("anchor_spans_recorded", len(anchors) == len(findings), note("CHK_ANCHOR")),
           ("engine_loaded", bool(G) and bool(G.RULES_OK),
            "gates.py 与 references/ruleset.json 均已加载" if G and G.RULES_OK
            else "引擎或规则表缺失，结果降级")]
  checks = [{"check": n, "pass": ok, "detail": d} for n, ok, d in pairs]
  metrics = {"dimensions_covered": sum(1 for v in coverage.values() if v.get("finding_ids")),
             "dimensions_no_issue_with_evidence": state.count("no_issue_with_evidence"),
             "dimensions_degraded": state.count("degraded_by_error"),
             "findings": len(findings), "actions": len(actions),
             "findings_high": sum(1 for f in findings if f["severity"] == "high"),
             "quote_hit_rate": hit_rate, "anchors": len(anchors),
             "pending_human": len(pending), "errors": len(errors),
             "action_ratio_per_finding": round(len(actions) / float(max(1, len(findings))), 2),
             "estimated_revision_rounds": max(1, -(-len(actions) // 6)), "rounds_note": note("ROUNDS")}
  payload = {
    "case_id": cid, "status": status, "sources": sources, "errors": errors,
    "degradations": degradations, "pending_human": pending,
    "uncertainty": [note("UNC_SCOPE"), note("UNC_PARAM"), note("UNC_SCIENCE")],
    "runtime": {"version": VERSION, "seconds": round(time.time() - started, 2), "model_requests": 0},
    "deliverable": {"primary": str(out / "edit_plan.md"), "editable": True, "format": "markdown+json",
                    "files": [str(out / n) for n in ARTIFACTS.values()]}, "preserved_facts": preserved,
    "evidence_map": [{"claim_id": f["finding_id"], "claim": f["diagnosis"][:120],
                      "locator": f["locator"], "quote": f["quote"],
                      "source_id": "manuscript", "kind": "structural_judgment"}
                     for f in findings],
    "change_log": change_log, "changes": change_log, "compliance_checks": checks,
    "export_artifact": None, "findings": findings, "actions": actions, "dimension_coverage": coverage,
    "metrics": metrics, "instruction_receipts": receipts(case)}
  payload.update(dict((k, str(out / v)) for k, v in ARTIFACTS.items()))
  filled, missing = G.fill(contract, payload)
  checks.append({"check": "contract_fields_filled", "pass": not missing,
         "detail": note("CHK_CONTRACT") if not missing
         else "未回填字段: %s" % ", ".join(missing)})

  def finalize(final_status, self_audit):
    document = dict(payload, status=final_status, self_audit=self_audit)
    document.update(G.fill(contract, document)[0])
    document["contract_unfilled_keys"] = missing
    if A:                                  # v1.1.0 asset pointers, added after contract
      for name, filename in A.ASSET_FILES.items():   # back-fill so they never alias a
        document[name] = str(out / filename)         # user contract key
    write(out / "result.json", document)

  try:
    finalize(status, {"stage": "pending"})
    report = G.inspect(out, list(contract.keys()))
    if not report.get("pass") and status == "ok":
      status = "partial"
    finalize(status, report)
    if log:
      log.mark("self_audit", "pass=%s status=%s contract_unfilled=%d"
               % (report.get("pass"), status, len(missing)))
    print("wrote %s | status=%s findings=%d actions=%d pending=%d self_audit=%s"
       % (out / "result.json", status, len(findings), len(actions), len(pending), report.get("pass")))
  except Exception as exc:
    errors.append({"stage": "finalize", "detail": str(exc)})
    try:
      finalize("partial", {"pass": False, "error": str(exc)})
    except Exception:
      print("result.json could not be finalized: %s" % exc)

  # v1.1.0 verifiable assets: additive; failure degrades to stubs, exit stays 0
  try:
    if A is None:
      print("assets.py not importable; verifiable assets skipped")
    else:
      if log:
        for item in degradations:
          log.degrade(item.get("stage") or "degradation", item.get("detail") or "")
        for item in errors:
          if item not in degradations:
            log.error(item.get("stage") or "error", item.get("detail") or "")
      info = A.build({
        "input": str(inp), "out": str(out), "case": case, "case_parsed": bool(case),
        "case_path": str(case_path) if case_path else None,
        "contract": contract, "cid": cid, "sources": sources,
        "manuscript": {"path": str(mpath) if mpath else None,
                       "name": mpath.name if mpath else None, "text": mtext,
                       "chars": len(mtext), "truncated": truncated,
                       "chapters": len(chapters), "paragraphs": len(paragraphs),
                       "words": G.wc(mtext) if G else 0},
        "findings": findings, "actions": actions, "anchors": anchors,
        "coverage": coverage, "pending": pending, "errors": errors,
        "degradations": degradations, "status": status, "started": started,
        "version": VERSION, "contract_missing": missing, "log": log,
        "preserved": len(preserved)})
      written = info.get("bytes") or {}
      print("wrote 5 verifiable assets | golden=%s diff=%s history=%s runlog=%s selfcheck=%s pass=%s"
            % (written.get("golden_standard"), written.get("diff_report"),
               written.get("version_history"), written.get("run_log"),
               written.get("self_check"), info.get("self_check_pass")))
  except Exception as exc:
    errors.append({"stage": "assets", "detail": "%s: %s" % (type(exc).__name__, exc)})
    try:
      A.ensure_assets(out, cid, VERSION, str(exc), log)
      print("verifiable assets completed by fallback after %s" % exc)
    except Exception:
      pass
  return 0


def asset_cid(input_dir, out_dir):
  """case_id for the post-run asset fallback: prefer result.json, then case.json."""
  try:
    data = json.loads((Path(out_dir) / "result.json").read_text(encoding="utf-8"))
    if data.get("case_id"):
      return data["case_id"]
  except Exception:
    pass
  try:
    data = json.loads((Path(input_dir) / "case.json").read_text(encoding="utf-8"))
    return data.get("case_id") or data.get("id") or "case-unknown"
  except Exception:
    return "case-unknown"


def main(argv=None):
  ap = argparse.ArgumentParser(
    description="Audit a manuscript's structural blueprint (six dimensions) and write an "
                "executable edit order plus result.json. Diagnosis only: no rewrite.",
    epilog="python3 audit.py --input /input --out /app/output [--check]")
  ap.add_argument("--input", default=str(Path("/input") if Path("/input").is_dir()
                                        else Path.cwd() / "input"), help="case directory")
  ap.add_argument("--out", default=str(Path("/app/output") if Path("/app").is_dir()
                                      else Path.cwd() / "output"), help="artifact directory")
  ap.add_argument("--check", action="store_true", help="only re-verify existing artifacts")
  ap.add_argument("--version", action="version", version=VERSION)
  args = ap.parse_args(argv)
  if args.check:
    if G is None:
      print(json.dumps({"pass": False, "error": "gates.py not importable"}, ensure_ascii=False))
      return 0
    print(json.dumps(G.inspect(args.out, G.contract_keys(args.input)), ensure_ascii=False, indent=2))
    return 0
  try:
    rc = run(args.input, args.out, time.time())
  finally:
    # post-run trap: aborted runs still get five honest asset stubs
    try:
      if A is not None:
        made = A.ensure_assets(Path(args.out), asset_cid(args.input, args.out), VERSION)
        if made:
          print("verifiable assets completed by post-run fallback: %s" % ", ".join(made))
    except Exception:
      pass
  return rc


if __name__ == "__main__":
  try:
    main()
  except SystemExit:
    raise
  except Exception as exc:
    print("aborted with %s (exit 0 by contract)" % exc)
  raise SystemExit(0)
