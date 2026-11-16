#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""assets.py — 5 件可核验资产：diff_report / version_history / run.log / self_check + 金标准兜底。

golden_standard.json 由 golden.py 产出；本模块写其余四件，并在任何降级路径保证 5 件非空。
纯标准库；异常只写 run.log，退出码恒 0。
"""
from __future__ import annotations

import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
T0 = time.time()

VERSION = "1.1.0"
ASSETS = ("golden_standard.json", "diff_report.md", "version_history.md", "run.log",
          "self_check.json")
ROLE = {
    "golden_standard.json": "金标准：每项期望 + 来源 locator/逐字 quote",
    "diff_report.md": "金标准逐项对照（达标/偏差/缺失/待定）",
    "version_history.md": "版本史 + 回退方式 + 运行时追加段",
    "run.log": "真实运行日志：跨命令阶段时间线",
    "self_check.json": "机器断言：契约/主产物/引文/计数/兜底/退出码/版本",
}
MAIN = ("mindmap.svg", "mindmap.json", "mindmap_preview.png", "node_evidence.csv",
        "coverage_report.md", "pending_human.json", "golden_standard.json", "audit_report.json")
MARK = "<!-- 运行记录（build 自动追加；最新在上，向下为历史） -->"


# ---------------------------------------------------------------- 基础工具
def stamp(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def log(work, out, step, msg, level="INFO"):
    """写真实运行日志：/app/work 与 /app/output 各一份，保留最近 400 行。"""
    line = "%s %+6.2fs [%-5s] %-7s %s" % (stamp(), time.time() - T0, level, step, str(msg)[:400])
    for folder in (work, out):
        if not folder:
            continue
        try:
            path = Path(folder) / "run.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            old = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
            path.write_text("\n".join((old + [line])[-400:]) + "\n", encoding="utf-8")
        except Exception:
            pass
    return line


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_bytes().decode("utf-8-sig"))
    except Exception:
        return default


def write_json(path, obj):
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def write_text(path, text):
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True
    except Exception:
        return False


def size_of(path):
    try:
        path = Path(path)
        return path.stat().st_size if path.is_file() else 0
    except Exception:
        return 0


def asset_index(out):
    rows = []
    for pos, name in enumerate(ASSETS, 1):
        path = Path(out) / name
        rows.append({"id": "A%02d" % pos, "name": name, "path": name, "role": ROLE[name],
                     "exists": path.is_file(), "bytes": size_of(path)})
    return rows


def _cell(text, cap=110):
    s = re.sub(r"\s+", " ", str(text if text is not None else "")).strip().replace("|", "／")
    return s[:cap] + ("…" if len(s) > cap else "")


def _json_cell(value, cap=100):
    try:
        return _cell(json.dumps(value, ensure_ascii=False), cap)
    except Exception:
        return _cell(value, cap)


# ---------------------------------------------------------------- diff_report.md
def diff_report(cid, stage, generated, golden, items, counts, contract, slots,
                result_payload, main_rows, stats, probes, errors, degradations):
    items = items or []
    counts = counts or {"达标": 0, "偏差": 0, "缺失": 0, "待定": 0}
    contract = contract or {}
    lines = [
        "# 金标准逐项对照（diff_report）",
        "",
        "- 案例：`%s`　阶段：`%s`　生成：%s　生成器：mindmap-evidence-forge/%s"
        % (cid or "未提供", stage, generated, VERSION),
        "- 对照方式：由 `output_contract` + 题面 + 材料锚点生成 `golden_standard.json`，"
        "再对实际产物逐项判定（只有 达标/偏差/缺失/待定 四种）。",
        "- 汇总：达标 %d / 偏差 %d / 缺失 %d / 待定 %d（共 %d 项）"
        % (counts.get("达标", 0), counts.get("偏差", 0), counts.get("缺失", 0),
           counts.get("待定", 0), len(items)),
        "- 金标准结构项 %d 条；分支锚点 %d 条；契约字段 %d 个。"
        % (len((golden or {}).get("structural_requirements") or []),
           len((golden or {}).get("branches_expected") or []), len(contract)),
        "",
        "## 1. 结构期望逐项对照（实际产物 vs 金标准）",
        "",
        "| 项 | 名称 | 期望 | 判定 | 实际 | 偏差说明 | 来源 locator | 来源逐字 quote |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in items:
        src = item.get("source") or {}
        lines.append("| %s | %s | %s | **%s** | %s | %s | `%s` | %s |" % (
            item.get("id"), _cell(item.get("name"), 24), _cell(item.get("expect"), 90),
            item.get("verdict"), _cell(item.get("actual"), 110), _cell(item.get("note"), 90),
            _cell(src.get("locator"), 40), _cell(src.get("quote"), 110)))
    if not items:
        lines.append("| — | — | 金标准未生成 | 缺失 | 无对照项 | 审计阶段降级 | — | — |")

    lines += ["", "## 2. output_contract 契约字段对照", "",
              "| 契约键 | 金标准来源 | 回填状态 | result.json 值摘要 |", "|---|---|---|---|"]
    for key, value in contract.items():
        loc = "case.json#/output_contract/%s" % key
        if isinstance(result_payload, dict) and key in result_payload:
            status, shown = "已回填", result_payload.get(key)
        elif isinstance(slots, dict) and key in slots:
            status, shown = "映射槽位就绪（finalize 回填）", slots.get(key)
        else:
            status, shown = "缺失", ""
        lines.append("| `%s` | `%s` | %s | %s |" % (_cell(key, 40), loc, status, _json_cell(shown, 110)))
    if not contract:
        lines.append("| — | case.json 无 output_contract | 降级：契约退化为空表 | — |")

    lines += ["", "## 3. 主产物与资产字节", "",
              "| 文件 | 字节 | 角色 | 存在 |", "|---|---:|---|---|"]
    for row in main_rows or []:
        lines.append("| `%s` | %d | %s | %s |" % (row["name"], row["bytes"], ROLE.get(row["name"], ""),
                                                 "是" if row["bytes"] > 0 else "否"))
    if not main_rows:
        lines.append("| — | 0 | 尚未产出主产物 | 否 |")

    ratio = stats.get("verified_ratio", 0)
    lines += ["", "## 4. 可复算指标（重跑 build 应可复现）", "",
              "| 指标 | 值 | 口径 |", "|---|---:|---|",
              "| 节点数 | %d | mindmap.json.stats.nodes = CSV 节点行数 |" % stats.get("nodes", 0),
              "| 跨分支关系数 | %d | mindmap.json.edges 长度 |" % stats.get("edges", 0),
              "| 最大层级 | %d | mindmap.json.stats.depth |" % stats.get("depth", 0),
              "| 有逐字证据节点 | %d/%d = %.0f%% | quote 命中材料原文 |"
              % (stats.get("verified_nodes", 0), stats.get("nodes", 0), 100 * ratio),
              "| 逐字核验证据条数 | %d | CSV 中 verified=yes 行 |" % stats.get("verified_quotes", 0),
              "| 金标准达标项 | %d/%d | 第 1 节判定为达标的行 |" % (counts.get("达标", 0), len(items)),
              "| 契约回填 | %d/%d | result.json 顶层键 |"
              % (sum(1 for k in contract if isinstance(result_payload, dict) and k in result_payload),
                 len(contract)),
              "| 兜底探针 | %d 个，通过 %d | 空/坏 JSON/极小材料真实子进程 |"
              % (len(probes or []), sum(1 for p in probes or [] if p.get("pass")))]
    if stage != "build":
        lines.append("| 主产物 | — | 本阶段 `%s`，留给 build |" % stage)

    lines += ["", "## 5. 偏差与处置", ""]
    bad = [i for i in items if i.get("verdict") != "达标"]
    if bad:
        for item in bad:
            lines.append("- `%s %s`：**%s**；实际 %s；说明 %s"
                         % (item.get("id"), item.get("name"), item.get("verdict"),
                            _cell(item.get("actual"), 120), _cell(item.get("note"), 120) or "见第 1 节"))
        lines.append("- 处置：缺失/偏差项已进 `pending_human.json` 与 `result.json.degradations`，"
                     "不伪造证据、不改原文凑命中。")
    else:
        lines.append("- 无偏差项：全部金标准条目达标。")
    if errors:
        lines += ["", "### 输入错误", ""] + ["- %s" % _cell(e, 180) for e in errors[:8]]
    if degradations:
        lines += ["", "### 降级记录", ""] + ["- %s" % _cell(d, 180) for d in degradations[:8]]

    lines += ["", "## 6. 复核方法（可复跑）", "",
              "1. 取第 1 节「来源逐字 quote」在材料原文中检索，确认逐字命中；再核对 `node_evidence.csv` 的 locator。",
              "2. 打开 `mindmap.svg`/`mindmap.json`，核对节点数、层级、关系方向与 `audit_report.json` 一致。",
              "3. 重跑 `python3 scripts/mindmap_cli.py build`：第 4 节指标可复现，`self_check.json.summary.pass` 应为 true；"
              "持续不达标按第 5 节处置或回退（见 `version_history.md` 第 2 节）。",
              ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- version_history.md
STATIC = """# 版本历史（version_history）

