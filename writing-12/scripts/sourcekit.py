#!/usr/bin/env python3
"""sourcekit.py -- 源材料读入、保真判定、契约字段绑定（仅标准库，离线）。

单独使用（做单点核查，不生成成稿）：
    python sourcekit.py --draft work/draft.json --index work/index.json [--result out/result.json] [--json]
"""
import argparse
import html
import hashlib
import json
import re
import shutil
import subprocess
import sys
import unicodedata
import zipfile
import zlib
from pathlib import Path

sys.dont_write_bytecode = True

# ---------------------------------------------------------------- 固定词表与正则
UNIT_ALT = ("%|‰|mg|kg|μg|µg|ng|pg|g|mL|ml|μL|µL|L|nM|µM|μM|mM|mol|mmol|μmol|µmol|nm|µm|μm|"
            "mm|cm|km|m|kDa|Da|bp|kb|°C|℃|K|kPa|MPa|Pa|GPa|Hz|kHz|MHz|V|mV|mA|A|W|kW|J|kJ|"
            "kcal|cal|rpm|h|hr|min|s|ms|d|wk|yr|fold|×|倍|例|名|人|份|次|天|小时|分钟|秒|年|月|日|个|项|组")
NUM_WITH_UNIT = re.compile(r"(?<![A-Za-z0-9.])(\d[\d,]*(?:\.\d+)?)\s*(" + UNIT_ALT + r")(?![A-Za-z])")
BARE_NUM = re.compile(r"(?<![A-Za-z0-9.])(\d[\d,]*(?:\.\d+)?)(?![A-Za-z])")
ABBREV_RX = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Za-z]{0,8}[A-Z][A-Za-z0-9\-]{0,10})(?![A-Za-z0-9])")
LOC_RX = re.compile(r"M\d+:P\d+")
META_TALK = re.compile(r"本文将|本节将|本段将|下面将|接下来将|本报告将|全文将|"
                       r"in this (?:paper|report|section|brief)|this (?:paper|report|brief) (?:will|aims)")
REQUIRED_FIELDS = ("audience", "genre", "sections", "preserved", "map", "changes")
NOT_ABBREV = {"PDF", "DOI", "URL", "JSON", "CSV", "XML", "HTML", "DOCX", "PPTX", "FIG", "TAB",
              "AND", "THE", "FOR", "WITH", "FROM", "NOT", "ALL", "ANY", "OK", "NA", "VS", "ET",
              "AL", "II", "III", "IV", "ID", "NOTE"}
CONTRACT_SLOTS = (
    (("case_id", "caseid", "案例"), "case_id"),
    (("deliver", "manuscript", "artifact", "transformed", "产物", "稿", "article"), "deliverable"),
    (("preserv", "retain", "保留", "fact", "事实", "must_keep"), "preserved_facts"),
    (("evidence", "source_map", "mapping", "对照", "来源", "映射", "citation", "trace", "locator"), "evidence_map"),
    (("change", "revision", "diff", "改动", "修改", "log"), "change_log"),
    (("glossar", "termin", "术语", "abbrev"), "glossary"),
    (("removed", "deleted", "删除", "omit", "reject"), "removed"),
    (("pending", "human", "确认", "待定"), "pending_human"),
    (("uncertain", "不确定"), "uncertainty"),
    (("audience", "受众", "reader"), "audience"),
    (("genre", "format", "体裁", "文体"), "genre"),
    (("length", "篇幅", "word"), "length"),
    (("status", "状态"), "status"))
DECODERS = ("utf-8-sig", "gb18030", "utf-16", "latin-1")
PLAIN_KINDS = {"md": "text", "txt": "text", "csv": "text", "tsv": "text", "json": "json",
               "tex": "text", "html": "text", "htm": "text", "xml": "text"}


