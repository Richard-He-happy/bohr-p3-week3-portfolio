#!/usr/bin/env python3
"""redraft.py -- 成果转化改写入口：init / show / check / build 四个动作。标准库、离线、退出码恒 0。"""
import argparse
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(BASE))
try:
    import compose as cp
except Exception:
    cp = None
try:
    import sourcekit as sk
except Exception:
    sk = None

SKILL, VERSION, START = "research-to-reader", "1.0.0", time.time()


def resolve_dirs(args):
    """定位 input/output/work 三个目录；输入缺失时退到包旁或当前目录，目录不可写时退到包旁。"""
    inp = Path(args.input or os.environ.get("SKILL_INPUT") or "/input")
    out = Path(args.output or os.environ.get("SKILL_OUTPUT") or "/app/output")
    wrk = Path(args.work or os.environ.get("SKILL_WORK") or "/app/work")
    notes = []
    if not inp.exists():
        for cand in (BASE.parent / "input", Path.cwd() / "input"):
            if cand.exists():
                notes.append("输入 %s 不存在，改用 %s" % (inp, cand))
                inp = cand
                break
    for folder, tag in ((wrk, "work"), (out, "output")):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            spare = BASE.parent / tag
            spare.mkdir(parents=True, exist_ok=True)
            notes.append("%s 不可写→%s" % (folder, spare))
            wrk, out = (spare, out) if tag == "work" else (wrk, spare)
    return inp, out, wrk, notes


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def read_any(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def load_json_work(dirpath, name):
    path = Path(dirpath) / name
    if not path.is_file():
        return None, "%s 不存在" % name
    try:
        return read_any(path), None
    except Exception as exc:
        return None, "%s 解析失败：%s" % (name, type(exc).__name__)


def cmd_init(args):
    inp, out, wrk, notes = resolve_dirs(args)
    write_json(out / "result.json", {"case_id": "UNKNOWN-CASE", "status": "partial", "sources": [],
                                     "degradations": ["init 启动"], "errors": [], "runtime": {}})
    case, case_path, mats, degradations = sk.sweep_input(inp) if sk else (None, None, [], [])
    instruction = sk.to_text((inp / "task.md").read_bytes()) if sk and (inp / "task.md").is_file() else ""
    index = cp.build_index(case, case_path, mats, instruction) if cp else {}
    index["degradations"] = list(degradations) + list(notes)
    write_json(wrk / "index.json", index)
    if not (wrk / "draft.json").is_file():
        write_json(wrk / "draft.json", cp.make_worknote(index) if cp else {})
    res = {"case_id": index["case_id"], "status": "partial",
           "degradations": degradations + notes + ["索引完成，等待工作稿"],
           "sources": [{k: m[k] for k in ("id", "name", "kind", "role", "method", "paragraphs")}
                       for m in index["materials"]],
           "pending_human": ["工作稿未完成，deliverable.md 尚未生成"], "errors": [], "uncertainty": [],
           "preserved_facts": [], "evidence_map": [], "change_log": [], "deliverable": None,
           "runtime": {"skill": SKILL, "version": VERSION, "elapsed_s": round(time.time() - START, 1)}}
    for field in index["output_contract"]:
        res.setdefault(field, [] if any(h in field.lower() for h in ("list", "map", "log", "facts")) else None)
    write_json(out / "result.json", res)
    try:
        import assets as _assets
        _assets.generate(out, inp, wrk, out / "result.json", 0)
    except Exception as _exc:
        pass
    order = index["workorder"]
    lines = ["== 材料索引 =="] + ["%-4s %-24s %-5s %-17s %6d字/%3d段 [%s]" % (
        m["id"], m["name"][:24], m["kind"], m["method"], m["chars"], m["paragraphs"], m["role"])
        for m in index["materials"]] or ["(无材料)"]
    lines += ["", "== 工作单 ==", "case_id: %s" % index["case_id"],
              "受众: %s%s" % (order.get("audience") or "未识别（按题面确认）",
                             "  <- `%s`" % order["basis"]["audience"] if order["basis"].get("audience") else ""),
              "体裁: %s" % (order.get("genre") or "未识别"),
              "篇幅: %s" % (order.get("length") or "未限定"),
              "契约: %s（%d 字段）" % (", ".join(index["output_contract"]) or "无", len(index["output_contract"])),
              "", "== 段落（前 40；共 %d） ==" % len(index["paragraphs"])]
    lines += ["%-10s %5d字  %s" % (p["loc"], p["chars"], p["text"][:54].replace("\n", " "))
              for p in index["paragraphs"][:40]]
    lines += ["", "== 关键数字 =="] + ["  " + k for k in index["key_numbers"][:15]]
    lines += ["", "== 缩写 ==", "  " + (", ".join(index["acronyms"][:25]) or "未检出"), "",
              "下一步：按 references/worknote-format.md 写 %s，然后 check → build。" % (wrk / "draft.json")]
    print("\n".join(lines))
    return 0


def cmd_show(args):
    _, _, wrk, _ = resolve_dirs(args)
    index, why = load_json_work(wrk, "index.json")
    if why:
        print("无法显示原文：%s（先跑 init）" % why)
        return 0
    chosen = [p for p in index["paragraphs"] if not args.mat or p["mat"] == args.mat]
    if args.ids:
        wanted = set()
        for part in re.split(r"[,\s]+", args.ids.strip()):
            span = re.match(r"(M\d+):P(\d+)-(?:M\d+:)?P?(\d+)$", part)
            if span:
                wanted |= {"%s:P%d" % (span.group(1), i) for i in range(int(span.group(2)), int(span.group(3)) + 1)}
            elif part:
                wanted.add(part)
        chosen = [p for p in chosen if p["loc"] in wanted]
    if args.grep:
        try:
            rx = re.compile(args.grep, re.I)
        except re.error:
            rx = re.compile(re.escape(args.grep), re.I)
        chosen = [p for p in chosen if rx.search(p["text"])]
    limit = max(1, args.limit)
    for p in chosen[:limit]:
        print("[%s] (%d字)\n%s\n" % (p["loc"], p["chars"], p["text"]))
    print("-- 命中 %d 段，显示 %d；材料 %s" % (len(chosen), min(len(chosen), limit), ", ".join(
        "%s=%s(%s)" % (m["id"], m["name"], m["method"]) for m in index["materials"])))
    return 0


def cmd_check(args):
    _, out, wrk, _ = resolve_dirs(args)
    index, why = load_json_work(wrk, "index.json")
    report = {"status": "partial", "errors": [], "warnings": [], "pending": [], "stats": {}}
    if why:
        report["errors"].append({"code": "no_index", "msg": why + "（先跑 init）"})
    else:
        note, why = load_json_work(wrk, "draft.json")
        if why:
            report["errors"].append({"code": "no_draft", "msg": why + "（先写工作稿）"})
        elif sk:
            report = sk.inspect_draft(note, index)
            try:
                lost = sk.missing_contract_keys(read_any(out / "result.json"), index.get("output_contract") or {})
                if lost:
                    report["warnings"].append({"code": "contract_missing",
                                               "msg": "result.json 缺契约字段：" + ", ".join(lost)})
            except Exception:
                pass
    write_json(wrk / "check.json", report)
    stats = report["stats"]
    print("== check ==\n判定 %s | 段落 %s | 正文 %s 字 | 引文 %s/%s | 成稿数字 %s（漂移 %s）" % (
        report["status"], stats.get("sections"), stats.get("body_words"), stats.get("quote_hit"),
        stats.get("quote_total"), stats.get("numbers_in_body"), len(stats.get("number_errors") or [])))
    for item in report["errors"]:
        print("  [错误] " + str(item.get("msg")))
    for item in report["warnings"]:
        print("  [提示] " + str(item.get("msg")))
    print("报告 %s" % (wrk / "check.json"))
    return 0


def cmd_build(args):
    inp, out, wrk, notes = resolve_dirs(args)
    degradations, extra_errors = list(notes), []
    index, why = load_json_work(wrk, "index.json")
    if index is None:
        case, case_path, mats, shadow = sk.sweep_input(inp) if sk else (None, None, [], [])
        instruction = sk.to_text((inp / "task.md").read_bytes()) if sk and (inp / "task.md").is_file() else ""
        degradations.append(why)
        index, degradations = cp.build_index(case, case_path, mats, instruction), degradations + shadow + \
            ["index.json 缺失，build 内重建"]
    else:
        for item in index.get("degradations") or []:
            if item not in degradations:
                degradations.append(item)
    note, why = load_json_work(wrk, "draft.json")
    report = {"status": "partial", "errors": [], "warnings": [], "pending": [], "stats": {}}
    fallback = bool(why)
    if why:
        extra_errors.append(why)
    elif sk:
        report = sk.inspect_draft(note, index)
        fallback = not any(str(x.get("text") or "").strip() for x in note.get("sections") or [] if isinstance(x, dict))
    if fallback:
        alt = cp.salvage_note(index, index.get("workorder") or {})
        if alt:
            note, fallback = alt, True
            degradations.append("工作稿缺失或不可用 → 确定性抽取兜底（未做读者改写）")
            if sk:
                report = sk.inspect_draft(note, index)
        elif not note:
            note = cp.make_worknote(index)
            note["headline"] = "无可用材料：未生成转化稿"
            degradations.append("无材料或无工作稿，deliverable 仅含占位说明")
    target = 0
    for source in ((index.get("workorder") or {}).get("length"), (note.get("genre") or {}).get("length_target")):
        found = re.search(r"(\d{2,5})", str(source or ""))
        if found:
            target = int(found.group(1))
            break
    stats = report.get("stats") or {}
    words = stats.get("body_words") or 0
    ctx = {"status": "partial", "fallback": fallback, "inp": inp, "wrk": wrk, "target": target,
           "ok_len": bool(target and 0.7 <= words / target <= 1.5), "degr": degradations, "unc": [],
           "basis": (index.get("workorder") or {}).get("basis") or {}, "started": START}
    if not [p for p in index["paragraphs"] if p["role"] != "instruction"]:
        ctx["status"] = "insufficient_evidence"
        ctx["unc"].append("输入没有可解析的事实材料，只能生成占位稿")
    elif not fallback and report["status"] == "ok":
        ctx["status"] = "ok"
    if not (index.get("output_contract") or {}):
        degradations.append("输入无 output_contract，result.json 仅含内置字段")
    if not (index.get("workorder") or {}).get("audience"):
        ctx["unc"].append("受众按默认推断，需作者确认")
    if not target:
        ctx["unc"].append("篇幅没有明确上限，按文体常规处理")
    (out / "deliverable.md").write_text(cp.render(ctx, note, report), encoding="utf-8")
    res = cp.finalize(out, index, note, report, ctx, extra_errors)
    assets_info = {}
    try:
        import assets as _assets
        assets_info = _assets.generate(out, inp, wrk, out / "result.json", 0) or {}
    except Exception as _exc:
        try:
            _res = read_any(out / "result.json")
            _res.setdefault("degradations", []).append("资产生成失败：%s: %s" % (type(_exc).__name__, _exc))
            write_json(out / "result.json", _res)
        except Exception:
            pass
    print("== build ==\nstatus=%s fallback=%s 字数=%s 目标=%s 文件=%s" % (
        res["status"], fallback, words, target or "-", sorted(res["runtime"]["files"])))
    print("保真摘要：引文 %s/%s ｜ 数字漂移 %s ｜ 契约回填 %s/%s" % (
        stats.get("quote_hit"), stats.get("quote_total"), len(stats.get("number_errors") or []),
        res["fidelity_summary"]["contract"]["filled"], res["fidelity_summary"]["contract"]["declared"]))
    print("errors %d | pending %d | degradations %d" % (
        len(res["errors"]), len(res["pending_human"]), len(res["degradations"])))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="redraft.py",
                                 description="科研成果转化改写（%s v%s）：建索引 → 校验工作稿 → 排版成稿" % (SKILL, VERSION))
    ap.add_argument("--input", default="", help="输入目录，默认 /input")
    ap.add_argument("--output", default="", help="产物目录，默认 /app/output")
    ap.add_argument("--work", default="", help="工作目录，默认 /app/work")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("init", help="扫描输入、建材料索引、写 partial result.json 与工作稿模板")
    show = sub.add_parser("show", help="按定位或关键词打印源文段落")
    show.add_argument("--ids", default="", help="定位区间，例如 M1:P1-M1:P6")
    show.add_argument("--grep", default="", help="正则或普通关键词")
    show.add_argument("--mat", default="", help="只输出某份材料，例如 M1")
    show.add_argument("--limit", type=int, default=40)
    sub.add_parser("check", help="校验工作稿：结构 / 引文 / 数字 / 覆盖 / 对照")
    sub.add_parser("build", help="生成 deliverable.md 并 finalize result.json")
    args = ap.parse_args(argv)
    action = args.cmd or "init"
    try:
        return {"init": cmd_init, "show": cmd_show, "check": cmd_check, "build": cmd_build}[action](args)
    except Exception as exc:
        try:
            _, out, _, _ = resolve_dirs(args)
            write_json(out / "result.json", {
                "case_id": "UNKNOWN-CASE", "status": "partial", "sources": [], "uncertainty": [],
                "preserved_facts": [], "evidence_map": [], "change_log": [], "degradations": [],
                "errors": ["%s: %s" % (type(exc).__name__, exc), traceback.format_exc()[-600:]],
                "pending_human": ["需人工重跑"],
                "runtime": {"skill": SKILL, "version": VERSION, "elapsed_s": round(time.time() - START, 1)}})
            if action != "show":
                (out / "deliverable.md").write_text(
                    "# 交付说明\n\n运行在 `%s` 阶段异常：%s\n\n兜底记录见 result.json 的 errors。\n" % (action, exc),
                    encoding="utf-8")
        except Exception:
            pass
        print("异常已兜底：%s: %s" % (type(exc).__name__, exc))
        return 0


if __name__ == "__main__":
    sys.exit(main())
