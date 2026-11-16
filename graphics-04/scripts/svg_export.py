#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""svg_export.py -- graphics-04 drawing and export layer.

A tiny primitive list (Sketch) is the single source of truth: the same list is
serialised to the layered SVG, printed to PDF and rasterised to PNG, so the
three deliverables can never drift apart. External converters are optional:
the engine that actually produced each file is recorded, and every missing
converter is reported as an explicit degradation instead of a silent failure.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
import zlib
from pathlib import Path

VERSION = "1.0.0"
FONT_STACK = "'Noto Sans CJK SC','Source Han Sans SC','Microsoft YaHei','SimHei',Arial,Helvetica,sans-serif"
INK_DARK, INK_MUTED, CANVAS_GRID = "#16202b", "#5d6b7a", "#c9d3dd"
FLOW_MEDIA = {"material": ("物料", "#1f5fa8", ""), "energy": ("能量", "#c1440e", "9,4"),
  "information": ("信息", "#2f7d4f", "2.5,3.5")}
LAYER_ORDER = ["background", "zones", "connections", "parts", "steps", "stages", "data", "legend",
  "labels", "notes"]
BOX_W, BOX_H, COL_GAP, ROW_GAP, PANEL_HEAD = 196, 84, 104, 48, 52

class Sketch:
  def __init__(self):
    self.p, self.maxx, self.maxy = [], 0.0, 0.0

  def _t(self, x, y):
    self.maxx, self.maxy = max(self.maxx, x), max(self.maxy, y)

  def rect(self, x, y, w, h, fill="none", stroke=INK_DARK, sw=1.4, rx=0, layer="parts", eid=None, src=None, dash=None):
    self.p.append(dict(t="r", x=x, y=y, w=w, h=h, fill=fill, stroke=stroke, sw=sw, rx=rx, layer=layer,
  eid=eid, src=src, dash=dash)); self._t(x + w, y + h)

  def poly(self, pts, stroke=INK_DARK, sw=1.6, layer="connections", eid=None, src=None, marker=None, dash=None):
    self.p.append(dict(t="p", pts=pts, stroke=stroke, sw=sw, layer=layer, eid=eid, src=src, marker=marker,
  dash=dash, fill="none"))
    for x, y in pts:
      self._t(x, y)

  def text(self, x, y, s, size=13, anchor="start", layer="labels", eid=None, fill=INK_DARK, weight="normal", src=None):
    self.p.append(dict(t="t", x=x, y=y, s=str(s), size=size, anchor=anchor, layer=layer, eid=eid, fill=fill,
  weight=weight, src=src))
    w = text_em_width(s, size)
    self._t(x + (0 if anchor == "start" else (-w if anchor == "end" else -w / 2)) + w, y + size * 0.3)

  def label(self, x, y, s, size=11, anchor="middle", layer="labels", eid=None, fill=INK_DARK):
    w = text_em_width(s, size)
    x0 = x if anchor == "start" else x - (w if anchor == "end" else w / 2)
    self.rect(x0 - 3, y - size * .95, w + 6, size * 1.3, fill="#ffffff", stroke="none", sw=0, layer=layer)
    self.text(x, y, s, size=size, anchor=anchor, layer=layer, eid=eid, fill=fill)

  def circle(self, cx, cy, r, fill="#ffffff", stroke=INK_DARK, sw=1.3, layer="labels", eid=None):
    self.p.append(dict(t="c", cx=cx, cy=cy, r=r, fill=fill, stroke=stroke, sw=sw, layer=layer, eid=eid))
    self._t(cx + r, cy + r)

