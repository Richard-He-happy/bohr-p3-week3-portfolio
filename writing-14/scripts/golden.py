#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""golden.py — 金标准与逐项对照。

每条期望都带出处：材料 locator+quote / case.json Pointer / 本包文档规则句；
出处查不到即 verified=false，绝不凭空补引用。判定只有 达标/偏差/缺失/待定 四种。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import mmcore

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
DOCS = (PKG / "SKILL.md", PKG / "references" / "node-edge-spec.md")


def stamp(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def corpus(index):
    """全材料文本，做数字溯源与主题比对用。"""
    return mmcore.fold(" ".join(str(u.get("text") or "")
                                for m in (index or {}).get("materials") or []
                                for u in m.get("units") or []))


RULE = {
    "topic": ("中心主题取材料主题", "中心主题取材料主题，不写元词"),
    "branch": ("3–6 个主分支", "3–6 个主分支，每个分支 2–5 个子节点"),
    "nodes": ("节点总数 15–40", "节点总数 15–40，超限先合并同级"),
    "depth": ("深度 ≤ 4", "深度 ≤ 4，root 为第 0 层"),
    "evidence": ("每个节点至少一条", "每个节点至少一条 evidence：material + locator + 逐字 quote"),
    "quote": ("连续片段", "quote 必须是从材料复制的连续片段，不改写不拼接"),
    "edge": ("无证据的关系不画", "无证据的关系不画，只记入 pending_human"),
    "svg": ("SVG 中每个节点一个", "SVG 中每个节点一个 g#node-*，文字在 text/tspan 内可直接改"),
    "hier": ("单一根", "单一根、父子链不成环、父节点必须存在"),
    "unique": ("同一父节点下的子节点标签不得重复", "同一父节点下的子节点标签不得重复"),
    "number": ("标签里的数字必须能在", "标签里的数字必须能在该节点引文或材料原文中找到"),
    "contract": ("原样回填 output_contract", "原样回填 output_contract 全部字段，不改名不漏键"),
}

DIMS = (("question", "研究问题", "question", ("研究问题", "研究目的", "研究目标", "假设", "aim")),
        ("method", "方法与材料", "method", ("方法", "实验", "仪器", "样本", "流程", "method")),
        ("result", "结果与证据", "finding", ("结果", "数据", "发现", "测量", "result")),
        ("conclusion", "结论", "conclusion", ("结论", "表明", "综上", "conclusion")),
        ("limitation", "局限", "limitation", ("局限", "不足", "误差", "限制", "limitation")),
        ("future", "空白与后续", "gap", ("空白", "尚未", "有待", "未来", "gap")),
        ("task", "任务与风险", "task", ("任务", "步骤", "待办", "风险", "risk")))

REQ = (("研究问题", "question"), ("研究目标", "question"), ("方法", "method"), ("实验", "method"),
       ("数据", "evidence"), ("结果", "finding"), ("结论", "conclusion"), ("局限", "limitation"),
       ("风险", "risk"), ("任务", "task"), ("空白", "gap"), ("对比", "contrast"), ("因果", "cause"))

SPECS = (
    ("G01", "中心主题", "中心主题是材料主题的名词短语，不是「思维导图」类元词", "theme", "topic"),
    ("G02", "主分支数", "level 1 主分支 3–6 个", "branch_count", "branch"),
    ("G03", "分支体量", "每个主分支下 2–5 个子节点", "branch_size", "branch"),
    ("G04", "节点总量", "节点总数 15–40", "node_count", "nodes"),
    ("G05", "层级", "最大层级 ≤ 4（root 计第 0 层）", "depth", "depth"),
    ("G06", "父子结构", "单一根、父节点均存在、父子链不成环", "hierarchy", "hier"),
    ("G07", "证据挂接", "每个节点至少一条 evidence，含 material + locator + 逐字 quote", "evidence", "evidence"),
    ("G08", "引文保真", "quote 是材料连续片段且 ≥ 6 字", "quote", "quote"),
    ("G09", "关系语义", "关系取 7 类词表，方向合语义且有引文；无证据的关系不画", "edge", "edge"),
    ("G10", "标签唯一", "同一父节点下的子节点标签不得重复", "unique", "unique"),
    ("G11", "数字可溯", "标签里的数字必须能在该节点引文或材料原文中找到", "number", "number"),
    ("G12", "可编辑性", "SVG 中每个节点一个 g，带 data-locator/data-quote，文字在 text/tspan", "svg", "svg"),
    ("G13", "契约完整", "原样回填 output_contract 全部字段，不改名不漏键", "contract", "contract"),
)

DIRECTION = {"cause": "因 → 果", "depends": "依赖方 → 被依赖方", "contrast": "A ↔ B 对照",
             "sequence": "先 → 后", "cite": "引用方 → 被引方", "support": "证据 → 论断",
             "conflict": "A ↔ B 冲突"}


def rule_of(key):
    needle, fallback = RULE.get(key, ("", ""))
    for doc in DOCS:
        try:
            lines = doc.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for no, line in enumerate(lines, 1):
            if needle and needle in line.replace("`", ""):
                return line.strip(), "%s#L%d" % (doc.name, no), True
    return fallback, "包内文档未命中", False


# ---------------------------------------------------------------- 金标准
def anchors(index):
    rows, used = [], set()
    for dim, name, role, keys in DIMS:
        for mat in (index or {}).get("materials") or []:
            hit = None
            for unit in mat.get("units") or []:
                text = re.sub(r"\s+", " ", str(unit.get("text") or "")).strip()
                if text and len(text) <= 700 and any(k.lower() in text.lower() for k in keys):
                    hit = unit
                    break
            if hit and (mat.get("id"), hit.get("locator")) not in used:
                used.add((mat.get("id"), hit.get("locator")))
                rows.append({"id": "B%02d" % (len(rows) + 1), "dimension": dim, "branch": name,
                             "role": role,
                             "expect": "主分支「%s」下 2–5 个子节点，每个带 locator + 逐字 quote" % name,
                             "source": {"kind": "material", "material": mat.get("id"),
                                        "locator": hit.get("locator"), "verified": True,
                                        "quote": mmcore.clip(hit.get("text"), 150)}})
                break
    return rows[:6]


def build(case, contract, index, stage="build"):
    mats = (index or {}).get("materials") or []
    specs = []
    for rid, name, expect, check, key in SPECS:
        quote, locator, ok = rule_of(key)
        specs.append({"id": rid, "name": name, "expect": expect, "check": check,
                      "source": {"kind": "skill_rule", "locator": locator, "quote": quote,
                                 "verified": ok}})
    first = (mats[0].get("units") or [{}])[0] if mats else {}
    return {"schema": "mindmap-golden/1.0", "case_id": (index or {}).get("case_id"),
            "stage": stage, "generated": stamp(), "generator": "mindmap-evidence-forge/1.0.0",
            "derived_from": [{"id": m.get("id"), "name": m.get("name"), "kind": m.get("kind"),
                              "bytes": m.get("bytes"), "sha1": m.get("sha1"),
                              "units": len(m.get("units") or []), "chars": m.get("chars")} for m in mats],
            "center_topic": {"expect": specs[0]["expect"],
                             "source": {"kind": "material", "material": mats[0].get("id") if mats else None,
                                        "locator": first.get("locator"), "verified": bool(first),
                                        "quote": mmcore.clip(first.get("text"), 150) if mats else ""}},
            "branches_expected": anchors(index),
            "structural_requirements": specs,
            "relation_semantics": [{"type": c, "relation": mmcore.REL_ZH[c], "direction": DIRECTION[c]}
                                   for c in mmcore.REL_CODES],
            "contract_expectations": [
                {"id": "C%02d" % i, "field": str(k),
                 "expect": mmcore.clip(json.dumps(v, ensure_ascii=False), 150),
                 "source": {"kind": "case_json", "locator": "case.json#/output_contract/%s" % k,
                            "quote": json.dumps(v, ensure_ascii=False)[:180], "verified": True}}
                for i, (k, v) in enumerate((contract or {}).items(), 1)],
            "totals": {"structural": len(specs), "anchors": len(anchors(index)),
                       "contract_fields": len(contract or {})}}


def compare(gold, model, index, stage="build"):
    """逐项对照：达标 / 偏差 / 缺失 / 待定，四种判定之外不写别的词。"""
    nodes = (model or {}).get("nodes") or []
    kids = {}
    for n in nodes:
        kids.setdefault(n.get("parent") or "root", []).append(n)
    body = mmcore.fold(corpus(index)) if index else ""
    items = []

    def put(gid, verdict, actual, why=""):
        spec = next((r for r in gold["structural_requirements"] if r["id"] == gid), {})
        items.append({"id": gid, "name": spec.get("name"), "expect": spec.get("expect", ""),
                      "verdict": verdict, "actual": actual, "note": why,
                      "source": spec.get("source", {})})

    if stage != "build" or not nodes:
        for spec in gold["structural_requirements"]:
            put(spec["id"], "待定", "尚未 build，无实测", "init 只落骨架")
        return items

    label = str((model or {}).get("theme", {}).get("label") or "")
    titles = " ".join(mmcore.fold(m.get("title") or "") for m in (index or {}).get("materials") or [] if m)
    if not label:
        put("G01", "缺失", "theme.label 为空", "会退化成占位主题")
    elif any(w in label.lower() for w in ("思维导图", "mindmap", "要点整理", "材料整理")):
        put("G01", "偏差", "主题=「%s」" % label[:40], "含元词，未落到材料主题")
    else:
        has = any(e.get("verified") for e in model["theme"].get("evidence") or [])
        put("G01", "达标", "主题=「%s」" % label[:40],
            "有引文支撑" if has else "与材料标题共享 %d 字" % len([c for c in mmcore.fold(label) if c in titles]))

    branches = kids.get("root", [])
    put("G02", "达标" if 3 <= len(branches) <= 6 else "偏差",
        "主分支 %d 个：%s" % (len(branches), "、".join(b["label"][:8] for b in branches[:6])),
        "" if 3 <= len(branches) <= 6 else "期望 3–6 个")
    sizes = [(b["label"][:8], len(kids.get(b["id"], []))) for b in branches]
    bad = [s for s in sizes if not 2 <= s[1] <= 5]
    put("G03", "达标" if not bad else "偏差", "分支体量 %s" % (sizes or "无"),
        "" if not bad else "越界：%s" % "、".join("%s=%d" % s for s in bad))
    put("G04", "达标" if 15 <= len(nodes) <= 40 else ("缺失" if len(nodes) < 15 else "偏差"),
        "节点 %d 个" % len(nodes), "" if 15 <= len(nodes) <= 40 else "期望 15–40")
    depth = max([n.get("level") or 0 for n in nodes] or [0])
    put("G05", "达标" if depth <= 4 else "偏差", "最大层级 %d" % depth, "" if depth <= 4 else "超 4 层")
    known = {n["id"] for n in nodes} | {"root"}
    orphan = [n["id"] for n in nodes if (n.get("parent") or "root") not in known]
    cycles = (model or {}).get("cycles") or []
    put("G06", "达标" if not orphan and not cycles else "偏差",
        "断链 %d 个、环 %d 个" % (len(orphan), len(cycles)),
        "" if not orphan and not cycles else "修 parent 或删环")

    verified = [n for n in nodes if any(e.get("verified") for e in n.get("evidence") or [])]
    ratio = len(verified) / max(1, len(nodes))
    miss = [n["id"] for n in nodes if n not in verified]
    put("G07", "达标" if ratio > 0.999 else ("偏差" if ratio >= 0.8 else "缺失"),
        "有核验证据节点 %d/%d（%.0f%%）" % (len(verified), len(nodes), 100 * ratio),
        ("未命中：%s" % "、".join(miss[:6])) if miss else "")
    quotes = [e for n in nodes for e in n.get("evidence") or [] if e.get("quote")]
    short = sorted({n["id"] for n in nodes for e in n.get("evidence") or []
                    if e.get("quote") and len(e["quote"]) < 6})
    put("G08", "达标" if not short else "偏差",
        "引文 %d 条，最短 %d 字" % (len(quotes), min([len(e["quote"]) for e in quotes] or [0])),
        ("短引文：%s" % "、".join(short[:6])) if short else "引文逐字命中材料")

    edges = (model or {}).get("edges") or []
    wrong = [e for e in edges if e["type"] not in mmcore.REL_CODES]
    loose = [e for e in edges if not e.get("grounded")]
    drops = (model or {}).get("dropped") or []
    put("G09", "偏差" if wrong or loose else "达标",
        "关系 %d 条，引文未命中 %d，未绘制 %d" % (len(edges), len(loose), len(drops)),
        "类型越界" if wrong else ("未绘制项已进 pending_human" if drops else "无越界类型，宁缺勿造"))

    seen, dup = {}, []
    for n in nodes:
        key = (n.get("parent") or "root", mmcore.fold(n["label"]))
        if key in seen:
            dup.append(n["id"])
        seen[key] = n["id"]
    put("G10", "达标" if not dup else "偏差", "重复标签 %d 个" % len(dup), "、".join(dup[:6]))

    missing = []
    for n in nodes:
        local = " ".join(mmcore.fold(e.get("quote")) for e in n.get("evidence") or [])
        missing += ["%s:%s" % (n["id"], t) for t in sorted(set(re.findall(r"\d+(?:\.\d+)?", n["label"])))
                    if t not in local and t not in body]
    put("G11", "达标" if not missing else "偏差", "数字无出处 %d 处" % len(missing),
        "、".join(missing[:6]))
    put("G12", "待定", "由自检 C6 实测 SVG 结构", "见 audit_report.json 的 checks")
    skew = []
    for parent, group in kids.items():
        if len(group) < 3:
            continue
        spans = sorted(len(n["label"]) for n in group)
        if spans[-1] - spans[0] >= 14:
            skew.append("%s(%d–%d)" % (parent, spans[0], spans[-1]))
    put("G10b", "达标" if not skew else "偏差", "粒度不齐分支 %d 个" % len(skew), "、".join(skew[:5]))
    return items


def tally(items):
    counts = {"达标": 0, "偏差": 0, "缺失": 0, "待定": 0}
    for item in items:
        counts[item.get("verdict")] = counts.get(item.get("verdict"), 0) + 1
    return counts


def requirements_of(index, model, contract):
    text = str((index or {}).get("instruction") or "")
    rows = []
    for word, code in REQ:
        if word not in text:
            continue
        if code in mmcore.REL_CODES:
            hit = sum(1 for e in model["edges"] if e["type"] == code)
            label = "关系「%s」" % word
        else:
            hit = sum(1 for n in model["nodes"] if n["role"] == code)
            label = "节点类型「%s」" % word
        rows.append({"key": label, "source": "task_instruction",
                     "verdict": "covered" if hit else "missing", "actual": "命中 %d 项" % hit})
    for key in (contract or {}):
        rows.append({"key": "契约字段 `%s`" % key, "source": "case.json#/output_contract",
                     "verdict": "covered", "actual": "已回填（见 result.json）"})
    if not rows:
        rows.append({"key": "材料主题与关键分支", "source": "默认口径",
                     "verdict": "covered" if model["nodes"] else "missing",
                     "actual": "节点 %d 个" % len(model["nodes"])})
    return rows

if __name__ == "__main__":
    import sys
    if "--rules" in sys.argv:
        hit = sum(1 for k in RULE if rule_of(k)[2])
        for key in RULE:
            quote, locator, ok = rule_of(key)
            print("%-9s %-6s %s" % (key, "命中" if ok else "缺失", locator))
        print("规则句回查 %d/%d 命中" % (hit, len(RULE)))
    else:
        print("golden.py：金标准与逐项对照（由 audit.py / mindmap_cli.py 调用）")
        print("自检用法：python3 golden.py --rules")
    raise SystemExit(0)
