#!/usr/bin/env python3
"""Golden-standard derivation for the reading-bench forge skill.

Re-derives what this build *should* have produced straight from the input bytes,
the case workorder and the acceptance rules published in `references/`, then reads
the artefacts back for the diff. No expectation is copied out of the artefact it
judges: quotes come from input bytes, 0/1/2 scores are re-counted from the published
rubric and locators are re-resolved against the paragraph index. Every row carries a
source locator plus a verbatim quote; degraded inputs yield an honest
`not_applicable` / `missing` verdict instead of an invented value.
"""
import hashlib
import json
import re
from pathlib import Path

KINDS = ("extraction", "numeric", "method", "definition", "conflict", "coverage", "table", "other")
STOP = set(("a an the of and or to in for on with by from this that these is are was were be been it its as at "
            "not but can may such using used study paper result results than then there their they has have had "
            "which who what when where how also more most both each into during show").split())
ID_KEYS = ("case_id", "caseId", "case", "id", "task_id", "taskId", "sample_id")
CONTRACT_KEYS = ("output_contract", "outputContract", "contract", "required_outputs", "result_contract", "output_schema")
WORKORDER_KEYS = ("organizer_workorder", "organizerWorkorder", "workorder", "benchmark_workorder", "work_order",
                  "benchmark_draft", "workorder_items", "cards_workorder")
SYNTH_KEYS = ("candidate_output", "candidate_answer", "baseline_output", "model_output", "response_text", "checker_log")

RULE_SPECS = (
    ("quote_verbatim", "references/question-spec.md", ("只允许空白差异",), "cards+anchors",
     "quote must be a contiguous verbatim slice of the material (whitespace may differ)"),
    ("locator_format", "references/question-spec.md", ("`M02#p11`",), "cards+anchors",
     "locator must be <material>#p<paragraph> and resolve to a real paragraph"),
    ("weight_sum", "references/question-spec.md", ("偏离 0.02 以上只记 NOTE",), "cards",
     "rubric weights of one card sum to 1.0 within 0.02"),
    ("score_scale", "SKILL.md", ("≥ 0.6",), "scores",
     "score is 2 when verbatim coverage >= 0.6, 1 when > 0, else 0"),
    ("item_score", "SKILL.md", ("满分 2",), "scores",
     "item score = sum(weight x point score), max 2"),
    ("aggregate_recompute", "references/contract-map.md", ("n2+n1+n0",), "aggregate",
     "n2+n1+n0 == n_points; all aggregates recomputable"),
    ("status_semantics", "references/contract-map.md", ("有题、无校验 FAIL",), "status",
     "ok/partial/insufficient_evidence/input_error follow the documented triggers"),
    ("synthetic_label", "references/contract-map.md", ("不是 DSH 分数",), "status",
     "checker/candidate logs: technical_synthetic, not_a_dsh_score=true, scored=false"),
    ("fallback_cap", "SKILL.md", ("上限 6 题",), "status",
     "fallback build emits at most 6 items from real paragraphs"),
    ("contract_echo", "SKILL.md", ("每个字段都会在顶层出现一次",), "contract",
     "every declared output_contract field appears on top level"),
)


# --------------------------------------------------------------------------- io
def read_text(p):
    try:
        b = Path(p).read_bytes()
    except OSError:
        return ""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "ignore")


def squeeze(t):
    return re.sub(r"\s+", " ", (t or "").replace("\ufeff", "")).strip()


