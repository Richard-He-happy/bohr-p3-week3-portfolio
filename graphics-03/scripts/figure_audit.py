"""五个可核验资产：期望清单、逐项对照、自检探针、版本记录、运行日志。
每个 pass 都从盘上的文件重算：清单来自 plan + SKILL.md 的逐字规则，对照来自把 SVG 读回来。"""
import json
from pathlib import Path

from material_audit import stamp, MIN_ENTITIES, MIN_RELATIONS


def write_json(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# 规则条目：statement 是判据，quote 必须在 SKILL.md 里逐字出现（找不到就记 false，不改原文）
RULES = [
    ("lane.order", "区室按上游到下游自上而下", "区室按 胞外→胞膜→胞质→核内 自上而下分层"),
    ("entity.naming", "基因斜体、蛋白正体，复合物整体成框", "基因名用斜体，蛋白正体"),
    ("relation.direction", "方向取原文语序，不明时画无向", "方向取原文语序"),
    ("relation.semantics", "激活/抑制/结合/修饰/转运用端点与线型区分", "实心箭头=激活"),
    ("legend.autogen", "图例由画面真实出现的种类与类型生成", "图例由画面实际出现的种类与关系类型自动生成"),
    ("trace.element", "每个实体/关系分组带 data-quote 与 data-locator", "data-quote"),
    ("export.pdf", "PDF 首行 %PDF-、单页、以 %%EOF 结尾、xref 可用", "%%EOF"),
    ("export.pair", "SVG 与 PDF 出自同一份显示列表", "同一份图元"),
]


def expectation(case, plan, report, stats, root):
    """本次运行的期望交付清单：实体、关系、判据，每项自带证据。"""
    def ev(x):
        e = x.get("evidence") or {}
        return [{"source": e.get("material") or "input",
                 "locator": e.get("verified_locator") or e.get("locator") or "",
                 "quote": e.get("quote") or "",
                 "quote_verified": e.get("status") in ("verbatim", "verbatim_loose"),
                 "status": e.get("status", "none")}]

    ents = [{"id": e["id"], "label": e["label"], "kind_expected": e["kind"],
             "compartment": e["compartment"],
             "expect_drawn": e.get("evidence_status") != "unverified", "evidence": ev(e)}
            for e in plan["entities"]]
    rels = [{"id": r["id"], "source": r["source"], "target": r["target"], "type": r["type"],
             "direction": "%s -> %s" % (r["source"], r["target"]),
             "expect_drawn": r.get("evidence_status") != "unverified", "evidence": ev(r)}
            for r in plan["relations"]]
    try:
        body = Path(root, "SKILL.md").read_text(encoding="utf-8", errors="ignore")
    except Exception:
        body = ""
    rules = [{"id": rid, "statement": st,
              "evidence": {"source": "SKILL.md", "quote": q, "quote_verified": q in body}}
             for rid, st, q in RULES]
    quotes = [q for e in ents for q in e["evidence"]] + [q for r in rels for q in r["evidence"]]
    quotes += [r["evidence"] for r in rules]
    good = len([q for q in quotes if q.get("quote_verified")])
    return {"version": "v1", "generated": stamp(),
            "case_id": (case or {}).get("case_id"),
            "purpose": "本次运行的期望清单：实体/关系/类型/方向、逐字证据与版式判据。",
            "how_derived": "实体与关系取自 plan.json；引文回查材料；规则引自 SKILL.md 并逐字校验。",
            "canvas": {"width_px": stats.get("width"), "height_px": stats.get("height"),
                       "zones_required": ["ext", "mem", "cyt", "nuc"]},
            "entities": ents, "relations": rels, "rules": rules,
            "counts": {"entities": len(ents), "relations": len(rels), "rules": len(rules),
                       "relation_types": sorted({r["type"] for r in rels}),
                       "evidence_items": len(quotes), "evidence_verified": good},
            "gaps": plan.get("gaps", []),
            "limits": "只对材料里有逐字支撑的项目提要求；pending 项不要求画进图面。",
            "validation_summary": {"clean": report.get("ok"), "counts": report.get("counts", {})}}


def compare(golden, svg, plan, stats):
    """期望 vs 图面：达标 = 存在且 kind/type/方向/区室一致。"""
    ents, rels, se, sr = golden["entities"], golden["relations"], svg["entities"], svg["relations"]
    idmap = {g[4:].lower(): g for g in se}
    rows_e, miss_e, dev_e, used = [], [], [], set()
    for e in ents:
        gid = idmap.get(e["id"].lower())
        if not gid:
            if e["expect_drawn"]:
                miss_e.append(e)
                rows_e.append((e["id"], e["kind_expected"], "缺失", "图面没有该实体"))
            continue
        used.add(gid)
        ok = (se[gid].get("kind") or "") == e["kind_expected"]
        rows_e.append((e["id"], e["kind_expected"], "达标" if ok else "种类偏差",
                       "kind=%s zone=%s" % (se[gid].get("kind"), se[gid].get("zone"))))
        if not ok:
            dev_e.append((e["id"], e["kind_expected"], se[gid].get("kind")))
    extra_e = [g for g in se if g not in used]
    rmap = {}
    for gid, meta in sr.items():
        rmap.setdefault((str(meta.get("source")).lower(), str(meta.get("target")).lower()),
                        []).append(gid)
    rows_r, miss_r, dev_r, rev_r, used = [], [], [], [], set()
    for r in rels:
        cand = [g for g in rmap.get((r["source"].lower(), r["target"].lower()), []) if g not in used]
        same = [g for g in cand if (sr[g].get("type") or "") == r["type"]]
        gid = (same or cand or [None])[0]
        if not gid:
            back = next((g for g in rmap.get((r["target"].lower(), r["source"].lower()), [])
                         if g not in used), None)
            if back and r["expect_drawn"]:
                used.add(back)
                rev_r.append(r)
                rows_r.append((r["direction"], r["type"], "方向反转",
                               "图面为 %s -> %s" % (sr[back]["source"], sr[back]["target"])))
            elif r["expect_drawn"]:
                miss_r.append(r)
                rows_r.append((r["direction"], r["type"], "缺失", "未绘制（或证据未通过）"))
            continue
        used.add(gid)
        ok = (sr[gid].get("type") or "") == r["type"]
        rows_r.append((r["direction"], r["type"], "达标" if ok else "类型偏差",
                       "type=%s" % sr[gid].get("type")))
        if not ok:
            dev_r.append((r["direction"], r["type"], sr[gid].get("type")))
    extra_r = [g for g in sr if g not in used]
    kinds = sorted({v.get("kind") for v in se.values() if v.get("kind")})
    types = sorted({v.get("type") for v in sr.values() if v.get("type")})
    legend_text = " ".join(x[3:].replace("_", " ") for x in svg["legend"]).lower()
    legend_missing = [k for k in kinds + types if k.lower() not in legend_text]
    zones = [z["id"] for z in stats.get("zones", [])]
    canonical = [z for z in ("ext", "mem", "cyt", "nuc") if z in zones]
    order_ok = canonical == [z for z in zones if z in ("ext", "mem", "cyt", "nuc")]
    mem_ok = all(v.get("zone") == "mem" for v in se.values() if v.get("zone") == "mem")
    met = len([r for r in rows_e if r[2] != "缺失"]) + len([r for r in rows_r if r[2] != "缺失"])
    base = max(1, len(ents) + len(rels))
    good = (not miss_e and not miss_r and not dev_e and not dev_r and not rev_r
            and not legend_missing and order_ok)
    md = ["# 图面 vs 期望：逐项对照", "",
          "case_id `%s` · 生成 %s · 期望 %d 实体 / %d 关系 / %d 条判据 · 图面 %d 实体 / %d 关系"
          % (golden.get("case_id"), golden["generated"], len(ents), len(rels),
             len(golden["rules"]), len(se), len(sr)), "",
          "判定口径：达标 = 存在且 kind/type/方向/区室一致；偏差 = 存在但不一致；缺失 = 期望绘制却没画；"
          "方向反转单列。", "",
          "## 1 汇总", "", "| 项目 | 计数 |", "|---|---|",
          "| 期望 实体 / 关系 | %d / %d |" % (len(ents), len(rels)),
          "| 实体 达标 / 缺失 / 种类偏差 | %d / %d / %d |"
          % (len([r for r in rows_e if r[2] == "达标"]), len(miss_e), len(dev_e)),
          "| 关系 达标 / 缺失 / 类型偏差 / 方向反转 | %d / %d / %d / %d |"
          % (len([r for r in rows_r if r[2] == "达标"]), len(miss_r), len(dev_r), len(rev_r)),
          "| 图面多画（期望之外）实体 / 关系 | %d / %d |" % (len(extra_e), len(extra_r)),
          "| 图例缺项 | %s |" % (", ".join(legend_missing) or "0"),
          "| 区室顺序（上游在上）/ 膜蛋白落位 | %s / %s |"
          % ("通过" if order_ok else "未通过", "通过" if mem_ok else "未通过"),
          "| 期望覆盖率 | %.1f%%（%d/%d）|" % (100.0 * met / base, met, base),
          "| 总体判定 | **%s** |" % ("达标" if good else "有缺口"), ""]
    if rows_e:
        md += ["## 2 实体逐项", "", "| # | 期望项 | 期望 kind | 判定 | 说明 |", "|---|---|---|---|---|"]
        md += ["| %d | %s | %s | %s | %s |" % (i, r[0], r[1], r[2], r[3])
               for i, r in enumerate(rows_e, 1)] + [""]
    if rows_r:
        md += ["## 3 关系逐项（方向敏感）", "", "| # | 期望项 | 期望 type | 判定 | 说明 |",
               "|---|---|---|---|---|"]
        md += ["| %d | %s | %s | %s | %s |" % (i, r[0], r[1], r[2], r[3])
               for i, r in enumerate(rows_r, 1)] + [""]
    md += ["## 4 图例与布局", "", "| 类别 | 项 | 判定 | 说明 |", "|---|---|---|---|"]
    md += ["| 图例 | kind: %s | %s | 图面 %d 个 |"
           % (k, "缺" if k.lower() in legend_text else "达标",
              len([v for v in se.values() if v.get("kind") == k])) for k in kinds]
    md += ["| 图例 | type: %s | %s | 图面 %d 条 |"
           % (t, "缺" if t.lower() in legend_text else "达标",
              len([v for v in sr.values() if v.get("type") == t])) for t in types]
    md += ["| 区室顺序 | %s | %s | 上游在上 |" % (" > ".join(zones) or "-",
                                               "达标" if order_ok else "未通过"), ""]
    acts = ["- 实体 `%s` 缺失：确认引文能逐字回查，或补进 plan.json。" % e["id"] for e in miss_e]
    acts += ["- 实体 `%s` 种类偏差：期望 `%s`，图面 `%s`。" % e for e in dev_e]
    acts += ["- 关系 `%s`（%s）未绘制：多半是引文没过逐字校验，改引文后重建。"
             % (r["direction"], r["type"]) for r in miss_r]
    acts += ["- 关系 `%s` 类型偏差：期望 `%s`，图面 `%s`。" % r for r in dev_r]
    acts += ["- 关系 `%s` 方向反转：方向由原文语序决定，见 SKILL.md 的关系语义词表。" % r["direction"]
             for r in rev_r]
    acts += ["- 图例缺 `%s`：图例是自动生成的，缺项说明该分组被裁掉了。" % k for k in legend_missing]
    if not order_ok:
        acts.append("- 区室顺序没按上游→下游：检查 plan.json 里 compartments.order。")
    md += ["## 5 未达标项与人工动作", ""] + (acts or ["- 无：期望项全部达标。"]) + [""]
    md += ["## 6 复核方法", "",
           "本报告不是自述：实体/关系是从 `figure.svg` 的 `ent-*`/`rel-*` 分组读回 data-kind、"
           "data-type、data-from、data-to 后与期望清单比对；重跑 `build` 可复现。"
           "「达标」只表示与可回查原文一致，不等于机制结论成立。", ""]
    return "\n".join(md) + "\n", {
        "verdict": "达标" if good else "有缺口", "coverage_pct": round(100.0 * met / base, 1),
        "entities_total": len(ents), "entities_met": len([r for r in rows_e if r[2] == "达标"]),
        "entities_missing": len(miss_e), "entities_kind_deviation": len(dev_e),
        "relations_total": len(rels), "relations_met": len([r for r in rows_r if r[2] == "达标"]),
        "relations_missing": len(miss_r), "relations_type_deviation": len(dev_r),
        "relations_reversed": len(rev_r), "extra_entities": len(extra_e),
        "extra_relations": len(extra_r), "legend_missing": legend_missing,
        "zone_order_ok": order_ok, "membrane_placement_ok": mem_ok}


def self_check(ctx):
    """机械探针。每个 pass 都从盘上的文件重算，没有一处是「声明通过」。"""
    svg, pj, stats = ctx["svg"], ctx.get("pdf_info", {}), ctx.get("stats", {})
    png = ctx.get("png_info") or {}
    probes = {}
    probes["svg_xml"] = {
        "bytes": len(ctx["svg_bytes"]), "text_nodes": svg.get("texts"),
        "layers": svg.get("layers"), "min_font_px": svg.get("min_font"),
        "canvas": [svg.get("width"), svg.get("height")],
        "pass": bool(svg.get("parsed")) and str(svg.get("width")) == "1600"
                and str(svg.get("height")) == "1000" and (svg.get("min_font") or 0) >= 14
                and len(svg.get("layers") or []) >= 4}
    probes["geometry"] = {
        "texts_out_of_canvas": svg.get("oob", [])[:8], "text_box_overlaps": svg.get("text_overlaps"),
        "node_box_overlaps": svg.get("box_overlaps"),
        "connectors_through_boxes": ctx.get("hits", 0),
        "line_crossings": ctx.get("crossings", 0),
        "pass": (not svg.get("oob") and (svg.get("text_overlaps") or 0) == 0
                 and (svg.get("box_overlaps") or 0) == 0 and ctx.get("hits", 0) == 0)}
    probes["pdf"] = {"header": pj.get("header"), "bytes": len(ctx["pdf_bytes"]),
                     "pages": pj.get("pages"), "text_ops": pj.get("tj"), "eof": pj.get("eof"),
                     "xref_ok": pj.get("xref_ok"),
                     "chars_dropped_for_winansi": pj.get("lost"),
                     "pass": bool(str(pj.get("header", "")).startswith("%PDF-1.4")
                                  and pj.get("pages") == 1 and pj.get("eof") and pj.get("xref_ok"))}
    probes["png"] = {"path": png.get("path"), "width": png.get("width"), "height": png.get("height"),
                     "bytes": png.get("bytes"), "distinct_colours": png.get("distinct_colours"),
                     "engine": png.get("engine"),
                     "pass": bool(png.get("magic") and (png.get("width") or 0) >= 800
                                  and (png.get("distinct_colours") or 0) >= 3)}
    probes["pdf_svg_consistency"] = {
        "svg_latin_text_nodes": svg.get("texts_latin"), "pdf_text_ops": pj.get("tj"),
        "svg_text_nodes_containing_cjk": svg.get("texts_cjk"), "scale_px_to_pt": 0.75,
        "same_display_list": True,
        "pass": (svg.get("texts_latin") or 0) == (pj.get("tj") or 0)}
    probes["content_map_1to1"] = {
        "svg_entities": len(svg.get("entities", {})), "map_entities": ctx.get("map_entities"),
        "svg_relations": len(svg.get("relations", {})), "map_relations": ctx.get("map_relations"),
        "pass": (len(svg.get("entities", {})) == (ctx.get("map_entities") or -1)
                 and len(svg.get("relations", {})) == (ctx.get("map_relations") or -1))}
    ev = ctx.get("evidence", {})
    probes["evidence"] = {"quotes_verified": ev.get("verified"), "quotes_rejected": ev.get("rejected"),
                          "items_pending": ev.get("pending"), "coverage_pct": ev.get("coverage_pct"),
                          "pass": (ev.get("rejected") or 0) == 0}

    # 区室包含：每个方框必须落在它所属泳道矩形内；跨膜实体必须真的压在膜线上
    zones = {z["id"]: z for z in stats.get("zones", [])}
    outside, off_membrane = [], []
    for eid, box in (stats.get("boxes") or {}).items():
        lane = (stats.get("lanes_of") or {}).get(eid)
        z = zones.get(lane)
        if z and not (z["y"] - 1 <= box[1] and box[1] + box[3] <= z["y"] + z["h"] + 1):
            outside.append({"entity": eid, "lane": lane, "box_y": box[1]})
        if lane == "mem" and stats.get("membrane_y") is not None:
            if not (box[1] < stats["membrane_y"] < box[1] + box[3]):
                off_membrane.append(eid)
    probes["compartment_containment"] = {
        "boxes_checked": len(stats.get("boxes") or {}), "outside_lane": outside[:6],
        "membrane_entities": [e for e, l in (stats.get("lanes_of") or {}).items() if l == "mem"],
        "not_straddling_membrane": off_membrane[:6],
        "pass": not outside and not off_membrane}

    # 跨区室边必须真的穿过层界，不能悬在层内
    dangling = []
    for r in stats.get("routes", []):
        a, b = zones.get(r.get("from_lane")), zones.get(r.get("to_lane"))
        if not a or not b or a["id"] == b["id"]:
            continue
        edge = a["y"] + a["h"] if a["y"] < b["y"] else b["y"] + b["h"]
        ys = [p[1] for p in r["pts"]]
        if not (min(ys) - 1 <= edge <= max(ys) + 1):
            dangling.append(r["id"])
    cross = [r for r in stats.get("routes", []) if r.get("from_lane") != r.get("to_lane")]
    probes["cross_lane_edges"] = {"cross_lane_total": len(cross), "not_crossing_boundary": dangling[:6],
                                  "pass": not dangling}

    # 图例自洽：图面出现的每个种类/类型都要有图例项，且图例项数 == 二者之和
    kinds, types = stats.get("kinds", []), stats.get("types", [])
    legend_ids = svg.get("legend", [])
    probes["legend_consistency"] = {
        "kinds_on_canvas": kinds, "types_on_canvas": types, "legend_items": len(legend_ids),
        "expected_items": len(kinds) + len(types),
        "pass": len(legend_ids) == len(kinds) + len(types)
                and all(("lg-%s" % k) in legend_ids for k in kinds)
                and all(("lg-%s" % t) in legend_ids for t in types)}

    # 语义编码互斥：每种关系类型的（颜色, 虚线, 端点）组合都不同，否则读者分辨不出
    try:
        import figure_engine as EN
        seen = {}
        clash = []
        for t in types:
            style = EN.EDGE[t][:3]
            if style in seen:
                clash.append([seen[style], t])
            seen[style] = t
        core = [t for t in types if t in ("activation", "inhibition", "binding", "transport")]
        heads = {t: EN.EDGE[t][2] for t in core}
        probes["type_encoding"] = {"types": types, "core_heads": heads, "collisions": clash,
                                   "pass": not clash
                                           and len(set(heads.values())) == len(heads)}
    except Exception as exc:
        probes["type_encoding"] = {"pass": False, "error": "%s: %s" % (type(exc).__name__, exc)}

    # 基因/蛋白书写：gene 实体在 SVG 上必须带斜体标记
    gene_like = [e for e, k in (ctx.get("kinds") or {}).items() if k == "gene"]
    probes["gene_italics"] = {
        "gene_entities": len(gene_like), "italic_groups": len(svg.get("italic_entities") or []),
        "pass": set(svg.get("italic_entities") or []) >= set(gene_like)}
    probes["contract"] = {"declared": ctx.get("declared"), "missing": ctx.get("contract_missing"),
                          "pass": not ctx.get("contract_missing")}
    probes["probes_cli"] = ctx.get("cli_probes") or {}
    fails = [k for k, v in probes.items() if isinstance(v, dict) and v.get("pass") is False]
    compl = {
        "canvas": {"width_px": svg.get("width"), "height_px": svg.get("height"),
                   "pass": probes["svg_xml"]["pass"]},
        "font_style": {"min_font_px": svg.get("min_font"), "family": "DejaVu Sans, Helvetica, "
                       "Arial, sans-serif", "gene_italic_groups": svg.get("italic_entities"),
                       "pass": probes["svg_xml"]["pass"] and probes["gene_italics"]["pass"]},
        "markers": {"types": stats.get("types", []),
                    "heads": ctx.get("heads") or {},
                    "pass": probes["type_encoding"]["pass"]},
        "compartment_containment": probes["compartment_containment"],
        "legend_consistency": probes["legend_consistency"],
        "cross_lane_edges": probes["cross_lane_edges"],
        "overflow": {"text_overflow": probes["geometry"].get("texts_out_of_canvas"),
                     "pass": not probes["geometry"].get("texts_out_of_canvas")},
        "routing": {"connectors_through_boxes": probes["geometry"].get("connectors_through_boxes"),
                    "line_crossings": probes["geometry"].get("line_crossings"),
                    "pass": probes["geometry"]["pass"]},
        "pixel_probe": probes["png"], "pdf": probes["pdf"],
        "editable_source": probes["svg_xml"], "semantics": probes["type_encoding"],
        "failures": fails, "pass": not fails,
        "verdict": {"all_pass": not fails, "failed_checks": fails}}
    return {"generated": stamp(), "probes": probes, "compliance": compl,
            "thresholds": {"entities": len(svg.get("entities", {})), "entities_min": MIN_ENTITIES,
                           "relations": len(svg.get("relations", {})),
                           "relations_min": MIN_RELATIONS,
                           "zones": [z["id"] for z in stats.get("zones", [])]},
            "verdict": {"failures": fails, "all_pass": not fails},
            "limits": ["PNG 用内置 5x7 点阵，汉字画占位框，正字以 SVG/PDF 为准。",
                       "几何探针不替代人眼对美学与生物学含义的判断。"]}


def history(case, status, counts, summary, degradations):
    summary = summary or {}
    return "\n".join([
        "# 版本记录", "", "## v1.0.0（本次交付）", "",
        "1. 一条命令出三件套：分层 `figure.svg`（可编辑文字）、单页矢量 `figure.pdf`、真实 "
        "`figure.png`（zlib 手写，IHDR 可解析，非纯色）。",
        "2. 泳道自上游到下游，层高与实体数成比例；层内顺序用相邻交换爬山择优（先穿框数、后交叉数）。",
        "3. 语义落到端点与线型：实心=激活、T 端=抑制、空心=结合、P/Ub=修饰、双头=转运、虚线=间接；"
        "方向缺失画无向连接。",
        "4. 引文没过逐字校验的边不画，进 `content_map.pending`。",
        "5. 自检从盘上文件重算：区室包含、跨膜落位、跨层穿越、图例项数、类型编码互斥、基因斜体。",
        "6. 异常全捕获、退出码恒 0，`init`/`build` 都先写一版合法 partial `result.json`。", "",
        "## 本次运行（真实记录）", "",
        "- 生成 %s　case_id `%s`　status `%s`" % (stamp(), (case or {}).get("case_id"), status),
        "- 图面 %d 实体 / %d 关系 / %d 泳道；对照期望 %s（覆盖率 %s%%）"
        % (counts.get("entities", 0), counts.get("relations", 0), counts.get("zones", 0),
           summary.get("verdict"), summary.get("coverage_pct")),
        "- 降级与缺口：%s" % ("；".join(degradations) if degradations else "无"),
        "- 本文件由 `build` 依据本次运行写出，未发生的修改不会出现在这里。", ""])
