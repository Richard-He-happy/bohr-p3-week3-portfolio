"""main.py - graphical-abstract workbench: init | show | check | build.

init scans /input into work/index.json and drops a partial result.json first.
show prints every indexed paragraph together with its locator so quotes can be
copied verbatim. check audits work/plan.json: four panel roles, verbatim evidence,
and figure numbers that do not occur in their own quote. build renders the layered
SVG, the vector PDF and a preview PNG, writes content_map.json plus
compliance_checks.json, and finalises result.json with all contract fields.
Pure standard library, no network, no CWD dependence; every subcommand exits 0 and
leaves a syntactically valid result.json even when the input is broken."""
import argparse, hashlib, json, re, shutil, subprocess, sys, time, traceback, zipfile
from pathlib import Path
_DESIGN_NOTES = """
Field notes that matter when maintaining this workbench.

scan_materials() sniffs the first bytes of each input, tags every file as pdf,
text or binary, and gives each paragraph a stable locator plus its material
sha1. verify_evidence() compares quotes after normalising curly quotes and soft
hyphens, and reports a hit found at another position as relocated; the sentence
is the evidence, the locator is only its address. audit_items() rejects an item
when a number printed in the figure never occurs in the quote backing it. The
output contract is mapped through a synonym vocabulary because case key names
vary; unmatched keys surface in runtime.unmatched_contract_fields instead of
silently disappearing. compose_figure() is the single layout authority: a flat
display list of rectangles, lines and text runs sorted by named layer, with
font-ladder shrinking before any item is dropped. Emit paths share that list:
SVG keeps text editable and one group per layer, PDF scales it into a single
page with base-14 fonts and a CID fallback, and PNG falls back to pngkit (the
stdlib rasteriser) so a real bitmap with a valid IHDR always exists.
"""
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import render_kit as kit
    KIT_ERR = ''
except Exception as exc:
    kit, KIT_ERR = (None, str(exc))
DEFAULT_INPUT, DEFAULT_WORK, DEFAULT_OUTPUT = ('/input', '/app/work', '/app/output')
ROLE_ORDER = ('problem', 'method', 'results', 'implication')
CONTRACT_ALIASES = ('output_contract', 'outputcontract', 'contract', 'output_fields', 'required_outputs')
FIELD_HINTS = [(a, b.split(',')) for a, b in (x.split('=') for x in 'content_map=content_map,element_map,mapping,provenance|compliance_checks=compliance,audit,export_check|exceptions=exception,deviation,issue,limitation|sources=sources,references|editable_source=editable,svg,vector,source|export_artifact=export,artifact,pdf,png,deliverable|figure_caption=caption,legend|problem=problem,question|method=method,approach|results=result,finding|implication=implication,conclusion,takeaway|uncertainty=uncertaint'.split('|'))]

def fold_ws(s):
    s = re.sub('[\\u2018\\u2019]', "'", str(s or ''))
    return re.sub('\\s+', ' ', re.sub('[\\u201c\\u201d]', '"', s).replace('\xa0', ' ')).strip()

def compact_key(s):
    return re.sub('\\s+', '', re.sub('-\\s*\\n\\s*', '', str(s or ''))).lower()

def dump_json(p, o):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def read_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))

def seek_key(o, names, d=0):
    if d > 4 or not isinstance(o, (dict, list)):
        return None
    if isinstance(o, dict):
        for k, v in o.items():
            if str(k).lower().replace('-', '_').strip() in names:
                return v
        o = list(o.values())
    return next((r for r in (seek_key(v, names, d + 1) for v in o[:25]) if r is not None), None)

def read_case_files(ind):
    ind, d = (Path(ind), {'case': {}, 'case_path': None, 'task_text': '', 'errors': []})
    for name in ('case.json', 'task.md'):
        f = ind / name
        if not f.is_file():
            c = sorted(ind.rglob('*' + name[4:])) if ind.exists() else []
            f = c[0] if c else None
        if f is None:
            continue
        try:
            if name == 'case.json':
                d['case'], d['case_path'] = (read_json(f), str(f))
            else:
                d['task_text'] = f.read_text(encoding='utf-8-sig', errors='replace')
        except Exception as e:
            d['errors'].append(f'{name} unreadable: {e}')
    return d

