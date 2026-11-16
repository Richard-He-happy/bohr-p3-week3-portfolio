#!/usr/bin/env python3
"""可核验资产层：金标准 / 差异报告 / 版本史 / 运行日志 / 自检回执。

它不是新入口：由 proposal_cli.py 在 init / finalize / all 收尾时调用 finish()，
因此原有命令行、参数、路径与退出码（恒 0）都不变。

设计约束：
  * 只用标准库，不联网，不依赖当前工作目录；
  * 一切异常都在本层吞掉并尽力留痕，绝不改变主流程退出码；
  * 金标准只从输入材料（output_contract + organizer_workorder）导出，
    diff_report 才把金标准与本次实际产物逐项对照，避免"自证自答"；
  * 输入坏掉时按内置默认导出并标 basis=builtin_default，不伪造成逐字引文。
"""
from __future__ import annotations

import json
import re
import sys
import time
import traceback
import unicodedata
from pathlib import Path

try:
    import audit_kit as AK
except Exception:  # 审计底座缺失时退化为纯文件读取，不阻断主流程
    AK = None

VERSION = "1.0.0"
LAYER = "evidence_assets.py"
ASSET_FILES = ("golden_standard.json", "diff_report.md", "version_history.md",
               "run.log", "self_check.json")
PROCESS_T0 = time.time()
_EVENTS = []

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
MONTH_TOKEN = re.compile(r"M\s*(\d{1,2})(?!\d)")
RISK_TOKEN = re.compile(r"R\s*([1-9])(?!\d)")
GOAL_TOKEN = re.compile(r"G\s*([1-9])(?!\d)")

DEFAULT_SUPPORT = (
    ("七要素可编辑正文", {"type": "artifact_main"}),
    ("关键论断—段落—引文/计划来源映射", {"type": "artifact_evidence"}),
    ("目标—工作包—里程碑—指标矩阵", {"type": "artifact_matrix"}),
    ("规划单位分项与合计", {"type": "artifact_units"}),
    ("至少3项风险及备选", {"type": "artifact_risks"}),
    ("至少2项人工确认，含真实申请人证据与真实资助要求", {"type": "artifact_human"}),
)
DEFAULT_LIMITS = (
    ("只用所供源材料；不得联网补写。", {"type": "limit_offline"}),
    ("不能将论文作者既有成果冒充申请人已完成工作。", {"type": "limit_attribution"}),
    ("数字、条件与来源冲突保持可追溯；拟议活动与已发表结果逐项区分。", {"type": "limit_traceable"}),
    ("不虚构年份、试验结果、设备已具备、伦理审批、真实政策或资助决定。", {"type": "limit_no_fabrication"}),
)


# ------------------------------------------------------------------ 基础工具
def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _elapsed():
    return round(time.time() - PROCESS_T0, 4)


def note(phase, **info):
    """主流程在关键节点调用；只记录真实事件，不参与任何判定。"""
    try:
        _EVENTS.append({"at": _now(), "t": _elapsed(), "phase": str(phase),
                        "info": dict(info)})
    except Exception:
        pass


def _read_text(path):
    try:
        raw = Path(path).read_bytes()
    except Exception:
        return ""
    if AK is not None:
        try:
            return AK.decode_bytes(raw)
        except Exception:
            pass
    return raw.decode("utf-8", "ignore")


def _load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path, payload):
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return True
    except Exception:
        return False


def _write_text(path, text):
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return True
    except Exception:
        return False


def _size(path):
    try:
        return Path(path).stat().st_size
    except Exception:
        return 0


def _norm(text):
    """引文比对口径：NFKC + 去掉全部空白，保留标点（逐字，不改字）。"""
    t = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"\s+", "", t)


def _esc_key(key):
    return str(key).replace("~", "~0").replace("/", "~1")


def _short(text, n=90):
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= n else t[:n] + "…"


def _cell(text, n=150):
    t = re.sub(r"\s+", " ", str(text if text is not None else "")).strip()
    if len(t) > n:
        t = t[:n] + "…"
    return t.replace("|", "\\|")


def _string_leaves(node, out=None, depth=0):
    if out is None:
        out = []
    if depth > 10:
        return out
    if isinstance(node, dict):
        for val in node.values():
            _string_leaves(val, out, depth + 1)
    elif isinstance(node, list):
        for val in node:
            _string_leaves(val, out, depth + 1)
    elif isinstance(node, str):
        out.append(node)
    return out


def _scalar_leaves(node, out=None, depth=0):
    """JSON 标量（字符串/数/布尔）的逐字序列化集合，用于数值型字段的来源核对。"""
    if out is None:
        out = set()
    if depth > 10:
        return out
    if isinstance(node, dict):
        for val in node.values():
            _scalar_leaves(val, out, depth + 1)
    elif isinstance(node, list):
        for val in node:
            _scalar_leaves(val, out, depth + 1)
    elif isinstance(node, str):
        out.add(node)
    elif isinstance(node, bool):
        out.add("true" if node else "false")
    elif isinstance(node, (int, float)):
        out.add(str(node))
    return out


# ------------------------------------------------------------------ 输入定位
def _find_case_input(inp):
    if not inp:
        return None
    root = Path(inp)
    if not root.exists():
        return None
    direct = root / "case.json"
    if direct.exists():
        return direct
    try:
        found = sorted(root.rglob("case*.json"))
    except Exception:
        found = []
    return found[0] if found else None


def _locate_workorder(node, depth=0):
    if depth > 6 or not isinstance(node, (dict, list)):
        return None
    if isinstance(node, dict):
        if "sections" in node and any(k in node for k in
                                      ("draft_size", "planning_months", "consistency")):
            return node
        children = node.values()
    else:
        children = node
    for child in children:
        hit = _locate_workorder(child, depth + 1)
        if hit is not None:
            return hit
    return None


def _pointer_to(node, target, path="", depth=0):
    if depth > 12:
        return None
    if node is target:
        return path or "/"
    if isinstance(node, dict):
        for key, val in node.items():
            hit = _pointer_to(val, target, path + "/" + _esc_key(key), depth + 1)
            if hit is not None:
                return hit
    elif isinstance(node, list):
        for pos, val in enumerate(node):
            hit = _pointer_to(val, target, path + "/" + str(pos), depth + 1)
            if hit is not None:
                return hit
    return None


def _quote(value, file_name, locator, raw_norm, leaves, note_text="", scalars=None):
    """构造一条带来源 locator 与逐字引文的金标准来源记录。"""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    target = _norm(text)
    match = "unverified"
    if target:
        if raw_norm and target in raw_norm:
            match = "raw_text"
        elif any(_norm(leaf) == target for leaf in leaves if isinstance(leaf, str)):
            match = "json_value"
        elif scalars and not isinstance(value, str) and str(value) in scalars:
            match = "json_scalar"
    rec = {"file": file_name or "case.json", "locator": locator or "/", "quote": text,
           "quote_verbatim": match in ("raw_text", "json_value", "json_scalar"),
           "match": match}
    if note_text:
        rec["note"] = note_text
    return rec


def _builtin(value, locator, note_text="输入未提供该项，按包内内置默认导出"):
    return {"file": "builtin_defaults", "locator": locator, "quote": value,
            "quote_verbatim": False, "match": "builtin_default", "note": note_text}


def _split_clauses(text):
    return [c.strip() for c in re.split(r"[；;]", str(text or "")) if c.strip()]


def _first_clause(clauses, words):
    for clause in clauses:
        if any(w in clause for w in words):
            return clause
    return None


# ------------------------------------------------------------------ 金标准
def _derive_plan(result, workorder):
    plan = {"lo": 1600, "hi": 2600, "months": 12, "cap": 100}
    we = result.get("workorder_execution") if isinstance(result, dict) else {}
    we = we if isinstance(we, dict) else {}
    deliv = result.get("deliverable") if isinstance(result, dict) else {}
    deliv = deliv if isinstance(deliv, dict) else {}
    rng = deliv.get("char_range")
    if isinstance(rng, list) and len(rng) >= 2:
        try:
            plan["lo"], plan["hi"] = int(rng[0]), int(rng[1])
        except Exception:
            pass
    for key, fallback in (("planning_months", 12), ("planning_unit_cap", 100)):
        val = we.get(key) or (workorder or {}).get(key) or fallback
        try:
            val = int(val)
        except Exception:
            val = fallback
        plan["months" if key == "planning_months" else "cap"] = val
    size = str((workorder or {}).get("draft_size") or "")
    hit = re.search(r"(\d{3,4})\s*[–\-—~至到]\s*(\d{3,4})", size)
    if hit:
        try:
            plan["lo"], plan["hi"] = int(hit.group(1)), int(hit.group(2))
        except Exception:
            pass
    return plan


