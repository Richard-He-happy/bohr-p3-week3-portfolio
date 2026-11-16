
import hashlib
import re
RULES_VERSION = 'pagegold-2'
PKG_VERSION = '1.1.0'
SECTION_LABELS = ('abstract', 'intro', 'related', 'methods', 'results', 'discussion',
                  'conclusion', 'limits', 'body')
ROLE_SPEC = {
    'title': dict(job='identity of the paper plus audience framing', secs=[], rng=(1, 3), nums=0,
                  fig='n/a', claim='title copied from the source title line; subtitle names audience and source'),
    'notice': dict(job='name the missing input honestly', secs=[], rng=(1, 4), nums=0, fig='n/a',
                   claim='a notice page states no scientific finding'),
    'outline': dict(job='navigation, nothing numeric', secs=[], rng=(3, 12), nums=0, fig='n/a',
                    claim='one line for every section that actually follows'),
    'background': dict(job='why the problem is worth attention', secs=['abstract', 'intro', 'related'],
                       rng=(1, 4), nums=0, fig='optional',
                       claim='name the gap with a source sentence; invent no context'),
    'question': dict(job='the one question the study answers', secs=['abstract', 'intro'], rng=(1, 3),
                     nums=0, fig='n/a', claim='phrase the studied question, not its result'),
    'methods': dict(job='design, data and analysis window', secs=['methods'], rng=(1, 4), nums=1,
                    fig='optional', claim='state design and measurement; keep numbers verbatim'),
    'results': dict(job='one measured claim per page with its number', secs=['results', 'abstract'],
                    rng=(1, 4), nums=1, fig='required_if_available',
                    claim='every results page carries at least one verbatim number'),
    'discussion': dict(job='what the results mean', secs=['discussion', 'results'], rng=(1, 4), nums=0,
                       fig='optional', claim='interpretation must be attributed, never asserted'),
    'limitations': dict(job='scope and boundary', secs=['limits', 'discussion'], rng=(1, 4), nums=0,
                        fig='n/a', claim='name the boundary the source itself names'),
    'conclusion': dict(job='the take-away', secs=['conclusion', 'abstract'], rng=(1, 4), nums=1,
                       fig='n/a', claim='restate measured effects; add no new number'),
    'thanks': dict(job='close', secs=[], rng=(0, 2), nums=0, fig='n/a', claim='fixed credit line'),
}
NUMBER_PATTERNS = [
    ('pvalue', r'p\s*[<>=]\s*0?\.\d+', 3.0),
    ('ci', r'95\s*%\s*CI\s*[\d.]+\s*to\s*[\d.]+', 3.0),
    ('percent', r'\d+(?:\.\d+)?\s*(?:%|percent)', 3.0),
    ('temperature', r'\d+(?:\.\d+)?\s*degrees?\s*Celsius', 2.0),
    ('quantity', r'\d+(?:\.\d+)?\s*(?:kilowatt hours?|weeks?|days?|months?|years?|buildings?|'
                 r'dwellings?|participants?|samples?|sites?)', 1.5),
    ('decimal', r'(?<![\d.])\d+\.\d+(?![\d.])', 1.0),
]
FIGURE_RE = re.compile(r'\b(?:fig(?:ure)?s?\.?)\s*(\d+)|\b图\s*(\d+)', re.I)
TABLE_RE = re.compile(r'\b(?:table)s?\s*(\d+)|\b表\s*(\d+)', re.I)
HARD_CHECKS = ('role', 'bullets', 'evidence', 'overflow')
ALL_CHECKS = ('role', 'sections', 'numbers', 'citations', 'bullets', 'evidence', 'overflow')
def digest(value):
    if isinstance(value, str):
        value = value.encode('utf-8')
    return hashlib.sha256(value or b'').hexdigest()
