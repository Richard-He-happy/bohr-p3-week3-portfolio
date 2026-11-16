#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mmcore.py — 导图内核：词表、工作稿规范化、引文逐字核验、树形布局、契约回填。

被 mindmap_cli.py / mmio.py / audit.py 导入；本身不含命令行入口。
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

REL_CODES = ("cause", "depends", "contrast", "sequence", "cite", "support", "conflict")
REL_ZH = {"cause": "因果", "depends": "依赖", "contrast": "对比",
          "sequence": "时间", "cite": "引用", "support": "支持", "conflict": "冲突"}
REL_ALIAS = {c: c for c in REL_CODES}
REL_ALIAS.update({v: k for k, v in REL_ZH.items()})
REL_ALIAS.update({"causal": "cause", "depend": "depends", "dep": "depends", "time": "sequence",
                  "order": "sequence", "时序": "sequence", "对照": "contrast", "compare": "contrast",
                  "citation": "cite", "ref": "cite", "supports": "support", "证据支持": "support",
                  "矛盾": "conflict", "依赖关系": "depends", "支持关系": "support", "引用关系": "cite",
                  "因果关系": "cause", "冲突关系": "conflict"})

ROLE_CODES = ("question", "method", "evidence", "finding", "conclusion",
              "limitation", "gap", "task", "risk", "concept", "subtopic")
ROLE_ZH = {"question": "问题", "method": "方法", "evidence": "证据", "finding": "结果",
           "conclusion": "结论", "limitation": "局限", "gap": "空白", "task": "任务",
           "risk": "风险", "concept": "概念", "subtopic": "子题"}
ROLE_ALIAS = {c: c for c in ROLE_CODES}
ROLE_ALIAS.update({v: k for k, v in ROLE_ZH.items()})
ROLE_ALIAS.update({"result": "finding", "发现": "finding", "recommendation": "task",
                   "methodology": "method", "方法学": "method", "研究问题": "question",
                   "topic": "concept", "要点": "subtopic", "危害": "risk"})

PAINT = {0: ("#123a5e", "#ffffff"), 1: ("#1f6fa8", "#ffffff"),
         2: ("#e2eef7", "#123a5e"), 3: ("#f4f8fc", "#123a5e")}
REL_PAINT = {"cause": ("#b3541e", "7,4"), "depends": ("#8a6d1f", "5,3"),
             "contrast": ("#6a4c93", "7,4"), "sequence": ("#1f6f8b", "9,3"),
             "cite": ("#5b6b7b", "2,4"), "support": ("#2a7f62", "7,4"),
             "conflict": ("#b02a37", "3,3")}

RESULT_FIXED = ("sources", "uncertainty", "pending_human", "errors",
                "degradations", "changes", "runtime", "artifacts", "coverage")

CONTRACT_RULES = (
    (r"content_?map|映射", "content_map"),
    (r"evidence|来源映射|source_?map|trace|locator|引用记录", "evidence_map"),
    (r"preserved|fact|事实|数字|术语", "preserved_facts"),
    (r"change|revision|diff|修改|变更|版本", "change_log"),
    (r"deliver|artifact|产物|文稿|main_?output|主结果", "deliverable"),
    (r"mindmap|structure|导图|节点|hierarch|branch|分支", "mindmap"),
    (r"uncertain|不确定|存疑|局限", "uncertainty"),
    (r"preview|预览|png|render|export", "preview"),
    (r"coverage|覆盖|count|统计", "coverage"),
    (r"source|来源|材料|material", "sources"),
    (r"note|说明|remark|comment|备注", "note"),
)

_DASH = ("\u00ad", "\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212")
_QUOTE = {"\u2018": '"', "\u2019": '"', "\u201c": '"', "\u201d": '"',
          "\u00a0": " ", "\u3000": " "}


def fold(text):
    """比对口径：NFKC → 破折号/引号折叠 → 空白压缩 → 小写。"""
    s = unicodedata.normalize("NFKC", str(text or ""))
    for ch in _DASH:
        s = s.replace(ch, "-")
    for a, b in _QUOTE.items():
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


