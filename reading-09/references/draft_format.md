# Draft field dictionary (`draft.json`)

The draft is the agent's ledger, stored at `<work>/draft.json`. Three consumers read it:
`build` turns it into the reproduction record, `check` validates its structure, and `doctor`
inspects the finished artefacts. Missing sections never crash the run, but they lower
`status` and leave gaps in the record. `init` writes a starter file named
`draft_skeleton.json` into the same folder — copy it, rename it, then fill it in.

## Shape

```jsonc
{
  "case_id": "repro-demo-001",
  "paper": {"title": "...", "doi": null, "repo": "...", "commit": "a1b2c3d"},
  "plan": [{"step": 1, "goal": "locate method", "command": "...", "expected": "...", "status": "done"}],
  "environment": {"python": "3.12.4", "platform": "Linux", "packages": {"numpy": "1.26.4"}, "seed": 0},
  "params": [], "paper_values": [], "tolerance": [], "claims": [],
  "attribution": [], "pending_human": [],
  "conclusion": {"verdict": "reproduced", "reason": "..."}
}
```

## Field by field

| key | what goes in | what breaks when it is wrong |
|---|---|---|
| `paper` | title, DOI, repository, commit; `null` when unknown | replayability drops |
| `plan` | step number, goal, command, expectation, status — only steps actually executed | record contradicts the logs |
| `environment` | Python version, OS, package versions, random seed (from `init` plus the host) | attribution stalls at "environment unknown" |
| `params` | one entry per key parameter: value, provenance class, verbatim evidence | a `paper` parameter without a quote is rejected |
| `paper_values` | metric name, reported value, unit, verbatim quotation | name mismatch produces `no_reported_value` rows |
| `tolerance` | equal to or tighter than `tolerance_plan.json` | any widening trips `tolerance_widened_after_run` |
| `claims` | statement, confidence, verbatim evidence | a claim without evidence is rejected |
| `attribution` | extra explanations you want on top of the script's call | conflicts surface in `uncertainty` |
| `conclusion` | one of the four grades plus a one-line reason | an invalid grade trips `conclusion_verdict_invalid` |

## Parameter provenance

```jsonc
{"name": "momentum", "value": 0.9, "class": "paper", "source": "§3.2",
 "evidence": {"source_id": "paper", "locator": "paper:§3.2 Training setup/p1",
              "quote": "momentum 0.9"}}
```

* `paper` — stated in the body, a table or an appendix. A verbatim `quote` that really
  matches the index is mandatory.
* `code_inferred` — not stated; read back from repository defaults or config files. Put
  file and line in `source`, and note the inference under `uncertainty`.
* `chosen` — neither source exists and you picked the value. Explain why; expect a
  `parameter_restoration` cause to be attached.

When the paper and the code disagree, do not silently pick one. Follow the paper, keep the
code value next to it, and write down both, e.g.
`"paper says lr=0.1, repo default is 0.01; used 0.1 per paper, default kept for auditing"`.

## Reported values and units

```jsonc
{"metric": "top1_accuracy", "value": 0.765, "unit": "fraction",
 "evidence": {"source_id": "paper", "locator": "paper:§4.1 Main results/p1",
              "quote": "Top-1 accuracy 76.5%"}}
```

* `metric` should match a key emitted by the candidate, or be normalisable to one
  (case, spaces and hyphens are ignored). If nothing lines up, let the row become
  `no_reported_value`; do not edit the number to force a pass.
* Percentversus fraction: convert the unit (76.5% ↔ 0.765). The value itself must not move.
* If the units cannot be reconciled (the paper reports a median, the candidate a mean),
  say so under `uncertainty` and mark the pair incomparable.

## Tolerance may only tighten

```jsonc
{"metric": "top1_accuracy", "abs_tol": 0.003, "rel_tol": 0.01,
 "basis": "paper gives three decimals; use half a last digit", "declared_step": "plan"}
```

`init` already froze the default band in `tolerance_plan.json` with
`before_any_run: true`. Entries here may be equal or smaller; wider numbers are flagged as
`tolerance_widened_after_run`, which is the equivalent of tuning the test after seeing the
answer.

## Claims and conclusion

```jsonc
{"id": "c1", "kind": "paper_result", "text": "paper reports Top-1 76.5%",
 "confidence": "direct",
 "evidence": [{"source_id": "paper", "locator": "paper:§4.1 Main results/p1",
               "quote": "Top-1 accuracy 76.5%"}]}
```

* `kind` is a free label; common values are `paper_result`, `method`, `param`,
  `environment`, `attribution`.
* `confidence` — `direct` (quoted straight from the material), `inferred` (deduced),
  `undetermined` (cannot tell).
* Quotes are normalised and searched as substrings; a miss rejects the evidence. Do not
  edit the source text to make a quote fit — delete the claim or hand it to
  `pending_human` instead.

`conclusion.verdict` accepts `reproduced`, `partially_reproduced`, `not_reproduced` or
`insufficient_evidence`. The tolerance-derived verdict has precedence; when the two differ
the computed verdict is kept, your `reason` is appended, and `verdict_conflict` is logged.

## Frequent validation errors

| error | meaning | fix |
|---|---|---|
| `claim_without_evidence` | claim has no evidence list | add a verbatim quote or lower the confidence |
| `evidence_rejected:…:quote_not_found` | quote does not occur in the material | copy the exact sentence back with `show --grep` |
| `param_class_invalid` | unknown provenance class | use one of the three allowed classes |
| `tolerance_not_predeclared` | metric absent from the frozen plan | keep the metric name used by `init` |
| `locator_mismatch` | quote found, section number differs | acceptable; prefer the locator the script reports |
