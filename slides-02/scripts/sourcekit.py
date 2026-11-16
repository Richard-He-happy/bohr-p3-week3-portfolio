
import json
import os
import re
import time
import zlib
from pathlib import Path
ALLOWED_STATUS = ('ok', 'partial', 'insufficient_evidence', 'input_error')
ALIASES = {
    'case_id': ('case_id', 'id'),
    'status': ('status', 'state'),
    'editable_source': ('editable_source', 'deck', 'presentation', 'pptx'),
    'export_artifact': ('export_artifact', 'export', 'pdf', 'render'),
    'content_map': ('content_map', 'slide_map', 'page_map', 'evidence_map'),
    'compliance_checks': ('compliance_checks', 'compliance', 'checks'),
    'exceptions': ('exceptions', 'exception', 'issues'),
    'page_golden': ('page_golden', 'pagegolden', 'golden', 'goldstandard'),
    'page_diff': ('page_diff', 'pagediff', 'diff', 'pagediffcheck'),
    'version_history': ('version_history', 'versionhistory', 'versions', 'changelog'),
    'export_check': ('export_check', 'exportcheck', 'rendercheck', 'exportrendercheck'),
    'template_check': ('template_check', 'templatecheck', 'templateinheritancecheck'),
    'format_compliance': ('format_compliance', 'formatcompliance', 'formatcheck',
                          'formatcompliancecheck', 'formatspec'),
    'self_check': ('self_check', 'selfcheck', 'finalcheck', 'selfcheckreport'),
    'run_log': ('run_log', 'runlog', 'executionlog', 'log'),
}
NORMALISED_ALIASES = {
    field: [re.sub(r'[^a-z]', '', name) for name in (field,) + spellings]
    for field, spellings in ALIASES.items()
}
def stamp():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
def dump_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
def shorten(value, limit):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '\u2026'
def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig', errors='replace'))
    except Exception:
        return None
def find_case(indir):
    candidates = [indir / 'case.json'] + sorted(indir.glob('case*.json'))
    for path in candidates:
        doc = read_json(path)
        if isinstance(doc, dict):
            return doc
        if isinstance(doc, list) and doc and isinstance(doc[0], dict):
            return doc[0]
    return {}
def dig(obj, wanted, depth=0):
    if depth > 6 or obj is None:
        return None
    if isinstance(obj, dict):
        flat = {re.sub(r'[^a-z0-9]', '', str(k).lower()): v for k, v in obj.items()}
        for needle in wanted:
            if needle in flat and not isinstance(flat[needle], (dict, list)):
                return flat[needle]
            for flat_key, value in flat.items():
                if needle in flat_key and not isinstance(value, (dict, list)):
                    return value
        for value in obj.values():
            found = dig(value, wanted, depth + 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj[:30]:
            found = dig(value, wanted, depth + 1)
            if found is not None:
                return found
    return None
def as_int(*values):
    for value in values:
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int):
            return value
        match = re.search(r'\b(\d{1,3})\b', str(value))
        if match:
            return int(match.group(1))
def scan_files(indir):
    buckets = {kind: [] for kind in ('pdf', 'pptx', 'json', 'doc', 'image')}
    by_extension = {'.pptx': 'pptx', '.docx': 'doc', '.json': 'json', '.md': 'doc',
                    '.txt': 'doc', '.png': 'image', '.jpg': 'image', '.svg': 'image'}
    paths = sorted(indir.rglob('*')) if indir.exists() else []
    for path in paths:
        try:
            head = path.open('rb').read(4) if path.is_file() and path.stat().st_size else b''
        except Exception:
            continue
        if not head:
            continue
        kind = by_extension.get(path.suffix.lower())
        if kind is None:
            kind = 'pdf' if head[:4] == b'%PDF' else 'doc'
        buckets[kind].append(path)
    return buckets
def first_named(files, markers):
    return next((path for path in files if any(m in path.name.lower() for m in markers)), None)
def read_workorder(jsons, indir):
    for name in ('slide-workorder.json', 'workorder.json', 'artifacts/slide-workorder.json'):
        doc = read_json(indir / name)
        if isinstance(doc, dict):
            return doc
    for path in jsons:
        doc = read_json(path)
        if isinstance(doc, dict) and dig(doc, ('slidecount', 'totalslides', 'slidespec')):
            return doc
    return {}
