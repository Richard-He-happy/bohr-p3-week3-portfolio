# draft.json: field dictionary, sample and check codes

`init` writes an empty template to `/app/work/draft.json`. The draft only states *what* to write; layout and contract backfill belong to `build`.

## 1. A passing sample (illustrative values, not a real case)

```json
{
  "audience": {
    "label": "industry partners and investors",
    "profile": "engineering or business background, no hands-on experience with this assay",
    "reading_goal": "decide whether it can be deployed, what it costs, where the risk is",
    "knowledge": "understands basic statistics; unfamiliar with the abbreviations and platform here",
    "depth": "one layer of mechanism, no parameter derivation",
    "term_policy": "expand every abbreviation at first use; keep three core terms with one sentence each",
    "strength_policy": "bench-scale results stay 'bench scale'; scale-up outlook is listed as unverified"
  },
  "genre": {"label": "technical transfer brief", "conventions": ["conclusion first", "question-form subheadings"], "length_target": 1100, "length_unit": "chars"},
  "headline": "Packed-bed reactor holds oil conversion at 91.2%",
  "deck": "72 h continuous run, conversion fluctuation under two percentage points",
  "sections": [
    {"id": "S1", "title": "Where the cost sits", "text": "Full prose goes here ...", "cites": ["M1:P2"], "strength": "established"}
  ],
  "preserved": [
    {"id": "F1", "kind": "number", "value": "91.2%", "locator": "M1:P5",
     "quote": "conversion stayed at 91.2% (n = 6, 72 h)", "treatment": "kept", "note": "keeps n and duration"}
  ],
  "map": [
    {"section_id": "S1", "source_locator": "M1:P5", "source_quote": "conversion stayed at 91.2%",
     "relation": "condensed", "note": "two sentences merged, value untouched"}
  ],
  "changes": [
    {"action": "trim", "locator": "M1:P7", "original_quote": "...", "revised_quote": "...",
     "reason": "reagent lot numbers are irrelevant to this reader; compressed into one method sentence"}
  ],
  "removed": [{"item": "GC temperature programme", "locator": "M1:P7", "action": "delete", "why": "reproduction detail, not evidence"}],
  "glossary": [{"term": "FAME", "expansion": "fatty acid methyl ester", "usage": "fatty acid methyl ester", "locator": "M1:P3"}],
  "pending": [{"issue": "plant-scale cost figure is vendor material only", "why": "not peer reviewed", "action": "publish after author confirms a citable source"}],
  "uncertainty": ["bench-scale packed-bed result not yet validated on an industrial unit"]
}
```

## 2. Field dictionary

| Field | Required | Format and expectation |
|---|---|---|
| `audience` | yes | `label` plus `profile`/`reading_goal`/`knowledge`/`depth`/`term_policy`/`strength_policy`; write specifics, not "general readers" |
| `genre` | yes | `label`, `conventions` (structural habits of that genre), `length_target` as an integer cap |
| `headline` / `deck` | optional | One-sentence conclusion naming object and effect; `deck` is an optional one-line lead |
| `sections` | yes | At least three entries; `text` is body prose, not bullets; `cites` is `M1:P3` or a list; `strength` is one of three levels |
| `preserved` | yes | At least five entries; `value` + `locator` + verbatim `quote` + `treatment` (kept/reworded/moved/condensed) |
| `map` | yes | At least one entry per section; `section_id` must exist; `source_locator` must parse |
| `changes` | yes | Every edit needs `action` and `reason`; `original_quote` should be verbatim |
| `removed` | optional | What was cut or compressed, and why it is not evidence |
| `glossary` | optional | Abbreviation expansion and the single agreed wording; mandatory for public-facing pieces |
| `pending` / `uncertainty` | optional | Items needing author confirmation or flagged as uncertain; copied into `result.json` under the same names |

## 3. Check codes (`check` and `sourcekit.py` share them)

| Code | Level | Action |
|---|---|---|
| `missing_field` / `empty_field` | error | One of the six blocks is absent or empty; complete it |
| `section_empty` | error | A section has no body |
| `too_short` | error | Body under 45% of the target; treated as an outline |
| `section_quote_miss` / `preserved_quote_miss` / `map_quote_miss` / `change_quote_miss` | error | A quote is not retrievable; use a real one or fix the locator |
| `locator_not_found` / `map_locator_missing` / `map_section_unknown` | error | Locator does not match the paragraph index |
| `preserved_value_missing` / `preserved_locator_missing` | error | A retained fact lacks a value or a locator |
| `number_not_in_source` | error | Body carries a number absent from the source; restore the source value and log any conversion in `pending` |
| `key_numbers_missing` | error | Not one unit-bearing key number reached the body |
| `change_action_missing` / `change_reason_missing` | error | A change record lacks action or reason |
| `short` / `long` | warning | Body outside the 70%–150% band around the target |
| `preserved_not_in_body` | warning | A retained fact never appears in the body |
| `terms_lost` | warning | Most source abbreviations are absent (public pieces need the glossary) |
| `low_paragraph_coverage` | warning | Fewer than 15% of paragraphs have provenance entries |
| `unit_variant` | warning | Values match but unit spelling differs |
| `meta_discourse` | warning | Body contains preview phrasing such as "this article will discuss"; state content directly |
| `audience_label_missing` / `genre_label_missing` | warning | The adaptation rationale has no basis |

## 4. Writing conventions

- `text` states content directly; no "in this section we …" transitions.
- One idea per paragraph, conclusion in the first sentence, so a reviewer can verify paragraph by paragraph.
- Copy numbers, units, sample sizes and baselines exactly as written in the source (`91.2%`, not "about nine in ten").
- Cost, market or schedule claims absent from the source belong in `pending`, never in the body as conclusions.
- If a unit conversion is unavoidable, keep the source unit in the body, explain the relationship in `note`, and add a `pending` item for the author.
