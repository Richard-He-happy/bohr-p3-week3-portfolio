---
name: source-anchored-charts
description: Build a publication-ready scientific figure whose every graphical mark is traceable to an exact cell of the case's own data table, and ship it as an editable layered SVG together with real PDF/PNG renders. Use when a case supplies a data table plus a drawing workorder (bar, grouped bar, long-format series, line, scatter) and demands verifiable data-to-mark provenance, faithful axis labels and units, legend/series agreement, and reproducible output rather than decorative styling.
version: 1.0.0
---

# source-anchored-charts

This package turns a case table into a figure that can be defended line by line: **cell → value →
mark geometry → rendered pixel/vector**, with every hop recorded in `result.json`. The package is
pure Python standard library; nothing is installed or downloaded at run time.

## 1. What is inside the scope

In scope: locating and parsing the case table (CSV / TSV / XLSX), resolving workorder fields onto
header names, splitting units out of headers, computing bar heights, point positions and error-bar
extents, applying a typographic preset, generating axis labels, ticks and legend, authoring an
editable layered SVG (all labels remain `<text>`), rendering PDF and PNG previews, and emitting a
point-level locator map plus a machine-readable audit block.

Deliberately out of scope: statistical method choice, significance testing, *computing* error
values, and experimental design. Error bars and significance information are **forwarded** from
source columns, never calculated here. Any entity name, unit or number that does not occur in the
case material is left absent and reported instead of being invented.

## 2. Calling the package

```bash
# container defaults: /input -> /app/output
python3 scripts/main.py

# explicit folders and a preset
python3 scripts/main.py --input /input --output /app/output --style nature

# usage text, exits 0
python3 scripts/main.py --help
```

| option | effect |
|---|---|
| `--input DIR` | folder with `case.json`, `task.md` and the source data table |
| `--output DIR` | folder receiving `result.json`, `chart.svg`, `chart.pdf`, `chart.png`, `chart_model.json` |
| `--style NAME` | one of `journal` (fallback), `nature`, `thesis`, `presentation`, `default` |
| `--version` | print `source-anchored-charts 1.0.0 (stdlib only)` |

When a flag is omitted the script looks for `/input` (else `./input`) and `/app/output` (else
`./output`). Folder resolution never depends on the process working directory, and the scripts
locate their sibling module through `Path(__file__).resolve().parent`.

Exit status is **always 0**. A syntactically valid `result.json` is written before the first risky
step and overwritten at the end; a crash is captured into `errors` and still leaves a legal
partial result behind.

## 3. Deliverables

| file | role |
|---|---|
| `chart.svg` | editable source: grouped `<g id="layer-…">` layers, live text nodes, mark ids match `content_map` |
| `chart.pdf` | vector export, one page, MediaBox = figure size |
| `chart.png` | raster preview at the requested dpi, 8-bit RGB |
| `chart_model.json` | the single intermediate model (canvas, series, points, geometry, axes, legend) that produced all of the above |
| `result.json` | the graded contract: status, editable source, exports, provenance map, audit block, exceptions |

The four chart files and `result.json` are written into `--output`; nothing else is required.

## 4. Reading the case folder

Resolution order, tolerant by construction:

1. `case.json` is primary; if it will not parse, any `case*.json` is tried, and the failure is
   logged to `errors` + `degradations` while the scan continues.
2. `case_id` is copied through untouched (falling back to `id`); `output_contract` is echoed at the
   root of `result.json`; `task_instruction` is quoted into `task.instruction`.
3. A drawing workorder is gathered from any key whose value is an object and whose name mentions
   `workorder`, and from any JSON file whose name mentions `workorder` or `figure`. The two sources
   are merged, so a separate `figure-workorder.json` works as well as an inline block.
4. All `.csv`, `.tsv`, `.tab`, `.xlsx`, `.xlsm` files under the input tree are attempted. The table
   named by `source_table_ref` wins when present; otherwise the table with the most numeric cells is
   picked.
5. With no readable table the package refuses to draw anything: `status=insufficient_evidence`,
   `pending_human` carries the gap, and `compliance_checks.failures=["no_source_table"]`.

Workorder key names are matched semantically — exact name first, then substring against the whole
workorder object. See `references/workorder-field-map.md` for the full alias table.

## 5. Pipeline in one pass

```
tables ──bind_columns──► series / points / issues          (header stem match for error columns)
       ──assemble_model──► chart_model.json                 (axes, ticks, colours, plot box)
       ──draw_svg──► chart.svg                             (layers, ids, text kept live)
       ──render_pdf──► chart.pdf                           (rsvg / soffice / headless browser)
       ──rasterize_png──► chart.png                        (pdftoppm / gs / headless browser)
       ──audits──► compliance_checks
       ──emit_result──► result.json
```

