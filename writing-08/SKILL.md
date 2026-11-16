---
name: bilingual-manuscript-weaver
description: Bilingual academic-manuscript workflow (EN<->ZH). The operator Agent reads every source unit and writes the target text by hand; runner.py only does the mechanical parts (extract text, slice units, verify fidelity, assemble deliverables). Outputs a paragraph-aligned bilingual manuscript, a locked term table, number/citation audit sheets, an evidence map, a change log and result.json. Unreadable material or unresolved terminology degrades to partial with explicit human-check items.
version: 1.0.0
---

# Bilingual Manuscript Weaver — operating manual

## 0. Four commands, one order

```bash
export SKILL="<directory holding this file>"
python3 "$SKILL/scripts/runner.py" --input /input --work /app/work --output /app/output init
#   read the index, open the source (or use show), then hand-write /app/work/workdraft.json
python3 "$SKILL/scripts/runner.py" --input /input --work /app/work --output /app/output check
python3 "$SKILL/scripts/runner.py" --input /input --work /app/work --output /app/output build
```

`runner.py` exposes the verbs below. `init` scans the case and leaves a legal partial `result.json` behind. `show` prints indexed source units with their locators. `check` diffs your hand-written draft against the index. `build` renders the deliverables and finalizes `result.json`. An additive fifth verb, `audit`, re-checks a finished package read-only (contract keys, deliverable, alignment row count, status honesty, fidelity rates) and writes `work/audit.json` — it is a safety net after `build`, not a replacement for the four-step order. Put the shared flags **before** the verb — that is how argparse parses them.

## 1. Scope

In scope: turning supplied research material (abstract, body text, figure/table captions, display equations, footnotes, reference entries) into the target language, in a form an editor can revise unit by unit. Trigger words: translate, bilingual, side-by-side, terminology lock, post-translation check.

Out of scope: writing without a source, claims that need external literature, OCR of text inside scanned images (register those as gaps only).

Hard limits: never introduce numbers, citations, mechanisms or conclusions absent from the supplied material; never strengthen or weaken the author's hedging or conditions; when something cannot be decided, park it in `pending_human` instead of guessing.

## 2. Runtime facts

- Inputs: `/input/case.json` plus attachments under `/input/`; an instruction sheet may also arrive as `/input/task.md`.
- Work dir `/app/work`; deliverables go to `/app/output/` and must include `result.json`.
- Dependencies: Python standard library only (3.8+), no network; code locates itself via `Path(__file__)` and does not care about the current directory.
- Overrides: `--input`, `--work`, `--output`. Defaults are `/input`, `/app/work`, `/app/output`; when a default path is absent the runner falls back to `input`, `work`, `output` under the current directory.
- Exit code: always 0. Failures are captured into `result.json` (`errors`, `degradations`) instead of being raised.
- Budget: 64 model requests / 900 seconds. Write first, polish later: after `init` you already hold a submittable partial. When fewer than ~120 seconds remain, run `build` and stop.

## 3. How inputs are discovered

1. Walk the input tree: try `case.json`, `input.json`, `task.json`, then any `case*.json`.
2. Decode with a chain: `utf-8-sig` (drop BOM) -> `utf-8` -> `gb18030` -> `big5` -> `latin-1`; undecodable bytes become replacement characters.
3. Claim fields by meaning, never by fixed key names. Instruction text may live under `task_instruction`, `brief`, `request`, `workorder` or `prompt`. Only `output_contract` is the delivery promise, and each of its keys must be echoed back unchanged. Material lists appear under `formal_inputs`, `artifacts`, `materials`, `runtime_files`. A supplied term base may be called `glossary`, `locked_terms`, `terminology` or `termbase`; supplied renderings win over everything else.
4. Detect material type from suffix plus magic bytes: PDF content streams are inflated with zlib; DOCX is unzipped and `word/document.xml` de-tagged; HTML is stripped of tags; plain text formats are read directly.
5. Material with no extractable characters (scanned PDF, raster image, unreadable archive) is recorded by name and reason with `quality=low` or `unreadable`, and listed as a degradation. Never guess body text from a filename or a domain label.
6. Every source unit gets a stable anchor: `M<index>:<filename>#P<three-digit unit>`. All evidence in later stages hangs off that anchor.

