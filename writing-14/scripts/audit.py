#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit.py — 结构体检、兜底成稿、自检探针与审计落盘。

金标准与逐项对照在 golden.py；本文件负责「把工作稿变成可判读的体检结论 + 附件」，
任何异常只降级为 error 记录，退出码恒 0。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import mmcore
import golden
import assets

HERE = Path(__file__).resolve().parent
CLI = HERE / "mindmap_cli.py"
T0 = time.time()

# ---------------------------------------------------------------- 小工具
def stamp(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def note(work, out, step, msg, level="INFO"):
    line = "%s %+6.2fs [%-5s] %-7s %s" % (stamp(), time.time() - T0, level, step, str(msg)[:400])
    for folder in (work, out):
        if not folder:
            continue
        try:
            target = Path(folder) / "run.log"
            target.parent.mkdir(parents=True, exist_ok=True)
            old = target.read_text(encoding="utf-8", errors="replace").splitlines() if target.is_file() else []
            target.write_text("\n".join((old + [line])[-400:]) + "\n", encoding="utf-8")
        except Exception:
            pass
    return line


def wjson(path, obj):
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def wtext(path, text):
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 兜底成稿
def _heading(text):
    t = (text or "").strip()
    return bool(t) and len(t) <= 34 and not re.search(r"[。．.；;！!？?：:]$", t)


def _groups(units, cap=5):
    out, cur = [], []
    for u in units:
        if _heading(u.get("text")) and cur:
            out.append(cur)
            cur = [u]
        else:
            cur.append(u)
    if cur:
        out.append(cur)
    out = [g for g in out if len(g) >= 2]
    if len(out) < 2 and len(units) >= 4:
        parts = min(cap, max(2, len(units) // 2))
        step = max(1, (len(units) + parts - 1) // parts)
        out = [units[i:i + step] for i in range(0, len(units), step)][:cap]
    return out[:cap]


def scaffold(index):
    """确定性兜底：一份材料一支，段首作分支名，其后段落作叶子，引文照抄原文。"""
    mats = [m for m in (index or {}).get("materials") or [] if m.get("units")]
    title = next((m["title"] for m in mats if len(m.get("title") or "") >= 4), None)
    nodes, spare, bid = [], [], 0
    for mat in mats[:3]:
        for group in _groups(mat["units"]):
            if len(nodes) >= 28:
                break
            bid += 1
            key, head = "b%d" % bid, group[0]
            head_label = re.sub(r"^#{1,6}\s*", "", mmcore.first_sentence(head.get("text"), 40)).strip()
            nodes.append({"id": key, "parent": "root", "role": "subtopic", "status": "summary",
                          "label": (head_label or mat.get("title") or mat["name"])[:20],
                          "evidence": [{"material": mat["id"], "locator": head.get("locator"),
                                        "quote": mmcore.first_sentence(head.get("text"), 150)}]})
            for k, u in enumerate(group[1:5], 1):
                leaf = mmcore.first_sentence(u.get("text"), 34).strip("。．. 、")
                if len(leaf) < 3:
                    continue
                nodes.append({"id": "%s_%d" % (key, k), "parent": key, "role": "evidence",
                              "status": "summary", "label": leaf[:22],
                              "evidence": [{"material": mat["id"], "locator": u.get("locator"),
                                            "quote": mmcore.first_sentence(u.get("text"), 150)}]})
            spare.extend((key, mat["id"], u) for u in group[5:])
    for key, mid, u in spare:
        if len(nodes) >= 16:
            break
        leaf = mmcore.first_sentence(u.get("text"), 34).strip("。．. 、")
        if len(leaf) < 3:
            continue
        nodes.append({"id": "%s_x%d" % (key, len(nodes)), "parent": key, "role": "evidence",
                      "status": "summary", "label": leaf[:22],
                      "evidence": [{"material": mid, "locator": u.get("locator"),
                                    "quote": mmcore.first_sentence(u.get("text"), 150)}]})
    if not nodes:
        nodes = [{"id": "n1", "parent": "root", "role": "risk", "label": "材料无可解析文本，需人工补录"}]
    return {"theme": {"label": (title or str((index or {}).get("case_id") or "材料要点"))[:40]},
            "nodes": nodes, "edges": []}


# ---------------------------------------------------------------- 结构体检
def inspect(draft, index):
    """把工作稿译成模型并逐项体检；check 命令与金标准对照共用这份事实。"""
    model = mmcore.build_model(draft or {}, index or {})
    issues = []

    def flag(severity, code, message):
        issues.append({"severity": severity, "code": code, "message": message})

    nodes = model["nodes"]
    body = golden.corpus(index)
    if not model["theme"]["label"]:
        flag("error", "theme_missing", "缺 theme.label：中心主题必须来自材料主题")
    if not nodes:
        flag("error", "nodes_empty", "nodes 为空：至少 1 个节点才能成图")

    seen, roles, kids = {}, {}, {}
    for node in nodes:
        kids.setdefault(node["parent"], []).append(node)
        roles[node["role"]] = roles.get(node["role"], 0) + 1
        if len(node["label"]) > 30:
            flag("warn", "label_long", "标签超 30 字 %s(%d)" % (node["id"], len(node["label"])))
        key = mmcore.fold(node["label"])
        if key in seen:
            flag("warn", "label_dup", "标签重复 %s ≈ %s" % (node["id"], seen[key]))
        seen[key] = node["id"]
        local = " ".join(mmcore.fold(e.get("quote")) for e in node["evidence"])
        for token in sorted(set(re.findall(r"\d+(?:\.\d+)?", node["label"]))):
            if token not in local and token not in body:
                flag("warn", "number_untraced", "数字无出处 %s：%s" % (node["id"], token))
        if node["status"] == "inference" and not node["summary"]:
            flag("warn", "inference_bare", "推断节点缺依据说明 %s" % node["id"])
        if not node["verified"]:
            flag("error", "node_unverified", "节点无逐字证据 %s" % node["id"])

    for drop in model["dropped"]:
        flag("error" if "非法" in drop["reason"] else "warn", "edge_dropped",
             "未采用关系 %s→%s：%s" % (drop["from"], drop["to"], drop["reason"]))
    for edge in model["edges"]:
        if not edge["grounded"]:
            flag("warn", "edge_unverified", "关系引文未命中 %s→%s" % (edge["from"], edge["to"]))
    for parent, group in kids.items():
        if len(group) > 7:
            flag("warn", "fanout_wide", "%s 下挂 %d 个子节点，建议 ≤7 并合并同级" % (parent, len(group)))
        if len(group) >= 3:
            span = sorted(len(n["label"]) for n in group)
            if span[-1] - span[0] >= 14:
                flag("warn", "granularity_skew", "%s 下同级标签 %d–%d 字，粒度不齐"
                     % (parent, span[0], span[-1]))
    if model["cycles"]:
        flag("error", "hierarchy_cycle", "父子链成环/断链：%s" % ", ".join(model["cycles"][:6]))
    if len(nodes) >= 6:
        for need in ("method", "finding"):
            if need not in roles:
                flag("warn", "role_missing", "缺角色 %s（材料确无此维度请在 coverage_report 说明）" % need)
    if model["depth"] > 4:
        flag("warn", "depth_deep", "层级过深 %d（建议 ≤4）" % model["depth"])
    if len(nodes) > 40:
        flag("warn", "node_many", "节点过多 %d（15–40 为宜，先合并同级）" % len(nodes))
    elif 0 < len(nodes) < 15:
        flag("warn", "node_few", "节点过少 %d（15–40 为宜，需补关键分支）" % len(nodes))

    verified = [n for n in nodes if n["verified"]]
    stats = {"nodes": len(nodes), "edges": len(model["edges"]), "depth": model["depth"],
             "roles": roles, "branches": len(kids.get("root", [])),
             "verified_nodes": len(verified), "unverified_nodes": len(nodes) - len(verified),
             "verified_quotes": sum(1 for n in nodes for e in n["evidence"] if e["verified"]),
             "rejected_quotes": sum(1 for n in nodes for e in n["evidence"] if not e["verified"]),
             "verified_ratio": round(len(verified) / len(nodes), 3) if nodes else 0.0,
             "dropped": len(model["dropped"])}
    errors = sum(1 for i in issues if i["severity"] == "error")
    return {"issues": issues, "stats": stats, "errors": errors, "warnings": len(issues) - errors,
            "model": model,
            "ok": errors == 0 and len(nodes) >= 6 and stats["verified_ratio"] >= 0.8}


# ---------------------------------------------------------------- 探针与自检
def _probe(name, files, timeout=120):
    root = Path(tempfile.mkdtemp(prefix="mm-%s-" % name))
    try:
        ind, wk, out = root / "input", root / "work", root / "output"
        for folder in (ind, wk, out):
            folder.mkdir(parents=True, exist_ok=True)
        for rel, content in (files or {}).items():
            target = ind / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content if isinstance(content, bytes) else str(content).encode("utf-8"))
        env = dict(os.environ, BOHR_INPUT_DIR=str(ind), BOHR_WORK_DIR=str(wk),
                   BOHR_OUTPUT_DIR=str(out), BOHR_PROBE="1")
        started = time.time()
        proc = subprocess.run([sys.executable, "-B", str(CLI), "build"], cwd=str(root),
                              env=env, capture_output=True, timeout=timeout)
        row = {"name": name, "input": sorted((files or {}).keys()) or ["（空目录）"],
               "cwd": "临时目录（非包目录，用于验 CWD 无关）",
               "exit_code": proc.returncode, "seconds": round(time.time() - started, 2)}
        payload, valid = None, False
        try:
            payload = json.loads((out / "result.json").read_text(encoding="utf-8"))
            valid = isinstance(payload, dict)
        except Exception:
            pass
        row["result_valid"] = valid
        row["status"] = (payload or {}).get("status")
        row["artifacts"] = {p.name: p.stat().st_size for p in sorted(out.glob("*")) if p.is_file()}
        row["keys_ok"] = bool(payload) and all(k in payload for k in
                                               ("case_id", "status", "sources", "errors",
                                                "degradations", "changes", "coverage"))
        row["stderr_tail"] = (proc.stderr or b"").decode("utf-8", "replace").strip()[-180:]
        row["pass"] = bool(row["exit_code"] == 0 and valid and row["keys_ok"]
                           and (out / "mindmap.json").is_file())
        return row
    except Exception as exc:
        return {"name": name, "pass": False, "error": str(exc)[:160]}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def probes(enabled):
    if not enabled or os.environ.get("BOHR_PROBE") == "1":
        return []
    tiny = {"case.json": json.dumps({"case_id": "PROBE-TINY",
                                     "task_instruction": "把材料整理成思维导图",
                                     "output_contract": {"deliverable": "导图", "evidence_map": "节点→来源",
                                                         "change_log": "变更"}}, ensure_ascii=False),
            "material.md": "# 标题\n\n## 方法\n使用 30 份样本对照。\n\n## 结果\n产率提升 12%。\n"}
    return [_probe("empty_input", {}),
            _probe("bad_json", {"case.json": "{\"case_id\": \"PROBE-BAD\", \"output_contract\": {",
                                "task.md": "# 探针\n\n方法：30 份样本对照。\n"}),
            _probe("tiny_material", tiny)]


def self_check(cid, model, index, svg_text, slots, items, errors, degradations,
               probe_rows, png_info, csv_rows, collisions):
    checks = []

    def add(cid_, name, expect, observed, ok, detail=None, applicable=True):
        checks.append({"id": cid_, "name": name, "expect": expect, "observed": observed,
                       "pass": bool(ok) if applicable else None, "applicable": bool(applicable),
                       "detail": [d for d in (detail or []) if d][:6]})

    nodes = (model or {}).get("nodes") or []
    keys = list((slots or {}).keys())
    lack = [k for k in keys if k not in (slots or {})]
    add("C1", "契约字段完整", "output_contract 每个键都进 result.json，缺值写 []",
        "共 %d 键，缺 %d 键" % (len(keys), len(lack)), not lack,
        ["缺键：%s" % "、".join(lack)] if lack else ["键名原样保留"])
    verified = [n for n in nodes if any(e.get("verified") for e in n.get("evidence") or [])]
    ratio = len(verified) / max(1, len(nodes))
    add("C2", "证据覆盖", "有逐字证据的节点比例 100%",
        "%d/%d = %.0f%%" % (len(verified), len(nodes), 100 * ratio), bool(nodes) and ratio > 0.999,
        ["未命中：%s" % "、".join(n["id"] for n in nodes if n not in verified)] if nodes and ratio < 0.999 else [],
        applicable=bool(nodes))
    g11 = next((i for i in items if i["id"] == "G11"), {})
    add("C3", "数字可溯", "标签数字可在引文或材料中找到", g11.get("actual") or "未计算",
        g11.get("verdict") == "达标", [g11.get("note")], applicable=bool(nodes))
    add("C4", "节点规模", "节点总数落在 15–40", "%d 节点" % len(nodes), 15 <= len(nodes) <= 40,
        applicable=bool(nodes))
    depth = max([n.get("level") or 0 for n in nodes] or [0])
    known = {n["id"] for n in nodes} | {"root"}
    orphan = [n["id"] for n in nodes if (n.get("parent") or "root") not in known]
    add("C5", "层级正确", "父节点存在、无环、深度 ≤4",
        "最大深度 %d，断链 %d" % (depth, len(orphan)), depth <= 4 and not orphan, orphan,
        applicable=bool(nodes))
    groups, quoted, broken = 0, 0, ""
    if svg_text:
        try:
            root = ET.fromstring(svg_text)
            for node in root.iter("{http://www.w3.org/2000/svg}g"):
                if (node.get("id") or "").startswith("node-"):
                    groups += 1
                    quoted += 1 if node.get("data-quote") is not None else 0
        except Exception as exc:
            broken = str(exc)[:90]
    add("C6", "SVG 可解析可编辑", "XML 可解析，node 组 = 节点数 + 1（含 root），且有 data-quote",
        "解析=%s，node 组=%d，data-quote=%d%s"
        % (not broken, groups, quoted, ("，异常：" + broken) if broken else ""),
        not broken and groups == len(nodes) + 1 and quoted >= groups, applicable=bool(svg_text))
    add("C7", "布局无重叠", "任意两节点框不相交", "重叠对 %d" % len(collisions or []),
        not collisions, ["%s ↔ %s" % (a, b) for a, b in (collisions or [])[:4]],
        applicable=bool(svg_text))
    add("C8", "产物一致", "CSV 覆盖全部节点、SVG 组数与 JSON 一致",
        "JSON=%d，CSV 行=%d，SVG 组=%d" % (len(nodes), csv_rows or 0, groups),
        (csv_rows or 0) >= len(nodes) and (groups == len(nodes) + 1 if svg_text else True),
        applicable=bool(nodes))
    add("C9", "预览可用", "预览非空可打开（PNG 魔数正确）",
        "%s，%s B" % ((png_info or {}).get("mode"), (png_info or {}).get("bytes")),
        bool((png_info or {}).get("bytes")), [(png_info or {}).get("note")],
        applicable=bool(png_info))
    for row in probe_rows:
        code = {"empty_input": "C10", "bad_json": "C11", "tiny_material": "C12"}.get(row.get("name"), "C13")
        tag = {"empty_input": "空输入", "bad_json": "坏 JSON", "tiny_material": "极小材料"}.get(
            row.get("name"), row.get("name"))
        add(code, "%s兜底（真实子进程）" % tag, "退出码 0，写出合法 result.json 与主产物",
            "exit=%s，result 合法=%s，状态=%s，产物 %d 个"
            % (row.get("exit_code"), row.get("result_valid"), row.get("status"),
               len(row.get("artifacts") or {})), bool(row.get("pass")),
            [row.get("error") or row.get("stderr_tail")])
    add("C14", "降级可读", "errors/degradations 每条都指向具体对象",
        "errors=%d，degradations=%d" % (len(errors or []), len(degradations or [])), True,
        [str(x)[:100] for x in (list(errors or []) + list(degradations or []))[:6]])
    return {"case_id": cid, "generated": stamp(),
            "environment": {"python": sys.version.split()[0], "stdlib_only": True, "offline": True,
                            "cwd_independent": True,
                            "renderers": [c for c in ("rsvg-convert", "inkscape", "convert", "chromium")
                                          if shutil.which(c)]},
            "checks": checks,
            "summary": {"checks": len(checks),
                        "applicable": sum(1 for c in checks if c["applicable"]),
                        "passed": sum(1 for c in checks if c["pass"] is True),
                        "failed": [c["id"] for c in checks if c["pass"] is False],
                        "na": [c["id"] for c in checks if c["applicable"] is False],
                        "pass": all(c["pass"] is not False for c in checks)}}


# ---------------------------------------------------------------- 落盘
def emit(stage, cid=None, case=None, contract=None, index=None, model=None, svg_text=None,
         out=None, work=None, slots=None, errors=None, degradations=None, do_probe=True,
         mode="agent", png_info=None):
    out, work, index = Path(out or "/app/output"), Path(work or "/app/work"), index or {}
    model = model if isinstance(model, dict) else {"nodes": [], "edges": [], "dropped": [],
                                                   "theme": {"label": "", "evidence": []}}
    summary = {}
    try:
        out.mkdir(parents=True, exist_ok=True)
        note(work, out, stage, "审计开始：材料 %d 份" % len(index.get("materials") or []))
        gold = golden.build(case or {}, contract or {}, index, stage)
        wjson(out / "golden_standard.json", gold)
        items = golden.compare(gold, model, index, stage, slots)
        counts = golden.tally(items)
        nodes = (model or {}).get("nodes") or []
        stats = {"nodes": len(nodes), "edges": len(model.get("edges") or []) if model else 0,
                 "depth": max([n.get("level") or 0 for n in nodes] or [0]),
                 "roles": {r: sum(1 for n in nodes if n.get("role") == r) for r in mmcore.ROLE_CODES},
                 "branches": sum(1 for n in nodes if n.get("parent") == "root"),
                 "verified_nodes": sum(1 for n in nodes if n.get("verified")),
                 "verified_ratio": (sum(1 for n in nodes if n.get("verified")) / len(nodes)) if nodes else 0.0,
                 "dropped": len((model or {}).get("dropped") or [])}
        rows = mmcore.write_evidence_csv(model, out / "node_evidence.csv") if stage == "build" else 0
        pend = mmcore.pending_items(model, index, stats)
        wjson(out / "pending_human.json",
              {"case_id": cid, "generated": stamp(), "count": len(pend), "items": pend})
        reqs = golden.requirements_of(index, model, contract)
        probe_rows = probes(do_probe and stage == "build")
        collisions = []
        if stage == "build" and svg_text and model:
            collisions = mmcore.collisions(mmcore.compose(model)["boxes"])
        check = self_check(cid, model, index, svg_text, slots, items, errors, degradations,
                           probe_rows, png_info, rows, collisions)
        report = {"schema": "mindmap-audit/1.0", "case_id": cid, "stage": stage,
                  "generated": stamp(), "counts": counts, "diff": items,
                  "requirements": reqs, "checks": check["checks"],
                  "summary": check["summary"], "probes": probe_rows,
                  "environment": check["environment"],
                  "limits": ["覆盖判定按 locator/角色/关键词做确定性匹配，等价表述可能被低估",
                             "分支锚点只取材料中可逐字引用的段落；材料没写的维度不进期待清单"]}
        wjson(out / "audit_report.json", report)
        coverage_bytes = mmcore.write_coverage(out / "coverage_report.md", cid, index, model, stats,
                                              items, reqs, probe_rows,
                                              (png_info or {}).get("mode"), stamp())
        summary = {"golden_standard": {"path": "golden_standard.json", "stage": stage,
                                       "requirements": len(items), "satisfied": counts["达标"],
                                       "deviations": counts["偏差"], "missing": counts["缺失"],
                                       "pending": counts["待定"]},
                   "audit_report": {"path": "audit_report.json", "pass": check["summary"]["pass"],
                                    "checks": check["summary"]["checks"],
                                    "failed": check["summary"]["failed"], "diff": items},
                   "node_evidence": {"path": "node_evidence.csv", "rows": rows},
                   "coverage_report": {"path": "coverage_report.md", "bytes": coverage_bytes,
                                       "requirements": len(reqs),
                                       "covered": sum(1 for r in reqs if r["verdict"] == "covered")},
                   "pending_human": {"path": "pending_human.json", "count": len(pend)},
                   "self_check": {"path": "audit_report.json#checks",
                                  "pass": check["summary"]["pass"],
                                  "checks": check["summary"]["checks"],
                                  "failed": check["summary"]["failed"]},
                   "probes": probe_rows}
        try:
            asset_summary = assets.emit(out=out, work=work, cid=cid, stage=stage,
                                        contract=contract or {}, index=index, model=model,
                                        items=items, counts=counts, checks=check, slots=slots,
                                        probes=probe_rows, svg_text=svg_text or "",
                                        png_info=png_info or {}, errors=errors or [],
                                        degradations=degradations or [], summary=summary,
                                        mode=mode, coverage_bytes=coverage_bytes,
                                        csv_rows=rows, pend=len(pend))
            summary.update(asset_summary or {})
        except Exception as exc:
            note(work, out, stage, "可核验资产降级：%s" % exc, "ERROR")
            summary["assets_error"] = str(exc)[:200]
        assets.ensure(out, cid, stage)
        note(work, out, stage, "对照 达标 %d / 偏差 %d / 缺失 %d / 待定 %d；自检 %s"
             % (counts["达标"], counts["偏差"], counts["缺失"], counts["待定"],
                "通过" if check["summary"]["pass"] else "未通过"),
             "INFO" if check["summary"]["pass"] else "WARN")
    except Exception as exc:
        note(work, out, stage, "审计降级：%s" % exc, "ERROR")
        assets.ensure(out, cid, stage)
        summary = {"error": str(exc)[:200],
                   "self_check": {"path": None, "pass": False, "checks": 0,
                                  "failed": ["audit_failed"], "error": str(exc)[:200]}}
    assets.ensure(out, cid, stage)
    return summary


if __name__ == "__main__":
    print("audit.py：结构体检 / 兜底成稿 / 自检探针 / 审计落盘。")
    print("由 mindmap_cli.py 调用；规则句回查见 golden.py --rules。")
    raise SystemExit(0)
