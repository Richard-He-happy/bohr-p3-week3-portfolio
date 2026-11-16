# Writing items and anchors that survive a second rater

Two questions are answered here: what makes a writing item decidable, and what makes a scoring anchor
observable. The scripts generate items with the same rules; hand-written items built this way are
interchangeable with generated ones.

## 1 The six fields an item cannot do without

| Field | Question it must answer | Failing shape |
|-|-|-|
| `input_refs` | which document, which part of it? | "according to the paper" |
| `instruction` | who writes what, in which genre, up to how many words? | "write a methods section" |
| `must_include_points` | what must literally appear in the draft? | "content should be complete" |
| `acceptable_variants` | which differences are legal and unpenalised? | missing entirely |
| `fail_criteria` | what lands in level 0 or 1? | "poor quality" |
| `format_requirements` | genre, word ceiling, mandatory sections | "follow the format" |

Acceptance test: two raters, forbidden to talk, read only the item and reach the same pass/fail verdict
on the same draft. If that fails, the item is missing a field - the raters are not at fault.

## 2 The only legal shape of a mandatory point

A point has to map onto something visible in the draft, and it has to carry a source locator. Legal
shapes:

1. Number plus unit - `750 °C`, `0.35 g`, `62.4 %`. Changing the value, dropping the unit or rounding
   all count as a miss.
2. Citation identity - a DOI or a full reference entry; numbering must match entry content.
3. Section presence and order - e.g. `Objective / Methods / Results` all present, in that order.
4. A short verbatim claim - roughly 40 characters from the material; paraphrasing is fine, changing the
   fact is not.
5. Figure or table caption elements - the object, condition and value named in the caption.

Banned as points or criteria: fluent, clear, well-organised, complete, academic, idiomatic. None of them
can be observed reliably by a second rater. Replace with "does section X exist", "is value Y present
with unit Z", "is citation C reproduced".

## 3 Anatomy of one anchor

An anchor is a machine-executable `check_rule`, a three-level definition, and a source locator:

```json
{"anchor_id": "A-T03-P01", "task_id": "T03", "point_id": "T03-P01", "scope": "point",
 "rule": {"type": "number_preserved", "value": "750", "unit": "°C"},
 "evidence_locator": "src-02:L5",
 "level_spec": {"2": "fully present and verbatim", "1": "value present, unit or condition missing", "0": "absent, altered or contradicted"}}
```

Available rule types, all machine-readable:

| Rule | Hit condition | Typical use |
|-|-|-|
| `number_preserved` | number token present; its unit directly follows when a unit is declared | parameters, measured results |
| `contains_all` | every given string appears in normalised text | DOI, reference entries, verbatim claims |
| `contains_any` | at least one given string appears | terms with several accepted spellings |
| `section_order` | all section titles exist; order must also match for level 2 | structural items |
| `word_limit` | whitespace token count inside the range | abstracts, response letters |
| `no_new_numbers` | draft number set is a subset of the material number set | global anti-invention guard |

Every item also gets two global anchors: `A-<task>-G1` (`no_new_numbers`) and `A-<task>-G2` (word limit,
or section order for outline items). That guarantees at least two anchors per item and that none of them
depends on writing style.

**Level discipline.** Level 2 is only for "phenomenon fully present, verbatim-faithful"; good prose never
upgrades a level. Level 1 means "content present but shape incomplete". Level 0 covers both "absent" and
"present but altered or reversed".

## 4 Reference answers are evidence packs, not model essays

A usable reference answer has two parts: verbatim evidence and assembly rules.

1. Every mandatory point gets a `locator` and a verbatim `quote`.
2. Assembly rules state the genre, the mandatory sections, the number-carry rule, and that connective
   prose is free as long as it introduces no new fact.
3. Legal variants (paraphrase, paragraph order, length allocation, active/passive, spelling convention,
   acronym introduction) and unacceptable errors (altered number, dropped point, new outside content,
   mismatched citation) are declared as a pair.

Why not one model essay: a single sample turns legal stylistic choices into errors and cannot say which
point failed. The evidence pack keeps facts checkable while leaving style free, and it cannot drift
beyond the material.

## 5 Two raters and what to do with disagreement

| Situation | Action |
|-|-|
| both raters agree | record as agreement in `scores_detail.csv` |
| one level apart | keep the stricter level (conservative), keep `delta` for analysis |
| more than one level apart | repair the anchor - add normalisation or split the criterion - recompute that anchor, log both the revision and a `change_log` entry |
| still split after repair | move that anchor to `pending_human` for a human ruling; never settle it silently |

Agreement is reported as Cohen's kappa over per-anchor pass/missed plus the list of anchors beyond a
one-level gap. Concentration of disagreement in a few criteria is normal. Disagreement spread across
many criteria means the criteria themselves are unobservable and the points must be rewritten, not the
scores massaged.

## 6 Failure patterns seen in earlier builds

| Symptom | Consequence | Fix |
|-|-|-|
| only a rubric totals table | no item text, no per-item record, nothing to replay | ship `tasks.jsonl`, `reference_answers/`, `scores_detail.csv` |
| criteria say "clear expression" | anchors unobservable, raters never agree | switch to number / section / citation rules |
| one model essay as the answer | style differences judged as errors | evidence pack plus legal-variant list |
| scores edited after disagreement | the consistency method is wrong | change the rule, recompute, keep the revision log |
| report claims "37% improvement" with no comparison | fabricated conclusion | report only this run's scores and the calibration controls |
| no hash, version or command | not reproducible | write `reproducibility.md` and implement `--audit` |
| scripts piled up to cover six directions | package bloat, load failures | keep <=12 text files, <=150KB, <=4 scripts |

## 7 Reuse in another discipline

1. Swap material: drop papers or guidelines of your field into `input/`; numbers, DOIs, headings and
   captions are extracted automatically.
2. Swap item types: edit `types` in `references/stylepack.json` (tier, action wording, sections, word
   limit).
3. Swap domain wording: rewrite `acceptable_variants` / `fail_criteria` text in the same style pack.
4. Swap the verification level: `kernel.py --check` covers contract and joins; `--audit` recomputes every
   cell from `ratees/*.txt` and fails loudly if anchors or raters were changed.
