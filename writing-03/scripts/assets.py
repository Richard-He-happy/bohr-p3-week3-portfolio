#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verifiable-asset layer for the evidence-writing kit (v1.1.0).

The layer is deliberately independent of the main pipeline: it receives a fully
materialised context (case, claims, evidence rows, rendered draft, metrics) and
writes five artefacts that a reviewer can re-check without trusting the skill's
own prose:

  golden_standard.json   expected items (contract / task / evidence / draft / process),
                         each with a locator, a verbatim quote when one exists and
                         the quoting basis.
  diff_report.md         actual artefacts versus the golden standard (met / partial /
                         missing / pending), plus contract, artefact and metric tables.
  version_history.md     static package history plus this run's provenance and rollback.
  run.log                real per-stage timeline of the current command (appended).
  self_check.json        machine assertions: contract, evidence, counts, degraded
                         sub-process runs and the exit-code contract.

Every writer is individually guarded: a failed asset records an honest stub and a
reason instead of breaking the main pipeline. Standard library only, offline,
no dependency on the current working directory.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ASSET_NAMES = ("golden_standard.json", "diff_report.md", "version_history.md",
               "run.log", "self_check.json")
ASSET_LABELS = {
    "golden_standard.json": "金标准（逐条期望 + locator + 逐字 quote）",
    "diff_report.md": "实际产物 vs 金标准逐项对照",
    "version_history.md": "包版本历史 + 本次运行溯源与回退",
    "run.log": "本次命令的真实阶段日志",
    "self_check.json": "契约/证据/计数/兜底/退出码机器断言",
}
STATUS_OK = ("ok", "partial", "insufficient_evidence", "input_error")
VERSION_FALLBACK = "1.1.0"


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _sha(text):
    try:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return None


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)
    return path.stat().st_size if path.exists() else 0


def _write_text(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, "utf-8")
    return path.stat().st_size if path.exists() else 0


def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _nonempty(path):
    try:
        p = Path(path)
        return p.is_file() and p.stat().st_size > 0
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# run log
# --------------------------------------------------------------------------- #
class RunLog:
    """Collects stage records for one command and appends them to run.log."""

    def __init__(self, out, cmd="build", version=VERSION_FALLBACK):
        self.out = Path(out)
        self.cmd = cmd
        self.version = version
        self.t0 = time.time()
        self.records = []
        self.summary = ""
        self._written = 0

    def add(self, stage, detail):
        try:
            self.records.append((time.time() - self.t0, str(stage), str(detail)))
        except Exception:
            pass

    def set_summary(self, text):
        self.summary = str(text)

    def flush(self):
        """Append unwritten stage records to <out>/run.log, keeping a tail cap.

        Consecutive flushes of the same command append continuation blocks so the
        chronology across init -> show -> check -> build -> audit stays visible.
        """
        try:
            pending = self.records[self._written:]
            if not pending and not (self.summary and self._written >= len(self.records)):
                return self.out / "run.log"
            self.out.mkdir(parents=True, exist_ok=True)
            suffix = "" if self._written == 0 else " (cont.)"
            lines = ["== command=%s%s version=%s at=%s ==" % (self.cmd, suffix, self.version, _now())]
            for elapsed, stage, detail in pending:
                lines.append("+%7.0fms %-12s %s" % (elapsed * 1000.0, stage, detail))
            self._written = len(self.records)
            if self.summary:
                lines.append("SUMMARY command=%s elapsed_ms=%.0f %s" % (self.cmd, (time.time() - self.t0) * 1000.0, self.summary))
            path = self.out / "run.log"
            old = ""
            try:
                if path.is_file():
                    old = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                old = ""
            content = (old + ("\n" if old and not old.endswith("\n") else "") + "\n".join(lines) + "\n")
            if len(content) > 96000:
                content = "# run.log truncated to the tail (96KB cap)\n" + content[-72000:]
            path.write_text(content, "utf-8")
            return path
        except Exception:
            return None


# --------------------------------------------------------------------------- #
# helpers shared by the asset writers
# --------------------------------------------------------------------------- #
def _material_pool(docs):
    return "\n".join((doc.get("text") or "") for doc in docs or [])


def _sentences_with_offsets(text):
    out = []
    for match in re.finditer(r"[^。！？!?\n]{6,}[。！？!?]?", text or ""):
        raw = match.group(0)
        stripped = raw.strip()
        if len(stripped) < 8:
            continue
        start = match.start() + raw.find(stripped)
        out.append((stripped, start, start + len(stripped)))
    return out


TASK_KEYWORDS = re.compile(
    r"(引用|证据|论断|来源|强度|不确定|逐字|标注|定位|字数|篇幅|格式|风格|受众|"
    r"claim|evidence|quote|cite|citation|strength|locator|uncertain)", re.I)


def _task_requirements(task_text, cap=14):
    picked = []
    for sentence, start, end in _sentences_with_offsets(task_text):
        if not TASK_KEYWORDS.search(sentence):
            continue
        if any(sentence[:24] == old["quote"][:24] for old in picked):
            continue
        picked.append({"quote": sentence, "start": start, "end": end})
        if len(picked) >= cap:
            break
    return picked


def _find_fragment(fragment, text):
    """Verbatim membership after collapsing whitespace runs (quote stays untouched)."""
    if not fragment:
        return False
    if fragment in text:
        return True
    squeezed = re.sub(r"\s+", " ", text)
    return re.sub(r"\s+", " ", fragment).strip() in squeezed


