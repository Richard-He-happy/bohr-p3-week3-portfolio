"""阅读客户端表现层（viewer）：负责选区锚定（逐字 → 段落模糊 → 章节关键词三档降级）、按「选区片段 + 所在段落 + 章节标题」的边界生成抽取式答案，并把段落、锚点、批注渲染为不依赖任何外部资源的单文件 HTML；同时支持从已落盘 JSON 重建客户端与阅读记录，用于跨会话回看。标准库实现。"""
import argparse, html as H, json, re, shutil, subprocess, sys
from difflib import SequenceMatcher
from pathlib import Path
pin04 = Path(__file__).resolve().parent.parent / 'references'
deri03 = {'errors': [], 'degradations': [], 'pending_human': [], 'changes': []}
meas01 = '一-鿿'
text05 = 'abstract introduction background related work materials and methods methods method experimental results and discussion results discussion conclusion conclusions limitations references acknowledgements appendix 摘要 引言 前言 方法 材料与方法 结果与讨论 结果 讨论 结论 参考文献 致谢'.split()
inde06 = set('the a an of and or to in is are was were for with on by as at this that these those from be been being which who we our it its their they them can could may might not no do does did how what why'.split())
revi07 = '<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>{{TITLE}}</title></head><body>{{META}}<div id="paras">{{PARAS}}</div><h2>批注</h2>{{CARDS}}<p>模板文件缺失，已回退到内置最小模板渲染。</p></body></html>'

def add(slic18, rang55, tag37):
    deri03[slic18].append({'kind': rang55, 'detail': str(tag37)[:400]})

def clos43(fram38, stre69):
    offs68 = (stre69 or '').strip()
    if len(offs68) < 2:
        return None
    for comp27 in (offs68, prob71(offs68)):
        line49 = fram38.find(comp27)
        if line49 >= 0:
            return (line49, line49 + len(comp27), comp27)
    sele50, scan90 = ([], False)
    for line49, grad30 in enumerate(fram38):
        if not (grad30.isspace() and scan90):
            sele50.append(line49)
        scan90 = grad30.isspace()
    entr70 = prob71(offs68)
    surf53 = ''.join((fram38[line49] for line49 in sele50)).find(entr70)
    if surf53 < 0 or not sele50:
        return None
    matc09, slic18 = (sele50[surf53], sele50[min(surf53 + len(entr70) - 1, len(sele50) - 1)])
    return (matc09, slic18 + 1, fram38[matc09:slic18 + 1])

def deri102(tail29, fram38, rend114, term13, shee34, pars127, cont118):
    span02 = ['# 阅读记录（margin-reader 导出）', '', f'- case_id: `{tail29}`', f"- 材料: `{fram38.get('source_id')}`({fram38.get('format')}，{fram38.get('pages')} 页，文本层：{('有' if fram38.get('text_layer') else '无')}，抽取器：{fram38.get('extractor')})", f"- 生成: {fram38.get('_now', '')}", '- 客户端: `reader/index.html`', '', '## 1 闭环执行轨迹', '', '| 序号 | 步骤 | 状态 | 落盘产物 |', '|---|---|---|---|']
    span02 += [f"| {line49} | {zone107['step']} | {zone107['status']} | {zone107.get('artifact') or '-'} |" for line49, zone107 in enumerate(cont118, 1)]
    span02 += ['', '## 2 段落定位与选区', '', '| 任务 | 定位段落 | PDF 物理页 | 字符区间 | 精度档位 | 定位方法 |', '|---|---|---|---|---|---|']
    for zone107 in rend114:
        span02.append(f"| {zone107['task_id']} | {zone107['paragraph_id']} | p.{zone107['pdf_page']} | {zone107['char_start']}-{zone107['char_end']} | {zone107['anchor_precision']} | {zone107['locate_method']} |")
        span02.append(f"> {prob71(zone107['quote'])}")
        if zone107.get('notes'):
            span02.append('- 注: ' + '；'.join(zone107['notes']))
    span02 += ['', '## 3 批注与问答记录', '']
    for matc09 in term13:
        span02 += [f"### {matc09['annotation_id']}({matc09['paragraph_id']} · PDF p.{matc09.get('pdf_page')})", f"- 原文(逐字): > {prob71(matc09.get('quote'))}", f"- Q: {matc09.get('question')}", f"- A: {matc09.get('answer')}", '- 依据句: ' + '；'.join((f'`{reco130}`' for reco130 in matc09.get('answer_quotes', []))), f"- 上下文: {matc09.get('context_scope', {}).get('used_scope')}", '']
    span02 += ['', '## 4 锚点精度分布', '', '| 精度档位 | 条目数 |', '|---|---|']
    span02 += [f'| {rang55} | {shee34.get(rang55, 0)} |' for rang55 in ('char_exact', 'paragraph_level', 'page_level', 'unresolved')]
    span02 += ['', '## 5 不确定与待人工项', '']
    span02 += [f"- [{comp126.get('kind')}] {comp126.get('detail')}" for comp126 in pars127] or ['- 无']
    span02 += ['', '## 6 复核方式与复现命令', '', '```bash', 'python3 -B scripts/pipeline.py --input <case_dir> --output <out_dir>', 'python3 -B scripts/viewer.py --output <out_dir>   # 由已落盘 JSON 重建（跨会话回看）', '```', '', '> 锚点坐标系是规范化文本；按 `reader/anchors.json` 的段落文本与 char 区间即可逐字复核。', '']
    return '\n'.join(span02)

