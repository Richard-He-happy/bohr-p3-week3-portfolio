"""evidence_check.py - document extraction kernel and draft auditor (stdlib only)."""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

from pdf_text import pdf_pages

DEFAULT_ENGINE = "cross-paper-field-matrix v1"
ENGINE = DEFAULT_ENGINE

_SPACE_RUN = re.compile(r"\s+")
_CHAR_SWAP = {
    "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'",
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u00a0": " ", "\u200b": "", "\u00ad": "",
    "\ufb01": "fi", "\ufb02": "fl",
}

_TOKEN_BREAK = b" \t\r\n\x00\x0c()<>[]{}/%"


def canon(value, squeeze=False):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    for src, dst in _CHAR_SWAP.items():
        text = text.replace(src, dst)
    return _SPACE_RUN.sub("" if squeeze else " ", text).strip()


def keyify(text, fallback="f"):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "_", canon(text).lower()).strip("_") or fallback


def locate_quote(haystack, needle):
    target = canon(needle)
    text = canon(haystack or "")
    if len(target) < 3 or not text:
        return {"found": False, "mode": "short", "index": -1}
    pos = text.find(target)
    if pos >= 0:
        return {"found": True, "mode": "exact", "index": pos}
    squashed_q, squashed_t = canon(needle, True), canon(haystack, True)
    loose = squashed_t.find(squashed_q) if squashed_q else -1
    if squashed_q and loose >= 0:
        return {"found": True, "mode": "loose", "index": loose}
    return {"found": False, "mode": "miss", "index": -1}


def sniff_kind(path):
    try:
        head = Path(path).read_bytes()[:8]
    except Exception:
        return "unreadable"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as zf:
                members = " ".join(zf.namelist()[:60])
        except Exception:
            return "zip"
        for marker, kind in (("word/document", "docx"), ("xl/workbook", "xlsx"),
                             ("ppt/presentation", "pptx")):
            if marker in members:
                return kind
        return "zip"
    return "text"


def docx_pages(path):
    from xml.etree import ElementTree as ET
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines = ["".join(node.text or "" for node in para.iter(ns + "t")) for para in root.iter(ns + "p")]
    return [("p1", "\n\n".join(line for line in lines if line.strip()))]


def text_pages(path):
    blob = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return [("p1", blob.decode(encoding))], encoding
        except Exception:
            pass
    return [("p1", blob.decode("utf-8", "replace"))], "replace"


def split_paragraphs(pages):
    paras = []
    for label, raw_text in pages:
        text = re.sub(r"[ \t]+", " ", raw_text or "")
        blocks = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
        if len(blocks) <= 1 and len(text) > 1500:
            blocks, current = [], []
            for line in [item.strip() for item in text.splitlines() if item.strip()]:
                current.append(line)
                if len(" ".join(current)) > 600:
                    blocks.append(" ".join(current))
                    current = []
            if current:
                blocks.append(" ".join(current))
        seq = 0
        for block in blocks:
            block = re.sub(r"-\n(?=[a-z])", "", block)
            block = re.sub(r"\s+", " ", block).strip()
            if len(block) < 3:
                continue
            if len(block) < 40 and paras and paras[-1]["locator"].split("#")[0] == label:
                paras[-1]["text"] += " " + block
                continue
            seq += 1
            paras.append({"pid": "p%d" % (len(paras) + 1),
                          "locator": "%s#para%d" % (label, seq),
                          "page": label, "text": block})
    return paras or [{"pid": "p1", "locator": "p1#para1", "page": "p1", "text": ""}]