def prepare_outdir(arg, log=None):
    for candidate in ([arg] if arg else []) + [os.environ.get('OUTPUT_DIR'), '/app/output', 'output']:
        if not candidate:
            continue
        try:
            path = Path(candidate)
            path.mkdir(parents=True, exist_ok=True)
            probe = path / '.write_probe'
            probe.write_text('1')
            probe.unlink()
            return path
        except Exception:
            if log:
                log('output dir not writable: %s' % candidate)
    return Path.cwd()
def prepare_indir(arg):
    for candidate in ([arg] if arg else []) + ['/input', '/app/input', str(Path.cwd() / 'input')]:
        if Path(candidate).is_dir():
            return Path(candidate)
    return Path(arg or 'input')
def contract_keys(contract):
    if isinstance(contract, dict):
        return [str(key) for key in contract]
    if isinstance(contract, list):
        return [key for key in contract if isinstance(key, str)]
    return []
def echo_contract(result, keys):
    unresolved = []
    for key in keys:
        probe = re.sub(r'[^a-z]', '', str(key).lower())
        field = next((f for f, names in NORMALISED_ALIASES.items() if probe in names), None)
        if field is None:
            field = next((f for f, names in NORMALISED_ALIASES.items()
                          if any(len(name) > 4 and name in probe for name in names)), None)
        if field and result.get(field) is not None:
            result[key] = result[field]
        else:
            result[key] = [] if re.search(r'(map|list|slides|checks|exceptions)', probe) else None
            unresolved.append(key)
    return unresolved
def tidy(text):
    text = text.replace('\u00ad', '').replace('\ufb01', 'fi').replace('\ufb02', 'fl')
    text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)
    text = re.sub(r'[ \t\u00a0]+', ' ', text)
    return re.sub(r'\n{2,}', '\n', text).strip()
def pdf_pages(path, log=None):
    tool = None
    try:
        import shutil
        tool = shutil.which('pdftotext')
    except Exception:
        tool = None
    if tool:
        try:
            import subprocess
            proc = subprocess.run([tool, '-layout', '-enc', 'UTF-8', str(path), '-'],
                                  capture_output=True, timeout=120)
            if proc.returncode == 0 and proc.stdout.strip():
                pages = [tidy(chunk) for chunk in proc.stdout.decode('utf-8', 'replace').split('\f')]
                pages = [page for page in pages if len(page) > 20]
                if pages:
                    return pages, 'pdftotext -layout'
        except Exception as err:
            if log:
                log('pdftotext failed: %s' % err)
    try:
        pages = [page for page in _builtin_pdf(path.read_bytes()) if len(page) > 20]
        return pages, 'builtin-pdf-parser'
    except Exception as err:
        if log:
            log('builtin pdf parser failed: %s' % err)
        return [], 'none'
def _pdf_objects(data):
    return {int(match.group(1)): match.group(2)
            for match in re.finditer(rb'(?<![0-9])(\d+)\s+0\s+obj(.*?)endobj', data, re.S)}
def _builtin_pdf(data):
    objects = _pdf_objects(data)
    page_numbers = sorted(number for number, body in objects.items()
                          if re.search(rb'/Type\s*/Page(?![s\w])', body))
    texts = []
    for number in page_numbers:
        chunks = []
        for ref in re.findall(rb'/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)', objects[number]):
            for stream_number in re.findall(rb'(\d+)\s+\d+\s+R', ref):
                stream_body = objects.get(int(stream_number), b'')
                match = re.search(rb'stream\r?\n(.*?)endstream', stream_body, re.S)
                if not match:
                    continue
                raw = match.group(1)
                if b'FlateDecode' in stream_body:
                    try:
                        raw = zlib.decompressobj().decompress(raw)
                    except Exception:
                        continue
                chunks.append(raw)
        texts.append(_content_stream(b'\n'.join(chunks)))
    return texts
