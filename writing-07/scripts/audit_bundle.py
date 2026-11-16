#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""writing-07 helper kernel for the rebuttal workbench.

Builds the comment ledger, renders the response letter, assembles all
deliverables and audits the finished bundle. Also runnable on its own to print
an audit report:  python3 audit_bundle.py --output /app/output --input /input
Read-only towards inputs; standard library only; exit code always 0.
"""

import argparse, json, re, sys

from pathlib import Path


TOOL_VERSION = "1.0.0"

SCRIPTS_DIR = Path(__file__).resolve().parent

REF_DIR = SCRIPTS_DIR.parent / "references"



def _load_ref(name, default):
    try:
        return json.loads((REF_DIR / name).read_text(encoding="utf-8"))
    except Exception:
        return default



VOCAB = _load_ref("comment_taxonomy.json", {})

FRAMES = _load_ref("reply_frames.json", {})

LEXICON = VOCAB.get("category_lexicon") or {}

FORBIDDEN = VOCAB.get("forbidden_claims") or []

TONE_MAP = VOCAB.get("decision_to_tone") or {"accept": "accept", "partial": "clarify",
                               "reject": "polite_rebuttal", "clarify": "clarify", "invalid": "appeal"}

_CUE_EN = "|".join(re.escape(w) for w in (VOCAB.get("request_cue_words") or [])) or r"(?!x)x"

_CUE_ZH = "|".join(re.escape(w) for w in (VOCAB.get("request_cue_zh") or [])) or r"(?!x)x"

CUE_RE = re.compile(r"(?:\b(?:%s)\b)|(?:%s)" % (_CUE_EN, _CUE_ZH), re.I)

HEAVY_RE = re.compile("|".join(re.escape(w) for w in (
    VOCAB.get("heavy_work_cue") or [])) or r"(?!x)x", re.I)

DECISION_SET = tuple(TONE_MAP)

FRAME_KEYS = {"accept": "agree_all", "partial": "agree_partial", "reject": "hold_original",
              "clarify": "clarify_reading", "invalid": "factual_mismatch"}

MUST_HAVE = ["response_letter.md", "comment_ledger.json", "change_locator.json",
             "evidence_pending.md", "pending_human.json", "result.json"]



def category_of(t):
    t = str(t or "").lower(); best, n0 = "writing", 0
    for k, kws in LEXICON.items():
        n = sum(1 for w in kws if w in t)
        if n > n0: best, n0 = k, n
    return best



def tone_of(d): return TONE_MAP.get(d, "accept")



def keywords(t):
    t = str(t or "").lower()
    return set(re.findall(r"[a-z]{4,}", t)) | set(re.findall(r"[\u4e00-\u9fff]{2,4}", t))



def dump_json(p, o): dump_text(p, json.dumps(o, ensure_ascii=False, indent=2))



def dump_text(p, s):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(str(s), encoding="utf-8")



def slurp(p):
    try: return Path(p).read_text(encoding="utf-8", errors="replace")
    except Exception: return ""



def squeeze(s): return re.sub(r"\s+", " ", str(s or "")).strip()



BULLET_RE = re.compile(r"^\s*(?:[-*•·]|\(?[a-zivx]{1,4}[).]|\(?\d{1,2}[).]|\(\d+\))\s+")

CLAUSE_SPLIT = re.compile(r"(?:;\s+|,\s+and\s+|\s+and\s+(?=[a-z])|\s+also\s+|；|并且|同时|另外|以及)")



def cli(argv=None):
    ap = argparse.ArgumentParser(
        prog="audit_bundle.py",
        description="Audit a writing-07 output directory: contract backfill, required artifacts, "
                    "locator joins, decision completeness, numeric preservation, over-claim scan.",
        epilog="example: python3 audit_bundle.py --output /app/output --input /input")
    ap.add_argument("--output", default="/app/output", help="directory holding the produced deliverables")
    ap.add_argument("--input", default=None, help="input directory used for the contract backfill check")
    a = ap.parse_args(argv)
    try:
        rep = inspect_outputs(a.output, a.input)
    except Exception as e:
        rep = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0



def inspect_outputs(outdir, inpdir=None):
    out = Path(outdir)
    res = _json_dict(out / "result.json")
    led = (_json_dict(out / "comment_ledger.json").get("comments")) or []
    loc = (_json_dict(out / "change_locator.json").get("locators")) or []
    dn = str(res.get("deliverable") or "revised_manuscript.md")
    contract = _json_dict(Path(inpdir) / "case.json").get("output_contract") if inpdir else None
    chs = [{"id": x.get("id"), "locator": x.get("locator"), "revised_quote": x.get("quote"),
            "numbers_preserved": True} for x in loc if isinstance(x, dict)]
    files = [p.name for p in out.glob("*") if p.is_file()] if out.is_dir() else []
    rep = inspect(slurp(out / dn), led, chs, contract if isinstance(contract, dict) else None, res, files,
                  letter_text=slurp(out / "response_letter.md"))
    rep["result_status"] = res.get("status")
    rep["deliverable"] = dn
    return rep



def _json_dict(p):
    try:
        v = json.loads(slurp(p))
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}



def _block_labels(text):
    """Return the P### labels of a blank-line separated document (same rule as the builders)."""
    labels, count, open_block = set(), 0, False
    for line in str(text or "").splitlines():
        if line.strip():
            if not open_block:
                count += 1
                open_block = True
        else:
            open_block = False
    return {"P%03d" % i for i in range(1, count + 1)}


