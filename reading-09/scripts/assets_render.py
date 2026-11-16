#!/usr/bin/env python3
import json
import re
import sys
import time
from pathlib import Path
SKILL_NAME = 'repro-audit-runbook'
SKILL_VERSION = '1.1.0'
ASSET_NAMES = ('golden_standard.json', 'diff_report.md', 'version_history.md', 'run.log', 'self_check.json')


def clip(s, limit=240):
    one = re.sub(r'\s+', ' ', str(s if s is not None else '')).strip()
    return one if len(one) <= limit else one[:limit - 1].rstrip() + chr(8230)


def asset_sizes(out):
    sizes = {}
    for name in ASSET_NAMES:
        try:
            sizes[name] = (Path(out) / name).stat().st_size
        except Exception:
            sizes[name] = 0
    return sizes

SKILL_NAME = 'repro-audit-runbook'
SKILL_VERSION = '1.1.0'
ASSET_NAMES = ('golden_standard.json', 'diff_report.md', 'version_history.md', 'run.log', 'self_check.json')
VERSIONS = (('v0.0.1', 'skeleton', 'SKILL.md frontmatter + `cli.py --help`', 'prove the package loads', 'delete the two files'), ('v0.1.0', 'index and band', '`init`: index with locators, `tolerance_plan.json` (`before_any_run=true`), partial `result.json`', 'read before answering; freeze the band first', 'skip `init`; `build` builds a plan at its own start'), ('v0.2.0', 'draft gate', '`show` + `check`: verbatim quotes, enums, widening rejection, `check_report.json`', 'separate reading from arithmetic', 'stop calling `check`; `build` still validates quotes'), ('v0.3.0', 'execution', '`build`: candidate discovery, isolated subprocess runs, metric parsing, deviation arithmetic, attribution, verdict', 'numbers must be observed', 'run the candidates by hand and fill `runs`'), ('v0.4.0', 'degradation and budget', '`doctor`, degradation table, 780 s soft deadline, partial first, exit 0', 'a broken material or timeout must not yield an empty delivery', 'remove the deadline guard in `pipeline.py` and the top-level try/except'), ('v0.5.0', 'format coverage and contract echo', 'PDF/DOCX/XLSX/CSV/JSON extraction; semantic backfill of any `output_contract` shape, unmapped keys reported', 'hidden cases mix formats and templates', 'unknown contract keys stay `null` and are reported in `degradations`'), ('v1.0.0', 'first submitted package', '8 files / 99,263 B: `result.json` + `reproduction.json` + `reproduction.md`, contract echoed key for key', 'baseline delivery on hidden cases', 'restore the whole package from `work/patch_backup/reading-09_orig`'), ('v1.1.0', 'evidence assets (this patch)', 'five replayable assets at the end of `build` (`golden_standard.json`, `diff_report.md`, `version_history.md`, `run.log`, `self_check.json`) + their summary keys in `result.json`; `scripts/assets.py` keeps the real log lines for `run.log`', 'completeness/replayability needs a per-item ledger, a real diff and machine self-checks', 'copy `SKILL.md` and `scripts/pipeline.py` from `work/patch_backup/reading-09_orig`, delete `scripts/assets.py` and the five emitted files, rerun `build`; identical to v1.0.0'))

