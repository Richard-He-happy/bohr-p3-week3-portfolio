---
name: rebuttal-response-workbench
description: A controlled rebuttal workbench for manuscript revision drill materials. It reads a specified manuscript baseline and the organizer's reviewer-comment summary, expands every comment into actionable sub-requirements, assigns a decision and a tone register to each of them, applies the substantive edits to the baseline for real, and delivers a revised manuscript, a point-by-point response letter, a change locator table, a pending-evidence list and a checkable structured result. Use for reviewer-comment triage, response-letter or rebuttal drafting, revision application, and for auditing whether each claimed change is actually present in the delivered manuscript.
version: 1.0.0
---

# Rebuttal Response Workbench (writing-07)

This package is a small, inspectable pipeline: read the drill materials, split
reviewer comments into sub-requirements, decide each one, apply real edits to
the baseline, render the response letter, then audit the finished bundle.
Everything is driven by two stdlib-only Python entry points and a two-pass
edit-plan workflow, so no result depends on files outside the package.

## Ground rules of the drill (higher priority than any deliverable)

The materials are an exercise, not a genuine peer-review record:

- `materials/manuscript-baseline.md` (or whatever baseline file the case
  supplies) is an organizer baseline summary. `materials/reviewer-comments.md`
  (or the equivalent comment file) is an organizer-written comment summary.
  Neither file is a full manuscript, and the wording is not a verbatim referee
  report.
- Revision scope is exactly that baseline: do not invent missing sections, and
  do not add numbers, citations or statistical conclusions that the baseline
  does not contain.
- Never write, in any output, that a reviewer said X verbatim, that an
  experiment was re-run or supplemented, that the original authors revised
  something, that the editor accepted the paper, that the whole manuscript is
  fully revised, or that the original review report was verified online. The
  build step removes such sentences automatically.
- Missing material is not an excuse to skip doable edits. Anything the baseline
  can support must be revised; genuinely impossible items go to the
  human-confirmation list and are explained honestly in the letter.
- Public paper links identify the source only. They do not prove that the
  original review content was inspected.

## Environment and entry points

| Item | Value |
|---|---|
| Build | `python3 scripts/build_revision.py --input /input --output /app/output --work /app/work` |
| Audit | `python3 scripts/audit_bundle.py --output /app/output --input /input` |
| Dependencies | Python 3 standard library only; no network; no dependency on the current working directory (resources are resolved from the script location) |
| Exit code | Always 0; failures are reported in `errors` / `degradations` inside `result.json` |
| First write | A partial `result.json` is written before any real work; the final state overwrites it unconditionally |
| Budget | 64 model requests and 900 s per case; when roughly two minutes are left, finalize with whatever is already verified |

`--stage` defaults to `auto`: finalize when the work directory contains an edit
plan with a non-empty `edits` or `sub_overrides`; otherwise run pass one only,
producing the ledger without touching the manuscript body. Further flags:
`--plan` (explicit plan path), `--deliverable-name` (main artifact filename,
default `revised_manuscript.md`; override it when the case requires another name).

## How inputs are located

No fixed file names or key names are assumed; materials are found by meaning:

1. Read `/input/case.json` first. If absent, recursively look for a JSON file
   whose name contains `case`. Malformed JSON is recorded in `errors` and the
   scan continues.
2. Keep `case_id` and `output_contract` untouched. Pull the task instruction
   from `task_instruction`, `organizer_workorder`, `organizer_edit_workorder`
   or equivalent fields, whatever their exact key spelling.
3. Walk every `.md/.txt/.rst/.tex` file under `/input/**` and score it by name
   hints and body word frequency: manuscript-looking names (manuscript,
   baseline, draft, paper, 正文, 稿件, 论文) push a file toward "baseline";
   comment-looking names (comment, reviewer, referee, 意见, 审稿) or frequent
   reviewer/comment words in the body push it toward "comments". One baseline
   candidate wins, and at most four comment sources are used.
4. Other attachments (PDF, images, CSV/XLSX, DOCX, JSON) are only registered by
   path. Unparsed material becomes a gap entry in the human-confirmation list
   instead of guessed content.

## Two passes, in this order

**Pass one - build the ledger, leave the manuscript alone**

