#!/usr/bin/env python3
"""OOXML + PDF toolchain (stdlib only).

Assembles an editable .pptx either by rewriting a supplied template/starting deck (keeping
its master, layouts and theme bytes) or by building a minimal package.  PDF preview:
LibreOffice/office-renderer when installed, else a real text-layer PDF from the deck's own
text runs, flagged as degraded.  Nothing here touches the network.
"""
import hashlib, re, shutil, subprocess, zipfile, zlib
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NSDECL = 'xmlns:a="%s" xmlns:r="%s" xmlns:p="%s"' % (NS_A, NS_R, NS_P)
XMLDECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
MIME_PREFIX = "application/vnd.openxmlformats-officedocument.presentationml."
MIME = {"pres": MIME_PREFIX + "presentation.main+xml", "slide": MIME_PREFIX + "slide+xml", "layout": MIME_PREFIX + "slideLayout+xml", "master": MIME_PREFIX + "slideMaster+xml", "notes": MIME_PREFIX + "notesSlide+xml", "nmaster": MIME_PREFIX + "notesMaster+xml", "theme": "application/vnd.openxmlformats-officedocument.theme+xml"}
DEFAULT_SIZE = (12192000, 6858000)
COLORMAP_XML = '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
GROUP_XML = '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
def squash(txt_src):
    return re.sub(r"\s+", " ", re.sub(r"-\s*\n\s*", "", txt_src or "")).strip()
def esc(seg):
    return xml_escape("" if seg is None else str(seg))
def paragraph_list(items, size=None, bullet=True, bold=False):
    it = [seq for seq in (items if isinstance(items, (list, tuple)) else [items]) if str(seq or "").strip()]
    if not it:
        return '<a:p><a:endParaRPr lang="en-US" dirty="0"/></a:p>'
    rp = '<a:rPr lang="en-US" altLang="zh-CN" sz="%d" b="%d" dirty="0"/>' % (size or 1800, 1 if bold else 0)
    bu = '<a:buChar char="&#8226;"/>' if bullet else '<a:buNone/>'
    return "".join('<a:p><a:pPr>%s</a:pPr><a:r>%s<a:t>%s</a:t></a:r></a:p>' % (bu, rp, esc(seg)) for seg in it)
def make_shape(seq, ph, payload, size=None, bullet=True, bold=False, geom=None, name="Shape"):
    if ph:
        attr = ' idx="%s"' % ph[1] if ph[1] not in (None, "") else ""
        placeholder, box = '<p:ph type="%s"%s/>' % (ph[0], attr), '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
        extent = ""
    else:
        placeholder, box = "", '<p:cNvSpPr txBox="1"/>'
        extent = '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/>'
    frame = '<a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>' % tuple(geom) if geom else ""
    return ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s %d"/>%s<p:nvPr>%s</p:nvPr></p:nvSpPr><p:spPr>%s%s</p:spPr>' '<p:txBody><a:bodyPr><a:normAutofit/></a:bodyPr><a:lstStyle/>%s</p:txBody></p:sp>' % (seq, esc(name), seq, box, placeholder, frame, extent, paragraph_list(payload, size, bullet, bold)))
def slide_part(page_shapes):
    return XMLDECL + '<p:sld %s><p:cSld><p:spTree>%s%s</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>' % (NSDECL, GROUP_XML, "".join(page_shapes))
def notes_part(seg):
    return XMLDECL + '<p:notes %s><p:cSld><p:spTree>%s%s</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>' % (NSDECL, GROUP_XML, make_shape(2, ("body", "1"), [seg] if seg else [], None, False, name="Notes"))
def rels_part(pair_list):
    return XMLDECL + '<Relationships xmlns="%s">%s</Relationships>' % (PKG_REL_NS, "".join('<Relationship Id="%s" Type="%s" Target="%s"/>' % prt for prt in pair_list))
def load_rels(txt_src):
    o = {}
    for tag in re.findall(r"<Relationship\b[^>]*/>", txt_src):
        seq, seg, ty = re.search(r'Id="([^"]+)"', tag), re.search(r'Target="([^"]+)"', tag), re.search(r'Type="([^"]+)"', tag)
        if seq and seg:
            o[seq.group(1)] = (seg.group(1), ty.group(1) if ty else "")
    return o
def geom(wd, ht, ky):
    d = {"left": (.05, .24, .44, .66), "sub": (.05, .55, .90, .20), "body": (.05, .24, .90, .66)}
    if ky == "top":
        return (838200, 365125, wd - 1676400, 1143000)
    fx, fy, fw, err = d[ky]
    return (int(wd * fx), int(ht * fy), int(wd * fw), int(ht * err))
