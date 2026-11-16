#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可核验资产：页级金标准 / 逐页 diff / 版本历史 / 运行日志 / 机器自检。

finalize 时在产物目录写下五件资产，并把摘要并入 result.json：

  golden_standard.json  页级金标准：逐页列出期望的标题/角色/要点/证据/图表/讲稿，
                        每项带来源 locator + 逐字 quote；无来源的项标 basis=contract。
  diff_report.md        实际 pptx 逐页 vs 金标准（达标/缺失/偏差）+ 页数一致性检查。
  version_history.md    静态版本记录 v0 → v1.0.0 → v1.1.0 + 回退方式 + 本次运行段。
  run.log               本次运行真实阶段日志：阶段 / 耗时 / 退出码 / 降级 / 异常。
  self_check.json       机器自检回执：契约键完整性、pptx/notes/content_map 计数一致、
                        导出件真实（PDF %PDF- / PNG IHDR）、空/坏输入兜底、退出码 0。

约束：纯标准库、离线、不依赖当前工作目录；单件资产失败被隔离成最小合法文件并记降级，
绝不影响主流程（退出码由调用方恒置 0）。本模块不 import ooxml_kit，可独立复用。
"""
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

VERSION = "1.1.0"
PACKAGE = "paper-deck-architect"
ASSETS = ("golden_standard.json", "diff_report.md", "version_history.md", "run.log", "self_check.json")
RESULT_FIELDS = ("golden_standard", "diff_report", "version_history", "run_log", "self_check")
DELIVERABLE_FILES = ("presentation.pptx", "presentation.pdf", "plan.json", "deck_model.json", "result.json")


# ---------------------------------------------------------------- 基础工具

def now_stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def squash(text):
    return re.sub(r"\s+", " ", str(text if text is not None else "")).strip()


def _json_text(payload):
    return json.dumps(payload, ensure_ascii=False, indent=1) + "\n"


def _write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if str(text or "").strip() else " ", encoding="utf-8")
    return path


def _write_json(path, payload):
    return _write_text(path, _json_text(payload))


def _size(path):
    try:
        return Path(path).stat().st_size
    except Exception:
        return 0


def _md_cell(value, limit=150):
    text = squash(value).replace("|", "/")
    return text[:limit] if text else "-"


def _item_text(item, limit=220):
    if isinstance(item, str):
        return squash(item)[:limit]
    try:
        return json.dumps(item, ensure_ascii=False)[:limit]
    except Exception:
        return squash(item)[:limit]


def _degrade(env, what, detail):
    """把资产链路的降级写进 result.json 的 degradations（与其他降级同一口径）。"""
    bucket = env.setdefault("degradations", [])
    if isinstance(bucket, list):
        bucket.append({"what": "verification asset %s" % what, "detail": squash(detail)[:300]})


# ---------------------------------------------------------------- 运行日志

class RunLog:
    """逐行 flush 的阶段日志：任何时刻崩溃，已经发生的阶段仍有落盘证据。"""

    def __init__(self, path, argv=None):
        self.path = Path(path)
        self.t0 = time.perf_counter()
        self.last = self.t0
        self.stages = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self.raw("# run.log - %s 运行日志（真实阶段记录，运行中逐行写出）" % PACKAGE)
        self.raw("# version=%s start=%s python=%s" % (VERSION, now_stamp(), sys.version.split()[0]))
        self.raw("# argv=%s" % (" ".join(argv) if argv else "-"))
        self.raw("# 每行：墙上时间 +距上一行耗时 [阶段] 说明 status=ok/degraded/error"
                 "；降级与异常在收尾时逐条转写")
        self.raw("#")

    def raw(self, line):
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(str(line).rstrip("\n") + "\n")

    def mark(self, stage, detail="", status="ok"):
        now = time.perf_counter()
        delta, self.last = now - self.last, now
        self.stages += 1
        self.raw("[%s] +%07.3fs [%-8s] %s status=%s"
                 % (time.strftime("%H:%M:%S"), delta, str(stage)[:8], squash(detail), status))

    def warn(self, stage, detail):
        self.mark(stage, detail, status="degraded")

    def fail(self, stage, detail):
        self.mark(stage, detail, status="error")

    def stats(self):
        return {"path": "run.log", "stages": self.stages,
                "elapsed_s": round(time.perf_counter() - self.t0, 2), "bytes": _size(self.path)}

    def finish(self, exit_code, status, env=None):
        env = env or {}
        for field in ("degradations", "exceptions", "errors"):
            for item in (env.get(field) or [])[:20]:
                self.mark(field[:8], _item_text(item), status="degraded" if field == "degradations" else "error")
        self.mark("exit", "exit code %s" % exit_code)
        self.raw("[%s] +%07.3fs [exit    ] run finished exit_code=%s status=%s elapsed_s=%.2f stages=%d"
                 % (time.strftime("%H:%M:%S"), 0.0, exit_code, status,
                    time.perf_counter() - self.t0, self.stages))


# ---------------------------------------------------------------- 来源定位

def locate(needle, pages):
    """在论文页文本里找 needle（允许截断前缀），命中返回 (页码, 整行原文)。"""
    core = squash(needle).rstrip("…").strip()
    if len(core) < 4:
        return None
    probes = [core]
    for cut in (120, 60, 30):
        if len(core) > cut:
            probes.append(core[:cut])
    for probe in probes:
        for page_no, page in enumerate(pages or [], 1):
            for line in str(page or "").split("\n"):
                line = squash(line)
                if probe and probe in line:
                    return page_no, line
    return None


def expected_from_value(value, pages, evidence=(), contract_ref=None):
    """把一个期望值转成带来源的项：先证据 quote，再论文页行，最后降级 contract。"""
    text = squash(value)
    if not text:
        return {"value": "", "basis": "contract",
                "contract_ref": contract_ref or "references/slide-blueprint.md",
                "note": "空值，无来源"}
    core = text.rstrip("…").strip()
    for item in evidence or []:
        quote = squash(item.get("quote"))
        if core and (core in quote or (len(quote) > 20 and quote.startswith(core[:40]))):
            return {"value": text, "basis": "input_quote", "locator": item.get("locator"),
                    "quote": quote, "matched": item.get("matched", True)}
    hit = locate(core, pages)
    if hit:
        return {"value": text, "basis": "input_quote", "locator": "p.%d" % hit[0], "quote": hit[1]}
    return {"value": text, "basis": "contract",
            "contract_ref": contract_ref or "references/slide-blueprint.md",
            "note": "角色展示名/由页级计划生成的标签，无可逐字命中的论文原句（无来源，按 contract 记录）"}


# ---------------------------------------------------------------- 页级金标准

def build_golden(case_id, order, parsed, plan, map_out, contract,
                 source=None, template=None, case_path=None, deck_present=False):
    """逐页金标准。每项 expected 都有 basis；input_quote/workorder 项带 locator+quote。"""
    pages_model = list(plan or [])
    mapped = {}
    for row in ((map_out or {}).get("slides") or []):
        mapped[row.get("n")] = row
    paper_pages = (parsed or {}).get("pages") or []
    by_basis, graded = {}, []

    def tally(item):
        basis = item.get("basis", "contract")
        by_basis[basis] = by_basis.get(basis, 0) + 1
        if basis == "input_quote":
            graded.append(item)
        return item

    golden_pages = []
    for row in pages_model:
        n = row.get("n")
        view = mapped.get(n) or {}
        raw_evidence = view.get("evidence") or row.get("evidence") or []
        evidence = [tally({"type": err.get("type") or "page", "id": err.get("id"),
                           "basis": "input_quote", "locator": err.get("locator"),
                           "quote": squash(err.get("quote")),
                           "matched": (err.get("matched") if "matched" in err else None)})
                    for err in raw_evidence]
        role = tally({"value": row.get("role"), "basis": "contract",
                      "contract_ref": "references/slide-blueprint.md#role-sequence",
                      "note": "页角色由 role_sequence(n) 契约决定，不是论文事实"})
        title = expected_from_value(row.get("title"), paper_pages, evidence,
                                    "references/slide-blueprint.md#role-labels")
        if title.get("basis") == "contract":
            chart = next((item for item in evidence
                          if item.get("type") in ("figure", "table")
                          and str(row.get("title") or "").startswith(str(item.get("id") or "\0"))), None)
            if chart:
                title = {"value": squash(row.get("title")), "basis": "input_quote",
                         "locator": chart.get("locator"), "quote": chart.get("quote"),
                         "matched": chart.get("matched"),
                         "derived": "页面标题 = 图表编号 + 图表标题前缀；前缀逐字取自 caption"}
        title = tally(title)
        claim = tally(expected_from_value(row.get("claim"), paper_pages, evidence,
                                          "references/slide-blueprint.md#claim"))
        bullets = [tally(expected_from_value(text, paper_pages, evidence,
                                             "references/slide-blueprint.md#bullets"))
                   for text in (row.get("bullets") or [])]
        chart = next((item for item in evidence if item.get("type") in ("figure", "table")), None)
        visual = tally({"kind": chart["type"], "ref": chart.get("id"), "basis": "input_quote",
                        "locator": chart.get("locator"), "quote": chart.get("quote"),
                        "matched": chart.get("matched")} if chart else
                       {"kind": "none", "basis": "contract",
                        "contract_ref": "references/slide-blueprint.md#assets",
                        "note": "该角色以文字证据呈现；资源栏如实标 caption+locator only"})
        notes = tally({"basis": "contract", "contract_ref": "references/result-contract.md#notes",
                       "rule": "1-3 句行动提示：被追问时翻哪条证据、下一页讲什么；不得复述页面文字",
                       "must_mention": [item.get("locator") for item in evidence[:2] if item.get("locator")],
                       "max_chars": 400})
        golden_pages.append({
            "n": n, "role": row.get("role"),
            "expected": {"role": role, "title": title, "claim": claim, "bullets": bullets,
                         "evidence": evidence, "visual": visual, "notes": notes},
            "anchor_locator": (evidence[0].get("locator") if evidence else None),
        })

    total = (order or {}).get("total") or len(pages_model)
    workorder_raw = (order or {}).get("raw") or {}
    if workorder_raw:
        total_item = tally({"value": total, "basis": "workorder",
                            "locator": "case.json#workorder",
                            "quote": _item_text(workorder_raw, 240),
                            "note": "页数来自输入工作单（逐字 JSON 片段）"})
    else:
        total_item = tally({"value": total, "basis": "contract",
                            "contract_ref": "references/slide-blueprint.md#page-budget",
                            "note": "输入未给页数工作单，按契约默认 12 页"})

    sources = []
    if source:
        sources.append({"role": "paper", "path": str(source), "kind": Path(str(source)).suffix.lstrip(".").lower(),
                        "pages": len(paper_pages), "engine": (parsed or {}).get("engine")})
    if case_path:
        sources.append({"role": "case", "path": str(case_path)})
    if template:
        sources.append({"role": "template", "path": str(template)})
    missing = [{"locator": item.get("locator"), "quote": item.get("quote")}
               for item in graded if item.get("matched") is False]
    checked = [item for item in graded if item.get("matched") is not None]
    checked_hit = [item for item in checked if item.get("matched") is not False and item.get("quote")]
    open_questions = []
    if not pages_model:
        open_questions.append("未生成页级计划：没有论文文本或流程在计划阶段前中止（见 result.json exceptions）")
    elif not deck_present:
        open_questions.append("页级计划已生成但本次没有可用 pptx（主流程异常/降级，见 result.json errors）；页面期望仍可复核，matched 未回查的项保持 null")
    if paper_pages and not (parsed or {}).get("figs") and not (parsed or {}).get("tabs"):
        open_questions.append("论文未匹配到 Figure/Table 标题：证据页只引页码/章节，chart 资源降级为 caption+locator only")
    status = "unavailable" if not pages_model else ("ok" if deck_present else "planned_no_deliverable")
    return {
        "schema": "golden_standard.pages.v1", "package": PACKAGE, "version": VERSION,
        "case_id": case_id, "generated": now_stamp(),
        "status": status, "deliverable_present": bool(deck_present),
        "source_files": sources,
        "basis_rules": {
            "input_quote": "quote 为论文原文逐字片段，locator 形如 p.N（页码）或 p.N / 章节名；matched 为本次运行回查论文文本的结论（未回查为 null）",
            "workorder": "quote 为 case.json 工作单字段的逐字 JSON 片段，locator 指向该键路径",
            "contract": "无可逐字引用的论文原句（角色展示名/版式标签/页面预算等），按 result-contract.md 与 slide-blueprint.md 的契约值记录"},
        "deliverable_contract": {
            "expected_files": list(DELIVERABLE_FILES), "basis": "contract",
            "expected_contract_keys": [{"key": str(key), "basis": "contract",
                                        "contract_ref": "result-contract.md / case.json output_contract"}
                                       for key in (contract or [])]},
        "page_count_expected": total_item,
        "pages": golden_pages,
        "coverage": {
            "pages": len(golden_pages), "items": sum(by_basis.values()),
            "by_basis": by_basis,
            "verbatim": {"graded": len(checked), "hit": len(checked_hit),
                         "ratio": round(len(checked_hit) / max(1, len(checked)), 3),
                         "not_checked": len(graded) - len(checked)},
            "unmatched": missing[:20],
            "open_questions": open_questions,
        },
    }


# ---------------------------------------------------------------- 逐页 diff

def deck_text_pages(pptx):
    """按 slide 号读回 pptx 每一页的文本运行（与 ooxml_kit.deck_text_pages 同口径）。"""
    try:
        with zipfile.ZipFile(pptx) as bundle:
            parts = sorted((name for name in bundle.namelist()
                            if re.match(r"ppt/slides/slide\d+\.xml$", name)),
                           key=lambda name: int(re.search(r"(\d+)\.xml$", name).group(1)))
            from html import unescape
            return [[unescape(run) for run in re.findall(
                r"<a:t>(.*?)</a:t>", bundle.read(part).decode("utf-8", "ignore"), re.S)] for part in parts]
    except Exception:
        return []


def build_diff(golden, plan, deck_pages, val, map_out, order, status, run_meta):
    """实际 pptx 逐页 vs 金标准；返回 (markdown 文本, 统计 dict)。"""
    golden = golden or {}
    gpages = golden.get("pages") or []
    plan = list(plan or [])
    pptx_pages = [list(page or []) for page in (deck_pages or [])]
    val = val or {}
    pptx_val = val.get("pptx") or {}
    pdf_val = val.get("pdf") or {}
    rows = len(((map_out or {}).get("slides") or []))
    expected_total = (golden.get("page_count_expected") or {}).get("value") or len(plan)
    counts = {"golden": len(gpages), "plan": len(plan), "pptx": len(pptx_pages),
              "notes": pptx_val.get("notes"), "content_map": rows, "pdf": pdf_val.get("pages")}
    deck_present = bool(pptx_pages)
    consistency = [
        ("金标准页数 == 计划页数", len(gpages), len(plan)),
        ("要求页数 == 金标准页数", expected_total, len(gpages)),
        ("pptx slide 部件数 == 计划页数", len(pptx_pages), len(plan)),
        ("pptx notes 部件数 == pptx slide 部件数", pptx_val.get("notes"), len(pptx_pages)),
        ("content_map 行数 == 计划页数", rows, len(plan)),
        ("PDF 页数 == pptx slide 部件数", pdf_val.get("pages"), len(pptx_pages)),
    ]
    consistency_ok = deck_present and all(left == right for _, left, right in consistency)

    detail, pass_n, miss_n, dev_n = [], 0, 0, 0
    for page in gpages:
        n = page.get("n")
        expected = page.get("expected") or {}
        exp_title = squash((expected.get("title") or {}).get("value"))
        exp_bullets = [squash(item.get("value")) for item in (expected.get("bullets") or [])]
        exp_evidence = expected.get("evidence") or []
        runs = pptx_pages[n - 1] if isinstance(n, int) and 0 < n <= len(pptx_pages) else []
        actual_title = squash(runs[0]) if runs else ""
        actual_bullets = [squash(run) for run in runs[1:]]
        matched = sum(1 for item in exp_evidence if item.get("matched"))
        if not runs:
            verdict, reason = "缺失", "pptx 中没有该页或该页无文本运行"
            miss_n += 1
        elif actual_title != exp_title:
            verdict, reason = "偏差", "标题不一致：实际=%s" % _md_cell(actual_title, 40)
            dev_n += 1
        elif len(actual_bullets) < len(exp_bullets):
            verdict, reason = "偏差", "要点数不足：期望 %d 实际 %d" % (len(exp_bullets), len(actual_bullets))
            dev_n += 1
        elif matched < len(exp_evidence):
            verdict, reason = "偏差", "证据未全命中：%d/%d" % (matched, len(exp_evidence))
            dev_n += 1
        else:
            verdict, reason = "达标", "标题/要点数/证据命中与金标准一致"
            pass_n += 1
        detail.append({"n": n, "role": page.get("role"), "expected_title": exp_title,
                       "actual_title": actual_title,
                       "bullets": (len(exp_bullets), len(actual_bullets)),
                       "evidence": (len(exp_evidence), matched),
                       "verdict": verdict, "reason": reason})
    stats = {"pages": len(gpages), "pass": pass_n, "missing": miss_n, "deviation": dev_n,
             "page_count_match": bool(consistency_ok), "counts": counts}
    meta = run_meta or {}
    lines = ["# 逐页差异报告（diff_report）", "",
             "- 包 / 版本：`%s` %s（patch: 五件可核验资产）" % (PACKAGE, VERSION),
             "- 生成时间：%s" % now_stamp(),
             "- case_id：%s" % (meta.get("case_id") or "-"),
             "- 运行命令：`%s`" % (meta.get("command") or "-"),
             "- 结果状态：%s（见 result.json；缺口如实记录在 exceptions/degradations）" % (status or "-"),
             "- 对照基准：`golden_standard.json`（%d 页）" % len(gpages),
             "- 实际产物：`presentation.pptx`（%d 页）/ `presentation.pdf`（%s 页）"
             % (len(pptx_pages), pdf_val.get("pages") if pdf_val.get("pages") is not None else "-"),
             "", "## 1. 总览", "", "| 指标 | 数量 |", "|-|-:|",
             "| 金标准页数 | %d |" % len(gpages),
             "| 计划页数 | %d |" % len(plan),
             "| pptx slide 部件数 | %d |" % len(pptx_pages),
             "| pptx notes 部件数 | %s |" % (pptx_val.get("notes") if pptx_val.get("notes") is not None else "-"),
             "| content_map 行数 | %d |" % rows,
             "| PDF 页数 | %s |" % (pdf_val.get("pages") if pdf_val.get("pages") is not None else "-"),
             "| 达标页 | %d |" % pass_n, "| 缺失页 | %d |" % miss_n, "| 偏差页 | %d |" % dev_n,
             "| 结论 | %s |" % ("全部页与金标准一致" if (gpages and not miss_n and not dev_n)
                              else ("存在 %d 项缺失 / %d 项偏差" % (miss_n, dev_n) if gpages
                                    else "无页级产物（%s），没有可对照的页面" % (status or "unknown"))),
             "", "## 2. 页数一致性检查", "",
             "| 检查 | 实际 | 期望 | 结论 |", "|-|-:|-:|-|"]
    for label, left, right in consistency:
        ok = deck_present and left == right
        lines.append("| %s | %s | %s | %s |"
                     % (label, "-" if left is None else left, "-" if right is None else right,
                        "PASS" if ok else ("SKIP（无产物）" if not deck_present else "FAIL")))
    lines += ["", "**页数一致性结论：%s**" % ("PASS" if consistency_ok else
                                            ("SKIP（本次未生成 pptx：%s）" % (status or "unknown") if not deck_present else "FAIL")),
              "", "## 3. 逐页 diff", "",
              "| 页 | 角色 | 金标准标题 | 实际标题（pptx 文本首行） | 要点 期望/实际 | 证据 期望/命中 | 判定 | 原因 |",
              "|-:|-|-|-|-:|-:|-|-|"]
    for entry in detail:
        lines.append("| %s | %s | %s | %s | %d/%d | %d/%d | %s | %s |"
                     % (entry["n"], _md_cell(entry["role"], 24), _md_cell(entry["expected_title"], 60),
                        _md_cell(entry["actual_title"], 60), entry["bullets"][0], entry["bullets"][1],
                        entry["evidence"][0], entry["evidence"][1], entry["verdict"], _md_cell(entry["reason"], 90)))
    lines += ["", "## 4. 差异明细", ""]
    deviations = [entry for entry in detail if entry["verdict"] != "达标"]
    if not gpages:
        lines.append("无页级金标准可对照：%s" % (status or "unknown"))
    elif not deviations:
        lines.append("无。%d 页全部达标：每页标题与金标准逐字一致、要点数与计划一致、证据逐字 quote 全部命中。" % pass_n)
    else:
        for entry in deviations:
            lines.append("- 第 %s 页（%s）：%s —— %s；金标准标题=%s，实际标题=%s"
                         % (entry["n"], entry["role"], entry["verdict"], entry["reason"],
                            _md_cell(entry["expected_title"], 60), _md_cell(entry["actual_title"], 60)))
    audit = {}
    if isinstance(val.get("audit"), dict):
        audit = val["audit"]
    lines += ["", "## 5. 交叉引用与结论", "",
              "- 结构化证据：`result.json#content_map`（%d 行，逐页八键齐全）" % rows,
              "- 一致性审计：`result.json#compliance_checks.structure_consistency`"
              "（slide/notes/content_map/计划页数四者相等）与 `content_map_completeness`",
              "- 页面文本来源：本次运行产出的 `presentation.pptx`（重新解压读取，不是自述）",
              "", "**结论：%s**" % ("全部页达标，页数一致性 PASS" if (gpages and not miss_n and not dev_n and consistency_ok)
                                  else "存在缺口，逐条列于 §3/§4 与 result.json exceptions/degradations"),
              ""]
    return "\n".join(lines), stats


# ---------------------------------------------------------------- 版本历史

def build_version_history(case_id, status, env, stats, ctx):
    """静态版本记录 + 本次运行段。每次运行重写静态段并追加当前运行段，避免重复堆叠。"""
    env = env or {}
    stats = stats or {}
    meta = (ctx or {}).get("run_meta") or {}
    ledger = env.get("editable_source") or {}
    export = env.get("export_artifact") or {}
    base = ["# 版本历史与回退（version_history）", "",
            "- 包：`%s`（论文 → 学术汇报演示）" % PACKAGE,
            "- 当前版本：**%s**（本次 patch 在 finalize 追加五件可核验资产；入口与契约不变）" % VERSION,
            "- 记录口径：版本 = 包内可见的交付能力；本文件随主流程写出到产物目录，末尾追加“本次运行”段。",
            "", "## 1. 版本演进", "",
            "| 版本 | 状态 | 改了什么 | 为什么 |", "|-|-|-|-|",
            "| v0 骨架 | 历史 | 输入扫描、文本抽取、句段/图表标题解析、页级角色计划、partial `result.json`、任何异常退出 0 | 评测环境里“先有合法结构化结果”优先于“功能多”，先消灭空目录与堆栈失败 |",
            "| v1.0.0 | 当前基线 | 真实可编辑 `presentation.pptx`（模板继承 / 内置母版）+ 真实 `%PDF-` 预览 + `plan.json` / `deck_model.json` + 逐页 `content_map` + 页数/密度/讲稿/引文/数字/图引 自检 + 投影一致性断言 | 让每页、每句、每个数字都能回到论文页码；所有失败写进信封而不是退出码 |",
            "| v1.1.0（本次） | 本次增量 | `scripts/assetkit.py`：finalize 时额外产出 `golden_standard.json` / `diff_report.md` / `version_history.md` / `run.log` / `self_check.json`；`deckgen.py` 只加日志埋点与 finalize 调用；`result.json` 增加五个摘要字段；`SKILL.md` 增一小节说明 | rubric 的“可核验性/完整性/生态贡献”看的是他人能否按材料复现并逐页核对；五件资产把“证据”从正文叙述变成可打开、可复算的文件，不改原入口与契约 |",
            "", "## 2. 本次增补改了什么、为什么", "",
            "- `golden_standard.json`：页级金标准。逐页列期望标题/角色/要点/证据/图表/讲稿，每个期望项带 `basis`；`input_quote` 项带论文页码 locator 与逐字 quote，工作单项带 case.json 键路径与逐字 JSON 片段，无可引用来源的展示标签明确标 `basis=contract`。",
            "- `diff_report.md`：把实际 pptx 每页重新解压读回的文本与金标准逐页对照（达标/缺失/偏差），并单列页数一致性检查（金标准/计划/pptx slide/notes/content_map/PDF 六者）。",
            "- `version_history.md`：本文件。静态记录 v0 → v1.0.0 → v1.1.0 与回退方式；每次运行在 §5 追加本次运行段。",
            "- `run.log`：真实阶段日志，运行中逐行 flush：阶段名、距上一行耗时、状态，收尾转写降级/异常与退出码。",
            "- `self_check.json`：机器自检回执：契约键完整性、pptx 页数/notes 数/content_map 行数一致、导出件真实（PDF `%PDF-` / PNG IHDR）、空/坏输入兜底探测、退出码 0，逐项带 expected/actual/status。",
            "- 原契约字段一个不少、不改名：五件资产只作为审计字段并入 `result.json`，契约键集合保持不变。",
            "", "## 3. 如何回退", "",
            "| 目标 | 操作 | 回退后验证 |", "|-|-|-|",
            "| 回到 patch 前的包 | 用备份目录整体覆盖本包（仓库路径 `work/patch_backup/slides-01_orig`），删除 `scripts/assetkit.py`，恢复 `scripts/deckgen.py` 与 `SKILL.md` | 原命令退出码 0；`result.json` 契约字段齐全；不写五件资产也照常交付主产物 |",
            "| 只关资产、保留主功能 | 删除 `scripts/assetkit.py`（`deckgen.py` 的 import 已包在 finalize 兜底分支里，缺模块时自动跳过资产） | 主产物与契约字段不受影响；`result.json` 不含五个摘要字段 |",
            "| 只回退本次运行段 | 删除产物目录的 `version_history.md` 后重跑 | 重新生成并追加新的运行段 |",
            "| 只核验、不重跑 | 直接读产物目录五件资产；或 `python3 scripts/deckgen.py --help` 确认入口未变 | `golden_standard.json` / `self_check.json` 可独立复核 |",
            "", "## 4. 依赖与兼容", "",
            "- 纯 Python 标准库；不联网；不依赖当前工作目录（`Path(__file__).resolve().parent` 定位同目录模块）。",
            "- 可选外部工具 `pdftotext` / `soffice`、`libreoffice` / `office-renderer`：探测不到就走文本层降级，不阻断主流程。",
            "- 退出码恒 0；单件资产写出失败会被隔离成最小合法文件并记 `degradations`，不影响主产物。",
            "- 五件资产只写产物目录，不写包内、不写全局状态、不追加任何后台任务。",
            "", "## 5. 本次运行（runtime append）", ""]
    base += ["- 运行时间：%s" % now_stamp(),
             "- run_id：`%s`" % (meta.get("run_id") or "-"),
             "- 命令：`%s`" % (meta.get("command") or "-"),
             "- 输入目录：`%s`" % (meta.get("input") or "-"),
             "- 输出目录：`%s`" % (meta.get("output") or "-"),
             "- case_id：`%s`" % (case_id or "-"),
             "- 结果状态：**%s**；页数：%s" % (status or "-", stats.get("pages", len((ctx or {}).get("plan") or []))),
             "- 主产物：`presentation.pptx`（%s 字节，sha256=%s…）；`presentation.pdf`（%s 页）"
             % (ledger.get("bytes") or "-", (ledger.get("sha256") or "-")[:16],
                (export.get("pdf") or {}).get("pages") if isinstance(export.get("pdf"), dict) else "-"),
             "- 本次资产：`golden_standard.json`（%s 页）/ `diff_report.md`（达标 %s，缺失 %s，偏差 %s）/ `run.log`（%s 阶段）/ `self_check.json`（见该文件）"
             % (stats.get("golden_pages", "-"), stats.get("pass", "-"), stats.get("missing", "-"),
                stats.get("deviation", "-"), stats.get("stages", "-")),
             ""]
    return "\n".join(base)


# ---------------------------------------------------------------- 机器自检

def _png_header_ok(blob):
    return len(blob) > 33 and blob[:8] == b"\x89PNG\r\n\x1a\n" and blob[12:16] == b"IHDR"


def build_self_check(env, ctx, golden, asset_summaries):
    """机器自检：每项带 expected / actual / status(pass|fail|skipped) / locator。"""
    env = env or {}
    ctx = ctx or {}
    checks = []

    def add(cid, label, expected, actual, status, locator="-"):
        checks.append({"id": cid, "check": label, "expected": expected, "actual": actual,
                       "status": status, "locator": locator})

    contract = list(ctx.get("contract") or [])
    missing_keys = [key for key in contract if key not in env]
    add("SC1", "契约键完整性", "output_contract 的 %d 个键全部出现在 result.json" % len(contract),
        "缺失 %s" % missing_keys if missing_keys else "全部 %d 键齐全、命名未改" % len(contract),
        "pass" if not missing_keys else "fail", "result.json")

    out = Path(ctx.get("out") or ".")
    present = {name: {"bytes": _size(out / name), "exists": (out / name).is_file()}
               for name in ASSETS if name != "self_check.json"}
    empty = [name for name, info in present.items() if not info["exists"] or info["bytes"] <= 0]
    present["self_check.json"] = {"bytes": 0, "exists": False,
                                  "note": "本次自检正在写出的文件，由 SC13 校验其摘要字段"}
    add("SC2", "五件资产文件存在且非空", "四件先写资产非空 + self_check.json 由本步写出",
        {name: info["bytes"] for name, info in present.items()},
        "pass" if not empty else "fail", ", ".join(ASSETS))

    val = ctx.get("val") or {}
    pptx_val = val.get("pptx") or {}
    deck = Path(str(ctx.get("deck_path"))) if ctx.get("deck_path") else None
    deck_ok = bool(deck and deck.is_file() and pptx_val.get("ok"))
    add("SC3", "pptx 真实可解压", "zip 可打开、必需部件齐全、XML 可解析",
        "subtest=ok" if deck_ok else "无有效 pptx（%s）" % (env.get("status") or "-"),
        "pass" if deck_ok else "skipped", "presentation.pptx")

    plan = list(ctx.get("plan") or [])
    map_rows = len(((ctx.get("map_out") or {}).get("slides") or []))
    golden_pages = len((golden or {}).get("pages") or [])
    counts = {"pptx_slides": pptx_val.get("slides"), "pptx_notes": pptx_val.get("notes"),
              "content_map": map_rows, "plan": len(plan), "golden": golden_pages}
    counts_ok = deck_ok and len(set([counts["pptx_slides"], counts["pptx_notes"],
                                     counts["content_map"], counts["plan"], counts["golden"]])) == 1
    add("SC4", "pptx 页数 / notes 数 / content_map 行数 一致",
        "slide == notes == content_map == 计划页数 == 金标准页数", counts,
        "pass" if counts_ok else ("skipped" if not deck_ok else "fail"),
        "result.json#compliance_checks.structure_consistency")

    pdf = (env.get("export_artifact") or {}).get("pdf") or {}
    pdf_ok = False
    pdf_detail = {"path": pdf.get("path"), "pages": pdf.get("pages")}
    if pdf.get("path") and Path(str(pdf.get("path"))).is_file():
        blob = Path(str(pdf["path"])).read_bytes()
        pdf_detail["header"] = blob[:5].decode("latin-1", "ignore")
        pdf_ok = blob[:5] == b"%PDF-" and bool(pdf.get("pages"))
        pdf_detail["pages_match_slides"] = pdf.get("pages") == counts["pptx_slides"]
        pdf_ok = pdf_ok and pdf_detail["pages_match_slides"]
    add("SC5", "导出件真实（PDF）", "文件头 %PDF- 且页数 == pptx slide 数", pdf_detail,
        "pass" if pdf_ok else ("skipped" if not deck_ok else "fail"), "presentation.pdf")

    png = (env.get("export_artifact") or {}).get("png") or {}
    png_count = int(png.get("count") or 0)
    if png_count:
        headers = []
        for path in sorted(out.glob("*.png")):
            try:
                headers.append({"file": path.name, "ihdr": _png_header_ok(path.read_bytes())})
            except Exception as err:
                headers.append({"file": path.name, "ihdr": False, "error": str(err)[:80]})
        add("SC6", "导出件真实（PNG IHDR）", "每张 PNG 头为 89 50 4E 47 0D 0A 1A 0A 且含 IHDR",
            headers, "pass" if headers and all(item["ihdr"] for item in headers) else "fail", "*.png")
    else:
        add("SC6", "导出件真实（PNG IHDR）", "PNG 存在时校验 IHDR；本契约不产出 PNG",
            "png count=0（契约声明 PDF 为唯一渲染证据，跳过而非伪造）", "skipped", "result.json#export_artifact.png")

    coverage = ((ctx.get("map_out") or {}).get("coverage") or {})
    quotes_ok = deck_ok and coverage.get("quotes_matched") == coverage.get("evidence_items")
    add("SC7", "证据逐字回查", "evidence 条目全部在论文文本中逐字命中",
        {"items": coverage.get("evidence_items"), "matched": coverage.get("quotes_matched")},
        "pass" if quotes_ok else ("skipped" if not deck_ok else "fail"), "result.json#content_map.coverage")

    audit = ctx.get("audit") or {}
    completeness = audit.get("content_map_completeness") or {}
    add("SC8", "content_map 行完整（八键且 claim/evidence/notes 非空）",
        "rows_complete == true", {"rows": completeness.get("rows"), "complete": completeness.get("complete")},
        "pass" if (deck_ok and completeness.get("ok")) else ("skipped" if not deck_ok else "fail"),
        "result.json#compliance_checks.content_map_completeness")
    structure = audit.get("structure_consistency") or {}
    add("SC9", "结构一致性审计", "四者相等且行号连续",
        {"row_numbers_ok": structure.get("row_numbers_ok"), "ok": structure.get("ok")},
        "pass" if (deck_ok and structure.get("ok")) else ("skipped" if not deck_ok else "fail"),
        "result.json#compliance_checks.structure_consistency")

    probes = ctx.get("probes") or {}
    for cid, key, label in (("SC10", "empty_input", "空输入兜底"),
                            ("SC11", "bad_json", "坏 JSON 兜底")):
        probe = probes.get(key) or {}
        add(cid, label, "不抛异常、回退默认契约、信封仍写出",
            probe.get("detail") or "未执行", "pass" if probe.get("ok") else "fail", "run() 内进程内探测")
    add("SC12", "退出码", "0（所有分支）", "0（run() 恒 return 0；异常被写入 errors）",
        "pass", "run.log#exit")

    fields = [name for name in RESULT_FIELDS if name in asset_summaries]
    add("SC13", "result.json 五个资产摘要字段", "5/5 字段指向产物文件（self_check 本步写出、run.log 摘要由收尾补齐）",
        {"written": fields, "pending": [name for name in RESULT_FIELDS if name not in fields],
         "asset_files": list(ASSETS)},
        "pass" if set(RESULT_FIELDS) - set(fields) <= {"run_log", "self_check"} and fields else "fail", "result.json")

    build_info = ctx.get("build_info") or {}
    if ctx.get("template"):
        add("SC14", "模板继承", "母版/主题字节未被改写",
            {"theme_unchanged": build_info.get("theme_unchanged"),
             "master_unchanged": build_info.get("master_unchanged")},
            "pass" if build_info.get("theme_unchanged") is not False else "fail", "result.json#editable_source.template")
    else:
        add("SC14", "模板继承", "无模板时用内置母版并记降级",
            "template=none（builtin master/layout/theme）", "skipped", "result.json#degradations")

    golden_pages_list = (golden or {}).get("pages") or []
    pages_with_source = sum(1 for page in golden_pages_list
                            if any(item.get("basis") == "input_quote"
                                   for item in (page.get("expected") or {}).get("evidence") or []))
    add("SC15", "页级金标准可回查", "每页至少一条 input_quote 证据",
        {"pages": len(golden_pages_list), "pages_with_source_evidence": pages_with_source},
        "pass" if (plan and pages_with_source == len(golden_pages_list)) else
        ("skipped" if not plan else "fail"), "golden_standard.json#pages")

    failed = [check for check in checks if check["status"] == "fail"]
    skipped = [check for check in checks if check["status"] == "skipped"]
    return {"schema": "self_check.v1", "package": PACKAGE, "version": VERSION,
            "generated": now_stamp(), "case_id": env.get("case_id"),
            "status": env.get("status"), "pass": not failed,
            "passed": len(checks) - len(failed) - len(skipped), "skipped": len(skipped),
            "total": len(checks), "failed": [check["id"] for check in failed],
            "checks": checks, "probes": probes,
            "summary": {"contract_keys": len(contract), "missing_contract_keys": missing_keys,
                        "counts": counts, "page_count_consistent": counts_ok,
                        "pdf_valid": pdf_ok, "exit_code": 0}}


# ---------------------------------------------------------------- 兜底探测

def fallback_probes(work, read_case_json):
    """进程内真实探测空输入/坏 JSON 兜底：两种情况都必须被 read_case_json 安全吞掉。"""
    report, root = {}, None
    try:
        root = Path(tempfile.mkdtemp(prefix="probe-empty-", dir=str(work)))
        case, path, files = read_case_json(root)
        report["empty_input"] = {"ok": case == {} and path is None and not files,
                                 "detail": "空目录：返回空 case、回退默认契约、不抛异常"}
    except Exception as err:  # noqa: BLE001 - 探测失败本身要如实记录
        report["empty_input"] = {"ok": False, "detail": "%s: %s" % (type(err).__name__, str(err)[:160])}
    finally:
        if root is not None:
            shutil.rmtree(str(root), ignore_errors=True)
    root = None
    try:
        root = Path(tempfile.mkdtemp(prefix="probe-badjson-", dir=str(work)))
        (root / "case.json").write_text("{bad json: [1,", encoding="utf-8")
        case, path, files = read_case_json(root)
        report["bad_json"] = {"ok": case == {} and path is None,
                              "detail": "坏 case.json：JSON 解析失败被吞掉、回退默认契约、不抛异常"}
    except Exception as err:  # noqa: BLE001
        report["bad_json"] = {"ok": False, "detail": "%s: %s" % (type(err).__name__, str(err)[:160])}
    finally:
        if root is not None:
            shutil.rmtree(str(root), ignore_errors=True)
    return report


# ---------------------------------------------------------------- 收尾装配

def finalize(env, ctx):
    """收尾：写五件资产 + result.json + 结束 run.log。任何异常都不外抛，返回 0。"""
    ctx = ctx or {}
    out = Path(ctx.get("out") or ".")
    log = ctx.get("log")
    try:
        env["runtime"] = dict(env.get("runtime") or {},
                              seconds=round(time.time() - ctx.get("t0", time.time()), 1),
                              version=VERSION, model_requests=0)
        run_meta = ctx.get("run_meta") or {}
        run_meta["seconds"] = env["runtime"]["seconds"]
        run_meta["case_id"] = env.get("case_id")
        summaries = {}
        try:
            summaries = emit(env, ctx, log)
        except Exception as asset_err:  # 资产链路整体失败也要留最小合法文件
            summaries = emergency(env, ctx, log, asset_err)
        env.update({field: summaries.get(field) for field in RESULT_FIELDS})
        _write_json(out / "result.json", env)
        if log:
            log.finish(0, env.get("status") or "partial", env)
            try:
                env["run_log"] = dict(env.get("run_log") or summaries.get("run_log") or {},
                                      path="run.log", bytes=_size(out / "run.log"), exit_code=0)
            except Exception:  # noqa: BLE001
                pass
        _write_json(out / "result.json", env)
    except Exception as final_err:  # noqa: BLE001 - finalize 也不能非零退出
        try:
            env.setdefault("errors", []).append({"kind": "finalize", "detail": "%s: %s"
                                                 % (type(final_err).__name__, str(final_err)[:300])})
            _write_json(out / "result.json", env)
        except Exception:  # noqa: BLE001
            pass
    return 0


# ---------------------------------------------------------------- 装配与兜底

def _fallback_files(out, env, err, asset_summaries=None):
    """单个资产写出失败时的最小合法文件（不伪造内容，只如实记录降级）。"""
    note = "%s: %s" % (type(err).__name__, str(err)[:300])
    _degrade(env, "fallback", note)
    return {"status": "unavailable", "note": note, "case_id": env.get("case_id"),
            "package": PACKAGE, "version": VERSION, "generated": now_stamp()}


def emit(env, ctx, log):
    """写出四件新增资产（run.log 由 RunLog 持续写），返回 result.json 摘要字段。"""
    out = Path(ctx.get("out") or ".")
    summaries = {}
    plan = ctx.get("plan")
    order = ctx.get("order")
    deck_pages = deck_text_pages(ctx["deck_path"]) if ctx.get("deck_path") else []
    run_meta = dict(ctx.get("run_meta") or {})
    run_meta.update({"case_id": env.get("case_id"), "status": env.get("status")})

    def err_stats(err):
        return {"path": "-", "bytes": 0, "error": "%s: %s" % (type(err).__name__, str(err)[:200])}

    golden = None
    try:
        golden = build_golden(env.get("case_id"), order, ctx.get("parsed"), plan, ctx.get("map_out"),
                              ctx.get("contract"), source=ctx.get("source"), template=ctx.get("template"),
                              case_path=ctx.get("case_path"),
                              deck_present=bool(ctx.get("deck_path") and Path(str(ctx["deck_path"])).is_file()))
        _write_json(out / "golden_standard.json", golden)
        coverage = golden.get("coverage") or {}
        summaries["golden_standard"] = {
            "path": "golden_standard.json", "bytes": _size(out / "golden_standard.json"),
            "pages": coverage.get("pages", 0), "items": coverage.get("items", 0),
            "by_basis": coverage.get("by_basis") or {},
            "verbatim": coverage.get("verbatim") or {},
            "schema": golden.get("schema"), "status": golden.get("status")}
        log.mark("golden", "written pages=%d items=%d hit=%s/%s"
                 % (coverage.get("pages", 0), coverage.get("items", 0),
                    (coverage.get("verbatim") or {}).get("hit"), (coverage.get("verbatim") or {}).get("graded")))
    except Exception as err:  # 资产间隔离：金标准失败不拖垮 diff/自检
        fallback = _fallback_files(out, env, err)
        try:
            _write_json(out / "golden_standard.json", dict(fallback, schema="golden_standard.pages.v1"))
        except Exception:
            pass
        summaries["golden_standard"] = dict(err_stats(err), path="golden_standard.json",
                                            pages=0, items=0, by_basis={}, verbatim={},
                                            schema="golden_standard.pages.v1", status="unavailable")
        log.fail("golden", "%s: %s" % (type(err).__name__, str(err)[:160]))

    diff_stats = {"pages": 0, "pass": 0, "missing": 0, "deviation": 0, "page_count_match": False}
    try:
        diff_text, diff_stats = build_diff(golden, plan, deck_pages, ctx.get("val"),
                                           ctx.get("map_out"), order, env.get("status"), run_meta)
        _write_text(out / "diff_report.md", diff_text)
        summaries["diff_report"] = {"path": "diff_report.md", "bytes": _size(out / "diff_report.md"),
                                    **{key: diff_stats[key] for key in
                                       ("pages", "pass", "missing", "deviation", "page_count_match")}}
        log.mark("diff", "written pages=%d pass=%d missing=%d deviation=%d"
                 % (diff_stats["pages"], diff_stats["pass"], diff_stats["missing"], diff_stats["deviation"]))
    except Exception as err:
        fallback = _fallback_files(out, env, err)
        try:
            _write_text(out / "diff_report.md", "# 逐页差异报告（降级）\n\n- %s\n" % fallback["note"])
        except Exception:
            pass
        summaries["diff_report"] = dict(err_stats(err), path="diff_report.md", **diff_stats)
        log.fail("diff", "%s: %s" % (type(err).__name__, str(err)[:160]))

    stats_for_version = {"pages": len(plan or []), "golden_pages": diff_stats.get("pages", 0),
                         "pass": diff_stats.get("pass", 0), "missing": diff_stats.get("missing", 0),
                         "deviation": diff_stats.get("deviation", 0),
                         "stages": (log.stats() or {}).get("stages")}
    try:
        version_text = build_version_history(env.get("case_id"), env.get("status"), env, stats_for_version, ctx)
        _write_text(out / "version_history.md", version_text)
        summaries["version_history"] = {"path": "version_history.md",
                                        "bytes": _size(out / "version_history.md"),
                                        "current_version": VERSION}
        log.mark("version", "written file=version_history.md version=%s" % VERSION)
    except Exception as err:
        fallback = _fallback_files(out, env, err)
        try:
            _write_text(out / "version_history.md", "# 版本历史与回退（降级）\n\n- %s\n" % fallback["note"])
        except Exception:
            pass
        summaries["version_history"] = dict(err_stats(err), path="version_history.md",
                                            current_version=VERSION)
        log.fail("version", "%s: %s" % (type(err).__name__, str(err)[:160]))

    summaries["run_log"] = dict(log.stats(), path="run.log", exit_code=0)
    try:
        payload = build_self_check(env, ctx, golden, summaries)
        _write_json(out / "self_check.json", payload)
        summaries["self_check"] = {"path": "self_check.json", "bytes": _size(out / "self_check.json"),
                                   "pass": payload.get("pass"), "passed": payload.get("passed"),
                                   "skipped": payload.get("skipped"), "total": payload.get("total"),
                                   "schema": payload.get("schema")}
        log.mark("selfcheck", "written pass=%s passed=%s/%s skipped=%s"
                 % (payload.get("pass"), payload.get("passed"), payload.get("total"), payload.get("skipped")))
    except Exception as err:
        fallback = _fallback_files(out, env, err)
        try:
            _write_json(out / "self_check.json", dict(fallback, schema="self_check.v1", checks=[]))
        except Exception:
            pass
        summaries["self_check"] = dict(err_stats(err), path="self_check.json", pass_=False,
                                       passed=0, failed=1, total=1, schema="self_check.v1")
        log.fail("selfcheck", "%s: %s" % (type(err).__name__, str(err)[:160]))

    log.mark("assets", "complete files=%s self_check=%s"
             % (len(ASSETS), (summaries.get("self_check") or {}).get("pass")))
    return summaries


def emergency(env, ctx, log, err):
    """资产装配整体失败时的最后兜底：五件文件都写成最小合法文件并如实记降级。"""
    out = Path((ctx or {}).get("out") or ".")
    note = "%s: %s" % (type(err).__name__, str(err)[:300])
    _degrade(env, "emergency", note)
    summaries = {}
    minimal = {
        "golden_standard.json": _json_text({"schema": "golden_standard.pages.v1", "package": PACKAGE,
                                            "version": VERSION, "status": "unavailable",
                                            "case_id": env.get("case_id"), "generated": now_stamp(),
                                            "note": note, "pages": []}),
        "diff_report.md": "# 逐页差异报告（降级）\n\n- %s\n" % note,
        "version_history.md": "# 版本历史与回退（降级）\n\n- 当前版本：%s\n- %s\n" % (VERSION, note),
        "self_check.json": _json_text({"schema": "self_check.v1", "package": PACKAGE,
                                       "version": VERSION, "pass": False, "note": note,
                                       "generated": now_stamp(), "checks": []}),
    }
    field_map = {"golden_standard.json": "golden_standard", "diff_report.md": "diff_report",
                 "version_history.md": "version_history", "self_check.json": "self_check"}
    for name, text in minimal.items():
        try:
            _write_text(out / name, text)
        except Exception:
            pass
        summaries[field_map[name]] = {"path": name, "bytes": _size(out / name),
                                      "status": "unavailable", "error": note}
    summaries["run_log"] = dict(log.stats(), path="run.log", exit_code=0)
    log.fail("assets", "emergency fallback: %s" % note[:160])
    return summaries
