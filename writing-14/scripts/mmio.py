#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mmio.py — 材料读入与产物渲染。

上半段：把 /input 里的各种格式读成带 locator 的单元，并建索引；
下半段：同一份布局几何既出可编辑 SVG 也出位图预览，故两侧结构必然一致。
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import zipfile
import zlib
from pathlib import Path

import mmcore

IN = Path(os.environ.get("BOHR_INPUT_DIR") or "/input")
WK = Path(os.environ.get("BOHR_WORK_DIR") or "/app/work")
OUT = Path(os.environ.get("BOHR_OUTPUT_DIR") or "/app/output")
SKILL_ID = "mindmap-evidence-forge/1.1.0"
TEXT_CAP = 600_000

KIND = {".pdf": "pdf", ".docx": "docx", ".md": "text", ".txt": "text", ".tex": "text",
        ".json": "json", ".csv": "csv", ".tsv": "tsv", ".yaml": "text", ".yml": "text",
        ".xml": "text", ".html": "text", ".htm": "text", ".bib": "text", ".rtf": "text",
        ".xlsx": "sheet", ".pptx": "slides", ".png": "image", ".jpg": "image",
        ".jpeg": "image", ".gif": "image", ".bmp": "image", ".tif": "image", ".tiff": "image",
        ".webp": "image", ".svg": "svg"}
SKIP = {".py", ".pyc", ".zip", ".gz", ".tar", ".so", ".exe", ".sh", ".js", ".css"}
ROLES = {"mindmap.svg": "主产物：可编辑导图", "mindmap.json": "结构真源与证据",
         "mindmap_preview.png": "预览位图", "node_evidence.csv": "节点→locator/quote",
         "coverage_report.md": "覆盖与结构说明", "pending_human.json": "待人工确认",
         "golden_standard.json": "金标准与出处", "audit_report.json": "对照与自检"}


# ---------------------------------------------------------------- 基础 IO
def ensure(path):
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def decode(raw):
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return raw.decode(encoding)
        except Exception:
            pass
    return raw.decode("utf-8", "replace")


def paragraphs(text):
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for block in re.split(r"\n\s*\n", body):
        block = re.sub(r"[ \t]+", " ", block).strip()
        if len(block) >= 2:
            out.append(block)
    return out


def sniff(path, guess):
    """扩展名 + 魔数双识别：不轻信后缀。"""
    try:
        head = path.open("rb").read(16)
    except Exception:
        head = b""
    if head.startswith(b"%PDF"):
        return "pdf"
    if head[:8] == b"\x89PNG\r\n\x1a\n" or head[:3] == b"\xff\xd8\xff" or head[:4] in (b"GIF8", b"II*\x00"):
        return "image"
    if head[:4] == b"PK\x03\x04":
        try:
            names = zipfile.ZipFile(path).namelist()
        except Exception:
            return "zip"
        for member, kind in (("word/document.xml", "docx"), ("xl/workbook.xml", "sheet"),
                             ("ppt/presentation.xml", "slides")):
            if member in names:
                return kind
        return "zip"
    if head[:1] in (b"{", b"["):
        return "json"
    if guess in ("pdf", "docx", "sheet", "slides", "json"):
        return guess
    return guess or "text"


# ---------------------------------------------------------------- 抽取
def pdf_units(path):
    exe = shutil.which("pdftotext")
    if exe:
        try:
            proc = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(path), "-"],
                                  capture_output=True, timeout=150)
            text = proc.stdout.decode("utf-8", "replace")
        except Exception:
            text = ""
        if text.strip():
            rows = []
            for page, chunk in enumerate(text.split("\f"), 1):
                for no, para in enumerate(paragraphs(chunk), 1):
                    rows.append({"locator": "p.%d¶%d" % (page, no), "text": para})
            return rows, "pdftotext"
    rows = []
    try:
        raw = path.read_bytes()
    except Exception:
        return rows, "读取失败"
    for index, match in enumerate(re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S), 1):
        try:
            blob = zlib.decompress(match.group(1))
        except Exception:
            continue
        if b"Tj" not in blob and b"TJ" not in blob:
            continue
        pieces = [re.sub(rb"\\([()\\])", rb"\1", tok.group(0)[1:-1]).decode("latin-1", "replace")
                  for tok in re.finditer(rb"\((?:\\\\.|[^\\()])*\)", blob)]
        text = " ".join(pieces).strip()
        if len(text) > 20:
            rows.append({"locator": "stream%d" % index, "text": text[:4000]})
    return rows, "raw-stream(页码为估计值)"