def squeeze(text):
    """更宽容的二次比对：抹掉空白与连字符。"""
    return re.sub(r"[\s\-]+", "", fold(text))


def clip(text, cap=60):
    return re.sub(r"\s+", " ", str(text or "")).strip()[:cap]


def first_sentence(text, cap=150):
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    m = re.match(r"(.{4,}?[。．.!?！？；;])", s)
    return (m.group(1) if m else s)[:cap].strip()


def _lookup(table, value):
    key = fold(value).strip("_ ")
    if key in table:
        return table[key]
    for alias, code in table.items():
        if alias and alias in key:
            return code
    return ""


def rel_of(value):
    return _lookup(REL_ALIAS, value)


def role_of(value):
    return _lookup(ROLE_ALIAS, value)


class Locator:
    """材料单元定位表：命中则返回该单元 locator。"""

    def __init__(self, materials):
        self.mats = {str(m.get("id")): m for m in (materials or [])
                     if isinstance(m, dict) and m.get("id")}
        self._view = {}

    def _rows(self, mid):
        if mid not in self._view:
            rows = [(str(u.get("locator") or "?"), fold(u.get("text")), squeeze(u.get("text")))
                    for u in (self.mats.get(mid) or {}).get("units") or []]
            head = " ".join(r[1] for r in rows)
            self._view[mid] = (rows, head, squeeze(head))
        return self._view[mid]

    def find(self, mid, quote):
        q = (quote or "").strip()
        if not q or mid not in self.mats:
            return False, None
        rows, head, flat = self._rows(mid)
        fq, sq = fold(q), squeeze(q)
        if not fq or (fq not in head and (not sq or sq not in flat)):
            return False, None
        for loc, ftxt, stxt in rows:
            if fq in ftxt or (sq and sq in stxt):
                return True, loc
        return True, None


class Forger:
    """把工作稿译成规范模型，并给每条证据发号供关系引用。"""

    FIGURE = re.compile(r"^(figure|fig|table|tbl|slide|image|diagram|图|表)", re.I)

    def __init__(self, index):
        self.loc = Locator((index or {}).get("materials"))
        self.seq = 0

    def evidence(self, raw_list):
        rows, any_ok = [], False
        for item in raw_list or []:
            if not isinstance(item, dict):
                continue
            quote = re.sub(r"\s+", " ", str(item.get("quote") or "")).strip()
            locator = str(item.get("locator") or "").strip()
            mid = str(item.get("material") or item.get("material_id") or "").strip()
            hit, found = self.loc.find(mid, quote)
            if not hit and not quote and self.FIGURE.match(locator):
                hit = True                 # 图表类可无引文，但必须给 locator
            self.seq += 1
            rows.append({"id": "EV%02d" % self.seq, "material": mid,
                         "locator": locator or (found or ""), "quote": quote,
                         "verified": bool(hit)})
            any_ok = any_ok or bool(hit)
        return rows, any_ok


def measure(model):
    """按 parent 链求层级，返回 (最大深度, 断链或成环节点)。"""
    pool = {n["id"]: n for n in model["nodes"]}
    depth, broken = 1, []
    for node in model["nodes"]:
        seen, hops, cur = {node["id"]}, 0, node
        while True:
            par = str(cur.get("parent") or "root").strip() or "root"
            if par == "root":
                break
            if par not in pool or par in seen or hops > 12:
                hops = -1
                break
            seen.add(par)
            hops += 1
            cur = pool[par]
        if hops < 0:
            broken.append(node["id"])
        else:
            node["level"] = hops + 1
            depth = max(depth, hops + 1)
    return depth, broken


