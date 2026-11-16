#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract.py — 输入盘查与排版规格抽取。

把目录内容分角色（模板 / 原稿 / 格式要求），再从文本规定、LaTeX 类文件里抽出逐项
取值，合并成一套带出处的规格，并换算成 OOXML 单位。仅标准库。
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import ooxml  # noqa: E402

# 中文字号 → pt
CJK_PT = {"初号": 42, "一号": 26, "小一": 24, "二号": 22, "小二": 18, "三号": 16,
          "小三": 15, "四号": 14, "小四": 12, "五号": 10.5}

# 规格项与兜底值（20 项）：模板与格式要求都没写时才用，且标 inferred。
DEF = [("page.size", "A4"), ("page.margin.top", "2.54cm"), ("page.margin.bottom", "2.54cm"),
       ("page.margin.left", "2.54cm"), ("page.margin.right", "2.54cm"), ("page.columns", "1"),
       ("body.font", "Liberation Serif"), ("body.font.eastasia", "SimSun"), ("body.size", "12pt"),
       ("body.line_spacing", "1.5"), ("body.align", "both"), ("heading.1.size", "16pt"),
       ("heading.2.size", "14pt"), ("heading.3.size", "12pt"), ("title.size", "18pt"),
       ("caption.size", "10.5pt"), ("caption.table.position", "above"), ("reference.style", "numeric"),
       ("reference.size", "10.5pt"), ("toc.levels", "3")]

# 出处强度：模板本体 > LaTeX 类文件 > 文字规定
RANK = {"template_docx": 0, "template_tex": 1, "requirements": 2}

PROSE = [(r"字体[^\n。；]{0,10}?(Times New Roman|Liberation Serif|宋体|黑体|楷体|SimSun)", "body.font"),
         (r"(Times New Roman|Liberation Serif|SimSun|宋体|黑体|楷体)\s*(?:字体|字型)", "body.font"),
         (r"字号[^\n。；]{0,8}?(\d+(?:\.\d+)?\s*pt|小[一二三四五]|初号|一号|二号|三号|四号|五号)", "body.size"),
         (r"行距[^\n。；]{0,8}?(\d+(?:\.\d+)?)", "body.line_spacing"),
         (r"(上|下|左|右)\s*(?:边距|margin)[^\n。；]{0,6}?(\d+(?:\.\d+)?\s*(?:cm|mm|in))", "margin"),
         (r"(单栏|双栏|两栏)", "page.columns"),
         (r"(?:图|表)注[^\n。；]{0,6}?(上方|上|下方|下)", "caption.table.position"),
         (r"(GB/T\s*7714|APA|IEEE|Vancouver|MLA|Chicago|Harvard|著者-出版年|顺序编码)", "reference.style")]

KIND = {".docx": "docx", ".dotx": "docx", ".doc": "docx", ".tex": "tex", ".cls": "tex", ".sty": "tex",
        ".pdf": "pdf", ".png": "image", ".jpg": "image", ".jpeg": "image", ".csv": "table",
        ".xlsx": "table", ".json": "json", ".md": "text", ".txt": "text"}
DOCS = ("docx", "tex", "text")


def as_num(v, d=0.0):
    m = re.search(r"-?[\d.]+", str(v))
    return float(m.group(0)) if m else d


def half(v, d=None):
    """pt → half-point（w:sz 的单位）。"""
    m = re.search(r"([\d.]+)", str(v))
    return int(round(float(m.group(1)) * 2)) if m else d


def scan(root):
    """递归盘点输入文件；跳过隐藏文件与 output/work 目录。"""
    root, out = Path(root), []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        if {"output", "work"} & set(p.relative_to(root).parts):
            continue
        out.append({"path": str(p), "kind": KIND.get(p.suffix.lower(), "other")})
    return out


def roles(files):
    """按文件名线索与类型分角色：(模板, 原稿, 格式要求)。"""
    tpl, draft, rules = [], [], []
    for f in files:
        nm = Path(f["path"]).name.lower()
        if (re.search(r"templ|模板", nm) or nm.endswith((".cls", ".sty"))) and f["kind"] in ("docx", "tex", "pdf"):
            tpl.append(f)
        elif re.search(r"requir|format|规定|要求|须知|格式", nm) and f["kind"] in ("text", "pdf", "json"):
            rules.append(f)
        elif re.search(r"manuscript|paper|draft|原稿|稿件|正文", nm) and f["kind"] in DOCS:
            draft.append(f)
    if not draft:
        spare = [f for f in files if f["kind"] in DOCS and f not in tpl + rules]
        draft = sorted(spare, key=lambda f: len(Path(f["path"]).name))[:1]
    return tpl[:2], draft[:1], [r for r in rules if r not in tpl][:3]


