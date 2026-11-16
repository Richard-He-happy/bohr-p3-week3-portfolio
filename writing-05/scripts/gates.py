#!/usr/bin/env python3
"""Six structural gates for manuscript-blueprint-audit (detection + self-check).

Imported by audit.py, which owns input discovery, segmentation and rendering.
Here: helpers, the quote anchor, the six gates, action building, coverage,
contract back-fill and an artifact checker. A finding exists only once its quote
is located in the source; the manuscript is never edited.

  python3 -B gates.py                                       # ruleset self-report
  python3 -B gates.py --work /app/output --input /input      # artifact check
"""

import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIMENSIONS = ("research_question_alignment", "section_structure", "argument_chain",
       "paragraph_relations", "duplication", "conclusion_boundary")
OPS = ("move", "merge", "split", "narrow", "delete", "insert")
OP_OF = {"research_question_alignment": "narrow", "section_structure": "move",
    "argument_chain": "insert", "paragraph_relations": "split",
    "duplication": "merge", "conclusion_boundary": "narrow"}
PRIO = {"high": "P1", "medium": "P2", "low": "P3"}
SKIP = ("references", "ack", "appendix")
STATUSES = ("findings", "no_issue_with_evidence", "degraded_by_error", "not_assessable")
RULE_KEYS = ("question", "contribution", "cite", "quantity", "figure_ref", "figure_caption",
      "claim_marker", "handoff_marker", "causal", "hedge", "absolute", "association",
      "design", "ref_entry")


def _load():
  for cand in (HERE.parent / "references" / "ruleset.json", HERE / "ruleset.json"):
    if cand.is_file():
      try:
        data = json.loads(cand.read_text(encoding="utf-8"))
      except Exception:
        return {}
      return data if isinstance(data, dict) else {}
  return {}


RULES = _load()
RULES_OK = bool(RULES)
_NEVER = re.compile(r"$^")
P = {}
for _k, _v in (RULES.get("patterns") or {}).items():
  try:
    P[_k] = re.compile(_v)
  except re.error:
    pass
for _k in RULE_KEYS:
  P.setdefault(_k, _NEVER)      # a missing rule never matches: no invented findings
ROLES = []
for _pair in (RULES.get("roles") or []):
  try:
    ROLES.append((_pair[0], re.compile(_pair[1])))
  except Exception:
    pass
STOP = set(("the a an and or of to in for on with as at by from that this these those is are was "
      "were be been we our it its not no than then using used use can may also such more most "
      "other into between within under over all any both each how what which while where when "
      "who has have had do does did one two three study paper results data").split())
CUT = set(".!?。！？;；")
ABBR = set("fig tab eq ref no vol pp cf vs etc al eg ie sec".split())


def squash(t):
  return re.sub(r"\s+", " ", t or "").strip()


def wc(t):
  t = t or ""
  return len(re.findall(r"[A-Za-z][A-Za-z\-']*", t)) + len(re.findall(r"[\u4e00-\u9fff]", t)) // 2


def _cut_ok(t, i):
  if t[i] != ".":
    return True
  if 0 < i < len(t) - 1 and t[i - 1].isdigit() and t[i + 1].isdigit():
    return False
  j = i - 1
  while j >= 0 and (t[j].isalnum() or t[j] == "."):
    j -= 1
  return not (t[j + 1:i].replace(".", "").lower() in ABBR) and (
    i + 1 >= len(t) or t[i + 1].isspace())


def sents(t):
  out, head, t = [], 0, (t or "")
  for i, ch in enumerate(t):
    if ch in CUT and _cut_ok(t, i):
      out.append(t[head:i + 1])
      head = i + 1
  if head < len(t):
    out.append(t[head:])
  return [s.strip() for s in out if wc(s) >= 2]