def build_model(draft, index):
    forge = Forger(index)
    theme = draft.get("theme") if isinstance(draft.get("theme"), dict) else {"label": draft.get("theme")}
    model = {"theme": {"id": "root", "label": clip(theme.get("label"), 60), "evidence": []},
             "nodes": [], "edges": [], "dropped": [], "unverified": [], "skipped": []}
    model["theme"]["evidence"], _ = forge.evidence(theme.get("evidence"))

    taken = {"root"}
    for pos, raw in enumerate([x for x in (draft.get("nodes") or []) if isinstance(x, dict)], 1):
        label = clip(raw.get("label"))
        if not label:
            model["skipped"].append({"at": pos, "reason": "label 为空"})
            continue
        nid = str(raw.get("id") or "n%d" % pos).strip() or "n%d" % pos
        if nid in taken or nid == "root":
            nid = "%s#%d" % (nid, pos)
        taken.add(nid)
        ev, ok = forge.evidence(raw.get("evidence"))
        role = role_of(raw.get("role") or raw.get("type")) or "subtopic"
        model["nodes"].append({
            "id": nid, "label": label,
            "parent": str(raw.get("parent") or raw.get("parent_id") or "root").strip() or "root",
            "parent_id": None, "level": 1, "role": role, "type": ROLE_ZH[role],
            "summary": clip(raw.get("summary"), 200),
            "status": (str(raw.get("status") or "summary").strip().lower() or "summary"),
            "evidence": ev, "evidence_ids": [e["id"] for e in ev], "verified": bool(ok)})
        if not ok:
            model["unverified"].append(nid)

    for node in model["nodes"]:                    # 断链挂回根，不丢节点
        if node["parent"] not in taken:
            model["dropped"].append({"from": node["parent"], "to": node["id"],
                                     "type": "hierarchy", "reason": "父节点不存在，已挂回 root"})
            node["parent"] = "root"
        node["parent_id"] = node["parent"]

    for pos, raw in enumerate([x for x in (draft.get("edges") or []) if isinstance(x, dict)], 1):
        src = str(raw.get("from") or raw.get("source") or "").strip()
        dst = str(raw.get("to") or raw.get("target") or "").strip()
        code = rel_of(raw.get("type") or raw.get("relation"))
        if not code or src not in taken or dst not in taken or src == dst:
            model["dropped"].append({"from": src, "to": dst,
                                     "type": code or str(raw.get("type") or ""),
                                     "reason": "端点或关系类型非法"})
            continue
        ev, ok = forge.evidence(raw.get("evidence"))
        if not ev:
            model["dropped"].append({"from": src, "to": dst, "type": code,
                                     "reason": "无证据，按规则不绘制"})
            continue
        model["edges"].append({"id": "r%d" % pos, "from": src, "to": dst, "source": src,
                               "target": dst, "type": code, "relation": REL_ZH[code],
                               "relation_en": code, "label": clip(raw.get("label"), 24) or REL_ZH[code],
                               "evidence": ev, "evidence_id": ev[0]["id"],
                               "evidence_ids": [e["id"] for e in ev], "grounded": bool(ok)})
    model["depth"], model["cycles"] = measure(model)
    return model


def char_w(ch):
    return 15.6 if ord(ch) > 0x2E7F else 8.4


def wrap_text(text, limit, max_lines=3):
    rows, cur, width = [], "", 0.0
    for ch in str(text or ""):
        step = char_w(ch)
        if width + step > limit and cur:
            rows.append(cur)
            cur, width = ch, step
        else:
            cur += ch
            width += step
    if cur:
        rows.append(cur)
    if len(rows) > max_lines:
        rows = rows[:max_lines]
        rows[-1] = rows[-1][:-1] + "…"
    return rows or [""]


