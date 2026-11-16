#!/usr/bin/env python3
"""Command layer for the reading-bench forge skill: init | show | check | build.

The verbs are safe to re-run and the process exit code is always 0; problems are
recorded in result.json rather than signalled. The work itself lives in reading_core.py.
"""
import argparse, os, sys, time, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reading_core as C

try:  # the v1.1.0 finalize-time asset layer; missing modules fall back to v1.0.0
    import bench_assets as ASSETS
except Exception:  # pragma: no cover - defensive import guard
    ASSETS = None

EVENTS = []


def note(stage, **kv):
    """Record one real build event for run.log (timestamps live only there)."""
    row = {"stage": stage, "t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "elapsed": round(time.time() - C.T_START, 3)}
    row.update({k: v for k, v in kv.items() if v is not None})
    EVENTS.append(row)


def finalize_result(doc, stage):
    """Put the contract echo on top of the envelope, then persist result.json."""
    scoring_blk = doc.get("scoring") or {}
    if doc.get("contract_echo"):
        doc.update(C.fulfill_contract(doc["contract_echo"], dict(
            case_id=doc.get("case_id"), state=doc.get("status"), sources=doc.get("sources"), items=doc.get("benchmark"),
            scoring=scoring_blk, anchors=doc.get("anchors"), stats=scoring_blk.get("aggregate"), outputs=doc.get("outputs"),
            report=(doc.get("outputs") or {}).get("report"),
            uncertainty=doc.get("uncertainty"), changes=doc.get("changes"),
            result={"report": (doc.get("outputs") or {}).get("report"), "benchmark": doc.get("benchmark"),
                    "anchors": doc.get("anchors"), "scoring": scoring_blk.get("aggregate")},
            claims=doc.get("anchors"), uncertainties=doc.get("uncertainty"),
            preserved_facts=doc.get("anchors"), evidence_map=doc.get("anchors"))))
    C.persist_result(doc, stage)


def grade_items(items):
    """Grade every rubric point 0/1/2 from verified anchor coverage (deterministic)."""
    out = []
    for item in items:
        ats, points = C.extract_terms(" ".join(item["reference_answer"])), []
        for rp in item["rubric"]:
            c = [(C.term_coverage(rp["key_terms"] or ats, e["quote"]), e) for e in item["evidence"]
                 if e.get("_v", {}).get("verified")]
            if not c:
                points.append({"rubric_id": rp["id"], "score": 0, "basis": "no verified quote in material"})
                continue
            x, ev = max(c, key=lambda z: z[0])
            s = 2 if x >= 0.6 else (1 if x > 0 else 0)
            points.append({"rubric_id": rp["id"], "score": s, "locator": ev["locator"], "coverage": x,
                        "basis": "%s (cov %.2f @ %s)" % ({2: "judgeable", 1: "review",
                                                          0: "no key term"}[s], x, ev["locator"] or "-")})
        tot = sum(p["score"] * next((r["weight"] for r in item["rubric"] if r["id"] == p["rubric_id"]), 0) for p in points)
        out.append({"id": item["id"], "type": item["type"], "difficulty": item["difficulty"], "points": points,
                    "score": round(tot, 3),
                    "judgeable": all(p["score"] >= 1 for p in points),
                    "fully_judgeable": all(p["score"] == 2 for p in points)})
    return out


def minimal_items(index, limit=6):
    """Deterministic fallback items built from paragraphs that really exist."""
    built = []
    for mat in index.get("materials", []):
        for par in mat.get("paragraphs", []):
            if len(built) >= limit:
                return built
            t = par["text"]
            if len(t) < 100:
                continue
            sents = [x for x in C.re.split(r"(?<=[。！？.!?])\s*", t) if x.strip()] or [t]
            nums = C.re.findall(r"\d+(?:[.,]\d+)?\s?(?:%|mg|g|mL|L|µM|mM|nM|nm|mm|h|min|s|°C|K)", t)
            s = next((x for x in sents if nums[0] in x), t)[:300] if nums else sents[0].strip()[:240]
            q = ("%s 的第 %s 段里出现了带单位的量值 %s；请摘出该句原文并给出 locator。"
                 % (mat["name"], par["pid"], nums[0])) if nums \
                else ("把 %s 中 %s 段的首句逐字摘下来，并注明 material 与 locator。"
                      % (mat["name"], par["pid"]))
            built.append({"id": "Q%02d" % (len(built) + 1), "type": "numeric" if nums else "extraction",
                          "difficulty": "easy", "question": q,
                          "rubric": [{"id": "R1", "text": "原文逐字一致，且 locator 正确", "weight": 1.0,
                                      "key_terms": C.extract_terms(s, 4)}],
                          "reference_answer": [s] + ([nums[0]] if nums else []),
                          "evidence": [{"material": mat["mid"], "locator": par["pid"], "quote": s}]})
    return built


def synthetic_candidates(ip, pack):
    """List candidate/checker artefacts shipped with a case, for the synthetic label."""
    n = ["case.json:candidate"] if C.deep_find(pack, ("candidate_output", "candidate_answer",
                                                 "baseline_output", "model_output", "checker_log")) else []
    return (n + [p.name for p in sorted(Path(ip).rglob("*")) if p.is_file()
                 and C.re.search(r"(candidate|baseline|response|checker|model_out)", p.name.lower())])[:5]


def render_report(reading_core, anchor_rows, scoring_blk, index, origin, rejected, issues, case_key):
    """Compose the human-readable audit report from already computed parts."""
    totals, tc = scoring_blk["aggregate"], {}
    for item in reading_core["items"]:
        tc[item["type"]] = tc.get(item["type"], 0) + 1
    mats = "\n".join(
        "- `%s` %s (kind=%s, paragraphs=%d, chars=%d, %s)"
        % (mat["mid"], mat["name"], mat["kind"], len(mat.get("paragraphs", [])), mat["chars"], mat["status"])
        for mat in index.get("materials", [])) or "- none"
    items = "\n".join(
        "| %s | %s | %s | %d | `%s` | %s |"
        % (item["id"], item["type"], item["question"][:38].replace("\n", " "), len(item["rubric"]),
           item["evidence"][0]["locator"] if item["evidence"] else "-", scoring_blk["items"][i]["score"])
        for i, item in enumerate(reading_core["items"])) or "| - | - | no items | 0 | - | - |"
    gaps = "\n".join(["- " + x for x in scoring_blk.get("pending_human", [])[:10]]
                     or ["- none: every rubric point carries a verified anchor"])
    if rejected:
        gaps += "\n" + "\n".join("- dropped `%s`: %s" % (x["id"], x["question"][:60]) for x in rejected)
    if issues:
        gaps += "\n- plus %d audit findings in work/check_report.json" % len(issues)
    return "\n".join([
        "# Reading benchmark self-audit report\n",
        "- case_id: `%s` | generated %s | origin **%s** | items %d / rubric points %d / anchors %d\n"
        % (case_key, C.stamp(), origin, len(reading_core["items"]), totals["n_points"], len(anchor_rows)),
        "> Built from the live input; the package ships no canned answers. `scoring.json` checks "
        "judgeability only - not an answer score, not a DSH score.\n",
        "## 1. Materials\n", mats,
        "\n## 2. Items, rubric points and anchors\n",
        "by type: " + (", ".join("%s=%d" % kv for kv in sorted(tc.items())) or "-"),
        "", "| item | type | prompt (truncated) | points | locator | self-check /2 |",
        "|---|---|---|---|---|---|", items,
        "\n## 3. Scale and totals\n",
        "Point scale 0/1/2: 2 = verbatim anchor found and it covers the answer key terms; "
        "1 = anchor found but coverage is thin, human review needed; 0 = no usable anchor. "
        "Item score = sum(weight x point), max 2; basis and locator are in `scoring.json`.",
        "- mean %.3f/2 | points at 2: %d/%d (%.1f%%) | judgeable %.1f%% | anchors verified %d/%d"
        % (totals["mean_score"], totals["n2"], totals["n_points"], 100 * totals["rate2"],
           100 * totals["judgeable_rate"], totals["n_anchors_verified"], totals["n_anchors"]),
        "\n## 4. Gaps and reproduction\n", gaps, "",
        "Reproduce: `init` -> author `work/questions.draft.json` -> `check` -> `build`; a new case "
        "only swaps the input tree (fields: `references/question-spec.md`).",
        "Limit: the self-check scores judgeability, not answer quality; quote lookup is whitespace/"
        "case based, so paraphrases and translations never count."]) + "\n"


def resolve_draft(explicit=None):
    for p in ([Path(explicit)] if explicit else []) + [C.WORK_DIR / "questions.draft.json",
                                                       C.WORK_DIR / "questions.json", C.OUT_DIR / "questions.draft.json"]:
        if p.is_file():
            try:
                return p, C.read_json(p), None
            except Exception as e:
                return p, None, "draft %s does not parse as JSON: %s" % (p, e)
    return None, None, "no draft found at " + str(C.WORK_DIR / "questions.draft.json")


def op_index(a):
    pack, case_path = C.read_case_pack(C.IN_DIR)
    doc, contract = C.bootstrap("init", pack)
    print("== %s %s | init ==\nroot in: %s\nroot out: %s\ncase file: %s" % (C.TITLE, C.VER, C.IN_DIR, C.OUT_DIR, case_path))
    if "_bad_json" in pack:
        doc["errors"].append({"stage": "case", "error": "case.json invalid: " + pack["_bad_json"]})
        print("! case.json is bad JSON -> continuing in partial mode")
    print("declared contract fields (%d): %s" % (len(C.contract_field_names(contract)), ", ".join(C.contract_field_names(contract)) or "NONE FOUND"))
    index = C.index_input(C.IN_DIR)
    C.write_json(C.WORK_DIR / "index.json", index)
    for mat in index["materials"]:
        print("  %-4s %-28s %-5s paras=%-3d chars=%-6d %s%s"
              % (mat["mid"], mat["name"][:28], mat["kind"], len(mat["paragraphs"]), mat["chars"], mat["status"],
                 ("  ! " + mat["note"]) if mat["note"] else ""))
    print("MATERIAL_COUNT %d" % len(index["materials"]))
    doc.update({"errors": doc["errors"] + index["errors"], "degradations": index["degradations"],
                "sources": C.source_records(index), "benchmark": {"stage": "indexed", "materials": len(index["materials"]),
                              "paragraphs": index["n_paragraphs"], "items": 0},
                "uncertainty": ["题集尚未编写；请写出 %s" % (C.WORK_DIR / "questions.draft.json")]})
    finalize_result(doc, "init")
    print("NEXT: run_build.py show --material %s --start 1, then check, then build"
          % (index["materials"][0]["mid"] if index["materials"] else "M01"))


def op_read(a):
    doc, _ = C.bootstrap("show", C.read_case_pack(C.IN_DIR)[0])
    index = C.load_or_index(doc)
    mat_map = {mat["mid"]: mat for mat in index.get("materials", [])}
    key = a.material if a.material in mat_map else next((k for k in mat_map if (a.material or "").lower() == k.lower()), None)
    if not key:
        for mat in index.get("materials", []):
            print("%-4s %-30s %-5s paras=%d chars=%d %s"
                  % (mat["mid"], mat["name"][:30], mat["kind"], len(mat["paragraphs"]), mat["chars"], mat["status"]))
        if a.material:
            print("! material %s is not in the index" % a.material)
            doc["errors"].append({"stage": "show", "error": "material %s not found" % a.material})
    else:
        mat, begin = mat_map[key], max(1, a.start)
        end = begin + max(1, a.limit)
        print("MATERIAL %s | %s | %s | paragraphs=%d\n" % (mat["mid"], mat["name"], mat["kind"], len(mat["paragraphs"])))
        for p in mat["paragraphs"][begin - 1:end - 1]:
            print("[%s%s] (%d chars)\n%s\n" % (p["pid"], (" p.%d" % p["page"]) if p.get("page") else "",
                                              len(p["text"]), p["text"][:1200]))
        if end - 1 < len(mat["paragraphs"]):
            print("... continue with --start %d" % end)
    C.persist_result(doc, "show")


def op_audit(a):
    doc, _ = C.bootstrap("check", C.read_case_pack(C.IN_DIR)[0])
    c = C.build_corpus(C.load_or_index(doc))
    path, draft, problem = resolve_draft(a.draft)
    print("== draft audit ==")
    if problem:
        print("! %s\n  next: write work/questions.draft.json (fields in references/question-spec.md), then re-run" % problem)
        C.write_json(C.WORK_DIR / "check_report.json", {"ok": False, "issues": [{"level": "error", "msg": problem}], "n_items": 0})
        doc.update({"errors": [{"stage": "check", "error": problem}],
                    "pending_human": ["write work/questions.draft.json first, then run check/build"]})
        C.persist_result(doc, "check")
        return
    audit = C.audit_items(draft, c)
    audit.update(draft_path=str(path), n_items=len(audit["items"]))
    C.write_json(C.WORK_DIR / "check_report.json", audit)
    print("draft %s | declared=%d accepted=%d rejected=%d"
          % (path.name, audit["n_raw"], len(audit["items"]), len(audit["rejected"])))
    for x in audit["issues"]:
        print("  FAIL  %-5s %s" % (x.get("item", "-"), x["msg"]))
    for w in audit["warnings"][:20]:
        print("  NOTE  %-5s %s" % (w.get("item", "-"), w["msg"]))
    print("RESULT: %s" % ("PASS" if audit["ok"] else "FAIL (build will fill the gaps itself)"))
    doc["errors"] = [{"stage": "check", "item": x.get("item"), "error": x["msg"]} for x in audit["issues"]]
    doc["pending_human"] = ["resolve %d audit finding(s), then rebuild" % len(audit["issues"])] if audit["issues"] else []
    finalize_result(doc, "check")


def op_build(a):
    pack, case_path = C.read_case_pack(C.IN_DIR)
    doc, contract = C.bootstrap("build", pack)
    case_key = str(C.deep_find(pack, C.ID_KEYS) or "") or None
    note("build_start", case_id=case_key, input=str(C.IN_DIR), output=str(C.OUT_DIR))
    index = C.load_or_index(doc)
    note("index_loaded", materials=len(index.get("materials") or []), paragraphs=index.get("n_paragraphs"))
    c = C.build_corpus(index)
    if "_bad_json" in pack:
        doc["errors"].append({"stage": "case", "error": "case.json invalid: " + pack["_bad_json"]})
    path, draft, problem = resolve_draft(a.draft)
    items, rejected, issues, origin = [], [], [], "agent_authored"
    if problem:
        print("! %s -> adding items generated from real paragraphs" % problem)
        doc["degradations"].append({"item": "draft", "issue": problem, "action": "fallback_generated_items"})
    else:
        audit = C.audit_items(draft, c)
        items, rejected, issues = audit["items"], audit["rejected"], audit["issues"]
        print("draft %s | accepted=%d rejected=%d problems=%d"% (path.name, len(items), len(rejected), len(issues)))
    note("draft_audit", mode=origin, accepted=len(items), rejected=len(rejected), problems=len(issues))
    if not items or rejected:
        origin = "fallback_minimal" if not items else "agent_authored_with_fallback"
        for raw in minimal_items(index, 6 if not items else 2):
            item, _ = C.coerce_item(raw, len(items) + 1)
            ev = item["evidence"][0]
            ev["_v"] = C.locate_quote(c, ev["material"], ev["quote"])
            items.append(item)
        doc["degradations"].append({"item": "benchmark", "issue": "no usable draft" if not items else "rejected items",
                                    "action": "added deterministic minimal items from real paragraphs"})
    for item in items:
        for ev in item["evidence"]:
            ev["_v"] = ev.get("_v") or C.locate_quote(c, ev["material"], ev["quote"])
    anchor_rows = [{"item_id": item["id"], "material": ev["material"], "locator": ev["locator"] or ev["_v"].get("pid"),
             "quote": ev["quote"], "verified": bool(ev["_v"].get("verified")), "match": ev["_v"].get("match")}
            for item in items for ev in item["evidence"]]
    C.write_json(C.OUT_DIR / "anchors.json", {"schema": "reading-bench-forge/anchors@1", "case_id": case_key, "generated_at": C.stamp(),
                                     "quote_policy": "verbatim quotes only; lookup normalises whitespace", "anchors": anchor_rows})
    C.write_json(C.OUT_DIR / "benchmark.json", {
        "schema": "reading-bench-forge/benchmark@1", "case_id": case_key, "generated_at": C.stamp(), "mode": origin,
        "n_items": len(items), "instruction": "按 rubric 点逐条打 0/1/2；每条引用都要落在 anchors.json 中的 locator 上。",
        "items": [dict(item, evidence=[{k: e[k] for k in ("material", "locator", "quote")} for e in item["evidence"]])
                  for item in items],
        "rejected": [{"id": x["id"], "question": x["question"], "reason": "no verbatim-verified evidence"}
                     for x in rejected]})

    sc_items = grade_items(items)
    points = [p for s in sc_items for p in s["points"]]
    n2, n1, n0 = (sum(p["score"] == k for p in points) for k in (2, 1, 0))
    totals = {"n_items": len(sc_items), "n_points": len(points), "n2": n2, "n1": n1, "n0": n0,
           "rate2": round(n2 / len(points), 3) if points else 0.0,
           "judgeable_rate": round((n2 + n1) / len(points), 3) if points else 0.0,
           "mean_score": round(sum(s["score"] for s in sc_items) / len(sc_items), 3) if sc_items else 0.0,
           "n_anchors": len(anchor_rows), "n_anchors_verified": sum(x["verified"] for x in anchor_rows)}
    human_queue = ["%s/%s score=%d: %s" % (s["id"], p["rubric_id"], p["score"], p["basis"])
            for s in sc_items for p in s["points"] if p["score"] < 2]
    human_queue += ["%s rejected: no verified anchor" % x["id"] for x in rejected]
    C.write_json(C.OUT_DIR / "scoring.json", {
        "schema": "reading-bench-forge/scoring@1", "case_id": case_key, "generated_at": C.stamp(),
        "scale": {"2": "verbatim anchor verified and covers the answer key terms",
                  "1": "anchor verified but coverage<0.6 -> a human should review", "0": "no usable anchor"},
        "disclaimer": "这是题集可判性自检分，不是被评测 Agent 的答题分，也不是 DSH 分数",
        "items": sc_items, "aggregate": totals, "pending_human": human_queue})
    synthetic_hits = synthetic_candidates(C.IN_DIR, pack)
    if synthetic_hits:
        doc["technical_synthetic"] = {"present": True, "not_a_dsh_score": True, "sources": synthetic_hits, "scored": False,
                                      "note": "checker/合成数据只登记，不参与评分，也不代表 DSH 分数"}
    (C.OUT_DIR / "report.md").write_text(
        render_report({"items": items}, anchor_rows, {"items": sc_items, "aggregate": totals, "pending_human": human_queue},
               index, origin, rejected, issues, case_key), encoding="utf-8")

    state = ("input_error" if not index.get("materials") else
              "insufficient_evidence" if not index.get("n_paragraphs") or not items else
              "ok" if origin == "agent_authored" and not issues else "partial")
    doc.update({"status": state, "pending_human": human_queue[:20],
                "outputs": dict({f.split(".")[0]: str(C.OUT_DIR / f) for f in
                                 ("benchmark.json", "anchors.json", "scoring.json", "report.md", "result.json")},
                                index=str(C.WORK_DIR / "index.json"), draft=str(path) if path else None),
                "benchmark": {"mode": origin, "n_items": len(items), "n_rubric_points": len(points),
                              "n_rejected": len(rejected), "scores": {s["id"]: s["score"] for s in sc_items}},
                "anchors": {"n_anchors": len(anchor_rows), "verified": totals["n_anchors_verified"]},
                "scoring": {"aggregate": totals},
                "sources": C.source_records(index), "changes": [{"what": "benchmark assembled from the live input", "mode": origin,
                             "why": "authored items win; the deterministic fallback only keeps the package non-empty"},
                            {"what": "scoring restricted to the anchor audit",
                             "why": "no invented model scores; checker logs are registered but never scored"}]})
    doc["errors"] = doc.get("errors", []) + issues[:20]
    doc["degradations"] = doc.get("degradations", []) + (index.get("degradations") or [])
    open_questions = [u for u in (doc.get("uncertainty") or []) if "not authored yet" not in u]
    open_questions += ["兜底题只覆盖摘录与数值两类，不包含推理题"] if origin != "agent_authored" and items else []
    open_questions += ["%d 个评分点没有可用锚点，需要人工补证据" % n0] if n0 else []
    degraded_ids = [mat["mid"] for mat in index["materials"] if mat["note"]]
    open_questions += ["材料解析降级: %s（引文需用平台解析器再核对一遍）" % ", ".join(degraded_ids)] if degraded_ids else []
    open_questions += ["输入目录下没有发现可用材料"] if not index.get("materials") else []
    doc["uncertainty"] = open_questions
    doc["runtime"].update({"materials": len(index["materials"]), "paragraphs": index["n_paragraphs"],
                           "n_items": len(items), "mode": origin})
    note("products_ready", cards=len(items), anchors=len(anchor_rows), points=len(points),
         n2=totals["n2"], n1=totals["n1"], n0=totals["n0"])
    finalize_result(doc, "build")
    passed = self_audit(doc, index, anchor_rows, items, sc_items, totals, points, contract)
    note("self_audit", passed=self_passed(doc), total=self_total(doc), ok=bool(passed))
    asset_keys = None
    if ASSETS is not None:
        raw_case = C.read_text(case_path)[0] if case_path else ""
        ctx = {"out_dir": str(C.OUT_DIR), "work_dir": str(C.WORK_DIR), "in_dir": str(C.IN_DIR),
               "pkg_root": str(Path(__file__).resolve().parent.parent), "case_path": str(case_path) if case_path else None,
               "raw_case": raw_case, "pack": pack, "contract": contract, "index": index,
               "events": EVENTS, "doc": doc, "t_start": C.T_START, "skill_version": C.VER,
               "case_id": case_key, "state": state, "origin": origin,
               "draft_path": str(path) if path else None, "rejected": rejected, "issues": issues}
        try:
            emitted = ASSETS.emit(C.OUT_DIR, ctx)
            if emitted:
                asset_keys = emitted.get("result_keys") or {}
                doc.update(asset_keys)
                facts = emitted.get("facts") or {}
                note("finalize_assets", assets=len([k for k in facts if k in
                                                   ("golden", "diff", "version", "log", "self")]),
                     self_check_ok=(facts.get("self") or {}).get("ok"))
        except Exception as e:  # never break the five primary products for an asset problem
            print("! asset layer failed: %s" % e)
            traceback.print_exc(limit=3)
            doc["degradations"].append({"item": "assets", "issue": str(e)[:300],
                                        "action": "kept the v1.0.0 five-product path, exit code still 0"})
    else:
        doc["degradations"].append({"item": "assets", "issue": "asset modules not importable",
                                    "action": "kept the v1.0.0 five-product path"})
        note("assets_unavailable")
    finalize_result(doc, "build")
    print("mode=%s items=%d points=%d anchors=%d verified=%d | status=%s"
          % (origin, len(items), len(points), len(anchor_rows), totals["n_anchors_verified"], state))
    print("wrote benchmark.json anchors.json scoring.json report.md result.json | SELF-AUDIT %s"
          % ("PASS" if passed else "ATTENTION"))
    if asset_keys:
        gs = asset_keys.get("golden_standard") or {}
        sc = asset_keys.get("self_check") or {}
        print("[assets] golden items=%s met=%s deviation=%s missing=%s quotes=%s | 5 assets written | "
              "SELF-CHECK %s (%s/%s)"
              % (gs.get("items"), gs.get("met"), gs.get("deviation"), gs.get("missing"), gs.get("quotes"),
                 "PASS" if sc.get("ok") else "ATTENTION", sc.get("checks_passed"), sc.get("checks_total")))


def self_passed(doc):
    return (doc.get("runtime") or {}).get("self_audit", {}).get("passed", 0)


def self_total(doc):
    return (doc.get("runtime") or {}).get("self_audit", {}).get("total", 0)


def _path_flags():
    """Shared --input/--output/--work options for every verb."""
    box = argparse.ArgumentParser(add_help=False)
    box.add_argument("--input", default=None, help="override the input root (default: /input)")
    box.add_argument("--output", default=None, help="override the output root (default: /app/output)")
    box.add_argument("--work", default=None, help="override the work root (default: /app/work)")
    return box


def self_audit(doc, index, anchor_rows, items, sc_items, totals, points, contract):
    """Cheap structural assertions over what was just written (added safeguard).

    Deterministic, no I/O: they only compare in-memory structures that are about to
    be persisted, and the verdict is echoed into result.json and stdout.
    """
    pids = {}
    for mat in index.get("materials", []):
        for par in mat.get("paragraphs", []):
            pids.setdefault(mat["mid"], set()).add(par["pid"])
    checks = [
        ("point_counts_add_up", totals["n2"] + totals["n1"] + totals["n0"] == len(points)),
        ("anchor_locators_resolve",
         all((not x["verified"]) or (not x["locator"]) or x["locator"] in pids.get(x["material"], set())
             for x in anchor_rows)),
        ("scoring_ids_match_benchmark", {s["id"] for s in sc_items} == {item["id"] for item in items}),
        ("scored_points_have_locator",
         all(p.get("locator") for s in sc_items for p in s["points"] if p["score"] >= 1)),
        ("contract_keys_on_top", all(k in doc for k in C.contract_field_names(contract))),
        ("aggregate_recomputable",
         abs(totals["mean_score"] - (round(sum(s["score"] for s in sc_items) / len(sc_items), 3) if sc_items else 0.0)) <= 0.002),
    ]
    bad = [name for name, good in checks if not good]
    doc["runtime"]["self_audit"] = {"ok": not bad, "passed": len(checks) - len(bad), "total": len(checks),
                                    "failed": bad, "checks": [n for n, _ in checks]}
    print("SELF-AUDIT %d/%d %s" % (len(checks) - len(bad), len(checks), "PASS" if not bad else "ATTENTION " + ",".join(bad)))
    return not bad


def run_cli(argv=None):
    flags = _path_flags()
    ap = argparse.ArgumentParser(prog="run_build.py",
                                 description="Author a reading benchmark from live materials (init/show/check/build).")
    sp = ap.add_subparsers(dest="cmd")
    sp.add_parser("init", parents=[flags], help="scan the input tree, write the index and a partial result.json")
    p = sp.add_parser("show", parents=[flags], help="print one material paragraph by paragraph, locators included")
    p.add_argument("--material"), p.add_argument("--start", type=int, default=1)
    p.add_argument("--limit", type=int, default=10)
    sp.add_parser("check", parents=[flags], help="audit a hand-written draft: fields, rubric, quotes, locators").add_argument("--draft")
    sp.add_parser("build", parents=[flags], help="write the five deliverables and finalise result.json").add_argument("--draft")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 0
    C.retarget(getattr(a, "input", None), getattr(a, "output", None), getattr(a, "work", None))
    try:
        {"init": op_index, "show": op_read, "check": op_audit, "build": op_build}[a.cmd](a)
    except Exception as e:
        print("! handled failure during %s: %s\n%s" % (a.cmd, e, traceback.format_exc(limit=3)))
        try:
            doc, _ = C.bootstrap(a.cmd + "/error", C.read_case_pack(C.IN_DIR)[0])
            doc["errors"].append({"stage": a.cmd, "error": str(e), "traceback": traceback.format_exc(limit=3)[-900:]})
            doc["pending_human"] = ["inspect the error, then re-run %s" % a.cmd]
            doc["degradations"] = [{"item": "run", "issue": str(e), "action": "wrote a legal partial result"}]
            finalize_result(doc, a.cmd + "/error")
            print("partial result.json persisted")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run_cli())
    except SystemExit:
        sys.exit(0)
    except Exception:
        sys.exit(0)