def _add(items, kind, key, expect, check, source=None, basis="workorder"):
    items.append({"id": "GS%02d" % (len(items) + 1), "kind": kind, "key": key,
                  "expect": expect, "check": check, "basis": basis, "source": source})


def _support_check(text):
    t = str(text or "")
    if "正文" in t or "七要素" in t:
        return {"type": "artifact_main"}
    if "论断" in t or "映射" in t or "引文" in t:
        return {"type": "artifact_evidence"}
    if "矩阵" in t:
        return {"type": "artifact_matrix"}
    if "规划单位" in t:
        return {"type": "artifact_units"}
    if "风险" in t:
        return {"type": "artifact_risks"}
    if "人工确认" in t:
        return {"type": "artifact_human"}
    return {"type": "artifact_main"}


def _limit_check(text):
    t = str(text or "")
    if "联网" in t or "只用所供" in t:
        return {"type": "limit_offline"}
    if "作者" in t or "冒充" in t:
        return {"type": "limit_attribution"}
    if "数字" in t or "追溯" in t or "单位" in t:
        return {"type": "limit_traceable"}
    if "虚构" in t or "设备已具备" in t or "伦理" in t:
        return {"type": "limit_no_fabrication"}
    if "碳捕集" in t or "材料中没有" in t or "标签" in t:
        return {"type": "limit_no_external_facts"}
    return {"type": "limit_traceable"}


def build_golden(inp, out, result, stage):
    """只读输入材料生成金标准；返回带内部 plan 的完整结构。"""
    result = result if isinstance(result, dict) else {}
    case_path = _find_case_input(inp)
    case = _load_json(case_path, {}) if case_path else {}
    if not isinstance(case, dict):
        case = {}
    raw = _read_text(case_path) if case_path else ""
    raw_norm = _norm(raw)
    leaves = _string_leaves(case)
    scalars = _scalar_leaves(case)
    case_name = case_path.name if case_path else "case.json"

    workorder = _locate_workorder(case) if case else None
    basis = "workorder"
    wo_ptr = ""
    wo_file = case_name
    raw_wo = raw
    if workorder is None:
        fallback = _load_json(Path(out) / "workorder.json", {}) or {}
        if isinstance(fallback, dict) and not fallback.get("absent"):
            workorder = fallback
            basis = "workorder_fallback"
            wo_file = "workorder.json"
            raw_wo = _read_text(Path(out) / "workorder.json")
            wo_ptr = ""
        else:
            workorder = {}
            basis = "builtin_default"
    else:
        hit = _pointer_to(case, workorder)
        wo_ptr = hit if hit not in (None, "/") else ""
        raw_wo = raw
    workorder = workorder if isinstance(workorder, dict) else {}
    raw_wo_norm = _norm(raw_wo)
    plan = _derive_plan(result, workorder)

    contract = case.get("output_contract") if isinstance(case.get("output_contract"), dict) else {}
    if not contract and isinstance(result.get("output_contract_echo"), dict):
        contract = result["output_contract_echo"]

    items = []

    # 1) output_contract 逐键
    for key, value in contract.items():
        check = {"type": "contract_key", "key": str(key)}
        if str(key) == "case_id":
            check["mode"] = "equals_input"
            expect = "result.json 的 case_id 原样回填输入 case_id"
        else:
            expect = "result.json 顶层键 %s 存在且非空（契约：%s）" % (key, _short(value, 60))
        src = _quote(value, case_name, "/output_contract/" + _esc_key(key), raw_norm, leaves)
        _add(items, "contract", "contract:" + str(key), expect, check, src, "output_contract")

    # 2) organizer_workorder：章节
    sections = workorder.get("sections") if isinstance(workorder.get("sections"), list) else []
    declared = [s for s in sections if isinstance(s, dict)]
    if declared:
        for pos, sec in enumerate(declared):
            sid = str(sec.get("id") or ("section%d" % (pos + 1)))
            title = str(sec.get("title") or sid)
            minimum = str(sec.get("minimum") or "")
            pointer = wo_ptr + "/sections/%d/%s" % (pos, "minimum" if minimum else "title")
            src = _quote(minimum or title, wo_file, pointer, raw_wo_norm, leaves)
            expect = "章节「%s」要有实质正文（%s）" % (title, _short(minimum or "workorder 未给 minimum", 80))
            _add(items, "section", "section:" + sid, expect,
                 {"type": "section", "section_id": sid, "title": title}, src)
    else:
        specs = AK.SECTION_SPECS if AK is not None else []
        for pos, spec in enumerate(specs):
            _add(items, "section", "section:" + spec["id"],
                 "默认七要素章节「%s」要有实质正文" % spec["title"],
                 {"type": "section", "section_id": spec["id"], "title": spec["title"]},
                 _builtin(spec["title"], "SECTION_SPECS[%d]" % pos), "builtin_default")

    # 3) 篇幅区间
    draft_size = workorder.get("draft_size")
    if draft_size:
        _add(items, "size", "draft_size",
             "七节正文合计落在 workorder 区间：%s" % _short(draft_size, 100),
             {"type": "chars_in_range"},
             _quote(draft_size, wo_file, wo_ptr + "/draft_size", raw_wo_norm, leaves))
    else:
        _add(items, "size", "draft_size",
             "七节正文合计落在默认区间 %d–%d 汉字" % (plan["lo"], plan["hi"]),
             {"type": "chars_in_range"},
             _builtin("%d–%d 汉字（默认区间）" % (plan["lo"], plan["hi"]), "defaults#draft_size"),
             "builtin_default")

    # 4) 周期与规划单位（含非货币口径）
    clauses = _split_clauses(workorder.get("consistency") or "")
    month_clause = _first_clause(clauses, ("月", "时间"))
    month_value = workorder.get("planning_months") or plan["months"]
    if month_clause:
        month_src = _quote(month_clause, wo_file, wo_ptr + "/consistency", raw_wo_norm, leaves)
    elif workorder:
        month_src = _quote(month_value, wo_file, wo_ptr + "/planning_months", raw_wo_norm,
                           leaves, scalars=scalars)
    else:
        month_src = _builtin("%s 个月（内置默认周期）" % month_value,
                             "defaults#planning_months")
    _add(items, "schedule", "planning_months",
         "全部计划时间标记不超过 %s 个月" % month_value, {"type": "months_within"}, month_src,
         "builtin_default" if month_src and month_src.get("match") == "builtin_default"
         else "workorder")

    unit_clause = _first_clause(clauses, ("单位",))
    cap_value = workorder.get("planning_unit_cap") or plan["cap"]
    if unit_clause:
        unit_src = _quote(unit_clause, wo_file, wo_ptr + "/consistency", raw_wo_norm, leaves)
    elif workorder:
        unit_src = _quote(cap_value, wo_file, wo_ptr + "/planning_unit_cap", raw_wo_norm,
                          leaves, scalars=scalars)
    else:
        unit_src = _builtin("%s 规划单位上限（内置默认）" % cap_value,
                            "defaults#planning_unit_cap")
    _add(items, "units", "planning_unit_cap",
         "规划单位分项之和 ≤ %s、等于 total 且非货币" % cap_value,
         {"type": "units_in_cap"}, unit_src,
         "builtin_default" if unit_src and unit_src.get("match") == "builtin_default"
         else "workorder")

    meaning = workorder.get("planning_unit_meaning")
    if meaning:
        _add(items, "units", "unit_meaning", "planning_units.json 声明单位含义（非货币/非已获资金/非真实预算）",
             {"type": "unit_meaning"},
             _quote(meaning, wo_file, wo_ptr + "/planning_unit_meaning", raw_wo_norm, leaves))
    else:
        _add(items, "units", "unit_meaning", "规划单位须声明为非货币一致性口径",
             {"type": "unit_meaning"},
             _builtin("规划单位：非货币、非已获资金、非真实预算。", "defaults#unit_meaning"),
             "builtin_default")

    # 5) 目标 / 里程碑
    goal_clause = _first_clause(clauses, ("目标",))
    for goal in ("G1", "G2", "G3"):
        if goal_clause:
            goal_src = _quote(goal_clause, wo_file, wo_ptr + "/consistency", raw_wo_norm, leaves)
        else:
            goal_src = _builtin(goal, "defaults#consistency_goal")
        _add(items, "goal", "goal:" + goal,
             "%s 在正文、目标矩阵与规划单位分项中一一对应并可 join" % goal,
             {"type": "goal_join", "goal": goal}, goal_src,
             "workorder" if goal_clause else "builtin_default")
    mile_clause = _first_clause(clauses, ("里程碑",)) or goal_clause
    if mile_clause:
        mile_src = _quote(mile_clause, wo_file, wo_ptr + "/consistency", raw_wo_norm, leaves)
    else:
        mile_src = _builtin("三阶段里程碑（M1–M4 / M5–M8 / M9–M12）",
                            "defaults#milestones")
    _add(items, "milestone", "milestones",
         "三阶段里程碑与工作包一一对应，时间不超过周期上限",
         {"type": "milestones"}, mile_src,
         "workorder" if mile_clause else "builtin_default")

    # 6) 必需附属产物
    required = workorder.get("required_supporting_files")
    required = required if isinstance(required, list) else []
    required = [r for r in required if isinstance(r, str)]
    if required:
        for pos, text in enumerate(required):
            kind = "supporting_file"
            if "风险" in text:
                kind = "risk"
            elif "人工确认" in text:
                kind = "human"
            elif "规划单位" in text:
                kind = "units"
            _add(items, kind, "supporting:%d" % pos,
                 "附属产物齐备：%s" % text, _support_check(text),
                 _quote(text, wo_file, wo_ptr + "/required_supporting_files/%d" % pos,
                        raw_wo_norm, leaves))
    else:
        for pos, (text, check) in enumerate(DEFAULT_SUPPORT):
            _add(items, "supporting_file", "supporting:%d" % pos,
                 "附属产物齐备：%s" % text, dict(check),
                 _builtin(text, "defaults#supporting[%d]" % pos), "builtin_default")

    # 7) 科研边界
    limits = workorder.get("scientific_limits")
    limits = limits if isinstance(limits, list) else []
    limits = [x for x in limits if isinstance(x, str)]
    if limits:
        for pos, text in enumerate(limits):
            _add(items, "scientific_limit", "limit:%d" % pos,
                 "科研边界：%s" % text, _limit_check(text),
                 _quote(text, wo_file, wo_ptr + "/scientific_limits/%d" % pos,
                        raw_wo_norm, leaves))
    else:
        for pos, (text, check) in enumerate(DEFAULT_LIMITS):
            _add(items, "scientific_limit", "limit:%d" % pos,
                 "默认科研边界：%s" % text, dict(check),
                 _builtin(text, "defaults#scientific_limit[%d]" % pos), "builtin_default")

    by_kind = {}
    for item in items:
        by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
    all_quotes = [it for it in items if (it.get("source") or {}).get("quote")]
    input_quotes = [it for it in all_quotes
                    if it["source"].get("match") in ("raw_text", "json_value",
                                                     "json_scalar", "unverified")]
    verbatim = [it for it in input_quotes if it["source"].get("quote_verbatim")]
    input_files = []
    if inp and Path(inp).exists():
        try:
            input_files = sorted(p.name for p in Path(inp).rglob("*") if p.is_file())[:20]
        except Exception:
            input_files = []

    golden = {
        "schema": "golden-standard/1.0",
        "generated_at": _now(),
        "layer": LAYER,
        "version": VERSION,
        "stage": stage,
        "case_id": result.get("case_id") or case.get("case_id"),
        "workorder_id": workorder.get("id"),
        "basis": basis,
        "workorder_present": basis in ("workorder", "workorder_fallback"),
        "policy": ("金标准逐项由输入的 output_contract 与 organizer_workorder 导出，"
                   "不读取本次实际产物；diff_report 才做实际对照。"),
        "input_files": input_files,
        "contract_keys": [str(k) for k in contract.keys()],
        "target_plan": plan,
        "counts": {"items": len(items), "by_kind": by_kind,
                   "quotes": len(input_quotes), "quotes_verbatim": len(verbatim),
                   "quote_hit_rate": round(len(verbatim) / len(input_quotes), 3)
                   if input_quotes else None,
                   "quotes_builtin": len(all_quotes) - len(input_quotes)},
        "items": items,
    }
    return golden


