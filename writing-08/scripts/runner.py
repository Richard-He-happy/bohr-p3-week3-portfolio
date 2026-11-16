#!/usr/bin/env python3
# runner.py -- CLI front end of the bilingual manuscript skill.
#
#   init    scan the case input, index every source block, keep an honest partial result.json
#   show    print indexed blocks with their locators so the Agent reads the real text
#   check   compare the fresh draft with the index (coverage / quotes / digits / markers / terms)
#   build   render the bilingual manuscript and companion tables, then finalize result.json
#   audit   read-only re-check of the delivered package (added on top of the base flow)
#
# Standard library only, independent of the current working directory, and every
# command ends with exit code 0 so one bad material cannot zero the whole run.

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus as C
V = '1.0.0'
PH = '[待译 / PENDING TRANSLATION]'
T0 = time.time()

def guess_direction(para_record, draft_doc, case_meta):
    flat_text = '\n'.join((para['text'] for para in para_record.get('paragraphs', [])[:20]))
    res_obj = C.han_ratio(flat_text)
    src = 'zh' if res_obj > 0.2 else 'en' if res_obj < 0.02 else 'mixed'
    ins = str(case_meta.get('instruction') or '') + ' ' + json.dumps(case_meta.get('scope') or '', ensure_ascii=False)
    src_text = (draft_doc or {}).get('target_lang') or ('zh' if re.search('中文|chinese', ins, re.I) else 'en' if re.search('英文|english', ins, re.I) else None)
    src_text = src_text or ('en' if src == 'zh' else 'zh')
    return (src, src_text if src_text != src else 'en' if src == 'zh' else 'zh')

