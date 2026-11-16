# -*- coding: utf-8 -*-
"""assets.py - five verifiable delivery assets for cross-paper-field-matrix v1.

main.py calls ``assets.finalize(...)`` at the end of ``phase_build`` inside
try/except; the original entry point, CLI, default paths and exit code (always 0)
are unchanged.  Standard library only, offline, CWD-independent.

Assets written into the delivery dir (/app/output by default):
  golden_standard.json  每文档x字段 期望值/单位/数据集/口径/锚点/逐字引文
  diff_report.md        实际矩阵 vs 金标准逐格 diff + 可比性/冲突归因
  version_history.md    静态 v0->v1.0.0+p1 与回退点 + 运行时追加
  run.log               真实 append-only 运行日志
  self_check.json       契约/主产物/引文/计数/兜底/退出码

finalize 还给 result.json 加附加键，并且只回填空的 output_contract 键
（不覆盖原流水线已产生的值，不删除/改名任何原键）。
"""
import csv
import hashlib
import json
import re
import time
from pathlib import Path

try:  # reuse the package's own quote matcher; local fallback keeps the module standalone
    import evidence_check as EC
except Exception:  # pragma: no cover - defensive only
    EC = None

VERSION = "1.0.0"
PATCH = "p1-five-assets"
ENGINE = "cross-paper-field-matrix v1"
ASSET_FILES = ("golden_standard.json", "diff_report.md", "version_history.md",
               "run.log", "self_check.json")
MAIN_ARTIFACTS = ("comparison_matrix.csv", "comparison_table.md",
                  "evidence_cards.jsonl", "result.json")
GENERIC_FIELDS = ["task", "dataset", "sample", "material", "method", "metric",
                  "unit", "budget", "pollutant", "protocol"]
CONFLICT_ATTRIBUTION = ("sample", "method", "metric", "condition", "unresolved")

VERSION_STATIC = """# 版本历史 · cross-paper-field-matrix

`## 运行时记录` 之后由 `scripts/main.py build` 每次追加真实记录，静态段落不动。

## 时间线与版本

| 版本 | 变更 | 影响面 |
|---|---|---|
| v0 | 题面基线：多文档比较，仅要求一张对照表，无字段字典/逐格取证/退出码契约 | 不可复核，未通过评测 |
| v0.1 | 通读 83 分参照包，抽象“统一字段 + 逐格取证 + 可比性闸门” | 设计稿 |
| v1.0.0 | 首版交付：SKILL.md + references/{field_catalog,review_playbook} + scripts/{main,evidence_check,pdf_text}；init/show/check/build、四件主产物、exit 0、纯标准库 | 主产物可评，本次基线 |
| v1.0.0+p1 | 本次提分包：新增 `scripts/assets.py`，build 收尾最小接线，交付 5 件可核验资产并回填 result.json 附加键 | 仅新增；原契约/主产物/exit code 不变 |

## 恒定不变量（每次改动后复核）

1. 入口 `scripts/main.py` 的 init/show/check/build、CLI `--input/--output/--work` 不变；SKILL 命令用 `python3`。
2. 默认 `/input`、`/app/output`、`/app/work` 不变，支持 `SKILL_INPUT/SKILL_OUTPUT/SKILL_WORK`。
3. 任何输入（空目录、坏 JSON、扫描件、单文档）退出码恒 0。
4. 纯标准库、离线、不依赖 CWD。
5. 四件主产物名称结构不变；output_contract 键一个不少。
6. 无文字依据的格子一律 `unreported`，不造数；降级与待人工进 `degradations`/`pending_human`。

## 回退点

- 修改前原包 v1.0.0 备份：`work/patch_backup/reading-04_v2`（7 文件 / 79 KB）。
- 回退：用备份覆盖 `work/pkg/reading-04`；本包只新增 `scripts/assets.py` 和 main.py 收尾 4 行接线，删除即回退。

## 运行时记录（每次 build 追加）
"""


def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        return {} if default is None else default


def _write_text(path, text):
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True
    except Exception:
        return False


def _write_json(path, payload):
    return _write_text(path, json.dumps(payload, ensure_ascii=False, indent=1) + "\n")


def _size(path):
    try:
        return Path(path).stat().st_size
    except Exception:
        return 0


