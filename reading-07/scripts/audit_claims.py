#!/usr/bin/env python3
"""audit_claims.py - claim-versus-source evidence auditor (reading-07).

Claims are open questions: split into atomic sub-claims, locate verbatim
passages with locators, grade with one of four support levels, always leave a
readable result.json (exit code 0).
"""

import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evidence_kit as K  # noqa: E402
import result_packaging as R  # noqa: E402

try:  # optional additive layer: five verifiable assets (scripts/claim_assets.py)
    import claim_assets as A
except Exception:  # pragma: no cover - the core audit must work without the asset layer
    A = None


def _alog(event, message, **fields):
    """Best-effort run.log hook for the optional asset layer; never affects the audit."""
    if A is not None:
        try:
            A.log(event, message, **fields)
        except Exception:
            pass

VERSION = "1.0.0"
START = time.time()
LEVELS = ("supported", "partially_supported", "contradicted", "insufficient_evidence")
TYPE_RULES = (("causal", "causal"), ("compare", "comparison"), ("scope", "scope"))
EVIDENCE_NEED = {"fact": "same finding stated explicitly",
                 "comparison": "both entities, same metric, same direction",
                 "causal": "causal link or intervention result",
                 "scope": "sampled domain or condition"}
METHOD_NOTES = {"levels": "四级定义见 references/support-levels.md",
                "gate": "覆盖度>=0.72 且无未对齐要素才可 supported；<0.40 归 insufficient_evidence",
                "conflict": "相反证据两处并列，判定保留，不折中",
                "deterministic": "规则固定、无随机采样；同一输入重复运行结果一致"}
AGGREGATION_RULE = ("任一子判断 contradicted 且无相反来源→contradicted；有冲突并列→partially_supported；"
                    "全部 supported→supported；全部 insufficient_evidence→insufficient_evidence；"
                    "其余→partially_supported")
SPLITTER = re.compile(r"(?:[，,]\s*)?(?:并且|而且|同时|此外|另外|以及|但是|然而|不过|但|且|"
                      r"and\s+also|,\s*(?:and|but|while|whereas|although)\s+)")
COMPARE_PAIR = re.compile(r"([A-Za-z0-9\u4e00-\u9fff%\.\-]{1,24})\s*(?:高于|低于|优于|劣于|大于|小于)"
                          r"\s*([A-Za-z0-9\u4e00-\u9fff%\.\-]{1,24})")
COMPARE_TAIL = re.compile(r"(?:compared (?:with|to)|than|versus|vs\.?|相比|比)\s*"
                          r"([A-Za-z0-9\u4e00-\u9fff%\.\- ]{1,30})", re.I)
CONDITION = re.compile(r"(?:在[^，。；]{2,40}?条件下|当[^，。；]{2,30}?时|在[^，。；]{2,30}?范围内|"
                       r"under [^,.;]{3,50}? conditions?|for [^,.;]{3,40}? samples?|"
                       r"in [^,.;]{3,40}? (?:group|cohort|setting))", re.I)


def make_subclaim(fragment, ordinal):
    text = K.tidy_space(fragment)
    kind = next((label for cue_name, label in TYPE_RULES if K.cue_hits(cue_name, text)), "fact")
    pair = COMPARE_PAIR.search(text)
    comparator = "%s vs %s" % (pair.group(1), pair.group(2)) if pair else None
    if not comparator:
        tail = COMPARE_TAIL.search(text)
        comparator = tail.group(1).strip(" ,，。.") if tail else None
    scope_match = CONDITION.search(text)
    return {"sub_id": "S%d" % ordinal, "text": text, "type": kind,
            "required_evidence_type": EVIDENCE_NEED[kind], "comparator": comparator,
            "negation": K.is_negated(text), "significance": bool(K.cue_hits("sig", text)),
            "conditions": scope_match.group(0) if scope_match else None,
            "quantifier": ";".join(K.cue_hits("scope", text)[:2]) or None,
            "numbers": K.numeric_tokens(text), "terms": K.key_terms(text)}


