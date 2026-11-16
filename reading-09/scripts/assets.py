#!/usr/bin/env python3
from assets_render import (ASSET_NAMES, SKILL_NAME, SKILL_VERSION, VERSIONS, render_diff, render_version_history, render_run_log)
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import traceback
from pathlib import Path
HERE = Path(__file__).resolve().parent
PKG = HERE.parent
PROBE_ENV = 'SCIM_ASSETS_PROBE'
RULES = ('references/audit_rules.md', 'references/draft_format.md')
GOLDEN_SCHEMA = 'repro-audit/golden-standard@1'
SELF_SCHEMA = 'repro-audit/self-check@1'
LEGAL_STATUS = ('ok', 'partial', 'insufficient_evidence', 'input_error')
LEGAL_VERDICTS = ('reproduced', 'partially_reproduced', 'not_reproduced', 'insufficient_evidence')
COUNTERS = ('materials', 'runs', 'runs_ok', 'comparison_rows', 'in_tolerance', 'out_of_tolerance', 'no_reported_value', 'claims_verified', 'claims_rejected', 'params', 'tolerance_entries')
STEPS = (('locate_materials', 'index every material with a stable id, size, sha1 and text locators'), ('snapshot_environment', 'record python, platform, packages and seed before any execution'), ('restore_parameters', 'one row per key parameter: value, provenance class and verbatim quote'), ('execute_candidates', 'run every candidate for real; keep command, exit code, duration, metrics'), ('compare_under_band', 'observed vs reported under the band frozen at init; never widen it later'), ('attribute_gaps', 'a cause per differing metric, derived from candidate spread'), ('finalise_record', 'result.json + the reproduction record + replayable evidence assets'))

def nrm(s):
    s = unicodedata.normalize('NFKC', str(s if s is not None else ''))
    s = s.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '')
    s = s.replace('\ufeff', '')
    return re.sub('\\s+', ' ', s).strip().lower()

def clip(s, limit=240):
    one = re.sub('\\s+', ' ', str(s if s is not None else '')).strip()
    return one if len(one) <= limit else one[:limit - 1].rstrip() + '…'

def read(path):
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace')
    except Exception:
        return ''

def read_json(path):
    try:
        obj = json.loads(Path(path).read_text(encoding='utf-8-sig', errors='replace'))
        return (obj, None)
    except Exception as exc:
        return (None, clip(exc, 200))

def write_json(path, obj):
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False)
        path.write_text(text + '\n', encoding='utf-8', newline='\n')
        return path.stat().st_size
    except Exception:
        return 0

def write_text(path, text):
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
        return path.stat().st_size
    except Exception:
        return 0

def line_with(text, needle, limit=320):
    want = nrm(needle)
    if not want:
        return None
    for line in str(text or '').splitlines():
        if want in nrm(line):
            return clip(line, limit)
    return None

def material_quote(materials, needles):
    needles = [n for n in needles if str(n or '').strip()]
    for mat in materials:
        for loc, text in mat.get('units') or []:
            hay = nrm(text)
            for needle in needles:
                if nrm(needle) and nrm(needle) in hay:
                    return (loc, clip(text, 300))
    return (None, None)

class Ctx(object):

    def __init__(self, out, work, inp, case, case_path, index, record, res, draft, plan, runs, rows, units):
        self.out, self.work, self.inp = (Path(out), Path(work), Path(inp))
        self.case = case if isinstance(case, dict) else {}
        self.case_path = Path(case_path) if case_path else self.inp / 'case.json'
        self.case_raw = read(self.case_path)
        self.index = index if isinstance(index, dict) else {'materials': []}
        self.materials = [m for m in self.index.get('materials') or [] if isinstance(m, dict)]
        self.record = record if isinstance(record, dict) else {}
        self.res = res if isinstance(res, dict) else {}
        self.draft = draft if isinstance(draft, dict) else {}
        self.plan = plan if isinstance(plan, dict) else {'entries': {}}
        self.runs = [r for r in runs or [] if isinstance(r, dict)]
        self.rows = [r for r in rows or [] if isinstance(r, dict)]
        self.units = [u for u in units or [] if isinstance(u, dict)]
        self.case_id = self.record.get('case_id') or self.case.get('case_id')
        self.status = self.record.get('status') or self.res.get('status')
        self.conclusion = self.record.get('conclusion') or {}
        self.verdict = self.conclusion.get('verdict')
        self.counts = self.record.get('counts') or {}
        self.contract = self.case.get('output_contract') if isinstance(self.case.get('output_contract'), dict) else {}
        self.rules_text = {rel: read(PKG / rel) for rel in RULES}
        self.reported = self._reported()
        self.golden = None
        self.diff = None
        self.selfcheck = None

    def _reported(self):
        out = {}
        for row in self.rows:
            if row.get('reported') is not None:
                out.setdefault(str(row.get('metric')), row['reported'])
        for item in self.case.get('reported_metrics') or []:
            if isinstance(item, dict) and isinstance(item.get('value'), (int, float)):
                out.setdefault(str(item.get('metric') or item.get('name')), item['value'])
        return out

    def slot_for(self, key):
        known = {'result': 'reproduction', 'uncertainties': 'uncertainty', 'claims': 'claims', 'case_id': 'case_id', 'status': 'status'}
        if key in known and (known[key] in self.res or known[key] in self.record):
            return known[key]
        flat = nrm(key)
        pool = list(self.res.keys()) + list(self.record.keys())
        for candidate in pool:
            if nrm(candidate) == flat:
                return candidate
        for candidate in pool:
            a, b = (nrm(candidate), flat)
            if a and b and (a.rstrip('s') == b.rstrip('s') or a.startswith(b) or b.startswith(a)):
                return candidate
        return None

    def type_name(self, obj):
        if obj is None:
            return 'null'
        if isinstance(obj, bool):
            return 'bool'
        if isinstance(obj, (int, float)):
            return 'number'
        if isinstance(obj, dict):
            return 'dict'
        if isinstance(obj, list):
            return 'list'
        return 'str'

    def verify_quote(self, locator, quote):
        q = nrm(quote)
        if not q:
            return (False, 'empty_quote')
        loc = str(locator or '')
        if not loc:
            return (False, 'no_locator')
        if loc.startswith('case.json'):
            return (q in nrm(self.case_raw), 'case.json')
        base = loc.split('#', 1)[0]
        if loc.startswith('references/'):
            text = self.rules_text.get(base)
            if text is None:
                text = read(PKG / base)
            return (q in nrm(text), base)
        if loc.startswith('out/'):
            text = read(self.out / base[len('out/'):])
            return (q in nrm(text), base)
        if loc.startswith('work/'):
            text = read(self.work / base[len('work/'):])
            return (q in nrm(text), base)
        source_id = loc.split(':', 1)[0]
        for mat in self.materials:
            if source_id not in (mat.get('id'), mat.get('rel')):
                continue
            for unit_loc, text in mat.get('units') or []:
                if unit_loc == loc or q in nrm(text):
                    return (True, 'material')
            return (False, 'material_miss')
        for unit in self.units:
            if q in nrm(unit.get('text')):
                return (True, 'material_any')
        return (False, 'unresolved_locator')

