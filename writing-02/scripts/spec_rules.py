#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版式规格的抽取、归并与单位换算。

三类材料各有一组扫描器：纯文本格式要求（scan_requirements）、LaTeX 模板
（scan_tex_template）、docx 模板（scan_docx_template）。扫描结果统一为
{id, value, source, locator, quote, inferred} 结构，再由 merge_layers 按
来源权重合并为 20 项规格，最后由 layout_metrics 换成 OOXML 需要的单位。

本模块无副作用、不读环境变量、不依赖当前工作目录。
"""
import re
import zipfile
from pathlib import Path

# 中文字号名 -> 磅值
CJK_TO_PT = {
    "初号": 42, "一号": 26, "小一": 24, "二号": 22, "小二": 18, "三号": 16,
    "小三": 15, "四号": 14, "小四": 12, "五号": 10.5,
}

# 默认版式：材料里没有规定时全部按此兜底（每项都会标 inferred=True）
DEFAULT_SPEC = [
    pair.split("|") for pair in (
        "page.size|A4\n"
        "page.margin.top|2.54cm\n"
        "page.margin.bottom|2.54cm\n"
        "page.margin.left|2.54cm\n"
        "page.margin.right|2.54cm\n"
        "page.columns|1\n"
        "body.font|Liberation Serif\n"
        "body.font.eastasia|SimSun\n"
        "body.size|12pt\n"
        "body.line_spacing|1.5\n"
        "body.align|both\n"
        "heading.1.size|16pt\n"
        "heading.2.size|14pt\n"
        "heading.3.size|12pt\n"
        "title.size|18pt\n"
        "caption.size|10.5pt\n"
        "caption.table.position|above\n"
        "reference.style|numeric\n"
        "reference.size|10.5pt\n"
        "toc.levels|3"
    ).splitlines()
]

# 数值越小优先级越高；default 层不参与合并（缺项时才用）
SOURCE_RANK = {"template_docx": 0, "template_tex": 1, "requirements": 2}

# (正则, 规格 ID)。group(1) 是被抽取的取值，margin 例外：group(1)=方位。
REQUIREMENT_RULES = [
    (r"字体[^\n。；]{0,10}?(Times New Roman|Liberation Serif|宋体|黑体|楷体|SimSun)", "body.font"),
    (r"字号[^\n。；]{0,8}?(\d+(?:\.\d+)?\s*pt|小[一二三四五]|初号|一号|二号|三号|四号|五号)", "body.size"),
    (r"行距[^\n。；]{0,8}?(\d+(?:\.\d+)?)", "body.line_spacing"),
    (r"(上|下|左|右)\s*(?:边距|margin)[^\n。；]{0,6}?(\d+(?:\.\d+)?\s*(?:cm|mm|in))", "margin"),
    (r"(单栏|双栏|两栏)", "page.columns"),
    (r"(?:图|表)注[^\n。；]{0,6}?(上方|上|下方|下)", "caption.table.position"),
    (r"(GB/T\s*7714|APA|IEEE|Vancouver|MLA|Chicago|Harvard|著者-出版年|顺序编码)", "reference.style"),
]

SIDE_ALIAS = {"上": "top", "下": "bottom", "左": "left", "右": "right"}
PAGE_PRESETS = {"A4": (11906, 16838), "A3": (16838, 23811), "A5": (8391, 11906)}


def grab_number(text, fallback=0.0):
    """取字符串里的第一个数值；没有就返回 fallback。"""
    hit = re.search(r"-?[\d.]+", str(text))
    return float(hit.group(0)) if hit else fallback


def to_half_points(text, fallback=None):
    """磅值 -> OOXML half-point（w:sz 单位）。"""
    hit = re.search(r"([\d.]+)", str(text))
    return int(round(float(hit.group(1)) * 2)) if hit else fallback


def _item(spec_id, value, source, locator, quote, inferred=False):
    return {"id": spec_id, "value": str(value), "source": source,
            "locator": locator, "quote": quote, "inferred": inferred}


def scan_requirements(blob, origin):
    """扫描格式要求文本，逐行匹配版式关键词。

    同一行可以同时命中多个规格（例如"字号 10.5pt，行距 1.5"），
    每个规格只取该行第一处命中，避免重复计数。
    """
    found = []
    for line_no, raw_line in enumerate(blob.splitlines(), 1):
        for pattern, spec_id in REQUIREMENT_RULES:
            hit = re.search(pattern, raw_line, re.I)
            if not hit:
                continue
            token = hit.group(1)
            if spec_id == "margin":
                spec_id = "page.margin." + SIDE_ALIAS[token]
                token = hit.group(2).replace(" ", "")
            elif spec_id == "body.size":
                token = ("%gpt" % CJK_TO_PT[token]) if token in CJK_TO_PT else token.replace(" ", "")
            elif spec_id == "body.line_spacing":
                token = "%g" % grab_number(token, 1.5)
            elif spec_id == "page.columns":
                token = 1 if token == "单栏" else 2
            elif spec_id == "caption.table.position":
                token = "above" if token.startswith("上") else "below"
            elif spec_id == "reference.style":
                token = "numeric" if re.search(r"7714|IEEE|Vancouver|顺序", token) else "author-year"
            found.append(_item(spec_id, token, "requirements",
                               "%s#L%d" % (origin, line_no), raw_line.strip()[:120]))
    return found


def scan_tex_template(blob, origin):
    """扫描 LaTeX 模板前导区里的版式命令。"""
    found = []

    def put(spec_id, value, quote):
        found.append(_item(spec_id, value, "template_tex",
                           "%s#%s" % (origin, quote.strip()[:30]), quote.strip()[:100]))

    for hit in re.finditer(r"\\documentclass(?:\[([^\]]*)\])?", blob):
        options = hit.group(1) or ""
        if "twocolumn" in options or "onecolumn" in options:
            put("page.columns", 2 if "twocolumn" in options else 1, hit.group(0))
        pt = re.search(r"(\d+)pt", options)
        if pt:
            put("body.size", pt.group(1) + "pt", hit.group(0))

    for hit in re.finditer(r"\\(?:usepackage\[([^\]]*)\]\{geometry\}|geometry\{([^}]*)\})", blob):
        options = (hit.group(1) or "") + "," + (hit.group(2) or "")
        for side, measure in re.findall(r"(top|bottom|left|right|margin)\s*=\s*([\d.]+\s*(?:cm|mm|in))", options):
            put("page.margin." + ("top" if side == "margin" else side),
                measure.replace(" ", ""), hit.group(0))

    for hit in re.finditer(r"\\(setmainfont|setCJKmainfont)(?:\[[^\]]*\])?\{([^}]+)\}", blob):
        spec_id = "body.font.eastasia" if hit.group(1) == "setCJKmainfont" else "body.font"
        put(spec_id, hit.group(2).strip(), hit.group(0))

    for hit in re.finditer(r"\\fontsize\{([\d.]+)pt\}", blob):
        put("body.size", hit.group(1) + "pt", hit.group(0))

    for hit in re.finditer(r"\\(onehalfspacing|doublespacing|singlespacing)", blob):
        ratio = {"onehalfspacing": "1.5", "doublespacing": "2", "singlespacing": "1"}[hit.group(1)]
        put("body.line_spacing", ratio, hit.group(0))

    for hit in re.finditer(r"\\linespread\{([\d.]+)\}", blob):
        put("body.line_spacing", hit.group(1), hit.group(0))

    for hit in re.finditer(r"\\bibliographystyle\{(\w+)\}", blob):
        style = "author-year" if hit.group(1) in ("apalike", "plainnat") else "numeric"
        put("reference.style", style, hit.group(0))

    for hit in re.finditer(r"\\captionsetup\{([^}]*)\}", blob):
        body = hit.group(1)
        font = re.search(r"font\s*=\s*(\w+)", body)
        if font:
            put("caption.size", {"small": "9pt", "footnotesize": "8pt"}.get(font.group(1), "10pt"),
                hit.group(0))
        pos = re.search(r"position\s*=\s*(above|below)", body)
        if pos:
            put("caption.table.position", pos.group(1), hit.group(0))

    if re.search(r"\\tableofcontents|tocbibind", blob):
        put("toc.levels", 3, "toc")
    return found


def scan_docx_template(path):
    """从 .docx/.dotx 模板的 OOXML 里抽取版式规格。

    只读 word/document.xml（节属性、TOC 域）与 word/styles.xml（样式表），
    不跟随主题字体与样式继承链——读不到的部分会退化为推断项。
    """
    archive = zipfile.ZipFile(path)
    name_list = set(archive.namelist())
    origin = Path(path).name
    found = []
    doc_xml = archive.read("word/document.xml").decode("utf-8", "replace")
    styles_xml = (archive.read("word/styles.xml").decode("utf-8", "replace")
                  if "word/styles.xml" in name_list else "")

    def put(spec_id, value, where, quote):
        if value not in (None, "", 0):
            found.append(_item(spec_id, value, "template_docx",
                               "%s#%s" % (origin, where), quote))

    def read_style(chunk):
        picked = {}
        for key, pattern in (("font", r'<w:rFonts[^>]*w:ascii="([^"]+)"'),
                             ("ea", r'w:eastAsia="([^"]+)"'),
                             ("sz", r'<w:sz w:val="(\d+)"'),
                             ("hang", r'<w:ind[^>]*w:hanging="(\d+)"'),
                             ("line", r'<w:spacing[^>]*w:line="(\d+)"')):
            hit = re.search(pattern, chunk)
            if hit:
                picked[key] = hit.group(1)
        if "sz" in picked:
            picked["pt"] = int(picked["sz"]) / 2
        rule = re.search(r'w:lineRule="(\w+)"', chunk)
        picked["rule"] = rule.group(1) if rule else "auto"
        return picked

    sect = doc_xml[doc_xml.rfind("<w:sectPr"):] if "<w:sectPr" in doc_xml else ""

    hit = re.search(r"<w:pgSz[^>]*>", sect)
    if hit:
        attrs = dict(re.findall(r'w:(\w+)="([^"]*)"', hit.group(0)))
        width, height = int(attrs.get("w", 11906)), int(attrs.get("h", 16838))
        page_name = ""
        for label, (pw, ph) in PAGE_PRESETS.items():
            if (abs(width - pw) < 60 and abs(height - ph) < 60) or \
                    (abs(width - ph) < 60 and abs(height - pw) < 60):
                page_name = label
        put("page.size", page_name or "%dx%dtw" % (width, height), "sectPr/pgSz",
            hit.group(0)[:100])

    hit = re.search(r"<w:pgMar[^>]*>", sect)
    if hit:
        attrs = dict(re.findall(r'w:(\w+)="([^"]*)"', hit.group(0)))
        for side in ("top", "bottom", "left", "right"):
            if side in attrs:
                put("page.margin." + side, "%.2fcm" % (int(attrs[side]) / 1440 * 2.54),
                    "sectPr/pgMar@" + side, 'w:%s="%s"' % (side, attrs[side]))

    hit = re.search(r"<w:cols[^>]*>", sect)
    if hit:
        attrs = dict(re.findall(r'w:(\w+)="([^"]*)"', hit.group(0)))
        put("page.columns", attrs.get("num", "1"), "sectPr/cols", hit.group(0)[:70])

    style_map = {}
    for block in re.finditer(r"<w:style [^>]*>(.*?)</w:style>", styles_xml, re.S):
        label = re.search(r'<w:name w:val="([^"]+)"', block.group(1))
        if label:
            style_map[label.group(1).strip().lower()] = read_style(block.group(1))

    defaults = re.search(r"<w:docDefaults>.*?</w:docDefaults>", styles_xml, re.S)
    normal = read_style(defaults.group(0)) if defaults else {}
    normal.update({k: v for k, v in style_map.get("normal", {}).items() if v})

    put("body.font", normal.get("font"), "styles.xml[Normal]/rFonts",
        'w:ascii="%s"' % (normal.get("font") or ""))
    put("body.font.eastasia", normal.get("ea"), "styles.xml[Normal]/rFonts",
        'w:eastAsia="%s"' % (normal.get("ea") or ""))
    if normal.get("pt"):
        put("body.size", "%gpt" % normal["pt"], "styles.xml[Normal]/sz",
            '<w:sz w:val="%s"/>' % normal["sz"])
    if normal.get("line"):
        put("body.line_spacing",
            ("%g" % (float(grab_number(normal["line"], 240)) / 240))
            if normal["rule"] == "auto" else ("%gpt" % (float(grab_number(normal["line"])) / 20)),
            "styles.xml[Normal]/spacing", '<w:spacing w:line="%s"/>' % normal["line"])

    for level in (1, 2, 3):
        head = style_map.get("heading %d" % level) or {}
        if head.get("pt"):
            put("heading.%d.size" % level, "%gpt" % head["pt"],
                "styles.xml[heading %d]/sz" % level, '<w:sz w:val="%s"/>' % head["sz"])

    for spec_id, style_name in (("caption.size", "caption"), ("reference.size", "bibliography")):
        style = style_map.get(style_name) or {}
        if style.get("pt"):
            put(spec_id, "%gpt" % style["pt"], "styles.xml[%s]/sz" % style_name,
                '<w:sz w:val="%s"/>' % style["sz"])

    bib = style_map.get("bibliography") or {}
    if bib.get("hang"):
        put("reference.hanging", "%stw" % int(float(bib["hang"])),
            "styles.xml[Bibliography]/ind", 'w:hanging="%s"' % bib["hang"])

    toc = re.search(r'TOC \\o "1-(\d)"', doc_xml)
    if toc:
        put("toc.levels", toc.group(1), "document.xml[TOC]", toc.group(0))
    return found


def merge_layers(entries):
    """按 模板 docx > 模板 tex > 格式要求 > 默认 合并；冲突保留并上报。"""
    merged, conflicts = [], []
    for spec_id, fallback in DEFAULT_SPEC:
        candidates = sorted([entry for entry in entries if entry["id"] == spec_id],
                            key=lambda entry: SOURCE_RANK.get(entry["source"], 8))
        distinct = []
        for entry in candidates:
            if entry["value"] not in distinct:
                distinct.append(entry["value"])
        if not candidates:
            merged.append(_item(spec_id, fallback, "default", "", "", inferred=True))
            continue
        winner = dict(candidates[0], inferred=False)
        if len(distinct) > 1:
            conflicts.append({
                "item": spec_id,
                "chosen": winner["value"],
                "rule": "docx>tex>要求>默认",
                "values": [{"value": entry["value"], "source": entry["source"],
                            "locator": entry["locator"]} for entry in candidates],
            })
        merged.append(winner)
    return merged, conflicts


def layout_metrics(items):
    """把字符串规格换成 OOXML 数值（twip / half-point / 布尔），供写 docx 使用。"""
    values = {entry["id"]: entry["value"] for entry in items}
    metrics = {
        "font": values["body.font"],
        "eastasia": values["body.font.eastasia"],
        "base_pt2": to_half_points(values["body.size"], 24),
    }
    line_text = str(values["body.line_spacing"]).lower()
    if line_text.endswith("pt"):
        metrics["line_twips"] = int(grab_number(line_text) * 20)
        metrics["line_rule"] = "exact"
    else:
        metrics["line_twips"] = int(round(grab_number(line_text, 1.5) * 240))
        metrics["line_rule"] = "auto"
    align = values["body.align"]
    metrics["jc"] = align if align in ("both", "left", "center", "right") else "both"
    metrics["title_pt2"] = to_half_points(values["title.size"], metrics["base_pt2"] + 8)
    metrics["caption_pt2"] = to_half_points(values["caption.size"], metrics["base_pt2"])
    metrics["ref_pt2"] = to_half_points(values["reference.size"], metrics["base_pt2"])
    metrics["note_pt2"] = max(14, metrics["base_pt2"] - 4)

    preset = PAGE_PRESETS.get(str(values["page.size"]))
    if preset:
        metrics["page_w"], metrics["page_h"] = preset
    else:
        dims = [float(v) for v in re.findall(r"[\d.]+", str(values["page.size"]))] or [210, 297]
        metrics["page_w"] = int(dims[0] / 25.4 * 1440)
        metrics["page_h"] = int((dims[1] if len(dims) > 1 else 297) / 25.4 * 1440)

    for key, side in (("mt", "top"), ("mb", "bottom"), ("ml", "left"), ("mr", "right")):
        raw = str(values["page.margin." + side])
        if raw[-2:] in ("cm", "mm"):
            divisor = 25.4 if raw.endswith("mm") else 2.54
            metrics[key] = int(float(raw[:-2]) / divisor * 1440)
        else:
            metrics[key] = 1440

    metrics["cols"] = max(1, int(grab_number(values["page.columns"], 1)))
    metrics["col_sep"] = metrics["cols"] > 1
    metrics["headings"] = {
        str(level): {"sz": to_half_points(values["heading.%d.size" % level], metrics["base_pt2"]),
                     "bold": True, "align": "left", "before": 240, "after": 120}
        for level in (1, 2, 3)
    }
    metrics["toc_depth"] = int(grab_number(values["toc.levels"], 0))
    metrics["bib_indent"] = 567
    metrics["bib_hang"] = 567
    return metrics