def _pdf_token_text(token):
    if token[:1] == b'<':
        digits = re.sub(rb'[^0-9A-Fa-f]', b'', token)
        digits += b'0' * (len(digits) % 2)
        try:
            raw = bytes.fromhex(digits.decode('ascii'))
        except Exception:
            return ''
        if raw[:2] == b'\xfe\xff':
            return raw.decode('utf-16-be', 'replace')
        return raw.decode('latin-1')
    body = token[1:-1]
    escapes = {b'n': b'\n', b'r': b'\r', b't': b'\t', b'b': b'\b', b'f': b'\f',
               b'(': b'(', b')': b')', b'\\': b'\\'}
    body = re.sub(rb'\\([nrtbf()\\])', lambda m: escapes[m.group(1)], body)
    body = re.sub(rb'\\([0-7]{1,3})', lambda m: bytes([int(m.group(1), 8) & 255]), body)
    try:
        return body.decode('utf-8')
    except Exception:
        return body.decode('latin-1')
def _content_stream(blob):
    if not blob:
        return ''
    pieces, buffer = [], []
    pattern = rb'\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]*>|TJ|Tj|T\*|ET|BT'
    for match in re.finditer(pattern, blob):
        token = match.group(0)
        if token in (b'Tj', b'TJ'):
            pieces.append(''.join(buffer))
            buffer = []
        elif token in (b'T*', b'ET', b'BT'):
            pieces.append('\n')
            buffer = []
        else:
            buffer.append(_pdf_token_text(token))
    pieces.append(''.join(buffer))
    return tidy(''.join(pieces))
def pdf_images(path, limit=3):
    try:
        data = path.read_bytes()
    except Exception:
        return []
    found = []
    for match in re.finditer(rb'/Subtype\s*/Image(.{0,500}?)stream\r?\n', data, re.S):
        if b'DCTDecode' not in match.group(1):
            continue
        end = data.find(b'endstream', match.end())
        blob = data[match.end():end].rstrip(b'\r\n') if end > 0 else b''
        if blob[:2] == b'\xff\xd8' and len(blob) > 25000:
            found.append(blob)
    found.sort(key=len, reverse=True)
    return found[:limit]
def jpeg_dims(blob):
    index = 2
    while index < len(blob) - 9:
        if blob[index] != 0xFF:
            index += 1
            continue
        if blob[index + 1] in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(blob[index + 5:index + 7], 'big')
            width = int.from_bytes(blob[index + 7:index + 9], 'big')
            return width, height
        index += 2 + int.from_bytes(blob[index + 2:index + 4], 'big')
    return 0, 0
SECTION_PATTERNS = [
    ('abstract', r'^abstract\b'),
    ('intro', r'^(\d+\.?\s*)?(introduction|background)\b'),
    ('related', r'^(\d+\.?\s*)?(related work|literature review)\b'),
    ('methods', r'^(\d+\.?\s*)?(methods?|materials and methods|experimental|methodology|approach|data)\b'),
    ('results', r'^(\d+\.?\s*)?(results?|findings)\b'),
    ('discussion', r'^(\d+\.?\s*)?discussion\b'),
    ('conclusion', r'^(\d+\.?\s*)?(conclusions?|summary)\b'),
    ('limits', r'^(\d+\.?\s*)?(limitations?|future (work|directions?))\b'),
]
HAN_HEADINGS = [
    ('limits', ('局限', '局限性与展望', '不足与展望')),
    ('conclusion', ('结论', '总结', '结束语')),
    ('discussion', ('讨论', '结果与讨论', '解读')),
    ('related', ('相关工作', '文献综述')),
    ('results', ('结果', '研究结果', '主要结果')),
    ('methods', ('方法', '材料与方法', '研究方法', '实验设计')),
    ('intro', ('引言', '前言', '背景', '研究背景')),
    ('abstract', ('摘要', '中文摘要')),
]
HAN = re.compile(r'[\u4e00-\u9fff]')
def is_cjk(text):
    return bool(text) and len(HAN.findall(text)) > max(20, 0.04 * len(text))
def heading_of(line):
    raw = line.strip()
    cleaned = raw.lower().lstrip('#').strip().rstrip('.:').strip()
    han = len(HAN.findall(cleaned))
    minimum = 2 if han > 0.3 * max(len(cleaned), 1) else 3
    if not (minimum <= len(cleaned) <= 45) or len(cleaned.split()) > 6:
        return None
    if raw.endswith(('.', '。', '!', '?', ';', '；', '！', '？')) and len(cleaned.split()) > 3:
        return None
    for name, pattern in SECTION_PATTERNS:
        if re.match(pattern, cleaned):
            return name
    without_number = re.sub(r'^[\d.\s、一二三四五六七八九十]+', '', cleaned)
    for name, prefixes in HAN_HEADINGS:
        if without_number.startswith(prefixes):
            return name
    return None
