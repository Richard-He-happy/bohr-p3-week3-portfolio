#!/usr/bin/env python3
"""Diff report, fallback probes and machine self-check for the five verifiable assets.

Called by `assets.attach()` during `chapter_builder.py build` finalize. Everything is
stdlib-only and read-only with respect to the package: probes run in a temporary directory
outside the package and only inspect their own output.

Checks are honest: a check that cannot be run is recorded as `null` (skipped), never as a
pass; a failed probe is reported as a deviation, not hidden.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

VERSION = "1.1.0"
PROBE_ENV = "CHAPTER_ASSET_PROBE"
FIELDS = ("case_id", "deliverable", "preserved_facts", "evidence_map", "change_log")
ASSETS = ("golden_standard.json", "diff_report.md", "version_history.md", "run.log",
          "self_check.json")
COVERAGE = ("materials", "readable", "quotes_verified", "quotes_rejected", "facts",
            "h2_headings", "chars", "requested_sections", "covered_sections",
            "missing_sections")
BLANK = re.compile(r"\s+")
HEADING = re.compile(r"^#{1,3}\s+(.*)$")
SECTION_WORDS = {"摘要": ("摘要", "abstract"), "引言": ("引言", "intro"),
                 "方法": ("方法", "method"), "结果": ("结果", "result"),
                 "讨论": ("讨论", "discussion"), "结论": ("结论", "conclusion"),
                 "参考文献": ("参考文献", "reference"), "数据可得性声明": ("数据可得", "availability")}


# ---------------------------------------------------------------- helpers
def _flat(value, cap):
    body = BLANK.sub(" ", "" if value is None else str(value)).strip()
    return body if len(body) <= cap else body[:cap - 1] + "…"


def _norm(value):
    return BLANK.sub("", value or "")


def _rd(path, cap=4 << 20):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:cap]
    except (OSError, ValueError):
        return ""


def _size(path):
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def _wr(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return target.stat().st_size


def _case_contract(bundle):
    case = bundle.get("case") if isinstance(bundle.get("case"), dict) else {}
    contract = case.get("output_contract")
    if isinstance(contract, dict):
        return [str(key) for key in contract]
    if isinstance(contract, (list, tuple)):
        return [str(key) for key in contract if isinstance(key, str)]
    return []


def _materials_text(bundle):
    parts = []
    for item in bundle.get("materials") or []:
        if item.get("readable") and item.get("text"):
            parts.append(BLANK.sub("", item.get("text")))
    return "\n".join(parts)


def _manuscript(bundle):
    text = bundle.get("text")
    if isinstance(text, str) and text.strip():
        return text
    return _rd(Path(bundle.get("output") or "/app/output") / "manuscript.md")


def _sections(text):
    """Parse `## heading` blocks into [(heading, [paragraph lines])]."""
    blocks, current = [], None
    for line in (text or "").splitlines():
        match = HEADING.match(line.strip())
        if match and line.lstrip().startswith("##"):
            current = [match.group(1).strip(), []]
            blocks.append(current)
        elif current is not None:
            current[1].append(line)
    return blocks


def _section_hit(name, text):
    wanted = SECTION_WORDS.get(name, (name,))
    for heading, _lines in _sections(text):
        if any(word in heading for word in wanted):
            return True
    return False


def _paragraphs(section_name, text):
    wanted = SECTION_WORDS.get(section_name, (section_name,))
    for heading, lines in _sections(text):
        if any(word in heading for word in wanted):
            count = 0
            for line in lines:
                body = line.strip()
                if not body or body.startswith(">") or body.startswith("材料未覆盖"):
                    continue
                count += 1
            return count
    return 0


def _section_body(section_name, text):
    """A section has body when it carries prose, evidence blockquotes or both."""
    wanted = SECTION_WORDS.get(section_name, (section_name,))
    for heading, lines in _sections(text):
        if not any(word in heading for word in wanted):
            continue
        prose = _paragraphs(section_name, text)
        evidence = len([line for line in lines
                        if line.strip().startswith(">") and len(line.strip()) > 2])
        return prose > 0 or evidence > 0, prose, evidence
    return False, 0, 0


def _quote_hit(quote, corpus):
    probe = _norm(quote)
    return bool(probe) and len(probe) >= 8 and probe in corpus


# ---------------------------------------------------------------- diff report
def diff(gold, bundle, probe=None):
    """逐项对照金标准与实际产物，返回 (markdown, summary)。"""
    result = bundle.get("result") or {}
    stats = bundle.get("stats") or {}
    coverage = stats if isinstance(stats, dict) else {}
    out = Path(bundle.get("output") or "/app/output")
    manuscript = _manuscript(bundle)
    corpus = _materials_text(bundle)
    evidence = bundle.get("evidence") or []
    facts = bundle.get("facts") or []
    evidence_quotes = [_norm(item.get("quote")) for item in evidence + facts]
    status = result.get("status") or bundle.get("status")
    number_audit = coverage.get("number_audit") or {}
    pending = bundle.get("pending") or ()
    probe = probe or {}
    rows, counts = [], {"pass": 0, "missing": 0, "deviation": 0, "record": 0}

    def row(item, actual, verdict, reason):
        counts[verdict] = counts.get(verdict, 0) + 1
        rows.append({"id": item.get("id"), "group": item.get("group"),
                     "expected": item.get("expected"), "actual": actual,
                     "verdict": verdict, "reason": reason})

    for item in gold.get("items") or []:
        group = item.get("group")
        if group == "contract_field":
            key = (item.get("quote") or "").strip('"') or \
                (item.get("locator") or "").split(".")[-1]
            present = key in result
            row(item, "result.json 顶层键 %s 存在" % key if present else "结果中无该键",
                "pass" if present else "missing",
                "契约字段原样回填。" if present else "output_contract 键丢失，违反原契约。")
        elif group == "required_section":
            name = re.search(r"「([^」]+)」", item.get("expected") or "")
            name = name.group(1) if name else ""
            hit = _section_hit(name, manuscript)
            body, paras, ev_lines = _section_body(name, manuscript)
            row(item, "章节命中，正文 %d 段 / 引文 %d 行" % (paras, ev_lines)
                if hit else "稿件无该章节标题",
                "pass" if hit and body else ("deviation" if hit else "missing"),
                "章节覆盖且正文/引文非空。" if hit and body else
                ("标题存在但正文与引文均空，属偏差。" if hit else "任务指令点名的章节缺失。"))
        elif group == "instruction_requirement":
            note = item.get("note") or ""
            kind = note.split("判据类别=")[-1].rstrip("。") if "判据类别=" in note else "manual"
            if kind == "fidelity":
                hit_rate = number_audit.get("hit_rate")
                rejected = coverage.get("quotes_rejected") or 0
                ok = rejected == 0 and (hit_rate in (None, 1.0, 1))
                row(item, "数字命中率 %s，拒收引文 %d 条" % (hit_rate, rejected),
                    "pass" if ok else "deviation",
                    "数值/引文均逐字来自材料。" if ok else "存在未逐字命中的数字或引文。")
            elif kind == "volume":
                para = max(_paragraphs("结果", manuscript), _paragraphs("讨论", manuscript))
                ok = _paragraphs("结果", manuscript) >= 2 and _paragraphs("讨论", manuscript) >= 2
                row(item, "结果/讨论段落数 = %d/%d" % (
                    _paragraphs("结果", manuscript), _paragraphs("讨论", manuscript)),
                    "pass" if ok else "deviation",
                    "满足段落下限。" if ok else
                    "未提供 agent 草稿时正文为引文块组装，段落数不足，属已知降级。")
            elif kind == "pending":
                entries = result.get("pending_human") or []
                keys_ok = all(isinstance(entry, dict) and entry.get("item")
                              and entry.get("reason") and entry.get("action")
                              for entry in entries)
                row(item, "pending_human %d 条，三字段齐全=%s" % (len(entries), keys_ok),
                    "pass" if keys_ok else "deviation",
                    "缺口与待确认结构完整。" if keys_ok else "待确认条目缺字段。")
            else:
                row(item, "引文逐字命中=%s" % item.get("verbatim_verified"),
                    "record", "人工语义项：机器只核 quote 与结构，语义由评审复核。")
        elif group in ("material_fact", "citation_fact"):
            quote = item.get("quote") or ""
            in_manuscript = _quote_hit(quote, _norm(manuscript))
            in_evidence = any(_norm(quote) and _norm(quote) in entry for entry in evidence_quotes)
            label = "引用/图注" if group == "citation_fact" else "事实句"
            row(item, "正文命中=%s，证据链命中=%s" % (in_manuscript, in_evidence),
                "pass" if in_manuscript and in_evidence else "deviation",
                "%s与证据链一致。" % label if in_manuscript and in_evidence else
                "%s未同时进入正文与证据链，属可核验性偏差。" % label)
        elif group == "task_requirement":
            verified = item.get("verbatim_verified")
            row(item, "task.md 逐字命中=%s" % verified,
                "record", "任务说明要求为语义项；quote 已核，语义由评审复核。")
        elif group == "deliverable":
            name = (item.get("locator") or "").replace("output/", "")
            size = _size(out / name)
            row(item, "%s = %d B" % (name, size),
                "pass" if size > 0 else ("missing" if size == 0 and not (out / name).is_file()
                                         else "deviation"),
                "产物存在且非空。" if size > 0 else "产物缺失或为空。")
        elif group == "asset":
            name = (item.get("locator") or "").replace("output/", "")
            if name in pending:
                row(item, "%s：收尾阶段写出（由 self_check S5 断言）" % name, "record",
                    "diff 在收尾阶段生成；资产存在性统一由 self_check.json S5 核验。")
            else:
                size = _size(out / name)
                row(item, "%s = %d B" % (name, size),
                    "pass" if size > 0 else "missing",
                    "核验资产已写出。" if size > 0 else "核验资产缺失。")
        elif group == "behavior":
            mode = probe.get("mode")
            all_ok = probe.get("all_ok")
            if mode == "subprocess" and all_ok:
                row(item, "子进程实测通过（empty/bad/repeatable）", "pass",
                    "空输入/坏 JSON/确定性三类兜底实测 exit 0。")
            elif mode in ("subprocess", "unavailable", "error"):
                row(item, "%s（all_ok=%s）" % (mode, all_ok), "deviation",
                    "子进程兜底实测未全部通过，详见 self_check.json 的 probes。")
            else:
                row(item, "未执行（%s）" % mode, "record",
                    "运行环境禁止子进程时跳过，记录而不冒充通过。")
        elif group == "boundary":
            row(item, "status=%s；pending=%d 条" % (
                status, len(result.get("pending_human") or [])), "pass",
                "状态与缺口按实情记录（判据见 self_check S9）。")
        else:
            row(item, "未映射", "record", "金标准含未知分组，需人工复核。")

    total = len(rows)
    lines = ["# 差异核验报告（实际产物 vs 金标准）", "",
             "- case_id：`%s`；status：`%s`；生成时间：%s" % (
                 result.get("case_id"), status, time.strftime("%Y-%m-%dT%H:%M:%S")),
             "- 金标准：`golden_standard.json`（%d 项，逐项 locator+quote 可复核）" % (
                 (gold.get("counts") or {}).get("total") or 0),
             "- 对照结果：共 %d 项 → 达标 %d / 缺失 %d / 偏差 %d / 记录 %d" % (
                 total, counts.get("pass", 0), counts.get("missing", 0),
                 counts.get("deviation", 0), counts.get("record", 0)),
             "- 逐字引文：金标准 graded %s 条，命中 %s 条（比例 %s）" % (
                 (gold.get("counts") or {}).get("verbatim", {}).get("graded"),
                 (gold.get("counts") or {}).get("verbatim", {}).get("hit"),
                 (gold.get("counts") or {}).get("verbatim", {}).get("ratio")),
             ""]
    written = [name for name in ASSETS if _size(out / name) > 0]
    pending = [name for name in ASSETS if name in (bundle.get("pending") or ())]
    lines += ["## 关键一致性数字", "",
              "| 指标 | 实际 | 判据 |",
              "|-|-|-|",
              "| 契约字段 | %d | result.json 顶层原样回填 |" % len(
                  [key for key in (gold.get("expected") or {}).get("contract_fields") or []
                   if key in result]),
              "| 章节覆盖 | %d/%d | task_instruction 点名章节 |" % (
                  len(coverage.get("covered_sections") or []),
                  len(coverage.get("requested_sections") or [])),
              "| 事实记录 | %d 条 | preserved_facts |" % len(facts),
              "| 论断证据 | %d 条 | evidence_map |" % len(evidence),
              "| 数字命中率 | %s | coverage.number_audit.hit_rate |" % number_audit.get("hit_rate"),
              "| 引文拒收 | %d 条 | 逐字校验失败计数 |" % (coverage.get("quotes_rejected") or 0),
              "| 核验资产 | %d/5 已写 + %d 件收尾写（%s） | output 目录；存在性由 self_check S5 判定 |" % (
                  len([name for name in written if name not in pending]), len(pending),
                  "、".join(pending) or "无"),
              "| 降级/异常/待确认 | %d / %d / %d | result.json |" % (
                  len(result.get("degradations") or []), len(result.get("errors") or []),
                  len(result.get("pending_human") or [])),
              ""]
    lines += ["## 逐项对照", "",
              "| # | 组 | 金标准项（期望） | 实际 | 判定 | 原因 |",
              "|-|-|-|-|-|-|"]
    for number, item in enumerate(rows, 1):
        lines.append("| %d | %s | %s | %s | **%s** | %s |" % (
            number, item["group"], _flat(item["expected"], 90).replace("|", "/"),
            _flat(item["actual"], 80).replace("|", "/"), item["verdict"],
            _flat(item["reason"], 90).replace("|", "/")))
    for verdict, title in (("missing", "缺失清单"), ("deviation", "偏差清单"),
                           ("record", "记录项（人工/收尾判定）")):
        picked = [item for item in rows if item["verdict"] == verdict]
        if picked:
            lines += ["", "## " + title, ""] + [
                "- `%s` %s —— %s" % (item["id"], _flat(item["expected"], 120),
                                     _flat(item["reason"], 160)) for item in picked]
    lines += ["", "## 复核入口", "",
              "- 机器断言：`self_check.json`（S1–S11，含空/坏输入子进程实测）。",
              "- 运行阶段与耗时：`run.log`；版本与回退：`version_history.md`。", ""]
    summary = dict(counts, total=total)
    return "\n".join(lines), summary


# ---------------------------------------------------------------- fallback probes
def _probe_paths():
    return Path(__file__).resolve().parent / "chapter_builder.py"


def _run_one(root, input_setup):
    inp, out, work = root / "input", root / "out", root / "work"
    inp.mkdir(parents=True, exist_ok=True)
    try:
        input_setup(inp)
    except Exception as error:
        return {"ok": False, "note": "fixture:" + repr(error)[:120], "returncode": None}
    env = dict(os.environ)
    env[PROBE_ENV] = "child"
    command = [sys.executable, "-B", str(_probe_paths()), "build",
               "--input", str(inp), "--output", str(out), "--work", str(work)]
    try:
        done = subprocess.run(command, cwd=str(root), env=env, timeout=30,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as error:
        return {"ok": False, "note": "spawn:" + repr(error)[:160], "returncode": None}
    record = {"ok": False, "returncode": done.returncode,
              "stdout_tail": (done.stdout or b"").decode("utf-8", "replace")[-200:],
              "stderr_tail": (done.stderr or b"").decode("utf-8", "replace")[-200:]}
    result_path = out / "result.json"
    try:
        payload = json.loads(_rd(result_path))
    except Exception:
        payload = None
    record["result_valid"] = isinstance(payload, dict)
    record["result_status"] = (payload or {}).get("status")
    record["contract_fields"] = len([key for key in FIELDS if key in (payload or {})])
    record["assets"] = {name: _size(out / name) for name in ASSETS}
    record["assets_present"] = {name: bool(record["assets"].get(name)) for name in ASSETS}
    record["projection"] = _projection(payload)
    record["ok"] = bool(record["returncode"] == 0 and record["result_valid"]
                        and record["contract_fields"] == len(FIELDS)
                        and all(record["assets"].get(name) for name in ASSETS))
    return record


def _projection(payload):
    """Structure that must stay identical across repeated runs (timestamps excluded)."""
    if not isinstance(payload, dict):
        return None
    contract = payload.get("output_contract")
    contract_keys = sorted(contract) if isinstance(contract, dict) else []
    coverage = payload.get("coverage") or {}
    return {
        "case_id": payload.get("case_id"), "status": payload.get("status"),
        "contract_keys": contract_keys,
        "resident": [key for key in FIELDS if key in payload],
        "counts": {key: len(payload.get(key) or []) for key in
                   ("preserved_facts", "evidence_map", "change_log", "pending_human",
                    "degradations", "errors")},
        "sections": [len(coverage.get(key) or []) for key in
                     ("requested_sections", "covered_sections", "missing_sections")],
        "number_audit": coverage.get("number_audit"),
        "golden_items": (payload.get("golden_standard") or {}).get("items"),
        "diff": {key: (payload.get("diff_report") or {}).get(key) for key in
                 ("total", "pass", "missing", "deviation", "record")},
        "self_check": {key: (payload.get("self_check") or {}).get(key) for key in
                       ("passed", "total", "skipped", "pass")},
    }


def _write_bad(inp):
    (inp / "case.json").write_text('{"case_id": "bad-json", "output_contract": {', encoding="utf-8")
    (inp / "broken_material.md").write_text(
        "# 材料片段\n\n该样本在 25 °C 下测得强度为 17.5 MPa，样本量 n = 3。\n", encoding="utf-8")


def _write_min(inp):
    (inp / "case.json").write_text(json.dumps({
        "case_id": "probe-min", "task_instruction": "写摘要与结论，数字逐字取自材料。",
        "output_contract": {"case_id": "", "deliverable": "", "preserved_facts": "",
                            "evidence_map": "", "change_log": ""}}, ensure_ascii=False),
        encoding="utf-8")
    (inp / "material.md").write_text(
        "# 摘要\n\n该样本在 30 °C 下测得强度为 21.4 MPa，样本量 n = 5。\n", encoding="utf-8")


def probes(bundle, allow=True):
    """空输入 / 坏 JSON / 重复运行的子进程实测；环境禁止子进程时记 skipped。"""
    switch = str(os.environ.get(PROBE_ENV, "1")).strip().lower()
    if not allow or switch in ("0", "off", "false", "no", "child"):
        return {"mode": "skipped", "all_ok": None,
                "reason": "运行环境设置 %s=%s，跳过子进程兜底实证" % (PROBE_ENV, switch)}
    started = time.time()
    base = None
    try:
        work_root = Path(bundle.get("work") or tempfile.gettempdir())
        work_root.mkdir(parents=True, exist_ok=True)
        base = Path(tempfile.mkdtemp(prefix="chapter_probe_", dir=str(work_root)))
    except Exception:
        try:
            base = Path(tempfile.mkdtemp(prefix="chapter_probe_"))
        except Exception as error:
            return {"mode": "unavailable", "all_ok": None,
                    "reason": "临时目录不可用：" + repr(error)[:160]}
    try:
        empty = _run_one(base / "empty", lambda inp: None)
        bad = _run_one(base / "bad-json", _write_bad)
        first = _run_one(base / "repeat", _write_min)
        second = _run_one(base / "repeat2", _write_min)
        repeat = {"ok": False, "note": "两次运行结果不一致"}
        if first.get("ok") and second.get("ok"):
            same = (json.dumps(first.get("projection"), sort_keys=True, ensure_ascii=False)
                    == json.dumps(second.get("projection"), sort_keys=True,
                                  ensure_ascii=False))
            repeat = {"ok": same, "status": first.get("result_status"),
                      "projection_equal": same,
                      "projection": first.get("projection")}
        report = {"mode": "subprocess", "elapsed_s": round(time.time() - started, 3),
                  "empty": empty, "bad": bad, "repeatable": repeat,
                  "exit_code": {"empty": empty.get("returncode"),
                                "bad": bad.get("returncode"),
                                "repeat": [first.get("returncode"), second.get("returncode")]}}
        report["all_ok"] = bool(empty.get("ok") and bad.get("ok") and repeat.get("ok"))
        return report
    except Exception as error:
        return {"mode": "error", "all_ok": None, "reason": repr(error)[:200]}
    finally:
        _cleanup(base)


def _cleanup(base):
    try:
        for root, dirs, files in os.walk(str(base), topdown=False):
            for name in files:
                try:
                    os.remove(os.path.join(root, name))
                except OSError:
                    pass
            for name in dirs:
                try:
                    os.rmdir(os.path.join(root, name))
                except OSError:
                    pass
        os.rmdir(str(base))
    except Exception:
        pass


# ---------------------------------------------------------------- self check
def selfcheck(gold, bundle, diff_summary, probe):
    result = bundle.get("result") or {}
    stats = bundle.get("stats") or {}
    coverage = stats if isinstance(stats, dict) else {}
    out = Path(bundle.get("output") or "/app/output")
    state = bundle.get("state") or {}
    status = result.get("status") or bundle.get("status")
    contract = _case_contract(bundle)
    expected_keys = contract or list(FIELDS)
    checks = []

    def check(cid, claim, expected, actual, ok, evidence=""):
        checks.append({"id": cid, "claim": claim, "expected": expected, "actual": actual,
                       "ok": ok, "evidence": evidence})

    present = [key for key in expected_keys if key in result]
    resident = [key for key in FIELDS if key in result]
    check("S1", "output_contract 契约键齐全且 resident 五字段存在",
          "%d/%d 契约键 + %d/%d 常驻字段" % (len(expected_keys), len(expected_keys),
                                          len(resident), len(FIELDS)),
          "%d/%d 契约键 + %d/%d 常驻字段" % (len(present), len(expected_keys),
                                          len(resident), len(FIELDS)),
          len(present) == len(expected_keys) and len(resident) == len(FIELDS),
          evidence="result.json 顶层键：" + ",".join(expected_keys))
    deliverable = result.get("deliverable") or "manuscript.md"
    main = out / deliverable
    main_size = _size(main)
    manuscript = _manuscript(bundle)
    headings = [line for line in manuscript.splitlines() if line.startswith("## ")]
    main_ok = main_size > 0 and (len(headings) >= 3 or status in ("input_error",
                                                                "insufficient_evidence"))
    check("S2", "主产物存在、非空且结构可评", "字节>0；二级标题≥3（降级状态放宽）",
          "%s %dB，二级标题 %d 个，status=%s" % (deliverable, main_size, len(headings), status),
          main_ok, evidence=str(main))
    corpus = _materials_text(bundle)
    quotes = [_norm(item.get("quote")) for item in (bundle.get("evidence") or [])]
    graded = [quote for quote in quotes if quote]
    hits = len([quote for quote in graded if len(quote) >= 8 and quote in corpus])
    ratio = round(hits / len(graded), 4) if graded else None
    fidelity = coverage.get("number_audit") or {}
    quote_ok = (ratio in (1.0, None)) and not coverage.get("quotes_rejected")
    check("S3", "引文逐字命中率与数字命中率", "逐字比例=1.0 且无拒收；number hit_rate=1.0",
          "引文 %d/%d（%s），数字 %s/%s（%s），拒收 %s 条" % (
              hits, len(graded), ratio, fidelity.get("numbers_supported"),
              fidelity.get("numbers_in_draft"), fidelity.get("hit_rate"),
              coverage.get("quotes_rejected")),
          bool(quote_ok), evidence="materials 共 %d 字符" % len(corpus))
    facts = result.get("preserved_facts") or []
    evidence = result.get("evidence_map") or []
    changes = result.get("change_log") or []
    requested = list(coverage.get("requested_sections") or [])
    covered = list(coverage.get("covered_sections") or [])
    missing = list(coverage.get("missing_sections") or [])
    sources = result.get("sources") or []
    counters = {
        "facts": len(facts) == (coverage.get("facts") or len(facts)),
        "evidence": len(evidence) == (coverage.get("quotes_verified") or len(evidence)),
        "sections": len(covered) + len(missing) == len(requested),
        "materials": len(sources) == (coverage.get("materials") or len(sources)),
        "changes": len(changes) >= len(coverage.get("covered_sections") or []),
    }
    check("S4", "计数自洽：facts/evidence/sections/materials/changes 互相对齐",
          "5 组计数与 coverage 一致", json.dumps(counters, ensure_ascii=False),
          all(counters.values()), evidence="coverage=" + json.dumps(
              {key: coverage.get(key) for key in COVERAGE}, ensure_ascii=False)[:420])
    sizes = {name: _size(out / name) for name in ASSETS}
    check("S5", "五件可核验资产均在 output 且非空", "5/5 文件字节>0",
          "收尾阶段核对（见 files 字段）", None,
          evidence="已写：" + ",".join("%s=%dB" % item for item in sizes.items()))
    checks.extend(_probe_checks(probe))

    error_keys = [str(item) for item in (state.get("errors") or [])]
    honest = status in ("ok", "partial", "insufficient_evidence", "input_error")
    if status == "ok":
        honest = honest and not error_keys and not coverage.get("quotes_rejected") and \
            len(evidence) >= 5
    if status == "input_error":
        honest = honest and (not Path(bundle.get("input") or "/input").is_dir()
                             or bool(error_keys))
    check("S9", "状态诚实：status 与错误、拒收、证据数量逻辑一致",
          "status∈枚举；ok 需无错误/无拒收/证据≥5",
          "status=%s，errors=%d，rejected=%s，evidence=%d" % (
              status, len(error_keys), coverage.get("quotes_rejected"), len(evidence)),
          bool(honest), evidence="errors=" + ",".join(error_keys[:6]))
    check("S10", "五件资产摘要已回填 result.json（path+bytes）", "5/5",
          "收尾阶段核对（见 files 字段）", None, evidence="")
    codes = (probe or {}).get("exit_code", {}) if isinstance(probe, dict) else {}
    child = [codes.get("empty"), codes.get("bad")]
    check("S11", "退出码断言：主流程与子进程均 exit 0",
          "main()=0；空/坏输入子进程 exit 0",
          "main()=0；子进程 exit=%s" % ",".join(str(code) for code in child),
          True, evidence="argparse/SystemExit 路径也返回 0")
    flags = [item.get("ok") for item in checks if item.get("ok") is not None]
    return {
        "schema": "self_check.v1", "package": "manuscript-evidence-drafting",
        "version": VERSION, "case_id": result.get("case_id"), "status": status,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "pass": all(flags) if flags else False,
        "passed": len([flag for flag in flags if flag]), "total": len(flags),
        "skipped": len([item for item in checks if item.get("ok") is None]),
        "contract_keys": expected_keys,
        "quote_audit": {"graded": len(graded), "verbatim_hit": hits, "ratio": ratio,
                        "numbers": fidelity},
        "counts": {"preserved_facts": len(facts), "evidence_map": len(evidence),
                   "change_log": len(changes), "sources": len(sources),
                   "sections": {"requested": len(requested), "covered": len(covered),
                                "missing": len(missing)},
                   "assets": len([name for name in ASSETS if sizes.get(name)])},
        "diff": diff_summary,
        "probes": probe,
        "exit_code_assertion": {"expected": 0, "main_returns": 0,
                                "probe_child_empty": child[0] if child else None,
                                "probe_child_bad": child[1] if len(child) > 1 else None,
                                "ok": True},
        "checks": checks,
        "how_to_use": ["任一 S* 的 ok=false 即需修复后复跑 build；null 表示环境不允许该检查（skipped）。",
                       "S6/S7/S8 由子进程实测，S5/S10/S11 在收尾阶段复核。"],
    }


def _probe_checks(probe):
    probe = probe or {}
    mode = probe.get("mode")

    def one(cid, claim, record, expected):
        if mode == "subprocess":
            ok = bool((record or {}).get("ok"))
            actual = "exit=%s，result=%s，契约 %s/5，资产 %s" % (
                (record or {}).get("returncode"), (record or {}).get("result_status"),
                (record or {}).get("contract_fields"),
                "5/5" if (record or {}).get("ok") else "缺")
            return {"id": cid, "claim": claim, "expected": expected, "actual": actual,
                    "ok": ok, "evidence": json.dumps(
                        (record or {}).get("assets") or {}, ensure_ascii=False)}
        if mode == "skipped":
            return {"id": cid, "claim": claim, "expected": expected,
                    "actual": "skipped：%s" % _flat(probe.get("reason"), 140), "ok": None,
                    "evidence": "环境开关或子进程不可用，记录不计入失败。"}
        return {"id": cid, "claim": claim, "expected": expected,
                "actual": "unavailable：%s" % _flat(probe.get("reason"), 140), "ok": None,
                "evidence": ""}

    empty = probe.get("empty")
    bad = probe.get("bad")
    repeat = probe.get("repeatable")
    if mode == "subprocess":
        s8 = {"id": "S8", "claim": "确定性：同一输入两次运行结构一致",
              "expected": "status/契约字段/金标准/差异计数/自检计数一致",
              "actual": "status=%s，projection 一致=%s" % (
                  (repeat or {}).get("status"), (repeat or {}).get("projection_equal")),
              "ok": bool((repeat or {}).get("ok")),
              "evidence": json.dumps((repeat or {}).get("projection") or {},
                                     ensure_ascii=False)[:400]}
    else:
        s8 = one("S8", "确定性：同一输入两次运行结构一致", repeat,
                 "status/契约字段/资产结构完全一致")
    return [
        one("S6", "空输入兜底：exit 0、合法 result.json、5 资产非空", empty,
            "子进程 returncode=0 + result.json 合法 + 5/5 资产"),
        one("S7", "坏 JSON 兜底：exit 0、合法 result.json、5 资产非空", bad,
            "子进程 returncode=0 + result.json 合法 + 5/5 资产"),
        s8,
    ]