def content(path):
    """文本直接读；PDF 借 pdftotext，取不到返回空串。"""
    if Path(path).suffix.lower() != ".pdf":
        return ooxml.slurp_text(path)
    tool = shutil.which("pdftotext")
    if not tool:
        return ""
    tmp = Path(str(path) + ".txt")
    try:
        subprocess.run([tool, "-layout", str(path), str(tmp)], timeout=60, capture_output=True)
        return ooxml.slurp_text(tmp) if tmp.exists() else ""
    except Exception:
        return ""


def tex_to_md(text):
    """LaTeX → Markdown：只搬结构与公式，不改文字。"""
    body = text.split("\\begin{document}")[-1].split("\\end{document}")[0]
    body = re.sub(r"(?m)(?<!\\)%.*$", "", body)
    body = re.sub(r"\\(section|subsection|subsubsection)\*?\{([^}]*)\}",
                  lambda m: "\n%s %s\n" % ("#" * {"section": 1, "subsection": 2,
                                                  "subsubsection": 3}[m.group(1)], m.group(2)), body)
    body = re.sub(r"\\\[(.*?)\\\]", r"\n$$\1$$\n", body, flags=re.S)
    body = re.sub(r"\\begin\{(equation|align)\*?\}(.*?)\\end\{\1\*?\}", r"\n$$\2$$\n", body, flags=re.S)
    body = re.sub(r"\\(?:textbf|textit|emph|cite|ref|label|text)\{([^}]*)\}", r"\1", body)
    body = re.sub(r"\\(?:noindent|newpage|centering|small|large|bfseries|itshape)\b", "", body)
    return re.sub(r"\n\s*\n+", "\n\n", body)


def prose_spec(text, origin):
    """文字规定逐行抽规格。

    页边距一行常同时写四条（上下左右），这里对边距规则全量扫描；
    其余规则每行只取首个命中，避免同一句重复登记同一规格项。
    """
    out = []
    for no, line in enumerate(text.splitlines(), 1):
        for pat, item in PROSE:
            for m in re.finditer(pat, line, re.I):
                item_id = item
                val = m.group(1)
                if item_id == "body.size":
                    val = ("%gpt" % CJK_PT[val]) if val in CJK_PT else val.replace(" ", "")
                elif item_id == "body.line_spacing":
                    val = "%g" % as_num(val, 1.5)
                elif item_id == "margin":
                    item_id = "page.margin." + {"上": "top", "下": "bottom", "左": "left", "右": "right"}[val]
                    val = m.group(2).replace(" ", "")
                elif item_id == "page.columns":
                    val = 1 if val == "单栏" else 2
                elif item_id == "caption.table.position":
                    val = "above" if val.startswith("上") else "below"
                elif item_id == "reference.style":
                    val = "numeric" if re.search(r"7714|IEEE|Vancouver|顺序", val) else "author-year"
                out.append({"id": item_id, "value": str(val), "source": "requirements",
                            "quote": line.strip()[:120], "locator": "%s#L%d" % (origin, no),
                            "inferred": False})
                if item != "margin":
                    break
    return out