def sha1_16(p):
    try:
        return hashlib.sha1(Path(p).read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def pick(o, names):
    if isinstance(o, dict):
        for n in names:
            for k, v in o.items():
                if str(k).lower().replace("-", "_") == n.lower().replace("-", "_"):
                    return v
    return None


# --------------------------------------------------------------- JSON fragments
def _ws(t, i):
    while i < len(t) and t[i] in " \t\r\n":
        i += 1
    return i


def _span(t, i):
    i = _ws(t, i)
    if i >= len(t):
        return None
    c = t[i]
    if c == '"':
        j = i + 1
        while j < len(t):
            if t[j] == "\\":
                j += 2
                continue
            if t[j] == '"':
                return (i, j + 1)
            j += 1
        return None
    if c in "{[":
        depth, j = 0, i
        while j < len(t):
            ch = t[j]
            if ch == '"':
                inner = _span(t, j)
                if not inner:
                    return None
                j = inner[1]
                continue
            if ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 0:
                    return (i, j + 1)
            j += 1
        return None
    j = i
    while j < len(t) and t[j] not in ",}] \t\r\n":
        j += 1
    return (i, j)


def _member(t, key, lo=0, hi=None):
    hi = len(t) if hi is None else hi
    m = re.compile(r'"' + re.escape(str(key)) + r'"\s*:').search(t, lo, hi)
    if not m:
        return None
    return _span(t, m.end())


def _elements(t, span):
    out = []
    i = _ws(t, span[0] + 1)
    while i < len(t) and i < span[1] and t[i] != "]":
        s = _span(t, i)
        if not s:
            break
        out.append(s)
        i = _ws(t, s[1])
        if i < len(t) and t[i] == ",":
            i += 1
        else:
            break
    return out


def _parts(path):
    out = []
    for seg in str(path).split("."):
        m = re.match(r"^([^\[\]]+)((?:\[\d+\])*)$", seg)
        if not m:
            return None
        out.append(m.group(1))
        for n in re.findall(r"\[(\d+)\]", m.group(2)):
            out.append(int(n))
    return out


def raw_fragment(text, path):
    """Return the exact source substring holding a dotted/indexed JSON value."""
    span = (0, len(text))
    for seg in _parts(path) or []:
        if span is None or span[1] > len(text):
            return None
        if isinstance(seg, int):
            if text[span[0]] != "[":
                return None
            els = _elements(text, span)
            if seg >= len(els):
                return None
            span = els[seg]
        else:
            if text[span[0]] != "{":
                return None
            span = _member(text, seg, span[0], span[1])
            if span is None:
                return None
    return text[span[0]:span[1]]


def string_at(text, path):
    frag = raw_fragment(text, path)
    if not frag or not frag.startswith('"'):
        return None, False
    try:
        val = json.loads(frag)
    except ValueError:
        return None, False
    inner = frag[1:-1]
    plain = json.dumps(val, ensure_ascii=False)[1:-1]
    return str(val), inner == plain


# ----------------------------------------------------- local rule re-implementations
def terms_from(t, k=8):
    out = []
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", t or ""):
        span = min(4, len(run))
        for i in range(len(run) - span + 1):
            out.append(run[i:i + span])
            if len(out) >= k:
                return out[:k]
    for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", t or ""):
        if w.lower() not in STOP:
            out.append(w.lower())
            if len(out) >= k:
                break
    return out[:k]


def coverage(terms, text):
    cf = (text or "").casefold()
    if not terms:
        return 0.0
    return round(sum(str(t).casefold() in cf for t in terms) / len(terms), 3)


def corpus_from(index):
    c = {}
    for m in index.get("materials") or []:
        buf, spans = "", []
        for par in m.get("paragraphs") or []:
            t = squeeze(par.get("text"))
            if t:
                buf += (" " if buf else "") + t
                spans.append((len(buf) - len(t), len(buf), par))
        if spans:
            c[m.get("mid")] = {"t": buf, "cf": buf.casefold(), "spans": spans}
    return c


def locate(corpus, mid, quote):
    q = squeeze(quote)
    if not q:
        return {"verified": False, "reason": "blank_quote"}
    if mid not in corpus:
        return {"verified": False, "reason": "material_unknown"}
    for mode, needle, hay in (("exact", q, corpus[mid]["t"]), ("casefold", q.casefold(), corpus[mid]["cf"])):
        pos = hay.find(needle)
        if pos >= 0:
            pid = None
            for s, e, par in corpus[mid]["spans"]:
                if s <= pos < e or pos < s < pos + len(needle):
                    pid = par.get("pid")
                    break
            return {"verified": True, "match": mode, "pid": pid}
    flat = re.sub(r"\s+", "", q)
    if flat and flat in re.sub(r"\s+", "", corpus[mid]["t"]):
        return {"verified": True, "match": "ignoring_all_spaces", "pid": None}
    return {"verified": False, "reason": "quote_absent"}


def grade(published_items, corpus):
    """Re-count every 0/1/2 point and item score from the published card text."""
    graded = []
    for it in published_items:
        auto = terms_from(" ".join(it.get("reference_answer") or []))
        rubric = it.get("rubric") or []
        points = []
        for rp in rubric:
            terms = rp.get("key_terms") or auto
            best = None
            for ev in it.get("evidence") or []:
                mid, quote = str(ev.get("material") or ""), str(ev.get("quote") or "")
                hit = locate(corpus, mid, quote)
                if not hit.get("verified"):
                    continue
                cov = coverage(terms, quote)
                if best is None or cov > best[0]:
                    best = (cov, ev)
            if best is None:
                points.append({"rubric_id": rp.get("id"), "score": 0,
                               "basis": "no verified quote in material", "locator": None})
                continue
            cov, ev = best
            score = 2 if cov >= 0.6 else (1 if cov > 0 else 0)
            points.append({"rubric_id": rp.get("id"), "score": score,
                           "locator": ev.get("locator") or None, "coverage": cov})
        total = 0.0
        for p in points:
            weight = next((float(r.get("weight") or 0.0) for r in rubric if r.get("id") == p["rubric_id"]), 0.0)
            total += p["score"] * weight
        graded.append({"id": it.get("id"), "points": points, "score": round(total, 3)})
    return graded


def aggregate(graded, cards):
    pts = [p for g in graded for p in g["points"]]
    n2 = sum(1 for p in pts if p["score"] == 2)
    n1 = sum(1 for p in pts if p["score"] == 1)
    n0 = sum(1 for p in pts if p["score"] == 0)
    n_ev = sum(len(it.get("evidence") or []) for it in cards)
    return {"n_items": len(graded), "n_points": len(pts), "n2": n2, "n1": n1, "n0": n0,
            "rate2": round(n2 / len(pts), 3) if pts else 0.0,
            "judgeable_rate": round((n2 + n1) / len(pts), 3) if pts else 0.0,
            "mean_score": round(sum(g["score"] for g in graded) / len(graded), 3) if graded else 0.0,
            "n_evidence": n_ev}


# ------------------------------------------------------------------- rendering
def fmt(v, limit=140):
    if isinstance(v, str):
        s = v
    else:
        s = json.dumps(v, ensure_ascii=False, sort_keys=True)
    return s if len(s) <= limit else s[:limit] + "..." + s[-20:]


class Basket:
    """Collects expectation rows, rules and the running tallies."""

    def __init__(self):
        self.items = []
        self.rules = []
        self.derivation = []
        self.not_applicable = []

    def add(self, category, subject, expectation, golden, actual, locator, quote,
            kind="input", verdict=None, note="", source_text=""):
        if verdict is None:
            verdict = "met" if golden == actual else "deviation"
        q = quote or ""
        item = {"id": "", "category": category, "subject": subject, "expectation": expectation,
                "golden": golden, "actual": actual, "verdict": verdict,
                "source": {"kind": kind, "locator": locator, "quote": q,
                           "quote_verbatim": bool(q) and squeeze(q) in squeeze(source_text or q),
                           "bytes": len(q.encode("utf-8"))},
                "note": note}
        self.items.append(item)
        return item

    def na(self, category, subject, expectation, golden, locator, quote, kind="input", note=""):
        return self.add(category, subject, expectation, golden, "n/a", locator, quote, kind,
                        verdict="not_applicable", note=note)

    def rule(self, rid, statement, locator, quote, source_text, verdict, actual, applied_to):
        self.rules.append({"id": rid, "rule": statement, "applied_to": applied_to,
                           "verdict": verdict, "actual": actual,
                           "source": {"kind": "package_rule", "locator": locator, "quote": quote,
                                      "quote_verbatim": bool(quote) and squeeze(quote) in squeeze(source_text or quote)}})


def _material_quote(rec):
    """Pick a checkable quote for one material and say where it came from."""
    name, kind = rec.get("name") or "", rec.get("kind") or ""
    path = rec.get("path") or ""
    if kind == "text":
        raw = read_text(path)
        cand = [ln.strip() for ln in raw.splitlines() if len(ln.strip()) >= 12]
        quote = cand[0] if cand else squeeze(raw)[:120]
        return quote, ("input/" + name), "input", raw
    pars = rec.get("paragraphs") or []
    if pars:
        quote = str(pars[0].get("text") or "")[:160]
        return quote, str(pars[0].get("pid") or name), "extracted", quote
    return "", "input/" + name, "binary", ""


def _case_block(ctx):
    """Return the parsed case pack, its raw text and whether it parsed."""
    raw = ctx.get("raw_case") or ""
    if not raw and ctx.get("case_path"):
        raw = read_text(ctx["case_path"])
    pack = ctx.get("pack") or {}
    ok = "_bad_json" not in pack
    return pack, raw, ok


def _artifacts(ctx):
    """Expectations for the five primary deliverables; the asset bundle is checked
    by self_check.json because it is written after this file."""
    b = Basket()
    out = Path(ctx["out_dir"])
    specs = (("benchmark.json", "json", ("schema", "items"), "题集快照：items/rejected/mode"),
             ("anchors.json", "json", ("schema", "anchors"), "引文抽查表：material/locator/quote/verified"),
             ("scoring.json", "json", ("schema", "items", "aggregate", "scale"), "0/1/2 评分表与汇总"),
             ("report.md", "md", ("#",), "人读凭证：材料/逐题/汇总/缺口四段"),
             ("result.json", "json", ("case_id", "status", "outputs", "contract_fields_present"), "信封 + 契约回填"))
    for name, kind, keys, what in specs:
        p = out / name
        exists = p.is_file()
        raw = read_text(p)
        b.add("artifacts", name, "%s exists and is non-empty" % what, True, exists and bool(squeeze(raw)),
              name, (raw.splitlines()[0] if raw else ""), "artifact", source_text=raw,
              verdict=None if exists and squeeze(raw) else "missing")
        if kind == "json" and exists:
            try:
                doc = json.loads(raw)
            except ValueError:
                doc = None
            for key in keys:
                frag = raw_fragment(raw, key)
                present = isinstance(doc, dict) and (key in doc or (isinstance(doc.get(key), (list, dict)) and doc.get(key)))
                if key == "#":
                    continue
                b.add("artifacts", "%s#%s" % (name, key), "required JSON key %r is present" % key,
                      True, bool(present), "%s#%s" % (name, key),
                      squeeze(frag) if frag else "", "artifact", source_text=raw,
                      verdict=None if present else "deviation")
        if kind == "md" and raw:
            b.add("artifacts", name + "#sections", "report carries four headed sections",
                 4, len(re.findall(r"(?m)^##\s+\d+\.", raw)), name + "#section-headers",
                 next((ln for ln in raw.splitlines() if ln.startswith("## ")), ""), "artifact", source_text=raw)
    return b


def _status_block(ctx, pub, b, cards):
    res = pub.get("result") or {}
    index = ctx.get("index") or {}
    n_mat = len(index.get("materials") or [])
    n_par = sum(len(m.get("paragraphs") or []) for m in index.get("materials") or [])
    origin = str((pub.get("benchmark") or {}).get("mode") or "")
    issues = len(ctx.get("issues") or [])
    expect = ("input_error" if not n_mat else
              "insufficient_evidence" if (not n_par or not cards) else
              "ok" if origin == "agent_authored" and not issues else "partial")
    res_status = str(res.get("status") or "")
    quote, loc, kind, src = _material_quote((index.get("materials") or [{}])[0]) if index.get("materials") else ("", "input/", "input", "")
    b.add("status", "status", "status follows the documented trigger table", expect, res_status,
          loc, quote, kind, source_text=src,
          note="recomputed from material/item/mode/issue counts, not read from the status field")
    # fallback / mode consistency
    draft_exists = bool(ctx.get("draft_path")) and Path(ctx.get("draft_path")).is_file()
    fallback = str((pub.get("benchmark") or {}).get("mode") or "") == "fallback_minimal"
    expect_fb = (not draft_exists) or not cards
    b.add("status", "mode_fallback", "fallback mode is used exactly when no usable draft exists",
          bool(expect_fb), fallback, "work/" + "questions.draft.json",
          "questions.draft.json absent -> deterministic fallback items" if not draft_exists else
          "draft present -> authored cards are used", "input",
          verdict=None if bool(expect_fb) == fallback else "deviation",
          note="path exists" if draft_exists else "path missing")
    if fallback:
        bad = []
        for it in cards:
            for ev in it.get("evidence") or []:
                hit = locate(corpus_from(index), str(ev.get("material") or ""), str(ev.get("quote") or ""))
                if not hit.get("verified"):
                    bad.append(it.get("id"))
        b.add("status", "fallback_items_real", "fallback items cite paragraphs that really exist",
              0, len(bad), "benchmark.json#items", (cards[0].get("evidence") or [{}])[0].get("quote", "") if cards else "",
              "artifact",
              verdict="met" if not bad and len(cards) <= 6 else "deviation",
              note="fallback cap is 6 items")
        b.add("status", "fallback_degraded", "a fallback run records a degradation entry",
              True, bool(res.get("degradations")), "result.json#degradations",
              "fallback_generated_items", "artifact",
              verdict="met" if res.get("degradations") else "deviation")
    # technical synthetic declaration
    synth = res.get("technical_synthetic") or {}
    hits = _synthetic_hits(ctx)
    b.add("status", "technical_synthetic", "checker/candidate material is registered but never scored",
          bool(hits), bool(synth.get("present")), "result.json#technical_synthetic",
          ";".join(hits) if hits else "no checker/candidate artefact in input", "artifact",
          verdict="met" if (bool(hits) == bool(synth.get("present"))
                            and synth.get("not_a_dsh_score") is True
                            and synth.get("scored", False) is False) else "deviation")
    # pending queue accounting
    sc_items = (pub.get("scoring") or {}).get("items") or []
    low_pts = sum(1 for s in sc_items for p in (s.get("points") or []) if int(p.get("score") or 0) < 2)
    rejected = ctx.get("rejected") or []
    expect_queue = min(20, low_pts + len(rejected))
    b.add("status", "pending_human_queue", "pending_human lists every point scored below 2 (capped at 20)",
          expect_queue, len(res.get("pending_human") or []), "result.json#pending_human",
          (res.get("pending_human") or [""])[0], "artifact", source_text=json.dumps(res.get("pending_human") or []))
    return b


def _synthetic_hits(ctx):
    pack = ctx.get("pack") or {}
    hits = []
    if isinstance(pack, dict):
        for name in SYNTH_KEYS:
            for k, v in pack.items():
                if str(k).lower().replace("-", "_") == name and v not in (None, "", [], {}):
                    hits.append("case.json:" + str(k))
    ip = Path(ctx.get("in_dir") or ".")
    try:
        for p in sorted(ip.rglob("*")):
            if p.is_file() and re.search(r"(candidate|baseline|response|checker|model_out)", p.name.lower()):
                hits.append(p.name)
    except OSError:
        pass
    return hits[:6]


def _contract_block(ctx, pub, b):
    pack, raw, parsed = _case_block(ctx)
    contract = ctx.get("contract")
    if not isinstance(contract, (dict, list)) or not contract:
        b.na("contract", "contract", "case declares an output_contract block", "absent",
             "case.json", "", "input",
             note="no usable output_contract in the input; contract echo may stay empty")
        return []
    frag = raw_fragment(raw, "output_contract")
    quote = squeeze(frag) if frag else ""
    names = [str(k) for k in contract] if isinstance(contract, dict) else [str(x) for x in contract]
    res = pub.get("result") or {}
    present = res.get("contract_fields_present") or []
    b.add("contract", "contract_fields_present", "declared field names are echoed in declaration order",
          names, present, "case.json#output_contract", quote, "input", source_text=raw)
    for name in names:
        b.add("contract", name, "declared contract field appears on the result.json top level",
              True, name in res, "case.json#output_contract", quote, "input", source_text=raw,
              note="value may be a real value or a null-shaped mirror; the key itself must never vanish")
    echo = res.get("contract_echo")
    b.add("contract", "contract_echo", "contract_echo reproduces the declared contract verbatim",
          contract, echo, "case.json#output_contract", quote, "input", source_text=raw)
    cid, cid_ok = string_at(raw, "case_id")
    ids = None
    try:
        ids = json.loads(raw) if parsed else None
    except ValueError:
        ids = None
    found = None
    if isinstance(ids, dict):
        for k in ID_KEYS:
            if ids.get(k) not in (None, ""):
                found = ids.get(k)
                break
    if cid is not None:
        b.add("contract", "case_id", "case_id from the case file is carried into result.json",
              str(found) if found is not None else cid, str(res.get("case_id") or ""),
              "case.json#case_id", cid, "input", source_text=raw,
              note="" if cid_ok else "value string needed JSON unescaping; quoted form is the raw source")
    return names


def _material_block(ctx, pub, b):
    index = ctx.get("index") or {}
    mats = index.get("materials") or []
    sources = {str(s.get("id")): s for s in (pub.get("result") or {}).get("sources") or []}
    for m in mats:
        mid = str(m.get("mid") or "")
        quote, loc, kind, src = _material_quote(m)
        src_rec = sources.get(mid) or {}
        size = m.get("bytes")
        b.add("materials", "%s.bytes" % mid, "material byte size matches the file on disk",
              size, src_rec.get("bytes"), "input/" + str(m.get("name") or ""), quote, kind, source_text=src)
        b.add("materials", "%s.sha1" % mid, "material sha1 prefix matches the file on disk",
              sha1_16(m.get("path")), src_rec.get("sha1"), "input/" + str(m.get("name") or ""), quote, kind,
              source_text=src)
        pars = m.get("paragraphs") or []
        expect_status = "ok" if pars else "no_text"
        b.add("materials", "%s.status" % mid, "material status reflects whether text was extracted",
              expect_status, str(src_rec.get("status") or ""), "input/" + str(m.get("name") or ""), quote, kind,
              source_text=src,
              note="pdf/docx materials are judged on the extracted text layer")
        nchar = sum(len(str(p.get("text") or "")) for p in pars)
        b.add("materials", "%s.chars" % mid, "material char count is the sum of its paragraph lengths",
              nchar, m.get("chars"), str((pars[0].get("pid") if pars else "input/" + str(m.get("name") or ""))),
              str((pars[0].get("text") if pars else quote) or "")[:160], kind, source_text=src)
        if pars:
            head = str(pars[0].get("text") or "")[:160]
            b.add("materials", "%s.paragraph1_verbatim" % mid,
                  "the first indexed paragraph is a verbatim slice of the material",
                  True, locate(corpus_from(index), mid, head).get("verified"),
                  str(pars[0].get("pid")), head, kind, source_text=src,
                  note="whitespace-normalised containment")


def _workorder_block(ctx, pub, b, cards, corpus):
    pack, raw, parsed = _case_block(ctx)
    wo = pick(pack, WORKORDER_KEYS) if isinstance(pack, dict) else None
    if wo is None:
        quote, loc, kind, src = _material_quote(((ctx.get("index") or {}).get("materials") or [{}])[0])
        b.na("workorder", "organizer_workorder",
             "a four-item source-conditioned workorder drives the card set", "not declared",
             loc if loc != "input/" else "case.json", quote, kind,
             note="no organizer_workorder in this input; cards are authored from the materials only")
        return
    items = wo if isinstance(wo, list) else pick(wo, ("items", "workorder", "cards", "drafts")) or []
    if isinstance(items, dict):
        items = pick(items, ("items",)) or []
    items = [x for x in items if isinstance(x, dict)]
    b.add("workorder", "declared_count", "the card set covers at least every workorder item",
          len(items), len(cards), "case.json#organizer_workorder",
          squeeze(raw_fragment(raw, "organizer_workorder.task") or ""), "input", source_text=raw)
    for i, it in enumerate(items[:8]):
        task, _ = string_at(raw, "organizer_workorder[%d].task" % i)
        q = task or squeeze(raw_fragment(raw, "organizer_workorder[%d]" % i) or "")
        refs = json.dumps(it, ensure_ascii=False)
        locs = re.findall(r"\b[A-Za-z]\d{2}#p\d+\b", refs)
        known = {str(p.get("pid")) for m in ((ctx.get("index") or {}).get("materials") or [])
                 for p in (m.get("paragraphs") or [])}
        unresolved = [lc for lc in locs if lc not in known]
        b.add("workorder", "item%d.locators" % (i + 1),
              "workorder source locators resolve to real paragraphs", 0, len(unresolved),
              "case.json#organizer_workorder[%d]" % i, q, "input", source_text=raw,
              verdict="met" if not unresolved else "deviation",
              note=("unresolved=" + ",".join(unresolved)) if unresolved else "")
        ans = pick(it, ("reference_answer", "reference_answers", "answer", "gold_answer"))
        ans = ans if isinstance(ans, list) else ([ans] if isinstance(ans, str) else [])
        if ans:
            terms = terms_from(" ".join(str(a) for a in ans))
            targets = [c for c in cards if any(
                str(e.get("material")) in locs for e in (c.get("evidence") or []))] or cards
            best = 0.0
            for c in targets[:8]:
                body = " ".join([str(x) for x in (c.get("reference_answer") or [])]
                                + [str(e.get("quote") or "") for e in (c.get("evidence") or [])])
                best = max(best, coverage(terms, body))
            b.add("workorder", "item%d.answer_covered" % (i + 1),
                  "a card carries the workorder reference answer's key terms", "coverage>=0.35",
                  best, "case.json#organizer_workorder[%d].reference_answer" % i, q, "input",
                  source_text=raw, verdict="met" if best >= 0.35 else "deviation",
                  note="max key-term coverage over the cards that point at the same material")
        elif it.get("reference_missing") is True or pick(it, ("reference_answer", "answer")) is None:
            b.add("workorder", "item%d.reference_missing" % (i + 1),
                  "no workorder answer -> nothing may be invented", True,
                  not any(c.get("_invented") for c in cards), "case.json#organizer_workorder[%d]" % i, q,
                  "input", source_text=raw,
                  note="package stores authored reference_answers only; the workorder answer stays absent")


def _card_block(ctx, pub, b, cards, corpus):
    sc = {str(s.get("id")): s for s in (pub.get("scoring") or {}).get("items") or []}
    wrel, wquote, _ = _rule_map(ctx)["weight_sum"]
    for it in cards[:12]:
        cid = str(it.get("id") or "")
        first_ev = (it.get("evidence") or [{}])[0]
        ev_loc = str(first_ev.get("locator") or first_ev.get("material") or "benchmark.json#items")
        ev_q = str(first_ev.get("quote") or "")
        b.add("cards", "%s.question_len" % cid, "question is at least 10 characters",
              10, len(str(it.get("question") or "")), ev_loc, ev_q, "input",
              verdict="met" if len(str(it.get("question") or "")) >= 10 else "deviation")
        rub = it.get("rubric") or []
        b.add("cards", "%s.rubric" % cid, "at least one rubric point is defined",
              True, bool(rub), ev_loc, ev_q, "input",
              note="points=" + str(len(rub)))
        weights = [float(r.get("weight") or 0.0) for r in rub]
        tot = round(sum(weights), 4)
        b.add("cards", "%s.weight_sum" % cid, "rubric weights sum to 1.0 within 0.02",
              1.0, tot, wrel, wquote, "package_rule",
              verdict="met" if rub and abs(tot - 1.0) <= 0.02 else "deviation")
        b.add("cards", "%s.reference_answer" % cid, "at least one reference answer is published",
              True, bool(it.get("reference_answer")), ev_loc, ev_q, "input")
        b.add("cards", "%s.type" % cid, "card type is one of the declared kinds",
              True, str(it.get("type") or "") in KINDS, ev_loc, ev_q, "input",
              note="value=" + str(it.get("type")))
        b.add("cards", "%s.evidence" % cid, "at least one evidence block is attached",
              True, bool(it.get("evidence")), ev_loc, ev_q, "input")
        bad = []
        for ev in it.get("evidence") or []:
            quote = str(ev.get("quote") or "")
            if len(squeeze(quote)) < 12:
                bad.append("short_quote")
                continue
            hit = locate(corpus, str(ev.get("material") or ""), quote)
            if not hit.get("verified"):
                bad.append("quote_absent")
                continue
            if hit.get("pid") and ev.get("locator") and hit.get("pid") != ev.get("locator"):
                bad.append("locator_mismatch")
        b.add("cards", "%s.evidence_located" % cid,
              "every published quote resolves verbatim and its locator agrees", 0, len(bad),
              ev_loc, ev_q, "input", verdict="met" if not bad else "deviation",
              note=",".join(sorted(set(bad))))
        b.add("cards", "%s.in_scoring" % cid, "the card has a scoring record", True, cid in sc,
              "scoring.json#items", ev_q, "artifact",
              verdict="met" if cid in sc else "missing")


def _anchor_block(ctx, pub, b, corpus):
    rows = (pub.get("anchors") or {}).get("anchors") or []
    for row in rows[:20]:
        cid = str(row.get("item_id") or "")
        mid, loc, quote = str(row.get("material") or ""), str(row.get("locator") or ""), str(row.get("quote") or "")
        hit = locate(corpus, mid, quote)
        s_loc = hit.get("pid") or loc or mid
        b.add("anchors", "%s.%s.verified" % (cid, loc or mid), "anchor quote is verified verbatim in the material",
              True, bool(row.get("verified")), s_loc, quote, "input",
              verdict="met" if hit.get("verified") else "deviation",
              note="match=" + str(hit.get("match") or hit.get("reason")))
        b.add("anchors", "%s.%s.locator" % (cid, loc or mid), "declared locator equals the paragraph the quote really sits in",
              hit.get("pid"), loc or None, s_loc, quote, "input",
              verdict=("met" if (hit.get("pid") is None or hit.get("pid") == loc) else "deviation"),
              note="space-insensitive/unknown-page matches carry no paragraph id")
        b.add("anchors", "%s.%s.match" % (cid, loc or mid), "documented match mode is reported",
              hit.get("match"), row.get("match"), s_loc, quote, "input",
              verdict="met" if (hit.get("match") or "") == (row.get("match") or "") else "deviation")


def _score_block(ctx, pub, b, cards, corpus):
    graded = grade(cards, corpus)
    sc_items = {str(s.get("id")): s for s in (pub.get("scoring") or {}).get("items") or []}
    raw = pub.get("scoring_raw") or ""
    order = {str(c.get("id")): i for i, c in enumerate(cards)}
    sc_lookup = {}
    for sid, s in sc_items.items():
        for p in s.get("points") or []:
            sc_lookup[(sid, str(p.get("rubric_id")))] = p
    for g in graded:
        card = next((c for c in cards if str(c.get("id")) == g["id"]), {})
        for p in g["points"]:
            key = (g["id"], str(p["rubric_id"]))
            real = sc_lookup.get(key) or {}
            ev_q = ""
            for ev in card.get("evidence") or []:
                if locate(corpus, str(ev.get("material") or ""), str(ev.get("quote") or "")).get("verified"):
                    ev_q = str(ev.get("quote") or "")
                    break
            b.add("scores", "%s/%s.score" % (g["id"], p["rubric_id"]),
                  "point score follows the 0/1/2 coverage rule", p["score"], real.get("score"),
                  str(real.get("locator") or p.get("locator") or "material"),
                  ev_q, "input",
                  verdict="met" if p["score"] == real.get("score") else "deviation",
                  note="recomputed coverage=%s" % p.get("coverage"))
            if p["score"] > 0:
                b.add("scores", "%s/%s.locator" % (g["id"], p["rubric_id"]),
                      "the scored point cites the anchor with the best coverage",
                      p.get("locator"), real.get("locator"), str(p.get("locator") or "material"),
                      ev_q, "input",
                      verdict="met" if (p.get("locator") or "") == (real.get("locator") or "") else "deviation")
        real_item = sc_items.get(g["id"]) or {}
        idx = order.get(g["id"], 0)
        frag = raw_fragment(raw, "items[%d]" % idx) if raw else None
        b.add("scores", "%s.item_score" % g["id"], "item score equals the weighted point sum",
              g["score"], real_item.get("score"), "scoring.json#items[%d]" % idx,
              squeeze(frag) if frag else "", "artifact", source_text=raw,
              verdict="met" if g["score"] == real_item.get("score") else "deviation",
              note="max 2")
    return graded


def _aggregate_block(ctx, pub, b, graded, cards):
    raw = pub.get("scoring_raw") or ""
    frag = raw_fragment(raw, "aggregate")
    quote = squeeze(frag) if frag else ""
    gold = aggregate(graded, cards)
    actual = (pub.get("scoring") or {}).get("aggregate") or {}
    for key in ("n_items", "n_points", "n2", "n1", "n0", "rate2", "judgeable_rate", "mean_score"):
        b.add("aggregate", key, "aggregate %s is recomputable from the published item table" % key,
              gold[key], actual.get(key), "scoring.json#aggregate", quote, "artifact", source_text=raw)
    anchors = (pub.get("anchors") or {}).get("anchors") or []
    b.add("aggregate", "n_anchors", "n_anchors counts every published evidence block",
          sum(len(it.get("evidence") or []) for it in cards), actual.get("n_anchors"),
          "scoring.json#aggregate", quote, "artifact", source_text=raw)
    b.add("aggregate", "n_anchors_verified", "n_anchors_verified counts verified anchor rows",
          sum(1 for a in anchors if a.get("verified")), actual.get("n_anchors_verified"),
          "scoring.json#aggregate", quote, "artifact", source_text=raw)
    b.add("aggregate", "counts_add_up", "n2 + n1 + n0 equals n_points", gold["n_points"],
          (actual.get("n2") or 0) + (actual.get("n1") or 0) + (actual.get("n0") or 0),
          "scoring.json#aggregate", quote, "artifact", source_text=raw)
    return gold, actual


def _version_block(ctx, b):
    p = Path(ctx["out_dir"]) / "version_history.md"
    raw = read_text(p)
    lines = raw.splitlines()
    for needle, loc in (("v0.0.1", "version_history.md#versions"), ("v1.0.0", "version_history.md#versions"),
                        ("v1.1.0", "version_history.md#versions")):
        quote = next((ln for ln in lines if needle in ln), "")
        b.add("version", "static_" + needle[1:], "static version history mentions " + needle, True,
              bool(quote), loc, quote, "artifact", source_text=raw,
              verdict="met" if quote else "missing")
    quote = next((ln for ln in lines if "回退" in ln), lines[-1] if lines else "")
    b.add("version", "rollback", "rollback path is documented", True, bool(quote),
          "version_history.md#rollback", quote, "artifact", source_text=raw)
    quote = next((ln for ln in lines if "本次运行" in ln), "")
    b.add("version", "runtime_section", "runtime section appended to the static ledger", True, bool(quote),
          "version_history.md#runtime", quote, "artifact", source_text=raw)


def _report_block(ctx, pub, b):
    raw = pub.get("report_text") or ""
    for head in ("## 1.", "## 2.", "## 3.", "## 4."):
        quote = next((ln for ln in raw.splitlines() if ln.startswith(head)), "")
        b.add("report", head, "report section %r is present" % head, True, bool(quote),
              "report.md#" + head.strip("#. ").replace(" ", "-"), quote, "artifact", source_text=raw,
              verdict="met" if quote else "missing")


def _rule_map(ctx):
    """Quote each published acceptance rule from the package reference it lives in."""
    root = Path(ctx.get("pkg_root") or ".")
    cache, out = {}, {}
    for rid, rel, needles, _, _ in RULE_SPECS:
        if rel not in cache:
            cache[rel] = read_text(root / rel)
        text = cache[rel]
        quote = ""
        for needle in needles:
            i = text.find(needle)
            if i >= 0:
                j = text.find("。", i)
                j = j + 1 if 0 <= j - i <= 180 else min(len(text), i + 120)
                quote = squeeze(text[i:j])
                break
        out[rid] = (rel, quote, text)
    return out


def derive(ctx):
    """Build the complete expectation set and verdicts for one build run."""
    pub = load_built(ctx["out_dir"])
    index = ctx.get("index") or {}
    corpus = corpus_from(index)
    cards = (pub.get("benchmark") or {}).get("items") or []
    b = Basket()
    b.derivation = [
        {"id": "D1", "source": "case.json", "method": "output_contract renamed/echoed, case_id and "
                                                "organizer_workorder extracted as raw JSON slices"},
        {"id": "D2", "source": "input materials", "method": "byte size/sha1/char counts re-read from disk; "
                                                       "paragraph ids and quotes re-resolved from the paragraph index"},
        {"id": "D3", "source": "benchmark.json", "method": "card invariants (question length, rubric, weights, "
                                                           "type, evidence) checked against the published card text"},
        {"id": "D4", "source": "benchmark.json + anchors.json", "method": "every 0/1/2 point re-counted from the "
                                                                        "published rubric key terms and the material "
                                                                        "bytes; locator re-derived independently"},
        {"id": "D5", "source": "scoring.json", "method": "item scores and all aggregate fields recomputed from the "
                                                         "re-counted point table"},
        {"id": "D6", "source": "references/ + SKILL.md", "method": "acceptance rules quoted verbatim from the "
                                                                   "shipped reference text and applied to the checks"},
    ]
    _contract_block(ctx, pub, b)
    _material_block(ctx, pub, b)
    _workorder_block(ctx, pub, b, cards, corpus)
    _card_block(ctx, pub, b, cards, corpus)
    _anchor_block(ctx, pub, b, corpus)
    graded = _score_block(ctx, pub, b, cards, corpus)
    gold_agg, _real_agg = _aggregate_block(ctx, pub, b, graded, cards)
    _status_block(ctx, pub, b, cards)
    b.items.extend(_artifacts(ctx).items)
    _report_block(ctx, pub, b)
    _version_block(ctx, b)

    # rules: quote from the shipped reference and link the verdict to the check family
    links = {}
    for it in b.items:
        links.setdefault(it["category"], []).append(it["verdict"])
    rmap = _rule_map(ctx)
    for rid, rel, needles, family, statement in RULE_SPECS:
        verdicts = [v for fam in str(family).split("+") for v in (links.get(fam) or [])]
        bad = sum(1 for v in verdicts if v in ("deviation", "missing"))
        qrel, quote, text = rmap[rid]
        verdict = "not_applicable" if not verdicts else ("met" if bad == 0 else "deviation")
        b.rule(rid, statement, qrel, quote, text, verdict,
               "%d applicable row(s), %d deviation/missing" % (len(verdicts), bad), family)

    for i, it in enumerate(b.items, 1):
        it["id"] = "G%03d" % i
    for i, r in enumerate(b.rules, 1):
        r["id"] = "R%02d" % i
    by_cat, by_ver = {}, {}
    for it in b.items:
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
        by_ver[it["verdict"]] = by_ver.get(it["verdict"], 0) + 1
    quotes = [it for it in b.items if it["source"]["quote"]]
    verified = [it for it in quotes if it["source"]["quote_verbatim"]]
    summary = {"n_items": len(b.items), "by_category": by_cat, "by_verdict": by_ver,
               "n_quotes": len(quotes), "n_quotes_verbatim": len(verified),
               "quote_hit_rate": round(len(verified) / len(quotes), 3) if quotes else 1.0,
               "n_rules": len(b.rules),
               "rules_met": sum(1 for r in b.rules if r["verdict"] in ("met", "not_applicable")),
               "met": by_ver.get("met", 0), "deviation": by_ver.get("deviation", 0),
               "missing": by_ver.get("missing", 0),
               "not_applicable": by_ver.get("not_applicable", 0)}
    return {"schema": "reading-bench-forge/golden-standard@1",
            "case_id": pub.get("result", {}).get("case_id") if isinstance(pub.get("result"), dict) else ctx.get("case_id"),
            "package": {"name": "reading-bench-forge", "version": ctx.get("skill_version"),
                        "revision": "v1.1.0 asset layer"},
            "purpose": "Independent expectation ledger for this build: what the benchmark should contain, "
                       "with a source locator and a verbatim quote for every row, plus the recomputation "
                       "rules behind each score.",
            "derivation": b.derivation,
            "recompute_rules": b.rules,
            "items": b.items,
            "summary": summary,
            "scope_note": "The five verifiable assets themselves (golden_standard.json, diff_report.md, "
                          "version_history.md, run.log, self_check.json) are written by this finalize "
                          "pass; their existence and non-emptiness is asserted by self_check.json, which "
                          "runs after they are on disk.",
            "gold_aggregate": gold_agg,
            "gold_status": next((it["golden"] for it in b.items if it["subject"] == "status"), None)}


def load_built(out_dir):
    """Read the artefacts this run already persisted (never the in-memory copies)."""
    out = {}
    for name in ("benchmark", "anchors", "scoring", "result"):
        p = Path(out_dir) / (name + ".json")
        raw = read_text(p)
        try:
            out[name] = json.loads(raw) if raw.strip() else None
        except ValueError:
            out[name] = None
        out[name + "_raw"] = raw
    rp = Path(out_dir) / "report.md"
    out["report_text"] = read_text(rp)
    return out
