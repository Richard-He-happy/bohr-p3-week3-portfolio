# Fidelity decision rules (terms / numbers / structure / boundaries)

Each of the four assessed dimensions maps to checks that can be run mechanically. Below are the decision rules and the usual point-losers.

## 1. Term consistency — one rendering per concept

- **Priority**: supplied term base > frequent acronym candidates > domain noun phrases. When a supplied rendering clashes with field habit, the supplied one wins; log the conflict in `note`.
- **Reach**: abstract, body, figure and table captions, footnotes, appendices and reference titles all use the same wording. Caption-vs-body divergence is the most common penalty.
- **Polysemy**: `resolution` is "分辨率" in imaging papers but "分离度" in separation/chromatography papers; `significant` is "显著的" in statistics and "明显的" in general prose. Decide once for this manuscript, explain it in the term-table `note`, and never re-interpret unit by unit.
- **Acronyms**: a first occurrence may read "中文（XRD）", later occurrences keep the acronym; never expand what the source left unexpanded. If no accepted rendering exists, write "中文（source term）" and park it in the pending list.

## 2. Number fidelity — copy the literal

- Every value, precision, interval, year, sample size, `p` value, confidence interval, temperature, concentration, dosage and magnification matches the source. `95% CI: 92–98%` must not shrink to `92–98%`.
- **Chinese vs English magnitude**: `3.2 万` = `32,000`; `1.5 亿` = `150 million`; `万亿` = `trillion`. The converted value must be numerically equivalent and the original notation goes into `note`.
- **Units and symbols**: no conversion, no omission, no case changes for case-sensitive forms (`mg/L`, `mL`, `°C`, `min⁻¹`); keep the U+2212 minus in `min−1`.
- **Statistical phrasing**: `mean ± SD`, `median (IQR)`, `two-tailed`, `95% CI` travel with their numbers.
- **Equations**: `k = 0.031 min⁻¹`, `·OH`, `TiO2` subscripts, `R²` superscripts follow the source; move the equation as one block and do not change operators.
- `preserved_facts.json` records `present_in_target` per fact. Anything `false` is either restored or explained.

## 3. Structural alignment — positions and labels stay

- Unit maps to unit: `para_id` and order unchanged. Do not merge units into flowing prose; authors revise paragraph by paragraph.
- Figures and tables: labels untouched (`图 3` <-> `Figure 3`), captions stay with their object; footnote markers (`a`, `b`, `*`) stay in position.
- References: authors, year, journal, volume/pages and DOI are copied verbatim; only style punctuation may be adjusted; bracketed numbers do not move.
- Headings: translate `## 参考文献` to `## References` but do not carry Markdown marks into the target prose.

## 4. Semantic boundaries — do not step over

- **Negation scope**: `The rate did not increase because of salinity` must not become "因为盐度速率没有增加". Reordering is allowed; changing the logic is not.
- **Evidence strength**: `suggests / indicates / demonstrates / proves` is a four-step ladder; keep the target at the same step, never upgrade or downgrade.
- **Hedges**: `may / might / likely / probably / up to / at least` must stay explicit.
- **Conditions**: phrases such as `under UV irradiation` or `at pH 3` may not be dropped.
- **Attribution**: `Zhang et al. reported …` stays a third-party report, never a finding of this study; inferences the authors did not make may not appear.

## 5. Register

- Academic written language: no colloquialisms (`a lot of` -> 大量), no promotional tone (do not inflate "novel breakthrough"), no word-for-word Chinese with stacked pre-modifiers.
- Full-width punctuation in Chinese, half-width in English; keep a space between English numbers and units (`12.5 mg/L`).
- Active vs passive may follow target-language habit, but the agent/patient relation must not change.

## 6. Four cases that go to a human instead of being forced

1. No accepted rendering exists, or two renderings are both standard in the field;
2. The source contradicts itself on a number or unit (body 95%, table 92%) — keep both and flag;
3. Cross-unit reference is unclear, a sentence is broken, a page is missing, or text lives only inside an image;
4. A claim would require external literature to confirm.

Each item needs `item`, `reason` and `locator` so the author can act on it directly.
