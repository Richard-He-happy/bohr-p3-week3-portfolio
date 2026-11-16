#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rule layer for the evidence-writing kit.  Two jobs share this module: 1. extraction/normalisation helpers consumed by ``pipeline.py``; 2. a standalone audit (``--input``/``--output``) that re-reads the source material and re-checks the emitted artefacts instead of trusting them.  Everything is standard library, offline, and every entry point returns 0. """
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

VERSION = "1.0.0"

# primitives
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
DOI_PAT = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
FUNC_EN = set("""the a an of and or to in for on with by as at from that this these those is are was were be been being we our it its their they than which who not can may might could should would will also such more most other into about between among both each per using used use study studies result showed show found find suggests suggest indicate however thus therefore has have had there""".split())
FUNC_ZH = set("""研究 显示 表明 本文 我们 方法 结果 结论 数据 分析 以及 这些 由于 因此 但是 然而 并且 相关 影响 具有 进行 可以 通过 一个 一种 中的 作者 中 的 了 和 与 在 是 为 对 也 有 被""".split())
NEG_HINT = re.compile(r"(no significant|not significant|no association|not associated|did not|no effect|" r"failed to|相反|无显著|未发现|不相关|无效)", re.I)
POS_HINT = re.compile(r"(significant|increased|higher|greater|improved|effective|显著|提高|改善|有效|增加|降低)", re.I)
OVERCLAIM = re.compile(r"(证明|证实|确证|proves? that|demonstrat\w* that|confirms? that)", re.I)


def file_digest(path):
    """SHA-256 of a file, or None when unreadable."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(1 << 16)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def extract_text(path):
    """Return ``(text, method, note)`` for one input file."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            tool = shutil.which("pdftotext")
            if tool:
                proc = subprocess.run([tool, "-layout", "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=90)
                if proc.returncode == 0 and proc.stdout.strip():
                    return proc.stdout.decode("utf-8", "ignore"), "pdftotext", ""
            for module in ("pypdf", "PyPDF2"):
                try:
                    reader = getattr(__import__(module), "PdfReader")(str(path))
                    text = "\n".join((page.extract_text() or "") for page in reader.pages)
                    if text.strip():
                        return text, module, ""
                except Exception:
                    pass
            return "", "none", "PDF has no text layer (likely a scan); OCR needed"
        if suffix == ".docx":
            raw = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "ignore")
            raw = re.sub(r"</w:p>|</w:tr>", "\n", raw)
            text = re.sub(r"<[^>]+>", "", raw)
            return (text.replace("&amp;", "&").replace("&lt;", "<") .replace("&gt;", ">"), "zip+ooxml", "")
        if suffix in (".xlsx", ".xlsm", ".pptx", ".doc"):
            return "", "unsupported", "office format not parsed here; export CSV/text first"
        if suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"):
            return "", "image", "image needs a vision pass"
        text = path.read_text(encoding="utf-8", errors="ignore")
        if suffix in (".html", ".htm"):
            text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S)
            text = re.sub(r"<[^>]+>", " ", text)
        return text, "text", ""
    except Exception as exc:
        return "", "error", "%s: %s" % (type(exc).__name__, exc)


# input discovery
DRAFT_HINT = re.compile(r"(draft|manuscript|to_?edit|rough|原稿|草稿|待改|初稿|段落)", re.I)
REF_HINT = re.compile(r"(ref|bib|reference|citation|文献)", re.I)


def scan_inputs(ind, case):
    """Walk the input tree and tag each file as draft | references | material."""
    pointers, docs, seen = [], [], set()

    def harvest(node):
        if isinstance(node, dict):
            for key, val in node.items():
                if isinstance(val, str) and 3 < len(val) < 300 and ("/" in val or "." in val):
                    pointers.append((key, val))
                harvest(val)
        elif isinstance(node, list):
            for item in node:
                harvest(item)

    harvest(case)
    for path in sorted(Path(ind).rglob("*")):
        if not path.is_file() or path.name in ("case.json", "task.md", "task.txt"):
            continue
        rel = str(path.relative_to(ind))
        if path.suffix.lower() in (".pyc", ".log") or "__pycache__" in rel:
            continue
        if path.resolve() in seen:
            continue
        seen.add(path.resolve())
        text, method, note = extract_text(path)
        kind = "references" if REF_HINT.search(path.stem) else "draft" if DRAFT_HINT.search(path.stem) else "material"
        for key, val in pointers:
            if val.endswith(path.name) and (DRAFT_HINT.search(key) or REF_HINT.search(key)):
                kind = "draft" if DRAFT_HINT.search(key) else "references"
        docs.append({"doc_id": "D%02d" % (len(docs) + 1), "path": rel, "kind": kind, "text": text, "method": method, "note": note, "bytes": path.stat().st_size, "sha256": file_digest(path)})
    return docs


