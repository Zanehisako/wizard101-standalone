#!/usr/bin/env python3
"""Verify context identity, exact caller unwinding and suspension recovery in Wine."""
import argparse
import json
from pathlib import Path
import subprocess
import shutil
from game_context import APP, ROOT, build, sha, wine_environment, analyze


def verify(work, app, keep):
    work, app, keep = map(lambda p: Path(p).resolve(), (work, app, keep))
    if keep.exists():
        raise RuntimeError('Retain prior verification; use a fresh directory')
    keep.mkdir(parents=True)
    helper = build(work)
    target = work/'context_target.exe'
    subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-static', '-fno-optimize-sibling-calls',
                    str(ROOT/'tests/context_target.c'), '-o', str(target)], check=True)
    runtime = app/'Contents/Resources/Runtime'
    (work/'TestData').mkdir(exist_ok=True)
    env = wine_environment(runtime, work/'TestData')
    env['WINEDLLOVERRIDES'] = 'winemenubuilder.exe=d'
    # Only the disposable prefix is initialized. No copy of game content is required.
    with (keep/'wineboot.txt').open('w') as log:
        subprocess.run([str(runtime/'bin/wine'), 'wineboot.exe', '-u'], env=env, stdout=log, stderr=log, check=True, timeout=60)
    checks = {}
    error_log = (keep/'target-error.txt').open('w')
    child = subprocess.Popen([str(runtime/'bin/wine'), str(target)], env=env, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=error_log, text=True, bufsize=1)
    try:
        identity = json.loads(child.stdout.readline())
        def command(value):
            child.stdin.write(value+'\n'); child.stdin.flush()
            return child.stdout.readline().strip()
        def run(label, fault=None, expected=None):
            args = [str(runtime/'bin/wine'), str(helper), '--test-target', '--pid', str(identity['pid']),
                    '--tid', str(identity['tid']), '--expected', expected or sha(target), '--seconds', '1']
            if fault:
                args += ['--fault', fault]
            with (keep/(label+'.jsonl')).open('w') as log, (keep/(label+'-error.txt')).open('w') as errors:
                result = subprocess.run(args, env=env, stdout=log, stderr=errors)
            path = keep/(label+'.jsonl')
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            return result.returncode, rows, path
        code, rows, path = run('known-stack')
        report = analyze(path, target)
        normal_rows = rows
        leaf = identity['leaf']-identity['base']; parent = identity['parent']-identity['base']
        checks['known_instruction_pointer'] = code == 0 and any(r.get('frames') and r['frames'][0].get('function_rva') == leaf for r in rows)
        checks['known_exact_caller'] = any(any(f.get('function_rva') == parent for f in r.get('frames', [])[1:]) for r in rows)
        checks['signed_function_identity'] = any(l['begin_rva'] == leaf for l in report['observed_game_function_leads'])
        checks['normal_resumption'] = command('alive') == 'ALIVE 1'
        checks['normal_suspend_budget'] = report['max_suspension_us'] < 100000
        for fault in ('context', 'read', 'timeout'):
            code, rows, _ = run(fault, fault)
            end = rows[-1] if rows else {}
            checks[fault+'_resumption'] = command('alive') == 'ALIVE 1' and not end.get('resume_failed', True)
            checks[fault+'_record'] = (code == 11 and end.get('cancelled') is True) if fault == 'timeout' else code == 0
        checks['preexisting_suspend'] = command('suspend') == 'SUSPEND 0'
        code, rows, _ = run('already-suspended')
        checks['suspend_count_retained'] = code == 0 and all(r['previous_suspend_count'] == 1 for r in rows if r.get('kind') == 'sample') and command('alive') == 'ALIVE 0'
        checks['other_owners_suspend_restored'] = command('resume') == 'RESUME 1' and command('alive') == 'ALIVE 1'
        code, rows, _ = run('wrong-hash', expected='0'*64)
        checks['hash_rejection_before_sampling'] = code == 5 and rows == [] and command('alive') == 'ALIVE 1'
        checks['no_raw_stack_or_credentials'] = all('stack' not in r and 'registers' not in r and 'arguments' not in r and 'path' not in r for r in normal_rows)
        (keep/'known-stack-report.json').write_text(json.dumps(report, indent=2)+'\n')
    finally:
        if child.poll() is None:
            child.stdin.write('exit\n'); child.stdin.flush(); child.wait(timeout=10)
        error_log.close()
        # This verifier owns only this disposable prefix; the game prefix is never initialized or updated.
        subprocess.run([str(runtime/'bin/wineserver'), '-k'], env=env, capture_output=True, timeout=10)
        shutil.rmtree(work/'TestData')
    result = dict(checks=checks, passed=all(checks.values()), helper_sha256=sha(helper),
                  target_sha256=sha(target), synthetic_only=True, game_function_attribution_verified=False,
                  patch_implemented=False, gameplay_accepted=False)
    (keep/'verification.json').write_text(json.dumps(result, indent=2)+'\n')
    if not result['passed']:
        raise RuntimeError('Context verification failed: '+', '.join(k for k, v in checks.items() if not v))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work', type=Path, default=Path('/private/tmp/w101-game-side'))
    p.add_argument('--app', type=Path, default=APP)
    p.add_argument('--keep', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(verify(a.work, a.app, a.keep), indent=2))
