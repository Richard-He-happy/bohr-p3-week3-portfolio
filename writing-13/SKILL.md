---
name: writing-bench-eval-kit
description: Build a runnable and re-checkable academic-writing benchmark from a case folder. The kit emits an item sheet with executable requirements, evidence-bound reference answers that still allow legitimate wording variants, three-level machine-checkable anchors, two independent raters with disagreement-driven anchor repair, per-item scores and an evaluation report, a reproducibility record, a per-item gold standard plus a comparison report, a release history, a run log and a machine-readable audit. Triggers - 学术写作题集 / 评测工具 / 评分锚点 / 评分表 / 双评一致性 / 评测报告 / 金标准 / writing benchmark / score manuscripts against anchors. Use it when a task asks you to design writing items, score drafts, measure rater agreement, or trace a quality gap back to the prompt, the answer, the anchor or the run.
version: 1.0.0
license: MIT
---

# writing-bench-eval-kit

A writing evaluation is only worth something when a second person can reproduce the number. This
skill takes a case folder and writes a complete, verifiable loop instead of a single sample essay or
a bare score table:

```
items (tasks.jsonl) -> reference answers (reference_answers/) -> anchors (anchors.md)
  -> two raters (scores_detail.csv) -> item totals (scores.csv) -> evaluation report (evaluation_report.md)
  -> reproducibility notes (reproducibility.md)
  -> asset set (golden_standard.json, diff_report.md, version_history.md, run.log, self_check.json)
  -> package index (deliverable.md) and contract echo (result.json)
```

## 1 Scope

In scope: decomposing material into judgeable writing items, extracting verbatim evidence, writing
observable criteria, scoring with two raters, repairing anchors when raters disagree, reporting per
item, and leaving a recomputation entry point.

Out of scope: deciding whether a scientific claim is *correct*, whether an argument is persuasive, or
whether the literature review is complete. Those have no observable footprint, so they are never
machine-scored; they go to `pending_human`.

Hard lines: never invent numbers, citations or conclusions that are absent from the material; never
claim benchmark scores, improvement factors or "validated" status that this run did not produce;
never treat a single model essay as the only accepted answer; never edit a score to make two raters
agree; never replace human sign-off for ambiguous items.

## 2 Runtime contract

| Item | Rule |
|-|-|
| Input | `/input/case.json` and `/input/task.md`; material lives anywhere below `/input/**` |
| Scratch | `/app/work` (may stay empty) |
| Output | `/app/output/`, always including `result.json` |
| Dependencies | Python standard library only (>=3.8); no network access |
| Paths | resolved from `Path(__file__).resolve().parent`; never from the current directory |
| Exit status | always `0`, including error paths |
| Persistence | a `partial` `result.json` is written first, then overwritten unconditionally at the end |
| Budget | 64 model requests / 900 s; this kit is deterministic and finishes in seconds, issuing 0 requests |

## 3 Commands

```bash
python3 -B scripts/bench.py --help                                 # interface summary
python3 -B scripts/bench.py                                        # /input -> /app/output
python3 -B scripts/bench.py --input <case> --output <out>          # explicit paths
python3 -B scripts/kernel.py --check <out> --input <case>          # 22 contract/join/report/evidence checks
python3 -B scripts/kernel.py --audit <out>                         # re-score every cell from anchors + ratees
```

Four modules, four jobs. `bench.py` drives the run and renders documents. `kernel.py` holds the shared
core: material extraction, item construction, anchor rules, the two raters, aggregation, and the
validation CLI. `ledger.py` writes the gold standard, the comparison and the score replay, and
orchestrates the asset block. `journal.py` owns the run log, release history, package inventory,
machine audit and the sealing steps. `bench.py` imports the other three; no intermediate file is meant
to be edited by hand.

The agent only has to: read this file, run `bench.py`, then inspect `status`, `consistency` and
`pending_human` inside `result.json`.

## 4 Input discovery (semantic, not key-name based)

