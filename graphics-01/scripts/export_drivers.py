#!/usr/bin/env python3
"""PNG/PDF export drivers for figure-lineage.

External SVG converters are probed in a fixed order; when none is usable the
standard-library rasteriser and vector writer still produce real files, and the
degradation is reported instead of being hidden."""
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

from layout_studio import parse_color, scene_objects


GLYPH_5X7 = {'A': ['01110', '10001', '10001', '11111', '10001', '10001', '10001'], 'B': ['11110', '10001', '10001', '11110', '10001', '10001', '11110'], 'C': ['01111', '10000', '10000', '10000', '10000', '10000', '01111'], 'D': ['11110', '10001', '10001', '10001', '10001', '10001', '11110'], 'E': ['11111', '10000', '10000', '11110', '10000', '10000', '11111'], 'F': ['11111', '10000', '10000', '11110', '10000', '10000', '10000'], 'G': ['01111', '10000', '10000', '10111', '10001', '10001', '01111'], 'H': ['10001', '10001', '10001', '11111', '10001', '10001', '10001'], 'I': ['11111', '00100', '00100', '00100', '00100', '00100', '11111'], 'J': ['00111', '00010', '00010', '00010', '00010', '10010', '01100'], 'K': ['10001', '10010', '10100', '11000', '10100', '10010', '10001'], 'L': ['10000', '10000', '10000', '10000', '10000', '10000', '11111'], 'M': ['10001', '11011', '10101', '10101', '10001', '10001', '10001'], 'N': ['10001', '11001', '10101', '10011', '10001', '10001', '10001'], 'O': ['01110', '10001', '10001', '10001', '10001', '10001', '01110'], 'P': ['11110', '10001', '10001', '11110', '10000', '10000', '10000'], 'Q': ['01110', '10001', '10001', '10001', '10101', '10010', '01101'], 'R': ['11110', '10001', '10001', '11110', '10100', '10010', '10001'], 'S': ['01111', '10000', '10000', '01110', '00001', '00001', '11110'], 'T': ['11111', '00100', '00100', '00100', '00100', '00100', '00100'], 'U': ['10001', '10001', '10001', '10001', '10001', '10001', '01110'], 'V': ['10001', '10001', '10001', '10001', '10001', '01010', '00100'], 'W': ['10001', '10001', '10001', '10101', '10101', '10101', '01010'], 'X': ['10001', '10001', '01010', '00100', '01010', '10001', '10001'], 'Y': ['10001', '10001', '01010', '00100', '00100', '00100', '00100'], 'Z': ['11111', '00001', '00010', '00100', '01000', '10000', '11111'], '0': ['01110', '10001', '10011', '10101', '11001', '10001', '01110'], '1': ['00100', '01100', '00100', '00100', '00100', '00100', '01110'], '2': ['01110', '10001', '00001', '00010', '00100', '01000', '11111'], '3': ['11110', '00001', '00001', '01110', '00001', '00001', '11110'], '4': ['00010', '00110', '01010', '10010', '11111', '00010', '00010'], '5': ['11111', '10000', '10000', '11110', '00001', '00001', '11110'], '6': ['01110', '10000', '10000', '11110', '10001', '10001', '01110'], '7': ['11111', '00001', '00010', '00100', '01000', '01000', '01000'], '8': ['01110', '10001', '10001', '01110', '10001', '10001', '01110'], '9': ['01110', '10001', '10001', '01111', '00001', '00001', '01110'], ' ': ['00000'] * 7, '-': ['00000', '00000', '00000', '11111', '00000', '00000', '00000'], '.': ['00000', '00000', '00000', '00000', '00000', '01100', '01100'], ',': ['00000', '00000', '00000', '00000', '00110', '00100', '01000'], '(': ['00010', '00100', '01000', '01000', '01000', '00100', '00010'], ')': ['01000', '00100', '00010', '00010', '00010', '00100', '01000'], '+': ['00000', '00100', '00100', '11111', '00100', '00100', '00000'], '/': ['00001', '00010', '00010', '00100', '01000', '01000', '10000'], '%': ['11001', '11010', '00010', '00100', '01000', '01011', '10011'], ':': ['00000', '01100', '01100', '00000', '01100', '01100', '00000'], ';': ['00000', '01100', '01100', '00000', '00110', '00100', '01000'], '=': ['00000', '00000', '11111', '00000', '11111', '00000', '00000'], '_': ['00000', '00000', '00000', '00000', '00000', '00000', '11111'], '*': ['00000', '10101', '01110', '11111', '01110', '10101', '00000'], '&': ['01100', '10010', '10100', '01000', '10101', '10010', '01101'], '#': ['01010', '11111', '01010', '01010', '11111', '01010', '00000']}

