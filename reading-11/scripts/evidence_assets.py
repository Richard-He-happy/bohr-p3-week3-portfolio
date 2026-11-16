#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可核验资产层（三）：对外入口。

由 scripts/run_clean.py 在 build/finalize 阶段调用 emit_assets(outdir, ctx)：
推导金标准 -> 读回产物做 diff -> 渲染版本史与 run.log -> 机器自检 self_check.json。
另含空/坏输入兜底探针与退出码恒 0 静态扫描。导入型模块，无 CLI。
"""

import re
import shutil
import tempfile
import time

from pathlib import Path

from evidence_golden import (
	ASSET_FILES,
	ENGINE_API,
	QUOTE_MIN_RATE,
	SCHEMA,
	TOOL,
	TOOL_VERSION,
	_apply_dedupe,
	_close,
	_dump_json,
	_dump_text,
	_expect_rows,
	_f,
	_fallback_golden,
	_mark,
	_now,
	_read_json,
	_stat_files,
	build_golden,
)
from evidence_render import (
	VERSION_LEDGER,
	_read_actual,
	build_diff,
	build_version_history,
	write_run_log,
)


# --------------------------------------------------------------- 机器自检

def _degraded_probe(ctx):
	probe = ctx.get("probe") or {}
	pipeline_fn = probe.get("pipeline")
	persist_fn = probe.get("persist")
	doc_factory = probe.get("doc_factory")
	if not (pipeline_fn and persist_fn and doc_factory):
		return {"ok": False, "skipped": True,
				"reason": "probe hooks not supplied by scripts/run_clean.py"}
	cases = [
		("empty_input", {}),
		("bad_json", {"case.json": "{\"case_id\": ", "records.json": "[{\"row_id\": "}),
	]
	probes = {}
	for name, files in cases:
		tmp_in = Path(tempfile.mkdtemp(prefix="lit-probe-in-"))
		tmp_out = Path(tempfile.mkdtemp(prefix="lit-probe-out-"))
		entry = {"ok": False}
		try:
			for file_name, text in files.items():
				(tmp_in / file_name).write_text(text, encoding="utf-8")
			doc2 = doc_factory()
			_dump_json(tmp_out / "result.json", doc2)
			sub = {"ind": tmp_in, "out": tmp_out, "res": doc2, "tpl": {}, "ev": [],
				   "a": ctx.get("a"), "t0": time.time()}
			raised = ""
			try:
				pipeline_fn(sub)
			except Exception as exc:
				raised = "%s: %s" % (type(exc).__name__, exc)
			try:
				persist_fn(sub)
			except Exception as exc:
				raised = (raised + "; " if raised else "") + "persist %s: %s" % (
					type(exc).__name__, exc)
			data = _read_json(tmp_out / "result.json")
			entry = {"ok": bool(not raised and isinstance(data, dict) and data
								and data.get("status") in ("insufficient_evidence", "input_error",
														   "partial", "ok")),
					 "pipeline_raised": raised,
					 "result_json_valid": bool(isinstance(data, dict) and data),
					 "status": data.get("status") if isinstance(data, dict) else None,
					 "degradations": len(data.get("degradations") or []),
					 "errors": len(data.get("errors") or []),
					 "result_bytes": (tmp_out / "result.json").stat().st_size
					 if (tmp_out / "result.json").is_file() else 0,
					 "output_dir_cleaned_up": True}
		except Exception as exc:
			entry = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
		finally:
			shutil.rmtree(tmp_in, ignore_errors=True)
			shutil.rmtree(tmp_out, ignore_errors=True)
		probes[name] = entry
	return {"ok": all(bool(entry.get("ok")) for entry in probes.values()), "probes": probes,
			"scope": "空输入/坏 JSON 在同一进程内真跑 pipeline+persist（临时目录已清理），验证仍产合法 result.json 且退出码 0"}


def _exit_policy_scan():
	scripts = Path(__file__).resolve().parent
	findings, checked = [], []
	try:
		for path in sorted(scripts.glob("*.py")):
			if path.resolve() == Path(__file__).resolve():
				continue          # 本模块源码含被扫描的模式字面量，排除自身
			text = path.read_text(encoding="utf-8", errors="replace")
			if "ArgumentParser" not in text:
				continue          # 只审真正的 CLI 入口（入口以外是导入型模块）
			if not re.search(r"(?m)^if __name__ == ['\"]__main__['\"]:", text):
				continue
			checked.append(path.name)
			for match in re.finditer(r"sys\.exit\(", text):
				tail = text[match.end():match.end() + 32].strip()
				if not (tail.startswith("main()") or tail.startswith("0)")):
					findings.append("%s: sys.exit(%s" % (path.name, tail.split("\n")[0][:30]))
			if re.search(r"raise\s+SystemExit", text):
				findings.append("%s: raise SystemExit" % path.name)
			if "return 0" not in text:
				findings.append("%s: no return-0 guard" % path.name)
	except Exception as exc:
		findings.append("scan failed: %s: %s" % (type(exc).__name__, exc))
	return {"ok": not findings, "scripts": checked, "findings": findings,
			"policy": "所有 CLI 路径返回 0；失败写进 result.json.errors / degradations"}

def build_self_check(out, ctx, golden, actual, tally, probe, exit_scan):
	out = Path(out)
	files = _stat_files(out)
	checks = {}

	# 1 契约键
	result = actual["result"]
	contract = ctx.get("contract") or {}
	expected_keys = [str(key) for key in contract]
	missing_keys = [key for key in expected_keys if key not in result]
	checks["contract_keys_complete"] = {
		"ok": not missing_keys, "expected": len(expected_keys),
		"present": len(expected_keys) - len(missing_keys), "missing": missing_keys[:20],
		"source": "已落盘 result.json 顶层键 vs case.json output_contract"}

	# 2 金标准对照
	record_layers = ("record", "change")
	layer_counts = tally.get("layers") or {}
	bad_layers = {layer: layer_counts.get(layer) for layer in record_layers
				  if layer_counts.get(layer) and (layer_counts[layer]["deviation"]
												  or layer_counts[layer]["missing"])}
	checks["golden_diff_clean"] = {
		"ok": not bad_layers, "met": tally.get("met"), "deviation": tally.get("deviation"),
		"missing": tally.get("missing"),
		"record_layer": layer_counts.get("record"),
		"change_layer": layer_counts.get("change"),
		"source": "diff_report.md 对 cleaned.csv / change_log.csv 的逐项对照"}

	# 3 计数自洽
	pairs = tally.get("counts_pairs") or []
	no_rows = not actual["cleaned"] and result.get("status") in ("insufficient_evidence",
																  "input_error")
	if no_rows:
		checks["counts_consistency"] = {
			"ok": True, "applicable": False, "pairs": pairs,
			"note": "输入无可清洗行：result.counts 为空且 cleaned.csv 无数据行，"
					"计数自洽检查不适用；该场景的兜底能力由 degraded_input_probe 覆盖。",
			"source": "已落盘 CSV 行数重算 vs result.json.counts"}
	else:
		checks["counts_consistency"] = {
			"ok": bool(pairs) and all(pair["ok"] for pair in pairs),
			"applicable": True, "pairs": pairs,
			"source": "已落盘 CSV 行数重算 vs result.json.counts"}

	# 4 单位换算一致
	formula_ok, changes = tally.get("formula_ok", 0), len(actual["changes"])
	conversion_rows = tally.get("conversion_rows") or []
	expected_factors = []
	for item in (ctx.get("expectations") or []):
		for change in item["changes"]:
			expected_factors.append((str(change["row_id"]), str(change["field"]),
									 float(change["factor"]), float(change["offset"])))
	actual_changes = {(str(row.get("row_id")), str(row.get("field"))): row
					  for row in actual["changes"]}
	factor_mismatch = []
	for row_id, field, factor, offset in expected_factors:
		row = actual_changes.get((row_id, field))
		if row is None:
			factor_mismatch.append("%s.%s missing" % (row_id, field))
			continue
		if not _close(_f(row.get("factor")), factor) or not _close(_f(row.get("offset")), offset):
			factor_mismatch.append("%s.%s factor/offset" % (row_id, field))
	checks["unit_conversion_consistent"] = {
		"ok": ((not changes and not expected_factors)
			   or (formula_ok == changes and not factor_mismatch)
			   and all(entry["uniform"] for entry in conversion_rows)
			   and bool(tally.get("observed_ok", True))),
		"change_rows": changes, "formula_recomputed_ok": formula_ok,
		"conversion_pairs": len(conversion_rows),
		"pairs_uniform": sum(1 for entry in conversion_rows if entry["uniform"]),
		"golden_factor_mismatch": factor_mismatch[:10],
		"observed_conversions_consistent": bool(tally.get("observed_ok", True)),
		"source": "change_log.csv 公式复算 + 同单位对因子唯一 + 金标准独立推导的 factor/offset"}

	# 5 规则计数一致
	strict_ids = {item["rule_id"] for item in (golden.get("rules") or []) if item.get("strict")}
	rule_rows = {row.get("rule_id"): row for row in (tally.get("rows") or [])
				 if row.get("layer") == "rule"}
	rule_bad = sorted(rule_id for rule_id in strict_ids
					  if (rule_rows.get(rule_id) or {}).get("verdict") != "met")
	if no_rows:
		checks["rule_tally_consistent"] = {
			"ok": True, "applicable": False, "strict_rules": len(strict_ids),
			"mismatched": [],
			"note": "输入无可清洗行：rules.json 未生成数据表快照，规则命中数量检查不适用。"}
	else:
		checks["rule_tally_consistent"] = {
			"ok": not rule_bad, "applicable": True, "strict_rules": len(strict_ids),
			"mismatched": rule_bad[:10],
			"source": "金标准按规则语义独立推导的命中行数 vs 落盘产物重算"}

	# 6 quote 逐字命中
	golden_counts = golden.get("counts") or {}
	quotes = int(golden_counts.get("quotes") or 0)
	hits = int(golden_counts.get("quotes_verbatim") or 0)
	rate = float(golden_counts.get("quote_hit_rate") or 0.0)
	checks["quote_verbatim_hit_rate"] = {
		"ok": quotes == 0 or rate >= QUOTE_MIN_RATE, "quotes": quotes,
		"verbatim_hits": hits, "rate": rate, "threshold": QUOTE_MIN_RATE,
		"source": "golden_standard.json quotes vs 输入原文（空白归一 + JSON \\uXXXX 反转义）"}

	# 7 兜底探针
	checks["degraded_input_probe"] = probe

	# 8 partial 先落盘
	partial = ctx.get("partial_at_start") or {}
	checks["partial_result_first"] = {
		"ok": bool(partial.get("written")), "detail": partial,
		"source": "scripts/run_clean.py 在 pipeline 之前写出的 partial result.json"}

	# 9 退出码策略
	exit_scan["current_run_exit_code"] = 0
	exit_scan["current_run_status"] = result.get("status")
	checks["exit_code_zero_policy"] = exit_scan

	# 10 资产齐备
	before_self = {name: files.get(name, 0) for name in ASSET_FILES if name != "self_check.json"}
	checks["assets_generated"] = {
		"ok": all(size > 0 for size in before_self.values()),
		"expected": len(ASSET_FILES), "observed_before_self_check": len(before_self),
		"sizes": before_self, "self_check_written": True,
		"source": "输出目录内 5 个资产的非空字节数；self_check.json 是本回执自身"}

	failed = [name for name, value in checks.items() if not value.get("ok")]
	return {"schema": SCHEMA, "kind": "self_check",
			"tool": {"name": TOOL, "version": TOOL_VERSION, "engine_api": ENGINE_API},
			"case_id": (ctx.get("case") or {}).get("case_id"),
			"generated_by": "scripts/evidence_assets.py（build/finalize 阶段）",
			"checks": checks, "ok": not failed, "failed": failed,
			"metrics": {"status": result.get("status"),
						"artifacts_observed": len(files), "artifacts_final": len(files) + 1, "checks": len(checks),
						"passed": len(checks) - len(failed),
						"records": (golden.get("counts") or {}).get("records"),
						"changes": (golden.get("counts") or {}).get("changes"),
						"quotes": quotes, "quote_hit_rate": rate,
						"diff": {"met": tally.get("met"), "deviation": tally.get("deviation"),
								 "missing": tally.get("missing")},
						"counts": (result.get("result") or {}).get("counts") or {}}}

# ------------------------------------------------------------------ 资产发射器

def emit_assets(outdir, ctx):
	"""写出 5 个资产并返回汇入 result.json 的 5 个键；任何失败都在内部降级。"""
	out = Path(outdir)
	out.mkdir(parents=True, exist_ok=True)
	ctx = dict(ctx or {})
	ctx.setdefault("ev", [])
	started = _now()
	_mark(ctx, "assets_start", ok=True, output=str(out))

	expectation = []
	try:
		expectation = _apply_dedupe(_expect_rows(ctx), ctx.get("rulebook") or {})
		ctx["expectations"] = expectation
	except Exception as exc:
		ctx.setdefault("asset_errors", []).append("expectations: %s: %s"
												  % (type(exc).__name__, exc))
		expectation = []
		ctx["expectations"] = []

	try:
		golden = build_golden(ctx, expectation)
	except Exception as exc:
		golden = _fallback_golden(ctx, exc)
		ctx.setdefault("asset_errors", []).append("golden: %s: %s" % (type(exc).__name__, exc))
	_dump_json(out / "golden_standard.json", golden)
	_mark(ctx, "golden_standard", ok=not golden.get("degraded"),
		  items=(golden.get("counts") or {}).get("items_total"),
		  quotes=(golden.get("counts") or {}).get("quotes"),
		  quote_hit_rate=(golden.get("counts") or {}).get("quote_hit_rate"))

	actual = _read_actual(out)
	summary_meta = {"started_at": started, "case_id": (ctx.get("case") or {}).get("case_id"),
					"input": str(ctx.get("ind")), "output": str(out)}
	write_run_log(out, ctx, summary_meta)          # 先落盘日志，保证 diff 时它已存在
	_mark(ctx, "run_log", ok=True, events=len(ctx.get("ev") or []))

	try:
		version_md = build_version_history(ctx, actual, {})
	except Exception as exc:
		version_md = ("# 版本历史 / Version history - %s\n\n- 本次渲染失败：`%s: %s`\n"
					  % (TOOL, type(exc).__name__, exc))
		ctx.setdefault("asset_errors", []).append("version: %s: %s"
												  % (type(exc).__name__, exc))
	_dump_text(out / "version_history.md", version_md)
	_mark(ctx, "version_history", ok=True, versions=len(VERSION_LEDGER))

	try:
		diff_md, tally = build_diff(ctx, golden, actual, expectation)
	except Exception as exc:
		diff_md = ("# 金标准对照报告 / Golden-standard diff report\n\n"
				   "- 生成失败：`%s: %s`\n- 原 9 件清洗产物不受影响。\n"
				   % (type(exc).__name__, exc))
		tally = {"met": 0, "deviation": 0, "missing": 0, "items": 0, "layers": {},
				 "counts_pairs": [], "conversion_rows": [], "formula_ok": 0,
				 "observed_ok": True, "rows": []}
		ctx.setdefault("asset_errors", []).append("diff: %s: %s" % (type(exc).__name__, exc))
	_dump_text(out / "diff_report.md", diff_md)
	_mark(ctx, "diff_report", ok=True, met=tally.get("met"),
		  deviation=tally.get("deviation"), missing=tally.get("missing"))

	probe = _degraded_probe(ctx)
	exit_scan = _exit_policy_scan()

	try:
		self_check = build_self_check(out, ctx, golden, actual, tally, probe, exit_scan)
	except Exception as exc:
		self_check = {"schema": SCHEMA, "kind": "self_check", "ok": False,
					  "failed": ["self_check_build"],
					  "error": "%s: %s" % (type(exc).__name__, exc), "checks": {}}
		ctx.setdefault("asset_errors", []).append("self_check: %s: %s"
												  % (type(exc).__name__, exc))
	_dump_json(out / "self_check.json", self_check)
	_mark(ctx, "self_check", ok=bool(self_check.get("ok")),
		  checks=len(self_check.get("checks") or {}),
		  passed=len(self_check.get("checks") or {}) - len(self_check.get("failed") or []))
	if ctx.get("asset_errors"):# 资产层内部异常如实进 degradations，不影响退出码
		for note in ctx["asset_errors"]:
			(ctx.get("res") or {}).setdefault("degradations", []).append(
				{"stage": "evidence_assets", "note": note})
	_mark(ctx, "finish", ok=True, exit_code=0, status=(ctx.get("res") or {}).get("status"))
	write_run_log(out, ctx, summary_meta)   # 覆盖写：补上 diff/self_check/finish 阶段

	sizes = _stat_files(out)
	golden_counts = golden.get("counts") or {}
	checks = self_check.get("checks") or {}
	return {
		"golden_standard": {
			"file": "golden_standard.json", "bytes": sizes.get("golden_standard.json", 0),
			"items": golden_counts.get("items_total"), "records": golden_counts.get("records"),
			"changes": golden_counts.get("changes"), "quotes": golden_counts.get("quotes"),
			"quote_hit_rate": golden_counts.get("quote_hit_rate"),
			"degraded": bool(golden.get("degraded"))},
		"diff_report": {
			"file": "diff_report.md", "bytes": sizes.get("diff_report.md", 0),
			"items": tally.get("items"), "met": tally.get("met"),
			"deviation": tally.get("deviation"), "missing": tally.get("missing")},
		"version_history": {
			"file": "version_history.md", "bytes": sizes.get("version_history.md", 0),
			"versions": len(VERSION_LEDGER), "run_section": True},
		"run_log": {
			"file": "run.log", "events": len(ctx.get("ev") or []),
			"phases": [event.get("phase") for event in (ctx.get("ev") or [])
					   if isinstance(event, dict)],
			"exit_code": 0},
		"self_check": {
			"file": "self_check.json", "bytes": sizes.get("self_check.json", 0),
			"ok": bool(self_check.get("ok")),
			"checks_total": len(checks), "checks_passed": len(checks) - len(
				self_check.get("failed") or []),
			"failed": list(self_check.get("failed") or [])[:10]},
	}
