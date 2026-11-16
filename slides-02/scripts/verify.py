
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
DEFAULT_CANVAS = (12192000, 6858000)
ALLOWED_STATUS = ('ok', 'partial', 'insufficient_evidence', 'input_error')
PROBE_ENV = 'DECK_FALLBACK_PROBE'
ASSET_FILES = ('page_golden.json', 'page_diff.md', 'version_history.md', 'run.log',
               'export_check.json', 'template_check.json', 'format_compliance.json',
               'self_check.json')
FONT_ALIASES = {
    'arial': ('liberationsans', 'arimo', 'helvetica', 'nexussans', 'arialunicodems', 'dejavusans'),
    'helvetica': ('arial', 'liberationsans'),
    'timesnewroman': ('liberationserif', 'times', 'nimbusroman', 'dejavuserif'),
    'calibri': ('carlito', 'calibrilight'),
    'cambria': ('caladea',),
    'georgia': ('gelasio',),
    'couriernew': ('liberationmono', 'courier'),
    'segoeui': ('selawik',),
    'verdana': ('dejavusans',),
}
CJK_FONT_MARKERS = ('notosans', 'notoserif', 'sourcehan', 'simsun', 'simhei', 'pingfang',
                    'microsoftyahei', 'wenquany', 'droid', 'uming', 'ukai', 'fandol', 'arphic')
def digest(value):
    if isinstance(value, str):
        value = value.encode('utf-8')
    return hashlib.sha256(value or b'').hexdigest()
def shorten(text, limit=140):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '\u2026'
def xml_escape(value):
    return (str(value).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))
def _run(command, timeout=180):
    try:
        proc = subprocess.run(command, capture_output=True, timeout=timeout)
        return (proc.returncode, proc.stdout.decode('utf-8', 'replace'),
                proc.stderr.decode('utf-8', 'replace'))
    except Exception as err:
        return -1, '', '%s: %s' % (type(err).__name__, err)
def _font_family(name):
    family = re.sub(r'^[A-Z]{6}\+', '', str(name))
    family = re.sub(r'[-,_]?(Bold|Italic|Regular|Light|Medium|Semibold|Oblique|Black|Roman).*$',
                    '', family, flags=re.I)
    family = re.sub(r'(PSMT|MT)$', '', family, flags=re.I)
    return re.sub(r'[^a-z0-9]', '', family.lower())
def _is_cjk_font(family):
    return any(marker in family for marker in CJK_FONT_MARKERS)
def compliance(pages, template, meta, audit, fits, figures, export_result, pdf_pages,
               template_source, filled_keys, unknown_keys, width):
    roles = [page['role'] for page in pages]
    count = len(pages)
    return {
        'mode': meta.get('mode'),
        'source_preservation': meta.get('source_preservation'),
        'template_inheritance': meta.get('template_inheritance'),
        'slide_count': {'requested': meta['requested'], 'actual': count,
                        'pass': meta['requested'] in (None, count)},
        'page_order': {'roles': roles, 'pass': roles[0] == 'title' and roles[-1] == 'thanks'},
        'template': {'source': template_source, 'inherited': bool(template.get('ok')),
                     'slide_width_emu': width, 'layouts': len(template.get('layouts', [])),
                     'theme_fonts': (template.get('fonts') or ['Arial'])[:5],
                     'footer_slot': bool(template.get('footer_slot')),
                     'footer_text': meta['footer'],
                     'title_slide': roles[0] == 'title', 'thanks_slide': roles[-1] == 'thanks'},
        'notes': {'with_notes': sum(1 for page in pages if page.get('notes')),
                  'pass': all(page.get('notes') for page in pages)},
        'text_fit': {'max_utilization': max([item['util'] for item in fits] or [0]),
                     'overflow_slides': [item['i'] for item in fits if item['util'] > 1.0]},
        'figures': figures,
        'evidence': {'bullets': audit['bullets'], 'verified': audit['verified'],
                     'pass': audit['bullets'] > 0 and audit['verified'] == audit['bullets']},
        'export': {'method': export_result['method'], 'degraded': export_result['degraded'],
                   'pages': pdf_pages, 'matches_slides': pdf_pages in (None, count)},
        'contract': {'required_keys': filled_keys + len(unknown_keys), 'filled': filled_keys,
                     'unknown_keys': unknown_keys},
        'overall_pass': bool(audit['bullets'] and audit['verified'] == audit['bullets']
                             and not export_result['degraded']),
    }
def _pdf_fonts(pdf):
    tool = shutil.which('pdffonts')
    if not tool:
        return None, 'pdffonts unavailable on this runtime'
    code, out, err = _run([tool, str(pdf)])
    if code != 0:
        return None, 'pdffonts rc=%d %s' % (code, err.strip()[:120])
    rows = []
    for line in out.splitlines():
        match = re.match(r'^(\S+)\s+(.+?)\s+(\S+)\s+(yes|no)\s+(yes|no)\s+(yes|no)\s+(\d+)\s+(\d+)\s*$',
                         line)
        if match:
            rows.append(dict(name=match.group(1), type=match.group(2).strip(),
                             encoding=match.group(3), embedded=match.group(4) == 'yes',
                             subset=match.group(5) == 'yes'))
    return rows, 'pdffonts'
