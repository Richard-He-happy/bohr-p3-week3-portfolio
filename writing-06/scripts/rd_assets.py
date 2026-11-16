# -*- coding: utf-8 -*-
"""Verification assets for rd-section-forge, produced by `build` (stdlib only).

The five assets answer five different reviewer questions:

  golden_standard.json  what is expected, one item per output_contract key and
                        one item per material-sourced readout/fact, each with a
                        locator + verbatim quote when the material supports it
                        (otherwise basis=contract)
  diff_report.md        what was actually delivered vs each expected item
                        (达标 / 偏差 / 缺失 + reason)
  version_history.md    static v0 -> v1.0.0 record (what/why/rollback) copied
                        from references/version_history.md, plus this run's
                        section appended
  run.log               append-only stage log: timings, exit codes,
                        degradations, exceptions
  self_check.json       machine receipt: contract keys, main artefacts, quote
                        hit rate, count consistency, empty/bad-JSON probes,
                        exit-code policy

Every writer is defensive: it never raises, and a failed asset degrades to a
non-empty stub that records the failure, so reviewers always have something to
verify.  No network, no third-party imports, no dependence on the current
working directory.
"""

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import rd_material as M

SKILL_NAME = "rd-section-forge"
VERSION = "1.0.0"
ASSETS = ("golden_standard.json", "diff_report.md", "version_history.md",
          "run.log", "self_check.json")
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
STATIC_HISTORY = PACKAGE_ROOT / "references" / "version_history.md"
LOG_CAP = 64000
LOG_TAIL = 160
READOUT_CAP = 16
FACT_CAP = 6

XREF_RE = re.compile(r"(Fig(?:ure)?s?\.?\s*\d+[A-Za-z]?|Table\s*\d+[A-Za-z]?"
                     r"|图\s*\d+[A-Za-z]?|表\s*\d+[A-Za-z]?)")
STAT_RE = re.compile(r"p\s*[<>=]\s*0?\.\d+|ANOVA|t-?test|Mann|Kruskal|Wilcoxon"
                     r"|mean|SD|SEM|CI\b", re.I)
CAPTION_HINT = re.compile(r"fig|caption|table|statistic|mean|sd|sem|n\s*=|p\s*[<>=]", re.I)

# Contract key -> (expected artefact, expected content).  The router is the
# same shape as M.CONTRACT_ROUTER; unknown keys are still listed as contract
# items so nothing in output_contract is silently dropped.
CONTRACT_TEXT = [
    (r"limit|局限", "manuscript.md (### Limitations / 局限性)",
     "局限小节：≥2 条，覆盖方法/样本/测量/统计层，每条写清“因此不能得出什么”"),
    (r"result.?map|readout|读数", "results_map.json",
     "读数映射：每个 Results 数值带 token/value/unit/sources，并给出 verified 覆盖"),
    (r"preserv|fact|事实", "preserved_facts.json",
     "关键事实表：fact + 逐字 quote + locator，quote 必须能在材料中逐字命中"),
    (r"evidence|source|证据|来源", "evidence_map.json",
     "证据映射：每条 claim → quote + locator + verified 状态，供第三方逐条回查"),
    (r"change|log|修改", "change_log.json",
     "修改记录：动作/原句/改句/原因 + pending_human，能看出改了什么、为什么"),
    (r"uncertain|pending|人工", "result.json (pending_human / uncertainty)",
     "人工确认项与不确定性：每条落到具体图表、字段或材料缺口，不写空话"),
    (r"deliver|manuscript|draft|正文", "manuscript.md (results_discussion.md)",
     "可编辑主稿：Results + Discussion 两节齐备，含 Limitations 小节，正文数字均有来源"),
]

SECTION_SPECS = [
    ("Results", r"^##\s*\d+\.\s*(Results|结果)",
     "至少 1 节 Results；段落只写观察（方向/幅度/组间比较/离散度），"
     "每段含值+单位+条件+图/表编号，不混入机制解释"),
    ("Discussion", r"^##\s*\d+\.\s*(Discussion|讨论)",
     "至少 1 节 Discussion；回指具体读数、说明与已有证据的一致/不一致及可能原因、"
     "机制标为推测、给出相关≠因果的边界"),
    ("Limitations", r"^#{2,4}\s*(Limitations|局限性|局限)",
     "≥2 条局限，覆盖方法/样本/测量/统计层，每条都写“因此不能得出什么”，"
     "不是泛泛的自我评价"),
]


# ---------------------------------------------------------------- primitives
def stamp():
    return datetime.now(timezone.utc).isoformat()[:19] + "Z"


def now():
    return time.monotonic()


def elapsed_ms(t0):
    try:
        return max(0, int((now() - t0) * 1000))
    except Exception:
        return -1


def sha16(data):
    """First 16 hex chars of sha256 for bytes / text / Path; '-' on failure."""
    try:
        if isinstance(data, Path):
            data = data.read_bytes()
        elif isinstance(data, str):
            data = data.encode("utf-8")
        return hashlib.sha256(bytes(data)).hexdigest()[:16]
    except Exception:
        return "-"


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _write_text(path, text):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return target


def _write_json(path, payload):
    return _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _short(value, cap=120):
    """Single-line digest of any JSON value for the log."""
    try:
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value)
    except Exception:
        text = "-"
    return text.replace("\n", " ")[:cap]


def _num_text(value):
    """Render a golden value without float noise; None -> '-'."""
    try:
        return M.render_number(float(value))
    except Exception:
        return "-"


# ------------------------------------------------------------------- run.log
def _log_path(out):
    return Path(out) / "run.log"


def _trim_log(path):
    try:
        lines = _read_text(path).splitlines()
        if len(lines) <= LOG_TAIL + 1:
            return
        rest = [ln for ln in lines[1:] if ln.strip()]
        head = lines[0] if lines and lines[0].startswith("#") else "# run.log — %s v%s" % (SKILL_NAME, VERSION)
        _write_text(path, "\n".join([head,
                                     "# ... %d earlier line(s) trimmed ..." % max(0, len(rest) - LOG_TAIL)]
                                    + rest[-LOG_TAIL:]))
    except Exception:
        pass


