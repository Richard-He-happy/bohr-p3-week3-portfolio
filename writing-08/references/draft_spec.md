# Draft JSON spec and troubleshooting

`scripts/corpus.py::audit_draft()` implements the rules below. The script never rewrites your source text; it only lists mismatches.

## 1. Where the file goes and how it is picked

- Keep it under `work/`. Candidates are tried in this order: `--draft` on the command line, `workdraft.json`, `draft.json`, `translation_draft.json`, then any other `*.json`.
- Only an object whose `paragraphs` is a non-empty array counts as a draft. Files whose name contains `template` (the empty skeleton from `init`) are skipped.
- Several incremental draft files are fine; the first valid one wins.

## 2. The five keys

| Key | Expected value | If omitted |
|---|---|---|
| `case_id` | echo of the case id; falls back to the index value | harmless |
| `target_lang` | `en` / `zh`; inferred from source language and instruction | direction label may be wrong |
| `glossary` | array of `{term, target, locator, note}` | term check has no input |
| `paragraphs` | array of `{para_id, source_quote, translation, note}` | whole draft is ignored |
| `change_log` | array of `{para_id, action, original_quote, revised_quote, reason, locator}` | main deliverable still gets fallback entries |

A unit id (`para_id`) can only be copied from `work/index.json`; it looks like `M2-P007` (material number, `P`, three-digit unit). Do not invent or renumber it. `note` is free text and is ignored by the checks.

## 3. The five mechanical gates

**Gate 1 — coverage.** Every indexed unit needs a non-blank `translation`. Coverage `covered / expected` below 0.999 is a hard fail; blank translations are reported separately in `empty_translations`.

**Gate 2 — quote.** Both `source_quote` and the source unit are whitespace-squeezed (runs collapsed to one space, trimmed, NBSP treated as space) and then compared case-insensitively by substring. A miss adds a `quote_issues` entry: replace the quote with a real contiguous fragment, and **do not touch the source**.

**Gate 3 — numbers and units.** Digit tokens are matched by `\d+(?:[.,]\d+)*` after removing thousands separators; a token present in the source but absent from the target adds a `number_issues` entry. If the source carries a unit and the target carries none, the report records `unit:xxx` the same way.

**Gate 4 — citation markers.** `[12]`, `[3,4]`, `(Zhang, 2019)` and similar must appear whole in the target text; each missing marker is a `citation_issues` entry.

**Gate 5 — terms.** When a known term string occurs in the source unit, its target must occur in that unit's target text; English tolerates inflection via a 6-character prefix. Mismatches are `term_issues`.

Two findings are recorded without being fatal on their own: a duplicated `para_id` (actually this one does force `fail`) and a `para_id` absent from the index (`unknown_para_ids`, recorded only).

## 4. Report -> action table

| Report fragment | What it means | Fix |
|---|---|---|
| `coverage 4/5` + `missing: M2-P006` | a caption or reference entry was not translated | add one paragraph record, keep the source label |
| `quote not verbatim` | quote miscopied, stitched across units, or punctuation changed | use a real contiguous fragment of that unit |
| `numbers [12.5]` | value rounded, worded, or deleted | write the original value back; conversions go in `note` |
| `numbers ["unit:mg/L"]` | number translated, unit dropped | restore the unit, do not convert |
| `cites ["[12]"]` | marker turned into a footnote or deleted | reinsert it verbatim; only bracket style may change |
| `terms 光催化 → photocatalysis` | a different rendering slipped in | use the term-table rendering; if a variant is really needed, change the table first |
| `unknown_para_id M2-P009` | unit ids changed after re-running `init` | re-run `init` and re-align to the new ids |

## 5. Batching and fallback

- Draft the abstract and conclusion units, run `check`; then add figure/reference units and `check` again.
- `build` always completes. Without a usable draft it writes the skeleton (empty slots `[PENDING / 待译]`), sets `status=partial`, and records the gaps in `pending_human` and `degradations`.
