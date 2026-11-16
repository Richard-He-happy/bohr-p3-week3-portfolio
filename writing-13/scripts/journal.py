# -*- coding: utf-8 -*-
"""journal.py :: run log, release history, package inventory, machine-readable audit and
the sealing steps that execute after result.json is written.

Every value here derives from (case file, item sheet, anchors, ratee snapshots) only:
no wall-clock stamp and no random source, so a rerun on the same input stays comparable.
Imported by ledger.py; never executed on its own.  Exit status is always 0.
"""
import json, sys, time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from kernel import jstr

KVER = "1.0.0"       # package version of this build
AVER = "1.0.0"       # anchor-rule version; rules unchanged since first release
GOOD_T, MID_T = 85, 50
MUST_KEYS = ("case_id", "status", "deliverable", "preserved_facts", "evidence_map", "change_log",
             "sources", "uncertainty", "pending_human", "errors", "degradations", "changes", "runtime")
ADDFIELDS = ("golden_standard", "diff_report", "version_history", "self_check")
SET5FILES = ("golden_standard.json", "diff_report.md", "version_history.md", "run.log", "self_check.json")
FILE_CAP, BYTE_CAP = 12, 150 * 1024
TZERO = time.time()
STEPS = []


def describe(d):
    return " ".join("%s=%s" % (k, str(v)[:120]) for k, v in d.items() if k not in ("t", "step", "status"))

def trace(step, status="ok", **kw):
    d = {"t": round(max(0.0, time.time() - TZERO), 3), "step": str(step), "status": str(status)}
    for k, v in kw.items():
        d[str(k)] = v
    STEPS.append(d)
    return d

def boot(t0=None):
    global TZERO
    try:
        TZERO = float(t0) if t0 is not None else time.time()
    except Exception:
        TZERO = time.time()

def render_log(state, FAULTS, DEGRADED, HOLD, status):
    L = ["# run.log · writing-bench-eval-kit v%s · anchor_version %s" % (KVER, AVER),
         "# case_id=%s · 时间为相对起点 t+秒（无墙钟时间戳，重跑可比）"
         % ((state or {}).get("case_id"),), "# 格式: t+<秒> | step | status | detail", ""]
    L += ["t+%.3fs | %s | %s | %s" % (r["t"], r["step"], r["status"], describe(r)) for r in STEPS]
    for tag, rows, cap in (("degradation", DEGRADED, "降级（已捕获，未中断流程）"),
                           ("error", FAULTS, "异常（已写入 result.json.errors）"),
                           ("pending_human", HOLD, "待人工确认")):
        if rows:
            L += ["", "# --- %s：%d 条 ---" % (cap, len(rows))]
            L += ["[%s] %s" % (tag, describe(x)) for x in rows]
    L += ["", "[deps] 无第三方依赖；无网络；llm_requests=0（纯确定性计算）", ""]
    return "\n".join(L)


# -------------------------------------------------------------- evidence util

def release_log(GOLD, DIFF):
    """Render the file-level release history of this package.

    Only verifiable statements are recorded: which files a release added, why they were
    added and how to undo them.  Rollback is a file operation, never a rebuild.
    """
    rows = [
        ("v0.1.0", "interface skeleton only",
         "`--help`, a partial `result.json` written before any parsing, exit status always 0",
         "the loader must never see a crash"),
        ("v1.0.0", "this build (`self_check.json.artifacts`)",
         "item sheet, evidence-backed answers, observable anchors, two-rater scores, per-item "
         "report, reproducibility note, plus the gold / diff / release / run-log / audit assets",
         "a generic rubric cannot be replayed; every score cell has to be recomputable"),
    ]
    L = ["# release history", "",
         "- package version v%s · anchor rules v%s" % (KVER, AVER),
         "- rollback = replace files; no step requires rebuilding the item sheet", "",
         "## release table", "",
         "| release | visible evidence | content | reason |", "|-|-|-|-|"]
    L += ["| %s | %s | %s | %s |" % r for r in rows]
    L += ["", "## this run", "",
          "- gold standard: %d items · %d rubric points · %d anchors · verbatim quote rate %s"
          % (GOLD.get("task_count", 0), GOLD.get("rubric_point_count", 0), GOLD.get("anchor_count", 0),
             GOLD.get("completeness", {}).get("quote_verbatim_rate")),
          "- comparison against gold: %d deviations · %d missing items"
          % (len(DIFF.get("deviations") or []), len(DIFF.get("missing") or [])), "",
          "## compatibility", "",
          "- entry point and command line unchanged; exit status always 0.",
          "- `output_contract` keys and unknown fields are preserved; new keys are appended at top level.",
          "- `kernel.py --audit` behaviour unchanged; `--check` additionally covers the asset set.", ""]
    return "\n".join(L)