def shorten(text, limit=160):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '\u2026'
def inventory(pool):
    numbers, figures, tables, sections = {}, {}, {}, {}
    for order, record in enumerate(pool):
        section = record.get('sec') or 'body'
        sections[section] = sections.get(section, 0) + 1
        for kind, pattern, weight in NUMBER_PATTERNS:
            for match in re.finditer(pattern, record['text'], re.I):
                token = match.group(0).strip()
                if len(token) < 2:
                    continue
                key = (token.lower(), section)
                if key not in numbers or weight > numbers[key]['weight']:
                    numbers[key] = dict(token=token, kind=kind, sec=section, page=record.get('page'),
                                        weight=weight, quote=record['text'], order=order)
        for match in FIGURE_RE.finditer(record['text']):
            number = int(match.group(1) or match.group(2))
            figures.setdefault(number, dict(n=number, sec=section, page=record.get('page'),
                                            quote=record['text']))
        for match in TABLE_RE.finditer(record['text']):
            number = int(match.group(1) or match.group(2))
            tables.setdefault(number, dict(n=number, sec=section, page=record.get('page'),
                                           quote=record['text']))
    return dict(numbers=sorted(numbers.values(), key=lambda row: (-row['weight'], row['order'])),
                figures=sorted(figures.values(), key=lambda row: row['n']),
                tables=sorted(tables.values(), key=lambda row: row['n']),
                sections=dict(sorted((label, count) for label, count in sections.items()
                                     if label in SECTION_LABELS)),
                sentences=len(pool),
                fingerprint=digest('\n'.join(record['text'] for record in pool)))
def _locator(meta, record):
    return '%s p.%s %s' % (meta.get('label'), record.get('page'), record.get('sec'))
def _required_numbers(items, availability, section_labels):
    if not section_labels:
        return []
    required, seen = [], set()
    for item in items:
        if item['sec'] not in section_labels:
            continue
        lowered = item['token'].lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        required.append(dict(token=item['token'], kind=item['kind'], locator=item['locator'],
                             quote=shorten(item.get('quote'), 400)))
        if len(required) >= 3:
            break
    return required
def _page_evidence(key_points, required, citations):
    evidence = [dict(kind='quote', locator=point['locator'], quote=point['quote'])
                for point in key_points if point['basis'] == 'source']
    evidence += [dict(kind='number', token=item['token'], locator=item['locator'],
                      quote=item.get('quote') or '') for item in required]
    evidence += [dict(kind=item['kind'], n=item['n'], locator=item['locator'],
                      quote=item.get('quote') or '') for item in citations]
    return evidence