def read_document(path):
    kind, notes = sniff_kind(path), []
    if kind == "pdf":
        pages, engine, notes = pdf_pages(Path(path).read_bytes())
        if engine != "pdftotext":
            notes.append("page numbers not authoritative; locators use %s blocks" % engine)
    elif kind == "docx":
        pages, engine = docx_pages(path), "docx-xml"
    elif kind == "text":
        pages, engine = text_pages(path)
    else:
        pages, engine = [], "unsupported"
        notes.append("%s container not parsed" % kind)
    paras = split_paragraphs(pages)
    text = " ".join(para["text"] for para in paras)
    quality = sum(ch.isalnum() for ch in text) / max(len(text), 1)
    if text and quality < 0.5:
        notes.append("low text quality (alnum %.2f): CID font or scan likely" % quality)
    return {"kind": kind, "engine": engine, "paras": paras, "text": text,
            "n_pages": len(pages), "quality": round(quality, 3), "notes": notes}


def matrix_rows(draft):
    rows = draft.get("matrix") or draft.get("cells") or draft.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


def normalize_fields(draft):
    raw = draft.get("fields") or draft.get("field_definitions") or draft.get("common_fields") or []
    fields = []
    for idx, item in enumerate(raw if isinstance(raw, list) else []):
        if isinstance(item, str):
            fields.append({"field_id": keyify(item, "f%d" % (idx + 1)), "name": item})
        elif isinstance(item, dict):
            label = item.get("name") or item.get("label") or item.get("field") or ""
            fields.append({
                "field_id": str(item.get("field_id") or item.get("id") or item.get("key")
                                or keyify(label, "f%d" % (idx + 1))),
                "name": label or "?",
                "definition": item.get("definition") or item.get("desc") or "",
                "unit": item.get("unit") or "",
                "value_rule": item.get("value_rule") or item.get("rule") or "",
            })
    return fields


def normalize_papers(draft):
    raw = draft.get("papers") or draft.get("documents") or draft.get("corpus") or []
    papers = []
    for idx, item in enumerate(raw if isinstance(raw, list) else []):
        if isinstance(item, str):
            papers.append({"doc_id": item, "citation": ""})
        elif isinstance(item, dict):
            papers.append(dict(item, doc_id=str(
                item.get("doc_id") or item.get("id") or item.get("source_document_id")
                or "D%d" % (idx + 1))))
    return papers


def _audit_definitions(report, papers, fields, texts):
    def err(code, detail, where=""):
        report["errors"].append({"code": code, "detail": detail, "where": where})

    def warn(code, detail, where=""):
        report["warnings"].append({"code": code, "detail": detail, "where": where})

    field_ids = [f["field_id"] for f in fields]
    if len(set(field_ids)) != len(field_ids):
        err("duplicate_field_id", "field_id not unique", "fields")
    for field in fields:
        if not field.get("definition"):
            warn("field_no_definition", "%s lacks definition" % field["field_id"], "fields")
        if not field.get("value_rule"):
            warn("field_no_value_rule", "%s lacks value rule" % field["field_id"], "fields")
    doc_ids = [p["doc_id"] for p in papers]
    for missing in [d for d in doc_ids if d not in texts] + [d for d in texts if d not in doc_ids]:
        warn("doc_set_mismatch", "document %s not in both draft and corpus" % missing, "papers")
    return field_ids