The audits are `audit_geometry` (pixel height back to value), `audit_legend` (legend items =
series = distinct colours), `mark_id_audit` (every mark id present exactly where the map claims),
plus artifact probes for PNG (`IHDR` magic, dimensions, colour type, ink present) and PDF
(`%PDF-` header, page count, MediaBox). They are computed into `compliance_checks` and never removed
if they fail — a failing audit turns `status` into `partial`.

## 6. Rules that make the figure checkable

- **Raw strings survive.** `y_raw` keeps the source cell verbatim (`"2.31"`, `"<0.01"`); the plotted
  number is parsed from that same string once. Nothing is rounded back into the provenance map.
- **Absent stays absent.** Empty cells, `NA`, `n.d.`, `-`, `not reported` and censored values
  (`<0.01`) are skipped and listed under `missing_value`; they are never drawn as zero.
- **Units are inherited, never guessed.** A header such as `Concentration (mg/L)` yields label
  `Concentration` and unit `mg/L`; without a unit the axis reads `unit not reported` and a
  `unit_unknown` exception is raised.
- **Colour follows the series.** Series are coloured in table order from a colour-blind-safe
  eight-colour set; the legend is generated from the same list, so ordering cannot drift.
- **Mark identity is deterministic.** ids look like `bar-s1-p3`, `pt-s2-p5`, `errt-s1-p3`,
  `xtick-2`, `legend-s1-text` and are identical across runs and across SVG / `content_map`.

## 7. result.json contract

`result.json` is emitted even when the build fails. Its root always exposes the slots below — a
slot with nothing to report stays present and null instead of disappearing:

- **identity** — `case_id` (copied from the case) and `status` (`ok`, `partial`,
  `insufficient_evidence` or `input_error`).
- **`editable_source`** — where the editable drawing lives and how to audit it: path, format,
  layer ids, number of text and element nodes, sha256, byte size, viewBox, model file name.
- **`export_artifact`** — one entry per rendered format: the SVG name plus PDF/PNG metadata
  (engine, page count, vector flag, MediaBox, pixel size, dpi, colour type, bytes).
- **`content_map`** — the provenance layer: chart descriptor, series with per-point raw value,
  parsed value, source locator and pixel geometry, axis definitions, legend entries, and the
  coverage counters (required / mapped / missing / ratio).
- **`compliance_checks`** — the audit layer: canvas, fonts, line widths, colours, legend
  consistency, geometry round-trip, content coverage, label overflow, mark-id audit, PNG and PDF
  probes, plus an aggregate `pass` flag and the `failures` list.
- **`exceptions`** — `{code, detail, severity, action}` for every mark that was skipped or blocked.
- **supporting records** — `sources`, `uncertainty`, `pending_human`, `errors`, `degradations`,
  `changes`, `runtime`, `task`.

Unknown `output_contract` keys are copied to the root as-is (null / [] when valueless). Inside
`content_map`, a point locator keeps `file`, `sheet`, `row`, `col`, `col_index`, `header`,
`x_header`, `x_col` and `quote`; error metadata (`error_raw`, `error`, `error_mode`,
`error_source`) is added when an error column was bound.

## 8. Audit block: how each rubric claim is backed

| claim | evidence inside `result.json` |
|---|---|
| figure really exists in all formats | `export_artifact.svg/pdf/png` all populated, `status=ok` |
| values match the source cells | `geometry_roundtrip.mismatch_count == 0` (2 % tolerance), `y_raw` verbatim, axis `unit`/`scale` in `content_map.axes` |
| nothing requested was silently dropped | `coverage.required == coverage.mapped`, `exceptions` lists every skip |
| a reviewer can re-derive every mark | per-point `source{file,sheet,row,col,header,quote}` + `editable_source.sha256` + `changes` + `runtime` |
| styling is systematic, not handmade | `line_widths`, `fonts`, `colors`, `legend_consistency` from the chosen preset |
| a repeat run yields the same figure | `editable_source.sha256` stable across two runs of the same input |
| new marks stay auditable | `mark_id_audit.expected == found_in_svg` and `missing` empty |
| export engines are honest | `export_artifact.*.engine` names the engine actually used; failures land in `degradations` |

## 9. Degradation ladder

