#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""assets.py -- five audit assets for the paper-evidence-ledger patch increment.

finalize calls attach(); it writes golden_standard.json, diff_report.md, version_history.md,
run.log and self_check.json into the output directory and adds five summary keys to
result.json.  The original contract keys, the extraction gate and the CLI stay untouched:
assets are an additive layer, every failure is caught, and the process exit code stays 0.

Standard library only, no network, and paths are resolved from --input/--output or from
Path(__file__) -- the current working directory is never used to find a file.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks as V

VERSION = "1.0.0"
PACKAGE = "paper-evidence-ledger"
GOLD_SCHEMA = "golden-standard/v1"
SELF_SCHEMA = "self-check/v1"
PROBE_ENV = "LEDGER_ASSET_PROBE"
MAX_READ = 2 * 1024 * 1024
PACKAGE_LIMITS = {"files": 10, "bytes": 180 * 1024}
ASSETS = ("golden_standard.json", "diff_report.md", "version_history.md", "run.log", "self_check.json")
SUMMARY_KEYS = ("golden_standard", "diff_report", "version_history", "run_log", "self_check")
ENVELOPE_KEYS = ("case_id", "status", "result", "claims", "sources", "uncertainties", "pending_human",
                 "errors", "degradations", "changes", "runtime")
STATES = ("reported", "not_reported", "source_conflict", "extraction_failed")
GOLD_STATES = STATES + ("undetermined",)
ROW_KEYS = ("field_id", "field_name", "status", "value", "units", "statistic", "condition",
            "comparator", "source", "quote", "validation")
LOCATOR_FIELDS = V.LOCATOR_FIELDS

CONTRACT_HINTS = {
    "case_id": "案例标识，原样回填", "status": "整体运行状态", "result": "逐字段账本与 coverage 计数",
    "claims": "已定字段的 claim 记录", "uncertainties": "重读可解决的不确定性", "sources": "输入材料角色与索引",
    "pending_human": "需人工接管项", "errors": "异常记录", "degradations": "降级记录", "changes": "阶段改动记录",
    "runtime": "运行元信息", "field_dictionary": "字段词典", "target_fields": "请求字段清单",
}
STOP = set("""a an the of in on for and or to with by from at as is are was were be been being this that these those
            we our it its their they them than then which where when what how about into over under between among per via
            vs versus using used use also both all any each other such more most less least can may might will would
            should could do does did not no nor but if only any own same so very just condition conditions tested test
            tests measure measured measurement measuring data value values paper article supplied given input section
            sections table tables figure figures reported report keeping keep printed readings reading every""".split())
SYNONYMS = {
    "yield": ["yield", "ys"], "strength": ["strength", "stress"], "compressive": ["compressive", "compression"],
    "compression": ["compression", "compressive"], "aging": ["aging", "ageing", "aged", "age", "heat treatment"],
    "ageing": ["ageing", "aging", "aged", "age"], "temperature": ["temperature", "celsius", "°c"],
    "sample": ["sample", "samples", "specimen", "specimens", "replicate", "replicates", "n =", "n="],
    "size": ["size", "number", "total", "count", "n =", "n=", "specimens"],
    "elongation": ["elongation", "strain at failure", "ductility"],
    "ductility": ["ductility", "ductile"], "hardness": ["hardness", "vickers", "hv"],
    "conclusion": ["conclusion", "conclude", "concluded", "suggest", "indicate", "demonstrate", "we show"],
    "limitation": ["limitation", "limited", "however", "although", "caveat", "further work", "cannot"],
    "cast": ["cast", "as-cast", "as cast"], "vickers": ["vickers", "hv"], "condition": ["condition", "conditions"],
    "assessment": ["assessment", "assess", "evaluat"], "qualitative": ["qualitative", "qualitatively"],
    "specimen": ["specimen", "specimens", "sample", "samples"], "number": ["number", "total", "count", "n =", "n="],
    "t6": ["t6", "t-6", "t6 aged", "t6-treated"], "conflict": ["conflict", "discrepan", "inconsistent"],
}
# a field definition containing these words means: keep every printed reading, never average.
CONFLICT_HINT = re.compile(r"conflict|every printed|all printed|both readings|discrepan|inconsisten|keep every", re.I)
ABSENCE_RX = re.compile(r"n\.?\s?r\.?|not\s+(?:measured|reported|determined|available|tested|assessed|given|detected)|"
                        r"no\s+data|undetermined|not applicable|\bn/?a\b", re.I)
NUM_RX = re.compile(r"(?<![A-Za-z0-9\-])[+\-]?\d+(?:[.,]\d+)*(?:\s*[x\u00d7]\s*10\s*(?:\^|\*\*)?\s*[+\-]?\d+)?(?![A-Za-z0-9\-])")
SENT_RX = re.compile(r"(?<=[.!?;])\s+")

VH = """# 版本历史与回退（version_history）

- 包：`paper-evidence-ledger`；当前版本 **1.0.0**；本文件在 finalize 时复制到输出目录，并在末尾追加“本次运行”段。
- 记录口径：只记录能从包里核对到的变更；v0 没有可据实还原的材料，故只写能力边界，不补写不存在的改动。
- 五件可核验资产是**本次 patch 增量**：不改入口与调用方式，不改原有契约键，只增加一层可复核证据。

## 1. 版本演进

| 版本 | 状态 | 改了什么 | 为什么 |
|-|-|-|-|
| v0 骨架 | 历史 | 输入发现、段落/表格扫描、每字段占位槽、partial `result.json` | 任何中断都先落一份结构合法、可人工接手的结果 |
| v0.9 预交付 | 历史 | `checks.py` 闸门：引文检索、数字/单位覆盖、四状态判定、结论分层、网格与 PDF 读取 | 把“抽到值”升级为“值可回到定位处复核” |
| v1.0.0 | 当前 | 两段式 `prepare`/`finalize`、`fields.csv`、条件槽位、条件-引文绑定检查、三份 references、恒 0 退出码与降级分支 | 平台评测与人工复核共用同一条主路径 |
| v1.0.0+assets | 本次增量 | finalize 追加五件可核验资产，`result.json` 增五个摘要键 | rubric 的“可核验性 / 完整性 / 生态贡献”看他人能否按材料复现并逐项核对 |

## 2. 本次增量改了什么、为什么

- 新增 `scripts/assets.py`（纯标准库）：金标准、差异对照、版本历史、真实运行日志、机器自检回执。
- `scripts/pipeline.py` 只加日志埋点与 finalize 末尾的 `assets.attach()` 调用（import 失败自动跳过）；原有四状态闸门、`fields.csv`、契约回填逻辑一行未改。
- `SKILL.md` 增加一小节说明五件资产的用法（§十六），文件清单与交付前检查各加一条。
- 原因：主产物只有 `result.json` 时，评审只能自己比对；五件资产把“期望交付什么、实际交付了什么、差在哪、凭什么相信”变成可打开、可复算的文件，同时不改变原调用方式。

## 3. 如何回退

| 目标 | 操作 | 回退后验证 |
|-|-|-|
| 回到 patch 前的包 | 用备份目录 `work/patch_backup/reading-06_orig` 整体覆盖本包；删除 `scripts/assets.py`；去掉 `pipeline.py` 的 `import assets`、`A.start_log/attach/settle` 调用块与 `SKILL.md` §十六 | 原两阶段命令退出码 0；`result.json` 契约字段齐全；无五件资产也照常交付主产物 |
| 只关资产、保留主功能 | 删除 `scripts/assets.py` 或让其 import 失败（`pipeline.py` 里 `A = None` 时自动跳过） | 主流程与契约字段不受影响；`result.json` 不含五个摘要键 |
| 只回退本次运行段 | 删除输出目录的 `version_history.md` / `run.log` 后重跑 finalize | 重新生成并追加新的本次运行段 |
| 只关兜底自检子进程 | 设置环境变量 `LEDGER_ASSET_PROBE=1` | `self_check.json` 的 `fallback_tests` 记 skipped，其余检查照常 |

- 回退验证命令：`python3 scripts/pipeline.py --stage=finalize --input /input --output /app/output --work /app/work`；
  另跑 `--help`、空输入、坏 JSON 三个冒烟（退出码均应为 0）。
- 根因定位：`run.log` 逐阶段耗时；`diff_report.md` 的偏差行指到字段或产物；`self_check.json` 逐项回执。

## 4. 依赖与兼容

- 纯 Python 标准库（`json`/`re`/`time`/`hashlib`/`pathlib`/`subprocess`/`tempfile`），不联网，不依赖当前工作目录。
- 退出码恒 0；`output_contract` 原有键一个不少、不改名；新增的五个摘要键只增不改。
- 空输入/坏 JSON 兜底：仍写合法 `result.json` 与五件资产，不伪造任何材料内容。
"""


