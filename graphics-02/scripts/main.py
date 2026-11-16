#!/usr/bin/env python3
"""source-anchored-charts - turn a case data table into an editable, source-anchored figure.

Flow: read the workorder and the table, bind values to columns, derive one data-to-mark
model, draw a layered SVG, render PDF/PNG previews, then write result.json with a per-mark
locator and the audit block. Standard library only; independent of the current directory."""
import argparse, hashlib, json, math, os, re, sys, time, traceback
from pathlib import Path
from xml.sax.saxutils import escape
sys.path.insert(0, str(Path(__file__).resolve().parent))
import chartkit as K

FONT_STACK = "Helvetica, Arial, 'Noto Sans CJK SC', 'DejaVu Sans', sans-serif"
STATE = {}
EMPTY_MAP = {"chart": None, "series": [], "axes": [], "legend": [], "coverage": {"required": 0, "mapped": 0, "missing": []}}


def add_exception(c, found, sev="warn", act=""):
    STATE["exceptions"].append({"code": c, "detail": found, "severity": sev, "action": act})


def assemble_model(bound, wo_spec, table):
    headers, chart = table["headers"], K.chart_kind(wo_spec, bound)
    categories = []
    for s in bound["ser"]:
        categories += [p["x"] for p in s["p"] if p["x"] not in categories]
    if chart != "bar" and not bound["xc"]:
        xs = []
        for s in bound["ser"]:
            for p in s["p"]:
                p["xn"] = K.to_number(p["x"])[0]
                xs += [p["xn"]] if p["xn"] is not None else []
        categories = sorted(set(xs)) or categories
    values = [p["v"] for s in bound["ser"] for p in s["p"]]
    if not values:
        raise ValueError("table " + table["file"] + " carries no numeric cell")
    use_log = wo_spec["ysc"].startswith("log") and any(v > 0 for v in values)
    if wo_spec["ysc"].startswith("log") and not use_log:
        add_exception("log_axis_no_positive", "the workorder asks for a log scale but every bound value is "
           "non-positive", "warn", "axis drawn as linear")
    if use_log:
        y_lo, y_hi, tick_values = K.decade_ticks(min(v for v in values if v > 0), max(values))
    else:
        v0, v1 = min(values), max(values)
        y_lo, y_hi, tick_values = K.linear_ticks(0. if (chart == "bar" and v0 >= 0) else min(v0, 0.), max(v1, 0.))
    if isinstance(wo_spec["ylim"], (list, tuple)) and len(wo_spec["ylim"]) == 2:
        y_lo, y_hi = float(wo_spec["ylim"][0]), float(wo_spec["ylim"][1])
    y_hi = y_hi if y_hi > y_lo else y_lo + 1.
    tick_values = [t for t in tick_values if y_lo - 1e-9 <= t <= y_hi + 1e-9] or [y_lo, y_hi]
    series_out, legend_out = [], []
    for si, s in enumerate(bound["ser"]):
        ps, sid = [], f"s{si + 1}"
        for pdf_info, p in enumerate(s["p"]):
            r = p["row"]
            q = {"id": f"{sid}-p{pdf_info + 1}", "x": p["x"], "yr": p["r"], "y": p["v"], "cat": bound["xc"],
                 "src": {"file": table["file"], "sheet": table["sheet"], "row": r["row"], "col": column_letter(p["c"]),
                         "col_index": p["c"], "header": headers[p["c"]], "x_header": headers[bound["xi"]],
                         "x_col": column_letter(bound["xi"]), "quote": r["line"]}}
            if p.get("xn") is not None:
                q["xn"] = p["xn"]
            if s["c"] in bound["errs"]:
                ec, er = bound["errs"][s["c"]], r["cells"][bound["errs"][s["c"]]]
                ev, ek = K.to_number(er)
                q.update(eraw=er, err=ev, emode=wo_spec["em"] or "as reported in the source",
                         esrc={"file": table["file"], "sheet": table["sheet"], "row": r["row"], "col": column_letter(ec),
                               "header": headers[ec], "quote": r["line"]})
                if ek != "ok":
                    add_exception("error_value_unparsable", f"row {r['row']} err={er!r}", "info", "bar omitted")
            ps.append(q)
        series_out.append({"id": sid, "name": s["n"], "unit": s["u"] or "", "column": headers[s["c"]],
                    "color": K.SERIES_COLORS[si % 8], "marker": K.SERIES_MARKERS[si % 8], "points": ps})
        legend_out.append({"id": "legend-" + sid, "series_id": sid, "label": s["n"], "color": K.SERIES_COLORS[si % 8]})
    yu = wo_spec["yu"] or series_out[0]["unit"]
    if not yu:
        add_exception("unit_unknown", "neither the column header nor the workorder states a y unit", "warn",
           "axis text becomes 'unit not reported'; nothing is guessed")
    return {"chart_type": chart, "title": wo_spec["ti"] or "",
            "axes": {"x": {"label": bound["xl"], "unit": bound["xu"] or "",
                           "scale": "category" if bound["xc"] else "linear", "categories": categories,
                           "source": {"header": headers[bound["xi"]], "col": column_letter(bound["xi"])}},
                     "y": {"label": wo_spec["yl"] or series_out[0]["column"], "unit": yu, "scale": "log" if use_log else "linear",
                           "min": y_lo, "max": y_hi, "ticks": tick_values,
                           "source": {"header": series_out[0]["column"], "note": "from header/workorder"}}},
            "series": series_out, "legend": legend_out,
            "source_table": {"file": table["file"], "sheet": table["sheet"], "header_row": table["header_row"],
                             "data_rows": len(table["rows"]), "headers": headers}}