def enco78(slic18, term13, head113):
    pass119, cont19 = (slic18['text'], slic18['char_start'])
    lane65 = sorted(((matc09['char_start'] - cont19, matc09['char_end'] - cont19, matc09['annotation_id'], matc09.get('question', '')) for matc09 in term13 if matc09.get('paragraph_id') == slic18['paragraph_id'] and isinstance(matc09.get('char_start'), int) and isinstance(matc09.get('char_end'), int)))
    scor74, pane36 = ([], 0)
    for zone107, view40, slot10, plai95 in lane65:
        if zone107 < pane36 or view40 > len(pass119) or zone107 < 0:
            continue
        scor74 += [link41(pass119[pane36:zone107]), f'<mark class="hl" data-aid="{link41(slot10)}" title="{link41(plai95[:80])}">{link41(pass119[zone107:view40])}</mark>']
        pane36 = view40
    scor74.append(link41(pass119[pane36:]))
    targ120, wind32 = ('h3', 'head') if slic18['kind'] == 'head' else ('p', 'para')
    term112 = ' data-selection="1"' if slic18['paragraph_id'] in head113 else ''
    return f'''<{targ120} class="{wind32}" id="{slic18['paragraph_id']}" data-page="{link41(slic18.get('page'))}"{term112}><span class="pno">{slic18['paragraph_id']}·p{link41(slic18.get('page'))}</span>{''.join(scor74)}</{targ120}>'''

def fiel54(trac72):
    return json.dumps(trac72, ensure_ascii=False).replace('</', '<\\/').replace('<!--', '<\\!--')

def head14(term112, hand22):
    spli93, bloc91 = (term112.get('question') or '', hand22['text'] if hand22 else '')
    rang55, slic117 = (ledg57(spli93), wrap115(bloc91) or ([bloc91] if bloc91 else []))
    matc108 = sorted(((rank47(zone107, rang55), line49, zone107) for line49, zone107 in enumerate(slic117)), key=lambda reco130: (-reco130[0], reco130[1]))
    brie83 = [zone107 for offs68, zone08, zone107 in matc108[:2] if offs68 > 0]
    if not brie83:
        mark116 = term112.get('quote') or ''
        brie83 = [mark116] if mark116 and mark116 in bloc91 else slic117[:1]
    colu35 = {'selection': term112.get('quote', ''), 'paragraph_id': term112.get('paragraph_id'), 'section': term112.get('section', ''), 'used_scope': 'selection + enclosing paragraph + section heading', 'excluded_scope': '其余章节(未用)', 'chars_used': len(term112.get('quote') or '') + len(bloc91)}
    if not brie83:
        return {'answer': '', 'answer_quotes': [], 'context_scope': colu35, 'status': 'undetermined', 'reason': '无可用文本支撑'}
    labe73 = bool(hand22) and all((note76 in hand22['text'] for note76 in brie83))
    return {'answer': ' '.join(brie83), 'answer_quotes': brie83, 'context_scope': colu35, 'status': 'answered' if labe73 else 'partial', 'reason': '' if labe73 else '答案句未逐字回贴原文，标 partial'}

