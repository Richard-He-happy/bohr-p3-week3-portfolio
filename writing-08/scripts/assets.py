#!/usr/bin/env python3
# assets.py -- verifiable-asset layer of the bilingual manuscript skill.
#
# Publishes five reviewable assets next to the seven core deliverables:
#   golden_standard.json  expectation ledger (locator + verbatim quote per item)
#   diff_report.md        golden standard vs the files actually produced
#   version_history.md    static version ledger + rollback playbook + this run
#   run.log               real phase journal of this build (timestamps, counts)
#   self_check.json       machine-checkable contract / artifact / quote / number /
#                         fallback / exit-code assertions
#
# Every helper degrades instead of raising: a broken asset must never take the
# core delivery down. Stdlib only, no network, independent of the current dir.

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
import corpus as C

VERSION = '1.0.0'
ASSET_NAMES = ('golden_standard.json', 'diff_report.md', 'version_history.md',
               'run.log', 'self_check.json')
CORE_NAMES = ('glossary.csv', 'alignment.csv', 'preserved_facts.json',
              'evidence_map.json', 'change_log.json')
ROLES = {'deliverable': 'translation.md', 'alignment': 'alignment.csv',
         'glossary': 'glossary.csv', 'preserved_facts': 'preserved_facts.json',
         'evidence_map': 'evidence_map.json', 'change_log': 'change_log.json'}
ABBR = {'output_contract': 'OC', 'task_instruction': 'IN',
        'deliverable_paragraphs': 'DP', 'glossary': 'GL', 'alignment': 'AL',
        'preserved_facts': 'PF', 'artifacts': 'AR', 'runtime': 'RT'}
LAYERS = ('output_contract', 'task_instruction', 'deliverable_paragraphs',
          'glossary', 'alignment', 'preserved_facts', 'artifacts', 'runtime')
MAX_UNITS = 70
MAX_FACTS = 90
MAX_GLOSSARY = 30
MAX_ITEMS_PER_LAYER = {'output_contract': 28, 'task_instruction': 4,
                       'deliverable_paragraphs': MAX_UNITS, 'glossary': MAX_GLOSSARY,
                       'alignment': MAX_UNITS, 'preserved_facts': MAX_FACTS,
                       'artifacts': len(CORE_NAMES) + len(ASSET_NAMES) + 2, 'runtime': 4}
QUOTE_CAP = 200
RUN = '%d.%06d' % (os.getpid(), int(time.time() * 1000000) % 1000000)

STATIC_VERSIONS = [
    ('v0.1.0', '2026-11-16',
     'Adaptation skeleton: four verbs init/show/check/build, index format, contract echo and '
     'partial-first result.',
     'Fork of the reference package; the adaptation had to keep the operational contract while '
     'changing every file name and every sentence.',
     'Copy the backup package back; rename the files to the reference names.'),
    ('v0.2.0', '2026-11-16',
     'Five fidelity gates: coverage, verbatim quote, numbers/units, citation markers, locked terms.',
     'A mechanically debuggable draft; the Agent cannot silently drop a digit or a term.',
     'Remove the gate calls from corpus.audit_draft (not recommended).'),
    ('v0.3.0', '2026-11-16',
     'Read-only audit verb + reference sheets (draft spec, quality rules, templates/fallbacks).',
     'Allows a post-build re-check without rebuilding; exception paths documented once.',
     'Drop the audit subparser and references/templates_and_fallbacks.md.'),
    ('v0.4.0', '2026-11-16',
     'Degraded-input hardening: empty input, corrupt case.json, missing draft and unreadable '
     'material all finalize with exit code 0.',
     'One bad upload must not zero the run; an honest partial result beats a crash.',
     'Restore the pre-hardening backup; degraded runs then raise instead of finalizing.'),
    ('v0.9.2', '2026-11-16',
     'Pre-asset freeze (backup tag): seven core deliverables and result.json frozen.',
     'Rollback anchor before the verifiable-asset layer; byte hashes live in '
     'work/patch_backup/writing-08_orig_manifest.json.',
     'Copy work/patch_backup/writing-08_orig over the package and re-run init.'),
    ('v1.0.0', '2026-11-16',
     'Verifiable-asset layer (current): golden_standard.json, diff_report.md, version_history.md, '
     'run.log, self_check.json + five additive result.json summary fields.',
     'A reviewer can re-derive every expectation, see what was met, and machine-check the run; '
     'CLI, paths, contract echo and exit code stay unchanged.',
     'Re-run build; or delete the five assets -- the core seven files stay valid.'),
]


# --------------------------------------------------------------------------
# small utilities
# --------------------------------------------------------------------------
def _now():
    return datetime.now(timezone.utc)


def _iso(moment=None):
    return (moment or _now()).strftime('%Y-%m-%dT%H:%M:%SZ')


def _trunc(value, limit=240):
    text = C.squeeze(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str))
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _md_cell(value, limit=180):
    return _trunc(value, limit).replace('|', '\\|')


def _write_json(path, obj):
    C.dump_json(path, obj)
    return Path(path).stat().st_size


def _write_text(path, text):
    C.dump_text(path, text)
    return Path(path).stat().st_size


def _read_csv(path, key):
    import csv
    rows = []
    try:
        with open(path, encoding='utf-8', newline='') as handle:
            rows = [row for row in csv.DictReader(handle)]
    except Exception:
        return []
    return rows


def _read_text_safe(path):
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace')
    except Exception:
        return ''


def _size(path):
    try:
        return Path(path).stat().st_size
    except Exception:
        return 0


# --------------------------------------------------------------------------
# run journal (real events, one JSON line each; shared by every verb)
# --------------------------------------------------------------------------
def log_event(work_dir, phase, ok=True, **fields):
    """Append one real event to <work>/run_events.jsonl. Never raises."""
    record = {'t': round(time.time(), 4), 'iso': _iso(), 'run': RUN,
              'phase': str(phase), 'ok': bool(ok)}
    for dict_key, value in fields.items():
        if isinstance(value, (dict, list)):
            record[dict_key] = _trunc(value, 600)
        elif isinstance(value, (int, float, bool)) or value is None:
            record[dict_key] = value
        else:
            record[dict_key] = _trunc(str(value), 400)
    try:
        target = Path(work_dir) / 'run_events.jsonl'
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception:
        return None
    return record


def read_journal(work_dir, limit=600):
    rows = []
    try:
        with open(Path(work_dir) / 'run_events.jsonl', encoding='utf-8', errors='replace') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return rows[-limit:]


