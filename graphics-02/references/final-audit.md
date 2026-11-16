# Final audit protocol (run this after every build)

The package writes its own audit, but the audit itself must be signed off. Walk the three gates
below in order; a figure is only deliverable when all three pass or when the remaining gap is
declared in `exceptions` / `pending_human`.

## Gate 1 — contract completeness

| assertion | pass condition |
|---|---|
| `result.json` parses | `json.load` succeeds |
| case identity | `case_id` equals the input case id (or `unknown` with an explanation) |
| contract echo | every key of the input `output_contract` appears at the root, null/[] when empty |
| artifact set | `editable_source.path`, `export_artifact.svg/pdf/png` present and the files exist |
| status honesty | `ok` only when audits pass and `errors`/`degradations` are empty; otherwise `partial` |

## Gate 2 — machine audits

Values are read from `compliance_checks`; thresholds are deliberately tight because a figure that
is *nearly* right is not a figure that can be published.

| audit key | assertion | failure name |
|---|---|---|
| `geometry_roundtrip` | `checked` equals the number of bar marks, `mismatch_count == 0`, relative error ≤ 2 % | `geometry_mismatch` |
| `legend_consistency` | `legend_items == series == distinct_colors` | `legend_series_mismatch` |
| `content_coverage` | `mapped == required`, `ratio == 1.0` | `coverage_incomplete` |
| `mark_id_audit` | `found_in_svg == expected`, `missing == []` | `mark_id_missing` |
| `png` | PNG signature present, width/height > 0, `ink_present` not False | `png_blank` |
| `pdf` | header starts with `%PDF-`, `pages >= 1`, MediaBox recorded | `pdf_missing` |
| `canvas_overflow` | rotated labels flag matches the rendered SVG | — (informational) |
| `pass` / `failures` | aggregate boolean and the exact failure list | — |

Additional spot checks that the audit cannot express:

1. Open `chart.svg` and confirm each data layer (`layer-data`, `layer-error`, …) exists and the
   labels are selectable text rather than paths.
2. Pick any point from `content_map.series[i].points[j]` and verify its `source.quote` line in the
   table really contains the quoted `y_raw` string.
3. Compare the axis unit and label against the header or workorder; confirm that no unit was
   invented when the source had none.
4. Re-run the same input into a second folder; `editable_source.sha256` must be unchanged.

## Gate 3 — evidence quality

- Every `exceptions[]` entry names a code, a concrete detail and the action taken; nothing is a
  generic "error".
- `pending_human[]` asks for the smallest missing thing (one column, one unit, one table) rather
  than asking for the whole figure again.
- `uncertainty[]` distinguishes what was stated in the workorder from what was inferred from the
  table shape, and repeats that statistics are forwarded, not computed.
- `degradations[]` lists only fallbacks actually taken; an unused optional renderer must not be
  mentioned as if it had failed.

## Failure triage

| symptom | first place to look |
|---|---|
| `coverage_incomplete` | `content_map.coverage.missing` and `bind_columns` issues (unparsable cells, header mismatch) |
| `geometry_mismatch` | axis min/max versus `geometry_roundtrip.mismatches[].expected/recomputed` |
| `legend_series_mismatch` | whether a series had zero plottable points (empty series still gets a legend entry) |
| `mark_id_missing` | SVG mark ids vs `content_map` ids; usually a chart type change without an id branch |
| `png_blank` | renderer output size/ink; try another engine from the fallback chain |
| `pdf_missing` | which engine was probed and why each step failed (`degradations`, runtime log) |

## Sign-off line

Record in the answer or work log: preset, table file/sheet used, number of marks, coverage ratio,
geometry checked/mismatched counts, legend counts, export engines, SVG sha256, runtime seconds.
That single line lets a reviewer reproduce the figure without reading the code.
