"""阅读客户端主流程（margin-reader）：一次程序化运行内完成 打开材料 → 切块分段 → 定位选区 → 以选区边界构造上下文作答 → 逐条落盘批注 → 回看渲染 → 导出阅读记录。仅使用 Python 标准库；不联网、不依赖工作目录；异常全部内部消化，进程退出码恒为 0。输出契约、证据字段与产物清单见 SKILL.md 与 references/。"""
import argparse, hashlib, json, os, re, sys, time, traceback
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import viewer as C
from viewer import head14, resolve, stri61, path111, shif26 as render_client
slot10 = '1.0.0'
text05 = 'abstract introduction background related work materials and methods methods method experimental results and discussion results discussion conclusion conclusions limitations references acknowledgements appendix 摘要 引言 前言 方法 材料与方法 结果与讨论 结果 讨论 结论 参考文献 致谢'.split()
deri03 = {'errors': [], 'degradations': [], 'pending_human': [], 'changes': []}
C.deri03 = deri03
span02 = ['reader/index.html', 'reader/anchors.json', 'reader/annotations.json', 'reader/qa_log.json', 'reader/reading_state.json', 'reading_record.md']
zone08 = ('case_id', 'status', 'result', 'claims', 'uncertainties', 'sources', 'pending_human', 'errors', 'degradations', 'changes', 'runtime')
matc09 = {'task.md', 'case.json', 'output-contract.md', 'guide.md', 'public-manifest.json'}

def clip51(stag85, wind32, zone107):
    wind32['runtime'].update(finished_at=now(), elapsed_s=round(time.time() - zone107, 2), python=sys.version.split()[0], log_counts={chai67: len(head113) for chai67, head113 in deri03.items()})
    lane65(stag85 / 'result.json', regi23(wind32.get('contract', {}), wind32))
    try:
        render_client(stag85)
    except Exception as line49:
        rend15('degradations', 'render_failed', repr(line49))
    try:
        import audit as A
        A.unit56(stag85, wind32, zone107)
    except Exception:
        rend15('errors', 'augment_failed', traceback.format_exc()[:600])
    return 0

