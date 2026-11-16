"""绘制与导出：显示列表 -> 分层 SVG / 单页 PDF + PDF 探针。同一份图元喂两个序列化器，
可编辑源与导出件在几何上必然一致；文字仍是 <text>，改一个标签就能重导。"""
import re
import zlib

from figure_engine import *          # noqa: F401,F403  （常量 + 量度 + 布局）
from figure_engine import W, H, PAD, MIN_PX, FONT_STACK, KIND, EDGE, LANE_LABEL, FOOT_Y
from figure_engine import LEGEND_Y, LEGEND_H, NODE_L, NODE_R, adv, fold, flat, sid, arrange


# ------------------------------------------------------------------ 图元（显示列表）

def p_rect(L, layer, grp, x, y, w, h, rx, fill, stroke=None, sw=1.0):
    L.append({"op": "rect", "layer": layer, "grp": grp, "x": x, "y": y, "w": w, "h": h,
              "rx": rx, "fill": fill, "stroke": stroke, "sw": sw})


def p_line(L, layer, grp, pts, stroke, sw, dash=None):
    L.append({"op": "line", "layer": layer, "grp": grp, "pts": [list(p) for p in pts],
              "stroke": stroke, "sw": sw, "dash": dash})


def p_poly(L, layer, grp, pts, fill):
    L.append({"op": "poly", "layer": layer, "grp": grp, "pts": [list(p) for p in pts], "fill": fill})


def p_dot(L, layer, grp, cx, cy, r, fill, stroke=None, sw=1.0):
    L.append({"op": "dot", "layer": layer, "grp": grp, "cx": cx, "cy": cy, "r": r,
              "fill": fill, "stroke": stroke, "sw": sw})


def p_text(L, layer, grp, x, y, s, size, anchor, fill, bold=False, italic=False):
    L.append({"op": "text", "layer": layer, "grp": grp, "x": x, "y": y, "s": str(s),
              "size": size, "anchor": anchor, "fill": fill, "bold": bold, "italic": italic})


def _unit(x1, y1, x2, y2):
    n = math.hypot(x2 - x1, y2 - y1) or 1.0
    return (x2 - x1) / n, (y2 - y1) / n


def _mid(pts):
    best, seg = -1.0, (pts[0], pts[-1])
    for a, b in zip(pts, pts[1:]):
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) > best:
            best, seg = abs(a[0] - b[0]) + abs(a[1] - b[1]), (a, b)
    return (seg[0][0] + seg[1][0]) / 2.0, (seg[0][1] + seg[1][1]) / 2.0


def leader(L, layer, grp, pts, kind, label="", badge="", fs=MIN_PX, direction="forward"):
    """线型 + 端点形状就是语义：实心箭头=激活，T 端=抑制，空心=接触，双头=转运，无头=缺方向。"""
    colour, dash, head, sw = EDGE.get(kind, EDGE["unspecified"])[:4]
    if direction == "undirected":
        head = "none"
    p_line(L, layer, grp, pts, colour, sw, dash)
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    ux, uy = _unit(x1, y1, x2, y2)
    px, py = -uy, ux

    def tri(x, y, vx, vy):
        p_poly(L, layer, grp, [(x, y), (x - vx * 12 + px * 5.4, y - vy * 12 + py * 5.4),
                               (x - vx * 12 - px * 5.4, y - vy * 12 - py * 5.4)], colour)

    if head == "solid":
        tri(x2, y2, ux, uy)
    elif head == "open":
        bx, by = x2 - ux * 12, y2 - uy * 12
        p_line(L, layer, grp, [(bx + px * 5.4, by + py * 5.4), (x2, y2),
                               (bx - px * 5.4, by - py * 5.4)], colour, 1.6)
    elif head == "bar":
        p_line(L, layer, grp, [(x2 - px * 9, y2 - py * 9), (x2 + px * 9, y2 + py * 9)], colour, 3.0)
    elif head == "double":
        tri(x2, y2, ux, uy)
        sx, sy = pts[0]
        vx, vy = _unit(pts[1][0], pts[1][1], sx, sy)
        p_poly(L, layer, grp, [(sx, sy), (sx - vx * 11 - vy * 4.6, sy - vy * 11 + vx * 4.6),
                               (sx - vx * 11 + vy * 4.6, sy - vy * 11 - vx * 4.6)], colour)
    if badge:
        p_text(L, layer, grp, x2 - ux * 20 + px * 13, y2 - uy * 20 + py * 13 + 5, badge, fs,
               "middle", colour, True)
    if label:
        mx, my = _mid(pts)
        p_text(L, layer, grp, mx, my - 7, label, fs, "middle", colour)


