#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作稿层：读取 draft.json 或 Markdown 草稿、逐字核对引文、七要素校验、模板兜底与正文渲染。"""
import json, re
from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "references" / "proposal-skeleton.md"
ELEMENT_IDS = ["background", "problem", "objectives", "methods", "plan", "risks", "outcomes"]

# 渲染
FIELD_ORDER = {"thead.ev": ["ref", "source_id", "locator", "quote", "status"],
          "thead.fact": ["term", "value", "source_id", "locator", "quote"],
          "thead.pend": ["item", "why", "needed_by"],
          "thead.cl": ["action", "target", "reason", "before", "after"]}


def format_cell(o, f):
    v = o.get(f)
    if f in ("quote", "before", "after"):
        return squeeze(v)[:110] or "—"
    if f == "metrics":
        return "；".join("%s（阈值：%s）" % (squeeze(m.get("name")), squeeze(m.get("threshold")))
                        for m in as_list(v) if isinstance(m, dict)) or "（未给出）"
    if f == "evidence" and isinstance(v, list):
        return "%d 条" % len(v)
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, list):
        return ", ".join(squeeze(x) for x in v) or "—"
    return squeeze(v) or "—"

def render_document(draft, ctx, rep, tpl):
    c, fmt_any = rep["counts"], []
    spec, sub_t, covh = template_maps(tpl)
    per, res = draft.get("period") or {}, draft.get("resources") or {}
    fmt_any.append("# %s\n" % (squeeze(draft.get("title")) or "开题报告与研究计划书"))
    fmt_any.append("> v%s｜case_id=%s｜status=%s｜工作稿=%s｜材料 %d｜证据 %d/%d｜%s"
             % (ctx.get("version"), ctx.get("case_id") or "n/a", ctx.get("status"), ctx.get("draft_source"),
                ctx.get("n_materials", 0), c["evidence_verified"], c["evidence_total"], ctx.get("now")))
    fmt_any.append("> 主产物为可编辑 Markdown；`result.json` 原样回填 output_contract。\n")
    fmt_any.append("## 0. 一页速览\n")
    fmt_any.append(md_table(tpl["thead.overview"], [
        ["研究周期", per.get("total") or "材料未给出", per.get("source") or "—"],
        ["研究问题", "%d 条，均含判伪条件" % c["rqs"], "§2"],
        ["七要素", "%d/%d 成节" % (c["sections_present"], c["sections_total"]), "附录 A"],
        ["里程碑", "%d 条（含判据 %d 条）" % (c["milestones"],
                                          sum(1 for m in as_list(draft.get("milestones")) if squeeze(m.get("criterion")))), "§5.2"],
        ["风险", "%d 条 / %d 类" % (c["risks"], c["risk_types"]), "§6"],
        ["证据", "%d/%d 逐字命中" % (c["evidence_verified"], c["evidence_total"]), "附录 B"]]))
    secs = {str(x.get("id")).lower(): x for x in as_list(draft.get("sections")) if isinstance(x, dict)}
    for eid in ELEMENT_IDS:
        fmt_any.append("\n## %s\n" % ctx["titles"].get(eid, eid))
        fmt_any.append((section_plain(secs.get(eid)) or "（缺内容，见附录D）") + "\n")
        for i, (th, key, fields) in enumerate(spec.get(eid, [])):
            if (eid, i) in sub_t:
                fmt_any.append("\n**%s**\n" % sub_t[(eid, i)])
            items = ([{"period": per.get("total"), "budget": res.get("budget"), "people": res.get("people"),
                       "data": res.get("data")}] if key == "__res__"
                     else [o for o in as_list(draft.get(key)) if isinstance(o, dict)])
            fmt_any.append(md_table(tpl[th], [[format_cell(o, f) for f in fields.split(",")] for o in items]))
    cov = rep["coverage"]
    fmt_any.append("\n## 附录 A：七要素覆盖矩阵\n")
    fmt_any.append(md_table(tpl["thead.cov"], [[ctx["titles"].get(e, e), "是" if cov[e]["present"] else "否",
                                       str(cov[e]["chars"]), str(cov[e]["evidence"]), covh.get(e, "—")] for e in ELEMENT_IDS]))
    evs = [{"ref": e.get("ref"), "source_id": e.get("source_id"), "locator": e.get("found_locator") or e.get("locator"),
            "quote": e.get("quote"), "status": e.get("status")} for e in rep["evidence"]]
    for title, th, items in (
            ("B：证据映射", "thead.ev", evs),
            ("C：事实保留", "thead.fact", [x for x in as_list(draft.get("preserved_facts")) if isinstance(x, dict)]),
            ("D：待确认与缺口", "thead.pend", [x for x in as_list(draft.get("pending_human")) if isinstance(x, dict)] + rep["gaps"])):
        fmt_any.append("\n## 附录 %s\n" % title)
        fmt_any.append(md_table(tpl[th], [[format_cell(o, f) for f in FIELD_ORDER[th]] for o in items], empty="（无）"))
    if rep["errors"] or rep["warnings"]:
        fmt_any.append("\n## 附录 E：自检结果\n")
        fmt_any.append(md_table(tpl["thead.diag"], [["错误", e] for e in rep["errors"]] + [["提醒", w] for w in rep["warnings"]]))
    fmt_any.append("\n## 附录 F：变更记录\n")
    fmt_any.append(md_table(tpl["thead.cl"], [[format_cell(x, f) for f in FIELD_ORDER["thead.cl"]]
                                     for x in as_list(draft.get("change_log")) if isinstance(x, dict)]))
    return "\n".join(fmt_any).rstrip() + "\n"