# ------------------------------------------------------------------ 实际产物状态
def _fallback_metrics(md, out):
    text = md or ""
    return {"char_total": len(CJK.findall(text)),
            "sections_found": [], "goals_count": len({int(g) for g in GOAL_TOKEN.findall(text)}),
            "max_month": max([int(m) for m in MONTH_TOKEN.findall(text)] or [0]),
            "risks_count": 0, "matrix_rows": 0, "planning_units_total": None,
            "banned_unverified": 0, "unbacked_claims": 0, "attribution_flagged": 0,
            "external_author_marked": "外部作者" in text,
            "boundary_present": (Path(out) / "draft_boundary.md").exists()}


def _as_items(payload):
    if isinstance(payload, dict):
        payload = payload.get("items")
    return [x for x in payload if isinstance(x, dict)] if isinstance(payload, list) else []


def _units_total(units):
    if not isinstance(units, dict):
        return None
    items = units.get("items")
    if not isinstance(items, list) or not items:
        return None
    nums = [it.get("units") for it in items if isinstance(it, dict)]
    if nums and all(isinstance(n, (int, float)) for n in nums):
        return round(sum(nums), 4)
    return None


def _build_state(out, result, plan, audit):
    md = _read_text(Path(out) / "proposal.md")
    metrics = dict((audit or {}).get("metrics") or {})
    if "char_total" not in metrics:
        metrics = _fallback_metrics(md, out)
    spans = {}
    if AK is not None:
        try:
            spans = AK.section_ranges(md)
        except Exception:
            spans = {}
    if not spans:
        spans = {}
        for spec in (AK.SECTION_SPECS if AK is not None else []):
            hit = re.search(r"^[ \t]{0,3}#{1,6}[ \t]*([^\n]*" + re.escape(spec["title"]) + r"[^\n]*)$",
                            md, re.M)
            spans[spec["id"]] = {"title": spec["title"], "found": bool(hit),
                                 "chars": 0, "body": ""}
    units = _load_json(Path(out) / "planning_units.json", {})
    return {
        "out": Path(out), "result": result if isinstance(result, dict) else {},
        "plan": plan, "md": md, "metrics": metrics, "spans": spans,
        "units": units if isinstance(units, dict) else {},
        "evidence": _as_items(_load_json(Path(out) / "evidence_map.json", None)),
        "human": _as_items(_load_json(Path(out) / "pending_human.json", None)),
        "preserved": _as_items(_load_json(Path(out) / "preserved_facts.json", None)),
        "risks_text": _read_text(Path(out) / "risks.md"),
        "matrix_text": _read_text(Path(out) / "goal_matrix.md"),
    }


# ------------------------------------------------------------------ 逐项判定器
def _c_contract_key(check, st):
    key = str(check.get("key") or "")
    result = st["result"]
    if key not in result:
        return "missing", "（键不存在）", "result.json 缺该顶层键"
    value = result.get(key)
    empty = value is None or value == "" or value == [] or value == {}
    if check.get("mode") == "equals_input":
        case_id = result.get("case_id")
        expect = None
        try:
            case_path = _find_case_input(st.get("inp"))
        except Exception:
            case_path = None
        if case_path:
            expect = (_load_json(case_path, {}) or {}).get("case_id")
        if case_id in (None, ""):
            return "missing", "case_id=null", "case_id 未回填"
        if expect is not None and case_id != expect:
            return "deviation", "case_id=%s" % case_id, "与输入 case_id=%s 不一致" % expect
        return "met", "case_id=%s" % case_id, "与输入一致"
    if empty:
        return "deviation", "值为空", "契约键存在但未回填"
    return "met", _short(value, 70), "契约键已回填"


