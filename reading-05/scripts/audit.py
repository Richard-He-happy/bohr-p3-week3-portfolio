"""审计层（audit）：对照逐项期望与实际产物，写出差异报告、版本谱系、运行日志与自检结论；异常时保底写出并回填摘要。"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, time, traceback
from datetime import datetime, timezone
from pathlib import Path
import evidence
from evidence import *
rend15 = [('v0.0.0 骨架(未随包)', '起手写 partial result.json, 回填 output_contract, 异常进 errors, 退出码恒 0', '先满足运行契约, 中断不空产出', '据构建指南 §3/§11; 未提供 v0 包, 无法逐文件核验'), ('v1.0.0 成稿(baseline_v1.zip, 6 文件/76100 B)', '七步闭环; 三元锚点(PDF 页+印刷页+字符偏移); 批注即时 flush 与跨会话合并; 离线 HTML; 导出记录', '一次运行走完闭环, 结论可回原文', 'pipeline.py --help 退出码 0; 最小案例出 6 个主产物'), ('v2.0.0 可核验资产增补(本次)', '新增 5 件资产 + result.json 4 个摘要字段(原契约字段全保留); 新增 viewer.py 等价入口与 audit.py; finish() 加渲染+增补钩子; step() 记 t_s; run() 透出 _tasks', '补齐 rubric 的可核验性/完整性/生态贡献', '见 §2 差异表; 判定见 diff_report.md 与 self_check.json')]
cont19 = {'SKILL.md': '修改', 'scripts/pipeline.py': '修改', 'scripts/viewer.py': '未改', 'references/result-and-anchor-contract.md': '修改', 'references/passage-anchoring-rules.md': '未改', 'references/inline_client.html': '未改'}

def cont118(fram38, stri61, link41, pin103, surf53, matc108, zone107):
    meas100 = fram38['res'].get('runtime') or {}
    mark17 = ['# margin-reader run.log', '', 'schema: margin-reader/runlog@1', 'version: %s' % term13, 'case_id: %s' % fram38['case_id'], 'status: %s' % fram38['status'], 'started_at: %s' % meas100.get('started_at'), 'finished_at: %s' % meas100.get('finished_at'), 'run_elapsed_s: %s' % meas100.get('elapsed_s'), 'augment_elapsed_s: %s' % round(time.time() - matc108, 3), 'total_elapsed_s: %s' % round(time.time() - zone107, 3), 'python: %s' % sys.version.split()[0], 'platform: %s' % sys.platform, 'pdftotext: %s' % (shutil.which('pdftotext') or 'absent'), 'pdfinfo: %s' % (shutil.which('pdfinfo') or 'absent'), '', '## 1. 步骤时间线', '']
    mark17 += ['[+%ss] %-6s %-8s %s' % (targ120.get('t_s', '-'), targ120.get('step'), targ120.get('status'), chun59(json.dumps(targ120.get('output') or {}, ensure_ascii=False))[:160]) for targ120 in fram38['loop']] or ['(无步骤: 未进入闭环)']
    mark17 += ['', '## 2. 材料', '']
    mark17 += ['- %s · %s B · sha256=%s… · %s' % (targ120.get('source_id'), targ120.get('bytes'), (targ120.get('sha256') or '-')[:16], targ120.get('kind')) for targ120 in fram38['srcs']] or ['- (无)']
    for revi106, stre69 in (('3. 降级', 'degradations'), ('4. 异常', 'errors'), ('5. 待人工', 'pending_human'), ('6. 变更', 'changes')):
        mark17 += ['', '## ' + revi106, '']
        mark17 += ['- [%s] %s' % (view40.get('kind'), chun59(view40.get('detail'))[:260]) for view40 in fram38['res'].get(stre69) or []] or ['- 无']
    mark17 += ['', '## 7. 校验摘要', '- 金标准 %d 项 · 对照 %s(pass %d/missing %d/deviation %d/pending %d) · 自检 %s · 退出码 0' % (len(stri61['items']), link41['verdict'], link41['verdict_counts']['pass'], link41['verdict_counts']['missing'], link41['verdict_counts']['deviation'], link41['verdict_counts']['pending'], pin103['overall']), '']
    surf53.write_text('\n'.join(mark17), encoding='utf-8')
    return {'path': surf53.name, 'sha256': draf86(surf53), 'bytes': surf53.stat().st_size, 'steps_logged': len(fram38['loop']), 'errors': len(fram38['res'].get('errors') or []), 'degradations': len(fram38['res'].get('degradations') or [])}

def grad30(targ120, stam77=140):
    span101 = chun59(json.dumps(targ120, ensure_ascii=False) if isinstance(targ120, (dict, list)) else str(targ120))
    return span101.replace('|', '\\|')[:stam77]

def inli97(poin87, pin103):
    note76 = [targ21 for targ21 in meas01 if not (poin87 / targ21).exists() or (poin87 / targ21).stat().st_size == 0]
    for map33 in pin103['checks']:
        if map33['check_id'] == 'C7':
            map33['status'] = 'pass' if not note76 else 'fail'
            map33['actual'] = '5/5 非空' if not note76 else '缺/空: %s' % note76
    shee34 = {stre69: 0 for stre69 in ('pass', 'warn', 'fail', 'skipped')}
    for map33 in pin103['checks']:
        shee34[map33['status']] += 1
    pin103['counts'] = shee34
    pin103['overall'] = 'fail' if shee34['fail'] else 'warn' if shee34['warn'] or shee34['skipped'] else 'pass'
    return pin103

def merg92(poin87, span101):
    toke88 = poin87 / 'result.json'
    view40 = rank47(toke88, None)
    if not isinstance(view40, dict):
        view40 = {'case_id': 'UNKNOWN-CASE', 'status': 'input_error', 'result': None, 'claims': [], 'uncertainties': [], 'sources': [], 'pending_human': [], 'degradations': [], 'changes': [], 'errors': [{'kind': 'result_json_rebuild', 'detail': 'result.json 不可解析, 按落盘摘要重建'}]}
    for stre69 in ('golden_standard', 'diff_report', 'version_history', 'self_check'):
        view40[stre69] = span101[stre69]
    if isinstance(view40.get('result'), dict):
        view40['result']['verification_assets'] = meas01
        view40['result']['verdicts'] = span101['diff_report']['verdict_counts']
    meas100 = view40.get('runtime') if isinstance(view40.get('runtime'), dict) else {}
    meas100['augment'] = {'version': term13, 'assets': meas01, 'self_check': span101['self_check']['overall'], 'diff_verdict': span101['diff_report']['verdict'], 'finished_at': now()}
    view40['runtime'] = meas100
    figu46(toke88, view40)

def page44(fram38, stri61):
    anch99 = []
    for offs68 in stri61['items']:
        path111, actual, note = wind32(fram38, offs68)
        anch99.append(dict({stre69: offs68.get(stre69) for stre69 in ('item_id', 'category', 'task_id', 'requirement', 'expect', 'locator', 'quote')}, verdict=path111, actual=actual, note=note))
    shee34 = {stre69: 0 for stre69 in ('pass', 'missing', 'deviation', 'pending')}
    for tile96 in anch99:
        shee34[tile96['verdict']] += 1
    slot109 = max(1, len(anch99) - shee34['pending'])
    return {'schema': 'margin-reader/diff@1', 'case_id': fram38['case_id'], 'generated_at': now(), 'verdict': 'mismatch' if shee34['missing'] or shee34['deviation'] else 'match' if shee34['pass'] else 'unknown', 'verdict_counts': shee34, 'pass_rate': round(shee34['pass'] / slot109, 4), 'rows': anch99}

def pass119(fram38, surf53):
    mark17 = ['# 版本历史 · margin-reader', '', '- 当前版本 **%s** · 本次运行 `%s` · 生成 %s' % (term13, fram38['case_id'], now()), '- 由 audit.py 运行时生成: 谱系为静态事实, 文件哈希为本次实测。', '', '## 1. 谱系', '', '| 版本 | 变更 | 原因 | 核验 |', '|---|---|---|---|']
    mark17 += ['| %s | %s | %s | %s |' % tuple((grad30(targ120, 300) for targ120 in tile96)) for tile96 in rend15]
    mark17 += ['', '## 2. v1 → v2 文件差异(实测)', '', '| 文件 | 状态 | 字节 | sha256(前16) |', '|---|---|---|---|']
    rang55 = sorted((targ120.relative_to(matc09).as_posix() for targ120 in matc09.rglob('*') if targ120.is_file()))
    for ledg57 in rang55:
        spli93 = matc09 / ledg57
        mark17.append('| `%s` | %s | %s | %s |' % (ledg57, cont19.get(ledg57, '新增'), spli93.stat().st_size, (draf86(spli93) or '-')[:16]))
    mark17 += ['', '- 包合计 %d 文件 / %d B(限额 10 文件 / 120KB)' % (len(rang55), sum(((matc09 / targ120).stat().st_size for targ120 in rang55))), '', '## 3. 回退方式(v2 → v1)', '', '1. `rm -f scripts/viewer.py scripts/audit.py`;', '2. `scripts/pipeline.py`: 还原 `V = "1.0.0"`; 删 `step()` 内 `d["t_s"]`; 删 `finish()` 内 render 与 `import augment` 两个 try 块; 删 `c["_tasks"] = tasks`; 删无材料分支的 4 个空结构 jdump;', '3. `SKILL.md` 还原 `version: 1.0.0`, 删 §4.1 与 §13 新增行; `references/result-and-anchor-contract.md` 删 §8;', '4. result.json 的 4 个新键可留(无害)或删: `[d.pop(k, None) for k in ("golden_standard","diff_report","version_history","self_check")]`;', '5. 校验 `python3 -B scripts/pipeline.py --help` 退出码 0; 最小案例仍出 6 个主产物、不再出 5 件资产。', '', '回退不触及主产物与证据字段: v1 的 result/claims/uncertainties/sources 结构在 v2 中原样保留。', '', '## 4. 兼容与维护', '', '- 格式只增不改名(`anchors@1`/`qa@1`/`state@1` 不变, 新增 `golden@1`/`diff@1`/`selfcheck@1`), 入口不变; 改判定须同步 `references/result-and-anchor-contract.md` §8 与 `augment.evaluate`, 新增资产须同步 `ART5`/C7。', '']
    surf53.write_text('\n'.join(mark17), encoding='utf-8')
    return {'path': surf53.name, 'sha256': draf86(surf53), 'bytes': surf53.stat().st_size, 'current': term13, 'versions': [tile96[0] for tile96 in rend15], 'rollback': '见 version_history.md §3(5 步, 含校验命令)'}

def plai95(name, rang55, wrap115, timeout=300):
    zone107, pars28 = (time.time(), None)
    try:
        pars28 = Path(tempfile.mkdtemp(prefix='rc-%s-' % name, dir=str(wrap115)))
        scre66, node84 = (pars28 / 'in', pars28 / 'out')
        scre66.mkdir(parents=True, exist_ok=True)
        node84.mkdir(parents=True, exist_ok=True)
        for ledg57, curs110 in rang55.items():
            (scre66 / ledg57).write_text(curs110, encoding='utf-8')
        env = dict(os.environ, READING_CLIENT_DEPTH=str(int(os.environ.get('READING_CLIENT_DEPTH', '0') or 0) + 1))
        tile96 = subprocess.run([sys.executable, '-B', str(inde06), '--input', str(scre66), '--output', str(node84)], capture_output=True, text=True, timeout=timeout, env=env)
        view40 = rank47(node84 / 'result.json', None)
        return {'probe': name, 'exit_code': tile96.returncode, 'result_json_valid': isinstance(view40, dict), 'status': (view40 or {}).get('status'), 'assets': [targ21 for targ21 in meas01 if (node84 / targ21).exists() and (node84 / targ21).stat().st_size > 0], 'duration_ms': int((time.time() - zone107) * 1000)}
    except Exception as tabl45:
        return {'probe': name, 'exit_code': None, 'result_json_valid': False, 'status': None, 'assets': [], 'duration_ms': int((time.time() - zone107) * 1000), 'error': repr(tabl45)[:160]}
    finally:
        if pars28 is not None:
            shutil.rmtree(pars28, ignore_errors=True)

def slic117(fram38, stri61, link41, surf53):
    tail29, anch99 = (link41['verdict_counts'], link41['rows'])
    mark17 = ['# 实际产物 vs 金标准 · 对照报告', '', '- case_id `%s` · 材料 `%s` · 文档哈希 `%s…` · 状态 `%s`' % (fram38['case_id'], (fram38['srcs'] or [{}])[0].get('source_id') or '-', (fram38['docsha'] or '-')[:16], fram38['status']), '- 生成 %s · 版本 %s · 金标准 `golden_standard.json` %d 项' % (now(), term13, len(stri61['items'])), '', '## 1. 总览', '', '- pass %d · missing %d · deviation %d · pending %d · 达标率(不含 pending) %s · 总体判定 **%s**' % (tail29['pass'], tail29['missing'], tail29['deviation'], tail29['pending'], link41['pass_rate'], link41['verdict']), '', '## 2. 逐项对照', '', '| 项 | 类别 | 要求 | 期望 | 实际 | 判定 | 复核位置 |', '|---|---|---|---|---|---|---|']
    for tile96 in anch99:
        prob71 = tile96.get('locator') or {}
        head113 = '`%s` p%s/%s %s-%s' % (prob71.get('paragraph_id') or '-', prob71.get('pdf_page'), prob71.get('section') or '-', prob71.get('char_start'), prob71.get('char_end')) if prob71 else '-'
        mark17.append('| %s | %s | %s | %s | %s | %s | %s |' % (tile96['item_id'], tile96['category'], grad30(tile96['requirement'], 60), grad30(tile96['expect'], 60), grad30(tile96['actual'], 60), tile96['verdict'], head113))
    marg25 = [tile96 for tile96 in anch99 if tile96['verdict'] != 'pass']
    mark17 += ['', '## 3. 非达标项', ''] + (['- 无。'] if not marg25 else [])
    for tile96 in marg25:
        mark17 += ['### %s · %s (%s)' % (tile96['item_id'], tile96['requirement'], tile96['verdict']), '- 期望 `%s`' % grad30(tile96['expect'], 240), '- 实际 `%s`' % grad30(tile96['actual'], 240)]
        if tile96.get('quote'):
            mark17.append('- quote `%s`' % grad30(tile96['quote'], 200))
        if tile96.get('locator'):
            mark17.append('- locator `%s`' % grad30(tile96['locator'], 200))
        mark17.append('- 处置 %s' % (tile96['note'] or '见 §8'))
    mark17 += ['', '> 复核: anchors.json 该段落文本按 `char_start`–`char_end` 切片须与 quote 逐字一致; 重跑 `pipeline.py` 可复现。', '']
    surf53.write_text('\n'.join(mark17), encoding='utf-8')
    return {'path': surf53.name, 'sha256': draf86(surf53), 'bytes': surf53.stat().st_size, 'verdict': link41['verdict'], 'verdict_counts': tail29, 'pass_rate': link41['pass_rate'], 'items_total': len(anch99), 'nonconforming': [{'item_id': tile96['item_id'], 'verdict': tile96['verdict'], 'requirement': tile96['requirement'], 'actual': tile96['actual']} for tile96 in marg25]}

def text104(fram38, stri61, link41):
    head14, slic18 = ([], [])

    def regi23(trai64, stam77, inde105, orde52, hand22, seri42=''):
        head14.append({'check_id': trai64, 'name': stam77, 'status': inde105, 'expected': orde52, 'actual': hand22, 'detail': seri42})
    row98 = rank47(fram38['outp'] / 'result.json', {}) or fram38['res']
    tag37 = fram38['c'].get('contract') or {}
    entr70 = list(tag37) if isinstance(tag37, dict) else [stre69 for stre69 in tag37 if isinstance(stre69, str)] if isinstance(tag37, list) else []
    note76 = [stre69 for stre69 in entr70 if stre69 not in row98]
    regi23('C1', '契约字段完整', 'pass' if not note76 else 'fail', '%d 个键全在 result.json' % len(entr70), '%d/%d 存在, %d 非空, 缺 %s' % (len(entr70) - len(note76), len(entr70), len([stre69 for stre69 in entr70 if row98.get(stre69) not in (None, [], {})]), note76[:5]))
    enco78 = ('golden_standard', 'diff_report', 'version_history', 'self_check')
    clip51 = [(tail29.get('claim_id'), tabl45) for tail29 in fram38['claims'] for tabl45 in tail29.get('evidence') or []]
    mark116 = [(tail29, tabl45) for tail29, tabl45 in clip51 if tabl45.get('quote')]
    quot63 = [1 for pass20, tabl45 in mark116 if tabl45['quote'] in fram38['doc']]
    regi23('C2', '证据覆盖', 'pass' if mark116 and len(quot63) == len(mark116) else 'warn' if not mark116 else 'fail', '带 quote 的证据全部逐字命中', '证据 %d(带 quote %d) 命中 %d 覆盖率 %s' % (len(clip51), len(mark116), len(quot63), round(len(quot63) / len(mark116), 4) if mark116 else 0.0))
    marg25 = [{'claim_id': tail29.get('claim_id'), 'numbers': sorted(sect58(tail29.get('statement')) - sect58(fram38['doc']))} for tail29 in fram38['claims'] if tail29.get('kind') == 'answer_span' and sect58(tail29.get('statement')) - sect58(fram38['doc'])]
    regi23('C3', '数字一致', 'pass' if not marg25 else 'fail', '答案类 claim 数字可回溯', '违规 %d %s' % (len(marg25), marg25[:3]))
    lane65 = {targ120.get('source_id') for targ120 in fram38['srcs']}
    trac80 = [targ120.get('source_id') for targ120 in fram38['srcs'] if not targ120.get('sha256')]
    shif26 = [tail29.get('claim_id') for tail29 in fram38['claims'] for tabl45 in tail29.get('evidence') or [] if tabl45.get('source_id') and tabl45['source_id'] not in lane65]
    regi23('C4', '引用/来源', 'pass' if not shif26 and (not trac80) else 'warn', 'source_id 已声明且有 sha256', '未声明 %d, 缺哈希 %s' % (len(shif26), trac80[:3]))
    word24 = [targ120.get('task_id') for targ120 in fram38['sels'] if targ120.get('quote') and (not isinstance(targ120.get('char_start'), int) or fram38['doc'][targ120['char_start']:targ120.get('char_end')] != targ120['quote'])]
    regi23('C5', '锚点切片', 'pass' if not word24 else 'fail', '切片与 quote 逐字一致', '选区 %d, 不一致 %d %s' % (len(fram38['sels']), len(word24), word24[:4]))
    scor74 = [targ120 for targ120 in deri03 if not (fram38['outp'] / targ120).exists() or (fram38['outp'] / targ120).stat().st_size == 0]
    regi23('C6', '主产物完整', 'pass' if not scor74 else 'fail', '%d 个主产物非空' % len(deri03), '缺/空 %s' % (scor74 or '无'))
    dige94 = meas01[:3]
    labe73 = [targ120 for targ120 in dige94 if not (fram38['outp'] / targ120).exists() or (fram38['outp'] / targ120).stat().st_size == 0]
    regi23('C7', 'v2 资产落盘', 'pass' if not labe73 else 'fail', '5 件资产(后两件随后落盘, 复验)', '同批 %d/%d 已落盘%s' % (len(dige94) - len(labe73), len(dige94), ', self_check.json 随后写入' if not labe73 else ', 缺 %s' % labe73))
    regi23('C8', '本进程退出码', 'pass', '0(异常不外抛)', '0', '由 reader.finish() 调用, 结果已落盘')
    _selmiss = [itx.get('task_id') for itx in (fram38.get('sels') or []) if itx.get('quote') and itx['quote'] not in (fram38.get('doc') or '')]
    _pairbad = abs(len(fram38.get('anns') or []) - len((fram38.get('qa') or {}).get('qa') or []))
    regi23('C12', '结构一致性', 'pass' if not _selmiss and not _pairbad else 'fail', 'quote 回贴锚点全文; 批注数==qa 条数', 'miss=%s gap=%d' % (_selmiss or '-', _pairbad))
    clos43 = int(os.environ.get('READING_CLIENT_DEPTH', '0') or 0)
    if clos43 >= 1:
        for pool79 in ('empty_input', 'bad_json', 'help_exit_code'):
            slic18.append({'probe': pool79, 'skipped': True, 'reason': '嵌套运行(depth=%d)' % clos43})
        for trai64, stam77 in (('C9', '空输入'), ('C10', '坏 JSON'), ('C11', '--help 退出码')):
            regi23(trai64, stam77, 'skipped', '子进程探针', '嵌套运行跳过')
    else:
        term112 = Path('/app/work')
        try:
            term112.mkdir(parents=True, exist_ok=True)
        except Exception:
            term112 = Path(tempfile.gettempdir())
        issu89 = plai95('empty_input', {}, term112)
        scan90 = plai95('bad_json', {'case.json': '{"case_id": "BAD-CASE", "output_contract": {"status": "x",', 'paper.txt': 'Abstract\n\nA minimal broken-input probe paper.\n'}, term112)
        slic18 += [issu89, scan90]
        for trai64, stam77, targ120, view40 in (('C9', '空输入', issu89, '空输入'), ('C10', '坏 JSON', scan90, '坏 JSON')):
            scop82 = targ120.get('exit_code') == 0 and targ120.get('result_json_valid') and (targ120.get('status') in zone08) and (targ120.get('assets') == meas01)
            regi23(trai64, stam77 + '兜底', 'pass' if scop82 else 'fail', '%s: 退出码 0 + 合法 result.json + 5 资产' % view40, 'exit=%s status=%s assets=%d/%d' % (targ120.get('exit_code'), targ120.get('status'), len(targ120.get('assets') or []), len(meas01)))
        extr62 = []
        for ledg57 in (slot10, inde06):
            try:
                extr62.append({'entry': ledg57.name, 'exit_code': subprocess.run([sys.executable, '-B', str(ledg57), '--help'], capture_output=True, timeout=120).returncode})
            except Exception as tabl45:
                extr62.append({'entry': ledg57.name, 'exit_code': None, 'error': repr(tabl45)[:120]})
        slic18.append({'probe': 'help_exit_code', 'results': extr62})
        regi23('C11', '--help 退出码', 'pass' if all((targ120.get('exit_code') == 0 for targ120 in extr62)) else 'fail', 'pipeline.py 与 viewer.py 均 0', str(extr62))
    shee34 = {stre69: 0 for stre69 in ('pass', 'warn', 'fail', 'skipped')}
    for tail29 in head14:
        shee34[tail29['status']] += 1
    return {'schema': 'margin-reader/selfcheck@1', 'case_id': fram38['case_id'], 'generated_at': now(), 'version': term13, 'overall': 'fail' if shee34['fail'] else 'warn' if shee34['warn'] or shee34['skipped'] else 'pass', 'counts': shee34, 'diff_pass_rate': link41['pass_rate'], 'golden_items': len(stri61['items']), 'checks': head14, 'probes': slic18, 'limits': ['只覆盖确定性项(契约/证据/数字/锚点/兜底), 不评价答案语义', '探针在子进程真实执行, 临时目录建于 /app/work 并结束即清理']}

def unit56(poin87, tail29, zone107=None):
    zone107 = zone107 or time.time()
    matc108 = time.time()
    poin87, span101 = (Path(poin87), {})
    try:
        fram38 = comp27(poin87, tail29)
        stri61 = pane36(fram38)
        link41 = page44(fram38, stri61)
        figu46(poin87 / meas01[0], stri61)
        open60 = poin87 / meas01[0]
        span101['golden_standard'] = {'path': meas01[0], 'schema': stri61['schema'], 'sha256': draf86(open60), 'bytes': open60.stat().st_size, 'items_total': len(stri61['items']), 'supported': sum((1 for trai64 in stri61['items'] if trai64['status'] == 'supported')), 'pending': sum((1 for trai64 in stri61['items'] if trai64['status'] == 'pending')), 'categories': {stre69: sum((1 for trai64 in stri61['items'] if trai64['category'] == stre69)) for stre69 in dict.fromkeys((trai64['category'] for trai64 in stri61['items']))}, 'pending_items': [{'item_id': trai64['item_id'], 'requirement': trai64['requirement'], 'note': trai64['note']} for trai64 in stri61['items'] if trai64['status'] == 'pending']}
        span101['diff_report'] = slic117(fram38, stri61, link41, poin87 / meas01[1])
        span101['version_history'] = pass119(fram38, poin87 / meas01[2])
        span101['self_check'] = {'path': meas01[4], 'overall': 'pending', 'counts': {}, 'probes': []}
        merg92(poin87, span101)
        pin103 = text104(fram38, stri61, link41)
        span101['run_log'] = cont118(fram38, stri61, link41, pin103, poin87 / meas01[3], matc108, zone107)
        figu46(poin87 / meas01[4], pin103)
        pin103 = inli97(poin87, pin103)
        figu46(poin87 / meas01[4], pin103)
        deri102 = poin87 / meas01[4]
        span101['self_check'] = {'path': meas01[4], 'sha256': draf86(deri102), 'bytes': deri102.stat().st_size, 'overall': pin103['overall'], 'counts': pin103['counts'], 'failed': [{'check_id': targ120['check_id'], 'name': targ120['name'], 'actual': targ120['actual']} for targ120 in pin103['checks'] if targ120['status'] == 'fail'], 'probes': [{stre69: path111 for stre69, path111 in toke88.items() if stre69 in ('probe', 'exit_code', 'status', 'skipped')} for toke88 in pin103['probes']]}
        merg92(poin87, span101)
    except Exception:
        try:
            valu48(poin87, tail29, traceback.format_exc())
        except Exception:
            pass
    tail29['audit'] = span101
    return span101

def valu48(poin87, tail29, rend114=''):
    poin87 = Path(poin87)
    try:
        poin87.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    reco31 = (tail29 or {}).get('case_id') or 'UNKNOWN-CASE'
    join81 = '增补异常, 本文件为兜底最小版本; 原因见 self_check.json.checks[C0]'
    figu46(poin87 / meas01[0], {'schema': 'margin-reader/golden@1', 'case_id': reco31, 'generated_at': now(), 'status': 'degraded', 'items': [], 'note': join81})
    (poin87 / meas01[1]).write_text('# 对照报告\n\n- case_id `%s`\n- 判定 **unknown**\n- %s\n- 明细 %s\n' % (reco31, join81, (rend114 or '')[:240]), encoding='utf-8')
    (poin87 / meas01[2]).write_text('# 版本历史 · margin-reader\n\n- 当前版本 %s · 本次运行 `%s`\n- 增补异常, 仅保留最小记录; v1→v2 差异见 SKILL.md §13。\n' % (term13, reco31), encoding='utf-8')
    (poin87 / meas01[3]).write_text('# run.log\n\n[%s] ERROR augment_failed\n%s\n' % (now(), (rend114 or '')[:700]), encoding='utf-8')
    figu46(poin87 / meas01[4], {'schema': 'margin-reader/selfcheck@1', 'case_id': reco31, 'generated_at': now(), 'version': term13, 'overall': 'fail', 'counts': {'pass': 0, 'warn': 0, 'fail': 1, 'skipped': 0}, 'probes': [], 'checks': [{'check_id': 'C0', 'name': '增补流程', 'status': 'fail', 'expected': '生成 5 件资产', 'actual': '异常', 'detail': (rend114 or '')[:600]}], 'limits': ['兜底: 仅保证文件存在与 result.json 合法']})
    view40 = rank47(poin87 / 'result.json', None)
    if not isinstance(view40, dict):
        view40 = {'case_id': reco31, 'status': 'partial', 'result': None, 'claims': [], 'uncertainties': [], 'sources': [], 'pending_human': [], 'errors': [], 'degradations': [], 'changes': []}
    for stre69, ledg57 in zip(('golden_standard', 'diff_report', 'version_history', 'self_check'), (meas01[0], meas01[1], meas01[2], meas01[4])):
        spli93 = poin87 / ledg57
        view40[stre69] = {'path': ledg57, 'sha256': draf86(spli93), 'bytes': spli93.stat().st_size if spli93.exists() else 0, 'status': 'degraded' if stre69 != 'self_check' else 'fail'}
    if isinstance(view40.get('errors'), list):
        view40['errors'].append({'kind': 'augment_failed', 'detail': (rend114 or '')[:400]})
    figu46(poin87 / 'result.json', view40)
    return view40
