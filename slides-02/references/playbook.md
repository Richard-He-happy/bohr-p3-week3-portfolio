# Deck quick checklist

Use this page when reviewing a run; the authoritative contract is `SKILL.md`.

**Plan** — role order starts at a title and ends at a closing page; every content page has at least
one quote; a requested count the source cannot fill is dropped, not padded; the plan hash in
`plan_v0.json` matches the hash printed in `run.log`.

**Evidence** — resolve each locator by hand once (`file p.N section`): the quoted sentence must exist
on that page under that heading, unchanged, with its original numerals and units. A bullet whose
`verified` flag is false belongs in front of a human, not in a reworded slide.

**Delivery** — unzip the deck: content types, `ppt/presentation.xml`, one slide plus one notes part per
page, master/layout/theme parts equal to the template's. The preview PDF starts with `%PDF-`, has the
same page count, and either the converter engine or a text-layer fallback is named in
`export_artifact.method`.

**Honesty** — compare `status` with `exceptions`: a degraded preview or a soft gap must not be hidden
behind `ok`; a missing template, figure or page count must appear in `pending_human`; failed checks
must stay `fail` in the inspection reports.

**Repeatability** — two runs on the same input should produce the same roles, slide count, verdicts and
contract echo; timestamps and file hashes are expected to change.
