#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reader_kit.py - shared plumbing for the source-bound paper QA runner.

Holds everything the runner should not care about: case discovery, paragraph and
question normalisation, measured-value extraction, contract echoing and the JSON /
CSV emitters. run_reader.py stays focused on ranking, quoting and answer assembly.
Standard library only; every resource path is derived from this file's location,
so the runner behaves the same no matter which directory it is launched from.
"""
import hashlib
import json
import re
import unicodedata
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REF_DIR = SCRIPT_DIR.parent / "references"

QID_KEYS = ("question_id", "qid", "questionid", "q_id", "id", "no", "序号", "编号")
QKEY_TEXT = ("question", "question_text", "text", "q", "query", "stem", "content", "prompt", "问题", "题目")
QKEY_PID = ("paragraph_id", "para_id", "paraid", "pid", "block_id", "id", "label", "段落编号")
QKEY_PTXT = ("text", "content", "body", "paragraph", "txt", "value", "sentence", "原文")
QKEY_SECTION = ("section", "section_name", "heading", "part", "chapter", "章节")
CASE_KEY_NAMES = ("case_id", "caseid", "case_key", "case")
PAPER_KEY_NAMES = ("paper_id", "paperid", "document_id", "doc_id", "doi", "paper")
VERSION_KEY_NAMES = ("material_version", "materialversion", "version", "material_rev")
PARAGRAPH_LIST_KEYS = ("paragraphs", "paragraph_list", "paras", "segments", "blocks", "text_blocks",
         "corpus", "sentences", "paragraph_texts", "段落")
QUESTION_LIST_KEYS = ("questions", "question_list", "question_set", "qas", "queries", "problems", "tasks", "问题清单")
SECTION_CONTAINER_KEYS = ("sections", "materials", "manuscript", "paper_sections", "body_sections")
TABLE_KEYS = ("tables", "table_texts", "table")
FIGURE_KEYS = ("figures", "figure_captions", "captions", "figure_legends", "legends")
BIBLIO_KEYS = ("references", "bibliography", "refs", "citations")
CONTRACT_FILL_KEYS = {"case_id", "status", "result", "claims", "uncertainties", "answers", "unanswered_parts",
        "coverage", "sources", "pending_human", "errors", "degradations", "changes", "runtime",
        "counts", "method_notes", "question_ids", "contract_keys", "summary", "verification",
        "primary_result", "evidence"}

# One entry per line: "zh = en1 ; en2". Kept inline so a missing term map is harmless.
_INLINE_TERM_LINES = """强度 = strength
抗拉 = tensile
硬度 = hardness
热处理 = heat treatment
合金 = alloy
温度 = temperature ; annealing temperature
应变 = strain
应力 = stress
晶粒 = grain
缺陷 = defect
疲劳 = fatigue
磨损 = wear
方法 = method
模型 = model
数据集 = dataset ; ImageNet ; benchmark
准确率 = accuracy ; top-1 ; top-5
误差 = error
基线 = baseline
光催化 = photocataly
降解 = degradation
催化剂 = catalyst
光源 = light source
波长 = wavelength
自由基 = radical
稳定性 = stability
去除率 = removal efficiency
浓度 = concentration
退火 = anneal
固溶 = solution treatment ; solutionized
时效 = aging
屈服 = yield
塑性 = ductility ; elongation
延伸率 = elongation
断裂 = fracture
韧性 = toughness
腐蚀 = corrosion
阻抗 = impedance
盐雾 = salt spray
涂层 = coating
孔隙 = porosity
密度 = density
显微组织 = microstructure
再结晶 = recrystallization
残余应力 = residual stress
寿命 = life ; cycles
循环 = cycle ; cycling
转速 = rpm ; speed
载荷 = load
变形 = deformation
焊 = weld
烧结 = sinter
比表面积 = surface area ; BET
带隙 = band gap
矿化 = mineralization
动力学 = kinetics
速率常数 = rate constant
投加量 = dosage ; loading
染料 = dye ; methylene blue ; rhodamine
抗生素 = antibiotic ; tetracycline
可见光 = visible light
紫外 = UV ; ultraviolet
光强 = irradiance
空穴 = hole
电子 = electron
复合 = recombination
毒性 = toxicity
训练 = training
推理 = inference
参数量 = parameters ; params
时延 = latency ; inference time
吞吐 = throughput
泛化 = generalization
消融 = ablation
鲁棒性 = robust
召回率 = recall
精确率 = precision
损失 = loss
学习率 = learning rate
数据增强 = augmentation
注意力 = attention
微调 = fine-tun ; fine tun
模块 = module ; component ; block
贡献 = contribut
移除 = removing ; removal ; without
去掉 = removing ; without
原因 = because ; attribut ; due to
机制 = mechanism ; attribut ; origin
解释 = attribut ; explain ; ascribed
表明 = indicat ; suggest ; show
归因 = attribut ; ascribed
下降 = decrease ; lower ; reduc ; drop
上升 = increase ; higher ; rise
幅度 = by ; margin
最佳 = best ; optimal ; highest
主要 = main ; dominant ; primary
贡献最大 = main contributor ; dominant
移动端 = mobile ; edge device
轮次 = epoch
批大小 = batch size
时间 = time ; duration
速率 = rate ; kinetics
初始浓度 = initial concentration
去除 = removal ; degradation
效率 = efficiency"""


def _parse_inline_terms(block):
    table = {}
    for raw in block.strip().splitlines():
        zh, _, ens = raw.partition("=")
        names = [x.strip() for x in ens.split(";") if x.strip()]
        if zh.strip() and names:
            table[zh.strip()] = names
    return table


INLINE_TERMS = _parse_inline_terms(_INLINE_TERM_LINES)

TRACE = {"errors": [], "degradations": [], "pending": [], "changes": [], "uncertainties": [], "missing": []}


def norm_text(s):
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"[\u2010-\u2015\-]", " ", s)
    s = s.replace("\u00b5", "u").replace("\u03bc", "u")
    return re.sub(r"\s+", " ", s).strip().lower()


def first_value(d, keys):
    """First populated value under any of the given key spellings, case-folded."""
    if not isinstance(d, dict):
        return None
    low = {}
    for k in d:
        low.setdefault(str(k).strip().lower(), k)
    for want in keys:
        k = low.get(want.lower())
        if k is not None and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def iter_pairs(obj, depth=0):
    if depth > 6:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (list, dict)):
                yield str(k), v
            yield from iter_pairs(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_pairs(v, depth + 1)


def load_json(p):
    err = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return json.loads(Path(p).read_text(encoding=enc, errors="replace")), None
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
    return None, err


def save_json(p, obj):
    p = Path(p)
    tmp = p.with_name(p.name + ".part")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def digest16(p):
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return None


def load_term_map():
    terms = dict(INLINE_TERMS)
    source = REF_DIR / "term_map.md"
    try:
        for raw in source.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("- "):
                line = line[2:].strip()
            if not line or line.startswith("#") or "=>" not in line:
                continue
            zh, _, tail = line.partition("=>")
            names = [x.strip() for x in re.split(r"[/,，;；、]", tail) if x.strip()]
            if zh.strip() and names:
                terms[zh.strip()] = names
    except Exception as exc:  # noqa: BLE001
        TRACE["degradations"].append({"item": "references/term_map.md", "reason": str(exc),
                                      "impact": "built-in term table only"})
    return terms


def locate_case(inp, case_arg=None):
    cands = [Path(case_arg)] if case_arg else []
    cands += [Path(inp) / n for n in ("case.json", "case_v3.json", "case-3.json")]
    for p in cands:
        if p.is_file():
            return p
    bad = re.compile(r"(score|gold|rubric|verifier|grading|expected|ground.?truth)", re.I)
    for p in sorted(Path(inp).glob("**/*.json")):
        if bad.search(p.name) or bad.search(str(p.parent)):
            continue
        return p
    return None


def extract_meta(case):
    m = {"case_id": None, "paper_id": None, "material_version": None}
    if isinstance(case, dict):
        m["case_id"] = first_value(case, CASE_KEY_NAMES)
        m["paper_id"] = first_value(case, PAPER_KEY_NAMES)
        m["material_version"] = first_value(case, VERSION_KEY_NAMES)
        if None in (m["paper_id"], m["material_version"]):
            for _, v in iter_pairs(case):
                if isinstance(v, dict):
                    m["paper_id"] = m["paper_id"] or first_value(v, PAPER_KEY_NAMES)
                    m["material_version"] = m["material_version"] or first_value(v, VERSION_KEY_NAMES)
    for k in m:
        if m[k] is not None:
            m[k] = m[k] if isinstance(m[k], str) else json.dumps(m[k], ensure_ascii=False)
    return m


def _paragraph(d, idx, section, origin, key):
    pid, text = None, None
    if isinstance(d, str):
        text = d
    elif isinstance(d, dict):
        pid, text = first_value(d, QKEY_PID), first_value(d, QKEY_PTXT)
        section = section or first_value(d, QKEY_SECTION)
        if not isinstance(text, str):
            text = " ".join(str(v) for k, v in d.items()
                            if isinstance(v, str) and str(k).lower() not in {x.lower() for x in QKEY_PID})
    if not isinstance(text, str):
        return None
    text = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()
    if len(text) < 3:
        return None
    pid = re.sub(r"^[\[\(]|[\]\)]$", "", str(pid)).strip() if pid else f"P{idx + 1}"
    return {"paragraph_id": pid, "section": str(section).strip() if section else "unknown",
            "text": text, "origin": origin, "locator": f"/{origin}/{key}"}


def split_marked_paragraphs(text):
    marks = [(m.start(), m.group(1)) for m in
             re.finditer(r"(?m)^\s*\[?(P\d{1,3}|S\d{1,3})\]?\s*[:.\-)]?\s+", text)]
    if len(marks) < 2:
        return []
    out = []
    for i, (pos, pid) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        seg = re.sub(r"^\s*\[?(P\d{1,3}|S\d{1,3})\]?\s*[:.\-)]?\s*", "", text[pos:end])
        out.append({"paragraph_id": pid, "text": seg.strip()})
    return out


def infer_section(text):
    head = norm_text(text[:160])
    for pat, sec in ((r"^abstract", "abstract"), (r"^(keywords|introduction)", "introduction"),
                     (r"^(experimental|method|materials and method)", "methods"),
                     (r"^(results?|findings)", "results"), (r"^discussion", "discussion"),
                     (r"^conclusions?", "conclusion"), (r"^(references|bibliography)", "references")):
        if re.search(pat, head):
            return sec
    return "unknown"


def gather_paragraphs(case):
    paras, seen = [], set()

    def push(item):
        if not item:
            return
        if item["paragraph_id"] in seen:
            item["paragraph_id"] = f'{item["paragraph_id"]}_{len(paras) + 1}'
        seen.add(item["paragraph_id"])
        paras.append(item)

    def from_bag(bag, sec, key):
        if isinstance(bag, str):
            bag = split_marked_paragraphs(bag) or [{"text": bag}]
        if not isinstance(bag, list):
            bag = [bag]
        for i, it in enumerate(bag):
            push(_paragraph(it, i, sec, key, i))

    def walk(obj, sec=None, depth=0):
        if depth > 7 or not isinstance(obj, (dict, list)):
            return
        if isinstance(obj, list):
            for v in obj:
                walk(v, sec, depth + 1)
            return
        for k, v in obj.items():
            kl = str(k).lower()
            bag = isinstance(v, list) and v and isinstance(v[0], dict) and first_value(v[0], QKEY_PTXT)
            if isinstance(v, (list, str)) and v and (kl in PARAGRAPH_LIST_KEYS or bag):
                # a named section that itself holds paragraphs ({"results": [...]}) keeps that name
                from_bag(v, sec if kl in PARAGRAPH_LIST_KEYS else str(k), str(k))
            elif kl in SECTION_CONTAINER_KEYS and isinstance(v, (dict, list)):
                for sk, sv in (v.items() if isinstance(v, dict) else enumerate(v)):
                    skl = str(sk).lower()
                    if skl in PARAGRAPH_LIST_KEYS and isinstance(sv, (list, str)):
                        from_bag(sv, sec or str(sk), str(sk))  # inherit the real section label instead of a container name
                    elif isinstance(sv, (dict, list)):
                        walk(sv, sec if skl in PARAGRAPH_LIST_KEYS else str(sk), depth + 1)
            elif isinstance(v, (dict, list)):
                walk(v, sec, depth + 1)

    walk(case)
    for names, kind in ((TABLE_KEYS, "table"), (FIGURE_KEYS, "figure_caption"), (BIBLIO_KEYS, "references")):
        bag = []
        for k, v in iter_pairs(case):
            if k.lower() in names and isinstance(v, list):
                bag = v
                break
        for i, it in enumerate(bag):
            txt, pid = "", None
            if isinstance(it, dict):
                pid = first_value(it, QKEY_PID)
                txt = first_value(it, QKEY_PTXT) or ""
                cap = first_value(it, ("caption", "title", "label", "legend"))
                rows = first_value(it, ("rows", "data", "table", "matrix"))
                if rows and not txt:
                    rr = [list(r) if isinstance(r, (list, tuple)) else [r] for r in rows]
                    head = rr[0] if len(rr) > 1 else []
                    txt = " ; ".join("; ".join(f"{head[i]}: {c}" if i < len(head) else str(c)
                                               for i, c in enumerate(r)) for r in (rr[1:] or rr))
                txt = (f"{str(cap).rstrip('. ')}. {txt}" if cap else txt).strip()
            else:
                txt = str(it)
            if len(txt) < 3:
                continue
            item = _paragraph({"paragraph_id": pid or f"{kind[0].upper()}{i + 1}", "text": txt}, i, kind, names[0], i)
            if item:
                item["kind"] = kind
                push(item)
    if not paras:  # no paragraph container at all: treat the longest text field as a marked-up article
        blob = ""
        stack = [case]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                stack.extend(v for v in o.values() if isinstance(v, (dict, list)))
                cand = [v for v in o.values() if isinstance(v, str) and len(v) > 200]
            elif isinstance(o, list):
                stack.extend(o)
                cand = []
            else:
                cand = []
            if cand:
                blob = max(cand + [blob], key=len)
        if blob:
            items = split_marked_paragraphs(blob)
            if not items:
                chunks = [c.strip() for c in re.split(r"\n\s*\n", blob) if len(c.strip()) > 80]
                items = [{"text": c} for c in chunks] or [{"text": blob}]
            for i, it in enumerate(items):
                push(_paragraph({"paragraph_id": it.get("paragraph_id") or f"P{i + 1}",
                            "text": it["text"]}, i, "unknown", "raw_text", i))
            if paras:
                TRACE["changes"].append({"item": "paragraphs", "change": f"由整篇文本回退切分 {len(paras)} 段"})
    if not paras:
        TRACE["missing"].append("论文段落文本（没有可解析的 paragraphs、sections 或整篇正文）")
        TRACE["errors"].append({"stage": "collect_paragraphs", "error": "paragraph text was not parseable"})
    for p in paras:
        p.setdefault("kind", "paragraph")
        if p["section"] in ("", "unknown"):
            p["section"] = infer_section(p["text"])
    return paras


def gather_questions(case):
    raw, where = None, None
    for name in QUESTION_LIST_KEYS:
        for k, v in iter_pairs(case):
            if k.lower() == name.lower() and isinstance(v, (list, dict)) and v:
                raw, where = v, name
                break
        if raw is not None:
            break
    if raw is None:
        mat = PARAGRAPH_LIST_KEYS + SECTION_CONTAINER_KEYS + TABLE_KEYS + FIGURE_KEYS + BIBLIO_KEYS
        for k, v in iter_pairs(case):
            if (isinstance(v, list) and v and len(v) <= 30 and all(isinstance(x, dict) for x in v)
                    and str(k).lower() not in mat and all(first_value(x, QKEY_TEXT) for x in v)
                    and not any(first_value(x, QKEY_PID[:5]) for x in v)):
                raw, where = v, k
                break
    out = []
    if isinstance(raw, dict):
        raw = [{"question_id": k, "question": v} for k, v in raw.items()]
    for i, it in enumerate(raw or []):
        qid = qtext = None
        if isinstance(it, str):
            qtext = it
        elif isinstance(it, dict):
            qid, qtext = first_value(it, QID_KEYS), first_value(it, QKEY_TEXT)
            if qtext is None:
                for k, v in it.items():
                    if isinstance(v, str) and len(v.strip()) > 6:
                        qtext, qid = v, qid or k
                        break
        if not qtext:
            continue
        out.append({"question_id": str(qid).strip() if qid else f"Q{i + 1}",
                    "question": str(qtext).strip()})
    ids = [q["question_id"] for q in out]
    for i, q in enumerate(out):
        if ids.count(q["question_id"]) > 1:
            q["question_id"] = f"Q{i + 1}"
    if not out:
        TRACE["missing"].append("问题清单（没有找到 questions 列表条目）")
    return out, where


def placeholder_payload():
    return {"case_id": None, "paper_id": None, "material_version": None, "status": "partial",
            "summary": "placeholder written before parsing",
            "result": {"answers": [], "unanswered_parts": [], "coverage": {}},
            "answers": [], "claims": [], "uncertainties": [], "uncertainty": [], "sources": [],
            "pending_human": [], "errors": [], "degradations": [], "changes": [],
            "counts": {}, "verification": {"ok": None}, "runtime": {"truncated": False}}


def fill_contract(payload, contract):
    """Mirror the supplied output_contract: every key survives, known ones carry content."""
    merged = {}
    if isinstance(contract, dict):
        merged.update(contract)
        r = merged.get("result")
        if isinstance(r, dict) and isinstance(payload.get("result"), dict):
            nr = dict(r)
            for k, v in payload["result"].items():
                if nr.get(k) in (None, "", [], {}):
                    nr[k] = v
            payload["result"] = nr
    for k, v in payload.items():
        if k not in merged or k in CONTRACT_FILL_KEYS:
            merged[k] = v
    # mirrors stay authoritative: a contract pre-declaring an empty list must not erase answers
    res = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    for k in ("answers", "unanswered_parts", "coverage"):
        if merged.get(k) in (None, "", [], {}) and res.get(k) not in (None, "", [], {}):
            merged[k] = res[k]
    return merged


def summarize_counts(answers, claims):
    evid = [e for c in claims for e in c.get("evidence", [])]
    hit = sum(1 for e in evid if e.get("quote_verified"))
    widths = [e.get("quote_words") or len(str(e.get("quote", "")).split()) for e in evid]
    subs = [s for a in answers for s in a.get("sub_questions") or []]
    trace = [digit_traceable(c) for c in claims]
    traced = sum(1 for t in trace if t is True)
    checked = sum(1 for t in trace if t is not None)
    by_status = {k: sum(1 for a in answers if a["status"] == k)
                 for k in ("answered", "partial", "insufficient_evidence", "input_error")}
    return {"questions": len(answers), "sub_questions": len(subs),
            "sub_questions_answered": sum(1 for s in subs if s.get("status") == "answered"),
            "numeric_claims": sum(1 for c in claims if " = " in str(c.get("text", ""))),
            "quotes_below_15_words": sum(1 for w in widths if w < 15),
            "quote_words_min": min(widths) if widths else None,
            "quote_words_max": max(widths) if widths else None,
            "answered": by_status["answered"], "partial": by_status["partial"],
            "insufficient_evidence": by_status["insufficient_evidence"],
            "input_error": by_status["input_error"],
            "claims": len(claims), "evidence": len(evid), "evidence_verified": hit,
            "quote_hit_rate": round(hit / len(evid), 4) if evid else None,
            "claims_without_evidence": sum(1 for c in claims if not c.get("evidence")),
            "numeric_claims_checked": checked, "numeric_claims_traced": traced,
            "numeric_trace_rate": round(traced / checked, 4) if checked else None}


def digit_traceable(claim):
    """Self-innovation: a numeric claim's value must occur in its own evidence quote.

    Returns True/False for claims shaped like "label = value unit"; None when the
    claim carries no number. Thousands separators and comma decimals are folded on
    the quote side, so 1,250 matches 1250 and 2,4 matches 2.4.
    """
    text = str(claim.get("text") or "")
    if " = " not in text:
        return None
    val = text.split(" = ", 1)[1].strip().split(" ", 1)[0]
    if not re.match(r"^\d", val):
        return None
    quotes = [str(e.get("quote") or "") for e in (claim.get("evidence") or [])]
    if not quotes:
        return False
    plain = val.replace(",", "")
    for q in quotes:
        for variant in (q, q.replace(",", ""), q.replace(",", ".")):
            if val in variant or plain in variant.replace(",", ""):
                return True
    return False


SECTION_PATTERNS = (("abstract", r"abstract|summary"), ("introduction", r"introduct|background"),
        ("methods", r"method|experimental|material|procedure|synthes"),
        ("results", r"result|finding"), ("discussion", r"discussion"),
        ("conclusion", r"conclusion|summary|outlook"), ("references", r"reference|bibliograph"))


def build_coverage(paras, answers):
    secs = {}
    for p in paras:
        secs[p["section"]] = secs.get(p["section"], 0) + 1
    cited = sorted({pid for a in answers for pid in a.get("evidence_paragraph_ids", [])})
    cited_sec = {p["section"] for p in paras if p["paragraph_id"] in cited}
    have = set()
    for s in secs:
        low = s.lower()
        for name, pat in SECTION_PATTERNS:
            if re.search(pat, low):
                have.add(name)
    missing = [n for n, _ in SECTION_PATTERNS if n not in have]
    only_abs = have and have <= {"abstract"}
    kinds = {p.get("kind", "paragraph") for p in paras}
    absent = [k for k in ("table", "figure_caption", "references") if k not in kinds]
    return {"paragraphs_supplied": len(paras), "paragraphs_indexed": len(paras),
            "paragraphs_cited": len(cited), "cited_paragraph_ids": cited,
            "sections_read": [{"section": k, "paragraphs": v} for k, v in sorted(secs.items())],
            "sections_cited": sorted(cited_sec),
            "sections_unread": missing if have else [],
            "unread_reason": ([] if not have else
                              [{"section": n, "reason": "only_abstract_supplied"} for n in missing]
                              if only_abs else
                              [{"section": n, "reason": "section_not_supplied"} for n in missing]),
            "read_status": ("section_labels_not_supplied" if not have else
                            "only_abstract_supplied" if only_abs else "full_text_sections_indexed"),
            "chars_supplied": sum(len(p["text"]) for p in paras),
            "not_supplied": TRACE["missing"] + [f"{k} 未提供，答案只依据已给的正文段落" for k in absent],
            "method": "所有供给段落都进检索索引并逐题打分；每题只引用得分最高的少量段落",
            "note": "材料是已抽取文本，没有 PDF 页图或像素，因此给不出页码与图元读数；未做 OCR、未联网检索"}


# --------------------------------------------------------- quotes, numbers, labels
# Plain ASCII spellings (um, 850 C, wt%) are accepted because extracted paper text often
# loses the micro/degree glyphs; longest unit first so MPa is preferred over Pa.
UNIT_WORDS = ("Pa MPa GPa kPa hPa N kN mN J kJ MJ W mW kW mV kV V mA A Hz kHz MHz GHz dB ppm ppb rpm "
         "nm um µm μm mm cm mL uL µL μL L mg ug µg μg ng g kg mol/L mmol/L µmol/L mg/L g/L mg/g "
         "m2/g m²/g m2·g-1 mAh/g Wh/kg F/g C/g mS/cm S/cm h min ms s d K °C ℃ C eV keV"
         " vol% mol% wt% at%").split()
UNIT_REGEX_BODY = "(?:" + "|".join(re.escape(u) for u in sorted(set(UNIT_WORDS), key=len, reverse=True)) \
    + r"|wt\.?\s?%|at\.?\s?%|vol\.?\s?%|mol\.?\s?%|%)"
VALUE_RE = re.compile(r"(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>" + UNIT_REGEX_BODY + r")(?![A-Za-z])")
LABEL_STOPWORDS = frozenset("at in for with under after before during by of and or to from the a an was were is are "
                    "reached showed show observed observe than about approximately around vs on as which that "
                    "this respectively value values measured obtained gave give up down below above "
                    "decreased increased reduced rose dropped rose improved enhanced fell grew remains remained"
                    .split())
PREPOSITION_WORDS = frozenset("at under for in with during after before within between on over".split())
CONDITION_RE = re.compile(r"\b(at|under|during|in the presence of|after|before|for|with|when|while|using|"
                  r"vs\.?|compared (?:with|to)|pH|humidity|irradiat\w*|light|temperature|strain rate|"
                  r"heating|anneal\w*)\b", re.I)


def sentence_spans(text):
    spans, start = [], 0
    for m in re.finditer(r"(?<=[.!?;])\s+(?=[A-Z0-9(\[])", text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    out = []
    for a, b in spans:
        if not text[a:b].strip():
            continue
        if out and len(text[a:b].strip()) < 25:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return [(a, b, text[a:b].strip()) for a, b in out]


def extend_window(text, a, b, lo=15, hi=60):
    """Expand a short span inside one paragraph to lo..hi words, snapping to sentence edges."""
    while len(text[a:b].split()) < lo:
        nxt = re.search(r"[.!?;]\s+", text[b:])
        prev = re.search(r"[.!?;]\s+(?=\S)", text[:a].rstrip())
        if nxt and len(text[a:b + nxt.end()].split()) <= hi:
            b += nxt.end()
        elif prev:
            a = prev.start() + 1
        else:
            break
    return text[a:b]


def slice_quote(text, a, b, terms, hi=60, lo=15):
    """Verbatim window of text[a:b] sized lo..hi words around the first matched term."""
    seg = text[a:b]
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", seg)]
    if len(words) <= hi:
        return extend_window(text, a, b, lo, hi).strip()
    low, pos = seg.lower(), 0
    for t in terms:
        p = low.find(t)
        if p >= 0:
            pos = p
            break
    idx = sum(1 for s, e in words if e <= pos)
    st = max(0, min(idx - 10, len(words) - hi))
    return text[a + words[st][0]:a + words[st + hi - 1][1]].strip()


def clean_number(s):
    """Tell separators apart: 1,250 becomes 1250 while 2,4 becomes 2.4."""
    s = str(s).strip()
    return s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")


UNIT_GROUPS = (("温度", ("C", "°C", "℃", "K")), ("时间", ("h", "min", "s", "ms", "d")),
          ("尺寸/粒径", ("nm", "um", "µm", "μm", "mm", "cm", "m2/g", "m²/g")),
          ("浓度", ("mg/L", "mol/L", "mmol/L", "µmol/L", "g/L", "mg/g", "ppm", "ppb")),
          ("应力/强度/压力", ("MPa", "GPa", "kPa", "hPa", "Pa", "N", "kN")),
          ("百分比", ("%", "wt%", "at%", "vol%", "mol%")),
          ("质量", ("mg", "g", "kg", "µg", "μg", "ng")), ("体积", ("mL", "µL", "μL", "L")),
          ("电位", ("mV", "V", "kV")), ("功率", ("W", "mW", "kW")),
          ("能量", ("eV", "keV", "J", "kJ", "MJ")), ("频率", ("Hz", "kHz", "MHz", "GHz")))
FORWARD_WORDS = {"to", "and", "or", "versus", "vs", "by", "respectively", "~", "-"}


def unit_group(unit):
    for zh, us in UNIT_GROUPS:
        if unit in us:
            return zh
    return "value"


def compose_label(pre, prev=None, unit=""):
    """Compose a short human-readable quantity name for one extracted number.

