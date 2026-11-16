#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evidence-grounded writing pipeline (writing-03, v1.1.0).

Commands (all exit 0, standard library only, offline, CWD independent):

  init    index /input materials + first partial result.json (no judgement)
  show    print material sentences with locators so a quote can be copied exactly
  check   validate an optional agent work draft under /app/work
  build   compose claims -> evidence_table -> draft, finalise result.json and
          write the five verifiable assets (also the default when no command
          is given; a missing work draft is covered by material-only fallback)
  audit   re-read the material and re-check the emitted artefacts

The agent-facing contract is intentionally narrow: /input in, /app/output out,
/app/work for working notes.  Every failure path still leaves a legal partial
result.json on disk and returns 0.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit import (VERSION, NEG_HINT, POS_HINT, units_of, claim_kind, ref_ent, bag_of,
                   abstract_only, overlap, grade_row, ref_text, scan_inputs, soften,
                   sentences, trim_cites, wo_checks, side_records, audit_out)
import assets as assetkit

CONTRACT_FIELDS = ["case_id", "deliverable", "preserved_facts", "evidence_map", "change_log"]
COMMANDS = ("init", "show", "check", "build", "all", "audit")
WORK_DRAFT_FILES = ("draft.json", "claims.json", "evidence.json", "plan.json", "draft.md")

PHRASES = { "zh": { "t": "证据支撑稿（{c}）", "lim": "证据边界", "ref": "参考文献", "h": {"高": "多项证据一致", "中": "研究提示", "低": "初步线索", "不足": "材料不足以判断"}, "cf": "但材料亦有相反结果：", "uc": "（待核）", "lm": "低强度或证据不足的论断仅作线索（%s）|材料内部存在未合并的冲突结果（%s）|" "部分来源仅摘要可核，未回原文确认|著录信息未联网核验", "rm": "（无著录；{s}，{l}）", "rs": "材料内文献表", "rt": "按首次引用编号；未给 DOI 不补写", },
    "en": { "t": "Evidence draft ({c})", "lim": "Boundaries", "ref": "References", "h": {"高": "Evidence indicates that", "中": "Studies suggest that", "低": "Preliminary evidence suggests", "不足": "The material cannot determine"}, "cf": "However, contrary findings exist: ", "uc": " (to be verified)",
        "lm": "Weak claims serve as leads only (%s)|Unresolved conflicting findings kept (%s)|"
              "Abstract-only sources not checked against full text|Bibliographic data not verified online",
        "rm": "(no record; source {s})", "rs": "Reference list as given",
        "rt": "First-citation order; no invented DOI",
    },
}


