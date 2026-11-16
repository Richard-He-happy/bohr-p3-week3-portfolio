#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ooxml.py — 文档读写底层：Markdown/LaTeX/Word 解析、最小 OOXML 打包、docx 模板取值读取。

中间表示是块序列（dict 列表），上层不碰 XML。仅标准库；不联网；无绝对路径。
"""

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
CT_WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml"
W, M = "{%s}" % WORD_NS, "{%s}" % MATH_NS
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
NSDECL = ('xmlns:w="%s" xmlns:r="%s" xmlns:m="%s" xmlns:wp="http://schemas.openxmlformats.org/'
          'drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/'
          '2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
          % (WORD_NS, REL_NS, MATH_NS))
CTRL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
CAP = re.compile(r"^\s*(图|表|式|Fig\.?|Figure|Table|Eq\.?|Equation)\s*[（(]?\s*(\d+[.\-]?\d*)")
H_RE = re.compile(r"^(#{1,6})\s+(.*)$")
IMG_RE = re.compile(r"^!\[(.*?)\]\((.*?)\)\s*$")
FN_RE = re.compile(r"^\[\^([^\]]+)\]:\s*(.*)$")
LI_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*)$")
SEP_RE = re.compile(r"^[\s:\-|]+$")
STOP_RE = re.compile(r"^(#|\||!\[|\$\$|\[\^|[-*+] |\d+[.)] )")
PAGE_TWIP = {"A4": (11906, 16838), "A3": (16838, 23811), "A5": (8391, 11906)}


def esc(v):
    """去控制字符后转义。"""
    return escape(CTRL.sub("", "" if v is None else str(v)))


def first_num(v, d=0.0):
    m = re.search(r"-?[\d.]+", str(v))
    return float(m.group(0)) if m else d


def squeeze(v):
    return re.sub(r"\s+", " ", v or "").strip()


def slurp_text(p):
    """按 utf-8-sig / utf-8 / gb18030 / latin-1 依次试解码。"""
    raw = open(p, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def _math(lines, i):
    head = lines[i].strip()
    close = "$$" if head.startswith("$$") else "\\]"
    carry = head[2:].strip()
    if carry.endswith(close):
        return {"kind": "equation", "text": carry[:-2].strip()}, i + 1
    parts, j = ([carry] if carry else []), i + 1
    while j < len(lines) and not lines[j].strip().endswith(close):
        parts.append(lines[j])
        j += 1
    if j < len(lines):
        parts.append(lines[j].strip()[:-2])
    return {"kind": "equation", "text": "\n".join(parts).strip()}, j + 1


def _tbl(lines, i):
    rows, j = [], i
    while j < len(lines) and lines[j].strip().startswith("|"):
        line = lines[j].strip()
        if not SEP_RE.match(line):
            rows.append([c.strip() for c in line.strip("|").split("|")])
        j += 1
    return ({"kind": "table", "rows": rows} if rows else None), j


def _para(lines, i):
    parts, j = [lines[i].strip()], i + 1
    while j < len(lines) and lines[j].strip() and not STOP_RE.match(lines[j].strip()):
        parts.append(lines[j].strip())
        j += 1
    return {"kind": "para", "text": " ".join(parts)}, j


def md_blocks(text):
    """Markdown → (块序列, 元信息)。行内标记留原样给写出层。"""
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        m = H_RE.match(s)
        if m:
            out.append({"kind": "heading", "text": m.group(2).strip(), "level": len(m.group(1))})
            i += 1
            continue
        m = IMG_RE.match(s)
        if m:
            out.append({"kind": "figure", "caption": m.group(1).strip(), "image": m.group(2).strip()})
            i += 1
            continue
        if s.startswith("$$") or s.startswith("\\["):
            b, i = _math(lines, i)
            out.append(b)
            continue
        if s.startswith("|") and s.count("|") >= 2:
            b, i = _tbl(lines, i)
            if b:
                out.append(b)
            continue
        m = FN_RE.match(s)
        if m:
            out.append({"kind": "note", "text": m.group(2).strip(), "id": m.group(1)})
            i += 1
            continue
        m = LI_RE.match(s)
        if m or CAP.match(s):
            out.append({"kind": "bullet", "text": m.group(1).strip()} if m else {"kind": "caption", "text": s})
            i += 1
            continue
        b, i = _para(lines, i)
        out.append(b)
    return out, {"footnotes": sum(1 for b in out if b["kind"] == "note")}


def _style_of(p):
    style, lvl, ppr = "", 0, p.find(W + "pPr")
    if ppr is not None:
        node = ppr.find(W + "pStyle")
        style = (node.get(W + "val") or "") if node is not None else ""
        node = ppr.find(W + "outlineLvl")
        if node is not None:
            try:
                lvl = int(node.get(W + "val")) + 1
            except (TypeError, ValueError):
                lvl = 0
    return style, lvl


def _kind(style, text, math):
    s = (style or "").lower()
    if re.search(r"heading|标题|head\d", s):
        return "heading"
    if re.search(r"caption|题注|图注|表注", s) or CAP.match(text):
        return "caption"
    for k, pat in (("title", r"title"), ("abstract", r"abstract|摘要"),
                   ("keywords", r"keyword|关键词"), ("reference", r"bibliograph|reference|参考文献")):
        if re.search(pat, s):
            return k
    if re.match(r"^\[\d+\]", text):
        return "reference"
    return "equation" if (math and len(text) < 3) else "para"


def docx_blocks(path):
    """docx → (块序列, 元信息)；表格按行读，脚注正文从 footnotes.xml 取。"""
    zf = zipfile.ZipFile(path)
    names = set(zf.namelist())
    body = ET.fromstring(zf.read("word/document.xml")).find(W + "body")
    pool = {}
    if "word/footnotes.xml" in names:
        for fn in ET.fromstring(zf.read("word/footnotes.xml")).findall(W + "footnote"):
            pool[fn.get(W + "id")] = squeeze("".join(n.text or "" for n in fn.iter(W + "t")))
    meta, out = {"footnotes": 0}, []
    for el in list(body):
        if el.tag == W + "tbl":
            out.append({"kind": "table", "text": "", "rows": [
                [squeeze("".join(n.text or "" for n in c.iter(W + "t"))) for c in r.findall(W + "tc")]
                for r in el.findall(W + "tr")]})
            continue
        if el.tag != W + "p":
            continue
        style, lvl = _style_of(el)
        text = squeeze("".join(n.text or "" for n in el.iter(W + "t")))
        maths = [ET.tostring(m, encoding="unicode") for m in el.iter(M + "oMath")]
        refs = [pool.get(r.get(W + "id"), "") for r in el.iter(W + "footnoteReference")]
        meta["footnotes"] += len(refs)
        k = _kind(style, text, bool(maths))
        if k == "heading" and not lvl:
            d = re.search(r"(\d)", style)
            lvl = max(1, min(4, int(d.group(1)))) if d else 1
        b = {"kind": k, "text": text, "style": style, "notes": refs}
        if maths:
            b["math"] = maths
        if k == "heading":
            b["level"] = lvl or 1
        if text or k != "para":
            out.append(b)
    return out, meta


def _rpr(font, ea, sz, bold=False):
    return ('<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s"/>%s<w:sz w:val="%d"/></w:rPr>'
            % (esc(font), esc(font), esc(ea), "<w:b/><w:bCs/>" if bold else "", sz))


def _gap(b=0, a=0, line=240, rule="auto"):
    return '<w:spacing w:before="%d" w:after="%d" w:line="%d" w:lineRule="%s"/>' % (b, a, line, rule)


def _style(sid, label, ppr, rpr, kind="paragraph"):
    return ('<w:style w:type="%s" w:styleId="%s"><w:name w:val="%s"/>%s%s</w:style>'
            % (kind, sid, esc(label), ppr, rpr))


def stylesheet(n):
    """styles.xml：Normal / Heading1-3 / Title / Abstract / Caption / Bibliography / FootnoteText。"""
    font, ea, line, rule = n["font"], n["ea"], n["line"], n.get("lineRule", "auto")
    base = _gap(n.get("space_before", 0), n.get("space_after", 120), line, rule)
    base += '<w:jc w:val="%s"/>' % n.get("align", "both")
    if n.get("first_line"):
        base += '<w:ind w:firstLine="%d"/>' % n["first_line"]
    out = [HEAD + '<w:styles %s>' % NSDECL, _style("Normal", "Normal", base, _rpr(font, ea, n["sz"]))]
    for d in (1, 2, 3):
        h = n["h"][str(d)]
        out.append(_style("Heading%d" % d, "heading %d" % d, _gap(h.get("before", 240), h.get("after", 120))
                          + '<w:jc w:val="%s"/><w:outlineLvl w:val="%d"/>' % (h.get("align", "left"), d - 1),
                          _rpr(font, ea, h["sz"], h.get("bold", True))))
    for sid, label, ppr, sz in (
            ("Title", "Title", _gap(240, 240) + '<w:jc w:val="center"/>', n["t_sz"]),
            ("Abstract", "Abstract", _gap(120, 120, line, rule) + '<w:jc w:val="both"/>', n["cap_sz"]),
            ("Caption", "caption", _gap(60, 120) + '<w:jc w:val="center"/>', n["cap_sz"]),
            ("Bibliography", "Bibliography", _gap(0, 60) + '<w:ind w:left="%d" w:hanging="%d"/>'
             % (n.get("ref_ind", 567), n.get("ref_hang", 567)), n["ref_sz"]),
            ("FootnoteText", "footnote text", _gap(0, 0), n["fn_sz"])):
        out.append(_style(sid, label, ppr, _rpr(font, ea, sz, sid == "Title")))
    border = ('<w:top w:val="single" w:sz="8" w:space="0" w:color="000000"/><w:left w:val="none"/>'
              '<w:bottom w:val="single" w:sz="8" w:space="0" w:color="000000"/><w:right w:val="none"/>'
              '<w:insideH w:val="none"/><w:insideV w:val="none"/>')
    out.append('<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr>'
               '<w:tblBorders>%s</w:tblBorders></w:tblPr></w:style></w:styles>' % border)
    return "".join(out)


def _runs(text, all_bold=False):
    """把 **粗** / *斜* 拆成 run，制表符转 w:tab。"""
    pieces = []
    for frag in re.split(r"(\*\*[^*\n]+\*\*|\*[^*\n]+\*)", text or ""):
        bold = all_bold or frag.startswith("**")
        ital = not bold and frag.startswith("*")
        body = frag[2:-2] if frag.startswith("**") else (frag[1:-1] if ital else frag)
        props = "<w:rPr>%s%s</w:rPr>" % ("<w:b/><w:bCs/>" if bold else "", "<w:i/><w:iCs/>" if ital else "")
        for idx, seg in enumerate(body.split("\t")):
            if seg or not idx:
                pieces.append('<w:r>%s%s<w:t xml:space="preserve">%s</w:t></w:r>'
                              % (props, "<w:tab/>" if idx else "", esc(seg)))
    return "".join(pieces) or '<w:r><w:t xml:space="preserve"></w:t></w:r>'


def wpar(style, text="", align=None, all_bold=False, extra="", raw=""):
    return '<w:p><w:pPr><w:pStyle w:val="%s"/>%s%s</w:pPr>%s%s</w:p>' % (
        style, '<w:jc w:val="%s"/>' % align if align else "", extra, _runs(text, all_bold), raw)


def _table(rows, n):
    """三线表：表头行加下框线，整表无竖线。"""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    out = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="5000" w:type="pct"/>'
           '<w:tblLook w:val="04A0" w:firstRow="1"/></w:tblPr>']
    for ri, row in enumerate(rows):
        out.append("<w:tr>%s" % ("<w:trPr><w:tblHeader/></w:trPr>" if ri == 0 and n.get("hdr_repeat") else ""))
        for cell in list(row) + [""] * (width - len(row)):
            edge = ('<w:tcPr><w:tcBorders><w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
                    '</w:tcBorders></w:tcPr>' if ri == 0 and len(rows) > 1 else "")
            out.append('<w:tc>%s%s</w:tc>'
                       % (edge, wpar("Normal", cell, all_bold=(ri == 0 and n.get("hdr_bold", True)))))
        out.append("</w:tr>")
    return "".join(out) + "</w:tbl>"


def write_docx(path, blocks, n, media=None):
    """块序列 → .docx；返回各内容单元计数。"""
    body, marks = [], 0
    tally = dict(figures=0, tables=0, equations=0, footnotes=0, media=0, bookmarks=0,
                 toc=bool(n.get("toc_levels")))
    for b in blocks:
        k, text = b["kind"], b.get("text", "")
        if k == "heading":
            body.append(wpar("Heading%d" % max(1, min(3, int(b.get("level", 1)))), text,
                              extra='<w:bookmarkStart w:id="%d" w:name="_Toc%d"/><w:bookmarkEnd w:id="%d"/>'
                                    % (marks + 100, marks + 1, marks + 100)))
            marks += 1
        elif k == "table":
            tally["tables"] += 1
            if b.get("caption"):
                body.append(wpar("Caption", b["caption"]))
            body.append(_table(b.get("rows", []), n))
        elif k == "figure":
            tally["figures"] += 1
            if b.get("caption"):
                body.append(wpar("Caption", b["caption"]))
        elif k == "equation":
            tally["equations"] += 1
            body.append(wpar("Normal", text + ("\t(%s)" % b["_num"] if b.get("_num") else ""),
                              align="center", raw="".join(b.get("math", []))))
        elif k == "caption":
            body.append(wpar("Caption", text))
        elif k == "reference":
            body.append(wpar("Bibliography", text))
        elif k in ("title", "authors", "abstract", "keywords"):
            body.append(wpar({"title": "Title", "authors": "Normal", "abstract": "Abstract",
                               "keywords": "Abstract"}[k], text))
        else:
            body.append(wpar("Normal", text))
            for note in ([text] if k == "note" else (b.get("notes") or [])):
                if note:
                    tally["footnotes"] += 1
                    body.append(wpar("FootnoteText", "[注] " + note))
    toc = ""
    if tally["toc"]:
        toc = ('<w:p><w:pPr><w:pStyle w:val="Normal"/></w:pPr><w:r><w:fldChar w:fldCharType="begin" '
               'w:dirty="true"/></w:r><w:r><w:instrText xml:space="preserve"> TOC \\o "1-%d" \\h \\z \\u '
               '</w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>目录</w:t></w:r>'
               '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>' % int(n["toc_levels"]))
    sect = ('<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter1"/><w:pgSz w:w="%d" w:h="%d"%s/>'
            '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" w:header="%d" w:footer="%d"/>'
            '<w:cols w:num="%d" w:space="%d"%s/></w:sectPr>'
            % (n["pgW"], n["pgH"], ' w:orient="landscape"' if n.get("landscape") else "", n["marT"],
               n["marR"], n["marB"], n["marL"], n.get("hd", 851), n.get("ft", 992), n.get("cols", 1),
               n.get("col_space", 425), ' w:sep="1"' if n.get("col_sep") else ""))
    parts = [
        ("word/document.xml", HEAD + '<w:document %s><w:body>%s%s%s</w:body></w:document>'
         % (NSDECL, toc, "".join(body), sect)),
        ("word/styles.xml", stylesheet(n)),
        ("word/footer1.xml", HEAD + '<w:ftr %s><w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
         '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE '
         '</w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r>'
         '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>' % NSDECL),
        ("word/_rels/document.xml.rels", HEAD + '<Relationships xmlns="%s">%s</Relationships>'
         % (PKG_NS, "".join('<Relationship Id="%s" Type="%s/%s" Target="%s"/>' % (i, REL_NS, t, tgt)
                            for i, t, tgt in (("rIdStyles", "styles", "styles.xml"),
                                              ("rIdFooter1", "footer", "footer1.xml"))))),
    ]
    # [Content_Types].xml 用的是 content-types 命名空间，不是 relationships 命名空间
    ctypes = (HEAD + '<Types xmlns="%s"><Default Extension="rels" ContentType="application/vnd.'
              'openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/'
              'xml"/>' % CT_NS + "".join('<Override PartName="/word/%s.xml" ContentType="%s.%s+xml"/>' % (a, CT_WORD, b)
                                          for a, b in (("document", "document.main"), ("styles", "styles"),
                                                       ("footer1", "footer"))) + "</Types>")
    root = (HEAD + '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%s/officeDocument" '
            'Target="word/document.xml"/></Relationships>' % (PKG_NS, REL_NS))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", ctypes)
        zf.writestr("_rels/.rels", root)
        for name, data in parts:
            zf.writestr(name, data)
    tally["bookmarks"] = marks
    return tally


def _attrs(frag):
    return dict(re.findall(r'w:(\w+)="([^"]*)"', frag))


def _traits(chunk):
    """样式块里的字体/字号/悬挂/行距；pt 由 half-point 反算。"""
    t = {}
    for k, pat in (("font", r'<w:rFonts[^>]*w:ascii="([^"]+)"'), ("ea", r'w:eastAsia="([^"]+)"'),
                   ("sz", r'<w:sz w:val="(\d+)"'), ("hang", r'<w:ind[^>]*w:hanging="(\d+)"'),
                   ("line", r'<w:spacing[^>]*w:line="(\d+)"')):
        m = re.search(pat, chunk)
        if m:
            t[k] = m.group(1)
    if "sz" in t:
        t["pt"] = int(t["sz"]) / 2
    m = re.search(r'w:lineRule="(\w+)"', chunk)
    t["rule"] = m.group(1) if m else "auto"
    # 原文片段留作 quote，避免拼出的字符串在来源里查不到
    for key, pat in (("spRaw", r"<w:spacing[^>]*>"), ("szRaw", r"<w:sz[^>]*>"), ("indRaw", r"<w:ind[^>]*>")):
        hit = re.search(pat, chunk)
        t[key] = hit.group(0) if hit else ""
    return t


def docx_spec(path):
    """从 .docx/.dotx 模板取逐项排版规格：页面、页边距、栏数、正文/标题/题注/文献样式、TOC。"""
    zf, base = zipfile.ZipFile(path), Path(path).name
    names = set(zf.namelist())
    dx = zf.read("word/document.xml").decode("utf-8", "replace")
    sx = zf.read("word/styles.xml").decode("utf-8", "replace") if "word/styles.xml" in names else ""
    found = []

    def keep(i, v, loc, quote):
        if v not in (None, "", 0):
            found.append({"id": i, "value": str(v), "source": "template_docx",
                          "locator": "%s#%s" % (base, loc), "quote": quote, "inferred": False})

    sect = dx[dx.rfind("<w:sectPr"):] if "<w:sectPr" in dx else ""
    m = re.search(r"<w:pgSz[^>]*>", sect)
    if m:
        a = _attrs(m.group(0))
        w, h = int(a.get("w", 11906)), int(a.get("h", 16838))
        label = ""
        for name, (pw, ph) in PAGE_TWIP.items():
            if (abs(w - pw) < 60 and abs(h - ph) < 60) or (abs(w - ph) < 60 and abs(h - pw) < 60):
                label = name
        keep("page.size", label or "%dx%dtw" % (w, h), "sectPr/pgSz", m.group(0)[:100])
    m = re.search(r"<w:pgMar[^>]*>", sect)
    if m:
        a = _attrs(m.group(0))
        for side in ("top", "bottom", "left", "right"):
            if side in a:
                keep("page.margin." + side, "%.2fcm" % (int(a[side]) / 1440 * 2.54),
                     "sectPr/pgMar@" + side, 'w:%s="%s"' % (side, a[side]))
    m = re.search(r"<w:cols[^>]*>", sect)
    if m:
        keep("page.columns", _attrs(m.group(0)).get("num", "1"), "sectPr/cols", m.group(0)[:70])

    pool = {}
    for blk in re.finditer(r"<w:style [^>]*>(.*?)</w:style>", sx, re.S):
        nm = re.search(r'<w:name w:val="([^"]+)"', blk.group(1))
        if nm:
            pool[nm.group(1).strip().lower()] = _traits(blk.group(1))
    core = re.search(r"<w:docDefaults>.*?</w:docDefaults>", sx, re.S)
    normal = _traits(core.group(0)) if core else {}
    normal.update({k: v for k, v in pool.get("normal", {}).items() if v})
    keep("body.font", normal.get("font"), "styles.xml[Normal]/rFonts", 'w:ascii="%s"' % (normal.get("font") or ""))
    keep("body.font.eastasia", normal.get("ea"), "styles.xml[Normal]/rFonts",
         'w:eastAsia="%s"' % (normal.get("ea") or ""))
    if normal.get("pt"):
        keep("body.size", "%gpt" % normal["pt"], "styles.xml[Normal]/sz",
             normal.get("szRaw") or '<w:sz w:val="%s"/>' % normal["sz"])
    if normal.get("line"):
        unit = (float(first_num(normal["line"], 240)) / 240 if normal["rule"] == "auto"
                else "%gpt" % (float(first_num(normal["line"])) / 20))
        keep("body.line_spacing", "%g" % unit if normal["rule"] == "auto" else unit,
             "styles.xml[Normal]/spacing", normal.get("spRaw") or '<w:spacing w:line="%s"/>' % normal["line"])
    for d in (1, 2, 3):
        h = pool.get("heading %d" % d) or {}
        if h.get("pt"):
            keep("heading.%d.size" % d, "%gpt" % h["pt"], "styles.xml[heading %d]/sz" % d,
                 h.get("szRaw") or '<w:sz w:val="%s"/>' % h["sz"])
    for item, key in (("caption.size", "caption"), ("reference.size", "bibliography")):
        node = pool.get(key) or {}
        if node.get("pt"):
            keep(item, "%gpt" % node["pt"], "styles.xml[%s]/sz" % key, node.get("szRaw") or '<w:sz w:val="%s"/>' % node["sz"])
    if (pool.get("bibliography") or {}).get("hang"):
        keep("reference.hanging", "%stw" % int(float(pool["bibliography"]["hang"])),
             "styles.xml[Bibliography]/ind", pool["bibliography"].get("indRaw")
             or 'w:hanging="%s"' % pool["bibliography"]["hang"])
    m = re.search(r'TOC \\o "1-(\d)"', dx)
    if m:
        keep("toc.levels", m.group(1), "document.xml[TOC]", m.group(0))
    return found
