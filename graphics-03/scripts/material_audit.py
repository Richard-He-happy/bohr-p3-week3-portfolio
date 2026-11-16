"""输入侧与产物侧的核对：切材料、比引文、验工单、读回图面、拼 content_map。
这里没有生物学判断，只有「原文里能不能逐字找到」与「图面和声明是不是一件事」。"""
import json
import re
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

SVG_NS = "{http://www.w3.org/2000/svg}"
MIN_ENTITIES, MIN_RELATIONS = 15, 12

TEXT_EXT = {".txt", ".md", ".markdown", ".json", ".csv", ".tsv", ".yaml", ".yml", ".xml",
            ".html", ".svg"}
BIN_EXT = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".pptx": "pptx", ".png": "image",
           ".jpg": "image", ".jpeg": "image", ".tif": "image", ".tiff": "image", ".zip": "zip"}


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_json(p):
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return json.loads(Path(p).read_text(encoding=enc))
        except Exception:
            continue
    return None


def write_json(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def squeeze(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def letters_only(s):
    """宽松比对键：只留字母/数字/汉字，吸收 PDF 抽字噪声。"""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(s or "").lower())


def norm_key(s):
    return re.sub(r"[^a-z0-9]", "_", str(s).lower()).strip("_")


def file_kind(p):
    if p.suffix.lower() in BIN_EXT:
        return BIN_EXT[p.suffix.lower()]
    if p.suffix.lower() in TEXT_EXT:
        return "text"
    try:
        head = p.open("rb").read(5)
    except Exception:
        return "unknown"
    return ("pdf" if head.startswith(b"%PDF") else "image" if head.startswith(b"\x89PNG")
            else "zip-office" if head.startswith(b"PK") else "unknown")


def pdf_streams(path):
    """PDF -> (逐段文字, 页数)；抽不出文本就返回空，由上层记缺口。"""
    data = Path(path).read_bytes()
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = m.group(1)
        try:
            raw = zlib.decompress(raw)
        except Exception:
            pass
        chunk = []
        for sm in re.finditer(rb"\((?:\\\\.|[^\\\\()])*\)|<[0-9A-Fa-f\s]{4,}>", raw):
            g = sm.group(0)
            try:
                if g.startswith(b"<"):
                    b = bytes.fromhex(re.sub(rb"\s", b"", g[1:-1]).decode())
                    chunk.append(b.decode("utf-16-be", "ignore")
                                 if b.count(b"\x00") > len(b) // 3
                                 else b.decode("latin-1", "ignore"))
                else:
                    chunk.append(re.sub(rb"\\\\(.)", rb"\1", g[1:-1]).decode("latin-1", "ignore"))
            except Exception:
                pass
        if "".join(chunk).strip():
            out.append(" ".join(chunk))
    return out, len(re.findall(rb"/Type\s*/Page[^s]", data))


def blocks_of(path):
    """材料 -> ([(locator, 文本)], 备注)；读不出只当缺口。"""
    kind = file_kind(path)
    try:
        if kind == "pdf":
            parts, pages = pdf_streams(path)
            if not "".join(parts).strip():
                return [], "PDF 文本不可抽（扫描件/编码流），按图片处理"
            return ([(("%s#stream%d" % (path.name, i + 1)), squeeze(t)) for i, t in enumerate(parts)],
                    "pdf: %d 页, %d 段文本" % (pages, len(parts)))
        if kind == "image":
            return [], "位图：读不到像素，只能人工核验"
        if kind in ("docx", "xlsx", "pptx", "zip-office"):
            with zipfile.ZipFile(path) as z:
                text = "\n".join(re.sub(r"<[^>]+>", "", re.sub(
                    r"</w:p>|</a:p>|</text:p>", "\n", z.read(n).decode("utf-8", "ignore")))
                    for n in z.namelist()[:40] if n.endswith(".xml"))
        else:
            text = path.read_bytes().decode("utf-8-sig", "ignore")
        if not text.strip():
            return [], "无可抽取文本"
        paras = [squeeze(x) for x in re.split(r"\n\s*\n", text)]
        paras = [p for p in paras if p] or [squeeze(x) for x in text.splitlines() if squeeze(x)]
        return [(("%s#para%d" % (path.name, i + 1)), p) for i, p in enumerate(paras)], None
    except Exception as exc:
        return [], "%s: %s" % (type(exc).__name__, exc)


def scan(inp):
    """遍历 /input：材料清单 + 逐字比对语料。"""
    inp, mats, corpus = Path(inp), [], []
    if not inp.exists():
        return mats, corpus
    for p in sorted(inp.rglob("*")):
        if not p.is_file() or p.name.startswith(".") or "__pycache__" in p.parts:
            continue
        blocks, note = blocks_of(p)
        mats.append({"id": p.name, "path": str(p), "rel": p.relative_to(inp).as_posix(),
                     "kind": file_kind(p), "bytes": p.stat().st_size, "blocks": len(blocks),
                     "note": note, "locators": [b[0] for b in blocks[:3]]})
        corpus += [{"material": mats[-1]["rel"], "locator": loc, "text": t} for loc, t in blocks]
    return mats, corpus


def quote_status(corpus, quote):
    """(状态, locator)：先逐字再宽松，都不中返回 None。"""
    q = squeeze(quote)
    if len(q) < 6:
        return None, None
    for b in corpus:
        if q in b["text"]:
            return "verbatim", b["locator"]
    sq = letters_only(q)
    if len(sq) >= 6:
        for b in corpus:
            if sq in letters_only(b["text"]):
                return "verbatim_loose", b["locator"]
    return None, None


def find_case(inp):
    inp = Path(inp)
    for c in (inp / "case.json", inp / "input" / "case.json"):
        if c.is_file():
            return c
    hits = [p for p in inp.rglob("*.json")
            if re.search(r"(^|/)(case|input)[^/]*\.json$", p.as_posix())]
    return sorted(hits)[0] if hits else None


def case_of(inp):
    cp = find_case(inp)
    return read_json(cp) if cp else None


def deep_find(obj, wants, depth=0):
    """在任意嵌套的 case.json 里按语义找字段，不依赖固定键路径。"""
    if depth > 6:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if v not in (None, "", [], {}) and any(
                    norm_key(k) == w or norm_key(k).endswith(w) or w in norm_key(k) for w in wants):
                return v
        kids = obj.values()
    elif isinstance(obj, list):
        kids = obj[:40]
    else:
        return None
    for v in kids:
        got = deep_find(v, wants, depth + 1)
        if got is not None:
            return got
    return None


def workorder(case):
    wo = deep_find(case, ["organizerworkorder", "workorder", "drawingorder", "figureworkorder"]) \
        if isinstance(case, dict) else None
    return wo if isinstance(wo, dict) else {}


def wo_items(wo, names):
    return next((wo[n] for n in names if wo.get(n)), [])


ZONE_KEYWORDS = (("extracellular", "secreted", "lumen", "胞外", "细胞外", "培养液"),
                 ("membrane", "receptor", "surface", "膜", "质膜"),
                 ("cytoplasm", "cytosol", "胞质", "胞内", "细胞质"),
                 ("nucleus", "nuclear", "chromatin", "细胞核", "核内"))


def guess_lane(text):
    t = (text or "").lower()
    for lane, *keys in ZONE_KEYWORDS:
        if any(k in t for k in keys):
            return lane
    return "cytoplasm"


def load_plan(work, out):
    for p in (Path(work) / "plan.json", Path(out) / "plan.json"):
        if p.is_file():
            obj = read_json(p)
            if isinstance(obj, dict) and (obj.get("entities") or obj.get("relations")):
                return obj, str(p), None
            return None, str(p), "plan.json 存在但没有 entities/relations"
    return None, None, "找不到 plan.json"


def fallback_plan(case, mats, corpus, edge_kind=None):
    """确定性兜底：只用工单条目与「A 动词 B」明写句。"""
    wo = workorder(case)
    els = wo_items(wo, ["required_elements", "elements", "entities", "required_entities"])
    rls = [r for r in wo_items(wo, ["required_relations", "relations", "edges", "interactions"])
           if isinstance(r, dict)]
    comps = wo_items(wo, ["compartments", "regions", "layers"])
    title = ""
    hint = deep_find(case, ["taskinstruction", "instruction", "task"]) if isinstance(case, dict) else None
    for cand in (wo.get("title"), hint):
        if isinstance(cand, str) and cand.strip():
            title = squeeze(cand.split("\n")[0])[:120]
            break
    ents, rels, seen = [], [], set()

    def add(lab, kind="unspecified", quote=None, loc="case.json#workorder", zone=None):
        lab = squeeze(lab)
        if lab and 1 < len(lab) <= 60 and lab.lower() not in seen:
            seen.add(lab.lower())
            ents.append({"id": lab, "label": lab, "kind": kind,
                         "compartment": zone or "unspecified",
                         "evidence": {"quote": quote or lab, "locator": loc}})

    for e in (els if isinstance(els, list) else []):
        d = e if isinstance(e, dict) else {"label": e}
        add(d.get("label") or d.get("name") or d.get("id"),
            (d.get("kind") or "unspecified").lower(), zone=d.get("compartment"))
    for n, d in enumerate(rls):
        s0, t0 = squeeze(d.get("source") or d.get("from")), squeeze(d.get("target") or d.get("to"))
        if s0 and t0:
            add(s0)
            add(t0)
            rels.append({"id": "r%d" % (n + 1), "source": s0, "target": t0,
                         "label": squeeze(d.get("label")), "type": d.get("type") or "unspecified",
                         "evidence": {"quote": "%s -> %s" % (s0, t0),
                                      "locator": "case.json#workorder.required_relations[%d]" % n}})
    gaps = ["兜底模式：标签全部取自输入原字符串，未做任何生物学推断。",
            "读材料、写 plan.json（带逐字引文）后重跑 build 才是正式图。"]
    if not rels:
        stop = set(("the a an this that these those it its they we our which who and but or if "
                    "when then than as at by for from in into of on to with also both each such "
                    "other protein proteins gene genes cell cells pathway signal signalling "
                    "level levels").split())
        pat = re.compile(r"\b([A-Za-z][A-Za-z0-9\-/]{1,17})\s+(activates|inhibits|represses|"
                         r"binds|phosphorylates|ubiquitinates|translocates|transports|recruits|"
                         r"promotes|suppresses|induces|cleaves|secretes|stabilizes)[a-z]*\s+"
                         r"([A-Za-z][A-Za-z0-9\-/]{1,17})\b")
        for b in corpus:
            for sent in re.split(r"(?<=[.!?])\s+", b["text"]):
                if len(rels) > 60:
                    break
                for m in pat.finditer(sent):
                    if m.group(1).lower() in stop or m.group(3).lower() in stop:
                        continue
                    lane = guess_lane(sent)
                    add(m.group(1), quote=m.group(0), loc=b["locator"], zone=lane)
                    add(m.group(3), quote=m.group(0), loc=b["locator"], zone=lane)
                    if not any(x["source"] == m.group(1) and x["target"] == m.group(3) for x in rels):
                        rels.append({"id": "r%d" % (len(rels) + 1), "source": m.group(1),
                                     "target": m.group(3), "label": "",
                                     "type": edge_kind(m.group(2)) if edge_kind else m.group(2),
                                     "evidence": {"quote": m.group(0), "locator": b["locator"]}})
        gaps.insert(0, "只从「A 动词 B」明写句挖边；分支、反馈环与缺失环节仍需人/Agent 写 plan.json。")
    if not ents:
        for m in mats[:10]:
            add(m["rel"])
        gaps.append("既无工单条目也无 plan.json：本图只做材料清点。")
    return {"title": title or "Supplied mechanism materials (inventory)",
            "subtitle": "fallback rendering - no Agent plan.json was found",
            "compartments": [{"id": squeeze(c.get("id") or c.get("label")) if isinstance(c, dict) else squeeze(c),
                              "order": i,
                              "label": squeeze(c.get("label") or c.get("id")) if isinstance(c, dict) else squeeze(c)}
                             for i, c in enumerate(comps)],
            "entities": ents, "relations": rels, "gaps": gaps}


def validate(plan, corpus, case):
    """给每项挂证据状态，并报出画不出来的东西。"""
    rep = {"ok": True, "issues": [], "rejected": [], "pending": [], "declared": 0}
    ents = [e for e in (plan.get("entities") or []) if isinstance(e, dict)]
    rels = [r for r in (plan.get("relations") or []) if isinstance(r, dict)]
    ids = set()

    def attach(x, kind, xid):
        ev = x.get("evidence") if isinstance(x.get("evidence"), dict) else {}
        q = ev.get("quote")
        st, loc = quote_status(corpus, q) if q else (None, None)
        if st:
            ev["status"], ev["verified_locator"] = st, loc
            ev["material"] = loc.split("#")[0]
        elif q and str(ev.get("locator", "")).startswith("case.json"):
            ev["status"], ev["declared_locator"] = "declared", ev.get("locator")
            rep["declared"] += 1
        elif q and len(squeeze(q)) < 6:
            ev["status"] = "too_short"
        elif q:
            ev["status"] = "unverified"
            rep["rejected"].append({"kind": kind, "id": xid, "quote": squeeze(q)[:110],
                                    "locator": ev.get("locator")})
        else:
            ev["status"] = "none"
            rep["issues"].append("%s %s: 没有 evidence.quote" % (kind, xid))
        x["evidence"] = ev
        return ev["status"]

    for e in ents:
        eid = squeeze(e.get("id"))
        if not eid:
            rep["issues"].append("实体缺 id: %r" % (e.get("label"),))
            continue
        if eid in ids:
            rep["issues"].append("实体 id 重复: %s" % eid)
        ids.add(eid)
        rep["issues"] += ["%s: 缺 %s" % (eid, f) for f in ("label", "kind", "compartment")
                          if not squeeze(e.get(f))]
        e["evidence_status"] = attach(e, "entity", eid)
    for r in rels:
        s0, t0 = squeeze(r.get("source")), squeeze(r.get("target"))
        if s0 not in ids or t0 not in ids:
            rep["issues"].append("关系 %s 指向不存在的实体 (%s -> %s)" % (r.get("id"), s0, t0))
        if not squeeze(r.get("type")):
            rep["issues"].append("关系 %s->%s 没有 type" % (s0, t0))
        r["evidence_status"] = attach(r, "relation", r.get("id"))
        if r["evidence_status"] == "unverified":
            rep["pending"].append({"kind": "relation", "id": r.get("id"), "from": s0, "to": t0,
                                   "reason": "引文未在材料中逐字命中，不绘制"})

    def candidates(name):
        """同名异义：同一标签可能对应多个实体（如胞质/核内两个 STAT3 池），返回候选集合。"""
        n = squeeze(name).lower()
        if not n:
            return set()
        hit = {squeeze(e.get("id")).lower() for e in ents
               if n in (squeeze(e.get("id")).lower(), squeeze(e.get("label")).lower())}
        if hit:
            return hit
        return {squeeze(e.get("id")).lower() for e in ents
                if n in set(re.split(r"[^a-z0-9]+", squeeze(e.get("label")).lower()))}

    wo = workorder(case)
    need = [squeeze(x.get("label") if isinstance(x, dict) else x)
            for x in wo_items(wo, ["required_elements", "elements", "entities", "required_entities"])]
    miss = [n for n in need if n and not candidates(n)]
    needr = [x for x in wo_items(wo, ["required_relations", "relations", "edges"])
             if isinstance(x, dict)]
    have = set()
    for r in rels:
        for s0 in candidates(r.get("source")):
            for t0 in candidates(r.get("target")):
                have.add((s0, t0))
    missr = []
    for x in needr:
        srcs, dsts = candidates(x.get("source")), candidates(x.get("target"))
        if srcs and dsts and not {(a, b) for a in srcs for b in dsts} & have:
            missr.append("%s->%s" % (squeeze(x.get("source")), squeeze(x.get("target"))))
    ok_st = ("verbatim", "verbatim_loose")

    def count(xs, v):
        return len([x for x in xs if x.get("evidence_status") == v])

    rep["counts"] = {
        "entities": len(ents), "relations": len(rels),
        "relations_drawn": len([r for r in rels if r.get("evidence_status") != "unverified"]),
        "entities_verified": len([e for e in ents if e["evidence_status"] in ok_st]),
        "relations_verified": len([r for r in rels if r["evidence_status"] in ok_st]),
        "entities_declared": count(ents, "declared"), "relations_declared": count(rels, "declared"),
        "required_elements": len(need), "required_elements_missing": len(miss),
        "required_relations": len(needr), "required_relations_missing": len(missr),
        "rejected_quotes": len(rep["rejected"]), "pending_items": len(rep["pending"]),
        "items_without_quote": len([x for x in ents + rels
                                    if x.get("evidence_status") in ("none", "too_short")])}
    rep["missing_required_elements"], rep["missing_required_relations"] = miss, missr
    rep["ok"] = not rep["issues"] and not rep["rejected"] and not miss and not missr
    return rep


# ---------------------------------------------------------------- 读回图面

def read_svg(text):
    """把 SVG 当数据读回：分组属性、图例、文字量度、越界。"""
    out = {"parsed": False, "entities": {}, "relations": {}, "legend": [], "layers": [],
           "texts": 0, "texts_latin": 0, "texts_cjk": 0, "italic_entities": [],
           "min_font": None, "oob": [], "text_overlaps": 0, "box_overlaps": 0, "boxes": 0}
    try:
        root = ET.fromstring(text)
    except Exception as exc:
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
        return out
    out.update({"parsed": True, "width": root.get("width"), "height": root.get("height")})
    boxes = []
    for g in root.iter(SVG_NS + "g"):
        gid = g.get("id") or ""
        if gid.startswith("layer-"):
            out["layers"].append(gid)
        elif gid.startswith("ent-"):
            out["entities"][gid] = {"kind": g.get("data-kind"), "zone": g.get("data-zone"),
                                    "quote": g.get("data-quote") or "",
                                    "locator": g.get("data-locator") or "",
                                    "italic": g.get("data-italic"),
                                    "status": g.get("data-quote-status")}
            if g.get("data-italic") == "true":
                out["italic_entities"].append(gid)
            for r in g.iter(SVG_NS + "rect"):
                if (r.get("fill") or "") != "none":
                    boxes.append((float(r.get("x")), float(r.get("y")),
                                  float(r.get("width")), float(r.get("height"))))
                    break
        elif gid.startswith("rel-"):
            out["relations"][gid] = {"type": g.get("data-type"), "source": g.get("data-from"),
                                     "target": g.get("data-to"),
                                     "direction": g.get("data-direction"),
                                     "quote": g.get("data-quote") or "",
                                     "locator": g.get("data-locator") or "",
                                     "status": g.get("data-quote-status")}
        elif gid.startswith("lg-"):
            out["legend"].append(gid)
    try:
        import figure_engine as EN
        width, height = float(out["width"]), float(out["height"])
    except Exception:
        EN, width, height = None, 1600.0, 1000.0
    spans = []
    for t in root.iter(SVG_NS + "text"):
        out["texts"] += 1
        fs = float(t.get("font-size") or 12)
        out["min_font"] = fs if out["min_font"] is None else min(out["min_font"], fs)
        body, x, y = (t.text or ""), float(t.get("x")), float(t.get("y"))
        if any(ord(c) > 255 for c in body):
            out["texts_cjk"] += 1
        if "".join(c for c in body if ord(c) < 256).strip():
            out["texts_latin"] += 1
        wpx = EN.adv(body, fs) if EN else len(body) * fs * 0.55
        anchor = t.get("text-anchor") or "start"
        x0 = x if anchor == "start" else (x - wpx / 2.0 if anchor == "middle" else x - wpx)
        spans.append((x0, y - fs * 0.78, x0 + wpx, y + fs * 0.25))
        if x0 < -1 or x0 + wpx > width + 1 or y - fs < -1 or y > height + 1:
            out["oob"].append({"text": body[:40], "x": round(x0, 1), "y": round(y, 1)})
    for i in range(len(spans)):
        for j in range(i + 1, len(spans)):
            a, b = spans[i], spans[j]
            if a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1:
                out["text_overlaps"] += 1
    out["box_overlaps"] = sum(
        1 for i in range(len(boxes)) for j in range(i + 1, len(boxes))
        if boxes[i][0] < boxes[j][0] + boxes[j][2] - 1 and boxes[j][0] < boxes[i][0] + boxes[i][2] - 1
        and boxes[i][1] < boxes[j][1] + boxes[j][3] - 1 and boxes[j][1] < boxes[i][1] + boxes[i][3] - 1)
    out["boxes"] = len(boxes)
    return out

def content_row(x, is_ent):
    """content_map 的一行：图面 id + 逐字引文 + 判型依据。"""
    import figure_engine as EN
    ev = x.get("evidence") or {}
    row = {"id": x["id"], "svg_id": "#%s-%s" % ("ent" if is_ent else "rel", EN.sid(x["id"])),
           "quote": ev.get("quote"), "quote_status": ev.get("status", "none"),
           "quote_verified": ev.get("status") in ("verbatim", "verbatim_loose"),
           "source_locator": ev.get("verified_locator") or ev.get("locator"), "drawn": True}
    if is_ent:
        row.update({"name": x["label"], "label": x["label"], "entity_type": x["kind"],
                    "compartment": x["compartment"], "species": x.get("species") or None,
                    "italic_required": bool(x["italic"])})
    else:
        colour, dash, head = EN.EDGE[x["type"]][:3]
        row.update({"from": x["source"], "to": x["target"], "relation_type": x["type"],
                    "direction": x["direction"], "label": x["label"],
                    "render": {"stroke": colour, "dash": dash, "head": head}})
    return row


def content_map(plan, p, st, counts, rep, layers):
    """实体 / 关系 / 图例编码 / 覆盖率的可核验清单。"""
    return {
        "figure": {"file": "figure.svg", "width": st["width"], "height": st["height"],
                   "layers": layers,
                   "xml_ids": "layer-* / zone-<id> / ent-<实体> / rel-<关系> / lg-*",
                   "trace_attrs": "data-quote, data-locator, data-quote-status, data-kind, "
                                  "data-type, data-direction, data-from, data-to, data-italic"},
        "entities": [content_row(e, True) for e in p["entities"]],
        "relations": [content_row(r, False) for r in p["relations"]],
        "compartments": [{"id": z["id"], "y": z["y"], "h": z["h"]} for z in st.get("zones", [])],
        "legend_encodings": ([{"channel": "fill", "meaning": k} for k in st.get("kinds", [])]
                             + [{"channel": "stroke+head+dash", "meaning": t}
                                for t in st.get("types", [])]),
        "encoding_notes": ["节点填充只编码实体种类", "线色+端点+虚线编码关系类型",
                           "没有 data_encoding 就不做数值编码"],
        "coverage": {"entities": len(p["entities"]), "relations": len(p["relations"]),
                     "required_elements": counts["required_elements"],
                     "required_elements_missing": counts["required_elements_missing"],
                     "required_relations": counts["required_relations"],
                     "required_relations_missing": counts["required_relations_missing"]},
        "pending": (plan.get("pending") if isinstance(plan.get("pending"), list) else [])
                   or [{"kind": x["kind"], "id": x["id"], "reason": x["reason"]}
                       for x in rep["pending"]],
        "gaps": p["gaps"]}
