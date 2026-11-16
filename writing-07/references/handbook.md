# Workbench handbook (writing-07, v1.0.0)

> Everything shown here is an **example** from a hand-built fixture. The numbers
> illustrate the interface; they are not results of any formal case and are not
> meant to be submitted as answers.

## 1. From commands to a finished bundle

There are two kinds of commands: the build (run twice) and the audit (rerun as
often as you like).

```bash
# pass one: scan materials, emit the comment ledger, leave the body untouched
python3 scripts/build_revision.py --input /input --output /app/output --work /app/work

# before pass two: complete /app/work/edit_plan.json (see section 3)

# pass two: apply the changes to the baseline, refresh the letter, locator table and result.json
python3 scripts/build_revision.py --input /input --output /app/output --work /app/work

# audit: read-only checks, no artifact is modified
python3 scripts/audit_bundle.py --output /app/output --input /input
```

### Flags

| Flag | Default | Meaning |
|---|---|---|
| `--input` | `/input` | input directory (`case.json` plus `materials/`) |
| `--output` | `/app/output` | output directory |
| `--work` | `/app/work` | working directory; `edit_plan.json` lives here by default |
| `--plan` | empty | explicit plan path, takes precedence over the work directory default |
| `--stage` | `auto` | `auto` / `plan` (pass one) / `draft` (same as pass one) / `finalize` (pass two) |
| `--deliverable-name` | `revised_manuscript.md` | main artifact filename; override when the case dictates another name |

`auto` behavior: a plan file exists in the work directory and contains a
non-empty `edits` or `sub_overrides` -> finalize; otherwise behave like pass one,
write the ledger and record a `draft_only` degradation saying the body was not
changed.

## 2. Input material and parsing tolerance

Required:

- `case.json`, with at least `case_id` and `output_contract`; optionally
  `organizer_workorder` / `organizer_edit_workorder`, whose items the build
  cross-checks against the produced output.
- A manuscript baseline: Markdown or plain text whose filename hints at
  `manuscript` / `baseline` (typically `materials/manuscript-baseline.md`).
- A comment summary: text whose filename hints at `comment` / `reviewer` /
  `意见` (typically `materials/reviewer-comments.md`).

Other attachments (PDF, images, spreadsheets, DOCX) are registered by path only.
Material that was not used appears as a gap entry in `pending_human`.

Comment parsing is deliberately tolerant. Each of these forms becomes a
separate comment: `### Comment 2` under a `## Reviewer 1` heading, a single-line
`Comment 1:`, a `1. ...` numbered list, `**Comment 3**`, or `意见2：`.
Inside one comment, `(a)`/`(b)` lists, `- ` bullets and `1)` lists are split
into sub-requirements; without a list, sentences are segmented and request cues
(should/please/add/clarify/建议/请/需要...) mark where a new request starts.

## 3. edit_plan.json in detail

```json
{
  "edits": [
    {
      "id": "E1",
      "comment_id": "C1",
      "sub_id": "C1.1",
      "op": "replace",
      "anchor": "P005",
      "original_quote": "a sentence copied verbatim from the baseline",
      "revised_quote": "the full sentence after the change (ends up in the manuscript)",
      "reason": "why this change is made (recorded in change_log)",
      "decision": "accept",
      "tone": "accept",
      "evidence_status": "provided",
      "evidence_note": "",
      "response_note": "optional extra wording for the response letter"
    }
  ],
  "sub_overrides": [
    {
      "sub_id": "C3.1",
      "decision": "partial",
      "tone": "clarify",
      "evidence_status": "not_provided",
      "evidence_note": "the supplied material has no inflammation markers, so the assay cannot be added",
      "response_note": "explain honestly why it cannot be done and offer the closest alternative"
    }
  ],
  "pending_human": [
    {"item": "C1.2", "reason": "the exact p-value must come from the authors"}
  ]
}
```

| Field | Required | Rule |
|---|---|---|
| `op` | no | `replace` (default) / `replace_all` / `append_after` / `append_end` |
| `anchor` | no | the `P###` from the ledger is recommended; can be omitted when `original_quote` is unique, the build then searches the whole text |
| `original_quote` | yes for replace ops | must exist verbatim in the baseline; `append_after` uses it to choose the insertion point |
| `revised_quote` | yes | must occur verbatim in the manuscript after finalize; otherwise the sub-requirement drops to partial and is filed for human confirmation |
| `decision` | no | default `accept`; one of `accept` / `partial` / `reject` / `clarify` / `invalid` |
| `tone` | no | mapped from decision when omitted: accept->accept, partial->clarify, reject->polite_rebuttal, clarify->clarify, invalid->appeal |
| `evidence_status` | no | `provided` / `not_provided` / `not_applicable` |
| `sub_id` | yes | must match a `C#.#` in the ledger; unmatched ids are logged as `unknown_sub_id` |
| `pending_human` | no | one entry per missing human input; merged into `pending_human.json` and result.json |