1. Case file: try `<in>/case.json`; else scan `case*.json` recursively and prefer one containing
   `case_id`; else fall back to the first `*.json`. If none exists, build items from `task.md` text and
   record an error.
2. Echo untouched: `case_id` is copied verbatim; every key of `output_contract` appears at the top level
   of `result.json` with the same name; unknown keys survive; missing values become `null` or `[]`
   (never a dropped key).
3. Semantic fields: `task_instruction`/`instruction`/`prompt`, `organizer_workorder`,
   `formal_inputs`, `material_version`, `source{title,doi}`, `runtime_files`, `task_count`/`n_tasks`.
4. Material: walk `input/**` and recognise `.md/.txt/.csv/.json/.html/.pdf/.docx/.xlsx/.tsv` by suffix
   and content. PDFs are parsed from FlateDecode content streams (Tj/TJ literals); there is no
   pre-extracted answer layer to lean on. Scanned PDFs are recorded as a degradation.
5. Manuscript detection: a key or filename matching
   `manuscript|draft|submission|candidate|to_evaluat|ratee|稿件|待评`, or a file under `ratees/` or
   `submissions/`. If found, score it for real (`status=ok`); otherwise deliver items, anchors and
   calibration only (`status=partial`) and say so in `pending_human`.
6. Missing objects (word limit, target style, translation language, manuscript) are listed in
   `uncertainty` or `pending_human`; they are never fabricated.

## 5 What lands in the output folder