def scan_materials(ind):
    """Walk /input; text and PDF become locator-tagged paragraphs."""
    ind, mats, chunks = (Path(ind), [], [])
    for p in sorted((x for x in ind.rglob('*') if x.is_file())) if ind.exists() else []:
        low = p.name.lower()
        if low in ('case.json', 'task.md') or (low.startswith('case') and low.endswith('.json')):
            continue
        rel, sid = (str(p.relative_to(ind)), f'm{len(mats) + 1}')
        head = p.open('rb').read(512) if p.stat().st_size else b''
        kind = 'pdf' if head[:4] == b'%PDF' else 'binary' if b'\x00' in head else 'text'
        rec = {'sid': sid, 'name': rel, 'kind': kind, 'bytes': p.stat().st_size, 'sha1': hashlib.sha1(p.read_bytes()).hexdigest()[:16], 'chunks': 0, 'method': 'utf-8 text'}
        ps = []
        try:
            if kind == 'text':
                txt = p.read_text(encoding='utf-8-sig', errors='replace')
                sep = '\\n' if p.suffix.lower() in ('.csv', '.tsv') else '\\n\\s*\\n'
                ps = [{'sid': sid, 'locator': f'para.{i + 1}', 'text': b.strip()} for i, b in enumerate(re.split(sep, txt)) if len(b.strip()) > 2]
            elif kind == 'pdf':
                ps, rec['method'] = pdf_paragraphs(p, sid)
            else:
                rec['method'] = f'{kind}: not parsed - convert to PDF/CSV, never invent content'
            for q in ps:
                q['source'] = rel
        except Exception as e:
            ps, rec['method'] = ([], f'extraction failed: {e}')
        rec['chunks'] = len(ps)
        mats.append(rec)
        chunks += ps
    return {'materials': mats, 'paragraphs': chunks}

def pdf_paragraphs(p, sid):
    exe = shutil.which('pdftotext')
    try:
        r = subprocess.run([exe, '-layout', str(p), '-'], capture_output=True, timeout=90) if exe else None
        txt = r.stdout.decode('utf-8', 'replace') if r else ''
        if txt.strip():
            return ([{'sid': sid, 'source': p.name, 'locator': f'p.{pi + 1} b{k + 1}', 'text': b.strip()} for pi, pg in enumerate(txt.split('\x0c')) for k, b in enumerate(re.split('\\n\\s*\\n', pg)) if len(b.strip()) > 1], 'pdftotext -layout; locator = p.<page> b.<block>')
    except Exception:
        pass
    return ([], 'PDF text not extracted: read the page and quote it, never invent text')

def verify_evidence(proofs, chunks, full):
    proofs = proofs or {}
    q, dec = (fold_ws(proofs.get('quote')), fold_ws(proofs.get('locator')))
    if len(q) < 4:
        return {'status': 'no_quote', 'locator': dec, 'source': proofs.get('source'), 'note': 'quote shorter than 4 characters'}
    cands = [p for p in chunks if compact_key(q) in compact_key(p['text'])]
    for p in cands:
        if dec and dec == p['locator']:
            return {'status': 'verified', 'locator': p['locator'], 'source': p['source'], 'quote': q, 'note': ''}
    if cands:
        p = cands[0]
        return {'status': 'verified' if not dec else 'relocated', 'locator': p['locator'], 'source': p['source'], 'quote': q, 'note': '' if not dec else f"'{dec}' did not hold it; corrected to '{p['locator']}'"}
    return {'status': 'unverified', 'locator': dec, 'source': proofs.get('source'), 'quote': q, 'note': 'no indexed paragraph contains this text character-for-character'}

def audit_items(plan, chunks):
    """Annotate every item with _m (evidence verify_evidence) and _eid; return counts + problems."""
    full, faults, n, ok = ({}, [], 0, 0)
    for p in chunks:
        full[p['source']] = full.get(p['source'], '') + compact_key(p['text'])
    for pi, pn in enumerate(plan.get('panels') or []):
        pid = str(pn.get('id') or f'P{pi + 1}') if isinstance(pn, dict) else f'P{pi + 1}'
        for ii, it in enumerate((pn.get('items') if isinstance(pn, dict) else None) or []):
            if not isinstance(it, dict):
                continue
            n += 1
            eid = it['_eid'] = str(it.get('id') or f'{pid}-I{ii + 1}')
            m = it['_m'] = verify_evidence(it.get('evidence'), chunks, full)
            bad = sorted({x for x in re.findall('\\d+(?:[.,]\\d+)?', fold_ws(' '.join((str(it.get(k) or '') for k in ('label', 'value', 'detail'))))) if x not in (m.get('quote') or '')})
            if bad:
                faults.append(f'{eid}: number(s) {bad} not in its quote')
            if m['status'] not in ('verified', 'relocated'):
                faults.append(f"{eid}: {m['status']} - {m['note']}")
            ok += m['status'] in ('verified', 'relocated')
    return (n, ok, faults)

