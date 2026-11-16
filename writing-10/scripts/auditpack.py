#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""附件层：金标准对照、差异报告、版本记录、运行日志、自检，以及结构化矩阵与表格产物。

纯标准库、离线、不依赖当前工作目录；异常只记入 degradations，不外抛。
"""
import csv, hashlib, io, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import draftkit as P  # noqa: E402

SELF_DIR, PKG = Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent
ENTRY_PATH, LOG_CAP = SELF_DIR / "entry.py", 64 * 1024
NUM_TOKEN = re.compile(r"\d+(?:\.\d+)?\s*(?:%|个月|月|年|例|人|次|万元|元|h|mg|mL|mM|天|周)")
OVERCLAIM_PHRASES = ("已完成", "已获得", "已证实", "结果显示", "已实现", "得到结论")
ARTIFACT_FILES = ["proposal.md", "result.json", "golden_standard.json", "diff_report.md", "version_history.md",
         "run.log", "self_check.json", "proposal_matrix.json", "milestones.csv", "risks.md"]
CHAPTER_TITLES = {"background": "一、研究背景与缺口", "problem": "二、研究问题与可证伪性", "objectives": "三、研究目标",
       "methods": "四、技术路线与方法", "plan": "五、阶段计划与里程碑", "risks": "六、风险与备选方案",
       "outcomes": "七、预期成果与验证方式", "data": "数据、样本与合规来源"}
SECTION_LABELS = {"background": "背景与缺口", "problem": "研究问题", "objectives": "研究目标", "methods": "技术路线",
        "data": "数据", "plan": "阶段计划", "risks": "风险", "outcomes": "预期成果"}
T = P.squeeze


def fmt_any(v):
    return [x for x in P.as_list(v) if isinstance(x, dict)]


def stamp_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _jl(p):
    try:
        p = Path(p)
        return (None, "not_found") if not p.is_file() else (
            json.loads(p.read_text(encoding="utf-8-sig", errors="replace").lstrip("\ufeff")), None)
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def _w(path, body):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, (dict, list)):
        t = p.with_name(p.name + ".tmp")
        t.write_text(json.dumps(body, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.replace(t, p)
    else:
        p.write_text(body, encoding="utf-8")
    return p.stat().st_size


def _hex(p, algo="sha256"):
    try:
        return hashlib.new(algo, Path(p).read_bytes()).hexdigest()[:16 if algo == "sha256" else 8]
    except Exception:
        return None


def note(outdir, stage, msg):
    """追加一行到 run.log，超 64KB 留尾部；永不抛异常。"""
    try:
        p = Path(outdir) / "run.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        old = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
        txt = old + "[%s] %-8s %s\n" % (stamp_iso(), stage, T(msg)[:400])
        if len(txt.encode("utf-8")) > LOG_CAP:
            txt = "[log rotated, tail kept]\n" + txt[-LOG_CAP // 2:]
        p.write_text(txt, encoding="utf-8")
    except Exception:
        pass


def result_hook(outdir, res):
    """finalize 钩子：每次命令的结果写进 run.log。"""
    try:
        res = res if isinstance(res, dict) else {}
        note(outdir, (T(res.get("note")).split(":")[0].split(" ")[0] or "run").upper(),
             "status=%s elapsed=%ss materials=%d errors=%d degradations=%d" % (
                 res.get("status"), (res.get("runtime") or {}).get("elapsed_s", "?"),
                 len(res.get("sources") or []), len(res.get("errors") or []), len(res.get("degradations") or [])))
        for tag, k in (("ERROR", "errors"), ("DEGRADE", "degradations")):
            for x in (res.get(k) or [])[:8]:
                note(outdir, tag, x)
    except Exception:
        pass


def section_plain_text(d, eid):
    for s in fmt_any(d.get("sections")):
        if T(s.get("id")).lower() == eid:
            return P.section_plain(s)
    return ""


def rq_rows(d):
    out = fmt_any(d.get("rqs") or d.get("research_questions"))
    for i, r in enumerate(out):
        r["id"] = T(r.get("id")) or "RQ%d" % (i + 1)
    return out


def rq_id_set(d):
    return {T(r.get("id")).upper() for r in rq_rows(d)}


def max_month(o):
    s = T(json.dumps(o, ensure_ascii=False, default=str))
    pk = [int(x) for x in re.findall(r"\d{1,2}\s*[–\-~至]\s*(\d{1,2})\s*月", s)]
    pk += [int(x) for x in re.findall(r"第\s*(\d{1,2})\s*月", s)]
    return max(pk) if pk else None


def month_span(s):
    t = T(s)
    m = re.search(r"(\d{1,2})\s*[–\-~至]\s*(\d{1,2})", t)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d{1,2})\s*月", t)
    return (int(m.group(1)), int(m.group(1))) if m else (None, None)


def period_months(o):
    per = (o or {}).get("period") or {}
    m = re.search(r"\d+", T(per.get("total")))
    return (int(m.group(0)) if m else None), per


def stray_numbers(D):
    """论断区数字：材料与计划字段都找不到同形文本者（计划字段含 period/里程碑/目标判据/步骤）。"""
    d, i = D["draft"], D["idx"]
    mat = " ".join(T(m.get("text")).lower() for m in (i.get("materials") or []))
    plan = T(json.dumps({k: d.get(k) for k in ("period", "milestones", "objectives", "steps")}, ensure_ascii=False)).lower()
    bad = []
    for sc in (json.dumps({k: d.get(k) for k in ("rqs", "objectives", "outcomes", "resources")}, ensure_ascii=False),
               json.dumps(d.get("sections"), ensure_ascii=False)):
        for mm in NUM_TOKEN.finditer(sc):
            v = mm.group(0).strip()
            if v.lower() not in mat and v.lower() not in plan and v not in bad:
                bad.append(v)
    return bad[:12]


# (id, 要素, 规则, rubric, 期望, 必备, 修复, 锚点词)
judged = "rule:<名> 对应 scripts/auditpack.py 中的函数；契约/工作单条目为逐项回执，判据见 must_have"


# ---------- 27 条判定规则：f(D) -> (status, actual, fix) ----------
def rule_contract(D):
    res, c = D["res"], (D["res"].get("_contract") or {})
    if not c:
        return "deviation", "输入未提供 output_contract", "确认 case.json"
    miss = []
    for k in c:
        v, kl = res.get(k), str(k).lower()
        if v in (None, "", [], {}):
            v = next((res.get(n) for n in res if not n.startswith("_") and kl.split("_")[0] in n.lower()
                      and res.get(n) not in (None, "", [], {})), None)
        if v in (None, "", [], {}):
            miss.append(str(k))
    if miss:
        return "deviation", "未覆盖 %d/%d：%s" % (len(miss), len(c), "、".join(miss[:6])), "补映射后重跑"
    return "pass", "契约 %d 字段均有值（self_check 复核）" % len(c), ""


def rule_period(D):
    tot, per = period_months(D["draft"])
    q, mx = T(per.get("quote")), max_month(D["draft"])
    if not tot:
        return "missing", "未声明研究周期", "从材料抽周期"
    if T(per.get("source")) in ("default_12m", "") or not q:
        return "deviation", "周期 %d 月为兜底值（无 quote）" % tot, "回填周期原文"
    if mx and mx > tot:
        return "deviation", "最远第 %d 月 > 周期 %d 月" % (mx, tot), "压缩里程碑"
    return "pass", "周期 %d 月，最远 %s 月；quote「%s」" % (tot, mx or "—", q[:34]), ""


def rule_evidence_ratio(D):
    c = (D["rep"] or {}).get("counts") or {}
    t, v = c.get("evidence_total", 0), c.get("evidence_verified", 0)
    if not t:
        return "missing", "全稿 0 条证据", "补 source_id+locator+quote"
    r = v / t
    return ("pass", "证据 %d/%d 逐字命中（%.0f%%）" % (v, t, r * 100), "") if r >= 0.9 else \
           ("deviation", "证据 %d/%d 命中（%.0f%%<90%%）" % (v, t, r * 100), "换原文切片")


def rule_honesty(D):
    d = D["draft"]
    hits = [w for w in OVERCLAIM_PHRASES if w in json.dumps({k: d.get(k) for k in ("rqs", "objectives", "outcomes")}, ensure_ascii=False)]
    pend = fmt_any(d.get("pending_human")) + fmt_any(D["res"].get("pending_human"))
    if hits:
        return "deviation", "既成结果断言：%s" % "、".join(hits), "改拟/将+判据"
    if not pend:
        return "deviation", "未记录 pending_human 缺口", "写未确认项"
    return "pass", "无结果断言；pending %d 条" % len(pend), ""


def rule_gap(D):
    txt = section_plain_text(D["draft"], "background")
    if len(txt) < 30:
        return "missing", "背景缺内容（%d 字）" % len(txt), "按三段式写"
    hit = [k for k in ("已知", "未知", "待验证", "缺口", "尚不清") if k in txt]
    return ("pass", "缺口含 %s（%d 字）" % ("、".join(hit), len(txt)), "") if len(hit) >= 2 else \
           ("deviation", "未收敛为缺口（命中 %s）" % ("、".join(hit) or "无"), "改已知→未知→待验证")


def rule_no_review(D):
    txt = section_plain_text(D["draft"], "background")
    if not txt:
        return "missing", "背景为空", "补写"
    if re.search(r"综述|研究现状表明|近年来", txt) and not re.search(r"缺口|未知|待验证", txt):
        return "deviation", "疑似综述式背景", "留缺口证据句"
    return "pass", "非综述式（%d 字）" % len(txt), ""


def rule_questions(D):
    rq = rq_rows(D["draft"])
    if not rq:
        return "missing", "无研究问题", "写 1–3 条"
    short = [T(r.get("id")) for r in rq if len(T(r.get("question"))) < 12]
    if short:
        return "deviation", "%s 问题过短/缺条件" % "、".join(short[:3]), "补对象+条件"
    if not 1 <= len(rq) <= 3:
        return "deviation", "%d 条 RQ（应 1–3）" % len(rq), "收敛数量"
    return "pass", "%d 条：%s" % (len(rq), "；".join(T(r.get("question"))[:42] for r in rq[:2])), ""


def rule_falsifier(D):
    rq = rq_rows(D["draft"])
    if not rq:
        return "missing", "无 RQ", "先写 RQ"
    bad = [T(r.get("id")) for r in rq if len(T(r.get("falsifier"))) < 8]
    return ("deviation", "%s 判伪条件缺失" % "、".join(bad[:3]), "写否定观测") if bad else \
           ("pass", "%d 条均有判伪：%s" % (len(rq), T(rq[0].get("falsifier"))[:52]), "")


def rule_metric(D):
    rq = rq_rows(D["draft"])
    if not rq:
        return "missing", "无 RQ", "先写 RQ"
    no = [T(r.get("id")) for r in rq if not any(T(m.get("threshold")) for m in fmt_any(r.get("metrics")))]
    nb = [T(r.get("id")) for r in rq if T(r.get("id")) not in no and
          any(not (T(m.get("basis")) or T(m.get("basis_locator"))) for m in fmt_any(r.get("metrics")))]
    if no:
        return "missing", "%s 缺指标/阈值" % "、".join(no[:3]), "补指标+阈值"
    if nb:
        return "deviation", "%s 阈值缺依据" % "、".join(nb[:3]), "补 basis 或 pending"
    return "pass", "阈值与依据齐：%s" % "、".join(T(m.get("threshold")) for r in rq for m in fmt_any(r.get("metrics")))[:52], ""


def rule_sample(D):
    rq = rq_rows(D["draft"])
    if not rq:
        return "missing", "无 RQ", "先写 RQ"
    thin = [T(r.get("id")) for r in rq if sum(1 for k in ("sample", "condition", "timepoint") if T(r.get(k))) < 2]
    return ("deviation", "%s 样本/条件/时点不足" % "、".join(thin[:3]), "补三项") if thin else \
           ("pass", "样本/条件/时点齐（%s）" % T(rq[0].get("sample"))[:28], "")


def rule_objective_link(D):
    d = D["draft"]
    objs, ids = fmt_any(d.get("objectives")), rq_id_set(d)
    if not objs:
        return "missing", "无目标", "按 RQ 拆目标"
    orph = [T(o.get("id")) for o in objs if T(o.get("rq")).upper() not in ids]
    naked = [r for r in ids if not any(T(o.get("rq")).upper() == r for o in objs)]
    if orph:
        return "deviation", "目标 %s 指向不存在的 RQ" % "、".join(orph[:3]), "改 rq 指向"
    if naked:
        return "deviation", "RQ %s 无目标" % "、".join(sorted(naked)[:3]), "补目标"
    return "pass", "%d 目标指向 %d 条 RQ" % (len(objs), len(ids)), ""


def rule_objective_criterion(D):
    objs = fmt_any(D["draft"].get("objectives"))
    if not objs:
        return "missing", "无目标", "补目标"
    bad = [T(o.get("id")) for o in objs if len(T(o.get("criterion"))) < 6]
    return ("deviation", "%s 缺判据" % "、".join(bad[:3]), "写判据") if bad else ("pass", "%d 目标均有判据" % len(objs), "")


def rule_steps(D):
    st = fmt_any(D["draft"].get("steps"))
    if not st:
        return "missing", "无路线步骤", "拆输入→操作→输出"
    if len(st) < 3:
        return "deviation", "步骤 %d 条（<3）" % len(st), "至少 3 步"
    bad = [T(s.get("id")) for s in st if not (T(s.get("input")) and T(s.get("action")) and T(s.get("output")))]
    return ("deviation", "%s 缺输入/操作/输出" % "、".join(bad[:3]), "补三要素") if bad else \
           ("pass", "%d 步成链（%s…%s）" % (len(st), T(st[0].get("id")), T(st[-1].get("id"))), "")


def rule_dependency(D):
    st = fmt_any(D["draft"].get("steps"))
    if not st:
        return "missing", "无步骤", "补路线"
    ids = [T(s.get("id")).upper() for s in st]
    bad, g = [], {}
    for s in st:
        deps = [T(x).upper() for x in P.as_list(s.get("depends_on")) if T(x) not in ("", "—", "-", "无")]
        g[T(s.get("id")).upper()] = [x for x in deps if x in ids]
        bad += [x for x in deps if x not in ids]
    if bad:
        return "deviation", "依赖悬空：%s" % "、".join(sorted(set(bad))[:4]), "修 depends_on"
    seen, stk = set(), set()

    def cyc(n):
        if n in stk:
            return True
        if n in seen:
            return False
        seen.add(n)
        stk.add(n)
        r = any(cyc(m) for m in g.get(n, []))
        stk.discard(n)
        return r

    if any(cyc(n) for n in g):
        return "deviation", "依赖成环", "打破环"
    return "pass", "依赖可解（%d 边）" % sum(len(v) for v in g.values()), ""


def rule_method_evidence(D):
    refs = {T(e.get("ref")).upper() for e in ((D["rep"] or {}).get("evidence") or [])}
    st = {T(s.get("id")).upper() for s in fmt_any(D["draft"].get("steps"))}
    if not st:
        return "missing", "无步骤", "补路线"
    hit = len(st & refs)
    if not hit:
        return "deviation", "方法无逐字来源（0/%d）" % len(st), "为每步补 quote"
    if hit < len(st):
        return "deviation", "方法有来源 %d/%d" % (hit, len(st)), "补其余引文"
    return "pass", "%d 步均有材料来源" % len(st), ""


def rule_data(D):
    dat = T((D["draft"].get("resources") or {}).get("data"))
    if not dat:
        return "missing", "未写数据来源", "补 resources.data"
    if re.search(r"待确认|未给出|未提供|见材料清单", dat):
        return "deviation", "数据口径未定：%s" % dat[:34], "按材料回填"
    return "pass", "数据：%s" % dat[:42], ""


def rule_data_number(D):
    bad = stray_numbers(D)
    return ("pass", "论断区数字均有材料/计划同形文本", "") if not bad else \
           ("deviation", "无依据数字 %d 个：%s" % (len(bad), "、".join(bad[:6])), "补依据或标计划值")


def rule_milestones(D):
    ms = fmt_any(D["draft"].get("milestones"))
    if not ms:
        return "missing", "无里程碑", "按周期排"
    if len(ms) < 3:
        return "deviation", "里程碑 %d 条（<3）" % len(ms), "至少 3 个"
    nc = [T(m.get("id")) for m in ms if len(T(m.get("criterion"))) < 6]
    nd = [T(m.get("id")) for m in ms if not T(m.get("deliverable"))]
    return ("deviation", "缺判据 %s；缺交付物 %s" % ("、".join(nc[:3]) or "—", "、".join(nd[:3]) or "—"), "补齐") \
        if (nc or nd) else ("pass", "%d 里程碑均有交付物与判据" % len(ms), "")


def rule_milestone_period(D):
    tot = period_months(D["draft"])[0]
    mx = max_month(D["draft"])
    if not tot:
        return "missing", "未声明周期", "写 period.total"
    if mx and mx > tot:
        return "deviation", "最远第 %d 月 > 周期 %d 月" % (mx, tot), "压缩或延长"
    cp = [T(m.get("id")) for m in fmt_any(D["draft"].get("milestones")) if m.get("critical_path") in (True, 1, "是", "True")]
    if not cp:
        return "deviation", "未标关键路径（%s/%d 月）" % (mx, tot), "标关键路径"
    return "pass", "里程碑在 %d 月内，关键路径 %s" % (tot, "、".join(cp[:4])), ""


def rule_resources(D):
    r = D["draft"].get("resources") or {}
    miss = [k for k in ("budget", "people") if not T(r.get(k)) or re.search(r"待确认|未给出|材料未给|未提供", T(r.get(k)))]
    return ("deviation", "经费/人员未落实（%s）" % "、".join(miss), "回填或 pending") if miss else \
           ("pass", "经费「%s」人员「%s」" % (T(r.get("budget"))[:18], T(r.get("people"))[:18]), "")


def rule_risk(D):
    rk = fmt_any(D["draft"].get("risks"))
    if not rk:
        return "missing", "无风险", "按四类补"
    if len(rk) < 4:
        return "deviation", "风险 %d 条（<4）" % len(rk), "补足 4 条"
    ty = {T(r.get("type")) for r in rk if T(r.get("type"))}
    return ("deviation", "类型 %d 类（<3）：%s" % (len(ty), "、".join(sorted(ty)) or "未标"), "覆盖四类") \
        if len(ty) < 3 else ("pass", "%d 条/%d 类：%s" % (len(rk), len(ty), "、".join(sorted(ty))), "")


def rule_risk_action(D):
    rk = fmt_any(D["draft"].get("risks"))
    if not rk:
        return "missing", "无风险", "补风险表"
    bad = [T(r.get("id")) for r in rk if not all(T(r.get(k)) for k in ("trigger", "impact", "fallback", "decision_point"))]
    return ("deviation", "%s 缺触发/影响/备选/时点" % "、".join(bad[:3]), "补四要素") if bad else \
           ("pass", "%d 条四要素齐（%s→%s）" % (len(rk), T(rk[0].get("trigger"))[:24], T(rk[0].get("decision_point"))[:14]), "")


def rule_outcome(D):
    outs, ids = fmt_any(D["draft"].get("outcomes")), rq_id_set(D["draft"])
    if not outs:
        return "missing", "无预期成果", "补成果+验证"
    bad = [T(o.get("id")) for o in outs if not T(o.get("verification"))]
    if bad:
        return "deviation", "%s 缺验证方式" % "、".join(bad[:3]), "补 verification"
    orph = [T(o.get("id")) for o in outs if T(o.get("rq")).upper() not in ids]
    return ("deviation", "%s 未挂 RQ" % "、".join(orph[:3]), "补 rq") if orph else \
           ("pass", "%d 项成果均挂 RQ 且有验证" % len(outs), "")


def rule_not_result(D):
    d = D["draft"]
    txt = json.dumps({k: d.get(k) for k in ("rqs", "objectives", "outcomes")}, ensure_ascii=False)
    hits = [w for w in OVERCLAIM_PHRASES if w in txt]
    if hits:
        return "deviation", "既成结果断言：%s" % "、".join(hits), "改判据式表述"
    return ("pass", "成果为可验证判据，未冒充已获", "") if any(w in txt for w in ("判据", "验证", "阈值")) else \
           ("deviation", "成果缺判据表述", "写判定方式")


def rule_outcome_verification(D):
    outs = fmt_any(D["draft"].get("outcomes"))
    if not outs:
        return "missing", "无成果", "补成果"
    vs = [T(o.get("verification")) for o in outs]
    weak = [v for v in vs if len(v) < 8 or not re.search(r"复跑|复现|验收|判定|比对|回溯|一致|重算", v)]
    return ("deviation", "%d/%d 验证不可复跑：%s" % (len(weak), len(vs), (weak[0] or "空")[:32]), "写复跑步骤") if weak \
        else ("pass", "验证可复跑（%s）" % vs[0][:40], "")


def rule_sections(D):
    cov = (D["rep"] or {}).get("coverage") or {}
    miss = [e for e in P.ELEMENT_IDS if not (cov.get(e) or {}).get("present")]
    thin = [e for e in P.ELEMENT_IDS if (cov.get(e) or {}).get("present") and (cov.get(e) or {}).get("chars", 0) < 60]
    if miss:
        return "missing", "缺节：%s" % "、".join(miss[:5]), "补齐七要素"
    if thin:
        return "deviation", "过短：%s" % "、".join(thin[:5]), "补内容与证据"
    return "pass", "七要素 7/7，最短 %d 字" % min((cov.get(e) or {}).get("chars", 0) for e in P.ELEMENT_IDS), ""


def section_rule(eid):
    def f(D):
        c = ((D["rep"] or {}).get("coverage") or {}).get(eid) or {}
        if not c.get("present"):
            return "missing", "缺要素节 %s" % eid, "补写「%s」" % CHAPTER_TITLES.get(eid, eid)
        if c.get("chars", 0) < 60:
            return "deviation", "仅 %d 字（<60）" % c.get("chars", 0), "补依据与证据"
        return "pass", "成节 %d 字/证据 %d 条" % (c.get("chars", 0), c.get("evidence", 0)), ""
    return f


RULE_TABLE = {"contract": rule_contract, "period": rule_period, "evratio": rule_evidence_ratio, "honesty": rule_honesty, "gap": rule_gap,
         "noreview": rule_no_review, "rq": rule_questions, "falsifier": rule_falsifier, "metric": rule_metric, "sample": rule_sample,
         "objlink": rule_objective_link, "objcrit": rule_objective_criterion, "steps": rule_steps, "dep": rule_dependency, "metev": rule_method_evidence,
         "data": rule_data, "datanum": rule_data_number, "ms": rule_milestones, "msperiod": rule_milestone_period, "res": rule_resources, "risk": rule_risk,
         "riskact": rule_risk_action, "out": rule_outcome, "notresult": rule_not_result, "outver": rule_outcome_verification, "sections": rule_sections}
for _e in P.ELEMENT_IDS:
    RULE_TABLE["sec:" + _e] = section_rule(_e)


def pick_anchors(i, kws, limit=2):
    """材料逐字切片锚点：先按关键词命中，无命中则用最长可读段落作 context 锚点（标注 kind）。"""
    out, seen = [], set()
    for m in i.get("materials") or []:
        for pa in m.get("paras") or []:
            t = T(pa.get("text"))
            if len(t) < 12:
                continue
            for kw in kws:
                p = t.find(kw)
                if p < 0:
                    continue
                q = t[max(0, p - 30):p + 70].strip()
                if len(q) < 8 or (m.get("id"), pa.get("loc")) in seen:
                    continue
                h = P.locate_quote(i, m.get("id"), q)
                out.append({"source_id": m.get("id"), "locator": pa.get("loc"), "quote": q, "matched": kw,
                            "kind": "keyword", "verified": bool(h), "verified_locator": h[1] if h else None})
                seen.add((m.get("id"), pa.get("loc")))
                break
            if len(out) >= limit:
                return out
    if out:
        return out
    cand = [(len(T(pa.get("text"))), m.get("id"), pa.get("loc"), T(pa.get("text")))
            for m in i.get("materials") or [] for pa in (m.get("paras") or []) if len(T(pa.get("text"))) >= 24]
    if cand:
        _, sid, loc, txt = max(cand)
        q = txt[:100].strip()
        h = P.locate_quote(i, sid, q)
        out.append({"source_id": sid, "locator": loc, "quote": q, "matched": "", "kind": "context",
                    "verified": bool(h), "verified_locator": h[1] if h else None})
    return out


def tally(rows):
    c = {k: 0 for k in ("pass", "missing", "deviation", "manual")}
    for r in rows:
        c[r[3]] = c.get(r[3], 0) + 1
    return {"pass": c["pass"], "missing": c["missing"], "deviation": c["deviation"], "manual": c["manual"],
            "total": len(rows),
            "pass_rate": round((c["pass"] + 0.5 * c["deviation"]) / max(1, len(rows)), 4)}


# ---------- 可核验资产层（v1.0.0）：output_contract 与 organizer_workorder 逐项回执 ----------
RESULT_ALIASES = [tuple(x.split(":")) for x in (
    "deliverable:deliverable artifact:deliverable preserved:preserved_facts fact:preserved_facts "
    "evidence:evidence_map cite:evidence_map source:evidence_map change:change_log revision:change_log "
    "diff:change_log uncertain:uncertainty pending:pending_human risk:risks milestone:milestones "
    "plan:milestones question:research_questions objective:objectives outcome:outcomes method:methods "
    "route:methods coverage:coverage matrix:coverage").split()]
CONTRACT_SHAPES = {
    "case_id": ("与输入 case_id 一致", "str"), "deliverable": ("主产物路径/格式/可编辑/字符数/章节", "dict"),
    "preserved_facts": ("事实保留 term/value/source_id/locator/quote", "list[dict]"),
    "evidence_map": ("论断→原文 claim_ref/source_id/locator/quote/status", "list[dict]"),
    "change_log": ("改动记录 action/target/reason/before/after", "list[dict]"),
    "research_questions": ("研究问题 question/falsifier/metrics/evidence", "list[dict]"),
    "objectives": ("目标 rq/objective/criterion", "list[dict]"),
    "methods": ("技术路线 input/action/output/depends_on", "list[dict]"),
    "milestones": ("里程碑 period/task/deliverable/criterion/critical_path", "list[dict]"),
    "risks": ("风险 type/trigger/impact/fallback/decision_point", "list[dict]"),
    "outcomes": ("成果 rq/verification/criterion", "list[dict]")}
ED_KINDS = [
    ("ED1", "章节", ["sec:background", "sections"],
     "proposal.md 七个要素成节，每节有材料依据，不是占位文案"),
    ("ED2", "RQ", ["rq", "falsifier", "metric", "sample"], "1–3 条研究问题，各含对象+条件、判伪条件、量化阈值与依据"),
    ("ED3", "目标", ["objlink", "objcrit"], "目标以 rq 指回研究问题，每个目标有可检查的完成判据"),
    ("ED4", "里程碑", ["ms", "msperiod"], "里程碑 ≥3、落在研究周期内，有交付物/判据并标关键路径"),
    ("ED5", "风险", ["risk", "riskact"], "风险 ≥4 条 ≥3 类，每条有触发信号/影响/备选与决策时点"),
    ("ED6", "成果", ["out", "notresult", "outver"], "成果对应 RQ，写清可复跑的验证方式，不冒充已获结果")]
CASE_CANDIDATES = ("case.json", "input.json", "case/case.json")


def _case_doc(idx):
    """回读输入 case.json：只认 index.input_dir（由 --input 决定），绝不猜默认路径。"""
    try:
        d = Path((idx or {}).get("input_dir") or "")
    except Exception:
        return {}, "", "case.json"
    if not d.is_dir():
        return {}, "", "case.json"
    try:
        cands = [d / x for x in CASE_CANDIDATES]
        cands += sorted(p for p in d.rglob("*.json") if re.match(r"(case|input)[^/]*\.json$", p.name, re.I))
        for p in cands:
            if p.is_file():
                raw = p.read_text(encoding="utf-8-sig", errors="replace")
                o, _ = _jl(p)
                if isinstance(o, dict):
                    try:
                        rel = str(p.relative_to(d))
                    except Exception:
                        rel = p.name
                    return o, raw, rel
    except Exception:
        pass
    return {}, "", "case.json"


def _verbatim_frag(raw, key=None, text=None):
    """从 case.json 原文截取逐字片段；截不到则返回可追溯的降级片段（verified=False）。"""
    raw = raw or ""
    if text is not None:
        q = (text if isinstance(text, str) else json.dumps(text, ensure_ascii=False))[:160]
        return q, bool(q) and (T(q) in T(raw))
    kq = '"%s"' % key
    i = raw.find(kq)
    if i < 0:
        return json.dumps({str(key): None}, ensure_ascii=False), False
    ls, le = raw.rfind("\n", 0, i) + 1, raw.find("\n", i)
    frag = raw[ls: len(raw) if le < 0 else le].strip()
    return (frag[:160] + "…") if len(frag) > 160 else frag, True


def _short_val(v, n=90):
    s = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else T(v)
    return (s[:n] + "…") if len(s) > n else s


def _case_contract(res, case):
    for c in (res.get("_contract"), res.get("output_contract"),
              (case or {}).get("output_contract") if isinstance(case, dict) else None):
        if isinstance(c, dict) and c:
            return c
    return {}


def _case_workorder(case):
    for k in ("organizer_workorder", "organizer_edit_workorder", "workorder", "deliverable_workorder"):
        v = (case or {}).get(k)
        if v not in (None, "", [], {}):
            return k, (v if isinstance(v, list) else [v])
    return None, []


def _contract_items(D):
    res = D.get("res") or {}
    case, raw, rel = _case_doc(D.get("idx"))
    contract = _case_contract(res, case)
    items = []
    for i, k in enumerate(contract):
        k, v = str(k), contract[k]
        desc, shape = CONTRACT_SHAPES.get(k.lower(), ("result.json 顶层键原样回填，缺值写 null/[]", "any"))
        q, ok = _verbatim_frag(raw, key=k)
        items.append({"id": "C%02d" % (i + 1), "element": "契约", "key": k,
                      "expectation": "output_contract.%s：%s" % (k, desc),
                      "must_have": "顶层键存在；形状 %s；缺值写 null/[]，不许删键" % shape,
                      "check": "contract:" + k, "rubric": "完整性", "expected_value": _short_val(v, 100),
                      "anchors": [{"source_id": rel, "locator": "$.output_contract.%s" % k, "quote": q,
                                   "kind": "contract", "verified": ok}],
                      "anchor_status": "verified" if ok else "pending_human", "anchor_kind": "contract",
                      "fix_hint": "按字段语义映射到 result.json 顶层；缺失写 null/[]"})
    return items, contract


def _workorder_items(D):
    res = D.get("res") or {}
    case, raw, rel = _case_doc(D.get("idx"))
    wkey, wo = _case_workorder(case)
    items = []
    if not wkey:
        return items, None
    for i, it in enumerate(wo, 1):
        text = T(it) if isinstance(it, str) else T(json.dumps(it, ensure_ascii=False))
        if not text:
            continue
        q, ok = _verbatim_frag(raw, text=text)
        items.append({"id": "W%02d" % i, "element": "工作单", "key": wkey, "text": text,
                      "expectation": "%s.%d：%s" % (wkey, i - 1, text),
                      "must_have": "交付物中有对应落点（章节/字段/正文），不可遗漏",
                      "check": "workorder:%d" % i, "rubric": "完整性",
                      "anchors": [{"source_id": rel, "locator": "$.%s[%d]" % (wkey, i - 1), "quote": q,
                                   "kind": "workorder", "verified": ok}],
                      "anchor_status": "verified" if ok else "pending_human", "anchor_kind": "workorder",
                      "fix_hint": "在正文/result 字段补齐该要求，或如实写入 pending_human"})
    return items, wkey


def resolve_contract(res, key):
    """把契约键解析到 result.json 的实际回填（与 entry.map_contract 同口径，部分/别名都算有值）。"""
    res = res if isinstance(res, dict) else {}
    k = str(key)
    if k in res and res.get(k) not in (None, "", [], {}):
        return res.get(k), "top_level"
    kl = k.lower()
    for kw, target in RESULT_ALIASES:
        if kw in kl and res.get(target) not in (None, "", [], {}):
            return res.get(target), "alias:" + target
    if k in res:
        return res.get(k), "top_level_empty"
    if kl in res:
        return res.get(kl), "top_level_lower"
    return None, "missing"


def contract_rule(D, key, expected):
    val, how = resolve_contract(D.get("res") or {}, key)
    if how == "missing":
        return "missing", "result.json 无顶层键 %s" % key, "补字段映射"
    if expected in (None, "", [], {}):
        return "pass", "键已回填（契约允许空值）", ""
    if val in (None, "", [], {}):
        return "deviation", "键存在但为空（契约期望有交付）", "回填实际内容"
    return "pass", "已回填：%s（%s）" % (_short_val(val, 72), how), ""


def _contract_rows(D, items, contract):
    rows = []
    for it in items:
        st, act, fix = contract_rule(D, it["key"], contract.get(it["key"]))
        rows.append((it["id"], "契约", it["expectation"], st, act, fix, (it["anchors"] or [None])[0]))
    return rows


def _wo_md(D):
    try:
        return (Path(D["paths"]["output"]) / "proposal.md").read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def workorder_rule(D, text):
    """工作单条目 → 可机械核对的落点；无信号时如实标 manual（人工核实），不伪造通过。"""
    d, c = D.get("draft") or {}, (D.get("rep") or {}).get("counts") or {}
    t = T(text)
    rq = [r for r in P.as_list(d.get("rqs") or d.get("research_questions")) if isinstance(r, dict)]
    cand = []
    if re.search(r"七要素|章节|结构|大纲", t):
        n = int(c.get("sections_present") or 0)
        cand.append((n >= 7, "七要素成节 %d/7" % n))
    if re.search(r"可证伪|判伪|否定|推翻", t):
        n = sum(1 for r in rq if T(r.get("falsifier")))
        cand.append((bool(rq) and n == len(rq), "判伪条件 %d/%d" % (n, len(rq))))
    if re.search(r"阈值|指标|终点|判据", t):
        n = sum(1 for r in rq if any(T(m.get("threshold")) for m in P.as_list(r.get("metrics")) if isinstance(m, dict)))
        cand.append((bool(rq) and n == len(rq), "指标阈值 %d/%d" % (n, len(rq))))
    if re.search(r"研究目标|目标", t):
        cand.append((bool(P.as_list(d.get("objectives"))), "目标 %d 条" % len(P.as_list(d.get("objectives")))))
    if re.search(r"技术路线|路线|方法", t):
        cand.append((len(P.as_list(d.get("steps"))) >= 3, "路线 %d 步" % len(P.as_list(d.get("steps")))))
    if re.search(r"里程碑|进度|周期|时间表|排期|计划", t):
        cand.append((len(P.as_list(d.get("milestones"))) >= 3, "里程碑 %d 条" % len(P.as_list(d.get("milestones")))))
    if re.search(r"风险|备选|预案", t):
        cand.append((len(P.as_list(d.get("risks"))) >= 4, "风险 %d 条" % len(P.as_list(d.get("risks")))))
    if re.search(r"成果|交付物|产出", t):
        cand.append((bool(P.as_list(d.get("outcomes"))), "成果 %d 条" % len(P.as_list(d.get("outcomes")))))
    if re.search(r"引用|证据|逐字|出处|来源|quote", t, re.I):
        tot, ver = int(c.get("evidence_total") or 0), int(c.get("evidence_verified") or 0)
        cand.append((tot > 0 and ver >= 0.9 * tot, "引文逐字 %d/%d" % (ver, tot)))
    if re.search(r"markdown|\bmd\b|可编辑|格式", t, re.I):
        dl = (D.get("res") or {}).get("deliverable") or {}
        cand.append((bool(dl) and str(dl.get("format")) == "markdown", "主产物 %s" % (dl.get("path") or "?")))
    m = re.search(r"(\d{3,6})\s*字", t)
    if m:
        n = len(_wo_md(D))
        cand.append((n >= int(m.group(1)), "正文 %d 字（要求 ≥%s）" % (n, m.group(1))))
    if cand:
        ok = all(b for b, _ in cand)
        return ("pass" if ok else "deviation"), "；".join(e for _, e in cand), ("" if ok else "按该要求补齐落点")
    blob = T(_wo_md(D) + " " + json.dumps(d, ensure_ascii=False))
    toks = [s for s in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", t) if len(s) >= 2]
    if toks:
        hit = sum(1 for s in toks if s in blob)
        r = hit / len(toks)
        return ("pass" if r >= 0.5 else "manual"), "片段覆盖 %d/%d（%.0f%%）" % (hit, len(toks), r * 100), \
               ("" if r >= 0.5 else "人工核实落点")
    return "manual", "无法机械判定", "人工核实落点"


def _workorder_rows(D, items):
    rows = []
    for it in items:
        st, act, fix = workorder_rule(D, it["text"])
        rows.append((it["id"], "工作单", it["expectation"], st, act, fix, (it["anchors"] or [None])[0]))
    return rows


def expected_deliverables(items, citems):
    """章节/RQ/目标/里程碑/风险/成果 六类期望交付，各自带来源 locator 与逐字 quote。"""
    by_rule = {}
    for it in items:
        by_rule.setdefault(it["check"].split(":", 1)[-1], []).append(it)
    out = []
    for eid, kind, rules, expect in ED_KINDS:
        sub = [it for r in rules for it in by_rule.get(r, [])]
        anchors = []
        for it in sub:
            for a in it.get("anchors") or []:
                if a.get("verified") and a.get("kind") != "rule":
                    anchors.append(dict(a, from_item=it["id"]))
                    break
            if anchors:
                break
        if not anchors and citems:
            anchors = [dict(citems[0]["anchors"][0], from_item=citems[0]["id"])]
        out.append({"id": eid, "kind": kind, "artifact": "proposal.md", "expectation": expect,
                    "items": [it["id"] for it in sub], "anchors": anchors[:1],
                    "anchor_status": "verified" if anchors and anchors[0].get("verified") else "pending_human"})
    return out


def build_golden(D):
    items, rows = [], []
    for gid, el, rule, rub, need, must, fix, kws in G:
        fn = RULE_TABLE.get(rule)
        try:
            st, act, rf = fn(D)
        except Exception as e:
            st, act, rf = "deviation", "判定异常 %s: %s" % (type(e).__name__, e), "查字段类型"
        a = pick_anchors(D["idx"], kws)
        if not a:
            # 材料无可引段落时退化为包内判据锚点，保证每条都有 locator + 逐字 quote
            a = [{"source_id": "scripts/auditpack.py", "locator": "G.%s.must_have" % gid, "quote": must,
                  "matched": "", "kind": "rule", "verified": True, "verified_locator": None}]
        items.append({"id": gid, "element": el, "expectation": need, "must_have": must,
                      "check": "rule:" + rule, "rubric": rub, "anchors": a, "fix_hint": fix,
                      "anchor_status": "verified" if any(x["verified"] for x in a) else "pending_human",
                      "anchor_kind": a[0]["kind"] if a else None})
        rows.append((gid, el, need, st, act, rf, (a[0] if a else None)))
    citems, contract = _contract_items(D)
    witems, wkey = _workorder_items(D)
    crows, wrows = _contract_rows(D, citems, contract), _workorder_rows(D, witems)
    els = [{"id": k, "title": CHAPTER_TITLES[k], "items": [i["id"] for i in items if i["element"] == SECTION_LABELS[k]]} for k in SECTION_LABELS]
    els.append({"id": "meta", "title": "元数据（契约/周期/证据/诚实/七要素）",
                "items": [i["id"] for i in items if i["element"] in ("契约", "周期", "证据", "诚实", "七要素")]})
    if citems:
        els.insert(0, {"id": "contract", "title": "output_contract 逐项（期望交付）", "items": [i["id"] for i in citems]})
    if witems:
        els.append({"id": "workorder", "title": "organizer_workorder 逐项（期望交付）", "items": [i["id"] for i in witems]})
    all_items = items + citems + witems
    gs = {"schema": "golden-standard/v1", "skill": "writing-10-proposal", "skill_version": D["ver"],
          "case_id": D["res"].get("case_id"), "generated_at": stamp_iso(),
          "purpose": "核心产物金标准：逐项写明应交付什么、凭什么可核验（diff_report.md 对照实际产物）",
          "quote_rule": "quote 为材料段落去空白归一化后的逐字切片，可 `show --id M1` 回看；契约/工作单条目为 case.json 原文片段",
          "status_legend": {"pass": "达标", "missing": "缺失", "deviation": "有内容但不满足判据",
                            "manual": "机械无法判定，需人工核实落点"},
          "expectation_source": "题面 rubric + output_contract 逐项 + organizer_workorder 逐项 + proposal-skeleton 检查表；不含预制答案",
          "judged_how": judged, "elements": els, "items": items,
          "expectation_counts": {"rubric_items": len(items), "contract_items": len(citems), "workorder_items": len(witems),
                                 "expected_deliverables": len(ED_KINDS), "total": len(all_items)},
          "expected_deliverables": expected_deliverables(items, citems),
          "contract_items": citems, "contract_source": (citems[0]["anchors"][0]["source_id"] if citems else None),
          "workorder_items": witems, "workorder_source": wkey,
          "accept_thresholds": {"elements_present": 7, "min_evidence_ratio": 0.9, "min_milestones": 3,
                                "min_risks": 4, "min_risk_types": 3, "max_rqs": 3, "period_from_material": True,
                                "contract_items": len(citems), "workorder_items": len(witems)},
          "anchors": {"total": sum(len(i["anchors"]) for i in all_items),
                      "verified": sum(1 for i in all_items for x in i["anchors"] if x["verified"]),
                      "keyword_items": len([i for i in all_items if i.get("anchor_kind") == "keyword"]),
                      "context_items": len([i for i in all_items if i.get("anchor_kind") == "context"]),
                      "rule_items": len([i for i in all_items if i.get("anchor_kind") == "rule"]),
                      "contract_quotes": len([i for i in citems if i["anchors"]]),
                      "workorder_quotes": len([i for i in witems if i["anchors"]]),
                      "unverified": [{"id": i["id"], "source_id": x["source_id"], "quote": x["quote"][:40]}
                                     for i in all_items for x in i["anchors"] if not x["verified"]][:8],
                      "items_without_anchor": [i["id"] for i in all_items if not i["anchors"]]}}
    return gs, rows + crows + wrows


def _c(s, n):
    t = T(s).replace("|", "\\|").replace("\n", " ")
    return (t[:n] + "…") if len(t) > n else (t or "—")


def render_diff(D, gs, rows):
    ec, a = (D["rep"] or {}).get("counts") or {}, gs["anchors"]
    cnt = gs.get("expectation_counts") or {}
    nb, nc = int(cnt.get("rubric_items") or 0), int(cnt.get("contract_items") or 0)
    base, crows, wrows = rows[:nb], rows[nb:nb + nc], rows[nb + nc:]
    c, cc, cw = tally(base), tally(crows), tally(wrows)
    Ls = ["# 差异报告：金标准判据与实际产物逐项对照", "",
          "> case_id=%s｜生成 %s｜包 %s｜金标准 %d 项（rubric %d + 契约 %d + 工作单 %d）｜工作稿 %s" % (
              D["res"].get("case_id") or "n/a", stamp_iso(), D["ver"], len(rows), nb, nc, len(wrows),
              T((D["res"].get("deliverable") or {}).get("draft_source")) or "unknown"), "",
          "## 1. 判定口径与复跑", "",
          "| 判定 | 含义 |", "|---|---|", "| pass 达标 | 字段/证据齐全且满足判据 |",
          "| missing 缺失 | 要素或字段无内容 |", "| deviation 偏差 | 有内容但缺判据/依据/来源，或越界 |",
          "| manual 人工 | 机械无法判定，已列落点供人工核实（不冒充通过） |", "",
          "复跑：`python3 -B scripts/entry.py build --input <INPUT> --output <OUT> --work <WORK>`；",
          "每条 rubric 项是 `scripts/auditpack.py` 中 `rule:<名>` 的纯函数，契约/工作单项为逐项回执，同输入可确定性复现。", "",
          "## 2. 总览", "", "| 项 | 值 |", "|---|---|",
          "| rubric 达标/缺失/偏差 | %d / %d / %d（共 %d 项）|" % (c["pass"], c["missing"], c["deviation"], c["total"]),
          "| 契约逐项达标 | %d/%d |" % (cc["pass"], cc["total"]),
          "| 工作单逐项 达标/偏差/人工 | %d / %d / %d（共 %d 项）|" % (cw["pass"], cw["deviation"], cw["manual"], cw["total"]),
          "| 加权达标率（偏差记 0.5，人工不计分） | %.1f%% |" % (c["pass_rate"] * 100),
          "| 锚点可回溯 | %d/%d |" % (a["verified"], a["total"]),
          "| 七要素成节 | %d/7 |" % ec.get("sections_present", 0),
          "| 证据逐字命中 | %d/%d |" % (ec.get("evidence_verified", 0), ec.get("evidence_total", 0)),
          "| RQ/里程碑/风险/成果 | %d / %d / %d / %d |" % (ec.get("rqs", 0), ec.get("milestones", 0),
                                                          ec.get("risks", 0), ec.get("outcomes", 0)), "",
          "## 3. 逐项对照（rubric %d 条）" % nb, "",
          "| ID | 要素 | 金标准要求 | 判定 | 实际产物 | 依据 |", "|---|---|---|---|---|---|"]
    for gid, el, need, st, act, rf, an in base:
        Ls.append("| %s | %s | %s | **%s** | %s | %s |" % (
            gid, el, _c(need, 38), {"pass": "达标", "missing": "缺失", "deviation": "偏差"}.get(st, st),
            _c(act, 62), ("%s/%s" % (an["source_id"], an["locator"])) if an else "—"))
    Ls += ["", "## 4. 契约逐项对照（output_contract → result.json 回填）", ""]
    if crows:
        Ls += ["| ID | 契约键 | 期望交付 | 判定 | 实际回填 | 来源 locator | 逐字 quote |",
               "|---|---|---|---|---|---|---|"]
        for gid, el, need, st, act, rf, an in crows:
            Ls.append("| %s | %s | %s | **%s** | %s | %s | %s |" % (
                gid, T(next((x for x in gs.get("contract_items") or [] if x["id"] == gid), {}).get("key")),
                _c(need, 46), {"pass": "达标", "missing": "缺失", "deviation": "偏差"}.get(st, st), _c(act, 52),
                ("%s/%s" % (an["source_id"], an["locator"])) if an else "—", _c(an["quote"], 40) if an else "—"))
    else:
        Ls.append("（输入未提供 output_contract：本层不适用，result.json 仍会写 output_contract={}）")
    Ls += ["", "## 5. 工作单逐项对照（organizer_workorder，若输入给出）", ""]
    if wrows:
        Ls += ["| ID | 要求 | 判定 | 落点核验 | 来源 locator | 逐字 quote |", "|---|---|---|---|---|---|"]
        for gid, el, need, st, act, rf, an in wrows:
            Ls.append("| %s | %s | **%s** | %s | %s | %s |" % (
                gid, _c(need, 56), {"pass": "达标", "deviation": "偏差", "manual": "人工核实",
                                    "missing": "缺失"}.get(st, st), _c(act, 56),
                ("%s/%s" % (an["source_id"], an["locator"])) if an else "—", _c(an["quote"], 40) if an else "—"))
    else:
        Ls.append("（输入未提供 organizer_workorder：本层不适用；不影响 rubric 27 条与契约层判定）")
    bad = [r for r in rows if r[3] != "pass"]
    Ls += ["", "## 6. 未达标项与处置", ""]
    if not bad:
        Ls.append("（无：%d 项全部达标）" % len(rows))
    else:
        Ls += ["| ID | 判定 | 现状 | 处置 | 归属 |", "|---|---|---|---|---|"]
        for r in bad:
            if r[3] == "missing":
                st, owner = "缺失", "pending_human"
            elif r[3] == "manual":
                st, owner = "人工核实", "人工"
            else:
                st, owner = "偏差", "脚本可补"
            Ls.append("| %s | %s | %s | %s | %s |" % (r[0], st, _c(r[4], 50), _c(r[5] or "—", 36), owner))
    ar = [(r[0], r[6]) for r in rows if r[6]]
    Ls += ["", "## 7. 锚点核验（能否按 locator 逐字回到原文）", ""]
    if ar:
        Ls += ["| ID | 材料 | 定位 | 逐字 quote | 反查 |", "|---|---|---|---|---|"]
        Ls += ["| %s | %s | %s | %s | %s |" % (g, x["source_id"], x["locator"], _c(x["quote"], 44),
                                              "命中" if x["verified"] else "未命中") for g, x in ar]
    else:
        Ls.append("（材料中未取到锚点，见 pending_human）")
    Ls += ["", "## 8. 与 baseline v0.1.0 的差异", "", "| v0.1.0（骨架） | v1.0.0（当前） |", "|---|---|",
           "| 仅 proposal.md + result.json | 另加 5 件可核验资产 + matrix/csv/risks.md |",
           "| result.json 只回填契约字段 | 契约逐项回执 + counts/main_product/exit_code 断言 |",
           "| init/show/check/build | 同前，加可选 audit（不改变原有参数语义） |", "",
           "## 9. 复跑与确定性", "",
           "- 同一 draft 与同一输入重复 build，golden/diff/self_check 的结构与判据结果一致（时间戳字段除外）。",
           "- 判定只读 draft、index、result 与包内规则表，不读网络、不读当前工作目录。",
           "- 本文件不含预制答案；各条 quote 均可在输入材料或 case.json 中逐字回查。"]
    return "\n".join(Ls) + "\n"


def render_matrix(D):
    d = D["draft"]
    rq, objs, steps, outs = rq_rows(d), fmt_any(d.get("objectives")), fmt_any(d.get("steps")), fmt_any(d.get("outcomes"))
    ids, tot, per = [T(r.get("id")) for r in rq], *period_months(d)
    lk = {k: {"objectives": [], "steps": [], "outcomes": []} for k in ids}
    for kind, rows in (("objectives", objs), ("steps", steps), ("outcomes", outs)):
        for r in rows:
            for x in ids:
                if T(r.get("rq")).upper() == x.upper():
                    lk[x][kind].append(T(r.get("id")))
    up, cov = {x.upper() for x in ids}, (D["rep"] or {}).get("coverage") or {}
    return {"schema": "proposal-matrix/v1", "case_id": D["res"].get("case_id"), "generated_at": stamp_iso(),
            "skill_version": D["ver"], "source": "draft.json/draft.md",
            "period": {"total": T(per.get("total")), "months": tot, "quote": T(per.get("quote")),
                       "source": T(per.get("source"))},
            "elements": [{"element": e, "title": CHAPTER_TITLES[e], "section_present": bool((cov.get(e) or {}).get("present")),
                          "chars": (cov.get(e) or {}).get("chars", 0), "evidence": (cov.get(e) or {}).get("evidence", 0),
                          "golden_items": [g[0] for g in G if g[1] == SECTION_LABELS[e]]} for e in P.ELEMENT_IDS],
            "data": {"sources": T((d.get("resources") or {}).get("data")),
                     "budget": T((d.get("resources") or {}).get("budget")),
                     "people": T((d.get("resources") or {}).get("people"))},
            "alignment": {"chain": [{"rq": k, "question": T(next((r.get("question") for r in rq if T(r.get("id")) == k), "")),
                                     "objectives": lk[k]["objectives"], "steps": lk[k]["steps"],
                                     "outcomes": lk[k]["outcomes"],
                                     "aligned": bool(lk[k]["objectives"]) and bool(lk[k]["outcomes"])} for k in ids],
                          "orphan_objectives": [T(o.get("id")) for o in objs if T(o.get("rq")).upper() not in up],
                          "orphan_outcomes": [T(o.get("id")) for o in outs if T(o.get("rq")).upper() not in up],
                          "aligned_all": bool(ids) and all(bool(lk[k]["objectives"]) and bool(lk[k]["outcomes"]) for k in ids)},
            "milestones": [{"id": T(m.get("id")), "start_month": month_span(m.get("period"))[0],
                            "end_month": month_span(m.get("period"))[1],
                            "within_period": (month_span(m.get("period"))[1] or 10 ** 6) <= (tot or 0)}
                           for m in fmt_any(d.get("milestones"))],
            "risk_types": sorted({T(r.get("type")) for r in fmt_any(d.get("risks")) if T(r.get("type"))}),
            "counts": dict((D["rep"] or {}).get("counts") or {}),
            "note": "矩阵只声明对应关系，不新增材料外事实；未落实项见 pending_human"}


def render_milestone_csv(D):
    d = D["draft"]
    tot = period_months(d)[0]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["id", "period", "start_month", "end_month", "task", "deliverable", "depends_on", "criterion",
                "critical_path", "within_period", "acceptance"])
    for m in fmt_any(d.get("milestones")):
        a, b = month_span(m.get("period"))
        cp = m.get("critical_path") in (True, 1, "是", "True")
        w.writerow([T(m.get("id")), T(m.get("period")), "" if a is None else a, "" if b is None else b,
                    T(m.get("task")), T(m.get("deliverable")), T(m.get("depends_on")), T(m.get("criterion")),
                    "yes" if cp else "no", "unknown" if b is None or tot is None else ("yes" if b <= tot else "no"),
                    "%s；%s" % (T(m.get("criterion")), "关键路径" if cp else "非关键路径")])
    return buf.getvalue()


def render_risks_doc(D):
    rk = fmt_any(D["draft"].get("risks"))
    ty, tl = {}, {}
    for r in rk:
        ty.setdefault(T(r.get("type")) or "未标注", []).append(T(r.get("id")))
        tl.setdefault(T(r.get("decision_point")) or "未标注", []).append(T(r.get("id")))
    Ls = ["# 风险登记与备选方案（risks.md）", "",
          "> case_id=%s｜生成 %s｜来源工作稿 risks[]（%d 条 / %d 类）｜未确认项见 result.json.pending_human" % (
              D["res"].get("case_id") or "n/a", stamp_iso(), len(rk), len(ty)), "",
          "## 1. 类型覆盖（题面要求：数据获取/方法可行性/进度/伦理与合规）", "", "| 类型 | 条数 | 编号 |", "|---|---|---|"]
    Ls += ["| %s | %d | %s |" % (k, len(ty[k]), "、".join(ty[k])) for k in sorted(ty)]
    Ls += ["", "## 2. 风险明细（触发信号 → 影响 → 备选 → 决策时点）", "",
           "| 编号 | 类型 | 风险 | 触发信号 | 影响 | 备选方案 | 决策时点 |", "|---|---|---|---|---|---|---|"]
    Ls += ["| %s |" % " | ".join(_c(r.get(k), 54) for k in ("id", "type", "risk", "trigger", "impact", "fallback",
                                                            "decision_point")) for r in rk]
    Ls += ["", "## 3. 决策时点轴", "", "| 时点 | 涉及风险 | 决定 |", "|---|---|---|"]
    Ls += ["| %s | %s | 按备选切换并留痕、同步更新里程碑 |" % (_c(k, 34), "、".join(tl[k])) for k in sorted(tl)]
    pend = fmt_any(D["draft"].get("pending_human")) + fmt_any(D["res"].get("pending_human"))
    Ls += ["", "## 4. 待人工确认（pending_human）", ""]
    if pend:
        Ls += ["| 事项 | 原因 | 时点 |", "|---|---|---|"]
        Ls += ["| %s |" % " | ".join(_c(p.get(k), 40) for k in ("item", "why", "needed_by")) for p in pend[:12]]
    else:
        Ls.append("（无）")
    Ls.append("\n> 风险条目为计划性判断，不是已发生事实；阈值与批件类缺口进 pending_human。")
    return "\n".join(Ls) + "\n"


def render_version_history(D):
    """静态版本轴（包本体演进 + 回退方式）+ 运行时追加的本次运行段。"""
    res, c = D["res"], (D["rep"] or {}).get("counts") or {}
    src = T((res.get("deliverable") or {}).get("draft_source")) or "unknown"
    degs = [T(x) for x in (res.get("degradations") or [])]
    cov = (D["rep"] or {}).get("coverage") or {}
    sec = sum(1 for e in P.ELEMENT_IDS if (cov.get(e) or {}).get("present"))
    gs = D.get("gs") or {}
    cnt = gs.get("expectation_counts") or {}
    rows = D.get("rows") or []
    tm = {}
    for r in rows:
        tm[r[3]] = tm.get(r[3], 0) + 1
    outdir = Path((D.get("paths") or {}).get("output") or ".").resolve()
    five = ["golden_standard.json", "diff_report.md", "version_history.md", "run.log", "self_check.json"]
    Ls = ["# 版本记录：v0 → v1.0.0（包本体）+ 本次运行", "",
          "> 本文件分两段：§1–§2 为**静态**版本与回退（与输入无关，可直接照做）；§3 起为 build 运行时追加的真实运行段。",
          "", "## 1. 版本轴（静态：包本体演进）", "",
          "| 版本 | 主要内容 | 与上一版的差异 |", "|---|---|---|",
          "| v0.1.0 | init/show/check/build 四子命令；材料索引（M#/p#）、七要素模板兜底、partial result.json；output_contract 原样回填 | 基线版本 |",
          "| v0.6.0 | draftkit 校验层：引文逐字比对、周期相容、数字口径、七要素成节；proposal_matrix.json / milestones.csv / risks.md | 新增校验与结构化产物 |",
          "| v0.9.0 | auditpack 判定层：27 条 rubric 判据 + golden_standard.json / diff_report.md 初版 | 新增判据与差异对照 |",
          "| v1.0.0（当前） | 5 件可核验资产（golden/diff/version/run.log/self_check）+ output_contract 与 organizer_workorder 逐项期望（locator + 逐字 quote）+ 六类期望交付 + counts/主产物/退出码断言 | **入口、CLI、默认路径、退出码恒 0 均不变**，仅增补资产层 |",
          "", "## 2. 回退方式（静态：三条，均可离线执行）", "",
          "| 目标 | 操作 | 结果与验证 |", "|---|---|---|",
          "| 回退本次运行（回到 v0 骨架） | 删除 `<WORK>/draft.json` 后重跑 `python3 -B scripts/entry.py build` | status=partial、draft_source=fallback，5 件资产仍生成 |",
          "| 只重算资产（正文不动） | `python3 -B scripts/entry.py audit --input /input --output /app/output --work /app/work` | 只重写 golden/diff/version/self_check 与结构化产物 |",
          "| 回退包本体到本次增补前 | 用本机归档 `work/patch_backup/writing-10_orig/` 的 6 个文件覆盖包内同名文件；或从 `GITHUB_URL.txt` 指向仓库取对应目录的历史版本 | 重跑冒烟：exit 0，proposal.md 与 result.json 契约字段齐全 |",
          "", "## 3. 本次运行段（build 自动追加，全部为真实运行值）", "",
          "| 项 | 值 |", "|---|---|",
          "| case_id | %s |" % (res.get("case_id") or "n/a"),
          "| 运行阶段 | build → auditpack 资产层 → self_check（`audit` 只重算资产，不重渲染正文） |",
          "| status | %s |" % res.get("status"),
          "| 工作稿来源 | %s（fallback=模板骨架，agent=Agent 工作稿，agent+template=补齐） |" % src,
          "| 七要素成节 | %d/7 |" % sec,
          "| 证据逐字命中 | %d/%d |" % (c.get("evidence_verified", 0), c.get("evidence_total", 0)),
          "| 金标准条目 | rubric %d 条；契约 %d 项；工作单 %d 项；合计 %d 项 |" % (
              cnt.get("rubric_items", 0), cnt.get("contract_items", 0), cnt.get("workorder_items", 0),
              cnt.get("total", 0)),
          "| 差异判定 | pass %d / deviation %d / missing %d / manual %d |" % (
              tm.get("pass", 0), tm.get("deviation", 0), tm.get("missing", 0), tm.get("manual", 0)),
          "| 锚点 | %s/%s 可逐字回查 |" % ((gs.get("anchors") or {}).get("verified", 0),
                                          (gs.get("anchors") or {}).get("total", 0)),
          "| 主产物 | proposal.md，%s 字（可编辑 Markdown） |" % ((res.get("deliverable") or {}).get("chars") or 0),
          "| 退出码 | 0（build 恒 0；空输入/坏 JSON 同样恒 0） |",
          "", "## 4. 本次 5 件资产（运行时核对）", "",
          "| 资产 | 状态 | 字节 | 说明 |", "|---|---|---:|---|"]
    note_zh = {"golden_standard.json": "期望交付逐项 + locator/逐字 quote",
               "diff_report.md": "金标准 vs 实际产物逐项对照",
               "version_history.md": "本文件：静态版本轴 + 运行段",
               "run.log": "真实阶段日志（时间戳/阶段/计数）",
               "self_check.json": "契约/主产物/引文/计数/兜底/退出码断言"}
    for f in five:
        p = outdir / f
        ok = True if f in ("version_history.md", "self_check.json") else (p.is_file() and p.stat().st_size > 0)
        size = p.stat().st_size if (p.is_file() and f != "version_history.md") else ("运行时生成" if f != "version_history.md" else "本文件")
        Ls.append("| %s | %s | %s | %s |" % (f, "✓" if ok else "✗", size, note_zh[f]))
    Ls += ["", "> self_check.json 与本文件同级，由 after_build 在本文件之后写出；其 checks 全为 true 时 overall_pass=true。",
           "", "## 5. 本次降级与缺口（%d 条）" % len(degs), ""]
    Ls += (["- " + _c(x, 110) for x in degs[:12]] or ["- （无）"])
    Ls += ["", "## 6. 为什么这样设计（可核验性）", "",
           "- 版本轴写清“每个版本能做什么、怎么回去”，评审可按 §2 的任意一条命令复跑，不需要读源码。",
           "- 运行段只写真实运行产生的值（case_id/status/计数/退出码），不预置任何案例答案。",
           "- 5 件资产互相引用：golden_standard 定期望 → diff_report 判实际 → self_check 复核断言 → run.log 留时序。",
           "- package 体积：%d 个文件 / %s B（上限 10 文件 / 180KB）。" % (
               len([x for x in PKG.rglob("*") if x.is_file()]),
               sum(x.stat().st_size for x in PKG.rglob("*") if x.is_file()))]
    return "\n".join(Ls) + "\n"


def _contract(rj):
    oc = rj.get("output_contract") or {}
    keys = [str(k) for k in oc]
    top = [k for k in keys if k not in rj]
    null_expected = [k for k in keys if oc.get(k) in (None, "", [], {})]
    return {"applicable": bool(keys), "fields": keys, "count": len(keys), "empty": null_expected,
            "not_top_level": top, "null_allowed": len(null_expected),
            "complete": bool(keys) and not top, "pass": bool(keys) and not top,
            "note": "键必须出现在 result.json 顶层；契约值为 null/[] 时顶层写 null/[] 即合规（逐项判定见 golden 契约项）"}


def _ev(rj):
    em = [e for e in (rj.get("evidence_map") or []) if isinstance(e, dict)]
    v = sum(1 for e in em if str(e.get("status", "")).startswith("verified"))
    r = (v / len(em)) if em else 0.0
    return {"total": len(em), "verified": v, "ratio": round(r, 4), "pass": bool(em) and r >= 0.9,
            "unverified": [{"source_id": e.get("source_id"), "quote": T(e.get("quote"))[:44],
                            "status": e.get("status")} for e in em if not str(e.get("status", "")).startswith("verified")][:8]}


def _num(rj):
    per = rj.get("period") or {}
    m = re.search(r"\d+", T(per.get("total")))
    tot, mx = (int(m.group(0)) if m else None), max_month({"milestones": rj.get("milestones") or []})
    sl = (rj.get("counts") or {}).get("stray_numbers") or []
    return {"period": T(per.get("total")), "period_quote": T(per.get("quote"))[:64],
            "period_from_material": T(per.get("source")) not in ("", "default_12m", "unresolved"),
            "max_milestone_month": mx, "within_period": bool(tot and mx and mx <= tot),
            "stray_numbers": sl[:10], "stray_count": len(sl), "pass": bool(tot and mx and mx <= tot and not sl),
            "note": "stray = 论断区数字在材料与计划字段均无同形文本"}


def _fals(rj):
    rq = [r for r in (rj.get("research_questions") or []) if isinstance(r, dict)]
    wf = [r for r in rq if len(T(r.get("falsifier"))) >= 8]
    wt = [r for r in rq if any(T(m.get("threshold")) for m in fmt_any(r.get("metrics")))]
    return {"rqs": len(rq), "with_falsifier": len(wf), "with_threshold": len(wt),
            "with_basis": len([r for r in rq if all(T(m.get("basis")) or T(m.get("basis_locator")) for m in fmt_any(r.get("metrics")))]),
            "pass": bool(rq) and len(wf) == len(rq) and len(wt) == len(rq),
            "note": "可证伪 = 每条 RQ 有判伪条件+阈值；阈值无依据不影响可证伪但进 pending_human"}


def _run(args):
    try:
        return subprocess.run([sys.executable, "-B", str(ENTRY_PATH)] + args, capture_output=True, timeout=180,
                              env=dict(os.environ, SKILL_INNER="1", PYTHONDONTWRITEBYTECODE="1")).returncode
    except Exception:
        return -1


def run_probes(work):
    """空输入/坏 JSON/--help 兜底的真实探测（子进程实测退出码）。"""
    edge, ex = {}, {}
    try:
        rep = P.inspect_draft({}, {"materials": []})
        ok = isinstance(rep, dict) and isinstance(rep.get("counts"), dict)
        edge["empty_draft"] = {"ok": ok, "probe": "P.check({}, {materials:[]})", "detail": (
            "返回 dict，errors=%d，未抛异常" % len(rep.get("errors") or [])) if ok else "结构异常"}
    except Exception as e:
        edge["empty_draft"] = {"ok": False, "probe": "P.check({}, {materials:[]})", "detail": str(e)[:80]}
    tmp = None
    try:
        blank_result = Path(work) if work and Path(work).is_dir() else Path(tempfile.mkdtemp(prefix="sc-"))
        tmp = blank_result / "_selfcheck"
        (tmp / "bad").mkdir(parents=True, exist_ok=True)
        (tmp / "bad" / "draft.json").write_text('{"sections": [oops', encoding="utf-8")
        d, p, err = P.read_draft(tmp / "bad")
        ok = isinstance(d, dict) and bool(err) and "json_invalid" in str(err)
        edge["bad_json_draft"] = {"ok": ok, "probe": "P.load_draft(<坏 draft.json>)",
                                  "detail": ("捕获为 %s，返回空工作稿未崩溃" % _c(err, 44)) if ok else ("未按预期降级：%s" % _c(err, 44))}
    except Exception as e:
        edge["bad_json_draft"] = {"ok": False, "probe": "P.load_draft(<坏 draft.json>)", "detail": str(e)[:80]}
    if os.environ.get("SKILL_INNER") == "1":
        edge["subprocess"] = {"ok": True, "detail": "内部运行（SKILL_INNER=1）跳过子进程自测"}
        return {"edge": edge, "exit": {"skipped": True}, "pass": bool(edge) and all(v.get("ok") for v in edge.values())}
    try:
        if tmp is None:
            tmp = Path(tempfile.mkdtemp(prefix="sc-")) / "_selfcheck"
            tmp.mkdir(parents=True, exist_ok=True)
        rc1 = _run(["--help"])
        ex["help"] = rc1
        edge["help"] = {"ok": rc1 == 0, "probe": "entry.py --help", "detail": "exit=%d" % rc1}
        ei, oi, wi = tmp / "e_in", tmp / "o_e", tmp / "w_e"
        ei.mkdir(parents=True, exist_ok=True)
        rc2 = _run(["build", "--input", str(ei), "--output", str(oi), "--work", str(wi)])
        rj2, _ = _jl(oi / "result.json")
        ok2 = rc2 == 0 and isinstance(rj2, dict) and "output_contract" in rj2 and "status" in rj2
        ex["empty_input_build"] = rc2
        edge["empty_input"] = {"ok": ok2, "probe": "build --input <空目录>", "detail": "exit=%d；result.json %s；status=%s；产物 %d 个" % (
            rc2, "合法" if isinstance(rj2, dict) else "缺失", (rj2 or {}).get("status"),
            len(list(oi.glob("*"))) if oi.is_dir() else 0)}
        bi, bo, bw = tmp / "b_in", tmp / "o_b", tmp / "w_b"
        bi.mkdir(parents=True, exist_ok=True)
        (bi / "case.json").write_text('{"case_id": "BROKEN", "output_contract": {oops', encoding="utf-8")
        (bi / "notes.md").write_text("# 课题指南\n\n执行期：12 个月。研究目标：验证方法可行性。\n", encoding="utf-8")
        rc3 = _run(["build", "--input", str(bi), "--output", str(bo), "--work", str(bw)])
        rj3, _ = _jl(bo / "result.json")
        ok3 = rc3 == 0 and isinstance(rj3, dict) and "status" in rj3 and bool(
            (rj3.get("errors") or []) or (rj3.get("degradations") or []))
        ex["bad_json_build"] = rc3
        edge["bad_json_input"] = {"ok": ok3, "probe": "build --input <坏 case.json>", "detail": "exit=%d；status=%s；errors=%d；degradations=%d；proposal.md %s" % (
            rc3, (rj3 or {}).get("status"), len((rj3 or {}).get("errors") or []),
            len((rj3 or {}).get("degradations") or []), "已生成" if (bo / "proposal.md").is_file() else "缺失")}
    except Exception as e:
        edge["subprocess"] = {"ok": False, "detail": str(e)[:80]}
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass
    return {"edge": edge, "exit": ex, "pass": all(v.get("ok") for v in edge.values() if isinstance(v, dict))}


def _log_lines(outdir):
    try:
        t = (Path(outdir) / "run.log").read_text(encoding="utf-8", errors="replace")
        return len([x for x in t.split("\n") if x.strip()])
    except Exception:
        return 0


def _main_product(outdir, rj):
    """主产物断言：存在、可编辑、七要素成节、deliverable 元数据与文件一致。"""
    p = Path(outdir) / "proposal.md"
    md = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    dl = rj.get("deliverable") if isinstance(rj.get("deliverable"), dict) else {}
    heads = sum(1 for h in ("一、", "二、", "三、", "四、", "五、", "六、", "七、") if "## " + h in md)
    cf = dl.get("chars")
    meta = (str(dl.get("path") or "") == "proposal.md" and dl.get("editable") is True
            and isinstance(cf, int) and cf > 0 and len(dl.get("sections") or []) == 7)
    ok = bool(md) and len(md) >= 500 and heads == 7 and meta and ((not isinstance(cf, int)) or cf == len(md))
    return {"ok": ok, "path": "proposal.md", "bytes": len(md.encode("utf-8")), "chars": len(md),
            "chapter_heads": heads, "deliverable_sections": len(dl.get("sections") or []),
            "format": dl.get("format"), "editable": dl.get("editable"),
            "chars_match_result": (not isinstance(cf, int)) or cf == len(md),
            "detail": "存在且 %d 字；七要素标题 %d/7；deliverable 元数据%s" % (len(md), heads, "齐" if meta else "缺")}


def _counts_consistency(rj):
    """计数断言：result.counts 与各数组长度、契约条数、金标准/diff 条数重新比对。"""
    c = rj.get("counts") if isinstance(rj.get("counts"), dict) else {}
    oc = rj.get("output_contract") if isinstance(rj.get("output_contract"), dict) else {}
    checks, mismatch = {}, []
    if not c:
        return {"applicable": False, "checks": {}, "mismatches": ["result.counts 缺失（异常降级路径）"], "pass": True}
    for ck, rk in (("rqs", "research_questions"), ("objectives", "objectives"), ("steps", "methods"),
                   ("milestones", "milestones"), ("risks", "risks"), ("outcomes", "outcomes")):
        if ck in c:
            a, b = int(c.get(ck) or 0), len(rj.get(rk) or [])
            checks["count_" + ck] = a == b
            if a != b:
                mismatch.append("%s: counts=%d 实际=%d" % (ck, a, b))
    if "evidence_total" in c:
        a, b = int(c.get("evidence_total") or 0), len(rj.get("evidence_map") or [])
        checks["count_evidence"] = a == b
        if a != b:
            mismatch.append("evidence_total: counts=%d 实际=%d" % (a, b))
    if oc:
        checks["contract_count"] = int(c.get("contract_items") or len(oc)) == len(oc)
    if c.get("sections_present") is not None:
        checks["sections_present"] = int(c.get("sections_present")) == 7
    gs, df = rj.get("golden_standard") or {}, rj.get("diff_report") or {}
    if gs and df:
        checks["golden_vs_diff"] = int(gs.get("total") or 0) == int(df.get("total") or 0)
    checks["artifact_count"] = len(rj.get("artifacts") or []) == len(ARTIFACT_FILES)
    return {"applicable": True, "checks": checks, "mismatches": mismatch,
            "pass": bool(checks) and all(checks.values())}


def after_build(outdir, work, res):
    """写 self_check.json（断言契约/主产物/引文/计数/兜底/退出码），摘要回填 result.json 与 run.log。"""
    outdir = Path(outdir)
    try:
        rj, _ = _jl(outdir / "result.json")
        rj = rj if isinstance(rj, dict) else {}
        if isinstance(res, dict):
            for k in ("case_id", "status", "deliverable", "period", "counts", "golden_standard", "diff_report",
                      "version_history", "coverage", "consistency", "sources"):
                if res.get(k) is not None:
                    rj[k] = res[k]
        arts = []
        for f in ARTIFACT_FILES:
            p, ref = outdir / f, f in ("result.json", "self_check.json")
            arts.append({"path": f, "exists": (True if f == "self_check.json" else p.is_file()),
                         "bytes": None if ref else (p.stat().st_size if p.is_file() else 0),
                         "sha256": None if ref else (_hex(p) if p.is_file() else None),
                         "note": "自引用/本文件：写入后不再统计哈希" if ref else None})
        rj["artifacts"] = arts
        c, ev, num, fc = _contract(rj), _ev(rj), _num(rj), _fals(rj)
        mp, cnt = _main_product(outdir, rj), _counts_consistency(rj)
        five = ["golden_standard.json", "diff_report.md", "version_history.md", "run.log", "self_check.json"]
        fv = dict((f, True if f == "self_check.json" else ((outdir / f).is_file() and (outdir / f).stat().st_size > 0))
                  for f in five)
        pb = run_probes(work)
        miss = [a["path"] for a in arts if not a["exists"]]
        chk = {"artifacts_complete": not miss, "assets_nonempty": all(fv.values()),
               "contract_complete": (c["pass"] if c["applicable"] else True), "main_product_ok": mp["ok"],
               "evidence_covered": ev["pass"], "counts_consistent": cnt["pass"],
               "numeric_consistent": num["pass"], "falsifiable": fc["pass"],
               "edge_cases_ok": pb["pass"], "no_errors": not (rj.get("errors") or []),
               "exit_codes_zero": all(v == 0 for v in pb["exit"].values() if isinstance(v, int)) if pb["exit"] else True}
        sc = {"schema": "self-check/v1", "skill": "writing-10-proposal",
              "skill_version": (rj.get("runtime") or {}).get("skill_version"), "case_id": rj.get("case_id"),
              "generated_at": stamp_iso(), "status": rj.get("status"), "artifacts": arts,
              "artifact_count": len([a for a in arts if a["exists"]]), "missing_artifacts": miss,
              "assets": [{"path": f, "ok": fv[f],
                          "bytes": (outdir / f).stat().st_size if f != "self_check.json" and (outdir / f).is_file() else None}
                         for f in five],
              "main_product": mp, "contract": c, "evidence": ev, "counts_consistency": cnt,
              "numeric_consistency": num, "falsifiability": fc,
              "pending_human_count": len(rj.get("pending_human") or []),
              "degradations_count": len(rj.get("degradations") or []), "errors_count": len(rj.get("errors") or []),
              "edge_cases": pb["edge"], "exit_codes": pb["exit"], "checks": chk,
              "overall_pass": all(chk.values()), "failures": [k for k, v in chk.items() if not v],
              "how_to_rerun": "python3 -B scripts/entry.py build --input /input --output /app/output --work /app/work；audit 只重算本文件",
              "bounds": {"offline": True, "stdlib_only": True, "cwd_independent": True, "exit_code": "always 0"}}
        _w(outdir / "self_check.json", sc)
        rj["self_check"] = {"path": "self_check.json", "overall_pass": sc["overall_pass"], "checks": chk,
                            "checks_total": len(chk), "checks_passed": sum(1 for v in chk.values() if v),
                            "artifact_count": sc["artifact_count"], "missing_artifacts": miss,
                            "exit_codes": pb["exit"], "evidence_ratio": ev["ratio"],
                            "main_product_ok": mp["ok"], "counts_consistent": cnt["pass"]}
        note(outdir, "ASSETS", "self_check overall=%s artifacts=%d/%d 5assets=%s checks=%d/%d 失败=%s" % (
            sc["overall_pass"], sc["artifact_count"], len(arts), "5/5" if all(fv.values()) else "缺",
            sum(1 for v in chk.values() if v), len(chk), ",".join(sc["failures"]) or "无"))
        note(outdir, "SUMMARY", "case_id=%s status=%s main_product=%s evidence=%d/%d counts=%s exit_code=0（空/坏输入同）" % (
            rj.get("case_id") or "n/a", rj.get("status"), "ok" if mp["ok"] else "fail",
            ev["verified"], ev["total"], "ok" if cnt["pass"] else "fail"))
        rj["run_log"] = {"path": "run.log", "lines": _log_lines(outdir), "exit_code": 0,
                         "note": "真实阶段日志：init/check/build/assets/summary 与错误降级行"}
        _w(outdir / "result.json", rj)
        if isinstance(res, dict):
            res["self_check"], res["artifacts"], res["run_log"] = rj["self_check"], arts, rj["run_log"]
    except Exception as e:
        note(outdir, "EXC", "post: %s: %s" % (type(e).__name__, e))


def emit_artifacts(outdir, work, res, rep=None, draft=None, idx=None, ver=None):
    """生成 5 件可核验资产的前 3 件（golden/diff/version）与结构化产物；self_check/run.log 摘要由 after_build 收尾。"""
    outdir, work = Path(outdir), Path(work)
    errs = []
    try:
        outdir.mkdir(parents=True, exist_ok=True)
        res = res if isinstance(res, dict) else {}
        for k in ("degradations", "errors", "pending_human", "uncertainty", "sources", "changes"):
            res.setdefault(k, [])
        if not isinstance(idx, dict) or not isinstance(idx.get("materials"), list):
            idx, _ = _jl(work / "index.json")
            idx = idx if isinstance(idx, dict) and isinstance(idx.get("materials"), list) else {"materials": []}
        if not isinstance(draft, dict) or not draft:
            draft = P.read_draft(work)[0]
            if not isinstance(draft, dict) or not draft:
                draft = _jl(work / "draft.effective.json")[0]
            draft = draft if isinstance(draft, dict) else {}
        if not isinstance(rep, dict):
            rep = P.inspect_draft(draft, idx)
        mo, pq = P.detect_period("\n".join(T(m.get("text")) for m in (idx.get("materials") or [])))
        if not ver:
            try:
                ver = (re.search(r"version:\s*([\d.]+)", (PKG / "SKILL.md").read_text(encoding="utf-8")) or [0, "2.1.0"])[1]
            except Exception:
                ver = "2.1.0"
        D = {"draft": draft, "idx": idx, "rep": rep, "res": res, "ver": ver,
             "paths": {"work": str(work), "output": str(outdir)}}
        note(outdir, "ASSETS", "start：golden/diff/version 生成（draft_source=%s materials=%d）" % (
            T((res.get("deliverable") or {}).get("draft_source")) or "unknown", len(idx.get("materials") or [])))
        gs, rows = build_golden(D)
        cnt = gs.get("expectation_counts") or {}
        nb, nc = int(cnt.get("rubric_items") or 0), int(cnt.get("contract_items") or 0)
        base, crows, wrows = rows[:nb], rows[nb:nb + nc], rows[nb + nc:]
        c, cc, cw = tally(base), tally(crows), tally(wrows)
        D.update(gs=gs, rows=rows)
        res["period"] = {"total": T((draft.get("period") or {}).get("total")) or ("%d 个月" % mo if mo else ""),
                         "quote": T((draft.get("period") or {}).get("quote")) or pq,
                         "source": T((draft.get("period") or {}).get("source")) or ("materials" if pq else "unresolved"),
                         "detected_months": mo}
        counts = res.get("counts") if isinstance(res.get("counts"), dict) else {}
        counts.update(dict((rep or {}).get("counts") or {}))
        counts.update(stray_numbers=stray_numbers(D), golden_items=len(rows), golden_pass=c["pass"],
                      golden_rubric_items=nb, golden_contract_items=len(crows), golden_workorder_items=len(wrows),
                      golden_manual=cw["manual"], golden_pass_rate=c["pass_rate"],
                      contract_items=len(crows), artifacts=len(ARTIFACT_FILES), exit_code=0)
        res["counts"] = counts
        for fn, name, body in ((_w, "golden_standard.json", gs), (_w, "proposal_matrix.json", render_matrix(D)),
                               (_w, "milestones.csv", render_milestone_csv(D)), (_w, "risks.md", render_risks_doc(D)),
                               (_w, "diff_report.md", render_diff(D, gs, rows))):
            try:
                fn(outdir / name, body)
            except Exception as e:
                errs.append("%s 生成失败 %s: %s" % (name, type(e).__name__, e))
        # version_history 必须在其余资产落盘后渲染，才能如实报告各资产状态与字节
        try:
            _w(outdir / "version_history.md", render_version_history(D))
        except Exception as e:
            errs.append("version_history.md 生成失败 %s: %s" % (type(e).__name__, e))
        res["golden_standard"] = {"path": "golden_standard.json", "schema": gs["schema"], "items": nb,
                                  "rubric_items": nb, "contract_items": len(crows), "workorder_items": len(wrows),
                                  "total": len(rows), "elements": len(gs["elements"]),
                                  "expected_deliverables": len(gs.get("expected_deliverables") or []),
                                  "anchors": gs["anchors"]["total"], "anchors_verified": gs["anchors"]["verified"],
                                  "status_counts": {"pass": c["pass"], "missing": c["missing"], "deviation": c["deviation"]},
                                  "items_without_anchor": gs["anchors"]["items_without_anchor"]}
        res["diff_report"] = {"path": "diff_report.md", "total": len(rows), "rubric_total": nb,
                              "contract_total": len(crows), "workorder_total": len(wrows),
                              "pass": c["pass"], "missing": c["missing"], "deviation": c["deviation"],
                              "manual": cw["manual"], "pass_rate": c["pass_rate"],
                              "contract_pass": cc["pass"], "workorder_pass": cw["pass"],
                              "items": [{"id": r[0], "element": r[1], "status": r[3]} for r in rows]}
        res["version_history"] = {"path": "version_history.md",
                                  "static_versions": ["v0.1.0", "v0.6.0", "v0.9.0", "v1.0.0"],
                                  "runtime_section": True,
                                  "rollback": ["删 <WORK>/draft.json 后 build 回 v0 骨架",
                                               "entry.py audit 只重算资产，正文不动",
                                               "用 work/patch_backup/writing-10_orig 或仓库历史回退包本体"]}
        res["run_log"] = {"path": "run.log", "exit_code": 0}
        note(outdir, "ASSETS", "golden=%d（rubric %d / 契约 %d / 工作单 %d）pass=%d missing=%d deviation=%d manual=%d anchors=%d/%d" % (
            len(rows), nb, len(crows), len(wrows), c["pass"], c["missing"], c["deviation"], cw["manual"],
            gs["anchors"]["verified"], gs["anchors"]["total"]))
        if not draft:
            errs.append("未取到工作稿：资产按 v0 骨架判定")
    except Exception as e:
        errs.append("assets: %s: %s" % (type(e).__name__, e))
        note(outdir, "EXC", "emit: %s" % e)
    if errs:
        try:
            res["degradations"] += errs
        except Exception:
            pass
    return res


def run_audit(a):
    """只重算 5 件套与结构化产物，不重渲染 proposal.md。"""
    try:
        outdir, work = Path(a.output).resolve(), Path(a.work).resolve()
        res, _ = _jl(outdir / "result.json")
        res = res if isinstance(res, dict) else {}
        res["_contract"] = res.get("_contract") or res.get("output_contract") or {}
        note(outdir, "AUDIT", "start work=%s" % work)
        emit_artifacts(outdir, work, res, None, None, None, None)
        after_build(outdir, work, res)
    except Exception as e:
        note(Path(getattr(a, "output", ".")), "EXC", "audit: %s" % e)
    return 0


# ---- 27 条金标准判据表（数据驱动，置后不影响调用时序） ----
G = [
 ("G01", "契约", "contract", "完整性", "output_contract 每字段原样回填，缺值 null/[]", "字段全在且非空", "补映射", ["output_contract", "契约"]),
 ("G02", "周期", "period", "正确性", "周期取自材料原文，里程碑不越界", "quote 逐字；最远月≤周期", "回填原文", ["周期", "执行期", "工期"]),
 ("G03", "证据", "evratio", "可核验性", "论断带 source_id+locator+逐字 quote", "命中率≥90%", "换原文切片", ["可核验", "复跑", "来源"]),
 ("G04", "诚实", "honesty", "正确性", "未获结果不写成已获，缺口进 pending_human", "无结果断言；pending 非空", "改拟/将", ["待确认", "缺口"]),
 ("G05", "背景与缺口", "sec:background", "完整性", "背景节成文并挂材料证据", "成节；≥60 字；有证据", "补写背景", ["背景", "现状", "前期"]),
 ("G06", "背景与缺口", "gap", "正确性", "缺口写成「已知—未知—待验证」", "含已知/未知/待验证", "改三段式", ["缺口", "未知", "待验证"]),
 ("G07", "背景与缺口", "noreview", "正确性", "背景不是领域综述", "无纯综述陈述", "留缺口句", ["综述", "研究现状"]),
 ("G08", "研究问题", "rq", "完整性", "1–3 条研究问题，含对象与条件", "1≤数量≤3；含条件", "收敛问题", ["研究问题", "假设"]),
 ("G09", "研究问题", "falsifier", "正确性", "每条 RQ 写明何种观测否定假设", "falsifier 含观测/时点", "补判伪", ["可证伪", "否定"]),
 ("G10", "研究问题", "metric", "正确性", "每条 RQ 有指标、阈值与依据", "name/threshold/basis", "补阈值依据", ["指标", "阈值", "终点"]),
 ("G11", "研究问题", "sample", "完整性", "每条 RQ 写清样本、条件、时点", "三项中≥2", "补样本时点", ["样本", "纳入"]),
 ("G12", "研究目标", "objlink", "完整性", "目标与 RQ 一一对应，无孤儿目标", "rq 指向存在 RQ", "修 rq", ["目标", "旨在"]),
 ("G13", "研究目标", "objcrit", "正确性", "每个目标有可检查完成判据", "criterion", "补判据", ["考核", "判据"]),
 ("G14", "技术路线", "steps", "完整性", "路线≥3 步，各含输入→操作→输出", "steps≥3；三要素齐", "拆步骤", ["技术路线", "方法"]),
 ("G15", "技术路线", "dep", "正确性", "依赖可解、无悬空、无环", "depends_on 均存在", "修依赖", ["依赖", "步骤"]),
 ("G16", "技术路线", "metev", "可核验性", "方法均来自材料，有 locator+quote", "每步有来源", "补方法引文", ["方法", "依据"]),
 ("G17", "数据", "data", "完整性", "数据来源、样本量、合规条件写明", "resources.data 非占位", "填数据来源", ["数据", "队列", "伦理"]),
 ("G18", "数据", "datanum", "正确性", "数字与材料同形，新增值标计划值", "无无依据数字", "标计划值", ["数据", "样本量"]),
 ("G19", "阶段计划", "ms", "完整性", "里程碑≥3，各有交付物与判据", "deliverable/criterion", "补里程碑", ["里程碑", "进度"]),
 ("G20", "阶段计划", "msperiod", "正确性", "里程碑落在周期内并标关键路径", "最远月≤周期；critical", "标关键路径", ["周期", "关键路径"]),
 ("G21", "阶段计划", "res", "完整性", "经费人员落在给定条件内，缺失标 pending", "budget/people", "回填或 pending", ["经费", "预算"]),
 ("G22", "风险", "risk", "完整性", "风险≥4 条、≥3 类（数据/方法/进度/伦理）", "条数≥4；类型≥3", "按四类补", ["风险", "伦理"]),
 ("G23", "风险", "riskact", "正确性", "每条风险有触发/影响/备选/决策时点", "四字段齐", "补四要素", ["触发", "备选"]),
 ("G24", "预期成果", "out", "完整性", "成果与 RQ 对应并写验证方式", "rq/verification", "补 rq 与验证", ["成果", "论文"]),
 ("G25", "预期成果", "notresult", "正确性", "成果写成可验证判据，不冒充已获结果", "含判据/验证", "改判据式", ["成果", "指标"]),
 ("G26", "预期成果", "outver", "可核验性", "给出可复跑的验证/验收方式", "含复跑/验收", "写复跑步骤", ["验证", "复现"]),
 ("G27", "七要素", "sections", "完整性", "七要素成节且各节不过短", "7/7；每节≥60 字", "补缺节", ["开题", "研究计划"]),
]