def split_claim(claim_text, limit=7):
    cleaned = K.tidy_space(claim_text)
    fragments = []
    for clause in re.split(r"[；;。\n]+", cleaned):
        trimmed = clause.strip(" ，,、")
        fragments += [p.strip(" ，,、") for p in SPLITTER.split(trimmed)
                      if len(p.strip(" ，,、")) >= 4]
    if len(fragments) <= 1:
        comma_parts = [p.strip() for p in re.split(r"[，,]", cleaned) if len(p.strip()) >= 6]
        directional = (len(comma_parts) == 2 and K.polarity(comma_parts[0]) != "none"
                       and K.polarity(comma_parts[1]) != "none")
        fragments = comma_parts if directional else ([cleaned] if cleaned else [])
    seen, subclaims = set(), []
    for fragment in fragments:
        fingerprint = re.sub(r"\s+", "", fragment)[:60]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        subclaims.append(make_subclaim(fragment, len(subclaims) + 1))
    if not subclaims:
        subclaims = [make_subclaim(cleaned or "(empty claim)", 1)]
    return subclaims[:limit]


def grade_subclaim(sub, units, keep=6):
    corpus_low = [(u, u["text"].lower()) for u in units]
    anchors = K.hard_anchors(sub["text"])
    spread = {a: sum(1 for _, low in corpus_low if a in low.replace(" ", "")) for a in set(anchors)}
    candidates, scanned = [], 0
    for unit, _low in corpus_low:
        scanned += 1
        for win in K.span_windows(unit):
            low = win["text"].lower()
            packed = low.replace(" ", "")
            hits = [t for t in sub["terms"] if t.lower() in low]
            coverage = len(hits) / float(len(sub["terms"])) if sub["terms"] else 0.0
            if coverage <= 0.05:
                continue
            anchor_hits = [a for a in anchors if a in packed]
            if anchors and not anchor_hits:
                coverage *= K.ANCHOR_PENALTY
            candidates.append({"win": win, "cov": coverage, "hit": hits, "ah": len(anchor_hits),
                               "asc": round(sum(1.0 / max(1, spread.get(a, 1)) for a in anchor_hits), 3),
                               "num": [n for n in sub["numbers"] if n in packed]})
    candidates.sort(key=lambda c: (c["asc"], c["ah"], round(c["cov"], 3),
                                   1 if c["num"] else 0, -len(c["win"]["text"])), reverse=True)
    top = candidates[:keep]
    scope = {"units_scanned": scanned,
             "sentence_windows": sum(len(u["sentences"]) for u in units),
             "candidates_kept": len(top)}
    if not top:
        return {"verdict": "insufficient_evidence", "verdict_confidence": "high", "evidence": [],
                "alternative": None, "rationale": "无共享实质内容词，至多主题相关。",
                "limitations": [], "search_scope": scope, "counter_evidence_searched": True}
    winner, passage = top[0], top[0]["win"]["text"]
    claim_dir, past_dir = K.polarity(sub["text"]), K.polarity(passage)
    missing = []
    if sub["significance"] and not K.cue_hits("sig", passage):
        missing.append("significance_not_reported: 原文未报告 P 值")
    if sub["numbers"] and not set(sub["numbers"]) & set(K.numeric_tokens(passage)):
        pool = K.numeric_tokens(passage)
        missing.append("reported_value_differs: 原文 %s / 论断 %s"
                       % ("/".join(pool[:3]), "/".join(sub["numbers"][:3]))
                       if pool else "quantity_not_reported: 原文未给出数值")
    if sub["quantifier"] and not K.cue_hits("scope", passage):
        missing.append("scope_not_established: 全称限定（%s）缺适用域" % sub["quantifier"])
    if sub["conditions"]:
        cond_terms = K.key_terms(sub["conditions"], limit=8)
        if cond_terms and not any(t.lower() in passage.lower() for t in cond_terms):
            missing.append("condition_not_matched: 条件「%s」未出现" % sub["conditions"])
    unit = winner["win"]["unit"]
    if anchors and winner["ah"] < len(set(anchors)):
        missing.append("anchor_not_matched: 论断数值/型号 %s 未全部出现"
                       % "/".join(sorted(set(anchors))[:3]))
    primary = {"source_id": unit["source_id"], "unit_id": unit["unit_id"],
               "locator": dict(unit["locator"]), "label": K.locator_label(unit),
               "quote": passage, "supports": True, "role": "minimal_sufficient",
               "coverage": round(winner["cov"], 3)}

    def emit(verdict, conf, reason, evidence=None, alternative=None, extra=()):
        return {"verdict": verdict, "verdict_confidence": conf,
                "evidence": evidence if evidence is not None else [primary],
                "alternative": alternative, "rationale": reason,
                "limitations": missing + list(extra), "search_scope": scope,
                "counter_evidence_searched": True}

    opposite = None
    if claim_dir in ("up", "down") and past_dir in ("up", "down") and claim_dir != past_dir:
        opposite = "原文方向与论断相反（%s/%s）" % (claim_dir, past_dir)
    elif K.is_negated(sub["text"]) != K.is_negated(passage) and winner["cov"] >= 0.80:
        opposite = "否定极性相反"
    if opposite:
        primary.update({"supports": False, "role": "counter"})
        return emit("contradicted", "medium", "%s；覆盖度 %.2f；证据句：%s"
                    % (opposite, winner["cov"], passage[:180]))
    reference_dir = past_dir if past_dir in ("up", "down") else claim_dir
    alt_hit = None
    if reference_dir in ("up", "down") or sub["type"] in ("comparison", "causal"):
        for cand in top[1:]:
            c_unit, b_unit = cand["win"]["unit"], winner["win"]["unit"]
            cand_dir = K.polarity(cand["win"]["text"])
            same_place = (c_unit["source_id"] == b_unit["source_id"]
                          and c_unit.get("section") == b_unit.get("section"))
            anchors_all = all(a in cand["win"]["text"].lower().replace(" ", "") for a in anchors)
            if (cand["cov"] >= max(0.42, winner["cov"] - 0.55)
                    and reference_dir in ("up", "down") and cand_dir in ("up", "down")
                    and cand_dir != reference_dir and anchors_all and not same_place):
                alt_hit = cand
                break
    if winner["cov"] < K.WEAK_CUT:
        return emit("insufficient_evidence", "medium", "最佳证据仅覆盖 %.0f%% 内容词（%s），属主题相关。"
                    % (winner["cov"] * 100, "、".join(winner["hit"][:6])))
    if alt_hit is not None:
        other_unit = alt_hit["win"]["unit"]
        alt_ev = {"source_id": other_unit["source_id"], "unit_id": other_unit["unit_id"],
                  "locator": dict(other_unit["locator"]), "label": K.locator_label(other_unit),
                  "quote": alt_hit["win"]["text"], "supports": False, "role": "counter",
                  "coverage": round(alt_hit["cov"], 3)}
        return emit("partially_supported", "low", "不同位置方向相反，判定保留：%s vs %s（%s/%s）"
                    % (primary["label"], past_dir, alt_ev["label"], K.polarity(alt_ev["quote"])),
                    alternative=alt_ev, extra=["conflicting_sources"])
    if winner["cov"] >= K.STRONG_CUT and not missing:
        return emit("supported", "high", "覆盖度 %.2f，方向/否定/数值/限定一致：%s"
                    % (winner["cov"], passage[:180]))
    if winner["cov"] >= K.STRONG_CUT:
        return emit("partially_supported", "medium", "覆盖主要内容词但要素未对齐：%s"
                    % "；".join(missing)[:220])
    return emit("partially_supported", "medium", "仅部分要素被支持（覆盖度 %.2f）：%s"
                % (winner["cov"], passage[:180]))

