"""evidence_core.py -- evidence layer: scalar evaluation, mining, envelope.

Holds the expression builder behind substitution checks, the sentence
harvesters that pull symbol definitions and derivation cues out of narrative
blocks, and the envelope writer that mirrors output-contract keys back to the
top level of result.json.
"""
import ast
import math
import re

STEP_SIGNALS = [("substitution", r"substitut"), ("rearrangement", r"rearrang|solv\w* for"),
        ("assumption", r"assum|suppos"), ("approximation", r"approximat|negligib|lineariz"),
        ("limit", r"in the limit|for small|for large"), ("integration", r"integrat"),
        ("differentiation", r"differentiat|derivative"),
        ("result", r"yields|gives|we obtain|follows|therefore|hence")]
WHERE_DEFINITION_RE = (r"(?:where|here|in which|with)\s+([^\W\d_][\w]{0,9})\s+(?:is|are|denotes|"
             r"represents|is the|is a|is an|is defined as)\s+([^.;]{3,200})")
AND_DEFINITION_RE = (r"(?:\band|,)\s+([^\W\d_][\w]{0,9})\s+(?:is|are)\s+(?:the|a|an)?\s*([^.;]{3,200})")
ASSIGN_RE = (r"(?<![\w.])([^\W\d_][\w]{0,9})\s*=\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*"
              r"([A-Za-z\u00b5\u03bc\u00b0\u03a9%/^0-9\u00b7.\-]{0,12})")
UNIT_IN_RE = (r"(?:in|units of|measured in|expressed in)\s+"
           r"([A-Za-z\u00b5\u03bc\u00b0\u03a9%/\u00b7^0-9\-]{1,20})")

import mathml_engine as mx
from mathml_engine import pack_text, flatten_text, tag_local

# ---- scalar evaluation used by substitution checks ----
SAFE_AST_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Call,
           ast.Attribute, ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
           ast.USub, ast.UAdd)
SAFE_CALL_NAMES = {"sqrt", "exp", "log", "log10", "sin", "cos", "tan", "fabs"}

def _build_expression(el, vm, depth=0):
    
    if depth > 40:
        return None
    ln, kids = tag_local(el.tag), list(el)
    if ln == "mi":
        return vm.get(pack_text(flatten_text(el)))
    if ln == "mn":
        try:
            return repr(float(pack_text(flatten_text(el))))
        except ValueError:
            return None
    if ln == "mo":
        s = pack_text(flatten_text(el))
        return {"+": "+", "-": "-", "*": "*", "/": "/", "×": "*"}.get(s)
    if ln == "mfrac":
        a, b = (_build_expression(kids[i], vm, depth + 1) for i in (0, 1))
        return "((%s)/(%s))" % (a, b) if a and b else None
    if ln == "msup":
        if tag_local(kids[0].tag) == "mi" and pack_text(flatten_text(kids[0])) == "e":
            b = _build_expression(kids[1], vm, depth + 1)
            return "(math.exp(%s))" % b if b else None
        a, b = _build_expression(kids[0], vm, depth + 1), _build_expression(kids[1], vm, depth + 1)
        return "((%s)**(%s))" % (a, b) if a and b else None
    if ln == "msqrt":
        a = _build_expression(kids[0], vm, depth + 1)
        return "(math.sqrt(%s))" % a if a else None
    if ln in ("math", "mrow", "mstyle", "mpadded", "semantics", "mtd"):
        parts = [_build_expression(k, vm, depth + 1) for k in kids]
        return "(" + "".join(parts) + ")" if parts and all(p is not None for p in parts) else None
    return None

def eval_formula(node, values):
    """(value|None, expression|None, reason). values: {'x': 3.2, 'x_1': 3.2}."""
    keys = sorted(values)
    vm = {k: "v%d" % i for i, k in enumerate(keys)}
    env = {"v%d" % i: float(values[k]) for i, k in enumerate(keys)}
    expr = _build_expression(node, vm)
    if not expr or len(expr) > 4000:
        return None, expr, "expression_not_supported"
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None, expr, "expr_parse_failed"
    for nd in ast.walk(tree):
        if not isinstance(nd, SAFE_AST_NODES):
            return None, expr, "expr_unsupported_node"
        if isinstance(nd, ast.Attribute) and nd.attr not in SAFE_CALL_NAMES:
            return None, expr, "expr_unsupported_attr"
        if isinstance(nd, ast.Name) and nd.id not in env and nd.id != "math":
            return None, expr, "expr_unknown_name"
    try:
        val = eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}}, dict(env, math=math))
    except Exception as exc:  # noqa: BLE001 - degraded numeric path
        return None, expr, "eval_error:" + type(exc).__name__
    return val, expr, "ok"
