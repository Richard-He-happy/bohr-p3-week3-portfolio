# Operator handbook: commands, fields, example, limits

Every input, output and score shown here is an **illustration, not an official case result**. Official
results are produced by the platform running this skill on its fixed cases.

## 1 Three commands

```bash
# 1) confirm the interface
python3 -B scripts/bench.py --help

# 2) build, score and report (defaults /input -> /app/output)
python3 -B scripts/bench.py --input /input --output /app/output

# 3) inspect and replay
python3 -B scripts/kernel.py --check /app/output --input /input
python3 -B scripts/kernel.py --audit /app/output
```

`bench.py` is non-interactive, offline, dependency-free, and always exits 0. Internal order is fixed: a
partial `result.json` first, then items, reference answers, anchors, two-rater scoring, anchor repair,
report, reproducibility, the asset set, and finalisation.

## 2 Input layout

| Location | Contents | Behaviour |
|-|-|-|
| `<in>/case.json` | `case_id`, `task_instruction`, `output_contract`, `organizer_workorder`, `reviewer_comments` | if absent, scan `case*.json`, then the first `*.json` |
| any material below `<in>` (`.md/.txt/.pdf/.docx/.csv/.json/.html`) | item source material | suffix and content based; PDFs use the text layer, scanned pages degrade |
| names matching `manuscript`, `draft`, `submission`, `ratee`, `稿件` | drafts to score | if found the run scores them (`status=ok`); otherwise items plus calibration only (`status=partial`) |

Every `output_contract` key appears at the top level of `result.json`: same name, unknown keys kept,
missing values `null` or `[]`.

## 3 Output layout