def audit_claim(claim, units):
    subclaims = split_claim(claim["claim_text"])
    for sub in subclaims:
        if "verdict" not in sub:
            sub.update(grade_subclaim(sub, units))
    overall = K.combine_verdicts(subclaims)
    conf = ("high" if all(s["verdict_confidence"] == "high" for s in subclaims)
            else ("low" if any(s["verdict_confidence"] == "low" for s in subclaims) else "medium"))
    return {"claim_id": claim["claim_id"], "claim_text": claim["claim_text"],
            "claim_kind": subclaims[0]["type"], "sub_claims": subclaims, "verdict": overall,
            "verdict_confidence": conf, "aggregation_rule": AGGREGATION_RULE,
            "evidence_path": "rule_engine", "conflict": K.conflict_block(subclaims),
            "limitations": list(dict.fromkeys(x for s in subclaims for x in s["limitations"])),
            "comparator": next((s["comparator"] for s in subclaims if s["comparator"]), None),
            "negation": any(s["negation"] for s in subclaims),
            "significance": any(s["significance"] for s in subclaims),
            "conditions": next((s["conditions"] for s in subclaims if s["conditions"]), None),
            "status": "verified" if overall != "insufficient_evidence" else "insufficient_evidence"}


def empty_result(case_id, status, contract=None):
    coverage = dict({"claims_requested": 0, "claims_verified": 0, "split_subclaims": 0,
                     "corpus_units": 0}, **{level: 0 for level in LEVELS})
    res = {"case_id": case_id, "status": status,
           "result": {"task": "literature_evidence_verification", "verifications": [],
                      "coverage": coverage, "aggregation_rule": AGGREGATION_RULE,
                      "method_notes": METHOD_NOTES, "artifacts": {}},
           "claims": [], "uncertainties": [], "sources": [], "pending_human": [],
           "errors": [], "degradations": [], "changes": [], "gaps": [],
           "runtime": {"version": VERSION, "python": sys.version.split()[0], "elapsed_sec": 0.0}}
    res["uncertainty"] = res["uncertainties"]
    for key, spec in (contract or {}).items():
        if key not in res:
            hint = spec.lower() if isinstance(spec, str) else ""
            res[key] = ([] if ("list" in hint or "array" in hint)
                        else ({} if ("dict" in hint or "object" in hint) else None))
            res["degradations"].append({"issue": "contract_field_filled_empty", "field": key})
        elif key == "result" and isinstance(spec, dict):
            res["result"].update({sub: res["result"].get(sub) for sub in spec})
            res["degradations"] += [{"issue": "contract_subfield_filled_empty",
                                     "field": "result." + sub}
                                    for sub in spec if sub not in res["result"]]
    return res


