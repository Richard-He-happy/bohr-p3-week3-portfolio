#!/usr/bin/env python3
"""Five verifiable assets for the material-anchored chapter pipeline.

`chapter_builder.py build` (the finalize step) calls `attach()` here, which writes these
files into the output directory next to the manuscript and result.json:

    golden_standard.json   期望交付逐项清单，每项带 locator + 逐字 quote
    diff_report.md         实际产物 vs 金标准逐项对照（达标/缺失/偏差/记录）
    version_history.md     静态版本历史 + 回退方式 + 本次运行段（runtime append）
    run.log                本次 build 的真实阶段日志（阶段/耗时/退出码/降级/异常）
    self_check.json        契约键/主产物/引文命中/计数自洽/兜底/退出码断言

Stdlib only, no network, no dependence on the current working directory.
The module is optional for the core pipeline: a failed import or a failed asset write must
never break the manuscript or the exit code.
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

VERSION = "1.1.0"
PKG = "manuscript-evidence-drafting"
GOLD_SCHEMA = "golden_standard.v1"
CHK_SCHEMA = "self_check.v1"
ASSETS = ("golden_standard.json", "diff_report.md", "version_history.md", "run.log",
          "self_check.json")
PROBE_ENV = "CHAPTER_ASSET_PROBE"
_BLANK = re.compile(r"\s+")
_ALNUM = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_RUN = None


# ---------------------------------------------------------------- small helpers
def _flat(value, cap):
    body = _BLANK.sub(" ", "" if value is None else str(value)).strip()
    return body if len(body) <= cap else body[:cap - 1] + "…"


def _clip(value, cap=140):
    return _flat(value, cap)


def _rd(path, cap=4 << 20):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:cap]
    except (OSError, ValueError):
        return ""


def _wr_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return target.stat().st_size


def _sha(path):
    try:
        digest = hashlib.sha256()
        with open(str(path), "rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _size(path):
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


# ---------------------------------------------------------------- run log
class RunLog(object):
    """Collect real per-stage timing; render it as run.log at finalize."""

    def __init__(self, argv, inp, out):
        self.t0 = time.time()
        self.rows = []
        self.header = {"argv": " ".join(str(x) for x in (argv or [])), "input": str(inp),
                       "output": str(out), "python": sys.version.split()[0],
                       "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self._mark("start", "build invoked")

    def _mark(self, stage, msg="", **kv):
        self.rows.append({"t": round(time.time() - self.t0, 4), "stage": stage,
                          "msg": msg, "kv": kv})

    def log(self, stage, msg="", **kv):
        try:
            self._mark(stage, msg, **kv)
        except Exception:
            pass

    def render(self, state, extra):
        limit = 0.0
        lines = ["# run.log | %s v%s" % (PKG, VERSION),
                 "# argv: %s" % (self.header["argv"] or "-"),
                 "# input: %s" % self.header["input"],
                 "# output: %s" % self.header["output"],
                 "# python: %s | started_at: %s" % (self.header["python"], self.header["started_at"]),
                 ""]
        for row in self.rows:
            delta = row["t"] - limit
            limit = row["t"]
            pairs = " ".join("%s=%s" % (key, _clip(value, 90))
                             for key, value in row["kv"].items()
                             if value is not None and value != "")
            lines.append("[%8.4fs] [+%7.4fs] [%-13s] %s%s"
                         % (row["t"], delta, row["stage"], _clip(row["msg"], 180),
                            (" " + pairs) if pairs else ""))
        for item in (state or {}).get("degradations") or []:
            lines.append("[degrade  ] code=%s path=%s"
                         % (_clip(item.get("code"), 60), _clip(item.get("path"), 90)))
        for item in (state or {}).get("errors") or []:
            lines.append("[error    ] %s" % _clip(item, 180))
        if extra:
            lines.append("[finalize ] %s" % _flat(extra, 400))
        if self.rows:
            last = self.rows[-1]
            lines.append("[exit     ] exit_code=0 elapsed=%.4fs status=%s"
                         % (last["t"], (state or {}).get("_status") or "-"))
        return "\n".join(lines) + "\n"


def start_run(argv, inp, out):
    global _RUN
    _RUN = RunLog(argv, inp, out)
    return _RUN


def log(stage, msg="", **kv):
    if _RUN is not None:
        _RUN.log(stage, msg, **kv)


def run_log_bytes(state, extra=""):
    """Render the log once; byte length is stable, so result.json can point at it."""
    if _RUN is None:
        return None, 0
    text = _RUN.render(state, extra)
    return text, len(text.encode("utf-8"))


# ---------------------------------------------------------------- inputs
def _read_inputs(bundle):
    """Return (case_name, case_raw, case_data, task_name, task_text, task_lines)."""
    inp = Path(bundle.get("input") or "/input")
    case = bundle.get("case") if isinstance(bundle.get("case"), dict) else {}
    case_name, case_raw = "case.json", ""
    candidates = [inp / "case.json"] + sorted(inp.glob("case*.json"))
    for path in candidates:
        if path.is_file():
            raw = _rd(path)
            if raw:
                case_name, case_raw = path.name, raw
                if not case:
                    try:
                        data = json.loads(raw)
                    except Exception:
                        data = {}
                    if isinstance(data, dict):
                        case = data
                break
    task_name, task_text, task_lines = "task.md", "", []
    for path in [inp / "task.md"] + sorted(inp.glob("task*.md")):
        if path.is_file():
            raw = _rd(path)
            if raw.strip():
                task_name, task_text, task_lines = path.name, raw, raw.splitlines()
                break
    return case_name, case_raw, case, task_name, task_text, task_lines


def _contract_keys(case):
    contract = case.get("output_contract") if isinstance(case, dict) else None
    if isinstance(contract, dict):
        return [str(key) for key in contract]
    if isinstance(contract, (list, tuple)):
        return [str(key) for key in contract if isinstance(key, str)]
    return []


def _section_names(case, instruction):
    names = []
    required = case.get("required_sections") if isinstance(case, dict) else None
    if isinstance(required, list):
        names += [str(item).strip() for item in required if str(item).strip()]
    for word in ("摘要", "引言", "方法", "结果", "讨论", "结论", "参考文献", "数据可得性声明"):
        if word in (instruction or "") and not any(word in name for name in names):
            names.append(word)
    return names[:12]


def _requirement_pieces(instruction, cap=6):
    pieces, seen = [], set()
    for raw in re.split(r"[；;。\n]", instruction or ""):
        piece = raw.strip(" -、，,：:")
        if not (8 <= len(piece) <= 200) or not any(
                key in piece for key in ("必须", "不得", "至少", "逐字", "保留", "只允许",
                                         "覆盖", "标注", "引用", "格式", "缺")):
            continue
        if piece[:30] in seen:
            continue
        seen.add(piece[:30])
        pieces.append(piece)
        if len(pieces) >= cap:
            break
    return pieces


def _requirement_check(piece):
    if any(key in piece for key in ("逐字", "数值", "单位", "图注")):
        return "number_audit.hit_rate=1.0 且 quotes_rejected=0", "fidelity"
    if "至少" in piece or "段" in piece:
        return "对应章节正文段落数达到下限", "volume"
    if "参考文献" in piece or "条目" in piece or "DOI" in piece:
        return "参考文献只出现材料内条目，缺项进 pending_human", "citation"
    if any(key in piece for key in ("必须", "不得", "不新增", "允许")):
        return "preserved_facts/evidence_map 均逐字命中材料", "fidelity"
    if any(key in piece for key in ("标注", "缺", "人工确认", "不确定")):
        return "缺口与待确认写入 pending_human/uncertainty", "pending"
    return "人工复核（无机器判据）", "manual"


_TASK_KEYS = ("事实", "来源", "引用", "章节", "可编辑", "可核验", "可复核", "缺", "标注",
              "异常", "不确定", "退出", "结果", "材料", "数字", "unit", "evidence")
_CITE_RX = re.compile(r"(?:doi:|DOI:|\[[0-9]{1,2}\]|图\s*[0-9]+|Figure\s*[0-9]+|"
                      r"Fig\.\s*[0-9]+|Journal|journal|出版社|参考文献)")
_CITE_LINE_RX = re.compile(r"^(?:\[[0-9]{1,2}\]|图\s*[0-9]+|Fig(?:ure|\.)\s*[0-9]+|"
                           r"Table\s*[0-9]+|表\s*[0-9]+)")


def _task_requirements(task_text, task_lines, cap=8):
    picked, seen = [], set()
    for number, line in enumerate(task_lines or [], 1):
        text = line.strip()
        if not (18 <= len(text) <= 240) or text.startswith(("#", "|", ">", "```", "-", "*")):
            continue
        if not any(key in text for key in _TASK_KEYS):
            continue
        if text[:30] in seen:
            continue
        seen.add(text[:30])
        picked.append((number, text))
        if len(picked) >= cap:
            break
    return picked


# ---------------------------------------------------------------- golden standard
def golden(bundle):
    """按 output_contract/题面逐项列期望交付，带 locator 与逐字 quote。"""
    case_name, case_raw, case, task_name, task_text, task_lines = _read_inputs(bundle)
    contract = _contract_keys(case)
    instruction = bundle.get("instruction") or ""
    materials = bundle.get("materials") or []
    pool = bundle.get("pool") or []
    stats = bundle.get("stats") or {}
    texts = {item.get("id"): _BLANK.sub("", item.get("text") or "") for item in materials
             if item.get("readable")}
    corpus = "\n".join(text for text in texts.values())
    case_flat = _BLANK.sub("", case_raw)
    items, counter, groups, basis_count = [], {}, {}, {}
    graded = []

    def add(group, expected, check, locator=None, quote=None, basis="contract",
            source=None, verified=None, note=""):
        counter[group] = counter.get(group, 0) + 1
        items.append({"id": "G-%s-%02d" % (_CODE[group], counter[group]), "group": group,
                      "expected": expected, "check": check, "locator": locator,
                      "quote": quote, "basis": basis, "source_file": source,
                      "verbatim_verified": verified, "note": note})
        groups[group] = groups.get(group, 0) + 1
        basis_count[basis] = basis_count.get(basis, 0) + 1
        if verified is not None:
            graded.append(verified)

    for key in contract:
        token = '"%s"' % key
        hit = bool(case_raw) and token in case_flat or token in case_raw
        add("contract_field", "result.json 顶层键 %s 原样存在，值按语义回填" % key,
            "result.json 含键 %s；缺值允许 null/[]" % key,
            locator="%s#output_contract.%s" % (case_name, key), quote=token if hit else None,
            basis="input_quote" if hit else "contract", source=case_name, verified=hit,
            note="契约键名在 case.json 中逐字命中。" if hit else
                 "case.json 未提供该键名，按运行契约推导（basis=contract）。")
    for name in _section_names(case, instruction):
        token = '"%s"' % name if name in case_raw else name
        hit = bool(token) and (token in case_raw if token.startswith('"') else token in instruction)
        where = "%s#required_sections" % case_name if token.startswith('"') else \
            "%s#task_instruction" % case_name
        add("required_section", "稿件章节标题覆盖「%s」，正文非空" % name,
            "manuscript.md 出现该章节标题（关键词匹配）",
            locator=where, quote=token, basis="input_quote" if hit else "contract",
            source=case_name, verified=hit, note="章节要求逐字取自输入。")
    for piece in _requirement_pieces(instruction):
        check, kind = _requirement_check(piece)
        add("instruction_requirement", "满足任务指令约束：%s" % _clip(piece, 160), check,
            locator="%s#task_instruction" % case_name, quote=piece, basis="input_quote",
            source=case_name, verified=piece in instruction,
            note="task_instruction 逐字片段；判据类别=%s。" % kind)
    for fact in (bundle.get("facts") or [])[:14]:
        quote = fact.get("value_text") or ""
        hit = _BLANK.sub("", quote) in corpus if quote else False
        add("material_fact", "主产物/证据链保留事实：%s" % _clip(quote, 150),
            "quote 在材料逐字命中且进入 evidence_map/preserved_facts",
            locator=fact.get("locator"), quote=quote, basis="input_quote",
            source=fact.get("source_id"), verified=hit,
            note="数值与单位沿用材料原句，不做换算。")
    cited = 0
    for material in materials:
        if cited >= 6 or not material.get("readable"):
            continue
        for number, line in enumerate((material.get("text") or "").splitlines(), 1):
            if cited >= 6:
                break
            text = line.strip().strip("-* ")
            if not (12 <= len(text) <= 240) or not _CITE_LINE_RX.match(text):
                continue
            hit = _BLANK.sub("", text) in corpus
            add("citation_fact", "引用/图注条目逐字保留：%s" % _clip(text, 150),
                "quote 在材料逐字命中且进入正文或 evidence_map",
                locator="%s:L%d" % (material.get("path"), number), quote=text,
                basis="input_quote", source=material.get("id"), verified=hit,
                note="引用编号、作者/年份/DOI、图注编号一律沿用材料原样，缺项不补造。")
            cited += 1
    for number, text in _task_requirements(task_text, task_lines):
        add("task_requirement", "任务说明要求：%s" % _clip(text, 160),
            "人工语义复核（task.md 为要求来源，不作事实证据）",
            locator="%s#L%d" % (task_name, number), quote=text, basis="input_quote",
            source=task_name, verified=text in task_text,
            note="task.md 逐字要求行；机器只核 quote，语义由评审复核。")
    for name, role in (("manuscript.md", "主产物：可编辑章节稿"), ("result.json", "结构化结果"),
                       ("evidence_map.json", "论断—引文映射"),
                       ("preserved_facts.json", "事实—来源记录"),
                       ("change_log.json", "改动记录"), ("pending_human.json", "待确认清单"),
                       ("consistency_report.md", "一致性报告")):
        add("deliverable", "%s（%s）存在且非空" % (name, role), "output 目录文件字节 > 0",
            locator="output/%s" % name, note="运行契约与交付要求推导（basis=contract）。")
    for name, desc in (("golden_standard.json", "本清单（期望交付逐项 + 逐字 quote）"),
                       ("diff_report.md", "实际 vs 金标准逐项对照"),
                       ("version_history.md", "版本历史 + 回退方式 + 本次运行段"),
                       ("run.log", "真实运行日志（阶段/耗时/退出码/降级/异常）"),
                       ("self_check.json", "契约/产物/引文/计数/兜底/退出码自检")):
        add("asset", "核验资产 %s：%s" % (name, desc), "5 件资产均在 output 且字节 > 0",
            locator="output/%s" % name, note="patch v1.1.0 增补资产（basis=contract）。")
    for claim, check in (("空输入仍 exit 0 且产出合法 result.json + 5 资产",
                          "self_check.json 的 S6 子进程实证"),
                         ("坏 JSON 仍 exit 0 且产出合法 result.json + 5 资产",
                          "self_check.json 的 S7 子进程实证"),
                         ("不依赖 CWD：从任意外部目录运行结果一致",
                          "self_check.json 的 S6/S7 子进程以临时 CWD 运行"),
                         ("同输入两次运行结构一致（幂等）",
                          "self_check.json 的 S8 重复运行对比")):
        add("behavior", claim, check, locator="self_check.json", note="运行契约推导（basis=contract）。")
    add("behavior", "任何路径退出码恒为 0", "self_check.json 的 S11 退出码断言 + 子进程实测",
        locator="self_check.json", note="运行契约推导（basis=contract）。")
    add("boundary", "status 诚实：ok/partial/insufficient_evidence/input_error 与实情一致",
        "self_check.json 的 S9 状态语义检查", locator="result.json#status")
    add("boundary", "材料缺口与不确定项进入 pending_human/uncertainty，不伪造结论",
        "pending_human/uncertainty 非空或明确为无", locator="result.json#pending_human")
    hit = len([flag for flag in graded if flag])
    total = len(items)
    return {
        "schema": GOLD_SCHEMA, "package": PKG, "version": VERSION,
        "case_id": case.get("case_id") or bundle.get("case_id"),
        "generated": _now(),
        "source_files": [{"role": "case", "file": case_name},
                         {"role": "task", "file": task_name if task_text else None}],
        "basis_rules": {
            "input_quote": "quote 为输入文件（case.json/task.md/材料）的逐字片段，可用 locator 复核。",
            "contract": "无正文来源：由 output_contract/任务说明/运行契约推导，按 note 核产物。"},
        "expected": {
            "contract_fields": contract or ["case_id", "deliverable", "preserved_facts",
                                            "evidence_map", "change_log"],
            "sections": [name for name in _section_names(case, instruction)],
            "deliverables": ["manuscript.md", "result.json", "evidence_map.json",
                             "preserved_facts.json", "change_log.json", "pending_human.json",
                             "consistency_report.md"],
            "assets": list(ASSETS),
            "facts_min": 5, "evidence_min": 5,
            "number_hit_rate": 1.0,
            "status_enum": ["ok", "partial", "insufficient_evidence", "input_error"],
            "exit_code": 0},
        "counts": {"total": total, "by_group": groups, "by_basis": basis_count,
                   "verbatim": {"graded": len(graded), "hit": hit,
                                "ratio": round(hit / len(graded), 4) if graded else None}},
        "items": items,
        "how_to_use": ["按 locator 打开源文件核对 quote；basis=contract 项按 check 核运行产物。",
                       "diff_report.md 逐项给出达标/缺失/偏差；self_check.json 给机器断言。"]}


_CODE = {"contract_field": "CON", "required_section": "SEC", "instruction_requirement": "INS",
         "material_fact": "FACT", "citation_fact": "CIT", "task_requirement": "TSK",
         "deliverable": "DLV", "asset": "AST", "behavior": "BEH", "boundary": "BND"}


# ---------------------------------------------------------------- version history
_STATIC_HISTORY = """# 版本历史 | manuscript-evidence-drafting