# conditioning
SENT_BREAK = re.compile(r"(?<=[。！？!?])\s*|(?<=\.)\s+(?=[A-Z0-9\"“(\[])")


def sentences(text):
    return [part.strip() for part in SENT_BREAK.split(text) if part and len(part.strip()) > 1]


def units_of(docs):
    """Split every readable document into sentence units with a locator each."""
    units = []
    for doc in docs:
        if not doc["text"].strip():
            continue
        body = doc["text"].replace("\r\n", "\n")
        cursor = block_no = 0
        for raw in re.split(r"\n\s*\n|\n(?=#{1,6}\s)", body):
            block = raw.strip()
            if not block:
                continue
            start = body.find(block, cursor)
            start = cursor if start < 0 else start
            cursor = start + len(block)
            block_no += 1
            if re.match(r"^#{1,6}\s", block):
                continue
            offset = start
            for seq, sentence in enumerate(sentences(block), 1):
                hit = body.find(sentence, offset)
                hit = offset if hit < 0 else hit
                offset = hit + len(sentence)
                units.append({ "uid": "%s#B%d.S%d" % (doc["doc_id"], block_no, seq), "doc": doc["doc_id"], "text": sentence, "loc": "%s [B%d.S%d] chars:%d-%d" % (doc["path"], block_no, seq, hit, hit + len(sentence)), })
    return units


try:  # bilingual term table: Chinese phrase -> English concept word
    _TERM_FILE = Path(__file__).resolve().parent.parent / "references" / "terms_zh2en.tsv"
    TERM_MAP = dict(line.split("\t")[:2] for line in _TERM_FILE.read_text("utf-8").splitlines() if "\t" in line and not line.startswith("#"))
except Exception:
    TERM_MAP = {}


def fold_terms(text):
    """Replace known Chinese phrases by their English concept word (longest match first)."""
    for phrase in sorted(TERM_MAP, key=len, reverse=True):
        if phrase in text:
            text = text.replace(phrase, " " + TERM_MAP[phrase] + " ")
    return text


def bag_of(text):
    """Concept bag: English words + Chinese bigrams after normalisation, stopwords dropped."""
    text = fold_terms(text)
    text = text.lower()
    han = CJK.findall(text)
    words = {w for w in re.findall(r"[a-z][a-z\-]{2,}|\d+(?:\.\d+)?", text) if w not in FUNC_EN}
    if len(han) > 1:
        words |= {"".join(han[i:i + 2]) for i in range(len(han) - 1)} - FUNC_ZH
    return words


def overlap(left, right, lt=None, rt=None):
    """Cosine-style overlap of two concept bags; a shared number adds a small bonus."""
    lt = lt or bag_of(left)
    rt = rt or bag_of(right)
    if not lt or not rt:
        return 0.0
    base = len(lt & rt) / ((len(lt) ** 0.5) * (len(rt) ** 0.5))
    same_number = (set(re.findall(r"\d+(?:[.,]\d+)?%?", left)) & set(re.findall(r"\d+(?:[.,]\d+)?%?", right)))
    return min(1.0, base + (0.08 if same_number else 0))