def build_golden(pages, inv, meta, requested=None, source_text=''):
    available = set(inv['sections'])
    figure_pages, table_pages = {}, {}
    rows = []
    evidence_items, evidence_verified = 0, 0
    for page_number, page in enumerate(pages, 1):
        role = page['role']
        spec = ROLE_SPEC.get(role) or ROLE_SPEC['background']
        declared = list(spec['secs'])
        expected = [label for label in declared if label in available]
        collapsed = bool(declared) and len(available) <= 1
        number_items = [dict(token=item['token'], kind=item['kind'], sec=item['sec'],
                             locator=_locator(meta, item), quote=item.get('quote'))
                        for item in inv['numbers'] if item['sec'] in expected]
        required = _required_numbers(number_items, available, expected)
        primary = expected[:1]
        duty = primary[0] if primary else ''
        citations = []
        if duty and duty not in figure_pages:
            citations = [dict(kind='figure', n=item['n'], locator=_locator(meta, item),
                              quote=item.get('quote'))
                         for item in inv['figures'] if item['sec'] in primary][:2]
            citations += [dict(kind='table', n=item['n'], locator=_locator(meta, item),
                               quote=item.get('quote'))
                          for item in inv['tables'] if item['sec'] in primary][:2]
            if citations:
                figure_pages[duty] = page_number
        elif duty:
            duty = 'covered_by_page_%d' % figure_pages[duty]
        placement = spec['fig']
        if placement == 'required_if_available':
            placement = 'required' if meta.get('has_figure') else 'not_available_in_source'
        src = list(page.get('src') or [])
        key_points, rows_bullets = [], list(page.get('bullets') or [])
        for position, item in enumerate(rows_bullets):
            text = item[0] if isinstance(item, (tuple, list)) else str(item)
            if position < len(src):
                record = src[position]
                quote = record['text']
                points = dict(index=position + 1, basis='source', level=0,
                              bullet=shorten(text, 160), quote=quote,
                              section=record.get('sec'), source_page=record.get('page'),
                              locator=_locator(meta, record),
                              verified=(quote in source_text) if source_text else None)
            else:
                points = dict(index=position + 1, basis='front_matter', level=0,
                              bullet=shorten(text, 160), quote='', locator='',
                              origin='workorder/case metadata')
            key_points.append(points)
        evidence = _page_evidence(key_points, required, citations)
        verified = 0
        for item in evidence:
            evidence_items += 1
            if item['kind'] == 'quote':
                ok = bool(item['quote'] and (item['quote'] in source_text or not source_text))
                if not source_text:
                    ok = None
            else:
                ok = bool(item.get('quote') and item['quote'] in source_text) if source_text else None
            item['verified'] = ok
            if ok is True:
                verified += 1
                evidence_verified += 1
        rows.append(dict(
            page=page_number, role=role, title=shorten(page['title'], 110),
            narrative_job=spec['job'],
            expected_sections=expected or ['<none: role has no section contract>'],
            declared_sections=declared, section_contract_available=bool(expected),
            labels_collapsed=collapsed, bullet_range=list(spec['rng']),
            numbers_required=required, min_numbers=(spec['nums'] if expected else 0),
            citations_required=citations, figure_placement=placement,
            citation_duty=(duty or 'none'), claim_expectation=spec['claim'],
            key_points=key_points, evidence=evidence,
            planned_quotes=[shorten(record['text'], 90) for record in src]))
    headlines = [item for item in inv['numbers'] if item['sec'] in ('abstract', 'conclusion')][:6]
    deck = dict(headline_numbers=[dict(token=item['token'], kind=item['kind'],
                                       locator=_locator(meta, item),
                                       quote=shorten(item.get('quote'), 400)) for item in headlines],
                figure_numbers=[item['n'] for item in inv['figures']],
                table_numbers=[item['n'] for item in inv['tables']],
                sections_available=inv['sections'], pages=len(pages), requested=requested,
                roles=[page['role'] for page in pages], extraction=meta.get('extraction'),
                figure_in_source=bool(meta.get('has_figure')))
    return dict(rules_version=RULES_VERSION, generated_at=meta.get('stamp'),
                case_id=meta.get('case_id'),
                source=dict(label=meta.get('label'), fingerprint=inv['fingerprint'],
                            sentences=inv['sentences']),
                evidence_totals=dict(items=evidence_items, verified=evidence_verified,
                                     ratio=round(evidence_verified / evidence_items, 3)
                                     if evidence_items else 0.0,
                                     with_locator=sum(1 for row in rows for item in row['evidence']
                                                      if item.get('locator'))),
                deck=deck, pages=rows)
def _section_of(locator):
    parts = str(locator or '').split()
    if parts and parts[-1] in SECTION_LABELS:
        return parts[-1]
    return 'unknown' if locator else ''
def _check_role(expected, actual):
    return dict(ok=actual == expected, expected=expected, actual=actual,
                evidence='content_map role field')
def _check_sections(golden, page, body_bullets):
    expected = [label for label in page['expected_sections'] if label in SECTION_LABELS]
    actual = sorted({_section_of(bullet.get('locator')) for bullet in body_bullets
                     if bullet.get('locator')})
    if not expected and page.get('labels_collapsed'):
        available = golden['deck']['sections_available']
        return dict(ok=False, na=False, expected=page.get('declared_sections'), actual=actual,
                    evidence='declared %s but extraction exposed only %d section label(s) (%s); the page '
                             'cannot be shown to draw from its declared section'
                             % (page.get('declared_sections'), len(available),
                                ','.join(available) or 'none'))
    if not expected:
        available = golden['deck']['sections_available']
        return dict(ok=True, na=True, expected=page['expected_sections'], actual=actual,
                    evidence='role has no section contract here; source sections: %s'
                             % (','.join(available) or 'none'))
    hits = [label for label in expected if label in actual]
    return dict(ok=bool(hits), na=False, expected=expected, actual=actual, hit=hits,
                evidence='locators of %d body bullet(s) resolve to %s' % (len(body_bullets), actual))
