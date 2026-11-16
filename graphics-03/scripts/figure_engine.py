"""布局内核：区室分带 -> 层内择优 -> 正交布线；文字量度用 Helvetica AFM 宽度，
换行、SVG 文本框与 PDF 矩阵共用一套数字。"""
import math
import re

W, H = 1600.0, 1000.0
PAD = 56.0
LANE_TOP, LANE_BOT, LANE_GAP = 104.0, 758.0, 30.0
NODE_L, NODE_R, RAIL_X = 214.0, 1520.0, 1556.0
FONT_STACK = "DejaVu Sans, Helvetica, Arial, sans-serif"
MIN_PX = 14.0
LEGEND_Y, LEGEND_H = 764.0, 178.0
FOOT_Y = (956.0, 972.0, 988.0)

LANES = [
    ("ext", "细胞外", "Extracellular",
     ("extracellular", "outside", "secreted", "lumen", "胞外", "细胞外", "分泌")),
    ("mem", "细胞膜", "Plasma membrane",
     ("membrane", "plasma_mem", "cell_surface", "surface", "膜", "质膜")),
    ("cyt", "细胞质", "Cytoplasm",
     ("cytoplasm", "cytosol", "cyto", "胞质", "胞内", "细胞质", "细胞浆")),
    ("nuc", "细胞核", "Nucleus",
     ("nucleus", "nuclear", "chromatin", "细胞核", "核内", "染色质")),
]
LANE_LABEL = {z[0]: (z[1], z[2]) for z in LANES}
LANE_LABEL["oth"] = ("未注明", "Location not stated")

# 种类 -> (填充色, 图例文字)
KIND = {
    "protein": ("#dbe8f6", "protein 蛋白"), "gene": ("#e2f0da", "gene 基因"),
    "complex": ("#efe0f6", "complex 复合物"), "ligand": ("#fde6d8", "ligand 配体"),
    "cell": ("#fdf1d2", "cell 细胞"), "metabolite": ("#ebebeb", "metabolite 代谢物"),
    "phenotype": ("#f7dede", "phenotype 表型"), "mirna": ("#ddf0ef", "miRNA"),
    "unspecified": ("#f1f3f5", "kind not stated 未注明"),
}

EDGE = {
    "activation": ("#1f6fb2", None, "solid", 2.0, "→", "activation 激活"),
    "inhibition": ("#b03a2e", None, "bar", 2.0, "⊣", "inhibition 抑制"),
    "binding": ("#2e7d5b", None, "open", 2.0, "◇", "binding 结合"),
    "modification": ("#6b4fa0", None, "solid", 2.2, "P", "modification 修饰 (P/Ub)"),
    "transport": ("#b06a1f", None, "double", 2.4, "⇄", "transport 转运"),
    "indirect": ("#7a7a7a", "5,5", "open", 1.6, "⇢", "indirect 间接 (inferred)"),
    "unspecified": ("#9a9a9a", "6,3,1,3", "open", 1.6, "?", "not stated 未说明"),
}

# 动词台账
VERBS = (
    ("activation", "activate activates activated activation promote promotes promoted induce "
     "induces upregulate stimulates enhances drives 激活 促进 上调 增强 诱导"),
    ("inhibition", "inhibit inhibits inhibited inhibition repress represses suppress suppresses "
     "block blocks blocked blockade prevent prevents 抑制 下调 阻断 负反馈 阻遏"),
    ("binding", "bind binds binding bound interacts interact interaction recruit recruits "
     "recruited dimerize dimerizes assemble assembles associates 结合 募集 互作 二聚化"),
    ("modification", "phosphorylate phosphorylates phosphorylated phosphorylation ubiquitinate "
     "ubiquitinates ubiquitination cleave cleaves cleavage methylate acetylate "
     "磷酸化 泛素化 甲基化 乙酰化 剪切 修饰"),
    ("transport", "transport transports translocate translocates translocation secrete secretes "
     "secretion release releases export exports import imports traffic shuttle "
     "转运 转位 分泌 释放 出核 入核 输出"),
    ("indirect", "indirect implied implies suggest suggests presumably 推断 推测 间接"),
)
VERB_MAP = {}
for _k, _blob in VERBS:
    for _w in _blob.split():
        VERB_MAP.setdefault(_w.lower(), _k)