def render_bundle(para_record, draft_units, term_entries, direction, state, notes, output_dir, file_name):
    flat_text, src_text = direction
    entries = para_record.get('paragraphs', [])
    doc_lines = ['# 双语对照译文 / Bilingual translation', '', '- case `%s` | %s -> %s | status **%s** | units %d | glossary %d' % (para_record.get('case_id'), flat_text, src_text, state, len(entries), len(term_entries)), '- 逐段以 para_id / locator 对齐；数字、单位、引用标记与专名逐字保留；Source 为逐字摘录。', '', '## 术语表 / Glossary', '', '| term | target | locator | note |', '|---|---|---|---|']
    doc_lines += ['| %s | %s | %s | %s |' % tuple(((term_entry.get(dict_key) or '').replace('|', '\\|') for dict_key in ('term', 'target', 'locator', 'note'))) for term_entry in term_entries] or ['| - | - | - | 未提供术语表（见 pending_human） |']
    doc_lines += ['', '## 逐段对照 / Alignment', '']
    table_rows, fact_rows, evidence_rows = ([], [], [])
    for para in entries:
        para_draft = draft_units.get(para['para_id'], {})
        target_text = (para_draft.get('translation') or '').strip()
        doc_lines += ['### %s · %s · `%s`' % (para['para_id'], para.get('kind'), para.get('locator')), '', '**Source [%s]**' % para.get('material_name'), ''] + ['> ' + chunk_txt for chunk_txt in (para.get('text') or '').split('\n')]
        doc_lines += ['', '**Target [%s]**' % src_text, '', target_text or PH]
        doc_lines += ['', '_note: %s_' % para_draft['note']] if para_draft.get('note') else []
        doc_lines.append('')
        nums = list(dict.fromkeys(C.digits_of(para.get('text', ''))))
        tnum = set(C.digits_of(target_text))
        okn = {counter: C.digit_ok(counter, tnum) for counter in nums}
        cits = list(dict.fromkeys(C.MARKER_RX.findall(para.get('text', ''))))
        table_rows.append({'para_id': para['para_id'], 'material': para.get('material_name'), 'locator': para.get('locator'), 'kind': para.get('kind'), 'source': para.get('text', ''), 'target': target_text, 'aligned': 'yes' if target_text else 'missing_target', 'numbers_missing': ';'.join((counter for counter in nums if not okn[counter])), 'terms': ';'.join((term_entry['term'] for term_entry in term_entries if term_entry.get('term') and term_entry['term'].lower() in (para.get('text') or '').lower()))})
        fact_rows += [{'fact_id': 'F-%s-%s' % (para['para_id'], counter.replace('.', '_')), 'para_id': para['para_id'], 'kind': 'number', 'value': counter, 'present_in_target': okn[counter], 'locator': para.get('locator'), 'source_quote': para.get('text', '')[:200]} for counter in nums]
        fact_rows += [{'fact_id': 'F-%s-cite-%s' % (para['para_id'], re.sub('\\W+', '', candidate)[:12]), 'para_id': para['para_id'], 'kind': 'citation', 'value': candidate, 'present_in_target': candidate in target_text, 'locator': para.get('locator'), 'source_quote': para.get('text', '')[:200]} for candidate in cits]
        evidence_rows.append({'id': 'E-%s' % para['para_id'], 'kind': 'translation_unit', 'para_id': para['para_id'], 'locator': para.get('locator'), 'source_quote': para.get('text', ''), 'target_text': target_text, 'terms': [term_entry['term'] for term_entry in term_entries if term_entry.get('term') and term_entry['term'].lower() in (para.get('text') or '').lower()], 'derivation': 'Agent read this verbatim source paragraph and wrote the target unit'})
    if notes:
        doc_lines += ['## 交付备注 / Notes', ''] + ['- ' + counter for counter in notes] + ['']
    C.dump_text(output_dir / file_name, '\n'.join(doc_lines))
    with open(Path(output_dir) / 'alignment.csv', 'w', encoding='utf-8', newline='') as fh:
        word_frags = csv.DictWriter(fh, fieldnames=['para_id', 'material', 'locator', 'kind', 'source', 'target', 'aligned', 'numbers_missing', 'terms'])
        word_frags.writeheader()
        word_frags.writerows(table_rows)
    with open(Path(output_dir) / 'glossary.csv', 'w', encoding='utf-8', newline='') as fh:
        word_frags = csv.DictWriter(fh, fieldnames=['term', 'target', 'locator', 'note', 'status'])
        word_frags.writeheader()
        for term_entry in term_entries:
            word_frags.writerow({'term': term_entry.get('term', ''), 'target': term_entry.get('target', ''), 'locator': term_entry.get('locator', ''), 'note': term_entry.get('note', ''), 'status': 'locked' if term_entry.get('target') else 'pending_human'})
    C.dump_json(Path(output_dir) / 'preserved_facts.json', {'case_id': para_record.get('case_id'), 'count': len(fact_rows), 'facts': fact_rows})
    C.dump_json(Path(output_dir) / 'evidence_map.json', {'case_id': para_record.get('case_id'), 'count': len(evidence_rows), 'units': evidence_rows})
    return ({'deliverable': file_name, 'alignment': 'alignment.csv', 'glossary': 'glossary.csv', 'preserved_facts': 'preserved_facts.json', 'evidence_map': 'evidence_map.json'}, fact_rows)

def build_change_log(draft_doc, para_record, output_dir, script_notes):
    log_entries = []
    for i, candidate in enumerate((draft_doc or {}).get('change_log') or (draft_doc or {}).get('changes') or [], 1):
        if isinstance(candidate, dict):
            log_entries.append({'id': candidate.get('id') or 'C%03d' % i, 'para_id': candidate.get('para_id'), 'action': candidate.get('action') or 'translate', 'original_quote': candidate.get('original_quote') or candidate.get('source_quote'), 'revised_quote': candidate.get('revised_quote') or candidate.get('translation'), 'reason': candidate.get('reason') or '', 'locator': candidate.get('locator'), 'actor': candidate.get('actor') or 'agent'})
        elif isinstance(candidate, str):
            log_entries.append({'id': 'C%03d' % i, 'para_id': None, 'action': 'note', 'original_quote': None, 'revised_quote': None, 'reason': candidate, 'locator': None, 'actor': 'agent'})
    log_entries += [{'id': 'A%03d' % i, 'para_id': None, 'action': 'auto_fill', 'original_quote': None, 'revised_quote': None, 'reason': counter, 'locator': None, 'actor': 'script'} for i, counter in enumerate(script_notes, 1)]
    C.dump_json(Path(output_dir) / 'change_log.json', {'case_id': para_record.get('case_id'), 'count': len(log_entries), 'entries': log_entries})
    return log_entries

