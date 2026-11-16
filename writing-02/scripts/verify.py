#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify.py — 内容单元核对与成品自检。

四件事：题注重编号并查越界引用、内容单元覆盖率、事实取值前后计数、成品字段级检查
（C1–C8）与交付前一致性断言（I1–I7）。只读文本与 OOXML，不改正文。
"""

import html
import re
import zipfile
from pathlib import Path

FACTS = [(r"p\s*[<>=]\s*0?\.\d+", "stat"),
         (r"\[\d+(?:\s*[-,]\s*\d+)*\]", "citation"),
         (r"\d+(?:\.\d+)?\s*(?:mg/kg|mg|kg|mL|ml|%|°C|MPa|kPa|nm|mm|cm|min|h|mmol|mM|nM)\b", "quantity")]


def renumber(blocks, log):
    """题注按出现顺序统一编号；正文越界图表号只登记，不改数字。

    没有题注的图表不凭空补题注 —— 那属于改内容，不属于排版。
    """
    cnt = {"figure": 0, "table": 0}
    for b in blocks:
        kind = b["kind"]
        if kind not in cnt:
            continue
        cnt[kind] += 1
        old = (b.get("caption") or "").strip()
        if not old:
            continue
        head = re.match(r"^\s*(?:图|表|Fig\.?|Table)\s*[\d.]+[\s:：.]*", old)
        new = ("%s %d %s" % ("图" if kind == "figure" else "表", cnt[kind],
                             old[head.end():] if head else old)).strip()
        if old != new:
            log.append({"action": "caption.renumber", "target": "%s#%d" % (kind, cnt[kind]), "before": old,
                        "after": new, "reason": "按题型前缀与出现顺序重排编号", "locator": kind + "#caption"})
        b["caption"] = new
    dangling = [{"ref": m.group(0), "available": cnt["figure" if m.group(1) == "图" else "table"]}
                for b in blocks if b["kind"] == "para"
                for m in re.finditer(r"(图|表)\s*(\d+)", b.get("text") or "")
                if not 1 <= int(m.group(2)) <= cnt["figure" if m.group(1) == "图" else "table"]]
    return {"captions": cnt, "dangling": dangling}


def cover(blocks, flat):
    """内容单元是否出现在成品纯文本里：去空白后取前 40 字符比对。"""
    u = []
    for b in blocks:
        if b.get("caption"):
            u.append(b["caption"])
        if b["kind"] == "table":
            u += [" ".join(r) for r in b.get("rows") or []]
        elif b["kind"] != "figure" and (b.get("text") or "").strip():
            u.append(b["text"])
    u = [re.sub(r"\s", "", x) for x in u if (x or "").strip()]
    miss = [x for x in u if x[:40] not in flat]
    return {"units": len(u), "matched": len(u) - len(miss),
            "ratio": round((len(u) - len(miss)) / max(1, len(u)), 4), "missing": [x[:60] for x in miss[:8]]}


def tally_facts(blocks, flat):
    """统计量/引用号/带单位数值的前后出现次数。

    `flat` 已去掉全部空白，比对前把取值也去空白，否则 "300 °C" 这类带空格的值会被误判为缺失。
    """
    seen = {}
    for b in blocks:
        blob = " ".join([b.get("text") or "", b.get("caption") or ""] + [" ".join(r) for r in b.get("rows") or []])
        for pat, kind in FACTS:
            for m in re.finditer(pat, blob):
                key = (kind, m.group(0).strip())
                seen[key] = seen.get(key, 0) + 1
    return [{"id": "%s:%s" % (k, v), "kind": k, "value": v, "before_count": c,
             "after_count": flat.count(re.sub(r"\s", "", v)), "locator": "manuscript#text",
             "status": "verified" if re.sub(r"\s", "", v) in flat else "missing"}
            for (k, v), c in seen.items()]


def docx_text(path):
    """取回成品 docx 的纯文本。"""
    try:
        xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return ""
    return html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml)))


def checks(st):
    """成品字段级自检 C1–C8：expected / actual / status / locator。"""
    n = st.get("nums") or {}
    rows = []
    for cid, label, want, key, loc in (
            ("C1", "正文字号", 'w:sz w:val="%d"' % n.get("sz", 0), "sx", "word/styles.xml"),
            ("C2", "页边距", 'w:top="%d"' % n.get("marT", 0), "dx", "word/document.xml"),
            ("C3", "行距", 'w:line="%d"' % n.get("line", 0), "sx", "word/styles.xml"),
            ("C4", "西文字体族", 'w:ascii="%s"' % (n.get("font") or ""), "sx", "word/styles.xml"),
            ("C5", "分栏数", 'w:num="%d"' % n.get("cols", 1), "dx", "word/document.xml"),
            ("C6", "页码域", "PAGE", "ftr", "word/footer1.xml")):
        hit = want in st.get(key, "")
        rows.append({"id": cid, "check": label, "expected": want, "actual": "hit" if hit else "miss",
                     "status": "pass" if hit else "fail", "locator": loc})
    ratio = (st.get("cov") or {}).get("ratio")
    rows.append({"id": "C7", "check": "内容单元覆盖率", "expected": ">=0.98", "actual": ratio,
                 "status": "pass" if (ratio or 0) >= 0.98 else "fail", "locator": "fidelity_report.json"})
    rows.append({"id": "C8", "check": "规格可回溯比例", "expected": "100%", "actual": st.get("trace"),
                 "status": "pass" if st.get("trace") == "100%" else "partial", "locator": "format_spec.md"})
    return rows


def invariants(st, payload):
    """一致性断言 I1–I7：任一条不成立都要降级并进待人工确认。"""
    rows = []

    def mark(cid, claim, want, got, ok, act):
        rows.append({"id": cid, "claim": claim, "expected": want, "actual": got, "ok": bool(ok), "action": act})

    contract = st["case"].get("output_contract") or {}
    keys = list(contract.keys()) if isinstance(contract, dict) else [str(k) for k in contract]
    gone = [k for k in keys if k not in payload]
    mark("I1", "契约字段齐全", len(keys), "%d/%d" % (len(keys) - len(gone), len(keys)), not gone,
         ("缺键：" + ",".join(gone)) if gone else "")
    parts = set()
    if st.get("docx"):
        try:
            parts = set(zipfile.ZipFile(Path(st["out"]) / st["docx"]).namelist())
        except Exception:
            parts = set()
    need = {"word/document.xml", "word/styles.xml"}
    mark("I2", "成品可解包", sorted(need), len(parts), need <= parts, "缺 document.xml 或 styles.xml")
    graded = [s for s in st["spec"] if not s["inferred"] and s.get("quote")]
    hit = [s for s in graded if s.get("traceable")]
    mark("I3", "规格出处可命中", "100%", "%d/%d" % (len(hit), len(graded)) if graded else "n/a",
         (not graded) or len(hit) == len(graded), "未命中项已列入 pending_human")
    ratio = (st.get("cov") or {}).get("ratio")
    units = (st.get("cov") or {}).get("units")
    mark("I4", "内容单元保真", ">=0.98 且单元数>0", "ratio=%s units=%s" % (ratio, units),
         ratio is not None and ratio >= 0.98 and (units or 0) > 0,
         "核对 fidelity_report.coverage.missing；单元数为 0 说明原稿没解析出内容")
    font = (st.get("nums") or {}).get("font") or ""
    axis = 'w:ascii="%s"' % font
    mark("I5", "字体已写入样式", axis, "hit" if axis in st.get("sx", "") else "miss",
         bool(font) and axis in st.get("sx", ""), "核对 font_resolution 与降级记录")
    draft = (st.get("xref") or {}).get("dangling") or []
    mark("I6", "交叉引用不越界", 0, len(draft), not draft, "正文图表号超出题注总数")
    shown, rolled = len(payload.get("format_spec") or []), (payload.get("result") or {}).get("spec_items")
    mark("I7", "规格计数自洽", len(st["spec"]), "%s/%s/%s" % (shown, rolled, len(st["spec"])),
         shown == rolled == len(st["spec"]), "format_spec 与 result.spec_items 必须同源")
    return rows
