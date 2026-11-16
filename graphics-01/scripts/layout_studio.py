#!/usr/bin/env python3
"""Deterministic layout, layered SVG serialisation and geometry helpers.

The output is a single SVG string whose element ids are stable and whose text
stays live, so content_map can address every element by id."""
import math
import re


FONT_STACK = "Arial, Helvetica, 'DejaVu Sans', sans-serif"
CJK_RX = re.compile('[\\u2e80-\\u9fff\\uff00-\\uffef]')
INK_COLOR = '#111111'
LAYER_ORDER = ['background', 'panels', 'edges', 'entities', 'labels', 'legend', 'title']
MARKER_DEFS = '<marker id="mk-activation" refX="8" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#333333"/></marker><marker id="mk-inhibition" refX="9" refY="5" markerWidth="10" markerHeight="10" markerUnits="userSpaceOnUse" orient="auto"><path d="M9,0 L9,10" stroke="#333333" stroke-width="2"/></marker><marker id="mk-binding" refX="9" refY="4" markerWidth="9" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto"><path d="M0,4 L4.5,0 L9,4 L4.5,8 z" fill="#333333"/></marker>'

def measure_text(s, size):
    return sum((1.0 if CJK_RX.match(c) else 0.55 for c in str(s))) * size

def xml_escape(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def break_label(label, maxch=22):
    label, words = (str(label), str(label).split())
    if len(label) <= maxch:
        return [label]
    if len(words) == 1:
        return [label[i:i + maxch] for i in range(0, len(label), maxch)]
    lines, cur = ([], '')
    for w in words:
        t = (cur + ' ' + w).strip() if cur else w
        if len(t) <= maxch:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])

def format_number(v):
    f = float(v)
    return str(int(round(f))) if abs(f - round(f)) < 1e-09 else ('%.3f' % f).rstrip('0').rstrip('.')

def parse_color(h):
    h = (h or '#000000').lstrip('#')
    h = ''.join((c * 2 for c in h)) if len(h) == 3 else h
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return (0, 0, 0)

def make_rect(i, layer, x, y, w, h, fill=None, stroke=None, lw=1.0, rx=0, dash=None, data=None):
    return {'k': 'rect', 'id': i, 'layer': layer, 'x': float(x), 'y': float(y), 'w': float(w), 'h': float(h), 'fill': fill, 'stroke': stroke, 'lw': lw, 'rx': rx, 'dash': dash, 'data': data or {}}

def make_path(i, layer, points, fill=None, stroke=None, lw=1.0, dash=None, closed=False, marker=None, data=None):
    return {'k': 'poly', 'id': i, 'layer': layer, 'pts': [[float(a), float(b)] for a, b in points], 'fill': fill, 'stroke': stroke, 'lw': lw, 'dash': dash, 'closed': closed, 'marker': marker, 'data': data or {}}

def make_text(i, layer, x, y, s, size, anchor='middle', fill=INK_COLOR, weight='normal', data=None):
    return {'k': 'text', 'id': i, 'layer': layer, 'x': float(x), 'y': float(y), 's': str(s), 'size': size, 'anchor': anchor, 'fill': fill, 'weight': weight, 'data': data or {}}

def terminal_marker(points, kind, color):
    """Marker glyph from the last segment; matches the SVG <marker> shapes."""
    (x1, y1), (x2, y2) = (points[-2], points[-1])
    a = math.atan2(y2 - y1, x2 - x1) if (x2, y2) != (x1, y1) else 0.0
    if kind == 'inhibition':
        px, py = (-math.sin(a), math.cos(a))
        return [make_path(None, 'edges', [[x2 - px * 4.6, y2 - py * 4.6], [x2 + px * 4.6, y2 + py * 4.6]], stroke=color, lw=2.2)]
    if kind == 'binding':
        return [make_path(None, 'edges', [[x2, y2], [x2 - 4, y2 - 3.2], [x2 - 8, y2], [x2 - 4, y2 + 3.2]], fill=color, stroke=color, lw=0.8, closed=True)]
    return [make_path(None, 'edges', [[x2, y2], [x2 - 8 * math.cos(a - 0.36), y2 - 8 * math.sin(a - 0.36)], [x2 - 8 * math.cos(a + 0.36), y2 - 8 * math.sin(a + 0.36)]], fill=color, stroke=color, lw=0.6, closed=True)]