def _audit_cells(report, cells, texts, field_ids):
    tally = dict(reported=0, unreported=0, quote_missing=0, quote_bad=0, locator_missing=0, auto=0)
    seen = {}
    for cell in cells:
        doc_id = str(cell.get("doc_id") or cell.get("source_document_id") or "")
        field_id = str(cell.get("field_id") or cell.get("field") or "")
        where = "%s/%s" % (doc_id or "?", field_id or "?")
        if not doc_id or doc_id not in texts:
            report["errors"].append({"code": "cell_unknown_doc",
                                     "detail": "cell cites unknown document %r" % doc_id,
                                     "where": where})
            continue
        if field_id not in field_ids:
            report["errors"].append({"code": "cell_unknown_field",
                                     "detail": "cell cites undeclared field %r" % field_id,
                                     "where": where})
        if (doc_id, field_id) in seen:
            report["errors"].append({"code": "duplicate_cell", "detail": "duplicate cell",
                                     "where": where})
        seen[(doc_id, field_id)] = cell
        status = canon(cell.get("status")).lower() or (
            "reported" if cell.get("value") not in (None, "") else "unreported")
        value = cell.get("value")
        if status == "reported" and value in (None, ""):
            report["errors"].append({"code": "reported_without_value", "detail": "value empty",
                                     "where": where})
            continue
        if status in ("unreported", "not_applicable"):
            tally["unreported"] += 1
            if status == "unreported" and not (cell.get("note") or cell.get("reason")):
                report["warnings"].append({"code": "unreported_no_reason",
                                           "detail": "no reason given", "where": where})
            continue
        tally["reported"] += 1
        tally["auto"] += str(cell.get("confidence") or "").lower() == "auto"
        quote = cell.get("quote") or cell.get("evidence_quote")
        if not quote:
            tally["quote_missing"] += 1
            report["errors"].append({"code": "quote_missing", "detail": "no verbatim quote",
                                     "where": where})
            continue
        if not locate_quote(texts.get(doc_id, ""), quote)["found"]:
            tally["quote_bad"] += 1
            report["errors"].append({"code": "quote_not_found",
                                     "detail": "quote absent from %s: %r" % (doc_id, canon(quote)[:90]),
                                     "where": where})
            continue
        if not (cell.get("locator") or cell.get("paragraph_id") or cell.get("page")):
            tally["locator_missing"] += 1
            report["errors"].append({"code": "locator_missing", "detail": "no locator",
                                     "where": where})
    return tally


def _audit_comparability(report, items, texts):
    for idx, item in enumerate(items):
        where = "comparability[%d]" % idx
        if not (item.get("dimension") or item.get("axis")):
            report["errors"].append({"code": "comparability_no_dimension",
                                     "detail": "item lacks dimension", "where": where})
        if "comparable" not in item and "verdict" not in item:
            report["errors"].append({"code": "comparability_no_verdict",
                                     "detail": "item lacks comparable flag", "where": where})
        doc_id = str(item.get("doc_id") or (item.get("doc_ids") or [""])[0])
        if item.get("quote") and doc_id in texts and not locate_quote(texts[doc_id], item["quote"])["found"]:
            report["errors"].append({"code": "comparability_quote_not_found",
                                     "detail": "quote absent from %s" % doc_id, "where": where})


def _audit_conclusions(report, items, texts):
    for idx, item in enumerate(items):
        where = "conclusions[%d]" % idx
        doc_id, quote = str(item.get("doc_id") or ""), item.get("quote")
        if quote and doc_id in texts and not locate_quote(texts[doc_id], quote)["found"]:
            report["errors"].append({"code": "conclusion_quote_not_found",
                                     "detail": "quote absent from %s" % doc_id, "where": where})


def _audit_agreement(report, items):
    for idx, item in enumerate(items):
        where = "agreement[%d]" % idx
        verdict = canon(item.get("verdict") or item.get("status")).lower()
        cause = canon(item.get("cause") or item.get("attribution")).lower()
        if verdict == "conflicting" and cause in ("", "unresolved"):
            report["errors"].append({"code": "conflict_without_attribution",
                                     "detail": "conflict not attributed to sample/method/metric/condition",
                                     "where": where})