def cli_args(argv):
    ap = argparse.ArgumentParser(prog="source-anchored-charts",
                                 description="Source-anchored data chart: workorder + source table -> "
                                             "chart_model.json -> editable layered SVG with PDF/PNG "
                                             "renders -> result.json.")
    ap.add_argument("--input", help="case folder holding case.json, task.md and the source table (default: /input when it exists, otherwise ./input)")
    ap.add_argument("--output", help="folder that receives result.json and the chart artifacts (default: /app/output when /app exists, otherwise ./output)")
    ap.add_argument("--style", help="typographic preset: journal | nature | thesis | presentation | default")
    ap.add_argument("--version", action="store_true", help="show the package version and exit 0")
    opts = ap.parse_args(argv)
    opts.input = opts.input or ("/input" if Path("/input").is_dir() else str(Path.cwd() / "input"))
    opts.output = opts.output or ("/app/output" if Path("/app").is_dir() else str(Path.cwd() / "output"))
    return opts


def column_letter(i):
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def draw_svg(model, sty, cw, ch):
    s, yaxis = K.preset_for(sty), model["axes"]["y"]
    use_log, y_lo, y_hi, categories = yaxis["scale"] == "log", yaxis["min"], yaxis["max"], model["axes"]["x"]["categories"]
    x0, y0 = max(48., s["f"] * 5.2), 26 + (14 if model["title"] else 0) + (16 if model["legend"] else 0)
    x1, y1 = cw - 18, ch - max(40., s["f"] * 3.4)
    L = {k: [] for k in ("background", "title", "axes", "data", "error", "legend", "labels")}
    L["background"].append(f'<rect id="canvas-bg" x="0" y="0" width="{cw:g}" height="{ch:g}" fill="#ffffff"/>')
    if model["title"]:
        L["title"].append(K.text_node("figure-title", cw / 2, 18, s["ti"], model["title"], e=' font-weight="bold"'))
    yl = yaxis["label"] or ""
    yl = f"{yl} ({yaxis['unit']})" if yaxis["unit"] else yl + " (unit not reported)"
    xl, xu = model["axes"]["x"]["label"] or "", model["axes"]["x"]["unit"]
    xl = (f"{xl} ({xu})" if xl else xu) if (xu and xu not in xl) else xl
    L["axes"] += [K.line_node("axis-y", x0, y0, x0, y1, "#111111", s["axl"]), K.line_node("axis-x", x0, y1, x1, y1, "#111111", s["axl"])]
    for ti, tv in enumerate(yaxis["ticks"]):
        yy = K.y_coord(tv, y_lo, y_hi, y0, y1, use_log)
        if yy is None or not (y0 - .5 <= yy <= y1 + .5):
            continue
        L["axes"] += [K.line_node(f"ytick-{ti}", x0 - 3, yy, x0, yy, "#111111", s["axl"]),
                      K.text_node(f"yticklabel-{ti}", x0 - 5, yy + s["s"] * .35, s["s"], K.tick_text(tv), "end")]
    band = (x1 - x0) / max(1, len(categories))
    rot = any(K.approx_width(c, s["s"]) > 46 for c in categories)
    for ci, ct in enumerate(categories):
        cx = x0 + (ci + .5) * band
        L["axes"].append(K.text_node(f"xtick-{ci}", cx + (2 if rot else 0), y1 + (6 if rot else 12), s["s"], ct,
                            "end" if rot else "middle",
                            f' transform="rotate(-35 {cx + 2:.2f} {y1 + 6:.2f})"' if rot else ""))
    yx = max(12., x0 - 34)
    L["labels"] += [K.text_node("label-yaxis", yx, (y0 + y1) / 2, s["f"], yl,
                       e=f' transform="rotate(-90 {yx:.2f} {(y0 + y1) / 2:.2f})"'),
                    K.text_node("label-xaxis", (x0 + x1) / 2, y1 + (34 if rot else 26), s["f"], xl)]
    bv = max(y_lo, 0.) if y_lo <= 0 <= y_hi else y_lo
    base = K.y_coord(bv, y_lo, y_hi, y0, y1, use_log)
    base = y1 if base is None else base
    slot = (band * (1 - s["bg"])) / max(1, len(model["series"]))
    for si, sr in enumerate(model["series"]):
        for p in sr["points"]:
            ci = categories.index(p["x"]) if p["x"] in categories else 0
            yy = K.y_coord(p["y"], y_lo, y_hi, y0, y1, use_log)
            if yy is None:
                add_exception("value_off_log_axis", f"mark {p['id']} value={p['yr']!r} cannot sit on a log axis",
           "info", "mark skipped")
                continue
            g = {"id": p["id"], "kind": model["chart_type"], "y_px": round(yy, 2), "pt": y0, "pb": y1}
            if model["chart_type"] == "bar":
                bx = x0 + ci * band + s["bg"] * band / 2 + si * slot + slot * s["gg"] / 2
                bw, t = max(1., slot * (1 - s["gg"])), min(yy, base)
                L["data"].append(f'<rect id="bar-{p["id"]}" class="mark" x="{bx:.2f}" y="{t:.2f}" width="{bw:.2f}" '
                                 f'height="{abs(base - yy):.2f}" fill="{sr["color"]}"/>')
                g.update(x_px=round(bx, 2), w_px=round(bw, 2), top=round(t, 2), h=round(abs(base - yy), 2),
                         base=round(base, 2), bv=bv)
            else:
                cx = x0 + (ci + .5) * band
                if p.get("xn") is not None and len(categories) > 1 and isinstance(categories[0], (int, float)):
                    cx = x0 + (p["xn"] - categories[0]) / ((categories[-1] - categories[0]) or 1) * (x1 - x0)
                L["data"].append(f'<circle id="pt-{p["id"]}" class="mark" cx="{cx:.2f}" cy="{yy:.2f}" '
                                 f'r="{max(1.6, s["f"] * .24):g}" fill="{sr["color"]}" stroke="#ffffff" stroke-width="0.5"/>')
                g.update(x_px=round(cx, 2))
            if p.get("err") is not None:
                e = abs(p["err"])
                yt, yb = K.y_coord(p["y"] + e, y_lo, y_hi, y0, y1, use_log), K.y_coord(p["y"] - e, y_lo, y_hi, y0, y1, use_log)
                if yt is None or yb is None:
                    add_exception("error_bar_off_axis", f"error span of {p['id']} leaves the axis range",
                       "info", "error bar skipped")
                else:
                    yt, yb = max(y0, min(y1, yt)), max(y0, min(y1, yb))
                    xc = g.get("x_px", 0) + (g.get("w_px", 0) / 2 if g["kind"] == "bar" else 0)
                    L["error"] += [K.line_node("err-" + p["id"], xc, yt, xc, yb, "#111111", s["axl"]),
                                   K.line_node("errc-" + p["id"], xc - 3, yt, xc + 3, yb, "#111111", s["axl"])]
                    g.update(et=round(yt, 2), eb=round(yb, 2))
            p["g"] = g
    lx, ly = 16., 29.
    for it in model["legend"]:
        w = 16 + K.approx_width(it["label"], s["s"])
        if lx + w > cw - 16:
            lx, ly = 16., ly + 14
        sw = (f'<rect id="{it["id"]}-swatch" x="{lx:.2f}" y="{ly - 8:.2f}" width="9" height="8" fill="{it["color"]}"/>'
              if model["chart_type"] == "bar" else
              f'<circle id="{it["id"]}-swatch" cx="{lx + 4:.2f}" cy="{ly - 4:.2f}" r="3.4" fill="{it["color"]}"/>')
        L["legend"].append(sw + K.text_node(it["id"] + "-text", lx + 13, ly - 1, s["s"], it["label"], "start"))
        it["xy"] = [round(lx, 1), round(ly, 1)]
        lx += w + 14
    body = "\n".join(f' <g id="layer-{k}">\n  ' + "\n  ".join(L[k]) + "\n </g>"
                     for k in ("background", "title", "axes", "data", "error", "legend", "labels") if L[k])
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
            f'width="{model["canvas"]["w_mm"]:.2f}mm" height="{model["canvas"]["h_mm"]:.2f}mm" viewBox="0 0 {cw:g} {ch:g}" '
            f'font-family="{FONT_STACK}">\n <title>{escape(model["title"] or "scientific data chart")}</title>\n'
            f' <desc>Editable chart from {escape(model["source_table"]["file"])}; text stays live, mark ids map to '
            f'content_map.</desc>\n{body}\n</svg>\n')


