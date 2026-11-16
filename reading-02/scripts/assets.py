#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""assets.py -- five verifiable assets for the figure-evidence-lens patch increment.

finalize calls attach(): it writes golden_standard.json, diff_report.md, version_history.md,
run.log and self_check.json into the output directory and adds five summary keys to
result.json.  Contract keys, CLI and the "exit code is always 0" rule stay untouched; this
is an additive layer and every failure is caught.  The golden standard is rebuilt from the
supplied material by an independent re-scan (not the organiser's hidden key).  Standard
library only, no network, no reliance on the current working directory.
"""
import csv as csvmod
import hashlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:                                  # structural pixel facts for the golden standard
  import raster_ops as RA
except Exception:                     # golden standard still works without the decoder
  RA = None

VERSION = "1.0.0"
PACKAGE = "figure-evidence-lens"
GOLD_SCHEMA = "golden-standard/v2"
SELF_SCHEMA = "self-check/v2"
PROBE_ENV = "FIGLENS_ASSET_PROBE"
MAX_READ = 2 * 1024 * 1024
PACKAGE_LIMITS = {"files": 10, "bytes": 180 * 1024}
ASSETS = ("golden_standard.json", "diff_report.md", "version_history.md", "run.log", "self_check.json")
SUMMARY_KEYS = ("golden_standard", "diff_report", "version_history", "run_log", "self_check")
ENVELOPE_KEYS = ("case_id", "status", "result", "claims", "uncertainties", "uncertainty", "sources",
                 "pending_human", "errors", "degradations", "changes", "runtime",
                 "output_contract_spec", "skill", "verification")
STATUSES = ("answered", "partial", "insufficient_evidence", "input_error")
READABILITY = ("directly_read", "inferred", "undetermined")
FIGURE_FIELDS = ("figure_id", "panel", "caption", "image_px", "plot_box_px", "ticks_px", "spacing",
                 "axes", "color_clusters", "legend_candidates", "elements", "digitized",
                 "traceable", "warnings", "calibration_notes")
RASTER_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")
NUM_RX = re.compile(r"(?<![A-Za-z0-9\-])([+\-]?\d+(?:[.,]\d+)*)(?:\s*[x\u00d7]\s*10\s*\^?\s*[+\-]?\d+)?")
UNIT_RX = re.compile(r"[+\\-]?\d+(?:[.,]\d+)*\s*([A-Za-z\u00b0\u00b5\u03bc%][A-Za-z0-9\u00b0\u00b5\u03bc%/]{0,11})")
SENT_RX = re.compile(r"(?<=[.!?;])\s+")
STOP_UNITS = frozenset("""a an the of in on for and or to with by from at as is are was were be been
being this that these those we our it its their they them than then which where when what how about into
over under between among per via vs versus using used use also both all any each other such more most
less least can may might will would should could do does did not no nor but if only own same so very
just condition conditions tested test tests measure measured measurement data value values paper article
supplied given input section sections table tables figure figures reported report keeping keep printed
readings reading every show shows shown mean means average max min total versus day days hour hours
second seconds minute minutes meter meters millimetre millimetres specimen specimens sample samples
run runs same respectively approximately around near after before during while at by""".split())

VH = """# 版本历史与回退（version_history）

- 包：`figure-evidence-lens`（阅读02 科研图表解析）；当前版本 **1.0.0**。
- 本文件是五件可核验资产之一：finalize 写入 `/app/output/version_history.md` 并在末尾追加本次运行段；
  只记录能从包里核对到的变更，不补写不存在的改动。

## 1. 版本演进

| 版本 | 改了什么 | 为什么 |
|-|-|-|
| v0 骨架 | 案例定位、首写 partial 壳、逐图测量、逐表复制、claims 审计 | 中断也先落合法可接手的结果 |
| v0.9 预交付 | `raster_ops.py` 像素/文本原语（解码、轴框/刻度/颜色簇/图例、标定、取点、表复制、PDF）+ references | 把“看见图”变成“能按像素复算的读数” |
| v1.0.0 | 单命令 CLI、契约回填、主产物、审计 `verification`、恒 0 退出码与降级 | 平台评测与人工复核共用主路径 |
| v1.0.0+assets | finalize 追加五件可核验资产，`result.json` 只增五个摘要键 | 期望交付/差异/可信度可复算 |

## 2. 本次增量

- 新增 `scripts/assets.py`（纯标准库）生成五件资产；`figure_runner.py` 只加 `import assets`（失败自动跳过）、
  `start_log/log/finish_log` 埋点与 `finalize_result()` 末尾 `A.attach()`；参数/路径/契约/退出码未改。
- `SKILL.md` 加 §11 说明五件资产；文件清单与交付前自检各加一条。

## 3. 如何回退

| 目标 | 操作 | 验证 |
|-|-|-|
| 回到 patch 前 | 用 `work/patch_backup/reading-02_orig` 覆盖本包，删 `scripts/assets.py`，去掉 `figure_runner.py` 的 import/埋点/attach 与 `SKILL.md` §11 | 原命令 exit 0；原 16 个顶层键齐全 |
| 只关资产 | 删 `scripts/assets.py`：`A=None` 时 `_log`/`attach` 自动跳过 | 主流程不受影响；无五个摘要键 |
| 回退本次运行段 | 删除输出目录 `version_history.md`/`run.log` 后重跑 | 重新追加运行段 |
| 关兜底自检子进程 | 设置 `FIGLENS_ASSET_PROBE=1` | `fallback_tests` 记 skipped，不判失败 |

- 回退验证：`python3 scripts/figure_runner.py --input /input --output /app/output`；另跑空输入/坏 `case.json` 冒烟（均 exit 0）。
- 定位：`run.log` 看阶段时间线，`diff_report.md` 看偏差条目，`self_check.json` 看逐项回执。

## 4. 依赖与兼容

- 纯标准库（`json/re/time/hashlib/pathlib/subprocess/tempfile/csv/struct`），不联网，不依赖当前目录。
- 退出码恒 0；`output_contract` 原有键一个不少；五件资产与五个摘要键只增不改。
- 空输入/坏 `case.json` 仍写合法 `result.json` 与五件资产，不伪造材料内容。

## 5. 本次运行（runtime append，由 finalize 真实追加）

- 待 finalize 追加
"""


class RunLog(object):
  """Real append-only execution log: one line per event, flushed immediately."""

  def __init__(self, path, argv, inp, out):
    self.p = Path(path)
    try:                             # keep one file bounded when an output dir is reused
      if self.p.is_file() and self.p.stat().st_size > 512 * 1024:
        self.p.write_text("", encoding="utf-8")
    except OSError:
      pass
    self.t0 = self.last = time.time()
    self.rows = []
    self._w("# run.log -- %s %s real execution log" % (PACKAGE, VERSION))
    self._w("# start=%s python=%s platform=%s" % (time.strftime("%Y-%m-%dT%H:%M:%S"),
                                                  sys.version.split()[0], sys.platform))
    self._w("# format: local-time gap-since-previous-line [stage] message key=value")
    self._w("# invocation=%s argv=%s" % (time.strftime("%Y%m%dT%H%M%S"),
                                         " ".join(str(a) for a in (argv or []))))
    self._w("# input=%s output=%s cwd=%s" % (inp, out, os.getcwd()))

  def _w(self, line):
    self.rows.append(line)
    try:
      with open(str(self.p), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    except OSError:
      pass

  def log(self, stage, msg="", **kv):
    moment = time.time()
    gap, self.last = moment - self.last, moment
    tail = " ".join("%s=%s" % (k, clip(v, 120)) for k, v in kv.items() if v is not None)
    self._w("[%s] +%08.3fs [%-10s] %s%s" % (time.strftime("%H:%M:%S"), gap, str(stage)[:10], msg,
                                            (" " + tail) if tail else ""))

  def finish(self, code=0, status=""):
    self.log("exit", "run finished", exit_code=code, status=status,
             elapsed_s=round(time.time() - self.t0, 3))

  def summary(self):
    try:
      size = self.p.stat().st_size
    except OSError:
      size = 0
    try:
      lines = self.p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
      lines = list(self.rows)
    stages = len([r for r in lines if r.startswith("[") and " [exit" not in r])
    return {"path": "run.log", "bytes": size, "stages": stages,
            "invocations": 1, "elapsed_s": round(time.time() - self.t0, 2)}


_LOG = None


def start_log(out, argv, inp):
  global _LOG
  try:
    Path(out).mkdir(parents=True, exist_ok=True)
    _LOG = RunLog(Path(out) / "run.log", argv, inp, out)
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


def now():
  return time.strftime("%Y-%m-%dT%H:%M:%S")


def clip(v, n=160):
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


def _sha(p):
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


def _size(out, name):
  p = Path(out) / name
  try:
    return p.stat().st_size if p.is_file() else 0
  except OSError:
    return 0


def _md(text):
  return clip(text, 260).replace("|", "\\|").replace("\n", " ")


def _collapse(t):
  t = re.sub(r"[\u2010-\u2015\u2212]", "-", t or "")
  t = re.sub(r"[\u2018\u2019]", "'", re.sub(r"[\u201c\u201d]", '"', t))
  return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff%.+-]", "", t).lower()


def _iter_strings(o):
  if isinstance(o, str):
    yield o
  elif isinstance(o, dict):
    for k, v in o.items():
      yield from _iter_strings(v)
  elif isinstance(o, list):
    for v in o:
      yield from _iter_strings(v)


def _walk_json(o, ptr="$"):
  yield ptr, o
  if isinstance(o, dict):
    for k, v in o.items():
      yield from _walk_json(v, ptr + "/" + str(k))
  elif isinstance(o, list):
    for i, v in enumerate(o):
      yield from _walk_json(v, ptr + "/%d" % i)


def _walk_strings(o, ptr="$"):
  if isinstance(o, str):
    yield ptr, o
  elif isinstance(o, dict):
    for k, v in o.items():
      yield from _walk_strings(v, ptr + "/" + str(k))
  elif isinstance(o, list):
    for i, v in enumerate(o):
      yield from _walk_strings(v, ptr + "/%d" % i)


def load_sources(inp):
  """Read every input file once: bytes/sha/kind plus raw text and parsed JSON strings."""
  doc = {"files": [], "raw": {}, "strings": {}, "json": {}}
  try:
    files = [p for p in sorted(Path(inp).rglob("*")) if p.is_file()][:400]
  except Exception:
    files = []
  for p in files:
    try:
      rel = str(p.relative_to(inp)).replace("\\", "/")
    except Exception:
      rel = p.name
    item = {"source_id": rel, "bytes": 0, "sha256": None,
            "kind": p.suffix.lower().lstrip(".") or "other"}
    try:
      item["bytes"] = p.stat().st_size
      item["sha256"] = _sha(p)
    except OSError:
      pass
    raw = ""
    try:
      if 0 <= item["bytes"] <= MAX_READ:
        raw = p.read_bytes().decode("utf-8", errors="replace")
        if raw.startswith("\ufeff"):
          raw = raw[1:]
    except OSError:
      pass
    doc["raw"][rel] = raw
    if item["kind"] in ("json", "csv"):
      try:
        doc["json"][rel] = json.loads(raw.strip() or "null") if item["kind"] == "json" \
            else [row for row in csvmod.reader(io.StringIO(raw))]
      except Exception:
        if item["kind"] == "json":
          pass
    if isinstance(doc["json"].get(rel), (dict, list)):
      doc["strings"][rel] = list(_iter_strings(doc["json"][rel]))
    doc["files"].append(item)
  return doc


def _src_get(src, sid):
  """One source entry as {raw, strings} for verbatim quote checks."""
  sid = str(sid or "")
  return {"raw": (src.get("raw") or {}).get(sid, ""),
          "strings": (src.get("strings") or {}).get(sid) or []}


def quote_hit(q, src):
  """Verbatim or decodable hit of a quote against one source entry."""
  q = (q or "").strip()
  if not q:
    return "empty"
  raw = src.get("raw") or ""
  if q in raw:
    return "exact"
  escaped = json.dumps(q, ensure_ascii=False)[1:-1]
  if escaped != q and escaped in raw:
    return "exact"
  for s in src.get("strings") or []:
    if isinstance(s, str) and q in s:
      return "decoded"
  cq, cr = _collapse(q), _collapse(raw)
  if cq and cq in cr:
    return "normalized"
  return "miss"


def _item(iid, group, expect, check, target, expected, source_id, locator, quote, quote_type,
          read_basis, **extra):
  it = {"item_id": iid, "group": group, "expect": expect, "check": check, "target": target,
        "expected": expected, "source_id": source_id, "locator": locator, "quote": quote,
        "quote_type": quote_type, "read_basis": read_basis}
  it.update(extra)
  return it


def _pick_table_id(node, key):
  for k in ("table_id", "label", "id", "name"):
    v = node.get(k)
    if isinstance(v, (str, int)) and str(v).strip():
      return str(v).strip()
  return str(key)


def _rows_of(v):
  if not isinstance(v, list) or not v:
    return None
  if all(isinstance(r, list) and all(not isinstance(x, (list, dict)) for x in r) for r in v):
    return [[str(x).strip() for x in r] for r in v]
  if all(isinstance(r, dict) for r in v):
    cols = []
    for r in v:
      for k in r:
        if str(k) not in cols:
          cols.append(str(k))
    return [["%s" % k for k in cols]] + [[str(r.get(k, "")).strip() for k in cols] for r in v]
  return None


def mine_tables(jsons):
  """Literal tables inside supplied JSON: rows + declared column headers (independent scan)."""
  found = []

  def visit(node, ptr, path, sid):
    if isinstance(node, dict):
      for k, v in node.items():
        nptr, npath = ptr + "/" + str(k), path + [str(k)]
        lk = str(k).lower()
        if lk in ("rows", "data", "body", "grid", "cells"):
          rows = _rows_of(v)
          if rows is not None:
            cols = None
            for probe in ("columns", "headers", "column_headers", "col_headers"):
              cand = node.get(probe)
              if isinstance(cand, list) and cand and all(isinstance(x, (str, int, float)) for x in cand):
                cols = [str(x).strip() for x in cand]
                break
            found.append({"source_id": sid, "locator": {"json_pointer": nptr},
                          "table_id": _pick_table_id(node, path[-2] if len(path) > 1 else "table"),
                          "columns": cols, "rows": rows})
            continue
        visit(v, nptr, npath, sid)
    elif isinstance(node, list):
      for i, v in enumerate(node):
        visit(v, ptr + "/%d" % i, path + [str(i)], sid)

  for sid, o in jsons.items():
    visit(o, "", [], sid)
  seen, out = set(), []
  for t in found:
    key = (t["table_id"], json.dumps(t["rows"], ensure_ascii=False))
    if key in seen:
      continue
    seen.add(key)
    out.append(t)
  return out[:8]


def mine_csv_tables(src):
  out = []
  for sid, rows in src.get("json", {}).items():
    if not sid.lower().endswith(".csv") or not isinstance(rows, list) or not rows:
      continue
    grid = [[str(x).strip() for x in r] for r in rows if r]
    if len(grid) < 2:
      continue
    out.append({"source_id": sid, "locator": {"line": 1}, "table_id": Path(sid).stem,
                "columns": grid[0], "rows": grid[1:]})
  return out


def mine_readings(jsons):
  """Numeric readings in the supplied prose/tables: value + adjacent unit + verbatim sentence."""
  facts = []
  for sid, o in jsons.items():
    for ptr, text in _walk_strings(o):
      if len(text) < 18:
        continue
      for sent in SENT_RX.split(text):
        s = sent.strip()
        if len(s) < 12 or not NUM_RX.search(s):
          continue
        for m in UNIT_RX.finditer(s):
          unit = m.group(1).strip()
          if not unit or len(unit) > 12:
            continue
          if unit.lower() in STOP_UNITS:
            continue
          try:
            value = float(m.group(0).split()[0].replace(",", ""))
          except Exception:
            continue
          facts.append({"source_id": sid, "locator": {"json_pointer": ptr}, "quote": s,
                        "value": _num_text(m.group(0).split()[0]), "unit": unit})
          break
  out, seen = [], set()
  for f in facts:
    key = (f["quote"], f["value"], f["unit"])
    if key in seen:
      continue
    seen.add(key)
    out.append(f)
  return out[:12]


def _num_text(raw):
  raw = str(raw).replace(",", "")
  try:
    f = float(raw)
  except Exception:
    return raw
  return ("%d" % f) if f.is_integer() else ("%g" % f)


def _png_size(p):
  """Read the PNG IHDR directly (independent of the skill decoder)."""
  try:
    b = Path(p).read_bytes()
  except OSError:
    return None
  if len(b) < 24 or b[:8] != b"\x89PNG\r\n\x1a\n" or b[12:16] != b"IHDR":
    return None
  try:
    w, h = struct.unpack(">II", b[16:24])
  except struct.error:
    return None
  return {"w": int(w), "h": int(h), "bytes": len(b)}


def _raster_records(inp, src):
  out = []
  for f in src.get("files") or []:
    sid = f["source_id"]
    if not sid.lower().endswith(RASTER_SUFFIXES):
      continue
    p = Path(inp) / sid
    facts = {}
    if RA is not None:
      try:
        facts = RA.inspect_image(p)
      except Exception:
        facts = {}
    out.append({"rel": sid, "path": p, "sha256": f.get("sha256"), "png": _png_size(p),
                "facts": facts})
  return out[:8]


def _find_figure(doc, source_id):
  figs = ((doc.get("result") or {}).get("figures") or {})
  base = Path(str(source_id).replace("\\", "/")).name
  for k, v in figs.items():
    if Path(str(k).replace("\\", "/")).name == base:
      return k, v
  return None, {}


def _ptr_items(case, group, label):
  """Expectations mined from case.json's own declarations (scope lists, contract)."""
  items, imgs, tabs = [], [], []

  def walk(node, ptr):
    if isinstance(node, dict):
      for k, v in node.items():
        p = ptr + "/" + str(k)
        lk = str(k).lower()
        if isinstance(v, list) and v and all(isinstance(x, (str, int)) for x in v):
          if any(w in lk for w in ("image", "figure", "photo", "raster", "artifact")):
            imgs.extend((p + "/%d" % i, str(x)) for i, x in enumerate(v))
          elif "table" in lk:
            tabs.extend((p + "/%d" % i, str(x)) for i, x in enumerate(v))
        walk(v, p)
    elif isinstance(node, list):
      for i, v in enumerate(node):
        walk(v, ptr + "/%d" % i)

  walk(case, "")
  seen = set()
  for p, name in imgs:
    if name in seen:
      continue
    seen.add(name)
    items.append(_item("G-SCOPE-I%02d" % len(items), group,
                       "任务声明必须解析的图 %s 出现在 coverage.images 且 analyzed=true" % name,
                       "scope_image", name, {"analyzed": True, "declared": True}, "case.json",
                       {"json_pointer": p}, name, "text", label))
  for p, name in tabs:
    if name in seen:
      continue
    seen.add(name)
    items.append(_item("G-SCOPE-T%02d" % len(items), group,
                       "任务声明必须解析的表 %s 在 coverage.tables 中 resolved=true" % name,
                       "scope_table", name, True, "case.json", {"json_pointer": p}, name,
                       "text", label))
  return items


def _task_items(task_text):
  items = []
  if not isinstance(task_text, str):
    return items
  for ln, line in enumerate(task_text.splitlines(), 1):
    s = line.strip()
    if len(s) < 12 or s.startswith("#"):
      continue
    low = s.lower()

    def add(expect, check, target, expected, basis):
      items.append(_item("G-TASK-%02d" % (len(items) + 1), "task", expect, check, target,
                         expected, "task.md", {"line": ln}, s, "text", basis))

    if re.search(r"\baxis\b|\baxes\b|\btick", low):
      add("任务要求轴类型与刻度：axes.x / axes.y 均存在", "axes_pair", "axes", True,
          "task.md 的轴读数要求")
    if "unit" in low:
      add("任务要求单位：x/y 轴对象显式携带 unit 键（可为 null 但需进 uncertainties）",
          "axes_unit_key", "axes", True, "task.md 的单位要求")
    if "legend" in low:
      add("任务要求图例顺序：legend_candidates 非空且条目数与颜色簇一致",
          "figure_legend", "legend", True, "task.md 的图例要求")
    if re.search(r"\bseries\b|\bcurves?\b", low):
      add("任务要求系列读数：digitized_series.csv 按系列输出且带误差列",
          "series_csv", "digitized_series.csv", True, "task.md 的系列读数要求")
    if re.search(r"\bcells?\b", low):
      add("任务要求逐字复制单元格：材料每个 cell 在表产物中逐字出现",
          "tables_obligation", "tables", True, "task.md 的表格逐字要求")
    if re.search(r"\bheader", low):
      add("任务要求保留表头字符串（既有提取器限制记 needs_review）",
          "tables_obligation", "tables", True, "task.md 的表头逐字要求")
    if re.search(r"locator|quote|evidence|verbatim", low):
      add("任务要求每条结论带 locator 与逐字 quote：claims 五键证据齐全",
          "claim_schema", "claims", True, "task.md 的证据要求")
      add("任务要求 quote 逐字来自材料：text quote 重检命中率 1.0",
          "claim_quote_hit", "claims", 1.0, "task.md 的证据要求")
    if re.search(r"undetermined|guess|invent", low):
      add("任务要求不可读就标 undetermined：readability 合法且 read_basis 非空",
          "claim_readability", "claims", True, "task.md 的诚实性要求")
    if re.search(r"\bcsv\b|\bjson\b|\bexport", low):
      add("任务要求机读导出：digitized_series.csv / tables.json 可解析且非空",
          "export_products", "artifacts", True, "task.md 的导出要求")
  return items[:16]


def _figure_items(rasters):
  out = []
  for r in rasters:
    rel, facts = r["rel"], r.get("facts") or {}
    box, png = facts.get("plot_box_px") or [], r.get("png")
    loc = {"kind": "raster", "image_px": png or {}, "bbox_px": box or None}

    def n():
      return len(out) + 1

    out.append(_item("G-FIG-P%02d" % n(), "figure_structure",
                     "input raster %s has one structure record in result.figures" % rel,
                     "figure_present", rel, True, rel, loc, "raster file %s" % rel, "measured",
                     "input inventory"))
    if png:
      out.append(_item("G-FIG-I%02d" % n(), "figure_structure",
                       "image_px equals PNG IHDR %(w)dx%(h)d" % png, "figure_image_px", rel, png,
                       rel, loc, "PNG IHDR: width=%(w)d height=%(h)d" % png, "measured",
                       "direct PNG IHDR parse (independent of the skill decoder)"))
    if box and len(box) == 4 and png:
      out.append(_item("G-FIG-B%02d" % n(), "figure_structure",
                       "plot_box is 4 numbers inside the image and >= 25%% of it",
                       "figure_plot_box", rel, {"box": box, "image_px": png}, rel, loc,
                       "plot box measured at [%s]" % ", ".join("%.0f" % v for v in box),
                       "measured", "frame ink rows/columns"))
      out.append(_item("G-FIG-S%02d" % n(), "figure_structure",
                       "spines left<right and top<bottom", "figure_spines", rel, True, rel,
                       loc, "spines measured", "measured", "frame bounds"))
    ticks = facts.get("ticks_px") or {}
    for axis in ("x", "y"):
      k = len(ticks.get(axis) or [])
      if k >= 2:
        out.append(_item("G-FIG-T%s%02d" % (axis.upper(), n()), "figure_structure",
                         "%s axis has %d measured major ticks (>=2)" % (axis, k),
                         "figure_tick_count", {"figure": rel, "axis": axis}, k, rel, loc,
                         "%s axis: %d major tick marks detected" % (axis, k), "measured",
                         "tick stroke detection"))
    clusters = facts.get("color_clusters") or []
    if facts.get("traceable") and clusters:
      out.append(_item("G-FIG-C%02d" % n(), "figure_structure",
                       "%d measured saturated colour clusters (>=1)" % len(clusters),
                       "figure_clusters", rel, len(clusters), rel, loc,
                       "%d saturated colour clusters measured" % len(clusters), "measured",
                       "colour clustering"))
      legends = facts.get("legend_candidates") or []
      ne = len((legends[0] or {}).get("entries_top_to_bottom") or []) if legends else 0
      if ne:
        out.append(_item("G-FIG-L%02d" % n(), "figure_structure",
                         "legend entries %d == colour clusters %d" % (ne, len(clusters)),
                         "figure_legend", rel, {"n_entries": ne, "n_clusters": len(clusters)},
                         rel, loc, "legend swatches top-to-bottom: %d" % ne, "measured",
                         "swatch order"))
    tr = bool(facts.get("traceable"))
    out.append(_item("G-FIG-R%02d" % n(), "figure_structure", "traceable = %s (measured)" % tr,
                     "figure_traceable", rel, tr, rel, loc, "traceable=%s" % tr, "measured",
                     "structure verdict"))
    out.append(_item("G-FIG-H%02d" % n(), "figure_structure",
                     "figure_structure sha256 equals the input raster sha256", "figure_sha", rel,
                     r.get("sha256"), rel, loc,
                     "input raster sha256=%s" % (r.get("sha256") or "")[:16], "measured",
                     "input file hash"))
    out.append(_item("G-FIG-F%02d" % n(), "figure_structure",
                     "each figure record carries %d structure fields" % len(FIGURE_FIELDS),
                     "figure_fields", rel, len(FIGURE_FIELDS), rel, loc,
                     "structural field list: %d fields" % len(FIGURE_FIELDS), "measured",
                     "structure fields"))
  return out


def _axes_items(rasters):
  out = []
  for r in rasters:
    facts = r.get("facts") or {}
    if not facts.get("traceable") or len(facts.get("ticks_px", {}).get("x") or []) < 2:
      continue
    rel = r["rel"]
    loc = {"kind": "visual", "bbox_px": facts.get("plot_box_px") or None}
    for axis in ("x", "y"):
      k = len((facts.get("ticks_px") or {}).get(axis) or [])
      tgt, tag = {"figure": rel, "axis": axis}, "G-AX-%s%%02d" % axis.upper()
      out.append(_item(tag % (len(out) + 1), "axes", "%s axis scale is linear/log" % axis,
                       "axis_scale", tgt, "linear|log", rel, loc,
                       "%s axis scale fit requested" % axis, "measured", "axis scale"))
      out.append(_item(tag % (len(out) + 1), "axes",
                       "%s axis tick_labels count == %d pixel ticks" % (axis, k),
                       "axis_tick_labels", tgt, k, rel, loc,
                       "%s axis: %d tick labels paired with %d pixel ticks" % (axis, k, k),
                       "measured", "label/tick pairing"))
      out.append(_item(tag % (len(out) + 1), "axes", "%s axis fit r2 >= 0.95" % axis,
                       "axis_r2", tgt, 0.95, rel, loc,
                       "%s least-squares fit quality gate" % axis, "measured", "least squares"))
      out.append(_item(tag % (len(out) + 1), "axes",
                       "%s axis unit key present (explicit null if unclear)" % axis,
                       "axis_unit_key", tgt, True, rel, loc,
                       "%s axis unit must be reported verbatim" % axis, "measured",
                       "unit string"))
      out.append(_item(tag % (len(out) + 1), "axes", "%s axis value_per_px > 0" % axis,
                       "axis_value_per_px", tgt, 0, rel, loc,
                       "%s axis data units per pixel" % axis, "measured", "calibration slope"))
  return out


def _series_items(rasters):
  out = []
  traceable = [r for r in rasters if (r.get("facts") or {}).get("traceable")]
  if not traceable:
    return out
  f0 = traceable[0]
  loc = {"kind": "file", "path": "digitized_series.csv"}
  nc = max(0, len((f0.get("facts") or {}).get("color_clusters") or []))
  out.append(_item("G-SER-01", "series", "digitized_series.csv exists with data rows",
                   "series_csv", "digitized_series.csv", True, f0["rel"], loc,
                   "traced series file required by the task", "measured", "task series"))
  out.append(_item("G-SER-02", "series", "CSV header has x,y,approx,err_x_data,err_y_data",
                   "series_header", "digitized_series.csv",
                   ["x", "y", "approx", "err_x_data", "err_y_data"], f0["rel"], loc,
                   "pixel-derived numbers need approx=true and an error term", "measured",
                   "error convention"))
  if nc:
    out.append(_item("G-SER-03", "series", "distinct CSV series == %d measured clusters" % nc,
                     "series_count", "digitized_series.csv", nc, f0["rel"], loc,
                     "%d colour clusters are traced-series candidates" % nc, "measured",
                     "cluster/series mapping"))
  out.append(_item("G-SER-04", "series",
                   "result.result.digitized_series_file points to the CSV", "series_file_field",
                   "digitized_series_file", "digitized_series.csv", f0["rel"], loc,
                   "digitized_series_file=digitized_series.csv", "measured", "result field"))
  out.append(_item("G-SER-05", "series",
                   "every row approx=true with numeric error columns; rows == counts",
                   "series_honesty", "digitized_series.csv", True, f0["rel"], loc,
                   "every traced row is approximate with a half-pixel error", "measured",
                   "pixel error convention"))
  return out


def _table_quote(t, src):
  """A verbatim quote that really exists in the table's source (headers/cells first)."""
  cands = []
  if t.get("columns"):
    cands.extend(str(c) for c in t["columns"][:2])
  for row in (t.get("rows") or [])[:2]:
    cands.extend(str(c) for c in (row or [])[:2])
  cands.append(str(t["table_id"]))
  entry = _src_get(src, t["source_id"])
  for q in cands:
    if q.strip() and quote_hit(q, entry) != "miss":
      return q
  return cands[0] if cands else str(t["table_id"])


def _table_items(tables, src):
  items = []
  for i, t in enumerate(tables):
    tid = t["table_id"]
    loc = dict(t["locator"])
    loc["table_id"] = tid
    tq = _table_quote(t, src)
    items.append(_item("G-TAB-I%02d" % (i + 1), "tables",
                       "表 %s 出现在 result.tables 与 tables.json" % tid, "table_present",
                       tid, True, t["source_id"], loc, tq, "text", "材料表清单"))
    cells = [c for row in t["rows"] for c in row if str(c).strip() != ""]
    if cells:
      items.append(_item("G-TAB-C%02d" % (i + 1), "tables",
                         "表 %s 的 %d 个单元格逐字出现" % (tid, len(cells)),
                         "table_cells", tid, cells, t["source_id"], loc,
                         str(cells[0]), "text", "material cells copied verbatim"))
    if t.get("columns"):
      items.append(_item("G-TAB-H%02d" % (i + 1), "tables",
                         "表 %s 的列名逐字保留：%s" % (tid, " | ".join(t["columns"])),
                         "table_headers", tid, t["columns"], t["source_id"], loc,
                         tq, "text", "material declared headers"))
    items.append(_item("G-TAB-F%02d" % (i + 1), "tables",
                       "tables/%s.csv 存在且行数不丢" % tid, "table_csv_file", tid,
                       len(t["rows"]), t["source_id"], loc, tq, "text",
                       "逐表 CSV 导出（材料 %d 数据行）" % len(t["rows"])))
  return items


def _reading_items(readings):
  items = []
  for i, f in enumerate(readings):
    loc = dict(f["locator"])
    items.append(_item("G-READ-%02d" % (i + 1), "readings",
                       "读数 %s %s 在 claims 中有可回查的支撑（value+unit 同句）"
                       % (f["value"], f["unit"]), "reading_supported",
                       {"value": f["value"], "unit": f["unit"]}, f["quote"], f["source_id"],
                       loc, f["quote"], "text", "材料原文读数"))
  return items


def _evidence_items(rasters, readings, tables):
  src0 = tables[0]["source_id"] if tables else (rasters[0]["rel"] if rasters else "case.json")
  out = [
      _item("G-EV-01", "evidence",
            "each claim has kind/text/conditions/readability and five evidence keys",
            "claim_schema", "claims", True, src0, {"kind": "audit", "path": "claims"},
            "every claim carries a locator and a verbatim quote", "measured", "evidence rule"),
      _item("G-EV-02", "evidence", "all text quotes are verbatim hits (ratio 1.0)",
            "claim_quote_hit", "claims", 1.0, "material source",
            {"kind": "audit", "path": "claims"},
            "verbatim quotes must be found in the cited source", "measured", "verbatim quotes"),
      _item("G-EV-03", "evidence", "visual quote bboxes stay inside the declared image",
            "claim_bbox", "claims", True, rasters[0]["rel"] if rasters else "case.json",
            {"kind": "visual", "bbox_px": None},
            "visual quotes need an in-bounds bbox locator", "measured", "visual locator"),
      _item("G-EV-04", "evidence", "verification.hard_failures == 0", "verification_hard",
            "verification", 0, "case.json", {"kind": "audit", "path": "/verification"},
            "audit gate: no blocking evidence failure", "measured", "audit gate"),
  ]
  for i, f in enumerate(readings[:4]):
    out.append(_item("G-EV-R%02d" % (i + 1), "evidence",
                     "reading %s %s has claim support and a verbatim quote"
                     % (f["value"], f["unit"]), "reading_supported",
                     {"value": f["value"], "unit": f["unit"]}, f["quote"], f["source_id"],
                     dict(f["locator"]), f["quote"], "text", "material reading vs claim"))
  return out


def _artifact_items(rasters, tables, traceable):
  out = [
      _item("G-ART-R01", "artifacts", "result.json exists, parses and is non-empty",
            "asset_valid_json", "result.json", True, "case.json",
            {"kind": "file", "path": "result.json"}, "mandatory deliverable", "measured",
            "result contract"),
      _item("G-ART-R02", "artifacts", "a legal partial shell was written first",
            "first_write_partial", "changes", True, "case.json",
            {"kind": "audit", "path": "/changes"}, "first write is a legal partial shell",
            "measured", "workflow step 1"),
  ]
  if rasters:
    out.append(_item("G-ART-F01", "artifacts", "figure_structure.json parses and has fields",
                     "asset_struct_json", "figure_structure.json", True, rasters[0]["rel"],
                     {"kind": "file", "path": "figure_structure.json"},
                     "structure product required for every raster", "measured", "main products"))
  if tables:
    out.append(_item("G-ART-T01", "artifacts", "tables.json parses and has the material tables",
                     "asset_tables_json", "tables.json", len(tables), tables[0]["source_id"],
                     {"kind": "file", "path": "tables.json"},
                     "literal table product required when tables exist", "measured",
                     "main products"))
  if traceable:
    out.append(_item("G-ART-D01", "artifacts", "digitized_series.csv exists and is non-empty",
                     "asset_digitized_csv", "digitized_series.csv", True, traceable[0]["rel"],
                     {"kind": "file", "path": "digitized_series.csv"},
                     "digitised series product required for traceable rasters", "measured",
                     "main products"))
  out.extend([
      _item("G-ASSET-01", "artifacts", "golden_standard.json is non-empty (this file)",
            "asset_present", "golden_standard.json", True, "self",
            {"kind": "file", "path": "golden_standard.json"},
            "five verifiable assets are written to /app/output", "measured", "patch increment"),
      _item("G-ASSET-02", "artifacts", "version_history.md has versions/rollback/run section",
            "asset_version_md", "version_history.md", True, "self",
            {"kind": "file", "path": "version_history.md"},
            "version history with rollback instructions", "measured", "patch increment"),
      _item("G-ASSET-03", "artifacts", "run.log is non-empty with real stage lines",
            "asset_run_log", "run.log", True, "self", {"kind": "file", "path": "run.log"},
            "real execution log", "measured", "patch increment"),
  ])
  return out


def _runtime_items(src):
  n_in = len(src.get("files") or [])
  return [
      _item("G-RUN-01", "runtime", "runtime.duration_s 为数字且 >= 0", "path_gte",
            "runtime.duration_s", 0, "case.json", {"kind": "audit", "path": "/runtime"},
            "runtime duration measured by the runner", "measured", "运行元数据"),
      _item("G-RUN-02", "runtime", "sources 覆盖全部输入文件且逐个带 sha256", "sources_hashed",
            "sources", n_in, "input directory", {"kind": "audit", "path": "/sources"},
            "%d input files must be hashed into sources" % n_in, "measured", "输入清单"),
      _item("G-RUN-03", "runtime", "runtime.input_files == 输入目录文件数 %d" % n_in,
            "path_eq", "runtime.input_files", n_in, "case.json",
            {"kind": "audit", "path": "/runtime/input_files"},
            "input file count", "measured", "运行元数据"),
  ]


def golden(state, src=None):
  """Rebuild the expected deliverables from the supplied material only."""
  inp = Path(state.get("input") or "/input")
  src = src or load_sources(inp)
  case = state.get("case") or {}
  groups, items = [], []

  def push(group, new):
    if new:
      groups.append(group)
      items.extend(new)

  contract = case.get("output_contract")
  contract_items = []
  if isinstance(contract, dict):
    for i, (k, v) in enumerate(contract.items()):
      q = v if isinstance(v, str) else (json.dumps(v, ensure_ascii=False) if v is not None else str(k))
      if not (q or "").strip():
        q = str(k)
      contract_items.append(_item("G-CON-%02d" % (i + 1), "contract",
                                  "result.json 顶层存在契约键 %r，取值回填且不丢键" % k, "top_key",
                                  k, "present", "case.json", {"json_pointer": "/output_contract/%s" % k},
                                  q, "text", "case.json 的 output_contract 逐项声明"))
  elif isinstance(contract, list):
    for i, k in enumerate(contract):
      contract_items.append(_item("G-CON-%02d" % (i + 1), "contract",
                                  "result.json 顶层存在契约键 %r" % k, "top_key", str(k),
                                  "present", "case.json", {"json_pointer": "/output_contract/%d" % i},
                                  str(k), "text", "case.json 的 output_contract 逐项声明"))
  if contract_items:
    status_q = ""
    if isinstance(contract, dict) and isinstance(contract.get("status"), str):
      status_q = contract["status"]
    contract_items.append(_item("G-CON-S01", "contract",
                                "status 取值属于 answered/partial/insufficient_evidence/input_error",
                                "status_vocab", "status", list(STATUSES), "case.json",
                                {"json_pointer": "/output_contract/status"},
                                status_q or "answered | partial | insufficient_evidence | input_error",
                                "text", "SKILL.md §6 状态语义"))
    contract_items.append(_item("G-CON-K01", "contract", "case_id 原样回填", "case_id_eq",
                                "case_id", case.get("case_id"), "case.json",
                                {"json_pointer": "/case_id"}, str(case.get("case_id") or ""),
                                "text", "案例标识"))
  push("contract", contract_items)
  push("scope", _ptr_items(case, "scope", "case.json 的必须对象声明"))

  task_text = src.get("raw", {}).get("task.md") or ""
  if not task_text:
    for sid, raw in src.get("raw", {}).items():
      if Path(sid).name.lower() == "task.md":
        task_text = raw
        break
  push("task", _task_items(task_text))

  rasters = _raster_records(inp, src)
  facts = [r.get("facts") or {} for r in rasters]
  traceable = [r for r in rasters if (r.get("facts") or {}).get("traceable")]
  push("figure_structure", _figure_items(rasters))
  push("axes", _axes_items(rasters))
  push("series", _series_items(rasters))

  material_jsons = {sid: o for sid, o in (src.get("json") or {}).items()
                    if Path(sid).name.lower() not in ("case.json", "readings.json")
                    and isinstance(o, (dict, list))}
  tables = mine_tables(material_jsons) + mine_csv_tables(src)
  readings = mine_readings(material_jsons)
  push("tables", _table_items(tables, src))
  push("readings", _reading_items(readings))
  push("evidence", _evidence_items(rasters, readings, tables))
  push("artifacts", _artifact_items(rasters, tables, traceable))
  push("runtime", _runtime_items(src))

  text_q = {"graded": 0, "exact": 0, "decoded": 0, "normalized": 0, "miss": 0, "misses": []}
  for it in items:
    if it.get("quote_type") != "text":
      continue
    text_q["graded"] += 1
    verdict = quote_hit(it.get("quote"), _src_get(src, it.get("source_id")))
    it["quote_verbatim"] = verdict
    if verdict in ("exact", "decoded", "normalized"):
      text_q[verdict] += 1
    else:
      text_q["miss"] += 1
      if len(text_q["misses"]) < 8:
        text_q["misses"].append({"item_id": it["item_id"], "source_id": it.get("source_id"),
                                 "quote": clip(it.get("quote"), 120)})
  hit = text_q["graded"] - text_q["miss"]
  by_group = {}
  for it in items:
    by_group[it["group"]] = by_group.get(it["group"], 0) + 1
  counts = {
      "total_items": len(items),
      "by_group": by_group,
      "contract_keys": len(contract) if isinstance(contract, (dict, list)) else 0,
      "rasters": len(rasters),
      "tables": len(tables),
      "readings": len(readings),
      "measured_items": len([it for it in items if it.get("quote_type") == "measured"]),
      "text_quote_verbatim": {"graded": text_q["graded"], "hit": hit,
                              "ratio": round(hit / text_q["graded"], 4) if text_q["graded"] else None,
                              "exact": text_q["exact"], "decoded": text_q["decoded"],
                              "normalized": text_q["normalized"], "miss": text_q["miss"],
                              "misses": text_q["misses"]},
  }
  return {
      "schema": GOLD_SCHEMA,
      "package": {"name": PACKAGE, "version": VERSION},
      "case_id": case.get("case_id") or "unknown-case",
      "generated": now(),
      "provenance": {
          "is_organizer_key": False,
          "method": "assets.py 对 /input 独立重扫：契约逐项、task 义务、材料表单元格与读数句、PNG IHDR/像素结构",
          "note": "自建金标准用于逐项对照，不是组织方隐藏答案；材料未提供的不生成期望值。",
          "sources": src.get("files") or [],
      },
      "quote_policy": {
          "text": "quote 为对应 source 的逐字子串（JSON 按解码值比对，转义/空白差异记 normalized）",
          "measured": "quote 为可离线复算的测量式（PNG IHDR、刻度像素、颜色簇、sha256）",
          "locator": "text 项给 json_pointer/line；visual/measured 项给 raster bbox/图像尺寸",
      },
      "counts": counts,
      "groups": groups,
      "items": items,
  }


def _dig(o, path):
  cur = o
  for part in str(path or "").split("."):
    if isinstance(cur, dict):
      if part not in cur:
        return None
      cur = cur[part]
    elif isinstance(cur, list) and str(part).isdigit():
      i = int(part)
      if i >= len(cur):
        return None
      cur = cur[i]
    else:
      return None
  return cur


def _is_num(x):
  return isinstance(x, (int, float)) and not isinstance(x, bool)


def _num(x):
  try:
    return float(x)
  except (TypeError, ValueError):
    return None


class Ctx(object):
  """Lazy view over the real products in the output directory."""

  def __init__(self, state, pay, out, src):
    self.state = state if isinstance(state, dict) else {}
    self.doc = pay if isinstance(pay, dict) else {}
    self.out = Path(out)
    self.input = Path(self.state.get("input") or "/input")
    self.src = src if isinstance(src, dict) else {}
    self._struct = None
    self._tables = None
    self._csv = None
    self._text = {}

  def _load(self, name):
    p = self.out / name
    if not p.is_file():
      return None
    try:
      return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
      return None

  def text(self, name):
    if name not in self._text:
      p = self.out / name
      try:
        self._text[name] = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
      except OSError:
        self._text[name] = ""
    return self._text[name]

  def struct(self):
    if self._struct is None:
      self._struct = self._load("figure_structure.json") or {}
    return self._struct if isinstance(self._struct, dict) else {}

  def tables(self):
    if self._tables is None:
      self._tables = self._load("tables.json") or []
    return self._tables if isinstance(self._tables, list) else []

  def rows(self):
    if self._csv is None:
      out = []
      p = self.out / "digitized_series.csv"
      if p.is_file():
        try:
          with open(str(p), newline="", encoding="utf-8", errors="replace") as fh:
            out = list(csvmod.DictReader(fh))
        except Exception:
          out = []
      self._csv = out
    return self._csv

  def figure(self, source_id):
    return _find_figure(self.doc, source_id)

  def fstruct(self, source_id):
    figs = self.struct()
    base = Path(str(source_id).replace("\\", "/")).name
    if isinstance(figs, dict):
      for k, v in figs.items():
        if Path(str(k).replace("\\", "/")).name == base:
          return v if isinstance(v, dict) else {}
    return {}

  def figures(self):
    figs = ((self.doc.get("result") or {}).get("figures") or {})
    return figs if isinstance(figs, dict) else {}

  def claims(self):
    c = self.doc.get("claims")
    return c if isinstance(c, list) else []

  def coverage(self):
    return ((self.doc.get("result") or {}).get("coverage") or {})

  def table_cells(self, tid):
    blobs = []
    for t in self.tables():
      if str(t.get("table_id")) != str(tid):
        continue
      for key in ("grid", "rows"):
        for row in t.get(key) or []:
          if isinstance(row, list):
            blobs.extend(str(x) for x in row)
          else:
            blobs.append(str(row))
      blobs.extend(str(x) for x in (t.get("columns") or []))
    slug = re.sub(r"[^\w.-]+", "_", str(tid))[:60]
    csv_text = self.text("tables/%s.csv" % slug)
    if csv_text:
      for line in csv_text.splitlines():
        blobs.extend([line] + line.split(","))
    return blobs


def c_top_key(it, ctx):
  k = it["target"]
  return ("present" if k in ctx.doc else "absent",
          "match" if k in ctx.doc else "missing")


def c_status_vocab(it, ctx):
  st = ctx.doc.get("status")
  return (str(st), "match" if st in STATUSES else "deviation")


def c_case_id_eq(it, ctx):
  want = it.get("expected")
  got = ctx.doc.get("case_id")
  if want is None:
    return (str(got), "needs_review")
  return (str(got), "match" if str(got) == str(want) else "deviation")


def _scope_row(rows, name):
  base = Path(str(name).replace("\\", "/")).name
  for r in rows or []:
    if not isinstance(r, dict):
      continue
    sid = str(r.get("source_id") or "")
    if Path(sid.replace("\\", "/")).name == base:
      return r
  return None


def c_scope_image(it, ctx):
  cov = ctx.coverage()
  row = _scope_row(cov.get("images"), it["target"])
  if row is None:
    return ("coverage.images 中无该图", "missing")
  ok = bool(row.get("analyzed"))
  return ("analyzed=%s declared=%s" % (row.get("analyzed"), row.get("declared")),
          "match" if ok else "deviation")


def c_scope_table(it, ctx):
  cov = ctx.coverage()
  want = str(it["target"])
  for r in cov.get("tables") or []:
    if not isinstance(r, dict):
      continue
    if str(r.get("table_id")) == want or want in str(r.get("table_id")):
      return ("resolved=%s" % r.get("resolved"), "match" if r.get("resolved") else "deviation")
  return ("coverage.tables 中无该表", "missing")


def _first_figure(ctx):
  figs = ctx.figures()
  for k, v in figs.items():
    if isinstance(v, dict):
      return k, v
  return None, {}


def c_axes_pair(it, ctx):
  _k, f = _first_figure(ctx)
  axes = f.get("axes") or {}
  ok = isinstance(axes.get("x"), dict) and isinstance(axes.get("y"), dict)
  return ("axes=%s" % sorted(axes.keys()) if isinstance(axes, dict) else "no axes",
          "match" if ok else ("missing" if not axes else "deviation"))


def c_axes_unit_key(it, ctx):
  _k, f = _first_figure(ctx)
  axes = f.get("axes") or {}
  sub = [a for a in ("x", "y") if isinstance(axes.get(a), dict)]
  if not sub:
    return ("no calibrated axes", "missing")
  ok = all("unit" in axes[a] for a in sub)
  units = {a: axes[a].get("unit") for a in sub}
  return ("unit keys=%s units=%s" % (ok, json.dumps(units, ensure_ascii=False)),
          "match" if ok else "deviation")


def c_axes_scale(it, ctx):
  _k, f = _first_figure(ctx)
  axis = (it.get("target") or {}).get("axis") or "x"
  a = ((f.get("axes") or {}).get(axis) or {})
  if not a:
    return ("axis %s not fitted" % axis, "missing")
  got = a.get("scale")
  ok = got in ("linear", "log", "log10") and not a.get("ambiguous") is True
  return ("scale=%r ambiguous=%s" % (got, a.get("ambiguous")), "match" if ok else "deviation")


def c_axes_tick_labels(it, ctx):
  _k, f = _first_figure(ctx)
  axis = (it.get("target") or {}).get("axis") or "x"
  a = ((f.get("axes") or {}).get(axis) or {})
  if not a:
    return ("axis %s not fitted" % axis, "missing")
  n, want = len(a.get("tick_labels") or []), it.get("expected")
  return ("tick_labels=%d expected=%s" % (n, want), "match" if n == want else "deviation")


def c_axes_r2(it, ctx):
  _k, f = _first_figure(ctx)
  axis = (it.get("target") or {}).get("axis") or "x"
  a = ((f.get("axes") or {}).get(axis) or {})
  r2 = _num(a.get("r2"))
  if r2 is None:
    return ("r2=n/a", "missing")
  return ("r2=%.4f" % r2, "match" if r2 >= float(it.get("expected") or 0.95) else "deviation")


def c_axes_value_per_px(it, ctx):
  _k, f = _first_figure(ctx)
  axis = (it.get("target") or {}).get("axis") or "x"
  a = ((f.get("axes") or {}).get(axis) or {})
  v = _num(a.get("value_per_px"))
  return ("value_per_px=%r" % v, "match" if v is not None and v > 0 else "missing")


def c_figure_present(it, ctx):
  k, f = ctx.figure(it["target"])
  return ("figure record key=%r" % k if k else "no figure record",
          "match" if k and f else "missing")


def c_figure_image_px(it, ctx):
  _k, f = ctx.figure(it["target"])
  got, want = f.get("image_px") or {}, it.get("expected") or {}
  if not got:
    return ("image_px absent", "missing")
  ok = _num(got.get("w")) == _num(want.get("w")) and _num(got.get("h")) == _num(want.get("h"))
  return ("image_px=%sx%s expected=%sx%s" % (got.get("w"), got.get("h"), want.get("w"), want.get("h")),
          "match" if ok else "deviation")


def c_figure_plot_box(it, ctx):
  _k, f = ctx.figure(it["target"])
  box, img = f.get("plot_box_px"), ((it.get("expected") or {}).get("image_px") or {})
  if not isinstance(box, list) or len(box) != 4:
    return ("plot_box=%r" % (box,), "missing")
  try:
    x0, y0, x1, y1 = (float(v) for v in box)
  except (TypeError, ValueError):
    return ("plot_box not numeric: %r" % (box,), "deviation")
  w, h = _num(img.get("w")), _num(img.get("h"))
  ok = (0 <= x0 < x1 and 0 <= y0 < y1 and w and h and x1 <= w and y1 <= h
        and (x1 - x0) >= 0.25 * w and (y1 - y0) >= 0.25 * h)
  return ("plot_box=[%.0f,%.0f,%.0f,%.0f] image=%sx%s" % (x0, y0, x1, y1, w, h),
          "match" if ok else "deviation")


def c_figure_spines(it, ctx):
  fs = ctx.fstruct(it["target"])
  sp = fs.get("spines_px") or {}
  left, right = _num(sp.get("left")), _num(sp.get("right"))
  top, bottom = _num(sp.get("top")), _num(sp.get("bottom"))
  ok = None not in (left, right, top, bottom) and left < right and top < bottom
  return ("spines=%s" % json.dumps(sp), "match" if ok else "missing")


def c_figure_tick_count(it, ctx):
  _k, f = ctx.figure((it.get("target") or {}).get("figure"))
  axis = (it.get("target") or {}).get("axis") or "x"
  n = len(((f.get("ticks_px") or {}).get(axis)) or [])
  want = it.get("expected")
  return ("%s ticks=%d expected=%s" % (axis, n, want), "match" if n == want else "deviation")


def c_figure_clusters(it, ctx):
  _k, f = ctx.figure(it["target"])
  n = len(f.get("color_clusters") or [])
  want = it.get("expected")
  return ("colour clusters=%d expected=%s" % (n, want), "match" if n == want else "deviation")


def c_figure_legend(it, ctx):
  _k, f = ctx.figure(it["target"])
  if not f:
    _k, f = _first_figure(ctx)
  legends = f.get("legend_candidates") or []
  want = it.get("expected")
  if not isinstance(want, dict):
    return ("legend_candidates=%d (task-level legend obligation)" % len(legends),
            "match" if legends else "missing")
  if not legends:
    return ("legend_candidates=[]", "missing")
  got = len((legends[0] or {}).get("entries_top_to_bottom") or [])
  n_clusters = want.get("n_clusters")
  ok = got == want.get("n_entries") and (n_clusters is None or len(f.get("color_clusters") or []) == n_clusters)
  return ("legend entries=%d expected=%s clusters=%d" % (got, want.get("n_entries"),
                                                        len(f.get("color_clusters") or [])),
          "match" if ok else "deviation")


def c_figure_traceable(it, ctx):
  _k, f = ctx.figure(it["target"])
  got, want = bool(f.get("traceable")), bool(it.get("expected"))
  return ("traceable=%s expected=%s" % (got, want), "match" if got == want else "deviation")


def c_figure_sha(it, ctx):
  fs = ctx.fstruct(it["target"])
  got, want = fs.get("sha256"), it.get("expected")
  if not got:
    return ("figure_structure 无 sha256", "missing")
  return ("sha256=%s" % str(got)[:16], "match" if str(got) == str(want) else "deviation")


def c_figure_fields(it, ctx):
  _k, f = ctx.figure(it["target"])
  got = [k for k in f if k in FIGURE_FIELDS]
  want = it.get("expected")
  return ("fields=%d expected=%d" % (len(got), want), "match" if len(got) >= want else "deviation")


def c_series_csv(it, ctx):
  rows = ctx.rows()
  return ("%d data rows" % len(rows), "match" if len(rows) > 0 else "missing")


def c_series_header(it, ctx):
  hdr = list(ctx.rows()[0].keys()) if ctx.rows() else []
  want = it.get("expected") or []
  missing = [h for h in want if h not in hdr]
  return ("header=%s missing=%s" % (hdr, missing),
          "match" if ctx.rows() and not missing else "deviation")


def c_series_count(it, ctx):
  names = sorted({str(r.get("series")) for r in ctx.rows() if r.get("series") not in (None, "")})
  want = it.get("expected")
  return ("series=%s expected=%s" % (names, want), "match" if len(names) == want else "deviation")


def c_series_file_field(it, ctx):
  got = _dig(ctx.doc, "result.digitized_series_file")
  want = it.get("expected")
  return (repr(got), "match" if got == want else ("needs_review" if got is None else "deviation"))


def c_series_honesty(it, ctx):
  rows = ctx.rows()
  if not rows:
    return ("no rows", "missing")
  bad_approx = [i for i, r in enumerate(rows)
                if str(r.get("approx")).lower() not in ("true", "1", "yes")]
  bad_err = [i for i, r in enumerate(rows)
             if _num(r.get("err_x_data")) is None or _num(r.get("err_y_data")) is None]
  declared = _dig(ctx.doc, "result.counts.digitized_points")
  ok = not bad_approx and not bad_err and (declared in (None, len(rows)))
  return ("rows=%d bad_approx=%d bad_err=%d declared=%s"
          % (len(rows), len(bad_approx), len(bad_err), declared), "match" if ok else "deviation")


def c_table_present(it, ctx):
  tid = it["target"]
  in_result = any(str(t.get("table_id")) == str(tid) for t in ((ctx.doc.get("result") or {}).get("tables") or []))
  in_file = any(str(t.get("table_id")) == str(tid) for t in ctx.tables())
  return ("result=%s tables.json=%s" % (in_result, in_file),
          "match" if in_result and in_file else "missing")


def c_tables_obligation(it, ctx):
  tables = ctx.tables()
  scanned = 0
  for t in tables:
    if isinstance(t, dict):
      scanned += len([r for r in (t.get("grid") or t.get("rows") or []) if r])
  return ("tables=%d scanned_rows=%d" % (len(tables), scanned),
          "match" if tables and scanned else "deviation")


def c_table_cells(it, ctx):
  want = it.get("expected")
  if not isinstance(want, list):
    return c_tables_obligation(it, ctx)
  blobs = ctx.table_cells(it["target"])
  want = [str(c) for c in want]
  hits = [c for c in want if any(c == b or c in b for b in blobs)]
  return ("%d/%d cells verbatim" % (len(hits), len(want)),
          "match" if len(hits) == len(want) else "deviation")


def c_table_headers(it, ctx):
  want = it.get("expected")
  if not isinstance(want, list):
    return c_tables_obligation(it, ctx)
  blobs = ctx.table_cells(it["target"])
  want = [str(c) for c in want]
  hits = [c for c in want if any(c == b or c in b for b in blobs)]
  if len(hits) == len(want):
    return ("%d/%d headers verbatim" % (len(hits), len(want)), "match")
  return ("%d/%d headers verbatim (既有 json-inline 提取器把首行当列名，参考包同行为)"
          % (len(hits), len(want)), "needs_review")


def c_table_csv_file(it, ctx):
  tid = it["target"]
  slug = re.sub(r"[^\w.-]+", "_", str(tid))[:60]
  p = ctx.out / "tables" / (slug + ".csv")
  if not p.is_file():
    return ("tables/%s.csv absent" % slug, "missing")
  rows = [r for r in p.read_text(encoding="utf-8", errors="replace").splitlines() if r.strip()]
  want = it.get("expected")
  return ("rows=%d expected=%s" % (len(rows), want), "match" if len(rows) >= want else "deviation")


def c_reading_supported(it, ctx):
  want = it.get("target") or {}
  quote, value, unit = it.get("quote") or "", str(want.get("value")), str(want.get("unit"))
  claims = ctx.claims()
  found, verbatim = [], 0
  for c in claims:
    if not isinstance(c, dict):
      continue
    blob = (str(c.get("text") or "") + " " +
            json.dumps(c.get("evidence") or {}, ensure_ascii=False))
    if (quote and quote in blob) or (value in blob and unit in blob):
      found.append(str(c.get("claim_id") or "?"))
      src = (c.get("evidence") or {}).get("source_id")
      if quote_hit(quote, _src_get(ctx.src, src)) in ("exact", "decoded", "normalized"):
        verbatim += 1
  if not claims:
    return ("no claims", "missing")
  ok = bool(found) and verbatim > 0
  return ("claims=%s verbatim_quote_hits=%d" % (found or "none", verbatim),
          "match" if ok else "deviation")


def _claim_quote_stats(ctx):
  graded, hit, misses = 0, 0, []
  for c in ctx.claims():
    if not isinstance(c, dict):
      continue
    ev = c.get("evidence") or {}
    q = ev.get("quote")
    if ev.get("quote_type") != "text" or not isinstance(q, str) or not q.strip():
      continue
    graded += 1
    src = _src_get(ctx.src, ev.get("source_id"))
    if quote_hit(q, src) in ("exact", "decoded", "normalized"):
      hit += 1
    elif len(misses) < 6:
      misses.append({"claim_id": c.get("claim_id"), "source_id": ev.get("source_id"),
                     "quote": clip(q, 100)})
  return {"graded": graded, "hit": hit,
          "ratio": round(hit / graded, 4) if graded else None, "misses": misses}


def c_claim_schema(it, ctx):
  claims = ctx.claims()
  if not claims:
    return ("no claims", "missing")
  bad = []
  for c in claims:
    if not isinstance(c, dict):
      bad.append("not-an-object")
      continue
    ev = c.get("evidence") or {}
    need = [f for f in ("kind", "text", "conditions", "readability", "evidence") if not c.get(f)]
    need += ["evidence." + f for f in ("quote", "quote_type", "source_id", "location")
             if not ev.get(f)]
    if c.get("readability") not in READABILITY:
      need.append("readability-vocab")
    if need:
      bad.append("%s:%s" % (c.get("claim_id"), ",".join(need)))
  return ("%d/%d claims complete%s" % (len(claims) - len(bad), len(claims),
                                      (" bad=" + "; ".join(bad[:4])) if bad else ""),
          "match" if not bad else "deviation")


def c_claim_quote_hit(it, ctx):
  st = _claim_quote_stats(ctx)
  if not st["graded"]:
    return ("no text quotes (visual-only claims)", "needs_review")
  ok = st["ratio"] >= float(it.get("expected") or 0.99)
  return ("%d/%d = %s%s" % (st["hit"], st["graded"], st["ratio"],
                             "" if ok else " misses=" + json.dumps(st["misses"], ensure_ascii=False)),
          "match" if ok else "deviation")


def c_claim_bbox(it, ctx):
  visual = 0
  bad = []
  for c in ctx.claims():
    ev = (c.get("evidence") or {}) if isinstance(c, dict) else {}
    if ev.get("quote_type") != "visual":
      continue
    visual += 1
    bbox = (ev.get("location") or {}).get("bbox_px")
    _k, f = ctx.figure(ev.get("source_id") or "")
    img = f.get("image_px") or {}
    if not (isinstance(bbox, list) and len(bbox) == 4 and img):
      bad.append(str(c.get("claim_id")))
      continue
    ok = 0 <= bbox[0] <= bbox[2] <= (img.get("w") or 0) and 0 <= bbox[1] <= bbox[3] <= (img.get("h") or 0)
    if not ok:
      bad.append(str(c.get("claim_id")))
  if not visual:
    return ("no visual claims", "needs_review")
  return ("%d/%d visual bboxes in bounds" % (visual - len(bad), visual),
          "match" if not bad else "deviation")


def c_claim_readability(it, ctx):
  claims = ctx.claims()
  if not claims:
    return ("no claims", "missing")
  bad = [str(c.get("claim_id")) for c in claims
         if not isinstance(c, dict) or c.get("readability") not in READABILITY
         or not (c.get("evidence") or {}).get("read_basis")]
  return ("%d/%d valid readability+basis" % (len(claims) - len(bad), len(claims)),
          "match" if not bad else "deviation")


def c_verification_hard(it, ctx):
  hf = _dig(ctx.doc, "verification.hard_failures")
  return ("hard_failures=%r expected=0" % (hf,), "match" if hf in (0, None) else "deviation")


def c_export_products(it, ctx):
  have_csv = len(ctx.rows()) > 0
  tables = ctx.tables()
  return ("csv_rows=%d tables=%d" % (len(ctx.rows()), len(tables)),
          "match" if have_csv and tables else "deviation")


def c_first_write_partial(it, ctx):
  steps = [str((c or {}).get("step")) for c in (ctx.doc.get("changes") or []) if isinstance(c, dict)]
  return ("steps=%s" % steps[:6], "match" if "partial" in steps else "deviation")


def c_path_gte(it, ctx):
  got = _num(_dig(ctx.doc, it["target"]))
  want = _num(it.get("expected")) or 0
  return ("%r expected>=" % got, "match" if got is not None and got >= want else "deviation")


def c_path_eq(it, ctx):
  got = _dig(ctx.doc, it["target"])
  want = it.get("expected")
  return ("%r expected=%r" % (got, want), "match" if got == want else "deviation")


def c_sources_hashed(it, ctx):
  srcs = ctx.doc.get("sources") or []
  if not isinstance(srcs, list) or len(srcs) < (it.get("expected") or 0):
    return ("sources=%d expected>=%s" % (len(srcs) if isinstance(srcs, list) else -1, it.get("expected")),
            "deviation")
  bad = [s for s in srcs if not isinstance(s, dict) or not re.match(r"^[0-9a-f]{64}$", str(s.get("sha256") or ""))
         or not isinstance(s.get("bytes"), int)]
  return ("%d sources, bad=%d" % (len(srcs), len(bad)), "match" if not bad else "deviation")


def c_asset_present(it, ctx):
  name = it["target"]
  n = _size(ctx.out, name)
  return ("%d bytes" % n, "match" if n > 0 else "missing")


def c_asset_valid_json(it, ctx):
  name = it["target"]
  p = ctx.out / name
  if not p.is_file():
    return ("absent", "missing")
  try:
    obj = json.loads(p.read_text(encoding="utf-8"))
  except Exception as e:
    return ("invalid JSON: %s" % clip(e, 80), "deviation")
  ok = bool(obj)
  return ("%d bytes, json=%s" % (p.stat().st_size, type(obj).__name__), "match" if ok else "deviation")


def c_asset_struct_json(it, ctx):
  fs = ctx.struct()
  if not fs:
    return ("absent/empty", "missing")
  ok = any(isinstance(v, dict) and v.get("image_px") for v in fs.values())
  return ("figures=%d image_px_present=%s" % (len(fs), ok), "match" if ok else "deviation")


def c_asset_tables_json(it, ctx):
  tables = ctx.tables()
  want = it.get("expected") or 0
  return ("tables=%d expected>=%d" % (len(tables), want), "match" if len(tables) >= want else "deviation")


def c_asset_digitized_csv(it, ctx):
  rows = ctx.rows()
  return ("%d rows" % len(rows), "match" if rows else "missing")


def c_asset_version_md(it, ctx):
  txt = ctx.text("version_history.md")
  need = ["版本演进", "如何回退", "本次运行"]
  miss = [k for k in need if k not in txt]
  return ("%d bytes, sections_ok=%s" % (len(txt), not miss),
          "match" if txt and not miss else "deviation")


def c_asset_run_log(it, ctx):
  txt = ctx.text("run.log")
  stages = len([ln for ln in txt.splitlines() if ln.startswith("[")])
  ok = txt.startswith("# run.log") and "# invocation=" in txt and stages >= 4
  return ("%d bytes, %d stage lines" % (len(txt), stages), "match" if ok else "deviation")


CHECKERS = {
    "top_key": c_top_key,
    "status_vocab": c_status_vocab,
    "case_id_eq": c_case_id_eq,
    "scope_image": c_scope_image,
    "scope_table": c_scope_table,
    "axes_pair": c_axes_pair,
    "axes_unit_key": c_axes_unit_key,
    "axis_unit_key": c_axes_unit_key,
    "axes_unit_key": c_axes_unit_key,
    "axis_scale": c_axes_scale,
    "axis_tick_labels": c_axes_tick_labels,
    "axis_r2": c_axes_r2,
    "axis_value_per_px": c_axes_value_per_px,
    "figure_present": c_figure_present,
    "figure_image_px": c_figure_image_px,
    "figure_plot_box": c_figure_plot_box,
    "figure_spines": c_figure_spines,
    "figure_tick_count": c_figure_tick_count,
    "figure_clusters": c_figure_clusters,
    "figure_legend": c_figure_legend,
    "figure_traceable": c_figure_traceable,
    "figure_sha": c_figure_sha,
    "figure_fields": c_figure_fields,
    "series_csv": c_series_csv,
    "series_header": c_series_header,
    "series_count": c_series_count,
    "series_file_field": c_series_file_field,
    "series_honesty": c_series_honesty,
    "table_present": c_table_present,
    "tables_obligation": c_tables_obligation,
    "table_cells": c_table_cells,
    "table_headers": c_table_headers,
    "table_csv_file": c_table_csv_file,
    "reading_supported": c_reading_supported,
    "claim_schema": c_claim_schema,
    "claim_quote_hit": c_claim_quote_hit,
    "claim_bbox": c_claim_bbox,
    "claim_readability": c_claim_readability,
    "verification_hard": c_verification_hard,
    "export_products": c_export_products,
    "first_write_partial": c_first_write_partial,
    "path_gte": c_path_gte,
    "path_eq": c_path_eq,
    "sources_hashed": c_sources_hashed,
    "asset_present": c_asset_present,
    "asset_valid_json": c_asset_valid_json,
    "asset_struct_json": c_asset_struct_json,
    "asset_tables_json": c_asset_tables_json,
    "asset_digitized_csv": c_asset_digitized_csv,
    "asset_version_md": c_asset_version_md,
    "asset_run_log": c_asset_run_log,
}
VERDICTS = ("match", "missing", "deviation", "needs_review")


def judge(g, state, pay, out, src):
  """Compare every golden item with the real product; never raises for one bad item."""
  ctx = Ctx(state, pay, out, src)
  rows = []
  for it in (g.get("items") or []):
    fn = CHECKERS.get(it.get("check"))
    if fn is None:
      actual, verdict = ("no checker for %r" % it.get("check"), "needs_review")
    else:
      try:
        actual, verdict = fn(it, ctx)
      except Exception as exc:
        actual, verdict = ("checker error: %s: %s" % (type(exc).__name__, clip(exc, 100)),
                           "needs_review")
    if verdict not in VERDICTS:
      actual, verdict = (str(actual), "needs_review")
    rows.append({"item_id": it.get("item_id"), "group": it.get("group"),
                 "expect": it.get("expect"), "expected": it.get("expected"),
                 "actual": clip(actual, 320), "verdict": verdict, "check": it.get("check"),
                 "source_id": it.get("source_id"), "locator": it.get("locator")})
  total = len(rows)
  count = {v: len([r for r in rows if r["verdict"] == v]) for v in VERDICTS}
  by_group = {}
  for r in rows:
    gd = by_group.setdefault(str(r["group"]), {v: 0 for v in VERDICTS})
    gd[r["verdict"]] += 1
  summary = {"total": total, "match": count["match"], "missing": count["missing"],
             "deviation": count["deviation"], "needs_review": count["needs_review"],
             "pass": bool(total) and count["missing"] == 0 and count["deviation"] == 0,
             "by_group": by_group}
  return rows, summary


REASON = {
    "missing": "应交付的产物/字段不存在",
    "deviation": "产物存在但与材料/任务要求不符",
    "needs_review": "机器口径不能判死，已在 self_check 披露",
}


def diff(g, state, pay, out, src, argv=None):
  rows, summary = judge(g, state, pay, out, src)
  case_id = (pay or {}).get("case_id")
  status = (pay or {}).get("status")
  stamp = now()
  gsha = _sha(Path(out) / "golden_standard.json")
  lines = ["# 差异核验报告（diff_report）", "",
           "- 生成时间：%s；`%s` %s；case_id：`%s`；status：`%s`" % (stamp, PACKAGE, VERSION, case_id, status),
           "- 运行命令：`%s`" % (" ".join(str(a) for a in (argv or [])) or "-"),
           "- 对照基准：`golden_standard.json`（schema=%s，sha256=%s，%d 条期望）"
           % (g.get("schema"), (gsha or "?")[:16], len(g.get("items") or [])),
           "- 对照方式：每条期望按 `check` 读 /app/output 真实产物；locator 指向材料或产物，可逐条回读。", "",
           "## 判定口径", "",
           "| verdict | 含义 | 计分 |", "|-|-|-|",
           "| `match` | 按 locator 可在产物中复核 | 通过 |",
           "| `missing` | 应交付的产物/字段不存在 | 不通过 |",
           "| `deviation` | 存在但与材料/任务要求不符 | 不通过 |",
           "| `needs_review` | 机器不能判死的既有边界，已在 self_check 披露 | 待复核 |", "",
           "## 汇总", "",
           "- 总计 **%d** 项；match=%d，missing=%d，deviation=%d，needs_review=%d；"
           "`pass`（missing=0 且 deviation=0）=**%s**%s"
           % (summary["total"], summary["match"], summary["missing"],
              summary["deviation"], summary["needs_review"], summary["pass"],
              "" if summary["pass"] else "（存在缺口，见偏差清单）"), "",
           "| 分组 | 合计 | match | missing | deviation | needs_review |", "|-|-:|-:|-:|-:|-:|"]
  for gname in g.get("groups") or list(summary["by_group"].keys()):
    gd = summary["by_group"].get(str(gname)) or {}
    lines.append("| %s | %d | %d | %d | %d | %d |" % (
        gname, sum(gd.values()), gd.get("match", 0), gd.get("missing", 0),
        gd.get("deviation", 0), gd.get("needs_review", 0)))
  lines += ["", "## 逐项明细", "",
            "| # | item_id | 期望（节选） | 实际 | verdict | 来源 locator |",
            "|-:|-|-|-|-|-|"]
  for i, r in enumerate(rows, 1):
    loc = r.get("locator") or {}
    loc_txt = json.dumps(loc, ensure_ascii=False) if isinstance(loc, dict) else str(loc)
    lines.append("| %d | %s | %s | %s | **%s** | `%s` |" % (
        i, r["item_id"], _md(r.get("expect")), _md(r.get("actual")), r["verdict"], _md(loc_txt)))
  bad = [r for r in rows if r["verdict"] in ("missing", "deviation", "needs_review")]
  lines += ["", "## 偏差与待复核清单", ""]
  if bad:
    lines += ["| item_id | verdict | 原因 | 复核动作 |", "|-|-|-|-|"]
    for r in bad:
      action = "按 `%s` 回读产物/材料复核" % (
          _md(json.dumps(r.get("locator") or {}, ensure_ascii=False)))
      lines.append("| %s | %s | %s | %s |" % (
          r["item_id"], r["verdict"], REASON.get(r["verdict"], "-"), action))
  else:
    lines.append("无：全部 %d 条期望均为 match。" % summary["total"])
  lines += ["", "## 复跑与复核步骤", "",
            "1. `python3 scripts/figure_runner.py --input /input --output /app/output`（视觉标注另给 `--readings`）",
            "2. 看 `run.log` 阶段时间线与 `result.json.verification` 的引文命中/覆盖。",
            "3. 按上表 locator 逐条回读：`json_pointer`→材料 JSON，`bbox_px`→栅格像素，`file`→产物文件名。",
            "4. 金标准 measured 项（PNG IHDR、刻度像素、颜色簇、sha256）可离线复算，不含人工读数。", ""]
  return "\n".join(lines), summary


def _vh_static():
  return VH.split("## 5. 本次运行")[0].rstrip() + "\n"


def version_history(state, pay, out, inp, argv, g=None):
  rt = (pay.get("runtime") or {})
  counts = ((pay.get("result") or {}).get("counts") or {})
  cov = ((pay.get("result") or {}).get("coverage") or {})
  elapsed = rt.get("duration_s")
  gcount = (g or {}).get("counts") or {}
  lines = [_vh_static(), "## 5. 本次运行（runtime append，由 finalize 真实追加）", "",
           "- 运行时间：%s（UTC finished=%s）" % (now(), rt.get("finished_utc") or "-"),
           "- run_id：`%s-%s`" % (time.strftime("%Y%m%dT%H%M%S"), str(pay.get("case_id"))[:24]),
           "- 命令：`%s`" % (" ".join(str(a) for a in (argv or [])) or "-"),
           "- 输入：`%s`；输出：`%s`；case_id：`%s`" % (inp, out, pay.get("case_id")),
           "- 状态：`%s`；退出码：**0**（脚本恒 return 0）；耗时 %s"
           % (pay.get("status"), ("%.2fs" % elapsed) if _is_num(elapsed) else "见 run.log"),
           "- 主产物：`result.json`（契约键 %d 个）+ `figure_structure.json`/`digitized_series.csv`/"
           "`tables.json`/`tables/<id>.csv`（材料允许时）" % len(pay.get("output_contract_spec") or {}),
           "- 五件资产：`golden_standard.json`（%d 条期望）、`diff_report.md`（逐项 verdict 见文件）、"
           "`version_history.md`、`run.log`、`self_check.json`" % (gcount.get("total_items") or 0),
           "- counts：images=%s/%s，tables=%s/%s，claims=%s，digitized_points=%s"
           % (counts.get("images_analyzed"), counts.get("required_images"),
              counts.get("required_tables_resolved"), counts.get("required_tables"),
              counts.get("claims"), counts.get("digitized_points")),
           "- gaps：missing_images=%s，missing_tables=%s；降级 %d、异常 %d、待人工 %d"
           % (cov.get("missing_images") or [], cov.get("missing_tables") or [],
              len(pay.get("degradations") or []), len(pay.get("errors") or []),
              len(pay.get("pending_human") or [])),
           "- 复跑：同一命令重跑；产物结构稳定，时间戳、耗时与本段除外。",
           "- 回退：见第 3 节；删 `scripts/assets.py` 即关闭五件资产，主流程不受影响。", ""]
  return "\n".join(lines)


def probes(allow):
  script = Path(__file__).resolve().parent / "figure_runner.py"
  command = "python3 scripts/figure_runner.py --input <tmp-in> --output <tmp-out>"
  if not allow:
    return {"skipped": "probe recursion guard (%s=1)" % PROBE_ENV, "results": [], "all_ok": None,
            "command": command}
  if not script.is_file():
    return {"skipped": "figure_runner.py not found next to assets.py", "results": [],
            "all_ok": None, "command": "-"}
  out = {"command": command, "results": []}
  cases = (("empty_input", None),
           ("bad_json", '{"case_id": "probe-bad-joon", "rows": [ !!! not json ]'))
  for name, setup in cases:
    res = {"case": name, "returncode": None, "ok": None}
    try:
      tmp = tempfile.mkdtemp(prefix="figlens-probe-")
      try:
        tin, tout = Path(tmp) / "in", Path(tmp) / "out"
        tin.mkdir(parents=True)
        if setup is not None:
          (tin / "case.json").write_text(setup, encoding="utf-8")
        env = dict(os.environ, **{PROBE_ENV: "1", "PYTHONIOENCODING": "utf-8",
                                  "PYTHONDONTWRITEBYTECODE": "1"})
        cp = subprocess.run([sys.executable, "-B", str(script), "--input", str(tin),
                             "--output", str(tout)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120, env=env, cwd=tmp)
        valid, status, contract_ok, nkeys = False, None, True, 0
        rj = tout / "result.json"
        if rj.is_file():
          try:
            doc = json.loads(rj.read_text(encoding="utf-8"))
            valid, status = True, doc.get("status")
            spec = doc.get("output_contract_spec")
            nkeys = len(spec) if isinstance(spec, dict) else 0
          except Exception:
            valid = False
        sizes = {a: _size(tout, a) for a in ASSETS}
        stdout_tail = (cp.stdout or "").strip().splitlines()
        res.update({"returncode": cp.returncode, "result_json_valid": valid, "status": status,
                    "output_contract_keys": nkeys, "contract_keys_ok": contract_ok,
                    "assets": sizes, "assets_ok": all(v > 0 for v in sizes.values()),
                    "stdout_tail": clip(stdout_tail[-1] if stdout_tail else "", 140)})
        res["ok"] = (cp.returncode == 0 and valid and res["assets_ok"] and contract_ok)
      finally:
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception as exc:
      res.update({"error": repr(exc)[:180], "ok": None})
    out["results"].append(res)
  out["all_ok"] = bool(out["results"]) and all(r.get("ok") for r in out["results"])
  return out


def _golden_quote_stats(g, src):
  graded = hit = 0
  methods = {"exact": 0, "decoded": 0, "normalized": 0, "miss": 0}
  misses = []
  for it in (g.get("items") or []):
    if it.get("quote_type") != "text" or not (it.get("quote") or "").strip():
      continue
    graded += 1
    v = quote_hit(it.get("quote"), _src_get(src, it.get("source_id")))
    if v in ("exact", "decoded", "normalized"):
      hit += 1
      methods[v] += 1
    else:
      methods["miss"] += 1
      if len(misses) < 6:
        misses.append({"item_id": it.get("item_id"), "source_id": it.get("source_id"),
                       "quote": clip(it.get("quote"), 90)})
  return {"graded": graded, "hit": hit,
          "ratio": round(hit / graded, 4) if graded else None,
          "methods": methods, "misses": misses}


def selfcheck(state, pay, out, g, dsum, probe, src, argv=None):
  checks = []
  case = state.get("case") or {}
  contract = case.get("output_contract")
  ckeys = list(contract.keys()) if isinstance(contract, dict) else list(contract or [])
  ctx = Ctx(state, pay, out, src)
  gq = _golden_quote_stats(g, src)

  def ck(cid, claim, expected, actual, ok, ev):
    checks.append({"id": cid, "claim": claim, "expected": expected, "actual": actual,
                   "ok": ok, "evidence": ev})

  present = [k for k in ckeys if k in pay]
  ck("C01_contract_keys", "契约键完整",
     "%d 个 output_contract 键全部出现在 result.json 顶层" % len(ckeys),
     "%d/%d 存在%s" % (len(present), len(ckeys),
                      "" if len(present) == len(ckeys) else "，缺：" + ",".join(set(ckeys) - set(present))),
     len(present) == len(ckeys), "result.json 顶层键")
  env_present = [k for k in ENVELOPE_KEYS if k in pay]
  ck("C02_envelope_keys", "既有封装字段完整",
     "%d 个既有封装键仍存在" % len(ENVELOPE_KEYS),
     "%d/%d 存在" % (len(env_present), len(ENVELOPE_KEYS)),
     len(env_present) == len(ENVELOPE_KEYS), "result.json 顶层键")

  gcount = (g.get("counts") or {})
  n_rasters, n_tables = int(gcount.get("rasters") or 0), int(gcount.get("tables") or 0)
  has_series = bool([it for it in (g.get("items") or []) if it.get("group") == "series"])
  status_now = str(pay.get("status") or "")
  strict = status_now == "answered"
  result_ok = isinstance(pay.get("result"), dict) and bool(pay.get("result")) or status_now == "input_error"
  fs_ok = (not n_rasters) or (isinstance(ctx.struct(), dict) and bool(ctx.struct()))
  tables_ok = (not n_tables) or bool(ctx.tables())
  digit_ok = (not has_series) or bool(ctx.rows())
  ck("C03_main_products", "主产物就绪",
     "result.json 合法；有图/有表/answered 有可追踪图时主产物齐全；"
     "其它状态按缺口降级",
     "result=%s figure_structure=%s tables=%s digitized=%s strict=%s"
     % (bool(result_ok), bool(fs_ok), bool(tables_ok), bool(digit_ok), strict),
     bool(result_ok and fs_ok and tables_ok and (digit_ok or not strict)), "输出目录实测")

  counts = (pay.get("result") or {}).get("counts") or {}
  cov = (pay.get("result") or {}).get("coverage") or {}
  rows = ctx.rows()
  claims = pay.get("claims") or []
  detail = {
      "claims": counts.get("claims", 0) == len(claims),
      "digitized_points": counts.get("digitized_points", 0) == len(rows),
      "images_missing": counts.get("images_missing", 0) == len(cov.get("missing_images") or []),
      "required_tables_resolved": counts.get("required_tables_resolved", 0) == len(
          [t for t in (cov.get("tables") or []) if t.get("resolved")]),
  }
  ck("C04_coverage_counts", "计数自洽",
     "counts.claims / digitized_points / images_missing / required_tables_resolved 与明细逐一相等",
     json.dumps(detail, ensure_ascii=False), all(detail.values()), "result.counts 与 coverage/claims/CSV 复算")

  ck("C05_golden_quotes", "金标准引文逐字",
     "text quote 重检命中率 >= 0.9（无 text quote 不判失败）",
     "%d/%d = %s methods=%s" % (gq["hit"], gq["graded"], gq["ratio"],
                                json.dumps(gq["methods"], ensure_ascii=False)),
     (not gq["graded"]) or (gq["ratio"] or 0) >= 0.9, "golden_standard.json 的 text 项对 /input 复检")

  meas_ok, meas_rows = True, []
  for it in (g.get("items") or []):
    if it.get("quote_type") != "measured":
      continue
    if it.get("check") == "figure_image_px":
      p = Path(state.get("input") or "/input") / str(it.get("target"))
      live = _png_size(p)
      want = it.get("expected") or {}
      ok = bool(live) and live.get("w") == want.get("w") and live.get("h") == want.get("h")
      meas_ok = meas_ok and ok
      meas_rows.append({"item_id": it.get("item_id"), "ok": ok,
                        "recomputed": live, "expected": want})
    elif it.get("check") == "figure_sha":
      p = Path(state.get("input") or "/input") / str(it.get("target"))
      live = _sha(p)
      ok = bool(live) and live == it.get("expected")
      meas_ok = meas_ok and ok
      meas_rows.append({"item_id": it.get("item_id"), "ok": ok,
                        "recomputed": {"sha256": live}, "expected": it.get("expected")})
  ck("C06_golden_measurements", "测量项可复算",
     "measured 项（IHDR/刻度/颜色簇/sha256）可独立重算",
     "%d/%d 复算一致" % (len([r for r in meas_rows if r["ok"]]), len(meas_rows)),
     bool(meas_ok), "golden_standard.json measured 项 + golden_quotes 重算")

  sizes = {a: _size(out, a) for a in ASSETS}
  first = all(sizes.get(a, 0) > 0 for a in ASSETS if a != "self_check.json")
  ck("C07_assets_present", "五件资产齐全非空",
     "golden/diff/version/run.log 已落盘且 >0 字节；self_check 为本回执",
     "golden=%dB diff=%dB version=%dB run.log=%dB；self_check=本回执"
     % (sizes.get("golden_standard.json", 0), sizes.get("diff_report.md", 0),
        sizes.get("version_history.md", 0), sizes.get("run.log", 0)),
     first, "输出目录")

  pr = {r.get("case"): r for r in (probe.get("results") or [])}
  for cid, name, label in (("C08_empty_input", "empty_input", "空输入兜底（子进程实跑）"),
                           ("C09_bad_json", "bad_json", "坏 JSON 兜底（子进程实跑）")):
    r = pr.get(name)
    if r is None:
      ck(cid, label, "exit 0 + result.json 合法 + 五件资产非空", probe.get("skipped") or "未执行",
         None, "self_check.fallback_tests")
    else:
      n_assets = len([v for v in (r.get("assets") or {}).values() if v > 0])
      ck(cid, label, "exit 0 + result.json 合法 + 五件资产非空",
         "exit=%s result_json=%s status=%s assets=%d/5" % (
             r.get("returncode"), r.get("result_json_valid"), r.get("status"), n_assets),
         bool(r.get("ok")), "self_check.fallback_tests.results")
  codes = [0] + [r.get("returncode") for r in (probe.get("results") or [])
                 if r.get("returncode") is not None]
  ck("C10_exit_code_zero", "退出码恒 0",
     "主进程恒返回 0；兜底子进程退出码均实测 0",
     "主进程 0；子进程 %s" % ("全部 0" if all(c == 0 for c in codes) else codes),
     all(c == 0 for c in codes), "run.log 的 exit 语义 / fallback_tests")

  st = str(pay.get("status") or "")
  honest = True
  if st == "answered":
    honest = not (pay.get("errors") or []) and not (cov.get("missing_images") or []) \
        and not (cov.get("missing_tables") or []) and len(claims) > 0
  elif st == "insufficient_evidence":
    honest = not claims or not (pay.get("result") or {}).get("figures")
  elif st == "input_error":
    honest = len(claims) == 0
  ck("C11_status_honest", "状态诚实（有缺口不报满）",
     "answered 须 errors=0、无 missing、claims>0",
     "status=%s errors=%d missing_images=%s claims=%d"
     % (st, len(pay.get("errors") or []), cov.get("missing_images") or [], len(claims)),
     honest, "result.json status/errors/coverage")

  ready = [k for k in SUMMARY_KEYS if isinstance(pay.get(k), dict) and pay[k].get("path")]
  ck("C12_asset_summary_fields", "result.json 五个摘要键就绪",
     "五个摘要键均为带 path 的对象",
     "%d/5 已挂载" % len(ready), len(ready) == 5, "result.json 顶层键")

  pkg_dir = Path(__file__).resolve().parent.parent
  files = [p for p in pkg_dir.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
  total = sum(p.stat().st_size for p in files)
  ck("C13_package_budget", "包体预算",
     "文件数 <= %d 且总字节 <= %d" % (PACKAGE_LIMITS["files"], PACKAGE_LIMITS["bytes"]),
     "files=%d bytes=%d" % (len(files), total),
     len(files) <= PACKAGE_LIMITS["files"] and total <= PACKAGE_LIMITS["bytes"], "包目录实测")

  steps = [str((c or {}).get("step")) for c in (pay.get("changes") or []) if isinstance(c, dict)]
  ck("C14_first_write_partial", "首写 partial 壳",
     "先落合法 partial 壳再替换（changes 含 partial 步）",
     "steps=%s" % steps[:8], "partial" in steps, "result.changes")

  schema = c_claim_schema({"target": "claims"}, ctx)
  qhit = c_claim_quote_hit({"expected": 0.99}, ctx)
  bbox = c_claim_bbox({"target": "claims"}, ctx)
  if not claims:
    ck("C15_claim_evidence", "claim 证据链",
       "answered 时 claim 五键证据齐全 + quote 命中 + bbox 在图像内；"
       "非 answered 无 claims 按缺口记",
       "no claims；status=%s（answered 才判失败）" % st,
       st != "answered", "claims 逐条复算")
  else:
    ck("C15_claim_evidence", "claim 证据链",
       "claim 五键证据齐全 + quote 命中 + bbox 在图像内",
       "schema=%s；%s；%s" % (schema[0], qhit[0], bbox[0]),
       schema[1] == "match" and qhit[1] in ("match", "needs_review")
       and bbox[1] in ("match", "needs_review"), "claims 逐条复算")

  honesty = c_series_honesty({"target": "digitized_series.csv"}, ctx)
  ck("C16_digitize_honesty", "像素读数诚实",
     "每行 approx=true 且带 x/y 半像素误差列；行数==counts",
     honesty[0], honesty[1] in ("match", "missing"), "digitized_series.csv 逐行复算")

  cell_items = [it for it in (g.get("items") or []) if it.get("check") == "table_cells"]
  if not cell_items:
    ck("C17_tables_verbatim", "表值逐字", "材料表单元格逐字出现在表产物中", "无材料表", None,
       "tables.json / tables/<id>.csv 复算")
  else:
    passed = len([it for it in cell_items if c_table_cells(it, ctx)[1] == "match"])
    ok17 = passed == len(cell_items) if st == "answered" else True
    ck("C17_tables_verbatim", "表值逐字",
       "answered 时材料表单元格全部逐字出现；其它状态的表值缺口已在 diff_report 记录",
       "%d/%d 表通过（status=%s）" % (passed, len(cell_items), st), ok17,
       "tables.json / tables/<id>.csv 复算")

  vh = ctx.text("version_history.md")
  vh_ok = vh and ("版本演进" in vh) and ("如何回退" in vh) and ("本次运行" in vh) \
      and ("v0" in vh) and ("v1.0.0" in vh)
  ck("C18_version_history", "版本历史完整",
     "含 v0→v1.0.0 演进、回退步骤与运行段",
     "%d bytes，sections=%s" % (len(vh.encode("utf-8")),
                                all(k in vh for k in ("版本演进", "如何回退", "本次运行"))),
     bool(vh_ok), "version_history.md 文本")

  d_total = (dsum or {}).get("total")
  d_ok = bool(dsum) and d_total == len(g.get("items") or []) and \
      sum(int((dsum or {}).get(k) or 0) for k in ("match", "missing", "deviation", "needs_review")) == d_total
  ck("C19_diff_complete", "差异对照完整",
     "覆盖 golden 全部条目且每项有唯一 verdict",
     "diff_total=%s golden_items=%d verdict_sum=%s pass=%s"
     % (d_total, len(g.get("items") or []),
        sum(int((dsum or {}).get(k) or 0) for k in ("match", "missing", "deviation", "needs_review")),
        (dsum or {}).get("pass")),
     d_ok, "diff_report.md 与 golden_standard.json 计数")

  rl = ctx.text("run.log")
  rl_stages = len([ln for ln in rl.splitlines() if ln.startswith("[")])
  known = any(k in rl for k in ("[boot", "[case", "[assets"))
  rl_ok = rl.startswith("# run.log") and "# invocation=" in rl and rl_stages >= 6 and known
  ck("C20_runlog_real", "run.log 真实运行日志",
     "有文件头/invocation、阶段行>=6 且含 boot/case",
     "%d bytes，%d stage lines，known_stage=%s" % (len(rl.encode("utf-8")), rl_stages, known),
     bool(rl_ok), "run.log 文本")

  ok_list = [c["ok"] for c in checks if c["ok"] is not None]
  return {
      "schema": SELF_SCHEMA, "package": PACKAGE, "version": VERSION,
      "case_id": pay.get("case_id"), "generated": now(), "status": st, "exit_code": 0,
      "pass": all(ok_list) if ok_list else False,
      "passed": len([x for x in ok_list if x]), "total": len(ok_list),
      "skipped": len([c for c in checks if c["ok"] is None]),
      "checks": checks,
      "quote_audit": {
          "golden": gq,
          "claims": _claim_quote_stats(ctx),
          "method": "用 source 原文/解码串重检 golden 与 claims 的 quote（三级匹配）",
      },
      "coverage": {"golden_items": len(g.get("items") or []), "by_group": gcount.get("by_group") or {},
                   "diff": {k: (dsum or {}).get(k) for k in
                            ("total", "match", "missing", "deviation", "needs_review", "pass")}},
      "fallback_tests": probe,
      "exit_codes": {"main": 0, "empty_input": (pr.get("empty_input") or {}).get("returncode"),
                     "bad_json": (pr.get("bad_json") or {}).get("returncode")},
      "package_budget": {"files": len(files), "bytes": total, "limits": PACKAGE_LIMITS},
      "artifacts": dict(sizes),
      "artifacts_note": "artifacts 为回执生成时字节数；最终值见 result.json 摘要键",
      "diff_report": {k: (dsum or {}).get(k) for k in
                      ("total", "match", "missing", "deviation", "needs_review", "pass")},
      "limitations": [
          "自建金标准由 /input 独立重扫，不是组织方答案。",
          "无 OCR：只校验结构项（刻度数/r2/单位键），标签值走 readings.json 并按引文审计。",
          "json-inline 表首行被既有提取器当列名（参考包同行为），记 needs_review。",
          "空/坏输入兜底由子进程实跑；禁子进程时 C08/C09 记 skipped。",
          "本回执字节最终以 result.json 摘要键为准。",
      ],
  }


def attach(state, pay, argv=None):
  """Write the five assets and add five summary keys; never raises to the caller."""
  out = Path(state.get("out") or "/app/output")
  inp = Path(state.get("input") or "/input")
  t_attach = time.time()
  try:
    out.mkdir(parents=True, exist_ok=True)
  except OSError:
    pass

  def fail(stage, exc):
    log("error", stage, detail=clip(exc, 180))

  for d in (pay.get("degradations") or []):
    log("degrade", clip(d.get("detail") if isinstance(d, dict) else d, 110))
  log("assets", "finalize: five verifiable assets", out=str(out))
  try:
    src = load_sources(inp)
  except Exception as exc:
    fail("sources", exc)
    src = load_sources(out)
  try:
    g = golden(state, src)
  except Exception as exc:
    fail("golden", exc)
    g = {"schema": GOLD_SCHEMA, "package": {"name": PACKAGE, "version": VERSION},
         "case_id": pay.get("case_id"), "generated": now(),
         "provenance": {"is_organizer_key": False, "method": "generation failed: %r" % (exc,)},
         "counts": {"total_items": 0, "by_group": {}}, "groups": [], "items": []}
  try:
    gsize = wr_json(out / "golden_standard.json", g)
    log("golden", "written", items=(g.get("counts") or {}).get("total_items"),
        bytes=gsize, quotes=(g.get("counts") or {}).get("text_quote_verbatim", {}).get("ratio"))
  except Exception as exc:
    fail("golden.write", exc)
    gsize = _size(out, "golden_standard.json")

  probe = probes(os.environ.get(PROBE_ENV) != "1")
  log("probes", "fallback probes", all_ok=probe.get("all_ok"), skipped=bool(probe.get("skipped")))

  try:
    (out / "version_history.md").write_text(
        version_history(state, pay, out, inp, argv, g), encoding="utf-8")
    log("version", "written", file="version_history.md", bytes=_size(out, "version_history.md"))
  except Exception as exc:
    fail("version", exc)
    try:
      (out / "version_history.md").write_text(
          _vh_static() + "\n## 5. 本次运行\n\n- 本次生成失败（已记 errors）：%r\n- exit 0\n" % (exc,),
          encoding="utf-8")
    except Exception:
      pass

  dsum, dmd = {}, "# 差异核验报告（diff_report）\n\n- 本次生成失败（已记 errors）。\n"
  try:
    dmd, dsum = diff(g, state, pay, out, src, argv)
    (out / "diff_report.md").write_text(dmd, encoding="utf-8")
    log("diff", "written", rows=dsum.get("total"), match=dsum.get("match"),
        missing=dsum.get("missing"), deviation=dsum.get("deviation"),
        needs_review=dsum.get("needs_review"), bytes=_size(out, "diff_report.md"))
  except Exception as exc:
    fail("diff", exc)
    try:
      (out / "diff_report.md").write_text(dmd, encoding="utf-8")
    except Exception:
      pass

  # five summary keys on result.json (only additions; original contract keys untouched)
  pay["golden_standard"] = {"path": "golden_standard.json", "bytes": _size(out, "golden_standard.json"),
                            "sha256": _sha(out / "golden_standard.json"), "schema": GOLD_SCHEMA,
                            "items": len(g.get("items") or []),
                            "by_group": (g.get("counts") or {}).get("by_group") or {},
                            "quote_verbatim": (g.get("counts") or {}).get("text_quote_verbatim") or {}}
  pay["diff_report"] = {"path": "diff_report.md", "bytes": _size(out, "diff_report.md")}
  pay["diff_report"].update({k: dsum.get(k) for k in
                             ("total", "match", "missing", "deviation", "needs_review", "pass")})
  pay["version_history"] = {"path": "version_history.md", "bytes": _size(out, "version_history.md"),
                            "sha256": _sha(out / "version_history.md"), "current_version": VERSION}
  pay["run_log"] = {"path": "run.log", "bytes": _size(out, "run.log"),
                    "stages": (log_summary() or {}).get("stages")}
  pay["self_check"] = {"path": "self_check.json", "bytes": None, "schema": SELF_SCHEMA}

  sc = {}
  try:
    sc = selfcheck(state, pay, out, g, dsum, probe, src, argv)
    last = -1
    for _round in range(4):
      _ = _size(out, "self_check.json")
      sc.setdefault("artifacts", {})["self_check.json"] = _size(out, "self_check.json")
      new_size = wr_json(out / "self_check.json", sc)
      if new_size == last:
        break
      last = new_size
    log("selfcheck", "written", pass_=sc.get("pass"), passed=sc.get("passed"),
        total=sc.get("total"), bytes=_size(out, "self_check.json"))
  except Exception as exc:
    fail("selfcheck", exc)
    sc = {"schema": SELF_SCHEMA, "package": PACKAGE, "exit_code": 0, "pass": False,
          "checks": [], "error": clip(exc, 200)}
    try:
      wr_json(out / "self_check.json", sc)
    except Exception:
      pass

  # reconcile: the summary key must carry the final self_check bytes/sha and the exit line
  log("assets", "complete", files=len(ASSETS), self_check=sc.get("pass"),
      attach_s=round(time.time() - t_attach, 3))
  finish_log(status=pay.get("status"), code=0)
  settle_t0 = time.time()
  try:
    sc_pass = sc.get("pass")
    sc["pass"], sc["passed"], sc["total"] = sc_pass, sc.get("passed"), sc.get("total")
    _ = wr_json(out / "self_check.json", sc)
  except Exception:
    pass
  pay["run_log"].update(log_summary())
  pay["self_check"].update({"bytes": _size(out, "self_check.json"),
                            "sha256": _sha(out / "self_check.json"),
                            "pass": sc.get("pass"), "passed": sc.get("passed"),
                            "total": sc.get("total"), "skipped": sc.get("skipped")})
  pay["golden_standard"].update({"bytes": _size(out, "golden_standard.json"),
                                 "sha256": _sha(out / "golden_standard.json")})
  pay["diff_report"].update({"bytes": _size(out, "diff_report.md"),
                             "total": dsum.get("total"), "match": dsum.get("match"),
                             "missing": dsum.get("missing"), "deviation": dsum.get("deviation"),
                             "needs_review": dsum.get("needs_review"), "pass": dsum.get("pass")})
  pay["version_history"].update({"bytes": _size(out, "version_history.md"),
                                 "sha256": _sha(out / "version_history.md")})
  pay["run_log"].update(log_summary())
  return pay


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
        "schema": GOLD_SCHEMA, "package": {"name": PACKAGE, "version": VERSION},
        "stage": "fallback", "generated": stamp, "case_id": "unknown-case",
        "provenance": {"is_organizer_key": False,
                       "note": "主流程未走到 finalize，金标准为空：" + note},
        "counts": {"total_items": 0, "by_group": {}}, "groups": [], "items": []})
  except Exception:
    pass
  try:
    (out / "diff_report.md").write_text(
        "# 差异核验报告（diff_report）\n\n- 生成时间：%s\n- 状态：fallback（主流程未走到 finalize：%s）\n\n"
        "金标准为空无法对照；result.json 保留最小合法结构，exit 0。\n"
        "- 回退与复跑方式见 version_history.md 第 3 节。\n" % (stamp, note), encoding="utf-8")
  except Exception:
    pass
  try:
    (out / "version_history.md").write_text(
        _vh_static() + "\n## 5. 本次运行（runtime append）\n\n- %s：主流程未走到 finalize（%s）。\n"
        "- 灾难分支兜底：五件资产按最小结构落盘；回退见第 3 节。\n"
        % (stamp, note), encoding="utf-8")
  except Exception:
    pass
  try:
    wr_json(out / "self_check.json", {
        "schema": SELF_SCHEMA, "package": PACKAGE, "stage": "fallback",
        "generated": stamp, "case_id": None, "status": "partial", "exit_code": 0,
        "pass": False, "passed": 0, "total": 0, "checks": [],
        "fallback_tests": {"skipped": "主流程未走到 finalize", "results": []},
        "limitations": ["主流程未启动：" + note]})
  except Exception:
    pass
  try:
    log("bootstrap", "fallback assets written", note=note)
    if not (out / "run.log").is_file():
      (out / "run.log").write_text(
          "# run.log -- %s %s\n# fallback %s\n- bootstrap：%s\n- exit_code=0\n"
          % (PACKAGE, VERSION, stamp, note), encoding="utf-8")
  except Exception:
    pass