def find_executable(*n):
    return next((p for p in (shutil.which(x) for x in n) if p), None)

def run_quietly(argv, target, minb=600):
    try:
        subprocess.run(argv, check=True, capture_output=True, timeout=240)
        return Path(target).exists() and Path(target).stat().st_size > minb
    except Exception:
        return False

def convert_via_engine(serialize_svg, target, png_w=0, dpi=300):
    """figure.svg -> real PNG/PDF with whatever the image ships (engine name returned)."""
    serialize_svg, target = (Path(serialize_svg), Path(target))
    if not serialize_svg.exists():
        return None
    t = find_executable('rsvg-convert')
    if t and run_quietly([t, '-w', str(png_w), '-o', str(target), str(serialize_svg)] if png_w else [t, '-f', 'pdf', '-o', str(target), str(serialize_svg)], target):
        return 'rsvg-convert'
    t = find_executable('cairosvg')
    if t and run_quietly([t, str(serialize_svg), '--output-width', str(png_w), '-o', str(target)] if png_w else [t, str(serialize_svg), '-o', str(target)], target):
        return 'cairosvg'
    t = find_executable('inkscape')
    if t and run_quietly([t, str(serialize_svg), '--export-type=png', '--export-filename=' + str(target), '--export-width=%d' % png_w] if png_w else [t, str(serialize_svg), '--export-type=pdf', '--export-filename=' + str(target)], target):
        return 'inkscape'
    if png_w:
        p = find_executable('pdftoppm')
        eng = convert_via_engine(serialize_svg, target.with_suffix('.pdf'), dpi=dpi) if p else None
        if eng and run_quietly([p, '-png', '-r', str(dpi), '-singlefile', str(target.with_suffix('.pdf')), str(target.with_suffix(''))], target, 800):
            return eng + '+pdftoppm'
        t = find_executable('convert', 'magick')
        if t and run_quietly([t, '-density', str(dpi), '-background', 'white', '-flatten', '-depth', '8', str(serialize_svg), str(target)], target, 800):
            return 'imagemagick'
        return None
    t = find_executable('soffice', 'libreoffice')
    if t and run_quietly([t, '--headless', '--convert-to', 'pdf', '--outdir', str(target.parent), str(serialize_svg)], target):
        return 'libreoffice-draw'
    return None

