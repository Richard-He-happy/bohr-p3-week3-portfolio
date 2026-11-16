---
name: figure-evidence-lens
description: Turn scientific figures plus literal source tables into auditable structured data. Recovers axis scales and ticks, units, legend-to-series order, digitised points with explicit pixel error, verdict-safe element notes (error bars, significance, scale bar, sub-panels), verbatim table cells, and one traceable locator per claim. Use when a task says "answer with evidence" about a chart, spectrum, micrograph, statistics table or multi-panel figure, or asks for plotted values as CSV/JSON.
version: 1.0.0
license: MIT
---

# figure-evidence-lens

## 0. Job of this skill

Given a case directory that holds one raster figure and the paper's literal tables, produce a
machine-checkable reading instead of a prose summary. The agent interprets what only eyes can
interpret (tick glyphs, unit strings, legend text, caption wording, scientific meaning); a small
stdlib tool measures what pixels can measure (frame, tick spacing, colour clusters, legend
swatches, calibrated traces, verbatim table grids) and audits every evidence quote.

Guiding rule: **a number that cannot be tied to a locator is not reported.** Unreadable material
becomes `undetermined`, missing material becomes an explicit gap, never an invention.

Trigger this skill when any of these is true:

- the request mentions axes, tick marks, units, legends, data points, error bars, scale bars or sub-panels;
- plotted values must be exported (CSV / JSON / table) or compared across series;
- the phrase "with evidence" / "give the basis" appears and the basis must be inside a figure or table;
- the input contains `artifacts/*.png|jpg|tif`, `material.json`, a paper PDF, or CSV/XLSX tables.

Do not trigger it for pure writing/translation work, and do not use it to invent values for
figures that were never supplied (report the gap instead).

## 1. Deliverables and runtime envelope

| Item | Requirement |
|-|-|
| Reads | `/input/case.json`, `/input/task.md`, everything else under `/input/` (raster, PDF, CSV, JSON) |
| Writes | `/app/output/result.json` (mandatory) plus `figure_structure.json`, `digitized_series.csv`, `tables.json`, `tables/<id>.csv` when the material allows, and the five verifiable assets of §11 |
| Contract | every key of the input `output_contract` is present in `result.json`; unknown keys are kept; absent values use `null`/`[]` |
| First write | a legal `partial` shell before analysis starts, replaced at the end without exception |
| Exit code | always `0`; failures land in `errors` / `degradations` / `pending_human` |
| Dependencies | Python standard library only, offline, path-safe (resolved from `Path(__file__)`) |
| Runtime | seconds per case on CPU; 64-request / 900 s / 16k-token case budget is untouched |

Two equivalent invocations (run once, then read `result.json`):

```bash
ct=python3; $ct /skills/weekly-skill/scripts/figure_runner.py --input /input --output /app/output
$ct /skills/weekly-skill/scripts/figure_runner.py --input /input --output /app/output --readings /app/work/readings.json
```

Use `--readings` explicitly when the agent has already written its visual notes; the tool also
searches `<work>/readings.json`, `<input>/readings.json` and `<output>/readings.json` in that order.

## 2. Ordered workflow

1. **Seed.** Load the case, keep `case_id` and `output_contract`, write the partial shell, hash every
   input file into `sources` (relative id + bytes + sha256).
2. **Inventory.** Build the must-do object list from the supplied scope (image list + table-id list).
   Objects not in that list are gaps, not extra credit; never synthesise pixels or captions for them.
3. **Measure.** For each raster: image size, plot box, spines, tick positions, colour clusters,
   legend swatch groups, traceability flag. Photos and schematics legitimately end this step with
   `traceable: false`.
4. **Interpret.** The agent writes `readings.json`: tick labels, units, scale kind (linear/log/dual),
   legend text and order, caption, sub-panel ids, element semantics, conclusions.
5. **Fit and trace.** Pair labels with detected ticks (order auto-corrected), least-squares fit per
   axis, then trace each requested series colour column by column into `digitized_series.csv` with
   `approx: true` and a half-pixel error term.
6. **Tables.** Copy CSV/JSON-inline tables verbatim — header strings, cells, units, conditions. Office
   containers stay text-level sources and are recorded as degradations when cells cannot be parsed.
7. **Audit and close.** Verify contract keys, claim schema, quote hits and bbox bounds, then finalise.
   A blocking failure demotes `answered` to `partial`; it never silently passes.

## 3. Finding inputs by meaning, not by key name

`case.json` may be named differently or be nested one level down: fall back to a recursive
`case*.json` search and keep going even when it is absent. Treat `task_instruction`,
`organizer_supplied_scope`, `formal_inputs`, `artifacts` and similar fields as content to inspect,
not as a schema you can rely on. File types are decided from magic bytes, never from the extension
or from a domain label in the task. Must-do image names and table ids come from any list-valued
field whose name mentions image/figure/photo or table.

## 4. The `readings.json` channel (agent input, also where the quality gain lives)