## 4. Who does what

| Stage | Owner | Output |
|---|---|---|
| `init` | script | legal partial `result.json`; `work/index.json` (materials, units, contract keys, supplied terms, acronym candidates); `work/workdraft.template.json` (empty skeleton) |
| reading | **Agent** | `show --para M2-P003`, `show --material M2`, `show --grep WORD`, `show --all`, or open the files directly; read every source unit verbatim |
| drafting | **Agent** | `work/workdraft.json`: source unit -> target text, plus term table and change log |
| `check` | script | `work/check_report.json`: coverage, quote, number, marker and term findings |
| `build` | script | seven deliverables plus a complete `result.json`; with no draft it emits the skeleton and sets `partial` |

> The one rule that matters: **runner.py never writes a translation.** Running only `build` produces a skeleton whose target slots read `[PENDING / 待译]` — a degraded submission. The only acceptable order is: read source -> hand-write draft -> `check` -> revise -> `build`.

## 5. The draft file (the only hand-written interface)

`work/workdraft.json`, fixed key names:

```json
{
  "case_id": "echo of the input id",
  "target_lang": "zh or en",
  "glossary": [
    {"term": "resolution", "target": "分离度", "locator": "M2:paper.md#P012", "note": "chromatography context"}
  ],
  "paragraphs": [
    {"para_id": "M2-P012", "source_quote": "verbatim contiguous fragment of that unit", "translation": "full target-language text", "note": "optional"}
  ],
  "change_log": [
    {"para_id": "M2-P012", "action": "translate", "original_quote": "source fragment",
     "revised_quote": "target fragment", "reason": "number kept verbatim / term locked", "locator": "M2:paper.md#P012"}
  ]
}
```

Notes:
- A non-empty `paragraphs` list is what makes a draft valid. Any `*draft*.json` under `work/` is discovered; `workdraft.json` is tried first.
- `source_quote` must be a **contiguous verbatim fragment** of that unit. It exists for verification only; do not paraphrase or stitch.
- Captions, table titles, footnotes and reference entries each become their own unit. Keep labels (`Fig. 3`, `图 3`, `Table 2`, `[12]`) and entry text in place.
- Drafting can be incremental: abstract and conclusions first, then figures and references; run `check` between batches.

## 6. The five gates behind `check`

1. **Coverage** — every anchor in the index needs one non-empty `translation`. A missing unit is a missing unit.
2. **Quote** — after whitespace squeezing (collapse runs, trim, NBSP as space) and case folding, `source_quote` must appear as a substring of the source unit. If it does not, pick a real fragment; **never edit the source to fit**.
3. **Numbers and units** — every digit string in the source (decimals, thousands separators, percents, `n = 3`, `95% CI`) must reappear verbatim in the target text. If the source carries a unit (`mg/L`, `°C`, `min`, `kPa`, ...) the target must carry units too. Chinese 万/亿 vs million/billion conversions go into `note` while the value stays equivalent.
4. **Citation markers** — `[12]`, `[3,4]`, `(Zhang, 2019)` must survive verbatim in the target text. Only bracket style may change; numbers and years may not.
5. **Terms** — when a term-table `term` occurs in a source unit, its `target` must occur in that unit's target text (English tolerates inflection by a 6-character prefix match).

Findings land in `work/check_report.json`. A `fail` verdict means hard problems: fix the draft and re-run. `build` is not blocked by `fail`, but the status will honestly say `partial`.

## 7. Deliverables and `result.json`

Seven core files under `/app/output/`, plus five verifiable assets that `build` writes beside them:

| File | Content |
|---|---|
| `translation.md` | main deliverable: locked term table first, then one block per unit (anchor, verbatim source, target text, note) |
| `glossary.csv` | columns `term,target,locator,note,status`; status is `locked` or `pending_human` |
| `alignment.csv` | columns `para_id,material,locator,kind,source,target,aligned,numbers_missing,terms` |
| `preserved_facts.json` | one record per number/marker: original value, landed flag, source fragment, anchor |
| `evidence_map.json` | per unit: verbatim source, target text, related terms, derivation note |
| `change_log.json` | operator edits plus script fallbacks (`actor=agent|script`) |
| `result.json` | contract echo + status + counts + five additive asset summaries |