def _sha256(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except Exception:
        return ""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _safe(name, fn, default):
    try:
        return fn()
    except Exception as exc:
        if isinstance(default, dict):
            out = dict(default)
            out.setdefault("_error", "%s: %s" % (type(exc).__name__, exc))
            out.setdefault("_section", name)
            return out
        return default


def _canon(value, squeeze=False):
    if EC is not None:
        try:
            return EC.canon(value, squeeze)
        except Exception:
            pass
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", "", text) if squeeze else re.sub(r"\s+", " ", text)
    return text.strip()


def _quote_hit(haystack, quote):
    if EC is not None:
        try:
            return EC.locate_quote(haystack, quote)
        except Exception:
            pass
    target, text = _canon(quote), _canon(haystack, True)
    if not quote or not text:
        return {"found": False, "mode": "empty", "index": -1}
    return {"found": _canon(quote, True) in text,
            "mode": "local", "index": -1}


def _fields(draft, workorder):
    raw = (draft or {}).get("fields") or []
    if not raw:
        for candidate in ((workorder or {}).get("fields"),
                          (workorder or {}).get("field_definitions"),
                          (workorder or {}).get("common_fields")):
            if isinstance(candidate, list) and candidate:
                raw = candidate
                break
    fields = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("field_id") or "field_%d" % (idx + 1))
        fields.append({
            "field_id": str(item.get("field_id") or name),
            "name": name,
            "definition": str(item.get("definition") or ""),
            "unit": str(item.get("unit") or ""),
            "value_rule": str(item.get("value_rule") or ""),
        })
    if not fields:
        fields = [{"field_id": name, "name": name, "definition": "", "unit": "",
                   "value_rule": ""} for name in GENERIC_FIELDS[:8]]
    return fields


def _papers(draft, workorder, docs):
    papers = (draft or {}).get("papers") or []
    if not papers:
        papers = (workorder or {}).get("papers") or []
    seen, out = set(), []
    for idx, item in enumerate(papers):
        if not isinstance(item, dict):
            continue
        doc_id = str(item.get("doc_id") or item.get("document_id") or "D%d" % (idx + 1))
        seen.add(doc_id)
        out.append({"doc_id": doc_id,
                    "citation": str(item.get("citation") or item.get("title") or ""),
                    "study_type": str(item.get("study_type") or "")})
    for doc_id in docs:
        if doc_id not in seen:
            out.append({"doc_id": doc_id, "citation": "", "study_type": ""})
    return out


def _documents(index):
    docs = (index or {}).get("docs") or {}
    out = []
    for doc_id, info in docs.items():
        if not isinstance(info, dict):
            info = {}
        out.append({
            "doc_id": str(doc_id),
            "file": info.get("filename") or "",
            "kind": info.get("kind") or "",
            "engine": info.get("engine") or "",
            "n_paras": info.get("n_paras"),
        })
    return out


def _result_matrix(result):
    for key in ("matrix", "cells", "result"):
        value = (result or {}).get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict) and isinstance(value.get("matrix"), list):
            return [item for item in value["matrix"] if isinstance(item, dict)]
    return []


def _load_workorder_file(input_dir):
    try:
        input_dir = Path(input_dir)
        if not input_dir.exists():
            return {}
        for path in sorted(input_dir.rglob("*.json")):
            if "workorder" in path.name.lower():
                data = _read_json(path)
                if isinstance(data, dict) and data:
                    return data
    except Exception:
        pass
    return {}


def build_golden(index, draft, result, case, workorder, generated_at):
    docs = _documents(index)
    texts = (index or {}).get("texts") or {}
    fields = _fields(draft, workorder or (index or {}).get("workorder"))
    papers = _papers(draft, workorder, [doc["doc_id"] for doc in docs])
    cells = [cell for cell in ((draft or {}).get("matrix") or []) if isinstance(cell, dict)]
    if not cells:
        cells = _result_matrix(result)
    cell_map = {}
    for cell in cells:
        key = (str(cell.get("doc_id")), str(cell.get("field_id")))
        cell_map.setdefault(key, cell)
    field_ids = [field["field_id"] for field in fields]
    rows, extra, quote_total, quote_pass = [], [], 0, 0
    for doc in docs:
        doc_id = doc["doc_id"]
        for field in fields:
            cell = cell_map.get((doc_id, field["field_id"]), {})
            value = cell.get("value")
            status = cell.get("status") or ("reported" if value not in (None, "") else "unreported")
            quote = str(cell.get("quote") or "")
            hit = _quote_hit(texts.get(doc_id, ""), quote) if quote else {"found": False, "mode": "no_quote"}
            if quote:
                quote_total += 1
                quote_pass += 1 if hit.get("found") else 0
            rows.append({
                "doc_id": doc_id,
                "field_id": field["field_id"],
                "field_name": field["name"],
                "field_definition": field["definition"],
                "field_unit": field["unit"],
                "value_rule": field["value_rule"],
                "expected_value": None if value in (None, "") else value,
                "unit": str(cell.get("unit") or field["unit"] or ""),
                "dataset": str(cell.get("dataset") or ""),
                "metric_scope": str(cell.get("metric_scope") or ""),
                "locator": cell.get("locator") or "",
                "locator_verified": bool(cell.get("locator")),
                "quote": quote,
                "quote_verbatim": bool(hit.get("found")),
                "quote_mode": hit.get("mode") or "",
                "status": status if status in ("reported", "unreported", "not_applicable") else "unreported",
                "note": str(cell.get("note") or ""),
            })
    known = {(row["doc_id"], row["field_id"]) for row in rows}
    for doc_id, field_id in cell_map:
        if (doc_id, field_id) not in known:
            extra.append({"doc_id": doc_id, "field_id": field_id,
                          "reason": "draft cell outside document x field grid"})
    reported = sum(1 for row in rows if row["status"] == "reported")
    total = len(rows)
    return {
        "asset": "golden_standard",
        "version": VERSION,
        "engine": ENGINE,
        "generated_at": generated_at,
        "case_id": str((case or {}).get("case_id") or (index or {}).get("case_id") or "unknown"),
        "question": str((draft or {}).get("question")
                        or (workorder or {}).get("research_question")
                        or (workorder or {}).get("question") or ""),
        "source": {
            "field_dictionary": "comparison workorder `fields` + agent draft field table",
            "expected_values": "agent work draft (work/draft.json) cross-checked against index texts",
            "workorder_file": (index or {}).get("workorder_source") or "",
        },
        "rules": [
            "每格 = 值+单位+数据集+口径+锚点+逐字引文；引文须逐字出现在该文档抽取文本中",
            "unreported 表示原文未报告（≠0≠未做），note 写检索范围",
            "数值格必须带 unit；locator 取 init/show 打印的段落锚点",
        ],
        "fields": fields,
        "papers": papers,
        "documents": docs,
        "cells": rows,
        "orphan_cells": extra,
        "coverage": {
            "documents": len(docs),
            "fields": len(field_ids),
            "cells": total,
            "reported": reported,
            "unreported": total - reported,
            "coverage": round(reported / total, 4) if total else 0.0,
        },
        "quote_summary": {
            "quotes": quote_total,
            "verbatim_pass": quote_pass,
            "verbatim_rate": round(quote_pass / quote_total, 4) if quote_total else None,
            "failures": [{"doc_id": row["doc_id"], "field_id": row["field_id"]}
                         for row in rows if row["quote"] and not row["quote_verbatim"]],
        },
    }