def toks(t):
  low = (t or "").lower()
  cjk = re.findall(r"[\u4e00-\u9fff]", low)
  latin = [w for w in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", low) if w not in STOP]
  if len(cjk) > max(6, len(latin) * 3):
    return set([cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)] + latin)
  return set(latin)


def jac(a, b):
  return 0.0 if not a or not b else len(a & b) / float(len(a | b))


def locate(plain, fragment):
  """(start, end) span of `fragment` in `plain`, or None.

  Tail drift is repaired by shortening the probe, so a quote that starts
  verbatim in the manuscript survives one mismatched trailing character.
  """
  q, lp = squash(fragment), (plain or "").lower()
  if not q or not plain:
    return None
  for probe, src in ((q, plain), (q.lower(), lp)):
    if probe in src:
      s = src.index(probe)
      return s, s + len(probe)
  cut = len(q)
  while cut > 20:
    cut -= 3
    short = q[:cut].rstrip()
    if len(short) <= 20:
      break
    for probe, src in ((short, plain), (short.lower(), lp)):
      if probe in src:
        s = src.index(probe)
        return s, s + len(probe)
  return None


def TH(key, default):
  v = (RULES.get("thresholds") or {}).get(key, default)
  return v if isinstance(v, (int, float)) else default


def msg(bucket, key, **fmt):
  table = RULES.get(bucket)
  raw = table.get(key) if isinstance(table, dict) else None
  if not isinstance(raw, str):
    return ""
  try:
    return raw.format(**fmt)
  except Exception:
    return raw


def label(group, key):
  return ((RULES.get("labels") or {}).get(group) or {}).get(key, key)


