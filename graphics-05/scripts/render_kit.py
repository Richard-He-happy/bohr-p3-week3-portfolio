"""render_kit.py - one figure model, three renderers (layered SVG, vector PDF, PNG).

The model built by compose_figure() is a display list of rectangles, lines and
text runs ordered by named layer. Geometry depends only on the plan and the
canvas constants, so the same plan always produces byte-identical SVG. The PNG
preview uses matplotlib when it is importable and falls back to pngkit (stdlib
zlib rasteriser) otherwise, so a bitmap is produced either way.
Standalone: python3 render_kit.py --plan P --out DIR
"""
import json, sys
from pathlib import Path
CANVAS_W, CANVAS_H, MARGIN, PT_SCALE = (1200, 760, 40, 0.72)
ROLE_STYLE = {'problem': ('PROBLEM', '#D55E00'), 'method': ('METHODS', '#0072B2'), 'results': ('KEY RESULTS', '#009E73'), 'implication': ('IMPLICATION', '#CC79A7'), 'other': ('NOTE', '#555555')}
LAYER_ORDER = ['background', 'structure', 'content', 'legend', 'footer', 'titles']
_LAYER_INDEX = {n: i for i, n in enumerate(LAYER_ORDER)}

def squash(s):
    return ' '.join(str(s or '').split())

def canonical_role(r):
    r = str(r or '').lower()
    for k, ns in (('problem', ('problem', 'question', 'gap', 'aim', 'motivation', 'challenge')), ('method', ('method', 'approach', 'pipeline', 'strategy', 'experiment', 'workflow')), ('results', ('results', 'finding', 'outcome', 'evidence', 'data', 'effect')), ('implication', ('implication', 'conclusion', 'significance', 'impact', 'outlook'))):
        if any((n in r for n in ns)):
            return k
    return 'other'

def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple((int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)))

def blend_white(h, keep):
    return '#%02X%02X%02X' % tuple((max(0, min(255, round(255 * (1 - keep) + c * 255 * keep))) for c in hex_to_rgb(h)))

def darken(h, f=0.72):
    return '#%02X%02X%02X' % tuple((max(0, min(255, round(c * 255 * f))) for c in hex_to_rgb(h)))

def char_advance(ch, size):
    if ord(ch) > 11903:
        return size
    if ch in "ilj.,;:'!|()[]":
        return size * 0.29
    if ch in 'mwMW':
        return size * 0.85
    return size * (0.65 if ch.isupper() else 0.56 if ch.isdigit() else 0.52)

def measure_width(s, size):
    return sum((char_advance(c, size) for c in s))

def fold_text(s, size, width, maxl=0):
    s = squash(s)
    if not s:
        return []
    toks, buf = ([], '')
    for ch in s:
        if ord(ch) > 11903 or ch == ' ':
            if buf:
                toks.append(buf)
                buf = ''
            toks.append(ch)
        else:
            buf += ch
    if buf:
        toks.append(buf)
    lines, cur = ([], '')
    for tk in toks:
        if not cur or measure_width((cur + tk).strip(), size) <= width:
            cur += tk
        else:
            if cur.strip():
                lines.append(cur.strip())
            cur = '' if tk == ' ' else tk
    if cur.strip():
        lines.append(cur.strip())
    if maxl and len(lines) > maxl:
        lines = lines[:maxl]
        lines[-1] = lines[-1].rstrip(' ,.;:') + '...'
    return lines

def text_op(x, y, s, size, weight='normal', color='#1A1A1A', anchor='start', eid=None, layer='content'):
    return dict(op='text', x=float(x), y=float(y), text=s, size=float(size), weight=weight, color=color, anchor=anchor, eid=eid, layer=layer)

def rect_op(x, y, w, h, fill=None, stroke=None, sw=1.0, rx=0, eid=None, layer='structure'):
    return dict(op='rect', x=float(x), y=float(y), w=float(w), h=float(h), fill=fill, stroke=stroke, sw=float(sw), rx=float(rx), eid=eid, layer=layer)

def line_op(x1, y1, x2, y2, color='#666666', sw=1.0, eid=None, layer='structure'):
    return dict(op='line', x1=float(x1), y1=float(y1), x2=float(x2), y2=float(y2), stroke=color, sw=float(sw), eid=eid, layer=layer)