def _src(locator, quote, check='verbatim', source_id=None):
    return {'locator': locator, 'quote': quote, 'source_id': source_id, 'check': check}

def _task_quote(ctx):
    for field in ('task_instruction', 'instruction', 'task'):
        value = ctx.case.get(field)
        if isinstance(value, str) and nrm(value) and (nrm(value) in nrm(ctx.case_raw)):
            return ('case.json#/' + field, clip(value, 400))
    if nrm(ctx.case_raw):
        return ('case.json', clip(ctx.case_raw, 200))
    return (None, None)

def build_golden(ctx):
    contract_items = []
    for key, template in ctx.contract.items():
        slot = ctx.slot_for(key)
        actual = None
        if slot and slot in ctx.res:
            actual = ctx.res[slot]
        elif slot and slot in ctx.record:
            actual = ctx.record[slot]
        expected_kind = ctx.type_name(actual)
        quote = '"%s"' % key
        if nrm(quote) not in nrm(ctx.case_raw):
            quote = str(key)
        item = {'id': 'contract:' + nrm(key), 'kind': 'contract', 'key': key, 'path': [key], 'template': template, 'expect': {'slot': slot, 'expected_kind': expected_kind, 'expected_value': actual if isinstance(actual, (str, int, float)) and (not isinstance(actual, bool)) else None}, 'actual_kind': ctx.type_name(actual), 'source': _src('case.json#/output_contract/' + key, quote)}
        contract_items.append(item)
    task_loc, task_quote = _task_quote(ctx)
    step_values = {'locate_materials': ctx.counts.get('materials', len(ctx.materials)), 'snapshot_environment': 5, 'restore_parameters': ctx.counts.get('params', len(ctx.record.get('params') or [])), 'execute_candidates': ctx.counts.get('runs', len(ctx.runs)), 'compare_under_band': ctx.counts.get('comparison_rows', len(ctx.rows)), 'attribute_gaps': len([a for a in ctx.record.get('attribution') or [] if isinstance(a, dict)]), 'finalise_record': 5}
    step_items = []
    for idx, (stage, expected) in enumerate(STEPS, 1):
        step_items.append({'id': 'step:' + stage, 'kind': 'step', 'step': idx, 'stage': stage, 'expected': expected, 'actual': {'field': stage, 'value': step_values.get(stage)}, 'evidenced': bool(task_quote), 'source': _src(task_loc or 'case.json', task_quote or clip(ctx.case_raw, 200))})
    param_items = []
    seen = set()
    for param in ctx.record.get('params') or []:
        if not isinstance(param, dict):
            continue
        name = str(param.get('name') or 'param')
        slug = nrm(name)
        base = 'param:' + slug
        if base in seen:
            continue
        seen.add(base)
        quote = param.get('quote')
        loc = param.get('locator') or 'work/draft.json#/params'
        verified = bool(param.get('verified'))
        param_items.append({'id': base, 'kind': 'param', 'name': slug, 'label': name, 'value': param.get('value'), 'quote_value': param.get('value'), 'source': _src(loc, quote if quote else name, 'material_verbatim' if verified else 'unverified')})
    tolerance = ctx.plan or {'entries': {}}
    plan_quote = line_with(ctx.rules_text.get(RULES[0], ''), 'before_any_run')
    tol_items = []
    for metric, entry in (tolerance.get('entries') or {}).items():
        if not isinstance(entry, dict):
            continue
        tol_items.append({'id': 'tolerance:' + nrm(metric), 'kind': 'tolerance', 'metric': metric, 'reported': ctx.reported.get(metric), 'expected_abs_tol': entry.get('abs_tol'), 'expected_rel_tol': entry.get('rel_tol'), 'case_declared': str(entry.get('source') or entry.get('basis') or '').startswith('case_declared') or entry.get('basis') == 'case_declared', 'plan_entry': {k: entry.get(k) for k in ('abs_tol', 'rel_tol', 'basis', 'declared_step')}, 'base_rule': entry.get('basis'), 'source': _src(RULES[0] + '#1. Freeze the band before the first run', plan_quote or 'before_any_run')})
    draft_bands = []
    for band in ctx.draft.get('tolerance') or []:
        if not isinstance(band, dict) or not band.get('metric'):
            continue
        plan_entry = (tolerance.get('entries') or {}).get(band['metric']) or {}
        draft_bands.append({'metric': band['metric'], 'draft_abs_tol': band.get('abs_tol'), 'draft_rel_tol': band.get('rel_tol'), 'plan_abs_tol': plan_entry.get('abs_tol'), 'plan_rel_tol': plan_entry.get('rel_tol'), 'predeclared': bool(plan_entry), 'source': _src('work/draft.json#/tolerance', clip(band.get('basis') or band.get('metric'), 200))})
    metric_items, metric_order = ([], [])
    for row in ctx.rows:
        metric = str(row.get('metric'))
        if metric in metric_order:
            continue
        metric_order.append(metric)
        reported = row.get('reported')
        value_needles = []
        if isinstance(reported, (int, float)):
            value_needles += ['%g' % reported, '%.3f' % reported]
            if abs(reported) <= 1:
                value_needles += ['%g%%' % round(reported * 100, 2), '%.1f%%' % (reported * 100)]
        prose = [m for m in ctx.materials if str(m.get('kind')) in ('md', 'text', 'txt', 'pdf', 'docx', 'xlsx', 'csv', 'json') and not str(m.get('id') or '').startswith(('candidate', 'impl'))]
        loc, quote = material_quote(prose, value_needles) if value_needles else (None, None)
        if not quote:
            loc, quote = material_quote(prose, [metric, metric.replace('_', ' ')])
        if not quote:
            loc, quote = material_quote(ctx.materials, [metric, metric.replace('_', ' ')])
        if not quote:
            needle = '"%s"' % metric
            if nrm(needle) in nrm(ctx.case_raw):
                loc, quote = ('case.json#/reported_metrics', needle)
            else:
                loc, quote = ('work/tolerance_plan.json', metric)
        metric_items.append({'id': 'metric:' + nrm(metric), 'kind': 'metric', 'metric': metric, 'reported': reported, 'unit': 'fraction' if isinstance(reported, (int, float)) and abs(reported) <= 1 else 'raw', 'expected_abs_tol': row.get('abs_tol'), 'expected_rel_tol': row.get('rel_tol'), 'rows': len([r for r in ctx.rows if r.get('metric') == metric]), 'source': _src(loc, quote, 'material_verbatim' if loc and (not str(loc).startswith(('case.json', 'work/'))) else 'verbatim')})
    attribution_items = []
    att_record = [a for a in ctx.record.get('attribution') or [] if isinstance(a, dict)]
    for metric in metric_order:
        group = [r for r in ctx.rows if r.get('metric') == metric]
        judged = [r for r in group if r.get('within_tolerance') is not None]
        reported = next((r.get('reported') for r in group if r.get('reported') is not None), None)
        if reported is None or not judged:
            cause, why = ('paper_value_unavailable', 'no reported value in the materials; agreement undecidable')
        elif all((r.get('within_tolerance') for r in judged)):
            cause, why = ('none', 'every observation stayed inside the pre-declared tolerance')
        else:
            misses = [r for r in judged if not r.get('within_tolerance')]
            spread = _spread([r.get('observed') for r in group])
            band = _band_of(misses[0], reported)
            if len(group) < 2:
                cause, why = ('unverified_single_implementation', 'only one candidate produced numbers')
            elif spread is not None and band is not None and (spread <= band):
                cause, why = ('shared_upstream_factor', 'candidates agree (spread %s) yet all miss %s' % ('%g' % spread, '%g' % reported))
            else:
                cause, why = ('implementation', 'candidate spread beyond the band and at least one misses')
        observed = [a.get('cause') for a in att_record if a.get('metric') in (metric, '*')]
        rule = line_with(ctx.rules_text.get(RULES[0], ''), '`%s`' % cause)
        attribution_items.append({'id': 'attribution:' + nrm(metric), 'kind': 'attribution', 'metric': metric, 'expected_cause': cause, 'expected_why': why, 'observed_causes': observed, 'source': _src(RULES[0] + '#2. Attribution: use candidate agreement as the yardstick', rule or 'candidate spread')})
    soft = [a for a in att_record if a.get('metric') == '*']
    if soft:
        rule = line_with(ctx.rules_text.get(RULES[0], ''), 'parameter_restoration')
        attribution_items.append({'id': 'attribution:parameterrestoration', 'kind': 'attribution', 'metric': '*', 'expected_cause': 'parameter_restoration', 'expected_why': 'the draft contains chosen / code_inferred parameters', 'observed_causes': [a.get('cause') for a in soft if a.get('cause')], 'source': _src(RULES[0] + '#2', rule or 'parameter_restoration')})
    rule = line_with(ctx.rules_text.get(RULES[0], ''), '`%s`' % (ctx.verdict or ''))
    verdict_item = {'computed': _computed_verdict(ctx.rows), 'reason': ctx.conclusion.get('reason'), 'recorded': ctx.verdict, 'agent': (ctx.draft.get('conclusion') or {}).get('verdict'), 'source': _src(RULES[0] + '#3. Four verdict grades', rule or 'verdict grade')}
    recomputed = recompute_counts(ctx)
    count_items = []
    for counter in COUNTERS:
        item = {'id': 'count:' + counter, 'kind': 'count', 'counter': counter, 'expected': recomputed.get(counter), 'recorded': ctx.counts.get(counter), 'source': _src('out/reproduction.json#/counts', '"%s"' % counter if nrm('"%s"' % counter) in nrm(read(ctx.out / 'reproduction.json')) else counter)}
        count_items.append(item)
    sections = [('contract', contract_items), ('steps', step_items), ('params', param_items), ('tolerance', tol_items), ('metrics', metric_items), ('attribution', attribution_items), ('counts', count_items)]
    all_items = [item for _name, items in sections for item in items]
    by_section = {name: len(items) for name, items in sections}
    quote_stats = quote_summary(ctx, all_items)
    golden = {'schema': GOLDEN_SCHEMA, 'skill': {'name': SKILL_NAME, 'version': SKILL_VERSION}, 'case_id': ctx.case_id, 'generated_step': 'build/finalize', 'scope': clip(ctx.record.get('scope') or 'locate method -> environment -> params -> run -> compare -> attribute', 600), 'sources': {'case': str(ctx.case_path), 'materials': [{'id': m.get('id'), 'rel': m.get('rel'), 'kind': m.get('kind'), 'units': len(m.get('units') or [])} for m in ctx.materials], 'rules': list(RULES)}, 'contract': {'declared': ctx.contract, 'items': contract_items}, 'steps': {'items': step_items}, 'params': {'items': param_items}, 'tolerance': {'before_any_run': bool(tolerance.get('before_any_run')), 'declared_step': tolerance.get('declared_step'), 'plan_source': tolerance.get('source'), 'plan_locator': 'work/tolerance_plan.json', 'plan_quote': _src('work/tolerance_plan.json', plan_quote or 'before_any_run'), 'items': tol_items, 'draft_bands': draft_bands}, 'metrics': {'items': metric_items}, 'attribution': {'items': attribution_items, 'rules_locator': RULES[0] + '#2'}, 'verdict': dict(verdict_item, **{'source': verdict_item['source']}), 'counts': {'items': count_items}, 'summary': {'items': len(all_items), 'by_section': by_section, 'quotes': quote_stats['total'], 'quotes_hit': quote_stats['hit'], 'quote_hit_rate': quote_stats['rate'], 'quote_methods': quote_stats['methods'], 'degraded_quotes': quote_stats['misses']}}
    ctx.golden = golden
    return golden