Rules for `result.json`:
- Keep every `output_contract` key exactly as spelled; unknown keys are not dropped. Point keys at their deliverable paths; use `null` or `[]` when nothing applies.
- Fixed root fields: `case_id` (echo of the input), `status`, `deliverable`, `preserved_facts`, `evidence_map`, `change_log`, `glossary`, `alignment`.
- Honesty fields: `sources`, `uncertainty`, `pending_human`, `errors`, `degradations`, `changes`, `metrics`, `runtime`.
- Asset summary fields are additive only: `golden_standard`, `diff_report`, `version_history`, `run_log`, `self_check`, `verifiable_assets`. They describe the review trail; removing them never changes the delivery contract.
- `status` semantics: `ok` = every unit done and checks pass; `partial` = gaps exist; `insufficient_evidence` = no readable material at all; `input_error` = structurally broken input.

### 7.1 The five verifiable assets (written by `build`)

| File | What it proves | How it is produced |
|---|---|---|
| `golden_standard.json` | expectation ledger per delivery paragraph, glossary entry, alignment row, preserved fact, contract key and artifact; every item carries a `source.locator` + verbatim `source.quote`; top-level `quote_hit_rate` | derived only from `/input` material, `output_contract`, `task_instruction` and package rules; never from the Agent draft |
| `diff_report.md` | item-by-item actual-vs-golden verdict (met / deviation / missing / n/a), per-layer scoreboard and gap table with locators | rendered from the files on disk right after the core deliverables |
| `version_history.md` | static v0.1.0 -> v1.0.0 ledger with reason per version, compatibility promise, three-scope rollback playbook, plus a runtime section for this build | static ledger in `scripts/assets.py`; runtime section appended at build time |
| `run.log` | real journal: UTC timestamp, elapsed seconds, phase, ok flag and counts for every step of this build; summary carries status and `exit_code: 0` | appended to `work/run_events.jsonl` by every verb, rendered at build time |
| `self_check.json` | machine receipt: contract keys + fixed root fields, main-artifact and counter agreement, 100% verbatim quote re-check, number/fact consistency, degraded-input probes (empty input, corrupt `case.json`, real `init`), exit-code-zero policy, assets present | runs the CLI as subprocesses in a temp dir; never recurses (`W08_ASSET_PROBE` guard) |

Asset rules:

1. The asset layer is additive. It is wrapped in `try/except`; a failure is recorded in `errors`/`degradations` and the seven core files plus `result.json` still finalize with exit code 0.
2. `self_check.json.ok` means "no hard mechanical failure". Content gaps (e.g. a number not yet in the target) are surfaced by `status=partial` and `diff_report.md`, not hidden.
3. A reviewer reads `run.log` first, then `self_check.json`, then the `diff_report.md` gap table; `golden_standard.json` is the arbiter when the two disagree.
4. Deleting the five assets does not invalidate the core delivery; the next `build` recreates them.


## 8. Four fidelity red lines

- **One rendering per term.** Abstract, body, figure and table captions, footnotes and appendix must use the same wording. Priority: supplied term base -> frequent acronyms -> domain noun phrases. Resolve ambiguous words (`resolution`, `significant`) once for this manuscript and justify it in `note`; do not expand acronyms the source never expanded.
- **Numbers stay put.** Digits, precision, ranges, years, sample sizes, `p` values, confidence intervals, concentrations and temperatures are copied literally. `12.7%` must not become `13%`; `n = 3` must not become a word.
- **Structure stays in place.** Unit maps to unit, order unchanged, figure/table numbers unchanged; reference entries (authors, year, journal, volume/pages, DOI) are verbatim; display equations, sub/superscripts, Greek letters and material/gene names (`TiO2`, `·OH`, `p = 0.03`) are copied as-is.
- **Semantic strength does not drift.** Keep the scope of negation, the conditions (`under UV`, `at pH 3`), the evidence ladder (`suggests / indicates / demonstrates`) and the hedges (`may / likely / up to`) at the same level — `suggests` must never become "proves". Additions are limited to grammatical necessities (subject, connective, classifier); omissions are limited to duplicated function words and articles; qualifiers, quantities and markers are never dropped. Third-party claims stay third-party.

## 9. What must go to the author (`pending_human`)