def layout_entry(it, w, sc, accent):
    k = str(it.get('kind') or 'text').lower()
    lab, det = (squash(it.get('label')), squash(it.get('detail') or it.get('note')))
    val, ops = (squash(it.get('value')), [])
    if k == 'value':
        vs, ds = (20 * sc, 11.5 * sc)
        v = fold_text(val or lab, vs, w - 20) or ['']
        d = fold_text(det, ds, w - 20)
        h = 8 + len(v) * (vs + 2) + (len(d) * (ds + 3) + 2 if d else 0) + 8
        ops += [rect_op(0, 0, w, h, blend_white(accent, 0.12), None, 0, 8), rect_op(0, 5, 3.5, h - 10, accent, None, 0, 1.5)]
        yy = 8 + vs * 0.85
        for ln in v:
            ops.append(text_op(11, yy, ln, vs, 'bold', darken(accent)))
            yy += vs + 2
        yy += 2 if d else 0
        for ln in d:
            ops.append(text_op(11, yy, ln, ds, 'normal', '#3A3A3A'))
            yy += ds + 3
        return (ops, h + 10)
    ls, ds = (13.5 * sc, 11.8 * sc)
    l, d = (fold_text(lab, ls, w), fold_text(det, ds, w))
    h = len(l) * (ls + 2) + len(d) * (ds + 3.4) + 6
    yy = ls * 0.85
    for ln in l:
        ops.append(text_op(0, yy, ln, ls, 'bold', '#1A1A1A'))
        yy += ls + 2
    for ln in d:
        ops.append(text_op(0, yy, ln, ds, 'normal', '#3A3A3A'))
        yy += ds + 3.4
    return (ops, h + 8)

def fit_entries(items, w, avail, accent):
    for sc in (1.0, 0.94, 0.88, 0.82, 0.76):
        lays, tot = ([], 0.0)
        for it in items:
            ops, h = layout_entry(it, w, sc, accent)
            lays.append((it, ops, h))
            tot += h
        if tot <= avail:
            return (sc, lays, [])
    sc, lays, tot, drop = (0.76, [], 0.0, [])
    for it in items:
        ops, h = layout_entry(it, w, sc, accent)
        if tot + h <= avail:
            lays.append((it, ops, h))
            tot += h
        else:
            drop.append(it.get('id') or it.get('label'))
    return (sc, lays, drop)

def place_panel(g, sizes, warns, els, dropped):
    p, role = (g['panel'], g['role'])
    label, color = ROLE_STYLE[role]
    x, y, w, h, pid = (g['x'], g['y'], g['w'], g['h'], g['id'])
    ops = [rect_op(x, y, w, h, '#FCFCFC', '#D9D9D9', 1.0, 10, pid + '-card'), rect_op(x, y, w, 34, color, None, 0, 10, pid + '-header'), rect_op(x, y + 17, w, 17, color, None, 0, 0, pid + '-headerb')]
    heading, hts = (squash(p.get('heading')) or label, 14.5)
    while measure_width(heading, hts) > w - 34 and hts > 9:
        hts -= 0.5
    ops.append(text_op(x + 12, y + 23, heading, hts, 'bold', '#FFFFFF', 'start', pid + '-heading'))
    sizes.append(hts)
    if role != 'other' and heading.upper() != label:
        ops.append(text_op(x + w - 10, y + 21, label, 9.0, 'normal', '#FFFFFF', 'end', pid + '-roletag'))
        sizes.append(9.0)
    items = [i for i in p.get('items') or [] if isinstance(i, dict)]
    ix, iw = (x + 13, w - 26)
    sc, lays, drop = fit_entries(items, iw, h - 58, color)
    if drop:
        dropped.append({'panel': pid, 'items': drop, 'reason': 'vertical overflow at smallest font scale'})
        warns.append(f'panel {pid}: {len(drop)} item(s) dropped')
    cy = y + 46
    for it, iops, ih in lays:
        eid = str(it.get('id') or f'{pid}-I{len(els) + 1}')
        for o in iops:
            o = dict(o, x=o['x'] + ix, y=o['y'] + cy)
            if o['op'] == 'text':
                o['eid'] = eid
                sizes.append(o['size'])
            ops.append(o)
        els.append({'id': eid, 'panel': pid, 'role': role, 'kind': str(it.get('kind') or 'text'), 'text': ' '.join([squash(it.get('label')), squash(it.get('value')), squash(it.get('detail') or it.get('note'))]).strip(), 'bbox': [round(ix, 1), round(cy, 1), round(iw, 1), round(ih, 1)]})
        cy += ih
    return ops