def runlog(out, stage, event, **fields):
    """Append one line to <out>/run.log.  Never raises."""
    try:
        target = _log_path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.stat().st_size == 0:
            _write_text(target, "# run.log — %s v%s · append-only · UTC\n"
                        "# columns: UTC | stage | event | key=value ..." % (SKILL_NAME, VERSION))
        parts = ["%s" % stamp(), "stage=%s" % stage, "event=%s" % event]
        for key in sorted(fields):
            parts.append("%s=%s" % (key, _short(fields[key])))
        with target.open("a", encoding="utf-8") as handle:
            handle.write(" | ".join(parts) + "\n")
        if target.stat().st_size > LOG_CAP:
            _trim_log(target)
        return True
    except Exception:
        return False


def log_meta(out):
    """Digest of run.log for result.json and self_check.json."""
    try:
        target = _log_path(out)
        text = _read_text(target)
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        stages, events, done, errors = [], 0, 0, []
        for line in lines:
            hit = re.search(r"stage=(\S+)", line)
            if hit and hit.group(1) not in stages:
                stages.append(hit.group(1))
            hit = re.search(r"event=(\S+)", line)
            if hit:
                events += 1
                if hit.group(1) == "done" and re.search(r"(^|\| )exit=0( \||$)", line):
                    done += 1
                if hit.group(1) == "error":
                    errors.append(line[:160])
        return {"path": "run.log", "exists": target.is_file(),
                "bytes": target.stat().st_size if target.is_file() else 0,
                "lines": len(lines), "stages": stages, "events": events,
                "done_exit_zero": done, "error_events": errors[:3]}
    except Exception as exc:
        return {"path": "run.log", "exists": False, "bytes": 0, "lines": 0,
                "stages": [], "events": 0, "done_exit_zero": 0,
                "error_events": ["log_meta: %s" % exc]}


# ------------------------------------------------------------------- golden
def _describe_contract(key):
    low = str(key or "").lower()
    for pattern, artifact, text in CONTRACT_TEXT:
        if re.search(pattern, low):
            return artifact, text
    return ("result.json",
            "契约字段 %s 原样回填：键名不改、不漏键；非空值或显式 "
            "not_separately_produced，缺值写 null/[]" % key)


def _quote_of(block, cap=300):
    """Verbatim prefix of a material block (safe to quote)."""
    try:
        text = str(block.get("text") or "").strip()
    except Exception:
        return ""
    return text[:cap]


def _case_rel(index):
    """Relative path of the contract file, so it is not quoted as material."""
    if index.get("case_rel"):
        return index["case_rel"]
    try:
        root = Path(index.get("input_root") or "")
        if root.is_dir():
            found = M.find_case(root)
            if found:
                return found.relative_to(root).as_posix()
    except Exception:
        pass
    return None


def _is_case_block(index, block):
    rel = _case_rel(index)
    return bool(rel) and block.get("file") == rel


def _anchor_blocks(index, cap=2):
    """Blocks that mention a figure/table label (used as expected xrefs)."""
    found = []
    for block in index.get("blocks") or []:
        if _is_case_block(index, block):
            continue
        if XREF_RE.search(block.get("text") or ""):
            found.append(block)
            if len(found) >= cap:
                break
    return found