def docx_units(path):
    try:
        xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return []
    import html as htmllib
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n\n", xml)))
    return [{"locator": "¶%d" % i, "text": para} for i, para in enumerate(paragraphs(text), 1)]


def json_units(payload):
    rows = []

    def walk(obj, pointer, depth=0):
        if len(rows) >= 300 or depth > 8:
            return
        if isinstance(obj, dict):
            for key, value in obj.items():
                walk(value, pointer + "/" + str(key).replace("~", "~0").replace("/", "~1"), depth + 1)
        elif isinstance(obj, list):
            for i, value in enumerate(obj[:80]):
                walk(value, "%s/%d" % (pointer, i), depth + 1)
        else:
            text = str(obj).strip()
            if text and text.lower() not in ("none", "null", "nan"):
                rows.append({"locator": "json:" + (pointer or "/"), "text": text[:500]})

    walk(payload, "")
    return rows


def extract(path, kind):
    try:
        if kind == "pdf":
            return pdf_units(path)
        if kind == "docx":
            return docx_units(path), "zip-xml"
        if kind == "json":
            return json_units(mmcore.read_json(path, {}) or {}), "json-pointer"
        if kind in ("csv", "tsv"):
            raw = decode(path.read_bytes()) if path.stat().st_size < 4_000_000 else ""
            sep = "\t" if kind == "tsv" else ","
            rows = [line for line in raw.splitlines() if line.strip()][:800]
            return ([{"locator": "row%d" % i, "text": " | ".join(c.strip() for c in line.split(sep))}
                     for i, line in enumerate(rows, 1)], "lines")
        if kind in ("text", "svg"):
            raw = decode(path.read_bytes()) if path.stat().st_size < 4_000_000 else ""
            return [{"locator": "¶%d" % i, "text": para} for i, para in enumerate(paragraphs(raw), 1)], "text"
    except Exception as exc:
        return [], "failed: %s" % str(exc)[:80]
    return [], "未支持格式(%s)" % kind


def title_of(units, stem):
    for unit in units[:3]:
        text = unit["text"].strip()
        m = re.search(r"^#{1,4}\s*(.{3,90})", text)
        if m:
            return m.group(1).strip()
        line = text.split("\n")[0].strip()
        if 4 <= len(line) <= 100:
            return line
    return stem


# ---------------------------------------------------------------- 索引与输入
def find_case():
    candidates = []
    if IN.is_dir():
        if (IN / "case.json").is_file():
            candidates.append(IN / "case.json")
        candidates += [p for p in sorted(IN.rglob("*.json"))
                       if p.name.lower().startswith("case") and p not in candidates]
    for path in candidates:
        payload = mmcore.read_json(path)
        if isinstance(payload, dict):
            return payload, path
    return {}, (candidates[0] if candidates else None)


def semantic(case, pattern, default=None):
    for key, value in (case or {}).items():
        if isinstance(value, (dict, list, str)) and re.search(pattern, str(key), re.I):
            return value
    return default


def material_files(skip_path=None):
    rows = []
    if not IN.is_dir():
        return rows
    skip = str(Path(skip_path).resolve()) if skip_path else None
    for path in sorted(IN.rglob("*")):
        if not path.is_file() or path.name.startswith(".") or path.suffix.lower() in SKIP:
            continue
        if skip and str(path.resolve()) == skip:
            continue
        rows.append(path)
    return rows