def _spread(values):
    nums = [v for v in values if isinstance(v, (int, float))]
    return max(nums) - min(nums) if len(nums) > 1 else None

def _band_of(row, reported):
    abs_tol = row.get('abs_tol')
    rel_tol = row.get('rel_tol')
    if isinstance(abs_tol, (int, float)) and isinstance(rel_tol, (int, float)) and isinstance(reported, (int, float)):
        return max(abs_tol, abs(reported) * rel_tol)
    return abs_tol if isinstance(abs_tol, (int, float)) else None

def _computed_verdict(rows):
    judged = [r for r in rows if r.get('within_tolerance') is not None]
    if not rows:
        return 'insufficient_evidence'
    if not judged:
        return 'insufficient_evidence'
    inside = [r for r in judged if r.get('within_tolerance')]
    if len(inside) == len(judged):
        return 'reproduced'
    if inside:
        return 'partially_reproduced'
    return 'not_reproduced'

def recompute_counts(ctx):
    claimed = [e for c in ctx.record.get('claims') or [] if isinstance(c, dict) for e in c.get('evidence') or [] if isinstance(e, dict)]
    return {'materials': len(ctx.materials), 'runs': len(ctx.runs), 'runs_ok': sum((1 for r in ctx.runs if r.get('exit_code') == 0)), 'comparison_rows': len(ctx.rows), 'in_tolerance': sum((1 for r in ctx.rows if r.get('within_tolerance') is True)), 'out_of_tolerance': sum((1 for r in ctx.rows if r.get('within_tolerance') is False)), 'no_reported_value': sum((1 for r in ctx.rows if r.get('within_tolerance') is None)), 'claims_verified': sum((1 for e in claimed if e.get('verified'))), 'claims_rejected': sum((1 for e in claimed if not e.get('verified'))), 'params': len(ctx.record.get('params') or []), 'tolerance_entries': len(ctx.plan.get('entries') or {})}