# bibliographies
def ref_ent(docs):
    """Parse the material's reference list; transcribe only, never invent fields."""
    ent, seen = [], set()
    for doc in docs:
        heading = re.search(r"^\s*#*\s*(参考文献|references?)\s*$", doc["text"], re.I | re.M)
        if doc["kind"] != "references" and not heading:
            continue
        tail = re.split(r"^\s*#*\s*(?:参考文献|references?)\s*$", doc["text"], flags=re.I | re.M)[-1]
        for chunk in re.split(r"\n(?=\s*(?:\[\d+\]|\d+[.)]\s))", tail):
            flat = " ".join(chunk.split())
            if len(flat) < 12 or flat[:80].lower() in seen:
                continue
            seen.add(flat[:80].lower())
            marker = re.match(r"^\s*(?:\[(\d+)\]|(\d+)[.)])\s*", flat)
            payload = flat[marker.end():] if marker else flat
            doi_hit = DOI_PAT.search(payload)
            year_hit = re.search(r"\b(19|20)\d{2}\b", payload)
            venue = re.search(r"(Journal|Nature|Science|Lancet|BMJ|Cell|PNAS|PLoS|Front|Proc|Res|Rev|" r"学报|杂志|Press|Springer|Elsevier|Wiley)", payload)
            ent.append({ "num": int(marker.group(1) or marker.group(2)) if marker else None, "raw": flat, "body": payload, "doi": doi_hit.group(0) if doi_hit else None, "year": year_hit.group(0) if year_hit else None, "venue": bool(venue), })
    return ent


# strength rules
DESIGN_RULES = [ (r"(systematic review|meta-?analys|荟萃|系统评价|系统综述)", "系统综述/荟萃", 3.0), (r"(guideline|consensus|指南|共识)", "指南/共识", 3.0), (r"(randomi[sz]ed|\bRCT\b|随机对照)", "RCT", 3.0), (r"(cohort|prospective|longitudinal|队列|前瞻|纵向)", "队列", 2.0), (r"(case-?control|病例对照)", "病例对照", 2.0),
    (r"(cross-?sectional|survey|横断面|调查)", "横断面", 1.5),
    (r"(case report|case series|病例报告|个案)", "病例报告", 0.5),
    (r"(preprint|bioRxiv|medRxiv|arXiv|预印本)", "预印本", 1.0),
    (r"(\breview\b|综述)", "叙述综述", 1.0),
    (r"(in vitro|cell line|mice|mouse|rat|体外|细胞系|小鼠|大鼠)", "体外/动物", 1.0),
]
SAMPLE_RULES = [ r"\bn\s*=\s*([\d,]{1,7})", r"([\d,]{2,7})\s*(?:participants|patients|subjects|individuals|samples|mice|rats|children|adults|" r"名|例|位|受试者|患者|样本)", ]
GRADE_CUTS = ((5.5, "高"), (3.5, "中"), (1.5, "低"))


def detect_design(text):
    for pattern, label, points in DESIGN_RULES:
        if re.search(pattern, text, re.I):
            return label, points
    return "未标明", 1.0


def detect_sample(text):
    counts = []
    for pattern in SAMPLE_RULES:
        for hit in re.finditer(pattern, text, re.I):
            digits = hit.group(1).replace(",", "")
            if digits.isdigit():
                counts.append(int(digits))
    return max(counts) if counts else None


def grade_row(sentence, doc_text, source_count, has_conflict, abstract_only):
    """Four-factor rating: design + sample + independent sources - conflict.  Caps: preprint <= 4.0, n < 100 <= 3.4, abstract-only <= 中. """
    design, design_pts = detect_design(sentence + " " + doc_text[:400])
    sample = detect_sample(sentence) or detect_sample(doc_text)
    if sample is None:
        size_pts, size_label = 0.0, "未报告"
    elif sample >= 1000:
        size_pts, size_label = 2.0, ">=1000"
    elif sample >= 100:
        size_pts, size_label = 1.5, "100-999"
    elif sample >= 10:
        size_pts, size_label = 1.0, "10-99"
    else:
        size_pts, size_label = 0.5, "<10"
    repeat_pts = 1.0 if source_count >= 2 else 0.0
    total = design_pts + size_pts + repeat_pts - (1.0 if has_conflict else 0.0)
    if "预印本" in design:
        total = min(total, 4.0)
    if sample is not None and sample < 100:
        total = min(total, 3.4)
    level = "不足"
    for cut, name in GRADE_CUTS:
        if total >= cut:
            level = name
            break
    if abstract_only and level == "高":
        level = "中"
    explain = "设计=%s(%.1f)；样本=%s(%.1f)；独立来源=%d(%.1f)；冲突=%d" % ( design, design_pts, size_label, size_pts, source_count, repeat_pts, 1 if has_conflict else 0)
    basis = {"design": design, "design_pts": design_pts, "sample_size": sample, "size_pts": size_pts, "sources": source_count, "conflict": bool(has_conflict), "score": round(total, 2)}
    return level, explain, basis