def compose_figure(plan):
    title = squash(plan.get('title')) or 'Graphical abstract'
    subtitle = squash(plan.get('subtitle') or plan.get('one_line_message'))
    caption = squash(plan.get('caption'))
    panels = [p for p in plan.get('panels') or [] if isinstance(p, dict)]
    ops = [rect_op(0, 0, CANVAS_W, CANVAS_H, '#FFFFFF', None, 0, 0, 'canvas', 'background')]
    els, warns, dropped, sizes = ([], [], [], [])
    ts = 30.0
    while measure_width(title, ts) > CANVAS_W - 2 * MARGIN and ts > 16:
        ts -= 1
    ops.append(text_op(MARGIN, 50, title, ts, 'bold', '#111111', 'start', 'title', 'titles'))
    sizes.append(ts)
    y = 76
    for line in fold_text(subtitle, 14.5, CANVAS_W - 2 * MARGIN, 2):
        ops.append(text_op(MARGIN, y, line, 14.5, 'normal', '#3F3F3F', 'start', 'subtitle', 'titles'))
        sizes.append(14.5)
        y += 19
    top, bottom = (max(112, y + 12), CANVAS_H - 140)
    n = max(1, len(panels))
    rows = 1 if n <= 4 else 2
    cols, gap = (max(1, -(-n // rows)), 26)
    pw = (CANVAS_W - 2 * MARGIN - (cols - 1) * gap) / cols
    ph = (bottom - top - (rows - 1) * gap) / rows
    geom = []
    for i, p in enumerate(panels):
        r_, c_ = divmod(i, cols)
        geom.append({'id': str(p.get('id') or f'P{i + 1}'), 'panel': p, 'role': canonical_role(p.get('role') or p.get('heading')), 'x': MARGIN + c_ * (pw + gap), 'y': top + r_ * (ph + gap), 'w': pw, 'h': ph})
    for g in geom:
        ops += place_panel(g, sizes, warns, els, dropped)
    for i in range(len(geom) - 1):
        a, b = (geom[i], geom[i + 1])
        if abs(a['y'] - b['y']) < 1 and b['x'] > a['x'] + 1:
            mid, x1, x2 = (a['y'] + a['h'] / 2, a['x'] + a['w'] + 3, b['x'] - 4)
            ops += [line_op(x1, mid, x2, mid, '#6E6E6E', 2.0, f'flow-{i + 1}'), line_op(x2, mid, x2 - 8, mid - 4.2, '#6E6E6E', 2.0), line_op(x2, mid, x2 - 8, mid + 4.2, '#6E6E6E', 2.0)]
            flow = squash(b['panel'].get('flow'))
            if flow:
                ops.append(text_op((x1 + x2) / 2, mid - 9, flow, 9.5, 'normal', '#555555', 'middle', f'flow-{i + 1}-l', 'structure'))
                sizes.append(9.5)
    ly = bottom + 16
    ops.append(line_op(MARGIN, ly, CANVAS_W - MARGIN, ly, '#DDDDDD', 1.0, 'rule-legend', 'legend'))
    pal = ['#D55E00', '#0072B2', '#009E73', '#CC79A7', '#555555']
    entries = [(squash(e.get('label')), squash(e.get('meaning')), pal[i % 5]) for i, e in enumerate((e for e in plan.get('legend') or [] if isinstance(e, dict)))]
    if not entries:
        entries = [(ROLE_STYLE[g['role']][0].title(), squash(g['panel'].get('heading')) or ROLE_STYLE[g['role']][0], ROLE_STYLE[g['role']][1]) for g in geom if g['role'] != 'other']
    lx = MARGIN
    for i, (lab, mea, col) in enumerate(entries[:6]):
        ops.append(rect_op(lx, ly + 12, 11, 11, col, None, 0, 2, f'legend-{i + 1}', 'legend'))
        txt = (f'{lab} - {mea}' if mea and mea.lower() != lab.lower() else lab)[:70]
        ops.append(text_op(lx + 17, ly + 22, txt, 10.5, 'normal', '#333333', 'start', f'legend-{i + 1}-t', 'legend'))
        sizes.append(10.5)
        lx += 51 + measure_width(txt, 10.5)
    cy = ly + 52
    for line in fold_text(caption, 10.8, CANVAS_W - 2 * MARGIN, 2):
        ops.append(text_op(MARGIN, cy, line, 10.8, 'normal', '#4A4A4A', 'start', 'caption', 'footer'))
        sizes.append(10.8)
        cy += 15
    ops.append(text_op(MARGIN, CANVAS_H - 26, f'{len(geom)} panels - {len(els)} traced elements - editable SVG / vector PDF', 9.2, 'normal', '#8A8A8A', 'start', 'footer-note', 'footer'))
    sizes.append(9.2)
    ops.sort(key=lambda o: _LAYER_INDEX.get(o.get('layer', 'content'), 2))
    maxy = max([o['y'] + (o['h'] if o['op'] == 'rect' else 0) for o in ops if o['op'] != 'line'] or [0])
    return {'CANVAS_W': CANVAS_W, 'CANVAS_H': CANVAS_H, 'title': title, 'subtitle': subtitle, 'caption': caption, 'ops': ops, 'elements': els, 'warnings': warns, 'dropped': dropped, 'stats': {'panels': len(geom), 'items': len(els), 'text_ops': sum((o['op'] == 'text' for o in ops)), 'min_font': round(min(sizes), 2) if sizes else 0, 'max_y': round(maxy, 1)}}

def xml_escape(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def emit_svg(m):
    o = ['<?xml version="1.0" encoding="UTF-8"?>', f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{CANVAS_W}" height="{CANVAS_H}" viewBox="0 0 {CANVAS_W} {CANVAS_H}" role="img" aria-labelledby="ga-title">', f"""  <title id="ga-title">{xml_escape(m['title'])}</title>""", '  <defs><style type="text/css"><![CDATA[text{font-family:Helvetica,Arial,"Noto Sans",sans-serif;}]]></style></defs>']
    cur = None
    for op in m['ops']:
        lay = op.get('layer', 'content')
        if lay != cur:
            if cur:
                o.append('  </g>')
            o.append(f'  <g id="layer-{lay}" data-layer="{lay}">')
            cur = lay
        eid = f''' id="{xml_escape(op['eid'])}"''' if op.get('eid') else ''
        if op['op'] == 'rect':
            st = f''' stroke="{op['stroke']}" stroke-width="{op['sw']}"''' if op['stroke'] else ''
            rx = f''' rx="{op['rx']}"''' if op['rx'] else ''
            o.append(f'''    <rect{eid} x="{op['x']:.1f}" y="{op['y']:.1f}" width="{op['w']:.1f}" height="{op['h']:.1f}" fill="{op['fill'] or 'none'}"{st}{rx}/>''')
        elif op['op'] == 'line':
            o.append(f'''    <line{eid} x1="{op['x1']:.1f}" y1="{op['y1']:.1f}" x2="{op['x2']:.1f}" y2="{op['y2']:.1f}" stroke="{op['stroke']}" stroke-width="{op['sw']}" stroke-linecap="round"/>''')
        else:
            fw = ' font-weight="bold"' if op['weight'] == 'bold' else ''
            an = {'middle': 'middle', 'end': 'end'}.get(op['anchor'], 'start')
            o.append(f'''    <text{eid} x="{op['x']:.1f}" y="{op['y']:.1f}" font-size="{op['size']:.1f}" fill="{op['color']}"{fw} text-anchor="{an}">{xml_escape(op['text'])}</text>''')
    if cur:
        o.append('  </g>')
    o.append('</svg>')
    return '\n'.join(o) + '\n'

def rounded_rect_path(x, yb, w, h, r):
    r = max(0.0, min(r, w / 2.0, h / 2.0))
    if r < 0.3:
        return f'{x:.2f} {yb:.2f} {w:.2f} {h:.2f} re'
    k = 0.5523 * r
    s = f'{x + r:.2f} {yb:.2f} m {x + w - r:.2f} {yb:.2f} l'
    s += f' {x + w - r + k:.2f} {yb:.2f} {x + w:.2f} {yb + r - k:.2f} {x + w:.2f} {yb + r:.2f} c'
    s += f' {x + w:.2f} {yb + h - r:.2f} l'
    s += f' {x + w:.2f} {yb + h - r + k:.2f} {x + w - r + k:.2f} {yb + h:.2f} {x + w - r:.2f} {yb + h:.2f} c'
    s += f' {x + r:.2f} {yb + h:.2f} l'
    s += f' {x + r - k:.2f} {yb + h:.2f} {x:.2f} {yb + h - r + k:.2f} {x:.2f} {yb + h - r:.2f} c'
    s += f' {x:.2f} {yb + r:.2f} l'
    s += f' {x:.2f} {yb + r - k:.2f} {x + r - k:.2f} {yb:.2f} {x + r:.2f} {yb:.2f} c h'
    return s

def emit_pdf(m):
    S = PT_SCALE
    cs, cjk = (['%.4f 0 0 %.4f 0 0 cm' % (S, S)], set())
    for op in m['ops']:
        if op['op'] == 'rect':
            if not op['fill'] and (not op['stroke']):
                continue
            cs.append('q')
            if op['fill']:
                cs.append('%.3f %.3f %.3f rg' % hex_to_rgb(op['fill']))
            if op['stroke']:
                cs.append('%.3f %.3f %.3f RG %.2f w' % (hex_to_rgb(op['stroke']) + (op['sw'],)))
            cs.append(rounded_rect_path(op['x'], CANVAS_H - op['y'] - op['h'], op['w'], op['h'], op['rx']))
            cs.append('B' if op['fill'] and op['stroke'] else 'f' if op['fill'] else 'S')
            cs.append('Q')
        elif op['op'] == 'line':
            cs.append('q %.3f %.3f %.3f RG %.2f w 1 J %.2f %.2f m %.2f %.2f l S Q' % (hex_to_rgb(op['stroke']) + (op['sw'], op['x1'], CANVAS_H - op['y1'], op['x2'], CANVAS_H - op['y2'])))
        elif op['text']:
            s, size = (op['text'], op['size'])
            x = op['x'] - (measure_width(s, size) / 2.0 if op['anchor'] == 'middle' else measure_width(s, size) if op['anchor'] == 'end' else 0)
            base, col = (CANVAS_H - op['y'], hex_to_rgb(op['color']))
            i = 0
            while i < len(s):
                j, is_c = (i, ord(s[i]) >= 11904)
                while j < len(s) and (ord(s[j]) >= 11904) == is_c:
                    j += 1
                part = s[i:j]
                fn = 'F3' if is_c else 'F2' if op['weight'] == 'bold' else 'F1'
                if is_c:
                    hx = part.encode('utf-16-be').hex().upper()
                    cjk.update((hx[k:k + 4] for k in range(0, len(hx), 4)))
                    lit = f'<{hx}>'
                else:
                    lit = '(' + ''.join(('\\' + c if c in '()\\' else c for c in part.encode('latin-1', 'replace').decode('latin-1'))) + ')'
                cs.append('BT /%s %.2f Tf %.3f %.3f %.3f rg 1 0 0 1 %.2f %.2f Tm %s Tj ET' % (fn, size, col[0], col[1], col[2], x, base - size * 0.22, lit))
                x += measure_width(part, size)
                i = j
    content = '\n'.join(cs).encode('latin-1', 'replace')
    codes, bf = (sorted(cjk), '')
    for i in range(0, len(codes), 100):
        ch = codes[i:i + 100]
        bf += '%d beginbfchar\n' % len(ch) + ''.join((f'<{c}> <{c}>\n' for c in ch)) + 'endbfchar\n'
    tu = ('/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n' + bf + 'endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n').encode('latin-1')

    def stream(d):
        return b'<< /Length %d >>\nstream\n' % len(d) + d + b'\nendstream'
    objs = [b'<< /Type /Catalog /Pages 2 0 rect_op >>', b'<< /Type /Pages /Kids [3 0 rect_op] /Count 1 >>', f'<< /Type /Page /Parent 2 0 rect_op /MediaBox [0 0 {CANVAS_W * S:.2f} {CANVAS_H * S:.2f}] /Resources << /ProcSet [/PDF /Text] /Font << /F1 4 0 rect_op /F2 5 0 rect_op /F3 6 0 rect_op >> >> /Contents 8 0 rect_op >>'.encode(), b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>', b'<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-CANVAS_H /DescendantFonts [7 0 rect_op] /ToUnicode 9 0 rect_op >>', b'<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> /DW 1000 >>', stream(content), stream(tu), b'<< /Producer (SciMaster graphical-abstract builder) /Creator (main.py build) >>']
    out, offs = (bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n'), [])
    for i, body in enumerate(objs):
        offs.append(len(out))
        out += b'%d 0 obj\n' % (i + 1) + body + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)
    for off in offs:
        out += b'%010d 00000 n \n' % off
    out += b'trailer\n<< /Size %d /Root 1 0 rect_op /Info 10 0 rect_op >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, xref)
    return bytes(out)

def emit_png(m, png_path):
    """Draw the preview bitmap: matplotlib when present, stdlib rasteriser otherwise.

    Returns (ok, engine, note); the engine string is copied into
    compliance_checks.png so a reviewer can see whether the preview came from a
    full plotting stack or from the degraded internal rasteriser.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        fig = plt.figure(figsize=(CANVAS_W / 100.0, CANVAS_H / 100.0), dpi=300)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, CANVAS_W)
        ax.set_ylim(CANVAS_H, 0)
        ax.axis('off')
        for op in m['ops']:
            if op['op'] == 'rect':
                ax.add_patch(Rectangle((op['x'], op['y']), op['w'], op['h'], facecolor=op['fill'] or 'none', edgecolor=op['stroke'] or 'none', linewidth=op['sw'] * 0.75, zorder=2))
            elif op['op'] == 'line':
                ax.plot([op['x1'], op['x2']], [op['y1'], op['y2']], color=op['stroke'], linewidth=op['sw'] * 0.75, solid_capstyle='round', zorder=3)
            else:
                ax.text(op['x'], op['y'], op['text'], fontsize=op['size'] * 0.72, color=op['color'], zorder=4, ha={'middle': 'center', 'end': 'right'}.get(op['anchor'], 'left'), va='baseline', fontweight='bold' if op['weight'] == 'bold' else 'normal')
        fig.savefig(png_path, dpi=300, facecolor='white', metadata={'Software': None})
        plt.close(fig)
        return (True, 'matplotlib Agg @ 300 dpi', '')
    except Exception as exc:
        try:
            import pngkit
            ok, engine, note = pngkit.render(m, png_path)
            return (ok, engine, f'matplotlib path failed ({exc}); {note}')
        except Exception as exc2:
            return (False, 'none', f'matplotlib and stdlib rasteriser both failed ({exc}; {exc2}); SVG+PDF kept')

def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description='Render plan.json to SVG + PDF (+ PNG preview).')
    ap.add_argument('--plan', default='work/plan.json', help='plan.json written by the agent')
    ap.add_argument('--out', default='output', help='output directory')
    a = ap.parse_args(argv)
    plan = json.loads(Path(a.plan).read_text(encoding='utf-8-sig'))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    m = compose_figure(plan)
    (out / 'graphical_abstract.svg').write_text(emit_svg(m), encoding='utf-8')
    (out / 'graphical_abstract.pdf').write_bytes(emit_pdf(m))
    print('png:', emit_png(m, str(out / 'graphical_abstract.png')))
    print('elements:', len(m['elements']), 'warnings:', m['warnings'])
    return 0
if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

_LAYOUT_CONTRACT = """
Maintenance contract for the renderer (read before touching geometry).

The public surface is deliberately tiny: compose_figure(plan) returns a dict with
the canvas size, the flat operation list, the traced element table and a small
stats block; emit_svg / emit_pdf / emit_png only consume that dict. Everything
downstream - content_map, compliance_checks, result.json - is derived from the
same dict, so the three exports can never drift apart.

Where each number comes from:
- canvas and margins are module constants; nothing else hard-codes a pixel size;
- panel width/height derive from the canvas, the panel count and the row split;
- text height comes from per-character advance estimates, folded at the panel
  width, so a long claim wraps instead of bleeding over the card edge;
- the font ladder tries full size first and walks down to 76 percent; only when
  even that cannot fit are trailing items removed and reported.

Three invariants worth guarding in review:
1. determinism - no random, no clock, no environment lookup, no dict iteration
   order dependence; two runs of the same plan must serialise to identical SVG;
2. traceability - every text operation carries the id of the element it belongs
   to, and the element table repeats that id, so the atlas can join both sides;
3. graceful degradation - a missing export engine changes engine strings and
   compliance notes, never the science content or the status of otherwise
   verified elements.
"""