def inli97(term13):
    zone107 = time.time()
    chun59 = Path(term13.input or os.environ.get('INPUT_DIR', '/input'))
    stag85 = Path(term13.output or os.environ.get('OUTPUT_DIR', '/app/output'))
    try:
        stag85.mkdir(parents=True, exist_ok=True)
    except Exception:
        stag85 = Path.cwd() / 'output'
        stag85.mkdir(parents=True, exist_ok=True)
    plai95 = stag85 / 'reader'
    wind32 = {'case_id': 'UNKNOWN-CASE', 'status': 'input_error', 'result': None, 'claims': [], 'uncertainties': [], 'sources': [], 'pending_human': deri03['pending_human'], 'errors': deri03['errors'], 'degradations': deri03['degradations'], 'changes': deri03['changes'], 'contract': {}, 'runtime': {'skill': 'margin-reader', 'version': slot10, 'started_at': now()}}
    colu35, fram38 = ({}, {})
    view40 = chun59 / 'case.json'
    if not view40.exists():
        pane36 = sorted(chun59.rglob('case*.json')) if chun59.exists() else []
        view40 = pane36[0] if pane36 else None
    if view40:
        try:
            colu35 = json.loads(view40.read_text(encoding='utf-8', errors='replace'))
            if not isinstance(colu35, dict):
                rend15('errors', 'case_not_object', f'{view40.name} 顶层不是对象')
                colu35 = {}
        except Exception as line49:
            rend15('errors', 'case_json_invalid', f'{view40.name}: {line49!r}')
            colu35 = {}
        wind32['case_id'] = str(colu35.get('case_id') or 'UNKNOWN-CASE')
        fram38 = colu35.get('output_contract') or colu35.get('outputContract') or {}
    else:
        rend15('degradations', 'case_json_missing', '无 case.json，按材料语义继续')
    wind32['contract'] = fram38
    wind32['runtime'].update(case_json=view40.name if view40 else None, output_contract_fields=list(fram38) if isinstance(fram38, dict) else fram38)
    lane65(stag85 / 'result.json', regi23(fram38, wind32))
    extr62 = next((colu35[chai67] for chai67 in ('task_instruction', 'instruction', 'task', 'question', 'prompt') if isinstance(colu35.get(chai67), str) and colu35[chai67].strip()), '')
    if not extr62 and (chun59 / 'task.md').exists():
        try:
            extr62 = (chun59 / 'task.md').read_text(encoding='utf-8', errors='replace')[:4000]
        except Exception as line49:
            rend15('degradations', 'task_md_unreadable', repr(line49))
    trac72 = tabl45(chun59)
    wind32['sources'] = [{'source_id': entr70['name'], 'path': entr70['path'].name, 'kind': entr70['kind'], 'bytes': entr70['size'], 'sha256': surf53(entr70['path'])} for entr70 in trac72]
    bloc91 = next((entr70 for entr70 in trac72 if entr70['kind'] == 'pdf'), None) or next((entr70 for entr70 in trac72 if entr70['kind'] == 'text'), None)
    inde105 = []

    def text104(labe73, row98, **stre69):
        seri42 = {'step': labe73, 'status': row98}
        seri42.update({chai67: head113 for chai67, head113 in stre69.items() if head113 is not None})
        seri42['t_s'] = round(time.time() - zone107, 3)
        inde105.append(seri42)
    if not bloc91:
        rend15('degradations', 'no_material', '未提供可读材料(PDF/TXT)')
        wind32['uncertainties'].append({'id': 'u-no-material', 'kind': 'missing_source', 'detail': '未提供可读材料(PDF/TXT)' + (f"；已见: {', '.join((entr70['name'] for entr70 in trac72))}" if trac72 else ''), 'action_required': '提供 PDF/TXT 后重跑'})
        for chai67 in ('open', 'locate', 'select', 'ask', 'save', 'review', 'export'):
            text104(chai67, 'skipped', output={'reason': 'no_material'})
        for curs11, path12 in (('anchors.json', {'schema': 'margin-reader/anchors@1', 'source_id': None, 'paragraphs': [], 'selections': [], 'precision_counts': {}}), ('annotations.json', []), ('qa_log.json', {'schema': 'margin-reader/qa@1', 'qa': []}), ('reading_state.json', {'schema': 'margin-reader/state@1', 'source_id': None, 'status': 'input_error', 'last_paragraph_id': None, 'sessions': 1})):
            lane65(plai95 / curs11, path12)
        wind32['result'] = {'document': None, 'closed_loop': inde105, 'selections': [], 'annotations': [], 'export': {'files': span02, 'entry_count': 0}, 'note': '无材料，阅读闭环未执行；已产出空结构的最小产物'}
        return clip51(stag85, wind32, zone107)
    figu46, rend114 = stri61(bloc91)
    text104('open', 'done' if figu46.get('text_layer') else 'failed' if rend114 else 'partial', output={'pages': figu46.get('pages'), 'text_layer': figu46.get('text_layer'), 'extractor': figu46.get('extractor'), 'encrypted': figu46.get('encrypted')}, artifact='reader/anchors.json')
    if rend114:
        wind32['status'] = 'insufficient_evidence'
        wind32['uncertainties'].append({'id': 'u-text-layer', 'kind': 'no_text_layer', 'detail': f"{bloc91['name']} 不可读({rend114})；不生成正文", 'action_required': 'OCR 后重跑或人工录入该段'})
        lane65(plai95 / 'anchors.json', {'schema': 'margin-reader/anchors@1', 'source_id': bloc91['name'], 'paragraphs': [], 'selections': [], 'precision_counts': {}})
        lane65(plai95 / 'annotations.json', [])
        lane65(plai95 / 'qa_log.json', {'schema': 'margin-reader/qa@1', 'qa': []})
        lane65(plai95 / 'reading_state.json', {'source_id': bloc91['name'], 'status': wind32['status'], 'last_paragraph_id': None})
        for chai67 in ('locate', 'select', 'ask', 'save', 'review', 'export'):
            text104(chai67, 'skipped', output={'reason': rend114})
        wind32['result'] = {'document': {chai67: head113 for chai67, head113 in figu46.items() if not chai67.startswith('_')}, 'closed_loop': inde105, 'selections': [], 'annotations': [], 'export': {'files': ['reader/index.html'], 'entry_count': 0}, 'note': f'文本层缺失({rend114})：保留占位客户端，未虚构原文'}
        clip51(stag85, wind32, zone107)
        render_client(stag85)
        return 0
    tail29 = path111(figu46.pop('_pages'))
    valu48 = '\n\n'.join((hand22['text'] for hand22 in tail29))
    text104('locate', 'done' if tail29 else 'failed', output={'blocks': len(tail29), 'chars': len(valu48)}, artifact='reader/anchors.json')
    matc108 = poin87(colu35, extr62)
    wind32['_tasks'] = matc108
    text104('select', 'done', output={'task_ids': [revi106['task_id'] for revi106 in matc108], 'with_selection': sum((1 for revi106 in matc108 if revi106.get('selection_text')))}, artifact='reader/anchors.json')
    mark17, grad30 = ([], {})
    try:
        scop82 = json.loads((plai95 / 'annotations.json').read_text(encoding='utf-8'))
        mark17 = [mark116 for mark116 in (scop82 if isinstance(scop82, list) else scop82.get('annotations', [])) if isinstance(mark116, dict)]
        grad30 = {(mark116.get('paragraph_id'), (mark116.get('question') or '').strip()): mark116 for mark116 in mark17}
        if mark17:
            rend15('changes', 'annotations_loaded', f'载入历史批注 {len(mark17)} 条')
    except Exception:
        pass
    marg25, meas100, tag37 = ({hand22['paragraph_id']: hand22 for hand22 in tail29}, [], [])
    for revi106 in matc108:
        anch99 = resolve(revi106, tail29, valu48)
        comp27 = marg25.get(anch99.get('paragraph_id'))
        if comp27 and anch99.get('pdf_page') is None:
            anch99.update(pdf_page=comp27['page'], printed_page=comp27.get('printed'), section=comp27['section'])
        slic18 = head14(anch99, comp27)
        anch99.update(head14=slic18['answer'], answer_quotes=slic18['answer_quotes'], status=slic18['status'], task_id=revi106['task_id'])
        meas100.append(anch99)
        scre66 = f'/reader/anchors.json#/selections/{len(meas100) - 1}'
        word24 = {'pdf_page': anch99.get('pdf_page'), 'printed_page': anch99.get('printed_page'), 'paragraph_id': anch99.get('paragraph_id'), 'section': anch99.get('section')}

        def spli93(merg92):
            note76 = comp27['text'].find(merg92) if comp27 else -1
            if note76 >= 0:
                row98 = comp27['char_start'] + note76
                return dict(word24, char_start=row98, char_end=row98 + len(merg92), json_pointer=scre66)
            return dict(word24, char_start=anch99.get('char_start'), char_end=anch99.get('char_end'), json_pointer=scre66)
        if slic18['answer_quotes']:
            tag37.append({'claim_id': revi106['task_id'] + '-answer', 'kind': 'answer_span', 'statement': slic18['answer'], 'readability': 'directly_read', 'evidence': [{'source_id': bloc91['name'], 'quote': mark116, 'location': spli93(mark116)} for mark116 in slic18['answer_quotes']], 'condition': '问答上下文边界=选区片段+所在段落+章节标题；其余章节未参与'})
        if anch99.get('quote'):
            tag37.append({'claim_id': revi106['task_id'] + '-anchor', 'kind': 'selection_anchor', 'statement': f"选中片段锚定于 {anch99.get('paragraph_id')}(PDF p.{anch99.get('pdf_page')})", 'readability': 'directly_read' if anch99['anchor_precision'] == 'char_exact' else 'inferred', 'evidence': [{'source_id': bloc91['name'], 'quote': anch99['quote'], 'location': spli93(anch99['quote'])}], 'condition': f"锚点精度={anch99['anchor_precision']}；规范化文本字符偏移"})
        if anch99['anchor_precision'] == 'unresolved' or slic18['status'] != 'answered':
            wind32['uncertainties'].append({'id': f"u-{revi106['task_id']}", 'kind': 'unresolved_or_weak', 'detail': f"{revi106['task_id']} 不完备(precision={anch99['anchor_precision']},status={slic18['status']})" + ('；' + '；'.join(anch99['notes']) if anch99['notes'] else ''), 'action_required': '人工确认段落或补段后重跑'})
        key = (anch99.get('paragraph_id'), (anch99['question'] or '').strip())
        if key in grad30:
            grad30[key].update(head14=slic18['answer'], answer_quotes=slic18['answer_quotes'], status=slic18['status'])
        else:
            scor74 = {'annotation_id': f"an-{anch99.get('paragraph_id') or 'na'}-{len(mark17) + 1:02d}", 'task_id': revi106['task_id'], 'paragraph_id': anch99.get('paragraph_id'), 'quote': anch99.get('quote', ''), 'pdf_page': anch99.get('pdf_page'), 'printed_page': anch99.get('printed_page'), 'section': anch99.get('section'), 'char_start': anch99.get('char_start'), 'char_end': anch99.get('char_end'), 'anchor_precision': anch99['anchor_precision'], 'question': anch99['question'], 'answer': slic18['answer'], 'answer_quotes': slic18['answer_quotes'], 'context_scope': slic18['context_scope'], 'status': slic18['status'], 'tags': ['reading-05', revi106.get('source', '')], 'created_at': now()}
            mark17.append(scor74)
            grad30[key] = scor74
        lane65(plai95 / 'annotations.json', mark17)
    text104('ask', 'done' if any((row98['status'] == 'answered' for row98 in meas100)) else 'partial', output={'answered': sum((1 for row98 in meas100 if row98['status'] == 'answered')), 'tasks': len(meas100)}, artifact='reader/qa_log.json')
    text104('save', 'done' if mark17 else 'failed', output={'annotations': len(mark17)}, artifact='reader/annotations.json')
    read39 = {'char_exact': 0, 'paragraph_level': 0, 'page_level': 0, 'unresolved': 0}
    for row98 in meas100:
        read39[row98['anchor_precision']] = read39.get(row98['anchor_precision'], 0) + 1
    wrap16 = {'schema': 'margin-reader/anchors@1', 'source_id': bloc91['name'], 'doc_text_sha256': slot109(valu48), 'normalization': '合并跨行连字符与软连字符、压缩多余空白；字符偏移以规范化文本为准', 'page_map': [{'pdf_page': hand22['page'], 'printed_page': hand22.get('printed'), 'paragraph_id': hand22['paragraph_id']} for hand22 in tail29], 'paragraphs': [{chai67: hand22.get(chai67) for chai67 in ('paragraph_id', 'kind', 'section', 'page', 'printed', 'char_start', 'char_end', 'text')} for hand22 in tail29], 'selections': [{chai67: row98.get(chai67) for chai67 in ('task_id', 'quote', 'paragraph_id', 'pdf_page', 'printed_page', 'section', 'char_start', 'char_end', 'anchor_precision', 'locate_method')} for row98 in meas100], 'precision_counts': read39}
    lane65(plai95 / 'anchors.json', wrap16)
    lane65(plai95 / 'qa_log.json', {'schema': 'margin-reader/qa@1', 'source_id': bloc91['name'], 'context_policy': 'context boundary: selected span + its paragraph + section heading', 'qa': [{'task_id': mark116.get('task_id'), 'question': mark116.get('question'), 'answer': mark116.get('answer'), 'answer_quotes': mark116.get('answer_quotes'), 'paragraph_id': mark116.get('paragraph_id'), 'anchor': {chai67: mark116.get(chai67) for chai67 in ('pdf_page', 'printed_page', 'char_start', 'char_end', 'section')}, 'anchor_precision': mark116.get('anchor_precision'), 'context_scope': mark116.get('context_scope'), 'status': mark116.get('status')} for mark116 in mark17]})
    try:
        scan90 = json.loads((plai95 / 'reading_state.json').read_text(encoding='utf-8'))
    except Exception:
        scan90 = {}
    lane65(plai95 / 'reading_state.json', {'schema': 'margin-reader/state@1', 'source_id': bloc91['name'], 'doc_text_sha256': slot109(valu48), 'last_paragraph_id': meas100[-1].get('paragraph_id') if meas100 else None, 'annotation_ids': [mark116['annotation_id'] for mark116 in mark17], 'sessions': int(scan90.get('sessions', 0)) + 1, 'resumed_from_previous': bool(scan90), 'updated_at': now()})
    text104('review', 'done', output={'annotations': len(mark17), 'paragraphs': len(tail29), 'resumed_from_previous': bool(scan90)}, artifact='reader/index.html')
    term112 = [row98 for row98 in meas100 if row98['anchor_precision'] == 'unresolved']
    if term112:
        wind32['uncertainties'].append({'id': 'u-unresolved', 'kind': 'unresolved_anchor', 'detail': f'{len(term112)} 个选区无法定位，未按段落级对待', 'action_required': '人工指定目标段落后重跑'})
    cont19 = sum((1 for row98 in meas100 if row98['status'] == 'answered'))
    page44 = fram38.get('status') if isinstance(fram38, dict) else ''
    pool79 = 'ok' if not isinstance(page44, str) or re.search('\\bok\\b', page44) else 'answered' if 'answered' in page44 else 'ok'
    wind32['status'] = pool79 if cont19 and cont19 == len(meas100) and (not term112) and all((row98['status'] == 'done' for row98 in inde105)) else 'partial'
    tag37.append({'claim_id': 'doc-facts', 'kind': 'document_facts', 'statement': f"{bloc91['name']}: {figu46.get('pages')} 页, 文本层{('可用' if figu46.get('text_layer') else '不可用')}, {len(tail29)} 个文本块", 'readability': 'directly_read', 'evidence': [{'source_id': bloc91['name'], 'quote': None, 'location': {'field': 'pages', 'pdf_page': None}}], 'condition': f"抽取器={figu46.get('extractor')}"})
    wind32['claims'] = tag37
    text104('export', 'done', output={'files': span02, 'entry_count': len(mark17)}, artifact='reading_record.md')
    wind32['result'] = {'task_summary': {'instruction': extr62[:300], 'tasks': len(meas100), 'answered': cont19}, 'document': figu46, 'closed_loop': inde105, 'selections': meas100, 'annotations': mark17, 'anchor_precision_counts': read39, 'context_design': {'rule': 'context boundary: selected span + its paragraph + section heading', 'enforced': True, 'excluded': '未选中的章节不进入问答依据；chars_used 记录实际使用字符数'}, 'export': {'files': span02, 'entry_count': len(mark17)}, 'efficiency': {'script_steps': len(inde105), 'user_actions': 1, 'reopen': 0, 'copy_paste': 0}, 'method_notes': {'extraction': figu46.get('extractor'), 'anchor_rule': wrap16['normalization'], 'context_rule': 'selection+paragraph+heading', 'persistence': '每条批注即时原子落盘；重跑时读入旧批注并按段落+问题合并，数量只增不减'}, 'artifacts': span02}
    clip51(stag85, wind32, zone107)
    render_client(stag85)
    return 0