def do_init(opts):
    d, work_dir, output_dir = C.resolve_roots(opts)
    for chunk_txt in (work_dir, output_dir):
        chunk_txt.mkdir(parents=True, exist_ok=True)
    case, cpath = C.locate_case(d)
    case_meta = C.case_fields(case or {})
    case_token, contract_fields, error_list = (str(case_meta.get('case_id') or 'unknown'), case_meta.get('contract') or {}, [])
    if cpath and (not case):
        error_list.append('case json unreadable: %s' % cpath)
    res_obj = C.result_skeleton(case_token, contract_fields, 'partial', V)
    res_obj['note'] = 'index not built yet'
    res_obj['runtime'] = {'skill_version': V, 'python': sys.version.split()[0], 'started': C.utc_stamp()}
    C.persist_result(output_dir, res_obj, error_list)
    para_record = C.build_index(d, case or {}, case_meta)
    para_record['case_id'] = case_token
    C.dump_json(work_dir / 'index.json', para_record)
    if not para_record['paragraphs']:
        error_list.append('no readable material paragraphs found under %s' % d)
    C.dump_json(work_dir / 'workdraft.template.json', {'case_id': case_token, 'target_lang': None, 'glossary': [], 'change_log': [], 'paragraphs': [{'para_id': para['para_id'], 'kind': para['kind'], 'locator': para['locator'], 'source_quote': para['text'][:400], 'translation': '', 'note': ''} for para in para_record['paragraphs']]})
    res_obj.update({'sources': [{dict_key: mat.get(dict_key) for dict_key in ('id', 'name', 'path', 'kind', 'quality')} for mat in para_record['materials']], 'errors': error_list, 'degradations': para_record['warnings'], 'pending_human': [{'item': mat['name'], 'reason': mat.get('note')} for mat in para_record['materials'] if mat.get('quality') in ('low', 'unreadable')], 'runtime': {'skill_version': V, 'python': sys.version.split()[0], 'started': C.utc_stamp(), 'phase': 'init', 'materials': len(para_record['materials']), 'paragraphs': len(para_record['paragraphs'])}, 'note': 'index built; Agent writes workdraft.json next'})
    C.persist_result(output_dir, res_obj, error_list)
    print('case_id:', case_token, '| input:', d, '| work:', work_dir, '| output:', output_dir)
    for mat in para_record['materials']:
        print('  %-3s %-30s kind=%-7s quality=%-10s chars=%-7s split_blocks=%-4s %s' % (mat.get('id') or '-', mat.get('name'), mat.get('kind'), mat.get('quality'), mat.get('chars'), mat.get('split_blocks'), mat.get('note') or ''))
    print('paragraphs:', len(para_record['paragraphs']), '| contract case_fields:', ', '.join(para_record['contract_keys']) or '(none)', '| supplied terms:', len(para_record['supplied_terms']))
    print('acronym candidates:', ', '.join((src_text['term'] for src_text in para_record['term_candidates'][:12])) or '(none)')
    if para_record['warnings']:
        print('warnings:', '; '.join(para_record['warnings'][:5]))
    print('\nNEXT STEP: read the actual source text (show --para ... or open the files) and hand-write %s/workdraft.json' % work_dir)
    print('  {"case_id":"...","target_lang":"zh|en","glossary":[{"term","target","locator"}],"paragraphs":[{"para_id","source_quote","translation","note"}],"change_log":[...]}')
    print('  then run: check -> build')
    return 0

def do_show(opts):
    _, work_dir, _ = C.resolve_roots(opts)
    para_record = C.read_json(work_dir / 'index.json') or {}
    chosen = para_record.get('paragraphs') or []
    if opts.para:
        word_frags = {chunk_txt.upper() for chunk_txt in ' '.join(opts.para).replace(',', ' ').split()}
        chosen = [para for para in chosen if para['para_id'].upper() in word_frags]
    if opts.material:
        chosen = [para for para in chosen if (para.get('material') or '').upper() == opts.material.upper()]
    if opts.grep:
        pat = re.compile(opts.grep, re.I)
        chosen = [para for para in chosen if pat.search(para.get('text', ''))]
    if not (opts.para or opts.material or opts.grep or opts.all):
        print('materials:', ', '.join(('%s=%s' % (mat.get('id'), mat.get('name')) for mat in para_record.get('materials', []))) or '(none)')
        print('paragraphs:', len(para_record.get('paragraphs') or []))
        print('usage: show --para M1-P001 | --material M1 | --grep PATTERN | --all [--max-chars N]')
        return 0
    consumed_chars = 0
    for i, para in enumerate(chosen):
        block_txt = '[%s] %s (%s, %d chars)\n%s\n' % (para['para_id'], para.get('locator'), para.get('kind'), para.get('chars'), para.get('text'))
        if consumed_chars + len(block_txt) > opts.max_chars:
            print('... %d more paragraphs truncated; use --para/--material' % (len(chosen) - i))
            break
        print(block_txt)
        consumed_chars += len(block_txt)
    return 0