def _choose_points(series):
    """Endpoints, extremes and up to six well-spread points of one series."""
    points = list(series.get("pts") or [])
    if not points:
        return []
    if len(points) <= 6:
        return points
    order = [points[0], points[-1]]
    order += [max(points, key=lambda p: p.get("y") if p.get("y") is not None else 0),
              min(points, key=lambda p: p.get("y") if p.get("y") is not None else 0)]
    step = max(1, len(points) // 4)
    order += [points[i] for i in range(0, len(points), step)]
    seen, chosen = set(), []
    for point in order:
        key = (point.get("x"), point.get("y"), point.get("loc"))
        if key in seen:
            continue
        seen.add(key)
        chosen.append(point)
        if len(chosen) >= 6:
            break
    return chosen


def build_golden(index):
    """Expected content of this case, from output_contract + indexed material."""
    contract = list(index.get("contract") or M.BASE_FIELDS)
    items, readouts, facts = [], [], []
    case_id = index.get("case_id")

    # 1) one item per output_contract key (no material source -> basis=contract)
    for order, key in enumerate(contract, 1):
        artifact, expect = _describe_contract(key)
        items.append({"id": "C%02d" % order, "kind": "contract", "field": str(key),
                      "artifact": artifact, "expect": expect, "basis": "contract",
                      "locator": None, "quote": None})

    # 2) expected sections; Results carries xref anchors when the material has them
    anchors = _anchor_blocks(index)
    for order, (name, _head_re, expect) in enumerate(SECTION_SPECS, 1):
        entry = {"id": "S%02d" % order, "kind": "section", "section": name,
                 "expect": expect, "basis": "contract", "locator": None, "quote": None}
        if name == "Results" and anchors:
            entry.update({"basis": "source", "locator": anchors[0].get("loc"),
                          "quote": _quote_of(anchors[0])})
            entry["anchors"] = [{"locator": b.get("loc"), "quote": _quote_of(b)} for b in anchors]
        items.append(entry)

    # 3) expected readouts: table series first, quoted blocks as fallback
    try:
        tables = [t for t in (index.get("tables") or []) if t.get("rows") and t.get("header")]
    except Exception:
        tables = []
    for table in tables[:2]:
        series = M.make_series(table)
        if not series:
            continue
        unit, cond = series["value"].get("unit") or "", series.get("cond")
        for point in _choose_points(series):
            block = M.resolve_block(index, point.get("loc")) if point.get("loc") else None
            if not block:
                continue
            item = {"id": "R%02d" % (len(readouts) + 1), "kind": "readout",
                    "value": _num_text(point.get("y")), "unit": unit,
                    "condition": (_num_text(point.get("x")) + " "
                                  + ((cond or {}).get("unit") or "")).strip()
                    if point.get("x") is not None else None,
                    "spread": _num_text(point.get("d")) if point.get("d") is not None else None,
                    "n": _num_text(point.get("n")) if point.get("n") is not None else None,
                    "locator": block.get("loc"), "quote": _quote_of(block),
                    "basis": "source",
                    "expect": "正文报告 %s%s 这一读数（条件 %s），并给图/表编号与 n/SD"
                              % (_num_text(point.get("y")), unit,
                                 ((_num_text(point.get("x")) + " "
                                   + ((cond or {}).get("unit") or "")).strip()
                                  if point.get("x") is not None else "给定条件"))}
            readouts.append(item)
            if len(readouts) >= READOUT_CAP:
                break
        if len(readouts) >= READOUT_CAP:
            break
    if not readouts:
        for block in index.get("blocks") or []:
            if _is_case_block(index, block):
                continue
            if str(block.get("text") or "").startswith(M.VISUAL_TAG):
                continue
            tokens = M.scan_quantities(block.get("text") or "")
            if not tokens:
                continue
            token = tokens[0]
            readouts.append({"id": "R%02d" % (len(readouts) + 1), "kind": "readout",
                             "value": token.get("raw"), "unit": token.get("unit") or "",
                             "condition": None, "spread": None, "n": None,
                             "locator": block.get("loc"), "quote": _quote_of(block),
                             "basis": "source",
                             "expect": "正文报告读数 %s%s，并标出可用 locator 的来源"
                                       % (token.get("raw"), token.get("unit") or "")})
            if len(readouts) >= min(READOUT_CAP, 8):
                break
    items.extend(readouts)

    # 4) expected preserved facts: caption / statistics / method lines of the material
    for block in index.get("blocks") or []:
        if len(facts) >= FACT_CAP:
            break
        if _is_case_block(index, block):
            continue
        text = str(block.get("text") or "")
        if not text or text.startswith(M.VISUAL_TAG):
            continue
        if not (CAPTION_HINT.search(text) or STAT_RE.search(text)):
            continue
        facts.append({"id": "F%02d" % (len(facts) + 1), "kind": "fact",
                      "locator": block.get("loc"), "quote": _quote_of(block),
                      "basis": "source",
                      "expect": "该材料事实须在 preserved_facts / evidence_map 中逐字保留并带 locator"})
    items.extend(facts)

    sourced = [x for x in items if x.get("basis") == "source"]
    verified = 0
    for item in sourced:
        try:
            if M.verify_citation(index, item.get("quote"), item.get("locator"))[0] in (
                    "exact", "span", "misplaced"):
                verified += 1
        except Exception:
            pass
    return {
        "schema": "golden-standard/1",
        "skill": SKILL_NAME, "skill_version": VERSION,
        "case_id": case_id, "generated_at": stamp(),
        "basis": "output_contract 逐键 + /input 材料逐条 locator/quote；"
                 "无材料来源的项标 basis=contract",
        "items": items,
        "contract_items": [x for x in items if x["kind"] == "contract"],
        "section_items": [x for x in items if x["kind"] == "section"],
        "readout_items": readouts, "fact_items": facts,
        "counts": {"total": len(items), "contract": len(contract),
                   "sections": len(SECTION_SPECS), "readouts": len(readouts),
                   "facts": len(facts), "sourced": len(sourced),
                   "contract_only": len(items) - len(sourced)},
        "verification": {"quote_total": len(sourced), "quote_verbatim": verified,
                         "quote_hit_rate": round(verified / len(sourced), 3) if sourced else 0.0},
    }


# --------------------------------------------------------------------- diff
def _section_report(manuscript):
    """(has_results, has_discussion, has_limits, results_sections, disc_sections,
        limit_items, paragraph_count)."""
    text = manuscript or ""
    results_hit = re.search(r"^##\s*\d+\.\s*(Results|结果)", text, re.M)
    disc_hit = re.search(r"^##\s*\d+\.\s*(Discussion|讨论)", text, re.M)
    limit_hit = re.search(r"^#{2,4}\s*(Limitations|局限性|局限)[^\n]*", text, re.M)
    results_sections = disc_sections = 0
    if results_hit:
        tail = text[results_hit.end():]
        stop = re.search(r"^##\s*\d+\.", tail, re.M)
        results_sections = len(re.findall(r"^###\s*\d+\.\d+",
                                          tail[:stop.start()] if stop else tail, re.M))
    if disc_hit:
        disc_sections = len(re.findall(r"^###\s*\d+\.\d+", text[disc_hit.end():], re.M))
    limit_items = 0
    if limit_hit:
        tail = text[limit_hit.end():]
        stop = re.search(r"^##\s", tail, re.M)
        limit_items = len(re.findall(r"^[-*•]\s+", tail[:stop.start()] if stop else tail, re.M))
    paragraphs = len([ln for ln in text.splitlines()
                      if ln.strip() and not ln.startswith("#") and not ln.startswith("- ")])
    return (results_hit is not None, disc_hit is not None, limit_hit is not None,
            results_sections, disc_sections, limit_items, paragraphs)


def _value_in_text(raw, text):
    """Boundary-aware presence of a rendered number in normalised text."""
    if not raw or not text:
        return False
    pattern = r"(?<![\d.])" + re.escape(str(raw)) + r"(?![\d.])"
    return re.search(pattern, text) is not None


def _actual_contract(key, value, payload, manuscript):
    """One-line description of what was actually delivered for a contract key."""
    try:
        low = str(key or "").lower()
        if re.search(r"deliver|manuscript|draft|正文", low):
            return "manuscript.md %d 字节 / %d 段" % (
                len((manuscript or "").encode("utf-8")),
                len([ln for ln in (manuscript or "").splitlines()
                     if ln.strip() and not ln.startswith("#")]))
        if re.search(r"preserv|fact|事实", low):
            return "%d 条事实（含 quote+locator）" % len(value or [])
        if re.search(r"evidence|source|证据|来源", low):
            return "%d 条证据条目" % len(value or [])
        if re.search(r"change|log|修改", low):
            return "%d 条修改记录" % len((value or {}).get("changes") or [])
        if re.search(r"limit|局限", low):
            items = (value or {}).get("items") or []
            return "%d 条局限" % len(items)
        if re.search(r"uncertain|pending|人工", low):
            return "%d 条待确认" % len((payload.get("pending_human") or []))
        if re.search(r"result.?map|readout|读数", low):
            return "results_map.json（%d 条读数）" % ((value or {}).get("sections") or 0)
        if isinstance(value, dict):
            return "已回填（%d 个键）" % len(value)
        if isinstance(value, list):
            return "已回填（%d 项）" % len(value)
        return "已回填"
    except Exception:
        return "已回填"


def render_diff(golden, payload, manuscript, counters):
    """Markdown comparison: expected item vs actual delivery, with reasons."""
    rows = []

    def add(item_id, expect, actual, status, reason):
        rows.append({"id": item_id, "expect": _short(expect, 150), "actual": _short(actual, 150),
                     "status": status, "reason": _short(reason, 160)})

    # contract fields
    for item in golden.get("contract_items") or []:
        key = item.get("field")
        value = payload.get(key)
        if key not in payload:
            add(item["id"], item["expect"], "缺少顶层键", "缺失",
                "result.json 未回填该契约键")
        elif isinstance(value, dict) and value.get("status") == "not_separately_produced":
            add(item["id"], item["expect"], "not_separately_produced", "偏差",
                "该字段未单独产出，已显式标注并指向 manuscript.md / 结果映射（诚实降级）")
        elif value in (None, "", [], {}):
            add(item["id"], item["expect"], "空值", "偏差",
                "键存在但无可交付内容；材料缺口应同时写进 pending_human/degradations")
        else:
            add(item["id"], item["expect"], _actual_contract(key, value, payload, manuscript),
                "达标", "契约键存在且非空，键名/顺序未被改写")

    # sections
    (has_results, has_disc, has_limits, results_sections, disc_sections,
     limit_items, _paragraphs) = _section_report(manuscript)
    section_state = {"Results": (has_results, results_sections),
                     "Discussion": (has_disc, disc_sections), "Limitations": (has_limits, limit_items)}
    for item in golden.get("section_items") or []:
        name = item["section"]
        present, count = section_state.get(name, (False, None))
        if not present:
            add(item["id"], item["expect"], "标题缺失", "缺失", "manuscript.md 中未找到该节标题")
        elif name == "Limitations" and (count or 0) < 2:
            add(item["id"], item["expect"], "节存在，局限 %s 条" % count, "偏差",
                "局限少于 2 条，未达到契约下限")
        elif name == "Results" and not results_sections:
            add(item["id"], item["expect"], "节存在但无小节", "偏差", "Results 无 ### 小节，组织性不足")
        else:
            add(item["id"], item["expect"], "节存在（%s 项）" % (count if count is not None else "—"),
                "达标", "节标题与内容存在")

    # readouts
    try:
        norm_manuscript = M.normalize(manuscript)
    except Exception:
        norm_manuscript = ""
    map_values = set()
    for section in (counters or {}).get("results_map_sections") or []:
        for readout in section.get("readouts") or []:
            raw = str(readout.get("token") or "").replace(" ", "")
            if raw:
                map_values.add(raw)
                try:
                    map_values.add(M.render_number(float(readout.get("value"))))
                except Exception:
                    pass
    for item in golden.get("readout_items") or []:
        raw = item.get("value")
        in_body = _value_in_text(raw, norm_manuscript)
        in_map = bool(map_values) and (str(raw) in map_values)
        if in_body:
            add(item["id"], item["expect"], "正文命中 %s%s" % (raw, item.get("unit") or ""),
                "达标", "读数写入正文且可回查 results_map")
        elif in_map:
            add(item["id"], item["expect"], "仅 results_map 命中", "偏差",
                "读数已记录但未写进正文，Results 覆盖不完整")
        else:
            add(item["id"], item["expect"], "正文未出现该读数", "缺失",
                "材料中有此值，但交付正文未转写（若有意省略需在 change_log/pending_human 说明）")

    # facts
    delivered = []
    for fact in (counters or {}).get("facts") or []:
        delivered.append(fact)
    delivered += [e for e in ((counters or {}).get("evidence") or [])
                  if isinstance(e, dict)]
    norm_delivered = [(M.normalize(x.get("quote") or ""), x) for x in delivered
                      if isinstance(x, dict) and x.get("quote")]
    for item in golden.get("fact_items") or []:
        want = M.normalize(item.get("quote") or "")
        hit = None
        for quote, entry in norm_delivered:
            if len(want) >= 8 and (want in quote or (len(quote) >= 8 and quote in want)):
                hit = entry
                break
        if hit is None:
            add(item["id"], item["expect"], "未在事实/证据表中出现", "缺失",
                "该材料事实没有被 preserved_facts 或 evidence_map 覆盖")
        elif hit.get("verified") in ("exact", "span", "misplaced"):
            add(item["id"], item["expect"], "逐字命中（%s）" % hit.get("verified"), "达标",
                "事实已保留且引文可在材料中逐字复核")
        else:
            add(item["id"], item["expect"], "命中但未逐字（%s）" % hit.get("verified"), "偏差",
                "引文与材料不一致，需回材料复制原文")

    summary = {"total": len(rows),
               "达标": sum(1 for row in rows if row["status"] == "达标"),
               "偏差": sum(1 for row in rows if row["status"] == "偏差"),
               "缺失": sum(1 for row in rows if row["status"] == "缺失")}
    summary["met"] = summary["达标"]
    summary["deviated"] = summary["偏差"]
    summary["missing"] = summary["缺失"]
    summary["pass_rate"] = round(summary["达标"] / summary["total"], 3) if summary["total"] else 0.0

    audit = (payload.get("metrics") or {}).get("self_audit") or {}
    audit_text = "%s/%s" % (audit.get("passed"),
                            (audit.get("passed") or 0) + (audit.get("failed") or 0)) \
        if audit else "-"
    lines = ["# 金标准对照报告（diff report）", "",
             "本报告由 `build` 在真实运行末尾生成：把 `/app/output` 的实际交付与 "
             "`golden_standard.json` 的期望项逐项对照，给出达标 / 偏差 / 缺失与原因。",
             "",
             "- case_id：`%s`" % (golden.get("case_id") or payload.get("case_id")),
             "- 状态：`%s` · self-audit：`%s` · mode：`%s`" % (
                 payload.get("status"), audit_text, payload.get("metrics", {}).get("mode")),
             "- 期望项：%d（契约 %d / 章节 %d / 读数 %d / 事实 %d）" % (
                 summary["total"], len(golden.get("contract_items") or []),
                 len(golden.get("section_items") or []),
                 len(golden.get("readout_items") or []), len(golden.get("fact_items") or [])),
             "- 结果：达标 %d · 偏差 %d · 缺失 %d · 达标率 %.1f%%" % (
                 summary["达标"], summary["偏差"], summary["缺失"], 100 * summary["pass_rate"]),
             "",
             "| # | 期望（摘自 golden_standard.json） | 实际 | 状态 | 原因 / 处置 |",
             "|---|---|---|---|---|"]
    for row in rows:
        lines.append("| %s | %s | %s | **%s** | %s |" % (
            row["id"], row["expect"].replace("|", "/"), row["actual"].replace("|", "/"),
            row["status"], row["reason"].replace("|", "/")))
    lines += ["", "## 偏差项处置", ""]
    actionable = [row for row in rows if row["status"] != "达标"][:10]
    if not actionable:
        lines.append("- 无：全部期望项达标。")
    for row in actionable:
        lines.append("- `%s`（%s）：%s → %s" % (row["id"], row["status"], row["actual"], row["reason"]))
    lines += ["", "## 判据", "",
              "1. 契约项以 `result.json` 顶层键存在且非空为准；未单独产出但显式标注的记为偏差而非缺失。",
              "2. 章节项以 `manuscript.md` 的二级/三级标题与局限条数为准。",
              "3. 读数项以正文逐字出现或以 `results_map.json` 记录为准；两者都没有才是缺失。",
              "4. 事实项以 `preserved_facts.json` / `evidence_map.json` 的逐字引文命中为准。",
              ""]
    return "\n".join(lines), summary, rows


# ------------------------------------------------------------ version history
def _static_history():
    text = _read_text(STATIC_HISTORY)
    if text.strip():
        return text.rstrip() + "\n"
    return ("# 版本与回退记录：%s\n\nv0 → v1.0.0：新增 5 个核验资产；原入口与调用方式不变。\n"
            "回退：删除 `scripts/rd_assets.py` 与 `references/version_history.md`，"
            "`result.json` 去掉 5 个新增顶层键即可回到 v0 行为。\n" % SKILL_NAME)


def render_version_history(out, payload, manuscript, stats):
    """Static package history + this-run section."""
    lines = [_static_history().rstrip(), "", "---", "",
             "## 本次运行（build 自动追加，不改写上文静态部分）", "",
             "- 时间（UTC）：%s" % stamp(),
             "- 运行：stage=build · mode=`%s` · status=`%s` · case_id=`%s`" % (
                 stats.get("mode"), payload.get("status"), payload.get("case_id")),
             "- 主产物：`manuscript.md` %d 字节，sha256[:16] `%s`" % (
                 len((manuscript or "").encode("utf-8")), sha16((manuscript or "").encode("utf-8"))),
             "- 运行期资产：`golden_standard.json`、`diff_report.md`、`self_check.json`、`run.log`"
             "（本文件追加段生成时已写入前三者与日志）",
             "- 契约回填：%s / %s 个键（缺失：%s）" % (
                 (payload.get("contract_fields") or {}).get("filled"),
                 (payload.get("contract_fields") or {}).get("total"),
                 ", ".join((payload.get("contract_fields") or {}).get("missing") or []) or "无"),
             "- 降级与异常（%d 条）：" % len(payload.get("degradations") or [])]
    for item in (payload.get("degradations") or [])[:8]:
        lines.append("  - %s" % item)
    if not payload.get("degradations"):
        lines.append("  - 无")
    lines += ["", "### 本次运行的回退方式", "",
              "1. 仅撤销本次运行记录：用包内 `references/version_history.md` 覆盖 "
              "`/app/output/version_history.md`，静态部分即恢复。",
              "2. 回到 v0 包行为：删除 `scripts/rd_assets.py` 与 `references/version_history.md`，"
              "恢复 v0 的 `scripts/rd_sections.py`；`result.json` 去掉 5 个新增顶层键。",
              "3. 主产物不回退：`manuscript.md` 等原有产物与 v0 同输入逐字节一致（本包仅在 build 末追加资产）。",
              ""]
    return "\n".join(lines)


# -------------------------------------------------------------- self check
def _probe_degraded_inputs(work):
    """Really execute the empty-input and bad-JSON fallback paths."""
    probes = []
    base = Path(work) / "_asset_probes"
    probe_draft = {
        "title": "degradation probe", "language": "en",
        "results": [{"heading": "probe", "xref": [], "paragraphs": ["Probe body 1.0."]}],
        "discussion": [{"heading": "probe", "xref": [], "paragraphs": ["Probe boundary."]}],
        "limitations": ["Method level: probe.", "Statistics level: probe."],
    }

    def run_probe(name, prepare):
        try:
            directory = prepare()
            case, case_error = M.read_case(directory)
            keys = M.contract_keys(case) if isinstance(case, dict) else list(M.BASE_FIELDS)
            index = M.build_index(directory, keys)
            text, _lang = M.render_markdown(probe_draft, M.SECTION_LABELS)
            blocks = len(index.get("blocks") or [])
            ok = bool(text.strip()) and ("## 1." in text)
            return {"case": name, "blocks": blocks, "render_bytes": len(text.encode("utf-8")),
                    "pass": ok, "note": "空/坏输入也渲染出合法稿件骨架"}
        except Exception as exc:
            return {"case": name, "pass": False, "error": "%s: %s" % (type(exc).__name__, exc)}

    def empty_dir():
        path = base / "empty_input"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def bad_json_dir():
        path = base / "bad_case_json"
        path.mkdir(parents=True, exist_ok=True)
        _write_text(path / "case.json", '{"case_id": "PROBE", "output_contract": {')
        _write_text(path / "notes.md", "Fig. 2C. Probe caption with 12.5% at 3 nM.\n\nANOVA p = 0.02.\n")
        return path

    for name, prepare in (("empty_input", empty_dir), ("bad_case_json", bad_json_dir)):
        result = run_probe(name, prepare)
        if name == "bad_case_json":
            try:
                _case, error = M.read_case(base / name)
                result["case_error"] = str(error)[:120]
                result["contract_fallback"] = list(M.contract_keys(None))
                result["pass"] = bool(result.get("pass")) and bool(error)
            except Exception as exc:
                result["pass"] = False
                result["error"] = "%s: %s" % (type(exc).__name__, exc)
        probes.append(result)
    return probes


def _artifact_rows(out, manuscript):
    rows = []
    names = ["manuscript.md", "results_discussion.md", "results_map.json",
             "evidence_map.json", "preserved_facts.json", "change_log.json",
             "result.json", "golden_standard.json", "diff_report.md",
             "version_history.md", "run.log"]
    for name in names:
        path = Path(out) / name
        exists = path.is_file()
        size = path.stat().st_size if exists else 0
        note = None
        if name == "result.json":
            note = "本文件在资产生成后还会被回填 5 个新字段，大小以最终文件为准"
        elif name == "run.log":
            note = "自检后仍会追加 main() 的 done 行与 finalize 行，最终字节数略大"
        rows.append({"path": name, "exists": exists, "bytes": size,
                     "sha256_16": sha16(path) if exists else "-", "note": note})
    return rows


def build_selfcheck(out, work, index, payload, manuscript, counters, golden_meta,
                    diff_meta, log_stat, mode, contract):
    """Machine receipt for this build; never raises."""
    contract = list(contract or [])
    checks, details = {}, {}

    # 1) contract keys: every key present at top level, name unchanged
    missing = [str(k) for k in contract if str(k) not in payload]
    empty = [str(k) for k in contract
             if str(k) in payload and payload.get(str(k)) in (None, "", [], {})]
    checks["contract_complete"] = not missing
    details["contract"] = {"total": len(contract), "present": len(contract) - len(missing),
                           "missing": missing, "empty_but_present": empty,
                           "filled": (payload.get("contract_fields") or {}).get("filled"),
                           "note": "空值不算缺失：材料无该项时 honest degradation"}

    # 2) main deliverable exists and is non-empty
    manuscript_path = Path(out) / "manuscript.md"
    plain_path = Path(out) / "results_discussion.md"
    main_ok = bool((manuscript or "").strip()) and manuscript_path.is_file() and \
        manuscript_path.stat().st_size > 0
    plain_ok = plain_path.is_file() and plain_path.stat().st_size > 0
    checks["main_artifacts"] = main_ok and plain_ok
    details["artifacts"] = {"manuscript": {"exists": manuscript_path.is_file(),
                                           "bytes": manuscript_path.stat().st_size
                                           if manuscript_path.is_file() else 0},
                            "results_discussion": {"exists": plain_ok},
                            "note": "主产物为可编辑 Markdown"}

    # 3) quote hit rate: delivered evidence + golden anchors, verbatim in material
    delivered = [e for e in (counters or {}).get("evidence") or [] if isinstance(e, dict)]
    delivered_ok = [e for e in delivered if e.get("verified") in ("exact", "span", "misplaced")]
    golden_anchors = [x for x in (golden_meta or {}).get("anchor_items") or []
                      if x.get("quote") and x.get("locator")]
    golden_ok = 0
    for item in golden_anchors:
        try:
            if M.verify_citation(index, item.get("quote"), item.get("locator"))[0] in (
                    "exact", "span", "misplaced"):
                golden_ok += 1
        except Exception:
            pass
    total = len(delivered) + len(golden_anchors)
    hit = len(delivered_ok) + golden_ok
    ratio = round(hit / total, 3) if total else 0.0
    if total:
        quote_pass = hit == total
    else:
        quote_pass = str(payload.get("status")) != "ok"
    checks["evidence_quote_hit"] = quote_pass
    details["quotes"] = {"delivered_total": len(delivered), "delivered_verbatim": len(delivered_ok),
                         "golden_total": len(golden_anchors), "golden_verbatim": golden_ok,
                         "hit_rate": ratio, "pass": quote_pass,
                         "note": "0 条可核时仅在非 ok 状态下通过（空/坏输入诚实降级）"}

    # 4) count consistency
    numbers_total = (counters or {}).get("numbers_total", 0)
    balanced = ((counters or {}).get("numbers_verified", 0)
                + (counters or {}).get("numbers_unverified", 0) == numbers_total)
    contract_filled = (payload.get("contract_fields") or {}).get("filled")
    contract_total = (payload.get("contract_fields") or {}).get("total")
    contract_present = all(str(k) in payload for k in contract)
    assets_written = [name for name in ASSETS[:4] if (Path(out) / name).is_file()
                      and (Path(out) / name).stat().st_size > 0]
    counts_ok = balanced and contract_present and len(assets_written) == 4
    checks["counts_consistent"] = counts_ok
    details["counts"] = {"numbers_total": numbers_total,
                         "numbers_balanced": balanced,
                         "contract_keys_present": contract_present,
                         "contract_filled": contract_filled, "contract_total": contract_total,
                         "assets_written_before_selfcheck": assets_written,
                         "note": "契约键完整性以 result.json 顶层键存在为准（材料缺口导致的空值"
                                 "不算缺失，由 diff_report 记为偏差）；"
                                 "numbers_verified + numbers_unverified == numbers_total"}

    # 5) degraded-input probes (really executed)
    probes = _probe_degraded_inputs(work)
    checks["degradation_fallback"] = all(p.get("pass") for p in probes) if probes else False
    details["degradation_tests"] = probes

    # 6) exit-code policy + observed log evidence
    log_stat = log_stat or {}
    observed_errors = log_stat.get("error_events") or []
    exit_ok = bool(log_stat.get("exists")) and len(log_stat.get("stages") or []) >= 1 \
        and not observed_errors
    checks["exit_code_zero"] = exit_ok
    details["exit_codes"] = {"policy": "main() 捕获所有异常并恒返回 0；"
                                       "意外异常走 safe_fail，仍写合法 result.json 与最小资产",
                             "current_stage": "build", "observed_done_exit_zero":
                                 log_stat.get("done_exit_zero", 0),
                             "error_events": observed_errors,
                             "note": "self_check 在 build 返回前生成；build-only 运行时 "
                                     "done 行由 main() 随后追加，observed_done_exit_zero 可能为 0，"
                                     "不代表非零退出",
                             "pass": exit_ok}

    # 7) run.log sanity
    log_ok = bool(log_stat.get("exists")) and log_stat.get("bytes", 0) > 0 \
        and log_stat.get("events", 0) >= 2
    checks["run_log"] = log_ok
    details["run_log"] = {"bits": log_stat, "pass": log_ok}

    passed = sum(1 for ok in checks.values() if ok)
    summary = {"total": len(checks), "passed": passed, "failed": len(checks) - passed,
               "failed_checks": [name for name, ok in checks.items() if not ok]}
    return {"schema": "self-check/1", "skill": SKILL_NAME, "skill_version": VERSION,
            "case_id": payload.get("case_id"), "generated_at": stamp(),
            "mode": mode, "status": payload.get("status"),
            "checks": checks, "summary": summary,
            "overall_pass": not summary["failed_checks"],
            "artifacts": _artifact_rows(out, manuscript),
            "details": details}


# --------------------------------------------------------------------- final
def _golden_anchor_items(golden):
    """Sourced items of the golden standard, for self-check quote verification."""
    try:
        return [x for x in golden.get("items") or []
                if x.get("basis") == "source" and x.get("quote") and x.get("locator")]
    except Exception:
        return []


def finalize(out, work, index, payload, manuscript, counters, mode):
    """Write the five assets and return the result.json field payloads."""
    out, work = Path(out), Path(work)
    out.mkdir(parents=True, exist_ok=True)
    meta = {}
    runlog(out, "build", "assets_begin",
           assets=",".join(ASSETS), status=payload.get("status"), mode=mode)

    # 1) golden_standard.json
    golden = {}
    try:
        golden = build_golden(index)
        _write_json(out / "golden_standard.json", golden)
        meta["golden_standard"] = {
            "path": "golden_standard.json", "schema": golden.get("schema"),
            "items": golden["counts"]["total"], "contract_items": golden["counts"]["contract"],
            "sections": golden["counts"]["sections"],
            "readouts": golden["counts"]["readouts"], "facts": golden["counts"]["facts"],
            "sourced": golden["counts"]["sourced"], "basis_contract": golden["counts"]["contract_only"],
            "quote_hit_rate": golden["verification"]["quote_hit_rate"],
            "bytes": (out / "golden_standard.json").stat().st_size,
            "sha256_16": sha16(out / "golden_standard.json"),
            "note": "金标准只列期望与来源；达标与否见 diff_report.md"}
        runlog(out, "assets", "golden_ok", items=golden["counts"]["total"],
               sourced=golden["counts"]["sourced"],
               quotes=golden["verification"]["quote_hit_rate"])
    except Exception as exc:
        golden = {"schema": "golden-standard/1", "case_id": payload.get("case_id"),
                  "error": "%s: %s" % (type(exc).__name__, exc),
                  "items": [], "contract_items": [], "section_items": [],
                  "readout_items": [], "fact_items": [],
                  "counts": {"total": 0, "contract": 0, "sections": 0, "readouts": 0,
                             "facts": 0, "sourced": 0, "contract_only": 0},
                  "verification": {"quote_total": 0, "quote_verbatim": 0, "quote_hit_rate": 0.0}}
        _write_json(out / "golden_standard.json", golden)
        meta["golden_standard"] = {"path": "golden_standard.json", "status": "error",
                                   "error": golden["error"],
                                   "bytes": (out / "golden_standard.json").stat().st_size,
                                   "items": 0}
        runlog(out, "assets", "golden_error", error=golden["error"])

    # 2) diff_report.md
    try:
        report, summary, _rows = render_diff(golden, payload, manuscript, counters or {})
        _write_text(out / "diff_report.md", report)
        meta["diff_report"] = {"path": "diff_report.md", "total": summary["total"],
                               "met": summary["met"], "deviated": summary["deviated"],
                               "missing": summary["missing"],
                               "pass_rate": summary["pass_rate"],
                               "bytes": (out / "diff_report.md").stat().st_size,
                               "sha256_16": sha16(out / "diff_report.md")}
        runlog(out, "assets", "diff_ok", total=summary["total"], met=summary["met"],
               deviated=summary["deviated"], missing=summary["missing"])
    except Exception as exc:
        text = ("# 金标准对照报告（生成失败降级）\n\n- 生成时间：%s\n- 错误：`%s: %s`\n"
                "- 处置：请按 `golden_standard.json` 手工逐项核对 `manuscript.md` 与 "
                "`result.json`，并在修复脚本后重跑 build。\n"
                % (stamp(), type(exc).__name__, exc))
        _write_text(out / "diff_report.md", text)
        meta["diff_report"] = {"path": "diff_report.md", "status": "error",
                               "error": "%s: %s" % (type(exc).__name__, exc),
                               "bytes": (out / "diff_report.md").stat().st_size}
        runlog(out, "assets", "diff_error", error=meta["diff_report"]["error"])

    # 3) version_history.md
    try:
        text = render_version_history(out, payload, manuscript,
                                      {"mode": mode, "out": str(out)})
        _write_text(out / "version_history.md", text)
        meta["version_history"] = {"path": "version_history.md", "from": "v0", "to": VERSION,
                                   "static_source": "references/version_history.md",
                                   "runtime_appended": True,
                                   "bytes": (out / "version_history.md").stat().st_size,
                                   "sha256_16": sha16(out / "version_history.md")}
        runlog(out, "assets", "version_ok", versions="v0->v1.0.0")
    except Exception as exc:
        _write_text(out / "version_history.md",
                    "# 版本记录（生成失败降级）\n\n- v0 → v1.0.0：5 个核验资产\n- 错误：`%s: %s`\n"
                    % (type(exc).__name__, exc))
        meta["version_history"] = {"path": "version_history.md", "status": "error",
                                   "error": "%s: %s" % (type(exc).__name__, exc),
                                   "bytes": (out / "version_history.md").stat().st_size}
        runlog(out, "assets", "version_error", error=meta["version_history"]["error"])

    # 4) run.log digest (the file itself has been appended throughout)
    meta["run_log"] = log_meta(out)
    meta["run_log"].update({"exit_code_policy": "always 0", "stage": "build"})
    runlog(out, "assets", "log_ok", lines=meta["run_log"].get("lines"),
           stages=",".join(meta["run_log"].get("stages") or []))

    # 5) self_check.json (needs the first four + the log)
    try:
        log_stat = log_meta(out)
        checks = build_selfcheck(out, work, index, payload, manuscript, counters or {},
                                 {"anchor_items": _golden_anchor_items(golden)},
                                 meta.get("diff_report") or {}, log_stat, mode,
                                 index.get("contract") or M.BASE_FIELDS)
        _write_json(out / "self_check.json", checks)
        meta["self_check"] = {"path": "self_check.json",
                              "overall_pass": checks["overall_pass"],
                              "checks": checks["checks"],
                              "summary": checks["summary"],
                              "bytes": (out / "self_check.json").stat().st_size,
                              "sha256_16": sha16(out / "self_check.json")}
        runlog(out, "assets", "selfcheck_done", overall=checks["overall_pass"],
               passed=checks["summary"]["passed"], failed=checks["summary"]["failed"],
               failed_checks=",".join(checks["summary"]["failed_checks"]))
    except Exception as exc:
        stub = {"schema": "self-check/1", "skill": SKILL_NAME, "overall_pass": False,
                "error": "%s: %s" % (type(exc).__name__, exc),
                "checks": {"selfcheck_generation": False},
                "summary": {"total": 1, "passed": 0, "failed": 1,
                            "failed_checks": ["selfcheck_generation"]}}
        _write_json(out / "self_check.json", stub)
        meta["self_check"] = {"path": "self_check.json", "overall_pass": False,
                              "error": stub["error"],
                              "bytes": (out / "self_check.json").stat().st_size,
                              "checks": stub["checks"],
                              "summary": stub["summary"]}
        runlog(out, "assets", "selfcheck_error", error=stub["error"])

    runlog(out, "build", "finalize_ok",
           assets=len([1 for name in ASSETS if (out / name).is_file()
                       and (out / name).stat().st_size > 0]),
           status=payload.get("status"), mode=mode)
    meta["run_log"] = log_meta(out)
    meta["run_log"].update({"exit_code_policy": "always 0", "stage": "build",
                            "note": "main() 返回前还会追加 done 行，最终字节数略大；"
                                    "self_check 的 run_log 项以自检时点为准"})
    return meta


# ------------------------------------------------------------- safe failure
def safe_assets(out, exc):
    """Last-resort stubs after an unexpected crash; still five non-empty files."""
    out = Path(out)
    try:
        out.mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    message = "%s: %s" % (type(exc).__name__, exc)
    runlog(out, "safe_fail", "error", exception=message)
    try:
        if not (out / "golden_standard.json").is_file():
            _write_json(out / "golden_standard.json",
                        {"schema": "golden-standard/1", "skill": SKILL_NAME,
                         "status": "safe_fail", "error": message, "items": [],
                         "note": "运行异常，金标准未能生成；请查看 run.log 与 result.json.errors"})
    except Exception:
        pass
    try:
        if not (out / "diff_report.md").is_file():
            _write_text(out / "diff_report.md",
                        "# 金标准对照报告（安全失败降级）\n\n- 状态：safe_fail\n- 错误：`%s`\n"
                        "- 处置：修复后重跑 build；result.json 仍为合法契约回填。\n" % message)
    except Exception:
        pass
    try:
        if not (out / "version_history.md").is_file():
            _write_text(out / "version_history.md",
                        _static_history() + "\n---\n\n## 本次运行（safe_fail）\n\n"
                        "- 时间（UTC）：%s\n- 错误：`%s`\n" % (stamp(), message))
    except Exception:
        pass
    try:
        if not (out / "self_check.json").is_file():
            _write_json(out / "self_check.json",
                        {"schema": "self-check/1", "skill": SKILL_NAME,
                         "overall_pass": False, "status": "safe_fail", "error": message,
                         "checks": {"pipeline_completed": False},
                         "summary": {"total": 1, "passed": 0, "failed": 1,
                                     "failed_checks": ["pipeline_completed"]}})
    except Exception:
        pass
    for name in ASSETS:
        try:
            path = out / name
            if not path.is_file() or path.stat().st_size == 0:
                _write_text(path, "safe_fail: %s\n" % message)
        except Exception:
            pass