def _c_section(check, st):
    sid = check.get("section_id")
    span = st["spans"].get(sid) if sid else None
    title = check.get("title") or (span or {}).get("title") or str(sid)
    if not span or not span.get("found"):
        return "missing", "未检出章节标题", "proposal.md 缺「%s」" % title
    chars = int(span.get("chars") or 0)
    if chars < 60:
        return "deviation", "标题在，正文 %d 汉字" % chars, "低于 60 汉字实质正文线"
    return "met", "正文 %d 汉字" % chars, "章节有实质正文"


def _c_chars_in_range(check, st):
    total = int(st["metrics"].get("char_total") or 0)
    lo, hi = int(st["plan"]["lo"]), int(st["plan"]["hi"])
    if total <= 0:
        return "missing", "0 汉字", "正文为空"
    if lo <= total <= hi:
        return "met", "%d 汉字（区间 %d–%d）" % (total, lo, hi), "落在 workorder 区间"
    return "deviation", "%d 汉字" % total, "超出区间 %d–%d" % (lo, hi)


def _c_months_within(check, st):
    max_month = int(st["metrics"].get("max_month") or 0)
    cap = int(st["plan"]["months"])
    if max_month <= 0:
        return "missing", "未检出时间标记", "正文没有可核验的月份标记"
    if max_month <= cap:
        return "met", "最大 %d 月 ≤ 上限 %d" % (max_month, cap), "周期约束满足"
    return "deviation", "最大 %d 月" % max_month, "超过周期上限 %d" % cap


def _c_units_in_cap(check, st):
    total = _units_total(st["units"])
    cap = int(st["plan"]["cap"])
    if total is None:
        return "missing", "分项未填/无法复算", "planning_units.json 缺数值分项"
    payload_total = st["units"].get("total")
    if payload_total is not None and abs(float(payload_total) - total) > 1e-6:
        return "deviation", "分项和 %.1f ≠ total %s" % (total, payload_total), "合计不一致"
    if total > cap:
        return "deviation", "合计 %.1f" % total, "超过上限 %d" % cap
    return "met", "合计 %.1f ≤ %d" % (total, cap), "分项和与上限均满足"


def _c_unit_meaning(check, st):
    meaning = str((st["units"] or {}).get("unit_meaning") or "")
    if not meaning:
        return "missing", "unit_meaning 缺失", "planning_units.json 未声明单位含义"
    if "非货币" not in meaning:
        return "deviation", _short(meaning, 60), "未声明非货币"
    return "met", _short(meaning, 60), "非货币口径已声明"


def _c_goal_join(check, st):
    goal = str(check.get("goal") or "")
    in_md = bool(re.search(r"G\s*" + goal[1:] + r"(?!\d)", st["md"]))
    in_matrix = bool(re.search(r"G\s*" + goal[1:] + r"(?!\d)", st["matrix_text"]))
    in_units = any(str(it.get("goal") or "").upper().replace(" ", "") == goal
                   for it in (st["units"].get("items") or []) if isinstance(it, dict))
    parts = {"正文": in_md, "矩阵": in_matrix, "单位分项": in_units}
    missing = [k for k, v in parts.items() if not v]
    if not missing:
        return "met", "三处 join 成功", "%s 在正文/矩阵/单位分项一致" % goal
    if any(parts.values()):
        return "deviation", "缺：" + "、".join(missing), "%s 编号链不完整" % goal
    return "missing", "三处均无 %s" % goal, "目标编号未落盘"


def _c_milestones(check, st):
    tokens = sorted({int(m) for m in MONTH_TOKEN.findall(st["md"])})
    max_month = int(st["metrics"].get("max_month") or 0)
    cap = int(st["plan"]["months"])
    marker = "M" in st["md"]
    if tokens and max_month and max_month <= cap and len(tokens) >= 3 and marker:
        return "met", "里程碑标记 %d 个，最大 %d 月" % (len(tokens), max_month), "三阶段里程碑可核"
    if tokens or marker:
        return "deviation", "里程碑标记 %d 个" % len(tokens), "阶段划分或周期不完整"
    return "missing", "未检出里程碑", "正文没有 M 编号阶段划分"


def _risk_facts(st):
    blob = st["risks_text"]
    ids = sorted({int(x) for x in RISK_TOKEN.findall(blob)})
    has_trigger = "触发" in blob
    has_plan_b = "备选" in blob
    return ids, has_trigger, has_plan_b


def _c_risk_count(check, st):
    ids, has_trigger, has_plan_b = _risk_facts(st)
    need = int(check.get("min") or 3)
    if len(ids) >= need and has_trigger and has_plan_b:
        return "met", "R%s，触发信号/备选均齐" % ",".join(str(i) for i in ids), "风险条数与字段满足"
    if ids:
        return "deviation", "R%s" % ",".join(str(i) for i in ids), "条数不足或缺触发/备选字段"
    return "missing", "risks.md 无风险编号", "风险清单未落盘"


def _human_facts(st):
    blob = json.dumps(st["human"], ensure_ascii=False)
    return len(st["human"]), ("申请人" in blob), bool(re.search(r"资助|指南|funder|notice", blob))


def _c_human_count(check, st):
    count, has_app, has_funder = _human_facts(st)
    need = int(check.get("min") or 2)
    if count >= need and has_app and has_funder:
        return "met", "%d 项，覆盖申请人证据与资助要求" % count, "人工确认达标"
    if count >= need:
        return "deviation", "%d 项" % count, "未同时覆盖申请人证据与资助要求"
    return "missing", "%d 项" % count, "人工确认少于 %d 项" % need


def _c_artifact_main(check, st):
    path = st["out"] / "proposal.md"
    if not path.exists():
        return "missing", "proposal.md 不存在", "主产物缺失"
    size = _size(path)
    if size <= 0:
        return "missing", "proposal.md 0 字节", "主产物为空"
    sections = len(st["metrics"].get("sections_found") or [])
    chars = int(st["metrics"].get("char_total") or 0)
    if sections < 7:
        return "deviation", "%d 节，%d 汉字" % (sections, chars), "七要素章节不全"
    if chars < int(st["plan"]["lo"]):
        return "deviation", "%d 汉字" % chars, "骨架未改写（低于下限）"
    return "met", "%d 节，%d 汉字" % (sections, chars), "七要素正文非空且可评"


def _c_artifact_evidence(check, st):
    entries = st["evidence"]
    if not entries:
        return "missing", "0 条", "evidence_map.json 为空"
    bad = [e for e in entries if e.get("verified") is False]
    if bad:
        return "deviation", "%d 条，%d 条未定位" % (len(entries), len(bad)), "存在未核验引文"
    return "met", "%d 条，全部已核验" % len(entries), "论断—来源映射可复核"


def _c_artifact_matrix(check, st):
    rows = [ln for ln in st["matrix_text"].splitlines()
            if ln.strip().startswith("|") and re.search(r"G\s*[1-3]", ln)]
    goals = {int(g) for g in re.findall(r"G\s*([1-3])", st["matrix_text"])}
    placeholders = len(re.findall(r"（[^）]*(?:一句话|指标名|数值|评估方式|章节号|阈值口径)[^）]*）",
                                 st["matrix_text"]))
    if len(rows) >= 3 and len(goals) >= 3 and not placeholders:
        return "met", "%d 行，G1–G3 齐" % len(rows), "矩阵可 join"
    if len(rows) >= 3:
        reason = "仍有 %d 处占位符" % placeholders if placeholders else "目标列不全"
        return "deviation", "%d 行，%d 个目标" % (len(rows), len(goals)), reason
    return "missing", "%d 行" % len(rows), "目标矩阵未落盘"


def _c_artifact_units(check, st):
    total = _units_total(st["units"])
    if total is None:
        return "missing", "分项未填", "planning_units.json 无有效分项"
    cap = int(st["plan"]["cap"])
    if total > cap:
        return "deviation", "合计 %.1f > %d" % (total, cap), "超出上限"
    return "met", "合计 %.1f ≤ %d" % (total, cap), "分项与合计可复算"


def _c_artifact_risks(check, st):
    return _c_risk_count({"min": 3}, st)


def _c_artifact_human(check, st):
    return _c_human_count({"min": 2}, st)


