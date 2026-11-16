
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
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
def export_check(pdf, slide_count, fits, figures, template):
    report = dict(path=str(pdf) if pdf else None, checks=[], overall_pass=False, verdict='fail')
    if not pdf or not Path(pdf).exists():
        report['checks'].append(dict(id='pdf_present', item='PDF export produced', status='fail',
                                     evidence='no PDF at %s (converter missing or failed)' % pdf))
        report['verdict'] = 'no PDF: the pptx remains the deliverable'
        return report
    blob = Path(pdf).read_bytes()
    theme_fonts = [font for font in (template.get('fonts') or []) if font] or ['Arial']
    def record(check_id, item, status, evidence):
        report['checks'].append(dict(id=check_id, item=item, status=status, evidence=evidence))
    report['pdf'] = dict(bytes=len(blob), sha256=digest(blob),
                         header=blob[:4].decode('latin-1', 'replace'),
                         header_ok=blob[:4] == b'%PDF')
    record('pdf_header', 'file starts with the PDF signature',
           'pass' if blob[:4] == b'%PDF' else 'fail',
           'first bytes %r · %d bytes · sha256 %s' % (blob[:5], len(blob), digest(blob)[:16]))
    pages, counted_via = None, 'regex /Type /Page'
    if shutil.which('pdfinfo'):
        code, info, _err = _run([shutil.which('pdfinfo'), str(pdf)])
        match = re.search(r'Pages:\s+(\d+)', info)
        if code == 0 and match:
            pages, counted_via = int(match.group(1)), 'pdfinfo'
    if pages is None:
        pages = len(re.findall(rb'/Type\s*/Page[^s]', blob))
    report['page_count'] = dict(slides=slide_count, pdf_pages=pages, via=counted_via,
                                ok=pages == slide_count)
    record('page_count', 'PDF page count equals slide count',
           'pass' if pages == slide_count else 'fail',
           '%d slide(s) -> %d PDF page(s) via %s' % (slide_count, pages, counted_via))
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
                           ok=(bool(fonts) and not unembedded and not substituted))
    record('fonts_embedded', 'every PDF font is embedded (no viewer-side substitution)',
           'pass' if (fonts and not unembedded) else 'fail',
           'pdffonts: %s' % (', '.join('%s emb=%s' % (font['name'], 'yes' if font['embedded'] else 'no')
                                       for font in (fonts or [])) or 'not parsed'))
    record('fonts_inherited', 'PDF font families match the template theme scheme',
           'pass' if (fonts and not substituted) else ('warn' if fonts else 'fail'),
           'theme %s -> PDF %s%s%s' % (
               theme_fonts, [font['name'] for font in (fonts or [])],
               '' if not substituted else ' · substituted: %s' % substituted,
               '' if not cjk_fallback else ' · CJK glyph fallback (expected for Han text): %s' % cjk_fallback))
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
                                   ok=bool(boxes) and not violations, modelled=model)
    record('text_overflow', 'no word crosses the page box in the rendered PDF',
           'pass' if (boxes and not violations) else ('fail' if boxes else 'unknown'),
           '%d page(s), %d word(s) checked, worst excess %.2f pt; modelled max utilization %.2f, '
           'modelled overflow slide(s) %s' % (
               len(boxes or []), sum(len(page['words']) for page in (boxes or [])),
               worst_excess, model['max_utilization'], model['overflow_slides'] or 'none'))
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
    report['overall_pass'] = not hard_failures
    report['verdict'] = ('pass' if not hard_failures
                         else 'fail: ' + ', '.join(check['id'] for check in hard_failures))
    return report
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
    if inherited:
        source = str(template_path) if template_path else 'builtin-default'
    elif template_path:
        source = 'builtin-default (template unreadable: %s)' % template_path
    else:
        source = 'builtin-default'
    return dict(source=source, inherited=inherited,
                template_sha256=(digest(Path(template_path).read_bytes())
                                 if template_path and Path(template_path).exists() else None),
                checks=items, failures=failures,
                passes=sum(1 for item in items if item['status'] == 'pass'),
                fails=sum(1 for item in items if item['status'] == 'fail'),
                warns=sum(1 for item in items if item['status'] == 'warn'),
                na=sum(1 for item in items if item['status'] == 'n/a'),
                overall_pass=not failures)