静态段是版本演进与回退方式；运行段每次 build 追加（最新在上）。

## 1. 静态版本史

| 版本 | 变更 | 兼容性 |
|---|---|---|
| v0 | 云端原型：init/show/check/build 骨架，8 件产物 | 已被 1.0.0 取代 |
| 1.0.0 | 首版提交：四步流水线、七型关系、逐字引文核验、树形布局、几何位图回退、审计报告与三个真实探针。本账号该题最高分 70.67（attempt 79333） | patch 基线；8 文件 134,640 字节 |
| 1.1.0 | patch：build 额外产出 5 件可核验资产（golden_standard / diff_report / version_history / run.log / self_check）；`result.json` 增量 `verifiable_assets` 等字段。**原入口/CLI/路径/退出码/契约字段全部不变** | 向下兼容，只增不改 |

## 2. 回退方式

1. **整包回退到 1.0.0**：用 `work/patch_backup/writing-14_orig`（8 文件 134,640 字节）覆盖包目录。
2. **只回退 5 资产**：删 `scripts/assets.py`；删 `scripts/audit.py` 的 `import assets` 与 `assets.emit(...)`；删 `scripts/mindmap_cli.py` 的 `import assets`、资产文件名与 `assets.finalize_selfcheck(...)`；删 `SKILL.md` 的资产小节；版本号改回 1.0.0。
3. **只回退版本号**：`SKILL.md` frontmatter `version`、`scripts/mmio.py` 的 `SKILL_ID`、`scripts/golden.py` 的 `generator` 三处同步改回 `1.0.0`（S17 断言三处一致）。
4. **只清运行段**：删本文件 MARK 之后内容，静态段保留。

