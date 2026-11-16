---
name: repro-audit-runbook
description: Turn a paper's reported numbers into a runnable audit — execute the bundled candidate implementations for real, lock the acceptance band before anything runs, diff observed against reported metrics, assign a cause to every gap, and deliver a graded verdict plus machine-readable artifacts a reviewer can replay.
version: 1.0.0
---

# Reproduction Audit Runbook

## What this is for

You get paper material plus one or more candidate implementations. This runbook drives a
fixed chain of custody: **inventory the material, snapshot the environment, restore the
parameters, execute the candidates, diff against the reported metrics inside a band that was
locked beforehand, explain the gaps, and grade the verdict.** Everything it emits is meant
to be replayed by somebody else.

Use it for reproduction attempts, method checks, "our number does not match the paper"
investigations, hyper-parameter restoration, and log/table reconciliation.
Skip it when there is nothing executable and no human can step in — the honest answer then
is `insufficient_evidence`.

## Non-negotiables

1. **Only what was observed.** Every number must come from a real execution or from the
   source material. A candidate that never ran cannot support a claim of agreement.
2. **Band before data.** The acceptance band is persisted before the first candidate starts.
   Later edits may tighten a band, never widen it.
3. **No fabrication.** Logs, metrics and quotations stay traceable. Missing data goes to
   `pending_human`; scanned pages and images are not guessed without OCR.

## Layout and paths

| Role | Default location | Notes |
|---|---|---|
| Input | `/input/case.json` and `/input/**` | `case_id`, `output_contract`, task text |
| Working area | `/app/work` | index, tolerance plan, draft, `runs/` |
| Deliverables | `/app/output` | `result.json`, `reproduction.json`, `reproduction.md` |
| Package root | directory holding `SKILL.md` | always invoke scripts by absolute path |

Both of these work and mean the same thing; explicit flags win:

* flags: `--input DIR --output DIR --work DIR`
* environment: `SCIM_INPUT`, `SCIM_OUTPUT`, `SCIM_WORK`

Find the package root and confirm the entry point loads:

```bash
PKG=${SKILL_ROOT:-/skills/weekly-skill}
test -f "$PKG/SKILL.md" || PKG=$(dirname "$(find / -maxdepth 4 -name SKILL.md 2>/dev/null | head -n1)")
python3 -B "$PKG/scripts/cli.py" --help
```

## The workflow

```bash
W=/app/work
python3 -B "$PKG/scripts/cli.py" init  --input /input --output /app/output --work "$W"
python3 -B "$PKG/scripts/cli.py" show  --id paper --grep "accuracy"
#   ... you write "$W/draft.json" here; a skeleton sits in "$W/draft_skeleton.json" ...
python3 -B "$PKG/scripts/cli.py" check --work "$W"
python3 -B "$PKG/scripts/cli.py" build --work "$W"
python3 -B "$PKG/scripts/cli.py" doctor --input /input --output /app/output --work "$W"
```

* `init` — indexes the input, freezes the tolerance plan, writes a legal partial
  `result.json` immediately, then prints the material inventory, unit preview, work-order
  summary and tolerance table. Read that output before opening any source file.
* `show` — replays indexed text units with their locators so quotations can be copied
  exactly.
* `check` — structural gate over the draft: verbatim evidence, enum values, and any band
  that was widened after the plan was frozen.
* `build` — executes the candidates, computes deviations, attributes gaps, and always
  finalises the artifacts (a missing or thin draft still yields a deterministic minimal
  record with `status=partial`).
* `doctor` — optional post-hoc audit of artefacts already on disk (envelope fields,
  contract keys, pre-declared band, verdict/row coherence).

Who does what: the scripts own the deterministic part (indexing, slicing, subprocess
execution, deviation arithmetic, validation, rendering). The agent owns the judgement
part (reproduction plan, provenance of each parameter value, metric semantics,
attribution wording, final verdict).

## Reading the input

1. Parse `case.json` with fallbacks `utf-8-sig`, `utf-8`, `gb18030`, `latin-1`. A corrupt
   file does not abort the run; the reason lands in `errors`.
2. Walk `/input/**`, skipping `case.json`. Classify by magic bytes first and suffix second:
   `%PDF`, `PK` followed by `word/`, `xl/` or `ppt/`, PNG/JPEG signatures. Never trust a
   label over the bytes.
3. Interpret case fields semantically rather than by exact key names: task text,
   organiser scope, candidate list, reported metrics, environment hints, output contract.
4. Give each material a stable `id` and a short `sha1`, then cut its text into located
   units. Examples of locators: page `paper:pg3/p2`, Markdown heading
   `paper:§4.1 Main results/p1`, table row `data:r7`, JSON pointer `log:#/results/accuracy`.

## Output contract

`result.json` must echo every key of `output_contract` under its original name — no
renames, no omissions; a missing value is `null`/`[]` but the key stays. On top of that the
envelope always carries `case_id`, `status`, `sources`, `uncertainty`, `pending_human`,
`errors`, `degradations`, `changes` and `runtime`.

`status` is one of `ok`, `partial`, `insufficient_evidence`, `input_error`.
Contract keys are mapped by meaning to reproduction record, comparison table, attribution,
tolerance, run log, parameter table, evidence and conclusion. A key that cannot be mapped is
filled with `null` and reported as `contract_field_unmapped:<key>` inside `degradations`.

## The draft

The agent's ledger lives at `<work>/draft.json`; the full field dictionary with examples is
in `references/draft_format.md`. Minimum viable content:

* `paper` — title, DOI, repo, commit; unknown values are `null`, never invented;
* `params` — value plus provenance class (`paper`, `code_inferred`, `chosen`) plus a
  verbatim quotation;
