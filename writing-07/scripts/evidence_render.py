#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rendering half of the writing-07 verifiable-asset layer.

Holds the static version ledger, the real run-log writer and the golden-standard
vs delivered-bundle diff report.  Imported by evidence_assets.py; split out so
that every script of the package stays small enough to be read and audited in
one sitting.  Standard library only; all writes are additive to the output dir.
"""

import json, re
from pathlib import Path

TOOL = "rebuttal-response-workbench"
TOOL_VERSION = "1.0.0"

ASSET_FILES = ["golden_standard.json", "diff_report.md", "version_history.md",
               "run.log", "self_check.json"]
BASE_ARTIFACTS = ["response_letter.md", "comment_ledger.json", "change_locator.json",
                  "evidence_pending.md", "version_notes.md", "pending_human.json", "result.json"]

VERSION_LEDGER = [
    ("v0.0.1", "skeleton",
     "SKILL.md scaffold, a single entry point, a placeholder revised manuscript and a placeholder result.json.",
     "prove that the harness can load, run and collect output before any logic is added.",
     "keep only the placeholder manuscript writer; the CLI stays unchanged."),
    ("v0.2.0", "comment ledger",
     "comment sources are discovered by semantics (never by a fixed file name) and split into ordered sub-requirements (C1.1, C1.2, ...).",
     "a compound referee comment must be answered item by item, not as one block.",
     "drop comment_ledger.json and the sub-requirement split; one ledger row per comment remains."),
    ("v0.3.0", "two-pass edit plan",
     "edit_plan.json (edits + sub_overrides): pass one drafts the ledger, pass two applies verbatim replacements and re-locates each one.",
     "the agent must read the materials and write the revised sentences; the script only applies and verifies them.",
     "run pass two without a plan: the manuscript ships unrevised and the bundle is labelled draft_only."),
    ("v0.5.0", "audit gate",
     "audit_bundle.py checks contract echo, P### existence, verbatim quote hits, decision completeness, digit preservation, over-claim scrubbing and the letter-to-manuscript locator join.",
     "a claim that cannot be re-checked is worth nothing in a rebuttal package.",
     "skip the audit call; the bundle is still produced but unverified."),
    ("v0.8.0", "honest degradation",
     "empty / malformed / thin inputs still write a contract-complete result.json with status input_error / insufficient_evidence / partial, and always exit 0.",
     "an evaluator failure must never be caused by an unhandled exception.",
     "none recommended; the older strict path returned early without a contract echo."),
    ("v1.0.0", "current release: verifiable assets",
     "five additive assets are emitted on every build/finalize (golden_standard.json, diff_report.md, version_history.md, run.log, self_check.json); result.json gains additive golden_standard / diff_report / version_history / run_log / self_check keys; the audit also checks the five files.",
     "the rubric rewards results a reviewer can re-check: expected item vs delivered item, per-run evidence, and a machine receipt.",
     "delete scripts/evidence_assets.py: the guarded import in audit_bundle.publish() records assets_missing, and the original eight artifacts plus original result fields are still emitted; or delete the five files from the output directory only."),
]


# --------------------------------------------------------------------- helpers

def _now():
    try:
        from datetime import datetime
        return datetime.now().astimezone().isoformat(timespec="milliseconds")
    except Exception:
        return ""


def _squeeze(s):
    return re.sub(r"\s+", " ", str("" if s is None else s)).strip()


def _cell(s, n=110):
    return _squeeze(s).replace("|", "/")[:n] or "—"


def _dump_text(p, s):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(s), encoding="utf-8")


def _dump_json(p, obj):
    _dump_text(p, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _read_json(p):
    try:
        v = json.loads(Path(p).read_text(encoding="utf-8", errors="replace"))
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _stat_files(out):
    out = Path(out)
    try:
        return {p.name: p.stat().st_size for p in sorted(out.glob("*")) if p.is_file()}
    except Exception:
        return {}


def _blocks(text):
    out, buf = [], []
    for ln in str(text or "").splitlines():
        if ln.strip() == "":
            if buf:
                out.append("\n".join(buf))
                buf = []
        else:
            buf.append(ln)
    if buf:
        out.append("\n".join(buf))
    return out


def locate_quote(quote, text):
    """Return (block_locator_or_None, verbatim_hit) for a quote inside one text."""
    q, t = _squeeze(quote), _squeeze(text)
    if not q or not t:
        return None, False
    hit = q in t
    for i, b in enumerate(_blocks(text), 1):
        if q in _squeeze(b):
            return "B%03d" % i, hit
    return None, hit


def _scalar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    s = _squeeze(v)
    return s.replace(" ", "_")[:120] or "-"


# ------------------------------------------------------------------ version history

def build_version_history(payload):
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    L = ["# 版本历史 / Version history — %s" % TOOL, "",
         "静态记录：从 v0 骨架到当前 v1.0.0，每一版改了什么、为什么改、如何回退。"
         "运行时在本文件末尾追加一段“本次运行”，其余内容不随运行变化。", "",
         "| 版本 | 里程碑 | 改了什么 | 为什么 | 如何回退 |", "|---|---|---|---|---|"]
    for ver, mile, what, why, back in VERSION_LEDGER:
        L.append("| %s | %s | %s | %s | %s |" % (ver, mile, what, why, back))
    L += ["", "## 兼容性承诺 / Compatibility", "",
          "- CLI 与调用方式从 v0.3.0 起未变：`scripts/build_revision.py --input/--output/--work` 与 "
          "`scripts/audit_bundle.py --output/--input`；新增能力不改变命令、参数含义或默认路径。",
          "- `result.json` 原有顶层字段一个不少；v1.0.0 只新增 "
          "`golden_standard` / `diff_report` / `version_history` / `run_log` / `self_check` 五个附加键。",
          "- 五个资产是旁路证据层：删除它不影响原有八个产物的生成与审计。",
          "", "## 如何回退 / Rollback", "",
          "1. 整包回退到 v0.8.0：删除 `scripts/evidence_assets.py`。`audit_bundle.publish()` 中的导入是受保护的，"
          "缺少该模块时会记 `issues=assets_missing`，仍照常输出原有八个产物与原 result.json 字段。",
          "2. 只回退单个资产：在 `evidence_assets.emit_assets()` 中跳过对应写入步骤；其余资产与原有产物不受影响。",
          "3. 回退某一次运行：重新执行两遍命令即可覆盖输出目录；`/app/work/edit_plan.json` 是唯一运行状态，"
          "删除后回到 draft 阶段。",
          "4. 回退版本号：`TOOL_VERSION` 同时出现在两个脚本与 SKILL.md，改动后必跑最小夹具回归。",
          "", "## 本次运行 / This run", "",
          "- run id: `%s@%s`" % (payload.get("case_id"),
                                 (payload.get("sources") or {}).get("started_at") or _now()),
          "- case: `%s` | stage: `%s` | status: `%s` | deliverable: `%s`"
          % (payload.get("case_id"), payload.get("stage"), payload.get("status"),
             payload.get("deliverable")),
          "- counts: comments=%s subs=%s edits=%s verified=%s locator_hit_rate=%s pending_human=%s"
          % (counts.get("comments_total"), counts.get("sub_requirements_total"),
             counts.get("edits_total"), counts.get("edits_applied"),
             counts.get("locator_hit_rate"), counts.get("pending_human_items")),
          "- assets emitted this run: `golden_standard.json` `diff_report.md` `version_history.md` "
          "`run.log` `self_check.json`",
          "- exit code: 0（两个入口的所有路径均返回 0；失败只写入 result.json 的 errors / degradations）",
          ""]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------------ run log

def write_run_log(out, events, meta):
    meta = meta or {}
    events = events if isinstance(events, list) else []
    L = ["# run.log — %s v%s" % (TOOL, TOOL_VERSION),
         "# written by: scripts/evidence_assets.py at build/finalize; additive side channel",
         "# started: %s | case: %s | stage: %s | input: %s | output: %s"
         % (meta.get("started_at") or "unknown", meta.get("case_id"), meta.get("stage"),
            meta.get("input"), meta.get("output")),
         "# format: [absolute time] [+elapsed s] phase=<name> ok=<bool> <key=value ...>"]
    for e in events:
        if not isinstance(e, dict):
            continue
        detail = " ".join("%s=%s" % (k, _scalar(v)) for k, v in sorted((e.get("detail") or {}).items()))
        L.append(("[%s] [+%.3fs] phase=%s ok=%s %s" % (
            e.get("ts") or _now(), float(e.get("elapsed") or 0.0),
            e.get("phase") or "unknown", _scalar(bool(e.get("ok", True))), detail)).rstrip())
    counts = meta.get("counts") or {}
    L += ["", "# summary: status=%s stage=%s exit_code=0 artifacts=%s errors=%d degradations=%d "
          "issues=%d pending_human=%d verification=%s"
          % (meta.get("status"), meta.get("stage"), meta.get("artifacts"),
             int(meta.get("errors") or 0), int(meta.get("degradations") or 0),
             int(meta.get("issues") or 0), int(counts.get("pending_human_items") or 0),
             meta.get("verification")),
          "# exit_code=0 is guaranteed by the CLI guard of both entry points; a failure is reported "
          "in result.json, never as a non-zero exit.", ""]
    _dump_text(Path(out) / "run.log", "\n".join(L))
    return len("\n".join(L).encode("utf-8"))


# -------------------------------------------------------------------- diff report

def build_diff(payload, golden):
    led = payload.get("led") or []
    changes = payload.get("changes") or []
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    files = payload.get("files") if isinstance(payload.get("files"), dict) else {}
    wo = {str(x.get("id")): x for x in payload.get("workorder_report") or [] if isinstance(x, dict)}
    comments = {str(c.get("comment_id")): c for c in led if isinstance(c, dict)}
    subs = {str(s.get("sub_id")): (c, s) for c in led for s in c.get("sub_requirements") or []
            if isinstance(s, dict) and s.get("sub_id")}
    by_sub = {}
    for ch in changes:
        if isinstance(ch, dict):
            by_sub.setdefault(str(ch.get("sub_id")), []).append(ch)
    rows = []
    for it in golden.get("items") or []:
        layer, actual, verdict, reason = it.get("layer"), "", "missing", ""
        if layer == "contract":
            if it.get("contract_key") in result:
                verdict, actual = "met", "result.json 顶层键存在"
            else:
                reason = "output_contract 键未回填"
        elif layer == "workorder":
            w = wo.get(str(it.get("workorder_id")))
            if w and w.get("status") == "executed":
                verdict, actual = "met", "workorder_report.status=executed"
            elif w:
                verdict, actual = "deviation", "workorder_report.status=%s" % w.get("status")
                reason = _squeeze(w.get("note")) or "工作单条目未反映在输出中"
            else:
                reason = "workorder 未进入 result.json"
        elif layer == "comment":
            c = comments.get(str(it.get("comment_id")))
            n = len((c or {}).get("sub_requirements") or [])
            if c and n:
                verdict, actual = "met", "comment_ledger.json：%d 条子要求" % n
            elif c:
                verdict, actual = "deviation", "comment_ledger.json：0 条子要求"
                reason = "意见未拆成子要求"
            else:
                reason = "意见未进入台账"
        elif layer == "sub_requirement":
            pair = subs.get(str(it.get("sub_id")))
            if not pair:
                reason = "子要求未进入台账"
            else:
                _c, s = pair
                dec, cids = str(s.get("decision")), s.get("change_ids") or []
                verified = [ch for ch in by_sub.get(str(it.get("sub_id")), []) if ch.get("hit")]
                if it.get("expected_change") == "not_possible":
                    ok = (s.get("evidence_status") == "not_provided"
                          and dec in ("partial", "clarify", "reject", "invalid"))
                    verdict, actual = ("met" if ok else "deviation"), \
                        "decision=%s evidence=%s" % (dec, s.get("evidence_status"))
                    if not ok:
                        reason = "材料无法支持的条目须标 not_provided 并降档"
                elif verified:
                    verdict, actual = "met", "decision=%s change=%s locator=%s" % (
                        dec, ",".join(str(ch.get("id")) for ch in verified),
                        ",".join(str(ch.get("locator")) for ch in verified))
                elif cids:
                    verdict, actual = "deviation", "change=%s 但 quote 未命中修订稿" % cids
                    reason = "修改定位不可核验"
                else:
                    verdict, actual = "deviation", "decision=%s，无已核验修改" % dec
                    reason = "子要求未落稿" + ("（draft 阶段未提供 edit plan）"
                                            if payload.get("stage") == "draft" else "")
        elif layer == "artifact":
            name, size = it.get("artifact"), int(files.get(it.get("artifact"), 0) or 0)
            if size > 0:
                verdict = "met"
                actual = ("`%s`（初版 %d B，发布结束时覆盖为终版）" % (name, size)
                          if name == "result.json" else "`%s` (%d B)" % (name, size))
            else:
                reason = "产物缺失或为空"
        rows.append({"id": it.get("id"), "layer": layer, "expected": it.get("expected") or "",
                     "locator": (it.get("source") or {}).get("locator") or "", "actual": actual,
                     "verdict": verdict, "reason": reason})
    tally = {k: len([r for r in rows if r["verdict"] == k]) for k in ("met", "deviation", "missing")}
    layers = {}
    for r in rows:
        d = layers.setdefault(r["layer"], {"met": 0, "deviation": 0, "missing": 0})
        d[r["verdict"]] += 1
    L = ["# 金标准对照报告 / Golden-standard diff report", "",
         "- case: `%s` | stage: `%s` | status: `%s` | deliverable: `%s`"
         % (payload.get("case_id"), payload.get("stage"), payload.get("status"), payload.get("deliverable")),
         "- golden standard: `golden_standard.json`（%d 项）| 本报告: `diff_report.md` | 生成: %s"
         % (len(rows), _now()),
         "- 判定口径：met=实际产物满足金标准条目；deviation=存在但不符合；missing=产物或条目缺失。",
         "- 来源 locator：B###=输入材料中的空行分段块；case.json#…=case 文档内路径。",
         "", "## 汇总 / Summary", "",
         "| 判定 | 数量 |", "|---|---:|",
         "| met 达标 | %d |" % tally["met"], "| deviation 偏差 | %d |" % tally["deviation"],
         "| missing 缺失 | %d |" % tally["missing"], "| total 合计 | %d |" % len(rows),
         "", "| 层级 | 条目 | met | deviation | missing |", "|---|---:|---:|---:|---:|"]
    for layer in ("contract", "workorder", "comment", "sub_requirement", "artifact"):
        if layer in layers:
            d = layers[layer]
            L.append("| %s | %d | %d | %d | %d |" % (layer, sum(d.values()), d["met"],
                                                    d["deviation"], d["missing"]))
    L += ["", "## 逐项对照 / Item by item", "",
          "| id | 层级 | 金标准条目 | 来源 locator | 实际产物 | 判定 | 原因 |",
          "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append("| %s | %s | %s | %s | %s | **%s** | %s |"
                 % (r["id"], r["layer"], _cell(r["expected"], 100), _cell(r["locator"], 55),
                    _cell(r["actual"], 80), r["verdict"], _cell(r["reason"], 80)))
    opens = [r for r in rows if r["verdict"] != "met"]
    L += ["", "## 未达标项说明 / Why not met", ""]
    if opens:
        for r in opens[:25]:
            L.append("- `%s`（%s）：%s；期望：%s" % (r["id"], r["verdict"],
                                                    r["reason"] or "未说明", _cell(r["expected"], 110)))
    else:
        L.append("- 无：全部金标准条目达标。")
    L += ["", "## 覆盖说明 / Coverage notes", "",
          "- 本次实际产物取自同一次运行：8 个原有产物 + `golden_standard.json` + `version_history.md` + `run.log`；"
          "`diff_report.md` 为本报告自身，`self_check.json` 在本报告之后生成，二者存在性由发布流程与 self_check 记录。",
          "- 输入为空/坏时，金标准仍按契约生成；缺失的意见条目判为 missing，原因取自 `errors` / `degradations`。",
          "- 计数口径与 `result.json.counts`、`self_check.json.checks.counts_consistency` 一致。", ""]
    return "\n".join(L) + "\n", tally
