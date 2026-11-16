#!/usr/bin/env python3
"""compose.py -- 材料索引构建、工作稿模板、成稿排版与 result.json 收口。仅标准库、离线、确定性。"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
try:
    import sourcekit as sk
except Exception:
    sk = None

SKILL, VERSION = "research-to-reader", "1.0.0"
READERS = (("产业界", r"产业界|企业|公司|工业|投资|商业化|licens|industry|合作方"),
           ("基金/项目评审", r"基金|资助|评审|申报|立项|funder|grant|panel"),
           ("政策部门", r"政策|监管|政府|决策|policy"),
           ("非专业公众", r"公众|大众|科普|媒体|新闻|public|lay"))
GENRES = (("技术转化简报", r"简报|白皮书|技术报告|一页纸|brief|whitepaper"),
          ("项目申报摘要", r"申报|提案|proposal|立项"),
          ("科普文章", r"科普|新闻稿|通稿|博客|press|popular"),
          ("论文摘要", r"abstract|论文摘要"))


def walk_keys(obj, bucket=None):
    """把嵌套 JSON 的键压平成 {小写键: 值}，方便从任意层级找字段。"""
    bucket = {} if bucket is None else bucket
    if isinstance(obj, dict):
        for k, v in obj.items():
            bucket.setdefault(str(k).lower(), v)
            walk_keys(v, bucket)
    elif isinstance(obj, list):
        for v in obj:
            walk_keys(v, bucket)
    return bucket


def first_text(flat, *names):
    for name in names:
        val = flat.get(name)
        if isinstance(val, (str, int, float)) and str(val).strip():
            return str(val).strip()
        if isinstance(val, dict):
            for alias in ("label", "name", "value", "text"):
                if isinstance(val.get(alias), str) and val[alias].strip():
                    return val[alias].strip()
        if isinstance(val, list) and val and isinstance(val[0], str):
            return "; ".join(val)[:300]
    return None


def read_workorder(case, instruction):
    """从 case 与题面里识别读者、文体、篇幅，并记录命中的依据片段。"""
    flat = walk_keys(case or {})
    order = {"audience": first_text(flat, "audience", "target_audience", "readers", "reader", "受众"),
             "genre": first_text(flat, "genre", "format", "text_type", "文体", "体裁"),
             "length": first_text(flat, "length", "word_limit", "max_words", "word_count", "max_length", "篇幅"),
             "instruction": first_text(flat, "task_instruction", "instruction", "task", "prompt") or instruction,
             "caller_note": first_text(flat, "organizer_workorder", "organizer_edit_workorder", "workorder", "requirements"),
             "basis": {}}
    haystack = "%s\n%s" % (instruction or "", order["instruction"] or "")
    for field, rules in (("audience", READERS), ("genre", GENRES)):
        if order[field]:
            continue
        for label, pattern in rules:
            found = re.search(pattern, haystack, re.I)
            if found:
                order[field], order["basis"][field] = label, found.group(0)
                break
    if not order["length"]:
        found = re.search(r"(\d{2,5})\s*(?:字|词|words?)", haystack, re.I)
        if found:
            order["length"], order["basis"]["length"] = found.group(1) + " 字", found.group(0)
    return order


def build_index(case, case_path, mats, instruction):
    paragraphs, records = [], []
    for i, mat in enumerate(mats, 1):
        mid = "M%d" % i
        blocks = sk.carve_blocks(mat["text"]) if sk else []
        record = {k: mat[k] for k in ("name", "path", "kind", "method", "role", "chars", "sha256")}
        records.append(dict(record, id=mid, paragraphs=len(blocks)))
        paragraphs += [{"loc": "%s:P%d" % (mid, j), "mat": mid, "text": t,
                        "role": mat["role"], "chars": len(t)} for j, t in enumerate(blocks, 1)]
    body = "\n".join(p["text"] for p in paragraphs if p["role"] != "instruction")
    alltext = "\n".join(p["text"] for p in paragraphs)
    vals, pairs = sk.numeric_atoms(body) if sk else (set(), set())
    return {"case_id": (case or {}).get("case_id") or (case or {}).get("id") or "UNKNOWN-CASE",
            "output_contract": (case or {}).get("output_contract") or {},
            "case_path": str(case_path) if case_path else None,
            "workorder": read_workorder(case, instruction), "materials": records, "paragraphs": paragraphs,
            "norm_exact": sk.fold(alltext) if sk else alltext,
            "norm_loose": sk.fold(alltext, True) if sk else alltext,
            "numbers": sorted(vals), "pairs": sorted(pairs),
            "acronyms": sorted(sk.abbrev_tokens(body)) if sk else [],
            "key_numbers": sorted(p for p in pairs
                                  if re.search(r"[%‰]|mg|kg|mL|mol|M|h|min|d|nM|mM|μ|µ", p))[:80],
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


WORKNOTE = {"_readme": "init 生成的空模板：sections 写完整正文（不要写提纲）；preserved 填必保留项；"
                        "map 做逐段来源对照；changes 记每处删改与理由。",
            "audience": {"label": "", "profile": "", "reading_goal": "", "knowledge": "", "depth": "",
                         "term_policy": "", "strength_policy": ""},
            "genre": {"label": "", "conventions": [], "length_target": 0, "length_unit": "字"},
            "headline": "", "deck": "", "sections": [], "preserved": [], "map": [], "changes": [],
            "removed": [], "glossary": [], "pending": [], "uncertainty": []}


def make_worknote(index):
    note = json.loads(json.dumps(WORKNOTE))
    order = index.get("workorder") or {}
    note["audience"]["label"] = order.get("audience") or ""
    note["genre"]["label"] = order.get("genre") or ""
    found = re.search(r"(\d{2,5})", order.get("length") or "")
    note["genre"]["length_target"] = int(found.group(1)) if found else 0
    return note


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(str(c or "").replace("|", "/").replace("\n", " ") for c in row) + " |"
            for row in rows]
    return "\n".join(out)


def render(ctx, note, report):
    """把工作稿排成可直接交付的 markdown：适配说明 / 正文 / 对照 / 保留项 / 删改 / 术语 / 待确认 / 自检。"""
    aud, gen = note.get("audience") or {}, note.get("genre") or {}
    stats = report.get("stats") or {}
    actual, target = stats.get("body_words", 0), ctx["target"]
    spec = "\n".join("- **%s**：%s" % (label, value) for label, value in (
        ("读者画像", aud.get("profile") or "未填写（需人工补充）"),
        ("阅读目的", aud.get("reading_goal") or "未填写"),
        ("知识假设", aud.get("knowledge") or "未填写"),
        ("解释深度", aud.get("depth") or "未填写"),
        ("术语策略", aud.get("term_policy") or "未填写"),
        ("论断强度", aud.get("strength_policy") or "未填写"),
        ("体裁惯例", "；".join(gen.get("conventions") or []) or "未填写"),
        ("篇幅", "目标 %s / 实际 %s 字（%s）" % (target or gen.get("length_target") or "未指定", actual,
                                          "落在允许区间" if ctx["ok_len"] else "偏离，见自检")),
        ("取舍原则", "必保留：主结论、数字与单位、条件与样本、图表引用、不确定性；可压缩：方法细节与文献罗列；"
                    "可删：重复表述与无关推导")))
    by_section = {}
    for item in note.get("map") or []:
        by_section.setdefault(str(item.get("section_id")), []).append(item)
    body_blocks, rows = [], []
    for i, sec in enumerate(note.get("sections") or [], 1):
        sid = str(sec.get("id") or "S%d" % i)
        cites = sec.get("cites")
        body_blocks.append("### %d. %s\n\n%s\n\n〔来源：%s ｜ 强度：%s〕\n" % (
            i, sec.get("title") or "", (sec.get("text") or "").strip(),
            "、".join(cites) if isinstance(cites, list) else (cites or "见对照表"),
            sec.get("strength") or "未标注"))
        for item in by_section.get(sid) or [{}]:
            rows.append([sid, item.get("source_locator") or "未标注", (item.get("source_quote") or "")[:110],
                         item.get("relation") or "缺对照", item.get("note") or ""])
    cmp_table = md_table(["段落", "源文位置", "源文要旨（逐字）", "处理", "说明"], rows or [["—"] * 5])
    keep_table = md_table(["编号", "类型", "值", "源位置", "原文", "处理"],
                          [[x.get("id") or "", x.get("kind") or "", x.get("value") or "", x.get("locator") or "",
                            (x.get("quote") or "")[:100], x.get("treatment") or "kept"]
                           for x in note.get("preserved") or []] or [["—"] * 6])
    change_table = md_table(["编号", "动作", "源位置", "原文", "改后/删除", "理由"],
                            [["C%d" % i, x.get("action") or "", x.get("locator") or "",
                              (x.get("original_quote") or "")[:90], (x.get("revised_quote") or "")[:90],
                              x.get("reason") or ""]
                             for i, x in enumerate(note.get("changes") or [], 1)]
                            or [["—", "verbatim", "—", "—", "—", "未记录"]])
    dropped = "\n".join("- `%s` %s：%s（%s）" % (x.get("locator") or "-", x.get("item") or "", x.get("why") or "",
                                              x.get("action") or "删除")
                        for x in note.get("removed") or []) or "- 无"
    glossary = "\n".join("- **%s**：%s；统一用「%s」（%s）" % (
        x.get("term") or "", x.get("expansion") or "—", x.get("usage") or x.get("term") or "",
        x.get("locator") or "—") for x in note.get("glossary") or []) or "- 无"
    pending = "\n".join("- **待确认**：%s（原因：%s；动作：%s）" % (
        p.get("issue") or "—", p.get("why") or "—", p.get("action") or p.get("owner") or "作者确认")
        for p in list(note.get("pending") or []) + list(report.get("pending") or [])) or "- 无"
    unsure = "\n".join("- " + (u if isinstance(u, str) else json.dumps(u, ensure_ascii=False))
                       for u in list(note.get("uncertainty") or []) + ctx["unc"]) or "- 无"
    banner = ("> ⚠ **兜底稿**：工作稿缺失或不可用，本文件由脚本按确定规则从源材料抽取，"
              "**未完成读者改写**，请在它之上继续写。\n") if ctx["fallback"] else ""
    basis = "；".join("`%s`→%s" % kv for kv in (ctx["basis"] or {}).items()) or "题面未给显式依据，按文体常规处理"
    return f"""# {note.get('headline') or '科研成果转化稿'}