def dump_json(p, o):
    t = Path(str(p) + ".tmp")
    t.write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(t, p)


def entry(argv=None):
    opts = cli_args(sys.argv[1:] if argv is None else argv)
    if opts.version:
        print("source-anchored-charts 1.0.0 (stdlib only)")
        return 0
    try:
        return pipeline(opts)
    except Exception:  # never leave without a legal result.json
        outdir = Path(opts.output)
        outdir.mkdir(parents=True, exist_ok=True)
        rp = outdir / "result.json"
        try:
            cur = json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            cur = {"case_id": "unknown"}
        cur["status"] = "partial"
        cur.setdefault("errors", []).append("unhandled:" + traceback.format_exc()[-300:])
        for k in ("exceptions", "pending_human", "degradations", "sources", "uncertainty", "changes"):
            cur.setdefault(k, [])
        for k in ("editable_source", "export_artifact", "content_map", "compliance_checks"):
            cur.setdefault(k, None)
        cur["pending_human"].append("pipeline raised an exception; read the errors list")
        try:
            dump_json(rp, cur)
        except Exception:
            pass
        return 0


def pipeline(opts):
    t0 = time.time()
    indir, outdir = Path(opts.input).resolve(), Path(opts.output).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    STATE.update(outdir=str(outdir), case_id="unknown", status="partial", contract={}, sources=[], errors=[],
             degradations=[], exceptions=[], pending_human=[], changes=[], uncertainty=[], instruction="",
             log=[], runtime={"python": sys.version.split()[0], "budget": "900 s / 64 requests"})
    K.emit_result(STATE, outdir)
    if not indir.is_dir():
        STATE.update(status="input_error", errors=["input_dir_missing"])
        STATE["pending_human"].append("put case.json and the source table inside the input folder")
        return K.emit_result(STATE, outdir)
    found = K.scan_inputs(indir)
    case_obj = found["case"] if isinstance(found["case"], dict) else {}
    STATE["case_id"] = case_obj.get("case_id") or case_obj.get("id") or "unknown"
    STATE["contract"] = case_obj.get("output_contract") or {}
    STATE["instruction"] = str(case_obj.get("task_instruction") or case_obj.get("instruction") or "")
    STATE["sources"] = [{"kind": "case_json", "path": found["cp"]},
                    {"kind": "task_md", "path": str(indir / "task.md") if (indir / "task.md").exists() else None}]

    for e in found["cerr"]:
        STATE["errors"].append(e)
        STATE["degradations"].append("case.json unreadable; continued from the directory scan")
    wo_spec = K.workorder_spec(found["wo"])
    wo_spec["st"] = opts.style or wo_spec["st"]
    if found["wo"]:
        STATE["changes"].append({"step": "workorder_in", "detail": f"keys: {sorted(found['wo'])[:10]}"})
    tables = []
    for p in found["tables"]:
        try:
            for t in K.open_table(p):
                t["path"] = str(p)
                tables.append(t)
        except Exception as e:
            STATE["errors"].append(f"table_read_failed:{p.name}:{str(e)[:60]}")
    STATE["sources"] += [{"kind": "data_table", "path": t["path"], "file": t["file"], "sheet": t["sheet"],
                      "rows": len(t["rows"])} for t in tables]
    if not tables:
        STATE["errors"].append("no_parsable_data_table")
        STATE.update(status="insufficient_evidence", content_map=EMPTY_MAP,
                 compliance_checks={"pass": False, "failures": ["no_source_table"]}, export_artifact={})
        STATE["pending_human"].append("supply the source table as CSV, TSV or XLSX")
        return K.emit_result(STATE, outdir)
    table = None
    if wo_spec["tb"]:
        b = str(wo_spec["tb"]).lower()
        table = next((t for t in tables if t["file"].lower() in b or b in t["file"].lower()), None)
    table = table or max(tables, key=lambda t: 2 * sum(K.to_number(c)[1] == "ok" for r in t["rows"] for c in r["cells"])
                   + len(t["rows"]))
    try:
        bound = K.bind_columns(table, wo_spec)
        if not bound["ser"]:
            raise ValueError("no numeric series resolved")
        model = assemble_model(bound, wo_spec, table)
    except Exception as e:
        STATE["errors"].append(f"model_build_failed:{str(e)[:130]}")
        STATE.update(status="insufficient_evidence", content_map=EMPTY_MAP,
                 export_artifact={}, compliance_checks={"pass": False, "failures": ["model_build_failed"]})
        STATE["pending_human"].append("column binding unresolved: compare workorder fields with the header row")
        return K.emit_result(STATE, outdir)
    for c, d_, act in bound["issues"]:
        add_exception(c, d_, "warn", act)
    for w in wo_spec.get("warn", []):
        add_exception("chart_type_unsupported", w, "warn", "bars drawn instead")
    cw = round(wo_spec["wm"] * 96 / 25.4, 2)
    hm = wo_spec["hm"] or round(wo_spec["wm"] * .62, 1)
    ch = round(float(hm) * 96 / 25.4, 2)
    model["canvas"] = {"w_px": cw, "h_px": ch, "w_mm": round(wo_spec["wm"], 2), "h_mm": round(float(hm), 2), "dpi": wo_spec["dpi"]}
    svg_text = draw_svg(model, wo_spec["st"] or "journal", cw, ch)
    (outdir / "chart.svg").write_bytes(svg_text.encode("utf-8"))
    dump_json(outdir / "chart_model.json", model)
    pdf_engine = K.render_pdf(str(outdir / "chart.svg"), str(outdir / "chart.pdf"), STATE["log"])
    if pdf_engine is None:
        STATE["degradations"].append("pdf: no vector renderer succeeded (rsvg-convert / soffice / browser)")
    pdf_info = K.probe_pdf(outdir / "chart.pdf")
    png_engine = K.rasterize_png(str(outdir / "chart.pdf"), str(outdir / "chart.png"), wo_spec["dpi"], STATE["log"]) \
        if pdf_info.get("header_ok") else None
    if png_engine is None:
        png_engine = K.browser_png(str(outdir / "chart.svg"), str(outdir / "chart.png"),
                                   wo_spec["dpi"], STATE["log"], cw, ch)
    if png_engine is None:
        STATE["errors"].append("png_export_failed:no rasteriser produced chart.png")
    png_info = K.probe_png(outdir / "chart.png")
    try:
        value_map, geo_audit, legend_audit = K.build_mark_map(model), K.audit_geometry(model), K.audit_legend(model)
    except Exception as e:
        add_exception("check_failed", str(e)[:80], "warn", "raw geometry survives in chart_model.json")
        value_map, geo_audit, legend_audit = {"series": [], "axes": [], "legend": [], "coverage": {"required": 0, "mapped": 0,
                      "missing": []}}, {"ok": False, "checked": 0}, {"ok": False}
    failures = [n for b, n in ((not legend_audit["ok"], "legend_series_mismatch"), (not geo_audit["ok"], "geometry_mismatch"),
                            (value_map["coverage"]["mapped"] != value_map["coverage"]["required"], "coverage_incomplete"),
                            (png_info.get("ink_present") is False, "png_blank"), (not pdf_info.get("header_ok"), "pdf_missing"))
             if b]
    marks = [(p["id"], (p.get("g") or {}).get("kind") == "bar")
             for sr in model["series"] for p in sr["points"] if p.get("g")]
    lost = [pid for pid, is_bar in marks
            if (('id="bar-%s"' % pid) if is_bar else ('id="pt-%s"' % pid)) not in svg_text]
    mark_audit = {"expected": len(marks), "found_in_svg": len(marks) - len(lost),
                  "missing": lost[:5], "ok": not lost}
    if not mark_audit["ok"]:
        failures.append("mark_id_missing")
    long_labels = [c for c in model["axes"]["x"]["categories"] if K.approx_width(c, 6.5) > 90]
    layer_ids = re.findall(r'<g id="(layer-[^"]+)"', svg_text)
    audit = {"canvas": {"width_mm": model["canvas"]["w_mm"], "height_mm": model["canvas"]["h_mm"],
                         "width_px": cw, "height_px": ch, "dpi": wo_spec["dpi"]},
              "fonts": {"family": FONT_STACK, "cjk_in_figure": K.contains_cjk(svg_text), "text_elements": svg_text.count("<text"),
                        "text_kept_as_text": True},
              "line_widths": {k: K.preset_for(wo_spec["st"] or "journal")[k] for k in ("lw", "axl", "gl")},
              "colors": {"palette": [x["color"] for x in model["series"]], "distinct": legend_audit["distinct_colors"]},
              "legend_consistency": legend_audit, "geometry_roundtrip": geo_audit, "content_coverage": value_map["coverage"],
              "canvas_overflow": {"x_labels_rotated": bool(long_labels), "layers": layer_ids},
              "mark_id_audit": mark_audit,
              "png": png_info, "pdf": pdf_info, "pass": not failures, "failures": failures}
    STATE.update(content_map=value_map, compliance_checks=audit)
    STATE["editable_source"] = {"path": "chart.svg", "format": "svg", "editable": True, "layers": layer_ids,
                            "text_count": svg_text.count("<text"), "element_count": len(re.findall(r'id="', svg_text)),
                            "sha256": hashlib.sha256(svg_text.encode()).hexdigest(),
                            "bytes": (outdir / "chart.svg").stat().st_size, "viewBox": f"0 0 {cw:g} {ch:g}",
                            "text_selectable": True, "model": "chart_model.json"}
    STATE["editable_source"]["layer_count"] = len(layer_ids)
    STATE["export_artifact"] = {"svg": "chart.svg",
                            "pdf": {"path": "chart.pdf", "engine": pdf_engine, "pages": pdf_info.get("pages"),
                                    "vector": bool(pdf_info.get("header_ok")), "mediabox_pt": pdf_info.get("mediabox_pt"),
                                    "bytes": pdf_info.get("bytes")},
                            "png": {"path": "chart.png", "engine": png_engine, "width": png_info.get("width"),
                                    "height": png_info.get("height"), "dpi": wo_spec["dpi"], "color_type": png_info.get("color_type"),
                                    "mean_level": png_info.get("mean_level"), "bytes": png_info.get("bytes")}}
    STATE["pending_human"] += [f"{e['code']}: {e['detail']}" for e in STATE["exceptions"]
                          if e["code"] in ("unit_unknown", "error_column_missing", "column_not_found")]
    STATE["uncertainty"] = [{"item": "chart_type", "note": "from workorder" if wo_spec["t"] else "inferred from table shape"},
                        {"item": "units/statistics", "note": "units copied from source, statistics transmitted not computed"}]
    STATE["changes"] += [{"step": "bind", "detail": f"x={table['headers'][bound['xi']]} y={[x['column'] for x in model['series']]}"},
                     {"step": "render_export", "detail": f"{cw:.1f}x{ch:.1f}px {wo_spec['st'] or 'journal'} pdf={pdf_engine} png={png_engine}"}]
    STATE["status"] = "ok" if (audit["pass"] and not STATE["degradations"] and not STATE["errors"]) else "partial"
    STATE["runtime"]["elapsed_s"] = round(time.time() - t0, 2)
    return K.emit_result(STATE, outdir)


if __name__ == "__main__":
    sys.exit(entry())
