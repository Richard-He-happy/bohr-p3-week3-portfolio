#!/usr/bin/env python3
"""源材料抽取与确定性复核工具（写作 Skill 的公共底座）。

设计原则：
  * 只用标准库，不联网，不假设当前工作目录；
  * 每个公开函数都是“失败即降级”，返回空结构而不是抛异常，
    这样调用方总能以退出码 0 收尾并交出可读的 partial 结果。

主要能力：
  扫描输入目录 -> 按扩展名与内容拆成可定位的文本单元；
  建立引文索引 -> 判断某句话能否在源材料中逐字定位；
  审计产物目录 -> 七要素、字数、目标数、月份、规划单位、风险、人工确认、
  归属与无据修饰等硬约束逐项体检，返回 issues / metrics / status。
"""
from __future__ import annotations

import html
import json
import re
import unicodedata
import zipfile
import zlib
from pathlib import Path

SECTION_SPECS = [
    {"id": "background", "title": "立项依据",
     "aliases": ["立项依据", "研究背景", "背景与意义", "立论依据"], "budget": 420},
    {"id": "question", "title": "科学问题",
     "aliases": ["科学问题", "关键科学问题", "拟解决的关键科学问题"], "budget": 260},
    {"id": "goals", "title": "研究目标",
     "aliases": ["研究目标", "研究目的", "总体目标"], "budget": 220},
    {"id": "content", "title": "研究内容",
     "aliases": ["研究内容", "研究任务"], "budget": 380},
    {"id": "innovation", "title": "创新点",
     "aliases": ["创新点", "特色与创新", "创新之处", "主要创新"], "budget": 260},
    {"id": "route", "title": "技术路线",
     "aliases": ["技术路线", "研究方案", "技术方案", "研究路线"], "budget": 320},
    {"id": "foundation", "title": "研究基础与可行性",
     "aliases": ["研究基础", "可行性", "工作基础", "研究基础与可行性"], "budget": 260},
]

BANNED_PHRASES = ["首次", "国际领先", "填补空白", "重大突破", "国内外首创", "世界首创",
                  "尚无先例", "领跑全球", "开创性突破"]

READABLE_SUFFIXES = {".txt": "text", ".md": "markdown", ".json": "json", ".csv": "csv",
                     ".tsv": "csv", ".docx": "docx", ".pdf": "pdf"}

META_FILENAMES = {"task.md", "case.json", "output-contract.md", "public-manifest.json",
                  "example-input.json", "skill.md", "guide.md"}

CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
MEASURE_TOKEN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|‰|mm|cm|MPa|kPa|GPa|℃|°C|K|N·m|N|kg|g|mg|μm|um|nm|"
    r"mL|ml|L|h|min|s|倍|次|个|组|层|周期|篇)")
SOURCE_UNIT_LIMIT = 400
SENTENCE_BREAK = re.compile(r"(?<=[。；！？!?;])|(?<=\.)\s+(?=[A-Z(\[\"“])|\n")

ATTRIB_CLAIM = re.compile(r"(申请人|本课题组|我方|本人)([^。；\n]{0,24})(已完成|已实现|已发表|已建成|已掌握)")
ATTRIB_EXEMPT = re.compile(r"不能|不作|未|非|尚|待|不构成|外部作者")
EXTERNAL_MARK = re.compile(r"外部作者|该文作者|原作者|Belter|Dollar")
CURRENCY = re.compile(r"\d+\s*万?元|￥|RMB|人民币")
MONTH_TOKEN = re.compile(r"(?:第\s*(\d{1,2})\s*个?月|M\s*(\d{1,2})(?!\d)|(\d{1,2})\s*个月)")
PLAN_TOKEN = re.compile(r"拟|计划|将|预计")
UNBACKED_CLAIM = re.compile(r"设备已(?:具备|到位|就绪)|已获(?:伦理|资助|批复|立项)|已通过伦理")