_AFM = ("278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278 556 556 556 556 "
        "556 556 556 556 556 556 278 278 584 584 584 556 1015 667 667 722 722 667 611 778 "
        "722 278 500 667 556 833 722 778 667 778 722 667 611 722 667 944 667 667 611 278 "
        "278 278 278 469 556 333 556 556 500 556 556 278 556 556 222 222 500 222 833 556 "
        "556 556 556 333 500 278 556 500 722 500 500 500 334 260 334 584")
_ADV = [float(x) for x in _AFM.split()]


def adv(s, size, bold=False):
    """字符串宽度 px（Helvetica 度量，粗体 1.03x）。"""
    total = 0.0
    for ch in str(s):
        o = ord(ch)
        total += _ADV[o - 32] if 32 <= o <= 126 else 600.0
    return total / 1000.0 * size * (1.03 if bold else 1.0)


def fold(s, maxw, size, bold=False, limit=3):
    """贪心换行，超长词硬切。"""
    s = "" if s is None else str(s).strip()
    if not s:
        return [""]
    lines, cur = [], ""
    for word in s.split():
        cand = (cur + " " + word).strip()
        if not cur or adv(cand, size, bold) <= maxw:
            if adv(cand, size, bold) <= maxw:
                cur = cand
                continue
        lines.append(cur)
        cur = word
        while adv(cur, size, bold) > maxw and len(cur) > 1:
            cut = max(1, int(len(cur) * maxw / max(1.0, adv(cur, size, bold))))
            lines.append(cur[:cut])
            cur = cur[cut:]
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        while adv(ln, size, bold) > maxw and len(ln) > 1:
            cut = max(1, int(len(ln) * maxw / max(1.0, adv(ln, size, bold))))
            out.append(ln[:cut])
            ln = ln[cut:]
        out.append(ln)
    if len(out) > limit:
        out = out[:limit]
        tail = out[-1]
        while tail and adv(tail + "…", size, bold) > maxw:
            tail = tail[:-1]
        out[-1] = tail + "…"
    return out or [""]


def flat(v):
    """dict/list/None -> 一行文字。"""
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return ", ".join(flat(x) for x in v)
    if isinstance(v, dict):
        return flat(v.get("label") or v.get("name") or v.get("text") or v.get("id"))
    return str(v).strip()


def sid(s):
    s = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(s))
    return re.sub(r"_+", "_", s).strip("_") or "x"


def as_int(v, default):
    try:
        return int(v)
    except Exception:
        return default


def edge_kind(t):
    """类型写法 -> 七种语义之一；认不出落到 unspecified。"""
    k = str(t or "").strip().lower().replace("-", "_").replace(" ", "_")
    return k if k in EDGE else VERB_MAP.get(k, "unspecified")