def save_result(target_dir, res):
    res["runtime"].update({"elapsed_sec": round(time.time() - START, 2), "finished": True})
    res["uncertainty"] = res["uncertainties"]
    (target_dir / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=2),
                                            encoding="utf-8")


def read_case(input_dir):
    for path in [input_dir / "case.json"] + sorted(input_dir.glob("case*.json")):
        if path.exists():
            try:
                obj = json.loads(K.slurp_text(path) or "null")
                return (obj if isinstance(obj, dict) else {}), str(path)
            except Exception:
                return {"_parse_error": "case json is not valid JSON"}, str(path)
    return {}, None


def conclusion_row(entry):
    subs = entry.get("sub_claims", [])
    pairs = [(s["sub_id"], ev) for s in subs for ev in s.get("evidence", [])]
    first = pairs[0][1] if pairs else {}
    return {"claim_id": "V-" + str(entry["claim_id"]), "input_claim_id": entry["claim_id"],
            "kind": entry.get("claim_kind") or "fact", "text": entry["claim_text"],
            "verdict": entry["verdict"],
            "evidence": [dict(sub_id=ident, source_id=ev.get("source_id"),
                              quote=ev.get("quote"), location=ev.get("locator"),
                              supports=ev.get("supports"), role=ev.get("role"))
                         for ident, ev in pairs],
            "source_id": first.get("source_id"), "location": first.get("locator"),
            "conditions": next((s.get("conditions") for s in subs if s.get("conditions")), None),
            "readability": {"supported": "directly_read", "contradicted": "directly_read",
                            "partially_supported": "inferred"}.get(entry["verdict"],
                                                                   "undetermined"),
            "sub_claim_verdicts": {s["sub_id"]: s["verdict"] for s in subs}}


def placeholder(claim, limitation, why, status):
    return {"claim_id": claim["claim_id"], "claim_text": claim["claim_text"],
            "sub_claims": [], "limitations": [limitation], "verdict": "insufficient_evidence",
            "verdict_confidence": "low", "status": status, "rationale": why,
            "conflict": {"conflict": False, "both_sides": []}}