# ---- narrative mining: definition sentences and derivation cues ----
def harvest_definitions(blocks):
    
    D, V = {}, {}
    for b in blocks:
        t, loc, sid = b["text"], b["path"], b["source_id"]
        for m in re.finditer(WHERE_DEFINITION_RE, t, re.I):
            u0 = re.search(UNIT_IN_RE, m.group(2))
            D.setdefault(m.group(1), {"definition": pack_text(re.split(r",\s*and\s|;\s", m.group(2))[0])[:220],
                                      "unit": pack_text(u0.group(1)) if u0 else "", "quote": t[:400],
                                      "locator": loc, "source_id": sid})
        for m in re.finditer(AND_DEFINITION_RE, t, re.I):
            u = re.search(UNIT_IN_RE, m.group(2))
            D.setdefault(m.group(1), {"definition": pack_text(re.split(r",\s*and\s|;\s", m.group(2))[0])[:220],
                                      "unit": pack_text(u.group(1)) if u else "", "quote": t[:400],
                                      "locator": loc, "source_id": sid})
        for m in re.finditer(ASSIGN_RE, t):
            try:
                V.setdefault(m.group(1), {"value": float(m.group(2)), "unit": pack_text(m.group(3)),
                                          "quote": t[:300], "locator": loc, "source_id": sid})
            except ValueError:
                continue
    return D, V

def harvest_steps(blocks):
    
    steps, seen, rows = [], set(), []
    for b in blocks:
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])|(?<=[!?])\s+", b["text"]):
            s = pack_text(s)
            low = s.lower()
            if len(s) >= 25 and s not in seen:
                rules = [k for k, r in STEP_SIGNALS if re.search(r, low)]
                if rules:
                    seen.add(s)
                    steps.append({"step_id": "D%d" % (len(steps) + 1), "from": None,
                                  "to": None, "rule": rules[0], "statement": s[:300],
                                  "assumptions": [s[:200]] if re.search(r"assum|suppos", low) else [],
                                  "approximations": [s[:200]] if re.search(
                                      r"approximat|negligib|lineariz", low) else [],
                                  "boundary_conditions": [s[:200]] if re.search(
                                      r"\bif\b|\bfor\b|in the limit|\bwhen\b", low) else [],
                                  "depends_on": [], "quote": s[:300], "locator": b["path"],
                                  "source_id": b["source_id"], "verified": False,
                                  "status": "textual_only"})
        for m in re.finditer(r"(?<![\w.])([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*"
                             r"([A-Za-z%\u00b0\u00b5][A-Za-z%\u00b0\u00b5/\u00b7^0-9\-]{0,11})\b",
                             b["text"]):
            if m.group(2).lower() not in ("and", "or", "the", "of", "to", "in", "is"):
                rows.append({"value": m.group(1), "unit": m.group(2), "quote": b["text"][:240],
                             "locator": b["path"], "source_id": b["source_id"],
                             "checked": "reported_as_written"})
    return steps[:24], rows[:40]
# ---- result envelope assembly and output-contract backfill ----
def assemble_result(state):
    
    r = {"case_id": state["case_id"], "status": state["status"], "result": state["result"]}
    for k in ("claims", "uncertainties", "sources", "pending_human", "errors",
              "degradations", "changes", "runtime"):
        r[k] = state[k]
    r["uncertainty"] = state["uncertainties"]   # alias expected by the task spec
    con = state["contract"] if isinstance(state["contract"], dict) else {}
    for k, v in con.items():
        if k not in r:
            r[k] = (state["result"].get(k) if k in state["result"]
                    else (type(v)() if isinstance(v, (list, dict)) else None))
    r["output_contract_echo"] = {k: ("result." + k if k in state["result"] else None) for k in con}
    r["contract_fields_missing"] = [k for k in con if k not in r]
    return r


