#!/usr/bin/env python3
# corpus.py -- text plumbing for the bilingual manuscript runner: extract text,
# index blocks, cross-check the Agent draft.  Stdlib only; helpers degrade instead
# of raising so one corrupt upload never takes the run down.

import json
import re
import sys
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path
DIGIT_RX = re.compile('\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?|\\d+(?:\\.\\d+)?')
UNIT_RX = re.compile('(?:%|‰|°C|mg|kg|mL|mM|µM|μM|nM|min|kPa|MPa|nm|µm|μm|kDa|Da|Hz|Gy|Sv)\\b')
MARKER_RX = re.compile('\\[\\s*\\d+(?:\\s*[-,–]\\s*\\d+)*\\s*\\]|\\(\\s*[A-Z][^()]{0,80}?\\b(?:19|20)\\d{2}[a-z]?\\s*\\)')
HAN_RX = re.compile('[\\u3400-\\u4dbf\\u4e00-\\u9fff]')
CAPTION_RX = re.compile('^(?:fig(?:ure)?\\.?|tab(?:le)?\\.?|scheme|chart|图|表|附表|附图)\\s*[\\dIVXivx]')
BIB_RX = re.compile('^(?:\\[\\d+\\]|\\d+\\.\\s+[A-Z])')
SHORT_CAP_RX = re.compile('\\b[A-Z][A-Z0-9]{1,7}\\b')
DECODER_CHAIN = ('utf-8-sig', 'utf-8', 'gb18030', 'big5', 'latin-1')

def utc_stamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def squeeze(flat_text):
    return re.sub('\\s+', ' ', (flat_text or '').replace('\xa0', ' ')).strip()

def fold_text(flat_text):
    return squeeze(flat_text).lower()

def term_hit(tgt, target_text):
    src_text, flat_text = (fold_text(tgt), fold_text(target_text))
    if src_text and src_text in flat_text:
        return True
    word_frags = [chunk_txt for chunk_txt in re.findall('[a-z]+|[\\u4e00-\\u9fff]+', src_text) if len(chunk_txt) > 3]
    return bool(word_frags) and all((chunk_txt[:6] in flat_text for chunk_txt in word_frags))

def digits_of(src_text):
    src_text = MARKER_RX.sub(' ', src_text or '')
    return [mat.group(0).replace(',', '') for mat in DIGIT_RX.finditer(src_text) if not src_text[mat.start() - 1:mat.start()].isalpha()]

def digit_ok(counter, toks):
    if counter in toks:
        return True
    try:
        val = float(counter)
    except Exception:
        return False
    return any(('%g' % (val * mat) in toks for mat in (10000.0, 100000000.0, 0.0001, 1e-08)))

def han_ratio(src_text):
    src_text = re.sub('\\s', '', src_text or '')
    return len(HAN_RX.findall(src_text)) / len(src_text) if src_text else 0.0

def read_text(para):
    try:
        raw = Path(para).read_bytes()
    except Exception:
        return ''
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        try:
            return raw.decode('utf-16')
        except Exception:
            pass
    for err_obj in DECODER_CHAIN:
        try:
            return raw.decode(err_obj)
        except Exception:
            pass
    return raw.decode('utf-8', 'replace')

def read_json(para):
    src_text = read_text(para)
    try:
        return json.loads(src_text) if src_text.strip() else None
    except Exception:
        return None

def dump_json(para, obj):
    para = Path(para)
    para.parent.mkdir(parents=True, exist_ok=True)
    para.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return para

def dump_text(para, flat_text):
    para = Path(para)
    para.parent.mkdir(parents=True, exist_ok=True)
    para.write_text(flat_text if flat_text.endswith('\n') else flat_text + '\n', encoding='utf-8')
    return para

def decode_pdf_escape(b):
    obj, i = ([], 0)
    while i < len(b):
        if b[i] == 92 and i + 1 < len(b):
            counter = b[i + 1]
            if counter in (110, 114, 116):
                obj.append({110: 10, 114: 13, 116: 9}[counter])
                i += 2
                continue
            if 48 <= counter <= 55:
                mat = re.match(b'[0-7]{1,3}', b[i + 1:i + 4])
                obj.append(int(mat.group(0), 8) & 255)
                i += 1 + len(mat.group(0))
                continue
            obj.append(counter)
            i += 2
            continue
        obj.append(b[i])
        i += 1
    return bytes(obj)

