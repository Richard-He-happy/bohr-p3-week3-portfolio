
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import design as dz
R_NS = dz.R_NS
CONTENT_PREFIX = dz.CONTENT_PREFIX
P_NS = dz.P_NS
NS_DECL = dz.NS_DECL
CANVAS_W, CANVAS_H = dz.CANVAS_W, dz.CANVAS_H
def render(shell, **fields):
    return dz.shells()[shell].format(**fields)
def xml_escape(value):
    return (str(value).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))
def _paragraph_xml(text, size=1800, bold=False, level=0, bullet_char=None, theme_font=None):
    latin = '<a:latin typeface="%s"/>' % xml_escape(theme_font) if theme_font else ''
    return render('bullet', lvl=level, marL=228600 + 342900 * level,
                  bu=bullet_char or ('\u2022' if not level else '\u2013'),
                  buf=xml_escape(theme_font) if theme_font else 'Arial',
                  sz=size, b=' b="1"' if bold else '', latin=latin, text=xml_escape(text))
def _shape_xml(shape_id, name, placeholder, x, y, cx, cy, paragraphs,
               size=1800, bold=False, anchor='t', theme_font=None):
    body = ''.join(_paragraph_xml(item[0], size, bold, item[1], theme_font=theme_font)
                   if isinstance(item, tuple) else item for item in paragraphs)
    if placeholder:
        ref = '<p:ph%s%s/>' % (' type="%s"' % placeholder[0] if placeholder[0] else '',
                               '' if placeholder[1] is None else ' idx="%d"' % placeholder[1])
    else:
        ref = '<p:ph/>'
    return render('shape', id=shape_id, name=xml_escape(name), ph=ref,
                  x=int(x), y=int(y), cx=int(cx), cy=int(cy), anchor=anchor, body=body)
def _picture_xml(shape_id, relationship_id, name, x, y, cx, cy):
    return render('picture', id=shape_id, name=xml_escape(name), rid=relationship_id,
                  x=int(x), y=int(y), cx=int(cx), cy=int(cy))
def _slide_part(shapes):
    return render('slide', ns=NS_DECL, shapes=''.join(shapes))
def _notes_part(text):
    paragraphs = ''.join(
        '<a:p><a:r><a:rPr lang="en-US" dirty="0"/><a:t>%s</a:t></a:r></a:p>' % xml_escape(line)
        for line in str(text).split('\n') if line.strip())
    shape = _shape_xml(2, 'Notes Placeholder 1', ('body', 1), 685800, 4343400,
                       5486400, 4114800, [paragraphs], 1200)
    return render('notes', ns=NS_DECL, shapes=shape)
def _rels_part(items):
    return render('rels', items=''.join(render('relItem', id=rid, type=kind, target=target)
                                        for rid, kind, target in items))
def _placeholder_types(xml_bytes):
    info = {'types': []}
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return info
    for shape in root.iter('{%s}sp' % P_NS):
        placeholder = shape.find('.//{%s}ph' % P_NS)
        if placeholder is not None:
            info['types'].append(placeholder.get('type') or 'body')
    return info
