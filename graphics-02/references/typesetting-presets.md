# Typographic presets, palette and export recipes

## Presets

`chartkit.PRESETS` holds eight numbers per preset in this order: base font size, small (tick) font
size, line width, axis line width, grid width, bar gap fraction, group gap fraction, title size.
The layout canvas is measured in CSS pixels at 96 dpi, while the SVG also declares its physical
size in millimetres, so one pixel is roughly 0.265 mm on paper.

| preset | font | small | line | axis | grid | bar gap | group gap | title |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `default` | 9.0 | 7.0 | 1.0 | 0.9 | 0.40 | 0.18 | 0.12 | 11.0 |
| `journal` | 8.0 | 6.5 | 0.9 | 0.8 | 0.35 | 0.15 | 0.10 | 9.0 |
| `nature` | 7.0 | 6.0 | 0.8 | 0.7 | 0.30 | 0.12 | 0.08 | 8.0 |
| `thesis` | 10.5 | 8.5 | 1.1 | 1.0 | 0.50 | 0.22 | 0.15 | 12.0 |
| `presentation` | 13.0 | 10.0 | 1.4 | 1.2 | 0.60 | 0.26 | 0.18 | 16.0 |

`--style` matches preset names case-insensitively by substring; an unknown name falls back to
`default`. The effective values are echoed in `compliance_checks.line_widths` and in `changes`, so
the audit shows which preset actually produced the figure.

## Series colours and markers

Colours are assigned to series in table order and never sorted or re-keyed:

`#0072B2` · `#D55E00` · `#009E73` · `#CC79A7` · `#E69F00` · `#56B4E9` · `#8C6D1F` · `#333333`

The matching marker sequence is `o s ^ D v P X *`. A ninth series wraps around the colour list
while the marker sequence keeps cycling, so two series can share a hue but not a shape. Legend
swatches are squares for bars and circles for line/scatter and are generated from the same colour
list — the legend therefore cannot drift away from the plotted marks.

## Fonts and text editability

```
Helvetica, Arial, 'Noto Sans CJK SC', 'DejaVu Sans', sans-serif
```

Every label is emitted as an SVG `<text>` element; nothing is converted to outlines. The chosen
stack is applied both inside the SVG and by the PDF renderer, so Chinese labels keep their code
points and stay selectable/editable. `compliance_checks.fonts.cjk_in_figure` records whether CJK
characters are present; pixel-identical previews additionally require a CJK font such as
`fonts-noto-cjk` to be installed.

## Export recipes

| output | first choice → fallbacks | notes |
|---|---|---|
| `chart.svg` | written directly | mm width/height, px `viewBox`, UTF-8, no external references, layered groups |
| `chart.pdf` | `rsvg-convert` → `soffice --convert-to pdf` → headless browser print | one page, vector, fonts embedded, MediaBox equals the figure box |
| `chart.png` | `pdftoppm -r <dpi>` → `gs -sDEVICE=png16m -r<dpi>` → headless-browser screenshot | 8-bit RGB, true raster of the vector figure at the requested dpi |

Each fallback appends its outcome to the runtime log (`pdf_engine=…`, `pdf_fail=…`,
`png_from_pdf=…`, `png_from_browser`), and the engine that actually produced the file is stored in
`export_artifact.pdf.engine` / `export_artifact.png.engine`. A missing renderer is reported as a
degradation; it is never papered over with a renamed placeholder file.

## Layout limits

- One axes per figure; multi-panel workorders are flattened and flagged.
- Bar/grouped bar (wide and long format), line and scatter are supported. Heatmap, box, violin and
  pie degrade to bars, with the reason recorded.
- Bars start at zero unless `axis.y.limits` says otherwise; negative values are drawn below the
  baseline.
- Log axes skip non-positive values (recorded per mark) and fall back to linear if no positive
  value exists.
- Category labels wider than the slot are rotated −35° and flagged in `canvas_overflow`.