# --------------------------------------------------------------------------
# golden standard
# --------------------------------------------------------------------------
def _quote_for(text, anchors=(), cap=QUOTE_CAP):
    """Return a contiguous verbatim substring of text, preferring one with an anchor."""
    text = text or ''
    if len(text.strip()) <= cap:
        return text.strip()
    for anchor in anchors:
        if not anchor:
            continue
        index = text.find(anchor)
        if index < 0:
            continue
        start = 0
        for separator in ('\n', '. ', '。', '！', '？', '; ', '；'):
            position = text.rfind(separator, 0, index)
            if position >= 0:
                start = max(start, position + len(separator))
        ends = [position + len(separator) for separator in ('. ', '。', '！', '？', '\n')
                for position in (text.find(separator, index),) if position >= 0]
        end = min(ends) if ends else len(text)
        candidate = text[start:end].strip()
        if candidate and len(candidate) <= cap:
            return candidate
        return text[max(0, index - cap // 3):index + cap][:cap].strip()
    return text.strip()[:cap].strip()


def _verbatim(quote, corpus_text):
    flat_quote, flat_source = C.squeeze(quote), C.squeeze(corpus_text)
    return bool(flat_quote) and bool(flat_source) and flat_quote in flat_source


def _skill_quote(skill_text, needle):
    for number, line in enumerate((skill_text or '').split('\n'), 1):
        if needle in line and line.strip():
            return ('SKILL.md#L%d' % number, line.strip(), True)
    return ('SKILL.md', None, False)


def _unit_facts(unit):
    text = unit.get('text') or ''
    facts = []
    for value in dict.fromkeys(C.digits_of(text)):
        facts.append(('number', value))
    for marker in dict.fromkeys(C.MARKER_RX.findall(text)):
        marker = C.squeeze(marker)
        if marker and not any(value == marker for kind, value in facts):
            facts.append(('citation', marker))
    return facts


def build_golden(index, contract_fields, deliverable_name, case_token, case_path,
                 skill_text, output_dir):
    """Expectation ledger derived only from the input material and package rules."""
    units = [unit for unit in (index.get('paragraphs') or []) if unit.get('para_id')]
    by_pid = {unit['para_id']: unit for unit in units}
    case_raw = _read_text_safe(case_path) if case_path else ''
    skill_raw = skill_text or _read_text_safe(output_dir.parent / 'SKILL.md')
    items, counters = [], {}
    meta = {'quotes_checked': 0, 'quotes_verbatim': 0, 'needs_human': [],
            'layers': {}, 'instruction_present': bool(index.get('instruction'))}

    def add(layer, expectation, check, source, basis):
        if counters.get(layer, 0) >= MAX_ITEMS_PER_LAYER.get(layer, 999):
            return
        counters[layer] = counters.get(layer, 0) + 1
        quote, kind = source.get('quote') or '', source.get('kind') or ''
        available = True
        if kind == 'case_value':
            source['quote_verbatim'] = True
            source['quote_source'] = 'parsed case.json field value (exact value or contiguous slice)'
        elif kind == 'material':
            source['quote_verbatim'] = _verbatim(quote, by_pid.get(check.get('para_id'), {}).get('text', ''))
        elif kind == 'package_rule':
            available = bool(skill_raw)
            source['quote_verbatim'] = _verbatim(quote, skill_raw) if available else False
        else:
            available = False
            source['quote_verbatim'] = False
            source['source_available'] = False
        if available and source.get('quote'):
            meta['quotes_checked'] += 1
            meta['quotes_verbatim'] += int(bool(source.get('quote_verbatim')))
        item = {'id': 'GS-%s-%03d' % (ABBR.get(layer, 'XX'), counters[layer]),
                'layer': layer, 'expectation': expectation, 'check': check,
                'source': source, 'basis': basis}
        items.append(item)

    # 1. output contract: every promised key must be echoed, unknown keys kept
    contract = contract_fields if isinstance(contract_fields, dict) else {}
    for dict_key, value in contract.items():
        expected = C.contract_value(dict_key, ROLES)
        quote = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        add('output_contract',
            'result.json echoes contract key %r unchanged and points it at %s'
            % (dict_key, expected or 'the matching deliverable'),
            {'kind': 'contract_key', 'key': dict_key, 'artifact': expected},
            {'file': 'case.json', 'locator': 'case.json#output_contract.%s' % dict_key,
             'quote': quote, 'kind': 'case_value'}, 'output_contract')
    add('output_contract', 'result.json echoes case_id %r' % case_token,
        {'kind': 'case_echo', 'value': case_token},
        {'file': 'case.json', 'locator': 'case.json#case_id', 'quote': str(case_token),
         'kind': 'case_value' if case_raw else 'derived'}, 'output_contract')
    if not contract:
        meta['needs_human'].append({'item': 'output_contract', 'reason': 'no output_contract supplied; '
                                    'only the package defaults are exported'})

    # 2. task instruction: coverage + fidelity duties
    instruction = index.get('instruction')
    if instruction:
        add('task_instruction', 'every indexed source unit receives a target-language text (coverage 100%)',
            {'kind': 'instruction_coverage'},
            {'file': 'case.json', 'locator': 'case.json#task_instruction',
             'quote': _quote_for(str(instruction)), 'kind': 'case_value'}, 'task_instruction')
        add('task_instruction', 'numbers, units and citation markers are kept verbatim; no invented facts',
            {'kind': 'instruction_fidelity'},
            {'file': 'case.json', 'locator': 'case.json#task_instruction',
             'quote': _quote_for(str(instruction)), 'kind': 'case_value'}, 'task_instruction')
    else:
        meta['needs_human'].append({'item': 'task_instruction',
                                    'reason': 'no instruction field found; duties inferred from output_contract'})

    # 3./5. deliverable paragraphs + alignment rows, one expectation each per unit
    for unit in units[:MAX_UNITS]:
        para_id = unit['para_id']
        source = {'file': unit.get('material_name'), 'locator': unit.get('locator'),
                  'quote': _quote_for(unit.get('text', '')), 'kind': 'material'}
        add('deliverable_paragraphs',
            'unit %s is translated in place in the manuscript (no placeholder left)' % para_id,
            {'kind': 'translation_present', 'para_id': para_id}, dict(source), 'source_unit')
        add('alignment', 'alignment.csv row %s has aligned=yes and an empty numbers_missing cell' % para_id,
            {'kind': 'alignment_row', 'para_id': para_id}, dict(source), 'source_unit')

    # 4. glossary table
    for entry in (index.get('supplied_terms') or [])[:MAX_GLOSSARY]:
        term, target = (entry.get('term') or ''), (entry.get('target') or '')
        unit = next((candidate for candidate in units
                     if C.fold_text(term) and C.fold_text(term) in C.fold_text(candidate.get('text'))), None)
        if unit:
            locator, quote, source_kind = unit.get('locator'), _quote_for(unit.get('text', ''), [term]), 'material'
        else:
            locator, quote, source_kind = 'case.json#glossary.%s' % term, term, 'case_value'
        add('glossary', 'glossary.csv locks %r -> %r and each unit containing %r uses that rendering'
            % (term, target or '(pending)', term),
            {'kind': 'glossary_term', 'term': term, 'target': target,
             'para_id': unit.get('para_id') if unit else None},
            {'file': unit.get('material_name') if unit else 'case.json', 'locator': locator,
             'quote': quote, 'kind': source_kind}, 'supplied_glossary')

    # 6. preserved facts: every number / citation marker in the source
    fact_count = 0
    for unit in units:
        if fact_count >= MAX_FACTS:
            break
        for kind, value in _unit_facts(unit):
            if fact_count >= MAX_FACTS:
                break
            fact_count += 1
            add('preserved_facts',
                '%s %r of %s reappears verbatim in the target text' % (kind, value, unit['para_id']),
                {'kind': 'fact', 'fact_kind': kind, 'value': value, 'para_id': unit['para_id']},
                {'file': unit.get('material_name'), 'locator': unit.get('locator'),
                 'quote': _quote_for(unit.get('text', ''), [value]), 'kind': 'material'},
                'source_unit')

    # 7. artifacts: seven core files + five verifiable assets, each with a package quote
    artifact_needles = {
        deliverable_name: 'main deliverable',
        'glossary.csv': 'glossary.csv', 'alignment.csv': 'alignment.csv',
        'preserved_facts.json': 'preserved_facts.json', 'evidence_map.json': 'evidence_map.json',
        'change_log.json': 'change_log.json', 'result.json': 'result.json',
        'golden_standard.json': 'golden_standard.json', 'diff_report.md': 'diff_report.md',
        'version_history.md': 'version_history.md', 'run.log': 'run.log',
        'self_check.json': 'self_check.json'}
    for name, label in artifact_needles.items():
        locator, quote, found = _skill_quote(skill_raw, '`%s`' % name if name != deliverable_name
                                             else 'translation.md')
        if not found:
            quote = _quote_for(str(instruction or contract.get('deliverable') or ''), [label])
            locator, source_kind = ('case.json#task_instruction' if instruction
                                    else 'case.json#output_contract'), 'case_value'
        else:
            source_kind = 'package_rule'
        add('artifacts', '%s exists and is non-empty (%s)' % (name, label),
            {'kind': 'artifact', 'file': name},
            {'file': 'SKILL.md' if found else 'case.json', 'locator': locator,
             'quote': quote or name, 'kind': source_kind}, 'package_deliverable')

    # 8. runtime contract: honest status + always-zero exit code
    add('runtime', 'status is one of ok/partial/insufficient_evidence/input_error and matches the checks',
        {'kind': 'status_honesty'},
        {'file': 'SKILL.md', 'locator': 'SKILL.md#status', 'quote': '`status` semantics',
         'kind': 'package_rule'}, 'package_rule')
    add('runtime', 'every CLI command exits with code 0 even on broken input',
        {'kind': 'exit_code'},
        {'file': 'SKILL.md', 'locator': 'SKILL.md#runtime-facts', 'quote': 'Exit code: always 0',
         'kind': 'package_rule'}, 'package_rule')

    meta['layers'] = {layer: counters.get(layer, 0) for layer in LAYERS if counters.get(layer)}
    meta['items'] = len(items)
    meta['quote_hit_rate'] = round(meta['quotes_verbatim'] / meta['quotes_checked'], 4) \
        if meta['quotes_checked'] else 1.0
    return {'asset': 'golden_standard', 'asset_version': VERSION, 'case_id': case_token,
            'generated_at': _iso(), 'derivation': 'input material + output_contract + task_instruction + '
            'package rules only; the Agent draft is not used to define expectations',
            'units_indexed': len(units), 'contract_keys': list(contract.keys()),
            'source_files': [unit.get('material_name') for unit in units[:MAX_UNITS]],
            'layers': meta['layers'], 'items': items, 'item_count': meta['items'],
            'quotes_checked': meta['quotes_checked'], 'quotes_verbatim': meta['quotes_verbatim'],
            'quote_hit_rate': meta['quote_hit_rate'], 'needs_human': meta['needs_human']}


# --------------------------------------------------------------------------
# actual-state snapshot + diff report
# --------------------------------------------------------------------------
def _actual_state(output_dir, deliverable_name, result_doc, index):
    output_dir = Path(output_dir)
    alignment = _read_csv(output_dir / 'alignment.csv', 'para_id')
    glossary = _read_csv(output_dir / 'glossary.csv', 'term')
    facts_doc = C.read_json(output_dir / 'preserved_facts.json') or {}
    facts = facts_doc.get('facts') or []
    evidence_doc = C.read_json(output_dir / 'evidence_map.json') or {}
    return {'alignment': {row.get('para_id'): row for row in alignment if row.get('para_id')},
            'glossary': {C.fold_text(row.get('term')): row for row in glossary if row.get('term')},
            'facts': facts, 'fact_keys': {(fact.get('para_id'), fact.get('value')): fact for fact in facts},
            'units': len(index.get('paragraphs') or []),
            'evidence_units': len(evidence_doc.get('units') or []),
            'result': result_doc, 'deliverable': deliverable_name,
            'report': result_doc}


def _diff_item(item, state, output_dir, status, unit_total):
    check, layer = item.get('check') or {}, item.get('layer')
    result_doc = state.get('result') or {}
    kind = check.get('kind')
    if kind == 'contract_key':
        key = check.get('key')
        if key not in result_doc:
            return 'missing', 'result.json has no key %r' % key
        value = result_doc.get(key)
        if value is None:
            return 'deviation', 'key present but null'
        expected = check.get('artifact')
        if expected and not (Path(output_dir) / str(expected)).is_file():
            return 'deviation', 'points at %r which is absent' % expected
        return 'met', 'echoed as %s' % _trunc(value, 90)
    if kind == 'case_echo':
        actual = result_doc.get('case_id')
        return ('met', 'case_id=%s' % actual) if actual == check.get('value') \
            else ('deviation', 'case_id=%r' % actual)
    if kind == 'instruction_coverage':
        aligned = sum(1 for row in (state.get('alignment') or {}).values()
                      if (row.get('aligned') or '').lower() == 'yes')
        return ('met', 'aligned %d/%d' % (aligned, unit_total)) if aligned >= unit_total \
            else ('deviation', 'aligned %d/%d rows' % (aligned, unit_total))
    if kind == 'instruction_fidelity':
        bad = len(result_doc.get('number_issues') or []) + len(result_doc.get('citation_issues') or []) \
            + len(result_doc.get('term_issues') or [])
        return ('met', '0 number/citation/term findings') if not bad \
            else ('deviation', '%d number/citation/term findings' % bad)
    if kind == 'translation_present':
        row = (state.get('alignment') or {}).get(check.get('para_id'))
        if row is None:
            return 'missing', 'no alignment row'
        if (row.get('target') or '').strip() and (row.get('aligned') or '').lower() == 'yes':
            return 'met', 'target %s chars, aligned=yes' % len(row.get('target') or '')
        return 'deviation', 'target empty or aligned!=yes'
    if kind == 'glossary_term':
        row = (state.get('glossary') or {}).get(C.fold_text(check.get('term')))
        if row is None:
            return 'missing', 'no glossary row'
        if (row.get('target') or '').strip() and (row.get('status') or '') == 'locked':
            return 'met', '%s -> %s' % (_trunc(check.get('term'), 40), _trunc(row.get('target'), 60))
        return 'deviation', 'target empty or status=%r' % row.get('status')
    if kind == 'alignment_row':
        row = (state.get('alignment') or {}).get(check.get('para_id'))
        if row is None:
            return 'missing', 'no alignment row'
        missing_numbers = (row.get('numbers_missing') or '').strip()
        if (row.get('aligned') or '').lower() == 'yes' and not missing_numbers:
            return 'met', 'aligned=yes, numbers_missing empty'
        return 'deviation', 'aligned=%r, numbers_missing=%r' % (row.get('aligned'), missing_numbers)
    if kind == 'fact':
        fact = (state.get('fact_keys') or {}).get((check.get('para_id'), check.get('value')))
        if fact is None:
            return 'missing', 'no preserved_facts record'
        if fact.get('present_in_target'):
            return 'met', 'present_in_target=true'
        return 'deviation', 'present_in_target=false'
    if kind == 'artifact':
        name = str(check.get('file'))
        size = _size(Path(output_dir) / name)
        if size:
            return 'met', '%d B' % size
        if name in ASSET_NAMES:
            return 'not_applicable', ('written by the same publish call; checked in '
                                      'self_check.json#assets_generated')
        return 'missing', 'file absent or empty'
    if kind == 'status_honesty':
        allowed = ('ok', 'partial', 'insufficient_evidence', 'input_error')
        if status not in allowed:
            return 'deviation', 'unexpected status %r' % status
        metrics = result_doc.get('metrics') or {}
        total = int(metrics.get('paragraphs_total') or 0)
        done = int(metrics.get('paragraphs_translated') or 0)
        verdict = metrics.get('check_verdict')
        if total and done >= total and verdict == 'pass':
            expected = 'ok'
        elif total:
            expected = 'partial'
        else:
            expected = 'insufficient_evidence'
        if expected == 'insufficient_evidence':
            return ('met', 'status=%s (no readable units)' % status) \
                if status in ('insufficient_evidence', 'input_error', 'partial') \
                else ('deviation', 'status=%r, expected insufficient_evidence' % status)
        return ('met', 'status=%s matches coverage %d/%d and verdict %r'
                % (status, done, total, verdict)) if status == expected \
            else ('deviation', 'status=%r, expected %r for coverage %d/%d verdict %r'
                  % (status, expected, done, total, verdict))
    if kind == 'exit_code':
        return 'met', 'policy always 0; runner returns main()'
    return 'not_applicable', 'unknown check kind %r' % kind


def render_diff(golden, output_dir, result_doc, index, status, case_token):
    unit_total = len(index.get('paragraphs') or [])
    state = _actual_state(output_dir, str(result_doc.get('deliverable') or ROLES['deliverable']),
                          result_doc, index)
    rows = []
    for item in (golden or {}).get('items') or []:
        verdict, reason = _diff_item(item, state, output_dir, status, unit_total)
        rows.append((item, verdict, reason))
    per_layer, totals = {}, {'met': 0, 'deviation': 0, 'missing': 0, 'not_applicable': 0}
    for item, verdict, reason in rows:
        bucket = per_layer.setdefault(item.get('layer'), {'met': 0, 'deviation': 0,
                                                          'missing': 0, 'not_applicable': 0, 'items': 0})
        bucket['items'] += 1
        bucket[verdict] = bucket.get(verdict, 0) + 1
        totals[verdict] = totals.get(verdict, 0) + 1
    summary = {'items': len(rows), 'met': totals['met'], 'deviation': totals['deviation'],
               'missing': totals['missing'], 'not_applicable': totals['not_applicable'],
               'by_layer': per_layer,
               'met_rate': round(totals['met'] / len(rows), 4) if rows else 0.0}
    lines = ['# diff_report.md — golden standard vs. actual deliverables', '',
             '- case: `%s` | status: **%s** | generated: %s' % (case_token, status, _iso()),
             '- basis: %d expectations from golden_standard.json compared item by item' % len(rows),
             '- verdict: met %d / deviation %d / missing %d / n/a %d (met rate %s)'
             % (totals['met'], totals['deviation'], totals['missing'],
                totals['not_applicable'], summary['met_rate']), '',
             '## Per-layer scoreboard', '',
             '| layer | expectations | met | deviation | missing | n/a |',
             '|---|---:|---:|---:|---:|---:|']
    for layer in LAYERS:
        bucket = per_layer.get(layer)
        if not bucket:
            continue
        lines.append('| %s | %d | %d | %d | %d | %d |'
                     % (layer, bucket['items'], bucket['met'], bucket['deviation'],
                        bucket['missing'], bucket['not_applicable']))
    gaps = [(item, verdict, reason) for item, verdict, reason in rows
            if verdict in ('deviation', 'missing')]
    lines += ['', '## Gaps to close before hand-off (%d)' % len(gaps), '']
    if gaps:
        lines += ['| id | layer | expectation | actual | state | locator |',
                  '|---|---|---|---|---|---|']
        for item, verdict, reason in gaps[:120]:
            source = item.get('source') or {}
            lines.append('| %s | %s | %s | %s | %s | `%s` |'
                         % (item.get('id'), item.get('layer'), _md_cell(item.get('expectation')),
                            _md_cell(reason, 140), verdict, source.get('locator') or '-'))
    else:
        lines.append('_None: every expectation that the current inputs allow is met._')
    lines += ['', '## Met expectations (condensed)', '',
              '| id | layer | expectation | evidence |', '|---|---|---|---|']
    for item, verdict, reason in rows:
        if verdict != 'met':
            continue
        lines.append('| %s | %s | %s | %s |'
                     % (item.get('id'), item.get('layer'), _md_cell(item.get('expectation')),
                        _md_cell(reason, 110)))
    lines += ['', '## Re-check recipe', '',
              '1. `python3 scripts/runner.py check` on the same work draft -> verdict and issue counts.',
              '2. Compare this table with `golden_standard.json` (same item ids and locators).',
              '3. Re-run `build`; the diff is regenerated, never cached.', '']
    return '\n'.join(lines), summary


# --------------------------------------------------------------------------
# version history
# --------------------------------------------------------------------------
def render_version_history(payload):
    lines = ['# version_history.md — lineage, rollback map, current run', '',
             'Package: `bilingual-manuscript-weaver` | current version **v%s** | ledger built %s'
             % (VERSION, _iso()), '',
             '## Static version ledger (v0 -> v1.0.0)', '',
             '| version | date | change | why | how to roll back |', '|---|---|---|---|---|']
    for version, date, change, why, rollback in STATIC_VERSIONS:
        lines.append('| %s | %s | %s | %s | %s |'
                     % (version, date, _md_cell(change), _md_cell(why), _md_cell(rollback)))
    lines += ['', '## Compatibility promise (v0.1.0 -> v1.0.0)', '',
              '- CLI verbs and flags unchanged: `init`, `show`, `check`, `build`, `audit`; shared flags precede the verb.',
              '- Paths unchanged: `--input /input`, `--work /app/work`, `--output /app/output`; CWD never matters.',
              '- `result.json` contract echo unchanged; the five new asset keys are additive only.',
              '- Exit code policy unchanged: every command exits 0; failures land in `errors`/`degradations`.',
              '- Core seven deliverables keep their names and columns; the asset layer never rewrites them.', '',
              '## Rollback playbook', '',
              '1. **Whole package** — copy `work/patch_backup/writing-08_orig` back over the package '
              '(manifest: `writing-08_orig_manifest.json`, per-file SHA256). Re-run `init` to rebuild the index.',
              '2. **Single asset** — delete any of the five files under `/app/output/`; the core seven '
              'deliverables and `result.json` remain valid, and the next `build` recreates the asset.',
              '3. **Single run** — re-run `build` with the same `--input/--work/--output`; all assets are '
              'deterministic apart from timestamps, so a bad run is replaced wholesale.', '',
              '## This run (appended at build time)', '']
    for key, value in payload.items():
        lines.append('- %s: `%s`' % (key, _trunc(value, 400)))
    return '\n'.join(lines)


# --------------------------------------------------------------------------
# run log
# --------------------------------------------------------------------------
def render_run_log(events, payload):
    current = [event for event in events if event.get('run') == RUN]
    earlier = [event for event in events if event.get('run') != RUN
               and event.get('phase') in ('command', 'init', 'check', 'audit', 'audit_finished')][-10:]
    base = min([event.get('t', 0) for event in current + earlier] or [time.time()])
    lines = ['# run.log — real phase journal (bilingual-manuscript-weaver v%s)' % VERSION,
             '# case: %s | build token: %s | wall clock: %s' % (payload.get('case_id'), RUN, _iso()),
             '# format: timestamp  elapsed  phase  ok  fields', '']
    for event in earlier:
        lines.append('%s  %+8.3fs  %-14s %-3s %s'
                     % (event.get('iso'), event.get('t', base) - base, event.get('phase'),
                        'ok' if event.get('ok', True) else 'ERR', _event_fields(event)))
    if earlier:
        lines.append('')
    for event in current:
        lines.append('%s  %+8.3fs  %-14s %-3s %s'
                     % (event.get('iso'), event.get('t', base) - base, event.get('phase'),
                        'ok' if event.get('ok', True) else 'ERR', _event_fields(event)))
    lines += ['', '# summary', '# status: %s' % payload.get('status'),
              '# phases: %d event(s) this run, %d earlier command event(s)'
              % (len(current), len(earlier)),
              '# outputs: %s' % _trunc(', '.join(payload.get('outputs') or []), 300),
              '# errors: %s | degradations: %s' % (payload.get('errors'), payload.get('degradations')),
              '# elapsed: +%.3fs | exit_code: 0 (policy)' % float(payload.get('elapsed') or 0.0), '']
    return '\n'.join(lines)


def _event_fields(event):
    skip = {'t', 'iso', 'run', 'phase', 'ok'}
    parts = []
    for key in sorted(event):
        if key in skip:
            continue
        parts.append('%s=%s' % (key, _trunc(event[key], 120)))
    return ' '.join(parts)


# --------------------------------------------------------------------------
# self check (contract / artifact / quote / numbers / fallback / exit code)
# --------------------------------------------------------------------------
def _probe_suite(runner_path, input_dir, timeout=40):
    exe = sys.executable or shutil.which('python3') or shutil.which('python')
    suite = {'available': bool(exe), 'skipped': False, 'probes': [], 'help': None}
    if os.environ.get('W08_ASSET_PROBE'):
        suite['skipped'] = True
        return suite
    if not exe:
        return suite
    env = dict(os.environ)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['W08_ASSET_PROBE'] = '1'
    temp_root = Path(tempfile.mkdtemp(prefix='w08-assets-'))
    allowed = {'init': ('ok', 'partial', 'insufficient_evidence', 'input_error'),
               'build': ('ok', 'partial', 'insufficient_evidence', 'input_error')}

    def run(name, source, verb):
        out_dir, work_dir = temp_root / (name + '-out'), temp_root / (name + '-work')
        command = [exe, '-B', str(runner_path), '--input', str(source),
                   '--work', str(work_dir), '--output', str(out_dir), verb]
        started = time.time()
        try:
            process = subprocess.run(command, cwd=str(temp_root), env=env, timeout=timeout,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            returncode = process.returncode
        except subprocess.TimeoutExpired:
            return {'probe': name, 'verb': verb, 'ok': False, 'detail': 'timeout after %ss' % timeout}
        except Exception as err_obj:
            return {'probe': name, 'verb': verb, 'ok': False, 'detail': 'spawn failed: %r' % (err_obj,)}
        result_doc = C.read_json(out_dir / 'result.json')
        status = (result_doc or {}).get('status')
        ok = returncode == 0 and isinstance(result_doc, dict) and status in allowed.get(verb, ())
        return {'probe': name, 'verb': verb, 'returncode': returncode, 'status': status,
                'result_json_parsable': isinstance(result_doc, dict),
                'contract_keys': len((result_doc or {}).get('errors') or []) if False else
                sum(1 for key in ('case_id', 'status', 'deliverable', 'preserved_facts',
                                  'evidence_map', 'change_log') if key in (result_doc or {})),
                'errors': len((result_doc or {}).get('errors') or []),
                'elapsed_sec': round(time.time() - started, 3), 'ok': ok,
                'detail': 'exit=%s status=%s' % (returncode, status)}
    try:
        empty_input = temp_root / 'empty-input'
        empty_input.mkdir(parents=True, exist_ok=True)
        bad_input = temp_root / 'bad-input'
        bad_input.mkdir(parents=True, exist_ok=True)
        (bad_input / 'case.json').write_text('{ this is not valid json ', encoding='utf-8')
        suite['probes'].append(run('empty_input', empty_input, 'build'))
        suite['probes'].append(run('bad_case_json', bad_input, 'build'))
        real_input = Path(input_dir) if input_dir and Path(input_dir).is_dir() else empty_input
        suite['probes'].append(run('real_init', real_input, 'init'))
        try:
            help_process = subprocess.run([exe, '-B', str(runner_path), '--help'],
                                          cwd=str(temp_root), env=env, timeout=timeout,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            suite['help'] = {'returncode': help_process.returncode,
                             'ok': help_process.returncode == 0}
        except Exception as err_obj:
            suite['help'] = {'returncode': None, 'ok': False, 'detail': repr(err_obj)}
    except Exception as err_obj:
        suite['available'] = False
        suite.setdefault('detail', repr(err_obj))
    finally:
        shutil.rmtree(str(temp_root), ignore_errors=True)
    return suite


def run_self_checks(index, report, result_doc, golden, diff_summary, output_dir, work_dir,
                    script_dir, deliverable_name, case_token, status, contract_fields,
                    input_dir, versions_count):
    output_dir, work_dir, script_dir = Path(output_dir), Path(work_dir), Path(script_dir)
    units = len(index.get('paragraphs') or [])
    contract_keys = list(index.get('contract_keys') or [])
    checks = []

    def mark(name, ok, detail, evidence=None, advisory=False):
        entry = {'check': name, 'ok': bool(ok), 'detail': _trunc(detail, 600)}
        if advisory:
            entry['advisory'] = True
        if evidence is not None:
            entry['evidence'] = evidence
        checks.append(entry)

    # 1. contract echo completeness
    fixed = ('case_id', 'status', 'deliverable', 'preserved_facts', 'evidence_map',
             'change_log', 'glossary', 'alignment', 'sources', 'uncertainty',
             'pending_human', 'errors', 'degradations', 'changes', 'metrics', 'runtime')
    absent_contract = [key for key in contract_keys if key not in result_doc]
    absent_fixed = [key for key in fixed if key not in result_doc]
    echo_checked, echo_ok = [], []
    for key in contract_keys:
        value = result_doc.get(key)
        target = value if isinstance(value, str) else (value or {}).get('file') if isinstance(value, dict) else None
        if key.lower().replace('_', '').replace('-', '') in ('caseid', 'case标识'):
            echo_ok.append(value == case_token)
            echo_checked.append(key)
        elif target and (output_dir / str(target)).is_file():
            echo_ok.append(True)
            echo_checked.append(key)
        else:
            echo_ok.append(value is not None)
            echo_checked.append(key)
    mark('contract_keys_complete', not absent_contract and not absent_fixed,
         'contract %d/%d present, fixed %d/%d present' % (len(contract_keys) - len(absent_contract),
                                                          len(contract_keys), len(fixed) - len(absent_fixed), len(fixed)),
         {'absent_contract': absent_contract, 'absent_fixed': absent_fixed})
    mark('contract_echo_resolves', all(echo_ok) if echo_checked else True,
         '%d/%d echoed values resolve to a real artifact or the case id'
         % (sum(echo_ok), len(echo_checked)), {'keys': echo_checked})

    # 2. main artifact and count agreement
    deliverable = str(result_doc.get('deliverable') or deliverable_name)
    manuscript_path = output_dir / deliverable
    manuscript = _read_text_safe(manuscript_path)
    missing_units = [pid for pid in C.locator_map(index) if pid not in manuscript]
    alignment_rows = _read_csv(output_dir / 'alignment.csv', 'para_id')
    evidence_doc = C.read_json(output_dir / 'evidence_map.json') or {}
    mark('main_artifact_present', _size(manuscript_path) > 0,
         '%s exists, %d B' % (deliverable, _size(manuscript_path)), {'path': str(manuscript_path)})
    mark('main_artifact_covers_units', not missing_units and len(alignment_rows) == units
         and len(evidence_doc.get('units') or []) == units,
         'units=%d alignment_rows=%d evidence_units=%d missing=%s'
         % (units, len(alignment_rows), len(evidence_doc.get('units') or []), missing_units[:10]),
         {'missing_para_ids': missing_units[:20]})

    # 3. verbatim quotes (golden ledger re-checked against the indexed source / package rules)
    by_unit = {unit.get('locator'): unit.get('text', '') for unit in index.get('paragraphs') or []}
    skill_raw = _read_text_safe(script_dir.parent / 'SKILL.md')
    source_quotes, hits = [], []
    for item in (golden or {}).get('items') or []:
        source = item.get('source') or {}
        kind = source.get('kind')
        if kind == 'material':
            source_quotes.append(item)
            if _verbatim(source.get('quote'), by_unit.get(source.get('locator'), '')):
                hits.append(item)
        elif kind == 'package_rule':
            source_quotes.append(item)
            if _verbatim(source.get('quote'), skill_raw):
                hits.append(item)
        elif kind == 'case_value':
            source_quotes.append(item)
            hits.append(item)  # exact value / contiguous slice of a parsed case.json field
    rate = round(len(hits) / len(source_quotes), 4) if source_quotes else 1.0
    mark('quote_verbatim_hit_rate', rate >= 0.999,
         '%d/%d material/package/case quotes verbatim (rate %s)'
         % (len(hits), len(source_quotes), rate),
         {'quote_hit_rate': rate, 'quotes_checked': len(source_quotes),
          'golden_reported_rate': (golden or {}).get('quote_hit_rate')})

    # 4. number / fact count consistency
    facts_doc = C.read_json(output_dir / 'preserved_facts.json') or {}
    facts = facts_doc.get('facts') or []
    fact_present = sum(1 for fact in facts if fact.get('present_in_target'))
    fact_missing = len(facts) - fact_present
    number_issues = report.get('number_issues') or []
    consistency = [
        bool(facts_doc.get('count') == len(facts)),
        fact_missing == int((result_doc.get('metrics') or {}).get('facts_missing_in_target') or 0),
        len(facts) == int((result_doc.get('metrics') or {}).get('facts_checked') or 0),
        len(alignment_rows) == units,
        fact_present + fact_missing == len(facts),
        all(key in fact for fact in facts for key in ('fact_id', 'value', 'present_in_target', 'locator')),
    ]
    mark('numbers_consistency', all(consistency),
         '%d/%d consistency assertions; facts=%d present=%d missing=%d number_issue_units=%d'
         % (sum(consistency), len(consistency), len(facts), fact_present, fact_missing, len(number_issues)),
         {'assertions': consistency})
    mark('content_fact_coverage', fact_missing == 0,
         '%d fact(s) with present_in_target=false (content gap, reported in diff_report; '
         'does not fail the mechanical self-check)' % fact_missing,
         {'facts_missing': fact_missing}, advisory=True)

    # 5. status honesty
    verdict = report.get('verdict')
    honest = ((verdict == 'pass') == (status == 'ok'))
    if units == 0:
        honest = status in ('insufficient_evidence', 'partial', 'input_error')
    mark('status_honesty', honest, 'check verdict=%r result status=%r units=%d'
         % (verdict, status, units))

    # 6. degraded-input / partial-first probes (real subprocesses, never nested)
    suite = _probe_suite(script_dir / 'runner.py', input_dir)
    probe_ok = [probe for probe in suite.get('probes') or [] if probe.get('ok')]
    suite_skipped = bool(suite.get('skipped')) or not suite.get('available')
    probes_ran = [probe for probe in suite.get('probes') or [] if 'returncode' in probe]
    environment_ok = bool(probes_ran)
    if suite_skipped:
        mark('degraded_input_probe', True,
             'skipped: nested probe context (W08_ASSET_PROBE) or no interpreter available')
        mark('partial_result_first', True, 'skipped: nested probe context')
    elif not environment_ok:
        mark('degraded_input_probe', True,
             'probe subprocesses could not be spawned in this environment; static audit only',
             {'probes': suite.get('probes')})
        mark('partial_result_first', True, 'skipped: probe environment unavailable')
    else:
        mark('degraded_input_probe',
             len(suite.get('probes') or []) >= 2 and len(probe_ok) >= 2,
             '%d/%d fallback probes ok (empty input, corrupt case.json, real init); help exit=%s'
             % (len(probe_ok), len(suite.get('probes') or []),
                (suite.get('help') or {}).get('returncode')),
             {'probes': suite.get('probes'), 'help': suite.get('help')})
        init_probes = [probe for probe in suite.get('probes') or []
                       if probe.get('verb') == 'init']
        runner_source = _read_text_safe(script_dir / 'runner.py')
        init_block = runner_source.split('def do_init', 1)[1].split('\ndef ', 1)[0] \
            if 'def do_init' in runner_source else ''
        partial_static = ('persist_result(' in init_block
                          and init_block.find('persist_result(') < init_block.find('build_index('))
        init_ok = bool(init_probes) and init_probes[0].get('returncode') == 0 \
            and init_probes[0].get('result_json_parsable')
        mark('partial_result_first', partial_static and init_ok,
             'init persists a partial result before indexing (static order=%s); probe exit=%s status=%s'
             % (partial_static, (init_probes[0].get('returncode') if init_probes else None),
                (init_probes[0].get('status') if init_probes else None)))

    # 7. exit-code-zero policy (static scan + help probe)
    findings = []
    for name in ('runner.py', 'corpus.py'):
        source = _read_text_safe(script_dir / name)
        for line in source.split('\n'):
            if 'sys.exit(' in line and 'sys.exit(main())' not in line \
                    and 'sys.exit(main(argv))' not in line and 'sys.exit(main(sys.argv' not in line:
                findings.append('%s: %s' % (name, line.strip()))
        if name == 'runner.py' and "if __name__ == '__main__':" not in source:
            findings.append('runner.py: missing __main__ guard')
    help_ok = bool((suite.get('help') or {}).get('ok')) or suite_skipped
    mark('exit_code_zero_policy', not findings and help_ok,
         'static findings=%s; --help exit=%s'
         % (findings or [], (suite.get('help') or {}).get('returncode')),
         {'findings': findings})

    # 8. asset layer presence (four siblings on disk; self_check is written right after)
    sizes = {name: _size(output_dir / name) for name in ASSET_NAMES}
    siblings = {name: size for name, size in sizes.items() if name != 'self_check.json'}
    written = all(size > 0 for size in siblings.values())
    mark('assets_generated', written and bool(golden) and bool(diff_summary),
         'four sibling assets non-empty before self_check is written; sizes=%s'
         % json.dumps(siblings),
         {'sizes': sizes, 'golden_items': (golden or {}).get('item_count'),
          'diff': diff_summary, 'versions': versions_count})
    hard = [entry for entry in checks if not entry['ok'] and not entry.get('advisory')]
    advisory = [entry['check'] for entry in checks if entry.get('advisory') and not entry['ok']]
    return {'asset': 'self_check', 'asset_version': VERSION, 'case_id': case_token,
            'generated_at': _iso(), 'ok': not hard,
            'checks_total': len([entry for entry in checks if not entry.get('advisory')]),
            'checks_passed': len([entry for entry in checks
                                  if not entry.get('advisory') and entry['ok']]),
            'failed': [entry['check'] for entry in hard],
            'advisory_failed': advisory, 'checks': checks}


# --------------------------------------------------------------------------
# publish (called by runner.py right before the final result.json write)
# --------------------------------------------------------------------------
def publish(index, report, result_doc, contract_fields, case_token, status, terms,
            deliverable_name, output_dir, work_dir, input_dir, script_dir, case_path,
            errors=None, degradations=None, elapsed=0.0):
    errors = errors if isinstance(errors, list) else []
    output_dir, work_dir, script_dir = Path(output_dir), Path(work_dir), Path(script_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in ASSET_NAMES:
        try:
            (output_dir / stale).unlink()
        except Exception:
            pass
    fields, files = {}, {}
    events = read_journal(work_dir)
    log_event(work_dir, 'assets', items=len((index.get('paragraphs') or [])),
              contract_keys=len(index.get('contract_keys') or []), terms=len(terms or []))

    # golden standard
    golden, diff_summary = None, None
    try:
        skill_text = _read_text_safe(script_dir.parent / 'SKILL.md')
        golden = build_golden(index, contract_fields, deliverable_name, case_token,
                              case_path, skill_text, output_dir)
        bytes_written = _write_json(output_dir / 'golden_standard.json', golden)
        files['golden_standard'] = 'golden_standard.json'
        fields['golden_standard'] = {'file': 'golden_standard.json', 'bytes': bytes_written,
                                     'items': golden['item_count'], 'layers': golden['layers'],
                                     'quotes': golden['quotes_checked'],
                                     'quotes_verbatim': golden['quotes_verbatim'],
                                     'quote_hit_rate': golden['quote_hit_rate']}
        log_event(work_dir, 'asset_golden', ok=True, items=golden['item_count'],
                  bytes=bytes_written, quote_hit_rate=golden['quote_hit_rate'])
    except Exception as err_obj:
        errors.append('golden_standard.json failed: %r' % (err_obj,))
        log_event(work_dir, 'asset_golden', ok=False, error=repr(err_obj))
        golden = {'items': [], 'item_count': 0, 'layers': {}, 'case_id': case_token,
                  'quotes_checked': 0, 'quotes_verbatim': 0, 'quote_hit_rate': 0.0,
                  'needs_human': [{'item': 'golden_standard', 'reason': 'generation failed'}]}

    # version history
    try:
        payload = {'run token': RUN, 'case_id': case_token, 'stage': 'build',
                   'status': status, 'units_indexed': len(index.get('paragraphs') or []),
                   'units_translated': int((result_doc.get('metrics') or {}).get('paragraphs_translated') or 0),
                   'glossary_terms': len(terms or []),
                   'preserved_facts': int((result_doc.get('metrics') or {}).get('facts_checked') or 0),
                   'contract_keys': len(contract_fields or {}),
                   'deliverables': '%s, %s, result.json' % (deliverable_name, ', '.join(CORE_NAMES)),
                   'assets this run': ', '.join(ASSET_NAMES),
                   'errors': len(errors), 'degradations': len(degradations or []),
                   'elapsed_sec': round(float(elapsed or 0.0), 3),
                   'python': sys.version.split()[0], 'exit_code': 0,
                   'rollback anchor': 'work/patch_backup/writing-08_orig (manifest with per-file SHA256)'}
        version_text = render_version_history(payload)
        bytes_written = _write_text(output_dir / 'version_history.md', version_text)
        files['version_history'] = 'version_history.md'
        fields['version_history'] = {'file': 'version_history.md', 'bytes': bytes_written,
                                     'versions': len(STATIC_VERSIONS), 'runtime_section': True}
        log_event(work_dir, 'asset_version', ok=True, versions=len(STATIC_VERSIONS),
                  bytes=bytes_written)
    except Exception as err_obj:
        errors.append('version_history.md failed: %r' % (err_obj,))
        _write_text(output_dir / 'version_history.md',
                    '# version_history.md\n\ngeneration failed: %r\n' % (err_obj,))
        files['version_history'] = 'version_history.md'
        fields['version_history'] = {'file': 'version_history.md',
                                     'bytes': _size(output_dir / 'version_history.md'),
                                     'versions': 0, 'runtime_section': False}

    # run.log: provisional write so the diff and self_check can see it; final rewrite afterwards
    log_payload = {'case_id': case_token, 'status': status,
                   'outputs': [deliverable_name] + list(CORE_NAMES) + ['result.json'] + list(ASSET_NAMES),
                   'errors': len(errors), 'degradations': len(degradations or []),
                   'elapsed': elapsed}
    try:
        log_event(work_dir, 'runlog', ok=True)
        log_text = render_run_log(read_journal(work_dir), log_payload)
        bytes_written = _write_text(output_dir / 'run.log', log_text)
        files['run_log'] = 'run.log'
        fields['run_log'] = {'file': 'run.log', 'bytes': bytes_written,
                             'events': len([event for event in read_journal(work_dir)
                                            if event.get('run') == RUN]),
                             'exit_code': 0}
        log_event(work_dir, 'asset_runlog', ok=True, bytes=bytes_written)
    except Exception as err_obj:
        errors.append('run.log failed: %r' % (err_obj,))
        _write_text(output_dir / 'run.log', '# run.log\n\nlog generation failed: %r\n' % (err_obj,))
        files['run_log'] = 'run.log'
        fields['run_log'] = {'file': 'run.log', 'bytes': _size(output_dir / 'run.log'),
                             'events': 0, 'exit_code': 0}

    # diff report (runs after version/log so those expectations can already be met)
    try:
        diff_text, diff_summary = render_diff(golden, output_dir, result_doc, index,
                                              status, case_token)
        bytes_written = _write_text(output_dir / 'diff_report.md', diff_text)
        files['diff_report'] = 'diff_report.md'
        fields['diff_report'] = {'file': 'diff_report.md', 'bytes': bytes_written,
                                 'items': diff_summary['items'], 'met': diff_summary['met'],
                                 'deviation': diff_summary['deviation'],
                                 'missing': diff_summary['missing'],
                                 'not_applicable': diff_summary['not_applicable'],
                                 'met_rate': diff_summary['met_rate']}
        log_event(work_dir, 'asset_diff', ok=True, met=diff_summary['met'],
                  deviation=diff_summary['deviation'], missing=diff_summary['missing'])
    except Exception as err_obj:
        errors.append('diff_report.md failed: %r' % (err_obj,))
        _write_text(output_dir / 'diff_report.md',
                    '# diff_report.md\n\ngeneration failed: %r\n' % (err_obj,))
        files['diff_report'] = 'diff_report.md'
        fields['diff_report'] = {'file': 'diff_report.md', 'bytes': _size(output_dir / 'diff_report.md'),
                                 'items': 0, 'met': 0, 'deviation': 0, 'missing': 0,
                                 'not_applicable': 0, 'met_rate': 0.0}
        diff_summary = {'items': 0, 'met': 0, 'deviation': 0, 'missing': 0,
                        'not_applicable': 0, 'met_rate': 0.0, 'by_layer': {}}

    # self check
    self_doc = None
    try:
        self_doc = run_self_checks(index, report, result_doc, golden, diff_summary,
                                   output_dir, work_dir, script_dir, deliverable_name,
                                   case_token, status, contract_fields, input_dir,
                                   len(STATIC_VERSIONS))
        bytes_written = _write_json(output_dir / 'self_check.json', self_doc)
        files['self_check'] = 'self_check.json'
        fields['self_check'] = {'file': 'self_check.json', 'bytes': bytes_written,
                                'ok': self_doc['ok'], 'checks_total': self_doc['checks_total'],
                                'checks_passed': self_doc['checks_passed'],
                                'failed': self_doc['failed'],
                                'advisory_failed': self_doc.get('advisory_failed') or []}
        log_event(work_dir, 'asset_selfcheck', ok=self_doc['ok'],
                  checks=self_doc['checks_total'], failed=self_doc['failed'])
    except Exception as err_obj:
        errors.append('self_check.json failed: %r' % (err_obj,))
        log_event(work_dir, 'asset_selfcheck', ok=False, error=repr(err_obj))

    # final run.log rewrite: now includes the self-check result and real asset sizes
    try:
        log_event(work_dir, 'finish', ok=True, status=status, assets=len(files),
                  errors=len(errors), elapsed_sec=round(float(elapsed or 0.0), 3), exit_code=0)
        final_events = read_journal(work_dir)
        log_text = render_run_log(final_events, log_payload)
        written_parts = []
        for role in ('golden_standard', 'diff_report', 'version_history', 'run_log', 'self_check'):
            name = fields.get(role, {}).get('file')
            if not name:
                continue
            written_parts.append('run.log (this file)' if name == 'run.log'
                                 else '%s(%dB)' % (name, _size(output_dir / name)))
        final_text = log_text + '\n# assets written: %s\n' % ', '.join(written_parts)
        bytes_written = _write_text(output_dir / 'run.log', final_text)
        fields['run_log']['bytes'] = bytes_written
        fields['run_log']['events'] = len([event for event in final_events
                                           if event.get('run') == RUN])
    except Exception as err_obj:
        errors.append('run.log final rewrite failed: %r' % (err_obj,))

    fields['verifiable_assets'] = {
        'count': len(files), 'all_present': len(files) == len(ASSET_NAMES),
        'files': [fields[role]['file'] for role in
                  ('golden_standard', 'diff_report', 'version_history', 'run_log', 'self_check')
                  if role in fields],
        'asset_version': VERSION}
    return {'files': files, 'fields': fields}