def arrange_model(model):
    """Deterministic rank-column layout; fits the canvas to the content."""
    canvas_cfg, style_cfg = (model['canvas'], model['style'])
    font_sizes, palette = (style_cfg['font_pt'], style_cfg['palette'])
    M, entity_list, chart = (38.0, model.get('entities') or [], model.get('chart'))
    relation_list = model.get('relations') or []
    for e in entity_list:
        e['lines'] = break_label(e.get('label', ''))
        tw = max([measure_text(l, font_sizes['label']) for l in e['lines']] or [20])
        e['box'] = {'w': max(74.0, tw + 24), 'h': max(30.0, len(e['lines']) * font_sizes['label'] * 1.5 + 15)}
    id_set = [e['id'] for e in entity_list]
    known_ids = set(id_set)
    rank = {k: 0 for k in id_set}
    edge_list = [r for r in relation_list if r.get('from') in known_ids and r.get('to') in known_ids and (r['from'] != r['to'])]
    for _ in range(len(id_set) + 1):
        moved = False
        for r in edge_list:
            if rank[r['to']] < rank[r['from']] + 1:
                rank[r['to']] = rank[r['from']] + 1
                moved = True
        if not moved:
            break
    max_depth = max(rank.values()) if rank else 0
    if max_depth > max(1, len(id_set) - 1):
        s = max(1, len(id_set) - 1) / float(max_depth)
        rank = {k: int(v * s) for k, v in rank.items()}
    columns = {}
    for e in entity_list:
        columns.setdefault(rank[e['id']], []).append(e)
    y_top = M + (44.0 if model.get('title') else 10.0)
    x, band = (M, 0.0)
    for r in sorted(columns):
        cw = max((e['box']['w'] for e in columns[r]))
        y = y_top
        for e in columns[r]:
            e['box'].update({'x': x, 'y': y, 'w': cw})
            y += e['box']['h'] + 26.0
        band = max(band, sum((e['box']['h'] for e in columns[r])) + 26.0 * (len(columns[r]) - 1))
        x += cw + 74.0
    content = x - 74.0 if columns else M + 240.0
    y_cur = y_top + band
    if chart:
        chart['box'] = {'x': M, 'y': y_cur + 26.0, 'w': max(520.0, content - M), 'h': 214.0}
        content = max(content, chart['box']['x'] + chart['box']['w'])
        y_cur = chart['box']['y'] + 214.0
    model['panels'] = []
    if chart and entity_list:
        model['panels'] = [{'id': 'panel-a', 'label': 'A', 'box': {'x': M - 14, 'y': y_top - 20, 'w': content - M + 28, 'h': band + 32}}, {'id': 'panel-b', 'label': 'B', 'box': {'x': chart['box']['x'] - 14, 'y': chart['box']['y'] - 20, 'w': chart['box']['w'] + 20, 'h': 208.0}}]
    legend_items = model.get('legend') or []
    for i, legend_item in enumerate(legend_items):
        legend_item.setdefault('color', palette[i % len(palette)])
    legend_box = {'x': M, 'y': y_cur + 24.0, 'w': max(170.0, max((measure_text(l['label'], font_sizes['legend']) for l in legend_items)) + 76), 'h': 19.0 * len(legend_items) + 16} if legend_items else None
    model['legend_box'] = legend_box
    canvas_cfg['width'] = int(round(max(float(canvas_cfg.get('width') or 0), content + M, legend_box['x'] + legend_box['w'] + M if legend_box else 0, 860.0)))
    canvas_cfg['height'] = int(round(max(float(canvas_cfg.get('height') or 0), (legend_box['y'] + legend_box['h'] if legend_box else y_cur) + M, 520.0)))
    canvas_cfg['auto_fit'] = True
    entity_by_id = {e['id']: e for e in entity_list}
    for r in relation_list:
        a, b = (entity_by_id.get(r.get('from')), entity_by_id.get(r.get('to')))
        if not a or not b or a is b:
            r['path'] = []
            continue
        ab, bb = (a['box'], b['box'])
        x1, y1, x2, y2 = (ab['x'] + ab['w'], ab['y'] + ab['h'] / 2, bb['x'], bb['y'] + bb['h'] / 2)
        if x2 < x1 + 16:
            yb = max(ab['y'] + ab['h'], bb['y'] + bb['h']) + 16
            r['path'] = [[x1, y1], [x1 + 13, y1], [x1 + 13, yb], [x2 - 13, yb], [x2 - 13, y2], [x2, y2]]
            r['route'] = 'under'
        else:
            xm = (x1 + x2) / 2.0
            r['path'] = [[x1, y1], [xm, y1], [xm, y2], [x2, y2]]
            r['route'] = 'elbow'
        r.setdefault('color', style_cfg.get('rel_color', {}).get(r.get('type'), '#333333'))
        r.setdefault('marker', style_cfg.get('rel_marker', {}).get(r.get('type'), 'activation'))
    return model