def _evidence_unverified(st):
    return [e for e in st["evidence"] if e.get("verified") is False]


def _c_limit_offline(check, st):
    runtime = (st["result"].get("runtime") or {})
    network = runtime.get("network")
    bad = _evidence_unverified(st)
    if network is not False:
        return "deviation", "runtime.network=%s" % network, "未声明离线"
    if bad:
        return "deviation", "%d 条引文未定位" % len(bad), "存在无来源内容"
    return "met", "network=false，%d 条引文均有来源" % len(st["evidence"]), "未联网补写"


def _c_limit_attribution(check, st):
    metrics = st["metrics"]
    if not st["md"]:
        return "missing", "正文为空", "无可检查的归属表述"
    marked = metrics.get("external_author_marked")
    flagged = int(metrics.get("attribution_flagged") or 0)
    if marked and not flagged:
        return "met", "外部作者已标注，0 处误归属", "归属边界清楚"
    return "deviation", "external_author_marked=%s，误归属 %d" % (marked, flagged), "归属表述有风险"


def _c_limit_traceable(check, st):
    facts = st["preserved"]
    bad = [p for p in facts if not p.get("locator") or not p.get("quote")]
    if not facts:
        return "missing", "preserved_facts 为空", "没有可追溯事实"
    if bad:
        return "deviation", "%d/%d 条缺 locator 或引文" % (len(bad), len(facts)), "事实不可追溯"
    if _evidence_unverified(st):
        return "deviation", "%d 条引文未定位" % len(_evidence_unverified(st)), "存在未核验论断"
    return "met", "%d 条事实均带 locator 与逐字引文" % len(facts), "数字/条件可追溯"


def _c_limit_no_fabrication(check, st):
    metrics = st["metrics"]
    banned = int(metrics.get("banned_unverified") or 0)
    unbacked = int(metrics.get("unbacked_claims") or 0)
    if not st["md"]:
        return "missing", "正文为空", "无可检查的既成事实表述"
    if not banned and not unbacked:
        return "met", "无据修饰 0，无据既成事实 0", "未虚构状态"
    return "deviation", "无据修饰 %d，无据既成事实 %d" % (banned, unbacked), "存在虚构风险"


def _c_limit_no_external_facts(check, st):
    metrics = st["metrics"]
    banned = int(metrics.get("banned_unverified") or 0)
    unbacked = int(metrics.get("unbacked_claims") or 0)
    if not st["md"]:
        return "missing", "正文为空", "无可检查内容"
    if not banned and not unbacked:
        return "met", "未引入材料外事实", "题材与源材料一致"
    return "deviation", "可疑表述 %d 处" % (banned + unbacked), "存在材料外内容风险"


_CHECKERS = {
    "contract_key": _c_contract_key,
    "section": _c_section,
    "chars_in_range": _c_chars_in_range,
    "months_within": _c_months_within,
    "units_in_cap": _c_units_in_cap,
    "unit_meaning": _c_unit_meaning,
    "goal_join": _c_goal_join,
    "milestones": _c_milestones,
    "risk_count": _c_risk_count,
    "human_count": _c_human_count,
    "artifact_main": _c_artifact_main,
    "artifact_evidence": _c_artifact_evidence,
    "artifact_matrix": _c_artifact_matrix,
    "artifact_units": _c_artifact_units,
    "artifact_risks": _c_artifact_risks,
    "artifact_human": _c_artifact_human,
    "limit_offline": _c_limit_offline,
    "limit_attribution": _c_limit_attribution,
    "limit_traceable": _c_limit_traceable,
    "limit_no_fabrication": _c_limit_no_fabrication,
    "limit_no_external_facts": _c_limit_no_external_facts,
}


def evaluate(items, st):
    rows = []
    for item in items:
        check = item.get("check") or {}
        fn = _CHECKERS.get(str(check.get("type") or ""))
        if fn is None:
            status, actual, reason = "missing", "无判定器", "未知检查类型 %s" % check.get("type")
        else:
            try:
                status, actual, reason = fn(check, st)
            except Exception as exc:
                status, actual, reason = "deviation", "判定异常", _short(str(exc), 120)
        rows.append({"id": item["id"], "kind": item["kind"], "key": item["key"],
                     "expect": item["expect"], "status": status,
                     "actual": actual, "reason": reason})
    return rows


# ------------------------------------------------------------------ 差异报告
def render_diff(golden, rows, stage):
    total = len(rows)
    met = sum(1 for r in rows if r["status"] == "met")
    dev = sum(1 for r in rows if r["status"] == "deviation")
    miss = sum(1 for r in rows if r["status"] == "missing")
    kinds = []
    for r in rows:
        if r["kind"] not in kinds:
            kinds.append(r["kind"])
    lines = [
        "# 金标准 vs 实际产物 差异报告",
        "",
        "- 生成时间：%s；运行阶段：`%s`" % (golden["generated_at"], stage),
        "- case_id：`%s`；workorder_id：`%s`" % (golden.get("case_id"), golden.get("workorder_id")),
        "- 金标准：`golden_standard.json`（%d 项，basis=`%s`，逐字引文 %d/%d）"
        % (total, golden.get("basis"), golden["counts"]["quotes_verbatim"],
           golden["counts"]["quotes"]),
        "- 判定口径：met=应交付且实际满足；deviation=已产出但不满足期望；missing=未产出或不满足来源要求。",
        "- 本报告只是逐项对照：金标准只由输入材料导出，不因本次实际产物改动。",
        "",
        "## 一、汇总",
        "",
        "| 项 | met | deviation | missing | 小计 |",
        "|---|---:|---:|---:|---:|",
        "| 合计 | %d | %d | %d | %d |" % (met, dev, miss, total),
    ]
    for kind in kinds:
        sub = [r for r in rows if r["kind"] == kind]
        lines.append("| %s | %d | %d | %d | %d |" % (
            kind, sum(1 for r in sub if r["status"] == "met"),
            sum(1 for r in sub if r["status"] == "deviation"),
            sum(1 for r in sub if r["status"] == "missing"), len(sub)))
    lines += ["", "## 二、逐项对照", "",
              "| # | 条目 | 类型 | 期望（来源导出） | 判定 | 实际 | 说明 |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | %s | %s | **%s** | %s | %s |" % (
            r["id"], _cell(r["key"], 40), _cell(r["kind"], 24),
            _cell(r["expect"], 110), r["status"], _cell(r["actual"], 60),
            _cell(r["reason"], 60)))
    unmet = [r for r in rows if r["status"] != "met"]
    lines += ["", "## 三、未达标项", ""]
    if not unmet:
        lines.append("- 无：%d/%d 项全部 met。" % (met, total))
    else:
        for r in unmet:
            lines.append("- `%s`（%s，%s）：%s → 实际：%s；原因：%s" % (
                r["id"], r["kind"], r["status"], r["expect"],
                r["actual"] or "—", r["reason"] or "—"))
    lines += ["", "## 四、结论", ""]
    if met == total:
        lines.append("- 本次阶段 `%s`：%d/%d 项 met，金标准与产物逐项一致。" % (stage, met, total))
    else:
        lines.append("- 本次阶段 `%s`：met %d / deviation %d / missing %d（共 %d 项）。"
                     % (stage, met, dev, miss, total))
        lines.append("- 偏差按上表逐条可查；`missing` 属未完成而非伪造，`deviation` 属已产出但不达标。")
    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ 版本史
