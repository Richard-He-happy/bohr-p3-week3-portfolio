#!/usr/bin/env python3
"""Read case material and turn it into quotable, locatable evidence. Stdlib only."""
import json
import os
import re
import time
import zipfile
from pathlib import Path

LIM_FILES, LIM_TOTAL, LIM_ONE, LIM_SCAN = 200, 20 << 20, 2 << 20, 45.0
CASE_BYTES = 4 << 20
T0 = time.time()
OPAQUE = frozenset(("wav mp4 mp3 db h5 npz npy pkl so exe bin doc ppt pptx xls xlsx gz zip "
                    "webp tiff tif bmp gif jpeg jpg png").split())
META = frozenset(("task.md", "readme.md", "case.md", "task_instruction.md"))
BLANK = re.compile(r"\s+")
SPLIT = re.compile(r"(?<=[。！？；!?;])|(?<=\.)\s+(?=[A-Z0-9\"“(])")
ADVICE = {"pdf": ("PDF 未解析", "补等价文本或粘贴待引段落"),
          "binary": ("二进制或图像未读取", "补文本或表格等价材料")}
OUTLINE = (("abstract", "摘要", "摘要 abstract summary"),
           ("intro", "1 引言", "引言 背景 目的 intro background aim"),
           ("method", "2 方法", "方法 材料 样本 实验 测量 统计 method participants"),
           ("result", "3 结果", "结果 发现 显著 降低 提高 result significant"),
           ("discussion", "4 讨论", "讨论 机制 解释 局限 discussion limitation"),
           ("conclusion", "5 结论", "结论 综上 conclusion"),
           ("reference", "参考文献", "参考文献 doi references journal"),
           ("availability", "数据可得性声明", "数据可得 availability"))
HINTS = {key: hint for key, _heading, hint in OUTLINE}


def flat(value, cap):
    body = BLANK.sub(" ", "" if value is None else str(value)).strip()
    return body if len(body) <= cap else body[:cap - 1] + "…"


def mark(state, code, path):
    state["degradations"].append({"code": code, "path": str(path)})


def load_one(path):
    sfx = path.suffix.lower()
    if sfx in (".docm", ".docx"):
        with zipfile.ZipFile(path) as archive:
            if "word/document.xml" not in archive.namelist():
                return "docx", "", "docx_part_missing"
            raw_xml = archive.read("word/document.xml")[:LIM_ONE]
        body = raw_xml.decode("utf-8", "replace").replace("</w:p>", "\n")
        clean = re.sub(r"<[^>]{0,4000}>", "", body)
        return "docx", clean, ""
    with open(path, "rb") as handle:
        head = handle.read(8)
        if head[:4] == b"%PDF" or sfx == ".pdf":
            return "pdf", "", "pdf_unparsed"
        if sfx.lstrip(".") in OPAQUE or b"\x00" in head:
            return "binary", "", "binary_unparsed"
        raw = head + handle.read(LIM_ONE + 1 - len(head))
    text, note = raw[:LIM_ONE].decode("utf-8-sig", "replace"), ""
    if len(raw) > LIM_ONE:
        note = "file_truncated"
    if sfx in (".json", ".jsonl") or head.lstrip().startswith(b"{"):
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=1)
        except Exception:
            if not note:
                note = "json_parse_failed"
    return ("json" if sfx == ".json" else "text"), text, note


def collect(root, state):
    """Read each case file once; records carry M01... ids, sizes and extracted text."""
    root, out, spent = Path(root), [], 0
    if not root.is_dir():
        state["errors"].append("input_dir_missing")
        return out
    try:
        queue = sorted((Path(h) / n for h, _s, names in os.walk(root) for n in names),
                       key=lambda item: str(item).lower())[:LIM_FILES + 1]
    except Exception:
        queue = []
    for path in queue:
        if len(out) >= LIM_FILES or time.time() - T0 > LIM_SCAN:
            mark(state, "file_capped", root)
            break
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if spent + min(size, LIM_ONE) > LIM_TOTAL:
            mark(state, "bytes_capped", path)
            break
        spent += min(size, LIM_ONE)
        rel = path.relative_to(root).as_posix()
        if rel.lower() == "case.json":
            continue
        rec = {"kind": "unknown", "note": "", "text": "", "chars": 0, "readable": False,
               "bytes": size, "path": rel, "id": "M%02d" % (len(out) + 1)}
        try:
            rec["kind"], rec["text"], rec["note"] = load_one(path)
        except Exception as exc:
            rec["note"] = "err:" + type(exc).__name__
            mark(state, "file_error", rel)
        rec["chars"], rec["readable"] = len(rec["text"]), bool(rec["text"].strip())
        if rec["note"]:
            mark(state, rec["note"], rel)
        if rec["kind"] in ADVICE:
            why, todo = ADVICE[rec["kind"]]
            state["pending_human"].append({"reason": why, "item": rel, "action": todo})
        if rel.rsplit("/", 1)[-1].lower() in META:
            rec["kind"], rec["note"] = "instruction", rec["note"] or "instruction_excluded"
            mark(state, "instruction_excluded", rel)
        out.append(rec)
    return out