def lane65(draf86, cell75):
    try:
        draf86.parent.mkdir(parents=True, exist_ok=True)
        revi106 = draf86.parent / (draf86.name + '.tmp')
        revi106.write_text(json.dumps(cell75, ensure_ascii=False, indent=2), encoding='utf-8')
        revi106.replace(draf86)
        return True
    except Exception as line49:
        rend15('errors', 'write_failed', f'{draf86}: {line49!r}')
        return False

def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def poin87(colu35, extr62):
    curs110 = []
    if isinstance(colu35, dict):
        for key in ('reading_tasks', 'tasks', 'reading_task', 'queries', 'questions'):
            head113 = colu35.get(key)
            for sect58, quot63 in enumerate(head113 if isinstance(head113, list) else [head113] if isinstance(head113, dict) else [], 1):
                if not isinstance(quot63, dict):
                    continue
                rang55 = lambda *offs68: next((quot63[mark116] for mark116 in offs68 if isinstance(quot63.get(mark116), str) and quot63[mark116].strip()), '')
                merg92, anch99 = (rang55('question', 'query', 'ask', 'prompt'), rang55('selection_text', 'selected_text', 'target_quote', 'target_quote_anchor', 'quote', 'selection'))
                if merg92 or anch99:
                    curs110.append({'task_id': str(quot63.get('task_id') or quot63.get('id') or f't{sect58}'), 'instruction': rang55('instruction', 'task') or extr62, 'question': merg92, 'selection_text': anch99, 'target_section': rang55('target_section', 'section', 'locate'), 'source': 'case.' + key})
    revi106 = (extr62 or '').strip()
    if not curs110 and revi106:
        dige94 = {'task_id': 't1', 'instruction': revi106, 'question': '', 'target_section': '', 'selection_text': ''}
        for toke88 in ('「(.{6,400}?)」', '“(.{6,400}?)”', '"([^"]{6,400})"', '『(.{6,400}?)』'):
            entr70 = re.search(toke88, revi106, re.S)
            if entr70:
                dige94['selection_text'] = entr70.group(1).strip()
                break
        dige94['target_section'] = next((mark116 for mark116 in sorted(text05, key=len, reverse=True) if mark116 in revi106.lower()), '')
        span101 = [mark116.strip() for mark116 in re.split('(?<=[。！？?])\\s*|\\n+|；|;', revi106) if mark116.strip()]
        shee34 = [mark116 for mark116 in span101 if re.search('[?？]|提问|问题|question|ask|问[:：]', mark116, re.I)]
        issu89 = max(shee34, key=len) if shee34 else span101[-1] if span101 else revi106
        entr70 = re.search('(?:提问|问题|question|ask|问)\\s*[:：]?\\s*(.+)$', issu89, re.I)
        dige94['question'] = (entr70.group(1) if entr70 else issu89).strip(' 。；;')
        dige94['source'] = 'task_instruction'
        curs110 = [dige94]
    return curs110

