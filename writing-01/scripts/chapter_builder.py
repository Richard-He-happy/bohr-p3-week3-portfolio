#!/usr/bin/env python3
"""Command line for material-anchored chapter drafts: init | show | check | build.

`build` always leaves a contract-complete result.json, the editable manuscript and the
audit files behind, and the process exit status is 0 on every path.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from material_ingest import (OUTLINE, bodies, collect, draft_sections, flat,  # noqa: E402
                             heading_matches, merge, quote_found, read_case,
                             split_sentences, title_of)

VERSION = "1.0.0"
T0 = time.time()
FIELDS = ("case_id", "change_log", "deliverable", "evidence_map", "preserved_facts")
STUB = '{"status": "input_error"}'
DIGITS = re.compile(r"\d+(?:\.\d+)?")
WORDS = ("摘要", "引言", "方法", "结果", "讨论", "结论", "参考文献", "数据可得性", "致谢", "附录")
GAP = "材料未覆盖本节，见文末缺口清单。"
LEAD = "本稿按章节锚定材料语句：材料 %d 份（可读 %d 份），证据句 %d 条，章节 %d 个。"


def save_json(path, payload):
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        try:
            Path(path).write_text(STUB, encoding="utf-8")
        except Exception:
            pass


def parse_cli(argv=None):
    cli = argparse.ArgumentParser(prog="chapter_builder.py",
                                  description="材料锚定的学术章节稿流水线 %s" % VERSION)
    cli.add_argument("cmd", nargs="?", default="build",
                     choices=["init", "show", "check", "build"])
    cli.add_argument("--input", default=None, help="材料目录，默认 /input")
    cli.add_argument("--output", default=None, help="产物目录，默认 /app/output")
    cli.add_argument("--work", default=None, help="工作目录，默认 /app/work")
    cli.add_argument("--draft", default=None, help="草稿，默认 <work>/draft.json")
    return cli.parse_args(argv)


def as_text(value):
    """Case instructions arrive as strings, objects or lists; flatten all three."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else ""


def pick(cli_value, env_key, fallback):
    """CLI flag beats environment variable beats the sandbox default."""
    return Path(cli_value or os.environ.get(env_key) or fallback).expanduser()


def prepare(args):
    root = pick(args.input, "SKILL_INPUT", "/input")
    if not root.is_dir() and (Path.cwd() / "input").is_dir():
        root = Path.cwd() / "input"
    out = pick(args.output, "SKILL_OUTPUT", "/app/output")
    work = pick(args.work, "SKILL_WORK", "/app/work")
    state = {"case": {}, "instruction": "", "case_id": "", "contract": {}, "rejected": [],
             "pending_human": [], "degradations": [], "errors": []}
    ctx = {"input": root, "output": out, "work": work, "state": state}
    try:
        out.mkdir(parents=True, exist_ok=True)
    except Exception:
        state["degradations"].append({"path": str(out), "code": "output_dir_fallback"})
        ctx["output"] = work
    try:
        work.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    case = read_case(root, state)
    state["case"] = case
    state["contract"] = case.get("output_contract")
    state["case_id"] = str(case.get("case_id") or case.get("id") or "")
    keys = ("task_instruction", "organizer_workorder", "organizer_edit_workorder", "requirements")
    pieces = [as_text(case.get(key)) for key in keys]
    state["instruction"] = flat(" | ".join(piece for piece in pieces if piece.strip()), 900)
    return ctx