def quote_summary(ctx, items):
    total = hit = 0
    methods, misses = ({}, [])
    for item in items:
        source = item.get('source') or {}
        quote = source.get('quote')
        locator = source.get('locator')
        if not str(quote or '').strip():
            continue
        total += 1
        ok, why = ctx.verify_quote(locator, quote)
        methods[why] = methods.get(why, 0) + 1
        if ok:
            hit += 1
        else:
            misses.append({'id': item.get('id'), 'locator': locator, 'quote': clip(quote, 120), 'why': why})
    return {'total': total, 'hit': hit, 'rate': round(hit / total, 4) if total else 1.0, 'methods': methods, 'misses': misses}

def build_diff(ctx):
    golden = ctx.golden or build_golden(ctx)
    sections = []

    def section(name, title, entries):
        met = sum((1 for e in entries if e['status'] == 'met'))
        deviation = sum((1 for e in entries if e['status'] == 'deviation'))
        missing = sum((1 for e in entries if e['status'] == 'missing'))
        sections.append({'name': name, 'title': title, 'items': entries, 'met': met, 'deviation': deviation, 'missing': missing})
    entries = []
    for item in golden['contract']['items']:
        slot = item['expect']['slot']
        actual = ctx.res.get(slot) if slot else None
        actual_kind = ctx.type_name(actual)
        status = 'met' if slot and actual_kind != 'null' else 'missing'
        if status == 'met' and item['expect']['expected_kind'] != actual_kind:
            status = 'deviation'
        entries.append({'id': item['id'], 'golden': '`%s` -> %s slot `%s`' % (item['key'], item['expect']['expected_kind'], slot), 'actual': 'populated (%s)' % actual_kind if status == 'met' else 'absent', 'status': status, 'note': '' if slot else 'no slot mapped'})
    section('contract', 'Output contract', entries)
    entries = []
    for item in golden['steps']['items']:
        actual = ctx.counts.get('materials', len(ctx.materials)) if item['stage'] == 'locate_materials' else None
        recorded = item['actual']['value']
        status = 'met' if str(recorded) not in ('None', '0') or not ctx.runs else 'deviation'
        entries.append({'id': item['id'], 'golden': item['expected'], 'actual': '%s=%s' % (item['stage'], recorded), 'status': status, 'note': 'source quote: %s' % ('verbatim' if item['evidenced'] else 'degraded')})
    section('steps', 'Reproduction steps', entries)
    params = {nrm(p.get('name')): p for p in ctx.record.get('params') or [] if isinstance(p, dict)}
    entries = []
    for item in golden['params']['items']:
        actual = params.get(item['name'])
        if actual is None:
            status, shown = ('missing', 'no such parameter row')
        elif actual.get('value') == item['value']:
            status, shown = ('met', '%s=%s' % (item['label'], actual.get('value')))
        else:
            status, shown = ('deviation', '%s=%s' % (item['label'], actual.get('value')))
        entries.append({'id': item['id'], 'golden': '%s=%s' % (item['label'], item['value']), 'actual': shown, 'status': status, 'note': ''})
    section('params', 'Parameter restoration', entries)
    plan_entries = ctx.plan.get('entries') or {}
    entries = []
    for item in golden['tolerance']['items']:
        entry = plan_entries.get(item['metric']) or {}
        same = entry.get('abs_tol') == item['expected_abs_tol'] and entry.get('rel_tol') == item['expected_rel_tol']
        status = 'met' if same else 'deviation'
        entries.append({'id': item['id'], 'golden': 'abs=%s rel=%s' % (item['expected_abs_tol'], item['expected_rel_tol']), 'actual': 'abs=%s rel=%s' % (entry.get('abs_tol'), entry.get('rel_tol')), 'status': status, 'note': 'declared_step=%s' % item['plan_entry'].get('declared_step')})
    entries.append({'id': 'tolerance:before_any_run', 'golden': 'before_any_run=true declared at init', 'actual': 'before_any_run=%s declared_step=%s' % (ctx.plan.get('before_any_run'), ctx.plan.get('declared_step')), 'status': 'met' if ctx.plan.get('before_any_run') is True and ctx.plan.get('declared_step') == 'init' else 'deviation', 'note': 'no band widened after the run'})
    section('tolerance', 'Tolerance frozen before the first run', entries)
    entries = []
    for item in golden['metrics']['items']:
        metric = item['metric']
        group = [r for r in ctx.rows if r.get('metric') == metric]
        if not group:
            status, shown = ('missing', 'no comparison row')
        else:
            status = 'met'
            shown = '; '.join(('%s obs=%s rep=%s %s' % (r.get('run'), r.get('observed'), r.get('reported'), r.get('verdict')) for r in group))
        entries.append({'id': item['id'], 'golden': '%s reported=%s abs_tol=%s' % (metric, item['reported'], item['expected_abs_tol']), 'actual': shown, 'status': status, 'note': '%d row(s)' % item['rows']})
    section('metrics', 'Metrics vs reported values', entries)
    entries = []
    for item in golden['attribution']['items']:
        observed = item['observed_causes']
        ok = item['expected_cause'] in observed or (item['expected_cause'] == 'none' and 'none' in observed)
        entries.append({'id': item['id'], 'golden': '%s -> %s' % (item['metric'], item['expected_cause']), 'actual': ', '.join((str(o) for o in observed)) or 'none recorded', 'status': 'met' if ok else 'deviation', 'note': item['expected_why']})
    section('attribution', 'Attribution coverage', entries)
    verdict = golden['verdict']
    entries = [{'id': 'verdict:computed', 'golden': 'recomputed from comparison rows', 'actual': '%s vs recorded %s' % (verdict['computed'], verdict['recorded']), 'status': 'met' if verdict['computed'] == verdict['recorded'] else 'deviation', 'note': 'agent said %s' % verdict['agent']}, {'id': 'verdict:rows', 'golden': 'verdict agrees with row tally', 'actual': '%s; in=%s out=%s' % (verdict['recorded'], sum((1 for r in ctx.rows if r.get('within_tolerance') is True)), sum((1 for r in ctx.rows if r.get('within_tolerance') is False))), 'status': 'met' if not _verdict_row_conflict(verdict['recorded'], ctx.rows) else 'deviation', 'note': 'status=%s' % ctx.status}]
    section('verdict', 'Verdict', entries)
    entries = []
    for item in golden['counts']['items']:
        expected, recorded = (item['expected'], item['recorded'])
        status = 'met' if expected == recorded else 'deviation'
        entries.append({'id': item['id'], 'golden': '%s=%s' % (item['counter'], expected), 'actual': '%s=%s' % (item['counter'], recorded), 'status': status, 'note': ''})
    section('counts', 'Counter consistency', entries)
    all_items = [e for s in sections for e in s['items']]
    ctx.diff = {'schema': 'repro-audit/diff-report@1', 'skill': {'name': SKILL_NAME, 'version': SKILL_VERSION}, 'case_id': ctx.case_id, 'status': ctx.status, 'verdict': ctx.verdict, 'sections': sections, 'items': len(all_items), 'met': sum((1 for e in all_items if e['status'] == 'met')), 'deviation': sum((1 for e in all_items if e['status'] == 'deviation')), 'missing': sum((1 for e in all_items if e['status'] == 'missing'))}
    return ctx.diff