def read_case(root, state):
    root = Path(root)
    if not root.is_dir():
        state["errors"].append("case_json_missing")
        return {}
    paths = [root / "case.json"] + [p for p in sorted(root.glob("case*.json"))
                                    if p.name != "case.json"][:4]
    for path in paths:
        try:
            blob = path.read_bytes()[:CASE_BYTES]
            payload = json.loads(blob.decode("utf-8-sig", "replace"))
            if isinstance(payload, dict):
                state["case_path"] = str(path)
                return payload
        except Exception as exc:
            state["errors"].append("case_json_unreadable:%s" % flat(exc, 80))
    state["errors"].append("case_json_missing")
    return {}


def split_sentences(materials, cap=6000):
    """Quotable sentences with source id, nearest heading and path:Lnn locator."""
    pool = []
    for item in materials:
        text = item.get("text") or ""
        if item.get("kind") == "instruction" or not (item.get("readable") and text):
            continue
        heading = ""
        for number, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            if line.startswith("#") and len(line) < 120:
                heading = line.lstrip("#").strip()
                continue
            for piece in SPLIT.split(line):
                piece = piece.strip(" -*\t")
                if len(piece) >= 24:
                    pool.append({"quote": flat(piece, 480), "source_id": item["id"],
                                 "heading": heading,
                                 "locator": "%s:L%d" % (item["path"], number)})
                if len(pool) >= cap:
                    return pool
    return pool


def bodies(materials):
    return {item["id"]: BLANK.sub("", item["text"]) for item in materials
            if item.get("readable") and item.get("text")}


def quote_found(quote, haystack, source_id=None):
    probe = BLANK.sub("", quote or "")
    if len(probe) < 8:
        return 0, None
    for mid, body in sorted(haystack.items(), key=lambda pair: 0 if source_id == pair[0] else 1):
        if probe in body:
            return 1, mid
    return 0, None


def title_of(case):
    source = case.get("source") if isinstance(case.get("source"), dict) else {}
    for value in (source.get("title"), case.get("title")):
        if isinstance(value, str) and value.strip():
            return flat(value, 160)
    return "学术写作产物（标题待补）"


def heading_matches(heading, key):
    return any(word in (heading or "").lower() for word in HINTS[key].split())


def source_blocks(pool):
    """One block per outline heading, filled with keyword-matched material sentences."""
    used, blocks = set(), []
    for key, heading, hint in OUTLINE:
        words = hint.split()
        picks = [i for i, item in enumerate(pool) if i not in used
                 and any(w in (item.get("heading") or "").lower() for w in words)][:4]
        ranked = sorted((i for i in range(len(pool)) if i not in used and i not in picks),
                        key=lambda i: (-sum(w in pool[i]["quote"].lower() for w in words), i))
        for index in ranked:
            if len(picks) >= 4 or sum(w in pool[index]["quote"].lower() for w in words) <= 0:
                break
            picks.append(index)
        used.update(picks)
        blocks.append({"key": key, "heading": heading, "items": [pool[i] for i in picks],
                       "auto": True, "paras": []})
    return blocks


def draft_sections(draft):
    """Normalise a draft into [{heading, paragraphs:[{text, quotes:[...]}]}]."""
    blocks = []
    for entry in (draft.get("sections") if isinstance(draft, dict) else None) or []:
        entry = {"paragraphs": [entry]} if isinstance(entry, str) else entry
        if not isinstance(entry, dict):
            continue
        body = entry.get("paragraphs") or []
        body = [body] if isinstance(body, str) else (body if isinstance(body, list) else [])
        paras = []
        for item in body:
            item = {"text": item} if isinstance(item, str) else item
            if not isinstance(item, dict):
                continue
            quotes = item.get("quotes") or []
            quotes = [q if isinstance(q, dict) else {"quote": str(q)} for q in
                      (quotes if isinstance(quotes, list) else [quotes])]
            paras.append({"text": str(item.get("text") or ""), "quotes": quotes})
        blocks.append({"heading": str(entry.get("heading") or entry.get("title") or ""),
                       "paragraphs": paras})
    return blocks


def merge(sections, pool, haystack):
    """Keep verified draft text; add material blocks for headings the draft skipped."""
    blocks, changes, rejected = [], [], []
    for section in sections:
        items = []
        for para in section["paragraphs"]:
            for quote in para.get("quotes") or []:
                ok, mid = quote_found(quote.get("quote"), haystack, quote.get("source_id"))
                if ok:
                    items.append({"quote": flat(quote.get("quote"), 480),
                                  "locator": quote.get("locator") or "", "source_id": mid})
                else:
                    rejected.append({"quote": flat(quote.get("quote"), 140),
                                     "locator": quote.get("locator") or ""})
        heading = section["heading"] or "(未命名章节)"
        blocks.append({"key": None, "heading": heading, "items": items,
                       "paras": [p["text"] for p in section["paragraphs"] if p["text"].strip()],
                       "auto": False})
        changes.append({"section": flat(heading, 80), "verified": len(items),
                        "action": "use_agent_draft"})
    for block in source_blocks(pool):
        if any(heading_matches(other["heading"], block["key"]) for other in blocks):
            continue
        blocks.append(block)
        changes.append({"section": block["heading"], "evidence": len(block["items"]),
                        "action": "assemble_from_source"})
    return blocks, changes, rejected