def choose_panels(kind, m):
  s = []
  if kind in ("apparatus", "combo") and m["parts"]:
    s.append("apparatus")
  if kind in ("process", "combo") and m["steps"]:
    s.append("process")
  if kind in ("route", "combo") and m["stages"]:
    s.append("route")
  if kind == "route" and not m["stages"] and m["steps"]:
    s.append("process")
  if kind == "process" and not m["steps"] and m["stages"]:
    s.append("route")
  if not s:
    s = ["apparatus"] * bool(m["parts"]) + ["process"] * bool(m["steps"]) + ["route"] * bool(m["stages"])
  return s

def compose_svg(m, specs, title, foot):
  W, y = 1440, 6
  cv = Sketch()
  cv.text(44, y + 34, title, size=22, weight="bold", eid="figure-title")
  y += 52
  for sp in specs:
    y = {"apparatus": panel_device, "process": panel_steps, "route": panel_route}[sp](cv, m, y, W) + 18
  y = panel_legend(cv, m, y, W)
  fl = fold_text(foot, 10, W - 120)[:4]
  for i, ln in enumerate(fl):
    cv.text(44, y + 16 + i * 13, ln, size=10, fill=INK_MUTED, layer="notes", eid="note-%d" % (i + 1))
  H = max(y + 40 + 13 * len(fl), 420)
  cv.rect(0, 0, W, H, fill="none", stroke=CANVAS_GRID, sw=1, layer="background", eid="canvas-frame")
  return dump_svg(cv, W, H, title), cv, W, H

def coord(value):
  """Format a coordinate with up to two decimals and no trailing zeros."""
  return ("%.2f" % float(value)).rstrip("0").rstrip(".")

def dump_svg(cv, W, H, title):
  L = ['<?xml version="1.0" encoding="UTF-8"?>',
  '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="%d" height="%d" viewBox="0 0 %d %d" '
  'font-family="%s">' % (W, H, W, H, xml_escape(FONT_STACK.replace("'", ""))),
  '<title>%s</title>' % xml_escape(title),
  '<desc>Apparatus / process / technical route figure. Layers: %s. graphics-04 v%s.</desc>'
  % (",".join(LAYER_ORDER), VERSION), '<defs>']
  for k in list(FLOW_MEDIA) + ["ink"]:
    L.append('<marker id="ar-%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
  'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="%s"/></marker>'
  % (k, FLOW_MEDIA[k][1] if k in FLOW_MEDIA else INK_DARK))
  L.append('</defs>')
  for ln in LAYER_ORDER:
    ps = [p for p in cv.p if p["layer"] == ln]
    if not ps:
      continue
    L.append('<g id="layer-%s" inkscape:groupmode="layer" inkscape:label="%s" '
  'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">' % (ln, ln))
    for p in ps:
      a = (' id="%s"' % xml_escape(p["eid"]) if p.get("eid") else "") + \
          (' data-src="%s"' % xml_escape(p["src"]) if p.get("src") else "")
      d = ' stroke-dasharray="%s"' % p["dash"] if p.get("dash") else ""
      t = p["t"]
      X, Y = (coord(p["x"]), coord(p["y"])) if t == "r" else (coord(p["cx"]), coord(p["cy"])) if t == "c" else ("0", "0")
      if t == "r":
        L.append('<rect%s x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s" stroke="%s" stroke-width="%s"%s/>'
  % (a, X, Y, coord(p["w"]), coord(p["h"]), coord(p.get("rx", 0)), p["fill"], p["stroke"], coord(p["sw"]), d))
      elif t == "c":
        L.append('<circle%s cx="%s" cy="%s" r="%s" fill="%s" stroke="%s" stroke-width="%s"/>'
  % (a, X, Y, coord(p["r"]), p["fill"], p["stroke"], coord(p["sw"])))
      elif t == "p":
        L.append('<polyline%s points="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round"%s%s/>'
  % (a, " ".join("%s,%s" % (coord(x), coord(y)) for x, y in p["pts"]), p["stroke"], coord(p["sw"]), d,
  ' marker-end="url(#%s)"' % p["marker"] if p.get("marker") else ""))
      else:
        L.append('<text%s x="%s" y="%s" font-size="%s" font-weight="%s" text-anchor="%s" fill="%s">%s</text>'
  % (a, X, Y, coord(p["size"]), p["weight"], p["anchor"], p["fill"], xml_escape(p["s"])))
    L.append('</g>')
  L.append('</svg>')
  return "\n".join(L)