def audit_draft(draft, index):
    texts = index.get("texts") or {}
    report = {"errors": [], "warnings": [], "counts": {}}
    papers, fields, cells = normalize_papers(draft), normalize_fields(draft), matrix_rows(draft)
    if not fields:
        report["errors"].append({"code": "no_fields", "detail": "no field definitions",
                                 "where": "fields"})
    if not cells:
        report["errors"].append({"code": "no_matrix", "detail": "no matrix cells", "where": "matrix"})
    field_ids = _audit_definitions(report, papers, fields, texts)
    tally = _audit_cells(report, cells, texts, field_ids)

    total = max(len(fields) * max(len(papers), 1), 1)
    report["counts"].update({
        "documents": len(papers), "fields": len(fields), "cells": len(cells),
        "cells_reported": tally["reported"], "cells_unreported": tally["unreported"],
        "cells_auto": tally["auto"], "quote_missing": tally["quote_missing"],
        "quote_not_found": tally["quote_bad"], "locator_missing": tally["locator_missing"],
        "coverage": round(tally["reported"] / total, 3),
        "quote_pass_rate": round((tally["reported"] - tally["quote_missing"] - tally["quote_bad"])
                                 / max(tally["reported"], 1), 3),
    })

    comparability = [x for x in (draft.get("comparability") or draft.get("comparability_checks") or [])
                     if isinstance(x, dict)]
    _audit_comparability(report, comparability, texts)
    report["counts"]["comparability_items"] = len(comparability)

    conclusions = [x for x in (draft.get("conclusions") or []) if isinstance(x, dict)]
    _audit_conclusions(report, conclusions, texts)
    report["counts"]["conclusion_items"] = len(conclusions)

    agreement = draft.get("agreement") or draft.get("synthesis") or {}
    items = [x for x in ((agreement.get("items") if isinstance(agreement, dict) else agreement) or [])
             if isinstance(x, dict)]
    _audit_agreement(report, items)
    report["counts"]["agreement_items"] = len(items)
    report["ok"] = not report["errors"]
    return report