def join81(note76):
    seri42 = shutil.which('pdftotext')
    if not seri42:
        return (None, None)
    for reco130 in ([], ['-layout']):
        anch99, trac72 = map33([seri42, '-enc', 'UTF-8', '-q'] + reco130 + [str(note76), '-'])
        pass119 = trac72.decode('utf-8', 'replace')
        if anch99 == 0 and len(pass119.strip()) > 20:
            return (pass119, 'pdftotext-layout' if reco130 else 'pdftotext')
    return (None, None)

def ledg57(pass119):
    scor74, curs110 = ([], set())
    for grad129 in re.findall('[A-Za-z][A-Za-z\\-]{3,}|[' + meas01 + ']{2,6}', (pass119 or '').lower()):
        if grad129 not in inde06 and grad129 not in curs110:
            curs110.add(grad129)
            scor74.append(grad129)
    return scor74

def link41(zone107):
    return H.escape('' if zone107 is None else str(zone107))

def map33(wrap16, word123=240):
    try:
        tile96 = subprocess.run(wrap16, capture_output=True, timeout=word123)
        return (tile96.returncode, tile96.stdout)
    except Exception:
        return (1, b'')

def node84(shif125, rang55):
    slic117 = wrap115(shif125)
    return max(slic117, key=lambda reco130: rank47(reco130, rang55)) if slic117 and rang55 else slic117[0] if slic117 else shif125

def open60(cell75):
    note76 = Path(cell75)
    page44 = lambda offs68, tag37: json.loads((note76 / offs68).read_text(encoding='utf-8')) if (note76 / offs68).exists() else tag37
    return (page44('result.json', {}), page44('reader/anchors.json', {}), page44('reader/annotations.json', []), page44('reader/qa_log.json', {}), page44('reader/reading_state.json', {}))

def orde52(pass119):
    if not pass119 or len(pass119) > 90:
        return False
    extr62 = pass119.lower().strip(' .:：')
    if len(pass119.split()) <= 8 and any((extr62 == zone107 or extr62.startswith(zone107) for zone107 in text05)):
        return True
    if re.match('^\\d{1,2}(\\.\\d{1,2}){0,2}\\.?\\s+[A-Z' + meas01 + ']', pass119) and len(pass119.split()) <= 12:
        return True
    return pass119.isupper() and 3 <= len(pass119) <= 60 and bool(re.search('[A-Z]', pass119))

def pars28(matc09):
    stag85 = f" / 印刷页 {matc09['printed_page']}" if matc09.get('printed_page') else ''
    return f'''<article class="card" data-target="{link41(matc09.get('paragraph_id'))}" tabindex="0"><header><b>{link41(matc09.get('annotation_id'))}</b> · {link41(matc09.get('paragraph_id'))} · PDF p{link41(matc09.get('pdf_page'))}{link41(stag85)} · char {link41(matc09.get('char_start'))}–{link41(matc09.get('char_end'))}</header><blockquote>{link41(matc09.get('quote'))}</blockquote><p class="q">Q: {link41(matc09.get('question'))}</p><p class="a">A: {link41(matc09.get('answer'))}</p><footer>anchor_precision: {link41(matc09.get('anchor_precision'))}</footer></article>'''

def path111(pages):
    hand22, slot109 = ([], '')
    for draf86, bloc91 in enumerate(pages, 1):
        chun59 = [sect58.strip() for sect58 in bloc91.split('\n') if sect58.strip()]
        figu46 = stam77(chun59)
        unit56 = [sect58 for line49, sect58 in enumerate(chun59) if not (line49 in (0, len(chun59) - 1) and len(chun59) > 3 and re.fullmatch('(?:page\\s*)?\\d{1,4}(?:\\s*(?:of|/)\\s*\\d{1,4})?', sect58, re.I))]
        pane36 = []
        for sect58 in unit56:
            if orde52(sect58):
                if pane36:
                    hand22.append({'kind': 'p', 'sec': slot109, 'page': draf86, 'lines': pane36})
                    pane36 = []
                slot109 = sect58
                hand22.append({'kind': 'h', 'sec': sect58, 'page': draf86, 'lines': [sect58]})
            else:
                pane36.append(sect58)
        if pane36:
            hand22.append({'kind': 'p', 'sec': slot109, 'page': draf86, 'lines': pane36})
        for slic18 in hand22:
            if slic18['page'] == draf86:
                slic18.setdefault('printed', figu46)
    scor74, toke88 = ([], 0)
    for slic18 in hand22:
        pass119 = re.sub('\\s*\\n\\s*', ' ', reco31('\n'.join(slic18['lines']))).strip()
        if not pass119:
            continue
        toke88 += 2 if scor74 else 0
        scor74.append({'paragraph_id': f'p{len(scor74) + 1}', 'kind': slic18['kind'], 'section': slic18['sec'], 'page': slic18['page'], 'printed': slic18.get('printed'), 'text': pass119, 'char_start': toke88, 'char_end': toke88 + len(pass119)})
        toke88 += len(pass119)
    return scor74