| File | Contents |
|-|-|
| `deliverable.md` | package index: item-type mix, six-direction coverage, file list, replay command |
| `tasks.jsonl` | item sheet, one JSON object per line; key set is defined in section 4 of the operator handbook |
| `reference_answers/<task_id>.md` | evidence pack: verbatim evidence, assembly rules, legal variants, unacceptable errors |
| `anchors.md` | three-level anchors as a readable table plus a ```json block for replay, and the revision log |
| `ratees/<id>.txt` | untouched snapshots of what was scored (real manuscript and calibration controls) |
| `scores_detail.csv` | per anchor: `level_rater_a, level_rater_b, delta, adjudicated, agree, evidence_quote, evidence_locator` |
| `scores.csv` | per item: `score, verdict, anchors, points_met, failure_type, blame, evidence, improvement` |
| `evaluation_report.md` | per-item score, evidence, failure type, fix suggestion; type mix; agreement; calibration; gaps |
| `reproducibility.md` | versions, input sha256, anchor version, exact commands, determinism verdict |
| `golden_standard.json` | per-item rubric, expected answer points, anchors with locator and verbatim quote, pass thresholds |
| `diff_report.md` | shipped delivery vs gold standard: coverage, missing parts, deviations with severity, replay result |
| `version_history.md` | version table: what each release added, why, and how to roll back |
| `run.log` | relative timestamps, steps, degradations, errors, human-pending items, final `[exit] exit_code=0` |
| `self_check.json` | machine audit: item count, completeness, quote hit rate, replayability, contract, fallbacks, exit code |
| `result.json` | contract echo plus status, sources, uncertainty, errors, degradations, changes, runtime and four asset pointers |

Extra fields in `result.json` for reviewers: `workorder_execution[]` (per work-order receipt),
`coverage` (items, anchors, points, directions, writing types), `consistency` (kappa, anchors beyond a
one-level gap, repairs, calibration table), `anchor_revisions[]`. The four asset fields
`golden_standard / diff_report / version_history / self_check` carry path, hash, counts and verdict
summary only - the files themselves stay in the output folder.

## 6 Pipeline, step by step

1. Land a `partial` `result.json` before any risky work.
2. Extract evidence: assign a locator per line (`<doc_id>:L<n>`); collect numbers with units, DOIs,
   reference entries, headings, figure/table captions and domain terms as `preserved_facts` candidates.
3. Construct items: six writing types across three tiers (tier1 extract/format, tier2 constrained
   rewrite, tier3 synthesis); rotate the six study directions (task set, reference answer, anchor,
   consistency, reproducibility, report); honour the requested count, default 6, clamped to 6-12.
4. Reference answers: verbatim evidence plus assembly rules, no writing beyond the material; declare
   legal variants and unacceptable errors as a pair.
5. Anchors: one machine-executable rule per mandatory point, plus one or two global anchors per item
   (`no_new_numbers`, and word limit or section order).
6. Two raters: rater A does normalised strict containment, rater B an independent lenient token bag.
   Each anchor gets level 0, 1 or 2.
7. Disagreement: when `|a-b| > 1`, repair the anchor only (add normalisation, split the criterion) and
   recompute that cell; record it in `anchor_revisions` and `change_log`. Scores are never adjusted.
8. Calibration: a positive control built from the reference evidence (should score all 2) and a
   negative control with removed points or altered numbers (should score much lower). Calibration
   proves discriminative power; it is not a benchmark result.
9. Report: per-item score, evidence, failure type, blame (prompt, answer, anchor, execution) and a fix
   suggestion. Numbers are joined from the CSVs by code, never typed by hand.
10. Reproducibility: input sha256, anchor version, a twice-in-one-process scoring comparison, and the
    `kernel.py --audit` replay entry point.
11. Asset set then finalise: gold standard, comparison, release history, run log, self audit. If the
    asset block throws, `fallback_assets` writes honest placeholders and the error is recorded; the
    primary deliverables are never emptied. Then overwrite `result.json` and seal it by reading it back.

## 7 Authoring rules (full text in `references/authoring-rules.md`)

Every item must carry: input references, an executable instruction (object, action, format, length),
at least three mandatory points each bound to a locator, legal variants, failure criteria and format
requirements. A mandatory point may only describe something a reviewer can *see*: a number with its
unit, a condition, a section, a citation entry or a term. Words such as fluent, clear, complete or
academic are banned as criteria - rewrite them as "does the draft contain X".

## 8 Anchor levels

| Level | Meaning | Machine decision |
|-|-|-|
| 2 | the phenomenon is fully present and verbatim-faithful | every rule in the anchor matches |
| 1 | partially present: number right but unit/condition missing, or wrong position | some rules match |
| 0 | absent, altered, or contradicted | no rule matches / a reverse rule fires |

Each anchor stores `anchor_id, task_id, point_id, level_spec{0,1,2}, observable_condition, check_rule,
evidence_locator, revision`. Rule types are exactly `contains_all`, `contains_any`,
`number_preserved`, `section_order`, `word_limit`, plus the global `no_new_numbers`.

## 9 Evidence and locators

- Locator form `src-01:L42` (document id plus 1-based line), optionally `#c120-190` for a character span.
- A `quote` must be findable **verbatim** in the named document. The script checks this; a miss goes to
  `pending_human` and the source text is never edited to make the check pass.
- Provenance has two classes: material text (`source_verbatim`, requires `verbatim=true`) and
  prompt/contract constraints (`case_spec` / `task_spec`, `verbatim=null`, meaning the evidence comes
  from the brief rather than the material and is not a missing citation).
- `preserved_facts` = `{fact_id, kind(number|unit|citation|heading|caption|term), value, locator, quote, verbatim}`.
- `evidence_map` = `{claim, kind(fact|requirement|anchor_source), locator, quote, doc_id, task_id, point_id}`.

## 10 Conflict and human hand-off

| Situation | Handling |
|-|-|
| ambiguous prompt (no length, no format, conflicting counts) | log in `uncertainty`, state the assumption inside the anchor, mark `assumption=true` |
| raters differ by more than one level | repair the anchor and recompute; if the same anchor still splits after two rounds, send it to `pending_human` instead of silently fixing a level |
| no manuscript provided | deliver items, answers, anchors and calibration only, `status=partial`, explain the gap |
| material too long | truncate by lines (default 400k characters per document) and record a degradation |
| no numbers or citations in the corpus | downgrade criteria to sections/terms/citation placeholders, lower the item count, never invent values |

