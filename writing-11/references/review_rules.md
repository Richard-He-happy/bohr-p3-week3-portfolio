# Checks, invariants and failure handling

This file states what the code actually computes, so a reviewer can tell a
computed result from a described one.

## 1. Findings any run can produce

Each finding carries `id`, `check`, `severity`, `status`, `message`, `locators`,
`action`. High findings are copied into `pending_human` and `uncertainty`.

| Check | Rule | Severity |
|---|---|---|
| `quote_traceability` | anchor or evidence quote must hit a block after normalisation | high |
| `annotation_scope` | target outside the workorder, or a proposal that rewrites author text | high |
| `workorder_receipt` | every target needs an accepted or explicitly rejected item with a reason | high |
| `annotation_quality` | note under 60 characters, or two notes with identical text | warn |
| `annotation_novelty` | note introduces a number that no material contains | high |
| `draft_schema` | proposal is not an object, or has no target id | high |
| `coverage` | an outline chapter has no drafted section | warn |
| `terminology` | one abbreviation with several expansions; an abbreviation defined twice (warn if identical, high if not); used before its definition; two spelling variants of one word | high / warn |
| `numbering` | two captions sharing a number (warn); gaps in table/figure/equation numbering (info); `Section N` without a matching heading (warn) | warn / info |
| `citation` | `[n]` cited but absent from the reference list (high); listed but never cited (info); `[CITATION]`, `??`, `待补` placeholders (high) | high / info |
| `units` | one quantity expressed in mixed units of the same dimension | info |
| `numeric_conflict` | one context carries several values for the same unit | warn |

Range detection matters: `from 28.5 MPa to 41.2 MPa`, `between 0.05 % and 0.25 %`,
`从 28.5 MPa 提高到 41.2 MPa` and `0.05 % 至 0.25 %` are endpoints of one comparison,
not contradictory values, so both endpoints are excluded from the conflict scan.

## 2. What the checks deliberately do not decide

* Whether a note is *entailed* by the sentence it cites. Only verbatim presence,
  scope and numeric novelty are tested.
* Whether the source is scientifically right. A contradiction between two source
  values is reported with both sides and left in place.
* Whether a bibliography is complete when the materials carry no reference list.
* Whether a target id maps onto the paragraph the author meant; when the id has no
  explicit anchor the paragraph index is taken from its `P<nnn>` suffix and the
  receipt is marked `resolution: heuristic` plus an uncertainty entry.

## 3. Build-time invariants (`self_check.json`)

Recomputed from the artifacts just written, never asserted from memory:

| Invariant | Test |
|---|---|
| `contract_keys` | every `output_contract` key is present in `result.json` under its original name |
| `source_blocks_verbatim` | hashing the manuscript after removing EA blockquotes equals the hash of the untouched block sequence |
| `annotations_counted` | blockquote markers in the manuscript equal the number of applied notes |
| `preview_not_empty` | `export_preview.pdf` is larger than zero bytes |
| `chapter_files_written` | at least one file exists under `revised_chapters/` when source blocks exist |
| `faults_rejected` | all four deliberate invalid operations were rejected and left state untouched |

A failure is appended to `errors`, the status drops to `partial`, and the detail stays
in `self_check.json`. The check never aborts the run.

## 4. Pre-return checklist

- [ ] `init` ran; `work/source_index.json` lists every material and resolves every target.
- [ ] `work/draft.json` has exactly one item per target; each quote came from `show`, not from memory.
- [ ] `check` reports zero `high`; each remaining `warn` is understood and left visible.
- [ ] `build` printed a status you can defend (`ok`, or `partial` with named reasons).
- [ ] `manuscript.md` keeps every heading and paragraph; the only added text is inside `> **[EA-...`.
- [ ] `versions/diff_v1_v2.patch` adds blocks and deletes nothing.
- [ ] `workorder_receipt.targets[]` is `done` or `pending_human` with an actionable reason.
- [ ] `workorder_receipt.operation_requirements[]` has one entry per requirement, each pointing at evidence.
- [ ] `consistency_tables.json` covers terms, symbols, definitions, numbering, citations and claims.
- [ ] `pending_human` names every missing chapter, fallback note, unreadable material and unresolved id.
- [ ] No note introduces a value, citation, figure or section the materials do not contain.

## 5. Failure matrix

| Situation | The skill does | A human must |
|---|---|---|
| no `/input`, no case JSON | `status=input_error`, `errors` says why, exit 0 | supply the case directory |
| case JSON malformed | `status=partial`, error recorded, materials still indexed | repair the JSON |
| a material unreadable | that material `unreadable`, others proceed, degradation note | supply a text version |
| PDF without a text layer | `degraded`, no guessed text; `pdftotext` used when present | install `pdftotext` or supply text |
| `.xlsx` supplied | `skipped` with a note | export CSV |
| target id nowhere in the materials | `pending_human` with the id, no note invented | confirm the id or the chapter |
| id present without an anchor | `resolution: heuristic`, uncertainty entry | check the paragraph on the manuscript |
| draft absent or unparsable | every target gets a labelled fallback note and the run reports `partial` | swap each fallback for a reviewed note |
| quote taken from memory | rejected, reason in `change_log`, original state kept | re-read with `show` |
| two source values for one quantity | both kept, `numeric_conflict` finding | decide what the author meant |
| no reference list | citations carried verbatim, info finding | complete the bibliography |
| interrupted run | partial `result.json` already on disk | rerun `build` |

## 6. Maintenance

Checks live in `scripts/consistency.py`; acceptance, quoting and locator resolution
live in `scripts/audit_checks.py`; file reading and rendering live in `scripts/docio.py`.
`run_revision.py` only orchestrates. Keep `build` deterministic: same index plus same
draft must produce byte-identical `manuscript.md`. A new material type is one branch
in `docio.guess_kind` plus one branch in `docio.index_material`, never a new dependency.

Budget reminder: 64 model requests and 900 s per case. `init` writes a legal partial
`result.json` before any parsing, so an interrupted run still leaves a valid artifact.