def coerce(plan):
    """plan 归一化；端点不认识的关系丢弃，不补分子。"""
    plan = plan if isinstance(plan, dict) else {}
    lanes = []
    for i, c in enumerate(plan.get("compartments") or []):
        d = c if isinstance(c, dict) else {"label": flat(c)}
        cid = flat(d.get("id")) or "c%d" % i
        lanes.append({"id": cid, "label": flat(d.get("label")) or cid,
                      "order": as_int(d.get("order"), i)})
    lanes.sort(key=lambda x: (x["order"], x["id"]))
    ents, seen = [], set()
    for i, e in enumerate(plan.get("entities") or []):
        d = e if isinstance(e, dict) else {"label": flat(e)}
        eid = flat(d.get("id")) or flat(d.get("label")) or "e%d" % i
        base, n = eid, 2
        while eid.lower() in seen:
            eid, n = "%s_%d" % (base, n), n + 1
        seen.add(eid.lower())
        kind = (flat(d.get("kind")) or "unspecified").lower()
        italic = d.get("italic")
        ev = d.get("evidence")
        ents.append({"id": eid, "label": flat(d.get("label")) or eid,
                     "sublabel": flat(d.get("sublabel") or d.get("detail")),
                     "kind": kind if kind in KIND else "unspecified",
                     "compartment": flat(d.get("compartment")),
                     "species": flat(d.get("species")),
                     "italic": (kind == "gene") if italic is None else bool(italic),
                     "evidence": ev if isinstance(ev, dict) else {},
                     "evidence_status": flat(d.get("evidence_status")),
                     "encoding": d.get("encoding")})
    by_id = {e["id"].lower(): e["id"] for e in ents}
    rels = []
    for i, r in enumerate(plan.get("relations") or []):
        if not isinstance(r, dict):
            continue
        src = by_id.get(flat(r.get("source")).lower())
        dst = by_id.get(flat(r.get("target")).lower())
        if not src or not dst or src == dst:
            continue
        ev = r.get("evidence")
        rels.append({"id": flat(r.get("id")) or "r%d" % (i + 1), "source": src, "target": dst,
                     "type": edge_kind(r.get("type") or r.get("relation")),
                     "label": flat(r.get("label")), "badge": flat(r.get("badge")),
                     "direction": (flat(r.get("direction")).lower() or "forward"),
                     "evidence": ev if isinstance(ev, dict) else {},
                     "evidence_status": flat(r.get("evidence_status"))})
    return {"title": flat(plan.get("title")), "subtitle": flat(plan.get("subtitle")),
            "compartments": lanes, "entities": ents, "relations": rels,
            "legend_extra": [flat(g) for g in (plan.get("legend_extra") or []) if flat(g)],
            "data_encoding": plan.get("data_encoding") if isinstance(plan.get("data_encoding"), dict) else {},
            "gaps": [flat(g) for g in (plan.get("gaps") or []) if flat(g)],
            "pending": [flat(g) for g in (plan.get("pending") or []) if flat(g)]}


# ------------------------------------------------------------------ 布局

def fit_grid(n, span, area):
    """(列, 行, 框宽, 框高, 拥挤)，尽量留 12px 布线余量。"""
    for rows in (1, 2, 3):
        cols = max(1, int(math.ceil(n / float(rows))))
        bw, bh = span / cols - 40.0, (area - (rows - 1) * 12.0 - 12.0) / rows
        if bw >= 150.0 and bh >= 40.0:
            return cols, rows, min(bw, 290.0), min(bh, 88.0), False
    cols = max(1, int(math.ceil(n / 3.0)))
    return cols, 3, max(112.0, span / cols - 26.0), max(30.0, (area - 36.0) / 3.0), True


def share_heights(weights, avail, gap):
    """层高按实体数分配，守住 76px 下限。"""
    total = avail - gap * (len(weights) - 1)
    base = [max(76.0, total * w / float(sum(weights) or 1)) for w in weights]
    for _ in range(5):
        over = sum(base) - total
        if over <= 0.5:
            break
        free = [i for i, b in enumerate(base) if b > 76.5]
        pool = sum(base[i] - 76.0 for i in free)
        if not free or pool <= 0:
            break
        for i in free:
            base[i] -= min(over, pool) * (base[i] - 76.0) / pool
    base[-1] += total - sum(base)
    return base


def lane_for(compartment, alias=None):
    """区室文本 -> 泳道 id；说不清就返回 None（落 oth 层并计入缺口）。"""
    probe = " " + (compartment or "").lower().replace("_", " ") + " "
    if alias:
        probe += " " + alias.get((compartment or "").lower(), "").lower().replace("_", " ") + " "
    for zid, _zh, _en, keys in LANES:
        if any(k in probe for k in keys):
            return zid
    return None


def alias_table(p):
    out = {}
    for c in p.get("compartments") or []:
        out[c["id"].lower()] = c["label"]
        out[c["label"].lower()] = c["label"]
    return out