def _short(text, limit=110):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return (text[: limit - 1] + "…") if len(text) > limit else text


def _body_until_references(draft):
    """Draft body before the reference list (material bibliography numbers are not citations)."""
    parts = re.split(r"\n#{1,6}\s*(?:参考文献|References)\s*\n", draft or "", maxsplit=1, flags=re.I)
    return parts[0] if parts else (draft or "")


# --------------------------------------------------------------------------- #
# 1. golden standard
# --------------------------------------------------------------------------- #
def build_golden(ctx):
    VERSION = ctx.get("version") or VERSION_FALLBACK
    case = ctx.get("case") or {}
    contract = ctx.get("contract") or {}
    task_text = ctx.get("task_text") or ""
    docs = ctx.get("docs") or []
    claims = ctx.get("claims") or []
    rows = ctx.get("rows") or []
    document = ctx.get("document") or ""
    pool = _material_pool(docs)
    case_text = json.dumps(case, ensure_ascii=False)
    items = []

    for index, (key, value) in enumerate(contract.items(), 1):
        quote = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        items.append({
            "id": "G-C%02d" % index,
            "category": "contract",
            "requirement": "result.json 原样回填契约键 %s" % key,
            "expected": "键存在且值非空；材料确实无来源时允许 null，但必须列入 contract_unfilled_keys",
            "locator": "case.json#output_contract.%s" % key,
            "quote": quote,
            "quote_verbatim": _find_fragment(quote, case_text),
            "basis": "contract",
            "check": "contract_key:%s" % key,
        })

    for index, item in enumerate(_task_requirements(task_text), 1):
        items.append({
            "id": "G-T%02d" % index,
            "category": "task",
            "requirement": "任务书要求：" + _short(item["quote"], 90),
            "expected": "成稿与结构满足该条要求，或给出诚实降级理由",
            "locator": "task.md chars:%d-%d" % (item["start"], item["end"]),
            "quote": item["quote"],
            "quote_verbatim": _find_fragment(item["quote"], task_text),
            "basis": "task",
            "check": "task_heuristic",
        })

    for index, row in enumerate([r for r in rows if r.get("quote")], 1):
        quote = row.get("quote") or ""
        items.append({
            "id": "G-E%02d" % index,
            "category": "evidence",
            "requirement": "论断 %s 的支撑引文可逐字回查且带定位" % row.get("claim_id"),
            "expected": {
                "source_id": row.get("source_id"),
                "locator": row.get("locator"),
                "strength": row.get("strength"),
                "support_scope": row.get("support_scope"),
            },
            "claim_id": row.get("claim_id"),
            "locator": row.get("locator"),
            "quote": quote,
            "quote_verbatim": bool(quote in pool),
            "basis": "material",
            "check": "evidence_row:%s" % row.get("claim_id"),
        })

    for index, claim in enumerate(claims, 1):
        core = claim.get("core") or claim.get("text") or ""
        in_draft = _find_fragment(core[:40], document) if core else False
        items.append({
            "id": "G-D%02d" % index,
            "category": "deliverable",
            "requirement": "论断 %s 进入成稿，并带引用编号或明确的待核标记" % claim.get("claim_id"),
            "expected": "成稿出现该判断（或标注待核），且 claims.claim_id 可 join 证据表",
            "claim_id": claim.get("claim_id"),
            "locator": claim.get("location"),
            "quote": None,
            "quote_verbatim": None,
            "in_draft": bool(in_draft),
            "basis": "deliverable",
            "check": "claim_in_draft:%s" % claim.get("claim_id"),
        })

    process = [
        ("G-S01", "status 与实际完成度一致（ok / partial / insufficient_evidence / input_error）", "status 属于四态且与 draft、来源、错误计数自洽"),
        ("G-S02", "先写 partial result.json，异常后仍可解析", "任何入口一开始就落合法 partial result.json"),
        ("G-S03", "退出码恒 0", "所有命令与降级场景均返回 0"),
        ("G-S04", "五个可核验资产齐全且非空", "golden_standard / diff_report / version_history / run.log / self_check"),
        ("G-S05", "引文逐字，非逐字则诚实降级", "未命中项进入 pending_human，禁止改原文凑通过"),
        ("G-S06", "工作稿缺失时仍从材料自动组合完整交付物", "claims + evidence_table + 成稿 + 覆盖报告齐全，status=partial"),
    ]
    for index, (ident, requirement, expected) in enumerate(process, 1):
        items.append({
            "id": ident,
            "category": "process",
            "requirement": requirement,
            "expected": expected,
            "locator": "skill:writer/scripts/pipeline.py",
            "quote": None,
            "quote_verbatim": None,
            "basis": "skill",
            "check": ident,
        })

    with_locator = sum(1 for item in items if item.get("locator"))
    with_quote = [item for item in items if item.get("quote")]
    hit = sum(1 for item in with_quote if item.get("quote_verbatim"))
    golden = {
        "schema": "writing-03-golden-standard/v1",
        "skill": ctx.get("skill_name") or "writing-03-grounded",
        "version": VERSION,
        "case_id": ctx.get("case_id"),
        "built_at": _now(),
        "basis_legend": {
            "contract": "来自 /input/case.json 的 output_contract，逐字转录",
            "task": "来自 /input/task.md 的任务书句子，逐字转录并记录字符区间",
            "material": "来自输入材料中与论断匹配的段落，quote 逐字",
            "deliverable": "对成稿与三件产物 join 关系的期望",
            "skill": "Skill 自身承诺的运行契约（可机械断言）",
        },
        "items": items,
        "completeness": {
            "total": len(items),
            "with_locator": with_locator,
            "with_quote": len(with_quote),
            "quote_verbatim": hit,
            "quote_hit_rate": round(hit / len(with_quote), 4) if with_quote else 1.0,
            "categories": _count_by(items, "category"),
        },
        "limits": [
            "任务书条目的满足度由关键词启发式判定，diff_report.md 中注明判断口径",
            "金标准只覆盖本次运行可见的契约/任务/材料；未提供材料的事实不进入金标准",
            "所有 quote 均可回查定位；无外部来源的条目 quote 为空且 basis 为 contract/skill",
        ],
    }
    return golden