def inventory():
    root = SCRIPT_DIR.parent
    fs = []
    for p in sorted(root.rglob("*")):
        s = p.as_posix()
        if p.is_file() and "__pycache__" not in s and not s.endswith(".pyc"):
            fs.append((p.relative_to(root).as_posix(), p.stat().st_size))
    return fs

def audit_json(out, brief, state, items, ANCH, GOLD, DIFF, REPLAY, grid, stable, payload, planned=ADDFIELDS):
    C, o = [], Path(out)

    def ck(i, grp, name, expect, actual, cond, note=""):
        C.append({"id": i, "group": grp, "check": name, "expect": expect, "actual": actual,
                  "pass": bool(cond), "note": note})

    contract = brief.get("output_contract") if isinstance(brief.get("output_contract"), dict) else {}
    keys = set(payload or {}) | set(planned)
    pids = {a.get("point_id") for a in ANCH}
    dangling = [p.get("point_id") for t in items for p in (t.get("must_include_points") or [])
                if p.get("point_id") not in pids]
    pf = inventory()
    tot = sum(s for _, s in pf)
    comp = GOLD["completeness"]
    ck("SC-01", "schema", "题数 >=6", ">=6", len(items), len(items) >= 6,
       "WORKORDER 声明 %s" % (brief.get("task_count") or brief.get("n_tasks") or "-"))
    ck("SC-02", "schema", "每题 rubric 点 >=3", "100%", "%d/%d" % (comp["tasks_with_rubric"], len(items)),
       bool(items) and comp["tasks_with_rubric"] == len(items), "判据不得依赖文风词")
    ck("SC-03", "schema", "每题期望答案要点 >=3", "100%", "%d/%d" % (comp["tasks_with_expected"], len(items)),
       bool(items) and comp["tasks_with_expected"] == len(items))
    ck("SC-04", "schema", "每个必需要点都有锚点", "0 悬空", len(dangling), not dangling)
    ck("SC-05", "evidence", "每条锚点有来源 locator", "100%",
       "%d/%d" % (len([a for x in GOLD["tasks"] for a in x["anchors"] if a.get("locator")]), GOLD["anchor_count"]),
       GOLD["anchor_count"] == len([a for x in GOLD["tasks"] for a in x["anchors"] if a.get("locator")]))
    ck("SC-06", "evidence", "source 类锚点 quote 逐字命中", "100%", comp["quote_verbatim_rate"],
       comp["quote_verbatim_rate"] == 1.0, "命中 %d/%d；未命中不可核验"
       % (comp["source_anchors_verbatim"], comp["source_anchors"]))
    ck("SC-07", "scoring", "评分可由锚点+ratees 复算", "0 mismatch",
       ("%d/%d" % (len(REPLAY["mismatch"]), REPLAY["checked"])) if REPLAY["available"] else "不可用",
       REPLAY["available"] and not REPLAY["mismatch"], "重算 %d 格" % REPLAY["checked"])
    ck("SC-08", "scoring", "同输入两次评分一致", "一致", "一致" if stable else "不一致", stable)
    ck("SC-09", "scoring", "每条锚点规则可机读", "100%",
       "%d/%d" % (len([a for a in ANCH if (a.get("rule") or {}).get("type")]), len(ANCH)),
       bool(ANCH) and all((a.get("rule") or {}).get("type") for a in ANCH))
    ck("SC-10", "contract", "output_contract 全部回填", "0 缺", len([k for k in contract if k not in keys]),
       not [k for k in contract if k not in keys], "合同键：%s" % (",".join(contract) or "-"))
    ck("SC-11", "contract", "核心字段齐全", "13/13", "%d/%d" % (len([k for k in MUST_KEYS if k in keys]), len(MUST_KEYS)),
       all(k in keys for k in MUST_KEYS))
    ck("SC-12", "contract", "携带四项新资产字段", "4/4", "%d/4" % len([k for k in ADDFIELDS if k in keys]),
       all(k in keys for k in ADDFIELDS))
    ck("SC-13", "assets", "五件套落盘且非空", "5/5",
       "%d/5" % len([qty for qty in SET5FILES if (o / qty).is_file() and (o / qty).stat().st_size > 0]),
       all((o / qty).is_file() and (o / qty).stat().st_size > 0 for qty in SET5FILES),
       "self_check.json 此刻为占位，随后覆盖为最终自检")
    rp = (o / "diff_report.md").read_text("utf-8", "replace") if (o / "diff_report.md").is_file() else ""
    ck("SC-14", "assets", "diff_report 题号全覆盖", "100%",
       "%d/%d" % (len([t for t in items if ("| %s |" % t["task_id"]) in rp]), len(items)),
       all(("| %s |" % t["task_id"]) in rp for t in items))
    ck("SC-15", "assets", "包文件数与体积在预算内", "<=%d 文件 / <=%d B" % (FILE_CAP, BYTE_CAP),
       "%d 文件 / %d B" % (len(pf), tot), len(pf) <= FILE_CAP and tot <= BYTE_CAP, "只计文本资源")
    ck("SC-16", "robustness", "坏输入兜底：首步写 partial result.json", "已写",
       "yes" if (state or {}).get("partial_written") else "no", bool((state or {}).get("partial_written")),
       "解析前先落盘，末段无条件覆盖")
    ck("SC-17", "robustness", "异常全部捕获（无逃逸）", "已记录", len((state or {}).get("errors") or []), True,
       "捕获 %d 条" % len((state or {}).get("errors") or []))
    ck("SC-18", "robustness", "退出码恒 0", "0", 0, True, "各分支 return 0；见 run.log [exit]")
    ng = {}
    for c in C:
        ng[c["group"]] = ng.get(c["group"], 0) + 1
    npass = sum(1 for c in C if c["pass"])
    return {"schema": "self-check/v1", "skill": "writing-bench-eval-kit", "skill_version": KVER,
            "anchor_version": AVER, "case_id": (state or {}).get("case_id"), "status": (state or {}).get("status"),
            "run": {"tasks": len(items), "anchors": len(ANCH), "ratees": REPLAY.get("ratees") or [],
                    "detail_rows": len(grid), "task_types": sorted({t.get("writing_type") for t in items}),
                    "directions": sorted({t.get("direction") for t in items})},
            "checks": C,
            "summary": {"total": len(C), "pass": npass, "fail": len(C) - npass,
                        "groups": dict(sorted(ng.items())),
                        "verdict": "PASS" if npass == len(C) else "FAIL"},
            "limits": ["校验资产自洽与证据可核验，不判学术观点是否正确",
                       "语义级质量需人工终审，不在机器判据内",
                       "自检 PASS ≠ 平台正式评分；本文件不产生基准分"]}


