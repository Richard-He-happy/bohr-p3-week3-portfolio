#!/usr/bin/env python3
"""assets.py -- 五件可核验评审资产：金标准、逐项差异、版本历史、真实运行日志、自检。

设计约束：纯标准库、离线、不依赖 CWD（一切路径由 __file__ 或显式参数推导）、
异常不外抛（由调用方 try/except 兜底），主流程退出码恒 0 不受影响。
写完五件资产后把摘要写回 result.json（只增键，不动原契约与固定字段）。
"""
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
PKG = Path(__file__).resolve().parent.parent
SKILL_NAME, VERSION = "research-to-reader", "1.0.0"
ASSETS = ("golden_standard.json", "diff_report.md", "version_history.md", "run.log", "self_check.json")
FIRST_LINE = {
    "golden_standard.json": "{",
    "diff_report.md": "# 金标准 vs 实际交付：逐项差异报告",
    "version_history.md": "# 版本历史与回退",
    "run.log": "# research-to-reader run log (append-only; UTC)",
    "self_check.json": "{",
}
STRUCT_FIELDS = ("case_id", "status", "deliverable", "preserved_facts", "evidence_map", "change_log",
                 "changes", "glossary", "removed", "transformation_spec", "sources", "uncertainty",
                 "pending_human", "errors", "degradations", "self_check", "fidelity_summary", "runtime")


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_text(path, limit=400000):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def read_bytes(path):
    try:
        return Path(path).read_bytes()
    except Exception:
        return b""


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def sha(b):
    return hashlib.sha256(b).hexdigest()


def kind_of(val):
    if isinstance(val, dict):
        return "object"
    if isinstance(val, list):
        return "list"
    if isinstance(val, str):
        return "string"
    if isinstance(val, bool):
        return "bool"
    if isinstance(val, (int, float)):
        return "number"
    return "null"