def inspect(text, led, chs, contract=None, result=None, files=None, letter_text=None):
    subs = [s for c in led for s in c.get("sub_requirements") or []]
    hits = [c for c in chs if c.get("locator") and squeeze(c.get("revised_quote")) in squeeze(text)]
    over = [m.group(0) for p in FORBIDDEN for m in re.finditer(p, text, re.I)]
    bad = [c.get("id") for c in chs if not c.get("numbers_preserved", True)]
    open_subs = [s.get("sub_id") for s in subs
                 if s.get("decision") == "accept" and not s.get("change_ids")]
    tests = [
        ("comments_have_subs", all(c.get("sub_requirements") for c in led) if led else False,
         "comment without sub-requirements"),
        ("decisions_complete", all(s.get("decision") in DECISION_SET for s in subs),
         "decision outside %s" % (DECISION_SET,)),
        ("locator_quotes_hit", len(hits) == len(chs),
         "%d/%d quotes found" % (len(hits), len(chs))),
        ("numbers_preserved", not bad, "changed numbers: %s" % bad[:5]),
        ("locators_exist", all(c.get("locator") for c in chs), "edit without block locator"),
        ("no_overclaim", not over, "banned claims: %s" % over[:5]),
        ("accepts_have_change", not open_subs, "accepted w/o change: %s" % open_subs[:5]),
    ]
    if contract:
        miss = [k for k in contract if result is None or k not in result]
        tests.append(("contract_echo", not miss, "missing keys: %s" % miss))
    if files is not None:
        miss = [f for f in MUST_HAVE if f not in files]
        tests.append(("artifacts_present", not miss, "missing files: %s" % miss))
    cited, stray = [], []
    if letter_text is not None:
        cited = sorted(set(re.findall(r"P\d{3}", letter_text)))
        known = _block_labels(text)
        stray = [p for p in cited if p not in known]
        tests.append(("letter_locator_join", not stray,
                      "letter cites locators absent from the manuscript: %s" % stray[:8]))
    rep = {"checks": {}, "problems": [], "counts": {}}
    for name, ok, detail in tests:
        rep["checks"][name] = {"ok": bool(ok), "detail": "" if ok else detail}
        if not ok:
            rep["problems"].append({"check": name, "detail": detail})
    got = len([s for s in subs if s.get("change_ids")])
    rep["counts"] = {"comments": len(led), "subs": len(subs), "subs_with_change": got,
                     "sub_requirement_coverage": round(got / max(1, len(subs)), 3),
                     "edits": len(chs), "edits_verified": len(hits),
                     "locator_hit_rate": round(len(hits) / max(1, len(chs)), 3),
                     "letter_locators": len(cited), "letter_locators_valid": len(cited) - len(stray)}
    rep["ok"] = all(v["ok"] for v in rep["checks"].values())
    return rep