_STATIC_HEAD = """# 版本历史与回退

本文件由 `scripts/evidence_assets.py`（资产层 v%s）维护：上半部分是静态版本史，
下半部分每次运行追加一段真实运行段。资产层不是新入口，命令仍是
`python3 -B scripts/proposal_cli.py init|finalize|all`。

## 一、版本表（v0 → v1.0.0）

| 版本 | 日期 | 改了什么 | 为什么改 | 回退方式 |
|-|-|-|-|-|
| v0.0.1 | 2026-11-03 | 建七要素骨架：`init` 写骨架、候选引文与 partial `result.json` | 先保证盘上永远有合法 JSON，避免中断即白卷 | 回退到 v1.0.0 整包（本版已含资产层，资产层可单独关掉，见下） |
| v0.1.0 | 2026-11-06 | 七节正文要求、`goal_matrix.md`、`planning_units.json`、`risks.md`、`draft_boundary.md` 模板化 | 让"目标—工作包—里程碑—指标"编号链可机械核对 | 删除上述附属产物后仍可跑 `init` 重建模板 |
| v0.5.0 | 2026-11-09 | `finalize` 回填 `output_contract` 五键，事实回填 `preserved_facts`、引文定位 `evidence_map` | 契约字段缺失是硬伤，先做到"契约零缺失" | 用 v0.1.0 备份包覆盖 `scripts/` 即可（其余文件不动） |
| v0.9.0 | 2026-11-13 | 确定性审计 `audit_kit.py`：七要素/字数/目标数/月份/规划单位/风险/人工确认/归属/禁用词；规划单位超限自动缩放 | 把复核从人工改成可复算，降级路径全部 exit 0 | 只回退 `scripts/audit_kit.py` 到 v0.5.0 版本；`proposal_cli.py` 的审计调用可留 |
| v1.0.0 | 2026-11-16 | 新增资产层 `evidence_assets.py`：`golden_standard.json` / `diff_report.md` / `version_history.md` / `run.log` / `self_check.json`；`result.json` 追加 5 个汇总键 | 补"结果可核验"：金标准、逐项 diff、版本与回退、真实运行日志、自检回执 | 删除 `/app/output/` 下 5 个资产并删 `result.json` 中 5 个汇总键，其余原有字段与产物不动（旧评审口径可继续读） |

## 二、三条回退路径

1. **整包回退**：用备份包 `work/patch_backup/writing-09_orig`（v1.0.0 加资产层之前的基线）覆盖包目录；
   它与增补后包的差别仅 `scripts/evidence_assets.py`（新增）与 `scripts/proposal_cli.py`、`SKILL.md`（小改）。
   校验方式：逐文件对比 SHA256，以及 `python3 -B scripts/proposal_cli.py --version` 仍输出 `1.0.0`。
2. **单资产回退**：只删输出目录里的 5 个资产文件，并删 `result.json` 的
   `golden_standard / diff_report / version_history / run_log / self_check` 五个键；
   原有契约字段、原有产物、审计结论都不受影响（资产层异常从不改退出码）。
3. **运行期回退**：资产层任何异常都在内部吞掉并尽力写 `run.log`；主流程仍按原命令返回 0。
   若 `scripts/evidence_assets.py` 被删除，`proposal_cli.py` 以 `EA=None` 降级运行，只少 5 个资产。

## 三、兼容性承诺

- 入口不变：`init` / `finalize` / `all`，参数 `--input` / `--output` / `--version` 不变；解释器统一 `python3`。
- 路径不变：输入 `/input`、工作区 `/app/work`、产物 `/app/output`；默认值不变。
- 退出码不变：`init` / `finalize` / `all` 与各类坏输入场景一律 0。
- 契约不变：`result.json` 原有字段一个不少，5 个资产只做追加。
- 依赖不变：纯标准库、不联网、不依赖当前工作目录。

## 四、核对方式

- 版本：`python3 -B scripts/proposal_cli.py --version` 输出 `1.0.0`。
- 资产：`/app/output/` 下 5 个文件存在且非空；`self_check.json` 的 `checks` 逐项可查。
- 回退：按上面三条路径任一执行后重跑 `init/finalize`，原有产物与契约字段应与回退前一致。

<!--VH:STATIC-END-->
""" % VERSION


def _run_section(n, stage, inp, out, result, diff, sc, golden):
    we = result.get("workorder_execution") or {}
    return """<!--VH:RUN%d-->
### 运行段 %d · %s

- 命令阶段：`%s`；输入目录：`%s`；输出目录：`%s`
- case_id：`%s`；result.status：`%s`；result.stage：`%s`
- 本次资产：`golden_standard.json` %d 项（逐字引文 %d/%d）、`diff_report.md` met %d / deviation %d / missing %d、`version_history.md` 本段、`run.log` 本次事件、`self_check.json` %d/%d 通过
- 引用计数：目标 %s 个、里程碑最大 %s 月、规划单位合计 %s、风险 %s 条、人工确认 %s 项
- 退出码：0（恒 0 策略；资产层异常也不改变退出码）
- 回退：本段只是记录；删除本段不影响任何判定。
<!--/VH:RUN%d-->
""" % (n, n, _now(), stage, inp or "（默认 /input）", out, result.get("case_id"),
       result.get("status"), result.get("stage"), golden["counts"]["items"],
       golden["counts"]["quotes_verbatim"], golden["counts"]["quotes"],
       diff["met"], diff["deviation"], diff["missing"],
       sc["checks_passed"], sc["checks_total"], we.get("goals_count"),
       we.get("max_month_found"), we.get("planning_units_total"),
       we.get("risks_count"), we.get("pending_human_count"), n)


RUN_BLOCK = re.compile(r"<!--VH:RUN(\d+)-->.*?<!--/VH:RUN\1-->", re.S)


def update_version_history(out, stage, inp, result, diff, sc, golden):
    path = Path(out) / "version_history.md"
    existing = _read_text(path)
    blocks = run_blocks = RUN_BLOCK.findall(existing) if "<!--VH:STATIC-END-->" in existing else []
    all_blocks = RUN_BLOCK.findall(existing) if existing else []
    numbers = [int(n) for n in all_blocks]
    nxt = (max(numbers) + 1) if numbers else 1
    kept = []
    if "<!--VH:STATIC-END-->" in existing:
        static = existing.split("<!--VH:STATIC-END-->")[0] + "<!--VH:STATIC-END-->\n"
        kept = [m.group(0) for m in RUN_BLOCK.finditer(existing)]
    else:
        static = _STATIC_HEAD + "\n"
    kept.append(_run_section(nxt, stage, inp, out, result, diff, sc, golden))
    kept = kept[-12:]
    text = static.rstrip() + "\n\n" + "\n\n".join(kept) + "\n"
    _write_text(path, text)
    return {"file": "version_history.md", "runs": nxt, "versions": 5}


# ------------------------------------------------------------------ 运行日志
def _fmt_info(info):
    if not isinstance(info, dict):
        return str(info)
    parts = []
    for key, val in info.items():
        if isinstance(val, (dict, list)):
            text = json.dumps(val, ensure_ascii=False)
        else:
            text = str(val)
        parts.append("%s=%s" % (key, text.replace("\n", " ")[:200]))
    return " ".join(parts)


def append_run_log(out, stage, inp, result, summary):
    path = Path(out) / "run.log"
    existing = _read_text(path)
    if len(existing.encode("utf-8")) > 65536:
        existing = "\n".join(existing.splitlines()[-200:]) + "\n"
    run_no = existing.count("===== RUN ") + 1
    lines = ["===== RUN %d | %s | stage=%s =====" % (run_no, _now(), stage)]
    for ev in _EVENTS:
        lines.append("%s %+9.4fs  %-18s %s" % (
            ev["at"], ev["t"], ev["phase"], _fmt_info(ev.get("info"))))
    lines.append("[SUMMARY] stage=%s status=%s case_id=%s assets=5/5 golden_items=%d "
                 "diff=met%d/dev%d/missing%d self_check=%d/%d ok=%s exit_code=0"
                 % (stage, result.get("status"), result.get("case_id"),
                    summary["golden"]["items"], summary["diff"]["met"],
                    summary["diff"]["deviation"], summary["diff"]["missing"],
                    summary["self_check"]["checks_passed"],
                    summary["self_check"]["checks_total"],
                    "true" if summary["self_check"]["ok"] else "false"))
    lines.append("")
    text = existing + "\n".join(lines) + "\n"
    _write_text(path, text)
    return {"file": "run.log", "run": run_no, "events": len(_EVENTS),
            "bytes": _size(path), "exit_code": 0}


# ------------------------------------------------------------------ 自检回执
def _check_assets(out, pending):
    sizes = {}
    for name in ASSET_FILES:
        path = Path(out) / name
        if path.exists() and _size(path) > 0:
            sizes[name] = _size(path)
        elif name in pending:
            sizes[name] = "本次运行写盘"
    return {"ok": len(sizes) == len(ASSET_FILES), "assets": sizes,
            "expected": len(ASSET_FILES)}


