# Workorder field map (`workorder_type: source_value_chart`)

No key name is ever assumed. `chartkit.workorder_spec()` resolves each field in two passes —
exact (case-insensitive) name first, then substring containment over the flattened workorder
object — and leaves the field empty when neither pass matches. Empty fields are visible in
`uncertainty` and, when they block drawing, in `exceptions` / `pending_human`.

## Alias groups

| spec slot | keys accepted (any spelling) | default / note |
|---|---|---|
| chart kind | `chart_type`, `figure_type`, `chart` | `bar`/`column`, `line`, `scatter`; empty ⇒ guessed from the table shape |
| x axis | `x`, `x_field`, `x_column`, `category` | one column, text or numeric |
| y axis | `y`, `y_fields`, `y_columns`, `value_column`, `data_columns` | name or list; empty ⇒ every numeric column except x |
| series split | `series_field`, `series_column`, `grouping` | long-format column; each distinct value becomes a series |
| error column | `error_bar.source_column` / `.column` / `.field` | otherwise matched by header stem: `p-Actin SD` → `p-Actin` |
| error mode | `error_bar.mode` (`sd`, `sem`, `ci95`) | copied verbatim into `error_mode`; never recomputed |
| axis titles | `x_label`/`xlabel`, `y_label`/`ylabel`, `axis.x.label`, `axis.y.label` | fall back to the header label |
| units | `x_unit`, `y_unit`, `axis.y.unit` | fall back to the bracketed unit inside the header |
| y scale | `axis.y.scale` | `linear` (default) or `log` |
| y limits | `axis.y.limits`, `y_limits` | `[min, max]` override of the computed range |
| figure size | `export.width_mm`, `export.height_mm` | default 170 mm wide, height = 62 % of width |
| raster dpi | `export.dpi`, `resolution` | default 300 |
| style | `style`, `style_preset`, `template` | preset name, see `typesetting-presets.md`; default `journal` |
| table choice | `source_table_ref`, `source_table` | file name or fragment of the intended table |

## Header and unit handling

`label_and_unit("Concentration (mg/L)")` returns `("Concentration", "mg/L")`; square brackets and
full-width brackets are accepted too. If neither the header nor the workorder supplies a unit, the
axis is labelled `… (unit not reported)` and a `unit_unknown` exception is raised. A unit is never
guessed, converted or appended.

Numeric cells are read through one parser: thousands separators, `%` (converted to a fraction),
Unicode minus signs and non-breaking spaces are normalised; `NA`, `n.d.`, empty strings and
censored expressions such as `<0.01` come back as *missing* (`nan` / `censored`) and are reported,
not coerced to zero.

## Error bars and significance

- Error magnitudes are read row by row from the matched error column. The raw text is preserved in
  `error_raw`; a value that fails to parse drops only that bar (`error_value_unparsable`).
- `significance_marks` are not rendered: a significance claim is a statistical assertion this
  package cannot verify. The request is recorded but no bracket or star is drawn.
- Nothing is recomputed from replicate rows. If the workorder asks for `sem` and the table only has
  `SD`, the SD column is transmitted as-is and `error_mode` says so.

## Panels and unsupported types

`panels` / `panel_layout` are parsed and flattened into one axes; all series survive and the
flattening is recorded (`panels_flattened`). Heatmap, box, violin and pie requests degrade to bar
marks with `chart_type_unsupported` — geometry is never fabricated for a type that is not drawn.

## Example block

```json
{"workorder_type": "source_value_chart",
 "chart_type": "grouped_bar",
 "x": "Treatment",
 "y": ["p-Actin", "p-ERK1/2"],
 "error_bar": {"mode": "sd"},
 "axis": {"y": {"label": "Normalized intensity", "unit": "a.u.", "scale": "linear"}},
 "export": {"width_mm": 120, "dpi": 150},
 "style": "journal",
 "source_table_ref": "figure3_source.csv"}
```