Several sub-requirements may share one change: give both edits the same
`revised_quote`, and the build records `change_ids` for each of them, so each
letter paragraph cites the same locator.

## 4. Why locators are `P###`

- A locator indexes the delivered Markdown after splitting on blank lines,
  counting from 1; headings occupy a block too, so `P001`, `P002`, ...
- Every change keeps two facts: `baseline_anchor` (the pre-change block) and
  `locator` (the post-change block).
- Positions in the response letter are not written separately: they come from
  `change_log.locator`, so letter, locator table and manuscript stay in sync.
  A reviewer can open the manuscript, count to block ###, and compare the
  `revised_quote` character by character.
- Page numbers and editor line numbers are avoided on purpose: the baseline has
  no stable line numbering, so they would break in another tool.

## 5. result.json quick reference

| Field | Content |
|---|---|
| `case_id` | identical to the input, never rewritten |
| `status` | `ok` / `partial` / `insufficient_evidence` / `input_error` |
| `deliverable` | main artifact filename (= `--deliverable-name`) |
| `preserved_facts` | digits/citations left untouched, with `locator`, proving no accidental edits |
| `evidence_map` | per claimed position: `claim` -> `locator` -> `source_quote`; unchanged evidence carries `basis=baseline_unchanged` |
| `change_log` | per change: `original_quote`, `revised_quote`, `reason`, `locator`, `numbers_preserved`, `hit` |
| `counts` | comments, sub-requirements, verified changes, open items, `locator_hit_rate`, decision histogram, evidence histogram |
| `verification` | audit result: per-check outcomes plus detailed counters |
| `workorder_report` | per-item execution status for `organizer_workorder` |
| `pending_human` / `errors` / `degradations` / `issues` / `uncertainty` | gaps, errors, degradations, uncertainty |
| all `output_contract` keys | backfilled at the top level; unknown keys preserved; missing values `null` or `[]` |

## 6. Pairing decisions with tone

| decision | tone | When | How the letter reads |
|---|---|---|---|
| accept | accept | doable inside the baseline and actually done | agreement + what changed + locator |
| partial | clarify | only part is doable, the rest goes to human confirmation | agreement on the doable part + locator + reason for the rest |
| clarify | clarify | the comment misreads the text, but rewording helps | restate the baseline wording, then show the change |
| reject | polite_rebuttal | the change would contradict supplied facts, keep the text | acknowledge the concern + re-checks + why the original stands |
| invalid | appeal | the comment contradicts the baseline (wrong section, number or already handled) | state the mismatch factually + offer to comply if the editor insists |

Three sentence types are banned: unconditional deference ("we fully agree and
have revised everything" with an untouched body), emotional pushback, and
promises about work outside the supplied material.

## 7. Example (example only, not a formal case result)

Hand-built fixture: 3 comments, 6 sub-requirements, 3 replace edits.

```json
{"edits": [{"id": "E1", "comment_id": "C2", "sub_id": "C2.1", "op": "replace", "anchor": "P003",
  "original_quote": "HbA1c decreased by 0.6 percentage points in the exercise group and by 0.1 percentage points in the usual-care group (p < 0.05). [12]",
  "revised_quote": "HbA1c decreased by 0.6 percentage points in the exercise group (n = 42) and by 0.1 percentage points in the usual-care group (n = 42) (p < 0.05). [12]",
  "reason": "Abstract must state per-group sample size", "decision": "accept", "evidence_status": "provided"}]}
```

Outcome (example): `status=partial`, `counts.locator_hit_rate=1.0`,
`counts.sub_requirements_total=6`, `counts.subs_with_verified_change=3`; the two
sub-requirements that ask for new experiments or data are `not_provided`.

## 8. Reusing this in another journal's revision

- Category vocabulary: replace `category_lexicon`, `decision_to_tone` and
  `decision_guide` in `comment_taxonomy.json` with field-specific wording; no
  script change needed.
- Letter wording: `reply_frames.json` holds four register frame sets that can be
  swapped wholesale for discipline-specific phrasing; keep the placeholders
  `{b}` / `{d}` / `{loc}` / `{s}` / `{n}`.
- Locator scaffold: `P###` works for any Markdown manuscript; convert DOCX/PDF
  to Markdown first if needed.
- Audit list: the checks in `audit_bundle.py` double as a human pre-delivery
  checklist.

## 9. Pre-delivery self-check

1. Comment count in the ledger equals comment count in the comment source;
2. Spot-check at least one multi-requirement comment: it must be split into
   `C1.1`/`C1.2` with a decision on each;
3. Every `accept` sub-requirement has `change_ids`, and `locator_hit_rate = 1.0`;
4. Every `P###` in `response_letter.md` can be counted in
   `revised_manuscript.md`;
5. `evidence_pending.md` contains no "already performed" type wording;
6. Every `output_contract` key is present in `result.json`;
7. `audit_bundle.py` prints `ok: true`; when it does not, confirm that the
   corresponding partial state is honestly listed in `pending_human`.