def sentences(pages, legacy=False):
    found = []
    section = 'body'
    first_line = None
    for page_number, page in enumerate(pages, 1):
        lines = [line.strip() for line in page.split('\n') if line.strip()]
        if first_line is None and lines:
            first_line = lines[0]
        first_heading = next((index for index, line in enumerate(lines) if heading_of(line)), None)
        if legacy:
            for line in lines[:500]:
                section = heading_of(line) or section
        for index, line in enumerate(lines):
            if first_line and (line == first_line or (len(first_line) > 20 and line.startswith(first_line[:30]))):
                continue
            if page_number == 1 and first_heading not in (None, 0) and index < first_heading:
                continue
            label = heading_of(line)
            if label:
                if not legacy:
                    section = label
                continue
            if line.startswith('#'):
                continue
            han_ratio = len(HAN.findall(line)) > 0.3 * max(len(line), 1)
            minimum = 18 if han_ratio else 45
            if len(line) < minimum - 5:
                continue
            for piece in re.split(r'(?<=[.!?;])\s+|(?<=[。！？；])', line):
                piece = piece.strip().lstrip('-•\u2022 ')
                if len(piece) >= minimum and re.search(r'[A-Za-z\u4e00-\u9fff]', piece):
                    found.append({'text': piece, 'sec': section, 'page': page_number})
    return found
def sentence_score(record):
    text = record['text']
    value = 0.0
    if re.search(r'\d', text):
        value += 2.0
    if re.search(r'%|p\s*[<=>]\s*0?\.\d|\bCI\b|±|increase|decrease|higher|lower|reduc|improv',
                 text, re.I):
        value += 1.4
    if re.search(r'\b(fig(?:ure)?\.?\s*\d|table\s*\d)\b|图\s*\d|表\s*\d', text, re.I):
        value += 1.2
    if record['sec'] in ('results', 'abstract', 'conclusion'):
        value += 1.0
    if re.search(r'\b(we|our|here|this (study|paper|work))\b|本文|本研究', text, re.I):
        value += 0.5
    if re.search(r'\b(however|but|although|limitation|only|warrant|caution)\b|然而|局限', text, re.I):
        value += 0.4
    return value - min(len(text) / 400.0, 1.2)
def choose(pool, used, count, prefer=(), keywords=None, strict=False, must=None, anchor=None, ban=()):
    ranked = []
    for index, record in enumerate(pool):
        if index in used or record['sec'] in ban:
            continue
        value = sentence_score(record) + (1.5 if record['sec'] in prefer else 0)
        if keywords and re.search(keywords, record['text'], re.I):
            value += 1.2
        ranked.append((value, index, record))
    if strict and prefer:
        in_house = [item for item in ranked if item[2]['sec'] in prefer]
        if len(in_house) >= count:
            ranked = in_house
    ranked.sort(key=lambda item: -item[0])
    selected = ranked[:count]
    if must and selected and not any(re.search(must, item[2]['text'], re.I) for item in selected):
        replacement = next((item for item in ranked[count:] if re.search(must, item[2]['text'], re.I)), None)
        if replacement:
            selected = selected[:-1] + [replacement]
    if anchor and selected and not any(item[2]['sec'] == anchor for item in selected):
        replacement = next((item for item in ranked[count:] if item[2]['sec'] == anchor), None)
        if replacement:
            selected = selected[:-1] + [replacement]
    ordered = sorted(selected, key=lambda item: item[1])
    used.update(item[1] for item in ordered)
    return [item[2] for item in ordered]
def display_line(text, max_chars=118):
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    for separator in ('; ', ', ', ' '):
        position = cut.rfind(separator)
        if position >= max_chars * 0.55:
            return cut[:position].rstrip(' ,;，；') + ' \u2026'
    return cut.rstrip() + ' \u2026'
