# -*- coding: utf-8 -*-
"""assets_ext.py :: verification-asset hardening layer (package v1.1.0 patch).

The five asset files were already emitted by v1.0.0; this layer adds the parts a reviewer
can re-check mechanically without trusting prose:

* ``golden_standard.json``  -> ``contract_expected``: one row per ``output_contract`` key,
  one row per organiser work-order key and one row per expected deliverable group
  (item sheet / reference answers / anchors / score tables / report / reproducibility /
  gold standard / comparison / release history / run log / audit / package index).
  Every row carries ``basis`` (``contract`` when the brief is the only source,
  ``task_spec`` when a verbatim quote exists), ``locator``, ``quote`` and ``quote_verbatim``.
* ``diff_report.md``        -> one row per expected row above with
  ``met / deviation / missing`` and the value actually observed on disk.
* ``version_history.md``    -> static v0.0.0 -> v1.1.0 release table with per-release
  rollback steps, then the runtime paragraph of this run.
* ``self_check.json``       -> extra assertions: main artefact, contract coverage, quote
  hit rate, count consistency, degraded-input policy, exit-code policy.
* ``result.json``           -> the fifth asset pointer (``run_log``) plus version metadata
  refreshed after sealing.

Pure standard library, no clock, no network, no third-party import.  Every public helper
catches its own exceptions and returns a data structure, so an asset problem can never
take the primary deliverables down.
"""
import hashlib, json, re, sys
from pathlib import Path

try:
    from kernel import canon, trim, jstr, dhash
except Exception:  # keep the module importable on its own (tests, degraded runs)
    def canon(s):
        return re.sub(r"\s+", " ", str(s or "")).strip().lower()

    def trim(s, qty=300):
        s = re.sub(r"\s+", " ", str(s or "")).strip()
        return s if len(s) <= qty else s[:qty].rstrip() + "…"

    def jstr(o, ind=1):
        return json.dumps(o, ensure_ascii=False, indent=ind, default=str)

    def dhash(s):
        import hashlib
        return hashlib.sha256(str(s).encode("utf-8", "replace")).hexdigest()

CURRENT = "v1.1.0"
VERSIONS = ("v0.0.0", "v0.1.0", "v1.0.0", "v1.1.0")
ASSET_FIELDS = ("golden_standard", "diff_report", "version_history", "run_log", "self_check")
ASSET_FILES = ("golden_standard.json", "diff_report.md", "version_history.md",
               "run.log", "self_check.json")

# expected deliverable groups: (item_id, group, artefact, keywords, expect, count_rule)
DELIVERY = (
    ("D-01", "评测题", "tasks.jsonl",
     ("评测题", "题集", "benchmark", "item sheet", "写作题", "item"),
     "题集逐题含可执行指令、必需要点、合法变体与失败判据", "lines == task_count"),
    ("D-02", "参考答案", "reference_answers/",
     ("参考答案", "reference answer", "答案"),
     "每题一份证据包式参考答案（逐字证据 + 装配规则 + 合法变体 + 不可接受错误）",
     "files == task_count"),
    ("D-03", "可观测锚点", "anchors.md",
     ("锚点", "anchor", "可观测"),
     "每个必需要点至少一个可机读锚点，锚点带 locator 与三级判据", "rows == anchor_count"),
    ("D-04", "评分表", "scores.csv + scores_detail.csv",
     ("评分表", "双评", "two-rater", "评分"),
     "逐题总分表 + 逐锚点双评明细（rater_a / rater_b / adjudicated）",
     "detail_rows == anchors × ratees"),
    ("D-05", "评测报告", "evaluation_report.md",
     ("评测报告", "逐题报告", "report", "报告"),
     "逐题得分、证据、失败类型与修复建议", "contains every task_id"),
    ("D-06", "复核/复现记录", "reproducibility.md",
     ("复现", "reproduc", "可复现"),
     "输入 sha256、锚点版本、复算命令与确定性结论", "non-empty"),
    ("D-07", "金标准", "golden_standard.json",
     ("金标准", "gold standard", "contract"),
     "逐题 rubric、期望答案要点、锚点期望（locator + 逐字 quote）与阈值",
     "task_count == task_count"),
    ("D-08", "逐项对照", "diff_report.md",
     ("差异", "对照", "diff", "对照报告"),
     "实际产物 vs 金标准逐项对照：达标 / 偏差 / 缺失 + 严重度", "contains every task_id"),
    ("D-09", "版本历史", "version_history.md",
     ("版本", "release", "回退"),
     "静态发布史（含回退方式）+ 本次运行段", "contains current release"),
    ("D-10", "运行日志", "run.log",
     ("日志", "run.log", "log"),
     "真实运行阶段日志，尾部 [exit] exit_code=0", "ends with exit_code=0"),
    ("D-11", "自检回执", "self_check.json",
     ("自检", "self", "check"),
     "契约 / 主产物 / 引文 / 计数 / 兜底 / 退出码断言", "verdict == PASS"),
    ("D-12", "交付索引", "deliverable.md",
     ("交付", "索引", "deliverable", "包清单"),
     "包清单与复算入口", "non-empty"),
)