def element_ids(svg):
  import xml.etree.ElementTree as ET
  try:
    return {e.attrib["id"] for e in ET.fromstring(svg).iter() if "id" in e.attrib}
  except Exception:
    return set(re.findall(r'id="([^"]+)"', svg))

def em_width(char):
  return 1.0 if ord(char) > 0x2E80 else 0.55

def export_bundle(cv, W, H, svgp, outdir, work, exc, budget, t0):
  outdir, svgp = Path(outdir), Path(svgp)
  pdf, png = outdir / "figure.pdf", outdir / "figure.png"
  info = {"png": None, "pdf": None}
  home = Path(tempfile.mkdtemp(prefix="render-"))
  env = dict(os.environ, HOME=str(home))
  soffice = shutil.which("soffice") or shutil.which("libreoffice")
  browser = find_browser()
  log = open(Path(work) / "render.log", "a")

  def exec_ok(command, limit=75):
    try:
      return subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            timeout=limit, env=env).returncode == 0
    except Exception:
      return False

  def convert(to):
    return [soffice, "--headless", "--nologo", "--nodefault", "--norestore", "--nolockcheck",
            "-env:UserInstallation=file://" + str(home / "lo"), "--convert-to", to,
            "--outdir", str(outdir), str(svgp)]

  def wait_meta(target, inspect, limit=25):
    end = time.time() + limit
    while time.time() < end:
      got = inspect(target)
      if got:
        return got
      time.sleep(0.4)
    return inspect(target)

  if soffice:
    exec_ok(convert("pdf"))
    if not pdf.exists():
      exec_ok(convert("pdf"))                 # first pass warms a fresh office profile
  if pdf_meta(pdf):
    info["pdf"] = dict(pdf_meta(pdf), engine="soffice-svg2pdf", degraded=False)
  elif browser:
    exec_ok([browser, "--headless=new", "--disable-gpu", "--no-first-run",
             "--no-default-browser-check", "--no-pdf-header-footer",
             "--user-data-dir=" + str(home / "browser"),
             "--print-to-pdf=" + str(pdf), svgp.resolve().as_uri()], 120)
    late = wait_meta(pdf, pdf_meta, 30)
    if late:
      info["pdf"] = dict(late, engine="chromium-print-pdf", degraded=True)
      exc.append({"code": "pdf_engine_fallback", "message": "本机没有 soffice，PDF 改由无头 Chromium 打印",
                  "severity": "minor", "action": "投稿前确认字体已嵌入；SVG 仍是可编辑真值"})
  if not info["pdf"]:
    try:
      skipped = write_minimal_pdf(cv, W, H, pdf)
      info["pdf"] = dict(pdf_meta(pdf), engine="stdlib-vector-pdf", degraded=True)
      exc.append({"code": "pdf_degraded", "message": "没有 soffice/Chromium，PDF 由标准库直接写矢量（跳过 %d 个 CJK 字符）" % skipped,
                  "severity": "major", "action": "文字以 SVG 为准；在装 soffice 的环境重跑可得完整 PDF"})
    except Exception as e:
      exc.append({"code": "pdf_failed", "message": "PDF 导出链全部失败：%s" % str(e)[:80],
                  "severity": "major", "action": "SVG 是可编辑真值；在装 soffice/Inkscape 的环境重跑"})
  if info["pdf"] and time.time() - t0 < budget + 120 and shutil.which("pdftoppm"):
    exec_ok(["pdftoppm", "-png", "-r", "160", "-singlefile", str(pdf), str(outdir / "figure")], 90)
    info["png"] = png_meta(png)
    if info["png"]:
      info["png"].update(engine="pdftoppm", dpi=160)
  if info["pdf"] and not info["png"] and shutil.which("gs"):
    exec_ok(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m", "-r160",
             "-sOutputFile=" + str(png), str(pdf)], 90)
    info["png"] = png_meta(png)
    if info["png"]:
      info["png"].update(engine="gs", dpi=160)
  if not info["png"] and browser:
    exec_ok([browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             "--hide-scrollbars", "--user-data-dir=" + str(home / "browser"),
             "--window-size=%d,%d" % (max(320, int(W)), max(240, int(H))),
             "--screenshot=" + str(png), svgp.resolve().as_uri()], 120)
    info["png"] = wait_meta(png, png_meta, 20)
    if info["png"]:
      info["png"].update(engine="chromium-screenshot", dpi=96)
  if not info["png"] and soffice:
    exec_ok(convert("png"))
    info["png"] = png_meta(png)
    if info["png"]:
      info["png"].update(engine="soffice-svg2png", dpi=96)
  if not info["png"]:
    exc.append({"code": "png_failed", "message": "没有可用的栅格渲染器（pdftoppm/gs/Chromium/soffice/ImageMagick）",
                "severity": "major", "action": "交付 SVG+PDF，PNG 需在装 poppler/gs 的环境重跑"})
  if not info["pdf"] and pdf_meta(pdf):
    info["pdf"] = dict(pdf_meta(pdf), engine="chromium-print-pdf-late", degraded=True)
    exc.append({"code": "pdf_engine_fallback", "message": "PDF 由无头 Chromium 异步写出，已按迟到文件接收",
                "severity": "minor", "action": "投稿前确认字体已嵌入；SVG 仍是可编辑真值"})
  if not info["png"] and png_meta(png):
    info["png"] = dict(png_meta(png), engine="chromium-screenshot-late", dpi=96)
  try:
    log.close()
  except Exception:
    pass
  return info