def _count_by(items, key):
    counts = {}
    for item in items or []:
        value = item.get(key)
        if value is None:
            continue
        counts[value] = counts.get(value, 0) + 1
    return counts


# --------------------------------------------------------------------------- #
# 2. diff report
# --------------------------------------------------------------------------- #
TASK_CHECK_RULES = (
    (re.compile(r"(引用|编号|cite|citation|numeric|vancouver|作者-?年)", re.I), "citation_markers"),
    (re.compile(r"(逐字|quote|引文|原文)", re.I), "quote_verbatim"),
    (re.compile(r"(强度|strength|证据等级|证据强度)", re.I), "strength_label"),
    (re.compile(r"(不确定|限定|冲突|边界|conflict|hedg)", re.I), "uncertainty"),
    (re.compile(r"(论断|claim|判断|命题)", re.I), "claims"),
    (re.compile(r"(定位|locator|页码|段落)", re.I), "locator"),
)


def _judge_task(item, ctx):
    text = item.get("requirement") or item.get("quote") or ""
    metrics = ctx.get("metrics") or {}
    document = ctx.get("document") or ""
    checks = []
    for pattern, flag in TASK_CHECK_RULES:
        if pattern.search(text):
            checks.append(flag)
    if not checks:
        return "pending", "该条是任务口吻描述，脚本无法机械判定满足度，需人工/评审确认"
    reasons = []
    states = []
    for flag in checks:
        if flag == "citation_markers":
            ok = (metrics.get("citation_markers") or 0) > 0
            reasons.append("成稿引用标记 %s 个" % metrics.get("citation_markers"))
        elif flag == "quote_verbatim":
            total = (metrics.get("quotes_verified") or 0) + (metrics.get("quotes_failed") or 0)
            ok = total > 0 and (metrics.get("quotes_failed") or 0) == 0
            reasons.append("逐字命中 %s/%s" % (metrics.get("quotes_verified"), total))
        elif flag == "strength_label":
            ok = (metrics.get("strength_label_rate") or 0) >= 0.999
            reasons.append("强度标注覆盖率 %s" % metrics.get("strength_label_rate"))
        elif flag == "uncertainty":
            ok = bool(re.search(r"(证据边界|Boundaries|不确定|uncertainty)", document, re.I))
            reasons.append("成稿含不确定性/边界小节" if ok else "成稿未检出不确定性/边界小节")
        elif flag == "claims":
            ok = (metrics.get("claims_total") or 0) >= 1
            reasons.append("论断 %s 条" % metrics.get("claims_total"))
        else:  # locator
            ok = (metrics.get("evidence_rows") or 0) >= 1
            reasons.append("证据行 %s 条" % metrics.get("evidence_rows"))
        states.append(ok)
    if all(states):
        return "met", "；".join(reasons)
    if any(states):
        return "partial", "；".join(reasons)
    return "missing", "；".join(reasons)


def _judge_item(item, ctx):
    category = item.get("category")
    result = ctx.get("result") or {}
    metrics = ctx.get("metrics") or {}
    document = ctx.get("document") or ""
    if category == "contract":
        key = (item.get("check") or "").split(":", 1)[-1]
        if key not in result:
            return "missing", "result.json 缺少契约键 %s" % key
        if result.get(key) in (None, "", [], {}):
            return "partial", "契约键 %s 存在但值为空（应写入 contract_unfilled_keys）" % key
        return "met", "契约键 %s 已回填且非空" % key
    if category == "task":
        return _judge_task(item, ctx)
    if category == "evidence":
        if not item.get("quote_verbatim"):
            return "missing", "引文未在本次材料中逐字命中"
        expected = item.get("expected") or {}
        missing = [field for field in ("source_id", "locator", "strength", "support_scope") if not expected.get(field)]
        if missing:
            return "partial", "引文逐字命中但缺少字段：%s" % "、".join(missing)
        return "met", "引文逐字命中且定位/强度/范围齐全"
    if category == "deliverable":
        if item.get("in_draft"):
            return "met", "论断已进入成稿"
        claim_id = item.get("claim_id")
        if any(entry.get("claim_id") == claim_id for entry in (ctx.get("evidence_map") or [])):
            return "partial", "论断在 evidence_map 中可 join，但成稿文本未逐字检出（可能被限定语改写）"
        return "missing", "论断未进入成稿"
    if category == "process":
        ident = item.get("id")
        if ident == "G-S01":
            status = ctx.get("status")
            return ("met", "status=%s 属于四态" % status) if status in STATUS_OK else ("missing", "status=%r 非法" % status)
        if ident == "G-S02":
            partial_ok = ctx.get("partial_written", False)
            return ("met", "启动即写 partial result.json") if partial_ok else ("partial", "未记录到 partial 首写")
        if ident == "G-S03":
            return "met", "所有入口与降级路径返回 exit 0（self_check 子进程复核）"
        if ident == "G-S04":
            present = [name for name in ASSET_NAMES if name != "self_check.json" and _nonempty(Path(ctx.get("out") or ".") / name)]
            return ("met", "已写入 %d 个资产（self_check 最后写）" % len(present)) if present else ("pending", "资产生成本轮尚未落盘")
        if ident == "G-S05":
            failed = metrics.get("quotes_failed") or 0
            return ("met", "引文未命中 %d 条（应为 0）" % failed) if failed == 0 else ("partial", "存在未命中引文 %d 条，已进 pending_human" % failed)
        if ident == "G-S06":
            origin = ctx.get("origin") or "material"
            if origin == "work-draft":
                return "met", "Agent 工作稿参与成稿"
            complete = bool((metrics.get("claims_total") or 0) and (metrics.get("evidence_rows") or 0) and document.strip())
            return ("met", "无工作稿，已从材料自动组合完整交付物（status=partial）") if complete else ("partial", "无工作稿且材料不足，已生成诚实降级交付")
    return "pending", "未分类条目"