def build_index(case, contract, case_path):
    materials, total = [], 0
    for no, path in enumerate(material_files(case_path), 1):
        try:
            size = path.stat().st_size
        except Exception:
            size = 0
        kind = sniff(path, KIND.get(path.suffix.lower(), ""))
        try:
            digest = hashlib.sha1(path.read_bytes()[:2_000_000]).hexdigest()[:12]
        except Exception:
            digest = None
        units, how = [], "skipped(%s)" % kind
        if kind in ("pdf", "docx", "json", "csv", "tsv", "text", "svg"):
            units, how = extract(path, kind)
        kept, chars = [], 0
        for unit in units:
            length = len(unit.get("text") or "")
            if total + chars + length > TEXT_CAP:
                break
            kept.append(unit)
            chars += length
        total += chars
        materials.append({"id": "M%d" % no, "name": path.name, "path": str(path), "kind": kind,
                          "bytes": size, "sha1": digest, "extractor": how, "units": kept,
                          "chars": chars, "title": title_of(kept, path.stem),
                          "text_available": bool(kept),
                          "note": None if kept else "无可用文本（图片/未支持格式/解析失败）"})
    order = semantic(case, r"workorder|requirement|deliverable_spec")
    if isinstance(order, (dict, list)):
        lines = [x for x in json.dumps(order, ensure_ascii=False, indent=1).splitlines() if x.strip()]
    elif isinstance(order, str):
        lines = [x for x in order.splitlines() if x.strip()]
    else:
        lines = []
    return {"skill": SKILL_ID, "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "input_dir": str(IN), "case_path": str(case_path) if case_path else None,
            "case_id": case.get("case_id") or case.get("id") or semantic(case, r"case_?id|^id$"),
            "contract": contract, "instruction": semantic(case, r"task_?instruction|instruction|prompt", ""),
            "workorder": lines[:60], "materials": materials, "total_chars": total}


def load_contract(case):
    value = semantic(case, r"output_contract|^contract$", {})
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------- 渲染
ESC = html.escape


def _head(model, geo, stamp):
    width, height = int(geo["w"]), int(geo["h"])
    return [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
        'font-family="Noto Sans CJK SC, Source Han Sans SC, Microsoft YaHei, Arial, sans-serif" '
        'data-generator="%s">' % (width, height, width, height, ESC(stamp)),
        '<title>%s</title>' % ESC(model["theme"]["label"] or "mindmap"),
        '<desc>%s</desc>' % ESC('可编辑导图：节点为 <g id="node-*">，带 data-locator/data-quote/'
                                'data-parent；关系为 <path id="rel-*">；文字全部在 text/tspan 中'),
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#5b6b7b"/>'
        '</marker></defs>',
        '<g id="hierarchy" fill="none" stroke="#9db4c6" stroke-width="1.7">',
    ]


def _tree_paths(geo):
    rows = []
    for curve in geo["curves"]:
        if curve["type"] != "hierarchy":
            continue
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = curve["d"]
        rows.append('<path id="tree-%s-%s" data-from="%s" data-to="%s" d="M%.1f,%.1f C%.1f,%.1f '
                    '%.1f,%.1f %.1f,%.1f"/>'
                    % (ESC(curve["from"]), ESC(curve["to"]), ESC(curve["from"]), ESC(curve["to"]),
                       x0, y0, x1, y1, x2, y2, x3, y3))
    return rows


def _rel_paths(model, geo):
    rows = []
    wired = {(c["from"], c["to"], c["type"]): c for c in geo["curves"] if c["type"] != "hierarchy"}
    for edge in model["edges"]:
        curve = wired.get((edge["from"], edge["to"], edge["type"]))
        if not curve:
            continue
        color, dash = mmcore.REL_PAINT.get(edge["type"], ("#5b6b7b", "5,3"))
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = curve["d"]
        rows.append('<path id="rel-%s" class="relation-%s" data-relation="%s" data-from="%s" '
                    'data-to="%s" data-evidence="%s" d="M%.1f,%.1f C%.1f,%.1f %.1f,%.1f %.1f,%.1f" '
                    'fill="none" stroke="%s" stroke-width="1.6" stroke-dasharray="%s" '
                    'marker-end="url(#arrow)"/>'
                    % (ESC(edge["id"]), ESC(edge["type"]), ESC(edge["relation"]), ESC(edge["from"]),
                       ESC(edge["to"]), ESC(edge.get("evidence_id") or ""),
                       x0, y0, x1, y1, x2, y2, x3, y3, color, dash))
        anchor = curve.get("anchor")
        if anchor:
            rows.append('<text id="rel-label-%s" x="%.1f" y="%.1f" font-size="11.5" fill="%s" '
                        'text-anchor="start">%s</text>'
                        % (ESC(edge["id"]), anchor[0], anchor[1], color, ESC(edge["label"])))
    return rows