def count_cjk(text):
    return len(CJK_RUN.findall(text or ""))


def split_sentences(text):
    return [s.strip() for s in SENTENCE_BREAK.split(text or "") if s and s.strip()]


def squash(text):
    t = unicodedata.normalize("NFKC", text or "")
    for old, new in (("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'"),
                     ("—", "-"), ("–", "-"), ("−", "-")):
        t = t.replace(old, new)
    t = re.sub(r"[\s\u3000\u00a0]+", "", t)
    return re.sub(r"[，。、；：！？（）()\[\]【】,.;:!?\"'_…·<>《》]", "", t).lower()


def decode_bytes(raw):
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "ignore")


def load_json_file(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def line_units(text, max_chars=1200):
    lines = text.splitlines()
    blocks, buf, start, width = [], [], None, 0
    for no, ln in enumerate(lines, 1):
        if not ln.strip():
            continue
        if start is None:
            start = no
        buf.append(ln)
        width += len(ln)
        if width >= max_chars:
            blocks.append({"locator": "L%d-L%d" % (start, no), "text": "\n".join(buf)})
            buf, start, width = [], None, 0
    if buf:
        blocks.append({"locator": "L%d-L%d" % (start, len(lines)), "text": "\n".join(buf)})
    return blocks[:SOURCE_UNIT_LIMIT]


def json_leaf_units(obj, pointer="", out=None, depth=0):
    if out is None:
        out = []
    if len(out) >= SOURCE_UNIT_LIMIT or depth > 8:
        return out
    if isinstance(obj, dict):
        for key, val in obj.items():
            esc = str(key).replace("~", "~0").replace("/", "~1")
            json_leaf_units(val, pointer + "/" + esc, out, depth + 1)
    elif isinstance(obj, list):
        for pos, val in enumerate(obj):
            json_leaf_units(val, pointer + "/" + str(pos), out, depth + 1)
    elif isinstance(obj, str) and len(obj.strip()) > 40:
        out.append({"locator": "JSON-Pointer" + (pointer or "/"), "text": obj})
    return out


def csv_row_units(text):
    rows = text.splitlines()
    units = []
    for base in range(0, max(1, len(rows)), 20):
        chunk = "\n".join(rows[base:base + 20])
        if chunk.strip():
            units.append({"locator": "row-%d-%d" % (base + 1, min(base + 20, len(rows))),
                          "text": chunk})
    return units[:SOURCE_UNIT_LIMIT]


def docx_para_units(path):
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", "ignore")
    except Exception:
        return []
    units = []
    for no, para in enumerate(re.findall(r"<w:p[ >].*?</w:p>", xml, re.S), 1):
        txt = html.unescape("".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, re.S))).strip()
        if txt:
            units.append({"locator": "para-%d" % no, "text": txt})
    return units[:SOURCE_UNIT_LIMIT]


def pdf_literal_text(data):
    pieces = []
    literal = re.compile(rb"\((?:\\.|[^\\()])*\)")
    escapes = {b"n": b"\n", b"r": b"", b"t": b" ", b"b": b"", b"f": b""}
    for hit in literal.finditer(data):
        body = hit.group(0)[1:-1]
        body = re.sub(rb"\\([nrtbf()\\])", lambda m: escapes.get(m.group(1), m.group(1)), body)
        body = re.sub(rb"\\([0-7]{1,3})", lambda m: bytes([int(m.group(1), 8) & 0xFF]), body)
        pieces.append(decode_bytes(body))
    return re.sub(r"[ \t]{2,}", " ", " ".join(pieces)).strip()


