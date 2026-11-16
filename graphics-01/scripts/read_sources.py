#!/usr/bin/env python3
"""Input reading, relation mining and figure-model composition for figure-lineage.

Only the standard library is used. The module never writes files: it returns a
single figure model that downstream modules render, export and audit."""
import csv
import io
import json
import re
import shutil
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
import hashlib
from pathlib import Path

from layout_studio import LAYER_ORDER


TOOL_VERSION, FIG_KIND = ('1.0.0', 'relationship_schematic')
VERB_TABLE = [('activation', 'activates?|activated|promotes?|induces?|upregulates?|up-regulates?|stimulates?|enhances?|促进|激活|上调|诱导|增强', 'activation', '#0072B2'), ('inhibition', 'inhibits?|inhibited|suppress(?:es|ed)?|repress(?:es|ed)?|blocks?|downregulates?|down-regulates?|attenuates?|抑制|下调|阻遏|阻断', 'inhibition', '#D55E00'), ('binding', 'binds?|binding|interacts? with|forms? a complex|recruits?|结合|互作|相互作用|复合物|招募', 'binding', '#009E73'), ('phosphorylation', 'phosphorylates?|phosphorylated|phosphorylation|磷酸化', 'activation', '#CC79A7'), ('expression', 'expresses?|encoded? by|encodes?|表达|编码', 'activation', '#56B4E9'), ('containment', 'contains?|includes?|comprises?|consists? of|is part of|subunit of|包含|包括|属于', 'activation', '#8d979f'), ('conversion', 'converts?|converted to|produces?|generates?|yields?|转化为|生成', 'activation', '#E69F00'), ('causal', 'leads? to|results? in|causes?|caused by|therefore|thus|hence|导致|引起|因此', 'activation', '#333333'), ('causal2', 'subsequently|随后|之后|接着', 'activation', '#999999')]
STYLE = {'font_pt': {'title': 11.0, 'label': 8.5, 'legend': 7.0}, 'line_width': 1.2, 'entity_fill': '#F2F7FB', 'entity_stroke': '#0B5F8A', 'palette': ['#0072B2', '#E69F00', '#009E73', '#CC79A7', '#D55E00', '#56B4E9', '#117733', '#333333'], 'rel_marker': {t: m for t, _p, m, _c in VERB_TABLE}, 'rel_color': {t: c for t, _p, _m, c in VERB_TABLE}}
PASSIVE_LEAD, PAREN_UNIT = (re.compile('^\\s*(is|are|was|were|been|被|受到|由)\\s*', re.I), re.compile('[\\(\\[]([^)\\]]+)[\\)\\]]'))
TOKEN_RX = re.compile('[A-Za-z][A-Za-z0-9\\-]{1,15}|[\\u4e00-\\u9fa5]{2,8}')
READABLE_SUFFIX = ('.md', '.txt', '.csv', '.tsv', '.json', '.yaml', '.yml', '.tex', '.xml')
RESERVED_NAMES = ('result.json', 'figure_model.json', 'edit_record.json')

def canon_text(s):
    return re.sub('[\\s\\u00a0]+', ' ', unicodedata.normalize('NFKC', str(s or '')).lower()).strip()

def first_value(d, *ns, default=None):
    """Semantic key lookup: exact, *_name, name_*; case-insensitive; empty values skipped."""
    if not isinstance(d, dict):
        return default
    low = {str(k).lower(): v for k, v in d.items()}
    for n in ns:
        for k, v in low.items():
            if (k == n or k.endswith('_' + n) or k.startswith(n)) and v not in (None, '', [], {}):
                return v
    return default

def read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8', errors='replace'))
    except Exception:
        return None

def pdf_to_text(p):
    """PDF text via pdftotext (poppler); the caller records when it is unavailable."""
    exception_log = shutil.which('pdftotext')
    if exception_log:
        try:
            r = subprocess.run([exception_log, '-layout', '-enc', 'UTF-8', str(p), '-'], capture_output=True, timeout=120)
            if r.returncode == 0 and r.stdout.strip():
                return (r.stdout.decode('utf-8', 'replace'), 'pdftotext')
        except Exception:
            pass
    return ('', 'no_text_layer')