def _node_groups(model, geo):
    rows = []
    evidence = {n["id"]: n["evidence"] for n in model["nodes"]}
    evidence["root"] = model["theme"]["evidence"]
    for nid in ["root"] + list(geo["order"]):
        if nid not in geo["boxes"]:
            continue
        node = geo["pool"][nid]
        x, y, w, h = geo["boxes"][nid]
        level = node["level"]
        fill, ink = mmcore.PAINT.get(level, mmcore.PAINT[3])
        pool = sorted(evidence.get(nid) or [], key=lambda e: 1 if e.get("verified") else 0, reverse=True)
        top = pool[0] if pool else {}
        rows.append('<g id="node-%s" data-node-id="%s" data-level="%d" data-role="%s"%s '
                    'data-locator="%s" data-quote="%s" data-material="%s" data-evidence="%d" '
                    'data-verified="%d"><title>%s</title>'
                    % (ESC(nid), ESC(nid), level, ESC(node.get("role") or ""),
                       "" if nid == "root" else ' data-parent="%s"' % ESC(node["parent"]),
                       ESC(str(top.get("locator") or "")[:70]), ESC(str(top.get("quote") or "")[:220]),
                       ESC(str(top.get("material") or "")[:12]), len(pool),
                       1 if top.get("verified") else 0, ESC(node["label"][:200])))
        rows.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="9" fill="%s" '
                    'stroke="%s" stroke-width="1.5"/>'
                    % (x, y, w, h, fill, "#1f6fa8" if level <= 1 else "#c9d8e4"))
        rows.append('<text x="%.1f" y="%.1f" font-size="%s" font-weight="%s" fill="%s" '
                    'text-anchor="middle">'
                    % (x + w / 2, y + (h - len(node["lines"]) * 19) / 2 + 14.5,
                       16 if level == 0 else (14.5 if level == 1 else 13),
                       "600" if level <= 1 else "400", ink))
        for k, line in enumerate(node["lines"]):
            rows.append('<tspan x="%.1f" dy="%s">%s</tspan>'
                        % (x + w / 2, 0 if k == 0 else 19, ESC(line)))
        rows.append("</text></g>")
    return rows


def _legend(geo):
    height = int(geo["h"])
    y = height - 34
    rows = ['<g id="legend" font-size="11.5" fill="#43566b">',
            '<text x="36" y="%d">关系图例（括号内为 JSON 里的 relation）：</text>' % y]
    x = 268
    for code in mmcore.REL_CODES:
        color, dash = mmcore.REL_PAINT[code]
        rows.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1.8" '
                    'stroke-dasharray="%s"/>' % (x, y - 4, x + 26, y - 4, color, dash))
        rows.append('<text x="%d" y="%d">%s %s</text>'
                    % (x + 31, y, ESC(mmcore.REL_ZH[code]), ESC(code)))
        x += 106
    rows.append("</g>")
    return rows


def to_svg(model, geo, stamp):
    parts = _head(model, geo, stamp)
    parts += _tree_paths(geo)
    parts.append('</g><g id="relations">')
    parts += _rel_paths(model, geo)
    parts.append('</g><g id="nodes">')
    parts += _node_groups(model, geo)
    parts.append("</g>")
    parts += _legend(geo)
    parts.append('<g id="stamp"><text x="36" y="%d" font-size="11" fill="#7b8b9a">%s</text></g></svg>'
                 % (int(geo["h"]) - 12, ESC(stamp)))
    return "\n".join(parts)


# ------------------------------------------------------------------ 位图
def _png_bytes(width, height, canvas):
    scanlines = bytearray()
    stride = width * 3
    for y in range(height):
        scanlines.append(0)
        scanlines += canvas[y * stride:(y + 1) * stride]

    def block(tag, payload):
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + block(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + block(b"IDAT", zlib.compress(bytes(scanlines), 9))
            + block(b"IEND", b""))