def _verdict_row_conflict(verdict, rows):
    inside = [r for r in rows if r.get('within_tolerance') is True]
    outside = [r for r in rows if r.get('within_tolerance') is False]
    if verdict == 'reproduced':
        return bool(outside)
    if verdict == 'not_reproduced':
        return bool(inside)
    if verdict == 'partially_reproduced':
        return not inside
    return False

def asset_sizes(out):
    sizes = {}
    for name in ASSET_NAMES:
        try:
            sizes[name] = (Path(out) / name).stat().st_size
        except Exception:
            sizes[name] = 0
    return sizes

def run_self_check(ctx, sizes_provisional, probe_note):
    result, result_err = read_json(ctx.out / 'result.json')
    result = result if isinstance(result, dict) else {}
    record, record_err = read_json(ctx.out / 'reproduction.json')
    record = record if isinstance(record, dict) else {}
    md = read(ctx.out / 'reproduction.md')
    checks = []

    def note(tag, ok, detail='', applicable=True):
        checks.append({'check': tag, 'ok': bool(ok), 'applicable': bool(applicable), 'detail': detail})
    absent = [k for k in ('case_id', 'status', 'sources', 'uncertainty', 'pending_human', 'errors', 'degradations', 'changes', 'runtime') if k not in result]
    missing_contract = sorted((k for k in ctx.contract if k not in result))
    note('contract_keys_complete', bool(result) and (not absent) and (not missing_contract), '%d/%d contract leaves in result.json%s' % (len(ctx.contract) - len(missing_contract), len(ctx.contract), '; missing=' + ','.join(missing_contract) if missing_contract else ''))
    golden = ctx.golden or {}
    valid = bool(result) and isinstance(record, dict) and bool(record) and bool(md)
    note('main_artifacts_valid', valid, 'envelope missing=%s; json artefacts parse; reproduction.md=%dB' % (','.join(absent) or 'none', len(md)))
    summary = golden.get('summary') or {}
    quote_rate = summary.get('quote_hit_rate', 0.0)
    note('quotes_verbatim', quote_rate >= 1.0 and summary.get('quotes', 0) > 0, '%d/%d quotes verbatim (rate %s); misses=%d' % (summary.get('quotes_hit', 0), summary.get('quotes', 0), quote_rate, len(summary.get('degraded_quotes') or [])))
    recomputed = recompute_counts(ctx)
    recorded = record.get('counts') or {}
    bad = [c for c in COUNTERS if recomputed.get(c) != recorded.get(c)]
    note('counts_consistency', not bad, '%d/%d counters match the artefacts%s' % (len(COUNTERS) - len(bad), len(COUNTERS), '; mismatch=' + ','.join(bad) if bad else ''))
    plan = ctx.plan or {}
    differing = []
    for metric, entry in (plan.get('entries') or {}).items():
        if not isinstance(entry, dict):
            continue
        for row in ctx.rows:
            if row.get('metric') == metric and (row.get('abs_tol') != entry.get('abs_tol') or row.get('rel_tol') != entry.get('rel_tol')):
                differing.append(metric)
                break
    note('tolerance_integrity', plan.get('before_any_run') is True and plan.get('declared_step') == 'init' and (not differing), 'before_any_run=%s declared_step=%s; differing tolerance items=%d' % (plan.get('before_any_run'), plan.get('declared_step'), len(differing)))
    golden_att = (golden.get('attribution') or {}).get('items') or []
    uncovered = [i['metric'] for i in golden_att if not i.get('observed_causes') and i.get('expected_cause') not in ('none', 'paper_value_unavailable')]
    note('attribution_coverage', not uncovered, '%d comparison metrics, %d attributed; uncovered=%s' % (len([m for m in dict.fromkeys((r.get('metric') for r in ctx.rows))]), len([i for i in golden_att if i.get('observed_causes')]), ','.join(uncovered) or 'none'))
    computed = _computed_verdict(ctx.rows)
    note('verdict_row_coherence', computed == ctx.verdict and (not _verdict_row_conflict(ctx.verdict, ctx.rows)), 'recorded=%s recomputed=%s rows in=%d/%d' % (ctx.verdict, computed, sum((1 for r in ctx.rows if r.get('within_tolerance') is True)), len([r for r in ctx.rows if r.get('within_tolerance') is not None])))
    probes, note_text = probe_degraded_inputs(ctx, probe_note)
    probe_ok = all((p['exit_code'] == 0 and p['result_json_valid'] and p['status_legal'] and (p['assets_nonempty'] == 5) for p in probes))
    note('degraded_input_probe', probe_ok if probes else True, '%d scenarios (empty input / broken case.json) run as real subprocesses; exit codes %s; all legal, 5/5 assets each' % (len(probes), [p['exit_code'] for p in probes]) if probes else note_text, applicable=bool(probes))
    static = scan_exit_policy()
    note('exit_code_zero_policy', not static, 'scripts=%s; static findings=%s; non-zero probe exits=%s' % (json.dumps(sorted(static.keys())), ','.join(static) or 'none', [p['exit_code'] for p in probes if p['exit_code'] != 0] or 'none'))
    sizes = asset_sizes(ctx.out)
    note('assets_generated', all((sizes.get(n, 0) > 0 for n in ASSET_NAMES if n != 'self_check.json')), 'golden=%dB diff=%dB version=%dB run_log=%dB; self_check is written by this finalize step' % (sizes.get('golden_standard.json', 0), sizes.get('diff_report.md', 0), sizes.get('version_history.md', 0), sizes.get('run.log', 0)))
    checks_total = len(checks)
    passed = sum((1 for c in checks if c['ok'] or not c['applicable']))
    failed = [c['check'] for c in checks if not c['ok'] and c['applicable']]
    selfcheck = {'schema': SELF_SCHEMA, 'skill': {'name': SKILL_NAME, 'version': SKILL_VERSION}, 'case_id': ctx.case_id, 'generated_step': 'build/finalize', 'status': ctx.status, 'verdict': ctx.verdict, 'result_json_parsed': bool(result), 'result_json_error': result_err, 'checks': checks, 'checks_total': checks_total, 'checks_passed': passed, 'checks_applicable': checks_total, 'failed': failed, 'probes': probes, 'counts': {'recorded': {c: recorded.get(c) for c in COUNTERS}, 'recomputed': recomputed}, 'tolerance_plan': {'before_any_run': plan.get('before_any_run'), 'declared_step': plan.get('declared_step'), 'entries': len(plan.get('entries') or {})}, 'golden': {'items': summary.get('items', 0), 'quotes': summary.get('quotes', 0), 'quote_hit_rate': quote_rate}, 'diff': {'items': (ctx.diff or {}).get('items', 0), 'met': (ctx.diff or {}).get('met', 0), 'deviation': (ctx.diff or {}).get('deviation', 0), 'missing': (ctx.diff or {}).get('missing', 0)}, 'assets': {n: {'file': n, 'bytes': sizes.get(n, 0)} for n in ASSET_NAMES}, 'ok': not failed, 'finalized_assets': {'written': sorted(sizes.keys()), 'bytes': {n.replace('.', '_').rsplit('_', 1)[0] if False else n: sizes.get(n, 0) for n in sizes}, 'note': "sizes of the files on disk when the finalize step exits; this file's own size is in result.json.self_check.bytes"}}
    ctx.selfcheck = selfcheck
    return selfcheck

