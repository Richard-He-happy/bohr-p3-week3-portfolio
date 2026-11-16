#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主流程编排：发现输入 -> 抽规格 -> 排版 docx -> 自检 -> 写 result.json。

对外只暴露两个入口：run_cli() 供命令行使用，process_case()/assemble_result()
供测试复用。所有失败都在本层兜住，进程退出码始终为 0。
"""
import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import docx_kit  # noqa: E402
import reporting  # noqa: E402
import spec_rules  # noqa: E402

VERSION = "1.0.0"

EXT_KIND = {
    ".docx": "docx", ".dotx": "docx", ".doc": "docx", ".tex": "tex",
    ".cls": "tex", ".sty": "tex", ".pdf": "pdf", ".png": "image",
    ".jpg": "image", ".jpeg": "image", ".csv": "table", ".xlsx": "table",
    ".json": "json", ".md": "text", ".txt": "text",
}

# 事实保真抽取用的三类模式：统计量、引用编号、带单位数值
FACT_RULES = [
    (r"p\s*[<>=]\s*0?\.\d+", "stat"),
    (r"\[\d+(?:\s*[-,]\s*\d+)*\]", "citation"),
    (r"\d+(?:\.\d+)?\s*(?:mg/kg|mg|kg|mL|ml|%|°C|MPa|kPa|nm|mm|cm|min|h|mmol|mM|nM)\b",
     "quantity"),
]

# output_contract 缺键时按内部关键字的语义回填（值在 assemble_result 内组装）


def _relative(target, base):
    try:
        return str(Path(target).resolve().relative_to(Path(base).resolve()))
    except (ValueError, OSError):
        return str(target)


def _scan_input(input_dir):
    """递归列出输入文件（跳过 output/ 与 work/ 子树），标注推断类型。"""
    input_dir = Path(input_dir)
    listing = []
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        parts = set(path.relative_to(input_dir).parts)
        if {"output", "work"} & parts:
            continue
        listing.append({"path": str(path),
                        "kind": EXT_KIND.get(path.suffix.lower(), "other")})
    return listing


def _bucket_roles(listing):
    """按文件名语义把输入分成 模板 / 原稿 / 格式要求 三组。"""
    templates, manuscripts, requirements = [], [], []
    for item in listing:
        name = Path(item["path"]).name.lower()
        is_template = (re.search(r"templ|模板", name) or name.endswith((".cls", ".sty"))) \
            and item["kind"] in ("docx", "tex", "pdf")
        is_requirement = re.search(r"requir|format|规定|要求|须知|格式", name) \
            and item["kind"] in ("text", "pdf", "json")
        is_manuscript = re.search(r"manuscript|paper|draft|原稿|稿件|正文", name) \
            and item["kind"] in ("docx", "tex", "text")
        if is_template:
            templates.append(item)
        elif is_requirement:
            requirements.append(item)
        elif is_manuscript:
            manuscripts.append(item)
    if not manuscripts:
        leftovers = [item for item in listing
                     if item["kind"] in ("docx", "tex", "text")
                     and item not in templates + requirements]
        manuscripts = sorted(leftovers, key=lambda item: len(Path(item["path"]).name))[:1]
    return templates[:2], manuscripts[:1], [item for item in requirements
                                            if item not in templates][:3]


def _read_any_source(path):
    """读文本/tex 直读；PDF 走可选 pdftotext，工具缺失则返回空串。"""
    path = Path(path)
    if path.suffix.lower() != ".pdf":
        return docx_kit.decode_text_file(path)
    binary = shutil.which("pdftotext")
    extraction = Path(str(path) + ".txt")
    if not binary:
        return ""
    try:
        subprocess.run([binary, "-layout", str(path), str(extraction)],
                       timeout=60, capture_output=True)
        return docx_kit.decode_text_file(extraction) if extraction.exists() else ""
    except Exception:
        return ""


def _tex_to_markdown(payload):
    """把 LaTeX 正文粗略降级为 Markdown 文本，供块解析器复用。"""
    body = payload.split("\\begin{document}")[-1].split("\\end{document}")[0]
    body = re.sub(r"(?m)(?<!\\)%.*$", "", body)
    level_of = {"section": 1, "subsection": 2, "subsubsection": 3}
    body = re.sub(r"\\(section|subsection|subsubsection)\*?\{([^}]*)\}",
                  lambda hit: "\n%s %s\n" % ("#" * level_of[hit.group(1)], hit.group(2)), body)
    body = re.sub(r"\\\[(.*?)\\\]", r"\n$$\1$$\n", body, flags=re.S)
    body = re.sub(r"\\begin\{(equation|align)\*?\}(.*?)\\end\{\1\*?\}",
                  r"\n$$\2$$\n", body, flags=re.S)
    body = re.sub(r"\\(?:textbf|textit|emph|cite|ref|label|text)\{([^}]*)\}", r"\1", body)
    body = re.sub(r"\\(?:noindent|newpage|centering|small|large|bfseries|itshape)\b", "", body)
    return re.sub(r"\n\s*\n+", "\n\n", body)


def _renumber_captions(blocks, changes):
    """按出现顺序统一图/表题注编号，并检出超出题注总数的交叉引用。"""
    seen = {"figure": 0, "table": 0}
    for block in blocks:
        kind = block["kind"]
        if kind not in seen:
            continue
        seen[kind] += 1
        previous = (block.get("caption") or "").strip()
        prefix = re.match(r"^\s*(?:图|表|Fig\.?|Table)\s*[\d.]+[\s:：.]*", previous)
        tail = previous[prefix.end():] if prefix else previous
        current = ("%s %d %s" % ("图" if kind == "figure" else "表", seen[kind], tail)).strip()
        if previous != current:
            changes.append({
                "action": "caption.renumber",
                "target": "%s#%d" % (kind, seen[kind]),
                "before": previous,
                "after": current,
                "reason": "按出现顺序统一题注前缀与序号",
                "locator": kind + "#caption",
            })
        block["caption"] = current

    dangling = []
    for block in blocks:
        if block["kind"] != "para":
            continue
        for hit in re.finditer(r"(图|表)\s*(\d+)", block.get("text") or ""):
            category = "figure" if hit.group(1) == "图" else "table"
            if not 1 <= int(hit.group(2)) <= seen[category]:
                dangling.append({"ref": hit.group(0), "available": seen[category]})
    return {"captions": seen, "dangling": dangling}


def _coverage_audit(blocks, flat_text):
    """逐内容单元检查是否出现在成品文本里（去空白后取前 40 字符做子串比对）。"""
    units = []
    for block in blocks:
        if block.get("caption"):
            units.append(block["caption"])
        if block["kind"] == "table":
            units.extend(" ".join(row) for row in (block.get("rows") or []))
        elif block["kind"] != "figure" and (block.get("text") or "").strip():
            units.append(block["text"])
    normalized = [re.sub(r"\s", "", unit) for unit in units if (unit or "").strip()]
    missed = [unit for unit in normalized if unit[:40] not in flat_text]
    matched = len(normalized) - len(missed)
    return {"units": len(normalized), "matched": matched,
            "ratio": round(matched / max(1, len(normalized)), 4),
            "missing": [unit[:60] for unit in missed[:8]]}


def _fact_audit(blocks, flat_text):
    """统计数字/引用/量值在适配前后的出现次数。"""
    tally = {}
    for block in blocks:
        blob = " ".join([block.get("text") or "", block.get("caption") or ""]
                        + [" ".join(row) for row in block.get("rows") or []])
        for pattern, category in FACT_RULES:
            for hit in re.finditer(pattern, blob):
                key = (category, hit.group(0).strip())
                tally[key] = tally.get(key, 0) + 1
    records = []
    for (category, value), before in tally.items():
        after = flat_text.count(value)
        records.append({
            "id": "%s:%s" % (category, value), "kind": category, "value": value,
            "before_count": before, "after_count": after,
            "locator": "manuscript#text",
            "status": "verified" if value in flat_text else "missing",
        })
    return records


def _docx_plain_text(path):
    """从 docx 的 word/document.xml 中提取纯文本（去标签、反转义）。"""
    try:
        payload = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return ""
    return html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", payload)))


def _export_pdf_preview(docx_path, output_dir):
    """存在 LibreOffice 时尽力导出 PDF 预览；失败不抛异常。"""
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if not binary:
        return None
    try:
        subprocess.run([binary, "--headless", "--convert-to", "pdf", "--outdir", str(output_dir),
                        str(docx_path)], timeout=210, capture_output=True)
        candidate = Path(output_dir) / (Path(docx_path).stem + ".pdf")
        if candidate.exists() and candidate.read_bytes()[:5] == b"%PDF-":
            return candidate
    except Exception:
        return None
    return None


def process_case(input_dir, output_dir, options, state):
    """一次完整适配：发现材料、抽规格、排版、自检并落盘伴随文件。"""
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    templates, manuscripts, requirements = _bucket_roles(_scan_input(input_dir))
    state["sources"] = [
        {"role": role, "path": _relative(item["path"], input_dir), "kind": item["kind"]}
        for role, group in (("template", templates), ("manuscript", manuscripts),
                            ("requirements", requirements))
        for item in group
    ]

    evidence, hosts = [], {}
    for item in templates + requirements:
        try:
            if item["kind"] == "docx":
                evidence += spec_rules.scan_docx_template(item["path"])
                archive = zipfile.ZipFile(item["path"])
                hosts[Path(item["path"]).name] = "".join(
                    archive.read(part).decode("utf-8", "replace")
                    for part in archive.namelist() if part.endswith(".xml"))
            else:
                payload = _read_any_source(item["path"])
                origin = Path(item["path"]).name
                if item["kind"] == "tex":
                    evidence += spec_rules.scan_tex_template(payload, origin)
                evidence += spec_rules.scan_requirements(payload, origin)
                hosts[origin] = payload
        except Exception as exc:
            state["errors"].append({"stage": "spec",
                                    "file": _relative(item["path"], input_dir),
                                    "error": str(exc)[:100]})

    case = state["case"]
    for field in ("task_instruction", "format_requirements"):
        blob = case.get(field)
        if isinstance(blob, str) and len(blob) > 8:
            evidence += spec_rules.scan_requirements(blob, "case.json")
            hosts.setdefault("case.json", blob)

    if not templates:
        state["degradations"].append({"what": "未提供模板文件",
                                      "handled": "用格式要求 + 默认规格继续",
                                      "impact": "规格可能不完整"})
    if not evidence:
        state["degradations"].append({"what": "没有抽到任何版式规格",
                                      "handled": "整套使用默认规格",
                                      "impact": "需要人工核对模板"})

    specs, conflicts = spec_rules.merge_layers(evidence)
    state["spec"], state["conflicts"] = specs, conflicts
    metrics = state["num_metrics"] = spec_rules.layout_metrics(specs)

    font_tool = shutil.which("fc-list")
    state["font_probe"] = None
    if font_tool:
        try:
            state["font_probe"] = bool(subprocess.run(
                [font_tool, metrics["font"]], timeout=20, capture_output=True).stdout.strip())
        except Exception:
            state["font_probe"] = None
    if state["font_probe"] is False:
        state["degradations"].append({
            "what": "模板字体 %s 在本机不可用" % metrics["font"],
            "handled": "按 revision3 改用 Liberation Serif",
            "impact": "字形可能与目标模板略有差异"})
        metrics["font"] = "Liberation Serif"
        state["pending"].append({"item": "body.font",
                                 "issue": "模板字体不可用，已替换为 Liberation Serif",
                                 "action": "请确认该替换可接受"})

    blocks = []
    if manuscripts:
        source_path = manuscripts[0]["path"]
        lowered = source_path.lower()
        if lowered.endswith((".docx", ".dotx")):
            blocks = docx_kit.docx_blocks(source_path)[0]
        elif lowered.endswith((".tex", ".ltx")):
            blocks = docx_kit.markdown_blocks(_tex_to_markdown(
                docx_kit.decode_text_file(source_path)))[0]
        else:
            blocks = docx_kit.markdown_blocks(docx_kit.decode_text_file(source_path))[0]
    else:
        state["errors"].append({"stage": "manuscript",
                                "error": "未找到原稿（docx/md/tex）"})

    state["changes"] = []
    state["xref"] = _renumber_captions(blocks, state["changes"])
    deliverable = output_dir / "deliverable.docx"
    counts = docx_kit.build_docx(str(deliverable), blocks, metrics)
    preview_file = None if options.no_preview else _export_pdf_preview(deliverable, output_dir)
    if not preview_file:
        state["degradations"].append({
            "what": "PDF 预览未生成（缺 soffice 或转换失败）",
            "handled": "保留可编辑 docx 作为主产物",
            "impact": "无法通过预览做目视核对"})

    flat = re.sub(r"\s", "", _docx_plain_text(deliverable))
    state.update({
        "deliverable": _relative(deliverable, output_dir),
        "preview": _relative(preview_file, output_dir) if preview_file else None,
        "counts": counts,
        "coverage": _coverage_audit(blocks, flat),
        "facts": _fact_audit(blocks, flat),
    })

    archive = None
    try:
        archive = zipfile.ZipFile(deliverable)
        state["docx_parts"] = set(archive.namelist())
        state["styles_xml"] = archive.read("word/styles.xml").decode("utf-8", "replace")
        state["document_xml"] = archive.read("word/document.xml").decode("utf-8", "replace")
        state["footer_xml"] = archive.read("word/footer1.xml").decode("utf-8", "replace")
    except Exception:
        state["docx_parts"] = set()
        state["styles_xml"] = state["document_xml"] = state["footer_xml"] = ""

    traceable = 0
    verifiable = 0
    for entry in specs:
        if entry["inferred"] or not entry.get("quote"):
            entry["traceable"] = None
            continue
        verifiable += 1
        host_text = hosts.get(str(entry["locator"]).split("#")[0], "")
        entry["traceable"] = bool(host_text and entry["quote"] in host_text)
        traceable += 1 if entry["traceable"] else 0
    state["traceability"] = ("100%" if verifiable and traceable == verifiable
                             else ("%d%%" % int(100.0 * traceable / verifiable)
                                   if verifiable else "n/a"))

    for entry in specs:
        if entry["inferred"]:
            state["pending"].append({"item": entry["id"], "issue": "无出处，使用默认值",
                                     "value": entry["value"],
                                     "action": "请确认目标模板是否另有规定"})
        elif entry["traceable"] is False:
            state["pending"].append({"item": entry["id"],
                                     "issue": "quote 未在来源文件中原样命中",
                                     "value": entry["value"],
                                     "action": "请核对模板原文"})
    for conflict in state["conflicts"]:
        state["pending"].append({"item": conflict["item"], "issue": "模板与格式要求冲突",
                                 "action": "已取 %s，请确认取舍" % conflict["chosen"]})
    for missing in (state["coverage"].get("missing") or [])[:8]:
        state["pending"].append({"item": "fidelity", "issue": "成品未匹配内容单元",
                                 "text": missing})
    for dangling in (state["xref"].get("dangling") or [])[:8]:
        state["pending"].append({"item": "xref", "issue": "引用图表号超出题注数量",
                                 "ref": dangling["ref"]})

    reporting.write_companions(output_dir, state)


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="scripts/main.py",
        description=("学术格式与模板适配器：扫描输入目录中的稿件、模板与格式要求，"
                     "抽取逐项可核对的版式规格，重排为可编辑 docx，并输出 "
                     "format_spec.md / style_map.json / fidelity_report.json / "
                     "pending_human.json 与 result.json。"),
        epilog="退出码恒为 0：失败信息写入 result.json 的 errors/degradations。",
    )
    parser.add_argument("--input", default="/input", help="输入材料目录（默认 /input）")
    parser.add_argument("--output", default="/app/output", help="产物目录（默认 /app/output）")
    parser.add_argument("--no-preview", action="store_true", help="跳过 PDF 预览导出")
    parser.add_argument("--version", action="version", version=VERSION)
    return parser.parse_args(argv)


def run_cli(argv=None):
    """命令行主入口；任何阶段异常都不会向外抛。"""
    args = _parse_args(argv)
    input_dir, output_dir = Path(args.input), Path(args.output)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    started_at = time.time()
    state = {"errors": [], "degradations": [], "pending": [], "changes": [],
             "conflicts": [], "spec": [], "facts": [], "case": {},
             "coverage": {}, "xref": {}, "workorder": []}

    case, case_failure = None, None
    candidates = ([input_dir / "case.json"] + sorted(input_dir.glob("case*.json"))
                  + sorted(input_dir.rglob("case*.json")))
    for candidate in candidates:
        try:
            case = json.loads(candidate.read_text(encoding="utf-8"))
            break
        except FileNotFoundError:
            continue
        except Exception as exc:
            case_failure = {"stage": "case", "file": str(candidate), "error": str(exc)[:120]}
            break
    if case is None and case_failure is None:
        case_failure = {"stage": "case", "error": "case.json 不存在或不可读"}
    if case_failure:
        state["errors"].append(case_failure)
        state["input_error"] = True
    state["case"] = case if isinstance(case, dict) else {}
    state["workorder"] = reporting.workorder_receipt(state["case"]) if isinstance(state["case"], dict) else []

    reporting.write_json(output_dir / "result.json", {
        "case_id": state["case"].get("case_id"), "status": "partial",
        "deliverable": None, "preserved_facts": [], "evidence_map": [],
        "change_log": [], "errors": state["errors"], "pending_human": [],
        "degradations": [], "runtime": {"version": VERSION, "stage": "partial"},
    })

    try:
        process_case(input_dir, output_dir, args, state)
    except Exception as exc:
        state["errors"].append({"stage": "runtime", "error": str(exc)[:200]})
    try:
        final = reporting.assemble_result(state, started_at, VERSION)
    except Exception as exc:
        final = {"case_id": state["case"].get("case_id"), "status": "partial",
                 "deliverable": None, "preserved_facts": [], "evidence_map": [],
                 "change_log": [],
                 "errors": state["errors"] + [{"stage": "finish", "error": str(exc)[:200]}],
                 "pending_human": [], "degradations": state["degradations"],
                 "runtime": {"version": VERSION}}
    reporting.write_json(output_dir / "result.json", final)
    print(json.dumps({key: final.get(key) for key in
                      ("case_id", "status", "deliverable", "export_artifact")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
