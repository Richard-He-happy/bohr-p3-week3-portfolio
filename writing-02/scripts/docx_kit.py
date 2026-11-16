#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档读写底层：Markdown / docx 解析 + 最小可用 OOXML docx 生成（纯标准库）。

上层只关心"块序列"：每个块是 dict，kind ∈ {heading, para, figure, table,
equation, note, bullet, caption, title, abstract, keywords, reference, authors}。
生成端把块序列映射到 styles.xml 中预定义的样式，写出可被 Word/WPS 打开的
docx 包；不做任何联网或第三方库调用。
"""
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
_NAMESPACES = (
    ("w", "http://schemas.openxmlformats.org/wordprocessingml/2006/main"),
    ("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships"),
    ("m", "http://schemas.openxmlformats.org/officeDocument/2006/math"),
    ("wp", "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"),
    ("a", "http://schemas.openxmlformats.org/drawingml/2006/main"),
    ("pic", "http://schemas.openxmlformats.org/drawingml/2006/picture"),
)
HEADER_NS = " ".join("xmlns:%s=\"%s\"" % (prefix, uri) for prefix, uri in _NAMESPACES)
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
DOC_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml"

_CONTROL_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_CAPTION_START = re.compile(r"^\s*(图|表|式|Fig\.?|Figure|Table|Eq\.?|Equation)\s*[（(]?\s*(\d+[.\-]?\d*)")


def escape_xml(value):
    """转义 XML 特殊字符，并剔除文字里不允许出现的控制字符。"""
    if value is None:
        value = ""
    return escape(_CONTROL_CHARS.sub("", str(value)))


def number_in(value, fallback=0.0):
    hit = re.search(r"-?[\d.]+", str(value))
    return float(hit.group(0)) if hit else fallback


def squeeze(value):
    return re.sub(r"\s+", " ", value or "").strip()


def decode_text_file(path):
    """按常见中文/西文编码顺序尝试读取纯文本文件。"""
    raw = open(path, "rb").read()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# 解析端
# ---------------------------------------------------------------------------

def markdown_blocks(text):
    """逐行解析 Markdown 子集，返回 (块列表, 元信息)。"""
    blocks = []
    lines = text.splitlines()
    cursor = 0
    while cursor < len(lines):
        line = lines[cursor].strip()
        if not line:
            cursor += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            blocks.append({"kind": "heading", "text": heading.group(2).strip(),
                           "level": len(heading.group(1))})
            cursor += 1
            continue

        figure = re.match(r"^!\[(.*?)\]\((.*?)\)\s*$", line)
        if figure:
            blocks.append({"kind": "figure", "caption": figure.group(1).strip(),
                           "image": figure.group(2).strip()})
            cursor += 1
            continue

        if line.startswith("$$") or line.startswith("\\["):
            closer = "$$" if line.startswith("$$") else "\\]"
            head = line[2:].strip()
            if head.endswith(closer):
                blocks.append({"kind": "equation", "text": head[:-2].strip()})
                cursor += 1
                continue
            collected = [head] if head else []
            probe = cursor + 1
            while probe < len(lines) and not lines[probe].strip().endswith(closer):
                collected.append(lines[probe])
                probe += 1
            if probe < len(lines):
                collected.append(lines[probe].strip()[:-2])
            blocks.append({"kind": "equation", "text": "\n".join(collected).strip()})
            cursor = probe + 1
            continue

        if line.startswith("|") and line.count("|") >= 2:
            rows = []
            probe = cursor
            while probe < len(lines) and lines[probe].strip().startswith("|"):
                table_line = lines[probe].strip()
                if not re.match(r"^[\s:\-|]+$", table_line):
                    rows.append([cell.strip() for cell in table_line.strip("|").split("|")])
                probe += 1
            if rows:
                blocks.append({"kind": "table", "rows": rows})
            cursor = probe
            continue

        footnote = re.match(r"^\[\^([^\]]+)\]:\s*(.*)$", line)
        if footnote:
            blocks.append({"kind": "note", "text": footnote.group(2).strip(),
                           "id": footnote.group(1)})
            cursor += 1
            continue

        list_item = re.match(r"^(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if list_item:
            blocks.append({"kind": "bullet", "text": list_item.group(1).strip()})
            cursor += 1
            continue
        if _CAPTION_START.match(line):
            blocks.append({"kind": "caption", "text": line})
            cursor += 1
            continue

        chunk = [line]
        probe = cursor + 1
        while probe < len(lines) and lines[probe].strip() and not re.match(
                r"^(#|\||!\[|\$\$|\[\^|[-*+] |\d+[.)] )", lines[probe].strip()):
            chunk.append(lines[probe].strip())
            probe += 1
        blocks.append({"kind": "para", "text": " ".join(chunk)})
        cursor = probe

    meta = {"footnotes": sum(1 for block in blocks if block["kind"] == "note")}
    return blocks, meta


def _classify_text(style, text, has_math):
    lowered = (style or "").lower()
    if re.search(r"heading|标题|head\d", lowered):
        return "heading"
    if re.search(r"caption|题注|图注|表注", lowered) or _CAPTION_START.match(text):
        return "caption"
    for kind, pattern in (("title", r"title"), ("abstract", r"abstract|摘要"),
                          ("keywords", r"keyword|关键词"),
                          ("reference", r"bibliograph|reference|参考文献")):
        if re.search(pattern, lowered):
            return kind
    if re.match(r"^\[\d+\]", text):
        return "reference"
    if has_math and len(text) < 3:
        return "equation"
    return "para"


def docx_blocks(path):
    """读 docx 正文为块序列，并统计脚注引用数量。"""
    archive = zipfile.ZipFile(path)
    available = set(archive.namelist())
    body = ET.fromstring(archive.read("word/document.xml")).find(W_NS + "body")
    footnotes = {}
    if "word/footnotes.xml" in available:
        for note in ET.fromstring(archive.read("word/footnotes.xml")).findall(W_NS + "footnote"):
            footnotes[note.get(W_NS + "id")] = squeeze(
                "".join(run.text or "" for run in note.iter(W_NS + "t")))

    blocks, meta = [], {"footnotes": 0}
    for element in list(body):
        if element.tag == W_NS + "tbl":
            rows = []
            for row in element.findall(W_NS + "tr"):
                rows.append([squeeze("".join(node.text or "" for node in cell.iter(W_NS + "t")))
                             for cell in row.findall(W_NS + "tc")])
            blocks.append({"kind": "table", "text": "", "rows": rows})
            continue
        if element.tag != W_NS + "p":
            continue

        style, level, props = "", 0, element.find(W_NS + "pPr")
        if props is not None:
            style_node, outline = props.find(W_NS + "pStyle"), props.find(W_NS + "outlineLvl")
            style = (style_node.get(W_NS + "val") or "") if style_node is not None else ""
            if outline is not None:
                try:
                    level = int(outline.get(W_NS + "val")) + 1
                except (TypeError, ValueError):
                    level = 0

        text = squeeze("".join(run.text or "" for run in element.iter(W_NS + "t")))
        maths = [ET.tostring(node, encoding="unicode") for node in element.iter(M_NS + "oMath")]
        notes = [footnotes.get(ref.get(W_NS + "id"), "")
                 for ref in element.iter(W_NS + "footnoteReference")]
        meta["footnotes"] += len(notes)
        kind = _classify_text(style, text, bool(maths))
        if kind == "heading" and not level:
            digit = re.search(r"(\d)", style)
            level = max(1, min(4, int(digit.group(1)))) if digit else 1

        block = {"kind": kind, "text": text, "style": style, "notes": notes}
        if maths:
            block["math"] = maths
        if kind == "heading":
            block["level"] = level or 1
        if text or kind != "para":
            blocks.append(block)
    return blocks, meta


# ---------------------------------------------------------------------------
# 生成端：OOXML 片段
# ---------------------------------------------------------------------------

def _run_props(face, eastasia, half_pt, bold=False):
    emphasis = "<w:b/><w:bCs/>" if bold else ""
    return ('<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s"/>%s'
            '<w:sz w:val="%d"/></w:rPr>'
            % (escape_xml(face), escape_xml(face), escape_xml(eastasia), emphasis, half_pt))


def _spacing(before=0, after=0, line=240, rule="auto"):
    return ('<w:spacing w:before="%d" w:after="%d" w:line="%d" w:lineRule="%s"/>'
            % (before, after, line, rule))


def _style_part(style_id, label, paragraph_props, run_props, style_type="paragraph"):
    return ('<w:style w:type="%s" w:styleId="%s"><w:name w:val="%s"/>%s%s</w:style>'
            % (style_type, style_id, escape_xml(label), paragraph_props, run_props))


def build_styles(metrics):
    """生成 word/styles.xml：Normal/Heading/Title/Caption/Bibliography 等样式。"""
    face = metrics["font"]
    eastasia = metrics["eastasia"]
    half_pt = metrics["base_pt2"]
    line = metrics["line_twips"]
    rule = metrics.get("line_rule", "auto")
    normal_ppr = (_spacing(metrics.get("space_before", 0), metrics.get("space_after", 120), line, rule)
                  + '<w:jc w:val="%s"/>' % metrics.get("jc", "both"))
    if metrics.get("first_line"):
        normal_ppr += '<w:ind w:firstLine="%d"/>' % metrics["first_line"]

    chunks = [XML_DECL + "<w:styles %s>" % HEADER_NS,
              _style_part("Normal", "Normal", normal_ppr, _run_props(face, eastasia, half_pt))]

    for level in (1, 2, 3):
        heading = metrics["headings"][str(level)]
        heading_ppr = (_spacing(heading.get("before", 240), heading.get("after", 120))
                       + '<w:jc w:val="%s"/><w:outlineLvl w:val="%d"/>'
                       % (heading.get("align", "left"), level - 1))
        chunks.append(_style_part("Heading%d" % level, "heading %d" % level,
                                  heading_ppr, _run_props(face, eastasia, heading["sz"],
                                                          heading.get("bold", True))))

    extras = (
        ("Title", "Title", _spacing(240, 240) + '<w:jc w:val="center"/>',
         metrics["title_pt2"], True),
        ("Abstract", "Abstract", _spacing(120, 120, line, rule) + '<w:jc w:val="both"/>',
         metrics["caption_pt2"], False),
        ("Caption", "caption", _spacing(60, 120) + '<w:jc w:val="center"/>',
         metrics["caption_pt2"], False),
        ("Bibliography", "Bibliography",
         _spacing(0, 60) + '<w:ind w:left="%d" w:hanging="%d"/>'
         % (metrics.get("bib_indent", 567), metrics.get("bib_hang", 567)),
         metrics["ref_pt2"], False),
        ("FootnoteText", "footnote text", _spacing(0, 0), metrics["note_pt2"], False),
    )
    for style_id, label, ppr, size, bold in extras:
        chunks.append(_style_part(style_id, label, ppr, _run_props(face, eastasia, size, bold)))

    borders = ('<w:top w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
               '<w:left w:val="none"/><w:bottom w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
               '<w:right w:val="none"/><w:insideH w:val="none"/><w:insideV w:val="none"/>')
    chunks.append('<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>'
                  '<w:tblPr><w:tblBorders>%s</w:tblBorders></w:tblPr></w:style></w:styles>'
                  % borders)
    return "".join(chunks)


def _inline_runs(text, always_bold=False):
    pieces = []
    for token in re.split(r"(\*\*[^*\n]+\*\*|\*[^*\n]+\*)", text or ""):
        bold = always_bold or token.startswith("**")
        italic = not bold and token.startswith("*")
        if token.startswith("**"):
            body = token[2:-2]
        elif italic:
            body = token[1:-1]
        else:
            body = token
        props = "<w:rPr>%s%s</w:rPr>" % ("<w:b/><w:bCs/>" if bold else "",
                                         "<w:i/><w:iCs/>" if italic else "")
        for index, segment in enumerate(body.split("\t")):
            if segment or not index:
                pieces.append('<w:r>%s%s<w:t xml:space="preserve">%s</w:t></w:r>'
                              % (props, "<w:tab/>" if index else "", escape_xml(segment)))
    return "".join(pieces) or '<w:r><w:t xml:space="preserve"></w:t></w:r>'


def _paragraph(style_id, text="", jc=None, bold_all=False, extra="", raw=""):
    align = '<w:jc w:val="%s"/>' % jc if jc else ""
    return ('<w:p><w:pPr><w:pStyle w:val="%s"/>%s%s</w:pPr>%s%s</w:p>'
            % (style_id, align, extra, _inline_runs(text, bold_all), raw))


def _table(rows, metrics):
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    chunks = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="5000" w:type="pct"/>'
              '<w:tblLook w:val="04A0" w:firstRow="1"/></w:tblPr>']
    for row_index, row in enumerate(rows):
        header = ("<w:trPr><w:tblHeader/></w:trPr>"
                  if row_index == 0 and metrics.get("hdr_repeat") else "")
        chunks.append("<w:tr>%s" % header)
        cells = list(row) + [""] * (width - len(row))
        for cell in cells:
            cell_props = (
                '<w:tcPr><w:tcBorders><w:bottom w:val="single" w:sz="4" w:space="0" '
                'w:color="000000"/></w:tcBorders></w:tcPr>'
                if row_index == 0 and len(rows) > 1 else "")
            bold = row_index == 0 and metrics.get("hdr_bold", True)
            chunks.append('<w:tc>%s%s</w:tc>' % (cell_props, _paragraph("Normal", cell, bold_all=bold)))
        chunks.append("</w:tr>")
    return "".join(chunks) + "</w:tbl>"


def build_docx(path, blocks, metrics):
    """把块序列写成最小 OOXML docx，返回各类内容单元计数。"""
    body, bookmark = [], 0
    counts = dict(figures=0, tables=0, equations=0, footnotes=0, media=0,
                  bookmarks=0, toc=bool(metrics.get("toc_depth")))

    for block in blocks:
        kind = block["kind"]
        text = block.get("text", "")
        if kind == "heading":
            marks = ('<w:bookmarkStart w:id="%d" w:name="_Toc%d"/>'
                     '<w:bookmarkEnd w:id="%d"/>' % (bookmark + 100, bookmark + 1, bookmark + 100))
            body.append(_paragraph("Heading%d" % max(1, min(3, int(block.get("level", 1)))),
                                   text, extra=marks))
            bookmark += 1
        elif kind == "table":
            counts["tables"] += 1
            if block.get("caption"):
                body.append(_paragraph("Caption", block["caption"]))
            body.append(_table(block.get("rows", []), metrics))
        elif kind == "figure":
            counts["figures"] += 1
            if block.get("caption"):
                body.append(_paragraph("Caption", block["caption"]))
        elif kind == "equation":
            counts["equations"] += 1
            suffix = "\t(%s)" % block["_num"] if block.get("_num") else ""
            body.append(_paragraph("Normal", text + suffix, jc="center",
                                   raw="".join(block.get("math", []))))
        elif kind == "caption":
            body.append(_paragraph("Caption", text))
        elif kind == "reference":
            body.append(_paragraph("Bibliography", text))
        elif kind in ("title", "authors", "abstract", "keywords"):
            style = {"title": "Title", "authors": "Normal", "abstract": "Abstract",
                     "keywords": "Abstract"}[kind]
            body.append(_paragraph(style, text))
        else:
            body.append(_paragraph("Normal", text))
            note_list = [text] if kind == "note" else (block.get("notes") or [])
            for note_text in note_list:
                if note_text:
                    counts["footnotes"] += 1
                    body.append(_paragraph("FootnoteText", "[注] " + note_text))

    toc = ""
    if counts["toc"]:
        toc = ('<w:p><w:pPr><w:pStyle w:val="Normal"/></w:pPr>'
               '<w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>'
               '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-%d" \\h \\z \\u </w:instrText></w:r>'
               '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>目录</w:t></w:r>'
               '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>' % int(metrics["toc_depth"]))

    section = ('<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter1"/>'
               '<w:pgSz w:w="%d" w:h="%d"%s/>'
               '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" w:header="%d" w:footer="%d"/>'
               '<w:cols w:num="%d" w:space="%d"%s/></w:sectPr>'
               % (metrics["page_w"], metrics["page_h"],
                  ' w:orient="landscape"' if metrics.get("landscape") else "",
                  metrics["mt"], metrics["mr"], metrics["mb"], metrics["ml"],
                  metrics.get("hd", 851), metrics.get("ft", 992), metrics.get("cols", 1),
                  metrics.get("col_space", 425),
                  ' w:sep="1"' if metrics.get("col_sep") else ""))

    relationships = [("rIdStyles", "styles", "styles.xml"),
                     ("rIdFooter1", "footer", "footer1.xml")]
    parts = [
        ("word/document.xml",
         XML_DECL + '<w:document %s><w:body>%s%s%s</w:body></w:document>'
         % (HEADER_NS, toc, "".join(body), section)),
        ("word/styles.xml", build_styles(metrics)),
        ("word/footer1.xml",
         XML_DECL + '<w:ftr %s><w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
         '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
         '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
         '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r>'
         '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>' % HEADER_NS),
        ("word/_rels/document.xml.rels",
         XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s'
         '</Relationships>' % "".join('<Relationship Id="%s" Type="%s/%s" Target="%s"/>'
                                      % (rel_id, REL_NS, rel_type, target)
                                      for rel_id, rel_type, target in relationships)),
    ]
    overrides = [("document", "document.main"), ("styles", "styles"), ("footer1", "footer")]
    content_types = (
        XML_DECL + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        + "".join('<Override PartName="/word/%s.xml" ContentType="%s.%s+xml"/>' % (part, DOC_MIME, kind)
                  for part, kind in overrides)
        + "</Types>")
    package_rels = (
        XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="%s/officeDocument" Target="word/document.xml"/></Relationships>'
        % REL_NS)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_rels)
        for name, payload in parts:
            archive.writestr(name, payload)
    counts["bookmarks"] = bookmark
    return counts
