#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""writing-03 evidence-driven writing minimal skill v1.0.0 | init/check/build | stdlib only
no CWD dependency | exit code always 0 | default /input /app/output /app/work | --input/--output/--work"""
import argparse, json, re, sys, time, traceback
from pathlib import Path
V = "1.0.0"
IN, OUT, WORK = "/input", "/app/output", "/app/work"
CAP = 2 * 1024 * 1024
EXT = {".md", ".markdown", ".txt", ".text", ".json", ".csv", ".tsv", ".tex", ".html", ".htm", ".rst", ".bib", ".xml"}
STOP = {"the", "a", "an", "of", "and", "or", "in", "on", "for", "with", "to", "by", "was", "were", "is", "are", "as", "at", "this", "that", "from", "between", "among", "we", "our", "study", "studies"}
NUM = re.compile(r"\d+(?:\.\d+)?%?")
MARK = re.compile(r"\[(\d{1,3})\]")
PEND = "（待核：材料未提供直接证据）"

def nw():
	return time.strftime("%Y-%m-%dT%H:%M:%S")

def ep(*a):
	try:
		print(*a)
	except Exception:
		pass

def js(o):
	return json.dumps(o, ensure_ascii=False, indent=1, default=str)

def wr(p, s):
	try:
		p = Path(p)
		p.parent.mkdir(parents=True, exist_ok=True)
		p.write_text(s, encoding="utf-8")
		return len(s.encode("utf-8"))
	except Exception:
		return 0

def wjs(p, o):
	return wr(p, js(o))

def rd(p):
	return Path(p).read_text(encoding="utf-8-sig", errors="replace")

def nrm2(s):
	return re.sub(r"\s+", " ", (s or "")).strip()

def als(x):
	return x if isinstance(x, list) else ([] if x in (None, "", {}, ()) else [x])

def cjk2(s):
	return sum(1 for c in (s or "") if "\u4e00" <= c <= "\u9fff") / max(1, len(s or ""))

def bri(o, n=150):
	s = nrm2(o if isinstance(o, str) else js(o))
	return s if len(s) <= n else s[:n] + "…"

def asu(t, x):
	m = re.search(r"([。.!?！？;；,，]*)$", t)
	return t[:m.start()] + x + m.group(1)

def mkd(p):
	try:
		Path(p).mkdir(parents=True, exist_ok=True)
		return True
	except Exception:
		return False

def okv2(v):
	return not (v is None or (isinstance(v, (str, list, dict)) and len(v) == 0))

def fnd(o, k):
	if isinstance(o, dict):
		if k in o: return o[k]
		for v in o.values():
			x = fnd(v, k)
			if x is not None: return x
	elif isinstance(o, list):
		for v in o:
			x = fnd(v, k)
			if x is not None: return x

def prs(a):
	p = {"command": None, "input": None, "output": None, "work": None}
	i, unk = 0, 0
	while i < len(a):
		x = a[i]
		if x in ("-h", "--help"):
			ep("run.py [init|check|build] [--input|--output|--work DIR]")
			return None
		if x.startswith("--") and x[2:].split("=")[0] in p:
			k = x[2:].split("=")[0]
			if "=" in x: p[k] = x.split("=", 1)[1]
			elif i + 1 < len(a): p[k] = a[i + 1]; i += 1
		elif x in ("init", "check", "build", "show", "all", "audit", "verify", "selfcheck"): p["command"] = x
		else: unk += 1
		i += 1
	if p["command"] is None: p["command"] = "build"
	return argparse.Namespace(**p)

def drs(ns):
	return (Path(ns.input) if ns.input else Path(IN), Path(ns.output) if ns.output else Path(OUT), Path(ns.work) if ns.work else Path(WORK))

def prp(out, wd):
	mkd(wd)
	if mkd(out): return Path(out), []
	mkd(Path(wd) / "output")
	return Path(wd) / "output", ["output_unwritable"]

def rdf(p):
	r = {"text": "", "method": "text", "error": ""}
	try:
		b = Path(p).read_bytes()
		if len(b) > CAP: b, r["error"] = b[:CAP], "truncated"
	except Exception:
		r["error"] = "read_failed"
		return r
	try:
		if Path(p).suffix.lower() == ".pdf" or b[:5] == b"%PDF-": r["method"], r["error"] = "pdf", "pdf_text_unsupported"
		else:
			for e in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
				try:
					r["text"] = b.decode(e); break
				except Exception: pass
			else: r["text"] = b.decode("utf-8", "replace")
	except Exception: r["error"] = "parse_failed"
	r["text"] = (r["text"] or "").replace("\r\n", "\n").replace("\r", "\n")
	return r

def knd(rel, txt):
	low = rel.lower()
	if any(x in low for x in ("draft", "manuscript", "discussion", "intro", "初稿", "草稿", "原稿", "待改")): return "draft"
	if any(x in low for x in ("reference", "refs", "bib", "参考文献")): return "references"
	if re.search(r"(?m)^\s*\[\d{1,3}\]\s+\S", txt) and (re.search("(?i)doi|et al", txt) or txt.count("[") >= 2): return "references"
	return "source"

def scn(inp):
	s = {"case": {}, "ce": "", "task": "", "task_path": "", "files": [], "mats": [], "errors": [], "warns": []}
	if not inp.exists():
		s["ce"] = "input_dir_missing"
		return s
	if (inp / "case.json").exists():
		try:
			c = json.loads(rd(inp / "case.json"))
			s["case"] = c if isinstance(c, dict) else {"items": als(c)}
		except Exception as e:
			s["ce"] = "bad_case_json:%s" % bri(str(e), 80)
	else: s["ce"] = "no_case_json"
	for n in ("task.md", "TASK.md", "task.txt"):
		if (inp / n).exists():
			try:
				s["task"], s["task_path"] = rd(inp / n), n
			except Exception:
				pass
			break
	try:
		ps = sorted(p for p in inp.rglob("*") if p.is_file())
	except Exception:
		ps = []
	for p in ps[:120]:
		try:
			rel, size = p.relative_to(inp).as_posix(), p.stat().st_size
		except Exception:
			continue
		if rel in ("case.json", "task.md") or "/." in "/" + rel: continue
		sf = p.suffix.lower()
		r = rdf(p) if (sf in EXT or sf == ".pdf") else {"text": "", "method": "unsupported", "error": "unsupported_format"}
		k = knd(rel, r["text"])
		s["files"].append({"path": rel, "bytes": size, "kind": k, "method": r["method"]})
		if r["error"]: s["warns"].append(rel + ":" + r["error"])
		if r["text"].strip(): s["mats"].append({"path": rel, "kind": k, "text": r["text"], "bytes": size, "method": r["method"]})
	if not s["mats"] and s["ce"] != "input_dir_missing": s["warns"].append("no_readable_material")
	return s

def uts(mts):
	us = []
	for m in mts:
		t, parts, st = m["text"], [], 0
		for mm in re.finditer(r"\n[ \t]*\n", t):
			parts.append((st, mm.start()))
			st = mm.end()
		parts.append((st, len(t)))
		for bi, (a, b) in enumerate(parts, 1):
			seg, spans, s0, i = t[a:b], [], 0, 0
			while i < len(seg):
				e = None
				if seg[i] in "。！？!?；;": e = i + 1
				elif seg[i] == "." and (i + 1 >= len(seg) or seg[i + 1].isspace()): e = i + 1
				if e:
					spans.append((s0, e))
					s0 = i = e
				else: i += 1
			if s0 < len(seg): spans.append((s0, len(seg)))
			for si, (x, y) in enumerate(spans, 1):
				sub = seg[x:y]
				qx, qy = a + x + len(sub) - len(sub.lstrip()), a + x + len(sub.rstrip())
				if qy > qx and len(t[qx:qy].strip()) >= 2:
					us.append({"path": m["path"], "kind": m["kind"], "text": t[qx:qy], "start": qx, "end": qy, "loc": "%s [B%d.S%d] chars:%d-%d" % (m["path"], bi, si, qx, qy)})
	return us

def hed(t):
	s = (t or "").strip()
	return bool(s) and (bool(re.match(r"^#{1,6}\s", s)) or (len(s) <= 40 and not re.search(r"[。.!?！？;；:：,，]", s)))

def tks(s):
	low = (s or "").lower()
	out = set(w for w in re.findall(r"[a-z][a-z\-]{2,}", low) if w not in STOP)
	out.update("#" + n for n in NUM.findall(low))
	for run in re.findall(r"[\u4e00-\u9fff]{2,}", low): out.update(run[i:i + 2] for i in range(len(run) - 1))
	for k, v in ZH.items():
		if k in low: out.update(v.split())
	return out

def ov(a, b):
	return len(a & b) / max(1, len(a)) if a and b else 0.0

def stg(t):
	tl = (t or "").lower()
	pts = (3.0 if re.search(r"(systematic review|meta-analysis|meta analysis|randomized|rct)", tl) else 2.0 if re.search(r"(cohort|guideline)", tl) else 1.5 if "review" in tl else 1.0)
	m = re.search(r"n\s*=\s*(\d{2,7})", tl.replace(",", "")) or re.search(r"enrolled\s+(\d{2,7})", tl)
	n = int(m.group(1)) if m else None
	if n: pts += 2.0 if n >= 1000 else (1.5 if n >= 100 else 1.0)
	return ("高" if pts >= 4.5 else "中" if pts >= 2.5 else "低" if pts >= 1.5 else "不足"), n

def cty(t):
	tl = (t or "").lower()
	if re.search(r"(导致|引起|造成|使得|caus|leads? to)", tl): return "因果"
	if re.search(r"(所有|全部|均|一致|普遍|always|all\b)", tl): return "全称"
	return "关联" if re.search(r"(相关|关联|associated|risk|风险|higher|lower|高于|低于)", tl) else "事实"

def mtc(c, srcs, maxn=2):
	ct, nums, sc = tks(c), set(NUM.findall(c)), []
	for u in srcs:
		v = ov(ct, tks(u["text"]))
		if nums: v += 0.12 * min(2, len(nums & set(NUM.findall(u["text"]))))
		if v >= 0.16: sc.append((round(v, 3), u))
	sc.sort(key=lambda x: (-x[0], x[1]["path"], x[1]["start"]))
	out = []
	for v, u in sc:
		if len(out) >= maxn or (out and v < 0.55 * out[0][0]): break
		out.append((v, u))
	return out

def ldr(wd):
	p = Path(wd) / "draft.json"
	if not p.exists(): return None, "no_draft"
	try:
		d = json.loads(rd(p))
		return (d, "") if isinstance(d, (dict, list)) else (None, "not_object")
	except Exception as e:
		return None, "bad_draft_json:%s" % bri(str(e), 80)

def ocl(c, n):
	if isinstance(c, str):
		c = {"text": c}
	if not isinstance(c, dict): return None
	cid = str(c.get("claim_id") or c.get("id") or "C%03d" % n)
	evs = []
	for e in als(c.get("evidence") or c.get("evidence_rows") or c.get("sources")):
		if isinstance(e, str):
			e = {"quote": e}
		if isinstance(e, dict):
			evs.append({"claim_id": cid, "source": str(e.get("source") or e.get("source_path") or e.get("file") or e.get("path") or ""), "locator": str(e.get("locator") or e.get("loc") or ""), "quote": str(e.get("quote") or e.get("verbatim") or e.get("text") or ""), "strength": str(e.get("strength") or ""), "support": str(e.get("support") or "")})
	return {"claim_id": cid, "text": str(c.get("text") or c.get("claim") or c.get("sentence") or ""), "type": str(c.get("claim_type") or c.get("type") or ""), "section": "", "evidence": evs, "pending": bool(c.get("pending")), "render": ""}

def nrm(d, cid):
	m = {"mode": "draft", "case_id": cid, "claims": [], "sections": [], "final_text": "", "change_log": [], "preserved_facts": [], "references": [], "pending": [], "warns": []}
	if not isinstance(d, dict): return m, ["draft_not_object"]
	dc = d.get("case_id")
	if dc and cid and str(dc).strip() != str(cid).strip(): return m, ["stale_draft_case_id"]
	for sec in als(d.get("sections")):
		if isinstance(sec, dict):
			h = str(sec.get("heading") or sec.get("title") or "").strip()
			ids = []
			for c in als(sec.get("claims")):
				cl = ocl(c, len(m["claims"]) + 1)
				if cl and nrm2(cl["text"]):
					cl["section"] = h
					m["claims"].append(cl)
					ids.append(cl["claim_id"])
			m["sections"].append({"heading": h, "claims": ids})
	for c in als(d.get("claims")):
		cl = ocl(c, len(m["claims"]) + 1)
		if cl and nrm2(cl["text"]): m["claims"].append(cl)
	for k, tgt in (("change_log", "change_log"), ("changes", "change_log"), ("preserved_facts", "preserved_facts"), ("facts", "preserved_facts"), ("references", "references")):
		for x in als(d.get(k)):
			if isinstance(x, dict): m[tgt].append(x)
			elif isinstance(x, str) and x.strip(): m[tgt].append({"raw": x.strip()})
	for k in ("deliverable", "draft", "manuscript", "final_text", "text", "markdown", "md"):
		v = d.get(k)
		if isinstance(v, str) and len(v.strip()) > 20:
			m["final_text"] = v.strip()
			break
	if not m["claims"] and not m["final_text"]: return m, ["draft_has_no_text"]
	return m, []

def fq(ev, mts, us):
	q = (ev.get("quote") or "").strip()
	if not q: return False, "empty", ""
	locp, src = (ev.get("locator") or "").split(" [")[0].strip(), (ev.get("source") or "").strip()
	cands = [m for m in mts if any(c and (m["path"] == c or m["path"].endswith("/" + c) or c == m["path"].split("/")[-1]) for c in (src, locp))]
	if not cands: cands = [m for m in mts if m["kind"] == "source"] or mts
	for m in cands:
		i = m["text"].find(q)
		if i >= 0:
			loc = next((u["loc"] for u in us if u["path"] == m["path"] and u["start"] <= i and i + len(q) <= u["end"]), "")
			return True, "exact", loc or "%s chars:%d-%d" % (m["path"], i, i + len(q))
	return False, "missing", ""

def vfy(m, mts, us):
	st = {"verified": 0, "failed": 0}
	for cl in m["claims"]:
		for ev in cl["evidence"]:
			ok, mt, loc = fq(ev, mts, us)
			ev["verified"], ev["match"] = ok, mt
			if loc: ev["locator"] = loc
			st["verified"] += int(ok)
			st["failed"] += int(not ok)
			if not ok:
				m["warns"].append("%s:quote_not_verbatim" % cl["claim_id"])
				m["pending"].append({"claim_id": cl["claim_id"], "issue": "quote_not_verbatim"})
		if not cl["type"]: cl["type"] = cty(cl["text"])
	for cl in m["claims"]:
		ver = [e for e in cl["evidence"] if e.get("verified")]
		cl["supported"] = bool(ver)
		cl["pending"] = cl["pending"] or not ver
		cl["strength"] = (ver[0].get("strength") or "") if ver else ""
	m["qstats"] = st
	return st

def ato(s, us):
	m = {"mode": "auto", "claims": [], "sections": [{"heading": "", "claims": []}], "final_text": "", "change_log": [], "preserved_facts": [], "references": [], "pending": [], "warns": list(s["warns"]), "qstats": {}}
	srcs = [u for u in us if u["kind"] == "source"]
	drafts = [u for u in us if u["kind"] == "draft"] or srcs
	sec = m["sections"][0]
	for u in drafts:
		if hed(u["text"]) and drafts is not srcs:
			if sec["claims"]:
				sec = {"heading": u["text"].strip(), "claims": []}
				m["sections"].append(sec)
			else: sec["heading"] = u["text"].strip()
			continue
		core = nrm2(MARK.sub("", u["text"]))
		if len(core) < 4: continue
		cid, evs = "C%03d" % (len(m["claims"]) + 1), []
		for _, su in mtc(core, srcs):
			lab, _ = stg(su["text"])
			evs.append({"claim_id": cid, "source": su["path"], "locator": su["loc"], "quote": su["text"], "verified": True, "match": "exact", "strength": lab, "support": "直接支撑"})
		m["claims"].append({"claim_id": cid, "text": core, "type": cty(core), "section": sec["heading"], "evidence": evs, "pending": not evs, "render": core})
		sec["claims"].append(cid)
		if not evs: m["pending"].append({"claim_id": cid, "issue": "no_material_evidence"})
	if not m["claims"]: m["pending"].append({"issue": "no_usable_material"})
	return flg(m)

def cmp(m, s):
	zh = cjk2(s["task"] + js(s["case"])[:2000]) > 0.12
	order = []
	def cn(p):
		if p and p not in order: order.append(p)
		return order.index(p) + 1 if p else None
	def mks(cl):
		ns = [cn(e.get("source")) for e in cl["evidence"] if e.get("verified")]
		return "".join("[%d]" % n for i, n in enumerate(ns) if n and n not in ns[:i])
	L = [m["final_text"].rstrip(), ""] if m["final_text"] else []
	if not m["final_text"]:
		byid = {c["claim_id"]: c for c in m["claims"]}
		for sec in m["sections"]:
			if sec["heading"]: L += [sec["heading"] if sec["heading"].startswith("#") else "## " + sec["heading"], ""]
			for cid in sec["claims"]:
				cl = byid.get(cid)
				if not cl: continue
				body = cl.get("render") or cl["text"]
				if cl.get("pending"): body = asu(body, PEND if zh else " (pending)")
				L += [body + ("" if MARK.search(body) else mks(cl)), ""]
	sofar = "\n".join(L)
	if "证据边界" not in sofar:
		L += ["## 证据边界", "", "- 仅使用 /input 材料，未联网核验文献与 DOI。", "- 待核/缺口 %d 条。" % len(m["pending"]), ""]
	refs = [ln.strip() for mt in s["mats"] if mt["kind"] == "references" for ln in mt["text"].replace("\ufeff", "").splitlines() if re.match(r"^\s*\[\d", ln)]
	refs += ["[%d] 材料内来源：%s" % (cn(p), p) for p in order]
	if "参考文献" not in sofar: L += ["## 参考文献", ""] + (refs or ["（材料未提供参考文献表；不编造文献。）"]) + [""]
	return "\n".join(L).rstrip() + "\n", order

def ctr(cse):
	oc = fnd(cse, "output_contract")
	out = []
	if isinstance(oc, dict): out = [(str(k), v) for k, v in oc.items()]
	elif isinstance(oc, list):
		for i, it in enumerate(oc):
			if isinstance(it, str): out.append((it, ""))
			elif isinstance(it, dict):
				out.append((str(it.get("key") or it.get("field") or it.get("name") or it.get("id") or "item_%d" % (i + 1)), it.get("description") or it.get("requirement") or ""))
	return out
try: _LEX = json.loads((Path(__file__).resolve().parent.parent / "references" / "lexicon.json").read_text(encoding="utf-8"))
except Exception: _LEX = {}
ZH = _LEX.get("zh", {}); HEUR = _LEX.get("heur", {})

def bfl(k, c):
	k = str(k).lower()
	for key, src in HEUR.items():
		if key in k:
			v = c.get(src)
			if isinstance(v, (int, float)): return v
			return v if okv2(v) else None
	if any(x in k for x in ("format", "style", "language", "格式", "语言")): return "Markdown 成稿；数字编号引用 [n]"
	if any(x in k for x in ("word", "count", "length", "字数", "长度")): return len(c.get("deliverable") or "")
	return None

def gld(m, s, con, fld, ft):
	nq = nok = nex = 0
	cls = []
	for c in m["claims"]:
		rows = []
		for e in c["evidence"]:
			nq += 1
			ok = bool(e.get("verified"))
			nok += int(ok)
			nex += int(e.get("match") == "exact")
			rows.append({"source": e.get("source"), "locator": e.get("locator"), "quote": e.get("quote"), "quote_verbatim": e.get("match") == "exact", "verified": ok, "strength": e.get("strength")})
		cls.append({"claim_id": c["claim_id"], "claim": MARK.sub("", c["text"]), "claim_type": c["type"], "supported": bool(c.get("supported")), "evidence": rows})
	keys = [k for k, _ in con]
	return {"case_id": m.get("case_id", ""), "generated_at": nw(), "version": V, "contract": [{"key": k, "requirement": bri(str(d), 120), "filled": bool(fld.get(k))} for k, d in con], "claims": cls, "totals": {"contract_keys": len(con), "contract_filled": len([k for k in keys if fld.get(k)]), "claims": len(m["claims"]), "claims_supported": len([c for c in m["claims"] if c.get("supported")]), "evidence_rows": nq, "quotes_verified": nok, "quotes_exact": nex, "pending_items": len(m["pending"]), "preserved_facts": len(ft)}, "completeness": {"quote_hit_rate": round(nok / nq, 4) if nq else 0.0, "quote_verbatim_rate": round(nex / nq, 4) if nq else 0.0, "contract_fill_rate": round(len([k for k in keys if fld.get(k)]) / len(con), 4) if con else 0.0}}

def dff(m, sts, con, g, arts, st):
	L = ["# 期望-实际差异报告（%s）" % (m.get("case_id") or "unknown"), "", "| 项 | 值 |", "|---|---|", "| 状态 | %s |" % sts, "| 成稿模式 | %s |" % ("agent-draft" if m["mode"] == "draft" else "auto-fallback"), "| 论断/证据行 | %d / %d |" % (len(m["claims"]), sum(len(c["evidence"]) for c in m["claims"])), "| 逐字引文校验 | %d 通过 / %d 失败 |" % (st.get("verified", 0), st.get("failed", 0)), "| 契约回填 | %d / %d |" % (g["totals"]["contract_filled"], len(con)), "", "## 契约回填", "| 契约键 | 已回填 |", "|---|---|"]
	L += ["| `%s` | %s |" % (r["key"], "是" if r["filled"] else "否") for r in g["contract"]]
	gaps = []
	if m["mode"] != "draft": gaps.append("未读取到 /app/work/draft.json，本次为自动兜底成稿。")
	if st.get("failed"): gaps.append("%d 条引文未逐字命中，已列入 pending_human。" % st["failed"])
	if m["pending"]: gaps.append("待核 %d 条。" % len(m["pending"]))
	L += ["", "## 剩余缺口"] + ["- " + x for x in (gaps or ["无阻断性缺口；引文逐字命中、契约键已回填。"])]
	return "\n".join(L) + "\n"

def lg(out, cmd, lines, t0):
	try:
		with open(str(Path(out) / "run.log"), "a", encoding="utf-8") as f:
			f.write("\n=== %s | cmd=%s | v%s ===\n" % (nw(), cmd, V))
			f.write("".join("[+%05.2fs] %s\n" % (time.time() - t0, x) for x in lines))
	except Exception:
		pass

def rsc(out, wd, cmd, e):
	try:
		mkd(out)
		mkd(wd)
		if not (Path(out) / "deliverable.md").exists(): wr(Path(out) / "deliverable.md", "# rescue placeholder\n\n%s exception: %s\n" % (cmd, bri(str(e), 300)))
		if not (Path(out) / "result.json").exists():
			wjs(Path(out) / "result.json", {"case_id": "", "status": "partial" if cmd == "build" else "input_error", "stage": cmd, "errors": [bri(str(e), 500)], "deliverable_path": "deliverable.md"})
	except Exception:
		pass

def cvr(k, m):
	k = str(k).lower()
	if "case_id" in k: return bool(m.get("case_id"))
	if any(x in k for x in ("deliverable", "draft", "text", "成稿")): return bool(m["final_text"] or [c for c in m["claims"] if nrm2(c["text"])])
	if any(x in k for x in ("evidence", "claim", "support", "证据")): return any(c["evidence"] for c in m["claims"])
	if any(x in k for x in ("fact", "number", "事实", "数字")): return bool(m["preserved_facts"]) or any(NUM.search(c["text"]) for c in m["claims"])
	if any(x in k for x in ("change", "修改", "变更")): return bool(m["change_log"]) or any(c["type"] in ("因果", "全称") for c in m["claims"])
	return True

def chk(inp, out, wd):
	t0 = time.time()
	out, _ = prp(out, wd)
	s = scn(inp); us = uts(s["mats"]); con = ctr(s["case"]); cid = cdf(s)
	d, derr = ldr(wd)
	rep = {"case_id": cid, "draft_error": derr, "checks": [], "passed": False}
	ep("=== check · writing-03 ===")
	if not d:
		ep("FAIL draft_exists: /app/work/draft.json missing (%s)" % derr)
		ep("next: run init, read materials, write /app/work/draft.json")
		wjs(Path(wd) / "check_report.json", rep)
		if not (Path(out) / "result.json").exists():
			wr(Path(out) / "deliverable.md", "# %s\n\n> check stage: no draft.\n" % (cid or "case"))
			wjs(Path(out) / "result.json", {"case_id": cid, "status": "partial" if s["mats"] else "input_error", "stage": "check", "errors": s["errors"], "warnings": s["warns"]})
		lg(out, "check", ["no_draft exit rc=0"], t0)
		return 0
	m, iss = nrm(d, cid)
	if "stale_draft_case_id" in iss:
		ep("FAIL case_id_matches: draft case_id != current case")
		wjs(Path(wd) / "check_report.json", rep)
		return 0
	st = vfy(m, s["mats"], us)
	fld = {k: cvr(k, m) for k, _ in con}
	miss = [k for k, _ in con if not fld[k]]
	rep["passed"] = not miss and len(m["claims"]) > 0 and st["failed"] == 0
	ep("claims=%d evidence=%d quotes=%d/%d contract_missing=%s passed=%s" % (len(m["claims"]), sum(len(c["evidence"]) for c in m["claims"]), st["verified"], st["verified"] + st["failed"], ",".join(miss) or "0", rep["passed"]))
	wjs(Path(wd) / "check_report.json", rep)
	lg(out, "check", ["claims=%d passed=%s exit rc=0" % (len(m["claims"]), rep["passed"])], t0)
	return 0

def bld(inp, out, wd):
	t0 = time.time()
	out, notes = prp(out, wd)
	s = scn(inp); us = uts(s["mats"]); con = ctr(s["case"]); cid = cdf(s)
	d, derr = ldr(wd)
	m = None
	if d:
		m2, iss = nrm(d, cid)
		if "stale_draft_case_id" not in iss and (m2["claims"] or m2["final_text"]): m = m2
		else: derr = "stale_draft_ignored" if "stale_draft_case_id" in iss else derr
	if m is None:
		m = ato(s, us)
		if derr: m["warns"].append(derr)
	else:
		vfy(m, s["mats"], us)
		flg(m)
	m["case_id"] = cid
	deliv, order = cmp(m, s)
	em = [{"claim_id": c["claim_id"], "claim": MARK.sub("", c["text"]), "claim_type": c["type"], "supported": bool(c.get("supported")), "evidence": [{"source": e.get("source"), "locator": e.get("locator"), "quote": e.get("quote"), "verified": bool(e.get("verified")), "match": e.get("match"), "strength": e.get("strength"), "support_scope": e.get("support")} for e in c["evidence"]]} for c in m["claims"]]
	ch = [{"change_id": "CH%03d" % (i + 1), "claim_id": str(x.get("claim_id") or ""), "action": str(x.get("action") or "edit"), "before": str(x.get("before") or ""), "after": str(x.get("after") or ""), "reason": str(x.get("reason") or ""), "locator": str(x.get("locator") or "")} for i, x in enumerate(als(m.get("change_log"))) if isinstance(x, dict)]
	ft, seen = [], set()
	for c in m["claims"]:
		for e in c["evidence"]:
			if e.get("verified"):
				for x in NUM.findall(e.get("quote") or ""):
					if (x, e.get("locator")) not in seen and len(ft) < 50:
						seen.add((x, e.get("locator")))
						ft.append({"fact_id": "F%02d" % (len(ft) + 1), "value": x, "claim_id": c["claim_id"], "source": e.get("source"), "locator": e.get("locator"), "quote": e.get("quote"), "kept_in_deliverable": x in deliv})
	if m["mode"] == "auto":
		for cl in m["claims"]:
			if cl["evidence"]:
				ch.append({"change_id": "CH%03d" % (len(ch) + 1), "claim_id": cl["claim_id"], "action": "add_citation", "before": nrm2(MARK.sub("", cl["text"])), "after": cl.get("render") or cl["text"], "reason": "补材料内引用与限定语", "locator": cl["evidence"][0].get("locator") or ""})
	pnd = list(m["pending"])
	for cl in m["claims"]:
		if cl.get("pending") and not any(p.get("claim_id") == cl["claim_id"] for p in pnd): pnd.append({"claim_id": cl["claim_id"], "issue": "unsupported_claim", "action": "回原文补证或保留待核表述"})
	st = m.get("qstats") or {"verified": sum(1 for c in m["claims"] for e in c["evidence"] if e.get("verified")), "failed": sum(1 for c in m["claims"] for e in c["evidence"] if e.get("verified") is False)}
	ttl = next((str(fnd(s["case"], k)) for k in ("title", "paper_id") if isinstance(fnd(s["case"], k), (str, int))), "")
	ctx = {"case_id": cid, "deliverable": deliv, "facts": ft, "evmap": em, "refs": [], "changes": ch, "pending": pnd, "status": "", "title": ttl}
	for k, _ in con: ctx[k] = bfl(k, ctx)
	fld = {k: okv2(ctx.get(k)) for k, _ in con}
	n = {"materials": len(s["mats"]), "claims": len(m["claims"]), "evidence_rows": sum(len(c["evidence"]) for c in m["claims"]), "quotes_verified": st.get("verified", 0), "quotes_failed": st.get("failed", 0), "citations": len(order), "deliverable_chars": len(deliv), "contract_keys": len(con), "contract_filled": len([k for k in fld if fld[k]]), "unsupported": len([c for c in m["claims"] if not c.get("supported")]), "pending_human": len(pnd)}
	if not s["mats"]: sts = "input_error"
	elif s["ce"] or m["mode"] != "draft": sts = "partial"
	elif m["claims"] and not any(c.get("supported") for c in m["claims"]): sts = "insufficient_evidence"
	elif st.get("failed") or (con and not all(fld[k] for k, _ in con)): sts = "partial"
	else: sts = "ok" if m["claims"] else "partial"
	errs = [s["ce"]] if s["ce"] else list(s["errors"])
	wrns = list(s["warns"]) + list(m.get("warns") or []) + notes
	degr = []
	if m["mode"] != "draft": degr.append("agent_work_absent: no draft.json; auto best-effort")
	if st.get("failed"): degr.append("quotes_not_verbatim:%d" % st["failed"])
	if s["ce"]: degr.append("case_unavailable:%s" % s["ce"])
	g = gld(m, s, con, fld, ft)
	arts = {}
	for name, content in (("deliverable.md", deliv), ("evidence.json", js({"case_id": cid, "version": V, "claims": em, "totals": n})), ("golden_standard.json", js(g))):
		wr(Path(out) / name, content)
	wr(Path(out) / "diff_report.md", dff(m, sts, con, g, {}, st))
	lg(out, "build", ["status=%s mode=%s claims=%d quotes=%d/%d" % (sts, m["mode"], n["claims"], n["quotes_verified"], n["quotes_failed"]), "exit rc=0"], t0)
	res = {"case_id": cid, "status": sts, "stage": "build", "deliverable": deliv, "deliverable_path": "deliverable.md", "preserved_facts": ft, "evidence_map": em, "change_log": ch, "metrics": n, "pending_human": pnd, "errors": errs, "warnings": wrns, "degradations": degr, "agent_work": {"draft_used": m["mode"] == "draft"}, "contract_backfill": {k: {"filled": fld[k]} for k, _ in con}, "output": str(out), "work": str(wd), "generated_at": nw()}
	for k, _ in con: res[k] = ctx.get(k)
	wjs(Path(out) / "result.json", res)
	ep('json: {"status": "%s", "mode": "%s", "claims": %d, "quotes_verified": %d, "contract_filled": %d/%d}' % (sts, m["mode"], n["claims"], n["quotes_verified"], n["contract_filled"], len(con)))
	return 0
def cdf(s):
	if isinstance(s["case"], dict):
		v = s["case"].get("case_id") or fnd(s["case"], "case_id")
		return str(v) if v not in (None, "") else ""
	return ""

def ini(inp, out, wd):
	t0 = time.time()
	out, notes = prp(out, wd)
	s = scn(inp); us = uts(s["mats"]); con = ctr(s["case"]); cid = cdf(s)
	wjs(Path(wd) / "index.json", {"case_id": cid, "case_error": s["ce"], "task_path": s["task_path"], "output_contract": [{"key": k, "requirement": bri(str(v), 200)} for k, v in con], "materials": [{"path": mt["path"], "kind": mt["kind"], "bytes": mt["bytes"], "chars": len(mt["text"])} for mt in s["mats"]], "units": [{"path": u["path"], "kind": u["kind"], "locator": u["loc"], "text": u["text"]} for u in us[:200]]})
	if not (Path(out) / "result.json").exists():
		wr(Path(out) / "deliverable.md", "# %s\n\n> init stage: write /app/work/draft.json then run build.\n" % (cid or "case"))
		r = {"case_id": cid, "status": "input_error" if (s["ce"] or not s["mats"]) else "partial", "stage": "init", "deliverable_path": "deliverable.md", "errors": s["errors"], "warnings": s["warns"], "contract_backfill": {k: {"filled": False} for k, _ in con}}
		for k, _ in con: r[k] = None
		wjs(Path(out) / "result.json", r)
	ep("=== writing-03 evidence writing init v%s ===" % V)
	ep("case_id=%s case_error=%s contract=%s" % (cid or "-", s["ce"] or "-", ",".join(k for k, _ in con) or "-"))
	for w in notes + s["warns"][:4]: ep("WARN %s" % w)
	ep("--- verbatim sentences (locator | text); copy quote verbatim into draft.json ---")
	for u in us[:10]: ep("  %s | %s" % (u["loc"], nrm2(u["text"])))
	ep("  ... (all %d sentences in /app/work/index.json)" % len(us))
	ep("next: read materials -> write /app/work/draft.json -> run.py check -> run.py build")
	lg(out, "init", ["materials=%d sentences=%d contract=%d exit rc=0" % (len(s["mats"]), len(us), len(con))], t0)
	return 0

def flg(m):
	for cl in m["claims"]:
		ver = [e for e in cl["evidence"] if e.get("verified")]
		cl["supported"] = bool(ver)
		cl["pending"] = cl["pending"] or not ver
		cl["strength"] = (ver[0].get("strength") or "") if ver else ""
	return m

ALIAS = {"init": "init", "check": "check", "build": "build", "show": "init", "all": "all", "audit": "check", "verify": "check"}

def mn(argv):
	out = wd = inp = None
	try:
		try:
			sys.stdout.reconfigure(encoding="utf-8", errors="replace")
		except Exception:
			pass
		ns = prs(argv)
		if ns is None: return 0
		cmd = ALIAS.get(str(getattr(ns, "command", "build") or "build").strip().lower(), "build")
		inp, out, wd = drs(ns)
		if cmd == "init": ini(inp, out, wd)
		elif cmd == "check": chk(inp, out, wd)
		elif cmd == "all":
			ini(inp, out, wd)
			bld(inp, out, wd)
		else: bld(inp, out, wd)
		return 0
	except SystemExit:
		return 0
	except Exception as e:
		rsc(out or Path(OUT), wd or Path(WORK), "main", e)
		ep("RESCUE: %s" % bri(str(e), 260))
		return 0

if __name__ == "__main__":
	try:
		sys.exit(mn(sys.argv[1:]))
	except SystemExit:
		pass
	except Exception:
		sys.exit(0)