def read_draft(path):
    target = Path(path)
    try:
        if not (target.is_file() and target.stat().st_size <= 8 << 20):
            return None
        payload = json.loads(target.read_bytes().decode("utf-8-sig", "replace"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def render(title, blocks, state, status, drafted, total, readable):
    """Markdown manuscript: headings, draft prose, verbatim evidence, gap appendix."""
    count = sum(len(block["items"]) for block in blocks)
    lines = ["# " + title, "", "> 流水线 v%s｜%s｜材料 %d 份（可读 %d 份）｜证据句 %d 条"
             % (VERSION, status, total, readable, count), ""]
    if not drafted:
        lines += ["> 未收到 agent 草稿：各章由材料语句锚定组装，定位符可逐条复核。", ""]
    for block in blocks:
        lines += ["## " + block["heading"], ""]
        if block["key"] == "abstract":
            lines += [LEAD % (total, readable, count, len(blocks)), ""]
        lines += [flat(text, 4000) + "\n" for text in block["paras"]]
        for item in block["items"]:
            lines += ["> " + item["quote"], ">",
                      "> 定位：`%s`（%s）" % (item["locator"], item["source_id"]), ""]
        if block["auto"] and not block["items"] and block["key"] != "abstract":
            lines += [GAP, ""]
    gaps = [block["heading"] for block in blocks
            if not block["items"] and not block["paras"]]
    notes = ["缺口章节：%s" % "、".join(flat(gap, 40) for gap in gaps)] if gaps else []
    notes += ["待确认：%s｜%s" % (flat(e.get("item"), 60), flat(e.get("reason"), 90))
              for e in state["pending_human"][:12]]
    notes += ["引用拒收：%s（%s）" % (flat(e.get("quote"), 100), e.get("locator") or "无定位")
              for e in state["rejected"][:8]]
    if state["degradations"]:
        notes.append("降级 %d 项：%s" % (len(state["degradations"]), "；".join(
            sorted({str(item.get("code")) for item in state["degradations"]}))))
    lines += ["## 附录 缺口与待确认", ""] + ["- " + note for note in notes or ["无。"]] + [""]
    body = "\n".join([text for block in blocks for text in block["paras"]]
                     + [item["quote"] for block in blocks for item in block["items"]])
    stats = {"materials": total, "readable": readable, "quotes_verified": count,
             "quotes_rejected": len(state["rejected"]),
             "h2_headings": sum(1 for line in lines if line.startswith("## ")),
             "chars": sum(len(line) for line in lines)}
    return "\n".join(lines).strip() + "\n", stats, body


def audit(body, facts, evidence):
    seen = DIGITS.findall(body)
    corpus = " ".join([str(item.get("value_text") or "") for item in facts]
                      + [str(item.get("quote") or "") for item in evidence])
    hits = sum(1 for token in seen if token in corpus)
    return {"numbers_in_draft": len(seen), "numbers_supported": hits,
            "hit_rate": round(hits / len(seen), 3) if seen else 0.0}


def report_md(stats, state):
    """Audit sheet: what is covered, what traces back, what a human still has to check."""
    audit = stats.get("number_audit") or {}
    lines = ["# 一致性检查报告", "",
             "- 章节：指令点名 %d 项，已覆盖 %d 项，缺 %d 项"
             % (len(stats.get("requested_sections") or []),
                len(stats.get("covered_sections") or []),
                len(stats.get("missing_sections") or [])),
             "- 数字：稿件 %d 个，可在证据链回溯 %d 个，命中率 %s"
             % (audit.get("numbers_in_draft", 0), audit.get("numbers_supported", 0),
                audit.get("hit_rate", 0.0)),
             "- 引用：通过 %d 条，拒收 %d 条"
             % (stats.get("quotes_verified", 0), stats.get("quotes_rejected", 0)),
             "- 待人工确认 %d 项，降级 %d 项"
             % (len(state["pending_human"]), len(state["degradations"])), ""]
    if stats.get("missing_sections"):
        lines += ["## 缺章节", ""] + ["- " + word for word in stats["missing_sections"]] + [""]
    if state["pending_human"]:
        lines += ["## 待人工确认", ""] + ["- %s：%s（%s）"
                                          % (flat(e.get("item"), 60), flat(e.get("reason"), 80),
                                             flat(e.get("action"), 80))
                                          for e in state["pending_human"]] + [""]
    return "\n".join(lines)


def compose(ctx, status, deliverable, extra):
    state = ctx["state"]
    values = {"case_id": state["case_id"], "deliverable": deliverable,
              "preserved_facts": extra.get("preserved_facts") or [],
              "evidence_map": state.get("evidence_map") or extra.get("evidence_map") or [],
              "change_log": state.get("change_log") or extra.get("change_log") or []}
    contract, result = state.get("contract"), {}
    if isinstance(contract, dict):
        for key in contract:
            result[key] = values.get(re.sub(r"[\s\-]+", "_", str(key).strip().lower()))
    elif isinstance(contract, list):
        names = [re.sub(r"[\s\-]+", "_", key.strip().lower()) if isinstance(key, str) else ""
                 for key in contract]
        result["output_contract_fields"] = [values.get(name) for name in names]
        for key, name in zip(contract, names):
            if isinstance(key, str):
                result[key] = values.get(name)
    for field in FIELDS:
        result.setdefault(field, values.get(field))
    limits = ["摘录式初稿：论证与措辞需作者补全；locator 为 `相对路径:L行号`。",
              "材料外数值、文献、图注未生成，缺口见 pending_human。"]
    if not extra.get("draft_used"):
        limits.append("未提供 agent 草稿，章节由材料语句兜底组装。")
    if any(item.get("code") == "pdf_unparsed" for item in state["degradations"]):
        limits.append("PDF 未解析，PDF 内数值可能缺失。")
    result.update({"status": status, "sources": extra.get("sources") or [],
                   "uncertainty": limits, "pending_human": state["pending_human"],
                   "errors": state["errors"], "degradations": state["degradations"],
                   "changes": values["change_log"], "coverage": extra.get("coverage") or {},
                   "runtime": {"version": VERSION, "python": sys.version.split()[0],
                               "elapsed_s": round(time.time() - T0, 2),
                               "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T0)),
                               "input_root": str(ctx["input"]),
                               "output_root": str(ctx["output"])}})
    return result


def cmd_init(ctx, _args):
    state = ctx["state"]
    materials = collect(ctx["input"], state)
    print("init | case=%s case_id=%s" % (state.get("case_path", "-"), state["case_id"] or "-"))
    print("materials=%d readable=%d sentences=%d pending=%d degradations=%d"
          % (len(materials), sum(1 for m in materials if m["readable"]),
             len(split_sentences(materials)), len(state["pending_human"]),
             len(state["degradations"])))
    for item in materials:
        print("%s %-11s %8dB %7dch %-4s %s" % (item["id"], item["kind"], item["bytes"],
                                               item["chars"],
                                               "READ" if item["readable"] else "SKIP",
                                               item["path"]))


def cmd_show(ctx, _args):
    pool = split_sentences(collect(ctx["input"], ctx["state"]))
    for item in pool[:25]:
        print("[%s] %s\n    %s" % (item["source_id"], item["locator"],
                                   flat(item["quote"], 300)))
    print("-- shown %d/%d" % (min(25, len(pool)), len(pool)))


def cmd_check(ctx, args):
    state = ctx["state"]
    stacks = bodies(collect(ctx["input"], state))
    path = Path(args.draft) if args.draft else Path(ctx["work"]) / "draft.json"
    sections = draft_sections(read_draft(path))
    verified, rejected = [], []
    for section in sections:
        for para in section["paragraphs"]:
            for quote in para.get("quotes") or []:
                ok, _mid = quote_found(quote.get("quote"), stacks, quote.get("source_id"))
                (verified if ok else rejected).append(quote)
    heads = [section["heading"] for section in sections]
    report = {"draft_found": bool(sections), "sections": len(sections),
              "paragraphs": sum(len(entry["paragraphs"]) for entry in sections),
              "quotes_total": len(verified) + len(rejected), "quotes_verified": len(verified),
              "quotes_rejected": len(rejected),
              "rejected": [flat(q.get("quote"), 140) for q in rejected],
              "draft_path": str(path), "materials_readable": len(stacks),
              "missing_required_sections": [heading for key, heading, _hint in OUTLINE
                                            if not any(heading_matches(h, key) for h in heads)],
              "ok": not rejected and bool(sections)}
    if not sections:
        report["note"] = "无草稿：build 将按材料兜底组装（partial）"
    save_json(Path(ctx["work"]) / "check.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=1))


def cmd_build(ctx, args):
    """Write partial result first, then the manuscript and the full result."""
    state, out = ctx["state"], Path(ctx["output"])
    save_json(out / "result.json", compose(ctx, "partial", None, {}))
    materials = collect(ctx["input"], state)
    pool = split_sentences(materials)
    stacks = bodies(materials)
    facts = [{"fact_id": "F%02d" % number, "value_text": flat(item["quote"], 240),
              "source_id": item["source_id"], "locator": item["locator"]}
             for number, item in enumerate([s for s in pool if DIGITS.search(s["quote"])],
                                           1)][:30]
    draft_path = Path(args.draft) if args.draft else Path(ctx["work"]) / "draft.json"
    sections = draft_sections(read_draft(draft_path))
    blocks, changes, rejected = merge(sections, pool, stacks)
    for item in rejected:
        state["rejected"].append(item)
        state["pending_human"].append({"reason": "引文未在材料中逐字出现",
                                       "item": item["locator"] or "draft quote",
                                       "action": "改为逐字引用或删去该句引文"})
    evidence = [{"claim_id": "C%03d" % (number + 1), "section": flat(heading, 80),
                 "quote": item["quote"], "source_id": item["source_id"],
                 "locator": item["locator"], "verified": True}
                for number, (heading, item) in enumerate([(block["heading"], item)
                                                          for block in blocks
                                                          for item in block["items"]])][:150]
    wanted = [word for word in WORDS if word in state["instruction"]]
    covered = [word for word in wanted if any(word in b["heading"] for b in blocks)]
    for word in [w for w in wanted if w not in covered]:
        state["pending_human"].append({"item": "章节：" + word,
                                       "reason": "任务指令点名，但稿件无对应章节",
                                       "action": "按材料补写，或向作者确认可省"})
    status = ("input_error" if not materials and not Path(ctx["input"]).is_dir() else
              "insufficient_evidence" if not sections and not evidence else
              "ok" if sections and not rejected and len(evidence) >= 5 else "partial")
    text, stats, body = render(title_of(state["case"]), blocks, state, status, bool(sections),
                               len(materials),
                               sum(1 for item in materials if item["readable"]))
    (out / "manuscript.md").write_text(text, encoding="utf-8")
    stats.update({"facts": len(facts), "requested_sections": wanted, "covered_sections": covered,
                  "missing_sections": [w for w in wanted if w not in covered],
                  "number_audit": audit(body, facts, evidence)})
    changes = changes[:59] + [{"action": "finalize", "status": status, "sections": len(blocks),
                               "evidence": len(evidence), "deliverable": "manuscript.md"}]
    state["change_log"], state["evidence_map"] = changes, evidence
    extras = {"preserved_facts": facts, "evidence_map": evidence, "change_log": changes,
              "coverage": stats, "draft_used": bool(sections),
              "sources": [dict((key, item.get(key)) for key in
                               ("id", "path", "kind", "bytes", "chars", "readable", "note"))
                          for item in materials]}
    save_json(out / "result.json", compose(ctx, status, "manuscript.md", extras))
    for name, payload in (("evidence_map.json", evidence), ("preserved_facts.json", facts),
                          ("change_log.json", changes),
                          ("pending_human.json", state["pending_human"])):
        save_json(out / name, payload)
    (out / "consistency_report.md").write_text(report_md(stats, state), encoding="utf-8")
    print("built %s | status=%s | sections=%d / evidence=%d / h2=%d / chars=%d"
          % (out / "manuscript.md", status, len(blocks), len(evidence),
             stats["h2_headings"], stats["chars"]))


def recover(ctx, error):
    state = ctx["state"]
    state["errors"].append("fatal:" + type(error).__name__)
    target = Path(ctx["output"])
    save_json(target / "result.json", compose(ctx, "input_error", None, {}))
    placeholder = ("# 学术写作产物\n\n## 摘要\n\n运行异常降级：%s，详见 result.json。\n\n"
                   "## 参考文献\n\n材料未提供。\n" % type(error).__name__)
    try:
        (target / "manuscript.md").write_text(placeholder, encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------- entry point
def main(argv=None):
    try:
        args = parse_cli(argv)
    except SystemExit:
        return 0
    ctx = None  # prepare() fills this in; a bad case leaves it empty
    try:
        ctx = prepare(args)
        {"init": cmd_init, "show": cmd_show, "check": cmd_check,
         "build": cmd_build}[args.cmd](ctx, args)
    except SystemExit:
        return 0
    except BaseException as error:
        if ctx:
            try:
                recover(ctx, error)
            except Exception:
                pass
        sys.stderr.write("downgraded %s, exit 0\n" % type(error).__name__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
