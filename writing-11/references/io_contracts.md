# Input, draft and output contracts

Everything the skill reads and writes is listed here. The scripts never invent a
field: a value that the material does not support is written as `null`, an empty
list, or an explicit `pending_human` item.

## 1. What arrives in `/input`

| Path | Role | Required |
|---|---|---|
| `case.json` | `case_id`, `task_instruction`, `output_contract`; a workorder may be nested under any key matching `workorder`/`work_order` | yes (any JSON carrying `case_id` or `output_contract` is also accepted) |
| `task.md` | human task statement; skipped by the indexer | no |
| `organizer-edit-workorder.json` | target list, operation requirements, scope, boundaries | expected for this topic |
| chapter material | `.md` / `.txt` / `.csv` / `.json` / `.docx` / `.pdf`, several files or one long file | at least one |

Material type is decided by magic bytes first (`%PDF`, `PK` + `word/`) and by
extension second. A filename is never taken as evidence about its content.

## 2. `work/draft.json` — the one file the agent authors

```json
{"case_id": "T07",
 "annotations": [{"annotation_id": "EA-01", "target_id": "T07-B003", "operation": "annotate",
                  "status": "accepted",
                  "anchor_quote": "<one sentence copied verbatim from the target block>",
                  "text": "<2-4 sentences: what the paragraph establishes, the condition it rests on,
                            the limitation it carries; quoting the source, adding no data>",
                  "evidence": [{"quote": "<verbatim sentence from any supplied material>",
                                "locator": "<the locator printed by show>",
                                "note": "<what that sentence establishes>"}],
                  "rationale": "<why this chapter's argument needs the clarification>"}],
 "outline": [{"id": "ch5", "heading": "5 Results"}],
 "chapter_drafts": [{"id": "ch5", "heading": "5 Results", "blocks": []}],
 "pending_human": ["<anything the agent could not settle from the material>"]}
```

`outline` and `chapter_drafts` are optional and only used for a coverage warning.
`pending_human` is merged into the run's own list.

Rules re-checked by `check` and again by `build`:

1. `target_id` must appear in the workorder; anything else is rejected, never applied.
2. `anchor_quote` must occur verbatim inside the resolved target block after
   whitespace and typography normalisation.
3. each `evidence[].quote` must occur verbatim somewhere in the materials.
4. `text` under 40 characters at acceptance, or under 60 at `check`, is treated as
   non-substantive.
5. `status: "rejected"` keeps the item in `change_log` with its `reason` and changes nothing.
6. `revised_original` / `replace_original` are refused: this skill annotates, it does not rewrite.

One item per target. Two targets mean two items; merging them fails the receipt
check because the receipt is kept per target id.

## 3. `work/` scratch files

| File | Written by | Contents |
|---|---|---|
| `source_index.json` | `init` | materials, blocks, locators, workorder, resolved items, notes, errors |
| `draft_template.json` | `init` | one empty proposal per target with a real anchor quote and locator |
| `check_report.json` | `check` | findings, counts, pass flag for the current draft |

## 4. `result.json`

Every key of `output_contract` is echoed with its original name; a value the run
cannot supply stays `null` or `[]`. On top of that:

| Key | Type | Meaning |
|---|---|---|
| `case_id` | string/null | taken from the case file, never from a contract placeholder |
| `status` | enum | `ok`, `partial`, `insufficient_evidence`, `input_error` |
| `deliverable` | object | `primary`, `editable`, `files`, `chapter_files`, `blocks`, `block_coverage`, `annotations_applied`, `annotations_rejected`, `words_added`, `source_words_rewritten` |
| `preserved_facts` | list | `{fact_id, kind, quote, source_locator, preserved, note}` computed by substring test |
| `evidence_map` | list | `{claim_id, target_id, target_locator, claim, generated_by, evidence[{quote, locator, verbatim}]}` |
| `change_log` / `changes` | list | one entry per applied note (`original_quote`, `revised_text`, `original_text_changed: false`) and per rejection (`reason`) |
| `workorder_receipt` | object | `{workorder_id, authority, targets[], operation_requirements[], version_control, fault_injections}` |
| `consistency` | object | `{report, ledger, findings, high, warn, info, facts_verified, checks}` |
| `sources` | list | `{id, path, kind, blocks, status, sha}` per material |
| `uncertainty`, `pending_human`, `errors`, `degradations` | list | objects with a reason, and a locator where one exists |
| `runtime` | object | skill, version, python, utc, elapsed_s, budget, deterministic_checks |

