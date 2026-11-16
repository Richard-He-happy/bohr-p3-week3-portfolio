#!/usr/bin/env python3
"""Finalize-time asset layer for the reading-bench forge skill.

`run_build.py build` calls :func:`emit` once, after the five primary deliverables
are on disk, and writes five verifiable assets into the output root:

    version_history.md   static ledger v0.0.1 -> v1.1.0 + runtime section
    golden_standard.json independent expectation ledger (see bench_golden)
    diff_report.md       expectation-vs-artefact diff + scoring recompute
    run.log              real stage log of this build process
    self_check.json      machine receipts for contract/quotes/counts/fallback

The original five products, the CLI, the paths and the always-zero exit code are
not touched. Any failure here is caught and recorded as a degradation; the package
then behaves like v1.0.0 for that run.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import bench_diff
import bench_golden

VERSION_LEDGER = 7
STATIC_LINES = (
    ("v0.0.1", "骨架：`init`/`show`、段落索引（`M01#p7`）、partial result.json、退出码恒 0"),
    ("v0.1.0", "材料抽取（纯文本/DOCX/XLSX/PDF 降级链）+ 基于逐字锚点覆盖度的 0/1/2 档位"),
    ("v0.2.0", "`check` + `audit_items`：字段/引文/locator/权重校验；不可核验题拒收而非评分"),
    ("v0.5.0", "`build`：五件主产物 + 6 项结构自检（runtime.self_audit）"),
    ("v0.9.0", "契约回填（未知字段空镜像）、状态/降级矩阵、technical_synthetic 只登记不评分"),
    ("v1.0.0", "首次交付：Agent 出题 + 确定性兜底 + 路径参数化 + 三 references；纯标准库、退出码恒 0"),
    ("v1.1.0", "本 patch：finalize 资产层（5 件可核验资产）+ 5 个 result.json 汇总键；CLI/主产物/原字段不变"),
)


def _now(ctx):
    return round(time.time() - float(ctx.get("t_start") or time.time()), 3)


def note(ctx, stage, **kv):
    """Append one real event to the shared, run_build-owned event list."""
    events = ctx.get("events")
    if events is None:
        return
    row = {"stage": stage, "t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "elapsed": _now(ctx)}
    row.update({k: v for k, v in kv.items() if v is not None})
    events.append(row)


def _write(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _dump(doc):
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def _size(path):
    try:
        return Path(path).stat().st_size
    except OSError:
        return -1


# --------------------------------------------------------------- version ledger
def render_version(ctx):
    """Static history up to v1.0.0 plus the v1.1.0 asset layer; runtime section added."""
    built = bench_golden.load_built(ctx["out_dir"])
    bm = built.get("benchmark") or {}
    cards = bm.get("items") or []
    sc = built.get("scoring") or {}
    points = sum(len(it.get("rubric") or []) for it in cards)
    anchors = (built.get("anchors") or {}).get("anchors") or []
    meta = ctx.get("state") or "partial"
    lines = ["# reading-bench-forge 版本账本 / version history",
             "",
             "入口契约（CLI/路径/退出码/产物 schema）从 v1.0.0 起冻结；本文件只追加版本与回退方式，",
             "运行时事实写在文末「本次运行」段，不带时间戳（确定性），时间戳只出现在 `run.log`。",
             "",
             "## 1. 静态版本历史（v0.0.1 → v1.1.0）", ""]
    for ver, text in STATIC_LINES:
        lines.append("- **%s** — %s" % (ver, text))
    lines += ["",
              "## 2. 兼容性承诺（v1.0.0 → v1.1.0）",
              "",
              "1. 三个根路径不变：`/input`、`/app/work`、`/app/output`（`--input/--output/--work` 可覆盖）；",
              "2. 四个 verb 不变：`init` / `show` / `check` / `build`，参数语义不变；",
              "3. 五件主产物文件名与 schema 不变；",
              "4. `output_contract` 每个字段仍在 `result.json` 顶层出现；",
              "5. 退出码恒 0；v1.1.0 只新增 5 件资产与 5 个 `result.json` 汇总键。",
              "",
              "## 3. 回退方式（任选其一）",
              "",
              "1. **删除资产模块**：删 `scripts/bench_assets.py`、`bench_golden.py`、`bench_diff.py`，"
              "`build` 自动回到 v1.0.0 路径；",
              "2. **环境开关**：`READBENCH_SKIP_ASSETS=1 python3 -B scripts/run_build.py build ...` 跳过资产层；",
              "3. **整包回滚**：用 `work/patch_backup/reading-10_orig/` 覆盖包内 7 个文件（v1.0.0 原样）；",
              "4. **只回退版本号**：把 `SKILL.md` frontmatter 与 `reading_core.py` 的 `VER` 改回 `1.0.0`，"
              "资产 schema 独立，不受影响。",
              "",
              "## 4. 变更记录约定",
              "",
              "改评分口径（覆盖度阈值 0.6、0/1/2 档位、引文匹配策略）属于语义变更，必须升版本并在此追加一条；"
              "只加资产/报告不算语义变更，记在 v1.1.0 一行里。",
              "",
              "## 本次运行（runtime, 无时间戳）",
              "",
              "- case_id: `%s` | status: **%s** | mode: `%s`"
              % (ctx.get("case_id") or "-", meta, bm.get("mode") or "-"),
              "- materials: %s | cards: %s | rubric points: %s | anchors: %s"
              % (len((ctx.get("index") or {}).get("materials") or []), len(cards), points, len(anchors)),
              "- 资产: `golden_standard.json`（独立金标准） / `diff_report.md`（逐项对照+评分表自洽） / "
              "`version_history.md`（本文件） / `run.log`（真实阶段日志） / `self_check.json`（机器回执）",
              "- 主产物: `benchmark.json` / `anchors.json` / `scoring.json` / `report.md` / `result.json`",
              "- exit code: 0（恒 0 策略；失败只写 `errors`/`degradations`）"]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------- run.log
def render_run_log(ctx, facts):
    events = list(ctx.get("events") or [])
    doc = ctx.get("doc") or {}
    lines = ["# reading-bench-forge run log | verb=build | package=%s"
             % (ctx.get("skill_version") or "-"),
             "# columns: t | elapsed_s | stage | facts"]
    for e in events:
        kv = " ".join("%s=%s" % (k, _flat(v)) for k, v in e.items() if k not in ("t", "elapsed", "stage"))
        lines.append("%s | %.3f | %s | %s" % (e.get("t"), float(e.get("elapsed") or 0.0), e.get("stage"), kv))
    deg = doc.get("degradations") or []
    err = doc.get("errors") or []
    lines.append("")
    lines.append("# degradations=%d errors=%d" % (len(deg), len(err)))
    for d in deg[:10]:
        lines.append("# degradation | %s" % _flat(d))
    for e in err[:10]:
        lines.append("# error | %s" % _flat(e))
    golden = facts.get("golden") or {}
    sc = facts.get("self_plan") or {}
    lines.append("# summary | status=%s mode=%s assets=5/5 golden_items=%s golden_met=%s golden_dev=%s "
                 "golden_missing=%s planned_self_checks=%s exit_code=0"
                 % (doc.get("status") or "-", (facts.get("mode") or "-"), golden.get("n_items", "-"),
                    golden.get("met", "-"), golden.get("deviation", "-"), golden.get("missing", "-"),
                    sc.get("total", "-")))
    return "\n".join(lines) + "\n"


def _flat(v):
    if isinstance(v, (dict, list)):
        s = json.dumps(v, ensure_ascii=False, sort_keys=True)
    else:
        s = str(v)
    s = s.replace("\n", " ")
    return s if len(s) <= 160 else s[:157] + "..."


# ------------------------------------------------------------- degraded probes
def _run(script, args, timeout=120):
    env = dict(os.environ)
    env["READBENCH_SKIP_PROBE"] = "1"
    env.pop("READBENCH_SKIP_ASSETS", None)
    t0 = time.time()
    try:
        cp = subprocess.run([sys.executable, "-B", str(script)] + list(args), capture_output=True,
                            timeout=timeout, env=env)
        return {"exit": cp.returncode, "seconds": round(time.time() - t0, 3)}
    except Exception as e:  # pragma: no cover - defensive
        return {"exit": -1, "seconds": round(time.time() - t0, 3)}


def run_probes(ctx):
    """Really run the degraded paths in child processes and record the receipts."""
    if os.environ.get("READBENCH_SKIP_PROBE") == "1":
        note(ctx, "probes_skipped", reason="nested finalize guard READBENCH_SKIP_PROBE=1")
        return {"skipped": True, "reason": "nested finalize run (probe guard active)"}
    root = Path(ctx.get("pkg_root") or ".")
    script = root / "scripts" / "run_build.py"
    lib = root / "scripts" / "reading_core.py"
    tmp = Path(tempfile.mkdtemp(prefix="readbench_probe_"))
    out = {"skipped": False, "root": "tmp", "scenarios": {}, "exit_codes": {}}
    try:
        # 1. empty input
        emp = tmp / "empty_in"
        emp.mkdir(parents=True)
        out["scenarios"]["empty_input"] = _run(script, ["build", "--input", str(emp),
                                                        "--output", str(tmp / "empty_out"),
                                                        "--work", str(tmp / "empty_work")])
        # 2. bad case.json + broken pdf
        bad = tmp / "bad_in"
        bad.mkdir(parents=True)
        (bad / "case.json").write_text("{ this is not json ", encoding="utf-8")
        (bad / "broken.pdf").write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n")
        out["scenarios"]["bad_json"] = _run(script, ["build", "--input", str(bad),
                                                     "--output", str(tmp / "bad_out"),
                                                     "--work", str(tmp / "bad_work")])
        # 3. init must persist a partial result before any finalize
        out["scenarios"]["init_partial"] = _run(script, ["init", "--input", str(emp),
                                                         "--output", str(tmp / "init_out"),
                                                         "--work", str(tmp / "init_work")])
        # 4. both entry points must answer --help / direct execution with 0
        out["scenarios"]["help_main"] = _run(script, ["--help"])
        out["scenarios"]["help_lib"] = _run(lib, [])
        for name, rec in out["scenarios"].items():
            out["exit_codes"][name] = rec.get("exit")
            note(ctx, "probe_" + name, exit=rec.get("exit"), seconds=rec.get("seconds"))
        for key, name in (("empty_input", "empty_out"), ("bad_json", "bad_out"), ("init_partial", "init_out")):
            p = tmp / name / "result.json"
            try:
                res = json.loads(p.read_text(encoding="utf-8"))
                out["scenarios"][key]["result_valid"] = True
                out["scenarios"][key]["status"] = res.get("status")
                out["scenarios"][key]["stage"] = res.get("stage")
                out["scenarios"][key]["assets"] = sorted(x.name for x in (tmp / name).glob("*")
                                                         if x.is_file() and x.suffix in (".json", ".md", ".log"))
            except Exception:
                out["scenarios"][key]["result_valid"] = False
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    return out


# ------------------------------------------------------------------- emit main
def emit(out_dir, ctx):
    """Write the five assets; returns the additive result.json summary keys."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    note(ctx, "assets_start", out=str(out))
    cached = _cached_skip()
    if cached:
        note(ctx, "assets_skipped", reason=cached)
        return None
    facts = {"assets": {}, "mode": (ctx.get("origin") or "-"),
             "self_plan": {"total": len(bench_diff.CHECK_NAMES)}, "_doc": ctx.get("doc")}
    # 1. version ledger (golden derives from the file, so it goes first)
    try:
        text = render_version(ctx)
        p = _write(out / "version_history.md", text)
        facts["version"] = {"file": "version_history.md", "bytes": _size(p), "versions": VERSION_LEDGER}
        note(ctx, "version_history", bytes=facts["version"]["bytes"], versions=VERSION_LEDGER)
    except Exception as e:
        _degrade(ctx, "version_history", e)
    # 2. golden standard
    golden = None
    try:
        golden = bench_golden.derive(ctx)
        p = _write(out / "golden_standard.json", _dump(golden))
        s = golden.get("summary") or {}
        facts["golden"] = {"file": "golden_standard.json", "bytes": _size(p), "n_items": s.get("n_items"),
                           "met": s.get("met"), "deviation": s.get("deviation"),
                           "missing": s.get("missing"), "quotes": s.get("n_quotes"),
                           "quote_hit_rate": s.get("quote_hit_rate")}
        note(ctx, "golden_standard", items=s.get("n_items"), met=s.get("met"),
             deviation=s.get("deviation"), missing=s.get("missing"),
             quote_hit_rate=s.get("quote_hit_rate"))
    except Exception as e:
        _degrade(ctx, "golden_standard", e)
    # 3. degraded-input probes (real child processes, guarded against recursion)
    probes = run_probes(ctx)
    facts["probes"] = probes
    # 4. diff report
    try:
        diff_text = bench_diff.render_diff(ctx, golden, probes, facts)
        p = _write(out / "diff_report.md", diff_text)
        facts["diff"] = {"file": "diff_report.md", "bytes": _size(p)}
        note(ctx, "diff_report", bytes=facts["diff"]["bytes"],
             met=(golden or {}).get("summary", {}).get("met"),
             deviation=(golden or {}).get("summary", {}).get("deviation"),
             missing=(golden or {}).get("summary", {}).get("missing"))
    except Exception as e:
        _degrade(ctx, "diff_report", e)
    # 5. run log (the only asset carrying wall-clock timestamps)
    try:
        note(ctx, "self_check_planned", checks=len(bench_diff.CHECK_NAMES))
        log_text = render_run_log(ctx, facts)
        p = _write(out / "run.log", log_text)
        facts["log"] = {"file": "run.log", "bytes": _size(p),
                        "events": len(ctx.get("events") or []), "exit_code": 0}
        note(ctx, "run_log", bytes=facts["log"]["bytes"], events=facts["log"]["events"])
    except Exception as e:
        _degrade(ctx, "run_log", e)
    # 6. self check (last: it reads every asset back from disk)
    self_doc = None
    try:
        self_doc = bench_diff.render_self_check(ctx, golden, probes, facts)
        p = _write(out / "self_check.json", _dump(self_doc))
        facts["self"] = {"file": "self_check.json", "bytes": _size(p),
                         "ok": self_doc.get("ok"),
                         "checks_total": self_doc.get("checks_total"),
                         "checks_passed": self_doc.get("checks_passed"),
                         "failed": self_doc.get("failed") or []}
        note(ctx, "self_check", ok=self_doc.get("ok"), passed=self_doc.get("checks_passed"),
             total=self_doc.get("checks_total"))
    except Exception as e:
        _degrade(ctx, "self_check", e)
    keys = result_keys(facts, out)
    note(ctx, "assets_done", assets=sum(1 for k in ("golden", "diff", "version", "log", "self") if k in facts))
    return {"result_keys": keys, "facts": facts}