Only words lying after the previous measurement's unit are considered, so a
trailing condition ("at 850 C", "for 1 h") cannot inherit the earlier quantity
name. Relative deltas ("18% higher than") are reported as a change instead of a
level, which keeps the label honest.
"""
    last = None
    for m in VALUE_RE.finditer(pre):
        last = m
    tail = pre[last.end():] if last else pre
    keep = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9\-\./]*", tail)
            if t.lower().strip(".-") not in LABEL_STOPWORDS and not re.fullmatch(UNIT_REGEX_BODY, t)
            and not t.lower().strip(".-").isdigit()]
    head = re.sub(r"[^A-Za-z]", " ", tail).lower().split()
    if any(w in head for w in ("higher", "lower", "more", "less", "increase", "decrease", "reduction",
                               "improvement", "than", "gain", "relative")) or \
            re.match(r"\s*(?:%\s*)?(higher|lower|more|less|greater|increase|decrease|reduction|improvement|than)",
                     sentence[sentence.find(m.group("num")) + len(m.group(0)) - len(unit):][:24] if False else
                     ""):
        return "相对变化"
    if keep and not (last is not None and head and head[-1] in PREPOSITION_WORDS):
        return " ".join(keep[-3:]).strip()
    if keep and last is not None and head and head[-1] in PREPOSITION_WORDS:
        return unit_group(unit)  # "after annealing at 850 C": the value is the annealing temperature
    if last is not None and head and all(h in FORWARD_WORDS for h in head) and prev:
        return prev  # "from 18 um to 2.4 um": same quantity, reuse the label
    return unit_group(unit) if last is not None else (prev or unit_group(unit))


def extract_values(sentence, cap=4):
    """One dict per distinct measured value: number, unit and a composed label."""
    out, seen = [], set()
    for m in VALUE_RE.finditer(sentence):
        pre = sentence[:m.start()].strip()
        if re.search(r"\b(table|tabletext|fig|figure|section|ref|page|eq|no)\.?\s*$|\[", pre[-20:], re.I):
            continue
        unit = (m.group("unit") or "").strip()
        prev_ch = sentence[m.start() - 1] if m.start() else " "
        if len(unit) == 1 and (prev_ch.isalnum() or prev_ch in "-_") :
            continue  # a trailing alphanumeric means the "unit" belongs to a name (ImageNet-1K, A100)
        if len(unit) == 1 and sentence[m.end():m.end() + 1].isdigit():
            continue
        ex = re.match(r"(?:\^?-\d|[\u00b7\^]-\d)", sentence[m.end():])  # append exponent notation (min-1, m^2) to the unit
        if ex and not unit.endswith(ex.group(0)):
            unit += ex.group(0)
        val = clean_number(m.group("num"))
        if not unit and not re.search(r"(reached|=|of|about|≈|~|:)", pre[-18:], re.I):
            continue
        if (val, unit) in seen:
            continue
        seen.add((val, unit))
        lab = compose_label(pre, out[-1]["label"] if out else None, unit) or "value"
        if re.match(r"\s*(?:%\s*)?(higher|lower|more|less|greater|increase|decrease|reduction|improvement|than|up to)",
                    sentence[m.end():m.end() + 20], re.I):
            lab = "相对变化"  # "18% higher than the T6 condition" is a delta, not an absolute level
        out.append({"label": lab, "value": val, "unit": unit, "label_class": unit_group(unit)})
        if len(out) >= cap:
            break
    return out


def condition_phrase(sentence):
    for m in CONDITION_RE.finditer(sentence):  # skip purpose phrases such as "for automotive body panels" (no quantity follows)
        if m.group(1).lower() == "for" and not re.search(r"\d", sentence[m.end():m.end() + 12]):
            continue
        frag = sentence[m.start():]
        words = [(x.start(), x.end()) for x in re.finditer(r"\S+", frag)]
        return (frag[:words[13][1]] if len(words) > 14 else frag).strip(" ,.;:(")
    return None


SUBQ_CUE = re.compile(r"多少|多大|多高|多长|多强|几|什么|哪些|哪个|如何|为什么|为何|是否|有没有|能否|占比|比例|多少倍")


def split_subquestions(q):
    parts = re.split(r"[？?；;。\n]+|（\d）|\(\d\)", q)
    parts = [p.strip(" ，,、：:") for p in parts if len(p.strip(" ，,、：:")) >= 4]
    if len(parts) <= 1:  # one sentence carrying two question cues: split it on the comma
        chunks = [c.strip(" ，,、：:") for c in re.split(r"[，,]", q) if c.strip(" ，,、：:")]
        if len(chunks) > 1 and sum(1 for c in chunks if SUBQ_CUE.search(c)) >= 2:
            parts = chunks
    return parts[:4] or [q.strip()]


def write_evidence_csv(out, meta, answers):
    import csv
    with (Path(out) / "evidence_map.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "paper_id", "question_id", "answer_status", "claim_id", "claim_kind",
                    "readability", "claim_text", "source_id", "paragraph_id", "section", "locator",
                    "char_start", "quote_words", "quote_verified", "quote"])
        for a in answers:
            for c in a["claims"]:
                for e in (c.get("evidence") or [{}]):
                    w.writerow([meta.get("case_id"), meta.get("paper_id"), a["question_id"], a["status"],
                                c["claim_id"], c["kind"], c.get("readability"), c["text"][:300],
                                meta.get("paper_id"), e.get("paragraph_id"), e.get("section"),
                                e.get("locator"), e.get("char_start"), e.get("quote_words"),
                                e.get("quote_verified"), e.get("quote")])


def make_claim(qid, cid, text, kind, evs, conds=None):
    return {"claim_id": cid, "question_id": qid, "text": text, "kind": kind,
            "readability": "directly_read" if kind == "reported" else ("inferred" if evs else "undetermined"),
            "source_id": None, "conditions": conds or [],
            "evidence": [{"paper_id": None, "paragraph_id": e["paragraph_id"], "section": e["section"],
                          "locator": e["locator"], "quote": e["quote"], "char_start": e["char_start"],
                          "quote_verified": e["char_start"] >= 0,
                          "quote_words": len(e["quote"].split())} for e in evs]}