def pdf_ops_text(d):
    obj = []
    for mat in re.finditer(b'\\((?:\\\\.|[^()\\\\])*\\)|\\bT[dDJj*]\\b|\\bET\\b|\\bBT\\b', d):
        src_text = mat.group(0)
        if src_text.startswith(b'('):
            obj.append(decode_pdf_escape(src_text[1:-1]).decode('latin-1'))
        elif src_text in (b'BT', b'Tj', b'TJ'):
            obj.append(' ')
        else:
            obj.append('\n')
    return ''.join(obj)

def pdf_text(para):
    try:
        data = Path(para).read_bytes()
    except Exception:
        return ''
    ch = []
    for mat in re.finditer(b'stream\\r?\\n', data):
        err_obj = data.find(b'endstream', mat.end())
        if err_obj < 0:
            continue
        raw = data[mat.end():err_obj]
        output_dir = b''
        for opts in (raw, raw.strip(b'\r\n')):
            try:
                output_dir = zlib.decompress(opts)
                break
            except Exception:
                try:
                    output_dir = zlib.decompressobj().decompress(opts)
                    break
                except Exception:
                    output_dir = b''
        if output_dir and (b'Tj' in output_dir or b'TJ' in output_dir):
            src_text = pdf_ops_text(output_dir)
            if src_text.strip():
                ch.append(src_text)
    return '\n\n'.join(ch)

def docx_text(para):
    try:
        with zipfile.ZipFile(para) as z:
            chunk_txt = z.read('word/document.xml').decode('utf-8', 'replace')
    except Exception:
        return ''
    from html import unescape
    return unescape(re.sub('<[^>]+>', '', re.sub('</w:p>', '\n\n', re.sub('<w:(?:tab|br)[^>]*/>', ' ', chunk_txt))))

def read_material(para):
    para = Path(para)
    try:
        h = para.read_bytes()[:8]
    except Exception:
        return ('', 'unreadable', 'unreadable', 'cannot open file')
    if h[:4] == b'%PDF':
        src_text = pdf_text(para)
        ok = len(src_text.strip()) > 200
        return (src_text, 'pdf', 'ok' if ok else 'low', '' if ok else 'thin/CID text layer; check the page')
    if h[:2] == b'PK':
        try:
            with zipfile.ZipFile(para) as z:
                names = z.namelist()
        except Exception:
            names = []
        if any((counter.startswith('word/') for counter in names)):
            return (docx_text(para), 'docx', 'ok', '')
        return ('', 'office', 'low', 'office package not text-extracted; open directly')
    if h[:8] == b'\x89PNG\r\n\x1a\n' or h[:2] == b'\xff\xd8':
        return ('', 'image', 'unreadable', 'raster image: read visually, do not guess')
    src_text = read_text(para)
    if para.suffix.lower() in ('.html', '.htm'):
        from html import unescape
        src_text = unescape(re.sub('<[^>]+>', ' ', re.sub('(?is)<(script|style).*?</\\1>', ' ', src_text)))
        return (src_text, 'html', 'ok', '')
    return (src_text, 'text', 'ok' if src_text.strip() else 'low', '')

def resolve_roots(opts):

    def pick(term_entry, d1, d2):
        return Path(term_entry) if term_entry else Path(d1) if Path(d1).exists() else Path(d2)
    return (pick(opts.input, '/input', 'input'), pick(opts.work, '/app/work', 'work'), pick(opts.output, '/app/output', 'output'))

def locate_case(d):
    candidate = [d / counter for counter in ('case.json', 'input.json', 'task.json') if (d / counter).is_file()] if d.is_dir() else []
    if d.is_dir():
        candidate += [para for para in sorted(d.rglob('case*.json')) if para not in candidate]
    for para in candidate:
        obj = read_json(para)
        if isinstance(obj, dict):
            return (obj, para)
    return ({}, candidate[0] if candidate else None)

def case_fields(case):

    def find(*pat, d=None):
        for dict_key, val in (case or {}).items():
            if any((chunk_txt in str(dict_key).lower() for chunk_txt in pat)) and val not in (None, '', [], {}):
                return val
        return d
    oc = case.get('output_contract')
    return {'case_id': case.get('case_id') or case.get('id') or find('case_id'), 'instruction': find('instruction', 'brief', 'request', 'task_desc', 'prompt', 'workorder'), 'contract': oc if isinstance(oc, dict) else find('contract', d={}) or {}, 'scope': find('scope', 'constraint', 'requirement', 'audience', 'style'), 'terms': find('glossary', 'locked_term', 'terminolog', 'termbase', d=[])}