def tex_spec(text, origin):
    """从 .tex/.cls/.sty 的版面命令取规格。"""
    out = []

    def keep(item, val, quote):
        out.append({"id": item, "value": str(val), "source": "template_tex",
                    "locator": "%s#%s" % (origin, quote.strip()[:30]),
                    "quote": quote.strip()[:100], "inferred": False})

    for m in re.finditer(r"\\documentclass(?:\[([^\]]*)\])?", text):
        opt = m.group(1) or ""
        if "twocolumn" in opt or "onecolumn" in opt:
            keep("page.columns", 2 if "twocolumn" in opt else 1, m.group(0))
        sz = re.search(r"(\d+)pt", opt)
        if sz:
            keep("body.size", sz.group(1) + "pt", m.group(0))
    for m in re.finditer(r"\\(?:usepackage\[([^\]]*)\]\{geometry\}|geometry\{([^}]*)\})", text):
        opt = (m.group(1) or "") + "," + (m.group(2) or "")
        for k, v in re.findall(r"(top|bottom|left|right|margin)\s*=\s*([\d.]+\s*(?:cm|mm|in))", opt):
            keep("page.margin." + ("top" if k == "margin" else k), v.replace(" ", ""), m.group(0))
    for m in re.finditer(r"\\(setmainfont|setCJKmainfont)(?:\[[^\]]*\])?\{([^}]+)\}", text):
        keep("body.font.eastasia" if m.group(1) == "setCJKmainfont" else "body.font", m.group(2).strip(), m.group(0))
    for m in re.finditer(r"\\fontsize\{([\d.]+)pt\}", text):
        keep("body.size", m.group(1) + "pt", m.group(0))
    for m in re.finditer(r"\\(onehalfspacing|doublespacing|singlespacing)", text):
        keep("body.line_spacing", {"onehalfspacing": "1.5", "doublespacing": "2",
                                   "singlespacing": "1"}[m.group(1)], m.group(0))
    for m in re.finditer(r"\\linespread\{([\d.]+)\}", text):
        keep("body.line_spacing", m.group(1), m.group(0))
    for m in re.finditer(r"\\bibliographystyle\{(\w+)\}", text):
        keep("reference.style", "author-year" if m.group(1) in ("apalike", "plainnat") else "numeric", m.group(0))
    for m in re.finditer(r"\\captionsetup\{([^}]*)\}", text):
        opt = m.group(1)
        f = re.search(r"font\s*=\s*(\w+)", opt)
        if f:
            keep("caption.size", {"small": "9pt", "footnotesize": "8pt"}.get(f.group(1), "10pt"), m.group(0))
        p = re.search(r"position\s*=\s*(above|below)", opt)
        if p:
            keep("caption.table.position", p.group(1), m.group(0))
    if re.search(r"\\tableofcontents|tocbibind", text):
        keep("toc.levels", 3, "toc")
    return out


def merge(cands):
    """同项取优先级最高者；多值记冲突并留全部候选。"""
    ok, clash = [], []
    for item, fallback in DEF:
        grp = sorted([c for c in cands if c["id"] == item], key=lambda c: RANK.get(c["source"], 8))
        vals = []
        for c in grp:
            if c["value"] not in vals:
                vals.append(c["value"])
        if grp:
            pick = dict(grp[0], inferred=False)
            if len(vals) > 1:
                clash.append({"item": item, "chosen": pick["value"], "rule": "docx>tex>prose>default",
                              "values": [{"value": c["value"], "source": c["source"],
                                          "locator": c["locator"]} for c in grp]})
        else:
            pick = {"id": item, "value": fallback, "source": "default", "locator": "", "quote": "",
                    "inferred": True}
        ok.append(pick)
    return ok, clash


def units(spec):
    """规格 → OOXML 单位（twip / half-point），写出与自检共用。"""
    w = {s["id"]: s["value"] for s in spec}
    n = {"font": w["body.font"], "ea": w["body.font.eastasia"], "sz": half(w["body.size"], 24)}
    sp = str(w["body.line_spacing"]).lower()
    if sp.endswith("pt"):
        n["line"], n["lineRule"] = int(as_num(sp) * 20), "exact"
    else:
        n["line"], n["lineRule"] = int(round(as_num(sp, 1.5) * 240)), "auto"
    n["align"] = w["body.align"] if w["body.align"] in ("both", "left", "center", "right") else "both"
    n["t_sz"] = half(w["title.size"], n["sz"] + 8)
    n["cap_sz"] = half(w["caption.size"], n["sz"])
    n["ref_sz"] = half(w["reference.size"], n["sz"])
    n["fn_sz"] = max(14, n["sz"] - 4)
    paper = str(w["page.size"])
    if paper in ooxml.PAGE_TWIP:
        n["pgW"], n["pgH"] = ooxml.PAGE_TWIP[paper]
    else:
        dim = [float(v) for v in re.findall(r"[\d.]+", paper)] or [210, 297]
        n["pgW"], n["pgH"] = int(dim[0] / 25.4 * 1440), int((dim[1] if len(dim) > 1 else 297) / 25.4 * 1440)
    for key, side in (("marT", "top"), ("marB", "bottom"), ("marL", "left"), ("marR", "right")):
        raw = str(w["page.margin." + side])
        n[key] = (int(float(raw[:-2]) / (25.4 if raw.endswith("mm") else 2.54) * 1440)
                  if raw[-2:] in ("cm", "mm") else 1440)
    n["cols"] = max(1, int(as_num(w["page.columns"], 1)))
    n["col_sep"] = n["cols"] > 1
    n["h"] = {str(i): {"sz": half(w["heading.%d.size" % i], n["sz"]), "bold": True, "align": "left",
                       "before": 240, "after": 120} for i in (1, 2, 3)}
    n["toc_levels"] = int(as_num(w["toc.levels"], 0))
    n["ref_ind"] = n["ref_hang"] = 567
    return n