def _check_numbers(page, page_text):
    required = page['numbers_required']
    covered = [item['token'] for item in required if item['token'].lower() in page_text.lower()]
    if not required:
        evidence = 'no numeric token inside this role section contract of this source'
    else:
        evidence = 'page text carries %d/%d expected numeric token(s), need %d' % (
            len(covered), len(required), page['min_numbers'])
    return dict(ok=(len(covered) >= page['min_numbers']), na=(not required),
                expected=[item['token'] for item in required], actual=covered,
                missing=[item['token'] for item in required if item['token'].lower() not in page_text.lower()],
                need=page['min_numbers'], evidence=evidence)
def _check_citations(page, page_text):
    required = page['citations_required']
    if not required:
        return dict(ok=True, na=True, expected=[], actual=[],
                    evidence='no figure/table number inside this role section contract')
    found = []
    for citation in required:
        pattern = FIGURE_RE if citation['kind'] == 'figure' else TABLE_RE
        if any(int(match.group(1) or match.group(2)) == citation['n']
               for match in pattern.finditer(page_text)):
            found.append('%s %d' % (citation['kind'], citation['n']))
    return dict(ok=len(found) == len(required), na=False,
                expected=['%s %d' % (item['kind'], item['n']) for item in required],
                actual=found, evidence='page text cites %s' % (found or 'no figure/table number'))
def _check_bullets(page, bullet_count):
    low, high = page['bullet_range']
    return dict(ok=(low <= bullet_count <= high), expected=[low, high], actual=bullet_count,
                evidence='%d bullet/subtitle line(s) recorded, allowed %d-%d'
                         % (bullet_count, low, high))
def _check_evidence(body_bullets):
    quoted = [bullet for bullet in body_bullets if bullet.get('quote')]
    if not quoted:
        return dict(ok=True, na=True, expected='verbatim when a quote exists', actual=[],
                    evidence='page carries no source quote (front matter only)')
    unverified = [shorten(bullet['text'], 50) for bullet in quoted if not bullet.get('verified')]
    return dict(ok=not unverified, na=False, expected='all quotes verbatim',
                actual='%d/%d' % (len(quoted) - len(unverified), len(quoted)),
                evidence=('unverified: %s' % '; '.join(unverified[:3])) if unverified else
                         'every quote occurs as a substring of the extracted source')
def _check_overflow(utilization):
    return dict(ok=(utilization <= 1.0), expected='<=1.0', actual=utilization,
                evidence='line-fit model utilization %.2f (rendered check in export_check.json)'
                         % utilization)
