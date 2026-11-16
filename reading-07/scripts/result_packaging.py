"""result_packaging.py - post-processing for the claim-evidence auditor.

Two pure helpers used right before the final result.json is written:
  * audit_structure: machine assertions that the assembled result is internally
    consistent (claims reported, verdict domain, coverage arithmetic, quotes);
  * tag_verbatim: mark each evidence quote with whether it still occurs
    verbatim in a source unit.
Both return plain dicts/booleans; neither mutates verdicts.
"""

import evidence_kit as K


def audit_structure(claims, verifications, units, coverage, levels):
    """Post-hoc consistency assertions over the assembled result (added check)."""
    subs = [s for v in verifications for s in v.get("sub_claims", [])]
    quoted = [e for s in subs for e in s.get("evidence", [])]
    counts = {lv: sum(1 for v in verifications if v["verdict"] == lv) for lv in levels}
    sub_counts = {lv: sum(1 for s in subs if s["verdict"] == lv) for lv in levels}
    found = [
        ("all_input_claims_reported",
         [c["claim_id"] for c in claims] == [v["claim_id"] for v in verifications],
         "input=%d reported=%d" % (len(claims), len(verifications))),
        ("verdict_domain_closed",
         all(v["verdict"] in levels and all(s["verdict"] in levels
                                            for s in v.get("sub_claims", []))
             for v in verifications), "domain=four-levels"),
        ("each_subclaim_has_evidence_or_search_scope",
         all(s.get("evidence") or (s["verdict"] == "insufficient_evidence"
                                   and s.get("search_scope")) for s in subs),
         "subclaims=%d corpus_units=%d" % (len(subs), len(units))),
        ("coverage_arithmetic",
         coverage.get("claims_verified") == len(verifications)
         and coverage.get("split_subclaims") == len(subs)
         and sum(counts.values()) == len(verifications) and sum(sub_counts.values()) == len(subs)
         and all(coverage.get(k) == counts[k] for k in levels)
         and coverage.get("sub_claim_verdicts") == sub_counts, "coverage vs assembled counts"),
        ("all_quotes_verbatim", all(e.get("verbatim") is not False for e in quoted),
         "quotes=%d" % len(quoted)),
    ]
    checks = [{"check": name, "ok": bool(ok), "detail": detail} for name, ok, detail in found]
    issues = ["%s: %s" % (name, detail) for name, ok, detail in found if not ok]
    return {"passed": not issues, "checks": checks, "issues": issues,
            "claims_checked": len(verifications), "quotes_checked": len(quoted)}


def tag_verbatim(verifications, units):
    """Mark each evidence quote with whether it still occurs verbatim in a source unit."""
    flats = [K.squeeze(u["text"]) for u in units]
    for entry in verifications:
        for sub in entry.get("sub_claims", []):
            for ev in sub.get("evidence", []):
                needle = K.squeeze(ev.get("quote"))
                ev["verbatim"] = bool(needle) and any(needle in flat for flat in flats)
