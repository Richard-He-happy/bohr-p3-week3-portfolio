---
name: paper-to-defence-deck
description: Turn a paper or research summary into a defensible academic talk deck. Delivers a real editable .pptx that inherits the organizer template, speaker notes per slide, a rendered PDF preview, a page plan frozen before rendering, a page-level golden standard with per-page diff, export/template inspection, a final self-check, and a contract-complete result.json whose bullets carry verbatim source quotes and locators. Handles generate/edit/adapt workorders, evidence-mapped slides and honest degradation. Use for 论文转汇报, 组会/开题/中期/答辩 decks, template adaptation, or editing an existing deck.
version: 1.0.0
---

# paper-to-defence-deck

A research document goes in; a presentation you can open, edit and defend comes out. A page plan fixes
the narrative first, every body bullet is a verbatim fragment of a source sentence, and every page is
measured afterwards against a standard registered before the slides existed.

Covers: paper → group-meeting/proposal/defence deck; adapting a deck to a new audience, length or
language; rebuilding under an organizer template without losing master, palette or footer. Not covered:
peer review, re-analysis, chart pixel digitisation, prose polishing, PowerPoint itself.

## Runtime contract

| item | rule |
|---|---|
| inputs | `/input/case.json`, `/input/task.md`, `/input/material.json`, `/input/artifacts/*.json`, any PDF/DOCX/TXT/MD, optional `template*.pptx` / `starting*.pptx` |
| scratch / delivery | `/app/work` / `/app/output` (output always contains `result.json`) |
| command | `python3 -B scripts/main.py --input /input --output /app/output` |
| dependencies | Python 3.9+ standard library only; no network; no third-party imports |
| paths | package resources resolved from `Path(__file__).resolve().parent`; no current-directory assumption |
| exit code | always `0`; failed stages are recorded in `result.json`, not signalled by a crash |
| first write | a partial `result.json` exists before heavy work; the final version overwrites it |

Flags: `--slides N`, `--template X.pptx`, `--no-pdf`, `--reuse-plan plan_v0.json`, `--no-golden`,
`--legacy-sections`, `--version`, `--help`. `--reuse-plan` replays a recorded page skeleton;
`--no-golden` writes only core result fields; `--legacy-sections` restores one-label-per-page
detection. All three are documented rollback targets inside `result.json.version_history`.

## Reading the input (content, not filename labels)

1. `case.json` is read as a dict or the first dict of a list. A malformed file is non-fatal: the run
   continues with `{}`, records `NO_CASE_JSON`, and the contract key set is empty. UTF-8 BOM is
   tolerated because local editors add it.
2. `output_contract` is captured verbatim (list or dict). Each key is mirrored at the result root
   under its original spelling through an alias table (`editable_source`≈`deck`/`pptx`,
   `export_artifact`≈`pdf`/`render`, `content_map`≈`slide_map`, `compliance_checks`≈`checks`,
   `exceptions`≈`issues`, plus optional inspection keys). A key with no produced value is
   `null`/`[]` and appears in `compliance_checks.contract.unknown_keys`.
3. The workorder is found by name (`artifacts/slide-workorder.json`, `slide-workorder.json`,
   `workorder.json`) or by content (any JSON carrying a slide-count key). Four contract fields are
   echoed back: **mode**, **total slide count**, **source preservation**, **template inheritance**;
   language, audience and footer are used when present.
4. Files are classified by extension plus magic bytes (`%PDF`, `PK`, text), so a mislabelled file still
   reaches the right reader.
5. Missing material is listed in `pending_human`, never guessed: no template, no figure, no caption,
   no page count all become explicit gaps.

## Stages

bootstrap (dirs/case/contract echo/partial result) → gather (file scan, workorder, text extraction
with pdftotext or the stdlib PDF reader, DOCX/TXT/MD direct, metadata) → plan (`plan_v0.json`) →
register (`page_golden.json`) → build (`presentation.pptx`, `presentation.pdf`) → audit (verbatim
evidence, `content_map`, `compliance_checks`) → inspect (`export_check.json`,
`template_check.json`, `page_diff.md`) → finalize (`result.json`, `selfcheck.json`, `run.log`).
Plan and standard are frozen before any slide part is written, so the diff compares a prediction with
the delivery and a page can honestly fail.

## Page plan schema (`plan_v0.json`)

```json
{"version": "v0", "case_id": "<from case.json>", "requested": 10,
 "roles": ["title", "background", "methods", "results", "discussion", "conclusion", "thanks"],
 "pages": [{"index": 2, "role": "background", "title": "Background", "quotes": ["<verbatim>"]}],
 "sha256": "<hash of the pages array>"}
```

Order is fixed: title → (outline when ≥8 pages) → background → question → methods → results×k →
discussion → limitations → conclusion → thanks; trimming for a small count drops limitations, outline,
question, discussion, background in that order. Each content page draws from its section contract,
keeps one line from the section it is named after, reserves sections owed to later pages, and for
results swaps in the sentence naming an owed figure/table. A page the sentence pool cannot fill is
dropped with `POOL_EXHAUSTED`, never padded with invented text.