| situation | reaction |
|---|---|
| `case.json` unreadable | `errors` + `degradations`, continue from the folder scan, `status=partial` |
| no table parseable | `insufficient_evidence`, empty `content_map`, `failures=[no_source_table]` |
| worked y column missing | `column_not_found`, that column skipped, remaining columns still plotted |
| empty / `NA` / censored cell | `missing_value`, mark skipped and listed in `coverage.missing` |
| error bars requested, no error column | `error_column_missing`, no bars drawn |
| log scale without positive values | `log_axis_no_positive` (axis becomes linear) or per-mark `value_off_log_axis` |
| long category labels | rotated −35°, `canvas_overflow.x_labels_rotated=true` |
| unsupported chart type (heatmap, box, pie) | `chart_type_unsupported`, bar marks used and flagged |
| no PDF engine | `degradations` entry, `export_artifact.pdf` null, SVG still delivered |
| no rasteriser | `errors: png_export_failed`, SVG (+PDF when available) still delivered |
| audit routine itself throws | `check_failed`, geometry preserved in `chart_model.json`, `status=partial` |
| any unexpected exception | caught by the top-level guard, `status=partial`, partial `result.json`, exit 0 |

Export fallback chains (first success wins, engine recorded):
PDF = `rsvg-convert` → `soffice/libreoffice` → headless Chromium-family browser;
PNG = `pdftoppm` → `ghostscript` → headless-browser screenshot of the SVG at the requested dpi.
A missing renderer never yields a renamed placeholder.

## 10. Pre-hand-over self-check

Run through `references/final-audit.md`; the short version:

1. `result.json` parses, `case_id` matches, all `output_contract` keys exist.
2. `compliance_checks.pass == true` and `failures == []`.
3. `coverage.required == coverage.mapped`; `coverage.missing` empty or explained in `exceptions`.
4. `geometry_roundtrip.checked` equals the number of bars, `mismatch_count == 0`.
5. `legend_consistency.legend_items == series == distinct_colors`.
6. `mark_id_audit.expected == mark_id_audit.found_in_svg`.
7. Axis unit is a source unit or the literal `unit not reported`.
8. `chart.pdf` starts with `%PDF-`, `pages >= 1`, `vector: true`; `chart.png` starts with the PNG
   signature and has non-zero width/height at the requested dpi.
9. `chart.svg` contains `<g id="layer-…">`, labels are `<text>`, mark ids match `content_map`.
10. Re-run the same input: `editable_source.sha256` unchanged.

## 11. Minimal example (illustrative only)

`case.json` (compact form; `organizer_workorder` may equally live in its own JSON file):

```json
{"case_id": "sample-case-07",
 "output_contract": {
   "case_id": null, "status": null,
   "editable_source": null, "export_artifact": null,
   "content_map": null, "compliance_checks": null,
   "exceptions": []},
 "organizer_workorder": {"workorder_type": "source_value_chart",
 "chart_type": "column", "x": "Condition", "y": ["p-ERK1/2"],
 "error_bar": {"mode": "sd"},
 "axis": {"y": {"label": "Signal ratio", "unit": "arb. unit"}},
 "export": {"width_mm": 100, "dpi": 200}}}
```

`data.csv`:

```
Condition,Rep,p-ERK1/2,p-ERK1/2 SD
WT,1,0.88,0.07
KO,1,1.94,0.15
```

```bash
python3 scripts/main.py --input /input --output /app/output
# artefact set: chart.svg chart.pdf chart.png chart_model.json result.json
# status "ok"; coverage {"required":2,"mapped":2,"ratio":1.0}
# mark s1-p2 -> value 1.94, quote "KO,1,1.94,0.15", row 3, column C
```

The numbers above are **示例 / illustrative only**; they are not the output of an official case.

## 12. Files, versions and extension points

```
SKILL.md                                 this document
scripts/main.py                          entry point: discovery -> model -> SVG -> render -> result.json
scripts/chartkit.py                      parsing, workorder resolution, SVG nodes, probes, audits
references/workorder-field-map.md        workorder aliases, binding order, unit rules
references/typesetting-presets.md        presets, palette, fonts, export recipes, limits
references/final-audit.md                acceptance checklist and evidence mapping
```

Python ≥ 3.8, standard library only. Optional renderers are discovered at run time:
`rsvg-convert`, `soffice/libreoffice`, `pdftoppm`, `gs`, plus a headless Chromium-family browser as
last resort. Text is emitted with the stack `Helvetica → Arial → Noto Sans CJK SC → DejaVu Sans`;
CJK labels stay editable in the SVG whether or not a CJK font is installed.

Extension points:

- Another chart type: add its mark branch in `draw_svg()` and a legend encoding, keeping the
  `bar-*` / `pt-*` id prefixes so `content_map` consumers keep working.
- Another workorder key: teach `chartkit.workorder_spec()` the alias and document it in
  `references/workorder-field-map.md`.
- Another audit: compute it in `chartkit`, expose it under `compliance_checks` and reference it in
  `references/final-audit.md`. A failing audit must stay visible, never be filtered away.
- Palette or preset changes are versioned changes; bump `version` and record the change here.