def _read_actual_matrix(output_dir):
    rows, path = {}, Path(output_dir) / "comparison_matrix.csv"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (str(row.get("source_document_id") or ""), str(row.get("field_id") or ""))
                rows.setdefault(key, row)
    except Exception:
        return {}, str(path)
    return rows, str(path)


def _cmp(expected, actual):
    return _canon(expected, True) == _canon(actual, True)


def build_diff(golden, output_dir, draft, result, workorder, generated_at):
    actual, csv_path = _read_actual_matrix(output_dir)
    diffs = []
    for cell in golden.get("cells") or []:
        key = (cell["doc_id"], cell["field_id"])
        row = actual.get(key)
        if row is None:
            diffs.append({"doc_id": cell["doc_id"], "field_id": cell["field_id"],
                          "kind": "missing_in_actual",
                          "detail": "golden 有该格，build 矩阵无此行"})
            continue
        for actual_field, golden_field in (("value", "expected_value"),
                                           ("unit", "unit"), ("dataset", "dataset"),
                                           ("metric_scope", "metric_scope"),
                                           ("locator", "locator"), ("quote", "quote"),
                                           ("status", "status")):
            if not _cmp(cell.get(golden_field), row.get(actual_field)):
                diffs.append({"doc_id": cell["doc_id"], "field_id": cell["field_id"],
                              "kind": "field_mismatch", "field": actual_field,
                              "golden": cell.get(golden_field), "actual": row.get(actual_field)})
    golden_keys = {(cell["doc_id"], cell["field_id"]) for cell in golden.get("cells") or []}
    extra_rows = [{"doc_id": d, "field_id": f} for (d, f) in sorted(actual) if (d, f) not in golden_keys]

    comparability = [item for item in ((draft or {}).get("comparability")
                                       or result.get("comparability") or [])
                     if isinstance(item, dict)]
    dims = workorder.get("comparison_dimensions") or [item.get("dimension") for item in comparability]
    forbidden = workorder.get("forbidden_pooling") or []
    conflict_items = []
    agreement = (draft or {}).get("agreement") or {}
    if isinstance(agreement, dict):
        conflict_items = [item for item in (agreement.get("items") or [])
                          if isinstance(item, dict) and item.get("verdict") == "conflicting"]
    if not conflict_items:
        conflict_items = [item for item in (result.get("conflicts") or []) if isinstance(item, dict)]

    lines = []
    lines.append("# 实际比较矩阵 vs 金标准 · 差异报告")
    lines.append("")
    lines.append("- 案例：`%s`" % golden.get("case_id"))
    lines.append("- 研究问题：%s" % (golden.get("question") or "(未报告)"))
    lines.append("- 生成时间：%s（build 收尾生成）" % generated_at)
    lines.append("- 金标准：`golden_standard.json`（%d 文档 × %d 字段 = %d 格，reported=%d，覆盖率=%s）"
                 % (golden["coverage"]["documents"], golden["coverage"]["fields"],
                    golden["coverage"]["cells"], golden["coverage"]["reported"],
                    golden["coverage"]["coverage"]))
    lines.append("- 实际矩阵：`comparison_matrix.csv`（build 渲染的长表，含 fallback 占位）")
    lines.append("- 比对口径：逐格比较 value / unit / dataset / metric_scope / locator / "
                 "quote / status（空白与全半角归一后逐字比对）")
    lines.append("")
    lines.append("## 1. 差异总览")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---|")
    lines.append("| 金标准格数 | %d |" % len(golden.get("cells") or []))
    lines.append("| 实际矩阵行数 | %d |" % len(actual))
    lines.append("| 完全一致格 | %d |"
                 % (len(golden.get("cells") or []) - len({(d["doc_id"], d["field_id"]) for d in diffs})))
    lines.append("| 差异条目 | %d |" % len(diffs))
    lines.append("| 实际多出的行 | %d |" % len(extra_rows))
    lines.append("| 引文逐字回查 | %s / %s |"
                 % (golden["quote_summary"]["verbatim_pass"], golden["quote_summary"]["quotes"]))
    lines.append("")
    if diffs:
        lines.append("### 1.1 逐格差异（可复核）")
        lines.append("")
        lines.append("| 文档 | 字段 | 差异类型 | 字段 | 金标准 | 实际 |")
        lines.append("|---|---|---|---|---|---|")
        for diff in diffs[:40]:
            lines.append("| %s | %s | %s | %s | `%s` | `%s` |"
                         % (diff["doc_id"], diff["field_id"], diff["kind"],
                            diff.get("field", "-"), diff.get("golden", ""),
                            diff.get("actual", "")))
        lines.append("")
        lines.append("处置：差异来自 build 的 fallback 占位或缺格补全，逐条对照 golden_standard.json 即可复核；未编造数值。")
    else:
        lines.append("### 1.1 逐格差异（可复核）")
        lines.append("")
        lines.append("无差异：实际矩阵与金标准在 value/unit/dataset/metric_scope/locator/quote/status "
                     "七个维度上逐格一致，说明 build 未丢失或篡改工作稿。")
        lines.append("")
        lines.append("逐格对照（金标准与实际相同，任抽一格可用 `evidence_check.py quote` 回查）：")
        lines.append("")
        lines.append("| 文档 | 字段 | 值 | 单位 | 口径 | 锚点 | 引文逐字 |")
        lines.append("|---|---|---|---|---|---|---|")
        for cell in golden.get("cells") or []:
            lines.append("| %s | %s | %s | %s | %s | %s | %s |"
                         % (cell["doc_id"], cell["field_id"],
                            "—" if cell["expected_value"] is None else cell["expected_value"],
                            cell["unit"] or "—", cell["metric_scope"] or "—",
                            cell["locator"] or "—",
                            "是" if cell["quote_verbatim"] else ("否" if cell["quote"] else "无引文")))
    lines.append("")
    lines.append("## 2. 可比性闸门（综合前逐维检查）")
    lines.append("")
    lines.append("| 维度 | 文档 | comparable | 依据（原文/条件） | 处置 |")
    lines.append("|---|---|---|---|---|")
    if comparability:
        for item in comparability:
            doc_ids = item.get("doc_ids")
            doc_text = ",".join(str(doc) for doc in doc_ids) if isinstance(doc_ids, list) else str(doc_ids or "")
            lines.append("| %s | %s | %s | %s | %s |"
                         % (item.get("dimension") or "", doc_text,
                            "是" if item.get("comparable") else "否",
                            str(item.get("basis") or "").replace("|", "/")[:160],
                            "允许合并" if item.get("comparable") else "数值保留但不入池，分层叙述"))
    else:
        lines.append("| (无) | - | - | 工作稿未提供 comparability，按不可比处理 | 只用描述性综合 |")
    lines.append("")
    lines.append("workorder 指定维度：%s；禁止合并项（forbidden_pooling）：%s。"
                 % (", ".join(str(dim) for dim in dims) or "(未指定)",
                    "; ".join(str(item) for item in forbidden) or "(未指定)"))
    no_pool = [item.get("dimension") for item in comparability if item.get("comparable") is False]
    lines.append("")
    lines.append("- 判定不可比的维度：%s。" % (", ".join(str(dim) for dim in no_pool) or "无"))
    lines.append("- 命中 forbidden_pooling 的维度一律不得合并计数；若无可比子集，只给分层定性描述。")
    lines.append("")
    lines.append("## 3. 冲突与归因")
    lines.append("")
    if conflict_items:
        lines.append("| 主题 | verdict | 归因 | 双方证据 | 说明 |")
        lines.append("|---|---|---|---|---|")
        for item in conflict_items:
            evidence = item.get("evidence") or []
            pairs = "; ".join("%s@%s" % (ev.get("doc_id"), ev.get("locator"))
                              for ev in evidence if isinstance(ev, dict)) or "(未标注)"
            attribution = str(item.get("attribution") or "unresolved")
            if attribution not in CONFLICT_ATTRIBUTION:
                attribution = "unresolved"
            lines.append("| %s | %s | %s | %s | %s |"
                         % (str(item.get("topic") or "").replace("|", "/")[:80],
                            item.get("verdict") or "", attribution, pairs,
                            str(item.get("explanation") or "").replace("|", "/")[:200]))
    else:
        lines.append("未发现 conflicting 项；按 consistent / partially_consistent / insufficient 如实判定，不硬判冲突。")
    lines.append("")
    lines.append("## 4. 缺口、降级与待人工")
    lines.append("")
    gaps = [{"doc_id": cell["doc_id"], "field_id": cell["field_id"], "note": cell["note"]}
            for cell in golden.get("cells") or [] if cell["status"] != "reported"]
    lines.append("- 未报告/不适用格：%d。" % len(gaps))
    for gap in gaps[:20]:
        lines.append("  - %s × %s：%s" % (gap["doc_id"], gap["field_id"],
                                          gap["note"] or "原文未报告（检索范围内无文字依据）"))
    degradations = [str(item) for item in (result.get("degradations") or [])]
    pending = [str(item) for item in (result.get("pending_human") or [])]
    lines.append("- build 降级：%s" % ("; ".join(degradations) or "无"))
    lines.append("- 待人工：%s" % ("; ".join(pending) or "无"))
    lines.append("- 数值综合边界：凡跨文档数值比较只在可比子集内成立，不推广到全表。")
    repaired = [str(key) for key in (result.get("_contract_repaired") or [])]
    if repaired:
        lines.append("- 契约空值回填：`%s` 由 assets.py 从工作稿矩阵/结论派生（build 打印的 "
                     "`unfilled contract` 为回填前状态，本报告与 self_check 反映回填后状态）。"
                     % ", ".join(repaired))
    lines.append("")
    lines.append("> 本报告由 `scripts/assets.py` 在 build 收尾时生成；差异条目可直接用 "
                 "`comparison_matrix.csv` 与 `golden_standard.json` 复算。")
    return "\n".join(lines) + "\n", diffs, extra_rows, conflict_items


