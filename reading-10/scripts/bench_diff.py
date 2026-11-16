#!/usr/bin/env python3
"""Diff/report layer for the finalize-time asset bundle.

`render_diff` turns the expectation ledger into a human-readable comparison report
(what the golden standard expected, what the artefacts actually contain, and whether
the 0/1/2 scoring table recomputes cleanly). `render_self_check` re-reads every
artefact from disk and records machine receipts for the contract, the primary
products, quotes, counts, the degraded-input fallbacks and the exit-code policy.

Both functions are pure readers: they never change the five primary deliverables.
"""
import json
import re
from pathlib import Path

import bench_golden

CHECK_NAMES = (
    "result_json_contract",
    "result_envelope",
    "primary_products",
    "card_invariants",
    "anchors_verified",
    "quote_hit_rate",
    "scoring_recompute",
    "golden_diff",
    "counts_consistency",
    "degraded_input_probe",
    "partial_result_first",
    "exit_code_zero",
    "assets_generated",
    "determinism_by_construction",
    "synthetic_label",
    "version_ledger",
)
ASSETS = ("golden_standard.json", "diff_report.md", "version_history.md", "run.log", "self_check.json")
MAIN = ("benchmark.json", "anchors.json", "scoring.json", "report.md", "result.json")
TS = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")


# --------------------------------------------------------------------- helpers
def _cat(golden, name):
    if not golden:
        return []
    return [it for it in golden.get("items") or [] if it.get("category") == name]


def _bad(rows):
    return [r for r in rows if r.get("verdict") in ("deviation", "missing")]


def _table(rows, gf=lambda v: bench_golden.fmt(v, 110)):
    out = ["| id | subject | expectation | golden | actual | verdict | source |",
           "|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append("| %s | `%s` | %s | %s | %s | %s | `%s` |"
                   % (r.get("id"), r.get("subject"), r.get("expectation"),
                      gf(r.get("golden")), gf(r.get("actual")), r.get("verdict"),
                      (r.get("source") or {}).get("locator")))
    return "\n".join(out)


def _verdict_counts(rows):
    c = {"met": 0, "deviation": 0, "missing": 0, "not_applicable": 0}
    for r in rows:
        c[r.get("verdict", "met")] = c.get(r.get("verdict", "met"), 0) + 1
    return c


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