ROLE_TITLES = {
    'title': ('', ''),
    'outline': ('Outline', '结构'),
    'background': ('Background', '研究背景'),
    'question': ('Research question', '研究问题'),
    'methods': ('Methods & data', '方法与数据'),
    'results': ('Results', '结果'),
    'discussion': ('Interpretation', '解读'),
    'limitations': ('Limitations', '局限与边界'),
    'conclusion': ('Conclusions', '结论'),
    'thanks': ('Thank you', '致谢'),
}
PAGE_RULES = {
    'background': (3, ('abstract', 'intro'), r'gap|need|challenge|however|remains|未'),
    'question': (2, ('abstract', 'intro'), r'\bwe (aim|ask|investigate|test)|objective|here we|本文'),
    'methods': (3, ('methods', 'related'), None),
    'results': (3, ('results', 'abstract'), r'\d'),
    'discussion': (3, ('discussion', 'results'), r'suggest|indicat|imply|consistent|表明'),
    'limitations': (3, ('limits', 'discussion'), r'limitation|future|further|only|局限'),
    'conclusion': (3, ('conclusion', 'abstract'), r'conclu|overall|summary|综上'),
}
NOTE_TEMPLATES = {
    'zh': '本页角色：{t}。要点逐字取自 {l}。讲法：先给出结论「{f}」，再按页序展开证据，末尾过渡到「{n}」。'
          '本段只是讲稿提示，不是论文原文。',
    'en': 'Slide role: {t}. Bullets are verbatim from {l}. Start with "{f}", walk the evidence in page order, '
          'then bridge to "{n}". This is a speaking prompt, not paper text.',
}
def role_sequence(count):
    sequence = ['title'] + (['outline'] if count >= 8 else []) + ['background', 'question', 'methods']
    sequence += ['results'] * max(1, count - len(sequence) - 4) + ['discussion', 'limitations',
                                                                   'conclusion', 'thanks']
    for drop in ('limitations', 'outline', 'question', 'discussion', 'background'):
        if len(sequence) > count and drop in sequence:
            sequence.remove(drop)
    while len(sequence) > count:
        sequence.pop(len(sequence) - 3)
    while len(sequence) < count:
        sequence.insert(max(1, sequence.index('discussion')), 'results')
    return sequence[:count]
def clean_title(title):
    title = re.sub(r'^[#=\-*\s]+', '', str(title or ''))
    title = re.sub(r'\s*#+\s*$', '', title)
    return re.sub(r'\s+', ' ', title).strip()
def make_pages(pool, meta, count, lang, exceptions):
    language_index = 1 if lang == 'zh' else 0
    sequence = role_sequence(max(3, count))
    used = set()
    pages = []
    reserved = {sections[0] for role, (_n, sections, _kw) in PAGE_RULES.items()
                if role in sequence}
    for role in sequence:
        title = ROLE_TITLES[role][language_index]
        if role in ('title', 'outline', 'thanks'):
            if role == 'title':
                bullets = [(line, 0) for line in meta['subtitle']]
            elif role == 'outline':
                bullets = [(ROLE_TITLES[r][language_index], 0) for r in sequence
                           if r not in ('title', 'outline', 'thanks')]
            else:
                bullets = [(meta['credit'], 0)]
            pages.append({'role': role, 'title': meta['title'] if role == 'title' else title,
                          'src': [], 'bullets': bullets, 'frame': True})
            continue
        want, sections, keywords = PAGE_RULES[role]
        must = r'\b(fig(?:ure)?|table)s?\.?\s*\d|图\s*\d|表\s*\d' if role == 'results' else None
        picked = choose(pool, used, want, sections, keywords, strict=True, must=must,
                        anchor=sections[0], ban=reserved - {sections[0]})
        if not picked:
            picked = choose(pool, used, 2)
        if not picked:
            exceptions.append({'code': 'POOL_EXHAUSTED', 'stage': 'plan',
                               'detail': 'no sentence left for %s' % role})
            continue
        if role == 'results':
            title = '%s %d' % (title, 1 + sum(1 for page in pages if page['role'] == 'results'))
        pages.append({'role': role, 'title': title, 'src': picked,
                      'bullets': [(display_line(record['text']), 0) for record in picked]})
    return pages
def add_notes(pages, meta, lang):
    language_index = 1 if lang == 'zh' else 0
    for index, page in enumerate(pages):
        if page['role'] in ('title', 'thanks', 'notice'):
            spinner = ('封面/致谢页：%s。来源：%s。' if language_index else
                       'Opening or closing slide: %s. Source: %s.')
            page['notes'] = spinner % (page['title'], meta['src_label'])
        else:
            page['notes'] = NOTE_TEMPLATES['zh' if language_index else 'en'].format(
                t=page['title'],
                l='、'.join(sorted({'p.%d' % record['page'] for record in page['src']})) or meta['src_label'],
                f=display_line(page['bullets'][0][0], 60) if page['bullets'] else '',
                n=pages[index + 1]['title'] if index + 1 < len(pages) else ('结束' if language_index else 'the end'))
    return pages