CAUSAL_RULES = [ (r"\bcauses?\b|\bleads? to\b|\bresults? in\b|\bproves?\b|\bdemonstrates? that\b|\bconfirms? that\b", "is associated with"), (r"导致([^。.；]{2,30})", r"与\1相关"), (r"证明了|证实了|确证|必然", "提示"), ]
ABSOLUTE_RULES = [ (r"\ball\b|\balways\b|\bnever\b", "in the material reviewed"), (r"所有|全部|总是|从来", "在所纳入材料中"), ]
ASSOC_HINT = re.compile(r"(associat|correlat|relat|相关|关联|伴随|有关)", re.I)


def soften(text):
    """Downgrade causal/absolute wording; return (new_text, change tuples)."""
    revised, changes = text, []
    for rules, reason in ((CAUSAL_RULES, "仅关联性观察、无随机化/干预对照，按强度下调为关联表述"), (ABSOLUTE_RULES, "全称量词超出单篇/小样本证据的支撑范围")):
        if rules is CAUSAL_RULES and ASSOC_HINT.search(revised):
            continue
        for pattern, replacement in rules:
            nxt = re.sub(pattern, replacement, revised, flags=re.I)
            if nxt != revised:
                action = "causal_to_association" if rules is CAUSAL_RULES else "universal_to_scoped"
                changes.append((action, revised, nxt, reason))
                revised = nxt
    return revised, changes


def trim_cites(sentence):
    return re.sub(r"\s*(?:[\[［]\d{1,3}[\]］]|\([A-Z][^()]{0,40}\d{4}[a-z]?\)|" r"（[^（）]{0,30}\d{4}）)+[。.；;!！?？]*\s*$", "", sentence).strip()


def claim_kind(sentence):
    if re.search(r"(compare|compared|higher than|lower than|高于|低于|相比|\bthan\b)", sentence, re.I):
        return "比较"
    if re.search(r"(because|causes?|leads? to|due to|导致|因为|因果)", sentence, re.I):
        return "因果"
    if re.search(r"(may|might|could|suggest|likely|可能|提示|推断|推测)", sentence, re.I):
        return "推断"
    return "事实"


def abstract_only(doc):
    return bool(re.search(r"(abstract|摘要)", doc["text"], re.I)) and len(doc["text"]) < 3000


def ref_text(doc, refs, number, phrases):
    """Best-effort bibliography line from the material; mark gaps instead of inventing."""
    body = doc.get("text", "") or ""
    for ref in refs:
        if (ref["doi"] and ref["doi"] in body) or overlap(ref["body"][:150], body[:300]) >= 0.35:
            return re.sub(r"^\s*(?:\[\d+\]|\d+[.)])\s*", "", ref["raw"])
    head = " ".join(body.split())[:170]
    if len(head) > 40 and re.search(r"(19|20)\d{2}", head):
        return head + "（自材料首段转录，著录可能不完整）"
    return phrases["rm"].format(n=number, s=doc.get("doc_id"), l=doc.get("path"))