def _md_table(header, rows):
    def esc(value):
        return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(esc(h) for h in header) + " |",
             "|" + "|".join(["---"] * len(header)) + "|"]
    lines += ["| " + " | ".join(esc(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def render_comparison_md(model, engine=DEFAULT_ENGINE):
    coverage = model["coverage"]
    by_cell = {(cell["doc_id"], cell["field_id"]): cell for cell in model["matrix"]}
    grid = []
    for field in model["fields"]:
        line = ["%s (%s)" % (field["field_id"], field["name"])]
        for paper in model["papers"]:
            cell = by_cell.get((paper["doc_id"], field["field_id"]))
            if not cell or cell.get("status") != "reported":
                line.append("—（未报告）")
            else:
                unit = (" " + str(cell.get("unit"))) if cell.get("unit") else ""
                line.append("%s%s  \n<sub>%s</sub>" % (cell.get("value"), unit,
                                                       cell.get("locator") or ""))
        grid.append(line)
    lines = ["# 跨论文共同字段对照表", "",
             "> case `%s` ｜ 状态 **%s** ｜ %s" % (model["case_id"], model["status"], engine), ""]
    if model.get("question"):
        lines += ["## A. 比较问题", "", model["question"], ""]
    lines += ["## B. 字段 × 文档矩阵（未报告留空；每格附 locator）", "",
              _md_table(["field_id (name)"] + [p["doc_id"] for p in model["papers"]], grid), "",
              "## C. 可比性判定", ""]
    lines += ["- **%s** ｜ %s → %s：%s" % (
        item.get("dimension"), ", ".join(item.get("doc_ids") or []),
        "可比" if item.get("comparable") else "不可比", item.get("basis"))
        for item in model["comparability"]]
    lines += ["", "## D. 结论一致性与冲突归因（详见 result.json.agreement）", ""]
    lines += ["- **%s** ｜ %s ｜ 归因：%s ｜ %s" % (
        item.get("topic"), item.get("verdict"), item.get("attribution"), item.get("explanation"))
        for item in (model["agreement"] or {}).get("items") or []]
    lines += ["", "## E. 覆盖、缺口与复跑", "",
              "- 单元格 %s；已报告 %s；未报告 %s；覆盖率 %s；引文命中率 %s" % (
                  coverage.get("cells"), coverage.get("cells_reported"),
                  coverage.get("cells_unreported"), coverage.get("coverage"),
                  coverage.get("quote_pass_rate")),
              "- 降级：%s" % ("; ".join(model.get("degradations") or []) or "无"),
              "- 复跑：main.py init → show --doc <id> → evidence_check.py quote → check → build。", ""]
    return "\n".join(lines)


def contract_fields(contract):
    if isinstance(contract, dict):
        return [str(key) for key in contract]
    if isinstance(contract, list):
        return [item if isinstance(item, str)
                else str(item.get("name") or item.get("key") or "field_%d" % (idx + 1))
                for idx, item in enumerate(contract) if isinstance(item, (str, dict))]
    return []


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig", errors="replace"))


def cli(argv=None):
    parser = argparse.ArgumentParser(
        prog="evidence_check.py",
        description="引文命中抽查与工作稿校验（纯标准库；不修改任何输入）")
    sub = parser.add_subparsers(dest="action")
    quote_cmd = sub.add_parser("quote", help="检查一段引文是否逐字属于某文档")
    for flag in ("--index", "--doc", "--quote"):
        quote_cmd.add_argument(flag, required=True)
    draft_cmd = sub.add_parser("draft", help="校验 draft.json 的字段/引文/覆盖")
    for flag in ("--index", "--draft"):
        draft_cmd.add_argument(flag, required=True)
    args = parser.parse_args(argv)
    if not args.action:
        parser.print_help()
        return
    try:
        if args.action == "quote":
            index = _read_json(args.index)
            result = dict(locate_quote((index.get("texts") or {}).get(args.doc, ""), args.quote),
                          doc=args.doc)
        else:
            result = audit_draft(_read_json(args.draft), _read_json(args.index))
    except Exception as exc:
        result = {"ok": False, "errors": [{"code": "verify_failure", "detail": repr(exc)}]}
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    cli(sys.argv[1:])


CONTRACT_HINTS = [
    ("case", "case_id"),
    ("status", "status"),
    ("paper|document|corpus", "papers"),
    ("field|schema|definition", "fields"),
    ("comparab", "comparability"),
    ("conflict", "conflicts"),
    ("agree|consisten|conclusion|finding", "agreement"),
    ("matrix|table|cells|rows", "matrix"),
    ("evidence|quote|card", "evidence_cards"),
    ("summary|answer|report|synthesis", "summary"),
    ("limit|uncertain|gap", "limitations"),
    ("coverage|stat|count|quality", "coverage"),
    ("method|repro", "method"),
    ("artifact|output_file", "artifacts"),
    ("pending|human", "pending_human"),
    ("source|provenance", "sources"),
]


def blank_of(spec):
    hint = json.dumps(spec, ensure_ascii=False).lower() if spec is not None else ""
    if '"array"' in hint or '"list"' in hint or hint == "array" or hint.startswith("["):
        return []
    if '"object"' in hint:
        return {}
    return None


def partial_result(case, case_id, errors):
    contract = case.get("output_contract")
    payload = {key: blank_of(contract.get(key) if isinstance(contract, dict) else None)
               for key in contract_fields(contract)}
    payload.update(case_id=case_id, status="partial", sources=[], uncertainty=[],
                   pending_human=[], errors=errors, degradations=[], changes=[],
                   runtime=dict(skill=ENGINE, stage="partial"))
    return payload


def fill_contract(case, model):
    contract = case.get("output_contract")
    payload, missing = {}, []
    for key in contract_fields(contract):
        value = model.get(key)
        if value in (None, "", [], {}):
            value = next((model[source] for pattern, source in CONTRACT_HINTS
                          if re.search(pattern, key.lower())
                          and model.get(source) not in (None, "", [], {})), None)
        if value is None:
            value = model.get(key, blank_of(contract.get(key) if isinstance(contract, dict) else None))
            if value in (None, "", [], {}):
                missing.append(key)
        if model.get("summary") and not isinstance(value, str) and "table" in key.lower():
            value = model["summary"]
        payload[key] = value
    return payload, missing