Call the build entry point once. It writes `comment_ledger.json`, which splits
each comment into sub-requirements (`C1.1`, `C1.2`, ...) with a category
(method/data/format/ethics/writing), an initial decision, an evidence status and
a suggested `P###` anchor.

**Pass two - write the plan, then apply it**

1. Read the ledger and fix `decision` and `tone` for every `sub_id`, writing the
   complete revised sentence for each change.
2. Save the plan to `/app/work/edit_plan.json` (shape in the next section; full
   schema and examples in `references/handbook.md`).
3. Call the same build command again. The script applies edits, verifies each
   claim, renders the letter and refreshes `result.json`.

Hard requirement: every sub-requirement that the baseline can support must have
an edit. Only items genuinely beyond the supplied material may stay edit-free,
and those need `evidence_status=not_provided` plus a reason in `sub_overrides`.

## Edit plan shape

```json
{
  "edits": [
    {"id": "E1", "comment_id": "C1", "sub_id": "C1.1", "op": "replace",
     "anchor": "P005",
     "original_quote": "a sentence that exists verbatim in the baseline",
     "revised_quote": "the complete replacement sentence",
     "reason": "why it changes", "decision": "accept",
     "evidence_status": "provided", "response_note": "extra note for the letter"}
  ],
  "sub_overrides": [
    {"sub_id": "C3.1", "decision": "partial",
     "evidence_status": "not_provided",
     "evidence_note": "why the supplied material cannot support it",
     "response_note": "what the letter says about it"}
  ],
  "pending_human": [{"item": "C1.2", "reason": "input a human must supply"}]
}
```

`op` is one of `replace` (default: find by `original_quote` and substitute),
`replace_all`, `append_after` (insert a paragraph after the anchor block) or
`append_end` (append at the end).
`decision` is one of `accept`, `partial`, `reject`, `clarify`, `invalid`.
`tone` may be omitted and is then mapped from the decision. `evidence_status`
is one of `provided`, `not_provided`, `not_applicable`.

## Ledger shape

One entry per comment, each carrying its sub-requirements:

| Level | Fields |
|---|---|
| Comment | `comment_id`, `source_label` (original heading, for numbering alignment), `raw_summary`, `decision`, `tone`, `change_ids`, `evidence_needed`, `sub_requirements` |
| Sub-requirement | `sub_id`, `text`, `type`, `decision`, `tone`, `anchor`, `anchor_score`, `change_ids`, `evidence_status`, `evidence_note`, `response_note`, `needs_human` |

The comment-level decision is rolled up from its sub-requirements: a single
distinct decision is propagated, a mixed set becomes `partial`. Letter wording
comes from the four tone-locked frame sets in `references/reply_frames.json`;
it is not improvised per run.

## What appears in the output directory

| File | Role |
|---|---|
| `revised_manuscript.md` (or the case-named main artifact) | The only manuscript: edited strictly on top of the baseline, with section levels and numbering preserved |
| `response_letter.md` | Point-by-point reply: one paragraph group per sub-requirement, with decision, tone, a `P###` locator and the verbatim revised sentence |
| `comment_ledger.json` | Central ledger: comment -> sub-requirement -> decision -> change -> evidence |
| `change_locator.json` | Per-change `P###` locator and verbatim quote, independently checkable |
| `evidence_pending.md` | Open items, evidence-status tally and runtime observations |
| `version_notes.md` | Version, baseline name, coverage numbers and scope notes |
| `pending_human.json` | Items requiring human confirmation, with reasons |
| `result.json` | Contract backfill, counters and verification report |

Locator convention: `P###` numbers the blank-line separated blocks of the
delivered file, counting heading blocks. Any Markdown viewer can therefore
recount the blocks; page numbers and editor line numbers are deliberately not
used because they do not survive a change of tool.

## Verifiable assets (v1.0.0)

Every build or finalize run also writes five additive evidence files next to the
deliverables. They are a side channel: the original entry points, CLI options and
result fields are unchanged, and `result.json` gains one summary per asset
(`golden_standard`, `diff_report`, `version_history`, `run_log`, `self_check`).

