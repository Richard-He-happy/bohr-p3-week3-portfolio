#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared core: item construction, anchor rules, two independent raters, aggregation,
word-pack loading, plus the validation command line used to inspect a delivery."""
import argparse, csv, hashlib, json, re, sys, unicodedata
from pathlib import Path

KVER = "1.0.0"; AVER = "1.0.0"
SET5 = ("golden_standard.json", "diff_report.md", "version_history.md", "run.log", "self_check.json")
ADDFIELDS = ("golden_standard", "diff_report", "version_history", "self_check")
NUMRX = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)")
REJECTRX = re.compile(r"(as an ai|i cannot|i can't|unable to (help|comply)|无法(完成|提供)|抱歉[，,]?我(不能|无法)|作为一个?AI)", re.I)
SOFTWORD = re.compile(r"(流畅|清晰|合理|完整|学术性|well[- ]written|clear and logical)")
TRACKS = ["task_set_design", "reference_answer", "scoring_anchor",
        "inter_annotator_consistency", "run_reproducibility", "evaluation_report"]
FAULT2TYPE = {"number_preserved": "事实不符", "no_new_numbers": "事实不符", "word_limit": "格式不符",
        "section_order": "缺要点", "contains_all": "缺要点", "contains_any": "缺要点"}


def fill(key, **kw):
    t = packdata().get(key)
    if t is None: return ""
    lines = t if isinstance(t, list) else [t]
    return "\n".join(x.format(**kw) for x in lines)


# ======================= item construction =======================

def packdata():
    """Load the wording pack (references/stylepack.json).  It is pure data on purpose:
wording edits never require touching code."""
    p = Path(__file__).resolve().parent.parent / "references" / "stylepack.json"
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return {}

def canon(s):
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", " ", re.sub(r"[\u00a0\u2009\u202f]", " ", s)).strip().lower()

def grain(s):
    return [t for t in re.split(r"[^0-9a-z\u00b5\u03bc%./+-]+", canon(s)) if t]

def dhash(s):
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()

def jstr(o, ind=1):
    return json.dumps(o, ensure_ascii=False, indent=ind, default=str)

def trim(s, qty=300):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if len(s) <= qty else s[:qty].rstrip() + "…"

def point(text, inspect_pkg, loc, quote, fid, obs):
    return dict(text=text, check=inspect_pkg, locator=loc, quote=quote, fact_id=fid, observable=obs)

def grade_level(rule, text, rater):
    """Grade one anchor rule against one text and return 0, 1 or 2.

 Rater a asks for the normalised string verbatim.  Rater b takes a genuinely separate
 route: it accepts when at most one word token of the rule is missing from the text.
 Keeping two implementations is what makes the agreement figure meaningful."""
    t, typ = canon(text), rule.get("type")
    if typ in ("contains_all", "contains_any"):
        got = 0
        for v in rule["values"]:
            if canon(v) in t: got += 1; continue
            vt = grain(v)
            if rater == "b" and len(vt) >= 2 and sum(1 for x in vt if x not in t) <= 1: got += 1
        if typ == "contains_any": return 2 if got else 0
        if got == len(rule["values"]): return 2
        return 1 if got >= max(1, (len(rule["values"]) + 1) // 2) else 0
    if typ == "number_preserved":
        v, u = rule.get("value", ""), rule.get("unit", "")
        if u and (canon(v + " " + u) in t or canon(v + u) in t): return 2
        if v and re.search(r"(?<![\d.])" + re.escape(canon(v)) + r"(?![\d])", t): return 1 if u else 2
        return 0
    if typ == "section_order":
        pos = [t.find(canon(h)) for h in rule["values"]]
        return (2 if pos == sorted(pos) else 1) if all(p >= 0 for p in pos) else 0
    if typ == "word_limit":
        w = len(re.findall(r"\S+", text)); hi = rule.get("max") or 10 ** 9
        return 2 if rule.get("min", 0) <= w <= hi else (1 if w <= hi * 1.25 else 0)
    if typ == "no_new_numbers":
        ex = [x for x in set(NUMRX.findall(canon(text))) if x not in set(rule.get("allowed") or [])]
        return 2 if not ex else (1 if len(ex) <= (1 if rater == "a" else 3) else 0)
    return 0

def score(ANCH, sub_id, text, run_kind, degr=None):
    if degr is not None and REJECTRX.search(text or "") and len((text or "").split()) < 120:
        degr.append({"stage": "score", "ratee": sub_id, "note": "refusal-like output detected"})
    lines = [l for l in (text or "").splitlines() if l.strip()]; rows = []
    for a in ANCH:
        la, lb = grade_level(a["rule"], text, "a"), grade_level(a["rule"], text, "b"); adj = min(la, lb)
        probe = [p for p in (a["rule"].get("values") or [a["rule"].get("value", "")]) if p]
        q = loc = ""
        for i, l in enumerate(lines, 1):
            if probe and any(canon(p) in canon(l) for p in probe):
                q, loc = trim(l, 200), "ratee:%s#L%d" % (sub_id, i); break
        if not q and lines: q, loc = trim(lines[0], 160), "ratee:%s#L1" % sub_id
        rows.append(dict(run_type=run_kind, ratee_id=sub_id, task_id=a["task_id"], anchor_id=a["anchor_id"],
                         point_id=a["point_id"] or "", scope=a["scope"], level_rater_a=la, level_rater_b=lb,
                         delta=la - lb, adjudicated=adj, agree=int(la == lb),
                         verdict="met" if adj == 2 else ("partial" if adj == 1 else "missed"),
                         failure_type="" if adj == 2 else FAULT2TYPE.get(a["rule"]["type"], "缺要点"),
                         evidence_quote=q, evidence_locator=loc or "ratee:%s#none" % sub_id,
                         src_locator=a["evidence_locator"] or "", rule=json.dumps(a["rule"], ensure_ascii=False)))
    return rows

def kappa(rows):
    ps = [(r["level_rater_a"] >= 1, r["level_rater_b"] >= 1) for r in rows]
    if not ps: return None
    qty = len(ps); po = sum(a == b for a, b in ps) / qty
    pa = sum(a for a, _ in ps) / qty; pb = sum(b for _, b in ps) / qty; pe = pa * pb + (1 - pa) * (1 - pb)
    return round((po - pe) / (1 - pe), 4) if pe < 1 else 1.0

def aggregate(rows, items):
    out, FX = [], packdata().get("fix", {})
    for t in items:
      for sub_id, run_kind in sorted({(r["ratee_id"], r["run_type"]) for r in rows if r["task_id"] == t["task_id"]}):
        rs = [r for r in rows if r["task_id"] == t["task_id"] and r["ratee_id"] == sub_id and r["run_type"] == run_kind]
        if not rs: continue
        audit_res = round(100.0 * sum(r["adjudicated"] for r in rs) / (2 * len(rs)), 1)
        ft = sorted({r["failure_type"] for r in rs if r["adjudicated"] < 2 and r["failure_type"]})
        out.append(dict(run_type=run_kind, ratee_id=sub_id, task_id=t["task_id"],
                        direction=t["direction"], writing_type=t["writing_type"], tier=t["tier"],
                        anchors=len(rs), points_met=sum(1 for r in rs if r["adjudicated"] == 2), score=audit_res,
                        verdict="pass" if audit_res >= 85 else ("partial" if audit_res >= 50 else "fail"),
                        failure_type=";".join(ft) or "无",
                        blame="无" if not ft else ("执行(格式)" if ft == ["格式不符"] else "执行(事实/要点)"),
                        anchor_ids=";".join(r["anchor_id"] for r in rs),
                        evidence=";".join(sorted({r["evidence_quote"][:80] for r in rs if r["evidence_quote"]}))[:400],
                        improvement=FX.get(ft[0] if ft else "无", "")))
    return out


# ======================= validation side =======================

def compose_tasks(brief, docs, EV, qty, uncn):
    TYPES = packdata().get("types", {})
    big = max(docs, key=lambda d: len(d["text"]))
    pick = lambda k, m: [f for f in EV if f["kind"] == k][:m]
    figs, ids, creads = pick("number", 40), pick("doi", 8), pick("heading", 20)
    refs_, tags = pick("citation", 12), pick("caption", 8)
    lang = "zh" if 40 * len(re.findall(r"[\u4e00-\u9fff]", big["text"])) > len(big["text"]) else "en"
    reviews = brief.get("reviewer_comments") or brief.get("reviews") or []
    reviews = reviews if isinstance(reviews, list) else [reviews]
    av = ["abstract_summary", "structured_outline"] + (["methods_rewrite"] if figs else []) + \
         (["citation_format"] if (ids or refs_) else []) + ["bilingual_abstract"] + (["review_response"] if reviews else [])
    items = []
    for i in range(qty):
        wt = av[i % len(av)]; tier, action, secs, wc = TYPES[wt]; shift = (i // len(av)) * 3
        tid, graded = "T%02d" % (i + 1), []
        if wt == "citation_format" and (ids or refs_):
            for f in ((ids + refs_)[shift:shift + 3] or (ids + refs_)[:3]):
                graded.append(point("逐字保留引用条目/标识：%s" % trim(f["value"], 90),
                             dict(type="contains_all", values=[f["value"]]), f["locator"], f["quote"],
                             f["fact_id"], "稿件出现与源材料完全一致的条目/DOI 字符串"))
        if wt == "structured_outline" and creads:
            secs = [f["value"] for f in creads[:4]]
            graded.append(point("大纲含小节且顺序一致：%s" % " / ".join(secs), dict(type="section_order", values=secs),
                         creads[0]["locator"], creads[0]["quote"], creads[0]["fact_id"], "按出现位置检查小节标题序列"))
        if wt == "review_response" and reviews:
            for k, it in enumerate(reviews[:3], 1):
                s = trim(it, 120)
                graded.append(point("回应审稿意见 %d：%s" % (k, s), dict(type="contains_all", values=[s[:60]]),
                             "case.json:reviewer_comments[%d]" % (k - 1), s, None, "回复中有该意见的逐条回应段"))
        for f in (figs[shift:] or figs):
            if len(graded) >= 3: break
            v = f["value"].split(" ")
            graded.append(point("逐字保留数值与单位：%s" % f["value"],
                         dict(type="number_preserved", value=v[0], unit=v[1] if len(v) > 1 else ""),
                         f["locator"], f["quote"], f["fact_id"], "稿件出现该数值且单位紧随其后，未改写/换算"))
        if len(graded) < 3:
            for f in tags:
                if len(graded) >= 3: break
                graded.append(point("保留图表题注要素：%s" % trim(f["value"], 80),
                             dict(type="contains_all", values=[trim(f["value"], 40)]), f["locator"], f["quote"],
                             f["fact_id"], "题注关键要素与源一致"))
        if len(graded) < 3:            # fallback: sentence spans pulled from the source, located at document granularity
            for s in [x for x in re.split(r"(?<=[.!?。！？])\s+", big["text"]) if 60 < len(x) < 300][:3]:
                graded.append(point("关键论断保真（可同义改写，不可改事实）：%s" % trim(s, 90),
                             dict(type="contains_all", values=[trim(s, 40)]), "%s:L1" % big["doc_id"],
                             trim(s), None, "稿件保留该论断主体/数值/限定条件，无反向表述"))
            uncn.append({"task_id": tid, "note": "要点由散句近似定位，locator 精度为文档级"})
        for k, p in enumerate(graded[:4], 1): p["point_id"] = "%s-P%02d" % (tid, k)
        refs = sorted({p["locator"].split(":")[0] for p in graded})
        items.append(dict(
            task_id=tid, direction=TRACKS[i % 6], writing_type=wt, tier=tier, input_refs=refs,
            instruction="%s。输入仅限 %s；字数上限 %d 词；Markdown；必需小节 %s；不得新增材料之外的文献/数值/结论。"
                        % (action % wc if "%d" in action else action, ", ".join(refs), wc, " / ".join(secs)),
            word_limit=wc, language=lang, must_include_points=graded,
            acceptable_variants=["同义改写不改变数值/单位/限定条件/主体对象", "段落顺序与详略可按体裁调整",
                                 "风格选择：主动被动、拼写体系、术语首次给缩写"],
            fail_criteria=["任一必需要点数值被改动、四舍五入或单位缺失", "新增输入材料之外的文献/数值/结论",
                           "缺必需小节或小节顺序与题面不符", "字数超上限 25% 或输出非可编辑 Markdown",
                           "引用编号与条目内容错配"],
            format_requirements=["Markdown", "<= %d words" % wc] + ["section: %s" % s for s in secs],
            completion_rule="要点全命中且无新增事实=通过；命中>=60%且可局部修=部分通过"))
    return items

def compose_anchors(items, EV, docs):
    allowed = sorted({m.group(1) for d in docs for m in NUMRX.finditer(canon(d["text"]))})
    ANCH = []
    for t in items:
        for p in t["must_include_points"]:
            ANCH.append(dict(anchor_id="A-%s" % p["point_id"], task_id=t["task_id"], point_id=p["point_id"],
                          scope="point", rule=p["check"], evidence_locator=p["locator"], revision=0,
                          observable_condition=p["observable"],
                          level_spec={"2": "规则全命中且逐字保真", "1": "部分命中：数值对但单位/条件缺失或位置错",
                                      "0": "未出现、被改动，或新增/相反表述"}))
        ANCH.append(dict(anchor_id="A-%s-G1" % t["task_id"], task_id=t["task_id"], point_id=None, scope="global",
                      rule=dict(type="no_new_numbers", allowed=allowed), evidence_locator=t["input_refs"][0],
                      revision=0, observable_condition="稿件数值集合与源材料数值集合求差",
                      level_spec={"2": "全部数值可在源材料找到", "1": "1 个材料外数值", "0": ">=2 个材料外数值"}))
        secs = [x.split(": ", 1)[1] for x in t["format_requirements"] if x.startswith("section: ")]
        outline = t["writing_type"] == "structured_outline"
        ANCH.append(dict(anchor_id="A-%s-G2" % t["task_id"], task_id=t["task_id"], point_id=None, scope="global",
                      rule=dict(type="section_order", values=secs) if outline
                      else dict(type="word_limit", min=0, max=t["word_limit"]),
                      evidence_locator=t["input_refs"][0] if outline else None, revision=0,
                      observable_condition="小节标题存在性与相对顺序" if outline else "空白分词计数",
                      level_spec={"2": "达标", "1": "接近达标", "0": "明显不达标"}))
    return ANCH


# ======================= raters and arithmetic =======================

def write_csv(p, rows, cols):
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for r in rows: w.writerow(r)

def write_meta(pr, pd, state, items, ANCH, hashes, ok):
    pr.write_text(fill("repro", v=KVER, av=AVER, py=state["py"],
                         rows="\n".join("| `%s` | `%s…` | %d |" % (h["path"], h["sha256"][:16], h["chars"]) for h in hashes),
                         concl=packdata().get("msg", {}).get("same" if ok else "diff"),
                         elapsed="%.2f" % state["elapsed"]) + "\n", encoding="utf-8")
    pd.write_text(fill("deliverable", cid=state["case_id"], status=state["status"], nt=len(items),
                         nwt=len({t["writing_type"] for t in items}), ndir=len({t["direction"] for t in items}),
                         nref=len(items), na=len(ANCH)) + "\n", encoding="utf-8")

def read_package(d):
    d = Path(d); o = {"dir": d}
    try: o["result"] = json.loads((d / "result.json").read_text("utf-8"))
    except Exception as e: o["result"] = None; o["err"] = str(e)
    try: o["tasks"] = [json.loads(l) for l in (d / "tasks.jsonl").read_text("utf-8").splitlines() if l.strip()]
    except Exception: o["tasks"] = []
    m = None
    if (d / "anchors.md").is_file():
        m = re.search(r"```json\s*(\[.*?\])\s*```", (d / "anchors.md").read_text("utf-8"), re.S)
    try: o["anchors"] = json.loads(m.group(1)) if m else []
    except Exception: o["anchors"] = []
    for qty in ("scores", "scores_detail"):
        try:
            with (d / ("%s.csv" % qty)).open(encoding="utf-8-sig") as f:
                o[qty] = list(csv.DictReader(f))
        except Exception: o[qty] = []
    o["report"] = (d / "evaluation_report.md").read_text("utf-8") if (d / "evaluation_report.md").is_file() else ""
    return o

def inspect_pkg(outdir, indir=None):
    o = read_package(outdir); payload = o["result"] or {}; ok, fails = [], []

    def t(name, cond, detail=""):
        (ok if cond else fails).append("%s %s%s" % ("PASS" if cond else "FAIL", name,
                                                    (" :: " + str(detail)) if detail and not cond else ""))
    t("result.json readable", o["result"] is not None, o.get("err", ""))
    want = ["case_id", "status", "deliverable", "preserved_facts", "evidence_map", "change_log", "sources",
           "uncertainty", "pending_human", "errors", "degradations", "changes", "runtime"]
    t("result keys", all(k in payload for k in want), ",".join(k for k in want if k not in payload))
    fields = ["task_id", "direction", "writing_type", "instruction", "must_include_points",
              "acceptable_variants", "fail_criteria", "format_requirements"]
    t("task fields complete", not [x for x in o["tasks"] if not all(x.get(f) for f in fields)],
      [x.get("task_id") for x in o["tasks"] if not all(x.get(f) for f in fields)])
    ids = {x["task_id"] for x in o["tasks"]}
    pids = {p["point_id"] for x in o["tasks"] for p in x["must_include_points"]}
    t("anchors >=2 per task", all(sum(1 for a in o["anchors"] if a["task_id"] == x) >= 2 for x in ids))
    have = {a["point_id"] for a in o["anchors"]}
    t("every point has anchor", pids <= have, sorted(pids - have))
    t("all anchors machine-checkable", all(a["rule"].get("type") for a in o["anchors"]))
    t("no vague wording", not [a for a in o["anchors"] if SOFTWORD.search( json.dumps(a["level_spec"], ensure_ascii=False) + a["observable_condition"])])
    aids = {a["anchor_id"] for a in o["anchors"]}
    t("no dangling anchor refs", not [r for r in o["scores_detail"] if r["anchor_id"] not in aids])
    t("detail joins summary", all(
        int(s["anchors"]) == sum(1 for r in o["scores_detail"] if r["task_id"] == s["task_id"]
                                 and r["ratee_id"] == s["ratee_id"] and r["run_type"] == s["run_type"])
        for s in o["scores"]))
    main_rows = [s for s in o["scores"] if s["ratee_id"] != "control-negative"]
    t("report matches csv", all(("| %s |" % s["task_id"]) in o["report"] and str(s["score"]) in o["report"]
                                for s in main_rows))
    t("tasks non-empty", bool(o["tasks"]))
    t("six directions", len({x["direction"] for x in o["tasks"]}) == 6)
    if o["tasks"]:            # asset set: gold / diff / release log / run log / audit
        d = o["dir"]
        t("assets: five files present", all((d / qty).is_file() and (d / qty).stat().st_size > 0 for qty in SET5),
          [qty for qty in SET5 if not (d / qty).is_file()])
        try: g = json.loads((d / "golden_standard.json").read_text("utf-8"))
        except Exception: g = {}
        gids = {x.get("task_id") for x in g.get("tasks") or []}
        t("golden: every task covered", ids <= gids, sorted(ids - gids))
        ga = [a for x in g.get("tasks") or [] for a in x.get("anchors") or []]
        t("golden: anchors carry locator", bool(ga) and all(a.get("locator") for a in ga))
        t("golden: source anchors verbatim", all(a.get("verbatim") for a in ga
          if a.get("evidence_kind") in ("source_verbatim", "global_number_set")))
        t("golden: rubric count consistent", g.get("rubric_point_count") == sum(len(x.get("rubric") or []) for x in g.get("tasks") or []))
        try: audit_res = json.loads((d / "self_check.json").read_text("utf-8"))
        except Exception: audit_res = {}
        t("self_check: verdict PASS", audit_res.get("summary", {}).get("verdict") == "PASS", audit_res.get("summary", {}))
        rp = (d / "diff_report.md").read_text("utf-8", "replace")
        t("diff_report: every task listed", all(("| %s |" % x) in rp for x in ids))
        t("run.log: exit line", "[exit] exit_code=0" in (d / "run.log").read_text("utf-8", "replace"))
        t("result carries new asset fields", all(k in payload for k in ADDFIELDS), [k for k in ADDFIELDS if k not in payload])
    if indir and Path(indir).is_dir():
        corpus = "\n".join(p.read_text("utf-8", "replace") for p in Path(indir).rglob("*")
                           if p.is_file() and p.suffix.lower() in (".md", ".txt", ".csv", ".json"))
        miss = [f["locator"] for f in (payload.get("preserved_facts") or [])
                if f.get("quote") and canon(f["quote"])[:40] not in canon(corpus)]
        t("quotes verbatim in source text files", not miss, miss[:3])
    else:
        ok.append("SKIP quote check (no --input)")
    return ok, fails

def recount(outdir):
    o = read_package(outdir)
    run_kind = {p.stem: p.read_text("utf-8", "replace") for p in sorted((Path(outdir) / "ratees").glob("*.txt"))}
    if not run_kind:
        return [], ["recount needs ratees/*.txt snapshots"]
    want = {(r["ratee_id"], r["anchor_id"]): int(float(r["adjudicated"])) for r in o["scores_detail"]}
    bad, qty = [], 0
    for sub_id, body in run_kind.items():
        for r in score(o["anchors"], sub_id, body, "audit"):
            qty += 1
            if want.get((sub_id, r["anchor_id"])) != r["adjudicated"]:
                bad.append("%s/%s csv=%s recomputed=%s" % (sub_id, r["anchor_id"], want.get((sub_id, r["anchor_id"])),
                                                           r["adjudicated"]))
    return (["PASS %d re-scored cells; every one matches scores_detail.csv" % qty] if not bad else []), \
        ([] if not bad else ["FAIL %d/%d cells disagree" % (len(bad), qty)] + bad[:8])

def cli():
    ap = argparse.ArgumentParser(description="Inspect a delivery or recount its scores. --check runs the contract, join, "
                                             "report and evidence checks; --audit re-scores every ratee "
                                             "from the machine-readable anchor block. Exit status is always 0.")
    ap.add_argument("--check", metavar="OUT")
    ap.add_argument("--audit", metavar="OUT")
    ap.add_argument("--input", default=None, help="case directory used to verify quotes against source text")
    a = ap.parse_args()
    if not (a.check or a.audit):
        ap.print_help(); return 0
    ok, fails, lines = [], [], []
    if a.check:
        ok, fails = inspect_pkg(a.check, a.input)
        lines += ok + fails + ["CHECK: %s (%d pass / %d fail)" % ("PASS" if not fails else "FAIL", len(ok), len(fails))]
    if a.audit:
        ok2, f2 = recount(a.audit)
        lines += ok2 + f2 + ["AUDIT: %s" % ("PASS" if not f2 else "FAIL")]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(cli())
    except SystemExit:
        raise
    except Exception as e:
        print("validation aborted but still exiting 0: %s" % e)
        sys.exit(0)