| File | Purpose | Fields to watch |
|-|-|-|
| `deliverable.md` | package index, the primary editable artefact | file list, replay command |
| `tasks.jsonl` | item sheet | eight fields per item, see section 4 |
| `reference_answers/T0x.md` | reference answers | verbatim evidence, assembly rules, variants, error list |
| `anchors.md` | anchor library | readable table plus ```json replay block plus revision log |
| `scores.csv` | per-item totals | `score` `verdict` `failure_type` `blame` `evidence` `improvement` |
| `scores_detail.csv` | per-anchor two-rater detail | `level_rater_a` `level_rater_b` `delta` `adjudicated` `evidence_quote` `evidence_locator` |
| `evaluation_report.md` | evaluation report | type mix, per-item score and evidence, kappa, calibration, gaps |
| `reproducibility.md` | reproducibility record | input sha256, anchor version, commands, determinism verdict |
| `ratees/*.txt` | snapshots of scored objects | manuscript plus two calibration controls, consumed by `--audit` |
| `result.json` | machine result | contract fields plus status, sources, uncertainty, errors and four asset pointers |
| `golden_standard.json`, `diff_report.md`, `version_history.md`, `run.log`, `self_check.json` | asset set | gold standard, comparison, release history, run log, machine audit |

## 4 Field dictionary

**One item** is one JSON object on one line of `tasks.jsonl`. Its keys, in the order the generator
writes them, with a deliberately small sample (values are illustrations):

- `task_id` - stable identifier such as `T07`; `direction` - which study direction the item exercises;
  `writing_type` and `tier` - the layered type pair from section 4.1.
- `input_refs` - array of document ids the item may use.
- `instruction` - one sentence naming object, action, genre, length ceiling and the no-new-facts rule.
- `word_limit`, `language` - numeric ceiling and output language.
- `must_include_points` - array of visible requirements; each one carries `text`, `check` (a rule
  object), `locator`, `quote`, `fact_id`, `observable`, `point_id`.
- `acceptable_variants`, `fail_criteria`, `format_requirements` - three string arrays, always non-empty.
- `completion_rule` - the sentence that maps point coverage to pass / partial.

A single point, to show the shape only:

```json
{"point_id":"T07-P02","text":"keep 812 K verbatim","check":{"type":"number_preserved","value":"812","unit":"K"},
 "locator":"src-01:L14","quote":"the bed was held at 812 K for 6 h","fact_id":"F-012",
 "observable":"the value appears with K directly after it and is not converted"}
```

### 4.1 Direction and type rotation

`direction` walks the six study directions in turn: task-set design, reference answer, scoring anchor,
inter-annotator consistency, run reproducibility, evaluation report.

`writing_type` is layered by difficulty: tier1 = extract or format (abstract, outline, citation
normalisation); tier2 = constrained rewrite (methods paragraph, bilingual abstract); tier3 = synthesis
(reviewer response). A type is only emitted when the material carries the evidence it needs - no DOI in
the corpus means no citation-normalisation item.

### 4.2 Row-level fields

Per-anchor rows use `verdict` (`met`, `partial`, `missed` for levels 2/1/0), `failure_type` (one of
missing-point, fact-mismatch, format-mismatch, citation-mismatch, refusal) and `blame`, which says
whether the gap sits in execution, the anchor or the prompt.

`result.json` highlights: `status` (`ok`, `partial`, `insufficient_evidence`, `input_error`),
`coverage` (item / anchor / point / direction / type counts, unparsed files, manuscripts),
`consistency` (kappa, anchors beyond a one-level gap, repair count, calibration table),
`workorder_execution` (one receipt per work-order line), `preserved_facts` (numbers, DOIs, headings and
captions with locator and verbatim quote), `evidence_map` (point to locator to quote), and `change_log`
(anchor revisions, or a note that no source was edited).

## 5 Worked example (illustration only)

Take a case folder `./case` holding:

- `case.json` with `case_id = "DEMO-KIT-A"`, the five illustrative contract keys
  (`case_id`, `deliverable`, `preserved_facts`, `evidence_map`, `change_log`), and
  `organizer_workorder.task_count = 6`;
- `material.md` with a `## 2 Methods` heading, the values `812 K`, `9500 h^-1`, `0.42 g`, and one DOI.

Run the driver:

```bash
python3 -B scripts/bench.py --input ./case --output ./out
```

Console line (illustration): `[done] case=DEMO-KIT-A status=ok items=6 anchors=30 assets=5/5 out=./out`

The driver has scored a draft because the folder also contained a `draft_v1.md`. A slice of the emitted
`result.json` (illustration):

```json
{"case_id":"DEMO-KIT-A","status":"ok",
 "deliverable":{"primary":"deliverable.md","task_count":6,"anchor_count":30,"has_manuscript":true},
 "consistency":{"kappa":0.83,"big_delta_anchors":0,"repaired":0,
   "calibration":[{"control":"control-positive","mean_score":100.0,"ok":6,"total":6},
                  {"control":"control-negative","mean_score":58.3,"ok":4,"total":6}]},
 "runtime":{"elapsed_s":0.2,"llm_requests":0}}
```

Then the two inspection commands report (illustration):

```
$ python3 -B scripts/kernel.py --check ./out --input ./case
CHECK: PASS (22 pass / 0 fail)
$ python3 -B scripts/kernel.py --audit ./out
PASS 60 re-scored cells; every one matches scores_detail.csv
AUDIT: PASS
```

## 6 What actually happens on bad input

| Input situation | Observed behaviour | Recorded in |
|-|-|-|
| no `case.json` | recursive `case*.json`, then first `*.json`, else `status=input_error` | `errors[]` |
| malformed `case.json` | keep raw text, extract from it, `status=input_error`, still valid `result.json` | `errors[]` |
| input folder missing | `status=input_error`, all contract fields present, exit 0 | `errors[]` |
| empty or unparsable material | no items; `deliverable.md` states the run is incomplete | `pending_human[]` |
| PDF without text layer | that document contributes captions/filename only; item count lowered | `degradations[]` |
| no manuscript | items, answers, anchors and calibration; `status=partial`; tells you to rerun with the draft | `pending_human[]` |
| empty or refusal draft | every anchor level 0, `failure_type=模型拒答` | `degradations[]` plus detail rows |
| raters more than one level apart | anchor repaired and recomputed, `score_changed=false` | `change_log[]` and `anchors.md` |
| output folder not writable | fall back to `./output` | `degradations[]` |

## 7 Limits

- Scientific opinion is not judged; only material consistency, point coverage and format compliance.
- With no manuscript the kit emits no manuscript score at all, and calibration controls are not results.
- PDF extraction is heuristic (Flate inflate plus Tj/TJ literals); scanned pages need external OCR. The
  unit vocabulary lives in the `UNIT` constant of `scripts/bench.py` and can be extended.
- Semantic quality (argument strength, literature sufficiency) is out of machine reach; keep those points
  in `pending_human`.
- The gold standard and the scorer share an evidence layer, so the gold standard cannot validate itself.
  Two external relations are checkable: (a) material anchors quote the material verbatim, and (b) every
  score can be recomputed from anchors plus `ratees/*.txt`.