{f'> {note["deck"]}' if note.get('deck') else ''}

> 状态 **{ctx['status']}** ｜ 受众 **{aud.get('label') or '未指定'}** ｜ 文体 **{gen.get('label') or '未指定'}** ｜ 目标 {target or '未指定'} 字 / 实际 {actual} 字

{banner}
## 一、改写依据（读者 / 文体 / 篇幅）

{spec}

判定依据：{basis}

## 二、正文成稿

{chr(10).join(body_blocks) if body_blocks else '（无正文：材料或工作稿不可用）'}

## 三、来源对照（逐段）

{cmp_table}

## 四、必保留项核销表

{keep_table}

## 五、删改清单与变更记录

{change_table}

未进入成稿的内容：
{dropped}

## 六、术语与缩写统一表

{glossary}

## 七、待人工确认与不确定性

{pending}

{unsure}

## 八、自检指标

- 段落 {stats.get('sections')}；正文 {actual} 字；引文命中 {stats.get('quote_hit')}/{stats.get('quote_total')}；对照覆盖 {stats.get('paragraphs_used')}/{stats.get('material_paragraphs')}
- 数字：成稿 {stats.get('numbers_in_body')} 个 / 源文 {stats.get('numbers_in_source')} 个 / 漂移 {len(stats.get('number_errors') or [])} 个
- 校验错误 {len(report.get('errors') or [])} 条、提示 {len(report.get('warnings') or [])} 条（明细见 result.json 的 errors / self_check）
"""


def salvage_note(index, order):
    """工作稿不可用时的确定性兜底：按三类槽位从源文原句摘录，不做改写。"""
    pool = [(p["loc"], sentence.strip()) for p in index.get("paragraphs", []) if p.get("role") != "instruction"
            for sentence in re.split(r"(?<=[。！？])\s*|(?<=[.!?])\s+", p.get("text") or "")
            if len(sentence.strip()) >= 12]
    if not pool:
        return None
    found = re.search(r"(\d{2,5})", order.get("length") or "")
    cap, spent = (int(found.group(1)) if found else 900), 0
    picked, keep, mapping, seen = [], [], [], set()
    buckets = (("要点摘录（原文句子，未改写）", r"[\s\S]", 4),
               ("关键数字与结果（原文句子，未改写）", r"[%‰]|\d", 8),
               ("条件与局限（原文句子，未改写）",
                r"局限|限制|尚需|有待|初步|提示|可能|未能|不足|limit|caveat|preliminary|suggest", 5))
    for i, (title, pattern, limit) in enumerate(buckets, 1):
        items = []
        for loc, sentence in pool:
            if len(items) >= limit or spent + len(sentence) > cap:
                break
            if re.search(pattern, sentence, re.I) and sentence not in seen:
                items.append((loc, sentence))
                seen.add(sentence)
                spent += len(sentence)
        if not items:
            continue
        picked.append({"id": "F%d" % i, "title": title, "text": "\n\n".join(x[1] for x in items),
                       "cites": [x[0] for x in items], "strength": "source-verbatim"})
        mapping.append({"section_id": "F%d" % i, "source_locator": items[0][0], "source_quote": items[0][1],
                        "relation": "quoted", "note": "兜底：逐字摘录，未做读者改写"})
        for loc, sentence in items:
            for v in sorted((sk.numeric_atoms(sentence)[1] if sk else set()))[:4]:
                keep.append({"id": "F%d" % (len(keep) + 1), "kind": "number", "value": v, "locator": loc,
                             "quote": sentence, "treatment": "kept"})
    if not picked:
        return None
    return {"audience": {"label": order.get("audience") or "未指定"},
            "genre": {"label": order.get("genre") or "未指定", "length_target": cap, "length_unit": "字"},
            "headline": "源材料要点抽取（兜底稿）", "deck": "脚本兜底：未完成读者改写，只保留原文句子与定位",
            "sections": picked, "preserved": keep, "map": mapping, "removed": [], "glossary": [],
            "changes": [{"action": "verbatim-extract", "locator": picked[0]["cites"][0],
                         "original_quote": picked[0]["text"].split("\n\n")[0],
                         "revised_quote": picked[0]["text"].split("\n\n")[0],
                         "reason": "工作稿缺失，先抽取以保证有可核对产物"}],
            "pending": [{"issue": "未按目标读者/文体改写", "why": "draft.json 缺失或不可用",
                         "action": "按 references/readership-map.md 改写后重跑 build"}],
            "uncertainty": ["兜底稿是原文抽取，可读性与篇幅均未达到目标文体要求"]}


def finalize(out, index, note, report, ctx, extra_errors):
    """无条件回填 result.json：契约键、固定字段、保真摘要、运行信息。"""
    contract = (index or {}).get("output_contract") or {}
    stats = report.get("stats") or {}
    case_id = (index or {}).get("case_id") or "UNKNOWN-CASE"
    res = {"case_id": case_id, "status": ctx["status"], "self_check": stats,
           "deliverable": {"file": "deliverable.md", "format": "markdown",
                           "audience": (note.get("audience") or {}).get("label"),
                           "genre": (note.get("genre") or {}).get("label"),
                           "length": {"target": ctx["target"], "unit": "字", "actual": stats.get("body_words")},
                           "sections": [x.get("title") for x in (note.get("sections") or [])],
                           "fallback": ctx["fallback"]},
           "preserved_facts": note.get("preserved") or [], "evidence_map": note.get("map") or [],
           "change_log": note.get("changes") or [], "changes": note.get("changes") or [],
           "glossary": note.get("glossary") or [], "removed": note.get("removed") or [],
           "transformation_spec": {"audience": note.get("audience") or {}, "genre": note.get("genre") or {},
                                   "note": "适配说明见 deliverable.md 第一节"},
           "uncertainty": list(note.get("uncertainty") or []) + ctx["unc"],
           "pending_human": list(note.get("pending") or []) + list(report.get("pending") or []),
           "errors": list(extra_errors) + [e.get("msg") for e in (report.get("errors") or [])],
           "degradations": ctx["degr"], "workorder": (index or {}).get("workorder") or {},
           "sources": [{"id": m["id"], "name": m["name"], "kind": m["kind"], "role": m["role"],
                        "method": m["method"], "paragraphs": m["paragraphs"], "chars": m["chars"],
                        "sha256_16": m["sha256"], "path": m["path"]}
                       for m in (index or {}).get("materials", [])]}
    for field in contract:
        res.setdefault(field, [] if any(h in field.lower() for h in ("list", "map", "log", "facts")) else None)
    fill = {"total": 0, "filled": 0, "null_fields": []}
    if sk:
        filled, fill = sk.bind_contract(contract, {
            "case_id": case_id, "deliverable": res["deliverable"], "preserved_facts": res["preserved_facts"],
            "evidence_map": res["evidence_map"], "change_log": res["change_log"], "glossary": res["glossary"],
            "removed": res["removed"], "uncertainty": res["uncertainty"], "pending_human": res["pending_human"],
            "status": res["status"], "audience": note.get("audience") or {}, "genre": note.get("genre") or {},
            "length": res["deliverable"]["length"]})
        res.update(filled)
        res["contract_fill"] = fill
        if fill["null_fields"]:
            res["degradations"].append("契约字段无法匹配产出，置空：%s" % ", ".join(fill["null_fields"]))
    res["fidelity_summary"] = {
        "contract": {"declared": fill["total"], "filled": fill["filled"], "null": fill["null_fields"]},
        "quotes": {"hit": stats.get("quote_hit"), "total": stats.get("quote_total"), "rate": stats.get("quote_hit_rate")},
        "numbers": {"in_body": stats.get("numbers_in_body"), "in_source": stats.get("numbers_in_source"),
                    "drift": len(stats.get("number_errors") or [])},
        "preserved": {"items": stats.get("preserved"), "quote_ok": stats.get("preserved_quote_ok")},
        "coverage": stats.get("paragraph_coverage"),
        "terms": {"source": stats.get("acronyms_in_source"), "kept": stats.get("acronyms_in_body")}}
    res["runtime"] = {"skill": SKILL, "version": VERSION, "python": sys.version.split()[0],
                      "started_at": datetime.fromtimestamp(ctx["started"], timezone.utc).isoformat(timespec="seconds"),
                      "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "elapsed_s": round(time.time() - ctx["started"], 1), "input_dir": str(ctx["inp"]),
                      "output_dir": str(out), "work_dir": str(ctx["wrk"]),
                      "files": {p.name: p.stat().st_size for p in sorted(out.glob("*")) if p.is_file()},
                      "counts": {"materials": len(index.get("materials", [])),
                                 "paragraphs": len(index.get("paragraphs", [])),
                                 "sections": len(note.get("sections") or []),
                                 "errors": len(res["errors"]), "pending": len(res["pending_human"])}}
    (out / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    res["runtime"]["files"] = {p.name: p.stat().st_size for p in sorted(out.glob("*")) if p.is_file()}
    (out / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return res