def find_browser():
  for name in CHROMIUM_NAMES:
    hit = shutil.which(name)
    if hit:
      return hit
  return next((c for c in CHROMIUM_PATHS if Path(c).is_file()), None)

def fold_text(s, size, maxw):
  """Line-fold a string to maxw; CJK glyphs may break anywhere."""
  lines, cur, used = [], "", 0.0
  for ch in str(s):
    step = em_width(ch) * size
    if used + step > maxw and cur:
      lines.append(cur); cur, used = ch, step
    else:
      cur, used = cur + ch, used + step
  if cur:
    lines.append(cur)
  return lines or [""]

def layer_ranks(parts, conns):
  ids = [p["id"] for p in parts]
  adj, ind = {i: [] for i in ids}, {i: 0 for i in ids}
  for c in conns:
    if c.get("drawable") and c["from_id"] != c["to_id"]:
      adj[c["from_id"]].append(c["to_id"]); ind[c["to_id"]] += 1
  dep, q, seen = {i: 0 for i in ids}, [i for i in ids if ind[i] == 0], 0
  while q:
    cur = q.pop(0); seen += 1
    for nx in adj[cur]:
      dep[nx] = max(dep[nx], dep[cur] + 1); ind[nx] -= 1
      if ind[nx] == 0:
        q.append(nx)
  if seen < len(ids):
    dep = {i: min(dep[i], 3) for i in ids}
  return dep