def execute(args):
    inp = next((c.resolve() for c in
                ([Path(args.input)] if args.input else []) +
                [Path("/input"), Path("/app/input"), Path.cwd() / "input", HERE.parent / "input"]
                if c.exists()), Path(args.input or "/input"))
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    res = empty_result("unknown", "partial")
    save_result(out, res)
    _alog("stage", "partial result written", output=str(out))
    try:
        case, case_path = read_case(inp)
        nested = case.get("input") if isinstance(case.get("input"), dict) else {}
        case_id = (case.get("case_id") or case.get("id") or nested.get("case_id")
                   or Path(case_path or "unknown").stem)
        res = empty_result("%s" % case_id, "partial", case.get("output_contract"))
        res["runtime"].update({"input_dir": str(inp), "case_file": case_path})
        _alog("input", "case file read", case_file=case_path, case_id=case_id,
              parse_error=bool(case.get("_parse_error")))
        if case.get("_parse_error"):
            res["errors"].append({"stage": "input", "issue": case["_parse_error"],
                                  "action": "continue"})
        save_result(out, res)
        claims, claims_origin, claim_gaps = K.discover_claims(inp, case)
        units, sources, degradations, gaps = K.collect_corpus(
            inp, skip=[p for p in (claims_origin, case_path) if p])
        for unit in units:
            unit["sentences"] = K.sentence_spans(unit["text"])
        res["runtime"]["claims_file"] = claims_origin
        res["sources"], res["gaps"] = sources, claim_gaps + gaps
        res["degradations"] = res["degradations"] + degradations
        res["result"]["corpus_units"] = len(units)
        _alog("corpus", "claims and corpus scanned", claims=len(claims),
              origin=claims_origin, sources=len(sources), units=len(units),
              degradations=len(res["degradations"]))
        if not units:
            res["pending_human"].append({"action": "提供可读原文",
                                         "reason": "input 下无可解析的原文段落"})
        if not claims:
            res["status"] = "input_error"
            _alog("claims", "no claims found", status="input_error")
            res["errors"].append({"stage": "claims", "issue": "no claims_to_verify found",
                                  "detail": "looked for claims-to-verify.json and case.json claims keys"})
            res["pending_human"].append({"action": "补充待核验论断清单",
                                         "reason": "缺少 claims，无法核验"})
            save_result(out, res)
            return res
        verifications, budget_hit = [], False
        for claim in claims:
            if time.time() - START > max(30.0, float(args.max_seconds)):
                budget_hit = True
                res["degradations"].append({"stage": "budget", "issue": "time_budget_reached",
                                            "detail": "remaining claims -> insufficient_evidence"})
                break
            try:
                entry = audit_claim(claim, units)
                verifications.append(entry)
                _alog("claim", "verified", claim_id=entry["claim_id"],
                      verdict=entry["verdict"],
                      subclaims=len(entry.get("sub_claims") or []))
            except Exception as exc:
                res["errors"].append({"stage": "claim", "claim_id": claim["claim_id"],
                                      "issue": "verification_failed",
                                      "detail": "%s: %s" % (type(exc).__name__, exc),
                                      "trace": traceback.format_exc(limit=2)})
                verifications.append(placeholder(claim, "runtime_error",
                                                 "核验异常，需人工复核", "error"))
        seen = {v["claim_id"] for v in verifications}
        verifications += [placeholder(c, "not_processed_budget", "未及处理（时间预算），需重跑",
                                      "pending") for c in claims if c["claim_id"] not in seen]
        R.tag_verbatim(verifications, units)
        subclaims = [s for v in verifications for s in v.get("sub_claims", [])]
        coverage = dict({level: sum(1 for v in verifications if v["verdict"] == level)
                         for level in LEVELS},
                        claims_requested=len(claims), claims_verified=len(verifications),
                        split_subclaims=len(subclaims), corpus_units=len(units),
                        sub_claim_verdicts={level: sum(1 for s in subclaims
                                                       if s["verdict"] == level)
                                            for level in LEVELS})
        res["result"].update({"verifications": verifications,
                              "claims_requested": len(claims), "coverage": coverage,
                              "artifacts": {"result_json": "result.json",
                                            "evidence_cards": "evidence_cards.jsonl",
                                            "report": "verification_report.md"}})
        res["claims"] = [conclusion_row(v) for v in verifications]
        for entry in verifications:
            for sub in entry.get("sub_claims", []):
                anchor = {"claim_id": entry["claim_id"], "sub_id": sub["sub_id"]}
                if sub["verdict"] == "insufficient_evidence":
                    res["uncertainties"].append(dict(
                        anchor, issue="原文未提供可判定证据（不足≠证伪）",
                        searched=sub.get("search_scope", {}), action="人工复核或补充材料"))
                res["uncertainties"] += [dict(anchor, issue=item,
                                              action="核对条件差异"
                                              if item.startswith("conflicting") else "")
                                         for item in sub.get("limitations", [])]
        res["self_check"] = R.audit_structure(claims, verifications, units, coverage, LEVELS)
        _alog("self_check", "structure audit", passed=res["self_check"]["passed"],
              checks=len(res["self_check"].get("checks") or []),
              issues=len(res["self_check"].get("issues") or []))
        if not res["self_check"]["passed"]:
            res["degradations"].append({"stage": "self_check", "issue": "structure_mismatch",
                                        "detail": "; ".join(res["self_check"]["issues"])[:400]})
        (out / "evidence_cards.jsonl").write_text(
            "\n".join(K.card_jsonl(verifications)) + ("\n" if verifications else ""),
            encoding="utf-8")
        res["status"] = ("input_error" if not verifications
                         else "partial" if (res["errors"] or budget_hit)
                         else "insufficient_evidence"
                         if all(v["verdict"] == "insufficient_evidence" for v in verifications)
                         else "ok")
        save_result(out, res)
        K.render_report(out, res)
        _alog("report", "verification_report.md written")
        return res
    except Exception as exc:
        res["status"] = "partial" if res.get("errors") else "input_error"
        res["errors"].append({"stage": "run", "issue": "unhandled",
                              "detail": "%s: %s" % (type(exc).__name__, exc),
                              "trace": traceback.format_exc(limit=3)})
        _alog("error", "unhandled exception", detail="%s: %s" % (type(exc).__name__, exc))
        save_result(out, res)
        return res