def split_lanes(ents, alias=None):
    """实际用到的泳道，上游->下游。"""
    lane_of = {e["id"]: (lane_for(e["compartment"], alias) or "oth") for e in ents}
    seeded = [z[0] for z in LANES if any(v == z[0] for v in lane_of.values())]
    used = [z[0] for z in LANES] if len(seeded) >= 2 else seeded
    if any(v == "oth" for v in lane_of.values()):
        used = used + ["oth"]
    return used, lane_of


def mount(lanes, groups, zbox):
    """泳道内摆框：返回 (位置, 行/通道信息, 拥挤)。"""
    pos, meta, tight = {}, {}, False
    for bi, lane in enumerate(lanes):
        top, h = zbox[bi][1], zbox[bi][2]
        a_top, a_bot = top + 8.0, top + h - 8.0
        area = a_bot - a_top
        ents = groups[lane]
        if not ents:
            continue
        cols, rows, bw, bh, tg = fit_grid(len(ents), NODE_R - NODE_L, area)
        if lane == "mem" and len(ents) <= 5:
            rows, cols = 1, max(1, len(ents))
            bh = min(74.0, area - 12.0)
            bw = min(250.0, (NODE_R - NODE_L) / cols - 30.0)
        tight = tight or tg
        block = rows * bh + (rows - 1) * 12.0
        y0 = a_top + (area - block) / 2.0
        for r in range(rows):
            row = ents[r * cols:(r + 1) * cols]
            if not row:
                continue
            span = (NODE_R - NODE_L) / float(len(row))
            w = min(bw, span - 26.0)
            ry = y0 + r * (bh + 12.0)
            for i, eid in enumerate(row):
                cx = NODE_L + span * (i + 0.5)
                pos[eid] = (cx - w / 2.0, ry, w, bh)
                meta[eid] = {"lane": bi, "row": r, "rows": rows, "row_top": ry,
                             "row_bot": ry + bh, "lane_top": top, "lane_bot": top + h,
                             "ch_bot": (ry + bh + 6.0) if r + 1 < rows else (top + h - 7.0),
                             "ch_top": (ry - 6.0) if r > 0 else (a_top - 4.0)}
    return pos, meta, tight


def col_clear(pos, x, ya, yb, skip=()):
    """[ya, yb] 上的竖线在 x 处是否避开方框。"""
    lo, hi = min(ya, yb), max(ya, yb)
    for eid, q in pos.items():
        if eid in skip:
            continue
        if q[0] - 2.0 < x < q[0] + q[2] + 2.0 and lo < q[1] + q[3] - 2.0 and hi > q[1] + 2.0:
            return False
    return True


def pick_side(pos, eid, other_y, skip=()):
    """(通道 x, 端口 x, 行中心 y)。"""
    q = pos[eid]
    cx, cy = q[0] + q[2] / 2.0, q[1] + q[3] / 2.0
    for dx in (13.0, 34.0, 60.0):
        for x in (q[0] - dx, q[0] + q[2] + dx):
            if (NODE_L - 12.0 <= x <= NODE_R + 12.0) and col_clear(pos, x, cy, other_y, skip):
                return x, (q[0] if x < cx else q[0] + q[2]), cy
    return cx, cx, cy


def spread(offsets, width):
    """同侧多条线沿端口均分，避免起点重合。"""
    n = len(offsets)
    if n <= 1:
        return {k: 0.0 for k in offsets}
    step = min(30.0, (width - 40.0) / float(n - 1))
    return {k: (i - (n - 1) / 2.0) * step for i, k in enumerate(sorted(offsets))}


def dedupe(pts):
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) > 0.5 or abs(p[1] - out[-1][1]) > 0.5:
            out.append(p)
    return out if len(out) > 1 else [pts[0], (pts[0][0], pts[0][1] + 1)]