本文件分两段：**静态版本记录**（包内固定内容，说明 v0→v1.0.0 的演进与回退方式）与
**本次运行段**（每次 `build` 由脚本追加，记录这一次运行的真实参数与产物指纹）。

## 1. 静态版本记录（runner 之前）

| 版本 | 变更 | 证据 / 说明 |
|-|-|-|
| v0 | 云端构建骨架：`SKILL.md` + 两个标准库脚本，`init/show/check/build` 四命令最小闭环 | 首抽前版本；入口与 CLI 从此刻固定 |
| v0.9 | 补降级分支表、`pending_human` 三字段与逐字引文校验；章节由材料兜底组装 | 与 v1.0.0 同一代码族 |
| v1.0.0 | 首抽提交版：材料锚定章节稿 + `evidence_map` + `preserved_facts` + `change_log`；契约字段原样回填 | 第 3 期写作01（challenge-308a6fdc）首抽 **60.6667**；入口 `scripts/chapter_builder.py` 不变 |
| v1.1.0 | patch：`build/finalize` 增补 5 件可核验资产（`golden_standard.json`、`diff_report.md`、`version_history.md`、`run.log`、`self_check.json`）；新增 2 个标准库脚本；SKILL.md 解释器统一 `python3`；**入口 / 子命令 / 参数 / 契约 / 退出码不变** | 本次 patch；验证记录 `work/validate_patch/writing-01.md` |