def inspect_draft(draft, index):
    errs, warns, gaps, cov = [], [], [], {}
    secs = {str(s.get("id")).lower(): s for s in as_list(draft.get("sections")) if isinstance(s, dict) and s.get("id")}
    for eid in ELEMENT_IDS:
        txt = section_plain(secs.get(eid))
        cov[eid] = {"present": eid in secs, "chars": len(txt), "evidence": len(collect_evidence(secs.get(eid) or {}))}
        if eid not in secs:
            errs.append("缺少要素：" + eid)
        elif len(txt) < 60:
            warns.append("要素内容过短：" + eid)
    rq_rows = [r for r in as_list(draft.get("rqs") or draft.get("research_questions")) if isinstance(r, dict)]
    if not rq_rows:
        errs.append("没有研究问题（rqs）")
    for i, r in enumerate(rq_rows, 1):
        rq_id_set = r.get("id") or "RQ%d" % i
        errs += ["%s 缺 %s" % (rq_id_set, f) for f in ("question", "falsifier") if not squeeze(r.get(f))]
        ms = [m for m in as_list(r.get("metrics")) if isinstance(m, dict)]
        if not ms:
            errs.append("%s 无指标" % rq_id_set)
        errs += ["%s 指标缺阈值" % rq_id_set for m in ms if not squeeze(m.get("threshold"))]
        warns += ["%s 阈值缺依据" % rq_id_set for m in ms
                  if squeeze(m.get("threshold")) and not (squeeze(m.get("basis")) or squeeze(m.get("basis_locator")))]
    objs = [o for o in as_list(draft.get("objectives")) if isinstance(o, dict)]
    steps = [s for s in as_list(draft.get("steps")) if isinstance(s, dict)]
    ms = [m for m in as_list(draft.get("milestones")) if isinstance(m, dict)]
    risks = [r for r in as_list(draft.get("risks")) if isinstance(r, dict)]
    outs = [o for o in as_list(draft.get("outcomes")) if isinstance(o, dict)]
    types = {squeeze(r.get("type")) for r in risks if squeeze(r.get("type"))}
    for cond, msg in ((not objs, "没有研究目标"), (len(ms) < 3, "里程碑少于 3 条"), (len(risks) < 4, "风险少于 4 条"),
                      (not outs, "没有预期成果")):
        if cond:
            errs.append(msg)
    if len(steps) < 3:
        warns.append("路线步骤少于 3 条")
    if len(types) < 3:
        warns.append("风险类型少于 3 类")
    errs += ["风险 %s 缺触发信号/备选" % r.get("id") for r in risks if not (squeeze(r.get("trigger")) and squeeze(r.get("fallback")))]
    warns += ["步骤 %s 缺 output" % s.get("id") for s in steps if not squeeze(s.get("output"))]
    warns += ["里程碑 %s 缺完成判据" % m.get("id") for m in ms if not squeeze(m.get("criterion"))]
    warns += ["成果 %s 缺验证方式" % o.get("id") for o in outs if not squeeze(o.get("verification"))]
    dstr = json.dumps(draft, ensure_ascii=False)
    per = squeeze((draft.get("period") or {}).get("total"))
    pk = [int(x) for x in re.findall(r"\d{1,2}\s*[–\-~至]\s*(\d{1,2})\s*月", dstr)] or \
         [int(x) for x in re.findall(r"第\s*(\d{1,2})\s*月", dstr)]
    mo = re.search(r"\d+", per)
    if pk and mo and max(pk) > int(mo.group(0)):
        errs.append("里程碑超周期：第 %d 月 > %s" % (max(pk), per))
    allmat = " ".join(squeeze(m.get("text")).lower() for m in index.get("materials", []))
    stray_numbers = []
    for mm in re.finditer(r"\d+(?:\.\d+)?\s*(?:%|个月|月|年|例|人|次|万元|天|周)", dstr):
        v = mm.group(0).strip()
        if v.lower() not in allmat and v not in stray_numbers:
            stray_numbers.append(v)
    if stray_numbers:
        warns.append("数字无材料同形文本（标计划值或补依据）：" + "、".join(stray_numbers[:8]))
    ev, bad = audit_quotes(collect_evidence(draft), index)
    warns += ["引文未命中 %s: %s" % (b.get("source_id") or "?", squeeze(b.get("quote"))[:40]) for b in bad[:5]]
    if bad:
        gaps.append({"item": "%d 条引文未命中" % len(bad), "why": "quote 改写/跨段", "needed_by": "成稿前"})
    return {"errors": errs, "warnings": warns, "coverage": cov, "evidence": ev, "gaps": gaps,
            "counts": {"sections_present": sum(1 for v in cov.values() if v["present"]), "sections_total": len(ELEMENT_IDS),
                       "rqs": len(rq_rows), "objectives": len(objs), "steps": len(steps), "milestones": len(ms),
                       "risks": len(risks), "risk_types": len(types), "outcomes": len(outs),
                       "evidence_total": len(ev),
                       "evidence_verified": sum(1 for e in ev if str(e.get("status", "")).startswith("verified"))}}