def regi23(fram38, wind32):
    tile96 = {chai67: wind32[chai67] for chai67 in ('case_id', 'status', 'result', 'claims', 'uncertainties', 'sources', 'pending_human', 'errors', 'degradations', 'changes', 'runtime')}
    tile96['uncertainty'] = wind32['uncertainties']
    brie83 = {}
    if isinstance(fram38, dict):
        for chai67, head113 in fram38.items():
            brie83[chai67] = tile96[chai67] if chai67 in tile96 else [] if isinstance(head113, list) else {} if isinstance(head113, dict) else None
    elif isinstance(fram38, list):
        brie83 = {chai67: tile96.get(chai67) for chai67 in fram38 if isinstance(chai67, str)}
    for chai67 in zone08:
        brie83.setdefault(chai67, tile96[chai67])
    brie83.setdefault('uncertainty', tile96['uncertainty'])
    return brie83

def rend15(hand22, chai67, seri42):
    deri03[hand22].append({'kind': chai67, 'detail': str(seri42)[:400]})

def slot109(row98):
    return hashlib.sha256(row98.encode('utf-8', 'ignore')).hexdigest()

def surf53(draf86):
    unit56 = hashlib.sha256()
    try:
        with open(draf86, 'rb') as sele50:
            for wind32 in iter(lambda: sele50.read(262144), b''):
                unit56.update(wind32)
        return unit56.hexdigest()
    except Exception:
        return None