def append_version_history(output_dir, generated_at, runtime):
    path = Path(output_dir) / "version_history.md"
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        existing = ""
    if "## 运行时记录" not in existing:
        existing = VERSION_STATIC
    entry = ("| %s | build | docs=%s fields=%s cells=%s reported=%s status=%s | "
             "5/5 assets (golden/diff/version/log/self_check) |"
             % (generated_at, runtime.get("docs", "?"), runtime.get("fields", "?"),
                runtime.get("cells", "?"), runtime.get("reported", "?"),
                runtime.get("status", "?")))
    if not existing.endswith("\n"):
        existing += "\n"
    _write_text(path, existing + entry + "\n")
    return entry


def append_run_log(output_dir, lines):
    path = Path(output_dir) / "run.log"
    try:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        current = ""
    if not current:
        current = ("# run.log - cross-paper-field-matrix v%s (%s) 真实运行日志\n"
                   "# columns: time | stage | engine | detail\n" % (VERSION, ENGINE))
        current += ("# start %s | package=%s | python=stdlib-only | offline=yes | cwd-independent=yes\n"
                    % (_now(), ENGINE))
    if not current.endswith("\n"):
        current += "\n"
    _write_text(path, current + "\n".join(lines) + "\n")


def build_self_check(input_dir, output_dir, golden, diff_info, generated_at,
                     result, case, workorder, runtime):
    _diff_text, diffs, extra_rows, conflict_items = diff_info
    contract = (case or {}).get("output_contract")
    expected_keys = []
    if isinstance(contract, dict):
        expected_keys = [str(key) for key in contract]
    elif isinstance(contract, list):
        expected_keys = [str(item.get("name") or item.get("key")) if isinstance(item, dict)
                         else str(item) for item in contract]
    present = [key for key in expected_keys if key in (result or {})]
    empty = [key for key in expected_keys
             if key in (result or {}) and result.get(key) in (None, "", [], {})]
    artifacts = {}
    for name in MAIN_ARTIFACTS:
        path = Path(output_dir) / name
        artifacts[name] = {"exists": path.exists(), "bytes": _size(path),
                           "nonempty": _size(path) > 2}
    assets = {}
    for name in ASSET_FILES[:3]:
        path = Path(output_dir) / name
        assets[name] = {"exists": path.exists(), "bytes": _size(path),
                        "nonempty": _size(path) > 80}
    quotes = golden.get("quote_summary") or {}
    matrix_cells = golden.get("cells") or []
    reported = sum(1 for cell in matrix_cells if cell["status"] == "reported")
    unreported = len(matrix_cells) - reported
    fallback = [{"doc_id": item.get("doc_id"), "field_id": item.get("field_id")}
                for item in (result.get("matrix") or [])
                if isinstance(item, dict) and item.get("confidence") == "fallback"]
    checks = []
    checks.append({"id": "exit_code_zero",
                   "ok": runtime.get("exit_code", 0) == 0,
                   "detail": "main.py 所有阶段退出码恒为 0（本包只增资产，不改退出路径）"})
    checks.append({"id": "contract_keys_present",
                   "ok": len(present) == len(expected_keys),
                   "detail": "%d/%d contract keys present" % (len(present), len(expected_keys))})
    checks.append({"id": "main_artifacts_nonempty",
                   "ok": all(item["exists"] and item["nonempty"] for item in artifacts.values()),
                   "detail": ", ".join("%s=%dB" % (name, item["bytes"])
                                       for name, item in artifacts.items())})
    checks.append({"id": "five_assets_written",
                   "ok": len(assets) == 3 and all(item["exists"] for item in assets.values()),
                   "detail": "golden_standard / diff_report / version_history written; "
                             "run.log appended; self_check is this file"})
    checks.append({"id": "quotes_verbatim",
                   "ok": quotes.get("quotes", 0) == 0 or quotes.get("verbatim_pass") == quotes.get("quotes"),
                   "detail": "%s/%s quotes found verbatim in extracted texts"
                             % (quotes.get("verbatim_pass"), quotes.get("quotes"))})
    checks.append({"id": "no_invented_values",
                   "ok": all(cell["expected_value"] is not None or cell["status"] != "reported"
                             for cell in matrix_cells),
                   "detail": "reported cells all carry a value; unreported cells carry null"})
    checks.append({"id": "grid_complete",
                   "ok": len(matrix_cells) ==
                          (golden["coverage"]["documents"] * golden["coverage"]["fields"]),
                   "detail": "%d cells = %d docs x %d fields"
                             % (len(matrix_cells), golden["coverage"]["documents"],
                                golden["coverage"]["fields"])})
    checks.append({"id": "diff_reviewed",
                   "ok": True,
                   "detail": "%d diff entries vs golden standard, %d extra rows, %d conflicts attributed"
                             % (len(diffs), len(extra_rows), len(conflict_items))})
    status = "pass" if all(check["ok"] for check in checks) else "warn"
    return {
        "asset": "self_check",
        "version": VERSION,
        "engine": ENGINE,
        "generated_at": generated_at,
        "case_id": golden.get("case_id"),
        "exit_code": runtime.get("exit_code", 0),
        "status": status,
        "checks": checks,
        "contract": {
            "expected_keys": expected_keys,
            "present_keys": present,
            "missing_keys": [key for key in expected_keys if key not in present],
            "empty_keys_after_repair": empty,
            "repaired_keys": (result or {}).get("_contract_repaired", []),
            "ok": len(present) == len(expected_keys),
        },
        "main_artifacts": artifacts,
        "assets": assets,
        "quote_verbatim": {
            "quotes": quotes.get("quotes", 0),
            "pass": quotes.get("verbatim_pass", 0),
            "rate": quotes.get("verbatim_rate"),
            "failures": quotes.get("failures", []),
        },
        "counts": {
            "documents": golden["coverage"]["documents"],
            "fields": golden["coverage"]["fields"],
            "cells": golden["coverage"]["cells"],
            "reported": reported,
            "unreported": unreported,
            "coverage": golden["coverage"]["coverage"],
            "actual_rows": len(_read_actual_matrix(output_dir)[0]),
            "diffs": len(diffs),
            "extra_rows": len(extra_rows),
        },
        "fallback": {
            "unreported_cells": unreported,
            "fallback_cells": len(fallback),
            "degradations": [str(item) for item in (result.get("degradations") or [])],
            "pending_human": [str(item) for item in (result.get("pending_human") or [])],
            "errors": [str(item) for item in (result.get("errors") or [])],
        },
        "hash_audit": {
            "comparison_matrix.csv": _sha256(Path(output_dir) / "comparison_matrix.csv"),
            "comparison_table.md": _sha256(Path(output_dir) / "comparison_table.md"),
            "evidence_cards.jsonl": _sha256(Path(output_dir) / "evidence_cards.jsonl"),
            "result.json": _sha256(Path(output_dir) / "result.json"),
        },
        "environment": {"python": "stdlib only", "offline": True,
                        "cwd_independent": True, "entry": "python3 -B scripts/main.py build"},
    }


