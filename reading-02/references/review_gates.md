# Review gates: rubric mapping, calibration maths, submission checks

## 1. Rubric → artifact map

| Scoring area | Sub-point | Where this skill answers it | Checkable artifact |
|-|-|-|-|
| Effect 40 | task completion 15 | every declared image and table enumerated in `coverage`; honest `status` | `result.json`, `figure_structure.json` |
| | correctness 15 | axis kind / ticks / units / legend recorded; fit `r2` and residual published | `axes.*`, `legend_candidates`, tables |
| | completeness 5 | axes, legend, series, error bars, significance, scale bar, panels, caption all fielded | `result.figures.*`, `elements` |
| | verifiability 5 | each claim has `quote` + locator; `verification.claim_checks` lists results | `claims`, `verification` |
| Gain 25 | quality 15 | pixel calibration plus per-column median tracing replaces eyeballing; errors are explicit | `digitized_series.csv` with `x_px`/`y_px` |
| | efficiency 5 | one command performs structure, fit, trace and table copy | `runtime.duration_s` |
| | gain proof 5 | same `readings.json` reruns identically; `r2`, residual, error columns retained | two runs of `verification` agree |
| Novelty 15 | new capability 5 | scale identification, pixel→data calibration, legend swatch grouping, error-band capture | `calibrate`, `legend_candidates` |
| | method 5 | multimodal cross-check of label count vs detected tick count | `calibration_notes` |
| | novelty evidence 5 | fitted alternatives and residuals kept in the record | `axes.*.alternatives` |
| Reliability 10 | usability 3 | two options; `--help` explains itself | `python3 figure_runner.py --help` |
| | stability 4 | exit 0 always; partial shell first; one bad figure cannot abort the rest | `errors`, `degradations` |
| | exceptions 3 | no frame / crop / missing legend / unknown unit / overexposure / overlap each have a branch | `warnings`, `uncertainties` |
| Ecosystem 10 | docs 3 | `SKILL.md` + three references, each self-contained | this folder |
| | reuse 4 | calibration and digitisation are plain functions usable on new images | `scripts/raster_ops.py` |
| | sharing 3 | figure-type guide, anomaly matrix and error conventions are portable | `references/figure_types.md` |

## 2. Calibration maths

Linear: `value = a·px + b` by ordinary least squares, where `a` is data units per pixel.

- `sxx = Σ(pᵢ − p̄)²`, `a = Σ(pᵢ − p̄)(vᵢ − v̄) / sxx`, `b = v̄ − a·p̄`
- `R² = 1 − SS_res/SS_tot`; `max_rel_dev = max |v̂ᵢ − vᵢ| / |vᵢ|`

Log: fit `t = log₁₀v` the same way, invert with `v = 10^(a·px + b)`, and report
`px_decade = |1/a|` instead of `value_per_px`.

Error: `err_data = 0.5 · s · |a|`, where `s` is the downsample stride (1 when no downsampling).

Direction: if `(v_last − v_first)·(px_last − px_first) < 0`, reverse the pixel list before pairing
(the y-axis case).

Choosing a fit: lower `max_rel_dev` wins. If both scales reach `R² ≥ 0.9995` with deviation ≤ 1%,
set `ambiguous = true`; the printed tick labels — not pixel spacing — must break the tie.

## 3. Pre-submission gate

1. `python3 -B scripts/figure_runner.py --help` exits 0 (also run `ast.parse` on both scripts).
2. Minimal fixture run: `result.json` parses, all contract keys are present, `coverage`/`counts`
   match the fixture.
3. Empty input: a legal `result.json` is still written (`insufficient_evidence` or `input_error`),
   exit code 0.
4. Corrupt JSON in `case.json`: the reason lands in `errors`, `status=input_error`, exit code 0.
5. Run twice: `digitized_series.csv` is byte-identical (determinism, no clocks or randomness in data).
6. Every `claims[].evidence.quote` is found in its `source_id` or sits inside the image bbox.
7. `uncertainties` covers missing error-bar definition, missing unit, cropped figure, missing legend.
8. Every `pending_human` entry carries an executable `action`.
9. No `__pycache__`, `.pyc`, prepared answers or unlabelled example data; every example is marked
   as an example.

## 4. Common score losses and the fix

| Loss | Fix |
|-|-|
| Image reading presented as an exact table value | keep `approx=true` and `err_*_data` |
| Log axis read as linear | inspect minor ticks / `10ⁿ` labels first |
| Legend mapped by memory | align `legend_candidates.entries_top_to_bottom` rgb values |
| Withheld material counted as unfinished work | `coverage.missing_*` + `pending_human`, and say so in `uncertainty.scope` |
| Only a prose summary delivered | always emit `digitized_series.csv`, `tables.json`, `figure_structure.json` |
| Sample conditions lost outside parentheses | bind them in `conditions` per series/panel |