```json
{"figures": {"artifacts/panel_c.png": {
  "figure_id": "Figure 3", "panel": "c",
  "caption": "verbatim caption text",
  "axes": {"x": {"label": "Wavelength", "unit": "nm", "scale": "linear",
                 "tick_labels": ["400", "500", "600"], "tick_px": [100, 300, 500]},
           "y": {"label": "Absorbance", "unit": "a.u.", "scale": "linear",
                 "tick_labels": ["0.0", "0.5", "1.0"]}},
  "legend": {"entries": [{"label": "control", "rgb": [33, 87, 190]},
                         {"label": "treated", "rgb": [206, 62, 40]}]},
  "elements": {"error_bars": "SEM, n=6 per group",
               "significance": "* p<0.05 between treated and control",
               "scale_bar": "not applicable"},
  "series": [{"name": "treated", "rgb": [206, 62, 40], "digitize": true, "tol": 60}]}},
 "claims": [{"claim_id": "k1", "kind": "value", "text": "peak absorbance 0.82 a.u. at 512 nm",
   "readability": "directly_read", "conditions": "treated group, panel c",
   "evidence": {"quote": "Absorbance 0.82", "quote_type": "text", "source_id": "material.json",
                "location": {"json_pointer": "/tables/1/rows/3/2"}, "read_basis": "literal cell"}}],
 "uncertainties": [], "pending_human": []}
```

Rules that keep this channel honest:

- `tick_labels` and `tick_px` run in the same direction (usually left→right, bottom→top). The tool
  flips them when value and pixel trends disagree and records the residual in `max_rel_dev`.
- If the label count differs from the detected tick count, pairing starts at the axis origin and a
  calibration note is added — read `result.figures.<id>.calibration_notes` before trusting a fit.
- `rgb` values are copied from `figure_structure.json` → `color_clusters`. Guessing colours from
  memory is the most common cause of a wrong legend mapping.
- A point trace is only as good as its identification: if two series share the same colour, say so
  in `uncertainties` instead of letting the tracer split them arbitrarily.

## 5. Reading rules that decide correctness

| Situation | Required handling |
|-|-|
| Evenly spaced major ticks, no minor ticks | default linear; never infer log from pixel spacing alone |
| Minor-tick gaps shrinking across a decade, or labels 1/10/100/10ⁿ | log candidate; must be backed by the printed labels |
| Left and right y axes | separate `y` and `y2` fits; never pool two tick sets into one calibration |
| Unit strings | copy verbatim (mV stays mV, µm stays µm); no unit means `null` plus an uncertainty — **not** "dimensionless" |
| Error bars | only `y_lo`/`y_hi` when caps are measurable; without a legend statement, `readability` is `inferred` |
| Pixel-derived numbers | always `approx: true` plus a half-pixel error in data units; never present them as table values |
| Significance stars / scale bars | record glyph position and caption wording; convert only when the scale-bar length is given |
| Photo, micrograph, schematic | `applicable: false` with a `basis` sentence; no invented points, peaks or error bars |
| Multiple panels | one entry per panel with its own axes and legend; captions bind conditions to panel ids |

## 6. `result.json` layout

Top level: `case_id`, `status` (`answered` / `partial` / `insufficient_evidence` / `input_error`),
`result` (`figures`, `tables`, `coverage`, `counts`, `digitized_series_file`), `claims`,
`uncertainties`, `uncertainty`, `sources`, `pending_human`, `errors`, `degradations`, `changes`,
`runtime`, `verification`, `output_contract_spec`.

Every claim carries `kind`, `text`, `evidence{quote, quote_type, source_id, location, read_basis}`,
`readability` (`directly_read` / `inferred` / `undetermined`) and `conditions`. `location` combines
any of `figure`, `panel`, `bbox_px`, `json_pointer`, `page`, `table_id`, `row`.

`status` semantics are strict: `answered` only when every declared object is resolved and evidence
passes; `partial` only while declared objects are still unparsed — it must **not** be used to imply
that the paper withheld other figures. `input_error` means the case itself is unreadable.

## 7. Failure handling

| Failure | Response |
|-|-|
| No frame / no ticks | warn `no_axis_frame_detected`; keep size and colour facts; `traceable=false` |
| JPEG / BMP / TIFF | structural pass skipped; degradation + `pending_human` asking for visual readings |
| Figure cropped or curve leaving the box | clip to the plot box; do not emit out-of-box points; record the crop |
| Legend absent | propose candidates by colour area and order; mark `inferred` |
| Unit unclear | `unit: null` + uncertainty; do not substitute a plausible unit |
| Overexposure / overlapping curves | report thickness spikes; mark the overlap region `undetermined` |
| Tables with units only in header or footnote | header verbatim, footnote into `uncertainties` |
| Only mentioned in text, no pixels | goes to `coverage.missing_*` and `pending_human`, never generated |

## 8. Self-audit before delivery

