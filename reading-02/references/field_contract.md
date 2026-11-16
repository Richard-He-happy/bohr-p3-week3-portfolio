# Field contract and error conventions

Two documents are described here: `readings.json` (the agent's visual channel) and `result.json`
(the graded deliverable). Coordinates are original-image pixels unless a field says otherwise;
the origin is the top-left corner, x grows right, y grows down.

## 1. `readings.json`

| Key | Type | Needed | Meaning |
|-|-|-|-|
| `figures` | object | yes | map keyed by `source_id` (path relative to `/input`) or bare file name |
| `figures.<sid>.figure_id` | string | no | printed figure label, e.g. `"Figure 3"` |
| `figures.<sid>.panel` | string | no | sub-panel letter; never let one panel inherit another's id |
| `figures.<sid>.caption` | string | no | caption copied verbatim (truncation allowed, value edits not) |
| `axes.x` / `axes.y` / `axes.y2` | object | if axes exist | `label`, `unit`, `scale` (`linear`/`log`/`auto`), `tick_labels`, optional `tick_px` |
| `legend.entries[]` | array | no | `label` + `rgb`, ordered as printed top-to-bottom |
| `elements` | object | no | free-form notes: `error_bars`, `significance`, `scale_bar`, `n`, … |
| `series[]` | array | no | `name`, `rgb`, `digitize` (bool), `tol` (default 60), optional `visual_points` |
| `claims[]` | array | yes | see section 3 |
| `uncertainties[]` | array | no | unstated values, conflicts, items needing human eyes |
| `pending_human[]` | array | no | `{item, why, action}`; `action` must be doable by a person |

Direction convention for ticks: `tick_labels` and `tick_px` must run in the same direction. When
value order and pixel order disagree, the tool reverses the pixel list and reports the residual.
When the two lists have different lengths, pairing begins at the axis origin and
`calibration_notes` gains a `label/pixel count mismatch` entry.

## 2. `result.json`

| Key | Content |
|-|-|
| `case_id` | copied from the case, never regenerated |
| `status` | contract vocabulary first; `answered`/`ok` mean success; unfinished declared objects force `partial` |
| `result.figures.<sid>` | `figure_id`, `panel`, `caption`, `image_px`, `plot_box_px`, `spines_px`, `ticks_px`, `spacing`, `axes`, `color_clusters`, `legend_candidates`, `elements`, `digitized`, `traceable`, `warnings`, `calibration_notes` |
| `result.tables[]` | `table_id`, `source_id`, `columns`, `n_rows`; header and cell order untouched |
| `result.coverage` | `images[]` (with `declared`), `tables[]` (with `resolved`), `missing_images`, `missing_tables` |
| `result.counts` | required images, analysed images, missing images, extracted tables, required tables, resolved tables, claims, digitised rows |
| `claims[]` | section 3 |
| `uncertainties[]` | unstated / conflicting / undetermined / human-check items |
| `uncertainty` | summary object: `visual_readings`, `missing_materials`, `scope`, `counts`, `fatal` |
| `sources[]` | `source_id`, `kind`, `bytes`, `sha256`, `path` for every input file |
| `pending_human[]` | hand-over points with an executable action |
| `errors[]` / `degradations[]` / `changes[]` | failures, reduced-capability paths, state transitions |
| `runtime` | skill name/version, Python version, input and output dirs, duration |
| `verification` | `n_claims`, `n_contract_keys`, `issues`, `claim_checks`, `hard_failures`, plus `evidence_metrics` and `scope_coverage` (self-audit summary) |
| `output_contract_spec` | the contract object exactly as received, for side-by-side checking |

## 3. Claim object

```json
{"claim_id": "k1", "kind": "value|trend|element|comparison|caption_fact|table_cell",
 "text": "one sentence, numbers and units as printed",
 "readability": "directly_read|inferred|undetermined",
 "conditions": "series, panel, specimen or scan rate that bound the statement",
 "evidence": {"quote": "verbatim string or visual description",
              "quote_type": "text|visual", "source_id": "relative path",
              "location": {"figure": "...", "panel": "...", "bbox_px": [0,0,10,10],
                           "json_pointer": "/tables/0/rows/1/1", "page": 3,
                           "table_id": "T01", "row": 1},
              "read_basis": "how the value was read (tick calibration, literal cell, legend)"}}
```

`location` may combine any of the listed sub-keys; a claim with no usable locator is treated as
unverifiable and should not be promoted to `directly_read`.

## 4. Error and precision conventions

| Quantity | Convention |
|-|-|
| Pixel quantisation | large rasters are stride-downsampled by `analysis_scale = s`, so coordinates carry ±s px |
| Data error | `err = 0.5 × s × \|slope\|` where slope is data units per pixel; written to `err_x_data` / `err_y_data` |
| Calibration residual | per-tick relative deviation → `max_rel_dev`; `r2` and the losing `alternatives` are reported together |
| Log axes | the fit happens on `log10(value)`; `value_per_px` is `null` and `px_decade` is given instead |
| Line thickness / error bars | each sampled column exposes `px_thickness`; `y_lo`/`y_hi` mark the column extent (cap or bar range) |
| Significant digits | `round_sig(x, 4)`; pixel-derived values keep `approx=true` and are never dressed up as table values |

## 5. `digitized_series.csv` columns

`figure, panel, series, x, y, y_lo, y_hi, x_unit, y_unit, err_x_data, err_y_data, x_px, y_px, approx`

Rows from several figures or series are separated by `figure` and `series`. `x_px`/`y_px` retain
original-image coordinates so any row can be checked against the raster later.