def pdf_stream_units(path):
    try:
        raw = Path(path).read_bytes()
    except Exception:
        return []
    units, seq = [], 0
    for head in re.finditer(rb"stream\r?\n", raw):
        begin = head.end()
        end = raw.find(b"endstream", begin)
        if end < 0:
            continue
        blob = raw[begin:end]
        try:
            data = zlib.decompress(blob)
        except Exception:
            data = blob
        if not (b"BT" in data or b"Tj" in data or b"TJ" in data):
            continue
        txt = pdf_literal_text(data)
        if len(txt) > 60:
            units.append({"locator": "pdf-stream-%d" % seq, "text": txt})
            seq += 1
        if len(units) >= SOURCE_UNIT_LIMIT:
            break
    return units


def collect_units(path):
    kind = READABLE_SUFFIXES.get(path.suffix.lower())
    if kind in ("text", "markdown"):
        return line_units(decode_bytes(path.read_bytes()))
    if kind == "json":
        try:
            return json_leaf_units(json.loads(decode_bytes(path.read_bytes())))
        except Exception:
            return line_units(decode_bytes(path.read_bytes()))
    if kind == "csv":
        return csv_row_units(decode_bytes(path.read_bytes()))
    if kind == "docx":
        return docx_para_units(path)
    if kind == "pdf":
        return pdf_stream_units(path)
    return []