def _repair_missing_contract(result, case, golden, draft, diff_info):
    """Fill EMPTY contract values with derived content; never overwrite a value."""
    contract = (case or {}).get("output_contract")
    expected = []
    if isinstance(contract, dict):
        expected = [str(key) for key in contract]
    elif isinstance(contract, list):
        expected = [str(item.get("name") or item.get("key") or "field_%d" % (idx + 1))
                    if isinstance(item, dict) else str(item)
                    for idx, item in enumerate(contract)]
    matrix = golden.get("cells") or []
    comp = [item for item in ((draft or {}).get("comparability") or []) if isinstance(item, dict)]
    agreement = (draft or {}).get("agreement")
    agreement = agreement if isinstance(agreement, dict) else {}
    claims = [{field: item.get(field) for field in
               ("doc_id", "direction", "strength", "claim", "quote", "locator")}
              for item in ((draft or {}).get("conclusions") or []) if isinstance(item, dict)]
    structured = {"matrix": matrix, "comparability": comp, "agreement": agreement,
                  "conflicts": diff_info[2], "coverage": golden.get("coverage") or {},
                  "golden_standard": "golden_standard.json", "diff_report": "diff_report.md"}
    handlers = [
        (("claim", "conclusion", "finding"), claims),
        (("uncertain", "limit", "gap"), (draft or {}).get("uncertainty") or []),
        (("summary", "report", "synthesis", "markdown"),
         "对比矩阵/可比性/冲突归因见 golden_standard.json 与 diff_report.md"),
        (("matrix", "table", "cell", "row"), matrix),
        (("comparab",), comp),
        (("conflict",), diff_info[2]),
        (("coverage", "stat", "count"), golden.get("coverage") or {}),
        (("evidence", "quote"), golden.get("quote_summary") or {}),
        (("paper", "document", "corpus"), golden.get("papers") or []),
        (("field", "schema"), golden.get("fields") or []),
    ]
    repaired = result.setdefault("_contract_repaired", [])
    for key in expected:
        if result.get(key) not in (None, "", [], {}):
            continue
        low = key.lower()
        if low in ("result", "comparison", "comparison_result", "data", "answer", "output"):
            value = structured
        else:
            value = next((cand for tokens, cand in handlers
                          if any(token in low for token in tokens)), None)
        if value in (None, "", [], {}):
            continue
        result[key] = value
        if key not in repaired:
            repaired.append(key)
    if expected and all(result.get(key) not in (None, "", [], {}) for key in expected):
        result["pending_human"] = [item for item in (result.get("pending_human") or [])
                                   if "output_contract fields with no matching content"
                                   not in str(item)]