# ---------------------------------------------------------------- 材料读取
def to_text(raw):
    for enc in DECODERS:
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def pdf_pull(path):
    exe = shutil.which("pdftotext")
    if exe:
        try:
            run = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(path), "-"],
                                 capture_output=True, timeout=90)
            if run.returncode == 0 and len(run.stdout.strip()) > 40:
                return to_text(run.stdout), "pdftotext"
        except Exception:
            pass
    try:
        blob = path.read_bytes()
    except Exception:
        return "", "unreadable"
    chunks = []
    for hit in re.finditer(rb"stream\r?\n", blob):
        stop = blob.find(b"endstream", hit.end())
        if stop <= 0:
            continue
        seg = blob[hit.end():stop]
        try:
            seg = zlib.decompress(seg)
        except Exception:
            pass
        if b"Tj" in seg or b"TJ" in seg:
            chunks.append(" ".join(x.decode("latin-1") for x in re.findall(rb"\(([^()\\]{2,})\)", seg)))
    text = re.sub(r"[ \t]{2,}", " ", "\n".join(chunks)).strip()
    return text, ("builtin-pdf" if len(re.sub(r"\s", "", text)) > 200 else "builtin-pdf-lowconf")


def docx_pull(path):
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n\n", re.sub(r"<w:(tab|br)[^>]*/>", "\t", xml))
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def xlsx_pull(path):
    lines = []
    with zipfile.ZipFile(path) as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            shared = [html.unescape(re.sub(r"<[^>]+>", "", si)) for si in
                      re.findall(r"<si>(.*?)</si>", zf.read("xl/sharedStrings.xml").decode("utf-8", "replace"), re.S)]
        sheets = sorted(n for n in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        for name in sheets:
            sheet = zf.read(name).decode("utf-8", "replace")
            for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
                cells = []
                for cell in re.findall(r"<c[^>]*?(?:/>|>.*?</c>)", row, re.S):
                    val = re.search(r"<v>(.*?)</v>", cell, re.S)
                    typ = re.search(r't="(\w+)"', cell)
                    raw = val.group(1) if val else ""
                    if raw.isdigit() and typ and typ.group(1) == "s" and int(raw) < len(shared):
                        raw = shared[int(raw)]
                    cells.append(raw)
                lines.append("\t".join(cells))
    return "\n".join(x for x in lines if x.strip())


def sniff_kind(path):
    """扩展名 + 文件头联合判断，扩展名可以被伪装。"""
    ext = path.suffix.lower().lstrip(".")
    try:
        head = path.open("rb").read(8)
    except Exception:
        head = b""
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return ext if ext in ("docx", "xlsx") else "zip"
    if head[:3] == b"\xff\xd8\xff" or head[:4] == b"\x89PNG":
        return "image"
    return PLAIN_KINDS.get(ext, ext or "unknown")


def read_material(path):
    """返回 (正文, 抽取方式)；失败不抛出，只标注抽取方式给上层降级。"""
    kind = sniff_kind(path)
    try:
        if kind == "pdf":
            return pdf_pull(path)
        if kind == "docx":
            return docx_pull(path), "docx-xml"
        if kind == "xlsx":
            return xlsx_pull(path), "xlsx-xml"
        if kind == "json":
            obj = read_json(path)
            flat = "\n".join(x.strip('"') for x in
                             re.findall(r'"([^"]{3,})"', json.dumps(obj, ensure_ascii=False)))
            return flat, "json-leaves"
        if kind == "image":
            return "", "image-no-ocr"
        if kind in ("pptx", "zip"):
            return "", "unsupported:" + kind
        text = to_text(path.read_bytes())
        head = text[:2000]
        if head and sum(c.isprintable() or c in "\n\t " for c in head) / len(head) < .85:
            return "", "binary-skip"
        return text, ("text" if kind in ("text", "csv") else "raw-bytes")
    except Exception as exc:
        return "", "failed:%s" % type(exc).__name__


def carve_blocks(text):
    blocks = []
    clean = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    for raw in [x.strip() for x in re.split(r"\n\s*\n", clean) if x.strip()]:
        sub = [x.strip() for x in re.split(r"\n(?=\S)", raw) if x.strip()] if len(raw) > 1400 else [raw]
        for piece in sub:
            if len(piece) <= 1400:
                blocks.append(piece)
                continue
            buf = ""
            for sent in re.split(r"(?<=[。！？；.!?])\s*", piece):
                buf += sent
                if len(buf) >= 700:
                    blocks.append(buf.strip())
                    buf = ""
            if buf.strip():
                blocks.append(buf.strip())
    return [re.sub(r"[ \t]+", " ", x) for x in blocks]


def sweep_input(inp):
    mats, degradations = [], []
    files = [p for p in sorted(inp.rglob("*")) if p.is_file() and not p.name.startswith(".")]
    case = case_path = None
    primary = inp / "case.json"
    if primary.is_file():
        try:
            case, case_path = read_json(primary), primary
        except Exception as exc:
            degradations.append("case.json 解析失败：%s" % type(exc).__name__)
    if case is None:
        for p in files:
            if p.suffix.lower() != ".json":
                continue
            try:
                obj = read_json(p)
            except Exception:
                continue
            if isinstance(obj, dict) and "output_contract" in obj:
                case, case_path = obj, p
                break
    for p in files:
        if (case_path and p == case_path) or p.name == "case.json":
            continue
        text, how = read_material(p)
        mats.append({"name": p.name, "path": str(p), "kind": sniff_kind(p), "method": how,
                     "text": text, "chars": len(text),
                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
                     "role": "instruction" if re.match(r"task.*\.md$", p.name, re.I) else "material"})
        if how.startswith("failed") or how == "unreadable":
            degradations.append("%s 解析失败(%s)，未入索引" % (p.name, how))
        elif how == "image-no-ocr":
            degradations.append("%s 为图片，未 OCR" % p.name)
        elif how.startswith("unsupported") or how == "binary-skip":
            degradations.append("%s 类型不支持（%s），未入索引，需人工提供文本" % (p.name, how))
        elif how.startswith("builtin-pdf"):
            degradations.append("%s 用内置 PDF 解析（无 pdftotext），多栏可能错序" % p.name)
    return case, case_path, mats, degradations


# ---------------------------------------------------------------- 数字 / 术语 / 引文原语
def canon_num(s):
    s = str(s).replace(",", "")
    try:
        f = float(s)
    except ValueError:
        return s
    return str(int(f)) if f == int(f) and abs(f) < 1e15 else "%.10g" % f


def as_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def fold(text, loose=False):
    """比较用归一化：去空白并 casefold；loose 额外做 NFKC 全半角折叠。"""
    if not isinstance(text, str):
        return ""
    s = unicodedata.normalize("NFKC", text) if loose else text
    s = s.replace("\u3000", " ").replace("\u00a0", " ")
    return re.sub(r"\s+", "", s.casefold() if loose else s)


def numeric_atoms(text):
    text = LOC_RX.sub(" ", text or "")
    vals, pairs = set(), set()
    for hit in NUM_WITH_UNIT.finditer(text):
        v = canon_num(hit.group(1))
        u = hit.group(2).replace("μ", "u").replace("µ", "u")
        vals.add(v)
        pairs.add(v + u)
    for hit in BARE_NUM.finditer(text):
        vals.add(canon_num(hit.group(1)))
    return vals, pairs


def abbrev_tokens(text):
    return {m.group(1) for m in ABBREV_RX.finditer(text or "")
            if len(m.group(1)) > 1 and m.group(1).upper() not in NOT_ABBREV}


def locators_in(text):
    return set(LOC_RX.findall(str(text or "")))


def count_words(text):
    cjk = len(re.findall(r"[\u3400-\u9fff]", text or ""))
    latin = len(re.findall(r"[A-Za-z][A-Za-z0-9\-']*", text or ""))
    return cjk + latin


def quote_state(quote, exact_norm, loose_norm):
    """逐字核验结果：exact / loose（全半角差异）/ miss / empty。"""
    if not fold(quote):
        return "empty"
    if fold(quote) in exact_norm:
        return "exact"
    return "loose" if fold(quote, True) in loose_norm else "miss"


# ---------------------------------------------------------------- 工作稿判定
def inspect_draft(draft, index):
    """对 draft.json 做确定性判定，返回 {status, errors, warnings, pending, stats}。"""
    errors, warnings, pending, stats = [], [], [], {}
    err = lambda code, msg, **extra: errors.append(dict(code=code, msg=msg, **extra))
    warn = lambda code, msg, **extra: warnings.append(dict(code=code, msg=msg, **extra))
    if not isinstance(draft, dict):
        err("draft_not_object", "工作稿顶层必须是 JSON 对象（收到 %s）" % type(draft).__name__)
        return {"status": "partial", "errors": errors, "warnings": warnings, "pending": pending, "stats": stats}
    for key in REQUIRED_FIELDS:
        if key not in draft:
            err("missing_field", "工作稿缺少必填段 %s" % key)
        elif draft[key] in (None, "", [], {}):
            err("empty_field", "工作稿段 %s 为空，无法排版成稿" % key)
    paras = {p["loc"]: p for p in index.get("paragraphs", [])}
    exact_norm, loose_norm = index.get("norm_exact", ""), index.get("norm_loose", "")
    aud, gen = draft.get("audience") or {}, draft.get("genre") or {}
    if not (isinstance(aud, dict) and aud.get("label")):
        warn("audience_label_missing", "audience.label 为空：成稿的读者适配说明缺依据")
    if not (isinstance(gen, dict) and gen.get("label")):
        warn("genre_label_missing", "genre.label 为空：成稿的文体说明缺依据")

    sections = draft.get("sections") or []
    sections = sections if isinstance(sections, list) else []
    sec_ids, texts, quoted, hit = [], [], 0, 0
    for i, sec in enumerate(sections, 1):
        if not isinstance(sec, dict):
            err("section_not_object", "sections 第 %d 项不是对象" % i)
            continue
        sid = str(sec.get("id") or "S%d" % i)
        sec_ids.append(sid)
        title, body_text = str(sec.get("title") or ""), str(sec.get("text") or "")
        if not body_text.strip():
            err("section_empty", "段落 %s 无正文" % sid)
        elif len(body_text) < 40 and len(sections) > 3:
            warn("section_too_short", "段落 %s 不足 40 字符，疑似只写了提纲" % sid)
        if not title.strip():
            warn("section_title_empty", "段落 %s 没有小标题" % sid)
        texts.append(body_text)
        if sec.get("quote"):
            quoted += 1
            state = quote_state(sec["quote"], exact_norm, loose_norm)
            if state == "miss":
                err("section_quote_miss", "段落 %s 引文在源材料中检索不到" % sid)
            elif state != "empty":
                hit += 1
    body = "\n".join(texts)
    stats["sections"] = len(sec_ids)
    stats["body_chars"] = len(re.sub(r"\s+", "", body))
    stats["body_words"] = count_words(body)

    target = None
    candidates = [gen.get("length_target") if isinstance(gen, dict) else None, draft.get("length_target"),
                  (draft.get("length") or {}).get("target") if isinstance(draft.get("length"), dict) else None]
    for cand in candidates:
        if as_float(cand):
            target = as_float(cand)
            break
    stats["length_target"] = target
    if target:
        ratio = count_words(body) / target
        stats["length_ratio"] = round(ratio, 3)
        if ratio < 0.45:
            err("too_short", "成稿 %d 字，不到目标 %d 字的 45%%，仍属提纲/片段" % (count_words(body), int(target)))
        elif ratio < 0.7:
            warn("short", "成稿 %d 字，只到目标 %d 字的 %d%%" % (count_words(body), int(target), int(ratio * 100)))
        elif ratio > 1.5:
            warn("long", "成稿 %d 字，超出目标 %d 字较多" % (count_words(body), int(target)))
    if META_TALK.search(body):
        warn("meta_discourse", "正文出现“本文将…”式元话语，改写稿应直接给内容而非预告：%s"
             % META_TALK.search(body).group(0))

    preserved = [x for x in (draft.get("preserved") or []) if isinstance(x, dict)] \
        if isinstance(draft.get("preserved"), list) else []
    good, absent = 0, []
    for i, item in enumerate(preserved, 1):
        value = str(item.get("value") or "").strip()
        loc = str(item.get("locator") or "").strip()
        if not value:
            err("preserved_value_missing", "preserved 第 %d 条缺 value" % i)
        if not loc:
            err("preserved_locator_missing", "preserved 第 %d 条缺 locator" % i)
        elif locators_in(loc) - set(paras):
            err("locator_not_found", "preserved 第 %d 条定位 %s 在材料索引中不存在" % (i, loc))
        quote = item.get("quote")
        if not quote:
            warn("preserved_quote_missing", "preserved 第 %d 条无 quote，无法逐字核验" % i)
        else:
            quoted += 1
            if quote_state(quote, exact_norm, loose_norm) == "miss":
                err("preserved_quote_miss", "preserved 第 %d 条的 quote 检索不到（不允许改源文凑校验）" % i)
            else:
                hit += 1
                good += 1
        if value and str(item.get("kind") or "").lower() in ("number", "unit", "term", "figure", "citation") \
                and fold(value) not in fold(body):
            absent.append(value)
    stats["preserved"], stats["preserved_quote_ok"] = len(preserved), good
    if absent:
        warn("preserved_not_in_body", "这些必保留项没进成稿正文：%s" % ", ".join(absent[:8]))

    mapping = [x for x in (draft.get("map") or []) if isinstance(x, dict)] \
        if isinstance(draft.get("map"), list) else []
    used = set()
    for i, item in enumerate(mapping, 1):
        sid = str(item.get("section_id") or "")
        if sid and sec_ids and sid not in sec_ids:
            err("map_section_unknown", "map 第 %d 条 section_id=%s 不存在" % (i, sid))
        locs = locators_in(item.get("source_locator"))
        if not locs:
            err("map_locator_missing", "map 第 %d 条缺可解析的 source_locator（形如 M1:P3）" % i)
        elif locs - set(paras):
            err("locator_not_found", "map 第 %d 条定位不存在：%s" % (i, ",".join(sorted(locs - set(paras)))))
        used |= (locs & set(paras))
        if item.get("source_quote"):
            quoted += 1
            if quote_state(item["source_quote"], exact_norm, loose_norm) == "miss":
                err("map_quote_miss", "map 第 %d 条的 source_quote 检索不到" % i)
            else:
                hit += 1

    changes = [x for x in (draft.get("changes") or []) if isinstance(x, dict)] \
        if isinstance(draft.get("changes"), list) else []
    for i, item in enumerate(changes, 1):
        if not str(item.get("action") or "").strip():
            err("change_action_missing", "changes 第 %d 条缺 action" % i)
        if not str(item.get("reason") or "").strip():
            err("change_reason_missing", "changes 第 %d 条缺 reason（原作者复核要靠它）" % i)
        if item.get("original_quote"):
            quoted += 1
            if quote_state(item["original_quote"], exact_norm, loose_norm) == "miss":
                err("change_quote_miss", "changes 第 %d 条的 original_quote 检索不到" % i)
            else:
                hit += 1
    stats["changes"] = len(changes)

    src_vals, src_pairs = set(index.get("numbers", [])), set(index.get("pairs", []))
    body_vals, body_pairs = numeric_atoms(body)
    drift, unit_notes = [], []
    for v in sorted(body_vals - src_vals):
        f = as_float(v)
        if f is not None and canon_num("%.10g" % (f / 100.0)) in src_vals:
            continue  # 小数改写成百分比，视为等价
        drift.append(v)
    for p in sorted(body_pairs - src_pairs):
        if re.search(r"\d", p) and any(p.startswith(v) for v in src_vals):
            unit_notes.append(p)
    if drift:
        err("number_not_in_source", "成稿出现源材料没有的数字：%s" % ", ".join(drift[:10]))
    if unit_notes:
        warn("unit_variant", "同一数值但单位写法与源文不同：%s" % ", ".join(unit_notes[:8]))
    stats["numbers_in_body"], stats["numbers_in_source"] = len(body_vals), len(src_vals)
    stats["number_errors"] = drift[:10]

    material_locs = {p["loc"] for p in index.get("paragraphs", []) if p.get("role") != "instruction"}
    stats["material_paragraphs"], stats["paragraphs_used"] = len(material_locs), len(used & material_locs)
    stats["paragraph_coverage"] = round(len(used & material_locs) / len(material_locs), 3) if material_locs else None
    if material_locs and stats["paragraph_coverage"] < 0.15:
        warn("low_paragraph_coverage", "只有 %d/%d 个段落进入逐段对照，请确认没漏关键证据"
             % (stats["paragraphs_used"], len(material_locs)))

    terms = [t for t in index.get("acronyms", []) if isinstance(t, str)]
    kept = [t for t in terms if t in body or t.lower() in body.lower()]
    stats["acronyms_in_source"], stats["acronyms_in_body"] = len(terms), len(kept)
    stats["terms_lost"] = [t for t in terms if t not in kept][:10]
    if terms and len(kept) / len(terms) < 0.35:
        warn("terms_lost", "源文缩写多数没出现在成稿（面向公众的稿子应在术语表给全称）：%s"
             % ", ".join(stats["terms_lost"]))

    key = set(index.get("key_numbers", []))
    kept_key = key & (body_vals | body_pairs)
    stats["key_numbers_source"], stats["key_numbers_kept"] = len(key), len(kept_key)
    if key and not kept_key:
        err("key_numbers_missing", "源文带单位的关键数字一个都没进成稿")

    stats["quote_total"], stats["quote_hit"] = quoted, hit
    stats["quote_hit_rate"] = round(hit / quoted, 3) if quoted else None
    if drift:
        pending.append({"issue": "数字与源文对不上：%s" % ", ".join(drift[:6]),
                        "why": "成稿数字须能在源文找到；有换算/改写需作者确认", "owner": "author"})
    if absent:
        pending.append({"issue": "必保留项没进正文：%s" % ", ".join(absent[:6]),
                        "why": "可能被删或被改写，需确认仍可回溯", "owner": "author"})
    return {"status": "ok" if not errors else "partial", "errors": errors, "warnings": warnings,
            "pending": pending, "stats": stats}


# ---------------------------------------------------------------- 契约绑定
def bind_contract(contract, ctx):
    out, report = {}, {"total": 0, "filled": 0, "null_fields": []}
    if not isinstance(contract, dict):
        return out, report
    for field in contract:
        report["total"] += 1
        key = field.lower()
        slot = next((s for hints, s in CONTRACT_SLOTS if any(h in key for h in hints)), None)
        value = ctx.get(slot) if slot and slot in ctx else None
        blank = value is None or (isinstance(value, (list, dict)) and not value) or value == ""
        out[field] = None if blank else value
        if blank:
            report["null_fields"].append(field)
        else:
            report["filled"] += 1
    return out, report


def missing_contract_keys(result, contract):
    return [f for f in (contract or {}) if f not in (result or {})]


# ---------------------------------------------------------------- 独立命令行
def main(argv=None):
    ap = argparse.ArgumentParser(prog="sourcekit.py",
                                 description="单点核查工作稿：结构完整性 / 逐字引文 / 数字漂移 / 段落覆盖 / 契约键")
    ap.add_argument("--draft", default="", help="工作稿 draft.json 路径")
    ap.add_argument("--index", default="", help="init 生成的 index.json 路径")
    ap.add_argument("--result", default="", help="可选：顺带核对 result.json 是否漏契约键")
    ap.add_argument("--json", action="store_true", help="以 JSON 打印判定报告")
    args = ap.parse_args(argv)
    report = {"status": "partial", "errors": [], "warnings": [], "pending": [], "stats": {}}
    try:
        if not (args.draft and args.index):
            report["errors"].append({"code": "args", "msg": "必须同时给 --draft 与 --index"})
        else:
            draft = json.loads(Path(args.draft).read_text(encoding="utf-8-sig"))
            index = json.loads(Path(args.index).read_text(encoding="utf-8-sig"))
            report = inspect_draft(draft, index)
            if args.result:
                result = json.loads(Path(args.result).read_text(encoding="utf-8-sig"))
                lost = missing_contract_keys(result, index.get("output_contract") or {})
                if lost:
                    report["errors"].append({"code": "contract_missing",
                                             "msg": "result.json 缺少契约键：" + ", ".join(lost)})
                    report["status"] = "partial"
    except Exception as exc:
        report["errors"].append({"code": "exception", "msg": "%s: %s" % (type(exc).__name__, exc)})
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        s = report["stats"]
        print("判定 %s ｜ 段落 %s ｜ 正文 %s 字 ｜ 引文 %s/%s ｜ 成稿数字 %s" % (
            report["status"], s.get("sections"), s.get("body_words"), s.get("quote_hit"),
            s.get("quote_total"), s.get("numbers_in_body")))
        for item in report["errors"]:
            print("  [错误] " + str(item.get("msg")))
        for item in report["warnings"]:
            print("  [提示] " + str(item.get("msg")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