Each receipt entry describes one workorder item: `item_id`, `target_id`, a `status` of
`done` or `pending_human`, the resolved `locator`, a `resolution` of `anchor` or `heuristic`,
the `annotations` attached to it, and a `reason` that explains any pending state.

`version_control` = `{v1_sha, v2_sha, annotations_in_v2, annotations_after_rollback,
rollback_equals_v1, reapply_equals_v2, source_blocks_unchanged}`; the three booleans are
recomputed from the files at every build, not carried over from an earlier run.

## 5. Artifacts under `/app/output`

| File | Content |
|---|---|
| `manuscript.md` | all source blocks verbatim, one blockquote per accepted note |
| `revised_chapters/<material>.md` | editable chapter per material, paragraph ids restored as `<!-- ID -->` comments |
| `revised_manuscript.md` | copy of `manuscript.md` for consumers that expect this name |
| `versions/v1_original.md`, `versions/diff_v1_v2.patch`, `versions/rollback_check.json` | before, delta and the recomputed hashes/fault probes |
| `consistency_report.md` | materials, findings table, preserved facts, draft validation, limits |
| `consistency_tables.json` | the six ledgers (section 7) |
| `consistency_ledger.md` | the same ledgers as tables for human reading |
| `operation_receipts.json` | the receipt object from `result.json` |
| `revision_records.json` | per-target records plus the full change list |
| `evidence_map.json`, `change_log.json`, `pending_human.json` | the matching `result.json` sections, standalone |
| `self_check.json` | build-time invariants, recomputed after the artifacts were written |
| `manuscript_preview.html`, `export_preview.pdf` | rendered previews; the PDF is ASCII-only by construction |

## 6. Locator grammar

A locator is always produced by `init`/`show` and printed with the text; it is never
typed by hand.

* prose: `<file> §<number> <title> ¶<paragraph>`; the heading block itself ends with `(heading)`
* JSON: `<file> #<id>` when a dict carries an id plus long text, else `<file> #/<json/path>`
* tabular text: `<file> #row N`; `.xlsx` is not parsed and is recorded as a degradation

Whitespace, NBSP, curly quotes, en/em dashes, minus signs and `ﬁ`/`ﬂ` ligatures are
normalised before comparison. A quote that fails is rejected and reported; it is
never "fixed" into a match.

## 7. Ledger schema (`consistency_tables.json`)

The ledger is the skill's own addition and doubles as a reusable template:

```json
{"case_id": "C01",
 "terms":       [{"term": "FDM", "expansions": ["fused deposition modeling"], "use_count": 7,
                  "first_locator": "...", "conflict": null}],
 "symbols":     [{"symbol": "E", "meanings": ["elastic modulus"], "single_meaning": true}],
 "definitions": [{"label": "UTS", "count": 2, "distinct_wording": 1, "status": "repeated identically"}],
 "numbering":   {"figure": {"referenced": ["2"], "caption_numbers": ["2"],
                            "caption_duplicates": ["2"], "gaps": [1]}},
 "citations":   {"cited": [1, 2], "listed": [], "missing_from_list": [1, 2],
                 "never_cited": [], "placeholder_blocks": [], "has_reference_list": false},
 "claims":      [{"claim_id": "K001", "locator": "...", "quote": "...", "polarity": "up",
                  "has_quantity": true}],
 "conflicts":   [{"category": "citations", "key": "cited but unlisted", "sides": [1, 2],
                  "locators": ["reference list"], "resolution": "flagged for the author"}],
 "counts": {"terms": 0, "symbols": 0, "definitions": 0, "claims": 1, "conflicts": 1},
 "limits": ["..."]}
```

To reuse it on another manuscript, keep the six keys and refill them; `counts` and
`limits` are advisory and are safe to edit. Do not delete `conflicts`: the receipt
for the consistency requirement points at that list.

## 8. Status vocabulary

| Status | When |
|---|---|
| `ok` | every target carries an accepted note, no rejection, no error, no degradation |
| `partial` | at least one rejection, fallback note, unreadable material or malformed input file |
| `insufficient_evidence` | materials parsed but no readable text block was produced |
| `input_error` | no case file, or no material at all |