def scan_materials(root):
    material_docs, table_docs, read_notes = ([], [], [])
    for p in sorted(Path(root).rglob('*')):
        if not p.is_file() or p.stat().st_size > 8000000:
            continue
        rel = str(p.relative_to(root))
        if rel.split('/')[0] in ('output', 'work') or p.name in RESERVED_NAMES:
            continue
        e, txt = (p.suffix.lower(), '')
        try:
            if e in READABLE_SUFFIX:
                txt = p.read_text(encoding='utf-8', errors='replace')
            elif e == '.pdf':
                txt, how = pdf_to_text(p)
                if how != 'pdftotext':
                    read_notes.append('%s:%s' % (how, rel))
            else:
                if e in ('.xlsx', '.xlsm', '.docx'):
                    read_notes.append('unsupported_source:' + rel)
                continue
            if e in ('.csv', '.tsv'):
                data_rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(txt)) if any((c.strip() for c in r))]
                if len(data_rows) > 1:
                    table_docs.append({'id': rel, 'header': data_rows[0], 'rows': data_rows[1:]})
            if txt.strip():
                material_docs.append({'id': rel, 'kind': e[1:], 'text': txt, 'lines': txt.splitlines()})
        except Exception as exc:
            read_notes.append('read_failed:%s:%s' % (rel, type(exc).__name__))
    return (material_docs, table_docs, read_notes)

def find_quote(material_docs, label):
    n = canon_text(label)
    if len(n) < 2:
        return (None, False)
    for d in material_docs:
        for i, ln in enumerate(d['lines'], 1):
            if n in canon_text(ln):
                q = ln.strip()
                q = q if len(q) <= 300 else ln[max(0, canon_text(ln).find(n) - 60):][:300]
                w = '%s#L%d' % (d['id'], i)
                if d['kind'] == 'pdf':
                    w = '%s#p%d+L%d' % (d['id'], d['text'].count('\x0c', 0, sum((len(x) + 1 for x in d['lines'][:i - 1]))) + 1, i)
                return ({'kind': d['kind'], 'source_id': d['id'], 'locator': w, 'quote': q}, True)
    return (None, False)

def edge_token(ch, head):
    t = TOKEN_RX.findall(ch)
    if not t:
        return ''
    v = t[-1] if head else t[0]
    return (t[-2] + ' ' + v if head and len(t) > 1 and v[:1].islower() and t[-2][:1].isupper() else v).strip(' -')

def infer_relations(material_docs):
    entity_list, relation_list, token_ids = ([], [], {})
    for d in material_docs:
        for ln in d['lines']:
            if not 6 < len(ln) < 500:
                continue
            for typ, pat, _m, _c in VERB_TABLE:
                for m in re.finditer(pat, ln, re.I):
                    h, t = (edge_token(ln[:m.start()], True), edge_token(ln[m.end():], False))
                    if len(h) < 2 or len(t) < 2 or canon_text(h) == canon_text(t):
                        continue
                    if PASSIVE_LEAD.match(ln[m.end():m.end() + 14]):
                        h, t = (t, h)
                    for lab in (h, t):
                        if canon_text(lab) not in token_ids and len(entity_list) < 16:
                            token_ids[canon_text(lab)] = 'e%d' % (len(entity_list) + 1)
                            entity_list.append({'id': token_ids[canon_text(lab)], 'label': lab})
                    if len(relation_list) < 22 and (token_ids[canon_text(h)], token_ids[canon_text(t)], typ) not in {(r['from'], r['to'], r['type']) for r in relation_list}:
                        relation_list.append({'id': 'r%d' % (len(relation_list) + 1), 'from': token_ids[canon_text(h)], 'to': token_ids[canon_text(t)], 'type': typ})
    return (entity_list, relation_list)