def material_files(d, case):
    visited_paths, output_dir = (set(), [])
    roots = [d] + ([d / chunk_txt for chunk_txt in ('artifacts', 'materials', 'resources', 'files')] if d.is_dir() else [])
    for res_obj in roots:
        if res_obj.is_dir():
            for para in sorted(res_obj.rglob('*')):
                if para.is_file() and (not para.name.startswith('.')) and ('__pycache__' not in para.parts) and (para.name not in ('case.json', 'input.json', 'task.json')) and (para not in visited_paths):
                    visited_paths.add(para)
                    output_dir.append(para)
    for dict_key in ('formal_inputs', 'artifacts', 'materials', 'runtime_files'):
        val = (case or {}).get(dict_key)
        for para_draft in val if isinstance(val, list) else [val] if val else []:
            quote_frag = para_draft if isinstance(para_draft, str) else para_draft.get('path') if isinstance(para_draft, dict) else ''
            candidate = d / quote_frag if quote_frag else None
            if candidate and candidate.is_file() and (candidate not in visited_paths):
                visited_paths.add(candidate)
                output_dir.append(candidate)
    return output_dir

def split_blocks(text, max_len=1200):
    output_dir = []
    for b in re.split('\\n\\s*\\n', text.replace('\r\n', '\n').replace('\r', '\n')):
        b = b.strip().lstrip('#').strip()
        if not b or re.fullmatch('!\\[[^\\]]*\\]\\([^)]*\\)', b):
            continue
        if len(b) <= max_len:
            output_dir.append(b)
            continue
        pending_buf = ''
        for flat_text in re.split('(?<=[.!?。！？；;])\\s*|(?<=。)', b):
            if not flat_text.strip():
                continue
            if len(pending_buf) + len(flat_text) > max_len and pending_buf:
                output_dir.append(pending_buf.strip())
                pending_buf = flat_text
            else:
                pending_buf += flat_text
        if pending_buf.strip():
            output_dir.append(pending_buf.strip())
    return output_dir

def block_kind(src_text):
    src_text = src_text.strip().lstrip('#').strip()
    if CAPTION_RX.match(src_text):
        return 'caption'
    if src_text.lower().startswith(('reference', 'references', 'bibliography', '参考文献')):
        return 'heading'
    if BIB_RX.match(src_text) and len(src_text) < 600:
        return 'reference'
    if len(src_text) < 120 and (not src_text.endswith(('。', '.', ';', '；', ':'))):
        return 'heading'
    return 'formula' if '$' in src_text or (len(src_text) < 60 and (not src_text.endswith('。')) and re.search('[=≈≤≥]\\s*\\S', src_text)) else 'body'

def build_index(d, case, case_meta):
    material_rows, entries, warning_list, abbrev_count, counter = ([], [], [], {}, 0)
    for path in material_files(d, case):
        src_text, dict_key, quote_frag, note = read_material(path)
        if not src_text.strip():
            material_rows.append({'id': None, 'path': str(path), 'name': path.name, 'kind': dict_key, 'quality': quote_frag, 'chars': 0, 'split_blocks': 0, 'note': note})
            if note:
                warning_list.append('%s: %s' % (path.name, note))
            continue
        counter += 1
        mid, block_list = ('M%d' % counter, split_blocks(src_text))
        material_rows.append({'id': mid, 'path': str(path), 'name': path.name, 'kind': dict_key, 'quality': quote_frag, 'chars': len(src_text), 'split_blocks': len(block_list), 'note': note})
        for i, chunk_txt in enumerate(block_list, 1):
            entries.append({'para_id': '%s-P%03d' % (mid, i), 'material': mid, 'material_name': path.name, 'material_path': str(path), 'locator': '%s:%s#P%03d' % (mid, path.name, i), 'kind': block_kind(chunk_txt), 'chars': len(chunk_txt), 'text': chunk_txt})
            for opts in SHORT_CAP_RX.findall(chunk_txt):
                abbrev_count[opts] = abbrev_count.get(opts, 0) + 1
    locked_terms = case_meta.get('terms') or []
    if isinstance(locked_terms, dict):
        locked_terms = [{'term': dict_key, 'target': val} for dict_key, val in locked_terms.items()]
    return {'case_id': str(case_meta.get('case_id') or 'unknown'), 'created': utc_stamp(), 'instruction': case_meta.get('instruction'), 'contract_keys': list((case_meta.get('contract') or {}).keys()), 'contract': case_meta.get('contract') or {}, 'materials': material_rows, 'paragraphs': entries, 'supplied_terms': locked_terms, 'warnings': warning_list, 'term_candidates': [{'term': dict_key, 'count': val} for dict_key, val in sorted(abbrev_count.items(), key=lambda kv: (-kv[1], kv[0]))[:40]]}