def emit_chart(model, prims):
    chart_spec, style_cfg = (model.get('chart') or {}, model['style'])
    b = chart_spec.get('box')
    if not b:
        return
    palette, ft = (style_cfg['palette'], max(6.0, style_cfg['font_pt']['legend'] - 0.5))
    x0, y0, pw, ph = (b['x'] + 64, b['y'] + 30, b['w'] - 96, b['h'] - 66)
    prims.append(make_text('chart-title', 'labels', b['x'] + 8, b['y'] + 15, chart_spec.get('title') or '', style_cfg['font_pt']['label'] + 0.5, 'start', INK_COLOR, 'bold'))
    series = chart_spec.get('series') or []
    vals = [v for s in series for v in s.get('values', []) if isinstance(v, (int, float))]
    vmax = (max(vals) if vals else 1.0) * 1.12 or 1.0
    for t in range(5):
        ty = y0 + ph - ph * t / 4.0
        prims.append(make_text('tick-%d' % t, 'labels', x0 - 5, ty + 2.5, format_number(vmax * t / 4.0), ft, 'end', '#444444'))
    for i, points in (('axis-x', [[x0, y0 + ph], [x0 + pw, y0 + ph]]), ('axis-y', [[x0, y0], [x0, y0 + ph]])):
        prims.append(make_path(i, 'labels', points, stroke='#333333', lw=0.9))
    yl = ' ; '.join(sorted({s.get('unit') or '' for s in series if s.get('unit')})) or chart_spec.get('unit') or ''
    if yl:
        prims.append(make_text('axis-y-label', 'labels', x0 - 40, y0 + ph / 2.0, yl, ft, 'middle', '#333333'))
    cats = chart_spec.get('categories') or []
    grp = pw / float(max(1, len(cats)))
    bw = grp / (len(series) + 0.6) if series else grp * 0.6
    for ci, cat in enumerate(cats):
        for si, s in enumerate(series):
            vs = s.get('values') or []
            v = vs[ci] if ci < len(vs) else None
            if not isinstance(v, (int, float)):
                continue
            hh = ph * (v / vmax)
            bx = x0 + grp * ci + grp * 0.08 + si * bw
            col = palette[(si + (1 if len(series) > 1 else 0)) % len(palette)]
            prims.append(make_rect('bar-%d-%d' % (ci + 1, si + 1), 'entities', bx, y0 + ph - hh, max(6.0, bw - 3), hh, fill=col, stroke=col, lw=0.6, data={'data-series': s.get('name', ''), 'data-category': str(cat)}))
        prims.append(make_text('cat-%d' % (ci + 1), 'labels', x0 + grp * ci + grp / 2.0, y0 + ph + 12, break_label(str(cat), 12)[0], ft, 'middle', '#222222'))