def cli(argv=None):
    parser = argparse.ArgumentParser(
        description="Audit literature claims against supplied sources: split compound statements, "
                    "quote verbatim passages with locators, and grade each judgement as supported / "
                    "partially_supported / contradicted / insufficient_evidence. Always exits 0.",
        epilog="python3 -B audit_claims.py --input /input --output /app/output")
    parser.add_argument("--input", default="/input",
                        help="directory holding case.json, claim list and source materials")
    parser.add_argument("--output", default="/app/output",
                        help="directory for result.json, evidence cards and the report")
    parser.add_argument("--max-seconds", dest="max_seconds", type=float, default=780.0,
                        help="soft wall-clock budget before remaining claims are left pending")
    args = parser.parse_args(argv)
    out = Path(args.output)
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    if A is not None:
        try:
            A.start(argv_list, args.input, str(out))
        except Exception:
            pass
    try:
        result = execute(args)
    except Exception as exc:
        out.mkdir(parents=True, exist_ok=True)
        result = empty_result("unknown", "input_error")
        result["errors"].append({"stage": "main", "issue": "fatal", "detail": str(exc)})
        save_result(out, result)
    if A is not None:
        try:
            A.attach(out, result, args.input, argv_list)   # five verifiable assets
        except Exception:
            pass
        try:
            save_result(out, result)                       # persist verifiable_assets
        except Exception:
            pass
    cov = result.get("result", {}).get("coverage", {})
    print("status=%s claims=%s subclaims=%s self_check=%s -> %s"
          % (result.get("status"), cov.get("claims_requested"), cov.get("split_subclaims"),
             (result.get("self_check") or {}).get("passed"), out / "result.json"))
    if A is not None:
        try:
            A.settle(out, result)                          # exit line + final result.json
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(cli())