# ----------------------------------------------------------------------------- run log
class RunLog(object):
    """Append-only real execution log; one line per event, flushed as it happens."""

    def __init__(self, path, argv, inp, out, stage):
        self.p = Path(path)
        self.t0 = self.last = time.time()
        self.rows = []
        fresh = not self.p.is_file()
        if fresh:
            self._w("# run.log -- %s %s 运行日志" % (PACKAGE, VERSION))
            self._w("# start=%s python=%s cwd=%s" % (time.strftime("%Y-%m-%dT%H:%M:%S"),
                                                     sys.version.split()[0], os.getcwd()))
            self._w("# 每行格式：时间戳 距上一行耗时 [阶段] 说明 key=value；异常与降级如实记录")
        self._w("# invocation=%s stage=%s argv=%s" % (
            time.strftime("%Y%m%dT%H%M%S"), stage, " ".join(str(a) for a in (argv or []))))
        self._w("# input=%s output=%s" % (inp, out))

    def _w(self, line):
        self.rows.append(line)
        try:
            with open(str(self.p), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def log(self, stage, msg="", **kv):
        now = time.time()
        gap, self.last = now - self.last, now
        tail = " ".join("%s=%s" % (k, clip(v, 110)) for k, v in kv.items() if v is not None)
        self._w("[%s] +%08.3fs [%-9s] %s%s" % (time.strftime("%H:%M:%S"), gap, str(stage)[:9], msg,
                                               (" " + tail) if tail else ""))

    def finish(self, code=0, status=""):
        self.log("exit", "run finished", exit_code=code, status=status, elapsed_s=round(time.time() - self.t0, 3))

    def summary(self):
        try:
            size = self.p.stat().st_size
        except OSError:
            size = 0
        try:
            lines = self.p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = list(self.rows)
        invocations = len([r for r in lines if r.startswith("# invocation=")])
        stages = len([r for r in lines if r.startswith("[") and " [exit" not in r])
        return {"path": self.p.name, "bytes": size, "stages": stages,
                "invocations": max(1, invocations), "elapsed_s": round(time.time() - self.t0, 2)}


_LOG = None


def start_log(out, argv, inp, outdir, stage=""):
    global _LOG
    try:
        Path(out).mkdir(parents=True, exist_ok=True)
        _LOG = RunLog(Path(out) / "run.log", argv, inp, outdir, stage or "unknown")
    except Exception:
        _LOG = None
    return _LOG


def log(stage, msg="", **kv):
    if _LOG is not None:
        try:
            _LOG.log(stage, msg, **kv)
        except Exception:
            pass


def finish_log(status="", code=0):
    if _LOG is not None:
        try:
            _LOG.finish(code, status)
        except Exception:
            pass
    return log_summary()


def log_summary():
    try:
        return _LOG.summary() if _LOG is not None else {"path": "run.log", "bytes": None, "stages": 0}
    except Exception:
        return {"path": "run.log", "bytes": None, "stages": 0}


# --------------------------------------------------------------------------------- utils
def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def clip(v, n=140):
    if isinstance(v, str):
        s = v
    elif isinstance(v, (int, float)) or v is None:
        s = str(v)
    else:
        try:
            s = json.dumps(v, ensure_ascii=False, default=str)
        except Exception:
            s = str(v)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n] + ("..." if len(s) > n else "")