def salvage_plan(index, case, task_text):
    sents = [(s, p) for p in index.get('paragraphs') or [] if not fold_ws(p['text']).startswith(('#', '|')) for s in re.split('(?<=[.!?])\\s+', fold_ws(p['text'])) if 60 <= len(s) <= 320]
    used, panels = (set(), [])
    for role in ROLE_ORDER:
        pick = next(((j, s, p) for j, (s, p) in enumerate(sents) if j not in used), None)
        if pick:
            used.add(pick[0])
            panels.append({'id': f'P{len(panels) + 1}', 'role': role, 'heading': role.title(), 'items': [{'id': f'P{len(panels) + 1}-I1', 'kind': 'text', 'detail': pick[1], 'evidence': {'source': pick[2]['source'], 'locator': pick[2]['locator'], 'quote': pick[1]}}]})
    title = fold_ws(seek_key(case, ('title', 'case_title', 'paper_title'))) or next((l.strip('# ').strip() for l in (task_text or '').splitlines() if l.strip().startswith('#')), '')
    return {'title': title[:140] or 'Graphical abstract', 'panels': panels or [{'id': 'P1', 'role': 'other', 'heading': 'Note', 'items': [{'id': 'P1-I1', 'kind': 'text', 'label': 'No usable text material', 'detail': 'No quotable sentence was supplied, so nothing was asserted.'}]}], 'subtitle': 'Auto-extracted fallback figure - quotes are verbatim, curation is minimal.', 'caption': 'Fallback build: text is quoted from the supplied material; see content_map.json.'}

def map_contract(contract, bundle):
    keys = list(contract.keys()) if isinstance(contract, dict) else [str(k) for k in contract or []]
    out, um = ({}, [])
    for k in keys:
        kl, best, score = (str(k).lower(), None, 0)
        for canon, words in FIELD_HINTS:
            s = sum((1 for w in words if w in kl))
            if s > score and bundle.get(canon) is not None:
                best, score = (canon, s)
        out[k] = bundle.get(best) if best else None
        if best is None:
            um.append(str(k))
    return (out, um)

def emit_result(out, index, contract, bundle, status, errors, downs, changes, t0=None):
    filled, um = map_contract(contract, bundle)
    res = dict(filled)
    for k in ('editable_source', 'export_artifact', 'content_map', 'compliance_checks', 'exceptions', 'figure_caption'):
        res.setdefault(k, bundle.get(k))
    res.update({'case_id': index.get('case_id'), 'status': status, 'sources': bundle.get('sources') or [], 'uncertainty': bundle.get('uncertainty') or [], 'pending_human': bundle.get('pending_human') or [], 'errors': errors, 'degradations': downs, 'changes': changes, 'runtime': {'tool': 'scripts/main.py', 'python': sys.version.split()[0], 'offline': True, 'cwd_independent': True, 'elapsed_s': round(time.time() - t0, 2) if t0 else None, 'unmatched_contract_fields': um}})
    dump_json(Path(out) / 'result.json', res)
    return res

def prepare_index(ind, work, failures):
    if (Path(work) / 'index.json').is_file():
        try:
            i = read_json(Path(work) / 'index.json')
            if i.get('paragraphs'):
                return i
        except Exception as e:
            failures.append(f'index.json unreadable: {e}')
    c = read_case_files(ind)
    failures.extend(c['errors'])
    i = scan_materials(ind)
    i['input_error'] = bool(c['errors'])
    cc = c['case'] if isinstance(c['case'], dict) else {}
    i['case_id'] = next((str(cc[k]) for k in ('case_id', 'caseId', 'case_name', 'id') if k in cc), None) or (Path(c['case_path']).stem if c['case_path'] else None)
    i['contract'], i['case'] = (seek_key(c['case'], CONTRACT_ALIASES) or {}, c)
    dump_json(Path(work) / 'index.json', i)
    return i