def walk(pos, meta, rel, down, y1, y2, rail=None, soff=0.0, toff=0.0):
    """出口 -> 通道行 -> 入口；目标不在层边缘时侧向进线，避免压过上排。"""
    a, b = meta[rel["source"]], meta[rel["target"]]
    sq, tq = pos[rel["source"]], pos[rel["target"]]
    scx, scy = sq[0] + sq[2] / 2.0, sq[1] + sq[3] / 2.0
    tcx, tcy = tq[0] + tq[2] / 2.0, tq[1] + tq[3] / 2.0
    if down and a["row"] == a["rows"] - 1:
        start, sx0 = (scx + soff, sq[1] + sq[3]), scx + soff
    elif (not down) and a["row"] == 0:
        start, sx0 = (scx + soff, sq[1]), scx + soff
    else:
        gx, port, _y = pick_side(pos, rel["source"], y1, (rel["source"],))
        start, sx0 = (port, scy + soff), gx
    if down and b["row"] == 0:
        end, tx0 = (tcx + toff, tq[1]), tcx + toff
    elif (not down) and b["row"] == b["rows"] - 1:
        end, tx0 = (tcx + toff, tq[1] + tq[3]), tcx + toff
    else:
        gx, port, _y = pick_side(pos, rel["target"], y2, (rel["target"],))
        end, tx0 = (port, tcy + toff), gx
    pts = [start, (sx0, start[1])] if abs(start[0] - sx0) > 0.5 else [start]
    pts.append((sx0, y1))
    if rail is not None:
        pts += [(rail, y1), (rail, y2), (tx0, y2)]
    elif abs(sx0 - tx0) > 0.5 or y2 != y1:
        pts.append((tx0, y2))
    pts.append((tx0, end[1]))
    if abs(tx0 - end[0]) > 0.5:
        pts.append(end)
    return dedupe(pts)


def route(pos, meta, rels, zbox):
    """正交布线：行间通道 / 层间走廊 / 右侧轨道。"""
    out, ctr, rails = [], {}, []
    fan_s = {e: spread([r["id"] for r in rels if r["source"] == e], pos[e][2]) for e in pos}
    fan_t = {e: spread([r["id"] for r in rels if r["target"] == e], pos[e][2]) for e in pos}
    for r in rels:
        si, ti = meta[r["source"]]["lane"], meta[r["target"]]["lane"]
        sq, tq = pos[r["source"]], pos[r["target"]]
        scy, tcy = sq[1] + sq[3] / 2.0, tq[1] + tq[3] / 2.0
        soff, toff = fan_s[r["source"]].get(r["id"], 0.0), fan_t[r["target"]].get(r["id"], 0.0)
        if si == ti:
            a, b = meta[r["source"]], meta[r["target"]]
            if a["row"] == b["row"]:
                lo, hi = min(sq[0] + sq[2], tq[0] + tq[2]), max(sq[0], tq[0])
                blocked = any(lo < q[0] + q[2] - 1 and q[0] < hi - 1 for e, q in pos.items()
                              if e not in (r["source"], r["target"]) and meta[e]["lane"] == si
                              and meta[e]["row"] == a["row"])
                if not blocked:
                    pts = ([(sq[0] + sq[2], scy), (tq[0], tcy)] if tq[0] > sq[0]
                           else [(sq[0], scy), (tq[0] + tq[2], tcy)])
                    out.append((r, dedupe(pts)))
                    continue
            elif col_clear(pos, sq[0] + sq[2] / 2.0, scy, tcy, (r["source"], r["target"])):
                pts = [(sq[0] + sq[2] / 2.0, sq[1] + sq[3] if b["row"] > a["row"] else sq[1]),
                       (sq[0] + sq[2] / 2.0, tcy), (tq[0] + tq[2] / 2.0, tcy),
                       (tq[0] + tq[2] / 2.0,
                        tq[1] if b["row"] > a["row"] else tq[1] + tq[3])]
                out.append((r, dedupe(pts)))
                continue
            k = ctr.get(("s", si), 0)
            ctr[("s", si)] = k + 1
            down = b["row"] >= a["row"]
            ch = (a["ch_bot"] + 3.0 * (k % 2)) if down else (a["ch_top"] - 3.0 * (k % 2))
            pts = walk(pos, meta, r, down, ch, ch, None, soff, toff)
        elif abs(si - ti) == 1:
            gi = min(si, ti)
            k = ctr.get(("g", gi), 0)
            ctr[("g", gi)] = k + 1
            gy = zbox[gi][1] + zbox[gi][2] + 4.5 + 4.0 * (k % 5)
            pts = walk(pos, meta, r, ti > si, gy, gy, None, soff, toff)
        else:
            down = ti > si
            lo, hi = min(scy, tcy), max(scy, tcy)
            slot = ctr.get(("r",), 0)
            ctr[("r",)] = slot + 1
            pick = slot % 4
            for cand in range(4):
                if not any(rr == cand and not (hi + 8 < a0 or lo - 8 > b0) for a0, b0, rr in rails):
                    pick = cand
                    break
            rails.append((lo, hi, pick))
            if down:
                y1 = zbox[si][1] + zbox[si][2] + 4.5 + 3.5 * (ctr.get(("d", si), 0) % 3)
                y2 = zbox[ti][1] - 6.0 - 3.5 * (ctr.get(("u", ti), 0) % 3)
                ctr[("d", si)], ctr[("u", ti)] = ctr.get(("d", si), 0) + 1, ctr.get(("u", ti), 0) + 1
            else:
                y1 = zbox[si][1] - 6.0 - 3.5 * (ctr.get(("u", si), 0) % 3)
                y2 = zbox[ti][1] + zbox[ti][2] + 4.5 + 3.5 * (ctr.get(("d", ti), 0) % 3)
                ctr[("u", si)], ctr[("d", ti)] = ctr.get(("u", si), 0) + 1, ctr.get(("d", ti), 0) + 1
            pts = walk(pos, meta, r, down, y1, y2, RAIL_X + 11.0 * pick, soff, toff)
        out.append((r, dedupe(pts)))
    return out