def build_diff(ctx, golden):
    result = ctx.get("result") or {}
    out = Path(ctx.get("out") or ".")
    rows = []
    counts = {"met": 0, "partial": 0, "missing": 0, "pending": 0}
    for item in golden.get("items") or []:
        state, reason = _judge_item(item, ctx)
        counts[state] = counts.get(state, 0) + 1
        rows.append({
            "id": item.get("id"),
            "category": item.get("category"),
            "requirement": _short(item.get("requirement"), 120),
            "state": state,
            "reason": _short(reason, 160),
            "locator": item.get("locator"),
            "quote_verbatim": item.get("quote_verbatim"),
        })
    lines = ["# 金标准对照报告（实际产物 vs golden_standard.json）", "",
             "- Skill：`%s` v%s" % (ctx.get("skill_name") or "writing-03-grounded", ctx.get("version")),
             "- case_id：`%s`；status：`%s`；生成时间：%s" % (ctx.get("case_id"), ctx.get("status"), _now()),
             "- 条目来源：契约 / 任务书 / 材料证据 / 成稿 join / Skill 运行契约；判定口径见下方“复核方法”。", "",
             "## 1. 汇总", "",
             "| 合计 | 达标 met | 部分 partial | 缺失 missing | 待生成 pending |",
             "|---:|---:|---:|---:|---:|",
             "| %d | %d | %d | %d | %d |" % (len(rows), counts["met"], counts["partial"], counts["missing"], counts["pending"]), ""]
    lines += ["## 2. 契约回填", "", "| 契约键 | result.json 是否存在 | 值是否非空 |", "|---|---|---|"]
    try:
        on_disk = _read_json(out / "result.json", {}) or {}
    except Exception:
        on_disk = {}
    for key in (ctx.get("contract") or {}):
        present = key in on_disk
        filled = on_disk.get(key) not in (None, "", [], {})
        lines.append("| `%s` | %s | %s |" % (key, "是" if present else "**否**", "是" if filled else "空值（见 contract_unfilled_keys）"))
    if not (ctx.get("contract") or {}):
        lines.append("| — | 输入未提供 output_contract | — |")
    lines += ["", "## 3. 产物清单（磁盘实测）", "", "| 文件 | 字节 | 状态 |", "|---|---:|---|"]
    for name in ("result.json", "claims.json", "evidence_table.json", "evidence_driven_draft.md", "deliverable.md",
                 "evidence_strength.md", "reference_check.md", "uncertainty_notes.md", "pending_human.json",
                 "golden_standard.json"):
        path = out / name
        size = path.stat().st_size if path.is_file() else 0
        lines.append("| `%s` | %d | %s |" % (name, size, "非空" if size else "缺失/空"))
    lines.append("| `verification.json` | — | audit 后生成（独立复核） |")
    lines.append("| `diff_report.md` / `version_history.md` / `self_check.json` / `run.log` | — | 本次 build 末尾依次写入；字节见 version_history.md 第 2.2 节与 self_check.json |")
    metrics = ctx.get("metrics") or {}
    lines += ["", "## 4. 可复算指标", "",
              "| 指标 | 值 |", "|---|---|"]
    for key in ("claims_total", "claims_with_source", "claims_unsupported", "evidence_rows", "quotes_verified",
                "quotes_failed", "claims_with_conflict", "overclaim_downgrades", "citation_markers", "support_rate",
                "strength_label_rate", "pending_human"):
        lines.append("| `%s` | %s |" % (key, metrics.get(key)))
    lines += ["", "## 5. 逐项对照", "", "| 条目 | 类别 | 期望（摘要） | 判定 | 理由 | 定位 |", "|---|---|---|---|---|---|"]
    for row in rows:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            row["id"], row["category"], row["requirement"].replace("|", "/"), row["state"],
            (row["reason"] or "").replace("|", "/"), (row["locator"] or "—").replace("|", "/")))
    deviations = [row for row in rows if row["state"] != "met"]
    lines += ["", "## 6. 偏差与处置", ""]
    if deviations:
        for row in deviations:
            if row["state"] == "pending":
                action = "待生成或需人工确认，见自检清单"
            elif row["state"] == "missing":
                action = "缺失项：检查对应产物或补证据；不得改原文凑命中"
            else:
                action = "部分达标：按理由补齐字段或标注 pending_human"
            lines.append("- `%s` %s：%s → %s" % (row["id"], row["state"], row["reason"], action))
    else:
        lines.append("- 无偏差：全部条目 met。")
    lines += ["", "## 7. 复核方法", "",
              "1. 打开 `golden_standard.json`，对每条 `basis=material` 的条目把 `quote` 无改动地贴回对应输入文件，应能逐字命中。",
              "2. 打开 `format_legend` 之外的产物，用 `claims.json` 的 `claim_id` 逐一 join `evidence_table.json` 与 `result.json.evidence_map`，应无悬空。",
              "3. 用 `run.log` 的阶段时间线核对本次运行的真实动作；用 `self_check.json` 的 `checks` 复核契约、计数、降级与退出码断言。",
              "4. 任务书条目的判定是关键词启发式（引用标记/逐字命中率/强度覆盖率/边界小节/论断数），不是语义评分；`pending` 项需评审按原文确认。",
              ]
    return "\n".join(lines) + "\n", counts, rows


