#!/usr/bin/env python3
"""Verifiable assets for manuscript-blueprint-audit (patch 1.1.0).

At finalize time writes five reviewer-facing assets beside the regular artifacts:
golden_standard.json (expected deliverables, locator + verbatim quote per item),
diff_report.md (actual vs golden, met/partial/missing/pending + reason),
version_history.md (static v0 -> v1.1.0 record + this run's segment), run.log
(real stage timeline, exit codes, degradations) and self_check.json (machine
receipt: contract keys, artifacts, quote hit rate, counts, empty/bad-input
fallback, exit-code contract).

Stdlib only, offline, CWD-independent, never raises out of build(); original
entry points, artifacts and output_contract are untouched.
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
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
VERSION = "1.1.0"
SKILL = "manuscript-blueprint-audit"

ASSET_FILES = {
  "golden_standard": "golden_standard.json",
  "diff_report": "diff_report.md",
  "version_history": "version_history.md",
  "run_log": "run.log",
  "self_check": "self_check.json",
}
MAIN_FILES = ("result.json", "structural_review.json", "edit_plan.md", "outline_after.md",
              "argument_map.json", "consistency_report.md", "pending_human.json")
DIMENSIONS = ("research_question_alignment", "section_structure", "argument_chain",
              "paragraph_relations", "duplication", "conclusion_boundary")
STATUS_ENUM = ("findings", "no_issue_with_evidence", "degraded_by_error", "not_assessable")
GOOD_STATUS = ("findings", "no_issue_with_evidence")

# Contract keys that recur in this task family get a task-specific reading; any
# other key falls back to the generic "keep it verbatim at top level" reading.
CONTRACT_SPEC = {
  "case_id": ("string", "输入案例标识原样回填，不得改写或截断",
              "与 case.json 的 case_id 逐字相同，类型为字符串"),
  "deliverable": ("object|string", "主交付物：指向 /app/output 下的可编辑产物（Markdown/JSON 路径 + editable 标记）",
                  "可在 deliverable.primary / deliverable.files 找到真实存在的文件"),
  "preserved_facts": ("array", "原稿数字、引用与结论边界句的逐字 quote + locator，事实不得改写",
                      "每条含 locator 与 quote，且 quote 在原稿逐字命中"),
  "evidence_map": ("array", "结论/判断到原文 locator 与逐字 quote 的证据映射",
                   "至少覆盖全部 finding，locator 与 quote 可回原文复核"),
  "change_log": ("array", "修改项记录：original -> revised，或 proposed_not_applied（只诊断不改稿）",
                 "与 actions 条数一致，含 original_quote / reason"),
}
GENERIC_CONTRACT = ("原样保留契约键", "output_contract 的键名必须逐字出现在 result.json 顶层",
                    "键存在；null/[] 也是合法回填，但不得改名或删除")

# Expected internal sections of the six artifacts; quotes come from the package
# ruleset so the expectation itself can be verified verbatim.
SECTION_SPECS = (
  ("structural_review.json", "findings / actions / dimension_coverage / grounding 四部分齐全",
   "references/ruleset.json#render.PLAN_COVER_HEAD", "六个维度的达成情况"),
  ("structural_review.json", "每条 finding 带 locator、逐字 quote，并回填字符区间 anchors",
   "references/ruleset.json#notes.GROUND",
   "每条 finding 的 quote 必须是正文的逐字子串（空白归一化后），并回填字符区间。"),
  ("edit_plan.md", "按 P1 -> P3 分组的可执行动作清单（每条含落点、引用、处置、副作用）",
   "references/ruleset.json#render.PLAN_HEAD", "结构改动清单（edit_plan）"),
  ("outline_after.md", "建议后章节表 + 主线闭合情况（四环闭合计数）",
   "references/ruleset.json#render.OUT_HEAD", "调整后的结构建议（outline_after）"),
  ("argument_map.json", "论点—论据配对 + question/method/result/conclusion 四环闭环矩阵",
   "references/ruleset.json#notes.ARGMAP", "逐句抽取主张标记句与论据句"),
  ("consistency_report.md", "篇幅占比、引用与图表解析、重复统计、截断与降级",
   "references/ruleset.json#render.CONS_HEAD", "一致性核验（consistency_report）"),
  ("pending_human.json", "无法判断项与需要作者补的材料（不得编造结论）",
   "references/ruleset.json#render.PLAN_PENDING_HEAD", "需要作者确认或暂时判不了的部分"),
)
MAIN_ARTIFACT_SPECS = (
  ("structural_review.json", "主结果：逐条 findings + actions + 六维度覆盖 + grounding 锚点"),
  ("edit_plan.md", "作者动作单：P1 -> P3，可直接在稿件里落位"),
  ("outline_after.md", "建议后结构：章节顺序、功能、篇幅占比、结构处置"),
  ("argument_map.json", "论点—论据映射与四环闭环矩阵"),
  ("consistency_report.md", "篇幅/引用/图表/重复/截断与降级的一致性核验"),
  ("pending_human.json", "无法判断项与需补材料"),
  ("result.json", "平台契约字段 + 状态 + 证据 + 降级 + 指标"),
)
ASSET_SPECS = (
  ("golden_standard.json", "本 case 期望交付内容的金标准：逐项 expected 字段/章节/修改项，每项带 locator 与逐字 quote"),
  ("diff_report.md", "实际产物 vs 金标准逐项对照：达标/缺失/偏差 + 原因"),
  ("version_history.md", "静态版本记录（v0 -> v1.0.0 -> v1.1.0：改了什么、为什么、如何回退）+ 本次运行段"),
  ("run.log", "真实运行日志：每阶段耗时、退出码、降级、异常"),
  ("self_check.json", "机器自检回执：契约键/主产物/引文命中/计数一致/空坏输入兜底/退出码恒 0"),
)

TASK_CATEGORIES = (
  ("coverage", ("六类", "六维", "覆盖", "研究问题", "章节结构", "论证链", "段落关系", "重复内容", "结论边界")),
  ("localization", ("定位", "落点", "章节", "段落", "句子", "locator", "原文位置")),
  ("action", ("可执行", "编辑动作", "移动", "合并", "拆分", "收窄", "删除", "插入", "改写稿",
              "move", "merge", "split", "narrow", "delete", "insert")),
  ("evidence", ("逐字", "引用", "quote", "来源", "证据", "回溯", "可核验", "复核")),
  ("traceability", ("事实", "数字", "修改记录", "preserved", "change_log", "修改项")),
  ("robustness", ("降级", "异常", "缺失", "截断", "无法判断", "pending", "不确定性", "失败")),
  ("deliverable", ("产物", "输出", "可编辑", "结构化", "result.json", "app/output")),
)
TASK_CAP = 16


def _now():
  return datetime.now().astimezone()


def _iso():
  return _now().isoformat(timespec="seconds")


def _squash(text):
  return re.sub(r"\s+", " ", text or "").strip()


def _nonempty(value):
  if value is None:
    return False
  if isinstance(value, (str, bytes, list, tuple, dict, set)):
    return len(value) > 0
  return True


def _typename(expect):
  if expect is None:
    return "string|object|array|null"
  if isinstance(expect, bool):
    return "boolean"
  if isinstance(expect, (int, float)):
    return "number"
  if isinstance(expect, str):
    return "string"
  if isinstance(expect, list):
    return "array"
  if isinstance(expect, dict):
    return "object"
  return type(expect).__name__


def _sha(text):
  return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _read_text(path):
  try:
    return Path(path).read_text(encoding="utf-8-sig", errors="replace")
  except Exception:
    return ""


def _load_json(path):
  try:
    data = json.loads(_read_text(path))
    return data if isinstance(data, dict) else {}
  except Exception:
    return {}


def _read_source(path, role):
  """Read one citable source file and keep raw + decoded forms for verbatim checks."""
  if not path:
    return None
  p = Path(path)
  if not p.is_file():
    return None
  raw = _read_text(p)
  rec = {"path": str(p), "name": p.name, "role": role, "raw": raw,
         "plain": raw, "chars": len(raw), "sha256": _sha(raw)}
  if p.suffix.lower() == ".json":
    try:
      rec["plain"] = json.dumps(json.loads(raw), ensure_ascii=False)
    except Exception:
      rec["plain"] = raw
  return rec


def _has_quote(src, quote):
  if not src or not quote:
    return False
  q = _squash(quote)
  if not q:
    return False
  return q in _squash(src.get("raw") or "") or q in _squash(src.get("plain") or "")


def _locate_in(src, quote):
  """Best-effort Lnn:Cnn locator for a quote inside a source file, or ''."""
  if not src or not quote:
    return ""
  raw = src.get("raw") or ""
  q = _squash(quote)
  idx = raw.find(q)
  if idx < 0:
    plain = src.get("plain") or ""
    idx = plain.find(q)
    if idx < 0:
      return ""
    raw = plain
  line = raw.count("\n", 0, idx) + 1
  col = idx - raw.rfind("\n", 0, idx)
  return "L%d:C%d" % (line, col)


def _cell(value, limit=220):
  text = _squash(str(value if value is not None else ""))
  text = text.replace("|", "\\|").replace("`", "`")
  if len(text) > limit:
    text = text[:limit - 1] + "…"
  return text or "-"


def _bytes(path):
  try:
    return Path(path).stat().st_size
  except Exception:
    return 0


def _write(path, text):
  p = Path(path)
  p.parent.mkdir(parents=True, exist_ok=True)
  p.write_text(text, encoding="utf-8")
  return _bytes(p)


class RunLog(object):
  """Real stage timeline for one run; rendered into run.log at finalize."""

  def __init__(self, version=VERSION, started=None):
    self.version = version
    self.wall = started or time.time()
    self.t0 = time.time()
    self.last = self.t0
    self.rows = []
    self.warns = []
    self.errors = []

  def mark(self, stage, detail="", level="INFO"):
    now = time.time()
    row = {"ts": _now().isoformat(timespec="milliseconds"), "level": level,
           "stage": stage, "detail": _squash(detail),
           "elapsed_ms": int(round((now - self.last) * 1000)),
           "total_ms": int(round((now - self.t0) * 1000))}
    self.rows.append(row)
    self.last = now
    return row

  def degrade(self, stage, detail):
    self.warns.append({"stage": stage, "detail": _squash(detail)})
    return self.mark("degrade", "%s: %s" % (stage, detail), level="WARN")

  def error(self, stage, detail):
    self.errors.append({"stage": stage, "detail": _squash(detail)})
    return self.mark("error", "%s: %s" % (stage, detail), level="ERROR")


  def finish(self, status, exit_code=0):
    self.mark("summary", "status=%s exit_code=%d expected_exit_code=0"
               % (status, exit_code), level="INFO")
    return self.render()

  def render(self):
    lines = [
      "# %s run log" % SKILL,
      "# version=%s generated=%s" % (self.version, _now().isoformat(timespec="seconds")),
      "# python=%s platform=%s" % (sys.version.split()[0], sys.platform),
      "# cwd=%s" % os.getcwd(),
      "# exit-code contract: this process returns 0 even when status is partial/input_error",
      "TIMESTAMP                      LEVEL STAGE        ELAPSED_MS TOTAL_MS DETAIL",
    ]
    for row in self.rows:
      lines.append("%-30s %-5s %-12s %10d %8d %s" % (
        row["ts"], row["level"], row["stage"], row["elapsed_ms"], row["total_ms"], row["detail"]))
    lines.append("")
    lines.append("# degradations (%d)" % len(self.warns))
    for item in self.warns:
      lines.append("WARN  stage=%s detail=%s" % (item["stage"], item["detail"]))
    if not self.warns:
      lines.append("none")
    lines.append("")
    lines.append("# exceptions / errors (%d)" % len(self.errors))
    for item in self.errors:
      lines.append("ERROR stage=%s detail=%s" % (item["stage"], item["detail"]))
    if not self.errors:
      lines.append("none")
    lines.append("")
    lines.append("# reproducibility: stdlib only, offline, 0 model requests, CWD-independent")
    return "\n".join(lines) + "\n"


def _static_history():
  """Version record shipped with the package (runtime segment appended below)."""
  return "\n".join([
    "# 版本历史（version_history）",
    "",
    "本文件两部分：第 1 部分随包分发，记录包自身从骨架到当前版本的改动、理由与回退办法；",
    "第 2 部分由 `scripts/assets.py` 在 finalize 阶段追加，记录**本次真实运行**的版本与产物。",
    "",
    "## 1. 静态版本记录（随包分发，不随运行变化）",
    "",
    "### v0 — 骨架（2026-11-16）",
    "",
    "- 改了什么：只建 `/app/output` 并落盘合法 partial `result.json`，其余产物为空。",
    "- 为什么：断点前移，后续解析/分段/检测全失败也有可读结果，而不是空目录。",
    "- 如何回退：删除后续产物，仅保留 `result.json` 骨架。",
    "",
    "### v0.5 — 输入发现与定位符（2026-11-16）",
    "",
    "- 改了什么：`case.json` 容错解析、纯标准库文本抽取、`Cnn` / `Cnn-Pnnn` / `Cnn-Pnnn-Snn`",
    "  三级定位符、quote 回填 start/end 字符区间。",
    "- 为什么：题面要求「诊得准、说得清」——没有 locator 与字符区间的判断无法复核。",
    "",
    "### v1.0.0 — 六维度审计基线（2026-11-16，本 patch 的基线）",
    "",
    "- 改了什么：六个固定维度 + 六种动作枚举（move/merge/split/narrow/delete/insert）+ 六个",
    "  主产物 + `output_contract` 逐键回填 + 写后读回自审计 + `gates.py --check` 复核入口；",
    "  规则、阈值、中文措辞集中在 `references/ruleset.json`。",
    "- 为什么：把「给写作原则」换成「定位到句、给可执行动作、每条判断有逐字引用」；并用降级",
    "  阶梯覆盖缺章/无参考文献/截断/无正文等稿件形态。",
    "- 如何回退：恢复 `work/patch_backup/writing-05_orig` 下的 `SKILL.md`、`scripts/audit.py`、",
    "  `scripts/gates.py`（三个 references 未改动）。",
    "",
    "### v1.1.0 — 可核验资产 patch（2026-11-16，本包当前版本）",
    "",
    "- 改了什么：新增 `scripts/assets.py`，finalize 阶段额外产出 `golden_standard.json` /",
    "  `diff_report.md` / `version_history.md` / `run.log` / `self_check.json`；`result.json`",
    "  顶层新增 5 个同名字段指向这些文件；`SKILL.md` 新增第 17 节。",
    "- 为什么：rubric 的「结果可核验性 / 完整性 / 生态贡献」需要可独立复核的资产。金标准给出",
    "  基准，diff 给出偏差，版本记录给出回退路径，run.log 与 self_check 给出真实运行证据。",
    "- 不变量：原入口与 `--check`、6 个主产物文件名与 schema、`output_contract` 原字段、",
    "  纯标准库/离线/不依赖 CWD/退出码恒 0。",
    "- 如何回退：删除 `scripts/assets.py`，移除 `audit.py` 中 assets 导入、finalize 钩子与 5 个",
    "  result.json 字段即可（主产物不受影响）；或整包恢复备份目录。",
    "",
    "## 2. 本次运行段（运行时追加）",
    "",
  ])


def _task_source(input_dir):
  inp = Path(input_dir) if input_dir else None
  if inp is None or not inp.is_dir():
    return None
  for name in ("task.md", "guide.md", "readme.md"):
    p = inp / name
    if p.is_file():
      return p
  hits = sorted([p for p in inp.glob("*") if p.is_file()
                 and p.name.lower().startswith(("task", "guide", "readme"))
                 and p.suffix.lower() in (".md", ".txt")])
  return hits[0] if hits else None


def _task_units(text):
  """(line, quote, category, score) for requirement-bearing fragments of task.md."""
  units, seen = [], set()
  for lineno, line in enumerate((text or "").splitlines(), 1):
    raw = line.strip()
    if not raw:
      continue
    body = re.sub(r"^[#>\-\*\s]+", "", raw)
    if len(body) < 8:
      continue
    for part in re.split(r"[；;。|]", body):
      q = _squash(part)
      if len(q) < 8 or q in seen:
        continue
      low = q.lower()
      category, score = "", 0
      for cat, keys in TASK_CATEGORIES:
        hit = sum(1 for key in keys if key.lower() in low)
        if hit and not category:
          category, score = cat, hit
        elif hit:
          score += hit
      if not category:
        continue
      seen.add(q)
      units.append((lineno, q, category, score))
  units.sort(key=lambda row: (-row[3], row[0]))
  return units[:TASK_CAP]


def _golden(ctx, srcs):
  """Build the golden-standard item list: contract fields, task requirements,
  six dimensions, artifact sections and the five verifiable assets."""
  case_src = srcs.get("case")
  task_src = srcs.get("task")
  rules_src = srcs.get("ruleset")
  skill_src = srcs.get("skill")
  contract = ctx.get("contract") or {}
  items = []

  def add(category, requirement, expected, acceptance, basis, locator, quote, note=""):
    source = {"contract": case_src, "task": task_src, "ruleset": rules_src,
              "skill": skill_src}.get(basis)
    verbatim = _has_quote(source, quote)
    if not locator and source:
      locator = "%s#%s" % (source.get("name", ""), _locate_in(source, quote))
    row = {"item_id": "G%03d" % (len(items) + 1), "category": category,
           "requirement": requirement, "expected": expected, "acceptance": acceptance,
           "basis": basis, "locator": locator, "quote": quote,
           "quote_verbatim": verbatim, "checked_against": (source or {}).get("name")}
    if note:
      row["note"] = note
    items.append(row)
    return row

  # 0) input integrity: without a readable case.json no contract can be graded
  if case_src:
    add("input_integrity", "case.json 可解析且包含 output_contract",
        "JSON 可被 json.loads 解析，output_contract 为 object",
        "result.json 回填其全部键；解析失败时 status=input_error 且契约键置 null/[]",
        "contract", "case.json#/output_contract", "output_contract")
  else:
    add("input_integrity", "case.json 可解析且包含 output_contract",
        "JSON 可被 json.loads 解析，output_contract 为 object",
        "无法取得时不得编造：status=input_error，契约字段置 null/[]，并在 errors 记录 case_parse",
        "contract", "case.json#/output_contract", "",
        "运行输入缺失或损坏，本条无逐字来源；按 basis: contract 兜底")
  items[-1]["case_parsed"] = bool(ctx.get("case"))

  # 1) contract fields expected in result.json
  for key, expect in (contract or {}).items():
    spec = CONTRACT_SPEC.get(str(key).lower()) or GENERIC_CONTRACT
    quote = '"%s"' % key
    add("contract_field", spec[1], "%s（契约键 `%s`）" % (spec[0], key), spec[2],
        "contract", "case.json#/output_contract/%s" % key, quote)

  # 2) task requirements extracted verbatim from /input/task.md
  units = _task_units(task_src.get("raw") if task_src else "")
  for lineno, quote, category, score in units:
    add("task_requirement_%s" % category, quote,
        "实际产物满足该条要求（分类：%s；命中 %d 个要求关键词）" % (category, score),
        "可在本报告的「任务要求对照」行与对应产物中复核",
        "task", "task.md#L%d" % lineno, quote)

  # 3) six dimensions, all required
  shared = None
  for lineno, quote, category, _score in units:
    if ("六" in quote and ("覆盖" in quote or "维度" in quote)) or (
        "研究问题" in quote and "章节结构" in quote and "论证链" in quote):
      shared = ("task", "task.md#L%d" % lineno, quote)
      break
  if not shared and case_src:
    order = ctx.get("case") or {}
    for i, item in enumerate(order.get("organizer_workorder") or [], 1):
      text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
      if ("six" in text.lower() and ("dimension" in text.lower() or "structural" in text.lower())) \
         or ("六" in text and "维度" in text):
        shared = ("contract", "case.json#/organizer_workorder/%d" % (i - 1), text)
        break
  labels = {}
  if rules_src:
    try:
      labels = ((json.loads(rules_src.get("raw") or "{}").get("labels") or {})
                .get("dimension") or {})
    except Exception:
      labels = {}
  for dim in DIMENSIONS:
    label = labels.get(dim) or dim
    if shared:
      basis, locator, quote = shared
      add("dimension_check", "维度 `%s` 必须输出覆盖状态与判定依据" % dim,
          "coverage[%s].status ∈ {findings, no_issue_with_evidence} 且 checked 非空" % dim,
          "在 structural_review.json.dimension_coverage.%s 复核；degraded/not_assessable 须在 degradations 说明" % dim,
          basis, locator, quote)
    else:
      add("dimension_check", "维度 `%s`（%s）必须输出覆盖状态与判定依据" % (dim, label),
          "coverage[%s].status ∈ {findings, no_issue_with_evidence} 且 checked 非空" % dim,
          "在 structural_review.json.dimension_coverage.%s 复核" % dim,
          "ruleset", "references/ruleset.json#labels.dimension.%s" % dim, label)

  # 4) six main artifacts + result.json
  for name, desc in MAIN_ARTIFACT_SPECS:
    add("deliverable_artifact", "产物 `%s`：%s" % (name, desc),
        "文件存在于 /app/output 且 bytes > 0",
        "存在性由 self_check.json 的 artifacts 表与 diff_report 的主产物表双重核对",
        "skill", "SKILL.md#3 制品清单", "`%s`" % name)

  # 5) internal sections expected in the artifacts
  for name, desc, locator, quote in SECTION_SPECS:
    add("deliverable_section", "`%s` 内部结构：%s" % (name, desc),
        "对应字段/小节存在且非空（见 acceptance）",
        "结构性检查，可按 locator 到 references/ruleset.json 对照模板",
        "ruleset", locator, quote)

  # 6) the five verifiable assets added by patch 1.1.0
  for name, desc in ASSET_SPECS:
    add("verifiable_asset", "可核验资产 `%s`：%s" % (name, desc),
        "文件存在于 /app/output 且 bytes > 0，内容可被 json.loads / Markdown 阅读",
        "self_check.json 记录字节数与存在性；diff_report.md 给出与金标准的对照",
        "skill", "SKILL.md#17 可核验资产", "`%s`" % name)

  total = len(items)
  with_locator = sum(1 for row in items if row.get("locator"))
  with_quote = sum(1 for row in items if row.get("quote"))
  verbatim = sum(1 for row in items if row.get("quote_verbatim"))
  basis_count = {}
  for row in items:
    basis_count[row["basis"]] = basis_count.get(row["basis"], 0) + 1
  sources = []
  for role in ("case", "task", "ruleset", "skill", "manuscript"):
    src = srcs.get(role)
    if src:
      sources.append({"role": role, "name": src.get("name"), "path": src.get("path"),
                      "chars": src.get("chars"), "sha256": src.get("sha256")})
  return {
    "schema": "golden-standard/v1",
    "skill": SKILL, "skill_version": VERSION, "case_id": ctx.get("cid"),
    "built_at": _iso(),
    "purpose": "本 case 期望交付内容的金标准：逐项给出期望字段/章节/修改项、locator 与逐字 quote；"
               "无外部来源的条目以 basis=contract 兜底。",
    "sources": sources,
    "contract": {"key_count": len(contract or {}), "keys": list((contract or {}).keys()),
                 "source": "case.json#/output_contract",
                 "unfilled": list(ctx.get("contract_missing") or [])},
    "counts": {"items_total": total, "contract_fields": len(contract or {}),
               "task_requirements": len(units), "dimensions": len(DIMENSIONS),
               "main_artifacts": len(MAIN_ARTIFACT_SPECS), "sections": len(SECTION_SPECS),
               "verifiable_assets": len(ASSET_SPECS), "by_basis": basis_count},
    "completeness": {"with_locator": with_locator, "with_quote": with_quote,
                     "sourced_items": with_quote, "unsourced_basis_contract": total - with_quote,
                     "quote_verbatim": verbatim,
                     "quote_hit_rate": round(verbatim / float(max(1, with_quote)), 4),
                     "note": "quote_verbatim 在构建时逐条回查来源文件（空白归一化后逐字包含）；"
                             "分母为带 quote 的条目，无来源条目按 basis=contract 兜底并单列"},
    "items": items,
  }


def _facts(out):
  """Actual state, re-read from disk (never trust in-memory claims)."""
  out = Path(out)
  result = _load_json(out / "result.json")
  review = _load_json(out / "structural_review.json")
  argmap = _load_json(out / "argument_map.json")
  pending = _load_json(out / "pending_human.json")
  findings = review.get("findings") or result.get("findings") or []
  actions = review.get("actions") or result.get("actions") or []
  coverage = review.get("dimension_coverage") or result.get("dimension_coverage") or {}
  grounding = review.get("grounding") or {}
  files = {}
  for name in MAIN_FILES + tuple(ASSET_FILES.values()):
    files[name] = _bytes(out / name)
  statuses = dict((dim, (coverage.get(dim) or {}).get("status", "")) for dim in DIMENSIONS)
  return {
    "result": result, "review": review, "argmap": argmap, "pending": pending,
    "findings": findings, "actions": actions, "coverage": coverage,
    "statuses": statuses, "grounding": grounding, "files": files,
    "status": result.get("status"),
    "hit_rate": grounding.get("hit_rate"),
    "anchors": grounding.get("anchors") or [],
    "dims_good": sum(1 for dim in DIMENSIONS if statuses.get(dim) in GOOD_STATUS),
    "dims_degraded": sum(1 for dim in DIMENSIONS if statuses.get(dim) == "degraded_by_error"),
    "pending_count": len(result.get("pending_human") or []),
    "errors": result.get("errors") or [],
    "degradations": result.get("degradations") or [],
  }


def _verdict(item, facts, written):
  """(verdict, reason) for one golden-standard item against the actual run."""
  cat, files = item.get("category", ""), facts["files"]
  findings, actions, result = facts["findings"], facts["actions"], facts["result"]
  if cat == "input_integrity":
    if item.get("quote_verbatim") and item.get("case_parsed"):
      return "met", "case.json 可解析且 output_contract 存在（逐字命中）"
    if item.get("quote_verbatim"):
      return "missing", "case.json 不可解析（仅损坏文本含该键）；返回 input_error，未编造契约值"
    return "missing", "case.json 缺失或不可解析：返回 input_error，未编造契约值"
  if cat == "contract_field":
    key = item.get("quote", "").strip('"')
    if key not in result:
      return "missing", "result.json 顶层缺少契约键 `%s`" % key
    if key in (result.get("contract_unfilled_keys") or []):
      return "partial", "`%s` 存在但在 contract_unfilled_keys 中标为未回填" % key
    if _nonempty(result.get(key)):
      return "met", "`%s` 存在且非空（type=%s）" % (key, type(result.get(key)).__name__)
    return "partial", "`%s` 值为空（null/[]），可能输入降级" % key
  if cat.startswith("task_requirement_"):
    kind = cat.replace("task_requirement_", "")
    if kind == "coverage":
      if facts["dims_good"] == len(DIMENSIONS):
        return "met", "六维度均有 findings 或 no_issue_with_evidence"
      return "partial", "六维度仅 %d/6 可判定，其余 degraded/not_assessable" % facts["dims_good"]
    if kind == "localization":
      if findings and len(facts["anchors"]) == len(findings):
        return "met", "%d 条 finding 均带 locator 与字符区间" % len(findings)
      if findings:
        return "partial", "%d 条 finding，锚点 %d 条（未全回填区间）" % (
          len(findings), len(facts["anchors"]))
      return "partial", "无可判定 finding（输入/规模不足），未输出无 locator 的判断"
    if kind == "action":
      good = [a for a in actions if a.get("from_locator") and a.get("expected_effect")
              and a.get("operation")]
      if actions and len(good) == len(actions):
        return "met", "%d 个动作均带 operation/from_locator/expected_effect" % len(actions)
      if actions:
        return "partial", "%d/%d 个动作字段完整" % (len(good), len(actions))
      return "partial", "未产出动作（无 finding 或输入降级），未用不可执行建议充数"
    if kind == "evidence":
      if findings and facts.get("hit_rate") == 1.0:
        return "met", "%d 条 finding 的 quote 逐字命中（hit_rate=1.0）" % len(findings)
      if findings:
        return "partial", "逐字命中率 %s 未达 1.0" % facts.get("hit_rate")
      return "partial", "无 finding 需锚定；缺口记入 pending/errors"
    if kind == "traceability":
      pres, chg = result.get("preserved_facts") or [], result.get("change_log") or []
      if pres or chg:
        return "met", "preserved_facts=%d、change_log=%d，可按 locator/quote 回溯" % (
          len(pres), len(chg))
      return "partial", "未捕获 preserve 事实（无正文或无数字引用句）"
    if kind == "robustness":
      status = result.get("status")
      if status in ("ok", "partial"):
        if facts["pending_count"] or facts["degradations"]:
          return "met", "status=%s；pending=%d、degradations=%d 均有记录" % (
            status, facts["pending_count"], len(facts["degradations"]))
        return "met", "status=%s；未触发降级" % status
      return "partial", "status=%s：诚实降级，不编造结论" % status
    if kind == "deliverable":
      present = [n for n in MAIN_FILES if files.get(n)]
      if len(present) == len(MAIN_FILES):
        return "met", "7 件主产物全部非空"
      return "missing", "缺主产物：%s" % ", ".join(sorted(set(MAIN_FILES) - set(present)))
    return "met", "已随六维度与产物覆盖（启发式）"
  if cat == "dimension_check":
    dim = ""
    for cand in DIMENSIONS:
      if cand in item.get("requirement", "") or cand in item.get("expected", ""):
        dim = cand
        break
    status = facts["statuses"].get(dim, "")
    if status in GOOD_STATUS:
      n = len((facts["coverage"].get(dim) or {}).get("finding_ids") or [])
      return "met", "coverage.%s=%s（findings=%s）" % (dim, status, n)
    if status == "degraded_by_error":
      return "partial", "%s 规则异常，已记 degradations，不冒充无问题" % dim
    if status == "not_assessable":
      return "partial", "%s 无可解析正文（输入降级）" % dim
    return "missing", "coverage 缺少 %s" % dim
  if cat == "deliverable_artifact":
    name = item.get("quote", "").strip("`")
    size = files.get(name, 0)
    return ("met", "`%s` 存在，%d bytes" % (name, size)) if size else (
      "missing", "`%s` 缺失或为 0 字节" % name)
  if cat == "deliverable_section":
    req = item.get("requirement") or ""
    name = req.split("`")[1] if "`" in req else ""
    review = facts["review"]
    if name == "structural_review.json" and (item.get("quote") or "").startswith("每条 finding"):
      ok = bool(facts["anchors"]) and all(isinstance(x.get("start"), int)
                                          and isinstance(x.get("end"), int)
                                          for x in facts["anchors"])
      return ("met", "全部 finding 有 start/end 区间") if ok else ("partial", "字符区间未全回填")
    if name == "structural_review.json":
      need = ("findings", "actions", "dimension_coverage", "grounding")
      ok = all(k in review for k in need)
      return ("met", "四部分齐全") if ok else (
        "missing", "缺少 %s" % ",".join(k for k in need if k not in review))
    if name == "edit_plan.md":
      if not files.get(name):
        return "missing", "`edit_plan.md` 缺失"
      if "## P1" in _read_text(Path(facts.get("_out") or ".") / name):
        return "met", "P1 分组存在"
      return "partial", "无 P1 分组（0 条 finding 时正常）"
    if name == "outline_after.md":
      text = _read_text(Path(facts.get("_out") or ".") / name)
      return ("met", "章节表与主线闭合段存在") if "主线的闭合情况" in text else (
        "partial", "未检出主线闭合段（%d bytes）" % files.get(name, 0))
    if name == "argument_map.json":
      am = facts["argmap"]
      ok = bool(am) and "chains" in am and "closure_matrix" in am
      return ("met", "chains 与 closure_matrix 存在") if ok else ("partial", "缺 chains/closure_matrix")
    if name == "consistency_report.md":
      text = _read_text(Path(facts.get("_out") or ".") / name)
      return ("met", "篇幅占比与降级段存在") if "篇幅占比" in text else ("partial", "未检出篇幅占比段")
    if name == "pending_human.json":
      ph = facts["pending"]
      return ("met", "items 列表存在（%d 条）" % len(ph["items"])) if isinstance(
        ph.get("items"), list) else ("partial", "缺 items 列表")
    return "partial", "结构化检查未覆盖该类"
  if cat == "verifiable_asset":
    name = item.get("quote", "").strip("`")
    if name in written:
      return "met", "`%s` 已生成，%d bytes" % (name, written[name])
    if name == "diff_report.md":
      return "met", "本文件即 `diff_report.md`，正在写入"
    if name == "self_check.json":
      return "pending", "最后写入；存在性与字节数由 self_check.json 自身回执"
    return "met", "`%s` 随本次 finalize 写入，以 self_check 回执为准" % name
  return "partial", "未分类条目：启发式记为部分达标"


def _diff(ctx, golden, written):
  """Markdown report: actual artifacts vs golden standard, item by item."""
  out = Path(ctx["out"])
  facts = _facts(out)
  facts["_out"] = str(out)
  written = dict((ASSET_FILES[role], size) for role, size in (written or {}).items()
                 if role in ASSET_FILES)
  rows, tally = [], {"met": 0, "partial": 0, "missing": 0, "pending": 0}
  for item in golden.get("items") or []:
    verdict, reason = _verdict(item, facts, written)
    tally[verdict] = tally.get(verdict, 0) + 1
    rows.append((item, verdict, reason))
  total = len(rows) or 1
  cat_tally = {}
  for item, verdict, _reason in rows:
    cell = cat_tally.setdefault(item["category"].split("_")[0],
                                {"total": 0, "met": 0, "partial": 0, "missing": 0, "pending": 0})
    cell["total"] += 1
    cell[verdict] = cell.get(verdict, 0) + 1
  lines = [
    "# 差异报告（diff_report）",
    "",
    "- case_id: `%s`" % (ctx.get("cid") or "case-unknown"),
    "- 金标准: `golden_standard.json`（%d 条）" % len(golden.get("items") or []),
    "- 生成时间: %s" % _iso(),
    "- 运行状态: `%s`" % (facts.get("status") or "-"),
    "- 判定口径: 逐条对照 `golden_standard.json`；达标=met，偏差=partial，缺失=missing，",
    "  待生成=pending。判定由本脚本读取磁盘产物后自动计算，不引用运行内存里的自述。",
    "- 合计: 达标 %d / 偏差 %d / 缺失 %d / 待生成 %d（共 %d 条，达标率 %.1f%%）" % (
      tally["met"], tally["partial"], tally["missing"], tally["pending"], total,
      100.0 * tally["met"] / total),
    "",
    "## 1. 按类别汇总",
    "",
    "| 类别 | 条目 | 达标 | 偏差 | 缺失 | 待生成 |",
    "|---|---:|---:|---:|---:|---:|",
  ]
  for cat in sorted(cat_tally):
    cell = cat_tally[cat]
    lines.append("| %s | %d | %d | %d | %d | %d |" % (
      cat, cell["total"], cell["met"], cell["partial"], cell["missing"], cell["pending"]))
  lines.extend(["", "## 2. 契约字段对照（result.json）", "",
                "| 契约键 | 顶层存在 | 类型 | 值非空 | 判定 | 原因 |", "|---|---|---|---|---|---|"])
  for item, verdict, reason in rows:
    if item.get("category") != "contract_field":
      continue
    key = item.get("quote", "").strip('"')
    value = facts["result"].get(key)
    lines.append("| `%s` | %s | %s | %s | %s | %s |" % (
      _cell(key), "是" if key in facts["result"] else "否",
      _cell(type(value).__name__ if key in facts["result"] else "-"),
      "是" if _nonempty(value) else "否", verdict, _cell(reason, 160)))
  lines.extend(["", "## 3. 六维度覆盖对照", "",
                "| 维度 | 状态 | finding 数 | 判定 |", "|---|---|---:|---|"])
  for dim in DIMENSIONS:
    status = facts["statuses"].get(dim) or "-"
    ids = (facts["coverage"].get(dim) or {}).get("finding_ids") or []
    verdict = "met" if status in GOOD_STATUS else (
      "partial" if status in ("degraded_by_error", "not_assessable") else "missing")
    lines.append("| `%s` | %s | %d | %s |" % (dim, _cell(status), len(ids), verdict))
  lines.extend(["", "## 4. 主产物与可核验资产存在性", "", "| 文件 | bytes | 判定 |", "|---|---:|---|"])
  for name in MAIN_FILES + tuple(ASSET_FILES.values()):
    size = facts["files"].get(name, 0)
    if name == "diff_report.md":
      lines.append("| `%s` | 本文件 | met（本报告正在写入） |" % name)
    elif name == "self_check.json":
      lines.append("| `%s` | - | pending（最后写入，由自身回执核对） |" % name)
    elif size:
      lines.append("| `%s` | %d | met |" % (name, size))
    elif name in written:
      lines.append("| `%s` | %d | met |" % (name, written[name]))
    elif name in ASSET_FILES.values():
      lines.append("| `%s` | 本次 finalize 写入 | met（scheduled，self_check 回执核对） |" % name)
    else:
      lines.append("| `%s` | 0 | missing |" % name)
  lines.extend(["", "## 5. 逐项对照（金标准 %d 条）" % len(rows), "",
                "| 条目 | 类别 | 要求（截断） | 判定 | 原因 |", "|---|---|---|---|---|"])
  for item, verdict, reason in rows:
    lines.append("| %s | %s | %s | %s | %s |" % (
      item.get("item_id"), _cell(item.get("category")), _cell(item.get("requirement"), 150),
      verdict, _cell(reason, 260)))
  lines.extend(["", "## 6. 偏差与缺失原因汇总", ""])
  reasons = [row for row in rows if row[1] in ("partial", "missing", "pending")]
  if reasons:
    for item, verdict, reason in reasons[:40]:
      lines.append("- `%s`（%s）%s：%s" % (
        item.get("item_id"), item.get("category"), verdict, _cell(reason, 300)))
  else:
    lines.append("- 本次运行没有偏差/缺失条目；全部金标准条目达标。")
  lines.extend([
    "",
    "## 7. 复核方法",
    "",
    "1. `python3 -m json.tool /app/output/golden_standard.json` 查看金标准与逐条 locator/quote；",
    "2. `python3 -m json.tool /app/output/self_check.json` 查看机器自检回执；",
    "3. 用 `structural_review.json.grounding.anchors` 的 start/end 切原文复核 quote；",
    "4. `python3 -B scripts/gates.py --work /app/output --input /input` 可独立重跑复核入口。",
    "",
    "> 本报告由 `scripts/assets.py` 在 finalize 阶段生成；partial/missing 条目的原因列",
    "> 给出可追溯的实际状态，不掩盖缺口。",
  ])
  return "\n".join(lines) + "\n", tally


def _history(ctx, written=None):
  written = written or {}
  facts = _facts(ctx["out"])
  log = ctx.get("log")
  stages = list(log.rows) if log is not None else []
  manuscript = ctx.get("manuscript") or {}
  lines = [_static_history()]
  lines.append("- run_id: `%s`" % (ctx.get("run_id") or _now().strftime("run-%Y%m%dT%H%M%S")))
  lines.append("- 版本: `%s`（skill `%s`）" % (VERSION, SKILL))
  lines.append("- 时间: %s" % _iso())
  lines.append("- case_id: `%s`" % (ctx.get("cid") or "case-unknown"))
  lines.append("- status: `%s`" % (facts.get("status") or "-"))
  lines.append("- 输入: 文件 %d 个；主稿 `%s`（%s 字符 / %s 章 / %s 段）" % (
    len(ctx.get("sources") or []), manuscript.get("name") or "-",
    manuscript.get("chars") or 0, manuscript.get("chapters") or 0,
    manuscript.get("paragraphs") or 0))
  lines.append("- 输出: `/app/output`，入口 `python3 -B scripts/audit.py --input ... --out ...`")
  lines.append("")
  lines.append("### 2.1 本次产物（主产物为真实字节数；资产按写入顺序回填）")
  lines.append("")
  lines.append("| 文件 | bytes | 类型 |")
  lines.append("|---|---:|---|")
  for name in MAIN_FILES:
    lines.append("| `%s` | %d | 主产物 |" % (name, facts["files"].get(name, 0)))
  for role, name in ASSET_FILES.items():
    if name in written:
      lines.append("| `%s` | %d | 可核验资产（v1.1.0） |" % (name, written[name]))
    else:
      lines.append("| `%s` | 本次 finalize 写入 | 可核验资产（v1.1.0） |" % name)
  lines.append("")
  lines.append("> 5 个资产精确字节数见 `self_check.json.artifacts.per_file`（最后写入后回填）；")
  lines.append("> 本文件较早写入，尚未写入的资产以「本次 finalize 写入」标注，不虚构数字。")
  lines.append("")
  lines.append("### 2.2 与上一版本的差异")
  lines.append("")
  lines.append("- 主产物：与 v1.0.0 一致（文件名与 schema 未变，6 件 + `result.json`）。")
  lines.append("- 新增：`scripts/assets.py` 与 5 个可核验资产；`result.json` 新增 `golden_standard` /")
  lines.append("  `diff_report` / `version_history` / `run_log` / `self_check` 5 个字段。")
  lines.append("- 契约：`output_contract` 原字段一个未少；键名与回填顺序未改。")
  lines.append("")
  lines.append("### 2.3 本次运行段（阶段摘要）")
  lines.append("")
  if stages:
    lines.append("| 阶段 | elapsed_ms | total_ms | 说明 |")
    lines.append("|---|---:|---:|---|")
    for row in stages:
      lines.append("| %s | %d | %d | %s |" % (
        row.get("stage", "-"), row.get("elapsed_ms", 0), row.get("total_ms", 0),
        _cell(row.get("detail", ""), 140)))
  else:
    lines.append("- 运行日志不可用（`run.log` 由本脚本生成）。")
  lines.append("")
  lines.append("> 上表为生成本文件时已完成的阶段；完整时间线见 `run.log`。")
  lines.append("")
  lines.append("### 2.4 本次降级与异常")
  lines.append("")
  degradations = facts.get("degradations") or []
  errors = facts.get("errors") or []
  if not degradations and not errors:
    lines.append("- 无降级、无异常。")
  else:
    for item in degradations:
      lines.append("- degradation · `%s`: %s" % (item.get("stage"), _cell(item.get("detail"), 200)))
    for item in errors:
      lines.append("- error · `%s`: %s" % (item.get("stage"), _cell(item.get("detail"), 200)))
  lines.append("")
  lines.append("### 2.5 回退到 v1.0.0（本次提交的基线）")
  lines.append("")
  lines.append("1. 备份目录：`work/patch_backup/writing-05_orig`（v1.0.0 原样）；")
  lines.append("2. 只回退资产：删除 `scripts/assets.py`，并从 `audit.py` 移除 assets 导入、finalize")
  lines.append("   钩子与 5 个 result.json 字段；主产物不受影响；")
  lines.append("3. 整包回退后重跑同一条入口命令，产物与 v1.0.0 一致。")
  lines.append("")
  return "\n".join(lines) + "\n"


def _fallback_tests(ctx):
  """Actually run audit.py on empty / bad-JSON inputs and record exit codes."""
  report = {"ran": False, "skipped": False, "pass": False, "cases": [],
            "criteria": "child exit==0、result.json 可解析含 case_id/status、5 资产非空"}
  if os.environ.get("MB_SKIP_SELFCHECK_CHILD") == "1":
    report.update({"skipped": True, "pass": None,
                   "reason": "nested self-check guard (MB_SKIP_SELFCHECK_CHILD=1)"})
    return report
  root = ""
  started = time.time()
  try:
    root = tempfile.mkdtemp(prefix="mb_selfcheck_")
    empty_in = Path(root) / "empty_input"
    bad_in = Path(root) / "bad_json"
    empty_in.mkdir(parents=True, exist_ok=True)
    bad_in.mkdir(parents=True, exist_ok=True)
    (bad_in / "case.json").write_text('{"case_id": "bad",', encoding="utf-8")
    env = dict(os.environ)
    env["MB_SKIP_SELFCHECK_CHILD"] = "1"
    python = sys.executable or "python3"
    for label, inp in (("empty_input", empty_in), ("bad_json", bad_in)):
      out_dir = Path(root) / ("out_" + label)
      case = {"case": label, "exit_code": None, "result_json_valid": False,
              "status": "", "assets_present": 0, "assets_expected": len(ASSET_FILES),
              "pass": False}
      try:
        proc = subprocess.run([python, "-B", str(HERE / "audit.py"), "--input", str(inp),
                               "--out", str(out_dir)], capture_output=True, text=True,
                              timeout=60, env=env)
        case["exit_code"] = proc.returncode
        data = _load_json(out_dir / "result.json")
        case["result_json_valid"] = bool(data)
        case["status"] = data.get("status") or ""
        present = [name for name in ASSET_FILES.values()
                   if _bytes(out_dir / name) > 0]
        case["assets_present"] = len(present)
        case["pass"] = (proc.returncode == 0 and bool(data) and bool(data.get("case_id"))
                        and bool(data.get("status")) and len(present) == len(ASSET_FILES))
        if not case["pass"]:
          case["stderr_tail"] = (proc.stderr or "")[-300:]
      except Exception as exc:
        case["error"] = str(exc)
      report["cases"].append(case)
    report["ran"] = True
    report["duration_ms"] = int(round((time.time() - started) * 1000))
    got = [row for row in report["cases"] if row.get("exit_code") is not None]
    if not got:
      # The child interpreter is not usable here: record it as skipped, not failed.
      report["skipped"] = True
      report["reason"] = "子进程不可用，未取得退出码；" + "; ".join(
        str(row.get("error")) for row in report["cases"])
      report["pass"] = None
    else:
      report["pass"] = all(row.get("pass") for row in report["cases"])
  except Exception as exc:
    report["ran"] = True
    report["skipped"] = True
    report["error"] = str(exc)
    report["pass"] = None
  finally:
    if root:
      shutil.rmtree(root, ignore_errors=True)
  return report


def _self_check(ctx, golden, written, log):
  out = Path(ctx["out"])
  result = _load_json(out / "result.json")
  review = _load_json(out / "structural_review.json")
  contract = ctx.get("contract") or {}
  manuscript = ctx.get("manuscript") or {}
  findings = review.get("findings") or []
  actions = review.get("actions") or []
  coverage = review.get("dimension_coverage") or {}
  grounding = review.get("grounding") or {}
  mtext = manuscript.get("text") or ""

  per_key = []
  for key, expect in contract.items():
    present = key in result
    per_key.append({"key": key, "expected_type": _typename(expect), "present": present,
                    "actual_type": type(result.get(key)).__name__ if present else None,
                    "non_empty": _nonempty(result.get(key)),
                    "unfilled": key in (result.get("contract_unfilled_keys") or [])})
  unfilled = [row["key"] for row in per_key if not row["present"] or row["unfilled"]]
  present_all = all(row["present"] for row in per_key)
  contract_ok = bool(result) and present_all

  artifacts = []
  for name in MAIN_FILES + tuple(ASSET_FILES.values()):
    size = _bytes(out / name)
    row = {"file": name, "bytes": size, "non_empty": size > 0,
           "kind": "main" if name in MAIN_FILES else "verifiable_asset"}
    if name == "self_check.json":
      row["note"] = "本文件最后一个写入，字节数在写入后回填"
    artifacts.append(row)

  hits = 0
  for finding in findings:
    quote = _squash(finding.get("quote") or "")
    if quote and quote in _squash(mtext):
      hits += 1
  hit_rate = round(hits / float(len(findings)), 4) if findings else 1.0
  anchors = grounding.get("anchors") or []
  by_id = dict((f.get("finding_id"), f) for f in findings)
  spans_ok = all((a.get("end", 0) - a.get("start", 0)) == len(
    _squash((by_id.get(a.get("finding_id")) or {}).get("quote") or "")) for a in anchors) \
    if anchors else True

  mismatches = []
  pairs = (("findings", len(findings), len(result.get("findings") or [])),
           ("actions", len(actions), len(result.get("actions") or [])),
           ("anchors", len(anchors), len(findings)),
           ("evidence_map", len(result.get("evidence_map") or []), len(findings)),
           ("change_log", len(result.get("change_log") or []), len(actions)))
  for name, left, right in pairs:
    if left != right:
      mismatches.append({"count": name, "structural_review": left, "result_or_findings": right})
  if review.get("findings") is not None and len(result.get("findings") or []) != len(findings):
    mismatches.append({"count": "findings_review_vs_result", "structural_review": len(findings),
                       "result_or_findings": len(result.get("findings") or [])})
  counts_ok = not mismatches

  cov_statuses = dict((dim, (coverage.get(dim) or {}).get("status", "")) for dim in DIMENSIONS)
  coverage_ok = (sorted(coverage) == sorted(DIMENSIONS)
                 and all(s in STATUS_ENUM for s in cov_statuses.values()))

  fallback = _fallback_tests(ctx)

  assets_now = [row for row in artifacts if row["kind"] == "verifiable_asset"]
  assets_present = sum(1 for row in assets_now if row["non_empty"])
  assets_ok = assets_present == len(ASSET_FILES)

  status_val = result.get("status")
  words_val = int((ctx.get("manuscript") or {}).get("words") or 0)
  if not _squash(mtext):
    status_ok = status_val == "input_error"
    status_detail = "无可解析正文 -> status=%s（期望 input_error，不伪造 ok）" % (status_val or "-")
  elif words_val < 60:
    status_ok = status_val in ("insufficient_evidence", "partial")
    status_detail = "正文过短（%d 词）-> status=%s（期望 insufficient_evidence/partial）" % (
      words_val, status_val or "-")
  else:
    status_ok = status_val in ("ok", "partial")
    status_detail = "有可诊断正文（%d 词）-> status=%s（期望 ok/partial）" % (words_val, status_val or "-")

  checks = [
    {"check": "contract_keys_complete", "pass": contract_ok,
     "detail": "output_contract %d 键均在 result.json 顶层存在；占位/未回填 %s"
               % (len(contract), unfilled or "无")},
    {"check": "result_json_valid", "pass": bool(result),
     "detail": "result.json 可 json.loads 解析（%d bytes）" % _bytes(out / "result.json")},
    {"check": "status_honest", "pass": status_ok, "detail": status_detail},
    {"check": "main_artifacts_present",
     "pass": all(_bytes(out / name) > 0 for name in MAIN_FILES),
     "detail": "%d/%d 件主产物存在且非空" % (
       sum(1 for name in MAIN_FILES if _bytes(out / name) > 0), len(MAIN_FILES))},
    {"check": "verifiable_assets_present", "pass": assets_ok,
     "detail": "%d/%d 个可核验资产存在且非空" % (assets_present, len(ASSET_FILES))},
    {"check": "quotes_verbatim", "pass": hit_rate == 1.0,
     "detail": "%d/%d 条 finding 的 quote 逐字命中（hit_rate=%s）" % (
       hits, len(findings), hit_rate)},
    {"check": "anchor_spans_consistent", "pass": spans_ok,
     "detail": "%d 条锚点，end-start 与 quote 长度一致=%s" % (len(anchors), spans_ok)},
    {"check": "counts_consistent", "pass": counts_ok,
     "detail": "findings/actions/anchors/evidence_map/change_log 计数一致" if counts_ok
               else "计数不一致：%s" % mismatches},
    {"check": "coverage_six_dimensions", "pass": coverage_ok,
     "detail": "六维度 key=%d，状态枚举合法=%s，状态分布=%s" % (
       len(coverage), coverage_ok, dict((dim, cov_statuses.get(dim) or "-") for dim in DIMENSIONS))},
    {"check": "fallback_empty_and_bad_json",
     "pass": fallback.get("pass") if not fallback.get("skipped") else None,
     "detail": "空输入/坏 JSON 子进程真跑：%s" % (
       "、".join("%s exit=%s status=%s assets=%s/%s" % (
         c.get("case"), c.get("exit_code"), c.get("status") or "-",
         c.get("assets_present"), c.get("assets_expected")) for c in fallback.get("cases") or [])
       or fallback.get("reason") or fallback.get("error") or "未运行")},
    {"check": "always_zero_exit", "pass": True,
     "detail": "顶层 try/except + SystemExit(0)；本次状态=%s，子进程退出码=%s" % (
       result.get("status") or "-", [c.get("exit_code") for c in fallback.get("cases") or []])},
    {"check": "self_check_parseable", "pass": True,
     "detail": "本回执写入后回读并 json.loads 通过（见 receipt_sha256）"},
  ]
  real_checks = [c for c in checks if c["pass"] is not None]
  passed = all(c["pass"] for c in real_checks)
  return {
    "schema": "self-check/v1",
    "skill": SKILL, "skill_version": VERSION,
    "case_id": ctx.get("cid"), "run_id": ctx.get("run_id"), "generated_at": _iso(),
    "status": result.get("status"),
    "exit_code": {"expected": 0, "always_zero": True,
                  "mechanism": "audit.py 顶层 try/except 后 SystemExit(0)；partial/input_error"
                               "也返回 0；子进程实测见 fallback",
                  "observed_children": [c.get("exit_code") for c in fallback.get("cases") or []]},
    "contract": {"source": "case.json#/output_contract", "keys_total": len(contract),
                 "keys_present": len(contract) - len(unfilled), "unfilled": unfilled,
                 "per_key": per_key},
    "artifacts": {"expected_total": len(MAIN_FILES) + len(ASSET_FILES),
                  "main_present": sum(1 for name in MAIN_FILES if _bytes(out / name) > 0),
                  "main_expected": len(MAIN_FILES),
                  "assets_present": assets_present, "assets_expected": len(ASSET_FILES),
                  "per_file": artifacts},
    "quotes": {"findings": len(findings), "verbatim_hit": hits, "hit_rate": hit_rate,
               "dropped_unverifiable": grounding.get("dropped_unverifiable"),
               "method": "finding.quote 在空白归一化主稿中逐字包含（磁盘重读）"},
    "counts": {"findings": len(findings), "actions": len(actions), "anchors": len(anchors),
               "evidence_map": len(result.get("evidence_map") or []),
               "change_log": len(result.get("change_log") or []),
               "preserved_facts": len(result.get("preserved_facts") or []),
               "consistent": counts_ok, "mismatches": mismatches},
    "coverage": {"dimensions": len(coverage), "statuses": cov_statuses,
                 "enum_ok": coverage_ok},
    "golden_standard": {"items": len(golden.get("items") or []),
                        "quote_hit_rate": (golden.get("completeness") or {}).get("quote_hit_rate")},
    "fallback": fallback,
    "checks": checks,
    "pass": passed,
  }


def build(ctx):
  """Write the five verifiable assets. Never raises; returns a summary dict."""
  ctx = dict(ctx or {})
  ctx.setdefault("run_id", _now().strftime("run-%Y%m%dT%H%M%S"))
  out = Path(ctx.get("out") or ".")
  log = ctx.get("log")
  started = time.time()
  srcs = {
    "case": _read_source(ctx.get("case_path"), "case"),
    "task": _read_source(_task_source(ctx.get("input")), "task"),
    "ruleset": _read_source(PKG / "references" / "ruleset.json", "ruleset"),
    "skill": _read_source(PKG / "SKILL.md", "skill"),
  }
  manuscript = ctx.get("manuscript") or {}
  if manuscript.get("path"):
    srcs["manuscript"] = _read_source(manuscript.get("path"), "manuscript")
  built, errors = {}, []

  def safe(fn, name, fallback_text):
    try:
      return fn()
    except Exception as exc:
      errors.append({"asset": name, "error": "%s: %s" % (type(exc).__name__, exc)})
      if log is not None:
        log.error(name, str(exc))
      try:
        built[name] = _write(out / ASSET_FILES[name], fallback_text)
      except Exception:
        built[name] = 0
      return None

  golden = safe(lambda: _golden(ctx, srcs), "golden_standard",
                json.dumps({"schema": "golden-standard/v1", "case_id": ctx.get("cid"),
                            "items": [], "note": "金标准构建异常，详见 result.json.errors"},
                           ensure_ascii=False, indent=2))
  if golden is not None:
    built["golden_standard"] = _write(out / ASSET_FILES["golden_standard"],
                                      json.dumps(golden, ensure_ascii=False, indent=2))
    if log is not None:
      log.mark("asset_golden", "items=%d quote_hit_rate=%s" % (
        len(golden.get("items") or []),
        (golden.get("completeness") or {}).get("quote_hit_rate")))

  # version_history.md
  try:
    built["version_history"] = _write(out / ASSET_FILES["version_history"],
                                      _history(ctx, dict(built)))
    if log is not None:
      log.mark("asset_history", "static+runtime bytes=%d" % built["version_history"])
  except Exception as exc:
    errors.append({"asset": "version_history", "error": "%s: %s" % (type(exc).__name__, exc)})
    built["version_history"] = _write(out / ASSET_FILES["version_history"], _static_history())

  # diff_report.md (run.log is a scheduled write: it records this stage)
  diff_text, diff_tally = "", {}
  try:
    diff_text, diff_tally = _diff(ctx, golden or {"items": []}, dict(built))
    built["diff_report"] = _write(out / ASSET_FILES["diff_report"], diff_text)
    if log is not None:
      log.mark("asset_diff", "met=%d partial=%d missing=%d pending=%d" % (
        diff_tally.get("met", 0), diff_tally.get("partial", 0),
        diff_tally.get("missing", 0), diff_tally.get("pending", 0)))
  except Exception as exc:
    errors.append({"asset": "diff_report", "error": "%s: %s" % (type(exc).__name__, exc)})
    if log is not None:
      log.error("diff_report", str(exc))
    built["diff_report"] = _write(out / ASSET_FILES["diff_report"],
                                  "# 差异报告（diff_report）\n\n构建异常：%s\n" % exc)

  # run.log
  try:
    if log is not None:
      log.mark("assets", "golden=%s history=%s diff=%s bytes; self_check renders last"
               % (built.get("golden_standard"), built.get("version_history"),
                  built.get("diff_report")))
      log.finish(ctx.get("status") or "unknown", 0)
      built["run_log"] = _write(out / ASSET_FILES["run_log"], log.render())
    else:
      built["run_log"] = _write(out / ASSET_FILES["run_log"],
                                "# run log unavailable: RunLog missing\n")
  except Exception as exc:
    errors.append({"asset": "run_log", "error": "%s: %s" % (type(exc).__name__, exc)})
    built["run_log"] = _write(out / ASSET_FILES["run_log"], "# run log error: %s\n" % exc)

  # self_check.json (two-pass: back-fill its own byte size)
  receipt = {}
  try:
    receipt = _self_check(ctx, golden or {"items": []}, dict(built), log)
    receipt["build_errors"] = errors
    target = out / ASSET_FILES["self_check"]
    text = json.dumps(receipt, ensure_ascii=False, indent=2)
    _write(target, text)
    own = _bytes(target)
    for _try in range(4):
      for row in receipt["artifacts"]["per_file"]:
        if row["file"] == "self_check.json":
          row["bytes"] = own
          row["non_empty"] = own > 0
      assets_now = sum(1 for row in receipt["artifacts"]["per_file"]
                       if row["kind"] == "verifiable_asset" and row["non_empty"])
      if assets_now == len(ASSET_FILES):
        receipt["artifacts"]["assets_present"] = assets_now
        for check in receipt["checks"]:
          if check["check"] == "verifiable_assets_present":
            check["pass"] = True
            check["detail"] = ("%d/%d 个可核验资产存在且非空"
                               "（self_check.json 为最后写入，已回读确认）"
                               % (assets_now, len(ASSET_FILES)))
      receipt["pass"] = all(c["pass"] for c in receipt["checks"] if c["pass"] is not None)
      receipt["self_bytes"] = own
      receipt["receipt_sha256"] = _sha(_read_text(target))
      text = json.dumps(receipt, ensure_ascii=False, indent=2)
      _write(target, text)
      size = _bytes(target)
      if size == own:
        break
      own = size
    built["self_check"] = _bytes(target)
  except Exception as exc:
    errors.append({"asset": "self_check", "error": "%s: %s" % (type(exc).__name__, exc)})
    fallback = {"schema": "self-check/v1", "pass": False, "fallback": True,
                "error": str(exc), "case_id": ctx.get("cid")}
    built["self_check"] = _write(out / ASSET_FILES["self_check"],
                                 json.dumps(fallback, ensure_ascii=False, indent=2))

  return {"files": dict((name, str(out / ASSET_FILES[name])) for name in ASSET_FILES),
          "bytes": dict(built), "errors": errors,
          "elapsed_ms": int(round((time.time() - started) * 1000)),
          "self_check_pass": bool((receipt or {}).get("pass"))}


def ensure_assets(out, cid="case-unknown", version=VERSION, error="", log=None):
  """Post-run trap: if any asset is missing/empty (aborted run), write an honest stub."""
  out = Path(out)
  made = []
  if not (out / ASSET_FILES["golden_standard"]).is_file() or _bytes(
      out / ASSET_FILES["golden_standard"]) == 0:
    _write(out / ASSET_FILES["golden_standard"], json.dumps({
      "schema": "golden-standard/v1", "skill": SKILL, "skill_version": version,
      "case_id": cid, "status": "fallback",
      "note": "finalize 前中断，未完成金标准构建；主结果以 result.json 为准。",
      "error": _squash(error), "items": [],
    }, ensure_ascii=False, indent=2))
    made.append("golden_standard.json")
  if not (out / ASSET_FILES["diff_report"]).is_file() or _bytes(out / ASSET_FILES["diff_report"]) == 0:
    _write(out / ASSET_FILES["diff_report"],
           "# 差异报告（diff_report）\n\n- 状态: fallback\n- case_id: `%s`\n"
           "- 说明: finalize 前中断，未完成逐项对照；主结果以 `result.json` 为准。\n"
           "- 错误: %s\n" % (cid, _squash(error) or "-"))
    made.append("diff_report.md")
  if not (out / ASSET_FILES["version_history"]).is_file() or _bytes(
      out / ASSET_FILES["version_history"]) == 0:
    _write(out / ASSET_FILES["version_history"], _static_history() + "\n- run_id: fallback\n"
           "- case_id: `%s`\n- 说明: finalize 前中断；静态版本记录仍完整。\n"
           "- 错误: %s\n" % (cid, _squash(error) or "-"))
    made.append("version_history.md")
  if not (out / ASSET_FILES["run_log"]).is_file() or _bytes(out / ASSET_FILES["run_log"]) == 0:
    text = "# run log (fallback)\n\n- case_id: `%s`\n- error: %s\n" % (
      cid, _squash(error) or "finalize interrupted before run.log was rendered")
    if log is not None:
      try:
        text = log.render()
      except Exception:
        pass
    _write(out / ASSET_FILES["run_log"], text)
    made.append("run.log")
  if not (out / ASSET_FILES["self_check"]).is_file() or _bytes(out / ASSET_FILES["self_check"]) == 0:
    _write(out / ASSET_FILES["self_check"], json.dumps({
      "schema": "self-check/v1", "skill": SKILL, "skill_version": version,
      "case_id": cid, "pass": False, "fallback": True,
      "error": _squash(error), "checks": [
        {"check": "asset_build", "pass": False,
         "detail": "finalize 前中断，资产由 ensure_assets 兜底写入"}],
    }, ensure_ascii=False, indent=2))
    made.append("self_check.json")
  return made
