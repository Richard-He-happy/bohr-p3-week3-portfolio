"""raster_ops.py - dependency-free primitives behind figure-evidence-lens.

Decodes PNG rasters and reports frame, tick, colour and legend structure; fits
pixel-to-value maps; copies literal CSV/JSON tables; pulls text strings out of
PDF streams. Offline, no third-party imports, and no assumptions about the CWD.
All reported coordinates are original image pixels; analysis_scale is the
downsampling stride that bounds the +/- quantisation error.
"""
from __future__ import annotations
import csv, hashlib, io, json, math, re, struct, zipfile, zlib
from pathlib import Path
import xml.etree.ElementTree as ET

PNG_SIG = b"\x89PNG\r\n\x1a\n"
MAX_PIXELS = 2_200_000
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def file_digest(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def magic_kind(p):
    """Coarse file flavour taken from magic bytes; the file name is ignored."""
    try: prefix = Path(p).read_bytes()[:16]
    except OSError: return "unreadable"
    if prefix.startswith(PNG_SIG): return "png"
    if prefix.startswith(b"\xff\xd8\xff"): return "jpeg"
    if prefix[:4] == b"%PDF": return "pdf"
    if prefix[:4] == b"PK\x03\x04":
        try: names = set(zipfile.ZipFile(p).namelist())
        except Exception: return "zip"
        if any(n.startswith("xl/") for n in names): return "xlsx"
        return "docx" if any(n.startswith("word/") for n in names) else "zip"
    for s, k in ((b"BM", "bmp"), (b"II*\x00", "tiff"), (b"MM\x00*", "tiff")):
        if prefix.startswith(s): return k
    try: txt = Path(p).read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError): return "binary"
    return "json" if txt.lstrip()[:1] in "{[" else ("csv" if txt.count(",") >= 3 else "text")


def decode_png(p):
    """Decode an 8-bit, non-interlaced PNG into RGB scanlines."""
    data = Path(p).read_bytes()
    if not data.startswith(PNG_SIG): raise ValueError("not a PNG stream")
    cursor, chunks, palette_body, header = 8, [], None, None
    while cursor + 8 <= len(data):
        ln = struct.unpack(">I", data[cursor:cursor + 4])[0]
        chunk_type, payload = data[cursor + 4:cursor + 8], data[cursor + 8:cursor + 8 + ln]
        if chunk_type == b"IHDR": header = struct.unpack(">IIBBBBB", payload)
        elif chunk_type == b"IDAT": chunks.append(payload)
        elif chunk_type == b"PLTE": palette_body = payload
        elif chunk_type == b"IEND": break
        cursor += 12 + ln
    if not header or not chunks: raise ValueError("PNG missing IHDR/IDAT")
    w, h, bd, ct, _c, _f, inter = header
    if bd != 8 or ct not in CHANNELS: raise ValueError("unsupported bd=%d ct=%d" % (bd, ct))
    if inter != 0: raise ValueError("interlaced PNG")
    nch, stride = CHANNELS[ct], w * CHANNELS[ct]
    stream = zlib.decompress(b"".join(chunks))
    if len(stream) < (stride + 1) * h: raise ValueError("truncated PNG data")
    prior, lines, cursor = bytearray(stride), [], 0
    for _y in range(h):
        ft, cursor = stream[cursor], cursor + 1
        scanline, cursor = bytearray(stream[cursor:cursor + stride]), cursor + stride
        if ft > 4: raise ValueError("bad PNG filter %d" % ft)
        if ft:
            for i in range(nch, stride):
                a = scanline[i - nch] if i >= nch else 0
                b, comp2 = prior[i], (prior[i - nch] if i >= nch else 0)
                if ft == 1: add = a
                elif ft == 2: add = b
                elif ft == 3: add = (a + b) >> 1
                else:
                    pp = a + b - comp2
                    pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - comp2)
                    add = a if pa <= pb and pa <= pc else (b if pb <= pc else comp2)
                scanline[i] = (scanline[i] + add) & 255
        lines.append(scanline)
        prior = scanline
    def rgb(scanline):
        if ct == 2: return bytearray(scanline)
        if ct == 6: return bytearray(b for x in range(w) for b in scanline[4 * x:4 * x + 3])
        if ct in (0, 4):
            st = 1 if ct == 0 else 2
            return bytearray(v for x in range(w) for v in (scanline[st * x],) * 3)
        if not palette_body: raise ValueError("no PLTE chunk")
        return bytearray(b for x in range(w) for b in palette_body[3 * scanline[x]:3 * scanline[x] + 3])
    return {"w": w, "h": h, "rows": [rgb(scanline) for scanline in lines]}