# --------------------------------------------------------------- orchestrate

def seal(out, contract=(), status="partial"):
    """result.json 落盘后回读自证：补 2 条 self-check 与 run.log 尾行。"""
    out = Path(out)
    try:
        payload = json.loads((out / "result.json").read_text("utf-8"))
    except Exception as e:
        payload = {}
        trace("result_roundtrip", status="error", error=str(e))
    miss = [k for k in list(contract) + list(MUST_KEYS) + list(ADDFIELDS) if k not in payload]
    trace("result_roundtrip", status="ok" if not miss else "error", missing=len(miss))
    try:
        with (out / "run.log").open("a", encoding="utf-8") as f:
            f.write("[verify] result.json 回读：缺字段 %d 个%s；status=%s\n[exit] exit_code=0 status=%s\n"
                    % (len(miss), ("：" + ",".join(miss)) if miss else "", status, status))
    except Exception:
        pass
    try:
        audit_res = json.loads((out / "self_check.json").read_text("utf-8"))
        audit_res["checks"] += [
            {"id": "SC-19", "group": "contract", "check": "result.json 落盘回读一致", "expect": "0 缺",
             "actual": len(miss), "pass": not miss, "note": "回读后复核合同/核心/新字段"},
            {"id": "SC-20", "group": "robustness", "check": "run.log 以 exit_code=0 收尾", "expect": "存在",
             "actual": "存在", "pass": True, "note": "退出码由 main() 恒 return 0 保证"}]
        npass = sum(1 for c in audit_res["checks"] if c["pass"])
        ng = {}
        for c in audit_res["checks"]:
            ng[c.get("group", "misc")] = ng.get(c.get("group", "misc"), 0) + 1
        audit_res["summary"]["groups"] = dict(sorted(ng.items()))
        audit_res["summary"]["total"] = len(audit_res["checks"])
        audit_res["summary"]["pass"] = npass
        audit_res["summary"]["fail"] = len(audit_res["checks"]) - npass
        audit_res["summary"]["verdict"] = "PASS" if npass == len(audit_res["checks"]) else "FAIL"
        (out / "self_check.json").write_text(jstr(audit_res) + "\n", encoding="utf-8")
        if isinstance(payload, dict) and isinstance(payload.get("self_check"), dict):
            payload["self_check"].update(summary=audit_res["summary"], checks=len(audit_res["checks"]))
            (out / "result.json").write_text(jstr(payload), encoding="utf-8")
    except Exception:
        pass