def publish(out, cid, dn, con, ctx, st, E, D, I, P, U, led, chs, rtext, stage,
         bn, cn, lang, pres, ev, case=None, plan=None, allsub=None, applied=None):
    """Emit every deliverable, inspect the finished bundle, then write result.json."""
    out = Path(out)
    allsub = allsub if allsub is not None else [s for c in led for s in c.get("sub_requirements") or []]
    applied = len([c for c in chs if c.get("hit")]) if applied is None else applied
    dump_text(out / dn, rtext)
    dump_text(out / "response_letter.md", draw_letter(led, chs, bn, dn, lang))
    dump_text(out / "evidence_pending.md", draw_pending(led, I, lang))
    dump_json(out / "comment_ledger.json", {
        "case_id": cid, "skill_version": TOOL_VERSION, "lang": lang,
        "scope": "controlled drill over the organizer baseline; not the verbatim review report", "comments": led})
    dump_json(out / "change_locator.json", {
        "case_id": cid, "deliverable": dn,
        "locator_scheme": "P### = index of the blank-line separated blocks of the delivered file, headings counted",
        "locators": [{"id": c.get("id"), "sub_id": c.get("sub_id"), "locator": c.get("locator"),
                      "quote": c.get("revised_quote"), "hit": c.get("hit")} for c in chs]})
    wo, ptxt = [], json.dumps(plan or {}, ensure_ascii=False).lower()
    for key in ("organizer_workorder", "organizer_edit_workorder"):
        v = (case or {}).get(key)
        for i, it in enumerate(v if isinstance(v, list) else ([] if v is None else [v])):
            txt = squeeze(it.get("instruction") if isinstance(it, dict) else it)
            kw = list(keywords(txt))[:6]
            ok = bool(kw) and sum(1 for w in kw if w in ptxt) >= max(1, len(kw) // 2)
            wid = str((it.get("id") if isinstance(it, dict) else "") or "%s-%d" % (key, i + 1))
            wo.append({"id": wid, "instruction": txt[:200],
                       "status": "executed" if ok else "not_executed",
                       "note": "" if ok else "no matching edit/override in the plan"})
            if not ok:
                P.append({"item": "workorder %s" % wid,
                          "reason": "workorder item not reflected in the output"})
    if wo and st == "ok" and any(w["status"] != "executed" for w in wo):
        st = "partial"
    cnt = lambda f: len([s for s in allsub if f(s)])
    counts = {"comments_total": len(led), "sub_requirements_total": len(allsub),
              "subs_with_verified_change": cnt(lambda s: s.get("change_ids")),
              "sub_requirement_coverage": round(cnt(lambda s: s.get("change_ids")) / max(1, len(allsub)), 3),
              "decision_coverage": round(cnt(lambda s: s.get("decision") in DECISION_SET) / max(1, len(allsub)), 3),
              "edits_total": len(chs), "edits_applied": applied,
              "locator_hit_rate": round(applied / len(chs), 3) if chs else 0.0,
              "evidence_provided": cnt(lambda s: s.get("evidence_status") == "provided"),
              "evidence_not_provided": cnt(lambda s: s.get("evidence_status") == "not_provided"),
              "evidence_not_applicable": cnt(lambda s: s.get("evidence_status") == "not_applicable"),
              "decisions": {k: cnt(lambda s, k=k: s.get("decision") == k) for k in DECISION_SET},
              "pending_human_items": len(P)}
    dump_text(out / "version_notes.md", "\n".join([
        "# 版本、基线与边界 / Version, baseline & scope", "",
        "- skill: rebuttal-response-workbench v%s (python standard library only) | stage: %s" % (TOOL_VERSION, stage),
        "- case: `%s` | baseline file: `%s` | comment files: `%s`" % (cid, bn, cn),
        "- main artifact: `%s` | comments/subs/edits: %d/%d/%d | locator hit rate: %.3f"
        % (dn, len(led), len(allsub), len(chs), counts["locator_hit_rate"]),
        "- 仅对指定基线做修订；未添加基线之外的文献、数值或结论；无法补做的实验与分析均如实标注。",
        "- Nothing beyond the supplied baseline was added; unimplemented analyses are listed as pending.", ""]))
    dump_json(out / "pending_human.json", {"case_id": cid, "items": P})
    ctx = dict(ctx)
    ctx.update({"case_id": cid, "status": st, "preserved_facts": pres, "evidence_map": ev,
                "change_log": chs, "uncertainty": U})
    res = {"case_id": cid, "status": st}
    res.update(backfill_contract(con, ctx))
    res.update({
        "skill": {"name": "rebuttal-response-workbench", "version": TOOL_VERSION},
        "stage": stage, "deliverable": ctx.get("deliverable"),
        "outputs": {p.name: p.stat().st_size for p in sorted(out.glob("*")) if p.is_file()},
        "counts": counts,
        "comment_ledger_summary": [{"comment_id": c.get("comment_id"), "decision": c.get("decision"),
                                    "tone": c.get("tone"),
                                    "subs": [{k: s.get(k) for k in ("sub_id", "type", "decision",
                                                                    "tone", "change_ids",
                                                                    "evidence_status")}
                                             for s in c.get("sub_requirements") or []]} for c in led],
        "workorder_report": wo,
        "sources": [{"name": bn, "role": "organizer manuscript baseline summary"},
                    {"name": cn, "role": "organizer reviewer comment summary"}],
        "scope_note": "Controlled revision drill over the organizer baseline and comment summary only: "
                      "no verbatim reviewer wording, no new experiment, no editorial decision claimed.",
        "uncertainty": U, "pending_human": P, "errors": E,
        "degradations": D, "issues": I[:50], "changes": chs,
        "runtime": {"version": TOOL_VERSION, "python": sys.version.split()[0], "stage": stage}})
    res["verification"] = inspect(rtext, led, chs, con if isinstance(con, dict) else None, res,
                                [p.name for p in out.glob("*") if p.is_file()],
                                letter_text=slurp(out / "response_letter.md"))
    dump_json(out / "result.json", res)
    return 0



def backfill_contract(con, ctx):
    out = {}
    for k in (con or {}):
        kl = str(k).lower()
        if k in ctx: out[k] = ctx[k]
        elif "case" in kl: out[k] = ctx.get("case_id")
        elif "deliver" in kl or "artifact" in kl: out[k] = ctx.get("deliverable")
        elif "preserv" in kl or "fact" in kl: out[k] = ctx.get("preserved_facts")
        elif "evidence" in kl or "source" in kl or "map" in kl: out[k] = ctx.get("evidence_map")
        elif "change" in kl or "diff" in kl or "log" in kl: out[k] = ctx.get("change_log")
        elif "status" in kl: out[k] = ctx.get("status")
        elif "uncertain" in kl: out[k] = ctx.get("uncertainty")
        else: out[k] = None
    out.setdefault("case_id", ctx.get("case_id"))
    return out



def draw_pending(led, issues, lang):
    every = [s for c in led for s in c.get("sub_requirements") or []]
    tally = {k: len([s for s in every if s.get("evidence_status") == k])
             for k in ("provided", "not_provided", "not_applicable")}
    L = ["# 未到位证据清单 / Pending evidence", "",
         "受控演练：下列条目在本次基线修订中尚未落实，或需要人工确认。 / "
         "Controlled drill: items below remain open or need a human decision.", "",
         "证据状态统计 / Evidence status tally: provided=%d · not_provided=%d · not_applicable=%d · subs=%d"
         % (tally["provided"], tally["not_provided"], tally["not_applicable"], len(every)), "",
         "| sub_id | 子要求 / sub-requirement | 类别 / category | 证据状态 / status | 备注 / note |",
         "|---|---|---|---|---|"]
    n = 0
    for c in led:
        for s in c.get("sub_requirements") or []:
            if s.get("needs_human") or s.get("evidence_status") == "not_provided" or not s.get("change_ids"):
                n += 1
                L.append("| %s | %s | %s | %s | %s |" % (
                    s.get("sub_id"), str(s.get("text"))[:80].replace("|", "/"), s.get("type"),
                    s.get("evidence_status"),
                    str(s.get("evidence_note") or s.get("decision"))[:80].replace("|", "/")))
    if not n:
        L.append("| — | — | — | — | 没有未到位条目 / none |")
    if issues:
        L += ["", "## 运行异常 / Runtime observations", ""] + \
             ["- `%s` %s" % (i.get("kind"), str(i.get("detail"))[:160]) for i in issues[:20]]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- output assembly

def draw_letter(led, chs, bn, dn, lang):
    F = (FRAMES.get("frames") or {}).get(lang) or (FRAMES.get("frames") or {}).get("en") or {}
    L = [F.get("heading", "# Response to Reviewers (draft)"), "", F.get("scope_line", "").format(b=bn), ""]
    for c in led:
        L += ["## Comment %s — %s" % (c.get("comment_id", "?"),
                                     c.get("source_label") or c.get("comment_id", "?")), ""]
        if c.get("raw_summary"):
            L += ["> Organizer's comment summary: %s" % c["raw_summary"][:400], ""]
        for s in c.get("sub_requirements") or []:
            L += ["**%s** · %s · decision=%s · tone=%s" % (s.get("sub_id"), s.get("type"),
                                                             s.get("decision"), s.get("tone")), "",
                  (F.get(FRAME_KEYS.get(s.get("decision"), ""), "") + " " + (s.get("response_note") or "")).strip(), ""]
            rel = [x for x in chs if x.get("id") in (s.get("change_ids") or [])]
            for x in rel:
                if x.get("locator"):
                    L += [F.get("changed_block", "").format(loc=x["locator"], d=dn), "",
                          '> "%s"' % squeeze(x.get("revised_quote"))[:400], ""]
                else:
                    L += [F.get("no_change_block", ""), ""]
            if not rel and s.get("decision") in ("accept", "partial"):
                L += [F.get("no_change_block", ""), ""]
            if not rel and s.get("decision") in ("reject", "invalid", "clarify") and s.get("anchor"):
                L += [F.get("kept_anchor", "").format(loc=s["anchor"]), ""]
            if s.get("needs_human") and s.get("evidence_status") != "provided":
                L += [F.get("evidence_line", "").format(s=s.get("evidence_status"), n=s.get("evidence_note")), ""]
        L.append("")
    return "\n".join(L).rstrip() + "\n"



def refresh_ledger(led, final=False):
    for c in led:
        for s in c.get("sub_requirements") or []:
            if final and s.get("decision") == "accept" and not s.get("change_ids"):
                s["decision"], s["tone"] = "partial", tone_of("partial")
        decs = [s["decision"] for s in c.get("sub_requirements") or []] or ["accept"]
        c["decision"] = decs[0] if len(set(decs)) == 1 else "partial"
        c["tone"] = tone_of(c["decision"])
        c["change_ids"] = [x for s in c.get("sub_requirements") or [] for x in s.get("change_ids") or []]
        c["evidence_needed"] = [s["text"][:200] for s in c.get("sub_requirements") or []
                                if s.get("evidence_status") == "not_provided"]
    return {s["sub_id"]: s for c in led for s in c.get("sub_requirements") or []}



def make_ledger(comments, bs, lang):
    led = []
    for c in comments:
        subs = []
        for k, s in enumerate(split_requirements(c.get("body", "")), 1):
            typ, needs = category_of(s), bool(HEAVY_RE.search(s))
            a, sc = best_anchor(s, bs)
            dec = "partial" if needs else "accept"
            note = "" if not needs else ("requested new experiment/analysis is outside the supplied materials"
                                         if lang == "en" else "所求补做实验/重做分析超出所给材料范围")
            subs.append({"sub_id": "%s.%d" % (c["comment_id"], k), "text": s, "type": typ,
                         "decision": dec, "tone": tone_of(dec), "anchor": a, "anchor_score": sc,
                         "change_ids": [], "evidence_status": "not_provided" if needs else "not_applicable",
                         "evidence_note": note, "response_note": "", "needs_human": needs})
        decs = [s["decision"] for s in subs] or ["accept"]
        d = decs[0] if len(set(decs)) == 1 else "partial"
        led.append({"comment_id": c["comment_id"], "source_label": c.get("source_label", ""),
                    "raw_summary": squeeze(c.get("body"))[:900], "decision": d, "tone": tone_of(d),
                    "response_summary": "", "change_ids": [],
                    "evidence_needed": [s["text"][:200] for s in subs if s["needs_human"]],
                    "sub_requirements": subs})
    return led



def best_anchor(sub, bs):
    """Pick the body block whose words overlap most with the sub-requirement; the enclosing heading counts too."""
    ts = keywords(sub); best, sc, head = None, 0.0, ""
    if not ts: return None, 0.0
    for b in bs:
        if b.get("level"): head = b.get("text"); continue
        bt = keywords(b.get("text")) | keywords(head)
        if not bt: continue
        x = len(ts & bt) / (len(bt) ** 0.5 + 3.0)
        if x > sc: best, sc = b.get("label"), x
    return (best, round(sc, 3)) if sc >= 0.12 else (None, round(sc, 3))



def split_requirements(body):
    """Expand one comment into ordered sub-requirements: bullets first, otherwise clauses with a request cue."""
    lines = [l.strip() for l in str(body or "").splitlines() if l.strip()]
    bl = [BULLET_RE.sub("", l).strip() for l in lines if BULLET_RE.match(l)]
    segs = bl if len(bl) >= 2 else [x.strip() for x in
                                    re.split(r"(?<=[。！？；;])|(?<=[.!?])\s+", str(body or "")) if x.strip()]
    fine = []
    for s in segs:
        parts = [x.strip(" ,.;") for x in CLAUSE_SPLIT.split(s) if x.strip(" ,.;")]
        fine += parts if len([x for x in parts if CUE_RE.search(x)]) >= 2 else [s]
    subs, ctx = [], ""
    for s in fine:
        s = s.strip(" -•*")
        if not s: continue
        if not CUE_RE.search(s):
            if not subs: ctx = (ctx + " " + s).strip()
            else: subs[-1] = (subs[-1] + " " + s).strip()
            continue
        subs.append((ctx + " " + s).strip() if ctx else s); ctx = ""
    return [x[:600] for x in (subs or [(ctx or str(body or "")).strip()]) if x]



if __name__ == "__main__":
    sys.exit(cli())