def compose_model(workorder, material_docs, table_docs, exception_log):
    raw_entities = first_value(workorder, 'required_entities', 'entities', 'nodes', default=[]) or []
    if isinstance(raw_entities, dict):
        raw_entities = [dict(v, id=k) if isinstance(v, dict) else {'id': k, 'label': v} for k, v in raw_entities.items()]
    entity_list = []
    for i, e in enumerate(raw_entities if isinstance(raw_entities, list) else []):
        lab = e if isinstance(e, str) else first_value(e, 'label', 'name', 'text', 'term', 'id')
        if lab:
            entity_list.append({'id': str(first_value(e, 'id', 'key', default='e%d' % (i + 1))) if isinstance(e, dict) else 'e%d' % (i + 1), 'label': str(lab), 'type': first_value(e, 'entity_type', 'type', 'kind') if isinstance(e, dict) else None})
    relation_list, render_mode = ([], 'workorder' if entity_list else 'extracted')
    if entity_list:
        entity_by_id = {canon_text(e['label']): e['id'] for e in entity_list}
        entity_by_id.update({canon_text(e['id']): e['id'] for e in entity_list})
        for i, r in enumerate(first_value(workorder, 'required_relations', 'relations', 'edges', 'links', default=[]) or []):
            if isinstance(r, str):
                m = re.split('\\s*(?:->|→|=>|-\\\\|⊣|\\|)\\s*', r)
                m = m if len(m) > 1 else re.split('\\s+(?:activates?|inhibits?|promotes?)\\s+', r, flags=re.I)
                if len(m) >= 2:
                    relation_list.append({'id': 'r%d' % (i + 1), 'from': entity_by_id.get(canon_text(m[0]), m[0]), 'to': entity_by_id.get(canon_text(m[-1]), m[-1]), 'type': 'inhibition' if re.search('inhibit|抑制|-\\\\|⊣', r, re.I) else 'activation'})
            elif isinstance(r, dict):
                a, b = (first_value(r, 'from', 'source', 'src', 'subject'), first_value(r, 'to', 'target', 'object', 'tail'))
                if a and b:
                    relation_list.append({'id': 'r%d' % (i + 1), 'from': entity_by_id.get(canon_text(a), str(a)), 'to': entity_by_id.get(canon_text(b), str(b)), 'type': str(first_value(r, 'relation_type', 'type', 'predicate', default='activation')).lower(), 'label': first_value(r, 'label', 'text'), 'direction': first_value(r, 'direction')})
    else:
        entity_list, relation_list = infer_relations(material_docs)
    workorder_text = json.dumps(workorder, ensure_ascii=False) if workorder else ''
    for e in entity_list:
        s, ok = find_quote(material_docs, e['label'])
        if not ok and workorder_text and (canon_text(e['label']) in canon_text(workorder_text)):
            s, ok = ({'kind': 'workorder', 'source_id': 'workorder', 'locator': 'workorder#required_entities', 'quote': e['label']}, True)
        e['source'], e['verified'] = (s, bool(ok))
        if not ok:
            exception_log.append({'type': 'label_not_in_source', 'object': e['label'], 'locator': None, 'reason': 'not found verbatim in any provided material', 'action': 'kept but flagged unverified; confirm before publication'})
    verified_ids = {e['id'] for e in entity_list if e['verified']}
    for r in relation_list:
        r['verified'] = r['from'] in verified_ids and r['to'] in verified_ids
        r['type'] = r['type'] if r['type'] in STYLE['rel_marker'] else 'activation'
        r['direction'] = r.get('direction') or 'forward'
        r['source'] = next((e['source'] for e in entity_list if e['id'] == r['from']), None) if r['verified'] else None
        if not r['verified']:
            exception_log.append({'type': 'relation_unverified', 'object': '%s-%s' % (r['from'], r['to']), 'reason': 'an endpoint is unverified or absent', 'action': 'excluded from the figure'})
    relation_list = [r for r in relation_list if r['verified']]
    chart_spec = None
    for t in [] if relation_list else table_docs:
        header_cells, data_rows = (t.get('header') or [], t.get('rows') or [])
        if len(header_cells) < 2 or len(data_rows) < 2:
            continue
        series_spec = []
        for ci in range(1, len(header_cells)):
            try:
                v = [float(str(r[ci] if ci < len(r) else '').replace(',', '').strip()) for r in data_rows]
            except Exception:
                continue
            u = PAREN_UNIT.search(str(header_cells[ci]))
            series_spec.append({'name': PAREN_UNIT.sub('', str(header_cells[ci])).strip() or 'value', 'unit': u.group(1).strip() if u else '', 'values': v, 'quote': [str(r[ci] if ci < len(r) else '') for r in data_rows]})
        if series_spec:
            chart_spec = {'title': str(first_value(workorder, 'figure_title', 'title', default='') or t['id']), 'table': t, 'categories': [str(r[0]) for r in data_rows], 'quotes': [s['quote'] for s in series_spec], 'series': [{'name': s['name'], 'unit': s['unit'], 'values': s['values']} for s in series_spec]}
            break
    series_count = len((chart_spec or {}).get('series') or [])
    legend_items = [{'id': 'l%d' % (i + 1), 'kind': 'relation', 'label': t, 'marker': STYLE['rel_marker'][t], 'color': STYLE['rel_color'][t]} for i, t in enumerate(dict.fromkeys((r['type'] for r in relation_list)))]
    for i, s in enumerate((chart_spec or {}).get('series') or []):
        legend_items.append({'id': 'l%d' % (len(legend_items) + 1), 'kind': 'series', 'label': s['name'] + (' (%s)' % s['unit'] if s['unit'] else ''), 'color': STYLE['palette'][(i + (series_count > 1)) % 8]})
    return ({'schema': 'figure-model/1.0', 'figure_id': str(first_value(workorder, 'figure_id', 'id', default='figure') or 'figure'), 'kind': 'data_chart' if chart_spec and (not relation_list) else FIG_KIND + '+chart' if chart_spec else FIG_KIND, 'title': str(first_value(workorder, 'figure_title', 'title', default='') or ''), 'entities': entity_list, 'relations': relation_list, 'legend': legend_items, 'chart': chart_spec, 'layers': list(LAYER_ORDER), 'extraction_mode': render_mode, 'canvas': {'width': 1200, 'height': 760, 'unit': 'px', 'background': '#FFFFFF'}, 'style': json.loads(json.dumps(STYLE))}, render_mode)

