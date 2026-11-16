#!/usr/bin/env python3
"""Runner for the figure-evidence-lens skill.

Standard library only, no network, independent of the working directory, and it
always exits 0. Stages: locate the case, drop a first-pass partial result.json,
inspect each raster, copy literal tables verbatim, fit axes and trace curves from
the agent readings, audit the evidence, then finalise the contract payload.
"""
import argparse, csv, io, json, re, sys, time, traceback, zipfile, zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
  import raster_ops as RA
  IMPORT_ERR = ""
except Exception as e:
  RA, IMPORT_ERR = None, str(e)
BASE_DIR = Path(__file__).resolve().parent.parent
VERSION = "1.0.0"
READABILITY_VALUES = ("directly_read", "inferred", "undetermined")
NUMBER_PATTERN = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
FIGURE_FIELDS = ("figure_id", "panel", "caption", "image_px", "plot_box_px", "ticks_px",
      "spacing", "axes", "color_clusters", "legend_candidates", "elements", "digitized",
      "traceable", "warnings", "calibration_notes")


def utc_stamp():
  return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def dump_json(p, o):
  p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
  p.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(p):
  try:
    # self-increment: tolerate a UTF-8 BOM, which plain utf-8 decoding rejects
    return json.loads(Path(p).read_text(encoding="utf-8-sig", errors="replace")), ""
  except Exception as e:
    return None, "%s: %s" % (type(e).__name__, e)


def digest_file(p):
  h = __import__("hashlib").sha256()
  with open(p, "rb") as f:
    for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
  return h.hexdigest()


def collapse_text(t):
  """Squash spacing and punctuation so a quote can still be matched verbatim."""
  t = re.sub(r"[\u2010-\u2015\u2212]", "-", t or "")
  t = re.sub(r"[\u2018\u2019]", "'", re.sub(r"[\u201c\u201d]", '"', t))
  return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff%.+-]", "", t).lower()


def collect_floats(t):
  return [float(x) for x in NUMBER_PATTERN.findall(str(t))]


def parse_label_number(v):
  """Turn a printed tick label into a float (thousands separators, 1e3, 10^3)."""
  if isinstance(v, (int, float)): return float(v)
  s = str(v if v is not None else "").strip().replace(",", "").replace("\u2212", "-")
  m = re.match(r"^10\s*\^\s*([-+]?\d+)$", s)
  if m: return 10.0 ** int(m.group(1))
  m = NUMBER_PATTERN.search(s)
  try: return float(m.group(0)) if m else None
  except ValueError: return None


def scope_objects(case_doc):
  """Collect the mandatory objects by meaning; no hard-coded JSON key names."""
  haystack, tids = json.dumps(case_doc, ensure_ascii=False), []

  def walk(o):
    if isinstance(o, dict):
      for k, v in o.items():
        if isinstance(v, list) and "table" in k.lower() and all(isinstance(x, str) for x in v):
          tids.extend(v)
        walk(v)
    elif isinstance(o, list):
      for v in o: walk(v)

  walk(case_doc)
  seen, raster_paths = set(), []
  for f in re.findall(r"[\w./\-]+\.(?:png|jpe?g|tiff?|bmp)", haystack):
    if Path(f).name not in seen:
      seen.add(Path(f).name)
      raster_paths.append(f)
  return raster_paths, sorted({t for t in tids if t})


def extract_source_text(p):
  k = RA.magic_kind(p) if RA else "text"
  if k == "pdf": return RA.pdf_strings(p)
  if k in ("text", "csv", "json"):
    try: return Path(p).read_text(encoding="utf-8", errors="replace")[:400000]
    except OSError: return ""
  return ""


# ------------------------------------------------- stage: figure reading
def locate_readings(cli, src_dir, work_dir, dst_dir):
  for p in ([Path(cli)] if cli else []) + [work_dir / "readings.json", src_dir / "readings.json",
                                          dst_dir / "readings.json", BASE_DIR / "readings.json"]:
    if p and Path(p).is_file():
      o, e = read_json(p)
      return (o if isinstance(o, dict) else {}), str(p), e
  return {}, "", "readings.json not found"