def pick_draft(work_dir, explicit=None):
    visited_paths, candidates_order = ([], [])
    if explicit:
        candidates_order.append(Path(explicit))
    for counter in ('workdraft.json', 'draft.json', 'translation_draft.json'):
        candidates_order.append(Path(work_dir) / counter)
    word_frags = Path(work_dir)
    if word_frags.is_dir():
        candidates_order += [para for para in sorted(word_frags.rglob('*.json')) if para.name not in ('index.json', 'check_report.json', 'result.json') and 'template' not in para.name.lower()]
    for para in candidates_order:
        if para in visited_paths or not para.is_file():
            continue
        visited_paths.append(para)
        obj = read_json(para)
        if isinstance(obj, dict) and isinstance(obj.get('paragraphs'), list) and obj['paragraphs']:
            return (obj, str(para), [str(chunk_txt) for chunk_txt in visited_paths])
    return (None, None, [str(chunk_txt) for chunk_txt in visited_paths])

def audit_draft(index, draft_doc):
    report = {'checked': False, 'verdict': 'fail', 'glossary_size': 0, 'coverage': {'expected': 0, 'covered': 0, 'ratio': 0.0, 'missing_para_ids': []}, 'quote_issues': [], 'number_issues': [], 'citation_issues': [], 'term_issues': [], 'empty_translations': [], 'duplicate_para_ids': [], 'unknown_para_ids': [], 'notes': []}
    if not isinstance(index, dict):
        report['notes'].append('no index')
        return report
    if not isinstance(draft_doc, dict):
        report['notes'].append('no draft')
        return report
    report['checked'] = True
    entries = index.get('paragraphs') or []
    by_id = {para.get('para_id'): para for para in entries if para.get('para_id')}
    draft_units = [para_draft for para_draft in draft_doc.get('paragraphs') or [] if isinstance(para_draft, dict) and para_draft.get('para_id')]
    ids = [para_draft['para_id'] for para_draft in draft_units]
    report['duplicate_para_ids'] = sorted({i for i in ids if ids.count(i) > 1})
    report['unknown_para_ids'] = sorted({i for i in ids if i not in by_id})
    trs = {para_draft['para_id']: para_draft.get('translation') for para_draft in draft_units}
    missing = [para['para_id'] for para in entries if para['para_id'] not in trs]
    ok = {i for i, val in trs.items() if squeeze(val)}
    report['coverage'] = {'expected': len(entries), 'covered': len(ok), 'ratio': round(len(ok) / len(entries), 3) if entries else 0.0, 'missing_para_ids': missing[:50]}
    term_entries = [term_entry for term_entry in draft_doc.get('glossary') or [] if isinstance(term_entry, dict) and term_entry.get('term')]
    report['glossary_size'] = len(term_entries)
    for para_draft in draft_units:
        pid, para_record = (para_draft.get('para_id'), by_id.get(para_draft.get('para_id')))
        if not para_record:
            continue
        quote_frag, src = (para_draft.get('source_quote'), para_record.get('text', ''))
        target_text = para_draft.get('translation') if isinstance(para_draft.get('translation'), str) else ''
        if not squeeze(target_text):
            report['empty_translations'].append(pid)
        if isinstance(quote_frag, str) and squeeze(quote_frag) and (fold_text(quote_frag) not in fold_text(para_record.get('text', ''))):
            report['quote_issues'].append({'para_id': pid, 'issue': 'quote not verbatim', 'locator': para_record.get('locator')})
        tnum = set(digits_of(target_text))
        miss = [counter for counter in dict.fromkeys(digits_of(src)) if not digit_ok(counter, tnum)]
        if miss:
            report['number_issues'].append({'para_id': pid, 'missing': miss[:20], 'locator': para_record.get('locator')})
        elif UNIT_RX.search(src) and (not UNIT_RX.search(target_text)):
            report['number_issues'].append({'para_id': pid, 'missing': ['unit:' + UNIT_RX.search(src).group(0)], 'locator': para_record.get('locator'), 'source': squeeze(src)[:160]})
        for candidate in dict.fromkeys(MARKER_RX.findall(src or '')):
            if squeeze(candidate) not in squeeze(target_text):
                report['citation_issues'].append({'para_id': pid, 'marker': squeeze(candidate), 'locator': para_record.get('locator')})
        for term_entry in term_entries:
            term, tgt = (term_entry.get('term') or '', term_entry.get('target') or '')
            if term and tgt and (fold_text(term) in fold_text(src)) and (not term_hit(tgt, target_text)):
                report['term_issues'].append({'para_id': pid, 'term': term, 'expected': tgt, 'locator': para_record.get('locator')})
    hard = report['quote_issues'] or report['number_issues'] or report['citation_issues'] or report['term_issues'] or report['empty_translations'] or report['duplicate_para_ids'] or (report['coverage']['ratio'] < 0.999)
    report['verdict'] = 'fail' if hard else 'pass'
    return report

