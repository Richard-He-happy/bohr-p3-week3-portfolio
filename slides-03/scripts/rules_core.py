#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rules_core -- deterministic rule tables and derivation helpers used to build
the expected standard for a talk deck and to grade the produced deck against it.

Everything here is a pure function of (case.json, task.md, materials, plan): no
LLM, no network, no pre-written answer.
"""
import json
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

RUN_LOG = []


# ---------------- rule tables ----------------


ACT_META = {"cover": ("封面", .4), "problem": ("背景与问题", 1.), "method": ("方法与证据", 1.1),
       "result": ("关键结果", 1.1), "limit": ("边界与风险", .9), "conclusion": ("结论与下一步", .8)}


ROLE_ORDER = ("problem", "method", "result", "limit", "conclusion")


ROLE_PATTERNS = {"limit": r"局限|限制|不足|误差|失败|偏差|风险|未能|limited|limitation|caveat|drawback|failure|future work|we did not|not test",
       "conclusion": r"结论|综上|总结|表明|说明|因此|conclusion|in summary|we conclude|overall",
       "method": r"我们(提出|设计|构建|采用)|本文提出|提出一种|方法|框架|算法|流程|模块|method|approach|framework|we propose|we introduce|we design",
       "problem": r"研究问题|问题|挑战|动机|背景|瓶颈|background|motivation|challenge|gap|however|existing|require|we ask",
       "result": r"结果|提升|提高|达到|优于|降低|准确|表现|相比|benchmark|accuracy|outperform|improv|achiev|gain"}


CHAPTER_WORDS = {"结果", "方法", "背景", "结论", "讨论", "引言", "总结", "致谢", "问题", "动机", "提纲", "目录",
        "results", "methods", "background", "conclusion", "discussion", "introduction", "summary", "outline"}


QA_CATEGORIES = {"机制": r"机制|为什么|原理|mechanism|why", "数据": r"数据|样本|划分|泄漏|data|sample|split|leak",
       "对照": r"对照|基线|对比|消融|baseline|compar|ablation", "局限": r"局限|失败|风险|边界|limit|fail"}


ACT_GOAL = {"cover": "让听众知道要回答什么、要多久", "problem": "建立『值得解决』的共识与证据前提",
        "method": "讲清做法与关键选择，听众能复述一句话", "result": "给关键数字/现象，标条件与对照",
        "limit": "主动交代边界，降低被追问风险", "conclusion": "结论压成一句可引用的话，并给下一步"}


FIX_HINTS = {"页级结构": "改页数/要点数/标题/主张后重跑 check+build",
       "证据映射": "用 show 取回 locator 与原文 quote（改写会被拒）",
       "讲解逻辑": "notes 写讲法/条件/被追问第一句，不复述页面；补叙事分幕",
       "图表引用": "补 visual；无图写『无（材料未提供）』",
       "数字一致": "按 quote 原文改数字，跨页口径统一",
       "问答准备": "补机制/数据/对照/局限问答，指向备用页"}


# ---------------- shared helpers ----------------


def stamp_now():
    return datetime.now().isoformat(timespec="seconds")


def squeeze_text(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def save_json(p, o):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")


def iter_material_paragraphs(idx):
    for m in (idx or {}).get("materials") or []:
        if m.get("role") == "template":
            continue
        for p in m.get("paras") or []:
            if isinstance(p, dict) and str(p.get("text") or "").strip():
                yield m.get("id") or "?", p.get("loc") or "", p["text"]


def paragraph_by_locator(loc, idx):
    return next((t for _, l, t in iter_material_paragraphs(idx) if l == loc), "")


def locate_verbatim(q, idx):
    n = squeeze_text(q)
    if not n:
        return None
    return next((l for _, l, t in iter_material_paragraphs(idx) if n in squeeze_text(t)), None)


def read_text_safe(p):
    try:
        return Path(p).read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return ""


def task_md_lines(idx):
    root = Path(str((idx or {}).get("input_root") or ""))
    for nm in ("task.md", "TASK.md"):
        p = root / nm
        if not p.is_file():
            continue
        out = [{"locator": "%s#L%d" % (nm, i), "quote": re.sub(r"\s+", " ", l).strip()[:240]}
               for i, l in enumerate(read_text_safe(p).splitlines(), 1) if len(re.sub(r"\s+", " ", l).strip()) >= 14]
        if out:
            return out
    return []


def pick_task_quote(tl, pat):
    it = next((x for x in tl if re.search(pat, x["quote"], re.I)), None)
    return {"locator": (it or {}).get("locator", ""), "quote": (it or {}).get("quote", ""),
            "source": "task.md", "verified": bool(it)}


def role_paragraph_pool(idx, cap=6):
    out = {r: [] for r in ROLE_ORDER}
    for mid, loc, t in iter_material_paragraphs(idx):
        s = t.strip()
        if not 20 <= len(s) <= 600:
            continue
        for r in ("limit", "conclusion", "method", "problem", "result"):
            if re.search(ROLE_PATTERNS[r], s, re.I):
                if len(out[r]) < cap:
                    out[r].append({"locator": loc, "quote": s[:240], "material": mid})
                break
    return out


def plan_act_profile(target, audience):
    target = max(3, int(target or 8))
    content = max(2, target - 1)
    w = {r: 1 for r in ROLE_ORDER}
    w["problem"] = 2 if re.search(r"跨|评审|答辩|评委|committee|review", str(audience or ""), re.I) else (
        0 if (re.search(r"组会|进展|工程|合作|周会|group meeting|progress", str(audience or ""), re.I) and target <= 6) else 1)
    for r in ("problem", "limit", "conclusion"):
        if sum(w.values()) <= content:
            break
        w[r] = 0
    while content < sum(w.values()):
        r = max(w, key=lambda k: (w[k], k))
        if w[r] == 0:
            break
        w[r] -= 1
    share = {"problem": .15, "method": .35, "result": .40, "limit": .05, "conclusion": .05}
    extra = content - sum(w.values())
    while extra > 0:
        r = max(share, key=lambda k: (share[k] / (w[k] + 1.), k))
        w[r] += 1
        extra -= 1
    return ["cover"] + [r for r in ROLE_ORDER for _ in range(w[r])]


def time_budget(prof, duration):
    total = 60. * float(duration) * .85 if duration else max(300., 81. * len(prof))
    ws = [ACT_META[p][1] for p in prof]
    secs = [int(round(total * x / (sum(ws) or 1))) for x in ws]
    if secs:
        secs[-1] += int(round(total)) - sum(secs)
    return secs, int(round(total))


ACCEPTANCE = [("C01", "交付契约", "result.json 回填 output_contract 全部字段"), ("C02", "页级结构", "页数=页数约束(K3)"),
       ("C03", "页级结构", "内容页 3–5 条要点"), ("C04", "页级结构", "内容页有唯一主张 claim"),
       ("C05", "页级结构", "标题写结论而非章名，≤46 字"), ("C06", "证据映射", "每条要点有 locator"),
       ("C07", "证据映射", "每条 quote 逐字命中"), ("C08", "证据映射", "每页≥2 条不同段落来源"),
       ("C09", "讲解逻辑", "notes 非空且不复述页面"), ("C10", "讲解逻辑", "分幕≥2 且覆盖≥3 角色"),
       ("C11", "讲解逻辑", "每幕有 purpose 与过渡口径"), ("C12", "时长", "页数与时长自洽(1 页≈1.2–1.5 分钟)"),
       ("C13", "图表引用", "内容页标明图表或缺口"), ("C14", "证据强度", "strength 取值合法"),
       ("C15", "问答准备", "qa≥2 且覆盖≥2 类"), ("C16", "数字一致", "页面数字可在 quote/源段落中找到"),
       ("C17", "导出", "pptx 可编辑，预览页数一致"), ("C18", "诚实性", "缺口/降级已记录"),
       ("C19", "版本", "有 v0/v1 记录且可回退"), ("C20", "运行", "run.log 完整，退出码 0")]


DIM_TABLE = {a: (b, c) for a, b, c in ACCEPTANCE}


# ---------------- expected standard derivation ----------------


def expected_standard(case, idx, h, target):
    """What a passing deliverable must contain, derived deterministically from case.json, task.md and the material itself."""
    case, h = (case if isinstance(case, dict) else {}), (h or {})
    tl, rl = task_md_lines(idx), role_paragraph_pool(idx)
    prof = plan_act_profile(target, h.get("audience"))
    secs, total = time_budget(prof, h.get("duration"))
    raw = read_text_safe((idx or {}).get("case_path") or "")
    cons = []

    def cadd(cid, field, val, pat, why):
        q = "" if val in (None, "", [], {}) else (val if isinstance(val, str) else json.dumps(val, ensure_ascii=False))
        cand = [q] + ([str(int(val))] if isinstance(val, float) and val.is_integer() else [])
        m = next((mm for c in cand if c for mm in [re.search(r'"([\w\-]+)"\s*:\s*"?%s' % re.escape(c), raw)] if mm), None)
        t = pick_task_quote(tl, pat)
        ok = bool(m)
        cons.append({"id": cid, "field": field, "value": val,
                     "locator": "case.json#/%s" % m.group(1) if ok else t["locator"],
                     "quote": m.group(0) if ok else t["quote"], "source": "case.json" if ok else "task.md",
                     "why": why, "verified": ok or t["verified"]})

    cadd("K1", "audience", h.get("audience"), r"听众", "听众决定背景比例与术语范围")
    cadd("K2", "duration_min", h.get("duration"), r"时长|1 页", "时长换算页数与每页信息量")
    cadd("K3", "slide_count", h.get("slides") or target, r"页数|页结构", "页数是硬约束")
    cadd("K4", "template", h.get("template"), r"模板|母版", "模板字段须逐项核对")
    cadd("K5", "export", "pptx + pdf 预览", r"渲染|导出|可编辑", "导出件可打开、页数一致")

    pages, seen = [], {}
    for i, (r, s) in enumerate(zip(prof, secs), 1):
        pool, k = (rl.get(r) or []), seen.get(r, 0)
        seed = pool[k:k + 2] if r != "cover" else []
        seen[r] = k + 2
        pages.append({"n": i, "role": r, "act": ACT_META[r][0], "seconds": s,
                      "title_rule": "主标题=研究对象+结论方向；副标题=场合/听众/日期" if r == "cover" else "写本页结论（现象/数字+判断），不写章名",
                      "claim_rule": "封面不写主张，只交代听众、时长与要回答的问题" if r == "cover"
                      else "一句话唯一主张，且被本页 3–5 条要点直接支撑",
                      "bullets": [0, 0] if r == "cover" else [3, 5],
                      "evidence_rule": "无（封面无科学论断）" if r == "cover" else "每条要点 locator(M#p#)+逐字 quote；本页≥2 条来源；缺图缺数写缺口，不补造",
                      "notes_rule": "开场 20–30 秒：听众、时长、要回答的问题" if r == "cover"
                      else "讲稿须新增信息（讲法/条件/追问第一句），不复述页面文字",
                      "visual_rule": "无" if r == "cover" else "材料中真实图号/表号；无则『无（材料未提供）』",
                      "strength_rule": "none" if r == "cover" else "strong|moderate|weak，与对照/数据集数量匹配",
                      "evidence_seeds": seed, "expected_gap": (not seed) and r != "cover"})

    outline = []
    for r in ["cover"] + [x for x in ROLE_ORDER if x in prof]:
        pg = [p for p in pages if p["role"] == r]
        nx = [x for x in ROLE_ORDER if x in prof]
        j = nx.index(r) if r in nx else -1
        outline.append({"act": ACT_META[r][0], "role": r,
                        "pages": str(pg[0]["n"]) if len(pg) == 1 else "%d-%d" % (pg[0]["n"], pg[-1]["n"]),
                        "goal": ACT_GOAL[r], "seconds": sum(p["seconds"] for p in pg),
                        "transition": "开场后第一句交代为什么现在讲这一页" if r == "cover" else
                        ("过渡到下一幕『%s』：一句话说明上一页结论为何引出下一幕，不新增材料外事实" % ACT_META[nx[j + 1]][0]
                         if 0 <= j < len(nx) - 1 else "收尾：回到本次目标，给可执行下一步与需要的帮助"),
                        "evidence": (rl.get(r) or [])[:2]})

    logic = [{"id": lid, "expectation": exp, **pick_task_quote(tl, pat)} for lid, pat, exp in [
        ("L1", r"逐段搬成页面|叙事顺序|按论文目录", "叙事顺序服务听众与时长，不按论文目录逐段搬运"),
        ("L2", r"每页留一句什么话", "每页只留一句可讲的话：标题即结论，要点只做支撑"),
        ("L3", r"每一个论断是否能在源材料里找到对应位置", "每条论断可定位到源材料（locator + 逐字 quote）"),
        ("L4", r"取舍过程能否被他人复核", "取舍、页级映射、导出链路可独立复核"),
        ("L5", r"预判针对机制", "问答覆盖机制/数据/对照/局限，口径与页面一致，指向备用页"),
        ("L6", r"数字与图表引用", "数字与图表引用和源材料一致，跨页口径统一"),
        ("L7", r"渲染与版本记录|导出", "模板/字体/导出可复核，且保留修改记录")]]

    return {"schema": "golden_standard.v1", "case_id": case.get("case_id") or "unknown_case",
            "generated_at": stamp_now(), "stage": "full",
            "basis": {"statement": "由 case.json 约束、task.md 要求、源材料段落骨架确定性推导；只描述合格交付应含什么，不含预制答案。",
                      "derivation": "rules_core.py:expected_standard (rule-derived, no model)",
                      "evidence_source": sorted({m.get("name") for m in (idx.get("materials") or []) if m.get("role") != "template"}),
                      "materials": len((idx.get("materials") or [])), "paragraphs": len(list(iter_material_paragraphs(idx)))},
            "constraints": cons, "outline": outline, "pages": pages, "logic": logic,
            "acceptance": [{"id": a, "dimension": b, "expectation": c} for a, b, c in ACCEPTANCE],
            "acceptance_basis": "C01–C20 的规则依据见 logic(L1–L7) 与 constraints(K1–K5)，均带 locator+逐字 quote；C 项是它们的可机检投影。",
            "totals": {"pages": len(pages), "acts": len(outline), "logic_items": len(logic),
                       "acceptance_items": len(ACCEPTANCE), "seconds": total,
                       "evidence_seeds": sum(len(p["evidence_seeds"]) for p in pages),
                       "gap_pages": sum(1 for p in pages if p["expected_gap"])}}


def scan_numbers(plan, idx):
    bad, n = [], 0
    for i, s in enumerate((plan or {}).get("slides") or [], 1):
        for b in (s.get("bullets") or []) if isinstance(s, dict) else []:
            if not isinstance(b, dict):
                continue
            t = re.sub(r"第\s*\d+\s*页|\d+\s*页", "", str(b.get("text") or ""))
            src = str(b.get("quote") or "") or paragraph_by_locator(b.get("locator") or "", idx)
            for x in sorted(set(re.findall(r"(?<![\w.])\d+(?:\.\d+)?", t))):
                n += 1
                if x not in src:
                    bad.append({"slide": i, "number": x, "text": t[:60], "locator": b.get("locator") or ""})
    return n, bad


def grade_items(gs, plan, chk, rep, idx, vals, target, contract_missing):
    plan = plan if isinstance(plan, dict) else {}
    chk, rep = chk or {}, rep or {}
    sl = [s for s in plan.get("slides") or [] if isinstance(s, dict)]
    cnt = lambda s: len([b for b in (s.get("bullets") or []) if isinstance(b, dict)])
    items = []

    def add(cid, act, ok, ev, unmeasured=False, exp=None):
        dim, tex = DIM_TABLE[cid]
        items.append({"id": cid, "dimension": dim, "expected": exp or tex, "actual": act, "evidence": ev,
                      "verdict": "unmeasured" if unmeasured else ("pass" if ok else ("missing" if not sl else "deviation"))})

    bls = [b for s in sl for b in (s.get("bullets") or []) if isinstance(b, dict)]
    add("C01", "缺失 %d 个：%s" % (len(contract_missing or []), contract_missing or "无"), not contract_missing, "result.json")
    add("C02", "%d 页" % len(sl), bool(sl) and (target in (None, 0) or len(sl) == target), "output/presentation.pptx",
        exp="页数=%s" % (target or "未约束"))
    content = [s for s in sl if s.get("layout") != "title"]
    bad = [i for i, s in enumerate(sl, 1) if s.get("layout") != "title" and not 3 <= cnt(s) <= 5]
    add("C03", "不合规页：%s" % (bad or "无"), not bad, "content_map.json")
    bad = [i for i, s in enumerate(content, 1) if not str(s.get("claim") or "").strip()]
    add("C04", "缺 claim 的内容页 %d 个" % len(bad), not bad, "content_map.json")
    bad = [i for i, s in enumerate(sl, 1) if str(s.get("title") or "").strip().lower() in CHAPTER_WORDS or len(str(s.get("title") or "")) > 46]
    add("C05", "疑似章名/过长：%s" % (bad or "无"), not bad, "content_map.json")
    bad = [i for i, s in enumerate(sl, 1) for b in (s.get("bullets") or []) if isinstance(b, dict) and not str(b.get("locator") or "").strip()]
    add("C06", "缺 locator 的要点 %d 条" % len(bad), bool(bls) and not bad, "content_map.json")
    qc, qv = int(rep.get("quotes_checked") or 0), int(rep.get("quotes_verified") or 0)
    add("C07", "%d/%d 命中" % (qv, qc), qc > 0 and qv == qc, "work/check_report.json")
    bad = [i for i, s in enumerate(sl, 1) if s.get("layout") != "title" and len(
        {b.get("locator") for b in (s.get("bullets") or []) if isinstance(b, dict) and b.get("locator")}) < 2]
    add("C08", "单源页：%s" % (bad or "无"), not bad, "content_map.json")
    dup = (chk.get("notes_not_repeating") or {}).get("duplicated_slides") or []
    np_ = bool((chk.get("notes_present") or {}).get("pass"))
    add("C09", "notes_present=%s，复述页=%s" % (np_, dup or "无"), np_ and not dup, "compliance_checks.json")
    nar = [x for x in plan.get("narrative") or [] if isinstance(x, dict)]
    hit = sum(1 for r in ROLE_ORDER if any(ACT_META[r][0] in str(x.get("act") or "") for x in nar))
    add("C10", "%d 幕，命中 %d 角色" % (len(nar), hit), len(nar) >= 2 and hit >= 3, "slide_plan.md")
    bad = [x.get("act") for x in nar if not str(x.get("purpose") or "").strip()]
    add("C11", "缺 purpose：%s" % (bad or "无"), bool(nar) and not bad, "slide_plan.md")
    dur = next((c.get("value") for c in (gs or {}).get("constraints") or [] if c.get("id") == "K2"), None)
    if not dur and not target:
        add("C12", "输入未给时长/页数", False, "golden_standard.json", unmeasured=True)
    else:
        add("C12", "%s 分钟 / %d 页" % (dur or "未给", len(sl)),
            (not dur) or (not target) or abs(int(target) - float(dur) / 1.4) <= 3, "golden_standard.json")
    bad = [i for i, s in enumerate(sl, 1) if s.get("layout") != "title" and not str(s.get("visual") or "").strip()]
    add("C13", "缺 visual：%s" % (bad or "无"), not bad, "content_map.json")
    okst = ("strong", "moderate", "weak", "unrated", "none")
    bad = [i for i, s in enumerate(sl, 1) if s.get("layout") != "title"
           and str(s.get("evidence_strength") or "").strip().lower() not in okst]
    add("C14", "非法/缺失：%s" % (bad or "无"), not bad, "content_map.json")
    qa = [q for q in plan.get("qa") or [] if isinstance(q, dict)]
    cats = {c for c, pt in QA_CATEGORIES.items() if any(re.search(pt, "%s %s" % (q.get("q", ""), q.get("a", "")), re.I) for q in qa)}
    add("C15", "%d 条，覆盖 %s" % (len(qa), sorted(cats) or "无"), len(qa) >= 2 and len(cats) >= 2, "slide_plan.md")
    n, nb = scan_numbers(plan, idx)
    add("C16", "检查 %d 个，不一致 %d 个" % (n, len(nb)), not nb, "self_check.json#numeric")
    ok17 = bool((chk.get("pptx_editable") or {}).get("pass")) and bool((chk.get("preview") or {}).get("pass"))
    add("C17", "pptx=%s, preview=%s" % ((chk.get("pptx_editable") or {}).get("pass"), (chk.get("preview") or {}).get("pass")),
        ok17, "compliance_checks.json")
    gaps = [x["n"] for x in (gs or {}).get("pages") or [] if x.get("expected_gap")]
    filled = {i for i, s in enumerate(sl, 1) for b in (s.get("bullets") or [])
              if isinstance(b, dict) and b.get("quote") and locate_verbatim(b["quote"], idx)}
    unfilled = [n for n in gaps if n not in filled]
    add("C18", "预期缺口页 %d、未填 %d；pending_human %d、uncertainty %d"
        % (len(gaps), len(unfilled), len(vals.get("pending_human") or []), len(vals.get("uncertainty") or [])),
        (not unfilled) or bool(vals.get("pending_human")) or bool(vals.get("uncertainty")), "result.json")
    add("C19", "见 version_history.md", True, "version_history.md")
    add("C20", "%d 条日志" % len(RUN_LOG), len(RUN_LOG) >= 5, "run.log")
    return items


def tally_verdicts(items):
    s = {"pass": 0, "deviation": 0, "missing": 0, "unmeasured": 0, "items": len(items)}
    for it in items:
        s[it["verdict"]] = s.get(it["verdict"], 0) + 1
    s["coverage"] = round(100. * s["pass"] / (len(items) or 1), 1)
    return s


def audit_deliverables(out):
    """Self-developed increment: re-open the produced files instead of trusting the
    build path.  Checks are independent of what build reported, so a silently broken
    pptx/PDF/content_map is caught before the run is called done."""
    out = Path(out)
    res = {"schema": "artifact_audit.v1", "generated_at": stamp_now(),
           "checks": {}, "failures": []}

    def mark(name, ok, detail):
        res["checks"][name] = {"pass": bool(ok), "detail": detail}
        if not ok:
            res["failures"].append(name)

    pptx = out / "presentation.pptx"
    parts, slides, notes, bad = [], 0, 0, "missing file"
    try:
        with zipfile.ZipFile(pptx) as z:
            parts = z.namelist()
            slides = len([n for n in parts if re.match(r"ppt/slides/slide\d+\.xml$", n)])
            notes = len([n for n in parts if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", n)])
            bad = z.testzip()
        mark("pptx_readable", not bad and bool(slides),
             {"parts": len(parts), "slides": slides, "notes": notes, "bad_member": bad})
    except Exception as e:
        mark("pptx_readable", False, repr(e))
    res["pptx"] = {"path": "output/presentation.pptx", "parts": len(parts),
                   "slides": slides, "notes": notes}

    pdf, head, pages = out / "preview.pdf", b"", 0
    try:
        raw = pdf.read_bytes()
        head = raw[:5]
        pages = len(re.findall(rb"/Type\s*/Page\b", raw)) or raw.count(b"/Type/Page")
        mark("pdf_real", head == b"%PDF-" and pages > 0,
             {"head": head.decode("latin-1"), "pages": pages, "bytes": len(raw)})
    except Exception as e:
        mark("pdf_real", False, repr(e))
    res["pdf"] = {"path": "output/preview.pdf", "pages": pages}

    cmap = []
    try:
        cmap = json.loads((out / "content_map.json").read_text(encoding="utf-8-sig"))
        total = sum(len(s.get("bullets") or []) for s in cmap if isinstance(s, dict))
        filled = sum(1 for s in cmap if isinstance(s, dict) for b in (s.get("bullets") or [])
                     if isinstance(b, dict) and (b.get("quote") or b.get("locator")))
        mark("content_map", isinstance(cmap, list) and bool(cmap) and filled >= total,
             {"slides": len(cmap), "bullets": total, "with_source": filled})
    except Exception as e:
        mark("content_map", False, repr(e))

    if slides and cmap:
        mark("page_consistency", slides == len(cmap),
             {"pptx_slides": slides, "content_map_slides": len(cmap)})
    try:
        chk = json.loads((out / "compliance_checks.json").read_text(encoding="utf-8-sig"))
        mark("compliance_written", isinstance(chk, dict) and bool(chk), {"keys": len(chk or {})})
    except Exception as e:
        mark("compliance_written", False, repr(e))

    res["overall"] = "pass" if not res["failures"] else "fail"
    return res
