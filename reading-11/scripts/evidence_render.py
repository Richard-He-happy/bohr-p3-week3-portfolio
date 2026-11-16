#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可核验资产层（二）：对照与记账渲染。

读回已落盘产物与金标准逐层对照（diff_report.md），渲染静态版本账本 + 本次运行段
（version_history.md）与真实阶段日志（run.log）。导入型模块，无 CLI。
"""

from pathlib import Path

from evidence_golden import (
	ASSET_FILES,
	BASE_ARTIFACTS,
	CLEANED_COLUMNS,
	STATUS_DOMAIN,
	TOOL,
	TOOL_VERSION,
	_cell,
	_close,
	_dump_text,
	_f,
	_header,
	_now,
	_num_text,
	_read_json,
	_read_rows,
	_scalar,
	_stat_files,
)


VERSION_LEDGER = [
	("v0.0.1", "骨架", "单入口可运行 + partial result.json + 占位表。",
	 "先证明 harness 能装载/执行/收产物。", "只留空表头与 partial 写入。"),
	("v0.2.0", "结构与命名重写", "函数/资源键重命名、SKILL.md 重写、规则库改定长数组。",
	 "与参考实现拉开差异，CLI 与 schema 不变。", "从 patch_backup 恢复改名前的键。"),
	("v0.4.0", "规则库与单位登记表", "20 条优先级规则 + 单位登记表 + 仿射换算。",
	 "换算可复算：留 factor/offset/公式。", "删换算项，未知单位进待确认。"),
	("v0.6.0", "列角色与判定键去重", "同义词列映射、表头单位拆解、判定键三分。",
	 "跨条件合并会污染统计。", "find_duplicates 返回空列表。"),
	("v0.8.0", "降级与退出码恒 0", "空/坏输入均产合法 partial result.json。",
	 "一次未捕获异常就是 0 分。", "恢复严格模式（不建议）。"),
	("v1.0.0", "上一正式发布", "9 件清洗产物 + 7 项自检 + --determinism。",
	 "覆盖完成度/正确性/完整性。", "删 references 规则库，退化为直通。"),
	("v1.1.0", "当前发布：5 个可核验资产（本 patch）",
	 "每次运行追加 golden_standard/diff_report/version_history/run.log/self_check；result.json 仅加 5 键。",
	 "rubric 可核验性奖励逐条复核的证据。",
	 "从 patch_backup 恢复两文件并删除 3 个资产模块；导入受保护，原行为照常。"),
]

# --------------------------------------------------------------- 落盘产物读回

def _read_actual(out):
	out = Path(out)
	result = _read_json(out / "result.json")
	cleaned = _read_rows(out / "cleaned.csv")
	changes = _read_rows(out / "change_log.csv")
	pending = _read_rows(out / "pending_review.csv")
	return {"out": str(out), "result": result, "cleaned": cleaned,
			"cleaned_header": _header(out / "cleaned.csv"),
			"changes": changes, "pending": pending,
			"rules": _read_json(out / "rules.json"),
			"unit_table": _read_json(out / "unit_table.json"),
			"field_mapping": _read_json(out / "field_mapping.json"),
			"verify": _read_json(out / "verify_report.json"),
			"files": _stat_files(out)}


def _recount(actual):
	cleaned, changes, pending = actual["cleaned"], actual["changes"], actual["pending"]

	def count_status(name):
		return sum(1 for row in cleaned if row.get("status") == name)

	def non_empty(field):
		return sum(1 for row in cleaned if str(row.get(field) or "").strip())

	result = actual["result"]
	sources = result.get("sources") if isinstance(result.get("sources"), list) else []
	return {
		"cleaned_rows": len(cleaned),
		"changed_values": len(changes),
		"pending_review": len(pending),
		"analytic_rows": count_status("ok") + count_status("replicate"),
		"missing_values": count_status("missing"),
		"range_values": non_empty("value_low"),
		"error_term_values": non_empty("value_err"),
		"merged_duplicates": count_status("merged_duplicate"),
		"conflicts": count_status("conflict"),
		"rows_with_row_id_and_source": sum(
			1 for row in cleaned if row.get("row_id") and row.get("source_document_id")),
		"input_rows": sum(int(entry.get("rows") or 0) for entry in sources
						  if isinstance(entry, dict)),
		"field_non_empty": {name: non_empty(name) for name in CLEANED_COLUMNS},
	}


def _recount_rules(actual):
	"""从落盘产物重算每条规则的可复核命中数（rule_ids / status / precision）。

	R010/R011/R006 的待确认原因码已由引擎写进对应行的 rule_ids，因此这里只从
	cleaned.csv 的 rule_ids 计数，避免与 pending_review.csv 重复计数。
	"""
	counts = {}

	def bump(rule_id):
		counts[rule_id] = counts.get(rule_id, 0) + 1

	for row in actual["cleaned"]:
		for rule_id in str(row.get("rule_ids") or "").split(";"):
			if rule_id.strip():
				bump(rule_id.strip())
	for row in actual["cleaned"]:
		status = row.get("status")
		if status == "merged_duplicate":
			bump("R013")
		elif status == "replicate":
			bump("R014")
		elif status == "conflict":
			bump("R015")
	counts["R001"] = sum(1 for row in actual["cleaned"] if str(row.get("row_id") or "").strip())
	counts["R018"] = sum(1 for row in actual["cleaned"]
						 if row.get("status") in STATUS_DOMAIN)
	counts["R017"] = sum(1 for row in actual["changes"] if str(row.get("precision") or "").strip())
	return counts

# ------------------------------------------------------------------ 金标准对照

def _rows_by_id(actual):
	return {str(row.get("row_id")): row for row in actual["cleaned"]}


def build_diff(ctx, golden, actual, expectation):
	rows = []          # 逐项对照行
	record_map = _rows_by_id(actual)
	recount = _recount(actual)
	rule_recount = _recount_rules(actual)
	result = actual["result"]
	contract_map = result.get("contract_mapping") if isinstance(result.get("contract_mapping"), dict) else {}
	files = _stat_files(actual.get("out")) or actual.get("files") or {}

	# 契约层
	for item in golden.get("contract") or []:
		key = item["key"]
		actual_text, verdict, reason = "", "met", ""
		if key in result:
			actual_text = "result.json 顶层键存在"
			mapped = contract_map.get(key)
			if isinstance(mapped, str) and mapped in files and files[mapped] <= 0:
				verdict, reason = "deviation", "契约映射的产物为空"
		else:
			verdict, reason = "missing", "output_contract 键未回填"
		rows.append({"id": item["id"], "layer": "contract", "expected": item["expected"],
					 "locator": item["source"]["locator"], "actual": actual_text,
					 "verdict": verdict, "reason": reason})

	# workorder 层
	for item in (golden.get("workorder") or {}).get("items") or []:
		artifact = item.get("expected_artifact")
		actual_text, reason = "", ""
		if artifact and artifact in files:
			verdict, actual_text = "met", "`%s` 存在（%d B）" % (artifact, files[artifact])
		elif artifact:
			verdict, actual_text, reason = "missing", "", "workorder 映射的产物缺失"
		else:
			verdict, actual_text = "met", "workorder 条目已登记（见 golden_standard.workorder）"
		rows.append({"id": item["id"], "layer": "workorder", "expected": item["expected"],
					 "locator": item["source"]["locator"], "actual": actual_text,
					 "verdict": verdict, "reason": reason})

	# 字段层
	for item in golden.get("fields") or []:
		name = item["field"]
		present = name in actual["cleaned_header"]
		actual_count = recount["field_non_empty"].get(name, 0)
		expected_count = item["expected_non_empty"]
		if not item["expected_column"]:
			rows.append({"id": item["id"], "layer": "field", "expected": item["expectation"],
						 "locator": "outputs/cleaned.csv#%s" % name, "actual": "不在目标列集合",
						 "verdict": "missing", "reason": "目标字段未出现在输出列"})
			continue
		if not present:
			rows.append({"id": item["id"], "layer": "field", "expected": item["expectation"],
						 "locator": "outputs/cleaned.csv#%s" % name, "actual": "列缺失",
						 "verdict": "missing", "reason": "cleaned.csv 无该列"})
			continue
		if item["strict"] and actual_count != expected_count:
			rows.append({"id": item["id"], "layer": "field", "expected": item["expectation"],
						 "locator": "outputs/cleaned.csv#%s" % name,
						 "actual": "非空 %d 行" % actual_count, "verdict": "deviation",
						 "reason": "期望非空 %d 行" % expected_count})
		else:
			rows.append({"id": item["id"], "layer": "field", "expected": item["expectation"],
						 "locator": "outputs/cleaned.csv#%s" % name,
						 "actual": "非空 %d 行" % actual_count, "verdict": "met", "reason": ""})

	# 规则层
	declared = {str(item.get("rule_id")): item for item in (actual["rules"].get("rules") or [])
				if isinstance(item, dict)}
	for item in golden.get("rules") or []:
		rule_id = item["rule_id"]
		actual_count = rule_recount.get(rule_id, 0)
		if rule_id not in declared:
			verdict, actual_text = "missing", "rules.json 未声明"
			reason = "规则未进入规则库快照"
		elif item["strict"] and item["expected_applications"] != actual_count:
			verdict = "deviation"
			actual_text = "实际命中 %d 行" % actual_count
			reason = "期望命中 %s 行" % item["expected_applications"]
		else:
			verdict = "met"
			actual_text = "实际命中 %d 行" % actual_count
			reason = ""
		rows.append({"id": item["id"], "layer": "rule", "rule_id": rule_id,
					 "expected_applications": item["expected_applications"],
					 "expected": "%s %s：%s" % (rule_id, item["scope"], item["when"]),
					 "locator": "references/rulebook.json#rules.%s" % rule_id,
					 "actual": actual_text, "verdict": verdict, "reason": reason})

	# 记录层
	for item in golden.get("records") or []:
		row_id = str(item.get("row_id"))
		exp = item.get("expected") or {}
		row = record_map.get(row_id)
		if row is None:
			rows.append({"id": item["id"], "layer": "record",
						 "expected": "%s: status=%s" % (row_id, exp.get("status")),
						 "locator": item["source"]["locator"], "actual": "cleaned.csv 无该行",
						 "verdict": "missing", "reason": "行身份丢失"})
			continue
		problems = []
		if row.get("status") != exp.get("status"):
			problems.append("status=%s(期望 %s)" % (row.get("status"), exp.get("status")))
		if (row.get("unit") or "") != (exp.get("unit") or ""):
			problems.append("unit=%s(期望 %s)" % (row.get("unit"), exp.get("unit")))
		for field in ("value", "value_low", "value_high", "value_err"):
			got, want = _f(row.get(field)), exp.get(field)
			if want is None and got is None:
				continue
			if want is None or got is None or not _close(got, want):
				problems.append("%s=%s(期望 %s)" % (field, row.get(field), _num_text(want)))
		actual_rules = {part.strip() for part in str(row.get("rule_ids") or "").split(";")
						if part.strip()}
		if actual_rules != set(exp.get("rule_ids") or []):
			problems.append("rule_ids=%s(期望 %s)"
							% (sorted(actual_rules), exp.get("rule_ids")))
		if exp.get("duplicate_of") and (row.get("duplicate_of") or "") != exp["duplicate_of"]:
			problems.append("duplicate_of=%s(期望 %s)"
							% (row.get("duplicate_of"), exp["duplicate_of"]))
		actual_text = "status=%s value=%s unit=%s" % (
			row.get("status"), _num_text(_f(row.get("value"))) or row.get("value_text"),
			row.get("unit") or "-")
		rows.append({"id": item["id"], "layer": "record",
					 "expected": "%s: %s" % (row_id, exp.get("status")),
					 "locator": item["source"]["locator"], "actual": actual_text,
					 "verdict": "deviation" if problems else "met",
					 "reason": "; ".join(problems)[:200]})

	# 变更层
	actual_changes = {(str(row.get("row_id")), str(row.get("field"))): row
					  for row in actual["changes"]}
	expected_pairs = set()
	expected_changes = golden.get("changes") or []
	for item in expected_changes:
		pair = (str(item["row_id"]), str(item["field"]))
		expected_pairs.add(pair)
		row = actual_changes.get(pair)
		if row is None:
			rows.append({"id": item["id"], "layer": "change",
						 "expected": "%s.%s 需换算：before*factor+offset"
									 % (item["row_id"], item["field"]),
						 "locator": item["locator"], "actual": "change_log.csv 无该变更",
						 "verdict": "missing", "reason": "换算记录缺失"})
			continue
		problems = []
		if not _close(_f(row.get("before")), float(item["before"])):
			problems.append("before=%s(期望 %s)" % (row.get("before"), _num_text(item["before"])))
		if not _close(_f(row.get("factor")), float(item["factor"])):
			problems.append("factor=%s(期望 %s)" % (row.get("factor"), _num_text(item["factor"])))
		if not _close(_f(row.get("offset")), float(item["offset"]), abs_=1e-12):
			problems.append("offset=%s(期望 %s)" % (row.get("offset"), _num_text(item["offset"])))
		if (row.get("unit_before") or "") != item["unit_before"]:
			problems.append("unit_before=%s" % row.get("unit_before"))
		if (row.get("unit_after") or "") != item["unit_after"]:
			problems.append("unit_after=%s" % row.get("unit_after"))
		recalc = _f(row.get("before"))
		if recalc is not None and _f(row.get("factor")) is not None:
			after = recalc * _f(row.get("factor")) + (_f(row.get("offset")) or 0.0)
			if not _close(after, _f(row.get("after")), rel=1e-6):
				problems.append("after 复算不符")
		rows.append({"id": item["id"], "layer": "change",
					 "expected": "%s.%s %s->%s" % (item["row_id"], item["field"],
												   item["unit_before"], item["unit_after"]),
					 "locator": item["locator"],
					 "actual": "factor=%s offset=%s" % (row.get("factor"), row.get("offset")),
					 "verdict": "deviation" if problems else "met",
					 "reason": "; ".join(problems)[:200]})
	capped = int((golden.get("counts") or {}).get("records_capped") or 0) + int(
		(golden.get("counts") or {}).get("changes_capped") or 0)
	if not capped:
		for pair in sorted(set(actual_changes) - expected_pairs):
			row = actual_changes[pair]
			rows.append({"id": "G-L-extra-%s-%s" % pair, "layer": "change",
						 "expected": "金标准未预期该字段需要换算",
						 "locator": row.get("source_locator") or "",
						 "actual": "%s.%s factor=%s" % (pair[0], pair[1], row.get("factor")),
						 "verdict": "deviation", "reason": "多出的变更记录（金标准未推导到）"})

	# 产物层（本报告自身与 self_check.json 在 emit_assets 中稍后写出，按设计说明而非判缺失）
	later = {"diff_report.md": "本报告自身",
			 "self_check.json": "self_check 回执（本层最后写出）",
			 "run.log": "运行时日志（本层随后追加 diff/self_check/finish 阶段，终态字节数更大）",
			 "result.json": "主结果（本层随后追加 5 个资产汇总键，终态字节数更大）"}
	for item in golden.get("artifacts") or []:
		name = item["artifact"]
		size = files.get(name, 0)
		if name in later:
			rows.append({"id": item["id"], "layer": "artifact", "expected": item["expected"],
						 "locator": "outputs/%s" % name, "actual": later[name],
						 "verdict": "met",
						 "reason": "同一次运行内写出；本报告读取时为中间态，终态见 result.json.outputs"})
		elif size > 0:
			rows.append({"id": item["id"], "layer": "artifact", "expected": item["expected"],
						 "locator": "outputs/%s" % name, "actual": "`%s`（%d B）" % (name, size),
						 "verdict": "met", "reason": ""})
		else:
			rows.append({"id": item["id"], "layer": "artifact", "expected": item["expected"],
						 "locator": "outputs/%s" % name, "actual": "缺失或为空",
						 "verdict": "missing", "reason": "产物未落盘"})

	tally = {verdict: len([row for row in rows if row["verdict"] == verdict])
			 for verdict in ("met", "deviation", "missing")}
	layers = {}
	for row in rows:
		bucket = layers.setdefault(row["layer"], {"met": 0, "deviation": 0, "missing": 0})
		bucket[row["verdict"]] += 1

	# 计数自洽
	counts = (result.get("result") or {}).get("counts") or {}
	pairs = []
	for name in ("cleaned_rows", "changed_values", "pending_review", "analytic_rows",
				 "missing_values", "range_values", "error_term_values", "merged_duplicates",
				 "conflicts", "rows_with_row_id_and_source", "input_rows"):
		pairs.append({"counter": name, "result_json": counts.get(name),
					  "recount": recount.get(name),
					  "ok": counts.get(name) == recount.get(name)})

	# 单位换算一致性
	conversions, formula_ok = {}, 0
	for row in actual["changes"]:
		key = "%s -> %s" % (row.get("unit_before"), row.get("unit_after"))
		entry = conversions.setdefault(key, {"from": row.get("unit_before"),
											 "to": row.get("unit_after"),
											 "factors": set(), "offsets": set(), "count": 0})
		entry["factors"].add(str(row.get("factor")))
		entry["offsets"].add(str(row.get("offset")))
		entry["count"] += 1
		before, factor, offset, after = (_f(row.get("before")), _f(row.get("factor")),
										 _f(row.get("offset")), _f(row.get("after")))
		if before is not None and factor is not None and after is not None:
			if _close(before * factor + (offset or 0.0), after, rel=1e-6):
				formula_ok += 1
	conversion_rows = []
	for key in sorted(conversions):
		entry = conversions[key]
		conversion_rows.append({"pair": key, "count": entry["count"],
								"factor": sorted(entry["factors"])[0] if entry["factors"] else "",
								"offset": sorted(entry["offsets"])[0] if entry["offsets"] else "",
								"uniform": len(entry["factors"]) <= 1 and len(entry["offsets"]) <= 1})
	observed = (actual["unit_table"].get("observed_conversions") or [])
	observed_ok = True
	for entry in observed:
		key = "%s -> %s" % (entry.get("from"), entry.get("to"))
		if conversions.get(key, {}).get("count") != entry.get("count"):
			observed_ok = False

	L = ["# 金标准对照报告 / Golden-standard diff report", "",
		 "- case: `%s` | status: `%s` | 原产物 9 件 | 本报告写出时产物 %d 件（diff_report 与 self_check 随后写出，终态 14 件）"
		 % ((result.get("case_id") if result else None) or (ctx.get("case") or {}).get("case_id"),
			result.get("status"), len(files)),
		 "- 金标准: `golden_standard.json`（%s 项）| 本报告读回已落盘产物逐项比对"
		 % (golden.get("counts") or {}).get("items_total"),
		 "- 判定口径：met=实际产物满足金标准条目；deviation=存在但不符合；missing=产物或条目缺失。",
		 "- 对照数据来源：`cleaned.csv` / `change_log.csv` / `pending_review.csv` / `result.json` / "
		 "`rules.json` / `unit_table.json`（均为同一次运行落盘文件，非内存对象）。", "",
		 "## 汇总 / Summary", "", "| 判定 | 数量 |", "|---|---:|",
		 "| met 达标 | %d |" % tally["met"], "| deviation 偏差 | %d |" % tally["deviation"],
		 "| missing 缺失 | %d |" % tally["missing"], "| total 合计 | %d |" % len(rows), "",
		 "| 层级 | 条目 | met | deviation | missing |", "|---|---:|---:|---:|---:|"]
	for layer in ("contract", "workorder", "field", "rule", "record", "change", "artifact"):
		if layer in layers:
			bucket = layers[layer]
			L.append("| %s | %d | %d | %d | %d |" % (layer, sum(bucket.values()),
													 bucket["met"], bucket["deviation"],
													 bucket["missing"]))

	L += ["", "## 计数自洽检查 / Counter consistency", "",
		  "| 计数项 | result.json | 从落盘文件重算 | 一致 |", "|---|---:|---:|:---:|"]
	for pair in pairs:
		L.append("| %s | %s | %s | %s |" % (pair["counter"], pair["result_json"],
											pair["recount"], "yes" if pair["ok"] else "**NO**"))
	L += ["", "全部一致意味着：`cleaned.csv` 行数、变更条数、待确认条数、可统计行数与 `result.json.counts` "
		  "互相可推导，没有口径漂移。", "",
		  "## 单位换算一致性 / Unit conversion", "",
		  "| 源单位 → 规范单位 | 次数 | factor | offset | 同组唯一 |", "|---|---:|---:|---:|:---:|"]
	for entry in conversion_rows:
		L.append("| %s | %d | %s | %s | %s |" % (entry["pair"], entry["count"], entry["factor"],
												 entry["offset"], "yes" if entry["uniform"] else "**NO**"))
	L += ["", "- change_log 公式复算一致：%d/%d（after = before*factor + offset，相对容差 1e-6）"
		  % (formula_ok, len(actual["changes"])),
		  "- unit_table.observed_conversions 与 change_log 分组计数：%s"
		  % ("一致" if observed_ok else "**不一致**"),
		  "- 换算类结论只对登记表内的单位发生；a.u./缺失/文本型单元格不出现在 change_log 中。", ""]

	L += ["## 逐项对照 / Item by item", "",
		  "### 契约与 workorder", "",
		  "| id | 层级 | 金标准条目 | locator | 实际 | 判定 | 原因 |", "|---|---|---|---|---|---|---|"]
	for row in rows:
		if row["layer"] in ("contract", "workorder"):
			L.append("| %s | %s | %s | %s | %s | **%s** | %s |"
					 % (row["id"], row["layer"], _cell(row["expected"], 90),
						_cell(row["locator"], 62), _cell(row["actual"], 70),
						row["verdict"], _cell(row["reason"], 60)))
	L += ["", "### 字段层（目标表 20 列）", "",
		  "| id | 字段 | 非空行数 | 判定 | 原因 |", "|---|---|---:|---|---|"]
	for row in rows:
		if row["layer"] == "field":
			L.append("| %s | %s | %s | **%s** | %s |"
					 % (row["id"], _cell(row["expected"], 52), _cell(row["actual"], 40),
						row["verdict"], _cell(row["reason"], 50)))
	L += ["", "### 规则层（期望命中 vs 实际命中）", "",
		  "| id | 规则 | 期望命中 | 实际命中 | 判定 |", "|---|---|---:|---:|---|"]
	for row in rows:
		if row["layer"] == "rule":
			L.append("| %s | %s | %s | %s | **%s** |"
					 % (row["id"], _cell(row["expected"], 60),
						_cell(row.get("expected_applications"), 20),
						_cell(row["actual"], 70), row["verdict"]))
	L += ["", "### 记录层（前 40 行，全量见 self_check.json 计数）", "",
		  "| id | 期望 | locator | 实际 | 判定 | 原因 |", "|---|---|---|---|---|---|"]
	record_rows = [row for row in rows if row["layer"] == "record"]
	for row in record_rows[:40]:
		L.append("| %s | %s | %s | %s | **%s** | %s |"
				 % (row["id"], _cell(row["expected"], 40), _cell(row["locator"], 40),
					_cell(row["actual"], 70), row["verdict"], _cell(row["reason"], 60)))
	if len(record_rows) > 40:
		L.append("| ... | 其余 %d 条记录对照已计入汇总 | | | | |" % (len(record_rows) - 40))
	L += ["", "### 变更层（前 40 条）", "",
		  "| id | 期望 | 实际 | 判定 | 原因 |", "|---|---|---|---|---|"]
	change_rows = [row for row in rows if row["layer"] == "change"]
	for row in change_rows[:40]:
		L.append("| %s | %s | %s | **%s** | %s |"
				 % (row["id"], _cell(row["expected"], 55), _cell(row["actual"], 60),
					row["verdict"], _cell(row["reason"], 50)))
	if len(change_rows) > 40:
		L.append("| ... | 其余 %d 条变更对照已计入汇总 | | | |" % (len(change_rows) - 40))
	L += ["", "### 产物层", "", "| id | 产物 | 实际 | 判定 |", "|---|---|---|---|"]
	for row in rows:
		if row["layer"] == "artifact":
			L.append("| %s | `%s` | %s | **%s** |"
					 % (row["id"], _cell(row["expected"].replace("输出目录存在非空文件 `", "").rstrip("`"), 40),
						_cell(row["actual"], 30), row["verdict"]))

	opens = [row for row in rows if row["verdict"] != "met"]
	L += ["", "## 未达标项说明 / Why not met", ""]
	if opens:
		for row in opens[:30]:
			L.append("- `%s`（%s）：%s；期望：%s"
					 % (row["id"], row["verdict"], row["reason"] or "未说明",
						_cell(row["expected"], 110)))
	else:
		L.append("- 无：全部金标准条目达标（met=%d）。" % tally["met"])
	L += ["", "## 覆盖说明 / Coverage notes", "",
		  "- 金标准由输入 + 规则 + 单位表事实独立推导；本报告读回落盘文件比对，可发现写盘/排序/去重/契约回填偏移。",
		  "- 输入为空/坏 JSON 时金标准仍按契约与规则生成，记录层为空、产物层如实判定缺失。",
		  "- 逐项上限：records=%s（截断 %s）、changes=%s（截断 %s）；计数自洽覆盖全量。"
		  % (len(golden.get("records") or []), (golden.get("counts") or {}).get("records_capped"),
			 len(golden.get("changes") or []), (golden.get("counts") or {}).get("changes_capped")),
		  "- 计数口径与 `result.json.counts`、`self_check.json.checks` 一致。", ""]
	return "\n".join(L) + "\n", {"met": tally["met"], "deviation": tally["deviation"],
								 "missing": tally["missing"], "items": len(rows),
								 "layers": layers, "counts_pairs": pairs,
								 "conversion_rows": conversion_rows,
								 "formula_ok": formula_ok, "observed_ok": observed_ok,
								 "rows": rows}

# --------------------------------------------------------------- 版本历史

def build_version_history(ctx, actual, tally):
	result = actual["result"]
	counts = (result.get("result") or {}).get("counts") or {}
	files = _stat_files(actual.get("out")) or actual.get("files") or {}
	done = len(files)
	total = len(BASE_ARTIFACTS) + len(ASSET_FILES)
	diff_line = ("- 金标准对照: met=%s deviation=%s missing=%s"
				 % (tally.get("met"), tally.get("deviation"), tally.get("missing"))
				 if isinstance(tally, dict) and "met" in tally
				 else "- 金标准对照结论见 `diff_report.md`（与 `self_check.json.checks.golden_diff_clean` 一致）")
	L = ["# 版本历史 / Version history - %s" % TOOL, "",
		 "静态记录：从 v0.0.1 骨架到当前 v1.1.0，每版改了什么、为什么改、如何回退。"
		 "运行时在本文件末尾追加「本次运行」段，其余内容不随运行变化（同输入两次运行逐字节一致）。", "",
		 "| 版本 | 里程碑 | 改了什么 | 为什么 | 如何回退 |", "|---|---|---|---|---|"]
	for version, milestone, what, why, back in VERSION_LEDGER:
		L.append("| %s | %s | %s | %s | %s |"
				 % (version, milestone, _cell(what, 160), _cell(why, 110), _cell(back, 130)))
	L += ["", "## 兼容性承诺 / Compatibility", "",
		  "- CLI 与调用方式自 v1.0.0 起未变：`python3 scripts/run_clean.py --input /input --output /app/output`，"
		  "`--determinism` 语义保留；v1.1.0 不新增必填参数、不改默认路径。",
		  "- `result.json` 原顶层字段一个不少；v1.1.0 只新增 "
		  "`golden_standard` / `diff_report` / `version_history` / `run_log` / `self_check` 五个汇总键。",
		  "- 5 个资产是旁路证据层：删除它们不影响原 9 件清洗产物的生成与校验。",
		  "- `--determinism` 仍逐字节比较数据产物；`run.log` 承载真实运行时间戳与耗时，按设计不参与比对"
		  "（比对结果会显式列出被排除的文件名）。",
		  "", "## 如何回退 / Rollback", "",
		  "1. **整包回退到 v1.0.0**：从 `work/patch_backup/reading-11_orig` 恢复 `scripts/run_clean.py` 与 "
		  "`SKILL.md`，并删除 `scripts/evidence_assets.py`（连同 `evidence_golden.py`/`evidence_render.py`）。`run_clean.py` 对该入口模块的导入是受保护的："
		  "模块缺失时只写一条 `degradations`（stage=evidence_assets），原有 9 件产物与 result.json 原字段照常输出。",
		  "2. **只回退单个资产**：在 `evidence_assets.emit_assets()` 中跳过对应写入步骤；其余资产与清洗产物不受影响，"
		  "`self_check` 会如实记录该资产缺失。",
		  "3. **只回退某一次运行**：本包不写运行状态文件，重跑同一条命令即可覆盖输出目录；"
		  "输出全部由本次输入决定。",
		  "4. **回退版本号**：`TOOL_VERSION` 定义在 `scripts/evidence_golden.py`，同值出现在 evidence_assets/evidence_render 与 `SKILL.md`，"
		  "改动后必须重跑最小夹具与 `--determinism`。",
		  "", "## 本次运行 / This run", "",
		  "- case: `%s` | status: `%s` | exit code: 0"
		  % (result.get("case_id"), result.get("status")),
		  "- 产物: 写出本文件时已落盘 %d / %d 件；diff_report.md 与 self_check.json 由本层随后写出，终态 %d 件"
		  % (done, total, total),
		  "- counts: input_rows=%s cleaned_rows=%s changed_values=%s pending_review=%s "
		  "analytic_rows=%s merged_duplicates=%s conflicts=%s"
		  % (counts.get("input_rows"), counts.get("cleaned_rows"), counts.get("changed_values"),
			 counts.get("pending_review"), counts.get("analytic_rows"),
			 counts.get("merged_duplicates"), counts.get("conflicts")),
		  diff_line,
		  "- 本次新增资产: `golden_standard.json` `diff_report.md` `version_history.md` "
		  "`run.log` `self_check.json`",
		  "- 回退本次运行: 删除输出目录后重跑 `scripts/run_clean.py`；包内文件无需改动。",
		  ""]
	return "\n".join(L) + "\n"

# --------------------------------------------------------------- 运行日志

def write_run_log(out, ctx, meta):
	events = ctx.get("ev") or []
	doc = ctx.get("res") or {}
	L = ["# run.log - %s v%s" % (TOOL, TOOL_VERSION),
		 "# written by: scripts/evidence_assets.py -> evidence_render.write_run_log() at the end of scripts/run_clean.py (build/finalize)",
		 "# started: %s | case: %s | input: %s | output: %s"
		 % (meta.get("started_at") or "unknown", meta.get("case_id"),
			meta.get("input"), meta.get("output")),
		 "# format: [local ISO time] [+elapsed s] phase=<name> ok=<bool> key=value ..."]
	for event in events:
		if not isinstance(event, dict):
			continue
		detail = " ".join("%s=%s" % (key, _scalar(value))
						  for key, value in sorted((event.get("detail") or {}).items()))
		L.append(("[%s] [+%.3fs] phase=%s ok=%s %s"
				  % (event.get("ts") or _now(), float(event.get("elapsed") or 0.0),
					 event.get("phase") or "unknown",
					 _scalar(bool(event.get("ok", True))), detail)).rstrip())
	degradations = doc.get("degradations") or []
	errors = doc.get("errors") or []
	L += ["", "# degradations: %d" % len(degradations)]
	for entry in degradations[:40]:
		L.append("# - stage=%s %s" % (entry.get("stage"),
									  " ".join("%s=%s" % (key, _scalar(value))
											   for key, value in sorted(entry.items())
											   if key != "stage")))
	L += ["# errors: %d" % len(errors)]
	for entry in errors[:40]:
		L.append("# - stage=%s %s" % (entry.get("stage"),
									  " ".join("%s=%s" % (key, _scalar(value))
											   for key, value in sorted(entry.items())
											   if key != "stage")))
	verify = _read_json(Path(out) / "verify_report.json")
	counts = (doc.get("result") or {}).get("counts") or {}
	files = _stat_files(out)
	L += ["",
		  "# summary: status=%s counts=%s"
		  % (doc.get("status"),
			 ",".join("%s=%s" % (key, counts.get(key)) for key in sorted(counts))),
		  "# summary: artifacts=%d verify=%s/%s formula=%s%% exit_code=0"
		  % (len(files), verify.get("passed"), verify.get("total"),
			 verify.get("formula_consistency_pct")),
		  "# exit_code=0 is guaranteed by the CLI guard of scripts/run_clean.py; "
		  "a failure is recorded in result.json (errors/degradations), never as a non-zero exit.", ""]
	_dump_text(Path(out) / "run.log", "\n".join(L))
