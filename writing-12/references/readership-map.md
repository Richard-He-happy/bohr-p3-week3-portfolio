# Readership × genre quick reference (depth, skeleton, pruning, strength)

Use together with the `audience` and `genre` blocks of the draft. Pick the reader in section 1, the skeleton in section 2, then control cuts and claims with sections 3 and 4.

## 1. Audience matrix: depth first, length second

| Reader | Background | Question they bring | Explanation depth | Terminology | Analogy | Typical length |
|---|---|---|---|---|---|---|
| Industry partner / investor | engineering or business, no bench experience | can it be used, at what cost, what risk | one causal layer plus key metrics | keep 3–5 terms, expand at first use, rename the rest | compare with an existing line or baseline | 800–1500 chars |
| Grant or project panel | same or adjacent field | novelty, feasibility, strength of evidence | method highlights plus evidence chain | domain terms fine, expand abbreviations | rarely needed | 1000–2000 chars |
| Policy and administration | non-technical, impact oriented | who is affected, what regulation is needed | conclusion plus conditions plus boundaries | plain wording, avoid abbreviations | scenario-based | 600–1200 chars |
| General public | no professional training | why this matters to me | conclusion plus a single mechanism metaphor | no abbreviations, or full name at first use | everyday analogy, no hype | 500–1200 chars |
| Peers (abstract / technical report) | same field | can it be reproduced, is it reliable | full method highlights and statistics | standard terms, expand at first use | none | per journal template |

## 2. Genre skeletons

| Genre | Required order | Claim treatment | Forbidden |
|---|---|---|---|
| Technical transfer brief | one-sentence conclusion → problem → approach → key data with conditions → deployment conditions and risk → to be validated | mark bench-scale results "bench scale"; outlook stays in a "to be validated" slot | presenting in-vitro or small-sample results as achieved |
| Grant-application summary | need → objective → technical route → prior results → novelty → plan | novelty must map to existing data; plan and results are separate | writing the plan as completed work |
| Popular-science article | phenomenon → mechanism metaphor → evidence (1–2 numbers) → limitations → significance | shift one level down: `established`→"the study found"; `preliminary`→"early results suggest" | "cure / solve completely / disrupt" |
| Journal abstract | background → methods → results (with n and statistics) → conclusion | same level as the source, qualifiers untouched | dropping sample size or statistical basis |
| Policy brief | conclusion → impact surface → conditions and risk → recommendations | recommendations stand alone and say "recommend" | presenting recommendations as facts |

## 3. Pruning order (drop from the outside in)

1. **Delete first**: acknowledgements, funding and submission details, repeated phrasing, derivations irrelevant to this reader, literature stacking.
2. **Compress next**: instrument models, reagent lot numbers, method parameters → one "method overview" sentence; values unchanged.
3. **Compress only, never delete**: sample sizes and groups, dose/duration/platform, baselines, statistical basis → shorter wording is fine, missing information is not.
4. **Never touch**: main conclusion, key numbers and units, limitations and uncertainty, figure/table identifiers (if absent, note "no number in the source").

Self-test: after the cut, can the reader still judge the conditions under which the conclusion holds? If not, evidence was removed.

## 4. Claim-strength table (downgrade only)

| Source wording | Level | Allowed adaptation | Forbidden adaptation |
|---|---|---|---|
| significantly improved / demonstrated (statistical test present) | established | "the study found … (p<0.05, n=6)" | "solved completely" |
| suggests / preliminary / in an in-vitro model | preliminary | "early results suggest …, in-vivo validation pending" | "proven effective" |
| may / hypothesised / mechanistically plausible | hypothesis | "the authors hypothesise …, mechanism unverified" | "because X, therefore Y" (causal claim) |
| promising / has potential | commercial extrapolation | keep "promising" and add a `pending_human` item | "will create a … market" (unsupported) |

One object, one name across the piece (e.g. keep "conversion" and do not alternate with "yield"); give the English original at first use of a term.

## 5. Anti-patterns and fixes

| Symptom | Root cause | Fix |
|---|---|---|
| numbers rounded, units dropped, sample size lost | writing without checking | verify against the source and lock each value in `preserved` |
| abbreviation wall or formulas in a public piece | depth not lowered | reset the terminology policy per section 1 and rewrite that paragraph |
| preliminary written as proven, correlation as causation | strength not downgraded | downgrade per section 4 and add an `uncertainty` entry |
| only headings and bullets | outline mistaken for body | `check` raises `too_short`; write the prose |
| body exists but no provenance | `map` left empty | add at least one entry per section, covering the must-keep content |
| market, cost or schedule claims appear | the agent extrapolated for the author | delete or move to `pending_human` |
| "this article will discuss" appears | meta-discourse survived | restate as content |

## 6. Final 60-second review

- Does the opening paragraph tell the target reader what this has to do with them?
- Does every number carry unit, condition and sample size? Does every conclusion carry its qualifier?
- Is every abbreviation expanded once? Is every concept named once?
- Does `map` cover all conclusion-bearing paragraphs? Does `changes` cover every edit?
- Is there a sentence with no support in the source? Delete it or move it to `pending`.