| File | What it proves | How to re-check |
|---|---|---|
| `golden_standard.json` | expected response/edit items, each with a source locator and a verbatim quote from the supplied materials, derived from `output_contract`, the organizer workorder and the review comments (`basis: contract` when there is no material source) | every `source.quote` is a literal substring of the named input file (`quote_verbatim`); `quote_block` gives its `B###` block |
| `diff_report.md` | the golden standard vs this run, item by item (met / deviation / missing, with the reason) | read the summary table and open the cited `P###` / `B###` / `case.json#…` locator |
| `version_history.md` | static evolution v0 skeleton → v1.0.0 (what changed, why, how to roll back) plus a section for this run | compare the run section with `result.json.counts` |
| `run.log` | real phase log: each phase, elapsed seconds, artifact count, degradations, exceptions and the exit code | walk the phase lines against the files in the output directory |
| `self_check.json` | machine receipt: contract-key completeness, main-artifact presence, verbatim-quote hit rate, counter consistency, empty/bad-JSON fallback probe and exit-code policy | every check carries `ok` plus the observed values; `failed` lists any red item |

The assets are written by `scripts/evidence_assets.py` (rendering in
`scripts/evidence_render.py`) from the same finalize step that writes
`result.json`. They are produced even when the input is empty or malformed
(status `input_error` / `insufficient_evidence`), and a failure in this side
channel is recorded in `issues` without changing the exit code.

## result.json expectations

- Every key of the input `output_contract` must be backfilled at the top level
  with its original name; absent values become `null` or `[]`, unknown keys are
  preserved, and `case_id` is copied unchanged.
- Fixed companions: `status` (`ok` / `partial` / `insufficient_evidence` /
  `input_error`), `deliverable`, `preserved_facts`, `evidence_map`,
  `change_log`, `counts`, `comment_ledger_summary`, `workorder_report`,
  `verification`, `sources`, `uncertainty`, `pending_human`, `errors`,
  `degradations`, `issues`, `changes`, `runtime`.
- `counts` reports at least: comments, sub-requirements, sub-requirements with a
  verified change, open items, `locator_hit_rate`, decision histogram and the
  evidence three-state histogram.

## Quality gates (one per scoring angle)

1. **Complete answers**: every comment in the comment source appears in the
   ledger; each sub-requirement gets its own row and decision. A generic "we
   have fully revised the manuscript" line is not acceptable.
2. **Accurate claims**: each plan `revised_quote` must occur verbatim in the
   final manuscript. The build locates and marks it (`hit`). A miss downgrades
   that sub-requirement to `partial` and files it for human confirmation; the
   source text is never massaged to make a check pass.
3. **Defensible evidence**: `evidence_status` stays within its three values;
   impossible items are `not_provided` with a reason; nothing may claim that an
   experiment was done or that an editorial decision exists.
4. **Consistent alignment**: letter positions come straight from
   `change_log.locator`, so letter and locator table are generated from one
   source. The audit additionally checks that every `P###` cited in the letter
   really exists in the delivered manuscript.
5. **No silent drift**: the digits of each edited sentence must be a superset of
   the original digits (`numbers_preserved`); any numeric change becomes a
   human-confirmation item instead of a quiet rewrite.
6. **Controlled tone**: four locked registers (accept / clarify /
   polite_rebuttal / appeal). `reject` and `invalid` need a factual re-check
   statement; no personal or emotional wording.

## Failure handling

| Trigger | Handling |
|---|---|
| Comments conflict with each other | Decide each on its own merits, state the trade-off rule in the letter, file the conflict for human confirmation |
| A comment contradicts the baseline | `decision=invalid`, `tone=appeal`, quote the baseline passage, never drop it silently |
| Baseline misses a section | Do not create a whole new section; explain inside existing paragraphs or file it for human confirmation |
| No experiment/data/citation can be supplied | `evidence_status=not_provided` plus a reason, stated honestly in the letter |
| Version mismatch | Treat the input baseline as the only version; record its filename in `version_notes.md` |
| Unreadable or permission-denied file | Log `errors`, keep going, deliver a partial bundle |
| Comment source missing | `degradations=comments_missing`, `status=insufficient_evidence` |
| Baseline missing | Placeholder deliverable, `status=input_error`, gap explained in the human list |
| An edit cannot be located | `issues=edit_not_applied`, the sub-requirement drops to `partial` |
| An out-of-scope claim appears | Delete the sentence and log `overclaim_removed` |