def panel_device(cv, m, y0, W):
  parts, conns = m["parts"], m["conns"]
  if not parts:                                  # gap canvas: no drawable entity reported
    cv.text(44, y0 + 34, "材料未提供可绘制的部件 / 步骤 / 阶段，此处为缺口说明", size=14, fill=INK_MUTED, eid="gap-note")
    return y0 + PANEL_HEAD + 60
  dep = layer_ranks(parts, conns)
  cols = {}
  for p in parts:
    cols.setdefault(dep[p["id"]], []).append(p)
  for c in sorted(cols):
    for k, p in enumerate(cols[c]):
      p["_x"], p["_y"] = 44 + c * (BOX_W + COL_GAP), y0 + PANEL_HEAD + k * (BOX_H + ROW_GAP)
  rows = max((len(v) for v in cols.values()), default=1)
  cv.text(44, y0 + 32, "A  装置结构与物料流向", size=17, weight="bold", eid="panel-A")
  for i, p in enumerate(parts, 1):
    x, y = p["_x"], p["_y"]
    cv.rect(x, y, BOX_W, BOX_H, fill="#f6f9fc", sw=1.5, rx=9, eid=p["id"], src=(p["source"] or {}).get("locator"))
    cv.circle(x + 16, y + 15, 9.5, fill="#1f3b57", stroke="#1f3b57", eid=p["id"] + "-badge")
    cv.text(x + 16, y + 19.5, i, size=11, anchor="middle", fill="#ffffff", weight="bold")
    for j, ln in enumerate(fold_text(p["name"], 13, BOX_W - 46)[:2]):
      cv.text(x + 32, y + 22 + j * 16, ln, size=13, weight="bold")
    cv.text(x + 12, y + BOX_H - 24, "n=%s" % p["qty"] if p["qty"] is not None else "数量未报告", size=10, fill=INK_MUTED)
    if p["ports"]:
      cv.text(x + 12, y + BOX_H - 11, "接口: " + " / ".join(p["ports"]), size=9, fill=INK_MUTED)
    if p["group"]:
      cv.text(x + BOX_W - 10, y + BOX_H - 11, p["group"], size=9, fill=INK_MUTED, anchor="end")
    cv.rect(x - 5, y + BOX_H / 2 - 5, 10, 10, fill="#ffffff", sw=1.1)
    cv.rect(x + BOX_W - 5, y + BOX_H / 2 - 5, 10, 10, fill="#ffffff", sw=1.1)
  chan, nback = max(p["_y"] + BOX_H for p in parts) + 26, 0
  for c in conns:
    if not c.get("drawable"):
      continue
    a = next(p for p in parts if p["id"] == c["from_id"])
    b = next(p for p in parts if p["id"] == c["to_id"])
    col, dash = FLOW_MEDIA[c["medium"]][1], FLOW_MEDIA[c["medium"]][2]
    ay, by, ax, bx = a["_y"] + BOX_H / 2, b["_y"] + BOX_H / 2, a["_x"] + BOX_W + 5, b["_x"] - 5
    if a is b:
      pts = [(ax, ay), (ax + 22, ay), (ax + 22, a["_y"] + BOX_H + 20), (a["_x"] + BOX_W / 2, a["_y"] + BOX_H + 20),
  (a["_x"] + BOX_W / 2, a["_y"] + BOX_H + 5)]
      mid = (ax + 22, ay + 10)
    elif dep[b["id"]] > dep[a["id"]]:
      mx = (ax + bx) / 2
      pts, mid = [(ax, ay), (mx, ay), (mx, by), (bx, by)], (mx, (ay + by) / 2)
    else:  # backward / recycle -> routed under the block, dashed
      yl, nback, dash = chan + nback * 22, nback + 1, "6,4"
      pts = [(ax, ay), (ax + 30, ay), (ax + 30, yl), (bx - 30, yl), (bx - 30, by), (bx, by)]
      mid = ((ax + bx) / 2, yl)
    cv.poly(pts, stroke=col, sw=1.9, eid=c["id"], marker="ar-" + c["medium"], dash=dash,
  src=(c["source"] or {}).get("locator"))
    cv.label(mid[0], mid[1] - 7, FLOW_MEDIA[c["medium"]][0] + ("：" + str(c["label"]) if c.get("label") else ""),
  size=10, fill=col, eid=c["id"] + "-label")
  return y0 + PANEL_HEAD + rows * (BOX_H + ROW_GAP) + 46 + nback * 22

