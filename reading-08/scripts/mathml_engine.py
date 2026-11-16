"""mathml_engine.py -- MathML rendering layer of the formula evidence audit skill.

Jobs handled here: tolerate the three MathML namespace spellings, repair named
HTML entities before parsing, turn formula nodes into a deterministic LaTeX
string in document order, count structural building blocks, and inventory the
identifiers one formula actually uses.

Pure standard library. Nothing is guessed: a node outside the mapping table
becomes a placeholder plus a flag so a human can review it later.
"""
import html
import re
from xml.etree import ElementTree as ET

_GREEK_ROWS = list(zip("αβγδεζηθικλμνξοπρστυφχψω",
              "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi "
              "omicron pi rho sigma tau upsilon phi chi psi omega".split()))
_GREEK_ROWS += list(zip("ΓΔΘΛΞΠΣΥΦΨΩ",
               "Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega".split()))
LETTER_COMMANDS = {k: "\\" + v for k, v in _GREEK_ROWS}
LETTER_COMMANDS.update({"∂": "\\partial"})
FUNCTION_WORDS = {"sin", "cos", "tan", "cot", "sec", "csc", "log", "ln", "lg", "exp", "max", "min",
         "lim", "sup", "inf", "det", "arg"}
OPERATOR_TEX = {"-": "-", "+": "+", "=": "=", "<": "<", ">": ">", "*": "*", "/": "/", ",": ",",
       ";": ";", "(": "(", ")": ")", "[": "[", "]": "]", "|": "|", "×": "\\times",
       "·": "\\cdot", "±": "\\pm", "≤": "\\le", "≥": "\\ge", "≠": "\\neq",
       "≈": "\\approx", "∼": "\\sim", "∝": "\\propto", "→": "\\to", "∈": "\\in",
       "∑": "\\sum", "∫": "\\int", "√": "\\sqrt", "°": "^{\\circ}",
       "%": "\\%", "_": "\\_"}
WIDE_OPERATORS = {"\\sum", "\\prod", "\\int", "lim", "max", "min"}
CONTAINER_TAGS = {"disp-formula", "formula", "equation"}

def pack_text(s):
    return re.sub(r"\s+", " ", (s or "").replace("\u2212", "-")).strip()

def tag_local(tag):
    
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag.rsplit(":", 1)[-1]

def flatten_text(el):
    return "".join(el.itertext())
# ---- XML loading: namespace sniffing, entity repair, fallback paths ----
def _expand_entity(m):
    if m.group(1) in ("lt", "gt", "amp", "quot", "apos"):
        return m.group(0)
    rep = html.entities.html5.get(m.group(1) + ";") or html.entities.html5.get(m.group(1))
    return "".join("&#x%X;" % ord(c) for c in rep) if rep else "&amp;" + m.group(1) + ";"

def load_xml(txt):
    """Parse XML, repairing named entities first and an undeclared mml: prefix second.

    Returns (root, note) where note says which repair path was used. Raises when
    neither repair makes the markup parseable; the caller then degrades to a
    regex annotation scan.
    """
    try:
        return ET.fromstring(txt), "parsed"
    except ET.ParseError:
        pass
    body = re.sub(r"^\s*<\?xml[^>]*\?>", "", txt)
    body = re.sub(r"<!DOCTYPE[^>]*>", "", body, flags=re.S)
    repaired = re.sub(r"&([A-Za-z][A-Za-z0-9]{1,30});", _expand_entity, body)
    try:
        return ET.fromstring(repaired), "parsed_after_entity_repair"
    except ET.ParseError:
        pass
    if "mml:" in repaired and "xmlns:mml" not in repaired:
        bound = re.sub(r"<([A-Za-z][\w.-]*)(?=[\s>/])",
                       r'<\1 xmlns:mml="http://www.w3.org/1998/Math/MathML"', repaired, count=1)
        return ET.fromstring(bound), "parsed_after_namespace_repair"
    raise ET.ParseError("markup unrecoverable after entity and namespace repair")