def report_block(report):
    candidate = report.get('coverage') or {}
    doc_lines = ['verdict: %s | coverage %s/%s (%s)' % (report.get('verdict'), candidate.get('covered'), candidate.get('expected'), candidate.get('ratio')), 'empty %d | quotes %d | numbers %d | cites %d | terms %d | glossary %s' % (len(report.get('empty_translations') or []), len(report.get('quote_issues') or []), len(report.get('number_issues') or []), len(report.get('citation_issues') or []), len(report.get('term_issues') or []), report.get('glossary_size'))]
    if candidate.get('missing_para_ids'):
        doc_lines.append('missing: ' + ', '.join(candidate['missing_para_ids'][:20]))
    for dict_key in ('quote_issues', 'number_issues', 'citation_issues', 'term_issues', 'unknown_para_ids'):
        for para_draft in (report.get(dict_key) or [])[:6]:
            doc_lines.append('  [%s] %s' % (dict_key[:-1], json.dumps(para_draft, ensure_ascii=False)))
    return '\n'.join(doc_lines)

def do_check(opts):
    _, work_dir, _ = C.resolve_roots(opts)
    para_record = C.read_json(work_dir / 'index.json') or {}
    draft_doc, consumed_chars, visited_paths = C.pick_draft(work_dir, opts.draft)
    report = C.audit_draft(para_record, draft_doc)
    if draft_doc is None:
        report['notes'] = ["no draft with non-empty 'paragraphs' in %s (seen: %s)" % (work_dir, ', '.join((Path(chunk_txt).name for chunk_txt in visited_paths)) or 'none')]
    report['draft_path'] = consumed_chars
    C.dump_json(work_dir / 'check_report.json', report)
    print(report_block(report))
    if report.get('verdict') != 'pass':
        print('\nRework the draft and run check again. `build` always completes and emits an honest partial result.')
    return 0