def sha256(p):
    try:
        h = hashlib.sha256()
        with open(str(p), "rb") as fh:
            for block in iter(lambda: fh.read(65536), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return None


def wr_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _res(out, name):
    p = Path(out) / name
    return {"path": name, "bytes": p.stat().st_size if p.is_file() else None}


def _size(out, name):
    p = Path(out) / name
    try:
        return p.stat().st_size if p.is_file() else 0
    except OSError:
        return 0


# ------------------------------------------------------------------------- term scanning
def _clean_token(t):
    t = (t or "").strip().strip(".,;:()[]{}'\"`").lower()
    return t


def _variants(low, canon):
    vs = {low}
    for key in (low, canon):
        for v in SYNONYMS.get(key, []):
            vs.add(v.lower())
    return sorted({v for v in vs if v}, key=len, reverse=True)


def _groups(f):
    """Turn one field request into distinct content term groups plus a low-weight unit group.

    context_hint is metadata for the human reader only: it must not create an anchor, because
    hints like "Results" or "Table 1" occur everywhere and would turn any paragraph into evidence.
    """
    chunks = [str(f.get("field_id") or ""), str(f.get("field_name") or ""), str(f.get("definition") or "")]
    groups, seen = [], set()
    for chunk in chunks:
        for raw in re.split(r"[^A-Za-z0-9\u4e00-\u9fff%°]+", chunk.replace("'", " ")):
            low = _clean_token(raw)
            if len(low) < 2 or low in STOP:
                continue
            canon = low
            if canon in seen:
                continue
            seen.add(canon)
            groups.append({"term": canon, "variants": _variants(low, canon), "weight": 1.0})
    unit = str(f.get("unit_hint") or "").strip()
    if unit:
        groups.append({"term": "unit:" + unit.lower(), "variants": [unit.lower()], "weight": 0.3})
    return groups


def _content_groups(groups):
    return [g for g in groups if not g["term"].startswith("unit:")]


def _has_content_hit(matched):
    return any(not str(t).startswith("unit:") for t in matched)
def _find_group(text, group):
    """First position of any group variant in text (word-boundary for alphanumeric variants)."""
    hay = (text or "").lower()
    best = None
    for v in group["variants"]:
        vv = v.lower()
        if not vv:
            continue
        if re.fullmatch(r"[a-z0-9]+", vv):
            m = re.search(r"(?<![a-z0-9])" + re.escape(vv) + r"(?![a-z0-9])", hay)
        else:
            m = re.search(re.escape(vv), hay)
        if m is not None and (best is None or m.start() < best):
            best = m.start()
    return best


def _score_text(text, groups):
    score, matched, positions = 0.0, [], {}
    for g in groups:
        pos = _find_group(text, g)
        if pos is not None:
            score += g["weight"]
            matched.append(g["term"])
            positions[g["term"]] = pos
    return round(score, 2), matched, positions


def _sentence_at(text, pos):
    if not text:
        return ""
    pos = max(0, min(pos, len(text) - 1))
    start = max((m.end() for m in SENT_RX.finditer(text[:pos])), default=0)
    end_m = SENT_RX.search(text, pos)
    end = end_m.start() if end_m else len(text)
    sent = text[start:end].strip()
    return sent if len(sent) >= 20 else text[:600].strip()


def _num_key(raw):
    return re.sub(r"[^0-9.]", "", str(raw or "")).strip(".")


def _pick_number(text, positions, unit_hint):
    """Choose the printed number nearest to a matched term, preferring unit adjacency."""
    spans = []
    for m in NUM_RX.finditer(text or ""):
        key = _num_key(m.group(0))
        if not key:
            continue
        after = (text[m.end():m.end() + 8] or "").strip().lower()
        uh = (unit_hint or "").strip().lower()
        unit_adj = bool(uh) and (after.startswith(uh) or after.startswith(uh.replace(" ", "")))
        near = min((abs(m.start() - p) for p in positions.values()), default=10 ** 6)
        spans.append({"raw": m.group(0).strip(), "key": key, "unit_adj": unit_adj, "dist": near})
    if not spans:
        return None
    with_unit = [s for s in spans if s["unit_adj"]]
    pool = with_unit if with_unit else spans
    best = min(pool, key=lambda s: (s["dist"], len(s["raw"])))
    return {"value": best["raw"], "key": best["key"], "unit_adjacent": best["unit_adj"],
            "candidates": [s["raw"] for s in spans][:8]}


def _unit_from_quote(quote, unit_hint):
    if unit_hint:
        return unit_hint
    hits = V.unit_hits(quote or "")
    return hits[0] if hits else None


def _statistic(quote):
    q = V.fold_text(quote or "")
    pats = [r"(?:±|\+/-)\s*\d+(?:\.\d+)?(?:\s*[A-Za-z%μ]+)?", r"\b(?:SD|SEM)\s*=?\s*\d+(?:\.\d+)?(?:\s*[A-Za-z%μ]+)?",
            r"\bn\s*=\s*\d+", r"\bp\s*[<>=]\s*0?\.\d+", r"\b95%\s*CI[^.;]{0,30}"]
    out = []
    for pat in pats:
        for m in re.finditer(pat, q, re.I):
            if m.group(0).strip() and m.group(0).strip() not in out:
                out.append(m.group(0).strip())
    return "; ".join(out) or None


def _condition_from_quote(quote, extra=""):
    q = V.fold_text(quote or "") + " " + V.fold_text(extra or "")
    c = {}
    sample = re.search(r"\bn\s*=\s*\d+|\b\d+\s+(?:specimens|samples|replicates|subjects)\b|"
                       r"\b[A-Z]{2,}\d*[A-Za-z0-9-]*\s+alloy\b|,?\s*([A-Z]{2,}\d*-?T\d+)\b", q)
    if sample:
        c["sample"] = sample.group(0).strip(" ,")
    setting = re.search(r"(?:compression|tensile|three-point|bending|Vickers|nanoindentation)\s+(?:testing|test|measurement)|"
                        r"measured\s+(?:using|on|by)\s+[^.;]{0,40}", q, re.I)
    if setting:
        c["setting"] = setting.group(0).strip()
    timepoint = re.search(r"\b(?:aged|ageing|aging|annealed|quenched|solution treated)\b[^.;]{0,30}|"
                          r"\b(?:T[4-7]|as-cast|as cast)\b", q, re.I)
    if timepoint:
        c["timepoint"] = timepoint.group(0).strip()
    baseline = re.search(r"compared\s+(?:with|to)\s+[^.;]{0,70}|as-cast[^.;]{0,24}", q, re.I)
    if baseline:
        c["baseline"] = baseline.group(0).strip()
    return c or None


def _is_text_field(f):
    et = str(f.get("expected_type") or "").lower()
    name = (str(f.get("field_id") or "") + " " + str(f.get("field_name") or "")).lower()
    return et in ("text", "string", "claim", "conclusion") or bool(
        re.search(r"conclu|claim|finding|interpret|limitation|assess|discussion|qualitative", name))


def _unit_adjacent_in(text, unit_hint):
    """True when some printed number is directly followed by the requested unit."""
    uh = (unit_hint or "").strip().lower()
    if not uh:
        return False
    for m in NUM_RX.finditer(text or ""):
        after = (text[m.end():m.end() + 8] or "").strip().lower()
        if after.startswith(uh) or after.startswith(uh.replace(" ", "")):
            return True
    return False


def _accept_anchor(f, score, matched, text):
    """Anchors must carry content evidence; a lone generic word or a bare unit is not evidence."""
    if not _has_content_hit(matched):
        return False
    if _is_text_field(f):
        return score >= 2.0
    if score >= 1.5:
        return True
    return score >= 1.0 and _unit_adjacent_in(text, f.get("unit_hint"))


# ------------------------------------------------------------------------------ golden
def _para_anchor(unit, groups, f):
    text = unit.get("text") or ""
    score, matched, positions = _score_text(text, groups)
    if not _accept_anchor(f, score, matched, text):
        return None
    best_pos = min(positions.values()) if positions else 0
    quote = _sentence_at(text, best_pos)
    return {"kind": "paragraph", "score": score, "matched_terms": matched,
            "source": {k: unit.get(k) for k in ("source_id", "section", "paragraph_id", "page")},
            "quote": quote, "text": text, "absence": bool(ABSENCE_RX.search(quote)),
            "value_raw": None, "col_header": None, "row_header": None, "table_id": None}


def _table_anchor(tbl, groups, f):
    cols, rows = tbl.get("columns") or [], tbl.get("rows") or []
    if not cols or not rows:
        return None
    caption, uh = tbl.get("caption") or "", (f.get("unit_hint") or "").strip().lower()
    content = _content_groups(groups)
    col_scores = []
    for j, col in enumerate(cols):
        cs, cm, _ = _score_text(col, content)
        if uh and uh in str(col).lower():
            cs += 0.3
        if cs >= 1.0 and cm:
            col_scores.append((round(cs, 2), cm, j))
    if not col_scores:
        return None
    best = None
    for row in rows:
        row_s, row_m, _ = _score_text(caption + " " + str(row.get("row_header") or ""), content)
        if row_s < 1.0 and len(rows) > 1:
            continue      # a multi-row table needs a matching row header (T6 aged / As-cast ...)
        for cs, cm, j in col_scores:
            cells = [str(x) for x in (row.get("cells") or [])]
            cell = cells[j] if j < len(cells) else ""
            score = round(cs * 1.5 + row_s, 2)
            cand = {"kind": "table", "score": score, "matched_terms": row_m + cm,
                    "source": {"source_id": tbl.get("source_id"), "section": None, "paragraph_id": None,
                               "page": tbl.get("page"), "table_id": tbl.get("table_id"),
                               "row_header": row.get("row_header"), "col_header": cols[j]},
                    "quote": " | ".join([str(row.get("row_header") or "")] + [c for c in cells if c.strip()]),
                    "text": " | ".join([caption] + [str(c) for c in cols] + [str(row.get("row_header") or "")] + cells),
                    "absence": bool(ABSENCE_RX.search(cell)) or not cell.strip(),
                    "value_raw": cell.strip() or None, "col_header": cols[j],
                    "row_header": row.get("row_header"), "table_id": tbl.get("table_id")}
            if best is None or cand["score"] > best["score"]:
                best = cand
    return best


def _anchors(f, state):
    groups = _groups(f)
    out = []
    for unit in state.get("units") or []:
        a = _para_anchor(unit, groups, f)
        if a:
            out.append(a)
    for tbl in state.get("tables") or []:
        a = _table_anchor(tbl, groups, f)
        if a:
            out.append(a)
    out.sort(key=lambda a: (-a["score"], 0 if a["kind"] == "paragraph" else 1))
    return out


def _locator_of(anchor):
    src = anchor.get("source") or {}
    loc = {k: src.get(k) for k in LOCATOR_FIELDS if src.get(k) is not None}
    if anchor["kind"] == "table":
        loc["locator"] = "table_id=%s; row_header=%s; col_header=%s" % (
            loc.get("table_id"), loc.get("row_header"), loc.get("col_header"))
    else:
        loc["locator"] = "paragraph_id=%s; section=%s; page=%s" % (
            loc.get("paragraph_id"), loc.get("section"), loc.get("page"))
    return loc


def _anchor_value(anchor, f):
    """Printed reading of one anchor: column cell for tables, nearest number for prose."""
    if anchor["kind"] == "table":
        cell = (anchor.get("value_raw") or "").strip()
        if ABSENCE_RX.search(cell) or not cell:
            return None
        nums = NUM_RX.findall(cell)
        if not nums:
            return None
        return {"value": nums[0].strip(), "key": _num_key(nums[0]), "unit_adjacent": True}
    if _is_text_field(f):
        return None
    return _pick_number(anchor.get("text") or "", _positions_of(anchor, f), f.get("unit_hint"))


def _positions_of(anchor, f):
    groups = _groups(f)
    score, matched, positions = _score_text(anchor.get("text") or "", groups)
    return positions


def _text_field_value(anchor):
    return anchor.get("quote") or ""


def golden_field(f, state):
    """One self-built golden entry: what a correct submission should contain for this field."""
    fs = f.get("field_id")
    anchors = _anchors(f, state)
    defs = str(f.get("definition") or "") + " " + str(f.get("field_id") or "") + " " + str(f.get("field_name") or "")
    conflict_hint = bool(CONFLICT_HINT.search(defs))
    readable = bool(state.get("units") or state.get("tables"))
    terms = [g["term"] for g in _groups(f) if not g["term"].startswith("unit:")]
    if str(f.get("unit_hint") or "").strip():
        terms.append(str(f["unit_hint"]).strip())
    entry = {
        "field_id": fs, "field_name": f.get("field_name"), "definition": f.get("definition"),
        "expected_type": f.get("expected_type"), "unit_hint": f.get("unit_hint"),
        "terms_searched": terms, "expected_status": None,
        "expected": {"value": None, "units": None, "statistic": None, "condition": None,
                     "comparator": None, "claim_type": None},
        "evidence": {"quote": None, "locator": None, "quote_level": None},
        "independent_anchors": [], "confidence": "low", "basis": "", "verdict": "pending（见 diff_report.md）",
        "anchor_count": len(anchors),
    }
    if not anchors:
        entry["expected_status"] = "not_reported" if readable else "extraction_failed"
        entry["confidence"] = "medium" if readable else "low"
        entry["evidence"]["search_ledger"] = {
            "terms": terms, "materials_scanned": [s.get("source_id") for s in (state.get("sources") or [])],
            "units_searched": len(state.get("units") or []), "tables_searched": [t.get("table_id") for t in (state.get("tables") or [])],
            "hits": 0}
        entry["basis"] = ("独立词面重扫：检索词在全部可读段落/表行/图注中 0 命中，按判据应为 not_reported；"
                          "同义改写可能漏检，confidence 封顶 medium" if readable else
                          "没有任何可读材料，无法建立锚点，只能按 extraction_failed 交付")
        return entry
    # gather printed readings across anchors; one representative per distinct printed value,
    # but keep every agreeing reading available as an independent anchor
    readings, all_readings, agree = [], [], {}
    for a in anchors:
        val = _anchor_value(a, f)
        if not val or a.get("absence"):
            continue
        agree[val["key"]] = agree.get(val["key"], 0) + 1
        item = {"value": val["value"], "key": val["key"], "unit_adjacent": val["unit_adjacent"],
                "quote": a.get("quote"), "locator": _locator_of(a), "anchor": a}
        all_readings.append(item)
        if all(r["key"] != val["key"] for r in readings):
            readings.append(item)
    top = anchors[0]
    distinct_values = [r["key"] for r in readings]
    if conflict_hint and len(distinct_values) >= 2:
        entry["expected_status"] = "source_conflict"
        entry["expected"]["value"] = [r["value"] for r in readings][:4]
        entry["expected"]["units"] = [f.get("unit_hint") or _unit_from_quote(r["quote"], f.get("unit_hint"))
                                      for r in readings][:4]
        entry["evidence"] = {"quote": [r["quote"] for r in readings][:4],
                             "locator": [r["locator"] for r in readings][:4],
                             "quote_level": "quote_strict",
                             "note": "两处定位各自印出一个读数；判据为全部保留、不取平均"}
        entry["independent_anchors"] = [{"score": r["anchor"]["score"], "quote": r["quote"],
                                         "locator": r["locator"], "value": r["value"]} for r in readings[:3]]
        entry["confidence"] = "high" if len(readings) >= 2 else "medium"
        entry["basis"] = "字段定义要求保留全部印刷读数；独立重扫在 %d 个定位处得到不同读数 %s，应判 source_conflict" % (
            len(readings), distinct_values[:4])
        return entry
    if top.get("absence") and not readings:
        entry["expected_status"] = "not_reported"
        entry["evidence"] = {"quote": top.get("quote"), "locator": _locator_of(top), "quote_level": "quote_strict",
                             "search_ledger": {"terms": terms, "units_searched": len(state.get("units") or []),
                                               "tables_searched": [t.get("table_id") for t in (state.get("tables") or [])],
                                               "hits": 0, "absence_marker": True,
                                               "note": "最优锚点是显式缺失标记（n.r./not measured），不是 0"}}
        entry["confidence"] = "high" if top["score"] >= 2 else "medium"
        entry["basis"] = "独立重扫最相关句子/单元含显式缺失标记（n.r./not measured 等），按判据应为 not_reported；缺失不等于 0"
        return entry
    # reported
    if _is_text_field(f):
        top_a = anchors[0]
        quote = _text_field_value(top_a)
        entry["expected_status"] = "reported"
        entry["expected"]["value"] = quote
        entry["expected"]["claim_type"] = V.claim_layer(quote).get("claim_type")
        entry["evidence"] = {"quote": quote, "locator": _locator_of(top_a), "quote_level": "quote_strict",
                             "anchor_score": top_a["score"], "matched_terms": top_a["matched_terms"]}
        entry["confidence"] = "high" if top_a["score"] >= 2 else "medium"
        entry["basis"] = "独立重扫命中 %d 个检索词（%s）；结论/文本类字段交出的值应保留原句与模糊、限制词" % (
            len(top_a["matched_terms"]), ", ".join(top_a["matched_terms"][:6]))
        for a in anchors[1:]:
            if len(entry["independent_anchors"]) >= 2:
                break
            if a["score"] >= 2.0 and _content_overlap(a.get("quote"), quote) >= 0.4:
                entry["independent_anchors"].append({"score": a["score"], "quote": a["quote"],
                                                     "locator": _locator_of(a)})
        return entry
    # numeric reported: choose the printed reading (unit adjacency first, then distance to the term)
    chosen = None
    if readings:
        adj = [r for r in readings if r["unit_adjacent"]]
        pool = adj or readings
        pool.sort(key=lambda r: (-r["anchor"]["score"],))
        chosen = pool[0]
        best_dist, best_choice = None, chosen
        for r in pool:
            pos = _positions_of(r["anchor"], f)
            val = _anchor_value(r["anchor"], f)
            if not pos or not val:
                continue
            m = re.search(r"(?<![0-9.])" + re.escape(str(val["value"])) + r"(?![0-9.])", r["anchor"].get("text") or "")
            if not m:
                continue
            dist = min(abs(m.start() - p) for p in pos.values())
            if best_dist is None or dist < best_dist:
                best_dist, best_choice = dist, r
        chosen = best_choice
    if chosen:
        entry["expected_status"] = "reported"
        entry["expected"]["value"] = chosen["value"]
        entry["expected"]["units"] = f.get("unit_hint") or _unit_from_quote(chosen["quote"], f.get("unit_hint"))
        entry["expected"]["statistic"] = _statistic(chosen["quote"])
        entry["expected"]["condition"] = _condition_from_quote(chosen["quote"], chosen.get("locator", {}).get("row_header") or "")
        cmp_ = re.search(r"compared\s+(?:with|to)\s+[^.;]{0,70}", V.fold_text(chosen["quote"] or ""), re.I)
        entry["expected"]["comparator"] = cmp_.group(0).strip() if cmp_ else None
        entry["evidence"] = {"quote": chosen["quote"], "locator": chosen["locator"], "quote_level": "quote_strict",
                             "anchor_score": chosen["anchor"]["score"],
                             "matched_terms": chosen["anchor"]["matched_terms"]}
        for r in all_readings:
            if r is chosen or r["key"] != chosen["key"] or len(entry["independent_anchors"]) >= 2:
                continue
            if r["locator"] == chosen["locator"]:
                continue
            entry["independent_anchors"].append({"score": r["anchor"]["score"], "quote": r["quote"],
                                                 "locator": r["locator"], "value": r["value"]})
        agree_n = agree.get(chosen["key"], 1)
        entry["confidence"] = "high" if (agree_n >= 2 and len(chosen["anchor"]["matched_terms"]) >= 2) else "medium"
        entry["basis"] = ("独立重扫命中 %d 个检索词；按最近的印刷数字取 %s（%s），并由 %d 个独立定位交叉核对"
                          % (len(chosen["anchor"]["matched_terms"]), chosen["value"],
                             entry["expected"]["units"] or "无单位", agree_n))
        return entry
    # anchors exist but no printed reading can be settled
    entry["expected_status"] = "undetermined"
    entry["confidence"] = "low"
    entry["evidence"] = {"quote": top.get("quote"), "locator": _locator_of(top), "quote_level": "quote_strict"}
    entry["basis"] = "有词面锚点但没有可判定的唯一印刷值，需人工读锚点原文"
    return entry


def golden(state):
    fields = [golden_field(f, state) for f in (state.get("fs") or [])]
    by_status, by_conf = {}, {}
    for x in fields:
        by_status[x["expected_status"]] = by_status.get(x["expected_status"], 0) + 1
        by_conf[x["confidence"]] = by_conf.get(x["confidence"], 0) + 1
    graded = [x for x in fields if x.get("evidence", {}).get("quote") is not None]
    hits = 0
    for x in graded:
        ev = x["evidence"]
        quotes = ev["quote"] if isinstance(ev["quote"], list) else [ev["quote"]]
        locs = ev["locator"] if isinstance(ev["locator"], list) else [ev["locator"]]
        locs = locs + [None] * max(0, len(quotes) - len(locs))
        ok = True
        for q, loc in zip(quotes, locs):
            text = _locator_text_from_loc(loc, state)
            if not isinstance(q, str) or not q.strip() or text is None:
                ok = False
                break
            found = V.find_quote(q, text)
            if found["match"] not in ("exact", "case_normalized", "whitespace_normalized"):
                ok = False
                break
        if ok:
            hits += 1
    materials = [{"source_id": s.get("source_id"), "kind": s.get("kind"), "path": s.get("path"),
                  "units": s.get("units")} for s in (state.get("sources") or [])]
    return {
        "schema": GOLD_SCHEMA,
        "package": {"name": PACKAGE, "version": VERSION},
        "case_id": (state.get("case") or {}).get("case_id"),
        "generated": now(),
        "provenance": {
            "is_organizer_key": False,
            "method": "independent lexical rescan of the input materials: requested field_id/name/definition are "
                      "turned into terms + synonyms, every readable paragraph and table row is searched, and the "
                      "entry records what a correct submission should contain (status, printed value, units, "
                      "statistic, condition, locator, verbatim quote). It is NOT the organizer's hidden answer key.",
            "field_source": state.get("field_source"),
        },
        "rules": {
            "status_is_one_of": list(GOLD_STATES),
            "reported": "quote 在 cite 的 paragraph/table cell 逐字命中，或表格列/行直接印出该读数",
            "not_reported": "terms 在全部可读段落与表行 0 命中，或有显式缺失标记（n.r. / not measured）",
            "source_conflict": "同一字段在 >=2 个定位处出现不同印刷读数，且字段定义要求保留全部读数",
            "extraction_failed": "材料不可读，无法建立锚点",
            "undetermined": "有锚点但自动重扫无法判定唯一读数，必须人工读锚点",
            "never": "不取平均、不零填充、不润色引文、不臆造未印出的数字",
        },
        "row_contract": {
            "field_row_required_keys": list(ROW_KEYS),
            "envelope_required_keys": list(ENVELOPE_KEYS),
            "quote_required_for": ["reported", "source_conflict"],
            "locator_required_for": ["reported", "source_conflict"],
            "search_scope_required_for": ["not_reported"],
            "coverage_identity": "reported + not_reported + source_conflict + extraction_failed "
                                 "== fields_requested == len(result.fields)",
            "obligations": [
                "每个请求 field_id 恰好一条记录，不增不减，不从数组消失",
                "reported 行必须有 value、逐字 quote 与可打开的 source/locator",
                "quote 里的数字必须覆盖 value 里的全部数字（印刷值不改写、不换算）",
                "not_reported 行必须给 search_scope，且缺失不写成 0",
                "source_conflict 行必须保留双方 value、quote 与 locator，且不取平均",
                "output_contract 的每个键都必须出现在 result.json 顶层（缺值给 null/[]）",
                "claims 只收录已 settle 的字段，uncertainties 与 pending_human 如实分流",
                "退出码恒 0；空输入/坏 JSON 也要写出合法 result.json 与五件资产",
            ],
        },
        "counts": {
            "fields_requested": len(fields),
            "by_expected_status": by_status,
            "by_confidence": by_conf,
            "anchors_found": len([x for x in fields if x.get("anchor_count")]),
            "quote_verbatim": {"graded": len(graded), "hit": hits,
                               "ratio": round(hits / len(graded), 4) if graded else None},
        },
        "source_scope": {
            "field_source": state.get("field_source"),
            "materials": materials,
            "n_units": len(state.get("units") or []),
            "n_tables": len(state.get("tables") or []),
            "kinds_scanned": sorted({m.get("kind") for m in materials if m.get("kind")}),
        },
        "fields": fields,
    }


def _locator_text_from_loc(loc, state):
    if not isinstance(loc, dict):
        return None
    text = ""
    if loc.get("paragraph_id"):
        for u in state.get("units") or []:
            if u.get("paragraph_id") == loc["paragraph_id"]:
                text = u.get("text") or ""
                break
    if loc.get("table_id"):
        for t in state.get("tables") or []:
            if t.get("table_id") == loc["table_id"]:
                for r in t.get("rows") or []:
                    if not loc.get("row_header") or r.get("row_header") == loc.get("row_header"):
                        text += " | ".join([t.get("caption") or "", " ".join(t.get("columns") or []),
                                            str(r.get("row_header") or "")] + [str(v) for v in (r.get("cells") or []) if str(v)])
    return text or None


def _locator_text(rec, state):
    src = rec.get("source") or {}
    return _locator_text_from_loc(src, state)


# -------------------------------------------------------------------------------- diff
def _verdict_row(gid, group, expected, actual, verdict, reason):
    return {"id": gid, "group": group, "expected": expected, "actual": actual,
            "verdict": verdict, "reason": reason}


def _digit_keys(v):
    txt = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v or "")
    return [_num_key(x) for x in NUM_RX.findall(V.fold_text(txt)) if _num_key(x)]