def compose(model):
    """缩进树布局：一行一节点、一列一层，列宽取该层最宽标签，故框体互不重叠。"""
    pool = {"root": {"id": "root", "label": model["theme"]["label"] or "中心主题",
                     "parent": None, "level": 0, "role": "concept"}}
    for n in model["nodes"]:
        pool[n["id"]] = {"id": n["id"], "label": n["label"] or n["id"], "parent": n["parent"],
                         "level": n.get("level", 1), "role": n.get("role", "")}
    kids = {}
    for nid, node in pool.items():
        if nid != "root":
            kids.setdefault(node["parent"], []).append(nid)
    for node in pool.values():
        node["lines"] = wrap_text(node["label"], 250 if node["level"] == 0 else 205)
        node["w"] = max(84.0, max(sum(char_w(c) for c in ln) for ln in node["lines"]) + 28)
        node["h"] = len(node["lines"]) * 19 + 16

    order, seen = [], {"root"}

    def walk(nid):
        for child in kids.get(nid, []):
            if child in seen:
                continue
            seen.add(child)
            order.append(child)
            walk(child)

    walk("root")
    order += [n["id"] for n in model["nodes"] if n["id"] not in order]   # 成环/孤立也要上图

    col_w = {0: pool["root"]["w"]}
    for nid in order:
        lv = pool[nid]["level"]
        col_w[lv] = max(col_w.get(lv, 0.0), pool[nid]["w"])
    col_x, x = {}, 36.0
    for lv in sorted(col_w):
        col_x[lv] = x
        x += col_w[lv] + 46

    y, boxes = 36.0, {}
    for nid in order:
        node = pool[nid]
        boxes[nid] = (col_x[node["level"]], y, node["w"], node["h"])
        y += node["h"] + 12
    body = y - 12
    root_h = pool["root"]["h"]
    boxes["root"] = (36.0, max(36.0, (body + 36.0) / 2 - root_h / 2), pool["root"]["w"], root_h)

    curves = []
    for nid in order:
        par = pool[nid]["parent"]
        if par not in boxes:
            continue
        px, py, pw, ph = boxes[par]
        cx, cy, cw, ch = boxes[nid]
        a = (px + pw, py + ph / 2)
        b = (cx, cy + ch / 2)
        dx = max(20.0, (b[0] - a[0]) / 2)
        curves.append({"from": par, "to": nid, "type": "hierarchy", "label": "",
                       "d": [a, (a[0] + dx, a[1]), (b[0] - dx, b[1]), b]})
    right = max(v[0] + v[2] for v in boxes.values())
    for edge in model["edges"]:
        if edge["from"] not in boxes or edge["to"] not in boxes:
            continue
        sx, sy, sw, sh = boxes[edge["from"]]
        tx, ty, tw, th = boxes[edge["to"]]
        a = (sx + sw, sy + sh / 2)
        b = (tx + tw, ty + th / 2)
        gutter = right + 64                     # 关系线走右侧走廊，避免压住节点
        curves.append({"from": edge["from"], "to": edge["to"], "type": edge["type"],
                       "label": edge.get("label") or REL_ZH.get(edge["type"], ""),
                       "anchor": (gutter + 4, (a[1] + b[1]) / 2),
                       "d": [a, (gutter, a[1]), (gutter, b[1]), b]})
    return {"pool": pool, "kids": kids, "boxes": boxes, "curves": curves, "order": order,
            "w": round(right + 168, 1),
            "h": round(max(body, boxes["root"][1] + root_h) + 138, 1)}


def bezier(points, steps=18):
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = points
    out = []
    for i in range(steps + 1):
        t = i / steps
        m = 1 - t
        out.append((m ** 3 * x0 + 3 * m ** 2 * t * x1 + 3 * m * t ** 2 * x2 + t ** 3 * x3,
                    m ** 3 * y0 + 3 * m ** 2 * t * y1 + 3 * m * t ** 2 * y2 + t ** 3 * y3))
    return out


def collisions(boxes):
    """框体两两相交断言：布局策略上应恒为空。"""
    items = list(boxes.items())
    hits = []
    for i in range(len(items)):
        a_id, (ax, ay, aw, ah) = items[i]
        for j in range(i + 1, len(items)):
            b_id, (bx, by, bw, bh) = items[j]
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                hits.append([a_id, b_id])
    return hits


def map_contract(contract, context):
    filled = {}
    for key in (contract or {}):
        probe = "%s|%s" % (str(key).lower(), key)
        for pattern, slot in CONTRACT_RULES:
            if re.search(pattern, probe, re.I):
                filled[key] = context.get(slot)
                break
        else:
            filled[key] = {"note": "无专用产物，用通用交付摘要回填", "artifacts": context.get("files")}
    return filled