def render_diff(ctx):
    diff = ctx.diff or build_diff(ctx)
    nid = '`%s`' % (ctx.case_id if ctx.case_id is not None else 'null')
    lines = ['# Reproduction diff report', '', '- case_id: %s | status: `%s` | verdict: `%s`' % (nid, ctx.status, ctx.verdict), '- golden standard: `golden_standard.json` (%d items, %d quote checks)' % (ctx.golden['summary']['items'], ctx.golden['summary']['quotes']), '- produced at build/finalize by `scripts/assets.py` (skill v%s)' % SKILL_VERSION, '', '## 0. Summary', '', '| section | items | met | deviation | missing | verdict |', '|---|---|---|---|---|---|']
    for sec in diff['sections']:
        verdict = 'ok' if sec['deviation'] == 0 and sec['missing'] == 0 else 'gap'
        lines.append('| %s | %d | %d | %d | %d | %s |' % (sec['name'], len(sec['items']), sec['met'], sec['deviation'], sec['missing'], verdict))
    lines += ['', '- **total: %d items; met %d / deviation %d / missing %d**' % (diff['items'], diff['met'], diff['deviation'], diff['missing']), '']
    for idx, sec in enumerate(diff['sections'], 1):
        lines += ['## %d. %s' % (idx, sec['title']), '', '- tally: met %d / deviation %d / missing %d' % (sec['met'], sec['deviation'], sec['missing']), '', '| item | golden | actual | status | note |', '|---|---|---|---|---|']
        for entry in sec['items']:
            lines.append('| %s | %s | %s | %s | %s |' % (entry['id'], entry['golden'].replace('|', '\\|'), entry['actual'].replace('|', '\\|'), entry['status'], entry['note'].replace('|', '\\|')))
        lines.append('')
    lines += ['## %d. Tolerance and attribution' % (len(diff['sections']) + 1), '', 'Tolerance is frozen by `init`; every observation is judged against that persisted plan and the band is never widened after the run.', '', '| metric | reported | abs_tol | rel_tol | observed | deviation | verdict |', '|---|---|---|---|---|---|---|']
    for row in ctx.rows:
        lines.append('| %s | %s | %s | %s | %s | %s | %s |' % (row.get('metric'), row.get('reported'), row.get('abs_tol'), row.get('rel_tol'), row.get('observed'), row.get('rel_dev'), row.get('verdict')))
    if not ctx.rows:
        lines.append('| - | - | - | - | - | - | no comparison row |')
    lines += ['', '| metric | expected cause | why | observed causes |', '|---|---|---|---|']
    for item in ctx.golden['attribution']['items'] if ctx.golden else []:
        lines.append('| %s | `%s` | %s | %s |' % (item['metric'], item['expected_cause'], item['expected_why'], ', '.join(('`%s`' % c for c in item['observed_causes'])) or 'none'))
    lines += ['', '## %d. Replay' % (len(diff['sections']) + 2), '', '1. `python3 -B scripts/cli.py init --input /input --output /app/output --work /app/work` -- re-freeze the band and index the materials.', '2. `python3 -B scripts/cli.py build --input /input --output /app/output --work /app/work` -- re-run every candidate; compare `runs[*].command`, `exit_code`, `metrics` and `stdout_tail`.', '3. `python3 -B scripts/cli.py doctor --input /input --output /app/output --work /app/work` -- re-audit the envelope, band and verdict coherence.', '4. Recompute `abs_dev`/`rel_dev` from this table; the verdict must stay `%s`.' % (ctx.verdict,), '']
    return '\n'.join(lines)