def panel_legend(cv, m, y, W):
  used = []
  for c in m["conns"]:
    if c.get("drawable") and c["medium"] not in used:
      used.append(c["medium"])
  used = used or ["material"]
  cv.text(44, y + 18, "图例", size=12, weight="bold", layer="legend", eid="legend-title")
  x = 96
  for k in used:
    cv.poly([(x, y + 13), (x + 34, y + 13)], stroke=FLOW_MEDIA[k][1], sw=2.2, layer="legend", eid="legend-line-" + k,
  marker="ar-" + k, dash=FLOW_MEDIA[k][2])
    cv.text(x + 42, y + 18, FLOW_MEDIA[k][0] + " 流向", size=11, layer="legend")
    x += 72 + text_em_width(FLOW_MEDIA[k][0], 11)
  for txt in ("部件/单元（左上角为图内编号）", "步骤序号（与正文顺序一致）"):
    cv.rect(x, y + 5, 16, 16, fill="#f6f9fc", sw=1.3, rx=3, layer="legend")
    cv.text(x + 24, y + 18, txt, size=11, layer="legend")
    x += 50 + text_em_width(txt, 11)
  return y + 34

def panel_route(cv, m, y0, W):
  stages, SW, gap, H = m["stages"], 262, 62, 300
  y = y0 + PANEL_HEAD
  cv.text(44, y0 + 32, "C  技术路线（阶段目标 / 方法 / 输入输出 / 依赖）", size=17, weight="bold", eid="panel-C")
  maxc = max(1, min(len(stages), max(1, int((W - 88 + gap) // (SW + gap)))))
  for k, st in enumerate(stages):
    r, c = divmod(k, maxc)
    x, yy = 44 + c * (SW + gap), y + r * (H + 74)
    cv.rect(x, yy, SW, H, fill="#fbf7f2", sw=1.4, rx=8, layer="stages", eid="stage-%d" % (k + 1),
  src=(st["source"] or {}).get("locator"))
    cv.rect(x, yy, SW, 40, fill="#e9dccb", sw=1.2, rx=8, layer="stages", eid="stage-%d-head" % (k + 1))
    cv.text(x + 10, yy + 25, ("%s %s" % (st["id"], st["title"]))[:26], size=13, weight="bold", layer="stages")
    cur = yy + 60
    for cap, vals in (("目标", [st["goal"]] if st["goal"] else []), ("方法", st["methods"]),
  ("输入", st["inputs"]), ("输出", st["outputs"]), ("依赖", st["deps"]),
  ("里程碑", [st["milestone"]] if st["milestone"] else [])):
      if not vals:
        continue
      cv.text(x + 10, cur, cap, size=10, weight="bold", fill=INK_MUTED, layer="stages"); cur += 13
      for v in vals[:3]:
        for ln in fold_text("· " + str(v), 11, SW - 24)[:2]:
          cv.text(x + 12, cur, ln, size=11, layer="stages"); cur += 14
      cur += 4
    if st["milestone"]:
      cv.poly([(x + SW - 16, yy + 46), (x + SW - 8, yy + 54), (x + SW - 16, yy + 62), (x + SW - 24, yy + 54)],
  stroke="#b06a1e", layer="stages", eid="stage-%d-milestone" % (k + 1))
    if c < maxc - 1 and k + 1 < len(stages):
      cv.poly([(x + SW, yy + H / 2), (x + SW + 6, yy + H / 2)], sw=1.8, eid="dep-%d" % (k + 1), marker="ar-ink")
      if stages[k + 1]["deps"]:
        cv.label(x + SW + gap / 2, yy + H / 2 - 10, str(stages[k + 1]["deps"][0])[:12], size=9, fill=INK_MUTED)
  return y + ((len(stages) + maxc - 1) // maxc) * (H + 74) + 8

def panel_steps(cv, m, y0, W):
  cx, bw = W / 2, min(760, W - 200)
  x, y = cx - bw / 2, y0 + PANEL_HEAD
  cv.text(44, y0 + 32, "B  工艺流程与步骤顺序", size=17, weight="bold", eid="panel-B")
  for s in m["steps"]:
    lines = fold_text(s["title"], 13, bw - 90)
    h = max(56, 30 + 18 * len(lines))
    lay = dict(layer="steps")
    cv.rect(x, y, bw, h, fill="#f7f9f5", sw=1.4, rx=8, eid="step-%d" % s["no"], layer="steps",
  src=(s["source"] or {}).get("locator"))
    cv.circle(x + 26, y + h / 2, 15, fill="#2f6b3f", stroke="#2f6b3f", eid="step-%d-badge" % s["no"], **lay)
    cv.text(x + 26, y + h / 2 + 5, s["no"], size=13, anchor="middle", fill="#ffffff", weight="bold", **lay)
    for j, ln in enumerate(lines):
      cv.text(x + 52, y + 26 + j * 18, ln, size=13, **lay)
    if s["no"] > 1:
      cv.poly([(cx, y - 34), (cx, y - 3)], sw=1.7, eid="flow-%d" % s["no"], marker="ar-ink")
    if s["parallel"]:
      cv.label(x + bw + 18, y + h / 2, "并行支路", size=10, anchor="start", fill=INK_MUTED, layer="steps")
    if s.get("loop_to"):
      cv.label(x + bw - 8, y + 14, "回流/终止：" + str(s["loop_to"]), size=10, anchor="end", fill=INK_MUTED,
  layer="steps")
    y += h + 34
  return y + 4

def pdf_meta(p):
  try:
    b = Path(p).read_bytes()
  except Exception:
    return None
  if not b.startswith(b"%PDF-"):
    return None
  return {"path": str(p), "pages": max(1, len(re.findall(rb"/Type\s*/Page[^s]", b))), "bytes": len(b),
  "vector": b"/Subtype /Image" not in b, "magic_ok": True}

CHROMIUM_NAMES = ("msedge", "microsoft-edge", "chrome", "google-chrome", "chromium", "chromium-browser")
CHROMIUM_PATHS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
  r"C:\Program Files\Google\Chrome\Application\chrome.exe")

def pdf_rgb(color):
  h = str(color).lstrip("#")
  return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)] if len(h) == 6 else [0.0, 0.0, 0.0]

def pdf_string(text):
  return "(" + str(text).replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)") + ")"