def read_design(path):
    info = {'parts': {}, 'layouts': [], 'masters': [], 'sldSz': [CANVAS_W, CANVAS_H],
            'fonts': [], 'footer_slot': False, 'ok': False, 'path': str(path), 'error': None}
    keep_prefixes = ('ppt/slideMasters/', 'ppt/slideLayouts/', 'ppt/theme/',
                     'ppt/notesMasters/', 'ppt/media/')
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.startswith(keep_prefixes) or name in ('ppt/tableStyles.xml', 'ppt/presProps.xml'):
                    info['parts'][name] = archive.read(name)
            presentation = archive.read('ppt/presentation.xml').decode('utf-8', 'replace')
        parts = info['parts']
        size = re.search(r'<p:sldSz[^>]*cx="(\d+)"[^>]*cy="(\d+)"', presentation)
        if size:
            info['sldSz'] = [int(size.group(1)), int(size.group(2))]
        for name in sorted(key for key in parts
                           if re.match(r'ppt/slideLayouts/slideLayout\d+\.xml$', key)):
            info['layouts'].append((name, _placeholder_types(parts[name])))
        info['masters'] = sorted(key for key in parts
                                 if re.match(r'ppt/slideMasters/slideMaster\d+\.xml$', key))
        themes = sorted(key for key in parts if re.match(r'ppt/theme/theme\d+\.xml$', key))
        if themes:
            theme_xml = parts[themes[0]].decode('utf-8', 'replace')
            info['theme_part'] = themes[0]
            info['fonts'] = sorted({face for face in re.findall(r'typeface="([^"]+)"', theme_xml) if face})
            major = re.search(r'<a:majorFont>\s*<a:latin typeface="([^"]*)"', theme_xml)
            minor = re.search(r'<a:minorFont>\s*<a:latin typeface="([^"]*)"', theme_xml)
            info['major_font'] = major.group(1) if major else ''
            info['minor_font'] = minor.group(1) if minor else ''
        info['footer_slot'] = any('ftr' in probe['types'] for _name, probe in info['layouts'])
        info['ok'] = bool(info['layouts']) and bool(info['masters'])
    except Exception as err:
        info['error'] = '%s: %s' % (type(err).__name__, err)
    return info
def _content_type(name):
    if name == 'ppt/presentation.xml':
        return CONTENT_PREFIX + 'presentationml.presentation.main+xml'
    member = re.search(r'/(slideLayout|slideMaster|notesMaster|notesSlide|slide)\d+\.xml$', name)
    if member:
        return CONTENT_PREFIX + 'presentationml.%s+xml' % member.group(1)
    if name.startswith('ppt/theme/'):
        return CONTENT_PREFIX + 'theme+xml'
    tail = name.rsplit('/', 1)[-1]
    if tail in ('presProps.xml', 'viewProps.xml', 'tableStyles.xml'):
        return CONTENT_PREFIX + 'presentationml.' + tail[:-4] + '+xml'
    return None
def _resolve_target(base, target):
    parts = []
    for piece in (base.split('/') if base else []) + target.split('/'):
        if piece in ('', '.'):
            continue
        if piece == '..':
            if parts:
                parts.pop()
        else:
            parts.append(piece)
    return '/'.join(parts)
def write_package(path, parts):
    parts = dict(parts)
    names = set(parts)
    for name in [key for key in names if key.endswith('.rels')]:
        try:
            root = ET.fromstring(parts[name])
        except Exception:
            parts.pop(name, None)
            continue
        source = name.replace('_rels/', '')
        source = source[:-5] if source.endswith('.rels') else source
        base = source.rsplit('/', 1)[0] if '/' in source else ''
        pruned = False
        for relationship in list(root):
            if (relationship.get('TargetMode') or '') == 'External':
                continue
            target = relationship.get('Target') or ''
            resolved = target.lstrip('/') if target.startswith('/') else _resolve_target(base, target)
            if resolved not in names:
                root.remove(relationship)
                pruned = True
        if pruned:
            parts[name] = ET.tostring(root, encoding='UTF-8', xml_declaration=True)
    header = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.'
              'openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType='
              '"application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" '
              'ContentType="application/xml"/><Default Extension="jpg" ContentType="image/jpeg"/>'
              '<Default Extension="png" ContentType="image/png"/>']
    header += ['<Override PartName="/%s" ContentType="%s"/>' % (name, kind) for name in sorted(parts)
               if not name.endswith('.rels') for kind in [_content_type(name)] if kind]
    parts['[Content_Types].xml'] = ('%s</Types>' % ''.join(header)).encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ['[Content_Types].xml'] + sorted(key for key in parts if key != '[Content_Types].xml'):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, parts[name])
    return path