def pin103(tail29, fram38, regi23, rend114, term13, dige94, path12, shee34, pars127, span101):
    marg124 = pin04 / 'inline_client.html'
    pass119 = marg124.read_text(encoding='utf-8') if marg124.exists() else revi07
    head113 = {zone107.get('paragraph_id') for zone107 in rend114}
    scre66 = ''.join((f'<span class="kv"><b>{link41(rang55)}</b> {link41(tail128)}</span>' for rang55, tail128 in [('case', tail29), ('材料', fram38.get('source_id')), ('格式', fram38.get('format')), ('页', fram38.get('pages')), ('文本层', '有' if fram38.get('text_layer') else '无'), ('抽取器', fram38.get('extractor')), ('段落', len(regi23)), ('批注', len(term13)), ('印刷页', '页脚检测' if any((slic18.get('printed') for slic18 in regi23)) else '未检出')]))
    text104 = {'{{TITLE}}': link41(f"{fram38.get('source_id') or tail29} · 阅读客户端"), '{{META}}': scre66, '{{PARAS}}': '\n'.join((enco78(slic18, term13, head113) for slic18 in regi23)), '{{CARDS}}': '\n'.join((pars28(matc09) for matc09 in term13)) or '<p class="empty">本次运行未产生批注。</p>', '{{STATS}}': ''.join((f'<tr><td>{link41(rang55)}</td><td>{link41(tail128)}</td></tr>' for rang55, tail128 in shee34.items())), '{{UNC}}': ''.join((f"<li>[{link41(comp126.get('kind'))}] {link41(comp126.get('detail'))}</li>" for comp126 in pars127)) or '<li>无</li>', '{{ANCHORS}}': fiel54(path12), '{{ANN}}': fiel54(term13), '{{QA}}': fiel54(dige94), '{{RECORD_JSON}}': fiel54(span101), '{{ANN_COUNT}}': str(len(term13))}
    for rang55, tail128 in text104.items():
        pass119 = pass119.replace(rang55, tail128)
    return pass119

def prob71(zone107):
    return re.sub('\\s+', ' ', zone107 or '').strip()

def rank47(pass119, rang55):
    extr62 = (pass119 or '').lower()
    return sum((1 for reco130 in rang55 if reco130 in extr62))

def reco31(pass119):
    pass119 = pass119.replace('\r\n', '\n').replace('\r', '\n').replace('\xad', '')
    pass119 = re.sub('(\\w)-\\n(\\w)', '\\1\\2', pass119)
    return re.sub('[ \\t]{2,}', ' ', re.sub('\\n{3,}', '\n\n', re.sub('[ \\t]+\\n', '\n', pass119))).strip('\n')