def finalize(result, contract, context, out_path, closing=None, extra=None):
    """先按契约逐键回填（缺值 [] ），再补固定字段与增量字段；契约同名键优先。"""
    payload = {"case_id": result.get("case_id"), "status": result.get("status")}
    for key, value in map_contract(contract, context).items():
        if key in ("case_id", "status"):
            continue
        payload[key] = value if value is not None else []
    for key in RESULT_FIXED:
        value = result.get(key)
        payload[key] = value if value is not None else []
    if closing:
        payload["runtime"] = dict(payload.get("runtime") or {}, **closing)
    if isinstance(extra, dict):
        for key, value in extra.items():
            if key not in ("case_id", "status"):
                payload.setdefault(key, value)
    dump(out_path, payload)
    return payload


def dump(path, obj):
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))
        return True
    except Exception:
        return False


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_bytes().decode("utf-8-sig"))
    except Exception:
        return default


# ---------------------------------------------------------------- 交付附件
def evidence_rows(model):
    """一行一条证据；无证据的节点也留一行，便于肉眼发现空洞。"""
    rows = []
    for node in (model or {}).get("nodes") or []:
        pool = node.get("evidence") or []
        if not pool:
            rows.append([node["id"], node["label"], node.get("parent"), node.get("level"),
                         node.get("role"), node.get("type"), node.get("status"),
                         "", "", "", "", "no"])
            continue
        for ev in pool:
            rows.append([node["id"], node["label"], node.get("parent"), node.get("level"),
                         node.get("role"), node.get("type"), node.get("status"), ev.get("id"),
                         ev.get("material"), ev.get("locator"), ev.get("quote"),
                         "yes" if ev.get("verified") else "no"])
    return rows


def write_evidence_csv(model, path):
    import csv
    import io
    header = ["node_id", "label", "parent_id", "level", "role", "type", "status",
              "evidence_id", "material", "locator", "quote", "verified"]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    rows = evidence_rows(model)
    writer.writerows(rows)
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\ufeff" + buf.getvalue(), encoding="utf-8")   # BOM 便于表格软件直开
    except Exception:
        pass
    return len(rows)


def pending_items(model, index, stats):
    items = []
    for nid in (model or {}).get("unverified") or []:
        items.append({"kind": "evidence_missing", "node": nid,
                      "question": "引文未逐字命中材料：请补原文片段或删除该节点"})
    for node in (model or {}).get("nodes") or []:
        if node.get("status") == "inference":
            items.append({"kind": "inference", "node": node["id"],
                          "question": "推断节点：请人工确认依据「%s」是否成立"
                                      % (node.get("summary") or "未填写")[:80]})
    for drop in (model or {}).get("dropped") or []:
        items.append({"kind": "edge_dropped", "edge": "%s→%s" % (drop["from"], drop["to"]),
                      "question": "关系 %s 未绘制（%s），需确认是否成立"
                                  % (drop["type"], drop["reason"])})
    for mat in (index or {}).get("materials") or []:
        if not mat.get("units"):
            items.append({"kind": "material_unreadable", "material": mat.get("id"),
                          "question": "%s（%s）无可用文本，需人工读图或补文本"
                                      % (mat.get("name"), mat.get("kind"))})
    if stats.get("nodes") and stats.get("verified_ratio", 0) < 1:
        items.append({"kind": "coverage_gap", "node": None,
                      "question": "证据覆盖率 %.0f%%，建议补到 100%%"
                                  % (100 * stats["verified_ratio"])})
    return items