def assemble_package(out, template, decks, title, author, stamp_text):
    parts, masters, layouts = {}, [], []
    if template.get('ok'):
        parts.update(template['parts'])
        masters = template['masters']
        layouts = [name for name, _info in template['layouts']]
        width, height = template['sldSz']
    else:
        parts.update(dz.fallback_parts())
        masters = ['ppt/slideMasters/slideMaster1.xml']
        layouts = ['ppt/slideLayouts/slideLayout1.xml']
        width, height = CANVAS_W, CANVAS_H
    presentation_rels, master_ids, slide_ids, rel_id = [], [], [], 0
    media_count = len([key for key in parts if key.startswith('ppt/media/')])
    for master in masters:
        rel_id += 1
        presentation_rels.append(('rId%d' % rel_id, R_NS + '/slideMaster', master.replace('ppt/', '')))
        master_ids.append('<p:sldMasterId id="%d" r:id="rId%d"/>' % (2147483647 + rel_id, rel_id))
    for index, deck in enumerate(decks, 1):
        layout = deck.get('layout') if deck.get('layout') in layouts else layouts[min(1, len(layouts) - 1)]
        rel_id += 1
        parts['ppt/slides/slide%d.xml' % index] = _slide_part(deck['shapes']).encode()
        slide_rels = [('rId1', R_NS + '/slideLayout', '../slideLayouts/' + layout.rsplit('/', 1)[-1])]
        for blob in deck.get('images', []):
            media_count += 1
            parts['ppt/media/image%d.jpg' % media_count] = blob
            slide_rels.append(('rId%d' % (len(slide_rels) + 1), R_NS + '/image',
                               '../media/image%d.jpg' % media_count))
        slide_rels.append(('rId%d' % (len(slide_rels) + 1), R_NS + '/notesSlide',
                           '../notesSlides/notesSlide%d.xml' % index))
        parts['ppt/notesSlides/notesSlide%d.xml' % index] = _notes_part(deck.get('notes') or ' ').encode()
        parts['ppt/notesSlides/_rels/notesSlide%d.xml.rels' % index] = _rels_part(
            [('rId1', R_NS + '/slide', '../slides/slide%d.xml' % index),
             ('rId2', R_NS + '/notesMaster', '../notesMasters/notesMaster1.xml')]).encode()
        parts['ppt/slides/_rels/slide%d.xml.rels' % index] = _rels_part(slide_rels).encode()
        presentation_rels.append(('rId%d' % rel_id, R_NS + '/slide', 'slides/slide%d.xml' % index))
        slide_ids.append('<p:sldId id="%d" r:id="rId%d"/>' % (255 + index, rel_id))
    rel_id += 1
    presentation_rels.append(('rId%d' % rel_id, R_NS + '/presProps', 'presProps.xml'))
    parts.setdefault('ppt/presProps.xml', render('presProps', ns=NS_DECL).encode())
    parts['ppt/_rels/presentation.xml.rels'] = _rels_part(presentation_rels).encode()
    parts['ppt/presentation.xml'] = render(
        'presentation', ns=NS_DECL, masters=''.join(master_ids), slides=''.join(slide_ids),
        cx=width, cy=height).encode()
    parts['_rels/.rels'] = _rels_part(
        [('rId1', R_NS + '/officeDocument', 'ppt/presentation.xml'),
         ('rId2', dz.CORE_PROPS, 'docProps/core.xml')]).encode()
    parts['docProps/core.xml'] = render('core', title=xml_escape(title), author=xml_escape(author),
                                        stamp=stamp_text).encode()
    write_package(out, parts)
    return {'slides': len(decks), 'bytes': out.stat().st_size, 'sldSz': [width, height],
            'sha256': hashlib.sha256(out.read_bytes()).hexdigest()}
def _line_util(texts, cx, cy, size, cjk):
    points = max(size / 100.0, 6.0)
    chars_per_line = max(8, int((cx / 12700) * 0.98 / (points if cjk else points * 0.52)))
    lines_needed = sum(max(1, math.ceil(len(text) / chars_per_line)) for text in texts)
    return lines_needed / max(1, int((cy / 12700 - 10) / (points * 1.34)))
