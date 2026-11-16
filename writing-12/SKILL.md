---
name: research-to-reader
description: Agent skill that converts scientific source material into a publishable piece for a named readership, genre and word budget. It indexes the material into citable paragraph locators, requires a complete draft body (not an outline), runs deterministic checks on verbatim quotes, numeric/unit drift, source coverage and output contract keys, then renders deliverable.md and fills result.json with status, provenance, uncertainty and change records. Use when a paper or technical report must become an industry brief, grant-application summary, popular-science article or journal abstract, or when one result must be retold for several audiences while numbers, conditions and claim strength stay intact.
version: 1.0.0
---

# research-to-reader: audience- and genre-aware rewriting

## 0. At a glance

Four steps: `init` builds the index → `show` reads source paragraphs → write `draft.json` → `check` until clean → `build` publishes.

| Artifact | What it is |
|---|---|
| `deliverable.md` | The publishable piece: adapted body plus change rationale, paragraph-by-paragraph provenance, retained-fact ledger, change log, glossary, open questions, self-check |
| `result.json` | Status machine, all original `output_contract` keys backfilled, source ledger, uncertainty, fidelity summary |
| `work/index.json` | Material and paragraph index (the authority for every `M1:P3` locator) |
| `work/check.json` | Full verdict of the latest deterministic check |

Three hard lines: **never alter source numbers or units**, **never add conclusions the material does not support**, **remove redundancy, not evidence**.

## 1. When to use it, when not

Use it to explain a paper or report to non-specialists; to produce a brief, an abstract and a popular article from one result; to compress into a hard word budget without losing conditions or sample sizes; to hand the original author an editable revision.

Do not use it for writing without source material, for inventing data, citations, institutions or market claims, for statistical inference, or as a substitute for peer review.

Red line: anything about market size, cost, schedule or mechanism that the source does not state must not be added; material marked confidential, unpublished or personal data is not extrapolated and goes into `pending_human`.

## 2. Runtime facts

- Input: `/input/case.json` (holds `output_contract`), `/input/task.md`, plus any files under `/input` (PDF, DOCX, XLSX, CSV, MD, JSON, TXT, images).
- Workspace: `/app/work/` with `index.json`, `draft.json` (template written by the first `init`), `check.json`.
- Output: `/app/output/deliverable.md` and `/app/output/result.json`. Before `build`, `result.json` is a valid partial placeholder.
- Dependencies: Python 3 standard library only; offline; independent of the current directory (scripts anchor on their own file location).
- Exit codes: always 0. Failures are recorded in `result.json.errors` and existing artifacts are kept.
- Budget: 900 s, 64 model requests, 16384 tokens per reply. Near 780 s, run `build` and stop; do not spend another round polishing prose.

Global flags `--input/--output/--work` must appear **before** the subcommand:

```
python3 scripts/redraft.py --input /input --work /app/work --output /app/output init
```

Write the deliverable in the language of the case material (normally Chinese); the tooling itself is language-agnostic.

## 3. Survey first, then write

`init` recursively scans `/input`, detects each material by extension plus file header, splits it into citable paragraphs numbered `M1:P1`, `M1:P2`, …; infers the reader, genre and length from the case and task text while recording which phrase it matched; extracts numbers and abbreviations from text materials; and writes the first partial `result.json` plus an empty `draft.json`.

Read all four blocks it prints: material list (with parser and degradation flags), work order (reader/genre/length/contract keys), paragraph list, key numbers and abbreviations.

Then read the source with `show`:

```
python3 scripts/redraft.py show --ids M1:P1-M1:P12
python3 scripts/redraft.py show --grep "limit|sample|dose" --limit 20
```

Always read: abstract or first section, every paragraph carrying numbers, limitations and conclusions, figure and table captions. **Judge by the text you read, never by file names, labels or field assumptions.**

## 4. Who does what

- Scripts do the mechanical work: index, print located source text, validate the draft, render, backfill the contract, record status.
- The Agent does the judgement work: define the reader profile and explanation depth, decide keep/compress/cut, **write the actual adapted body paragraph by paragraph**, register retained facts, write provenance and change reasons.
- The most common failure is not "bad prose" but "only advice or an outline". `check` raises `too_short` when the body is under 45% of the target; `build` without a usable draft can only emit a deterministic fallback and downgrades to `partial`.

## 5. The draft (draft.json)

Field details: `references/worknote-format.md`. Six blocks are mandatory:

1. `audience`: label, profile, reading goal, assumed knowledge, depth, terminology policy, claim-strength policy.
2. `genre`: label, conventions, word target.
3. `headline` / `deck`: one-sentence conclusion, optional deck.
4. `sections`: **the actual body**. Each entry gets `title`, `text`, `cites` (source locators) and `strength` (established / preliminary / hypothesis).
5. `preserved`: retained-fact ledger with `value`, `locator`, verbatim `quote` and `treatment` (kept/reworded/moved/condensed).
6. `map`, `changes`, `removed`, `glossary`, `pending`, `uncertainty`: paragraph provenance, change records, deletion rationale, terminology unification, open questions, uncertainty.

Write prose in `text`, not bullets; one idea per paragraph with the conclusion first; every locator must come from the real paragraph list printed by `init`.

## 6. The check gate

```
python3 scripts/redraft.py check
```

The report has `[错误]` (errors) and `[提示]` (warnings) levels and is saved to `work/check.json`. Errors must reach zero before `build`:

| Error | Meaning | Fix |
|---|---|---|
| missing / empty field | One of the six blocks is incomplete | Complete it, re-check |
| empty section / `too_short` | Body is an outline or too thin | Write real prose; do not expand headings |
| `*_quote_miss` | A quote is not in the source | Use a real quote; **never edit the source** |
| `locator_not_found` | Locator not in the index | Re-read the `init` paragraph list |
| `number_not_in_source` | The body has a number the source does not | Restore the original number; put conversions in `pending` |
| missing `action` / `reason` | A change cannot be reviewed | Add the action and the reason |
| `key_numbers_missing` | All unit-bearing key numbers were dropped | Bring the result numbers back |

Warnings (`short`/`long`/`preserved_not_in_body`/`terms_lost`/`low_paragraph_coverage`/`unit_variant`/`meta_discourse`) do not block delivery, but each one must be read and either accepted or fixed. `meta_discourse` is new: phrasing such as "this article will discuss …" is flagged, because an adapted piece states content directly.

Repair order: fix the quote → fix the locator → move the unverifiable item into `pending`. Editing the source to make a quote pass is forbidden.

## 7. Build: publish the piece and close the result

```
python3 scripts/redraft.py build
```

Writes `deliverable.md` (eight fixed sections) and **unconditionally** rewrites `result.json`:

- Every original key of `output_contract` is copied back under its exact name. Anything that cannot be mapped becomes `null` or `[]`, and a `contract_fill` tally plus a `degradations` entry records it.
- Fixed fields: `case_id`, `status`, `deliverable`, `preserved_facts`, `evidence_map`, `change_log`, `changes`, `glossary`, `removed`, `transformation_spec`, `sources`, `uncertainty`, `pending_human`, `errors`, `degradations`, `self_check`, `fidelity_summary`, `runtime`.
- `status` values: `ok` (structure, quotes and numbers all pass), `partial` (gaps exist but the piece is usable; gaps go to `errors`/`pending_human`), `insufficient_evidence` (no parseable factual material), `input_error` (the input itself is unparseable).
- Each entry in `sources` carries a `method`: `pdftotext`, `builtin-pdf`, `docx-xml`, `xlsx-xml`, `text`, `image-no-ocr` and so on; every parser downgrade also lands in `degradations`.
- `degradations` spans both stages: problems found during `init` (broken `case.json`, image-only material, low-confidence PDF parsing) are carried through `index.json` into `build`, so a re-run does not lose them.
- `fidelity_summary` is new: a machine-readable roll-up of contract fill, quote hit rate, numeric drift, retained-fact tally, paragraph coverage and abbreviation retention — one place to recompute the evidence.

## 8. Fidelity rules

- One locator syntax only: `M<material>:P<paragraph>`; ranges such as `M1:P3-M1:P6` are accepted.
- A `quote` must appear verbatim in the source. Whitespace and full/half-width differences are tolerated; re-wording, additions and translation are not.
- Every number in the body must exist in the source, unit spelling included. Any conversion or rounding must be explained in `note` and listed in `pending`.
- Sample sizes, conditions (species, dose, duration, platform), baselines and figure/table numbers travel with the conclusion they belong to.
- Correlation must not be written as causation, preliminary results must not be written as settled, and one concept gets one name for the whole piece.

## 9. Reader, genre, claim strength

Decide in this order: reader knowledge → explanation depth and term density → examples and length allocation. `references/readership-map.md` holds the audience matrix and five genre skeletons.

Claim strength has exactly three levels, written to `sections[].strength`:

- `established`: the source states it with statistical support;
- `preliminary`: in-vitro, single experiment or small sample — the adaptation must keep "preliminary / to be validated";
- `hypothesis`: mechanistic speculation, application extrapolation, commercial outlook — soften in prose and put it in `pending_human`.

Strength may stay level or go down. It never goes up.