## Golden standard and diff

`page_golden.json` freezes, per planned page, role, narrative job, expected/declared sections, bullet
range, required verbatim numbers, owed figure/table citations, figure placement, claim expectation and
planned quotes. `page_diff.md` compares it with the delivered `content_map` on seven checks (role,
sections, numbers, citations, bullets, evidence, overflow; hard vs soft split and schema in
`references/playbook.md`) and carries summary, per-page expected-vs-actual tables, a numbered gap index
and a reproduction block; `result.json.page_diff` holds the machine summary.

## `result.json` contract

Root keys: `case_id`, `status`, `editable_source`, `export_artifact`, `content_map`,
`compliance_checks`, `exceptions`, plus `errors`, `degradations`, `pending_human`, `uncertainty`,
`sources`, `changes`, `runtime`, `page_golden`, `page_diff`, `export_check`, `template_check`,
`version_history`, `selfcheck`, and every key of the input `output_contract`.

- **`status`** — three honest states: `ok` needs a written deck, zero unverified source bullets, a
  genuine (not degraded) preview, passing compliance and no hard page failure; `insufficient_evidence`
  means no readable source (a three-page notice deck is still delivered); everything else is `partial`.
- **`editable_source`** — the openable deck: location, format label, byte count, content hash, page
  count, canvas size in EMU, requested mode, and design provenance (`template:<file>`,
  `starting-deck:<file>` or `builtin-default`).
- **`export_artifact`** — the preview: location, page count, size, conversion route and whether that
  route was a fallback; absent (`null`) when no conversion worked.
- **`content_map[]`** — one record per delivered page: narrative role, headline, layout name, speaker
  prompt, and bullets, each with visible text, source sentence, locator, verification flag and origin
  (`source` vs `front_matter`).
- **`compliance_checks`** — the contract guard: requested vs delivered counts, role order, design
  provenance, note coverage, text-fit model, figure accounting, evidence ratio, preview status, key
  accounting, and one `overall_pass`.
- **`page_golden` / `page_diff`** — where the frozen standard lives and its verdict summary: per-page
  outcomes, hard/soft gap tallies, headline-number and figure coverage, gap list.
- **`export_check` / `template_check`** — the two inspection reports: what the PDF really contains, and
  whether the organizer design survived; both carry item-level status plus evidence.
- **`version_history`** — skill lineage, one row per stage executed with its artifact, rollback switches.
- **`exceptions[]`** — failure records `{code, stage, detail}`; conversion failures add a suggested
  `action`.
- **`selfcheck`** — the closing independent pass over the delivered files: package members, preview
  page count, content-map length, contract echo, evidence rate and status honesty.

## Evidence and numbers

- Bullet = verbatim prefix of a source sentence; `quote` = whole sentence. Nothing rephrased, rounded
  or re-numbered.
- Locator grammar: `<source file> p.<page> <section>`; the section is the heading in force at that
  sentence's position.
- Numbers keep source notation (`27 percent`, `p < 0.01`, `1.2 million`); no conversion, no rounding.
- Figures are cited from embedded originals and labelled not-redrawn; captions quoted, never authored.
  Vector-only sources stay text-only with `embedded_from_source: 0`.
- Unverifiable quotes raise `QUOTE_UNVERIFIED` and stay visible; they are never silently repaired.

## Degradation table

| situation | behaviour |
|---|---|
| `case.json` missing/corrupt | `NO_CASE_JSON`, continue, contract keys 0, deck still attempted |
| fewer than 4 usable sentences | `LOW_SOURCE_TEXT` + `INSUFFICIENT_INPUT`, 3-slide notice deck, `insufficient_evidence` |
| no template | builtin 16:9 design, `pending_human` entry, inheritance items `n/a` |
| template unreadable | fall back to the starting deck's design when readable, else builtin; recorded in `degradations` |
| edit/adapt without starting deck | `EDIT_WITHOUT_STARTING_DECK`, mode degrades to generate |
| no LibreOffice/soffice | `PDF_TEXT_FALLBACK`: stdlib text-layer PDF marked degraded; pptx remains authoritative |
| export and fallback both fail | `PDF_RENDER_UNAVAILABLE`, `export_artifact: null`, pptx kept |
| PDF without text layer | little text extracted → `LOW_SOURCE_TEXT`; OCR out of scope |
| sentence pool exhausted | `POOL_EXHAUSTED`, page dropped, shortfall in `slide_count` and `uncertainty` |
| text overflow | font ladder 20/18/16 → 12 pt against a line-fit model; residual listed in `text_fit` and re-measured in `export_check` |
| template font missing | substitution reported in `export_check.fonts`, not hidden |
| stale `--reuse-plan` | `PLAN_REUSE_INVALID` / `PLAN_REUSE_MISS`; pages rebuilt from what matched |

