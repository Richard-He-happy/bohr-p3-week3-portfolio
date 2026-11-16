#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可核验资产层（一）：金标准推导与共用工具。

按输入原文 + 规则语义（references/rulebook.json）+ 单位登记表事实独立推导逐字段期望
清洗结果，并写出 golden_standard.json；同时提供资产层共用的常量与文件/文本工具。
导入型模块，无 CLI。
"""

import csv
import json
import re
import time

from pathlib import Path

from clean_engine import (key_form, natural_parts, parse_cell, show_num)


TOOL = "literature-extraction-standardizer"
TOOL_VERSION = "1.1.0"
ENGINE_API = "1.0.0"
SCHEMA = "lit-extraction-standardizer/evidence-assets/v1"

ASSET_FILES = ["golden_standard.json", "diff_report.md", "version_history.md",
			   "run.log", "self_check.json"]

BASE_ARTIFACTS = ["result.json", "cleaned.csv", "change_log.csv", "pending_review.csv",
				  "anomaly_report.md", "rules.json", "field_mapping.json",
				  "unit_table.json", "verify_report.json"]

STATUS_DOMAIN = ["ok", "needs_review", "missing", "replicate", "merged_duplicate", "conflict"]

REASON_TO_RULE = {"unknown_unit": "R010", "missing_unit": "R011", "unparsed_value": "R006"}

CLEANED_COLUMNS = ["row_id", "source_document_id", "source_locator", "indicator", "material",
				   "condition_summary", "value", "value_low", "value_high", "value_err",
				   "value_text", "unit", "original_field", "original_value", "original_unit",
				   "rule_ids", "judgment_key", "status", "duplicate_of", "note"]

RECORD_CAP = 120
CHANGE_CAP = 240
QUOTE_MIN_RATE = 0.8

# ------------------------------------------------------------------ 基础工具

def _now():
	try:
		from datetime import datetime
		return datetime.now().astimezone().isoformat(timespec="milliseconds")
	except Exception:
		return ""


def _mark(ctx, phase, ok=True, **detail):
	"""向运行日志追加一个阶段事件；时间戳/耗时只进 run.log。"""
	ev = ctx.get("ev")
	if ev is None:
		return
	try:
		ev.append({"ts": _now(),
				   "elapsed": round(time.time() - float(ctx.get("t0") or time.time()), 3),
				   "phase": phase, "ok": bool(ok), "detail": detail})
	except Exception:
		pass


def _squeeze(value):
	return re.sub(r"\s+", " ", str("" if value is None else value)).strip()


def _cell(value, n=110):
	return (_squeeze(value).replace("|", "/")[:n] or "-")


def _scalar(value):
	if isinstance(value, bool):
		return "true" if value else "false"
	return (_squeeze(value).replace(" ", "_")[:120] or "-")


def _dump_json(path, obj):
	_dump_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _dump_text(path, text):
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(str(text), encoding="utf-8")


def _read_json(path):
	try:
		obj = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
		return obj if isinstance(obj, dict) else {}
	except Exception:
		return {}


def _decode(raw):
	for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
		try:
			return raw.decode(enc)
		except UnicodeDecodeError:
			continue
	return raw.decode("latin-1", "replace")


def _read_text(path):
	try:
		return _decode(Path(path).read_bytes())
	except Exception:
		return ""


def _stat_files(out):
	out = Path(out)
	try:
		return {p.name: p.stat().st_size for p in sorted(out.glob("*")) if p.is_file()}
	except Exception:
		return {}


def _read_rows(path):
	try:
		if not Path(path).is_file():
			return []
		with open(path, encoding="utf-8", newline="") as fh:
			return [dict(rec) for rec in csv.DictReader(fh)]
	except Exception:
		return []


def _header(path):
	try:
		if not Path(path).is_file():
			return []
		with open(path, encoding="utf-8", newline="") as fh:
			line = fh.readline().strip()
		return [col for col in line.split(",")] if line else []
	except Exception:
		return []


def _f(value):
	if value is None:
		return None
	try:
		return float(str(value).replace(",", "").strip())
	except Exception:
		return None


def _close(a, b, rel=1e-9, abs_=1e-12):
	if a is None or b is None:
		return False
	return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def _num_text(value):
	if value is None:
		return ""
	try:
		return show_num(float(value), 6)
	except Exception:
		return _squeeze(value)


def _unescape_unicode(text):
	def repl(match):
		try:
			return chr(int(match.group(1), 16))
		except Exception:
			return match.group(0)
	return re.sub(r"\\u([0-9a-fA-F]{4})", repl, str(text or ""))


def _source_texts(ctx):
	"""把输入原文按文件名归一后缓存，供逐字 quote 命中判定（不依赖 CWD）。"""
	texts, paths = {}, []
	for path in ctx.get("record_files") or []:
		paths.append(str(path))
	if ctx.get("case_file"):
		paths.append(str(ctx["case_file"]))
	for path in ctx.get("ref_files") or []:
		paths.append(str(path))
	for path in paths:
		name = Path(path).name if not str(path).startswith("references/") else str(path)
		raw = _read_text(path)
		if not raw:
			continue
		texts[name] = {"raw": _squeeze(raw), "unescaped": _squeeze(_unescape_unicode(raw))}
	return texts


def _quote_hit(quote, texts, file_name=None):
	probe = _squeeze(quote)
	if not probe:
		return False
	pool = []
	if file_name and file_name in texts:
		pool.append(texts[file_name])
	pool.extend(value for key, value in texts.items() if key != file_name)
	for entry in pool:
		if probe in entry.get("raw", "") or probe in entry.get("unescaped", ""):
			return True
	return False

# ------------------------------------------------------- 期望结果（独立判定逻辑）

def _cond_key(row):
	conds = row.get("conds") or {}
	return "|".join("%s=%s" % (key_form(name), key_form(value))
					for name, value in sorted(conds.items()) if str(value).strip())


def _judgment_key(row):
	return "|".join([str(row.get("source_document_id") or "") or "-",
					 _cond_key(row) or "-",
					 key_form(row.get("indicator")) or "-",
					 key_form(row.get("material")) or "-"])


def _expect_primary(cell, unit):
	"""按规则语义把单元格原文映射成期望的标准形态（不读引擎的逐行判定）。"""
	if cell["kind"] == "missing":
		return {"status": "missing", "rule_ids": {"R006"},
				"value_text": "(missing: %s)" % str(cell.get("raw") or "").strip()}
	if cell["kind"] == "text":
		return {"status": "needs_review", "rule_ids": {"R006", "R010"},
				"value_text": str(cell.get("raw") or "").strip(),
				"reason": "unparsed_value"}
	if not unit:
		return {"status": "needs_review", "rule_ids": {"R011"},
				"value_text": "%s (no unit)" % (cell.get("raw") or ""),
				"reason": "missing_unit"}
	return None


def _expect_rows(ctx):
	"""从输入行 + 规则语义 + 单位登记表推导每行的期望清洗结果。"""
	rows = ctx.get("longrows") or []
	ureg = ctx.get("ureg")
	expectation = []
	for row in rows:
		cellraw = str(row.get("value_raw") or "")
		unitraw = str(row.get("unit_raw") or "")
		cell = parse_cell(cellraw)
		unitlabel = unitraw.strip() or str(cell.get("unit") or "").strip()
		exp = {"row_id": row.get("row_id"), "file": row.get("_file") or "",
			   "document_id": row.get("source_document_id") or "",
			   "locator": row.get("source_locator") or "",
			   "original_field": row.get("original_field") or "",
			   "original_value": cellraw, "original_unit": unitraw,
			   "status": "ok", "rule_ids": set(), "reason": "",
			   "value": None, "value_low": None, "value_high": None, "value_err": None,
			   "value_text": "", "unit": "", "duplicate_of": "", "changes": [],
			   "judgment_key": _judgment_key(row)}
		early = _expect_primary(cell, unitlabel)
		if early:
			exp.update(early)
			expectation.append(exp)
			continue
		conv = ureg.to_canonical(unitlabel) if ureg is not None else None
		if conv is None:
			exp.update({"status": "needs_review", "rule_ids": {"R010"},
						"value_text": "%s %s" % (cell.get("raw") or "", unitlabel),
						"reason": "unknown_unit"})
			expectation.append(exp)
			continue
		if not unitraw.strip() and cell.get("unit"):
			exp["rule_ids"].add("R004")
		mult, offs = float(conv["factor"]), float(conv["offset"])
		exp["unit"] = conv["unit"]
		if cell["kind"] == "range":
			exp["rule_ids"].add("R007")
			targets = [("value_low", cell["low"]), ("value_high", cell["high"])]
		elif cell["kind"] == "error":
			exp["rule_ids"].add("R008")
			targets = [("value", cell["value"]), ("value_err", cell["err"])]
		else:
			targets = [("value", cell["value"])]
		for field, origin in targets:
			addterm = offs if field != "value_err" else 0.0
			newval = origin * mult + addterm
			exp[field] = abs(newval) if field == "value_err" else newval
			if abs(mult - 1.0) > 1e-12 or abs(addterm) > 1e-12:
				rule = "R008" if field == "value_err" else "R009"
				exp["rule_ids"].add(rule)
				exp["changes"].append({"row_id": exp["row_id"], "field": field,
									   "before": origin, "factor": mult, "offset": addterm,
									   "unit_before": unitlabel, "unit_after": exp["unit"],
									   "rule_id": rule, "locator": exp["locator"],
									   "document_id": exp["document_id"]})
		if cell["kind"] == "range":
			exp["value_text"] = "%s-%s" % (_num_text(cell["low"]), _num_text(cell["high"]))
		elif cell["kind"] == "error":
			exp["value_text"] = "%s +/- %s" % (_num_text(cell["value"]), _num_text(cell["err"]))
		else:
			exp["value_text"] = _num_text(cell["value"])
		expectation.append(exp)
	return expectation


def _apply_dedupe(expectation, rulebook):
	"""用更简单的比较规则独立复算判定键去重结论（R013/R014/R015）。"""
	matching = (rulebook or {}).get("matching") or {}
	conftol = float(matching.get("conflict_relative_tolerance", 0.05))
	reptol = float(matching.get("replicate_relative_tolerance", 0.05))
	groups = {}
	for exp in expectation:
		if exp["status"] == "ok":
			groups.setdefault(exp["judgment_key"], []).append(exp)
	for sig in sorted(groups):
		members = sorted(groups[sig], key=lambda item: natural_parts(item["row_id"]))
		if len(members) < 2:
			continue
		units = sorted({item["unit"] for item in members})
		values = [item["value"] if item["value"] is not None else item["value_low"]
				  for item in members]
		if len(units) > 1:
			for item in members:
				item["status"] = "conflict"
				item["reason"] = "unit_conflict"
			continue
		present = [abs(value) for value in values if value is not None]
		top = max(present) if present else 0.0
		identical = bool(present) and all(
			value is not None and abs(value - values[0]) <= 1e-9 * max(abs(value), 1e-300)
			for value in values)
		spread = 0.0 if len(present) < 2 or not top else (max(present) - min(present)) / top
		if identical:
			for item in members[1:]:
				item["status"] = "merged_duplicate"
				item["duplicate_of"] = members[0]["row_id"]
				item["reason"] = "identical"
		elif spread <= reptol:
			for item in members[1:]:
				item["status"] = "replicate"
				item["reason"] = "replicate"
		else:
			for item in members:
				item["status"] = "conflict"
				item["reason"] = "value_conflict"
	return expectation


def _expected_field_counts(expectation):
	counts = {name: 0 for name in CLEANED_COLUMNS}
	for exp in expectation:
		counts["row_id"] += 1 if exp["row_id"] else 0
		counts["source_document_id"] += 1 if exp["document_id"] else 0
		counts["source_locator"] += 1 if exp["locator"] else 0
		counts["indicator"] += 1 if exp["original_field"] or exp["unit"] else 0
		counts["material"] += 1 if exp["judgment_key"].split("|")[-1] not in ("", "-") else 0
		counts["condition_summary"] += 1 if "|" in exp["judgment_key"] else 0
		counts["value"] += 1 if exp["value"] is not None else 0
		counts["value_low"] += 1 if exp["value_low"] is not None else 0
		counts["value_high"] += 1 if exp["value_high"] is not None else 0
		counts["value_err"] += 1 if exp["value_err"] is not None else 0
		counts["value_text"] += 1 if exp["value_text"] else 0
		counts["unit"] += 1 if exp["unit"] else 0
		counts["original_field"] += 1 if exp["original_field"] else 0
		counts["original_value"] += 1 if exp["original_value"] else 0
		counts["original_unit"] += 1 if exp["original_unit"] else 0
		counts["rule_ids"] += 1 if exp["rule_ids"] else 0
		counts["judgment_key"] += 1 if exp["judgment_key"] else 0
		counts["status"] += 1
		counts["duplicate_of"] += 1 if exp["duplicate_of"] else 0
		counts["note"] += 1 if exp["status"] not in ("ok", "replicate") else 0
	return counts


def _expected_rule_counts(expectation, rules):
	"""按规则语义独立统计每条的应命中行数（strict 规则参与 diff 判定）。"""
	counts = {rule_id: 0 for rule_id in rules}
	statuses = [exp["status"] for exp in expectation]
	for exp in expectation:
		for rule_id in exp["rule_ids"]:
			counts[rule_id] = counts.get(rule_id, 0) + 1
	counts["R013"] = statuses.count("merged_duplicate")
	counts["R014"] = statuses.count("replicate")
	counts["R015"] = statuses.count("conflict")
	counts["R001"] = sum(1 for exp in expectation if exp["row_id"])
	counts["R018"] = sum(1 for exp in expectation if exp["status"] in STATUS_DOMAIN)
	counts["R017"] = sum(len(exp["changes"]) for exp in expectation)
	if rules.get("R012") is not None:
		counts["R012"] = None  # 归一化幅度无法从落盘产物复核，仅登记
	return counts

# --------------------------------------------------------------- 金标准构建

def build_golden(ctx, expectation):
	case = ctx.get("case") or {}
	contract = ctx.get("contract") or {}
	rulebook = ctx.get("rulebook") or {}
	target = ctx.get("target") or {}
	rules = ctx.get("rules") or {}
	texts = ctx.get("texts") or _source_texts(ctx)
	ctx["texts"] = texts
	fields = [str(name) for name in ((target or {}).get("fields") or CLEANED_COLUMNS)]
	artifact_map = (rulebook.get("messages") or {}).get("artifacts") or {}
	matching = rulebook.get("matching") or {}

	contract_items = []
	for key in contract:
		artifact = artifact_map.get(key, "")
		quote = _squeeze(key)
		hit = _quote_hit(quote, texts, "case.json")
		contract_items.append({
			"id": "G-C%02d" % (len(contract_items) + 1), "key": key,
			"expected": "result.json 顶层出现键 `%s`，且内容与 output_contract 同型" % key,
			"expected_artifact": artifact,
			"source": {"file": "case.json", "locator": "case.json#output_contract.%s" % key,
					   "quote": quote, "quote_verbatim": bool(hit)},
			"basis": "contract"})

	workorder_items, workorder_source = [], "case.json workorder"
	raw_workorder = None
	for name in ("workorder", "cleaning_workorder", "field_workorder", "organizer_workorder",
				 "target_fields"):
		if isinstance(case.get(name), (list, dict)):
			raw_workorder = (name, case[name])
			break
	if raw_workorder:
		name, raw = raw_workorder
		sequence = raw if isinstance(raw, list) else [raw]
		for index, item in enumerate(sequence):
			text = item.get("instruction") if isinstance(item, dict) else item
			text = _squeeze(text if isinstance(text, str) else json.dumps(text, ensure_ascii=False))
			if not text:
				continue
			workorder_items.append({
				"id": "G-W%02d" % (len(workorder_items) + 1),
				"instruction": text[:400],
				"expected": "该 workorder 条目对应的清洗字段/产物出现在输出中",
				"source": {"file": "case.json", "locator": "case.json#%s[%d]" % (name, index),
						   "quote": text[:300],
						   "quote_verbatim": bool(_quote_hit(text[:300], texts, "case.json"))},
				"basis": "contract"})
	else:
		workorder_source = "derived from references/rulebook.json messages.artifacts (case 未提供 workorder)"
		for key in artifact_map:
			instruction = "输出 %s（契约键 `%s`）" % (artifact_map[key], key)
			workorder_items.append({
				"id": "G-W%02d" % (len(workorder_items) + 1), "instruction": instruction,
				"expected": "输出目录存在非空文件 `%s`" % artifact_map[key],
				"expected_artifact": artifact_map[key],
				"source": {"file": "references/rulebook.json",
						   "locator": "references/rulebook.json#messages.artifacts.%s" % key,
						   "quote": artifact_map[key],
						   "quote_verbatim": bool(_quote_hit(artifact_map[key], texts))},
				"basis": "package contract"})

	field_items = []
	counts = _expected_field_counts(expectation)
	strict_fields = {"row_id", "source_document_id", "source_locator", "indicator", "material",
					 "value", "value_low", "value_high", "value_err", "unit", "original_field",
					 "original_value", "original_unit", "rule_ids", "judgment_key", "status",
					 "duplicate_of"}
	for name in CLEANED_COLUMNS:
		field_items.append({
			"id": "G-F%02d" % (len(field_items) + 1), "field": name,
			"expected_column": name in fields or name in CLEANED_COLUMNS,
			"expected_non_empty": counts.get(name, 0),
			"strict": name in strict_fields,
			"expectation": {
					"row_id": "每一输入行一个身份，原样保留（R001）",
					"source_document_id": "来源文献编号",
					"source_locator": "原文定位，原样保留",
					"indicator": "归一后的指标标签；原文留在 original_field（R012）",
					"material": "归一后的物质标签（R012）",
					"condition_summary": "条件列排序后的 name=value 摘要（判定键与展示用）",
					"value": "单值行换算后的主值；缺失/区间/未知单位时为空（R006/R007/R010）",
					"value_low": "区间下界换算值（R007）",
					"value_high": "区间上界换算值（R007）",
					"value_err": "± 误差项换算值，同一 factor、不加 offset（R008）",
					"value_text": "给人看的原文形态（缺失记号/区间/± 原样保留）",
					"unit": "规范单位；未确认时为空（R010/R011）",
					"original_field": "指标列原文，用于回溯",
					"original_value": "数值单元格原文，逐字不加工",
					"original_unit": "单位单元格原文，逐字不加工",
					"rule_ids": "本行命中规则号并集，; 分隔",
					"judgment_key": "来源|条件摘要|指标|物质 四段判定键（R013/R014/R015）",
					"status": "ok/needs_review/missing/replicate/merged_duplicate/conflict（R018）",
					"duplicate_of": "被合并行指向保留行的 row_id（R013）",
					"note": "补充事实（同单位直通、不等式边界等），非结论字段",
				}[name],
			"source": {"file": "references/rulebook.json",
					   "locator": "references/rulebook.json#target_table.fields",
					   "quote": name,
					   "quote_verbatim": bool(_quote_hit(name, texts))},
			"basis": "rules"})

	strict_rules = {"R001", "R004", "R006", "R007", "R008", "R009", "R010", "R011",
					"R013", "R014", "R015", "R017", "R018"}
	rule_counts = _expected_rule_counts(expectation, rules)
	rule_items = []
	for rule_id in sorted(rules):
		rule = rules[rule_id]
		expected = rule_counts.get(rule_id)
		observed = expected is None or expected > 0
		rule_items.append({
			"id": "G-R%02d" % (len(rule_items) + 1), "rule_id": rule_id,
			"priority": rule.get("priority"), "scope": rule.get("applies_to"),
			"when": _squeeze(rule.get("condition"))[:200],
			"do": _squeeze(rule.get("transform"))[:200],
			"human_gate": bool(rule.get("human_gate")),
			"strict": rule_id in strict_rules,
			"coverage": "observed" if observed else "not_observed",
			"expected_applications": expected,
			"evidence": {
				"R004": "cleaned.csv 的 rule_ids 含 R004 的行数（单位取自表头）",
				"R006": "cleaned.csv 的 rule_ids 含 R006 的行数（缺失/文本）",
				"R007": "cleaned.csv 的 rule_ids 含 R007 的行数（区间）",
				"R008": "cleaned.csv 的 rule_ids 含 R008 的行数（± 误差）",
				"R009": "cleaned.csv 的 rule_ids 含 R009 的行数（发生换算）",
				"R010": "cleaned.csv 的 rule_ids 含 R010 的行数 + 待确认原因码 unknown_unit",
				"R011": "cleaned.csv 的 rule_ids 含 R011 的行数 + 待确认原因码 missing_unit",
				"R013": "cleaned.csv 中 status=merged_duplicate 的行数",
				"R014": "cleaned.csv 中 status=replicate 的行数",
				"R015": "cleaned.csv 中 status=conflict 的行数",
				"R017": "change_log.csv 中 precision 非空的行数",
				"R018": "cleaned.csv 中 status 落在允许集合内的行数",
				"R001": "cleaned.csv 中 row_id 非空的行数",
			}.get(rule_id, "登记项（规则已声明；本次输入未触发可独立复核的计数）"),
			"basis": "rules"})

	record_items = []
	for exp in expectation[:RECORD_CAP]:
		quote = exp["original_value"]
		hit = _quote_hit(quote, texts, exp["file"])
		record_items.append({
			"id": "G-D%03d" % (len(record_items) + 1), "row_id": exp["row_id"],
			"source": {"file": exp["file"], "document_id": exp["document_id"],
					   "locator": exp["locator"], "quote": quote,
					   "quote_verbatim": bool(hit)},
			"original": {"field": exp["original_field"], "value": exp["original_value"],
						 "unit": exp["original_unit"]},
			"expected": {"status": exp["status"], "value": exp["value"],
						 "value_low": exp["value_low"], "value_high": exp["value_high"],
						 "value_err": exp["value_err"], "unit": exp["unit"],
						 "value_text": exp["value_text"],
						 "rule_ids": sorted(exp["rule_ids"]),
						 "duplicate_of": exp["duplicate_of"],
						 "judgment_key": exp["judgment_key"]},
			"basis": sorted(exp["rule_ids"]) or ["R018"],
			"note": ("待人工：" + exp["reason"]) if exp["reason"] else ""})

	change_items = []
	for exp in expectation:
		if len(change_items) >= CHANGE_CAP:
			break
		for change in exp["changes"]:
			if len(change_items) >= CHANGE_CAP:
				break
			change_items.append({
				"id": "G-L%03d" % (len(change_items) + 1),
				"row_id": change["row_id"], "field": change["field"],
				"before": change["before"], "factor": change["factor"],
				"offset": change["offset"], "unit_before": change["unit_before"],
				"unit_after": change["unit_after"], "rule_id": change["rule_id"],
				"locator": change["locator"],
				"expected": "after = before*factor + offset 且单位/规则号与 change_log.csv 一致"})
	changes_total = sum(len(exp["changes"]) for exp in expectation)

	artifact_items = []
	for name in BASE_ARTIFACTS + ASSET_FILES:
		artifact_items.append({
			"id": "G-A%02d" % (len(artifact_items) + 1), "artifact": name,
			"expected": "输出目录存在非空文件 `%s`" % name,
			"source": {"file": "package contract", "locator": "outputs/%s" % name,
					   "quote": "", "quote_verbatim": False},
			"basis": "contract"})

	quotes = [item for item in (contract_items + workorder_items + field_items + record_items)
			  if item["source"]["quote"]]
	hits = [item for item in quotes if item["source"]["quote_verbatim"]]
	counters = {
		"records": len(expectation), "records_in_golden": len(record_items),
		"records_capped": max(0, len(expectation) - len(record_items)),
		"changes": len(change_items), "changes_total": changes_total,
		"changes_capped": max(0, changes_total - len(change_items)),
		"contract_keys": len(contract_items),
		"workorder_items": len(workorder_items), "fields": len(field_items),
		"rules": len(rule_items), "artifacts": len(artifact_items),
		"quotes": len(quotes), "quotes_verbatim": len(hits),
		"quote_hit_rate": round(len(hits) / len(quotes), 4) if quotes else 0.0,
		"items_total": (len(contract_items) + len(workorder_items) + len(field_items)
						+ len(rule_items) + len(record_items) + len(change_items)
						+ len(artifact_items))}
	return {
		"schema": SCHEMA, "kind": "golden_standard",
		"tool": {"name": TOOL, "version": TOOL_VERSION, "engine_api": ENGINE_API},
		"case_id": (ctx.get("case") or {}).get("case_id"),
		"generated_by": "scripts/evidence_golden.py，由 scripts/run_clean.py -> evidence_assets.emit_assets() 在 build/finalize 阶段调用",
		"scope_note": ("只覆盖 output_contract、规则库语义、目标字段表与输入抽取行；期望值由输入原文 + "
                       "规则语义 + unit_registry 换算事实独立推导，不读本次实际判定。"),
		"locator_scheme": ("records[].source.locator = 输入行自带的 source_document_id / source_locator "
						   "（原样）；case.json#<path> = 案例文档内路径；"
						   "references/rulebook.json#<path> = 规则库内路径；outputs/<name> = 输出文件。"),
		"basis_legend": {
			"contract": "从 case.json 的 output_contract / workorder 或包级产物契约直接导出",
			"rules": "从 references/rulebook.json 的规则声明与目标字段表导出",
			"records": "从输入抽取行 + 单位登记表事实逐行推导"},
		"inputs": {"case_file": Path(str(ctx.get("case_file"))).name if ctx.get("case_file") else None,
				   "contract_keys": list(contract.keys()),
				   "record_files": [Path(str(p)).name for p in (ctx.get("record_files") or [])],
				   "input_rows": len(expectation),
				   "unit_table": "references/unit_registry.json",
				   "matching_tolerance": {"replicate": matching.get("replicate_relative_tolerance"),
										  "conflict": matching.get("conflict_relative_tolerance")}},
		"contract": contract_items,
		"workorder": {"source": workorder_source, "items": workorder_items},
		"fields": field_items,
		"rules": rule_items,
		"records": record_items,
		"changes": change_items,
		"artifacts": artifact_items,
		"counts": counters,
		"notes": [
			"records 超过 %d 行时只写前 %d 行，changes 超过 %d 条时只写前 %d 条；"
			"counts.records_capped / changes_capped 记录被截断数量，diff_report 对全量计数仍做自洽检查。"
			% (RECORD_CAP, RECORD_CAP, CHANGE_CAP, CHANGE_CAP),
			"区间/± 误差不压成单值；缺失不补 0；未知单位不猜——这些是 expected 的一部分，不是建议。",
		]}


def _fallback_golden(ctx, error):
	return {"schema": SCHEMA, "kind": "golden_standard",
			"tool": {"name": TOOL, "version": TOOL_VERSION},
			"case_id": (ctx.get("case") or {}).get("case_id"),
			"generated_by": "scripts/evidence_golden.py",
			"degraded": True,
			"error": "%s: %s" % (type(error).__name__, error),
			"note": "金标准生成失败；原 9 件清洗产物不受影响，diff_report/self_check 会如实记录缺口。",
			"contract": [], "workorder": {"items": []}, "fields": [], "rules": [],
			"records": [], "changes": [], "artifacts": [], "counts": {"items_total": 0}}