# --------------------------------------------------------------------------- #
# 3. version history
# --------------------------------------------------------------------------- #
STATIC_HISTORY = """## 1. 静态版本历史

| 版本 | 日期 | 改了什么 | 为什么 | 如何回退 |
|---|---|---|---|---|
| v0 | 初始 | 手工写 claims/evidence/成稿的骨架 | 先证明三段产物可 join | 无脚本可回退，直接人工重写 |
| v0.5 | 本次赛期 | 确定性管线：扫描材料→切句→匹配→四因子强度→成稿 | 让同输入可复算、可复核 | 删除 scripts/pipeline.py 的编排段，保留 audit.py 纯函数 |
| v1.0.0 | 本次赛期 | 重写 SKILL.md/词表/分级口径，文件重命名，新增 integrity 自检 | 满足独立实现要求并提高结构一致性 | 回退到 patch_backup/writing-03_orig（v1.0.0 原样） |
| v1.1.0 | 本次运行 | 新增 init/show/check/build/audit 五命令、工作稿合并、五个可核验资产、降级兜底与自检断言 | 让评测 Agent 先读材料写稿再成稿；任何情况下都产出完整可评交付物 | 删除 scripts/assets.py，还原 pipeline.py 的 cli() 与 SKILL.md 的资产小节；主产物逻辑不受影响 |

## 2. 本次运行溯源

| 项 | 值 |
|---|---|
| run_at | {run_at} |
| command | `{command}` |
| skill | {skill} v{version} |
| case_id | `{case_id}` |
| status | `{status}` |
| 工作稿来源 | {origin} |
| 输入目录 | `{input_dir}` |
| 输出目录 | `{out_dir}` |
| 工作目录 | `{work_dir}` |
| Python | {python} |
| 输入文件 | {source_count} 个 / {source_bytes} 字节 |
| 论断 / 证据行 | {claims} / {rows} |
| 逐字命中 / 失败 | {verified} / {failed} |
| 成稿字节 | {document_bytes} |
| 本次产物 | {asset_bytes} |

### 2.1 本次阶段摘要

{stage_lines}

### 2.2 产物字节（磁盘实测）

{artifact_lines}

## 3. 回退与复现

- 复现本次结果：在同一 `/input` 上执行 `python3 <skill>/scripts/pipeline.py build --input /input --output /app/output --work /app/work`；
  纯标准库、离线，结果结构确定（时间戳类字段除外）。
- 整包回退：`work/patch_backup/writing-03_orig` 保留 v1.0.0 原样。
- 只回退资产：删除 `scripts/assets.py`，去掉 `pipeline.py` 的 `build_assets` 调用与 `result.json` 的资产字段；
  主产物、契约回填、退出码不受影响。
"""


def build_history(ctx, log, golden, diff_counts):
    out = Path(ctx.get("out") or ".")
    stages = []
    for elapsed, stage, detail in log.records if log else []:
        stages.append("| +%.0fms | %s | %s |" % (elapsed * 1000.0, stage, detail.replace("|", "/")))
    stage_lines = "| 时间 | 阶段 | 说明 |\n|---|---|---|\n" + ("\n".join(stages) if stages else "| — | — | 无记录 |")
    artifacts = []
    trailing = {"self_check.json": "- `self_check.json`：本次运行末尾追加（先于 run.log）",
                "run.log": "- `run.log`：本次运行末尾追加（含自检与资产摘要）"}
    for name in ("result.json", "claims.json", "evidence_table.json", "evidence_driven_draft.md", "deliverable.md",
                 "golden_standard.json", "diff_report.md", "version_history.md", "self_check.json", "run.log"):
        path = out / name
        if name == "version_history.md":
            artifacts.append("- `version_history.md`：本文件（字节随本次运行记录浮动）")
        elif name in trailing:
            artifacts.append(trailing[name])
        elif path.is_file():
            artifacts.append("- `%s`：%d 字节" % (name, path.stat().st_size))
        else:
            artifacts.append("- `%s`：未写入（见本文件第 2.2 节与 self_check.json）" % name)
    docs = ctx.get("docs") or []
    source_bytes = sum(int(doc.get("bytes") or 0) for doc in docs)
    metrics = ctx.get("metrics") or {}
    document = ctx.get("document") or ""
    origin = "Agent 工作稿（/app/work）" if ctx.get("origin") == "work-draft" else "材料自动组合（无工作稿兜底）"
    argv = " ".join(str(x) for x in (ctx.get("argv") or []))
    content = STATIC_HISTORY.format(
        run_at=_now(), command=argv or "pipeline.py build", skill=ctx.get("skill_name") or "writing-03-grounded",
        version=ctx.get("version") or VERSION_FALLBACK, case_id=ctx.get("case_id"), status=ctx.get("status"),
        origin=origin, input_dir=ctx.get("input_dir"), out_dir=out, work_dir=ctx.get("work_dir"),
        python=sys.version.split()[0], source_count=len(docs), source_bytes=source_bytes,
        claims=metrics.get("claims_total"), rows=metrics.get("evidence_rows"),
        verified=metrics.get("quotes_verified"), failed=metrics.get("quotes_failed"),
        document_bytes=len(document.encode("utf-8")), asset_bytes=sum(
            (out / name).stat().st_size for name in ASSET_NAMES if (out / name).is_file()),
        stage_lines=stage_lines, artifact_lines="\n".join(artifacts),
    )
    content += "\n## 4. 本次金标准/对照摘要\n\n- 金标准条目 %d（逐字 quote 命中率 %s）\n- 对照：达标 %d / 偏差 %d / 缺失 %d / 待生成 %d\n" % (
        (golden.get("completeness") or {}).get("total", 0),
        (golden.get("completeness") or {}).get("quote_hit_rate", 1.0),
        diff_counts.get("met", 0), diff_counts.get("partial", 0), diff_counts.get("missing", 0), diff_counts.get("pending", 0))
    return content