def run_init(a):
    t0, work, out = (time.time(), Path(a.work), Path(a.output))
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    failures = []
    catalog = prepare_index(a.input, work, failures)
    cc = catalog['case'].get('case') or {}
    emit_result(out, catalog, catalog['contract'], {'sources': []}, 'partial', failures, ['result.json written before any figure exists (init step)'], [{'what': 'indexed input', 'detail': f"{len(catalog['materials'])} material(s), {len(catalog['paragraphs'])} paragraph(s)"}], t0)
    print(f"scan: case={catalog['case_id']} contract_keys={len(catalog['contract'])} work={work} output={out}")
    v = seek_key(cc, ('organizer_workorder', 'organizer_edit_workorder', 'task_instruction', 'instruction', 'scope'))
    if v:
        print('[init] workorder:', fold_ws(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))[:700])
    for m in catalog['materials']:
        print(f"   {m['sid']:>3} {m['kind']:<9} {m['bytes']:>9}B chunks={m['chunks']:<4} {m['name']}  / {m['method']}")
    for p in catalog['paragraphs'][:8]:
        print(f"   <{p['sid']}> {p['source']} @ {p['locator']} | {fold_ws(p['text'])[:170]}")
    print(f"[init] paragraphs={len(catalog['paragraphs'])}; NEXT: write work/plan.json (see SKILL.md 7), then check, build")
    return 0

def run_show(a):
    catalog = read_json(Path(a.work) / 'index.json')
    ps = catalog.get('paragraphs') or []
    if a.sid:
        ps = [p for p in ps if a.sid in (p['sid'], p['source'])]
    if a.grep:
        ps = [p for p in ps if compact_key(a.grep) in compact_key(p['text'])]
    print(f'[show] {len(ps)} para; ' + ', '.join((f"{m['sid']}={m['name']}" for m in catalog.get('materials') or [])))
    for p in ps[:int(a.limit)]:
        print(f"--- [{p['sid']}] {p['source']} at {p['locator']}\n{fold_ws(p['text'])[:int(a.chars)]}")
    return 0

def run_check(a):
    work = Path(a.work)
    try:
        plan = read_json(work / 'plan.json')
        assert isinstance(plan, dict)
    except Exception as e:
        msg = f'work/plan.json missing or invalid: {e}'
        print('check: FAIL -', msg)
        dump_json(work / 'check.json', {'ok': False, 'problems': [msg]})
        return 0
    n, ok, faults = audit_items(plan, read_json(work / 'index.json').get('paragraphs') or [])
    if not fold_ws(plan.get('title')):
        faults.append('title is empty')
    roles = {kit.canonical_role(p.get('role') or p.get('heading')) for p in plan.get('panels') or [] if isinstance(p, dict)} if kit else set()
    faults += [f'missing panel role: {r} (problem -> method -> results -> implication)' for r in ROLE_ORDER if r not in roles]
    if not n:
        faults.append('no items: each panel needs items[] with evidence')
    rep = {'ok': not faults, 'problems': faults, 'stats': {'panels': len(plan.get('panels') or []), 'items': n, 'verified': ok, 'coverage': round(ok / n, 3) if n else 0.0, 'roles': sorted(roles)}}
    dump_json(work / 'check.json', rep)
    print(f"audit summary: panels={rep['stats']['panels']} items={n} verified={ok} coverage={rep['stats']['coverage']} -> {('PASS' if not faults else 'NEEDS DEFAULT_WORK')}")
    for x in faults:
        print('  -', x)
    print('next:', 'run build' if not faults else 'repair the FAIL items, re-run check')
    return 0

