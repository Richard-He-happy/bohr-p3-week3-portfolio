"""main.py - four-phase shell for the cross-paper field matrix (stdlib only, exit 0)."""
import argparse
import csv
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_check as EC

ENGINE = "cross-paper-field-matrix v1"
GENERIC_DIMENSIONS = ["task", "dataset", "sample", "material", "method", "metric", "unit", "budget"]
CSV_COLUMNS = ["source_document_id", "field_id", "field_name", "value", "unit", "dataset",
               "metric_scope", "status", "confidence", "quote", "locator", "note"]
def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig", errors="replace"))


def _write_json(path, payload):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def _write_text(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def resolve_dirs(args):
    return (Path(args.input or os.environ.get("SKILL_INPUT", "/input")),
            Path(args.output or os.environ.get("SKILL_OUTPUT", "/app/output")),
            Path(args.work or os.environ.get("SKILL_WORK", "/app/work")))


def iter_pairs(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield str(key), value
            yield from iter_pairs(value)
    elif isinstance(obj, list):
        for value in obj[:40]:
            yield from iter_pairs(value)


def locate_case(input_dir, errors):
    if not input_dir.exists():
        errors.append({"code": "input_missing", "detail": "input dir not found: %s" % input_dir})
        return {}, None
    candidates = sorted(input_dir.rglob("case.json")) or sorted(input_dir.rglob("*.json"))
    for path in candidates:
        try:
            return _read_json(path), path
        except Exception as exc:
            errors.append({"code": "case_json_invalid",
                           "detail": "%s: %r" % (path.name, exc)})
    return {}, None


def locate_workorder(case, files):
    for path in files:
        if "workorder" in path.name.lower() and path.suffix.lower() == ".json":
            try:
                return _read_json(path), path.name
            except Exception:
                pass
    embedded = next(((value, "case:" + key) for key, value in iter_pairs(case)
                     if "workorder" in key.lower() and isinstance(value, dict)), ({}, ""))
    return embedded


def workorder_fields(workorder):
    source = None
    aliases = ("fields", "field_definitions", "common_fields", "comparison_fields",
               "columns", "schema", "dimensions")
    for key, value in iter_pairs(workorder):
        if key.lower() in aliases and isinstance(value, (list, dict)) \
                and (source is None or len(str(value)) > len(str(source))):
            source = value
    if isinstance(source, dict):
        source = [{"name": key,
                   "definition": value if isinstance(value, str)
                   else json.dumps(value, ensure_ascii=False)}
                  for key, value in source.items()]
    fields = EC.normalize_fields({"fields": source or []}) \
        or [{"field_id": name, "name": name} for name in GENERIC_DIMENSIONS]
    return [dict({"definition": "", "unit": "", "value_rule": ""}, **item) for item in fields]


def workorder_papers(workorder):
    aliases = ("papers", "documents", "corpus", "sources", "source_documents", "paper_list")
    raw = next((value for key, value in iter_pairs(workorder)
                if key.lower() in aliases and isinstance(value, list) and value), [])

    def pick(item, *names):
        return next((str(item[name]) for name in names
                     if isinstance(item, dict) and item.get(name)), "")

    papers = []
    for idx, item in enumerate(raw):
        papers.append({
            "doc_id": pick(item, "doc_id", "id", "source_document_id") or "D%d" % (idx + 1),
            "title": item if isinstance(item, str) else pick(item, "title", "name"),
            "file": pick(item, "file", "filename", "path"),
        })
    return papers


def bind_doc_ids(papers, docs):
    binding = {}
    for paper in papers:
        filename = os.path.basename(paper.get("file") or "").lower()
        target = next((doc_key for doc_key, doc in docs.items()
                       if filename and (filename in doc["filename"].lower()
                                        or doc["filename"].lower() in filename)), None)
        if target and target not in binding:
            binding[target] = paper["doc_id"]
    for key, doc in docs.items():
        doc["doc_id"], doc["workorder_id"] = binding.get(key, key), binding.get(key)
    return docs


def ensure_cell_grid(docs, fields, cells, degradations):
    present = {(cell.get("doc_id"), cell.get("field_id")) for cell in cells}
    before = len(cells)
    for doc_id in docs:
        for field in fields:
            if (doc_id, field["field_id"]) not in present:
                cells.append({
                    "doc_id": doc_id, "field_id": field["field_id"],
                    "field_name": field["name"], "unit": field.get("unit") or "",
                    "dataset": "", "metric_scope": "", "confidence": "fallback",
                    "value": None, "quote": None, "locator": None,
                    "status": "unreported", "note": "read this paper and fill by hand",
                })
    added = len(cells) - before
    if added:
        degradations.append("%d cell(s) missing from the draft were added as unreported placeholders"
                            % added)
    return cells


def derive_sections(fields, cells):
    comparability = []
    for dimension in GENERIC_DIMENSIONS:
        hit_fields = [field["field_id"] for field in fields
                      if dimension in (field["field_id"] + str(field["name"])).lower()]
        values = {cell["doc_id"]: EC.canon(str(cell.get("value")), True)
                  for cell in cells
                  if cell.get("field_id") in hit_fields and cell.get("status") == "reported"}
        if values:
            comparability.append(dict(
                dimension=dimension, doc_ids=sorted(values),
                comparable=len(set(values.values())) == 1,
                basis="%d distinct value(s) over %d document(s); pool only within strata"
                      % (len(set(values.values())), len(values))))
    reported = sum(cell.get("status") == "reported" for cell in cells)
    agreement = {
        "overall": "insufficient" if not reported else "partially_consistent",
        "items": [dict(topic="overall effect direction",
                       verdict="insufficient" if not reported else "partially_consistent",
                       attribution="unresolved",
                       explanation="auto: %d reported cell(s); read the papers to assign direction"
                                   % reported)],
    }
    return comparability, agreement


def phase_init(args):
    started, (input_dir, output_dir, work_dir) = time.time(), resolve_dirs(args)
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    errors, degradations = [], []
    case, case_path = locate_case(input_dir, errors)
    case_id = str(case.get("case_id") or case.get("id")
                  or (case_path.parent.name if case_path else "unknown"))
    _write_json(output_dir / "result.json", EC.partial_result(case, case_id, errors))

    files = [path for path in sorted(input_dir.rglob("*")) if path.is_file()] if input_dir.exists() else []
    material_suffixes = (".pdf", ".docx", ".txt", ".md", ".csv", ".tsv",
                         ".json", ".html", ".xlsx", ".pptx")
    materials = [path for path in files
                 if path.suffix.lower() in material_suffixes
                 and path.name.lower() != "task.md"
                 and "case" not in path.name.lower()
                 and "workorder" not in path.name.lower()]
    workorder, workorder_source = locate_workorder(case, files)
    fields, docs = workorder_fields(workorder), {}
    for idx, path in enumerate(materials):
        try:
            doc = EC.read_document(path)
        except Exception as exc:
            errors.append({"code": "extract_failed", "detail": "%s: %r" % (path.name, exc)})
            doc = {"kind": EC.sniff_kind(path), "engine": "failed", "paras": [],
                   "text": "", "notes": ["extraction failed"]}
        doc.update(filename=path.name, path=str(path))
        docs["D%d" % (idx + 1)] = doc
        degradations += ["%s: %s" % (path.name, note) for note in doc.get("notes") or []]
    papers = workorder_papers(workorder)
    bind_doc_ids(papers, docs)

    _write_json(work_dir / "index.json", dict(
        case_id=case_id,
        case_path=str(case_path or ""),
        workorder_source=workorder_source,
        generated=time.strftime("%FT%T"),
        docs={doc["doc_id"]: dict(
            {key: doc.get(key) for key in ("filename", "kind", "engine", "n_pages",
                                           "quality", "notes", "path")},
            n_paras=len(doc["paras"]), text_chars=len(doc["text"]))
            for doc in docs.values()},
        paras={doc["doc_id"]: doc["paras"] for doc in docs.values()},
        texts={doc["doc_id"]: doc["text"] for doc in docs.values()},
        workorder=dict(question=str(workorder.get("question")
                                    or workorder.get("research_question") or ""),
                       fields=fields, papers=papers, source=workorder_source)))

    result = EC.partial_result(case, case_id, errors)
    result.update(
        sources=[dict(source_document_id=doc["doc_id"], file=doc["filename"],
                      kind=doc["kind"], engine=doc["engine"],
                      locator_scheme="<page>#para<n>") for doc in docs.values()],
        degradations=degradations,
        pending_human=["read the corpus, author %s, then run check and build"
                       % (work_dir / "draft.json")],
        runtime=dict(skill=ENGINE, stage="init", seconds=round(time.time() - started, 2),
                     docs=len(docs)))
    _write_json(output_dir / "result.json", result)

    print("== 材料索引 ==")
    for doc in docs.values():
        print("%s | %s | %s | %d paras | %s | wo=%s" % (
            doc["doc_id"], doc["filename"], doc["kind"], len(doc["paras"]),
            doc["engine"], doc.get("workorder_id")))
    print("== 比较要求 (%s) == %s | fields: %s | papers: %s" % (
        workorder_source or "none",
        workorder.get("question") or "(no question)",
        ", ".join(field["field_id"] for field in fields),
        ", ".join(paper["doc_id"] for paper in papers) or "(none)"))
    print("== 下一步 == 1) show --doc <id>  2) 写 %s  3) check  4) build"
          % (work_dir / "draft.json"))
    return 0


def phase_show(args):
    _, _, work_dir = resolve_dirs(args)
    index = _read_json(work_dir / "index.json")
    docs = index.get("docs") or {}
    paras = index.get("paras") or {}
    if args.doc and args.doc in paras:
        doc_paras = paras[args.doc]
        bounds = re.match(r"^(\d+)\s*[:\-]\s*(\d+)$", str(args.paras or ""))
        low, high = (int(bounds.group(1)), int(bounds.group(2))) if bounds else (1, len(doc_paras))
        for para in doc_paras[low - 1:high]:
            print("[%s %s] %s" % (args.doc, para["locator"], para["text"][:1200]))
        print("-- %s: %d paragraphs, showed %d..%d"
              % (args.doc, len(doc_paras), low, min(high, len(doc_paras))))
    else:
        listing = "\n".join("%s | %s | %s | %s paras"
                            % (key, value["filename"], value["kind"], value.get("n_paras"))
                            for key, value in docs.items())
        print(listing or "(empty corpus)")
    return 0


def phase_check(args):
    _, _, work_dir = resolve_dirs(args)
    draft, _ = load_draft(work_dir)
    if "_err" in draft:
        print(json.dumps({"ok": False,
                          "errors": [{"code": "draft_unreadable", "detail": draft["_err"]}]},
                         ensure_ascii=False))
        return 0
    report = EC.audit_draft(draft, _read_json(work_dir / "index.json"))
    print(json.dumps(report, ensure_ascii=False, indent=1))
    for error in report["errors"][:10]:
        print("FIX [%s] %s :: %s" % (error["code"], error["where"], error["detail"]))
    counts = report["counts"]
    print("coverage=%s quote_pass=%s reported=%s errors=%d"
          % (counts["coverage"], counts["quote_pass_rate"], counts["cells_reported"],
             len(report["errors"])))
    return 0


def load_draft(work_dir):
    path = work_dir / "draft.json"
    if not path.exists():
        return {}, ""
    try:
        return _read_json(path), str(path)
    except Exception as exc:
        return {"_err": repr(exc)}, str(path)


def gather_inputs(args, case, errors, pending, degradations):
    input_dir, _, work_dir = resolve_dirs(args)
    index = {}
    try:
        index = _read_json(work_dir / "index.json") if (work_dir / "index.json").exists() else {}
    except Exception as exc:
        errors.append({"code": "index_unreadable", "detail": repr(exc)})
    if not index.get("docs"):
        try:
            phase_init(args)
            index = _read_json(work_dir / "index.json")
        except Exception as exc:
            errors.append({"code": "init_failed", "detail": repr(exc)})
    docs, workorder = index.get("docs") or {}, index.get("workorder") or {}
    case_id = index.get("case_id") or str(case.get("case_id") or "unknown")
    draft, draft_source = load_draft(work_dir)
    if "_err" in draft:
        errors.append({"code": "draft_unreadable", "detail": draft["_err"]})
        draft = {}
    if not draft:
        degradations.append("no usable draft.json: cells kept as unreported placeholders "
                            "(no values invented)")
        pending.append("Agent must read the papers and fill every cell by hand")
    return input_dir, index, docs, workorder, case_id, draft, draft_source


def assemble_model(workorder, docs, case_id, draft, degradations):
    fields = EC.normalize_fields(draft) or workorder.get("fields") \
        or [dict(field_id=name, name=name, definition="", unit="", value_rule="")
            for name in GENERIC_DIMENSIONS]
    papers = [{**dict(filename=docs[paper["doc_id"]].get("filename"),
                      kind=docs[paper["doc_id"]].get("kind"),
                      n_paras=docs[paper["doc_id"]].get("n_paras"),
                      engine=docs[paper["doc_id"]].get("engine")),
               **paper}
              for paper in (EC.normalize_papers(draft) or [{"doc_id": doc_id} for doc_id in docs])
              if paper.get("doc_id") in docs]
    raw_cells = EC.matrix_rows(draft)
    cells = [cell for cell in raw_cells if cell.get("doc_id") in docs]
    if len(raw_cells) != len(cells):
        degradations.append("%d draft cell(s) cited absent documents and were dropped"
                            % (len(raw_cells) - len(cells)))
    for cell in cells:
        cell.setdefault("field_name", next((field["name"] for field in fields
                                            if field["field_id"] == cell.get("field_id")), ""))
        cell.setdefault("status", "reported" if cell.get("value") not in (None, "")
                        else "unreported")
        cell.setdefault("confidence", "draft")
    cells = ensure_cell_grid(docs, fields, cells, degradations)

    comparability = [item for item in (draft.get("comparability")
                                       or draft.get("comparability_checks") or [])
                     if isinstance(item, dict)]
    agreement = draft.get("agreement") or draft.get("synthesis") or {}
    if not comparability or not (isinstance(agreement, dict)
                                 and agreement.get("overall") and agreement.get("items")):
        auto_comp, auto_agreement = derive_sections(fields, cells)
        comparability = comparability or auto_comp
        agreement = (agreement if isinstance(agreement, dict) and agreement.get("items")
                     else auto_agreement)
        degradations.append("comparability/agreement partly derived from field values; "
                            "condition judgement pending")

    model = dict(
        case_id=case_id,
        question=draft.get("question") or workorder.get("question") or "",
        papers=papers, fields=fields, matrix=cells,
        comparability=comparability, agreement=agreement,
        limitations=draft.get("limitations") or [],
        uncertainty=draft.get("uncertainty") or [],
        degradations=degradations,
        artifacts=["comparison_matrix.csv", "comparison_table.md",
                   "evidence_cards.jsonl", "result.json"],
        sources=[dict(source_document_id=doc_id, file=docs[doc_id].get("filename"),
                      kind=docs[doc_id].get("kind"), engine=docs[doc_id].get("engine"),
                      n_paras=docs[doc_id].get("n_paras")) for doc_id in docs],
        evidence_cards=[dict(card_id="C%03d" % (idx + 1),
                             source_document_id=cell["doc_id"],
                             field_id=cell["field_id"],
                             value=cell.get("value"), unit=cell.get("unit"),
                             dataset=cell.get("dataset"),
                             metric_scope=cell.get("metric_scope"),
                             quote=cell.get("quote"), locator=cell.get("locator"))
                        for idx, cell in enumerate(c for c in cells
                                                   if c.get("status") == "reported")])
    return model, fields, papers, cells


def write_artifacts(output_dir, model):
    _write_text(output_dir / "comparison_table.md", model["summary"])
    with (output_dir / "comparison_matrix.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for cell in model["matrix"]:
            writer.writerow([cell.get("doc_id" if key == "source_document_id" else key, "")
                             for key in CSV_COLUMNS])
    with (output_dir / "evidence_cards.jsonl").open("w", encoding="utf-8") as handle:
        handle.write("\n".join(json.dumps(card, ensure_ascii=False)
                               for card in model["evidence_cards"]) + "\n")


def phase_build(args):
    started, (input_dir, output_dir, work_dir) = time.time(), resolve_dirs(args)
    output_dir.mkdir(parents=True, exist_ok=True)
    errors, pending, degradations = [], [], []
    case, _ = locate_case(input_dir, errors)
    _write_json(output_dir / "result.json",
                EC.partial_result(case, str(case.get("case_id") or "unknown"), errors))

    input_dir, index, docs, workorder, case_id, draft, draft_source = gather_inputs(
        args, case, errors, pending, degradations)
    model, fields, papers, cells = assemble_model(workorder, docs, case_id, draft, degradations)

    report = EC.audit_draft({"fields": fields, "papers": papers, "matrix": cells,
                             "comparability": model["comparability"],
                             "conclusions": [item for item in (draft.get("conclusions") or [])
                                             if isinstance(item, dict)],
                             "agreement": model["agreement"]}, index)
    counts = report["counts"]
    has_reported = counts["cells_reported"] > 0
    agreement = model["agreement"]
    model.update(
        coverage=counts, pending_human=pending,
        status="ok" if (has_reported and not report["errors"] and not degradations)
        else "partial" if has_reported else "insufficient_evidence",
        conflicts=[item for item in (agreement.get("items") if isinstance(agreement, dict)
                                     else agreement) if item.get("verdict") == "conflicting"],
        method="init 抽取带 locator 的段落；Agent 把每篇文档映射到同一字段表，逐格记录 "
               "value+unit+dataset+metric_scope+quote+locator；先按条件判定可比性再合并；"
               "冲突归因到 sample/method/metric/condition。")
    if not docs:
        model["status"] = "input_error"
        pending.append("no readable corpus document found under the input directory")

    model["summary"] = EC.render_comparison_md(model, ENGINE)
    write_artifacts(output_dir, model)

    result, missing = EC.fill_contract(case, model)
    result.update(
        case_id=case_id, status=model["status"], sources=model["sources"],
        uncertainty=model["uncertainty"] or ["cells with confidence=fallback have no value: "
                                             "read the paper"],
        pending_human=pending + ([] if not report["errors"]
                                 else ["check errors: " +
                                       ", ".join(error["code"]
                                                 for error in report["errors"][:5])]),
        errors=errors + report["errors"], degradations=degradations,
        changes=[dict(step="build", source=draft_source or "(none)", to=model["artifacts"]),
                 dict(step="contract",
                      resolved=len(EC.contract_fields(case.get("output_contract"))) - len(missing))],
        runtime=dict(skill=ENGINE, stage="build",
                     seconds=round(time.time() - started, 2), docs=len(docs),
                     fields=len(fields), cells=len(cells),
                     reported=counts["cells_reported"], coverage=counts["coverage"],
                     quote_pass_rate=counts["quote_pass_rate"]))
    if missing:
        result["pending_human"].append("output_contract fields with no matching content: %s"
                                       % ", ".join(missing))
    _write_json(output_dir / "result.json", result)
    asset_info = {}
    try:  # 提分包增量：写 5 件可核验资产并回填附加键；失败不影响主流程与退出码
        import assets
        asset_info = assets.finalize(input_dir, output_dir, work_dir, case) or {}
    except Exception:
        pass
    print("status=%s docs=%d fields=%d cells=%d reported=%d coverage=%s quote_pass=%s"
          % (model["status"], len(docs), len(fields), len(cells),
             counts["cells_reported"], counts["coverage"], counts["quote_pass_rate"]))
    repaired = [key for key in (asset_info.get("repaired") or []) if key in missing]
    print("artifacts:", ", ".join(model["artifacts"]),
          "| unfilled contract:", [key for key in missing if key not in repaired] or "none",
          "| assets: %s/5 (build 收尾自动生成)" % asset_info.get("asset_count", 0))
    return 0


PHASES = {"init": phase_init, "show": phase_show, "check": phase_check, "build": phase_build}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="跨论文共同字段对照流水线（Agent 主答 + 脚本托管；%s）" % ENGINE)
    sub = parser.add_subparsers(dest="cmd")
    for name, help_text in (
            ("init", "扫描材料、建立段落索引并写 partial result.json"),
            ("show", "打印带 locator 的原文段落"),
            ("check", "校验 Agent 工作稿的字段/引文/覆盖"),
            ("build", "生成比较表、证据卡与 final result.json")):
        command = sub.add_parser(name, help=help_text)
        for flag in ("--input", "--output", "--work"):
            command.add_argument(flag)
        if name == "show":
            command.add_argument("--doc")
            command.add_argument("--paras")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not args.cmd:
        build_parser().print_help()
        return 0
    try:
        PHASES[args.cmd](args)
    except Exception as exc:
        try:
            input_dir, output_dir, _ = resolve_dirs(args)
            output_dir.mkdir(parents=True, exist_ok=True)
            _write_json(output_dir / "result.json", EC.partial_result(
                locate_case(input_dir, [])[0], "unknown",
                [{"code": "unhandled_exception",
                  "detail": "%s: %s" % (type(exc).__name__, exc),
                  "trace": traceback.format_exc()[-900:]}]))
        except Exception:
            pass
        print("ERROR %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