def compose_slide(page, width, height, template, footer, zh):
    margin = int(width * 0.062)
    text_width = width - int(width * 0.124)
    title_y, title_h = int(height * 0.05), int(height * 0.16)
    body_y = title_y + title_h + int(height * 0.015)
    body_h = int(height * 0.885) - body_y
    major_font = template.get('major_font') or ''
    minor_font = template.get('minor_font') or ''
    shapes = []
    if page['role'] == 'title':
        cover_ref = ('ctrTitle', None) if template.get('has_ctr') else ('title', None)
        shapes.append(_shape_xml(2, 'Title 1', cover_ref, margin, int(height * 0.26),
                                 text_width, int(height * 0.26), [(page['title'], 0)],
                                 3200, True, theme_font=major_font))
        if page['bullets']:
            shapes.append(_shape_xml(3, 'Subtitle 2', (None, 1), margin, int(height * 0.56),
                                     text_width, int(height * 0.2),
                                     [(text, 0) for text, _level in page['bullets']],
                                     1600, theme_font=minor_font))
        return shapes, 0.0
    shapes.append(_shape_xml(2, 'Title 1', ('title', None), margin, title_y, text_width, title_h,
                             [(page['title'], 0)], 3000, True, theme_font=major_font))
    texts = [text for text, _level in page['bullets']]
    pictures = page.get('images') or []
    body_width = int(text_width * 0.52) if pictures else text_width
    size = 2000 if len(texts) <= 3 else 1800 if len(texts) <= 4 else 1600
    utilization = 0.0
    while size > 1200:
        utilization = _line_util(texts, body_width, body_h, size, zh)
        if utilization <= 1.0:
            break
        size -= 100
    if texts:
        shapes.append(_shape_xml(3, 'Content 2', (None, 1), margin, body_y, body_width, body_h,
                                 list(page['bullets']), size, theme_font=minor_font))
    if pictures:
        image_width = int(text_width * 0.44)
        image_w, image_h = _image_dims(pictures[0])
        image_height = min(body_h, int(image_width * (image_h / image_w)) if image_w
                           else int(body_h * 0.7))
        shapes.append(_picture_xml(9, 'rId2', 'Figure 1', margin + body_width + int(text_width * 0.02),
                                   body_y, image_width, max(image_height, int(body_h * 0.4))))
    if footer:
        footer_ref = ('ftr', None) if template.get('footer_slot') else None
        shapes.append(_shape_xml(4, 'Footer 3', footer_ref, margin, int(height * 0.93),
                                 text_width, int(height * 0.05), [(footer, 0)], 1000,
                                 theme_font=minor_font))
    return shapes, round(utilization, 2)
def _image_dims(blob):
    import sourcekit
    return sourcekit.jpeg_dims(blob)
def render_pdf(pdf_path, pptx_path, work_dir, pages, exceptions):
    office = shutil.which('soffice') or shutil.which('libreoffice')
    if office:
        try:
            (work_dir / '_lo_profile').mkdir(parents=True, exist_ok=True)
            subprocess.run([office, '--headless', '--norestore', '--nologo', '--convert-to', 'pdf',
                            '--outdir', str(pdf_path.parent.resolve()), str(pptx_path.resolve())],
                           capture_output=True, timeout=280, cwd=str(work_dir),
                           env=dict(os.environ, HOME=str((work_dir / '_lo_profile').resolve())))
            if (pdf_path.exists() and pdf_path.read_bytes()[:4] == b'%PDF'
                    and pdf_path.stat().st_size > 800):
                return {'method': 'libreoffice-headless', 'degraded': False}
        except Exception:
            pass
    try:
        _text_layer_pdf(pdf_path, pages)
        exceptions.append({
            'code': 'PDF_TEXT_FALLBACK', 'stage': 'export',
            'detail': 'no LibreOffice/soffice on this runtime; a stdlib text-layer PDF was written as '
                      'the preview while the pptx remains the authoritative editable source',
            'action': 're-export with PowerPoint/LibreOffice for pixel-accurate delivery'})
        return {'method': 'stdlib-text-fallback', 'degraded': True}
    except Exception as err:
        exceptions.append({
            'code': 'PDF_RENDER_UNAVAILABLE', 'stage': 'export',
            'detail': 'no working LibreOffice/soffice on this runtime and the stdlib PDF fallback '
                      'failed: %s' % err,
            'action': 're-export the pptx to PDF in PowerPoint/LibreOffice for delivery'})
        return {'method': 'none', 'degraded': True}