def run_selfcheck(output_dir, result, contract_keys):
    output_dir = Path(output_dir)
    checks = []
    def add(check_id, item, status, evidence):
        checks.append(dict(id=check_id, item=item, status=status, evidence=evidence))
    source = result.get('editable_source') or {}
    export = result.get('export_artifact') or {}
    content_map = result.get('content_map') or []
    slides = source.get('slides')
    pptx_path = Path(source.get('path') or output_dir / 'presentation.pptx')
    if pptx_path.exists():
        try:
            with zipfile.ZipFile(pptx_path) as archive:
                members = archive.namelist()
            slide_parts = sorted(name for name in members
                                 if re.match(r'ppt/slides/slide\d+\.xml$', name))
            notes_parts = [name for name in members if name.startswith('ppt/notesSlides/notesSlide')]
            add('pptx_opens', 'pptx opens as an OPC package', 'pass',
                '%d member(s), %d slide part(s), sha256 %s'
                % (len(members), len(slide_parts), digest(pptx_path.read_bytes())[:16]))
            ok = ('ppt/presentation.xml' in members and '[Content_Types].xml' in members
                  and len(slide_parts) == slides)
            add('pptx_slide_count', 'pptx slide parts equal editable_source.slides',
                'pass' if ok else 'fail',
                '%d part(s) vs %s declared' % (len(slide_parts), slides))
            add('pptx_notes', 'every slide has a notes part', 'pass' if len(notes_parts) == slides else 'fail',
                '%d notes part(s) for %s slide(s)' % (len(notes_parts), slides))
        except Exception as err:
            add('pptx_opens', 'pptx opens as an OPC package', 'fail',
                '%s: %s' % (type(err).__name__, err))
    else:
        add('pptx_opens', 'pptx opens as an OPC package', 'fail', 'no pptx at %s' % pptx_path)
    pdf_path = Path(export.get('path') or output_dir / 'presentation.pdf')
    if pdf_path.exists() and pdf_path.read_bytes()[:4] == b'%PDF':
        pages = len(re.findall(rb'/Type\s*/Page[^s]', pdf_path.read_bytes()))
        add('pdf_preview', 'PDF preview has a real PDF header and one page per slide',
            'pass' if pages == slides else ('n/a' if not slides else 'fail'),
            '%d PDF page(s) for %s slide(s)' % (pages, slides))
    else:
        add('pdf_preview', 'PDF preview has a real PDF header and one page per slide',
            'n/a' if not export else 'fail',
            'export_artifact=%s (degraded runs keep the pptx as deliverable)' % (export or None))
    add('content_map_shape', 'content_map has one row per delivered slide',
        'pass' if len(content_map) == slides else 'fail',
        '%d content_map row(s) vs %s slide(s)' % (len(content_map), slides))
    echoed = [key for key in contract_keys if key in result]
    add('contract_echo', 'every input output_contract key is present at the result root',
        'pass' if len(echoed) == len(contract_keys) else 'fail',
        '%d/%d key(s) present' % (len(echoed), len(contract_keys)))
    source_bullets = [bullet for row in content_map for bullet in (row.get('bullets') or [])
                      if bullet.get('kind') == 'source']
    unverified = [bullet for bullet in source_bullets if bullet.get('verified') is not True]
    add('evidence_rate', 'every source bullet is verified against the extracted text',
        'pass' if (source_bullets and not unverified) else ('n/a' if not source_bullets else 'fail'),
        '%d/%d source bullet(s) verified' % (len(source_bullets) - len(unverified), len(source_bullets)))
    status = result.get('status')
    degraded = bool((result.get('export_artifact') or {}).get('degraded'))
    honest = not (status == 'ok' and degraded)
    add('status_honesty', 'status does not claim ok while the export is degraded',
        'pass' if honest else 'fail', 'status=%r, export degraded=%s' % (status, degraded))
    failures = [check['id'] for check in checks if check['status'] == 'fail']
    report = dict(generated_at=__import__('time').strftime('%Y-%m-%dT%H:%M:%SZ',
                                                          __import__('time').gmtime()),
                  overall_pass=not failures, failures=failures, checks=checks)
    try:
        (output_dir / 'selfcheck.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    except Exception:
        pass
    return dict(path=str(output_dir / 'selfcheck.json'), overall_pass=report['overall_pass'],
                failures=failures, checks=[dict(id=check['id'], status=check['status'])
                                           for check in checks])