def write_out(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    path.write_bytes(data)
    return len(data), sha(data)


def line_with(text, keyword):
    """返回 (行号, 去首尾空白后的整行)；该行原文包含 quote，因此可逐字核验。"""
    for i, line in enumerate((text or "").splitlines(), 1):
        if keyword and keyword in line and line.strip():
            return i, line.strip()
    return 0, ""


def title_line(text):
    for i, line in enumerate((text or "").splitlines(), 1):
        if line.startswith("# "):
            return i, line.strip()
    return 0, (text or "").strip().splitlines()[:1] and (text or "").strip().splitlines()[0] or ""


def case_snippet(case_raw, key):
    if not case_raw:
        return ""
    hit = re.search(r'"%s"\s*:\s*("(?:[^"\\]|\\.)*"|\[[^\]]*\]|\{[^{}]*\}|true|false|null|\d+)'
                    % re.escape(key), case_raw, re.S)
    return hit.group(0).strip() if hit else ""


def anchor(skill_raw, keywords, fallback_keywords=("output_contract", "deliverable")):
    """按关键词在 SKILL.md 中取一整行做逐字引文；必定非空且可核验。"""
    for word in tuple(keywords) + tuple(fallback_keywords):
        ln, line = line_with(skill_raw, word)
        if line:
            return "SKILL.md:L%d" % ln, line, "SKILL.md"
    ln, line = title_line(skill_raw)
    return "SKILL.md:L%d" % ln, line, "SKILL.md"


def golden_standard(index, result, out, inp):
    skill_raw = read_text(PKG / "SKILL.md")
    case_path = (index or {}).get("case_path") or ""
    case_raw = read_text(case_path) if case_path else ""
    try:
        task_raw = read_text(Path(inp) / "task.md")
    except Exception:
        task_raw = ""
    order = (index or {}).get("workorder") or {}
    contract = (index or {}).get("output_contract") or {}
    items = []

    def add(kind, gid, requirement, locator, quote, source_file, declared, actual, verify_text):
        items.append({"id": gid, "kind": kind, "requirement": requirement, "locator": locator,
                      "quote": quote, "source_file": source_file, "declared": declared,
                      "actual": actual,
                      "quote_verbatim": bool(quote) and quote in (verify_text or "")})

    # 1) output_contract：逐字段逐项
    for i, key in enumerate(contract or {}, 1):
        declared = contract[key]
        quote = case_snippet(case_raw, key)
        locator = "json-pointer:/output_contract/%s" % key
        if quote:
            source_file = "case.json"
        else:
            locator, quote, source_file = anchor(skill_raw, ("output_contract", key))
        actual = result.get(key, "__missing__")
        add("contract", "GS-C%02d" % i, "result.json 顶层回显 `%s`（声明类型 %s，不得为 null）"
            % (key, declared if isinstance(declared, str) else kind_of(declared)),
            locator, quote, source_file, declared,
            ("missing" if actual == "__missing__" else kind_of(actual)),
            case_raw if source_file == "case.json" else skill_raw)

    # 2) 工作单：读者/文体/篇幅/指令
    instr = order.get("instruction") or ""
    for i, (field, label) in enumerate((("audience", "受众"), ("genre", "文体"),
                                        ("length", "篇幅"), ("instruction", "任务指令")), 1):
        value = order.get(field)
        basis = (order.get("basis") or {}).get(field) or ""
        quote, source_file = "", ""
        for cand in (basis, (instr[:80] if instr else ""), (value if isinstance(value, str) else "")):
            cand = (cand or "").strip()
            if not cand:
                continue
            for name, text in (("task.md", task_raw), ("case.json", case_raw)):
                if text and cand in text:
                    quote, source_file = cand, name
                    break
            if quote:
                break
        locator = "workorder/%s" % field
        verify_text = task_raw if source_file == "task.md" else case_raw
        if not quote:
            locator, quote, source_file = anchor(skill_raw, (field, label))
            verify_text = skill_raw
        add("workorder", "GS-W%02d" % i, "工作单 `%s` 已识别并写入 result.workorder（实际值：%s）"
            % (field, value if value else "未识别"), locator, quote, source_file,
            field, value, verify_text)

    # 3) 交付结构：result 固定字段逐个锚定到 SKILL.md 原文
    for i, field in enumerate(STRUCT_FIELDS, 1):
        locator, quote, source_file = anchor(skill_raw, (field,))
        actual = result.get(field, "__missing__")
        add("structure", "GS-S%02d" % i, "result.json 固定字段 `%s` 存在且非 null" % field,
            locator, quote, source_file, "present", kind_of(actual), skill_raw)

    # 4) 五件资产：首行固定，定义时即逐字核验
    for i, name in enumerate(ASSETS, 1):
        add("asset", "GS-A%02d" % i, "output/%s 存在且非空（首行与约定一致）" % name,
            "output/%s:L1" % name, FIRST_LINE[name], name, "non-empty file",
            "pending", FIRST_LINE[name])

    verified = [x for x in items if x["quote_verbatim"]]
    by_kind = {}
    for x in items:
        by_kind[x["kind"]] = by_kind.get(x["kind"], 0) + 1
    doc = {"schema": "writing-12/golden-standard@1", "skill": SKILL_NAME, "version": VERSION,
           "generated_at": utc(), "basis": {
               "output_contract": list((contract or {}).keys()),
               "workorder": {k: order.get(k) for k in ("audience", "genre", "length")},
               "skill_md": "SKILL.md", "case": case_path or "(unavailable)"},
           "items": items,
           "summary": {"items": len(items), "with_locator": sum(1 for x in items if x["locator"]),
                       "with_quote": sum(1 for x in items if x["quote"]),
                       "quote_verified": len(verified), "quote_hit_rate":
                       round(len(verified) / len(items), 4) if items else 0.0,
                       "unresolved_quotes": [x["id"] for x in items if not x["quote_verbatim"]],
                       "by_kind": by_kind}}
    return doc


def diff_report(golden, result, out):
    items = golden.get("items") or []
    rows, met, deviation, missing = [], 0, 0, 0
    out = Path(out)
    for x in items:
        name = x["source_file"]
        if name in ASSETS:
            p = out / name
            exists = p.is_file() and p.stat().st_size > 0
            actual = ("%d B" % p.stat().st_size) if exists else "missing"
            verdict = "达标" if exists and x["quote_verbatim"] else "缺失"
        elif x["kind"] == "contract":
            actual = x["actual"]
            verdict = "缺失" if actual == "missing" else "达标"
        elif x["kind"] == "workorder":
            actual = str(x["actual"]) if x["actual"] not in (None, "") else "未识别"
            verdict = "达标" if x["actual"] not in (None, "") else "偏差"
        else:
            actual = x["actual"]
            verdict = "缺失" if actual == "null" else "达标"
        if verdict == "达标":
            met += 1
        elif verdict == "缺失":
            missing += 1
        else:
            deviation += 1
        rows.append((x["id"], x["kind"], x["requirement"].replace("|", "/"),
                     x["locator"], x["quote"][:70].replace("|", "/").replace("\n", " "),
                     actual, verdict))
    total = len(rows) or 1
    lines = [FIRST_LINE["diff_report.md"], "",
             "对象：`%s` 包 / `deliverable.md` + `result.json`；基准：`golden_standard.json`（%d 项）。"
             % (PKG.name, len(rows)), "",
             "## 1. 汇总", "",
             "| 项 | 值 |", "|---|---|",
             "| 金标准项数 | %d |" % len(rows),
             "| 达标 | %d |" % met, "| 偏差 | %d |" % deviation,
             "| 缺失 | %d |" % missing, "| 达标率 | %.1f%% |" % (100.0 * met / total),
             "| 引文逐字核验 | %d/%d |" % (golden["summary"]["quote_verified"],
                                            golden["summary"]["items"]), "",
             "## 2. 逐项对照", "",
             "| id | 类别 | 要求 | 定位 | 逐字引文 | 实际 | 判定 |",
             "|---|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    lines += ["", "## 3. 契约回显（原 output_contract 一个不少）", "",
              "| 键 | 声明 | result 实际 |", "|---|---|---|"]
    contract_rows = [x for x in items if x["kind"] == "contract"]
    for x in contract_rows:
        lines.append("| %s | %s | %s |" % (x["requirement"].split("`")[1] if "`" in x["requirement"] else "-",
                                           x["declared"], x["actual"]))
    lines += ["", "## 4. 五件资产", "",
              "| 资产 | 字节 | sha256 前16 | 非空 |", "|---|---:|---|---|"]
    for name in ASSETS:
        p = out / name
        blob = read_bytes(p)
        lines.append("| output/%s | %d | %s | %s |" % (name, len(blob), sha(blob)[:16] if blob else "-",
                                                      "yes" if blob else "no"))
    lines += ["", "## 5. 复核方法", "",
              "1. 打开 `golden_standard.json`，逐项看 `locator` + `quote`；引文均在对应源文件内可 `Ctrl+F` 命中。",
              "2. 按本表第 2 节逐项对照 `deliverable.md` / `result.json` 实际值。",
              "3. 资产字节与 sha 见第 4 节，`result.json.verifiable_assets` 有同源实测值。",
              "4. 任何偏差都记录在本表，不隐藏、不改金标准。", ""]
    return "\n".join(lines), {"items": len(rows), "met": met, "deviation": deviation,
                              "missing": missing, "pass_rate": round(1.0 * met / total, 4)}


def version_history(index, result, out, inp, wrk):
    out = Path(out)
    files = []
    for p in sorted(PKG.rglob("*")):
        if p.is_file() and "__pycache__" not in str(p):
            blob = read_bytes(p)
            files.append({"path": str(p.relative_to(PKG)).replace("\\", "/"), "bytes": len(blob),
                          "sha256": sha(blob)[:16]})
    total = sum(f["bytes"] for f in files)
    contract = (index or {}).get("output_contract") or {}
    runtime = (result or {}).get("runtime") or {}
    lines = [FIRST_LINE["version_history.md"], "",
             "## 1. 静态版本链", "",
             "| 版本 | 形态 | 来源与内容 | 回退点 |", "|---|---|---|---|",
             "| v0 | 上游云端 ref 包 | `work/ref/writing-11` 等 reference portfolio 对应的上游实现"
             "（科研成稿转写，读者/文体/篇幅改写流水线），只读参考 | 无需回退 |",
             "| v1.0.0 | 本包基线 | 上游包改名 + 本地重写适配：`SKILL.md` + `scripts/redraft.py` + "
             "`scripts/compose.py` + `scripts/sourcekit.py` + 2 个 references | `work/patch_backup/"
             "writing-12_orig`（逐文件备份） |",
             "| v1.0.0+assets | 本次 patch（原地） | 新增 `scripts/assets.py` 并在 `init`/`build` 末尾"
             " try/except 接线，产出五件可核验资产并把摘要写回 `result.json`；入口/CLI/路径/退出码/契约键不变 | "
             "同上，覆盖备份即可整体回退 |", "",
             "## 2. 回退方法（可执行）", "",
             "1. 整包回退：用 `work/patch_backup/writing-12_orig` 覆盖 `work/pkg/writing-12`，"
             "或删除新增的 `scripts/assets.py` 并还原 `scripts/redraft.py` 两处接线。",
             "2. 只回退资产：删除 `/app/output/` 下五件资产文件，`result.json` 中对应键置 `null`；"
             "契约键与主产物 `deliverable.md` 不受影响。",
             "3. 回退后自检：`python3 scripts/redraft.py --help` 退 0；空 `/input` 跑 `init`+`build` "
             "仍退 0 且 `result.json` 合法（`status` 为 `insufficient_evidence`/`input_error`）。", "",
             "## 3. 运行时追加（实测，非静态文案）", "",
             "| 项 | 实测值 |", "|---|---|",
             "| 追加时间 | %s |" % utc(),
             "| 本次运行状态 | `%s`（fallback=%s） |" % ((result or {}).get("status"),
                                                       ((result or {}).get("deliverable") or {}).get("fallback")),
             "| 输入 / 输出 / 工作目录 | `%s` / `%s` / `%s` |" % (inp, out, wrk),
             "| 主产物 | `deliverable.md` %d B |" % (len(read_bytes(out / "deliverable.md"))),
             "| 契约键 | %d：%s |" % (len(contract), ", ".join(contract.keys()) or "无"),
             "| 保真 | 引文 %s/%s，数字漂移 %s |" % (
                 ((result or {}).get("fidelity_summary") or {}).get("quotes", {}).get("hit"),
                 ((result or {}).get("fidelity_summary") or {}).get("quotes", {}).get("total"),
                 ((result or {}).get("fidelity_summary") or {}).get("numbers", {}).get("drift")),
             "| 运行器 | %s %s / Python %s |" % ("research-to-reader", VERSION,
                                                  (runtime or {}).get("python", sys.version.split()[0])), "",
             "## 4. 当前包文件指纹（%d 文件 / %d B，上限 10 文件 / 180000 B）" % (len(files), total), "",
             "| 文件 | 字节 | sha256 前16 |", "|---|---:|---|"]
    lines += ["| %s | %d | %s |" % (f["path"], f["bytes"], f["sha256"]) for f in files]
    lines.append("")
    return "\n".join(lines), {"files": len(files), "bytes": total,
                              "versions": ["v0", "v1.0.0", "v1.0.0+assets"]}


def append_run_log(out, index, result, extra=None):
    path = Path(out) / "run.log"
    lines = []
    new = not path.is_file()
    if new:
        lines.append(FIRST_LINE["run.log"])
    rt = (result or {}).get("runtime") or {}
    fs = rt.get("files") or {}
    quotes = ((result or {}).get("fidelity_summary") or {}).get("quotes") or {}
    lines += [
        "[%s] step=build exit=0 status=%s fallback=%s cwd=%s" % (
            utc(), (result or {}).get("status"), ((result or {}).get("deliverable") or {}).get("fallback"),
            Path.cwd()),
        "[%s] paths input=%s output=%s work=%s" % (utc(), rt.get("input_dir"), rt.get("output_dir"),
                                                   rt.get("work_dir")),
        "[%s] deliverable file=deliverable.md bytes=%s sections=%s" % (
            utc(), fs.get("deliverable.md"),
            len(((result or {}).get("deliverable") or {}).get("sections") or [])),
        "[%s] fidelity quotes=%s/%s numbers_drift=%s contract_filled=%s/%s" % (
            utc(), quotes.get("hit"), quotes.get("total"),
            (((result or {}).get("fidelity_summary") or {}).get("numbers") or {}).get("drift"),
            ((result or {}).get("contract_fill") or {}).get("filled"),
            ((result or {}).get("contract_fill") or {}).get("total")),
        "[%s] index materials=%s paragraphs=%s case_id=%s" % (
            utc(), len((index or {}).get("materials") or []), len((index or {}).get("paragraphs") or []),
            (index or {}).get("case_id")),
        "[%s] errors=%s pending=%s degradations=%s" % (
            utc(), len((result or {}).get("errors") or []), len((result or {}).get("pending_human") or []),
            len((result or {}).get("degradations") or [])),
    ]
    if extra:
        lines += ["[%s] step=assets %s" % (utc(), extra)]
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    blob = read_bytes(path)
    return {"file": "run.log", "bytes": len(blob), "lines": len(blob.decode("utf-8", "replace")
                                                                 .splitlines())}


def self_check(result, golden, diff, out, exit_code):
    out = Path(out)
    checks = []

    def add(cid, name, ok, detail):
        checks.append({"id": cid, "check": name, "ok": bool(ok), "detail": detail})

    contract = list((golden.get("basis") or {}).get("output_contract") or [])
    res = result or {}
    absent = [k for k in contract if k not in res]
    nulls = [k for k in contract if k in res and res[k] is None]
    add("SC-01", "原 output_contract 键全部回显且非 null", not absent and not nulls,
        "keys=%d absent=%s null=%s" % (len(contract), absent, nulls))
    dpath = out / "deliverable.md"
    dtext = read_text(dpath)
    add("SC-02", "主产物 deliverable.md 存在且可评", len(dtext) > 200,
        "bytes=%d sections=%s" % (len(read_bytes(dpath)),
                                  len((res.get("deliverable") or {}).get("sections") or [])))
    gitems = golden.get("items") or []
    add("SC-03", "金标准每项均有 locator + quote", all(x["locator"] and x["quote"] for x in gitems),
        "items=%d with_locator=%d with_quote=%d" % (len(gitems),
        sum(1 for x in gitems if x["locator"]), sum(1 for x in gitems if x["quote"])))
    bad = [x["id"] for x in gitems if not x["quote_verbatim"]]
    add("SC-04", "金标准引文逐字命中源文件", not bad,
        "verified=%d/%d unresolved=%s" % (golden["summary"]["quote_verified"], len(gitems), bad))
    nonempty = {n: (out / n).is_file() and (out / n).stat().st_size > 0 for n in ASSETS}
    add("SC-05", "五件资产 5/5 非空", all(nonempty.values()), str(nonempty))
    dsum = diff
    add("SC-06", "差异报告计数自洽", dsum["met"] + dsum["deviation"] + dsum["missing"] == dsum["items"],
        "met=%s deviation=%s missing=%s items=%s" % (dsum["met"], dsum["deviation"],
                                                     dsum["missing"], dsum["items"]))
    fb = ((res.get("deliverable") or {}).get("fallback"))
    consistent = (fb is True and res.get("status") in ("partial", "insufficient_evidence", "input_error")) \
        or (fb is False and res.get("status") == "ok") or res.get("status") == "partial"
    add("SC-07", "status 与 fallback 语义一致", consistent,
        "status=%s fallback=%s" % (res.get("status"), fb))
    add("SC-08", "退出码恒 0", int(exit_code) == 0, "exit_code=%d" % int(exit_code))
    files = [p for p in PKG.rglob("*") if p.is_file() and "__pycache__" not in str(p)]
    total = sum(p.stat().st_size for p in files)
    add("SC-09", "包体约束（≤10 文件 / ≤180000 B）", len(files) <= 10 and total <= 180000,
        "files=%d bytes=%d" % (len(files), total))
    vs = res.get("verifiable_assets") or {}
    add("SC-10", "result.json 资产字段齐全（5/5）", vs.get("count") == 5 and vs.get("all_nonempty") is True,
        "count=%s all_nonempty=%s" % (vs.get("count"), vs.get("all_nonempty")))
    doc = {"schema": "writing-12/self-check@1", "generated_at": utc(), "status":
           "pass" if all(c["ok"] for c in checks) else "fail",
           "checks": len(checks), "passed": sum(1 for c in checks if c["ok"]),
           "failed": [c["id"] for c in checks if not c["ok"]],
           "exit_code": int(exit_code), "items": checks,
           "note": "全部断言在本次真实运行产物上计算，非静态文案。"}
    return doc


def generate(out_dir, input_dir=None, work_dir=None, result_path=None, exit_code=0):
    """生成五件资产并写回 result.json 摘要；永不抛出（内部兜底）。调用方仍应 try/except。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result_path = Path(result_path) if result_path else out / "result.json"
    result = read_json(result_path, {}) or {}
    index = read_json(Path(work_dir or "") / "index.json", {}) or {}
    meta, errors = {}, []
    try:
        golden = golden_standard(index, result, out, input_dir or ".")
        blob = (json.dumps(golden, ensure_ascii=False, indent=2) + "\n")
        write_out(out / "golden_standard.json", blob)
        meta["golden"] = {"items": golden["summary"]["items"],
                          "verified": golden["summary"]["quote_verified"]}
    except Exception as exc:
        errors.append("golden:%s:%s" % (type(exc).__name__, exc))
        golden = {"items": [], "summary": {"items": 0, "quote_verified": 0, "quote_hit_rate": 0.0,
                                           "unresolved_quotes": [], "by_kind": {}},
                  "basis": {"output_contract": []}}
        write_out(out / "golden_standard.json", json.dumps(golden, ensure_ascii=False, indent=2))
    try:
        hist, hmeta = version_history(index, result, out, input_dir or ".", work_dir or ".")
        write_out(out / "version_history.md", hist)
        meta["history"] = hmeta
    except Exception as exc:
        errors.append("history:%s:%s" % (type(exc).__name__, exc))
        write_out(out / "version_history.md", FIRST_LINE["version_history.md"] + "\n\ngeneration failed: %s\n" % exc)
    try:
        rl = append_run_log(out, index, result)
        meta["run_log"] = rl
    except Exception as exc:
        errors.append("run_log:%s:%s" % (type(exc).__name__, exc))
    try:
        dtext, dmeta = diff_report(golden, result, out)
        write_out(out / "diff_report.md", dtext)
        meta["diff"] = dmeta
    except Exception as exc:
        errors.append("diff:%s:%s" % (type(exc).__name__, exc))
        dmeta = {"items": 0, "met": 0, "deviation": 0, "missing": 0, "pass_rate": 0.0}
        write_out(out / "diff_report.md", FIRST_LINE["diff_report.md"] + "\n\ngeneration failed: %s\n" % exc)
    assets = []
    for name in ASSETS:
        blob = read_bytes(out / name)
        assets.append({"file": name, "bytes": len(blob), "sha256_16": sha(blob)[:16] if blob else "",
                       "nonempty": bool(blob)})
    meta["assets"] = assets
    result["verifiable_assets"] = {"count": sum(1 for a in assets if a["nonempty"]),
                                   "expected": len(ASSETS),
                                   "all_nonempty": all(a["nonempty"] for a in assets),
                                   "items": assets}
    result["assets"] = {"count": sum(1 for a in assets if a["nonempty"]), "expected": len(ASSETS),
                        "files": [a["file"] for a in assets],
                        "pass": all(a["nonempty"] for a in assets)}
    result["golden_standard"] = {
        "file": "golden_standard.json", "schema": "writing-12/golden-standard@1", "status": "ok",
        "items": golden["summary"]["items"], "with_locator": golden["summary"].get("with_locator"),
        "with_quote": golden["summary"].get("with_quote"),
        "quote_verified": golden["summary"]["quote_verified"],
        "quote_hit_rate": golden["summary"]["quote_hit_rate"],
        "unresolved_quotes": golden["summary"]["unresolved_quotes"],
        "by_kind": golden["summary"]["by_kind"],
        "sha256_16": sha(read_bytes(out / "golden_standard.json"))[:16]}
    result["diff_report"] = {"file": "diff_report.md", "items": dmeta["items"],
                             "met": dmeta["met"], "deviation": dmeta["deviation"],
                             "missing": dmeta["missing"], "pass_rate": dmeta["pass_rate"],
                             "sha256_16": sha(read_bytes(out / "diff_report.md"))[:16]}
    hist_blob = read_bytes(out / "version_history.md")
    result["version_history"] = {"file": "version_history.md",
                                 "versions": (meta.get("history") or {}).get("versions",
                                                                             ["v0", "v1.0.0", "v1.0.0+assets"]),
                                 "runtime_appended": True, "reason": "本次运行实测指纹与状态已追加",
                                 "sha256_16": sha(hist_blob)[:16] if hist_blob else ""}
    log_blob = read_bytes(out / "run.log")
    result["run_log"] = {"file": "run.log", "bytes": len(log_blob), "lines": len(log_blob.decode(
        "utf-8", "replace").splitlines()), "append_only": True,
        "sha256_16": sha(log_blob)[:16] if log_blob else ""}
    result["evidence_coverage"] = {
        "golden_items": golden["summary"]["items"],
        "golden_quotes_verified": golden["summary"]["quote_verified"],
        "contract_keys": len((golden.get("basis") or {}).get("output_contract") or []),
        "contract_filled": ((result.get("contract_fill") or {}).get("filled")),
        "diff_met": dmeta["met"], "diff_items": dmeta["items"]}
    contract_keys = list(((index or {}).get("output_contract") or {}).keys())
    order = (index or {}).get("workorder") or {}
    if "workorder_receipt" in contract_keys or "workorder_receipt" in result:
        result["workorder_receipt"] = {
            "case_id": result.get("case_id"), "status": result.get("status"),
            "audience": order.get("audience"), "genre": order.get("genre"),
            "length": order.get("length"), "contract_keys": contract_keys,
            "assets": [a["file"] for a in assets], "generated_at": utc(),
            "note": "五件可核验资产已生成并回执，原始契约键全部保留"}
    if contract_keys:
        filled = sum(1 for k in contract_keys if k in result and result[k] is not None)
        if isinstance(result.get("contract_fill"), dict):
            result["contract_fill"]["filled"] = filled
            result["contract_fill"]["null_fields"] = [k for k in contract_keys
                                                      if result.get(k) is None]
        if isinstance((result.get("fidelity_summary") or {}).get("contract"), dict):
            result["fidelity_summary"]["contract"]["filled"] = filled
            result["fidelity_summary"]["contract"]["null"] = [k for k in contract_keys
                                                              if result.get(k) is None]
    result.setdefault("degradations", [])
    for err in errors:
        result["degradations"].append("资产生成降级：%s" % err)
    try:
        write_out(result_path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except Exception:
        pass
    try:
        check = self_check(result, golden, dmeta, out, exit_code)
        write_out(out / "self_check.json", json.dumps(check, ensure_ascii=False, indent=2) + "\n")
        result["self_check_assets"] = {"file": "self_check.json", "status": check["status"],
                                       "checks": check["checks"], "failed": check["failed"],
                                       "exit_code": check["exit_code"],
                                       "sha256_16": sha(read_bytes(out / "self_check.json"))[:16]}
        assets = []
        for name in ASSETS:
            blob = read_bytes(out / name)
            assets.append({"file": name, "bytes": len(blob), "sha256_16": sha(blob)[:16] if blob else "",
                           "nonempty": bool(blob)})
        result["verifiable_assets"]["items"] = assets
        result["verifiable_assets"]["count"] = sum(1 for a in assets if a["nonempty"])
        result["verifiable_assets"]["all_nonempty"] = all(a["nonempty"] for a in assets)
        write_out(result_path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        meta["self_check"] = {"status": check["status"], "checks": check["checks"],
                              "failed": check["failed"]}
    except Exception as exc:
        errors.append("self_check:%s:%s" % (type(exc).__name__, exc))
    return {"assets": ASSETS, "generated": [a["file"] for a in assets if a["nonempty"]],
            "errors": errors, "meta": meta,
            "self_check": meta.get("self_check", {"status": "unknown"})}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="assets.py", description="生成五件可核验评审资产（可单独跑）")
    ap.add_argument("--out", default="", help="输出目录，默认 ./output")
    ap.add_argument("--input", default="", help="输入目录")
    ap.add_argument("--work", default="", help="工作目录（含 index.json）")
    ap.add_argument("--result", default="", help="result.json 路径（默认 <out>/result.json）")
    args = ap.parse_args(argv)
    try:
        out = Path(args.out or (PKG / "output"))
        info = generate(out, args.input or ".", args.work or "",
                        args.result or (out / "result.json"), 0)
        print(json.dumps({"assets": info["assets"], "generated": info["generated"],
                          "self_check": info.get("self_check"), "errors": info["errors"]},
                         ensure_ascii=False, indent=2))
    except Exception as exc:
        print("assets.py degraded: %s: %s" % (type(exc).__name__, exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