def count_crossings(routes):
    """交叉计数：只算严格内部相交。"""
    hs, vs = [], []
    for _r, pts in routes:
        for a, b in zip(pts, pts[1:]):
            if abs(a[1] - b[1]) < 0.6 and abs(a[0] - b[0]) > 1:
                hs.append((min(a[0], b[0]), max(a[0], b[0]), a[1]))
            elif abs(a[0] - b[0]) < 0.6 and abs(a[1] - b[1]) > 1:
                vs.append((min(a[1], b[1]), max(a[1], b[1]), a[0]))
    return sum(1 for a, b, y in hs for c, d, x in vs if a + 1 < x < b - 1 and c + 1 < y < d - 1)


def box_intrusions(pos, routes):
    """连线只允许碰它连接的两个框。"""
    hits = []

    def crosses(p1, p2, r):
        x, y, w, h = r
        if abs(p1[1] - p2[1]) < 0.6:
            a, c = min(p1[0], p2[0]), max(p1[0], p2[0])
            return (y + 2 < p1[1] < y + h - 2) and a < x + w - 2 and c > x + 2
        if abs(p1[0] - p2[0]) < 0.6:
            a, c = min(p1[1], p2[1]), max(p1[1], p2[1])
            return (x + 2 < p1[0] < x + w - 2) and a < y + h - 2 and c > y + 2
        return False

    for r, pts in routes:
        for a, b in zip(pts, pts[1:]):
            for eid, rect in pos.items():
                if eid not in (r["source"], r["target"]) and crosses(a, b, rect):
                    hits.append({"relation": r["id"], "box": eid})
    return hits


def _eval(lanes, groups, zbox, rels):
    pos, meta, tight = mount(lanes, groups, zbox)
    routes = route(pos, meta, rels, zbox) if rels else []
    return (count_crossings(routes) if routes else 0, len(box_intrusions(pos, routes)),
            pos, meta, routes, tight)