# side artefacts
def side_records(out, rows, refs, hedge_note):
    """Write strength/note: strength rationale, reference check, uncertainty notes."""
    out = out
    strength = ["# 强度记录", "", "口径见 references/grading_manual.md：>=5.5 高，3.5-5.4 中，1.5-3.4 低，其余不足。", ""]
    for row in rows:
        strength += [ "- **%s** <- %s | 强度 **%s** | %s" % (row["claim_id"], row.get("source_id") or "无来源", row["strength"], row.get("rationale", "")), "  - 论断：%s" % row["claim"][:150], "  - 范围：%s" % row.get("support_scope", ""), "  - 定位：%s" % (row.get("locator") or "—"), ]
    (out / "evidence_strength.md").write_text("\n".join(strength), "utf-8")

    check = ["# 著录核验", "", "离线运行，**未联网核验**：只记材料一致性与著录完整度，不声称文献真实存在。", "", "| # | 著录 | 年 | DOI | 完整度 | 缺项 |", "|---|---|---|---|---|"]
    for ref in refs:
        missing = [name for name, present in (("year", ref["year"]), ("venue", ref["venue"]), ("doi", ref["doi"])) if not present]
        if not re.search(r"[A-Z][a-z]{2,}", ref["body"]):
            missing.append("authors")
        check.append("| %s | %s | %s | %s | %s | %s |" % ( ref["num"] or "-", ref["raw"][:70].replace("|", "/"), ref["year"] or "缺", ref["doi"] or "未给", "完整" if not missing else "缺失", "、".join(missing) or "—"))
    if not refs:
        check.append("| — | 无文献表 | — | — | 缺口 |")
    check += ["", "- 编号按首次引用重排；无著录标缺口，不补造作者/年份/DOI。", "- 待办：联网用 Crossref/PubMed 复核 DOI 后才可标“已核验”。"]
    (out / "reference_check.md").write_text("\n".join(check), "utf-8")

    weak = "、".join(sorted({row["claim_id"] for row in rows if row["strength"] in ("低", "不足")})) or "无"
    conflicted = "、".join(sorted({row["claim_id"] for row in rows if row.get("conflicts")})) or "无"
    (out / "uncertainty_notes.md").write_text("\n".join([ "# 不确定性", "", "- 低/不足论断：" + weak, "- 存在冲突证据：" + conflicted, "- 仅摘要来源：%d" % sum(1 for row in rows if row.get("abstract_only")), "- 无来源论断：%d" % sum(1 for row in rows if not row.get("source_id")), "- 著录未联网核验：全部", "", "限定语：" + hedge_note, ]), "utf-8")


# work orders
WORKORDER_KEYS = ("organizer_workorder", "organizer_edit_workorder", "workorder", "edit_workorder")


def wo_checks(case, draft, cited_sources):
    """Execute the judgeable items of an organiser work order and report each."""
    items = []
    for key in WORKORDER_KEYS:
        value = case.get(key)
        bucket = [value] if isinstance(value, (str, dict)) else (value or [])
        for index, item in enumerate(bucket, 1):
            if isinstance(item, dict):
                items.append((key, item.get("id") or "%s-%d" % (key, index), item))
            else:
                items.append((key, "%s-%d" % (key, index), item))
    rec = []
    for key, item_id, item in items:
        instr = (item.get("instruction") or item.get("text") or item.get("task") or json.dumps(item, ensure_ascii=False)) if isinstance(item, dict) else str(item)
        checks = []
        length_hit = re.search(r"(\d{2,4})\s*(?:字|words?|词)", instr, re.I)
        if length_hit:
            counted = len(CJK.findall(draft))
            counted = counted if counted > 30 else len(re.findall(r"[A-Za-z][A-Za-z\-]+", draft))
            checks.append({"check": "length<=%s" % length_hit.group(1), "actual": counted, "pass": counted <= int(length_hit.group(1)) * 1.15})
        ref_hit = re.search(r"(?:引用|cite|citation)[^0-9]{0,12}(\d+)\s*(?:篇|条|references?)", instr, re.I)
        if ref_hit:
            checks.append({"check": "refs>=%s" % ref_hit.group(1), "actual": len(cited_sources), "pass": len(cited_sources) >= int(ref_hit.group(1))})
        style_hit = re.search(r"(apa|vancouver|nature|author-?year|作者-?年|数字编号|numeric)", instr, re.I)
        if style_hit:
            style = style_hit.group(1).lower()
            numeric = style in ("vancouver", "numeric", "nature", "数字编号")
            checks.append({"check": "style=%s" % style, "pass": bool(re.search(r"\[\d+\]", draft)) if numeric else bool(re.search(r"\([A-Z][A-Za-z]+\s+et al\.?,?\s*\d{4}\)", draft))})
        rec.append({ "id": item_id, "instruction": instr[:200], "checks": checks, "status": ("done" if all(c["pass"] for c in checks) else "partial") if checks else "unverifiable", "note": "" if checks else "无确定判据，按 SKILL.md 人工确认", })
    return rec