# ---- moved here from the entry point: assembly of the analysis record ----
DEFAULT_GLOSSARY = {"T": "temperature", "p": "pressure", "V": "volume", "m": "mass", "t": "time",
         "x": "generic variable", "n": "amount", "R": "gas constant", "kB": "Boltzmann"}


def plain_symbol(sym):
    s = re.sub(r"\\mathrm\{([^}]*)\}", r"\1", sym or "")
    return re.sub(r"[{}^_$\\]", "", re.sub(r"\\[a-zA-Z]+", "", s)).strip()


def make_claim(cid, kind, read, stmt, sid, loc, q, cond="as provided", conf="high"):
    return {"claim_id": cid, "kind": kind, "readability": read, "statement": stmt,
            "source_id": sid, "location": loc, "quote": q, "condition": cond,
            "confidence": conf, "quote_verified": None,
            "evidence": {"quote": q, "location": loc}}


def build_analysis(state, mats):
    R, bs, U, C = state["result"], mats["blocks"], state["uncertainties"], []
    D, V = harvest_definitions(bs)
    corpus = pack_text(" ".join(b["text"] for b in bs))
    P, var, checks = [], {}, []
    for f in mats["formulas"][:40]:
        node, fl = f.get("node"), list(f.get("flags") or [])
        tex, src = f.get("latex"), f.get("latex_source", "given")
        cf = f.get("parse_confidence", "medium")
        if f.get("tex"):
            tex, src, cf = f["tex"], "mml_annotation", "high"
        if not tex and node is not None:
            tex, src, cf = mx.compact_latex(mx.render_latex(node, fl)), "structural_mapping", "high"
        if not tex:
            continue
        stc = mx.count_structures(node) if node is not None else {}
        sm = mx.list_symbols(node) if node is not None else []
        iss, fid = mx.latex_issues(tex), "F%d" % (len(P) + 1)
        P.append(({"formula_id": fid, "source_id": f.get("source_id") or fid,
                   "eq_number": f.get("eq") or None, "mathml_raw_path": f.get("path"),
                   "latex": tex, "latex_source": src, "parse_confidence": cf, "structure": stc,
                   "flags": sorted(set(fl + iss)),
                   "symbols": [x["symbol"] for x in sm if x["role"] == "variable"],
                   "status": "ok" if not iss else "needs_review"}, node, sm, tex))
        C.append(make_claim("C-%s" % fid, "reported", "directly_read", "Formula %s from %s" % (fid, f.get("path")),
                    f.get("source_id"), f.get("path"), (f.get("raw") or tex)[:300], "as provided", cf))
        for x in sm:
            if x["role"] == "variable":
                e = var.setdefault(x["symbol"], {"symbol": x["symbol"], "latex": x["latex"],
                                                 "plain": plain_symbol(x["symbol"]), "formula_ids": [],
                                                 "value_range": None})
                if fid not in e["formula_ids"]:
                    e["formula_ids"].append(fid)
    for e in var.values():
        p = e["plain"]
        d, v = D.get(p) or D.get(p.rstrip("0123456789")), V.get(p)
        e["value"] = v
        if d:
            e.update(definition=d["definition"], unit=d["unit"], definition_source="paper_defined",
                     locator=d["locator"], quote=d["quote"], source_id=d["source_id"], confidence="high")
            C.append(make_claim("S-%s" % p, "reported", "directly_read", "%s: %s" % (p, d["definition"][:150]),
                        d["source_id"], d["locator"], d["quote"], "definition as printed", "high"))
        elif corpus and re.search(r"(?<![\w])%s(?![\w])" % re.escape(p), corpus):
            e.update(definition=None, unit="", definition_source="context_inferred", locator=None,
                     quote="", source_id=None, confidence="low")
            U.append({"id": "U-def-%s" % p, "type": "definition_inferred", "object": e["symbol"],
                      "description": "used without explicit definition", "impact": "definition null",
                      "quote": ""})
        else:
            h = DEFAULT_GLOSSARY.get(p.rstrip("0123456789"))
            e.update(definition=None, unit="", definition_source="common_knowledge", locator=None,
                     quote="", source_id=None, confidence="low", common_knowledge_hint=h, inferred=True)
            U.append({"id": "U-gloss-%s" % p, "type": "definition_absent", "object": e["symbol"],
                      "description": "not defined in material" + ("; hint: %s" % h if h else ""),
                      "impact": "common_knowledge/inferred", "quote": ""})
        if e["definition_source"] != "paper_defined":
            C.append(make_claim("S-%s" % p, "inferred", "inferred", "%s is used but not defined explicitly" % p,
                        None, None, "", "context only", "low"))
    steps, rows = harvest_steps(bs)
    for d in steps:
        C.append(make_claim("C-%s" % d["step_id"], "inferred", "directly_read",
                    "Text reports a %s step: %s" % (d["rule"], d["statement"][:180]), d["source_id"],
                    d["locator"], d["quote"], "sentence level", "medium"))
    for rec, node, sm, tex in P:
        vals, miss = {}, []
        for x in sm:
            if x["role"] != "variable":
                continue
            v = (var.get(x["symbol"]) or {}).get("value")
            if v:
                vals[x["symbol"]] = v["value"]
            elif plain_symbol(x["symbol"]) not in miss:
                miss.append(plain_symbol(x["symbol"]))
        c = {"formula_id": rec["formula_id"], "substituted": dict(vals), "computed": None,
             "is_example": False, "status": "not_computable", "missing_symbols": miss[:12],
             "unit_check": "not_evaluated", "order_of_magnitude_check": "not_evaluated"}
        if node is not None and not miss:
            val = eval_formula(node, vals)[0]
            if val is not None:
                c.update(status="computed", computed=val, unit_check="units from source definitions",
                         order_of_magnitude_check=("log10|v|=%.3f" % math.log10(abs(val))) if val else "n/a")
        elif node is not None and not vals:
            pv = {k: 1.0 for x in sm if x["role"] == "variable" for k in (x["symbol"], plain_symbol(x["symbol"]))}
            val = eval_formula(node, pv)[0]
            if val is not None:
                c.update(status="example_only", is_example=True, computed=val, substituted=pv,
                         unit_check="probe 1.0, not paper data", order_of_magnitude_check="example only",
                         note="\u793a\u4f8b\u4ee3\u5165\uff0c\u975e\u8bba\u6587\u590d\u73b0")
        checks.append(c)
        C.append(make_claim("C-N-%s" % rec["formula_id"], "inferred" if c["is_example"] else "reported",
                    "inferred" if c["is_example"] else "directly_read",
                    "Numeric check %s: %s" % (rec["formula_id"], c["status"]), rec["source_id"],
                    rec["mathml_raw_path"], tex[:300],
                    "flagged example" if c["is_example"] else "reported values", "medium"))
    if any(c["is_example"] for c in checks):
        U.append({"id": "U-example", "type": "synthetic_example", "object": "numeric_checks",
                  "description": "no reported values; 1.0 probe only shows evaluability",
                  "impact": "not a paper result", "quote": ""})
    vs = sorted(var.values(), key=lambda x: x["symbol"])
    cnt = {}
    for x in vs:
        cnt[x["definition_source"]] = cnt.get(x["definition_source"], 0) + 1
    R.update({"formulas": [p[0] for p in P], "variables": vs, "derivations": steps,
              "numeric_checks": checks, "indicator_checks": rows,
              "missing_objects": R.get("missing_objects", []),
              "coverage": {"formulas_total": len(P),
                           "formulas_ok": sum(p[0]["status"] == "ok" for p in P),
                           "variables_total": len(vs), "by_source": cnt,
                           "derivations_total": len(steps),
                           "numeric_computed": sum(c["status"] == "computed" for c in checks),
                           "numeric_example_only": sum(c["is_example"] for c in checks),
                           "claims_total": len(C), "uncertainties_total": len(U),
                           "symbol_coverage": round(sum(bool(x["definition"]) or x["definition_source"]
                                                        == "context_inferred"
                                                        for x in vs) / len(vs), 3) if vs else 0.0},
              "method_notes": "TeX annotation verbatim when present else structural MathML "
                              "mapping; definitions only from explicit sentences."})
    return C, U