## Pre-delivery audit

```bash
python3 scripts/audit_bundle.py --output /app/output --input /input
```

The audit covers contract backfill, presence of required artifacts, `P###` and
verbatim-quote hits, decision completeness, digit preservation, out-of-scope
claim scanning, presence of verified changes for every `accept`, and the
letter-to-manuscript locator join. Any `ok:false` means going back to the plan,
or keeping an honest partial state.

## Minimal end-to-end example (example only, not a formal case result)

```bash
python3 scripts/build_revision.py --input ./mycase --output ./out --work ./work   # pass one: ledger
# edit ./work/edit_plan.json (one replace plus one sub_override in this example)
python3 scripts/build_revision.py --input ./mycase --output ./out --work ./work   # pass two: deliverables
python3 scripts/audit_bundle.py --output ./out --input ./mycase
```

Illustrative counters from a hand-made fixture: `comments_total = 3`,
`sub_requirements_total = 6`, `subs_with_verified_change = 3`,
`locator_hit_rate = 1.0`, `status = partial` because two evidence-type
sub-requirements stay open. These numbers demonstrate the interface only.

## Common failure modes this pipeline is built to prevent

| Failure mode | What usually goes wrong | What the pipeline does instead |
|---|---|---|
| Thank-you letter without substance | the reply says "we carefully revised everything" and no claim can be checked | a decision and a verified change locator are demanded per sub-requirement; `accepts_have_change` fails otherwise |
| Half-answered compound comment | only the methods half of a three-part request is addressed | the comment is expanded into ordered sub-requirements, each with its own row, decision and evidence state |
| Claimed change missing from the manuscript | the letter says a sentence was changed but the delivered text is untouched | every plan edit is located after application; a miss is downgraded and listed for human confirmation |
| Skipping work because material is thin | comments that the baseline can partly satisfy are waved away as out of scope | only items with a recorded `not_provided` evidence reason may stay edit-free, and the letter must explain them |
| Numeric drift while rewriting | a percentage or p-value silently changes while wording is polished | the digit multiset of each edit must cover the original digits; any change becomes a human item |
| Locators that cannot be reproduced | page or line references that only work in one editor | `P###` block indexes are counted from the delivered file itself, and the audit re-checks them |
| Overclaiming to look thorough | asserting that experiments were re-run or that the editor accepted the revision | out-of-scope sentences are removed at build time and logged as `overclaim_removed` |
| Silent version mixing | edits applied to a version other than the one supplied | one input baseline is treated as the only version and its filename is recorded in `version_notes.md` |

## Working order when time is tight

1. Pass one immediately; it is cheap and gives the ledger.
2. For each sub-requirement the baseline can satisfy, write the edit first;
   only afterwards compose the `response_note`.
3. Leave genuinely impossible items as `sub_overrides` and keep moving; do not
   let one missing dataset block the rest of the bundle.
4. Run pass two, then the audit. When the audit reports a miss, fix the plan and
   run pass two again; when time runs out, keep the current partial bundle and
   make the open items explicit rather than inventing success.

## Package inventory

```
SKILL.md                         metadata and this document
scripts/build_revision.py        input discovery, block/comment parsing, edit application, locator checks
scripts/audit_bundle.py          ledger construction, letter rendering, bundle assembly and audit (also standalone CLI)
scripts/evidence_assets.py       five verifiable assets: golden standard, self-check receipt and emitter
scripts/evidence_render.py       version ledger, run-log writer and golden-vs-actual diff report
references/comment_taxonomy.json comment categories, request cues, forbidden-claim patterns, decision and evidence rules
references/reply_frames.json     four-register reply frames in Chinese and English
references/handbook.md           plan schema, locator rules, field dictionary, reuse and self-check guide
```

## Maintenance

- Current version 1.0.0. To extend categories or vocabularies, edit
  `references/comment_taxonomy.json` only; no script change is needed.
- To change letter wording or register style, edit
  `references/reply_frames.json` only.
- After touching either script, rerun the audit above plus one minimal-fixture
  regression. After touching the asset layer, also confirm the five evidence
  files exist and `self_check.json.ok` is true in the output directory.