def page_shapes(txt_src, wd, ht, title_ph, body_ph):
    acc=[make_shape(2, title_ph, [txt_src.get("title")], None, False, True, name="Title") if title_ph else make_shape(2, None, [txt_src.get("title")], 3000, False, True, geom(wd, ht, "top"), "Title")]
    if txt_src.get("role") == "title":
        acc.append(make_shape(3, body_ph, txt_src.get("bullets"), None, False, name="Subtitle") if body_ph else make_shape(3, None, txt_src.get("bullets"), 1800, False, False, geom(wd, ht, "sub"), "Subtitle"))
    else:
        acc.append(make_shape(3, body_ph, txt_src.get("bullets"), None, True, name="Content") if body_ph else make_shape(3, None, txt_src.get("bullets"), 1800, True, False, geom(wd, ht, "body"), "Content"))
    return acc
def layout_part(knd):
    size = (("ctrTitle", None, 4000, True, (838200, 1600200, 10515600, 1905000), "Title"), ("subTitle", "1", 1800, False, (838200, 3657600, 10515600, 1651000), "Sub")) if knd == 1 else \
         (("title", None, 3000, True, (838200, 365125, 10515600, 1143000), "Title"), ("body", "1", 1800, False, (838200, 1600200, 10515600, 4525963), "Content"))
    head = 'type="title" preserve="1"><p:cSld name="Title Slide"' if knd == 1 else 'type="obj" preserve="1"><p:cSld name="Title and Content"'
    body = make_shape(2, (size[0][0], size[0][1]), ["Title"], size[0][2], False, size[0][3], size[0][4], size[0][5]) + make_shape(3, (size[1][0], size[1][1]), ["Body"], size[1][2], knd == 2, False, size[1][4], size[1][5])
    return XMLDECL + '<p:sldLayout %s %s><p:spTree>%s%s</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>' % (NSDECL, head, GROUP_XML, body)
def master_part():
    tx = ('<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="3000" b="1"/></a:lvl1pPr></p:titleStyle><p:bodyStyle>' '<a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:bodyStyle><p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle></p:txStyles>')
    return XMLDECL + ('<p:sldMaster %s><p:cSld><p:bg><p:bgPr><a:solidFill><a:schemeClr val="bg1"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>' '<p:spTree>%s</p:spTree></p:cSld>%s<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/><p:sldLayoutId id="2147483650" r:id="rId2"/></p:sldLayoutIdLst>%s</p:sldMaster>') % (NSDECL, GROUP_XML, COLORMAP_XML, tx)
def theme_part():
    accents = [("dk2", "1F3864"), ("lt2", "E7E6E6"), ("accent1", "2F5597"), ("accent2", "C55A11"), ("accent3", "70AD47"), ("accent4", "7F6000"), ("accent5", "4472C4"), ("accent6", "808080")]
    scheme = ['<a:clrScheme name="PaperDeck"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>' '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>']
    scheme.extend('<a:%s><a:srgbClr val="%s"/></a:%s>' % (slot, color, slot) for slot, color in accents)
    scheme.append('<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme>')
    fonts = ('<a:fontScheme name="PaperDeck"><a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>' '<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>')
    fill = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    line = '<a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
    effect = '<a:effectStyle><a:effectLst/></a:effectStyle>'
    fmt = ('<a:fmtScheme name="PaperDeck"><a:fillStyleLst>%s</a:fillStyleLst><a:lnStyleLst>%s</a:lnStyleLst>' '<a:effectStyleLst>%s</a:effectStyleLst><a:bgFillStyleLst>%s</a:bgFillStyleLst></a:fmtScheme>' % (fill * 3, line * 3, effect * 3, fill * 3))
    return XMLDECL + ('<a:theme xmlns:a="%s" name="PaperDeck"><a:themeElements>%s%s%s</a:themeElements>' '<a:objectDefaults/><a:extraClrSchemeLst/></a:theme>') % (NS_A, "".join(scheme), fonts, fmt)
def notesmaster_part():
    return XMLDECL + ('<p:notesMaster %s><p:cSld><p:spTree>%s%s</p:spTree></p:cSld>%s<p:notesStyle><a:lvl1pPr><a:defRPr sz="1200"/></a:lvl1pPr></p:notesStyle></p:notesMaster>') % ( NSDECL, GROUP_XML, make_shape(2, ("body", "1"), [], 1200, False, False, (685800, 1143000, 5486400, 4800600), "Notes"), COLORMAP_XML)
