#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slidewriter -- stdlib OOXML writer that produces an editable .pptx, plus an
optional LibreOffice-based PDF export.

    python3 slidewriter.py --plan work/slide_plan.json --out output/presentation.pptx
        [--template in/template.pptx] [--info work/deck_info.json]

write_deck(deck, out, template=None) returns a small info mapping.  A deck looks
like {"title", "subtitle", "meta", "slides":[{"title","bullets":[{"text",
"locator"}],"notes","layout"}]}.  The built-in master is 16:9
(12192000x6858000 EMU), dark-blue titles, Arial for Latin and Microsoft YaHei
for CJK.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# ---------------- OOXML namespaces and geometry ----------------


XMLN_A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


XMLN_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


XMLN_P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'


XML_NS = XMLN_A + " " + XMLN_R + " " + XMLN_P


XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


REL_URI = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


MIME_VENDOR = "application/vnd.openxmlformats-officedocument"


SLIDE_W, SLIDE_H, EMU_INCH = 12192000, 6858000, 914400


# ---------------- low-level OOXML fragments ----------------


def xml_escape(s):
    return (str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def emu(v):
    return int(round(v * EMU_INCH))


def text_run(t, sz=None, b=False, c=None):
    rp = 'lang="en-US"' + (' sz="%d"' % (sz * 100) if sz else "") + (' b="1"' if b else "")
    f = '<a:solidFill><a:srgbClr val="%s"/></a:solidFill>' % c if c else ""
    return '<a:r><a:rPr %s dirty="0">%s</a:rPr><a:t>%s</a:t></a:r>' % (rp, f, xml_escape(t))


def paragraph(t, sz=None, b=False, c=None, bullet=True, algn=None):
    h = '<a:pPr lvl="0"%s' % (' algn="%s"' % algn if algn else "")
    h += (' marL="%d" indent="%d"><a:buFont typeface="Arial"/><a:buChar char="&#8226;"/></a:pPr>'
          % (emu(0.25), -emu(0.25))) if bullet else ' marL="0" indent="0"><a:buNone/></a:pPr>'
    return "<a:p>%s%s</a:p>" % (h, text_run(t, sz, b, c))


def shape(pid, name, ph, box, body="", anchor="t"):
    """ph=(type,idx) or None; box=(x,y,cx,cy) in EMU or None."""
    nv = ('<p:nvSpPr><p:cNvPr id="%d" name="%s"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>%s</p:nvSpPr>'
          % (pid, xml_escape(name), '<p:nvPr><p:ph type="%s" idx="%d"/></p:nvPr>' % ph if ph else "<p:nvPr/>"))
    geo = ('<p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
           '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>' % box) if box else "<p:spPr/>"
    return ('<p:sp>%s%s<p:txBody><a:bodyPr wrap="square" anchor="%s"><a:normAutofit/></a:bodyPr>'
            '<a:lstStyle/>%s</p:txBody></p:sp>' % (nv, geo, anchor, body))


# ---------------- built-in master / layout / notes master ----------------


SP_TREE = ('<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>')


TITLE_BOX = (emu(0.6), emu(0.35), SLIDE_W - emu(1.2), emu(1.1))


BODY_BOX = (emu(0.6), emu(1.6), SLIDE_W - emu(1.2), SLIDE_H - emu(2.1))


THEME_XML = "".join([
    XML_DECL, '<a:theme %s name="TalkDeckStudio"><a:themeElements><a:clrScheme name="TalkDeckStudio">' % XMLN_A,
    '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>',
    '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>',
    '<a:dk2><a:srgbClr val="1F3864"/></a:dk2><a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>',
    '<a:accent1><a:srgbClr val="1F4E79"/></a:accent1><a:accent2><a:srgbClr val="C00000"/></a:accent2>',
    '<a:accent3><a:srgbClr val="595959"/></a:accent3><a:accent4><a:srgbClr val="2E75B6"/></a:accent4>',
    '<a:accent5><a:srgbClr val="548235"/></a:accent5><a:accent6><a:srgbClr val="BF8F00"/></a:accent6>',
    '<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink>',
    '</a:clrScheme><a:fontScheme name="TalkDeckStudio"><a:majorFont><a:latin typeface="Arial"/>',
    '<a:ea typeface="Microsoft YaHei"/><a:cs typeface=""/></a:majorFont><a:minorFont>',
    '<a:latin typeface="Arial"/><a:ea typeface="Microsoft YaHei"/><a:cs typeface=""/></a:minorFont>',
    '</a:fontScheme><a:fmtScheme name="TalkDeckStudio"><a:fillStyleLst>',
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3, '</a:fillStyleLst><a:lnStyleLst>',
    "".join('<a:ln w="%d"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
            '<a:prstDash val="solid"/></a:ln>' % w for w in (6350, 12700, 19050)),
    '</a:lnStyleLst><a:effectStyleLst>', '<a:effectStyle><a:effectLst/></a:effectStyle>' * 3,
    '</a:effectStyleLst><a:bgFillStyleLst>', '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3,
    '</a:bgFillStyleLst></a:fmtScheme></a:themeElements>',
    '<a:objectDefaults/><a:extraClrSchemeLst/></a:theme>'])


CLRMAP_XML = ('<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
          'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>')


TEXT_STYLES = ('<p:txStyles><p:titleStyle><a:lvl1pPr algn="l"><a:defRPr sz="3200" b="1"><a:solidFill>'
       '<a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mj-lt"/><a:ea typeface="+mj-ea"/>'
       '</a:defRPr></a:lvl1pPr></p:titleStyle><p:bodyStyle><a:lvl1pPr marL="%d" indent="%d">'
       '<a:defRPr sz="2000"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mn-lt"/>'
       '<a:ea typeface="+mn-ea"/></a:defRPr></a:lvl1pPr></p:bodyStyle><p:otherStyle><a:lvl1pPr>'
       '<a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle></p:txStyles>' % (emu(0.25), -emu(0.25)))


MASTER_XML = "".join([XML_DECL, "<p:sldMaster %s><p:cSld>" % XML_NS,
                  '<p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>', SP_TREE,
                  shape(2, "Deck Title Placeholder", ("title", 0), TITLE_BOX, paragraph("Title", 32, True, bullet=False)),
                  shape(3, "Deck Body Placeholder", ("body", 1), BODY_BOX, paragraph("Body", 20)),
                  '</p:spTree></p:cSld>', CLRMAP_XML,
                  '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>',
                  TEXT_STYLES, '</p:sldMaster>'])


LAYOUT_XML = "".join([XML_DECL, '<p:sldLayout %s type="obj" preserve="1"><p:cSld name="Deck Title and Content">' % XML_NS, SP_TREE,
                  shape(2, "Deck Title", ("title", 0), TITLE_BOX, paragraph("Title", 32, True, bullet=False)),
                  shape(3, "Deck Body", ("body", 1), BODY_BOX, paragraph("Body", 20)),
                  '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'])


NOTES_MASTER_XML = "".join([XML_DECL, "<p:notesMaster %s><p:cSld>" % XML_NS, SP_TREE,
                   shape(2, "Slide Thumbnail Placeholder", ("sldImg", 2), (emu(0.7), emu(1.2), emu(6.0), emu(3.4))),
                   shape(3, "Speaker Notes Placeholder", ("body", 3), (emu(0.7), emu(4.8), emu(6.0), emu(3.8)),
                      paragraph("Notes", 12, bullet=False)),
                   '</p:spTree></p:cSld>', CLRMAP_XML,
                   '<p:notesStyle><a:lvl1pPr><a:defRPr sz="1200"/></a:lvl1pPr></p:notesStyle></p:notesMaster>'])


# ---------------- per-slide and per-notes XML ----------------


def render_slide(s, meta=""):
    sh = []
    if s.get("layout") == "title":
        sh.append(shape(2, "Deck Title", ("title", 0), (emu(0.9), emu(2.0), SLIDE_W - emu(1.8), emu(1.6)),
                     paragraph(s.get("title", ""), 40, True, "1F4E79", False, "ctr"), "b"))
        if s.get("subtitle"):
            sh.append(shape(3, "Subtitle 2", ("body", 1), (emu(0.9), emu(3.8), SLIDE_W - emu(1.8), emu(1.3)),
                         paragraph(s["subtitle"], 20, False, "404040", False, "ctr")))
        if meta:
            sh.append(shape(4, "Meta 3", None, (emu(0.9), emu(5.3), SLIDE_W - emu(1.8), emu(0.7)),
                         paragraph(meta, 14, False, "595959", False, "ctr")))
    else:
        bl = s.get("bullets") or []
        sh.append(shape(2, "Deck Title", ("title", 0), (emu(0.6), emu(0.32), SLIDE_W - emu(1.2), emu(0.95)),
                     paragraph(s.get("title", ""), 28, True, "1F4E79", False), "ctr"))
        body = "".join(paragraph(b.get("text", ""), 18 if len(bl) <= 4 else 16) for b in bl) or paragraph("(none)", 16, bullet=False)
        sh.append(shape(3, "Deck Body", ("body", 1), (emu(0.6), emu(1.45), SLIDE_W - emu(1.2), SLIDE_H - emu(2.35)), body))
        if s.get("source"):
            sh.append(shape(4, "Source 3", None, (emu(0.6), SLIDE_H - emu(0.78), SLIDE_W - emu(1.2), emu(0.35)),
                         paragraph("Source: " + s["source"], 10, False, "808080", False)))
    return "".join([XML_DECL, "<p:sld %s><p:cSld>" % XML_NS, SP_TREE, "".join(sh),
                    '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'])


def render_notes(text):
    ps = "".join(paragraph(x, 12, bullet=False) for x in str(text or "").split("\n"))
    return "".join([XML_DECL, "<p:notes %s><p:cSld>" % XML_NS, SP_TREE,
                    shape(2, "Speaker Notes Placeholder", ("body", 1), None, ps or paragraph("")),
                    '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>'])


REL_HEAD = XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'


def relationship(rid, typ, tgt):
    return '<Relationship Id="%s" Type="%s%s" Target="%s"/>' % (rid, REL_URI, typ, tgt)


# ---------------- package assembly ----------------


def write_package(path, parts):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmpz")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in parts:
            z.writestr(n, d.encode("utf-8") if isinstance(d, str) else d)
    os.replace(tmp, path)


def write_builtin(deck, out):
    sl, meta, n = deck.get("slides") or [], deck.get("meta") or "", len(deck.get("slides") or [])
    ct = [XML_DECL + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
          '<Default Extension="xml" ContentType="application/xml"/>']
    for pn, tp in (("presentation", "presentation.main"), ("slideMasters/slideMaster1", "slideMaster"),
                   ("slideLayouts/slideLayout1", "slideLayout"), ("notesMasters/notesMaster1", "notesMaster"),
                   ("theme/theme1", "theme"), ("presProps", "presProps"), ("viewProps", "viewProps"),
                   ("tableStyles", "tableStyles")):
        ct.append('<Override PartName="/ppt/%s.xml" ContentType="%s.%s+xml"/>'
                  % (pn, MIME_VENDOR, tp if tp == "theme" else "presentationml." + tp))
    for i in range(1, n + 1):
        ct.append('<Override PartName="/ppt/slides/slide%d.xml" ContentType="%s.presentationml.slide+xml"/>'
                  '<Override PartName="/ppt/notesSlides/notesSlide%d.xml" ContentType="%s.presentationml.notesSlide+xml"/>'
                  % (i, MIME_VENDOR, i, MIME_VENDOR))
    ct.append("</Types>")
    parts = [("[Content_Types].xml", "".join(ct)),
             ("_rels/.rels", REL_HEAD + relationship("rId1", "officeDocument", "ppt/presentation.xml") + "</Relationships>")]
    pres = [XML_DECL, "<p:presentation %s saveSubsetFonts=\"1\">" % XML_NS,
            '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>',
            '<p:notesMasterIdLst><p:notesMasterId r:id="rId2"/></p:notesMasterIdLst>', "<p:sldIdLst>"]
    prels = [REL_HEAD, relationship("rId1", "slideMaster", "slideMasters/slideMaster1.xml"),
             relationship("rId2", "notesMaster", "notesMasters/notesMaster1.xml"),
             relationship("rId3", "theme", "theme/theme1.xml"), relationship("rId4", "presProps", "presProps.xml"),
             relationship("rId5", "viewProps", "viewProps.xml"), relationship("rId6", "tableStyles", "tableStyles.xml")]
    for i in range(1, n + 1):
        pres.append('<p:sldId id="%d" r:id="rId%d"/>' % (255 + i, 100 + i))
        prels.append(relationship("rId%d" % (100 + i), "slide", "slides/slide%d.xml" % i))
        parts += [("ppt/slides/slide%d.xml" % i, render_slide(sl[i - 1], meta)),
                  ("ppt/slides/_rels/slide%d.xml.rels" % i, REL_HEAD +
                   relationship("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml") +
                   relationship("rId2", "notesSlide", "../notesSlides/notesSlide%d.xml" % i) + "</Relationships>"),
                  ("ppt/notesSlides/notesSlide%d.xml" % i, render_notes(sl[i - 1].get("notes"))),
                  ("ppt/notesSlides/_rels/notesSlide%d.xml.rels" % i, REL_HEAD +
                   relationship("rId1", "notesMaster", "../notesMasters/notesMaster1.xml") +
                   relationship("rId2", "slide", "../slides/slide%d.xml" % i) + "</Relationships>")]
    pres.append('</p:sldIdLst><p:sldSz cx="%d" cy="%d"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>'
                % (SLIDE_W, SLIDE_H))
    prels.append("</Relationships>")
    parts += [("ppt/presentation.xml", "".join(pres)), ("ppt/_rels/presentation.xml.rels", "".join(prels)),
              ("ppt/slideMasters/slideMaster1.xml", MASTER_XML),
              ("ppt/slideMasters/_rels/slideMaster1.xml.rels", REL_HEAD +
               relationship("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml") +
               relationship("rId2", "theme", "../theme/theme1.xml") + "</Relationships>"),
              ("ppt/slideLayouts/slideLayout1.xml", LAYOUT_XML),
              ("ppt/slideLayouts/_rels/slideLayout1.xml.rels", REL_HEAD +
               relationship("rId1", "slideMaster", "../slideMasters/slideMaster1.xml") + "</Relationships>"),
              ("ppt/notesMasters/notesMaster1.xml", NOTES_MASTER_XML),
              ("ppt/notesMasters/_rels/notesMaster1.xml.rels", REL_HEAD +
               relationship("rId1", "theme", "../theme/theme1.xml") + "</Relationships>"),
              ("ppt/theme/theme1.xml", THEME_XML),
              ("ppt/presProps.xml", XML_DECL + "<p:presentationPr %s/>" % XML_NS),
              ("ppt/viewProps.xml", XML_DECL + '<p:viewPr %s><p:gridSpacing cx="76200" cy="76200"/></p:viewPr>' % XML_NS),
              ("ppt/tableStyles.xml", XML_DECL + '<a:tblStyleLst %s def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>' % XMLN_A)]
    write_package(out, parts)
    return {"mode": "builtin_master", "slides": n}


def attr_of(tag, k):
    m = re.search(r'%s="([^"]*)"' % k, tag)
    return m.group(1) if m else ""


def write_from_template(deck, out, tmpl):
    """Keep the template's masters, layouts, theme and fonts; replace its slide list with ours."""
    z = zipfile.ZipFile(tmpl)
    names = set(z.namelist())
    pres = z.read("ppt/presentation.xml").decode("utf-8-sig")
    rels = z.read("ppt/_rels/presentation.xml.rels").decode("utf-8-sig")
    tags = re.findall(r"<Relationship\b[^>]*/>", rels)
    rmap = {attr_of(t, "Id"): attr_of(t, "Target") for t in tags}
    notes_tgt = next((attr_of(t, "Target") for t in tags if attr_of(t, "Type").endswith("/notesMaster")), "")
    drop, keep = set(), []
    for t in tags:
        if attr_of(t, "Type").endswith(("/slide", "/notesSlide")):
            b = attr_of(t, "Target").lstrip("/")
            b = b[4:] if b.startswith("ppt/") else "ppt/" + b
            drop |= {b, b.rsplit("/", 1)[0] + "/_rels/" + b.rsplit("/", 1)[1] + ".rels"}
        else:
            keep.append(t)
    for nm in names:
        if re.match(r"ppt/(slides/slide|notesSlides/notesSlide)\d+\.xml$", nm):
            drop |= {nm, nm.rsplit("/", 1)[0] + "/_rels/" + nm.rsplit("/", 1)[1] + ".rels"}
    layouts = sorted(n for n in names if re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", n))
    if not layouts:
        raise ValueError("template has no slideLayout")
    chosen = layouts[0]
    for c in layouts:
        if 'type="obj"' in z.read(c).decode("utf-8-sig", "ignore")[:700].lower():
            chosen = c
            break
    sl, meta = deck.get("slides") or [], deck.get("meta") or ""
    used = [int(x[3:]) for x in rmap if re.match(r"rId\d+$", x)]
    nxt = (max(used) + 1) if used else 1
    base = max([int(x) for x in re.findall(r'<p:sldId id="(\d+)"', pres)] or [255]) + 1
    ids, nrels, ovr, newp = [], [], [], []
    for i in range(1, len(sl) + 1):
        rid = "rId%d" % nxt
        nxt += 1
        ids.append('<p:sldId id="%d" r:id="%s"/>' % (base - 1 + i, rid))
        nrels.append(relationship(rid, "slide", "slides/slide%d.xml" % i))
        ovr.append('<Override PartName="/ppt/slides/slide%d.xml" ContentType="%s.presentationml.slide+xml"/>' % (i, MIME_VENDOR))
        newp.append(("ppt/slides/slide%d.xml" % i, render_slide(sl[i - 1], meta)))
        srel = [relationship("rId1", "slideLayout", "../slideLayouts/" + chosen.split("/")[-1])]
        if notes_tgt:
            srel.append(relationship("rId2", "notesSlide", "../notesSlides/notesSlide%d.xml" % i))
            ovr.append('<Override PartName="/ppt/notesSlides/notesSlide%d.xml" ContentType="%s.presentationml.notesSlide+xml"/>' % (i, MIME_VENDOR))
            newp += [("ppt/notesSlides/notesSlide%d.xml" % i, render_notes(sl[i - 1].get("notes"))),
                     ("ppt/notesSlides/_rels/notesSlide%d.xml.rels" % i, REL_HEAD +
                      relationship("rId1", "notesMaster", "../" + notes_tgt.replace("../", "")) +
                      relationship("rId2", "slide", "../slides/slide%d.xml" % i) + "</Relationships>")]
        newp.append(("ppt/slides/_rels/slide%d.xml.rels" % i, REL_HEAD + "".join(srel) + "</Relationships>"))
    block = "<p:sldIdLst>" + "".join(ids) + "</p:sldIdLst>"
    pres = re.sub(r"<p:sldIdLst>.*?</p:sldIdLst>", block, pres, flags=re.S)
    if "<p:sldIdLst>" not in pres:
        pres = pres.replace("<p:sldSz", block + "<p:sldSz", 1)
    ct = z.read("[Content_Types].xml").decode("utf-8-sig")
    for nm in drop:
        ct = re.sub(r'<Override PartName="/%s"[^>]*/>' % re.escape(nm), "", ct)
    ct = ct.replace("</Types>", "".join(ovr) + "</Types>")
    over = {"[Content_Types].xml": ct, "ppt/presentation.xml": pres,
            "ppt/_rels/presentation.xml.rels": REL_HEAD + "".join(keep + nrels) + "</Relationships>"}
    parts = [(nm, over[nm] if nm in over else z.read(nm))
             for nm in z.namelist() if nm not in drop and not nm.endswith("/")]
    write_package(out, parts + newp)
    return {"mode": "template_rebuilt", "slides": len(sl), "template": str(tmpl),
            "layout_used": chosen.split("/")[-1]}


# ---------------- public entry points ----------------


def write_deck(deck, out, template=None):
    info = {"template_used": False, "errors": []}
    if template:
        try:
            info.update(write_from_template(deck, out, Path(template)))
            info["template_used"] = True
            return info
        except Exception as e:
            info["errors"].append("template inheritance failed: %r" % (e,))
    info.update(write_builtin(deck, out))
    return info


def libreoffice_pdf(pptx, out_dir):
    """Best-effort high-fidelity PDF via LibreOffice; returns a Path or None."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None
    try:
        subprocess.run([exe, "--headless", "--norestore", "--convert-to", "pdf", "--outdir",
                        str(out_dir), str(pptx)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=150)
        c = Path(out_dir) / (Path(pptx).stem + ".pdf")
        if c.exists() and c.stat().st_size > 1200:
            return c
    except Exception:
        pass
    return None


def cli_main():
    ap = argparse.ArgumentParser(description="OOXML deck writer with optional LibreOffice PDF export")
    ap.add_argument("--plan"); ap.add_argument("--out"); ap.add_argument("--template")
    ap.add_argument("--info", help="write the build info JSON to this path")
    a = ap.parse_args()
    if not (a.plan and a.out):
        ap.print_help()
        return 0
    try:
        d = json.loads(Path(a.plan).read_text(encoding="utf-8-sig"))
        info = write_deck(d.get("deck", d), a.out, a.template)
        if a.info:
            Path(a.info).parent.mkdir(parents=True, exist_ok=True)
            Path(a.info).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(info, ensure_ascii=False))
    except Exception as e:
        print("slidewriter error: %r" % (e,))
    return 0


def wrap_text(text, size, max_width):
    
    text = "" if text is None else str(text)
    lines, cur, w = [], "", 0.0
    for ch in text:
        cw = float(size) if ord(ch) > 0x2E7F else float(size) * 0.55
        if w + cw > max_width and cur:
            lines.append(cur)
            cur, w = ch, cw
        else:
            cur += ch
            w += cw
    if cur:
        lines.append(cur)
    return lines or [""]


if __name__ == "__main__":
    sys.exit(cli_main())