def render_bundle(plan, out, failures, downs):
    if kit is None:
        failures.append(f'renderer import failed: {KIT_ERR}')
        return (None, {}, None)
    try:
        model = kit.compose_figure(plan)
        svg, pdf, pngp = (out / 'graphical_abstract.svg', out / 'graphical_abstract.pdf', out / 'graphical_abstract.png')
        svg.write_text(kit.emit_svg(model), encoding='utf-8')
        pdf.write_bytes(kit.emit_pdf(model))
    except Exception as e:
        failures.append(f'render failed: {e}')
        return (None, {}, None)
    files, png = ({'svg': svg, 'pdf': pdf}, None)
    ok, method, note = kit.emit_png(model, str(pngp))
    if not ok and shutil.which('pdftoppm'):
        try:
            subprocess.run(['pdftoppm', '-png', '-r', '150', '-singlefile', str(pdf), str(pngp.with_suffix(''))], check=True, timeout=180)
            ok, method = (True, 'pdftoppm from the vector PDF')
        except Exception as e:
            note += f' | pdftoppm: {e}'
    if ok and pngp.is_file():
        files['png'] = pngp
        d = pngp.read_bytes()[16:24]
        png = {'path': 'graphical_abstract.png', 'method': method, 'note': note, 'px': [int.from_bytes(d[:4], 'big'), int.from_bytes(d[4:], 'big')]}
    else:
        downs.append(f'PNG preview unavailable ({note}); the vector PDF is the export artifact')
    return (model, files, png)

def compliance_report(model, files, png, plan, ok, n):
    st, pal = ((model or {}).get('stats') or {}, ['#D55E00', '#0072B2', '#009E73', '#CC79A7'])
    w, h = (kit.CANVAS_W, kit.CANVAS_H) if kit else (None, None)
    return {'canvas_px': [w, h], 'min_font': st.get('min_font'), 'inside_canvas': (st.get('max_y') or 0) <= (h or 760), 'text_nodes': st.get('text_ops'), 'overflow_dropped': len((model or {}).get('dropped') or []), 'svg': {'path': 'graphical_abstract.svg' if 'svg' in files else None, 'vector': True, 'editable_text': True, 'layers': kit.LAYER_ORDER if kit else None}, 'pdf': {'path': 'graphical_abstract.pdf' if 'pdf' in files else None, 'pages': 1, 'vector': True, 'page_pt': [round(w * kit.PT_SCALE, 1), round(h * kit.PT_SCALE, 1)] if kit else None, 'fonts': 'Helvetica base-14 + STSong-Light CID', 'embedded': False}, 'png': png, 'palette': {'scheme': 'Okabe-Ito subset', 'values': pal, 'cvd_safe': True, 'colour_redundant': 'panel headers name each role'}, 'coverage': round(ok / n, 3) if n else 0.0, 'bytes': {k: x.stat().st_size for k, x in files.items()}}