def squeeze(s):
    return re.sub(r"[\s\u3000]+", " ", str(s if s is not None else "").replace("\ufeff", "")).strip()

def as_list(v):
    return [] if v is None else (v if isinstance(v, list) else [v])

def split_paras(text, cap=1400):
    out = []
    for b in [x.strip() for x in re.split(r"\n\s*\n", str(text or "").replace("\r\n", "\n"))]:
        while len(b) > cap:
            cut = b.rfind("\n", 0, cap)
            cut = cut if cut > 200 else cap
            out.append(b[:cut].strip())
            b = b[cut:].strip()
        if b:
            out.append(b)
    return out or ([squeeze(text)] if squeeze(text) else [])


def detect_period(text):
    kw = re.compile(r"周期|执行期|研究期|总工期|工期|计划期|duration|period|期限", re.I)
    for line in str(text or "").split("\n"):
        m = re.search(r"(\d{1,2}(?:\.\d)?)\s*(个月|月|months?|years?|年|周|weeks?)", line, re.I) if kw.search(line) else None
        if m:
            x, u = float(m.group(1)), m.group(2).lower()
            mo = x * 12 if u in ("年", "year", "years") else (x / 4.345 if u in ("周", "week", "weeks") else x)
            return max(1, int(round(mo))), squeeze(line)[:200]
    return None, ""


def md_table(head, rows, empty="（无）"):
    if not rows:
        return empty + "\n"
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    out += ["| " + " | ".join(squeeze(x).replace("|", "\\|") for x in r) + " |" for r in rows]
    return "\n".join(out) + "\n"

def read_template(path=None):
    p = Path(path or TEMPLATE_PATH)
    raw = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    blocks, cur = {}, None
    for line in raw.split("\n"):
        m = re.match(r"^\s*<!--\s*KEY:([\w.\-]+)\s*-->\s*$", line)
        if m:
            cur = m.group(1); blocks[cur] = []; continue
        if cur is not None:
            blocks[cur].append(line)
    tpl = {}
    for k, lines in blocks.items():
        body = [l.strip() for l in lines if l.strip()]
        if k.startswith("thead."):
            tpl[k] = [c.strip() for c in body[0].strip().strip("|").split("|")] if body else ["—"]
        elif k.startswith("rows."):
            tpl[k] = [[c.strip() for c in l.strip().strip("|").split("|")] for l in body]
        elif k.startswith(("spec.", "subtitle", "covhint")):
            tpl[k] = body
        else:
            tpl[k] = "\n".join(body)
    return tpl

def template_maps(tpl):
    """spec: eid -> [[thead,item,fields]]; sub: (eid,i) -> 小标题; cov: eid -> 判据提示。"""
    sp = {k[5:]: [x.split("|") for x in v] for k, v in tpl.items() if k.startswith("spec.")}
    fill_slots = {(x[0], int(x[1])): x[2] for x in (l.split("|") for l in tpl.get("subtitle", [])) if len(x) > 2}
    return sp, fill_slots, {x[0]: x[1] for x in (l.split("|") for l in tpl.get("covhint", [])) if len(x) > 1}