def contract_value(dict_key, fl):
    lk = str(dict_key).lower()
    for keys, role in (('glossar', 'glossary'), ('术语', 'glossary'), ('align', 'alignment'), ('对照', 'alignment'), ('preserv', 'preserved_facts'), ('fact', 'preserved_facts'), ('number', 'preserved_facts'), ('evidence', 'evidence_map'), ('source_map', 'evidence_map'), ('locator', 'evidence_map'), ('change', 'change_log'), ('log', 'change_log'), ('revision', 'change_log'), ('deliver', 'deliverable'), ('translat', 'deliverable'), ('manuscript', 'deliverable'), ('译文', 'deliverable')):
        if keys in lk:
            return fl.get(role)
    for stem in fl:
        if stem in lk or lk in stem:
            return fl[stem]
    return None

def result_skeleton(case_token, contract_fields, state, ver):
    res_obj = {'case_id': case_token, 'status': state, 'skill': 'bilingual-manuscript-weaver', 'skill_version': ver, 'deliverable': None, 'preserved_facts': None, 'evidence_map': None, 'change_log': None, 'glossary': None, 'alignment': None, 'sources': [], 'uncertainty': [], 'pending_human': [], 'errors': [], 'degradations': [], 'changes': [], 'runtime': {}}
    for dict_key in contract_fields if isinstance(contract_fields, dict) else {}:
        res_obj.setdefault(dict_key, None)
    return res_obj