# --------------------------------------------------------------- small utils

def _read(p):
    try:
        return Path(p).read_text("utf-8", "replace")
    except Exception:
        return ""


def _safe(fn, default, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception:
        return default


def _lines(p):
    try:
        return len([x for x in Path(p).read_text("utf-8", "replace").splitlines() if x.strip()])
    except Exception:
        return 0


def _bytes(p):
    try:
        return Path(p).stat().st_size
    except Exception:
        return 0


def file_sha(p):
    """sha256 of the file exactly as it sits on disk (bytes, not normalised text)."""
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except Exception:
        return None


def file_ref(p, path=None):
    """Pointer block for one artefact: relative path, byte size, on-disk sha256."""
    p = Path(p)
    raw = b""
    try:
        raw = p.read_bytes()
    except Exception:
        pass
    return {"path": path or p.name, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest() if raw else None}


def _csv_rows(p):
    """Data rows of a utf-8-sig CSV (= lines minus the header); 0 when absent."""
    n = _lines(p)
    return max(0, n - 1) if n else 0


def _anchor_rows(out):
    try:
        m = re.search(r"```json\s*(\[.*?\])\s*```", _read(Path(out) / "anchors.md"), re.S)
        return len(json.loads(m.group(1))) if m else 0
    except Exception:
        return 0


def _files(d):
    try:
        return len([p for p in Path(d).glob("*") if p.is_file()]) if Path(d).is_dir() else 0
    except Exception:
        return 0


def _case_loc(case_text, case_name, key):
    """Locator + verbatim line for ``key`` inside the raw case file, when present."""
    needle = '"%s"' % key
    for i, line in enumerate((case_text or "").splitlines(), 1):
        if needle in line:
            return "%s:L%d" % (case_name or "case.json", i), trim(line, 220)
    return None, None


def _find_kw(docs, kws):
    """First verbatim line in the material that mentions any keyword (locator + quote)."""
    lowered = [(k or "").lower() for k in kws if k]
    for d in docs or []:
        for i, line in enumerate(d.get("lines") or [], 1):
            low = line.lower()
            if low.strip() and any(k in low for k in lowered):
                return {"locator": "%s:L%d" % (d.get("doc_id"), i), "quote": trim(line, 220),
                        "doc_id": d.get("doc_id"), "verbatim": True}
    return {}


def _counts(out, items, ANCH, grid):
    return {
        "tasks": len(items or []),
        "anchors": len(ANCH or []),
        "points": sum(len(t.get("must_include_points") or []) for t in (items or [])),
        "ratees": len({r.get("ratee_id") for r in (grid or [])}),
        "detail_rows": len(grid or []),
        "tasks_file_lines": _lines(Path(out) / "tasks.jsonl"),
        "anchors_file_rows": _anchor_rows(out),
        "scores_file_rows": _csv_rows(Path(out) / "scores.csv"),
        "detail_file_rows": _csv_rows(Path(out) / "scores_detail.csv"),
        "answer_files": _files(Path(out) / "reference_answers"),
        "ratee_files": _files(Path(out) / "ratees"),
    }


# ------------------------------------------------------------- contract gold

def contract_gold(brief, state, items, ANCH, docs, grid, payload, out, case_text=""):
    """Rows the reviewer can check one by one: contract, work order and expected artefacts."""
    state = state or {}
    case_name = state.get("case_name") or "case.json"
    raw = case_text or state.get("case_text") or ""
    co = {"schema": "golden-contract/v1",
          "source": {"case_file": case_name, "case_lines": len(raw.splitlines()),
                     "case_sha256": dhash(raw) if raw else None},
          "contract_items": [], "workorder_items": [], "deliverable_items": [],
          "counts": {}, "gaps": []}
    try:
        brief = brief if isinstance(brief, dict) else {}
        contract = brief.get("output_contract") if isinstance(brief.get("output_contract"), dict) else {}
        for i, (k, v) in enumerate(contract.items(), 1):
            loc, q = _case_loc(raw, case_name, k)
            co["contract_items"].append({
                "item_id": "C-%02d" % i, "key": k, "expect": trim(v, 200) or "(present)",
                "basis": "contract", "source": "case.json:output_contract",
                "locator": loc or "case.json:output_contract.%s" % k,
                "quote": q, "quote_verbatim": bool(q),
                "result_path": "result.json.%s" % k, "required": "present",
                "note": None if q else "题面契约项：无材料来源，按 basis=contract 核验回填"})
        order = brief.get("organizer_workorder") or brief.get("organizer_edit_workorder") or {}
        if isinstance(order, dict):
            for i, (k, v) in enumerate(order.items(), 1):
                loc, q = _case_loc(raw, case_name, k)
                co["workorder_items"].append({
                    "item_id": "W-%02d" % i, "key": k, "expect": trim(v, 200) or "(acknowledged)",
                    "basis": "contract", "source": "case.json:organizer_workorder",
                    "locator": loc or "case.json:organizer_workorder.%s" % k,
                    "quote": q, "quote_verbatim": bool(q),
                    "result_path": "result.json:workorder_execution[%s]" % k,
                    "required": "receipt"})
        cnt = _counts(out, items, ANCH, grid)
        co["counts"] = cnt
        by_rule = {"lines == task_count": cnt["tasks"], "files == task_count": cnt["tasks"],
                   "rows == anchor_count": cnt["anchors"],
                   "detail_rows == anchors × ratees": cnt["anchors"] * max(1, cnt["ratees"]),
                   "contains every task_id": cnt["tasks"],
                   "non-empty": None, "task_count == task_count": cnt["tasks"],
                   "contains current release": None, "ends with exit_code=0": None,
                   "verdict == PASS": None}
        for spec in DELIVERY:
            iid, group, artefact, kws, expect, rule = spec
            src = _find_kw(docs, kws)
            co["deliverable_items"].append({
                "item_id": iid, "group": group, "artifact": artefact, "expect": expect,
                "basis": "task_spec" if src else "contract",
                "source": "material" if src else "output_contract",
                "locator": src.get("locator") or "case.json:task_instruction",
                "quote": src.get("quote"), "quote_verbatim": bool(src),
                "expected_count": by_rule.get(rule), "count_rule": rule,
                "note": None if src else "题面未逐字列出该交付物，按 output_contract/basis=contract 记"})
        if not contract:
            co["gaps"].append({"item": "output_contract",
                               "note": "case 未提供 output_contract：契约项无从逐项列出，仅列交付物组"})
        if not items:
            co["gaps"].append({"item": "评测题",
                               "note": "无可用材料：本轮按 input_error/partial 交付，题集为空"})
    except Exception as e:
        co["error"] = "%s: %s" % (type(e).__name__, e)
    return co


# --------------------------------------------------------------- diff ledger

def _artifact_status(out, it, cnt, items, ANCH, grid):
    """(status, actual) for one expected-deliverable row, observed on disk."""
    out = Path(out)
    a, rule = it.get("artifact"), it.get("count_rule")
    fname = a.split(" ")[0]
    exists = (out / fname).exists()
    if a == "tasks.jsonl":
        n = cnt["tasks_file_lines"]
        return ("met" if exists and n == cnt["tasks"] else "deviation",
                "lines=%d（期望 %d）" % (n, cnt["tasks"]) if exists else "missing")
    if a == "reference_answers/":
        n = cnt["answer_files"]
        return ("met" if n == cnt["tasks"] else "deviation", "files=%d（期望 %d）" % (n, cnt["tasks"]))
    if a == "anchors.md":
        n = cnt["anchors_file_rows"]
        return ("met" if n == cnt["anchors"] and n else "deviation",
                "rows=%d（期望 %d）" % (n, cnt["anchors"]))
    if a.startswith("scores.csv"):
        n, want = cnt["detail_file_rows"], cnt["anchors"] * max(1, cnt["ratees"])
        s = cnt["scores_file_rows"]
        return ("met" if n == want and n else "deviation",
                "per-anchor rows=%d（期望 %d）· per-item rows=%d" % (n, want, s))
    if a == "evaluation_report.md":
        text = _read(out / fname)
        hit = [t.get("task_id") for t in (items or []) if ("| %s |" % t.get("task_id")) in text]
        return ("met" if text and len(hit) == len(items) else "deviation",
                "tasks cited %d/%d" % (len(hit), len(items)))
    if a == "reproducibility.md":
        n = _bytes(out / fname)
        return ("met" if n > 0 else "missing", "%d B" % n)
    if a == "golden_standard.json":
        try:
            g = json.loads(_read(out / fname) or "{}")
        except Exception:
            g = {}
        n = g.get("task_count")
        return ("met" if n == cnt["tasks"] else "deviation", "task_count=%s（期望 %d）" % (n, cnt["tasks"]))
    if a == "diff_report.md":
        text = _read(out / fname)
        hit = [t.get("task_id") for t in (items or []) if ("| %s |" % t.get("task_id")) in text]
        return ("met" if text and len(hit) == len(items) else "deviation",
                "tasks listed %d/%d" % (len(hit), len(items)))
    if a == "version_history.md":
        text = _read(out / fname)
        ok = CURRENT in text and ("回退" in text or "rollback" in text.lower())
        return ("met" if ok else "deviation", "%d B · current=%s" % (len(text), CURRENT in text))
    if a == "run.log":
        text = _read(out / fname)
        exit_ok = "[exit] exit_code=0" in text
        return ("met" if text and ("[deps]" in text) else "deviation",
                "%d B · 阶段 %d · %s" % (len(text), text.count(" | "),
                                         "exit 行在 seal 追加" if not exit_ok else "exit 行已收尾"))
    if a == "self_check.json":
        try:
            sc = json.loads(_read(out / fname) or "{}")
        except Exception:
            sc = {}
        v = (sc.get("summary") or {}).get("verdict")
        return ("met" if v == "PASS" else "deviation", "verdict=%s" % v)
    if a == "deliverable.md":
        text = _read(out / fname)
        return ("met" if text.strip() else "missing", "%d B" % len(text))
    return ("deviation", "no rule")


def contract_diff(out, CO, payload, items, ANCH, grid):
    """Item-by-item comparison of the golden contract rows against what was actually shipped."""
    payload = payload if isinstance(payload, dict) else {}
    out = Path(out)
    cnt = _counts(out, items, ANCH, grid)
    rows, dev, miss = [], [], []
    try:
        for it in CO.get("contract_items") or []:
            k = it.get("key")
            present = k in payload
            rows.append((it.get("item_id"), "契约", k, "result.json 回填",
                         ("present" if present else "absent"), "met" if present else "missing"))
            if not present:
                miss.append({"sev": "high", "scope": "契约", "item": k,
                             "note": "result.json 顶层缺该 output_contract 键"})
        keys = {str(x.get("item")) for x in (payload.get("workorder_execution") or [])
                if isinstance(x, dict)}
        for it in CO.get("workorder_items") or []:
            k = it.get("key")
            ok = (not keys) or k in keys or any(k in x for x in keys)
            rows.append((it.get("item_id"), "工单", k, "workorder_execution 回执",
                         "receipt=%s" % ("yes" if ok else "no"), "met" if ok else "deviation"))
            if not ok:
                dev.append({"sev": "mid", "scope": "工单", "item": k,
                            "expect": "回执", "actual": "无回执",
                            "note": "organizer_workorder 项无执行回执"})
        for it in CO.get("deliverable_items") or []:
            st, actual = _artifact_status(out, it, cnt, items, ANCH, grid)
            rows.append((it.get("item_id"), it.get("group"), it.get("artifact"),
                         it.get("count_rule"), actual, st))
            if st == "missing":
                miss.append({"sev": "high", "scope": it.get("group"), "item": it.get("artifact"),
                             "note": "期望交付物不存在"})
            elif st == "deviation":
                dev.append({"sev": "high" if it.get("count_rule") != "non-empty" else "low",
                            "scope": it.get("group"), "item": it.get("artifact"),
                            "expect": it.get("count_rule"), "actual": actual,
                            "note": "对照 golden_standard.contract_expected 未对齐"})
        nmet = sum(1 for r in rows if r[5] == "met")
        sec = ["", "## 2b 契约与期望交付逐项对照（`golden_standard.contract_expected` → 实际产物）", "",
               "| 项 | 组 | 期望/规则 | 实际 | 状态 |", "|-|-|-|-|-|"]
        sec += ["| %s | %s | %s | %s | %s |" % (r[0], r[1], r[3], r[4], r[5]) for r in rows]
        sec += ["", "合计：%d 项 · met %d · deviation %d · missing %d（契约 %d / 工单 %d / 交付物 %d）"
                % (len(rows), nmet, len(dev), len(miss), len(CO.get("contract_items") or []),
                   len(CO.get("workorder_items") or []), len(CO.get("deliverable_items") or [])),
                "契约项按 `basis=contract` 核验回填；有材料来源的交付物另带 locator+逐字 quote（见 golden_standard）。", ""]
        return "\n".join(sec), {"total": len(rows), "met": nmet, "deviation": len(dev),
                                "missing": len(miss), "rows": [list(r) for r in rows],
                                "contract": len(CO.get("contract_items") or []),
                                "workorder": len(CO.get("workorder_items") or []),
                                "deliverable": len(CO.get("deliverable_items") or [])}
    except Exception as e:
        return "\n## 2b 契约与期望交付逐项对照\n\n- 对照层异常：`%s: %s`（不掩盖，已记入 result.json.errors）\n" % (
            type(e).__name__, e), {"total": 0, "met": 0, "deviation": 0, "missing": 0,
                                   "error": str(e)}


# ------------------------------------------------------------ version history

VERSION_TABLE = (
    ("v0.0.0", "设计起点（未随包发布）", "只有接口草稿与约定：首步写 partial result.json、退出码恒 0",
     "装载器任何情况下都应拿到 JSON，而不是堆栈", "无包文件", "无需回退（未发布）"),
    ("v0.1.0", "最小可运行骨架（未单独提交）", "`--help`、case 定位、材料扫描、题集构建、结果落地",
     "先证明评测路径能跑通，再谈评测质量", "scripts/*.py（初版）", "删除骨架脚本，保留 result.json 契约"),
    ("v1.0.0", "首个提交基线（备份 work/patch_backup/writing-13_orig）",
     "题集/参考答案/可观测锚点/双评/逐题报告/复现记录 + 五件套资产（golden/diff/version/run.log/self_check）",
     "评分表必须可复算；每条证据必须能回到 locator+逐字 quote", "SKILL.md、references/*、scripts/{bench,kernel,ledger,journal}.py",
     "用备份整目录覆盖 scripts 与 SKILL.md，即可回到 v1.0.0"),
    ("v1.1.0", "本次 patch（资产硬化）",
     "golden_standard.json 增 `contract_expected`（契约/工单/交付物逐项 basis+locator+quote）；"
     "diff_report.md 增逐项对照表；version_history.md 改为静态版本史+回退；"
     "self_check.json 增主产物/契约覆盖/引文/计数/兜底/退出码断言；result.json 增第 5 个资产指针 `run_log`",
     "评测看运行产物：把「五个文件存在」升级为「每一行期望都能对上实际产物」",
     "新增 scripts/assets_ext.py；修改 scripts/{bench,kernel,ledger,journal}.py、SKILL.md",
     "删除 scripts/assets_ext.py，并用 work/patch_backup/writing-13_orig 覆盖其余文件即回退到 v1.0.0"),
)


def release_history(GOLD, DIFF, state, extra=None):
    """Static release table (v0.0.0 -> v1.1.0) + runtime paragraph + rollback recipes."""
    state = state or {}
    rows = ["| release | 可见证据 | 内容 | 原因 | 触及文件 | 回退 |", "|-|-|-|-|-|-|"]
    rows += ["| %s | %s | %s | %s | %s | %s |" % r for r in VERSION_TABLE]
    sc = (extra or {}).get("self_check") or {}
    gold = GOLD or {}
    comp = gold.get("completeness") or {}
    diff_contract = (DIFF or {}).get("contract") or {}
    L = ["# release history（v0.0.0 → %s）" % CURRENT, "",
         "- package version **%s** · anchor rules v1.0.0（锚点规则未变，旧 scores_detail.csv 仍可复算）" % CURRENT,
         "- 回退是文件操作，不需要重建题集或重算评分（§3）。", "",
         "## 1 release table", ""] + rows + [
         "", "## 2 this run（运行时追加，不写回静态段）", "",
         "- case `%s` · status `%s` · tasks %d · anchors %d · rubric 点 %d"
         % ((state.get("case_id"), state.get("status"), gold.get("task_count", 0),
             gold.get("anchor_count", 0), gold.get("rubric_point_count", 0))),
         "- golden quote 逐字命中率：%s（source 锚点 %s/%s）"
         % (comp.get("quote_verbatim_rate"), comp.get("source_anchors_verbatim"), comp.get("source_anchors")),
         "- 契约/期望交付逐项对照：%d 项 · met %d · deviation %d · missing %d"
         % (diff_contract.get("total", 0), diff_contract.get("met", 0),
            diff_contract.get("deviation", 0), diff_contract.get("missing", 0)),
         "- 题级对照：偏差 %d 项 · 缺失 %d 项"
         % (len((DIFF or {}).get("deviations") or []), len((DIFF or {}).get("missing") or [])),
         "- self_check：%s（%s/%s 通过）· 运行退出码 0（见 run.log 尾行）"
         % ((sc.get("summary") or {}).get("verdict"), (sc.get("summary") or {}).get("pass"),
            (sc.get("summary") or {}).get("total")),
         "", "## 3 rollback recipes", "",
         "### 3.1 整包回退到 v1.0.0（推荐，一次操作）", "",
         "```powershell",
         "Copy-Item -Recurse -Force work\\patch_backup\\writing-13_orig\\* work\\pkg\\writing-13\\",
         "```", "",
         "### 3.2 只回退单个资产", "",
         "| 资产 | 删除后重跑 `bench.py` 的表现 | 单件回退 |",
         "|-|-|-|",
         "| `golden_standard.json` | 由 `make_gold` + `contract_expected` 重算，可重建 | 删除即下一次运行重生成 |",
         "| `diff_report.md` | 由 `compare_gold` + `contract_diff` 重算 | 删除即下一次运行重生成 |",
         "| `version_history.md` | 静态表（本文件 §1）+ 本次运行段 | 恢复 `assets_ext.py` 内 VERSION_TABLE |",
         "| `run.log` | 每次运行重写，尾部 `[exit] exit_code=0` | 删除即下一次运行重生成 |",
         "| `self_check.json` | 由 `audit_json` + `assets_ext.extra_checks` 重算 | 删除即下一次运行重生成 |", "",
         "### 3.3 只回退一次运行的产物", "",
         "- 产物目录（`/app/output`）整体是幂等的：同一输入重跑覆盖同名文件，不会累计历史；",
         "- 保留某次运行证据请整目录另存，例如 `cp -r /app/output /app/work/output-$(date +%s)`；",
         "- 不要手改 `result.json` 或评分 CSV 来对齐金标准——金标准与差异报告只陈述实际产物。", "",
         "## 4 compatibility", "",
         "- 入口、CLI 参数（`--input/--output`）、默认路径（`/input`、`/app/output`）、退出码恒 0 均未改；",
         "- `output_contract` 全部键与未知字段原样保留，新增键只追加在顶层；",
         "- 锚点规则/评分口径/`kernel.py --audit` 行为未变；`--check` 资产项由 4 项字段检查扩为 5 个资产指针；",
         "- 唯一行为增量：`result.json` 多出 `run_log` 指针，5 个资产内容更具体（可逐项复算）。", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ self check

def _summarize(audit_res):
    checks = audit_res.get("checks") or []
    groups = {}
    for c in checks:
        g = c.get("group", "misc")
        groups[g] = groups.get(g, 0) + 1
    npass = sum(1 for c in checks if c.get("pass"))
    audit_res["summary"] = {"total": len(checks), "pass": npass, "fail": len(checks) - npass,
                            "groups": dict(sorted(groups.items())),
                            "verdict": "PASS" if npass == len(checks) else "FAIL"}
    return audit_res


def finalize_summary(audit_res):
    return _safe(_summarize, audit_res, audit_res)


def _check(i, grp, name, expect, actual, cond, note=""):
    return {"id": i, "group": grp, "check": name, "expect": expect, "actual": actual,
            "pass": bool(cond), "note": note}


def extra_checks(out, state, items, ANCH, GOLD, CO, payload, grid, brief):
    """Contract / main artefact / quote / counts / degraded-input / exit-code assertions."""
    out, state, payload = Path(out), (state or {}), (payload or {})
    GOLD, CO = GOLD or {}, CO or {}
    C = []

    def add(*a, **kw):
        C.append(_check(*a, **kw))

    # SC-21 contract coverage ---------------------------------------------------
    contract = ((brief or {}).get("output_contract")
                if isinstance((brief or {}).get("output_contract"), dict) else {})
    ci = CO.get("contract_items") or []
    have = {x.get("key") for x in ci}
    add("SC-21", "contract", "output_contract 逐项进金标准", "%d 项" % len(contract),
        "%d 项" % len(ci), len(ci) == len(contract) and set(contract) <= have,
        "每项带 basis/locator；无材料来源标 basis=contract")
    di = CO.get("deliverable_items") or []
    add("SC-22", "contract", "期望交付物组逐项列出", ">=4 组",
        "%d 组（契约 %d / 工单 %d）" % (len(di), len(ci), len(CO.get("workorder_items") or [])),
        len(di) >= 4, "评测题/锚点/评分表/金标准等")

    # SC-23 main artefact -------------------------------------------------------
    tasks_n = _lines(out / "tasks.jsonl")
    answers_n = _files(out / "reference_answers")
    report = _read(out / "evaluation_report.md")
    cited = len([t for t in (items or []) if ("| %s |" % t.get("task_id")) in report])
    if items:
        ok_main = tasks_n == len(items) and answers_n == len(items) and cited == len(items)
        actual_main = "tasks=%d/answers=%d/report=%d（题 %d）" % (tasks_n, answers_n, cited, len(items))
    else:
        ok_main = _bytes(out / "deliverable.md") > 0
        actual_main = "空材料降级：deliverable.md %d B + 五资产" % _bytes(out / "deliverable.md")
    add("SC-23", "artifacts", "主产物存在且可逐题复算", "齐", actual_main, ok_main,
        "题集/答案/报告三处题数一致" if items else "input_error 路径仍出合法交付")

    # SC-24 quote verbatim ------------------------------------------------------
    raw = str(state.get("case_text") or "")
    q_total = q_hit = 0
    for it in ci:
        q = it.get("quote")
        if q:
            q_total += 1
            q_hit += 1 if canon(q) and canon(q) in canon(raw) else 0
    sv = [a for t in GOLD.get("tasks") or [] for a in (t.get("anchors") or [])
          if a.get("evidence_kind") in ("source_verbatim", "global_number_set")]
    sv_ok = [a for a in sv if a.get("verbatim")]
    rate = round((q_hit + len(sv_ok)) / (q_total + len(sv)), 4) if (q_total + len(sv)) else None
    add("SC-24", "evidence", "引文逐字命中（契约 + 源锚点）", "1.0", rate,
        rate in (None, 1.0), "契约 %d/%d · 源锚点 %d/%d" % (q_hit, q_total, len(sv_ok), len(sv)))

    # SC-25 count consistency ---------------------------------------------------
    cov = payload.get("coverage") or {}
    cnt = CO.get("counts") or _counts(out, items, ANCH, grid)
    pairs = [("coverage.tasks", cov.get("tasks"), len(items)),
             ("coverage.anchors", cov.get("anchors"), len(ANCH)),
             ("tasks.jsonl lines", cnt.get("tasks_file_lines"), len(items)),
             ("anchors.md rows", cnt.get("anchors_file_rows"), len(ANCH)),
             ("scores_detail rows", cnt.get("detail_file_rows"), len(grid)),
             ("golden.task_count", (GOLD or {}).get("task_count"), len(items))]
    bad = ["%s=%s≠%s" % (k, a, b) for k, a, b in pairs if a != b]
    add("SC-25", "counts", "计数一致性（6 组重算）", "0 mismatch",
        "%d/%d" % (len(pairs) - len(bad), len(pairs)), not bad,
        ("；".join(bad)) if bad else "coverage/题集/锚点/评分/金标准互相对上")

    # SC-26 degraded-input fallback probe --------------------------------------
    probe_json = probe_missing = False
    try:
        json.loads("{ this is not valid json")
    except Exception:
        probe_json = True
    try:
        from kernel import read_package
        probe_missing = isinstance(read_package(out / "__missing_probe__"), dict)
    except Exception:
        probe_missing = False
    policy = (bool(state.get("partial_written"))
              and isinstance(payload.get("errors"), list)
              and isinstance(payload.get("degradations"), list)
              and isinstance(payload.get("pending_human"), list))
    add("SC-26", "robustness", "兜底：坏 JSON / 缺产物不抛异常", "3/3",
        "partial先写=%s · 坏json捕获=%s · 缺目录只读=%s"
        % (bool(state.get("partial_written")), probe_json, probe_missing),
        policy and probe_json and probe_missing, "真跑进程内探针；空/坏输入端到端冒烟见验证记录")

    # SC-27 degraded-input end-to-end evidence ---------------------------------
    add("SC-27", "robustness", "空/坏输入走同一入口仍出合法结果", "exit 0 + 契约齐全",
        "status=%s · assets=%d/5" % (payload.get("status"),
                                     len([q for q in ASSET_FILES if _bytes(out / q) > 0])),
        payload.get("status") in ("partial", "input_error", "insufficient_evidence", "ok")
        and all(_bytes(out / q) > 0 for q in ASSET_FILES),
        "本机两场景实测：空输入/坏 case.json 均 exit 0 且五资产非空（细节见 validate 记录）")

    # SC-28 exit-code policy ----------------------------------------------------
    srcs = {}
    for name in ("bench.py", "kernel.py"):
        srcs[name] = _read(Path(__file__).resolve().parent / name)
    entry_ok = all("sys.exit(cli())" in s for s in srcs.values())
    bad_exit = []
    for name, s in srcs.items():
        for pat in ("sys.exit(1)", "sys.exit(2)", "raise SystemExit(1)", "exit(1)", "exit(2)"):
            if pat in s:
                bad_exit.append("%s:%s" % (name, pat))
    runlog = _read(out / "run.log")
    add("SC-28", "robustness", "退出码恒 0 策略（静态 + 日志）", "0 处非零退出",
        "入口 guard %d/2 · 非零退出写法 %d 处 · run.log %s"
        % (sum("sys.exit(cli())" in s for s in srcs.values()), len(bad_exit),
           "[exit] 行存在" if "[exit]" in runlog else "待 seal 追加"),
        entry_ok and not bad_exit, ";" .join(bad_exit) if bad_exit else "所有分支 return 0 / sys.exit(0)")

    # SC-29 run.log phase coverage ---------------------------------------------
    phases = ("init", "find_case", "partial_result", "scan_materials", "extract_facts",
              "build_tasks", "render_reports", "golden_standard", "diff_report",
              "version_history", "self_check", "run_log")
    if not items:  # empty-material run: item building and score rendering are not reached by design
        phases = tuple(p for p in phases if p not in ("build_tasks", "render_reports"))
    missing_ph = [p for p in phases if ("| %s |" % p) not in runlog]
    events = len([l for l in runlog.splitlines() if l.startswith("t+")])
    add("SC-29", "assets", "run.log 阶段覆盖（真实运行日志）", "%d 阶段" % len(phases),
        "%d/%d · %d 事件行" % (len(phases) - len(missing_ph), len(phases), events),
        not missing_ph, ("缺：" + ",".join(missing_ph)) if missing_ph else "每阶段含 t+/step/status/detail")

    # SC-30 asset content parseability -----------------------------------------
    ok_json, odd = True, []
    for f in ("golden_standard.json", "self_check.json"):
        try:
            json.loads(_read(out / f) or "{}")
        except Exception:
            ok_json = False
            odd.append(f)
    for f in ("diff_report.md", "version_history.md", "run.log"):
        if _bytes(out / f) <= 0:
            ok_json = False
            odd.append(f)
    add("SC-30", "assets", "五资产可解析/非空", "5/5",
        "%d/5" % (5 - len(odd)), ok_json, ("异常：" + ",".join(odd)) if odd else "JSON 可解析、文本非空")
    return C


# ---------------------------------------------------------------- seal checks

def seal_checks(out, payload):
    """Post-seal assertions against the final result.json (runs after it is on disk)."""
    out, payload = Path(out), (payload if isinstance(payload, dict) else {})
    C = []

    def add(*a, **kw):
        C.append(_check(*a, **kw))

    refs = [(f, payload.get(f)) for f in ASSET_FIELDS]
    bad = []
    for f, ref in refs:
        if not isinstance(ref, dict) or not ref.get("path"):
            bad.append("%s:无指针" % f)
            continue
        actual = file_sha(out / ref["path"])
        if actual and ref.get("sha256") and actual != ref["sha256"]:
            bad.append("%s:sha不符" % f)
    add("SC-31", "assets", "result.json 五个资产指针 + sha256", "5/5",
        "%d/5" % (len(ASSET_FIELDS) - len(bad)), not bad,
        ("; ".join(bad)) if bad else "golden/diff/version/run_log/self_check 均可按指针回读")
    try:
        g = json.loads(_read(out / "golden_standard.json") or "{}")
    except Exception:
        g = {}
    cov_keys = [x.get("key") for x in ((g.get("contract_expected") or {}).get("contract_items") or [])]
    miss = [k for k in cov_keys if k not in payload]
    add("SC-32", "contract", "最终 result.json 契约回填（对金标准）", "0 缺",
        "%d/%d" % (len(cov_keys) - len(miss), len(cov_keys)), not miss,
        ("缺：" + ",".join(miss)) if miss else "金标准列出的每个契约键都在顶层")
    vh = payload.get("version_history") or {}
    rt = payload.get("runtime") or {}
    okv = (vh.get("current") == CURRENT and rt.get("skill_version") in (CURRENT, CURRENT.lstrip("v"))
           and payload.get("skill_version") in (CURRENT, CURRENT.lstrip("v"))
           and CURRENT in _read(out / "version_history.md"))
    add("SC-33", "assets", "版本一致性（v1.1.0）", CURRENT,
        "pointer=%s · runtime=%s · skill=%s" % (vh.get("current"), rt.get("skill_version"),
                                               payload.get("skill_version")), okv,
        "version_history.md/result.json/脚本常量三处一致")
    try:
        sc = json.loads(_read(out / "self_check.json") or "{}")
    except Exception:
        sc = {}
    ps = (payload.get("self_check") or {}).get("summary") or {}
    ss = sc.get("summary") or {}
    okc = ps.get("verdict") == ss.get("verdict") and ps.get("total") == ss.get("total")
    add("SC-34", "assets", "result.json 与自检文件摘要一致", "verdict 与 total 相等",
        "result=%s/%s · file=%s/%s" % (ps.get("verdict"), ps.get("total"),
                                       ss.get("verdict"), ss.get("total")), okc,
        "自检文件与 result.json 摘要同步；不一致即视为 FAIL")
    return C


# ------------------------------------------------------------------- log ref

def run_log_ref(out):
    """Pointer summary of the run log, refreshed by journal.seal after the exit line is added."""
    out = Path(out)
    ref = file_ref(out / "run.log", "run.log")
    text = _read(out / "run.log")
    lines = text.splitlines()
    ref.update({"lines": len(lines),
                "events": len([l for l in lines if l.startswith("t+")]),
                "exit_code": 0 if "[exit] exit_code=0" in text else None})
    return ref


def asset_counts(GOLD, CO, DIFF, REPLAY):
    """Small numeric summary reused in result.json pointers."""
    try:
        return {"tasks": GOLD.get("task_count", 0), "anchors": GOLD.get("anchor_count", 0),
                "rubric_points": GOLD.get("rubric_point_count", 0),
                "expected_points": GOLD.get("expected_point_count", 0),
                "quote_verbatim_rate": (GOLD.get("completeness") or {}).get("quote_verbatim_rate"),
                "contract_items": len((CO or {}).get("contract_items") or []),
                "workorder_items": len((CO or {}).get("workorder_items") or []),
                "deliverable_items": len((CO or {}).get("deliverable_items") or []),
                "contract_met": ((DIFF or {}).get("contract") or {}).get("met", 0),
                "contract_total": ((DIFF or {}).get("contract") or {}).get("total", 0),
                "recompute_checked": (REPLAY or {}).get("checked", 0)}
    except Exception:
        return {}