def encode_png(model, target):
    """Degraded real PNG: stdlib zlib + 5x7 bitmap font (ASCII only). Never raises to caller."""
    S, W, H = (2, int(model['canvas']['width']) * 2, int(model['canvas']['height']) * 2)
    px = bytearray([255, 255, 255]) * (W * H)

    def fill_rect(x0, y0, x1, y1, c):
        x0 = max(0, int(x0))
        y0 = max(0, int(y0))
        x1 = min(W - 1, int(x1))
        y1 = min(H - 1, int(y1))
        for y in range(y0, y1 + 1):
            o = (y * W + x0) * 3
            for _ in range(x0, x1 + 1):
                px[o] = c[0]
                px[o + 1] = c[1]
                px[o + 2] = c[2]
                o += 3

    def line(x0, y0, x1, y1, c, t):
        t = max(1, int(t))
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        x, y, r = (int(x0), int(y0), t // 2)
        while True:
            fill_rect(x - r, y - r, x + r, y + r, c)
            if x == int(x1) and y == int(y1):
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    def polyline(points, c, t):
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            line(x0 * S, y0 * S, x1 * S, y1 * S, c, t * S)

    def fill_poly(points, c):
        xs = [p[0] * S for p in points]
        ys = [p[1] * S for p in points]
        x0, x1 = (int(min(xs)), int(max(xs)))
        y0, y1 = (int(min(ys)), int(max(ys)))
        for y in range(max(0, y0), min(H - 1, y1) + 1):
            for x in range(max(0, x0), min(W - 1, x1) + 1):
                inside, j = (False, len(points) - 1)
                for i in range(len(points)):
                    if (ys[i] > y) != (ys[j] > y) and x < (xs[j] - xs[i]) * (y - ys[i]) / (ys[j] - ys[i]) + xs[i]:
                        inside = not inside
                    j = i
                if inside:
                    o = (y * W + x) * 3
                    px[o] = c[0]
                    px[o + 1] = c[1]
                    px[o + 2] = c[2]

    def glyph(chart_spec):
        return GLYPH_5X7.get(chart_spec.upper()) or ['11111', '10001', '10001', '10001', '10001', '10001', '11111']

    def make_text(x, y, s, size, c):
        step = max(1, int(round(size * S / 7.0)))
        cx, cy = (int(x * S), int(y * S) - 3 * step)
        for chart_spec in str(s):
            g = glyph(chart_spec)
            for rr, row in enumerate(g):
                for cc, bit in enumerate(row):
                    if bit == '1':
                        fill_rect(cx + cc * step, cy + rr * step, cx + (cc + 1) * step - 1, cy + (rr + 1) * step - 1, c)
            cx += 6 * step
    for p in scene_objects(model, False):
        if p['k'] == 'rect':
            x, y, w, h = (p['x'] * S, p['y'] * S, p['w'] * S, p['h'] * S)
            if p.get('fill') and parse_color(p['fill']) != (255, 255, 255):
                fill_rect(x, y, x + w - 1, y + h - 1, parse_color(p['fill']))
            if p.get('stroke'):
                c = parse_color(p['stroke'])
                t = max(1, int(p.get('lw', 1) * S))
                line(x, y, x + w, y, c, t)
                line(x + w, y, x + w, y + h, c, t)
                line(x + w, y + h, x, y + h, c, t)
                line(x, y + h, x, y, c, t)
        elif p['k'] == 'poly':
            if p.get('closed') and p.get('fill'):
                fill_poly(p['pts'], parse_color(p['fill']))
            if p.get('stroke') and (not p.get('closed')):
                polyline(p['pts'], parse_color(p['stroke']), p.get('lw', 1))
        elif p['k'] == 'text':
            make_text(p['x'], p['y'], p['s'], p['size'], parse_color(p.get('fill') or '#111111'))
    raw = b''.join((b'\x00' + bytes(px[y * W * 3:(y + 1) * W * 3]) for y in range(H)))

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 4294967295)
    ihdr = struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0)
    Path(target).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))

def escape_pdf_string(s):
    o = []
    for c in s:
        if ord(c) < 32 or ord(c) > 255:
            return None
        o.append('\\' + c if c in '()\\' else c)
    return ''.join(o)

def pdf_path(points):
    parts = ['%.2f %.2f m' % points[0]]
    parts += ['%.2f %.2f l' % pt for pt in points[1:]]
    return ' '.join(parts)