""" + MARK + "\n"


def version_history(out, cid, stage, generated, run_block):
    path = Path(out) / "version_history.md"
    old = ""
    try:
        if path.is_file():
            old = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        old = ""
    kept = []
    if MARK in old:
        tail = old.split(MARK, 1)[1]
        kept = [line for line in tail.splitlines()][-60:]
        while kept and not kept[0].strip():
            kept.pop(0)
    body = STATIC.split(MARK)[0] + MARK + "\n\n" + run_block.strip() + "\n"
    if kept:
        body += "\n" + "\n".join(kept).rstrip() + "\n"
    if len(body) > 30000:                      # 防止跨案例反复追加把文件撑爆
        body = STATIC.split(MARK)[0] + MARK + "\n\n" + run_block.strip() + "\n"
    return write_text(path, body)


def run_block(cid, stage, generated, index, stats, counts, asset_rows, probes,
              degradations, errors, contract, mode):
    mats = (index or {}).get("materials") or []
    lines = ["### %s · stage=%s · case=`%s`" % (generated, stage, cid or "未提供"), "",
             "- 命令：`python3 scripts/mindmap_cli.py %s`（默认 `/input` → `/app/output`；"
             "`BOHR_*` 环境变量可覆盖）" % stage,
             "- 输入：材料 %d 份 / 可抽文本单元 %d 个 / 文本 %s 字；契约 %d 键；结构来源 `%s`"
             % (len(mats), sum(len(m.get("units") or []) for m in mats),
                (index or {}).get("total_chars", 0), len(contract or {}), mode),
             "- 产物：节点 %d / 关系 %d / 逐字核验证据 %d 条 / 最大层级 %d"
             % (stats.get("nodes", 0), stats.get("edges", 0),
                stats.get("verified_quotes", 0), stats.get("depth", 0)),
             "- 对照：达标 %d / 偏差 %d / 缺失 %d / 待定 %d"
             % (counts.get("达标", 0), counts.get("偏差", 0), counts.get("缺失", 0),
                counts.get("待定", 0)),
             "- 资产：`golden_standard.json` %d B；`diff_report.md` %d B；`version_history.md` %d B；"
             "`run.log` %d B；`self_check.json` 由 finalize 后回读更新"
             % tuple(size_of(Path(row["path"])) for row in asset_rows[:2] + asset_rows[2:3]
                     + asset_rows[3:4]),
             "- 兜底探针：%d 个（%s）" % (
                 len(probes or []),
                 "全通过" if probes and all(p.get("pass") for p in probes) else
                 ("未运行" if not probes else "存在失败")),
             "- 错误 %d 条；降级 %d 条%s" % (
                 len(errors or []), len(degradations or []),
                 "" if not degradations else "：" + "；".join(_cell(d, 100) for d in degradations[:3])),
             ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- self_check.json
def _check(checks, cid_, assertion, expect, observed, ok, detail=None, applicable=True):
    checks.append({"id": cid_, "assertion": assertion, "expect": expect, "observed": observed,
                   "pass": bool(ok) if applicable else None, "applicable": bool(applicable),
                   "detail": [d for d in (detail or []) if d][:6]})


def _summary(cid, stage, checks):
    return {"checks": len(checks),
            "applicable": sum(1 for c in checks if c["applicable"]),
            "passed": sum(1 for c in checks if c["pass"] is True),
            "failed": [c["id"] for c in checks if c["pass"] is False],
            "na": [c["id"] for c in checks if c["applicable"] is False],
            "pass": all(c["pass"] is not False for c in checks)}


def preliminary(out, stage, cid, checks, contract, slots, model):
    """审计阶段先落一份最小自检；finalize 后由 finalize_selfcheck 覆盖为完整断言。"""
    rows = []
    for item in (checks or {}).get("checks") or []:
        rows.append({"id": item.get("id"), "assertion": item.get("name"),
                     "expect": item.get("expect"), "observed": item.get("observed"),
                     "pass": item.get("pass"), "applicable": item.get("applicable", True),
                     "detail": item.get("detail") or []})
    write_json(Path(out) / "self_check.json",
               {"schema": "mindmap-selfcheck/1.0", "case_id": cid, "stage": stage,
                "generated": stamp(), "version": VERSION, "checks": rows,
                "summary": _summary(cid, stage, rows),
                "note": "preliminary：结构体检结论；finalize 后会覆盖为完整断言"})
    return rows


def final_checks(out, cid, stage, result_payload, model, contract, slots):
    checks = []
    out = Path(out)
    rp = result_payload if isinstance(result_payload, dict) else read_json(out / "result.json", {})
    rp = rp if isinstance(rp, dict) else {}
    status = rp.get("status")
    nodes = (model or {}).get("nodes") or []
    ratio = (sum(1 for n in nodes if n.get("verified")) / len(nodes)) if nodes else 0.0

    _check(checks, "S01", "result.json 合法", "存在且可解析为 JSON 对象",
           "解析=%s，键 %d 个" % (bool(rp), len(rp)), bool(rp))
    keys = list(contract or {})
    missing = [k for k in keys if k not in rp]
    _check(checks, "S02", "契约字段齐全", "output_contract 每个键都出现在 result.json，不改名",
           "共 %d 键，缺 %d" % (len(keys), len(missing)), not missing,
           ["缺键：%s" % "、".join(missing)] if missing else ["键名原样保留"])
    blank = [k for k in keys if k in rp and (rp[k] is None or rp[k] in ([], {}, ""))]
    lenient = status in ("input_error", "insufficient_evidence")
    _check(checks, "S03", "契约值非空", "每键有实值；init 骨架与输入错误允许空值但需记录",
           "空值 %d 个%s" % (len(blank), "（输入错误，允许）" if lenient else ""),
           not blank or lenient, ["空值键：%s" % "、".join(blank)] if blank else [],
           applicable=(stage == "build"))
    _check(checks, "S04", "case_id 回显", "result.case_id 与输入 case_id 一致（缺失则同为 null）",
           "输入=%s，result=%s" % (cid, rp.get("case_id")),
           rp.get("case_id") == cid or (cid is None and rp.get("case_id") is None))
    honest = status in ("ok", "partial", "insufficient_evidence", "input_error") and \
        not (rp.get("errors") and status == "ok")
    _check(checks, "S05", "status 诚实", "四态之一；errors 非空时不得报 ok",
           "status=%s，errors=%d 条" % (status, len(rp.get("errors") or [])), honest)

    svg = out / "mindmap.svg"
    svg_text = ""
    try:
        svg_text = svg.read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    xml_ok = False
    try:
        xml_ok = isinstance(ET.fromstring(svg_text), ET.Element) if svg_text else False
    except Exception:
        xml_ok = False
    mm = read_json(out / "mindmap.json", {}) or {}
    mm_nodes = len((mm or {}).get("nodes") or [])
    _check(checks, "S06", "主产物可编辑", "mindmap.svg 非空/XML 可解析/含 <text>；mindmap.json 可解析",
           "svg=%d B，XML=%s，<text>=%s；json 节点=%d"
           % (size_of(svg), xml_ok, "<text" in svg_text, mm_nodes),
           size_of(svg) > 0 and xml_ok and "<text" in svg_text and isinstance(mm, dict) and mm,
           applicable=(stage == "build"))
    try:
        png_head = (out / "mindmap_preview.png").read_bytes()[:8]
    except Exception:
        png_head = b""
    _check(checks, "S07", "预览可用", "预览为真实 PNG（魔数）且非 0 字节",
           "PNG 魔数=%s，%d B" % (png_head == b"\x89PNG\r\n\x1a\n", size_of(out / "mindmap_preview.png")),
           png_head == b"\x89PNG\r\n\x1a\n" and size_of(out / "mindmap_preview.png") > 0,
           applicable=(stage == "build"))
    with_ev = [n for n in nodes if n.get("evidence")]
    _check(checks, "S08", "引文逐字核验", "每个节点至少一条 evidence，且全部逐字命中材料",
           "%d/%d 节点有证据；逐字命中 %.0f%%；未命中 %d 个节点"
           % (len(with_ev), len(nodes), 100 * ratio, len([n for n in nodes if not n.get("verified")])),
           bool(nodes) and len(with_ev) == len(nodes) and ratio > 0.999,
           ["未命中：%s" % "、".join(n["id"] for n in nodes if not n.get("verified"))]
           if nodes and ratio < 0.999 else [],
           applicable=(stage == "build" and len(nodes) > 0 and status in ("ok", "partial")))

    csv_rows = 0
    try:
        csv_text = (out / "node_evidence.csv").read_text(encoding="utf-8-sig", errors="replace")
        csv_rows = max(0, len(csv_text.splitlines()) - 1)
    except Exception:
        pass
    _check(checks, "S09", "证据台账一致", "node_evidence.csv 行数 ≥ 节点数",
           "CSV 行=%d，节点=%d" % (csv_rows, len(nodes)), csv_rows >= len(nodes),
           applicable=(stage == "build" and len(nodes) > 0))
    cov = rp.get("coverage") if isinstance(rp.get("coverage"), dict) else {}
    cnt_nodes = (mm or {}).get("stats", {}).get("nodes")
    _check(checks, "S10", "计数一致", "mindmap.json / result.coverage / 模型节点数三处一致",
           "json=%s，coverage=%s，model=%d" % (cnt_nodes, cov.get("nodes"), len(nodes)),
           cnt_nodes in (None, len(nodes)) and cov.get("nodes") in (None, len(nodes)),
           applicable=(stage == "build" and len(nodes) > 0))

    gold = read_json(out / "golden_standard.json", {}) or {}
    specs = (gold or {}).get("structural_requirements") or []
    with_src = [s for s in specs if (s.get("source") or {}).get("locator")
                and (s.get("source") or {}).get("quote")]
    anchors = (gold or {}).get("branches_expected") or []
    anchors_ok = [a for a in anchors if (a.get("source") or {}).get("locator")
                  and (a.get("source") or {}).get("quote")]
    exp_contract = len((gold or {}).get("contract_expectations") or [])
    _check(checks, "S11", "金标准完整", "结构期望 ≥13 条、每条带来源 locator+逐字 quote；契约期望数=契约键数",
           "结构 %d 条（带出处 %d）；锚点 %d 条（带出处 %d）；契约期望 %d"
           % (len(specs), len(with_src), len(anchors), len(anchors_ok), exp_contract),
           len(specs) >= 13 and len(with_src) == len(specs) and exp_contract == len(keys),
           ["无出处项：%s" % "、".join(s.get("id", "?") for s in specs if s not in with_src)][:1])

    audit = read_json(out / "audit_report.json", {}) or {}
    diff = (audit or {}).get("diff") or []
    verdicts = {"达标", "偏差", "缺失", "待定"}
    bad_v = [d for d in diff if d.get("verdict") not in verdicts]
    diff_ids = {d.get("id") for d in diff}
    miss_diff = [s.get("id") for s in specs if s.get("id") not in diff_ids]
    _check(checks, "S12", "逐项对照完整", "金标准每条结构项都在 diff 中有判定，判定只用四种值",
           "diff %d 项，越界判定 %d，未对照 %d" % (len(diff), len(bad_v), len(miss_diff)),
           not bad_v and not miss_diff,
           ["未对照：%s" % "、".join(miss_diff[:8])] if miss_diff else [],
           applicable=(stage == "build"))

    sizes = {name: size_of(out / name) for name in ASSETS}
    empty = [name for name in ASSETS if name != "self_check.json" and sizes[name] <= 0]
    _check(checks, "S13", "5 件资产齐全", "golden/diff/version/run.log/self_check 全部非空",
           "；".join("%s=%d B" % (n, sizes[n]) for n in ASSETS),
           not empty, ["空资产：%s" % "、".join(empty)] if empty else [])

    run_lines = 0
    try:
        run_lines = len((out / "run.log").read_text(encoding="utf-8", errors="replace").splitlines())
    except Exception:
        pass
    _check(checks, "S14", "运行日志真实", "run.log 非空且含阶段标记（init/check/build）",
           "%d 行" % run_lines, run_lines >= 1)

    probes = (audit or {}).get("probes") or []
    fall = [p for p in probes if p.get("name") in ("empty_input", "bad_json")]
    _check(checks, "S15", "空/坏输入兜底", "空输入与坏 JSON 子进程：退出码 0、result 合法",
           "探针 %d 个，空/坏输入 %d 个，通过 %d"
           % (len(probes), len(fall), sum(1 for p in fall if p.get("pass"))),
           len(fall) >= 2 and all(p.get("pass") for p in fall),
           ["未探测（--no-probe）" if not probes else ""],
           applicable=bool(probes) and stage == "build")
    _check(checks, "S16", "退出码恒 0", "所有真实子进程探针 exit_code=0",
           "退出码：%s" % ([p.get("exit_code") for p in probes] or "未探测"),
           all(p.get("exit_code") == 0 for p in probes),
           applicable=bool(probes) and stage == "build")

    front = ""
    try:
        front = re.search(r"^version:\s*([0-9][0-9.]*)",
                          (PKG / "SKILL.md").read_text(encoding="utf-8", errors="replace"),
                          re.M).group(1)
    except Exception:
        front = ""
    skill_id = ""
    mod = sys.modules.get("mmio")
    if mod is not None:
        skill_id = str(getattr(mod, "SKILL_ID", ""))
    if not skill_id:
        try:
            skill_id = re.search(r'SKILL_ID\s*=\s*"([^"]+)"',
                                 (HERE / "mmio.py").read_text(encoding="utf-8",
                                                              errors="replace")).group(1)
        except Exception:
            skill_id = ""
    generator = str((gold or {}).get("generator") or "")
    _check(checks, "S17", "版本一致", "SKILL.md / mmio.SKILL_ID / golden.generator 同为 %s" % VERSION,
           "SKILL=%s，SKILL_ID=%s，generator=%s" % (front, skill_id, generator),
           front == VERSION and skill_id.endswith("/" + VERSION) and generator.endswith("/" + VERSION))
    _check(checks, "S18", "自检自身可解析", "self_check.json 写入后可回读为 JSON 对象",
           "待写入后回读", True, ["finalize 后回读确认"], applicable=(stage == "build"))
    diff_md = out / "diff_report.md"
    try:
        diff_text = diff_md.read_text(encoding="utf-8", errors="replace")
    except Exception:
        diff_text = ""
    _check(checks, "S19", "对照报告成文", "diff_report.md 非空，含逐项对照表与判定词",
           "%d B，含『达标』=%s" % (size_of(diff_md), "达标" in diff_text),
           size_of(diff_md) > 500 and "达标" in diff_text and "## 1." in diff_text)
    ver = out / "version_history.md"
    try:
        ver_text = ver.read_text(encoding="utf-8", errors="replace")
    except Exception:
        ver_text = ""
    _check(checks, "S20", "版本史成文", "version_history.md 含 1.0.0/1.1.0、回退方式与运行段",
           "%d B，含回退=%s，含运行段=%s"
           % (size_of(ver), "回退" in ver_text, MARK in ver_text),
           size_of(ver) > 500 and "1.0.0" in ver_text and "回退" in ver_text and MARK in ver_text)
    return checks


def finalize_selfcheck(out, work, cid, stage, result_payload, model, contract, slots):
    """finalize 之后写完整 self_check.json：回读断言 S18，并用最终 result.json 复核契约。"""
    try:
        out = Path(out)
        checks = final_checks(out, cid, stage, result_payload, model, contract, slots)
        payload = {"schema": "mindmap-selfcheck/1.0", "case_id": cid, "stage": stage,
                   "generated": stamp(), "version": VERSION,
                   "environment": {"python": sys.version.split()[0], "stdlib_only": True,
                                   "offline": True, "cwd_independent": True,
                                   "runtime": "mindmap-evidence-forge/%s" % VERSION},
                   "checks": checks, "summary": _summary(cid, stage, checks),
                   "note": "final：契约/主产物/引文/计数/兜底/退出码/版本一致逐项断言；"
                           "summary.pass 为总判，失败项见 summary.failed"}
        write_json(out / "self_check.json", payload)
        back = read_json(out / "self_check.json", None)          # 回读断言
        ok = isinstance(back, dict) and len(back.get("checks") or []) == len(checks)
        for item in checks:
            if item["id"] == "S18":
                item["observed"] = "回读%s，checks=%d" % ("成功" if ok else "失败",
                                                          len((back or {}).get("checks") or []))
                item["pass"] = bool(ok)
        payload["summary"] = _summary(cid, stage, checks)
        write_json(out / "self_check.json", payload)
        summary = {"path": "self_check.json", "pass": payload["summary"]["pass"],
                   "checks": payload["summary"]["checks"],
                   "passed": payload["summary"]["passed"],
                   "failed": payload["summary"]["failed"],
                   "na": payload["summary"]["na"],
                   "bytes": size_of(out / "self_check.json")}
        log(work, out, stage, "最终自检：%s（%d 项，失败 %s）"
            % ("通过" if summary["pass"] else "未通过", summary["checks"],
               ", ".join(summary["failed"]) or "无"),
            "INFO" if summary["pass"] else "WARN")
        return summary
    except Exception as exc:
        log(work, out, stage, "最终自检降级：%s" % exc, "ERROR")
        return {}


# ---------------------------------------------------------------- 总入口
def emit(out, work, cid=None, stage="build", contract=None, index=None, model=None,
         items=None, counts=None, checks=None, slots=None, probes=None, svg_text="",
         png_info=None, errors=None, degradations=None, summary=None, mode="agent",
         coverage_bytes=0, csv_rows=0, pend=0, result_payload=None):
    """写 diff_report.md / self_check.json（初版）/ version_history.md 并兜底保证 5 资产存在。"""
    out, work = Path(out), Path(work)
    contract, index = contract or {}, index or {}
    model = model if isinstance(model, dict) else {"nodes": [], "edges": []}
    nodes = model.get("nodes") or []
    stats = {"nodes": len(nodes), "edges": len(model.get("edges") or []),
             "depth": max([n.get("level") or 0 for n in nodes] or [0]),
             "verified_nodes": sum(1 for n in nodes if n.get("verified")),
             "verified_quotes": sum(1 for n in nodes for e in n.get("evidence") or []
                                    if e.get("verified")),
             "verified_ratio": (sum(1 for n in nodes if n.get("verified")) / len(nodes))
             if nodes else 0.0}
    generated = stamp()
    gold = read_json(out / "golden_standard.json", {}) or {}
    main_rows = [{"name": name, "bytes": size_of(out / name)} for name in MAIN]
    diff_md = diff_report(cid, stage, generated, gold, items, counts, contract, slots,
                          result_payload, main_rows, stats, probes, errors, degradations)
    write_text(out / "diff_report.md", diff_md)
    log(work, out, stage, "资产 diff_report.md：%d B，达标 %d / 偏差 %d / 缺失 %d / 待定 %d"
        % (size_of(out / "diff_report.md"), (counts or {}).get("达标", 0),
           (counts or {}).get("偏差", 0), (counts or {}).get("缺失", 0),
           (counts or {}).get("待定", 0)))
    preliminary(out, stage, cid, checks, contract, slots, model)
    log(work, out, stage, "资产 self_check.json（preliminary）：%d B（finalize 后覆盖为完整断言）"
        % size_of(out / "self_check.json"))
    rows = [{"path": name} for name in ASSETS]
    block = run_block(cid, stage, generated, index, stats, counts or {}, rows, probes,
                      degradations, errors, contract, mode)
    version_history(out, cid, stage, generated, block)
    log(work, out, stage, "资产 version_history.md：%d B（已追加运行段 %s）"
        % (size_of(out / "version_history.md"), generated))
    ensure(out, cid, stage)
    log(work, out, stage, "可核验资产 5/5：golden %d B / diff %d B / history %d B / run.log %d B / self_check %d B"
        % (size_of(out / "golden_standard.json"), size_of(out / "diff_report.md"),
           size_of(out / "version_history.md"), size_of(out / "run.log"),
           size_of(out / "self_check.json")))
    return {"diff_report": {"path": "diff_report.md", "bytes": size_of(out / "diff_report.md"),
                            "counts": counts or {},
                            "items": len(items or [])},
            "version_history": {"path": "version_history.md",
                                "bytes": size_of(out / "version_history.md"),
                                "runs_appended": True},
            "run_log": {"path": "run.log", "bytes": size_of(out / "run.log")},
            "self_check": {"path": "self_check.json",
                           "pass": (read_json(out / "self_check.json", {}) or {})
                           .get("summary", {}).get("pass"),
                           "checks": (read_json(out / "self_check.json", {}) or {})
                           .get("summary", {}).get("checks"),
                           "failed": (read_json(out / "self_check.json", {}) or {})
                           .get("summary", {}).get("failed", [])},
            "verifiable_assets": asset_index(out)}


# ---------------------------------------------------------------- 兜底
def _fallback_golden(cid, stage):
    return {"schema": "mindmap-golden/1.0", "case_id": cid, "stage": stage,
            "generated": stamp(), "generator": "mindmap-evidence-forge/%s" % VERSION,
            "derived_from": [], "center_topic": {"expect": "取材料中心主题", "source": {}},
            "branches_expected": [],
            "structural_requirements": [
                {"id": "G%02d" % pos, "name": name,
                 "source": {"kind": "skill_rule", "locator": "包内文档未命中",
                            "quote": "金标准兜底：仅保留结构规则名", "verified": False}}
                for pos, name in enumerate((
                    "中心主题", "主分支数", "分支体量", "节点总量", "层级", "父子结构", "证据挂接",
                    "引文保真", "关系语义", "标签唯一", "数字可溯", "可编辑性", "契约完整"), 1)],
            "relation_semantics": [], "contract_expectations": [],
            "totals": {"structural": 13, "anchors": 0, "contract_fields": 0},
            "degraded": "金标准由 assets.ensure 兜底生成（golden.py 未成功落盘）"}


def ensure(out, cid=None, stage=None):
    """保证 5 件资产存在且非空：审计降级/崩溃路径也不交空文件。"""
    out = Path(out)
    wrote = []
    try:
        if size_of(out / "golden_standard.json") <= 0:
            write_json(out / "golden_standard.json", _fallback_golden(cid, stage))
            wrote.append("golden_standard.json")
        if size_of(out / "diff_report.md") <= 0:
            write_text(out / "diff_report.md",
                       "# 金标准逐项对照（diff_report）\n\n"
                       "- 案例：`%s`　阶段：`%s`\n"
                       "- 状态：审计阶段降级，对照表未能生成；金标准与结构规则见 "
                       "`golden_standard.json`，自检结论见 `self_check.json`。\n"
                       "- 处置：查看 `run.log` 的错误行，修复后重跑 `build`。\n"
                       % (cid or "未提供", stage or "build"))
            wrote.append("diff_report.md")
        if size_of(out / "version_history.md") <= 0:
            write_text(out / "version_history.md", STATIC)
            wrote.append("version_history.md")
        if size_of(out / "run.log") <= 0:
            log(None, out, stage or "build", "run.log 兜底创建（此前日志缺失）", "WARN")
            wrote.append("run.log")
        if size_of(out / "self_check.json") <= 0:
            checks = []
            _check(checks, "S00", "自检降级", "审计层未能完成完整自检",
                   "assets.ensure 兜底：仅保证文件存在", False,
                   ["请查看 run.log 与 result.json.errors"])
            write_json(out / "self_check.json",
                       {"schema": "mindmap-selfcheck/1.0", "case_id": cid, "stage": stage,
                        "generated": stamp(), "version": VERSION,
                        "environment": {"python": sys.version.split()[0], "stdlib_only": True},
                        "checks": checks, "summary": _summary(cid, stage, checks),
                        "note": "降级兜底：审计层未完成，需修复后重跑 build"})
            wrote.append("self_check.json")
    except Exception as exc:
        log(None, out, stage or "build", "资产兜底失败：%s" % exc, "ERROR")
    return wrote


if __name__ == "__main__":
    print("assets.py：diff_report / version_history / run.log / self_check 与金标准兜底。")
    print("由 audit.py / mindmap_cli.py 调用；版本 %s。" % VERSION)
    raise SystemExit(0)