def dump_json(path, payload):
    """Atomic JSON write so a crash never leaves a truncated result."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)


def save_text(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, "utf-8")


# --------------------------------------------------------------------------- #
# agent work draft
# --------------------------------------------------------------------------- #
def _normalise_claim(item, index, fallback_location="work:draft"):
    text = str(item.get("text") or item.get("claim") or item.get("sentence") or "").strip()
    if not text:
        return None
    return {
        "claim_id": str(item.get("claim_id") or item.get("id") or "C%03d" % index),
        "text": text,
        "core": str(item.get("core") or trim_cites(text)),
        "type": str(item.get("type") or claim_kind(text)),
        "location": str(item.get("location") or item.get("locator") or fallback_location),
    }


def _normalise_evidence(item, claim_ids):
    if not isinstance(item, dict):
        return None
    quote = item.get("quote") or item.get("quotation")
    row = {
        "claim_id": str(item.get("claim_id") or item.get("id") or ""),
        "source_id": item.get("source_id") or item.get("source"),
        "locator": item.get("locator") or item.get("location"),
        "quote": quote if isinstance(quote, str) and quote.strip() else None,
        "strength": item.get("strength") if item.get("strength") in ("高", "中", "低", "不足") else None,
        "support_scope": item.get("support_scope"),
        "conflicts": item.get("conflicts") if isinstance(item.get("conflicts"), list) else [],
        "rationale": item.get("rationale") or "来源：Agent 工作稿（quote 由脚本回原文逐字复核）",
    }
    if not row["claim_id"] or (claim_ids and row["claim_id"] not in claim_ids):
        return None
    return row


def load_work_draft(work, case_id=None):
    """Read /app/work/draft.json (or draft.md); never raises. Returns a dict.

    A draft that names a different case_id is ignored (stale work directory).
    """
    info = {"path": None, "used": False, "kind": None, "claims": [], "evidence": [],
            "preserved_facts": [], "change_log": [], "notes": "", "error": None, "draft_text": None}
    work = Path(work)
    for name in WORK_DRAFT_FILES:
        path = work / name
        if not path.is_file():
            continue
        try:
            if path.suffix.lower() == ".json":
                data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(data, dict) and data.get("case_id") and str(data.get("case_id")) != str(case_id) and case_id not in (None, "UNKNOWN"):
                    info["error"] = "stale draft for case_id=%s (current=%s)" % (data.get("case_id"), case_id)
                    continue
                raw_claims, raw_evidence = [], []
                if isinstance(data, list):
                    raw_claims = data
                elif isinstance(data, dict):
                    raw_claims = data.get("claims") or data.get("claim_list") or data.get("items") or []
                    raw_evidence = (data.get("evidence") or data.get("evidence_rows")
                                    or data.get("rows") or (data.get("evidence_table") or {}).get("rows")
                                    or data.get("evidence_table") or [])
                    info["preserved_facts"] = data.get("preserved_facts") or []
                    info["change_log"] = data.get("change_log") or data.get("changes") or []
                    info["notes"] = str(data.get("notes") or "")
                claims = []
                evidence = []
                for index, item in enumerate(raw_claims if isinstance(raw_claims, list) else [], 1):
                    if not isinstance(item, dict):
                        continue
                    claim = _normalise_claim(item, index)
                    if claim:
                        claims.append(claim)
                        row = _normalise_evidence(item, {claim["claim_id"]})
                        if row:
                            evidence.append(row)
                        for nested in item.get("evidence") or []:
                            if isinstance(nested, dict) and not nested.get("claim_id"):
                                nested = dict(nested, claim_id=claim["claim_id"])
                            nested_row = _normalise_evidence(nested, {claim["claim_id"]})
                            if nested_row:
                                evidence.append(nested_row)
                claim_ids = {claim["claim_id"] for claim in claims}
                for item in raw_evidence if isinstance(raw_evidence, list) else []:
                    row = _normalise_evidence(item, claim_ids)
                    if row:
                        evidence.append(row)
                if claims or evidence:
                    info.update(path=str(path), used=True, kind="json", claims=claims, evidence=evidence)
                    return info
            else:
                text = path.read_text(encoding="utf-8", errors="ignore")
                picked = [part for part in sentences(text) if len(part.strip()) >= 8]
                if picked:
                    info.update(path=str(path), used=True, kind="md", draft_text=text)
                    return info
        except Exception as exc:
            info["error"] = "%s: %s" % (type(exc).__name__, exc)
    return info


def choose_claims(ctx, work_draft):
    """Return (claims, mode, draft_doc, origin): agent work draft first, else material."""
    if work_draft.get("used") and work_draft.get("kind") == "json" and work_draft.get("claims"):
        claims = work_draft["claims"]
        return claims, "synthesize", None, "work-draft"
    if work_draft.get("used") and work_draft.get("kind") == "md":
        text = work_draft.get("draft_text") or ""
        doc = {"doc_id": "WORK", "path": work_draft.get("path"), "kind": "draft", "text": text,
               "method": "work-draft", "note": "", "bytes": len(text.encode("utf-8")), "sha256": None}
        claims = []
        for part in sentences(text):
            text_part = part.strip()
            if len(text_part) < 8 or re.match(r"^(#{1,6}\s|\||-{3,})", text_part):
                continue
            claims.append({"claim_id": "C%03d" % (len(claims) + 1), "text": text_part,
                           "core": trim_cites(text_part), "type": claim_kind(text_part),
                           "location": "work:%s %s" % (work_draft.get("path"), part[:20])})
        return claims, "revise", doc, "work-draft"
    claims, mode, draft_doc = make_claims(ctx["docs"], ctx["units"], ctx["case"], ctx["instr"])
    return claims, mode, draft_doc, "material"


def merge_work_evidence(rows, claims, work_draft, pool, pending, grads, docs=None):
    """Prefer agent-proposed evidence rows when their quote hits verbatim; flag misses."""
    supplied = work_draft.get("evidence") or []
    if not supplied:
        return rows, 0
    doc_map = {doc["doc_id"]: doc for doc in (docs or [])}
    targets = {claim["claim_id"] for claim in claims}
    grouped = {}
    for item in supplied:
        claim_id = item.get("claim_id")
        if claim_id not in targets:
            continue
        quote = item.get("quote")
        if quote and quote not in pool:
            pending.append({"id": "P%03d" % (len(pending) + 1), "issue": "工作稿引文未逐字命中",
                            "detail": "%s: %s" % (claim_id, quote[:80]), "needed": "回原文核对后重写 quote",
                            "source_id": item.get("source_id")})
            grads.append({"stage": "work-draft", "type": "quote_not_verbatim",
                          "detail": "%s 工作稿引文未命中，改用材料自动匹配结果" % claim_id})
            continue
        if not quote:
            continue
        source_id = item.get("source_id")
        source_doc = doc_map.get(source_id) or {}
        doc_text = source_doc.get("text") or pool
        level, why, basis = grade_row(quote, doc_text, 1, bool(item.get("conflicts")), abstract_only(source_doc) if source_doc else False)
        scope = item.get("support_scope") or ("直接支撑" if item.get("locator") else "部分支撑（范围不一致）")
        grouped.setdefault(claim_id, []).append({
            "claim_id": claim_id, "claim": "", "source_id": source_id,
            "source_path": source_doc.get("path"), "locator": item.get("locator"), "quote": quote,
            "source_type": basis["design"], "strength": item.get("strength") or level,
            "strength_basis": basis, "rationale": item.get("rationale"), "conflicts": item.get("conflicts") or [],
            "verified": True, "abstract_only": bool(source_doc.get("text")) and abstract_only(source_doc) if source_doc else False,
            "support_scope": scope,
        })
    merged, replaced = [], 0
    by_claim = {claim["claim_id"]: claim["core"] for claim in claims}
    for row in rows:
        if row["claim_id"] in grouped:
            if row["claim_id"] not in {item["claim_id"] for item in merged}:
                for item in grouped[row["claim_id"]]:
                    item["claim"] = by_claim.get(row["claim_id"], "")
                    merged.append(item)
                replaced += 1
            continue
        merged.append(row)
    return merged, replaced


# --------------------------------------------------------------------------- #
# claim cutting and evidence mapping (material-only fallback)
# --------------------------------------------------------------------------- #
def make_claims(docs, units, case, instr):
    """Cut claims: sentence-level from the draft, otherwise evidence-bearing material sentences."""
    claims = []
    drafts = [doc for doc in docs if doc["kind"] == "draft" and doc["text"].strip()]
    if drafts:
        source = drafts[0]
        for unit in units:
            text = unit["text"].strip()
            if unit["doc"] != source["doc_id"] or len(text) < 8:
                continue
            if re.match(r"^(\||-{3,}|\[\d+\]\s)", text):
                continue
            claims.append({ "claim_id": "C%03d" % (len(claims) + 1), "text": text, "core": trim_cites(text), "type": claim_kind(text), "location": "draft:%s %s" % (source["path"], unit["loc"]), "uid": unit["uid"], "doc": unit["doc"], })
        return claims, "revise", source

    topic = (instr + " " + json.dumps(case.get("source") or {}, ensure_ascii=False))[:6000]
    topic_tokens = bag_of(topic)
    ref_docs = {doc["doc_id"] for doc in docs if doc["kind"] == "references"}
    ranked = sorted( ((overlap(topic, unit["text"], topic_tokens) + (0.04 if re.search(r"\d", unit["text"]) else 0.0), unit) for unit in units if unit["doc"] not in ref_docs and len(unit["text"]) >= 20 and not re.match(r"^(参考文献|references?|doi|https?)", unit["text"], re.I)), key=lambda pair: -pair[0])
    length_hint = re.search(r"(\d{2,4})\s*(?:字|words?|词|characters?)", topic, re.I)
    target = max(3, min(12, int(round((int(length_hint.group(1)) if length_hint else 240) / 30.0))))
    picked, per_doc = [], {}
    for score, unit in ranked:
        if len(picked) >= target:
            break
        if per_doc.get(unit["doc"], 0) >= 2:
            continue
        if any(overlap(unit["text"], kept["text"]) > 0.8 for kept in picked):
            continue
        per_doc[unit["doc"]] = per_doc.get(unit["doc"], 0) + 1
        picked.append(unit)
    for unit in picked:
        claims.append({ "claim_id": "C%03d" % (len(claims) + 1), "text": unit["text"], "core": trim_cites(unit["text"]), "type": claim_kind(unit["text"]), "location": unit["loc"], "uid": unit["uid"], "doc": unit["doc"], })
    return claims, "synthesize", None


def map_evidence(claims, units, docs, refs):
    """Link each claim to verbatim source passages plus explicit conflicts."""
    doc_map = {doc["doc_id"]: doc for doc in docs}
    pool = [unit for unit in units if doc_map[unit["doc"]]["kind"] == "material"]
    ref_to_doc = {}
    for ref in refs:
        candidates = [ (1.0 if (ref["doi"] and ref["doi"] in doc["text"]) else overlap(ref["body"][:150], doc["text"][:400]), doc["doc_id"]) for doc in docs if doc["kind"] != "references"]
        candidates = [pair for pair in candidates if pair[0] >= 0.45]
        if candidates:
            ref_to_doc[ref["num"]] = max(candidates)[1]

    rows = []
    for claim in claims:
        claim_tokens = bag_of(claim["core"])
        anchored = {ref_to_doc[int(mark)] for mark in re.findall(r"[\[［](\d{1,3})[\]］]", claim["text"]) if int(mark) in ref_to_doc}
        scored = sorted(((overlap(claim["core"], unit["text"], claim_tokens), unit) for unit in pool), key=lambda pair: -pair[0])
        preferred = [unit for score, unit in scored if unit["doc"] in anchored]
        base = (1.0, preferred[0]) if preferred else (scored[0] if scored else (0.0, None))
        floor = 0.05 if preferred else 0.16
        if base[1] is None or base[0] < floor:
            rows.append({ "claim_id": claim["claim_id"], "claim": claim["core"], "source_id": None, "locator": None, "quote": None, "source_type": None, "strength": "不足", "strength_basis": {"reason": "无>=%.2f 重叠段落" % floor}, "support_scope": "无直接支撑", "conflicts": [], "verified": False, "rationale": "未匹配到来源，需补证或改写", })
            continue
        chosen = [base[1]]
        for score, unit in scored:
            if unit["uid"] in {item["uid"] for item in chosen}:
                continue
            same_doc = unit["doc"] in {item["doc"] for item in chosen}
            if (unit["doc"] in anchored or score >= max(floor, base[0] * 0.72)) and not same_doc:
                chosen.append(unit)
                if len(chosen) >= 3:
                    break
        conflicts = [{ "source_id": unit["doc"], "locator": unit["loc"], "quote": unit["text"], "similarity": round(score, 2), "why": "主题重叠但结论方向相反", } for score, unit in scored if score >= 0.40 and unit["uid"] not in {item["uid"] for item in chosen}
            and bool(NEG_HINT.search(unit["text"])) != bool(NEG_HINT.search(claim["core"]))
            and (POS_HINT.search(unit["text"]) or NEG_HINT.search(unit["text"]))]
        for unit in chosen:
            doc = doc_map[unit["doc"]]
            level, why, basis = grade_row(unit["text"], doc["text"], len(chosen), bool(conflicts), abstract_only(doc))
            score = overlap(claim["core"], unit["text"], claim_tokens)
            scope = "直接支撑" if score >= 0.3 else "部分支撑（范围不一致）"
            if basis["sample_size"]:
                scope += "；n~%d" % basis["sample_size"]
            if level in ("低", "不足"):
                scope += "；仅限该研究条件"
            rows.append({ "claim_id": claim["claim_id"], "claim": claim["core"], "source_id": unit["doc"], "source_path": doc["path"], "locator": unit["loc"], "quote": unit["text"], "source_type": basis["design"], "strength": level, "strength_basis": basis,
                "rationale": why + ("；冲突下调" if conflicts else ""), "conflicts": conflicts[:3],
                "verified": True, "abstract_only": abstract_only(doc), "support_scope": scope,
            })
    return rows


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def compose(docs, claims, rows, mode, draft_doc, case_id, lang, case, refs):
    """Render the draft: hedged claims, resolvable citation numbers, conflicts kept."""
    words = PHRASES[lang]
    doc_map = {doc["doc_id"]: doc for doc in docs}
    cites, change_log = {}, []
    rows_by_claim = {}
    for row in rows:
        rows_by_claim.setdefault(row["claim_id"], []).append(row)
    rank = {"不足": 0, "低": 1, "中": 2, "高": 3}

    def cite(ids):
        numbers = {cites.setdefault(src, len(cites) + 1) for src in ids}
        return "".join("[%d]" % n for n in sorted(numbers))

    def sourced(claim):
        return [row for row in rows_by_claim.get(claim["claim_id"], []) if row.get("quote")]

    def level_of(claim):
        backed = sourced(claim)
        return min((row["strength"] for row in backed), key=lambda lv: rank[lv]) if backed else "不足"

    for claim in claims:
        claim["_t"], downgrades = soften(claim["core"])
        for action, before, after, reason in downgrades:
            change_log.append({ "change_id": "CH%03d" % (len(change_log) + 1), "claim_id": claim["claim_id"], "action": action, "original_quote": before, "revised_quote": after, "reason": reason, "locator": claim["location"], "human_confirm": True, })

    def emit(claim):
        backed, level = sourced(claim), level_of(claim)
        body = re.sub(r"\s*(?:\[\d{1,3}\]|［\d{1,3}］|[。.；;])+\s*$", "", claim["_t"]).rstrip()
        if not backed:
            revised = re.sub(r"[。.]$", "", body) + words["uc"]
            change_log.append({ "change_id": "CH%03d" % (len(change_log) + 1), "claim_id": claim["claim_id"], "action": "mark_unverified", "original_quote": claim["core"], "revised_quote": revised, "reason": "未匹配到来源，改为待核表述并保留原判断", "locator": claim["location"], "human_confirm": True, })
            return revised
        if level in ("低", "不足") and not re.search(r"(可能|提示|初步|尚|may|suggest|prelim)", body, re.I):
            body = words["h"][level] + ("，" if lang == "zh" else " ") + body
        revised = body + cite(row["source_id"] for row in backed) + ("。" if lang == "zh" else ".")
        conflicts = [item for row in backed for item in (row.get("conflicts") or [])]
        if conflicts and " " not in revised[-3:]:
            revised += (" " + words["cf"] + re.sub(r"[。.]$", "", conflicts[0]["quote"][:150]) + cite(item["source_id"] for item in conflicts[:2]) + ("。" if lang == "zh" else "."))
        change_log.append({ "change_id": "CH%03d" % (len(change_log) + 1), "claim_id": claim["claim_id"], "action": "ground_and_hedge", "original_quote": claim["core"], "revised_quote": revised, "reason": "为实质判断补可回查引用编号，并按证据强度调整限定语气", "locator": claim["location"], "human_confirm": True, })
        return revised

    joiner = "" if lang == "zh" else " "
    lines = ["# " + words["t"].format(c=case_id), ""]
    source_meta = case.get("source")
    if isinstance(source_meta, dict) and any(source_meta.values()):
        lines += ["> " + "；".join("%s=%s" % (key, val) for key, val in source_meta.items() if val), ""]

    if mode == "revise" and draft_doc:
        by_text = {claim["text"]: claim for claim in claims}
        lines += ["<!-- 修订稿：保留原块结构；逐句补证、按强度调语气、过度推断已下调 -->", ""]
        for block in re.split(r"\n\s*\n", draft_doc["text"]):
            stripped = block.strip()
            if not stripped:
                continue
            if re.match(r"^#{1,6}\s", stripped):
                lines.append(stripped)
            else:
                lines.append(joiner.join(emit(by_text[sentence]) if sentence in by_text else sentence for sentence in sentences(stripped)))
            lines.append("")
    else:
        paragraph = []
        for claim in claims:
            paragraph.append(emit(claim))
            if len(paragraph) >= 3:
                lines += [joiner.join(paragraph), ""]
                paragraph = []
        if paragraph:
            lines += [joiner.join(paragraph), ""]

    boundary = words["lm"].split("|")
    weak = [claim["claim_id"] for claim in claims if not [row for row in rows_by_claim.get(claim["claim_id"], []) if row.get("strength") in ("高", "中")]]
    conflicted = sorted({row["claim_id"] for row in rows if row.get("conflicts")})
    lines += ["## " + words["lim"], ""]
    if weak:
        lines.append("- " + boundary[0] % "、".join(weak[:8]))
    if conflicted:
        lines.append("- " + boundary[1] % "、".join(conflicted))
    if any(row.get("abstract_only") for row in rows):
        lines.append("- " + boundary[2])
    lines += ["- " + boundary[3], "", "## " + words["ref"], "", "<!-- %s -->" % words["rt"]]
    for doc_id, number in sorted(cites.items(), key=lambda pair: pair[1]):
        lines += ["[%d] %s" % (number, ref_text(doc_map.get(doc_id, {}), refs, number, words)), ""]
    if refs:
        lines += ["## " + words["rs"], ""] + ["- " + ref["raw"] for ref in refs]
    for index, entry in enumerate(change_log, 1):
        entry["change_id"] = "CH%03d" % index
    return "\n".join(lines).rstrip() + "\n", change_log, cites


# --------------------------------------------------------------------------- #
# shared preparation
# --------------------------------------------------------------------------- #
def resolve_work(args, out):
    """Pick a writable work directory; fall back next to the output."""
    candidates = [getattr(args, "work", None), os.environ.get("SKILL_WORK"), "/app/work", str(Path(out).parent / "work")]
    for cand in candidates:
        if not cand:
            continue
        path = Path(cand)
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".probe"
            probe.write_text("x", "utf-8")
            probe.unlink()
            return path
        except Exception:
            continue
    path = Path.cwd() / "work"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return path


def prepare(args, log, cmd):
    """Discover input, write a partial result.json, index docs/units/refs."""
    started = time.time()
    errors, grads, pending, sources = [], [], [], []
    case, con, case_id, instr = {}, {}, "UNKNOWN", ""
    task_text = ""

    def flag(issue, detail, needed, source_id=None):
        pending.append({"id": "P%03d" % (len(pending) + 1), "issue": issue, "detail": detail, "needed": needed, "source_id": source_id})

    def safe(stage, worker, default):
        try:
            return worker()
        except Exception as exc:
            errors.append({"stage": stage, "type": type(exc).__name__, "detail": str(exc)[:200]})
            return default

    ind = next((Path(cand) for cand in ([args.input] if args.input else [])
                + [os.environ.get("SKILL_INPUT"), "/input", "input"]
                if cand and Path(cand).is_dir()), None)
    out = Path(args.output or os.environ.get("SKILL_OUTPUT") or "/app/output")
    try:
        out.mkdir(parents=True, exist_ok=True)
        probe = out / ".probe"
        probe.write_text("x", "utf-8")
        probe.unlink()
    except Exception:
        out = Path.cwd() / "output"
        out.mkdir(parents=True, exist_ok=True)
    work = resolve_work(args, out)

    def write_partial():
        payload = {"case_id": case_id, "status": "partial", "skill_version": VERSION, "sources": sources}
        for key in con:
            payload[key] = None if key in CONTRACT_FIELDS else con[key]
        for key in CONTRACT_FIELDS:
            payload.setdefault(key, [] if key != "deliverable" else None)
        payload["case_id"] = case_id
        dump_json(out / "result.json", payload)

    write_partial()
    log.add("startup", "partial result.json written; out=%s work=%s" % (out, work))
    if ind is None:
        errors.append({"stage": "input", "type": "no_input_dir", "detail": "无 input"})
        log.add("input", "no input directory found")
    else:
        log.add("input", "input=%s" % ind)
        for cand in [ind / "case.json"] + sorted(ind.glob("*case*.json")):
            if cand.is_file() and not case:
                case = safe("input", lambda: json.loads( cand.read_text(encoding="utf-8", errors="ignore")), {})
        if not case:
            errors.append({"stage": "input", "type": "no_case_json", "detail": "无 case"})
        if isinstance(case.get("output_contract"), dict):
            con = dict(case["output_contract"])
        case_id = str(case.get("case_id") or case.get("id") or "UNKNOWN")
        instr = " ".join(str(case.get(key) or "") for key in ("task_instruction", "task", "instruction", "prompt", "goal"))
        for task_name in ("task.md", "task.txt"):
            task_file = ind / task_name
            if task_file.is_file():
                task_text = task_file.read_text(encoding="utf-8", errors="ignore")
                instr += " " + task_text[:4000]
                break
    if not con:
        con = {key: None for key in CONTRACT_FIELDS}
        errors.append({"stage": "contract", "type": "missing_output_contract", "detail": "兜底 5 字段"})
    write_partial()
    log.add("case", "case_id=%s contract_keys=%d parse_errors=%d" % (case_id, len(con), len(errors)))

    docs = safe("discover", lambda: scan_inputs(ind, case) if ind else [], [])
    for doc in docs:
        sources.append({"source_id": doc["doc_id"], "path": doc["path"], "bytes": doc["bytes"], "sha256": doc["sha256"], "kind": doc["kind"], "read_method": doc["method"]})
        if doc["note"]:
            grads.append({"stage": "extract", "source_id": doc["doc_id"], "type": "extraction_partial", "detail": doc["note"]})
        if not doc["text"].strip():
            flag("无可抽文本", "%s(%s)" % (doc["path"], doc["method"]), "OCR 或人工转录", doc["doc_id"])
    if not docs:
        flag("无材料", "只有 case.json 或目录缺失", "确认 artifacts")
    units = safe("segment", lambda: units_of(docs), [])
    refs = safe("refs", lambda: ref_ent(docs), [])
    if not refs:
        flag("无文献表", "不能核对著录", "补文献表")
    lang = "zh" if len(re.findall(r"[\u4e00-\u9fff]", " ".join(doc["text"][:800] for doc in docs) + instr)) > 20 else "en"
    log.add("discover", "files=%d readable_texts=%d units=%d refs=%d lang=%s" % (
        len(docs), sum(1 for doc in docs if doc["text"].strip()), len(units), len(refs), lang))
    return {
        "started": started, "cmd": cmd, "input_dir": ind, "out": out, "work": work,
        "out_dir": str(out), "work_dir": str(work),
        "case": case, "contract": con, "case_id": case_id, "instr": instr, "task_text": task_text,
        "docs": docs, "units": units, "refs": refs, "lang": lang, "sources": sources,
        "errors": errors, "degradations": grads, "pending": pending,
        "partial_written": True, "log": log, "argv": sys.argv,
        "version": VERSION, "skill_name": "writing-03-grounded",
        "script_path": str(Path(__file__).resolve()),
    }


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def _output_dir(args):
    out = Path(args.output or os.environ.get("SKILL_OUTPUT") or "/app/output")
    try:
        out.mkdir(parents=True, exist_ok=True)
        probe = out / ".probe"
        probe.write_text("x", "utf-8")
        probe.unlink()
    except Exception:
        out = Path.cwd() / "output"
        try:
            out.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    return out


def _complete_outputs(out):
    required = ["result.json", "claims.json", "evidence_table.json", "evidence_driven_draft.md", "deliverable.md"]
    required += list(assetkit.ASSET_NAMES)
    for name in required:
        path = Path(out) / name
        if not path.is_file() or path.stat().st_size == 0:
            return False
    return True


def maybe_fallback(args, log):
    """If a one-command run left no complete deliverable, compose it from materials."""
    out = _output_dir(args)
    if _complete_outputs(out):
        return False
    sub = assetkit.RunLog(out, cmd="fallback-build", version=VERSION)
    log.add("fallback", "outputs incomplete -> compose complete deliverable from materials")
    try:
        cmd_build(args, sub, "fallback-build")
    except Exception as exc:
        log.add("fallback_error", "%s: %s" % (type(exc).__name__, str(exc)[:160]))
        try:
            assetkit.emergency(out, VERSION, "fallback build failed: %s" % type(exc).__name__)
        except Exception:
            pass
    return True


def write_index(ctx):
    materials = []
    for doc in ctx["docs"]:
        entry = {key: doc.get(key) for key in ("doc_id", "path", "kind", "bytes", "method", "note")}
        entry["chars"] = len(doc.get("text") or "")
        materials.append(entry)
    index = {
        "case_id": ctx["case_id"],
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "input_dir": str(ctx["input_dir"]) if ctx["input_dir"] else None,
        "contract_keys": list((ctx["contract"] or {}).keys()),
        "materials": materials,
        "unit_count": len(ctx["units"]),
        "reference_count": len(ctx["refs"]),
        "next": "用 show 打印带 locator 的原文；读完后把论断/逐字引文写进 /app/work/draft.json，再 check、build。",
    }
    dump_json(ctx["work"] / "index.json", index)
    return index


def cmd_init(ctx, args):
    index = write_index(ctx)
    print("== init v%s == case_id=%s contract=%s materials=%d units=%d refs=%d" % (
        VERSION, ctx["case_id"], ",".join(index["contract_keys"]) or "none",
        len(ctx["docs"]), len(ctx["units"]), len(ctx["refs"])))
    for doc in ctx["docs"]:
        print("  %-4s %-28s %-10s %6d chars  %s" % (doc["doc_id"], doc["path"], doc["kind"],
                                                    len(doc["text"] or ""), doc["method"]))
    print("NEXT: show -> read material -> write %s -> check -> build" % (ctx["work"] / "draft.json"))
    ctx["log"].add("init", "index written; units=%d materials=%d" % (len(ctx["units"]), len(ctx["docs"])))
    ctx["log"].flush()
    maybe_fallback(args, ctx["log"])
    ctx["log"].flush()
    return 0


def cmd_show(ctx, args):
    limit = int(getattr(args, "limit", 80) or 80)
    pattern = getattr(args, "grep", None)
    shown = 0
    for unit in ctx["units"]:
        if pattern and pattern not in unit["text"]:
            continue
        print("%-28s %s" % (unit["loc"], unit["text"][:300]))
        shown += 1
        if shown >= limit:
            break
    if shown == 0:
        print("(no unit matched; materials=%d units=%d)" % (len(ctx["docs"]), len(ctx["units"])))
    print("SHOWN %d/%d units; quote 时必须逐字复制上面的句子（含标点）" % (shown, len(ctx["units"])))
    ctx["log"].add("show", "shown=%d/%d grep=%s" % (shown, len(ctx["units"]), pattern))
    ctx["log"].flush()
    maybe_fallback(args, ctx["log"])
    ctx["log"].flush()
    return 0


def cmd_check(ctx, args):
    work_draft = load_work_draft(ctx["work"], ctx["case_id"])
    pool = "\n".join(doc["text"] for doc in ctx["docs"])
    report = {"case_id": ctx["case_id"], "work_draft": bool(work_draft.get("used")),
              "draft_path": work_draft.get("path"), "kind": work_draft.get("kind"),
              "claims": 0, "evidence": 0, "quote_hits": 0, "quote_misses": [], "missing_fields": [],
              "unsupported": [], "notes": work_draft.get("notes") or ""}
    if not work_draft.get("used"):
        report["next"] = "未发现工作稿；build 会从材料自动组合完整交付物（status=partial）。建议先 show 再写 draft.json。"
        print("CHECK no work draft at %s" % ctx["work"])
        print("NEXT: build 将从材料自动组合成稿（完整但 status=partial）；写工作稿可提高完成度。")
    else:
        claims = work_draft.get("claims") or []
        evidence = work_draft.get("evidence") or []
        report["claims"] = len(claims)
        report["evidence"] = len(evidence)
        quoted = [row for row in evidence if row.get("quote")]
        hits = [row for row in quoted if row["quote"] in pool]
        report["quote_hits"] = len(hits)
        report["quote_misses"] = ["%s: %s" % (row.get("claim_id"), (row.get("quote") or "")[:60])
                                  for row in quoted if row["quote"] not in pool]
        missing = [row.get("claim_id") for row in evidence
                   if not all(row.get(field) for field in ("source_id", "locator", "quote"))]
        report["missing_fields"] = missing
        supported = {row.get("claim_id") for row in hits}
        report["unsupported"] = [claim["claim_id"] for claim in claims if claim["claim_id"] not in supported]
        print("CHECK draft=%s claims=%d evidence=%d quote_hit=%d/%d missing_fields=%d unsupported=%d" % (
            work_draft.get("path"), len(claims), len(evidence), len(hits), len(quoted), len(missing), len(report["unsupported"])))
        if report["quote_misses"]:
            print("WARN 引文未逐字命中（build 会丢弃这些行并进 pending_human，不得改原文凑通过）：")
            for item in report["quote_misses"][:8]:
                print("  -", item)
        if claim_md := (work_draft.get("kind") == "md"):
            print("NOTE 工作稿是 Markdown 成稿；build 会把它当作修订稿逐句补证。")
        print("NEXT: build")
    dump_json(ctx["work"] / "check_report.json", report)
    ctx["log"].add("check", "draft=%s claims=%d evidence=%d quote_hit=%d/%d" % (
        report["draft_path"], report["claims"], report["evidence"], report["quote_hits"],
        report["quote_hits"] + len(report["quote_misses"])))
    ctx["log"].flush()
    maybe_fallback(args, ctx["log"])
    ctx["log"].flush()
    return 0


def cmd_audit(args, log):
    ind = args.input or os.environ.get("SKILL_INPUT") or "/input"
    out = _output_dir(args)
    maybe_fallback(args, log)
    try:
        report = audit_out(ind, out)
    except Exception as exc:
        print("verify degraded: %s: %s" % (type(exc).__name__, exc))
        report = {}
    missing = [name for name in assetkit.ASSET_NAMES if not (out / name).is_file() or (out / name).stat().st_size == 0]
    if missing:
        written = assetkit.emergency(out, VERSION, "audit 在 build 之前运行，缺少资产：%s" % ",".join(missing))
        print("assets restored as honest stubs:", ",".join(written) or "none")
    log.add("audit", "passed=%s missing_assets=%s" % (report.get("passed"), missing or "none"))
    log.flush()
    return 0


def cmd_build(args, log, cmd="build"):
    ctx = prepare(args, log, cmd)
    work_draft = load_work_draft(ctx["work"], ctx["case_id"])
    if work_draft.get("error"):
        ctx["degradations"].append({"stage": "work-draft", "type": "stale_or_unreadable_draft",
                                    "detail": str(work_draft.get("error"))[:200]})
    origin = "material"
    try:
        claims, mode, draft_doc, origin = choose_claims(ctx, work_draft)
    except Exception as exc:
        ctx["errors"].append({"stage": "claims", "type": type(exc).__name__, "detail": str(exc)[:200]})
        claims, mode, draft_doc, origin = [], "synthesize", None, "material"
    ctx["origin"] = origin
    ctx["work_draft"] = work_draft
    if not claims:
        ctx["pending"].append({"id": "P%03d" % (len(ctx["pending"]) + 1), "issue": "无论断", "detail": "文本过短", "needed": "提供正文/摘要", "source_id": None})
    log.add("claims", "origin=%s claims=%d mode=%s draft_path=%s" % (origin, len(claims), mode, work_draft.get("path")))
    rows = map_evidence(claims, ctx["units"], ctx["docs"], ctx["refs"])
    pool = "\n".join(doc["text"] for doc in ctx["docs"])
    rows, replaced = merge_work_evidence(rows, claims, work_draft, pool, ctx["pending"], ctx["degradations"], ctx["docs"])
    if replaced:
        log.add("evidence", "rows=%d work_draft_rows_used=%d" % (len(rows), replaced))
    else:
        log.add("evidence", "rows=%d" % len(rows))
    document, change_log, cites = compose(ctx["docs"], claims, rows, mode, draft_doc, ctx["case_id"],
                                          ctx["lang"], ctx["case"], ctx["refs"])
    for extra in (work_draft.get("change_log") or [])[:50]:
        if isinstance(extra, dict):
            change_log.append({
                "change_id": "CH%03d" % (len(change_log) + 1),
                "claim_id": str(extra.get("claim_id") or ""),
                "action": str(extra.get("action") or "agent_recorded"),
                "original_quote": extra.get("original_quote") or extra.get("before") or "",
                "revised_quote": extra.get("revised_quote") or extra.get("after") or "",
                "reason": str(extra.get("reason") or "Agent 工作稿记录的修改"),
                "locator": extra.get("locator") or "",
                "human_confirm": bool(extra.get("human_confirm", True)),
            })
    save_text(ctx["out"] / "evidence_driven_draft.md", document)
    save_text(ctx["out"] / "deliverable.md", document)
    log.add("compose", "draft_bytes=%d change_log=%d cites=%d" % (
        len(document.encode("utf-8")), len(change_log), len(cites)))

    for row in rows:
        if row.get("quote") and row["quote"] not in pool:
            row["verified"] = False
            ctx["degradations"].append({"stage": "verify", "source_id": row.get("source_id"), "type": "quote_not_verbatim", "detail": "%s 引文未逐字命中" % row["claim_id"]})
            ctx["pending"].append({"id": "P%03d" % (len(ctx["pending"]) + 1), "issue": "引文未命中", "detail": row["claim_id"], "needed": "回原文核对", "source_id": row.get("source_id")})
    unsupported = [claim["claim_id"] for claim in claims if not [row for row in rows if row["claim_id"] == claim["claim_id"] and row.get("source_id")]]
    for claim_id in unsupported:
        ctx["pending"].append({"id": "P%03d" % (len(ctx["pending"]) + 1), "issue": "论断无支撑", "detail": claim_id, "needed": "补证或删句", "source_id": None})

    facts = []
    for unit in ctx["units"]:
        for hit in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(%|‰|mg|g|kg|mL|L|μL|µm|nm|mm|cm|h|min|s|岁|例|名|倍|℃|" r"个月|年|周|天)", unit["text"]):
            facts.append({"fact_id": "F%03d" % (len(facts) + 1), "value": hit.group(0), "quote": unit["text"][:180], "locator": unit["loc"], "source_id": unit["doc"], "in_draft": hit.group(0) in document})
    facts = facts[:200]
    backed = [row for row in rows if row.get("source_id")]
    lvc = {}
    for row in rows:
        lvc[row["strength"]] = lvc.get(row["strength"], 0) + 1
    doc_body = re.split(r"\n#{1,6}\s*(?:参考文献|References)\s*\n", document, maxsplit=1, flags=re.I)[0]
    metrics = dict( claims_total=len(claims), claims_with_source=len(claims) - len(unsupported), claims_unsupported=len(unsupported), evidence_rows=len(rows), quotes_verified=sum(1 for row in backed if row.get("verified")), quotes_failed=sum(1 for row in backed if not row.get("verified")), strength_counts=lvc,
        claims_with_conflict=len({row["claim_id"] for row in rows if row.get("conflicts")}),
        overclaim_downgrades=len(change_log), distinct_sources_cited=len(cites),
        citation_markers=len(re.findall(r"\[\d+\]", doc_body)), preserved_facts=len(facts),
        pending_human=len(ctx["pending"]),
        support_rate=round((len(claims) - len(unsupported)) / len(claims), 3) if claims else 0.0,
        strength_label_rate=round(sum(1 for row in rows if row.get("strength")) / len(rows), 3) if rows else 0.0,
    )
    hedge_note = "高→“%s”；中→“%s”；低→“%s”；不足→“%s”" % tuple( PHRASES[ctx["lang"]]["h"][level] for level in ("高", "中", "低", "不足"))
    try:
        side_records(ctx["out"], rows, ctx["refs"], hedge_note)
    except Exception as exc:
        ctx["degradations"].append({"stage": "aux", "type": type(exc).__name__, "detail": "辅助记录失败"})
    dump_json(ctx["out"] / "claims.json", { "case_id": ctx["case_id"], "language": ctx["lang"], "count": len(claims), "claims": [{key: val for key, val in claim.items() if not key.startswith("_") and key != "uid"} for claim in claims]})
    dump_json(ctx["out"] / "evidence_table.json", { "case_id": ctx["case_id"], "count": len(rows), "schema": "claim_id,source_id,locator,quote,strength,support_scope,conflicts,rationale,verified", "rows": rows})
    dump_json(ctx["out"] / "pending_human.json", {"case_id": ctx["case_id"], "items": ctx["pending"]})

    status = ("input_error" if (not ctx["docs"] or not ctx["units"]) else "insufficient_evidence" if (not claims or not backed) else "partial" if (ctx["errors"] or unsupported or metrics["quotes_failed"]) else "ok")
    if origin != "work-draft" and status == "ok":
        status = "partial"
        ctx["degradations"].append({"stage": "work-draft", "type": "agent_work_absent",
                                    "detail": "未发现 /app/work 工作稿：已从材料自动组合完整交付物，status 记为 partial"})
    if time.time() - ctx["started"] > 780:
        ctx["degradations"].append({"stage": "budget", "type": "time_budget", "detail": "预算，提前 finalize"})
    evidence_map = [{ "claim_id": claim["claim_id"], "claim": claim.get("core") or claim.get("text"), "claim_type": claim.get("type"), "claim_location": claim.get("location"), "strength": min((row["strength"] for row in rows if row["claim_id"] == claim["claim_id"]), key=lambda lv: ["不足", "低", "中", "高"].index(lv), default="不足"),
        "evidence": [row for row in rows if row["claim_id"] == claim["claim_id"]],
        "unsupported": claim["claim_id"] in unsupported,
    } for claim in claims]
    uncertainty = ["著录与真实性未联网核验（离线），DOI/期刊/年份按材料转录"]
    if metrics["claims_with_conflict"]:
        uncertainty.append("冲突证据 %d 条，已在 conflicts 与成稿表述中保留" % metrics["claims_with_conflict"])
    if unsupported:
        uncertainty.append("未匹配来源：" + "、".join(unsupported[:6]))
    if any(row.get("abstract_only") for row in rows):
        uncertainty.append("含仅摘要可核来源，强度最高记中")
    if origin != "work-draft":
        uncertainty.append("未收到 Agent 工作稿：交付物由材料自动组合（完整但 status=partial）")

    integrity = { "claims_evidence_join": not ({row["claim_id"] for row in rows} - {claim["claim_id"] for claim in claims}), "quotes_all_verbatim": metrics["quotes_failed"] == 0, "citation_numbers_resolvable": (max((int(x) for x in re.findall(r"\[(\d{1,3})\]", document)), default=0) <= len(cites)) if cites else True, }
    asset_meta = assetkit.asset_paths(ctx["out"])
    result = { "case_id": ctx["case_id"], "status": status, "skill": "writing-03-grounded", "skill_version": VERSION, "deliverable": document, "deliverable_path": str(ctx["out"] / "evidence_driven_draft.md"), "preserved_facts": facts, "evidence_map": evidence_map, "change_log": change_log,
        "claims": {"path": str(ctx["out"] / "claims.json"), "count": len(claims)},
        "evidence_table": {"path": str(ctx["out"] / "evidence_table.json"), "count": len(rows)},
        "workorder_receipt": wo_checks(ctx["case"], document, cites),
        "sources": ctx["sources"], "metrics": metrics, "uncertainty": uncertainty,
        "pending_human": ctx["pending"], "errors": ctx["errors"], "degradations": ctx["degradations"],
        "changes": change_log, "integrity": integrity,
        "agent_work": {"draft_used": origin == "work-draft", "draft_path": work_draft.get("path"),
                       "kind": work_draft.get("kind"), "work_dir": str(ctx["work"])},
        "verifiable_assets": asset_meta,
        "golden_standard": asset_meta["golden_standard.json"], "diff_report": asset_meta["diff_report.md"],
        "version_history": asset_meta["version_history.md"], "run_log": asset_meta["run.log"],
        "self_check": asset_meta["self_check.json"],
        "runtime": {"script": "pipeline.py", "version": VERSION, "python": sys.version.split()[0], "seconds": round(time.time() - ctx["started"], 2), "argv": sys.argv[1:], "network": "disabled", "input_dir": str(ctx["input_dir"]), "output_dir": str(ctx["out"]), "work_dir": str(ctx["work"])},
    }
    merged = {}
    for key, val in (ctx["contract"] or {}).items():
        merged[key] = result[key] if key in CONTRACT_FIELDS else result.get(key, val)
    for key in CONTRACT_FIELDS:
        merged.setdefault(key, result[key])
    for key, val in result.items():
        merged.setdefault(key, val)
    merged.setdefault("integrity", {})
    merged["integrity"].update(integrity)
    merged["integrity"]["contract_backfilled"] = all(key in merged for key in (ctx["contract"] or {}))
    unfilled = [key for key in (ctx["contract"] or {}) if merged.get(key) in (None, "", [], {})]
    merged["contract_unfilled_keys"] = unfilled
    merged["verifiable_assets"] = asset_meta
    dump_json(ctx["out"] / "result.json", merged)
    log.add("result", "result.json written; status=%s contract=%d/%d" % (
        status, len([key for key in (ctx["contract"] or {}) if key in merged]), len(ctx["contract"] or {})))

    ctx["result"] = merged
    ctx["document"] = document
    ctx["rows"] = rows
    ctx["claims"] = claims
    ctx["change_log"] = change_log
    ctx["cites"] = cites
    ctx["metrics"] = metrics
    ctx["evidence_map"] = evidence_map
    ctx["facts"] = facts
    ctx["status"] = status
    log.add("assets_begin", "writing golden/diff/history/self_check/run.log")
    built = assetkit.build_assets(ctx, log)
    try:
        disk = json.loads((ctx["out"] / "result.json").read_text(encoding="utf-8"))
        disk["verifiable_assets"] = built
        for name, field in (("golden_standard.json", "golden_standard"), ("diff_report.md", "diff_report"),
                            ("version_history.md", "version_history"), ("run.log", "run_log"),
                            ("self_check.json", "self_check")):
            disk[field] = built.get(name)
        self_check = {}
        try:
            self_check = json.loads((ctx["out"] / "self_check.json").read_text(encoding="utf-8"))
        except Exception:
            self_check = {}
        disk["coverage"] = {
            "golden_items": len((assetkit._read_json(ctx["out"] / "golden_standard.json", {}) or {}).get("items") or []),
            "self_check_pass": self_check.get("pass"),
            "self_check_checks": ((self_check.get("summary") or {}).get("passed")),
            "diff": (self_check.get("counts") or {}).get("diff"),
        }
        dump_json(ctx["out"] / "result.json", disk)
    except Exception as exc:
        log.add("asset_error", "result asset fields: %s" % type(exc).__name__)
    try:
        print("done %s claims=%d rows=%d quote=%d/%d pending=%d assets=%d/5" % (
            status, len(claims), len(rows), metrics["quotes_verified"], len(backed), len(ctx["pending"]),
            sum(1 for name in assetkit.ASSET_NAMES if (ctx["out"] / name).is_file())))
    except Exception:
        pass
    return 0


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def crash_guard(output_path, work_path, exc):
    """Last-resort handler: a legal partial result.json still lands on disk."""
    try:
        out = Path(output_path)
        out.mkdir(parents=True, exist_ok=True)
        target = out / "result.json"
        current = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
        current["case_id"] = current.get("case_id") or "UNKNOWN"
        current["status"] = "partial"
        for key in ("preserved_facts", "evidence_map", "change_log", "sources", "errors", "pending_human", "changes"):
            current.setdefault(key, [])
        current.setdefault("deliverable", None)
        current.setdefault("uncertainty", ["未完成"])
        current["errors"] = current.get("errors", []) + [ {"stage": "fatal", "type": type(exc).__name__, "detail": str(exc)[:400]}]
        dump_json(target, current)
        assetkit.emergency(out, VERSION, "%s: %s" % (type(exc).__name__, str(exc)[:120]))
    except Exception:
        pass


def cli(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = "build"
    if argv and not argv[0].startswith("-") and argv[0] in COMMANDS:
        cmd = argv.pop(0)
    elif argv and not argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        print("unknown command %r; valid: %s" % (argv[0], ", ".join(COMMANDS)))
        return 0
    if cmd == "all":
        cmd = "build"
    parser = argparse.ArgumentParser( prog="pipeline.py", description="Evidence-grounded writing: claims -> evidence_table -> draft -> 5 verifiable assets; " "stdlib only, offline, partial result first, exit code always 0.", epilog="Commands: init / show / check / build (default) / audit. Input defaults to /input; output to /app/output; work to /app/work.")
    parser.add_argument("command", nargs="?", choices=COMMANDS, default=cmd, help=argparse.SUPPRESS)
    parser.add_argument("--input", default=None, help="input directory (default /input, env SKILL_INPUT)")
    parser.add_argument("--output", default=None, help="output directory (default /app/output, env SKILL_OUTPUT)")
    parser.add_argument("--work", default=None, help="work directory for draft/index (default /app/work, env SKILL_WORK)")
    parser.add_argument("--limit", type=int, default=80, help="show: max sentences to print")
    parser.add_argument("--grep", default=None, help="show: only print sentences containing this string")
    parser.add_argument("--version", action="version", version="writing-03 " + VERSION)
    parsed = parser.parse_args(argv)
    try:
        out = Path(parsed.output or os.environ.get("SKILL_OUTPUT") or "/app/output")
        log = assetkit.RunLog(out, cmd=parsed.command or cmd, version=VERSION)
    except Exception:
        log = assetkit.RunLog(Path.cwd() / "output", cmd=cmd, version=VERSION)
    try:
        if parsed.command == "init":
            ctx = prepare(parsed, log, "init")
            try:
                write_index(ctx)
            except Exception:
                pass
            return cmd_init(ctx, parsed)
        if parsed.command == "show":
            ctx = prepare(parsed, log, "show")
            try:
                write_index(ctx)
            except Exception:
                pass
            return cmd_show(ctx, parsed)
        if parsed.command == "check":
            ctx = prepare(parsed, log, "check")
            return cmd_check(ctx, parsed)
        if parsed.command == "audit":
            return cmd_audit(parsed, log)
        return cmd_build(parsed, log, parsed.command or "build")
    except Exception as exc:
        log.add("fatal", "%s: %s" % (type(exc).__name__, str(exc)[:200]))
        log.flush()
        crash_guard(parsed.output or os.environ.get("SKILL_OUTPUT") or "/app/output",
                    parsed.work or "/app/work", exc)
        import traceback
        traceback.print_exc()
        return 0


if __name__ == "__main__":
    sys.exit(cli())