## 11 Failure handling

| Failure | Actual behaviour | Recorded in |
|-|-|-|
| case.json absent | recursive `case*.json`; else build items from `task.md`, `status=partial` | `errors[]` |
| malformed JSON | keep raw text, continue extraction, `status=partial`, still exit 0 | `errors[]` |
| PDF without text layer | use filename/caption only for that document, lower item count | `degradations[]` |
| empty or refusal-style manuscript | all anchors level 0, `failure_type=模型拒答` | `scores_detail.csv` |
| output folder not writable | fall back to `./output` | `degradations[]` |
| budget nearly exhausted | finalise immediately as partial | `runtime` |
| asset block raises | write placeholder assets, keep items/scores/report intact | `errors[]` + `self_check.json` |

## 12 Pre-delivery checks (22 are scripted; verify these by eye too)

- [ ] each `anchor_id` and `task_id` in `scores_detail.csv` joins back to an anchor and an item; no dangling reference.
- [ ] every mandatory point has at least one anchor; every anchor rule is machine-readable.
- [ ] item ids, scores and verdicts in `evaluation_report.md` equal those in `scores.csv`.
- [ ] every evidence quote hits the source text, or is explicitly marked as a ratee-side quote.
- [ ] no invented score or improvement factor; calibration is labelled as calibration.
- [ ] `output_contract` is fully echoed and `case_id` is untouched.
- [ ] `kernel.py --check --input <case>` is all PASS and `--audit` reproduces every cell of `scores_detail.csv`.
- [ ] `golden_standard.json` has at least three rubric points and three expected points per item, anchors carry locators, and material anchors are all verbatim.
- [ ] `self_check.json` reports `summary.verdict == PASS`; failures must be explained, never deleted to force a PASS.
- [ ] `diff_report.md` lists every item and gives deviations a severity; `run.log` ends with `[exit] exit_code=0`.
- [ ] calibration: the positive control scores at least 85 everywhere and the negative control is clearly lower; otherwise the anchors do not discriminate and the criteria must change.

## 13 Files and versions

| File | Responsibility |
|-|-|
| `SKILL.md` | this document |
| `scripts/bench.py` | driver: discover, extract, build, answer, anchor, score, calibrate, report, result.json |
| `scripts/kernel.py` | shared core plus validation CLI (`--check`, `--audit`) |
| `scripts/ledger.py` | gold standard, comparison report, score replay, asset orchestration |
| `scripts/journal.py` | run log, release history, package inventory, self audit, sealing |
| `references/authoring-rules.md` | how to write items and anchors, rater policy, failure patterns, reuse across fields |
| `references/operator-handbook.md` | field dictionary, full command walk-through, worked example, limits |
| `references/stylepack.json` | every document template and the item-type/fix tables; wording changes need no code change |

Current package version `1.0.0`; anchor-rule version `1.0.0` (rules unchanged since the first release,
so older `scores_detail.csv` files still replay). Bump the four script constants `KVER` and
`version_history.md` together.

Known limits: scientific opinion is not judged; PDF extraction is heuristic (Flate plus Tj/TJ), so
scanned pages need external OCR; with no manuscript the kit delivers items, anchors and calibration
only; calibration scores are never presented as benchmark results.

## 14 Minimal run (illustrative, not a benchmark result)

See `references/operator-handbook.md` section 5 for the full walk-through. Minimum shape: one
`case.json` (with the five `output_contract` fields and `organizer_workorder.task_count`) plus one
`material.md`, then:

```bash
python3 -B scripts/bench.py --input ./case --output ./out
```

The console line looks like `[done] case=... status=ok items=6 anchors=30 assets=5/5 out=./out`. Those
numbers only illustrate the interface and are **not** results of any official case.