def tabl45(chun59):
    brie83 = []
    if not chun59.exists():
        return brie83
    for draf86 in sorted(chun59.rglob('*')):
        labe73, line49 = (draf86.name.lower(), draf86.suffix.lower())
        if not draf86.is_file() or labe73.startswith('.') or labe73 in matc09:
            continue
        chai67 = 'pdf' if line49 == '.pdf' else 'text' if line49 in ('.txt', '.md', '.markdown', '.text') else 'json' if line49 == '.json' else 'table' if line49 in ('.csv', '.tsv') else 'office' if line49 in ('.docx', '.xlsx', '.pptx') else None
        if chai67:
            brie83.append({'kind': chai67, 'path': draf86, 'name': draf86.name, 'size': draf86.stat().st_size})
    return brie83

def trai64(argv=None):
    pass20 = argparse.ArgumentParser(prog='pipeline.py', description='margin-reader 主流程：单次运行走完 打开→分段→定位→边界问答→批注→回看→导出，输出 result.json 与离线单文件 HTML 阅读客户端（锚点含 PDF 物理页、印刷页与字符偏移）。', epilog='产物与契约见 SKILL.md；无论成功或降级，退出码恒为 0。')
    pass20.add_argument('--input', default=None, help='案例输入目录；缺省读 $INPUT_DIR，再缺省 /input')
    pass20.add_argument('--output', default=None, help='产物输出目录；缺省读 $OUTPUT_DIR，再缺省 /app/output')
    pass20.add_argument('--version', action='version', version='margin-reader ' + slot10)
    term13 = pass20.parse_args(argv)
    return inli97(term13)
if __name__ == '__main__':
    try:
        trai64()
    except SystemExit:
        raise
    except Exception:
        rend15('errors', 'uncaught', traceback.format_exc()[:1500])
        try:
            cell75 = Path(sys.argv[sys.argv.index('--output') + 1]) if '--output' in sys.argv[:-1] else Path(os.environ.get('OUTPUT_DIR', '/app/output'))
            cell75.mkdir(parents=True, exist_ok=True)
            lane65(cell75 / 'result.json', {'case_id': 'UNKNOWN-CASE', 'status': 'input_error', 'result': None, 'claims': [], 'uncertainties': [], 'sources': [], 'pending_human': deri03['pending_human'], 'errors': deri03['errors'], 'degradations': deri03['degradations'], 'changes': deri03['changes'], 'runtime': {'version': slot10}})
            import audit as _A
            _A.valu48(cell75, {'case_id': 'UNKNOWN-CASE'}, traceback.format_exc())
        except Exception:
            pass
    sys.exit(0)