def diff_golden(golden, content_map, fits, compliance, counts=None):
    util_by_page = {item['i']: item['util'] for item in fits}
    rows, gaps = [], []
    for standard, delivered in zip(golden['pages'], content_map):
        page_text = ' '.join([bullet.get('text') or '' for bullet in delivered['bullets']]
                             + [bullet.get('quote') or '' for bullet in delivered['bullets']])
        body = [bullet for bullet in delivered['bullets'] if bullet.get('kind') != 'front_matter']
        checks = {
            'role': _check_role(standard['role'], delivered['role']),
            'sections': _check_sections(golden, standard, body),
            'numbers': _check_numbers(standard, page_text),
            'citations': _check_citations(standard, page_text),
            'bullets': _check_bullets(standard, len(delivered['bullets'])),
            'evidence': _check_evidence(body),
            'overflow': _check_overflow(util_by_page.get(standard['page'], 0.0)),
        }
        hard = [name for name, check in checks.items() if not check['ok'] and name in HARD_CHECKS]
        soft = [name for name, check in checks.items() if not check['ok'] and name not in HARD_CHECKS]
        verdict = 'FAIL' if hard else ('PARTIAL' if soft else 'PASS')
        for name in hard + soft:
            gaps.append(dict(page=standard['page'], role=standard['role'], check=name,
                             severity='hard' if name in hard else 'soft',
                             detail=checks[name].get('evidence')))
        rows.append(dict(page=standard['page'], role=standard['role'], title=delivered['title'],
                         narrative_job=standard['narrative_job'], verdict=verdict, checks=checks,
                         hard_fail=hard, soft_fail=soft))
    delivered_text = ' '.join([bullet.get('text') or '' for page in content_map for bullet in page['bullets']]
                              + [bullet.get('quote') or '' for page in content_map
                                 for bullet in page['bullets']]).lower()
    headline = golden['deck']['headline_numbers']
    headline_found = [item['token'] for item in headline if item['token'].lower() in delivered_text]
    wanted = ([('figure', number) for number in golden['deck']['figure_numbers']]
              + [('table', number) for number in golden['deck']['table_numbers']])
    cited = ['%s %d' % (kind, number) for kind, number in wanted
             if any(int(match.group(1) or match.group(2)) == number
                    for match in (FIGURE_RE if kind == 'figure' else TABLE_RE).finditer(delivered_text))]
    summary = dict(pages=len(rows),
                   passed=sum(1 for row in rows if row['verdict'] == 'PASS'),
                   partial=sum(1 for row in rows if row['verdict'] == 'PARTIAL'),
                   failed=sum(1 for row in rows if row['verdict'] == 'FAIL'),
                   hard_gaps=sum(1 for gap in gaps if gap['severity'] == 'hard'),
                   soft_gaps=sum(1 for gap in gaps if gap['severity'] == 'soft'),
                   headline=dict(covered=len(headline_found), required=len(headline),
                                 tokens=[item['token'] for item in headline],
                                 missing=[item['token'] for item in headline
                                          if item['token'].lower() not in delivered_text],
                                 ok=len(headline_found) == len(headline) if headline else True),
                   citations=dict(covered=cited,
                                  required=['%s %d' % (kind, number) for kind, number in wanted],
                                  missing=['%s %d' % (kind, number) for kind, number in wanted
                                           if '%s %d' % (kind, number) not in cited],
                                  ok=len(cited) == len(wanted)))
    export = dict(overall_pass=(compliance.get('export') or {}).get('matches_slides'),
                  method=(compliance.get('export') or {}).get('method'))
    count_rows = []
    if counts:
        labels = [('golden standard', 'golden', 'page_golden.json pages[]'),
                  ('page plan', 'plan', 'plan_v0.json pages[]'),
                  ('pptx slide parts', 'pptx_slides', 'zip: ppt/slides/slideN.xml'),
                  ('pptx notes parts', 'pptx_notes', 'zip: ppt/notesSlides/notesSlideN.xml'),
                  ('content_map rows', 'content_map', 'result.json.content_map[]'),
                  ('PDF pages', 'pdf_pages', 'PDF page objects')]
        for label, key, source in labels:
            value = counts.get(key)
            count_rows.append(dict(artefact=label, key=key, count=value, expected=summary['pages'],
                                   source=source,
                                   ok=(value == summary['pages']) if value is not None else None))
        requested = counts.get('requested')
        matched = [row['count'] for row in count_rows if row['count'] is not None]
        consistent = bool(matched) and all(value == summary['pages'] for value in matched)
        shortfall = (requested is not None and requested != summary['pages'])
        page_count = dict(rows=count_rows, consistent=consistent, verdict='PASS' if consistent else 'FAIL',
                          requested=requested, delivered=summary['pages'], shortfall=shortfall,
                          shortfall_note=('requested %s, delivered %d: the source sentence pool could not '
                                          'fill the request; recorded in uncertainty'
                                          % (requested, summary['pages'])) if shortfall else '')
    else:
        page_count = dict(rows=[], consistent=None, verdict='not_checked', requested=None,
                          delivered=summary['pages'], shortfall=False, shortfall_note='')
    return dict(rules_version=RULES_VERSION, case_id=golden.get('case_id'), pages=rows, gaps=gaps,
                summary=summary, export=export, page_count=page_count,
                overall=('PASS' if not gaps else ('FAIL' if summary['hard_gaps'] else 'PARTIAL')))
