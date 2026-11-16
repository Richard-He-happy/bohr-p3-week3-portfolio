#!/usr/bin/env python3
"""Build a source-bound editable schematic with real PNG/PDF exports.

Discovers the case directory, reads every material, calls read_sources to
compose one figure model, renders it through layout_studio, exports through
export_drivers and finally writes result.json with the traceability audit."""
import argparse
import hashlib
import json
import re
import struct
import sys
import time
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

import export_drivers as exporters
from layout_studio import FONT_STACK, arrange_model, measure_text, serialize_svg
from read_sources import (TOOL_VERSION, apply_svg_edits, compose_model,
                           first_value, read_json, scan_materials)


def contract_keys(c):
    if isinstance(c, dict):
        return list(c.keys())
    o = []
    for it in c if isinstance(c, list) else []:
        o += [it] if isinstance(it, str) else [str(it[k]) for k in ('name', 'field', 'key', 'id') if isinstance(it, dict) and it.get(k)]
    return [k for k in dict.fromkeys(o) if k]

def inspect_png(path):
    """Real IHDR + genuine non-white ratio (PNG filters 0-4 undone)."""
    try:
        b = Path(path).read_bytes()
        if b[:8] != b'\x89PNG\r\n\x1a\n':
            return {'ok': False, 'reason': 'not_png_signature'}
        pos, ih, idat = (8, None, b'')
        while pos < len(b) - 8:
            n = struct.unpack('>I', b[pos:pos + 4])[0]
            t = b[pos + 4:pos + 8]
            if t == b'IHDR':
                ih = struct.unpack('>IIBBBBB', b[pos + 8:pos + 21])
            elif t == b'IDAT':
                idat += b[pos + 8:pos + 8 + n]
            pos += 12 + n
        if not ih:
            return {'ok': False, 'reason': 'no_ihdr'}
        w, h, dep, ct = (ih[0], ih[1], ih[2], ih[3])
        r = {'ok': True, 'width': w, 'height': h, 'bit_depth': dep, 'color_type': ct, 'bytes': len(b)}
        if dep != 8 or ct not in (2, 6) or w * h > 12000000:
            return r
        bpp, raw_entities = (3 if ct == 2 else 4, zlib.decompress(idat))
        stride, prev, nw, tot = (w * bpp, bytearray(w * bpp), 0, 0)
        sy, sx = (max(1, h // 60), max(1, w // 60))
        for y in range(h):
            f, ln = (raw_entities[y * (stride + 1)], bytearray(raw_entities[y * (stride + 1) + 1:(y + 1) * (stride + 1)]))
            if f:
                for i in range(stride):
                    a = ln[i - bpp] if i >= bpp else 0
                    if f == 1:
                        ln[i] = ln[i] + a & 255
                    elif f == 2:
                        ln[i] = ln[i] + prev[i] & 255
                    elif f == 3:
                        ln[i] = ln[i] + (a + prev[i] >> 1) & 255
                    else:
                        c, q = (prev[i - bpp] if i >= bpp else 0, None)
                        q = a + prev[i] - c
                        pa, pb, pc = (abs(q - a), abs(q - prev[i]), abs(q - c))
                        ln[i] = ln[i] + (a if pa <= pb and pa <= pc else prev[i] if pb <= pc else c) & 255
            if y % sy == 0:
                for x in range(0, w, sx):
                    o = x * bpp
                    tot += 1
                    nw += 0 if ln[o] > 245 and ln[o + 1] > 245 and (ln[o + 2] > 245) else 1
            prev = ln
        r['nonwhite_ratio'] = round(nw / float(tot or 1), 4)
        r['blank'] = r['nonwhite_ratio'] < 0.004
        return r
    except Exception as e:
        return {'ok': False, 'reason': '%s: %s' % (type(e).__name__, e)}

def inspect_pdf(path):
    try:
        b = Path(path).read_bytes()
        return {'ok': b[:5] == b'%PDF-' and b'%%EOF' in b[-2048:], 'bytes': len(b), 'pages': b.count(b'/Type/Page') - b.count(b'/Type/Pages') + b.count(b'/Type /Page') - b.count(b'/Type /Pages ')}
    except Exception as e:
        return {'ok': False, 'reason': '%s: %s' % (type(e).__name__, e)}

def build_content_map(m, svg_text):
    """content_map (element -> source + verbatim quote) plus the machine checks, from one model."""
    ids = {e.get('id') for e in ET.fromstring(svg_text).iter() if e.get('id')}
    entity_list = [{'id': e['id'], 'label': e['label'], 'entity_type': e.get('type') or 'entity', 'verified': bool(e.get('verified')), 'svg_ids': ['ent-' + e['id']] + (['lbl-' + e['id']] if len(e['lines']) == 1 else ['lbl-%s-%d' % (e['id'], i + 1) for i in range(len(e['lines']))]), 'source': e.get('source')} for e in m['entities']]
    relation_list = [{'id': r['id'], 'svg_id': 'edge-' + r['id'], 'from': r['from'], 'to': r['to'], 'relation_type': r['type'], 'marker': r.get('marker'), 'direction': r.get('direction'), 'route': r.get('route'), 'verified': r.get('verified'), 'source': r.get('source')} for r in m['relations']]
    legend_items = [{'id': l['id'], 'kind': l['kind'], 'label': l['label'], 'color': l['color'], 'svg_id': 'lg-' + l['id'], 'encoding': l.get('marker') or 'colour swatch'} for l in m['legend']]
    dp, ch = ([], m.get('chart'))
    if ch:
        for ci, cat in enumerate(ch['categories']):
            for si, s in enumerate(ch['series']):
                dp.append({'id': 'bar-%d-%d' % (ci + 1, si + 1), 'category': cat, 'series': s['name'], 'unit': s['unit'], 'value': s['values'][ci], 'source': {'kind': 'table', 'source_id': ch['table']['id'], 'locator': '%s#row=%d,col=%s' % (ch['table']['id'], ci + 2, s['name']), 'quote': ch['quotes'][si][ci]}})
    export_result = [s for e in entity_list for s in e['svg_ids']] + [r['svg_id'] for r in relation_list] + [l['svg_id'] for l in legend_items] + [d['id'] for d in dp]
    mp = sum((1 for e in entity_list if e['verified'] and e['source']))
    content_map = {'entities': entity_list, 'relations': relation_list, 'legend': legend_items, 'data_points': dp, 'coverage': {'required_entities': len(entity_list), 'mapped_entities': mp, 'required_relations': len(relation_list), 'legend_items': len(legend_items), 'entity_coverage': round(mp / float(len(entity_list) or 1), 3), 'complete': mp == len(entity_list)}, 'svg_ids_expected': export_result, 'svg_sha256': hashlib.sha256(svg_text.encode()).hexdigest(), 'svg_sha256_recheck': hashlib.sha256(serialize_svg(json.loads(json.dumps(m))).encode()).hexdigest()}
    st, cv = (m['style'], m['canvas'])
    bx = [e['box'] for e in m['entities']]
    overlap_pairs = sum((1 for i in range(len(bx)) for j in range(i + 1, len(bx)) if bx[i]['x'] < bx[j]['x'] + bx[j]['w'] - 1 and bx[j]['x'] < bx[i]['x'] + bx[i]['w'] - 1 and (bx[i]['y'] < bx[j]['y'] + bx[j]['h'] - 1) and (bx[j]['y'] < bx[i]['y'] + bx[i]['h'] - 1)))
    W, H, marker_count = (cv['width'], cv['height'], len(set(re.findall('<marker id="([^"]+)"', svg_text))))
    outside = sum((1 for b in bx if b['x'] < 0 or b['y'] < 0 or b['x'] + b['w'] > W + 0.5 or (b['y'] + b['h'] > H + 0.5)))
    tight = sum((1 for e in m['entities'] if max([measure_text(x, st['font_pt']['label']) for x in e['lines']] or [0]) > e['box']['w'] - 8))
    used, series_count, miss = ({r['type'] for r in m['relations']}, len((m.get('chart') or {}).get('series') or []), [s for s in export_result if s not in ids])
    audit = {'canvas': {'ok': 0 < W <= 4000 and 0 < H <= 4000, 'width_px': W, 'height_px': H}, 'svg_wellformed': {'ok': svg_text.count('<text') > 0 and len([i for i in ids if i.startswith('layer-')]) >= 4, 'layers': sorted((i for i in ids if i.startswith('layer-'))), 'text_elements': svg_text.count('<text'), 'marker_defs': marker_count}, 'id_map': {'ok': not miss, 'content_map_ids': len(export_result), 'missing': miss[:8]}, 'labels_verbatim': {'ok': all((e.get('verified') for e in m['entities'])), 'unverified': [e['label'] for e in m['entities'] if not e.get('verified')]}, 'style': {'ok': min(st['font_pt'].values()) >= 6 and 0.4 <= st['line_width'] <= 3, 'family': FONT_STACK, 'sizes_pt': st['font_pt'], 'line_width_pt': st['line_width']}, 'fonts': {'ok': min(st['font_pt'].values()) >= 6, 'family': FONT_STACK, 'sizes_pt': st['font_pt']}, 'line_widths': {'ok': 0.4 <= st['line_width'] <= 3, 'pt': st['line_width']}, 'markers': {'ok': marker_count >= 2, 'distinct_markers': marker_count, 'relation_types': sorted(used)}, 'legend_consistency': {'ok': len([l for l in legend_items if l['kind'] == 'relation']) == len(used) and len(legend_items) == len(used) + series_count, 'legend_items': len(legend_items), 'encoding_categories': len(used) + series_count}, 'overlap': {'ok': overlap_pairs == 0, 'pairs': overlap_pairs}, 'overflow': {'ok': outside == 0 and tight == 0, 'outside_canvas': outside, 'text_overflow': tight}, 'determinism': {'ok': content_map['svg_sha256'] == content_map['svg_sha256_recheck']}}
    audit['pass'] = all((v['ok'] for v in audit.values() if isinstance(v, dict) and isinstance(v.get('ok'), bool)))
    audit['failures'] = [k for k, v in audit.items() if isinstance(v, dict) and v.get('ok') is False]
    return (content_map, audit)

def audit_locators(figure_model, input_dir):
    checked, missing = 0, []
    for item in list(figure_model.get('entities') or []) + list(figure_model.get('relations') or []):
        src = item.get('source') or {}
        if not isinstance(src, dict) or src.get('kind') in (None, 'workorder'):
            continue
        locator = str(src.get('locator') or '')
        file_part = locator.split('#')[0]
        if not file_part:
            continue
        checked += 1
        if not (Path(input_dir) / file_part).is_file():
            missing.append(locator)
    return {'ok': not missing, 'checked': checked, 'missing': missing[:8]}

def write_json(p, o):
    Path(p).write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding='utf-8')

def run(argv=None):
    started_at = time.time()
    parser = argparse.ArgumentParser(prog='figure-lineage', description=__doc__.split('\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog='Writes figure.svg (layered, live text), figure.png and figure.pdf (real exports), figure_model.json, edit_record.json for edit cases, and result.json. The process always exits with code 0.')
    parser.add_argument('--input', help='case directory; defaults to /input, /app/input or ./input')
    parser.add_argument('--output', help='artifact directory; defaults to /app/output or ./output')
    parser.add_argument('--case', help='explicit path to a case.json instead of auto-discovery')
    a = parser.parse_args(argv)
    input_dir = Path(a.case).parent if a.case else Path(next((p for p in [a.input, '/input', '/app/input', 'input'] if p and Path(p).is_dir()), '.'))
    output_dir = Path(a.output or ('/app/output' if Path('/app').is_dir() else 'output'))
    output_dir.mkdir(parents=True, exist_ok=True)
    case_path = Path(a.case) if a.case else next((p for p in [input_dir / 'case.json', input_dir / 'input' / 'case.json'] if p.exists()), None)
    case_path = case_path or next(iter(sorted(input_dir.glob('**/case*.json'))), None)
    case_raw = read_json(case_path) if case_path else {}
    broken_case = bool(case_path) and (not isinstance(case_raw, dict))
    case_doc = case_raw if isinstance(case_raw, dict) else {}
    contract_fields, exception_log = (contract_keys(first_value(case_doc, 'output_contract', default=[])), [])
    payload = {'case_id': first_value(case_doc, 'case_id', 'id'), 'status': 'partial', 'editable_source': None, 'export_artifact': None, 'content_map': None, 'compliance_checks': None, 'exceptions': [], 'sources': [], 'uncertainty': [], 'pending_human': [], 'errors': [], 'degradations': [], 'changes': [], 'output_contract_echo': first_value(case_doc, 'output_contract', default=[]), 'runtime': {'script': 'build_figure.py', 'version': TOOL_VERSION, 'python': sys.version.split()[0], 'started': time.strftime('%Y-%m-%dT%H:%M:%S')}}
    for k in contract_fields:
        payload.setdefault(k, None)
    write_json(output_dir / 'result.json', payload)
    try:
        material_docs, table_docs, read_notes = scan_materials(input_dir)
        payload['errors'] = read_notes + (['case.json could not be parsed as a JSON object; continuing with empty case'] if broken_case else [])
        workorder = first_value(case_doc, 'organizer_workorder', 'workorder', 'figure_workorder') or {}
        if not isinstance(workorder, dict) or not workorder:
            workorder = first_value(read_json(next(iter(sorted(input_dir.glob('**/*workorder*.json'))), None) or ''), 'workorder', 'figure_workorder', default={}) or {}
        if not workorder:
            workorder = first_value(read_json(next((p for p in sorted(input_dir.glob('**/material.json'))), None) or ''), 'workorder', 'figure', default={}) or {}
        if not workorder:
            exception_log.append({'type': 'workorder_missing', 'object': 'workorder', 'locator': None, 'reason': 'no organizer workorder in case.json or anywhere in the input tree', 'action': 'model composed from material sentences; extraction heuristics apply'})
        payload['sources'] = [{'id': d['id'], 'kind': d['kind'], 'chars': len(d['text'])} for d in material_docs] + [{'id': 'table:' + t['id'], 'kind': 'table', 'rows': len(t['rows']), 'cols': len(t['header'])} for t in table_docs]
        if not material_docs and (not table_docs):
            raise LookupError('no readable material under %s' % input_dir)
        figure_model, render_mode = compose_model(workorder, material_docs, table_docs, exception_log)
        if not figure_model['entities'] and (not figure_model.get('chart')):
            exception_log.append({'type': 'no_drawable_content', 'object': 'figure', 'locator': None, 'reason': 'no entity/relation/table could be read from the materials', 'action': 'empty canvas written; supply a workorder or readable source text'})
        baseline_file = first_value(workorder, 'source_artifact', 'baseline', 'base_figure')
        baseline_file = Path(str(baseline_file)) if baseline_file and Path(str(baseline_file)).is_file() else next(iter(sorted(input_dir.glob('**/*.svg'))), None)
        if baseline_file and Path(baseline_file).suffix.lower() == '.svg':
            figure_model, render_mode = apply_svg_edits(figure_model, Path(baseline_file), workorder, output_dir, exception_log, payload)
        arrange_model(figure_model)
        svg_text = serialize_svg(figure_model)
        (output_dir / 'figure.svg').write_text(svg_text, encoding='utf-8')
        export_result = {'png': None, 'pdf': None, 'engines': {}, 'degradations': []}
        if render_mode == 'edited':
            for f in ('png', 'pdf'):
                eng = exporters.convert_via_engine(output_dir / 'figure.svg', output_dir / ('figure.' + f), png_w=int(figure_model['canvas']['width'] * 2))
                if eng:
                    export_result[f], export_result['engines'][f] = (output_dir / ('figure.' + f), eng)
                else:
                    export_result['degradations'].append({'artifact': f, 'engine': None, 'status': 'missing', 'reason': 'an edited baseline needs an SVG converter; matplotlib would redraw other geometry'})
        else:
            export_result = exporters.write_exports(figure_model, output_dir, dpi=300)
        payload['degradations'] += export_result['degradations']
        content_map, audit = build_content_map(figure_model, svg_text)
        audit['source_locators'] = audit_locators(figure_model, input_dir)
        figure_model['export'] = {'formats': ['svg'] + [f for f in ('png', 'pdf') if export_result.get(f)], 'dpi': 300, 'color_space': 'RGB', 'engines': export_result['engines']}
        write_json(output_dir / 'figure_model.json', figure_model)
        if render_mode == 'edited':
            audit['edited_source'] = {'ok': bool(payload.get('changes')), 'changes': len(payload.get('changes') or [])}
            audit['pass'] = bool(payload.get('changes'))
            audit['failures'] = [k for k, v in audit.items() if isinstance(v, dict) and v.get('ok') is False]
        export_meta = {}
        for f in ('png', 'pdf'):
            p = export_result.get(f)
            if p:
                probe = inspect_png(p) if f == 'png' else inspect_pdf(p)
                export_meta[f] = {'path': str(p), 'engine': export_result['engines'].get(f), 'width': probe.get('width'), 'height': probe.get('height'), 'dpi': 300 if f == 'png' else None, 'pages': probe.get('pages'), 'bytes': p.stat().st_size, 'color_space': 'RGB', 'probe': probe}
            else:
                export_meta[f] = {'path': None, 'engine': None, 'status': 'missing'}
        for f, k in (('png', 'pixel_probe'), ('pdf', 'pdf_probe')):
            audit[k] = export_meta[f].get('probe') or {'ok': None, 'reason': 'no_' + f}
        if render_mode != 'edited':
            audit['pass'] = bool(audit['pass']) and audit['source_locators']['ok'] and all((audit[k].get('ok') is not False for k in ('pixel_probe', 'pdf_probe')))
            audit['failures'] = [k for k, v in audit.items() if isinstance(v, dict) and v.get('ok') is False]
        payload.update({'export_artifact': export_meta, 'content_map': content_map, 'compliance_checks': audit, 'exceptions': exception_log, 'editable_source': {'path': str(output_dir / 'figure.svg'), 'format': 'svg', 'editable': True, 'text_live': True, 'layers': figure_model['layers'], 'element_count': len(re.findall(' id="', svg_text)), 'text_count': svg_text.count('<text'), 'marker_types': sorted(set(re.findall('<marker id="mk-([^"]+)"', svg_text))), 'sha256': hashlib.sha256(svg_text.encode()).hexdigest(), 'mode': render_mode, 'coordinate_system': '%dx%d px' % (figure_model['canvas']['width'], figure_model['canvas']['height'])}})
        payload['pending_human'] = [{'item': e['label'], 'why': 'label not verifiable in the provided sources', 'action': 'confirm the name or supply the missing source'} for e in figure_model['entities'] if not e.get('verified')]
        payload['uncertainty'] = [{'topic': 'layout', 'detail': 'deterministic heuristic placement, not a curated journal layout'}]
        if render_mode == 'extracted':
            payload['uncertainty'].append({'topic': 'extraction', 'detail': 'relations parsed by sentence patterns; modality, timing and conditions are not modelled'})
        if render_mode == 'edited':
            payload['uncertainty'].append({'topic': 'edit', 'detail': 'only workorder-named elements were touched'})
        ok = bool(export_result.get('png') or export_result.get('pdf')) and audit.get('pass') is not False
        ok = ok and (render_mode == 'edited' or all((e.get('verified') for e in figure_model['entities'])))
        payload['status'] = 'ok' if ok else 'partial'
        if not ok:
            payload['uncertainty'].append({'topic': 'status', 'detail': 'partial: see compliance_checks.failures / degradations'})
    except Exception as e:
        payload['status'] = 'input_error'
        payload['errors'] = (payload.get('errors') or []) + ['%s: %s' % (type(e).__name__, e)]
        payload['exceptions'] = payload.get('exceptions') or [{'type': 'no_result', 'object': 'figure', 'reason': 'case/workorder/material could not be read', 'action': 'nothing produced; see errors'}]
    finally:
        payload['runtime'].update({'elapsed_s': round(time.time() - started_at, 2), 'contract_fields': len(contract_fields), 'input_dir': str(input_dir), 'output_dir': str(output_dir)})
        for k in contract_fields:
            payload.setdefault(k, None)
        write_json(output_dir / 'result.json', payload)
    return 0


if __name__ == "__main__":
    sys.exit(run())