def run_build(a):
    t0, work, out = (time.time(), Path(a.work), Path(a.output))
    for d in (work, out):
        d.mkdir(parents=True, exist_ok=True)
    failures, downs, exc, status = ([], [], [], 'ok')
    catalog = prepare_index(a.input, work, failures)
    contract, chunks = (catalog.get('contract') or {}, catalog.get('paragraphs') or [])
    try:
        plan = read_json(work / 'plan.json')
        assert isinstance(plan, dict)
    except Exception as e:
        plan = salvage_plan(catalog, catalog['case'].get('case') or {}, catalog['case'].get('task_text'))
        downs.append(f'plan.json missing/invalid ({e}): auto-extracted from verbatim sentences')
        exc.append({'code': 'plan_missing', 'detail': str(e), 'action': 'deterministic fallback'})
        status = 'partial'
    n, ok, faults = audit_items(plan, chunks)
    proofs = {it['_eid']: it['_m'] for pn in plan.get('panels') or [] if isinstance(pn, dict) for it in pn.get('items') or []}
    for pi, pn in enumerate(plan.get('panels') or []):
        if not isinstance(pn, dict):
            continue
        survivors = [dict(it, id=it['_eid']) for it in pn.get('items') or [] if (it.get('_m') or {}).get('status') in ('verified', 'relocated')]
        for it in pn.get('items') or []:
            m = it.get('_m') or {}
            if m.get('status') == 'relocated':
                exc.append({'code': 'locator_corrected', 'detail': f"{it['_eid']}: {m['note']}", 'action': f"cite {m['locator']}"})
            elif m.get('status') not in ('verified', 'relocated'):
                exc.append({'code': 'element_dropped', 'detail': f"{it['_eid']}: {m.get('status')} {m.get('note')}", 'action': 'removed; add a verbatim quote and rebuild'})
        if not survivors:
            downs.append(f"panel {pn.get('id') or pi + 1}: no verified evidence (placeholder box)")
            status = 'partial'
        pn['items'] = survivors or [{'id': f'P{pi + 1}-note', 'kind': 'text', 'label': 'No verified evidence', 'detail': 'Panel left empty: no supplied passage could be quoted verbatim.'}]
    model, files, png = render_bundle(plan, out, failures, downs)
    status = 'partial' if not model else status
    if (model or {}).get('dropped'):
        downs.append(f"{len(model['dropped'])} item(s) dropped for vertical overflow")
        status = 'partial' if status == 'ok' else status
    atlas = [{'element_id': el['id'], 'panel': el['panel'], 'role': el['role'], 'text': el['text'], 'svg_id': f"#{el['id']}", 'bbox': el['bbox'], 'evidence': {k: (proofs.get(el['id']) or {}).get(k) for k in ('source', 'locator', 'quote', 'status')}} for el in (model or {}).get('elements') or []]
    audit = compliance_report(model, files, png, plan, ok, n)
    dump_json(out / 'content_map.json', atlas)
    dump_json(out / 'compliance_checks.json', audit)
    doubts = []
    if n and ok < n:
        doubts.append(f'{n - ok} of {n} element(s) dropped: quote not found in the material')
        status = 'partial' if status == 'ok' else status
    if not chunks:
        status = 'input_error' if catalog.get('input_error') else 'insufficient_evidence'
        doubts.append('no parseable material under /input; nothing scientific was asserted')
    bundle = {'sources': [{'id': m['sid'], 'name': m['name'], 'kind': m['kind'], 'sha1': m['sha1'], 'paragraphs': m['chunks']} for m in catalog.get('materials') or []], 'editable_source': 'graphical_abstract.svg' if model else None, 'export_artifact': {'pdf': 'graphical_abstract.pdf', 'png': png['path'] if png else None, 'pages': 1} if model else None, 'content_map': atlas, 'compliance_checks': audit, 'exceptions': exc, 'figure_caption': plan.get('caption') or plan.get('subtitle') or plan.get('title'), 'uncertainty': doubts, 'pending_human': [x['detail'] for x in exc if x['code'] == 'element_dropped']}
    emit_result(out, catalog, contract, bundle, status, failures, downs, [{'what': 'figure built', 'detail': f"{len(atlas)} traced element(s), {len(plan.get('panels') or [])} panel(s)"}, {'what': 'exports', 'detail': ', '.join(sorted(files)) or 'none'}, {'what': 'evidence', 'detail': 'each element: source + locator + verbatim quote; drops listed in exceptions'}], t0)
    print(f"build summary: status={status} elements={len(atlas)} rejected={n - ok} files={{{', '.join((f'{k}:{v.stat().st_size}B' for k, v in files.items()))}}}")
    for x in failures + downs:
        print('  note:', x)
    return 0

def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    for k in ('input', 'work', 'output'):
        common.add_argument('--' + k, default=None)
    ap = argparse.ArgumentParser(prog='main.py', description='evidence-first graphical abstract workbench')
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('init', parents=[common], help='scan inputs, write index.json plus a partial result.json')
    sh = sub.add_parser('show', parents=[common], help='print indexed paragraphs with locators')
    for k, dv in (('sid', ''), ('grep', ''), ('limit', 40), ('chars', 600)):
        sh.add_argument('--' + k, default=dv)
    sub.add_parser('check', parents=[common], help='audit work/plan.json: roles, evidence, coverage')
    sub.add_parser('build', parents=[common], help='render SVG/PDF/PNG exports and finalise result.json')
    a = ap.parse_args(argv)
    a.input, a.work, a.output = (a.input or DEFAULT_INPUT, a.work or DEFAULT_WORK, a.output or DEFAULT_OUTPUT)
    cmd = a.cmd or 'init'
    try:
        return {'init': run_init, 'show': run_show, 'check': run_check, 'build': run_build}[cmd](a)
    except SystemExit:
        return 0
    except Exception:
        tb = traceback.format_exc()
        try:
            Path(a.output).mkdir(parents=True, exist_ok=True)
            catalog = read_json(Path(a.work) / 'index.json') if (Path(a.work) / 'index.json').is_file() else {'case_id': None}
            emit_result(Path(a.output), catalog, catalog.get('contract') or {}, {'sources': []}, 'partial', [f'{cmd} crashed: {tb.splitlines()[-1]}'], [tb[-900:]], [], time.time())
        except Exception:
            pass
        print(f'[{cmd}] failed, result.json finalised:\n{tb}')
        return 0
if __name__ == '__main__':
    sys.exit(main())