# audit
def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_case(ind):
    roots = [Path(ind) / "case.json"] + sorted(Path(ind).glob("*case*.json"))
    for cand in roots:
        if cand.is_file():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                continue
    return {}


def audit_out(ind, out):
    """Independent verification: re-read the material, never trust self-reports."""
    out = Path(out)
    checks = []
    result = _load_json(out / "result.json")
    case = _read_case(ind) if Path(ind).is_dir() else {}
    con = case.get("output_contract") or {}

    missing = [key for key in con if key not in result]
    checks.append({"check": "contract_fields", "pass": not missing, "found": len(set(con) & set(result)), "expected": len(con), "detail": "缺失: %s" % missing if missing else "契约齐全"})
    checks.append({"check": "case_id_echo", "pass": str(result.get("case_id")) == str(case.get("case_id") or result.get("case_id")), "detail": "case_id=%s" % result.get("case_id")})
    blank = [key for key in con if result.get(key) in (None, "", [], {})]
    checks.append({"check": "contract_values_filled", "pass": not blank, "detail": "空值: %s" % blank if blank else "契约均有实值"})

    docs = scan_inputs(ind, case) if Path(ind).is_dir() else []
    material = "\n".join(doc["text"] for doc in docs)
    rows = _load_json(out / "evidence_table.json").get("rows", [])
    claims = _load_json(out / "claims.json").get("claims", [])
    draft_path = out / "evidence_driven_draft.md"
    draft = draft_path.read_text(encoding="utf-8") if draft_path.exists() else ""

    quoted = [row for row in rows if row.get("quote")]
    misses = [row["claim_id"] for row in quoted if row["quote"] not in material]
    checks.append({"check": "quote_verbatim", "pass": not misses, "hit": len(quoted) - len(misses), "total": len(quoted), "detail": "未命中: %s" % misses if misses else "引文逐字命中"})
    dangling = sorted({row["claim_id"] for row in rows} - {claim["claim_id"] for claim in claims})
    checks.append({"check": "claim_join", "pass": not dangling, "detail": "悬空: %s" % dangling if dangling else "claims/evidence 可 join"})
    incomplete = [row["claim_id"] for row in rows if not all(field in row for field in ("locator", "strength", "support_scope", "quote"))]
    checks.append({"check": "row_fields", "pass": not incomplete, "detail": "缺字段: %s" % incomplete if incomplete else "四要素齐全"})

    markers = sorted({int(x) for x in re.findall(r"\[(\d{1,3})\]", draft)})
    source_count = len({row["source_id"] for row in rows if row.get("source_id")})
    checks.append({"check": "citation_resolvable", "pass": bool(markers) and max(markers) <= source_count, "markers": len(markers), "sources": source_count, "detail": "%s/%d" % (markers, source_count)})
    loud = OVERCLAIM.findall(draft)
    checks.append({"check": "overclaim_scan", "pass": not loud, "hits": len(loud), "detail": "越级表述 %d 处" % len(loud) if loud else "无越级表述"})

    report = { "case_id": result.get("case_id"), "passed": all(check["pass"] for check in checks), "checks": checks, "metrics": { "claims": len(claims), "evidence_rows": len(rows), "quotes": len(quoted), "quote_hit": len(quoted) - len(misses), "distinct_sources": source_count, "citation_markers": len(markers), },
        "limits": ["未联网核验文献真实性与 DOI（离线）", "扫描件/图像无法逐字校验，见 degradations"],
    }
    (out / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print("verify %s  %s" % ("PASS" if report["passed"] else "FAIL", " ".join("%s=%s" % (check["check"], check["pass"]) for check in checks)))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser( prog="audit.py", description="Independent audit for the evidence-writing kit: verbatim quote hit, " "claim/evidence join, contract backfill, citation resolution, overclaim scan.")
    parser.add_argument("--input", default="/input", help="input directory (default /input)")
    parser.add_argument("--output", default="/app/output", help="output directory (default /app/output)")
    args = parser.parse_args(argv)
    try:
        audit_out(args.input, args.output)
    except Exception as exc:
        print("verify degraded: %s: %s" % (type(exc).__name__, exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