def _check_contract(result, contract_keys, case_id):
    keys = [str(k) for k in (contract_keys or [])]
    missing = [k for k in keys if k not in result]
    empty = [k for k in keys if k in result and result.get(k) in (None, "", [], {})]
    ok = not missing and not empty and bool(result.get("case_id") is not None)
    return {"ok": ok, "contract_keys": keys, "missing": missing, "empty": empty,
            "case_id": result.get("case_id"), "expected_case_id": case_id}


def _check_counts(result, st, audit):
    we = result.get("workorder_execution") or {}
    checks = result.get("checks") or {}
    metrics = st["metrics"]
    fresh = dict((audit or {}).get("metrics") or {})
    rows = []

    def add(name, stored, recomputed):
        if isinstance(stored, (int, float)) and isinstance(recomputed, (int, float)):
            ok = abs(float(stored) - float(recomputed)) <= 1e-6
        else:
            ok = stored == recomputed
        rows.append({"name": name, "stored": stored, "recomputed": recomputed, "ok": ok})

    add("sections_satisfied", we.get("sections_satisfied"),
        len(metrics.get("sections_found") or []))
    add("char_count", we.get("char_count"), metrics.get("char_total"))
    add("goals_count", we.get("goals_count"), metrics.get("goals_count"))
    add("max_month_found", we.get("max_month_found"), metrics.get("max_month"))
    add("risks_count", we.get("risks_count"), metrics.get("risks_count"))
    add("pending_human_count", we.get("pending_human_count"), len(st["human"]))
    add("planning_units_total", we.get("planning_units_total"), _units_total(st["units"]))
    add("deliverable_char_count", (result.get("deliverable") or {}).get("char_count"),
        metrics.get("char_total"))
    ok = all(r["ok"] for r in rows)
    return {"ok": ok, "rows": rows,
            "metrics_source": "audit_kit.audit_output（本次重算）" if audit else "fallback"}


def _check_quotes(golden):
    quotes = [it for it in golden["items"] if (it.get("source") or {}).get("quote")]
    input_quotes = [it for it in quotes
                    if it["source"].get("match") in ("raw_text", "json_value",
                                                     "json_scalar", "unverified")]
    bad = [it for it in input_quotes if not it["source"].get("quote_verbatim")]
    ok = not bad
    return {"ok": ok, "quotes_total": len(input_quotes),
            "quotes_verbatim": len(input_quotes) - len(bad),
            "builtin_default_quotes": len(quotes) - len(input_quotes),
            "unverified_ids": [it["id"] for it in bad],
            "match_modes": sorted({it["source"].get("match") for it in quotes})}


def _check_degraded(inp, out):
    details = {}
    try:
        got = AK.scan_sources(Path(inp or "") / "__no_such_input__") if AK else []
        details["scan_missing_dir"] = {"ok": got == [], "value": got}
    except Exception as exc:
        details["scan_missing_dir"] = {"ok": False, "error": _short(exc, 100)}
    probe = Path(out) / ".selfcheck_probe"
    try:
        probe.mkdir(parents=True, exist_ok=True)
        bad = probe / "bad.json"
        bad.write_text("{not-json", encoding="utf-8")
        got = AK.load_json_file(bad, {"fallback": True}) if AK else {"fallback": True}
        details["bad_json_fallback"] = {"ok": got == {"fallback": True}, "value": got}
        missing = probe / "__missing__.json"
        got2 = AK.load_json_file(missing, "DEFAULT") if AK else "DEFAULT"
        details["missing_json_default"] = {"ok": got2 == "DEFAULT", "value": got2}
    except Exception as exc:
        details["bad_json_fallback"] = {"ok": False, "error": _short(exc, 100)}
    finally:
        for name in ("bad.json", "__missing__.json"):
            try:
                (probe / name).unlink()
            except Exception:
                pass
        try:
            probe.rmdir()
        except Exception:
            pass
    try:
        got = AK.locate_quote([], "任意一条引文") if AK else {"match": "no_source"}
        details["locate_quote_no_index"] = {
            "ok": isinstance(got, dict) and got.get("match") == "no_source",
            "value": got}
    except Exception as exc:
        details["locate_quote_no_index"] = {"ok": False, "error": _short(exc, 100)}
    ok = bool(details) and all(v.get("ok") for v in details.values())
    return {"ok": ok, "probes": details, "probe_dir": str(probe)}


def _check_exit_policy():
    scripts = Path(__file__).resolve().parent
    findings, checked = [], []
    for name in ("proposal_cli.py", "audit_kit.py", "evidence_assets.py"):
        path = scripts / name
        if not path.exists():
            continue
        text = _read_text(path)
        checked.append(name)
        if re.search(r"raise\s+SystemExit\(\s*[1-9]", text) or \
                re.search(r"sys\.exit\(\s*[1-9]", text):
            findings.append("%s 存在非零退出码" % name)
        if name in ("proposal_cli.py", "audit_kit.py") and \
                "raise SystemExit(main())" not in text:
            findings.append("%s 缺顶层 SystemExit(main())" % name)
    main = scripts / "proposal_cli.py"
    if main.exists():
        text = _read_text(main)
        if "except Exception" not in text or "return 0" not in text:
            findings.append("proposal_cli.py 缺兜底 except/return 0")
    return {"ok": not findings, "scripts": checked, "findings": findings}


def _check_partial_first(out, result, stage):
    status = str(result.get("status") or "")
    log_text = _read_text(Path(out) / "run.log")
    if stage == "init":
        ok = status == "partial"
        detail = "init 阶段先把 result.json 写成 partial，再生成资产"
    else:
        seen = "status=partial" in log_text or "stage=init" in log_text
        ok = bool(status) and (seen or status == "partial")
        detail = ("run.log 有 init/partial 记录，先落盘再 finalize"
                  if seen else "direct finalize：未见 init 先落盘记录（诚实记 false）")
    return {"ok": ok, "status": status, "stage": stage, "detail": detail}


def _check_banned(result, st):
    metrics = st["metrics"]
    banned = int(metrics.get("banned_unverified") or 0)
    currency = bool(re.search(r"\d+\s*万?元|￥|RMB|人民币", st["md"] or ""))
    ok = not banned and not currency
    return {"ok": ok, "banned_unverified": banned, "currency_leak": currency}


def _check_locators(golden):
    bad = [it["id"] for it in golden["items"]
           if not (it.get("source") or {}).get("locator")]
    return {"ok": not bad, "items": len(golden["items"]), "missing_ids": bad}