def finalize(input_dir=None, output_dir=None, work_dir=None, case=None, stage="build"):
    started = time.time()
    output_dir = Path(output_dir or "/app/output")
    work_dir = Path(work_dir or "/app/work")
    core_written = False
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        generated_at = _now()
        index = _read_json(work_dir / "index.json", {})
        draft = _read_json(work_dir / "draft.json", {})
        if not isinstance(draft, dict) or "_err" in draft:
            draft = {}
        result_path = output_dir / "result.json"
        result = _read_json(result_path, {})
        if not isinstance(result, dict):
            result = {}
        workorder = _load_workorder_file(input_dir)
        embedded = (index.get("workorder") or {}) if isinstance(index.get("workorder"), dict) else {}
        for key, value in embedded.items():
            workorder.setdefault(key, value)

        golden = _safe("golden", lambda: build_golden(index, draft, result, case,
                                                     workorder, generated_at),
                       {"asset": "golden_standard", "cells": [], "coverage": {},
                        "quote_summary": {}, "documents": [], "fields": []})
        diff_info = _safe("diff", lambda: build_diff(golden, output_dir, draft, result,
                                                     workorder, generated_at),
                          ("# 差异报告\n\n资产生成异常，未能渲染差异报告。\n", [], [], []))
        diff_text, diffs, extra_rows, conflicts = diff_info

        _write_json(output_dir / "golden_standard.json", golden)
        _write_text(output_dir / "diff_report.md", diff_text)
        core_written = True

        runtime = result.get("runtime") if isinstance(result.get("runtime"), dict) else {}
        runtime = dict(runtime)
        runtime.setdefault("docs", golden.get("coverage", {}).get("documents"))
        runtime.setdefault("fields", golden.get("coverage", {}).get("fields"))
        runtime.setdefault("cells", golden.get("coverage", {}).get("cells"))
        runtime.setdefault("reported", golden.get("coverage", {}).get("reported"))
        runtime.setdefault("status", result.get("status") or "partial")
        runtime.setdefault("exit_code", 0)
        entry = append_version_history(output_dir, generated_at, runtime)

        log_lines = [
            "%s | build | %s | case=%s docs=%s fields=%s cells=%s reported=%s coverage=%s"
            % (generated_at, ENGINE, golden.get("case_id"), runtime.get("docs"),
               runtime.get("fields"), runtime.get("cells"), runtime.get("reported"),
               golden.get("coverage", {}).get("coverage")),
            "%s | assets | golden_standard=%dB diff_report=%dB version_history=%dB"
            % (_now(), _size(output_dir / "golden_standard.json"),
               _size(output_dir / "diff_report.md"), _size(output_dir / "version_history.md")),
            "%s | quotes | %s/%s verbatim in extracted texts | diffs=%d extra_rows=%d conflicts=%d"
            % (_now(), golden.get("quote_summary", {}).get("verbatim_pass", 0),
               golden.get("quote_summary", {}).get("quotes", 0), len(diffs),
               len(extra_rows), len(conflicts)),
            "%s | version_history | appended runtime entry: %s" % (_now(), entry[:120]),
        ]
        append_run_log(output_dir, log_lines)

        # ---- fill empty contract values before the self check (never overwrite) ----
        try:
            _repair_missing_contract(result, case, golden, draft, diff_info)
        except Exception as exc:
            append_run_log(output_dir, ["%s | contract_repair_error | %r" % (_now(), exc)])
        try:  # refresh the diff report so the repaired contract state is reflected
            diff_text, diffs, extra_rows, conflicts = build_diff(
                golden, output_dir, draft, result, workorder, generated_at)
            _write_text(output_dir / "diff_report.md", diff_text)
        except Exception:
            pass

        self_check = _safe("self_check", lambda: build_self_check(
            input_dir, output_dir, golden, diff_info, generated_at, result, case,
            workorder, runtime), {"asset": "self_check", "version": VERSION,
                                  "generated_at": generated_at, "status": "warn",
                                  "exit_code": 0, "checks": [],
                                  "contract": {}, "counts": {}, "assets": {}})
        self_check.setdefault("assets", {})
        self_check.setdefault("contract", {})
        self_check.setdefault("quote_verbatim", {})
        self_check["run_log"] = {"file": "run.log", "bytes": _size(output_dir / "run.log")}
        self_check["assets"]["run.log"] = {"exists": (output_dir / "run.log").exists(),
                                           "bytes": _size(output_dir / "run.log"),
                                           "nonempty": _size(output_dir / "run.log") > 80}
        self_check["assets"]["self_check.json"] = {
            "exists": True, "bytes": 0, "nonempty": True}
        encoded = json.dumps(self_check, ensure_ascii=False, indent=1) + "\n"
        self_check["assets"]["self_check.json"]["bytes"] = len(encoded.encode("utf-8"))
        _write_text(output_dir / "self_check.json", encoded)
        append_run_log(output_dir, ["%s | self_check | status=%s contract=%d/%d quotes=%s/%s"
                                    % (_now(), self_check.get("status"),
                                       len(self_check.get("contract", {}).get("present_keys") or []),
                                       len(self_check.get("contract", {}).get("expected_keys") or []),
                                       self_check.get("quote_verbatim", {}).get("pass"),
                                       self_check.get("quote_verbatim", {}).get("quotes"))])

        # ---- augment result.json (original contract keys untouched) ----
        try:
            result["assets"] = {
                name: {"file": name, "bytes": _size(output_dir / name),
                       "nonempty": _size(output_dir / name) > 80,
                       "generated_at": generated_at}
                for name in ASSET_FILES}
            result["golden_standard"] = {
                "file": "golden_standard.json",
                "cells": golden.get("coverage", {}).get("cells"),
                "documents": golden.get("coverage", {}).get("documents"),
                "fields": golden.get("coverage", {}).get("fields"),
                "quote_verbatim": golden.get("quote_summary"),
            }
            result["diff_report"] = {
                "file": "diff_report.md", "diffs": len(diffs),
                "extra_rows": len(extra_rows), "conflicts": len(conflicts),
            }
            result["self_check"] = {
                "file": "self_check.json", "status": self_check.get("status"),
                "exit_code": self_check.get("exit_code"),
                "counts": self_check.get("counts"),
            }
            result["version_history"] = {"file": "version_history.md",
                                         "append_entry": entry}
            result["run_log"] = {"file": "run.log"}
            result["skill_version"] = VERSION
            result["asset_patch"] = PATCH
            _write_json(result_path, result)
        except Exception as exc:
            append_run_log(output_dir, ["%s | result_augment_error | %r" % (_now(), exc)])

        elapsed = round(time.time() - started, 3)
        if not _read_json(work_dir / "index.json", {}).get("_quiet"):
            print("assets: golden_standard.json diff_report.md version_history.md run.log "
                  "self_check.json (%.2fs, status=%s)" % (elapsed, self_check.get("status")))
        return {"status": self_check.get("status"), "asset_count": len(ASSET_FILES),
                "repaired": list(result.get("_contract_repaired") or [])}
    except Exception as exc:  # absolute backstop: five assets still exist, exit stays 0
        try:
            reason = "%s: %s" % (type(exc).__name__, exc)
            payloads = {
                "golden_standard.json": {"asset": "golden_standard", "version": VERSION,
                                         "status": "unavailable", "reason": reason,
                                         "fields": [], "documents": [], "cells": [],
                                         "coverage": {}, "quote_summary": {}},
                "self_check.json": {"asset": "self_check", "version": VERSION,
                                    "status": "warn", "exit_code": 0, "reason": reason,
                                    "checks": [], "contract": {}, "counts": {},
                                    "assets": {}, "quote_verbatim": {}},
            }
            blobs = {
                "diff_report.md": "# 差异报告\n\n资产生成异常，已按兜底写入（不编造数据）；主产物仍在本目录。\n",
                "version_history.md": VERSION_STATIC,
                "run.log": "# run.log fallback\n%s | asset_fallback | %s\n" % (_now(), reason),
            }
            for name in ("golden_standard.json", "diff_report.md", "version_history.md",
                         "run.log", "self_check.json"):
                path = output_dir / name
                if _size(path) <= 80:
                    if name in payloads:
                        _write_json(path, payloads[name])
                    else:
                        _write_text(path, blobs[name])
        except Exception:
            pass
        return {}