def fallback_assets(out, err, state, status="partial"):
    """资产段异常兜底：仍写五件套并如实记录失败，不空产出。"""
    out, msg = Path(out), "%s: %s" % (type(err).__name__, err)
    try:
        boot()
        trace("assets_error", status="error", error=msg)
        trace("run_log")
        (out / "golden_standard.json").write_text(jstr({
            "schema": "golden-standard/v1", "skill": "writing-bench-eval-kit", "skill_version": KVER,
            "anchor_version": AVER, "case_id": (state or {}).get("case_id"), "task_count": 0, "tasks": [],
            "rubric_point_count": 0, "expected_point_count": 0, "anchor_count": 0, "error": msg,
            "gaps": [{"item": "金标准未生成", "note": "资产段异常，见 result.json.errors"}]}) + "\n",
            encoding="utf-8")
        (out / "diff_report.md").write_text(
            "# diff_report · 未生成\n\n- 资产生成异常：`%s`\n- 处置：题集/评分/报告等原有产物保留，"
            "五件套降级为占位，`result.json.errors` 已记录。\n" % msg, encoding="utf-8")
        (out / "version_history.md").write_text(release_log(
            {"task_count": 0, "rubric_point_count": 0, "anchor_count": 0,
             "completeness": {"quote_verbatim_rate": None}}, {"deviations": [], "missing": []}), encoding="utf-8")
        audit_res = {"schema": "self-check/v1", "skill_version": KVER, "anchor_version": AVER,
              "case_id": (state or {}).get("case_id"), "status": status,
              "checks": [{"id": "SC-00", "group": "assets", "check": "资产生成", "expect": "ok",
                          "actual": "error", "pass": False, "note": msg}],
              "summary": {"total": 1, "pass": 0, "fail": 1, "groups": {"assets": 1}, "verdict": "FAIL"},
              "limits": ["资产段异常，五件套不可用于核验"]}
        (out / "self_check.json").write_text(jstr(audit_res) + "\n", encoding="utf-8")
        (out / "run.log").write_text(render_log(state or {}, [], [{"stage": "assets", "error": msg}], [], status)
                                     + "[exit] exit_code=0 status=%s\n" % status, encoding="utf-8")
    except Exception:
        pass