def render_diff_md(diff, golden):
    summary, headline = diff['summary'], diff['summary']['headline']
    lines = ['# Delivered deck vs page-level golden standard', '']
    lines.append('- case `%s` · source `%s` · rule set `%s`' % (
        diff.get('case_id'), golden['source']['label'], RULES_VERSION))
    lines.append('- source fingerprint (sha256 of the sentence pool): `%s…`'
                 % golden['source']['fingerprint'][:16])
    lines.append('- the standard in `page_golden.json` was registered before the deck existed; this diff '
                 'reads `result.json.content_map`, so pages can fail.')
    lines.append('- generated %s · %d page(s) (requested %s) · %d sentence(s) in the source' % (
        golden.get('generated_at'), summary['pages'], golden['deck'].get('requested'),
        golden['source']['sentences']))
    lines += ['', '## Summary', '', '| metric | value |', '|---|---|']
    lines.append('| pages PASS / PARTIAL / FAIL | %d / %d / %d |' % (
        summary['passed'], summary['partial'], summary['failed']))
    lines.append('| gaps (hard / soft) | %d / %d |' % (summary['hard_gaps'], summary['soft_gaps']))
    lines.append('| headline numbers present | %d/%d%s |' % (
        headline['covered'], headline['required'],
        '' if headline['ok'] else ' → missing ' + ', '.join(headline['missing'])))
    citations = summary['citations']
    lines.append('| figure/table numbers present | %d/%d%s |' % (
        len(citations['covered']), len(citations['required']),
        '' if citations['ok'] else ' → missing ' + ', '.join(citations['missing'])))
    lines.append('| PDF rendered | %s |' % (
        'yes (%s)' % diff['export']['method'] if diff['export']['overall_pass'] else 'no / degraded'))
    lines.append('| overall | **%s** |' % diff['overall'])
    page_count = diff.get('page_count') or {}
    lines += ['', '## Page-count consistency', '']
    if page_count.get('rows'):
        lines += ['| artefact | count | expected pages | consistent | source |', '|---|---|---|---|---|']
        for row in page_count['rows']:
            count = 'not read' if row['count'] is None else row['count']
            verdict = 'n/a' if row['ok'] is None else ('PASS' if row['ok'] else 'FAIL')
            lines.append('| %s | %s | %s | %s | %s |' % (
                row['artefact'], count, row['expected'], verdict, row['source']))
        lines.append('')
        lines.append('- verdict: **%s** (golden standard, page plan, pptx slides/notes, content_map and '
                     'PDF must all agree)' % page_count.get('verdict'))
        if page_count.get('shortfall_note'):
            lines.append('- note: %s' % page_count['shortfall_note'])
    else:
        lines.append('Not checked: no page-count counts were passed to this renderer.')
    lines += ['', '| # | role | title | verdict | hard gaps | soft gaps |', '|---|---|---|---|---|---|']
    for row in diff['pages']:
        lines.append('| %d | %s | %s | %s | %s | %s |' % (
            row['page'], row['role'], shorten(row['title'], 46), row['verdict'],
            ', '.join(row['hard_fail']) or '-', ', '.join(row['soft_fail']) or '-'))
    lines += ['', '## Page detail', '']
    for row in diff['pages']:
        lines += ['### p%d · %s · %s — %s' % (row['page'], row['role'],
                                              shorten(row['title'], 70), row['verdict']), '']
        lines += ['| check | expected | actual | result | evidence |', '|---|---|---|---|---|']
        for name in ALL_CHECKS:
            check = row['checks'][name]
            status = 'n/a' if check.get('na') else ('pass' if check['ok'] else 'fail')
            expected = check['expected']
            actual = check['actual']
            expected = ', '.join(str(item) for item in expected) if isinstance(expected, list) else str(expected)
            actual = ', '.join(str(item) for item in actual) if isinstance(actual, list) else str(actual)
            lines.append('| %s | %s | %s | %s | %s |' % (
                name, shorten(expected, 70), shorten(actual, 70), status, shorten(check['evidence'], 110)))
        standard = golden['pages'][row['page'] - 1] if row['page'] - 1 < len(golden['pages']) else {}
        frozen = standard.get('evidence') or []
        lines.append('')
        lines.append('Golden evidence frozen before the build (locator + verbatim quote):')
        for item in frozen[:5]:
            tag = item.get('kind') or 'quote'
            if item.get('token'):
                tag += ' ' + item['token']
            elif item.get('n'):
                tag += ' %s' % item['n']
            lines.append('- `%s` · %s · "%s"' % (item.get('locator') or 'no locator', tag,
                                                shorten(item.get('quote'), 130)))
        if not frozen:
            lines.append('- none on this page: it carries front matter only, so there is no source '
                         'quote to freeze (no quote is invented)')
        lines.append('')
    lines += ['## Gap index', '']
    if not diff['gaps']:
        lines.append('No gap: every page meets its pre-registered expectation.')
    else:
        lines += ['| # | page | role | check | severity | detail |', '|---|---|---|---|---|---|']
        for number, gap in enumerate(diff['gaps'], 1):
            lines.append('| %d | p%d | %s | %s | %s | %s |' % (
                number, gap['page'], gap['role'], gap['check'], gap['severity'],
                shorten(gap['detail'], 120)))
    lines += ['', '## Reproduce', '', '```',
              'python3 scripts/main.py --input <case dir> --output <out dir>',
              'python3 scripts/main.py --input <case dir> --output <out dir> --reuse-plan <out>/plan_v0.json',
              '```', 'Only the timestamps vary between runs; the standard and this diff are deterministic '
              'in the source text plus the workorder.']
    return '\n'.join(lines) + '\n'