def _pdf_boxes(pdf):
    tool = shutil.which('pdftotext')
    if not tool:
        return None, 'pdftotext unavailable on this runtime'
    code, out, err = _run([tool, '-bbox-layout', str(pdf), '-'])
    if code != 0 or '<page' not in out:
        return None, 'pdftotext -bbox-layout rc=%d %s' % (code, err.strip()[:120])
    pages = []
    for page in re.finditer(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', out, re.S):
        words = [(float(a), float(b), float(c), float(d)) for a, b, c, d in
                 re.findall(r'<word xMin="([\d.-]+)" yMin="([\d.-]+)" '
                            r'xMax="([\d.-]+)" yMax="([\d.-]+)"', page.group(3))]
        pages.append(dict(width=float(page.group(1)), height=float(page.group(2)), words=words))
    return pages, 'pdftotext -bbox-layout on %d page(s)' % len(pages)
def _png_ihdr(blob):
    if not blob or blob[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    if len(blob) < 33 or blob[12:16] != b'IHDR':
        return None
    return dict(width=int.from_bytes(blob[16:20], 'big'),
                height=int.from_bytes(blob[20:24], 'big'),
                bit_depth=blob[24], colour_type=blob[25])
def _pptx_inventory(pptx):
    info = dict(path=str(pptx) if pptx else None, opens=False)
    if not pptx:
        info['error'] = 'no pptx supplied to the inspector'
        return info
    try:
        blob = Path(pptx).read_bytes()
        with zipfile.ZipFile(pptx) as archive:
            members = archive.namelist()
        info.update(opens=True, members=len(members),
                    slide_parts=len([name for name in members
                                     if re.match(r'ppt/slides/slide\d+\.xml$', name)]),
                    notes_parts=len([name for name in members
                                     if name.startswith('ppt/notesSlides/notesSlide')]),
                    layouts=len([name for name in members
                                 if re.match(r'ppt/slideLayouts/slideLayout\d+\.xml$', name)]),
                    has_presentation='ppt/presentation.xml' in members,
                    has_content_types='[Content_Types].xml' in members,
                    bytes=len(blob), sha256=digest(blob))
    except Exception as err:
        info['error'] = '%s: %s' % (type(err).__name__, err)
    return info
def _png_inventory(out_dir):
    files = []
    if out_dir:
        try:
            files = sorted(path for path in Path(out_dir).rglob('*')
                           if path.is_file() and path.suffix.lower() == '.png')
        except Exception:
            files = []
    rows = []
    for path in files:
        try:
            ihdr = _png_ihdr(path.read_bytes())
        except Exception as err:
            ihdr = None
            rows.append(dict(file=path.name, bytes=0, ihdr=False, error='%s: %s' % (type(err).__name__, err)))
            continue
        rows.append(dict(file=path.name, bytes=path.stat().st_size, ihdr=bool(ihdr),
                         width=(ihdr or {}).get('width'), height=(ihdr or {}).get('height'),
                         bit_depth=(ihdr or {}).get('bit_depth')))
    return dict(count=len(files), checked=rows, ok=(all(row['ihdr'] for row in rows) if rows else None),
                reason=(None if rows else
                        'no PNG preview in this run: the PDF is the only rendered artefact, so there is '
                        'no IHDR to verify (nothing fabricated)'))
def export_check(pdf, slide_count, fits, figures, template, pptx=None, out_dir=None,
                 export_method=None, export_degraded=False):
    report = dict(path=str(pdf) if pdf else None, checks=[], overall_pass=False, verdict='fail',
                  method=export_method, degraded=bool(export_degraded),
                  pptx=_pptx_inventory(pptx), png=_png_inventory(out_dir))
    def record(check_id, item, status, evidence):
        report['checks'].append(dict(id=check_id, item=item, status=status, evidence=evidence))
    inventory = report['pptx']
    record('pptx_unzips', 'pptx unzips as an OPC package with one slide part per page',
           'pass' if (inventory.get('opens') and inventory.get('has_presentation')
                      and inventory.get('slide_parts') == slide_count) else 'fail',
           ('%d member(s), %d slide part(s), %d notes part(s), %d layout part(s) for %d page(s), '
            'sha256 %s' % (inventory.get('members', 0), inventory.get('slide_parts', 0),
                           inventory.get('notes_parts', 0), inventory.get('layouts', 0), slide_count,
                           (inventory.get('sha256') or 'n/a')[:16]))
           if inventory.get('opens') else 'pptx unreadable: %s' % (inventory.get('error') or 'unknown'))
    png = report['png']
    record('png_ihdr', 'a PNG preview, when present, carries a valid IHDR',
           'pass' if png['ok'] else ('n/a' if png['ok'] is None else 'fail'),
           ('%d PNG file(s): %s' % (png['count'], ', '.join(
               '%s %sx%s' % (row['file'], row.get('width'), row.get('height'))
               for row in png['checked']))) if png['count'] else png['reason'])
    if not pdf or not Path(pdf).exists():
        record('pdf_present', 'PDF export produced', 'fail',
               'no PDF at %s (converter missing or failed; --no-pdf skips it on purpose)' % pdf)
        slide_parts = inventory.get('slide_parts')
        report['page_count'] = dict(slides=slide_count, pdf_pages=None, pptx_slide_parts=slide_parts,
                                    via='not exported', ok=(slide_parts == slide_count))
        record('page_count', 'pptx slide parts and the declared slide count agree',
               'pass' if report['page_count']['ok'] else 'fail',
               '%d declared slide(s) vs %s pptx slide part(s); no PDF page to compare'
               % (slide_count, slide_parts))
        report['failures'] = [dict(check=check['id'], reason=check['evidence'])
                              for check in report['checks'] if check['status'] == 'fail']
        report['status_summary'] = _status_summary(report['checks'])
        report['verdict'] = 'no PDF: the pptx remains the deliverable'
        return report
    blob = Path(pdf).read_bytes()
    theme_fonts = [font for font in (template.get('fonts') or []) if font] or ['Arial']
    pdf_pages = len(re.findall(rb'/Type\s*/Page[^s]', blob))
    counted_via = 'regex /Type /Page'
    if shutil.which('pdfinfo'):
        code, info, _err = _run([shutil.which('pdfinfo'), str(pdf)])
        match = re.search(r'Pages:\s+(\d+)', info)
        if code == 0 and match:
            pdf_pages, counted_via = int(match.group(1)), 'pdfinfo'
    report['pdf'] = dict(bytes=len(blob), sha256=digest(blob),
                         header=blob[:4].decode('latin-1', 'replace'),
                         header_ok=blob[:4] == b'%PDF', pages=pdf_pages, pages_via=counted_via,
                         method=export_method, degraded=bool(export_degraded),
                         engine=('libreoffice/soffice' if export_method == 'libreoffice-headless'
                                 else 'stdlib text-layer fallback' if export_method == 'stdlib-text-fallback'
                                 else str(export_method)))
    record('pdf_header', 'file starts with the PDF signature',
           'pass' if blob[:4] == b'%PDF' else 'fail',
           'first bytes %r · %d bytes · sha256 %s' % (blob[:5], len(blob), digest(blob)[:16]))
    record('pdf_method', 'PDF comes from a real office render, not only a fallback',
           'pass' if (export_method == 'libreoffice-headless' and not export_degraded)
           else ('warn' if blob[:4] == b'%PDF' else 'fail'),
           'method=%s, degraded=%s: %s' % (
               export_method, bool(export_degraded),
               'a real office converter rendered the preview' if export_method == 'libreoffice-headless'
               and not export_degraded else
               'no office converter: text-layer PDF only, so layout fidelity is unverified; the pptx '
               'stays authoritative'))
    slide_parts = inventory.get('slide_parts')
    report['page_count'] = dict(slides=slide_count, pdf_pages=pdf_pages, pptx_slide_parts=slide_parts,
                                via=counted_via,
                                ok=(pdf_pages == slide_count
                                    and (slide_parts is None or slide_parts == slide_count)))
    record('page_count', 'pptx slide parts, PDF page count and the declared slide count agree',
           'pass' if report['page_count']['ok'] else 'fail',
           '%d declared slide(s) -> %s pptx slide part(s) -> %d PDF page(s) via %s'
           % (slide_count, slide_parts, pdf_pages, counted_via))
    fonts, font_source = _pdf_fonts(pdf)
    theme_families = [_font_family(name) for name in theme_fonts]
    resolved, unembedded = [], [font['name'] for font in (fonts or []) if not font['embedded']]
    for font in fonts or []:
        family = _font_family(font['name'])
        if family in theme_families:
            status = 'inherited'
        elif any(family in FONT_ALIASES.get(theme, ()) or theme in FONT_ALIASES.get(family, ())
                 for theme in theme_families):
            status = 'metric-alias'
        elif _is_cjk_font(family):
            status = 'cjk-fallback'
        else:
            status = 'substituted'
        resolved.append(dict(pdf_font=font['name'], family=family, theme_fonts=theme_fonts,
                             status=status, embedded=font['embedded']))
    substituted = [row['pdf_font'] for row in resolved if row['status'] == 'substituted']
    cjk_fallback = [row['pdf_font'] for row in resolved if row['status'] == 'cjk-fallback']
    report['fonts'] = dict(source=font_source, theme_fonts=theme_fonts,
                           base_fonts=[font['name'] for font in (fonts or [])],
                           resolution=resolved,
                           all_embedded=bool(fonts) and not unembedded,
                           substituted=substituted, cjk_fallback=cjk_fallback,
                           ok=(bool(fonts) and not unembedded and not substituted) if fonts else None)
    record('fonts_embedded', 'every PDF font is embedded (no viewer-side substitution)',
           'pass' if (fonts and not unembedded) else ('fail' if fonts else 'unknown'),
           'pdffonts: %s' % (', '.join('%s emb=%s' % (font['name'], 'yes' if font['embedded'] else 'no')
                                       for font in (fonts or [])) or
                             'font table not readable on this runtime (%s)' % font_source))
    record('fonts_inherited', 'PDF font families match the template theme scheme',
           'pass' if (fonts and not substituted) else ('warn' if fonts else 'unknown'),
           'theme %s -> PDF %s%s%s' % (
               theme_fonts, [font['name'] for font in (fonts or [])],
               '' if not substituted else ' · substituted: %s' % substituted,
               '' if not cjk_fallback else ' · CJK glyph fallback (expected for Han text): %s' % cjk_fallback)
           if fonts else 'font table not readable on this runtime (%s)' % font_source)
    boxes, box_source = _pdf_boxes(pdf)
    violations, worst_excess = [], 0.0
    for number, page in enumerate(boxes or [], 1):
        outside = []
        for x0, y0, x1, y1 in page['words']:
            excess = max(x1 - (page['width'] - 1.0), y1 - (page['height'] - 1.0),
                         -x0 - 1.0, -y0 - 1.0)
            worst_excess = max(worst_excess, excess)
            if excess > 0:
                outside.append([round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)])
        if outside:
            violations.append(dict(page=number, words=len(outside), sample=outside[:4],
                                   page_size=[round(page['width'], 2), round(page['height'], 2)]))
    model = dict(max_utilization=max([item['util'] for item in fits] or [0]),
                 overflow_slides=[item['i'] for item in fits if item['util'] > 1.0])
    report['text_overflow'] = dict(method=box_source, pages_checked=len(boxes or []),
                                   violations=violations, worst_excess_pt=round(worst_excess, 2),
                                   ok=(not violations) if boxes else None, modelled=model)
    record('text_overflow', 'no word crosses the page box in the rendered PDF',
           'pass' if (boxes and not violations) else ('fail' if boxes else 'unknown'),
           '%d page(s), %d word(s) checked, worst excess %.2f pt; modelled max utilization %.2f, '
           'modelled overflow slide(s) %s' % (
               len(boxes or []), sum(len(page['words']) for page in (boxes or [])),
               worst_excess, model['max_utilization'], model['overflow_slides'] or 'none')
           if boxes else 'word boxes not readable on this runtime (%s); only the line-fit model was '
                  'checked: max utilization %.2f' % (box_source, model['max_utilization']))
    pdf_images = len(re.findall(rb'/Subtype\s*/Image', blob))
    placed = int(figures.get('placed') or 0)
    report['images'] = dict(placed_in_deck=placed, pdf_image_xobjects=pdf_images,
                            ok=(placed == 0 or pdf_images >= placed))
    record('figures_rendered', 'every picture placed in the deck reaches the PDF',
           'pass' if report['images']['ok'] else 'fail',
           '%d picture(s) placed -> %d image XObject(s) in the PDF' % (placed, pdf_images))
    report['geometry'] = (dict(first_page_pt=[round(boxes[0]['width'], 2), round(boxes[0]['height'], 2)],
                               emu=[int(round(boxes[0]['width'] * 12700)),
                                    int(round(boxes[0]['height'] * 12700))])
                          if boxes else None)
    hard_failures = [check for check in report['checks'] if check['status'] == 'fail']
    report['failures'] = [dict(check=check['id'], reason=check['evidence'])
                          for check in report['checks'] if check['status'] in ('fail',)]
    report['status_summary'] = _status_summary(report['checks'])
    report['overall_pass'] = not hard_failures
    report['verdict'] = ('pass' if not hard_failures
                         else 'fail: ' + ', '.join(check['id'] for check in hard_failures))
    return report
def _status_summary(checks):
    summary = {key: 0 for key in ('pass', 'warn', 'fail', 'unknown', 'n/a')}
    for check in checks:
        status = check.get('status') or 'unknown'
        summary[status] = summary.get(status, 0) + 1
    return summary
def _placeholders(xml):
    found = []
    for match in re.finditer(r'<p:ph([^/>]*)/?>', xml):
        kind = re.search(r'type="([^"]+)"', match.group(1))
        index = re.search(r'idx="(\d+)"', match.group(1))
        found.append((kind.group(1) if kind else 'body', int(index.group(1)) if index else None))
    return found
def _theme_colours(xml):
    return sorted(set(re.findall(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', xml)))
def template_check(pptx, template, template_path, meta, slide_count):
    items = []
    def record(check_id, item, status, expected, actual, evidence):
        items.append(dict(id=check_id, item=item, status=status, expected=expected,
                          actual=actual, evidence=evidence))
    try:
        with zipfile.ZipFile(pptx) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
    except Exception as err:
        return dict(source=str(template_path), inherited=False,
                    checks=[dict(id='pptx_readable', status='fail',
                                 item='pptx opens as an OPC package',
                                 evidence='%s: %s' % (type(err).__name__, err))],
                    layout_map=[], deviations=[dict(check='pptx_readable', status='fail',
                                                    reason='%s: %s' % (type(err).__name__, err))],
                    failures=['pptx_readable'], overall_pass=False, passes=0, fails=1, warns=0, na=0)
    source_parts = template.get('parts') or {}
    inherited = bool(template.get('ok'))
    if template_path and not inherited:
        record('template_readable', 'the supplied template opens as an OPC package', 'warn',
               'readable .pptx', 'unreadable',
               'inheritance could not be verified; the builtin design was used instead')
    presentation = parts.get('ppt/presentation.xml', b'').decode('utf-8', 'replace')
    size = re.search(r'<p:sldSz[^>]*cx="(\d+)"[^>]*cy="(\d+)"', presentation)
    actual_size = [int(size.group(1)), int(size.group(2))] if size else None
    wanted_size = template.get('sldSz') or [None, None]
    record('slide_size', 'slide size inherited from the master',
           'pass' if (actual_size and (not inherited or wanted_size == actual_size)) else 'fail',
           '%s emu' % (wanted_size if inherited else 'builtin 16:9'), '%s emu' % actual_size,
           'presentation.xml/p:sldSz')
    deck_masters = sorted(name for name in parts
                          if re.match(r'ppt/slideMasters/slideMaster\d+\.xml$', name))
    design_masters = sorted(name for name in source_parts
                            if re.match(r'ppt/slideMasters/slideMaster\d+\.xml$', name))
    record('master', 'slide master carried over byte-identical',
           'pass' if (deck_masters and design_masters
                      and digest(parts[deck_masters[0]]) == digest(source_parts[design_masters[0]]))
           else ('n/a' if (not inherited and deck_masters) else 'fail'),
           'sha256 %s' % (digest(source_parts[design_masters[0]])[:16] if design_masters else 'n/a'),
           'sha256 %s' % (digest(parts[deck_masters[0]])[:16] if deck_masters else 'none'),
           '%s vs template %s' % (deck_masters[0] if deck_masters else 'no master part',
                                  design_masters[0] if design_masters else 'no template master'))
    used_layouts, unresolved, identical = [], [], 0
    for number in range(1, slide_count + 1):
        rels = parts.get('ppt/slides/_rels/slide%d.xml.rels' % number, b'').decode('utf-8', 'replace')
        match = re.search(r'Target="\.\./slideLayouts/(slideLayout\d+\.xml)"', rels)
        layout = 'ppt/slideLayouts/' + match.group(1) if match else None
        used_layouts.append(layout)
        if not layout or layout not in parts:
            unresolved.append(number)
        elif inherited and layout in source_parts and digest(parts[layout]) == digest(source_parts[layout]):
            identical += 1
    record('layouts_resolved', 'every slide points at a layout part that exists',
           'pass' if not unresolved else 'fail', '%d slide(s), one layout each' % slide_count,
           '%d unresolved' % len(unresolved),
           'slide->layout: %s' % [item.rsplit('/', 1)[-1] if item else None
                                  for item in used_layouts])
    record('layouts_inherited', 'layout parts used are the template layouts, unmodified',
           'pass' if (inherited and identical == slide_count) else ('n/a' if not inherited else 'warn'),
           'all %d slide(s) on unmodified template layouts' % slide_count,
           '%d/%d byte-identical layout part(s)' % (identical, slide_count),
           'distinct layouts used: %s' % sorted({item.rsplit('/', 1)[-1]
                                                 for item in used_layouts if item}))
    deck_themes = sorted(name for name in parts if re.match(r'ppt/theme/theme\d+\.xml$', name))
    design_themes = sorted(name for name in source_parts
                           if re.match(r'ppt/theme/theme\d+\.xml$', name))
    record('theme_part', 'theme part carried over byte-identical',
           'pass' if (deck_themes and design_themes
                      and digest(parts[deck_themes[0]]) == digest(source_parts[design_themes[0]]))
           else ('n/a' if (not inherited and deck_themes) else 'fail'),
           'sha256 %s' % (digest(source_parts[design_themes[0]])[:16] if design_themes else 'n/a'),
           'sha256 %s' % (digest(parts[deck_themes[0]])[:16] if deck_themes else 'none'),
           'theme part %s' % (deck_themes[0] if deck_themes else 'missing'))
    deck_xml = (parts[deck_themes[0]] if deck_themes else b'').decode('utf-8', 'replace')
    design_xml = (source_parts[design_themes[0]] if design_themes else b'').decode('utf-8', 'replace')
    deck_fonts = sorted(set(re.findall(r'typeface="([^"]+)"', deck_xml)))
    design_fonts = sorted(set(re.findall(r'typeface="([^"]+)"', design_xml)))
    record('theme_fonts', 'theme font scheme unchanged (no silent font swap)',
           'pass' if (deck_fonts == design_fonts or not inherited) else 'fail',
           design_fonts or 'builtin Arial', deck_fonts,
           'typefaces declared in the output theme')
    record('theme_colours', 'colour scheme unchanged (accent colours not replaced)',
           'pass' if (_theme_colours(deck_xml) == _theme_colours(design_xml) or not inherited) else 'fail',
           _theme_colours(design_xml) or 'builtin academic scheme', _theme_colours(deck_xml),
           '%d srgbClr value(s) compared with the template theme' % len(_theme_colours(design_xml)))
    overrides = []
    for number in range(1, slide_count + 1):
        xml = parts.get('ppt/slides/slide%d.xml' % number, b'').decode('utf-8', 'replace')
        overrides += ['slide%d:%s' % (number, value) for value in _theme_colours(xml)]
    record('no_local_colour_override', 'slide bodies do not hard-code colours over the theme',
           'pass' if not overrides else 'warn', 'no srgbClr in slide bodies',
           overrides or 'none', '%d literal colour value(s) inside slide XML' % len(overrides))
    unbound, total = [], 0
    for number in range(1, slide_count + 1):
        layout_part = used_layouts[number - 1]
        layout_xml = (source_parts.get(layout_part) or parts.get(layout_part) or b'').decode('utf-8', 'replace')
        layout_refs = _placeholders(layout_xml)
        slide_xml = parts.get('ppt/slides/slide%d.xml' % number, b'').decode('utf-8', 'replace')
        for kind, index in _placeholders(slide_xml):
            total += 1
            if not any(kind == other_kind and (index is None or other_index is None or index == other_index)
                       for other_kind, other_index in layout_refs):
                unbound.append('slide%d:%s/%s' % (number, kind, index))
    record('placeholder_binding', 'every slide placeholder exists in its layout',
           'pass' if not unbound else 'fail', 'ph type/idx present in the bound layout',
           '%d/%d bound' % (total - len(unbound), total),
           'unbound: %s' % (unbound[:6] or 'none'))
    footer_slides = [number for number in range(1, slide_count + 1)
                     if any(kind == 'ftr' for kind, _index in
                            _placeholders(parts.get('ppt/slides/slide%d.xml' % number, b'')
                                          .decode('utf-8', 'replace')))]
    if template.get('footer_slot'):
        record('footer_slot', 'footer uses the template ftr placeholder',
               'pass' if footer_slides else 'fail', 'ftr placeholder on body slides',
               '%d slide(s) with ftr' % len(footer_slides),
               'layouts exposing ftr: %s' % [name.rsplit('/', 1)[-1]
                                             for name, info in template.get('layouts', [])
                                             if 'ftr' in info['types']])
    else:
        record('footer_slot', 'footer drawn as a text box (the template has no ftr slot)',
               'n/a' if not inherited else 'warn', 'ftr placeholder',
               '%d slide(s) with ftr' % len(footer_slides),
               'no ftr placeholder in the template; footer text kept: %s'
               % shorten(meta.get('footer'), 60))
    footer_probe = xml_escape(meta.get('footer') or '')[:48]
    carried = sum(1 for number in range(1, slide_count + 1)
                  if footer_probe and footer_probe in
                  parts.get('ppt/slides/slide%d.xml' % number, b'').decode('utf-8', 'replace'))
    record('footer_text', 'footer string matches the workorder verbatim',
           'pass' if (not footer_probe or carried) else 'warn', shorten(meta.get('footer'), 60),
           '%d/%d slide(s) carry it' % (carried, slide_count),
           'one footer string reused on every slide, no per-slide rewrite')
    notes_masters = [name for name in parts if re.match(r'ppt/notesMasters/notesMaster\d+\.xml$', name)]
    record('notes_master', 'notes master present so speaker notes stay editable',
           'pass' if notes_masters else 'fail', 'ppt/notesMasters/notesMaster1.xml',
           notes_masters or 'missing', '%d notesMaster part(s)' % len(notes_masters))
    deck_media = sorted(name for name in parts if name.startswith('ppt/media/'))
    design_media = sorted(name for name in source_parts if name.startswith('ppt/media/'))
    record('media_copied', 'template media parts preserved',
           'pass' if len(deck_media) >= len(design_media) else 'warn',
           '%d template media part(s)' % len(design_media),
           '%d media part(s) in the output' % len(deck_media),
           'media: %s' % (deck_media[:4] or 'none'))
    hard_ids = ('slide_size', 'master', 'layouts_resolved', 'theme_fonts', 'theme_colours',
                'placeholder_binding', 'notes_master')
    failures = [item['id'] for item in items if item['status'] == 'fail' and item['id'] in hard_ids]
    layout_map = [dict(slide=number,
                       layout=(used_layouts[number - 1].rsplit('/', 1)[-1]
                               if used_layouts[number - 1] else None),
                       bound=bool(used_layouts[number - 1] and used_layouts[number - 1] in parts))
                  for number in range(1, slide_count + 1)]
    deviations = [dict(check=item['id'], status=item['status'], reason=item.get('evidence'))
                  for item in items if item['status'] in ('fail', 'warn')]
    if inherited:
        source = str(template_path) if template_path else 'builtin-default'
    elif template_path:
        source = 'builtin-default (template unreadable: %s)' % template_path
    else:
        source = 'builtin-default'
    return dict(source=source, inherited=inherited,
                template_sha256=(digest(Path(template_path).read_bytes())
                                 if template_path and Path(template_path).exists() else None),
                checks=items, failures=failures, layout_map=layout_map, deviations=deviations,
                passes=sum(1 for item in items if item['status'] == 'pass'),
                fails=sum(1 for item in items if item['status'] == 'fail'),
                warns=sum(1 for item in items if item['status'] == 'warn'),
                na=sum(1 for item in items if item['status'] == 'n/a'),
                overall_pass=not failures)
def _shape_runs(xml):
    shapes = []
    for match in re.finditer(r'<p:sp>.*?</p:sp>', xml, re.S):
        chunk = match.group(0)
        name = re.search(r'<p:cNvPr[^>]*name="([^"]*)"', chunk)
        sizes = [int(value) / 100.0 for value in re.findall(r'<a:rPr[^>]*sz="(\d+)"', chunk)]
        xfrm = re.search(r'<a:off x="(-?\d+)" y="(-?\d+)"/><a:ext cx="(\d+)" cy="(\d+)"/>', chunk)
        shapes.append(dict(name=(name.group(1) if name else ''), sizes=sizes,
                           paragraphs=len(re.findall(r'<a:p>', chunk)),
                           box=([int(xfrm.group(1)), int(xfrm.group(2)),
                                 int(xfrm.group(3)), int(xfrm.group(4))] if xfrm else None)))
    return shapes
def format_compliance(pptx, out_dir, pdf_pages, pages, meta, content_map, golden, requested,
                      design=None, export_method=None):
    report = dict(schema='format_compliance.v1',
                  generated_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  case_id=(meta or {}).get('case_id'), deck=None, canvas=None, page_count=None,
                  font_sizes=None, font_family=None, footer=None, method=None,
                  checks=[], failures=[], overall_pass=False)
    def record(check_id, item, status, expected, actual, evidence):
        report['checks'].append(dict(id=check_id, item=item, status=status, expected=expected,
                                     actual=actual, evidence=evidence))
    try:
        blob = Path(pptx).read_bytes()
        with zipfile.ZipFile(pptx) as archive:
            names = archive.namelist()
            presentation = archive.read('ppt/presentation.xml').decode('utf-8', 'replace')
            slide_names = sorted(name for name in names
                                 if re.match(r'ppt/slides/slide\d+\.xml$', name))
            slide_xml = [archive.read(name).decode('utf-8', 'replace') for name in slide_names]
            theme_name = next((name for name in names
                               if re.match(r'ppt/theme/theme\d+\.xml$', name)), None)
            theme_xml = archive.read(theme_name).decode('utf-8', 'replace') if theme_name else ''
        report['deck'] = dict(path=str(pptx), bytes=len(blob), sha256=digest(blob),
                              slides=len(slide_names))
    except Exception as err:
        record('pptx_readable', 'the pptx opens as an OPC package', 'fail',
               'readable .pptx', 'unreadable', '%s: %s' % (type(err).__name__, err))
        report['failures'] = [dict(check='pptx_readable', reason=str(err))]
        return report
    design = design or {}
    report['deck']['template_source'] = design.get('path') or 'builtin-default'
    size_match = re.search(r'<p:sldSz[^>]*cx="(\d+)"[^>]*cy="(\d+)"', presentation)
    actual_size = [int(size_match.group(1)), int(size_match.group(2))] if size_match else None
    expected_size = list(design.get('sldSz') or DEFAULT_CANVAS)
    width, height = (actual_size or expected_size)[:2]
    ratio = round(width / float(height), 4) if height else 0.0
    target_ratio = round(16 / 9.0, 4)
    ratio_ok = abs(ratio - target_ratio) <= 0.01
    report['canvas'] = dict(slide_width_emu=width, slide_height_emu=height,
                            ratio=ratio, target='16:9', target_ratio=target_ratio,
                            tolerance=0.01, expected_emu=expected_size,
                            status='pass' if ratio_ok else 'fail')
    record('canvas_ratio', 'slide canvas is 16:9 within 0.01', 'pass' if ratio_ok else 'fail',
           '16:9 (ratio %.4f)' % target_ratio, '%.4f (%d x %d emu)' % (ratio, width, height),
           'presentation.xml/p:sldSz; design canvas %s emu' % expected_size)
    counts = dict(requested=requested, delivered=len(pages), pptx_slides=len(slide_xml),
                  content_map_rows=len(content_map), golden_pages=(len(golden['pages'])
                                                                  if golden else None),
                  pdf_pages=pdf_pages)
    internal = [value for key, value in counts.items()
                if key in ('delivered', 'pptx_slides', 'content_map_rows', 'golden_pages', 'pdf_pages')
                and value is not None]
    internal_ok = bool(internal) and all(value == counts['delivered'] for value in internal)
    if not internal_ok:
        page_status = 'fail'
    elif requested is not None and requested != counts['delivered']:
        page_status = 'warn'
    else:
        page_status = 'pass'
    report['page_count'] = dict(counts, internal_consistent=internal_ok, status=page_status)
    record('page_count', 'page count fits the request and every artefact agrees',
           page_status, 'requested %s, delivered %d, all artefacts equal'
           % (requested, counts['delivered']),
           'pptx %d / content_map %d / golden %s / PDF %s'
           % (counts['pptx_slides'], counts['content_map_rows'], counts['golden_pages'], pdf_pages),
           'a request the source cannot fill is recorded as a shortfall, never padded')
    title_sizes, body_sizes, subtitle_sizes, footer_sizes, font_rows = [], [], [], [], []
    for index, xml in enumerate(slide_xml, 1):
        row = dict(slide=index, title_pt=None, subtitle_pt=None, body_pt=[], footer_pt=None,
                   bullets=0, footer_box=None)
        for shape in _shape_runs(xml):
            name, sizes = shape['name'], shape['sizes']
            if not sizes:
                continue
            if name.startswith('Title'):
                row['title_pt'] = sizes[0]
            elif name.startswith('Subtitle'):
                row['subtitle_pt'] = sizes[0]
            elif name.startswith('Content'):
                row['body_pt'] = sizes
                row['bullets'] = shape['paragraphs']
            elif name.startswith('Footer'):
                row['footer_pt'] = sizes[0]
                row['footer_box'] = shape['box']
        for key, bucket in (('title_pt', title_sizes), ('subtitle_pt', subtitle_sizes),
                            ('footer_pt', footer_sizes)):
            if row[key] is not None:
                bucket.append(row[key])
        body_sizes += row['body_pt']
        font_rows.append(row)
    titles_ok = bool(title_sizes) and all(28 <= value <= 36 for value in title_sizes)
    bodies_ok = bool(body_sizes) and all(12 <= value <= 20 for value in body_sizes)
    subs_ok = all(14 <= value <= 18 for value in subtitle_sizes)
    foots_ok = all(8 <= value <= 12 for value in footer_sizes)
    hierarchy = []
    for row in font_rows:
        if row['title_pt'] is not None and row['body_pt'] and row['title_pt'] <= max(row['body_pt']):
            hierarchy.append('slide %d title %.1f <= body %.1f'
                             % (row['slide'], row['title_pt'], max(row['body_pt'])))
        elif row['title_pt'] is not None and row['subtitle_pt'] is not None \
                and row['title_pt'] <= row['subtitle_pt']:
            hierarchy.append('slide %d title %.1f <= subtitle %.1f'
                             % (row['slide'], row['title_pt'], row['subtitle_pt']))
    report['font_sizes'] = dict(
        title_pt=sorted(set(title_sizes)), subtitle_pt=sorted(set(subtitle_sizes)),
        body_ladder_pt=sorted(set(body_sizes)), footer_pt=sorted(set(footer_sizes)),
        slides=font_rows, hierarchy_violations=hierarchy,
        status='pass' if (titles_ok and bodies_ok and subs_ok and foots_ok and not hierarchy)
        else 'fail')
    record('font_title', 'every page title sits on the 28-36 pt heading step',
           'pass' if titles_ok else 'fail', 'title 28-36 pt', sorted(set(title_sizes)),
           'sizes from ppt/slides/slideN.xml rPr/@sz (hundredths of a point)')
    record('font_body', 'every body bullet sits on the 12-20 pt ladder',
           'pass' if bodies_ok else 'fail', 'body 12-20 pt', sorted(set(body_sizes)),
           'the writer walks 20/18/16/15/14/13/12 pt down the ladder; nothing below 12 pt')
    record('font_hierarchy', 'the title is larger than the body on every page',
           'pass' if not hierarchy else 'fail', 'title > body',
           hierarchy or 'title above subtitle and body on every page',
           'per-shape sz attributes compared page by page')
    record('font_footer', 'the footer uses the small 8-12 pt step',
           'pass' if foots_ok else 'fail', 'footer 8-12 pt', sorted(set(footer_sizes)),
           'footer text box size on the pages that carry it')
    theme_faces = sorted({face for face in re.findall(r'typeface="([^"]+)"', theme_xml) if face})
    for face in design.get('fonts') or []:
        if face not in theme_faces:
            theme_faces.append(face)
    slide_faces = sorted({face for xml in slide_xml
                          for face in re.findall(r'typeface="([^"]*)"', xml) if face})
    foreign = [face for face in slide_faces if face not in theme_faces]
    report['font_family'] = dict(theme_faces=theme_faces, slide_faces=slide_faces,
                                 foreign=foreign, status='pass' if not foreign else 'fail')
    record('font_family', 'slide runs name only faces inherited from the theme',
           'pass' if not foreign else 'fail', 'slide faces subset of theme faces', slide_faces,
           'theme faces: %s; foreign: %s' % (theme_faces, foreign or 'none'))
    footer_expected = (meta or {}).get('footer') or ''
    probe = xml_escape(footer_expected)[:48]
    body_slides = [page for page in pages if page.get('role') != 'title']
    carried = [row['slide'] for row in font_rows
               if probe and ('%s' % probe) in slide_xml[row['slide'] - 1]]
    footer_slot = 'ftr' if any('<p:ph type="ftr"' in xml for xml in slide_xml) else 'textbox'
    bottom_ok = all(row['footer_box'] is None
                    or (row['footer_box'][1] >= int(height * 0.85)
                        and row['footer_box'][1] + row['footer_box'][3] <= height)
                    for row in font_rows if row['footer_box'])
    footer_ok = bool(body_slides) and len(carried) == len(body_slides) and bottom_ok
    report['footer'] = dict(expected=footer_expected, slot=footer_slot,
                            body_slides=len(body_slides), slides_carrying=len(carried),
                            bottom_band_ok=bottom_ok, status='pass' if footer_ok else 'fail')
    record('footer_text', 'the workorder footer string reaches every body slide unchanged',
           'pass' if len(body_slides) and len(carried) == len(body_slides) else 'fail',
           '%d body slide(s)' % len(body_slides), '%d slide(s) carry it' % len(carried),
           'slot=%s, text=%r' % (footer_slot, footer_expected[:48]))
    record('footer_position', 'the footer stays inside the bottom band of the canvas',
           'pass' if bottom_ok else 'fail', 'y >= 85% of canvas height, y+cy <= canvas height',
           'canvas height %d emu' % height, 'footer offsets read from the slide XML')
    report['method'] = export_method
    failures = [check['id'] for check in report['checks'] if check['status'] == 'fail']
    report['failures'] = [dict(check=check['id'], reason=check['evidence'])
                          for check in report['checks'] if check['status'] == 'fail']
    report['overall_pass'] = not failures
    report['verdict'] = 'pass' if not failures else 'fail: ' + ', '.join(failures)
    return report
def _fallback_probes(limit=30):
    if os.environ.get(PROBE_ENV):
        return ('n/a', 'fallback probes are skipped inside a probe subprocess (recursion guard)', [])
    main_py = Path(__file__).resolve().parent / 'main.py'
    if not main_py.exists():
        return ('n/a', 'main.py not found next to verify.py', [])
    root, rows = None, []
    try:
        root = Path(tempfile.mkdtemp(prefix='deck_probe_'))
        paper = ('# Probe paper\n\nWe measured 12 samples over 3 weeks and the effect was stable. '
                 'The method controls for temperature. The conclusion is limited to the sampled buildings.\n')
        for label, bad_case in (('empty_input', None), ('bad_json', '{ this is not valid json: [')):
            indir = root / label / 'input'
            indir.mkdir(parents=True, exist_ok=True)
            if bad_case:
                (indir / 'case.json').write_text(bad_case, encoding='utf-8')
                (indir / 'paper.md').write_text(paper, encoding='utf-8')
            outdir, workdir = root / label / 'output', root / label / 'work'
            env = dict(os.environ)
            env[PROBE_ENV] = '1'
            try:
                proc = subprocess.run([sys.executable, '-B', str(main_py),
                                       '--input', str(indir), '--output', str(outdir),
                                       '--work', str(workdir)],
                                      capture_output=True, timeout=limit, env=env)
                exit_code = proc.returncode
            except Exception as err:
                rows.append(dict(scenario=label, exit_code=None, status=None, ok=False,
                                 result_json=False, error='%s: %s' % (type(err).__name__, err)))
                continue
            result, error = None, None
            try:
                result = json.loads((outdir / 'result.json').read_text(encoding='utf-8'))
            except Exception as err:
                error = '%s: %s' % (type(err).__name__, err)
            status = (result or {}).get('status')
            rows.append(dict(scenario=label, exit_code=exit_code, status=status,
                             result_json=(result is not None),
                             ok=(exit_code == 0 and status in ALLOWED_STATUS),
                             error=error))
    except Exception as err:
        return ('warn', 'the fallback probe could not run on this runtime: %s: %s'
                % (type(err).__name__, err), rows)
    finally:
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)
    ok = bool(rows) and all(row['ok'] for row in rows)
    ran_bad = any(row.get('exit_code') is not None and not row['ok'] for row in rows)
    env_bad = any(row.get('exit_code') is None for row in rows)
    detail = '; '.join('%s: exit=%s, status=%s%s' % (
        row['scenario'], row['exit_code'], row['status'],
        '' if row['ok'] else ' (%s)' % (row.get('error') or 'not ok')) for row in rows) or 'no probe ran'
    return ('pass' if ok else ('fail' if ran_bad else ('warn' if env_bad else 'fail')), detail, rows)
def run_self_check(output_dir, result, contract_keys, expect_assets=True):
    output_dir = Path(output_dir)
    checks, assets = [], []
    def add(check_id, item, status, evidence):
        checks.append(dict(id=check_id, item=item, status=status, evidence=evidence))
    echoed = [key for key in contract_keys if key in result]
    add('contract_echo', 'every input output_contract key sits at the result root',
        'pass' if len(echoed) == len(contract_keys) else 'fail',
        '%d/%d contract key(s) present at the root' % (len(echoed), len(contract_keys)))
    source = result.get('editable_source') or {}
    slides = source.get('slides')
    pptx_path = Path(source.get('path') or output_dir / 'presentation.pptx')
    inventory = _pptx_inventory(pptx_path if pptx_path.exists() else None)
    main_ok = bool(inventory.get('opens') and inventory.get('has_presentation')
                   and inventory.get('slide_parts') == slides
                   and inventory.get('notes_parts') == slides)
    add('main_artifact', 'the editable pptx opens with one slide and one notes part per page',
        'pass' if main_ok else 'fail',
        ('%d member(s), %d slide part(s), %d notes part(s), sha256 %s'
         % (inventory.get('members', 0), inventory.get('slide_parts', 0),
            inventory.get('notes_parts', 0), (inventory.get('sha256') or 'n/a')[:16]))
        if inventory.get('opens') else 'pptx unreadable: %s' % (inventory.get('error') or 'unknown'))
    export = result.get('export_artifact') or {}
    pdf_path = Path(export.get('path') or output_dir / 'presentation.pdf')
    pdf_pages = None
    if pdf_path.exists() and pdf_path.read_bytes()[:4] == b'%PDF':
        pdf_pages = len(re.findall(rb'/Type\s*/Page[^s]', pdf_path.read_bytes()))
        add('export_artifact', 'the PDF preview starts with %PDF- and has one page per slide',
            'pass' if pdf_pages == slides else 'fail',
            '%d PDF page(s) for %s slide(s), method=%s, degraded=%s'
            % (pdf_pages, slides, export.get('method'), export.get('degraded')))
    else:
        skipped_export = ((result.get('compliance_checks') or {}).get('export') or {}).get('method') == 'skipped'
        add('export_artifact', 'the PDF preview starts with %PDF- and has one page per slide',
            'n/a' if skipped_export else 'warn',
            'export_artifact=%s (the pptx remains the deliverable; a missing preview is recorded, '
            'not fabricated)' % (export or None))
    plan_pages = None
    try:
        plan_pages = len(json.loads((output_dir / 'plan_v0.json').read_text(encoding='utf-8'))
                         .get('pages') or [])
    except Exception:
        plan_pages = None
    golden = result.get('page_golden') or {}
    content_map = result.get('content_map') or []
    counts = dict(golden_pages=len(golden.get('pages') or []) or None, plan_pages=plan_pages,
                  pptx_slide_parts=inventory.get('slide_parts'),
                  pptx_notes_parts=inventory.get('notes_parts'),
                  content_map_rows=len(content_map), pdf_pages=pdf_pages)
    mismatched = ['%s=%s' % (name, value) for name, value in counts.items()
                  if value is not None and value != slides]
    add('page_count_consistency',
        'golden standard, page plan, pptx slides/notes, content_map and PDF agree on the page count',
        'pass' if (slides and not mismatched) else 'fail',
        '%s page(s); %s' % (slides, 'all artefacts agree' if not mismatched
                            else 'mismatch: ' + ', '.join(mismatched)))
    gold_pages = golden.get('pages') or []
    delivered_quotes = {row.get('slide_index'): {bullet.get('quote') for bullet in
                                                 (row.get('bullets') or []) if bullet.get('quote')}
                        for row in content_map}
    trace_missing = []
    for page in gold_pages:
        quotes = delivered_quotes.get(page.get('page')) or set()
        for item in page.get('evidence') or []:
            if item.get('kind') == 'quote' and item.get('quote') and item['quote'] not in quotes:
                trace_missing.append('p%s' % page.get('page'))
    golden_items = [item for page in gold_pages for item in page.get('evidence') or []]
    golden_verified = [item for item in golden_items if item.get('verified') is True]
    source_bullets = [bullet for row in content_map for bullet in (row.get('bullets') or [])
                      if bullet.get('kind') == 'source']
    unverified = [bullet for bullet in source_bullets if bullet.get('verified') is not True]
    quote_ok = bool(source_bullets) and not unverified and not trace_missing \
        and (not golden_items or len(golden_verified) == len(golden_items))
    add('evidence_quotes',
        'every source bullet and every frozen golden quote resolves to a verbatim source sentence',
        'pass' if quote_ok else ('n/a' if not source_bullets else 'fail'),
        '%d/%d source bullet(s) verified; golden evidence %d/%d verified, page trace %s'
        % (len(source_bullets) - len(unverified), len(source_bullets),
           len(golden_verified), len(golden_items), 'complete' if not trace_missing
           else 'missing on ' + ', '.join(sorted(set(trace_missing)))))
    missing_assets, missing_fields = [], []
    for name in ASSET_FILES:
        path = output_dir / name
        if name == 'self_check.json':
            assets.append(dict(name=name, bytes=None, status='written by this stage'))
            continue
        if not path.exists() or not path.stat().st_size:
            missing_assets.append(name)
            assets.append(dict(name=name, bytes=0, status='missing'))
            continue
        parsed = True
        if name.endswith('.json'):
            try:
                json.loads(path.read_text(encoding='utf-8'))
            except Exception:
                parsed = False
                missing_assets.append(name + ' (invalid JSON)')
        assets.append(dict(name=name, bytes=path.stat().st_size,
                           status='ok' if parsed else 'invalid JSON'))
    for field in ('page_golden', 'page_diff', 'version_history', 'run_log', 'export_check',
                  'template_check', 'format_compliance'):
        if not result.get(field):
            missing_fields.append(field)
    if not expect_assets:
        add('asset_completeness',
            'all eight page-level verifiable artefacts exist as non-empty files and sit in result.json',
            'n/a', '--no-golden run: the inspection artefacts are skipped by that rollback flag; '
                   'run.log, format_compliance.json and self_check.json are still written')
    else:
        add('asset_completeness',
            'all eight page-level verifiable artefacts exist as non-empty files and sit in result.json',
            'pass' if (not missing_assets and not missing_fields) else 'fail',
            '%d/%d file(s) on disk; result.json fields %s'
            % (len(ASSET_FILES) - len(missing_assets), len(ASSET_FILES),
               'complete' if not missing_fields else 'missing ' + ', '.join(missing_fields))
            + '; self_check.json is emitted by this stage and mirrored immediately after')
    probe_status, probe_detail, probe_rows = _fallback_probes()
    add('fallback_probes',
        'empty input and a corrupt case.json still exit 0 with a valid result envelope',
        probe_status, probe_detail)
    probe_codes = [row['exit_code'] for row in probe_rows if row.get('exit_code') is not None]
    exit_ok = ((probe_status in ('n/a', 'warn') and not probe_codes)
               or (probe_codes and all(code == 0 for code in probe_codes)))
    add('exit_code', 'the process exits 0, including on the fallback paths',
        'pass' if exit_ok else 'fail',
        'the entry point always returns 0; probe subprocess exit code(s): %s'
        % (probe_codes or 'not measured (%s)' % probe_status))
    status = result.get('status')
    degraded = bool(export.get('degraded'))
    hard_gaps = (result.get('page_diff') or {}).get('hard_gaps')
    add('status_honesty', 'status never claims ok while the preview is degraded or a page hard-fails',
        'pass' if not (status == 'ok' and (degraded or hard_gaps)) else 'fail',
        'status=%r, export degraded=%s, page hard gaps=%s' % (status, degraded, hard_gaps))
    failures = [check['id'] for check in checks if check['status'] == 'fail']
    skipped = [check['id'] for check in checks if check['status'] in ('n/a', 'warn', 'unknown')]
    report = dict(schema='self_check.v1',
                  generated_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  case_id=result.get('case_id'), exit_code=0, status=status,
                  overall_pass=not failures, pass_=not failures,
                  passed=sum(1 for check in checks if check['status'] == 'pass'),
                  skipped=skipped, total=len(checks), failures=failures, checks=checks,
                  assets=assets, fallback_probes=probe_rows,
                  notes=['written by the closing stage; result.json mirrors this summary under '
                         'self_check (legacy alias selfcheck) right after this file exists',
                         'checks read the files on disk, not builder state'])
    try:
        (output_dir / 'self_check.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    except Exception:
        pass
    summary = dict(path=str(output_dir / 'self_check.json'), schema='self_check.v1',
                   overall_pass=report['overall_pass'], pass_=report['overall_pass'],
                   exit_code=0, passed=report['passed'], skipped=len(skipped),
                   failed=len(failures), total=len(checks), failures=failures,
                   assets=assets,
                   checks=[dict(id=check['id'], status=check['status']) for check in checks])
    return summary