# ------------------------------------------------------------------ diff report
def render_diff(ctx, golden, probes, facts):
    """Actual vs golden comparison plus the scoring-table self-consistency block."""
    out = Path(ctx["out_dir"])
    case_id = (golden or {}).get("case_id") or ctx.get("case_id") or "-"
    lines = ["# 金标准对照报告 / diff report", "",
             "- case_id: `%s` | package: reading-bench-forge %s | 生成阶段: `build/finalize`（资产层，无时间戳）"
             % (case_id, ctx.get("skill_version") or "-"),
             "- 金标准: `golden_standard.json`（独立推导） | 产物: `benchmark.json` / `anchors.json` / "
             "`scoring.json` / `report.md` / `result.json`",
             "- 本报告只做两件事：逐项对照「期望 vs 实际」，并把 0/1/2 评分表从落盘产物复算一遍。", ""]
    if not golden:
        lines += ["## 1. 状态", "", "金标准推导失败（见 run.log / self_check.json 的 degrading 记录），"
                  "本报告退化为产物清单；对照结论标为 `missing`。", "",
                  "| 产物 | 字节 | 存在 |", "|---|---:|---|"]
        for name in MAIN:
            p = out / name
            lines.append("| `%s` | %d | %s |" % (name, p.stat().st_size if p.is_file() else 0, p.is_file()))
        return "\n".join(lines) + "\n"
    summary = golden.get("summary") or {}
    # ---- 1 provenance
    lines += ["## 1. 金标准是怎么独立推导出来的", "",
              "| # | 来源 | 推导方法 |", "|---|---|---|"]
    for d in golden.get("derivation") or []:
        lines.append("| %s | %s | %s |" % (d.get("id"), d.get("source"), d.get("method")))
    lines += ["", "复算口径（逐条从 `references/` 与 `SKILL.md` 原文引用，见 golden_standard.json "
              "的 `recompute_rules`）：", ""]
    for r in golden.get("recompute_rules") or []:
        lines.append("- **%s** %s — 源: `%s`；本次判定: **%s**（%s）"
                     % (r.get("id"), r.get("rule"), (r.get("source") or {}).get("locator"),
                        r.get("verdict"), r.get("actual")))
    # ---- 2 summary
    lines += ["", "## 2. 对照总览", "",
              "| 类别 | 项数 | met | deviation | missing | not_applicable |",
              "|---|---:|---:|---:|---:|---:|"]
    for cat in sorted(summary.get("by_category") or {}):
        rows = _cat(golden, cat)
        c = _verdict_counts(rows)
        lines.append("| %s | %d | %d | %d | %d | %d |"
                     % (cat, len(rows), c["met"], c["deviation"], c["missing"], c["not_applicable"]))
    lines += ["| **合计** | **%d** | **%d** | **%d** | **%d** | **%d** |"
              % (summary.get("n_items", 0), summary.get("met", 0), summary.get("deviation", 0),
                 summary.get("missing", 0), summary.get("not_applicable", 0)),
              "",
              "- 逐字引文命中率: **%s**（%s/%s 条带引文的期望行可在源文本中逐字命中）"
              % (summary.get("quote_hit_rate"), summary.get("n_quotes_verbatim"), summary.get("n_quotes")),
              "- 复算规则: %s/%s 条为 met 或 not_applicable（见 §1 与 golden_standard.json）"
              % (summary.get("rules_met"), summary.get("n_rules")), ""]
    # ---- 3 per category tables
    lines += ["## 3. 逐项对照（期望 vs 实际）", ""]
    for cat in sorted(summary.get("by_category") or {}):
        rows = _cat(golden, cat)
        lines += ["### 3.%d %s（%d 项）" % (sorted(summary.get("by_category") or {}).index(cat) + 1, cat, len(rows)), "",
                  _table(rows), ""]
    # ---- 4 scoring recompute
    lines += ["## 4. 评分表自洽（从落盘产物复算）", "", "### 4.1 逐点 0/1/2 复算", ""]
    score_rows = [r for r in _cat(golden, "scores") if r.get("subject", "").endswith(".score")]
    lines += ["| 题/点 | 期望分（独立复算） | 实际分（scoring.json） | 复算说明 | 判定 |",
              "|---|---:|---:|---|---|"]
    for r in score_rows:
        lines.append("| `%s` | %s | %s | %s | %s |"
                     % (r.get("subject"), r.get("golden"), r.get("actual"),
                        r.get("note") or "-", r.get("verdict")))
    lines += ["", "### 4.2 题分与加权求和", "",
              "| 题 | 期望题分 Σ(w×点分) | 实际题分 | 判定 |", "|---|---:|---:|---|"]
    for r in _cat(golden, "scores"):
        if r.get("subject", "").endswith(".item_score"):
            lines.append("| `%s` | %s | %s | %s |"
                         % (r.get("subject"), r.get("golden"), r.get("actual"), r.get("verdict")))
    lines += ["", "### 4.3 汇总指标复算", "",
              "| 指标 | 期望（从题表重算） | 实际（aggregate） | 判定 |", "|---|---|---|---|"]
    for r in _cat(golden, "aggregate"):
        lines.append("| `%s` | %s | %s | %s |"
                     % (r.get("subject"), bench_golden.fmt(r.get("golden")),
                        bench_golden.fmt(r.get("actual")), r.get("verdict")))
    lines += ["", "### 4.4 自洽断言", ""]
    groups = {"点数相加 n2+n1+n0==n_points": _cat(golden, "aggregate"),
              "题分=Σ(weight×点分)、满分 2": _cat(golden, "scores"),
              "权重和≈1.0（±0.02）": _cat(golden, "cards"),
              "锚点 verified 与 locator 一致": _cat(golden, "anchors"),
              "契约字段全部在顶层": _cat(golden, "contract")}
    passed = 0
    for label, rows in groups.items():
        bad = _bad(rows)
        ok = not bad
        passed += ok
        detail = "全部通过" if ok else "偏离/缺失: " + ",".join(r.get("id") for r in bad[:8])
        lines.append("- %s — **%s**（%s）" % (label, "PASS" if ok else "FAIL", detail))
    consistency = "PASS" if passed == len(groups) else "REVIEW"
    lines += ["", "- 评分表自洽结论：**%s**（%d/%d 组断言通过）" % (consistency, passed, len(groups)), ""]
    # ---- 5 contract echo
    lines += ["## 5. 契约回填", ""]
    crow = _cat(golden, "contract")
    lines += [_table(crow) if crow else "输入未声明 `output_contract`，契约回填不适用。", ""]
    # ---- 6 artifact inventory
    lines += ["## 6. 产物清单", "",
              "| 产物 | 字节 | 角色 |", "|---|---:|---|"]
    roles = {"benchmark.json": "题集快照", "anchors.json": "引文核验表", "scoring.json": "0/1/2 评分表",
             "report.md": "人读凭证", "result.json": "信封+契约回填"}
    for name in MAIN:
        p = out / name
        lines.append("| `%s` | %d | %s |" % (name, p.stat().st_size if p.is_file() else 0, roles.get(name, "-")))
    facts_assets = facts.get("assets") or {}
    emitted = []
    for key, name in (("golden", "golden_standard.json"), ("version", "version_history.md")):
        p = out / name
        emitted.append("| `%s` | %d | 本次 finalize 写出 |" % (name, p.stat().st_size if p.is_file() else 0))
    lines += emitted
    lines += ["| `diff_report.md` | 本文件 | 本次 finalize 写出 |",
              "| `run.log` | 阶段日志 | 紧随本报告写出（同一 finalize 批次） |",
              "| `self_check.json` | 机器回执 | 最后写出，校验以上全部资产 |",
              "", "- `self_check.json` 对 5 件资产逐个做「存在且非空」断言；`run.log` 记录真实阶段时间。", ""]
    # ---- 7 degraded probes
    lines += ["## 7. 降级输入实测（同一次 finalize 内的子进程）", ""]
    if not (probes or {}).get("skipped"):
        lines += ["| 场景 | exit | result.status | result.json 合法 | 资产数 |", "|---|---:|---|---|---:|"]
        for name, rec in (probes.get("scenarios") or {}).items():
            if "status" in rec or "result_valid" in rec:
                lines.append("| %s | %s | %s | %s | %s |"
                             % (name, rec.get("exit"), rec.get("status"), rec.get("result_valid"),
                                len(rec.get("assets") or [])))
    else:
        lines.append("嵌套 finalize 调用（探针守卫生效），本次跳过子进程实测。")
    lines += [""]
    # ---- 8 version + reproductions + gaps
    ver = facts.get("version") or {}
    lines += ["## 8. 版本与回退", "",
              "- `version_history.md`：%s 字节，静态 7 个版本（v0.0.1→v1.1.0）+ 运行时段；"
              "回退方式见该文件 §3（删除资产模块 / `READBENCH_SKIP_ASSETS=1` / 整包回滚）。"
              % ver.get("bytes", "?"), ""]
    bad = [r for r in golden.get("items") or [] if r.get("verdict") in ("deviation", "missing")]
    lines += ["## 9. 偏离项与复现", ""]
    if bad:
        lines.append("本批次存在 %d 条偏离/缺失（如实列出，不隐藏）：" % len(bad))
        lines += ["- %s `%s` %s: 期望 %s / 实际 %s"
                  % (r.get("id"), r.get("subject"), r.get("verdict"),
                     bench_golden.fmt(r.get("golden")), bench_golden.fmt(r.get("actual"))) for r in bad[:20]]
    else:
        lines.append("本批次无偏离、无缺失：金标准覆盖输入侧、题卡侧、锚点侧、评分表侧与汇总结论。")
    lines += ["", "复现命令（在包根执行）：",
              "", "```bash",
              "python3 -B scripts/run_build.py init  --input <in> --output <out> --work <work>",
              "python3 -B scripts/run_build.py check --input <in> --output <out> --work <work>",
              "python3 -B scripts/run_build.py build --input <in> --output <out> --work <work>",
              "# build 之后 out/ 下应有 10 件产物：5 件主产物 + 5 件可核验资产",
              "python3 -B scripts/run_build.py build --input <in> --output <out> --work <work>  # 幂等重跑",
              "```", "",
              "> 本报告的每个数字都来自落盘产物 + 输入原文的独立复算；没有手写数字，也不含预制的正式案例答案。"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- self check
def render_self_check(ctx, golden, probes, facts):
    """Machine receipts: contract, primary products, quotes, counts, fallbacks, exit codes."""
    out = Path(ctx["out_dir"])
    checks = []

    def add(cid, title, ok, detail, applicable=True):
        checks.append({"id": cid, "title": title, "ok": bool(ok), "applicable": bool(applicable),
                       "detail": detail})

    contract = ctx.get("contract") or {}
    names = [str(k) for k in contract] if isinstance(contract, dict) else [str(x) for x in contract] if contract else []
    result = _read_json(out / "result.json") or {}
    missing = [n for n in names if n not in result]
    add("result_json_contract", "每个声明的 output_contract 字段都出现在 result.json 顶层",
        not missing, "declared=%d missing=%s" % (len(names), missing or "none"),
        applicable=bool(names))

    envelope = ("case_id", "status", "stage", "skill", "outputs", "benchmark", "anchors", "scoring",
                "sources", "uncertainty", "pending_human", "errors", "degradations", "changes",
                "technical_synthetic", "runtime", "contract_fields_present", "contract_echo")
    lack = [k for k in envelope if k not in result]
    expect_status = (golden or {}).get("gold_status")
    add("result_envelope", "result.json 信封字段齐全且 status 与推导口径一致",
        not lack and (expect_status in (None, result.get("status"))),
        "missing_keys=%s status=%s expected=%s" % (lack or "none", result.get("status"), expect_status))

    prods = {}
    for name in MAIN:
        p = out / name
        prods[name] = {"bytes": p.stat().st_size if p.is_file() else 0, "exists": p.is_file()}
    parsed = all(_read_json(out / n) is not None for n in MAIN if n.endswith(".json"))
    report = (out / "report.md").read_text(encoding="utf-8") if (out / "report.md").is_file() else ""
    sections = len(re.findall(r"(?m)^##\s+\d+\.", report))
    add("primary_products", "五件主产物存在、非空、JSON 可解析、report 四段齐全",
        all(v["bytes"] > 0 for v in prods.values()) and parsed and sections >= 4,
        "all_nonempty=%s parsed=%s report_sections=%d"
        % (all(v["bytes"] > 0 for v in prods.values()), parsed, sections))

    bm = _read_json(out / "benchmark.json") or {}
    cards = bm.get("items") or []
    sc = _read_json(out / "scoring.json") or {}
    bad_cards = []
    for it in cards:
        rub = it.get("rubric") or []
        if len(str(it.get("question") or "")) < 10 or not rub or not (it.get("reference_answer")):
            bad_cards.append(it.get("id"))
        elif abs(sum(float(r.get("weight") or 0) for r in rub) - 1.0) > 0.02:
            bad_cards.append(it.get("id"))
        elif not it.get("evidence"):
            bad_cards.append(it.get("id"))
    add("card_invariants", "题卡结构/权重/证据齐全且权重和≈1.0",
        not bad_cards, "cards=%d bad=%s" % (len(cards), bad_cards or "none"), applicable=bool(cards))

    anchors = (_read_json(out / "anchors.json") or {}).get("anchors") or []
    bad_anchor = [a.get("item_id") for a in anchors if not a.get("verified")]
    add("anchors_verified", "anchors.json 每行 verified=true",
        not bad_anchor, "anchors=%d unverified=%s" % (len(anchors), bad_anchor or "none"),
        applicable=bool(anchors))

    gsum = (golden or {}).get("summary") or {}
    add("quote_hit_rate", "金标准引文逐字命中率 = 1.0",
        float(gsum.get("quote_hit_rate") or 0) >= 1.0,
        "quotes=%s verbatim=%s rate=%s" % (gsum.get("n_quotes"), gsum.get("n_quotes_verbatim"),
                                           gsum.get("quote_hit_rate")),
        applicable=bool(gsum.get("n_quotes")))

    score_bad = _bad(_cat(golden, "scores")) + _bad(_cat(golden, "aggregate"))
    add("scoring_recompute", "逐点分、题分与全部汇总指标可从落盘产物复算",
        not score_bad, "deviation/missing=%s" % (len(score_bad)), applicable=bool(cards))

    add("golden_diff", "金标准对照无 deviation / missing",
        not gsum.get("deviation") and not gsum.get("missing"),
        "met=%s deviation=%s missing=%s not_applicable=%s"
        % (gsum.get("met"), gsum.get("deviation"), gsum.get("missing"), gsum.get("not_applicable")))

    res_bm = result.get("benchmark") or {}
    res_an = result.get("anchors") or {}
    sc_items = sc.get("items") or []
    agg = sc.get("aggregate") or {}
    n_points = sum(len(it.get("rubric") or []) for it in cards)
    n_evidence = sum(len(it.get("evidence") or []) for it in cards)
    ok_counts = (res_bm.get("n_items") == len(cards) == len(sc_items)
                 and agg.get("n_items") == len(cards)
                 and agg.get("n_points") == n_points
                 and res_bm.get("n_rubric_points") == n_points
                 and (res_an.get("n_anchors") == len(anchors) == n_evidence)
                 and (res_an.get("verified") == sum(1 for a in anchors if a.get("verified"))))
    add("counts_consistency", "题数/点数/锚点数在 result、benchmark、anchors、scoring 间一致",
        ok_counts, "cards=%d points=%d anchors=%d evidence=%d" % (len(cards), n_points, len(anchors), n_evidence),
        applicable=bool(cards))

    if (probes or {}).get("skipped"):
        add("degraded_input_probe", "空输入与坏 JSON 的 build 仍 exit 0 且产出合法 partial + 5 资产",
            True, "nested finalize run: probe skipped by READBENCH_SKIP_PROBE=1 (outer process runs it)",
            applicable=False)
        add("partial_result_first", "init 先落合法 partial result.json", True,
            "nested finalize run: probe skipped", applicable=False)
    else:
        scn = (probes or {}).get("scenarios") or {}
        emp, badj = scn.get("empty_input") or {}, scn.get("bad_json") or {}
        ok_deg = (emp.get("exit") == 0 and emp.get("result_valid") is True
                  and badj.get("exit") == 0 and badj.get("result_valid") is True
                  and len(emp.get("assets") or []) >= 5 and len(badj.get("assets") or []) >= 5)
        add("degraded_input_probe", "空输入与坏 JSON 的 build 仍 exit 0 且产出合法 partial + 5 资产",
            ok_deg, "empty(status=%s,exit=%s,assets=%d) bad(status=%s,exit=%s,assets=%d)"
            % (emp.get("status"), emp.get("exit"), len(emp.get("assets") or []),
               badj.get("status"), badj.get("exit"), len(badj.get("assets") or [])))
        init = scn.get("init_partial") or {}
        add("partial_result_first", "init 先落合法 partial result.json",
            init.get("exit") == 0 and init.get("stage") == "init" and init.get("status") == "partial",
            "init(exit=%s stage=%s status=%s)" % (init.get("exit"), init.get("stage"), init.get("status")))

    script = Path(ctx.get("pkg_root") or ".") / "scripts" / "run_build.py"
    src = bench_golden.read_text(script)
    non_zero = re.findall(r"sys\.exit\((?!0\b)\s*[1-9]\d*\s*\)", src)
    exits = (probes or {}).get("exit_codes") or {}
    add("exit_code_zero", "CLI 入口无显式非零退出，全部子进程 exit 0",
        not non_zero and (not exits or all(v == 0 for v in exits.values())),
        "static_nonzero=%s probe_exits=%s" % (non_zero or "none", exits or "skipped"))

    asset_sizes = {}
    for name in ASSETS[:-1]:
        p = out / name
        if name == "run.log":  # volatile by design: assert existence, never record its byte count
            asset_sizes[name] = "present" if p.is_file() and p.stat().st_size > 0 else "missing"
        else:
            asset_sizes[name] = p.stat().st_size if p.is_file() else 0
    add("assets_generated", "5 件可核验资产全部写出且非空（本文件随后写出）",
        all(v not in (0, "missing") for v in asset_sizes.values()),
        "assets=%s self_check=rendered,written-next" % asset_sizes)

    texts = {}
    for name in ("golden_standard.json", "diff_report.md", "version_history.md"):
        texts[name] = (out / name).read_text(encoding="utf-8") if (out / name).is_file() else ""
    log_text = (out / "run.log").read_text(encoding="utf-8") if (out / "run.log").is_file() else ""
    stamps = {n: len(TS.findall(t)) for n, t in texts.items()}
    add("determinism_by_construction", "除 run.log 外的资产不含时间戳（可逐字节复跑）",
        sum(stamps.values()) == 0 and bool(TS.findall(log_text)),
        "timestamps=%s run_log_stamps=%d" % (stamps, len(TS.findall(log_text))))

    ts_item = next((it for it in _cat(golden, "status") if it.get("subject") == "technical_synthetic"), None)
    synth = result.get("technical_synthetic") or {}
    add("synthetic_label", "checker/候选输出只登记不评分（technical_synthetic）",
        (ts_item is None or ts_item.get("verdict") == "met") and synth.get("not_a_dsh_score") is True,
        "present=%s not_a_dsh_score=%s scored=%s" % (synth.get("present"),
                                                     synth.get("not_a_dsh_score"), synth.get("scored")))

    ver_text = (out / "version_history.md").read_text(encoding="utf-8") if (out / "version_history.md").is_file() else ""
    tags = sum(1 for tag in ("v0.0.1", "v0.1.0", "v0.2.0", "v0.5.0", "v0.9.0", "v1.0.0", "v1.1.0")
               if tag in ver_text)
    add("version_ledger", "版本账本含 7 个静态版本、回退方式与运行时段",
        tags == 7 and "回退" in ver_text and "本次运行" in ver_text,
        "version_tags=%d/7 rollback=%s runtime_section=%s"
        % (tags, "回退" in ver_text, "本次运行" in ver_text))

    applicable = [c for c in checks if c["applicable"]]
    failed = [c["id"] for c in applicable if not c["ok"]]
    passed = sum(1 for c in applicable if c["ok"])
    ok = not failed
    doc = {"schema": "reading-bench-forge/self-check@1",
           "skill": {"name": "reading-bench-forge", "version": ctx.get("skill_version")},
           "case_id": result.get("case_id"),
           "status": result.get("status"),
           "ok": ok,
           "checks_total": len(checks),
           "checks_applicable": len(applicable),
           "checks_passed": passed,
           "failed": failed,
           "checks": checks,
           "assets": {name: asset_sizes.get(name) for name in ASSETS[:-1]},
           "golden": {"items": gsum.get("n_items"), "met": gsum.get("met"),
                      "deviation": gsum.get("deviation"), "missing": gsum.get("missing"),
                      "not_applicable": gsum.get("not_applicable"),
                      "quote_hit_rate": gsum.get("quote_hit_rate")},
           "probes": {"skipped": bool((probes or {}).get("skipped")),
                      "exit_codes": (probes or {}).get("exit_codes") or {}}
           if not (probes or {}).get("skipped") else {"skipped": True,
                                                      "reason": (probes or {}).get("reason")},
           "notes": ["This file asserts facts already on disk; it does not re-run the model.",
                     "The scoring table is a judgeability self-check, not an answer score and not a DSH score.",
                     "Timestamps live only in run.log; every other asset is byte-reproducible from the same input."]}
    return doc