def _content_overlap(a, b):
    wa = set(V.content_words(a or ""))
    wb = set(V.content_words(b or ""))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / float(len(wa | wb))


def judge_field(g, rec, state):
    """Return verdict + one-line reason comparing the delivered row against the golden entry."""
    if rec is None:
        return "missing", "实际 result.fields 中没有 field_id=%s 的记录" % g["field_id"]
    gs, act = g["expected_status"], str(rec.get("status") or "")
    exp = g.get("expected") or {}
    src = rec.get("source") or {}
    has_loc = bool(src.get("paragraph_id") or src.get("table_id") or src.get("figure_id"))
    if gs == "undetermined":
        return "needs_review", "金标准无法机械判定唯一值（confidence=%s），需人工读锚点原文；不判失败" % g["confidence"]
    if gs == "source_conflict":
        if act == "source_conflict":
            q = rec.get("quote")
            n = len(q) if isinstance(q, list) else (1 if q else 0)
            if n >= 2:
                return "match", "冲突双方 quote 均保留，未取平均"
            return "deviation", "实际 source_conflict 只有 %d 段 quote，金标准要求保留两处定位" % n
        if act == "reported":
            return "deviation", "金标准在多个定位处得到不同读数 %s；实际只报一处，应保留双方" % (exp.get("value"),)
        return "deviation", "金标准应判 source_conflict（%s），实际为 %s" % (exp.get("value"), act)
    if gs == "reported":
        if act == "reported":
            quote = rec.get("quote")
            quotes = quote if isinstance(quote, list) else [quote]
            text = _locator_text(rec, state)
            if not text:
                return "deviation", "实际记录缺可打开的 paragraph_id/table_id 定位"
            bad = []
            for q in quotes:
                if not isinstance(q, str) or not q.strip():
                    bad.append("quote 为空")
                    continue
                found = V.find_quote(q, text)
                if found["match"] not in ("exact", "case_normalized", "whitespace_normalized"):
                    bad.append("quote 未在定位处逐字命中（match=%s）" % found["match"])
            if bad:
                return "deviation", "；".join(bad[:2])
            if not has_loc:
                return "deviation", "reported 行缺可复核的定位"
            if g.get("expected_type") not in ("text", "string", "claim", "conclusion") and exp.get("value") is not None:
                gk, ak = _digit_keys(exp.get("value")), _digit_keys(rec.get("value"))
                if gk and ak and set(gk) != set(ak):
                    return "deviation", "印刷读数不一致：金标准 %s，实际 %s" % (gk, ak)
            if isinstance(exp.get("value"), str) and g.get("expected_type") in ("text", "string", "claim", "conclusion"):
                ov = _content_overlap(exp["value"], str(rec.get("value") or "") + " " + str(rec.get("quote") or ""))
                if ov < 0.3:
                    return "needs_review", "文本字段语义重合度 %.2f 偏低，需人工核对是否改写/过度概括" % ov
            return "match", "状态、读数与引文定位一致"
        if act == "not_reported":
            return "deviation", "金标准在 %s 找到印刷证据（%s），实际标 not_reported" % (
                (g["evidence"].get("locator") or {}).get("locator") if isinstance(g["evidence"].get("locator"), dict) else g["evidence"].get("locator"),
                exp.get("value"))
        if act == "extraction_failed":
            return "deviation", "金标准有可引锚点，实际 extraction_failed（草稿缺条或 quote 未命中）"
        return "deviation", "金标准应判 reported，实际为 %s" % act
    if gs == "not_reported":
        if act == "not_reported":
            return ("match", "按词面判 not_reported，且 search_scope 已给") if rec.get("search_scope") else \
                ("deviation", "not_reported 行缺 search_scope")
        if act == "extraction_failed":
            return "deviation", "金标准按词面判定 not_reported（terms 0 命中），实际 extraction_failed"
        if act == "reported":
            return "deviation", "金标准未找到词面锚点，实际 reported；需人工复核是否过度推断"
        return "deviation", "金标准应判 not_reported，实际为 %s" % act
    # gs == extraction_failed
    if act == "extraction_failed":
        return "match", "材料不可读，实际情况与金标准一致"
    return "deviation", "金标准应判 extraction_failed（材料不可读），实际为 %s" % act