def scene_objects(model, for_svg=False):
    canvas_cfg, style_cfg = (model['canvas'], model['style'])
    font_sizes, lw = (style_cfg['font_pt'], style_cfg.get('line_width', 1.2))
    prims = [make_rect('bg-canvas', 'background', 0, 0, canvas_cfg['width'], canvas_cfg['height'], fill='#FFFFFF')]
    for p in model.get('panels') or []:
        b = p['box']
        prims.append(make_rect(p['id'], 'panels', b['x'], b['y'], b['w'], b['h'], '#FFFFFF', '#9aa4ad', 0.8, 6, '4 3'))
        prims.append(make_text('lbl-' + p['id'], 'labels', b['x'] + 7, b['y'] + 15, p['label'], font_sizes['title'], 'start', INK_COLOR, 'bold'))
    if model.get('title'):
        prims.append(make_text('title-main', 'title', 38, 34, model['title'], font_sizes['title'] + 1.5, 'start', INK_COLOR, 'bold'))
    for r in model.get('relations') or []:
        points = r.get('path') or []
        if len(points) < 2:
            continue
        col = r.get('color', '#333333')
        prims.append(make_path('edge-' + r['id'], 'edges', points, stroke=col, lw=lw, dash=r.get('dash'), data={'data-rel-type': r.get('type', ''), 'data-from': r['from'], 'data-to': r['to']}))
        if not for_svg:
            prims += terminal_marker(points, r.get('marker', 'activation'), col)
        if r.get('label'):
            md = points[len(points) // 2]
            prims.append(make_text('lbl-edge-' + r['id'], 'labels', md[0] + 3, md[1] - 4, r['label'], font_sizes['legend'], 'start', '#444444'))
    for e in model['entities']:
        b, n = (e['box'], len(e['lines']))
        prims.append(make_rect('ent-' + e['id'], 'entities', b['x'], b['y'], b['w'], b['h'], fill=e.get('fill', style_cfg['entity_fill']), stroke=e.get('stroke', style_cfg['entity_stroke']), lw=lw, rx=4, data={'data-entity-id': e['id'], 'data-entity-type': e.get('type', '')}))
        for i, ln in enumerate(e['lines']):
            ty = b['y'] + b['h'] / 2.0 + (i - (n - 1) / 2.0) * font_sizes['label'] * 1.5 + font_sizes['label'] * 0.36
            prims.append(make_text('lbl-' + e['id'] if n == 1 else 'lbl-%s-%d' % (e['id'], i + 1), 'labels', b['x'] + b['w'] / 2.0, ty, ln, font_sizes['label'], 'middle', INK_COLOR, data={'data-entity-id': e['id']}))
    emit_chart(model, prims)
    legend_box, legend_items = (model.get('legend_box'), model.get('legend') or [])
    if legend_box and legend_items:
        prims.append(make_rect('legend-box', 'legend', legend_box['x'], legend_box['y'], legend_box['w'], legend_box['h'], fill='#FFFFFF', stroke='#8d979f', lw=0.8, rx=3))
        prims.append(make_text('legend-title', 'legend', legend_box['x'] + 8, legend_box['y'] + 12.5, 'Legend', font_sizes['legend'] + 0.5, 'start', INK_COLOR, 'bold'))
        for i, legend_item in enumerate(legend_items):
            ly, col = (legend_box['y'] + 26 + i * 19, legend_item.get('color', '#333333'))
            if legend_item.get('kind') == 'relation':
                prims.append(make_path('lg-' + legend_item['id'], 'legend', [[legend_box['x'] + 10, ly - 3], [legend_box['x'] + 40, ly - 3]], stroke=col, lw=lw))
                prims += terminal_marker([[legend_box['x'] + 10, ly - 3], [legend_box['x'] + 40, ly - 3]], legend_item.get('marker', 'activation'), col)
            else:
                prims.append(make_rect('lg-' + legend_item['id'], 'legend', legend_box['x'] + 10, ly - 8, 16, 9, fill=col, stroke=col, lw=0.6))
            prims.append(make_text('lglbl-' + legend_item['id'], 'legend', legend_box['x'] + 48, ly, legend_item['label'], font_sizes['legend'], 'start', INK_COLOR))
    return prims

def element_xml(p):
    at = ' id="%s"' % p['id'] if p.get('id') else ''
    for a, v in (p.get('data') or {}).items():
        at += ' %s="%s"' % (a, xml_escape(v))
    if p['k'] == 'rect':
        s = '<rect%s x="%g" y="%g" width="%g" height="%g" fill="%s" stroke="%s" stroke-width="%g"' % (at, p['x'], p['y'], p['w'], p['h'], p['fill'] or 'none', p['stroke'] or 'none', p.get('lw') or 0)
        s += ' rx="%g"' % p['rx'] if p.get('rx') else ''
        s += ' stroke-dasharray="%s"' % p['dash'] if p.get('dash') else ''
        return s + '/>'
    if p['k'] == 'poly':
        s = '<path%s d="M%s%s" fill="%s" stroke="%s" stroke-width="%g" stroke-linejoin="round"' % (at, ' L'.join(('%g,%g' % (a, b) for a, b in p['pts'])), ' Z' if p.get('closed') else '', p['fill'] or 'none', p['stroke'] or 'none', p.get('lw') or 0)
        s += ' stroke-dasharray="%s"' % p['dash'] if p.get('dash') else ''
        s += ' marker-end="url(#mk-%s)"' % p['marker'] if p.get('marker') else ''
        return s + '/>'
    return '<text%s x="%g" y="%g" font-size="%g" text-anchor="%s" fill="%s" font-weight="%s">%s</text>' % (at, p['x'], p['y'], p['size'], p.get('anchor', 'middle'), p['fill'], p.get('weight', 'normal'), xml_escape(p['s']))

def serialize_svg(model):
    canvas_cfg = model['canvas']
    W, H = (canvas_cfg['width'], canvas_cfg['height'])
    prims = scene_objects(model, True)
    relation_list = {str(r.get('id')): r for r in model.get('relations') or []}
    for p in prims:
        if p['k'] == 'poly' and (p.get('id') or '').startswith('edge-'):
            p['marker'] = relation_list.get(p['id'][5:], {}).get('marker', 'activation')
    target = ['<?xml version="1.0" encoding="UTF-8"?>', '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img">' % (W, H, W, H), '  <title>%s</title>' % xml_escape(model.get('title') or model.get('figure_id') or 'schematic'), '  <desc>Layered editable schematic (scifig-editable 1.0); live text, ids map to content_map.</desc>', '  <defs>' + MARKER_DEFS + '</defs>']
    for L in model.get('layers') or LAYER_ORDER:
        els = [p for p in prims if p.get('layer') == L]
        if els:
            target.append('  <g id="layer-%s" data-layer="%s" font-family="%s" fill="%s">' % (L, L, FONT_STACK, INK_COLOR))
            target += ['    ' + element_xml(p) for p in els]
            target.append('  </g>')
    return '\n'.join(target + ['</svg>']) + '\n'