* `paper_values` — metric name in the candidate's unit, reported value, unit, quotation;
* `tolerance` — equal to or tighter than what `tolerance_plan.json` declares;
* `claims` — text, confidence (`direct`, `inferred`, `undetermined`), verbatim quote;
* `conclusion.verdict` — one of the four grades.

`check` normalises quotations (NFKC, whitespace folding, zero-width removal, lower case)
and looks for them as substrings of the indexed text. A miss becomes
`evidence_rejected`. Rewriting the source to force a hit is out of bounds: drop the claim
or hand it over via `pending_human`.

## Acceptance band and reruns

`init` writes `<work>/tolerance_plan.json` before any candidate executes, stamped with
`before_any_run: true` and `declared_step: "init"`. If the case supplies a band it is used
and labelled `case_declared`; otherwise the default is 2% relative plus 0.5% of the reported
magnitude to absorb rounding. When no reported value exists the row is graded
`no_reported_value` — never "matches".

The comparison formula, attribution table, verdict tiers and the reviewer's replay path are
specified in `references/audit_rules.md`.

## Attribution and grading

The scripts classify every differing metric deterministically using the spread between
candidates relative to the band: no difference, shared upstream factor, implementation
difference, single unverified implementation, missing reported value, parameter
restoration, underspecified environment. Extra explanations written under
`draft.attribution` are kept side by side and never overwrite the automatic call; any
conflict is recorded in `uncertainty`.

Grades: `reproduced` (everything inside the band), `partially_reproduced` (some inside),
`not_reproduced` (everything outside), `insufficient_evidence` (nothing ran, or nothing to
compare). If the agent's verdict disagrees with the computed one, the computed verdict wins
and `verdict_conflict` is logged.

## Degradation paths

| Situation | Behaviour | Status |
|---|---|---|
| `case.json` absent or unparsable | continue with an empty case, reason in `errors` | `input_error` |
| image or scanned material | no pixel reading; queued for human takeover | `partial` |
| PDF without a text layer | `pdf_text:failed` note, suggest render/OCR | `partial` |
| no candidate found | no invented run; ask a human to execute | `insufficient_evidence` |
| candidate crashes or times out | keep `runs/<name>/run.log`, degrade only that run | `partial` |
| candidate prints no metrics | recorded under `uncertainty`, nothing guessed | `partial` |
| no draft at all | deterministic minimal record (materials, env, band, real runs, diff) | `partial` |
| band widened after the fact | flagged by `check`, logged by `build` | `partial` |

## Budget and safety net

Budget per case is 64 model requests / 900 s / 16384 tokens. The scripts keep a soft
deadline at 780 s: both `init` and `build` publish a legal partial `result.json` first, and
with less than 60 s left unstarted candidates are skipped with `run_skipped_deadline`.
Uncaught exceptions still produce a partial result; the process exit code is always 0.

## Pre-flight checklist

- [ ] every `output_contract` key present in `result.json`, `case_id` matches the input
- [ ] `check` is PASS, or every ERROR is listed in `pending_human` and the status downgraded
- [ ] `tolerance_plan.json` says `before_any_run=true` and no band was widened
- [ ] each metric has observed/reported/band/verdict or an explicit `no_reported_value`
- [ ] `reproduction.md` has all ten sections; run sections show command, exit code, duration
- [ ] status and verdict agree — nothing that failed to run is `reproduced`
- [ ] UTF-8 without BOM inside the package; no `__pycache__`, `.pyc` or scratch files
- [ ] `python3 -B scripts/audit_lib.py --selftest` prints `PASS`

## Worked miniature (illustration only, not a graded case)

Assume `/input/case.json` has `case_id=demo-001`, a contract asking for
`reproduction_record` and `comparison_table`, and the material contains `paper.md` plus
`impl/candidate_a.py` and `impl/candidate_b.py`.

```bash
python3 -B "$PKG/scripts/cli.py" init
# 3 materials / 5 units; band for top1_accuracy: abs=0.003825 rel=0.02 (before_any_run=True)
python3 -B "$PKG/scripts/cli.py" show --id paper --grep "Top-1"
# paper:§4.1 Main results/p1 | ... Top-1 accuracy 76.5% and macro F1 0.741 ...
python3 -B "$PKG/scripts/cli.py" check   # PASS claims=2 ok=2 rejected=0 params=4 widened=0
python3 -B "$PKG/scripts/cli.py" build   # runs 2 (ok 2); rows 4 in=4 out=0; verdict reproduced
```

| method file | metric | run output | paper value | relative gap | call |
|---|---|---|---|---|---|
| `impl/candidate_a.py` | Top-1 accuracy | 0.7660 | 0.7650 | 1.31e-3 | inside band |
| `impl/candidate_b.py` | Top-1 accuracy | 0.7605 | 0.7650 | 5.88e-3 | inside band |

## Package contents and maintenance

```
SKILL.md                     this file: contract, workflow, rules, checklist
scripts/cli.py               front end: paths, init, show, check, doctor, dispatch
scripts/pipeline.py          build orchestration, reported values, band freeze, publish
scripts/experiment.py        candidate discovery, execution, metric parsing, diff, render
scripts/audit_lib.py         extraction, quote matching, tolerance math, contract fill
references/draft_format.md   draft field dictionary and failure examples
references/audit_rules.md    band priors, comparison formula, causes, verdicts, replay
```

When changing behaviour, update all three layers: script behaviour → "The workflow" and
"Degradation paths"; fields → "Output contract"/"The draft" plus
`references/draft_format.md`; rules → "Acceptance band"/"Attribution and grading" plus
`references/audit_rules.md`. Then rerun `scripts/audit_lib.py --selftest` and `cli.py doctor`.