def _rgb(color):
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def rasterize(model, geo, target, scale=1.0):
    """纯标准库位图：节点实心块 + 层级/关系连线 + 行纹理，布局与 JSON 完全同源。"""
    width = int(min(2400, max(64, geo["w"] * scale)))
    height = int(min(2400, max(64, geo["h"] * scale)))
    if width * height > 4_500_000:
        width = 1500
        height = int(min(2400, max(64, geo["h"] * width / max(1.0, geo["w"]))))
    canvas = bytearray(b"\xff" * (width * height * 3))
    sx, sy = width / max(1.0, geo["w"]), height / max(1.0, geo["h"])

    def pixel(px, py, rgb):
        if 0 <= px < width and 0 <= py < height:
            at = (py * width + px) * 3
            canvas[at:at + 3] = bytes(rgb)

    def frame(x0, y0, x1, y1, rgb, solid):
        ix0, iy0 = max(0, int(x0)), max(0, int(y0))
        ix1, iy1 = min(width, int(x1)), min(height, int(y1))
        if solid:
            for py in range(iy0, iy1):
                for px in range(ix0, ix1):
                    pixel(px, py, rgb)
            return
        for px in range(ix0, ix1):
            pixel(px, iy0, rgb)
            pixel(px, iy1 - 1, rgb)
        for py in range(iy0, iy1):
            pixel(ix0, py, rgb)
            pixel(ix1 - 1, py, rgb)

    for curve in geo["curves"]:
        rgb = _rgb("#9db4c6" if curve["type"] == "hierarchy"
                   else mmcore.REL_PAINT[curve["type"]][0])
        points = mmcore.bezier(curve["d"], 26)
        for k in range(len(points) - 1):
            (ax, ay), (bx, by) = points[k], points[k + 1]
            steps = max(1, int(max(abs(bx - ax) * sx, abs(by - ay) * sy)))
            for s in range(steps + 1):
                t = s / steps
                pixel(int((ax + (bx - ax) * t) * sx), int((ay + (by - ay) * t) * sy), rgb)

    for nid, (x, y, w, h) in geo["boxes"].items():
        level = geo["pool"][nid]["level"]
        fill, ink = mmcore.PAINT.get(level, mmcore.PAINT[3])
        frame(x * sx, y * sy, (x + w) * sx, (y + h) * sy, _rgb(fill), True)
        frame(x * sx, y * sy, (x + w) * sx, (y + h) * sy,
              _rgb("#1f6fa8" if level <= 1 else "#c9d8e4"), False)
        left, top = int(x * sx) + 7, int(y * sy) + 7
        right, bottom = min(width - 1, int((x + w) * sx) - 7), int((y + h) * sy) - 6
        for py in range(top, max(top, min(bottom, top + int((bottom - top) * 0.62)))):
            if (py - top) % 4 < 2:                 # 纹理条示意文字行，不伪造字形
                for px in range(left, right):
                    pixel(px, py, _rgb(ink))
    target = Path(target)
    target.write_bytes(_png_bytes(width, height, canvas))
    return {"width": width, "height": height, "bytes": target.stat().st_size}


CHAIN = (
    ("rsvg-convert", lambda svg, png, geo: ["rsvg-convert", "-w", "2200", "-o", str(png), str(svg)]),
    ("inkscape", lambda svg, png, geo: ["inkscape", str(svg), "--export-type=png",
                                        "--export-filename=" + str(png)]),
    ("convert", lambda svg, png, geo: ["convert", "-background", "white", "-density", "150",
                                       str(svg), str(png)]),
    ("chromium", lambda svg, png, geo: ["chromium", "--headless", "--disable-gpu", "--no-sandbox",
                                        "--screenshot=" + str(png),
                                        "--window-size=%d,%d" % (int(geo["w"]), int(geo["h"])),
                                        "file://" + str(svg)]),
)


def preview(svg_path, png_path, model, geo):
    """渲染链：先真渲染 SVG；全缺席时按几何位图降级，绝不靠改扩展名冒充。"""
    svg_path, png_path = Path(svg_path), Path(png_path)
    for name, build in CHAIN:
        if not shutil.which(name):
            continue
        try:
            subprocess.run(build(svg_path, png_path, geo), capture_output=True, timeout=180,
                           cwd=str(svg_path.parent))
            if png_path.is_file() and png_path.stat().st_size > 2000 \
                    and png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n":
                return {"mode": "svg-render", "renderer": name, "bytes": png_path.stat().st_size}
        except Exception:
            continue
    try:
        info = rasterize(model, geo, png_path)
        base = {"mode": "geometry-blocks", "renderer": "builtin", "bytes": info["bytes"],
                "note": "本机无 SVG 渲染器：按同一几何数据生成位图（色块+连线+行纹理，无字形）"}
        if info["bytes"] > 900_000:
            base = {"mode": "none", "renderer": "builtin", "bytes": 0,
                    "note": "位图超出体积预算，已放弃预览"}
            png_path.unlink(missing_ok=True)
        return base
    except Exception as exc:
        return {"mode": "none", "renderer": None, "bytes": 0,
                "note": "位图生成失败：%s" % str(exc)[:120]}
