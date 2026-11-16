# Reading guide by figure type

Every rule here governs interpretation only. A quantity with no visible basis stays
`undetermined`; it never enters the factual layer.

## 1. Line, scatter and kinetics curves

1. Close the frame first: are top/right spines present? `spines_px` gives what the tool found; when a
   spine is missing, derive the boundary from the axis start.
2. Ticks: evenly spaced major ticks do not prove a linear axis. Only shrinking minor gaps or printed
   `10ⁿ` labels justify calling it logarithmic.
3. Units: copy the string inside the axis label (`mV`, `kPa`, `µε`) and do not borrow a unit from
   the other axis.
4. Series identity: combine colour clusters with legend swatch order. If two series share a colour and
   differ only by marker, state that they cannot be separated.
5. Sampling: one value per pixel column (median y), line width becomes `px_thickness`. A thickness
   jump means overlapping curves — mark that span `undetermined` and emit no points there.
6. Frequent mistakes: treating a legend swatch as a data point; treating a low-saturation grid line as
   a curve (the cluster filter drops greys).

## 2. Bars, boxes and error bars

1. Bar height is the top-edge pixel converted through the y calibration; bar width and bar gaps are
   not data.
2. Error bars: read the caption to classify SD / SEM / 95% CI / range. Without any caption statement,
   report only the cap range and set `inferred`.
3. Box plots: read the median line, box edges (Q1/Q3) and whisker ends; whether whiskers are 1.5·IQR
   or min/max must come from the caption, otherwise `undetermined`.
4. Significance: record the glyph (`*`, `**`, `n.s.`) together with the bracket endpoints, i.e. which
   two groups are being compared.
5. Frequent mistakes: counting an error bar as a second series; reporting `n.s.` as significant.

## 3. Spectra and peak shapes

1. The abscissa is usually wavenumber / wavelength / energy — check the direction (FTIR is often
   high-to-low from left to right).
2. Peak position: the column of a local minimum (transmittance) or maximum (absorbance/intensity)
   after calibration; peak height is measured against the local baseline.
3. Peak width is reported as an approximate FWHM only; instrument resolution is not recoverable.
   Do not assign chemical identity from an image.
4. Frequent mistakes: reading the jagged glyph of a tick label as a peak; reading baseline drift as
   a peak.

## 4. Micrographs, photographs and schematics

1. No axis frame means `traceable=false`: report dimensions, colour clusters and scale-bar candidates,
   nothing quantitative.
2. Scale bar: first read the printed length (µm) from caption or bar label, then convert using the
   bar's pixel length; with no printed length, report pixel length only.
3. Counting or sizing particles requires visual segmentation, which the tool does not perform; the
   agent must supply the bbox evidence itself.
4. Frequent mistakes: treating the scale bar as a data series; "correcting" a caption unit from
   physical intuition.

## 5. Multi-panel figures

1. One entry per panel: `figure_id` + `panel` + that panel's own axes and legend. Sharing a legend
   across panels is forbidden.
2. Captions often pack `(a)(b)(c)` conditions into one sentence — bind each condition to its panel.
3. Summary conclusions may only restate comparisons that the caption or body text actually makes;
   never do arithmetic across panels.
4. Panels mentioned in text but not supplied as pixels go to `coverage.missing_images`; their data is
   not inferred.

## 6. Tables

1. Keep the header verbatim, including unit rows, parentheses and superscript spellings. Do not merge
   or swap columns.
2. Grouped (spanning) headers need two header rows plus a note row; do not flatten them into one.
3. Missing cells stay empty — never fill them with 0. `—`, `N/A`, `n.d.` stay as printed and their
   meaning goes into `uncertainties` unless the caption defines it.
4. Footnotes (significance codes, sample sizes, conditions) are recorded separately, not folded into
   numeric columns.

## 7. Anomaly decision matrix

| Observation | Verdict | Action |
|-|-|-|
| No ticks, no frame | photograph / schematic | `traceable=false`; report colours and size; quantitative need goes to `pending_human` |
| Figure cropped | one axis end missing | clip the bbox to what is visible; do not invent the missing ticks; log the crop |
| Legend missing | unnamed swatches | propose candidates by area/position; `readability=inferred` |
| Unit unknown | no unit on the label | `unit=null`; never treat as dimensionless |
| Overexposed / low contrast | ink and background merge | fall back to visual reading; add a degradation |
| Curves overlap | abnormal column thickness | no points in the overlap; give the interval and reason |
| Dual y axis | different tick sets left/right | fit `y` and `y2` separately; never mix them |
| Reversed axis | values grow with pixel index | the tool auto-corrects; still state the scale direction on the axis |
| JPEG/TIFF | no stdlib decoder | skip structure, rely on agent readings |

## 8. Reading order (repeat every time)

axes → units → legend → series → points/trend → error and significance → caption conditions →
conclusion with quote or bbox. Skipping ahead to a conclusion is the most common source of a
"number that is not in the figure" error.