def encode_pdf(model, target):
    """Degraded real vector PDF: catalog + page + content stream, base-14 Helvetica (Latin only)."""
    W, H = (int(model['canvas']['width']), int(model['canvas']['height']))
    cmds = ['1 1 1 rg 0 0 %d %d re f' % (W, H)]
    for p in scene_objects(model, False):
        if p['k'] == 'rect':
            x, y, w, h = (p['x'], H - p['y'] - p['h'], p['w'], p['h'])
            if p.get('fill') and parse_color(p['fill']) != (255, 255, 255):
                r, g, b = [v / 255.0 for v in parse_color(p['fill'])]
                cmds.append('%.4f %.4f %.4f rg %.2f %.2f %.2f %.2f re f' % (r, g, b, x, y, w, h))
            if p.get('stroke'):
                r, g, b = [v / 255.0 for v in parse_color(p['stroke'])]
                cmds.append('%.4f %.4f %.4f RG %.2f w %.2f %.2f %.2f %.2f re S' % (r, g, b, p.get('lw', 1), x, y, w, h))
        elif p['k'] == 'poly':
            points = [(px, H - py) for px, py in p['pts']]
            if len(points) < 2:
                continue
            if p.get('closed') and p.get('fill'):
                r, g, b = [v / 255.0 for v in parse_color(p['fill'])]
                cmds.append('%.4f %.4f %.4f rg %s h f' % (r, g, b, pdf_path(points)))
            if p.get('stroke') and (not p.get('closed')):
                r, g, b = [v / 255.0 for v in parse_color(p['stroke'])]
                cmds.append('%.4f %.4f %.4f RG %.2f w %s S' % (r, g, b, p.get('lw', 1), pdf_path(points)))
        elif p['k'] == 'text':
            s = escape_pdf_string(str(p['s']))
            if s is None:
                continue
            size, x = (p['size'], p['x'])
            if p.get('anchor') == 'middle':
                x -= 0.26 * size * len(s)
            elif p.get('anchor') == 'end':
                x -= 0.52 * size * len(s)
            r, g, b = [v / 255.0 for v in parse_color(p.get('fill') or '#111111')]
            cmds.append('BT %.4f %.4f %.4f rg /F1 %.2f Tf %.2f %.2f Td (%s) Tj ET' % (r, g, b, size, x, H - p['y'], s))
    stream = '\n'.join(cmds).encode('latin-1')
    chunks, offsets = ([b'%PDF-1.4\n'], [])

    def add(format_number, body):
        offsets.append(sum((len(c) for c in chunks)))
        chunks.append(('%d 0 obj\n' % format_number).encode('latin-1') + body + b'\nendobj\n')
    add(1, b'<< /Type /Catalog /Pages 2 0 R >>')
    add(2, b'<< /Type/Pages /Kids [3 0 R] /Count 1 >>')
    add(3, b'<< /Type/Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>' % (W, H))
    add(4, b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream')
    add(5, b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    xref, n = (sum((len(c) for c in chunks)), len(offsets))
    chunks.append(('xref\n0 %d\n0000000000 65535 f \n' % (n + 1)).encode('latin-1'))
    chunks.append(b''.join((('%010d 00000 n \n' % off).encode('latin-1') for off in offsets)))
    chunks.append(b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (n + 1, xref))
    Path(target).write_bytes(b''.join(chunks))

def write_exports(model, out_dir, dpi=300):
    """Returns real exports + engine per artifact + degradations. Never raises."""
    out_dir, res = (Path(out_dir), {'png': None, 'pdf': None, 'degradations': [], 'engines': {}})
    W, H = (float(model['canvas']['width']), float(model['canvas']['height']))
    svg_path, png, pdf = (out_dir / 'figure.svg', out_dir / 'figure.png', out_dir / 'figure.pdf')
    for f, target in (('png', png), ('pdf', pdf)):
        eng = convert_via_engine(svg_path, target, png_w=int(W * 2) if f == 'png' else 0, dpi=dpi)
        if eng:
            res['engines'][f] = eng
            res[f] = target
            continue
        try:
            (encode_png if f == 'png' else encode_pdf)(model, target)
            eng = 'stdlib-zlib' if f == 'png' else 'stdlib-pdf'
            res['engines'][f] = eng
            res[f] = target
            res['degradations'].append({'artifact': f, 'engine': eng, 'status': 'degraded', 'reason': 'no external converter; stdlib renderer used (ASCII/Latin text only)'})
        except Exception as e:
            res['degradations'].append({'artifact': f, 'engine': None, 'status': 'missing', 'reason': 'no converter and stdlib renderer failed: %s' % e})
    return res