def compose(p, meta=None):
    """plan -> (显示列表, 宽, 高, 统计)。层顺序固定，任何 plan 都一样。"""
    meta = meta or {}
    L = []
    lo = arrange(p)
    zbox, pos = lo["zbox"], lo["pos"]
    lanes_of = lo["lane_of"]
    stats = {"entities": len(p["entities"]), "relations": len(p["relations"]),
             "crossings": lo["crossings"], "hits": lo["hits"], "order_choice": lo.get("order_choice", "-"),
             "tight": lo["tight"], "overflow": [], "min_font": MIN_PX,
             "lanes": len(lo["lanes"]),
             "zones": [{"id": z[0], "y": z[1], "h": z[2]} for z in zbox],
             "boxes": {}, "lanes_of": dict(lanes_of), "membrane_y": None,
             "unplaced": [e["id"] for e in p["entities"] if e["id"] not in pos]}
    p_rect(L, "background", None, 0, 0, W, H, 0, "#ffffff")
    for i, ln in enumerate(fold(p["title"] or "Biological mechanism figure",
                                W - 2 * PAD, 26, True, 2)):
        p_text(L, "title", None, PAD, 40 + 26 * i, ln, 26, "start", "#132433", True)
    sub = p["subtitle"] or meta.get("byline", "")
    if sub:
        p_text(L, "title", None, PAD, 88, fold(sub, W - 2 * PAD, MIN_PX, False, 1)[0], MIN_PX,
               "start", "#4a5b6b")

    for bi, (zid, y, h) in enumerate(zbox):
        grp = ("zone-%s" % sid(zid), {"data-zone": zid, "data-order": str(bi)})
        p_rect(L, "zones", grp, PAD, y, W - 2 * PAD, h, 6,
               "#f7fafc" if bi % 2 == 0 else "#fdfefe", "#c9d6e3", 1.0)
        zh, en = LANE_LABEL.get(zid, (zid, ""))
        lg = ("zone-%s-label" % sid(zid), {"data-zone": zid})
        p_text(L, "zones", lg, PAD + 14, y + h / 2.0 - 2, zh, 16, "start", "#20364a", True)
        p_text(L, "zones", lg, PAD + 14, y + h / 2.0 + 16,
               (en[:20] + "…") if len(en) > 20 else (en or zid), MIN_PX, "start", "#5d7183")
        if zid == "mem":
            cy = y + h / 2.0
            for off in (-9.0, 9.0):
                p_line(L, "zones", lg, [(NODE_L - 96, cy + off), (NODE_R + 6, cy + off)],
                       "#c2ae95", 2.0)
            x = NODE_L - 96
            while x <= NODE_R:
                for off in (-9.0, 9.0):
                    p_dot(L, "zones", lg, x, cy + off, 3.0, "#e5d9c6", "#c2ae95", 0.9)
                x += 26.0
            stats["membrane_y"] = cy

    for e in p["entities"]:
        eid = e["id"]
        if eid not in pos:
            continue
        x, y, w, h = pos[eid]
        ev = e.get("evidence") or {}
        status = e.get("evidence_status") or (
            "verbatim" if ev.get("verified_locator") else
            ("declared" if ev.get("declared_locator") else
             ("unverified" if ev.get("quote") else "none")))
        attrs = {"data-kind": e["kind"], "data-zone": lanes_of.get(eid, ""),
                 "data-quote": ev.get("quote") or "",
                 "data-locator": ev.get("verified_locator") or ev.get("locator") or "",
                 "data-quote-status": status,
                 "data-italic": "true" if e["italic"] else "false"}
        if e["species"]:
            attrs["data-species"] = e["species"]
        grp = ("ent-%s" % sid(eid), attrs)
        p_rect(L, "entities", grp, x, y, w, h, 16 if e["kind"] == "complex" else 9,
               KIND.get(e["kind"], KIND["unspecified"])[0], "#33475b",
               1.5 if e["kind"] == "complex" else 1.2)
        if e["kind"] == "complex":
            p_rect(L, "entities", grp, x + 4, y + 4, w - 8, h - 8, 12, "none", "#33475b", 0.8)
        stats["boxes"][eid] = [round(v, 2) for v in (x, y, w, h)]
        maxw = w - 20
        lines = fold(e["label"], maxw, 15, True, 3)
        subs = fold(e["sublabel"], maxw, MIN_PX, False, 2) if (e["sublabel"] and h >= 52) else []
        need = len(lines) * 18 + len(subs) * 16
        while need > h - 10 and len(lines) > 1:
            lines, need = lines[:-1], (len(lines) - 1) * 18 + len(subs) * 16
            lines[-1] = lines[-1] + "…"
        if need > h - 10 and subs:
            subs, need = [], len(lines) * 18
        ty0 = y + (h - need) / 2.0 + 15
        for i, ln in enumerate(lines):
            p_text(L, "entities", grp, x + w / 2.0, ty0 + i * 18, ln, 15, "middle", "#152535",
                   True, e["italic"])
        for i, ln in enumerate(subs):
            p_text(L, "entities", grp, x + w / 2.0, ty0 + len(lines) * 18 + i * 16, ln, MIN_PX,
                   "middle", "#54687a")
        enc = e.get("encoding")
        tag = flat(enc.get("label") or enc.get("value")) if isinstance(enc, dict) else flat(enc)
        if tag:
            p_text(L, "entities", grp, x + 8, y + 17, tag, MIN_PX, "start", "#1f3b57", True)
        for ln in lines + subs:
            size = 15 if ln in lines else MIN_PX
            if adv(ln, size, ln in lines) > maxw + 1:
                stats["overflow"].append({"entity": eid, "text": ln,
                                          "width_px": round(adv(ln, size), 1),
                                          "box_px": round(maxw, 1)})

    routed = []
    for r, pts in lo["routes"]:
        ev = r.get("evidence") or {}
        status = r.get("evidence_status") or (
            "verbatim" if ev.get("verified_locator") else
            ("declared" if ev.get("declared_locator") else "none"))
        attrs = {"data-type": r["type"], "data-direction": r["direction"],
                 "data-quote": ev.get("quote") or "",
                 "data-locator": ev.get("verified_locator") or ev.get("locator") or "",
                 "data-quote-status": status, "data-from": r["source"], "data-to": r["target"]}
        head = EDGE.get(r["type"], EDGE["unspecified"])[4]
        leader(L, "relations", ("rel-%s" % sid(r["id"]), attrs), pts, r["type"],
               r.get("label") or "", r.get("badge") or head, MIN_PX, r["direction"])
        routed.append({"id": r["id"], "source": r["source"], "target": r["target"],
                       "type": r["type"], "direction": r["direction"],
                       "from_lane": lanes_of.get(r["source"]), "to_lane": lanes_of.get(r["target"]),
                       "pts": [[round(px, 1), round(py, 1)] for px, py in pts]})
    stats["routes"] = routed

    kinds, types = [], []
    for e in p["entities"]:
        if e["kind"] not in kinds:
            kinds.append(e["kind"])
    for r in p["relations"]:
        if r["type"] not in types:
            types.append(r["type"])
    stats["kinds"], stats["types"] = kinds, types

    p_rect(L, "legend", ("legend", {"data-roles": "entity-kind,relation-type"}),
           PAD, LEGEND_Y, W - 2 * PAD, LEGEND_H, 8, "#fcfdfe", "#b9c8d6", 1.0)
    p_text(L, "legend", None, PAD + 16, LEGEND_Y + 24, "图例 Legend", 16, "start", "#132433", True)
    gx = PAD + 186
    p_text(L, "legend", None, PAD + 16, LEGEND_Y + 50, "实体种类 Kind", MIN_PX, "start",
           "#4a5b6b", True)
    per = max(1, int((W - PAD - 16 - gx) // 214))
    for i, k in enumerate(kinds):
        cx = gx + (i % per) * ((W - PAD - 16 - gx) / per)
        cy = LEGEND_Y + 50 + (i // per) * 26
        gid = "lg-%s" % sid(k)
        p_rect(L, "legend", (gid, {"data-kind": k}), cx, cy - 13, 26, 18, 4,
               KIND.get(k, KIND["unspecified"])[0], "#33475b", 1.2)
        p_text(L, "legend", (gid, {}), cx + 34, cy, KIND.get(k, KIND["unspecified"])[1], MIN_PX,
               "start", "#152535")
    ky = LEGEND_Y + 50 + (int(math.ceil(len(kinds) / float(per))) if kinds else 0) * 26 + 12
    p_text(L, "legend", None, PAD + 16, ky, "关系语义 Relation", MIN_PX, "start", "#4a5b6b", True)
    tper = max(1, int((W - PAD - 16 - gx) // 330))
    for i, t in enumerate(types):
        cx = gx + (i % tper) * ((W - PAD - 16 - gx) / tper)
        cy = ky + (i // tper) * 26
        gid = "lg-%s" % sid(t)
        leader(L, "legend", (gid, {"data-type": t}), [(cx, cy - 5), (cx + 56, cy - 5)], t)
        p_text(L, "legend", (gid, {}), cx + 66, cy, EDGE.get(t, EDGE["unspecified"])[5], MIN_PX,
               "start", "#152535")
    p_text(L, "legend", None, PAD + 16, LEGEND_Y + LEGEND_H - 12,
           "图例由画面实际出现的种类与关系类型自动生成，每项都能回查到数据来源。", MIN_PX,
           "start", "#5d7183")

    p_text(L, "notes", None, PAD, FOOT_Y[0],
           fold("方向 = 上游→下游；虚线 = 间接或推测；点划线 = 原文未说明类型/方向。",
                (W - 2 * PAD) * 0.7, MIN_PX, False, 1)[0], MIN_PX, "start", "#33475b")
    p_text(L, "notes", None, PAD, FOOT_Y[1],
           fold("Direction = upstream to downstream; dashed = indirect or inferred; dash-dot = "
                "type or direction not stated in the source.",
                (W - 2 * PAD) * 0.8, MIN_PX, False, 1)[0], MIN_PX, "start", "#33475b")
    p_text(L, "notes", None, PAD, FOOT_Y[2],
           fold(meta.get("footer", ""), W - 2 * PAD, MIN_PX, False, 1)[0], MIN_PX, "start",
           "#8896a4")
    stats["items"] = len(L)
    return L, W, H, stats

def _hex_rgb(h):
    h = (h or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except Exception:
        return (0.0, 0.0, 0.0)


def _pdf_rgb(h):
    r, g, b = _hex_rgb(h)
    return "%.2f %.2f %.2f" % (r, g, b)


def emit(items, width=W, height=H, meta=None):
    """一遍走完显示列表 -> (SVG 文本, PDF 字节, 因 WinAnsi 丢掉的字符数)。"""
    meta = meta or {}
    k = 0.75                      # 1px = 0.75pt -> 1200 x 750 pt
    pw, ph = width * k, height * k
    lost = [0]

    def num(v):
        s = "%.2f" % v
        return s.rstrip("0").rstrip(".") if "." in s else s

    def xml(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))

    def pdf_str(s):
        keep = []
        for ch in str(s):
            try:
                ch.encode("latin-1")
                keep.append(ch)
            except UnicodeEncodeError:
                lost[0] += 1
        return "".join(keep).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    svg = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
           'font-family="%s" version="1.1">' % (int(width), int(height), int(width), int(height),
                                               FONT_STACK),
           "<title>%s</title>" % xml(meta.get("title", "mechanism figure")),
           "<desc>%s</desc>" % xml(meta.get("desc", "biological mechanism / pathway figure")),
           "<metadata>pathway-mechanism-drawer v1; entity/relation groups carry data-quote and "
           "data-locator; labels stay as &lt;text&gt; so a reviewer can retype one and re-export."
           "</metadata>"]
    ops = []
    cur_layer, cur_group = None, None
    flip = lambda v: ph - v * k
    for it in items:
        layer = it.get("layer")
        if layer != cur_layer:
            if cur_group:
                svg.append("</g>")
                cur_group = None
            if cur_layer:
                svg.append("</g>")
            svg.append('<g id="layer-%s">' % layer)
            cur_layer = layer
        grp = it.get("grp")
        gid = grp[0] if isinstance(grp, tuple) else None
        if gid != cur_group:
            if cur_group:
                svg.append("</g>")
            cur_group = gid
            if gid:
                svg.append('<g id="%s"%s>' % (gid, "".join(
                    ' %s="%s"' % (a, xml(b)) for a, b in sorted((grp[1] or {}).items()))))
        op = it.get("op")
        if op == "rect":
            if it.get("fill") == "none" and not it.get("stroke"):
                continue
            svg.append('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s"%s/>' % (
                num(it["x"]), num(it["y"]), num(it["w"]), num(it["h"]), num(it["rx"]), it["fill"],
                ' stroke="%s" stroke-width="%s"' % (it["stroke"], num(it["sw"]))
                if it.get("stroke") else ""))
            box = "%s %s %s %s re" % (num(it["x"] * k), num(flip(it["y"] + it["h"])),
                                      num(it["w"] * k), num(it["h"] * k))
            if it.get("fill") and it["fill"] != "none":
                ops.append("%s rg %s f" % (_pdf_rgb(it["fill"]), box))
            if it.get("stroke"):
                ops.append("%s RG %s w %s S" % (_pdf_rgb(it["stroke"]), num(it["sw"] * k), box))
        elif op == "line":
            pts = it["pts"]
            svg.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s"%s '
                       'stroke-linejoin="round" stroke-linecap="round"/>' % (
                           " ".join("%s,%s" % (num(p[0]), num(p[1])) for p in pts), it["stroke"],
                           num(it["sw"]),
                           ' stroke-dasharray="%s"' % it["dash"] if it.get("dash") else ""))
            ops.append("%s RG %s w 1 J 1 j %s %s S" % (
                _pdf_rgb(it["stroke"]), num(it["sw"] * k),
                "[%s] 0 d" % " ".join(num(float(v) * k) for v in it["dash"].split(","))
                if it.get("dash") else "[] 0 d",
                " ".join("%s %s %s" % (num(p[0] * k), num(flip(p[1])), "m" if i == 0 else "l")
                         for i, p in enumerate(pts))))
        elif op == "poly":
            pts = it["pts"]
            svg.append('<polygon points="%s" fill="%s"/>' % (
                " ".join("%s,%s" % (num(p[0]), num(p[1])) for p in pts), it["fill"]))
            ops.append("%s rg %s h f" % (_pdf_rgb(it["fill"]), " ".join(
                "%s %s %s" % (num(p[0] * k), num(flip(p[1])), "m" if i == 0 else "l")
                for i, p in enumerate(pts))))
        elif op == "dot":
            svg.append('<circle cx="%s" cy="%s" r="%s" fill="%s"%s/>' % (
                num(it["cx"]), num(it["cy"]), num(it["r"]), it["fill"],
                ' stroke="%s" stroke-width="%s"' % (it["stroke"], num(it["sw"]))
                if it.get("stroke") else ""))
            r, g, b = _hex_rgb(it["fill"])
            cx, cy, rr = it["cx"], it["cy"], it["r"]
            q = 0.5523 * rr
            ops.append(("%s %s %s rg %s %s m " + " ".join(["%s %s %s %s %s %s c"] * 4) + " f") % (
                num(r), num(g), num(b), num((cx + rr) * k), num(flip(cy)),
                num((cx + rr) * k), num(flip(cy + q)), num((cx + q) * k), num(flip(cy + rr)),
                num(cx * k), num(flip(cy + rr)),
                num((cx - q) * k), num(flip(cy + rr)), num((cx - rr) * k), num(flip(cy + q)),
                num((cx - rr) * k), num(flip(cy)),
                num((cx - rr) * k), num(flip(cy - q)), num((cx - q) * k), num(flip(cy - rr)),
                num(cx * k), num(flip(cy - rr)),
                num((cx + q) * k), num(flip(cy - rr)), num((cx + rr) * k), num(flip(cy - q)),
                num((cx + rr) * k), num(flip(cy))))
        else:
            body = "".join(c for c in str(it["s"]) if c != "\n")
            style = (' font-weight="bold"' if it.get("bold") else "") + \
                    (' font-style="italic"' if it.get("italic") else "")
            svg.append('<text x="%s" y="%s" font-size="%s" text-anchor="%s" fill="%s"%s>%s</text>'
                       % (num(it["x"]), num(it["y"]), num(it["size"]), it["anchor"], it["fill"],
                          style, xml(body)))
            enc = pdf_str(body)
            if enc.strip():
                wpx = adv(body, it["size"], it.get("bold")) * k
                tx = it["x"] * k - wpx * (0.5 if it["anchor"] == "middle"
                                          else (1.0 if it["anchor"] == "end" else 0.0))
                face = "F2" if it.get("bold") else ("F3" if it.get("italic") else "F1")
                ops.append("BT /%s %s Tf %s rg %s %s Td (%s) Tj ET" % (
                    face, num(it["size"] * k), _pdf_rgb(it["fill"]), num(tx),
                    num(flip(it["y"])), enc))
    svg += (["</g>"] if cur_group else []) + (["</g>"] if cur_layer else []) + ["</svg>"]
    stream = zlib.compress("\n".join(ops).encode("latin-1", "replace"), 9)
    info = "<< /Title (%s) /Producer (pathway-mechanism-drawer, python stdlib) >>" % pdf_str(
        meta.get("title", ""))
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %s %s] /Resources << /Font << /F1 5 0 R "
             "/F2 6 0 R /F3 7 0 R >> >> /Contents 4 0 R >>" % (num(pw), num(ph))).encode(),
            b"<< /Length " + str(len(stream)).encode() + b" /Filter /FlateDecode >>\nstream\n" +
            stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique "
            b"/Encoding /WinAnsiEncoding >>",
            info.encode("latin-1", "replace")]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offs = []
    for i, blob in enumerate(objs, 1):
        offs.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + blob + b"\nendobj\n"
    xref = len(out)
    out += ("xref\n0 %d\n" % (len(objs) + 1)).encode() + b"0000000000 65535 f \n"
    for o in offs:
        out += ("%010d 00000 n \n" % o).encode()
    out += ("trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, len(objs), xref)).encode()
    return "\n".join(svg) + "\n", bytes(out), lost[0]


def probe_pdf(data):
    """读回我们自己写的 PDF：文件头、页数、EOF、xref 偏移、以及显示文字算符数量。"""
    out = {"header": data[:8].decode("latin-1", "replace"),
           "pages": data.count(b"/Type /Page") - data.count(b"/Type /Pages"),
           "eof": data.rstrip().endswith(b"%%EOF"), "tj": 0, "xref_ok": False}
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            out["tj"] += zlib.decompress(m.group(1)).count(b"Tj")
        except Exception:
            out["tj"] += m.group(1).count(b"Tj")
    m = re.search(rb"startxref\s+(\d+)", data)
    if m:
        off = int(m.group(1))
        out["xref_ok"] = data[off:off + 4] == b"xref"
        if out["xref_ok"]:
            rows = re.findall(r"(\d{10}) (\d{5}) ([nf])",
                              data[off:off + 4096].decode("latin-1", "replace"))
            ok = True
            for i, (o, _g, f) in enumerate(rows[1:], 1):
                if f == "n":
                    ok = ok and bool(re.match(rb"%d\s+0\s+obj" % i, data[int(o):int(o) + 24]))
            out["xref_ok"] = ok and len(rows) > 2
    return out


def relay(plan, meta=None):
    """plan -> {items_list, svg, pdf, ...stats}。plan 再怪也不抛异常给上层。"""
    p = coerce(plan)
    items, width, height, stats = compose(p, meta)
    stats["svg"], stats["pdf"], stats["pdf_chars_lost"] = emit(items, width, height, meta)
    stats.update({"width": width, "height": height, "items_list": items, "plan": p})
    return stats


if __name__ == "__main__":
    import sys
    if "--help" in sys.argv or "-h" in sys.argv:
        print("figure_paint.py - 显示列表 -> 分层 SVG + 单页矢量 PDF；relay(plan) 是库入口。")
        sys.exit(0)
    demo = {"title": "paint selftest", "entities": [
        {"id": "A", "label": "AKT1", "kind": "gene", "compartment": "cytoplasm"},
        {"id": "B", "label": "p-AKT", "kind": "protein", "compartment": "cytoplasm"}],
        "relations": [{"id": "r1", "source": "A", "target": "B", "type": "activation"}]}
    st = relay(demo)
    print("items=%d svg=%dB pdf=%dB crossings=%s hits=%s pdfprobe=%s"
          % (len(st["items_list"]), len(st["svg"]), len(st["pdf"]), st["crossings"],
             st["hits"], probe_pdf(st["pdf"])))
    sys.exit(0)