def _text_layer_pdf(path, pages):
    page_w, page_h = 842, 595
    def ascii_only(value):
        kept = []
        for char in str(value or ''):
            code = ord(char)
            if code < 32:
                continue
            kept.append(char if code < 256 else '?')
        return ''.join(kept)
    def literal(value):
        return ascii_only(value).replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')
    def wrap(value, width):
        lines, current = [], ''
        for word in str(value or '').split():
            if len(current) + len(word) + 1 > width and current:
                lines.append(current)
                current = word
            else:
                current = (current + ' ' + word).strip()
        if current:
            lines.append(current)
        return lines or ['']
    def normalise(page):
        if isinstance(page, dict):
            return page.get('title') or page.get('claim') or '', list(page.get('bullets') or [])
        if isinstance(page, (tuple, list)) and len(page) == 2:
            head, body = page
            if isinstance(body, dict):
                body = list(body.values())
            return str(head or ''), list(body or [])
        return str(page or ''), []
    objects = [None, None, None]
    objects[0] = b'<< /Type /Catalog /Pages 2 0 R >>'
    objects[2] = b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'
    kids = []
    for page in pages or []:
        heading, bullets = normalise(page)
        rows = [(20, str(heading))]
        for bullet in bullets[:9]:
            if isinstance(bullet, dict):
                bullet = bullet.get('text') or bullet.get('bullet') or bullet.get('point') or ''
            rows.append((12, '- ' + str(bullet)))
        lines = []
        for size, text in rows:
            for line in wrap(text, 92 if size > 15 else 108):
                lines.append((size, line))
        ops = ['BT', '1 0 0 1 46 548 Tm']
        cursor = 548
        for size, text in lines[:40]:
            cursor -= size + 9
            ops.append('/F1 %d Tf' % size)
            ops.append('1 0 0 1 46 %d Tm' % max(30, cursor))
            ops.append('(%s) Tj' % literal(text))
        ops.append('ET')
        stream = '\n'.join(ops).encode('latin-1', 'replace')
        content_id = len(objects) + 1
        objects.append(b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream')
        page_id = len(objects) + 1
        objects.append(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources '
                       b'<< /Font << /F1 3 0 R >> >> /Contents %d 0 R >>'
                       % (page_w, page_h, content_id))
        kids.append(page_id)
    if not kids:
        stream = b'BT /F1 18 Tf 1 0 0 1 46 520 Tm (No pages) Tj ET'
        content_id = len(objects) + 1
        objects.append(b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream')
        page_id = len(objects) + 1
        objects.append(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Resources '
                       b'<< /Font << /F1 3 0 R >> >> /Contents %d 0 R >>' % content_id)
        kids.append(page_id)
    objects[1] = (b'<< /Type /Pages /Kids [' + b' '.join(b'%d 0 R' % kid for kid in kids)
                  + b'] /Count %d >>' % len(kids))
    buffer = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(buffer))
        buffer += b'%d 0 obj\n' % number + body + b'\nendobj\n'
    xref = len(buffer)
    buffer += b'xref\n0 %d\n' % (len(objects) + 1)
    buffer += b'0000000000 65535 f \n'
    for offset in offsets:
        buffer += b'%010d 00000 n \n' % offset
    buffer += (b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'
               % (len(objects) + 1, xref))
    Path(path).write_bytes(bytes(buffer))
    return len(kids)