def scan_sources(input_dir, limit_files=40):
    found = []
    if not input_dir or not Path(input_dir).exists():
        return found
    readable = []
    for p in sorted(Path(input_dir).rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        if p.suffix.lower() not in READABLE_SUFFIXES:
            continue
        readable.append(p)
    for p in readable[:limit_files]:
        found.append({
            "source_id": "S%02d" % (len(found) + 1),
            "name": p.name,
            "path": str(p),
            "kind": READABLE_SUFFIXES.get(p.suffix.lower(), "binary"),
            "role": "meta" if p.name.lower() in META_FILENAMES else "source",
            "units": collect_units(p),
        })
    return found


def quote_index(sources):
    idx = []
    for src in sources:
        if src.get("role") == "meta":
            continue
        for unit in src.get("units", []):
            flat = squash(unit.get("text", ""))
            if len(flat) >= 30:
                idx.append((src["source_id"], src["name"], unit["locator"], flat,
                            unit.get("text", "")))
    return idx


def locate_quote(index, quote):
    target = squash(quote)
    miss = {"match": "unmatched", "source_id": None, "locator": None, "ratio": 0.0}
    if not target:
        return {"match": "empty", "source_id": None, "locator": None, "ratio": 0.0}
    if not index:
        return {"match": "no_source", "source_id": None, "locator": None, "ratio": 0.0}
    for sid, name, loc, flat, _raw in index:
        if target in flat:
            return {"match": "normalized", "source_id": sid, "locator": loc,
                    "source": name, "ratio": 1.0}
    if len(target) >= 24:
        head, tail = target[:16], target[-16:]
        for sid, name, loc, flat, _raw in index:
            if head in flat and tail in flat:
                return {"match": "partial", "source_id": sid, "locator": loc,
                        "source": name, "ratio": 0.9}
    return miss


def harvest_facts(sources, limit=40):
    facts, seen = [], set()
    for src in sources:
        if src.get("role") == "meta":
            continue
        for unit in src.get("units", []):
            for sent in split_sentences(unit.get("text", "")):
                hit = MEASURE_TOKEN.search(sent)
                if not hit:
                    continue
                quote = sent.strip()
                if not (8 <= len(quote) <= 260):
                    continue
                key = squash(quote)[:60]
                if key in seen:
                    continue
                seen.add(key)
                facts.append({"fact_id": "F%02d" % (len(facts) + 1),
                              "value": hit.group(0).strip(), "quote": quote,
                              "source_id": src["source_id"], "source": src["name"],
                              "locator": unit["locator"]})
                if len(facts) >= limit:
                    return facts
    return facts


def heading_hits(md):
    hits = []
    for m in re.finditer(r"^[ \t]{0,3}(#{1,6})[ \t]*(.+?)[ \t]*$", md, re.M):
        hits.append((m.start(), m.end(), len(m.group(1)), m.group(2).strip()))
    return hits


def section_ranges(md):
    heads = heading_hits(md)
    spans = {}
    for spec in SECTION_SPECS:
        anchor = None
        for pos, stop_pos, level, title in heads:
            if any(alias in title for alias in spec["aliases"]):
                anchor = (pos, stop_pos, level)
                break
        if not anchor:
            spans[spec["id"]] = {"title": spec["title"], "found": False, "heading": None,
                                 "chars": 0, "body": ""}
            continue
        pos, stop_pos, level = anchor
        stop = len(md)
        for nxt, nxt_end, nxt_level, _t in heads:
            if nxt > pos and nxt_level <= level:
                stop = nxt
                break
        body = md[stop_pos:stop]
        cleaned = re.sub(r"^[ \t]*[-*>].*$", "", body, flags=re.M)
        spans[spec["id"]] = {"title": spec["title"], "found": True,
                             "heading": md[pos:stop_pos].strip(),
                             "chars": count_cjk(cleaned), "body": body}
    return spans


def _section_audit(md, plan, report):
    issue = report["issue"]
    spans = section_ranges(md)
    present = [k for k, v in spans.items() if v["found"]]
    thin = [k for k, v in spans.items() if v["found"] and v["chars"] < 60]
    for key in spans:
        if not spans[key]["found"]:
            issue("critical", "section_missing", "缺少要素章节：%s" % spans[key]["title"])
    for key in thin:
        issue("major", "section_thin", "章节正文过短（<%d 汉字）：%s" % (60, spans[key]["title"]))
    total = sum(v["chars"] for v in spans.values()) if present else count_cjk(md)
    lo = int(plan.get("chars_min") or plan.get("lo") or 1600)
    hi = int(plan.get("chars_max") or plan.get("hi") or 2600)
    if total < lo:
        issue("major", "chars_below", "正文字数 %d < 下限 %d" % (total, lo))
    elif total > hi:
        issue("minor", "chars_above", "正文字数 %d > 上限 %d" % (total, hi))
    return spans, present, total, lo, hi


def _schedule_audit(md, plan, report, total, lo, hi):
    issue = report["issue"]
    goals = sorted({int(g) for g in re.findall(r"G\s*([1-9])", md) if int(g) <= 5})
    if len(goals) != 3:
        issue("major", "goals_count", "检出目标数 %d（要求 3：G1/G2/G3）" % len(goals))
    month_cap = int(plan.get("planning_months") or plan.get("months") or 12)
    months = []
    for m in MONTH_TOKEN.finditer(md):
        val = next((int(g) for g in m.groups() if g), 0)
        if 0 < val <= 60:
            months.append(val)
    max_month = max(months) if months else 0
    if max_month > month_cap:
        issue("major", "months_over", "计划时间出现 %d 月 > 上限 %d" % (max_month, month_cap))
    unit_cap = int(plan.get("planning_unit_cap") or plan.get("cap") or 100)
    pu = load_json_file(Path(report["out"]) / "planning_units.json", None)
    pu_total = None
    if not pu:
        issue("major", "planning_units_missing", "planning_units.json 缺失或不可解析")
    else:
        items = pu.get("items") or []
        nums = [it.get("units") for it in items if isinstance(it, dict)]
        if items and all(isinstance(n, (int, float)) for n in nums):
            pu_total = sum(nums)
            if pu.get("total") is not None and abs(float(pu.get("total")) - pu_total) > 1e-6:
                issue("major", "units_total_mismatch",
                      "分项之和 %.1f 与 total %s 不一致" % (pu_total, pu.get("total")))
            if pu_total > unit_cap:
                issue("major", "units_over_cap", "规划单位合计 %.1f > 上限 %d" % (pu_total, unit_cap))
        else:
            issue("major", "units_unfilled", "planning_units.json 存在未填分项")
        if not (pu.get("unit_meaning") or "").strip():
            issue("minor", "unit_meaning_missing", "planning_units.json 未声明规划单位含义")
    if CURRENCY.search(md):
        issue("critical", "currency_leak", "正文出现货币/经费表述（规划单位非货币）")
    return goals, month_cap, max_month, unit_cap, pu, pu_total


def _support_audit(out, report, md):
    issue = report["issue"]
    risk_json = load_json_file(Path(out) / "risks.json", None)
    risk_path = Path(out) / "risks.md"
    risk_text = decode_bytes(risk_path.read_bytes()) if risk_path.exists() else ""
    blob = risk_text + (json.dumps(risk_json, ensure_ascii=False) if risk_json else "")
    risk_ids = sorted({int(r) for r in re.findall(r"R\s?([1-9])", blob) if int(r) <= 9})
    for kw in ("触发", "备选"):
        if kw not in blob:
            issue("minor", "risk_field_missing", "风险未含“%s”字段" % kw)

    human = load_json_file(Path(out) / "pending_human.json", None)
    if isinstance(human, dict):
        human = human.get("items")
    human = human if isinstance(human, list) else []
    human_text = json.dumps(human, ensure_ascii=False)
    if len(human) < 2:
        issue("major", "pending_human_count", "人工确认项 %d < 2" % len(human))
    if not re.search(r"申请人", human_text):
        issue("major", "pending_human_applicant", "人工确认项未覆盖“真实申请人证据”")
    if not re.search(r"资助|指南|funder|notice", human_text):
        issue("major", "pending_human_funder", "人工确认项未覆盖“真实资助要求”")

    matrix_path = Path(out) / "goal_matrix.md"
    matrix_rows = 0
    if matrix_path.exists():
        matrix_text = decode_bytes(matrix_path.read_bytes())
        matrix_rows = len([ln for ln in matrix_text.splitlines()
                           if ln.strip().startswith("|") and re.search(r"G\s?[1-3]", ln)])
        if matrix_rows < 3:
            issue("major", "matrix_rows", "目标矩阵可 join 行数 %d < 3" % matrix_rows)
    else:
        issue("major", "matrix_missing", "goal_matrix.md 缺失")

    boundary = Path(out) / "draft_boundary.md"
    if not boundary.exists():
        issue("minor", "boundary_missing", "draft_boundary.md 缺失（已完成/拟开展边界未落表）")

    unbacked = len(UNBACKED_CLAIM.findall(md))
    if unbacked:
        issue("minor", "equipment_claim_unbacked",
              "出现 %d 处“设备已具备/已获伦理/已获资助”类既成事实表述" % unbacked)
    return human, matrix_rows, boundary.exists(), unbacked


def _attribution_audit(md, report):
    issue = report["issue"]
    banned_hits = 0
    for word in BANNED_PHRASES:
        for sent in re.split(r"(?<=[。；！？\n])", md):
            if word not in sent:
                continue
            sourced = re.search(r"（[^）]{0,80}(来源|locator|evidence|S\d\d)[^）]{0,80}）|et al|等\（\d{4}", sent)
            if not sourced:
                issue("major", "banned_phrase", "无据修饰“%s”：%s" % (word, sent.strip()[:60]))
                banned_hits += 1
                break
    misuse = []
    for m in ATTRIB_CLAIM.finditer(md):
        window = md[max(0, m.start() - 16):m.end()]
        if not ATTRIB_EXEMPT.search(window):
            misuse.append(m.group(1) + m.group(3))
    for item in misuse:
        issue("minor", "attribution_risk", "疑似把既有成果写成申请人已完成：%s" % item)
    plan_marks = len(PLAN_TOKEN.findall(md))
    if plan_marks < 5:
        issue("minor", "plan_markers_few", "拟开展标记仅 %d 处" % plan_marks)
    return banned_hits, misuse, plan_marks


def audit_output(out, plan=None):
    plan = plan or {}
    out = Path(out)
    report = {"issues": [], "metrics": {}, "notes": [], "out": str(out),
              "issue": lambda level, code, msg: report["issues"].append(
                  {"level": level, "code": code, "message": msg})}

    proposal = out / "proposal.md"
    md = decode_bytes(proposal.read_bytes()) if proposal.exists() else ""
    if not proposal.exists():
        report["issue"]("critical", "proposal_missing", "proposal.md 不存在")

    spans, present, total, lo, hi = _section_audit(md, plan, report)
    goals, month_cap, max_month, unit_cap, pu, pu_total = _schedule_audit(
        md, plan, report, total, lo, hi)
    human, matrix_rows, boundary_ok, unbacked = _support_audit(out, report, md)
    banned_hits, misuse, plan_marks = _attribution_audit(md, report)

    evidence = load_json_file(out / "evidence_map.json", None)
    if isinstance(evidence, dict):
        evidence = evidence.get("items")
    evidence = evidence or []
    joined = _matrix_units_join(out, pu)

    report["metrics"] = {
        "char_total": total, "char_range": [lo, hi],
        "sections_found": present, "sections_total": len(SECTION_SPECS),
        "section_chars": {k: v["chars"] for k, v in spans.items()},
        "goals_count": len(goals), "max_month": max_month, "month_cap": month_cap,
        "planning_units_total": pu_total, "unit_cap": unit_cap,
        "risks_count": len(sorted({int(r) for r in re.findall(r"R\s?([1-9])", _risk_blob(out))
                                   if int(r) <= 9})),
        "pending_human_count": len(human),
        "matrix_rows": matrix_rows, "evidence_entries": len(evidence),
        "banned_unverified": banned_hits, "plan_markers": plan_marks,
        "attribution_flagged": len(misuse),
        "external_author_marked": bool(EXTERNAL_MARK.search(md)),
        "boundary_present": boundary_ok,
        "matrix_units_joined": joined,
        "unbacked_claims": unbacked,
    }
    crit = [i for i in report["issues"] if i["level"] == "critical"]
    major = [i for i in report["issues"] if i["level"] == "major"]
    report["counts"] = {"critical": len(crit), "major": len(major),
                        "minor": len(report["issues"]) - len(crit) - len(major)}
    report["status"] = "ok" if not crit and not major else "partial"
    report.pop("issue", None)
    report.pop("out", None)
    return report


def _risk_blob(out):
    text = ""
    rp = Path(out) / "risks.md"
    if rp.exists():
        text = decode_bytes(rp.read_bytes())
    rj = load_json_file(Path(out) / "risks.json", None)
    return text + (json.dumps(rj, ensure_ascii=False) if rj else "")


def _matrix_units_join(out, units_payload):
    matrix = Path(out) / "goal_matrix.md"
    if not matrix.exists() or not isinstance(units_payload, dict):
        return None
    unit_goals = {str(it.get("goal", "")).upper().replace(" ", "")
                  for it in (units_payload.get("items") or []) if isinstance(it, dict)}
    unit_goals.discard("")
    if not unit_goals:
        return None
    text = decode_bytes(matrix.read_bytes())
    row_goals = set()
    for line in text.splitlines():
        if line.strip().startswith("|"):
            row_goals.update(g.upper().replace(" ", "") for g in re.findall(r"G\s*[1-3]", line))
    return sorted(unit_goals & row_goals) == sorted(unit_goals)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        description="复核基金申请书产物目录：七要素、字数、目标数、规划单位、风险与归属。")
    parser.add_argument("--output", default="", help="含 proposal.md 等产物的目录")
    parser.add_argument("--input", default="", help="案例输入目录（可选，仅登记）")
    args = parser.parse_args(argv)
    target = Path(args.output or ".").resolve()
    print(json.dumps(audit_output(target), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