def resolve(pass119, regi23, read39):
    spli93, term112 = (pass119.get('question') or '', pass119.get('selection_text') or '')
    slot109 = (pass119.get('target_section') or '').lower().strip(' .:：')
    pool79 = [slic18 for slic18 in regi23 if slic18['kind'] == 'p']
    tile96 = {'task_id': pass119['task_id'], 'question': spli93, 'requested_selection': term112, 'target_section': pass119.get('target_section') or '', 'quote': '', 'paragraph_id': None, 'pdf_page': None, 'printed_page': None, 'section': '', 'char_start': None, 'char_end': None, 'anchor_precision': 'unresolved', 'locate_method': '', 'notes': []}

    def merg92(slic18, quote, issu89, chai67):
        zone107 = read39.find(quote)
        tile96.update(quote=quote, paragraph_id=slic18['paragraph_id'], pdf_page=slic18['page'], printed_page=slic18.get('printed'), section=slic18['section'], char_start=zone107 if zone107 >= 0 else slic18['char_start'], char_end=zone107 + len(quote) if zone107 >= 0 else slic18['char_end'], anchor_precision=issu89, locate_method=chai67)
        if zone107 < 0:
            tile96['notes'].append('quote 未定位，用段落偏移')
    tabl45 = clos43(read39, term112) if term112 else None
    if tabl45:
        matc09, wind131, quote = tabl45
        hand22 = next((reco130 for reco130 in regi23 if reco130['char_start'] <= matc09 <= reco130['char_end']), None)
        tile96.update(quote=quote, char_start=matc09, char_end=wind131, anchor_precision='char_exact', locate_method='verbatim_search')
        if hand22:
            tile96.update(paragraph_id=hand22['paragraph_id'], pdf_page=hand22['page'], printed_page=hand22.get('printed'), section=hand22['section'])
    elif term112:
        note76, ratio = targ21(term112, pool79)
        if note76 and ratio >= 0.55:
            merg92(note76, node84(note76['text'], ledg57(term112)), 'paragraph_level', 'fuzzy_paragraph_match')
            tile96['notes'].append(f'选中文本未逐字命中({ratio:.2f})，降级到段落级')
        else:
            tile96['notes'].append(f'选中文本未找到(最佳相似度{ratio:.2f})')
    if tile96['anchor_precision'] == 'unresolved':
        poin87 = [note76 for note76 in pool79 if slot109 and slot109 in (note76['section'] or '').lower()] or pool79
        rang55 = ledg57(spli93) or ledg57(term112) or ledg57(pass119.get('instruction', ''))
        inli97 = sorted(poin87, key=lambda note76: -rank47(note76['text'], rang55)) if poin87 else []
        if inli97 and rang55 and rank47(inli97[0]['text'], rang55):
            merg92(inli97[0], node84(inli97[0]['text'], rang55), 'paragraph_level', 'keyword_rank_in_section' if slot109 else 'keyword_rank_global')
            tile96['notes'].append(f"按关键词在{('章节「%s」' % slot109 if slot109 else '全文')}内排序定位，锚点为段落级")
        elif poin87:
            merg92(poin87[0], poin87[0]['text'][:300], 'page_level', 'section_first_paragraph')
            tile96['notes'].append('仅到章节首段，降级为页级')
    return tile96

def shif26(cell75):
    note76 = Path(cell75)
    inde105, curs11, term13, dige94, zone08 = open60(cell75)
    term13 = term13 if isinstance(term13, list) else term13.get('annotations', [])
    revi106 = inde105.get('result') or {}
    fram38 = dict(revi106.get('document') or {})
    fram38['_now'] = (inde105.get('runtime') or {}).get('finished_at') or ''
    cont118, rend114 = (revi106.get('closed_loop') or [], curs11.get('selections', []))
    shee34, pars127 = (curs11.get('precision_counts') or {}, inde105.get('uncertainties') or [])
    span101 = deri102(inde105.get('case_id', 'UNKNOWN-CASE'), fram38, rend114, term13, shee34, pars127, cont118)
    meas100 = note76 / 'reader'
    meas100.mkdir(parents=True, exist_ok=True)
    (note76 / 'reading_record.md').write_text(span101, encoding='utf-8')
    (meas100 / 'index.html').write_text(pin103(inde105.get('case_id', ''), fram38, curs11.get('paragraphs', []), rend114, term13, dige94.get('qa', []), curs11, shee34, pars127, span101), encoding='utf-8')
    return True

def stam77(chun59):
    for comp27 in (chun59[0] if chun59 else '', chun59[-1] if chun59 else ''):
        quot63 = re.fullmatch('(?:page\\s*|p\\.?\\s*)?(\\d{1,4})(?:\\s*(?:of|/)\\s*\\d{1,4})?', comp27.strip(), re.I) or re.match('(?:page|pp?\\.)\\s*(\\d{1,4})', comp27.strip(), re.I)
        if quot63:
            return int(quot63.group(1))
    return None

