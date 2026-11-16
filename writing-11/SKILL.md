---
name: chapter-edit-ledger
description: Sectioned long-document revision driven by an organizer edit workorder. Loads chapter materials, indexes every block into a locatable anchor, lets the agent author one source-grounded editorial annotation per target paragraph, then re-verifies every quote, keeps all author text byte-identical and returns an editable manuscript plus per-target receipts, evidence map, preserved-fact inventory, change log, six-category consistency ledger and a rendered PDF preview. Trigger on degree-thesis chapters, long reports, paragraph target ids such as C01-P002, chapter-level revision, terminology/symbol/numbering consistency, citation anchoring, or any reviewable record of what a machine changed in a manuscript.
version: 1.0.0
---

# Chapter edit ledger

## 1. Scope: what this skill does and refuses to do

This skill performs **one class of task**: a long document arrives as sectioned
chapters together with an edit workorder that names paragraph-level targets, and each
target must receive exactly one editorial annotation that is traceable to the supplied
text. It is a revision *harness*, not a text generator: it indexes the materials,
tells the agent which block each target resolves to, validates the notes the agent
writes, assembles the manuscript, and reports cross-chapter consistency.

It will not:

* rewrite, paraphrase or delete author sentences, or "improve" wording;
* create a citation, a DOI, a figure, a table, a section or a measurement;
* resolve a contradiction between two source statements — both sides are reported;
* claim that source-derived working chapters amount to a finished degree thesis;
* call a remote service, a cooperation account, Word revision XML or a network API.

When material is missing, the gap is written into `pending_human` and left open.

## 2. Triggering and preconditions

Use it when at least one of these is true:

- paragraph or block ids (`C01-P002`, `T01-P057`) appear in the task and in the materials;
- the task says "revise / annotate / 修改 / 批注 / 章节" over multi-chapter text;
- a workorder lists `target_ids` and operation requirements;
- the reviewer needs a change record, a consistency report or a preserved-fact inventory;
- the text is long enough (roughly >8k words, or several files) that reading it once is
  not enough to keep terminology and numbering consistent.

Do not use it for open-ended drafting from scratch, for pure translation, for
proof-reading with no source of truth, or when no material file is available at all.

Preconditions: a readable case file, at least one text-bearing material, and — for full
credit — a workorder. Without a workorder the run still executes, but receipts cover
targets only and `uncertainty` records the missing scope.

## 3. Runtime contract

| Item | Value |
|---|---|
| input | `/input/case.json` (or any JSON with `case_id`/`output_contract`), `task.md`, materials under `/input/**` |
| work dir | `/app/work` — `source_index.json`, `draft.json`, `draft_template.json`, `check_report.json` |
| output dir | `/app/output` — `result.json` plus the artifacts in section 9 |
| dependencies | Python 3.9+ standard library only; `pdftotext` used only if already installed |
| network | never |
| working directory | irrelevant: every path comes from a flag, an environment variable or `__file__` |
| exit code | `0` on every path, including failure |
| partial safety | a legal partial `result.json` is written before any parsing |
| budget | 64 model requests / 900 s per case; `build` finalises unconditionally |

Paths may be overridden with `--input`, `--out`, `--work`, or `INPUT_DIR` / `OUT_DIR` /
`WORK_DIR`. When `/app` does not exist the defaults fall back to `./output` and
`./work`, so the same commands run unchanged in a local shell.

## 4. Package layout

| File | Role |
|---|---|
| `SKILL.md` | this contract, workflow and boundary statement |
| `scripts/run_revision.py` | CLI: `init`, `show`, `check`, `build`; orchestration only |
| `scripts/docio.py` | file typing, text/JSON/docx/pdf reading, block splitting, previews, chapter export, result writing |
| `scripts/audit_checks.py` | locator resolution, verbatim quoting, draft validation, acceptance, fault probes, CLI (`audit`, `quote`, `ledger`) |
| `scripts/consistency.py` | manuscript scan, preserved facts, six ledgers, ledger and report rendering |
| `references/io_contracts.md` | draft schema, result schema, locator grammar, ledger schema |
| `references/review_rules.md` | every computed check, invariants, failure matrix, maintenance |

## 5. The four commands

```bash
python3 scripts/run_revision.py init  --input /input --out /app/output
python3 scripts/run_revision.py show  --target C01-P002
python3 scripts/run_revision.py check
python3 scripts/run_revision.py build
```

### 5.1 `init`

Writes the partial result, locates the case file and the workorder, types every
material by magic bytes, splits prose into sections and blocks, attaches `<!-- ID -->`
markers to the block that follows them, resolves every target, and prints:

* the material index with section locators and the first blocks;
* the workorder task and its operation requirements;
* for each target: `item id → locator` plus the exact paragraph text.

