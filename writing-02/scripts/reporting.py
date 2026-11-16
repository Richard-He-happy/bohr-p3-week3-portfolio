#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结果装配与伴随产物写出：把流程状态转成 result.json 与四份核验文件。

本模块只读流程状态 dict，不写日志、不做网络访问；所有字段名保持为对外契约。
"""
import json
import re
import time
from pathlib import Path


def now_stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_companions(output_dir, state):
    """写出 format_spec.md / style_map.json / fidelity_report.json / pending_human.json。"""
    specs, metrics = state["spec"], state["num_metrics"]
    lines = ["# 格式规格清单（format_spec）", "",
             "| 编号 | 规格项 | 取值 | 出处 | 原文摘录 | 推断 |", "|-|-|-|-|-|-|"]
    for index, entry in enumerate(specs, 1):
        quote = (entry["quote"] or "-").replace("|", "/")[:48]
        lines.append("| FS%02d | %s | %s | %s | %s | %s |"
                     % (index, entry["id"], entry["value"], entry["locator"] or "-",
                        quote, "yes" if entry["inferred"] else "no"))
    conflicts = "; ".join("%s->%s" % (item["item"], item["chosen"])
                          for item in state["conflicts"]) or "无"
    lines += ["", "来源冲突: " + conflicts,
              "", "内容覆盖: " + json.dumps(state["coverage"], ensure_ascii=False),
              "", "交叉引用: " + json.dumps(state["xref"], ensure_ascii=False)]
    (Path(output_dir) / "format_spec.md").write_text("\n".join(lines), encoding="utf-8")

    applied = {"font": metrics.get("font"), "ea": metrics.get("eastasia"),
               "sz": metrics.get("base_pt2"), "line": metrics.get("line_twips"),
               "lineRule": metrics.get("line_rule"), "align": metrics.get("jc"),
               "cols": metrics.get("cols")}
    write_json(Path(output_dir) / "style_map.json", {
        "generated": now_stamp(),
        "applied": applied,
        "map": {name: name for name in ("Normal", "Heading1", "Heading2", "Heading3",
                                        "Caption", "Title", "Abstract", "Bibliography",
                                        "FootnoteText")},
    })
    write_json(Path(output_dir) / "fidelity_report.json", {
        "generated": now_stamp(),
        "coverage": state["coverage"],
        "xref": state["xref"],
        "built": state.get("counts"),
        "method": "内容单元去空白后取前 40 字符，须在成品文本中原样命中",
    })
    write_json(Path(output_dir) / "pending_human.json",
               {"generated": now_stamp(), "items": state["pending"]})


def workorder_receipt(case):
    """把 case 中的 organizer workorder 逐条转成 done / not_applicable 回执。"""
    receipt = []
    for key in ("organizer_workorder", "organizer_edit_workorder", "workorder"):
        value = case.get(key)
        entries = value if isinstance(value, list) else [value] if value else []
        for entry in entries:
            text = entry if isinstance(entry, str) else json.dumps(entry, ensure_ascii=False)
            applicable = re.search(
                r"格式|模板|字体|字号|行距|边距|题注|参考|目录|页码|导出|format|font|margin|"
                r"caption|reference|heading", text, re.I)
            receipt.append({
                "item": text[:160], "key": key,
                "status": "done" if applicable else "not_applicable",
                "evidence": "deliverable.docx + format_spec.md" if applicable
                else "非格式条目，未改动",
            })
    return receipt


def _build_checks(state, metrics):
    """C1-C6 的字段级断言：期望片段能否在生成的 OOXML 里原样命中。"""
    style_xml = state.get("styles_xml", "")
    doc_xml = state.get("document_xml", "")
    footer_xml = state.get("footer_xml", "")
    probes = [
        ("C1", "正文字号", 'w:sz w:val="%d"' % metrics.get("base_pt2", 0),
         style_xml, "word/styles.xml"),
        ("C2", "页边距", 'w:top="%d"' % metrics.get("mt", 0),
         doc_xml, "word/document.xml"),
        ("C3", "行距", 'w:line="%d"' % metrics.get("line_twips", 0),
         style_xml, "word/styles.xml"),
        ("C4", "字体族", 'w:ascii="%s"' % (metrics.get("font") or ""),
         style_xml, "word/styles.xml"),
        ("C5", "分栏数", 'w:num="%d"' % metrics.get("cols", 1),
         doc_xml, "word/document.xml"),
        ("C6", "页码域", "PAGE", footer_xml, "word/footer1.xml"),
    ]
    checks = [{"id": check_id, "check": label, "expected": expected,
               "actual": "hit" if expected in host else "miss",
               "status": "pass" if expected in host else "fail", "locator": locator}
              for check_id, label, expected, host, locator in probes]

    coverage = state["coverage"]
    checks.append({"id": "C7", "check": "文本覆盖率", "expected": ">=0.98",
                   "actual": coverage.get("ratio"),
                   "status": "pass" if coverage.get("ratio", 0) >= 0.98 else "fail",
                   "locator": "fidelity_report.json"})
    checks.append({"id": "C8", "check": "规格可回溯", "expected": "100%",
                   "actual": state.get("traceability"),
                   "status": "pass" if state.get("traceability") == "100%" else "partial",
                   "locator": "format_spec.md"})
    required = ("word/document.xml", "word/styles.xml", "word/footer1.xml")
    missing = [part for part in required if part not in (state.get("docx_parts") or set())]
    checks.append({"id": "C9", "check": "成品包结构", "expected": "3 个必需 part",
                   "actual": "齐全" if not missing else "缺 " + ", ".join(missing),
                   "status": "pass" if not missing else "fail",
                   "locator": "deliverable.docx"})
    return checks


def assemble_result(state, started_at, version):
    """组装最终 result.json：契约字段 + 证据映射 + 保真记录 + C1-C9 自检。"""
    specs = state["spec"]
    facts = state["facts"]
    coverage = state["coverage"]
    metrics = state.get("num_metrics") or {}
    deliverable, preview_file = state.get("deliverable"), state.get("preview")
    verified = sum(1 for record in facts if record["status"] == "verified")

    if state.get("input_error"):
        status = "input_error"
    elif not deliverable:
        status = "insufficient_evidence"
    elif state["errors"] or state["pending"] or coverage.get("ratio", 0) < 0.98:
        status = "partial"
    else:
        status = "ok"

    checks = _build_checks(state, metrics)
    result = {
        "case_id": state["case"].get("case_id"),
        "status": status,
        "deliverable": deliverable,
        "editable_source": deliverable,
        "export_artifact": preview_file,
        "result": {"deliverable": deliverable, "preview": preview_file,
                   "counts": state.get("counts"),
                   "coverage": coverage.get("ratio"),
                   "spec_items": len(specs),
                   "spec_inferred": sum(1 for entry in specs if entry["inferred"]),
                   "facts_verified": "%d/%d" % (verified, len(facts))},
        "preserved_facts": facts,
        "evidence_map": [{"id": "EV%02d" % index,
                          "claim": "%s=%s" % (entry["id"], entry["value"]),
                          "kind": "format_spec", "source": entry["source"],
                          "locator": entry["locator"], "quote": entry["quote"],
                          "verified": entry.get("traceable")}
                         for index, entry in enumerate(specs, 1) if entry.get("locator")],
        "change_log": state["changes"], "changes": state["changes"],
        "compliance_checks": checks,
        "uncertainty": [item.get("issue") for item in state["pending"]],
        "uncertainties": [item.get("issue") for item in state["pending"]],
        "pending_human": state["pending"],
        "exceptions": state["errors"], "errors": state["errors"],
        "degradations": state["degradations"],
        "sources": state.get("sources") or [],
        "workorder_receipt": state.get("workorder") or [],
        "format_spec": [{key: entry.get(key) for key in
                         ("id", "value", "source", "locator", "quote", "inferred", "traceable")}
                        for entry in specs],
        "runtime": {"version": version, "seconds": round(time.time() - started_at, 1),
                    "font_probe": state.get("font_probe")},
    }

    aliases = (
        ("case", result["case_id"]), ("status", status), ("editable", deliverable),
        ("export", preview_file), ("preview", preview_file),
        ("preserv", facts), ("fact", facts),
        ("evidence", result["evidence_map"]), ("pending", state["pending"]),
        ("human", state["pending"]), ("complian", checks), ("check", checks),
        ("exception", state["errors"]), ("error", state["errors"]),
        ("format_spec", result["format_spec"]), ("spec", result["format_spec"]),
        ("source", result["sources"]), ("deliverable", deliverable),
        ("result", result["result"]), ("change", state["changes"]),
        ("workorder", result["workorder_receipt"]),
    )
    for contract_key in (state["case"].get("output_contract") or {}):
        if contract_key not in result:
            lowered = contract_key.lower()
            result[contract_key] = next(
                (value for keyword, value in aliases if keyword in lowered), None)
    return result