def version_history(records, case_id, lineage, context=None):
    lines = ['# Version history — %s' % case_id, '']
    lines.append('Two layers: the **package lineage** (version changes and how to roll back) and the '
                 '**run record** (what this execution did, in order). The run record is appended at '
                 'runtime; the lineage is static.')
    lines += ['', '## Package lineage', '', '| version | date | change | why | rollback |', '|---|---|---|---|---|']
    for note in lineage:
        lines.append('| %s | %s | %s | %s | %s |' % (
            note['version'], note['date'], note['change'], note['why'], note['rollback']))
    lines += ['', '## Run record', '', '| step | time | version | artifact | detail |',
              '|---|---|---|---|---|']
    for record in records:
        lines.append('| %s | %s | %s | %s | %s |' % (
            record.get('step'), record.get('time'), record.get('version'),
            record.get('artifact') or '-', shorten(record.get('detail'), 150)))
    context = context or {}
    if context:
        lines += ['', '## Run environment', '', '| item | value |', '|---|---|']
        for label, key in (('run id', 'run_id'), ('command', 'command'), ('python', 'python'),
                           ('platform', 'platform'), ('working directory', 'cwd'),
                           ('tool chain', 'tools'), ('started (UTC)', 'started'),
                           ('elapsed seconds', 'elapsed'), ('exit code', 'exit_code'),
                           ('status', 'status')):
            value = context.get(key)
            if value is not None and value != '':
                lines.append('| %s | %s |' % (label, shorten(str(value), 200)))
        lines += ['', '## Delivered artefacts', '',
                  '| artefact | bytes | written by |', '|---|---:|---|']
        for item in context.get('assets') or []:
            lines.append('| %s | %s | %s |' % (item.get('name'), item.get('bytes', '-'),
                                               item.get('stage', 'run')))
    lines += ['', '### Stage notes', '']
    for record in records:
        if record.get('note'):
            lines.append('- **%s** · %s: %s' % (record.get('version'), record.get('step'), record['note']))
    lines += ['', '## Rollback targets', '', '| target | command | effect |', '|---|---|---|']
    lines.append('| v0 page skeleton | `--reuse-plan <out>/plan_v0.json` | rebuild from the recorded plan '
                 '(roles, titles, quote texts); the plan hash is printed in `run.log` |')
    lines.append('| behaviour without the checks | `--no-golden` | core fields only; skip golden/diff/export/'
                 'template inspection (format compliance and the closing self-check still run) |')
    lines.append('| legacy section labels | `--legacy-sections` | restore one label per page |')
    lines.append('| pre-patch build (v1.0.0) | restore the pre-patch `scripts/` tree from the release archive '
                 '(kept as `slides-02_orig`); the new artefacts are additive |')
    lines += ['', 'No rollback deletes an artifact: the flags only change what the current run writes, so an '
              'older `presentation.pptx` survives until a run overwrites it.']
    return '\n'.join(lines) + '\n'