def fill_slots(s, kv):
    try:
        return str(s).format(**kv)
    except Exception:
        return str(s)

def section_plain(sec):
    if not isinstance(sec, dict):
        return ""
    parts = [squeeze(b.get("text")) if isinstance(b, dict) else squeeze(b) for b in as_list(sec.get("blocks"))]
    return "\n".join(x for x in parts if x) or squeeze(sec.get("text"))

SECTION_HINTS = {"background": ["背景", "缺口", "background", "意义"], "problem": ["问题", "假设", "problem", "可证伪"],
                "objectives": ["目标", "objective", "aim"], "methods": ["方法", "路线", "method", "approach"],
                "plan": ["计划", "工期", "进度", "timeline", "里程碑", "安排"], "risks": ["风险", "risk", "备选"],
                "outcomes": ["成果", "outcome", "output", "预期"]}

def draft_from_markdown(text):
    secs, cur = {}, None
    for line in str(text).split("\n"):
        h = re.match(r"^\s{0,3}#{1,4}\s*(.+?)\s*$", line)
        if h:
            low = h.group(1).lower()
            cur = next((e for e, kws in SECTION_HINTS.items() if e in low or any(k in low for k in kws)), None)
            if cur:
                secs.setdefault(cur, [])
            continue
        if cur:
            secs[cur].append(line)
    return {"sections": [{"id": k, "blocks": [{"text": "\n".join(v).strip(), "evidence": []}]}
                         for k, v in secs.items() if "\n".join(v).strip()]}

def read_draft(work):
    for name in ("draft.json", "proposal_draft.json", "draft.md"):
        p = Path(work) / name
        if not p.is_file():
            continue
        try:
            txt = p.read_text(encoding="utf-8-sig", errors="replace")
        except Exception as e:
            return {}, str(p), "unreadable: %s" % e
        if not name.endswith(".json"):
            return draft_from_markdown(txt), str(p), None
        try:
            obj = json.loads(txt.lstrip("\ufeff"))
            return (obj, str(p), None) if isinstance(obj, dict) else ({}, str(p), "draft.json 顶层不是对象")
        except Exception as e:
            return draft_from_markdown(txt), str(p), "json_invalid: %s" % e
    return {}, None, "未找到工作稿（%s）" % work

def locate_quote(index, sid, quote):
    q = squeeze(quote).lower()
    if len(q) < 6:
        return None
    mats = index.get("materials") or []
    for m in [x for x in mats if x.get("id") == sid] + [x for x in mats if x.get("id") != sid]:
        for pa in m.get("paras", []):
            if q in squeeze(pa.get("text")).lower():
                return m["id"], pa["loc"], "exact"
        if q in squeeze(m.get("text")).lower():
            return m["id"], "body", "loose"
    return None