It also writes `work/draft_template.json`: one skeleton item per target with a real
anchor sentence and a real locator, ready to be filled.

### 5.2 `show`

Prints one target: locator, anchors, full block text. Use it instead of recalling a
sentence — every rejected quote in practice came from typing instead of reading.

### 5.3 `check`

Validates `work/draft.json` without touching the manuscript: target scope, verbatim
anchors, verbatim evidence, note length, duplicate notes, numeric novelty against the
materials, missing receipts, outline coverage. Writes `work/check_report.json` and
prints `high`/`warn` counts plus the target coverage ratio.

### 5.4 `build`

Re-runs the same validator, applies only accepted items, and produces the manuscript,
the chapter exports, the patch, the rollback proof, the fault probes, the consistency
report and ledger, the previews, the auxiliary JSON records, the self-check, the five
review assets of section 9 and finally `result.json`. A target the draft does not cover
receives a deterministic fallback note
(anchor sentence plus the nearest related passage by word overlap) marked
`generated_by: deterministic_fallback`, `needs_review: true`, and the run reports
`partial`.

## 6. Writing an annotation that survives verification

A note is accepted only when all of these hold:

1. `target_id` is inside the workorder.
2. `anchor_quote` occurs verbatim inside that target block.
3. `text` is at least 40 characters (60 to avoid a `check` warning).
4. every `evidence[].quote` occurs verbatim somewhere in the materials.
5. it introduces no number that the materials never state.

A good note does three things in two to four sentences: states what the paragraph
establishes, states the condition or limitation the claim depends on (quoted from the
text), and says what a reader may therefore conclude. It never adds a citation, a
percentage, a sample size or an interpretation the source does not support.

Example shape (illustrative, not a case result):

> The reported strength is a mean over five specimens at 5 mm/min. The paragraph gives
> neither specimen conditioning nor test temperature, so the number supports a
> within-study comparison between print settings rather than an absolute material
> property.

## 7. Locator grammar and quote verification

Locators are generated, printed, and then copied:

- prose: `chapters/ch03.md §2 Materials and methods ¶2`; a heading is `... (heading)`;
- JSON: `chapters/ch03.json #C01-P057`, or `#/<json/path>` for dicts without an id;
- delimited text: `data.csv #row 12`.

Comparison normalises NBSP, curly quotes, en/em dash, minus sign and `ﬁ`/`ﬂ` before
searching inside one block; cross-block hits are reported as such. A failed quote is
rejected with a reason, never adjusted into a match. Ids without an explicit marker
fall back to the paragraph index implied by the `P<nnn>` suffix and are labelled
`resolution: heuristic`.

## 8. Cross-chapter consistency: the six ledgers

`consistency_tables.json` and `consistency_ledger.md` hold six ledgers, all computed:

| Ledger | What it records |
|---|---|
| terms | abbreviations, their source expansions, use count, first locator, conflicting expansions |
| symbols | symbols defined by a `where X is …` pattern and whether they carry one meaning |
| definitions | labels defined more than once, with distinct wording and a status |
| numbering | per label: referenced numbers, caption numbers, duplicate captions, gaps |
| citations | cited numbers, listed numbers, cited-but-unlisted, never-cited, placeholder blocks |
| claims | conclusion-bearing sentences with polarity and whether they carry a quantity |

Conflicts are listed with both sides and a `resolution` string saying who decides.
The ledger is a table, not a verdict: it does not prove a claim true, it does not judge
entailment, and an empty row means the pattern was not found, not that nothing exists.
This is the deliberate answer to "a mechanical inventory alone is not scientific
verification": the ledger keeps locators so each row can be re-read in context, and
the numeric scan ignores stated ranges (English and Chinese forms) instead of
reporting endpoints as contradictions.

## 9. Deliverable inventory

Primary: `manuscript.md` (all source blocks verbatim, notes as blockquotes) and
`revised_chapters/<material>.md` (editable chapters with paragraph ids restored).
Supporting: `revised_manuscript.md`, `export_preview.pdf`, `manuscript_preview.html`,
`versions/{v1_original.md,diff_v1_v2.patch,rollback_check.json}`,
`consistency_report.md`, `consistency_tables.json`, `consistency_ledger.md`,
`revision_records.json`, `operation_receipts.json`, `evidence_map.json`,
`change_log.json`, `pending_human.json`, `self_check.json`, `result.json`.

Review assets, written by `build` in the same directory and referenced from `result.json`:
`golden_standard.json` (expected sections, word counts, citations, figures and pending
items, each with a locator and a verbatim quote), `diff_report.md` (actual run vs the
golden standard, item by item), `version_history.md` (static v0 to v1.0.0 chain plus the
runtime rollback record), `run.log` (the real build log) and `self_check.json` (contract,
main products, quote counts, fallbacks and exit code). They are projections of the
verified run: no new source text, no new fact, and every entry stays locatable.