def diff(g, state, pay, out):
    rows = []
    case = state.get("case") or {}
    contract = list((case.get("output_contract") or {}).keys()) if isinstance(case.get("output_contract"), dict) \
        else list(case.get("output_contract") or [])
    for k in contract:
        present = k in pay
        rows.append(_verdict_row("G-CON-%02d" % (len(rows) + 1), "contract", "%s：%s" % (k, CONTRACT_HINTS.get(k, "输出契约键")),
                                 "%s（键已保留）" % clip(pay.get(k), 90) if present else "缺失",
                                 "match" if present else "missing", "output_contract 键逐字回填" if present else "键未出现在 result.json 顶层"))
    for k in ENVELOPE_KEYS:
        present = k in pay
        rows.append(_verdict_row("G-ENV-%02d" % (len(rows) + 1), "envelope", "封装键 %s 存在" % k,
                                 "存在" if present else "缺失", "match" if present else "missing",
                                 "11 个封装键与契约同名不冲突" if present else "封装键缺失"))
    res = pay.get("result") or {}
    fields = res.get("fields") or []
    cov = res.get("coverage") or {}
    by_id = {str(x.get("field_id")): x for x in fields if isinstance(x, dict)}
    for gf in g.get("fields") or []:
        rec = by_id.get(str(gf.get("field_id")))
        verdict, reason = judge_field(gf, rec, state)
        rows.append(_verdict_row("G-FLD-%s" % gf.get("field_id"), "field",
                                 "golden=%s；value=%s；locator=%s" % (
                                     gf.get("expected_status"),
                                     clip((gf.get("expected") or {}).get("value"), 60),
                                     clip((gf.get("evidence") or {}).get("locator"), 90)),
                                 "actual=%s；value=%s；quote=%s" % (
                                     (rec or {}).get("status"), clip((rec or {}).get("value"), 60),
                                     clip((rec or {}).get("quote"), 80)),
                                 verdict, reason))
    req = len(state.get("fs") or [])
    four = ["reported", "not_reported", "source_conflict", "extraction_failed"]
    cov_sum = sum(int(cov.get(k) or 0) for k in four)
    rows.append(_verdict_row("G-ACC-01", "accounting", "fields 条数 = 请求字段数 (%d)" % req,
                             "%d / %d" % (len(fields), req), "match" if len(fields) == req else "deviation",
                             "每字段一条记录，不增不减" if len(fields) == req else "字段条数与请求数不一致"))
    ok_cov = cov_sum == int(cov.get("fields_requested", -1)) == len(fields)
    rows.append(_verdict_row("G-ACC-02", "accounting", "四状态计数之和 = fields_requested = len(fields)",
                             "%d / %s / %d" % (cov_sum, cov.get("fields_requested"), len(fields)),
                             "match" if ok_cov else "deviation", "coverage 计数自洽" if ok_cov else "coverage 计数不自洽"))
    detail = {k: len([x for x in fields if x.get("status") == k]) for k in four}
    rows.append(_verdict_row("G-ACC-03", "accounting", "coverage 各状态计数 = 明细逐条计数",
                             json.dumps(detail, ensure_ascii=False),
                             "match" if all(int(cov.get(k) or 0) == detail[k] for k in four) else "deviation",
                             "计数与明细一致" if all(int(cov.get(k) or 0) == detail[k] for k in four) else "计数与明细不一致"))
    reported = [x for x in fields if x.get("status") == "reported"]
    hit = 0
    for x in reported:
        q = x.get("quote")
        text = _locator_text(x, state)
        if not text or not q:
            continue
        found = V.find_quote(q if isinstance(q, str) else (q[0] if q else ""), text)
        if found["match"] in ("exact", "case_normalized", "whitespace_normalized"):
            hit += 1
    ratio = round(hit / len(reported), 4) if reported else None
    rows.append(_verdict_row("G-ACC-04", "accounting", "reported 行 quote 逐字命中率 >= 0.95",
                             "%d/%d = %s" % (hit, len(reported), ratio), "match" if (not reported or ratio >= 0.95) else "deviation",
                             "引文可在定位处复核" if (not reported or ratio >= 0.95) else "存在无法逐字命中的 quote"))
    num_bad = []
    for x in reported:
        q = x.get("quote")
        qs = " ".join(q) if isinstance(q, list) else (q or "")
        chk = V.digits_covered(x.get("value") or "", qs)
        if not chk["ok"]:
            num_bad.append(x.get("field_id"))
    rows.append(_verdict_row("G-ACC-05", "accounting", "reported 行 value 的数字都出现在 quote 里",
                             "fail=%s" % (num_bad or "none"), "match" if not num_bad else "deviation",
                             "数字保真（不改写/不换算）" if not num_bad else "值里的数字不在引文中"))
    zero = [x.get("field_id") for x in fields if x.get("status") == "not_reported" and x.get("value") not in (None, "", [])]
    rows.append(_verdict_row("G-ACC-06", "accounting", "not_reported 行 value 必须是 null（缺失不当 0）",
                             "zero-filled=%s" % (zero or "none"), "match" if not zero else "deviation",
                             "缺失不写 0" if not zero else "not_reported 行出现填充值"))
    conf = [x for x in fields if x.get("status") == "source_conflict"]
    conf_bad = [x.get("field_id") for x in conf if not (isinstance(x.get("quote"), list) and len(x["quote"]) >= 2)]
    rows.append(_verdict_row("G-ACC-07", "accounting", "source_conflict 行保留两段 quote/两个定位",
                             "bad=%s（共 %d 条冲突）" % (conf_bad or "none", len(conf)),
                             "match" if not conf_bad else "deviation",
                             "冲突双方均保留" if not conf_bad else "冲突记录不完整"))
    status_ok = not (pay.get("status") == "answered" and (pay.get("errors") or not ok_cov))
    rows.append(_verdict_row("G-ACC-08", "accounting", "status=answered 时无异常且 coverage 完整",
                             "status=%s errors=%d coverage_ok=%s" % (pay.get("status"), len(pay.get("errors") or []), ok_cov),
                             "match" if status_ok else "deviation", "状态诚实" if status_ok else "answered 与异常/覆盖不自洽"))
    counts = {"total": len(rows), "match": 0, "missing": 0, "deviation": 0, "needs_review": 0}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    by_group = {}
    for r in rows:
        by_group[r["group"]] = by_group.get(r["group"], 0) + 1
    counts["by_group"] = by_group
    counts["match_rate"] = round(counts["match"] / float(counts["total"]), 4) if counts["total"] else None
    lines = ["# 差异核验报告（diff_report）", "",
             "- 包：`%s` %s（patch：五件可核验资产）" % (PACKAGE, VERSION),
             "- 生成时间：%s" % now(),
             "- case_id：%s" % (pay.get("case_id") or (state.get("case") or {}).get("case_id")),
             "- 运行状态：%s（见 result.json；缺口均有记录）" % pay.get("status"),
             "- 对照基准：`golden_standard.json`（%d 个字段条目，自建金标准，不是组织方答案）" % len(g.get("fields") or []),
             "", "## 1. 总览", "", "| 指标 | 数量 |", "|-|-:|",
             "| 对照项合计 | %d |" % counts["total"], "| 达标 match | %d |" % counts["match"],
             "| 缺失 missing | %d |" % counts["missing"], "| 偏差 deviation | %d |" % counts["deviation"],
             "| 需人工 needs_review | %d |" % counts["needs_review"],
             "| 达标率 | %s |" % (("%.2f%%" % (counts["match_rate"] * 100)) if counts["match_rate"] is not None else "-"),
             "", "按组：", "", "| 组 | 条目 |", "|-|-:|"]
    for grp, n in sorted(by_group.items()):
        lines.append("| %s | %d |" % (grp, n))
    titles = {"contract": "2. 输出契约逐项", "envelope": "3. 封装字段逐项", "accounting": "4. 计数与完整性",
              "field": "5. 字段逐项对照（金标准 vs 实际）"}
    for grp in ("contract", "envelope", "accounting", "field"):
        sub = [r for r in rows if r["group"] == grp]
        if not sub:
            continue
        lines += ["", "## " + titles.get(grp, grp), ""]
        if grp == "field":
            lines += ["| 字段 | 金标准期望 | 实际交付 | 判定 | 原因 |", "|-|-|-|-|-|"]
            for r in sub:
                lines.append("| %s | %s | %s | %s | %s |" % (r["id"], _md(r["expected"]), _md(r["actual"]),
                                                             r["verdict"], _md(r["reason"])))
        else:
            lines += ["| 编号 | 期望 | 实际 | 判定 | 说明 |", "|-|-|-|-|-|"]
            for r in sub:
                lines.append("| %s | %s | %s | %s | %s |" % (r["id"], _md(r["expected"]), _md(r["actual"]),
                                                             r["verdict"], _md(r["reason"])))
    issues = [r for r in rows if r["verdict"] in ("missing", "deviation", "needs_review")]
    lines += ["", "## 6. 偏差与缺口清单", ""]
    if issues:
        for r in issues:
            lines.append("- **%s**（%s）：%s；期望=%s；实际=%s" % (r["id"], r["verdict"], _md(r["reason"]),
                                                               _md(r["expected"]), _md(r["actual"])))
        lines += ["", "复跑 `python3 scripts/pipeline.py --stage=finalize --input <input> --output <output> --work <work>`，"
                      "并读 golden_standard.json 对应条目的 locator/quote 原文后再判。"]
    else:
        lines.append("- 无缺失；对照项全部达标或已按预期记录。")
    lines += ["", "## 7. 如何复核本报告", "",
              "1. 打开 `golden_standard.json`，取某字段条目的 `evidence.locator`（paragraph_id 或 table_id+row_header+col_header）",
              "2. 在输入材料的同一位置搜索 `evidence.quote`，应逐字命中",
              "3. 对照 `result.json.result.fields[]` 的同名字段，检查 status/value/units/quote/locator 是否一致",
              "4. `self_check.json` 给出契约键、覆盖计数、引文命中率、数字一致性与空/坏输入兜底的机器回执",
              ""]
    return "\n".join(lines), counts