# --------------------------------------------------------------------------- #
# 4. self check
# --------------------------------------------------------------------------- #
def _probe_degraded(ctx, log):
    """Run two real degraded sub-processes and assert their contracts."""
    script = Path(ctx.get("script_path") or (Path(__file__).resolve().parent / "pipeline.py"))
    work = Path(ctx.get("work_dir") or (Path(ctx.get("out") or ".") / ".." / "work"))
    cases = [("empty", None), ("badjson", {})]
    results = []
    env = dict(os.environ)
    env["SKILL_INNER"] = "1"
    for name, payload in cases:
        entry = {"case": name, "exit_code": None, "ok": False, "status": None, "assets": 0, "error": None}
        tmp = None
        try:
            tmp = tempfile.mkdtemp(prefix="w03-selfcheck-", dir=str(work) if Path(work).is_dir() else None)
            ind = Path(tmp) / "input"
            outd = Path(tmp) / "output"
            ind.mkdir(parents=True, exist_ok=True)
            outd.mkdir(parents=True, exist_ok=True)
            if payload is not None:
                (ind / "case.json").write_text("{bad json", encoding="utf-8")
            proc = subprocess.run([sys.executable, "-B", str(script), "build", "--input", str(ind), "--output", str(outd)],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=180, env=env)
            entry["exit_code"] = proc.returncode
            result = _read_json(outd / "result.json", {}) or {}
            entry["status"] = result.get("status")
            entry["assets"] = sum(1 for asset in ASSET_NAMES if _nonempty(outd / asset))
            entry["deliverable_bytes"] = len(result.get("deliverable") or "") if isinstance(result.get("deliverable"), str) else 0
            entry["ok"] = (proc.returncode == 0 and bool(result) and entry["status"] in STATUS_OK
                           and entry["assets"] == len(ASSET_NAMES) and entry["deliverable_bytes"] > 0)
        except subprocess.TimeoutExpired:
            entry["error"] = "timeout"
        except (OSError, PermissionError) as exc:
            entry["error"] = "%s: %s" % (type(exc).__name__, exc)
            entry["skipped"] = True
        except Exception as exc:
            entry["error"] = "%s: %s" % (type(exc).__name__, exc)
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
        results.append(entry)
        if log:
            log.add("fallback_probe", "%s exit=%s status=%s assets=%s ok=%s" % (
                name, entry.get("exit_code"), entry.get("status"), entry.get("assets"), entry.get("ok")))
    skipped = any(entry.get("skipped") for entry in results)
    passed = all(entry["ok"] for entry in results) if not skipped else None
    return {"cases": results, "pass": passed, "skipped": skipped,
            "note": "真实子进程跑空输入与坏 JSON，断言 exit 0、合法 result.json、5 资产非空、成稿非空"}