The tool already emits `verification.evidence_metrics` and `verification.scope_coverage` on every
run; use them as a gate. Additionally check:

- `result.json` parses, all contract keys exist, `case_id` unchanged;
- `status` matches the real coverage; any unparsed declared object forces `partial`;
- every text quote matches its source exactly (normalised hits are flagged) and every visual quote
  has an in-bounds bbox;
- no pixel-derived number appears without `approx` and an error term;
- `uncertainties` lists every withheld quantity; `pending_human` entries name an executable action;
- an empty or corrupt input still yields a legal `result.json` and exit code 0;
- the five assets of §11 are non-empty and `self_check.json` reports `pass: true` (or lists
  probes as `skipped` when the sandbox forbids subprocesses).

## 9. Minimal synthetic example (illustration only — not an official case)

Fixture: `case.json` with `case_id: DEMO-X` and a 5-key contract plus one vendor extra key;
`artifacts/fig1.png` = 600×420 synthetic chart, red curve A and blue curve B, two-colour legend;
`material.json` = one table `T01`; `readings.json` = x 0–8 mm / y 0–100 N, series A digitised.

```bash
python3 scripts/figure_runner.py --input ./input --output ./out
# stdout -> {"status": "answered", "output": "./out", "errors": 0, "degradations": 0, "claims": 3}
```

| Artifact | What to expect |
|-|-|
| `result.json` | all contract keys present (vendor extra key kept as `null`); `status` reflects coverage |
| `figure_structure.json` | plot box, spines, x/y tick centres, colour clusters, legend swatch order |
| calibration | per axis `scale`, `r2`, `max_rel_dev`, `value_per_px`; alternatives listed when linear/log are close |
| `digitized_series.csv` | one row per column sample: data x/y, `y_lo`/`y_hi`, pixel coords, `approx`, error columns |
| `tables.json` | `T01` header and rows copied verbatim, no unit conversion |
| `verification` | per-claim quote match, hard-failure count, `evidence_metrics`, `scope_coverage` |

## 10. Files, version, maintenance

| File | Role |
|-|-|
| `SKILL.md` | this entry point |
| `scripts/figure_runner.py` | orchestration: discovery, contract shell, per-figure pipeline, tables, audit, finalise |
| `scripts/assets.py` | five verifiable assets: golden standard, diff report, version history, run log, self check |
| `scripts/raster_ops.py` | pure pixel/text primitives: PNG decode, frame/tick/colour analysis, least-squares fit, trace, CSV/JSON table copy, PDF string extraction |
| `references/field_contract.md` | field dictionary for `readings.json` and `result.json`, error conventions |
| `references/figure_types.md` | per-figure-type reading guide and the anomaly decision matrix |
| `references/review_gates.md` | rubric-to-artifact mapping, calibration maths, pre-submit gates |

Version 1.0.0, Python ≥ 3.8, no external packages. When a field is added or renamed, update
`references/field_contract.md` and section 6 here in the same change.

## 11. Five verifiable assets (additive patch increment)

Finalise also writes five machine-checkable assets to `/app/output/`. They are an additive
layer only: delete `scripts/assets.py` and the runner silently falls back to the original
behaviour (`A = None`), while the CLI, the contract keys and the always-0 exit code stay
unchanged. Every asset is produced by the same real run — nothing is copied in from a test.

| Asset | Contents | Verify with |
|-|-|-|
| `golden_standard.json` | expected delivery item by item (contract keys, figure structure, axes, series, readings, table values), each with a source `locator` and a verbatim `quote`; measured items are re-computable (PNG IHDR, tick pixels, colour clusters, file sha256) | `python3 -c "import json;print(json.load(open('/app/output/golden_standard.json'))['counts'])"` |
| `diff_report.md` | actual product vs golden, one verdict per item (`match` / `missing` / `deviation` / `needs_review`), grouped summary, deviation list and re-run steps | `grep -c "^| G-" /app/output/diff_report.md` |
| `version_history.md` | static v0 → v1.0.0 evolution, this assets increment, rollback table, plus a runtime section appended by finalise | `grep -n "本次运行" /app/output/version_history.md` |
| `run.log` | real execution log: invocation, per-stage lines with timings, degradations, final `[exit] … exit_code=0` | `tail -n 5 /app/output/run.log` |
| `self_check.json` | 20 machine assertions: contract keys, main products, counts, quote hits, asset presence, empty/bad-input fallback subprocesses, exit codes, package budget | `python3 -c "import json;d=json.load(open('/app/output/self_check.json'));print(d['pass'],d['passed'],d['total'])"` |

`result.json` gains five summary keys (`golden_standard`, `diff_report`, `version_history`,
`run_log`, `self_check`), each an object with `path`/`bytes`/`sha256`; no existing contract
key is renamed or dropped. Re-running the same command regenerates all five assets; setting
`FIGLENS_ASSET_PROBE=1` disables only the two fallback subprocess probes.