## 10. Pruning priority

| Tier | Content | Treatment |
|---|---|---|
| Must keep | Main conclusion, key numbers and units, conditions and samples, figure/table identifiers, limitations and uncertainty | Keep verbatim or equivalently; register in `preserved` |
| Compressible | Method parameters, instrument models, reagent lot numbers, literature stacking | One summary sentence; numbers unchanged |
| Removable | Repeated phrasing, derivations irrelevant to this reader, acknowledgements, submission and funding details | Put in `removed` with the reason it is not evidence |

One test decides: after the cut, can the reader still judge the conditions under which the conclusion holds? If not, it was evidence.

## 11. Conflicts, gaps, human confirmation

- Reader and genre conflict (e.g. "for the public" plus "complete methods"): the reader wins, methods collapse into one sentence, and the conflict goes to `pending_human`.
- Length cannot hold the content: keep the must-keep tier, cut the removable tier, and explain the trade-off in the first section of the piece.
- The same metric appears with two values: list both, mark `uncertainty`, never pick one for the author.
- Missing citation or figure number: no placeholder digits — write "(no number in the source; to be supplied)" and add a `pending` item.
- Confidential or unpublished material: do not publish details; `pending_human` records "release requires authorization".

## 12. Failure handling

| Situation | Behaviour |
|---|---|
| `case.json` missing or broken JSON | Search recursively for a JSON containing `output_contract`; if none, use built-in fields and log a `degradations` entry |
| No `pdftotext` available | Fall back to built-in stream parsing; if the text is too sparse, flag `builtin-pdf-lowconf` and ask for human review |
| Material is an image | No OCR; record `image-no-ocr`; never invent a caption |
| One file fails to parse | Downgrade only that file, continue with the rest, log the name and cause |
| `draft.json` missing or unusable | `build` extracts source sentences deterministically as a fallback, sets `status=partial`, and marks the top of the piece "fallback draft, audience rewriting not done" |
| Exception mid-run | Still writes a valid partial `result.json` plus an explanatory `deliverable.md`; exit code stays 0 |
| Repeated runs | Artifacts overwrite; file set and status stay stable |

## 13. Pre-delivery checklist

- [ ] `deliverable.md` has all eight sections: adaptation rationale, body, paragraph provenance, retained facts, change records, glossary, open questions, self-check.
- [ ] `check` shows no `[错误]`, quote hit rate is 100%, numeric drift is 0.
- [ ] Every key claim has a `locator` in `evidence_map`.
- [ ] Read it as the target reader: no unexplained abbreviation, no bare formula, no invented terminology.
- [ ] `result.json` has every contract key, a `status` matching reality, and a recomputable `fidelity_summary`.
- [ ] Examples and illustrative outputs are marked "example".

## 14. Minimal invocation example (illustrative, not an official case result)

```
$ python3 scripts/redraft.py init
== material index ==
M1   sample_report.md  text  text   764 chars/  5 paras [material]
...
reader: 产业界  <- `产业界`
genre: 技术转化简报   length: 1000 chars
contract: case_id, deliverable, preserved_facts, evidence_map, change_log (5 fields)

# write /app/work/draft.json here; sections carry the full body
$ python3 scripts/redraft.py check
verdict ok | sections 4 | body 968 chars | quotes 7/7 | numbers 9 (drift 0)
$ python3 scripts/redraft.py build
status=ok fallback=False words=968 target=1000 files=['deliverable.md', 'result.json']
fidelity: quotes 7/7 | numeric drift 0 | contract 5/5
```

Material and numbers above are constructed to show the interface; official cases come from the platform `/input`.

## 15. Package, version, maintenance

| File | Responsibility |
|---|---|
| `SKILL.md` | This document: workflow, contract, rules, failure handling |
| `scripts/redraft.py` | CLI entry point and the four-step orchestration |
| `scripts/compose.py` | Index construction, draft template, rendering, result finalisation |
| `scripts/sourcekit.py` | Material readers, fidelity checks, contract binding (runs standalone for spot checks) |
| `references/worknote-format.md` | `draft.json` field dictionary, sample, check-code table |
| `references/readership-map.md` | Audience matrix, genre templates, pruning order, strength table, anti-patterns |

Version 1.0.0; standard library only; no network; no external services. All illustrative output is labelled as an example.

Maintenance: new file formats need no code change — `init` detects them by extension plus header. A new genre is one matrix row plus a structure paragraph in `readership-map.md`. Judgement changes belong in `sourcekit.inspect_draft`; `redraft.py` reuses its verdict. After touching a script, re-run `--help` (exit 0), one empty input, one broken JSON, and confirm a partial `result.json` is still produced.