def decode_file(path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")

def node_path(root, target):
    
    out = []

    def walk(node, cur):
        if node is target:
            out.extend(cur)
            return True
        seen = {}
        for k in list(node):
            ln = tag_local(k.tag)
            seen[ln] = seen.get(ln, 0) + 1
            if walk(k, cur + ["%s[%d]" % (ln, seen[ln])]):
                return True
        return False

    return "/" + "/".join(out) if walk(root, [tag_local(root.tag) + "[1]"]) else ""

def pick_id(el):
    for k in ("id", "source_id", "{http://www.w3.org/XML/1998/namespace}id"):
        if el.get(k):
            return el.get(k)
    return ""

def gather_formula_nodes(root):
    
    out, done = [], set()
    for el in root.iter():
        if tag_local(el.tag) not in CONTAINER_TAGS:
            continue
        math_el = next((m for m in el.iter() if tag_local(m.tag) == "math"), None)
        if math_el is None or id(math_el) in done:
            continue
        done.add(id(math_el))
        label = next((pack_text(flatten_text(k)) for k in el.iter() if tag_local(k.tag) == "label"), "")
        tex = next((pack_text(flatten_text(a)) for a in math_el.iter() if tag_local(a.tag) == "annotation"
                    and "tex" in (a.get("encoding") or "").lower()), "")
        out.append({"node": math_el, "fid": pick_id(el) or pick_id(math_el), "eq": label, "tex": tex,
                    "path": node_path(root, math_el),
                    "raw": pack_text(ET.tostring(math_el, encoding="unicode"))[:1500]})
    for m in [x for x in root.iter() if tag_local(x.tag) == "math"]:
        if id(m) not in done:
            done.add(id(m))
            out.append({"node": m, "fid": pick_id(m), "eq": "", "path": node_path(root, m),
                        "raw": pack_text(ET.tostring(m, encoding="unicode"))[:1500]})
    return out

def walk_text_blocks(root):
    
    out, seen = [], set()

    def walk(node):
        ln = tag_local(node.tag)
        if ln in ("math", "inline-formula", "disp-formula"):
            return
        if ln in ("p", "title", "caption", "td", "th", "list-item"):
            t = pack_text(flatten_text(node))
            if len(t) >= 8 and t not in seen:
                seen.add(t)
                out.append({"path": node_path(root, node), "text": t})
            return
        for k in list(node):
            walk(k)

    walk(root)
    return out
# ---- MathML -> LaTeX rendering (deterministic, order preserving) ----
def _braces_balanced(s):
    d, i = 0, 0
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        d += {"{": 1, "}": -1}.get(s[i], 0)
        if d < 0:
            return False
        i += 1
    return d == 0

def _group(s):
    s = s.strip()
    if not s:
        return "{}"
    if re.fullmatch(r"[A-Za-z0-9]|\\[A-Za-z]+", s):
        return s
    return s if (s[0] == "{" and s[-1] == "}" and _braces_balanced(s)) else "{" + s + "}"

def escape_char(c):
    return OPERATOR_TEX.get(c) or (c if c.isalnum() else "\\square")

def ident_latex(el):
    s = pack_text(flatten_text(el))
    if not s:
        return ""
    variant = (el.get("mathvariant") or "").lower()
    body = "".join(LETTER_COMMANDS.get(c, escape_char(c)) for c in s)
    if len(s) == 1:
        return body
    if s in FUNCTION_WORDS:
        return "\\" + s
    return ("\\mathrm{%s}" % body) if s.isalpha() else body

def render_latex(el, flags=None, depth=0):
    
    flags = flags if flags is not None else []
    if depth > 60:
        flags.append("max_nesting_depth")
        return "\\square"
    ln, kids = tag_local(el.tag), list(el)
    if ln == "semantics":
        for k in kids:
            if tag_local(k.tag) == "annotation" and "tex" in (k.get("encoding") or "").lower():
                return pack_text(flatten_text(k))
        return render_latex(kids[0], flags, depth + 1) if kids else ""
    if ln == "mi":
        return ident_latex(el)
    if ln == "mn":
        return pack_text(flatten_text(el)).replace(" ", "")
    if ln == "mtext":
        return "\\text{%s}" % pack_text(flatten_text(el)).replace("_", "\\_").replace("%", "\\%")
    if ln == "mo":
        s = pack_text(flatten_text(el))
        return OPERATOR_TEX.get(s) or "".join(OPERATOR_TEX.get(c, escape_char(c)) for c in s)
    if ln in ("mspace", "none", "prescripts"):
        return ""
    if ln in ("mstyle", "mpadded", "mphantom", "menclose", "math", "mrow", "mtd"):
        return "".join(filter(None, [render_latex(k, flags, depth + 1) for k in kids]))
    if ln == "mfrac":
        if len(kids) < 2:
            flags.append("mfrac_arity")
            return "\\frac%s{}" % _group(render_latex(kids[0], flags, depth + 1) if kids else "")
        return "\\frac%s%s" % (_group(render_latex(kids[0], flags, depth + 1)),
                              _group(render_latex(kids[1], flags, depth + 1)))
    if ln == "msqrt":
        return "\\sqrt{%s}" % "".join(render_latex(k, flags, depth + 1) for k in kids)
    if ln == "mroot":
        if len(kids) < 2:
            flags.append("mroot_arity")
            return "\\sqrt{}"
        return "\\sqrt[%s]{%s}" % (render_latex(kids[1], flags, depth + 1),
                                   render_latex(kids[0], flags, depth + 1))
    if ln in ("msub", "msup", "msubsup"):
        if len(kids) < 2:
            flags.append(ln + "_arity")
            return "".join(render_latex(k, flags, depth + 1) for k in kids)
        base = render_latex(kids[0], flags, depth + 1)
        sub = render_latex(kids[1], flags, depth + 1)
        if ln == "msub":
            return "%s_{%s}" % (_group(base), sub)
        sup = render_latex(kids[2], flags, depth + 1) if len(kids) > 2 else ""
        return "%s^{%s}" % (_group(base), sub) if ln == "msup" else "%s_{%s}^{%s}" % (
            _group(base), sub, sup)
    if ln in ("munder", "mover", "munderover"):
        base = render_latex(kids[0], flags, depth + 1) if kids else ""
        lo = render_latex(kids[1], flags, depth + 1) if len(kids) > 1 else ""
        hi = render_latex(kids[2], flags, depth + 1) if len(kids) > 2 else ""
        if ln == "munder":
            return "%s_{%s}" % (_group(base), lo)
        if ln == "mover":
            if pack_text(flatten_text(kids[1]) if len(kids) > 1 else "") in ("^", "~", "¯"):
                flags.append("accent_normalized")
                return "\\overline%s" % _group(base)
            return "%s^{%s}" % (_group(base), lo)
        if base.strip() not in WIDE_OPERATORS:
            flags.append("munderover_nonbigop")
        return "%s_{%s}^{%s}" % (_group(base) if base.strip() not in WIDE_OPERATORS else base, lo, hi)
    if ln == "mfenced":
        open_tok, close_tok = el.get("open", "("), el.get("close", ")")
        inner = ", ".join(render_latex(k, flags, depth + 1) for k in kids)
        if open_tok or close_tok:
            return "\\left%s %s\\right%s" % (OPERATOR_TEX.get(open_tok, open_tok) or ".",
                                             inner, OPERATOR_TEX.get(close_tok, close_tok) or ".")
        return inner
    if ln == "mtable":
        rows = [[render_latex(c, flags, depth + 1) for c in r if tag_local(c.tag) == "mtd"]
                for r in kids if tag_local(r.tag) in ("mtr", "mlabeledtr")]
        w = max((len(r) for r in rows), default=0)
        if not w:
            flags.append("empty_mtable")
            return "\\square"
        if w == 2 and len(rows) > 1:
            flags.append("mtable_as_cases")
            return "\\begin{cases} %s \\end{cases}" % " \\\\ ".join(
                "%s & %s" % (r[0], r[1] if len(r) > 1 else "") for r in rows)
        flags.append("mtable_as_matrix")
        return "\\begin{matrix} %s \\end{matrix}" % " \\\\ ".join(
            " & ".join(r + [""] * (w - len(r))) for r in rows)
    if ln in ("mtr", "mlabeledtr"):
        return " & ".join(render_latex(k, flags, depth + 1) for k in kids)
    flags.append("unmapped:" + ln)
    return "\\square"

def compact_latex(s):
    s = re.sub(r"\s+", " ", s or "").strip()
    sp = r"(\\times|\\cdot|\\pm|\\approx|\\le|\\ge|\\neq|\\sim|\\propto|\\to|\\in)"
    s = re.sub(r"(?<=[^\s{])(%s)" % sp, r" \1", s)
    s = re.sub(r"(%s)(?=[^\s}])" % sp, r"\1 ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.replace("\\left ", "\\left").replace("\\right ", "\\right").strip()
# ---- structural counters and the identifier inventory ----
def count_structures(el, acc=None):
    
    acc = acc if acc is not None else {"fracs": 0, "subsups": 0, "radicals": 0,
                                       "matrices": 0, "cases": 0}
    ln = tag_local(el.tag)
    if ln == "mfrac":
        acc["fracs"] += 1
    elif ln in ("msub", "msup", "msubsup"):
        acc["subsups"] += 1
    elif ln in ("msqrt", "mroot"):
        acc["radicals"] += 1
    elif ln == "mtable":
        w = max((len([c for c in r if tag_local(c.tag) == "mtd"]) for r in el
                 if tag_local(r.tag) in ("mtr", "mlabeledtr")), default=0)
        acc["cases" if w == 2 else "matrices"] += 1
    for k in el:
        count_structures(k, acc)
    return acc

def list_symbols(el, out=None):
    
    out = out if out is not None else []

    def add(sym, latex, role):
        for it in out:
            if it["symbol"] == sym:
                it["count"] += 1
                return
        out.append({"symbol": sym, "latex": latex, "role": role, "count": 1})

    def walk(node):
        ln, kids = tag_local(node.tag), list(node)
        if ln in ("msub", "msup", "msubsup") and kids and tag_local(kids[0].tag) == "mi":
            base = pack_text(flatten_text(kids[0]))
            if ln != "msub" and base in ("e", "10"):
                for k in kids[1:]:
                    walk(k)
                return
            sub = render_latex(kids[1]) if ln in ("msub", "msubsup") and len(kids) > 1 else ""
            sup = (render_latex(kids[1]) if ln == "msup" and len(kids) > 1 else
                   render_latex(kids[2]) if ln == "msubsup" and len(kids) > 2 else "")
            sym = base + ("_{%s}" % sub if sub else "") + ("^{%s}" % sup if sup else "")
            add(sym, ident_latex(kids[0]) + ("_{%s}" % sub if sub else "")
                + ("^{%s}" % sup if sup else ""),
                "operator" if base in FUNCTION_WORDS else "variable")
            return
        if ln == "mi":
            s = pack_text(flatten_text(node))
            if s:
                add(s, ident_latex(node), "operator" if s in FUNCTION_WORDS else "variable")
            return
        for k in kids:
            walk(k)

    walk(el)
    return out
def latex_issues(s):
    
    d, bad, i = 0, False, 0
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        d += {"{": 1, "}": -1}.get(s[i], 0)
        bad = bad or d < 0
        i += 1
    return [k for k, c in (("empty_latex", not s), ("unbalanced_braces", bad or d),
                           ("placeholder_square", "\\square" in s)) if c]
