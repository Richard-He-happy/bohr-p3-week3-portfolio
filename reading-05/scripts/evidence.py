"""可核验资产 · 证据层（evidence）：扫描输出目录并载入本轮结果，把任务、段落、选区、批注逐条对齐，生成带定位器与逐字引文的逐项期望，并对每一项给出可复核的判定。本层只读数据、不写屏幕输出；纯标准库实现。"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, time, traceback
from datetime import datetime, timezone
from pathlib import Path
term13 = '1.0.0'
text05 = Path(__file__).resolve().parent
matc09 = text05.parent
inde06, slot10 = (text05 / 'pipeline.py', text05 / 'viewer.py')
meas01 = ['golden_standard.json', 'diff_report.md', 'version_history.md', 'run.log', 'self_check.json']
deri03 = ['reader/anchors.json', 'reader/annotations.json', 'reader/qa_log.json', 'reader/reading_state.json', 'reader/index.html', 'reading_record.md']
zone08 = ('ok', 'answered', 'partial', 'insufficient_evidence', 'input_error')
pin04 = ['annotation_id', 'task_id', 'paragraph_id', 'quote', 'pdf_page', 'char_start', 'char_end', 'anchor_precision', 'question', 'answer', 'answer_quotes', 'status']
curs11 = ['open', 'locate', 'select', 'ask', 'save', 'review', 'export']
span02 = '一-鿿'
path12 = set('the a an of and or to in is are was were for with on by as at this that these those from be been being which who we our it its their they them can could may might not no do does did how what why'.split())
revi07 = re.compile('(?<![A-Za-z0-9])\\d+(?:[.,]\\d+)?')

def bloc91(pars28):
    return pars28['c'].get('_tasks') or [{'task_id': pool79.get('task_id'), 'question': pool79.get('question'), 'selection_text': pool79.get('requested_selection') or '', 'target_section': pool79.get('target_section') or ''} for pool79 in pars28['sels']]

def brie83(pars28, merg92):
    return next((pool79 for pool79 in pars28['sels'] if str(pool79.get('task_id')) == str(merg92)), None)

def cell75(pars28, prob71, trac80):
    entr70 = [lane65 for lane65 in pars28['paras'] if lane65.get('kind') == 'p' and (lane65.get('text') or '').strip()]
    if not entr70:
        return None
    valu48 = line49(prob71) or line49(trac80)
    stre69 = [lane65 for lane65 in entr70 if trac80 and trac80.lower() in (lane65.get('section') or '').lower()] or entr70
    targ21 = sorted(stre69, key=lambda lane65: -read39(lane65['text'], valu48))[0]
    return targ21 if valu48 and read39(targ21['text'], valu48) else None

def chai67(pars28, stri61):
    for lane65 in pars28['paras']:
        head14, cont19 = (lane65.get('char_start'), lane65.get('char_end'))
        if isinstance(head14, int) and isinstance(cont19, int) and (head14 <= stri61 <= cont19):
            return lane65
    return None

def chun59(pool79):
    return re.sub('\\s+', ' ', pool79 or '').strip()

def colu35(grad30, prob71):
    prob71 = (prob71 or '').strip()
    if len(prob71) < 2 or not grad30:
        return None
    view40 = grad30.find(prob71)
    if view40 >= 0:
        return (view40, view40 + len(prob71))
    tabl45 = grad30.find(chun59(prob71))
    return (tabl45, tabl45 + len(chun59(prob71))) if tabl45 >= 0 else None

def comp27(trai64, hand22):
    note76 = trai64 / 'reader'
    enco78 = rank47(trai64 / 'result.json', {}) or {}
    rend15 = rank47(note76 / 'anchors.json', {}) or {}
    mark17 = rank47(note76 / 'annotations.json', [])
    mark17 = mark17.get('annotations') if isinstance(mark17, dict) else mark17
    mark17 = [head14 for head14 in mark17 or [] if isinstance(head14, dict)]
    offs68 = [lane65 for lane65 in rend15.get('paragraphs') or [] if isinstance(lane65, dict)]
    tail29 = enco78.get('result') or {}
    return {'outp': trai64, 'res': enco78, 'anns': mark17, 'qa': rank47(note76 / 'qa_log.json', {}) or {}, 'paras': offs68, 'doc': '\n\n'.join((lane65.get('text') or '' for lane65 in offs68)), 'docsha': rend15.get('doc_text_sha256'), 'sels': tail29.get('selections') or [], 'docs': tail29.get('document') or {}, 'loop': tail29.get('closed_loop') or [], 'claims': enco78.get('claims') or [], 'srcs': enco78.get('sources') or [], 'c': hand22, 'case_id': enco78.get('case_id') or hand22.get('case_id'), 'status': enco78.get('status')}

def draf86(lane65):
    fram38 = hashlib.sha256()
    try:
        with open(lane65, 'rb') as shee34:
            for hand22 in iter(lambda: shee34.read(1 << 18), b''):
                fram38.update(hand22)
        return fram38.hexdigest()
    except Exception:
        return None

def fiel54(seri42, regi23, merg92, stam77, map33, clip51, scor74, word24, slic18=None, status='supported', note=''):
    return {'item_id': seri42, 'category': regi23, 'task_id': merg92, 'requirement': stam77, 'expect': map33, 'locator': clip51, 'quote': scor74, 'check': word24, 'check_arg': slic18 or {}, 'status': status, 'note': note}

def figu46(lane65, open60):
    try:
        lane65 = Path(lane65)
        lane65.parent.mkdir(parents=True, exist_ok=True)
        scan90 = lane65.parent / (lane65.name + '.tmp')
        scan90.write_text(json.dumps(open60, ensure_ascii=False, indent=2), encoding='utf-8')
        scan90.replace(lane65)
        return True
    except Exception:
        return False

def line49(scan90):
    quot63, join81 = ([], set())
    for dige94 in re.findall('[A-Za-z][A-Za-z\\-]{3,}|[' + span02 + ']{2,6}', (scan90 or '').lower()):
        if dige94 not in path12 and dige94 not in join81:
            join81.add(dige94)
            quot63.append(dige94)
    return quot63

def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def pane36(pars28):
    grad30, page44 = (pars28['doc'], [])
    for scan90 in bloc91(pars28):
        merg92, prob71 = (str(scan90.get('task_id') or 't?'), scan90.get('question') or '')
        scop82, trac80 = ((scan90.get('selection_text') or '').strip(), (scan90.get('target_section') or '').strip())
        toke88 = colu35(grad30, scop82) if scop82 else None
        scre66 = chai67(pars28, toke88[0]) if toke88 else cell75(pars28, prob71, trac80) if prob71 else None
        if scop82 and toke88:
            labe73 = grad30[toke88[0]:toke88[1]]
            page44.append(fiel54(merg92 + '-A0', 'answer_point', merg92, '答案依据覆盖任务选中文本(原文逐字存在)', {'selection': labe73}, sele50(pars28, scre66, labe73), labe73, 'answer_contains'))
        elif scop82:
            page44.append(fiel54(merg92 + '-A0', 'answer_point', merg92, '答案依据覆盖任务选中文本', {'selection': scop82}, None, None, 'unsupported', status='pending', note='材料中未逐字找到该选中文本'))
        if scre66:
            node84 = sorted(stag85(scre66.get('text') or '') or [scre66.get('text') or ''], key=lambda pool79: (-read39(pool79, line49(prob71)), len(pool79)))[0]
            page44.append(fiel54(merg92 + '-A1', 'answer_point', merg92, '答案包含该问题在原段落的最佳支撑句(逐字,不改写)', {'sentence': node84}, sele50(pars28, scre66, node84), node84, 'answer_contains'))
            ledg57 = sorted(sect58(node84))
            if ledg57:
                page44.append(fiel54(merg92 + '-N1', 'number_consistency', merg92, '答案数字可在原文支撑句中逐字找到', {'numbers': ledg57}, sele50(pars28, scre66, node84), node84, 'answer_numbers', {'numbers': ledg57}))
        else:
            page44.append(fiel54(merg92 + '-A1', 'answer_point', merg92, '答案由材料段落支撑', {}, None, None, 'unsupported', status='pending', note='材料中未找到与问题相关的段落'))
        page44.append(fiel54(merg92 + '-L1', 'evidence_anchor', merg92, '锚点真实: 切片与 quote 逐字一致', {'slice_equals_quote': True}, None, None, 'anchor_slice', {'task_id': merg92}))
        if scop82:
            page44.append(fiel54(merg92 + '-L2', 'evidence_anchor', merg92, '给出逐字选中文本时精度须 char_exact', {'anchor_precision': 'char_exact'}, sele50(pars28, scre66, grad30[toke88[0]:toke88[1]]) if toke88 else None, None, 'anchor_precision', {'task_id': merg92}))
        page44.append(fiel54(merg92 + '-R1', 'annotation_record', merg92, '批注与原文位置绑定且字段齐全(%d 项)' % len(pin04), {'fields': pin04}, None, None, 'annotation_fields', {'task_id': merg92}))
        page44.append(fiel54(merg92 + '-R2', 'qa_record', merg92, '问答记录可复用: 问题原文一致/答案非空/锚点含页与区间', {'question': prob71}, None, None, 'qa_record', {'task_id': merg92, 'question': prob71}))
    page44 += [fiel54('G-1', 'closed_loop', '*', '七步闭环各有记录且状态可判定', {'steps': curs11}, None, None, 'loop_steps'), fiel54('G-2', 'export', '*', '导出件齐全且非空', {'files': deri03}, None, None, 'export_files'), fiel54('G-3', 'export', '*', 'reading_record.md 覆盖全部批注', {'>=annotations': len(pars28['anns'])}, None, None, 'record_coverage'), fiel54('G-4', 'citation_consistency', '*', 'claim 的 source_id 已声明, quote 命中', {'source_ids': [pool79.get('source_id') for pool79 in pars28['srcs']]}, None, None, 'citation_sources'), fiel54('G-5', 'number_consistency', '*', '答案类 claim 数字在原文中', {'numbers_subset_of': 'doc'}, None, None, 'global_numbers'), fiel54('G-6', 'evidence_anchor', '*', 'doc_text_sha256 与段落文本一致', {'doc_text_sha256': pars28['docsha']}, None, None, 'doc_hash'), fiel54('G-7', 'status', '*', 'status 合法; ok/answered 时无 unresolved', {'allowed': list(zone08)}, None, None, 'status_consistency')]
    return {'schema': 'margin-reader/golden@1', 'case_id': pars28['case_id'], 'source_id': (pars28['srcs'] or [{}])[0].get('source_id') or pars28['docs'].get('source_id'), 'doc_text_sha256': pars28['docsha'], 'generated_at': now(), 'definition': '期望交付内容清单, 由任务要求+材料机械推导, 无预置答案', 'derivation_rule': '选区逐字命中→所在段落, 否则按问题关键词在目标章节取段; 支撑句=段内最优句; 期望数字=该句数字集; 期望锚点=字符区间', 'acceptance': '判定见 references/result-and-anchor-contract.md §8; quote 须在段落文本逐字命中', 'items': page44}

def rank47(lane65, tail29=None):
    try:
        return json.loads(Path(lane65).read_text(encoding='utf-8'))
    except Exception:
        return tail29

def read39(scan90, valu48):
    orde52 = (scan90 or '').lower()
    return sum((1 for tile96 in valu48 if tile96 in orde52))

def sect58(scan90):
    return {tile96.replace(',', '') for tile96 in revi07.findall(scan90 or '')}

def sele50(pars28, scre66, scor74):
    pool79 = pars28['doc'].find(scor74) if scor74 else -1
    return {'source_id': (pars28['srcs'] or [{}])[0].get('source_id') or pars28['docs'].get('source_id'), 'pdf_page': (scre66 or {}).get('page'), 'printed_page': (scre66 or {}).get('printed'), 'paragraph_id': (scre66 or {}).get('paragraph_id'), 'section': (scre66 or {}).get('section'), 'char_start': pool79 if pool79 >= 0 else (scre66 or {}).get('char_start'), 'char_end': pool79 + len(scor74) if pool79 >= 0 and scor74 else (scre66 or {}).get('char_end')}

def stag85(scan90):
    return [pool79.strip() for pool79 in re.split('(?<=[.!?。！？])\\s+', scan90 or '') if pool79.strip()]

def trac72(pars28, merg92):
    return next((tile96 for tile96 in pars28['qa'].get('qa') or [] if isinstance(tile96, dict) and str(tile96.get('task_id')) == str(merg92)), None)

def wind32(pars28, clos43):
    marg25, slic18 = (clos43.get('check'), clos43.get('check_arg') or {})
    merg92 = slic18.get('task_id') or clos43.get('task_id')
    if clos43.get('status') == 'pending' or marg25 == 'unsupported':
        return ('pending', '材料中无法建立期望', clos43.get('note') or '需人工补材料后重跑')
    if marg25 == 'answer_contains':
        pool79 = brie83(pars28, merg92) or {}
        plai95 = clos43['expect'].get('sentence') or clos43['expect'].get('selection') or ''
        stre69 = chun59(' '.join((pool79.get('answer_quotes') or []) + [pool79.get('answer') or '']))
        extr62 = bool(plai95) and chun59(plai95) in stre69
        return ('pass' if extr62 else 'deviation', '命中=%s' % extr62, '' if extr62 else '答案未覆盖期望句')
    if marg25 == 'answer_numbers':
        pool79 = brie83(pars28, merg92) or {}
        plai95 = set(slic18.get('numbers') or [])
        tag37 = sect58(' '.join((pool79.get('answer_quotes') or []) + [pool79.get('answer') or '']))
        if plai95 - tag37:
            return ('deviation', '缺数字 %s' % sorted(plai95 - tag37), '答案未含原文数字')
        if tag37 - sect58(pars28['doc']):
            return ('deviation', '多余数字 %s' % sorted(tag37 - sect58(pars28['doc'])), '数字无法回溯')
        return ('pass', '数字一致(%d)' % len(plai95), '')
    if marg25 == 'anchor_slice':
        pool79 = brie83(pars28, merg92)
        if not pool79 or not pool79.get('quote'):
            return ('missing', '无有效选区', '定位未产出选区')
        prob71, head14, cont19 = (pool79['quote'], pool79.get('char_start'), pool79.get('char_end'))
        poin87 = pars28['doc'][head14:cont19] if isinstance(head14, int) and isinstance(cont19, int) else ''
        if poin87 == prob71:
            return ('pass', 'doc[%s:%s]==quote(%d字)' % (head14, cont19, len(prob71)), '')
        if prob71 in pars28['doc']:
            return ('deviation', '偏移不一致(切片=%r)' % poin87[:40], '锚点偏移需重算')
        return ('deviation', 'quote 未原文命中', '疑似改写原文')
    if marg25 == 'anchor_precision':
        pool79 = brie83(pars28, merg92)
        if not pool79:
            return ('missing', '无选区记录', '定位未执行')
        plai95, tag37 = (clos43['expect']['anchor_precision'], pool79.get('anchor_precision'))
        return ('pass', tag37, '') if tag37 == plai95 else ('deviation', tag37, '精度降级, 需人工确认段落')
    if marg25 == 'annotation_fields':
        head14 = wrap16(pars28, merg92)
        if not head14:
            return ('missing', '无该任务批注', '保存步骤未落盘')
        surf53 = [shee34 for shee34 in pin04 if shee34 not in head14]
        return ('pass', '%d/%d 字段' % (len(pin04) - len(surf53), len(pin04)), '缺 %s' % surf53 if surf53 else '')
    if marg25 == 'qa_record':
        tile96 = trac72(pars28, merg92)
        if not tile96:
            return ('missing', '无问答记录', 'qa_log 未落盘')
        pass20 = []
        if chun59(tile96.get('question')) != chun59(slic18.get('question')):
            pass20.append('问题不一致')
        if not chun59(tile96.get('answer')):
            pass20.append('答案为空')
        if not isinstance((tile96.get('anchor') or {}).get('char_start'), int):
            pass20.append('锚点缺区间')
        return ('pass', '记录完整', '') if not pass20 else ('deviation', ';'.join(pass20), '问答记录不完整')
    if marg25 == 'loop_steps':
        tag37 = [pool79.get('step') for pool79 in pars28['loop']]
        surf53 = [pool79 for pool79 in curs11 if pool79 not in tag37]
        pass20 = [pool79.get('step') for pool79 in pars28['loop'] if pool79.get('status') not in ('done', 'skipped', 'failed', 'partial')]
        if surf53:
            return ('missing', '缺步骤 %s' % surf53, '闭环不完整')
        if pass20:
            return ('deviation', '状态非法 %s' % pass20, '步骤状态不可判定')
        return ('pass', '%d/7 步' % len(tag37), '')
    if marg25 == 'export_files':
        surf53 = [shee34 for shee34 in deri03 if not (pars28['outp'] / shee34).exists() or (pars28['outp'] / shee34).stat().st_size == 0]
        return ('pass', '%d/%d 非空' % (len(deri03) - len(surf53), len(deri03)), '') if not surf53 else ('missing', '缺/空 %s' % surf53, '导出不完整')
    if marg25 == 'record_coverage':
        lane65 = pars28['outp'] / 'reading_record.md'
        scan90 = lane65.read_text(encoding='utf-8', errors='replace') if lane65.exists() else ''
        rang55, unit56 = (len(re.findall('^###\\s+an-', scan90, re.M)), len(pars28['anns']))
        return ('pass', '%d 块 >= %d 条' % (rang55, unit56), '') if rang55 >= unit56 else ('missing', '%d 块 < %d 条' % (rang55, unit56), '导出未覆盖全部批注')
    if marg25 == 'citation_sources':
        link41, pass20 = ({pool79.get('source_id') for pool79 in pars28['srcs']}, [])
        for shif26 in pars28['claims']:
            for reco31 in shif26.get('evidence') or []:
                if reco31.get('source_id') and reco31['source_id'] not in link41:
                    pass20.append('%s:source_id 未声明' % shif26.get('claim_id'))
                if reco31.get('quote') and reco31['quote'] not in pars28['doc']:
                    pass20.append('%s:quote 未命中' % shif26.get('claim_id'))
        return ('pass', '%d 条 claim 可回溯' % len(pars28['claims']), '') if not pass20 else ('deviation', ';'.join(pass20[:4]), '引用不一致')
    if marg25 == 'global_numbers':
        pass20 = ['%s:%s' % (hand22.get('claim_id'), sorted(sect58(hand22.get('statement')) - sect58(pars28['doc']))) for hand22 in pars28['claims'] if hand22.get('kind') == 'answer_span' and sect58(hand22.get('statement')) - sect58(pars28['doc'])]
        return ('pass', '数字均可回溯', '') if not pass20 else ('deviation', ';'.join(pass20[:4]), '出现原文没有的数字')
    if marg25 == 'doc_hash':
        plai95 = clos43['expect'].get('doc_text_sha256')
        tag37 = hashlib.sha256(pars28['doc'].encode('utf-8')).hexdigest()
        if not plai95:
            return ('missing', '无 doc_text_sha256', '锚点未带全文哈希')
        return ('pass', tag37[:16] + '…', '') if tag37 == plai95 else ('deviation', tag37[:16] + '…', '哈希与段落文本不符')
    if marg25 == 'status_consistency':
        issu89, spli93 = (pars28['status'], [pool79 for pool79 in pars28['sels'] if pool79.get('anchor_precision') == 'unresolved'])
        if issu89 not in zone08:
            return ('deviation', str(issu89), 'status 不在允许值内')
        if issu89 in ('ok', 'answered') and spli93:
            return ('deviation', '%s 但有 %d unresolved' % (issu89, len(spli93)), '状态与证据不符')
        if issu89 == 'answered' and (not pars28['sels']):
            return ('deviation', 'answered 但无答案', '状态与产物不符')
        return ('pass', str(issu89), '')
    return ('pending', '未实现判定', '需补实现')

def wrap16(pars28, merg92):
    return next((head14 for head14 in pars28['anns'] if str(head14.get('task_id')) == str(merg92)), None)