def figure_reading(reading, source_key):
  f = reading.get("figures") or {}
  return f.get(source_key) or f.get(Path(source_key).name) or {}


def fit_axes(fig, reading):
  """Pair agent tick labels with detected tick pixels, then least-squares fit."""
  axes, axis_notes, det = {}, [], fig.get("ticks_px") or {}
  for key in ("x", "y", "y2"):
    contract = (reading.get("axes") or {}).get(key)
    if not isinstance(contract, dict): continue
    labels = contract.get("tick_labels") or contract.get("labels") or []
    labels = [labels] if isinstance(labels, (str, int, float)) else labels
    positions = contract.get("tick_px") or det.get(key if key != "y2" else "y") or []
    vals = [v for v in (parse_label_number(x) for x in labels) if v is not None]
    if not (vals and positions):
      axis_notes.append({"axis": key, "issue": "tick labels or tick pixels missing",
                    "n_labels": len(labels), "n_tick_px": len(positions)})
      continue
    if len(labels) != len(positions):
      axis_notes.append({"axis": key, "issue": "label/pixel count mismatch", "n_labels": len(labels),
                    "n_detected_ticks": len(positions), "action": "pairing from the axis origin"})
    n = min(len(vals), len(positions))
    fitted = RA.fit_scale(positions[:n], vals[:n], contract.get("scale", "auto"))
    if fitted:
      fitted.update({"axis": key, "unit": contract.get("unit"), "label": contract.get("label"),
                  "tick_labels": labels, "tick_px": positions[:n]})
      axes[key] = fitted
  return axes, axis_notes


def audit_result(doc, state):
  """Repeatable audit: contract backfill, claim schema, verbatim quote hits."""
  problems, per_claim = [], []
  absent = [k for k in state["contract"] if k not in doc]
  if absent: problems.append("contract keys missing: %s" % absent)
  for c in doc.get("claims") or []:
    evidence, claim_issues = c.get("evidence") or {}, []
    claim_key = c.get("claim_id") or "?"
    for f in ("kind", "text", "evidence", "readability", "conditions"):
      if not c.get(f): claim_issues.append("missing field %s" % f)
    for f in ("quote", "quote_type", "source_id", "location"):
      if not evidence.get(f): claim_issues.append("evidence missing %s" % f)
    if c.get("readability") not in READABILITY_VALUES: claim_issues.append("invalid readability %r" % c.get("readability"))
    quoted, quote_kind, source_key = evidence.get("quote") or "", evidence.get("quote_type"), str(evidence.get("source_id"))
    corpus = state["texts"].get(source_key) or state["texts"].get(Path(source_key).name) or ""
    matched = "n/a"
    if quote_kind == "text" and quoted:
      if not corpus:
        matched = "source_not_indexed"; claim_issues.append("quote source not indexed: %s" % source_key)
      elif quoted in corpus: matched = "exact"
      elif collapse_text(quoted) and collapse_text(quoted) in collapse_text(corpus): matched = "normalized"
      else:
        matched = "not_found"; claim_issues.append("verbatim quote not found in source")
    elif quote_kind == "visual":
      positions = (state["figures"].get(source_key) or {}).get("image_px") or {}
      bbox = (evidence.get("location") if isinstance(evidence.get("location"), dict) else {}).get("bbox_px")
      if bbox and positions:
        ok = 0 <= bbox[0] <= bbox[2] <= positions.get("w", 0) and 0 <= bbox[1] <= bbox[3] <= positions.get("h", 0)
        matched = "bbox_in_bounds" if ok else "bbox_out_of_bounds"
        if not ok: claim_issues.append("visual bbox outside image")
      else: matched = "locator_only"
    per_claim.append({"claim_id": claim_key, "issues": claim_issues, "quote_match": matched})
    problems += ["%s: %s" % (claim_key, i) for i in claim_issues]
  blocking = [i for i in problems if any(k in i for k in (
      "missing field", "evidence missing", "not found in source", "outside image",
      "invalid readability", "contract keys missing"))]
  # self-increment: publish how much of the declared scope was actually covered and
  # how many claims found traceable evidence, so a reviewer can compare runs at a glance.
  marks = [c["quote_match"] for c in per_claim]
  hits = marks.count("exact") + marks.count("normalized") + marks.count("bbox_in_bounds")
  coverage = (state.get("payload") or {}).get("coverage") or {}
  image_rows, table_rows = coverage.get("images") or [], coverage.get("tables") or []
  open_gaps = list(coverage.get("missing_images") or []) + \
    list(coverage.get("missing_tables") or [])
  declared_total = len(image_rows) + len(table_rows)
  parsed_total = sum(1 for c in image_rows if c.get("analyzed")) + \
    sum(1 for c in table_rows if c.get("resolved"))
  return {"checked_at": utc_stamp(), "n_claims": len(doc.get("claims") or []),
          "n_contract_keys": len(state["contract"]), "issues": problems[:60],
          "claim_checks": per_claim, "hard_failures": len(blocking),
          "evidence_metrics": {
            "claims_audited": len(per_claim),
            "evidence_hits": hits,
            "hit_rate": round(hits / len(per_claim), 4) if per_claim else None,
            "locator_only": marks.count("locator_only"),
            "undetermined_safe": marks.count("n/a")},
          "scope_coverage": {
            "images_declared": len(image_rows),
            "images_parsed": sum(1 for c in image_rows if c.get("analyzed")),
            "tables_declared": len(table_rows),
            "tables_parsed": sum(1 for c in table_rows if c.get("resolved")),
            "open_gaps": open_gaps,
            "complete": declared_total > 0 and parsed_total == declared_total
                    and not open_gaps}}