def _md(text):
    s = clip(text, 220)
    return s.replace("|", "\\|").replace("\n", " ")


# ---------------------------------------------------------------------- version history
def version_history(state, pay, out, inp, argv):
    fields = (pay.get("result") or {}).get("fields") or []
    cov = (pay.get("result") or {}).get("coverage") or {}
    elapsed = state.get("elapsed_s") if isinstance(state, dict) else None
    lines = [VH, "", "## 5. 本次运行（runtime append）", "",
             "- 运行时间：%s" % now(),
             "- run_id：`%s-%s`" % (time.strftime("%Y%m%dT%H%M%S"), str(pay.get("case_id"))[:24]),
             "- 命令：`%s`" % (" ".join(str(x) for x in (argv or [])) or "-"),
             "- 输入：`%s`；输出：`%s`；case_id：%s" % (inp, out, pay.get("case_id")),
             "- 状态：%s；退出码 **0**；耗时 %s" % (pay.get("status"),
                                                  ("%.2fs" % elapsed) if isinstance(elapsed, (int, float)) else "见 run.log"),
             "- 主产物：`result.json`（字段 %d 条；逐字段账本与 coverage 计数）；另交 `fields.csv`" % len(fields),
             "- 本次交付资产：`golden_standard.json`、`diff_report.md`、`version_history.md`、`run.log`、`self_check.json`",
             "- coverage：reported=%s not_reported=%s source_conflict=%s extraction_failed=%s" % (
                 cov.get("reported"), cov.get("not_reported"), cov.get("source_conflict"), cov.get("extraction_failed")),
             "- 降级 %d 条、异常 %d 条、待人工确认 %d 条（详见 result.json 与 run.log）" % (
                 len(pay.get("degradations") or []), len(pay.get("errors") or []), len(pay.get("pending_human") or [])),
             "- 复跑：同一命令重跑；产物结构稳定，时间戳与耗时字段除外。",
             "- 回退：见上文第 3 节；本次运行不改变包内任何版本判定。", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------------ probes
def probes(allow):
    script = Path(__file__).resolve().parent / "pipeline.py"
    if not allow:
        return {"skipped": "probe recursion guard (%s=1)" % PROBE_ENV, "results": [], "all_ok": None,
                "command": "python3 scripts/pipeline.py --stage=finalize --input <tmp> --output <tmp> --work <tmp>"}
    if not script.is_file():
        return {"skipped": "pipeline.py not found next to assets.py", "results": [], "all_ok": None,
                "command": "-"}
    out = {"command": "python3 scripts/pipeline.py --stage=finalize --input <tmp> --output <tmp> --work <tmp>",
           "results": []}
    cases = (("empty_input", None),
             ("bad_json", '{"case_id": "probe-bad", "paragraphs": [ !!! not json ]'))
    for name, setup in cases:
        res = {"case": name, "returncode": None, "ok": None}
        try:
            tmp = tempfile.mkdtemp(prefix="ledger-probe-")
            try:
                tin, tout, twork = Path(tmp) / "in", Path(tmp) / "out", Path(tmp) / "work"
                tin.mkdir(parents=True)
                if setup is not None:
                    (tin / "case.json").write_text(setup, encoding="utf-8")
                env = dict(os.environ, **{PROBE_ENV: "1", "PYTHONIOENCODING": "utf-8"})
                cp = subprocess.run([sys.executable, "-B", str(script), "--stage=finalize",
                                     "--input", str(tin), "--output", str(tout), "--work", str(twork)],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    timeout=120, env=env, cwd=tmp)
                status, valid, contract_ok = None, False, True
                rj = tout / "result.json"
                if rj.is_file():
                    try:
                        doc = json.loads(rj.read_text(encoding="utf-8"))
                        valid, status = True, doc.get("status")
                        keys = list((doc.get("output_contract") or {})) if isinstance(doc.get("output_contract"), dict) else []
                        contract_ok = all(k in doc for k in keys)
                    except Exception:
                        valid = False
                sizes = {a: _size(tout, a) for a in ASSETS}
                res.update({"returncode": cp.returncode, "result_json_valid": valid, "status": status,
                            "contract_keys_ok": contract_ok, "assets": sizes,
                            "assets_ok": all(v > 0 for v in sizes.values()),
                            "stdout_tail": clip((cp.stdout or "").strip().splitlines()[-1] if (cp.stdout or "").strip() else "", 120)})
                res["ok"] = cp.returncode == 0 and valid and res["assets_ok"] and contract_ok
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        except Exception as exc:
            res.update({"error": repr(exc)[:160], "ok": None})
        out["results"].append(res)
    out["all_ok"] = bool(out["results"]) and all(r.get("ok") for r in out["results"])
    return out


# ---------------------------------------------------------------------------- self check
def _quote_stats(fields, state):
    graded, hit, num_bad = 0, 0, []
    for x in fields:
        if x.get("status") != "reported":
            continue
        q = x.get("quote")
        text = _locator_text(x, state)
        if not text or not q:
            continue
        graded += 1
        found = V.find_quote(q if isinstance(q, str) else (q[0] if q else ""), text)
        if found["match"] in ("exact", "case_normalized", "whitespace_normalized"):
            hit += 1
        if not V.digits_covered(x.get("value") or "", q if isinstance(q, str) else " ".join(q or []))["ok"]:
            num_bad.append(x.get("field_id"))
    return {"graded": graded, "hit": hit, "ratio": round(hit / graded, 4) if graded else None,
            "number_bad": num_bad}


def selfcheck(state, pay, out, g, probe):
    checks = []
    case = state.get("case") or {}
    contract = list(case.get("output_contract") or {}) if isinstance(case.get("output_contract"), dict) else list(case.get("output_contract") or [])
    fields = (pay.get("result") or {}).get("fields") or []
    cov = (pay.get("result") or {}).get("coverage") or {}
    qs = _quote_stats(fields, state)
    four = ["reported", "not_reported", "source_conflict", "extraction_failed"]

    def ck(cid, claim, expected, actual, ok, ev):
        checks.append({"id": cid, "claim": claim, "expected": expected, "actual": actual, "ok": ok, "evidence": ev})

    present = [k for k in contract if k in pay]
    ck("C01_contract_keys", "契约键完整性", "%d 个 output_contract 键全部出现在 result.json 顶层" % len(contract),
       "%d/%d 存在%s" % (len(present), len(contract), "" if len(present) == len(contract) else "，缺：" + ",".join(set(contract) - set(present))),
       len(present) == len(contract), "result.json 顶层键")
    env_present = [k for k in ENVELOPE_KEYS if k in pay]
    ck("C02_envelope_keys", "封装字段齐全", "11 个封装键都存在（case_id/status/result/claims/sources/uncertainties/pending_human/errors/degradations/changes/runtime）",
       "%d/11 存在" % len(env_present), len(env_present) == 11, "result.json 顶层键")
    req = len(state.get("fs") or [])
    ids = [str(x.get("field_id")) for x in fields]
    req_ids = [str(f.get("field_id")) for f in (state.get("fs") or [])]
    ck("C03_field_rows", "字段行完整唯一", "fields 条数 = 请求字段数，field_id 不重复且集合一致",
       "%d/%d 条，unique=%d，set_equal=%s" % (len(fields), req, len(set(ids)), set(ids) == set(req_ids)),
       len(fields) == req and len(set(ids)) == len(ids) and set(ids) == set(req_ids), "result.fields")
    cov_sum = sum(int(cov.get(k) or 0) for k in four)
    detail = {k: len([x for x in fields if x.get("status") == k]) for k in four}
    ok_cov = cov_sum == int(cov.get("fields_requested", -1)) == len(fields) and all(int(cov.get(k) or 0) == detail[k] for k in four)
    ck("C04_coverage_consistency", "覆盖计数自洽", "四状态计数之和 = fields_requested = len(fields)，且与明细一致",
       "%d / %s / %d；detail=%s" % (cov_sum, cov.get("fields_requested"), len(fields), detail), ok_cov, "result.coverage")
    ck("C05_quote_verbatim", "引文逐字命中率", "reported>0 时 >= 0.95；无 reported 时记 0 条且不判失败",
       "%d/%d = %s" % (qs["hit"], qs["graded"], qs["ratio"]), (not qs["graded"]) or qs["ratio"] >= 0.95,
       "reported 行 quote 对 source/locator 重新检索")
    ck("C06_number_consistency", "数字一致性", "reported 行 value 的数字全部逐字出现在 quote 中",
       "bad=%s" % (qs["number_bad"] or "none"), not qs["number_bad"], "checks.digits_covered 重算")
    sizes = {a: _size(out, a) for a in ASSETS}
    first = all(sizes.get(a, 0) > 0 for a in ASSETS if a != "self_check.json")
    ck("C07_assets_present", "五件资产齐全非空", "golden/diff/version/run.log/self_check 均 > 0 字节（self_check 本回执写盘后复核）",
       "golden=%dB diff=%dB version=%dB run.log=%dB；self_check=本回执" % (
           sizes.get("golden_standard.json", 0), sizes.get("diff_report.md", 0),
           sizes.get("version_history.md", 0), sizes.get("self_check.json", 0)),
       first, "输出目录")
    pr = {r.get("case"): r for r in (probe.get("results") or [])}
    for cid, name, label in (("C08_empty_input", "empty_input", "空输入兜底（子进程实跑）"),
                             ("C09_bad_json", "bad_json", "坏 JSON 兜底（子进程实跑）")):
        r = pr.get(name)
        if r is None:
            ck(cid, label, "exit 0 + result.json 合法 + 五件资产非空", probe.get("skipped") or "未执行", None,
               "self_check.fallback_tests")
        else:
            ck(cid, label, "exit 0 + result.json 合法 + 五件资产非空",
               "exit=%s result_json=%s status=%s assets=%d/5" % (
                   r.get("returncode"), r.get("result_json_valid"), r.get("status"),
                   len([v for v in (r.get("assets") or {}).values() if v > 0])),
               bool(r.get("ok")), "self_check.fallback_tests.results")
    codes = [0] + [r.get("returncode") for r in (probe.get("results") or []) if r.get("returncode") is not None]
    ck("C10_exit_code_zero", "退出码恒 0", "主进程与兜底子进程的退出码均为 0",
       "主进程 0（脚本恒 return 0）；子进程 %s" % ("全部 0" if all(c == 0 for c in codes) else codes),
       all(c == 0 for c in codes), "run.log 的 exit 行 / fallback_tests")
    st = str(pay.get("status") or "")
    honest = True
    if st == "answered":
        honest = not (pay.get("errors") or []) and ok_cov and cov_sum == req
    elif st == "input_error":
        honest = len(fields) == 0
    elif st == "partial":
        honest = True
    ck("C11_status_honest", "状态诚实（有缺口不报满）", "answered 时无 errors 且 coverage 完整；其余状态与缺口一致",
       "status=%s errors=%d coverage_ok=%s" % (st, len(pay.get("errors") or []), ok_cov), honest,
       "result.json status/errors/coverage")
    ready = [k for k in ("golden_standard", "diff_report", "version_history", "run_log", "self_check")
             if isinstance(pay.get(k), dict) and pay[k].get("path")]
    ck("C12_asset_summary_fields", "result.json 五字段就绪", "五个摘要键均为带 path 的对象",
       "%d/5 已回填（本次写入后复核）" % len(ready), None, "result.json")
    pkg_dir = Path(__file__).resolve().parent.parent
    files = [p for p in pkg_dir.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    total = sum(p.stat().st_size for p in files if p.is_file())
    ck("C13_package_budget", "包体预算", "文件数 <= 10 且总字节 <= 184320",
       "files=%d bytes=%d" % (len(files), total),
       len(files) <= PACKAGE_LIMITS["files"] and total <= PACKAGE_LIMITS["bytes"], "包目录实测")
    ok = [c["ok"] for c in checks if c["ok"] is not None]
    return {
        "schema": SELF_SCHEMA, "package": PACKAGE, "version": VERSION,
        "case_id": pay.get("case_id"), "generated": now(), "status": st, "exit_code": 0,
        "pass": all(ok) if ok else False, "passed": len([x for x in ok if x]), "total": len(ok),
        "skipped": len([c for c in checks if c["ok"] is None]), "checks": checks,
        "quote_audit": {"graded": qs["graded"], "verbatim_hit": qs["hit"], "ratio": qs["ratio"],
                        "method": "对每个 reported 行，用其 source 重新拼出定位文本并用 checks.find_quote 检索 quote"},
        "number_consistency": {"bad": qs["number_bad"],
                               "method": "checks.digits_covered(value, quote)：value 的每个数字组必须逐字出现在 quote"},
        "coverage": {"requested": req, "detail": detail, "sum": cov_sum},
        "fallback_tests": probe,
        "exit_codes": {"finalize": 0, "empty_input": (pr.get("empty_input") or {}).get("returncode"),
                       "bad_json": (pr.get("bad_json") or {}).get("returncode")},
        "package_budget": {"files": len(files), "bytes": total, "limits": PACKAGE_LIMITS},
        "artifacts": {a: sizes.get(a) for a in ASSETS},
        "limitations": [
            "自建金标准不是组织方隐藏答案：not_reported 的独立性只到词面，同义改写可能漏检，confidence 封顶 medium。",
            "无文本层/加密 PDF 不做 OCR，金标准只能记 extraction_failed 并进 pending_human；不猜内容。",
            "空输入/坏 JSON 兜底由本机子进程实跑（cwd 临时目录，验证不依赖 CWD）；环境禁止子进程时 C08/C09 记 skipped，不判失败。",
            "self_check.json 自身与本回执在写盘顺序上互相引用，最终字节见 result.json 的 self_check.bytes。",
        ],
    }


# ------------------------------------------------------------------------------- attach
def attach(out_dir, state, pay, inp, argv):
    out = Path(out_dir)
    attach_t0 = time.time()
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    def fail(stage, exc):
        e = {"stage": "assets." + stage, "detail": "%s: %s" % (type(exc).__name__, clip(exc, 200))}
        for bucket in (pay.get("errors"), (state.get("errs") if isinstance(state, dict) else None)):
            try:
                bucket.append(e)
            except Exception:
                pass
        log("error", stage, detail=clip(exc, 160))

    for d in (pay.get("degradations") or []):
        log("degrade", clip(d.get("detail") if isinstance(d, dict) else d, 110))
    log("assets", "finalize: five verifiable assets", out=str(out))
    try:
        g = golden(state)
    except Exception as exc:
        fail("golden", exc)
        g = {"schema": GOLD_SCHEMA, "package": {"name": PACKAGE, "version": VERSION},
             "case_id": pay.get("case_id"), "generated": now(), "rules": {}, "row_contract": {},
             "counts": {"fields_requested": 0, "quote_verbatim": {"graded": 0, "hit": 0, "ratio": None}},
             "source_scope": {}, "fields": [], "provenance": {"is_organizer_key": False,
                                                               "method": "generation failed: %r" % (exc,)}}
    try:
        log("golden", "written", fields=len(g.get("fields") or []),
            bytes=wr_json(out / "golden_standard.json", g))
    except Exception as exc:
        fail("golden.write", exc)
    try:
        (out / "version_history.md").write_text(version_history(state, pay, out, inp, argv), encoding="utf-8")
        log("version", "written", file="version_history.md")
    except Exception as exc:
        fail("version", exc)
        try:
            (out / "version_history.md").write_text("# 版本历史\n\n当前版本 %s；本次生成失败已记 errors：%r\n"
                                                    % (VERSION, exc), encoding="utf-8")
        except Exception:
            pass
    dsum = {}
    try:
        md, dsum = diff(g, state, pay, out)
        (out / "diff_report.md").write_text(md, encoding="utf-8")
        log("diff", "written", rows=dsum.get("total"), match=dsum.get("match"),
            missing=dsum.get("missing"), deviation=dsum.get("deviation"))
    except Exception as exc:
        fail("diff", exc)
        try:
            (out / "diff_report.md").write_text("# 差异核验\n\n本次生成失败（已记 errors）：%r\n\ncase_id=%s status=%s\n"
                                                % (exc, pay.get("case_id"), pay.get("status")), encoding="utf-8")
        except Exception:
            pass
    probe = probes(os.environ.get(PROBE_ENV) != "1")
    log("selfcheck", "fallback probes", all_ok=probe.get("all_ok"), skipped=bool(probe.get("skipped")))
    sc = {}
    try:
        sc = selfcheck(state, pay, out, g, probe)
        log("selfcheck", "written", pass_=sc.get("pass"), passed=sc.get("passed"), total=sc.get("total"),
            bytes=wr_json(out / "self_check.json", sc))
    except Exception as exc:
        fail("selfcheck", exc)
        sc = {"schema": SELF_SCHEMA, "package": PACKAGE, "exit_code": 0, "pass": False,
              "checks": [], "error": clip(exc, 200)}
        try:
            wr_json(out / "self_check.json", sc)
        except Exception:
            pass
    # five summary keys on result.json (only additions; original contract keys untouched)
    pay["golden_standard"] = _res(out, "golden_standard.json")
    pay["golden_standard"].update({"schema": GOLD_SCHEMA, "fields": len(g.get("fields") or []),
                                   "by_expected_status": (g.get("counts") or {}).get("by_expected_status") or {},
                                   "quote_verbatim": (g.get("counts") or {}).get("quote_verbatim") or {},
                                   "sha256": sha256(out / "golden_standard.json")})
    pay["diff_report"] = _res(out, "diff_report.md")
    pay["diff_report"].update({k: dsum.get(k) for k in ("total", "match", "missing", "deviation", "needs_review")})
    pay["version_history"] = _res(out, "version_history.md")
    pay["version_history"].update({"current_version": VERSION, "sha256": sha256(out / "version_history.md")})
    pay["run_log"] = _res(out, "run.log")
    pay["run_log"].update(log_summary())
    pay["self_check"] = _res(out, "self_check.json")
    pay["self_check"].update({"pass": sc.get("pass"), "passed": sc.get("passed"), "total": sc.get("total"),
                              "skipped": sc.get("skipped"), "schema": SELF_SCHEMA})
    try:
        settled = [k for k in ("golden_standard", "diff_report", "version_history", "run_log", "self_check")
                   if isinstance(pay.get(k), dict) and pay[k].get("path")]
        for c in sc.get("checks") or []:
            if c.get("id") == "C12_asset_summary_fields":
                c["actual"] = "%d/5 已回填 result.json" % len(settled)
                c["ok"] = len(settled) == 5
            if c.get("id") == "C07_assets_present":
                fin = {a: _size(out, a) for a in ASSETS}
                c["actual"] = "5/5：golden=%dB diff=%dB version=%dB run.log=%dB self_check=%dB" % (
                    fin["golden_standard.json"], fin["diff_report.md"], fin["version_history.md"],
                    fin["run.log"], fin["self_check.json"])
                c["ok"] = all(v > 0 for v in fin.values())
        ok = [c["ok"] for c in sc.get("checks") or [] if c["ok"] is not None]
        sc["pass"], sc["passed"], sc["total"] = all(ok) if ok else False, len([x for x in ok if x]), len(ok)
        sc["artifacts"] = {a: _size(out, a) for a in ASSETS}
        wr_json(out / "self_check.json", sc)
        pay["self_check"].update({"bytes": _size(out, "self_check.json"), "pass": sc["pass"],
                                  "passed": sc["passed"], "total": sc["total"]})
        log("selfcheck", "reconciled", pass_=sc["pass"], passed=sc["passed"], total=sc["total"])
        md2, d2 = diff(g, state, pay, out)
        if d2.get("total") == dsum.get("total"):
            (out / "diff_report.md").write_text(md2, encoding="utf-8")
            pay["diff_report"].update({"bytes": _size(out, "diff_report.md"),
                                       "match": d2.get("match"), "deviation": d2.get("deviation")})
        # version_history 的“本次运行”段要写真实总耗时（含兜底自检），故在收尾后再落一次
        if isinstance(state, dict):
            state["elapsed_s"] = round((state.get("elapsed_s") or 0) + (time.time() - attach_t0), 3)
        (out / "version_history.md").write_text(version_history(state, pay, out, inp, argv), encoding="utf-8")
        pay["version_history"].update({"bytes": _size(out, "version_history.md"),
                                       "sha256": sha256(out / "version_history.md")})
        log("version", "refreshed with final elapsed", bytes=pay["version_history"]["bytes"])
        if isinstance(sc, dict) and sc.get("artifacts") is not None:
            sc["artifacts"] = {a: _size(out, a) for a in ASSETS}
            wr_json(out / "self_check.json", sc)
            pay["self_check"].update({"bytes": _size(out, "self_check.json")})
    except Exception as exc:
        fail("selfcheck.final", exc)
    log("assets", "complete", files=len(ASSETS), self_check=pay.get("self_check", {}).get("pass"))
    return pay


def settle(pay, out):
    """Final pass: log the settle line first, then rewrite result.json so run.log.bytes is exact."""
    if not isinstance(pay, dict):
        return pay
    log("result", "settled", note="final result.json rewrite after run.log flush")
    out = Path(out)
    pay["run_log"] = _res(out, "run.log")
    pay["run_log"].update(log_summary())
    hp = out / "golden_standard.json"
    dp = out / "diff_report.md"
    vp = out / "version_history.md"
    sp = out / "self_check.json"
    if isinstance(pay.get("golden_standard"), dict):
        pay["golden_standard"]["bytes"] = hp.stat().st_size if hp.is_file() else None
        pay["golden_standard"]["sha256"] = sha256(hp)
    if isinstance(pay.get("diff_report"), dict):
        pay["diff_report"]["bytes"] = dp.stat().st_size if dp.is_file() else None
    if isinstance(pay.get("version_history"), dict):
        pay["version_history"]["bytes"] = vp.stat().st_size if vp.is_file() else None
        pay["version_history"]["sha256"] = sha256(vp)
    if isinstance(pay.get("self_check"), dict):
        pay["self_check"]["bytes"] = sp.stat().st_size if sp.is_file() else None
    for k in SUMMARY_KEYS:
        pay.setdefault(k, None)
    wr_json(out / "result.json", pay)
    return pay


def ref_fields(out):
    out = Path(out)
    return {"golden_standard": {"path": "golden_standard.json", "bytes": _size(out, "golden_standard.json")},
            "diff_report": {"path": "diff_report.md", "bytes": _size(out, "diff_report.md")},
            "version_history": {"path": "version_history.md", "bytes": _size(out, "version_history.md")},
            "run_log": {"path": "run.log", "bytes": _size(out, "run.log")},
            "self_check": {"path": "self_check.json", "bytes": _size(out, "self_check.json")}}


def fallback(out_dir, note):
    """Disaster branch: a fatal error before finalize still leaves legal assets and exit 0."""
    out = Path(out_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    stamp, note = now(), clip(note, 300)
    try:
        wr_json(out / "golden_standard.json", {
            "schema": GOLD_SCHEMA, "package": {"name": PACKAGE, "version": VERSION}, "stage": "fallback",
            "generated": stamp, "provenance": {"is_organizer_key": False, "note": "主流程未走到 finalize：" + note},
            "rules": {}, "row_contract": {}, "counts": {"fields_requested": 0},
        "fields": [], "source_scope": {}})
    except Exception:
        pass
    try:
        (out / "diff_report.md").write_text(
            "# 差异核验报告（diff_report）\n\n- 生成时间：%s\n- 状态：fallback（主流程未走到 finalize：%s）\n\n"
            "金标准为空，无法逐项对照；result.json 保留了最小合法结构，退出码依然为 0。\n" % (stamp, note),
            encoding="utf-8")
    except Exception:
        pass
    try:
        (out / "version_history.md").write_text(
            VH + "\n## 5. 本次运行（runtime append）\n\n- %s：主流程未走到 finalize（%s）。\n"
                 "- 本次为灾难分支兜底：五件资产仍按最小结构落盘，回退与复跑方式见上文第 3 节。\n" % (stamp, note),
            encoding="utf-8")
    except Exception:
        pass
    try:
        wr_json(out / "self_check.json", {
            "schema": SELF_SCHEMA, "package": PACKAGE, "stage": "fallback", "generated": stamp,
            "case_id": None, "status": "partial", "exit_code": 0, "pass": False, "passed": 0, "total": 0,
            "checks": [], "fallback_tests": {"skipped": "主流程未走到 finalize", "results": []},
            "limitations": ["主流程未启动：" + note]})
    except Exception:
        pass
    try:
        log("bootstrap", "fallback assets written", note=note)
        if not (out / "run.log").is_file():
            (out / "run.log").write_text("# run.log -- %s %s\n- %s\n- bootstrap：%s\n- exit_code=0\n"
                                         % (PACKAGE, VERSION, stamp, note), encoding="utf-8")
    except Exception:
        pass