def builtin_package(size=DEFAULT_SIZE):
    wd, ht = size
    lr = rels_part([("rId1", NS_R + "/slideMaster", "../slideMasters/slideMaster1.xml")])
    return {"_rels/.rels": rels_part([("rId1", NS_R + "/officeDocument", "ppt/presentation.xml")]), "ppt/slideMasters/slideMaster1.xml": master_part(), "ppt/slideMasters/_rels/slideMaster1.xml.rels": rels_part([("rId1", NS_R + "/slideLayout", "../slideLayouts/slideLayout1.xml"), ("rId2", NS_R + "/slideLayout", "../slideLayouts/slideLayout2.xml"), ("rId3", NS_R + "/theme", "../theme/theme1.xml")]),
            "ppt/slideLayouts/slideLayout1.xml": layout_part(1), "ppt/slideLayouts/slideLayout2.xml": layout_part(2),
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels": lr, "ppt/slideLayouts/_rels/slideLayout2.xml.rels": lr,
            "ppt/theme/theme1.xml": theme_part(), "ppt/notesMasters/notesMaster1.xml": notesmaster_part(),
            "ppt/notesMasters/_rels/notesMaster1.xml.rels": rels_part([("rId1", NS_R + "/theme", "../theme/theme1.xml")]),
            "ppt/presentation.xml": (XMLDECL + '<p:presentation %s saveSubsetFonts="1"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>' '<p:sldIdLst></p:sldIdLst><p:sldSz cx="%d" cy="%d"/><p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle><a:lvl1pPr>' '<a:defRPr sz="1800"/></a:lvl1pPr></p:defaultTextStyle></p:presentation>') % (NSDECL, wd, ht),
            "ppt/_rels/presentation.xml.rels": rels_part([("rId1", NS_R + "/slideMaster", "slideMasters/slideMaster1.xml"), ("rId2", NS_R + "/theme", "theme/theme1.xml"), ("rId3", NS_R + "/notesMaster", "notesMasters/notesMaster1.xml")])}
def contenttypes_part(ct_rows):
    return (XMLDECL + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Default Extension="jpeg" ContentType="image/jpeg"/>'
            + "".join('<Override PartName="/%s" ContentType="%s"/>' % res for res in ct_rows) + "</Types>")
def save_zip(path, parts):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bnd:
        for ky in ["[Content_Types].xml"] + sorted(ky for ky in parts if ky != "[Content_Types].xml"):
            val = parts[ky]
            bnd.writestr(ky, val.encode("utf-8") if isinstance(val, str) else val)