def compose_result(para_record, report, term_entries, open_units, status, produced, error_list, degradations, log_entries, consumed_chars, contract_fields, case_token, ver, elapsed):
    unit_total = len(para_record.get('paragraphs', []))
    unc = [{'item': 'coverage', 'detail': 'translated units %d/%d' % (unit_total - open_units, unit_total)}, {'item': 'numbers', 'detail': '%d paragraph(s) with digits/units not carried over' % len(report.get('number_issues') or [])}, {'item': 'terms', 'detail': '%d glossary term(s) missing from their paragraph target' % len(report.get('term_issues') or [])}, {'item': 'quotes', 'detail': '%d draft quote(s) not verbatim in source' % len(report.get('quote_issues') or [])}]
    ph = [{'item': term_entry['term'], 'reason': '术语译名待确认（target 为空）', 'locator': term_entry.get('locator')} for term_entry in term_entries if not term_entry.get('target')]
    ph += [{'item': mat.get('name'), 'reason': mat.get('note')} for mat in para_record.get('materials', []) if mat.get('quality') in ('low', 'unreadable')]
    if open_units:
        ph.append({'item': 'untranslated_paragraphs', 'reason': '%d 段无译文' % open_units, 'para_ids': (report.get('coverage') or {}).get('missing_para_ids', [])})
    ph += [{'item': src_text.get('term'), 'reason': '术语译名未在该段落地', 'locator': src_text.get('locator')} for src_text in report.get('term_issues') or []]
    ph += [{'item': 'number:' + ','.join(chunk_txt.get('missing', [])[:5]), 'reason': '数字/单位未在译文出现，需核对', 'locator': chunk_txt.get('locator')} for chunk_txt in report.get('number_issues') or []]
    res_obj = result_skeleton(case_token, contract_fields, status, ver)
    res_obj.update({'sources': [{dict_key: mat.get(dict_key) for dict_key in ('id', 'name', 'path', 'kind', 'quality', 'note')} for mat in para_record.get('materials', [])], 'uncertainty': unc, 'pending_human': ph, 'errors': error_list, 'degradations': degradations + (para_record.get('warnings') or []), 'changes': log_entries[:200], 'term_issues': (report.get('term_issues') or [])[:50], 'number_issues': (report.get('number_issues') or [])[:50], 'quote_issues': (report.get('quote_issues') or [])[:50], 'metrics': {'materials': len(para_record.get('materials', [])), 'paragraphs_total': unit_total, 'paragraphs_translated': unit_total - open_units, 'coverage': (report.get('coverage') or {}).get('ratio'), 'glossary_terms': len(term_entries), 'facts_checked': produced.pop('_facts', 0), 'facts_missing_in_target': produced.pop('_miss', 0), 'check_verdict': report.get('verdict')}, 'runtime': {'skill_version': ver, 'python': sys.version.split()[0], 'finished': utc_stamp(), 'elapsed_sec': round(elapsed, 2), 'phase': 'build'}})
    for dict_key, val in produced.items():
        if dict_key in res_obj:
            res_obj[dict_key] = val
    for dict_key in contract_fields if isinstance(contract_fields, dict) else {}:
        if dict_key not in ('case_id', 'status'):
            res_obj[dict_key] = contract_value(dict_key, produced)
    lk = {}
    if isinstance(contract_fields, dict):
        lk = {str(dict_key).lower(): dict_key for dict_key in contract_fields}
    if 'result' in lk:
        res_obj[lk['result']] = {'deliverable': produced.get('deliverable'), 'metrics': res_obj.get('metrics'), 'scaffold': 'deterministic fallback kept the package non-empty; Agent draft improves units'}
    if 'claims' in lk:
        res_obj[lk['claims']] = {'evidence_map': 'evidence_map.json', 'units': res_obj['metrics'].get('paragraphs_total'), 'facts_checked': res_obj['metrics'].get('facts_checked')}
    if 'uncertainties' in lk:
        res_obj[lk['uncertainties']] = unc
    if 'preserved_facts' in lk:
        res_obj[lk['preserved_facts']] = {'file': 'preserved_facts.json', 'count': res_obj['metrics'].get('facts_checked')}
    if 'evidence_map' in lk:
        res_obj[lk['evidence_map']] = {'file': 'evidence_map.json', 'units': res_obj['metrics'].get('paragraphs_total')}
    if 'change_log' in lk:
        res_obj[lk['change_log']] = {'file': 'change_log.json', 'entries': len(log_entries)}
    return res_obj

def persist_result(output_dir, res_obj, error_list):
    for src_text in (Path(output_dir) / 'result.json', Path(output_dir) / 'result.partial.json'):
        try:
            dump_json(src_text, res_obj)
            return src_text
        except Exception as err_obj:
            error_list.append('result.json write failed (%s): %s' % (src_text, err_obj))
    return None
if __name__ == '__main__':
    print('corpus.py is the helper library; run `python3 runner.py --help` for the CLI.')
    print('shared entry points: read_material, build_index, pick_draft, audit_draft, compose_result')

def locator_map(index):
    """para_id -> locator, used by the audit command."""
    return {entry.get('para_id'): entry.get('locator')
            for entry in index.get('paragraphs') or [] if entry.get('para_id')}


def quality_rates(report):
    """Turn a check report into plain fidelity rates for `audit`."""
    coverage = report.get('coverage') or {}
    expected = coverage.get('expected') or 0
    covered = coverage.get('covered') or 0
    denominator = covered or expected

    def intact(bad_count, total):
        return round(1 - float(bad_count) / total, 4) if total else 1.0

    return {
        'units_expected': expected,
        'units_covered': covered,
        'alignment_coverage': round(covered / expected, 4) if expected else 0.0,
        'quotes_verbatim': intact(len(report.get('quote_issues') or []), denominator),
        'numbers_carried': intact(len(report.get('number_issues') or []), denominator),
        'citations_kept': intact(len(report.get('citation_issues') or []), denominator),
        'terms_locked': intact(len(report.get('term_issues') or []),
                               max(int(report.get('glossary_size') or 0), 1)),
        'glossary_size': int(report.get('glossary_size') or 0),
    }