def render_version_history(ctx):
    lines = ['# Version history - repro-audit kit (SKILL `%s`)' % SKILL_NAME, '', 'Static ledger of the package itself (v0.0.1 -> v1.1.0) followed by a deterministic section appended by the current `build` run. Each row states what changed, why, and how to roll back.', '', '| version | theme | what changed | why | rollback |', '|---|---|---|---|---|']
    for version, theme, change, why, rollback in VERSIONS:
        lines.append('| `%s` | %s | %s | %s | %s |' % (version, theme, change, why, rollback))
    lines += ['', '## Compatibility promise', '', '- Entry point unchanged: `python3 -B scripts/cli.py init|show|check|build|doctor`; defaults `/input`, `/app/output`, `/app/work`; `--input/--output/--work` still override.', '- Contract echo and the original artefacts untouched; v1.1.0 only *adds* five files and summary keys, emitted by the same `build` call.', '- If `scripts/assets.py` is missing or raises, `build` records one degradation, still writes every v1.0.0 artefact and exits 0.', '- `run.log` is the only asset with wall-clock timestamps.', '', '## Rollback in one command each', '', '1. Restore the whole v1.0.0 package: `work/patch_backup/reading-09_v2`.', '2. Stop emitting the assets: remove the `assets.finalize` call at the end of `pipeline.do_build` and delete the five files.', '3. Keep `run.log` only: delete `golden_standard.json`, `diff_report.md`, `self_check.json`; stale summary keys are ignored.', '4. Per asset: every file names its producer (`skill.version=%s`), so a stale asset is detectable after a downgrade.' % SKILL_VERSION, '', '## Current run (appended by build/finalize)', '', 'Deterministic for the same input; no timestamp is recorded here (wall-clock facts live in `run.log`).', '', '| field | value |', '|---|---|', '| case_id | `%s` |' % (ctx.case_id,), '| status | `%s` |' % (ctx.status,), '| verdict | `%s` |' % (ctx.verdict,), '| materials / runs | `%d / %d` |' % (len(ctx.materials), len(ctx.runs)), '| comparison rows | `%d` |' % len(ctx.rows), '| claims | `%d` |' % len(ctx.record.get('claims') or []), '| params | `%d` |' % len(ctx.record.get('params') or []), '| skill version | `%s` |' % SKILL_VERSION, '', '| asset | bytes | items | note |', '|---|---:|---:|---|']
    golden = ctx.golden or {}
    diff = ctx.diff or {}
    sizes = asset_sizes(ctx.out)
    lines += ['| `golden_standard.json` | %d | %d | per-item locator + verbatim quote ledger |' % (sizes.get('golden_standard.json', 0), (golden.get('summary') or {}).get('items', 0)), '| `diff_report.md` | %d | %d | actual artefacts vs golden_standard.json, item by item |' % (sizes.get('diff_report.md', 0), (diff or {}).get('items', 0)), '| `version_history.md` | - | %d | this file; a file cannot store its own byte count |' % len(VERSIONS), '| `run.log` | %d | - | real phases, candidate commands/exit codes/metrics, degradations |' % sizes.get('run.log', 0), '']
    return '\n'.join(lines)

def _ts(offset=0.0):
    return time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(time.time() + offset))

def render_run_log(ctx, log_lines, stages):
    header = ['# repro-audit run log', '# skill: %s v%s' % (SKILL_NAME, SKILL_VERSION), '# case_id: %s' % (ctx.case_id,), '# generated_at: %s' % _ts(), '# command: python3 -B scripts/cli.py build', '# python: %s' % sys.version.split()[0], '# platform: %s' % getattr(__import__('platform'), 'platform')(), '# input: %s' % ctx.inp, '# output: %s' % ctx.out, '# work: %s' % ctx.work, '# timestamps: wall clock of this process; relative order is real', '']
    body = []
    stamp = _ts()
    for line in log_lines or []:
        body.append('[%s] %s' % (stamp, line))
    body += ['', '# ---- candidates (real subprocess runs) ----']
    for run in ctx.runs:
        body.append('[%s] run=%s exit=%s duration=%ss command=%s' % (stamp, run.get('name'), run.get('exit_code'), round(run.get('duration_s') or 0, 2), run.get('command')))
        body.append('           workdir=%s metrics=%s' % (run.get('workdir'), json.dumps(run.get('metrics') or {}, ensure_ascii=False)))
        if run.get('stdout_tail'):
            body.append('           stdout_tail=%s' % clip(run.get('stdout_tail'), 300))
        if run.get('stderr_tail'):
            body.append('           stderr_tail=%s' % clip(run.get('stderr_tail'), 200))
    if not ctx.runs:
        body.append('[%s] no candidate ran (see record.pending_human)' % stamp)
    body += ['', '# ---- assets ----']
    body += ['[%s] %s' % (stamp, s) for s in stages or []]
    degraded = ctx.record.get('degradations') or []
    pending = ctx.record.get('pending_human') or []
    if degraded or pending:
        body += ['', '# ---- degradations / pending_human ----']
        body += ['[%s] degradation=%s' % (stamp, d) for d in degraded]
        body += ['[%s] pending_human=%s' % (stamp, p) for p in pending]
    body.append('')
    return '\n'.join(header + body)