def write_coverage(path, case_id, index, model, stats, items, reqs, probes, mode, stamp):
    """覆盖说明：给评审一张可核对的账，不写结论性口号。"""
    counts = {"达标": 0, "偏差": 0, "缺失": 0, "待定": 0}
    for item in items:
        counts[item.get("verdict")] = counts.get(item.get("verdict"), 0) + 1
    mats = (index or {}).get("materials") or []
    width = max([len([n for n in model["nodes"] if n.get("parent") == p]) for p in
                 {n.get("parent") for n in model["nodes"]}] or [0])
    lines = [
        "# 覆盖与结构说明（coverage_report）", "",
        "- 案例：`%s`　生成时间：%s" % (case_id or "未提供", stamp),
        "- 结构来源：%s" % ("Agent 工作稿" if mode == "agent" else "脚本确定性兜底"),
        "- 材料 %d 份，可抽文本单元 %d 个" % (len(mats), sum(len(m.get("units") or []) for m in mats)),
        "", "## 1. 结构账", "",
        "| 指标 | 数值 | 口径 |", "|---|---|---|",
        "| 节点 | %d | 含 %d 个主分支 |" % (stats["nodes"], stats.get("branches", 0)),
        "| 跨分支关系 | %d | 只保留有引文支撑的关系 |" % stats["edges"],
        "| 最大层级 | %d | root 计第 0 层，建议 ≤4 |" % stats["depth"],
        "| 证据覆盖率 | %.0f%% | %d/%d 节点有逐字命中证据 |"
        % (100 * stats.get("verified_ratio", 0), stats.get("verified_nodes", 0), stats["nodes"]),
        "| 未绘制关系 | %d | 逐条列在 pending_human.json |" % stats.get("dropped", 0),
        "", "## 2. 七类节点覆盖", "", "| 类型 | 数量 | 状态 |", "|---|---|---|"]
    for code in ROLE_CODES:
        if code == "subtopic":
            continue
        num = (stats.get("roles") or {}).get(code, 0)
        lines.append("| %s | %d | %s |" % (ROLE_ZH[code], num, "已覆盖" if num else "材料未给或未建节点"))
    lines += ["", "## 3. 任务要求覆盖", "", "| 要求 | 来源 | 判定 | 实际 |", "|---|---|---|---|"]
    for req in reqs:
        lines.append("| %s | %s | %s | %s |" % (req["key"], req["source"], req["verdict"], req["actual"]))
    covered = sum(1 for r in reqs if r["verdict"] == "covered")
    lines += ["", "要求覆盖 %d/%d；missing 项同时写入 pending_human.json。" % (covered, len(reqs)),
              "", "## 4. 规模与折叠策略", "",
              "- 规模纪律：节点 15–40，单一父节点下 ≤7 个子节点，深度 ≤4。",
              "- 折叠方式：超限时按材料主题聚类合并同级，保留可追溯的代表节点；被折叠的原始段落仍在 index.json 中可查。",
              "- 本案例：节点 %d，最宽分支 %d 个子节点，深度 %d。" % (stats["nodes"], width, stats["depth"]),
              "", "## 5. 金标准对照", "", "| 判定 | 数量 |", "|---|---|"]
    for key in ("达标", "偏差", "缺失", "待定"):
        lines.append("| %s | %d |" % (key, counts.get(key, 0)))
    lines += ["", "逐项期望、实际与出处见 `audit_report.json` 的 `diff[]`。",
              "", "## 6. 预览", "",
              "- 预览模式：`%s`；SVG 是唯一可编辑源，节点文字在 text/tspan 内。" % (mode or "none"),
              "", "## 7. 复核步骤", "",
              "1. 打开 `node_evidence.csv`，逐行把 quote 贴回原文检索，确认 locator 一致。",
              "2. 打开 `mindmap.json`，抽查 `edges[].relation` 的方向是否符合「因→果 / 证据→论断」等语义。",
              "3. 浏览器打开 `mindmap.svg`，改任一节点文字，确认可编辑、无外链字体。",
              "4. 重跑 `build`，`audit_report.json` 各项计数应可复现。",
              "", "## 8. 探针与降级", ""]
    if probes:
        for row in probes:
            lines.append("- %s：exit=%s，result 合法=%s，状态=%s"
                         % (row.get("name"), row.get("exit_code"), row.get("result_valid"), row.get("status")))
    else:
        lines.append("- 本轮未跑空输入/坏 JSON 探针（`--no-probe`）。")
    text = "\n".join(lines) + "\n"
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except Exception:
        pass
    return len(text)