The PDF is a real PDF 1.4 file with a text layer for ASCII content; CJK glyphs cannot
be embedded without a font file, so they appear as `?` and the file says so in its own
header line. `manuscript.md` and the HTML preview remain authoritative for those
characters.

## 10. Invariants and the build-time self-check

`build` recomputes six invariants after writing the artifacts and stores them in
`self_check.json`: contract keys present under their original names, source blocks
verbatim (hash of the manuscript minus blockquotes equals the hash of the original
sequence), blockquote count equals applied notes, preview non-empty, chapter files
written when source blocks exist, and every fault probe rejected. A failure is
appended to `errors`, the status drops to `partial`, and nothing is hidden.

The rollback proof is computed, not asserted: blockquotes are stripped from the
manuscript, the result is hashed and compared with `v1_original.md`; the same
annotations are re-applied and compared with the assembled manuscript. Four deliberate
invalid operations (fabricated anchor, unknown target, invented evidence, malformed
draft) are pushed through the same validator that accepts real notes, and the receipt
records that the state did not change.

## 11. Degradation and failure matrix

| Situation | Behaviour |
|---|---|
| no `/input` or no case JSON | `status=input_error`, `errors` explains, exit 0 |
| case JSON malformed | `status=partial`, error recorded, materials still indexed |
| one material unreadable | that material `unreadable`, the rest proceed, degradation note |
| PDF without a text layer | `degraded`; `pdftotext` used when present, no invented text |
| `.xlsx` supplied | `skipped`, note recorded, nothing guessed |
| target id absent | `pending_human` with an action, no annotation invented |
| id present, no anchor | heuristic resolution, uncertainty entry, `resolution: heuristic` |
| no `draft.json` | deterministic fallback notes, `partial`, every fallback listed |
| quote not verbatim | item rejected with reason, original state kept |
| verifier module missing | build still assembles; the consistency block reports zero findings and says so |
| interrupted run | a partial `result.json` is already on disk; rerun `build` |

## 12. Honesty boundaries

* Source-derived working chapters are **not** a completed degree thesis; the run never
  claims otherwise, and `pending_human` keeps the missing frame visible.
* No remote client, no cooperation account, no Word revision XML: only local files.
* No invented experiment, value, unit or citation. Ambiguous units are neither
  converted nor corrected; they are reported.
* Status reflects reality: `ok` only when every target carries a reviewed note and no
  error, degradation or rejection occurred.
* Fallback notes are labelled and listed; they are never presented as reviewed prose.

## 13. Worked micro-example (illustrative, not a case result)

Materials: `chapters/ch05.md` with a `<!-- T07-B003 -->` marker before a results
paragraph; a workorder whose `target_ids` is `["T07-B003"]`; `output_contract` naming
`case_id`, `deliverable`, `preserved_facts`, `evidence_map`, `change_log`.

```bash
python3 scripts/run_revision.py init --input /tmp/case7 --out /tmp/out7   # 1 material, 7 blocks, 1 target
# draft one note: anchor_quote + text + evidence + rationale
python3 scripts/run_revision.py check                                     # 0 high, targets 1/1
python3 scripts/run_revision.py build                                     # status=ok, 1 applied
```

Shape of the receipt for that run (**example only, not a formal case result**):

| field | value |
|---|---|
| `case_id` | `T07` |
| `workorder_receipt.targets[0].status` | `done` |
| `…targets[0].locator` | `chapters/ch05.md §4 Results ¶1` |
| `…targets[0].annotations` | `["EA-01"]` |
| `version_control.rollback_equals_v1` | `true` |
| `deliverable.annotations_applied` | `1`, `source_words_rewritten` `0` |

## 14. Version, maintenance and known limits

Version 1.0.0, standard library only, tested on Python 3.12. No configuration file,
no service, no cached state outside `/app/work`.

Known limits: prose splitting is heading- and blank-line-based, so a document without
blank lines between paragraphs becomes one large block per section; tables inside
markdown stay plain text; `.xlsx` is not parsed; the PDF preview cannot embed CJK
glyphs; abbreviation and symbol detection need the patterns in `references/review_rules.md`
and miss free-form definitions. Above roughly 200k characters the run still works but
`init` prints only the first blocks — use `--max-blocks` and `--chars` to keep the
output readable, and `show` per target.

Maintenance: change checks only in `scripts/consistency.py`, acceptance rules only in
`scripts/audit_checks.py`, reading and rendering only in `scripts/docio.py`.
`run_revision.py` stays orchestration. Determinism requirement: same index plus same
draft must yield a byte-identical `manuscript.md`.