def open_raster(p):
    """Decode a raster into RGB scanlines, strided down when the image is large."""
    flavour = magic_kind(p)
    if flavour != "png": raise ValueError("no stdlib decoder for kind=%s (PNG only)" % flavour)
    raster = decode_png(p)
    w, h, scale = raster["w"], raster["h"], 1
    if w * h > MAX_PIXELS:
        scale = int(math.ceil(math.sqrt(w * h / MAX_PIXELS)))
        lines = []
        for y in range(0, h, scale):
            src, r = raster["rows"][y], bytearray()
            for x in range(0, w, scale): r += src[3 * x:3 * x + 3]
            lines.append(r)
        raster = {"w": len(lines[0]) // 3, "h": len(lines), "rows": lines}
    return raster, {"format": "png", "decoder": "stdlib zlib+unfilter", "orig_w": w,
                 "orig_h": h, "analysis_scale": scale, "analysis_w": raster["w"],
                 "analysis_h": raster["h"]}


def channel_gap(p, q):
    return max(abs(p[0] - q[0]), abs(p[1] - q[1]), abs(p[2] - q[2]))


def pixel_at(lines, y, x):
    i = 3 * x
    return (lines[y][i], lines[y][i + 1], lines[y][i + 2])


def canvas_rgb(raster):
    """Most common colour in a sparse sample, i.e. the canvas or paper tone."""
    from collections import Counter
    w, h, lines = raster["w"], raster["h"], raster["rows"]
    comp2, sx, sy = Counter(), max(1, w // 80), max(1, h // 80)
    for y in range(0, h, sy):
        for x in range(0, w, sx): comp2[pixel_at(lines, y, x)] += 1
    return tuple(comp2.most_common(1)[0][0])


def group_runs(vals, gap=1):
    report = []
    for v in sorted(vals):
        if report and v - report[-1][-1] <= gap: report[-1].append(v)
        else: report.append([v])
    return report


def ink_runs(raster, bg, horizontal=True, thr=60, min_frac=0.45):
    """Rows/columns crossed by long ink runs, grouped into candidate spines."""
    w, h, lines = raster["w"], raster["h"], raster["rows"]
    hits, outer, inner = [], h if horizontal else w, w if horizontal else h
    for o in range(outer):
        run = picked = 0
        for i in range(inner):
            p = pixel_at(lines, o, i) if horizontal else pixel_at(lines, i, o)
            if channel_gap(p, bg) > thr:
                run += 1
                picked = max(picked, run)
            else: run = 0
        if picked >= min_frac * inner: hits.append(o)
    return group_runs(hits)


def tick_marks(raster, bg, spine, box, axis="x", band=14, thr=60, min_dark=3):
    """Locate outward tick marks beside a spine and return cluster centres."""
    w, h, lines = raster["w"], raster["h"], raster["rows"]
    cursor = []
    if axis == "x":
        rng, lim = range(max(0, spine + 1), min(h, spine + band)), min(w, box[2] + 1)
        for x in range(box[0], lim):
            if sum(1 for y in rng if channel_gap(pixel_at(lines, y, x), bg) > thr) >= min_dark: cursor.append(x)
    else:
        rng, lim = range(max(0, spine - band), max(0, spine)), min(h, box[3] + 1)
        for y in range(box[1], lim):
            if sum(1 for x in rng if channel_gap(pixel_at(lines, y, x), bg) > thr) >= min_dark: cursor.append(y)
    return [sum(g) / len(g) for g in group_runs(cursor) if len(g) <= max(6, band)]


def gap_profile(comp2):
    """Describe tick-gap geometry: major spacing regularity and minor-gap trend."""
    gaps = [round(comp2[i + 1] - comp2[i], 2) for i in range(len(comp2) - 1)]
    if len(comp2) < 3:
        return {"n": len(comp2), "gaps": gaps, "uniform_major": None, "minor_gaps": [],
                "minor_pattern": "undetermined"}
    big, minor = max(gaps), [g for g in gaps if g <= 0.6 * max(gaps)]
    pat = "undetermined"
    if len(minor) >= 3:
        pat = "decreasing (log-decade style)" if minor[0] > minor[-1] * 1.3 else "even (linear style)"
    return {"n": len(comp2), "gaps": gaps,
            "uniform_major": (big - min(gaps)) <= 0.12 * big, "minor_gaps": minor,
            "minor_pattern": pat}


def colour_groups(raster, box, bg, thr=45, top=10, min_count=40):
    """Chromatic, non-background pixel groups found inside the plot box."""
    from collections import defaultdict
    w, lines = raster["w"], raster["rows"]
    accumulator = defaultdict(lambda: [0, 0, 0, 0])
    for y in range(box[1], min(box[3], raster["h"])):
        for x in range(box[0], min(box[2], w)):
            p = pixel_at(lines, y, x)
            if channel_gap(p, bg) <= thr or max(p) - min(p) < 42: continue  # skip bg/achromatic ink
            a = accumulator[(p[0] >> 5, p[1] >> 5, p[2] >> 5)]
            a[0] += 1
            a[1] += p[0]
            a[2] += p[1]
            a[3] += p[2]
    clusters = [{"rgb": [round(a[1] / a[0]), round(a[2] / a[0]), round(a[3] / a[0])],
           "pixels": a[0]} for _k, a in accumulator.items() if a[0] >= min_count]
    clusters.sort(key=lambda d: -d["pixels"])
    return clusters[:top]


def colour_mask(raster, color, tol=60, box=None):
    """Binary mask selecting one series colour inside the plot box."""
    w, h, lines = raster["w"], raster["h"], raster["rows"]
    x0, y0, x1, y1 = box or (0, 0, w, h)
    x1, y1 = min(x1, w), min(y1, h)
    mask = [bytearray(x1 - x0) for _ in range(max(0, y1 - y0))]
    for y in range(y0, y1):
        row = mask[y - y0]
        for x in range(x0, x1):
            p = pixel_at(lines, y, x)
            if abs(p[0] - color[0]) <= tol and abs(p[1] - color[1]) <= tol \
                    and abs(p[2] - color[2]) <= tol:
                row[x - x0] = 1
    return mask


def blobs(mask, min_px=12, max_px=60000):
    """8-connected components found with run merging plus a union-find table."""
    h, w = len(mask), len(mask[0]) if mask else 0
    lab = [[0] * w for _ in range(h)]
    par = []

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a

    for y in range(h):
        prow = lab[y - 1] if y else None
        x = 0
        while x < w:
            if not mask[y][x]:
                x += 1
                continue
            x2 = x
            while x2 < w and mask[y][x2]: x2 += 1
            nb = {find(prow[i]) for i in range(x, x2) if prow and prow[i]}
            if nb:
                idn = min(nb)
                for o in nb:
                    if o != idn: par[find(o)] = idn
            else:
                par.append(len(par)); idn = len(par) - 1
            for i in range(x, x2): lab[y][i] = idn
            x = x2
    bx = {}
    for y in range(h):
        for x in range(w):
            if not lab[y][x]: continue
            r = find(lab[y][x])
            b = bx.get(r)
            if b is None:
                bx[r] = [x, y, x, y, 1]
                continue
            b[0] = min(b[0], x); b[1] = min(b[1], y)
            b[2] = max(b[2], x); b[3] = max(b[3], y); b[4] += 1
    report = [{"bbox": b[:4], "w": b[2] - b[0], "h": b[3] - b[1], "pixels": b[4]}
           for b in bx.values() if min_px <= b[4] <= max_px]
    report.sort(key=lambda d: -d["pixels"])
    return report


def column_scan(mask, box):
    """Per-column mask extent, the raw material for a digitisation trace."""
    x0, y0, trace_pts = box[0], box[1], []
    for cx in range(len(mask[0]) if mask else 0):
        ys = [y for y in range(len(mask)) if mask[y][cx]]
        if ys:
            trace_pts.append({"x_px": x0 + cx, "y_px": y0 + sum(ys) / len(ys),
                        "y_top_px": y0 + min(ys), "y_bot_px": y0 + max(ys), "n_px": len(ys)})
    return trace_pts


def fit_scale(pixels, values, scale="auto"):
    """Least-squares pixel-to-value map; the slope is data units per pixel."""
    if len(pixels) > 2 and (values[-1] - values[0]) * (pixels[-1] - pixels[0]) < 0:
        pixels = list(reversed(pixels))  # values rise as pixels fall (y axes)
    samples = [(float(p), float(v)) for p, v in zip(pixels, values) if v is not None]
    if len(samples) < 2: return None
    candidates = []
    for sc in (["log"] if scale == "log" else
               ["linear"] if scale == "linear" else ["linear", "log"]):
        if sc == "log" and any(v <= 0 for _p, v in samples): continue
        ts = [math.log10(v) if sc == "log" else v for _p, v in samples]
        n, mp, mt = len(samples), sum(p[0] for p in samples) / len(samples), sum(ts) / len(ts)
        sxx = sum((p[0] - mp) ** 2 for p in samples)
        if sxx == 0: continue
        a = sum((samples[i][0] - mp) * (ts[i] - mt) for i in range(n)) / sxx
        b = mt - a * mp
        ss = sum((ts[i] - (a * samples[i][0] + b)) ** 2 for i in range(n))
        tot = sum((t - mt) ** 2 for t in ts)
        r2 = 1 - ss / tot if tot > 0 else (1.0 if ss == 0 else 0.0)
        deviations = [abs((10 ** (a * q[0] + b) if sc == "log" else a * q[0] + b) - q[1]) / abs(q[1])
                for q in samples if q[1]]
        candidates.append({"scale": sc, "slope": a, "intercept": b, "r2": round(r2, 6),
                       "max_rel_dev": round(max(deviations), 6) if deviations else None,
                       "value_per_px": round(abs(a), 8) if sc == "linear" else None,
                       "px_decade": round(abs(1 / a), 2) if sc == "log" else None})
    if not candidates: return None
    candidates.sort(key=lambda d: (d["max_rel_dev"] if d["max_rel_dev"] is not None else 1, -d["r2"]))
    picked = dict(candidates[0])
    picked["alternatives"] = [{k: t[k] for k in ("scale", "r2", "max_rel_dev")} for t in candidates[1:]]
    picked["ambiguous"] = bool(len(candidates) > 1 and candidates[1]["r2"] >= 0.9995
                             and (candidates[1]["max_rel_dev"] or 0) <= 0.01)
    if picked["ambiguous"]:
        picked["ambiguity_note"] = "linear and log fits indistinguishable; use printed labels"
    return picked


def pixel_to_value(comp2, v):
    y = comp2["slope"] * v + comp2["intercept"]
    return 10 ** y if comp2["scale"] == "log" else y


def round_sig(x, n=4):
    if x is None or x == 0: return x
    return round(x, -int(math.floor(math.log10(abs(x)))) + (n - 1))


def series_from_pixels(raster, box, color, cal_x, cal_y, scale=1, tol=60, max_rows=3000):
    """Trace one colour-isolated curve and map it through the fitted calibrations."""
    trace_pts = column_scan(colour_mask(raster, color, tol=tol, box=box), box)
    if not trace_pts: return []
    keep, lines = max(1, len(trace_pts) // max_rows), []
    for k, q in enumerate(trace_pts):
        if k % keep: continue
        yt = pixel_to_value(cal_y, q["y_top_px"]) if cal_y else None
        yb = pixel_to_value(cal_y, q["y_bot_px"]) if cal_y else None
        lines.append({"x": round_sig(pixel_to_value(cal_x, q["x_px"])) if cal_x else None,
                     "y": round_sig(pixel_to_value(cal_y, q["y_px"])) if cal_y else None,
                     "y_lo": round_sig(min(yt, yb)) if yb is not None else None,
                     "y_hi": round_sig(max(yt, yb)) if yb is not None else None,
                     "x_px": round(q["x_px"], 1), "y_px": round(q["y_px"], 1),
                     "px_thickness": q["n_px"], "approx": True,
                     "err_x_data": round_sig(0.5 * scale * abs(cal_x["slope"])) if cal_x else None,
                     "err_y_data": round_sig(0.5 * scale * abs(cal_y["slope"])) if cal_y else None})
    return lines


def inspect_image(p):
    """Inspect one raster figure and return structural facts; never raises."""
    report = {"file": str(p), "sha256": file_digest(p), "kind": magic_kind(p), "plot_box_px": None,
           "spines_px": {}, "ticks_px": {}, "spacing": {}, "color_clusters": [],
           "legend_candidates": [], "annotation_candidates": [], "image_px": {},
           "analysis_scale": 1, "traceable": False, "warnings": []}
    try: raster, meta = open_raster(p)
    except Exception as e:
        report["warnings"].append("decode_failed")
        report["decode_error"] = "%s: %s" % (type(e).__name__, e)
        return report
    s = meta["analysis_scale"]
    report.update({"image_px": {"w": meta["orig_w"], "h": meta["orig_h"]}, "analysis_scale": s,
                "analysis_px": {"w": meta["analysis_w"], "h": meta["analysis_h"]}})
    bg = canvas_rgb(raster)
    report["background_rgb"] = list(bg)
    w, h = raster["w"], raster["h"]
    if w < 60 or h < 60:
        report["warnings"].append("raster_too_small")
        return report
    rl, clusters = ink_runs(raster, bg, True), ink_runs(raster, bg, False)
    report["horizontal_lines_px"] = [round(sum(g) / len(g) * s, 1) for g in rl][:12]
    report["vertical_lines_px"] = [round(sum(g) / len(g) * s, 1) for g in clusters][:12]
    if not rl or not clusters:
        report["warnings"].append("no_axis_frame_detected: photograph, schematic or unboxed plot")
        report["color_clusters"] = colour_groups(raster, (0, 0, w, h), bg)
        return report
    rw, ybot, xl = raster["rows"], max(g[-1] for g in rl), min(g[0] for g in clusters)
    yg = [g for g in rl if g[-1] < ybot - 5]
    xg = [g for g in clusters if g[0] > xl + 5]
    ytop = min(g[0] for g in yg) if yg else next(
        (y for y in range(h) if channel_gap(pixel_at(rw, y, xl), bg) > 60), 0)
    xr = max(g[-1] for g in xg) if xg else max(
        (x for x in range(w) if channel_gap(pixel_at(rw, ybot, x), bg) > 60), default=w - 1)
    box = (xl, ytop, xr, ybot)
    report["plot_box_px"] = [round(v * s, 1) for v in box]
    report["spines_px"] = {"left": round(xl * s, 1), "bottom": round(ybot * s, 1),
                        "top": round(ytop * s, 1), "right": round(xr * s, 1)}
    xt, yt = tick_marks(raster, bg, ybot, box, "x"), tick_marks(raster, bg, xl, box, "y")
    report["ticks_px"] = {"x": [round(comp2 * s, 1) for comp2 in xt],
                       "y": [round(comp2 * s, 1) for comp2 in yt],
                       "x_wide": [round(comp2 * s, 1) for comp2 in tick_marks(raster, bg, ybot, box, "x", band=26)]}
    report["spacing"] = {"x": gap_profile(xt), "y": gap_profile(yt)}
    report["color_clusters"] = colour_groups(raster, box, bg)
    swatch_list = []
    for comp2 in report["color_clusters"][:8]:
        for blob in blobs(colour_mask(raster, comp2["rgb"], tol=55, box=box), 40, 20000):
            bw, bh = blob["w"], blob["h"]
            if bh <= max(3, 2 * s) and 6 <= bw <= 90 and bw >= 2 * bh:
                b = blob["bbox"]
                swatch_list.append({"rgb": comp2["rgb"], "bbox": [b[0] + box[0], b[1] + box[1],
                                                    b[2] + box[0], b[3] + box[1]]})
    swatch_list.sort(key=lambda d: (d["bbox"][1], d["bbox"][0]))
    legend_groups = []
    for d in swatch_list:
        for g in legend_groups:
            if abs(g[-1]["bbox"][0] - d["bbox"][0]) <= max(6, 3 * s) and \
                    d["bbox"][1] - g[-1]["bbox"][3] <= max(30, 8 * s):
                g.append(d)
                break
        else: legend_groups.append([d])
    for g in legend_groups:
        if len(g) < 2 or all(d["rgb"] == g[0]["rgb"] for d in g): continue
        xs = [d["bbox"][0] for d in g] + [d["bbox"][2] for d in g]
        ys = [d["bbox"][1] for d in g] + [d["bbox"][3] for d in g]
        report["legend_candidates"].append({
            "bbox_px": [round(min(xs) * s, 1), round(min(ys) * s, 1),
                        round(max(xs) * s, 1), round(max(ys) * s, 1)],
            "entries_top_to_bottom": [d["rgb"] for d in g], "n_entries": len(g),
            "read_basis": "swatch order"})
    report["traceable"] = True
    return report


# ------------------------------------------------- source text + tables
def pdf_strings(p, cap=300000):
  """Pull literal strings out of PDF content streams; no OCR or layout recovery."""
  try: stream = Path(p).read_bytes()
  except OSError: return ""
  report = []
  for mask in re.finditer(rb"stream\r?\n(.*?)endstream", stream, re.S):
    b = mask.group(1)
    try: b = zlib.decompress(b)
    except Exception: pass
    report += [re.sub(rb"\\([()\\])", rb"\1", t.group(0)[1:-1]).decode("latin-1")
            for t in re.finditer(rb"\((?:\\.|[^\\()])*\)", b)]
  return re.sub(r"\s+", " ", " ".join(report))[:cap]


# ------------------------------------------------------- table primitives


def rectify(g):
  w = max(len(r) for r in g)
  return [list(r) + [""] * (w - len(r)) for r in g]


def csv_to_table(p):
  stream = Path(p).read_text(encoding="utf-8-sig", errors="replace")
  prefix = stream[:4000]
  d = "," if prefix.count(",") >= max(prefix.count(";"), prefix.count("\t")) else \
      ";" if prefix.count(";") >= prefix.count("\t") else "\t"
  g = [r for r in csv.reader(io.StringIO(stream), delimiter=d) if any(str(comp2).strip() for comp2 in r)]
  return {"format": "csv", "delimiter": d, "columns": g[0] if g else [], "rows": g[1:],
          "grid": g, "n_rows": max(0, len(g) - 1)}


def json_inline_tables(o, path_expr="$"):
  """Tabular arrays literally present inside JSON documents count as real tables."""
  report = []
  if isinstance(o, dict):
    tid = next((o[k] for k in o if k.lower() in ("table_id", "label") and isinstance(o[k], str)), None)
    for k, v in o.items():
      if isinstance(v, list) and v and all(isinstance(r, list) for r in v) and \
          all(all(not isinstance(x, (list, dict)) for x in r) for r in v):
        g = rectify([[str(x) for x in r] for r in v])
        report.append({"table_id": tid or k, "json_pointer": "%s/%s" % (path_expr, k), "columns": g[0],
                    "rows": g[1:], "grid": g, "n_rows": len(g) - 1, "format": "json-inline"})
      else: report += json_inline_tables(v, "%s/%s" % (path_expr, k))
  elif isinstance(o, list):
    for i, v in enumerate(o): report += json_inline_tables(v, "%s/%d" % (path_expr, i))
  return report


def walk_files(root, cap=400):
  return [p for p in sorted(root.rglob("*")) if p.is_file() and not any(
      x.startswith(".") for x in p.relative_to(root).parts)][:cap]