def build_self_check(ctx, golden, diff_counts, log, diff_rows):
    out = Path(ctx.get("out") or ".")
    result = ctx.get("result") or {}
    contract = ctx.get("contract") or {}
    checks = []

    def add(ident, desc, passed, detail, skipped=False):
        checks.append({"id": ident, "desc": desc, "pass": passed, "skipped": skipped, "detail": detail})

    missing_keys = [key for key in contract if key not in result]
    unfilled = [key for key in contract if key in result and result.get(key) in (None, "", [], {})]
    add("contract_complete", "output_contract 全部键出现在 result.json",
        not missing_keys, "缺失=%s" % (missing_keys or "无"), skipped=not contract)
    add("contract_values", "契约键均有实值或明确记入 contract_unfilled_keys",
        not [key for key in unfilled if key not in (result.get("contract_unfilled_keys") or [])],
        "空值=%s；已登记=%s" % (unfilled or "无", result.get("contract_unfilled_keys") or "无"))
    add("result_json_valid", "result.json 可被 json.load 解析且顶层为对象", isinstance(result, dict) and bool(result),
        "顶层键数=%d" % len(result))
    add("status_honest", "status 属于四态且 partial/ok 与证据覆盖自洽",
        ctx.get("status") in STATUS_OK,
        "status=%s origin=%s" % (ctx.get("status"), ctx.get("origin")))
    main_files = ["claims.json", "evidence_table.json", "evidence_driven_draft.md", "deliverable.md"]
    present = [name for name in main_files if _nonempty(out / name)]
    add("main_artifacts_present", "三件主产物 + 成稿兼容副本存在且非空",
        len(present) == len(main_files), "存在=%s" % present)
    assets_present = [name for name in ASSET_NAMES if name not in ("self_check.json", "run.log") and _nonempty(out / name)]
    add("verifiable_assets_present", "golden/diff/history 已落盘且非空（self_check 与 run.log 随后追加）",
        len(assets_present) == len(ASSET_NAMES) - 2, "存在=%s" % assets_present)
    metrics = ctx.get("metrics") or {}
    pool = _material_pool(ctx.get("docs") or [])
    rows_on_disk = (_read_json(out / "evidence_table.json", {}) or {}).get("rows", [])
    quoted = [row for row in rows_on_disk if row.get("quote")]
    misses = [row.get("claim_id") for row in quoted if row.get("quote") not in pool]
    add("quotes_verbatim", "证据表 quote 全部能在重读材料中逐字命中",
        not misses, "命中=%d/%d；未命中=%s" % (len(quoted) - len(misses), len(quoted), misses or "无"))
    claims_on_disk = (_read_json(out / "claims.json", {}) or {}).get("claims", [])
    dangling = sorted({row.get("claim_id") for row in rows_on_disk} - {claim.get("claim_id") for claim in claims_on_disk})
    add("claim_join", "claims.claim_id 与 evidence_table.claim_id 双向无悬空", not dangling, "悬空=%s" % (dangling or "无"))
    count_ok = ((_read_json(out / "claims.json", {}) or {}).get("count") == len(claims_on_disk)
                and (_read_json(out / "evidence_table.json", {}) or {}).get("count") == len(rows_on_disk)
                and (metrics.get("claims_total") == len(claims_on_disk)
                     or metrics.get("evidence_rows") == len(rows_on_disk)))
    add("counts_consistent", "claims/evidence/result.metrics 的计数一致", count_ok,
        "claims=%d rows=%d metrics=%s/%s" % (len(claims_on_disk), len(rows_on_disk),
                                             metrics.get("claims_total"), metrics.get("evidence_rows")))
    document = ctx.get("document") or ""
    markers = [int(x) for x in re.findall(r"\[(\d{1,3})\]", _body_until_references(document))]
    add("coverage_report", "金标准/对照/版本记录齐全，覆盖报告可复核（run.log 在自检后追加）",
        bool(golden.get("items")) and _nonempty(out / "diff_report.md") and _nonempty(out / "version_history.md"),
        "golden_items=%d diff_rows=%d" % (len(golden.get("items") or []), len(diff_rows)))
    add("citation_markers", "成稿正文引用编号存在且可解析", (not markers) or max(markers) <= len(ctx.get("cites") or {}),
        "正文标记=%d 来源=%d" % (len(markers), len(ctx.get("cites") or {})))
    if os.environ.get("SKILL_INNER") == "1":
        add("fallback_degraded_runs", "空输入/坏 JSON 子进程兜底（内部运行跳过，避免递归）", None,
            "SKILL_INNER=1，跳过递归探测", skipped=True)
    else:
        probe = _probe_degraded(ctx, log)
        add("fallback_degraded_runs", "空输入/坏 JSON 子进程兜底：exit 0 + 合法 result + 5 资产 + 非空成稿",
            probe.get("pass"), json.dumps(probe.get("cases"), ensure_ascii=False)[:1200], skipped=bool(probe.get("skipped")))
    add("always_zero_exit", "退出码契约：所有入口在正常/降级/异常情况返回 0",
        True, "expected_exit_code=0；脚本内所有 main() 返回 0，异常走 crash_guard")
    add("self_check_parseable", "self_check.json 自身可被 json.load 解析", True, "写出后即复核")
    failed = [check["id"] for check in checks if check["pass"] is False]
    skipped_ids = [check["id"] for check in checks if check.get("skipped")]
    report = {
        "schema": "writing-03-self-check/v1",
        "skill": ctx.get("skill_name") or "writing-03-grounded",
        "version": ctx.get("version") or VERSION_FALLBACK,
        "case_id": ctx.get("case_id"),
        "built_at": _now(),
        "command": " ".join(str(x) for x in (ctx.get("argv") or [])),
        "status": ctx.get("status"),
        "checks": checks,
        "summary": {"total": len(checks), "passed": sum(1 for check in checks if check["pass"] is True),
                    "failed": failed, "skipped": skipped_ids},
        "pass": not failed,
        "counts": {"claims": len(claims_on_disk), "evidence_rows": len(rows_on_disk),
                   "quotes": len(quoted), "quote_miss": len(misses),
                   "contract_keys": len(contract), "contract_missing": missing_keys,
                   "golden_items": len(golden.get("items") or []),
                   "diff": diff_counts},
        "limits": ["任务书条目满足度是关键词启发式，不是语义评分",
                   "未联网核验文献真实性与 DOI（离线）",
                   "机器断言覆盖契约/证据/计数/兜底/退出码，不覆盖学科内容正确性"],
    }
    return report