## Self-check and reviewer protocol

The final `selfcheck` stage re-reads delivered files instead of trusting the build, writes
`selfcheck.json` and mirrors a summary in `result.json.selfcheck`. Manual re-check:

1. `--help` and `--version` exit 0.
2. `result.json` parses and has every `output_contract` key at the root.
3. `len(content_map) == editable_source.slides`; every `kind=source` bullet has `verified: true`.
4. The pptx opens as a zip with `ppt/presentation.xml`, one slide part and one notes part per slide;
   the PDF starts with `%PDF-` and has one page per slide.
5. `page_diff.md` covers every page and its gap index matches `result.json.page_diff.gaps`.
6. `template_check.json` items are `pass`, or their `warn`/`n/a` reason is visible in the evidence.

## Quality bar and troubleshooting

What separates an acceptable deck from a merely complete one, in the order a reviewer notices it:

1. **Order tells a story.** A reader who only sees the page titles should be able to predict the talk:
   why this problem, what was asked, how it was studied, what was measured, what it means, where it
   stops. If two adjacent results pages make the same point, one of them is a methods page or noise.
2. **One measured claim per results page.** The claim must contain the number, and that number must be
   the one the source reports in that context — not a nearby number from the abstract.
3. **Evidence is boring.** No bullet may be more interesting than its source sentence. If a bullet
   sounds smoother than the paper, it has probably been paraphrased and should be reverted.
4. **Template is invisible.** Fonts, colours, footer position and page geometry should look like the
   organizer's template, not like the skill's taste. The only visible change should be content.
5. **Notes help a speaker.** Notes say what to emphasise and how to bridge to the next page; they are
   not a second copy of the slide text and must not be cited as evidence.

Symptom → first check:

- *Slide count short of the request*: read `compliance_checks.slide_count` and `uncertainty`; if the
  sentence pool ran out, the honest fix is a shorter deck, not duplicated bullets.
- *A page shows the wrong section*: inspect its bullets' locators; a locator naming the wrong heading
  means the heading detector missed a heading (check `page_golden.deck.sections_available`).
- *A results page has no figure*: confirm the source actually embeds a JPEG; vector figures are out of
  scope and `figure_placement` will say `not_available_in_source`.
- *PDF is missing*: look at `export_artifact.method` and `exceptions`; a `PDF_TEXT_FALLBACK` means the
  runtime had no office converter and the preview is a text layer, while the pptx is still the source.
- *Template check warns*: read the check's evidence; a missing `ftr` slot or a font substitution is a
  recorded boundary, not a delivery failure.
- *A page hard-fails the diff*: rebuild from `--reuse-plan` after editing the plan, or fix the source
  extraction first — never patch the delivered JSON by hand.

Before publishing, open the pptx in a real presentation tool once. The automated checks cover headings,
placeholders and evidence; they cannot tell you that a title reads badly or that a figure sits where
the eye does not go.

## Budget, example, layout, limits

Built for 64 model requests / 900 s / 16384 tokens per response: no model call inside the script, one
process, at most one PDF conversion (280 s timeout), seconds end-to-end for 10–12 slides. Partial
`result.json` after discovery, `plan_v0.json` after planning, one `run.log` line per stage; a fatal
error rewrites `result.json` as `partial` with the traceback.

Minimal call (example only, not a formal case result): `case.json` with
`output_contract: ["case_id","status","editable_source","export_artifact","content_map","compliance_checks","exceptions"]`,
`paper.md`, and a workorder `{"mode":"generate","total_slides":8,"language":"en"}`:

```
python3 -B scripts/main.py --input /input --output /app/output
```

That demo yields 8 slides with every source bullet verified and `export_artifact.pages = 8`; its diff
may be `PASS` or `PARTIAL` depending on what the source names. These numbers describe the interface,
not a benchmark score.

Package: `scripts/main.py` (CLI + stages), `scripts/sourcekit.py` (discovery, contract echo,
extraction, sentence/section analysis, planning), `scripts/packaging.py` (OOXML assembly, design
inheritance, geometry, PDF fallback), `scripts/goldcheck.py` (golden standard, diff, history),
`scripts/verify.py` (compliance, export/template inspection, self-check), `scripts/design.py`
(compressed OOXML furniture + builtin design), `references/playbook.md` (role table, budgets, schemas,
checklist, limits). Change static XML in `design.py`, role rules in `sourcekit.PAGE_RULES` /
`ROLE_TITLES`, per-role contracts in `goldcheck.ROLE_SPEC`, geometry in `packaging.compose_slide`; then
re-run the checks on an English source, a Chinese source, a template case, a starting-deck case and
empty input, and confirm `--legacy-sections` still shows section gaps.

Known limits: scanned PDFs are not OCRed; only embedded JPEG figures are reused; tables/charts are
cited, not rebuilt; placeholder geometry is computed in the safe area rather than copying bespoke
rectangles (master/layouts/theme/footer still inherit).
