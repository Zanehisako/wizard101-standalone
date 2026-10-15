#!/usr/bin/env python3
"""Build, capture and inspect bounded game-side Windows-context samples."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'game'))
from pe_identity import PEIdentity

APP = Path.home()/'Desktop/Wizard101 Optimizations.app'
DATA = Path.home()/'Library/Application Support/Wizard101 Optimizations/Data'
EXPECTED = '544ab726ef7b920a5ccb67aa3d06b245db7e0012317d2fe7856d58c17c31cf7e'
GAME = Path('Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin/WizardGraphicalClient.exe')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(work):
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    output = work/'context_sampler.exe'
    subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-static', '-Wall', '-Wextra',
                    str(ROOT/'game/context_sampler.c'), '-ldbghelp', '-lbcrypt', '-o', str(output)], check=True)
    return output


def wine_environment(runtime, data):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('W101_', 'WINE', 'DYLD_', 'DXVK_', 'D9VK_', 'VK_', 'MVK_', 'CX_', 'CROSSOVER'))}
    env.update(WINEPREFIX=str(Path(data).resolve()/'Prefix'), WINEARCH='win64', WINEDEBUG='-all',
               WINEMSYNC='1', WINEDLLPATH=str(runtime/'lib/wine'),
               DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib')
    return env


def analyze(path, exe):
    path = Path(path)
    if path.stat().st_size > 4*1024**2:
        raise ValueError('Sample exceeds the 4 MiB evidence budget')
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if len(rows) < 2 or rows[0].get('kind') != 'session' or rows[-1].get('kind') != 'end':
        raise ValueError('Incomplete sample; no attribution')
    session, end = rows[0], rows[-1]
    pe = PEIdentity(exe)
    if session.get('executable_sha256') != pe.sha256:
        raise ValueError('Sample and executable identities differ')
    if not session.get('diagnostic_only') or end.get('resume_failed'):
        raise ValueError('Invalid diagnostic or failed resumption')
    samples = [r for r in rows if r.get('kind') == 'sample']
    self_counts, inclusive_counts, verified = Counter(), Counter(), {}
    rejected = Counter()
    cpu = Counter()
    for sample in samples:
        cpu[sample['tid']] += sample['cpu_delta_100ns']/10
        if not sample.get('context_valid') or sample.get('previous_suspend_count') != 0:
            rejected['invalid_or_preexisting_suspension'] += 1
            continue
        seen = set()
        for index, frame in enumerate(sample['frames']):
            if frame['module'].lower() != Path(exe).name.lower():
                continue
            rva = frame['rva']-(1 if index else 0)
            identity = pe.function(rva)
            if not identity:
                rejected['no_runtime_function_identity'] += 1
                continue
            if frame.get('function_rva') != identity['begin_rva'] or frame.get('signature') != identity['signature']:
                rejected['unverified_function_signature'] += 1
                continue
            key = (sample['tid'], identity['begin_rva'])
            verified[key] = identity
            if index == 0:
                self_counts[key] += 1
            if key not in seen:
                inclusive_counts[key] += 1
                seen.add(key)
    leads = [dict(tid=key[0], **verified[key], self_samples=self_counts[key], inclusive_samples=count)
             for key, count in inclusive_counts.most_common(30)]
    self_leads = [dict(tid=key[0], **verified[key], self_samples=count, inclusive_samples=inclusive_counts[key])
                 for key, count in self_counts.most_common(30)]
    cpu_valid = session.get('cpu_clock_observed_advancing') is True and any(cpu.values())
    return dict(schema=1, diagnostic_only=True, executable_sha256=pe.sha256,
                sample_sha256=sha(path), sample_completed=end.get('completed') is True,
                context_samples=len(samples), rejected=dict(rejected), threads_cpu_us=dict(cpu) if cpu_valid else None,
                cpu_clock_valid=bool(cpu_valid),
                max_suspension_us=max((r['suspension_us'] for r in samples), default=0),
                observed_game_function_leads=leads, observed_game_self_leads=self_leads,
                attribution_verified=False, selected_patch=None,
                limitation='Wall-clock context occupancy and interval CPU totals do not prove blocking work or its caller. Validate repeated live spans and disassembly before any patch. Scored gameplay excludes this diagnostic.')


def capture(app, data, work, output, seconds=5, tid=None):
    app, data, output = map(lambda p: Path(p).resolve(), (app, data, output))
    if output.exists():
        raise ValueError('Use a fresh evidence directory')
    if not 1 <= seconds <= 10:
        raise ValueError('Sampling is bounded to 1-10 seconds')
    exe = data/GAME
    pe = PEIdentity(exe)
    if pe.sha256 != EXPECTED:
        raise ValueError('Unapproved executable; original paths retained')
    runtime = app/'Contents/Resources/Runtime'
    helper = build(work)
    output.mkdir(parents=True)
    (output/'identity.json').write_text(json.dumps(pe.catalog(), indent=2)+'\n')
    args = [str(runtime/'bin/wine'), str(helper), '--expected', EXPECTED, '--seconds', str(seconds)]
    if tid is not None:
        args += ['--tid', str(tid)]
    # Never kill the helper on a Python timeout: it owns a suspension decrement.
    # Its watchdog resumes the sampled thread and its loop has an internal limit.
    with (output/'contexts.jsonl').open('x') as log, (output/'helper-error.txt').open('x') as errors:
        result = subprocess.run(args, env=wine_environment(runtime, data), stdout=log, stderr=errors)
    if result.returncode:
        raise RuntimeError(f'Sampling did not complete (exit {result.returncode}); inspect {output}/helper-error.txt')
    report = analyze(output/'contexts.jsonl', exe)
    report['helper_sha256'] = sha(helper)
    report['helper_source_sha256'] = sha(ROOT/'game/context_sampler.c')
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app', type=Path, default=APP)
    p.add_argument('--data', type=Path, default=DATA)
    p.add_argument('--work', type=Path, default=Path('/private/tmp/w101-game-side'))
    p.add_argument('--output', type=Path)
    p.add_argument('--seconds', type=int, default=5)
    p.add_argument('--tid', type=int)
    p.add_argument('--build-only', action='store_true')
    p.add_argument('--analyze', type=Path)
    args = p.parse_args()
    if args.build_only:
        print(build(args.work))
    elif args.analyze:
        print(json.dumps(analyze(args.analyze, args.data/GAME), indent=2))
    else:
        if args.output is None:
            p.error('Pass a fresh --output evidence directory')
        print(json.dumps(capture(args.app, args.data, args.work, args.output, args.seconds, args.tid), indent=2))