class Audit:
  """Findings, actions and per-dimension notes for one manuscript."""

  def __init__(self, plain, text, chapters, paragraphs, truncated=False):
    self.plain, self.text, self.ch, self.pa = plain, text, chapters, paragraphs
    self.trunc = truncated
    self.F, self.A, self.PH, self.ER, self.AN, self.Q, self.N = [], [], [], [], [], [], {}
    self.bad, self.dropped = set(), 0

  def hold(self, kind, detail, needed):
    self.PH.append({"item_id": "PH%02d" % (len(self.PH) + 1), "kind": kind,
            "detail": detail, "needed_action": needed})

  def first(self, paras, key, floor=0):
    for p in paras:
      for loc, s in p["sents"]:
        if P[key].search(s) and wc(s) >= floor:
          return loc, s
    return "", ""

  def anchor(self, raw):
    clip = int(TH("clip_chars", 150))
    q = squash(raw)
    if not q:
      return None
    probes = [q[:w] for w in (clip, clip * 2, clip * 3)]
    probes += [q[:c] for c in range(min(len(q), clip + 90), 16, -4)]
    for probe in probes:
      span = locate(self.plain, probe)
      if span:
        return self.plain[span[0]:span[1]], span[0], span[1]
    return None

  def rec(self, dim, sev, loc, raw, rule, op=None, to="", conf="medium", **fmt):
    hit = self.anchor(raw)
    if not hit:
      self.dropped += 1
      self.ER.append({"stage": "anchor", "rule": rule,
              "detail": "dropped %s at %s: quote absent" % (rule, loc)})
      return None
    quote, start, end = hit
    fid = "F%02d" % (len(self.F) + 1)
    self.F.append({"finding_id": fid, "dimension": dim, "severity": sev, "locator": loc,
           "quote": quote, "diagnosis": msg("diagnosis", rule, **fmt), "evidence_for_judgment":
             msg("basis", rule, **fmt) or msg("diagnosis", rule, **fmt), "confidence": conf})
    self.AN.append({"finding_id": fid, "rule": rule, "start": start, "end": end})
    use = op if op in OPS else OP_OF[dim]
    self.Q.append({"finding_id": fid, "operation": use, "from_locator": loc, "to_locator": to or loc,
           "expected_effect": msg("effect", rule, **fmt) or msg("default_effect", dim),
           "risk": msg("hazard", rule, **fmt) or msg("default_hazard", use),
           "priority": PRIO.get(sev, "P2"), "executable": True})
    return self.F[-1]

  def body(self):
    return [p for p in self.pa if p["role"] not in SKIP]

  def joined(self, roles):
    return "\n".join(p["text"] for p in self.pa if p["role"] in roles)

  # gate 1
  def g_sections(self):
    g = {}
    for p in self.pa:
      g.setdefault(p["role"], []).append(p)
    self.N["chapters"] = len(self.ch)
    if len(self.ch) <= 1:
      h = self.pa[0]
      self.rec("section_structure", "high", h["loc"], h["text"], "SEC1", "insert",
          conf="high", ch=len(self.ch), pp=len(self.pa))
      return
    have = sorted(g)
    for role in ("introduction", "method", "result", "conclusion"):
      if role in have or (role == "conclusion" and {"conclusion", "discussion"} & set(have)):
        continue
      if self.trunc:
        self.hold("truncated_manuscript", msg("pending", "PD_TRUNC_DIM", label=label("role", role)),
             msg("pending", "PD_TRUNC_DIM_N"))
        continue
      t = self.pa[-1]
      self.rec("section_structure", "high", t["loc"], t["text"], "SEC2", "insert",
          conf="high", label=label("role", role), role=role,
          present=", ".join(have) or "none", pp=len(self.pa))
    seq = [(c["loc"], c["role"]) for c in self.ch if c["role"] in
       ("introduction", "method", "result", "discussion", "conclusion")]
    names = [r for _l, r in seq]
    for early, late in (("method", "result"), ("result", "discussion"),
              ("result", "conclusion")):
      if early in names and late in names and names.index(early) > names.index(late):
        bl = next(l for l, r in seq if r == late)
        al = next(l for l, r in seq if r == early)
        h = next((p for p in self.pa if p["loc"].startswith(bl)), None)
        if h:
          self.rec("section_structure", "high", h["loc"], h["text"], "SEC3", "move",
              to=al, conf="high", a=label("role", early), b=label("role", late), cl=bl, ce=al,
              seq=" > ".join("%s(%s)" % (l, r) for l, r in seq))
        break
    tot = sum(c["words"] for c in self.ch) or 1
    self.N["share"] = {c["loc"] + " " + (c["title"] or "")[:40]:
             round(c["words"] / float(tot), 3) for c in self.ch}
    ref = (g.get("references") or [None])[0]
    if ref and not P["ref_entry"].search(ref["text"]):
      self.rec("section_structure", "medium", ref["loc"], ref["text"], "SEC5", "insert", conf="medium")

  # gate 2
  def g_question(self):
    pool = [p for p in self.pa if p["role"] in ("abstract", "introduction", "body")] or self.pa
    loc, sentence = self.first(pool[:8], "question", 8)
    if not sentence:
      if wc(self.text) < 300:
        self.hold("no_research_question", msg("pending", "PD_NO_RQ"), msg("pending", "PD_NO_RQ_N"))
        return
      h = pool[0]
      self.rec("research_question_alignment", "high", h["loc"], h["text"], "RQ1", "insert",
          conf="medium", pp=len(pool[:8]))
      return
    down = toks(self.joined(("result", "discussion", "conclusion")) or self.text)
    keys = sorted([t for t in toks(sentence) if len(t) > 4])[:10]
    miss = [t for t in keys if t not in down]
    if keys and len(miss) >= max(3, int(0.5 * len(keys))):
      self.rec("research_question_alignment", "high", loc, sentence, "RQ2", "narrow",
          conf="medium", terms=", ".join(keys), t=len(keys), k=len(miss), miss=", ".join(miss[:6]))
    cloc, claim = self.first(pool[:6], "contribution")
    if claim and len(claim) > 40:
      ck = sorted([t for t in toks(claim) if len(t) > 4])[:8]
      lost = [t for t in ck if t not in down]
      if ck and len(lost) >= max(3, int(0.6 * len(ck))):
        self.rec("research_question_alignment", "medium", cloc, claim, "RQ3", "narrow",
            conf="low-medium", terms=", ".join(ck), t=len(ck), k=len(lost))

  # gate 3
  def g_arguments(self):
    listed = set(int(x) for x in P["ref_entry"].findall(self.text))
    cited, holder, body = set(), {}, self.body()
    self.N["body_paras"] = len(body)
    floor = int(TH("claim_paragraph_min_words", 30))
    for para in body:
      support = [s for _l, s in para["sents"] if P["cite"].search(s)
           or P["quantity"].search(s) or P["figure_ref"].search(s)]
      claims = [(l, s) for l, s in para["sents"] if P["claim_marker"].search(s)
           and not (P["cite"].search(s) or P["quantity"].search(s)
               or P["figure_ref"].search(s))]
      for sl, s in para["sents"]:
        for found in P["cite"].finditer(s):
          for num in re.findall(r"\d+", found.group(0)):
            cited.add(int(num))
            holder.setdefault(int(num), (sl, s))
      if claims and not support and wc(para["text"]) >= floor and para["role"] != "abstract":
        sev = "high" if para["role"] in ("result", "discussion", "conclusion") else "medium"
        self.rec("argument_chain", sev, claims[0][0], claims[0][1], "ARG1", "insert",
            conf="medium", n=len(para["sents"]), c=len(claims))
    for num in (sorted(cited - listed)[:3] if listed else []):
      loc, sentence = holder.get(num, ("", ""))
      if loc:
        self.rec("argument_chain", "high", loc, sentence, "ARG2", "insert", conf="high",
            n=num, u=len(cited), r=len(listed),
            bad=", ".join(str(x) for x in sorted(cited - listed)[:5]))
    if cited and not listed:
      self.hold("no_reference_list", msg("pending", "PD_NOREF", n=len(cited)),
           msg("pending", "PD_NOREF_N"))
    caps = set(m.group(1) for m in (P["figure_caption"].match(x.strip())
                   for x in self.text.splitlines()) if m)
    refs = set(P["figure_ref"].findall(self.text))
    orphan = sorted(refs - caps)
    if orphan:
      for para in self.pa:
        hit = [(l, s) for l, s in para["sents"]
           if orphan[0] in P["figure_ref"].findall(s)]
        if hit:
          self.rec("argument_chain", "medium", hit[0][0], hit[0][1], "ARG3", "insert",
              conf="medium", lab=orphan[0], ref=", ".join(sorted(refs)) or "none",
              cap=", ".join(sorted(caps)) or "none")
          break
    self.N["citation"] = {"in_text": len(cited), "listed": len(listed),
               "unresolved": sorted(cited - listed)[:10] if listed else [],
               "figure_refs": sorted(refs), "captions": sorted(caps)}

  # gate 4
  def g_paragraphs(self):
    body = self.body()
    terms = {p["loc"]: toks(p["text"]) for p in body}
    min_w = int(TH("handoff_min_words", 55))
    floor = float(TH("handoff_jaccard", 0.05))
    raised = 0
    for left, right in zip(body, body[1:]):
      if raised >= 2 or left["ch"] != right["ch"]:
        continue
      if wc(left["text"]) < min_w or wc(right["text"]) < min_w:
        continue
      score = jac(terms[left["loc"]], terms[right["loc"]])
      if score < floor and not P["handoff_marker"].match(right["text"]):
        raised += 1
        loc, s = right["sents"][0]
        self.rec("paragraph_relations", "low", loc, s, "PAR1", "insert",
            conf="low-medium", a=left["loc"], b=right["loc"], v=round(score, 3),
            wa=wc(left["text"]), wb=wc(right["text"]))
    mix_w, mixed = int(TH("mixed_layer_min_words", 120)), 0
    for para in body:
      if mixed >= 2:
        break
      nums = sum(1 for _l, s in para["sents"] if P["quantity"].search(s))
      cl = sum(1 for _l, s in para["sents"] if P["claim_marker"].search(s))
      if wc(para["text"]) >= mix_w and nums >= 2 and cl >= 1:
        mixed += 1
        self.rec("paragraph_relations", "medium", para["loc"], para["text"], "PAR2",
            "split", to=para["sents"][0][0], conf="medium", w=wc(para["text"]), nn=nums, nc=cl)
    self.N["pairs"] = max(0, len(body) - 1)

  # gate 5
  def g_repeats(self):
    min_w = int(TH("dup_paragraph_min_words", 45))
    width = int(TH("dup_shingle", 8))
    ceil = float(TH("dup_paragraph", 0.30))
    body = [p for p in self.body() if wc(p["text"]) >= min_w]
    gram = {}
    for para in body:
      seq = sorted(toks(para["text"]))
      gram[para["loc"]] = set(tuple(seq[i:i + width])
                  for i in range(max(0, len(seq) - width + 1)))
    pairs = []
    for i in range(len(body)):
      for j in range(i + 1, len(body)):
        a, b = body[i], body[j]
        score = jac(gram[a["loc"]], gram[b["loc"]])
        if score >= ceil:
          pairs.append((score, a, b))
    self.N["dup_compared"] = max(0, len(body) * (len(body) - 1) // 2)
    pairs.sort(key=lambda x: -x[0])
    for score, a, b in pairs[:5]:
      cross = a["ch"] != b["ch"]
      self.rec("duplication", "high" if (cross and score >= 0.5) else "medium",
          b["loc"], b["text"], "DUP1", "merge", to=a["loc"],
          conf="high" if score >= 0.5 else "medium", a=a["loc"], b=b["loc"],
          v=round(score, 3), shingle=width,
          kind=msg("notes", "DUP_CROSS") if cross else msg("notes", "DUP_INTRA"))
    min_chars, seen = int(TH("verbatim_sentence_min_chars", 55)), {}
    for para in self.pa:
      if para["role"] in SKIP or wc(para["text"]) < 25:
        continue
      for loc, s in para["sents"]:
        key = re.sub(r"\W+", "", s.lower())
        if len(key) >= min_chars:
          seen.setdefault(key, []).append((loc, s, para["loc"]))
    for key, hits in seen.items():
      if len(hits) >= 2 and len(self.F) < 40:
        self.rec("duplication", "medium", hits[-1][0], hits[-1][1], "DUP2", "delete",
            conf="high", a=hits[0][2], b=hits[-1][2], n=len(key), k=len(hits))
    self.N["dup_pairs"] = len(pairs)
    self.N["dup_top"] = round(pairs[0][0], 3) if pairs else 0.0

  # gate 6
  def g_bounds(self):
    ev = self.joined(("method", "result", "abstract"))
    targets = [p for p in self.pa if p["role"] in ("conclusion", "discussion", "abstract")]
    self.N["bound_sentences"] = sum(len(p["sents"]) for p in targets)
    if not targets:
      return
    corr, designed = bool(P["association"].search(ev)), bool(P["design"].search(ev))
    cap, raised = int(TH("bound_sentence_cap", 6)), 0
    for para in targets:
      for loc, s in para["sents"]:
        if raised >= cap:
          break
        if P["causal"].search(s) and not P["hedge"].search(s) and corr and not designed:
          raised += 1
          hit = sorted(set(x.lower() for x in P["association"].findall(ev)))[:3]
          self.rec("conclusion_boundary", "high", loc, s, "BND1", "narrow",
              conf="high", terms=", ".join(hit) or "association")
        elif P["absolute"].search(s) and not P["hedge"].search(s) and wc(s) >= 8:
          raised += 1
          hit = sorted(set(x.lower() for x in P["absolute"].findall(s)))[:3]
          self.rec("conclusion_boundary", "medium", loc, s, "BND2", "narrow",
              conf="medium", terms=", ".join(hit) or "absolute")

  def build_actions(self):
    keys = ("finding_id", "operation", "from_locator", "to_locator", "expected_effect",
        "risk", "priority", "executable")
    for spec in self.Q:
      row = {"action_id": "A%02d" % (len(self.A) + 1)}
      row.update(dict((k, spec[k]) for k in keys))
      self.A.append(row)

  def evidence_for(self, dim):
    n = self.N
    if dim == "research_question_alignment":
      return msg("checked", dim)
    key = {"section_structure": "chapters", "argument_chain": "body_paras",
       "paragraph_relations": "pairs", "duplication": "dup_compared",
       "conclusion_boundary": "bound_sentences"}[dim]
    if dim == "duplication":
      return msg("checked", dim, n=n.get(key, 0), v=n.get("dup_top", 0.0))
    return msg("checked", dim, n=n.get(key, 0))

  def coverage(self):
    table = {}
    for dim in DIMENSIONS:
      ids = [f["finding_id"] for f in self.F if f["dimension"] == dim]
      if not self.pa:
        status, checked = "not_assessable", msg("checked", "absent")
      elif dim in self.bad:
        status, checked = "degraded_by_error", msg("checked", "failed")
      elif ids:
        status, checked = "findings", "已逐条给出 locator 与原文逐字 quote，可直接回稿核对。"
      else:
        status, checked = "no_issue_with_evidence", self.evidence_for(dim)
      table[dim] = {"status": status, "finding_ids": ids, "checked": checked}
    return table

  def run(self):
    for dim, gate in (("section_structure", self.g_sections),
             ("research_question_alignment", self.g_question),
             ("argument_chain", self.g_arguments),
             ("paragraph_relations", self.g_paragraphs),
             ("duplication", self.g_repeats),
             ("conclusion_boundary", self.g_bounds)):
      try:
        gate()
      except Exception as exc:
        self.bad.add(dim)
        self.ER.append({"stage": "gate", "dimension": dim, "detail": str(exc)})
    try:
      self.build_actions()
    except Exception as exc:
      self.ER.append({"stage": "actions", "detail": str(exc)})
    return {"findings": self.F, "actions": self.A, "pending": self.PH, "errors": self.ER,
        "anchors": self.AN, "coverage": self.coverage(), "note": self.N, "dropped": self.dropped}


def fill(contract, payload):
  """Copy contract keys verbatim; unmatched keys stay null/[] and are reported."""
  alias = dict((re.sub(r"[^a-z0-9]", "", str(k).lower()), k) for k in payload)
  out, missing = {}, []
  for key, expect in (contract or {}).items():
    flat = re.sub(r"[^a-z0-9]", "", str(key).lower())
    hit = alias.get(flat)
    if hit is None:
      for alt in alias:
        if alt and (alt in flat or flat in alt):
          hit = alias[alt]
          break
    if hit is None:
      out[key] = [] if isinstance(expect, list) else None
      missing.append(key)
      continue
    val = payload[hit]
    if isinstance(expect, list) and not isinstance(val, list):
      val = [val]
    elif isinstance(expect, str) and not isinstance(val, str):
      val = val.get("primary") if isinstance(val, dict) else json.dumps(
        val, ensure_ascii=False)[:400]
    elif isinstance(expect, dict) and not isinstance(val, dict):
      val = {"value": val}
    out[key] = val
  return out, missing


def preserved_facts(a):
  """Verbatim sentences that carry numbers, citations or hedges."""
  cap, out = int(TH("fact_cap", 25)), []
  for para in a.body():
    for loc, s in para["sents"]:
      if len(out) >= cap:
        return out
      if not (P["quantity"].search(s) or P["cite"].search(s) or P["hedge"].search(s)):
        continue
      kind = "number" if P["quantity"].search(s) else (
        "citation" if P["cite"].search(s) else "scope")
      out.append({"fact_id": "PF%02d" % (len(out) + 1), "locator": loc, "quote": s,
            "kind": kind, "note": msg("notes", "PF")})
  return out


def inspect(work, keys=None):
  """Re-read the written artifacts and re-check them, ignoring the run's own claims."""
  work = Path(work)
  try:
    rv = json.loads((work / "structural_review.json").read_text(encoding="utf-8"))
    rs = json.loads((work / "result.json").read_text(encoding="utf-8"))
  except Exception as exc:
    return {"pass": False, "error": "artifacts unreadable: %s" % exc, "checks": [], "counts": {}}
  fs = rv.get("findings") or []
  acts = rv.get("actions") or []
  cov = rv.get("dimension_coverage") or {}
  ids = set(f.get("finding_id") for f in fs)
  spans = dict((x.get("finding_id"), x)
               for x in ((rv.get("grounding") or {}).get("anchors") or []))
  chk = [("quotes_present", all((f.get("quote") or "").strip() for f in fs)),
         ("six_dimensions", sorted(cov) == sorted(DIMENSIONS)),
         ("coverage_status_enum", all(v.get("status") in STATUSES for v in cov.values())),
         ("anchor_spans_consistent", all((spans.get(f.get("finding_id")) or {}).get("end", 0)
              - (spans.get(f.get("finding_id")) or {}).get("start", 0)
              == len(f.get("quote") or "") for f in fs)),
         ("finding_action_join", all(x.get("finding_id") in ids for x in acts)),
         ("actions_well_formed", all(x.get("operation") in OPS and x.get("from_locator")
                                     and x.get("expected_effect") for x in acts)),
         ("no_rewrite_file", not any((work / n).exists()
                                     for n in ("manuscript.md", "rewrite.md", "revised.md"))),
         ("case_id_kept", bool(rs.get("case_id"))),
         ("status_declared", bool(rs.get("status"))),
         ("contract_keys_present", all(k in rs for k in (keys or [])))]
  return {"pass": all(ok for _n, ok in chk), "checks": [{"check": n, "pass": ok} for n, ok in chk],
          "counts": {"findings": len(fs), "actions": len(acts),
                     "dimensions_with_findings": sum(1 for v in cov.values()
                                                     if v.get("finding_ids")),
                     "dimensions_degraded": sum(1 for v in cov.values()
                                                if v.get("status") == "degraded_by_error"),
                     "quote_hit_rate": (rv.get("grounding") or {}).get("hit_rate"),
                     "pending_human": len(rs.get("pending_human") or []),
                     "errors": len(rs.get("errors") or [])}}


def contract_keys(input_dir):
  """Contract key names from case.json, used by the checker only."""
  try:
    case = Path(input_dir) / "case.json"
    if not case.is_file():
      return []
    return list((json.loads(case.read_text(encoding="utf-8-sig", errors="replace")).get("output_contract") or {}))
  except Exception:
    return []


def main(argv=None):
  ap = argparse.ArgumentParser(
    description="Check structural-review artifacts: quote anchors, dimension coverage, "
                "action form, contract keys, absence of rewrite files.")
  ap.add_argument("--work", default=str(Path("/app/output") if Path("/app").is_dir()
                                       else Path.cwd() / "output"), help="artifact directory")
  ap.add_argument("--input", default=str(Path("/input") if Path("/input").is_dir()
                                        else Path.cwd() / "input"), help="case directory")
  args = ap.parse_args(argv)
  print(json.dumps(inspect(args.work, contract_keys(args.input)), ensure_ascii=False, indent=2))
  return 0


if __name__ == "__main__":
  try:
    main()
  except SystemExit:
    raise
  except Exception as exc:
    print(json.dumps({"pass": False, "error": str(exc)}, ensure_ascii=False))
  raise SystemExit(0)