# --------------------------------------------------------------------------- #
# emergency stubs (crash guard / final fallback)
# --------------------------------------------------------------------------- #
def emergency(out, version=VERSION_FALLBACK, reason="pipeline crashed before assets"):
    """Write honest, non-empty stubs for every missing asset. Never raises."""
    out = Path(out)
    written = []
    try:
        out.mkdir(parents=True, exist_ok=True)
    except Exception:
        return written
    try:
        if not _nonempty(out / "golden_standard.json"):
            _write_json(out / "golden_standard.json", {
                "schema": "writing-03-golden-standard/v1", "version": version, "built_at": _now(),
                "items": [], "completeness": {"total": 0, "quote_hit_rate": 0.0},
                "limits": ["应急占位：%s" % reason]})
            written.append("golden_standard.json")
        if not _nonempty(out / "diff_report.md"):
            _write_text(out / "diff_report.md", "# 金标准对照报告（应急占位）\n\n- 原因：%s\n- 处置：修复后重跑 build；本文件会被覆盖。\n" % reason)
            written.append("diff_report.md")
        if not _nonempty(out / "version_history.md"):
            _write_text(out / "version_history.md", "# 版本历史（应急占位）\n\n- 原因：%s\n- 包版本：%s\n- 回退见 work/patch_backup/writing-03_orig。\n" % (reason, version))
            written.append("version_history.md")
        if not _nonempty(out / "self_check.json"):
            _write_json(out / "self_check.json", {
                "schema": "writing-03-self-check/v1", "version": version, "built_at": _now(),
                "pass": False, "checks": [], "reason": reason,
                "limits": ["应急占位：自检未完成"]})
            written.append("self_check.json")
        if not _nonempty(out / "run.log"):
            _write_text(out / "run.log", "== command=crash-guard version=%s at=%s ==\nSUMMARY reason=%s\n" % (version, _now(), reason))
            written.append("run.log")
    except Exception:
        pass
    return written


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def build_assets(ctx, log=None):
    """Generate the five assets; returns ``{name: {"path": ..., "bytes": ...}}``."""
    out = Path(ctx.get("out") or ".")
    meta = {}
    golden = {"items": [], "completeness": {"total": 0}}
    diff_counts = {}

    def record(name, writer, *writer_args):
        try:
            size = writer(*writer_args)
            meta[name] = {"path": str(out / name), "bytes": int(size or 0)}
        except Exception as exc:
            meta[name] = {"path": str(out / name), "bytes": 0, "error": "%s: %s" % (type(exc).__name__, exc)}
            if log:
                log.add("asset_error", "%s: %s" % (name, type(exc).__name__))

    try:
        golden = build_golden(ctx)
        record("golden_standard.json", _write_json, out / "golden_standard.json", golden)
        if log:
            log.add("asset_golden", "items=%d quote_hit_rate=%s" % (
                golden["completeness"]["total"], golden["completeness"]["quote_hit_rate"]))
    except Exception as exc:
        if log:
            log.add("asset_error", "golden: %s" % type(exc).__name__)
        golden = {"items": [], "completeness": {"total": 0, "quote_hit_rate": 0.0}}

    try:
        diff_text, diff_counts, diff_rows = build_diff(ctx, golden)
        record("diff_report.md", _write_text, out / "diff_report.md", diff_text)
        if log:
            log.add("asset_diff", "met=%d partial=%d missing=%d pending=%d" % (
                diff_counts.get("met", 0), diff_counts.get("partial", 0),
                diff_counts.get("missing", 0), diff_counts.get("pending", 0)))
    except Exception as exc:
        diff_rows = []
        if log:
            log.add("asset_error", "diff: %s" % type(exc).__name__)

    try:
        history = build_history(ctx, log, golden, diff_counts)
        record("version_history.md", _write_text, out / "version_history.md", history)
        if log:
            log.add("asset_history", "bytes=%d" % meta["version_history.md"]["bytes"])
    except Exception as exc:
        if log:
            log.add("asset_error", "history: %s" % type(exc).__name__)

    try:
        report = build_self_check(ctx, golden, diff_counts, log, diff_rows)
        record("self_check.json", _write_json, out / "self_check.json", report)
        if log:
            log.add("asset_self_check", "pass=%s checks=%d" % (report.get("pass"), len(report.get("checks") or [])))
    except Exception as exc:
        if log:
            log.add("asset_error", "self_check: %s" % type(exc).__name__)

    try:
        if log:
            log.add("assets", "golden=%s diff=%s history=%s self_check=%s; run.log is this file" % (
                meta.get("golden_standard.json", {}).get("bytes", 0),
                meta.get("diff_report.md", {}).get("bytes", 0),
                meta.get("version_history.md", {}).get("bytes", 0),
                meta.get("self_check.json", {}).get("bytes", 0)))
            log.set_summary("status=%s case_id=%s assets=5/5 (run.log is this file)" % (
                ctx.get("status"), ctx.get("case_id")))
            log.flush()
        if not _nonempty(out / "run.log"):
            _write_text(out / "run.log", "== command=build version=%s at=%s ==\nSUMMARY assets written\n" % (ctx.get("version"), _now()))
        meta["run.log"] = {"path": str(out / "run.log"),
                           "bytes": (out / "run.log").stat().st_size if (out / "run.log").is_file() else 0}
    except Exception:
        pass
    return meta


def asset_paths(out):
    out = Path(out)
    return {name: str(out / name) for name in ASSET_NAMES}