def png_meta(p):
  try:
    b = Path(p).read_bytes()
  except Exception:
    return None
  if b[:8] != b"\x89PNG\r\n\x1a\n":
    return None
  return {"path": str(p), "width": int.from_bytes(b[16:20], "big"), "height": int.from_bytes(b[20:24], "big"),
  "bytes": len(b), "magic_ok": True}

def probe_png(p):
  """decode the PNG header + IDAT to prove the preview is real and non-blank."""
  try:
    b = Path(p).read_bytes()
    w, h = int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
    idat, i = b"", 8
    while i < len(b):
      ln = int.from_bytes(b[i:i + 4], "big")
      if b[i + 4:i + 8] == b"IDAT":
        idat += b[i + 8:i + 8 + ln]
      i += 12 + ln
    raw = zlib.decompress(idat)
    cols, step = set(), max(3, (len(raw) // 6000) * 3)
    for k in range(0, len(raw) - 3, step):
      cols.add(raw[k:k + 3])
      if len(cols) > 400:
        break
    return {"ihdr": [w, h], "unique_colors": len(cols), "non_blank": len(cols) > 1,
  "ok": w > 200 and h > 200 and len(cols) > 1}
  except Exception as e:
    return {"error": str(e), "ok": False}

def text_em_width(s, size):
  """Estimated rendered width of a string, in user units."""
  return sum(em_width(char) for char in str(s)) * size

def write_minimal_pdf(cv, W, H, target):
  ops, cjk_skipped = [], 0

  def circle_path(cx, cy, rad, fill):
    k, steps = 0.5523 * rad, [(rad, 0), (rad, k), (k, rad), (0, rad), (-k, rad), (-rad, k), (-rad, 0),
                              (-rad, -k), (-k, -rad), (0, -rad), (k, -rad), (rad, -k), (rad, 0)]
    pts = [("%s %s" % (coord(cx + dx), coord(cy + dy))) for dx, dy in steps]
    ops.append(pts[0] + " m " + " ".join("%s %s %s c" % (pts[i], pts[i + 1], pts[i + 2]) for i in range(1, 13, 3))
               + (" f" if fill else " S"))

  for p in cv.p:
    kind = p["t"]
    if kind in ("r", "c", "p") and p.get("fill", "none") != "none":
      ops.append("%.3f %.3f %.3f rg" % tuple(pdf_rgb(p["fill"])))
      if kind == "r":
        ops.append("%s %s %s %s re f" % (coord(p["x"]), coord(H - p["y"] - p["h"]), coord(p["w"]), coord(p["h"])))
      elif kind == "c":
        circle_path(p["cx"], H - p["cy"], p["r"], True)
    if kind in ("r", "c", "p"):
      ops.append("%.3f %.3f %.3f RG %s w" % (tuple(pdf_rgb(p["stroke"])) + (coord(p.get("sw", 1)),)))
      if p.get("dash"):
        ops.append("[%s] 0 d" % " ".join(str(round(float(v), 2)) for v in str(p["dash"]).split(",")))
      if kind == "r":
        ops.append("%s %s %s %s re S" % (coord(p["x"]), coord(H - p["y"] - p["h"]), coord(p["w"]), coord(p["h"])))
      elif kind == "c":
        circle_path(p["cx"], H - p["cy"], p["r"], False)
      else:
        pts = ["%s %s" % (coord(x), coord(H - y)) for x, y in p["pts"]]
        if pts:
          ops.append(pts[0] + " m " + " ".join(q + " l" for q in pts[1:]) + (" S" if len(pts) > 1 else " h S"))
      if p.get("dash"):
        ops.append("[] 0 d")
    elif kind == "t":
      latin = "".join(ch for ch in str(p["s"]) if ord(ch) < 0x2E80)
      cjk_skipped += len(str(p["s"])) - len(latin)
      if not latin.strip():
        continue
      width = text_em_width(latin, p["size"])
      left = p["x"] - (0 if p["anchor"] == "start" else (width if p["anchor"] == "end" else width / 2))
      ops.append("%.3f %.3f %.3f rg BT /F1 %s Tf %s %s Td %s Tj ET" % (
        tuple(pdf_rgb(p["fill"])) + (coord(p["size"]), coord(left), coord(H - p["y"]), pdf_string(latin))))
  body = "\n".join(ops).encode("latin-1", "replace")
  objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 5 0 R >> >> "
     "/Contents 4 0 R >>" % (int(round(W)), int(round(H)))).encode("ascii"),
    b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
  out, offsets = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
  for index, obj in enumerate(objects, 1):
    offsets.append(len(out))
    out += ("%d 0 obj\n" % index).encode("ascii") + obj + b"\nendobj\n"
  xref_at = len(out)
  out += ("xref\n0 %d\n" % (len(objects) + 1)).encode("ascii") + b"0000000000 65535 f \n"
  out += b"".join(("%010d 00000 n \n" % off).encode("ascii") for off in offsets)
  out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
          % (len(objects) + 1, xref_at)).encode("ascii")
  Path(target).write_bytes(bytes(out))
  return cjk_skipped

def xml_escape(text):
  """Escape the five XML special characters used inside the SVG output."""
  return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