def stri61(quot63):
    tag37 = {'source_id': quot63['name'], 'path': quot63['path'].name, 'format': quot63['kind'], 'pages': 0, 'text_layer': False, 'extractor': None}
    try:
        if quot63['kind'] == 'pdf':
            clip51 = {}
            if shutil.which('pdfinfo'):
                anch99, trac72 = map33(['pdfinfo', str(quot63['path'])], 60)
                for sect58 in trac72.decode('utf-8', 'replace').splitlines():
                    if ':' in sect58:
                        rang55, tail128 = sect58.split(':', 1)
                        clip51[rang55.strip().lower()] = tail128.strip()
            tag37.update(encrypted=str(clip51.get('encrypted', '')).lower().startswith('yes'), pages_reported=clip51.get('pages'))
            if tag37['encrypted']:
                add('pending_human', 'encrypted_pdf', f"{quot63['name']} 加密；若无正文需无密码副本")
            if quot63['size'] > 120 * 1048576:
                add('degradations', 'oversize_pdf', f"{quot63['name']} >120MB，仅处理前 400 页")
            pass119, valu48 = join81(quot63['path'])
            if not pass119:
                scop82 = trac80(quot63['path'])
                pass119, valu48 = ('\x0c'.join(scop82), 'builtin_stream_scan') if scop82 else (None, None)
                if pass119:
                    add('degradations', 'extractor_fallback', 'pdftotext 缺失，改用标准库内容流抽取(分页近似)')
            if not pass119:
                add('pending_human', 'no_text_layer', f"{quot63['name']} 无文本层(扫描件/加密)；需 OCR 或人工录入")
                return (tag37, 'no_text_layer')
            tag37['extractor'] = valu48
            pages = [reco31(reco130) for reco130 in pass119.split('\x0c')]
        elif quot63['kind'] == 'text':
            row98 = quot63['path'].read_text(encoding='utf-8', errors='replace')
            pages = [reco31(reco130) for reco130 in (row98.split('\x0c') if '\x0c' in row98 else [row98])]
            tag37['extractor'] = 'text'
        else:
            add('pending_human', 'unsupported_material', f"{quot63['name']}({quot63['kind']}) 非可读文本载体")
            return (tag37, 'unsupported')
    except Exception as view40:
        add('errors', 'read_failed', f"{quot63['name']}: {view40!r}")
        return (tag37, 'unreadable')
    pages = [note76 for note76 in pages if note76.strip()] or ['']
    word24 = '\n'.join(pages)
    matc09 = sum((comp27.isalpha() for comp27 in word24))
    tag37.update(pages=len(pages), text_layer=len(word24.strip()) > 40 and matc09 >= max(20, 0.25 * len(re.sub('\\s', '', word24))))
    if not tag37['text_layer']:
        add('pending_human', 'no_text_layer', f"{quot63['name']} 文本过少或乱码(alpha={matc09})，疑为扫描件；需 OCR")
        return (tag37, 'no_text_layer')
    tag37['_pages'] = pages
    return (tag37, None)

def targ21(hand121, pool79):
    regi122, pass20, marg25 = (prob71(hand121)[:400].lower(), None, 0.0)
    for note76 in pool79:
        tile96 = SequenceMatcher(None, regi122, prob71(note76['text'])[:1200].lower()).ratio()
        if tile96 > marg25:
            pass20, marg25 = (note76, tile96)
    return (pass20, marg25)

def trac80(note76):
    try:
        import zlib
        tag37 = note76.read_bytes()
    except Exception:
        return None
    scor74 = []
    for quot63 in re.finditer(b'stream\\r?\\n(.*?)endstream', tag37, re.S):
        try:
            pass119 = zlib.decompress(quot63.group(1)).decode('latin-1', 'ignore')
        except Exception:
            continue
        reco130 = ' '.join(re.findall('\\((?:[^()\\\\]|\\\\.)*\\)', pass119))
        if reco130.strip():
            scor74.append(reco130)
    return scor74 or None

def trai64(mark17=None):
    rend15 = argparse.ArgumentParser(prog='viewer.py', description='margin-reader 表现层：读取输出目录中已落盘的 JSON，重建离线单文件 HTML 阅读客户端与 Markdown 阅读记录。', epilog='用法: --output <out_dir>；渲染失败也只打印错误对象，退出码恒为 0。')
    rend15.add_argument('--output', default='/app/output', help='产物目录；缺省 /app/output')
    matc09 = rend15.parse_args(mark17)
    try:
        print(json.dumps(shif26(matc09.output), ensure_ascii=False, indent=2))
    except Exception as view40:
        print(json.dumps({'error': repr(view40)}, ensure_ascii=False))
    return 0

def wrap115(pass119):
    return [zone107.strip() for zone107 in re.split('(?<=[.!?。！？])\\s+', pass119 or '') if zone107.strip()]
if __name__ == '__main__':
    try:
        sys.exit(trai64())
    except SystemExit:
        raise
    except Exception:
        print(json.dumps({'error': 'uncaught'}))
        sys.exit(0)