def do_build(opts):
    d, work_dir, output_dir = C.resolve_roots(opts)
    for chunk_txt in (output_dir, work_dir):
        chunk_txt.mkdir(parents=True, exist_ok=True)
    error_list, degradations, script_notes = ([], [], [])
    case, cpath = C.locate_case(d)
    case_meta = C.case_fields(case or {})
    if cpath and (not case):
        error_list.append('case json unreadable: %s' % cpath)
    para_record = C.read_json(work_dir / 'index.json')
    if not (isinstance(para_record, dict) and para_record.get('paragraphs')):
        para_record = C.build_index(d, case or {}, case_meta)
    case_token = str(para_record.get('case_id') or case_meta.get('case_id') or 'unknown')
    contract_fields = case_meta.get('contract') or para_record.get('contract') or {}
    draft_doc, consumed_chars, _ = C.pick_draft(work_dir, opts.draft)
    report = C.audit_draft(para_record, draft_doc)
    if draft_doc is None:
        degradations.append('no Agent work draft found; deterministic scaffold delivered (translation slots marked)')
    draft_units = {para_draft['para_id']: para_draft for para_draft in (draft_doc or {}).get('paragraphs') or [] if isinstance(para_draft, dict) and para_draft.get('para_id')}
    for para in para_record['paragraphs']:
        if not C.squeeze((draft_units.get(para['para_id']) or {}).get('translation')):
            draft_units[para['para_id']] = {'para_id': para['para_id'], 'translation': '', 'note': 'translation slot empty at build time'}
            script_notes.append('paragraph %s has no Agent translation; placeholder emitted' % para['para_id'])
    term_entries, seen_t = ([], set())
    draft_gl = (draft_doc or {}).get('glossary') or []
    for term_entry in list(draft_gl) + list(para_record.get('supplied_terms') or []):
        if isinstance(term_entry, dict) and term_entry.get('term') and (term_entry['term'].lower() not in seen_t):
            seen_t.add(term_entry['term'].lower())
            term_entries.append({'term': term_entry['term'], 'target': term_entry.get('target') or '', 'note': term_entry.get('note') or '', 'locator': term_entry.get('locator') or ('' if term_entry in draft_gl else 'case.supplied_terms')})
    direction, unit_total = (guess_direction(para_record, draft_doc, case_meta), len(para_record['paragraphs']))
    open_units = sum((1 for para in para_record['paragraphs'] if not C.squeeze((draft_units.get(para['para_id']) or {}).get('translation'))))
    status = 'insufficient_evidence' if not unit_total else 'partial' if open_units or (report.get('verdict') or 'fail') == 'fail' else 'ok'
    notes = ['未完成单元 %d/%d；缺口见 pending_human 与 alignment.csv 的 aligned 列' % (open_units, unit_total)] if status != 'ok' else []
    if not unit_total:
        notes = ['未发现可读材料：请核对 /input 下材料路径与格式；本文件仅为结构骨架，不含译文']
        error_list.append('no readable material paragraphs under %s' % d)
    if report.get('number_issues'):
        notes.append('数字/单位未全部落地 %d 段（preserved_facts.json present_in_target=false）' % len(report['number_issues']))
    if report.get('term_issues'):
        notes.append('术语不一致 %d 处（见 result.json term_issues）' % len(report['term_issues']))
    produced, fact_rows, log_entries = ({}, [], [])
    try:
        produced, fact_rows = render_bundle(para_record, draft_units, term_entries, direction, status, notes, output_dir, opts.deliverable_name)
    except Exception as err_obj:
        error_list.append('deliverable build failed: %s' % err_obj)
        C.dump_text(output_dir / opts.deliverable_name, '# 译文 / Translation\n\n' + PH)
        produced['deliverable'] = opts.deliverable_name
        degradations.append('deliverable emitted as skeleton after error')
    try:
        log_entries = build_change_log(draft_doc, para_record, output_dir, script_notes)
        produced['change_log'] = 'change_log.json'
    except Exception as err_obj:
        error_list.append('change log build failed: %s' % err_obj)
    produced['_facts'] = len(fact_rows)
    produced['_miss'] = sum((1 for chunk_txt in fact_rows if not chunk_txt.get('present_in_target')))
    res_obj = C.compose_result(para_record, report, term_entries, open_units, status, produced, error_list, degradations, log_entries, consumed_chars, contract_fields, case_token, V, time.time() - T0)
    saved_path = C.persist_result(output_dir, res_obj, error_list)
    print('status:', status, '| paragraphs:', unit_total, '| translated:', unit_total - open_units, '| glossary:', len(term_entries), '| verdict:', report.get('verdict'))
    print('outputs:', json.dumps({dict_key: val for dict_key, val in produced.items() if not dict_key.startswith('_')}, ensure_ascii=False))
    print('result:', str(saved_path) if saved_path else 'FAILED')
    return 0