def layout_catalog(bnd):
    acc = []
    for name in sorted((nod for nod in bnd if re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", nod)), key=lambda nod: int(re.search(r"(\d+)\.xml$", nod).group(1))):
        txt_src = bnd[name].decode("utf-8", "ignore") if isinstance(bnd[name], bytes) else bnd[name]
        ty, squash = re.search(r'<p:sldLayout\b[^>]*\btype="([^"]+)"', txt_src), re.search(r'<p:cSld\b[^>]*\bname="([^"]*)"', txt_src)
        ph = []
        for a1 in re.findall(r"<p:ph\b([^>]*?)/?>", txt_src):
            t1, i1 = re.search(r'type="([^"]+)"', a1), re.search(r'idx="(\d+)"', a1)
            ph.append((t1.group(1) if t1 else "body", i1.group(1) if i1 else None))
        acc.append({"part": name, "type": ty.group(1) if ty else "", "name": squash.group(1) if squash else "", "phs": ph})
    return acc
def assemble_deck(slides, acc, template=None):
    theme_hashes = master_hashes = None
    if template:
        with zipfile.ZipFile(template) as zin:
            bnd = {nod: zin.read(nod) for nod in zin.namelist() if not nod.endswith("/")}
        if "ppt/presentation.xml" not in bnd:
            raise ValueError("template lacks ppt/presentation.xml")
        theme_hashes = {nod: hashlib.sha256(bnd[nod]).hexdigest() for nod in bnd if re.match(r"ppt/theme/theme\d+\.xml$", nod)}
        master_hashes = {nod: hashlib.sha256(bnd[nod]).hexdigest() for nod in bnd if re.match(r"ppt/slideMasters/slideMaster\d+\.xml$", nod)}
        overrides = []
    else:
        bnd, overrides = builtin_package(), [("ppt/presentation.xml", MIME["pres"]), ("ppt/slideMasters/slideMaster1.xml", MIME["master"]), ("ppt/slideLayouts/slideLayout1.xml", MIME["layout"]), ("ppt/slideLayouts/slideLayout2.xml", MIME["layout"]), ("ppt/theme/theme1.xml", MIME["theme"]), ("ppt/notesMasters/notesMaster1.xml", MIME["nmaster"])]
    get = lambda ky: (bnd.get(ky) or b"").decode("utf-8", "ignore") if isinstance(bnd.get(ky), bytes) else (bnd.get(ky) or "")
    presentation, rel_map = get("ppt/presentation.xml"), load_rels(get("ppt/_rels/presentation.xml.rels"))
    mt = re.search(r'<p:sldSz\b[^>]*cx="(\d+)"[^>]*cy="(\d+)"', presentation)
    wd, ht = (int(mt.group(1)), int(mt.group(2))) if mt else DEFAULT_SIZE
    squash = next((seg.replace("../", "") for seg, ty in rel_map.values() if ty.endswith("/notesMaster")), None)
    squash = "ppt/" + squash if squash and not squash.startswith("ppt/") else squash
    squash = squash if squash and squash in bnd else None
    cts_text = get("[Content_Types].xml")
    dropped = 0
    if template:
        for prt in [q for q in bnd if re.match(r"ppt/(slides|notesSlides)/", q)]:
            cts_text = re.sub(r'<Override PartName="/%s"[^>]*/>' % re.escape(prt), "", cts_text)
            bnd.pop(prt, None)
            dropped += 1 if re.match(r"ppt/slides/slide\d+\.xml$", prt) else 0
    catalog = layout_catalog(bnd)
    title_lay = next((lay for lay in catalog if lay["type"] == "title"), None) or (catalog[0] if catalog else None)
    body_lay = next((lay for lay in catalog if lay["type"] in ("obj", "tx", "secHead")), None) or (catalog[-1] if catalog else title_lay)
    id_list, pres_rels = [], [(rid, ty, seg) for rid, (seg, ty) in rel_map.items() if not re.search(r"/(slide|notesSlide)$", ty)]
    for seq, txt_src in enumerate(slides):
        nod, ttl = seq + 1, txt_src.get("role") == "title"
        lay = title_lay if ttl else body_lay
        placeholders = (lay or {}).get("phs", [])
        title_ph = next((q for q in placeholders if q[0] in ("title", "ctrTitle")), None)
        body_ph = next((q for q in placeholders if q[0] in ("body", "obj", "subTitle", "tx")), None)
        rel_pairs = ([("rId1", NS_R + "/slideLayout", "../slideLayouts/" + Path(lay["part"]).name)] if lay else []) + ([("rId2", NS_R + "/notesSlide", "../notesSlides/notesSlide%d.xml" % nod)] if squash else [])
        bnd["ppt/slides/slide%d.xml" % nod] = slide_part(page_shapes(txt_src, wd, ht, title_ph, body_ph))
        bnd["ppt/slides/_rels/slide%d.xml.rels" % nod] = rels_part(rel_pairs)
        overrides.append(("ppt/slides/slide%d.xml" % nod, MIME["slide"]))
        pres_rels.append(("rIdS%d" % nod, NS_R + "/slide", "slides/slide%d.xml" % nod))
        id_list.append('<p:sldId id="%d" r:id="rIdS%d"/>' % (256 + seq, nod))
        if squash:
            bnd["ppt/notesSlides/notesSlide%d.xml" % nod] = notes_part(txt_src.get("notes"))
            bnd["ppt/notesSlides/_rels/notesSlide%d.xml.rels" % nod] = rels_part([("rId1", NS_R + "/slide", "../slides/slide%d.xml" % nod), ("rId2", NS_R + "/notesMaster", "../" + squash.replace("ppt/", ""))])
            overrides.append(("ppt/notesSlides/notesSlide%d.xml" % nod, MIME["notes"]))
            pres_rels.append(("rIdN%d" % nod, NS_R + "/notesSlide", "notesSlides/notesSlide%d.xml" % nod))
    lst = "<p:sldIdLst>%s</p:sldIdLst>" % "".join(id_list)
    presentation = re.sub(r"<p:sldIdLst>.*?</p:sldIdLst>", lst, presentation, flags=re.S) if "<p:sldIdLst>" in presentation else presentation.replace("</p:sldMasterIdLst>", "</p:sldMasterIdLst>" + lst)
    bnd["ppt/presentation.xml"] = presentation.encode("utf-8")
    bnd["ppt/_rels/presentation.xml.rels"] = rels_part(pres_rels).encode("utf-8")
    bnd["[Content_Types].xml"] = (cts_text.replace("</Types>", "".join('<Override PartName="/%s" ContentType="%s"/>' % fw for fw in overrides) + "</Types>") if "</Types>" in cts_text else contenttypes_part(overrides)).encode("utf-8")
    save_zip(acc, bnd)
    return {"engine": "stdlib-ooxml-template-surgery" if template else "stdlib-ooxml-minimal", "template": str(template) if template else None, "master": [Path(prt).name for prt in sorted(master_hashes)] if master_hashes else ["slideMaster1.xml"], "layout_names": sorted({(title_lay or {}).get("name", ""), (body_lay or {}).get("name", "")} - {""}),
            "layouts_used": sorted({Path((lay or {}).get("part", "")).name for lay in (title_lay, body_lay)} - {"."}),
            "theme_unchanged": (theme_hashes == {nod: hashlib.sha256(bnd[nod]).hexdigest() for nod in theme_hashes if nod in bnd}) if theme_hashes else None,
            "master_unchanged": (master_hashes == {nod: hashlib.sha256(bnd[nod]).hexdigest() for nod in master_hashes if nod in bnd}) if master_hashes else None,
            "sz": [wd, ht], "dropped_slides": dropped}
def deck_text_pages(pptx):
    """Collect the text runs of every slide in a built .pptx, slide order preserved."""
    try:
        with zipfile.ZipFile(pptx) as bnd:
            parts = sorted((nod for nod in bnd.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", nod)), key=lambda nod: int(re.search(r"(\d+)\.xml$", nod).group(1)))
            from html import unescape
            return [[unescape(run) for run in re.findall(r"<a:t>(.*?)</a:t>", bnd.read(nod).decode("utf-8", "ignore"), re.S)]
                    for nod in parts]
    except Exception:
        return []
def textlayer_pdf(pages, target):
    def clean(txt_src):
        return "".join(ch if 32 <= ord(ch) < 127 else ("?" if ord(ch) > 126 else " ") for ch in str(txt_src or ""))
    def literal(txt_src):
        return "(" + clean(txt_src).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"
    total, font_id = max(1, len(pages)), 3 + 2 * max(1, len(pages))
    objects = [(1, b"<< /Type /Catalog /Pages 2 0 R >>")]
    kids = b" ".join(b"%d 0 R" % (3 + 2 * seq) for seq in range(total))
    objects.append((2, b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % total))
    for seq in range(total):
        lines = [ln for ln in ((pages[seq] if seq < len(pages) else []) or []) if str(ln).strip()][:22] or [""]
        ops = ["BT", "/F1 18 Tf", "1 0 0 1 48 500 Tm", "22 TL", literal(lines[0]) + " Tj", "/F1 11 Tf", "16 TL"]
        for ln in lines[1:]:
            ops.extend(["T*", literal(ln[:120]) + " Tj"])
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1", "replace")
        objects.append((3 + 2 * seq, ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 720 540] " "/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>" % (font_id, 4 + 2 * seq)).encode("ascii")))
        objects.append((4 + 2 * seq, b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"))
    objects.append((font_id, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"))
    objects.sort()
    blob = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offset = {}
    for num, body in objects:
        offset[num] = len(blob)
        blob += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    xref_at, size = len(blob), max(offset) + 1
    blob += b"xref\n0 %d\n0000000000 65535 f \n" % size
    blob += b"".join(b"%010d 00000 n \n" % offset[nod] for nod in range(1, size))
    blob += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref_at)
    Path(target).write_bytes(bytes(blob))
    return {"pages": total, "bytes": len(blob)}
def render_preview_pdf(pptx, outdir, work=None, timeout=240):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    target = outdir / (Path(pptx).stem + ".pdf")
    tries = []
    office = shutil.which("soffice") or shutil.which("libreoffice")
    if office:
        try:
            subprocess.run([office, "-env:UserInstallation=file://%s" % (Path(work or outdir) / "_lo_profile"), "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(outdir), str(pptx)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            tries.append(["libreoffice", bool(target.exists())])
        except Exception:  # probing a toolchain must never abort the run
            tries.append(["libreoffice", "error"])
    res = shutil.which("office-renderer")
    if res and not target.exists():
        try:
            subprocess.run([res, str(pptx), str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            tries.append(["office-renderer", bool(target.exists())])
        except Exception:  # probing a toolchain must never abort the run
            tries.append(["office-renderer", "error"])
    if target.exists() and target.read_bytes()[:5] == b"%PDF-":
        return {"pdf": str(target), "engine": "libreoffice" if tries and tries[0][1] is True else (tries[-1][0] if tries else None), "tries": tries, "degraded": False}
    pages = deck_text_pages(pptx)
    if pages:
        try:
            wrote = textlayer_pdf(pages, target)
            tries.append(["stdlib-textlayer", wrote["pages"]])
            return {"pdf": str(target), "engine": "stdlib-textlayer", "tries": tries, "degraded": True}
        except Exception:
            tries.append(["stdlib-textlayer", "error"])
    return {"pdf": None, "engine": None, "tries": tries, "degraded": True}
def read_paper(path):
    payload, pages, eng, suf = "", [], "none", path.suffix.lower()
    if suf == ".pdf":
        try:
            res = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            if res.stdout and len(res.stdout.strip()) > 200:
                payload, eng = res.stdout.decode("utf-8", "ignore"), "pdftotext"
        except Exception:
            pass
        if not payload:
            raw = []
            for mt in re.finditer(rb"stream\r?\n(.*?)endstream", path.read_bytes(), re.S):
                try:
                    fy = zlib.decompress(mt.group(1))
                except Exception:
                    continue
                if b"Tj" in fy or b"TJ" in fy:
                    raw += [seg[1:-1].decode("latin-1", "ignore") for seg in re.findall(rb"\((?:\\\\.|[^\\\\()])*\)", fy)]
            payload, eng = " ".join(raw), ("stdlib-inflate" if len(" ".join(raw).strip()) > 100 else "none")
        pages = pages or payload.split("\f")
    elif suf in (".docx", ".pptx"):
        with zipfile.ZipFile(path) as bnd:
            qs = [q for q in bnd.namelist() if re.match(r"word/document\.xml$|ppt/slides/slide\d+\.xml$", q)]
            payload = re.sub(r"\s+", " ", " ".join(re.sub(r"<[^>]+>", " ", bnd.read(q).decode("utf-8", "ignore")) for q in qs))
        pages, eng = [payload], suf[1:]
    else:
        payload = path.read_text(encoding="utf-8", errors="ignore")
        pages, eng = payload.split("\f"), (suf[1:] or "txt")
    lay = [l.strip() for l in (pages[0] if pages else "").split("\n") if l.strip()][:8]
    meta = {"title": next((l for l in lay[:5] if 25 <= len(l) <= 190 and not re.search(r"@|doi|http|arxiv|copyright|漏", l, re.I)), ""), "byline": [l for l in lay[1:6] if re.search(r"[A-Z][a-z]+ [A-Z]", l) and len(l) < 160][:2], "stem": path.stem}
    return {"text": squash(payload), "pages": pages or [payload], "engine": eng, "meta": meta}
def inspect_deck(path, expect=None):
    import xml.etree.ElementTree as ET
    rep = {"path": str(path), "ok": False, "members": 0, "slides": 0, "notes": 0, "issues": []}
    try:
        bnd = zipfile.ZipFile(path)
    except Exception as err:  # noqa: BLE001
        rep["issues"].append("not a zip: %s" % err)
        return rep
    member_names = bnd.namelist()
    rep["members"] = len(member_names)
    rep["issues"] += ["missing " + nod for nod in ("[Content_Types].xml", "ppt/presentation.xml") if nod not in member_names]
    sl = sorted(nod for nod in member_names if re.match(r"ppt/slides/slide\d+\.xml$", nod))
    rep["slides"] = len(sl)
    rep["notes"] = len([nod for nod in member_names if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", nod)])
    for nod in sl:
        try:
            ET.fromstring(bnd.read(nod))
        except Exception as err:  # noqa: BLE001
            rep["issues"].append("bad xml %s: %s" % (nod, err))
    if expect and rep["slides"] != expect:
        rep["issues"].append("slide count %d != expected %d" % (rep["slides"], expect))
    rep["ok"] = not rep["issues"]
    return rep
def inspect_pdf(path):
    try:
        fy = Path(path).read_bytes()
    except Exception:
        return {"path": str(path), "ok": False, "pages": 0}
    nod = len(re.findall(rb"/Type\s*/Page[^s]", fy))
    return {"path": str(path), "ok": fy[:5] == b"%PDF-" and nod > 0, "pages": nod}