- No accepted rendering exists, or two renderings are both current in this field (choose one and flag it).
- The source contradicts itself on numbers (body says 95%, table says 92%): keep both, note the conflict, do not arbitrate.
- Unclear cross-unit reference, broken sentence, missing page, text inside an image, scanned PDF with an empty text layer.
- A conclusion that would need external literature: do not write it, list it for confirmation.

Each item states `item`, `reason`, `locator` so the editor can jump straight to it.

## 10. Failure handling

| Situation | Script behaviour | Status |
|---|---|---|
| `case.json` missing or invalid JSON | keep looking for other case files and readable material; fill unknown contract keys with `null` | `partial` / `input_error` |
| Material is an image, Office package or archive | record name and reason, ask for human reading, never guess content | `partial` + `pending_human` |
| Thin or CID-encoded PDF text layer | keep whatever text was extracted, mark `quality=low` | `partial` + `degradations` |
| Draft missing or incomplete | skeleton delivery: full bilingual structure, empty slots marked `[PENDING / 待译]` | `partial` |
| Input directory empty | nothing invented; empty `sources` plus structural skeleton | `insufficient_evidence` |
| One material fails to parse | only that material degrades; others still get indexed | depends on coverage |
| A few numbers/terms did not land | recorded in `number_issues`/`term_issues` and `pending_human`, no abort | depends on other units |

## 11. Pre-handoff checklist

1. `result.json` parses, contract keys are present, `case_id` matches the input.
2. Manuscript unit count equals index unit count and no `[PENDING / 待译]` slot remains (or every gap is listed in `pending_human`).
3. In `alignment.csv`, `aligned` is `yes` everywhere and `numbers_missing` is empty.
4. `glossary.csv` has no empty `target`; any such row must also appear in `pending_human`.
5. `preserved_facts.json` has no `present_in_target=false`; if it does, the reason is written down.
6. `status`, `errors`, `degradations` and `pending_human` reflect reality — not cleared to look tidy.
7. Read the abstract and conclusion once more: no conclusion sentences were invented.
8. The five verifiable assets exist and are non-empty; `self_check.json` reports `ok: true`; `diff_report.md` has no `missing` core expectation (content deviations are allowed only when `status` is `partial`).

## 12. Interface example (illustration only, not a case result)

```text
$ runner.py --input ./input --work ./work --output ./out init
case_id: EXAMPLE-NOT-A-TEST-CASE
  M1  abstract.md  kind=text  quality=ok  chars=390  units=6
committed: 6 | contract keys: case_id, deliverable, preserved_facts, evidence_map, change_log | given terms: 1
NEXT: read the source, then hand-write work/workdraft.json

$ runner.py --input ./input --work ./work --output ./out show --para M1-P002
[M1-P002] M1:abstract.md#P002 (body, 140 chars)
……

$ runner.py --input ./input --work ./work --output ./out check
verdict: pass | coverage 6/6 (1.0)

$ runner.py --input ./input --work ./work --output ./out build
status: ok | paragraphs: 6 | translated: 6 | glossary: 5 | verdict: pass
```

The snippet above documents the interface only; it is not output from any official case.

## 13. Package map and maintenance

```
SKILL.md                                  this manual
scripts/runner.py                         CLI: init / show / check / build (+ additive audit verb)
scripts/corpus.py                         text extraction, unit index, draft audit, result assembly
scripts/assets.py                         verifiable-asset layer: golden standard, diff, version
                                          history, run log, self check (additive; never blocks build)
references/draft_spec.md                  draft fields, gate semantics, troubleshooting
references/translation_quality.md         term / number / marker / register decision rules
references/templates_and_fallbacks.md     term-table, bilingual block and pending templates + six exception paths
```

Version 1.0.0; standard library only; a run takes seconds; nothing to install. To support a new material type, extend `corpus.read_material`. To change a verification rule, extend `corpus.audit_draft`. Delivery keys follow the input `output_contract` automatically, so the CLI does not change. The unit index, verbatim-quote check and number/marker comparison can be reused for proofreading, reviewer-reply drafting and terminology consistency inspection. The asset layer is deliberately read-only with respect to the core delivery: `assets.publish()` runs after the seven deliverables exist and only adds files plus five `result.json` summary keys.