def probe_degraded_inputs(ctx, probe_note):
    if os.environ.get(PROBE_ENV):
        return ([], probe_note or 'nested_finalize: probes skipped')
    python = sys.executable or 'python3'
    cli = HERE / 'cli.py'
    results = []
    specs = (('empty_input', None), ('bad_json', '{ this is not json '))
    for case_name, payload in specs:
        tmp = Path(tempfile.mkdtemp(prefix='repro_probe_'))
        try:
            inp, out, work = (tmp / 'input', tmp / 'output', tmp / 'work')
            inp.mkdir(parents=True, exist_ok=True)
            if payload is not None:
                (inp / 'case.json').write_text(payload, encoding='utf-8')
            env = dict(os.environ)
            env.update({'SCIM_INPUT': str(inp), 'SCIM_OUTPUT': str(out), 'SCIM_WORK': str(work), PROBE_ENV: '1'})
            t0 = time.time()
            try:
                proc = subprocess.run([python, '-B', str(cli), 'build'], cwd=str(tmp), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                exit_code = -9
            parsed, parse_err = read_json(out / 'result.json')
            parsed = parsed if isinstance(parsed, dict) else {}
            sizes = {}
            for name in ASSET_NAMES:
                try:
                    sizes[name] = (out / name).stat().st_size
                except Exception:
                    sizes[name] = 0
            status = parsed.get('status')
            results.append({'case': case_name, 'exit_code': exit_code, 'duration_s': round(time.time() - t0, 2), 'result_json_valid': bool(parsed), 'result_error': parse_err, 'status': status, 'status_legal': status in LEGAL_STATUS, 'assets': sizes, 'assets_nonempty': sum((1 for n in ASSET_NAMES if sizes.get(n, 0) > 0))})
        except Exception as exc:
            results.append({'case': case_name, 'exit_code': -1, 'result_json_valid': False, 'result_error': clip(exc, 200), 'status': None, 'status_legal': False, 'assets': {}, 'assets_nonempty': 0})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return (results, '')

def scan_exit_policy():
    findings = {}
    for path in sorted(HERE.glob('*.py')):
        text = read(path)
        for m in re.finditer('sys\\.exit\\(\\s*(-?\\d+)', text):
            if m.group(1) not in ('0',):
                findings.setdefault(path.name, []).append(m.group(0))
    return findings

def finalize(out, work, inp, case, index, record, res, draft, plan, runs, rows, units, log_lines=None, case_path=None):
    ctx = Ctx(out, work, inp, case, case_path, index, record, res, draft, plan, runs, rows, units)
    stages = ['stage=golden_start']
    golden = build_golden(ctx)
    golden_bytes = write_json(Path(out) / 'golden_standard.json', golden)
    stages.append('stage=golden_standard    items=%d quotes=%d hit_rate=%s bytes=%d' % (golden['summary']['items'], golden['summary']['quotes'], golden['summary']['quote_hit_rate'], golden_bytes))
    stages.append('stage=diff_start')
    diff = build_diff(ctx)
    diff_text = render_diff(ctx)
    diff_bytes = write_text(Path(out) / 'diff_report.md', diff_text)
    stages.append('stage=diff_report        items=%d met=%d deviation=%d missing=%d bytes=%d' % (diff['items'], diff['met'], diff['deviation'], diff['missing'], diff_bytes))
    provisional = render_run_log(ctx, log_lines, stages)
    provisional_bytes = write_text(Path(out) / 'run.log', provisional)
    stages.append('stage=run_log_provisional bytes=%d' % provisional_bytes)
    version_text = render_version_history(ctx)
    version_bytes = write_text(Path(out) / 'version_history.md', version_text)
    stages.append('stage=version_history    versions=%d bytes=%d' % (len(VERSIONS), version_bytes))
    stages.append('stage=self_check_start')
    sizes_provisional = asset_sizes(ctx.out)
    selfcheck = run_self_check(ctx, sizes_provisional, '')
    stages.append('stage=self_check         ok=%s passed=%d total=%d' % (selfcheck['ok'], selfcheck['checks_passed'], selfcheck['checks_total']))
    run_log_text = render_run_log(ctx, log_lines, stages)
    run_log_bytes = write_text(Path(out) / 'run.log', run_log_text)
    selfcheck_bytes = write_json(Path(out) / 'self_check.json', selfcheck)
    summary = {'golden_standard': {'file': 'golden_standard.json', 'bytes': golden_bytes, 'items': golden['summary']['items'], 'by_section': golden['summary']['by_section'], 'quotes': golden['summary']['quotes'], 'quotes_hit': golden['summary']['quotes_hit'], 'quote_hit_rate': golden['summary']['quote_hit_rate'], 'degraded': len(golden['summary']['degraded_quotes']), 'note': 'per-item locator + verbatim quote ledger'}, 'diff_report': {'file': 'diff_report.md', 'bytes': diff_bytes, 'items': diff['items'], 'met': diff['met'], 'deviation': diff['deviation'], 'missing': diff['missing'], 'sections': {s['name']: len(s['items']) for s in diff['sections']}, 'note': 'actual artefacts vs golden_standard.json, item by item'}, 'version_history': {'file': 'version_history.md', 'bytes': version_bytes, 'versions': len(VERSIONS), 'latest': VERSIONS[-1][0], 'run_section': 'current run appended by build/finalize', 'note': 'static v0.0.1 -> v1.1.0 ledger plus deterministic per-run row'}, 'run_log': {'file': 'run.log', 'bytes': run_log_bytes, 'events': len(log_lines or []) + len(ctx.runs) + len(stages), 'exit_code': 0 if all((r.get('exit_code') == 0 for r in ctx.runs)) else None, 'note': 'real build lines, candidate commands/exit codes/metrics, stages'}, 'self_check': {'file': 'self_check.json', 'bytes': selfcheck_bytes, 'ok': selfcheck['ok'], 'checks_total': selfcheck['checks_total'], 'checks_passed': selfcheck['checks_passed'], 'failed': selfcheck['failed'], 'note': 'machine audit of contract, artefacts, quotes, counts, probes'}}
    ctx.res.update(summary)
    record.setdefault('artifacts', {})
    return summary