def iter_dicts(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from iter_dicts(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_dicts(v)

def collect_evidence(draft):
    rows = []
    for d in iter_dicts(draft):
        ev = d.get("evidence")
        if isinstance(ev, list):
            rows += [{"ref": str(d.get("id") or d.get("name") or ""), "source_id": e.get("source_id"),
                      "locator": e.get("locator"), "quote": e.get("quote")} for e in ev if isinstance(e, dict)]
    return rows

def audit_quotes(rows, index):
    out, bad = [], []
    for r in rows:
        hit = locate_quote(index, r.get("source_id"), r.get("quote"))
        row = dict(r, status="verified", source_id=hit[0], found_locator=hit[1], match=hit[2]) if hit \
            else dict(r, status="quote_not_found")
        if not hit:
            bad.append(row)
        out.append(row)
    return out, bad

def pick_seed_paragraphs(index, limit=10):
    """挑可读段落做兜底素材（长句优先，跳过标题行）。"""
    rows = [(m["id"], pa["loc"], squeeze(pa.get("text"))) for m in index.get("materials", [])
            for pa in m.get("paras", []) if len(squeeze(pa.get("text"))) >= 40
            and not re.match(r"^[#>|*\-{]", squeeze(pa.get("text")))]
    rows.sort(key=lambda r: -min(len(r[2]), 600))
    return [{"source_id": r[0], "locator": r[1], "text": r[2]} for r in rows[:limit]]

def harvest_facts(index, pat, limit=10):
    out, seen = [], set()
    for m in index.get("materials", []):
        for pa in m.get("paras", []):
            t = squeeze(pa.get("text"))
            for mm in pat.finditer(t):
                v = mm.group(0).strip()
                if v.lower() not in seen:
                    seen.add(v.lower())
                    out.append({"term": v, "value": v, "source_id": m["id"], "locator": pa["loc"],
                                "quote": t[max(0, mm.start() - 20): mm.end() + 10][:120]})
                    if len(out) >= limit:
                        return out
    return out


def month_slots(mo):
    kv = {"months": mo, "end": mo, "q1": max(1, mo // 4), "h": max(2, mo // 2), "p80": max(3, int(mo * 0.8))}
    kv.update(q1a=kv["q1"] + 1, h1=kv["h"] + 1, p80a=kv["p80"] + 1)
    return kv

def template_draft(ctx, tpl):
    mo, kv, seeds = int(ctx.get("months") or 12), month_slots(int(ctx.get("months") or 12)), ctx.get("seeds") or []
    ev = lambda rows: [{"source_id": r["source_id"], "locator": r["locator"], "quote": r["text"][:220]} for r in rows]
    bg = fill_slots(tpl.get("fb.bg_preface", ""), kv) + "\n" + (
        "\n".join("- （%s/%s）%s" % (r["source_id"], r["locator"], r["text"][:240]) for r in seeds[:4])
        if seeds else tpl.get("fb.bg_empty", ""))
    d = {"case_id": ctx.get("case_id"), "degraded": True,
         "title": (ctx.get("title") or "开题报告与研究计划书") + tpl.get("fb.title_suffix", ""),
         "period": {"total": "%d 个月" % mo, "quote": ctx.get("period_quote") or "",
                    "source": "materials" if ctx.get("period_quote") else "default_12m"},
         "rqs": [{"id": "RQ1", "question": fill_slots(tpl.get("fb.rq_question", ""), kv),
                  "hypothesis": seeds[0]["text"][:180] if seeds else tpl.get("fb.rq_hyp_fallback", ""),
                  "falsifier": fill_slots(tpl.get("fb.rq_falsifier", ""), kv),
                  "metrics": [{"name": tpl.get("fb.metric_name", ""), "threshold": tpl.get("fb.metric_threshold", ""),
                               "basis": "pending_human"}],
                  "sample": tpl.get("fb.sample", ""), "condition": tpl.get("fb.condition", ""),
                  "timepoint": fill_slots(tpl.get("fb.timepoint", ""), kv), "evidence": ev(seeds[:1])}],
         "sections": [{"id": "background", "blocks": [{"text": bg, "evidence": ev(seeds[:2])}]}],
         "resources": {"budget": tpl.get("fb.res_na", ""), "people": tpl.get("fb.res_na", ""),
                       "data": "见材料清单", "note": tpl.get("fb.res_note", "")},
         "preserved_facts": ctx.get("facts") or [], "pending_human": [],
         "change_log": [{"action": "脚本兜底生成初稿", "target": "proposal.md", "reason": "无可用 Agent 工作稿",
                         "before": "—", "after": "七要素骨架 + 材料证据"}]}
    evmap = {"problem": ev(seeds[1:3]), "methods": ev(seeds[2:4]),
             "plan": [{"source_id": "constraints", "locator": "detected", "quote": ctx["period_quote"]}]
             if ctx.get("period_quote") else []}
    for eid, k in (("problem", "fb.s.problem"), ("objectives", "fb.s.objectives"), ("methods", "fb.s.methods"),
                   ("plan", "fb.s.plan"), ("risks", "fb.s.risks"), ("outcomes", "fb.s.outcomes")):
        d["sections"].append({"id": eid, "blocks": [{"text": fill_slots(tpl.get(k, ""), kv), "evidence": evmap.get(eid, [])}]})
    for it in [y.split("|") for e in ("objectives", "methods", "plan", "risks", "outcomes")
               for y in tpl.get("spec." + e, []) if y.split("|")[1] != "__res__"]:
        f = it[2].split(",")
        d[it[1]] = [dict(zip(f, ([fill_slots(x, kv) for x in r] + ["—"] * len(f))[:len(f)])) for r in tpl.get("rows." + it[1], [])]
    for s in d["steps"]:
        s["depends_on"] = [] if s["depends_on"] in ("—", "") else [s["depends_on"]]
    for m in d["milestones"]:
        m["critical_path"] = str(m["critical_path"]) in ("1", "是", "True")
    return d

# 校验
 