def replay_plan(path, pool, exceptions):
    try:
        recorded = json.loads(Path(path).read_text(encoding='utf-8-sig', errors='replace'))
    except Exception:
        recorded = None
    if not isinstance(recorded, dict) or not isinstance(recorded.get('pages'), list):
        exceptions.append({'code': 'PLAN_REUSE_INVALID', 'stage': 'plan',
                           'detail': '%s is not a page plan' % path})
        return None
    by_text = {record['text']: record for record in pool}
    pages, missing = [], 0
    for planned in recorded['pages']:
        quotes = planned.get('quotes') or []
        matched = [by_text[quote] for quote in quotes if quote in by_text]
        missing += sum(1 for quote in quotes if quote not in by_text)
        if not matched and planned.get('role') not in ('title', 'outline', 'thanks'):
            continue
        pages.append({'role': planned.get('role') or 'background',
                      'title': planned.get('title') or planned.get('role'),
                      'src': matched,
                      'bullets': [(display_line(record['text']), 0) for record in matched]})
    if missing:
        exceptions.append({'code': 'PLAN_REUSE_MISS', 'stage': 'plan',
                           'detail': '%d recorded quote(s) missing from the current source' % missing})
    return pages or None
def fill_frames(pages, meta, lang):
    language_index = 1 if lang == 'zh' else 0
    body_roles = [page['role'] for page in pages
                  if page['role'] not in ('title', 'outline', 'thanks', 'notice')]
    for page in pages:
        if page.get('bullets'):
            continue
        if page['role'] == 'title':
            page['bullets'] = [(line, 0) for line in meta['subtitle']]
        elif page['role'] == 'outline':
            page['bullets'] = [(ROLE_TITLES[role][language_index], 0) for role in body_roles]
        elif page['role'] == 'thanks':
            page['bullets'] = [(meta['credit'], 0)]
    return pages
def notice_pages(lang, missing):
    chinese = lang == 'zh'
    return [
        {'role': 'notice',
         'title': '输入不完整：没有可用正文' if chinese else 'Input incomplete - no usable source text',
         'src': [], 'frame': True,
         'bullets': [
             ('未能从输入目录的 PDF 文本层 / DOCX / TXT / MD 中读到足够正文。' if chinese else
              'No readable source text was found in the input directory (PDF text layer, DOCX, TXT, MD).', 0),
             ('已检查 case.json、material.json、artifacts/slide-workorder.json 以及全部附件。' if chinese else
              'Checked case.json, material.json, artifacts/slide-workorder.json and every attachment.', 0),
             ('请放入带文本层的论文后重跑；本次没有生成任何科学结论。' if chinese else
              'Re-run with a paper that has a text layer; no scientific claim was produced here.', 0)]},
        {'role': 'notice', 'title': '需要什么输入' if chinese else 'What this skill needs',
         'src': [], 'frame': True,
         'bullets': [('case.json（output_contract 原样回填）' if chinese else
                      'case.json carrying output_contract', 0),
                     ('可提取文字的论文 PDF / DOCX / TXT / MD' if chinese else
                      'a paper PDF / DOCX / TXT / MD with extractable text', 0),
                     ('可选：template.pptx 与 artifacts/slide-workorder.json' if chinese else
                      'optional: template.pptx and artifacts/slide-workorder.json', 0)]},
        {'role': 'notice', 'title': '本次状态' if chinese else 'Status of this run',
         'src': [], 'frame': True,
         'bullets': [('status = insufficient_evidence；缺口：%s' % '、'.join(missing[:4]) if chinese else
                      'status = insufficient_evidence; gaps: %s' % ', '.join(missing[:4]), 0)]},
    ]
def pick_layout(template, role):
    layouts = template.get('layouts') or []
    if not layouts:
        return None
    if role == 'notice':
        return layouts[-1][0]
    wanted = 'ctrTitle' if role == 'title' else 'title'
    for name, info in layouts:
        if wanted in info['types'] and (role == 'title' or
                                        any(kind in info['types'] for kind in ('obj', 'body', 'tx'))):
            return name
    return layouts[0][0]