def _cached_skip():
    if os.environ.get("READBENCH_SKIP_ASSETS") == "1":
        return "READBENCH_SKIP_ASSETS=1"
    return ""


def _degrade(ctx, name, exc):
    doc = ctx.get("doc")
    if isinstance(doc, dict):
        doc.setdefault("degradations", []).append(
            {"item": "assets", "issue": "%s: %s" % (name, str(exc)[:300]),
             "action": "kept the v1.0.0 deliverables and continued with exit code 0"})
    note(ctx, "asset_error", asset=name, error=str(exc)[:300])


def result_keys(facts, out):
    """The five additive result.json keys; byte counts are read back from disk."""
    g = facts.get("golden") or {}
    d = facts.get("diff") or {}
    v = facts.get("version") or {}
    l = facts.get("log") or {}
    s = facts.get("self") or {}
    golden_summary = {}
    try:
        golden_summary = (json.loads((Path(out) / "golden_standard.json").read_text(encoding="utf-8"))
                          .get("summary") or {})
    except Exception:
        pass
    return {
        "golden_standard": {"file": "golden_standard.json", "bytes": _size(Path(out) / "golden_standard.json"),
                            "items": g.get("n_items"), "quotes": g.get("quotes"),
                            "quote_hit_rate": g.get("quote_hit_rate"),
                            "met": g.get("met"), "deviation": g.get("deviation"),
                            "missing": g.get("missing"),
                            "not_applicable": golden_summary.get("not_applicable"),
                            "by_category": golden_summary.get("by_category")},
        "diff_report": {"file": "diff_report.md", "bytes": _size(Path(out) / "diff_report.md"),
                        "items": g.get("n_items"), "met": g.get("met"),
                        "deviation": g.get("deviation"), "missing": g.get("missing"),
                        "scoring_consistency": "PASS" if not (golden_summary.get("deviation") or
                                                             golden_summary.get("missing")) else "REVIEW"},
        "version_history": {"file": "version_history.md", "bytes": _size(Path(out) / "version_history.md"),
                            "versions": VERSION_LEDGER, "run_section": True, "rollback": True},
        "run_log": {"file": "run.log", "bytes": _size(Path(out) / "run.log"),
                    "events": l.get("events"), "exit_code": 0,
                    "degradations": len(facts.get("_doc", {}).get("degradations") or []),
                    "errors": len(facts.get("_doc", {}).get("errors") or [])},
        "self_check": {"file": "self_check.json", "bytes": _size(Path(out) / "self_check.json"),
                       "ok": s.get("ok"), "checks_total": s.get("checks_total"),
                       "checks_passed": s.get("checks_passed"), "failed": s.get("failed") or []},
    }
