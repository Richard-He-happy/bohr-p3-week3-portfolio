# Decision rules: band, comparison, causes, grades, replay

## 1. Freeze the band before the first run

`init` writes `tolerance_plan.json` while no candidate has executed. The stamps
`before_any_run: true` and `declared_step: "init"` are the proof of that ordering.

Selection order:

1. The case states a band (`{metric|name, abs_tol|abs|atol, rel_tol|rel|rtol}`) — take it
   and label the entry `case_declared`. Highest priority.
2. Nothing stated — use the prior default: relative width `0.02`, absolute width
   `0.005 × |reported|`. The first covers ordinary run-to-run jitter; the second absorbs
   the rounding implied by however many digits the paper printed.
3. No reported value at all — absolute width `0`, relative width `0.02` as a placeholder,
   and the metric ends up graded `no_reported_value` rather than "within band".

Arithmetic:

```
gap          abs_dev = |observed - reported|
relative gap rel_dev = abs_dev / |reported|   (when reported is non-zero)
inside band  within  = abs_dev <= abs_tol  OR  rel_dev <= rel_tol
```

Either dimension passing is enough. Why freeze first: a band chosen after seeing the data
can turn any mismatch into a match, which destroys the discriminating power of the whole
exercise. This is also why `check` only allows tightening and rejects any wider entry as
`tolerance_widened_after_run`.

## 2. Attribution: use candidate agreement as the yardstick

The script first makes a deterministic call from the numbers, then the agent adds prose.
Only two quantities matter: how far the observations sit from each other, and how far they
sit from the reported value.

| cause label | automatic trigger | reading |
|---|---|---|
| `none` | every observation inside the band | nothing to explain |
| `shared_upstream_factor` | candidate spread within the band, but all of them miss the reported value | independent implementations agree, so the drift is upstream: data version/split, restored parameters, environment |
| `implementation` | candidate spread beyond the band and at least one misses | difference lives in implementation details: algorithm variant, defaults, randomness |
| `unverified_single_implementation` | only one candidate produced numbers | cannot separate implementation from upstream |
| `paper_value_unavailable` | no reported value in the material | register the gap; never claim agreement |
| `parameter_restoration` | the draft contains `chosen` or `code_inferred` entries | parameter reconstruction itself is uncertain |
| `environment_underspecified` | the environment snapshot lacks key fields | cross-machine rebuilding is blocked |

Confidence is `determined` when the script decides directly from the numbers and `inferred`
when the call is heuristic and needs review. Entries the agent adds under
`draft.attribution` are preserved next to the automatic ones and never overwrite them.

## 3. Four verdict grades

| grade | condition |
|---|---|
| `reproduced` | every comparable observation sits inside the pre-declared band |
| `partially_reproduced` | some observations sit inside, some do not |
| `not_reproduced` | comparable observations are all outside |
| `insufficient_evidence` | no candidate ran, or there is nothing to compare |

`status` and `verdict` are independent. `status` reports delivery health
(`ok`, `partial`, `insufficient_evidence`, `input_error`); `verdict` reports the scientific
call. Any gap (`pending_human` or `degradations` non-empty) forces `status` to at least
`partial`. One must not stand in for the other: a run that never happened can never be
`reproduced`.

## 4. How a reviewer replays the work

1. Open `result.json`, locate the embedded record's `tolerance_plan`, verify
   `declared_step=init` and `before_any_run=true`.
2. Re-execute each entry of `runs[*]` from its `command` inside its `workdir`; compare
   `exit_code`, `metrics` and `stdout_tail` with what the record says.
3. Recompute `abs_dev`/`rel_dev` from the comparison table and check them against
   `abs_tol`/`rel_tol`; confirm no verdict was hand-edited.
4. For every `inferred` cause, re-derive it from the candidate spread and the parameter
   table. If it does not hold, move it into `uncertainty`.
5. Inspect whether a gap was used as a conclusion. Reproduced outcome with missing raw data
   is inconsistent and must be downgraded.

## 5. Traps that cost points

- **Mixed units.** Paper says 76.5 (percent), candidate prints 0.766 (fraction). Convert,
  never rewrite the digits.
- **Mixed splits.** Comparing validation numbers with test numbers makes an implementation
  issue look real. Note the split under `uncertainty`.
- **Single seed.** One run is thin support for `reproduced`. Candidate agreement helps, but
  does not replace repeated seeds.
- **Absence read as agreement.** A metric the material never reports is not a success; it
  is `no_reported_value`.
- **Incomplete environment snapshot.** Without Python/packages/seed, cross-machine drift
  cannot be excluded and attribution stops at "unverified".
- **Quotes massaged to fit.** Evidence has to be verbatim; otherwise `check` rejects it and
  replayability suffers.