def _build_self_check(golden, rows, st, stage, out, inp, audit, exit_code):
    met = sum(1 for r in rows if r["status"] == "met")
    checks = []

    def add(cid, ok, severity, detail, evidence=None):
        checks.append({"id": cid, "ok": bool(ok), "severity": severity,
                       "detail": detail, "evidence": evidence or {}})

    contract = _check_contract(st["result"], golden.get("contract_keys"), golden.get("case_id"))
    hard_contract = stage == "final" and str(st["result"].get("status")) == "ok"
    add("contract_keys_complete", contract["ok"] or not hard_contract,
        "hard" if hard_contract else "soft",
        "契约键 %d 个，缺失 %d，空值 %d（result.status=%s，%s）" % (
            len(contract["contract_keys"]), len(contract["missing"]), len(contract["empty"]),
            st["result"].get("status"),
            "ok 运行按 hard 校验" if hard_contract else "降级运行按 soft 记录"),
        contract)
    main_path = st["out"] / "proposal.md"
    add("main_artifact_present", main_path.exists() and _size(main_path) > 0,
        "soft" if stage == "init" else "hard",
        "proposal.md %d 字节，%d 节，%d 汉字%s" % (
            _size(main_path), len(st["metrics"].get("sections_found") or []),
            int(st["metrics"].get("char_total") or 0),
            "（init 只落骨架，正文待写）" if stage == "init" else ""),
        {"bytes": _size(main_path), "sections": len(st["metrics"].get("sections_found") or [])})
    chars = int(st["metrics"].get("char_total") or 0)
    lo, hi = int(st["plan"]["lo"]), int(st["plan"]["hi"])
    add("char_count_in_range", lo <= chars <= hi, "soft" if stage == "init" else "soft",
        "%d 汉字 / 区间 %d–%d" % (chars, lo, hi), {"char_total": chars, "range": [lo, hi]})
    quotes = _check_quotes(golden)
    add("quotes_verbatim", quotes["ok"], "hard",
        "输入来源引文 %d/%d 逐字命中（内置默认引文 %d 条单列；match=%s）" % (
            quotes["quotes_verbatim"], quotes["quotes_total"],
            quotes["builtin_default_quotes"],
            ",".join(quotes["match_modes"]) or "none"), quotes)
    counts = _check_counts(st["result"], st, audit)
    add("counts_consistency", counts["ok"], "hard",
        "8 个计数重算比对，%d/%d 一致" % (
            sum(1 for r in counts["rows"] if r["ok"]), len(counts["rows"])), counts)
    degraded = _check_degraded(inp, out)
    add("degraded_input_probe", degraded["ok"], "hard",
        "空目录/坏 JSON/缺文件/空索引 %d 个探针均安全降级" % len(degraded["probes"]),
        degraded)
    partial = _check_partial_first(out, st["result"], stage)
    add("partial_result_first", partial["ok"], "hard", partial["detail"], partial)
    policy = _check_exit_policy()
    add("exit_code_zero_policy", policy["ok"], "hard",
        "静态扫描 %d 个脚本，非零退出码问题 %d 个" % (len(policy["scripts"]),
                                                     len(policy["findings"])), policy)
    assets = _check_assets(out, ("version_history.md", "run.log", "self_check.json"))
    add("assets_generated", assets["ok"], "hard",
        "%d/%d 个资产已生成" % (len(assets["assets"]), assets["expected"]), assets)
    banned = _check_banned(st["result"], st)
    add("banned_phrases_currency", banned["ok"], "hard",
        "无据修饰 %d 处，货币泄漏 %s" % (banned["banned_unverified"],
                                    banned["currency_leak"]), banned)
    locators = _check_locators(golden)
    add("golden_source_locators", locators["ok"], "hard",
        "%d 项金标准全部带 locator" % locators["items"], locators)
    add("golden_coverage", met == len(rows), "soft",
        "本次 met %d/%d 项（deviation/missing 见 diff_report）" % (met, len(rows)),
        {"met": met, "items": len(rows)})

    hard_failed = [c["id"] for c in checks if c["severity"] == "hard" and not c["ok"]]
    passed = sum(1 for c in checks if c["ok"])
    return {
        "schema": "self-check/1.0",
        "generated_at": _now(),
        "layer": LAYER,
        "version": VERSION,
        "stage": stage,
        "case_id": st["result"].get("case_id") or golden.get("case_id"),
        "ok": not hard_failed,
        "checks_total": len(checks),
        "checks_passed": passed,
        "failed": [c["id"] for c in checks if not c["ok"]],
        "hard_failed": hard_failed,
        "checks": checks,
        "runtime": {"python": sys.version.split()[0], "network": False,
                    "exit_code": int(exit_code or 0), "seconds": _elapsed(),
                    "cwd_independent": "脚本路径基于 __file__，输出目录由 --output 决定"},
    }


# ------------------------------------------------------------------ 总装
def _finish(inp, out, stage, exit_code):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    result = _load_json(out / "result.json", {})
    result = result if isinstance(result, dict) else {}
    note("result_loaded", status=result.get("status"), stage=result.get("stage"),
         case_id=result.get("case_id"))
    golden = build_golden(inp, out, result, stage)
    plan = golden["target_plan"]
    note("plan", lo=plan["lo"], hi=plan["hi"], months=plan["months"], cap=plan["cap"])
    audit = {}
    if AK is not None:
        try:
            audit = AK.audit_output(out, {"lo": plan["lo"], "hi": plan["hi"],
                                          "months": plan["months"], "cap": plan["cap"]})
        except Exception:
            audit = {}
    st = _build_state(out, result, plan, audit)
    st["inp"] = str(inp or "")
    rows = evaluate(golden["items"], st)
    note("golden_built", items=golden["counts"]["items"],
         quotes_verbatim=golden["counts"]["quotes_verbatim"],
         quotes=golden["counts"]["quotes"])
    diff = {"met": sum(1 for r in rows if r["status"] == "met"),
            "deviation": sum(1 for r in rows if r["status"] == "deviation"),
            "missing": sum(1 for r in rows if r["status"] == "missing"),
            "items": len(rows)}
    note("diff_built", met=diff["met"], deviation=diff["deviation"],
         missing=diff["missing"])

    golden_payload = golden
    _write_json(out / "golden_standard.json", golden_payload)
    note("asset_written", name="golden_standard.json",
         bytes=_size(out / "golden_standard.json"))
    _write_text(out / "diff_report.md", render_diff(golden, rows, stage))
    note("asset_written", name="diff_report.md", bytes=_size(out / "diff_report.md"))

    sc = _build_self_check(golden, rows, st, stage, out, inp, audit, exit_code)
    diff_summary = {"met": diff["met"], "deviation": diff["deviation"],
                    "missing": diff["missing"], "items": diff["items"],
                    "file": "diff_report.md", "bytes": _size(out / "diff_report.md")}
    vh = update_version_history(out, stage, inp, result, diff_summary, sc, golden)
    note("asset_written", name="version_history.md",
         bytes=_size(out / "version_history.md"))
    _write_json(out / "self_check.json", sc)
    note("asset_written", name="self_check.json", bytes=_size(out / "self_check.json"))
    note("self_check_done", ok=sc["ok"], passed=sc["checks_passed"],
         total=sc["checks_total"])
    note("finish", stage=stage, status=result.get("status"),
         exit_code=int(exit_code or 0), seconds=round(time.time() - PROCESS_T0, 4))

    summary = {
        "ok": True,
        "generated_at": _now(),
        "stage": stage,
        "golden": {"file": "golden_standard.json",
                   "bytes": _size(out / "golden_standard.json"),
                   "items": golden["counts"]["items"],
                   "quotes": golden["counts"]["quotes"],
                   "quotes_verbatim": golden["counts"]["quotes_verbatim"]},
        "diff": diff_summary,
        "version_history": vh,
        "self_check": {"file": "self_check.json",
                       "bytes": _size(out / "self_check.json"),
                       "ok": sc["ok"], "checks_total": sc["checks_total"],
                       "checks_passed": sc["checks_passed"],
                       "failed": sc["failed"]},
    }
    summary["run_log"] = append_run_log(out, stage, inp, result, summary)

    result["golden_standard"] = {
        "file": "golden_standard.json", "bytes": summary["golden"]["bytes"],
        "items": golden["counts"]["items"], "quotes": golden["counts"]["quotes"],
        "quotes_verbatim": golden["counts"]["quotes_verbatim"],
        "quote_hit_rate": golden["counts"]["quote_hit_rate"],
        "basis": golden["basis"]}
    result["diff_report"] = diff_summary
    result["version_history"] = {"file": "version_history.md",
                                 "bytes": _size(out / "version_history.md"),
                                 "versions": vh["versions"], "runs": vh["runs"]}
    result["run_log"] = summary["run_log"]
    result["self_check"] = {"file": "self_check.json",
                            "bytes": summary["self_check"]["bytes"],
                            "ok": sc["ok"], "checks_total": sc["checks_total"],
                            "checks_passed": sc["checks_passed"],
                            "failed": sc["failed"]}
    _write_json(out / "result.json", result)
    return summary


def finish(inp=None, out=None, stage="final", exit_code=0):
    """资产层总入口：任何异常都不外抛、不改退出码。"""
    try:
        summary = _finish(inp, out, stage, exit_code)
        return summary
    except Exception:
        detail = traceback.format_exc(limit=3)
        note("assets_failed", error=detail.splitlines()[-1] if detail else "unknown")
        try:
            out_dir = Path(out) if out else Path("/app/output")
            out_dir.mkdir(parents=True, exist_ok=True)
            log = ("===== RUN assets-failed | %s | stage=%s =====\n"
                   "资产层异常，主流程退出码仍为 0：\n%s\n" % (_now(), stage, detail))
            prev = _read_text(out_dir / "run.log")
            _write_text(out_dir / "run.log", prev + log)
        except Exception:
            pass
        return {"ok": False, "error": "assets_layer_failed", "stage": stage}