def do_audit(opts):
    """Read-only audit of what build produced; never rebuilds and never exits non-zero."""
    in_root, work_dir, output_dir = C.resolve_roots(opts)
    index = C.read_json(work_dir / 'index.json') or {}
    draft_doc, draft_path, _ = C.pick_draft(work_dir, None)
    if isinstance(draft_doc, dict):
        report = C.audit_draft(index, draft_doc)
    else:
        report = {'checked': False, 'verdict': 'fail', 'coverage': {}, 'glossary_size': 0}
    checks = []

    def mark(label, ok, detail):
        checks.append({'check': label, 'ok': bool(ok), 'detail': str(detail)[:300]})

    result_path = output_dir / 'result.json'
    result_doc = C.read_json(result_path) or {}
    mark('result.json readable', bool(result_doc), result_path)
    contract_keys = index.get('contract_keys') or []
    absent_keys = [key for key in contract_keys if key not in result_doc]
    mark('output_contract keys present', not absent_keys,
         absent_keys or '%d key(s)' % len(contract_keys))
    deliverable = str(result_doc.get('deliverable') or 'translation.md')
    deliverable_path = output_dir / deliverable
    mark('deliverable non-empty', deliverable_path.is_file() and deliverable_path.stat().st_size > 0,
         deliverable_path)
    units = len(index.get('paragraphs') or [])
    alignment_path = output_dir / 'alignment.csv'
    try:
        with open(alignment_path, encoding='utf-8', newline='') as handle:
            alignment_rows = len(list(csv.DictReader(handle)))
    except Exception:
        alignment_rows = -1
    mark('alignment rows match units', alignment_rows == units,
         '%s/%s' % (alignment_rows, units))
    manuscript = C.read_text(deliverable_path) if deliverable_path.is_file() else ''
    missing_units = [pid for pid in C.locator_map(index) if pid not in manuscript]
    mark('every unit rendered in manuscript', not missing_units, missing_units[:20])
    honest_status = (report.get('verdict') == 'pass') == (result_doc.get('status') == 'ok')
    mark('status matches check verdict', honest_status,
         {'verdict': report.get('verdict'), 'status': result_doc.get('status')})
    rates = C.quality_rates(report)
    verdict = all(entry['ok'] for entry in checks)
    C.dump_json(work_dir / 'audit.json',
                {'case_id': index.get('case_id') or result_doc.get('case_id'),
                 'passed': verdict, 'checks': checks, 'rates': rates,
                 'draft': draft_path, 'deliverable': deliverable})
    print('audit: %s | %d/%d checks | rates %s' % (
        'PASS' if verdict else 'ATTENTION', sum(1 for entry in checks if entry['ok']),
        len(checks), json.dumps(rates, ensure_ascii=False)))
    for entry in checks:
        if not entry['ok']:
            print('  [FAIL] %s: %s' % (entry['check'], entry['detail']))
    return 0

def main(argv=None):
    ap = argparse.ArgumentParser(prog='runner.py', description='Bilingual manuscript skill CLI: init -> show -> (Agent writes workdraft.json) -> check -> build. Every command exits 0.')
    ap.add_argument('--input', help='input dir (default /input)')
    ap.add_argument('--work', help='work dir (default /app/work)')
    ap.add_argument('--output', help='output dir (default /app/output)')
    sp = ap.add_subparsers(dest='cmd')
    sp.add_parser('init', help='scan the input, index source blocks, write the partial result').set_defaults(func=do_init)
    para = sp.add_parser('show', help='print indexed source blocks with locators')
    para.add_argument('--para', action='append', help='para_id (repeatable)')
    para.add_argument('--material', help='material id, e.g. M1')
    para.add_argument('--grep', help='regex over paragraph text')
    para.add_argument('--all', action='store_true')
    para.add_argument('--max-chars', type=int, default=24000)
    para.set_defaults(func=do_show)
    para = sp.add_parser('check', help='compare the Agent draft with the index')
    para.add_argument('--draft', help='explicit draft json path')
    para.set_defaults(func=do_check)
    para = sp.add_parser('build', help='render the deliverables and finalize result.json')
    para.add_argument('--draft', help='explicit draft json path')
    para.add_argument('--deliverable-name', default='translation.md')
    para.set_defaults(func=do_build)
    p = sp.add_parser('audit', help='read-only audit of the delivered package')
    p.set_defaults(func=do_audit)
    opts = ap.parse_args(argv)
    if not getattr(opts, 'func', None):
        ap.print_help()
        print('\nQuick start: init -> show -> write workdraft.json -> check -> build')
        return 0
    try:
        return opts.func(opts)
    except SystemExit:
        raise
    except Exception as err_obj:
        try:
            _, _, output_dir = C.resolve_roots(opts)
            C.dump_json(output_dir / 'result.json', {'case_id': 'unknown', 'status': 'input_error', 'skill': 'bilingual-manuscript-weaver', 'skill_version': V, 'errors': ['unhandled: %r' % (err_obj,)], 'sources': [], 'uncertainty': [], 'pending_human': [], 'degradations': ['command aborted'], 'deliverable': None, 'preserved_facts': None, 'evidence_map': None, 'change_log': None, 'runtime': {'finished': C.utc_stamp()}})
        except Exception:
            pass
        print('ERROR (handled, exit 0): %r' % (err_obj,))
        return 0
if __name__ == '__main__':
    sys.exit(main())