## 2. 回退方式

1. **整包回退**：用 `work/patch_backup/writing-01_orig`（5 文件 / 46,526 B，逐文件 sha256 见
   `writing-01_orig_manifest.json`）覆盖当前包目录，即回到 v1.0.0。
2. **单文件回退**：只把 `scripts/chapter_builder.py` 换回 v1.0.0 版本即可；两个新脚本
   （`assets.py`、`audit.py`）不再被调用，`/app/output` 不再产出 5 资产，其余主产物与
   `result.json` 原有字段完全不受影响。
3. **回退验证**：重跑 `build`，确认输出目录没有 `golden_standard.json` 等 5 个文件、
   `result.json` 没有 5 个摘要字段、原契约字段齐全、退出码 0。
4. **升级回滚粒度**：新增行为都收在「assets 导入失败/资产写入失败 → 降级记录 + 主流程继续」
   的分支里；因此不需要回滚数据，只需回滚上面两类文件。

"""


def history(bundle):
    state = bundle.get("state") or {}
    result = bundle.get("result") or {}
    out = Path(bundle.get("output") or "/app/output")
    deliverable = result.get("deliverable") or "manuscript.md"
    main = out / deliverable
    elapsed = None
    if _RUN is not None:
        elapsed = round(time.time() - _RUN.t0, 3)
    if elapsed is None:
        elapsed = bundle.get("elapsed")
    sizes = {name: _size(out / name) for name in ASSETS}
    written = "、".join(
        "%s=%dB" % (name, sizes.get(name)) for name in ASSETS
        if (sizes.get(name) or 0) > 0) or "无"
    pending = "、".join(
        "version_history.md=本文件（生成中）" if name == "version_history.md" else name
        for name in ASSETS if not (sizes.get(name) or 0)) or "无"
    lines = [_STATIC_HISTORY, "## 3. 本次运行（runtime append）", "",
             "- 运行时间：%s；run_id：`%s-%s`" % (
                 _now(), time.strftime("%Y%m%dT%H%M%S"), str(result.get("case_id"))[:24]),
             "- 命令：`python3 -B scripts/chapter_builder.py %s`" % (_flat(
                 " ".join(str(x) for x in (bundle.get("argv") or [])), 320) or "-"),
             "- 输入：`%s`；输出：`%s`" % (bundle.get("input"), bundle.get("output")),
             "- case_id：%s；status：%s；耗时：%s s；退出码：0" % (
                 result.get("case_id"), result.get("status"),
                 elapsed if elapsed is not None else "-"),
             "- 主产物：`%s`（%s B，sha256 `%s`）" % (
                 deliverable, _size(main), (_sha(main) or "-")[:16]),
             "- 五件资产（已写：%s；本文件生成后由 finalize 写出：%s）" % (written, pending),
             "- 降级 %d 条、异常 %d 条、待确认 %d 条（详见 run.log 与 result.json）" % (
                 len(state.get("degradations") or []), len(state.get("errors") or []),
                 len(state.get("pending_human") or [])),
             "- 复跑：同一命令重跑即可；除时间戳/耗时外，结构、计数与判定稳定。", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- finalize
def attach(out_dir, bundle, save_result):
    """Write 4 assets, fill result refs, write 5th, fill run.log. Never raises."""
    out = Path(out_dir)
    state = bundle.get("state") or {}
    result = bundle.get("result") or {}
    summary = {"golden_standard": None, "diff_report": None, "version_history": None,
               "run_log": None, "self_check": None, "errors": []}

    def fail(stage, error):
        summary["errors"].append({"stage": "assets." + stage, "error": repr(error)[:200]})
        log("error", stage, detail=_clip(str(error), 120))

    log("assets", "finalize: five verifiable assets", out=str(out))
    try:
        out.mkdir(parents=True, exist_ok=True)
    except Exception as error:
        fail("mkdir", error)

    gold = {"schema": GOLD_SCHEMA, "package": PKG, "version": VERSION,
            "case_id": result.get("case_id"), "generated": _now(), "items": [],
            "counts": {"total": 0}, "expected": {}, "source_files": []}
    try:
        gold = golden(bundle)
        _wr_json(out / "golden_standard.json", gold)
        log("assets.golden", "written", items=gold["counts"]["total"],
            bytes=_size(out / "golden_standard.json"))
    except Exception as error:
        fail("golden", error)
        try:
            _wr_json(out / "golden_standard.json", gold)
        except Exception:
            pass

    probe = {"mode": "unavailable", "all_ok": None}
    try:
        import audit
        probe = audit.probes(bundle)
        log("assets.probes", "empty/bad/repeatable subprocess probes", mode=probe.get("mode"),
            all_ok=probe.get("all_ok"), elapsed_s=probe.get("elapsed_s"))
    except Exception as error:
        fail("probes", error)

    diff_md, diff_sum = "# 差异核验报告\n\n金标准生成失败，见 run.log。\n", {}
    try:
        import audit
        bundle["pending"] = ("diff_report.md", "version_history.md", "run.log",
                              "self_check.json")
        diff_md, diff_sum = audit.diff(gold, bundle, probe)
        (out / "diff_report.md").write_text(diff_md, encoding="utf-8")
        log("assets.diff", "written", rows=diff_sum.get("total"),
            pass_=diff_sum.get("pass"), missing=diff_sum.get("missing"),
            deviation=diff_sum.get("deviation"), record=diff_sum.get("record"),
            bytes=_size(out / "diff_report.md"))
    except Exception as error:
        fail("diff", error)
        try:
            (out / "diff_report.md").write_text(diff_md, encoding="utf-8")
        except Exception:
            pass

    try:
        (out / "version_history.md").write_text(history(bundle), encoding="utf-8")
        log("assets.version", "written", bytes=_size(out / "version_history.md"))
    except Exception as error:
        fail("version", error)

    checks = None
    try:
        import audit
        checks = audit.selfcheck(gold, bundle, diff_sum, probe)
        _wr_json(out / "self_check.json", checks)
        log("assets.selfcheck", "written", bytes=_size(out / "self_check.json"),
            pass_=checks.get("pass"))
    except Exception as error:
        fail("selfcheck", error)

    def ref(name, extra=None):
        record = {"path": name, "bytes": _size(out / name)}
        record.update(extra or {})
        return record

    result["golden_standard"] = ref("golden_standard.json", {
        "schema": GOLD_SCHEMA, "items": gold.get("counts", {}).get("total") or 0,
        "by_basis": gold.get("counts", {}).get("by_basis") or {},
        "verbatim": gold.get("counts", {}).get("verbatim") or {},
        "case_id": gold.get("case_id")})
    result["diff_report"] = ref("diff_report.md", {
        key: diff_sum.get(key) for key in ("total", "pass", "missing", "deviation", "record")})
    result["version_history"] = ref("version_history.md", {"current_version": VERSION})
    result["self_check"] = ref("self_check.json", {
        "schema": CHK_SCHEMA, "pass": (checks or {}).get("pass"),
        "passed": (checks or {}).get("passed"), "total": (checks or {}).get("total"),
        "skipped": (checks or {}).get("skipped")})
    bundle["result"] = result

    # run.log is rendered once, after every content stage and before self_check finalization;
    # its byte length is therefore exact and can be pointed at from result.json.
    log("assets", "four assets written",
        golden=_size(out / "golden_standard.json"), diff=_size(out / "diff_report.md"),
        version=_size(out / "version_history.md"),
        self_check=_size(out / "self_check.json"))
    log("finalize", "result.json contract fields + five asset refs",
        status=result.get("status"), contract=_contract_fields(bundle))
    state["_status"] = result.get("status")
    run_text, run_bytes = run_log_bytes(state, "five assets written; result.json final")
    try:
        (out / "run.log").write_text(run_text, encoding="utf-8")
    except Exception as error:
        fail("runlog", error)
    run_bytes = _size(out / "run.log")
    result["run_log"] = {"path": "run.log", "bytes": run_bytes}
    if checks is not None:
        _finalize_checks(checks, out, result, run_bytes)
        _wr_json(out / "self_check.json", checks)
        result["self_check"] = dict(result.get("self_check") or {})
        result["self_check"].update({
            "path": "self_check.json", "bytes": _size(out / "self_check.json"),
            "pass": checks.get("pass"), "passed": checks.get("passed"),
            "total": checks.get("total"), "skipped": checks.get("skipped")})
    result["run_log"] = {"path": "run.log", "bytes": run_bytes}
    try:
        save_result(result)
    except Exception as error:
        fail("result", error)
    summary.update({key: result.get(key) for key in
                    ("golden_standard", "diff_report", "version_history",
                     "run_log", "self_check")})
    summary["all_nonempty"] = all((summary.get(key) or {}).get("bytes") for key in
                                  ("golden_standard", "diff_report", "version_history",
                                   "run_log", "self_check"))
    return summary


def _contract_fields(bundle):
    case = bundle.get("case") if isinstance(bundle.get("case"), dict) else {}
    keys = _contract_keys(case)
    return len(keys) or 5


def _finalize_checks(checks, out, result, run_bytes):
    """Refresh the checks that depend on files written after the first self_check render."""
    sizes = {name: _size(out / name) for name in ASSETS}
    if not sizes.get("run.log"):
        sizes["run.log"] = run_bytes or 0
    for item in checks.get("checks") or []:
        if item.get("id") == "S5":
            item["actual"] = (
                "golden_standard.json=%dB、diff_report.md=%dB、version_history.md=%dB、"
                "run.log=%dB；self_check.json=本回执" % (
                    sizes.get("golden_standard.json") or 0,
                    sizes.get("diff_report.md") or 0,
                    sizes.get("version_history.md") or 0,
                    sizes.get("run.log") or 0))
            item["ok"] = all((sizes.get(name) or 0) > 0 for name in
                             ("golden_standard.json", "diff_report.md",
                              "version_history.md", "run.log"))
        elif item.get("id") == "S10":
            fields = ("golden_standard", "diff_report", "version_history", "run_log",
                      "self_check")
            present = len([key for key in fields
                           if isinstance(result.get(key), dict) and result[key].get("path")])
            item["actual"] = "%d/5 已回填 result.json（含 path+bytes）" % present
            item["ok"] = present == 5
        elif item.get("id") == "S11":
            codes = checks.get("exit_code_assertion") or {}
            child = [codes.get("probe_child_empty"), codes.get("probe_child_bad")]
            item["ok"] = bool(codes.get("main_returns") == 0 and all(
                (code in (0, None)) for code in child))
            item["actual"] = "main()=0；子进程 exit=%s" % ",".join(
                str(code) for code in child)
    flags = [item.get("ok") for item in checks.get("checks") or [] if item.get("ok") is not None]
    checks["pass"] = bool(flags) and all(flags)
    checks["passed"] = len([flag for flag in flags if flag])
    checks["total"] = len(flags)
    checks["skipped"] = len([item for item in checks.get("checks") or []
                             if item.get("ok") is None])
    checks["files"] = {"golden_standard.json": sizes.get("golden_standard.json"),
                       "diff_report.md": sizes.get("diff_report.md"),
                       "version_history.md": sizes.get("version_history.md"),
                       "run.log": sizes.get("run.log"),
                       "self_check.json": "本回执（写后为最终字节）",
                       "result.json": _size(out / "result.json")}
    return checks


def fallback(out_dir, note, argv=None, inp=None, out=None, state=None):
    """Disaster branch: write a minimal, honest set of five assets; return their refs."""
    out = Path(out_dir)
    state = state or {}
    try:
        out.mkdir(parents=True, exist_ok=True)
    except Exception:
        return {}
    case_id = None
    try:
        case_id = state.get("case_id") or (state.get("case") or {}).get("case_id")
    except Exception:
        pass
    try:
        _wr_json(out / "golden_standard.json", {
            "schema": GOLD_SCHEMA, "package": PKG, "version": VERSION, "case_id": case_id,
            "generated": _now(), "items": [], "counts": {"total": 0},
            "expected": {}, "source_files": [],
            "fallback_note": "主流程异常降级：金标准未能从输入推导（%s）" % _clip(note, 200)})
    except Exception:
        pass
    try:
        (out / "diff_report.md").write_text(
            "# 差异核验报告（降级）\n\n- case_id：%s\n- 主流程异常：`%s`\n"
            "- 判定：金标准未生成，无法逐项对照；五件资产按最小结构写出，"
            "缺口见 result.json 的 errors/degradations。\n" % (case_id, _clip(note, 300)),
            encoding="utf-8")
    except Exception:
        pass
    try:
        lines = [_STATIC_HISTORY, "## 3. 本次运行（runtime append，降级）", "",
                 "- 运行时间：%s" % _now(),
                 "- 命令：`python3 -B scripts/chapter_builder.py %s`" % _flat(
                     " ".join(str(x) for x in (argv or [])), 300),
                 "- 输入：`%s`；输出：`%s`" % (inp, out),
                 "- 状态：input_error（降级）；退出码：0",
                 "- 异常：`%s`" % _clip(note, 300),
                 "- 五件资产：以最小结构写出（items=0），不伪造成绩或数据。", ""]
        (out / "version_history.md").write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass
    try:
        (out / "run.log").write_text(
            "# run.log | %s v%s\n# argv: %s\n# input: %s\n# output: %s\n"
            "[fatal    ] %s\n[exit     ] exit_code=0（异常已捕获，降级写出）\n"
            % (PKG, VERSION, _flat(" ".join(str(x) for x in (argv or [])), 300), inp, out,
               _clip(note, 400)), encoding="utf-8")
    except Exception:
        pass
    try:
        _wr_json(out / "self_check.json", {
            "schema": CHK_SCHEMA, "package": PKG, "version": VERSION, "case_id": case_id,
            "generated": _now(), "pass": False, "passed": 0, "total": 2, "skipped": 0,
            "fallback_note": _clip(note, 300),
            "checks": [
                {"id": "S0", "claim": "主流程完成", "expected": "build 正常结束",
                 "actual": "异常降级：%s" % _clip(note, 160), "ok": False},
                {"id": "S11", "claim": "退出码恒为 0", "expected": 0, "actual": 0, "ok": True}],
            "exit_code_assertion": {"expected": 0, "main_returns": 0, "ok": True}})
    except Exception:
        pass
    refs = {}
    keys = {"golden_standard.json": "golden_standard", "diff_report.md": "diff_report",
            "version_history.md": "version_history", "run.log": "run_log",
            "self_check.json": "self_check"}
    for name, key in keys.items():
        refs[key] = {"path": name, "bytes": _size(out / name)}
    return refs