def _cost(lanes, groups, zbox, rels, plan_idx=None):
    """扣分：穿框 > 交叉 > 与工单顺序的位移。"""
    try:
        cr, hits, _p, _m, _r, _t = _eval(lanes, groups, zbox, rels)
    except Exception:
        return (10 ** 9,)
    drift = (sum(abs(i - plan_idx.get(e, i)) for b in lanes for i, e in enumerate(groups[b]))
             if plan_idx else 0)
    return (1000.0 * float(hits) + 10.0 * float(cr) + 0.5 * float(drift),)


def _improve(lanes, start, zbox, rels):
    """层内相邻交换爬山（≤3 轮），平手保留原序，保证可复现。"""
    cur = {b: list(start[b]) for b in lanes}
    plan_idx = {e: i for b in lanes for i, e in enumerate(start[b])}
    best = _cost(lanes, cur, zbox, rels, plan_idx)
    for _ in range(3):
        moved = False
        for b in lanes:
            for i in range(len(cur[b]) - 1):
                cand = {k: list(v) for k, v in cur.items()}
                cand[b][i], cand[b][i + 1] = cand[b][i + 1], cand[b][i]
                sc = _cost(lanes, cand, zbox, rels, plan_idx)
                if sc < best:
                    best, cur, moved = sc, cand, True
        if not moved:
            break
    return best, cur


def arrange(p):
    """层序固定、层内择优。"""
    ents, rels = p["entities"], p["relations"]
    blank = {"lanes": [], "groups": {}, "pos": {}, "meta": {}, "zbox": [], "routes": [],
             "crossings": 0, "hits": 0, "tight": False, "lane_of": {}, "order_choice": "empty"}
    if not ents:
        return blank
    lanes, lane_of = split_lanes(ents, alias_table(p))
    weights = [max(2.0, min(7.0, float(sum(1 for e in ents if lane_of[e["id"]] == b))))
               for b in lanes]
    heights = share_heights(weights, LANE_BOT - LANE_TOP, LANE_GAP)
    zbox, y = [], LANE_TOP
    for b, h in zip(lanes, heights):
        zbox.append((b, y, h))
        y += h + LANE_GAP
    base = {b: [e["id"] for e in ents if lane_of[e["id"]] == b] for b in lanes}
    best = None
    for name, st in (("plan order", base),
                     ("reversed plan", {b: list(reversed(v)) for b, v in base.items()})):
        try:
            sc, groups = _improve(lanes, st, zbox, rels)
        except Exception:
            continue
        if best is None or sc < best[0]:
            best = (sc, name if name == "plan order" else name + " + swap search", groups)
    if best is None:
        best = (_cost(lanes, base, zbox, rels), "plan order", base)
    _sc, name, groups = best
    cr, hits, pos, meta, routes, tight = _eval(lanes, groups, zbox, rels)
    return {"lanes": lanes, "groups": groups, "pos": pos, "meta": meta, "zbox": zbox,
            "routes": routes, "crossings": cr, "hits": hits, "tight": tight,
            "lane_of": lane_of, "order_choice": name}


if __name__ == "__main__":
    import sys
    if "--help" in sys.argv or "-h" in sys.argv:
        print("figure_engine.py - 布局内核（区室分带 / 层内择优 / 正交布线），供 figure_paint 调用。")
        sys.exit(0)
    demo = {"title": "layout selftest", "entities": [
        {"id": "A", "label": "AKT1", "kind": "gene", "compartment": "cytoplasm"},
        {"id": "B", "label": "p-AKT", "kind": "protein", "compartment": "cytoplasm"},
        {"id": "C", "label": "FOXO3", "kind": "protein", "compartment": "nucleus"}],
        "relations": [{"id": "r1", "source": "A", "target": "B", "type": "activation"},
                      {"id": "r2", "source": "B", "target": "C", "type": "inhibition"}]}
    lo = arrange(coerce(demo))
    print("lanes=%s crossings=%s hits=%s order=%s"
          % (",".join(lo["lanes"]), lo["crossings"], lo["hits"], lo["order_choice"]))
    sys.exit(0)