def apply_svg_edits(m, baseline_file, workorder, out, exception_log, payload):
    """Source-preserving edit: keep ids/layers/coordinates, replace only the workorder-named labels."""
    raw_entities = baseline_file.read_text(encoding='utf-8', errors='replace')
    try:
        root = ET.fromstring(raw_entities.encode('utf-8'))
    except Exception as e:
        exception_log.append({'type': 'baseline_unparsable', 'object': baseline_file.name, 'reason': str(e), 'action': 'generated a new SVG instead'})
        return (m, 'generated')
    done = []
    for op in first_value(workorder, 'edit_operations', 'edits', 'changes', default=[]) or []:
        if not isinstance(op, dict):
            continue
        eid = str(first_value(op, 'target', 'element_id', 'id', 'selector', default='') or '')
        new, old = (first_value(op, 'new_label', 'new_text', 'text', 'value'), first_value(op, 'old_label', 'old_text', 'from'))
        for el in root.iter():
            if not str(el.tag).endswith('text'):
                continue
            cur = ''.join(el.itertext())
            if eid and el.get('id') == eid or (old and canon_text(cur) == canon_text(old)):
                if new:
                    el.text = str(new)
                    done.append({'element_id': el.get('id'), 'original': cur, 'revised': str(new), 'locator': '%s#%s' % (baseline_file.name, el.get('id'))})
                break
    if not done:
        exception_log.append({'type': 'no_edit_applied', 'object': baseline_file.name, 'reason': 'no operation matched an id or label', 'action': 'baseline preserved unchanged'})
    t = ET.tostring(root, encoding='unicode')
    t = t if t.lstrip().startswith('<?xml') else '<?xml version="1.0" encoding="UTF-8"?>\n' + t
    (out / 'figure.svg').write_text(t, encoding='utf-8')
    (out / 'edit_record.json').write_text(json.dumps({'baseline': {'path': str(baseline_file), 'sha256': hashlib.sha256(raw_entities.encode()).hexdigest()}, 'revised': {'path': str(out / 'figure.svg'), 'sha256': hashlib.sha256(t.encode()).hexdigest()}, 'changes': done, 'preserved': ['element ids', 'layer groups', 'coordinates', 'styles']}, ensure_ascii=False, indent=2), encoding='utf-8')
    payload['changes'] = done
    return (m, 'edited')