def finalize_result(state):
  """Always emit a legal result.json: contract keys seeded first, extras kept."""
  contract, result_body = state["contract"], state["payload"]
  final = {}
  for k in contract: final[k] = None
  for k, v in (("case_id", state["case_id"]), ("status", state["status"]), ("result", result_body),
              ("claims", state["claims"]), ("uncertainties", state["uncertainties"]),
              ("uncertainty", state["uncertainty"]), ("sources", state["sources"]),
              ("pending_human", state["pending_human"]), ("errors", state["errors"]),
              ("degradations", state["degradations"]), ("changes", state["changes"]),
              ("runtime", state["runtime"])):
    final[k] = final[k] if final.get(k) is not None else v
  final["output_contract_spec"] = contract
  final["skill"] = {"name": "figure-evidence-lens", "version": VERSION,
                    "readability_levels": list(READABILITY_VALUES)}
  final["verification"] = audit_result(final, state)
  if final["verification"]["hard_failures"] and final["status"] in ("answered", "ok"):
    final["status"] = state["status"] = "partial"
    final["errors"].append("status downgraded: verification failure")
  dump_json(state["out"] / "result.json", final)
  return final


def pipeline(state):
  src_dir, dst_dir = state["input"], state["out"]
  note_change, note_degrade = state["changes"].append, state["degradations"].append
  note_uncertainty, note_pending = state["uncertainties"].append, state["pending_human"].append
  case_doc, load_err = read_json(src_dir / "case.json")
  if case_doc is None:
    for p in sorted(src_dir.rglob("case*.json")):
      case_doc, load_err = read_json(p)
      if case_doc is not None:
        note_change({"step": "discover", "note": "case read from %s" % p.name}); break
  case_doc = case_doc if isinstance(case_doc, dict) else {}
  if not case_doc:
    state["errors"].append("case.json could not be parsed: %s" % load_err)
    state["status"] = "insufficient_evidence" if "FileNotFound" in load_err else "input_error"
    state["uncertainty"]["fatal"] = "no case: %s" % load_err
  state["case"] = case_doc
  state["contract"] = case_doc.get("output_contract") if isinstance(case_doc.get("output_contract"), dict) else {}
  state["case_id"] = case_doc.get("case_id") or "unknown-case"
  input_files = RA.walk_files(src_dir)
  state["sources"] = [{"source_id": str(p.relative_to(src_dir)),
                    "kind": (RA.magic_kind(p) if RA else "text"), "bytes": p.stat().st_size,
                    "sha256": digest_file(p), "path": str(p)} for p in input_files]
  for p in input_files:
    if p.suffix.lower() in (".md", ".txt", ".json", ".csv", ".pdf") and p.name != "case.json":
      t = extract_source_text(p)
      if t: state["texts"][str(p.relative_to(src_dir))] = t
  if (src_dir / "task.md").is_file():
    state["texts"]["task.md"] = (src_dir / "task.md").read_text(errors="replace")
  state["runtime"]["input_files"] = len(input_files)
  dump_json(dst_dir / "result.json", {"case_id": state["case_id"], "status": "partial", "result": None,
                          "claims": [], "uncertainties": [], "sources": state["sources"],
                          "note": "first-pass partial shell",
                          "runtime": state["runtime"]})
  note_change({"step": "partial", "note": "first-pass partial result.json in place"})
  required_images, required_tables = scope_objects(case_doc)
  readings_doc, readings_path, readings_error = locate_readings(state["cli_readings"], src_dir, state["work"], dst_dir)
  if readings_error:
    note_degrade("readings unavailable: %s" % readings_error)
    state["uncertainty"]["visual_readings"] = ("No readings.json: axis labels, units, legend text "
                                            "and captions not attached; only pixel-structural "
                                            "facts are reported.")
  else:
    note_change({"step": "readings", "note": "absorbed %s" % readings_path})
  figure_map, image_coverage, missing_images = {}, [], []
  raster_paths = [p for p in input_files if (RA.magic_kind(p) if RA else "") in ("png", "bmp", "jpeg", "tiff")]
  for p in raster_paths[:8]:
    source_key = str(p.relative_to(src_dir))
    if not RA or RA.magic_kind(p) != "png":
      figure_map[source_key] = {"file": source_key, "traceable": False, "image_px": {},
                  "warnings": ["no decoder for %s" % (RA.magic_kind(p) if RA else "?")]}
      note_degrade("%s: raster decode unsupported, visual reading only" % source_key)
      note_pending({"item": source_key, "why": "offline decoder unavailable",
          "action": "supply axis, legend and points through readings.json"})
      continue
    f, reading = RA.inspect_image(p), figure_reading(readings_doc, source_key)
    f["source_id"] = source_key
    for k in ("figure_id", "panel", "caption"): f[k] = reading.get(k)
    f["elements"] = reading.get("elements") or {}
    axes, axis_notes = fit_axes(f, reading) if reading else ({}, [])
    f["axes"], f["calibration_notes"] = axes, axis_notes
    for n in axis_notes: note_uncertainty({"kind": "calibration", "figure": source_key, "detail": n})
    figure_map[source_key] = f
    image_coverage.append({"source_id": source_key, "analyzed": True,
                "declared": any(Path(r).name == p.name for r in required_images)})
  for r in required_images:
    if not any(Path(r).name == Path(c["source_id"]).name for c in image_coverage):
      missing_images.append(r)
      state["uncertainty"].setdefault("missing_materials", []).append(r)
  state["figures"] = figure_map
  table_records = []
  for p in input_files:
    kind, source_key = (RA.magic_kind(p) if RA else ""), str(p.relative_to(src_dir))
    try:
      if kind == "csv":
        t = RA.csv_to_table(p); t.update({"table_id": Path(p).stem, "source_id": source_key})
        table_records.append(t)
      elif kind == "json":
        for t in RA.json_inline_tables(read_json(p)[0] or {}):
          t["source_id"] = source_key; table_records.append(t)
      elif kind in ("xlsx", "docx"):
        note_degrade("%s: Office container kept as text source; cells not parsed" % source_key)
    except Exception as e:
      note_degrade("%s: table extraction failed (%s)" % (source_key, e))
  if table_records:
    dump_json(dst_dir / "tables.json", table_records)
    for i, t in enumerate(table_records):
      try:
        (dst_dir / "tables").mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^\w.-]+", "_", str(t.get("table_id") or "t%d" % i))[:60]
        with open(dst_dir / "tables" / (slug + ".csv"), "w", newline="", encoding="utf-8") as fh:
          csv.writer(fh).writerows(t.get("grid") or [])
      except Exception as e: note_degrade("table csv write failed: %s" % e)
  haystack = collapse_text(" ".join(state["texts"].values())) + collapse_text(json.dumps(case_doc, ensure_ascii=False)) + \
      collapse_text(json.dumps(table_records, ensure_ascii=False))
  table_coverage, missing_tables = [], []
  for table_id in required_tables:
    located = collapse_text(table_id) in haystack
    table_coverage.append({"table_id": table_id, "resolved": located})
    if not located:
      missing_tables.append(table_id)
      note_pending({"item": table_id, "why": "scope table id not located",
          "action": "locate the literal table or confirm absence"})
  digitized_rows = []
  for source_key, f in figure_map.items():
    reading, axis_map = figure_reading(readings_doc, source_key), f.get("axes") or {}
    if not reading.get("series") or not f.get("traceable") or not axis_map.get("y"): continue
    try: img, meta = RA.open_raster(src_dir / source_key)
    except Exception as e:
      note_degrade("%s: re-decode failed (%s)" % (source_key, e)); continue
    box = tuple(int(round(v / meta["analysis_scale"])) for v in f["plot_box_px"])
    for s in reading.get("series") or []:
      if not (s.get("digitize") and s.get("rgb")): continue
      traced = RA.series_from_pixels(img, box, s["rgb"], axis_map.get("x"), axis_map["y"],
                            meta["analysis_scale"], tol=int(s.get("tol", 60)))
      for r in traced:
        r.update({"figure": f.get("figure_id") or source_key, "panel": f.get("panel"),
                  "series": s.get("name") or str(s.get("rgb")),
                  "x_unit": (axis_map.get("x") or {}).get("unit"), "y_unit": axis_map["y"].get("unit")})
        digitized_rows.append(r)
      f.setdefault("digitized", []).append({"series": s.get("name"), "rgb": s.get("rgb"),
                                            "n_points": len(traced), "source_id": source_key})
  if digitized_rows:
    csv_fields = ["figure", "panel", "series", "x", "y", "y_lo", "y_hi", "x_unit", "y_unit",
            "err_x_data", "err_y_data", "x_px", "y_px", "approx"]
    with open(dst_dir / "digitized_series.csv", "w", newline="", encoding="utf-8") as fh:
      wr = csv.DictWriter(fh, fieldnames=csv_fields, extrasaction="ignore")
      wr.writeheader()
      for r in digitized_rows: wr.writerow(r)
  dump_json(dst_dir / "figure_structure.json", figure_map)
  claim_list = []
  for i, c in enumerate(readings_doc.get("claims") or [], 1):
    evidence = c.get("evidence") or {}
    claim_list.append({
        "claim_id": c.get("claim_id") or "c%02d" % i, "kind": c.get("kind") or "value",
        "text": c.get("text"),
        "evidence": {"quote": evidence.get("quote") or "",
                    "quote_type": evidence.get("quote_type") or
                    ("visual" if evidence.get("bbox_px") or evidence.get("figure") else "text"),
                    "source_id": evidence.get("source_id"), "location": evidence.get("location") or {},
                    "read_basis": evidence.get("read_basis") or ""},
        "readability": c.get("readability") or "undetermined",
        "conditions": c.get("conditions") or "as shown in the supplied material"})
  state["claims"] = claim_list
  for u in readings_doc.get("uncertainties") or []: note_uncertainty(u if isinstance(u, dict) else {"note": str(u)})
  for x in readings_doc.get("pending_human") or []: note_pending(x if isinstance(x, dict) else {"item": str(x)})
  tally = {"required_images": len(required_images), "images_analyzed": len(image_coverage),
            "images_missing": len(missing_images), "tables_extracted": len(table_records),
            "required_tables": len(required_tables),
            "required_tables_resolved": sum(1 for c in table_coverage if c["resolved"]),
            "claims": len(claim_list), "digitized_points": len(digitized_rows)}
  images_complete = len(image_coverage) >= len(required_images) if required_images else bool(image_coverage)
  state["payload"] = {
      "task": case_doc.get("task_instruction") or "", "domain": case_doc.get("domain"),
      "figures": {source_key: {k: f.get(k) for k in FIGURE_FIELDS} for source_key, f in figure_map.items()},
      "tables": [{"table_id": t.get("table_id"), "source_id": t.get("source_id"),
                  "columns": t.get("columns"), "n_rows": t.get("n_rows")} for t in table_records],
      "digitized_series_file": "digitized_series.csv" if digitized_rows else None,
      "coverage": {"images": image_coverage, "tables": table_coverage, "missing_images": missing_images,
                  "missing_tables": missing_tables}, "counts": tally}
  state["status"] = state["status"] if state["status"] == "input_error" else \
      ("answered" if (claim_list and images_complete and not missing_images and not readings_error)
                  else "partial" if (figure_map or table_records or claim_list) else "insufficient_evidence")
  if state["status"] == "partial":
    state["uncertainty"]["scope"] = ("analysed objects only; unlisted figures or "
                                  "tables are declared gaps")
  state["uncertainty"]["counts"] = tally


def make_parser():
  p = argparse.ArgumentParser(
      description="figure-evidence-lens: case dir -> result.json, figure_structure.json, digitized_series.csv and audited claims",
      epilog="Example: python figure_runner.py --input ./input --output ./output --readings ./readings.json")
  p.add_argument("--input", help="case dir (case.json, task.md, artifacts/)")
  p.add_argument("--output", help="output dir for result.json and artefacts")
  p.add_argument("--readings", help="Agent visual readings JSON")
  p.add_argument("--version", action="version", version=VERSION)
  return p


def resolve_directory(cli, cands, create=False):
  for c in ([cli] if cli else []) + cands:
    if not c: continue
    if Path(c).is_dir(): return Path(c)
    if create and c == cli:
      try:
        Path(c).mkdir(parents=True, exist_ok=True); return Path(c)
      except OSError: pass
  if create:
    for c in cands:
      try:
        Path(c).mkdir(parents=True, exist_ok=True); return Path(c)
      except OSError: continue
  return Path(cands[-1])


def main_entry(argv=None):
  opt = make_parser().parse_args(argv)
  started = time.time()
  src_dir = resolve_directory(opt.input, ["/input", str(BASE_DIR / "input")])
  dst_dir = resolve_directory(opt.output, ["/app/output", str(BASE_DIR.parent / "output")], create=True)
  work_dir = dst_dir / "work"
  try: work_dir.mkdir(parents=True, exist_ok=True)
  except OSError: work_dir = dst_dir
  state = {"cli_readings": getattr(opt, "readings"), "input": src_dir, "out": dst_dir, "work": work_dir, "contract": {},
        "case": {}, "case_id": "unknown-case", "claims": [], "uncertainties": [],
        "pending_human": [], "sources": [], "errors": [], "degradations": [], "changes": [],
        "figures": {}, "texts": {}, "payload": {}, "status": "partial", "uncertainty": {},
        "runtime": {"skill": "figure-evidence-lens", "version": VERSION,
                    "started_utc": utc_stamp(), "python": sys.version.split()[0],
                    "input_dir": str(src_dir), "output_dir": str(dst_dir),
                    "raster_ops": "ok" if RA else IMPORT_ERR[:120]}}
  if not RA: state["degradations"].append("raster_ops import failed: %s" % IMPORT_ERR)
  try:
    pipeline(state)
  except Exception:
    state["errors"].append("fatal: " + traceback.format_exc(limit=3).replace("\n", " | ")[:900])
    state["status"] = "partial" if state.get("payload") else "insufficient_evidence"
    state["uncertainty"]["fatal"] = "run aborted; see errors"
  finally:
    try:
      state["runtime"].update({"duration_s": round(time.time() - started, 2), "finished_utc": utc_stamp()})
      finalize_result(state)
    except Exception:
      try:
        dump_json(state["out"] / "result.json", {
            "case_id": state.get("case_id", "unknown-case"), "status": "input_error",
            "result": None, "claims": [], "uncertainties": state.get("uncertainties", []),
            "errors": state.get("errors", []) + ["finalize failed"],
            "runtime": state.get("runtime", {})})
      except Exception: pass
  print(json.dumps({"status": state.get("status"), "output": str(state["out"]),
                    "errors": len(state["errors"]), "degradations": len(state["degradations"]),
                    "claims": len(state.get("claims") or [])}, ensure_ascii=False))
  return 0


if __name__ == "__main__":
  try: sys.exit(main_entry())
  except SystemExit: raise
  except Exception: sys.exit(0)
